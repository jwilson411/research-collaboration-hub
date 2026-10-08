"""Adversarial pagination, interrupted requests, session revocation, and boundary checks."""
from concurrent.futures import ThreadPoolExecutor
import base64
import json
import unittest
import urllib.parse
import uuid
import test_api as api
import test_attachments as attachments


class Milestone7Security(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    setUpClass = classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)
    setUp = api.Integration.setUp
    study = api.Integration.study
    item = api.Integration.item

    def add(self, **changes):
        payload=self.item(**changes)
        status, result, _=self.alex.request('/api/studies/atlas/items',payload)
        self.assertEqual(status,200,result)
        return payload,result['items'][-1]

    def test_search_more_than_one_hundred_complete_and_permission_scoped(self):
        marker='Paging-'+uuid.uuid4().hex
        ids=set()
        for n in range(107):
            _, record=self.add(title=f'{marker} {n:03}',body='Synthetic pagination record')
            ids.add(record['id'])
        query='/api/search?q='+marker
        status, legacy, headers=self.alex.request(query)
        self.assertEqual(status,200);self.assertEqual(len(legacy),100)
        self.assertEqual(headers['X-Total-Count'],'107');self.assertEqual(headers['X-Results-Truncated'],'true')
        collected=[]
        for page in range(1,6):
            status,result,_=self.alex.request(query+f'&page={page}&pageSize=25')
            self.assertEqual(status,200);self.assertEqual(result['total'],107)
            self.assertEqual(result['page'],page);self.assertEqual(result['pageSize'],25)
            self.assertEqual(result['hasMore'],page<5)
            collected.extend(hit['item']['id'] for hit in result['items'])
        self.assertEqual(set(collected),ids);self.assertEqual(len(collected),107)
        self.assertEqual(collected,sorted(collected))
        self.assertEqual(self.alex.request(query+'&page=100000&pageSize=100')[1]['items'],[])
        for client in (self.sam,self.admin):
            result=client.request(query+'&page=1')[1]
            self.assertEqual(result['total'],0);self.assertEqual(result['items'],[])
        first=self.alex.request(query+'&page=1&pageSize=25')[1]
        self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))[0],200)
        try:
            self.assertEqual(self.alex.request(query+'&page=2&pageSize=25')[1]['total'],0)
            self.assertEqual(self.sam.request(query+'&page=1&pageSize=100')[1]['total'],107)
        finally:
            self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))[0],200)
        self.assertEqual(self.alex.request(query+'&page=1&pageSize=25')[1],first)

    def test_search_parameter_bounds_are_explicit(self):
        for suffix in ('page=0','page=-1','page=100001','page=2147483648','page=null','page=',
                       'page=1.2','page=+1','page=1&page=2','pageSize=0','pageSize=101',
                       'pageSize=null','pageSize=','pageSize=10&pageSize=20','q=a&q=b'):
            self.assertEqual(self.alex.request('/api/search?'+suffix)[0],400,suffix)
        self.assertEqual(self.alex.request('/api/search?q='+'a'*200+'&page=1')[0],200)
        self.assertEqual(self.alex.request('/api/search?q='+'a'*201+'&page=1')[0],400)
        result=self.alex.request('/api/search?pageSize=1')[1]
        self.assertEqual(result['page'],1);self.assertEqual(result['pageSize'],1)

    def test_concurrent_writers_and_exact_retry_after_restart(self):
        other=api.Client().login('alex')
        left=self.item(title='Concurrent A '+uuid.uuid4().hex)
        right=dict(left,title='Concurrent B '+uuid.uuid4().hex,requestId=str(uuid.uuid4()))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(client.request,'/api/studies/atlas/items',payload)
                     for client,payload in ((self.alex,left),(other,right))]
            responses=[f.result() for f in futures]
        self.assertEqual(sorted(r[0] for r in responses),[200,409])
        winner=left if responses[0][0]==200 else right
        before=self.study()
        self.stop();self.start()
        self.alex=api.Client().login('alex')
        self.assertEqual(self.alex.request('/api/studies/atlas/items',winner)[0],200)
        self.assertEqual(self.study(),before)
        self.assertEqual(self.alex.request('/api/studies/atlas/items',dict(winner,body='Mismatched retry'))[0],409)

    def test_switched_session_and_revoked_mapping_deny_stale_retry(self):
        payload,item=self.add(title='Session-bound synthetic record')
        self.alex.login('sam')
        self.assertEqual(self.alex.request('/api/studies/atlas/items',payload)[0],404)
        self.assertEqual(self.alex.request('/api/studies/atlas')[0],404)
        self.alex.login('alex')
        self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))[0],200)
        try:
            self.assertEqual(self.alex.request('/api/studies/atlas/items',payload)[0],404)
            self.assertEqual(self.alex.request('/api/studies/atlas/documents/protocol-1/download')[0],404)
        finally:
            self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))[0],200)
        before=self.study()['revision']
        self.assertEqual(self.alex.request('/api/studies/atlas/items',payload)[0],200)
        self.assertEqual(self.study()['revision'],before)

    def test_deleted_ancestor_masks_descendant_search_and_download(self):
        marker='Removed-'+uuid.uuid4().hex
        _,parent=self.add(title='Parent '+marker)
        _,reply=self.add(kind='reply',title='Reply '+marker,parentId=parent['id'])
        _,document=self.add(kind='document',title='Document '+marker,body=marker,parentId=reply['id'])
        uploaded=dict(name=marker+'.txt',contentBase64=base64.b64encode(marker.encode()).decode(),parentId=reply['id'],
                      expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/files',uploaded)
        self.assertEqual(status,200);file=study['files'][-1]
        self.assertEqual(self.alex.request('/api/studies/atlas/items/'+parent['id']+'/delete',
            dict(expectedRevision=study['revision'],requestId=str(uuid.uuid4())))[0],200)
        page=self.alex.request('/api/search?q='+marker+'&page=1')[1]
        self.assertEqual(page['total'],0)
        for path in (f'/documents/{document["id"]}/download',f'/files/{file["id"]}/download'):
            self.assertEqual(self.alex.request('/api/studies/atlas'+path)[0],404)
        self.assertNotIn(marker,json.dumps(self.alex.request('/api/studies/atlas')[1]))
        self.assertNotIn(marker,json.dumps(self.alex.request('/api/studies/atlas/documents')[1]))

    def test_interrupted_local_persistence_fails_closed_and_same_request_recovers(self):
        before=self.study()
        prior_bytes=self.data.read_bytes()
        pending=self.data.with_name(self.data.name+'.tmp')
        self.assertFalse(pending.exists())
        pending.mkdir()
        request=self.item(title='Recoverable persistence interruption')
        try:
            status,response,_=self.alex.request('/api/studies/atlas/items',request)
            self.assertEqual(status,503)
            self.assertIn('not saved',response['error'])
            self.assertNotIn(str(self.data),json.dumps(response))
            self.assertNotIn('StackTrace',json.dumps(response))
            self.assertEqual(self.study(),before)
            self.assertEqual(self.data.read_bytes(),prior_bytes)
            self.assertTrue(pending.is_dir())
        finally:
            pending.rmdir()
        self.assertEqual(self.alex.request('/api/studies/atlas/items',request)[0],200)
        after=self.study()
        self.assertEqual(after['revision'],before['revision']+1)
        self.assertEqual(self.alex.request('/api/studies/atlas/items',request)[0],200)
        self.assertEqual(self.study(),after)

    def test_url_configuration_cannot_override_fixed_loopback_listener(self):
        self.stop()
        previous=self.env.get('ASPNETCORE_URLS')
        self.env['ASPNETCORE_URLS']='http://127.0.0.1:5081'
        try:
            self.start()  # Helper requires the exact 127.0.0.1:5080 startup message and healthy API.
            self.assertEqual(api.Client().request('/api/session')[0],200)
        finally:
            if previous is None:self.env.pop('ASPNETCORE_URLS',None)
            else:self.env['ASPNETCORE_URLS']=previous

    def test_input_limits_unknown_api_and_recoverable_validation(self):
        before=self.study()['revision']
        for changes in (dict(title=None),dict(body=None),dict(title='x'*181),dict(body='x'*20001)):
            self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(**changes))[0],400)
        self.assertEqual(self.study()['revision'],before)
        self.assertEqual(self.alex.request('/api/studies/atlas/items',self.item(body='x'*1048576))[0],413)
        self.assertEqual(self.study()['revision'],before)
        self.add(title='x'*180,body='x'*20000)
        for method,payload in (('GET',None),('POST',{})):
            status,result,headers=self.alex.request('/api/nonexistent-endpoint',payload,method=method)
            self.assertEqual(status,404);self.assertIsInstance(result,dict)
            self.assertIn('application/json',headers['Content-Type'])
        self.assertEqual(self.alex.request('/api/nonexistent-endpoint',{},csrf=False)[0],400)
        self.assertEqual(self.alex.request('/local-spa-route')[0],200)


if __name__=='__main__':unittest.main(verbosity=2)
