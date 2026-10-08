"""Launcher contract checks using a fake SDK; no listener or environment changes."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def run_launcher(self, *args, sdk='10.0.401', restore='0', selected='10.0.401'):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'dotnet'
            output = Path(directory) / 'calls.jsonl'
            fake.write_text('''#!/usr/bin/env python3
import json,os,sys
if sys.argv[1]=='--list-sdks':
 print(os.environ['FAKE_SDK']+' [/fake]');sys.exit(0)
if sys.argv[1]=='--version':
 print(os.environ['SELECTED_SDK']);sys.exit(0)
with open(os.environ['CALLS'],'a') as stream:
 stream.write(json.dumps({'args':sys.argv[1:],'cwd':os.getcwd(),'provider':os.environ['HUB_STORAGE_PROVIDER'],'release':os.environ['HUB_DEMO_FILE_RELEASE'],'aspnet':os.environ['ASPNETCORE_ENVIRONMENT'],'dotnet':os.environ['DOTNET_ENVIRONMENT']})+'\\n')
if sys.argv[1]=='restore':sys.exit(int(os.environ['RESTORE_EXIT']))
''')
            fake.chmod(0o755)
            env = dict(os.environ, DOTNET=str(fake), CALLS=str(output), FAKE_SDK=sdk,
                       RESTORE_EXIT=restore, SELECTED_SDK=selected, HUB_STORAGE_PROVIDER='SqlServer',
                       HUB_DEMO_FILE_RELEASE='true', DOTNET_ENVIRONMENT='Production')
            result = subprocess.run(['bash', str(ROOT/'scripts/start-demo.sh'), *args],
                                    cwd=directory, env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []
            return result, calls

    def test_safe_defaults_from_other_directory(self):
        result, calls = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['args'], ['restore', '--locked-mode'])
        for call in calls:
            self.assertEqual(call['cwd'], str(ROOT))
            self.assertEqual(call['provider'], 'Json')
            self.assertEqual(call['release'], 'false')
            self.assertEqual(call['aspnet'], 'Development')
            self.assertEqual(call['dotnet'], 'Development')
        self.assertIn('--no-launch-profile', calls[1]['args'])
        self.assertIn('--no-restore', calls[1]['args'])

    def test_explicit_release(self):
        result, calls = self.run_launcher('--release-synthetic-files')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls[-1]['release'], 'true')

    def test_reject_missing_sdk_and_unknown_arguments(self):
        for args, sdk in [((), '9.0.1'), (('--urls', 'http://0.0.0.0:5080'), '10.0.401')]:
            result, calls = self.run_launcher(*args, sdk=sdk)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_reject_incorrect_selected_sdk(self):
        result, calls = self.run_launcher(selected='11.0.100')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_restore_failure_never_starts(self):
        result, calls = self.run_launcher(restore='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
