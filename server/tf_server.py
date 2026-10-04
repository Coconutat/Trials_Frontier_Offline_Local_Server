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
import re
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

# ★ Windows 控制台默认是 GBK，而二进制上传（幽灵 payload）被解码成含 U+FFFD 的
# 字符串后 print 会抛 UnicodeEncodeError —— 虽然响应已经发出去了，但那条日志会
# 丢掉，控制台还会刷一堆 Traceback。统一把标准流改成 UTF-8 + errors="replace"。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
        # ROADMAP 第 2 条：登录只查库，**不再自动注册**。
        # 账号必须先在 http://<服务器>:8000/__register 上注册。
        acc, err = acct.login_account(username, password)
        if acc is None:
            print("[acct] 会话请求被拒：%s（%s）" % (username, err), flush=True)
            return 401, {"Content-Type": "application/json"}, {
                "error": err or "invalid-credentials",
                "errorCode": "NOT_REGISTERED" if err == "not-found" else "INVALID_CREDENTIALS",
                "message": ("此账号尚未在本地服务器注册，请先打开 "
                            "http://<服务器IP>:8000/__register 注册" if err == "not-found"
                            else "用户名或密码不正确"),
            }
        ticket = acct.issue_session(acc)
        # ★ 登录固化：把长期凭据一并发下去，客户端会存进安全存储，
        #   下次启动就能静默换会话，不必再让玩家手输账号（见 tflocal_accounts
        #   里 issue_remember_ticket 的反汇编依据）。
        rm = acct.issue_remember_ticket(acc)
        return 200, {"Content-Type": "application/json"}, \
            acct.session_body(acc, ticket, remember, remember_ticket=rm)

    # ★ 登录固化的静默换会话：客户端拿我们发过的长期凭据（rememberMeTicket）
    #   或普通会话票来换新会话，不该再退化成匿名槽。
    #   依据：Playground::Credentials::Convert() @0x1903c4 的 type=7 分支
    #   会把 rememberMeTicket 当票据重新走一次会话建立。
    # 登录固化：票据既可能出现在 Authorization 头，也可能被放在请求体里，
    # 两条路径都要认（SDK 的 PlayerCredentials 走头，但保不齐换个版本走体）。
    body_tok = js.get("rememberMeTicket") or js.get("ticket")
    if info.get("kind") == "bearer" or (body_tok and not username):
        tok = info.get("ticket") or body_tok
        acc = acct.account_by_remember_ticket(tok) or acct.account_by_ticket(tok)
        if acc is not None:
            rm = acct.issue_remember_ticket(acc)
            return 200, {"Content-Type": "application/json"}, \
                acct.session_body(acc, acct.issue_session(acc), True, remember_ticket=rm)
        dev = acct.device_by_ticket(tok)
        if dev is not None:
            return 200, {"Content-Type": "application/json"}, \
                acct.session_body(dev, dev["ticket"], remember)

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
        # ★ 排行榜的数据源：存档里的 highscores2 是**玩家自己的最佳成绩表**，
        #   真正跑过的图 drivetime > 0，没跑过的是 `[track, 0, 256, 0, 0]`。
        #   直接从存档同步，榜单就和玩家的实际进度永远一致，
        #   也不会出现"客户端只提交了一部分成绩"导致榜单缺图的情况。
        n = _ingest_highscores(pid, _json_body(body))
        if n:
            print("[rank-save] profile=%s 从存档同步了 %d 条赛道成绩" % (pid, n), flush=True)
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

# 幽灵协议（反汇编 tmp/libcmp/orig-libTrialsGo.so 得到，见 notes）：
#   tr::OnlineUserStorage 的资源名恒为 "ghost"，URL 模板 @0xb8c6d4 / 0xb8c6f4 /
#   0xb8c71f / 0xb8c741：
#     %s/%s/userstorage/v2/content/%s                建容器（POST，需回 contentId）
#     %s/%s/userstorage/v2/content/%s/%d/payload     取/传二进制
#     %s/%s/userstorage/v2/content/%s/%d             取/改/删 metadata
#     %s/%s/userstorage/v2/search/%s/%s              按 tag 检索
#   tag @0xb87a8e / 0xb87ab7 / 0xb87af4：
#     get_ghost?track_id=%d&players=%s&limit=1
#     get_ghost_timed?track_id=%d&players=%s&drive_time=%d&limit=1
#     get_pvp_ghost?track_id=%d&players=%s&limit=1&pvpid=%d
#   建容器的响应由 parseJsonResponse @0x578a08 解析，只认**顶层整型键 contentId**
#   （@0xb87d21）；检索的响应由 GhostQueryObject::onQueryCompleted @0x508288 解析，
#   要的是 {"contents":[{"contentId":<int>,"metadata":{...}}]}（contents @0xb87d18，
#   metadata 必须是**对象**，字符串会让它按成员链表去读而崩）。
_USERSTORAGE_RE = re.compile(r"^/public/userstorage/v2/(content|search)/ghost(?:/(.*))?$")


def _looks_like_ghost(path):
    p = path.lower()
    return any(h in p for h in _GHOST_HINT)


def _ghost_caller(headers):
    """取调用者的 profileId（认不出就返回 None，不影响功能）。"""
    try:
        info, _err = acct.authenticate(headers)
    except Exception:
        info = None
    if isinstance(info, dict):
        return info.get("profileId")
    return None


def _ghost_metadata(body):
    """客户端发的 body 是 {"metadata": {...}}；兼容直接给 metadata 的情况。

    ⚠ 处理器拿到的 body 是**原始字节**（`_handle` 只读流、不做解析），
    所以这里必须先自己 JSON 解析——踩过这个坑：不解析会静默拿到空元数据，
    赛道号丢失，幽灵就永远检索不到。
    """
    if isinstance(body, (bytes, bytearray)):
        body = _json_body(body)
    if isinstance(body, dict):
        md = body.get("metadata")
        if isinstance(md, dict):
            return md
    return {}


