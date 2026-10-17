"""Isolated regression tests for S1 userstorage authorization and S2 save paths."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import tf_server as srv  # noqa: E402
import tflocal_accounts as acct  # noqa: E402


class SecurityStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        for name, rel in (
            ("ACCOUNTS", "accounts.json"),
            ("SESSIONS", "sessions.json"),
            ("DEVICES", "devices.json"),
            ("REMEMBER", "remember.json"),
            ("BINDINGS", "bindings.json"),
            ("GHOST_DIR", "ghosts"),
        ):
            self.patches.enter_context(patch.object(acct, name, str(root / rel)))
        self.patches.enter_context(patch.object(acct, "GHOST_STORE", str(root / "ghosts" / "store")))
        self.patches.enter_context(patch.object(acct, "GHOST_INDEX", str(root / "ghosts" / "index.json")))
        self.patches.enter_context(patch.object(acct, "GHOST_REPLAYS", str(root / "ghosts" / "replays.json")))

    @staticmethod
    def auth(username, password):
        token = base64.b64encode((username + ":" + password).encode()).decode()
        return {"Authorization": "Basic " + token}

    @staticmethod
    def call(method, path, body=b"", headers=None):
        return srv.h_userstorage(method, path, "", body, headers or {})

    def test_owner_can_mutate_but_non_owner_and_invalid_token_cannot(self):
        victim, err = acct.register_account("victim", "victim-secret")
        self.assertIsNone(err)
        owner_headers = self.auth("victim", "victim-secret")
        status, _, result = self.call(
            "POST", "/public/userstorage/v2/content/ghost",
            json.dumps({"metadata": {"track_id": 123}}).encode(), owner_headers)
        self.assertEqual(status, 200)
        cid = result["contentId"]
        status, _, _ = self.call(
            "PUT", "/public/userstorage/v2/content/ghost/%d/payload" % cid,
            b"owner-payload", owner_headers)
        self.assertEqual(status, 200)

        other, err = acct.register_account("other", "other-secret")
        self.assertIsNone(err)
        status, _, _ = self.call(
            "PUT", "/public/userstorage/v2/content/ghost/%d/payload" % cid,
            b"other-payload", self.auth("other", "other-secret"))
        self.assertIn(status, (401, 403))
        self.assertEqual(acct.ghost_payload(cid), b"owner-payload")

        acct.bind_client(victim, client_ip="bound-client")
        invalid = {"Authorization": "Bearer definitely-not-a-ticket",
                   "X-TF-Client": "bound-client"}
        status, _, _ = self.call(
            "PUT", "/public/userstorage/v2/content/ghost/%d/payload" % cid,
            b"invalid-payload", invalid)
        self.assertIn(status, (401, 403))
        self.assertEqual(acct.ghost_payload(cid), b"owner-payload")

        status, _, _ = self.call(
            "DELETE", "/public/userstorage/v2/content/ghost/%d" % cid,
            b"", self.auth("other", "other-secret"))
        self.assertIn(status, (401, 403))
        self.assertIsNotNone(acct.ghost_payload(cid))

    def test_anonymous_may_create_but_cannot_modify_existing_content(self):
        status, _, result = self.call(
            "POST", "/public/userstorage/v2/content/ghost",
            json.dumps({"metadata": {"track_id": 124}}).encode(), {})
        self.assertEqual(status, 200)
        cid = result["contentId"]
        status, _, _ = self.call(
            "PUT", "/public/userstorage/v2/content/ghost/%d/payload" % cid,
            b"anonymous-payload", {})
        self.assertIn(status, (401, 403))
        self.assertIsNone(acct.ghost_payload(cid))


class SavePathSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.save_dir = Path(self.tmp.name) / "save"
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(acct, "SAVE_DIR", str(self.save_dir)))
        self.patches.enter_context(patch.object(acct, "ADMIN", str(Path(self.tmp.name) / "admin.json")))

    @staticmethod
    def doc(version):
        return {"version": version, "content": {"items2": [0, 1]}}

    def test_rollback_and_restore_reject_escape_components(self):
        profile = "11111111-1111-1111-1111-111111111111"
        history = self.save_dir / profile / "history"
        history.mkdir(parents=True)
        acct._store(str(self.save_dir / profile / "latest.json"), self.doc(7))
        acct._store(str(history / "1700000000.json"), self.doc(3))
        outside = Path(self.tmp.name) / "outside.json"
        acct._store(str(outside), self.doc(99))

        self.assertEqual(acct.rollback_save(profile, "1700000000")[1], None)
        self.assertEqual(acct.load_progress(profile)["version"], 3)
        before = outside.read_text(encoding="utf-8")
        for bad_profile, bad_ts in (
            ("../outside", "1700000000"),
            (profile, "../../outside"),
            (profile, "/tmp/outside"),
        ):
            self.assertIn(acct.rollback_save(bad_profile, bad_ts)[1], ("bad-profile", "bad-ts", "not-found"))
            self.assertEqual(outside.read_text(encoding="utf-8"), before)
        self.assertIsNone(acct.restore_save(profile, "../../outside"))
        self.assertEqual(outside.read_text(encoding="utf-8"), before)

    def test_admin_rollback_route_rejects_traversal(self):
        h = object.__new__(srv.Handler)
        h.command = "POST"
        h.headers = {"Content-Type": "application/json"}
        h.client_address = ("127.0.0.1", 12345)
        sent = []

        def send(_self, status, headers, raw):
            sent.append((status, headers, raw))

        with patch.object(srv.Handler, "_send", send), \
             patch.object(srv.Handler, "_admin_token", return_value="admin-token"), \
             patch.object(acct, "admin_by_token", return_value={"username": "admin"}):
            self.assertTrue(h._introspect(
                "/__api/admin/rollback", "",
                json.dumps({"profile": "../outside", "ts": "1700000000"}).encode()))
        self.assertEqual(sent[0][0], 400)
        self.assertIn("bad-profile", sent[0][2].decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
