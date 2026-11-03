"""Instant quick-add: placeholder returns immediately, planning happens in the
background, voice transcription split out. Model calls are mocked."""
import copy
import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from tests.util import TC as TestClient, USER, UserTestCase

import agent
import server


class FakeBG:
    def __init__(self):
        self.jobs = []

    def add_task(self, func, *args):
        self.jobs.append((func, args))


class QuickAddTest(UserTestCase):
    def setUp(self):
        super().setUp()
        agent.mem["tasks"] = []

    def test_quick_add_returns_placeholder_instantly(self):
        bg = FakeBG()
        with patch.object(agent, "chat") as chat, patch.object(agent, "save_mem"):
            t0 = time.perf_counter()
            out = server.quick_add(server.QuickAddIn(text="Buy milk"), bg, USER)
            dt = time.perf_counter() - t0
        chat.assert_not_called()
        self.assertLess(dt, 1.0)
        self.assertEqual(len(bg.jobs), 1)
        func, args = bg.jobs[0]
        self.assertIs(func, server._plan_quick_add)
        self.assertEqual(len(args), 3)
        self.assertEqual(args[1:], ("Buy milk", USER))
        pending = out["pending"]
        self.assertEqual(pending["text"], "Buy milk")
        self.assertEqual(args[0], pending["id"])
        self.assertEqual(agent.mem["tasks"], [])  # raw text is not a task
        self.assertEqual(agent.mem["quick_add_pending"][0]["text"], "Buy milk")

    def test_plan_job_finishes_and_replies(self):
        agent.mem["quick_add_pending"] = [{"id": "p1", "text": "Buy milk"}]
        server.histories[USER] = [{"role": "user", "content": str(i)} for i in range(15)]
        seen = {}
        with patch.object(agent, "chat",
                          side_effect=lambda t, h: (seen.update(text=t, n=len(h)),
                                                    ("All set.", h))[1]), \
             patch.object(agent, "save_mem"):
            server._plan_quick_add("p1", "Buy milk", USER)
        self.assertEqual(seen["n"], 10)
        for phrase in ("(Quick add)", "Buy milk", "Separate",
                       "6 words", "23:00", "bedtime", "add_habit", "one short line"):
            self.assertIn(phrase, seen["text"])
        self.assertEqual(agent.mem["quick_add_pending"], [])
        self.assertEqual(agent.mem["last_reply"], "All set.")

    def test_plan_job_clears_planning_on_error(self):
        agent.mem["quick_add_pending"] = [{"id": "p1", "text": "x"}]
        with patch.object(agent, "chat", side_effect=RuntimeError("down")), \
             patch.object(agent, "save_mem"):
            server._plan_quick_add("p1", "x", USER)  # must not raise
        self.assertEqual(agent.mem["quick_add_pending"], [])
        self.assertEqual(agent.mem["last_reply"], server.QUICK_ADD_FAIL_MSG)
        self.assertEqual(agent.mem["quick_add_error"]["text"], "x")

    def test_http_quick_add_end_to_end(self):
        with patch.object(agent, "chat", return_value=("Done.", [])), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            r = client.post("/quick-add", json={"text": "Buy milk"})
            self.assertEqual(r.status_code, 200)
            self.assertIn("pending", r.json())
            # TestClient runs the background job before returning: planning done.
            data = client.get("/today").json()
        self.assertEqual(data["pending"], [])
        self.assertEqual(data["last_reply"], "Done.")
        self.assertEqual(agent.mem["last_reply"], "Done.")

    def test_today_exposes_planning_and_last_reply(self):
        agent.mem["quick_add_pending"] = [{"id": "p1", "text": "Buy milk"}]
        agent.mem["last_reply"] = "Filed under To-do."
        with TestClient(server.app) as client:
            data = client.get("/today").json()
        self.assertEqual(data["tasks"], [])
        self.assertEqual(data["pending"][0]["text"], "Buy milk")
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

    def test_startup_sweep_clears_stale_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "u.json"), "w") as f:
                json.dump({"tasks": [{"title": "stuck", "planning": True}]}, f)
            with patch.object(agent, "DATA_DIR", tmp):
                agent.clear_stale_planning()
            data = json.load(open(os.path.join(tmp, "u.json")))
        self.assertNotIn("planning", data["tasks"][0])


