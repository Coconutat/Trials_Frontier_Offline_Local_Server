# ROADMAP 进度与任务规划

> 对应根目录 [`ROADMAP.md`](ROADMAP.md)。本文档记录每一条的**当前完成度、证据、缺口、下一步动作**。
> 最后更新：2026-10-04 22:40（设备 `<设备序列号>` / 小米 8 / LineageOS 22.2 `ursa`）

---

## 总览

| # | ROADMAP 条目 | 状态 | 完成度 |
| --- | --- | --- | --- |
| 1 | 修复 APK 启动 BUG（联网闪退） | ✅ **已修复并实机验证（m14/m15）** | 100% |
| 2 | 修复账号管理（注册 / 登录分离） | ✅ **已实现并 curl 实测（含内置注册页）** | 85% |
| 2b | VIP 下发（买了 VIP 就激活 VIP 事件） | ✅ **已实机验证（m16）** | 100% |
| 3 | 在线功能完善（碉堡 / 午夜杯 / 限时活动 / 排行榜 / 幽灵对手） | 🟡 **排行榜 + 幽灵已通；限时活动/碉堡/午夜杯待做** | 55% |
| 4 | WebUI 管理界面 | 🟡 **已起头：`/__ui` 注册页 + `/__api/*`** | 15% |
| 5 | 一键开服打包成 exe | ⚪ 未开始 | 0% |
| 6 | 设备侧：游戏数据重定向到 `/sdcard/Android/data/<pkg>` | ✅ **绑定挂载已实机验证 + 重启自动恢复** | 90% |

---

## 1. 修复 APK 启动 BUG —— 联网闪退

### 用户观察（ROADMAP 原文）
> 经过测试，如果联网就会闪退，关闭 wlan 等启动就能进入，再开启网络即可。可能是连接谷歌服务，我们要劫持这一部分网络，让它来到我们服务器。

### ✅ 已修复（2026-10-04，m14）

**根因（tombstone 实证）**：闪退是 `tr::VIPManager::getPlayerMembership()` 里的**空指针解引用**，
跟谷歌服务、跟我们服务器地址都无关。

```
#00 libTrialsGo.so  tr::VIPManager::getPlayerMembership()+120   ← 读 0x0，崩溃点
#01 libTrialsGo.so  tr::UserTracker::getMembershipDate()+88
#02 libTrialsGo.so  tr::UserTracker::updateCommonAttributes()+44
#03 libTrialsGo.so  mz::DNAManager::sendDnaEvent(...)+168
#04 libTrialsGo.so  tr::UserTracker::sessionStart()+1492
#05 libTrialsGo.so  tr::UserTracker::init()+320
#06 libTrialsGo.so  tr::GlobalData::init(mz::InputPointerState*)+1236
#07 libTrialsGo.so  tr::MainApp::init()+112
#08 libTrialsGo.so  resize+420
#09 boot.oat        art_jni_trampoline+112
#11 base.vdex       com.ubisoft.redlynx.trialsgo.GL2View$Renderer.onSurfaceChanged+10
#13 framework.jar   android.opengl.GLSurfaceView$GLThread.guardedRun+994
```

`getPlayerMembership()` @`0x0062e5c4` 反汇编（关键片段）：

```
0x62e5f0  bl NetworkChecker::getNetworkType ; cbz w0        -> 空返回   ← 断网就跳过，故只有联网才崩
0x62e600  cmn w0, #1                        ; b.eq           -> 空返回
0x62e60c  bl AntiCheating::isValid          ; tbz w0,#0      -> 空返回
0x62e630  bl PlayerItems::getItemCount      ; tbz w0,#0      -> 空返回   ← 存档里有会员道具才继续
0x62e638  ldr x0, [x21]        ; x0 = this->[0]  ← slot0 会员计时器指针
0x62e63c  ldr w8, [x0]         ; ★ 崩在这（x0 == NULL）
0x62e6b4  ldr x0, [x21, #8]    ; slot1 同一模式
0x62e6b8  ldr w8, [x0]         ; ★ 同样会崩
```

会员计时器由 `VIPManager::activateMembership()` 创建，**正常由服务器下发触发**；
离线私服从不激活会员，但存档里存在会员道具（item 0x80），于是过了三道闸后指针仍为 NULL。

**修法（2 × 4 字节）**：把两处 `ldr w8,[x0]` 换成 `mov w8,#0`，后面紧跟的
`cbz w8, ->空返回` 于是总是跳到「空会员列表」分支，彻底不碰空指针。
语义 = 离线状态下玩家不是俱乐部会员。

| 补丁 id | 文件偏移 | 原始 → 补丁 |
| --- | --- | --- |
| `vip-membership-null-timer-slot0` | `0x0062e63c` | `08 00 40 b9` → `08 00 80 52` |
| `vip-membership-null-timer-slot1` | `0x0062e6b8` | `08 00 40 b9` → `08 00 80 52` |

两条都已写进 `tools/patch_native.py`（现共 11 条补丁，`--dry-run` 全 `[OK]`）。

**实机验证（联网状态，`192.168.1.100:8000`）**：进程存活 135 秒以上、`am_crash` / `am_proc_died` 零条，
服务器收到完整启动序列
`GET /` → `/dlcontent_frontier_android/794/info.json` → `/v1/applications/<appid>/configuration`
→ `POST /v3/profiles/sessions` → `/frontieronlinecontent/loc.json` → News。截图 `tmp\m14a.png`。

**取证技巧（可复用）**：`debuggerd` 一开始不为游戏落 tombstone，先执行
`adb shell "cmd package compile -m speed -f com.ubisoft.redlynx.trialsfrontier.ggp"`
强制 AOT 重编译，之后 `adb logcat -d` 里的 `F DEBUG` 行就是游戏的完整 native 栈。