def h_userstorage(method, path, query, body, headers):
    """userstorage v2 的幽灵内容仓库（客户端上传/检索自己的幽灵走这条）。"""
    m = _USERSTORAGE_RE.match(path)
    if not m:
        return 200, {"Content-Type": "application/json"}, {"data": []}
    kind, rest = m.group(1), (m.group(2) or "").strip("/")
    q = dict(parse_qsl(query, keep_blank_values=True))
    owner = _ghost_caller(headers)

    if kind == "content":
        parts = [p for p in rest.split("/") if p] if rest else []
        cid = None
        if parts and parts[0].lstrip("-").isdigit():
            cid = int(parts[0])
            tail = parts[1] if len(parts) > 1 else ""
        else:
            tail = ""

        # POST /content/ghost —— 建容器，必须回真实 contentId
        if method == "POST" and cid is None:
            md = _ghost_metadata(body)
            track = md.get("track_id")
            try:
                track = int(track) if track is not None else None
            except Exception:
                track = None
            new_id = acct.ghost_create(track, owner, md)
            print("[ghost] create 赛道 %s -> contentId=%d owner=%s"
                  % (track, new_id, owner), flush=True)
            return 200, {"Content-Type": "application/json"}, {"contentId": new_id}

        if cid is None:
            return 200, {"Content-Type": "application/json"}, {"data": []}

        # PUT /content/ghost/<id>/payload —— 传二进制
        if tail == "payload" and method == "PUT":
            raw = body if isinstance(body, (bytes, bytearray)) else b""
            rec = acct.ghost_put_payload(cid, bytes(raw))
            if rec is None:
                print("[ghost] payload id=%d 不存在，仍然接收（%d 字节）" % (cid, len(raw)),
                      flush=True)
                return 200, {"Content-Type": "application/json"}, {"contentId": cid}
            print("[ghost] payload id=%d 赛道 %s %d 字节 drive_time=%s frames=%s"
                  % (cid, rec.get("track_id"), len(raw), rec.get("drive_time"),
                     rec.get("frames")), flush=True)
            return 200, {"Content-Type": "application/json"}, {"contentId": cid}

        # GET /content/ghost/<id>/payload —— 回二进制
        if tail == "payload":
            blob = acct.ghost_payload(cid)
            if blob:
                print("[ghost] 下发幽灵 id=%d (%d 字节)" % (cid, len(blob)), flush=True)
                return 200, {"Content-Type": "application/octet-stream"}, blob
            return 200, {"Content-Type": "application/json"}, {"data": []}

        # PUT /content/ghost/<id> —— 更新 metadata（body 里没有 track_id，靠合并）
        if method == "PUT" and not tail:
            md = _ghost_metadata(body)
            rec = acct.ghost_update(cid, md, owner)
            if rec is None:
                new_id = acct.ghost_create(None, owner, md)
                print("[ghost] update id=%d 不存在，补建 contentId=%d" % (cid, new_id),
                      flush=True)
                return 200, {"Content-Type": "application/json"}, {"contentId": new_id}
            print("[ghost] 更新 metadata id=%d 赛道 %s drive_time=%s"
                  % (cid, rec.get("track_id"), rec.get("drive_time")), flush=True)
            return 200, {"Content-Type": "application/json"}, {"contentId": cid}

        if method == "DELETE" and not tail:
            acct.ghost_delete(cid)
            return 200, {"Content-Type": "application/json"}, {"data": []}

        # GET /content/ghost/<id> —— 取 metadata
        rec = acct.ghost_get(cid)
        if rec:
            return 200, {"Content-Type": "application/json"}, {
                "contentId": cid,
                "metadata": rec.get("metadata") or {},
            }
        return 200, {"Content-Type": "application/json"}, {"data": []}

    # search/<tag>?...
    tag = rest or ""
    def _num(name, default=None):
        try:
            return int(q.get(name))
        except Exception:
            return default

    track = _num("track_id")
    limit = _num("limit", 1)
    drive_time = _num("drive_time")
    rows = acct.ghost_search(track_id=track, players=q.get("players"),
                             limit=limit, drive_time=drive_time)
    print("[ghost] search %s 赛道 %s players=%s -> %d 个"
          % (tag, track, q.get("players"), len(rows)), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "contents": [{"contentId": r.get("contentId"),
                      "metadata": r.get("metadata") or {}} for r in rows]
    }


def h_ghost(path, query, body, headers):
    """resultservice 下的幽灵端点：这些回的是**原始幽灵字节**。

    实测调用顺序（玩家跑完一条赛道）：
      POST .../enhancestats/track<ID>            成绩落库
      GET  .../replaydata?track_id=<ID>          问「服务器上有没有我这条赛道的回放」
      （随后客户端才走 userstorage 上传幽灵，见 h_userstorage）
    所以 replaydata 的 query 形式**故意继续回 {"data": []}**：这是在问
    「有没有」，回「没有」客户端才会老老实实把新幽灵传上来。真正的下载走
    userstorage 的 search/content，以及 replaydata 的路径形式。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    seg = path.rstrip("/").split("/")[-1]
    track = q.get("track_id") or (seg if seg.isdigit() else "")
    tracking = int(track) if str(track).isdigit() else None

    if "/replaydata" in path and not seg.isdigit() and q.get("track_id"):
        return 200, {"Content-Type": "application/json"}, {"data": []}

    if tracking:
        rec = acct.ghost_any_for_track(tracking)
        if rec:
            blob = acct.ghost_payload(rec.get("contentId"))
            if blob:
                print("[ghost] %s 赛道 %s -> contentId=%s (%d 字节)"
                      % (path, tracking, rec.get("contentId"), len(blob)), flush=True)
                return 200, {"Content-Type": "application/octet-stream"}, blob
    return 200, {"Content-Type": "application/json"}, {"data": []}


# ---------------------------------------------------------------------------
# A.N.B.A（Robotman）支线的假机器人对手
# ---------------------------------------------------------------------------
# 客户端链路（`tmp/libcmp/orig-libTrialsGo.so` 逐指令反汇编确认）：
#   tr::OnlineRobotMission::findOpponent(track, range, flag)          @0x501fcc
#     -> tr::MatchMaking::getRobot(listener, track, range, offset)    @0x4f8fdc
#        URL @0xb86327 = "%s/%s/match/v1/robot?track_name=track%d&range=%d&offset=%d"
#        cmd = 0x47
#     -> tr::MatchMaking::parseJsonResponse(cmd=0x47) 分支：
#        parseMatchMakingResult()，把 result[0] 置 3，err 恒 0
#     -> tr::OnlineRobotMission::onMatchMakingComplete(err, res)      @0x5021fc
#          res[0] 必须 == 3
#          strcpy(this+0xad, res+0x85)   <- 对手显示名
#          this+0xec = res+0xc8          <- drivetime
#        -> tr::OnlineGhostManager::getRobotGhost(this+8, track, name, drivetime)
#           URL @0xb87a48 = ".../resultservice/v1/robot_replaydata?track_id=%d&time=%d&player=%s"
#        -> onGhostReceived(...) 落盘 robot_ghost-<hash(name)>-<track>.robot
#        -> OnlineUbiservices::getPlayerProfile(this+0x10, name)      @0x517448
#           URL @0xb89137 = "<ubi>/v1/profiles/%s"
#        -> onProfilesQueryCompleted: strcpy(this+0x2c, ProfileQueryData+0x48)
#           （ProfileQueryData+0x48 == profile+0x40 == nameOnPlatform）
#        -> OnlineFacebookClient::getUserPicture(name, 73, 73)        @0x50ef8c
#           URL @0xb887cc = "<graph.facebook.com>/%s/picture?width=%d&height=%d"
#           失败回退 OnlineUbiservices::getUserPicture(name, 0)       @0x517c10
#           URL @0xb89267 = "<akamaized>/%s/default_146_146.png"
#        -> tr::OnlineRobotMission::onPictureReceived                 @0x5027f4
#           ★ if (err != 0) return;  —— 不清 [+0x120]、不回 state 2，界面永远停在
#              「检索对手中」。所以 graph.facebook.com / ubisoft-avatars.akamaized.net
#              这两个域名必须由打补丁时重写到本地服务器（见 dist/patcher/patch_dynaddr.py
#              的 HOST_EXACT）。
#
# 响应形状：tr::MatchMaking::parseMatchMakingResult @0x4f94a8 **只认根对象的扁平
# 成员键**，而且**不做任何 JSON 类型检查**（值一律按 32 位字从 [node+0x28] 读：
# 字符串就是指针，数字就是整数）：
#   "player"      -> strcpy(res+0x85)                            对手名，必须非空
#   "drivetime"   -> *(int*)(res+0xc8)                           幽灵请求里的 time=
#   "upgrades"    -> LeaderBoardData::parseUpgrades(res+0xb4)     车辆升级位域
#   "data"        -> LeaderBoardData::parseData(res+0xb4)         外观/数据位域
#   "score_value" -> *(int*)(res+0xcc)
#   "replay_id"   -> *(int*)(res+0xe4)
# 所以 data/upgrades 必须是 JSON **整数**：之前的兜底 `{"data": []}` 会让
# parseData 把数组节点的指针当位域用。
_ROBOT_NAMES = (
    "Robotman", "IronGear", "BrakeLess", "SandStorm", "GhostRider", "TangoPro",
    "HiVoltage", "RustBucket", "NitroNina", "WheelieKing", "CliffHanger",
    "TwoStroke", "BackflipBob", "MudSlinger", "AxleRose", "SpokeSlinger",
)


def _robot_opponent(track):
    """给一条赛道挑一个稳定的假对手 -> (名字, 用时ms, 幽灵记录或 None)。

    名字必须对同一条赛道保持稳定：客户端拿到名字后会立刻用
    `.../robot_replaydata?...&player=<名字>` 和 `GET /v1/profiles/<名字>` 回查，
    每次换名字会让对手资料/幽灵文件名对不上号。
    """
    rec = acct.ghost_any_for_track(track) if track else None
    seed = (track or 0) & 0xFFFFFFFF
    if rec:
        seed = (seed * 31 + int(rec.get("contentId") or 0)) & 0xFFFFFFFF
    name = _ROBOT_NAMES[seed % len(_ROBOT_NAMES)]
    drive = int((rec or {}).get("drive_time") or 0)
    if drive <= 0:
        # 这条赛道还没有真幽灵时编一个像样的成绩，避免 time=0
        # （客户端会用 time 去请求幽灵，0 容易被当异常成绩丢掉）。
        drive = 45000 + (seed % 60000)
    return name, drive, rec


def h_match_robot(path, query, body, headers):
    """GET /public/match/v1/robot —— A.N.B.A（Robotman）支线的对手查询。

    见上面 `_ROBOT_NAMES` 处的长注释：这是「检索对手中」卡死链路的**第一环**。
    空响应会让对手名变成空串，后续头像 URL 退化成 `//...`，`onPictureReceived`
    拿到 err != 0 直接 return，状态机永远停在「检索对手中」。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    raw = (q.get("track_name") or "").strip()
    if raw.startswith("track"):
        raw = raw[5:]
    try:
        track = int(raw)
    except Exception:
        track = None
    if track is None:
        try:
            track = int(q.get("track_id") or "")
        except Exception:
            track = None

    name, drive, rec = _robot_opponent(track)
    print("[robot] %s 赛道 %s range=%s offset=%s -> 对手 %s (%d ms%s)"
          % (path, track, q.get("range"), q.get("offset"), name, drive,
             ", 幽灵 contentId=%s" % rec.get("contentId") if rec else ", 无幽灵"),
          flush=True)
    return 200, {"Content-Type": "application/json"}, {
        # ★ player 必须非空：它决定对手名、robot_ghost-<hash(name)>-<track>.robot
        #   的文件名，以及头像 URL 里的路径段。
        "player": name,
        "drivetime": drive,
        # upgrades/data 是 LeaderBoardData 的位域整数，0 = 默认车。
        "upgrades": 0,
        "data": 0,
        # score_value 用 1：parseJsonResponse 在调用 parseMatchMakingResult 之前
        # 就把 res+0xcc 预置成 1，说明这是客户端认的「有效」值。
        "score_value": 1,
        "replay_id": 0,
    }


