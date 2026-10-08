"""Real HTTP integration checks; stdlib only, synthetic data, loopback only.

Run: DOTNET=/path/to/dotnet python3 tests/test_api.py
The suite builds and owns port 5080; stop the preview before running.
"""
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
DOTNET = os.environ.get("DOTNET", "dotnet")
BASE = "http://127.0.0.1:5080"


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def request(self, path, payload=None, method=None, csrf=True, headers=None):
        head = dict(headers or {})
        if payload is not None:
            head["Content-Type"] = "application/json"
        if csrf and self.csrf:
            head["X-CSRF-TOKEN"] = self.csrf
        req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers=head, method=method)
        try:
            response = self.opener.open(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        data = response.read()
        try:
            data = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            pass
        return response.status, data, response.headers

    def login(self, identity):
        status, session, _ = self.request("/api/session")
        assert status == 200
        self.csrf = session["csrf"]
        assert self.request("/api/session", {"identity": identity})[0] == 200
        self.csrf = self.request("/api/session")[1]["csrf"]
        return self


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 5080)) == 0:
                raise RuntimeError("Stop the existing preview: tests require exclusive port 5080")
        subprocess.run([DOTNET, "build", "--no-incremental", "--nologo"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        cls.temp = tempfile.TemporaryDirectory(prefix="hub-integration-")
        cls.data = Path(cls.temp.name) / "hub.json"
        cls.env = dict(os.environ, ASPNETCORE_ENVIRONMENT="Development", HUB_DEMO_ENABLED="true", HUB_DATA=str(cls.data))
        cls.log = open(Path(cls.temp.name) / "server.log", "w+")
        cls.start()

    @classmethod
    def start(cls):
        cls.log.seek(0, 2)
        offset = cls.log.tell()
        cls.server = subprocess.Popen([DOTNET, str(ROOT / "bin/Debug/net10.0/ResearchHub.dll")], cwd=ROOT,
                                      env=cls.env, stdout=cls.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            if cls.server.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            try:
                cls.log.seek(offset)
                started = "Now listening on: http://127.0.0.1:5080" in cls.log.read()
                if started and Client().request("/api/session")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(.1)
        raise RuntimeError("Server did not start")

    @classmethod
    def stop(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait()

    @classmethod
    def tearDownClass(cls):
        cls.stop()
        cls.log.close()
        cls.temp.cleanup()

    def setUp(self):
        self.alex = Client().login("alex")
        self.sam = Client().login("sam")
        self.admin = Client().login("admin")

    def study(self, client=None, study="atlas"):
        status, value, _ = (client or self.alex).request("/api/studies/" + study)
        self.assertEqual(status, 200)
        return value

    def item(self, **changes):
        payload = dict(kind="discussion", title="Integration question", body="Synthetic test content",
                       expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        payload.update(changes)
        return payload

    def test_access_boundaries(self):
        self.assertEqual([s["id"] for s in self.alex.request("/api/studies")[1]], ["atlas"])
        self.assertEqual(self.admin.request("/api/studies")[1], [])
        for client, study, document in [(self.alex, "beacon", "beacon-protocol"), (self.sam, "atlas", "protocol-1"), (self.admin, "atlas", "protocol-1")]:
            self.assertEqual(client.request("/api/studies/" + study)[0], 404)
            self.assertEqual(client.request(f"/api/studies/{study}/documents/{document}/download")[0], 404)
            self.assertEqual(client.request(f"/api/studies/{study}/items", self.item())[0], 404)
            self.assertEqual(client.request(f"/api/studies/{study}/stage", dict(stage="Active", expectedRevision=1, requestId=str(uuid.uuid4())))[0], 404)
        self.assertEqual(self.alex.request("/api/search?q=Historical")[1], [])
        self.assertEqual(self.admin.request("/api/search")[1], [])
        for client in [self.alex, self.sam]:
            self.assertEqual(client.request("/api/admin")[0], 403)
            self.assertEqual(client.request("/api/admin/role", dict(identity="alex", role="Administrator"))[0], 403)
            self.assertEqual(client.request("/api/admin/mapping", dict(studyId="atlas", groupId="demo-group-b"))[0], 403)

    def test_csrf_and_host(self):
        for path, payload, client in [("/api/session", {"identity": "admin"}, self.alex), ("/api/studies/atlas/items", self.item(), self.alex), ("/api/studies/atlas/stage", {"stage": "Closed"}, self.alex), ("/api/admin/role", {"identity": "alex", "role": "Administrator"}, self.admin), ("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-b"}, self.admin)]:
            self.assertEqual(client.request(path, payload, csrf=False)[0], 400)
            self.assertEqual(client.request(path, payload, csrf=False, headers={"X-CSRF-TOKEN": "invalid"})[0], 400)
        self.assertEqual(self.alex.request("/api/session", headers={"Host": "attacker.example"})[0], 403)

    def test_invalid_inputs_and_cross_study_links(self):
        for changes in [dict(kind=None), dict(title=None), dict(body=None), dict(body=42), dict(title=[]), dict(title=" "), dict(title="x" * 181), dict(body="x" * 20001), dict(kind="script"), dict(requestId=None), dict(requestId="invalid"), dict(parentId="beacon-protocol"), dict(documentId="beacon-protocol"), dict(kind="reply", parentId=None), dict(documentId="missing")]:
            with self.subTest(changes=changes):
                self.assertEqual(self.alex.request("/api/studies/atlas/items", self.item(**changes))[0], 400)
        self.assertEqual(self.alex.request("/api/search?q=" + "x" * 201)[0], 400)
        self.assertEqual(self.alex.request("/api/session", {"identity": None})[0], 400)
        self.assertEqual(self.alex.request("/api/studies/atlas/stage", {"stage": None, "expectedRevision": self.study()["revision"], "requestId": str(uuid.uuid4())})[0], 400)
        self.assertEqual(self.admin.request("/api/admin/mapping", {"studyId": "atlas", "groupId": None})[0], 400)
        self.assertEqual(self.admin.request("/api/admin/role", {"identity": "alex", "role": None})[0], 400)
        self.assertEqual(self.alex.request("/api/studies/atlas/items", self.item(body="x" * 1048576))[0], 413)

    def test_idempotency_and_concurrency(self):
        payload = self.item()
        status, first, _ = self.alex.request("/api/studies/atlas/items", payload)
        self.assertEqual(status, 200)
        status, repeated, _ = self.alex.request("/api/studies/atlas/items", payload)
        self.assertEqual(status, 200)
        self.assertEqual(first, repeated)
        mismatched = dict(payload, body="Changed retry content")
        self.assertEqual(self.alex.request("/api/studies/atlas/items", mismatched)[0], 409)
        reused = dict(stage="Closed", expectedRevision=first["revision"], requestId=payload["requestId"])
        self.assertEqual(self.alex.request("/api/studies/atlas/stage", reused)[0], 409)
        payload["requestId"] = str(uuid.uuid4())
        self.assertEqual(self.alex.request("/api/studies/atlas/items", payload)[0], 409)

    def test_deleted_content_and_relationships(self):
        marker = "Removed" + uuid.uuid4().hex
        secret_body = "SyntheticRemovedBody" + uuid.uuid4().hex
        status, study, _ = self.alex.request("/api/studies/atlas/items", self.item(kind="document", title=marker, body=secret_body))
        self.assertEqual(status, 200)
        item = study["items"][-1]
        path = f'/api/studies/atlas/items/{item["id"]}/delete'
        request = dict(expectedRevision=study["revision"], requestId=str(uuid.uuid4()))
        self.assertEqual(self.sam.request(path, request)[0], 404)
        self.assertEqual(self.alex.request(path, request, csrf=False)[0], 400)
        self.assertEqual(self.alex.request(path, request)[0], 200)
        self.assertEqual(self.alex.request(path, request)[0], 200)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/documents/{item["id"]}/download')[0], 404)
        self.assertEqual(self.alex.request("/api/search?q=" + marker)[1], [])
        self.assertEqual(self.alex.request("/api/studies/atlas/items", self.item(documentId=item["id"]))[0], 400)
        tombstone = next(i for i in self.study()["items"] if i["id"] == item["id"])
        self.assertTrue(tombstone["deleted"])
        self.assertNotEqual(tombstone["body"], secret_body)
        self.assertNotIn(secret_body, json.dumps(self.study()))
        self.assertNotIn(secret_body, json.dumps(self.alex.request("/api/studies")[1]))

    def test_mapping_revocation_and_roles_do_not_grant_membership(self):
        self.assertEqual(self.admin.request("/api/admin/role", {"identity": "alex", "role": "Administrator"})[0], 200)
        self.assertEqual(self.alex.request("/api/admin")[0], 200)
        self.assertEqual(self.alex.request("/api/studies/beacon")[0], 404)
        self.assertEqual(self.admin.request("/api/admin/role", {"identity": "alex", "role": "Researcher"})[0], 200)
        self.assertEqual(self.alex.request("/api/admin")[0], 403)
        self.assertEqual(self.admin.request("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-b"})[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas")[0], 404)
        self.assertEqual(self.alex.request("/api/search")[1], [])
        self.assertEqual(self.alex.request("/api/studies/atlas/documents/protocol-1/download")[0], 404)
        self.assertEqual(self.sam.request("/api/studies/atlas")[0], 200)
        self.assertEqual(self.admin.request("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-a"})[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas")[0], 200)

    def test_lifecycle_and_reopen(self):
        before = self.study()
        for stage in ["Closed", "Active"]:
            payload = dict(stage=stage, expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
            self.assertEqual(self.alex.request("/api/studies/atlas/stage", payload)[0], 200)
            self.assertEqual(self.alex.request("/api/studies/atlas/stage", payload)[0], 200)
            if stage == "Closed":
                self.assertEqual(self.alex.request("/api/studies/atlas/items", self.item())[0], 409)
                self.assertEqual(self.alex.request("/api/studies/atlas/documents/protocol-1/download")[0], 200)
        self.assertEqual(before["items"], self.study()["items"])
        self.assertEqual(self.alex.request("/api/studies/atlas/items", self.item())[0], 200)

    def test_plain_text_download_and_stored_html(self):
        body = '<script>alert("synthetic")</script><img src=x onerror=alert(1)>'
        status, study, _ = self.alex.request("/api/studies/atlas/items", self.item(kind="document", title="../../synthetic.html", body=body))
        self.assertEqual(status, 200)
        item = study["items"][-1]
        status, content, headers = self.alex.request(f'/api/studies/atlas/documents/{item["id"]}/download')
        self.assertEqual(status, 200)
        self.assertEqual(content.decode(), body)
        self.assertIn("text/plain", headers["Content-Type"])
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertNotIn("synthetic.html", headers["Content-Disposition"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.alex.request("/api/studies/atlas/documents/missing/download")[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/documents/question-1/download")[0], 404)

    def test_production_startup_refuses_demo(self):
        for environment, enabled in [("Production", "true"), ("Production", "false"), ("Development", "false")]:
            result = subprocess.run([DOTNET, str(ROOT / "bin/Debug/net10.0/ResearchHub.dll")], cwd=ROOT,
                                    env=dict(self.env, ASPNETCORE_ENVIRONMENT=environment, HUB_DEMO_ENABLED=enabled),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Development-only", result.stdout)

    def test_z_restart_persistence(self):
        request = self.item(title="Survives restart")
        status, before, _ = self.alex.request("/api/studies/atlas/items", request)
        self.assertEqual(status, 200)
        self.stop()
        self.start()
        self.alex = Client().login("alex")
        self.assertEqual(self.study(), before)
        status, replayed, _ = self.alex.request("/api/studies/atlas/items", request)
        self.assertEqual(status, 200)
        self.assertEqual(replayed, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
