# ROADMAP 进度与任务规划

> 对应根目录 [`ROADMAP.md`](ROADMAP.md)。本文档记录每一条的**当前完成度、证据、缺口、下一步动作**。
> 最后更新：2026-10-05（真机 `<设备序列号>` / 小米 8 / LineageOS 22.2 `ursa` ＋ 模拟器 `emulator-5554` / Android 14 / x86_64）

---

## 总览

| # | ROADMAP 条目 | 状态 | 完成度 |
| --- | --- | --- | --- |
| 1 | 修复 APK 启动 BUG（联网闪退） | ✅ **已修复并实机验证（m14/m15）** | 100% |
| 2 | 修复账号管理（注册 / 登录分离） | ✅ **已实现并 curl 实测（含内置注册页）** | 85% |
| 2b | VIP 下发（买了 VIP 就激活 VIP 事件） | ✅ **已实机验证（m16）** | 100% |
| 3 | 在线功能完善（碉堡 / 午夜杯 / 限时活动 / 排行榜 / 幽灵对手） | 🟡 **部分实现；本轮补齐碉堡奖励/结赛及基础货币链，21项隔离回归通过，待真机到账验证** | 不再沿用旧95%估计 |
| 4 | WebUI 管理界面 | 🟡 **五屏已交付（`/__admin`：登录／账号／存档／下发＋午夜杯运营屏＋碉堡运营屏，CN+EN，160 项后台回归 + headless 冒烟）；概览等两屏待做** | 65% |
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

### 2026-10-05 奖励/结算复核（优先于下方历史结论）

**“端点200、界面能进、比赛不崩”不等于奖励到账。** 旧95%及“剩余不是服务端缺口”的说法撤回；下方记录保留作历史，不作本轮完成依据。

本轮修复于 [服务端](<server/tf_server.py>) 和 [运营配置](<server/data/tf_config.json>)：
- 补实际 `POST /pvp_matches/v1/close`，返回胜者与换主次数；筹码/段位只结算一次，已领取对局不再重新展示。
- `increase_rewards` 由丢弃币值改成共享奖池增量累计；刷新/重启保留奖池与reward_data，拒绝无比赛凭据增币及重复经济增量。
- 筹码商店按真实 `use_chips` 扣款；新增基础价金票购买，免费票按对局在 `start_race` 消耗，不再匹配即扣票。
- 6小时对局不再30分钟消失、不再跑完三图就提前结算；对局/成绩/奖池/余额/领取回执原子持久化，失败不假报成功。
- 赛季期限固定、奖励wire改为26档嵌套结构，特殊奖用RewardID；段位0确为Legend，修正连胜两星及掉星保护。
- **金币/宝石由客户端成功回调发放**，服务端不另改存档加第二份。

验证：`python -m unittest discover -s tests -v`，[21项回归](<tests/test_pvp_economy.py>)通过（含临时回环HTTP、重启、重复领取、并发支出和模拟磁盘失败）。**本轮没有真机复验、没有重启现有服务器、没有重打APK或更新发布包。**

未闭环：真机实际入账/重登同步；套装折扣及商店缓存价的金票购买（当前拒绝非基价）；无操作ID的购物重放；多活跃对局、跨季未结局与历史数值；午夜杯真实次数/冷却与领奖、礼物收发和活动礼包业务。原生调用点与限制见 [研究笔记](<work/trials-frontier/notes/pvp-reward-contract.md>)、[修复报告](<work/trials-frontier/notes/2026-10-05_pvp-economy-report.md>)。

### 历史已完成记录（不代表完整奖励/经济链已实现）
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
- **内置幽灵已折成「对手榜」（2026-10-05 落地）**：见下面 §3.3。修好了
  「库里有 44 个幽灵、全球榜上却只有玩家自己一行、点进去没有对手可挑战」。

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
- **好友链（`friends`）✅ 2026-10-05 已落地**：
  - 端点族归 `tr::OnlineFriends`（`POST /public/friends/v1/update`，cmd 0x65）与
    `tr::OnlineUbiservices`（`GET /v2/profiles/me/friends` cmd 0x50、
    `GET /v1/profiles?idOnPlatform=` cmd 0x4b）。
  - **`friends/v1/update` 必须原样回显请求里的 `uplay` id 数组**（`h_friends_update`）。
    客户端遍历**本地**好友表的每个 pid 去回包里比对（`0x51d844 json_strcmp([x21+0x28], x9+0x81)`），
    **未匹配就清零该条目标志位**（`0x51d864 str wzr,[x9,#0xac]`），收尾 `0x51da30 tbnz #3`
    判定失败 ⇒ **好友被删**。所以原来落 `*` 兜底的 `{"data": []}` 等于回 `{"uplay":[]}`，
    会把好友列表清空。
  - `GET /v2/profiles/me/friends` 由 `rules.json:98` 的桩提供（`GhostRider` / `TangoPro`）。
    这个桩的**形状是对的**，但有三个隐含硬约束（已写进 `rules.json` 的 `//friends2~4` 注释）：
    ① cmd 0x50 分支 `0x5182a8` **没有 `cbz x21`**，空 body / 非法 JSON 会让 NULL 进解析器，
    `0x51cf18 ldr x8,[x1,#0x10]` 直接读地址 `0x10` ⇒ **SIGSEGV**；`{}` 同样崩
    （`0x51cf1c` 读 NULL+0x10，`cbz x28`@0x51cf20 只保护 x28）。
    ② 不检查 JSON 类型标签 `+0x30`，`pid`/`nameOnPlatform`/`state` 必须是**字符串**，否则进 `strlen` 崩。
    ③ **`pid` 必须排在 `nameOnPlatform` 之前**，否则 `strcmp(buf,"0")==0` 整条被静默跳过。
    另：`pid` ≥ 43 字节会让 `addFriend` 的 `strcpy(x20+0x81,key)` 堆溢出。
  - ⚠ 部署要点：`/v2/profiles/me/friends` 与 `/v1/profiles` 的 base 是**硬编码字面量**
    `https://public-ubiservices.ubi.com` @`0xb85565`，**不走** `[OnlineCore+0x28]`，
    只能靠 DNS/hosts 劫持接管；只有 `friends/v1/update` 走可变的私服地址。两者不是同一 host。
  - 好友位仍没有真实成绩，因此不会出现在任何榜单里 —— 这是刻意的
    （旧版给它们塞假成绩正是报障根源）。
  - 完整反汇编报告：`work/trials-frontier/notes/friends-v1.md`（745 行）。
- **「现时内购礼包」/ targeting ✅ 2026-10-05 已落地**（ROADMAP 第 3 条的最后一条支线）：
  - **`GET /public/targeting/v1/condition_items?type=bundles`（cmd 0x85）就是礼包开关。**
    解析器 `parseConfigData`@`0x515dc8`：**根必须是 JSON 数组**（`0x515e34 cmp w8,#2`）、
    元素**必须是整数**（`0x515e58 cmp w8,#4`，非整数静默跳过）；这份整数列表就是
    `OnlineProfileEligibilityManager+0x10` 里的**礼包 id 白名单**，bundle id 是**单字节（0..255）**。
    消费方 `ProfileEligibilityManager::isBundleEligible`@`0x5955e8`，唯一调用者是
    `StoreItem::unlockConditionsOK`@`0x609a20` ⇒ `OfferManager::pushPopup`@`0x5ff750`（礼包弹窗）。
    以前落 `*` 兜底的 `{"data": []}` 是个 **JSON 对象**，根类型判等直接失败
    ⇒ 白名单恒为空 ⇒ **礼包功能整体是死的（且静默无错）**。现 `h_targeting_bundle_config`
    回 `[0..255]`（全开）；回 `[]` 是最小安全值。
  - `GET`/`POST /public/targeting/v1/configuration`（两者共用 cmd 0x49）
    现由 `h_targeting_configuration` 回 **`{}`** —— 这是文档化的安全最小值：
    `root->first_child == NULL` 走 `0x4eef3c` 默认值路径（`w27 = -1`），
    而 `0x4eefd0 cmn w27,#1; b.eq` 会**跳过整个配置包下载**，正是离线想要的。
  - ⚠ 永远**不要**发 `metadata`：`downloadurl` 会让客户端对任意绝对 URL 发 GET 并
    `SaveFile::writeSystemFile` 落盘（`0x4ef250`），随后 `GlobalData::onDataPacksUpdated()`
    —— 既污染本地状态又指向真实 S3。
  - ⚠ 唯一真实崩溃面在别处：`0x4eed1c str w9,[x8,#0x10]`（写 `login.access`）
    **未判 `OnlineCore::m_authentication+0x28` 是否为 NULL**。所以本端点暂不返回 `login`。
  - **本次改动没有引入崩溃面**：`tr::json_strcmp`@`0x569138`（仅 20 字节）对 NULL 安全
    （`cbz x0/x1 → mov w0,#-1; ret`），两个解析器共 10 处显式 `cbz`/类型检查 ——
    这与本项目 `reward_config` 那个「缺 key 就无条件解引用」的 bug 性质不同。
  - 商店商品表其实来自**另一个端点** `receiptvalidation/v1/product/configuration`（cmd 0x19），
    但 `limited_purchases` 表从**两个端点任一**都会被同一次
    `StoreManager::parseStoreConfiguration`@`0x57b30c` 解析（元素结构 `ServerStoreItemData` 步长 **0x20**）。
  - ✅ **真机已命中**：2026-10-05 00:30:25 三个端点全部走新处理器
    （`condition_items` → `[0,1,2,…]`、`configuration` GET/POST → `{}`），游戏无崩溃。
  - 完整反汇编报告：`work/trials-frontier/notes/targeting-v1.md`（770 行）。
  - **遗留未闭环**：bundle id ↔ 具体礼包的映射表**不在 `.so` 里**
    （`StoreManager+0xd0` 只存 `product_id` 字符串），必须从游戏数据包或运行时 dump 得到；
    应急做法是回 `[0..255]` 全量。另外 `limited_purchases` 目前仍是 `[]` —— 那是真钱 IAP 商品，
    `product_id` 必须匹配客户端本地商品表才有意义，尚无可靠来源。