# ------------------------------------------------- 限时活动 / 赛季（weekly_track_system）
# 客户端调用链（反汇编 tr::OnlineWeeklyChallenge，全部经 OnlineCore::getRequest）：
#   requestWeekIndex           cmd 0x76  %s/%s/liveevents/v1/weekly_track_system/basic_info
#   requestWeeklyConfiguration cmd 0x77  %s/%s/liveevents/v1/weekly_track_system/config/%d
#   requestOpponentId          cmd 0x78  %s/%s/liveevents/v1/weekly_track_system/find_opponent
#   requestRewardConfig        cmd 0x79  "%s%s%d"（base + reward_config/ + 槽位数）
# 响应由 OnlineWeeklyChallenge::parseJsonResponse @0x504ef4 分派：
#   sub w8, cmd, #0x76 ; cmp w8, #9 ; 跳转表 @0xb8710c
#   0x76 -> 0x504f7c（basic_info） 0x77 -> 0x505124（config）
#   0x78 -> 0x505164（opponent）   0x79 -> 0x5051e8（reward_config）
# ⚠ 所有数值字段都必须带 JSON **整数**类型标签（客户端逐个判 [node+0x30] == 4），
#   给字符串或 null 会被当成「这个键不存在」。
_WEEK_SECONDS = 7 * 24 * 3600


