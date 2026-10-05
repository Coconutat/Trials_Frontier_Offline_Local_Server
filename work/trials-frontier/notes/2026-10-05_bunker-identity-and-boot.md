# 2026-10-05 碉堡：身份稳定 + 启动期端点 + 经济契约回归修复

**范围：`work/trials-frontier/scope.md` 的 granted / lab_only。只改本项目服务器、配置与测试；HTTP 测试只监听回环随机端口；未启动真机、未改玩家存档。** 29/29 隔离回归绿 + 真 HTTP 烟测通过；**真机未验证**。

## 证据

| Evidence | source_ref / repro_command | 说明 |
|---|---|---|
| E-BOOT-LOG | `work/trials-frontier/notes/server-log.jsonl`（7360 行，末次 2026-10-05 20:54:28） | 真机全量请求日志（MI 8，Host `192.168.5.2:8000`） |
| E-NONE-PVP | 同上，`path` 含 pvp 的行按会话分组 | 20:5x 那场（三张截图前）**67 条请求里 pvp 路径 0 条**；整场停在 friends 之后的内容/新闻阶段并重试 dlcontent 13 次 |
| E-ID-MIX | 同上，按 `req_headers.Authorization` 分组 | `Ubi_v1` 5419 / **无 Authorization 1737** / **`tf-local-ticket-0001` 1489** / UbiMobile 110 / Basic 55 |
| E-401 | 同上，`status>=400` 共 52 条 | `progress` 401×8、`enhancestats/batch_update` 401×9、`sessions` 401×15；**PVP 端点从未 4xx** |
| E-GAMECFG-REAL | `work/trials-frontier/notes/real-server-samples.md` §1/§2 | 真人样本：`gamecfg-mob.ubi.com/profile/?epoch=1` → 裸 `[]` + `Ubisoft-CA/Zone/Server-Time`；`?action=register_device` → `{"device":{"federated_id","ubimobi_access_token"}}`（各 43 字符 base62） |
| E-CHIPSTORE-OBB | `tmp/PVP_CHIPS_REPORT.md` §5.5 + `tmp/pvp_chip_store.txt` | 筹码商店物品表来自 OBB `content.dat` 的 `/conf/pvp_chip_store.txt`（客户端本地表），服务端只需扣筹码 |
| E-DISCOUNT | `pvp-reward-contract.md`（`purchaseChipstoreItem @0x5e6e1c`、`getCurrentPVPChipStorePriceMultiplier @0x582040`） | 客户端按持有 type9 套装打折：`total=int(float(num*amount)*multiplier+0.5); price=total//num` |
| E-GREEN | `python -m unittest discover -s tests`；`python -m py_compile server/tf_server.py server/tflocal_accounts.py tests/test_pvp_economy.py` | Ran 29 tests OK |
| E-SMOKE | `python tmp/smoke_bunker_http.py` | 起真 HTTP（临时 PVP_STATE_PATH/LOG_PATH，未动 `server/data/pvp_state.json`）：`/`→200`[]`、`register_device`→200 双 token、`pvp_init`/`matches`/`matches/1`/`players`(数组)/`pvp_config`/`ranking/legends`/`pvp_banner` 全部 200 |

## Findings