### 事后复盘：走过的弯路（别再重复）
**闪退由「设备具备外网可达性」触发，与本机服务器地址无关。**

| 条件 | tf_server.txt | WLAN | adb reverse | 结果 |
| --- | --- | --- | --- | --- |
| A | `192.168.1.100:8000` | UP（有外网） | 无 | **native SIGSEGV 崩溃** |
| B | `127.0.0.1:8000` | UP（有外网） | 无 | **native SIGSEGV 崩溃**（且服务器收不到任何请求） |
| C | `127.0.0.1:8000` | UP（有外网） | 有 | **native SIGSEGV 崩溃** |
| D | `127.0.0.1:8000` | **DOWN** | 有 | **✅ 正常存活**（pid 16782 / 16782，`am_crash` 零条） |

崩溃特征（`adb logcat -b events`）：

```
am_crash: [2158,0,com.ubisoft.redlynx.trialsfrontier.ggp,954776644,Native crash,Segmentation fault,unknown,0,0]
am_proc_died: [0,<pid>,com.ubisoft.redlynx.trialsfrontier.ggp,0,2]
```

- 约每分钟复现一次（17:20:25 / 17:21:18 / 17:22:25 / 17:23:50）。
- `crash` 缓冲区与 `/data/tombstones/` 里**没有游戏的 tombstone**，只有与游戏无关的指纹 HAL 崩溃
  （`fingerprint.syna.sdm845.so` 的 `palMutexFree` FORTIFY abort）——那是设备噪声，可忽略。
- 游戏进程内的 SIGSEGV 没有 dump，说明 `debuggerd` 没能为它落盘（或被信号处理吞掉）。

### 被排除的可能（当初的弯路）
- **不是** `tf_server.txt` 里的地址字符串太长导致缓冲区溢出。`tools/patch_dynaddr.py` 注入的例程
  （`build_routine()`，第 216 行起）用 `read(fd, sp+0x60, 0x3f)` 读入（上限 63 字节）、NUL 截断、
  去首尾空白，host 扫描有 `cmp x28,#64; b.lo` 上限，写回每个字面量前还有容量检查
  `sub x22, x27, #7 ; subs x22, x22, x21`。`192.168.1.100:8000`（16 字节）远低于上限。
- **不是**局域网路由问题。设备侧 `curl -s -m 4 http://192.168.1.100:8000/__ping` → `pong`，
  PC 侧 `http://192.168.1.100:8000/__ping` → `pong`，TCP 路径通畅。
  （设备 `ping 192.168.1.100` 100% 丢包是 ICMP 被防火墙挡，不能作判据。）
- **不是**内购补丁引起的：装不含 IAP 补丁的 `tf-m8-release-backup.apk` 照样崩。
- **不是** Google / 阿里 DoT 流量引起的：用
  `iptables -N TFBLOCK; iptables -A TFBLOCK -d 192.168.1.100 -j RETURN; iptables -A TFBLOCK -j DROP;
  iptables -I OUTPUT -o wlan0 -j TFBLOCK; ip6tables -I OUTPUT -o wlan0 -j DROP`
  把整条 wlan0 出网全封（只放行本机服务器），**仍然崩溃**。
  （这些规则已在 10-04 清理掉。）
- ⇒ **真正起作用的只是「Android 是否报告有可用网络」这一个事实**，因为
  `NetworkChecker::getNetworkType()` 是那道最外层的闸。

### 联网时游戏的行为（修复前）
服务器日志显示，联网启动时**只发出 `GET /?product=101&portal=Google&version=7.9.4` 一条请求就崩溃**；
而 WLAN 关闭时能正常进村庄。正常跑通时的请求序列是
`GET /` → `/dlcontent_frontier_android/794/info.json` → `/v1/applications/1c91448e-…/configuration` → …
⇒ 崩溃发生在 `GET /` 之后、第一个 Ubiservices 请求之前，即 `GlobalData::init` 阶段的遥测路径里
（现已与 tombstone 完全对上）。

---

## 2. 修复账号管理

### 用户要求
> 登录一个账号等于注册一个新账号，这不行，我们要有账号注册功能。然后登录是登陆，登陆时查找我们私服的数据库，对应上才能登陆。

### ✅ 已完成（2026-10-04，注册/登录彻底分离）
- 删掉会隐式建号的旧 `ensure_account`，换成一对明确函数（`server/tflocal_accounts.py`）：
  - `register_account(user, pw, name?) -> (acc, err)`，`err ∈ {None, "bad-request", "exists"}`
  - `login_account(user, pw) -> (acc, err)`，`err ∈ {None, "bad-request", "not-found", "invalid-credentials"}`
    —— **只查库，绝不建号**；对早期无口令的老账号补写本次口令；成功则记 `logins` / `last_login`
  - `set_password` / `delete_account` / `list_accounts_public()`（去掉 `pw`/`salt`，附 `created_iso`/`last_login_iso`）
- `POST /v3/profiles/sessions` 的 `Basic` 分支改走 `login_account`，失败一律 **401** + 可读原因：
  ```json
  {"error":"not-found","errorCode":"NOT_REGISTERED",
   "message":"此账号尚未在本地服务器注册，请先打开 http://<服务器IP>:8000/__register 注册"}
  ```
- 新增**内置注册页**：`GET /__ui`（别名 `/__register`）→ 深色主题单页；
  API：`POST /__api/register`、`/__api/login`、`/__api/password`、`/__api/delete`。
  > `GET /` 被游戏 gamecfg 端点占着（`/?product=101&portal=Google&version=7.9.4`），网页只能挂 `/__`。
- curl 实测：未注册 → 401 `not-found`；老账号 `test@example.com:<口令>` → 200
  （`profileId=<player-profile-id>`）；重复注册 → 400 `exists`；
  错口令 → 401 `invalid-credentials`；`/__register` 页 200。