def _week_index():
    """-> (week_start, week_index)。basic_info 与 config 必须给出同一个周，
    否则客户端会认为「配置不属于当前周」而拒绝开赛。"""
    week_start = (int(time.time()) // _WEEK_SECONDS) * _WEEK_SECONDS
    return week_start, (week_start // _WEEK_SECONDS) & 0xFFFFFF


# 本周挑战的赛道。必须挑一条游戏真能加载、且玩家跑过的赛道：1041 在幽灵库里
# （owner 0 / 6f857655 / 99511744 都有它的幽灵），真机日志里也出现过
# `GET /public/playerstats/v1/ranking/track1041` 与 ghost_*_1041.bin。
_WEEKLY_TRACK_ID = 1041


def h_liveevents_basic_info(path, query, body, headers):
    """GET|POST /public/liveevents/v1/weekly_track_system/basic_info —— 限时活动的「门」。

    ⚠ 同一个 URL 服务两条命令，响应形状共用：
      · GET  → cmd **0x76**：客户端逐个解析下面的键，回调
        `vtable[3](err=0, week_index, week_start, weeK_end, last_participated_week,
         last_participated_week_lb, left_retry_times, midnight_circuit_start_time,
         midnight_circuit_end_time, last_attempt_time)`。
      · POST → cmd **0x7f**（`postLastWeekData`，body `{"last_participated_week":%d,
        "last_participated_week_lb":%d,"additional_retry":%d}`，反汇编 0x503800 确认
        它也是拼 basic_info）：只取 `last_participated_week` /
        `last_participated_week_lb` / `left_retry_times`，然后回调 vtable[3] 与 vtable[7]。
      （POST 的 cmd 由 `OnlineCore::postJson` 的第 4 个参数带进去，不是 URL 决定的。）

    客户端契约（`OnlineWeeklyChallenge::parseJsonResponse` cmd 0x76 @0x504f7c）：
    根对象成员逐个 json_strcmp，命中后取值，最后一次性回调上面那个函数。

    ⚠ 两个坑：
      1. 键名是 `weeK_end`（**大写 K**，.rodata @0xb8763a 就是这么拼的）。
         写成 `week_end` 客户端收不到；`week_end` 那个拼法只出现在 config 里
         （@0xb876f0）。
      2. `midnight_circuit_start_time` / `midnight_circuit_end_time` 是**午夜杯**
         （Midnight Circuit）的时间窗，留 0 等于「永不开放」。
    """
    now = int(time.time())
    week_start, week_index = _week_index()
    payload = {
        "week_index": week_index,
        "week_start": week_start,
        "weeK_end": week_start + _WEEK_SECONDS,   # ★大写 K
        "last_participated_week": 0,
        "last_participated_week_lb": 0,
        "left_retry_times": 3,
        # 午夜杯先给一个常开窗口（1 小时前 ~ 24 小时后），保证能点进去
        "midnight_circuit_start_time": now - 3600,
        "midnight_circuit_end_time": now + 24 * 3600,
        "last_attempt_time": 0,
    }
    print("[liveevent] basic_info week_index=%s" % payload["week_index"], flush=True)
    return 200, {"Content-Type": "application/json"}, payload


def h_liveevents_config(path, query, body, headers):
    """GET /public/liveevents/v1/weekly_track_system/config/<n> —— 本周挑战配置。

    响应契约（`parseChallengeConfiguration` @0x5055f0，键地址已逐个反汇编确认）：
        week_index                                        -> cfg+0x00
        week_settings{week_start, week_end, week_leaderboard,
                      global_cooldown_time, global_retry_count,
                      global_gem_amount}                  -> cfg+0x04..0x14, 0x70
        challenge_settings{track_id, bike_id, bike_skin,
                           bike_upgrade{handle,engine,wheel,frame},
                           force_upgrade, task[]}         -> cfg+0x18..0x34, 0x38/0x40
        extra_settings{ad_reward_skip_cooldown_time,
                       ad_reward_retry_count}             -> cfg+0x68/0x6c
        retry_pool[{retry,gems}]                          -> cfg+0x48/0x50/0x58
    ⚠ 收尾会做 `strcmp(json, "null")`：**响应体字面为 "null" 时回调 err=7** 直接失败。
    ⚠ 路径末段那个 %d 是客户端传进来的（周号），我们忽略即可，任何值都回同一份配置。
    """
    week_start, week_index = _week_index()
    payload = {
        "week_index": week_index,
        "week_settings": {
            "week_start": week_start,
            "week_end": week_start + _WEEK_SECONDS,
            "week_leaderboard": 0,
            # 冷却/重试：给 0 冷却 + 3 次重试，避免玩家一进去就被冷却卡住
            "global_cooldown_time": 0,
            "global_retry_count": 3,
            "global_gem_amount": 1,
        },
        "challenge_settings": {
            "track_id": _WEEKLY_TRACK_ID,
            "bike_id": 0,
            "bike_skin": 0,
            "bike_upgrade": {"handle": 0, "engine": 0, "wheel": 0, "frame": 0},
            # 0 = 用玩家自己的车；1 = 强制用上面那台（force_upgrade 只是个布尔）
            "force_upgrade": 0,
            # task 故意留空：skill 名字要靠 MissionDB 反查，填错名字有解引用空指针的
            # 风险。等真机确认过合法 skill 名（.rodata 里疑似有 in_air_upsidedown /
            # backwheel / fronflip / backflip @0xb86c28）再填。
            "task": [],
        },
        "extra_settings": {
            "ad_reward_skip_cooldown_time": 0,
            "ad_reward_retry_count": 1,
        },
        "retry_pool": [{"retry": 1, "gems": 1}],
    }
    print("[liveevent] config -> 赛道 %d 周号 %d" % (_WEEKLY_TRACK_ID, week_index), flush=True)
    return 200, {"Content-Type": "application/json"}, payload


def h_liveevents_find_opponent(path, query, body, headers):
    """GET /public/liveevents/v1/weekly_track_system/find_opponent —— 本周对手。

    响应契约（`OnlineWeeklyChallenge::parseJsonResponse` cmd 0x78 @0x505164）：
        {"opponent": "<str>", "replay_id": <int>}
    → `ChallengeOpponent+0x00`（mt::String::operator=）/ `+0x20`（int），然后
      `listener->vtable[1](listener, err=0)`。
    ⚠ `"opponent"` 在 .rodata 里是 `/find_opponent` 的尾巴子串（@0xb871fe），
      别被字符串搜索误导成独立常量。
    名字必须对同一周稳定：客户端会拿它去查头像和幽灵。
    """
    name, drive, rec = _robot_opponent(_WEEKLY_TRACK_ID)
    print("[liveevent] find_opponent -> %s (%d ms)" % (name, drive), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "opponent": name,
        "replay_id": 0,
    }


def h_liveevents_reward_config(path, query, body, headers):
    """GET /public/liveevents/v1/weekly_track_system/reward_config/<槽位数> —— 奖励表。

    响应契约（cmd 0x79 @0x5051e8 → `parseRewardsSlot` @0x505d28）：
    根对象的**每个成员**都被当成一个「奖励槽」，槽名 = 成员键，槽体交给
    parseRewardsSlot 解析成 `vector<pair<int,int>>`（物品 id + 数量），最后塞进
    `map<String, vector<pair<int,int>>>`。
    槽体到底长什么样（对象里包一层 "reward"？还是 [[id,count],…]？）反汇编读下来
    自相矛盾（配对的第二个 int 取的是**下一个成员**的子节点），所以先回空对象：
    cmd 0x79 对空的第一个成员有 `cbz` 保护，不会崩，只是奖励界面空着。
    真机跑通后再按实际需求补。
    """
    print("[liveevent] reward_config %s -> {}" % path, flush=True)
    return 200, {"Content-Type": "application/json"}, {}


def h_liveevents_accept(path, query, body, headers):
    """weekly_track_system 里那几个 POST（start_race / end_race / skip_cooldown /
    refill_retry_count / last_week_data …）的宽容接收端。

    为什么可以只回 `{"data": []}`：
      · 这些请求走 `OnlineCore::postJson`（POST + JSON body），
      · 响应 cmd 落在 0x7a–0x7e，`OnlineWeeklyChallenge::parseJsonResponse`
        的跳转表把这一段全部指向 **0x5053d8**，而那里只有函数收尾（ret/析构），
        **一个字节都不解析**——客户端只关心 HTTP 成功。
    请求体（.rodata 常量，反汇编已确认，逗号后带空格）：
      start_race       {"gem":%s,"checksum":"%s","timestamp":%u, "restart":%s}
      end_race         {"score":%u,"checksum":"%s","timestamp":%u}
      skip_cooldown    {"gem":%s,"skiptimer":%s,"checksum":"%s","timestamp":%u}
      refill_retry_count {"checksum":"%s","retry_times":"%d","timestamp":%u}
    checksum 是客户端算的 MD5（`OnlineChecksum::calculateMD5`），我们不做校验。
    ⚠ 上传周数据（`postLastWeekData`，body 见上面 last_participated_week 那条）
      **不是独立端点**：它的 URL 也是 basic_info（反汇编 0x503800 `add x2,x2,#0x16c`），
      只是走 POST + cmd 0x7f。所以由 `h_liveevents_basic_info` 一并覆盖。
    """
    b = _json_body(body)
    print("[liveevent] %s %s <- %s -> data:[]" % (path, query, b), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


def h_ghost_upload(path, query, body, headers):
    """PUT .../payload 之外落单的二进制上传（老路径），落盘到 inbox 备用。"""
    q = dict(parse_qsl(query, keep_blank_values=True))
    track = q.get("track_id") or ""
    raw = body if isinstance(body, (bytes, bytearray)) else b""
    if track and raw[:4] == b"\x03\x00\x00\x00":
        p = acct.store_ghost(track, "upload_%s_%d.bin"
                             % (q.get("player", "anon")[:12], int(time.time())), bytes(raw))
        print("[ghost] 收到上传 赛道 %s -> %s (%d 字节)" % (track, p, len(raw)), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


def h_replay_id(path, query, body, headers):
    """POST /public/resultservice/v1/replay_id —— 登记「谁在哪条赛道跑了多少」。"""
    b = _json_body(body)
    client_ip = None
    try:
        client_ip = headers.get("_client_ip") or headers.get("X-Real-IP")
    except Exception:
        pass
    rec = acct.ghost_record_replay(b.get("profile_id"), b.get("track_name"),
                                   b.get("drive_time"), b.get("faults"), b.get("bike"),
                                   client_ip)
    print("[ghost] replay_id %s %s %s ms" % (rec.get("profile_id"),
                                             rec.get("track_name"), rec.get("drive_time")),
          flush=True)
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


def h_vip_registration(path, query, body, headers):
    """VIP 排行榜徽章注册。

    反汇编依据（libTrialsGo.so `tr::VIPLeaderboardBadgeService::registerMembership`
    @0x51ab68，360 字节，尾部 0x51ac70..0x51accc）：
      if (GlobalSettings::getSetting(hash("Anticheating_Enabled"), 1) != 0) {
          ts = AntiCheating::getSystemTime();
          snprintf(buf1, 0x100, "%s%uvip%s", <base>, ts,
                   "18e3548c59ad40dd03907b7aeee71d67");      // 盐 @0xb86ca1
          OnlineChecksum::calculateMD5(md5, buf1);
          OnlineChecksum::formatToJson(json, md5, ts);
          snprintf(body, 0x400, "{\\"badge_display\\":true,%s}", json);   // fmt @0xb8961f
      } else {
          snprintf(body, 0x400, "{\\"badge_display\\":true}");           // @0xb8965f
      }
      snprintf(url, 0x400, "%s%s", <serverAddr>, "/public/targeting/v1/vip_registration"); // @0xb89639
      DebugOut::add("%s\\n%s", url, body);                                // @0xb89555
      OnlineCore::postJson(listener, url, body, /*cmd=*/0x72, /*needAuth=*/1);  // PLT 0x352770

    响应由同一个类的 `onNetworkDataReceived` @0x51b0ac 处理，它只认 **cmd 0x73**
    （`cmp w3,#0x73`），所以本端点的响应其实不会被解析 —— 但按 `parseJsonData`
    认识的形状回一个 `badge_display` 最稳妥。
    """
    print("[vip] vip_registration body=%s"
          % body[:200].decode("utf-8", "replace"), flush=True)
    return 200, {"Content-Type": "application/json"}, {"badge_display": True}


def h_vip_validation(path, query, body, headers):
    """VIP 成员查询 —— 这是唯一会被 `parseJsonData` 解析响应的端点。

    `tr::VIPLeaderboardBadgeService::sendMembershipQuery` @0x51ad70（340 字节）：
    URL 以 `%s%s` 拼 `<serverAddr>` + `/public/targeting/v1/vip_validation?profiles=`
    （@0xb896a4），然后把 `char const** profiles` 里每个字符串用 `strcat` 依次追加
    （0x51ae38），最后
      OnlineCore::getRequest(listener, listener, url, /*cmd=*/0x73, 0, /*needAuth=*/1, 0)
    （0x51ae54 `mov w3,#0x73`、0x51ae6c PLT 0x33f1d0）。

    `parseJsonData(unsigned char* text, uint len)` @0x51b0fc（972 字节）只认两个顶层键：
      "player"        @0xb882f8  字符串值 → 追加进一个 std::string 缓冲
      "badge_display" @0xb89738  **只看键是否存在**（0x51b1d8 `cset w8,eq` /
                                 0x51b1dc `orr w26,w26,w8`），值本身没读
    之后每个 profile 组装成 `VIPLeaderboardBadgeService::ProfileData`（16 字节，
    badgeDisplay 在 +8）插进 `mt::Array<ProfileData>`（`this+0x10` 计数、`this+0x18` 数据）。
    不返回 "player" 就只是不插任何 ProfileData，是安全的。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    profiles = q.get("profiles") or ""
    print("[vip] vip_validation profiles=%s" % profiles, flush=True)
    # 两个键都是根对象的直接成员。不返回任何键的话 parseJsonData 会静默 return、
    # 不回调 listener，界面会一直等；所以至少把这两个键给出去。
    return 200, {"Content-Type": "application/json"}, {
        "player": profiles,
        "badge_display": True,
    }


def h_vip_badge_option(path, query, body, headers):
    """VIP 徽章显示开关。

    `tr::VIPLeaderboardBadgeService::sendBadgeOption(bool)` @0x51afe8（184 字节）：
      body = on ? "{\\"badge_display\\":true}"  (@0xb8965f)
                : "{\\"badge_display\\":false}" (@0xb896f8)
      url  = <serverAddr> + "/public/targeting/v1/vip_badge_option" (@0xb896d2)
      OnlineCore::postJson(listener, url, body, /*cmd=*/0x74, /*needAuth=*/1)  // 0x51b068
    这里把客户端请求里的 badge_display 原样回显（解析失败就回 true）。
    """
    try:
        req = json.loads(body.decode("utf-8", "replace") or "{}")
        val = bool(req.get("badge_display", True))
    except Exception:
        val = True
    print("[vip] vip_badge_option badge_display=%s" % val, flush=True)
    return 200, {"Content-Type": "application/json"}, {"badge_display": val}


LEADERBOARD_PATH = os.path.join(HERE, "data", "leaderboards.json")
LEADERBOARD_LOCK = threading.Lock()


def _load_leaderboards():
    try:
        with open(LEADERBOARD_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_leaderboards(obj):
    os.makedirs(os.path.dirname(LEADERBOARD_PATH), exist_ok=True)
    # ★ Windows 上 os.replace 偶发 WinError 5（杀软/索引器短暂占用目标文件），
    #   事务性写盘因此要重试，否则会留下 leaderboards.json.tmp 且丢一次成绩。
    tmp = "%s.%d.tmp" % (LEADERBOARD_PATH, os.getpid())
    last = None
    for attempt in range(6):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            os.replace(tmp, LEADERBOARD_PATH)
            return
        except OSError as exc:            # PermissionError 也是 OSError
            last = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass
    print("[rank-save] 榜单落盘失败：%s" % last, flush=True)


def _record_result(profile_id, track_name, stats):
    """保存一条真实成绩；同一账号/赛道只保留最佳 drivetime。

    ★ 两个来源字段并不一致，所以是**合并**而不是整条覆盖：
        · 存档 highscores2 行 = [track, drivetime, data, upgrades, submittime]
          —— 有 drivetime/data/upgrades，**没有 score_value**；
        · batch_update 的 JSON —— 有 drivetime/score_value/data/upgrades。
      如果谁后到就把整条覆盖，score_value 会被存档同步清零。
      规则：drivetime 更小才算新纪录；时间相同则补齐缺失字段；时间更差直接丢弃。
    """
    if not profile_id or not track_name or not isinstance(stats, dict):
        return False
    try:
        drivetime = int(stats.get("drivetime", 0))
    except (TypeError, ValueError):
        return False
    if drivetime <= 0:
        return False
    clean = {
        "player": profile_id,
        "drivetime": drivetime,
        "submittime": int(stats.get("submittime", 0) or 0),
        "data": int(stats.get("data", 0) or 0),
        "upgrades": int(stats.get("upgrades", 0) or 0),
        "extradata": int(stats.get("extradata", 0) or 0),
        "updated": int(time.time()),
    }
    # 只有来源真的带了这个字段才写，避免用"不存在的 0"覆盖已有数据。
    for key in ("score_value", "global_score"):
        if key in stats and stats[key] is not None:
            try:
                clean[key] = float(stats[key]) if key == "global_score" else int(stats[key])
            except (TypeError, ValueError):
                pass
    if "_client_submittime" in stats:
        clean["_client_submittime"] = int(stats["_client_submittime"] or 0)
    with LEADERBOARD_LOCK:
        db = _load_leaderboards()
        board = db.setdefault(track_name, {})
        old = board.get(profile_id)
        if old is not None:
            old_time = int(old.get("drivetime", 0))
            if old_time < drivetime:
                return False                      # 更慢的一次，直接丢
            if old_time == drivetime:
                merged = dict(old)
                for k, v in clean.items():
                    if k in ("player", "drivetime", "updated"):
                        continue
                    if not merged.get(k) and v:
                        merged[k] = v             # 补齐缺失字段，不覆盖已有值
                if merged == old:
                    return False
                board[profile_id] = merged
                _save_leaderboards(db)
                return True
        board[profile_id] = clean
        _save_leaderboards(db)
    return True


def _u32(v):
    """存档里的 data/upgrades 是有符号 int，按 32 位无符号回放。"""
    try:
        return int(v) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 0


def _record_highscores_row(profile_id, row):
    """把存档 highscores2 的一行 [track, drivetime, data, upgrades, submittime] 入库。

    ★ 这一行是不是"跑过"完全看 drivetime：客户端给没跑过的赛道写成 0
      （实测 191 行里 163 行是 `[track, 0, 256, 0, 0]` 占位）。
      所以 drivetime > 0 就是"真的跑过"的唯一判据，不需要别的推断。
    """
    if not isinstance(row, (list, tuple)) or len(row) < 2:
        return False
    try:
        track = int(row[0])
        drivetime = int(row[1])
    except (TypeError, ValueError):
        return False
    if drivetime <= 0 or track <= 0:
        return False
    return _record_result(profile_id, "track%d" % track, {
        "drivetime": drivetime,
        "data": _u32(row[2] if len(row) > 2 else 0),
        "upgrades": _u32(row[3] if len(row) > 3 else 0),
        # ★ 存档行的 submittime 恒为 0（客户端从没填过）。直接回显会让榜单
        #   显示 1970-01-01，所以填"服务器收到这条成绩的时间" —— 真实值，不是编的。
        "submittime": int(time.time()),
        "_client_submittime": int(row[4] or 0) if len(row) > 4 else 0,
    })


def _ingest_highscores(profile_id, content):
    """从玩家上报的存档里同步成绩表。只收 drivetime > 0 的赛道。"""
    if not isinstance(content, dict):
        return 0
    rows = content.get("highscores2") or content.get("highscores") or []
    if not isinstance(rows, list):
        return 0
    n = 0
    for row in rows:
        if _record_highscores_row(profile_id, row):
            n += 1
    return n


def h_result_stats(path, query, body, headers):
    """接收真实跑图成绩。只收真正跑过的图，不制造任何记录。"""
    payload = _json_body(body)
    caller, err = acct.authenticate(headers)
    if err or not caller or caller.get("kind") != "account":
        return 401, {"Content-Type": "application/json"}, {"error": "invalid-credentials"}
    profile_id = caller["profileId"]
    endpoint = path.rstrip("/").rsplit("/", 1)[-1]
    accepted = 0

    if endpoint == "batch_update":
        # ★ 批量同步是启动/进度同步时把本地整张 highscores 表发上来。
        #   表里有 191 行，但**只有真正跑过的图 drivetime > 0**，
        #   其余 163 行是 [track, 0, 256, 0, 0] 的占位（解锁但没跑）。
        #   以前这里一律入库，就是"我没跑的也有记录"的根源。
        #   现在只收 drivetime > 0 的行，未跑过的图永远不会出现在榜单里。
        for item in (payload.get("updates") or []):
            if not isinstance(item, dict):
                continue
            track = str(item.get("track_name") or "")
            stats = item.get("stats") or {}
            if not re.fullmatch(r"track[0-9]+", track) or not isinstance(stats, dict):
                continue
            try:
                if int(stats.get("drivetime", 0) or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            if _record_result(profile_id, track, stats):
                accepted += 1
        print("[rank-save] profile=%s batch_update accepted=%d" % (profile_id, accepted),
              flush=True)
        return 200, {"Content-Type": "application/json"}, {"data": []}

    track = endpoint.strip()
    if not re.fullmatch(r"track[0-9]+", track):
        return 400, {"Content-Type": "application/json"}, {"error": "invalid-track"}
    updates = payload.get("updates", []) if isinstance(payload, dict) else []
    if isinstance(updates, list) and updates:
        # 单赛道请求的 body 通常是 updates:[{stats:...}]；忽略其中可能
        # 被篡改的 track_name，赛道身份以 URL 为准。
        for item in updates:
            if isinstance(item, dict) and _record_result(profile_id, track, item.get("stats") or {}):
                accepted += 1
    elif isinstance(payload, dict):
        stats = payload.get("stats") or payload
        if _record_result(profile_id, track, stats):
            accepted = 1
    print("[rank-save] profile=%s track=%s accepted=%d" %
          (profile_id, track, accepted), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


GLOBAL_LEADERBOARDS = {"global_stats", "global_stats_donkey"}


def _aggregate_global_entries():
    """从真实单赛道记录计算主界面总榜；不为未跑赛道创建行。"""
    with LEADERBOARD_LOCK:
        db = _load_leaderboards()
    totals = {}
    for board, records in db.items():
        if board in GLOBAL_LEADERBOARDS or not board.startswith("track"):
            continue
        for profile_id, row in (records or {}).items():
            try:
                drivetime = int(row.get("drivetime", 0))
            except (TypeError, ValueError):
                continue
            if drivetime <= 0:
                continue
            out = totals.setdefault(profile_id, {
                "player": profile_id,
                "data": 0,
                "upgrades": 0,
                "submittime": 0,
                "drivetime": 0,
                "score_value": 0,
                "extradata": 0,
                "global_score": 0.0,
                "updated": 0,
            })
            out["data"] += 1
            # upgrades/extradata 是位掩码，合并而非相加。
            out["upgrades"] |= int(row.get("upgrades", 0) or 0)
            out["extradata"] |= int(row.get("extradata", 0) or 0)
            out["submittime"] = max(out["submittime"], int(row.get("submittime", 0) or 0))
            out["drivetime"] += drivetime
            out["score_value"] += int(row.get("score_value", 0) or 0)
            if "global_score" in row:
                out["global_score"] += float(row.get("global_score") or 0)
            else:
                # 客户端单图提交没有 global_score；总榜分数用真实单图
                # score_value 的和推导，不生成任何额外赛道记录。
                out["global_score"] += float(row.get("score_value", 0) or 0)
            out["updated"] = max(out["updated"], int(row.get("updated", 0) or 0))
    rows = list(totals.values())
    rows.sort(key=lambda r: (-float(r["global_score"]), -int(r["data"]), r["player"]))
    return [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]


def _stored_entries(board, requested_players=None, keep_total=False):
    if board in GLOBAL_LEADERBOARDS:
        rows = _aggregate_global_entries()
    else:
        with LEADERBOARD_LOCK:
            rows = list((_load_leaderboards().get(board) or {}).values())
        rows.sort(key=lambda r: (int(r.get("drivetime", 0)), str(r.get("player", ""))))
        rows = [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]
    total = len(rows)
    wanted = set(requested_players or [])
    if wanted:
        # 注意：过滤掉的只是**要展示给客户端的行**，rank 保持在全榜中的真实名次。
        rows = [r for r in rows if r.get("player") in wanted]
    return (rows, total) if keep_total else rows


def _rank_entry(row):
    return {
        "player": row["player"],
        "rank": int(row["rank"]),
        "stats": {k: row[k] for k in (
            "data", "upgrades", "submittime", "drivetime",
            "score_value", "extradata", "global_score") if k in row},
    }


def h_playerstats_ranking(path, query, body, headers):
    board = path.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    q = dict(parse_qsl(query, keep_blank_values=True))
    players = [x for x in (q.get("players") or "").split(",") if x]
    rows, total = _stored_entries(board, players, keep_total=True)
    # ★ playerCount 必须是**全榜人数**，不是过滤后给这个客户端看的行数：
    #   客户端拿它算「你超过了前 X%」，回过滤后的 1 会让百分位永远显示 100%。
    return 200, {"Content-Type": "application/json"}, {
        "leaderboard": board, "playerCount": total, "httpCode": 200,
        "results": [_rank_entry(r) for r in rows],
    }


def h_playerstats_stats(path, query, body, headers):
    board = path.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    q = dict(parse_qsl(query, keep_blank_values=True))
    players = [x for x in (q.get("players") or "").split(",") if x]
    rows = _stored_entries(board, players or [_caller_profile(headers)])
    return 200, {"Content-Type": "application/json"}, {
        "statboard": board,
        "results": [_rank_entry(rows[0])] if rows else [],
    }


DYNAMIC_EXACT = [
    ("POST", "/public/resultservice/v1/enhancestats/batch_update", h_result_stats),
    ("POST", "/public/resultservice/v1/enhancestats/track", h_result_stats),
    ("POST", "/public/playerprogress/v1/progress", h_progress),
    ("GET", "/public/playerprogress/v1/progress", h_progress_latest),
    ("GET", "/public/playerprogress/v1/progress/version", h_progress_version),
    ("GET", "/public/playerprogress/v1/progress/status", h_progress_status),
    ("POST", "/public/playerprogress/v1/swap", h_progress_swap),
    ("GET", "/v2/profiles/me", h_profile_me),
    # ★ 会话端点必须注册为动态处理，否则会落到 rules.json 里那条写死的匿名桩：
    #   返回固定 profileId 11111111-… 且**没有 rememberMeTicket**，
    #   症状就是「每次重启都要重新登录」「登录了也没有分数记录和在线服务」。
    #   v1 = 用户名密码登录（真校验），v3 = 设备静默登录；GET 是会话续期。
    ("POST", "/v1/profiles/sessions", h_session),
    ("POST", "/v2/profiles/sessions", h_session),
    ("POST", "/v3/profiles/sessions", h_session),
    ("GET", "/v1/profiles/sessions", h_session),
    ("GET", "/v1/profiles", h_profiles_query),
    ("GET", "/public/receiptvalidation/v1/product/configuration", h_iap_products),
    ("GET", "/public/receiptvalidation/v1/verify_android", h_iap_verify),
    ("POST", "/public/receiptvalidation/v1/verify_android", h_iap_verify),
    # VIP 排行榜徽章（tr::VIPLeaderboardBadgeService，见三个处理器的 docstring）：
    #   registerMembership 走 /public/...；反作弊关闭时改走 /private/...direct_...
    ("POST", "/public/targeting/v1/vip_registration", h_vip_registration),
    ("POST", "/private/targeting/v1/direct_vip_registration", h_vip_registration),
    ("GET", "/public/targeting/v1/vip_validation", h_vip_validation),
    # sendBadgeOption 是 POST、getBadgeOption 是 GET，两者 URL 相同（ELF 里查不到
    # 调用点，是虚表调用），所以两种方法都要支持。
    ("GET", "/public/targeting/v1/vip_badge_option", h_vip_badge_option),
    ("POST", "/public/targeting/v1/vip_badge_option", h_vip_badge_option),
]

DYNAMIC = [
    ("GET", "/public/timeservice/v1/gettime", h_timeservice),
    # 排行榜与玩家统计（板名在路径末段，只能用前缀匹配）：
    #   /public/playerstats/v1/ranking/{track66633|track1097|legends|global_stats…}
    #   /public/playerstats/v1/stats/{...}?players=
    ("GET", "/public/playerstats/v1/ranking/", h_playerstats_ranking),
    ("GET", "/public/playerstats/v1/stats/", h_playerstats_stats),
    # A.N.B.A（Robotman）支线的对手查询。前缀匹配顺带兜住 robot_v2
    # （"%s/%s/match/v1/robot_v2?track_name=%s&score=%lu&range=%d" @0xb86362）。
    ("GET", "/public/match/v1/robot", h_match_robot),
    # 限时活动/赛季：basic_info 是整条支线的入口（POST 与 GET 两个版本真机都发过）。
    # 它此前落到 rules.json 的 "*" 兜底 {"data": []}，客户端拿到的 week_index 全是 0，
    # 于是活动列表恒为空。
    ("GET", "/public/liveevents/v1/weekly_track_system/basic_info", h_liveevents_basic_info),
    ("POST", "/public/liveevents/v1/weekly_track_system/basic_info", h_liveevents_basic_info),
    # 活动配置：URL 末段带周号（`config/%d`），只能前缀匹配。
    ("GET", "/public/liveevents/v1/weekly_track_system/config/", h_liveevents_config),
    ("POST", "/public/liveevents/v1/weekly_track_system/config/", h_liveevents_config),
    # 本周对手（无反汇编出来的参数，纯 GET；POST 变体一并用宽容端兜住）。
    ("GET", "/public/liveevents/v1/weekly_track_system/find_opponent", h_liveevents_find_opponent),
    ("POST", "/public/liveevents/v1/weekly_track_system/find_opponent", h_liveevents_find_opponent),
    # 奖励表：URL 末段是槽位数（`reward_config/%d`）。
    ("GET", "/public/liveevents/v1/weekly_track_system/reward_config/", h_liveevents_reward_config),
    ("POST", "/public/liveevents/v1/weekly_track_system/reward_config/", h_liveevents_reward_config),
    # 开赛/完赛/跳冷却/补重试次数——响应在客户端侧完全不被解析，见 h_liveevents_accept。
    ("POST", "/public/liveevents/v1/weekly_track_system/start_race", h_liveevents_accept),
    ("POST", "/public/liveevents/v1/weekly_track_system/end_race", h_liveevents_accept),
    ("POST", "/public/liveevents/v1/weekly_track_system/skip_cooldown", h_liveevents_accept),
    ("POST", "/public/liveevents/v1/weekly_track_system/refill_retry_count", h_liveevents_accept),
]


def pick_dynamic(method, path):
    # 图片与好友头像：<base>/<pid>/picture?width=..&height=..（见 .rodata @0xb887cc）
    if method == "GET" and (path.lower().endswith(_IMAGE_EXT) or path.endswith("/picture")):
        return h_placeholder_image, "dyn:placeholder-image"
    # 结尾斜杠容错：真机确实会发 `GET /v1/profiles/`（OnlineRobotMissionProfileQuery
    # 查对手资料那条链），而 rules.json 里的静态桩只认 `/v1/profiles/` 之外的形式，
    # 不归一化就会回匿名档 11111111-1111-1111-1111-111111111111。
    stripped = path.rstrip("/") or path
    for m, p, fn in DYNAMIC_EXACT:
        if m == method and (path == p or (path != stripped and stripped == p)):
            return fn, "dyn:%s %s" % (m, p)
    if method == "POST" and path.startswith("/public/resultservice/v1/enhancestats/"):
        return h_result_stats, "dyn:result-stats"
    # 幽灵：userstorage v2 的内容仓库（客户端上传/检索自己的幽灵）。
    # 这一个处理器要按 HTTP 方法分派建/取/改/删，所以把 method 绑进去。
    if path.startswith("/public/userstorage/v2/"):
        return (lambda p, q, b, h: h_userstorage(method, p, q, b, h)), "dyn:userstorage-ghost"
    # 幽灵：resultservice 下的 ghost / replaydata / replay_id
    # （replay_id 这条路径里不含 ghost/replaydata 字样，必须单独先判，
    #   否则会掉进 resultservice 的通配规则里，登记就丢了）
    if path.endswith("/replay_id") and path.startswith("/public/resultservice/"):
        return h_replay_id, "dyn:replay-id"
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


_WEBUI_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trials Frontier 本地私服</title>
<style>
 body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#1d1712;color:#eee;margin:0;padding:24px}
 h1{font-size:20px;margin:0 0 4px} .sub{color:#a99;font-size:13px;margin-bottom:20px}
 .card{background:#2a221b;border:1px solid #463829;border-radius:10px;padding:18px;max-width:760px;margin-bottom:18px}
 label{display:block;margin:10px 0 4px;font-size:13px;color:#cbb}
 input{width:100%;box-sizing:border-box;padding:9px;border-radius:6px;border:1px solid #54432f;background:#181310;color:#eee;font-size:14px}
 button{margin-top:14px;padding:10px 18px;border:0;border-radius:6px;background:#c8892b;color:#241a0c;font-weight:700;font-size:14px;cursor:pointer}
 button:hover{background:#e0a040}
 table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #3a2e22}
 #msg{margin-top:12px;font-size:14px;min-height:20px}
 .ok{color:#6ad06a} .bad{color:#e86a6a}
 code{background:#181310;padding:2px 5px;border-radius:4px}
</style></head><body>
<h1>特技摩托：前线 · 本地私服</h1>
<div class="sub">ROADMAP 第 2 条 —— 账号注册与登录已分离：<b>必须先在这里注册，游戏里才能登录。</b></div>

<div class="card">
  <h2 style="font-size:16px;margin:0">注册账号</h2>
  <label>账号（游戏里登录用，建议邮箱格式）</label><input id="u" autocomplete="off" placeholder="you@example.com">
  <label>密码</label><input id="p" type="password" placeholder="至少 6 位">
  <label>游戏内显示名（可留空）</label><input id="n" autocomplete="off" placeholder="留空则与账号相同">
  <button onclick="reg()">注册</button>
  <div id="msg"></div>
</div>

<div class="card">
  <h2 style="font-size:16px;margin:0">已注册账号</h2>
  <div id="list">载入中…</div>
  <button onclick="load()">刷新</button>
</div>

<script>
function say(t, ok){var m=document.getElementById('msg');m.textContent=t;m.className=ok?'ok':'bad';}
async function reg(){
  var u=document.getElementById('u').value.trim(), p=document.getElementById('p').value,
      n=document.getElementById('n').value.trim();
  if(!u||!p){say('账号和密码都要填。',false);return;}
  var r=await fetch('/__api/register',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:u,password:p,nameOnPlatform:n||u})});
  var j=await r.json();
  say(j.message||j.error||('HTTP '+r.status), !!j.ok);
  if(j.ok){document.getElementById('p').value='';load();}
}
async function load(){
  var r=await fetch('/__accounts'); var j=await r.json();
  var h='<table><tr><th>账号</th><th>显示名</th><th>profileId</th><th>注册时间</th></tr>';
  (j.accounts||[]).forEach(function(a){
    h+='<tr><td>'+a.username+'</td><td>'+(a.nameOnPlatform||'')+'</td><td><code>'+(a.profileId||'').slice(0,8)+'…</code></td><td>'+(a.created_iso||'')+'</td></tr>';
  });
  document.getElementById('list').innerHTML=h+'</table>';
}
load();
</script></body></html>
"""


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
            if self._introspect(path, query, body):
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

    def _introspect(self, path, query, body=b""):
        """本地管理端点：/__accounts /__saves /__save /__sessions /__ghosts …"""
        q = dict(parse_qsl(query, keep_blank_values=True))
        if path == "/__ping":
            self._send(200, {"Content-Type": "text/plain"}, b"pong\n")
            return True

        def js(obj, status=200):
            self._send(status, {"Content-Type": "application/json"},
                       json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
            return True

        if path == "/__accounts":
            return js({"count": len(acct.list_accounts_public()),
                       "accounts": acct.list_accounts_public()})
        if path in ("/__register", "/__ui"):
            self._send(200, {"Content-Type": "text/html; charset=utf-8"},
                       _WEBUI_HTML.encode("utf-8"))
            return True
        if path == "/__api/register":
            form = {}
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                form = _json_body(body) or {}
            else:
                form = dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
            acc, err = acct.register_account(form.get("username"), form.get("password"),
                                            form.get("nameOnPlatform"))
            if acc is None:
                msg = {"bad-request": "用户名和密码都不能为空",
                       "exists": "这个账号名已经被注册了，换一个",
                       }.get(err, err or "注册失败")
                return js({"ok": False, "error": err, "message": msg}, 400)
            return js({"ok": True, "username": acc["username"],
                       "profileId": acc["profileId"], "message": "注册成功，可以在游戏里登录了"})
        if path == "/__api/login":
            form = _json_body(body) or {}
            acc, err = acct.login_account(form.get("username"), form.get("password"))
            if acc is None:
                return js({"ok": False, "error": err}, 401)
            return js({"ok": True, "username": acc["username"], "profileId": acc["profileId"]})
        if path == "/__api/password":
            form = _json_body(body) or {}
            acc, err = acct.set_password(form.get("username"), form.get("password"))
            if acc is None:
                return js({"ok": False, "error": err}, 400)
            return js({"ok": True, "username": acc["username"], "message": "口令已更新"})
        if path == "/__api/delete":
            form = _json_body(body) or {}
            who, err = acct.delete_account(form.get("username"))
            if who is None:
                return js({"ok": False, "error": err}, 400)
            return js({"ok": True, "username": who, "message": "账号已删除（存档目录保留）"})
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
        if path == "/__leaderboards":
            # 排行榜诊断：track 榜是原始落库数据，global_stats 是实时聚合视图。
            db = _load_leaderboards()
            tracks = {}
            for board, records in sorted(db.items()):
                rows = sorted((records or {}).values(),
                              key=lambda r: int(r.get("drivetime", 0)))
                tracks[board] = [{"rank": i, "player": r.get("player"),
                                  "drivetime": r.get("drivetime"),
                                  "score_value": r.get("score_value")}
                                 for i, r in enumerate(rows, 1)]
            global_rows = [{"rank": r["rank"], "player": r["player"],
                            "tracks": r["data"], "total_drivetime": r["drivetime"],
                            "global_score": r["global_score"]}
                           for r in _aggregate_global_entries()]
            return js({"tracks": tracks,
                       "global_stats": global_rows,
                       "note": "global_stats 由真实单赛道记录实时聚合，不落库"})
        if path == "/__ghosts":
            root = acct.GHOST_DIR
            out = {}
            if os.path.isdir(root):
                for t in sorted(os.listdir(root)):
                    if t in ("store", "inbox") or not os.path.isdir(os.path.join(root, t)):
                        continue
                    out[t] = acct.list_ghosts(t)
            store = [{"contentId": r.get("contentId"), "track_id": r.get("track_id"),
                      "owner": r.get("owner"), "drive_time": r.get("drive_time"),
                      "frames": r.get("frames"), "size": r.get("size"),
                      "builtin": bool(r.get("builtin")), "stored": bool(r.get("stored"))}
                     for r in acct.ghost_list()]
            return js({"ghosts": out, "store": store,
                       "replays": acct.ghost_replays()[-20:],
                       "note": "ghosts=<赛道>/内置文件；store=客户端上传的内容仓库"})
        if path == "/__help":
            return js({"endpoints": ["/__ping", "/__log", "/__accounts", "/__devices",
                                     "/__sessions", "/__saves", "/__save?profile=<pid>",
                                     "/__history?profile=<pid>",
                                     "/__restore?profile=<pid>&ts=<时间戳|latest>",
                                     "/__ghosts（内置幽灵文件 + 上传的幽灵仓库 + replay_id 登记）",
                                     "/__leaderboards（排行榜落库与主榜聚合）",
                                     "/__register（注册网页，也可用 /__ui）",
                                     "POST /__api/register {username,password,nameOnPlatform}",
                                     "POST /__api/login {username,password}",
                                     "POST /__api/password {username,password}"]})
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
