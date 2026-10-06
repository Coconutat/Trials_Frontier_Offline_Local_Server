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
             ("GET", "/__api/admin/weekly"), ("POST", "/__api/admin/weekly"),
             ("POST", "/__api/admin/undo"),
             ("GET", "/__api/admin/templates"), ("POST", "/__api/admin/templates"),
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
                         {"item_id": 1, "name": "Coins", "before": 100, "after": 1100})
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

    def test_catalog_items_beyond_currency_are_grantable(self):
        """目录里的东西（远不止金币钻石）要真能写进去，否则清单是个骗人的壳。"""
        allowed = acct.grantable_items()
        self.assertGreater(len(allowed), 100, "可下发目录太小，是不是没读到 items.json？")
        iid = 150 if 150 in allowed else sorted(i for i in allowed if i not in (1, 2))[0]
        self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": iid, "amount": 4, "mode": "set"}])
        self.assertIsNone(err, "目录里的 %d 居然不能下发：%s" % (iid, err))
        self.assertEqual(acct.load_progress_items(PID)[iid], 4)
        self.assertEqual(res["applied"][0]["name"], allowed[iid])

    def test_rejects_item_outside_whitelist(self):
        self.write_save()
        # 1152 是 items2 里真实存在的计数器，但它不在物品目录里（目录只收游戏自己
        # 奖励/商店表出现过的 id），所以必须仍然发不出去。
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
    金票塞回可下发目录（items.json），test_golden_ticket_is_not_a_save_item 会响。
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
        self.assertNotIn(135, acct.grantable_items())
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
                   "/__api/admin/weekly", "/__api/admin/undo", "/__api/admin/templates",
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
                     "/__admin/i18n.json", "/__admin/items.json"):
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


# ---------------------------------------------------------------- 物品目录
class ItemCatalog(Base):
    """`server/admin/items.json` 是 tools/build_item_catalog.py 的产物。

    它决定「下发物品」屏能勾到什么，所以形状错了必须在这里响，而不是等玩家点下去。
    """

    @classmethod
    def setUpClass(cls):
        cls.cat = json.loads((ADMIN_DIR / "items.json").read_text(encoding="utf-8"))
        cls.js = (ADMIN_DIR / "app.js").read_text(encoding="utf-8")

    def test_shape_and_count_agree(self):
        c = self.cat
        self.assertEqual(sorted(c), ["categories", "items", "levels", "outfits", "paints",
                                     "rewards", "source"])
        self.assertEqual(c["source"]["items"], len(c["items"]),
                         "source.items 与实际条数不一致（重新跑 tools/build_item_catalog.py）")
        self.assertEqual(c["source"]["outfits"], len(c["outfits"]),
                         "source.outfits 与实际套数不一致（重新跑 tools/build_item_catalog.py）")
        self.assertEqual(c["source"]["paints"], len(c["paints"]),
                         "source.paints 与实际款数不一致（重新跑 tools/build_item_catalog.py）")
        self.assertEqual(c["source"]["levels"], len(c["levels"]),
                         "source.levels 与实际赛道数不一致（重新跑 tools/build_item_catalog.py）")
        self.assertEqual(c["source"]["rewards"], len(c["rewards"]),
                         "source.rewards 与实际奖励 ID 数不一致（重新跑 tools/build_item_catalog.py）")
        self.assertTrue(c["source"]["en"] and c["source"]["cn"], "没记本地化表来源")
        self.assertGreater(len(c["items"]), 300)

    def test_every_item_points_at_a_declared_category(self):
        keys = {x["key"] for x in self.cat["categories"]}
        self.assertEqual(len(keys), len(self.cat["categories"]), "分类键重复")
        nameless = []
        for k, it in self.cat["items"].items():
            self.assertEqual(str(it["id"]), k, "键与 id 不一致：" + k)
            self.assertIn(it["cat"], keys, "%s 的分类 %s 没在 categories 里" % (k, it["cat"]))
            if not it["en"]:
                nameless.append(k)
        # 有十几个 id 只出现在奖励表里、没有 NameId（例：111/185/237/560）。界面用 #id 兜底，
        # 但这类必须一直是少数 —— 数量暴涨说明抽取器坏了或者本地化表没读上。
        self.assertLess(len(nameless), 25, "没名字的物品太多：%s" % nameless)
        for k in nameless:
            self.assertNotEqual(self.cat["items"][k]["cat"], "currency", "货币必须有名字：" + k)

    def test_categories_are_bilingual(self):
        for x in self.cat["categories"]:
            self.assertTrue(x["en"].strip(), x["key"])
            self.assertTrue(x["cn"].strip(), x["key"])
            self.assertNotEqual(x["en"], x["key"], "英文名就是键名，等于没翻译：" + x["key"])

    def test_flag_categories_are_real_and_counted_as_flags(self):
        """app.js 里 FLAG_CATS 的类在存档里是 0/1 标志，只能解锁；写错类会被当成计数器。"""
        m = re.search(r"FLAG_CATS\s*=\s*\{([^}]*)\}", self.js)
        self.assertTrue(m, "app.js 里找不到 FLAG_CATS")
        flags = set(re.findall(r"(\w+)\s*:", m.group(1)))
        keys = {x["key"] for x in self.cat["categories"]}
        self.assertTrue(flags <= keys, "FLAG_CATS 里有不存在的分类：" + str(flags - keys))
        self.assertIn("outfit", flags)          # 真机看过：服装部件 0/1
        self.assertNotIn("parts", flags)        # 零件是计数器，不能被当成标志
        self.assertNotIn("blueprint", flags)    # 蓝图是碎片计数器：真机档里有 0/1/3/7 片
        self.assertNotIn("currency", flags)

    def test_currency_is_present_and_tickets_are_not(self):
        by_cat = {}
        for k, it in self.cat["items"].items():
            by_cat.setdefault(it["cat"], []).append(int(k))
        self.assertEqual(sorted(by_cat["currency"]), [1, 2], "货币只该有金币与钻石")
        # 金票(135)走 pvp_state.json，不进存档 items2 —— 出现在这里会被误当成存档物品下发。
        self.assertNotIn(135, (int(k) for k in self.cat["items"]),
                         "金票不该出现在存档物品目录里")