### 缺口
- 客户端侧没有"注册"入口（游戏本身只会发登录请求），所以**注册必须先去 `/__ui` 网页**。
- 口令是明文 HTTP + base64 传的（内网可接受，但需要文档说明）。
- 存档同步已打通（见 §2.1）。

### 2.2 VIP 下发（m15 → m16，已实机验证）
- **链路本来就在**：买下商店骑士俱乐部档位 → `StoreManager::onPurchaseComplete`
  → `StoreManager::pushItemPurchasedPopup` → **`VIPManager::activateMembership(type)`**
  （`activateMembership` 全库仅 `0x0057a7e8` / `0x0057a86c` 两个调用点，都在 `pushItemPurchasedPopup` 内）。
- `activateMembership` 会 `PlayerItems::setItemCount(0x80, 0, … | (1<<type))` 并启动会员计时器
  （时长 `GlobalSettings::getSetting(…)` 默认 `0x278d00` = 2592000 秒 = 30 天），
  **道具 id `0x80`（=128）即会员位掩码**，bit0/bit1 = 「未来的会员」/「道路队长」。
- m14 用的「把 `getPlayerMembership()` 涂成常量空列表」虽能止崩，却让会员状态永远读不出来，
  VIP 下发无从谈起。**m15 换成 5 × 4 字节的空指针守卫**（见 `dist/README.md` §11.3），
  语义与原始逻辑一致，且 `VIPManager::init()` 跑过之后能如实返回真实会员状态。
- **第二个缺口（m16 修掉）**：`VIPManager::isVIPStoreOfferAvailable()` @`0x0062edd4` 要求
  `StoreItem && IAPItemInfo` 同时非 NULL，而离线没有 Google Play，
  `mz::IAPManager::getProductInfoEnabled` 恒返回 NULL ⇒ 档位不可用。
  m16 把 `OfferManager::findVIPOffers` 里那条 `bl`（`0x006019e0`）改跳进代码洞
  `0x0096d85c`，洞里 3 条指令返回一个伪造的 `IAPItemInfo`（`+0x84` bit0 = 1）。
  只动这一条调用，`0x0088a3e4` 那处购买校验等其它 IAP 路径完全不变。
- **实机结果（2026-10-04 11:32，小米 8 / LineageOS 22.2）**：
  骑士俱乐部两档由「未知（离线）」变成 **「剩余时间：29天」**；进村庄弹
  **「每日登录奖励」65💎 + 65000🪙，剩余时间 29 天**；服务器日志同秒收到客户端主动发出的
  `POST /public/targeting/v1/vip_registration`、`POST /private/…/direct_vip_registration`、
  `GET /public/targeting/v1/vip_validation`、`GET|POST /public/targeting/v1/vip_badge_option`。
  `registerMembership()` 全库**只有 `VIPManager::activateMembership` 一个调用者**
  ⇒ 证明两档会员都被真正激活（`activateMembership(0)` 与 `(1)` 各一次）。
- 服务端实现：`server/tf_server.py` 的 `h_vip_registration` / `h_vip_validation` /
  `h_vip_badge_option`，`DYNAMIC_EXACT` 里共 5 条。唯一被解析的是 `vip_validation`
  （`onNetworkDataReceived` @`0x0051b0ac` 只有 `cmp w3,#0x73` 一个分支），
  响应必须含顶层键 `player` 与 `badge_display`。
- 仍缺：`activateMembership` 是**本地生效**的，服务端存档里暂时还看不到 item 128
  （等客户端下次上报会带上来）；也没有服务端「免费发放会员」的管理接口。

### 2.1 存档持久化与「登录后清档」事故（已完成修复）
- 根因：`tr::OnlinePlayerProgress::parseResponse` @`0x0057433c` 的 **cmd 0x24** 分支
  `parseProgress` → `Player::save()` @`0x362bc0` 是**无条件**的。服务器对
  `GET /public/playerprogress/v1/progress` 回 `{"data": []}` ⇒ 客户端本地存档被清空。
- 修复：`serve_progress()` 永不再回空 JSON（无档时 **404**，让客户端走 `onNetworkError`）；
  新增防清档护栏（新档 richness 不到旧档一半就只记 history）；每次上报把 payload 外层 `version` +1；
  `/progress/version` 回非 0 版本号，让 `ProgressSyncManager::onProgressCheckComplete`
  判定"版本冲突"从而给出云端恢复入口。
- 用户丢失的进度已从 `server-log.jsonl` 里捞回并恢复
  （`identifier = 742E35A97CEE6BF4D95A7B567BD58042FCD53E1D`，`tmp/recover_save.py`）。
- 真机验证：登录 → `/progress/version` → `GET /progress` 下载 → `player.bin` 1096→1890 →
  HUD `402/402` 汽油、`6,633,802` 金币、`8,905` 宝石、`9` 星 ✅

#### 2.1.1 第二次清档事故（2026-10-04 22:42，「半个档」覆盖，已修复）
- **现象**：玩家进游戏只见**新手教程**（"你好骑手！请在提车前确认"），金币/钻石/赛道纪录全没。
- **根因**：客户端在一次冷启动里会连做两次 `syncProgress` —— 先 POST 一份**完整档**
  （17 个键 / ~25 KB），**约 6 秒后**再 POST 一份**半个档**（7~8 个键 / ~3.9 KB）。
  后者只带 `checksum / game_version / identifier / items2 / (robotman) / timers2 /
  timestamp / version`，而 `profile`、`highscores2`、`achievements2`、`missions2`、
  `statistics2`、`tutorials2`、`settings` **全部缺失**（客户端自己的序列化时序问题）。
