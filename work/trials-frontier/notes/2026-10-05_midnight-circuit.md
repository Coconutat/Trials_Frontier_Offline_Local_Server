# 午夜杯（Midnight Circuit）逆向 + 落地分析

日期：2026-10-05 23:07 +08:00
对象库：`tmp/libcmp/orig-libTrialsGo.so`（7.9.4，14901128 B，VA == 文件偏移；`.init_array` 之后 VA − 0x10000 = 偏移）
服务器：`server/tf_server.py`、`server/rules.json`、`server/data/tf_config.json`
素材：`pvp_docs/午夜杯回忆/{pvp.png,现状.png,游戏规则/*}`、`pvp_docs/午夜杯.md`
真机日志：`work/trials-frontier/notes/server-log.jsonl`

---

## 0. 一句话结论

午夜杯在客户端就是 **周赛（weekly challenge）**：`tr::MenuzStateWeeklyChallenge` + `tr::WeeklyChallengeManager` + `tr::OnlineWeeklyChallenge`，
wire 全部走 `…/liveevents/v1/weekly_track_system/*`（服务端端点已经齐了）。
「每次进去只能加入、没有全球榜 / 挑战 / Top 1%」**不是缺端点，而是配置里 `week_settings.week_leaderboard` 恒发 `0`**：
客户端把它当**排行榜数字 id** 用（落在 `ChallengeConfig+0x0c` → `WeeklyChallengeManager+0x1c`），
`id < 1` 时 `hasLeaderboard()` 直接为假、`getPlayerRankPercent()` 返回 `-1.0f` ⇒ 榜单区空、TOP 1% 条无数据、
周结算奖杯退化成最低档（`getPlayerTrophyType(-1)` = 5 = wood）。

---

## 1. Evidence → Finding → Path

