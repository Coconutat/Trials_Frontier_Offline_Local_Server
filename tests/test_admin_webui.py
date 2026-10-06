"""后台管理页（/__admin）离线自检。

    python -m unittest tests.test_admin_webui -v

覆盖三件真正会出事的事：
  1. 门禁有没有洞 —— 每个 /__* 端点没登录时必须是 401（含改前裸奔的那几个）。
  2. 下发物品有没有把存档写坏 —— 白名单、version 必须 +1、改前必须能回滚。
  3. 前端文案 / 静态白名单有没有缺件 —— i18n 两语键集必须一致，
     app.js 和 index.html 用到的键必须都在，_ADMIN_FILES 必须覆盖 admin/ 全部文件。

全部写盘都在 TemporaryDirectory 里；不启动服务器、不连设备。
"""
import email.message
import json
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import tf_server as srv          # noqa: E402
import tflocal_accounts as acct  # noqa: E402

ADMIN_DIR = ROOT / "server" / "admin"
PID = "53ebbd18-818e-5c2c-a865-773262f736e5"


class Resp(object):
    """伪 handler 收集到的一次响应。"""

    def __init__(self, status, headers, raw):
        self.status = status
        self.headers = dict(headers or {})
        self.raw = raw or b""

    @property
    def text(self):
        return self.raw.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)

    def jget(self, key, default=None):
        """JSON 端点的字段；HTML 端点（/__ui）返回 default，不炸。"""
        try:
            return self.json().get(key, default)
        except Exception:
            return default

    def token(self):
        """Set-Cookie 里的 tf_admin 值；清除 Cookie 时是空串。"""
        c = self.headers.get("Set-Cookie") or ""
        if "tf_admin=" not in c:
            return None
        return c.split("tf_admin=", 1)[1].split(";", 1)[0]


def request(path, body=None, token=None, query="", method="GET", host=None):
    """离线调一次 _introspect。返回 (handled, Resp|None)。"""
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    h = object.__new__(srv.Handler)
    h.command = method
    h.client_address = ("127.0.0.1", 12345)
    h.headers = {"Content-Type": "application/json"}
    if host:                      # 不传就没有 Host，_public_host 会去探测真机 IP
        h.headers["Host"] = host
    if token is not None:
        h.headers["Cookie"] = "tf_admin=" + token
    box = []

    def fake_send(self, status, headers, raw):
        box.append(Resp(status, headers, raw))

    with patch.object(srv.Handler, "_send", fake_send):
        handled = h._introspect(path, query, payload)
    return handled, (box[0] if box else None)


