"""Bounded filtered retrieval across synthetic live study records."""
import json
import unittest
import urllib.parse
import uuid
import test_api as api

class SearchFilters(unittest.TestCase):
    setUpClass=classmethod(api.Integration.setUpClass.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    setUp=api.Integration.setUp
    study=api.Integration.study
    item=api.Integration.item

    def search(self,client=None,**params):
        return (client or self.alex).request('/api/search?'+urllib.parse.urlencode(dict(page=1,pageSize=25,**params)))
    def add(self,kind='discussion',**changes):
        payload=self.item(kind=kind,**changes)
        status,state,_=self.alex.request('/api/studies/atlas/items',payload)
        self.assertEqual(status,200,state)
        return state['items'][-1]

    def test_types_and_study_filters_preserve_exact_context(self):
        marker='Kinds-'+uuid.uuid4().hex
        expected={}
        for kind in ('document','documentation','discussion','reply','decision','idea'):
            extra={'parentId':expected['discussion']['id']} if kind=='reply' else {}
            expected[kind]=self.add(kind,title=marker+' '+kind,body='Synthetic context',**extra)
        for kind,item in expected.items():
            status,result,_=self.search(q=marker,kind=kind,studyId='atlas')
            self.assertEqual(status,200);self.assertEqual(result['total'],1)
            self.assertEqual(result['items'][0]['item']['id'],item['id'])
            self.assertEqual(result['items'][0]['studyTitle'],self.study()['title'])
        result=self.search(q=marker)[1]
        self.assertEqual(result['total'],6)
        self.assertEqual({x['id'] for x in result['facets']['studies']},{'atlas'})

    def test_task_metadata_and_current_body_only(self):
        marker='Task-'+uuid.uuid4().hex
        payload=dict(title=marker,body='Old private revision marker '+marker,status='Blocked',assignee='reviewer',dueDate='2027-04-19',links=[],expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/tasks',payload)
        self.assertEqual(status,200);task=study['items'][-1]
        for query in ('Blocked','reviewer','Casey','2027-04-19'):
            found=self.search(q=query,kind='task')[1]
            self.assertIn(task['id'],[h['item']['id'] for h in found['items']])
        update=dict(payload,body='New current body',status='Done',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request('/api/studies/atlas/tasks/'+task['id'],update)[0],200)
        result=self.search(q=marker,kind='task')[1]
        encoded=json.dumps(result)
        self.assertNotIn('Old private revision',encoded);self.assertNotIn('history',encoded)
        self.assertIn('Status: Done',encoded)
        self.assertEqual(self.search(q='Old private revision marker '+marker,kind='task')[1]['total'],0)

    def test_resource_metadata_is_bounded_and_not_fetched(self):
        marker='Source-'+uuid.uuid4().hex
        payload=dict(title='Recorded pointer',body='x'*1000+' matchingneedle '+ 'y'*1000,url='https://example.invalid/'+marker,ownerId='alex',source=marker,lastVerified='2026-01-01',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/resources',payload)
        self.assertEqual(status,200);record=study['items'][-1]
        for query in (marker,'matchingneedle'):
            hit=next(h for h in self.search(q=query,kind='resource')[1]['items'] if h['item']['id']==record['id'])
            self.assertLessEqual(len(hit['item']['body']),362)
            self.assertLessEqual(len(hit['context']),362)
        self.assertIn('matchingneedle',self.search(q='matchingneedle',kind='resource')[1]['items'][0]['item']['body'])

    def test_decision_template_and_retained_resource_metadata(self):
        marker='Evidence-'+uuid.uuid4().hex
        decision=dict(title='Decision metadata',rationale='Choose a synthetic path',alternatives=marker,ownerId='reviewer',effectiveDate='2026-01-01',itemIds=[],fileIds=[],reason='Initial decision',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/decisions',decision)
        self.assertEqual(status,200,study);decision_id=study['item']['id']
        self.assertIn(decision_id,[h['item']['id'] for h in self.search(q=marker,kind='decision')[1]['items']])
        self.assertIn(decision_id,[h['item']['id'] for h in self.search(q='Casey',kind='decision')[1]['items']])
        document=dict(title='Template search record',body='Synthetic text',templateId='protocol',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/documents',document)
        self.assertEqual(status,200,study);document_id=study['items'][-1]['id']
        self.assertIn(document_id,[h['item']['id'] for h in self.search(q='Study protocol',kind='document')[1]['items']])
        resource=dict(title='Retained source',body='Earlier pointer',url=None,ownerId='alex',source=marker+' oldsource',lastVerified='2026-01-01',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/resources',resource)
        self.assertEqual(status,200,study);resource_id=study['items'][-1]['id']
        replacement=dict(resource,source='New source',reason='Synthetic replacement',expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4()))
        status,study,_=self.alex.request('/api/studies/atlas/resources/'+resource_id+'/replace',replacement)
        self.assertEqual(status,200,study)
        hits=self.search(q=marker+' oldsource',kind='resource')[1]['items']
        self.assertEqual([h['item']['id'] for h in hits],[resource_id])
        self.assertIn('oldsource',hits[0]['context'])

    def test_inaccessible_unknown_and_revoked_filters_do_not_leak(self):
        unknown=self.search(studyId='unknown-study')[1]
        denied=self.search(studyId='beacon')[1]
        self.assertEqual(unknown,denied);self.assertEqual(denied['facets'],dict(studies=[],kinds=[]))
        self.assertEqual(self.search(client=self.admin)[1]['facets'],dict(studies=[],kinds=[]))
        self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-b'))[0],200)
        try:
            self.assertEqual(self.search(studyId='atlas')[1],unknown)
            self.assertEqual(self.search()[1]['total'],0)
        finally:
            self.assertEqual(self.admin.config('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))[0],200)

    def test_removed_ancestor_masks_child_snippet_and_kind(self):
        marker='Ancestor-'+uuid.uuid4().hex
        parent=self.add(title='Disposable parent')
        child=self.add('reply',title=marker,body=marker,parentId=parent['id'])
        self.assertEqual(self.search(q=marker,kind='reply')[1]['total'],1)
        self.assertEqual(self.alex.request('/api/studies/atlas/items/'+parent['id']+'/delete',dict(expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))[0],200)
        self.assertNotIn(marker,json.dumps(self.search(q=marker)[1]))
        self.assertEqual(self.search(q=marker,kind='reply')[1]['total'],0)

    def test_invalid_filters_and_unknown_parameters_fail_cleanly(self):
        for suffix in ('kind=unknown','kind=','kind=task&kind=idea','studyId=','studyId=atlas&studyId=beacon','studyId='+'x'*101,'owner=alex','kind=%00'):
            self.assertEqual(self.alex.request('/api/search?page=1&'+suffix)[0],400,suffix)
        self.assertEqual(self.search(q='',kind='task')[0],200)

if __name__=='__main__':unittest.main(verbosity=2)
