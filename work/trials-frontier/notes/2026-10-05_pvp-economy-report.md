# 2026-10-05 碉堡奖励与货币结算修复

**范围：路线图第三条的一批实质修复，不是第三条全部完成。21 项隔离回归通过；尚未部署或验证真机到账。** 金票基础价格已支持，套装折扣/商店缓存旧价格仍会被拒绝，不能称购买链全部闭环。

## 范围与证据

沿用 [授权范围](<../scope.md>)：granted / lab_only。本轮只读本地 APK 派生产物、修改项目代码并跑临时回环 HTTP，不访问官方服务、不操作手机、不修改真实玩家存档。主路线 R1 APK，lead + cre/cae/doc。技能包实际位于 `F:\Code\reverse-skill`；工具索引未生成，按 PATH 实测，不运行需单独批准的包脚本、不安装依赖。报告类型为普通逆向（flavor=null）。

| Evidence | source_ref / repro_command | content_hash |
|---|---|---|
| E-PVP-NATIVE | [原生契约笔记](<pvp-reward-contract.md>)；`python tools/re/disasm.py tmp/libcmp/orig-libTrialsGo.so 0x4fa87c 0x200`（需本地已有 Capstone/pyelftools，与笔记样本相同） | 样本 SHA256 `743F945CD7E3378DBF78EADC9D864DE0C465B558BDA8A54923B46A8F170FB7F4` |
| E-PVP-RED | 初始隔离回归：6/6失败，0.032s；奖池725/4/2刷新成150/1/0、1801s对局消失、重启丢对局、提前结算、扣票时机错误、季奖形状错误 | n/a，命令观察 |
| E-PVP-GREEN | [可运行回归](<../../../tests/test_pvp_economy.py>)：`python -m unittest discover -s tests -v`；[本轮结果](<../../../tmp/pvp-test-results.txt>)：21/21通过，0.754s，含临时真实HTTP链 | n/a，可复跑 |

## Findings

全部 location 为 [服务端实现](<../../../server/tf_server.py>) 中列明的函数；`status=validated` **仅指源码/隔离服务端层**，不代表真机结果。置信度 high，severity n/a_re。

| Finding | 根因 → 本次改动 | Evidence |
|---|---|---|
| F-PVP-POOL | `h_pvp_increase_rewards`：原实现只记reward_data，丢coin/gem/special；现按真实race累加共享奖池、去除重试时间戳差异影响、持久保存并返回总量。race_id=0只接受零增量进度同步，这是本地验证策略 | E-PVP-NATIVE, E-PVP-RED, E-PVP-GREEN |
| F-PVP-CLOSE | `h_pvp_close`：缺失真正的POST `/close`，客户端拿不到winner而不能走胜者本地发奖分支；现校验期限/参与者、返回winner与换主次数、一次结算筹码/段位、保存领取回执并隐藏已领取对局 | E-PVP-NATIVE, E-PVP-GREEN |
| F-PVP-LIFE | `_pvp_prune` / `_pvp_state_save`：6小时局错误使用30分钟队列TTL、重启只恢复筹码/票；现对局/成绩/奖池/领取状态同文件持久化、结果上报不提前结算、未知比赛不伪造 | E-PVP-RED, E-PVP-GREEN |
| F-PVP-CURRENCY | `h_pvp_chips` / `h_pvp_start_race`：原来不认识use_chips、start只回200；现校验余额并原子扣筹码，每局免费票在start消耗，金票另记账号余额。基础票价购买按num×price扣筹码并增票 | E-PVP-NATIVE, E-PVP-GREEN |
| F-PVP-SEASON | `_pvp_season_rewards` / `h_pvp_close_season`：季奖wire需26档嵌套结构，特殊物品用145+RewardID；修复稳定赛季id/期限、历史段位保留、Legend与连胜/掉星显示规则 | E-PVP-NATIVE, E-PVP-GREEN |

服务端**不直接追加角色金币、宝石、普通商店物品**：客户端的成功回调已经负责发放，并随后通过现有存档同步上报。否则会双发。

## P-PVP-REWARD（path_type=callflow）

1. `new_ranked → matches → start_race`：确定对局/玩家，持久扣每局免费票或账号金票。E-PVP-NATIVE / F-PVP-CURRENCY。
2. `race → increase_rewards → matches/<id>`：保存真实成绩、生成race_id、确认增量奖池、返回总量快照。E-PVP-NATIVE / F-PVP-POOL。
3. 六小时到期 `close`：服务端原子结算筹码与排名、记录per-player回执、返回胜者。E-PVP-GREEN / F-PVP-CLOSE。
4. 客户端 `onMatchEndSent → PlayerItems::add / giveSpecialReward → progress`：发本地金币宝石并上传存档。最后这段只有静态证据，**待真机验证**。E-PVP-NATIVE。

## 验证及上线

```powershell
python -m unittest discover -s tests -v
python -m py_compile server/tf_server.py tests/test_pvp_economy.py
```

所有测试写入临时目录，HTTP测试只监听回环随机端口且结束后关闭。覆盖重启恢复、过早/重复领取、失效凭据、跨账号访问、并发不足余额、模拟磁盘写入失败503+回滚、奖励重放、免费票恢复、金票、升传奇及掉星保护。原始6项红回归已转绿；新增无race奖励漏洞也先红后绿。

尚未重启现有服务、更新发布目录或重新打APK。源码运行入口仍为 `python server/tf_server.py --host 0.0.0.0 --port 8000`；先备份运行期数据，在维护窗口停旧进程再启动，不要双进程同时写同一个状态文件。旧的筹码/票文件可读；旧版本未持久化的比赛和奖励不能凭空恢复。

## 未闭环与下一步

- **真机到账**：需单局转盘累计→六小时结束→领取→金币/宝石/筹码变化→重登存档；服务器测试不能替代它。重复成功回包也不自动保证客户端exactly-once。
- **套装折扣票价**：原生确有折扣并先舍入总价再整除数量，严格基价校验不支持它。当前拒绝不匹配价格而非任意信任请求；下一步重建拥有的type9套装与倍率、覆盖缓存旧价流程。
- **无事务ID的购物/开赛**：chips仅use_chips无商品/操作ID，连续同额消费与网络重放不可区分；同赛道未完赛start目前按重试。不能声称全部货币操作exactly-once。
- **多槽/赛季规则**：当前匹配仍按单个活跃局去重；跨季未结对局、历史各季数值快照、Elo、平局/连胜历史规则未完整还原。失败清连胜及季后回25为私服策略。
- **其余第三条功能**：午夜杯次数/冷却/奖励实领、礼物真实发送领取、活动及礼包条件并未在本轮补齐。旧200响应/不崩溃不能作经济功能完成证据。
- **存储边界**：单进程锁+单JSON原子替换；已结赛回执暂保留，随数据增长需要清理策略或SQLite。并非多进程事务系统。

## 时间线与可复用经验（本项目 journal）

2026-10-05：核对历史scope/路线图 → 6红测试 → 并行native契约核查/源码根因修复 → 独立边界审查 → 21绿测试。参见 [时间线](<../timeline.md>) 与 [工作项](<../workitems.md>)。

1. “客户端不解析回包”不等于服务端不用记账；沿成功回调确认谁发物品。
2. 同一个奖励在请求里是增量、刷新里是快照；重试收据不要包含可变化的时间戳。
3. 奖品RewardID、库存ItemId、特殊等级是三个不同空间；界面能进/HTTP200均不能证明到账。