- **为什么旧护栏没拦住**：第一道护栏只看 `_richness`（`items2/2 + highscores2 +
  achievements2 + tutorials2 + (missions2?5) + (statistics2?5)`）。半个档的 items2 有
  **428 对**，`428*2 = 856 > 650/2` ⇒ 判定"不算清档"，照常覆盖 `latest.json`
  （实测 `richness 650 -> 428`、段落 `17 -> 8`）。
- **修复**（`server/tflocal_accounts.py`）：
  - 新增 `_SAVE_SECTIONS` 与 `_lost_sections()`：**旧档里非空、新档里缺失/变空的段落，
    一个都不许丢**（`items2 / highscores2 / achievements2 / missions2 / statistics2 /
    tutorials2 / settings / profile / store_bonus / dailyexperience`）。
  - 护栏改为「段落丢失 **或** richness 减半」命中即拒绝，被拒的那份仍写进 `history/`。
  - 拒绝分支回 `server_version = 旧版本 + 1`。旧实现误写成 `version` 键 ⇒ `h_progress`
    回 `version=0` ⇒ 客户端以为服务器没档、下一轮继续推本地（永远走不到恢复）。
    回「+1」而**不是**旧版本，是为了让下一轮 `GET /progress/version` 与客户端记在
    `Player+0x4864` 的本地版本对不上 ⇒ `ProgressSyncManager::onProgressCheckComplete`
    判定版本冲突 ⇒ 拉起 `MenuzStateSyncProgress`，把"用云端"的恢复入口交回给玩家。
- **恢复过程**：完整档仍在 `history/1791124895.json`（22:41:35）；`tmp/restore_now.py`
  把它提回 `latest.json` 并把 `version` 抬到 71。真机复验：
  `GET /progress/version → GET /progress/status → GET /progress` 客户端拉下完整档，
  村庄 HUD 回到 **16,748,033 金币 / 9,066,302 钻石 / 456/456 汽油**，
  `highscores2` 里 **36 条真跑过的赛道纪录一条不少**（旧档的 200 条里有 164 条是
  `[track,0,256,0,0]` 占位，客户端重新序列化时把它们丢了，不是数据损失）✅
- **关键反向结论（恢复入口在哪）**：
  - `ProgressSyncManager::checkProgressSyncEv` @`0x006262d4` **唯一调用者**是
    `tr::OnlineCore::onAuthenticationComplete` @`0x0056c1e4` ⇒ 版本比对只在
    **认证完成**时跑。调用前有三道门：`[0xe20000+0x490]` 的首个 int `== 2`、
    `ProgressSyncManager::switchLocalProgress()` @`0x00625b7c` 返回位 0 为 1、
    且 `MenuzStateMachine::searchPositionFromTop(0) != -1`
    ⇒ **新手教程期间状态栈顶不是常规菜单，比对会被跳过**，必须先走完教程。
  - `ProgressSyncManager::getServerProgressAsync` @`0x006263a4` **唯一调用者**是
    `tr::MenuzStateSyncProgress::onConfirmationDone(int idx, MZ_MENUZ_CONFIRM_RESULT res)`
    @`0x007ab0d4`：只在 `res == 1` 且 **按钮 index == 6** 时 `b #PLT_getServerProgressAsync`
    （index 5 / 7 是别的动作，**index 0x4d2 = 1234 会调 `Player::resetProgress()`，千万别点**）。
    ⇒ 「进度冲突」对话框里**下载云端那一项 = 按钮 6**。
  - 服务器侧对应入口：`GET /__restore?profile=<pid>&ts=<时间戳|latest>`
    （`acct.restore_save`），历史快照用 `GET /__history?profile=<pid>` 列。

---

## 3. 在线功能完善

### 已完成
- **端点骨架**：`server/tf_server.py` 的 `DYNAMIC_EXACT` + 前缀表已覆盖
  `resultservice`（幽灵）、`playerstats/v1/ranking/*`（排行榜）、`pvp_matches/v1/*`、
  `liveevents/v1/weekly_track_system/*`、`gift/v1/*`、`friends/v1/update`、
  `playerprogress/v1/*`、`receiptvalidation/v1/*`、`timeservice`、`targeting`、`pushnotification` 等，未命中的走 `*` 兜底 200。
- **幽灵对手（全链路已通）**：文件格式已解出（前 4 字节 `03 00 00 00`），
  上传走 `userstorage/v2` 的 `contentId` 仓库、下载走
  `userstorage/v2/search/ghost/get_ghost` 与 `resultservice/v1/replaydata/<track>`；
  `server/data/ghosts/` 下同时保留内置 `.bin` 与客户端上传的 `store/<contentId>.bin`。
  细节见下面「缺口 → 幽灵 userstorage 协议」一节的实现说明（该缺口已关闭）。
- **幽灵素材库（2026-10-04 补）**：从原版真机提取 **44 个幽灵 / 30 条赛道 / 79441 字节**
  进 `server/data/ghosts/<赛道id>/`，全部通过 zlib 自检；`.gitignore` 里
  `server/data/ghosts/**/*.bin` 的屏蔽**已解除**（`store/`、`index.json`、`replays.json`、
  `inbox/` 这些运行期数据仍然不入库）。逐条清单见 `server/data/ghosts/INDEX.md`，
  格式与「比赛幽灵怎么被加载」的逆向结论见 `server/data/ghosts/README.md`。
  ★ 关键结论：`GameWorld::initGhostReplay`@`0x4c434c` 是唯一决策点，
  `MissionManager::checkGhostOverride` 返回 false 时比赛**干脆没有幽灵**（走 `GhostReplay::uninit`），
  所以单人跑图看不到对手幽灵是设计而非 bug；幽灵只来自「内存里的在线幽灵」
  「在线任务幽灵」「内置关卡幽灵（datapack 的 `/level/ghost/`）」三类。
- **真钱内购（IAP）完整破解** ✅ 已实机验证（见 §3.1）。
- **广告**：native 侧 `AdInterface::initAndroid()` 短路，Tapjoy/AdMob/Flurry/AdColony 全部不加载；
  logcat 实测广告相关 0 条。服务端遥测也已打桩。
