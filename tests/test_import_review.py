"""Operator review is tracking, never a quarantine/access override. Real loopback HTTP."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import uuid
import test_api as api
import test_ingestion as ingestion


class ImportReview(unittest.TestCase):
    setUpClass = classmethod(ingestion.Ingestion.setUpClass.__func__)
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)

    def setUp(self):
        self.admin = api.Client().login('admin')
        self.alex = api.Client().login('alex')
        self.sam = api.Client().login('sam')
        self.assertEqual(self.admin.config('/api/admin/role', {'identity':'alex','role':'Administrator'})[0],200)
        self.manifest = json.loads((api.ROOT/'fixtures/app-import.json').read_text())
        record = next(r for r in self.manifest['records'] if r['kind']=='discussion')
        self.original_author = record['author_id']
        record.update(source_id='review-'+uuid.uuid4().hex, author_id='unresolved-synthetic-author', references=[])
        self.manifest['records']=[record]
        self.source = record['source_id']
        status,self.report,_=self.alex.request('/api/studies/atlas/imports/apply',dict(manifest=self.manifest,**self.write()))
        self.assertEqual(status,200,self.report)
        self.assertEqual(self.report['counts']['quarantined'],1)
        self.base='/api/studies/atlas/imports/'+self.report['id']

    def tearDown(self):
        # Restart cases invalidate server-held sessions; cleanup explicitly selects its actor.
        self.admin.login('admin')
        self.assertEqual(self.admin.config('/api/admin/role', {'identity':'alex','role':'Researcher'})[0],200)

    def write(self):
        return dict(expectedRevision=self.alex.request('/api/studies/atlas')[1]['revision'],requestId=str(uuid.uuid4()))
    def review(self,action='Assign',disposition='NeedsCorrection',**extra):
        payload=dict(sourceId=self.source,ownerId='alex',action=action,disposition=disposition,note='Synthetic operator review',**self.write())
        payload.update(extra)
        return self.alex.request(self.base+'/review',payload),payload
    def receipt(self):
        payload=self.write(); result=self.alex.request(self.base+'/receipts',payload)
        self.assertEqual(result[0],200,result[1]);return result[1],payload

    def test_immutable_receipt_replay_restart_and_disposition_not_acceptance(self):
        result,payload=self.review();self.assertEqual(result[0],200,result[1])
        replay=self.alex.request(self.base+'/review',payload);self.assertEqual(replay[0],200)
        self.assertEqual(len(replay[1]['case']['history']),1)
        self.assertEqual(self.review('Review')[0][0],200)
        first,_=self.receipt()
        self.assertEqual(self.review('Resolve','Excluded')[0][0],200)
        second,payload=self.receipt()
        self.assertEqual(first['cases'][0]['state'],'Reviewed')
        self.assertEqual(second['cases'][0]['state'],'Resolved')
        self.assertEqual(second['report']['counts']['quarantined'],1)
        self.assertEqual(self.alex.request(self.base+'/receipts',payload)[1],second)
        path='/api/studies/atlas/imports/receipts/'+first['id']
        self.assertEqual(self.alex.request(path)[1],first)
        export=self.alex.request(path+'/export');self.assertEqual(export[1],first)
        self.assertIn('attachment',export[2]['Content-Disposition'])
        self.assertNotIn('body',json.dumps(first));self.assertNotIn('content_base64',json.dumps(first))
        self.assertFalse(any((i.get('provenance') or {}).get('sourceId')==self.source for i in self.alex.request('/api/studies/atlas')[1]['items']))
        self.stop();self.start();self.alex=api.Client().login('alex')
        self.assertEqual(self.alex.request(path)[1],first)
        self.assertEqual(self.review('Reopen')[0][0],200)
        self.assertEqual(self.alex.request(path)[1],first)

    def test_auth_owner_csrf_stale_and_conflicting_replay(self):
        result,payload=self.review(ownerId='sam');self.assertEqual(result[0],400)
        result,payload=self.review();self.assertEqual(result[0],200)
        for client in (self.sam,self.admin):
            self.assertEqual(client.request(self.base+'/review',payload)[0],404)
            self.assertEqual(client.request('/api/studies/atlas/imports/review')[0],404)
        self.assertEqual(self.alex.request(self.base+'/review',dict(payload,note='changed'))[0],409)
        self.assertEqual(self.alex.request(self.base+'/review',dict(payload,requestId=str(uuid.uuid4())))[0],409)
        self.assertEqual(self.alex.request(self.base+'/review',payload,csrf=False)[0],400)
        self.admin.config('/api/admin/role',{'identity':'alex','role':'Researcher'})
        self.assertEqual(self.alex.request(self.base+'/review',payload)[0],404)
        self.admin.config('/api/admin/role',{'identity':'alex','role':'Administrator'})
        receipt,receipt_payload=self.receipt()
        self.admin.config('/api/admin/mapping',{'studyId':'atlas','groupId':'demo-group-b'})
        try:
            self.assertEqual(self.alex.request(self.base+'/receipts',receipt_payload)[0],404)
            self.assertEqual(self.alex.request('/api/studies/atlas/imports/receipts/'+receipt['id']+'/export')[0],404)
        finally:self.admin.config('/api/admin/mapping',{'studyId':'atlas','groupId':'demo-group-a'})

    def test_corrected_lineage_rejects_different_kind(self):
        self.assertEqual(self.review()[0][0],200)
        self.assertEqual(self.review('Resolve','CorrectedInLaterImport',successorReportId=self.report['id'])[0][0],400)
        different=copy.deepcopy(self.manifest);different['records'][0]['kind']='decision';different['records'][0]['author_id']=self.original_author
        status,wrong,_=self.alex.request('/api/studies/atlas/imports/apply',dict(manifest=different,**self.write()))
        self.assertEqual(status,200);self.assertEqual(wrong['counts']['imported'],1)
        self.assertEqual(self.review('Resolve','CorrectedInLaterImport',successorReportId=wrong['id'])[0][0],400)
        # A different source identity cannot be relabeled as the correction.
        self.assertEqual(self.review('Resolve','CorrectedInLaterImport',successorReportId=str(uuid.uuid4()))[0][0],400)

    def test_corrected_same_identity_records_receipt_without_rewriting_history(self):
        self.assertEqual(self.review()[0][0],200)
        before,_=self.receipt()
        corrected=copy.deepcopy(self.manifest);corrected['records'][0]['author_id']=self.original_author
        status,later,_=self.alex.request('/api/studies/atlas/imports/apply',dict(manifest=corrected,**self.write()))
        self.assertEqual(status,200);self.assertEqual(later['counts']['imported'],1)
        self.assertEqual(self.review('Resolve','CorrectedInLaterImport',successorReportId=later['id'])[0][0],200)
        after,_=self.receipt();self.assertEqual(after['cases'][0]['disposition'],'CorrectedInLaterImport')
        self.assertEqual(after['report']['counts']['quarantined'],1)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/receipts/'+before['id'])[1],before)

    def test_competing_review_writes_have_one_winner_and_stable_receipt(self):
        first=api.Client().login('alex');second=api.Client().login('alex')
        common=dict(sourceId=self.source,ownerId='alex',action='Assign',disposition='NeedsCorrection',**self.write())
        payloads=[dict(common,note='First concurrent synthetic assignment',requestId=str(uuid.uuid4())),
                  dict(common,note='Second concurrent synthetic assignment',requestId=str(uuid.uuid4()))]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(client.request,self.base+'/review',payload) for client,payload in zip((first,second),payloads)]
            results=[future.result() for future in futures]
        self.assertEqual(sorted(result[0] for result in results),[200,409])
        winner=next(index for index,result in enumerate(results) if result[0]==200)
        receipt,_=self.receipt()
        self.assertEqual(len(receipt['cases'][0]['history']),1)
        self.assertEqual(receipt['cases'][0]['history'][0]['note'],payloads[winner]['note'])
        replay=self.alex.request(self.base+'/review',payloads[winner]);self.assertEqual(replay[0],200)
        self.assertEqual(len(replay[1]['case']['history']),1)
        self.assertEqual(self.alex.request('/api/studies/atlas/imports/receipts/'+receipt['id'])[1],receipt)

    def test_correction_rejects_different_source_study(self):
        self.assertEqual(self.review()[0][0],200)
        different=copy.deepcopy(self.manifest)
        different['studies']['another-synthetic-source']='demo-group-a'
        different['records'][0]['study_id']='another-synthetic-source'
        different['records'][0]['author_id']=self.original_author
        status,later,_=self.alex.request('/api/studies/atlas/imports/apply',dict(manifest=different,**self.write()))
        self.assertEqual(status,200);self.assertEqual(later['counts']['imported'],1)
        self.assertEqual(self.review('Resolve','CorrectedInLaterImport',successorReportId=later['id'])[0][0],400)

    def test_legacy_report_cannot_claim_verified_correction(self):
        self.stop()
        state=json.loads(self.data.read_text());study=next(s for s in state['studies'] if s['id']=='atlas')
        legacy=next(r for r in study['importReports'] if r['id']==self.report['id'])
        legacy.pop('sha256',None)
        for outcome in legacy['outcomes']:
            for key in ('sourceStudyId','sourceKind','sourceRevision','sourceFingerprint'):outcome.pop(key,None)
        self.data.write_text(json.dumps(state));self.start();self.alex=api.Client().login('alex')
        self.assertEqual(self.review()[0][0],200)
        corrected=copy.deepcopy(self.manifest);corrected['records'][0]['author_id']=self.original_author
        status,later,_=self.alex.request('/api/studies/atlas/imports/apply',dict(manifest=corrected,**self.write()))
        self.assertEqual(status,200)
        self.assertEqual(self.review('Resolve','CorrectedInLaterImport',successorReportId=later['id'])[0][0],400)
        self.assertEqual(self.review('Resolve','Excluded')[0][0],200)

    def test_tampered_receipt_and_report_fail_closed(self):
        self.assertEqual(self.review()[0][0],200)
        receipt,payload=self.receipt();path='/api/studies/atlas/imports/receipts/'+receipt['id']
        self.stop();original=self.data.read_text()
        try:
            for field in ('importReceipts','importReports','importReviewEvents','nullOutcomes','nullReasons','nullEvents','overflowCounts'):
                state=json.loads(original);study=next(s for s in state['studies'] if s['id']=='atlas')
                if field=='importReceipts': next(r for r in study[field] if r['id']==receipt['id'])['scope']='tampered'
                elif field=='importReports':next(r for r in study[field] if r['id']==self.report['id'])['manifestSha256']='tampered'
                elif field=='importReviewEvents':study[field][-1]['note']='tampered'
                elif field=='nullOutcomes':next(r for r in study['importReports'] if r['id']==self.report['id'])['outcomes']=None
                elif field=='nullReasons':
                    report=next(r for r in study['importReports'] if r['id']==self.report['id'])
                    report.pop('sha256',None);report['outcomes'][0]['reasons']=None
                elif field=='nullEvents':study['importReviewEvents']=None
                else:
                    report=next(r for r in study['importReports'] if r['id']==self.report['id'])
                    report['counts']={'quarantined':2147483647,'imported':2147483647}
                self.data.write_text(json.dumps(state));self.start();self.alex=api.Client().login('alex')
                self.assertEqual(self.alex.request(path)[0],503)
                self.assertEqual(self.alex.request(path+'/export')[0],503)
                self.assertEqual(self.alex.request('/api/studies/atlas/imports')[0],503)
                self.assertEqual(self.alex.request(self.base+'/receipts',payload)[0],503)
                self.stop()
        finally:
            self.data.write_text(original);self.start();self.alex=api.Client().login('alex')


if __name__=='__main__':unittest.main()
