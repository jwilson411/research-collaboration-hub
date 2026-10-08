"""Real stopped-demo recovery rehearsal; owns loopback port 5080 and disposable state."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
import test_api as api


class RecoveryRehearsal(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 5080)) == 0:
                raise RuntimeError('Stop preview; recovery rehearsal requires exclusive loopback port 5080')
        subprocess.run([api.DOTNET, 'build', '--no-incremental', '--nologo'], cwd=api.ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix='hub-recovery-')
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'source'; cls.source.mkdir()
        cls.data = cls.source / 'hub.json'
        cls.blobs = cls.source / 'files'
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT='Development', HUB_DEMO_ENABLED='true',
                       HUB_DATA=str(cls.data), HUB_FILES=str(cls.blobs), HUB_DEMO_FILE_RELEASE='true')
        cls.log = open(cls.root / 'server.log', 'w+')
        cls.start()

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(api.ROOT / 'tools/backup_demo.py'), *map(str, args)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_stopped_snapshot_restores_exact_evidence_and_access(self):
        alex = api.Client().login('alex')
        def study(): return alex.request('/api/studies/atlas')[1]
        def write(suffix, payload):
            body = dict(payload, expectedRevision=study()['revision'], requestId=str(uuid.uuid4()))
            status, value, _ = alex.request('/api/studies/atlas' + suffix, body)
            self.assertEqual(status, 200, value)
            return body, value
        content = b'Synthetic recovery evidence. No actual research data.\n'
        _, uploaded = write('/files', dict(name='recovery.txt', contentBase64=base64.b64encode(content).decode()))
        file = next(f for f in uploaded['files'] if f['name'] == 'recovery.txt')
        before_ids = {i['id'] for i in study()['items']}
        _, documented = write('/documents', dict(title='Synthetic recovery document', body='Exact first revision', fileIds=[file['id']]))
        document = next(i for i in documented['items'] if i['id'] not in before_ids)
        request, capture = write('/handoffs', dict(title='Synthetic recovery handoff', summary='Recovery rehearsal',
                                                  itemIds=[document['id']], fileIds=[file['id']]))
        handoff_path = '/api/studies/atlas/handoffs/' + capture['id']
        download_path = '/api/studies/atlas/files/' + file['id'] + '/download'
        self.assertEqual(alex.request(download_path)[:2], (200, content))
        original_study = study()
        original_snapshot = alex.request(handoff_path)[1]
        seed_snapshot = alex.request('/api/studies/atlas/handoffs/journey-handoff')
        self.assertEqual(seed_snapshot[0], 200)
        self.stop()
        source_before = {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in self.source.rglob('*') if p.is_file()}
        archive_parent = self.root / 'archives'; archive_parent.mkdir()
        restore_parent = self.root / 'restores'; restore_parent.mkdir()
        archive = archive_parent / 'synthetic.zip'
        backup = self.cli('create', '--state', self.data, '--blobs', self.blobs, '--output', archive, '--stopped')
        verified = self.cli('verify', '--archive', archive)
        restored = self.cli('restore', '--archive', archive, '--parent', restore_parent, '--name', 'demo-restore-rehearsal', '--stopped')
        self.assertEqual(verified['manifestSha256'], restored['manifestSha256'])
        self.env.update(HUB_DATA=restored['state'], HUB_FILES=restored['blobs'])
        self.start()
        alex = api.Client().login('alex')
        self.assertEqual(study(), original_study)
        self.assertEqual(alex.request(download_path)[:2], (200, content))
        self.assertEqual(alex.request(handoff_path)[:2], (200, original_snapshot))
        self.assertEqual(alex.request('/api/studies/atlas/handoffs/journey-handoff')[:2], seed_snapshot[:2])
        self.assertEqual(alex.request('/api/studies/atlas/handoffs', request)[:2], (200, capture))
        self.assertEqual(study()['revision'], original_study['revision'])
        for identity in ('sam', 'admin'):
            outsider = api.Client().login(identity)
            for path in ('/api/studies/atlas', download_path, handoff_path):
                self.assertEqual(outsider.request(path)[0], 404, (identity, path))
        write('/documents/' + document['id'] + '/versions', dict(title='Synthetic recovery document', body='Second revision in isolated restore', fileIds=[file['id']]))
        self.assertEqual(alex.request(handoff_path)[1], original_snapshot)
        self.stop()
        source_after = {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in self.source.rglob('*') if p.is_file()}
        self.assertEqual(source_before, source_after)
        self.assertNotEqual(Path(restored['state']).read_bytes(), self.data.read_bytes())
        print(json.dumps(dict(restoredBlobCount=backup['files'], verifiedMembers=verified['verifiedMembers'],
                              downloadedBytes=len(content), downloadedSha256=hashlib.sha256(content).hexdigest(),
                              manifestSha256=verified['manifestSha256'], handoffSha256=capture['sha256'],
                              seedHandoffSha256=seed_snapshot[1]['sha256'], originalFilesUnchanged=len(source_before),
                              sourceMetadataBytes=self.data.stat().st_size, negativeAccessChecks=6), sort_keys=True))


if __name__ == '__main__': unittest.main(verbosity=2)
