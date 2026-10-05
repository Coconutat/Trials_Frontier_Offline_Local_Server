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
