"""Isolated metadata rehearsal never changes live content or attachment bytes."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import uuid
import test_api as api
import test_ingestion as ingestion


class MigrationRehearsal(unittest.TestCase):
    setUpClass=classmethod(ingestion.Ingestion.setUpClass.__func__)
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)

    def setUp(self):
        self.admin=api.Client().login('admin');self.alex=api.Client().login('alex')
        self.assertEqual(self.admin.config('/api/admin/role',{'identity':'alex','role':'Administrator'})[0],200)
        self.backup=self.data.read_text()
        self.manifest=json.loads((api.ROOT/'fixtures/app-import.json').read_text())
        self.prefix=uuid.uuid4().hex[:10]+'-'
        for record in self.manifest['records']:
            record['source_id']=self.prefix+record['source_id']
            if record.get('parent_id'):record['parent_id']=self.prefix+record['parent_id']
            record['references']=[self.prefix+r for r in record.get('references',[])]
        self.base='/api/studies/atlas/imports/rehearsals'
        self.original=self.content()
        self.original_blobs=self.blob_bytes()

    def tearDown(self):
        self.stop();self.data.write_text(self.backup);self.start()

    def content(self):
        study=next(s for s in json.loads(self.data.read_text())['studies'] if s['id']=='atlas')
        return {name:study[name] for name in ('items','files','importLedger','importReports','currentProtocol','documentReviews')}
    def blob_bytes(self):return {str(p.relative_to(self.blobs)):p.read_bytes() for p in self.blobs.rglob('*') if p.is_file()} if self.blobs.exists() else {}
    def create(self,manifest=None):
        payload=dict(manifest=manifest or self.manifest,expectedRevision=self.alex.request('/api/studies/atlas')[1]['revision'],requestId=str(uuid.uuid4()))
        status,session,_=self.alex.request(self.base,payload);self.assertEqual(status,200,session)
        return session,payload
    def action(self,session,action,manifest=None,client=None):
        payload=dict(action=action,expectedRevision=session['revision'],requestId=str(uuid.uuid4()))
        if manifest is not None:payload['manifest']=manifest
        result=(client or self.alex).request(self.base+'/'+session['id']+'/actions',payload)
        return result,payload
    def ok_action(self,session,action,manifest=None):
        result,payload=self.action(session,action,manifest);self.assertEqual(result[0],200,result[1]);return result[1],payload
    def unchanged(self):
        self.assertEqual(self.content(),self.original)
        self.assertEqual(self.blob_bytes(),self.original_blobs)

    def test_morning_fixtures_reconcile_without_live_changes(self):
        original=json.loads((api.ROOT/'fixtures/app-import.json').read_text())
        delta=json.loads((api.ROOT/'fixtures/app-import-delta-conflict.json').read_text())
        exception=json.loads((api.ROOT/'fixtures/app-import-exception.json').read_text())
        session,_=self.create(original)
        self.assertEqual(session['report']['counts']['imported'],7)
        session,_=self.ok_action(session,'Apply')
        session,_=self.ok_action(session,'Delta',delta)
        self.assertEqual(session['report']['inputCount'],7)
        self.assertGreaterEqual(session['report']['counts']['quarantined'],1)
        session,_=self.ok_action(session,'Rollback')
        self.assertEqual(session['branchSha256'],session['baselineSha256'])
        blocked,_=self.create(exception)
        self.assertEqual(blocked['report']['inputCount'],1)
        self.assertEqual(blocked['report']['counts']['quarantined'],1)
        self.assertTrue(any('author' in reason for row in blocked['inventory'] for reason in row['reasons']))
        self.unchanged()

    def test_inventory_abort_retry_apply_rollback_restart_no_live_changes(self):
        session,payload=self.create()
        self.assertEqual(session['report']['inputCount'],7);self.assertEqual(len(session['inventory']),7)
        self.assertEqual(sum(session['report']['counts'].values()),7)
        self.assertEqual(sum(r['kind']=='version' for r in session['inventory']),2)
        self.assertTrue(all(r['groupMappingValid'] for r in session['inventory']))
        self.assertTrue(any(r['referenceIds'] for r in session['inventory']))
        self.assertNotIn('branch',session);self.assertNotIn('baseline',session);self.assertNotIn('manifest',session)
        self.assertEqual(self.alex.request(self.base,payload)[1],session)
        baseline=session['branchSha256'];self.unchanged()
        session,_=self.ok_action(session,'Abort');self.assertEqual(session['state'],'Aborted')
        self.assertEqual(self.action(session,'Apply')[0][0],409)
        session,_=self.ok_action(session,'Retry');self.assertEqual(session['state'],'Ready')
        session,apply_payload=self.ok_action(session,'Apply');self.assertEqual(session['state'],'Applied')
        self.assertNotEqual(session['branchSha256'],baseline);self.unchanged()
        self.assertEqual(self.alex.request(self.base+'/'+session['id']+'/actions',apply_payload)[1],session)
        session,_=self.ok_action(session,'Rollback');self.assertEqual(session['branchSha256'],baseline)
        self.unchanged()
        self.stop();self.start();self.alex=api.Client().login('alex')
        self.assertEqual(self.alex.request(self.base+'/'+session['id'])[1],session)
        status,export,headers=self.alex.request(self.base+'/'+session['id']+'/export')
        self.assertEqual(status,200);self.assertEqual(export['receipt'],session)
        self.assertEqual(len(export['receiptSha256']),64);self.assertIn('attachment',headers['Content-Disposition'])
        self.assertNotIn('content_base64',json.dumps(export));self.assertNotIn('"body"',json.dumps(export))
        self.assertNotIn('migrationRehearsals',self.alex.request('/api/studies/atlas')[1])

    def test_delta_conflict_tombstone_and_no_resurrection(self):
        session,_=self.create();session,_=self.ok_action(session,'Apply')
        conflict=copy.deepcopy(self.manifest)
        thread=next(r for r in conflict['records'] if r['kind']=='discussion');thread['body']='Conflicting same revision'
        session,_=self.ok_action(session,'Delta',conflict)
        self.assertIn('revision_conflict',next(r for r in session['inventory'] if r['sourceId']==thread['source_id'])['reasons'])
        session,_=self.ok_action(session,'Apply')
        deleted=copy.deepcopy(self.manifest)
        for record in deleted['records']:record.update(deleted=True,revision=2)
        session,_=self.ok_action(session,'Delta',deleted);session,_=self.ok_action(session,'Apply')
        self.assertGreater(session['report']['counts']['deleted'],0)
        resurrection=copy.deepcopy(self.manifest)
        for record in resurrection['records']:record['revision']=3
        session,_=self.ok_action(session,'Delta',resurrection)
        self.assertTrue(any('tombstone_blocks_resurrection' in r['reasons'] for r in session['inventory']))
        self.unchanged()

    def test_unknown_mapping_and_author_quarantine_never_overridden(self):
        manifest=copy.deepcopy(self.manifest);manifest['studies']['synthetic-study']='unresolved-group'
        manifest['records'][0]['author_id']='unknown-author'
        manifest['records'][0]['legacy_url']='https://example.invalid/'+('x'*2001)
        manifest['records'][0]['references']=['invalid reference with spaces',42]
        session,_=self.create(manifest)
        self.assertEqual(session['report']['counts']['quarantined'],7)
        self.assertTrue(all(not r['groupMappingValid'] for r in session['inventory']))
        first=next(r for r in session['inventory'] if r['sourceId']==manifest['records'][0]['source_id'])
        self.assertEqual(first['legacyUrlStatus'],'UnsupportedReference');self.assertEqual(first['unsupportedReferenceCount'],2)
        session,_=self.ok_action(session,'Apply')
        self.assertEqual(session['branchSummary']['ledgerEntries'],0)
        self.unchanged()

    def test_membership_revocation_csrf_stale_and_concurrent_action(self):
        session,_=self.create()
        payload=dict(action='Apply',expectedRevision=session['revision'],requestId=str(uuid.uuid4()))
        path=self.base+'/'+session['id']+'/actions'
        self.assertEqual(self.alex.request(path,payload,csrf=False)[0],400)
        for actor in ('sam','admin'):
            client=api.Client().login(actor)
            self.assertEqual(client.request(self.base+'/'+session['id'])[0],404)
            self.assertEqual(client.request(path,payload)[0],404)
        clients=[api.Client().login('alex'),api.Client().login('alex')]
        payloads=[payload,dict(payload,action='Abort',requestId=str(uuid.uuid4()))]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(c.request,path,p) for c,p in zip(clients,payloads)]
            results=[f.result() for f in futures]
        self.assertEqual(sorted(r[0] for r in results),[200,409])
        winner=next(i for i,r in enumerate(results) if r[0]==200)
        self.assertEqual(self.alex.request(path,payloads[winner])[0],200)
        self.assertEqual(self.alex.request(path,dict(payloads[winner],action='Retry'))[0],409)
        self.admin.config('/api/admin/role',{'identity':'alex','role':'Researcher'})
        self.assertEqual(self.alex.request(path,payloads[winner])[0],404)
        self.admin.config('/api/admin/role',{'identity':'alex','role':'Administrator'})
        self.admin.config('/api/admin/mapping',{'studyId':'atlas','groupId':'demo-group-b'})
        self.assertEqual(self.alex.request(self.base+'/'+session['id']+'/export')[0],404)
        self.unchanged()

    def test_bad_manifest_and_stale_group_mapping_fail_closed(self):
        revision=self.alex.request('/api/studies/atlas')[1]['revision']
        for manifest in ('missing',None,[],42):
            payload=dict(expectedRevision=revision,requestId=str(uuid.uuid4()))
            if manifest!='missing':payload['manifest']=manifest
            self.assertEqual(self.alex.request(self.base,payload)[0],400)
            self.assertEqual(self.alex.request('/api/studies/atlas')[1]['revision'],revision)
        session,_=self.create()
        self.assertTrue(any(r['legacyUrlStatus']=='RecordedHttpReferenceNotFetched' for r in session['inventory']))
        self.admin.config('/api/admin/mapping',{'studyId':'atlas','groupId':'demo-group-b'})
        self.admin.config('/api/admin/role',{'identity':'sam','role':'Administrator'})
        sam=api.Client().login('sam')
        view=sam.request(self.base+'/'+session['id']);self.assertEqual(view[0],200)
        self.assertFalse(view[1]['groupMappingCurrent']);self.assertEqual(view[1]['allowedActions'],[])
        self.assertEqual(self.action(session,'Apply',client=sam)[0][0],409)
        self.unchanged()

    def test_corrupt_lineage_and_private_branch_are_not_exported(self):
        session,_=self.create();session,payload=self.ok_action(session,'Apply')
        self.stop();before=self.data.read_text()
        try:
            for corruption in ('branch','history','null'):
                data=json.loads(before);study=next(s for s in data['studies'] if s['id']=='atlas');stored=study['migrationRehearsals'][0]
                if corruption=='branch':stored['branch']['items'][0]['body']='CORRUPTED PRIVATE BODY'
                elif corruption=='history':stored['history'][1]['previousSha256']='tampered'
                else:stored['history']=None
                self.data.write_text(json.dumps(data));self.start();self.alex=api.Client().login('alex')
                for path in (self.base,self.base+'/'+session['id'],self.base+'/'+session['id']+'/export'):
                    response=self.alex.request(path);self.assertEqual(response[0],503);self.assertNotIn('CORRUPTED PRIVATE BODY',json.dumps(response[1]))
                self.assertEqual(self.alex.request(self.base+'/'+session['id']+'/actions',payload)[0],503)
                self.stop()
        finally:self.data.write_text(before);self.start()
        self.unchanged()


if __name__=='__main__':unittest.main()