- **反作弊**：`tr::AntiCheating::isValid()` 恒返回 true；`MenuzStateMain::isUserBlackListed()` 恒 0。

### 缺口
- **幽灵的 `userstorage/v2/*` 链已实现**（2026-10-04 补）：
  - **根因**：`POST /public/userstorage/v2/content/ghost` 的响应由
    `tr::OnlineUserStorage::parseJsonResponse` @`0x578a08` 解析，**只认顶层整型键 `contentId`**。
    以前一律回 `{"data": []}` ⇒ 客户端拿不到 id ⇒ 退化成一路 `PUT /content/ghost/0/payload`，
    于是所有幽灵都撞在同一个 id 上、也检索不出来。
  - **上传链**：create 回 `{"contentId": N}` → `PUT .../ghost/N/payload` 存本体 →
    `PUT .../ghost/N` 补 metadata（**该请求体里没有 `track_id`，必须做字段合并**）→
    `POST /public/resultservice/v1/replay_id` 登记。
  - **下载链**：`GET /public/userstorage/v2/search/ghost/get_ghost?track_id=T&players=<csv>&limit=1`
    回 `{"contents":[{"contentId":N,"metadata":{…原样回显…}}]}`（**`metadata` 必须是 JSON 对象**，
    `GhostQueryObject::onQueryCompleted` @`0x508288` 会把它当成员链表继续读，传字符串会读到野指针）；
    客户端再 `GET .../ghost/N/payload` 取本体。另有 `replaydata/<track>` 的匿名幽灵路径。
  - **`replaydata?track_id=<ID>`（查询式）故意保持回 `{"data": []}`**：xref 显示它被
    `OnlineGhostManager::submitGhost` 内部引用，是「服务器上有没有我这条赛道的回放」的
    **上传前检查**——回「有」客户端就不传了。别好心把它改成下发二进制。
  - `players=<csv>` 过滤在单机离线环境下没有意义（库里只有自己），所以
    「按 players 过滤后一个都没命中」时回落到全部候选，否则竞速永远没有对手。
  - 诊断端点 `GET /__ghosts`：幽灵索引 + 仓库文件 + 最近的 `replay_id` 登记。
  - 端到端回归 `tmp/ghost_e2e.py`（复刻真机抓到的调用顺序）12 项断言全绿。
- **排行榜：真实成绩落库 + 主界面总榜聚合**（2026-10-04 重做）
  - 旧实现会给**没跑过的赛道**生成随机记录、时间也对不上，玩家的反馈是
    「时间和记录对不上，然后我没跑的也有记录」。现已删除全部合成数据。
  - 落库规则（`server/tf_server.py` 的 `_record_result`）：按 **(账号, 赛道)** 唯一，
    同一赛道只保留更快的 `drivetime`，更慢的提交直接丢弃；`global_score` 只在客户端真的
    带了这个字段时才写，不再用 `score_value` 伪造。
  - **数据源（2026-10-04 第二次修正）**：真机上跑完图客户端**只发** `POST .../enhancestats/batch_update`
    （一次 15 条），从不发单赛道提交 —— 早先「只信单赛道、忽略 batch_update」的判断是错的，
    正是「跑了一个图但没看到记录」的原因。现在两条路都入库，判据统一为 **`drivetime > 0`**：
    存档 `highscores2` 里没跑过的赛道是 `[track, 0, 256, 0, 0]` 的占位行，`drivetime` 为 0 的一律丢。
  - **存档即真相**：客户端上报进度时（`POST /public/playerprogress/v1/progress`）服务器会顺带
    解析 body 里的 `highscores2` 整表入库，所以榜单永远与玩家真实进度一致，不依赖客户端分批提交。
  - **主界面大榜单**（`/public/playerstats/v1/ranking/global_stats` 与 `global_stats_donkey`）
    改为**实时聚合视图**、不落库：把该账号每一条真实赛道记录汇总成一行
    （`data` = 已完成赛道数、`drivetime` = 各图最佳时间之和、`score_value`/`global_score` = 各图分数之和、
    `upgrades`/`extradata` 按位掩码合并），按 `global_score` 降序排名。
    **一张图都没跑过就不会出现在总榜里。**
  - 新增诊断端点 `GET /__leaderboards`：可直接看到落库的每条赛道记录与总榜聚合结果。
  - 回归测试 `REGRESSION PASS`：批量同步不入库；`track100` 依次提交 30000 / 35000 / 28000 后
    只剩 28000 一条；未提交的 `track999` 保持空榜；总榜聚合出 `tracks=2`。
- 好友位仍是写死的 `GhostRider` / `TangoPro`，但它们没有真实成绩，
  因此不会出现在任何榜单里 —— 这是刻意的（旧版给它们塞假成绩正是报障根源）。
