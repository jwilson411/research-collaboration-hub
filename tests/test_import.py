import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reconcile_import', ROOT / 'tools/reconcile_import.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    return json.loads((ROOT / 'fixtures/synthetic-import.json').read_text())


class ReconciliationTests(unittest.TestCase):
    def test_complete_fidelity_and_restart_retry(self):
        batch = fixture()
        state, report = module.reconcile(batch)
        self.assertEqual(report['counts']['imported'], 7)
        self.assertEqual(sum(report['counts'].values()), 7)
        restored = json.loads(json.dumps(state))
        retried, retry_report = module.reconcile(batch, restored)
        self.assertEqual(retried, state)
        self.assertEqual(retry_report['counts']['unchanged'], 7)
        self.assertEqual(state['records']['version-1']['record'], batch['records'][1])
        self.assertEqual(state['records']['reply-1']['record']['parent_id'], 'thread-1')
        self.assertEqual(state['records']['attachment-1']['record']['parent_id'], 'reply-1')
        self.assertEqual(state['records']['reply-1']['record']['author_id'], 'former-member')
        self.assertNotIn('principals', state)  # Attribution cannot become a login roster.

    def test_deterministic_order(self):
        batch = fixture()
        state, report = module.reconcile(batch)
        batch['records'].reverse()
        other, other_report = module.reconcile(batch)
        self.assertEqual(state, other)
        self.assertEqual(report, other_report)

    def test_group_acl_and_author_quarantine(self):
        for mutate in [lambda b: b.update(approved_group_ids=[]),
                       lambda b: b['records'][0]['acl'].update(principals=['synthetic-reader']),
                       lambda b: b['records'][0].update(author_id='unknown')]:
            batch = fixture()
            mutate(batch)
            state, report = module.reconcile(batch)
            self.assertGreater(report['counts']['quarantined'], 0)
            self.assertNotIn('document-1', state['records'])
            self.assertNotIn('version-1', state['records'])

    def test_checksum_and_dependent_quarantine(self):
        batch = fixture()
        batch['records'][1]['sha256'] = '0' * 64
        state, report = module.reconcile(batch)
        self.assertNotIn('version-1', state['records'])
        self.assertNotIn('thread-1', state['records'])
        self.assertNotIn('reply-1', state['records'])
        self.assertNotIn('attachment-1', state['records'])
        self.assertEqual(report['input_count'], sum(report['counts'].values()))

    def test_cross_study_and_cycle(self):
        batch = fixture()
        batch['studies']['other-study'] = 'synthetic-group-other'
        batch['approved_group_ids'].append('synthetic-group-other')
        batch['records'][4].update(study_id='other-study', acl={'groups': ['synthetic-group-other'], 'principals': []})
        state, report = module.reconcile(batch)
        self.assertNotIn('reply-1', state['records'])
        batch = fixture()
        batch['records'][4]['parent_id'] = 'reply-1'
        self.assertNotIn('reply-1', module.reconcile(batch)[0]['records'])

    def test_deletion_delta_never_resurrects(self):
        batch = fixture()
        state, _ = module.reconcile(batch)
        delta = copy.deepcopy(batch)
        delta['records'] = [dict(batch['records'][1], revision=2, deleted=True)]
        deleted, report = module.reconcile(delta, state)
        self.assertEqual(report['counts']['deleted'], 1)
        self.assertTrue(report['historical_unavailable_relationships'])
        retried, _ = module.reconcile(batch, deleted)
        self.assertEqual(retried, deleted)
        delta['records'][0].update(revision=3, deleted=False)
        blocked, report = module.reconcile(delta, deleted)
        self.assertEqual(blocked, deleted)
        self.assertIn('tombstone_blocks_resurrection', report['outcomes'][0]['reasons'])

    def test_conflict_and_duplicate(self):
        batch = fixture()
        state, _ = module.reconcile(batch)
        batch['records'][0]['title'] = 'Changed without a source revision'
        new, report = module.reconcile(batch, state)
        self.assertEqual(state, new)
        self.assertEqual(report['counts']['quarantined'], 1)
        batch['records'].append(copy.deepcopy(batch['records'][0]))
        with self.assertRaises(ValueError):
            module.reconcile(batch)

    def test_invalid_input(self):
        for change in [lambda b: b.update(synthetic=False), lambda b: b.update(schema=2),
                       lambda b: b.update(records={})]:
            batch = fixture()
            change(batch)
            with self.assertRaises(ValueError):
                module.reconcile(batch)
        batch = fixture()
        batch['records'][1].update(content_base64='../not base64', revision=True)
        report = module.reconcile(batch)[1]
        result = next(r for r in report['outcomes'] if r['source_id'] == 'version-1')
        self.assertIn('invalid_revision', result['reasons'])
        self.assertIn('invalid_binary_encoding', result['reasons'])

    def test_cli_dry_run_apply_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            args = [sys.executable, str(ROOT / 'tools/reconcile_import.py'),
                    str(ROOT / 'fixtures/synthetic-import.json'), '--state', str(state)]
            dry = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertFalse(state.exists())
            applied = subprocess.run(args + ['--apply'], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            first = state.read_bytes()
            retried = subprocess.run(args + ['--apply'], capture_output=True, text=True)
            self.assertEqual(retried.returncode, 0, retried.stderr)
            self.assertEqual(state.read_bytes(), first)
            self.assertEqual(json.loads(retried.stdout)['counts']['unchanged'], 7)


if __name__ == '__main__':
    unittest.main()
