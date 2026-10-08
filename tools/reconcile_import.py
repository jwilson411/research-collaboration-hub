#!/usr/bin/env python3
"""Offline synthetic manifest rehearsal. This never writes to the application."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

KINDS = {'document', 'version', 'discussion', 'reply', 'attachment', 'decision'}
PARENTS = {'version': {'document'}, 'reply': {'discussion', 'reply'},
           'attachment': {'discussion', 'reply'}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def reconcile(manifest, previous=None):
    """Return deterministic state and a complete per-record accounting report."""
    if manifest.get('schema') != 1 or manifest.get('synthetic') is not True:
        raise ValueError('Only schema 1 explicitly synthetic manifests are supported')
    records = manifest.get('records')
    if not isinstance(records, list):
        raise ValueError('records must be a list')
    ids = [r.get('source_id') for r in records if isinstance(r, dict)]
    if len(ids) != len(records) or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError('Every record needs a nonempty source_id')
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source_id: a batch must contain one revision per source record')
    state = copy.deepcopy(previous or {'schema': 1, 'records': {}})
    if state.get('schema') != 1 or not isinstance(state.get('records'), dict):
        raise ValueError('Unsupported reconciliation state')
    studies = manifest.get('studies', {})
    groups = manifest.get('approved_group_ids', [])
    principals = manifest.get('principals', {})
    if not isinstance(studies, dict) or not isinstance(groups, list) or not isinstance(principals, dict):
        raise ValueError('Invalid mapping catalogs')
    results, proposed = {}, {}
    for record in sorted(records, key=lambda r: r['source_id']):
        rid = record['source_id']
        reasons = []
        revision = record.get('revision')
        old = state['records'].get(rid)
        study = record.get('study_id')
        mapped = studies.get(study)
        deleted = record.get('deleted', False)
        if type(revision) is not int or revision < 1:
            reasons.append('invalid_revision')
        if not isinstance(deleted, bool):
            reasons.append('invalid_deleted_flag')
        if record.get('kind') not in KINDS:
            reasons.append('unsupported_kind')
        if not mapped or mapped not in groups:
            reasons.append('unresolved_group_mapping')
        if record.get('acl') != {'groups': [mapped], 'principals': []}:
            reasons.append('unsupported_or_unresolved_acl')
        if record.get('author_id') not in principals:
            reasons.append('unresolved_historical_author')
        if not isinstance(record.get('original_timestamp'), str) or not record['original_timestamp']:
            reasons.append('missing_original_timestamp')
        refs = record.get('references', [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            reasons.append('invalid_references')
        if not deleted and record.get('kind') in PARENTS and not isinstance(record.get('parent_id'), str):
            reasons.append('missing_parent')
        if not deleted and record.get('kind') in {'version', 'attachment'}:
            try:
                content = base64.b64decode(record.get('content_base64', ''), validate=True)
                if hashlib.sha256(content).hexdigest() != record.get('sha256'):
                    reasons.append('checksum_mismatch')
            except (ValueError, TypeError):
                reasons.append('invalid_binary_encoding')
        if old and (old['record']['study_id'] != study or old['record']['kind'] != record.get('kind')):
            reasons.append('immutable_identity_changed')
        fingerprint = digest(record)
        status = 'deleted' if deleted else 'imported'
        if old and not reasons:
            if revision < old['record']['revision']:
                status = 'stale_ignored'
            elif revision == old['record']['revision']:
                if fingerprint == old['fingerprint']:
                    status = 'unchanged'
                else:
                    reasons.append('revision_conflict')
            elif old['record'].get('deleted') and not deleted:
                reasons.append('tombstone_blocks_resurrection')
        results[rid] = {'source_id': rid, 'study_id': study, 'status': 'quarantined' if reasons else status,
                        'reasons': sorted(reasons), 'fingerprint': fingerprint}
        if not reasons and status in {'imported', 'deleted'}:
            proposed[rid] = {'fingerprint': fingerprint, 'record': copy.deepcopy(record)}
    # Fixed-point dependency validation prevents publishing a child of any quarantined record.
    while True:
        rejected = {}
        combined = {**state['records'], **proposed}
        for rid, entry in proposed.items():
            record = entry['record']
            if record.get('deleted'):
                continue
            refs = list(record.get('references', []))
            if record.get('parent_id'):
                refs.append(record['parent_id'])
            reasons = []
            for ref in refs:
                target = combined.get(ref, {}).get('record')
                if ref == rid or not target or target.get('deleted') or results.get(ref, {}).get('status') == 'quarantined':
                    reasons.append('unavailable_relationship:' + ref)
                elif target['study_id'] != record['study_id']:
                    reasons.append('cross_study_relationship:' + ref)
                elif ref == record.get('parent_id') and target['kind'] not in PARENTS.get(record['kind'], KINDS):
                    reasons.append('invalid_parent_kind:' + ref)
            # Parent chains must terminate; cycles cannot preserve a threaded conversation.
            visited, cursor = {rid}, record.get('parent_id')
            while cursor and cursor in combined:
                if cursor in visited:
                    reasons.append('parent_cycle')
                    break
                visited.add(cursor)
                cursor = combined[cursor]['record'].get('parent_id')
            if reasons:
                rejected[rid] = sorted(set(reasons))
        if not rejected:
            break
        for rid, reasons in rejected.items():
            proposed.pop(rid)
            results[rid].update(status='quarantined', reasons=reasons)
    state['records'].update(proposed)
    outcomes = [results[rid] for rid in sorted(results)]
    counts = {name: sum(r['status'] == name for r in outcomes)
              for name in ['imported', 'deleted', 'unchanged', 'stale_ignored', 'quarantined']}
    # Existing references to deleted records remain historical, but never resolve to live content.
    dangling = []
    for rid, entry in sorted(state['records'].items()):
        r = entry['record']
        if r.get('deleted'):
            continue
        for ref in sorted(set(r.get('references', []) + ([r['parent_id']] if r.get('parent_id') else []))):
            target = state['records'].get(ref, {}).get('record')
            if not target or target.get('deleted'):
                dangling.append({'source_id': rid, 'unavailable_target': ref})
    report = {'schema': 1, 'synthetic': True, 'input_count': len(records), 'counts': counts,
              'outcomes': outcomes, 'historical_unavailable_relationships': dangling,
              'state_sha256': digest(state), 'live_application_ingestion': False}
    assert sum(counts.values()) == len(records)
    return state, report


def write_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, encoding='utf-8') as output:
        temporary = output.name
        json.dump(value, output, indent=2, sort_keys=True)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--state', type=Path, help='Prior rehearsal state; only written with --apply')
    parser.add_argument('--report', type=Path, help='Optional deterministic report output')
    parser.add_argument('--apply', action='store_true', help='Persist accepted records to rehearsal state only')
    args = parser.parse_args()
    try:
        if args.apply and not args.state:
            raise ValueError('--apply requires --state')
        manifest = json.loads(args.manifest.read_text())
        previous = json.loads(args.state.read_text()) if args.state and args.state.exists() else None
        state, report = reconcile(manifest, previous)
        if args.apply:
            write_atomic(args.state, state)
        if args.report:
            write_atomic(args.report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report['counts']['quarantined'] else 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f'Invalid rehearsal input: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