| # | Evidence（反汇编/日志实证） | Finding | Path |
|---|---|---|---|
| E1 | `tr::OnlineLeaderboards::getLeaderboardName(char* out, int id) @0x00509604`(180 B)：`id==0`→`"global_stats"`；`id==0x10000`→`"global_stats_donkey"`；`id==0x100000`→`"global_stats_crazy"`；`id & 0xe0000`→`snprintf(out,32,"%s%d","event_stats",((id>>18)&0x18)\|((id>>17)&7))`；否则→`snprintf(out,32,"track%d",id)`。常量：`'%s%d'@0xb4745c`、`'track%d'@0xb87f8a`、`'event_stats'@0xb881dc`、`'global_stats'@0xb881e8`、`'global_stats_donkey'@0xb881f5`、`'global_stats_crazy'@0xb88209` | 客户端只有一套 **数字 id → 榜名** 的映射；`event_stats1..7`（bits17-19）是**活动**榜，`track<N>` 是赛道榜 | 我们要发的 `week_leaderboard` 必须落在这套 id 空间里；服务端只需按算出来的名字提供 `playerstats/v1/ranking/<name>` |
| E2 | `OnlineWeeklyChallenge::parseChallengeConfiguration @0x005055f0`：`week_start→cfg+0x04`、`week_end→cfg+0x08`、**`week_leaderboard→cfg+0x0c`**、`global_cooldown_time→cfg+0x10`、`global_retry_count→cfg+0x14`、`global_gem_amount→cfg+0x70`，全部 `ldr w8,[json_node,#0x28]`（**整数**读取）。键串地址：`week_index@0xb87624`、`week_start@0xb8762f`、`week_leaderboard@0xb876f9`；`week_leaderboard` 全库**唯一** xref = `0x005057b0` | `week_leaderboard` 是 **int**，写进 ChallengeConfig+0x0c | 服务端继续发整数（我们已经在发，只是值恒 0） |
| E3 | `WeeklyChallengeManager` 的 `ChallengeConfig` 在 `this+0x10`（`getWeeklyTrackIdEv @0x006362a8` 从 `x0+0x10` 复制 ChallengeConfig，任务容器在其 +0x38） | `cfg+0x0c` ⇒ **`manager+0x1c`** | `manager+0x1c` = 排行榜 id |
| E4 | `WeeklyChallengeManager::hasLeaderboardEv @0x006316fc` 与 `getLeaderboardEv @0x00634500` 同构：`if(!this[0x89]) return null; int id=this[0x1c]; if(id<1) return null; lb=LeaderboardManager::getLeaderboard(id); if(!lb \|\| ((int*)lb)[0x34/4]<=0) return null; return lb;` | `manager+0x1c` = 本地榜 id，`+0x89` = 榜是否启用，`lb+0x34` = 行数 | id<1 ⇒ 客户端认定"没有榜" |
| E5 | `WeeklyChallengeManager::getPlayerRankPercentEv @0x00634548`(184 B) 开头：`s8=-1.0f; if(!this[0x89]) return -1; if(this[0x1c]<1) return -1; lb=getLeaderboard(this[0x1c]); if(!lb \|\| lb[0x34]<1) return -1;`，后面按行数算百分位；`getPlayerTrophyType(float) @0x006353c8`：`<=1`→1(platinum)、`<=10`→2(gold)、`<=25`→3(silver)、`>100`或`<=0`→5(wood)、其余 4(bronze)（常数 `100.0f@0xb44b70`）。调用链 `MenuzStateWeeklyChallenge::giveWeeklyRewardEv @0x007b7e44` → `getPlayerRankPercent` → `getPlayerTrophyType` → `calculateReward(WTS_TROPHY_TYPE)` | **Top 1% 条与周奖杯完全由榜数据驱动**：名次/行数→百分位→奖杯档；拿不到榜就是 -1 ⇒ wood | 服务端只要让该榜"存在且含自己这一行"，Top1%/奖杯自动就对 |
| E6 | `WeeklyChallengeManager::requestOpponentLbDataEv @0x00631d98`、`updateGhostStateEv @0x00631420`、`updateEv @0x00630ac4` 三处调用 `OnlineWeeklyChallenge::requestPlayerStats(listener, [x19,#0xa8], [x19,#0x1c])`；`OnlineWeeklyChallenge::requestPlayerStats @0x00503cc8` 转发到 `OnlineLeaderboards::requestPlayerStats(OnlineLeaderBoardListener*, const char*, int) @0x0050a934`（真实现；PLT 0x35e750） | 拉榜请求 = `(榜名 @+0xa8, 数字 @+0x1c)` | 榜名与 id 同源，改一个即可 |
| E7 | 真机日志 2026-10-05 22:30:39（设备 `192.168.5.2:8000`）：`GET …/weekly_track_system/config/0` → 紧接 `GET /public/playerstats/v1/ranking/global_stats?around=53ebbd18-818e-5c2c-a865-773262f736e5,20` 与 `GET …/ranking/global_stats?players=53ebbd18…,44444444…,55555555…`（两个页签 GLOBAL / 好友）；全部 200 | `week_leaderboard:0` 时客户端**确实**按 `getLeaderboardName(0)="global_stats"` 去拉榜（两个页签同名不同参数），但显示侧 `getLeaderboard(0)` 查不到 ⇒ 屏幕空白 | 换一个 `>=1` 的 id，拉取与显示两侧就都指向同一个榜 |
| E8 | 同日志：22:30:42 `POST …/weekly_track_system/start_race` `{"gem":false,"checksum":"61D0E6C286FF38F9ED648F9B43BAE397","timestamp":1791210633, "restart":false}`；22:31:16 `POST …/end_race` `{"score":359974908,"checksum":"B79F98826C577475DD38DBA01AB93AC5","timestamp":1791210666}`；两者服务端都回 `{"data": []}`（客户端对这段响应一个字节都不解析） | 真机今天就完整跑完过一局午夜杯（进赛道→跑完→上报） | 起跑/结算链路**已经能用**，本轮不用碰 |
| E9 | 全日志 grep：**没有任何 POST `/public/playerstats/*`**；成绩入库只经 `POST /public/playerprogress/v1/progress`（存档 `highscores2`，`_ingest_highscores`）与 `batch_update` | 赛道榜的行来自"存档同步"，不是一次显式提交 | 要验证：跑一局午夜杯是否会把该赛道成绩写进存档 → 进榜 |
| E10 | `WeeklyChallengeManager::loadConfigEv @0x006307ac`：`datapack::DataFilePack::searchFile('/conf/wts_rewards.txt' @0xb91a00)` → `WeeklyChallengeManager::parseJson(const char*, char*) @0x34e7b0` → `populateRewardLists()`；`h_liveevents_reward_config`（服务端）按 `platinum/gold/silver/bronze/wood` 回 `{"reward":[Reward_{variant*5+i+1}],"n":[...]}` | 奖杯→物品表在**本地** datapack，服务器只给槽位编号 | 奖杯发放不需要服务端加东西（除非要做"奖励可配"） |
| E11 | `h_liveevents_find_opponent` 目前回 `_robot_opponent(weekly_track_id)` 的机器人名；`WeeklyChallengeManager::{requestOpponentEv @0x00631748, validateOpponentEv @0x006320a4, invalidateOpponentEv @0x006309c4, onGhostQuery/onGhostReceived}` + 日志里的 `GET /public/userstorage/v2/search/ghost/get_pvp_ghost` | 「Next Challenger」= `find_opponent` 给的名字 + 该名字的**幽灵**（走 userstorage 幽灵查询）；名字必须是幽灵库能解析的身份 | 让 `find_opponent` 回**榜上真实 pid**（也就是 `_opponent_entries()` 已经折出来的 `44444444/55555555/66666666`，它们的 pid→contentId 映射已建好），"挑战这些人"才成立 |
| E12 | 侧发现：`server/tf_server.py` 的 `GLOBAL_LEADERBOARDS = {"global_stats","global_stats_donkey"}` **缺 `global_stats_crazy`**（E1 证明第三个总榜存在） | 该榜会被当成普通 track 榜聚合/落库，且对它的成绩上报会命中 `400 invalid-track` | 顺手补进集合（独立小修，不在午夜杯主线上） |
| E13 | 死路记录：`callers.py 0x509604` 对 `getLeaderboardName` 返回 0 个调用点（只经函数指针/内联）；`getUserSavePercentageEv @0x00636048` 其实是 `PlayerItems::getItemCount(0x24,1)>>16 / 100.0f`，是**存档完成度**，**不是**榜百分位 | 两条弯路都排除了：榜名不靠 callers 找；Top1% 不看 item 0x24 | 后续别再从这两处下手 |