class OutfitSets(Base):
    """服装按「套」下发：勾一套 = 头盔/上衣/裤装三件（`id = ItemType*5 + tier`）。

    240 件里多数在任何配置里都不出现（隐藏/未上架），只能从游戏自带的套装表推出来，
    所以这里钉的是「推导规则本身」——规则错了，写进存档的就是一堆别的物品的编号。
    """

    @classmethod
    def setUpClass(cls):
        cls.cat = json.loads((ADMIN_DIR / "items.json").read_text(encoding="utf-8"))
        cls.sets = cls.cat["outfits"]
        cls.items = cls.cat["items"]

    def test_parts_follow_the_formula(self):
        self.assertEqual(len(self.sets), 80, "套装表条数变了（customization.txt 里是 80 套）")
        seen = set()
        for k, o in self.sets.items():
            self.assertEqual(o["parts"], [o["type"] * 5, o["type"] * 5 + 1, o["type"] * 5 + 2], k)
            self.assertIn(o["type_src"], ("ItemType", "40+ID"), k)
            for tier, pid in enumerate(o["parts"]):
                self.assertNotIn(pid, seen, "同一个编号被两套用了：%d" % pid)
                seen.add(pid)
                it = self.items[str(pid)]
                self.assertEqual(it["cat"], "outfit", str(pid))
                self.assertEqual(it["set"], k, str(pid))
                self.assertEqual(it["part"], tier, str(pid))
        self.assertEqual(len(seen), 240, "80 套 × 3 件应该是 240 个编号")

    def test_high_roller_is_the_unlimited_fuel_set(self):
        """用户点名的那套：集齐 = 无限汽油（服务端只负责把这 3 件写进存档）。"""
        hr = [o for o in self.sets.values() if "High Roller" in (o["en"] or "")]
        self.assertEqual(len(hr), 1, "找不到 The High Roller")
        o = hr[0]
        self.assertEqual(o["parts"], [740, 741, 742])
        self.assertTrue(o["hidden"], "High Roller 没上架过，应该是隐藏套装")
        self.assertIn("MULTIPLY_FUEL_REFILL_TIME", o["bonus"])
        self.assertIn("无限汽油", o["bonus_cn"])
        self.assertIn("Unlimited fuel", o["bonus_en"])

    def test_old_sets_without_itemtype_use_40_plus_id(self):
        """ID 0–19 那批记录里没有 ItemType 字段，type = 40 + Rider ID（部件名反查验证过）。"""
        eg = [o for o in self.sets.values() if "Eggman" in (o["en"] or "")]
        self.assertEqual(len(eg), 1)
        o = eg[0]
        self.assertEqual((o["type"], o["type_src"], o["parts"]), (57, "40+ID", [285, 286, 287]))
        self.assertEqual(o["part_names"]["285"],
                         ["The Eggman Helmet Piece", "艾格曼头盔"], "官方部件名没读上")

    def test_hidden_sets_and_bonus_coverage(self):
        hidden = [o for o in self.sets.values() if o["hidden"]]
        bonus = [o for o in self.sets.values() if o["bonus"]]
        self.assertEqual(len(hidden), 46, "UnlockType 全是 4 的套数变了")
        self.assertGreaterEqual(len(bonus), 20, "有套装效果的套数掉了")
        for o in bonus:
            self.assertTrue(o["bonus_en"] and o["bonus_cn"], "套装效果没有中英文案：" + o["key"])
        for o in hidden:
            self.assertEqual(o["unlock"], [4, 4, 4], "隐藏套装的 UnlockType 变了：" + o["key"])

    def test_namespace_collisions_are_recorded_and_given_to_outfits(self):
        """20 个编号同时是某个「赛道解锁」条目 —— 以服装为准，旧名字留在 source 里。"""
        bad = self.cat["source"]["overlap_ids"]
        self.assertEqual(len(bad), 20, "撞车编号数变了（重新跑生成器再看）")
        for r in bad:
            self.assertEqual(r["was"], "track")
            self.assertTrue(r["alias"], "撞车的旧名字没留证")
            self.assertEqual(self.items[str(r["id"])]["cat"], "outfit")
            self.assertEqual(self.items[str(r["id"])]["alias"], r["alias"])
        by_cat = {}
        for it in self.items.values():
            by_cat[it["cat"]] = by_cat.get(it["cat"], 0) + 1
        self.assertEqual(by_cat["outfit"], 240, "服装类应该正好等于全部部件")
        self.assertEqual(by_cat["track"], 157, "赛道解锁条目里有 20 个判给服装了")

    def test_every_part_is_grantable(self):
        ids = {int(k) for k in self.items}
        for o in self.sets.values():
            for pid in o["parts"]:
                self.assertIn(pid, ids, "部件不在目录里，下发给它会 not-grantable")


class Paints(Base):
    """涂装不是「一个涂装一个键」，而是「每辆车一条位掩码」：

        items2[664 + BikeID] = ((当前装备的 SkinIndex + 1) << 24) | 已拥有位掩码

    位算错不会「没生效」，而是把别的涂装标成已拥有（还可能写到别的车的字上），
    所以这里把编码本身钉死。真机存档（ccb）里 6 条涂装字都满足这个编码。
    """

    @classmethod
    def setUpClass(cls):
        cls.cat = json.loads((ADMIN_DIR / "items.json").read_text(encoding="utf-8"))
        cls.paints = cls.cat["paints"]

    def test_catalog_covers_every_skin_in_the_bike_table(self):
        self.assertEqual(len(self.paints), 108, "bikes.txt 的 SkinData 是 108 款")
        self.assertEqual(sorted(int(k) for k in self.paints), list(range(108)))
        seen = set()
        for k, p in self.paints.items():
            self.assertEqual(str(p["id"]), k, "键与 id 不一致：" + k)
            self.assertEqual(p["key"], 664 + p["bike"], "存档键算错了：" + k)
            self.assertEqual(p["bit"], 1 << p["slot"], "位算错了：" + k)
            self.assertLess(p["slot"], 24, "存档里只有 24 位可用：" + k)
            self.assertNotIn((p["bike"], p["slot"]), seen, "同一辆车的同一款出现两次：" + k)
            seen.add((p["bike"], p["slot"]))
            self.assertTrue(p["en"], "涂装没有名字：" + k)
        self.assertEqual(len({p["bike"] for p in self.paints.values()}), 17,
                         "有涂装的车数变了（19 辆车，其中 2 辆没上过涂装）")
        self.assertGreaterEqual(sum(1 for p in self.paints.values() if p["cn"]), 60,
                               "官方中文名掉了一半以上，本地化表是不是没读上")

    def test_paint_is_not_a_category_any_more(self):
        """涂装编号不能留在 items 里当存档物品 —— 一半涂装编号同时是零件号。"""
        keys = [c["key"] for c in self.cat["categories"]]
        self.assertNotIn("paint", keys, "涂装不该再有分类：它不走 items2 的 id")
        for it in self.cat["items"].values():
            self.assertNotEqual(it["cat"], "paint", "还有条目被判成涂装")

    def test_grantable_paints_comes_from_the_catalog(self):
        allowed = acct.grantable_paints()
        self.assertEqual(len(allowed), 108, "可下发涂装数量不对，是不是没读到 items.json？")
        self.assertEqual(allowed[3]["key"], 664 + 7, "Riptide 是 BikeID 7，第 0 款")
        self.assertEqual(allowed[3]["slot"], 0)
        self.assertTrue(allowed[3]["name"])

    def test_value_encoding_keeps_the_equipped_paint(self):
        self.assertEqual(acct._paint_value(0, 0), 0x01000001)
        self.assertEqual(acct._paint_value(0x02000004, 0), 0x02000005)   # 当前装备不能被顶掉
        self.assertEqual(acct._paint_value(0x01000001, 0), 0x01000001)   # 重复下发不改值
        self.assertEqual(acct._paint_value(0x01000001, 3), 0x01000009)

    def test_grant_sets_the_bit_on_the_bike_word(self):
        self.write_save()                            # 存档里没有 664+ 的键
        res, err = acct.grant_items(PID, [], [3])    # id 3 = BikeID 7 第 0 款 → 键 671
        self.assertIsNone(err, "只发涂装被当成 bad-grant 了：%s" % err)
        self.assertEqual(res["paint_applied"][0]["key"], 671)
        self.assertEqual(res["paint_applied"][0]["before"], 0)
        self.assertEqual(res["grants"], 1, "只发涂装也要算一次下发，前端靠它拼提示")
        it = acct.load_progress_items(PID)
        self.assertEqual(it[671], 0x01000001)
        self.assertNotIn(3, it, "涂装自己的编号被当成 items2 的键写下去了")

    def test_grant_keeps_an_equipped_paint(self):
        self.write_save(items=(0, 457, 671, 0x02000004))   # 已拥有并装备第 2 款
        self.assertIsNone(acct.grant_items(PID, [], [3])[1])
        self.assertEqual(acct.load_progress_items(PID)[671], 0x02000005)

    def test_rejects_unknown_paint_without_writing(self):
        before = self.write_save()
        res, err = acct.grant_items(PID, [], [9999])
        self.assertIsNone(res)
        self.assertEqual(err, "not-grantable-paint:9999")
        self.assertEqual(acct.load_progress(PID)["content"]["items2"], before["content"]["items2"])

    def test_bad_paint_does_not_leave_the_item_written(self):
        before = self.write_save()
        res, err = acct.grant_items(PID, [{"item_id": 1, "amount": 10}], [9999])
        self.assertIsNone(res)
        self.assertEqual(acct.load_progress(PID)["content"]["items2"], before["content"]["items2"],
                         "涂装报错时物品已经写进去了")

    def test_undo_puts_the_paint_back(self):
        self.write_save()
        res, err = acct.grant_items(PID, [], [3])
        self.assertIsNone(err)
        self.assertIsNone(acct.restore_snapshot(PID, res["snapshot"])[1])
        self.assertNotIn(671, acct.load_progress_items(PID))

    def test_endpoint_carries_paints(self):
        token = self.login()
        self.write_save()
        handled, r = request("/__api/admin/grant", token=token, method="POST",
                             body={"profile": PID, "paints": [3]})
        self.assertTrue(handled)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json()["paint_applied"][0]["paint_id"], 3)
        self.assertEqual(acct.load_progress_items(PID)[671], 0x01000001)


