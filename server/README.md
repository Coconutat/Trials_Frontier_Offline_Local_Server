# server/ — Trials Frontier 离线后端

游戏 7.9.4（versionCode 561，arm64-v8a）的联网后端在 2019 年前后停服。这个目录用
**一个纯标准库的 Python HTTP 服务器**把它顶替掉：客户端所有请求改指本机，服务器按
端点返回合理的 JSON，顺带把账号、存档、排行榜、幽灵、PVP 赛季全部落到本地文件。

没有任何第三方依赖 —— 只要 Python 3.8+（用的 `http.server` / `threading` / `json`）。

```
python server/tf_server.py --host 0.0.0.0 --port 8000
```

改 APK 让它指向本机地址的是 `../tools/` 里的补丁工具（见 `../tools/README.md`）。

---

## 1. 快速开始

```bash
# 启动（默认就是 0.0.0.0:8000）
python server/tf_server.py

# 换个端口 / 只监听本机
python server/tf_server.py --host 127.0.0.1 --port 8080

# 语法自检（改完先跑这个再重启）
python -m py_compile server/tf_server.py
```

打开 <http://127.0.0.1:8000/__ui> 是内嵌的账号管理页（注册 / 改密 / 删号 / 看存档 /
看排行榜 / 看幽灵 / 看运行时配置）。`http://127.0.0.1:8000/__help` 列出全部本地端点。

**改完要重启**：`rules.json` 与 `data/tf_config.json` 都热加载（每次请求重新读 / 按 mtime），
但 `tf_server.py` 与 `tflocal_accounts.py` 的修改必须重启进程。

```powershell
# Windows 上重启（杀掉占着 8000 的那个进程再拉起）
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess -Force
Start-Process C:\Python314\python.exe -ArgumentList "server\tf_server.py","--host","0.0.0.0","--port","8000" `
  -WorkingDirectory <仓库根> -WindowStyle Hidden `
  -RedirectStandardOutput <日志> -RedirectStandardError <日志>
```

真机排查时最有用的一条命令（日志是 JSONL，一行一条请求）：

```powershell
# 看最近 20 条非 200 的请求
Get-Content work\trials-frontier\notes\server-log.jsonl -Tail 2000 |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.status -ne 200 } | Select-Object -Last 20 ts, method, path, status
```

> ⚠ `ts` 是 ISO 时间字符串，比较请用 `[datetime]::Parse(...)`，不要用 `.Substring()`；
> `query` 有些端点是**对象**不是字符串；`resp_body` 可能是 bytes。

---

## 2. 文件

| 文件 | 作用 |
|---|---|
| `tf_server.py` | HTTP 服务器：路由 + 全部动态端点处理器 + 请求日志 + 内嵌管理页。~4000 行 |
| `tflocal_accounts.py` | 本地账号 / 会话 / 长期凭据 / 设备 / 存档 / 幽灵存储 + 管理员账号 + 受控下发。纯数据层，不碰 HTTP。~1800 行 |
| `admin/` | 后台管理页（`/__admin`）：`index.html` + `app.css` + `app.js` + `i18n.json`（CN/EN）+ `items.json`（官方物品目录：478 条物品 + 80 套服装 + 108 款涂装 + 12 个蓝图 + 382 条赛道 + 304 条奖励名，由 `tools/build_item_catalog.py` 生成）。纯静态、零依赖，由 `_ADMIN_FILES` 把「路径 → 文件名」写死成白名单（杜绝路径穿越） |
| `rules.json` | 静态桩响应表（`"<METHOD> <路径前缀>"` → `{status, headers, body}`）。只服务那些「有响应就行」的端点 |
| `data/tf_config.json` | 运营参数（匹配、赛季、周赛、奖励、筹码）。**唯一入库的 `data/` 文件** |
| `data/ghosts/` | 幽灵仓库：`<赛道id>/*.bin`（游戏自带静态幽灵，入库）+ `store/` `index.json` `replays.json`（运行期，不入库） |
| `data/save/` `accounts.json` `sessions.json` `devices.json` `remember.json` `leaderboards.json` `admin.json` `player_levels.json` | 全部是运行期私有数据（`admin.json` 是管理员口令哈希 + 票据），被 `.gitignore` 排除 |

`tf_server.py` 的分区（行号截至 2026-10，只作导航用）：

| 行 | 内容 |
|---|---|
| 1–44 | 模块 docstring、imports、`HERE`/`ROOT`/`LOG_PATH`/`RULES_PATH` |
| 46–330 | 运行时配置：`_TF_CONFIG_DEFAULTS`、`tf_config()`、`cfg()`、`cfg_int()`、`cfg_set()` |
| 332–348 | 请求环形缓冲 `RECENT`（≤400 条）、`LOG_LOCK`、`MAX_BODY_LOG = 8192`、`load_rules()` |
| 350–421 | 时间服务 `h_timeservice`；占位图片 `h_placeholder_image` |
| 422–517 | PVP 赛季横幅 `h_pvp_banner` |
| 519–996 | 本地账号侧端点：会话、存档、profile；幽灵读写 `h_userstorage` / `h_ghost` |
| 997–1105 | A.N.B.A / Robotman 假对手 `h_match_robot` |
| 1107–1330 | 限时活动 & 周赛（`liveevents/v1/weekly_track_system`） |
| 1333–2698 | PVP / 碉堡（`pvp_matches/v1`，最大的一块） |
| 2701–2985 | 幽灵上传、`replay_id`、内购、targeting（VIP / 礼包）、好友 |
| 2987–3402 | 排行榜：落盘、全局榜聚合、`h_playerstats_ranking`、`h_gift` |
| 3404–3564 | 路由表 `DYNAMIC_EXACT` / `DYNAMIC`、`pick_dynamic()`、`pick_rule()`、`render()` |
| 3592–3652 | 内嵌管理页 `_WEBUI_HTML` |
| 3653–3965 | `class Handler(BaseHTTPRequestHandler)`：流水线、日志、`_introspect` |
| 3966– | `main()` |