---

## 2. 现状 vs pvp.png（目标 UI）对照

| pvp.png 元素 | 客户端来源 | 服务端现状 |
|---|---|---|
| 标题 MIDNIGHT CIRCUIT / 当周名 X-Factor | `MenuzStateWeeklyChallenge`（本地 loc + 配置） | 无需服务端 |
| 左上 Next Challenger + 头像 | `find_opponent` → `{"opponent": name, "replay_id": int}` | ⚠ 回的是机器人名，不是榜上人 |
| 倒计时 02:12:12:34 | `basic_info` 的 `midnight_circuit_start_time/end_time`（按周钉死） | ✅ 已正确 |
| GLOBAL / 好友 两个页签 | 同一个榜名，`?around=<pid>,20` / `?players=<pid,…>` | ✅ 端点已有，但榜名恒为 `global_stats` |
| TOTAL PLAYERS: 52985 | `ranking` 响应的 `playerCount` | ✅ 已回全榜人数 |
| 行：名次/名字/徽章/国旗/0/时间 | `results[].{rank,player,stats{...}}`（drivetime 毫秒） | ✅ 形状已对（缺国旗/徽章来源，属外观） |
| 自己那行高亮（284 Sandholm） | `getPlayerLBData`（榜里要有**自己**的行） | ⚠ 取决于榜选得对不对 |
| 底部 TOP 1% 条 | `getPlayerRankPercent()` → 名次/行数 | ⚠ 现在恒 -1（wood） |
| 周结束敲奖杯 | `giveWeeklyReward → getPlayerTrophyType → calculateReward` + `reward_config` | ✅ 规则在客户端；奖杯编号映射已对 |

---

## 3. 建议的最小落地方案（待讨论确认后再动手）