- **礼物链（`gift/v1/*`）✅ 2026-10-05 已落地**：
  - 端点族属 `tr::OnlineGifting`（网络层）/ `tr::GiftingManager`（UI），共 6 个 op：
    GET `get_gifts`(0x40) / `gifts`(0x42) / `claim?type=`(0x41)，
    POST `give_golden_ticket`(0x3e) / `send_gifts`(0x3f) / `ad_reward`(0x43)。
  - **两个必须特判的地方**（都已实现于 `h_gift`）：
    1. `get_gifts` 的响应**根必须是 JSON 数组** —— `parseGiftArray`@0x51f784 第一条指令
       就是 `ldr w8,[x1,#0x30]; cmp w8,#2; b.ne`（type tag 2 = 数组）。
       以前回 `{"data": []}` 是对象 ⇒ 第一跳收工 ⇒ 永远「没有礼物」，且**静默无错**。
    2. `gifts` 是**唯一**能写 `OnlineGifting+0x28`（server_time）的响应，
       而 `GiftingManager::isUptoDate()` 读的正是它 ⇒ 缺了它，
       `MenuzStateWarRoom::updateGiftingIndicator`@0x73999c 的
       `[m_appTicker] % 300 == 0`（300 帧 @56.4fps ≈ **5.32 秒**）永远为真，
       战争房间无限重发 `get_gifts`（实测 **6 小时 581 次**，日志里最大的一条噪声源）。
  - POST 与 `claim` 的响应体客户端**一个字节都不解析**，回 200 即可。
  - 完整反汇编报告：`work/trials-frontier/notes/gift-v1.md`。
  - ✅ **真机复验通过（2026-10-05 00:22 重启后）**，三步证据链：
    1. **`gifts`(0x42) 只有一个调用点** = `OnlineCore::onAuthenticationComplete` @`0x56c2b0`
       —— 即**每次登录只发一次**。所以轮询修复**必须重启游戏才生效**，改完服务端不重启客户端是看不出差别的。
    2. **解析器同时写两个字段**（`parseJsonResponse` 0x42 分支，逐指令核对）：
       ```
       0x51f638  add  x20, x20, #0x95c      ; x20 = 0xb8695c "server_time"
       0x51f644  bl   json_strcmp
       0x51f648  cbz  w0, #0x51f658         ; 命中 → 0x51f658
       0x51f64c  ldr  x21, [x21, #8]        ; 否则找下一个兄弟
       0x51f654  b    #0x51f668             ; 没找到也落到 0x51f668
       0x51f658  ldr  w8, [x21, #0x28]      ; 命中：取整数值
       0x51f65c  str  w8, [x19, #0x28]      ; this->server_time = w8
       0x51f668  bl   mt::time::Time::getTimeOfDay()
       0x51f66c  str  w0, [x19, #0x2c]      ; this->localTime —— 两条路径都会写
       ```
       ⇒ `isUptoDate()` 的 `w0 = (w9 != 0) && (w8 != 0)`（`/0x59b020`）里
       `+0x2c` 恒非零、`+0x28` 以前恒为零 ⇒ **修复前必然 false**；现在 `+0x28` 有值 ⇒ **true**。
    3. **实测**：00:22:28 登录拿到 `{"server_time": 1791130948, ...}`；00:24:55 进硲堡/战争房间
       （`pvp_matches/v1/matches` + `/players` 同时出现，`MenuzStateWarRoom::transitionEnter`
       @`0x73a44c` 触发一次 `requestUpdate` → 1 次 `get_gifts`）；**随后 172 秒零 `get_gifts`**
       （00:24:55 → 00:27:47），期间 00:26:59 / 00:27:07 仍在房间内发 `pvp_matches`。
       **修复前同样时长 = 约 32 次**（5.3 秒一次）。⇒ 轮询已消除，只剩进房间那一次。
  - **定位方法（可复用）**：5.32 秒轮询只发生在**硲堡/战争房间界面**。用
    `server-log.jsonl` 找 `get_gifts` 的「间隔 < 8 秒的连发段」（本次 14 段全部落在
    10-04 21:00–23:15），再看同一时间窗内的其它请求 —— 441 次 `pvp_matches` 与 524 次
    `get_gifts` 完全重叠，即可确认是 `MenuzStateWarRoom` 在刷。
- **排行榜 `global_stats` 400 已修（2026-10-05）**：客户端除按赛道上报外，还会把自己的
  **总榜行** `POST` 到 `/public/resultservice/v1/enhancestats/global_stats`。该 body 与
  `batch_update` 同形，但 `stats` 里**没有 `track`**（只有
  `data/global_score/drivetime/upgrades/submittime`），于是掉进 `h_result_stats` 的
  `track[0-9]+` 正则 ⇒ **400 invalid-track（实测 16 次 100% 失败）**。
  现在 `endpoint in GLOBAL_LEADERBOARDS` 直接回 200 并丢弃：总榜在本服务器是
  **实时聚合视图**（`_aggregate_global_entries`），本来就无处可存，丢弃是安全的。
  - ✅ **真机复验通过（2026-10-05 00:15:56 重启后）**：修复前那次 `end_race`（00:11:19）
    触发了一串**每 11 秒一次的重试风暴** —— 00:11:19 / 00:11:30 / 00:11:41 / 00:11:52 /
    00:12:03 / 00:12:14 / 00:12:25 / 00:12:36 / 00:12:47 / 00:12:58 / 00:13:09 共 **11 次全 400**，
    直到玩家手动离开；第二场 00:14:21 `end_race` 后又是 10 次全 400。重启用 200 之后
    **同一个 11 秒风暴立刻消失**，且 `global_stats_donkey`、`track1041` 仍 200（未回归）。
    ⇒ 这个 400 不是无害噪音，它每场比赛都白烧 10~11 次请求 + 一次 11 秒的重试循环。
- **历史判断（已被本节顶部复核更正）**：碉堡 / 午夜杯主链已通；当时误认为只剩真机复验、没有服务端缺口。实际上 `/close`、奖池累计和扣费等仍缺，不能以此段宣称经济功能完成。
  - ✅ **真机整链复验通过（2026-10-05 00:10:47 起）**：修复后玩家连跑两场，
    `GET config/0`(00:09:52 / 00:10:37) → `POST start_race`(00:10:47) → `POST end_race`(00:11:19)
    → `POST start_race`(00:13:47) → `POST end_race`(00:14:21) 全部 200，
    随后 `POST /public/userstorage/v2/content/ghost` + `PUT .../ghost/58(/payload)`(00:16:05)
    成功上传幽灵。全程 logcat **零 `libTrialsGo` / 零 SIGSEGV**（见下面「midnight cup 验证」）。
- **⚠ 设备侧无关噪音，别再当成本项目的 bug**：这台 Xiaomi（sdm845）的指纹 HAL
  `/vendor/bin/hw/android.hardware.biometrics.fingerprint-service.xiaomi` **每 ~6.6 秒**
  就 `abort()` 一次（栈：`synaFpDeviceOpen` → `CSynaFpImpl::DevUninit` → `palMutexFree` →
  `HandleUsingDestroyedMutex` → `__fortify_fatal`），整夜不停，与本游戏毫无关系。
  **后果**：logcat 抓取必须用 `*:F` 而不是 `*:E`，否则这条噪音会把有用日志冲掉。
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
### 3.2 午夜杯 / 周挑战（`weekly_track_system`）—— 主链已通

服务端实现（`server/tf_server.py`，全部有反汇编契约注释）：

| 端点 | 处理器 | 响应契约 |
| --- | --- | --- |
| `basic_info`（GET + POST） | `h_liveevents_basic_info` | 入口；POST 变体还顺带覆盖 `postLastWeekData`（cmd 0x7f，同一 URL，见 0x503800 `add x2,x2,#0x16c`） |
| `config/<n>`（GET + POST） | `h_liveevents_config` | `parseChallengeConfiguration` @0x5055f0 |
| `reward_config/<n>` | `h_liveevents_reward_config` | `parseRewardsSlot` @0x505d28 |
| `find_opponent` | `h_liveevents_find_opponent` | `{"opponent","replay_id"}` |
| `start_race`/`end_race`/`skip_cooldown`/`refill_retry_count` | `h_liveevents_accept` | 响应 **0 字节被解析**，回 200 即可 |

**★ bike_id 必须 ≥ 1（真机崩溃根因，2026-10-05 修复）**
玩家点「进入场地」**必崩**，logcat：
```
F/libc: Fatal signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0xb0
#00 pc 0x6cbf20 libTrialsGo.so (tr::MenuzComponentWeeklyChallengeBike::setBike(int, int)+60)
#01 pc 0x7b454c libTrialsGo.so (tr::MenuzStateWeeklyChallenge::loadIntroState()+944)
```
机制（逐条对齐）：`setBike` @0x6cbee4 把服务端给的 bike_id 直接喂给
`UpgradeManager::getBike(unsigned short)` @0x62ac2c，后者遍历由 `parseBikeData` @0x62a190
从 `/conf/bikes.txt` 建出的车表（**19 台、1..19 连续、无 0**），查不到就 `mov x0,xzr; ret`；
调用方紧接着 `0x6cbf20 ldr w8,[x0,#0xb0]` ⇒ 空指针，**fault addr 0xb0 与崩溃地址完全吻合**。
佐证：`getBikeIndexByID` @0x62a12c = `sub w0,w1,#1`（车号 1-based）。
**修法**：`server/tf_server.py` 的 `h_liveevents_config` 里 `"bike_id": 0` → **`1`**
（1 是碉堡 PVP 链早已在用的值，且 `tf_server.py:2119` 本就有 `bike < 1 ⇒ 1` 护栏）。
⚠ 客户端**把周挑战 config 缓存在本地**（崩溃发生在 `config/0` 拉取之前的 00:04:45，
而拉到 config 是 00:04:52），所以改服务端后**必须重新拉一次 config** 才生效。

