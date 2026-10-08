#!/usr/bin/env python3
"""Offline synthetic-demo backup/restore. No production data, credentials, or in-place restore.

A SyntheticDemo marker is an eligibility assertion, not a content sanitizer. Stop the
app first. Archive checksums detect corruption, not malicious replacement or approval.
Application-level handoff digests must also pass the restored-app rehearsal.
"""
from __future__ import annotations
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import sys
import tempfile
import uuid
import zipfile

FORMAT = "research-hub-synthetic-demo-backup"
MAX_STATE = 16 * 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_BLOB = 512 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_FILES = 10000
STATE_KEYS = {"datasetKind", "configRevision", "configRequests", "configurationHistory", "studies", "roles", "audit"}
CREDENTIAL_KEYS = {"password", "secret", "privatekey", "apikey", "accesstoken", "refreshtoken", "credentials", "connectionstring", "sqlconnection", "csrf"}
UNSAFE_COMPONENTS = {".git", "wwwroot", ".ssh", ".aws", ".codex", "node_modules"}
SYSTEM_ROOTS = {"/etc", "/bin", "/sbin", "/usr", "/var", "/opt", "/proc", "/sys", "/dev", "/boot", "/root", "/run", "/lib", "/lib64"}


class BackupError(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def parse_json(data: bytes):
    def pairs(values):
        obj = {}
        for key, value in values:
            if key in obj:
                raise BackupError("Duplicate JSON properties are unsupported")
            obj[key] = value
        return obj
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(BackupError("Non-finite JSON number")))
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise BackupError("Invalid or excessively nested JSON") from error


def checked_path(value, *, directory=False, exists=True) -> Path:
    raw = Path(value).expanduser()
    if ".." in raw.parts:
        raise BackupError("Traversal components are forbidden")
    path = Path(os.path.abspath(raw))
    for component in [path, *path.parents]:
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise BackupError("Symlinks, junctions, reparse points, and linked ancestors are forbidden")
    if exists:
        if directory and not path.is_dir():
            raise BackupError("Expected an existing directory")
        if not directory and (not path.is_file() or not stat.S_ISREG(path.stat().st_mode)):
            raise BackupError("Expected a regular file")
    return path


def safe_parent(value) -> Path:
    parent = checked_path(value, directory=True)
    if parent == Path(parent.anchor) or str(parent) in {"/tmp", "/home", "/Users"}:
        raise BackupError("Choose a dedicated demo recovery directory, not a filesystem root")
    folded = {part.casefold() for part in parent.parts}
    if folded & UNSAFE_COMPONENTS:
        raise BackupError("Repository, webroot, or credential directories are forbidden destinations")
    if os.name != "nt" and any(parent == Path(root) or Path(root) in parent.parents for root in SYSTEM_ROOTS):
        raise BackupError("System directories are forbidden destinations")
    if os.name == "nt" and folded & {"windows", "program files", "program files (x86)", "programdata"}:
        raise BackupError("System directories are forbidden destinations")
    if any((ancestor / ".git").is_file() or (ancestor / ".git" / "HEAD").exists()
           for ancestor in [parent, *parent.parents]):
        raise BackupError("Backups and restores must remain outside Git repositories")
    return parent


def path_hash(path: Path) -> str:
    return sha(os.path.normcase(str(path)).encode("utf-8"))


def boundaries(roots: list[Path]) -> dict:
    return {"roots": sorted({path_hash(p) for p in roots}),
            "ancestors": sorted({path_hash(a) for p in roots for a in [p, *p.parents]})}


def reject_source_overlap(destination: Path, protected: dict):
    if set(protected["roots"]) & {path_hash(p) for p in [destination, *destination.parents]} or path_hash(destination) in protected["ancestors"]:
        raise BackupError("Destination overlaps the original source directories")


def require_offline():
    try:
        with socket.create_connection(("127.0.0.1", 5080), timeout=1):
            raise BackupError("Stop the loopback demo server on port 5080 before backup or restore")
    except ConnectionRefusedError:
        return
    except BackupError:
        raise
    except OSError as error:
        raise BackupError("Could not verify that the loopback demo is stopped") from error


def read_bounded(path: Path, limit: int) -> bytes:
    checked_path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BackupError("Only regular files are supported")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise BackupError("Payload exceeds the demo backup size limit")
    return data