1. `server/data/tf_config.json` 新增 `weekly.leaderboard_id`（默认 = 本周赛道 id，`-1`/缺省 = 自动取 `weekly.track_id`），
   `h_liveevents_config` 把它塞进 `week_settings.week_leaderboard`。
   理由（ponytail：复用已有真实数据，不造新表）：赛道规则原文「每个人在午夜杯的赛道都是一样的…每周的挑战都是全球性」
   ⇒ 榜 = **本周赛道的全球榜**，服务端已经有该榜的真实行（玩家 + 3 个内置幽灵对手），`getLeaderboardName(id)=track<id>` 天然命中，
   且自己的行一定在榜里 ⇒ Top 1%/奖杯链路自动生效。
   备选：`event_stats1..7`（活动榜，属活动系统的"每腿一榜"，见 E1 的字段描述 `Weekly_Leaderboard_Missions`）——语义更"官方"，
   但需要新增一个只装午夜杯成绩的榜，而成绩从哪来（E9：没有 playerstats 提交）尚未打通。
2. `h_liveevents_find_opponent`：改成从**本周赛道榜**里挑对手（优先挑比玩家快的最近一名 = "Next Challenger"），
   返回的 `opponent` 用榜上的 `player`（pid），从而与幽灵库/幽灵查询打通；没有对手时回落到现在的机器人。
3. 补 `global_stats_crazy` 进 `GLOBAL_LEADERBOARDS`（E12）。
4. 回归测试进 `tests/test_pvp_economy.py`：`week_leaderboard` 命中配置值、`find_opponent` 回榜上 pid、
   `ranking/track<id>` 含自己那一行、`global_stats_crazy` 走聚合而不是 `invalid-track`。

## 4. 待验证实验（必须在真机上做，服务端无法自证）

A. 把 `week_leaderboard` 设成本周赛道 id（如 1041），重启服务端 → 进午夜杯 → 看日志是否出现
   `GET /public/playerstats/v1/ranking/track1041?around=<pid>,20` 与 `?players=…`（**若出现即证明 id→榜名链路完全打通**）。
B. 同一屏看 UI：榜行是否显示（名次/名字/时间）、底部 TOP 1% 条是否动、自己那行是否高亮。
C. 跑一局 → 确认 `start_race`/`end_race` 之外是否出现成绩上报（E9），以及榜上时间是否更新。
D. 周结算路径：把 `basic_info` 的 `week_start/weeK_end` 临时拨到"已结束"，看是否出现敲奖杯画面（奖杯档由百分位决定）。

## 5. 待讨论（阻塞实施）

- Q1 `week_leaderboard` 取值：本周赛道 id（推荐）/ `event_stats<N>` / 保持 0。
- Q2 全球榜里的"别人"：沿用现有 3 个内置幽灵对手（`44444444 GhostRider`、`55555555 TangoPro`、`66666666 IronGear`）
  够不够？要不要多造些对手让 TOP 1% 有意义（人数、名字、时间分布）？
- Q3 「挑战这些人」：点榜上某人就下他的幽灵（要求 `find_opponent` 回 pid）——这个方向对不对？
- Q4 午夜杯次数/冷却（`left_retry_times`、`global_cooldown_time`、`skip_cooldown`、`refill_retry_count`）要不要按规则补？
  现状：`left_retry_times=3`、冷却 0、refill 桩回 `{"data":[]}`。
- Q5 先做实验 A/B（改一个配置值 + 重启 + 真机看一眼）还是先把改动一次做全？

---

## 6. 落地记录（2026-10-05 22:00–23:50，真机逐项验证）

### 6.1 让客户端走出「加入午夜杯！」那一屏（根因）
`week_settings.week_leaderboard` 原为写死的 `0` ⇒ 客户端 `hasLeaderboard()`/`getPlayerRankPercent()` 直接判空。
改成配置项 `weekly.leaderboard_id`（0 = 自动 = 本周赛道 id ⇒ `track<id>` 榜，复用已有的真实行）。
追加：`basic_info` 的 `(last_participated_week, last_participated_week_lb)` 在**玩家本周榜上有名**时报
`(本周周号, 本周榜 id)`（`_weekly_joined()`）—— 否则 `updateStateEv` 永远给 state 2（= UI 3 = `loadJoinState`），
按下按钮直接开赛、跑完又回到同一屏。真机 23:26 冷启后客户端立刻开始拉
`config/0 → reward_config/2961 → ranking/track1041?around= → find_opponent → stats/track1041 → ghost/<id>/payload`，
即进入了"已加入"那一屏。