| Finding | 根因 → 改动 | Evidence |
|---|---|---|
| F-ID-SPLIT | **未提交版本里 PVP/存档状态会被劈成两半**：同一台客户端混用「账号票 / 不带 Authorization / 我们发的固定匿名票」三种身份，`authenticate` 把后两类判成匿名槽 `11111111-…`。症状正是用户所说的「时好时坏」：有时看到自己的段位与进行中的对局，有时是全新玩家（rank25/0 筹码/无对局 ⇒「当前对决」空转）。→ 新增 `tflocal_accounts.resolve_identity()`：认成账号时按客户端 IP + device_id 落 `data/bindings.json` 绑定；认不出凭据时（**明确口令错误除外**）归到绑定账号。`h_session` 在设备/匿名兜底前先查绑定。 | E-ID-MIX, E-401, E-GREEN |
| F-BOOT-GAMECFG | `GET /?product=101&portal=Google&version=…`（启动第一条）以前落 rules.json 的 `*` 兜底，回 `{"data": []}`（对象），真服务器回**裸 `[]`**；`register_device` 完全没实现。→ 新增 `h_gamecfg`（含 `_base62`），注册 `GET|POST /`。 | E-BOOT-LOG, E-GAMECFG-REAL, E-SMOKE |
| F-START-STR | 未提交的 `h_pvp_start_race` 写死 `type(tid) is int`，而真机发**字符串** `"1062"` ⇒ 点「开赛」一律 400（红测试正指这条）。→ 容忍数字串，并把 `track` 统一存成 int（否则 `h_pvp_race` 的 `pending["track"] != tid` 会 409）。 | `tmp/pvp-abc-red-tests.txt`, E-BOOT-LOG |
| F-SEASON-DUP | 季奖配置 rank 5/10/15/20/25 的 `item_id:145` **各写重一条** ⇒ 特殊季奖双发；且只覆盖 8 个档，而客户端结算的是「index ≥ 当前 rank 之和」，缺档等于那一级白给。→ 去重保护 + 全 26 档（35 条）表，Python 默认与 `tf_config.json` 同步；表结构与 `_note` 明确写成「将来 WebUI 赛季编辑器要生成的模板」。 | pvp-reward-contract.md, E-GREEN |
| F-CHIP-DEBUG | `chips.bonus=114514`（旧版重启丢筹码的一次性补偿）与 `chips.bot_start=500` 是调试值，状态已持久化后只会凭空印钱 / 让对手余额造假。→ 删除；人机与真人共用 `_pvp_chips_for`（无赛道即不产币）。用户 2026-10-05 确认删。 | E-GREEN |
| F-SHOP-PRICE | 金票购买要求 `price == 基价`，穿折扣套装时客户端送来的是折后单价 ⇒ 合法购买被 400。→ 放宽为 `0 < price <= 基价`（上界仍由服务端价表钉死）。筹码商店其余部分**不需要服务端改动**：物品表在客户端 OBB 里，服务端只扣筹码（`POST /chips` 已在未提交 diff 里实现并返回 `{"chips":left}`）。 | E-CHIPSTORE-OBB, E-DISCOUNT |
| F-STATE-BLOAT | 每个成功请求都 `copy.deepcopy` 全部状态 + `force=True` 整份重写（`indent=1`），且对局/回执永不清理 ⇒ 越玩越慢。→ 紧凑 JSON；双方都领完后 `_pvp_slim_match()` 丢掉成绩/回执/归属大块；`reward_receipts` 只留最近 128 条。 | E-GREEN |

## 未做（故意）

- **`POST /public/pushnotification/v1/register_device`、`GET /dlcontent_frontier_android/<ver>/info.json`、`/frontieronlinecontent/loc.json`、`/ingame/.../News/` 仍走 `*` 兜底。** 没有可靠的 wire 样本（真服务器那几条早已 404/NoSuchBucket，设备上也没有缓存样本），凭空编形状的风险大于收益；这四条在成功启动的会话里也频繁重试，**不能证明是卡住的原因**。需要判定时请抓一次卡住时的服务器控制台输出（JSONL 只记到了 20:54:28，之后服务端看到了什么无从得知）。

## 复跑

```powershell
python -m unittest discover -s tests -v
python -m py_compile server/tf_server.py server/tflocal_accounts.py tests/test_pvp_economy.py
python tmp\smoke_bunker_http.py     # 真 HTTP 烟测，只写临时目录
```

## 真机待验证（服务器测试替代不了）

1. 冷启动进碉堡：四个面板是否还有转圈；`pvp_state.json` 里是否只落在**账号槽**（不再出现 `11111111-…` 的增长）。
2. 一局完整流程：开赛扣票 → 跑图 → 转盘累计 → 六小时到期 close → 领取 → 金币/宝石/筹码变化 → 重登存档。
3. 穿折扣套装买黄金门票。
4. 若仍卡住：抓服务端 stdout（含 `[pvp]`/`[gamecfg]` 行）与 `adb logcat`，定位是「客户端没发请求」还是「发了但解析失败」。
