"""Decision supersession integration checks with synthetic data and loopback HTTP."""
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


class Decisions(unittest.TestCase):
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',5080))==0:raise RuntimeError('Decision tests require exclusive loopback port5080')
        subprocess.run([api.DOTNET,'build','--no-incremental','--nologo'],cwd=api.ROOT,check=True,stdout=subprocess.DEVNULL)
        cls.temp=tempfile.TemporaryDirectory(prefix='hub-decisions-')
        cls.data=Path(cls.temp.name)/'hub.json';cls.blobs=Path(cls.temp.name)/'files'
        cls.env=dict(os.environ,ASPNETCORE_ENVIRONMENT='Development',HUB_DEMO_ENABLED='true',HUB_DATA=str(cls.data),HUB_FILES=str(cls.blobs),HUB_DEMO_FILE_RELEASE='true')
        cls.log=open(Path(cls.temp.name)/'server.log','w+');cls.start()

    def setUp(self):
        self.alex=api.Client().login('alex');self.reviewer=api.Client().login('reviewer');self.lead=api.Client().login('lead')
        self.sam=api.Client().login('sam');self.admin=api.Client().login('admin')
    def study(self):return self.alex.request('/api/studies/atlas')[1]
    def payload(self,**changes):
        result=dict(title='Synthetic decision '+uuid.uuid4().hex[:8],rationale='A synthetic rationale for coordination.',alternatives='An alternate sequence was considered.',
                    ownerId='reviewer',effectiveDate='2026-10-01',itemIds=[],fileIds=[],reason='',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        result.update(changes);return result
    def write(self,payload,previous=None,client=None):
        path='/api/studies/atlas/decisions'+('' if previous is None else '/'+previous+'/supersede')
        return (client or self.alex).request(path,payload)
    def create(self,**changes):
        payload=self.payload(**changes);status,result,_=self.write(payload);self.assertEqual(status,200,result);return payload,result
    def supersede(self,prior,**changes):
        payload=self.payload(reason='Replace the earlier synthetic working choice.',**changes)
        status,result,_=self.write(payload,prior['item']['id'],self.reviewer);self.assertEqual(status,200,result);return payload,result
    def change(self,suffix,payload,client=None):
        return (client or self.alex).request('/api/studies/atlas'+suffix,dict(payload,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))
    def capture(self,ids):
        status,result,_=self.change('/handoffs',dict(title='Decision handoff',summary='Immutable context',itemIds=ids,fileIds=[]))
        self.assertEqual(status,200,result);return result

    def test_access_fixed_roles_csrf_and_validation(self):
        payload=self.payload()
        for client in (self.sam,self.admin):
            self.assertEqual(client.request('/api/studies/atlas/decisions')[0],404)
            self.assertEqual(self.write(payload,client=client)[0],404)
        self.assertEqual(self.alex.request('/api/studies/atlas/decisions',payload,csrf=False)[0],400)
        for changes in [dict(title=''),dict(title='x'*181),dict(rationale=''),dict(rationale='x'*20001),dict(alternatives='x'*4001),
                        dict(ownerId='admin'),dict(ownerId='sam'),dict(ownerId=None),dict(effectiveDate='10/1/26'),dict(effectiveDate='1800-01-01'),
                        dict(effectiveDate=None),dict(itemIds=[None]),dict(itemIds=['protocol-1']*2),dict(fileIds=['x']*31),dict(requestId='bad')]:
            self.assertEqual(self.write(dict(payload,**changes))[0],400,changes)
        _,decision=self.create()
        replacement=self.payload(reason='Synthetic change')
        self.assertEqual(self.write(replacement,decision['item']['id'])[0],403)
        self.admin.config('/api/admin/role',dict(identity='alex',role='Administrator'))
        self.assertEqual(self.write(replacement,decision['item']['id'])[0],403,'application admin is not study reviewer')
        for client in (self.sam,self.admin):
            self.assertEqual(client.request('/api/studies/atlas/decisions/'+decision['item']['id'])[0],404)
        self.assertEqual(self.write(self.payload(reason=''),decision['item']['id'],self.reviewer)[0],400)

    def test_immutable_single_successor_chain_and_current_history_views(self):
        _,first=self.create();original=copy.deepcopy(first['item'])
        _,second=self.supersede(first,rationale='Second immutable rationale')
        self.assertNotEqual(first['item']['id'],second['item']['id'])
        self.assertEqual(second['item']['decision']['supersedesId'],first['item']['id'])
        self.assertEqual(second['familyId'],first['familyId']);self.assertEqual(second['item']['version'],2)
        retained=self.alex.request('/api/studies/atlas/decisions/'+first['item']['id'])[1]
        self.assertEqual(retained['item'],original);self.assertEqual(retained['status'],'Superseded')
        self.assertEqual(retained['supersededById'],second['item']['id'])
        view=self.alex.request('/api/studies/atlas/decisions')[1]
        self.assertNotIn(first['item']['id'],[d['item']['id'] for d in view['current']])
        self.assertIn(first['item']['id'],[d['item']['id'] for d in view['history']])
        self.assertEqual(self.write(self.payload(reason='Branch attempt'),first['item']['id'],self.lead)[0],409)
        _,third=self.supersede(second,rationale='Third immutable rationale')
        self.assertEqual([d['item']['id'] for d in third['lineage']],[first['item']['id'],second['item']['id'],third['item']['id']])
        self.assertEqual([d['status'] for d in third['lineage']],['Superseded','Superseded','Current'])
        self.assertEqual(self.write(self.payload(reason='Cycle attempt'),first['item']['id'],self.lead)[0],409)
        for record in (first,second,third):self.assertEqual(self.change('/items/'+record['item']['id']+'/delete',{})[0],409)

    def test_exact_evidence_owner_and_referenced_draft_retention(self):
        before={i['id'] for i in self.study()['items']}
        response=self.change('/documents',dict(title='Exact synthetic evidence',body='Draft evidence version one',fileIds=[]));self.assertEqual(response[0],200)
        document=next(i for i in response[1]['items'] if i['id'] not in before)
        before_files={f['id'] for f in self.study()['files']}
        response=self.change('/files',dict(name='synthetic.txt',contentBase64=base64.b64encode(b'Synthetic evidence bytes').decode()));self.assertEqual(response[0],200)
        file=next(f for f in response[1]['files'] if f['id'] not in before_files)
        _,decision=self.create(itemIds=[document['id']],fileIds=[file['id']])
        self.assertEqual(decision['item']['decision']['itemIds'],[document['id']])
        self.assertEqual(decision['item']['fileIds'],[file['id']]);self.assertEqual(decision['item']['decision']['ownerId'],'reviewer')
        self.assertEqual(self.change('/items/'+document['id']+'/delete',{})[0],409)
        snapshot=self.capture([decision['item']['id']])
        self.assertIn(document['id'],[r['item']['id'] for r in snapshot['items']])
        self.assertIn(file['id'],[r['file']['id'] for r in snapshot['files']])
        for changes in [dict(itemIds=['beacon-protocol']),dict(itemIds=['missing']),dict(fileIds=['beacon-protocol'])]:
            self.assertEqual(self.write(self.payload(**changes))[0],400)
        path=self.blobs/(file['id']+'.blob');content=path.read_bytes();path.write_bytes(b'tamper')
        try:self.assertEqual(self.write(self.payload(fileIds=[file['id']]))[0],400)
        finally:path.write_bytes(content)

    def test_removed_ancestor_evidence_and_retained_chain_ancestor(self):
        before={i['id'] for i in self.study()['items']}
        result=self.change('/items',dict(kind='discussion',title='Synthetic parent',body='Question context'))
        parent=next(i for i in result[1]['items'] if i['id'] not in before)
        before.add(parent['id'])
        result=self.change('/items',dict(kind='reply',title='Synthetic child',body='Reply context',parentId=parent['id']))
        reply=next(i for i in result[1]['items'] if i['id'] not in before)
        self.assertEqual(self.change('/items/'+parent['id']+'/delete',{})[0],200)
        self.assertEqual(self.write(self.payload(itemIds=[reply['id']]))[0],400)
        masked=next(i for i in self.study()['items'] if i['id']==reply['id'])
        self.assertTrue(masked['deleted']);self.assertNotIn('Reply context',masked['body'])
        self.assertEqual(self.alex.request('/api/search?q=Reply%20context')[1],[])
        self.assertEqual(self.change('/items',dict(kind='reply',title='Blocked descendant',body='Synthetic',parentId=reply['id']))[0],400)

        before={i['id'] for i in self.study()['items']}
        result=self.change('/items',dict(kind='discussion',title='Retained context',body='Synthetic original context'))
        context=next(i for i in result[1]['items'] if i['id'] not in before);before.add(context['id'])
        result=self.change('/items',dict(kind='decision',title='Legacy decision',body='Immutable earlier rationale',parentId=context['id']))
        legacy=next(i for i in result[1]['items'] if i['id'] not in before)
        prior=self.alex.request('/api/studies/atlas/decisions/'+legacy['id'])[1]
        _,replacement=self.supersede(prior)
        self.assertEqual(self.change('/items/'+context['id']+'/delete',{})[0],409)
        self.assertEqual(self.alex.request('/api/studies/atlas/decisions/'+replacement['item']['id'])[0],200)

    def test_handoff_freezes_captured_decision_state(self):
        _,first=self.create();snapshot=self.capture([first['item']['id']])
        captured=next(r for r in snapshot['items'] if r['item']['id']==first['item']['id'])
        self.assertEqual(captured['decision']['status'],'Current')
        _,second=self.supersede(first)
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1],snapshot)
        newer=self.capture([second['item']['id']])
        states={r['item']['id']:r['decision']['status'] for r in newer['items'] if r['decision']}
        self.assertEqual(states[first['item']['id']],'Superseded');self.assertEqual(states[second['item']['id']],'Current')

    def test_delete_unreferenced_decision_redacts_new_metadata_and_replay(self):
        marker='Synthetic removed alternative '+uuid.uuid4().hex
        payload,decision=self.create(alternatives=marker,reason=marker)
        snapshot=self.capture([decision['item']['id']])
        self.assertEqual(self.change('/items/'+decision['item']['id']+'/delete',{})[0],200)
        self.assertEqual(self.write(payload)[0],404)
        self.assertEqual(self.alex.request('/api/studies/atlas/decisions/'+decision['item']['id'])[0],404)
        self.assertNotIn(marker,json.dumps(self.study()))
        projected=self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1]
        self.assertTrue(projected['redacted']);self.assertNotIn(marker,json.dumps(projected))
        self.assertEqual(projected['sha256'],snapshot['sha256'])

    def test_board_origin_and_reverse_status_preserved_across_supersession(self):
        board=self.change('/boards',dict(title='Decision origin',purpose='Synthetic exact-version exercise',responsibleId='reviewer'))[1]
        board=self.change('/boards/'+board['id']+'/ideas',dict(title='Origin idea',body='Original immutable proposal'))[1]
        idea=board['ideas'][0]
        self.assertEqual(self.write(self.payload(itemIds=[idea['currentVersionId']]))[0],400,'use typed board conversion')
        converted=self.change(f'/boards/{board["id"]}/ideas/{idea["id"]}/decisions',dict(versionId=idea['currentVersionId'],title='Board choice',rationale='Initial synthetic choice'))[1]
        prior=self.alex.request('/api/studies/atlas/decisions/'+converted['decisionId'])[1]
        _,replacement=self.supersede(prior)
        self.assertEqual(replacement['item']['boardDecision'],prior['item']['boardDecision'])
        detail=self.alex.request('/api/studies/atlas/boards/'+board['id'])[1]
        links={d['id']:d for d in detail['ideas'][0]['versions'][0]['decisions']}
        self.assertEqual(links[prior['item']['id']]['status'],'Superseded')
        self.assertEqual(links[prior['item']['id']]['supersededById'],replacement['item']['id'])
        self.assertEqual(links[replacement['item']['id']]['status'],'Current')
        export=self.alex.request('/api/studies/atlas/boards/'+board['id']+'/export')[1]
        self.assertIn(b'[Superseded]',export);self.assertIn(replacement['item']['id'].encode(),export)
        self.assertEqual(self.change(f'/boards/{board["id"]}/ideas/{idea["id"]}/delete',{})[0],409)

    def test_import_cannot_overwrite_or_delete_retained_decision(self):
        self.admin.config('/api/admin/role',dict(identity='alex',role='Administrator'))
        manifest=json.loads((api.ROOT/'fixtures/app-import.json').read_text())
        response=self.change('/imports/apply',dict(manifest=manifest));self.assertEqual(response[0],200,response[1])
        imported=next(r['targetId'] for r in response[1]['outcomes'] if r['sourceId']=='decision-1')
        delta=copy.deepcopy(manifest);delta['records']=[dict(manifest['records'][6],revision=2,body='Overwritten source rationale')]
        preview=self.alex.request('/api/studies/atlas/imports/preview',dict(manifest=delta))[1]
        self.assertEqual(preview['counts']['quarantined'],1)
        self.assertIn('decision_history_requires_typed_supersession_or_retention',preview['outcomes'][0]['reasons'])
        prior=self.alex.request('/api/studies/atlas/decisions/'+imported)[1];self.supersede(prior)
        delta['records'][0]['deleted']=True
        result=self.change('/imports/apply',dict(manifest=delta));self.assertEqual(result[0],200)
        self.assertEqual(result[1]['counts']['quarantined'],1)
        self.assertEqual(self.alex.request('/api/studies/atlas/decisions/'+imported)[1]['item'],prior['item'])

    def test_z_restart_replay_roles_lifecycle_and_revocation(self):
        request,first=self.create();replacement_request,second=self.supersede(first)
        self.assertEqual(self.write(replacement_request,first['item']['id'])[0],403)
        self.assertEqual(self.write(replacement_request,first['item']['id'],self.reviewer)[1]['item']['id'],second['item']['id'])
        conflict=dict(request,rationale='Different request');self.assertEqual(self.write(conflict)[0],409)
        stale=self.payload(expectedRevision=1);self.assertEqual(self.write(stale)[0],409)
        self.assertEqual(self.change('/stage',dict(stage='Closed'))[0],200)
        try:
            self.assertEqual(self.write(self.payload())[0],409)
            self.assertEqual(self.write(replacement_request,first['item']['id'],self.reviewer)[0],200)
        finally:self.assertEqual(self.change('/stage',dict(stage='Active'))[0],200)
        self.stop();self.start();self.alex=api.Client().login('alex');self.reviewer=api.Client().login('reviewer');self.admin=api.Client().login('admin')
        self.assertEqual(self.write(replacement_request,first['item']['id'],self.reviewer)[1],second)
        self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))
        try:
            self.assertEqual(self.write(replacement_request,first['item']['id'],self.reviewer)[0],404)
            self.assertEqual(self.reviewer.request('/api/studies/atlas/decisions/'+second['item']['id'])[0],404)
        finally:self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))


if __name__=='__main__':unittest.main(verbosity=2)
