"""Administrator-only synthetic workspace creation without directory membership changes."""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import uuid
import test_api as api
import test_attachments as attachments

class Provisioning(unittest.TestCase):
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    setUpClass=classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)
    setUp=api.Integration.setUp
    def admin_state(self):return self.admin.request('/api/admin')[1]
    def payload(self,**changes):
        value=dict(studyId='synthetic-'+uuid.uuid4().hex[:12],title='Synthetic new research workspace',summary='Synthetic coordination only; no actual study data.',
                   groupId='demo-group-a',expectedRevision=self.admin_state()['configRevision'],requestId=str(uuid.uuid4()))
        value.update(changes);return value
    def create(self,**changes):
        payload=self.payload(**changes)
        status,receipt,_=self.admin.request('/api/admin/studies',payload)
        self.assertEqual(status,200,receipt);return payload,receipt

    def test_empty_paused_workspace_access_and_audited_provenance(self):
        before=self.admin_state()
        payload,receipt=self.create(groupId='demo-group-b',stage='Active',members=['admin'])
        self.assertEqual(receipt['initialStage'],'Paused');self.assertEqual(receipt['initialGroupId'],'demo-group-b')
        self.assertEqual(receipt['configRevision'],before['configRevision']+1)
        path='/api/studies/'+payload['studyId']
        for client in (self.admin,self.alex):self.assertEqual(client.request(path)[0],404)
        status,study,_=self.sam.request(path);self.assertEqual(status,200)
        self.assertEqual(study['stage'],'Paused');self.assertEqual(study['revision'],1)
        self.assertEqual(study['items'],[]);self.assertEqual(study['files'],[])
        orientation=self.sam.request(path+'/onboarding')[1]
        self.assertEqual(orientation['contact'],'Study contact not configured')
        self.assertIsNone(study['currentProtocol']);self.assertEqual(study['documentReviews'],{})
        self.assertEqual(study['provisioning']['datasetKind'],'SyntheticDemo')
        self.assertEqual(study['provisioning']['actor'],'admin')
        self.assertEqual(study['provisioning']['initialGroupId'],'demo-group-b')
        after=self.admin_state()
        self.assertEqual(after['groups'],before['groups']);self.assertEqual(after['roles'],before['roles'])
        events=[e for e in after['configurationHistory'] if e['target']==payload['studyId']]
        self.assertEqual(len(events),1);self.assertEqual(events[0]['action'],'Provisioned synthetic study')
        self.assertEqual(len([e for e in after['audit'] if e['target']==payload['studyId']]),1)
        self.assertEqual(self.sam.request(path+'/items',dict(kind='discussion',title='Paused attempt',body='Synthetic',expectedRevision=1,requestId=str(uuid.uuid4())))[0],409)
        self.assertEqual(self.sam.request(path+'/stage',dict(stage='Active',expectedRevision=1,requestId=str(uuid.uuid4())))[0],200)
        self.assertEqual(self.sam.request(path+'/items',dict(kind='discussion',title='First collaboration',body='Synthetic',expectedRevision=2,requestId=str(uuid.uuid4())))[0],200)
        self.assertEqual(self.admin.request(path)[0],404)
        templates=self.sam.request(path+'/templates')[1]
        self.assertEqual(len(templates),3)
        self.assertTrue(all(t['versionId'].startswith('default:'+payload['studyId']+':') for t in templates))

    def test_invalid_fields_atomic_and_seed_collision(self):
        before=self.admin_state()
        for changes in (dict(studyId=None),dict(studyId='ab'),dict(studyId='a'*49),dict(studyId='Upper'),dict(studyId='a--b'),
                        dict(studyId='a-b-'),dict(studyId='../atlas'),dict(studyId='1study'),dict(studyId='a_b'),dict(studyId='abc\n'),
                        dict(title=None),dict(title=' '),dict(title='x'*181),dict(summary=None),dict(summary='x'*2001),
                        dict(groupId=None),dict(groupId=''),dict(groupId='new-directory-group'),dict(requestId='bad'),dict(expectedRevision=0)):
            self.assertEqual(self.admin.request('/api/admin/studies',self.payload(**changes))[0],400,changes)
        self.assertEqual(self.admin_state(),before)
        self.assertEqual(self.admin.request('/api/admin/studies',self.payload(studyId='atlas'))[0],409)
        self.assertEqual(self.admin.request('/api/admin/studies',self.payload(),csrf=False)[0],400)
        self.assertEqual(self.admin_state(),before)
        payload,_=self.create(studyId='a'+'b'*47,title='x'*180,summary='x'*2000)
        self.assertEqual(self.alex.request('/api/studies/'+payload['studyId'])[0],200)

    def test_idempotence_restart_stale_and_cross_operation_keys(self):
        payload,receipt=self.create();before=self.admin_state()
        self.assertEqual(self.admin.request('/api/admin/studies',payload)[1],receipt)
        self.assertEqual(self.admin_state(),before)
        self.assertEqual(self.admin.request('/api/admin/studies',dict(payload,title='Changed'))[0],409)
        self.assertEqual(self.admin.request('/api/admin/studies',self.payload(studyId=payload['studyId']))[0],409)
        self.assertEqual(self.admin.request('/api/admin/studies',self.payload(expectedRevision=receipt['configRevision']-1))[0],409)
        self.assertEqual(self.admin.request('/api/admin/mapping',dict(studyId=payload['studyId'],groupId='demo-group-b',expectedRevision=receipt['configRevision'],requestId=payload['requestId']))[0],409)
        study=self.alex.request('/api/studies/'+payload['studyId'])[1]
        self.stop();self.start();self.admin=api.Client().login('admin');self.alex=api.Client().login('alex')
        self.assertEqual(self.admin.request('/api/admin/studies',payload)[1],receipt)
        self.assertEqual(self.alex.request('/api/studies/'+payload['studyId'])[1],study)
        self.assertEqual(self.admin_state(),before)

    def test_current_admin_role_before_replay(self):
        payload=self.payload()
        for client in (self.alex,self.sam):self.assertEqual(client.request('/api/admin/studies',payload)[0],403)
        self.assertEqual(self.admin.config('/api/admin/role',dict(identity='alex',role='Administrator'))[0],200)
        try:
            payload=self.payload()
            self.assertEqual(self.alex.request('/api/admin/studies',payload)[0],200)
        finally:self.assertEqual(self.admin.config('/api/admin/role',dict(identity='alex',role='Researcher'))[0],200)
        before=self.admin_state()
        self.assertEqual(self.alex.request('/api/admin/studies',payload)[0],403)
        self.assertEqual(self.admin_state(),before)

    def test_concurrent_duplicate_requests_create_one_workspace(self):
        for identical in (False,True):
            payload=self.payload()
            second=payload if identical else dict(payload,requestId=str(uuid.uuid4()))
            clients=[api.Client().login('admin'),api.Client().login('admin')]
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(client.request,'/api/admin/studies',body) for client,body in zip(clients,[payload,second])]
                statuses=[future.result()[0] for future in futures]
            self.assertEqual(sorted(statuses),[200,200] if identical else [200,409])
            current=self.admin_state()
            self.assertEqual(current['configRevision'],payload['expectedRevision']+1)
            self.assertEqual(len([s for s in current['mappings'] if s['studyId']==payload['studyId']]),1)
            self.assertEqual(len([e for e in current['configurationHistory'] if e['target']==payload['studyId']]),1)

    def test_interrupted_persistence_does_not_partially_provision(self):
        payload=self.payload();before=self.admin_state()
        prior=self.data.read_bytes() if self.data.exists() else None
        pending=self.data.with_name(self.data.name+'.tmp');self.assertFalse(pending.exists());pending.mkdir()
        try:
            self.assertEqual(self.admin.request('/api/admin/studies',payload)[0],503)
            self.assertEqual(self.admin_state(),before)
            self.assertEqual(self.data.read_bytes() if self.data.exists() else None,prior)
            self.assertEqual(self.alex.request('/api/studies/'+payload['studyId'])[0],404)
        finally:pending.rmdir()
        self.assertEqual(self.admin.request('/api/admin/studies',payload)[0],200)
        self.assertEqual(self.admin.request('/api/admin/studies',payload)[0],200)
        self.assertEqual(len([e for e in self.admin_state()['audit'] if e['target']==payload['studyId']]),1)

    def test_unmarked_dataset_fails_closed_without_relabeling(self):
        self.create()
        self.stop();original=self.data.read_bytes();state=json.loads(original);state.pop('datasetKind')
        self.data.write_text(json.dumps(state));self.start()
        try:
            before=self.data.read_bytes()
            self.assertEqual(self.admin.request('/api/admin/studies',self.payload())[0],503)
            self.assertEqual(self.data.read_bytes(),before)
            self.assertNotIn('datasetKind',json.loads(before))
        finally:
            self.stop();self.data.write_bytes(original);self.start()

if __name__=='__main__':unittest.main(verbosity=2)
