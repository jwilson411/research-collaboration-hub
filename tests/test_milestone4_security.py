"""Independent document/handoff boundary regressions; synthetic loopback data only."""
import json
import unittest
import uuid
import test_api as api
import test_attachments as attachments


class Milestone4Security(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    setUpClass = classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)
    study = api.Integration.study
    item = api.Integration.item
    upload = attachments.Attachments.upload
    create_file = attachments.Attachments.create

    def setUp(self):
        api.Integration.setUp(self)
        self.reviewer = api.Client().login("reviewer")
        self.lead = api.Client().login("lead")

    def documents(self, client=None):
        status, result, _ = (client or self.alex).request("/api/studies/atlas/documents")
        self.assertEqual(status, 200)
        return result

    def document_payload(self, **changes):
        payload = dict(title="Independent " + uuid.uuid4().hex, body="Synthetic document " + uuid.uuid4().hex,
                       fileIds=[], expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        payload.update(changes)
        return payload

    def create_document(self, **changes):
        request = self.document_payload(**changes)
        existing = {v["item"]["id"] for v in self.documents()["versions"]}
        status, _, _ = self.alex.request("/api/studies/atlas/documents", request)
        self.assertEqual(status, 200)
        added = [v for v in self.documents()["versions"] if v["item"]["id"] not in existing]
        self.assertEqual(len(added), 1)
        return request, added[0]

    def state(self, client, version_id, status, **changes):
        request = dict(status=status, reason="Synthetic review rationale", expectedRevision=self.study()["revision"],
                       requestId=str(uuid.uuid4()))
        request.update(changes)
        return client.request(f"/api/studies/atlas/documents/{version_id}/state", request)

    def handoff(self, item_ids=None, file_ids=None, **changes):
        request = dict(title="Synthetic handoff " + uuid.uuid4().hex, summary="Independent handoff boundary check",
                       expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        if item_ids is not None:
            request["itemIds"] = item_ids
        if file_ids is not None:
            request["fileIds"] = file_ids
        request.update(changes)
        return request

    def create_handoff(self, item_ids, file_ids):
        request = self.handoff(item_ids, file_ids)
        status, snapshot, _ = self.alex.request("/api/studies/atlas/handoffs", request)
        self.assertEqual(status, 200)
        return request, snapshot

    def test_document_authorization_csrf_and_role_transitions(self):
        payload, version = self.create_document()
        version_id = version["item"]["id"]
        for client in [self.sam, self.admin]:
            self.assertEqual(client.request("/api/studies/atlas/documents")[0], 404)
            self.assertEqual(client.request("/api/studies/atlas/documents", self.document_payload())[0], 404)
            self.assertEqual(client.request(f"/api/studies/atlas/documents/{version_id}/versions", self.document_payload())[0], 404)
            self.assertEqual(self.state(client, version_id, "Review")[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/documents", self.document_payload(), csrf=False)[0], 400)
        self.assertEqual(self.alex.request(f"/api/studies/atlas/documents/{version_id}/versions", self.document_payload(), csrf=False)[0], 400)
        self.assertEqual(self.alex.request(f"/api/studies/atlas/documents/{version_id}/state",
                         dict(status="Review", reason="No token", expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())), csrf=False)[0], 400)
        self.assertEqual(self.state(self.alex, version_id, "Review")[0], 200)
        self.assertEqual(self.state(self.alex, version_id, "Accepted")[0], 403)
        self.assertEqual(self.state(self.reviewer, version_id, "Accepted")[0], 403)
        self.assertEqual(self.state(self.reviewer, version_id, "Draft")[0], 200)
        self.assertEqual(self.state(self.alex, version_id, "Review")[0], 200)
        acceptance = dict(status="Accepted", reason="Lead review", expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        self.assertEqual(self.lead.request(f"/api/studies/atlas/documents/{version_id}/state", acceptance)[0], 200)
        self.assertEqual(self.alex.request(f"/api/studies/atlas/documents/{version_id}/state", acceptance)[0], 403)
        self.assertEqual(self.reviewer.request(f"/api/studies/atlas/documents/{version_id}/state", acceptance)[0], 403)
        self.assertEqual(self.state(self.alex, version_id, "Superseded")[0], 403)
        self.assertEqual(self.state(self.reviewer, version_id, "Superseded")[0], 403)
        self.assertEqual(self.state(self.lead, version_id, "Superseded")[0], 200)
        final = next(v for v in self.documents()["versions"] if v["item"]["id"] == version_id)
        self.assertEqual(final["status"], "Superseded")
        for key in ["id", "title", "body", "author", "createdAt", "version"]:
            self.assertEqual(final["item"][key], version["item"][key])
        self.assertEqual(self.lead.request(f"/api/studies/atlas/items/{version_id}/delete",
                         dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 409)

    def test_protocol_designation_is_not_document_acceptance(self):
        _, version = self.create_document()
        version_id = version["item"]["id"]
        designation = dict(kind="item", id=version_id, reason="Working reference only",
                           expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request("/api/studies/atlas/protocol", designation)[0], 200)
        self.assertEqual(next(v for v in self.documents()["versions"] if v["item"]["id"] == version_id)["status"], "Draft")
        self.assertEqual(self.state(self.alex, version_id, "Review")[0], 200)
        self.assertEqual(self.state(self.lead, version_id, "Accepted")[0], 200)
        self.assertEqual(self.state(self.lead, version_id, "Superseded")[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/protocol", dict(kind=None, id=None, reason="Clear working reference",
                         expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 200)
        self.assertEqual(self.state(self.lead, version_id, "Superseded")[0], 200)

    def test_document_versions_idempotency_and_exact_evidence(self):
        request, first = self.create_document()
        first_id = first["item"]["id"]
        before_count = len(self.documents()["versions"])
        self.assertEqual(self.alex.request("/api/studies/atlas/documents", request)[0], 200)
        self.assertEqual(len(self.documents()["versions"]), before_count)
        self.assertEqual(self.alex.request("/api/studies/atlas/documents", dict(request, body="Changed retry"))[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/documents", dict(request, requestId=str(uuid.uuid4())))[0], 409)
        second_request = self.document_payload(title=first["item"]["title"], body="Second immutable version")
        self.assertEqual(self.alex.request(f"/api/studies/atlas/documents/{first_id}/versions", second_request)[0], 200)
        family = [v for v in self.documents()["versions"] if v["familyId"] == first["familyId"]]
        self.assertEqual(len(family), 2)
        second = next(v for v in family if v["item"]["id"] != first_id)
        self.assertEqual(second["previousVersionId"], first_id)
        self.assertEqual(next(v for v in family if v["item"]["id"] == first_id)["item"]["body"], request["body"])
        for version in [first, second]:
            self.assertEqual(self.state(self.alex, version["item"]["id"], "Review")[0], 200)
        self.assertEqual(self.state(self.lead, first_id, "Accepted")[0], 200)
        self.assertEqual(self.state(self.lead, second["item"]["id"], "Accepted")[0], 409)
        self.assertEqual(self.state(self.lead, first_id, "Superseded")[0], 200)
        self.assertEqual(self.state(self.lead, second["item"]["id"], "Accepted")[0], 200)
        self.assertEqual(self.alex.request(f"/api/studies/atlas/documents/{first_id}/download")[1].decode(), request["body"])

    def test_document_invalid_and_foreign_evidence(self):
        for changes in [dict(title=None), dict(body=None), dict(title=" "), dict(body="x" * 20001),
                        dict(fileIds=["beacon-protocol"]), dict(fileIds=[None])]:
            self.assertEqual(self.alex.request("/api/studies/atlas/documents", self.document_payload(**changes))[0], 400)
        _, version = self.create_document()
        self.assertEqual(self.state(self.alex, version["item"]["id"], None)[0], 400)
        self.assertEqual(self.state(self.alex, version["item"]["id"], "Review", reason=None)[0], 400)
        self.assertEqual(self.alex.request("/api/studies/atlas/documents/beacon-protocol/versions", self.document_payload())[0], 404)

    def test_accepted_document_preserves_file_and_parent_evidence(self):
        status, study, _ = self.alex.request("/api/studies/atlas/items", self.item())
        self.assertEqual(status, 200)
        parent = study["items"][-1]["id"]
        status, study, _ = self.alex.request("/api/studies/atlas/items", self.item(kind="reply", parentId=parent))
        self.assertEqual(status, 200)
        reply = study["items"][-1]["id"]
        _, _, file = self.create_file(parentId=reply)
        _, version = self.create_document(fileIds=[file["id"]])
        version_id = version["item"]["id"]
        self.assertEqual(self.state(self.alex, version_id, "Review")[0], 200)
        self.assertEqual(self.state(self.lead, version_id, "Accepted")[0], 200)
        for path in [f'/api/studies/atlas/files/{file["id"]}/delete', f"/api/studies/atlas/items/{parent}/delete", f"/api/studies/atlas/items/{reply}/delete"]:
            self.assertEqual(self.alex.request(path, dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 409)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/download')[0], 200)

    def test_acceptance_rejects_now_unavailable_file(self):
        for missing in [False, True]:
            _, _, file = self.create_file()
            _, version = self.create_document(fileIds=[file["id"]])
            version_id = version["item"]["id"]
            self.assertEqual(self.state(self.alex, version_id, "Review")[0], 200)
            if missing:
                (self.blobs / (file["id"] + ".blob")).unlink()
            else:
                self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/delete',
                                 dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 200)
            self.assertEqual(self.state(self.lead, version_id, "Accepted")[0], 409)
            self.assertEqual(next(v for v in self.documents()["versions"] if v["item"]["id"] == version_id)["status"], "Review")

    def test_deleted_document_review_reason_is_not_exposed(self):
        _, version = self.create_document()
        version_id = version["item"]["id"]
        marker = "RemovedReviewReason" + uuid.uuid4().hex
        self.assertEqual(self.state(self.alex, version_id, "Review", reason=marker)[0], 200)
        self.assertEqual(self.state(self.reviewer, version_id, "Draft", reason=marker)[0], 200)
        _, snapshot = self.create_handoff([version_id], [])
        self.assertEqual(self.alex.request(f"/api/studies/atlas/items/{version_id}/delete",
                         dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 200)
        for response in [self.study(), self.alex.request("/api/studies")[1], self.documents(),
                         self.alex.request("/api/studies/atlas/handoffs/" + snapshot["id"])[1]]:
            self.assertNotIn(marker, json.dumps(response))
        self.assertIn(marker, self.data.read_text())

    def test_handoff_access_csrf_stale_and_replay(self):
        payload = self.handoff(["question-1"], [])
        for client in [self.sam, self.admin]:
            self.assertEqual(client.request("/api/studies/atlas/handoffs")[0], 404)
            self.assertEqual(client.request("/api/studies/atlas/handoffs", payload)[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs", payload, csrf=False)[0], 400)
        status, snapshot, _ = self.alex.request("/api/studies/atlas/handoffs", payload)
        self.assertEqual(status, 200)
        path = "/api/studies/atlas/handoffs/" + snapshot["id"]
        for client in [self.sam, self.admin]:
            self.assertEqual(client.request(path)[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs", payload)[1], snapshot)
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs", dict(payload, summary="Changed replay"))[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs", dict(payload, requestId=str(uuid.uuid4())))[0], 409)
        for changes in [dict(itemIds=["beacon-protocol"]), dict(fileIds=["missing"]), dict(title=None), dict(summary="x" * 2001), dict(itemIds=[None])]:
            self.assertEqual(self.alex.request("/api/studies/atlas/handoffs", self.handoff([], [], **changes))[0], 400)

    def test_handoff_no_deleted_snapshot_body_or_filename_bypass(self):
        marker = "SnapshotSecret" + uuid.uuid4().hex
        status, study, _ = self.alex.request("/api/studies/atlas/items", self.item(body=marker))
        self.assertEqual(status, 200)
        item_id = study["items"][-1]["id"]
        filename = "SnapshotFile" + uuid.uuid4().hex + ".txt"
        _, _, file = self.create_file(name=filename, content=filename.encode())
        replay, snapshot = self.create_handoff([item_id], [file["id"]])
        self.assertIn(marker, json.dumps(snapshot))
        self.assertIn(filename, json.dumps(snapshot))
        raw_before = self.data.read_text()
        self.assertEqual(self.alex.request(f"/api/studies/atlas/items/{item_id}/delete", dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 200)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/files/{file["id"]}/delete', dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 200)
        path = "/api/studies/atlas/handoffs/" + snapshot["id"]
        status, redacted, _ = self.alex.request(path)
        self.assertEqual(status, 200)
        self.assertTrue(redacted["redacted"])
        self.assertEqual(redacted["sha256"], snapshot["sha256"])
        for response in [redacted, self.alex.request("/api/studies/atlas/handoffs", replay)[1], self.study(), self.alex.request("/api/studies")[1], self.alex.request("/api/studies/atlas/handoffs")[1]]:
            self.assertNotIn(marker, json.dumps(response))
            self.assertNotIn(filename, json.dumps(response))
            self.assertNotIn(file["sha256"], json.dumps(response))
        self.assertIn(marker, raw_before)
        self.assertIn(marker, self.data.read_text())  # fixed stored record; HTTP projection controls availability

    def test_handoff_revocation_and_tampered_files(self):
        _, _, file = self.create_file()
        _, snapshot = self.create_handoff([], [file["id"]])
        path = "/api/studies/atlas/handoffs/" + snapshot["id"]
        (self.blobs / (file["id"] + ".blob")).write_bytes(b"x" * file["size"])
        status, projected, _ = self.alex.request(path)
        self.assertEqual(status, 200)
        self.assertTrue(projected["redacted"])
        self.assertFalse(projected["files"][0]["available"])
        self.assertEqual(self.admin.config("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-b"})[0], 200)
        self.assertEqual(self.alex.request(path)[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs")[0], 404)
        self.assertEqual(self.admin.request(path)[0], 404)
        self.assertEqual(self.sam.request(path)[0], 200)
        self.assertEqual(self.admin.config("/api/admin/mapping", {"studyId": "atlas", "groupId": "demo-group-a"})[0], 200)

    def test_z_snapshot_and_document_restart_persistence(self):
        _, version = self.create_document()
        payload, snapshot = self.create_handoff([version["item"]["id"]], [])
        self.stop()
        self.start()
        self.alex = api.Client().login("alex")
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs/" + snapshot["id"])[1], snapshot)
        self.assertEqual(self.alex.request("/api/studies/atlas/handoffs", payload)[1], snapshot)
        actual = next(v for v in self.documents()["versions"] if v["item"]["id"] == version["item"]["id"])
        self.assertEqual(actual, version)

    def test_z_release_policy_rechecked_by_acceptance_and_snapshot(self):
        _, _, file = self.create_file()
        _, version = self.create_document(fileIds=[file["id"]])
        version_id = version["item"]["id"]
        self.assertEqual(self.state(self.alex, version_id, "Review")[0], 200)
        _, snapshot = self.create_handoff([], [file["id"]])
        self.stop()
        self.env["HUB_DEMO_FILE_RELEASE"] = "false"
        self.start()
        try:
            self.alex = api.Client().login("alex")
            self.lead = api.Client().login("lead")
            self.assertEqual(self.state(self.lead, version_id, "Accepted")[0], 409)
            status, projected, _ = self.alex.request("/api/studies/atlas/handoffs/" + snapshot["id"])
            self.assertEqual(status, 200)
            self.assertTrue(projected["redacted"])
            self.assertFalse(projected["files"][0]["available"])
        finally:
            self.stop()
            self.env["HUB_DEMO_FILE_RELEASE"] = "true"
            self.start()


if __name__ == "__main__":
    unittest.main(verbosity=2)
