"""Weekly find -> stats -> payload regressions over the production HTTP routes.

All fixtures and request logs live in TemporaryDirectory; no running service is used.
"""
import contextlib
import copy
from http.client import HTTPConnection
from http.server import HTTPServer
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import tf_server as srv

PLAYER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
BASE = "/public/liveevents/v1/weekly_track_system/"


def ghost_blob():
    raw = struct.pack("<III", 0, 25000, 10) + bytes(20)
    return struct.pack("<IIII", 3, 0, len(raw), 0) + zlib.compress(raw)


class WeeklyOpponentChainTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.config = copy.deepcopy(srv._TF_CONFIG_DEFAULTS)
        self.config["weekly"].update(track_id=1258, fake_field=0)
        for module in (srv, srv.acct):
            for name, value in list(vars(module).items()):
                if isinstance(value, str) and Path(value).is_absolute():
                    try:
                        relative = Path(value).relative_to(Path(srv.HERE) / "data")
                    except ValueError:
                        continue
                    self.stack.enter_context(patch.object(module, name, str(self.root / relative)))
        for p in (patch.object(srv, "tf_config", return_value=self.config),
                  patch.object(srv, "_caller_profile", return_value=PLAYER),
                  patch.object(srv, "_ghost_caller", return_value=PLAYER),
                  patch.object(srv.acct, "authenticate",
                               return_value=({"kind": "account", "who": PLAYER,
                                              "profileId": PLAYER}, None)),
                  patch.object(srv.time, "time", return_value=1800000000),
                  patch.object(srv, "_OPPONENT_CACHE", None),
                  patch.object(srv, "LOG_PATH", str(self.root / "requests.jsonl")),
                  contextlib.redirect_stdout(io.StringIO())):
            self.stack.enter_context(p)
        self.server = HTTPServer(("127.0.0.1", 0), srv.Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.stack.callback(self.stop_http)

    def stop_http(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, method="GET", body=None):
        self.connection.request(method, path, body=body)
        response = self.connection.getresponse()
        raw = response.read()
        payload = json.loads(raw) if "json" in response.getheader("Content-Type", "") else raw
        return response.status, payload

    def upload(self, owner=PLAYER, track=1258, blob=None):
        cid = self.create_content(owner, track)
        with patch.object(srv, "_ghost_caller", return_value=owner):
            status, _ = self.request("/public/userstorage/v2/content/ghost/%d/payload" % cid,
                                     "PUT", ghost_blob() if blob is None else blob)
            self.assertEqual(status, 200)
        return cid

    def create_content(self, owner=PLAYER, track=1258):
        with patch.object(srv, "_ghost_caller", return_value=owner):
            status, result = self.request("/public/userstorage/v2/content/ghost", "POST",
                                          json.dumps({"metadata": {"track_id": track,
                                                                    "drive_time": 25000}}))
            self.assertEqual(status, 200)
        return result["contentId"]

    def board_row(self, owner=PLAYER, track=1258):
        boards = srv._load_leaderboards()
        boards.setdefault("track%d" % track, {})[owner] = {"player": owner, "drivetime": 25000}
        srv._save_leaderboards(boards)

    def assert_chain(self, player, cid, method="GET"):
        status, opponent = self.request(BASE + "find_opponent", method)
        self.assertEqual(status, 200)
        self.assertEqual(opponent, {"opponent": player, "replay_id": cid})
        status, stats = self.request("/public/playerstats/v1/stats/track1258?players=" + player)
        self.assertEqual(status, 200)
        self.assertEqual([row["player"] for row in stats["results"]], [player])
        status, blob = self.request("/public/userstorage/v2/content/ghost/%d/payload" % cid)
        self.assertEqual(status, 200)
        self.assertEqual(blob, ghost_blob())
        self.assertEqual(srv.acct.ghost_probe(blob), (25000, 0, 10))

    def test_upload_only_real_http_chain(self):
        self.board_row()
        cid = self.upload()
        self.assert_chain(PLAYER, cid)
        self.assert_chain(PLAYER, cid, "POST")

    def test_no_candidate_is_explicit_error(self):
        status, payload = self.request(BASE + "find_opponent")
        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "weekly-opponent-unavailable"})
        self.assertEqual(srv._weekly_track_health(1258), (0, 0))
        warning = srv.admin_weekly_status()["warnings"][0]["cn"]
        self.assertIn("同赛道真实榜行", warning)
        self.assertNotIn("一个幽灵都没有", warning)

    def test_uploaded_identity_without_board_row_is_not_advertised(self):
        self.upload()
        status, payload = self.request(BASE + "find_opponent")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "weekly-opponent-unavailable")
        self.assertEqual(srv._weekly_track_health(1258)[0], 0)

    def test_missing_or_short_payload_is_not_advertised(self):
        self.board_row()
        cid = self.create_content()
        status, payload = self.request(BASE + "find_opponent")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "weekly-opponent-unavailable")
        with patch.object(srv, "_OPPONENT_CACHE", None):
            status, _ = self.request("/public/userstorage/v2/content/ghost/%d/payload" % cid,
                                     "PUT", b"too-short")
            self.assertEqual(status, 200)
            status, payload = self.request(BASE + "find_opponent", "POST")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "weekly-opponent-unavailable")

    def test_unreadable_candidate_is_skipped(self):
        first, second = srv.OPPONENT_PIDS[:2]
        cache = (
            {first: {"track1258": {"player": first, "drivetime": 25000}},
             second: {"track1258": {"player": second, "drivetime": 26000}}},
            {first: {"track1258": 101}, second: {"track1258": 102}},
        )

        def payload(cid):
            if cid == 101:
                raise OSError("payload disappeared during read")
            return ghost_blob()

        with patch.object(srv, "_OPPONENT_CACHE", cache), \
                patch.object(srv.acct, "ghost_payload", side_effect=payload):
            self.assertEqual(srv._weekly_opponent(), (second, 102))
            self.assertEqual(srv._weekly_track_health(1258)[0], 1)

    def test_cross_track_upload_is_not_advertised(self):
        self.board_row()
        self.upload(track=9999)
        status, payload = self.request(BASE + "find_opponent")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "weekly-opponent-unavailable")


if __name__ == "__main__":
    unittest.main()
