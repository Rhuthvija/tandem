"""Multi-user deployment: header auth, per-user isolation, file storage,
per-user card images, and deploy files. Model calls are mocked."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient as RawClient

import agent
import server
from tests.util import TC, USER, USER2, UserTestCase

HDR2 = {"X-User-Id": USER2}


class AuthTest(UserTestCase):
    def test_missing_header_rejected(self):
        with RawClient(server.app) as client:
            self.assertEqual(client.get("/today").status_code, 400)
            self.assertEqual(client.post("/chat", json={"message": "hi"}).status_code, 400)

    def test_bad_uuid_rejected(self):
        with RawClient(server.app, headers={"X-User-Id": "nope"}) as client:
            self.assertEqual(client.get("/today").status_code, 400)

    def test_home_and_static_open_without_header(self):
        with RawClient(server.app) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/static/mascot/otter_base.png").status_code, 200)


class IsolationTest(UserTestCase):
    def test_memories_isolated(self):
        agent.mem["tasks"] = [{"title": "Mine", "date": "2026-10-30", "time": "19:00",
                               "for_event": "To-do", "done": False}]
        with TC(server.app, headers=HDR2) as client:
            other = client.get("/today").json()
        with TC(server.app) as client:
            mine = client.get("/today").json()
        self.assertEqual(other["tasks"], [])
        self.assertEqual([t["title"] for t in mine["tasks"]], ["Mine"])

    def test_history_per_user(self):
        with patch.object(agent, "chat", side_effect=lambda t, h: ("r", h + [{"role": "u"}])), \
             TC(server.app) as client:
            client.post("/chat", json={"message": "hi"})
        self.assertEqual(len(server.histories[USER]), 1)
        self.assertIsNone(server.histories.get(USER2))

    def test_background_job_uses_explicit_user(self):
        mem2 = copy.deepcopy(agent.EMPTY)
        mem2["tasks"] = [{"title": "x", "date": "2026-10-30", "for_event": "To-do",
                          "done": False, "planning": True}]
        self._db[USER2] = mem2
        with patch.object(agent, "chat", return_value=("Done.", [])), \
             patch.object(agent, "save_mem"):
            server._plan_quick_add(0, "x", USER2)
        self.assertNotIn("planning", self._db[USER2]["tasks"][0])
        self.assertEqual(self._db[USER2]["last_reply"], "Done.")
        self.assertIsNone(self._db[USER]["last_reply"])

    def test_paint_job_uses_explicit_user(self):
        d = "2026-10-30"
        mem2 = copy.deepcopy(agent.EMPTY)
        mem2["cards"] = {d: {"title": "t", "image": None, "image_pending": True}}
        self._db[USER2] = mem2
        with patch.object(agent, "paint_card", return_value=b"PNG"), \
             patch.object(agent, "save_card_image") as save_img, \
             patch.object(agent, "save_mem"):
            server._paint_and_save(d, "scene", USER2)
        save_img.assert_called_once_with(USER2, d, b"PNG")
        card = self._db[USER2]["cards"][d]
        self.assertEqual(card["image"], f"/cards/{d}/image?user_id={USER2}")
        self.assertFalse(card["image_pending"])
        self.assertNotIn(d, self._db[USER]["cards"])


class CardImageHttpTest(UserTestCase):
    def test_image_served_per_user(self):
        d = "2026-10-30"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(agent, "DATA_DIR", tmp):
            os.makedirs(os.path.join(tmp, "cards", USER))
            with open(os.path.join(tmp, "cards", USER, f"{d}.png"), "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\nxxx")
            with TC(server.app) as client:
                r = client.get(f"/cards/{d}/image")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.content, b"\x89PNG\r\n\x1a\nxxx")
                self.assertIn("image/png", r.headers["content-type"])
            with TC(server.app, headers=HDR2) as client:
                self.assertEqual(client.get(f"/cards/{d}/image").status_code, 404)


class FileStoreTest(unittest.TestCase):
    """Real file backend against a temp dir (no fake store here)."""

    def test_roundtrip(self):
        mem = copy.deepcopy(agent.EMPTY)
        mem["tasks"] = [{"title": "t"}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(agent, "DATA_DIR", tmp):
            agent.save_user("u1", mem)
            self.assertTrue(os.path.exists(os.path.join(tmp, "u1.json")))
            loaded = agent.load_user("u1")
        self.assertEqual(loaded["tasks"], [{"title": "t"}])

    def test_missing_user_gets_empty(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(agent, "DATA_DIR", tmp):
            loaded = agent.load_user("nobody")
        self.assertEqual(loaded, agent.EMPTY)

    def test_sweep_clears_stale_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "u.json"), "w") as f:
                json.dump({"tasks": [{"title": "stuck", "planning": True}]}, f)
            with patch.object(agent, "DATA_DIR", tmp):
                agent.clear_stale_planning()
            data = json.load(open(os.path.join(tmp, "u.json")))
        self.assertNotIn("planning", data["tasks"][0])


class DeployFilesTest(unittest.TestCase):
    def test_deploy_files(self):
        req = open("requirements.txt").read()
        for pkg in ("fastapi==", "uvicorn==", "openai==", "psycopg"):
            self.assertIn(pkg, req)
        render = open("render.yaml").read()
        self.assertIn("uvicorn server:app --host 0.0.0.0 --port $PORT", render)
        self.assertIn("MODEL_API_KEY", render)
        self.assertIn("DATABASE_URL", render)
        self.assertTrue(os.path.exists("DEPLOY.md"))
        self.assertIn("data/", open(".gitignore").read())


if __name__ == "__main__":
    unittest.main()