def request_handle(path, method="GET", token=None, body=b"", query="", host=None):
    """走**真正的 `_handle`**，包含它在 `_introspect` 之前抄的那些近路。

    门禁测试必须走这一条：`_handle` 里的 `if path == "/__xxx": return` 就是绕过
    访问控制的洞（`/__log` 曾经正好卡在那儿），只调 `_introspect` 测不出来。
    """
    h = object.__new__(srv.Handler)
    h.command = method
    h.client_address = ("127.0.0.1", 12345)
    h.path = path + ("?" + query if query else "")
    h.headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    if host:
        h.headers["Host"] = host
    if token is not None:
        h.headers["Cookie"] = "tf_admin=" + token
    h.rfile = io.BytesIO(body)
    box = []

    def fake_send(self, status, headers, raw):
        box.append(Resp(status, headers, raw))

    with patch.object(srv.Handler, "_send", fake_send):
        h._handle(method)
    assert box, "没走到 _send：%s %s" % (method, path)
    return box[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for name, rel in (("ACCOUNTS", "accounts.json"), ("SESSIONS", "sessions.json"),
                          ("DEVICES", "devices.json"), ("REMEMBER", "remember.json"),
                          ("BINDINGS", "bindings.json"), ("ADMIN", "admin.json")):
            p = patch.object(acct, name, str(d / rel))
            p.start()
            self.addCleanup(p.stop)
        self.save_dir = d / "save"
        p = patch.object(acct, "SAVE_DIR", str(self.save_dir))
        p.start()
        self.addCleanup(p.stop)
        # 防手滑：这些用例永远不该碰真存档目录。
        self.assertNotEqual(acct.SAVE_DIR, os.path.join(
            str(ROOT / "server"), "data", "save"))

    # ---------------------------------------------------------------- 工具
    def bootstrap(self, password="correct-horse-9"):
        """造管理员。返回口令。"""
        acct.admin_create("admin", password)
        return password

    def login(self, password="correct-horse-9"):
        pw = self.bootstrap() if not acct.admin_exists() else password
        token, err = acct.admin_login("admin", pw)
        self.assertIsNone(err)
        self.assertTrue(token)
        return token

    def write_save(self, pid=PID, items=(0, 457, 1, 100, 2, 50, 1152, 14), version=7):
        doc = {
            "version": version, "saved_at": 1800000000,
            "saved_at_iso": "2027-01-15 08:00:00", "account": "tester",
            "kind": "account",
            "content": {
                "items2": list(items),
                "highscores2": [[1024, 3000, 256, 0, 0], [1051, 0, 256, 0, 0]],
                "achievements2": [1, 2], "tutorials2": [1],
                "missions2": [1], "statistics2": {"runs": 3},
            },
        }
        acct._store(os.path.join(acct.SAVE_DIR, pid, "latest.json"), doc)
        return doc

    def history(self, pid=PID):
        h = os.path.join(acct.SAVE_DIR, pid, "history")
        return sorted(os.listdir(h)) if os.path.isdir(h) else []


# ---------------------------------------------------------------- 鉴权
class AdminAuth(Base):
    def test_bootstrap_creates_exactly_one_admin(self):
        self.assertFalse(acct.admin_exists())
        user, pw = acct.admin_bootstrap()
        self.assertEqual(user, "admin")
        self.assertEqual(len(pw), 12)
        # 第二次不许再建（否则每次重启都换口令，控制台打的那行立刻作废）。
        self.assertIsNone(acct.admin_bootstrap())
        self.assertTrue(acct.admin_exists())

    def test_login_and_token_roundtrip(self):
        pw = self.bootstrap()
        token, err = acct.admin_login("admin", pw)
        self.assertIsNone(err)
        self.assertEqual(acct.admin_by_token(token)["username"], "admin")
        self.assertIsNone(acct.admin_by_token("deadbeef"))
        self.assertIsNone(acct.admin_by_token(None))

    def test_wrong_password_and_unknown_user(self):
        pw = self.bootstrap()
        self.assertEqual(acct.admin_login("admin", pw + "x")[1], "invalid-credentials")
        self.assertEqual(acct.admin_login("root", pw)[1], "not-found")
        self.assertEqual(acct.admin_login("", pw)[1], "bad-request")

    def test_expired_token_rejected(self):
        token = self.login()
        db = acct._load(acct.ADMIN, {})
        db["sessions"][token]["created"] -= acct.ADMIN_SESSION_TTL + 1
        acct._store(acct.ADMIN, db)
        self.assertIsNone(acct.admin_by_token(token))

    def test_expired_session_swept_on_next_login(self):
        pw = self.bootstrap()
        old, _ = acct.admin_login("admin", pw)
        db = acct._load(acct.ADMIN, {})
        db["sessions"][old]["created"] -= acct.ADMIN_SESSION_TTL + 1
        acct._store(acct.ADMIN, db)
        acct.admin_login("admin", pw)
        self.assertNotIn(old, acct._load(acct.ADMIN, {})["sessions"])

    def test_logout_kills_only_that_token(self):
        pw = self.bootstrap()
        a, _ = acct.admin_login("admin", pw)
        b, _ = acct.admin_login("admin", pw)
        self.assertTrue(acct.admin_logout(a))
        self.assertIsNone(acct.admin_by_token(a))
        self.assertIsNotNone(acct.admin_by_token(b))
        self.assertFalse(acct.admin_logout(a))

    def test_password_change_kicks_old_tokens(self):
        pw = self.bootstrap()
        old, _ = acct.admin_login("admin", pw)
        acct.admin_create("admin", "brand-new-pw-1", force=True)
        self.assertIsNone(acct.admin_by_token(old))
        self.assertEqual(acct.admin_login("admin", pw)[1], "invalid-credentials")
        self.assertIsNotNone(acct.admin_login("admin", "brand-new-pw-1")[0])

    def test_create_refuses_duplicate_without_force(self):
        self.bootstrap()
        self.assertEqual(acct.admin_create("admin", "other-pw-99")[1], "exists")

    def test_username_is_normalised(self):
        pw = self.bootstrap()
        self.assertIsNotNone(acct.admin_login("ADMIN", pw)[0])
        self.assertIsNotNone(acct.admin_login("  Admin ", pw)[0])


# ---------------------------------------------------------------- 门禁
class AdminGate(Base):
    # 改前裸奔、现在必须被墙住的端点 —— 这是这次改动最要紧的安全面。
    GATED = [("GET", "/__accounts"), ("GET", "/__devices"), ("GET", "/__sessions"),
             ("GET", "/__saves"), ("GET", "/__save"), ("GET", "/__history"),
             ("GET", "/__restore"), ("GET", "/__leaderboards"), ("GET", "/__ghosts"),
             ("GET", "/__config"), ("POST", "/__config"), ("GET", "/__log"),
             ("GET", "/__help"), ("POST", "/__api/login"),
             ("POST", "/__api/password"), ("POST", "/__api/delete"),
             ("POST", "/__api/admin/grant"), ("POST", "/__api/admin/rollback"),
             ("POST", "/__api/admin/revert"), ("GET", "/__api/admin/pvp"),
             ("GET", "/__api/admin/info"),
             ("POST", "/__api/admin/pvp"),
             ("POST", "/__api/admin/sessions/clear"),
             ("POST", "/__api/admin/password")]
    PUBLIC = [("GET", "/__ping"), ("GET", "/__ui"), ("GET", "/__register"),
              ("POST", "/__api/register"), ("POST", "/__api/admin/login")]

    def test_every_gated_endpoint_401_without_token(self):
        for method, path in self.GATED:
            handled, r = request(path, body={}, method=method)
            self.assertTrue(handled, path)
            self.assertEqual(r.status, 401, "%s %s 没被门禁拦住" % (method, path))
            self.assertEqual(r.json()["error"], "admin-required", path)

    def test_real_routing_gates_before_any_shortcut(self):
        """★ 真正的路由（_handle）也不许有近路。这曾经真的漏过一次：/__log。"""
        for method, path in self.GATED:
            r = request_handle(path, method=method)
            self.assertEqual(r.status, 401, "%s %s 在 _handle 层就漏了" % (method, path))
            self.assertEqual(r.json()["error"], "admin-required", path)

    def test_real_routing_serves_log_only_with_token(self):
        token = self.login()
        self.assertEqual(request_handle("/__log").status, 401)
        r = request_handle("/__log", token=token)
        self.assertEqual(r.status, 200)
        self.assertIsInstance(r.json(), list)     # 形状没变：裸数组

    def test_bogus_token_is_not_enough(self):
        handled, r = request("/__accounts", token="0" * 32)
        self.assertTrue(handled)
        self.assertEqual(r.status, 401)
        self.assertEqual(request_handle("/__accounts", token="0" * 32).status, 401)

    def test_gated_endpoint_ok_with_token(self):
        token = self.login()
        for method, path in self.GATED:
            if path in ("/__api/login", "/__api/password", "/__api/delete",
                        "/__api/admin/rollback", "/__api/admin/revert"):
                continue  # 这几个要真参数，下面单独测
            handled, r = request(path, body={}, token=token, method=method)
            self.assertTrue(handled, path)
            self.assertNotEqual(r.status, 401, "%s %s 有票据还被拦" % (method, path))
            self.assertNotEqual(request_handle(path, method=method, token=token).status,
                                401, "%s %s 在 _handle 层被拦" % (method, path))

    def test_public_endpoints_stay_open(self):
        for method, path in self.PUBLIC:
            handled, r = request(path, body={}, method=method)
            self.assertTrue(handled, path)
            # 公开端点可能因为参数不对回 400/401(invalid-credentials)，
            # 但不能是门禁那个错。
            self.assertNotEqual(r.jget("error"), "admin-required", path)
            open_r = request_handle(path, method=method)
            self.assertNotEqual(open_r.jget("error"), "admin-required",
                                "%s 在 _handle 层被拦" % path)

    def test_me_reports_state_without_leaking_401(self):
        handled, r = request("/__api/admin/me")
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)          # 200 而不是 401：不靠状态码泄信息
        self.assertFalse(r.json()["ok"])
        self.assertIsNone(r.json()["username"])
        handled, r = request("/__api/admin/me", token=self.login())
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["username"], "admin")

    # ------------------------------------------------------------ 登录端点
    def test_login_endpoint_sets_httponly_cookie(self):
        pw = self.bootstrap()
        handled, r = request("/__api/admin/login",
                             body={"username": "admin", "password": pw}, method="POST")
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Secure", cookie)   # ★ 明文 HTTP 下加 Secure 会静默失效
        self.assertTrue(r.token())
        self.assertEqual(acct.admin_by_token(r.token())["username"], "admin")

    def test_login_endpoint_rejects_bad_password(self):
        self.bootstrap()
        handled, r = request("/__api/admin/login",
                             body={"username": "admin", "password": "nope"}, method="POST")
        self.assertEqual(r.status, 401)
        self.assertFalse(r.json()["ok"])
        self.assertNotIn("Set-Cookie", r.headers)

    def test_logout_clears_cookie(self):
        token = self.login()
        handled, r = request("/__api/admin/logout", body={}, token=token, method="POST")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.token(), "")                       # Max-Age=0
        self.assertIn("Max-Age=0", r.headers.get("Set-Cookie", ""))
        self.assertIsNone(acct.admin_by_token(token))

    def test_password_endpoint_enforces_min_length(self):
        token = self.login()
        handled, r = request("/__api/admin/password", body={"password": "short"},
                             token=token, method="POST")
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["error"], "too-short")

    def test_password_endpoint_resigns_cookie(self):
        old = self.login()
        acct.admin_create("admin", "another-old-1", force=True)   # 制造一个已知口令
        old, _ = acct.admin_login("admin", "another-old-1")
        handled, r = request("/__api/admin/password", body={"password": "fresh-secret-1"},
                             token=old, method="POST")
        self.assertEqual(r.status, 200)
        fresh = r.token()
        self.assertTrue(fresh)
        self.assertIsNone(acct.admin_by_token(old))      # 旧票被 force 踢掉
        self.assertIsNotNone(acct.admin_by_token(fresh))  # 但重签了一张，没被登出
        self.assertIsNotNone(acct.admin_login("admin", "fresh-secret-1")[0])


