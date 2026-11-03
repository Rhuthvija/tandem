"""Task edit sheet contract: PATCH title/time/date/duration, DELETE removes."""
import unittest
from datetime import datetime
from unittest.mock import patch

from tests.util import TC as TestClient, UserTestCase

import agent
import server


def _task(title="Gym", time="19:00"):
    return {"title": title, "date": datetime.now().strftime("%Y-%m-%d"),
            "time": time, "for_event": "To-do", "done": False}


class TaskEditTest(UserTestCase):
    def setUp(self):
        super().setUp()
        agent.mem["tasks"] = [_task()]
        agent.mem["habits"] = []
        agent.mem["habit_log"] = {}

    def test_patch_full_update(self):
        today = datetime.now().strftime("%Y-%m-%d")
        with TestClient(server.app) as client:
            r = client.patch("/tasks/0", json={"title": "Evening gym", "time": "20:00",
                                               "date": today, "duration": 45})
        self.assertEqual(r.status_code, 200)
        t = agent.mem["tasks"][0]
        self.assertEqual(t["title"], "Evening gym")
        self.assertEqual(t["time"], "20:00")
        self.assertEqual(t["date"], today)
        self.assertEqual(t["duration"], 45)
        self.assertEqual(r.json()["title"], "Evening gym")

    def test_patch_partial_title_only(self):
        with TestClient(server.app) as client:
            r = client.patch("/tasks/0", json={"title": "Morning gym"})
        self.assertEqual(r.status_code, 200)
        t = agent.mem["tasks"][0]
        self.assertEqual(t["title"], "Morning gym")
        self.assertEqual(t["time"], "19:00")  # untouched
        self.assertNotIn("duration", t)

    def test_patch_missing_task(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.patch("/tasks/99", json={"title": "x"}).status_code, 404)

    def test_patch_rejects_bad_input_without_partial_mutation(self):
        today = datetime.now().strftime("%Y-%m-%d")
        bad = [{"title": "  "}, {"time": "9pm"}, {"time": "25:00"},
               {"date": "tomorrow"}, {"date": "2026-13-01"}, {"duration": -5}]
        with TestClient(server.app) as client:
            for body in bad:
                r = client.patch("/tasks/0", json=body)
                self.assertEqual(r.status_code, 400, body)
        t = agent.mem["tasks"][0]
        self.assertEqual((t["title"], t["time"], t["date"]), ("Gym", "19:00", today))
        self.assertNotIn("duration", t)

    def test_patch_duration_omitted_keeps_null_clears(self):
        agent.mem["tasks"][0]["duration"] = 30
        with TestClient(server.app) as client:
            self.assertEqual(client.patch("/tasks/0", json={"title": "Gym!"}).status_code, 200)
        self.assertEqual(agent.mem["tasks"][0]["duration"], 30)
        with TestClient(server.app) as client:
            self.assertEqual(client.patch("/tasks/0", json={"duration": None}).status_code, 200)
        self.assertNotIn("duration", agent.mem["tasks"][0])

    def test_delete_removes_and_hides_from_today(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.delete("/tasks/0").status_code, 200)
            self.assertEqual(client.get("/today").json()["tasks"], [])
        self.assertTrue(agent.mem["tasks"][0]["removed"])

    def test_delete_missing_task(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.delete("/tasks/99").status_code, 404)

    def test_undo_sets_not_done(self):
        agent.mem["tasks"][0]["done"] = True
        with TestClient(server.app) as client:
            r = client.post("/tasks/0/undo")
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.json()["done"])
        self.assertFalse(agent.mem["tasks"][0]["done"])

    def test_undo_idempotent_and_404(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.post("/tasks/0/undo").status_code, 200)
            self.assertEqual(client.post("/tasks/99/undo").status_code, 404)
        self.assertFalse(agent.mem["tasks"][0]["done"])


if __name__ == "__main__":
    unittest.main()
