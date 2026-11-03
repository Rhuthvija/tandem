"""Tap-only onboarding contract: days saved in profile, reset wipes all."""
import copy
import unittest
from unittest.mock import patch

from tests.util import TC as TestClient, USER, UserTestCase

import agent
import server


class OnboardingTest(UserTestCase):

    def _payload(self, **over):
        body = {"name": "Test", "routine": "Usually busy in the mornings and afternoons.",
                "days": "studying", "wake": "07:00", "sleep": "23:00",
                "energy": "morning", "per_day": 3}
        body.update(over)
        return body

    def test_onboarding_saves_days(self):
        with patch.object(agent, "save_mem"), TestClient(server.app) as client:
            r = client.post("/onboarding", json=self._payload(days="working"))
            self.assertEqual(r.status_code, 200)
            profile = client.get("/profile").json()["profile"]
        self.assertEqual(profile["days"], "working")
        self.assertEqual(profile["name"], "Test")
        self.assertEqual(agent.mem["routine"], "Usually busy in the mornings and afternoons.")

    def test_onboarding_days_defaults(self):
        body = self._payload()
        del body["days"]
        with patch.object(agent, "save_mem"), TestClient(server.app) as client:
            r = client.post("/onboarding", json=body)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(client.get("/profile").json()["profile"]["days"], "other")

    def test_onboarding_marks_day_huddled(self):
        """No auto huddle on onboarding day, but the chip still works."""
        from datetime import datetime
        with patch.object(agent, "save_mem"), TestClient(server.app) as client:
            self.assertEqual(client.post("/onboarding", json=self._payload()).status_code, 200)
            self.assertTrue(client.get("/today").json()["huddled"])
        self.assertEqual(agent.mem["last_huddle"], datetime.now().strftime("%Y-%m-%d"))

    def test_reset_clears_everything(self):
        agent.mem["profile"] = {"name": "X", "days": "studying"}
        agent.mem["tasks"] = [{"title": "t"}]
        server.histories[USER] = [{"role": "user", "content": "hi"}]
        with patch.object(agent, "save_mem"), TestClient(server.app) as client:
            self.assertEqual(client.post("/reset").status_code, 200)
        for key, val in agent.EMPTY.items():
            self.assertEqual(agent.mem[key], val)
        self.assertIsNone(server.histories.get(USER))


if __name__ == "__main__":
    unittest.main()
