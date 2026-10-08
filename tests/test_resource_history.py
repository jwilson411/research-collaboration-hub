"""Versioned templates/resource pointers: immutable evidence and access boundaries."""
import json
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
import uuid
import test_api as api
import test_attachments as attachments

class ResourceHistory(unittest.TestCase):
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    setUpClass=classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)
    study=api.Integration.study
    def setUp(self):
        api.Integration.setUp(self)
        self.lead=api.Client().login('lead');self.reviewer=api.Client().login('reviewer')
    def payload(self,**fields):return dict(fields,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
    def post(self,path,client=None,**fields):return (client or self.alex).request('/api/studies/atlas'+path,self.payload(**fields))
    def template(self,**changes):
        fields=dict(title='Synthetic outline '+uuid.uuid4().hex,description='A synthetic starting point',body='Original exact outline',reason='Initial catalog definition')
        fields.update(changes);return fields
    def resource(self,**changes):
        fields=dict(title='Synthetic local reference',body='Ask the synthetic owner',url='https://example.invalid/one',ownerId='alex',source='Synthetic source',lastVerified='2026-01-01')
        fields.update(changes);return fields
    def create_resource(self):
        status,study,_=self.post('/resources',**self.resource());self.assertEqual(status,200,study);return study['items'][-1]
    def capture(self,ids):
        status,result,_=self.post('/handoffs',title='Exact resource evidence',summary='Synthetic snapshot',itemIds=ids,fileIds=[])
        self.assertEqual(status,200,result);return result

    def test_template_role_validation_cross_study_and_replay(self):
        payload=self.payload(**self.template())
        for client,status in ((self.alex,403),(self.reviewer,403),(self.sam,404),(self.admin,404)):
            self.assertEqual(client.request('/api/studies/atlas/templates',payload)[0],status)
        self.assertEqual(self.lead.request('/api/studies/atlas/templates',payload,csrf=False)[0],400)
        status,catalog,_=self.lead.request('/api/studies/atlas/templates',payload)
        self.assertEqual(status,200,catalog);definition=catalog['versions'][-1]
        self.assertEqual(self.lead.request('/api/studies/atlas/templates',payload)[1],catalog)
        self.assertEqual(self.alex.request('/api/studies/atlas/templates',payload)[0],403)
        self.assertEqual(self.lead.request('/api/studies/atlas/templates',dict(payload,body='Different'))[0],409)
        for client in (self.sam,self.admin):
            self.assertEqual(client.request('/api/studies/atlas/templates/'+definition['id']+'/versions')[0],404)
        self.assertEqual(self.post('/documents',title='Foreign default',body='Synthetic',templateVersionId='default:beacon:protocol:1')[0],400)
        self.assertEqual(self.post('/documents',title='Mismatch',body='Synthetic',templateId='protocol',templateVersionId=definition['versionId'])[0],400)
        for change in (dict(title=None),dict(description=None),dict(body=None),dict(reason=None),dict(body='x'*20001),dict(description='x'*1001)):
            self.assertEqual(self.post('/templates',client=self.lead,**self.template(**change))[0],400)

    def test_template_exact_definition_pinned_and_legacy_default_frozen(self):
        original=self.alex.request('/api/studies/atlas/templates/protocol/versions')[1][0]
        status,study,_=self.post('/documents',title='Pinned default',body='Edited local draft',templateId='protocol')
        self.assertEqual(status,200,study);document=study['items'][-1]
        self.assertEqual(document['template']['versionId'],original['versionId'])
        persisted=json.loads(self.data.read_bytes())
        stored=next(st for st in persisted['studies'] if st['id']=='atlas')['templateDefinitions']
        self.assertIn(original,stored)
        snapshot=self.capture([document['id']])
        status,catalog,_=self.post('/templates/protocol/versions',client=self.lead,**self.template(body='Changed exact outline'))
        self.assertEqual(status,200,catalog);latest=catalog['versions'][-1]
        self.assertEqual(latest['previousVersionId'],self.alex.request('/api/studies/atlas/templates/protocol/versions')[1][-2]['versionId'])
        status,study,_=self.post('/documents',title='Pinned newer definition',body='User edited text',templateId='protocol',templateVersionId=latest['versionId'])
        self.assertEqual(status,200);new=study['items'][-1]
        self.assertEqual(new['template']['versionId'],latest['versionId']);self.assertNotEqual(new['template']['sha256'],document['template']['sha256'])
        status,study,_=self.post('/documents/'+document['id']+'/versions',title='New document revision',body='New text')
        self.assertEqual(status,200);self.assertEqual(study['items'][-1]['template'],document['template'])
        self.assertEqual(self.post('/documents/'+document['id']+'/versions',title='Attempt switch',body='Text',templateVersionId=latest['versionId'])[0],400)
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1],snapshot)
        status,study,_=self.post('/documents',title='Legacy ID remains v1',body='Text',templateId='protocol')
        self.assertEqual(status,200);self.assertEqual(study['items'][-1]['template']['versionId'],original['versionId'])

    def test_resource_replacement_reverification_and_snapshot_are_immutable(self):
        original=self.create_resource();snapshot=self.capture([original['id']])
        payload=self.payload(**self.resource(url='https://example.invalid/two',ownerId='reviewer',reason='Owner supplied replacement'))
        path='/api/studies/atlas/resources/'+original['id']+'/replace'
        status,study,_=self.alex.request(path,payload);self.assertEqual(status,200,study);replacement=study['items'][-1]
        self.assertEqual(replacement['resource']['versionDetails']['previousVersionId'],original['id'])
        self.assertEqual(next(i for i in study['items'] if i['id']==original['id']),original)
        before=study['revision'];self.assertEqual(self.alex.request(path,payload)[0],200);self.assertEqual(self.study()['revision'],before)
        status,study,_=self.post('/resources/'+replacement['id']+'/reverify',lastVerified='2026-02-01',reason='Owner reported a local check')
        self.assertEqual(status,200,study);verified=study['items'][-1]
        self.assertEqual(verified['resource']['url'],replacement['resource']['url'])
        self.assertEqual(verified['resource']['versionDetails']['operation'],'Reverified')
        listing=self.alex.request('/api/studies/atlas/resources')[1]
        self.assertIn(verified['id'],[i['id'] for i in listing['current']])
        self.assertIn(original['id'],[i['id'] for i in listing['history']])
        detail=self.alex.request('/api/studies/atlas/resources/'+original['id'])[1]
        self.assertFalse(detail['current']);self.assertEqual(len(detail['history']),3)
        for item in (original,replacement,verified):
            self.assertEqual(self.post('/items/'+item['id']+'/delete')[0],409)
        self.assertEqual(self.post('/resources/'+original['id']+'/replace',**self.resource(reason='Attempt branch'))[0],409)
        self.assertEqual(self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1],snapshot)
        later=self.capture([verified['id']])
        self.assertTrue({original['id'],replacement['id'],verified['id']}.issubset({e['item']['id'] for e in later['items']}))

    def test_resource_revision_boundaries_current_owner_and_authorization(self):
        original=self.create_resource();path='/api/studies/atlas/resources/'+original['id']+'/replace'
        base=self.payload(**self.resource(reason='Update'))
        for changes in (dict(url='javascript:alert(1)'),dict(url='https://user:pass@example.invalid'),dict(ownerId='sam'),dict(lastVerified=None),dict(lastVerified='2999-01-01'),dict(reason=None),dict(reason=''),dict(source=None)):
            self.assertEqual(self.alex.request(path,dict(base,**changes))[0],400,changes)
        self.assertEqual(self.alex.request(path,base,csrf=False)[0],400)
        self.assertEqual(self.alex.request(path,dict(base,expectedRevision=0))[0],409)
        for client in (self.sam,self.admin):
            self.assertEqual(client.request(path,base)[0],404)
            self.assertEqual(client.request('/api/studies/atlas/resources/'+original['id'])[0],404)
        self.assertEqual(self.post('/resources/foreign/reverify',lastVerified='2026-01-01',reason='Invalid')[0],404)
        status,study,_=self.alex.request(path,base);self.assertEqual(status,200)
        self.assertEqual(self.alex.request(path,dict(base,reason='Changed replay'))[0],409)
        self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))[0],200)
        try:self.assertEqual(self.alex.request(path,base)[0],404)
        finally:self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))[0],200)

    def test_simultaneous_template_and_resource_writers_produce_one_successor(self):
        status,catalog,_=self.post('/templates',client=self.lead,**self.template())
        self.assertEqual(status,200);definition=catalog['versions'][-1]
        resource=self.create_resource()
        for path,client_id,fields in (('/templates/'+definition['id']+'/versions','lead',self.template()),
                                      ('/resources/'+resource['id']+'/replace','alex',self.resource(reason='Concurrent replacement'))):
            revision=self.study()['revision']
            requests=[dict(fields,title='Concurrent choice '+str(index),expectedRevision=revision,requestId=str(uuid.uuid4())) for index in range(2)]
            clients=[api.Client().login(client_id),api.Client().login(client_id)]
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(client.request,'/api/studies/atlas'+path,payload) for client,payload in zip(clients,requests)]
                results=[future.result() for future in futures]
            self.assertEqual(sorted(result[0] for result in results),[200,409])
            self.assertEqual(self.study()['revision'],revision+1)
            winner=0 if results[0][0]==200 else 1
            self.assertEqual(clients[winner].request('/api/studies/atlas'+path,requests[winner])[0],200)
            self.assertEqual(self.study()['revision'],revision+1)
        versions=self.alex.request('/api/studies/atlas/templates/'+definition['id']+'/versions')[1]
        self.assertEqual(len(versions),2)
        history=self.alex.request('/api/studies/atlas/resources/'+resource['id'])[1]['history']
        self.assertEqual(len(history),2)

    def test_closed_study_rejects_new_catalog_and_resource_changes(self):
        original=self.create_resource()
        self.assertEqual(self.post('/stage',stage='Closed')[0],200)
        try:
            self.assertEqual(self.post('/templates',client=self.lead,**self.template())[0],409)
            self.assertEqual(self.post('/resources/'+original['id']+'/reverify',lastVerified='2026-01-01',reason='New check')[0],409)
        finally:self.assertEqual(self.post('/stage',stage='Active')[0],200)

    def test_standalone_removed_resource_masks_snapshot_and_read_paths(self):
        original=self.create_resource();snapshot=self.capture([original['id']])
        self.assertEqual(self.post('/items/'+original['id']+'/delete')[0],200)
        self.assertEqual(self.alex.request('/api/studies/atlas/resources/'+original['id'])[0],404)
        self.assertEqual(self.post('/resources/'+original['id']+'/reverify',lastVerified='2026-01-01',reason='Removed')[0],404)
        detail=self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1]
        entry=next(e for e in detail['items'] if e['item']['id']==original['id'])
        self.assertFalse(entry['available']);self.assertNotIn('resource',entry['item'])

    def test_legacy_nested_resource_ancestor_masking_and_chain_retention(self):
        for chained in (False,True):
            status,study,_=self.post('/items',kind='discussion',title='Synthetic legacy resource parent',body='Legacy context')
            self.assertEqual(status,200);parent=study['items'][-1]
            resource=self.create_resource()
            # A stopped synthetic legacy fixture exercises nullable parent relationships
            # that native resource creation does not expose as an editing capability.
            self.stop()
            data=json.loads(self.data.read_bytes())
            stored=next(st for st in data['studies'] if st['id']=='atlas')
            next(item for item in stored['items'] if item['id']==resource['id'])['parentId']=parent['id']
            self.data.write_text(json.dumps(data));self.start()
            self.alex=api.Client().login('alex')
            if chained:
                status,study,_=self.post('/resources/'+resource['id']+'/reverify',lastVerified='2026-01-01',reason='Retain exact legacy context')
                self.assertEqual(status,200);successor=study['items'][-1]
                self.assertEqual(successor['parentId'],parent['id'])
                self.assertEqual(self.post('/items/'+parent['id']+'/delete')[0],409)
            else:
                snapshot=self.capture([resource['id']])
                self.assertEqual(self.post('/items/'+parent['id']+'/delete')[0],200)
                self.assertEqual(self.alex.request('/api/studies/atlas/resources/'+resource['id'])[0],404)
                self.assertEqual(self.post('/resources/'+resource['id']+'/reverify',lastVerified='2026-01-01',reason='Removed ancestor')[0],404)
                detail=self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1]
                entry=next(e for e in detail['items'] if e['item']['id']==resource['id'])
                self.assertFalse(entry['available']);self.assertNotIn('resource',entry['item'])

    def test_template_and_resource_history_survive_backup_restore(self):
        status,catalog,_=self.post('/templates',client=self.lead,**self.template())
        self.assertEqual(status,200);definition=catalog['versions'][-1]
        status,study,_=self.post('/documents',title='Recovery template document',body='Synthetic',templateVersionId=definition['versionId'])
        self.assertEqual(status,200);document=study['items'][-1]
        original=self.create_resource()
        status,study,_=self.post('/resources/'+original['id']+'/reverify',lastVerified='2026-01-01',reason='Synthetic repeated check')
        self.assertEqual(status,200);resource=study['items'][-1];snapshot=self.capture([document['id'],resource['id']])
        before=self.alex.request('/api/studies/atlas/templates/'+definition['id']+'/versions')[1]
        old_data=self.env['HUB_DATA'];old_files=self.env['HUB_FILES']
        self.stop()
        try:
            with tempfile.TemporaryDirectory(prefix='hub-history-recovery-') as temporary:
                root=Path(temporary);archive=root/'synthetic.zip';restores=root/'restores';restores.mkdir()
                def cli(*args):
                    result=subprocess.run([sys.executable,str(api.ROOT/'tools/backup_demo.py'),*map(str,args)],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr);return json.loads(result.stdout)
                cli('create','--state',old_data,'--blobs',old_files,'--output',archive,'--stopped')
                restored=cli('restore','--archive',archive,'--parent',restores,'--name','demo-restore-history','--stopped')
                self.env.update(HUB_DATA=restored['state'],HUB_FILES=restored['blobs']);self.start()
                try:
                    self.alex=api.Client().login('alex')
                    self.assertEqual(self.alex.request('/api/studies/atlas/templates/'+definition['id']+'/versions')[1],before)
                    self.assertEqual(next(i for i in self.study()['items'] if i['id']==document['id']),document)
                    self.assertEqual(self.alex.request('/api/studies/atlas/resources/'+resource['id'])[1]['item'],resource)
                    self.assertEqual(self.alex.request('/api/studies/atlas/handoffs/'+snapshot['id'])[1],snapshot)
                finally:self.stop()
        finally:
            self.env.update(HUB_DATA=old_data,HUB_FILES=old_files);self.start()

if __name__=='__main__':unittest.main(verbosity=2)