def inspect_state(data: bytes) -> tuple[dict, dict[str, tuple[int, str]]]:
    state = parse_json(data)
    if not isinstance(state, dict) or state.get("datasetKind") != "SyntheticDemo" or set(state) - STATE_KEYS:
        raise BackupError("Only explicitly marked SyntheticDemo state with a recognized schema is eligible")
    studies = state.get("studies")
    roles = state.get("roles")
    if not isinstance(studies, list) or not isinstance(roles, dict) or set(roles) - {"alex", "sam", "admin", "reviewer", "lead"}:
        raise BackupError("Unrecognized synthetic study or principal configuration")
    def reject_credentials(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if re.sub(r"[^a-z]", "", key.casefold()) in CREDENTIAL_KEYS:
                    raise BackupError("Credential configuration must never enter a demo backup")
                reject_credentials(child)
        elif isinstance(value, list):
            for child in value:
                reject_credentials(child)
    try:
        reject_credentials(state)
    except RecursionError as error:
        raise BackupError("Excessively nested state") from error
    referenced = {}
    for study in studies:
        if not isinstance(study, dict) or study.get("groupId") not in {"demo-group-a", "demo-group-b"}:
            raise BackupError("Only known synthetic directory groups are eligible")
        file_sets = [study.get("files", [])]
        snapshots = study.get("handoffs", [])
        if not isinstance(snapshots, list):
            raise BackupError("Malformed handoff collection")
        for snapshot in snapshots:
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), dict):
                raise BackupError("Malformed handoff snapshot")
            file_sets.append(snapshot["content"].get("files", []))
        for files in file_sets:
            if not isinstance(files, list):
                raise BackupError("Malformed file collection")
            for file in files:
                if not isinstance(file, dict):
                    raise BackupError("Malformed file record")
                identity, size, digest = file.get("id"), file.get("size"), file.get("sha256")
                if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity) or type(size) is not int or not 0 < size <= MAX_BLOB or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                    raise BackupError("Malformed immutable file identity, size, or checksum")
                record = (size, digest.lower())
                if identity in referenced and referenced[identity] != record:
                    raise BackupError("Conflicting checksums for one immutable file identity")
                referenced[identity] = record
    if len(referenced) > MAX_FILES or len(data) + sum(size for size, _ in referenced.values()) > MAX_TOTAL:
        raise BackupError("Backup exceeds bounded demo limits")
    return state, referenced


def archive_member(name: str) -> bool:
    return name == "state.json" or re.fullmatch(r"blobs/[0-9a-f]{32}\.blob", name) is not None


def create_backup(state_path, blobs_path, output_path, *, stopped=False) -> dict:
    if not stopped:
        raise BackupError("Explicit --stopped acknowledgement is required")
    require_offline()
    state_path = checked_path(state_path)
    blobs = checked_path(blobs_path, directory=True)
    output = checked_path(output_path, exists=False)
    parent = safe_parent(output.parent)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,90}\.zip", output.name) or output.exists():
        raise BackupError("Choose a new simple .zip filename; existing outputs are never overwritten")
    protected = boundaries([state_path.parent, blobs])
    reject_source_overlap(output, protected)
    original = read_bounded(state_path, MAX_STATE)
    _, refs = inspect_state(original)
    entries = {"state.json": {"size": len(original), "sha256": sha(original)}}
    pending = parent / (".backup-pending-" + uuid.uuid4().hex)
    try:
        with zipfile.ZipFile(pending, "x", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("state.json", original)
            for identity, (size, digest) in sorted(refs.items()):
                payload = read_bounded(blobs / (identity + ".blob"), MAX_BLOB)
                if len(payload) != size or sha(payload) != digest:
                    raise BackupError("Referenced file size/checksum mismatch; source backup refused")
                member = "blobs/" + identity + ".blob"
                archive.writestr(member, payload)
                entries[member] = {"size": size, "sha256": digest}
            manifest = {"format": FORMAT, "version": 1, "datasetKind": "SyntheticDemo", "members": entries,
                        "sourceBoundaries": protected, "handoffValidation": "Required in restored application; archive verification is not domain validation"}
            manifest["manifestSha256"] = sha(canonical(manifest))
            archive.writestr("manifest.json", canonical(manifest))
        if read_bounded(state_path, MAX_STATE) != original:
            raise BackupError("Source metadata changed during backup; stop the app and retry")
        with pending.open("rb") as stream:
            os.fsync(stream.fileno())
        # Hard-link publication is exclusive and cannot overwrite an existing destination.
        os.link(pending, output)
        return {"archive": str(output), "files": len(refs), "manifestSha256": manifest["manifestSha256"]}
    finally:
        if pending.exists():
            pending.unlink()


def verified_archive(path) -> tuple[dict, dict[str, bytes]]:
    path = checked_path(path)
    if path.stat().st_size > MAX_TOTAL + MAX_MANIFEST + 4 * 1024 * 1024:
        raise BackupError("Archive exceeds bounded demo limits")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 2:
                raise BackupError("Too many archive members")
            names = [info.filename for info in infos]
            if len({name.casefold() for name in names}) != len(names) or "manifest.json" not in names:
                raise BackupError("Duplicate members or missing manifest")
            for info in infos:
                mode = info.external_attr >> 16
                if info.filename != "manifest.json" and not archive_member(info.filename):
                    raise BackupError("Unexpected or unsafe archive member")
                if info.orig_filename != info.filename or info.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise BackupError("Links, directories, encryption, or unsupported compression are forbidden")
                limit = MAX_MANIFEST if info.filename == "manifest.json" else MAX_STATE if info.filename == "state.json" else MAX_BLOB
                if info.file_size < 0 or info.file_size > limit:
                    raise BackupError("Archive member exceeds its size limit")
            if sum(info.file_size for info in infos) > MAX_TOTAL + MAX_MANIFEST:
                raise BackupError("Archive expands beyond its size limit")
            manifest = parse_json(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != 1 or manifest.get("datasetKind") != "SyntheticDemo":
                raise BackupError("Unsupported archive format")
            claimed = manifest.get("manifestSha256")
            unsigned = {k: v for k, v in manifest.items() if k != "manifestSha256"}
            if claimed != sha(canonical(unsigned)):
                raise BackupError("Canonical manifest checksum mismatch")
            entries = manifest.get("members")
            bounds = manifest.get("sourceBoundaries")
            if not isinstance(entries, dict) or set(entries) != set(names) - {"manifest.json"} or "state.json" not in entries:
                raise BackupError("Manifest member accounting mismatch")
            if not isinstance(bounds, dict) or set(bounds) != {"roots", "ancestors"} or any(not isinstance(bounds[k], list) or not bounds[k] or len(bounds[k]) > 100 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in bounds[k]) for k in bounds):
                raise BackupError("Invalid original-source boundaries")
            payloads = {}
            for name, expected in entries.items():
                payload = archive.read(name)
                if not isinstance(expected, dict) or type(expected.get("size")) is not int or expected.get("size") != len(payload) or expected.get("sha256") != sha(payload):
                    raise BackupError("Archive payload size/checksum mismatch")
                payloads[name] = payload
            _, refs = inspect_state(payloads["state.json"])
            if set(payloads) != {"state.json"} | {"blobs/" + identity + ".blob" for identity in refs}:
                raise BackupError("Archive does not exactly account for referenced immutable files")
            for identity, (size, digest) in refs.items():
                payload = payloads["blobs/" + identity + ".blob"]
                if len(payload) != size or sha(payload) != digest:
                    raise BackupError("Metadata-to-blob checksum mismatch")
            return manifest, payloads
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as error:
        raise BackupError("Malformed or unreadable backup archive") from error


def publish_directory(staging: Path, destination: Path):
    if os.name == "nt":
        os.rename(staging, destination)  # Windows refuses an existing target.
        return
    if sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise BackupError("Exclusive atomic directory publication is unavailable on this host")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1) != 0:
            raise OSError(ctypes.get_errno(), "Exclusive directory publication failed")
        return
    raise BackupError("Exclusive restore publication is supported only on the tested Linux path or Windows; do not use fallback overwrite operations")


