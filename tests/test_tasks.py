"""Structured task regression checks, synthetic HTTP-only data on loopback.

Run separately from other HTTP suites: DOTNET=/path/to/dotnet python3 tests/test_tasks.py
"""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
import uuid
import test_api as api


class Tasks(unittest.TestCase):
    setUpClass = classmethod(api.Integration.setUpClass.__func__)
    tearDownClass = classmethod(api.Integration.tearDownClass.__func__)
    start = classmethod(api.Integration.start.__func__)
    stop = classmethod(api.Integration.stop.__func__)
    setUp = api.Integration.setUp
    study = api.Integration.study
    item = api.Integration.item
    def payload(self, **updates):
        value = dict(title="Synthetic review", body="Review protocol and record outcome", assignee="alex",
                     dueDate="2027-03-14", status="Open", links=["protocol-1", "question-1"],
                     expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        value.update(updates)
        return value

    def create(self, **updates):
        status, state, _ = self.alex.request("/api/studies/atlas/tasks", self.payload(**updates))
        self.assertEqual(status, 200)
        return state, state["items"][-1]

    def test_task_assignees_access_csrf(self):
        self.assertEqual([x["id"] for x in self.alex.request("/api/studies/atlas/assignees")[1]], ["alex"])
        for client in (self.sam, self.admin):
            self.assertEqual(client.request("/api/studies/atlas/assignees")[0], 404)
            self.assertEqual(client.request("/api/studies/atlas/tasks", self.payload())[0], 404)
        state, item = self.create()
        path = "/api/studies/atlas/tasks/" + item["id"]
        self.assertEqual(self.sam.request(path, self.payload())[0], 404)
        for path in ("/api/studies/atlas/tasks", path):
            self.assertEqual(self.alex.request(path, self.payload(), csrf=False)[0], 400)
        self.assertEqual(self.alex.request("/api/studies/beacon/tasks/" + item["id"], self.payload())[0], 404)

    def test_task_validation_links_and_assignment(self):
        for update in (dict(title=None), dict(title=" "), dict(title="x" * 181), dict(body=None),
                       dict(body="x" * 20001), dict(status=None), dict(status="Approved"),
                       dict(assignee="sam"), dict(assignee="admin"), dict(assignee="missing"),
                       dict(dueDate="2027-02-29"), dict(dueDate="2027-3-1"), dict(dueDate="2101-01-01"),
                       dict(links=["beacon-protocol"]), dict(links=["missing"]), dict(links=[None]),
                       dict(links=["protocol-1", "protocol-1"]), dict(links=["task-1"]), dict(requestId="bad")):
            with self.subTest(update=update):
                self.assertEqual(self.alex.request("/api/studies/atlas/tasks", self.payload(**update))[0], 400)
        _, item = self.create(assignee=None, dueDate=None, links=[])
        self.assertIsNone(item["task"]["assignee"])
        self.assertEqual(item["task"]["links"], [])
        self.assertEqual(self.alex.request("/api/studies/atlas/tasks/missing", self.payload())[0], 404)
        self.assertEqual(self.alex.request("/api/studies/atlas/tasks/protocol-1", self.payload())[0], 404)

    def test_task_history_conflict_replay_restart(self):
        original = self.payload()
        status, first, _ = self.alex.request("/api/studies/atlas/tasks", original)
        self.assertEqual(status, 200)
        item = first["items"][-1]
        self.assertEqual(self.alex.request("/api/studies/atlas/tasks", original)[1], first)
        self.assertEqual(self.alex.request("/api/studies/atlas/tasks", dict(original, body="Changed retry"))[0], 409)
        path = "/api/studies/atlas/tasks/" + item["id"]
        stale = self.payload(expectedRevision=original["expectedRevision"])
        self.assertEqual(self.alex.request(path, stale)[0], 409)
        update = self.payload(status="Done", body="Outcome captured", links=["protocol-1"])
        status, after, _ = self.alex.request(path, update)
        self.assertEqual(status, 200)
        revised = next(x for x in after["items"] if x["id"] == item["id"])
        self.assertEqual(revised["version"], 2)
        self.assertEqual(revised["task"]["status"], "Done")
        old = revised["task"]["history"][0]
        self.assertEqual(old["body"], original["body"])
        self.assertEqual(old["links"], original["links"])
        self.assertEqual(old["actor"], "alex")
        self.stop()
        self.start()
        self.alex = api.Client().login("alex")
        self.assertEqual(self.study(), after)
        self.assertEqual(self.alex.request(path, update)[1], after)

    def test_task_deleted_history_and_evidence(self):
        marker = "RemovedTaskBody" + uuid.uuid4().hex
        _, item = self.create(body=marker)
        path = "/api/studies/atlas/tasks/" + item["id"]
        self.assertEqual(self.alex.request(path, self.payload(body="Edited description"))[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas/items/" + item["id"] + "/delete",
                         dict(expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4())))[0], 200)
        self.assertNotIn(marker, json.dumps(self.study()))
        self.assertNotIn(marker, json.dumps(self.alex.request("/api/studies")[1]))
        self.assertEqual(self.alex.request(path, self.payload())[0], 404)
        status, st, _ = self.alex.request("/api/studies/atlas/items", self.item(kind="discussion"))
        self.assertEqual(status, 200)
        evidence = st["items"][-1]["id"]
        self.assertEqual(self.alex.request("/api/studies/atlas/items/" + evidence + "/delete",
                         dict(expectedRevision=st["revision"], requestId=str(uuid.uuid4())))[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas/tasks", self.payload(links=[evidence]))[0], 400)

    def test_task_concurrent_update(self):
        _, item = self.create()
        path = "/api/studies/atlas/tasks/" + item["id"]
        before = self.study()
        first = self.payload(body="First synthetic editor", expectedRevision=before["revision"])
        second = self.payload(body="Second synthetic editor", expectedRevision=before["revision"])
        other = api.Client().login("alex")
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(client.request, path, value) for client, value in ((self.alex, first), (other, second))]
            outcomes = [future.result() for future in calls]
        self.assertEqual(sorted(outcome[0] for outcome in outcomes), [200, 409])
        after = self.study()
        self.assertEqual(after["revision"], before["revision"] + 1)
        revised = next(x for x in after["items"] if x["id"] == item["id"])
        self.assertEqual(len(revised["task"]["history"]), 1)

    def test_task_lifecycle(self):
        _, item = self.create()
        stage = dict(stage="Closed", expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request("/api/studies/atlas/stage", stage)[0], 200)
        for path in ("/api/studies/atlas/tasks", "/api/studies/atlas/tasks/" + item["id"]):
            self.assertEqual(self.alex.request(path, self.payload())[0], 409)
        stage = dict(stage="Active", expectedRevision=self.study()["revision"], requestId=str(uuid.uuid4()))
        self.assertEqual(self.alex.request("/api/studies/atlas/stage", stage)[0], 200)
        self.assertEqual(self.alex.request("/api/studies/atlas/tasks/" + item["id"], self.payload(status="In progress"))[0], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
