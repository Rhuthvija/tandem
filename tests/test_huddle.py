"""Morning Huddle contract: POST /huddle pins energy into the agent instruction,
marks the day huddled, and /today reports it. Model calls are mocked."""
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

import agent
import server


class HuddleTest(unittest.TestCase):
    def setUp(self):
        self._mem = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                      for k, v in agent.mem.items()}
        self._history = list(server.history)
        server.history = []

    def tearDown(self):
        agent.mem.clear()
        agent.mem.update(self._mem)
        server.history = self._history

    def test_huddle_posts_instruction_with_energy(self):
        seen = {}

        def fake_chat(text, history):
            seen["text"] = text
            seen["history"] = history
            return "Warm summary here.", history + [{"role": "user", "content": text}]

        with patch.object(agent, "chat", side_effect=fake_chat), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            r = client.post("/huddle", json={"energy": "high"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"reply": "Warm summary here."})
        for phrase in ("Morning huddle", "Energy: high", "big-task limit",
                       "go lighter if energy is low",
                       "don't move it without asking",
                       "warm 2-3 sentence summary"):
            self.assertIn(phrase, seen["text"])

    def test_huddle_marks_day_and_today_reports_it(self):
        agent.mem["last_huddle"] = None
        with patch.object(agent, "chat", return_value=("ok", [])), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            self.assertFalse(client.get("/today").json()["huddled"])
            self.assertEqual(client.post("/huddle", json={"energy": "okay"}).status_code, 200)
            self.assertTrue(client.get("/today").json()["huddled"])
        self.assertEqual(agent.mem["last_huddle"], datetime.now().strftime("%Y-%m-%d"))
        # yesterday's huddle doesn't count
        agent.mem["last_huddle"] = (datetime.now().date() - timedelta(days=1)).isoformat()
        with TestClient(server.app) as client:
            self.assertFalse(client.get("/today").json()["huddled"])

    def test_huddle_trims_long_history(self):
        server.history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
                          for i in range(15)]
        seen = {}
        with patch.object(agent, "chat",
                          side_effect=lambda t, h: (seen.setdefault("n", len(h)), "ok", h)[1:]), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            client.post("/huddle", json={"energy": "low"})
        self.assertEqual(seen["n"], 10)

    def test_huddle_needs_energy(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.post("/huddle", json={}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