# ---------------------------------------------------------------- 下发物品
class Grant(Base):
    def test_add_bumps_version_and_snapshots(self):
        self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": 1, "amount": 1000}])
        self.assertIsNone(err)
        self.assertEqual(res["applied"][0],
                         {"item_id": 1, "name": "coins", "before": 100, "after": 1100})
        self.assertEqual(acct.load_progress_items(PID)[1], 1100)
        # ★ version 必须 +1，否则 remote==local，客户端用本地档覆盖服务器，下发当场失效。
        self.assertEqual(acct.load_progress(PID)["version"], 8)
        self.assertEqual(res["server_version"], 8)
        # 快照必须是「下发前」那份，不能带上改动。
        snap = acct._load(os.path.join(acct.SAVE_DIR, PID, "history",
                                       res["snapshot"] + ".json"), None)
        self.assertEqual(snap["version"], 7)
        self.assertEqual(snap["content"]["items2"][3], 100)

    def test_only_items2_version_saved_at_and_audit_move(self):
        before = self.write_save()
        acct.grant_items(PID, [{"item_id": 2, "amount": 5, "mode": "set"}])
        after = acct.load_progress(PID)
        for k, v in before["content"].items():
            if k == "items2":
                continue
            self.assertEqual(after["content"][k], v, "content.%s 被动了" % k)
        for k, v in before.items():
            if k in ("content", "version", "saved_at", "saved_at_iso", "granted"):
                continue
            self.assertEqual(after[k], v, "顶层 %s 被动了" % k)
        self.assertEqual(set(after) - set(before), {"granted"})
        self.assertEqual(after["content"]["items2"][5], 5)   # id 2 -> 5（set 不是加）
        # saved_at 是**应该**动的：它记录服务端这次写入的时刻。
        self.assertNotEqual(after["saved_at"], before["saved_at"])
        self.assertTrue(after["saved_at_iso"])

    def test_appends_item_that_is_missing(self):
        self.write_save(items=(1, 100))          # 没有 id 2
        res, err = acct.grant_items(PID, [{"item_id": 2, "amount": 3}])
        self.assertIsNone(err)
        self.assertEqual(acct.load_progress_items(PID)[2], 3)
        self.assertEqual(res["applied"][0]["before"], 0)

    def test_rejects_item_outside_whitelist(self):
        self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": 1152, "amount": 1}])
        self.assertIsNone(res)
        self.assertEqual(err, "not-grantable:1152")
        # 被拒绝时不许留下任何痕迹
        self.assertEqual(acct.load_progress(PID)["version"], 7)
        self.assertEqual(self.history(), [])

    def test_rejects_negative_result(self):
        self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": 1, "amount": -500}])
        self.assertEqual(err, "negative:1")
        self.assertEqual(acct.load_progress_items(PID)[1], 100)
        self.assertEqual(self.history(), [])

    def test_rejects_junk_and_empty(self):
        self.write_save()
        for bad in ([], None, ["x"], [{"item_id": "?", "amount": 1}],
                    [{"item_id": 1, "amount": None}]):
            self.assertIsNotNone(acct.grant_items(PID, bad)[1], repr(bad))
        self.assertEqual(acct.load_progress(PID)["version"], 7)

    def test_bad_profile_and_missing_save(self):
        self.write_save()
        self.assertEqual(acct.grant_items("", [{"item_id": 1, "amount": 1}])[1], "bad-profile")
        self.assertEqual(acct.grant_items("nobody", [{"item_id": 1, "amount": 1}])[1],
                         "no-save")

    def test_multi_item_grant_is_atomic_on_error(self):
        self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": 1, "amount": 10},
                                          {"item_id": 999, "amount": 1}])
        self.assertEqual(err, "not-grantable:999")
        self.assertEqual(acct.load_progress_items(PID)[1], 100)   # 前一条也不许落地
        self.assertEqual(acct.load_progress(PID)["version"], 7)

    def test_audit_keeps_last_twenty(self):
        self.write_save()
        for i in range(23):
            self.assertIsNone(acct.grant_items(PID, [{"item_id": 1, "amount": 1}])[1])
        audit = acct.load_progress(PID)["granted"]
        self.assertEqual(len(audit), 20)
        self.assertEqual(acct.load_progress(PID)["version"], 7 + 23)

    # ------------------------------------------------------------ 撤销
    def test_undo_grant_restores_original(self):
        self.write_save()
        res, _ = acct.grant_items(PID, [{"item_id": 1, "amount": 1000}])
        out, err = acct.restore_snapshot(PID, res["snapshot"])
        self.assertIsNone(err)
        self.assertEqual(acct.load_progress_items(PID)[1], 100)
        self.assertEqual(out["server_version"], 7)

    def test_undo_refuses_arbitrary_history(self):
        doc = self.write_save()
        acct._snapshot(PID, doc, "")          # 冒充玩家自己的普通历史档
        plain = [f[:-5] for f in self.history() if not f.startswith(("pre_grant_",
                                                                    "pre_restore_"))]
        self.assertTrue(plain)
        for name in plain + ["latest", "", None, "../../latest"]:
            self.assertEqual(acct.restore_snapshot(PID, name)[1], "not-a-snapshot", repr(name))

    def test_undo_missing_snapshot(self):
        self.write_save()
        self.assertEqual(acct.restore_snapshot(PID, "pre_grant_nope")[1], "not-found")

    # ------------------------------------------------------------ 回滚
    def test_rollback_leaves_its_own_restore_point(self):
        before = self.write_save(version=7)
        # 手写一条旧历史档。★ 不能走 write_save()：那会顺手把 latest.json 也改掉。
        old = json.loads(json.dumps(before))
        old["version"] = 3
        old["saved_at_iso"] = "old"
        acct._store(os.path.join(acct.SAVE_DIR, PID, "history", "1770000000.json"), old)
        self.assertEqual(acct.load_progress(PID)["version"], 7)
        snap, err = acct.rollback_save(PID, "1770000000")
        self.assertIsNone(err)
        self.assertTrue(snap.startswith(acct.RESTORE_SNAPSHOT_TAG), snap)
        self.assertEqual(acct.load_progress(PID)["version"], 3)
        # 撤销这次回滚 == 回到回滚前
        self.assertIsNone(acct.restore_snapshot(PID, snap)[1])
        self.assertEqual(acct.load_progress(PID)["version"], 7)

    def test_rollback_errors(self):
        self.write_save()
        self.assertEqual(acct.rollback_save(PID, "latest")[1], "bad-ts")
        self.assertEqual(acct.rollback_save(PID, "")[1], "bad-ts")
        self.assertEqual(acct.rollback_save(PID, "1700000000")[1], "not-found")

    def test_restore_save_keeps_old_contract(self):
        """/__restore 的调用方只看返回真假，形状不能变。"""
        self.write_save()
        self.assertTrue(acct.restore_save(PID, "latest"))     # latest = 原样返回
        self.assertIsNone(acct.restore_save(PID, "1700000000"))  # 不存在 -> 假

    def test_snapshot_keep_is_bounded(self):
        doc = self.write_save()
        for _ in range(acct.SNAPSHOT_KEEP + 6):
            acct._snapshot(PID, doc, acct.GRANT_SNAPSHOT_TAG)
        pref = [f for f in self.history() if f.startswith(("pre_grant_", "pre_restore_"))]
        self.assertEqual(len(pref), acct.SNAPSHOT_KEEP)

    def test_snapshot_names_survive_plain_history_trim(self):
        """前缀名在 sorted() 里排在纯数字后面，save_progress 的裁剪丢不到它们。"""
        self.write_save()
        res, _ = acct.grant_items(PID, [{"item_id": 1, "amount": 1}])
        hist = os.path.join(acct.SAVE_DIR, PID, "history")
        for i in range(acct.SAVE_HISTORY_MAX + 10):
            acct._store(os.path.join(hist, "17%08d.json" % i), {"version": i})
        files = sorted(f for f in os.listdir(hist) if f.endswith(".json"))
        for old in files[:-acct.SAVE_HISTORY_MAX]:
            if "_" not in old:
                os.remove(os.path.join(hist, old))
        self.assertIn(res["snapshot"] + ".json", os.listdir(hist))