**✅ 真机验证（2026-10-05 00:10:47，修复生效后重跑）**
- 服务端实测 `GET /public/liveevents/v1/weekly_track_system/config/0` 返回
  `..."challenge_settings": {"track_id": 1041, "bike_id": 1, ...}` —— 新增的两个字段
  `week_index: 2961` 与 `track_id: 1041` 也在（`find_opponent` / 排行榜按此对齐）。
- 真机请求链（全部 200，**中间没有任何一次崩溃**）：
  `config/0`(00:09:52) → `config/0`(00:10:37) → `start_race`(00:10:47) → `end_race`(00:11:19)
  → `start_race`(00:13:47) → `end_race`(00:14:21) → `replaydata` + `ghost` 上传(00:16:05)。
- **`logcat-mdnt.txt` 全文 grep `TrialsGo|alsfrontier|SIGSEGV` = 0 命中**；
  该文件里唯一的 `F/DEBUG` tombstone 全部来自指纹 HAL（见上面的噪音条）。
  ⇒ **「进入场地」崩溃已彻底修复，两场完整比赛 + 幽灵上传走通。**

**其余要点**
- `reward_config` 的 `reward` **必须是槽对象的第一个成员**（`parseRewardsSlot` 拿
  first_child 的 key 去 `strcmp("reward")`），且**槽对象只给一个成员会崩**：
  0x505d7c 无条件 `ldr x25,[x8,#0x10]`（x8 = first_child->next）⇒ 每个槽固定给两个等长数组。
  奖励本身由**客户端**按 `Reward_<n>` 查本地 `/conf/wts_rewards.txt` 发放，服务端不下发物品。
- 周赛任务的真正驱动是 `MissionDB` 里写死的 3 个任务 451/452/453
  （`setUpWeeklyChallengeMissionTiming` @0x5c45f0 用午夜杯时间窗改写其 type-6 条件），
  **纯客户端逻辑**，所以 `challenge_settings.task` 保持空数组是对的。
- 诊断：`GET /__leaderboards`、服务器 stdout 的 `[liveevent]` 行。

### 3.3 幽灵对手榜（2026-10-05 落地）—— 「榜上只有我自己」
> 用户反馈（原话）：「我们拿了这么多幽灵数据，但是全球排行榜上一个没有。我也无法挑战自己，因为无法点击开始」

**根因**：排行榜是按 `player`(pid) 建行的，而幽灵库里的条目 owner 是 onlineId 哈希，
两者之间**没有任何桥**。`server/data/leaderboards.json` 里 36 个榜每个只有 1 行
（全是玩家 `<player-profile-id>`），所以 `playerCount` 恒为 1。

**数据澄清（重要，别再把幽灵数当对手数）**：`server/data/ghosts/index.json` 里
**内置幽灵**（`builtin=True` / 带 `legacy_path`，54 条、30 条赛道）owner 全是
`6f857655` —— 那是库里**唯一来自「别人」**的数据；其余 owner 是玩家自己的 pid
（运行期上传）。`server/data/ghosts/INDEX.md` 里那张表的 owner 列**已过时**
（它写 `99511744`/`0`，是 `ghost_sync_legacy` 改写 owner 之前的旧值），
**以 `index.json` 为准**。

**实现**（`server/tf_server.py`）：
- `OPPONENT_PIDS = list(FRIEND_NAMES)` = `44444444-…`(GhostRider) / `55555555-…`(TangoPro) /
  `66666666-…`(IronGear，本轮新增到 `FRIEND_NAMES`)。
- `def _opponent_entries()`：扫 `acct.ghost_list()`，只收 `builtin`/`legacy_path` 条目，
  按赛道分组、按 `drive_time` 升序 `zip(OPPONENT_PIDS, recs)` —— 第 1 个身份拿该赛道
  最快的内置幽灵，第 2 个拿次快，第 3 个再下一个。`drivetime` 用幽灵**自己的真实时间**，
  同时记 `{pid: {board: contentId}}`。结果缓存在 `_OPPONENT_CACHE`。
- `def _load_ranked_boards()`：`_load_leaderboards()` 的浅拷贝再 `setdefault` 合并对手行。
  ★ 对手**不落盘**：`_record_result` 走的是原始 `_load_leaderboards()`，所以
  `_save_leaderboards` 永远不会把对手固化进 `leaderboards.json`，改幽灵库后对手榜自动跟着变。
  `_stored_entries` / `_aggregate_global_entries` 已改用 `_load_ranked_boards()`。
- `h_ghost`：在原来「该赛道随便挑一条」之前，先按请求里的 `players=<csv>` 查
  `{pid: {board: contentId}}`，命中就回**那一条**幽灵 —— 榜上显示的时间与实际跑的幽灵一致
  （`[ghost] … 对手 <pid> 的幽灵 cid=N`）。

**实测**（`GET /public/playerstats/v1/ranking/…`）：
| 请求 | 修复前 | 修复后 |
|---|---|---|
| `track1062?players=<我>,44444444,55555555` | 1 行 | **3 行**（GhostRider 24776 / 我 24776 / TangoPro 27357），`playerCount=3` |
| `track1062?around=<我>,20` | 1 行 | 3 行 |
| `global_stats?players=…` | 1 行 | **4 行**（我 843423 / GhostRider 708933 / TangoPro 335671） |
| `GET /public/resultservice/v1/ghost?track_id=1062&players=44444444-…` | 1857 B（任意） | 1857 B `cid=19`（榜上 24776 那条） |
| 同上 `players=55555555-…` | 1857 B（同一份） | **2020 B `cid=18`**（榜上 27357 那条） |

⇒ 客户端那两条查询形状**都**被覆盖了：`players=`（好友页：自己 + 两个好友 pid）能拿到 3 行，
`around=`（全球页，服务端本来就不过滤）能拿到全部行。

**仍未闭环**：`66666666-…`(IronGear) 只拿到 1 条赛道（要第 3 条内置幽灵的赛道才有），
且它**不在 `rules.json` 的好友桩里**，所以只在「全球 / around」页可见。
若要让它是常驻对手，把 `server/rules.json:100` 的 `friends` 数组补一条即可。

### 3.4 「比赛幽灵」按钮永远是灰的（2026-10-05 修复）—— `replay_id` 响应缺键
> 用户反馈（原话）：「我想挑战这个幽灵，但是呢，比赛幽灵按钮是灰色的」

**结论一句话**：`POST /public/resultservice/v1/replay_id` 必须回
`{"replay_id": <int ≥ 1>}`，而旧实现回的是 `{"data": []}`。

**逐指令链路**（`tmp/libcmp/orig-libTrialsGo.so`）：

1. `tr::MenuzStateMap::setupRaceButton(bool doGhost, LeaderboardPlayerItem const* item)`
   @`0x77e01c`（世界地图上那颗按钮；比赛内的同名函数是
   `tr::IngameStateLeaderboard::setupRaceButton` @`0x6fa2c8`）：
   ```asm
   0x77e150  ldr  w8, [x21, #0x84]
   0x77e154  cmn  w8, #1            ; item->ghost_id == -1 ?
   0x77e158  b.ne 0x77e288          ; != -1 -> 跳过硬 disable 的那一段
   ...       bl   OnlineGhostManager::checkGhost(...)
             bl   MenuzComponentButtonImage::disable()   ; 首帧必然置灰
   ```
   +0x84 只在 `onGhostQuery` 回调里被写过，所以**它是唯一开关**。
2. `tr::OnlineGhostManager::checkGhost(OnlineGhostManagerListener*, int leaderboardId,
   char const* profile_id, int drive_time, int faults, int bike)` @`0x5070cc`
   → `OnlineCore::postJson(obj+8, url, body, cmd=0x0e /*14*/, 1)`；
   URL = `%s/%s/resultservice/v1/replay_id` @`0xb87ba9`，
   body = `{"profile_id":"%s","track_name":"track%d","drive_time":%d,"faults":%d,"bike":%d}`
   @`0xb87b58`（`drive_time/faults/bike` 直接来自榜上那一行，所以**回的时间必须与榜行一致**）。
3. `tr::GhostQueryObject::onNetworkDataReceived` @`0x508800`，jump table @`0xb879b0`
   （只认 cmd 13..19）；**cmd 14 → @`0x50895c`**：
   ```asm
   0x5089b4  strb wzr, [x20, w8]        ; 截断 body
   0x5089bc  ldr  x24, [x0, #0x10]      ; root 的第一个孩子
   0x5089a8  add  x21, x21, #0xbc0      ; "replay_id" @0xb87bc0
   ...       json_strcmp(node->[0x20], "replay_id") -> w20 = *(int*)(node+0x28)
   0x5089d8  cmp  w20, #1
   0x5089dc  b.lt 0x508a68              ; ★ < 1 一律走失败分支（err=7）
   0x5089e0  ldr  x8, [x0]              ; 成功：listener->vtable[0x18](err=0, id=w20, name)
   ```
   `{"data": []}` ⇒ 没有 `replay_id` 键 ⇒ `w20 = 0` ⇒ 走失败分支 ⇒ 死循环置灰。
4. `listener->vtable[+0x18]` 经 `.data.rel.ro` 取证确认就是
   **`_ZThn392_N2tr13MenuzStateMap12onGhostQuery(TR_ONLINE_ERROR, int, char const*)`**
   @`0x77f97c` —— 该子对象位于 `MenuzStateMap+0x188`，它的 vtable **address point = `0xdedbb8`**
   （`_ZTV` 头两槽在 `0xdedba8`/`0xdedbb0`：offset-to-top = 0、typeinfo = `_ZTIN2tr13MenuzStateMapE`）：
   `+0x00` onGhostMetaDataReceived / `+0x08` onGhostReceived / `+0x10` onGhostSent /
   **`+0x18` onGhostQuery**（前三槽是基类默认桩 `0x4ffc94` / `0x4ffe14` / `0x4ffe18`，
   即 `0xdedbb8`/`0xdedbc0`/`0xdedbc8`；`+0x18` 落在 `0xdedbd0`）。
   `tr::MenuzStateMap::onGhostQuery` @`0x77f900` 做的事：
   `strncmp(getSelectedData()->profile_id, name, 0x28)` 相等且 `err != -1` 时
   **`selected->[0x84] = id`**，然后 `MenuzStateMap::enableStartButtonIfPossible()`。
   ⇒ 下一次 `setupRaceButton` 看到 `[0x84] != -1` 就不再 `disable()`，**按钮点亮**。