class Blueprints(Base):
    """蓝图是**碎片计数器**：`id = (车号 + 72) * 5 + 4`，每辆车要求的片数不同。

    片数来自 `/conf/upgrades.txt` 的 `BP`；反汇编里 `MenuzBlueprintRenderer::init` 拿
    `BikeUpgrade::getUpgradeID(bikeID, 4)`（已拥有）与车记录 `[+0x58]`（需要）比大小，
    `blueprintComplete()` 就是两者相等。代号写错会把碎片写到别的物品上，所以钉死。
    """

    # 官方文案里写明的 7 辆（"Collect N to build"）+ 只在 upgrades.txt 里有数字的 5 辆。
    NEED = {374: 4, 379: 20, 404: 20, 414: 50, 419: 50, 429: 20,
            434: 30, 439: 20, 444: 50, 449: 50, 454: 50, 459: 50}
    # 有 LOCF 文案可交叉验证的 7 辆（英文文案里的 "Collect N to build"）。
    LOCF_SAID = {439: 20, 429: 20, 434: 30, 414: 50, 444: 50, 449: 50, 454: 50}

    @classmethod
    def setUpClass(cls):
        cls.cat = json.loads((ADMIN_DIR / "items.json").read_text(encoding="utf-8"))
        cls.items = cls.cat["items"]
        cls.bp = {int(k): v for k, v in cls.items.items() if v["cat"] == "blueprint"}

    def test_only_the_twelve_bikes_that_have_pieces_are_listed(self):
        self.assertEqual(len(self.bp), 12, "有碎片的车变多了/少了（重新跑生成器）")
        for iid, it in self.bp.items():
            self.assertEqual(it["id"], iid)
            self.assertEqual(iid, (it["bike"] + 72) * 5 + 4, "编号公式算错了：%d" % iid)
            self.assertTrue(1 <= it["bike"] <= 19, "车号越界：%d" % it["bike"])
            self.assertTrue(it["bike_en"].strip(), "没记车名：%d" % iid)
            self.assertTrue(it["en"].strip(), "没名字：%d" % iid)

    def test_needs_come_from_the_upgrade_table(self):
        self.assertEqual({i: it.get("need") for i, it in self.bp.items()}, self.NEED,
                         "每辆车要的碎片数变了（/conf/upgrades.txt 的 BP）")
        # 生成器漏读 upgrades.txt 时会退回统一值 —— 那就说明 BP 没读到。
        self.assertGreater(len(set(self.NEED.values())), 2, "片数全是同一个值，八成读错了表")

    def test_needs_agree_with_the_official_text(self):
        """官方文案 "Collect N to build" 里写明的 7 辆必须与 BP 一致（两路独立取证）。"""
        self.assertTrue(set(self.LOCF_SAID) <= set(self.NEED))
        for iid, n in self.LOCF_SAID.items():
            self.assertEqual(self.bp[iid].get("need"), n, "文案与 BP 不一致：%d" % iid)

    def test_bikes_without_pieces_are_reported_not_invented(self):
        src = self.cat["source"]
        self.assertEqual(len(src["blueprint_bikes"]), 12)
        self.assertEqual(len(src["no_blueprint_bikes"]), 7, "没碎片的车数是 7（19 辆里）")
        for name in src["no_blueprint_bikes"]:
            self.assertTrue(name.strip())
        # 缺碎片的车不能凭空出现在目录里：369/384/389/394/399/409/424 都不该有条目。
        for iid in (369, 384, 389, 394, 399, 409, 424):
            self.assertNotIn(iid, self.bp, "没碎片的车被造了编号：%d" % iid)

    def test_the_redlynx_copy_paste_name_is_gone(self):
        """374/379/439 的 NameId 被 RedLynx 写成了 Tango 的 Redlynx 涂装名，必须换掉。"""
        for iid in (374, 379, 439):
            it = self.items[str(iid)]
            self.assertEqual(it["cat"], "blueprint")
            self.assertNotIn("Redlynx", it["en"], "旧名字没换掉：" + it["en"])
            self.assertEqual(it.get("alias"), "Redlynx Paint Job for Tango",
                             "撞车/错名没留证：%s" % iid)
        for it in self.items.values():
            self.assertNotIn("Redlynx Paint Job", it["en"],
                             "Redlynx 涂装名还在蓝图里当名字：" + it["en"])

    def test_every_piece_is_grantable(self):
        allowed = acct.grantable_items()
        for iid in self.bp:
            self.assertIn(iid, allowed, "碎片不在白名单里，下发给它会 not-grantable：%d" % iid)
        self.assertIn(404, allowed, "Berserker 碎片（只在 giftbox 的紧凑形式里出现）漏了")


