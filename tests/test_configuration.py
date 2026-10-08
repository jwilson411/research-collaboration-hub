"""Synthetic admin concurrency/replay security regressions; exclusive loopback5080."""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import uuid
import test_api as api

class Configuration(unittest.TestCase):
    setUpClass = classmethod(api.Integration.setUpClass.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    setUp = api.Integration.setUp

    def config(self):
        status, data, _ = self.admin.request('/api/admin')
        self.assertEqual(status, 200)
        return data

    def command(self, **fields):
        return dict(expectedRevision=self.config()['configRevision'], requestId=str(uuid.uuid4()), **fields)

    def test_validation_csrf_authorization(self):
        for path, fields in [('/api/admin/role', dict(identity='sam',role='Researcher')),('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a'))]:
            payload=self.command(**fields)
            self.assertEqual(self.alex.request(path,payload)[0],403)
            self.assertEqual(self.admin.request(path,payload,csrf=False)[0],400)
            self.assertEqual(self.admin.request(path,fields)[0],400)
            self.assertEqual(self.admin.request(path,dict(payload,requestId='bad'))[0],400)
            self.assertEqual(self.admin.request(path,dict(payload,expectedRevision=-1))[0],400)
            self.assertEqual(self.admin.request(path,dict(payload,expectedRevision=payload['expectedRevision']+1))[0],409)
        self.assertEqual(self.admin.request('/api/admin/role',self.command(identity='admin',role='Researcher'))[0],400)
        self.assertEqual(self.admin.request('/api/admin/mapping',self.command(studyId='atlas',groupId='unresolved'))[0],400)

    def test_concurrent_admin_writes_and_replay(self):
        before=self.config()
        first=self.command(identity='sam',role='Researcher')
        second=self.command(studyId='atlas',groupId='demo-group-a')
        other=api.Client().login('admin')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.admin.request,'/api/admin/role',first),pool.submit(other.request,'/api/admin/mapping',second)]
            results=[f.result() for f in futures]
        self.assertEqual(sorted(x[0] for x in results),[200,409])
        after=self.config()
        self.assertEqual(after['configRevision'],before['configRevision']+1)
        self.assertEqual(len(after['configurationHistory']),len(before['configurationHistory'])+1)
        change=after['configurationHistory'][-1]
        self.assertEqual(change['actor'],'admin')
        self.assertEqual(change['revision'],after['configRevision'])
        self.assertIn('before',change)
        self.assertIn('after',change)
        path,payload=('/api/admin/role',first) if results[0][0]==200 else ('/api/admin/mapping',second)
        self.assertEqual(self.admin.request(path,payload)[0],200)
        self.assertEqual(self.config()['configRevision'],after['configRevision'])
        altered=dict(payload,expectedRevision=after['configRevision'])
        self.assertEqual(self.admin.request(path,altered)[0],409)
        other_path,other_fields=('/api/admin/mapping',dict(studyId='atlas',groupId='demo-group-a')) if path.endswith('/role') else ('/api/admin/role',dict(identity='sam',role='Researcher'))
        cross=dict(other_fields,expectedRevision=after['configRevision'],requestId=payload['requestId'])
        self.assertEqual(self.admin.request(other_path,cross)[0],409)
        self.assertNotIn('configRequests',json.dumps(after))
        self.assertNotIn(payload['requestId'],json.dumps(after))

    def test_revocation_before_replay_and_restart(self):
        self.assertEqual(self.admin.request('/api/admin/role',self.command(identity='alex',role='Administrator'))[0],200)
        self.alex=api.Client().login('alex')
        performed=self.command(identity='sam',role='Researcher')
        self.assertEqual(self.alex.request('/api/admin/role',performed)[0],200)
        self.assertEqual(self.alex.request('/api/studies/beacon')[0],404)
        self.assertEqual(self.admin.request('/api/admin/role',self.command(identity='alex',role='Researcher'))[0],200)
        self.assertEqual(self.alex.request('/api/admin/role',performed)[0],403)
        mapping=self.command(studyId='atlas',groupId='demo-group-a')
        self.assertEqual(self.admin.request('/api/admin/mapping',mapping)[0],200)
        before=self.config()
        self.stop();self.start()
        self.admin=api.Client().login('admin')
        self.assertEqual(self.config(),before)
        self.assertEqual(self.admin.request('/api/admin/mapping',mapping)[0],200)
        self.assertEqual(self.config(),before)

if __name__=='__main__': unittest.main(verbosity=2)