5. 点下去 → `tr::MenuzStateMap::loadLeaderboardGhost()` @`0x77c77c`
   → `tr::PopupStateLoadGhost::setupLeaderboardGhost(item, leaderboardId, listener)` @`0x811248`
   → `tr::OnlineGhostManager::getGhost(listener, item->[0x84], leaderboardId, item->[0x6c])` @`0x506e48`
   → `tr::OnlineUserStorage::getData(listener, "ghost", id)` @`0x578780`
   → `GET %s/%s/userstorage/v2/content/ghost/%d/payload` @`0xb8c6f4`（**直接取二进制**）。
   ★ 这条 URL 早就由 `h_userstorage` 正确服务，所以**回对 replay_id 就够了**。

**`LeaderboardPlayerItem` 布局**（推出，供以后参考）：
`+0x00 char[0x28]` profile_id / `+0x60 int drive_time` / `+0x64 int faults` /
`+0x6c int bike` / `+0x84 int ghost_id`（初值 -1）。

**修复**（`server/tf_server.py` 的 `h_replay_id`，@`server/tf_server.py:2713`）：
- 照旧 `acct.ghost_record_replay(...)` 登记，然后按 `profile_id` + `track_name`
  查 `_opponent_entries()` 的 `{pid: {board: contentId}}`，命中就回
  **`{"replay_id": <该 contentId>}`**；榜外的 pid（玩家自己）回退到
  `acct.ghost_any_for_track(track)`；两者都查不到才回 `{"data": []}` 的失败形状。
- 回的是**真实存在且带二进制**的 contentId，正好能被上面第 5 步的 `/payload` 取走。

**实测（HTTP，`server/tf_server.py` 重启后 PID 31132 / :8000）**：
| 请求 body | 响应 |
|---|---|
| `{"profile_id":"44444444-…","track_name":"track100","drive_time":10509,…}` | `{"replay_id": 6}` |
| `{"profile_id":"55555555-…","track_name":"track100","drive_time":11014,…}` | `{"replay_id": 5}` |
| `{"profile_id":"<player-profile-id>","track_name":"track1041","drive_time":25656,…}` | `{"replay_id": 54}`（兜底） |

`GET /public/userstorage/v2/content/ghost/5/payload` → **937 B**、`/ghost/6/payload` → **905 B**，
首 4 字节都是 `03 00 00 00`（幽灵容器头）；
`track100` 榜行 `#1 GhostRider 10509 / #2 我 10509 / #3 TangoPro 11014` ——
与客户端 body 里带的时间**逐条对得上**。

**真机坐实的旧行为**：`server-log.jsonl` 里 31 次 `POST …/replay_id` 全部 `{"data": []}`；
其中 `00:44:16–00:45:44` 的 13 次带对手 pid（`track100` 两次分别是 GhostRider 10509 /
TangoPro 11014，`track1087` 若干），正是用户反复点那颗灰按钮的痕迹。

**仍未闭环**：`track1236` / `track66772` 这类赛道 `playerCount=0`（库里本来就没有
内置幽灵），点了不会出现对手行 —— 要补对手得先往幽灵库里放数据。

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

## 4. WebUI 管理界面 —— 🟡 五屏已交付（登录 / 账号 / 存档 / 下发 / 午夜杯运营 / 碉堡运营）

### ✅ 已交付（2026-10-06）

挂在**同一个端口**的 `/__admin` 下（不是另起 `tf_webui.py`），静态四件套在 `server/admin/`：
`index.html` + `app.css` + `app.js` + `i18n.json`（CN/EN，`localStorage.tf_lang` → `navigator.language`）。
前端零依赖、零 CDN，弹簧缓动由 JS 采样成 CSS `linear(...)`（`springEase()`，`damping 1.0 /
response 0.34`，只有手势回弹给 0.8），三档 `prefers-reduced-motion / -transparency / -contrast` 全支持。

| 屏 | 内容 |
|---|---|
| 登录 | 管理员口令（首启 12 位随机口令只打到控制台）；`--reset-admin` 兜底 |
| 账号 | 会话卡（总数 / 一键清空）+ 账号表 9 列（含封禁徽标、可复制的 profileId、记住我用量）+ 设备表 + 改口令 |
| 存档 | 槽位表（kind 徽标 / 物品数 / 赛道记录 / richness / 写入时间）+ 详情（关键余额 + 历史快照）+ 逐个「回滚到此」 |
| 下发物品 | 存档槽下拉 + 竞技场卡（金票 / 筹码，服务端即时生效）+ 醒目警示卡（如实写明要玩家在游戏里点「用云端」）+ **按类折叠的官方物品清单**（478 条，勾选 + 填数量 + 搜索；货币 / 消耗品 / 零件 / 服装 / 蓝图 / 赛道与碎片）。**服装按「套」列**：80 套（含 46 套从未上架的隐藏套装），勾一套 = 头盔 / 上衣 / 裤装一起解锁，行上显示官方名 + 内部代号 + 已拥有 n/3 + 套装效果（The High Roller = 无限汽油）。**涂装按「车」列**：108 款分 17 辆车，勾一款 = 给 `items2[664+BikeID]` 的位掩码置位（位 = SkinIndex），与真机存档逐位吻合。**蓝图按「车」列**：碎片是**计数器**（不是 0/1 标志），12 辆车的需求量各不同（Tango 4、Bronco 20、KTM 450 RALLY 30、Stallion / Donkey 50…），行上显示「需要 N 片 / 已拥有 n/N」、勾选默认填「还差几片」，另外 7 辆车没有碎片编号（只能金币买，界面说明） |
| 午夜杯运营 | 侧栏独立入口「午夜杯」。**顶部「午夜杯怎么运作」引导卡** + 6 张卡：**现状**（只读：本周赛道／窗口起止+剩余／周号／**本周车辆（实际车号 + 租借等级）**／真实+合成榜上行数／**幽灵与榜行数 + 预检警告**／挑战规则／玩家次数表／最近改动，每条改动带「撤销」）／**时间**（窗口长度 天数 + 模拟翻周 上一周・本周・下一周 + 确认门控的「立刻结束本届」）／**挑战规则**（每周次数 + 冷却，并只读说明赛道计时在客户端原表）／**赛道与对手**（赛道下拉（带图的车辆级别）+ 榜单 id + **本届车辆**（0 = 按赛道级别自动随机，整周同一辆）+ **租借升级**（0..10）+ 合成对手数 + 基准成绩 + 快/慢敌比例）／**奖励**（每档奖励个数 + 5 档 × 15 个池子方块，木档空 = 走内置规则）／**模板**（只读「当前生效值」+ 用户模板：存为模板／套用整页／只套用奖励方案／重命名／复制／删除）。每张卡一个「保存改动」，**只发改过的键**；改完写 `tf_config.json` 立即生效，每个键一条审计、可一键撤销 |
| 碉堡运营 | 侧栏独立入口「碉堡」。**顶部「碉堡怎么运作」引导卡** + 8 张卡：**现状**（只读：内部届号／客户端看到的编号／赛季长度／窗口起止+剩余／玩家档案表（段位・星・连胜・金票・筹码）／进行中对局／队列与在线／最近改动逐条可撤销 + 四条如实警示：排位对局时长现在是测试值、挂机产币是关的、段位与星章金票只能从这个页面改、奖励表里有不在官方 43 个里的编号）／**赛季**（赛季长度 天数 + 显示编号偏移 + 推进计数 + 确认门控的「推进到下一赛季」+ 赛季名 + 横幅图片路径带预览）／**对局时长**（排位对局时长（秒）+ 5 分钟 / 1 小时 / 还原 6 小时三个预设 + 新配出来的「友军对局时长」）／**段位与星章**（25 格升阶星章表 + 起始段位；段位名在客户端里根本不存在，只读说明写在卡里）／**匹配与 AI**（总开关／等真人多久放 AI／在线判定窗口／排队条目过期／固定赛道（382 条可搜勾选，最多 3 条）／候选赛道池／兜底赛道／AI 成绩倍率与毫秒增减／固定车辆（带车表下拉：`#号 名字 · T级别`）／**按赛道级别随机发车**／**随机池只放剧情车**／并行对局槽／排位局上限／加时局金票价／新玩家送票／免费票上限与恢复间隔／AI 用哪个档案）／**筹码与曲线**（曲线 x/y、起始筹码、每条赛道产币周期（0 = 挂机产币关闭）、筹码上限、败方保留比例）／**赛季奖励**（rank 0..25 逐行：金币 / 钻石 / 特殊奖励 —— `item_id 145` 的 `amount` 是客户端原表的 RewardID，下拉给出物品表里全部 **309 个**编号（按类别分组、官方 43 个标 ★）+ 可手填编号，只有物品表里查不到的编号服务端才拒（`bad-special`）并在界面标红；同档金币钻石相加、重复特殊奖直接报错；下面还有「礼包（商城商品）」= `product_list` 表）／**模板**（同午夜杯：只读当前生效值 + 存为模板／套用整页／只套用奖励方案／重命名／复制／删除） |

- **鉴权**：管理员账号独立于玩家账号，存 `data/admin.json`（`_hash_pw`，不入库）；登录发
  `tf_admin` Cookie（`HttpOnly; SameSite=Strict`，**故意不加 `Secure`** —— 只能走明文 HTTP）。
  门禁用 `startswith("/__") and not in _PUBLIC`，**新增端点默认是关的**。
