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
    data/ghosts/<track>/<name>.bin      上传/内置的幽灵文件

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

    if scheme.lower().startswith("ubimobile"):
        info["kind"] = "device"
        info["device_id"] = decoded.split(":")[0] if decoded else ""
        return info

    # 我们自己签发的票据一律是 tf- 开头，不能被误当成"用户名:口令"
    if not token.startswith("tf-") and ":" in decoded:
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
    out = []
    for key, acc in sorted(db.get("users", {}).items()):
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
        dev = device_by_ticket(c)
        if dev:
            return {"kind": "device", "who": "device:" + str(dev.get("deviceId"))[:8],
                    "profileId": dev["profileId"]}, None

    if (not info.get("raw")) or info.get("token") == ANON_TICKET:
        return {"kind": "anon", "who": "<anonymous>", "profileId": ANON_PROFILE_ID}, None
    return None, "unknown-ticket"


def lookup_account(username):
    with _LOCK:
        return _load(ACCOUNTS, {}).get("users", {}).get((username or "").lower())


# ------------------------------------------------------------------ 会话响应
def session_body(acc, ticket, remember_me=False):
    """育碧 /v3/profiles/sessions 的响应体（实测字段）。"""
    if acc:
        pid = acc["profileId"]
        name = acc.get("nameOnPlatform") or acc["username"]
    else:
        pid = ANON_PROFILE_ID
        name = "LocalPlayer"
    return {
        "platformType": "ubimobile",
        "ticket": ticket,
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
    who_info, err = authenticate(headers)
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

    # ★★ 防清档护栏（真机事故复盘）：
    #   客户端在"登录/换 owner/首次同步"这些时序上会把**重置后的默认存档**上报回来
    #   （实测 items2 从 45 对掉到个位数）。一旦覆盖 latest.json，玩家进度就再也回不去。
    #   所以：明显劣化时**只写 history，不覆盖 latest**，并把旧档继续当作可下发来源。
    old = load_progress(pid)
    old_rich = _richness((old or {}).get("content"))
    new_rich = _richness(obj)
    if old and old_rich >= 10 and new_rich * 2 < old_rich:
        print("[save] ⚠ 拒绝用明显更空的存档覆盖 %s（旧 richness=%d -> 新 richness=%d），"
              "新数据已存进 history/%d.json；如需强制接受请删掉 latest.json"
              % (who, old_rich, new_rich, now), flush=True)
        return pid, {"rejected": True, "old_richness": old_rich,
                     "new_richness": new_rich, "saved_at": now, "account": who,
                     "version": int((old or {}).get("version") or 0)}, None

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
    who_info, err = authenticate(headers)
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
