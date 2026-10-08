"""Named brainstorming session HTTP checks; synthetic data, loopback only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import uuid
import test_api as api


class Boards(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 5080)) == 0:
                raise RuntimeError('Stop the preview; board tests own loopback port 5080')
        subprocess.run([api.DOTNET, 'build', '--no-incremental', '--nologo'], cwd=api.ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix='hub-boards-')
        cls.data = Path(cls.temp.name) / 'hub.json'
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT='Development', HUB_DEMO_ENABLED='true', HUB_DATA=str(cls.data),
                       HUB_FILES=str(Path(cls.temp.name)/'files'), HUB_DEMO_FILE_RELEASE='true')
        cls.log = open(Path(cls.temp.name)/'server.log', 'w+')
        cls.start()

    def setUp(self):
        self.alex = api.Client().login('alex'); self.sam = api.Client().login('sam')
        self.admin = api.Client().login('admin'); self.reviewer = api.Client().login('reviewer'); self.lead = api.Client().login('lead')

    def study(self): return self.alex.request('/api/studies/atlas')[1]
    def payload(self, **fields): return dict(fields, expectedRevision=self.study()['revision'], requestId=str(uuid.uuid4()))
    def post(self, suffix, fields, client=None):
        return (client or self.alex).request('/api/studies/atlas' + suffix, self.payload(**fields))
    def board(self, **changes):
        payload = self.payload(title='Synthetic session '+uuid.uuid4().hex[:8], purpose='Explore fictional handoff options.', responsibleId='reviewer')
        payload.update(changes)
        status, board, _ = self.alex.request('/api/studies/atlas/boards', payload)
        self.assertEqual(status, 200, board)
        return payload, board
    def idea(self, board, title='Synthetic idea', body='Compare the alternatives.'):
        before = set(board['ideaOrder'])
        status, result, _ = self.post(f'/boards/{board["id"]}/ideas', dict(title=title, body=body))
        self.assertEqual(status, 200, result)
        return result, next(i for i in result['ideas'] if i['id'] not in before)
    def detail(self, board, client=None): return (client or self.alex).request(f'/api/studies/atlas/boards/{board["id"]}')
    def delete(self, board, idea): return self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/delete', {})

    def test_a_readonly_seed_session_has_retained_revisions_and_exact_decision(self):
        before = self.data.read_bytes() if self.data.exists() else None
        status, board, _ = self.alex.request('/api/studies/atlas/boards/journey-board')
        self.assertEqual(status, 200)
        self.assertEqual(board['title'], 'Returning collaborator workshop')
        self.assertEqual(board['responsibleId'], 'reviewer')
        self.assertEqual(board['ideaOrder'], ['journey-board-start', 'journey-board-questions'])
        idea = next(i for i in board['ideas'] if i['id']=='journey-board-start')
        self.assertEqual([v['item']['version'] for v in idea['versions']], [1, 2])
        self.assertEqual(idea['currentVersionId'], 'journey-board-start-v2')
        self.assertEqual(idea['versions'][0]['decisions'], [])
        self.assertEqual(idea['versions'][1]['decisions'][0]['id'], 'journey-board-decision')
        decision=next(i for i in self.study()['items'] if i['id']=='journey-board-decision')
        self.assertEqual(decision['boardDecision']['ideaVersionId'], 'journey-board-start-v2')
        self.assertEqual(decision['boardDecision']['sourceAuthor'], 'alex')
        self.assertEqual(self.data.read_bytes() if self.data.exists() else None, before)

    def test_metadata_and_order_history_capture_old_values_without_body_copies(self):
        _,board=self.board(); original_title=board['title']; original_purpose=board['purpose']
        payload=self.payload(title='Renamed synthetic session',purpose='Revised purpose',responsibleId='alex')
        path=f'/api/studies/atlas/boards/{board["id"]}'
        status,changed,_=self.alex.request(path,payload);self.assertEqual(status,200)
        event=changed['history'][-1]
        self.assertEqual(event['before']['title'],original_title);self.assertEqual(event['before']['purpose'],original_purpose)
        self.assertEqual(event['before']['responsibleId'],'reviewer');self.assertEqual(event['after']['responsibleId'],'alex')
        self.assertEqual(event['after']['title'],'Renamed synthetic session')
        count=len(changed['history']);self.assertEqual(len(self.alex.request(path,payload)[1]['history']),count)
        changed,one=self.idea(changed,body='Idea body must not be copied into session history')
        changed,two=self.idea(changed)
        original_order=changed['ideaOrder'][:]
        result=self.post(f'/boards/{board["id"]}/reorder',dict(ideaIds=list(reversed(original_order))))
        event=result[1]['history'][-1]
        self.assertEqual(event['before']['ideaOrder'],original_order)
        self.assertEqual(event['after']['ideaOrder'],list(reversed(original_order)))
        self.assertEqual(event['before']['currentVersions'],event['after']['currentVersions'])
        self.assertNotIn('Idea body must not be copied',json.dumps(result[1]['history']))

    def test_access_owner_validation_csrf_and_fixed_roles(self):
        payload = self.payload(title='Boundary session',purpose='Synthetic purpose',responsibleId='alex')
        for client in (self.sam,self.admin):
            self.assertEqual(client.request('/api/studies/atlas/boards',payload)[0],404)
            self.assertEqual(client.request('/api/studies/atlas/boards')[0],404)
        self.assertEqual(self.alex.request('/api/studies/atlas/boards',payload,csrf=False)[0],400)
        for changes in [dict(title=''),dict(title='x'*181),dict(purpose=''),dict(purpose='x'*4001),
                        dict(responsibleId='sam'),dict(responsibleId='admin'),dict(responsibleId='unknown'),dict(responsibleId=None),dict(requestId='bad')]:
            self.assertEqual(self.alex.request('/api/studies/atlas/boards',dict(payload,**changes))[0],400,changes)
        _,board=self.board()
        self.assertEqual(board['responsibleId'],'reviewer');self.assertTrue(board['responsibleAvailable'])
        self.assertEqual(board['studyRole'],'Researcher')
        self.assertNotIn('boards',self.study())
        for client in (self.sam,self.admin):
            self.assertEqual(self.detail(board,client)[0],404)
            self.assertEqual(client.request(f'/api/studies/atlas/boards/{board["id"]}/export')[0],404)
        self.assertEqual(self.alex.request(f'/api/studies/beacon/boards/{board["id"]}')[0],404)
        self.admin.config('/api/admin/role',dict(identity='alex',role='Administrator'))
        self.assertEqual(self.post(f'/boards/{board["id"]}/state',dict(status='Archived',reason='No admin role bypass'))[0],403)
        self.assertEqual(self.post(f'/boards/{board["id"]}/state',dict(status='Archived',reason='Reviewer-managed session'),self.reviewer)[0],200)

    def test_immutable_idea_revisions_and_stale_update(self):
        _,board=self.board();board,idea=self.idea(board,body='Version one context')
        original=idea['current'];old_payload=self.payload(title='Conflicting edit',body='Stale text')
        result=self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='Revised idea',body='Version two context'))
        self.assertEqual(result[0],200)
        updated=result[1]['ideas'][0]
        self.assertEqual(len(updated['versions']),2);self.assertEqual(updated['versions'][0]['item'],original)
        self.assertNotEqual(updated['current']['id'],original['id'])
        self.assertEqual(updated['current']['version'],2)
        self.assertEqual(updated['current']['boardIdea']['previousVersionId'],original['id'])
        self.assertEqual(self.alex.request(f'/api/studies/atlas/boards/{board["id"]}/ideas/{idea["id"]}/versions',old_payload)[0],409)
        self.assertEqual(self.post(f'/items/{original["id"]}/delete',{})[0],409)
        for fields in [dict(title='',body='Text'),dict(title='Title',body=''),dict(title='x'*181,body='Text'),dict(title='Title',body='x'*20001)]:
            self.assertEqual(self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',fields)[0],400)

    def test_reorder_requires_complete_distinct_current_list(self):
        _,board=self.board();board,one=self.idea(board,title='First');board,two=self.idea(board,title='Second');board,three=self.idea(board,title='Third')
        original=board['ideaOrder'];stale=self.payload(ideaIds=list(reversed(original)))
        for ids in [None,[],[one['id'],one['id'],three['id']],[one['id'],two['id'],'foreign']]:
            self.assertEqual(self.post(f'/boards/{board["id"]}/reorder',dict(ideaIds=ids))[0],400)
            self.assertEqual(self.detail(board)[1]['ideaOrder'],original)
        changed=self.post(f'/boards/{board["id"]}/reorder',dict(ideaIds=[three['id'],one['id'],two['id']]))
        self.assertEqual(changed[0],200);self.assertEqual(changed[1]['ideaOrder'],[three['id'],one['id'],two['id']])
        self.assertEqual(self.alex.request(f'/api/studies/atlas/boards/{board["id"]}/reorder',stale)[0],409)
        _,foreign=self.board();foreign,other=self.idea(foreign)
        self.assertEqual(self.post(f'/boards/{board["id"]}/ideas/{other["id"]}/versions',dict(title='Wrong session',body='Text'))[0],404)

    def test_exact_old_revision_decision_backlinks_and_immutable_handoff(self):
        _,board=self.board();board,idea=self.idea(board,body='Original proposal to be cited')
        version1=idea['current']
        self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='Later proposal',body='Different later text'))
        payload=self.payload(versionId=version1['id'],title='Synthetic decision',rationale='Choose the original proposal for the rehearsal.')
        path=f'/api/studies/atlas/boards/{board["id"]}/ideas/{idea["id"]}/decisions'
        status,converted,_=self.alex.request(path,payload);self.assertEqual(status,200,converted)
        decision=next(i for i in self.study()['items'] if i['id']==converted['decisionId'])
        self.assertEqual(decision['parentId'],version1['id']);self.assertEqual(decision['boardDecision']['ideaVersionId'],version1['id'])
        self.assertEqual(decision['boardDecision']['ideaVersion'],1)
        self.assertEqual(decision['boardDecision']['sourceAuthor'],version1['author'])
        first=next(v for v in converted['ideas'][0]['versions'] if v['item']['id']==version1['id'])
        self.assertEqual(first['decisions'],[dict(id=decision['id'],title=decision['title'])])
        self.assertEqual(self.alex.request(path,payload)[1]['decisionId'],decision['id'])
        capture=self.post('/handoffs',dict(title='Board decision handoff',summary='Exact original revision',itemIds=[decision['id']],fileIds=[]))
        self.assertEqual(capture[0],200,capture[1]);snapshot=capture[1]
        self.assertIn(version1['id'],[r['item']['id'] for r in snapshot['items']])
        self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='Third proposal',body='Another later text'))
        self.assertEqual(self.alex.request(f'/api/studies/atlas/handoffs/{snapshot["id"]}')[1],snapshot)
        self.assertEqual(self.delete(board,idea)[0],409)
        self.assertEqual(self.post('/items',dict(kind='decision',title='Bypass',body='Generic conversion',parentId=version1['id']))[0],400)

    def test_softdelete_redacts_all_versions_export_and_handoff(self):
        _,board=self.board();marker='Synthetic erased idea '+uuid.uuid4().hex
        board,idea=self.idea(board,body=marker)
        version=idea['current']['id']
        self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='Another version',body=marker+' newer'))
        capture=self.post('/handoffs',dict(title='Pre-removal capture',summary='',itemIds=[version],fileIds=[]))
        self.assertEqual(capture[0],200);snapshot=capture[1]
        self.assertEqual(self.delete(board,idea)[0],200)
        self.assertEqual(self.detail(board)[1]['ideas'],[])
        self.assertNotIn(marker,json.dumps(self.study()))
        exported=self.alex.request(f'/api/studies/atlas/boards/{board["id"]}/export')
        self.assertEqual(exported[0],200);self.assertNotIn(marker.encode(),exported[1])
        self.assertNotIn(marker,json.dumps(self.detail(board)[1]['history']))
        projected=self.alex.request(f'/api/studies/atlas/handoffs/{snapshot["id"]}')[1]
        self.assertTrue(projected['redacted']);self.assertNotIn(marker,json.dumps(projected))
        self.assertEqual(projected['sha256'],snapshot['sha256'])
        self.assertEqual(self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='No resurrection',body='Text'))[0],404)

    def test_task_reference_blocks_idea_removal_until_reference_removed(self):
        _,board=self.board();board,idea=self.idea(board);version=idea['current']['id']
        before={i['id'] for i in self.study()['items']}
        task=dict(title='Uses exact idea',body='Synthetic next action',assignee='alex',dueDate=None,status='Open',links=[version],fileLinks=[])
        result=self.post('/tasks',task);self.assertEqual(result[0],200)
        task_id=next(i['id'] for i in result[1]['items'] if i['id'] not in before)
        self.assertEqual(self.delete(board,idea)[0],409)
        self.assertEqual(self.post(f'/tasks/{task_id}',dict(task,links=[]))[0],200)
        self.assertEqual(self.delete(board,idea)[0],200)

    def test_archive_reopen_study_close_and_authorize_before_replay(self):
        _,board=self.board();board,idea=self.idea(board)
        archive=self.payload(status='Archived',reason='Pause this synthetic session')
        path=f'/api/studies/atlas/boards/{board["id"]}/state'
        self.assertEqual(self.reviewer.request(path,archive)[0],200)
        self.assertEqual(self.alex.request(path,archive)[0],403,'researcher cannot replay reviewer-only transition')
        self.assertEqual(self.sam.request(path,archive)[0],404)
        writes=[('/ideas',dict(title='New',body='Text')),('/reorder',dict(ideaIds=[idea['id']])),
                (f'/ideas/{idea["id"]}/versions',dict(title='Changed',body='Text')),
                (f'/ideas/{idea["id"]}/decisions',dict(versionId=idea['current']['id'],title='Decision',rationale='Text')),
                (f'/ideas/{idea["id"]}/delete',{})]
        for suffix,fields in writes:self.assertEqual(self.post(f'/boards/{board["id"]}'+suffix,fields)[0],409)
        self.assertEqual(self.post(f'/boards/{board["id"]}',dict(title='Changed',purpose='Text',responsibleId='alex'))[0],409)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/boards/{board["id"]}/export')[0],200)
        self.assertEqual(self.post('/stage',dict(stage='Closed'))[0],200)
        try:self.assertEqual(self.post(f'/boards/{board["id"]}/state',dict(status='Active',reason='Blocked while study closed'),self.lead)[0],409)
        finally:self.assertEqual(self.post('/stage',dict(stage='Active'))[0],200)
        self.assertEqual(self.post(f'/boards/{board["id"]}/state',dict(status='Active',reason='Resume synthetic work'),self.lead)[0],200)
        self.assertEqual(self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='Resumed',body='New retained version'))[0],200)

    def test_export_exact_versions_and_legacy_ideas_stay_separate(self):
        _,board=self.board();literal='<script>synthetic()</script>'
        board,idea=self.idea(board,title='Text-only export',body=literal)
        self.post(f'/boards/{board["id"]}/ideas/{idea["id"]}/versions',dict(title='Second',body='Retained second revision'))
        legacy=self.post('/items',dict(kind='idea',title='Legacy independent idea',body='Legacy text'))
        self.assertEqual(legacy[0],200)
        detail=self.detail(board)[1]
        self.assertEqual(len(detail['ideas']),1);self.assertEqual(len(detail['ideas'][0]['versions']),2)
        export=self.alex.request(f'/api/studies/atlas/boards/{board["id"]}/export')
        self.assertEqual(export[0],200);self.assertTrue(export[2]['Content-Type'].startswith('text/plain'))
        self.assertIn('attachment',export[2]['Content-Disposition']);self.assertEqual(export[2]['X-Content-Type-Options'],'nosniff')
        self.assertIn(literal.encode(),export[1]);self.assertIn(b'exact version 1',export[1]);self.assertIn(b'exact version 2',export[1])
        self.assertNotIn(b'Legacy independent idea',export[1])

    def test_z_restart_idempotency_and_group_revocation(self):
        request,board=self.board();count=len(self.alex.request('/api/studies/atlas/boards')[1]['boards'])
        self.assertEqual(self.alex.request('/api/studies/atlas/boards',request)[1]['id'],board['id'])
        self.assertEqual(len(self.alex.request('/api/studies/atlas/boards')[1]['boards']),count)
        board,idea=self.idea(board)
        before=self.detail(board)[1];self.stop();self.start();self.alex=api.Client().login('alex');self.admin=api.Client().login('admin')
        self.assertEqual(self.detail(board)[1],before)
        self.assertEqual(self.alex.request('/api/studies/atlas/boards',request)[1]['id'],board['id'])
        self.assertEqual(self.alex.request('/api/studies/atlas/boards',dict(request,title='Changed request'))[0],409)
        self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))
        try:
            self.assertEqual(self.detail(board)[0],404)
            self.assertEqual(self.alex.request('/api/studies/atlas/boards',request)[0],404)
            self.assertEqual(self.alex.request(f'/api/studies/atlas/boards/{board["id"]}/export')[0],404)
            moved=api.Client().login('sam').request(f'/api/studies/atlas/boards/{board["id"]}')[1]
            self.assertFalse(moved['responsibleAvailable'])
        finally:self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))


if __name__=='__main__': unittest.main(verbosity=2)