class QuickAddSplitTest(UserTestCase):
    """One message becomes several clean tasks (fake model response)."""

    def setUp(self):
        super().setUp()
        agent.mem["tasks"] = []
        agent.mem["profile"] = {"name": "T", "sleep": "23:00", "wake": "07:00",
                                "energy": "morning", "per_day": 3}

    def _make_pending(self, text="x"):
        agent.mem.setdefault("quick_add_pending", []).append(
            {"id": "p1", "text": text, "created_at": "2026-01-01T20:00"})
        return "p1"

    def _fake_resp(self, msg):
        import types
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    def _tool_msg(self, calls):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.tool_calls = calls
        m.content = None
        m.model_dump.return_value = {"role": "assistant", "content": None}
        return m

    def _text_msg(self, text):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.tool_calls = None
        m.content = text
        m.model_dump.return_value = {"role": "assistant", "content": text}
        return m

    def _call(self, name, args, cid="c1"):
        from unittest.mock import MagicMock
        c = MagicMock()
        c.id = cid
        c.function.name = name
        c.function.arguments = json.dumps(args)
        return c

    def test_split_one_message_into_three_tasks(self):
        today = datetime.now().strftime("%Y-%m-%d")
        pid = self._make_pending("study OS unit Concurrency and Synchronization "
                                 "for 2 hours today finish by 11, and do leetcode "
                                 "dsa stack question, and walk 10k steps")
        tasks_arg = {"tasks": [
            {"title": "OS: Concurrency & Sync", "date": today, "time": "21:00",
             "for_event": "To-do", "size": "big", "note": "2h, ends 23:00"},
            {"title": "LeetCode: stack question", "date": today, "time": "19:30",
             "for_event": "To-do", "size": "quick"},
            {"title": "Walk 10k steps", "date": today, "time": "19:45",
             "for_event": "To-do", "size": "quick"},
        ]}
        with patch.object(agent.client.chat.completions, "create", side_effect=[
                self._fake_resp(self._tool_msg([self._call("add_tasks", tasks_arg)])),
                self._fake_resp(self._text_msg("Added 3 tasks.")),
        ]):
            server._plan_quick_add(pid, "study OS...", USER)
        titles = [t["title"] for t in agent.mem["tasks"]]
        self.assertEqual(titles, ["OS: Concurrency & Sync",
                                  "LeetCode: stack question",
                                  "Walk 10k steps"])
        for t in agent.mem["tasks"]:
            self.assertLessEqual(len(t["title"].split()), 6)
            self.assertFalse(t["done"])  # left unticked for the user
        self.assertEqual(agent.mem["tasks"][0].get("note"), "2h, ends 23:00")
        self.assertEqual(agent.mem.get("quick_add_pending"), [])
        self.assertEqual(agent.mem["last_reply"], "Added 3 tasks.")

    def test_prompt_has_split_and_time_rules(self):
        p = agent.quick_add_prompt("finish by 11")
        for phrase in ("6 words", "23:00", "bedtime", "current time",
                       "Separate", "note"):
            self.assertIn(phrase, p)

    def test_tidy_truncates_title_and_clamps_past_time(self):
        today = datetime.now().strftime("%Y-%m-%d")
        agent.mem["tasks"] = [{"title": "one two three four five six seven eight",
                               "date": today, "time": "00:00",
                               "for_event": "To-do", "done": False}]
        server._tidy_quick_add_tasks(0)
        t = agent.mem["tasks"][0]
        self.assertEqual(t["title"], "one two three four five six")
        self.assertGreaterEqual(t["time"], datetime.now().strftime("%H:%M"))

    def test_plan_timeout_marks_failure(self):
        pid = self._make_pending("slow request")

        def slow(text, history):
            time.sleep(0.2)
            return ("late", history)

        with patch.object(agent, "chat", side_effect=slow):
            server._plan_quick_add(pid, "slow request", USER, timeout=0.05)
        self.assertEqual(agent.mem["quick_add_pending"], [])
        self.assertEqual(agent.mem["last_reply"], server.QUICK_ADD_FAIL_MSG)
        self.assertEqual(agent.mem["quick_add_error"]["text"], "slow request")


if __name__ == "__main__":
    unittest.main()
