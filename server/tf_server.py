#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trials Frontier 本地服务器（本地存档/离线后端）

阶段目标：先把客户端所有请求记录下来，再逐个端点填响应。

用法：
    python server/tf_server.py --host 0.0.0.0 --port 8000

响应规则放在 server/rules.json（可热改，每次请求重新读取）：
    {
      "POST /v2/profiles/sessions": {
        "status": 200,
        "headers": {"Content-Type": "application/json"},
        "body": {...}
      },
      "*": {"status": 200, "body": {...}}
    }
键格式 "<METHOD> <路径前缀>"；"*" 是兜底。body 是 dict/list 则序列化成 JSON，
是字符串则原样发送（便于塞任意文本）。

日志：
  - 控制台
  - work/trials-frontier/notes/server-log.jsonl（每条请求一行 JSON，含请求/响应体）
"""

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_PATH = os.path.join(ROOT, "work", "trials-frontier", "notes", "server-log.jsonl")
RULES_PATH = os.path.join(HERE, "rules.json")

# 记录最近 N 条请求，便于 /__log 查看
RECENT = []
RECENT_MAX = 400
LOG_LOCK = threading.Lock()

MAX_BODY_LOG = 8192


def load_rules():
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:  # 规则坏了也要能跑，只是打日志
        print("[rules] 解析失败: %r" % (e,), flush=True)
        return {}


# ------------------------------------------------------------------ 动态端点
# 静态 rules.json 表达不了的响应（要现算）放这里。
# 处理器签名：(path, query, body, headers) -> (status, headers, body_obj)
# body_obj 交给 render() 序列化，所以可以是 dict / str / "@文件"。

# tr::OnlineTimeService::verifyChecksum 的盐（libTrialsGo.so @0x00b8526f）
TS_SALT = "c8f68210a7247676aaee552cb6d81c8a"


def h_timeservice(path, query, body, headers):
    """反作弊时钟源。响应被 tr::OnlineTimeService::parseJsonResponse (cmd 0x67) 解析：
    必须同时满足 ret==1、checksum==md5("<time_now>" + TS_SALT)、且 time_now 与设备时钟接近
    （tr::OnlineCore::checkDeviceDate）。缺 checksum 或对象为空 => onTimeServiceResponse(err=7)
    => AntiCheating::newState(0) => 「警报！」反作弊弹窗。"""
    now = int(time.time())
    digest = hashlib.md5(("%d%s" % (now, TS_SALT)).encode("utf-8")).hexdigest()
    return 200, {}, {"ret": True, "time_now": now, "checksum": digest}


# ------------------------------------------------------------ 占位图片
# 商店 / 特供商品里的动态 offer 图，原始地址是
#   https://s3.amazonaws.com/frontieronlinecontent/<name>.png
# 该 bucket 现在返回 NoSuchBucket（素材永久丢失），本地纹理包
# TrialsTexturesDL_android_offericons.dat 里也没有这些动态图，
# 所以这里现画一张占位图发回去，免得页面上出现空白/破图。
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_PLACEHOLDER_PNG = None


def _placeholder_png():
    global _PLACEHOLDER_PNG
    if _PLACEHOLDER_PNG is not None:
        return _PLACEHOLDER_PNG
    import struct
    import zlib
    w = h = 256
    rows = bytearray()
    for y in range(h):
        rows.append(0)                      # 每行的 filter type = 0
        for x in range(w):
            edge = min(x, y, w - 1 - x, h - 1 - y)
            if edge < 6:
                r, g, b = 0xC8, 0xA0, 0x5A  # 金色外框
            elif edge < 9:
                r, g, b = 0x24, 0x16, 0x0E  # 深色内衬
            else:
                fy = y / (h - 1)
                r = int(0x3A + 0x42 * (1 - fy))
                g = int(0x24 + 0x24 * (1 - fy))
                b = int(0x18 + 0x10 * (1 - fy))
                if ((x + y) // 24) % 2 == 0:  # 淡淡的斜纹，避免纯色块
                    r = min(255, r + 8)
                    g = min(255, g + 6)
                    b = min(255, b + 4)
            rows += bytes((r, g, b))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    _PLACEHOLDER_PNG = (b"\x89PNG\r\n\x1a\n"
                        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
                        + chunk(b"IEND", b""))
    return _PLACEHOLDER_PNG


def h_placeholder_image(path, query, body, headers):
    return 200, {"Content-Type": "image/png"}, _placeholder_png()


# ------------------------------------------------------ 本地账号 / 存档 / 幽灵
# 见 server/tflocal_accounts.py。三个动态端点的角色：
#   POST /v1/profiles/sessions     用户名密码登录（凭据真的会被校验）
#   POST /v3/profiles/sessions     设备静默登录（匿名，沿用固定 profileId）
#   POST /public/playerprogress/v1/progress   客户端上传的完整存档，落盘
try:
    import tflocal_accounts as acct
except ImportError:  # 允许把 tf_server.py 单独拷走
    sys.path.insert(0, HERE)
    import tflocal_accounts as acct

ANON_TICKET = "tf-local-ticket-0001"


def _json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


def h_session(path, query, body, headers):
    """育碧会话端点。用户名密码来自 Authorization: Ubi_v1 t=base64("user:pass")。"""
    info = acct.parse_authorization(headers)
    js = _json_body(body)
    username = info.get("username") or js.get("username") or js.get("email")
    password = info.get("password") or js.get("password")
    remember = bool(js.get("rememberMe"))

    if info.get("kind") == "basic" and username:
        acc = acct.ensure_account(username, password,
                                  name_on_platform=js.get("nameOnPlatform"))
        if acc is None:
            return 401, {"Content-Type": "application/json"}, {"error": "invalid credentials"}
        ticket = acct.issue_session(acc)
        return 200, {"Content-Type": "application/json"}, acct.session_body(acc, ticket, remember)

    # 设备静默登录：按设备 id 分配独立的 profileId，
    # 这样不登录的多台设备不会挤在同一个槽里互相覆盖存档。
    if info.get("kind") == "device":
        dev = acct.ensure_device(info.get("device_id"))
        if dev is not None:
            return 200, {"Content-Type": "application/json"}, \
                acct.session_body(dev, dev["ticket"], remember)

    # 既没有凭据也没有设备 id：保持旧的匿名槽（兼容已存在的老存档）
    acc = acct.account_by_ticket(ANON_TICKET)
    return 200, {"Content-Type": "application/json"}, acct.session_body(acc, ANON_TICKET, remember)


def h_progress(path, query, body, headers):
    """客户端把完整存档 POST 上来。归属严格按凭据走，凭据不对回 401。

    ★ 响应形状不是随便写的：`OnlinePlayerProgress::parseResponse` @0x57433c 的
      **cmd 0x21**（syncProgress @0x573798 那条 POST）分支只读两个 int 键 ——
      `version`@0xb4056d 和 `time_stamp`@0xb89a9c，读到后 `DebugOut::add(
      "SYNCED TO VERSION %d")` 并写进 `Player+0x4864`（客户端记的"本地版本"）。
      以前回 `{"data": []}` ⇒ 本地版本恒为 0 ⇒ 客户端每次都认为"和服务器一致"，
      于是把自己的存档推上来（这才是覆盖服务器存档的元凶）。
    """
    pid, brief, err = acct.save_progress(headers, body, _client_ip(headers))
    if err:
        print("[save] 拒绝越权/无效凭据的存档上报：%s" % err, flush=True)
        return 401, {"Content-Type": "application/json"}, {"error": err}
    if pid:
        brief["ok"] = True
    return 200, {"Content-Type": "application/json"}, {
        "version": int(brief.get("server_version") or 0),
        "time_stamp": int(brief.get("saved_at") or 0),
    }


def h_progress_version(path, query, body, headers):
    """GET /public/playerprogress/v1/progress/version —— 版本比对（cmd 0x22）。

    响应必须是 `{"version": N, "time_stamp": T}`（见 acct.progress_version 的说明）。
    N == 客户端本地版本（或 0）时客户端会把本地存档推上来；
    N 不同且非 0 时游戏会拉起自己的"进度同步"界面，让玩家选择用云端还是用本地。
    真机清档事故后，这里改成回**真实服务器版本**，玩家才有恢复入口。
    """
    pid, ver, ts, note = acct.progress_version(headers, _client_ip(headers))
    print("[save] 版本比对：pid=%s note=%s -> version=%d time_stamp=%d"
          % (pid, note, ver, ts), flush=True)
    return 200, {"Content-Type": "application/json"}, {"version": ver, "time_stamp": ts}


def h_progress_status(path, query, body, headers):
    """GET /public/playerprogress/v1/progress/status —— 云端进度摘要（cmd 0x25）。

    `OnlinePlayerProgress::parseStatus` @0x00574d7c 按成员名取 5 个 int：
      coins@0 / diamonds@4 / missions_completed@8 / player_level@0xc / player_points@0x18。
    返回值是 `[status+8] != 0`（即 missions_completed 非 0 才算"有效"），
    `parseResponse` 里 `tbz w0,#0` 为 0 时走 error 分支。金币/宝石从 items2 里取
    （实测 items2 的 id 1 = 金币、id 2 = 宝石）。
    """
    pid, content, note = acct.serve_progress(headers, _client_ip(headers))
    coins = gems = 0
    items = (content or {}).get("items2") or []
    for i in range(0, len(items) - 1, 2):
        if items[i] == 1:
            coins = int(items[i + 1] or 0)
        elif items[i] == 2:
            gems = int(items[i + 1] or 0)
    missions = len(((content or {}).get("missions2") or {}).get("solved") or [])
    print("[save] 云端摘要：pid=%s note=%s coins=%d gems=%d missions=%d"
          % (pid, note, coins, gems, missions), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "coins": coins,
        "diamonds": gems,
        "missions_completed": missions,
        "player_level": 0,
        "player_points": 0,
    }


def h_progress_latest(path, query, body, headers):
    """GET /public/playerprogress/v1/progress —— **下发给客户端的存档**。

    ★★ 这是真机清档事故的那个端点，必须看成"会把玩家本地存档覆盖成我返回的东西"：
       tr::OnlinePlayerProgress::parseResponse @0x57433c（cmd 0x24）解析完 JSON 之后
       会无条件调用 tr::Player::save() @0x362bc0。所以：
         · 有存档 -> 原样回客户端当初 POST 上来的那份 content（键名天然一致）；
         · 一份都没有 -> 回 **404**（让客户端走 onNetworkError @0x574198），
           **绝对不能回 {} / {"data": []}**，那等于把玩家进度清零。
       响应键就是 parseProgress @0x574780 认识的那套（客户端上传用的同一套）：
       version / game_version / items(2) / missions(2) / statistics(2) / achievements(2) /
       tutorials(2) / timers(2) / highscores(2) / upgrades / store_bonus /
       dailyexperience / robotman / profile / settings / identifier。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    pid, content, note = acct.serve_progress(headers, _client_ip(headers))
    if not content:
        print("[save] 下发请求但没有可用存档（%s）-> 404，避免客户端清档" % note, flush=True)
        return 404, {"Content-Type": "application/json"}, {"error": "no saved progress"}
    keys = [k for k in ("version", "game_version", "identifier") if k in content]
    print("[save] 下发存档 pid=%s note=%s 顶层键=%d %s"
          % (pid, note, len(content), ",".join(keys)), flush=True)
    if q.get("download") not in ("1", "true", "yes"):
        # 不带 download 参数也照发：客户端只在这一条路径上取存档，
        # 早期"默认回空"的做法正是清档的元凶。
        pass
    return 200, {"Content-Type": "application/json"}, content