# ---------------------------------------------------------------- 运营参数
class _ParamOps(Base):
    """运营屏（午夜杯 / 碉堡）共用的夹具。

    ★ 这些端点**真的会改 tf_config.json / templates.json / config_audit.jsonl**。
      所以每个用例都把这三条路径指到临时目录 —— 顺带证明它们是可注入的，
      谁也不许把线上一份参数改了。
    """

    def setUp(self):
        super().setUp()
        d = Path(self.tmp.name)
        for name, rel in (("CONFIG_PATH", "tf_config.json"),
                          ("AUDIT_PATH", "config_audit.jsonl"),
                          ("TEMPLATES_PATH", "templates.json")):
            p = patch.object(srv, name, str(d / rel))
            p.start()
            self.addCleanup(p.stop)
        srv._CONFIG_CACHE["mtime"] = None
        srv._CONFIG_CACHE["data"] = None
        srv._TRACK_CACHE["mtime"] = None
        srv._TRACK_CACHE["rows"] = []
        self.token = self.login()

    # ---------------------------------------------------------------- 工具
    def get(self, path="/__api/admin/weekly", query=""):
        handled, r = request(path, token=self.token, query=query)
        self.assertTrue(handled, path)
        self.assertEqual(r.status, 200, r.text)
        return r.json()

    def post(self, path, body):
        handled, r = request(path, token=self.token, method="POST", body=body)
        self.assertTrue(handled, path)
        return r

    def config_file(self):
        """磁盘上的 tf_config.json 原文 —— 端点必须真写盘，不是只改内存。"""
        try:
            with open(srv.CONFIG_PATH, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except OSError:
            return {}

    def write_config(self, node):
        """摆一份"线上已有的配置"，用来测正常路径（键本来就在文件里）。"""
        with open(srv.CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(node, fp)
        srv._CONFIG_CACHE["mtime"] = None
        srv._CONFIG_CACHE["data"] = None
        return node


class WeeklyOps(_ParamOps):
    """`/__api/admin/weekly` · `/__api/admin/undo` · `/__api/admin/templates`。"""

    def set_fields(self, fields, expect=200):
        r = self.post("/__api/admin/weekly", {"fields": fields})
        self.assertEqual(r.status, expect, r.text)
        return r

    # ---------------------------------------------------------------- 读
    def test_get_hands_out_everything_the_screen_needs(self):
        j = self.get()
        for key in ("config", "status", "tracks", "templates", "audit"):
            self.assertIn(key, j)
        self.assertEqual(j["config"]["window_days"], 7)
        self.assertEqual(j["config"]["left_retry_times"], 3)
        self.assertEqual(j["config"]["reward_ids"], {})
        self.assertFalse(j["status"]["experimental"], "默认 7 天不该标实验性")
        self.assertEqual(j["status"]["week_end"] - j["status"]["week_start"], 7 * 86400)
        self.assertEqual(j["status"]["retry_limit"], 3)

    def test_status_warns_when_the_track_has_no_ghost(self):
        """★ 用户实测的坑：`track_id` 换成本服没有幽灵的赛道 ⇒ 玩家卡在「加入午夜杯」。

        此时服务端只能给出 `replay_id=0`，客户端反复去要 `ghost/0/payload`（404），界面看起来
        就是转圈/回到加入屏。现状卡必须先把「这条赛道几个幽灵 / 榜上几行真数据」摆出来，并在
        为 0 时明确警告，而不是让人自己猜。
        """
        self.write_config({"weekly": {"track_id": 1258}})
        s = self.get()["status"]
        self.assertEqual(s["track_id"], 1258)
        self.assertEqual(s["ghosts"], 0)
        self.assertEqual(s["board_rows"], 0)
        self.assertTrue(any("幽灵" in w["cn"] for w in s["warnings"]),
                        "空赛道必须警告：%r" % (s["warnings"],))
        for w in s["warnings"]:
            self.assertTrue(w["cn"] and w["en"], w)

    def test_status_alone_writes_nothing(self):
        """现状卡只是看一眼，不该在配置或审计里留下东西。"""
        self.get()
        self.assertEqual(self.config_file(), {})
        self.assertEqual(srv.audit_log(20), [])

    # ---------------------------------------------------------------- 写
    def test_post_one_key_writes_file_and_records_audit(self):
        self.write_config({"weekly": {"left_retry_times": 3}})
        j = self.set_fields({"left_retry_times": 5}).json()
        first = j["applied"][0]
        self.assertEqual(first["key"], "left_retry_times")
        self.assertEqual((first["before"], first["after"]), (3, 5))
        self.assertTrue(first["audit"], "没给「撤销」留审计编号")
        self.assertEqual(j["config"]["left_retry_times"], 5)
        self.assertEqual(self.config_file()["weekly"]["left_retry_times"], 5)
        rec = j["audit"][0]
        self.assertEqual((rec["kind"], rec["path"], rec["before"], rec["after"]),
                         ("weekly", ["weekly", "left_retry_times"], 3, 5))

    def test_audit_says_when_the_key_was_not_in_the_file(self):
        """文件里本来没这个键 ⇒ 记录要如实说"新增"，撤销就是删掉它（回代码默认值）。"""
        self.set_fields({"left_retry_times": 5})
        rec = self.get()["audit"][0]
        self.assertFalse(rec["existed"])
        self.assertIsNone(rec["before"])

    def test_post_is_all_or_nothing(self):
        """一半字段合法、一半非法 ⇒ 一个都不改（改一半最难解释）。"""
        r = self.set_fields({"left_retry_times": 7, "track_id": 99999999}, expect=400)
        self.assertEqual(r.json()["error"], "range:track_id:1-1000000")
        self.assertEqual(self.config_file(), {}, "非法请求居然写盘了")
        self.assertEqual(srv.weekly_values()["left_retry_times"], 3)

    def test_post_rejects_junk_and_translates_the_message(self):
        cases = [({"nope": 1}, "unknown-key:nope"),
                 ({"track_id": "abc"}, "bad-value:track_id"),
                 ({"reward_slots": 9}, "range:reward_slots:1-8"),
                 ({"window_days": 0}, "range:window_days:1-30"),
                 ({"reward_ids": {"iron": [1]}}, "bad-tier:iron"),
                 ({"reward_ids": {"gold": [99]}}, "bad-pool:gold")]
        for fields, code in cases:
            r = self.set_fields(fields, expect=400)
            self.assertEqual(r.json()["error"], code, fields)
            msg = r.json()["message"]
            self.assertTrue(msg, "错误没翻成中文：" + code)
            self.assertNotIn(":", msg, "界面不该看到错误码：" + msg)
        self.assertEqual(self.config_file(), {})

    def test_null_removes_the_key_and_the_default_comes_back(self):
        self.set_fields({"window_days": 14})
        self.assertEqual(self.get()["status"]["window_days"], 14)
        self.assertTrue(self.get()["status"]["experimental"], "非 7 天要标实验性")
        self.set_fields({"window_days": None})
        self.assertNotIn("window_days", self.config_file().get("weekly", {}))
        self.assertEqual(self.get()["config"]["window_days"], 7)
        self.assertFalse(self.get()["status"]["experimental"])

    def test_reward_pools_keep_only_named_tiers(self):
        r = self.set_fields({"reward_ids": {"platinum": [3, 8], "wood": []}})
        self.assertEqual(r.json()["config"]["reward_ids"], {"platinum": [3, 8]})
        # 空列表 = 这一档没指定 ⇒ 走内置规则，配置里不该留一个空数组
        self.assertNotIn("wood", self.config_file()["weekly"]["reward_ids"])

    # ---------------------------------------------------------------- 撤销
    def test_undo_restores_the_previous_value(self):
        self.set_fields({"cooldown_seconds": 60})          # 先让它变成"已存在的键"
        aid = self.set_fields({"cooldown_seconds": 120}).json()["applied"][0]["audit"]
        r = self.post("/__api/admin/undo", {"id": aid})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json()["restored"], 60)
        self.assertEqual(srv.weekly_values()["cooldown_seconds"], 60)
        # 对**同一条**记录再撤一次是幂等的（撤的是同一个 before）
        self.post("/__api/admin/undo", {"id": aid})
        self.assertEqual(srv.weekly_values()["cooldown_seconds"], 60)

    def test_undo_of_a_new_key_deletes_it(self):
        """记录里说"这个键本来是新增的" ⇒ 撤销要删掉它，让代码默认值重新生效。"""
        aid = self.set_fields({"fake_field": 30}).json()["applied"][0]["audit"]
        r = self.post("/__api/admin/undo", {"id": aid})
        self.assertEqual(r.status, 200, r.text)
        self.assertIsNone(r.json()["restored"])
        self.assertNotIn("fake_field", self.config_file().get("weekly", {}))
        self.assertEqual(srv.weekly_values()["fake_field"], 0)

    def test_undo_rejects_bad_ids(self):
        r = self.post("/__api/admin/undo", {"id": "0-nope"})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["error"], "not-found")
        r = self.post("/__api/admin/undo", {})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.json()["error"], "bad-id")

    # ---------------------------------------------------------------- 模板
    def test_templates_round_trip(self):
        self.set_fields({"left_retry_times": 5, "reward_ids": {"gold": [7]}})
        r = self.post("/__api/admin/templates",
                      {"page": "weekly", "action": "save", "name": "高难周"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json()["templates"][0]["name"], "高难周")
        self.assertNotIn("values", r.json()["templates"][0], "列表不该带整份快照")

        # 复制：界面拿不到源模板的 values，所以只能由服务端读源份来存
        r = self.post("/__api/admin/templates",
                      {"page": "weekly", "action": "copy", "name": "高难周",
                       "new_name": "高难周 副本"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json()["values"]["left_retry_times"], 5)
        listed = self.get("/__api/admin/templates", "page=weekly")
        self.assertEqual(set(t["name"] for t in listed["templates"]["weekly"]),
                         {"高难周", "高难周 副本"})
        self.assertEqual(listed["current"]["weekly"]["left_retry_times"], 5)

        # 改回默认再整页套用 ⇒ 快照把两个键都写回来，并且每个键都能单独撤销
        self.set_fields({"left_retry_times": 3, "reward_ids": None})
        r = self.post("/__api/admin/templates",
                      {"page": "weekly", "action": "apply", "name": "高难周", "parts": "all"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(srv.weekly_values()["left_retry_times"], 5)
        self.assertEqual(srv.weekly_values()["reward_ids"], {"gold": [7]})
        self.assertEqual({rec["kind"] for rec in self.get()["audit"]}, {"weekly"},
                         "套用必须走同一条审计路径")

        # 只套奖励：参数键稳住不动
        self.set_fields({"left_retry_times": 4})
        self.post("/__api/admin/templates",
                  {"page": "weekly", "action": "apply", "name": "高难周", "parts": "rewards"})
        vals = srv.weekly_values()
        self.assertEqual(vals["left_retry_times"], 4)
        self.assertEqual(vals["reward_ids"], {"gold": [7]})

    def test_template_rename_and_delete(self):
        self.post("/__api/admin/templates", {"page": "weekly", "action": "save", "name": "a"})
        r = self.post("/__api/admin/templates",
                      {"page": "weekly", "action": "rename", "name": "a", "new_name": "b"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual([t["name"] for t in r.json()["templates"]], ["b"])
        r = self.post("/__api/admin/templates",
                      {"page": "weekly", "action": "delete", "name": "b"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json()["templates"], [])

    def test_template_errors(self):
        cases = [({"page": "nope", "action": "save", "name": "x"}, "bad-page"),
                 ({"page": "weekly", "action": "nope", "name": "x"}, "bad-action"),
                 ({"page": "weekly", "action": "save", "name": "  "}, "bad-name"),
                 ({"page": "weekly", "action": "apply", "name": "missing"}, "not-found"),
                 ({"page": "weekly", "action": "copy", "name": "missing",
                   "new_name": "y"}, "not-found")]
        for body, code in cases:
            r = self.post("/__api/admin/templates", body)
            self.assertEqual(r.status, 400, body)
            self.assertEqual(r.json()["error"], code, body)
            self.assertTrue(r.json()["message"], code)
        # 存两次同名是覆盖；复制到已存在的名字才算冲突
        self.post("/__api/admin/templates", {"page": "weekly", "action": "save", "name": "dup"})
        r = self.post("/__api/admin/templates",
                      {"page": "weekly", "action": "copy", "name": "dup", "new_name": "dup"})
        self.assertEqual(r.json()["error"], "exists")

    # ---------------------------------------------------------------- 赛道目录
    def test_track_catalog_reads_the_levels_section(self):
        """赛道下拉：有 levels 段就给名字；没有就空表（界面退化成手填，绝不猜名字）。"""
        # 真目录里现在有 levels 段（382 条赛道），所以「没有那段」这条路要拿临时目录试。
        self.assertTrue(srv.track_catalog())
        p = patch.object(srv, "_TRACK_CATALOG_PATH", str(Path(self.tmp.name) / "items.json"))
        p.start()
        self.addCleanup(p.stop)

        def catalog_with(doc):
            with open(srv._TRACK_CATALOG_PATH, "w", encoding="utf-8") as fp:
                json.dump(doc, fp)
            srv._TRACK_CACHE["mtime"] = None
            srv._TRACK_CACHE["rows"] = []
            return srv.track_catalog()

        self.assertEqual(catalog_with({"items": {}}), [])
        self.assertEqual(catalog_with({"levels": {"1042": {"en": "Docks", "cn": "码头"},
                                                 "1041": {"cn": "训练场"}}}),
                         [{"id": 1041, "name": "训练场", "name_cn": "训练场"},
                          {"id": 1042, "name": "Docks", "name_cn": "码头"}])
        self.assertEqual(self.get()["tracks"], srv.track_catalog())


# ---------------------------------------------------------------- 文案
# ---------------------------------------------------------------- 碉堡（PVP 运营）
class Bunker(_ParamOps):
    """`/__api/admin/bunker`，以及它复用的 `/__api/admin/undo` · `/__api/admin/templates`。

    碉堡是跟午夜杯**各自独立**的第二张运营屏：字段表在服务端（`_BUNKER_FIELDS`），
    前端照着 `kind` 画控件，写入仍然一条审计 + 一次撤销。
    """

    CARDS = ["now", "season", "duration", "rank", "match", "chips", "rewards", "templates"]
    KINDS = ("int", "float", "bool", "text", "banner", "stars", "ids", "rewards", "products")

    def bget(self):
        return self.get("/__api/admin/bunker")

    def bset(self, fields, expect=200):
        r = self.post("/__api/admin/bunker", {"fields": fields})
        self.assertEqual(r.status, expect, r.text)
        return r

    # ---------------------------------------------------------------- 读
    def test_get_hands_out_every_card_and_field(self):
        """界面要的东西一次给全：8 张卡 + 服务端字段表 + 现状 + 三个目录 + 模板 + 审计。"""
        j = self.bget()
        for key in ("cards", "fields", "values", "status", "tracks", "rewards", "bikes",
                    "templates", "audit"):
            self.assertIn(key, j)
        self.assertEqual([c["id"] for c in j["cards"]], self.CARDS)
        self.assertTrue(all(c["cn"] and c["en"] for c in j["cards"]))
        self.assertEqual({f["key"] for f in j["fields"]}, set(srv._BUNKER_KEYS))
        self.assertEqual(sorted(j["values"]), sorted(srv._BUNKER_KEYS))
        ids = {c["id"] for c in j["cards"]}
        for f in j["fields"]:
            self.assertIn(f["card"], ids, f["key"])
            self.assertIn(f["kind"], self.KINDS, f["key"])
            self.assertTrue(f["cn"] and f["en"], "字段标签必须中英双语（不进 i18n）：" + f["key"])
            self.assertIn("now", f, f["key"])
        # 现状卡是只读、模板卡是列表：都没有表单字段
        self.assertEqual([f["key"] for f in j["fields"] if f["card"] == "now"], [])
        self.assertEqual([f["key"] for f in j["fields"] if f["card"] == "templates"], [])

    def test_status_alone_writes_nothing(self):
        self.bget()
        self.assertEqual(self.config_file(), {})
        self.assertEqual(srv.audit_log(20), [])

    def test_status_reports_the_season_and_warns(self):
        s = self.bget()["status"]
        self.assertGreaterEqual(s["season"], 1)
        self.assertEqual(s["display_id"], s["season"])            # 默认显示偏移 0
        self.assertEqual(s["end"] - s["start"], s["duration_days"] * 86400)
        self.assertTrue(s["warnings"], "现状卡必须带上警示")
        for w in s["warnings"]:
            self.assertTrue(w["cn"] and w["en"])
        for p in s["players"]:                                     # 玩家档案表
            self.assertEqual(set(p), {"profile", "rank", "star", "season", "this_season",
                                      "golden_ticket", "win_streak", "chips"})
            self.assertIsInstance(p["rank"], int)
            self.assertIsInstance(p["this_season"], bool)

    def test_catalogs_come_from_the_item_catalog(self):
        """奖励下拉 = 物品表 `server/admin/items.json` 的**全部** 309 个奖励编号，按类别分组。

        2026-10-06 真机实验（覆盖包改了 `/conf/pvp_match_rewards.txt` 再挂载）推翻了「填表外
        编号一定变毛驴轮胎」的旧说法：兜底奖励是**该编号自己声明的 `Fallback`**，玩家**已经
        拥有**这件物品时才画（`257`/`220` 行都带 `Fallback:221` = Doughnut）。所以现在不拦
        表外编号，只把它们标出来（`official=false`），并在界面上写清显示规则。
        """
        j = self.bget()
        self.assertEqual(len(j["tracks"]), len(srv.track_catalog()))
        self.assertTrue(all({"id", "name"} <= set(b) for b in j["bikes"]))
        cat = j["rewards"]
        items = json.loads((ADMIN_DIR / "items.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cat), len(items["rewards"]), "下拉必须是物品表全量")
        self.assertEqual(len(srv._PVP_SPECIAL_IDS), 43)
        # 官方 43 个必须都在，而且恰好标出 43 个
        official = {r["id"] for r in cat if r["official"]}
        self.assertEqual(official, set(srv._PVP_SPECIAL_IDS))
        # 按类别分组：同类别必须连续（下拉用 <optgroup> 分组）
        cats = [r["cat"] for r in cat]
        self.assertEqual(cats, sorted(cats, key=lambda c: srv._REWARD_CAT_ORDER.index(c)))
        self.assertTrue(all(r["cat_cn"] and r["name"] for r in cat))
        self.assertTrue(all(isinstance(r["item_id"], int) for r in cat))
        # 用户报的「加了喷漆结果是毛驴轮胎」：205/257 这类不在官方 43 个里，但现在允许填
        for rid in (205, 257, 258, 259, 221):
            self.assertIn(rid, {r["id"] for r in cat})
            self.assertNotIn(rid, srv._PVP_SPECIAL_IDS)

    def test_status_players_are_read_only(self):
        """现状卡里的玩家档案只是看一眼：不许写配置，也不许在审计里留东西。"""
        s = self.bget()["status"]
        for p in s["players"]:
            self.assertTrue(p["profile"])
        self.assertEqual(self.config_file(), {})
        self.assertEqual(srv.audit_log(20), [])

    # ---------------------------------------------------------------- 写
    def test_int_field_round_trips_and_says_what_changed(self):
        self.write_config({"matchmaking": {"match_duration_seconds": 21600}})
        j = self.bset({"matchmaking.match_duration_seconds": 7200}).json()
        first = j["applied"][0]
        self.assertEqual(first["key"], "matchmaking.match_duration_seconds")
        self.assertEqual((first["before"], first["after"]), (21600, 7200))
        self.assertTrue(first["audit"], "没给「撤销」留审计编号")
        self.assertEqual(self.config_file()["matchmaking"]["match_duration_seconds"], 7200)
        self.assertEqual(j["values"]["matchmaking.match_duration_seconds"], 7200)
        rec = j["audit"][0]
        self.assertEqual((rec["kind"], rec["path"]),
                         ("bunker", ["matchmaking", "match_duration_seconds"]))

    def test_friendly_match_duration_is_configurable_now(self):
        """原来 `_pvp_season()` 里写死 3600，现在必须是配置键。"""
        j = self.bset({"matchmaking.friendly_match_duration": 1800}).json()
        self.assertEqual(j["values"]["matchmaking.friendly_match_duration"], 1800)
        self.assertEqual(self.config_file()["matchmaking"]["friendly_match_duration"], 1800)

    def test_apply_is_all_or_nothing(self):
        r = self.bset({"season.duration_days": 400, "chips.max": 1}, expect=400)
        self.assertEqual(r.json()["error"], "range:season.duration_days:1-365")
        self.assertEqual(self.config_file(), {}, "非法请求居然写盘了")
        self.assertEqual(srv.bunker_values()["season.duration_days"], 30)

    def test_rejects_junk_and_translates_the_message(self):
        cases = [({"nope": 1}, "unknown-key:nope"),
                 ({"season.duration_days": 400}, "range:season.duration_days:1-365"),
                 ({"season.duration_days": "abc"}, "bad-value:season.duration_days"),
                 ({"season.duration_days": 3.5}, "bad-value:season.duration_days"),
                 ({"season.title_text": "a|b"}, "bad-pipe"),
                 ({"season.banner_path": "/etc/passwd"}, "bad-banner"),
                 ({"season.banner_path": "/pvp_banner/x.jpg"}, "bad-banner"),
                 ({"season.star_array": [1, 2, 3]}, "bad-stars"),
                 ({"season.star_array": [3] * 25 + [101]}, "range:season.star_array:0-100"),
                 ({"season.rewards": []}, "bad-rewards"),
                 ({"season.rewards": [{"rank": 30, "item_id": 1, "amount": 1}]},
                  "range:season.rewards(名次):0-25"),
                 ({"season.rewards": [{"rank": 1, "item_id": 7, "amount": 1}]},
                  "bad-reward-item:7"),
                 # 奖励编号只挡「物品表里查不到」的（205/257 这些现在能填，见下一条用例）
                 ({"season.rewards": [{"rank": 1, "item_id": 145, "amount": 999}]},
                  "bad-special:999"),
                 ({"season.rewards": [{"rank": 1, "item_id": 145, "amount": 12345}]},
                  "bad-special:12345"),
                 ({"season.product_list": "nope"}, "bad-products"),
                 ({"matchmaking.enabled": "maybe"}, "bad-value:matchmaking.enabled")]
        for fields, code in cases:
            r = self.bset(fields, expect=400)
            self.assertEqual(r.json()["error"], code, fields)
            msg = r.json()["message"]
            self.assertTrue(msg, "错误没翻成中文：" + code)
            self.assertNotIn(":", msg, "界面不该看到错误码：" + msg)
        self.assertEqual(self.config_file(), {})

    def test_bool_and_float_are_coerced(self):
        j = self.bset({"matchmaking.enabled": 0, "season.chip_equation_x": "0.25"}).json()
        self.assertIs(j["values"]["matchmaking.enabled"], False)
        self.assertEqual(j["values"]["season.chip_equation_x"], 0.25)
        self.assertIs(self.config_file()["matchmaking"]["enabled"], False)

    def test_null_removes_the_key_and_the_default_comes_back(self):
        self.bset({"season.display_offset": 5})
        self.assertEqual(self.config_file()["season"]["display_offset"], 5)
        self.bset({"season.display_offset": None})
        self.assertNotIn("display_offset", self.config_file().get("season", {}))
        self.assertEqual(self.bget()["values"]["season.display_offset"], 0)

    def test_null_on_a_key_that_was_never_set_leaves_no_audit(self):
        """本来就是默认值 ⇒ 不该留下一条"什么都没改"的审计。"""
        j = self.bset({"season.display_offset": None}).json()
        self.assertIsNone(j["applied"][0]["audit"])
        self.assertEqual(self.config_file(), {})

    def test_star_array_needs_25_cells_and_keeps_25(self):
        j = self.bset({"season.star_array": [3] * 24 + [7]}).json()
        self.assertEqual(len(j["values"]["season.star_array"]), 25)
        self.assertEqual(j["values"]["season.star_array"][-1], 7)
        self.assertEqual(len(self.config_file()["season"]["star_array"]), 25)
        # 客户端原表是 26 格（末尾一格给 Legend），收得下，但只存 25 格
        j = self.bset({"season.star_array": [3] * 25 + [9]}).json()
        self.assertEqual(j["values"]["season.star_array"], [3] * 25)

    def test_every_reward_id_in_the_item_table_is_accepted(self):
        """奖励编号只挡「物品表里查不到」的，物品表里有的一律放行（含官方 43 个之外）。

        旧版按客户端原表 `PVPMatchSpecialRewards` 的 43 个编号做白名单，理由是「表外编号会塌成
        占位物」。2026-10-06 真机实验推翻了它：把覆盖包里的 `220` 改成指向 Stallion 图纸后，
        只有**已经拥有**该物品的账号画兜底物（`Fallback:221` = 甜甜圈），没拥有的账号正常显示
        ⇒ 显示什么由「玩家有没有」决定，与编号是否在原表里无关。所以白名单撤掉，只留物品表校验。
        """
        for good in (202, 203, 205, 220, 221, 257, 258, 259, 20000, 20040, 20048):
            j = self.bset({"season.rewards": [{"rank": 1, "item_id": 145, "amount": good}]}).json()
            self.assertEqual(j["values"]["season.rewards"],
                             [{"rank": 1, "item_id": 145, "amount": good}])
        # 物品表（`items.json` 的 rewards）里没有的编号：客户端解析不出来，仍然 400
        for bad in (0, 999, 12345, 99999):
            r = self.bset({"season.rewards": [{"rank": 1, "item_id": 145, "amount": bad}]},
                          expect=400)
            self.assertEqual(r.json()["error"], "bad-special:%d" % bad)
            self.assertIn("物品表", r.json()["message"])

    def test_track_ids_keep_three_and_dedupe(self):

        j = self.bset({"matchmaking.track_ids": [1041, 1041, 1001, 1002, 1003]}).json()
        self.assertEqual(j["values"]["matchmaking.track_ids"], [1041, 1001, 1002])
        self.assertEqual(self.config_file()["matchmaking"]["track_ids"], [1041, 1001, 1002])

    def test_rewards_merge_coins_and_gems_but_refuse_a_second_special(self):
        j = self.bset({"season.rewards": [{"rank": 1, "item_id": 1, "amount": 10},
                                          {"rank": 1, "item_id": 1, "amount": 5},
                                          {"rank": 0, "item_id": 2, "amount": 3}]}).json()
        self.assertEqual(j["values"]["season.rewards"],
                         [{"rank": 0, "item_id": 2, "amount": 3},
                          {"rank": 1, "item_id": 1, "amount": 15}])
        self.assertEqual(self.config_file()["season"]["rewards"], j["values"]["season.rewards"])
        # 特殊奖（item 145 的 amount 是客户端原表的 RewardID）同档只能一条
        r = self.bset({"season.rewards": [{"rank": 1, "item_id": 145, "amount": 220},
                                          {"rank": 1, "item_id": 145, "amount": 203}]}, expect=400)
        self.assertEqual(r.json()["error"], "dup-special:1")
        # 普通奖励表照样能存下特殊奖
        j = self.bset({"season.rewards": [{"rank": 1, "item_id": 145, "amount": 220}]}).json()
        self.assertEqual(j["values"]["season.rewards"],
                         [{"rank": 1, "item_id": 145, "amount": 220}])

    def test_products_round_trip(self):
        j = self.bset({"season.product_list": [{"product_id": "chip_shop.goldentickets",
                                                "amount": 3}]}).json()
        self.assertEqual(j["values"]["season.product_list"],
                         [{"product_id": "chip_shop.goldentickets", "amount": 3}])
        self.assertEqual(self.config_file()["season"]["product_list"],
                         [{"product_id": "chip_shop.goldentickets", "amount": 3}])
        j = self.bset({"season.product_list": []}).json()
        self.assertEqual(j["values"]["season.product_list"], [])

    def test_banner_path_must_point_into_the_served_folder(self):
        j = self.bset({"season.banner_path": "/pvp_banner/season.png"}).json()
        self.assertEqual(j["values"]["season.banner_path"], "/pvp_banner/season.png")
        # 空字符串 = 回到内置占位图，允许
        j = self.bset({"season.banner_path": ""}).json()
        self.assertEqual(j["values"]["season.banner_path"], "")

    def test_advance_button_moves_the_window_one_round(self):
        """「推进到下一赛季」= `season.advance` 加一，内部届号跟着挪一轮，显示编号不动。"""
        self.assertEqual(self.bget()["values"]["season.advance"], 0)
        before = srv._pvp_season_window()
        self.bset({"season.advance": 1})
        after = srv._pvp_season_window()
        self.assertEqual(after[0], before[0] + 1)
        self.assertEqual(after[2] - after[1], before[2] - before[1])
        self.assertEqual(self.bget()["values"]["season.advance"], 1)
        # 显示编号只由 display_offset 决定
        self.bset({"season.display_offset": 3})
        self.assertEqual(self.bget()["status"]["display_id"],
                         self.bget()["status"]["season"] + 3)

    # ---------------------------------------------------------------- 撤销 / 模板
    def test_undo_restores_the_previous_value(self):
        self.bset({"season.display_offset": 5})
        aid = self.bset({"season.display_offset": 9}).json()["applied"][0]["audit"]
        r = self.post("/__api/admin/undo", {"id": aid})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.bget()["values"]["season.display_offset"], 5)

    def test_templates_are_per_page(self):
        """两个页面的模板互不可见（GET 按页筛，返回结构是 {页: [模板]}）。"""
        self.post("/__api/admin/templates", {"page": "bunker", "action": "save", "name": "b1"})
        self.post("/__api/admin/templates", {"page": "weekly", "action": "save", "name": "w1"})
        self.assertEqual([p["id"] for p in self.get("/__api/admin/templates")["pages"]],
                         ["weekly", "bunker"])
        b = self.get("/__api/admin/templates", query="page=bunker")["templates"]
        w = self.get("/__api/admin/templates", query="page=weekly")["templates"]
        self.assertEqual([t["name"] for t in b["bunker"]], ["b1"])
        self.assertEqual([t["name"] for t in w["weekly"]], ["w1"])
        self.assertNotIn("weekly", b)

    def test_template_apply_brings_the_saved_values_back(self):
        self.bset({"season.display_offset": 5, "matchmaking.match_duration_seconds": 7200})
        self.post("/__api/admin/templates", {"page": "bunker", "action": "save", "name": "s1"})
        self.bset({"season.display_offset": 9, "matchmaking.match_duration_seconds": 3600})
        r = self.post("/__api/admin/templates",
                      {"page": "bunker", "action": "apply", "name": "s1", "parts": "all"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.bget()["values"]["season.display_offset"], 5)
        self.assertEqual(self.bget()["values"]["matchmaking.match_duration_seconds"], 7200)

    def test_page_hooks_cover_both_screens(self):
        """两个页面各自独立：模板 / 撤销端点全靠这张表知道「这页管哪些键」。"""
        self.assertEqual(sorted(srv._PAGE_HOOKS), ["bunker", "weekly"])
        for page, hook in srv._PAGE_HOOKS.items():
            self.assertTrue(hook["label"], page)
            self.assertTrue(hook["keys"], page)
            self.assertTrue(callable(hook["values"]) and callable(hook["apply"]), page)
        b = srv._PAGE_HOOKS["bunker"]
        self.assertEqual(b["values"], srv.bunker_values)
        self.assertEqual(b["apply"], srv.admin_bunker_apply)
        # 「只套用奖励方案」看 reward_keys；普通套用（keys）不动奖励表
        self.assertEqual(set(b["reward_keys"]), set(srv._BUNKER_REWARD_KEYS))
        self.assertEqual(set(b["keys"]) | set(b["reward_keys"]), set(srv._BUNKER_KEYS))
        self.assertFalse(set(b["keys"]) & set(b["reward_keys"]))


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
        # 折叠清单里的物品名来自 items.json、不走 i18n，所以「t('前缀' + 变量)」这种动态键
        # 现在一条都没有了。断言它消失，是为了别让这条检查悄悄变成空断言。
        self.assertEqual(dyn, set(), "又有动态键了？这里需要逐条展开核对：" + str(sorted(dyn)))
        # 键名放在表里、t() 收的是变量（或由 JS 直接拼）的，必须单独核一遍，
        # 否则删掉一个 i18n 键测试不会响。
        for k in ("grant.pvpGolden", "grant.pvpChips",
                  "grant.list.search", "grant.list.selected", "grant.list.unlock",
                  "grant.list.unverified", "grant.list.empty", "grant.modeHint",
                  "saves.coins", "saves.gems",
                  # 午夜杯运营屏：表单标签 / 档位名 / 冷却预设都放在表里、t() 收变量
                  "weekly.f.track", "weekly.f.board", "weekly.f.fake", "weekly.f.base",
                  "weekly.f.fast", "weekly.f.slow", "weekly.f.retry", "weekly.f.cool",
                  "weekly.f.offset", "weekly.f.slots", "weekly.f.days", "weekly.f.rewardIds",
                  "weekly.tier.platinum", "weekly.tier.gold", "weekly.tier.silver",
                  "weekly.tier.bronze", "weekly.tier.wood",
                  "weekly.rules.p1", "weekly.rules.p10", "weekly.rules.p1h", "weekly.rules.p6h"):
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
