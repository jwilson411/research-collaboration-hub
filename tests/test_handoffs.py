"""Immutable handoff integration checks using only loopback and synthetic state."""
import base64
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import uuid
import test_api as api


class Handoffs(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 5080)) == 0:
                raise RuntimeError('Stop the preview; handoff tests own loopback port 5080')
        subprocess.run([api.DOTNET, 'build', '--no-incremental', '--nologo'], cwd=api.ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix='hub-handoffs-')
        cls.data = Path(cls.temp.name) / 'hub.json'
        cls.blobs = Path(cls.temp.name) / 'files'
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT='Development', HUB_DEMO_ENABLED='true',
                       HUB_DATA=str(cls.data), HUB_FILES=str(cls.blobs), HUB_DEMO_FILE_RELEASE='true')
        cls.log = open(Path(cls.temp.name) / 'server.log', 'w+')
        cls.start()

    def setUp(self):
        self.alex = api.Client().login('alex'); self.sam = api.Client().login('sam')
        self.admin = api.Client().login('admin'); self.lead = api.Client().login('lead')
        if self._testMethodName != 'test_a_seeded_journey_handoff_baseline':
            self.change('/protocol', dict(kind=None, id=None, reason='Isolate synthetic handoff test'))

    def study(self): return self.alex.request('/api/studies/atlas')[1]
    def change(self, suffix, payload, client=None):
        return (client or self.alex).request('/api/studies/atlas' + suffix,
            dict(payload, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))
    def item(self, kind='decision', body='Synthetic decision rationale', **extra):
        before = {i['id'] for i in self.study()['items']}
        status, study, _ = self.change('/items', dict(kind=kind, title='Synthetic ' + uuid.uuid4().hex[:8], body=body, **extra))
        self.assertEqual(status, 200, study)
        return next(i for i in study['items'] if i['id'] not in before)
    def file(self, content=b'Synthetic file version one', **extra):
        before = {f['id'] for f in self.study()['files']}
        status, study, _ = self.change('/files', dict(name='synthetic.txt', contentBase64=base64.b64encode(content).decode(), **extra))
        self.assertEqual(status, 200, study)
        return next(f for f in study['files'] if f['id'] not in before)
    def doc(self, body='Synthetic text version one', previous=None, files=None):
        before = {i['id'] for i in self.study()['items']}
        path = '/documents' if previous is None else f'/documents/{previous}/versions'
        status, study, _ = self.change(path, dict(title='Synthetic specification', body=body, fileIds=files or []))
        self.assertEqual(status, 200, study)
        return next(i for i in study['items'] if i['id'] not in before)
    def capture(self, items=None, files=None, **extra):
        payload = dict(title='Synthetic handoff', summary='A fixed coordination snapshot, not an external approval.',
                       itemIds=items, fileIds=files, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4()))
        payload.update(extra)
        result = self.alex.request('/api/studies/atlas/handoffs', payload)
        self.assertEqual(result[0], 200, result[1])
        return payload, result[1]
    def get(self, snapshot, client=None):
        return (client or self.alex).request('/api/studies/atlas/handoffs/' + snapshot['id'])

    def test_a_seeded_journey_handoff_baseline(self):
        # Read-only content check: no source edits or snapshot creation.
        before = self.data.read_bytes() if self.data.exists() else None
        status, snapshot, _ = self.alex.request('/api/studies/atlas/handoffs/journey-handoff')
        self.assertEqual(status, 200, snapshot)  # Detail GET verifies the stored capture digest.
        self.assertEqual(snapshot['id'], 'journey-handoff')
        self.assertRegex(snapshot['sha256'], r'^[0-9A-F]{64}$')
        self.assertFalse(snapshot['redacted'])
        captured = {entry['item']['id']: entry for entry in snapshot['items']}
        for source, expected_status, expected_version in [('journey-guide-v1', 'Superseded', 1), ('journey-guide-v2', 'Accepted', 2)]:
            entry = captured[source]
            self.assertTrue(entry['available'])
            self.assertEqual(entry['review']['status'], expected_status)
            self.assertEqual(entry['review']['history'][-1]['to'], expected_status)
            self.assertEqual(entry['item']['version'], expected_version)
            self.assertEqual(entry['item']['author'], 'alex')
        task = captured['journey-task']['item']
        self.assertEqual(task['task']['assignee'], 'reviewer')
        self.assertEqual(task['task']['status'], 'Open')
        self.assertEqual(task['author'], 'alex')
        self.assertEqual(captured['journey-question']['item']['author'], 'reviewer')
        self.assertEqual(captured['journey-decision']['item']['author'], 'lead')
        self.assertEqual(snapshot['createdBy'], 'lead')
        self.assertIn('2026-09-12T14:30:00', snapshot['createdAt'])
        self.assertEqual(self.data.read_bytes() if self.data.exists() else None, before)

    def test_access_csrf_bounds_and_hidden_storage(self):
        record = self.item()
        payload = dict(title='Synthetic boundary check', summary='', itemIds=[record['id']], fileIds=[],
                       expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4()))
        for client in (self.sam, self.admin):
            self.assertEqual(client.request('/api/studies/atlas/handoffs', payload)[0], 404)
            self.assertEqual(client.request('/api/studies/atlas/handoffs')[0], 404)
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs', payload, csrf=False)[0], 400)
        for change in [dict(title=''), dict(title='x'*181), dict(summary='x'*2001), dict(itemIds=[None]),
                       dict(itemIds=[record['id']]*2), dict(itemIds=['x']*51), dict(fileIds=['x']*31),
                       dict(itemIds=['beacon-protocol']), dict(fileIds=['not-a-file']), dict(itemIds=[],fileIds=[]),
                       dict(requestId='invalid')]:
            bad = dict(payload, **change)
            self.assertEqual(self.alex.request('/api/studies/atlas/handoffs', bad)[0], 400, change)
        _, snapshot = self.capture([record['id']], [])
        for client in (self.sam, self.admin): self.assertEqual(self.get(snapshot, client)[0], 404)
        self.assertEqual(self.alex.request('/api/studies/beacon/handoffs/' + snapshot['id'])[0], 404)
        self.assertNotIn('handoffs', self.study())
        self.assertNotIn('handoffs', self.alex.request('/api/studies')[1][0])
        summaries = self.alex.request('/api/studies/atlas/handoffs')[1]
        summary = next(s for s in summaries if s['id'] == snapshot['id'])
        self.assertNotIn('items', summary); self.assertNotIn('content', summary)
        self.assertEqual(summary['itemCount'], 1)

    def test_exact_versions_reviews_tasks_and_protocol_are_immutable(self):
        file1 = self.file(); doc1 = self.doc(files=[file1['id']])
        self.assertEqual(self.change(f'/documents/{doc1["id"]}/state', dict(status='Review',reason='Synthetic peer review'))[0], 200)
        self.assertEqual(self.change(f'/documents/{doc1["id"]}/state', dict(status='Accepted',reason='Synthetic local acceptance'), self.lead)[0], 200)
        question = self.item('discussion', 'Synthetic open question')
        task_input = dict(title='Synthetic follow-up', body='Original task body', assignee='alex', dueDate='2026-12-01', status='Open', links=[doc1['id'],question['id']], fileLinks=[file1['id']])
        before = {i['id'] for i in self.study()['items']}
        result = self.change('/tasks', task_input); self.assertEqual(result[0],200)
        task = next(i for i in result[1]['items'] if i['id'] not in before)
        decision = self.item(documentId=doc1['id'], fileIds=[file1['id']])
        self.assertEqual(self.change('/protocol', dict(kind='item',id=doc1['id'],reason='Pin an exact accepted version'))[0],200)
        source_revision = self.study()['revision']
        _, snapshot = self.capture([task['id'],decision['id']], [])
        self.assertEqual(snapshot['sourceRevision'], source_revision)
        self.assertEqual(snapshot['currentProtocol']['id'], doc1['id']); self.assertTrue(snapshot['protocolAvailable'])
        captures = {r['item']['id']: r for r in snapshot['items']}
        self.assertEqual(captures[doc1['id']]['item']['body'], doc1['body'])
        self.assertEqual(captures[doc1['id']]['review']['status'], 'Accepted')
        self.assertEqual(captures[task['id']]['item']['task']['assignee'], 'alex')
        self.assertEqual(captures[task['id']]['item']['task']['history'], [])
        self.assertEqual(next(f['file'] for f in snapshot['files'] if f['file']['id']==file1['id'])['sha256'], file1['sha256'])
        file2 = self.file(b'Synthetic file version two', documentId=file1['id'])
        doc2 = self.doc('Synthetic text version two', previous=doc1['id'], files=[file2['id']])
        self.assertEqual(self.change(f'/tasks/{task["id"]}', dict(task_input,body='Changed current task body',status='Done',links=[doc2['id']],fileLinks=[file2['id']]))[0],200)
        self.assertEqual(self.change('/protocol',dict(kind='item',id=doc2['id'],reason='New exact working version'))[0],200)
        readback = self.get(snapshot)[1]
        self.assertEqual(readback, snapshot)
        self.assertEqual(len(snapshot['sha256']),64)
        self.assertIn('not a signature or approval',snapshot['digestScope'])

    def test_removal_redacts_projection_but_preserves_internal_capture_and_digest(self):
        marker = 'Synthetic removed rationale ' + uuid.uuid4().hex
        decision = self.item(body=marker)
        _, snapshot = self.capture([decision['id']], [])
        before = json.loads(self.data.read_text())
        original = next(h for s in before['studies'] if s['id']=='atlas' for h in s['handoffs'] if h['id']==snapshot['id'])
        self.assertEqual(self.change(f'/items/{decision["id"]}/delete', {})[0],200)
        redacted = self.get(snapshot)[1]
        self.assertTrue(redacted['redacted']); self.assertEqual(redacted['sha256'],snapshot['sha256'])
        self.assertNotIn(marker,json.dumps(redacted)); self.assertNotIn(marker,json.dumps(self.study()))
        hidden = next(r for r in redacted['items'] if r['item']['id']==decision['id'])
        self.assertFalse(hidden['available']); self.assertIsNone(hidden['item']['task']); self.assertIsNone(hidden['item']['provenance'])
        after = json.loads(self.data.read_text())
        stored = next(h for s in after['studies'] if s['id']=='atlas' for h in s['handoffs'] if h['id']==snapshot['id'])
        self.assertEqual(stored,original)
        self.assertIn(marker,json.dumps(stored))

    def test_file_removal_quarantine_and_tamper_never_bypass_current_download_checks(self):
        attachment = self.file()
        _, snapshot = self.capture([], [attachment['id']])
        path = self.blobs / (attachment['id'] + '.blob')
        original = path.read_bytes(); path.write_bytes(b'Synthetic tamper')
        try:
            self.assertTrue(self.get(snapshot)[1]['redacted'])
            self.assertFalse(self.get(snapshot)[1]['files'][0]['available'])
            self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{attachment["id"]}/download')[0],409)
            payload = dict(title='Unavailable',summary='',itemIds=[],fileIds=[attachment['id']],expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
            self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',payload)[0],400)
        finally: path.write_bytes(original)
        self.assertEqual(self.get(snapshot)[1],snapshot)
        self.assertEqual(self.change(f'/files/{attachment["id"]}/delete',{})[0],200)
        self.assertFalse(self.get(snapshot)[1]['files'][0]['available'])
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{attachment["id"]}/download')[0],404)

    def test_current_task_capture_omits_obsolete_history_evidence(self):
        attachment = self.file(); before={i['id'] for i in self.study()['items']}
        task_input=dict(title='Current-only task',body='First task state',assignee='alex',dueDate=None,status='Open',links=[],fileLinks=[attachment['id']])
        result=self.change('/tasks',task_input); self.assertEqual(result[0],200)
        task=next(i for i in result[1]['items'] if i['id'] not in before)
        self.assertEqual(self.change(f'/tasks/{task["id"]}',dict(task_input,body='Current task state',fileLinks=[]))[0],200)
        self.assertEqual(self.change(f'/files/{attachment["id"]}/delete',{})[0],200)
        _,snapshot=self.capture([task['id']],[])
        captured=next(r['item'] for r in snapshot['items'] if r['item']['id']==task['id'])
        self.assertEqual(captured['body'],'Current task state'); self.assertEqual(captured['version'],2)
        self.assertEqual(captured['task']['history'],[]); self.assertEqual(snapshot['files'],[])
        self.assertEqual(len(next(i for i in self.study()['items'] if i['id']==task['id'])['task']['history']),1)

    def test_imported_file_family_and_provenance_evidence_are_bundled(self):
        self.admin.config('/api/admin/role',dict(identity='alex',role='Administrator'))
        fixture=json.loads((api.ROOT/'fixtures/app-import.json').read_text())
        result=self.change('/imports/apply',dict(manifest=fixture)); self.assertEqual(result[0],200,result[1])
        mapped={o['sourceId']:o['targetId'] for o in result[1]['outcomes']}
        _,snapshot=self.capture([], [mapped['version-2']])
        self.assertIn(mapped['document-1'],[r['item']['id'] for r in snapshot['items']])
        version=next(f['file'] for f in snapshot['files'] if f['file']['id']==mapped['version-2'])
        self.assertEqual(version['provenance']['sourceId'],'version-2'); self.assertEqual(version['familyId'],mapped['document-1'])
        self.assertNotIn('original',version['provenance'])

    def test_lifecycle_replay_restart_and_revocation(self):
        record=self.item(); payload,snapshot=self.capture([record['id']],[])
        self.assertEqual(self.change('/stage',dict(stage='Closed'))[0],200)
        self.assertEqual(self.get(snapshot)[1],snapshot)
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',payload)[1],snapshot)
        fresh=dict(payload,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',fresh)[0],409)
        self.assertEqual(self.change('/stage',dict(stage='Active'))[0],200)
        self.stop(); self.start(); self.alex=api.Client().login('alex'); self.admin=api.Client().login('admin')
        self.assertEqual(self.get(snapshot)[1],snapshot)
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',payload)[1],snapshot)
        conflict=dict(payload,title='Different operation')
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',conflict)[0],409)
        stale=dict(payload,requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',stale)[0],409)
        self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))
        try:
            self.assertEqual(self.get(snapshot)[0],404)
            self.assertEqual(self.alex.request('/api/studies/atlas/handoffs',payload)[0],404)
        finally: self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))

    def test_z_integrity_and_release_policy_after_restart(self):
        attachment=self.file(); _,snapshot=self.capture([], [attachment['id']])
        self.stop(); self.env['HUB_DEMO_FILE_RELEASE']='false'; self.start(); self.alex=api.Client().login('alex')
        self.assertTrue(self.get(snapshot)[1]['redacted'])
        self.assertEqual(self.get(snapshot)[1]['sha256'],snapshot['sha256'])
        self.stop(); self.env['HUB_DEMO_FILE_RELEASE']='true'
        saved=self.data.read_bytes(); state=json.loads(saved)
        persisted=next(h for s in state['studies'] if s['id']=='atlas' for h in s['handoffs'] if h['id']==snapshot['id'])
        persisted['content']['studySummary']='Tampered synthetic capture'
        self.data.write_text(json.dumps(state)); self.start(); self.alex=api.Client().login('alex')
        try:
            response=self.get(snapshot)
            self.assertEqual(response[0],503); self.assertNotIn('Tampered synthetic capture',json.dumps(response[1]))
        finally:
            self.stop(); self.data.write_bytes(saved); self.start(); self.alex=api.Client().login('alex')
        self.assertEqual(self.get(snapshot)[1],snapshot)


if __name__=='__main__': unittest.main(verbosity=2)
