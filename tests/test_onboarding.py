"""Personal, context-bound orientation using synthetic loopback HTTP."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import uuid
import test_api as api

class Onboarding(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 5080)) == 0:
                raise RuntimeError('Stop preview: onboarding tests own loopback port 5080')
        subprocess.run([api.DOTNET, 'build', '--no-incremental', '--nologo'], cwd=api.ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix='hub-orientation-')
        cls.data = Path(cls.temp.name) / 'hub.json'
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT='Development', HUB_DEMO_ENABLED='true', HUB_DATA=str(cls.data))
        cls.log = open(Path(cls.temp.name) / 'server.log', 'w+')
        cls.start()

    def setUp(self):
        self.alex = api.Client().login('alex')
        self.reviewer = api.Client().login('reviewer')
        self.sam = api.Client().login('sam')

    def get(self, client=None):
        status, data, _ = (client or self.alex).request('/api/studies/atlas/onboarding')
        self.assertEqual(status, 200, data)
        return data

    def study(self): return self.alex.request('/api/studies/atlas')[1]
    def step(self, data, step): return next(s for s in data['steps'] if s['id'] == step)
    def payload(self, step, completed=True, client=None):
        data = self.get(client)
        return dict(stepId=step, completed=completed, contextKey=self.step(data,step)['contextKey'], expectedRevision=data['revision'], requestId=str(uuid.uuid4()))
    def mark(self, payload, client=None): return (client or self.alex).request('/api/studies/atlas/onboarding',payload)
    def change(self, path, value):
        return self.alex.request('/api/studies/atlas'+path,dict(value,expectedRevision=self.study()['revision'],requestId=str(uuid.uuid4())))
    def discussion(self):
        status, study, _ = self.change('/items',dict(kind='discussion',title='Synthetic orientation question '+uuid.uuid4().hex,body='Which next step needs clarification?'))
        self.assertEqual(status,200)
        return study['items'][-1]['id']

    def test_a_private_revision_idempotency_restart(self):
        before=self.study(); other=self.get(self.reviewer); payload=self.payload('guidance')
        status, saved, _=self.mark(payload)
        self.assertEqual(status,200); self.assertTrue(self.step(saved,'guidance')['completed'])
        self.assertEqual(self.mark(payload)[1],saved)
        self.assertEqual(self.get(self.reviewer),other)
        self.assertEqual(self.study()['revision'],before['revision'])
        self.assertNotIn('personalOnboarding',self.study())
        self.assertNotIn('personalOnboarding',json.dumps(self.alex.request('/api/studies')[1]))
        self.assertEqual(self.mark(dict(payload,completed=False))[0],409)
        stale=self.payload('actions'); stale['expectedRevision']=payload['expectedRevision']
        self.assertEqual(self.mark(stale)[0],409)
        other_payload=self.payload('questions',client=self.reviewer)
        self.assertEqual(self.mark(other_payload,self.reviewer)[0],200)
        self.assertEqual(self.get(),saved)
        self.stop(); self.start(); self.alex=api.Client().login('alex')
        self.assertEqual(self.get(),saved); self.assertEqual(self.mark(payload)[1],saved)

    def test_b_new_question_and_reply_invalidate_context(self):
        payload=self.payload('questions'); self.assertEqual(self.mark(payload)[0],200)
        discussion=self.discussion()
        self.assertFalse(self.step(self.get(),'questions')['completed'])
        self.assertEqual(self.mark(payload)[0],409)
        updated=self.payload('questions'); self.assertEqual(self.mark(updated)[0],200)
        status,_,_=self.change('/items',dict(kind='reply',title='Synthetic reply',body='Add an explicit next action.',parentId=discussion))
        self.assertEqual(status,200); self.assertFalse(self.step(self.get(),'questions')['completed'])
        self.assertEqual(self.mark(updated)[0],409)

    def test_c_new_designation_requires_new_acknowledgement(self):
        payload=self.payload('guidance'); self.assertEqual(self.mark(payload)[0],200)
        status, study,_=self.change('/documents',dict(title='Synthetic new working guidance',body='A new immutable working reference.'))
        self.assertEqual(status,200); document=study['items'][-1]
        # A new draft alone does not displace accepted working guidance.
        self.assertTrue(self.step(self.get(),'guidance')['completed'])
        self.assertEqual(self.change('/protocol',dict(kind='item',id=document['id'],reason='Use this draft for the synthetic working exercise.'))[0],200)
        self.assertFalse(self.step(self.get(),'guidance')['completed'])
        self.assertEqual(self.mark(payload)[0],409)

    def test_d_handoff_removal_changes_acknowledgement_context(self):
        discussion=self.discussion()
        status, snapshot,_=self.change('/handoffs',dict(title='Synthetic orientation capture',summary='Current context.',itemIds=[discussion],fileIds=[]))
        self.assertEqual(status,200,snapshot)
        payload=self.payload('handoff'); self.assertEqual(self.mark(payload)[0],200)
        self.assertEqual(self.change('/items/'+discussion+'/delete',{})[0],200)
        self.assertFalse(self.step(self.get(),'handoff')['completed'])
        self.assertEqual(self.mark(payload)[0],409)

    def test_e_read_acknowledgements_allowed_when_closed(self):
        try:
            for stage in ('Paused','Closed'):
                self.assertEqual(self.change('/stage',dict(stage=stage))[0],200)
                revision=self.study()['revision']
                payload=self.payload('actions'); status,data,_=self.mark(payload)
                self.assertEqual(status,200); self.assertEqual(data['studyStage'],stage)
                self.assertEqual(self.study()['revision'],revision)
        finally:
            self.assertEqual(self.change('/stage',dict(stage='Active'))[0],200)
        payload=self.payload('actions')
        self.assertEqual(self.alex.request('/api/studies/atlas/onboarding',payload,csrf=False)[0],400)
        self.assertEqual(self.sam.request('/api/studies/atlas/onboarding',payload)[0],404)
        self.assertEqual(self.mark(dict(payload,contextKey='bad'))[0],400)
        status,beacon,_=self.sam.request('/api/studies/beacon/onboarding')
        self.assertEqual(status,200)
        unavailable=self.step(beacon,'handoff')
        self.assertFalse(unavailable['available'])
        self.assertEqual(self.sam.request('/api/studies/beacon/onboarding',dict(stepId='handoff',completed=True,contextKey=unavailable['contextKey'],expectedRevision=beacon['revision'],requestId=str(uuid.uuid4())))[0],409)

if __name__ == '__main__': unittest.main()
