# Timeline (append-only)

## 2026-10-03T13:08:41.5275608+08:00 | lead | init
- action: case-init
- command_or_ref: skills/scripts/case-init.ps1
- result_summary: case directory created; scope ready_for_act=true
- artifacts: [scope.md, workitems.md]
- evidence_ids: []
- decision_delta: [case_initialized]
- carry_forward_refs: [scope.md]
- next: open PRIMARY SKILL.md and ACT within scope

## 2026-10-05T14:01:00+08:00 | lead/cre/cae | PVP economic repair
- action: continue ROADMAP item 3; read native contracts, reproduce missing settlement, implement and independently review
- command_or_ref: `python -m unittest discover -s tests -v`
- result_summary: initial 6/6 failed; expanded 21/21 passed, including isolated localhost HTTP. No device/production deployment or player-save writes.
- artifacts: [native contracts](<notes/pvp-reward-contract.md>), [repair report](<notes/2026-10-05_pvp-economy-report.md>)
- evidence_ids: [E-PVP-NATIVE, E-PVP-RED, E-PVP-GREEN]
- decision_delta: actual /close route; shared reward deltas; client owns ordinary currency grant; server owns PVP balances/receipts; withdraw historical 95% claim
- carry_forward_refs: [scope](<scope.md>), [workitems](<workitems.md>)
- next: device receipt/persistence validation; outfit-discount pricing and remaining roadmap-3 business flows
## 2026-10-05T21:30:00+08:00 | lead/cre/cae | 碉堡身份稳定 + 启动期端点 + 经济契约回归
- action: 复盘真机日志（7360 行）定位「面板转圈 + 时好时坏」；按用户指定优先级（启动/身份 → 硬 bug → 减法 → 季奖+测试 → 商店）修复并补测试
- command_or_ref: `python -m unittest discover -s tests`；`python tmp/smoke_bunker_http.py`
- result_summary: 身份轮盘（无 Authorization 1737 条 + 匿名票 1489 条把 PVP 状态劈成两槽）已修；`GET /`(gamecfg)+`register_device` 按真实样本实现；字符串 track 回归、季奖重复/缺档、114514/500 调试值、金票折扣价、状态膨胀全部处理；29/29 测试绿，真 HTTP 碉堡四面板全 200
- artifacts: [本批报告](<notes/2026-10-05_bunker-identity-and-boot.md>), [真机日志](<notes/server-log.jsonl>), [契约笔记](<notes/pvp-reward-contract.md>)
- evidence_ids: [E-BOOT-LOG, E-NONE-PVP, E-ID-MIX, E-401, E-GAMECFG-REAL, E-CHIPSTORE-OBB, E-DISCOUNT, E-GREEN, E-SMOKE]
- decision_delta: 身份按「客户端 IP + device_id」绑定（明确口令错误不洗白）；筹码模型以「按赛道产币 + 赢家夺输家 (100-keep)%」为准（撤回 test_abc_* 的 0 起点/无挂机产出断言）；季奖必须是全 26 档的扁平可编辑表（WebUI 模板）；金票价格上界由服务端价表钉死、下界允许客户端折扣
- carry_forward_refs: [scope](<scope.md>), [workitems](<workitems.md>)
- next: 真机验证四面板与完整对局；register_device/dlcontent/loc.json/News 四个启动期桩待用户判定是否需要真响应
## 2026-10-06T00:40:00+08:00 | lead/cre/cae | 午夜杯落地：榜单 id → 已参加 state → Next Challenger → 合成榜 → 服务端次数 → 奖励轮转
- action: 按用户「先分析 → 讨论 → 动手」的节奏，把午夜杯（= 周赛 `liveevents/v1/weekly_track_system`）从"每次进去只能加入"做到可打、可上榜、可结算领奖；每一步先反汇编取证、再真机验证
- command_or_ref: `python -m unittest discover -s tests`（49 项全绿）；`python tools/wts_reward_doc.py`；adb 截图与 `notes/server-log.jsonl` 逐条对照
- result_summary: ①`week_settings.week_leaderboard` 恒发 0 = 客户端认定"没有榜"（榜区空白 + TOP 1% 条 + 周奖杯一起退化）→ 改为按本周赛道 id；②`basic_info` 的 `(last_participated_week, lb)` 恒 0 让客户端永远停在「加入午夜杯！」那一屏 → 改为报"实际参加过的那一周 + 那个榜"；③`find_opponent` 回显示名 + `replay_id=0` 导致 ~30 次/秒死循环（`stats?players=<名>` 查不到 + `ghost/0/payload` 404）→ 改回 pid + 该 pid 在本周赛道的幽灵 contentId；④榜上只有 3 人、最好也只是"前 34%" → 合成 120 个对手（不落盘 / 不进总榜 / 同周恒定），现为 rank 1/123 = 0.81% = 前 1%；⑤每周次数改服务端权威（`start_race` 扣、`skip_cooldown` 补满、`refill_retry_count` 加）；⑥appcfg 的 sandbox url 绝不发回环地址（否则 Java/DLC 与 Ubi SDK 被钉死在 127.0.0.1、必须插线）；⑦"奖励永远同一件"的根因 = 客户端挑池内物品用的是**它不播种的 `rand()`** → 服务端每次轮转池子，并给出 `reward_slots`(1..8) / `reward_ids`；⑧新增"模拟翻周"`week_offset` 与"按请求的那一周回 config"，真机跑通结算/领奖（截图：「前 1%」+「领取奖励！」）
- artifacts: [午夜杯逆向笔记](<notes/2026-10-05_midnight-circuit.md>), [奖励池对照表](<notes/weekly-reward-pools.md>), [奖池摘要（WebUI 用）](<../../server/data/wts_rewards.json>)
- evidence_ids: [E-WLB-ID, E-STATE-34, E-OPP-PID, E-FAKE-FIELD, E-ATTEMPTS, E-APPCFG-LOOPBACK, E-RAND-UNSEEDED, E-REWARD-ROTATE, E-WEEKOFFSET, E-GREEN49]
- decision_delta: 午夜杯榜 = 本周赛道榜（`weekly.leaderboard_id` 可换）；合成对手只做展示层、绝不进总榜；奖励**只能换池子**、不能改内容或数量（内容在客户端 `/conf/wts_rewards.txt`，喷漆/蓝图/皮肤不在其中 —— 15 池全扫零命中）；每周次数只在内存（`ponytail:` 重启满血）
- carry_forward_refs: [scope](<scope.md>), [workitems](<workitems.md>)
- next: `week_offset` 验完调回 0；`reward_ids` 终稿由用户定；想要喷漆/蓝图或任意数量需另开"服务端塞存档"一轮；碉堡遗留 4 小项（对手显示名 / `match_loser_keeps_pct` / 卡住的 match 3 / `match_duration_seconds` 还原）