def h_progress_swap(path, query, body, headers):
    """POST /public/playerprogress/v1/swap —— 账号切换时"换进度所有者"。

    tr::OnlinePlayerProgress::switchProgressOwner @0x5740b0 发这个请求（cmd 0x26），
    响应由 parseResponse @0x57433c 里 0x57459c 那段处理：找成员名 `identifier`
    (@0xba7808)，它的字符串值必须 **长度 ≥ 6**，然后 strcpy 进 Player+0x6be0、
    以 error=0 回调 onProgressSwap、再 Player::save()。

    所以只要回 {"identifier": "<≥6 字符>"} 就是成功。这里顺便先跑一次收养，
    保证换 owner 之后立刻能拿到（或继承到）存档。
    """
    pid, content, note = acct.serve_progress(headers, _client_ip(headers))
    ident = (content or {}).get("identifier") or pid or ""
    if len(str(ident)) < 6:
        ident = pid or acct.ANON_PROFILE_ID
    print("[swap] 进度换 owner：owner=%s note=%s -> identifier=%s"
          % (pid, note, ident), flush=True)
    return 200, {"Content-Type": "application/json"}, {"identifier": ident}


def _client_ip(headers):
    """从请求头里掏客户端 IP（tf_server 会把真实来源塞进 X-TF-Client）。"""
    return (headers or {}).get("X-TF-Client") or None