- **受控写档**：`grant_items()` 只动 `items2` + `version` + 审计字段，先埋 `pre_grant_` 快照；
  可下发的物品集合由 `admin/items.json`（478 条物品 + 80 套服装 + 108 款涂装 + 12 个蓝图 +
  382 条赛道 + 309 条奖励名，
  `tools/build_item_catalog.py` 生成）决定，读不到目录就退回只放金币/钻石 —— 宁可少发也不能因为
  文件丢了把下发全放开。
  ★ 涂装走 `paints` 参数（`grantable_paints()` + `_paint_value()`）：**涂装不占 `items2` 的键**，
  而是写 `items2[664 + BikeID]` 里 `1 << SkinIndex` 那一位，所以界面按车分组。
  ★ 蓝图是计数器（真机档里 379 = 7 片、404 = 3 片），走普通 `items` 通道、`mode` 可 `add`/`set`，
  编号 `(车号 + 72) * 5 + 4`、需求量来自 `/conf/upgrades.txt` 的 `BP`。
  `rollback_save()` 埋 `pre_restore_` 快照（回滚本身不可逆）；两者都能一键撤销。
  带前缀的快照名在 `sorted()` 里排在纯数字时间戳之后，所以不会被 `SAVE_HISTORY_MAX` 的裁剪丢掉。
- **回归**：`tests/test_admin_webui.py`（160 项，全库 228 项）+ `tools/ui_smoke.mjs`（headless Edge + CDP
  逐屏断言，对 `Runtime.exceptionThrown` / console error 零容忍；每屏可带 `suffixes` 给分段截图改后缀）。
  ⚠ 教训：只调 `_introspect` 的门禁测试会给**假绿灯** —— `_handle` 里在它之前的内联近路
  就是绕过访问控制的洞（`/__log` 曾经这么裸奔过），所以门禁必须用真路由 `request_handle()` 测。

### 午夜杯运营屏（第四屏，2026-10-06）

> 用户 m03924：「web控制午夜杯…功能上独立控制季节赛时间，对局时长。奖励物品。要有模板。」
> **午夜杯没有对局时长**（那是碉堡的），所以那一格换成「挑战规则」（每周次数 + 冷却）；
> m03964 的答复定了粒度：奖励**只暴露池子编号 1..15**、不预览池内容（每池装什么在客户端的
> `/conf/wts_rewards.txt` 里，由 `getRewardItemForSlot @0x635880` 取）、模板=整页参数快照、
> 保存立即回写 `tf_config.json`（撤销当安全网，不做草稿→应用）。

- **服务端**（`server/tf_server.py`，`_reward_pool_ids()` 之后 / `h_liveevents_accept` 之前一整块）：
  - `_WEEKLY_KEYS` 是白名单（键 → `(lo, hi)`）；`weekly_values()` 只吐白名单内的键，
    `_weekly_reward_ids()` 负责把 `reward_ids` 夹到 1..15。
  - `GET|POST /__api/admin/weekly`：GET 回 `config` + `status` + `tracks` + `templates` + `audit`；
    POST `{fields:{…}}` **先收集 ops、逐键校验，全部合法才写**（任一键非法整批不落盘），
    每个键回 `{key, before, after, audit}`。
  - `POST /__api/admin/undo {id}` 按审计条目回滚**单个键**；`/__api/admin/templates`
    支持 `save / apply / copy / rename / delete`（`apply` 的 `parts` 可选 `all` / `rewards`）。
    三个端点都登记进 `/__help`，并且**默认都在门禁里**（门禁是 `startswith("/__")` 减白名单）。
  - **审计与撤销**：`cfg_set()` 记 `existed`/`before`，新增 `cfg_unset()`（删键，让代码默认值重新生效），
    `_audit_append()` 追加到 `server/data/config_audit.jsonl`（`AUDIT_KEEP = 300`，写失败只打日志）。
    模板的存/改名/复制/删除**不进审计**（只有套用会改配置，那时按键各记一条）。
- **时间窗**：新增 `weekly.window_days`（1..30，默认 7）。`_week_span()` 用它算秒数，
  替换了所有 `_WEEK_SECONDS` 算术（周号反推 / `weeK_end` / `midnight_circuit_end_time` /
  `week_end`）；`_WEEK_SECONDS = 7*24*3600` 只留作「7 天基线」，凡不等于它的窗口，
  管理端点的 `status.experimental` 为真，界面就显示「实验性」。**客户端不认识这个键**，
  它只影响服务端算出来的时间戳。
- **界面契约上的两句实话**（都写在卡片的只读说明里）：
  ①客户端**只在进入午夜杯时读一次**奖励配置（`weekly-reward-pools.md:381/387`）⇒ 改完要让玩家
  「退出午夜杯再进」，不用重启游戏；②赛道计时/用时上限在客户端原表里，服务端改不了。
  另外「玩家的挑战次数只存在服务器内存里」也在现状卡里明说了 —— 服务重启会把次数还满。
- **引导卡 + 赛道预检（2026-10-06，用户 m07402 报「改了参数以后就无法正常进行了」）**：
  页面顶部多一张「午夜杯怎么运作（怎么开、怎么关、哪里最容易踩坑）」卡（`weekly.guide.title` +
  `weekly.guide.l1..l6`，文案在 `server/admin/i18n.json`，不是服务端字段表），写明
  **没有开关**（届号 = 时间/届长，钉在 1970 的 epoch 上）、「立刻结束本届」= 周号 +1、
  换赛道前要先确认这条赛道有幽灵、周榜 ID = 0 的含义、改奖励要退出重进、次数在内存里重启回满。
  现状卡加一行「幽灵 / 榜行」（`ghosts` / `board_rows`）+ 红字警告（`status.warnings`）：
  这次的直接原因是用户把 `weekly.track_id` 换成 1258 —— 本服 `server/data/ghosts/` 与
  `server/data/leaderboards.json` 里**都没有 1258**，于是 `_weekly_joined()` 拿不到榜行 ⇒
  `last_participated_week` 恒为 0 ⇒ 客户端永远停在「加入午夜杯」；同时 `_weekly_opponent()`
  只能回 `replay_id=0` ⇒ 客户端每秒几十次去要 `ghost/0/payload`（404）。
  现在 `ghosts==0` 直接写清这个因果并建议「让玩家跑一圈上传幽灵，或换回 1041」；
  `lb != track`、窗口 ≠ 7 天也各有一条警告。
- **踩过的坑**：`dash()`（`server/admin/app.js:115`）返回的是 **DOM 元素**，被 `weeklyVal()` 当字符串
  拼进 `before + ' → ' + after` 时会渲染成 `[object HTMLSpanElement]`；空值必须一律返回 `'—'` 字符串。

### 碉堡（PVP）运营屏（第五屏，2026-10-06）

> 用户 m03924：「落地PVP控制…功能上独立控制季节赛时间，对局时长。奖励物品。要有模板。」
> m03981：「**我希望能带 GUI 都带 GUI**，这样方便懒人管理。主要是很多人不懂 json」、
> 「我也要能写这是第几个赛季」、「WebUI 做个带 GUI 的模板编辑器…还能做个模板保存。可以复用。」
> m04000：模板统一存 `server/data/templates.json`；特殊奖励下拉 + 可手填。

- **8 张卡的字段表在服务端**（`_BUNKER_CARDS` / `_bf()` / `_BUNKER_FIELDS`，中英标签 + 说明 +
  `kind` + 范围都写在表里）⇒ 前端只按 `kind` 造控件，**加一个运营参数只改服务端**。
  前端不把这些标签写进 `i18n.json`（那里的回归禁止动态拼 `t()` key）。
- **写路径复用午夜杯那一套**：`admin_bunker_apply()` 先收集 ops、逐键校验、全合法才写，
  `cfg_set` / `cfg_unset`（清空数字框 = 删键回默认值）各记一条 `kind="bunker"` 审计，
  撤销端点与模板端点跟午夜杯共用（`_PAGE_HOOKS` 里多一条 `bunker`）。
- **赛季显示编号**（m03981）落在 `season.display_offset`：**只在下发边界套偏移**，
  内部届号（`_pvp_season_window()` 的时间派生值）、赛季窗口、玩家档案里的 `season` 全都不动。
  `season.advance` = 推进计数，让本届窗口整体往前挪一轮（不是多届历史）。
- **赛季名是字面文本、不能含 `|`**：`title_text` 被客户端当纯文本渲染（不走本地化），
  但 `PopupStatePVPXGames::getPVPSeasonName` 只取**第一个 `|` 之后**的部分（`0x81a044`/`0x81a070`），
  所以服务端直接把含 `|` 的输入判成 `bad-pipe`（界面同步提示）。同理**换横幅图必须换 URL**
  （客户端拿 URL hash 跟 `season_banner%d.bnr` 里的 4 字节比，不符才重下），卡里写明了。
- **奖励编辑器**：`season.rewards` 的 rank 0..25 逐行；特殊奖励用客户端原表的 RewardID
  （`item_id 145` 的 `amount` 是 RewardID，**不是** ItemId）—— 下拉给**物品表里全部 309 个编号**
  （按零件/蓝图/服装/赛道/消耗品/其它/金币/钻石/特殊分组，`<optgroup>`），其中客户端固定表
  `PVPMatchSpecialRewards` 里的 **43 个**标 ★；界面也给这 43 个加一行提示。可以手填，
  只有「物品表里查不到」的编号会被服务端拒（`bad-special:<id>`）并当场标红。
  金币/钻石同档相加、重复特殊奖报错。`season.product_list`（礼包）用另一张小表编辑。
