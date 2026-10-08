"""Startup/reload boundary checks; runtime test owns only loopback port 5080."""
import os
import json
import socket
import time
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_api as api


class StartupBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([api.DOTNET,'build','--no-incremental','--nologo'],cwd=api.ROOT,check=True,stdout=subprocess.DEVNULL)

    def test_custom_kestrel_endpoints_refused_before_listen(self):
        with tempfile.TemporaryDirectory(prefix='hub-startup-boundaries-') as temporary:
            for endpoint in ('http://127.0.0.1:5081','synthetic-invalid-endpoint'):
                with self.subTest(endpoint=endpoint):
                    state=Path(temporary)/'hub.json'
                    env=dict(os.environ,ASPNETCORE_ENVIRONMENT='Development',HUB_DEMO_ENABLED='true',HUB_DATA=str(state),
                             HUB_FILES=str(Path(temporary)/'files'),Kestrel__Endpoints__SyntheticCheck__Url=endpoint)
                    result=subprocess.run([api.DOTNET,str(api.ROOT/'bin/Debug/net10.0/ResearchHub.dll')],cwd=api.ROOT,
                                          env=env,capture_output=True,text=True,timeout=10)
                    self.assertNotEqual(result.returncode,0)
                    output=result.stdout+result.stderr
                    self.assertIn('Custom Kestrel endpoints are disabled for the local demo.',output)
                    self.assertNotIn('Now listening on:',output)
                    self.assertNotIn(endpoint,output)
                    self.assertFalse(state.exists())

    def test_dynamic_endpoints_do_not_reload_or_override_loopback(self):
        for port in (5080,5081):
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',port))==0:
                    raise RuntimeError('Startup reload test requires free loopback ports 5080 and 5081')
        cls=type(self)
        with tempfile.TemporaryDirectory(prefix='hub-startup-reload-') as temporary:
            root=Path(temporary)
            content=root/'content';content.mkdir()
            settings=content/'appsettings.json';settings.write_text('{}')
            cls.env=dict(os.environ,ASPNETCORE_ENVIRONMENT='Development',HUB_DEMO_ENABLED='true',
                         ASPNETCORE_CONTENTROOT=str(content),HUB_DATA=str(root/'hub.json'),HUB_FILES=str(root/'files'))
            cls.log=open(root/'server.log','w+')
            try:
                api.Integration.start.__func__(cls)
                settings.write_text(json.dumps({'Kestrel':{'Endpoints':{'SyntheticReload':{'Url':'http://127.0.0.1:5081'}}}}))
                # Default JSON reload debounce is shorter than this observation window.
                for _ in range(30):
                    time.sleep(.1)
                    with socket.socket() as probe:
                        self.assertNotEqual(probe.connect_ex(('127.0.0.1',5081)),0,'Configuration must never open an additional listener')
                    self.assertEqual(api.Client().request('/api/session')[0],200)
                cls.log.seek(0)
                self.assertNotIn('Now listening on: http://127.0.0.1:5081',cls.log.read())
            finally:
                if getattr(cls,'server',None) is not None:api.Integration.stop.__func__(cls)
                cls.log.close()


if __name__=='__main__':unittest.main(verbosity=2)