# ---------------------------------------------------------------- 竞技场余额
class Pvp(Base):
    """PVP 金票/筹码走服务端 pvp_state.json —— 真机实测 m00702 才搞清这不是存档物品。

    这一组用例存在的意义就是把「金票真源是服务端状态」这件事钉住：谁要再把
    金票塞回 GRANTABLE_ITEMS，test_golden_ticket_is_not_a_save_item 会响。
    """

    def setUp(self):
        super().setUp()
        self.pvp_path = Path(self.tmp.name) / "pvp_state.json"
        for name, val in (("PVP_STATE_PATH", str(self.pvp_path)),
                          ("_pvp_players", {}), ("_pvp_chips", {}),
                          ("_pvp_tickets", {})):
            p = patch.object(srv, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.assertNotEqual(srv.PVP_STATE_PATH, os.path.join(
            str(ROOT / "server"), "data", "pvp_state.json"))
        # 脏标记/节流是模块级 list，测试之间必须清干净。
        srv._pvp_saved_at[0] = 0.0
        srv._pvp_dirty[0] = False

    def stored(self):
        return json.loads(self.pvp_path.read_text(encoding="utf-8"))

    def test_golden_ticket_is_not_a_save_item(self):
        """金票不在存档白名单里 —— 它是 pvp_state.json 的计数器，不是 items2。"""
        self.assertNotIn(135, acct.GRANTABLE_ITEMS)
        self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": 135, "amount": 3}])
        self.assertIsNone(res)
        self.assertEqual(err, "not-grantable:135")

    def test_read_is_side_effect_free(self):
        got = srv.pvp_read(PID)
        self.assertFalse(got["known"])
        self.assertEqual(got["golden_ticket"], srv._PVP_DEFAULT_GOLDEN_TICKET)
        self.assertEqual(got["chips"], 0)
        # 只读不该建档 —— 后台点一下就给玩家凭空建 PVP 档是不对的。
        self.assertNotIn(PID, srv._pvp_players)
        self.assertFalse(self.pvp_path.exists())

    def test_grant_golden_ticket_add_and_persist(self):
        srv._pvp_players[PID] = {"rank": 24, "star": 2, "season": 692,
                                 "win_streak": 3, "golden_ticket": 13}
        res, err = srv.pvp_grant(PID, {"golden_ticket": 2000})
        self.assertIsNone(err)
        self.assertEqual(res["mode"], "add")
        self.assertEqual(res["applied"][0],
                         {"field": "golden_ticket", "before": 13, "after": 2013})
        # ★ 立刻落盘（force=True），不等 10 秒节流 —— 服务器随时可能被关掉。
        self.assertEqual(self.stored()["players"][PID]["golden_ticket"], 2013)
        self.assertEqual(srv.pvp_read(PID)["golden_ticket"], 2013)

    def test_grant_set_mode_overwrites(self):
        srv._pvp_players[PID] = {"golden_ticket": 13, "rank": 24}
        res, err = srv.pvp_grant(PID, {"golden_ticket": 5}, mode="set")
        self.assertIsNone(err)
        self.assertEqual(res["applied"][0]["after"], 5)

    def test_grant_creates_player_entry_with_default_when_absent(self):
        res, err = srv.pvp_grant(PID, {"golden_ticket": 7})
        self.assertIsNone(err)
        self.assertEqual(res["applied"][0]["before"], srv._PVP_DEFAULT_GOLDEN_TICKET)
        self.assertEqual(srv.pvp_read(PID)["golden_ticket"],
                         srv._PVP_DEFAULT_GOLDEN_TICKET + 7)

    def test_chips_grant_settles_accrual_first(self):
        """覆盖筹码前必须先把「按时间产出」的挂账结算掉，否则会吞掉玩家该得的币。"""
        with patch.object(srv, "cfg_int", side_effect=lambda sec, key, default=0: {
                ("chips", "per_track_seconds"): 3600,
                ("chips", "max"): 0}.get((sec, key), default)):
            srv._pvp_chips[PID] = {"chips": 100, "ts": int(time.time()) - 7200,
                                   "acc": 0, "tracks": [1024, 1032]}   # 2 条赛道 × 2 小时
            res, err = srv.pvp_grant(PID, {"chips": 1000}, mode="set")
            self.assertIsNone(err)
            # 7200 秒 × 2 条 = 4 段，各 1 枚 -> 结算到 104，然后才被 set 成 1000。
            self.assertEqual(res["applied"][0]["before"], 104)
            self.assertEqual(res["applied"][0]["after"], 1000)
        self.assertEqual(self.stored()["chips"][PID]["chips"], 1000)

    def test_rejects_unknown_field_without_partial_write(self):
        srv._pvp_players[PID] = {"golden_ticket": 13}
        res, err = srv.pvp_grant(PID, {"golden_ticket": 99, "rank": 1})
        self.assertIsNone(res)
        self.assertEqual(err, "not-grantable:rank")
        self.assertEqual(srv.pvp_read(PID)["golden_ticket"], 13)   # 一个也没动
        self.assertFalse(self.pvp_path.exists())

    def test_rejects_negative_bad_mode_and_junk(self):
        srv._pvp_players[PID] = {"golden_ticket": 13}
        for fields, mode, want in (({"golden_ticket": -1}, "add", "negative:golden_ticket"),
                                   ({"golden_ticket": "x"}, "add", "bad-value:golden_ticket"),
                                   ({"golden_ticket": 1}, "mul", "bad-mode"),
                                   ({}, "add", "bad-request")):
            res, err = srv.pvp_grant(PID, fields, mode=mode)
            self.assertIsNone(res, fields)
            self.assertEqual(err, want, fields)
        self.assertIsNone(srv.pvp_grant("", {"golden_ticket": 1})[0])
        self.assertEqual(srv.pvp_read(PID)["golden_ticket"], 13)

    # ------------------------------------------------------------ 走 HTTP
    def test_endpoint_reads_and_writes(self):
        token = self.login()
        srv._pvp_players[PID] = {"rank": 24, "star": 2, "season": 692,
                                 "win_streak": 3, "golden_ticket": 13}
        handled, r = request("/__api/admin/pvp", token=token,
                             query="profile=" + PID)
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json()["player"]["golden_ticket"], 13)
        self.assertEqual(r.json()["player"]["rank"], 24)

        handled, r = request("/__api/admin/pvp", token=token, method="POST",
                             body={"profile": PID, "fields": {"golden_ticket": 40}})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json()["applied"][0]["after"], 53)
        self.assertEqual(r.json()["player"]["golden_ticket"], 53)

    def test_endpoint_400s_are_mapped(self):
        token = self.login()
        r = request("/__api/admin/pvp", token=token, query="", method="GET")[1]
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["error"], "bad-profile")
        r = request("/__api/admin/pvp", token=token, method="POST",
                    body={"profile": PID, "fields": {"rank": 3}})[1]
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["error"], "not-grantable:rank")


