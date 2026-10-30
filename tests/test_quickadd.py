"""Instant quick-add: placeholder returns immediately, planning happens in the
background, voice transcription split out. Model calls are mocked."""
import copy
import io
import json
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

import agent
import server


class FakeBG:
    def __init__(self):
        self.jobs = []

    def add_task(self, func, *args):
        self.jobs.append((func, args))


class QuickAddTest(unittest.TestCase):
    def setUp(self):
        self._mem = copy.deepcopy(agent.mem)
        self._history = list(server.history)
        agent.mem["tasks"] = []
        server.history = []

    def tearDown(self):
        agent.mem.clear()
        agent.mem.update(self._mem)
        server.history = self._history

    def test_quick_add_returns_placeholder_instantly(self):
        bg = FakeBG()
        with patch.object(agent, "chat") as chat, patch.object(agent, "save_mem"):
            t0 = time.perf_counter()
            out = server.quick_add(server.QuickAddIn(text="Buy milk"), bg)
            dt = time.perf_counter() - t0
        chat.assert_not_called()
        self.assertLess(dt, 1.0)
        self.assertEqual(len(bg.jobs), 1)
        func, args = bg.jobs[0]
        self.assertIs(func, server._plan_quick_add)
        self.assertEqual(args, (0, "Buy milk"))
        task = out["task"]
        self.assertEqual(task["title"], "Buy milk")
        self.assertEqual(task["date"], datetime.now().strftime("%Y-%m-%d"))
        self.assertTrue(task["planning"])
        self.assertNotIn("time", task)
        self.assertEqual(agent.mem["tasks"][0]["title"], "Buy milk")

    def test_plan_job_finishes_and_replies(self):
        agent.mem["tasks"] = [{"title": "Buy milk", "date": "2026-10-30",
                               "for_event": "To-do", "done": False, "planning": True}]
        server.history = [{"role": "user", "content": str(i)} for i in range(15)]
        seen = {}
        with patch.object(agent, "chat",
                          side_effect=lambda t, h: (seen.update(text=t, n=len(h)),
                                                    ("All set.", h))[1]), \
             patch.object(agent, "save_mem"):
            server._plan_quick_add(0, "Buy milk")
        self.assertEqual(seen["n"], 10)
        for phrase in ("(Quick add, placeholder task id 0)", "Buy milk",
                       "update_task/move_task", "remove_task", "one short line"):
            self.assertIn(phrase, seen["text"])
        self.assertNotIn("planning", agent.mem["tasks"][0])
        self.assertEqual(agent.mem["last_reply"], "All set.")

    def test_plan_job_clears_planning_on_error(self):
        agent.mem["tasks"] = [{"title": "x", "date": "2026-10-30",
                               "for_event": "To-do", "done": False, "planning": True}]
        with patch.object(agent, "chat", side_effect=RuntimeError("down")), \
             patch.object(agent, "save_mem"):
            server._plan_quick_add(0, "x")  # must not raise
        self.assertNotIn("planning", agent.mem["tasks"][0])
        self.assertTrue(agent.mem["last_reply"])

    def test_http_quick_add_end_to_end(self):
        with patch.object(agent, "chat", return_value=("Done.", [])), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            r = client.post("/quick-add", json={"text": "Buy milk"})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["task"]["planning"])
            # TestClient runs the background job before returning: planning done.
            data = client.get("/today").json()
        self.assertNotIn("planning", data["tasks"][0])
        self.assertEqual(data["last_reply"], "Done.")
        self.assertEqual(agent.mem["last_reply"], "Done.")

    def test_today_exposes_planning_and_last_reply(self):
        agent.mem["tasks"] = [{"title": "x", "date": datetime.now().strftime("%Y-%m-%d"),
                               "for_event": "To-do", "done": False, "planning": True}]
        agent.mem["last_reply"] = "Filed under To-do."
        with TestClient(server.app) as client:
            data = client.get("/today").json()
        self.assertTrue(data["tasks"][0]["planning"])
        self.assertEqual(data["last_reply"], "Filed under To-do.")

    def test_quick_add_needs_text(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.post("/quick-add", json={}).status_code, 422)

    def test_transcribe_and_voice_contract(self):
        class Resp:
            status_code = 200
            text = "buy milk tomorrow"

        def fake_post(*a, **k):
            return Resp()

        def files():
            return {"audio": ("speech.wav", io.BytesIO(b"RIFFxxxx"), "audio/wav")}

        with patch.object(server.requests, "post", side_effect=fake_post), \
             patch.object(agent, "chat", return_value=("Heard.", [])), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            t = client.post("/transcribe", files=files())
            self.assertEqual(t.status_code, 200)
            self.assertEqual(t.json(), {"heard": "buy milk tomorrow"})
            v = client.post("/voice", files=files())
            self.assertEqual(v.status_code, 200)
            self.assertEqual(set(v.json()), {"heard", "reply"})

    def test_load_mem_strips_stale_planning(self):
        mem = dict(copy.deepcopy(agent.EMPTY))
        mem["tasks"] = [{"title": "stuck", "planning": True, "done": False,
                         "date": "2026-10-30", "for_event": "To-do"}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(mem, f)
        with patch.object(agent, "MEMORY", f.name):
            loaded = agent.load_mem()
        self.assertNotIn("planning", loaded["tasks"][0])


if __name__ == "__main__":
    unittest.main()