def _caller_profile(headers):
    info, err = acct.authenticate(headers)
    if info:
        return info["profileId"]
    return acct.ANON_PROFILE_ID


def h_profile_me(path, query, body, headers):
    info, _ = acct.authenticate(headers)
    acc = None
    if info and info["kind"] == "account":
        acc = acct.lookup_account(info["who"])
    elif info and info["kind"] == "device":
        acc = acct.device_by_profile(info["profileId"])
    return 200, {"Content-Type": "application/json"}, acct.profile_body(acc)


def h_profiles_query(path, query, body, headers):
    """OnlineFriends::resolveOnlineIds 走 %s/v1/profiles?profileId=…（.rodata @0xb89064）。"""
    me = h_profile_me(path, query, body, headers)[2]
    wanted = []
    for k, v in parse_qsl(query, keep_blank_values=True):
        if k.lower() == "profileid":
            wanted += [x for x in v.split(",") if x]
    out = [me]
    seen = {me["profileId"]}
    for pid in wanted:
        if pid in seen:
            continue
        seen.add(pid)
        out.append({
            "profileId": pid, "userId": pid, "platformType": "ubimobile",
            "idOnPlatform": pid,
            "nameOnPlatform": FRIEND_NAMES.get(pid, "Player" + pid[:4]),
        })
    return 200, {"Content-Type": "application/json"}, {"profiles": out}