# ---------------------------------------------------------------- 清会话
class ClearSessions(Base):
    def seed(self):
        db = {"tf-local-a-1111": {"user": "a", "profileId": "p1"},
              "tf-local-a-2222": {"user": "a", "profileId": "p1"},
              "tf-local-b-3333": {"user": "b", "profileId": "p2"}}
        acct._store(acct.SESSIONS, db)
        acct._store(acct.REMEMBER, {"a": {"ticket": "keep-me"}})
        return db

    def test_clear_one_user_only(self):
        self.seed()
        self.assertEqual(acct.clear_sessions("a"), 2)
        left = acct._load(acct.SESSIONS, {})
        self.assertEqual(list(left), ["tf-local-b-3333"])
        # ★ 长期凭据不能被碰，否则玩家被踢出登录态。
        self.assertIn("a", acct._load(acct.REMEMBER, {}))

    def test_clear_all(self):
        self.seed()
        self.assertEqual(acct.clear_sessions(), 3)
        self.assertEqual(acct._load(acct.SESSIONS, {}), {})

    def test_clear_accepts_endpoint_shape(self):
        token = self.login()
        self.seed()
        handled, r = request("/__api/admin/sessions/clear", body={"username": "a"},
                             token=token, method="POST")
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json(), {"ok": True, "removed": 2})
        handled, r = request("/__api/admin/sessions/clear", body={}, token=token,
                             method="POST")
        self.assertEqual(r.json()["removed"], 1)

    def test_clear_empty_and_unknown_user(self):
        self.assertEqual(acct.clear_sessions(), 0)
        self.seed()
        self.assertEqual(acct.clear_sessions("nobody"), 0)


