"""Connected synthetic import checks against a real loopback HTTP app; no source systems."""
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


class Ingestion(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 5080)) == 0:
                raise RuntimeError('Stop the preview; ingestion tests own loopback port 5080')
        subprocess.run([api.DOTNET, 'build', '--no-incremental', '--nologo'], cwd=api.ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix='hub-ingestion-')
        cls.data = Path(cls.temp.name) / 'hub.json'
        cls.blobs = Path(cls.temp.name) / 'files'
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT='Development', HUB_DEMO_ENABLED='true',
                       HUB_DATA=str(cls.data), HUB_FILES=str(cls.blobs), HUB_DEMO_FILE_RELEASE='true')
        cls.log = open(Path(cls.temp.name) / 'server.log', 'w+')
        cls.start()

    def setUp(self):
        self.admin = api.Client().login('admin')
        self.alex = api.Client().login('alex')
        self.sam = api.Client().login('sam')
        self.assertEqual(self.admin.config('/api/admin/role', {'identity': 'alex', 'role': 'Researcher'})[0], 200)
        self.manifest = json.loads((api.ROOT / 'fixtures/app-import.json').read_text())
        prefix = uuid.uuid4().hex[:12] + '-'
        for r in self.manifest['records']:
            r['source_id'] = prefix + r['source_id']
            if 'parent_id' in r: r['parent_id'] = prefix + r['parent_id']
            r['references'] = [prefix + ref for ref in r.get('references', [])]
        self.assertEqual(self.admin.config('/api/admin/role', {'identity': 'alex', 'role': 'Administrator'})[0], 200)

    def study(self): return self.alex.request('/api/studies/atlas')[1]
    def preview(self, manifest=None, client=None, **kwargs):
        return (client or self.alex).request('/api/studies/atlas/imports/preview', {'manifest': manifest or self.manifest}, **kwargs)
    def payload(self, manifest=None):
        return dict(manifest=manifest or self.manifest, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4()))
    def apply(self, manifest=None):
        payload = self.payload(manifest)
        status, report, _ = self.alex.request('/api/studies/atlas/imports/apply', payload)
        self.assertEqual(status, 200, report)
        return payload, report
    def target(self, report, suffix):
        return next(o['targetId'] for o in report['outcomes'] if o['sourceId'].endswith(suffix))

    def test_access_csrf_and_readonly_preview(self):
        before = self.study(); blobs = list(self.blobs.glob('*'))
        for client in (self.sam, self.admin):
            self.assertEqual(self.preview(client=client)[0], 404)
            self.assertEqual(client.request('/api/studies/atlas/imports')[0], 404)
            self.assertEqual(client.request('/api/studies/atlas/imports/apply', self.payload())[0], 404)
        self.assertEqual(self.preview(csrf=False)[0], 400)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', self.payload(), csrf=False)[0], 400)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/preview')[0], 405)
        status, report, _ = self.preview()
        self.assertEqual(status, 200); self.assertEqual(report['counts']['imported'], 7)
        self.assertFalse(report['applied']); self.assertEqual(self.study(), before)
        self.assertEqual(list(self.blobs.glob('*')), blobs)
        self.admin.config('/api/admin/role', {'identity': 'alex', 'role': 'Researcher'})
        self.assertEqual(self.preview()[0], 404)

    def test_fidelity_replay_restart_and_provenance(self):
        payload, report = self.apply()
        self.assertEqual(report['counts']['imported'], 7)
        study = self.study(); version = self.target(report, 'version-1'); reply = self.target(report, 'reply-1')
        self.assertNotIn('importLedger', study); self.assertNotIn('importReports', study)
        self.assertFalse(any(i['id'] == version for i in study['items']), 'versions must be file-only')
        files = {f['id']: f for f in study['files']}
        self.assertEqual(files[version]['version'], 1)
        self.assertEqual(files[version]['familyId'], self.target(report, 'document-1'))
        self.assertEqual(files[self.target(report, 'version-2')]['familyId'], files[version]['familyId'])
        self.assertEqual(files[self.target(report, 'attachment-1')]['parentId'], reply)
        original = self.manifest['records'][1]
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{version}/download')[1], base64.b64decode(original['content_base64']))
        item = next(i for i in study['items'] if i['id'] == reply)
        self.assertEqual(item['author'], 'former-member'); self.assertEqual(item['parentId'], self.target(report, 'thread-1'))
        self.assertNotIn('original', item['provenance'])
        decision = next(i for i in study['items'] if i['id'] == self.target(report, 'decision-1'))
        self.assertIn(self.target(report, 'version-2'), decision['fileIds'])
        self.assertIn(reply, decision['provenance']['referenceTargetIds'])
        self.assertEqual(self.alex.request('/api/session', {'identity': 'former-member'})[0], 400)
        self.assertEqual(self.sam.request(f'/api/studies/atlas/files/{version}/download')[0], 404)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', payload)[1], report)
        before = self.study(); self.stop(); self.start(); self.alex = api.Client().login('alex')
        self.assertEqual(self.study(), before)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', payload)[1], report)
        _, retried = self.apply(); self.assertEqual(retried['counts']['unchanged'], 7)

    def test_mapping_checksum_acl_and_unknown_author_quarantine(self):
        for field in ('group', 'acl', 'author', 'checksum'):
            batch = copy.deepcopy(self.manifest)
            if field == 'group': batch['studies']['synthetic-study'] = 'demo-group-b'
            elif field == 'acl': batch['records'][0]['acl']['principals'] = ['alex']
            elif field == 'author': batch['records'][0]['author_id'] = 'unresolved'
            else: batch['records'][1]['sha256'] = '0' * 64
            before = len(list(self.blobs.glob('*.blob')))
            status, report, _ = self.preview(batch)
            self.assertEqual(status, 200); self.assertGreater(report['counts']['quarantined'], 0)
            self.assertEqual(sum(report['counts'].values()), 7)
            self.assertEqual(len(list(self.blobs.glob('*.blob'))), before)
        batch = copy.deepcopy(self.manifest); batch['approved_group_ids'] = []
        _, report = self.apply(batch)
        self.assertEqual(report['counts']['quarantined'], 7)
        self.assertFalse(any(i.get('provenance', {}).get('sourceId', '').startswith(batch['records'][0]['source_id'][:12]) for i in self.study()['items'] if i.get('provenance')))

    def test_bad_types_duplicate_and_bounds_never_500(self):
        for value in ('one', None, {}, []):
            batch = copy.deepcopy(self.manifest); batch['schema'] = value
            self.assertEqual(self.preview(batch)[0], 400)
            batch = copy.deepcopy(self.manifest); batch['records'][0]['revision'] = value
            status, report, _ = self.preview(batch)
            self.assertEqual(status, 200); self.assertGreater(report['counts']['quarantined'], 0)
            batch = copy.deepcopy(self.manifest); batch['records'][1]['version_number'] = value
            self.assertEqual(self.preview(batch)[0], 200)
        for field in ('body', 'title', 'filename'):
            batch = copy.deepcopy(self.manifest); batch['records'][3][field] = {}
            self.assertEqual(self.preview(batch)[1]['counts']['quarantined'] > 0, True)
        batch = copy.deepcopy(self.manifest); batch['records'] *= 2
        self.assertEqual(self.preview(batch)[0], 400)
        batch['records'] *= 8
        self.assertEqual(self.preview(batch)[0], 400)
        batch = copy.deepcopy(self.manifest); batch['synthetic'] = False
        self.assertEqual(self.preview(batch)[0], 400)
        batch = copy.deepcopy(self.manifest); batch['records'][0]['body'] = 'x' * 910000
        self.assertIn(self.preview(batch)[0], (400, 413))

    def test_relationship_cycle_missing_parent_and_duplicate_versions(self):
        for mode in ('cycle', 'missing', 'duplicate'):
            batch = copy.deepcopy(self.manifest)
            if mode == 'cycle': batch['records'][4]['parent_id'] = batch['records'][4]['source_id']
            elif mode == 'missing': batch['records'][4]['parent_id'] = 'not-imported'
            else: batch['records'][2]['version_number'] = 1
            report = self.preview(batch)[1]
            self.assertGreater(report['counts']['quarantined'], 0)
        _, report = self.apply()
        batch = copy.deepcopy(self.manifest); batch['records'] = [batch['records'][1]]
        batch['records'][0]['source_id'] += '-duplicate'
        report = self.preview(batch)[1]
        self.assertEqual(report['counts']['quarantined'], 1)
        self.assertIn('duplicate_document_version_number', report['outcomes'][0]['reasons'])

    def test_delta_tombstones_no_resurrection_and_current_protocol(self):
        _, report = self.apply(); version = self.target(report, 'version-1'); reply = self.target(report, 'reply-1')
        selected = dict(kind='file', id=version, reason='Synthetic validation', expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol', selected)[0], 200)
        batch = copy.deepcopy(self.manifest); batch['records'] = [dict(batch['records'][1], revision=2, deleted=True)]
        _, blocked = self.apply(batch)
        self.assertEqual(blocked['counts']['quarantined'], 1)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{version}/download')[0], 200)
        self.alex.request('/api/studies/atlas/protocol', dict(kind=None, id=None, reason='Clear before delta', expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))
        # Deletion does not resolve arbitrary missing relationship IDs.
        batch['records'][0]['references'] = ['missing-deleted-evidence']
        _, deleted = self.apply(batch); self.assertEqual(deleted['counts']['deleted'], 1)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{version}/download')[0], 404)
        batch['records'][0].update(revision=3, deleted=False)
        _, resurrect = self.apply(batch); self.assertEqual(resurrect['counts']['quarantined'], 1)
        batch = copy.deepcopy(self.manifest); batch['records'] = [dict(batch['records'][4], revision=2, deleted=True), dict(batch['records'][5], revision=2, deleted=True)]
        _, removed = self.apply(batch); self.assertEqual(removed['counts']['deleted'], 2)
        tombstone = next(i for i in self.study()['items'] if i['id'] == reply)
        self.assertEqual(tombstone['body'], '[Removed from demo view]'); self.assertIsNone(tombstone['provenance']); self.assertEqual(tombstone['fileIds'], [])
        attachment = self.target(report, 'attachment-1')
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{attachment}/download')[0], 404)
        stale = self.preview()[1]; self.assertGreater(stale['counts']['stale_ignored'], 0)

    def test_parent_deletion_requires_complete_structural_tombstones(self):
        _, report = self.apply()
        root = dict(self.manifest['records'][0], revision=2, deleted=True)
        batch = copy.deepcopy(self.manifest); batch['records'] = [root]
        _, blocked = self.apply(batch)
        self.assertIn('live_dependents_require_tombstones', blocked['outcomes'][0]['reasons'])
        child1 = dict(self.manifest['records'][1], revision=2, deleted=True)
        child2 = dict(self.manifest['records'][2], revision=2, deleted=True)
        batch['records'] = [root, child1, dict(child2, revision='bad')]
        preview = self.preview(batch)[1]
        self.assertGreaterEqual(preview['counts']['quarantined'], 2)
        batch['records'] = [root, child1, child2]
        _, closed = self.apply(batch)
        self.assertEqual(closed['counts']['deleted'], 3)
        for suffix in ('version-1', 'version-2'):
            target = self.target(report, suffix)
            self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{target}/download')[0], 404)

    def test_binary_source_mutation_and_destination_change(self):
        _, report = self.apply()
        batch = copy.deepcopy(self.manifest); batch['records'] = [dict(batch['records'][1], revision=2)]
        self.assertIn('immutable_binary_version_changed_use_new_source_id', self.preview(batch)[1]['outcomes'][0]['reasons'])
        thread = self.target(report, 'decision-1')
        self.alex.request(f'/api/studies/atlas/items/{thread}/delete', dict(expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))
        batch = copy.deepcopy(self.manifest); batch['records'] = [dict(batch['records'][6], revision=2, body='Source update must not overwrite target deletion')]
        self.assertIn('changed_on_target', self.preview(batch)[1]['outcomes'][0]['reasons'])

    def test_native_children_protect_imported_parent(self):
        batch = copy.deepcopy(self.manifest)
        batch['records'] = [dict(batch['records'][3], references=[])]
        _, report = self.apply(batch)
        parent = self.target(report, 'thread-1')
        status, study, _ = self.alex.request('/api/studies/atlas/items', dict(kind='reply', title='Native reply', body='Synthetic follow-up', parentId=parent, documentId=None, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))
        self.assertEqual(status, 200)
        reply = study['items'][-1]['id']
        delete = lambda target: self.alex.request('/api/studies/atlas/items/' + target + '/delete', dict(expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))[0]
        self.assertEqual(delete(parent), 409)
        self.assertEqual(delete(reply), 200)
        status, study, _ = self.alex.request('/api/studies/atlas/files', dict(name='native-note.txt', contentBase64=base64.b64encode(b'Synthetic attachment').decode(), parentId=parent, documentId=None, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))
        self.assertEqual(status, 200)
        self.assertEqual(delete(parent), 409)
        self.assertTrue(any(i['id'] == parent and not i['deleted'] for i in self.study()['items']))
        # A native new version remains protected even after original imported versions are removed.
        _, family_report = self.apply(self.manifest)
        v1 = self.target(family_report, 'version-1')
        v2 = self.target(family_report, 'version-2')
        family = self.target(family_report, 'document-1')
        status, study, _ = self.alex.request('/api/studies/atlas/files', dict(name='native-revision.txt', contentBase64=base64.b64encode(b'Synthetic newer revision').decode(), parentId=None, documentId=v1, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))
        self.assertEqual(status, 200)
        for version in (v1, v2):
            self.assertEqual(self.alex.request('/api/studies/atlas/files/' + version + '/delete', dict(expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4())))[0], 200)
        self.assertEqual(delete(family), 409)

    def test_text_delta_history_version_and_idempotency_conflict(self):
        payload, report = self.apply(); decision = self.target(report, 'decision-1')
        # New optional document metadata must not change legacy imported-item fingerprints.
        initial = next(i for i in self.study()['items'] if i['id'] == decision)
        self.assertNotIn('documentVersion', initial)
        self.assertNotIn('boardIdea', initial)
        self.assertNotIn('boardDecision', initial)
        persisted = json.loads(self.data.read_text())
        persisted_item = next(i for s in persisted['studies'] if s['id'] == 'atlas' for i in s['items'] if i['id'] == decision)
        self.assertNotIn('documentVersion', persisted_item)
        self.assertNotIn('boardIdea', persisted_item)
        self.assertNotIn('boardDecision', persisted_item)
        batch = copy.deepcopy(self.manifest); batch['records'] = [dict(batch['records'][6], revision=2, body='Synthetic amended rationale')]
        _, updated = self.apply(batch); self.assertEqual(updated['counts']['imported'], 1)
        record = next(i for i in self.study()['items'] if i['id'] == decision)
        self.assertEqual(record['version'], 2); self.assertEqual(record['body'], 'Synthetic amended rationale')
        stored = json.loads(self.data.read_text())
        ledger = next(s for s in stored['studies'] if s['id'] == 'atlas')['importLedger'][batch['records'][0]['source_id']]
        self.assertEqual(len(ledger['history']), 1)
        self.assertEqual(ledger['history'][0]['original']['body'], self.manifest['records'][6]['body'])
        payload['manifest'] = batch
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', payload)[0], 409)
        fresh = self.payload(); fresh['expectedRevision'] -= 1
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', fresh)[0], 409)

    def test_interrupted_orphan_recovery_and_integrity(self):
        report = self.preview()[1]; target = self.target(report, 'version-1')
        content = base64.b64decode(self.manifest['records'][1]['content_base64'])
        self.blobs.mkdir(exist_ok=True); (self.blobs / (target + '.blob')).write_bytes(content)
        (self.blobs / 'interrupted.pending').write_bytes(b'incomplete unattached bytes')
        _, applied = self.apply(); self.assertEqual(applied['counts']['imported'], 7)
        self.assertEqual((self.blobs / (target + '.blob')).read_bytes(), content)
        # A new batch with a conflicting orphan fails atomically, without granting any content access.
        other = copy.deepcopy(self.manifest)
        for r in other['records']:
            r['source_id'] += '-orphan'
            if 'parent_id' in r: r['parent_id'] += '-orphan'
            r['references'] = [ref + '-orphan' for ref in r['references']]
        target = self.target(self.preview(other)[1], 'version-1-orphan')
        bad = self.blobs / (target + '.blob'); bad.write_bytes(b'tampered')
        before = self.study(); payload = self.payload(other)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', payload)[0], 503)
        self.assertEqual(self.study(), before)
        bad.unlink()
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/apply', payload)[0], 200)

    def test_z_disabled_release_policy_and_revoked_mapping(self):
        self.stop(); self.env['HUB_DEMO_FILE_RELEASE'] = 'false'; self.start(); self.alex = api.Client().login('alex')
        try:
            before = len(list(self.blobs.glob('*.blob')))
            _, report = self.apply()
            self.assertGreaterEqual(report['counts']['quarantined'], 6)
            self.assertEqual(len(list(self.blobs.glob('*.blob'))), before)
        finally:
            self.stop(); self.env['HUB_DEMO_FILE_RELEASE'] = 'true'; self.start(); self.alex = api.Client().login('alex')
        self.admin = api.Client().login('admin')
        self.admin.config('/api/admin/mapping', {'studyId': 'atlas', 'groupId': 'demo-group-b'})
        try:
            self.assertEqual(self.preview()[0], 404)
            self.assertEqual(self.alex.request('/api/studies/atlas/imports')[0], 404)
        finally:
            self.admin.config('/api/admin/mapping', {'studyId': 'atlas', 'groupId': 'demo-group-a'})


if __name__ == '__main__': unittest.main(verbosity=2)