FRIEND_NAMES = {
    "44444444-4444-4444-4444-444444444444": "GhostRider",
    "55555555-5555-5555-5555-555555555555": "TangoPro",
}


# -------------------------------------------------------------- 幽灵 / 内购
# 幽灵文件格式（实测解出，见 server/data/ghosts/README.md）：
#   0x00 u32 version=3 ; 0x04 u32 tag ; 0x08 u32 解压后长度 ; 0x0c u32 0
#   0x10 ... zlib 流；解压后 0x00 u32=1, 0x04 u32=该次跑的时间(ms),
#   0x08 u32=帧数, 0x0c u32=0, 0x10 起是帧数据。
# 客户端侧 tr::OnlineGhostManagerListener::onGhostReceived(TR_ONLINE_ERROR,int,void*,int,int)
# 说明幽灵是以「原始字节 + 长度」回调的，所以这里直接把 .bin 原样发回去。
_GHOST_HINT = ("ghost", "replaydata")


def _looks_like_ghost(path):
    p = path.lower()
    return any(h in p for h in _GHOST_HINT)


def h_ghost(path, query, body, headers):
    q = dict(parse_qsl(query, keep_blank_values=True))
    track = q.get("track_id") or ""
    if not track:
        seg = path.rstrip("/").split("/")[-1]
        if seg.isdigit():
            track = seg
    player = (q.get("player") or q.get("players") or "").split(",")[0].strip()
    names = acct.list_ghosts(track) if track else []
    if names:
        pick = names[-1]
        for n in names:                       # 优先匹配请求里点名的玩家
            if player and player.lower().lstrip("0x") in n.lower():
                pick = n
                break
        blob = acct.load_ghost(track, pick)
        if blob:
            print("[ghost] 赛道 %s -> %s (%d 字节)" % (track, pick, len(blob)), flush=True)
            return 200, {"Content-Type": "application/octet-stream"}, blob
    # 本地没有该赛道的幽灵：保持历史行为（客户端能安全消化 {"data": []}）
    return 200, {"Content-Type": "application/json"}, {"data": []}


