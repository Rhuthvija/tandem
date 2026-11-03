"""Shared multi-user test harness: header-authenticated client plus a fake
per-user store, so requests and direct agent.mem access share live state."""
import copy
import unittest
from unittest.mock import patch

import agent
import server

USER = "00000000-0000-0000-0000-000000000001"
USER2 = "00000000-0000-0000-0000-000000000002"


def TC(*a, **k):
    from fastapi.testclient import TestClient
    h = dict(k.pop("headers", None) or {})
    h.setdefault("X-User-Id", USER)
    k["headers"] = h
    return TestClient(*a, **k)


class UserTestCase(unittest.TestCase):
    def setUp(self):
        self._db = {}
        mem = copy.deepcopy(agent.EMPTY)
        self._db[USER] = mem
        agent.bind_user(USER, mem)
        self._lp = patch.object(agent, "load_user", self._fake_load)
        self._sp = patch.object(agent, "save_mem", lambda: None)
        self._lp.start()
        self._sp.start()
        self._histories = server.histories
        server.histories = {}

    def tearDown(self):
        agent.unbind_user()
        self._lp.stop()
        self._sp.stop()
        server.histories = self._histories

    def _fake_load(self, uid):
        return self._db.setdefault(uid, copy.deepcopy(agent.EMPTY))
