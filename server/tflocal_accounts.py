#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trials Frontier —— 本地账号系统 + 存档持久化

设计目标（对应用户的三点要求）：
  1. 账号和密码算凭据：客户端发过来的 Authorization 头里带 base64("用户名:密码")，
     我们解出来做真正的校验（首次登录自动注册）。
  2. 服务器记住账号：账号、会话票据、每个账号的 profileId 都落盘。
  3. 留下赛道信息 / 存档：客户端每隔一段时间 POST 一次
     /public/playerprogress/v1/progress，body 里就是完整存档
     （items2 / highscores2 / achievements2 / checksum …），我们原样存档。

数据全部放在 server/data/ 下：
    data/accounts.json        账号表
    data/sessions.json        会话票据 -> 账号
    data/save/<pid>/latest.json   该账号最近一次上传的存档
    data/save/<pid>/history/<ts>.json   历史快照（保留最近 N 份）
    data/ghosts/<track>/<name>.bin      内置/抓取到的幽灵文件（原始字节）
    data/ghosts/index.json              幽灵仓库索引（contentId -> 元数据）
    data/ghosts/store/<id>.bin          客户端上传的幽灵二进制
    data/ghosts/replays.json            replay_id 登记（谁在哪条赛道跑了多少）

授权头格式（实测）：
    Authorization: Ubi_v1 t=<base64("user:pass")>          ← 用户名密码登录
    Authorization: UbiMobile_v1 t=<base64("devid:ticket:x")>  ← 设备静默登录
"""

import base64
import binascii
import hashlib
import json
import os
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ACCOUNTS = os.path.join(DATA, "accounts.json")
SESSIONS = os.path.join(DATA, "sessions.json")
DEVICES = os.path.join(DATA, "devices.json")
# 长期凭据（育碧叫 rememberMeTicket）。跟 sessions.json 分开存，
# 因为 sessions 只保留最近 200 张会被裁剪，长期凭据不能被裁掉。
REMEMBER = os.path.join(DATA, "remember.json")
# 客户端（IP / 设备 id）-> 账号。用途见 resolve_identity()。
BINDINGS = os.path.join(DATA, "bindings.json")
SAVE_DIR = os.path.join(DATA, "save")
GHOST_DIR = os.path.join(DATA, "ghosts")

# 匿名/设备登录沿用原来那个固定的 profileId，
# 这样升级服务器不会让已在用的本地存档「换人」而丢失进度。
ANON_PROFILE_ID = "11111111-1111-1111-1111-111111111111"
ANON_USER_ID = "11111111-1111-1111-1111-111111111111"
ANON_SPACE_ID = "22222222-2222-2222-2222-222222222222"
ANON_SESSION_ID = "33333333-3333-3333-3333-333333333333"
# 历史遗留的匿名票据：老的客户端会把这张票缓存下来一直用，必须继续认它，
# 否则老设备的存档上报会 401（真机上踩过这个坑）。
ANON_TICKET = "tf-local-ticket-0001"

SAVE_HISTORY_MAX = 20
_LOCK = threading.RLock()


# ------------------------------------------------------------------ 基础 IO
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _store(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _iso(ts):
    """unix 秒 -> 本地可读时间串；空值返回 None。"""
    if not ts:
        return None
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
    except Exception:
        return None


def _hash_pw(username, password, salt):
    h = hashlib.sha256()
    h.update(salt.encode("utf-8"))
    h.update(username.lower().encode("utf-8"))
    h.update(b"\x00")
    h.update(password.encode("utf-8"))
    return h.hexdigest()


def _det_id(username):
    """用户名 -> 固定 UUID（同一个名字永远得到同一个 profileId）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "trialsfrontier-local:" + username.lower()))


