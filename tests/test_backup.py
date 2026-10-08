"""Offline recovery tool tests. Synthetic temp fixtures only; no app server required."""
import copy
import importlib.util
import json
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

TOOL = Path(__file__).resolve().parents[1] / "tools/backup_demo.py"
spec = importlib.util.spec_from_file_location("backup_demo", TOOL)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
REAL_OFFLINE = backup.require_offline


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".hub-backup-tests-", dir=TOOL.parents[2])
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.blobs = self.source / "files"
        self.blobs.mkdir()
        self.backups = self.root / "archives"
        self.backups.mkdir()
        self.recovery = self.root / "recovery"
        self.recovery.mkdir()
        self.identity = "a" * 32
        self.content = b"Synthetic retained attachment\n"
        file = dict(id=self.identity, size=len(self.content), sha256=backup.sha(self.content).upper(), deleted=True)
        self.state = dict(datasetKind="SyntheticDemo", roles={"admin": "Administrator"}, studies=[
            dict(id="atlas", groupId="demo-group-a", files=[file], handoffs=[dict(content=dict(files=[copy.deepcopy(file)]))])])
        self.state_path = self.source / "hub.json"
        self.write_state()
        (self.blobs / (self.identity + ".blob")).write_bytes(self.content)
        self.archive = self.backups / "synthetic.zip"
        self.offline = mock.patch.object(backup, "require_offline", return_value=None)
        self.offline.start()

    def tearDown(self):
        self.offline.stop()
        self.temp.cleanup()

    def write_state(self):
        self.state_path.write_bytes(backup.canonical(self.state))

    def create(self):
        return backup.create_backup(self.state_path, self.blobs, self.archive, stopped=True)

    def rewrite_archive(self, change, *, resign=True):
        with zipfile.ZipFile(self.archive) as archive:
            entries = {info.filename: archive.read(info) for info in archive.infolist()}
        manifest = json.loads(entries["manifest.json"])
        change(entries, manifest)
        if resign:
            unsigned = {k: v for k, v in manifest.items() if k != "manifestSha256"}
            manifest["manifestSha256"] = backup.sha(backup.canonical(unsigned))
        entries["manifest.json"] = backup.canonical(manifest)
        self.archive.unlink()
        with zipfile.ZipFile(self.archive, "x") as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)

    def test_complete_referenced_snapshot_and_tombstone_roundtrip(self):
        (self.blobs / ("b" * 32 + ".blob")).write_bytes(b"Unreferenced orphan must not enter backup")
        (self.blobs / "interrupted.pending").write_bytes(b"Incomplete write")
        original = self.state_path.read_bytes()
        result = self.create()
        manifest, members = backup.verified_archive(self.archive)
        self.assertEqual(set(members), {"state.json", "blobs/" + self.identity + ".blob"})
        self.assertNotIn(str(self.source), json.dumps(manifest))
        restored = backup.restore_backup(self.archive, self.recovery, "demo-restore-roundtrip", stopped=True)
        self.assertEqual(Path(restored["state"]).read_bytes(), original)
        self.assertEqual((Path(restored["blobs"]) / (self.identity + ".blob")).read_bytes(), self.content)
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(restored["manifestSha256"], result["manifestSha256"])
        self.assertEqual(restored["applicationValidation"], "Still required")

    def test_marker_credentials_and_non_demo_groups_fail_closed(self):
        for changes in [dict(datasetKind=None), dict(datasetKind="Production"), dict(connectionString="not a real credential"),
                        dict(roles={"actual-user": "Administrator"}), dict(studies=[dict(groupId="actual-group", files=[])])]:
            with self.subTest(changes=changes):
                base = self.state
                self.state = dict(base, **changes)
                self.write_state()
                with self.assertRaises(backup.BackupError): self.create()
                self.assertFalse(self.archive.exists())
                self.state = base
        self.state["studies"][0]["configuration"] = {"api_key": "synthetic forbidden credential field"}
        self.write_state()
        with self.assertRaises(backup.BackupError): self.create()

    def test_existing_destinations_and_source_overlap_never_overwrite(self):
        self.create()
        original = self.archive.read_bytes()
        with self.assertRaises(backup.BackupError): self.create()
        self.assertEqual(self.archive.read_bytes(), original)
        target = self.recovery / "demo-restore-existing"
        target.mkdir()
        (target / "keep.txt").write_text("Keep this file")
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.archive, self.recovery, target.name, stopped=True)
        self.assertEqual((target / "keep.txt").read_text(), "Keep this file")
        for parent in [self.source, self.blobs]:
            with self.assertRaises(backup.BackupError):
                backup.restore_backup(self.archive, parent, "demo-restore-overlap", stopped=True)
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.state_path, self.blobs, self.source / "overlap.zip", stopped=True)

    def test_symlinks_traversal_repo_and_webroot_are_refused(self):
        self.create()
        link = self.root / "linked-state.json"
        link.symlink_to(self.state_path)
        with self.assertRaises(backup.BackupError): backup.create_backup(link, self.blobs, self.backups / "other.zip", stopped=True)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.recovery, target_is_directory=True)
        with self.assertRaises(backup.BackupError): backup.restore_backup(self.archive, linked_parent, "demo-restore-link", stopped=True)
        for name in ["../escape", "demo-restore-../escape", "demo-restore-UPPER", "C:\\escape", "demo-restore-"]:
            with self.assertRaises(backup.BackupError): backup.restore_backup(self.archive, self.recovery, name, stopped=True)
        for component in ["wwwroot", "repo"]:
            parent = self.root / component
            parent.mkdir()
            if component == "repo":
                (parent / ".git").mkdir()
                (parent / ".git" / "HEAD").write_text("ref: refs/heads/main")
            with self.assertRaises(backup.BackupError): backup.restore_backup(self.archive, parent, "demo-restore-rejected", stopped=True)
        blob = self.blobs / (self.identity + ".blob")
        saved = self.root / "original.blob"
        blob.rename(saved)
        blob.symlink_to(saved)
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.state_path, self.blobs, self.backups / "linked-blob.zip", stopped=True)

    def test_referenced_bytes_and_manifest_corruption_fail_closed(self):
        blob = self.blobs / (self.identity + ".blob")
        blob.write_bytes(b"Tampered")
        with self.assertRaises(backup.BackupError): self.create()
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.backups.iterdir()), [])
        blob.write_bytes(self.content)
        self.create()
        self.rewrite_archive(lambda entries, manifest: entries.__setitem__("blobs/" + self.identity + ".blob", b"Tampered payload"))
        with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)
        self.assertEqual(list(self.recovery.iterdir()), [])

    def test_canonical_manifest_and_state_accounting(self):
        self.create()
        self.rewrite_archive(lambda entries, manifest: manifest.__setitem__("handoffValidation", "tampered"), resign=False)
        with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)
        self.archive.unlink(); self.create()
        def drop_blob(entries, manifest):
            name = "blobs/" + self.identity + ".blob"
            entries.pop(name); manifest["members"].pop(name)
        self.rewrite_archive(drop_blob)
        with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)
        self.archive.unlink(); self.create()
        def state_mismatch(entries, manifest):
            source = json.loads(entries["state.json"])
            source["studies"][0]["files"][0]["sha256"] = "0" * 64
            entries["state.json"] = backup.canonical(source)
            manifest["members"]["state.json"] = {"size": len(entries["state.json"]), "sha256": backup.sha(entries["state.json"])}
        self.rewrite_archive(state_mismatch)
        with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)

    def test_malformed_paths_duplicate_members_symlinks_and_bombs(self):
        self.create()
        good = self.archive.read_bytes()
        for name in ["../outside", "/absolute", "C:\\outside", "blobs/../outside", "unexpected.txt", "STATE.JSON"]:
            self.archive.write_bytes(good)
            with zipfile.ZipFile(self.archive, "a") as archive: archive.writestr(name, b"bad")
            with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)
        self.archive.write_bytes(good)
        with zipfile.ZipFile(self.archive, "a") as archive:
            info = zipfile.ZipInfo("blobs/" + "c" * 32 + ".blob")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"/outside")
        with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)
        self.archive.write_bytes(good)
        with zipfile.ZipFile(self.archive, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("blobs/" + "c" * 32 + ".blob", b"x" * (backup.MAX_BLOB + 1))
        with self.assertRaises(backup.BackupError): backup.verified_archive(self.archive)

    def test_interrupted_publish_cleans_only_owned_staging(self):
        self.create()
        keeper = self.recovery / "unrelated.txt"
        keeper.write_text("Unrelated data")
        with mock.patch.object(backup, "publish_directory", side_effect=OSError("Simulated publish failure")):
            with self.assertRaises(OSError): backup.restore_backup(self.archive, self.recovery, "demo-restore-interrupted", stopped=True)
        self.assertEqual(list(self.recovery.iterdir()), [keeper])
        self.assertEqual(keeper.read_text(), "Unrelated data")
        original = self.state_path.read_bytes()
        self.archive.unlink()
        reader = backup.read_bounded
        reads = 0
        def changed(path, limit):
            nonlocal reads
            if path == self.state_path:
                reads += 1
                if reads == 2: return b"Concurrent source mutation"
            return reader(path, limit)
        with mock.patch.object(backup, "read_bounded", side_effect=changed):
            with self.assertRaises(backup.BackupError): self.create()
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_explicit_offline_ack_and_probe_fail_closed(self):
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.state_path, self.blobs, self.archive)
        with mock.patch.object(socket, "create_connection", return_value=mock.MagicMock()):
            with self.assertRaises(backup.BackupError): REAL_OFFLINE()
        with mock.patch.object(socket, "create_connection", side_effect=PermissionError("Probe forbidden")):
            with self.assertRaises(backup.BackupError): REAL_OFFLINE()
        with mock.patch.object(socket, "create_connection", side_effect=ConnectionRefusedError()):
            REAL_OFFLINE()

    def test_atomic_destination_race_refuses_existing_empty_directory(self):
        self.create()
        actual_publish = backup.publish_directory
        target = self.recovery / "demo-restore-race"
        def race(staging, destination):
            destination.mkdir()
            actual_publish(staging, destination)
        with mock.patch.object(backup, "publish_directory", side_effect=race):
            with self.assertRaises(OSError): backup.restore_backup(self.archive, self.recovery, target.name, stopped=True)
        self.assertTrue(target.is_dir())
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(list(self.recovery.iterdir()), [target])


if __name__ == "__main__":
    unittest.main(verbosity=2)