### 6.2 Next Challenger 必须是 pid + 幽灵 contentId
`find_opponent` 原先回**显示名**（`_robot_opponent`）且 `replay_id: 0` ⇒ 客户端拿显示名去查
`stats/track1041?players=TangoPro`（服务端按 profileId 存行）永远查不到，并以 **~30 次/秒** 死循环重试
`find_opponent` + `stats` + `ghost/0/payload`(404)。
现在 `_weekly_opponent()` 从 `_opponent_entries()` 里挑一个"本周榜上有行、且这条赛道有内置幽灵"的对手，
回 `{"opponent": "<pid>", "replay_id": <contentId>}`（1041 实测 `44444444-…` / `replay_id=2`）。
修复后同样一段操作只发 3 次请求、`ghost/2/payload` 200。

### 6.3 本周榜单的"其他玩家"：合成行
`weekly.fake_field`（数量，0 = 关）+ `fake_field_base_ms`（0 = 自动 = 这条赛道最快的内置幽灵）
+ `fake_field_fast_pct`（默认 3）+ `fake_field_slow_pct`（默认 25）。三条硬约束：**不落盘**（`leaderboards.json` 只有真实行）、
**不进总榜**（`_aggregate_global_entries` 跳过 `_WEEKLY_FAKE_PIDS`）、**同周内恒定**（种子 = 周号 + 赛道）。
1041 实测：基准 25656ms ⇒ 合成行 24973~32070ms；玩家 24.368s ⇒ **rank 1/123 = 0.81% = TOP 1%**。
基准刻意**不取玩家自己的成绩**，否则他一进步整个榜跟着变（永远差一点）。

### 6.4 每周次数：服务端权威
`start_race` 扣一次、`skip_cooldown` 补满、`refill_retry_count` 按客户端报的 `retry_times` 加（夹 1..9）；
`basic_info.left_retry_times` 回真实剩余、`last_attempt_time` 回最后一次；冷却**时长**是 config 里的 `global_cooldown_time`
（默认 3600s，规则），每周上限 `left_retry_times`（默认 3）。
`ponytail:` 次数只在内存里（`_WEEKLY_ATTEMPTS`），重启服务器会白送满次数。

### 6.5 appcfg 不再发回环地址（"插线才能玩"的根）
`sandboxes[].url` 是 Java/DLC 的 base，Ubi SDK 所在的 `libplayground.so` 只认编译期写死的
`http://127.0.0.1:8000/{version}`。以前 Host 原样回显 ⇒ 只要有一次请求从回环进来，Java/SDK 就被钉死在 127.0.0.1，
必须 `adb reverse`（用户 2026-10-05 明确不要）。现在 `_public_host()` 把
`127.0.0.1/localhost/::1/0.0.0.0` 换成局域网 IP（`_lan_ip()` 自动探测，`appcfg.public_host` 可写死）。
真机验证：撤掉 `adb reverse` 后设备从 Wi-Fi 打 200、从回环打 000，冷启 22 个请求 100% 走 `192.168.5.2`。
⚠ 前提仍有一条改不掉：`tf_server.txt` 第一行必须是 PC 的局域网 IP（原生侧启动时读它改写 URL）。

### 6.6 事实澄清：榜是"每人每周最好成绩"，客户端只在新 PB 时才上传
真机 23:45:38 那局 24.368s ⇒ `POST /public/resultservice/v1/enhancestats/track1041` 成功、榜行从 24404 更新到 24368；
23:47:39 那局只有 `end_race`、**没有** `enhancestats` 请求 —— 客户端本地判定"不是新纪录"就不上传。
所以"记录上传不进去"通常是跑得比本周最好成绩慢，不是服务端问题。
（成绩入口：`h_result_stats` 只收 `track[0-9]+`，同一赛道只保留更小的 drivetime。）

### 6.7 未提交 & 遗留
本批（6.1–6.5 + 6 项测试，共 41 项全绿）**尚未 commit**。
遗留：`match_duration_seconds` 测试期设的 300 要还原 21600；碉堡两个老问题（真人对手显示名、`match_loser_keeps_pct` 取 50 还是 100）。