- ★★ **显示规则：玩家「已经拥有」这件物品时，客户端画它自带的兜底奖励**（2026-10-06 真机实验）：
  用户报「加了喷漆和衣服，游戏里看到的全是毛驴轮胎」。旧结论（43 个编号白名单）是**部分错的**，
  真因是原表每条奖励自己声明了 `Fallback`（`PVPMatchRewardTypes` 309 行里 237 行带它，
  其中 215 行是 `221` = Doughnut「毛驴轮胎」、22 行是 `-2`）：编号本身完全认识，
  只是玩家**已经有**那件物品，客户端就改画兜底物。证据链：
  ①`tr::PVPManager::getSpecialRewardById @0x5e231c` 查 `this+0x288` 的 `std::map<int, WheelReward>`
  时确实是 get-or-create，但唯一往这张表塞真数据的是
  `PVPDataParser::parseMatchSpecialRewards @0x5db0b4`，它读的原表 `PVPMatchSpecialRewards` 只有 7 组
  （零件 4 档 + `202` Soylent 涂装 + `203` Luchador 涂装 + `220` 毛驴图纸）；
  ②当晚做了覆盖包实验：造一个 `TrialsContentExtraDL_0probe.dat`（改原表 + 改 LOCF 三条当挂载探针）
  推进 `/data/data/<pkg>/files/`，`/proc/<pid>/fd` 里 **`298 -> …/files/TrialsContentExtraDL_0probe.dat`**，
  排在 13 个原 DL 包之后（引擎 `initAdditionalDataPacks()` 升序排序后 `reverse`，`searchFile` 从末尾往前扫，
  先命中先赢）⇒ **覆盖生效**；把 220 那行改成指向 `ItemId 414` Stallion 图纸、删掉 `Fallback` 后，
  游戏里那一档就真的画出了 Stallion 图纸；用户随后确认「只有这个账号没有的物品才能显示，
  有了就返回毛驴轮胎」。
  ③所以**喷漆 / 衣服 / 赛道也能当赛季奖励**（只是玩家已有该物时会显示兜底物），
  想让它在赛季列表里稳定显示真实图标，最稳的还是「下发物品」页。
  另外 `getCombinedSeasonRewards @0x5e7364` 只收 `item_id == 145` 的 pair，别的 item_id 直接跳过。
  详见 [contract §5d](<work/trials-frontier/notes/pvp-reward-contract.md>)。
- **引导卡（2026-10-06，m07402）**：页面顶部一张「碉堡怎么运作（赛季、奖励、玩家数据）」
  （`bunker.guide.title` + `bunker.guide.l1..l6`），写明赛季长度与**显示编号**的关系、
  奖励表是**每档增量**（`item_id` 只能是 1 金币 / 2 钻石 / 145 奖励物品）、
  **奖励显示规则**（玩家没拥有就画真图标、已拥有就画该编号自带的兜底奖励）、
  官方 43 个带 ★ 与「表外也能填」、改完要让玩家退出重进、段位只能在页内改。
  现状卡也多一条警告：奖励表里有编号不在官方 43 个里时，逐条列出并说明显示不稳定。
- **段位名不存在**（这不是没做，是做不了）：`tr::MenuzComponentPVPRank::render @0x720300` 里
  Localizator 调用数为 0，rank 用 `mt::String::setInteger` 画数字；LOCF 两份语言包里
  没有任何 `RANK_%d` / `PVP_RANK_%d` 键（62 个 `M_PVP_SEASON_TITLE_1..62` 的载体键表
  `0x2440a8` 也没有代码引用）。所以卡片只提供星章表与起始段位，并只读说明这一点。
- **382 条赛道**来自 `server/admin/items.json` 新增的 `levels` 段（`tools/build_item_catalog.py`
  的 `load_levels()`），赛道多选因此是可搜索的勾选清单，不是 JSON 文本框。
- ★ **绝不直接改 `server/data/pvp_state.json`**：金票 / 筹码 / 段位 / 星 / 连胜只在
  `/__api/admin/*`（走 `_pvp_request` 事务）里改，手改文件会被服务端下次写盘覆盖 —— 现状卡里明说。
- **踩过的坑**：①`bunker_payload()` 的 `templates` 一开始返回的是 `templates_for("bunker")`
  （`{page: [...]}` 字典），前端 `(data.templates || []).map` 直接炸；要 `.get("bunker", [])`。
  ②全局 `input { width: 100% }` 会把勾选框撑满整行，把后面的赛道名挤成「看…」——
  勾选框必须自己收回 16px。③长值（横幅路径 / UUID）在「当前生效值」网格里会溢出到相邻格子，
  `.kv .v` 要 `overflow-wrap: anywhere`。

### 车与地图的发车规则（2026-10-06，用户 m07949 / m08106）

> 用户 m07949：「原版设计里，车和地图是随机的。当然了，车和地图级别挂钩。1 级车跑一级地图…
> 碉堡的车辆升级状态随玩家真实升级的级别，午夜杯则是车升级不够或者没有这个车，给一个这个赛季
> 临时租给你的车，不入玩家真实车库的车。给你保底跑。如果你有这个车而且升级满，那数据随你本地等级。」
> 用户 m08042 拍板三条：①碉堡**每场随机发车**、只从玩家**已拥有**的车里挑；②午夜杯**整周固定
> 一台**随机车（不能每场变）+ 租借升级填 **5/5/5/5**；③组内随机、每场独立。

**逆向证据**（都在 `server/README.md` §5.4/§5.5 里有对应实现说明）：

- `LevelManager::isCorrectBikeTier @0x47c170`：图的 `B` 字段（`/conf/levels.txt`，`0xff` = 不限）
  是要求的车辆级别，车的 `Tier`（`/conf/bikes.txt`）必须**相等**；车 `Tier == 0xff` 直接放行。
- `OnlinePVP::getBikeAndTrackLists @0x4f96c0` 末尾把玩家的车库压成 `"bikes":%d` 位图，
  `UpgradeManager::getBikeIDbyIndex @0x62c4d8` 只有 `add w0, w1, #1; ret` 两条指令 ⇒ **bit i = 车号 i+1**；
  `BikeUpgrade::getBikeStatus @0x61c310` 要求「车在库里」且状态为 0 才置位。
  真机抓到的位图 `521227` = 车号 {1,2,4,11,13,14,15,16,17,18,19}，与用户的存档吻合。
- `OnlineWeeklyChallenge::parseChallengeConfiguration @0x5055f0` 定出挑战配置布局
  （`+0x18 track_id` / `+0x1c bike_id` / `+0x20 bike_skin` / `+0x24..0x34` 四个部件升级 / `+0x34 force_upgrade`）。
- `WeeklyChallengeManager::setBikeUpgradeLevel @0x636710`：`force_upgrade == 0` ⇒ 四个部件取
  **`max(玩家自己的升级, 配置值)`**；`force_upgrade != 0` 才无条件覆盖 ⇒ 这正是原版
  「没车 / 升级不够就借你一辆带固定升级的车」的实现，服务端发 5/5/5/5 + `force_upgrade = 0` 即可。
- 游戏自己的 LOCF 文案（`0xd174a4d1` / `0xd8010a3a`）逐字确认租借设计；`0xcae83f68` 还说明
  午夜杯「有时允许你开自己的车，有时强制所有人用同一辆」。
- 车表（`/conf/bikes.txt` 的 `Comment`/`Tier`）：T0 = 1/2/3/13/15/18、T1 = 4/5/6/14、
  T2 = 7/8/9/16/17、255 = 10/11/12/19；图表的 `B` 分布 = 0:135 / 1:142 / 2:101 / 255:4。
  LOCF 里**没有**单车名，英文名来自 `Comment`，中文名是人工补的。

**落地**：`items.json` 多出 `bikes` 段、`levels[].bike`（`tools/build_item_catalog.py`）；
服务端 `bike_catalog()` / `_track_bike_tier()` / `_pvp_owned_bikes()` / `_pvp_bike_pool()` /
`_pvp_pick_bikes()` / `_weekly_bike_id()` / `_weekly_loan_upgrade()`；碉堡 match 卡多两个开关
（`matchmaking.bike_random` / `bike_story_only`）+ 车表下拉，午夜杯多「本届车辆 / 租借升级」两行。

### 还没做

概览屏、运行时+日志屏。剩余可管项：`/__config` 的可视化编辑、幽灵库浏览替换。
（`weekly.*` 归午夜杯屏，`season.*` / `matchmaking.*` / `chips.*` 已归碉堡屏。）

### 历史：当时的已有基础

服务器已有一批只读内省端点（`tf_server.py` 的 `_introspect`）：

```
/__ping  /__log  /__accounts  /__devices  /__sessions
/__saves  /__save?profile=<pid>  /__history?profile=<pid>&ts=<ts|latest>
/__restore?profile=<pid>&ts=<ts|latest>  /__ghosts
```

### 当时的建议实现路径（部分已不适用，保留作决策记录）

1. 新增 `server/tf_webui.py`（纯标准库 `http.server`，或 Flask 单文件），复用 `tflocal_accounts` 的读写函数。
   → **实际做法相反**：不新增进程/端口，直接挂在 `tf_server.py` 的 `_introspect` 里，
   静态文件走 `_ADMIN_FILES` 白名单（「路径 → 文件名」写死，杜绝路径穿越）。
2. 页面：账号列表 / 新建账号 / 改口令 / 删除；存档列表 + 一键回滚；幽灵库浏览与替换；
   全局开关（`Anticheating_Enabled`、活动时间、商品表下发）。
   → 前三项已做；幽灵库与全局开关留在后四屏。
3. 与 `tf_server.py` 同进程不同端口（例如 8001），或用 `/admin` 前缀挂在同端口。
   → 选了后者（`/__admin`），因为客户端连接的局域网 IP 与端口已经散落在 APK / `tf_server.txt` 里，
   再多开一个端口只会多一个要填的地方。

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

## 7. 下一步规划（2026-10-05 盘点）

> ROADMAP 那五条讲的是**做什么**，这一节讲**先做哪个、为什么现在能做**。

### P0 · 收口（不用等任何人）

| # | 事项 | 现状 / 依据 |
| --- | --- | --- |
| 1 | **真机复验「比赛幽灵」按钮** | 服务端已修并**离线复验**：`h_replay_id` 查不到对手时改为回 `{"replay_id": 1}`（客户端 cmd 14 是 `cmp w20,#1; b.lt` 硬失败，<1 就永远是灰的）；`GET /public/resultservice/v1/replaydata?track_id=N` 现在按 `pid + track` 回 `{"content_id": N}` 让客户端**更新已有**幽灵而不是每场新建。**只差用户在真机上点一次**。 |
| 2 | 私服规则数值**改照史料填** | `work/trials-frontier/notes/online-rules-evidence.md` 落地后，「赛季多长 / 榜截断多少 / 门票怎么消耗」从**自己编**变成**有出处**（见 P1-4）。 |
| 3 | 后台服务器 | 已在跑：`python server\tf_server.py --host 0.0.0.0 --port 8000`（`/public/timeservice/v1/time` 实测 HTTP 200 `{"data": []}`）。 |