# ---------------------------------------------------------------- 端点串起来
class Endpoints(Base):
    def test_grant_then_undo_through_http_surface(self):
        token = self.login()
        self.write_save()
        handled, r = request("/__api/admin/grant", token=token, method="POST", body={
            "profile": PID, "items": [{"item_id": 2, "amount": 5}]})
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)
        snap = r.json()["snapshot"]
        self.assertEqual(r.json()["server_version"], 8)

        handled, r = request("/__api/admin/revert", token=token, method="POST",
                             body={"profile": PID, "snapshot": snap})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json()["server_version"], 7)
        self.assertEqual(acct.load_progress_items(PID).get(2, 0), 50)   # 回到 7 版的原值

    def test_grant_endpoint_maps_errors_to_400(self):
        token = self.login()
        handled, r = request("/__api/admin/grant", token=token, method="POST",
                             body={"profile": PID, "items": [{"item_id": 1, "amount": 1}]})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["error"], "no-save")
        self.assertIn("latest.json", r.json()["message"])

    def test_rollback_endpoint_returns_snapshot(self):
        token = self.login()
        self.write_save(version=7)
        acct._store(os.path.join(acct.SAVE_DIR, PID, "history", "1770000000.json"),
                    self.write_save(version=3))
        handled, r = request("/__api/admin/rollback", token=token, method="POST",
                             body={"profile": PID, "ts": "1770000000"})
        self.assertEqual(r.status, 200)
        self.assertTrue(r.json()["snapshot"].startswith(acct.RESTORE_SNAPSHOT_TAG))
        self.assertEqual(r.json()["server_version"], 3)
        handled, r = request("/__api/admin/rollback", token=token, method="POST",
                             body={"profile": PID, "ts": "1700000000"})
        self.assertEqual(r.status, 400)

    def test_info_hands_out_the_addresses(self):
        """后台要能把「玩家注册入口」发给别人，所以端点必须回能直接用的绝对地址。"""
        token = self.login()
        handled, r = request("/__api/admin/info", token=token, host="192.168.9.9:9999")
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)
        j = r.json()
        self.assertEqual(j["username"], "admin")
        self.assertEqual(j["register_url"], "http://192.168.9.9:9999/__ui")
        self.assertEqual(j["admin_url"], "http://192.168.9.9:9999/__admin")

    def test_info_never_hands_out_loopback(self):
        """在 PC 上用 127.0.0.1 打开后台时，发出去的地址必须是玩家能连上的那个。"""
        token = self.login()
        with patch.object(srv, "_lan_ip", return_value="10.1.2.3"):
            handled, r = request("/__api/admin/info", token=token, host="127.0.0.1:8123")
        self.assertEqual(r.json()["register_url"], "http://10.1.2.3:8123/__ui")
        self.assertEqual(r.json()["admin_url"], "http://10.1.2.3:8123/__admin")

    def test_public_host_reads_the_real_header_object(self):
        """★ 真机上 headers 是 email.message.Message 而不是 dict。

        只认 dict 时 `_req_host` 永远取不到 Host，`_public_host` 就退回默认端口 8000：
        真机实测服务器跑在 8123，发给玩家的地址却是 `http://192.168.x.x:8000/__ui`。
        """
        msg = email.message.Message()
        msg["Host"] = "192.168.9.9:8123"
        self.assertEqual(srv._req_host(msg), "192.168.9.9:8123")
        self.assertEqual(srv._public_host(msg), "192.168.9.9:8123")   # 非回环原样带回
        loop = email.message.Message()
        loop["Host"] = "127.0.0.1:8123"
        with patch.object(srv, "_lan_ip", return_value="10.1.2.3"):
            self.assertEqual(srv._public_host(loop), "10.1.2.3:8123")

    def test_help_lists_admin_ui_and_new_endpoints(self):
        token = self.login()
        handled, r = request("/__help", token=token)
        self.assertTrue(handled)
        blob = json.dumps(r.json(), ensure_ascii=False)
        self.assertIn("/__admin", blob)
        for ep in ("/__api/admin/login", "/__api/admin/grant", "/__api/admin/pvp",
                   "/__api/admin/rollback", "/__api/admin/info",
                   "/__api/admin/revert", "/__api/admin/password",
                   "/__api/admin/sessions/clear"):
            self.assertIn(ep, blob, "%s 没登记进 /__help" % ep)
        self.assertIn("[public]", blob)     # 门禁边界要能自解释