- **限时活动 / 赛季**：`liveevents/v1/*` 未构造真实数据；很多现时内购礼包需要服务器触发。
- **碉堡筹码（2026-10-04 第二次修正，用户 m04710 / m04835）**：
  - 让客户端那个「赢家头像下慢慢填充的圆环」动起来，靠的是 `season.chip_equation_x/y`
    （`PVPManager::getNumChipsTotal` @0x5e1838 = `pow(t,x)*y`；`PVPMatch::getChipProgress`
    @0x5ed8c4 把它的**小数部分**当填充比例，回绕到 0 时 `animateChips` 出一枚）。
    早先发 `0/0` 是错的（圆环永远空着），现在 `0.5/0.5`。
  - `PVPTrack+0x20 = owner_change_time`（真 unix 时间戳）、`PVPTrack+0x24 = bike` —— 早前
    把这两个偏移搞混，才误以为「`+0x20` 同时是车种 ID，所以曲线只能发 0」。
  - `chip_base` 必须是「这一局开始时此人已有的筹码余额」：早前恒 0，导致客户端每局都把
    对手头像下的红筹码清零（用户 m04835：「这一把 AI 的筹码清零了」）。现在人机有
    `chips.bot_start` 一笔初始余额并持久化。
  - **整局结算**：局内新产的筹码进余额之外，赢家还要**夺走输家已有的筹码**
    （`chips.match_loser_keeps_pct`，默认输家保住 50%）。早前只加不减，所以
    「三条赛道都赢了，对面已有的筹码也不会扣除」（用户 m04835）。
    客户端的 `getChipHeritage` @0x5dec48 硬编码 0.5/0.1，只影响赛后文案，转移比例由服务器定。
  - 人机成绩 = 玩家成绩 × `matchmaking.bot_time_margin_pct` + `bot_time_margin_ms`
    （默认 +1.8% + 400ms），`_pvp_bot_time` 强制夹到 ≥ 1.0 —— 用户 m04710：「跑完以后
    幽灵比我快……默认真人赢」。
- **碉堡 / 午夜杯**：未做。

### 3.1 真钱内购破解结论（重要，别再走弯路）
- ❌ **靠服务器回成功响应不行**：`StoreManager::onNetworkDataReceived` @`0x0057b0cc` 的
  `cmd 0x17` 分支（`0x57b1a4`）**只是再调一次 `mz::IAPManager::purchase()`**，仍然回到 Google Play。
- ❌ **改道本地货币路径也不行**：真钱礼包的 `getPriceHard/getPriceSoft/getPriceChips` 全是 0
  （价格来自 Google Play 商品表），改道过去只会静默返回 —— 表现为"点了没反应"。
- ✅ **正确做法**：`StoreManager::onPurchaseComplete(IAPItemInfo*, IAPReceipt*)` @`0x00579940`
  （3296 字节）无条件发奖、全程不校验收据、不联网。它是 `IAPManagerListener` vtable 的**槽 0**；
  失败/取消走槽 `0x08`/`0x10`。把这两个入口改成尾调用 `onPurchaseComplete`（收据传 NULL，
  函数内 `0x579ad0`/`0x579e90` 两处有 `cbz x20` 判空）：

  | 补丁 id | 符号 | 字节 |
  | --- | --- | --- |
  | `iap-failed-redirects-to-complete` | `_ZN2tr12StoreManager16onPurchaseFailedEiPN2mz11IAPItemInfoE` | `f3 0f 1e f8 fd 7b 01 a9 fd 43 00 91` → `e1 03 02 aa e2 03 1f aa e4 fb ff 17` |
  | `iap-cancel-redirects-to-complete` | `_ZN2tr12StoreManager16onPurchaseCancelEPN2mz11IAPItemInfoE` | `f3 0f 1e f8 fd 7b 01 a9` → `e2 03 1f aa ce fb ff 17` |

- 实机结果：商店 → 宝石 → 「宝石城堡 5 800 宝石 11.00 $」→ 弹出「谢谢你的购买！ 5 800 宝石」，
  HUD 宝石 `27 475 → 33 275`。全程无服务器请求。

---

## 4. WebUI 管理界面 —— 🟡 已起头（注册页 + 管理 API）

### 已有基础
服务器已有一批只读内省端点（`tf_server.py` 的 `_introspect`）：

```
/__ping  /__log  /__accounts  /__devices  /__sessions
/__saves  /__save?profile=<pid>  /__history?profile=<pid>&ts=<ts|latest>
/__restore?profile=<pid>&ts=<ts|latest>  /__ghosts
```

### 建议实现路径
1. 新增 `server/tf_webui.py`（纯标准库 `http.server`，或 Flask 单文件），复用 `tflocal_accounts` 的读写函数。
2. 页面：账号列表 / 新建账号 / 改口令 / 删除；存档列表 + 一键回滚；幽灵库浏览与替换；
   全局开关（`Anticheating_Enabled`、活动时间、商品表下发）。
3. 与 `tf_server.py` 同进程不同端口（例如 8001），或用 `/admin` 前缀挂在同端口。

### ★ 决策记录：这些运营参数交给 WebUI 管（用户 m04835，2026-10-04）

用户 m04835（verbatim）：「产出筹码速度和AI控制可以留给WebUI控制，赛季奖励可以在WebUI设置
(然后可以保存模板)，这些决策记录在案。」

所以**不把这些值写死在代码里**，它们都已经（或将）落到 `server/data/tf_config.json`，
服务器每次请求热读，改完即时生效、不需要重启：

| 需求 | 配置路径 | 当前默认 |
| --- | --- | --- |
| 筹码产出速度（局内曲线） | `season.chip_equation_x` / `season.chip_equation_y` | `0.5` / `0.5` |
| 筹码产出速度（账号级赛道产线） | `chips.per_track_seconds` / `chips.max` | `3600` 秒 / 不限 |
| 筹码结算 | `chips.match_loser_keeps_pct` / `chips.bot_start` | 输家保住 `50`% / 人机初始 `500` |
| AI 控制（人机成绩） | `matchmaking.bot_time_margin_pct` / `bot_time_margin_ms` | `1.018` / `400` |
| AI 控制（要不要人机、等多久、赛道池） | `matchmaking.enabled` / `bot_wait_seconds` / `candidate_tracks` / `track_ids` | `true` / `60` / 24 条 / 空=随机 |
| 赛季奖励 | `season.rewards` | 17 条 `{rank,item_id,amount}` |

- **赛季奖励要支持保存模板**：`season.rewards` 的契约来自 `parseSeasonData` @0x4fe4f4
  （`[{"rank":int,"item_id":int,"amount":int}, …]`，同 rank 可多对）；WebUI 存成命名模板
  （建议 `server/data/season_templates.json`），支持「存为模板 / 套用 / 导入导出 JSON」。
