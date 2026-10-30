"""Calendar: GET /calendar?month=YYYY-MM returns per-day events, tasks
(skipping removed) and day-card flags. No model calls."""
import copy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import agent
import server


class CalendarTest(unittest.TestCase):
    def setUp(self):
        self._mem = copy.deepcopy(agent.mem)
        self._history = list(server.history)
        agent.mem["events"] = [
            {"title": "Maths exam", "date": "2026-02-14", "kind": "exam"},
            {"title": "Dentist", "date": "2026-02-14", "kind": "personal"},
            {"title": "Mystery trip", "date": "unknown", "kind": "other"},
        ]
        agent.mem["tasks"] = [
            {"title": "Revise algebra", "date": "2026-02-14", "time": "19:00",
             "for_event": "Maths exam", "done": True},
            {"title": "Old draft", "date": "2026-02-14", "time": "20:00",
             "for_event": "Maths exam", "done": False, "removed": True},
            {"title": "Buy gift", "date": "2026-02-20", "time": "18:00",
             "for_event": "To-do", "done": False},
        ]
        agent.mem["cards"] = {"2026-02-14": {"title": "t", "date": "2026-02-14"}}
        server.history = []

    def tearDown(self):
        agent.mem.clear()
        agent.mem.update(self._mem)
        server.history = self._history

    def test_month_days(self):
        with TestClient(server.app) as client:
            feb = client.get("/calendar", params={"month": "2026-02"}).json()
            leap = client.get("/calendar", params={"month": "2024-02"}).json()
            octo = client.get("/calendar", params={"month": "2026-10"}).json()
        self.assertEqual(len(feb["days"]), 28)
        self.assertEqual(len(leap["days"]), 29)
        self.assertEqual(len(octo["days"]), 31)
        self.assertEqual(feb["month"], "2026-02")

    def test_day_contents(self):
        with TestClient(server.app) as client:
            days = client.get("/calendar", params={"month": "2026-02"}).json()["days"]
        day = days["2026-02-14"]
        self.assertEqual([e["title"] for e in day["events"]], ["Maths exam", "Dentist"])
        self.assertEqual([t["title"] for t in day["tasks"]], ["Revise algebra"])
        task = day["tasks"][0]
        self.assertEqual((task["id"], task["time"], task["done"]), (0, "19:00", True))
        self.assertTrue(day["has_card"])
        self.assertFalse(days["2026-02-20"]["has_card"])
        self.assertEqual(days["2026-02-20"]["tasks"][0]["id"], 2)

    def test_unknown_events_ignored(self):
        with TestClient(server.app) as client:
            days = client.get("/calendar", params={"month": "2026-02"}).json()["days"]
        seen = [e for d in days.values() for e in d["events"]]
        self.assertEqual(len(seen), 2)
        self.assertNotIn("unknown", [e["date"] for e in seen])

    def test_bad_month_rejected(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.get("/calendar", params={"month": "nope"}).status_code, 400)
            self.assertEqual(client.get("/calendar", params={"month": "2026-13"}).status_code, 400)
            self.assertEqual(client.get("/calendar").status_code, 422)


if __name__ == "__main__":
    unittest.main()