def h_ghost_upload(path, query, body, headers):
    """客户端核对/上报幽灵时把二进制塞进来，落盘备用。"""
    q = dict(parse_qsl(query, keep_blank_values=True))
    track = q.get("track_id") or ""
    raw = body if isinstance(body, (bytes, bytearray)) else b""
    if track and raw[:4] == b"\x03\x00\x00\x00":
        p = acct.store_ghost(track, "upload_%s_%d.bin" % (q.get("player", "anon")[:12], int(time.time())), bytes(raw))
        print("[ghost] 收到上传 赛道 %s -> %s (%d 字节)" % (track, p, len(raw)), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


def h_iap_verify(path, query, body, headers):
    """收据校验。原来走兜底 {"data": []}（等于失败），这里改成明确放行。

    端点由 .rodata @0xb8c81c 的 '%s/public/receiptvalidation/v1/%s?pid=%s&uid=%s&transaction_id=%s'
    拼出，第二个 %s 实测值是 'verify_android'（@0xb8c80d）。日志串：
    'VALIDATION RESPONSE: %d' / 'VALIDATION RESPONSE: %s'（@0xb8c89c / @0xb8c8cd）。
    ⚠ 响应字段名没有实测验证过，这里是尽力而为的放行写法。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    print("[iap] verify_android pid=%s uid=%s tx=%s"
          % (q.get("pid"), q.get("uid"), q.get("transaction_id")), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "valid": True, "status": 0, "errorCode": 0, "ret": True,
        "product_list": [], "data": [],
    }


def h_iap_products(path, query, body, headers):
    """内购商品表 / 限购配置。响应形状已从 `tr::StoreManager::parseResponse`

    （libTrialsGo.so @0x57b1dc，cmd 0x19 分支直接把 **json 根** 交给
    `parseStoreConfiguration` @0x57b30c）反汇编出来：

        parseResponse: json_parse(text) -> root；cmd==0x19 -> parseStoreConfiguration(this, root)
        parseStoreConfiguration: 遍历 root 的顶层成员，找名为 "limited_purchases"
            (@0xb8c8e5) 的成员；命中后遍历它的每个元素对象，逐个读这 5 个键：
              "name"          @0xbb3f5e  (字符串)
              "product_id"    @0xbaaa7d  (字符串)
              "limit"         @0xbb3a74  (int)
              "counter"       @0xb8c8fc  (int)
              "fake_counter"  @0xb8c8f7  (int)
            每个元素被 _M_emplace_back_aux 追加进 std::vector<tr::ServerStoreItemData>。

    所以正确的响应是 **顶层键** `limited_purchases`（不是 "product_list"）：

        {"limited_purchases": [ {"name":..., "product_id":..., "limit":N,
                                 "counter":N, "fake_counter":N}, ... ]}

    返回空数组是安全的（遍历零次），而且比 `{}` 安全得多。
    （`product_list` @0xb86bf3 那个串其实属于 `tr::OnlinePVP::parseSeason`，跟内购无关 ——
     早期笔记把它误记成内购键了。）
    """
    print("[iap] product/configuration 被请求", flush=True)
    return 200, {"Content-Type": "application/json"}, {"limited_purchases": []}


DYNAMIC_EXACT = [
    ("POST", "/v1/profiles/sessions", h_session),
    ("POST", "/v3/profiles/sessions", h_session),
    ("POST", "/public/playerprogress/v1/progress", h_progress),
    ("GET", "/public/playerprogress/v1/progress", h_progress_latest),
    ("GET", "/public/playerprogress/v1/progress/version", h_progress_version),
    ("GET", "/public/playerprogress/v1/progress/status", h_progress_status),
    ("POST", "/public/playerprogress/v1/swap", h_progress_swap),
    ("GET", "/v2/profiles/me", h_profile_me),
    ("GET", "/v1/profiles", h_profiles_query),
    ("GET", "/public/receiptvalidation/v1/product/configuration", h_iap_products),
    ("GET", "/public/receiptvalidation/v1/verify_android", h_iap_verify),
    ("POST", "/public/receiptvalidation/v1/verify_android", h_iap_verify),
]

DYNAMIC = [
    ("GET", "/public/timeservice/v1/gettime", h_timeservice),
]


def pick_dynamic(method, path):
    # 图片与好友头像：<base>/<pid>/picture?width=..&height=..（见 .rodata @0xb887cc）
    if method == "GET" and (path.lower().endswith(_IMAGE_EXT) or path.endswith("/picture")):
        return h_placeholder_image, "dyn:placeholder-image"
    for m, p, fn in DYNAMIC_EXACT:
        if m == method and path == p:
            return fn, "dyn:%s %s" % (m, p)
    # 幽灵：resultservice 下的 ghost / replaydata（GET 取幽灵，POST 上传幽灵）
    if _looks_like_ghost(path) and path.startswith("/public/resultservice/"):
        return (h_ghost_upload if method == "POST" else h_ghost), "dyn:ghost"
    for m, prefix, fn in DYNAMIC:
        if m == method and path.startswith(prefix):
            return fn, "dyn:%s" % prefix
    return None, None


def pick_rule(rules, method, path):
    key = "%s %s" % (method, path)
    if key in rules:
        return rules[key], key
    # 前缀匹配，取最长
    best = None
    for k in rules:
        if k == "*" or " " not in k:
            continue
        m, _, p = k.partition(" ")
        if m != method:
            continue
        if path.startswith(p):
            if best is None or len(p) > len(best[1]):
                best = (rules[k], p)
    if best:
        return best[0], "prefix:%s" % best[1]
    if method + " *" in rules:
        return rules[method + " *"], method + " *"
    if "*" in rules:
        return rules["*"], "*"
    # 默认：200 空 JSON 对象
    return {"status": 200, "headers": {"Content-Type": "application/json"}, "body": {}}, "default"


def render(rule):
    status = int(rule.get("status", 200))
    headers = dict(rule.get("headers") or {})
    body = rule.get("body", {})
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    elif isinstance(body, (dict, list)):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif body is None:
        raw = b""
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = str(body).encode("utf-8")
    # allow <path>:bodyfile 形式的外部文件
    if isinstance(body, str) and body.startswith("@"):
        p = body[1:]
        p = p if os.path.isabs(p) else os.path.join(HERE, p)
        try:
            with open(p, "rb") as f:
                raw = f.read()
        except Exception as e:
            print("[rules] 读不到 body 文件 %s: %r" % (p, e), flush=True)
    return status, headers, raw


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TFLocal/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):  # 关掉默认 stderr 噪声
        pass

    # ---------- 工具 ----------
    def _read_body(self):
        n = self.headers.get("Content-Length")
        if n:
            try:
                return self.rfile.read(int(n))
            except Exception:
                return b""
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            chunks = []
            while True:
                line = self.rfile.readline().strip()
                try:
                    sz = int(line.split(b";")[0], 16)
                except Exception:
                    break
                if sz == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(sz))
                self.rfile.readline()
            return b"".join(chunks)
        return b""

    def _handle(self, method):
        t0 = time.time()
        raw_path = self.path
        sp = urlsplit(raw_path)
        path, query = sp.path, sp.query
        body = self._read_body()

        # 内省端点
        if path == "/__log":
            with LOG_LOCK:
                data = json.dumps(RECENT[-100:], ensure_ascii=False, indent=1).encode("utf-8")
            self._send(200, {"Content-Type": "application/json"}, data)
            return
        if path == "/__ping":
            self._send(200, {"Content-Type": "text/plain"}, b"pong\n")
            return
        if path.startswith("/__"):
            if self._introspect(path, query):
                return

        dyn, which = pick_dynamic(method, path)
        if dyn is not None:
            hdrs = {k: v for k, v in self.headers.items()}
            # 把真实来源 IP 塞进请求头，供 save_progress / serve_progress 判断
            # "同一台设备"（登录后继承匿名槽存档）用。客户端自己发的同名头会被覆盖。
            hdrs["X-TF-Client"] = self.client_address[0] if self.client_address else ""
            st, hd, obj = dyn(path, query, body, hdrs)
            status, headers, raw = render({"status": st, "headers": hd, "body": obj})
        else:
            rules = load_rules()
            rule, which = pick_rule(rules, method, path)
            status, headers, raw = render(rule)
        self._send(status, headers, raw)

        entry = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "method": method,
            "url": raw_path,
            "path": path,
            "query": dict(parse_qsl(query, keep_blank_values=True)),
            "req_headers": {k: v for k, v in self.headers.items()},
            "req_body": body[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "req_body_len": len(body),
            "rule": which,
            "status": status,
            "resp_body": ("<binary %d bytes>" % len(raw)) if which.startswith("dyn:placeholder-image")
                         else raw[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "ms": round((time.time() - t0) * 1000, 1),
        }
        line = json.dumps(entry, ensure_ascii=False)
        with LOG_LOCK:
            RECENT.append(entry)
            if len(RECENT) > RECENT_MAX:
                del RECENT[: len(RECENT) - RECENT_MAX]
            try:
                os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass
        # 控制台精简输出
        mark = "" if which == "default" else ("  <- " + which)
        print(
            "%-6s %-70s -> %d  %4dms%s"
            % (method, (path + ("?" + query if query else ""))[:70], status, entry["ms"], mark),
            flush=True,
        )
        if body:
            print("        REQ  %s" % body[:400].decode("utf-8", "replace").replace("\n", " "), flush=True)
        if which == "default":
            print("        RESP %s" % raw[:200].decode("utf-8", "replace").replace("\n", " "), flush=True)
        elif which == "dyn:placeholder-image":
            print("        RESP <占位 PNG %d bytes>" % len(raw), flush=True)

    def _introspect(self, path, query):
        """本地管理端点：/__accounts /__saves /__save /__sessions /__ghosts"""
        q = dict(parse_qsl(query, keep_blank_values=True))
        if path == "/__ping":
            self._send(200, {"Content-Type": "text/plain"}, b"pong\n")
            return True

        def js(obj, status=200):
            self._send(status, {"Content-Type": "application/json"},
                       json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
            return True

        if path == "/__accounts":
            db = acct._load(acct.ACCOUNTS, {}).get("users", {})
            return js({"count": len(db), "accounts": [
                {k: v for k, v in a.items() if k not in ("pw", "salt")} for a in db.values()]})
        if path == "/__devices":
            devs = acct.list_devices()
            return js({"count": len(devs), "devices": devs})
        if path == "/__sessions":
            db = acct._load(acct.SESSIONS, {})
            return js({"count": len(db), "sessions": db})
        if path == "/__saves":
            return js({"saves": acct.list_saves()})
        if path == "/__save":
            pid = q.get("profile") or acct.ANON_PROFILE_ID
            got = acct.load_progress(pid)
            if not got:
                return js({"error": "no save for %s" % pid}, 404)
            return js(got)
        if path == "/__history":
            pid = q.get("profile") or acct.ANON_PROFILE_ID
            return js({"profileId": pid, "history": acct.list_history(pid)})
        if path == "/__restore":
            pid = q.get("profile") or acct.ANON_PROFILE_ID
            ts = q.get("ts") or "latest"
            got = acct.restore_save(pid, ts)
            if not got:
                return js({"error": "no snapshot %s for %s" % (ts, pid)}, 404)
            return js({"ok": True, "profileId": pid, "ts": ts})
        if path == "/__ghosts":
            root = acct.GHOST_DIR
            out = {}
            if os.path.isdir(root):
                for t in sorted(os.listdir(root)):
                    out[t] = acct.list_ghosts(t)
            return js({"ghosts": out})
        if path == "/__help":
            return js({"endpoints": ["/__ping", "/__log", "/__accounts", "/__devices",
                                     "/__sessions", "/__saves", "/__save?profile=<pid>",
                                     "/__history?profile=<pid>",
                                     "/__restore?profile=<pid>&ts=<时间戳|latest>",
                                     "/__ghosts"]})
        return False

    def _send(self, status, headers, raw):
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            if not any(k.lower() == "content-length" for k in headers):
                self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_OPTIONS(self):
        self._handle("OPTIONS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if not os.path.exists(RULES_PATH):
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            json.dump({"*": {"status": 200, "body": {}}}, f, indent=2)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("Trials Frontier 本地服务器已启动： http://%s:%d" % (args.host, args.port), flush=True)
    print("规则文件： %s" % RULES_PATH, flush=True)
    print("请求日志： %s" % LOG_PATH, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("停止。", flush=True)


if __name__ == "__main__":
    main()