def _device_id_uuid(device_id):
    """设备 id -> 固定 UUID。不同设备不登录也各占一个槽。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "trialsfrontier-device:" + str(device_id).lower()))


# ------------------------------------------------------------------ 授权头解析
def parse_authorization(headers):
    """返回 dict(kind, username, password, device_id, ticket, raw)。

    kind: 'basic'（用户名密码）/ 'device'（设备静默）/ 'bearer'（只带票据）/ None

    ★ 实测客户端会用**两种**写法送用户名密码：
        Authorization: Basic <base64("用户名:口令")>       ← 登录界面走这个（标准 HTTP Basic）
        Authorization: Ubi_v1 t=<base64("用户名:口令")>    ← 另一种写法
      两个都要认，否则登录会被当成匿名兜底（真机上踩过这个坑）。
    """
    raw = ""
    for k, v in (headers.items() if hasattr(headers, "items") else []):
        if k.lower() == "authorization":
            raw = v
            break
    if not raw:
        return {"kind": None, "raw": ""}
    parts = raw.split(None, 1)
    scheme = parts[0] if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    token = rest[2:].strip() if rest[:2].lower() == "t=" else rest
    if not token:
        return {"kind": None, "raw": raw, "scheme": scheme}
    decoded = ""
    try:
        decoded = base64.b64decode(token + "=" * (-len(token) % 4)).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        decoded = ""
    info = {"kind": None, "raw": raw, "scheme": scheme, "token": token, "decoded": decoded}

    # ★ 我们自己签发的票据一律 tf- 开头，**任何 scheme 下都当票据处理**。
    #   必须放在 UbiMobile 分支之前：登录固化用的 rememberMeTicket 就是这种长票据，
    #   若被误判成设备 token，会解出一个根本不存在的 device_id，
    #   于是静默掉进匿名槽 —— 表现就是"每次重启都要重新登录"。
    if token.startswith("tf-") or decoded.startswith("tf-"):
        info["kind"] = "bearer"
        info["ticket"] = token if token.startswith("tf-") else decoded
        info["decoded_ticket"] = decoded
        return info

    if scheme.lower().startswith("ubimobile"):
        info["kind"] = "device"
        info["device_id"] = decoded.split(":")[0] if decoded else ""
        return info

    if ":" in decoded:
        info["kind"] = "basic"
        info["username"], info["password"] = decoded.split(":", 1)
        return info

    info["kind"] = "bearer"
    info["ticket"] = token
    info["decoded_ticket"] = decoded
    return info


def _ticket_to_user(headers):
    """兼容旧调用：把请求映射到账号用户名（匿名/设备返回 None）。

    ★ 现在走 authenticate()，所以 basic 形态会**校验口令**；
      以前这里直接 `return info["username"]`，等于知道用户名就能冒充别人。
    """
    info, err = authenticate(headers)
    if err or not info:
        return None
    return info["who"] if info["kind"] == "account" else None


# ------------------------------------------------------------------ 账号
def register_account(username, password, name_on_platform=None):
    """注册一个**全新**账号。

    ROADMAP 第 2 条：登录和注册必须分开 —— 登录只查库，绝不隐式建号。
    返回 (acc, err)，err ∈ {None, "bad-request", "exists"}。
    """
    username = (username or "").strip()
    if not username or not password:
        return None, "bad-request"
    key = username.lower()
    with _LOCK:
        db = _load(ACCOUNTS, {})
        users = db.setdefault("users", {})
        if key in users:
            print("[acct] 注册被拒：%s 已存在" % username, flush=True)
            return None, "exists"
        salt = binascii.hexlify(os.urandom(8)).decode("ascii")
        pid = _det_id(key)
        now = int(time.time())
        acc = {
            "username": username,
            "nameOnPlatform": name_on_platform or username,
            "profileId": pid,
            "userId": pid,
            "spaceId": ANON_SPACE_ID,
            "salt": salt,
            "pw": _hash_pw(key, password, salt),
            "has_password": True,
            "created": now,
            "logins": 0,
        }
        users[key] = acc
        _store(ACCOUNTS, db)
    print("[acct] 注册新账号 %s (profileId=%s)" % (username, pid), flush=True)
    return dict(acc), None


def login_account(username, password):
    """只查私服数据库，不建号。

    返回 (acc, err)，err ∈ {None, "bad-request", "not-found", "invalid-credentials"}。
    """
    username = (username or "").strip()
    if not username or not password:
        return None, "bad-request"
    key = username.lower()
    with _LOCK:
        db = _load(ACCOUNTS, {})
        users = db.get("users", {})
        acc = users.get(key)
        if acc is None:
            print("[acct] 登录失败：%s 未注册（先在网页上注册）" % username, flush=True)
            return None, "not-found"
        if acc.get("has_password") and acc["pw"] != _hash_pw(key, password, acc["salt"]):
            print("[acct] 登录失败：%s 密码不匹配" % username, flush=True)
            return None, "invalid-credentials"
        if not acc.get("has_password"):
            # 历史遗留账号（早期自动注册且没记口令）：补上这次的口令
            acc["pw"] = _hash_pw(key, password, acc["salt"])
            acc["has_password"] = True
        acc["logins"] = acc.get("logins", 0) + 1
        acc["last_login"] = int(time.time())
        _store(ACCOUNTS, db)
        return dict(acc), None


def ensure_account(username, password=None, name_on_platform=None):
    """兼容旧调用：先按登录查库，查不到**不建号**。仅供内部/测试使用。"""
    if password is None:
        return lookup_account(username)
    acc, err = login_account(username, password)
    if acc is None and err == "not-found":
        return None
    return acc


def set_password(username, password):
    """管理员改口令。返回 (acc, err)。"""
    username = (username or "").strip()
    if not username or not password:
        return None, "bad-request"
    key = username.lower()
    with _LOCK:
        db = _load(ACCOUNTS, {})
        acc = db.get("users", {}).get(key)
        if acc is None:
            return None, "not-found"
        acc["salt"] = binascii.hexlify(os.urandom(8)).decode("ascii")
        acc["pw"] = _hash_pw(key, password, acc["salt"])
        acc["has_password"] = True
        _store(ACCOUNTS, db)
        return dict(acc), None


def delete_account(username):
    """删除账号（不动它的存档目录）。返回 (username, err)。"""
    username = (username or "").strip()
    if not username:
        return None, "bad-request"
    key = username.lower()
    with _LOCK:
        db = _load(ACCOUNTS, {})
        if key not in db.get("users", {}):
            return None, "not-found"
        db["users"].pop(key, None)
        _store(ACCOUNTS, db)
    print("[acct] 删除账号 %s" % username, flush=True)
    return username, None


def list_accounts_public():
    """给网页/内省用：去掉口令与盐。"""
    db = _load(ACCOUNTS, {})
    remember = _load(REMEMBER, {})
    out = []
    for key, acc in sorted(db.get("users", {}).items()):
        rm = remember.get(key) or {}
        out.append({
            "username": acc.get("username", key),
            "nameOnPlatform": acc.get("nameOnPlatform"),
            "profileId": acc.get("profileId"),
            "created": acc.get("created"),
            "created_iso": _iso(acc.get("created")),
            "last_login": acc.get("last_login"),
            "last_login_iso": _iso(acc.get("last_login")),
            "logins": acc.get("logins", 0),
            "banned": bool(acc.get("banned")),
            # 登录固化状态：有 ticket 就说明这台服务器已经给过长期凭据，
            # 客户端下次启动应当能静默换会话，不必再手输账号。
            "rememberTicket": rm.get("ticket"),
            "remember_since_iso": _iso(rm.get("created")),
            "remember_uses": rm.get("uses", 0),
        })
    return out


def issue_session(acc):
    """给账号发一张票据并落盘。"""
    ticket = "tf-local-%s-%s" % (acc["username"].lower()[:12],
                                 binascii.hexlify(os.urandom(4)).decode("ascii"))
    with _LOCK:
        db = _load(SESSIONS, {})
        db[ticket] = {"user": acc["username"].lower(), "profileId": acc["profileId"],
                      "created": int(time.time())}
        # 只留最近 200 张
        if len(db) > 200:
            for k in sorted(db, key=lambda x: db[x].get("created", 0))[: len(db) - 200]:
                db.pop(k, None)
        _store(SESSIONS, db)
    return ticket


def account_by_ticket(ticket):
    if not ticket:
        return None
    with _LOCK:
        sess = _load(SESSIONS, {}).get(ticket)
        if not sess:
            return None
        return _load(ACCOUNTS, {}).get("users", {}).get(sess.get("user", ""))


# ------------------------------------------------------- 长期凭据（登录固化）
def issue_remember_ticket(acc):
    """签发 / 复用该账号的 rememberMeTicket —— 登录固化的关键。

    ★ 为什么需要它（反汇编依据）：
      `Playground::Credentials::SaveToPersistentStorage()` @0x1856a0 把凭据存进
      SecureInfoManager；下次启动时 `Playground::Credentials::AreValid()` 会调
      `IsRememberMeTicket()` @0x1851e4，为真则走
      `USDataAuthenticationConverters::Convert()` @0x1903c4 的分支：
          PlayerCredentials(ubiservices::String(ticket), /*type=*/7, /*rememberMe=*/0)
      也就是"拿长期票据直接静默换会话"。
      票据的来源是 `ubiservices::SessionInfo::getRememberMeTicket()` @0x4705b8，
      而它读的就是 `/v3/profiles/sessions` 响应里的 `rememberMeTicket` 字段
      （字段名 @0x00834288，同一个解析器里还有 ticket/userId/expiration/sessionKey…）。

      我们以前的响应只有 `"rememberMe": true` 却**没有** `rememberMeTicket`，
      客户端拿不到可长期复用的凭据 ⇒ 每次重启只能退回设备静默匿名会话
      （`Player-C83D83` 那个槽），于是玩家看到的是"没有分数记录、没有在线碉堡"，
      必须手动再登录一次。

    票据做成**每账号稳定**的：同一个账号反复登录拿到同一张，
    这样即使客户端把旧票据存了很久也依然有效。
    """
    if not acc:
        return None
    key = (acc.get("username") or "").lower()
    if not key:
        return None
    with _LOCK:
        db = _load(REMEMBER, {})
        rec = db.get(key)
        if rec and rec.get("ticket"):
            ticket = rec["ticket"]
            rec["last_used"] = int(time.time())
            rec["uses"] = rec.get("uses", 0) + 1
        else:
            ticket = "tf-rm-%s-%s" % (key[:12], binascii.hexlify(os.urandom(4)).decode("ascii"))
            rec = {"ticket": ticket, "profileId": acc.get("profileId"),
                   "created": int(time.time()), "uses": 1}
            print("[acct] 为 %s 签发长期凭据 %s" % (key, ticket), flush=True)
        db[key] = rec
        _store(REMEMBER, db)
    return ticket


def account_by_remember_ticket(ticket):
    """长期凭据 -> 账号。被 authenticate() 的 bearer 分支调用。"""
    if not ticket:
        return None
    with _LOCK:
        for key, rec in _load(REMEMBER, {}).items():
            if rec.get("ticket") == ticket:
                return _load(ACCOUNTS, {}).get("users", {}).get(key)
    return None


def list_remember_tickets():
    with _LOCK:
        return dict(_load(REMEMBER, {}))


def forget_remember_ticket(username):
    """踢掉某个账号的长期凭据（管理用）。返回被删的票据或 None。"""
    key = (username or "").lower()
    with _LOCK:
        db = _load(REMEMBER, {})
        rec = db.pop(key, None)
        _store(REMEMBER, db)
    return rec.get("ticket") if rec else None


# ------------------------------------------------------------- 设备（未登录）
def ensure_device(device_id):
    """设备静默登录：按设备 id 分配独立 profileId，避免多台设备挤同一个匿名槽。

    ★ 注意：这跟"幽灵"无关 —— 幽灵库是有意全局共享的（排行榜上下载别人的记录
    本来就是游戏设计），所以幽灵不按设备/账号分目录。
    """
    device_id = str(device_id or "").strip()
    if not device_id:
        return None
    with _LOCK:
        db = _load(DEVICES, {})
        dev = db.get(device_id)
        now = int(time.time())
        if dev is None:
            pid = _device_id_uuid(device_id)
            dev = {
                "deviceId": device_id,
                "profileId": pid,
                "userId": pid,
                "username": "device-" + device_id[:8],
                "nameOnPlatform": "Player-" + device_id[:6].upper(),
                "ticket": "tf-dev-%s" % binascii.hexlify(os.urandom(4)).decode("ascii"),
                "created": now,
            }
            db[device_id] = dev
            print("[acct] 新设备 %s -> profileId=%s" % (device_id[:8], pid), flush=True)
        dev["last_seen"] = now
        dev["sessions"] = dev.get("sessions", 0) + 1
        _store(DEVICES, db)
        return dict(dev)


def device_by_ticket(ticket):
    if not ticket:
        return None
    with _LOCK:
        for dev in _load(DEVICES, {}).values():
            if dev.get("ticket") == ticket:
                return dict(dev)
    return None


def device_by_profile(profile_id):
    if not profile_id:
        return None
    with _LOCK:
        for dev in _load(DEVICES, {}).values():
            if dev.get("profileId") == profile_id:
                return dict(dev)
    return None


# ------------------------------------------------------------- 统一鉴权
def authenticate(headers):
    """把请求的 Authorization 解析成调用者。

    返回 (info, error)：
      info  = {"kind": "account"|"device"|"anon", "who": str, "profileId": str}
      error = None / "invalid-credentials" / "unknown-ticket"

    规则（用来堵住"知道用户名就能改写别人服务器侧存档"的洞）：
      * Ubi_v1 t=base64("用户名:口令")  → 必须口令正确，否则 401
      * Ubi_v1 t=<我们发过的票据>       → 必须在 sessions/devices 表里，否则 401
      * UbiMobile_v1 t=<设备 token>     → 按设备发独立槽位（令牌本身即设备凭据）
      * 完全没有 Authorization 头      → 走旧的匿名槽（兼容老存档）
    """
    info = parse_authorization(headers)
    kind = info.get("kind")

    if kind == "device":
        dev = ensure_device(info.get("device_id"))
        if dev is None:
            return None, "unknown-ticket"
        return {"kind": "device", "who": "device:" + str(info.get("device_id"))[:8],
                "profileId": dev["profileId"]}, None

    if kind == "basic":
        user = info.get("username") or ""
        acc = lookup_account(user)
        if acc is None:
            return None, "invalid-credentials"
        if acc.get("has_password"):
            if acc["pw"] != _hash_pw(user.lower(), info.get("password") or "", acc["salt"]):
                print("[acct] %s 存档上报口令错误 -> 401" % user, flush=True)
                return None, "invalid-credentials"
        return {"kind": "account", "who": user.lower(), "profileId": acc["profileId"]}, None

    # bearer：我们自己签发的票据
    for c in (info.get("ticket"), info.get("token"), info.get("decoded_ticket")):
        if not c:
            continue
        acc = account_by_ticket(c)
        if acc:
            return {"kind": "account", "who": acc["username"].lower(),
                    "profileId": acc["profileId"]}, None
        # 长期凭据（rememberMeTicket）：登录固化的静默会话走这条
        acc = account_by_remember_ticket(c)
        if acc:
            return {"kind": "account", "who": acc["username"].lower(),
                    "profileId": acc["profileId"]}, None
        dev = device_by_ticket(c)
        if dev:
            return {"kind": "device", "who": "device:" + str(dev.get("deviceId"))[:8],
                    "profileId": dev["profileId"]}, None

    if (not info.get("raw")) or info.get("token") == ANON_TICKET:
        return {"kind": "anon", "who": "<anonymous>", "profileId": ANON_PROFILE_ID}, None
    return None, "unknown-ticket"


# ------------------------------------------------- 客户端 -> 账号绑定（身份稳定）
# ★ 为什么需要（2026-10-05 真机日志复盘）：一次冷启动里客户端会用**好几个身份**发请求 ——
#   带账号票据的、完全不带 Authorization 的、以及我们回给它的匿名票
#   `tf-local-ticket-0001`。7360 条真机请求里 1737 条没有 Authorization、
#   1489 条用那张匿名票，于是 PVP/存档状态被劈成「账号槽」和「匿名槽」两半，
#   表现就是用户说的「时好时坏」：有时看到自己的段位与进行中的对局，
#   有时是全新玩家（rank 25 / 0 筹码 / 没有对局 → 碉堡界面空转）。
#   这里按客户端 IP（tf_server 注入的 X-TF-Client）+ 设备 id 记住最近一次
#   **成功登录**的账号，之后认不出凭据的请求一律归到它名下。
# ponytail: 按 IP 绑定；同一 NAT 后多台设备会串成同一个人，家用单机私服够用。
#           真要多人就只认 by_device（UbiMobile 票里的 device_id），IP 那条删掉即可。
def _load_bindings():
    db = _load(BINDINGS, {})
    if not isinstance(db, dict):
        db = {}
    for key in ("by_ip", "by_device"):
        if not isinstance(db.get(key), dict):
            db[key] = {}
    return db


def bind_client(acc, client_ip=None, device_id=None):
    """把账号记在这台客户端（IP / 设备 id）名下；只在成功登录后调用。"""
    who = (acc or {}).get("username")
    if not who:
        return
    who = who.lower()
    with _LOCK:
        db = _load_bindings()
        changed = False
        if client_ip and db["by_ip"].get(client_ip) != who:
            db["by_ip"][client_ip] = who
            changed = True
        if device_id and db["by_device"].get(str(device_id)) != who:
            db["by_device"][str(device_id)] = who
            changed = True
        if changed:
            _store(BINDINGS, db)
            print("[acct] 客户端绑定：ip=%s device=%s -> %s" % (client_ip, device_id, who),
                  flush=True)


def account_by_client(client_ip=None, device_id=None):
    """按设备 id 优先、其次客户端 IP，取回这台客户端登录过的账号。"""
    with _LOCK:
        db = _load_bindings()
    who = (db["by_device"].get(str(device_id)) if device_id else None) or \
          (db["by_ip"].get(client_ip) if client_ip else None)
    return lookup_account(who) if who else None


def resolve_identity(headers):
    """`authenticate()` + 「认不出凭据时归到这台客户端的账号」。

    返回与 `authenticate()` 同形的 (info, error)。规则：
      * 明确的口令错误（invalid-credentials）**不许**被 IP 绑定洗白，照旧 401；
      * 已经认成账号 → 顺手把绑定刷新（下次不带凭据也能认出来）；
      * 设备票 / 匿名 / 不认识的票 → 看这台客户端登录过谁，有就归他。
    """
    raw = parse_authorization(headers or {})
    info, err = authenticate(headers)
    client_ip = (headers or {}).get("X-TF-Client") or None
    device_id = raw.get("device_id") if raw.get("kind") == "device" else None
    if info and info.get("kind") == "account":
        bind_client(lookup_account(info["who"]), client_ip, device_id)
        return info, None
    if err == "invalid-credentials":
        return info, err
    acc = account_by_client(client_ip, device_id)
    if acc is not None:
        return {"kind": "account", "who": acc["username"].lower(),
                "profileId": acc["profileId"]}, None
    return info, err


def lookup_account(username):
    with _LOCK:
        return _load(ACCOUNTS, {}).get("users", {}).get((username or "").lower())


# ------------------------------------------------------------------ 会话响应
def session_body(acc, ticket, remember_me=False, remember_ticket=None):
    """育碧 /v3/profiles/sessions 的响应体（实测字段）。

    ★ `rememberMeTicket` 是**登录固化**的必需字段，不是可选装饰：
      `ubiservices::SessionInfo::getRememberMeTicket()` @0x4705b8 读它，
      游戏侧 `Playground::Credentials::SaveToPersistentStorage()` @0x1856a0 把它
      存进安全存储，下次启动 `IsRememberMeTicket()` 为真就用
      `PlayerCredentials(ticket, type=7, rememberMe=0)`（`Convert()` @0x1903c4）
      静默换会话。缺了它，客户端每次重启都会退回设备匿名会话。
    字段名与同族键（ticket/userId/expiration/rememberMeTicket/sessionKey…）
    都在 libubiservices.so 的同一个 session 解析器里，`rememberMeTicket` @0x00834288。
    """
    if acc:
        pid = acc["profileId"]
        name = acc.get("nameOnPlatform") or acc["username"]
    else:
        pid = ANON_PROFILE_ID
        name = "LocalPlayer"
    body = {
        "platformType": "ubimobile",
        "ticket": ticket,
        "twoFactorAuthenticationTicket": None,
        "profileId": pid,
        "userId": pid,
        "nameOnPlatform": name,
        "idOnPlatform": pid,
        "environment": "Prod",
        "expiration": "2099-12-31T23:59:59.000Z",
        "spaceId": ANON_SPACE_ID,
        "clientIp": "127.0.0.1",
        "serverTime": "2026-01-01T00:00:00.000Z",
        "sessionId": ANON_SESSION_ID,
        "sessionKey": "tf-local-session-key",
        "rememberMe": bool(remember_me),
    }
    if remember_ticket:
        body["rememberMeTicket"] = remember_ticket
    return body


def profile_body(acc):
    if acc:
        pid = acc["profileId"]
        name = acc.get("nameOnPlatform") or acc["username"]
    else:
        pid, name = ANON_PROFILE_ID, "LocalPlayer"
    return {"profileId": pid, "userId": pid, "platformType": "ubimobile",
            "idOnPlatform": pid, "nameOnPlatform": name}


# ------------------------------------------------------------------ 存档
def _split_body(body):
    """客户端可能发 JSON 字符串，也可能是原始字节。"""
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(bytes(body).decode("utf-8"))
        except Exception:
            return None
    if isinstance(body, dict):
        return body
    return None


def _richness(obj):
    """粗略衡量一份进度"有多满"，用来判断新上报是不是把存档清空了。"""
    if not isinstance(obj, dict):
        return 0
    n = len(obj.get("items2") or []) // 2
    n += len(obj.get("highscores2") or [])
    n += len(obj.get("achievements2") or [])
    n += len(obj.get("tutorials2") or [])
    if obj.get("missions2"):
        n += 5
    if obj.get("statistics2"):
        n += 5
    return n


# ★★ 第二道防清档护栏（2026-10-04 第二次真机事故复盘）：
#   客户端在一次冷启动里会连做两次 syncProgress —— 先 POST 一份**完整档**（17 个键，
#   ~25 KB），约 6 秒后再 POST 一份**半个档**（7~8 个键，~3.9 KB）。第二次那份只带
#   `checksum/game_version/identifier/items2/(robotman)/timers2/timestamp/version`，
#   **`profile`、`highscores2`、`achievements2`、`missions2`、`statistics2`、
#   `tutorials2`、`settings` 全没了**（那是客户端自己的序列化时序问题，不是玩家的选择）。
#   而第一道护栏（richness 减半）拦不住它：items2 有 428 对，光这一项就够 856 > 650/2，
#   于是半个档照样覆盖了 latest.json ⇒ 玩家真机表现 = 回到新手教程、赛道纪录全没。
#   所以再加一道**按段落**的判定：旧档里非空、新档里缺失/变空的段落，一个都不许丢。
_SAVE_SECTIONS = ("items2", "highscores2", "achievements2", "missions2",
                  "statistics2", "tutorials2", "settings", "profile",
                  "store_bonus", "dailyexperience")


def _lost_sections(old, new):
    """返回旧档里非空、但新档里缺失或变空的段落名（按 _SAVE_SECTIONS 顺序）。"""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    return [k for k in _SAVE_SECTIONS if old.get(k) and not new.get(k)]


def save_progress(headers, body, client_ip=None):
    """把客户端上传的存档落盘。返回 (profileId or None, 摘要 dict, error)。

    ★ 归属严格按 authenticate() 的结果走：口令不对 / 票据不认识 -> error，调用方回 401。
      这样"知道用户名就能改写别人服务器侧存档"的洞就堵住了。
    ★ client_ip 记进 payload，供 serve_progress 判断"同一台设备"用（登录后接手上一个
      匿名/设备槽的存档），避免局域网上互相串档。
    """
    obj = _split_body(body)
    if obj is None:
        return None, {}, "bad-body"
    who_info, err = resolve_identity(headers)
    if err:
        return None, {}, err
    pid, who = who_info["profileId"], who_info["who"]
    d = os.path.join(SAVE_DIR, pid)
    hist = os.path.join(d, "history")
    os.makedirs(hist, exist_ok=True)
    now = int(time.time())
    # ★ 每次**被接受**的上报把版本号 +1。客户端把 sync 响应里的 version 记进
    #   Player+0x4864 当作"本地版本"，再拿它跟 /progress/version 返回的 version 比：
    #   相等 -> 客户端把自己的存档推上来；不等 -> 进入"进度冲突"界面，由玩家选择
    #   用云端还是用本地。这正是我们要的"服务器记住存档、登录后能恢复"的正常语义。
    old_doc = load_progress(pid)
    ver = int((old_doc or {}).get("version") or 0) + 1
    payload = {
        "saved_at": now,
        "saved_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "version": ver,
        "account": who,
        "kind": who_info["kind"],
        "profileId": pid,
        "client_ip": client_ip,
        "content": obj,
    }
    _store(os.path.join(d, "history", "%d.json" % now), payload)
    with _LOCK:
        try:
            files = sorted(f for f in os.listdir(hist) if f.endswith(".json"))
            for f in files[:-SAVE_HISTORY_MAX]:
                os.remove(os.path.join(hist, f))
        except Exception:
            pass

    # ★★ 防清档护栏（两次真机事故复盘）：
    #   客户端在"登录/换 owner/首次同步/冷启动"这些时序上会把**重置后的默认存档**或
    #   **只序列化了一半的存档**上报回来（实测 richness 从 650 掉到 428、段落从 17 个
    #   掉到 8 个）。一旦覆盖 latest.json，玩家进度就再也回不去。
    #   所以两道判定，命中任意一条就**只写 history，不覆盖 latest**：
    #     (a) 段落丢失：旧档非空、新档缺失/变空的 `_SAVE_SECTIONS` 里的任一段落；
    #     (b) richness 减半：旧档 ≥10 且新档不到旧档一半。
    #   ★ 拒绝时回的 `server_version` 取**旧版本 +1**（而落盘的旧档版本号并不变）：
    #     `h_progress` 把它当 `{"version": …}` 发给客户端，客户端会把它记进
    #     `Player+0x4864`。这样下一轮 `GET /progress/version` 返回的仍是真实旧版本，
    #     与客户端记的对不上 ⇒ `ProgressSyncManager` 判定"版本冲突"、拉起
    #     `MenuzStateSyncProgress`，玩家就拿到了"用云端"的恢复入口。
    #     若这里回 0（旧实现的 bug）客户端会以为服务器没档，继续推本地，永远走不到恢复。
    old = load_progress(pid)
    old_ver = int((old or {}).get("version") or 0)
    old_rich = _richness((old or {}).get("content"))
    new_rich = _richness(obj)
    lost = _lost_sections((old or {}).get("content"), obj)
    if old and (lost or (old_rich >= 10 and new_rich * 2 < old_rich)):
        print("[save] ⚠ 拒绝覆盖 %s 的存档（丢失段落=[%s]，旧 richness=%d -> 新 richness=%d），"
              "新数据已存进 history/%d.json；如需强制接受请删掉 latest.json"
              % (who, ",".join(lost), old_rich, new_rich, now), flush=True)
        return pid, {"rejected": True, "lost_sections": lost, "old_richness": old_rich,
                     "new_richness": new_rich, "saved_at": now, "account": who,
                     "server_version": old_ver + 1}, None

    _store(os.path.join(d, "latest.json"), payload)
    brief = {
        "account": who,
        "kind": who_info["kind"],
        "profileId": pid,
        "server_version": ver,
        "items": len(obj.get("items2") or []) // 2,
        "tracks": len(obj.get("highscores2") or []),
        "version": obj.get("version"),
        "game_version": obj.get("game_version"),
        "identifier": obj.get("identifier"),
        "saved_at": now,
    }
    print("[save] %s(%s): %d 条物品 / %d 条赛道纪录 -> %s"
          % (who, who_info["kind"], brief["items"], brief["tracks"],
             os.path.join(d, "latest.json")), flush=True)
    return pid, brief, None


def load_progress(profile_id):
    return _load(os.path.join(SAVE_DIR, profile_id, "latest.json"), None)


def _all_saves():
    out = []
    if not os.path.isdir(SAVE_DIR):
        return out
    for pid in sorted(os.listdir(SAVE_DIR)):
        doc = load_progress(pid)
        if doc:
            out.append((pid, doc))
    return out


def serve_progress(headers, client_ip=None):
    """给 'GET /public/playerprogress/v1/progress' 选一份要下发给客户端的存档。

    返回 (profileId, content dict, note)；什么都没找到时返回 (None, None, note)。

    ★★ 为什么需要这个函数（真机事故复盘）：
       `tr::OnlinePlayerProgress::parseResponse`（libTrialsGo.so @0x57433c，cmd 0x24
       = retrieveProgress @0x573d4c 发出的 GET）会调 `parseProgress` @0x574780，
       然后**无条件 `tr::Player::save()` @0x362bc0**。也就是说：
       **服务器对 /progress 返回什么，客户端就把本地存档覆盖成什么。**
       之前我们对这个端点回 `{"data": []}`，客户端解析出"全是默认值"，
       紧接着 Player::save() → **玩家本地存档被清空**（用户实测：登录账号后进度没了）。

    所以规则是：
      1. 调用方自己的槽有存档 -> 直接下发；
      2. 否则，**同一 client_ip 上最近一次匿名/设备槽的存档** -> 「原地收养」，
         复制进调用方槽再下发（解决"玩一半才登录，进度不能丢"）；
      3. 否则退到老的匿名槽 ANON_PROFILE_ID；
      4. 真的什么都没有 -> 返回 None，调用方必须回 **404**（让客户端走
         onNetworkError @0x574198 分支），**绝不能回空 JSON**，否则就是清档。
    """
    who_info, err = resolve_identity(headers)
    if err:
        return None, None, "auth:" + err
    pid = who_info["profileId"]
    doc = load_progress(pid)
    if doc and doc.get("content"):
        return pid, doc["content"], "own"

    donors = []
    if client_ip:
        for dpid, ddoc in _all_saves():
            if dpid == pid or not ddoc.get("content"):
                continue
            if ddoc.get("client_ip") != client_ip:
                continue
            if ddoc.get("kind") not in ("device", "anon"):
                continue
            donors.append((ddoc.get("saved_at") or 0, dpid, ddoc))
    if not donors:
        legacy = load_progress(ANON_PROFILE_ID)
        if legacy and legacy.get("content") and ANON_PROFILE_ID != pid:
            donors.append((legacy.get("saved_at") or 0, ANON_PROFILE_ID, legacy))
    if not donors:
        return None, None, "empty"

    _, src_pid, src = max(donors, key=lambda t: t[0])
    adopted = dict(src)
    adopted.update({
        "saved_at": int(time.time()),
        "saved_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "account": who_info["who"],
        "kind": who_info["kind"],
        "profileId": pid,
        "client_ip": client_ip,
        "adopted_from": src_pid,
        "adopted_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    d = os.path.join(SAVE_DIR, pid)
    os.makedirs(os.path.join(d, "history"), exist_ok=True)
    _store(os.path.join(d, "latest.json"), adopted)
    print("[save] 收养存档：%s(%s) 继承 %s 的进度（items=%d, tracks=%d）"
          % (who_info["who"], who_info["kind"], src_pid,
             len((adopted.get("content") or {}).get("items2") or []) // 2,
             len((adopted.get("content") or {}).get("highscores2") or [])), flush=True)
    return pid, adopted["content"], "adopted:" + src_pid


def progress_version(headers, client_ip=None):
    """给 `GET /public/playerprogress/v1/progress/version` 用（cmd 0x22 → checkProgress）。

    返回 (pid, version, time_stamp, note)。

    ★★ 为什么要"版本号"（反汇编 `tr::ProgressSyncManager::onProgressCheckComplete`
       @0x00625da4 得到的确切语义）：
       - 客户端把上一次 sync 响应里的 `version` 记进 `Player+0x4864`（本地版本）；
       - `/progress/version` 的响应必须是 `{"version": N, "time_stamp": T}`；
         `OnlinePlayerProgress::parseResponse` cmd 0x22 分支只认这两个 int 键
         （`version`@0xb4056d、`time_stamp`@0xb89a9c）；
       - 比较结果：
           remote == local  或  remote == 0  -> `syncProgress(listener,false)`：**客户端覆盖服务器**；
           remote != local 且 remote != 0    -> 置冲突标志并拉起 `MenuzStateSyncProgress`，
                                                由玩家选择"用云端 / 用本地"。
       之前我们对这个端点回 `{"data": []}` → remote 恒为 0 → 客户端每次都把本地（被清空的）
       存档推上来覆盖服务器。现在服务器给真实版本号，冲突时游戏自己会给出恢复入口。
    """
    pid, content, note = serve_progress(headers, client_ip)
    if not content:
        return None, 0, 0, note
    doc = load_progress(pid) or {}
    return pid, int(doc.get("version") or 0), int(doc.get("saved_at") or 0), note


def list_devices():
    with _LOCK:
        db = _load(DEVICES, {})
    return [{k: v.get(k) for k in ("deviceId", "profileId", "nameOnPlatform",
                                   "created", "last_seen", "sessions")}
            for v in db.values()]


def list_saves():
    out = []
    if not os.path.isdir(SAVE_DIR):
        return out
    for pid in sorted(os.listdir(SAVE_DIR)):
        latest = load_progress(pid)
        if latest:
            c = latest.get("content") or {}
            out.append({
                "profileId": pid,
                "account": latest.get("account"),
                "kind": latest.get("kind"),
                "saved_at": latest.get("saved_at"),
                "saved_at_iso": latest.get("saved_at_iso"),
                "items": len(c.get("items2") or []) // 2,
                "tracks": len(c.get("highscores2") or []),
                "identifier": c.get("identifier"),
                "richness": _richness(c),
                "adopted_from": latest.get("adopted_from"),
            })
    return out


def list_history(profile_id):
    """列某个槽的全部历史快照（供 /__restore 用）。"""
    hist = os.path.join(SAVE_DIR, profile_id, "history")
    if not os.path.isdir(hist):
        return []
    out = []
    for f in sorted(os.listdir(hist)):
        if not f.endswith(".json"):
            continue
        doc = _load(os.path.join(hist, f), None)
        if doc:
            c = doc.get("content") or {}
            out.append({
                "ts": f[:-5],
                "saved_at_iso": doc.get("saved_at_iso"),
                "items": len(c.get("items2") or []) // 2,
                "tracks": len(c.get("highscores2") or []),
                "identifier": c.get("identifier"),
                "richness": _richness(c),
            })
    return out


def restore_save(profile_id, ts):
    """把某个历史快照提回 latest.json。ts 为 'latest' 或 history 文件名里的时间戳。"""
    if ts in (None, "", "latest"):
        return load_progress(profile_id)
    src = os.path.join(SAVE_DIR, profile_id, "history", "%s.json" % ts)
    doc = _load(src, None)
    if not doc:
        return None
    _store(os.path.join(SAVE_DIR, profile_id, "latest.json"), doc)
    print("[save] 已把 %s 的 history/%s.json 提回 latest.json（items=%d, richness=%d）"
          % (profile_id, ts, len((doc.get("content") or {}).get("items2") or []) // 2,
             _richness(doc.get("content"))), flush=True)
    return doc


# ------------------------------------------------------------------ 幽灵
# 两层存储，各有来历：
#
#   1) 「按赛道放文件」的老目录  data/ghosts/<track>/<name>.bin
#      从原版设备上抓来的内置幽灵（别人的最好线路）就放在这里。resultservice
#      那几个直接回原始字节的端点优先读它。文件格式见 data/ghosts/README.md。
#
#   2) 新的 userstorage v2 内容仓库  data/ghosts/store/<id>.bin + data/ghosts/index.json
#      客户端上传**自己的**幽灵时走这条链（实测顺序）：
#        POST /public/userstorage/v2/content/ghost          建容器 -> 必须回真实 contentId
#        PUT  /public/userstorage/v2/content/ghost/<id>/payload   传二进制
#        PUT  /public/userstorage/v2/content/ghost/<id>           更新 metadata
#      服务器的 create 响应如果不带 contentId，客户端就一路用 id=0（实测踩过），
#      下发给别人时也就查不到。所以这里必须分配并持久化真实 id。
GHOST_STORE = os.path.join(GHOST_DIR, "store")
GHOST_INDEX = os.path.join(GHOST_DIR, "index.json")
GHOST_REPLAYS = os.path.join(GHOST_DIR, "replays.json")

# 实测客户端会给 players 发 "0" 表示「不限玩家」。
GHOST_ANY_PLAYERS = ("", "0", "-1", "any", "all", "null")

# 客户端会在赛道 ID 上叠高位标志位，幽灵库里必须一律按裸 ID 存：
#   | 0x800000 (8388608)  PVP 对手幽灵（OnlinePVP::parseJsonResponse cmd 0x2c 分支
#                        `orr w2,w8,#0x800000` → getPVPGhost() →
#                        resultservice/v1/pvp_replaydata?track_id=8389649&player=…&pvp_id=…）
#   | 0x10000  (65536)    排行榜（周赛）变体，如 track66633 = 65536 + 1097
#   | 0x100000 (1048576)  排行榜（另一套）变体，如 track1049609 = 1048576 + 1033
# 真实赛道 ID 目前最大 1438，掩到 0xFFFF 足够。★ 掩码必须在**存储边界**做：
# 以前只在查询侧掩、写入侧原样存，于是 index.json 里 51:8389649 与 1:1041 混存，
# 查询掩完变成 track1097 却永远对不上 track66633 那条记录 —— 精确匹配全 miss。
TRACK_MASK = 0xFFFF


def mask_track(track_id):
    """把客户端赛道 ID 掩成裸 ID；不是整数就返回 None。"""
    if track_id is None:
        return None
    try:
        return int(track_id) & TRACK_MASK
    except (TypeError, ValueError):
        return None


def ghost_dir(track_id):
    return os.path.join(GHOST_DIR, str(track_id))


def list_ghosts(track_id):
    d = ghost_dir(track_id)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith(".bin"))


def store_ghost(track_id, name, blob):
    d = ghost_dir(track_id)
    os.makedirs(d, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in "._-") or "ghost"
    p = os.path.join(d, safe)
    with open(p, "wb") as f:
        f.write(blob)
    return p


def load_ghost(track_id, name):
    p = os.path.join(ghost_dir(track_id), name)
    if os.path.isfile(p):
        with open(p, "rb") as f:
            return f.read()
    return None


def _load_ghosts():
    obj = _load(GHOST_INDEX, None)
    if not isinstance(obj, dict):
        obj = {}
    if not isinstance(obj.get("items"), dict):
        obj["items"] = {}
    try:
        obj["next_id"] = max(1, int(obj.get("next_id") or 1))
    except Exception:
        obj["next_id"] = 1
    return obj


def _save_ghosts(obj):
    _store(GHOST_INDEX, obj)


def ghost_probe(blob):
    """读幽灵文件头（0x00 version / 0x04 tag / 0x08 解压后长度 / 0x10 zlib）。

    只解压前 20 字节就够拿到「这次跑的时间」和帧数，不用整段解压。
    返回 (drive_time, tag, frames)；不是幽灵文件就返回 (None, None, None)。
    """
    import struct
    import zlib

    if not blob or len(blob) < 20 or blob[:4] != b"\x03\x00\x00\x00":
        return None, None, None
    tag = struct.unpack_from("<I", blob, 4)[0]
    try:
        d = zlib.decompressobj()
        head = d.decompress(blob[16:], 32)
    except Exception:
        return None, tag, None
    if len(head) < 0x0C:
        return None, tag, None
    drive_time = struct.unpack_from("<I", head, 0x04)[0]
    frames = struct.unpack_from("<I", head, 0x08)[0]
    return int(drive_time), int(tag), int(frames)


def _legacy_ghost_files():
    """扫描 data/ghosts/<track>/*.bin，产出 (track_id, 相对 data 的路径, 绝对路径)。"""
    out = []
    if not os.path.isdir(GHOST_DIR):
        return out
    for name in sorted(os.listdir(GHOST_DIR)):
        d = os.path.join(GHOST_DIR, name)
        if not os.path.isdir(d) or name in ("store", "inbox"):
            continue
        if not name.isdigit() or int(name) <= 0:
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".bin"):
                p = os.path.join(d, fn)
                out.append((int(name), os.path.relpath(p, DATA).replace("\\", "/"), p))
    return out


def _migrate_ghost_records(obj):
    """一次性把 index.json 里带标志位的 track_id 掩回裸 ID，并补上缺的 `size`。

    ★ 两者都是客户端硬要求：
      * 掩码：查询侧早就在掩，写入侧没掩 ⇒ `track66633` 与 `track1097` 对不上（见 TRACK_MASK）。
      * `size`：`GhostQueryObject::onQueryCompleted` @0x508288 的 type-3 分支
        （`0x5083b8 str w8,[sp,#0x14]` 读键 `size`@0xb4317f）**`size < 1` 直接判定失败**，
        而内置幽灵只有 metadata、从来没写过 size —— 排行榜挑战永远拿不到幽灵。
    """
    changed = 0
    for rec in obj["items"].values():
        raw = rec.get("track_id")
        bare = mask_track(raw)
        if bare is not None and bare != raw:
            rec["track_id"] = bare
            changed += 1
        md = rec.get("metadata")
        if isinstance(md, dict):
            mraw = md.get("track_id")
            mbare = mask_track(mraw)
            if mbare is not None and mbare != mraw:
                md["track_id"] = mbare
                changed += 1
        if not rec.get("size"):
            n = None
            p = os.path.join(GHOST_STORE, "%s.bin" % rec.get("contentId"))
            if os.path.isfile(p):
                n = os.path.getsize(p)
            elif rec.get("legacy_path"):
                q = os.path.join(DATA, str(rec["legacy_path"]).replace("/", os.sep))
                if os.path.isfile(q):
                    n = os.path.getsize(q)
            if n:
                rec["size"] = n
                changed += 1
    return changed


def ghost_sync_legacy():
    """把老目录里的内置幽灵登记进新仓库（只登记一次，用 relpath 记录来源）。"""
    with _LOCK:
        obj = _load_ghosts()
        items = obj["items"]
        known = set()
        for rec in items.values():
            if rec.get("legacy_path"):
                known.add(rec["legacy_path"])
        added = 0
        for track, rel, p in _legacy_ghost_files():
            if rel in known:
                continue
            try:
                with open(p, "rb") as f:
                    blob = f.read()
            except OSError:
                continue
            drive_time, tag, frames = ghost_probe(blob)
            cid = int(obj["next_id"])
            obj["next_id"] = cid + 1
            items[str(cid)] = {
                "contentId": cid,
                "track_id": mask_track(track),
                "owner": "6f857655",
                "metadata": {
                    "track_id": mask_track(track),
                    "drive_time": drive_time or 0,
                    "checksum": tag or 0,
                    "version": 79401,
                },
                "drive_time": drive_time or 0,
                "checksum": tag or 0,
                "version": 79401,
                "created": int(time.time()),
                "updated": int(time.time()),
                "legacy_path": rel,
                "frames": frames,
                "size": len(blob),
                "builtin": True,
            }
            added += 1
        fixed = _migrate_ghost_records(obj)
        if added or fixed:
            _save_ghosts(obj)
            if added:
                print("[ghost] 登记内置幽灵 %d 个" % added, flush=True)
            if fixed:
                print("[ghost] 迁移幽灵记录 %d 处（赛道掩码 / 补 size）" % fixed, flush=True)
        return added


def _ghost_record(cid):
    obj = _load_ghosts()
    return obj["items"].get(str(cid))


def ghost_get(cid):
    return _ghost_record(cid)


def ghost_create(track_id, owner, metadata):
    """建幽灵容器，返回分配到的 contentId（必须回给客户端）。"""
    md = dict(metadata) if isinstance(metadata, dict) else {}
    if track_id is None:
        track_id = md.get("track_id")
    # ★ 存入前掩码（见 TRACK_MASK）：客户端 create 时发的 track_id 可能带
    #   |0x800000 / |0x10000 / |0x100000 标志位，原样存下来查询就永远对不上。
    track_id = mask_track(track_id)
    if track_id is not None:
        md["track_id"] = track_id
    now = int(time.time())
    with _LOCK:
        obj = _load_ghosts()
        cid = int(obj["next_id"])
        obj["next_id"] = cid + 1
        rec = {
            "contentId": cid,
            "track_id": track_id,
            "owner": owner,
            "metadata": md,
            "drive_time": _as_int(md.get("drive_time")),
            "checksum": _as_int(md.get("checksum")),
            "version": _as_int(md.get("version")),
            "pvpid": _as_int(md.get("pvpid")),
            "created": now,
            "updated": now,
            "size": None,
        }
        obj["items"][str(cid)] = rec
        _save_ghosts(obj)
    return cid


def _as_int(v):
    try:
        return int(v)
    except Exception:
        return None


def ghost_update(cid, metadata, owner=None):
    """更新 metadata。

    ⚠ 客户端 updateMetaData 的 body 里**没有 track_id**（实测
    `{"metadata":{"drive_time":..,"checksum":..,"version":..}}`），
    所以这里做合并，绝不能把 create 时记下的 track_id 抹掉。
    """
    with _LOCK:
        obj = _load_ghosts()
        rec = obj["items"].get(str(cid))
        if rec is None:
            return None
        md = dict(metadata) if isinstance(metadata, dict) else {}
        merged = dict(rec.get("metadata") or {})
        merged.update(md)
        rec["metadata"] = merged
        if merged.get("track_id") is not None:
            bare = mask_track(merged["track_id"])
            if bare is not None:
                rec["track_id"] = bare
                merged["track_id"] = bare
        for key in ("drive_time", "checksum", "version", "pvpid"):
            val = _as_int(merged.get(key))
            if val is not None:
                rec[key] = val
        if owner:
            rec["owner"] = owner
        rec["updated"] = int(time.time())
        _save_ghosts(obj)
    return rec


def ghost_put_payload(cid, blob):
    rec = _ghost_record(cid)
    if rec is None:
        return None
    os.makedirs(GHOST_STORE, exist_ok=True)
    tmp = os.path.join(GHOST_STORE, "%s.bin.tmp" % cid)
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, os.path.join(GHOST_STORE, "%s.bin" % cid))
    drive_time, tag, frames = ghost_probe(blob)
    with _LOCK:
        obj = _load_ghosts()
        rec = obj["items"].get(str(cid))
        if rec is None:
            return None
        rec["size"] = len(blob)
        rec["stored"] = True
        rec["frames"] = frames
        rec["payload_drive_time"] = drive_time
        rec["updated"] = int(time.time())
        # 二进制头里的时间比 metadata 更权威（metadata 是上传前算的）。
        if drive_time:
            rec["drive_time"] = drive_time
            md = dict(rec.get("metadata") or {})
            md["drive_time"] = drive_time
            rec["metadata"] = md
        _save_ghosts(obj)
    return rec


def ghost_payload(cid):
    """取幽灵二进制。新仓库优先，内置幽灵回落到老目录里的文件。"""
    rec = _ghost_record(cid)
    if rec is None:
        return None
    p = os.path.join(GHOST_STORE, "%s.bin" % cid)
    if os.path.isfile(p):
        with open(p, "rb") as f:
            return f.read()
    rel = rec.get("legacy_path")
    if rel:
        q = os.path.join(DATA, rel.replace("/", os.sep))
        if os.path.isfile(q):
            with open(q, "rb") as f:
                return f.read()
    return None


def ghost_delete(cid):
    with _LOCK:
        obj = _load_ghosts()
        rec = obj["items"].pop(str(cid), None)
        if rec is not None:
            _save_ghosts(obj)
    p = os.path.join(GHOST_STORE, "%s.bin" % cid)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass
    return rec


def ghost_search(track_id=None, players=None, limit=1, drive_time=None,
                 pvpid=None, owner=None):
    """幽灵检索。返回按「该优先给谁」排好序的记录列表。

    排序口径：请求方点名的玩家排前面，其次按时间接近度（给了 drive_time）
    或按成绩快慢；内置幽灵垫后。`players` 一个都没命中时**回落到全部**——
    单机离线只有自己一个人，严格过滤会导致永远查不到幽灵。

    `pvpid`：PVP 专用的对手位（`get_pvp_ghost?…&pvpid=%d`，真机只见 1 和 2）。
      ⚠ 以前完全不读它，于是 pvpid=1 与 pvpid=2 拿到同一批幽灵。
    `owner`：只认某个人自己的幽灵（上传链路用它查「我这条赛道传过没有」）。
      ⚠ 注意 `get_pvp_ghost` 的 `players` 参数是**请求者自己**的 pid，
      不能拿去做 owner 过滤 —— 那会把 named 变成永远空集、静默回落到全部。
    """
    ghost_sync_legacy()
    track_id = mask_track(track_id)
    wanted = set()
    if players:
        for p in str(players).split(","):
            p = p.strip().lower()
            if p and p not in GHOST_ANY_PLAYERS:
                wanted.add(p)
    obj = _load_ghosts()
    cands = []
    for rec in obj["items"].values():
        if track_id is not None and rec.get("track_id") != track_id:
            continue
        if not (rec.get("stored") or rec.get("legacy_path")):
            continue          # 只有 metadata、没有二进制的容器不算
        if pvpid is not None and _as_int(rec.get("pvpid")) != int(pvpid):
            continue
        if owner is not None and str(rec.get("owner") or "") != str(owner):
            continue
        cands.append(rec)
    if not cands:
        return []
    named = [r for r in cands
             if wanted and str(r.get("owner") or "").lower() in wanted]
    pool = named or cands

    def sort_key(r):
        if drive_time:
            gap = abs((r.get("drive_time") or 0) - int(drive_time))
        else:
            gap = 0
        return (0 if r in named else 1, gap, r.get("drive_time") or 0, r.get("contentId") or 0)

    pool = sorted(pool, key=sort_key)
    try:
        n = max(1, int(limit))
    except Exception:
        n = 1
    return pool[:n]


def ghost_list(track_id=None):
    ghost_sync_legacy()
    obj = _load_ghosts()
    out = []
    for rec in obj["items"].values():
        if track_id is not None and rec.get("track_id") != track_id:
            continue
        out.append(rec)
    out.sort(key=lambda r: (r.get("track_id") or 0, r.get("drive_time") or 0))
    return out


def ghost_any_for_track(track_id):
    """给 resultservice 那几个「回原始字节」的端点用：挑该赛道最好的一个。"""
    rows = ghost_search(track_id=track_id, limit=1)
    return rows[0] if rows else None


def ghost_any():
    """库里任意一条**有二进制**的幽灵（不分赛道）。

    ★ 用于 resultservice 那些「回原始字节」的端点兜底。客户端这三个 cmd
      （15/16/18，分支都在 `0x508854`）都带 `cmp w8,#0x65; b.lo 0x5089fc`：
      **响应体小于 101 字节就判 err=7**，而空响应 `{"data": []}` 只有 12 字节
      —— 于是「检索对手中…」永远卡住。幽灵 blob 里不含赛道号
      （`03 00 00 00 | u32 checksum | u32 frames | u32 0 | zlib`），
      所以真的一条都没有时，跨赛道下发在结构上客户端发现不了。
    """
    ghost_sync_legacy()
    obj = _load_ghosts()
    rows = [r for r in obj["items"].values()
            if r.get("stored") or r.get("legacy_path")]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("drive_time") or 0, r.get("contentId") or 0))
    return rows[0]


# ------------------------------------------------------------ 回放登记（replay_id）
def ghost_record_replay(profile_id, track_name, drive_time, faults=None, bike=None,
                        client_ip=None):
    """POST /public/resultservice/v1/replay_id —— 把「谁在哪条赛道跑了多少」记下来。

    响应对客户端没有语义（它只当成功/失败），但记下来能对上后面上传的幽灵。
    """
    rec = {
        "profile_id": profile_id,
        "track_name": track_name,
        "track_id": _as_int(str(track_name or "").replace("track", "")) or None,
        "drive_time": _as_int(drive_time),
        "faults": _as_int(faults),
        "bike": _as_int(bike),
        "client_ip": client_ip,
        "ts": int(time.time()),
    }
    with _LOCK:
        rows = _load(GHOST_REPLAYS, [])
        if not isinstance(rows, list):
            rows = []
        rows.append(rec)
        _store(GHOST_REPLAYS, rows[-500:])
    return rec


def ghost_replays(profile_id=None):
    rows = _load(GHOST_REPLAYS, [])
    if not isinstance(rows, list):
        return []
    if profile_id:
        rows = [r for r in rows if r.get("profile_id") == profile_id]
    return rows