- 这些全是**数值型运营参数**，形状（键名、数组结构）不变，所以改错最多是显示不好看，
  **不会让客户端崩**（客户端 JSON 解析器不做类型检查，怕的是类型/形状变化，见 §3）。
- `season.star_array`（25 项星章表）也属于同一类，一起交给 WebUI，但**长度必须 ≤ 26**。

---

## 5. 一键开服打包成 exe —— 未开始

### 建议实现路径
1. `server/launch.py`：选端口、生成默认 `tf_server.txt` 内容、起服务器、打印局域网 IP 与配置说明。
2. `pyinstaller --onefile --add-data "rules.json;." --add-data "data;data" server/launch.py`。
3. 首次运行自动创建 `server/data/`，并提示把 IP 填进手机的
   `/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt`。
4. 注意：局域网部署要求手机能直连 PC（见 §1，Windows 防火墙需放行 Python 入站，已验证有放行规则）。

---

## 6. 设备侧：游戏数据重定向到 `/sdcard/Android/data/<pkg>` —— ⛔ 已放弃并回滚

> 用户要求（2026-10-04，m03625）：**「现在游戏所有数据都在 `/data/data/包名`，我们能不能让他重定向到 `/sdcard/Android/data/包名`。」**
> 目的：存档 / 幽灵 / 下载内容包放到用户可访问的共享目录，方便备份、换机、用文件管理器直接改。

**结论：技术上做得到（绑定挂载 + `adb reboot` 后自动恢复都实测通过），但它必须依赖 root**
（KernelSU 的 `post-fs-data.d` / `service.d` 开机钩子 + `mount --bind`），**不适合作为离线包的交付形态**。
用户 2026-10-04 决定放弃（m04281：「如果重定向依靠root，那没必要了。把存档恢复即可。」），
**设备侧已完整回滚，`tools/tf_redirect_mount.sh` / `tools/tf_redirect_unmount.sh` 仅作技术参考保留。**

### 回滚记录（2026-10-04 已完成，游戏正常）

```sh
sh tools/tf_redirect_unmount.sh     # umount 3 处 + 把游戏数据搬回 /data/data/$PKG/files
rm -f /data/adb/post-fs-data.d/tf_files_bind.sh /data/adb/service.d/tf_files_bind.sh
```

- `mv` 遇到**已存在的目录**（`.Fabric`）会报 `bad '.Fabric': Directory not empty` 而跳过 ⇒ 要手工
  `cp -rn $SRC/.Fabric/. $DST/.Fabric/ && rm -rf $SRC/.Fabric` 合并（两边的 crashlytics 日志取并集）。
- **搬回来的文件 SELinux 标签会留在 `media_rw_data_file:s0`**：`restorecon -R` 对这些路径
  **找不到规则**（干跑 `restorecon -Rnv` 无任何输出），必须手工
  `chcon -R u:object_r:app_data_file:s0:c512,c768 /data/data/$PKG/files`
  （目录本身会自动是 `app_data_file`，只有搬过去的老文件需要重标）。
- 回滚后复核：`/proc/mounts` 已无 trialsfrontier 条目、私有目录 135 项、
  属主 `u0_a296 u0_a296`（10296:10296）、标签全部 `app_data_file:s0:c512,c768`；
  游戏启动正常（进程存活、**无 `avc: denied`、无崩溃**），村庄 HUD 完整
  （456/456 汽油、**16,748,033** 金币、**9,066,302** 钻石、13 星）。
- 注：私有目录条目数 136 → 135，少的是游戏自己会删/重建的临时文件
  （`AppEventsLogger.persistedevents`、`screenshot.jpg`），非游戏数据。

### 方案（技术参考）：ext4 绑定挂载

**方案：ext4 绑定挂载**（**不是**软链接）

```sh
mount --bind /data/media/0/Android/data/$PKG/files /data/data/$PKG/files
```

- 关掉游戏 → `mkdir -p /data/data/$PKG/files` → `mount --bind <底层 ext4 路径> <私有目录>`
  → 游戏数据落在 `/data/media/0/Android/data/$PKG/files`，同时**照旧能在 `/sdcard/Android/data/$PKG/files` 看到和编辑**（同一批 inode）。
- 一次性/手工：`sh tools/tf_redirect_mount.sh`；回滚：`sh tools/tf_redirect_unmount.sh`（会先 `am force-stop`，再把外部目录里的游戏数据搬回私有目录）。
- 幂等：已挂载时再执行直接 `exit 0`，可安全重复调用。

### ★ 为什么必须绑 ext4 路径，而不是绑 `/sdcard/...`
- `/sdcard/Android/data` 是 **sdcardfs** 视图（`/data/media on /mnt/user/0/emulated/0/Android/data type sdcardfs`），
  而 `/data/media/0/Android/data/$PKG` 本身是**纯 ext4**（`/dev/block/sda21`，标签 `u:object_r:media_rw_data_file:s0`）。
- 绑底层 ext4 ⇒ 游戏拿到**正常 ext4 语义**；绑 sdcardfs ⇒ 会踩到 sdcardfs 的路径/权限怪行为。

### ⛔ 走过的弯路：整目录软链接（**已否决，别再试**）
第一版把 `/data/data/$PKG/files` 换成 `ln -s /sdcard/Android/data/$PKG/files`。结果**游戏一进 `CustomNativeActivity` 就 SIGSEGV，2/2 复现**，回滚后立刻恢复。tombstone：