### P1 · ROADMAP §3「在线功能完善」的剩余缺口

| # | 事项 | 卡在哪 / 怎么解 |
| --- | --- | --- |
| 4 | `limited_purchases` 的 `product_id` | **`.so` 里只有 product_id 字符串，没有 bundle id ↔ 具体礼包的映射**（`targeting-v1.md` §9）。两条路：运行时 dump，或在真机上抓一次**真实**的 `receiptvalidation/v1/product/configuration` 响应。**在此之前商店里不会出现礼包**（`h_iap_products` 回空数组）。 |
| 5 | 午夜杯 / 限时活动的**运营参数** | 现在有出处了：赛季长度 **S1 = 59 天（2014-12-12→2015-02-09）→ S83 = 28 天（2021-03-22→2021-04-19）**；榜截断 **PvP 前 10 000 / Global 前 30 000**；**KTM Rally = 4 个 leg、间隔约 7 天、每赛道只取前 3 000**；**Golden Ticket = PvP 排名赛的入场消耗品**；**Midnight Club = 编号每周轮次**（服务器 `event/22`）；事件编号 `/event/1…/event/123+`，多 leg 为 2–6。全部带 URL + 原文。 |
| 6 | 事件/赛季**具体数值**仍缺的那些 | 史料明确查不到（`online-rules-evidence.md` §5）：Legend 以下的段位名、晋升星数、ticket 发放与恢复节奏、**PvP 赛后金币/宝石量级**、芯片收支速率、每日登录奖励链、每日任务结构、限时礼包内容。⇒ 这些**只能我们自己定**，且应当交给 WebUI（见 P2）。 |
| 7 | `dlcontent_frontier_android/794/info.json` 是否要给真内容 | 未定。仓库里目前只有 `tmp/cdn/frontieronlinecontent.zip`（305 198 B）。 |

### P2 · ROADMAP §4「WebUI 管理界面」

| # | 事项 | 说明 |
| --- | --- | --- |
| 8 | 管理界面 | 注册页 + 管理 API 已起头。有了 P1-5/6 的分工，**赛季长度、榜截断、leg 数、门票消耗这些正好按 §4 的 ★ 决策记录做成 WebUI 可调项** —— 那些"史料查不到"的数值本来就该是运营参数。 |

### P3 · ROADMAP §5「一键开服打包成 exe」

| # | 事项 | 说明 |
| --- | --- | --- |
| 9 | 打包 exe | 未开始。 |

### P4 · 悬而未决 / 需要用户输入

| # | 事项 | 需要什么 |
| --- | --- | --- |
| 10 | **Data Cube 为什么在赛道里看不见**（m01917） | **已定论的部分**：它是**常驻本地 10 环剧情链 `MISSION_362–371`**（PANDORA'S CUBE / HIDDEN DATA / IMPACT / INVESTIGATION / DISCOVERY / UTOPIA / DIVISION / DOWNFALL / PANIC ROOM / THE DARK MACHINE），文本**全部由客户端 loc 表本地提供**；`.so` 里**没有方块位置表**。用户存档 `missions2.solved` 里 **362/363/365/366/367 已经 solved** ⇒ 这条链在这个档上已经走了 5 环。`missions2.available` 是 `(group<<16)\|mask` 位掩码、只覆盖 mission 0–191，方块任务不在其中（说明它们不是任务大厅里可选的剧情任务）。<br>**缺的是用户回答**：这个存档是**原版带过来的**，还是**在私服新开的**？若是带过来的 ⇒ 已收集的方块按设计**永久消失**，当前表现就是正确的。 |
| 11 | 在模拟器上跑一遍在线功能 | 服务器已在后台跑（`0.0.0.0:8000`）。**模拟器访问宿主机必须用 `10.0.2.2`**，即 `/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt` 里应写 `10.0.2.2:8000`（真机则写宿主机的局域网 IP）。 |

### 附：本轮清掉的垃圾（2026-10-05，共释放 1742.3 MB）

- 删 `$e/` —— **1229 文件 90.6 MB**，一份完整 APK 解包，是某次 PowerShell 变量重定向事故的产物（`.gitignore` 里的 `/$*/` 规则早就把它标注为「历史遗留」）。
- 删 `tmp/build/` 下全部 `*-unsigned.apk` 与 `*-aligned.apk` 共 41 个 —— **1.65 GB** 纯中间产物。**保留 `tmp/build/tf-m16.apk`**，因为 `tools/make_selfcontained.ps1` 拿它当 `$Base`。

---

## 8. 第二轮修复（2026-10-05，用户 m02863 提的四项）

> 依据来自两个只读逆向子代理的报告 + 真机（小米 8 `<设备序列号>`）实测，全部端点契约已按反汇编逐条核对。

### 8.1 碉堡（PVP）筹码：总量不保存

- **根因**：账号级筹码与局内票**从来没落盘**，每次重启都从 `cfg_int("chips","start")` 重来；「从 0 涨到 1 或 3」是 `_pvp_chips_for()` 按**已解锁赛道数**的产出曲线在跑（实测 ≈1 枚/92 秒 = 3600 ÷ 39 条赛道），产出逻辑本身没错。
- **改动**：`server/tf_server.py` 新增 `_pvp_state_load/_pvp_state_save` + `PVP_STATE_PATH`，落 `server/data/pvp_state.json`（已加进 `.gitignore:51`）。
- **补偿**：`tf_config.json` 里 `chips.bonus = 114514`，每个账号**只发一次**（`bonus_done` 一起落盘）。真人账号已是 114514，人机 `44444444-…` 保持 `chips.bot_start = 500`。
- 用户对两个数的区分（原话 m02863）：「碉堡界面那个筹码是货币，对局那个是争夺工资」—— 代码里本来就分开：`_pvp_chips`（账号级货币，商店消费）与 `_pvp_match_chips`（局内曲线）。

### 8.2 碉堡进去转圈

- **根因**：`GET /public/pvp_matches/v1/players?profiles=…` 原来回 `{"data": []}`（**对象**），而 `parseFriendLeaderboard @0x4fe88c` 第一句就是 `ldr w8,[x1,#0x30]; cmp w8,#2; b.ne` ⇒ **根必须是 JSON 数组**，对象直接短路，界面永远转圈。
- **改动**：新增 `h_pvp_players`（按 `profiles` 切 CSV 去重，逐条 `_pvp_player_info()` + `profile_id`，**直接返回列表**），路由从 `h_pvp_accept` 改指它。
- **踩坑**：动态处理器的 `query` 参数是**原始查询字符串**不是 dict，必须 `dict(parse_qsl(query or ""))`。
- **真机验证**：`tmp/shot1.png` —— 碉堡完整加载，25 级徽章、赛季奖励轨道、左下角筹码 **114514**，转圈消失。

### 8.3 幽灵挑战 / 上传 / 下载

- **挑战（按钮灰）**：`h_replay_id` 命中不到时回 `{"data": []}` → 客户端 `cmp w20,#1; b.lt` 判 err=7。改为「先跨赛道兜底 `ghost_any()`，再不行回 `{"replay_id": 1}`」。
- **上传（每场 +1 条）**：`replaydata?track_id=N` 被设成永远回空，而客户端 cmd 13 正是用它的 **`"content_id"`（snake_case）@0xb87d85** 决定「更新已有」还是「新建」。改为按 `pid + track` 查本人幽灵并回 `{"content_id": N}`。
- **下载（12 字节 JSON 当幽灵喂引擎）**：cmd 15/16/18 分支有 `cmp w8,#0x65; b.lo`，**响应体必须 ≥101 字节**；改为无幽灵时 **404 + 空体**。`h_ghost` 兼容**单数 `player`**（`pvp_replaydata`/`robot_replaydata` 发的就是单数）。
- **形状不符**：search 的 `metadata` 补 `size`（cmd 28 `size < 1` 直接失败）、补 `pvpid` 过滤、`get_ghost` 的 `players` 当 owner 过滤（**只有非 PVP**）、`GET /content/ghost/<id>` 补顶层 `profileId`。
- **赛道号掩码**：以前只在查询侧掩 `&0xFFFF`、写入侧原样存，index.json 里 `51:8389649` 与 `1:1041` 混存。现在**在存储边界掩**（`mask_track` + `_migrate_ghost_records`），迁移后 `track_id > 0xFFFF` 的记录数 = 0。
- **真机验证**：`PUT /public/userstorage/v2/content/ghost/67/payload`（2063 B，头 `03 00 00 00`）+ `PUT /content/ghost/67`（body 无 `track_id`，与 `createMetaData` 的 `w5==-1` 分支一致），落库 `cid 67 / track 1315 / size 2063`。`GET …/replaydata?track_id=1315` → `{"content_id": 67}`（复用），无幽灵赛道 → `{"data": []}`（新建）。

### 8.4 午夜杯（= 周赛）规则

- **时间窗滑动**：服务端原来给 `now-3600 ~ now+24h`，而客户端把这对时间戳写进**物品 1165 / 1166**（实测：槽位 = `base_id*5 + variant`，即 `getItemCount(233,0/1)`；`base 234 → 1170 = 5` 与 `item_names.tsv` 的 `234='Rally Tickets'` 吻合可佐证）。存档 history 里 `1166-1165` 恒为 **90000** 且两端一起前移 ⇒ 倒计时永不减少。**改为按 epoch 周钉死**为 `week_start ~ week_start+604800`，且与 `config` 的 `week_end` 一致（此前两者矛盾：`ChallengeConfig::getRemainingTime @0x62f358` = `week_end + mc_challenge_end_extra_time`，后者实测 = **10**）。
- **`last_participated_week` 回 0**：新增进程内 `_WEEKLY_LAST`，**记住客户端 POST 上来的值再原样还回去**（服务端不产生它）。以前一直回 0 ⇒ `updateLastWeekIndex @0x6335cc` 永远满足 `w8 < 1` 而反复重发。两种 POST body 都接（`{"additional_retry":%d}` @0xb87596 / 带 `last_participated_week` 的 @0xb87465）；`additional_retry` 是客户端本地装扮加成（`getCurrentChallengeRetryBonus`，本机算 256）、**不可信，直接丢弃**。
- **物品 233 / 125 不需要服务端下发**（原子代理建议已作废）：物品由客户端自己上传、服务端只存不产。存档实测 `getItemCount(125,2)`（槽位 627）= **1**，`canEnterEv @0x7b26c4` 的门是过的。
- **决定不做的三件**：①`left_retry_times` 递减（`+0x258` 读者扫出 240 处无法区分栈偏移，`checkCooldownValidity` 机制上不该锁死，用户也没抱怨）②BUG-10（robot 对手名/time 绑定，现有 `ghost_any_for_track` 兜底实际能对上）③BUG-11（`h_ghost_upload` 死代码）。`reward_config` 也**保持每槽 1 条**（改成 12~31 条是对 pair 语义的猜测，有崩栈风险）。
- **代码顺带**：`weekly.window_hours` / `weekly.task` 两个失效配置键删掉；`_WEEKLY_TRACK_ID` 常量改成 `_weekly_track_id()`（读 `weekly.track_id`，热加载）。

