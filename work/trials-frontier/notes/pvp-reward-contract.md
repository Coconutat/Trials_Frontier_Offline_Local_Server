# PVP 奖励原生契约核查（只读）

## 范围与结论
- 依据 [scope](../scope.md) 的 granted / lab_only；仅分析已有本地材料。**本轮无真机、无联网、无动态抓包；不把历史“完成率”当证据。** 未修改服务端源码、APK或玩家数据。
- 样本：[orig-libTrialsGo.so](../../../tmp/libcmp/orig-libTrialsGo.so)，AArch64，SHA256 `743F945CD7E3378DBF78EADC9D864DE0C465B558BDA8A54923B46A8F170FB7F4`。下文 `@` 为该样本虚拟地址；本次代码/只读字符串段 VA=文件偏移，不能推广到全部段。
- 方法：先读 [旧报告](../../../tmp/PVP_CHIPS_REPORT.md)、[match原表](../../../tmp/pvp_match_rewards.txt)、[chip店原表](../../../tmp/pvp_chip_store.txt)，再用已读的 [disasm.py](../../../tools/re/disasm.py) / [syms.py](../../../tools/re/syms.py) 和本机 Capstone/pyelftools 静态交叉核查。未运行 reverse-skill 包脚本。
- **金币/宝石/普通商品由客户端发入 PlayerItems；服务端持久化 PVP 比赛状态、筹码、金票、rank/star/streak。不能在成功回包之外再给一份金币宝石。** 服务端幂等不等于未经改造客户端的端到端 exactly-once。

## 1. Evidence → Finding → Path：match 奖池与结算

| Evidence | Finding | 最小服务端路径 |
|---|---|---|
| `OnlinePVP::parseMatch @0x4fd9d0`；`@0x4fdd60` 取 rewards 前三整数，`@0x4fe1d4` 重建 match+0x170 | wire `rewards:[coins,gems,specialLevel]` 是**单个 match 奖池快照**，没有每 pid 奖池分支 | 用共享 match pool 持久化；对双方查询返回同一池，而非按 pid 分裂 |
| increase 请求模板 `@0xb8672d`；匿名成功 callback `@0x5e8dfc`（vtable `0xdda8d8`）调用 `increaseCoins/Gems/SpecialLevel @0x5e8e98/0x5e8ea4/0x5e8eb0` | `coin/gem/special` 是**增量**；`reward_data` 在 `@0x5e8e8c` 覆盖 match+0x1b8；成功后 race_id 清零 `@0x5e8eb4`。增加接口回包不是奖池刷新输入 | 原子累加三项并覆盖 reward_data；refresh 回总量；重试去重不能把合法第二次增量吞掉 |
| `OnlinePVP::endMatch @0x4fa87c`，URL串 `@0xb86677` | 真正路由是 `/public/pvp_matches/v1/close`，不是 `/end_match` | finish_match 内部实现应绑定实际 close 路由 |
| `parseJsonResponse @0x4fc484`，请求type `0x2f` | close 只提取 `last_match_winner` 字符串与 `ownership_changes` 整数。winner==当前pid→result0；缺 winner→1；其他 winner→2 | 从持久比赛结果生成，勿用固定当前pid作为winner |
| `PVPManager::onMatchEndSent @0x5e776c`；`@0x5e78d4` 非0跳过物品池，胜利遍历 pair；`PlayerItems::add @0x5e7c14` 的 w1=item_id、w3=amount；特殊奖 `giveSpecialReward @0x5e7ce0` | **胜利客户端本地发金币、宝石和特殊奖**；非胜利不走同一物品池发奖。`@0x5e80a0/0x5e80e0` 是 item136/137统计，不是钱 | close 只结算/持久化 PVP 服务端归属和筹码，不再次把池内币加入角色存档 |
| `markRewardsCollected(int) @0x5e1a9c`，调用 `@0x5e7e58`；成功末段移除本地 match | 客户端有近期已领奖ID记录（阈值51），但本 callback 内未见先检查该集合的幂等保护 | 服务端需 per-pid close receipt、不会重新展示已关闭比赛；不能宣称仅靠重复成功回包即可保证客户端恰好发一次 |