```
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0    Cause: null pointer dereference
#00 libc.so (__strcmp_aarch64+32)
#01/#02 libTrialsGo.so 0x8b4c18 / 0x8b4dcc
#03 mz::IAPManagerAndroid::queryProducts(...)+500   = 0x889008
#04 mz::IAPManager::queryProducts(...)+124          = 0x88a314
#05 tr::StoreManager::reinit()+396                  = 0x579180
#06 tr::StoreManager::init()+40                     = 0x578fcc
#07 tr::GlobalData::init(mz::InputPointerState*)+1216 = 0x4d0a5c
#08 tr::MainApp::init()+112                         = 0x8436a0
```

根因（`tmp/disasm.py` 实证）：`IAPManager_CallInit` 包装函数在
`0x8b4da8 cbz x8, 0x8b4e24` / `0x8b4dac cbz x20, 0x8b4e44` 处发现 **portal 名为 NULL** 时，
`0x8b4e44` 只打了一条警告（`IAPManager_CallInit: IAP called on an unvailable store. Please check your db file` @`0xbac6dd`）
**然后 `0x8b4e60 b #0x8b4db0` 又跳回去继续，把 NULL 传给 `IAPManager_CallInit`** →
`strcmp("Google Play", NULL)` 崩在第 0 页。**这是游戏自身的上游 bug**；
真正的诱因是软链接把 `files/` 的路径解析重定向到了 sdcardfs，导致它读不到拿 portal 名所需的那份 db/配置。

> 教训：**在这个游戏上改动 `files/` 的落盘位置，唯一可行的是绑定挂载到真正的 ext4 目录。**
> 任何把访问重定向到 sdcardfs 的方案（软链接、bind 到 `/sdcard/...`）都会让启动段错误。

### 持久化：KernelSU 开机钩子（重启实测通过；**回滚时已删除**）
- 设备有 `/data/adb/service.d/` 与 `/data/adb/modules/`，但**原本没有 `/data/adb/post-fs-data.d/`**，已新建。
- `tf_files_bind.sh` 同时装到 **`/data/adb/post-fs-data.d/tf_files_bind.sh`** 与 **`/data/adb/service.d/tf_files_bind.sh`**（`chmod 0755`），
  内容即幂等调用 `tools/tf_redirect_mount.sh`。
- **`adb reboot` 实测**：重启后 `uptime` = `up 1 min`、`sys.boot_completed=1`，
  `/proc/mounts` 里 3 条绑定（`/data/data/...`、`/data/user/0/...`、`/data_mirror/data_ce/null/0/...`）仍在，
  `/data/data/$PKG/files` 仍是 136 项 ⇒ **无需任何人工干预即自动恢复**。

### SELinux 结论（Enforcing 下也成立）
- 私有目录标签 `u:object_r:app_data_file:s0:c512,c768`；外部目录及其内容 `u:object_r:media_rw_data_file:s0`（底层）/ `sdcardfs:s0`（`/sdcard` 视图）。
- 绑定挂载后 `ls -Z` 显示目录是 `media_rw_data_file:s0`，里面**游戏自己新建**的文件是 `app_data_file:s0:c512,c768`。
- logcat 里**没有任何涉及 `media_rw_data_file` 的 `avc: denied`** ⇒ `untrusted_app` 读写 `media_rw_data_file` 是被允许的。
- 目录属主 `u0_a296 sdcard_rw`（10296:1015），与重定向前一致。

### 重定向期间的验证证据（已回滚，仅作记录）
- 重定向后游戏正常启动（进程存活），并在 `/sdcard/Android/data/$PKG/files` 里看到**新的写入**：
  `player.bin`（4015 B）、`pvp_ghost_1_1041_328389155.bin`（1888 B）。
  后者**顺带真机证实了 §3 的「PVP 对手幽灵下发」真的落地了**。

---

## 附：当前交付物

| 路径 | 说明 |
| --- | --- |
| `dist/TrialsFrontier-offline.apk` | 完整离线版 APK（m16），26 906 224 字节，SHA-256 `EA77B0B420BF790BB626189F74A3BC64BB384607C2A273F36ADBF558FD8EAB53` |
| `dist/patcher/` | 面向用户自己原版 APK 的补丁工具链（含 `tfpatcher.py`、`patch_native.py` 等） |
| `dist/server/` | 本地服务器（`tf_server.py`、`tflocal_accounts.py`、`rules.json`、`data/ghosts/`） |
| `dist/README.md` | 完整交付说明（526 行，含内购破解章节） |
| `tools/patch_native.py` | 10 条 native 补丁，`--dry-run` 对原版 `libTrialsGo.so` 自检全 `[OK]` |
| `tools/tf_redirect_mount.sh` | 把 `files/` 绑定挂载到 `/sdcard/Android/data/<pkg>/files`（幂等，见 §6） |
| `tools/tf_redirect_unmount.sh` | 卸载绑定并把游戏数据搬回私有目录（回滚用，见 §6） |
| `tmp/build/tf-m8-release-backup.apk` | 上一版发布基线备份（无 IAP 补丁） |

### 构建流水线
```
pwsh -File tools\make_apk.ps1 -Name <名字> [-NativeDir tmp\m13] [-Manifest tmp\m4\AndroidManifest.xml]
```
内部：`python tools\build_apk.py --base tmp\extract\aUiMEPVatQ.apk --out ... --replace lib/arm64-v8a/*.so=... --drop-prefix lib/armeabi-v7a/`
→ `zipalign -p -f 4` → `apksigner sign --v1 --v2 --v3`（keystore `work/trials-frontier/keystore/trials.jks`，alias `trials`）。

> ⚠️ **基线与清单两个坑**：native 补丁必须基于 `tmp\m8`（含 `DLContentManager::isDLReady()`），
> 基于 `tmp\m2` 会丢掉「下载暂停」修复；`make_apk.ps1` 必须传 `-Manifest tmp\m4\AndroidManifest.xml`
> （targetSdk 27），否则明文 HTTP 被禁、Java 侧 DLC/内购校验报 `Cleartext HTTP traffic ... not permitted`。