---

## 3. 请求处理流水线

```
Handler.do_GET / do_POST / do_PUT / do_DELETE
  ├─ path.startswith("/__")                -> _introspect()      # 本地管理 API，不记日志
  │     ├─ /__admin、/__admin/*            -> 后台页静态文件（_ADMIN_FILES 白名单）
  │     ├─ /__api/admin/*                  -> 管理员登录 / 登出 / 改口令 / 下发 …
  │     ├─ _PUBLIC = /__ping /__ui /__register /__api/register
  │     └─ 其余 /__*  无有效 tf_admin Cookie -> 401 admin-required    ★ 唯一的墙
  ├─ pick_dynamic(method, path)            # 命中 -> (handler, which)
  │     命中：构造 hdrs，注入 X-TF-Client = 客户端 IP，调用处理器
  └─ 未命中：load_rules() -> pick_rule() -> render() -> 兜底
        最后统一 _send() + 追加一条 JSONL 日志 + 控制台摘要
```

日志条目字段：`ts / method / url / path / query / req_headers / req_body / req_body_len / rule / status / resp_body / ms`。
落到 `work/trials-frontier/notes/server-log.jsonl`（同时进内存环形缓冲 `RECENT`，`/__log` 可读，**要管理员**）。
`/__*` 请求本身不进这个日志（`/__admin` 的访问也不会污染游戏端点统计）。

**`X-TF-Client`**：服务器在把请求交给动态处理器前，用来源 IP **覆盖**同名请求头。
`tflocal_accounts.save_progress()` / `serve_progress()` 靠它判断「这是不是同一台设备」，
从而让没登录的设备也能继承匿名槽位。客户端自己伪造这个头是无效的。

---

## 4. 路由：两级

### 4.1 动态端点（写代码的）

`pick_dynamic()` 的判断顺序**有依赖，改的时候别打乱**：

1. `GET /pvp_banner/` —— 必须先判，否则会被第 2 条图片通配吃掉，客户端会下到 256×256 的
   占位 PNG（2868 字节），超过 `mt::file::SaveFile` 的 `0x800` 上限。
2. `GET` 且路径以 `_IMAGE_EXT`（`.png/.jpg/.jpeg/.gif/.webp`）或 `/picture` 结尾 → 占位图。
3. 去掉结尾斜杠后再匹配（真机会发 `GET /v1/profiles/`）。
4. `DYNAMIC_EXACT`（精确路径表）。
5. `POST /public/resultservice/v1/enhancestats/` → `h_result_stats`。
6. `/public/userstorage/v2/` → `h_userstorage`。
7. `/replay_id` 必须排在幽灵判断之前。
8. `_looks_like_ghost(path)` → `h_ghost_upload` / `h_ghost`。
9. `DYNAMIC`（前缀表，**顺序敏感**）。

`DYNAMIC` 里两条顺序约束是踩过坑的：

* `GET /public/pvp_matches/v1/players` 必须排在 `GET .../player/` **之前**，否则被后者抢走。
* `POST .../start_race` 必须排在 `GET .../new_ranked` 之类更具体的前缀之后。

### 4.2 静态桩（改 JSON 的）

`rules.json` 的键是 `"<METHOD> <路径前缀>"`，`"*"` 是兜底。匹配优先级：
精确键 → 最长前缀 → `"<METHOD> *"` → `"*"` → 内置默认（200 + `{}`）。
不含空格的键（例如 `//friends2` 这种注释行）会被跳过，所以可以放心用 `//` 写注释。

`body` 是 dict/list 会序列化成 JSON，是字符串则原样发送。

> 只在**不需要状态**的端点上用 rules.json。任何要记账、要按玩家区分、要读存档的，
> 都该写进 `tf_server.py` 成为动态端点 —— 早期把 `/profiles/sessions` 放静态桩的后果
> 是「每次重启都要重新登录」「登录了也没分数记录」。

---

## 5. 端点地图

下面按功能分组。`cmd` 是客户端 `onNetworkDataReceived` 区分响应的命令码（逆向自
`libTrialsGo.so`），改响应形状时对不上就会静默失败。

### 5.1 会话 / 账号 / 存档