精确请求模板：
```text
POST /public/pvp_matches/v1/increase_rewards
{"race_id":%d,"match_id":%d, "coin":%d,"gem":%d,"special":%d,"reward_data":%d,%s}
# 末尾 %s 为附加 checksum 字段片段。

POST /public/pvp_matches/v1/close
{"match_id":%d,"create_new": "%s","ticket": "%s","outfit": %d,"param": %d }
# 两个布尔串是 "True" / "False"；param=extraMatchSlots XOR 0xa39cd9f6。
```
`requestEndMatch @0x5e1c7c` 调 `getPVPExtraMatchSlots()`；`endMatch @0x4fa97c` XOR，故 param 不是金额/票数。

**race_id=0 边界（追加核查）：** `checkMatchSpecialReward @0x5e3fcc-0x5e3fd8`、`validateMatches @0x5e3ef8-0x5e3f04`、`onMatchReceived @0x5e45fc-0x5e4608` 均提交 `coin=gem=special=race_id=0`、仅更新 reward_data。但 `increaseMatchRewards @0x5e2ff4-0x5e3038` 在输入 delta<=0 时也设 race_id0，type1/2仍可透传负币量；未发现其正常UI调用传负币量。因此限制 id0 仅零货币/特殊ID刷新可以是服务端验证策略，**不是已证明的全客户端不变量**；正增量应绑定已知非零race，并考虑奖励成功后客户端会清race_id。

**筹码倍率（确定 / 不可证）：**
- 确定：成功且 result0 时取 `getPlayerChips(0,-1)` 原值（`@0x5e7d40-0x5e7d50`）；result!=0 时取 `int(float(chips)*0.5+0.5)`（`@0x5e78d4-0x5e78fc`），非负数为四舍五入半额。对本地统计/任务链成立，不是金币宝石半奖。
- 不可证：历史真实服务器如何落账、平局/断线最终判定以及所有跨重试时序；本轮没有服务器历史样本或真机闭环。服务端不能先对同一值减半后又套客户端公式二次减半。

## 2. Evidence → Finding → Path：chip 店与金票

| Evidence | Finding | 最小服务端路径 |
|---|---|---|
| `OnlinePVP::spendChips @0x4fb1f8`；模板 `@0xb867c0` | `POST /public/pvp_matches/v1/chips` body **`{"use_chips":N}`**，没有商品ID。解析 `@0x4fc5a8` 读 `chips` | 校验/原子扣余额，回 `{"chips":余额}`；不能据请求猜商品再给币 |
| `onChipsSpent @0x5e6fdc`，错误分支直接提示；成功 `@0x5e7068` 写 manager+0x138；pending商品 `giveSpecialReward @0x5e7108`，随后清pending | 收到成功才在客户端给 pending StoreItem/WheelReward；Type0 ItemId135 特地跳过 `@0x5e70e8-0x5e70f8` | 普通 chip 商品由客户端发，服务端只扣筹码；需要承认无请求ID的通用扣费重放边界 |
| `purchaseChipstoreItem @0x5e6e1c`：总价/数量→单价；`purchaseGoldenTickets @0x4fb3b0`，GET调用 `@0x4fb4c4` | `GET /public/pvp_matches/v1/purchase_tickets?num=N&price=P&checksum=S`，**price为单价**；回 `chips`、`golden_ticket` 两个余额 | 原子扣 N×P 筹码、增 N 金票，校验服务端价表而非相信任意客户端价格 |
| `onGoldenTicketsPurchased @0x5e7320` 写 manager+0x134，再走 onChipsSpent | 金票不是普通本地库存商品重复发放；回包是余额不是增量 | 统一服务端票余额 |
| `onStartRaceSent @0x5e5750-0x5e5760`：golden标志真时 manager+0x134 减1 | 成功开赛会减本地镜像；不是服务端可不扣票的理由 | `start_race` 成功时持久扣票一次；不要在创建match时提前扣，否则双扣/刷新返还 |

