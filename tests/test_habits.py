"""Habit sheet: fast suggestion endpoint that skips existing habits."""
import copy
import unittest

from tests.util import TC as TestClient, UserTestCase

import agent
import server


class HabitSuggestionsTest(UserTestCase):

    def test_returns_suggestions(self):
        agent.mem["habits"] = []
        with TestClient(server.app) as client:
            r = client.get("/habit-suggestions")
        self.assertEqual(r.status_code, 200)
        sugs = r.json()["suggestions"]
        self.assertGreaterEqual(len(sugs), 5)
        self.assertTrue(all(isinstance(s, str) and s.strip() for s in sugs))

    def test_skips_existing_habits(self):
        agent.mem["habits"] = [{"title": "Read 10 pages", "minutes": 10, "time": "21:00"}]
        with TestClient(server.app) as client:
            sugs = client.get("/habit-suggestions").json()["suggestions"]
        self.assertNotIn("📖 Read 10 pages", sugs)
        self.assertTrue(all("read" not in s.lower() for s in sugs))

    def test_falls_back_to_full_list_when_all_match(self):
        agent.mem["habits"] = [{"title": "e", "minutes": 1, "time": "21:00"}]
        with TestClient(server.app) as client:
            sugs = client.get("/habit-suggestions").json()["suggestions"]
        self.assertEqual(len(sugs), len(server.HABIT_SUGGESTIONS))


if __name__ == "__main__":
    unittest.main()