### 8.5 仍未收敛的一条

`POST basic_info` 在真机上**每次 `GET basic_info` 后面都跟一次**（两种 body 交替），即使服务端已回 `last_participated_week = 2961 == week_index`。逐条量时间后确认**不是风暴**：00:46–00:59 只有 10 次、13:19 与 13:24 各一次，节奏 = 每次进界面/回前台一次。所以 `updateLastWeekIndex` 的 `w8 == week_index → 不发` 不是唯一触发点，`submitLastWeekData` 另有调用者。**暂不处理**（无害，且 `last_participated_week` 现在能正确往返）。

## 9. 第三轮修复（2026-10-06，用户 m02696 / m03026 / m03499 提的三条物品清单 bug）

> 三条都是「后台下发的物品清单不对」，根因同一类：**只按奖励/商店配置里的 `ItemId` 抓 id，漏掉了真源表**。
> 全部靠 `content.dat` 里的真源表 + 反汇编 + 真机存档三方交叉验证。

### 9.1 服装缺件（m02696：「衣服还缺少一部分…有个衣服叫 high Roll 之类，集齐套装效果是无限汽油」）

- **根因**：隐藏/未上架套装（High Roller、Henchman 黑/橙、Polar Vortex、KTM Gear…）**在任何奖励或商店配置里都不出现**，
  按 `ItemId` 抓永远抓不到。真源是 `/conf/customization.txt`（`0007_*.bin`）：`Rider` 数组 80 条。
- **公式**：套装部件 `id = ItemType * 5 + tier`（tier 0/1/2 = 头盔/上衣/裤装）；Rider ID 0–19 那批记录没有
  `ItemType` 字段，用 `type = 40 + Rider ID`（靠 `ITEM_57_0` = "The Eggman Helmet Piece" 这类部件名反查印证）。
  80 套 × 3 件 = 240 个编号，其中 **99 个此前从没进过目录**，**165 个在真机存档里出现过**（可下发）。
- **顺带**：`UnlockType` 全 4 = 没上架过 → 46 套隐藏；`BonusPower` = 套装效果（24 套），**集齐即账号级生效**
  （文案自己写着 "Outfit does not need to be equipped"），High Roller = `MULTIPLY_FUEL_REFILL_TIME 0.006`
  → 界面文案「全套奖励：无限汽油！」（官方中文名就是「摩天轮」，用户的记忆是对的）。与「赛道解锁」撞车的
  20 个编号按服装归类、旧名留 `alias`。提交 `1bf32c3`。

### 9.2 涂装只有 53 条（m03026：「研究一下涂装怎么下发」）

- **根因**：那 53 条是按奖励表 `ItemId` 抓出来的伪条目，而且 13 个编号同时是零件号。
- **真源**：`/conf/bikes.txt` 的 `SkinData` = **108 款**（`ID` 连续 0..107）。
- **★ 涂装不进 `items2` 的键空间**：存档里每辆车只有一条
  `items2[664 + BikeID] = ((当前装备的 SkinIndex + 1) << 24) | 已拥有位掩码`（位 = SkinIndex，24 位）。
  反汇编（`getCustomBikeTextureItemId` @`0x0061d350`、`hasCustomBikeTexture` @`0x0061d4e8` 等 8 个符号）
  + ccb 真机存档 6 条逐位对照确认；反汇编里的 XOR/rotate 只是内存混淆，JSON 是明文。
  所以下发走独立的 `paints` 参数（`grantable_paints()` + `_paint_value()`），后台按「车」分组。提交 `ec3b6aa`。

### 9.3 蓝图（m03499：「蓝图没问题，但是蓝图是碎片。每个车的蓝图碎片要求数量不一样。而且车数量也对不上」）

- **三条症状的根因**：① 界面把 `blueprint` 当 0/1 标志（`FLAG_CATS`），而真机存档里它是**计数器**
  （ccb 档 379 = 7 片、404 = 3 片、429 = 1004 片）；② 需求量没进目录；③ 11 条里 3 条（374/379/439）的官方名
  被 RedLynx 复制粘贴成了 Tango 的 Redlynx 涂装名，界面三行同名；④ 缺 **404 Berserker** ——
  它只以紧凑形式 `{IID,IL,IC}` 出现在 `/conf/giftbox.txt`，而生成器原来只收有整数 `ItemId` 的节点。
- **编号**：`id = (车号 + 72) * 5 + 4`。反汇编印证：`hadleBlueprintPurchase()` @`0x00663110` 里
  `bikeID + 0x48` → `×5` → `+4` 后调 `PlayerItems::add(...)`；`MenuzBlueprintRenderer::init()` @`0x007c3060`
  用 `BikeUpgrade::getUpgradeID(bikeID, 4)` 读已拥有、车记录 `[+0x58]` 读需求量，`blueprintComplete()`
  @`0x007c4e5c` 比两者是否相等。
- **需求量真源**：`/conf/upgrades.txt` 的 `BP`（Tango 4、Bronco 20、KTM 450 RALLY 30、Stallion / Donkey 50…），
  与官方文案里 7 处 "Collect N to build" 逐条吻合。
- **车辆名单**：19 辆车里只有 12 辆有碎片编号；另外 7 辆（Armadillo / Jackal / Mantis / Marauder / Riptide /
  Phantom / Moonrover）的编号 369/384/389/394/399/409/424 在任何配置和真机存档里都不存在 —— **只能金币买，
  不是漏挖**，界面照实说明、不造条目。
- **★ 紧凑形式不能一律套公式**：`{IID,IL,IC}` 的 `IC` 各家含义不同 —— 计数器类是数量，赛道（`IID 170`）装的是
  **赛道 id**、涂装（`IID 133/134/136`）装的是**涂装序号**、零件礼包（`IID 70`）装的是**零件号**。
  先放宽成「所有 `{IID,IL}` 都收」时目录立刻多出 25 条垃圾（503 条 / 撞车 46）；收窄成「只收蓝图那一族」
  后回到 478 条 / 撞车 20。
- **界面**：蓝图按「车」列一行，显示官方名 + 车名 + 「需要 N 片」+「已拥有 n/N」+ 旧名（`alias`），
  勾选时数量框默认填「还差几片」；`FLAG_CATS` 只剩 `outfit`。

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
| `dist/TrialsFrontier-offline-full.apk` | **全自包含离线版（推荐给普通用户）**：336 531 425 字节，SHA-256 `4A76FAA832C643E7ED344E6A27F2D5DEE987481A40363F02F8BA1F1D6FE049FA`。DL 内容 + OBB 都在包内，首启由 app 自己解包进 `/data/data` 与 `/sdcard`，**不需要 adb、不需要 root、不依赖服务器**。原理见 `work/trials-frontier/notes/selfcontained-apk.md` |
| `dist/TrialsFrontier-offline-full-说明.md` | 上面那个包的安装说明（怎么装 / 限制 / 改 IP / 校验） |
| `dist/TrialsFrontier-clean-pack.7z` | 干净整合包（APK + OBB + data 区、无存档），给**有 root / 用 adb** 的人；347 128 628 字节，SHA-256 `41AB9DD206A9F4C1C793B42743D6D7F3DEBBF8AFA5A77CF1F7477C331B95B2DC` |
| `tools/make_selfcontained.ps1` | 打全自包含 APK 的流水线：换 Application 名 → javac+d8 出 `classes4.dex` → 生成 `payload.txt` → `build_apk --add` → `zipalign -p -f 4` → `apksigner` |
| `tools/apkpayload/OfflinePayloadSetup.java` | 首启自解包类（`extends DexApplicationClass`，只覆盖 `onCreate`），随包进 `classes4.dex` |
| `work/trials-frontier/notes/*.md` | 逆向与情报笔记：`selfcontained-apk.md`（打包原理 + 两个坑）、`online-rules-evidence.md`（赛季/事件史料，带出处）、`real-server-samples.md`（全仓库唯二的真实服务器样本）、`web-research-toolkit.md`（本机抓取方法） |

### 构建流水线
```
pwsh -File tools\make_apk.ps1 -Name <名字> [-NativeDir tmp\m13] [-Manifest tmp\m4\AndroidManifest.xml]
```
内部：`python tools\build_apk.py --base tmp\extract\aUiMEPVatQ.apk --out ... --replace lib/arm64-v8a/*.so=... --drop-prefix lib/armeabi-v7a/`
→ `zipalign -p -f 4` → `apksigner sign --v1 --v2 --v3`（keystore `work/trials-frontier/keystore/trials.jks`，alias `trials`）。

> ⚠️ **基线与清单两个坑**：native 补丁必须基于 `tmp\m8`（含 `DLContentManager::isDLReady()`），
> 基于 `tmp\m2` 会丢掉「下载暂停」修复；`make_apk.ps1` 必须传 `-Manifest tmp\m4\AndroidManifest.xml`
> （targetSdk 27），否则明文 HTTP 被禁、Java 侧 DLC/内购校验报 `Cleartext HTTP traffic ... not permitted`。