原价表例子：[chip店原表:361–465](../../../tmp/pvp_chip_store.txt#L361-L465)：金币50000/20000/10000/5000→筹码4000/2000/1100/650；宝石5→1000筹码；金票3/5/10的价格依服务器 chip_shop 配置。

**价格更正（追加核查）：** `parseSeason @0x4fd2a0-0x4fd318` 对 `product_id==chip_shop.goldentickets` 将 ItemId135 的 `WheelReward+0x28总价 = +0x14数量 × product.amount`；旧报告把另一普通 product_id 分支的 `setItemCount(amount) @0x4fd3a4` 混入了此分支。`amount` 确为**单张基价**，不是包数量。UI `@0x6451f4-0x645214` 对票也应用服装折扣：`total=int(float(num*amount)*multiplier+0.5)`；购买 `@0x648164/0x6482cc` 传此总价，`@0x5e6e1c` 整除数量得到 query.price。因此**无折扣时 price==amount，有折扣时不保证相等**，不可用无条件等值校验拒绝合法折扣。`getCurrentPVPChipStorePriceMultiplier @0x582040` 对拥有三件的 type9 套装逐项乘系数。原表每包 ItemValue3000 是未覆盖的包总价；无覆盖/无折扣时3/5/10票对应 query.price1000/600/300。服务端应按有效配置与持有套装验证，不接受任意客户端报价。

## 3. Evidence → Finding → Path：赛季奖励和 rollover
- `parseSeasonData @0x4fe4f4` 需要 **nested**：`current_season.rewards:[{"rank":N,"rewards":[{"item_id":X,"amount":Y}]}]`，不是扁平数组。
- `getCombinedSeasonRewards(int) @0x5e7364` 检查 vector 总字节 `0x270`（26×0x18）；`@0x5e73dc-0x5e7490` 对所有 **index>=最终rank R** 累加金币/宝石，并带出 type145特殊奖。因此提供 rank0..25完整26档；金额是每档增量，不是累计总额。
- coin/gem pair 的 item_id 是1/2；特殊季奖应为 `item_id:145, amount:RewardID`。`@0x5e7430` 只收145，`setupRewards @0x735574-0x73557c` 把 pair.amount 传 `getSpecialRewardById`，不是把 RewardID 当库存ItemId。
- `OnlinePVP::closeSeason @0x4fb994` 实际 **`POST /public/pvp_matches/v1/close_season` body `{}`**（串 `@0xb868ca/0xb85588`）；签名的 int 参数没有发出去。response `rank/star` 解析 `@0x4fc638`。
- `MenuzStatePVPPostSeason::onEndSeasonRequestCompleted @0x735d68` 成功后进入动画链；`onAnimationFinished @0x7341f0` 发特殊奖，`@0x734218` 调 PlayerItems::add，source串为 `PVPSeasonRewards`。**季奖金币/宝石也是客户端发。**
- 服务端建议：按(pid,旧season)持久 close receipt 与 next rank/star；保留可供旧季展示/结算的配置，不要抢先全局删除；返回新rank/star但不重复入普通货币。由于请求无season字段，必须由服务端pending状态识别待关闭旧季，不能每次请求无限 rollover。

## 4. 排位：确定规则与不可证边界
**确定（静态客户端行为，不冒充历史服务器规则）：**
1. **rank0=Legend**。`initLegendsLeaderboards @0x721618-0x721624` 对 manager.rank==0 按 elo_rank 定位；`toRankUnknownState @0x727158` 写 **-1**，未揭示另有独立flag，不能混用0。
2. `getNewRankAfterGettingOneStar(int rank,int star) @0x5e859c`：rank0→(0,0)；非0时，若**旧star==cap[rank]**→(rank-1,1)，否则→(rank,star+1)。`getStarCountForRank @0x5e16e8` 读配置数组。即 rank1满星之后再赢升0，不能 clamp到1；别把条件偷换成增加后 `>=cap`。
3. `onMatchEndSent` 本体不更新 manager 的 rank/star/win_streak。`onPlayerRankingReceived @0x5e7648-0x5e7664` 复制服务端 PVPPlayerData；`parseRankingData @0x4fc918` 映射 rank+0、star+4、elo/elo_rank+8、season+12、golden_ticket+16、chips+20、win_streak+24。
4. UI `PostMatch.activate @0x731634-0x731654` 复制manager到本地动画状态；`@0x731658-0x731670` **旧win_streak>=2且本场胜**置bonus。`startRankAnim @0x7307cc` 先加一星，再 timer7→`@0x73035c/0x730360` 加一星。因此第三连胜起预演加2星（rank0直接不再加）。
5. 失败动画 `startRankAnim @0x73080c-0x730870`：rank20..25不掉星；rank15..19减1且最低0、不掉rank；rank1..14减1，若旧star==0则 rank+1、star=cap[newrank]-1；rank0不掉rank。无owner结果不做此失败分支。

**不可证 / 不应伪造：** 原服务器 Elo算法、胜负/平局对 win_streak 的完整历史规则、所有保护档是否与当前远端配置一致。本轮能证明“客户端预测UI + 服务端ranking覆盖”，不能证明客户端替服务器持久推进。离线实现可据以上预测规则保持显示一致；输后清 streak 是服务端设计选择，不能标成此回调里已观察到的写操作。

## 5. 原表ID与special范围
- [match原表:1–56](../../../tmp/pvp_match_rewards.txt#L1-L56)：RewardID100→ItemId145；RewardID1/2/3/4→ItemId1（金币），RewardID5→ItemId2（宝石）。**RewardID≠ItemId**。
- [match原表:3633–3670](../../../tmp/pvp_match_rewards.txt#L3633-L3670)：SpecialRewardLevel离散值 **0,1,2,3.9,4,6,100**；最大 **100** 对应 Donkey Blueprint RewardID220；2→202，3.9→203。不能把6当最大等级；表里comment Tier名称与ItemId实际tier并非总一致，按ID核对。
- [match原表:3671–3697](../../../tmp/pvp_match_rewards.txt#L3671-L3697)：MissingRewardFallbackRewards按rank1..25配置；兜底候选不是金币/宝石无条件加发。
- 旧报告的 `pow(t,x)*y` 若x=0得到恒定**总量**，不是恒定速率；欲线性累计应x=1、y=每秒速率。此处修正数学解释，不改旧报告或线上配置。

## 5b. ★ 赛季特殊奖只有 43 个编号可用（2026-10-06 追加，用户实测 bug）
- **症状**：运营在赛季奖励里填了几款**喷漆/衣服**的编号（205/257/258/259），真机上整张奖励轨道全部显示 **毛驴轮胎**。
- **机制**：`tr::PVPManager::getSpecialRewardById(int) @0x5e231c`（324 B）查 `this+0x288` 的 `std::map<int, tr::ItemManager::WheelReward>`（键=节点 `+0x20`、值=节点 `+0x24`），**未命中时不返回 null，而是就地插入一个默认构造的空 WheelReward**：`0x5e2410` 的 `std::piecewise_construct`（字面量 `@0xb8f859`）+ `0x5e242c bl ..._Rb_tree..._M_emplace_hint_unique...`，返回 `x8+0x24` ⇒ 调用点 `MenuzStatePVPPostSeason::setupRewards` 的 `0x735584 cbz x23,#0x7359f8` 是死代码。
- **唯一填充者**：`tr::PVPDataParser::parseMatchSpecialRewards(json_value*, std::map<int,WheelReward>&) @0x5db0b4`（它同时也往 `std::vector<PVPSpecialWheelRewardLevel>` 里 emplace，该 `_M_emplace_back_aux @0x5ddaf0` 的唯一调用者就是它）；对照 `PVPDataParser::parseMatchRewardTypes @0x5daf5c` 只调 `ItemManager::parseWheelReward @0x59dd8c`（1712 B）、**函数签名里没有 map** ⇒ 那张 309 条的轮盘表（喷漆/衣服/赛道都在里面）**不会**填这张表。
- **原表真源**：`/conf/pvp_match_rewards.txt`（= `tmp/packout/all/0024_a7ebc782.bin`，125010 B）的 `PVPMatchSpecialRewards` 是 **list[7]**（`PVPMatchRewardTypes` list[309]、`MissingRewardFallbackRewards` dict[25]、`PVPMatchRewards` dict[4] 另计）：
  | Comment | SpecialRewardLevel | ids |
  |---|---|---|
  | Crafting Item Tier 2 | 0.0 | 20003,20008,20013,20018,20023,20028,20033,20038,20043,20048 |
  | Crafting Item Tier 3 | 1.0 | 20002,20007,20012,20017,20022,20027,20032,20037,20042,20047 |
  | Soylent Bike Skin | 2.0 | 202 |
  | Donkey Blueprint | **100.0** | 220 |
  | Luchador Bikeskin | 3.9 | 203 |
  | Crafting Item Tier 4 | 4.0 | 20001,20006,20011,20016,20021,20026,20031,20036,20041,20046 |
  | Crafting Item lvl 5 | 6.0 | 20000,20005,20010,20015,20020,20025,20030,20035,20040,20045 |
- ⇒ **去重后 43 个编号**（`202, 203, 220` + 40 个零件）。第 5 档轮盘编号 `20004/20009/…/20049` 只在 309 条那张表里，**不是**特殊奖。
- 其它约束：`getCombinedSeasonRewards @0x5e7364` 只收 `cmp w8,#0x91`（item_id==145）的 pair，别的 item_id 在 `0x5e7430-0x5e7480` 被 `b.ne` 跳过；`isRewardSpecial(const WheelReward&) @0x5e22e0` = `ldrb [x1,#4]` 非零为真，否则 `ldrsh [x1,#0x10]` 走 `/10-1 >= 10`。
- **服务端落地（`server/tf_server.py`）**：`_PVP_SPECIAL_GROUPS`（7 组，同一张表）+ `_PVP_SPECIAL_IDS`（frozenset，43）；`_bunker_rewards_check()` 对 `item_id 145` 的 amount 不在集合里就 `bad-special:<id>`；`_bunker_catalogs()` 改成吐 `specials`（43 条，带 `group_en/group_cn`，按组连续，供 `<optgroup>`），`bunker_payload()` 的键从 `rewards` 改成 `specials`。

## 6. 最小回归清单
- 同一match双方查询池一致；两次不同increase累加、同一已识别重试不再累加；进程重启仍保留池和reward_data。
- close按(pid,match)一次bank；过早close不bank；重复close/重启不多入筹码、不重复暴露本地领奖入口。
- chip支付成功才本地发物品；purchase_tickets增余额；golden start_race只扣一次且刷新后不返还。
- 季奖nested26档；rank R领取的是R..25各档之和；重复close_season不推进两个季节；不在服务端另加金币宝石。
- rank1满cap再胜→rank0；旧streak2再胜两星；rank14零星失败→rank15且cap[15]-1；rank15零星失败不降档；rank20不掉星。
- **以上是建议测试，不是本子任务已完成的真机/服务端回归。** 主代理收到早期和最终证据后另行实现/验证。
