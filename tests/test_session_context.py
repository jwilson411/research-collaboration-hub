"""Independent HTTP checks for cross-tab actor binding and session generations."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import socket
import time
import unittest
import urllib.request
import uuid
import test_api as api
import test_attachments as attachments

class SessionContext(unittest.TestCase):
    start=classmethod(api.Integration.start.__func__)
    stop=classmethod(api.Integration.stop.__func__)
    setUpClass=classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass=classmethod(api.Integration.tearDownClass.__func__)
    setUp=api.Integration.setUp
    study=api.Integration.study
    item=api.Integration.item
    def tab(self,client):
        other=api.Client();other.cookies=client.cookies;other.opener=client.opener
        other.csrf=client.csrf;other.session_context=client.session_context
        return other
    def changed(self,result):
        self.assertEqual(result[0],409,result[1]);self.assertEqual(result[1]['code'],'session_changed')
    def cookie_header(self,client):
        request=urllib.request.Request(api.BASE+'/api/session');client.cookies.add_cookie_header(request)
        return request.get_header('Cookie')

    def test_cross_tab_generation_never_revives_on_return_to_same_actor(self):
        first=self.alex.session_context;other=self.tab(self.alex)
        payload=self.item(title='Stale Alex draft')
        before=self.study()['revision']
        other.login('reviewer');second=other.session_context
        self.assertNotEqual(first,second)
        self.changed(self.alex.request('/api/studies/atlas/items',payload))
        self.changed(self.alex.request('/api/studies/atlas'))
        self.assertEqual(other.request('/api/studies/atlas')[1]['revision'],before)
        other.login('alex');third=other.session_context
        self.assertNotIn(third,(first,second))
        self.changed(self.alex.request('/api/studies/atlas/items',payload))
        # Explicitly refresh actor context before intentionally submitting; never auto-retry.
        self.alex.request('/api/session')
        status,study,_=self.alex.request('/api/studies/atlas/items',payload)
        self.assertEqual(status,200);self.assertEqual(study['items'][-1]['author'],'alex')
        other.request('/api/session');other.login('reviewer')
        self.changed(self.alex.request('/api/studies/atlas/items',payload))  # Even idempotent replay is gated.

    def test_all_mutation_families_require_context_separately_from_csrf(self):
        paths=['/api/session','/api/studies/atlas/items','/api/studies/atlas/stage','/api/studies/atlas/items/missing/delete',
               '/api/studies/atlas/documents','/api/studies/atlas/documents/missing/state','/api/studies/atlas/files',
               '/api/studies/atlas/files/missing/delete','/api/studies/atlas/tasks','/api/studies/atlas/protocol',
               '/api/studies/atlas/handoffs','/api/studies/atlas/boards','/api/studies/atlas/onboarding',
               '/api/studies/atlas/templates','/api/studies/atlas/resources','/api/studies/atlas/decisions',
               '/api/studies/atlas/imports/preview','/api/studies/atlas/imports/apply','/api/studies/atlas/imports/rehearsals',
               '/api/studies/atlas/imports/rehearsals/missing/actions',
               '/api/studies/atlas/imports/missing/review','/api/studies/atlas/imports/missing/receipts',
               '/api/admin/studies','/api/admin/mapping','/api/admin/role','/api/nonexistent']
        for path in paths:
            self.changed(self.alex.request(path,{},headers={'X-HUB-SESSION':''}))
        token=self.alex.session_context;self.alex.session_context=None
        try:self.changed(self.alex.request('/api/session',{'identity':'reviewer'}))
        finally:self.alex.session_context=token
        for invalid in ('bad','A'*63,'A'*65,'0'*64,self.alex.session_context+','+self.alex.session_context):
            self.changed(self.alex.request('/api/session',{'identity':'reviewer'},headers={'X-HUB-SESSION':invalid}))
        self.assertEqual(self.alex.request('/api/session',{'identity':'reviewer'},csrf=False,headers={'X-HUB-SESSION':''})[0],400)
        self.assertEqual(self.alex.request('/api/session')[1]['user']['id'],'alex')

    def test_parallel_switches_same_generation_allow_only_one(self):
        other=self.tab(self.alex);original=self.alex.session_context
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(client.request,'/api/session',{'identity':identity})
                     for client,identity in ((self.alex,'reviewer'),(other,'sam'))]
            results=[future.result() for future in futures]
        self.assertEqual(sorted(result[0] for result in results),[200,409])
        winner='reviewer' if results[0][0]==200 else 'sam'
        session=self.alex.request('/api/session')[1]
        self.assertEqual(session['user']['id'],winner);self.assertNotEqual(session['sessionContext'],original)
        self.changed(other.request('/api/session',{'identity':'alex'}))

    def test_inflight_body_finishes_as_original_actor_before_switch(self):
        payload=self.item(title='Slow synthetic write remains Alex')
        body=json.dumps(payload).encode();other=self.tab(self.alex)
        headers=('POST /api/studies/atlas/items HTTP/1.1\r\nHost: 127.0.0.1:5080\r\nContent-Type: application/json\r\n'
                 f'Content-Length: {len(body)}\r\nCookie: {self.cookie_header(self.alex)}\r\n'
                 f'X-CSRF-TOKEN: {self.alex.csrf}\r\nX-HUB-SESSION: {self.alex.session_context}\r\nConnection: close\r\n\r\n').encode()
        connection=socket.create_connection(('127.0.0.1',5080),timeout=5)
        try:
            connection.sendall(headers+body[:1]);time.sleep(.15)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(other.request,'/api/session',{'identity':'reviewer'})
                try:
                    with self.assertRaises(TimeoutError):future.result(timeout=.2)
                finally:connection.sendall(body[1:])
                response=b''
                while True:
                    part=connection.recv(65536)
                    if not part:break
                    response+=part
                self.assertIn(b'HTTP/1.1 200',response.split(b'\r\n',1)[0])
                self.assertEqual(future.result(timeout=5)[0],200)
            other.request('/api/session')
            record=next(item for item in other.request('/api/studies/atlas')[1]['items'] if item['title']==payload['title'])
            self.assertEqual(record['author'],'alex')
            self.changed(self.alex.request('/api/studies/atlas/items',payload))
        finally:connection.close()

    def test_cancelled_body_releases_session_gate(self):
        other=self.tab(self.alex)
        headers=('POST /api/studies/atlas/items HTTP/1.1\r\nHost: 127.0.0.1:5080\r\nContent-Type: application/json\r\nContent-Length: 10000\r\n'
                 f'Cookie: {self.cookie_header(self.alex)}\r\nX-CSRF-TOKEN: {self.alex.csrf}\r\nX-HUB-SESSION: {self.alex.session_context}\r\n\r\n').encode()
        connection=socket.create_connection(('127.0.0.1',5080),timeout=5)
        connection.sendall(headers+b'{');time.sleep(.1);connection.close()
        self.assertEqual(other.request('/api/session',{'identity':'reviewer'})[0],200)
        self.changed(self.alex.request('/api/studies/atlas/items',{}))

    def test_restart_old_session_cannot_write_and_cookie_spoof_is_ignored(self):
        payload=self.item(title='Restart invalidates intended actor')
        old=self.alex.session_context
        self.stop();self.start()
        self.changed(self.alex.request('/api/studies/atlas/items',payload))
        fresh=self.alex.request('/api/session')[1]
        self.assertNotEqual(fresh['sessionContext'],old);self.assertEqual(fresh['user']['id'],'alex')
        cookie=self.cookie_header(self.alex)+'; hub.identity=admin'
        self.assertEqual(self.alex.request('/api/session',headers={'Cookie':cookie})[1]['user']['id'],'alex')
        self.assertEqual(self.alex.request('/api/admin',headers={'Cookie':cookie})[0],403)
        replaced='; '.join(part for part in cookie.split('; ') if not part.startswith('hub.session='))+'; hub.session='+'A'*64
        self.changed(self.alex.request('/api/studies/atlas/items',payload,headers={'Cookie':replaced}))
        self.assertEqual(self.alex.request('/api/studies/atlas/items',payload)[0],200)

    def test_response_context_authorization_context_and_cookie_isolation(self):
        status,session,headers=self.alex.request('/api/session')
        self.assertEqual(headers['X-HUB-SESSION'],session['sessionContext'])
        cookie=next(cookie for cookie in self.alex.cookies if cookie.name=='hub.session')
        attributes={key.lower():str(value).lower() for key,value in cookie._rest.items()}
        self.assertIn('httponly',attributes);self.assertEqual(attributes.get('samesite'),'strict')
        before=session['authorizationContext'];generation=session['sessionContext']
        self.assertEqual(self.admin.config('/api/admin/role',dict(identity='alex',role='Administrator'))[0],200)
        try:
            after=self.alex.request('/api/session')[1]
            self.assertNotEqual(before,after['authorizationContext']);self.assertEqual(generation,after['sessionContext'])
        finally:self.assertEqual(self.admin.config('/api/admin/role',dict(identity='alex',role='Researcher'))[0],200)
        independent=api.Client().login('sam')
        self.assertNotEqual(independent.session_context,generation)
        self.assertEqual(self.alex.request('/api/session')[1]['user']['id'],'alex')
        self.assertEqual(independent.request('/api/studies/atlas')[0],404)

    def test_z_session_capacity_bounded_existing_session_preserved(self):
        rejected=False
        try:
            for _ in range(1030):
                result=api.Client().request('/api/session')
                if result[0]==503:rejected=True;break
                self.assertEqual(result[0],200)
            self.assertTrue(rejected)
            self.assertEqual(self.alex.request('/api/session')[1]['user']['id'],'alex')
        finally:self.stop();self.start()

if __name__=='__main__':unittest.main(verbosity=2)
