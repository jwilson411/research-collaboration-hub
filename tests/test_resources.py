"""Template provenance and safe synthetic resource pointer HTTP checks."""
import unittest
import uuid
import test_api as harness

class ResourceTests(unittest.TestCase):
    setUpClass=classmethod(harness.Integration.setUpClass.__func__)
    tearDownClass=classmethod(harness.Integration.tearDownClass.__func__)
    start=classmethod(harness.Integration.start.__func__)
    stop=classmethod(harness.Integration.stop.__func__)
    def setUp(self):
        self.client=harness.Client().login('alex')
    def study(self):
        return self.client.request('/api/studies/atlas')[1]
    def payload(self,**changes):
        value=dict(title='Synthetic local resource',body='Ask the synthetic owner for the local checklist.',url=None,ownerId='alex',source='Synthetic checklist author',lastVerified='2026-01-01',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        value.update(changes)
        return value
    def test_templates_provenance_revisions_snapshot_restart(self):
        status,templates,_=self.client.request('/api/studies/atlas/templates')
        self.assertEqual(status,200);self.assertEqual({t['id'] for t in templates},{'protocol','handoff','orientation'})
        payload=dict(title='Edited protocol outline',body=templates[0]['body']+'\nEdited locally.',templateId='protocol',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.client.request('/api/studies/atlas/documents',payload)
        self.assertEqual(status,200);item=study['items'][-1];self.assertEqual(item['template']['id'],'protocol')
        self.assertEqual(study['documentReviews'][item['id']]['status'],'Draft')
        self.assertEqual(self.client.request('/api/studies/atlas/documents',payload)[0],200)
        change=dict(payload,templateId='unknown',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.client.request('/api/studies/atlas/documents',change)[0],400)
        change.pop('templateId');change['body']='Next immutable content'
        status,study,_=self.client.request('/api/studies/atlas/documents/'+item['id']+'/versions',change)
        self.assertEqual(status,200);self.assertEqual(study['items'][-1]['template'],item['template'])
        type(self).stop();type(self).start()
        self.assertEqual(next(i for i in self.study()['items'] if i['id']==item['id']),item)
    def test_resource_validation_authorization_and_retry(self):
        path='/api/studies/atlas/resources'
        for changes in [dict(url='javascript:alert(1)'),dict(url='https://user:pass@example.invalid/a'),dict(url='file:///tmp/local'),dict(url='http:///missing'),dict(body='',url=None),dict(ownerId='sam'),dict(source=''),dict(lastVerified='2999-01-01'),dict(lastVerified='2026-02-30'),dict(title=' '),dict(requestId='bad')]:
            self.assertEqual(self.client.request(path,self.payload(**changes))[0],400,changes)
        for identity in ['sam','admin']:
            denied=harness.Client().login(identity)
            self.assertEqual(denied.request(path)[0],404)
            self.assertEqual(denied.request('/api/studies/atlas/templates')[0],404)
            self.assertEqual(denied.request(path,self.payload())[0],404)
        self.assertEqual(self.client.request(path,self.payload(),csrf=False)[0],400)
        self.assertEqual(self.client.request(path,self.payload(expectedRevision=0))[0],409)
        payload=self.payload(url='https://example.invalid/synthetic-guide')
        self.assertEqual(self.client.request(path,payload)[0],200)
        self.assertEqual(self.client.request(path,payload)[0],200)
        self.assertEqual(self.client.request(path,dict(payload,title='Changed'))[0],409)
        items=self.client.request(path)[1]['resources'];self.assertEqual(len([i for i in items if i['resource'].get('url')==payload['url']]),1)
    def test_pointer_handoff_and_reopen(self):
        status,study,_=self.client.request('/api/studies/atlas/resources',self.payload())
        self.assertEqual(status,200);item=study['items'][-1]
        capture=dict(title='Resource snapshot',summary='',itemIds=[item['id']],fileIds=[],expectedRevision=study['revision'],requestId=str(uuid.uuid4()))
        status,snapshot,_=self.client.request('/api/studies/atlas/handoffs',capture)
        self.assertEqual(status,200)
        for stage in ['Closed','Active']:
            payload=dict(stage=stage,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
            self.assertEqual(self.client.request('/api/studies/atlas/stage',payload)[0],200)
            if stage=='Closed':self.assertEqual(self.client.request('/api/studies/atlas/resources',self.payload())[0],409)
        self.assertEqual(self.client.request('/api/studies/atlas/resources',self.payload())[0],200)
        self.assertEqual(self.client.request('/api/studies/atlas/items/'+item['id']+'/delete',dict(expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))[0],200)
        current=self.client.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1]
        entry=next(i for i in current['items'] if i['item']['id']==item['id'])
        self.assertFalse(entry['available']);self.assertNotIn('resource',entry['item'])
    def test_removed_ancestor_masks_all_document_read_paths(self):
        def post(path,**fields):
            return self.client.request('/api/studies/atlas'+path,dict(fields,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))
        status,study,_=post('/items',kind='discussion',title='Temporary synthetic context',body='Context')
        self.assertEqual(status,200);parent=study['items'][-1]
        status,study,_=post('/items',kind='document',title='Hidden descendant protocol',body='AncestorSecretSyntheticOnly',parentId=parent['id'])
        self.assertEqual(status,200);document=study['items'][-1]
        self.assertEqual(post('/documents/'+document['id']+'/state',status='Review',reason='Synthetic review')[0],200)
        self.assertEqual(post('/protocol',kind='item',id=document['id'],reason='Synthetic selection')[0],200)
        self.assertEqual(post('/items/'+parent['id']+'/delete')[0],409)
        self.assertEqual(post('/protocol',kind=None,id=None,reason='Clear before removal')[0],200)
        self.assertEqual(post('/items/'+parent['id']+'/delete')[0],200)
        study=self.study();masked=next(i for i in study['items'] if i['id']==document['id'])
        self.assertTrue(masked['deleted']);self.assertNotIn('AncestorSecretSyntheticOnly',str(study))
        self.assertNotIn(document['id'],study['documentReviews'])
        self.assertFalse(self.client.request('/api/studies/atlas/protocol')[1]['available'])
        self.assertEqual(self.client.request('/api/search?q=AncestorSecretSyntheticOnly')[1],[])
        self.assertNotIn(document['id'],[v['item']['id'] for v in self.client.request('/api/studies/atlas/documents')[1]['versions']])
        self.assertEqual(self.client.request('/api/studies/atlas/documents/'+document['id']+'/download')[0],404)
        self.assertEqual(post('/documents/'+document['id']+'/versions',title='Attempt',body='Synthetic')[0],404)
        self.assertEqual(post('/documents/'+document['id']+'/state',status='Review',reason='Attempt')[0],404)
        self.assertEqual(post('/protocol',kind='item',id=document['id'],reason='Attempt')[0],400)
        self.assertEqual(post('/tasks',title='Attempt',body='Synthetic',status='Open',links=[document['id']])[0],400)

    def test_accepted_document_ancestor_is_retained(self):
        def post(path,client=None,**fields):
            return (client or self.client).request('/api/studies/atlas'+path,dict(fields,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))
        parent=post('/items',kind='discussion',title='Retained parent',body='Synthetic')[1]['items'][-1]
        doc=post('/items',kind='document',title='Retained child',body='Synthetic',parentId=parent['id'])[1]['items'][-1]
        self.assertEqual(post('/documents/'+doc['id']+'/state',status='Review',reason='Synthetic')[0],200)
        lead=harness.Client().login('lead')
        self.assertEqual(post('/documents/'+doc['id']+'/state',client=lead,status='Accepted',reason='Synthetic')[0],200)
        self.assertEqual(post('/items/'+parent['id']+'/delete')[0],409)
        self.assertEqual(self.client.request('/api/studies/atlas/documents/'+doc['id']+'/download')[0],200)