# ---------------------------------------------------------------- 静态页
class StaticFiles(Base):
    def test_every_admin_file_is_registered(self):
        on_disk = {p.name for p in ADMIN_DIR.iterdir() if p.is_file()}
        served = {name for name, _ in srv._ADMIN_FILES.values()}
        self.assertEqual(on_disk - served, set(), "admin/ 里有文件没登记进 _ADMIN_FILES")
        self.assertEqual(served - on_disk, set(), "_ADMIN_FILES 登记了不存在的文件")

    def test_whitelist_has_no_escape(self):
        for path in srv._ADMIN_FILES:
            self.assertTrue(path.startswith("/__admin"))
            name, _ = srv._ADMIN_FILES[path]
            self.assertNotIn("/", name)
            self.assertNotIn("..", name)

    def test_files_served_without_login(self):
        """登录表单自己必须能加载，否则谁也进不去。"""
        for path in ("/__admin", "/__admin/", "/__admin/app.css", "/__admin/app.js",
                     "/__admin/i18n.json"):
            handled, r = request(path)
            self.assertTrue(handled, path)
            self.assertEqual(r.status, 200, path)
            self.assertTrue(r.raw, path)
            self.assertEqual(r.headers.get("Cache-Control"), "no-store", path)

    def test_path_traversal_is_not_a_key(self):
        for path in ("/__admin/../tf_server.py", "/__admin/app.css/../app.js",
                     "/__admin/..%2fapp.js", "/__admin/nope.js",
                     "/__admin/app.js/", "/__admin/i18n.json/../app.js"):
            r = request_handle(path)
            self.assertNotEqual(r.status, 200, path)
        # /__admin 和 /__admin/ 都是 index，是白名单里**明确**的两项。
        for path in ("/__admin", "/__admin/"):
            self.assertEqual(srv._ADMIN_FILES[path][0], "index.html")

    def test_missing_dir_reports_404_not_crash(self):
        with patch.object(srv, "_ADMIN_DIR", os.path.join(self.tmp.name, "gone")):
            handled, r = request("/__admin")
            self.assertTrue(handled)
            self.assertEqual(r.status, 404)
            self.assertEqual(r.json()["error"], "admin-ui-missing")


