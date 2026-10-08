"""Exact local migrated-link resolution; no redirect, external fetch or permission expansion."""
import copy
import json
import unittest
import urllib.parse
import uuid
import test_api as api
import test_ingestion as ingestion

class MigratedLinks(unittest.TestCase):
    setUpClass=classmethod(ingestion.Ingestion.setUpClass.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    study=ingestion.Ingestion.study
    payload=ingestion.Ingestion.payload
    apply=ingestion.Ingestion.apply
    def setUp(self):
        ingestion.Ingestion.setUp(self)
        for record in self.manifest['records']:
            record['legacy_url']='https://example.invalid/history/'+record['source_id']+'?version='+record['kind']
        _,self.report=self.apply()
    def source(self,kind):return next(r for r in self.manifest['records'] if r['kind']==kind)
    def resolve(self,record=None,client=None,**changes):
        record=record or self.source('discussion')
        params=dict(studyId='atlas',sourceStudyId=record['study_id'],sourceId=record['source_id'])
        params.update(changes)
        return (client or self.alex).request('/api/resolve?'+urllib.parse.urlencode(params))
    def url(self,url,client=None):
        return (client or self.alex).request('/api/resolve?'+urllib.parse.urlencode(dict(studyId='atlas',sourceUrl=url)))
    def test_each_item_version_and_link_resolves_exact_local_target(self):
        for record in self.manifest['records']:
            status,result,headers=self.resolve(record)
            self.assertEqual(status,200,result)
            target=next(o['targetId'] for o in self.report['outcomes'] if o['sourceId']==record['source_id'])
            self.assertTrue(result['href'].startswith('#study/atlas/'))
            self.assertTrue(result['href'].endswith('/'+target))
            self.assertNotIn('Location',headers)
            self.assertEqual(self.url(record['legacy_url'])[1],result)
            self.assertEqual(self.url(record['legacy_url']+'&different=1')[0],404)
        versions=[self.resolve(r)[1] for r in self.manifest['records'] if r['kind']=='version']
        self.assertEqual({v['version'] for v in versions},{1,2})
        self.assertEqual(len({v['href'] for v in versions}),2)
        self.stop();self.start();self.alex=api.Client().login('alex')
        self.assertEqual(self.resolve()[0],200)
    def test_unknown_inaccessible_and_revoked_have_same_response(self):
        missing=self.resolve(sourceId='missing-source')[1]
        for client in (self.sam,self.admin):
            status,result,_=self.resolve(client=client)
            self.assertEqual(status,404);self.assertEqual(result,missing)
        self.assertEqual(self.resolve(studyId='unknown-study')[1],missing)
        self.assertEqual(self.resolve(studyId='beacon')[1],missing)
        self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))[0],200)
        try:
            self.assertEqual(self.resolve()[1],missing)
            self.assertEqual(self.resolve(client=self.sam)[0],200)
        finally:self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))
    def test_file_integrity_release_and_deleted_targets_fail_closed(self):
        record=self.source('attachment');target=next(o['targetId'] for o in self.report['outcomes'] if o['sourceId']==record['source_id'])
        path=self.blobs/(target+'.blob');original=path.read_bytes()
        try:
            path.write_bytes(b'corrupted synthetic evidence')
            self.assertEqual(self.resolve(record)[0],404)
        finally:path.write_bytes(original)
        self.assertEqual(self.resolve(record)[0],200)
        payload=dict(expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/files/'+target+'/delete',payload)[0],200)
        self.assertEqual(self.resolve(record)[0],404)
    def test_removed_ancestor_masks_record_and_url(self):
        record=self.source('reply');parent_id=next(o['targetId'] for o in self.report['outcomes'] if o['sourceId']==record['parent_id'])
        self.stop();state=json.loads(self.data.read_text());study=next(s for s in state['studies'] if s['id']=='atlas')
        next(item for item in study['items'] if item['id']==parent_id)['deleted']=True
        self.data.write_text(json.dumps(state));self.start();self.alex=api.Client().login('alex')
        self.assertEqual(self.resolve(record)[0],404)
        self.assertEqual(self.url(record['legacy_url'])[0],404)
    def test_ambiguous_legacy_url_and_unresolved_source_are_unavailable(self):
        first=self.source('discussion');second=copy.deepcopy(first)
        second['source_id']='ambiguous-'+uuid.uuid4().hex;second['references']=[]
        manifest=copy.deepcopy(self.manifest);manifest['records']=[second]
        _,report=self.apply(manifest)
        self.assertEqual(report['counts']['imported'],1)
        self.assertEqual(self.url(first['legacy_url'])[0],404)
        self.assertEqual(self.resolve(first)[0],200)
        second['source_id']='unresolved-'+uuid.uuid4().hex;second['author_id']='unknown-synthetic-author';second['legacy_url']+='&unresolved=1'
        _,report=self.apply(manifest)
        self.assertEqual(report['counts']['quarantined'],1)
        self.assertEqual(self.resolve(second)[0],404)
        self.assertEqual(self.url(second['legacy_url'])[0],404)
    def test_invalid_parameters_and_redirect_payloads(self):
        for extra in ('','studyId=atlas','studyId=atlas&sourceId=x','studyId=atlas&sourceId=x&sourceStudyId=y&sourceId=z',
                      'studyId=atlas&sourceUrl=javascript%3Aalert(1)','studyId=atlas&sourceUrl=%2F%2Fevil.example',
                      'studyId=atlas&sourceUrl=https%3A%2F%2Fu%3Ap%40example.invalid',
                      'studyId=atlas&sourceUrl=https%3A%2F%2Fexample.invalid&sourceId=x',
                      'studyId=atlas&sourceStudyId=x&sourceId=y&redirect=https%3A%2F%2Fexample.invalid',
                      'studyId=atlas&sourceStudyId=x&sourceId=%0A',
                      'studyId=atlas&sourceStudyId=x&sourceId='+'x'*201):
            self.assertEqual(self.alex.request('/api/resolve?'+extra)[0],400,extra)
        status,body,headers=self.url('https://example.invalid/?next=https://untrusted.invalid')
        self.assertEqual(status,404);self.assertNotIn('Location',headers)
        self.assertNotIn('untrusted.invalid',json.dumps(body))

if __name__=='__main__':unittest.main(verbosity=2)
