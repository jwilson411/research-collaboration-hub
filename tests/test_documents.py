"""Synthetic document-family HTTP tests; owns loopback5080 while running."""
import uuid
import unittest
import test_api as harness

class DocumentTests(unittest.TestCase):
    setUpClass = classmethod(harness.Integration.setUpClass.__func__)
    tearDownClass = classmethod(harness.Integration.tearDownClass.__func__)
    start = classmethod(harness.Integration.start.__func__)
    stop = classmethod(harness.Integration.stop.__func__)

    def setUp(self):
        self.alex=harness.Client().login('alex')
        self.reviewer=harness.Client().login('reviewer')
        self.lead=harness.Client().login('lead')
        self.sam=harness.Client().login('sam')
        self.admin=harness.Client().login('admin')

    def study(self):
        status,value,_=self.alex.request('/api/studies/atlas')
        self.assertEqual(status,200)
        return value

    def payload(self,**changes):
        value=dict(title='Synthetic stable family',body='Immutable version one',fileIds=[],expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        value.update(changes)
        return value

    def create(self):
        payload=self.payload()
        status,study,_=self.alex.request('/api/studies/atlas/documents',payload)
        self.assertEqual(status,200)
        return study['items'][-1]

    def change(self,item,status,client=None,**kwargs):
        value=dict(status=status,reason='Synthetic review rationale',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        value.update(kwargs)
        return (client or self.alex).request(f"/api/studies/atlas/documents/{item['id']}/state",value)

    def version_state(self,item):
        result=self.alex.request('/api/studies/atlas/documents')[1]
        return next(v for v in result['versions'] if v['item']['id']==item['id'])

    def test_family_immutable_versions_and_states(self):
        original=self.create()
        revision=self.payload(title='Renamed family title',body='Immutable version two')
        endpoint=f"/api/studies/atlas/documents/{original['id']}/versions"
        status,study,_=self.alex.request(endpoint,revision)
        self.assertEqual(status,200)
        second=study['items'][-1]
        self.assertNotEqual(original['id'],second['id'])
        self.assertEqual(second['version'],2)
        self.assertEqual(second['documentVersion']['familyId'],original['id'])
        self.assertEqual(second['documentVersion']['previousVersionId'],original['id'])
        self.assertEqual(next(i for i in study['items'] if i['id']==original['id']),original)
        self.assertEqual(self.alex.request(endpoint,revision)[0],200)
        self.assertEqual(len([i for i in self.study()['items'] if (i.get('documentVersion') or {}).get('familyId')==original['id']]),2)
        self.assertEqual(self.alex.request(endpoint,dict(revision,body='Changed replay'))[0],409)
        self.assertEqual(self.change(original,'Review')[0],200)
        self.assertEqual(self.change(original,'Accepted',self.alex)[0],403)
        self.assertEqual(self.change(original,'Accepted',self.reviewer)[0],403)
        self.assertEqual(self.change(original,'Draft',self.reviewer)[0],200)
        self.assertEqual(self.change(original,'Review')[0],200)
        self.assertEqual(self.change(original,'Accepted',self.lead)[0],200)
        self.assertEqual(self.change(second,'Review')[0],200)
        self.assertEqual(self.change(second,'Accepted',self.lead)[0],409)
        self.assertEqual(self.change(original,'Superseded',self.lead)[0],200)
        self.assertEqual(self.change(second,'Accepted',self.lead)[0],200)
        self.assertEqual(self.version_state(second)['status'],'Accepted')
        self.assertEqual(next(i for i in self.study()['items'] if i['id']==original['id']),original)
        self.assertEqual(self.alex.request(f"/api/studies/atlas/items/{original['id']}/delete",dict(expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))[0],409)
        type(self).stop();type(self).start()
        self.assertEqual(self.alex.request("/api/studies/atlas/documents")[0],409)
        self.alex.login("alex")
        self.assertEqual(self.version_state(original)['status'],'Superseded')
        self.assertEqual(self.version_state(second)['status'],'Accepted')

    def test_access_validation_csrf_stale_and_protocol_guard(self):
        item=self.create()
        path=f"/api/studies/atlas/documents/{item['id']}/state"
        for client in [self.sam,self.admin]:
            self.assertEqual(client.request('/api/studies/atlas/documents')[0],404)
            self.assertEqual(client.request('/api/studies/atlas/documents',self.payload())[0],404)
            self.assertEqual(self.change(item,'Review',client)[0],404)
        self.assertEqual(self.alex.request('/api/studies/atlas/documents',self.payload(),csrf=False)[0],400)
        for changes in [dict(title=' '),dict(body=None),dict(title='x'*181),dict(fileIds=['missing']),dict(requestId='bad')]:
            self.assertEqual(self.alex.request('/api/studies/atlas/documents',self.payload(**changes))[0],400)
        self.assertEqual(self.alex.request('/api/studies/atlas/documents/beacon-protocol/versions',self.payload())[0],404)
        self.assertEqual(self.change(item,'Review',expectedRevision=0)[0],409)
        self.assertEqual(self.change(item,'Accepted',self.lead)[0],409)
        self.assertEqual(self.change(item,'Review',reason='')[0],400)
        payload=dict(status='Review',reason='Exact retry',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request(path,payload)[0],200)
        self.assertEqual(self.alex.request(path,payload)[0],200)
        self.assertEqual(len(self.version_state(item)['history']),1)
        self.assertEqual(self.change(item,'Accepted',self.lead)[0],200)
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',dict(kind='item',id=item['id'],reason='Working reference',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))[0],200)
        self.assertEqual(self.change(item,'Superseded',self.lead)[0],409)
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',dict(kind=None,id=None,reason='Clear working reference',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))[0],200)
        self.assertEqual(self.change(item,'Superseded',self.lead)[0],200)

    def test_legacy_family_and_closed_workspace(self):
        result=self.alex.request('/api/studies/atlas/documents')[1]
        legacy=next(v for v in result['versions'] if v['item']['id']=='protocol-1')
        self.assertEqual(legacy['familyId'],'protocol-1')
        self.assertEqual(legacy['status'],'Draft')
        item=self.create()
        stage=lambda value:self.alex.request('/api/studies/atlas/stage',dict(stage=value,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))
        self.assertEqual(stage('Closed')[0],200)
        self.assertEqual(self.alex.request('/api/studies/atlas/documents',self.payload())[0],409)
        self.assertEqual(self.change(item,'Review')[0],409)
        self.assertEqual(self.alex.request('/api/studies/atlas/documents')[0],200)
        self.assertEqual(stage('Active')[0],200)
        self.assertEqual(self.change(item,'Review')[0],200)

if __name__=='__main__':
    unittest.main(verbosity=2)