# ---------------------------------------------------------------- 文案
class I18n(Base):
    @classmethod
    def setUpClass(cls):
        cls.blob = json.loads((ADMIN_DIR / "i18n.json").read_text(encoding="utf-8"))
        cls.html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
        cls.js = (ADMIN_DIR / "app.js").read_text(encoding="utf-8")
        cls.css = (ADMIN_DIR / "app.css").read_text(encoding="utf-8")

    def test_key_sets_are_identical(self):
        self.assertEqual(set(self.blob), {"cn", "en"})
        cn, en = set(self.blob["cn"]), set(self.blob["en"])
        self.assertEqual(cn - en, set(), "英文缺这些键")
        self.assertEqual(en - cn, set(), "中文缺这些键")
        self.assertGreater(len(cn), 100)

    def test_no_value_is_empty(self):
        for lang, table in self.blob.items():
            for k, v in table.items():
                self.assertTrue(str(v).strip(), "%s.%s 是空的" % (lang, k))

    def test_placeholder_keys_agree_across_langs(self):
        pat = re.compile(r"\{(\w+)\}")
        for k, cn in self.blob["cn"].items():
            self.assertEqual(set(pat.findall(cn)), set(pat.findall(self.blob["en"][k])),
                             "%s 的 {占位符} 两语不一致" % k)

    def test_html_data_i18n_keys_exist(self):
        keys = set(re.findall(r'data-i18n="([^"]+)"', self.html))
        self.assertTrue(keys)
        missing = sorted(k for k in keys if k not in self.blob["cn"])
        self.assertEqual(missing, [], "index.html 用了不存在的键")

    def test_js_literal_keys_exist(self):
        lit = set(re.findall(r"\bt\(\s*'([^']+)'", self.js))
        dyn = set(re.findall(r"\bt\(\s*'([^']+)'\s*\+", self.js))
        missing = sorted(k for k in lit - dyn if k not in self.blob["cn"])
        self.assertEqual(missing, [], "app.js 用了不存在的键")
        # t('前缀' + 变量) 形式的键在这里逐一展开核对
        for prefix, concretes in {"grant.item": ["grant.item1", "grant.item2"]}.items():
            self.assertIn(prefix, dyn, "不再有动态键 " + prefix + "？更新这条断言")
            for k in concretes:
                self.assertIn(k, self.blob["cn"], k)
        # PVP_LABEL 这类「键名放在表里、t() 收的是变量」的也要单独核一遍，
        # 否则删掉一个 i18n 键测试不会响。
        for k in ("grant.pvpGolden", "grant.pvpChips"):
            self.assertIn(k, self.blob["cn"], k)
            self.assertIn(k, self.blob["en"], k)

    def test_tags_in_translations_are_balanced(self):
        """文案会过 innerHTML 的只有 <b> / <code>；不配对的标签会把界面吃掉。"""
        for lang, table in self.blob.items():
            for k, v in table.items():
                for tag in ("b", "code", "i", "em", "strong"):
                    self.assertEqual(str(v).count("<%s>" % tag),
                                     str(v).count("</%s>" % tag),
                                     "%s.%s 的 <%s> 不配对" % (lang, k, tag))

    def test_css_handles_reduced_motion_and_transparency(self):
        for flag in ("prefers-reduced-motion", "prefers-reduced-transparency",
                     "prefers-contrast"):
            self.assertIn(flag, self.css, "没处理 " + flag)
        self.assertIn("backdrop-filter", self.css)

    def test_no_unsanitised_html_sink_for_player_data(self):
        """玩家可控字符串（账号名/平台名）必须走 textContent，不许拼 innerHTML。"""
        self.assertNotIn(".innerHTML", self.js)
        self.assertIn("textContent", self.js)


class Frontend(Base):
    """app.js / app.css / index.html 之间那些「只有浏览器里才会炸」的接口。"""

    @classmethod
    def setUpClass(cls):
        cls.html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
        cls.js = (ADMIN_DIR / "app.js").read_text(encoding="utf-8")
        cls.css = (ADMIN_DIR / "app.css").read_text(encoding="utf-8")

    def test_app_js_parses(self):
        """★ 语法错一次整个界面就全白。正则测不出来，必须真解析。"""
        node = shutil.which("node")
        if not node:
            self.skipTest("没装 node，跳过 JS 语法解析")
        proc = subprocess.run([node, "--check", str(ADMIN_DIR / "app.js")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_i18n_json_parses_in_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("没装 node")
        proc = subprocess.run([node, "-e", "JSON.parse(require('fs')"
                               ".readFileSync(process.argv[1],'utf8'))",
                               str(ADMIN_DIR / "i18n.json")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_css_braces_balance(self):
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        self.assertEqual(css.count("{"), css.count("}"), "app.css 花括号不配对")

    def test_every_dom_id_app_js_uses_exists_in_html(self):
        ids = set(re.findall(r"\$\('#([\w-]+)'\)", self.js))
        self.assertGreater(len(ids), 10)
        have = set(re.findall(r'id="([\w-]+)"', self.html))
        self.assertEqual(sorted(ids - have), [], "app.js 引用了 index.html 里没有的 id")

    def test_nav_labels_match_screens(self):
        navs = set(re.findall(r'data-nav="([\w-]+)"', self.html))
        self.assertTrue(navs)
        # SCREENS 表的键必须和侧栏里的 data-nav 一一对应
        block = re.search(r"const SCREENS\s*=\s*\{(.*?)\n\};", self.js, re.S)
        self.assertIsNotNone(block, "找不到 SCREENS 表")
        keys = set(re.findall(r"^\s*(\w+)\s*:", block.group(1), re.M))
        self.assertEqual(navs - keys, set(), "侧栏有 SCREENS 里没有的项")
        self.assertEqual(keys - navs, set(), "SCREENS 里有侧栏没挂的项")
        for k in keys:
            self.assertIn("data-nav=\"%s\"" % k, self.html)

    def test_html_loads_registered_assets(self):
        for path in ("/__admin/app.css", "/__admin/app.js"):
            self.assertIn(path, self.html, "index.html 没引用 " + path)

    def test_html_is_self_contained_no_cdn(self):
        """离线服务器不能依赖任何外部域名，否则没网时后台变白页。"""
        for bad in ("http://", "https://", "//cdn", "integrity="):
            hits = [m for m in re.findall(r"(?:src|href)=\"([^\"]+)\"", self.html)
                    if bad in m]
            self.assertEqual(hits, [], "index.html 引了外部资源：%s" % hits)


if __name__ == "__main__":
    unittest.main(verbosity=2)