| 方法 | 路径 | 处理器 |
|---|---|---|
| POST | `/v1|/v2/profiles/sessions` | `h_session` —— v1/v2 = 用户名密码登录 |
| POST | `/v3/profiles/sessions` | `h_session` —— v3 = 设备静默登录 |
| GET | `/v1/profiles/sessions` | `h_session` —— 票据续期 |
| GET | `/v2/profiles/me` | `h_profile_me` |
| GET | `/v1/profiles` | `h_profiles_query` |
| GET/POST | `/public/playerprogress/v1/progress` | `h_progress` / `h_progress_latest` |
| — | `/progress/version` `/progress/status` | `h_progress_version` / `h_progress_status` |
| POST | `/progress/swap` | `h_progress_swap` |

存档格式：`progress` 的 body 是一组扁平数组（`items2` `highscores2` `achievements2`
`missions2` …），`items2` 是 `[id, value, id, value, …]` 对。`_SAVE_SECTIONS` 定义了哪些段
参与「完整度」比较，`_lost_sections()` 用来防止一次残缺的写入把已有进度覆盖没。
保存历史保留 20 份（`SAVE_HISTORY_MAX`），`/__history` 与 `/__restore` 可以回滚。

### 5.2 排行榜

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/public/playerstats/v1/ranking/<board>` | `h_playerstats_ranking` |
| GET | `/public/playerstats/v1/stats/…` | `h_playerstats_stats` |
| POST | `/public/resultservice/v1/enhancestats/batch_update`、`/track` | `h_result_stats`，把成绩落盘 |

* 全局榜 `global_stats` / `global_stats_donkey`（`GLOBAL_LEADERBOARDS`）会把所有赛道的
  成绩聚合起来。
* 响应里 `playerCount` **必须是全榜人数**，不是过滤后剩下的行数 —— 否则客户端的百分位
  永远显示 100%。
* `_opponent_entries()` 从 `FRIEND_NAMES` 造内置对手行，排行榜与 `replay_id` 都靠它。
* 未知赛道要返回**完整对象**（`{"leaderboard","playerCount","httpCode","results"}`），
  不能回 `{"data":[]}`：早期回空导致客户端对 `track66633` 反复重试（一天 337 次）。

**榜行里的 `data` / `upgrades` 是位域，不是计数器**（反汇编定论，见
`work/trials-frontier/notes/online-endpoints.md`）：

* `data` = 那一场**骑手外观**：bits 0–7 未用、8–13 一个 6 位字段（真机取 1/2/4/13，
  `encodeData` 会把 ≤1 归 0）、bits 14–19 / 20–25 / 26–31 分别是 outfit 的 part2 / part1 / part0。
  部件的**高 2 位不在 `data` 里**，合起来是 24 位 = 存档 `content.profile.outfit`。
  客户端 `LeaderBoardData::getOutfit(int)` 就是解它。
* `upgrades` = 车辆升级：bits 6–15 一个 10 位字段 + 四个 4 位字段（bit0–5 未用）。
* `bikeSkin` 只从 `extradata` 来（`parseData2` @0x625134），而**这一版客户端从不发 `extradata`**。
* **0 不是客户端会产生的外观值**：真机 172 条真成绩里 `data` 最小 `0x100`，
  而 `outfit = 0`（没自定义过的号，如华为账号）确实就是 `0x100` ⇔ parts (0,0,0)。
  服务端取不到真值时统一用 `_lb_ghost_data()`（`_LB_GHOST_OUTFITS` 里按 owner 稳定挑一套），
  绝不再发 0 —— 发 0 会让客户端拿没见过的值去渲染（服装错、骑手没脑袋）。

### 5.3 幽灵 / 回放

| 方法 | 路径 | 处理器 |
|---|---|---|
| GET | `/public/userstorage/v2/content/ghost/<id>/payload` | `h_userstorage` —— **裸二进制**，不经 JSON |
| GET | `/public/userstorage/v2/search/ghost/<track>` | `h_userstorage` |
| POST/PUT | `…/content/ghost[/<id>][/payload]` | `h_ghost_upload` |
| POST | `/public/resultservice/v1/replay_id` | `h_replay_id` |
| GET | `/public/resultservice/v1/replaydata…` | `h_ghost` |

**`replay_id` 的契约（踩过大坑）**：世界地图上从排行榜点对手，「比赛幽灵」按钮的可用性
完全取决于这里。响应**必须**是 `{"replay_id": <int ≥ 1>}`：

* 客户端 `tr::GhostQueryObject::onNetworkDataReceived`（cmd 0x0e）按 key 名 `replay_id`
  取值，`< 1` 一律当失败 → 按钮保持灰色。
* 因此 `h_replay_id` 会按 `profile_id` + `track_name` 反查 `_opponent_entries()`，回**真实存在
  且带二进制 payload** 的 contentId；查不到才回 `{"data": []}`。
* 拿到的 id 之后会走 `GET …/content/ghost/<id>/payload`，所以**回的 id 必须真的能下到**。

### 5.4 PVP / 碉堡（`pvp_matches/v1`）

**2026-10-05：奖励/经济链修复，尚待真机到账验收。**
`start_race → race → increase_rewards → matches → close` 现有实际记账；奖池、对局、免费票、金票、筹码和领取状态持久化。
金币/宝石由客户端成功回调发放，服务端不直接修改角色存档重复加币。
季奖配置仍为扁平运营条目，wire输出26档嵌套数组；特殊项 `item_id=145` 的 `amount` 是原表RewardID。
旧固定 `rewards.default/win` 占位奖池已删除，改为实际转盘上报累计。

```powershell
python -m unittest discover -s tests -v
```

当前仅验证基础价金票购买，套装折扣/旧缓存价会被拒绝；不能将21项隔离回归等同于真机完整复刻。
部署前备份数据并停止旧进程，源码修改需重启；不要同时开两个进程写同一状态文件。
详见 [本轮修复报告](<../work/trials-frontier/notes/2026-10-05_pvp-economy-report.md>)。

`h_pvp_init` / `h_pvp_matches` / `h_pvp_accept` / `h_pvp_player` / `h_pvp_race` /
`h_pvp_chips` / `h_pvp_new_ranked` / `h_pvp_config` / `h_pvp_season_data` /
`h_pvp_close_season`，参数全部来自 `tf_config.json` 的 `matchmaking` / `season` / `chips`。

* 机器人账号固定为 `matchmaking.bot_profile_id` = `44444444-4444-4444-4444-444444444444`，
  名字 `GhostRider`。
* 排队表有 TTL（`_PVP_QUEUE_TTL = 1800`），拿不到真人就回机器人。
* 机器人成绩 = 玩家成绩 × `bot_time_margin_pct` + `bot_time_margin_ms`（默认 1.018 / 400ms）。
* 赛季星星曲线 `season.star_array` 是 25 级天梯，`chip_equation_x/y` 决定筹码结算。

**外观（`outfit`）**：碉堡界面两侧的骑手立绘取自 `parseMatch` @0x4fd9d0 的 `player1`/`player2` 槽，
槽里 `outfit` 是 24 位（3 个 8 位部件：头盔 / 上身 / 下身），**直接来自该玩家存档的
`content.profile.outfit`**（`_pvp_outfit_of()`）。曾经这里硬编码 0，于是把对手也画成 0 号部件
（默认黄盔迷彩）⇒ 两台机器看起来"衣服没同步"。对局里客户端自己上报的 `outfit` / `bike_data`
也存在结果行里（`_pvp_reported()` 只收合法整数，垃圾值回退）。

**局内筹码与局外钱包是两笔钱**：对局槽里的数字 = `chip_base` + 局内占住赛道产出的筹码，
而 **`chip_base` 恒为 0**（用户 m01903 纠正：局内筹码从 0 起算，只有赢下赛道才开始涨；
以前把钱包余额灌进去，结果对手头像下面直接显示你的存款）。结算不受影响 ——
`_pvp_bank_match_chips` 只把「本局产出 = match − base」计入钱包，掠夺输家的也只是他这一局的产出。

### 5.5 限时活动 / 午夜杯（`liveevents/v1/weekly_track_system`）

`config/<week_index>`、`basic_info`(GET+POST)、`find_opponent`、`reward_config/<n>`、
`start_race` / `end_race` / `skip_cooldown` / `refill_retry_count`（后四个都进 `h_liveevents_accept`）。

* 周赛固定跑 `weekly.track_id`（默认 1041）；`_week_index()` 按 7 天一个窗口算，
  `weekly.week_offset` 把「本周」整体推后 N 周（= **模拟翻周**，真机验「敲奖杯/领奖」用）。
* `week_settings.week_leaderboard` 是客户端认的**排行榜数字 id**：发 `0` 等于告诉它「本模式没有榜」
  （榜区空白 + TOP 1% 条 + 周奖杯一起退化）。`weekly.leaderboard_id = 0` 时自动用本周赛道
  （`track<id>` 榜，复用榜单视图里已有的行）。
* `basic_info` 的 `(last_participated_week, last_participated_week_lb)` 决定客户端进哪个子状态：
  本周参加过 → 结算/领奖屏；只参加过上一周（配 `week_offset=1`）→ 上周结算屏。见 `_weekly_joined()`。
* `config/<week>` 必须**按请求的那一周**回 —— 翻周后客户端会来要上一周，回本周它会判定
  「配置不属于当前周」并每秒重试（界面卡在「查看进度…」）。
* `find_opponent` 必须回**pid + 该 pid 在本周赛道上的幽灵 contentId**：回显示名 + `replay_id=0`
  会让客户端以 ~30 次/秒刷 `find_opponent`+`stats`+`ghost/0/payload`(404)。见 `_weekly_opponent()`。
* 榜单里的「其他玩家」由 `weekly.fake_field`（默认 120）+ `fake_field_base_ms/fast_pct/slow_pct`
  合成（客户端用「名次/playerCount」算百分位，只有 3 行时永远进不了全球 1%）。合成行不落盘、
  不进总榜、同周内恒定。
* 每周次数是**服务端权威**的：`start_race` 扣、`skip_cooldown` 补满、`refill_retry_count` 加；
  剩余走 `basic_info.left_retry_times`，冷却**时长**是 `weekly.cooldown_seconds`（规则）。
  `ponytail:` 次数只在内存里（`_WEEKLY_ATTEMPTS`），重启服务器会白送满次数。
* 奖励池内容在客户端 `/conf/wts_rewards.txt`（15 个池子），服务端只能选「哪一档用哪个池子」：
  `weekly.reward_slots`(1..3) / `weekly.reward_ids`。**完整对照表**见
  `work/trials-frontier/notes/weekly-reward-pools.md`，WebUI 用的机器可读版本是
  `data/wts_rewards.json`（由 `tools/wts_reward_doc.py` 生成）。
  ★ 客户端挑「池内哪一件」用的是它**不播种的 `rand()`** —— 池子不变就永远是同一件。
* `config/<week>` 响应里 **`challenge_settings.bike_id` 必须是一个合法车辆 id** ——
  曾经给 0 导致「进入午夜杯场地」直接崩溃。

### 5.6 内购 / 礼包 / 好友（targeting）

| 方法 | 路径 | 处理器 |
|---|---|---|
| GET | `/public/receiptvalidation/v1/product/configuration` | `h_iap_products` |
| GET/POST | `…/verify_android` | `h_iap_verify` |
| GET/POST | `/public/targeting/v1/configuration` | `h_targeting_configuration` |
| GET | `/public/targeting/v1/condition_items` | `h_targeting_bundle_config` |
| GET | `/public/targeting/v1/vip_validation` | `h_vip_validation` |
| POST | `/public/targeting/v1/vip_registration`、`/private/targeting/v1/direct_vip_registration` | `h_vip_registration` |
| GET/POST | `/public/targeting/v1/vip_badge_option` | `h_vip_badge_option` |
| POST | `/public/friends/v1/update` | `h_friends_update` |

> ⚠ **真钱内购无法靠服务器伪造**。`receiptvalidation` 回成功只会让客户端再调
> `IAPManager::purchase()` 去问 Google Play；真正发奖的入口是
> `tr::StoreManager::onPurchaseComplete(IAPItemInfo*, IAPReceipt*)`。要做「免费购买」得在 native 层
> 把 `onPurchaseFailed` / `onPurchaseCancel` 尾调用重定向到它（patches 见 `tools/README.md`）。
> 服务器侧能做的只有把 `limited_purchases` 填出来让礼包「显示」。

### 5.7 礼物（`gift/v1`）

一个处理器 `h_gift` 覆盖 6 个 op（`give_golden_ticket` 0x3e / `send_gifts` 0x3f /
`get_gifts` 0x40 / `claim?type=` 0x41 / `gifts` 0x42 / `ad_reward` 0x43）。

* `GET gifts`（0x42）**必须回 `server_time`**：客户端 `OnlineGifting::isUptoDate()` 要求
  `+0x28` 非零，而这是唯一会写它的响应。不回就等于永远「数据过期」，客户端在碉堡界面里
  每 5.3 秒重发一次 `get_gifts`（实测 442 秒 85 次）。
* `GET get_gifts`（0x40）响应根**必须是 JSON ARRAY**；元素含大小写敏感的
  `type`（`"golden_ticket"` / `"fuel"`）、`amount`、`time_stamp`（绝对 unix 秒）、`friend`。
  不是数组只是得到空列表，不会崩。
* POST 类响应的 body 会被客户端丢弃，只有本地记账。
* 服务端不校验 `checksum`。

### 5.8 其它

`h_timeservice`（服务器时间，客户端有 `TS_SALT` 签名）、`h_match_robot`（A.N.B.A 假对手，
`_ROBOT_NAMES` 里 16 个名字）、`h_placeholder_image`（所有图片请求的占位图）、
`h_pvp_banner`（赛季横幅）。

---

## 6. 运行时配置 `data/tf_config.json`

按 mtime 热加载，改完存盘即生效。键：

| 分组 | 关键项 |
|---|---|
| `matchmaking` | `enabled`、`bot_wait_seconds=60`、`active_window_seconds=300`、`search_ttl_seconds=1800`、`track_id=1041`、`bot_profile_id`、`bot_name`、`bike_id`、`free_tickets_max/initial/interval_seconds`、`start_rank=25`、`candidate_tracks`、`bot_time_margin_pct=1.018`、`bot_time_margin_ms=400` |
| `season` | `track_id`、`title_text`、`banner_path`、`duration_days`、`star_array`（25 级天梯每级星数）、`product_list`、`rewards`、`chip_equation_x/y` |
| `weekly` | `track_id=1041`、`left_retry_times=3`、`window_hours=24`、`task` |
| `rewards` | `default=[150,1,0]`、`win=[300,2,0]` = `[金币, 钻石, 特殊奖励等级]` |
| `chips` | `start`、`per_track_seconds`、`max`、`bot_start=500`、`match_loser_keeps_pct=50` |

缺键会与 `_TF_CONFIG_DEFAULTS` 深合并补齐，所以可以只写要改的部分。
`/__config` 可以读，`cfg_set()` 可以写回。

---

## 7. 本地管理端点（`/__*`）

这些是**本机管理接口，不是游戏协议**，客户端永远不会请求它们，也不进请求日志。

**访问控制**（`server/tf_server.py` 的 `_introspect` 里那段「唯一的墙」）：服务器绑 `0.0.0.0`，
局域网里谁都能连，所以除下面四个公开端点外，**所有 `/__*` 都要管理员 Cookie**：

| 公开端点 | 为什么公开 |
|---|---|
| `/__ping` | 存活探测 |
| `/__ui`、`/__register`、`POST /__api/register` | 玩家要在游戏里自助注册账号（`_WEBUI_HTML` 内嵌页），登录页本身也得能加载 |

改前裸奔、现在要管理员的一批：`POST /__config`、`/__restore`、`/__api/login`、
`/__api/password`、`/__api/delete`。实现上用 `path.startswith("/__") and path not in _PUBLIC`
（而不是白名单表），**新增端点默认是关的**，忘了加门禁也不会漏。

### 7.1 后台管理页 `/__admin`

```
后台管理页： http://127.0.0.1:8000/__admin   （手机用 http://<局域网IP>:8000/__admin）
```

* 管理员账号**独立于玩家账号**，存在 `data/admin.json`（`_hash_pw` = sha256(salt+用户名小写+NUL+口令)，
  与账号库同一套；不入库）。**没有网页自助创建** —— 否则第一个访问到 `/__admin` 的人
  就能把自己设成管理员。
* 首次启动若无管理员，`admin_bootstrap()` 生成 12 位随机口令，**只打到控制台**（66 字符宽的框）；
  登录后发 `tf_admin` Cookie（`HttpOnly; SameSite=Strict; Max-Age=604800`，**故意不加 `Secure`**：
  服务器只能走明文 HTTP，加了浏览器不回传，登录会静默失效）。
* 忘了口令：`python tf_server.py --reset-admin`（无参数 = 再随机一个）。带上口令要 ≥8 位。
  这条走命令行而不是网页，同样是为了不留无窗口期的后门。
* 页面是静态四件套（`server/admin/`），CN/EN 双语（`i18n.json`，`localStorage.tf_lang`
  优先、否则跟随 `navigator.language`）。前端**只用 `textContent` 渲染玩家可控字符串**
  （账号名 / 平台名直接来自客户端上报，是信任边界）。
* 「下发物品」屏的物品清单来自 `server/admin/items.json`（478 条物品 + 80 套服装 + 108 款涂装
  + 12 个蓝图 + 382 条赛道 + 304 条奖励名，中英名直接取自游戏自己的本地化表），由
  `tools/build_item_catalog.py` 从解包出的 `content.dat` 生成 —— 改物品表 / 套装表 / 车表 /
  升级表 / 赛道表就重跑它。每条带 `cat` 与 `verified`：
  只有**真机上确认过存档写法**的类（货币 / 消耗品 / 零件 / 服装 / 蓝图）不带「未验证」警告；
  赛道没有证据，会挂警告。`outfit` 在存档里是 0/1 标志（只能解锁，mode 固定 `set`），
  **蓝图和其余类一样是计数器**（这一条最初写错了，见下面那条）。
  另外两段不参与下发、只喂下拉：`levels`（382 条赛道 → `track_catalog()`，午夜杯的
  `weekly.track_id` 与碉堡的候选/固定赛道都用它）、`rewards`（`/conf/pvp_match_rewards.txt`
  的 RewardID → 名字 → ItemId；碉堡「赛季奖励」的下拉**只取其中 `PVPMatchSpecialRewards`
  那 43 个编号**，见 §7.1 那条）。
* **服装按「套」列**（`outfits` 段，来自 `/conf/customization.txt`）：勾一套 = 头盔 / 上衣 /
  裤装三件一起解锁（`id = ItemType * 5 + tier`），行上带官方名 + 内部代号 +
  「已拥有 n/3」+ **套装效果文案**（`BonusPower`，集齐即账号级生效，例如 The High Roller
  = 无限汽油）+「隐藏」标记（`UnlockType` 全 4 = 没上架过的 46 套）。240 件里 99 件在任何
  配置里都不出现，是按套装表推出来的；与「赛道解锁」撞车的 20 个编号按服装归类。
* **涂装按「车」列**（`paints` 段，来自 `/conf/bikes.txt` 的 `SkinData`，108 款）：
  ★ 涂装**不占 `items2` 的键**（一半涂装编号同时是零件号，按 id 发下去会写到零件计数上）。
  存档里每辆车只有一条 `items2[664 + BikeID] = ((当前装备的 SkinIndex + 1) << 24) | 已拥有位掩码`，
  所以界面按车分组、勾一款 = 给那一位置 1（`tflocal_accounts._paint_value()`），
* **蓝图按「车」列**（`blueprints` 段，来自 `/conf/upgrades.txt` 的 `BP`，12 辆车）：
  ★ 蓝图是**碎片计数器**，不是 0/1 标志（真机档里 379 = 7 片、404 = 3 片、429 = 1004 片）。
  编号 `id = (车号 + 72) * 5 + 4`，需求量每辆车不同（Tango 4 片、Bronco 20、KTM 450 RALLY 30、
  Stallion / Donkey 50…，与官方文案里 7 处 "Collect N to build" 逐条吻合），行上显示
  「需要 N 片 / 已拥有 n/N」，勾选时数量框默认填「还差几片」。19 辆车里只有 12 辆有碎片编号，
  另外 7 辆（Armadillo / Jackal / Mantis / Marauder / Riptide / Phantom / Moonrover）在任何
  配置里都没有编号、只能金币买，界面会说明、不造条目。374/379/439 的官方名被 RedLynx 写成了
  Tango 的 Redlynx 涂装名，目录里换成规范名并把旧名留在 `alias`（仍然可按旧名搜到）。
* **午夜杯运营屏**（侧栏独立入口「午夜杯」）：把 `weekly.*` 的键分成 6 张卡（现状 / 时间 /
  挑战规则 / 赛道与对手 / 奖励 / 模板），每张卡一个「保存改动」，**只发改过的键**。
  两个新东西：①`weekly.window_days`（1..30，默认 7）—— `_week_span()` 用它替换了所有
  `_WEEK_SECONDS` 算术（周号反推 / `weeK_end` / `midnight_circuit_end_time` / `week_end`），
  不等于 7 天时管理端点回 `experimental: true`、界面标「实验性」；②参数**模板** = 整页快照
  （存 `data/templates.json`，支持「套用整页 / 只套用奖励方案 / 重命名 / 复制 / 删除」）。
  每次参数改动记一条审计（`data/config_audit.jsonl`，保留 300 条），界面上逐条能**一键撤销**
  （`cfg_unset()` 负责把键删回代码默认值，`cfg_set()` 记 `existed`/`before`）。
  ★ 奖励卡**只暴露池子编号 1..15**：每池装什么在客户端的 `/conf/wts_rewards.txt` 里
  （`getRewardItemForSlot`），所以界面不预览内容；客户端**只在进入午夜杯时读一次**奖励配置，
  卡片上写明「改完让玩家退出午夜杯再进」（不用重启游戏）。
* **碉堡（PVP）运营屏**（侧栏独立入口「碉堡」）：8 张卡（现状 / 赛季 / 对局时长 / 段位与星章 /
  匹配与 AI / 筹码与曲线 / 赛季奖励 / 模板），字段表整张在服务端（`_BUNKER_CARDS` + `_bf()` +
  `_BUNKER_FIELDS`：中英标签、说明、`kind`、范围），前端只按 `kind` 造控件 ⇒ **加一个运营参数
  只改服务端**。写路径与审计/撤销/模板跟午夜杯完全共用（`_PAGE_HOOKS` 里多一条 `bunker`）。
  几个必须记住的边界：
  - **赛季显示编号**（`season.display_offset`）只在**下发边界**套偏移，内部届号（`_pvp_season_window()`
    的时间派生值）、赛季窗口、玩家档案里的 `season` 都不动；`season.advance` = 推进计数，
    让本届窗口整体往前挪一轮。
  - **赛季名不能含 `|`**：`title_text` 是纯文本（本地化分支只在 NULL 时走），但客户端
    `PopupStatePVPXGames::getPVPSeasonName` 只取第一个 `|` 之后的部分 ⇒ 含 `|` 直接 `bad-pipe`。
    **换横幅图必须换 URL**（客户端拿 URL hash 跟 `season_banner%d.bnr` 里的 4 字节比，不符才重下）。
  - **特殊奖励是 RewardID 不是 ItemId**：`item_id 145` 的 `amount` 由客户端的
    `/conf/pvp_match_rewards.txt` 解释。★★ **只有原表 `PVPMatchSpecialRewards` 里的 43 个编号
    能用**（`_PVP_SPECIAL_GROUPS` / `_PVP_SPECIAL_IDS`：零件 4 档 + 202 Soylent 涂装 +
    203 Luchador 涂装 + 220 毛驴图纸），别的编号服务端判 `bad-special:<id>`，界面当场标红。
    原因：`PVPManager::getSpecialRewardById` 是 **get-or-create**，未知编号会就地插一个空的
    `WheelReward` ⇒ 玩家看到的是同一个占位物（毛驴轮胎）。喷漆 / 衣服 / 赛道只存在于另一张
    309 条的轮盘表，**当不了赛季奖励**，要发请走「下发物品」页。
  - **段位名不存在**（客户端 `MenuzComponentPVPRank` 里零次本地化调用、LOCF 里也没有
    `RANK_%d` 键）⇒ 只提供星章表与起始段位，卡里只读说明。
  - **绝不直接编辑 `data/pvp_state.json`**：金票 / 筹码 / 段位 / 星 / 连胜只走 `/__api/admin/*`
    （内部走 `_pvp_request` 事务），手改文件会被服务端下次写盘覆盖。

### 7.2 端点

| 端点 | 作用 |
|---|---|
| `/__log` | 最近 400 条请求的环形缓冲 |
| `/__accounts` | 账号列表（脱敏） |
| `/__devices` `/__sessions` | 设备槽 / 活跃会话 |
| `/__saves` `/__save` `/__history` `/__restore` | 存档查看 / 指定槽位 / 历史 / 回滚 |
| `/__leaderboards` `/__ghosts` | 排行榜 / 幽灵仓库内容 |
| `/__config` | 当前生效的运行时配置 |
| `/__help` | 端点清单（**新增端点要同步登记**，这是自发现的唯一入口） |
| `POST /__api/admin/login` `logout` `me` | 管理员登录 / 登出 / 当前身份（`me` 未登录也 200） |
| `GET /__api/admin/info` | 后台要展示的两条外发地址：玩家注册 `/__ui`、手机上的后台 `/__admin`（基址走 `_public_host()`，**绝不回环**） |
| `POST /__api/admin/password` | 改口令（<8 位拒；改完**重签 Cookie**，否则把自己踢掉） |
| `POST /__api/admin/grant` | 存档下发（可下发项 = `admin/items.json` 的 478 条，服装按套勾，蓝图按车勾、可填片数；`paints` 字段 = 涂装 id 数组，写 `items2[664+BikeID]` 的位掩码；每次先埋快照） |
| `POST /__api/admin/rollback` `revert` | 回滚到历史快照 / 撤销上一次下发（回 `snapshot` 名字给界面做「撤销」） |
| `POST /__api/admin/sessions/clear` | 清会话票据（不动 `remember.json`，玩家不会被踢出登录态） |
| `GET\|POST /__api/admin/weekly` | 午夜杯运营参数（GET = 配置 + 现状 + 赛道目录 + 模板 + 最近改动；POST `{fields:{…}}` **逐键校验、全部合法才落盘**，每个键回 `{key,before,after,audit}`） |
| `GET\|POST /__api/admin/bunker` | 碉堡运营参数（GET = 8 张卡的字段表 + 当前值 + 现状（赛季/玩家/对局/队列/在线）+ 赛道与奖励目录 + 模板 + 最近改动；POST 同 weekly 的 `{fields:{…}}` 契约，空值 = 删键回默认） |
| `POST /__api/admin/undo` | 撤销一条参数改动（`{id}` 来自 weekly / bunker 的 `audit`；按记录里的 `existed` 决定写回还是删键） |
| `GET\|POST /__api/admin/templates` | 参数模板（GET `?page=weekly\|bunker`；POST `{page,action:save\|apply\|copy\|rename\|delete,name,new_name,parts}`，`parts` 可 `all` / `rewards`） |

### 7.3 下发的两条通道（别搞混）

* **竞技场（服务端权威，即时生效）**：金票 / 筹码直接写 `data/pvp_state.json`，
  客户端无从覆盖。金票**不是存档物品**（`items2` 里 id 135 从来不存在），
  所以它只能走这条路 —— 见 `ROADMAP_STATUS.md` 的「金票」条目。
* **存档物品（尽力而为）**：改 `data/save/<pid>/latest.json` 的 `items2` 并 **bump `version`**。
  bump 是必需的（否则 `remote == local`，客户端静默用本地档覆盖服务器），但 bump 后
  客户端也**可能不弹** `MenuzStateSyncProgress` 而是直接推本地档 ⇒ 不保证送达。
  界面上必须如实这么写，别承诺「即点即得」。

---

## 8. 开发约定

* **纯标准库**。不要为了一个小功能引入依赖（`tools/re/` 下的逆向脚本可以依赖
  pyelftools / capstone，那是另一回事）。
* **不要静默编造数据**。响应形状必须能对上客户端的解析器；宁可回一个明确失败形状
  （如 `{"data": []}`），也不要用看似合理的假数据 —— 假数据会让客户端进入更难查的状态。
* **改端点先查笔记**。`work/trials-frontier/notes/online-endpoints.md` 是全端点台账，
  `gift-v1.md` / `friends-v1.md` / `targeting-v1.md` / `_inline-build.md` / `item-ids.md`
  是按功能分册的逆向记录；`../ROADMAP_STATUS.md` 的 §3.x 记的是每个真实 bug 的完整链路。
  这些笔记里都带了 libTrialsGo.so 里的地址与指令，改之前先读能省掉一整轮反汇编。
* **验证要真机**。服务器回 200 不代表客户端认了 —— 常见失败模式是解析器静默丢字段
  （按钮不变、列表为空、轮询不停）。`server-log.jsonl` + `adb logcat` 一起看：
  ```powershell
  & D:\SDK\ADB\adb.exe -s <serial> logcat -v time '*:F' 'DEBUG:V' 'alsfrontier.ggp:V'
  ```
  用 `*:F` 而不是 `*:E`，否则会被设备上无关的指纹 HAL 崩溃日志刷屏。
* **重试 `ReplaceFileW EIO (Win32 1175)`**。本仓库在 Windows 上偶发这个错误，直接重试即可。

### 逆向坐标约定（读笔记时会用到）

`libTrialsGo.so`（7.9.4，AArch64，14901128 字节）：

* `.text`（VA `0x3661b0`）、`.rodata`（VA `0xb3b840`）的 **VA == 文件偏移**。
* 从 `.init_array` 起（VA `0xdb9dc8`）全部 **VA − 0x10000 = 文件偏移**：
  `.data.rel.ro` VA `0xdba140`、`.got` VA `0xe08eb0`、`.data` VA `0xe23000`。
* 本地化 id = `mt::String::getHashCode(KEY)` @`0x8695ac`（实现在 `tools/re/mt_hash.py`）。

---

## 9. 已知缺口

* `limited_purchases`：`h_iap_products` 现在回空数组。要显示礼包得知道 `product_id`
  与 bundle id 的映射，而且**点了仍会走 Google Play**（见 §5.6）。
* `dlcontent_frontier_android/794/info.json` 一直落 `*` 兜底回 `{"data": []}`，
  是否该有真实内容尚未确认。
* `friends/v1/update`、`pushnotification/v1/register_device`、`targeting/v1/condition_items`
  目前只回 `{"data": []}`，够用但没做真的语义。

真正还没闭环的以 `../ROADMAP.md` 和 `../ROADMAP_STATUS.md` 为准。
