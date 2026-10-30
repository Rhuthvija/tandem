"""Day-card fixes: re-reflect replaces card+image, failed art settles pending,
mascot edit mode with generation fallback. Model calls are mocked."""
import base64
import copy
import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import agent
import server

FAKE_B64 = base64.b64encode(b"PNGDATA").decode()


def _art_result():
    return SimpleNamespace(data=[SimpleNamespace(b64_json=FAKE_B64, url=None)])


class DayCardTest(unittest.TestCase):
    def setUp(self):
        self._mem = copy.deepcopy(agent.mem)
        self._history = list(server.history)
        server.history = []

    def tearDown(self):
        agent.mem.clear()
        agent.mem.update(self._mem)
        server.history = self._history

    def test_rereflect_replaces_card_and_image(self):
        d = datetime.now().strftime("%Y-%m-%d")
        agent.mem["tasks"] = [
            {"title": "Done thing", "date": d, "time": "10:00", "for_event": "To-do", "done": True},
            {"title": "Todo thing", "date": d, "time": "11:00", "for_event": "To-do", "done": False},
        ]
        agent.mem["habits"] = []
        agent.mem["habit_log"] = {}
        agent.mem["cards"] = {d: {"title": "Old", "date": d, "done": 0, "total": 0,
                                  "image": f"/static/cards/{d}.png"}}
        with patch.object(agent, "make_day_card",
                          return_value={"title": "New", "lesson": "l", "note": "n", "scene": "s"}), \
             patch.object(agent, "paint_card", return_value=True) as paint, \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            r = client.post("/reflect", json={"mood": "okay", "carry_over": False})
        self.assertEqual(r.status_code, 200)
        paint.assert_called_once()
        card = agent.mem["cards"][d]
        self.assertEqual(card["title"], "New")
        self.assertEqual((card["done"], card["total"]), (1, 2))
        self.assertEqual(card["image"], f"/static/cards/{d}.png")
        self.assertFalse(card["image_pending"])

    def test_failed_art_clears_pending(self):
        d = datetime.now().strftime("%Y-%m-%d")
        agent.mem["tasks"] = []
        agent.mem["habits"] = []
        agent.mem["habit_log"] = {}
        with patch.object(agent, "make_day_card",
                          return_value={"title": "t", "lesson": "l", "note": "n", "scene": "s"}), \
             patch.object(agent, "paint_card", return_value=False), \
             patch.object(agent, "save_mem"), \
             TestClient(server.app) as client:
            client.post("/reflect", json={"mood": "okay", "carry_over": False})
        card = agent.mem["cards"][d]
        self.assertIsNone(card["image"])
        self.assertFalse(card["image_pending"])

    def test_paint_card_uses_mascot_edit(self):
        out = os.path.join(tempfile.mkdtemp(), "card.png")
        with patch.object(agent.client.images, "edit", return_value=_art_result()) as edit, \
             patch.object(agent.client.images, "generate") as gen:
            self.assertTrue(agent.paint_card("a quiet evening", out))
        gen.assert_not_called()
        self.assertEqual(edit.call_count, 1)
        _, kwargs = edit.call_args
        self.assertEqual(kwargs["model"], "muse-image-1.0")
        self.assertIn("reference", kwargs["prompt"])
        name, blob, mime = kwargs["image"]
        self.assertEqual((name, mime), ("otter_base.webp", "image/webp"))
        self.assertTrue(blob.startswith(b"RIFF"))
        with open(out, "rb") as f:
            self.assertEqual(f.read(), b"PNGDATA")

    def test_paint_card_falls_back_to_generate(self):
        out = os.path.join(tempfile.mkdtemp(), "card.png")
        with patch.object(agent.client.images, "edit", side_effect=RuntimeError("nope")), \
             patch.object(agent.client.images, "generate", return_value=_art_result()) as gen:
            self.assertTrue(agent.paint_card("a quiet evening", out))
        _, kwargs = gen.call_args
        for word in ("purple", "otter", "cream", "orange scarf"):
            self.assertIn(word, kwargs["prompt"])
        with open(out, "rb") as f:
            self.assertEqual(f.read(), b"PNGDATA")

    def test_paint_card_both_fail(self):
        out = os.path.join(tempfile.mkdtemp(), "card.png")
        with patch.object(agent.client.images, "edit", side_effect=RuntimeError("nope")), \
             patch.object(agent.client.images, "generate", side_effect=RuntimeError("nope")):
            self.assertFalse(agent.paint_card("a quiet evening", out))


if __name__ == "__main__":
    unittest.main()
