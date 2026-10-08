"""Exact protocol and binary-evidence regressions with synthetic loopback data."""
import unittest
import uuid
import test_attachments as attachments

class Protocols(unittest.TestCase):
    setUpClass=classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass=classmethod(attachments.Attachments.tearDownClass.__func__)
    start=classmethod(attachments.Attachments.start.__func__)
    stop=classmethod(attachments.Attachments.stop.__func__)
    setUp=attachments.Attachments.setUp
    study=attachments.Attachments.study
    item=attachments.Attachments.item
    upload=attachments.Attachments.upload
    create=attachments.Attachments.create
    def designation(self, **changes):
        payload=dict(kind='item',id='protocol-1',reason='Synthetic reviewed selection',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        payload.update(changes)
        return payload

    def designate(self, **changes):
        request=self.designation(**changes)
        status, state, _=self.alex.request('/api/studies/atlas/protocol',request)
        self.assertEqual(status,200)
        return request,state

    def test_protocol_authorization_validation(self):
        path='/api/studies/atlas/protocol'
        self.assertEqual(self.sam.request(path,self.designation())[0],404)
        self.assertEqual(self.sam.request(path)[0],404)
        self.assertEqual(self.admin.request(path)[0],404)
        self.assertEqual(self.admin.request(path,self.designation())[0],404)
        self.assertEqual(self.alex.request(path,self.designation(),csrf=False)[0],400)
        for change in (dict(id='beacon-protocol'),dict(id='question-1'),dict(id='missing'),dict(kind='other'),dict(reason=' '),dict(reason='x'*1001),dict(kind=None),dict(id=None),dict(requestId='bad')):
            with self.subTest(change=change): self.assertEqual(self.alex.request(path,self.designation(**change))[0],400)
        _,_,quarantine=self.create(name='synthetic.pdf',content=b'%PDF-1.7 synthetic')
        self.assertEqual(self.alex.request(path,self.designation(kind='file',id=quarantine['id']))[0],400)
        _,_,attached=self.create(parentId='question-1')
        self.assertEqual(self.alex.request(path,self.designation(kind='file',id=attached['id']))[0],400)

    def test_protocol_deleted_cross_study_and_lifecycle(self):
        _,state,file=self.create()
        self.assertEqual(self.alex.request('/api/studies/atlas/files/'+file['id']+'/delete',dict(expectedRevision=state['revision'],requestId=str(uuid.uuid4())))[0],200)
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',self.designation(kind='file',id=file['id']))[0],400)
        beacon=self.study(client=self.sam,study='beacon')
        self.assertEqual(self.sam.request('/api/studies/beacon/stage',dict(stage='Active',expectedRevision=beacon['revision'],requestId=str(uuid.uuid4())))[0],200)
        beacon=self.study(client=self.sam,study='beacon')
        payload=self.upload(expectedRevision=beacon['revision'])
        status,beacon,_=self.sam.request('/api/studies/beacon/files',payload)
        self.assertEqual(status,200)
        other=beacon['files'][-1]['id']
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',self.designation(kind='file',id=other))[0],400)
        self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(fileIds=[other]))[0],400)
        stage=dict(stage='Paused',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/stage',stage)[0],200)
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',self.designation())[0],409)
        stage=dict(stage='Active',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/stage',stage)[0],200)

    def test_protocol_exact_version_protection_history_restart(self):
        request,selected=self.designate()
        self.assertEqual(selected['currentProtocol']['id'],'protocol-1')
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',request)[1],selected)
        self.assertEqual(self.alex.request('/api/studies/atlas/protocol',dict(request,reason='Altered retry'))[0],409)
        deletion=dict(expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/items/protocol-1/delete',deletion)[0],409)
        self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(kind='document',title='Current protocol',body='Synthetic newer version'))[0],200)
        self.assertEqual(self.study()['currentProtocol']['id'],'protocol-1')
        _,_,first=self.create()
        _,selected=self.designate(kind='file',id=first['id'])
        _,_,second=self.create(documentId=first['id'],content=b'Synthetic revision')
        self.assertEqual(self.study()['currentProtocol']['id'],first['id'])
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.alex.request('/api/studies/atlas/files/'+first['id']+'/delete',dict(expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))[0],409)
        _,cleared=self.designate(kind=None,id=None,reason='Clear for synthetic review')
        self.assertIsNone(cleared['currentProtocol'])
        self.assertEqual(cleared['protocolHistory'][-2]['id'],first['id'])
        self.assertEqual(cleared['protocolHistory'][-1]['reason'],'Clear for synthetic review')
        self.stop();self.start()
        self.alex=attachments.api.Client().login('alex')
        self.assertEqual(self.study(),cleared)

    def test_protocol_unavailable_blob_or_release_policy(self):
        _,_,file=self.create()
        self.designate(kind='file',id=file['id'])
        self.assertTrue(self.alex.request('/api/studies/atlas/protocol')[1]['available'])
        blob=self.blobs/(file['id']+'.blob')
        blob.write_bytes(b'x'*file['size'])
        for missing in (False,True):
            if missing: blob.unlink()
            view=self.alex.request('/api/studies/atlas/protocol')[1]
            self.assertFalse(view['available'])
            self.assertEqual(view['current']['id'],file['id'])
            self.assertEqual(self.alex.request('/api/studies/atlas/protocol',self.designation(kind='file',id=file['id']))[0],400)
            self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(fileIds=[file['id']]))[0],400)
        _,_,released=self.create()
        self.stop();self.env['HUB_DEMO_FILE_RELEASE']='false';self.start()
        self.alex=attachments.api.Client().login('alex')
        try:
            self.assertEqual(self.alex.request('/api/studies/atlas/protocol',self.designation(kind='file',id=released['id']))[0],400)
            self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(fileIds=[released['id']]))[0],400)
        finally:
            self.stop();self.env['HUB_DEMO_FILE_RELEASE']='true';self.start()
            self.alex=attachments.api.Client().login('alex')

    def test_protocol_file_citations_exact_and_invalid(self):
        _,_,file=self.create()
        for ids in ([file['id'],file['id']],['missing'],[None]):
            self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(fileIds=ids))[0],400)
        _,_,quarantine=self.create(name='unsafe.pdf',content=b'%PDF-1.7 synthetic')
        self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(fileIds=[quarantine['id']]))[0],400)
        status,state,_=self.alex.request('/api/studies/atlas/items',self.item(kind='decision',fileIds=[file['id']]))
        self.assertEqual(status,200)
        self.assertEqual(state['items'][-1]['fileIds'],[file['id']])
        payload=dict(title='Synthetic evidence task',body='Review exact file',assignee='alex',dueDate=None,status='Open',links=[],fileLinks=[file['id']],expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,state,_=self.alex.request('/api/studies/atlas/tasks',payload)
        self.assertEqual(status,200)
        task=state['items'][-1]
        self.assertEqual(task['task']['fileLinks'],[file['id']])
        payload.update(fileLinks=[quarantine['id']],expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/tasks',payload)[0],400)
        _,_,new=self.create(documentId=file['id'],content=b'New exact synthetic bytes')
        task=next(i for i in self.study()['items'] if i['id']==task['id'])
        self.assertEqual(task['task']['fileLinks'],[file['id']])
        self.assertNotEqual(file['id'],new['id'])
        payload.update(fileLinks=[new['id']],expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,state,_=self.alex.request('/api/studies/atlas/tasks/'+task['id'],payload)
        self.assertEqual(status,200)
        updated=next(i for i in state['items'] if i['id']==task['id'])
        self.assertEqual(updated['task']['fileLinks'],[new['id']])
        self.assertEqual(updated['task']['history'][-1]['fileLinks'],[file['id']])

if __name__=='__main__': unittest.main(verbosity=2)
