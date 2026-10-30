"""Prep planning: rename/remove tools, removed tasks hidden everywhere,
and the ask-first prompt rules. Model calls are mocked."""
import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

import agent
import server


def _task(title, done=False):
    return {"title": title, "date": datetime.now().strftime("%Y-%m-%d"),
            "time": "19:00", "for_event": "Exam", "done": done}


class PrepTest(unittest.TestCase):
    def setUp(self):
        self._mem = copy.deepcopy(agent.mem)
        self._history = list(server.history)
        agent.mem["tasks"] = [_task("Old name"), _task("Gone")]
        agent.mem["tasks"][1]["removed"] = True
        agent.mem["habits"] = []
        agent.mem["habit_log"] = {}
        server.history = []

    def tearDown(self):
        agent.mem.clear()
        agent.mem.update(self._mem)
        server.history = self._history

    def test_update_task_renames(self):
        self.assertEqual(agent.update_task(0, "Specific topic"), "✏️ Renamed to Specific topic")
        self.assertEqual(agent.mem["tasks"][0]["title"], "Specific topic")
        self.assertEqual(agent.update_task(99, "x"), "No such task")
        self.assertIn("update_task", agent.FUNCS)
        schema = next(t for t in agent.TOOLS if t["function"]["name"] == "update_task")
        self.assertEqual(schema["function"]["parameters"]["required"], ["task_id", "title"])

    def test_remove_task_marks_removed_ids_stable(self):
        self.assertEqual(agent.remove_task(0), "🗑️ Removed Old name")
        self.assertTrue(agent.mem["tasks"][0]["removed"])
        self.assertEqual(len(agent.mem["tasks"]), 2)
        self.assertEqual(agent.mem["tasks"][1]["title"], "Gone")
        self.assertEqual(agent.remove_task(99), "No such task")
        self.assertIn("remove_task", agent.FUNCS)
        schema = next(t for t in agent.TOOLS if t["function"]["name"] == "remove_task")
        self.assertEqual(schema["function"]["parameters"]["required"], ["task_id"])

    def test_today_hides_removed(self):
        with TestClient(server.app) as client:
            data = client.get("/today").json()
        self.assertEqual([t["title"] for t in data["tasks"]], ["Old name"])
        self.assertEqual(data["total"], 1)

    def test_system_prompt_hides_removed(self):
        prompt = agent.system_prompt()
        self.assertIn("Old name", prompt)
        self.assertNotIn("Gone", prompt)

    def test_system_prompt_prep_rules(self):
        prompt = agent.system_prompt()
        for phrase in ("do NOT add prep tasks yet",
                       "Send me the topics or syllabus",
                       "revision slot",
                       "update_task",
                       "remove_task",
                       "just plan it",
                       "share topics anytime",
                       "birthday"):
            self.assertIn(phrase, prompt)

    def test_week_record_ignores_removed(self):
        week = server.week_record()
        self.assertEqual((week["done"], week["total"]), (0, 1))

    def test_reflect_ignores_removed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        card = {"title": "t", "lesson": "l", "note": "n", "scene": "s"}
        with patch.object(agent, "make_day_card", return_value=dict(card)), \
             patch.object(agent, "paint_card", return_value=False), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            r = client.post("/reflect", json={"mood": "okay", "carry_over": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 1)
        self.assertNotEqual(agent.mem["tasks"][0]["date"], today)  # active carried over
        self.assertEqual(agent.mem["tasks"][1]["date"], today)  # removed stays put


if __name__ == "__main__":
    unittest.main()
