"""Attachment boundary tests; synthetic bytes only; owns loopback port 5080."""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
import uuid
import test_api as api


class Attachments(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)
    setUp = api.Integration.setUp
    study = api.Integration.study
    item = api.Integration.item

    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 5080)) == 0:
                raise RuntimeError("Stop the existing preview before running attachment tests")
        subprocess.run([api.DOTNET, "build", "--no-incremental", "--nologo"], cwd=api.ROOT,
                       check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix="hub-attachments-")
        cls.data = Path(cls.temp.name) / "hub.json"
        cls.blobs = Path(cls.temp.name) / "files"
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT="Development", HUB_DEMO_ENABLED="true",
                       HUB_DATA=str(cls.data), HUB_FILES=str(cls.blobs), HUB_DEMO_FILE_RELEASE="true")
        cls.log = open(Path(cls.temp.name) / "server.log", "w+")
        cls.start()

    def upload(self, name="synthetic.txt", content=b"Synthetic attachment", **changes):
        payload = dict(name=name, contentBase64=base64.b64encode(content).decode(), parentId=None,
                       documentId=None, expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        payload.update(changes)
        return payload

    def create(self, **changes):
        request = self.upload(**changes)
        status, study, _ = self.alex.request("/api/studies/atlas/files", request)
        self.assertEqual(status, 200)
        return request, study, study["files"][-1]

    def test_access_csrf_and_prevalidation_no_blobs(self):
        count = len(list(self.blobs.iterdir()))
        payload = self.upload(contentBase64="invalid")
        self.assertEqual(self.sam.request("/api/studies/atlas/files", payload)[0], 404)
        self.assertEqual(self.admin.request("/api/studies/atlas/files", payload)[0], 404)
        self.assertEqual(self.sam.request("/api/studies/atlas/files")[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/files", payload, csrf=False)[0], 400)
        self.assertEqual(len(list(self.blobs.iterdir())), count)
        _, study, file = self.create()
        path = f'/api/studies/atlas/files/{file["id"]}'
        self.assertEqual(self.sam.request(path + "/download")[0], 404)
        self.assertEqual(self.admin.request(path + "/download")[0], 404)
        delete = dict(expectedRevision=study["revision"], requestId=str(uuid.uuid4()))
        self.assertEqual(self.sam.request(path + "/delete", delete)[0], 404)
        self.assertEqual(self.alex.request(path + "/delete", delete, csrf=False)[0], 400)

    def test_validation_and_no_orphans_on_rejected_input(self):
        count = len(list(self.blobs.iterdir()))
        bad = [dict(name=None), dict(name="../secret.txt"), dict(name="C:\\secret.txt"),
               dict(name="bad\r\nHeader.txt"), dict(name="page.html"), dict(name="file.exe"),
               dict(contentBase64=None), dict(contentBase64="invalid"), dict(content=b""),
               dict(content=b"\xff\xfe"), dict(content=b"nul\x00text"), dict(content=b"x" * (512 * 1024 + 1)),
               dict(name="fake.pdf", content=b"not pdf"), dict(name="fake.png", content=b"not png"),
               dict(name="fake.jpg", content=b"not jpg"), dict(parentId="beacon-protocol"),
               dict(parentId="protocol-1"), dict(documentId="missing"), dict(expectedRevision=-1)]
        reserved = ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
        bad.extend(dict(name=name + ".txt") for name in reserved)
        bad.extend([dict(name="con.TXT"), dict(name="pRn.notes.txt"), dict(name="lPt9.txt")])
        for changes in bad:
            with self.subTest(changes=str(changes)[:80]):
                expected = 409 if "expectedRevision" in changes else 400
                self.assertEqual(self.alex.request("/api/studies/atlas/files", self.upload(**changes))[0], expected)
        self.assertEqual(len(list(self.blobs.iterdir())), count)

    def test_file_search_member_only(self):
        marker = "Search" + uuid.uuid4().hex
        _, _, file = self.create(name=marker + ".txt", content=b"Synthetic bytes stay out of search")
        status, hits, _ = self.alex.request("/api/search?q=" + marker.lower())
        self.assertEqual(status, 200)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["studyId"], "atlas")
        self.assertEqual(hits[0]["item"]["id"], file["id"])
        self.assertEqual(hits[0]["item"]["kind"], "file")
        self.assertEqual(hits[0]["item"]["title"], file["name"])
        for client in [self.sam, self.admin]:
            self.assertEqual(client.request("/api/search?q=" + marker)[1], [])
            self.assertNotIn(file["id"], json.dumps(client.request("/api/search")[1]))

    def test_allowed_fixture_and_quarantine(self):
        fixture = (api.ROOT / "fixtures/demo-attachment.png").read_bytes()
        _, _, file = self.create(name="demo.png", content=fixture)
        self.assertEqual(file["status"], "DemoReleased")
        status, body, headers = self.alex.request(f'/api/studies/atlas/files/{file["id"]}/download')
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture)
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for name, content in [("modified.png", fixture + b"altered"), ("sample.pdf", b"%PDF-1.7\n/JavaScript synthetic"), ("sample.jpg", b"\xff\xd8\xffsynthetic")]:
            _, _, binary = self.create(name=name, content=content)
            self.assertEqual(binary["status"], "Quarantined")
            self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{binary["id"]}/download')[0], 409)

    def test_versions_replay_and_conflict(self):
        request, study, first = self.create(parentId="question-1")
        count = len(list(self.blobs.iterdir()))
        self.assertEqual(self.alex.request("/api/studies/atlas/files", request)[1], study)
        self.assertEqual(len(list(self.blobs.iterdir())), count)
        self.assertEqual(self.alex.request("/api/studies/atlas/files", dict(request, name="changed.txt"))[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/files", dict(request, requestId=str(uuid.uuid4())))[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/files", self.upload(documentId=first["id"]))[0], 400)
        _, _, second = self.create(parentId="question-1", documentId=first["id"], content=b"Synthetic revision")
        self.assertEqual(second["familyId"], first["familyId"])
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["documentId"], first["id"])
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{first["id"]}/download')[1], b"Synthetic attachment")

    def test_delete_and_deleted_parent(self):
        marker = uuid.uuid4().hex
        _, study, file = self.create(name=marker + ".txt", content=marker.encode())
        self.assertEqual(len(self.alex.request("/api/search?q=" + marker)[1]), 1)
        request = dict(expectedRevision=study["revision"], requestId=str(uuid.uuid4()))
        path = f'/api/studies/atlas/files/{file["id"]}'
        self.assertEqual(self.alex.request(path + "/delete", request)[0], 200)
        self.assertEqual(self.alex.request(path + "/delete", request)[0], 200)
        self.assertEqual(self.alex.request(path + "/download")[0], 404)
        self.assertEqual(self.alex.request("/api/search?q=" + marker)[1], [])
        self.assertNotIn(file["id"], [f["id"] for f in self.alex.request("/api/studies/atlas/files")[1]])
        for value in [self.study(), self.alex.request("/api/studies")[1]]:
            self.assertNotIn(file["name"], json.dumps(value))
            self.assertNotIn(file["sha256"], json.dumps(value))
        self.assertEqual(self.alex.request("/api/studies/atlas/files", self.upload(documentId=file["id"]))[0], 400)
        status, study, _ = self.alex.request("/api/studies/atlas/items", self.item())
        self.assertEqual(status, 200)
        parent = study["items"][-1]["id"]
        marker = uuid.uuid4().hex
        _, study, file = self.create(parentId=parent, name=marker + ".txt", content=marker.encode())
        self.assertEqual(len(self.alex.request("/api/search?q=" + marker)[1]), 1)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/items/{parent}/delete',
                         dict(expectedRevision=study["revision"], requestId=str(uuid.uuid4())))[0], 200)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/download')[0], 404)
        self.assertEqual(self.alex.request("/api/search?q=" + marker)[1], [])
        self.assertNotIn(file["id"], [f["id"] for f in self.alex.request("/api/studies/atlas/files")[1]])
        for value in [self.study(), self.alex.request("/api/studies")[1]]:
            self.assertNotIn(file["name"], json.dumps(value))
            self.assertNotIn(file["sha256"], json.dumps(value))

    def test_tampering_missing_blob_and_orphan(self):
        _, _, file = self.create()
        path = self.blobs / (file["id"] + ".blob")
        path.write_bytes(b"x" * file["size"])
        url = f'/api/studies/atlas/files/{file["id"]}/download'
        self.assertEqual(self.alex.request(url)[0], 409)
        path.unlink()
        self.assertEqual(self.alex.request(url)[0], 404)
        orphan = uuid.uuid4().hex
        (self.blobs / (orphan + ".blob")).write_bytes(b"Synthetic interrupted write")
        self.assertEqual(self.alex.request(f"/api/studies/atlas/files/{orphan}/download")[0], 404)
        self.assertNotIn(orphan, json.dumps(self.alex.request("/api/studies/atlas/files")[1]))

    def test_storage_configuration_rejects_application_root_and_symlink(self):
        linked = Path(self.temp.name) / "linked-storage"
        linked.symlink_to(api.ROOT, target_is_directory=True)
        for root in [api.ROOT / "wwwroot" / "uploads", linked]:
            result = subprocess.run([api.DOTNET, str(api.ROOT / "bin/Debug/net10.0/ResearchHub.dll")],
                                    cwd=api.ROOT, env=dict(self.env, HUB_FILES=str(root)),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Attachment storage must", result.stdout)

    def test_revocation(self):
        marker = "Revocation" + uuid.uuid4().hex
        _, _, file = self.create(name=marker + ".txt")
        self.assertEqual(len(self.alex.request("/api/search?q=" + marker)[1]), 1)
        self.assertEqual(self.admin.request("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-b"})[0], 200)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/download')[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/files")[0], 404)
        self.assertEqual(self.alex.request("/api/search?q=" + marker)[1], [])
        self.assertEqual(self.admin.request("/api/search?q=" + marker)[1], [])
        self.assertEqual(len(self.sam.request("/api/search?q=" + marker)[1]), 1)
        self.assertEqual(self.admin.request("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-a"})[0], 200)
        self.assertEqual(len(self.alex.request("/api/search?q=" + marker)[1]), 1)
        self.assertEqual(self.sam.request("/api/search?q=" + marker)[1], [])

    def test_z_restart_and_default_quarantine(self):
        request, before, file = self.create()
        self.stop()
        self.start()
        self.alex = api.Client().login("alex")
        self.assertEqual(self.alex.request("/api/studies/atlas/files", request)[1], before)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/download')[0], 200)
        self.stop()
        self.env["HUB_DEMO_FILE_RELEASE"] = "false"
        self.start()
        self.alex = api.Client().login("alex")
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/download')[0], 409)
        _, _, quarantined = self.create()
        self.assertEqual(quarantined["status"], "Quarantined")
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{quarantined["id"]}/download')[0], 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