def restore_backup(archive_path, parent_path, name: str, *, stopped=False) -> dict:
    if not stopped:
        raise BackupError("Explicit --stopped acknowledgement is required")
    require_offline()
    if not re.fullmatch(r"demo-restore-[a-z0-9][a-z0-9-]{0,47}", name):
        raise BackupError("Destination name must be demo-restore- followed by a simple lowercase token")
    parent = safe_parent(parent_path)
    destination = checked_path(parent / name, directory=True, exists=False)
    archive_path = checked_path(archive_path)
    if destination.exists() or destination == archive_path or destination in archive_path.parents:
        raise BackupError("Restore requires a new isolated destination; nothing existing is overwritten")
    manifest, payloads = verified_archive(archive_path)
    reject_source_overlap(destination, manifest["sourceBoundaries"])
    staging = Path(tempfile.mkdtemp(prefix=".demo-restore-pending-", dir=parent))
    try:
        (staging / "files").mkdir()
        for member, payload in payloads.items():
            target = staging / "hub.json" if member == "state.json" else staging / "files" / member.split("/")[1]
            with target.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        # Recheck caller-selected ancestry before exclusive publication; no archive paths are extracted.
        safe_parent(parent)
        if destination.exists() or destination.is_symlink():
            raise BackupError("Destination appeared during restore; refusing overwrite")
        publish_directory(staging, destination)
        return {"destination": str(destination), "state": str(destination / "hub.json"), "blobs": str(destination / "files"),
                "manifestSha256": manifest["manifestSha256"], "applicationValidation": "Still required"}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--state", required=True)
    create.add_argument("--blobs", required=True)
    create.add_argument("--output", required=True)
    create.add_argument("--stopped", action="store_true", help="Acknowledge that the synthetic app has been stopped")
    restore = sub.add_parser("restore")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--parent", required=True)
    restore.add_argument("--name", required=True)
    restore.add_argument("--stopped", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--archive", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create_backup(args.state, args.blobs, args.output, stopped=args.stopped)
        elif args.command == "restore":
            result = restore_backup(args.archive, args.parent, args.name, stopped=args.stopped)
        else:
            manifest, payloads = verified_archive(args.archive)
            result = {"verifiedMembers": len(payloads), "manifestSha256": manifest["manifestSha256"], "applicationValidation": "Still required"}
        print(json.dumps(result, indent=2))
        return 0
    except (BackupError, OSError, ValueError, RecursionError) as error:
        print("Demo recovery refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
