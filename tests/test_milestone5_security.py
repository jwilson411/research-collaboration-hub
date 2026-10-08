"""Independent board and personal onboarding boundary checks; synthetic loopback only."""
import json
import unittest
import uuid
import test_api as api
import test_attachments as attachments


class Milestone5Security(unittest.TestCase):
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    setUpClass = classmethod(attachments.Attachments.setUpClass.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)
    study = api.Integration.study
    item = api.Integration.item

    def setUp(self):
        api.Integration.setUp(self)
        self.reviewer = api.Client().login("reviewer")
        self.lead = api.Client().login("lead")

    def mutation(self, **changes):
        payload = dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        payload.update(changes)
        return payload

    def board(self):
        payload = self.mutation(title="Independent board " + uuid.uuid4().hex, purpose="Synthetic ideas", responsibleId="alex")
        status, result, _ = self.alex.request("/api/studies/atlas/boards", payload)
        self.assertEqual(status, 200)
        return payload, result

    def idea(self, board_id, **changes):
        payload = self.mutation(title="Synthetic idea " + uuid.uuid4().hex, body="Synthetic idea body " + uuid.uuid4().hex)
        payload.update(changes)
        status, result, _ = self.alex.request(f"/api/studies/atlas/boards/{board_id}/ideas", payload)
        self.assertEqual(status, 200)
        return payload, result, result["ideas"][-1]

    def get_board(self, board_id, client=None):
        status, result, _ = (client or self.alex).request(f"/api/studies/atlas/boards/{board_id}")
        self.assertEqual(status, 200)
        return result

    def onboarding(self, client=None):
        status, result, _ = (client or self.alex).request("/api/studies/atlas/onboarding")
        self.assertEqual(status, 200)
        return result

    def progress(self, result, step, completed=True, **changes):
        payload = dict(stepId=step["id"], completed=completed, contextKey=step["contextKey"],
                       expectedRevision=result["revision"], requestId=str(uuid.uuid4()))
        payload.update(changes)
        return payload

    def test_board_membership_cross_board_and_csrf(self):
        _, board = self.board()
        board_id = board["id"]
        _, _, idea = self.idea(board_id)
        base = f"/api/studies/atlas/boards/{board_id}"
        for client in [self.sam, self.admin]:
            for path in ["/api/studies/atlas/boards", base, base + "/export"]:
                self.assertEqual(client.request(path)[0], 404)
            self.assertEqual(client.request(base + "/ideas", self.mutation(title="Other", body="Other"))[0], 404)
        self.assertEqual(self.alex.request(base + "/ideas", self.mutation(title="No token", body="No token"), csrf=False)[0], 400)
        _, other = self.board()
        self.assertEqual(self.alex.request(f'/api/studies/atlas/boards/{other["id"]}/ideas/{idea["id"]}/versions',
                         self.mutation(title="Cross board", body="Must not edit"))[0], 404)
        self.assertEqual(self.alex.request("/api/studies/beacon/boards/" + board_id)[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/boards", self.mutation(title="Bad responsible", purpose="Synthetic", responsibleId="sam"))[0], 400)

    def test_board_reorder_complete_and_idempotent(self):
        _, board = self.board()
        board_id = board["id"]
        _, _, first = self.idea(board_id)
        _, _, second = self.idea(board_id)
        path = f"/api/studies/atlas/boards/{board_id}/reorder"
        for order in [[first["id"]], [first["id"], first["id"]], [first["id"], "foreign"], [None, second["id"]]]:
            self.assertEqual(self.alex.request(path, self.mutation(ideaIds=order))[0], 400)
        request = self.mutation(ideaIds=[second["id"], first["id"]])
        status, result, _ = self.alex.request(path, request)
        self.assertEqual(status, 200)
        self.assertEqual(result["ideaOrder"], request["ideaIds"])
        self.assertEqual(self.alex.request(path, request)[1], result)
        self.assertEqual(self.alex.request(path, dict(request, ideaIds=[first["id"], second["id"]]))[0], 409)
        self.assertEqual(self.alex.request(path, dict(request, requestId=str(uuid.uuid4())))[0], 409)

    def test_board_archiving_role_before_replay_and_closed_study(self):
        _, board = self.board()
        board_id = board["id"]
        _, _, idea = self.idea(board_id)
        path = f"/api/studies/atlas/boards/{board_id}"
        archive = self.mutation(status="Archived", reason="Synthetic moderation")
        self.assertEqual(self.reviewer.request(path + "/state", archive)[0], 200)
        self.assertEqual(self.alex.request(path + "/state", archive)[0], 403)
        self.assertEqual(self.alex.request(path + "/ideas", self.mutation(title="Archived write", body="Blocked"))[0], 409)
        self.assertEqual(self.alex.request(path + "/reorder", self.mutation(ideaIds=[idea["id"]]))[0], 409)
        self.assertEqual(self.alex.request(path + f'/ideas/{idea["id"]}/decisions', self.mutation(versionId=idea["currentVersionId"], title="Blocked", rationale="Archived"))[0], 409)
        self.assertEqual(self.lead.request(path + "/state", self.mutation(status="Active", reason="Resume"))[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas/stage", self.mutation(stage="Closed"))[0], 200)
        try:
            self.assertEqual(self.alex.request(path + "/ideas", self.mutation(title="Closed write", body="Blocked"))[0], 409)
            self.assertEqual(self.lead.request(path + "/state", self.mutation(status="Archived", reason="Closed study"))[0], 409)
        finally:
            self.assertEqual(self.alex.request("/api/studies/atlas/stage", self.mutation(stage="Active"))[0], 200)

    def test_board_exact_revision_decision_and_retained_evidence(self):
        _, board = self.board()
        board_id = board["id"]
        original, _, idea = self.idea(board_id)
        idea_id, first_version = idea["id"], idea["currentVersionId"]
        path = f"/api/studies/atlas/boards/{board_id}/ideas/{idea_id}"
        status, updated, _ = self.alex.request(path + "/versions", self.mutation(title="Revised idea", body="Different synthetic revision"))
        self.assertEqual(status, 200)
        updated_idea = next(i for i in updated["ideas"] if i["id"] == idea_id)
        self.assertNotEqual(updated_idea["currentVersionId"], first_version)
        first = next(v for v in updated_idea["versions"] if v["item"]["id"] == first_version)
        self.assertEqual(first["item"]["body"], original["body"])
        self.assertEqual(self.alex.request("/api/studies/atlas/items",
                         self.item(kind="decision", parentId=first_version))[0], 400)
        decision_request = self.mutation(versionId=first_version, title="Choose original idea", rationale="Synthetic reason")
        status, result, _ = self.alex.request(path + "/decisions", decision_request)
        self.assertEqual(status, 200)
        self.assertIsNotNone(result["decisionId"])
        self.assertEqual(self.alex.request(path + "/decisions", decision_request)[1], result)
        first = next(v for i in self.get_board(board_id)["ideas"] if i["id"] == idea_id for v in i["versions"] if v["item"]["id"] == first_version)
        self.assertIn(result["decisionId"], [d["id"] for d in first["decisions"]])
        self.assertEqual(self.alex.request(path + "/delete", self.mutation())[0], 409)
        self.assertEqual(self.alex.request(f"/api/studies/atlas/items/{first_version}/delete", self.mutation())[0], 409)
        _, _, other = self.idea(board_id)
        self.assertEqual(self.alex.request(path + "/decisions", self.mutation(versionId=other["currentVersionId"], title="Foreign", rationale="Wrong logical idea"))[0], 404)

    def test_board_deleted_history_and_handoff_redacted(self):
        _, board = self.board()
        board_id = board["id"]
        marker = "RemovedBoardBody" + uuid.uuid4().hex
        _, _, idea = self.idea(board_id, body=marker)
        snapshot_request = self.mutation(title="Board evidence snapshot", summary="Synthetic", itemIds=[idea["currentVersionId"]], fileIds=[])
        status, snapshot, _ = self.alex.request("/api/studies/atlas/handoffs", snapshot_request)
        self.assertEqual(status, 200)
        self.assertEqual(self.alex.request(f'/api/studies/atlas/boards/{board_id}/ideas/{idea["id"]}/delete', self.mutation())[0], 200)
        for response in [self.get_board(board_id), self.alex.request("/api/studies/atlas/boards")[1], self.study(),
                         self.alex.request("/api/studies")[1], self.alex.request("/api/studies/atlas/handoffs/" + snapshot["id"])[1],
                         self.alex.request("/api/studies/atlas/handoffs", snapshot_request)[1]]:
            self.assertNotIn(marker, json.dumps(response))
        status, export, _ = self.alex.request(f"/api/studies/atlas/boards/{board_id}/export")
        self.assertEqual(status, 200)
        self.assertNotIn(marker, export.decode())
        self.assertEqual(self.alex.request("/api/search?q=" + marker)[1], [])

    def test_onboarding_user_binding_private_serialization_and_revisions(self):
        before_study = self.study()["revision"]
        alex = self.onboarding()
        reviewer_before = self.onboarding(self.reviewer)
        step = next(s for s in alex["steps"] if s["available"])
        request = self.progress(alex, step, userId="reviewer", identity="reviewer")
        status, completed, _ = self.alex.request("/api/studies/atlas/onboarding", request)
        self.assertEqual(status, 200)
        self.assertTrue(next(s for s in completed["steps"] if s["id"] == step["id"])["completed"])
        self.assertEqual(self.study()["revision"], before_study)
        self.assertEqual(self.onboarding(self.reviewer), reviewer_before)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding?userId=reviewer&identity=reviewer")[1], completed)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", request)[1], completed)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", dict(request, completed=False))[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", dict(request, requestId=str(uuid.uuid4())))[0], 409)
        for public in [self.study(), self.alex.request("/api/studies")[1]]:
            self.assertNotIn("personalOnboarding", public if isinstance(public, dict) else json.dumps(public))
            self.assertNotIn(request["requestId"], json.dumps(public))

    def test_onboarding_membership_csrf_validation_and_closed_acknowledgments(self):
        progress = self.onboarding()
        step = next(s for s in progress["steps"] if s["available"])
        payload = self.progress(progress, step)
        for client in [self.sam, self.admin]:
            self.assertEqual(client.request("/api/studies/atlas/onboarding")[0], 404)
            self.assertEqual(client.request("/api/studies/atlas/onboarding", payload)[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", payload, csrf=False)[0], 400)
        for changes in [dict(stepId=None), dict(stepId="beacon-protocol"), dict(contextKey=None), dict(requestId=None)]:
            self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", dict(payload, **changes))[0], 400)
        self.assertEqual(self.alex.request("/api/studies/atlas/stage", self.mutation(stage="Closed"))[0], 200)
        try:
            current = self.onboarding()
            step = next(s for s in current["steps"] if s["available"])
            revision = self.study()["revision"]
            self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", self.progress(current, step))[0], 200)
            self.assertEqual(self.study()["revision"], revision)
        finally:
            self.assertEqual(self.alex.request("/api/studies/atlas/stage", self.mutation(stage="Active"))[0], 200)

    def test_onboarding_stale_context_replay_requires_reacknowledgment(self):
        self.assertEqual(self.alex.request("/api/studies/atlas/protocol", self.mutation(kind="item", id="protocol-1", reason="First working reference"))[0], 200)
        before = self.onboarding()
        step = next(s for s in before["steps"] if s["id"] == "guidance")
        self.assertTrue(step["available"])
        request = self.progress(before, step)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", request)[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas/protocol", self.mutation(kind="item", id="journey-guide-v2", reason="Different exact working reference"))[0], 200)
        after = self.onboarding()
        current = next(s for s in after["steps"] if s["id"] == step["id"])
        self.assertNotEqual(current["contextKey"], step["contextKey"])
        self.assertFalse(current["completed"])
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", request)[0], 409)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", self.progress(after, current))[0], 200)

    def test_onboarding_imported_conversation_delta_invalidates_completion(self):
        manifest = json.loads((api.ROOT / "fixtures/app-import.json").read_text())
        source = next(r for r in manifest["records"] if r["kind"] == "discussion")
        source["source_id"] = "orientation-delta-" + uuid.uuid4().hex
        source["references"] = []
        manifest["records"] = [source]
        self.assertEqual(self.admin.config("/api/admin/role", {"identity": "alex", "role": "Administrator"})[0], 200)
        try:
            status, report, _ = self.alex.request("/api/studies/atlas/imports/apply", self.mutation(manifest=manifest))
            self.assertEqual(status, 200)
            self.assertEqual(report["counts"]["imported"], 1)
            before = self.onboarding()
            questions = next(s for s in before["steps"] if s["id"] == "questions")
            request = self.progress(before, questions)
            self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", request)[0], 200)
            source["revision"] += 1
            source["body"] = "Changed synthetic imported conversation " + uuid.uuid4().hex
            status, report, _ = self.alex.request("/api/studies/atlas/imports/apply", self.mutation(manifest=manifest))
            self.assertEqual(status, 200)
            self.assertEqual(report["counts"]["imported"], 1)
            current = next(s for s in self.onboarding()["steps"] if s["id"] == "questions")
            self.assertNotEqual(current["contextKey"], questions["contextKey"])
            self.assertFalse(current["completed"])
            self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", request)[0], 409)
        finally:
            self.assertEqual(self.admin.config("/api/admin/role", {"identity": "alex", "role": "Researcher"})[0], 200)

    def test_z_restart_personal_and_board_history_persistence(self):
        _, board = self.board()
        _, detail, _ = self.idea(board["id"])
        progress = self.onboarding()
        step = next(s for s in progress["steps"] if s["available"])
        request = self.progress(progress, step)
        status, before, _ = self.alex.request("/api/studies/atlas/onboarding", request)
        self.assertEqual(status, 200)
        self.stop()
        self.start()
        self.alex = api.Client().login("alex")
        self.assertEqual(self.onboarding(), before)
        self.assertEqual(self.alex.request("/api/studies/atlas/onboarding", request)[1], before)
        self.assertEqual(self.get_board(board["id"]), detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
