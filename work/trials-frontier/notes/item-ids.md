# Trials Frontier — Item IDs (mined from local game data)

Generated from the offline APK/OBB dump in this repo. **No `server/` files were modified.**

## How these IDs were obtained (and what is certain vs inferred)

`content.dat` is a `datapack::DataFilePack` container and it **was fully decoded**:

```
0x00 u32 magic  = 0xdbf7dddb
0x04 u32 count  = 2494
0x08 u32 recsize= 12
0x0C table[count] x 12 bytes  { u32 uncompressedSize, u32 dataOffset, u32 nameHash }
end_of_table = 12 + count*recsize = 29940
blob @ end_of_table+dataOffset = { u32 compressedSize, u8 flag(1=zlib), 3 pad, payload }, 16-byte aligned, 0xba pad
nameHash = mt::String::getHashCode(path)  -> lets you name every entry
```

All 2494 entries were decompressed to `tmp\packout\all\NNNN_<hash>.bin`; 433 are text/JSON.
The `/conf/*.txt` / `/conf/*.json` entry names below were recovered by hashing the
path strings found in `libTrialsGo.so` and matching them against the container table —
so **the provenance column is the real internal path**, not a guess.

“Where it came from” for every table in this document is a
`content.dat entry #N (<internal path>) @0xNNNNNN` triple: entry index, recovered internal path, and
the absolute byte offset of that entry’s zlib blob inside `content.dat`.
Reproduce any of them with `python tmp\itemdb_extract.py tmp\obbdata\content.dat --hash /conf/itemdb.txt`.

Matching machinery: `tmp\match_paths.py` (hash every candidate path string from
`tmp\libTrialsGo.strings.txt` and compare against the container table) — 167 of 2494 entries named.
The extraction driver is `tmp\make_itemids.py`; raw dumps are in `tmp\packout\itemids_report.txt`.

### 已知数据瑕疵：`dailyrewards.txt` 有一处 JSON 语法错误（原厂 typo）

一次性把 8 张配置表全部 dump 出来验证时（条目 **#10** `dailyrewards`、**#49** `wts_rewards`、
**#8** `dailyquestrewards`、**#9** `dailyquesttasks`、**#2232–2235** `state_pvp_*`），
**解包/解压 0 失败**，但 `/conf/dailyrewards.txt` 的**第 993 行少一个逗号**：

```
"ItemAmount":1	<-- 这里缺 ','	"Fallback":2
```

⇒ `json.loads` 直接报 `Expecting ',' delimiter`。**这不是我们解包或解压的问题，是 RedLynx 自己发出去的数据有 typo**（其余各表均可正常解析）。

* **影响**：任何"把 `content.dat` 全表 dump 成 JSON 再 diff / 校验"的工具必须对这一行容错，否则脚本会挂在这一张表上。
* **落地**：写解析器时按行正则补齐或对该表单独 try/except。
* 复现：`tmp\packout\all\` 里对应 `<idx>_<hash>.bin` **本身就是解好的明文**，直接复制改名即可；要重放容器则用 `datapack::DataFilePack`（`tmp\obb\content.dat`，magic `dbf7dddb`）按表记录取 blob，`flag==1` 时 `zlib.decompress`（配方已由 `tmp\verify_pack_recipe.py` 验证 SHA256 一致）。文件名后缀 = `getHashCode(path)`，据此反查条目号。

The `ITEM_TYPE` enum (235 values) was decoded from the jump table of
`MissionEditorTexts::getNameForItemType(ITEM_TYPE)` @ `0x437458` in `tmp\extract\libTrialsGo.so`.

---

## 0. ID-space overview

| ID / range | what it is | basis |
|---|---|---|
| `1` | Coins | `ITEM_0_1`, recurring in every reward table |
| `2` | **Gems / Diamonds (钻石/宝石)** | `ITEM_0_2`, `/MENUZ/ITEM/DIAMOND.PNG` |
| `5`–`54` | **零件 crafting parts** = `ITEM_TYPE*5 + TIER`, TYPE 1–10, TIER 0–4 | verified numerically (see §2) |
| `0`–`107` | **喷漆 bike paints/skins** (`bikeskin.txt` skin ids) | `/conf/bikes.txt` `SkinData`; wheel-entry comment: “ItemId points to ID defined in bikeskins.txt” |
| `135` | PVP Golden Ticket | `ITEM_27_0`, `/MENUZ/ITEM/TICKET.PNG` |
| `145` | Special PVP reward (random/unknown item) | `PVPMatchRewardTypes` ID 100, `/MENUZ/ITEM/QUESTIONMARK.PNG` |
| `150`, `151`, `152`, `171`, `179` | Doughnut, Bronco Buck Set, Event Point Set, VIP membership badge, unknown | `/conf/wheelspecials.txt` (see §7b) |
| `205`–`847` | **服装 rider outfit parts**, allocated in 3-item blocks (helmet, upper, lower) | `/conf/wheelspecials.txt`, `/conf/wts_rewards.txt` |
| `414`–`459` | **摩托蓝图 bike blueprints** | `/MENUZ/ITEM/BLUEPRINT_nn.PNG` reward entries |
| `635`, `637` | consumable boosts (Coin Magnet / Rarified Fuel) | `/MENUZ/ITEM/BOOSTS_n.PNG` |
| `1108`–`1438`, `65010` | **地图/赛道 tracks & track pieces** = the `levels.txt` `ID` field | `/conf/levels.txt` + every `Type:1/3` reward |
| `1191`–`1210` | West-side (WST_) tracks sold for PVP chips | `/conf/pvp_chip_store.txt` |
| `20000`–`20054+` | *reward IDs* (not item IDs) used by the PVP ladder wheel | `/conf/pvp_match_rewards.txt` |

A reward record is `{ ID, Comment, Type, ItemId, ItemAmount, TextureName` or
`TextureAtlasId/TextureAtlasIndex, Rarity, WheelChance, Fallback, ShowInfoPopup, NameId, DescriptionId,
LvlUnlock, MissionUnlock, TrackUnlock, TierAllowed, SoundId, AwardCount, ItemValue }`.
`Type` in these catalogs is a *display* type, not `ITEM_TYPE`: `0` = generic item/currency, `1` = track, `2` = bike skin, `3` = track piece.

The equivalent compact form used inside `giftbox.txt` / `xp.txt` / `upgrades.txt` is
`{ IID, IL, IC }` = (item-type-or-category, item level, count), where `IID 0 IL 1` = coins, `IID 0 IL 2` = gems,
`IID 0 IL 3` = golden tickets, `IID 170 IL 1` = a track (IC = the track item ID), `IID 127` = boosts,
`IID 133/134/136` = paintjobs, `IID 30` = Doughnut consumable.

> ### ⚠ `ItemId` is only unique **within a `Type`**
>
> The game reuses the same numbers across item categories. A scan of every reward catalog found
> **88 `ItemId` values that carry more than one `Type`** — e.g.

| ItemId | Type 0 | Type 1 | Type 2 |
|---|---|---|---|
| `5` | Crafting Item (Tier 0 Chain) | — | bike skin “Camo” |
| `13` | Crafting Item (Tier 3 Spring) | — | bike skin “Wasp” |
| `1105` | outfit part “Feaster Bunny Head” | track `LVL_COAL_TOWN` | — |
| `1195` | outfit part “The Deputy Head” | track `WST_UNSTABLE_TUNNEL` | — |

> So when granting an item, **always carry the `Type` alongside the `ItemId`** (or grant the
> `{IID, IL, IC}` triple, which is unambiguous). Every table below repeats the type for this reason.

---

## 1. 钻石/宝石 (gems/diamonds) and other currency

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `1` | Coins — `ITEM_0_1` / `/MENUZ/ITEM/COIN.PNG` | currency | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` (MonthlyRewards ID 1, 1000 coins) |
| `2` | **Gems / Diamonds — `ITEM_0_2` / `/MENUZ/ITEM/DIAMOND.PNG`** | premium currency | `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` (MonthlyRewards ID 2 = 3 gems); `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 5 “A gem” |
| `135` | PVP Golden Ticket — `ITEM_27_0` / `/MENUZ/ITEM/TICKET.PNG` | currency | `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` (MonthlyRewards ID 3) |
| `234`-type | `[%d] Event Currency` → e.g. `ITEM_234_*` | currency | `ITEM_TYPE` 234 from `getNameForItemType` @ `0x437458` |

Diamond drops are also configured per level-category in `/conf/level_rewards.txt` as
`d,<probability>,<amount>` (default 0.02 = 2% when omitted). Example first block (`0` = The Cave / The Aqueduct / Rock Wall):
`i,1,0,20 / i,2,0,20 / i,3,0,30 / i,4,0,30 / x,10 / d,0.03,5` → 3% chance of 5 diamonds.

---

## 2. 零件 — crafting parts (ItemId = ITEM_TYPE*5 + TIER)

`ITEM_TYPE` 1–10 x tier 0–4. Confirmed arithmetically against `/conf/wts_rewards.txt`
(“Crafting Item (Tier 4 Chain)” = ItemId 9 = 1*5+4; “(Tier 4 Gear)” = 54 = 10*5+4)
and against `/conf/itemdb.txt` (rewards at ID 20040–20054 with `NameId` = `ITEM_9_4`…`ITEM_10_4`).

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `5` | `ITEM_1_0` — Chain (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 4 |
| `6` | `ITEM_1_1` — Chain (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 5 |
| `7` | `ITEM_1_2` — Chain (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 6 |
| `8` | `ITEM_1_3` — Chain (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 7 |
| `9` | `ITEM_1_4` — Chain (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 8 |
| `10` | `ITEM_2_0` — Spring (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 9 |
| `11` | `ITEM_2_1` — Spring (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 10 |
| `12` | `ITEM_2_2` — Spring (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 11 |
| `13` | `ITEM_2_3` — Spring (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 12 |
| `14` | `ITEM_2_4` — Spring (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 13 |
| `15` | `ITEM_3_0` — Bolt (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 14 |
| `16` | `ITEM_3_1` — Bolt (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 15 |
| `17` | `ITEM_3_2` — Bolt (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 16 |
| `18` | `ITEM_3_3` — Bolt (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 17 |
| `19` | `ITEM_3_4` — Bolt (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 18 |
| `20` | `ITEM_4_0` — Nut (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 19 |
| `21` | `ITEM_4_1` — Nut (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 20 |
| `22` | `ITEM_4_2` — Nut (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 21 |
| `23` | `ITEM_4_3` — Nut (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 22 |
| `24` | `ITEM_4_4` — Nut (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 23 |
| `25` | `ITEM_5_0` — Metal Sheet (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 24 |
| `26` | `ITEM_5_1` — Metal Sheet (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 25 |
| `27` | `ITEM_5_2` — Metal Sheet (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 26 |
| `28` | `ITEM_5_3` — Metal Sheet (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 27 |
| `29` | `ITEM_5_4` — Metal Sheet (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 28 |
| `30` | `ITEM_6_0` — Spark Plug (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 29 |
| `31` | `ITEM_6_1` — Spark Plug (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 30 |
| `32` | `ITEM_6_2` — Spark Plug (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 31 |
| `33` | `ITEM_6_3` — Spark Plug (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 32 |
| `34` | `ITEM_6_4` — Spark Plug (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 33 |
| `35` | `ITEM_7_0` — Pipe (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 34 |
| `36` | `ITEM_7_1` — Pipe (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 35 |
| `37` | `ITEM_7_2` — Pipe (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 36 |
| `38` | `ITEM_7_3` — Pipe (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 37 |
| `39` | `ITEM_7_4` — Pipe (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 38 |
| `40` | `ITEM_8_0` — Ball Bearing (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 39 |
| `41` | `ITEM_8_1` — Ball Bearing (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 40 |
| `42` | `ITEM_8_2` — Ball Bearing (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 41 |
| `43` | `ITEM_8_3` — Ball Bearing (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 42 |
| `44` | `ITEM_8_4` — Ball Bearing (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 43 |
| `45` | `ITEM_9_0` — Piston (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 44 |
| `46` | `ITEM_9_1` — Piston (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 45 |
| `47` | `ITEM_9_2` — Piston (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 46 |
| `48` | `ITEM_9_3` — Piston (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 47 |
| `49` | `ITEM_9_4` — Piston (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 48 |
| `50` | `ITEM_10_0` — Gear (tier 0) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 49 |
| `51` | `ITEM_10_1` — Gear (tier 1) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 50 |
| `52` | `ITEM_10_2` — Gear (tier 2) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 51 |
| `53` | `ITEM_10_3` — Gear (tier 3) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 52 |
| `54` | `ITEM_10_4` — Gear (tier 4) | 零件 / crafting part | `content.dat entry #16 (/conf/itemdb.txt) @0x011f54`; enumerated in `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894` MonthlyRewards ID 53 |

> Note: the runtime string for `ITEM_TYPE 8` is `"[8] Break Handle"`, but every reward comment and
> `itemdb` entry for the same ID range says **Ball Bearing**. The string is a developer slip-up;
> `ITEM_8_*` really is “Ball Bearing”. ID 43 = tier-3 Ball Bearing, ID 44 = tier-4 Ball Bearing.

---

## 3. 喷漆 — bike paints / skins (108 of them)

Source: `content.dat entry #2 (/conf/bikes.txt) @0x009774` → `SkinData`. The `ID` field **is** the paint item id used by the shop/reward configs (the wheel-entry comment says
“ItemId points to ID defined in bikeskins.txt”). The paint-can texture comes from the PAINT_<bike>_<slot>.PNG atlas entry,
the 3D texture is `/GFX/OBJECT/BIKE/BIKE_<bike>_<slot>.PNG`. `DiamondCost` = gem price if sold for gems.
Slot = `SkinIndex`（0 起）；只有 17 辆车有涂装（BikeID 18 HD EV 没有）。

★ **但 `SkinData.ID` 绝不是存档 `items2` 的键** —— 见本节的「存档里怎么存」。这一条踩过坑：
108 款里有 13 个 ID（5,13,23,28,30,33,45,46,49,51,52,53,54）同时是**零件**编号，
按 ID 写 `items2[id]` 会改到玩家的零件计数上。

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `0` | Flaming Tango | 喷漆 / bike skin, BikeID 2 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[0] |
| `1` | America | 喷漆 / bike skin, BikeID 1 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[1] |
| `2` | Poopdeck | 喷漆 / bike skin, BikeID 6 slot 0 — DiamondCost 100, MissionUnlock 90 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[2] |
| `3` | Snakebite | 喷漆 / bike skin, BikeID 7 slot 0 — DiamondCost 75, MissionUnlock 220 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[3] |
| `4` | Chester | 喷漆 / bike skin, BikeID 8 slot 0 — DiamondCost 75, MissionUnlock 220 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[4] |
| `5` | Camo | 喷漆 / bike skin, BikeID 4 slot 0 — DiamondCost 75, MissionUnlock 71 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[5] |
| `6` | Vanilla Glow | 喷漆 / bike skin, BikeID 4 slot 1 — MissionUnlock 151 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[6] |
| `7` | Marine | 喷漆 / bike skin, BikeID 5 slot 0 — DiamondCost 75, MissionUnlock 149 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[7] |
| `8` | Golden Mantis | 喷漆 / bike skin, BikeID 5 slot 1 — DiamondCost 200, MissionUnlock 149 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[8] |
| `9` | Union Jack | 喷漆 / bike skin, BikeID 2 slot 1 — DiamondCost 75, MissionUnlock 43 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[9] |
| `10` | Bastille | 喷漆 / bike skin, BikeID 2 slot 2 — DiamondCost 75, MissionUnlock 43 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[10] |
| `11` | Mad Bird | 喷漆 / bike skin, BikeID 7 slot 1 — DiamondCost 75, MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[11] |
| `12` | 8-Ball | 喷漆 / bike skin, BikeID 3 slot 1 — DiamondCost 75, MissionUnlock 220 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[12] |
| `13` | Wasp | 喷漆 / bike skin, BikeID 3 slot 0 — DiamondCost 100, MissionUnlock 102 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[13] |
| `14` | Neon | 喷漆 / bike skin, BikeID 2 slot 3 — DiamondCost 75 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[14] |
| `15` | Sailor | 喷漆 / bike skin, BikeID 3 slot 2 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[15] |
| `16` | Medic | 喷漆 / bike skin, BikeID 3 slot 3 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[16] |
| `17` | Soylent | 喷漆 / bike skin, BikeID 2 slot 4 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[17] |
| `18` | Aloha | 喷漆 / bike skin, BikeID 3 slot 4 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[18] |
| `19` | Luchador | 喷漆 / bike skin, BikeID 3 slot 5 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[19] |
| `20` | Kaleidoscope | 喷漆 / bike skin, BikeID 3 slot 6 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[20] |
| `21` | Mithril Mantis | 喷漆 / bike skin, BikeID 5 slot 2 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[21] |
| `22` | Pumpkin King | 喷漆 / bike skin, BikeID 5 slot 3 — DiamondCost 100 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[22] |
| `23` | Venom | 喷漆 / bike skin, BikeID 8 slot 1 — DiamondCost 75, MissionUnlock 43 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[23] |
| `24` | Mr. Bones | 喷漆 / bike skin, BikeID 4 slot 2 — DiamondCost 100, MissionUnlock 43 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[24] |
| `25` | Scales | 喷漆 / bike skin, BikeID 6 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[25] |
| `26` | Lava | 喷漆 / bike skin, BikeID 1 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[26] |
| `27` | Stitch | 喷漆 / bike skin, BikeID 2 slot 5 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[27] |
| `28` | The Gourd | 喷漆 / bike skin, BikeID 7 slot 2 — DiamondCost 75, MissionUnlock 43 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[28] |
| `29` | Spirits | 喷漆 / bike skin, BikeID 8 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[29] |
| `30` | Boogeyman | 喷漆 / bike skin, BikeID 1 slot 2 — DiamondCost 75, MissionUnlock 43 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[30] |
| `31` | Raven | 喷漆 / bike skin, BikeID 3 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[31] |
| `32` | Heartbreaker | 喷漆 / bike skin, BikeID 3 slot 8 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[32] |
| `33` | Noble | 喷漆 / bike skin, BikeID 9 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[33] |
| `34` | Winter1 | 喷漆 / bike skin, BikeID 1 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[34] |
| `35` | Winter2 | 喷漆 / bike skin, BikeID 4 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[35] |
| `36` | Winter3 | 喷漆 / bike skin, BikeID 6 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[36] |
| `37` | Winter4 | 喷漆 / bike skin, BikeID 9 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[37] |
| `38` | Rodeo1 | 喷漆 / bike skin, BikeID 5 slot 4 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[38] |
| `39` | Fallout Donkey | 喷漆 / bike skin, BikeID 19 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[39] |
| `40` | Molten Donkey | 喷漆 / bike skin, BikeID 19 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[40] |
| `41` | 4thJuly | 喷漆 / bike skin, BikeID 3 slot 9 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[41] |
| `42` | Cruise Red | 喷漆 / bike skin, BikeID 11 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[42] |
| `43` | Spec Ops Agent | 喷漆 / bike skin, BikeID 11 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[43] |
| `44` | Cruise White | 喷漆 / bike skin, BikeID 11 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[44] |
| `45` | Palomino Stallion | 喷漆 / bike skin, BikeID 10 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[45] |
| `46` | Snowy Stallion | 喷漆 / bike skin, BikeID 10 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[46] |
| `47` | Black Stallion | 喷漆 / bike skin, BikeID 10 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[47] |
| `48` | Cowhide Armadillo | 喷漆 / bike skin, BikeID 1 slot 4 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[48] |
| `49` | Ceremonial Feathers | 喷漆 / bike skin, BikeID 9 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[49] |
| `50` | Hippie | 喷漆 / bike skin, BikeID 7 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[50] |
| `51` | Redlynx | 喷漆 / bike skin, BikeID 2 slot 6 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[51] |
| `52` | Undead Horse | 喷漆 / bike skin, BikeID 10 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[52] |
| `53` | Batbike | 喷漆 / bike skin, BikeID 8 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[53] |
| `54` | Nutcracker | 喷漆 / bike skin, BikeID 2 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[54] |
| `55` | Winter Wolf | 喷漆 / bike skin, BikeID 6 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[55] |
| `56` | Blizzard Donkey | 喷漆 / bike skin, BikeID 19 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[56] |
| `57` | Candy Cane Donkey | 喷漆 / bike skin, BikeID 19 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[57] |
| `58` | Fanny Pack | 喷漆 / bike skin, BikeID 5 slot 5 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[58] |
| `59` | Edge | 喷漆 / bike skin, BikeID 4 slot 4 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[59] |
| `60` | KTM_white | 喷漆 / bike skin, BikeID 13 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[60] |
| `61` | Cheetah | 喷漆 / bike skin, BikeID 7 slot 4 — DiamondCost 75, MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[61] |
| `62` | Saurus | 喷漆 / bike skin, BikeID 9 slot 3 — DiamondCost 75, MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[62] |
| `63` | Hungry Shark | 喷漆 / bike skin, BikeID 1 slot 5 — DiamondCost 75, MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[63] |
| `64` | Cyclops | 喷漆 / bike skin, BikeID 9 slot 4 — DiamondCost 75, MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[64] |
| `65` | The Revenant | 喷漆 / bike skin, BikeID 7 slot 5 — MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[65] |
| `66` | Hard Rocker | 喷漆 / bike skin, BikeID 8 slot 4 — MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[66] |
| `67` | The Dead Of Day | 喷漆 / bike skin, BikeID 5 slot 6 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[67] |
| `68` | KTM NEON | 喷漆 / bike skin, BikeID 13 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[68] |
| `69` | RED BULL | 喷漆 / bike skin, BikeID 14 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[69] |
| `70` | VENGEANCE KNIGHT | 喷漆 / bike skin, BikeID 9 slot 5 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[70] |
| `71` | FEASTER DONKEY | 喷漆 / bike skin, BikeID 19 slot 4 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[71] |
| `72` | CAMO_BANDITO | 喷漆 / bike skin, BikeID 15 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[72] |
| `73` | THE RENOWNED BERSERKAR | 喷漆 / bike skin, BikeID 8 slot 5 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[73] |
| `74` | RED_BMW F800 GS | 喷漆 / bike skin, BikeID 16 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[74] |
| `75` | Ausx_Mantis | 喷漆 / bike skin, BikeID 5 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[75] |
| `76` | Ausx_Tango | 喷漆 / bike skin, BikeID 2 slot 8 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[76] |
| `77` | SANDSTORM | 喷漆 / bike skin, BikeID 5 slot 8 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[77] |
| `78` | THUNDERSTORM | 喷漆 / bike skin, BikeID 15 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[78] |
| `79` | VALENTINE_IN | 喷漆 / bike skin, BikeID 6 slot 4 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[79] |
| `80` | CLAWRIDE | 喷漆 / bike skin, BikeID 7 slot 6 — MissionUnlock 244 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[80] |
| `81` | ICY X | 喷漆 / bike skin, BikeID 5 slot 9 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[81] |
| `82` | RIPTIDE X-18 | 喷漆 / bike skin, BikeID 7 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[82] |
| `83` | PURPLE DUST | 喷漆 / bike skin, BikeID 13 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[83] |
| `84` | DARK_HORSE | 喷漆 / bike skin, BikeID 16 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[84] |
| `85` | DARKMAGIC | 喷漆 / bike skin, BikeID 8 slot 6 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[85] |
| `86` | TRANZIT_PAINTJOB | 喷漆 / bike skin, BikeID 5 slot 10 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[86] |
| `87` | CRIMSON_CRUISER | 喷漆 / bike skin, BikeID 9 slot 6 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[87] |
| `88` | RISING_STREAKS | 喷漆 / bike skin, BikeID 5 slot 11 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[88] |
| `89` | GOLDEN_DIRT | 喷漆 / bike skin, BikeID 7 slot 8 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[89] |
| `90` | EXTRATERRESTRIAL | 喷漆 / bike skin, BikeID 6 slot 5 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[90] |
| `91` | HD-2 | 喷漆 / bike skin, BikeID 17 slot 0 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[91] |
| `92` | YELLOW_SUBMARINE | 喷漆 / bike skin, BikeID 9 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[92] |
| `93` | BLACKJACK BRONCO | 喷漆 / bike skin, BikeID 3 slot 10 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[93] |
| `94` | ALPACA | 喷漆 / bike skin, BikeID 6 slot 6 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[94] |
| `95` | TURTLE | 喷漆 / bike skin, BikeID 2 slot 9 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[95] |
| `96` | BAD BONE | 喷漆 / bike skin, BikeID 3 slot 11 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[96] |
| `97` | OPERA | 喷漆 / bike skin, BikeID 9 slot 8 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[97] |
| `98` | Stache | 喷漆 / bike skin, BikeID 7 slot 9 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[98] |
| `99` | Christmas Bandito | 喷漆 / bike skin, BikeID 15 slot 2 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[99] |
| `100` | Green Donkey | 喷漆 / bike skin, BikeID 19 slot 5 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[100] |
| `101` | Blossom | 喷漆 / bike skin, BikeID 9 slot 9 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[101] |
| `102` | Fudge | 喷漆 / bike skin, BikeID 2 slot 10 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[102] |
| `103` | Firestarter | 喷漆 / bike skin, BikeID 8 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[103] |
| `104` | Nocturnal | 喷漆 / bike skin, BikeID 6 slot 7 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[104] |
| `105` | Beluga | 喷漆 / bike skin, BikeID 15 slot 3 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[105] |
| `106` | Sheriff | 喷漆 / bike skin, BikeID 7 slot 10 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[106] |
| `107` | Dawn Breaker | 喷漆 / bike skin, BikeID 14 slot 1 | `content.dat entry #2 (/conf/bikes.txt) @0x009774` SkinData[107] |

### 存档里怎么存（★ 反汇编 + 真机存档双向确认）

每辆车**只有一条** `items2` 记录，键 = `664 + BikeID`（= `0x299 + bikeIndex`，`bikeIndex = BikeID − 1`）：

```
items2[664 + BikeID] = ((当前装备的 SkinIndex + 1) << 24) | 已拥有位掩码
已拥有位掩码 = 位 i（i < 24）置 1 ⇔ SkinIndex == i 的那款已拥有；active 0 = 没装备涂装
```

真机存档对照（`server/data/save/53ebbd18-…/latest.json`，ccb，`items2` 632 条）：

| 键 | BikeID / 车 | 值 | active | 位掩码 | 解出的 SkinIndex |
|---|---|---|---|---|---|
| 665 | 1 Armadillo | `0x03000014` | 2 | `0b10100` | {2,4} |
| 666 | 2 Tango | `0x01000017` | 0 | `0b10111` | {0,1,2,4} |
| 668 | 4 Jackal | `0x03000005` | 2 | `0b101` | {0,2} |
| 677 | 13 KTM 500 EXC | `0x02000006` | 1 | `0b110` | {1,2} |
| 678 | 14 KTM 450 RALLY | `0x02000002` | 1 | `0b10` | {1}（= 107 Dawn Breaker ✓） |
| 680 | 16 BMW F800 GS | `0x02000002` | 1 | `0b10` | {1} |

667 / 669 / 670 / 671 不存在 ⇒ 那几辆车一款涂装都没有。5/5 条 active ∈ 位掩码，且每个位都对应
`SkinData` 里真实存在的 `(BikeID, SkinIndex)`。

反汇编符号（`tmp\extract\libTrialsGo.so`，arm64）：

| 地址 | 符号 | 关键指令 |
|---|---|---|
| `0x0062a12c` | `tr::UpgradeManager::getBikeIndexByID(unsigned short)` | `and w8,w1,#0xffff; sub w0,w8,#1` ⇒ bikeIndex = BikeID − 1 |
| `0x0062c4d8` | `tr::UpgradeManager::getBikeIDbyIndex(int)` | `add w0,w1,#1` |
| `0x0061d350` | `tr::PlayerItems::getCustomBikeTextureItemId(int bikeId)` | `getBikeIndexByID(bikeId) + 0x299`（0x299 = 665） |
| `0x0061c04c` | `tr::PlayerItems::getCustomBikeTextures(int bikeId)` | 循环 `(1 << i) & mask`，返回已拥有的 SkinIndex 列表 |
| `0x0061d4e8` | `tr::PlayerItems::hasCustomBikeTexture(int bikeId, int skinIndex)` | `skinIndex == -1` 直接返回 1，否则测位 |
| `0x0061d378` | `tr::PlayerItems::getActiveCustomBikeTexture(int bikeId)` | 解 active 后再查 `isCustomSkinSupported`，不支持返回 0 |
| `0x0061d570` | `tr::PlayerItems::setActiveCustomBikeTexture(int bikeId, int skinIndex)` | `w11 = 0x01000000 + (skinIndex << 24)`；`bfxil w11,w10,#7,#0x18`（保留低 24 位的 bit7..30） |
| `0x0062b4c4` | `tr::UpgradeManager::isCustomSkinSupported(int bikeID, int skinIndex)` | 读配置 `bikeID*0x18 + skinIndex - 0x18` → `UpgradeManager + 0x18c`，`!= -1` 即支持 |

⚠ **内存里的 XOR/rotate 只是反作弊混淆，不在 JSON 里**：RAM 中 `m_items[i]` 存的是
`raw = rol(M, 7) ^ 0x0AB1D4F5` 这类形式（`getCustomBikeTextures` 用 `ror(raw ^ 0x0AB1D4F5, 7)`、
`getActiveCustomBikeTexture` 用 `(byte3(ror(raw,7)) ^ 0xEA) - 1`），而**存档 JSON 存的是明文 M**
（上表 6 条只有按明文解释才自洽）。`0x0AB1D4F5` 是**全局的数值混淆常量**，不是涂装专用
（`tmp/skinconst.py` 扫全库命中 43 处，包括 `PlayerItems::getItemCount`、`PlayerTimers::TimedAction::start`、
`PlayTierReward::setDiamondRewardAmount`）。

官方名：108 款里只有 **66 款**被商店/奖励表引用过（`Type == 2` 记录的 `ItemId` = `SkinData.ID`，
`NameId` 形如 `WSB_RIPTIDE_SNAKEBITE_TITLE`），其中 **67 款有官方中文名**（"Snake Bite paint job for the Riptide"
/ "激流蛇咬涂装"；另有 11 条名字只在解析失败的 `0010_1854657d.bin` 的原始文本里，见 §9 的运行记录）。
没有官方名的显示内部名（Boogeyman / SANDSTORM / TURTLE …）。

服务端怎么发：`tflocal_accounts.grantable_paints()` 给出 `{id: {key, slot, bike, name}}`，
`_paint_value(cur, slot)` = `int(cur or 0) | (1 << slot)`，若高 8 位为 0 再顺手 `|= (slot+1) << 24`；
后台按「车」分组列（`paints` 段），勾一款 = 给那一位置 1。**只有 24 位可用**，所以校验 `0 <= slot < 24`。

---

## 4. 服装 — rider outfits

### 4a. Outfit **parts** that have a real item ID (3 per outfit: helmet / upper / lower)

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `205` | `RIDER_01_HELMET_ON` — Dogfighter Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `206` | `RIDER_01_UPPER_ON` — Dogfighter Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `207` | `RIDER_01_LOWER_ON` — Dogfighter Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `215` | `RIDER_04_HELMET_ON` — Gladiator Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `216` | `RIDER_04_UPPER_ON` — Gladiator Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `217` | `RIDER_04_LOWER_ON` — Gladiator Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `220` | `RIDER_05_HELMET_ON` — Butcher Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `221` | `RIDER_05_UPPER_ON` — Butcher Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `222` | `RIDER_05_LOWER_ON` — Butcher Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `225` | `RIDER_07_HELMET_ON` — Cooler Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `226` | `RIDER_07_UPPER_ON` — Cooler Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `227` | `RIDER_07_LOWER_ON` — Cooler Bottom. | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `235` | `RIDER_06_HELMET_ON` — Hipster Helmet | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `236` | `RIDER_06_UPPER_ON` — Hipster Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `237` | `RIDER_06_LOWER_ON` — Hipster Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `241` | `RIDER_02_UPPER_ON` — Scarf Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `242` | `RIDER_02_LOWER_ON` — Scarf Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `246` | `RIDER_10_UPPER_ON` — Diver Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `247` | `RIDER_10_LOWER_ON` — Diver Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `290` | `RIDER_21_HELMET_ON` — The Soldier Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `291` | `RIDER_21_UPPER_ON` — The Soldier Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `292` | `RIDER_21_LOWER_ON` — The Soldier lower | 服装 / rider outfit part (lower), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `295` | `RIDER_19_HELMET_ON` — Pumpkin King top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `296` | `RIDER_19_UPPER_ON` — Pumpkin King middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `297` | `RIDER_19_LOWER_ON` — Pumpkin King lower | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `530` | `RIDER_27_HELMET_ON` — Death Knight Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `531` | `RIDER_27_UPPER_ON` — Death Knight Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `532` | `RIDER_27_LOWER_ON` — Death Knight Legs | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `542` | `RIDER_25_LOWER_ON` — Snowfox Lower | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `545` | `RIDER_26_HELMET_ON` — Polar Vortex Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `546` | `RIDER_26_UPPER_ON` — Polar Vortex Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `547` | `RIDER_26_LOWER_ON` — Polar Vortex lower | 服装 / rider outfit part (lower), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `550` | `RIDER_28_HELMET_ON` — The Yeti | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `551` | `RIDER_28_UPPER_ON` — The Yeti | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `552` | `RIDER_28_LOWER_ON` — The Yeti | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `555` | `RIDER_29_HELMET_ON` — Arctic Explorer Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `556` | `RIDER_29_UPPER_ON` — Arctic Explorer Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `557` | `RIDER_29_LOWER_ON` — Arctic Explorer Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `560` | `RIDER_30_HELMET_ON` — The Cowgirl | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `561` | `RIDER_30_UPPER_ON` — The Cowgirl | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `562` | `RIDER_30_LOWER_ON` — The Cowgirl | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `570` | `RIDER_32_HELMET_ON` — The Convict | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `571` | `RIDER_32_UPPER_ON` — The Convict | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `572` | `RIDER_32_LOWER_ON` — The Convict | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `575` | `RIDER_33_HELMET_ON` — The Sheriff | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `576` | `RIDER_33_UPPER_ON` — The Sheriff | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `577` | `RIDER_33_LOWER_ON` — The Sheriff | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `720` | `RIDER_36_HELMET_ON` — Indie Rider Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `721` | `RIDER_36_UPPER_ON` — Indie Rider Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `722` | `RIDER_36_LOWER_ON` — Indie Rider bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `725` | `RIDER_37_HELMET_ON` — Henchman Uniform Orange | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `726` | `RIDER_37_UPPER_ON` — Henchman Uniform Orange | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `727` | `RIDER_37_LOWER_ON` — Henchman Uniform Orange | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `735` | `RIDER_44_HELMET_ON` — The Gunslinger | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `736` | `RIDER_44_UPPER_ON` — The Gunslinger | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `737` | `RIDER_44_LOWER_ON` — The Gunslinger | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `775` | `RIDER_48_HELMET_ON` — The Undead Rider | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `776` | `RIDER_48_UPPER_ON` — The Undead Rider | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `777` | `RIDER_48_LOWER_ON` — The Undead Rider | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `780` | `RIDER_49_HELMET_ON` — The Hillbilly top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `781` | `RIDER_49_UPPER_ON` — The Hillbilly middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `782` | `RIDER_49_LOWER_ON` — The Hillbilly bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `785` | `RIDER_50_HELMET_ON` — Christmas Gal | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `786` | `RIDER_50_UPPER_ON` — Christmas Gal | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `787` | `RIDER_50_LOWER_ON` — Christmas Gal | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `795` | `RIDER_53_HELMET_ON` — Holiday Scarf | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `796` | `RIDER_53_UPPER_ON` — Holiday Scarf | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `797` | `RIDER_53_LOWER_ON` — Holiday Scarf | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `805` | `RIDER_54_HELMET_ON` — KTM Gear Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `806` | `RIDER_54_UPPER_ON` — KTM Gear Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `807` | `RIDER_54_LOWER_ON` — KTM Gear lower | 服装 / rider outfit part (lower), catalog `Type` **0** | `dailyrewards.txt` @0x00d894 |
| `815` | `RIDER_56_HELMET_ON` — The Temple Rider Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `816` | `RIDER_56_UPPER_ON` — The Temple Rider Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `817` | `RIDER_56_LOWER_ON` — The Temple Rider Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `820` | `RIDER_57_HELMET_ON` — Ninja | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `821` | `RIDER_57_UPPER_ON` — Ninja | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `822` | `RIDER_57_LOWER_ON` — Ninja | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `830` | `RIDER_59_HELMET_ON` — Halloween Lady | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `831` | `RIDER_59_UPPER_ON` — Halloween Lady | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `832` | `RIDER_59_LOWER_ON` — Halloween Lady | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `842` | `RIDER_61_LOWER_ON` — Redbull Leg | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `845` | `RIDER_62_HELMET_ON` — Heartbreak Kit | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `846` | `RIDER_62_UPPER_ON` — Heartbreak Kit | 服装 / rider outfit part (upper), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `847` | `RIDER_62_LOWER_ON` — Heartbreak Kit | 服装 / rider outfit part (lower), catalog `Type` **0** | `wts_rewards.txt` @0x02c514 |
| `1101` | `RIDER_63_UPPER_ON` — VENGEANCE KNIGHT Uniform Bottom | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1102` | `RIDER_63_LOWER_ON` — VENGEANCE KNIGHT Uniform Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1105` | `RIDER_64_HELMET_ON` — Feaster Bunny Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1106` | `RIDER_64_UPPER_ON` — Feaster Bunny Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1107` | `RIDER_64_LOWER_ON` — Feaster Bunny bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1110` | `RIDER_65_HELMET_ON` — BUTCH SUTE Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1111` | `RIDER_65_UPPER_ON` — BUTCH SUTE Head | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1112` | `RIDER_65_LOWER_ON` — BUTCH SUTE Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1115` | `RIDER_66_HELMET_ON` — Reputed Hero Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1116` | `RIDER_66_UPPER_ON` — Reputed Hero Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1117` | `RIDER_66_LOWER_ON` — Reputed Hero Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1120` | `RIDER_67_HELMET_ON` — Neon Freeze Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1121` | `RIDER_67_UPPER_ON` — Neon Freeze Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1122` | `RIDER_67_LOWER_ON` — Neon Freeze Head | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1125` | `RIDER_68_HELMET_ON` — Neon Blaze Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1126` | `RIDER_68_UPPER_ON` — Neon Blaze Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1127` | `RIDER_68_LOWER_ON` — Neon Blaze Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1130` | `RIDER_69_HELMET_ON` — The Wurst Racer | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1131` | `RIDER_69_UPPER_ON` — The Wurst Racer | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1132` | `RIDER_69_LOWER_ON` — The Wurst Racer | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1140` | `RIDER_72_HELMET_ON` — Ted- Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1141` | `RIDER_72_UPPER_ON` — Ted- Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1142` | `RIDER_72_LOWER_ON` — Ted- Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1185` | `RIDER_74_HELMET_ON` — The Sno-Rider Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1186` | `RIDER_74_UPPER_ON` — The Sno-Rider Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1187` | `RIDER_74_LOWER_ON` — The Sno-Rider Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1190` | `RIDER_75_HELMET_ON` — Chris Wheels Caper Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1191` | `RIDER_75_UPPER_ON` — Chris Wheels Caper Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1192` | `RIDER_75_LOWER_ON` — Chris Wheels Caper Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1195` | `RIDER_76_HELMET_ON` — The Deputy Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1196` | `RIDER_76_UPPER_ON` — The Deputy Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1197` | `RIDER_76_LOWER_ON` — The Deputy Legs | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1200` | `RIDER_77_HELMET_ON` — Nutjob frank - Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1201` | `RIDER_77_UPPER_ON` — Nutjob frank - Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1202` | `RIDER_77_LOWER_ON` — Nutjob frank - Lower | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1205` | `RIDER_78_HELMET_ON` — The Speedrunner Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1206` | `RIDER_78_UPPER_ON` — The Speedrunner Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1207` | `RIDER_78_LOWER_ON` — The Speedrunner Legs | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1210` | `RIDER_79_HELMET_ON` — Bad Bone SR-HEAD | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1211` | `RIDER_79_UPPER_ON` — Bad Bone SR-Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1212` | `RIDER_79_LOWER_ON` — Bad Bone SR-Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1220` | `RIDER_81_HELMET_ON` — The Trials Rising Head | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1221` | `RIDER_81_UPPER_ON` — The Trials Rising Torso | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1222` | `RIDER_81_LOWER_ON` — The Trials Rising bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1225` | `RIDER_82_HELMET_ON` — Orbie Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1226` | `RIDER_82_UPPER_ON` — Orbie Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1227` | `RIDER_82_LOWER_ON` — Orbie Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1230` | `RIDER_83_HELMET_ON` — HD-Asphalt Feeder - Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1231` | `RIDER_83_UPPER_ON` — HD-Asphalt Feeder - Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1232` | `RIDER_83_LOWER_ON` — HD-Asphalt Feeder - Leg | 服装 / rider outfit part (lower), catalog `Type` **0** | `wheelspecials.txt` @0x02a354 |
| `1280` | `RIDER_84_HELMET_ON` — Moonrider - Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1281` | `RIDER_84_UPPER_ON` — Moonrider - Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1282` | `RIDER_84_LOWER_ON` — Moonrider - Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1285` | `RIDER_85_HELMET_ON` — JUNGLE_EXPLORER - Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1286` | `RIDER_85_UPPER_ON` — JUNGLE_EXPLORER - Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1287` | `RIDER_85_LOWER_ON` — JUNGLE_EXPLORER - Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1290` | `RIDER_86_HELMET_ON` — Dr Cool - Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1291` | `RIDER_86_UPPER_ON` — Dr Cool - Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1292` | `RIDER_86_LOWER_ON` — Dr Cool - Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1295` | `RIDER_87_HELMET_ON` — Madcap Elf - Top | 服装 / rider outfit part (helmet), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1296` | `RIDER_87_UPPER_ON` — Madcap Elf - Middle | 服装 / rider outfit part (upper), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |
| `1297` | `RIDER_87_LOWER_ON` — Madcap Elf - Bottom | 服装 / rider outfit part (lower), catalog `Type` **0** | `pvp_match_rewards.txt` @0x01d4f4 |

Outfit parts are **not** derived by a formula from the rider index; each outfit is hand-allocated a
block of 3 consecutive IDs (helmet, upper, lower). Known blocks: 235–237 Hipster, 240–242 Scarf,
245–247 Diver, 205–207 Dogfighter, 550–552 Yeti, 560–562 Cowgirl, 570–572 Convict, 575–577 Sheriff,
725–727 Henchman Orange, 735–737 Gunslinger, 775–777 Undead Rider, 795–797 Holiday Scarf,
820–822 Ninja, 845–847 Heartbreak Kit.

### 4b. Rider outfit catalogue (rider index → name; the index is NOT an item ID)

Source: `content.dat entry #7 (/conf/customization.txt) @0x00af74` → `Rider` (80 entries). `HelmetOnIcon` is `/MENUZ/HOMESHACK/RIDER_<nn>_HELMET_ON.PNG`.
Beware: the `RIDER_<nn>` art index only tracks the list position for the first ~20 outfits.

| rider index | name/key | item type | where it came from |
|---|---|---|---|
| `0` | The Survivor | 服装 / rider outfit — art RIDER_00 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[0] |
| `1` | The Dogfighter | 服装 / rider outfit — art RIDER_01 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[1] |
| `2` | The Stuntman | 服装 / rider outfit — art RIDER_20 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[2] |
| `3` | The Gladiator | 服装 / rider outfit — art RIDER_04 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[3] |
| `4` | The Butcher | 服装 / rider outfit — art RIDER_05 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[4] |
| `5` | The Cooler | 服装 / rider outfit — art RIDER_07 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[5] |
| `6` | The Samsarian | 服装 / rider outfit — art RIDER_09 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[6] |
| `7` | The Hipster | 服装 / rider outfit — art RIDER_06 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[7] |
| `8` | The Scarf | 服装 / rider outfit — art RIDER_02 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[8] |
| `9` | The Diver | 服装 / rider outfit — art RIDER_10 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[9] |
| `10` | The Rebel | 服装 / rider outfit — art RIDER_08 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[10] |
| `11` | The Priest | 服装 / rider outfit — art RIDER_11 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[11] |
| `12` | The Enforcer | 服装 / rider outfit — art RIDER_12 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[12] |
| `13` | The Goon | 服装 / rider outfit — art RIDER_13 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[13] |
| `14` | The Cyberpunk | 服装 / rider outfit — art RIDER_14 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[14] |
| `15` | The Platinum Knight | 服装 / rider outfit — art RIDER_15 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[15] |
| `16` | The Cyborg | 服装 / rider outfit — art RIDER_16 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[16] |
| `17` | The Eggman | 服装 / rider outfit — art RIDER_17 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[17] |
| `18` | The Soldier | 服装 / rider outfit — art RIDER_21 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[18] |
| `19` | The Pumpkin King | 服装 / rider outfit — art RIDER_19 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[19] |
| `20` | Ancient Guardian | 服装 / rider outfit — art RIDER_18 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[20] |
| `21` | Manbird | 服装 / rider outfit — art RIDER_22 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[21] |
| `22` | Cornelius Costume | 服装 / rider outfit — art RIDER_23 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[22] |
| `23` | Death Knight | 服装 / rider outfit — art RIDER_27 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[23] |
| `24` | The Mountaineer | 服装 / rider outfit — art RIDER_24 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[24] |
| `25` | Snowfox | 服装 / rider outfit — art RIDER_25 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[25] |
| `26` | Polar Vortex | 服装 / rider outfit — art RIDER_26 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[26] |
| `27` | The Yeti | 服装 / rider outfit — art RIDER_28 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[27] |
| `28` | Arctic Explorer | 服装 / rider outfit — art RIDER_29 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[28] |
| `29` | The Cowgirl | 服装 / rider outfit — art RIDER_30 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[29] |
| `30` | The Native Warrior | 服装 / rider outfit — art RIDER_31 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[30] |
| `31` | The Convict | 服装 / rider outfit — art RIDER_32 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[31] |
| `32` | The Sheriff | 服装 / rider outfit — art RIDER_33 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[32] |
| `33` | Henchman Uniform Black | 服装 / rider outfit — art RIDER_34 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[33] |
| `34` | Super Spy Black | 服装 / rider outfit — art RIDER_35 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[34] |
| `35` | Indie Rider | 服装 / rider outfit — art RIDER_36 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[35] |
| `36` | Henchman Uniform Orange | 服装 / rider outfit — art RIDER_37 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[36] |
| `37` | Super Spy White | 服装 / rider outfit — art RIDER_38 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[37] |
| `38` | The Gunslinger | 服装 / rider outfit — art RIDER_44 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[38] |
| `39` | The High Roller | 服装 / rider outfit — art RIDER_45 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[39] |
| `40` | Hungry Shark | 服装 / rider outfit — art RIDER_47 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[40] |
| `41` | The Undead Rider | 服装 / rider outfit — art RIDER_48 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[41] |
| `42` | Hillbilly | 服装 / rider outfit — art RIDER_49 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[42] |
| `43` | Christmas Gal | 服装 / rider outfit — art RIDER_50 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[43] |
| `44` | Sugar Daddy | 服装 / rider outfit — art RIDER_51 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[44] |
| `45` | Holiday Scarf | 服装 / rider outfit — art RIDER_53 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[45] |
| `46` | MUMMY_BOY | 服装 / rider outfit — art RIDER_71 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[46] |
| `47` | KTM Gear | 服装 / rider outfit — art RIDER_54 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[47] |
| `48` | THE_KING | 服装 / rider outfit — art RIDER_55 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[48] |
| `49` | INDIANA_JONES | 服装 / rider outfit — art RIDER_56 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[49] |
| `50` | NINJA | 服装 / rider outfit — art RIDER_57 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[50] |
| `51` | HALLOWEEN_MAN | 服装 / rider outfit — art RIDER_58 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[51] |
| `52` | HALLOWEEN_LADY | 服装 / rider outfit — art RIDER_59 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[52] |
| `53` | KTM450_RALLY | 服装 / rider outfit — art RIDER_60 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[53] |
| `54` | REDBULL | 服装 / rider outfit — art RIDER_61 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[54] |
| `55` | HEARTBRAKE_KIT | 服装 / rider outfit — art RIDER_62 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[55] |
| `56` | VENGEANCE_KNIGHT | 服装 / rider outfit — art RIDER_63 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[56] |
| `57` | FEASTER_BUNNY | 服装 / rider outfit — art RIDER_64 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[57] |
| `58` | BUTCH_SUTE | 服装 / rider outfit — art RIDER_65 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[58] |
| `59` | REPUTED_HERO | 服装 / rider outfit — art RIDER_66 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[59] |
| `60` | NEON_FREEZE | 服装 / rider outfit — art RIDER_67 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[60] |
| `61` | NEON_BLAZE | 服装 / rider outfit — art RIDER_68 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[61] |
| `62` | WURST_RACER | 服装 / rider outfit — art RIDER_69 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[62] |
| `63` | BMW_RACER | 服装 / rider outfit — art RIDER_70 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[63] |
| `64` | TED | 服装 / rider outfit — art RIDER_72 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[64] |
| `65` | CLAWGIRL | 服装 / rider outfit — art RIDER_73 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[65] |
| `66` | XGAMES | 服装 / rider outfit — art RIDER_74 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[66] |
| `67` | CHRIS_WHEELS_CAPER | 服装 / rider outfit — art RIDER_75 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[67] |
| `68` | THE_DEPUTY | 服装 / rider outfit — art RIDER_76 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[68] |
| `69` | NUTJOB_FRANK | 服装 / rider outfit — art RIDER_77 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[69] |
| `70` | THE SPEEDRUNNER | 服装 / rider outfit — art RIDER_78 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[70] |
| `71` | BAD_BONE_SR | 服装 / rider outfit — art RIDER_79 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[71] |
| `72` | STUNTMAN_ANTTI_OUTFIT | 服装 / rider outfit — art RIDER_80 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[72] |
| `73` | TRAILS RISING OUTFIT | 服装 / rider outfit — art RIDER_81 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[73] |
| `74` | ORBIE | 服装 / rider outfit — art RIDER_82 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[74] |
| `75` | HARLEY_DAVIDSON_RIDER | 服装 / rider outfit — art RIDER_83 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[75] |
| `76` | MOONRIDER | 服装 / rider outfit — art RIDER_84 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[76] |
| `77` | JUNGLE_EXPLORER | 服装 / rider outfit — art RIDER_85 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[77] |
| `78` | Dr Cool | 服装 / rider outfit — art RIDER_86 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[78] |
| `79` | Madcap Elf | 服装 / rider outfit — art RIDER_87 | `content.dat entry #7 (/conf/customization.txt) @0x00af74` Rider[79] |

---

## 5. 摩托蓝图 — bike blueprints, and the bike catalogue

### 5a. Blueprint item IDs

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `374` | Tango Blueprint Piece | 摩托蓝图 / bike blueprint | `dailyrewards.txt` @0x00d894 (`/MENUZ/ITEM/BLUEPRINT_TIERI.PNG`) |
| `379` | Bronco Blueprint Piece | 摩托蓝图 / bike blueprint | `dailyrewards.txt` @0x00d894 (`/MENUZ/ITEM/BLUEPRINT_TIERI.PNG`) |
| `414` | Stallion x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_9.PNG`) |
| `419` | Agent x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_10.PNG`) |
| `429` | KTM 500 x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_12.PNG`) |
| `434` | KTM 450 x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_13.PNG`) |
| `439` | Bandito Bike Blueprint Piece | 摩托蓝图 / bike blueprint | `wheelspecials.txt` @0x02a354 (`/MENUZ/ITEM/BLUEPRINT_14.PNG`) |
| `444` | BMW F800 GS x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_15.PNG`) |
| `449` | HD XG750R x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_16.PNG`) |
| `454` | HD Electric x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_17.PNG`) |
| `459` | Donkey x2 | 摩托蓝图 / bike blueprint | `wts_rewards.txt` @0x02c514 (`/MENUZ/ITEM/BLUEPRINT_18.PNG`) |

**Formula (inferred, but consistent for every blueprint observed).** The blueprint atlas entry
is `/MENUZ/ITEM/BLUEPRINT_<nn>.PNG` and the item ID is

```
blueprint ItemId = 369 + 5 * nn          (nn = the numeric suffix of BLUEPRINT_<nn>.PNG)
=> nn = (ItemId - 369) / 5
```

| atlas | ItemId | bike (Upgrades ID / N) | observed in |
|---|---|---|---|
| `BLUEPRINT_9` | `414` | 10 / STALLION | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_10` | `419` | 11 / AGENT | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_12` | `429` | 13 / KTM 500-EXC | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_13` | `434` | 14 / KTM 450 Rally | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_14` | `439` | 15 / BANDITO | `wheelspecials.txt` @0x02a354 |
| `BLUEPRINT_15` | `444` | 16 / BMW F 800 GS | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_16` | `449` | 17 / HARLEY-DAVIDSON XG750R | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_17` | `454` | 18 / HARLEY-DAVIDSON EV | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_18` | `459` | 19 / DONKEY | `wts_rewards.txt` @0x02c514 |
| `BLUEPRINT_TIERI` | `374` | tier-1 blueprint atlas shared by the starter bikes (Tango Blueprint Piece) | `dailyrewards.txt` @0x00d894 |
| `BLUEPRINT_TIERI` | `379` | tier-1 blueprint atlas shared by the starter bikes (Bronco Blueprint Piece) | `dailyrewards.txt` @0x00d894 |

Check: `369+5*9=414` Stallion, `369+5*10=419` Agent, `369+5*18=459` Donkey — matches every row above.
The atlas index runs one ahead of the `upgrades.txt` bike ID (`BLUEPRINT_9` → `Upgrades[10] STALLION`).
Blueprint slots for nn 3–8 and 11 (`384 389 394 399 404 409 424`) are **not referenced by any reward
catalog in this build**, so those IDs are inferred from the formula only and are marked as such.

### 5b. Bike catalogue (BikeData keys — these are *bike* indexes, not item IDs)

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `1` | Armadillo | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[1] — BikeType 0, Tier 0, GarageOrder 0 |
| `2` | Tango | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[2] — BikeType 1, Tier 0, GarageOrder 1 |
| `3` | Bronco | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[3] — BikeType 2, Tier 0, GarageOrder 2 |
| `4` | Jackal | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[4] — BikeType 0, Tier 1, GarageOrder 6 |
| `5` | Mantis | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[5] — BikeType 1, Tier 1, GarageOrder 7 |
| `6` | Marauder | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[6] — BikeType 2, Tier 1, GarageOrder 8 |
| `7` | Riptide | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[7] — BikeType 0, Tier 2, GarageOrder 10 |
| `8` | Berserker | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[8] — BikeType 1, Tier 2, GarageOrder 11 |
| `9` | Phantom | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[9] — BikeType 2, Tier 2, GarageOrder 12 |
| `10` | Stallion | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[10] — BikeType 0, Tier 255, GarageOrder 16 |
| `11` | BMW | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[11] — BikeType 2, Tier 255, GarageOrder 17 |
| `12` | Moonrover | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[12] — BikeType None, Tier 255, GarageOrder 18 |
| `13` | KTM 500 EXC | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[13] — BikeType 3, Tier 0, GarageOrder 4 |
| `14` | KTM 450 RALLY | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[14] — BikeType 3, Tier 1, GarageOrder 9 |
| `15` | BANDITO | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[15] — BikeType 2, Tier 0, GarageOrder 3 |
| `16` | BMW F800 GS | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[16] — BikeType 2, Tier 2, GarageOrder 13 |
| `17` | HD | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[17] — BikeType 1, Tier 2, GarageOrder 14 |
| `18` | HD EV | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[18] — BikeType 1, Tier 0, GarageOrder 5 |
| `19` | Donkey | 摩托 / bike (BikeData key) | `content.dat entry #2 (/conf/bikes.txt) @0x009774` BikeData[19] — BikeType 1, Tier 255, GarageOrder 15 |

Blueprint counts per bike come from `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` → `Upgrades[].BP`:

| bike (Upgrades ID / N) | BP | where it came from |
|---|---|---|
| 1 / ARMADILLO | 4 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[1] |
| 2 / TANGO | 4 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[2] |
| 3 / BRONCO | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[3] |
| 4 / JACKAL | 10 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[4] |
| 5 / MANTIS | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[5] |
| 6 / MARAUDER | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[6] |
| 7 / RIPTIDE | 10 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[7] |
| 8 / BERSERKER | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[8] |
| 9 / PHANTOM | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[9] |
| 10 / STALLION | 50 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[10] |
| 11 / AGENT | 50 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[11] |
| 12 / PASILA | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[12] |
| 13 / KTM 500-EXC | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[13] |
| 14 / KTM 450 Rally | 30 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[14] |
| 15 / BANDITO | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[15] |
| 16 / BMW F 800 GS | 50 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[16] |
| 17 / HARLEY-DAVIDSON XG750R | 50 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[17] |
| 18 / HARLEY-DAVIDSON EV | 50 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[18] |
| 19 / DONKEY | 50 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[19] |
| 20 / KUMPULA | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[20] |
| 21 / KONALA | 20 | `content.dat entry #45 (/conf/upgrades.txt) @0x027bf4` Upgrades[21] |

> In `giftbox.txt` a blueprint is written `{"IID": <bike index>, "IL": 4, "IC": 1}` — e.g.
> Berserker IID 80, Agent IID 83, Donkey IID 91. In `wts_rewards.txt`/`wheelspecials.txt` the same
> blueprints appear directly as ItemIds 419 (Agent), 434 (KTM 450), 444 (BMW F800 GS),
> 449 (HD XG750R), 454 (HD Electric), 459 (Donkey), each with `ItemAmount: 2` (“x2”).

---

## 6. 地图/赛道 — tracks and track pieces

Track item IDs are exactly the `ID` field of `content.dat entry #18 (/conf/levels.txt) @0x012214` → `Levels`. `Type: 1` = full track,
`Type: 3` = track piece (`/MENUZ/ITEM/TRACK_PIECE.PNG`). “Grantable as a reward” lists the
reward catalog(s) that actually hand the track out.

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `1` | LVL_NIGHT_LIFE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1 |
| `2` | LVL_PIKE_ALLEY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 2 |
| `4` | LVL_ROCKY_DESERT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 4 |
| `8` | LVL_THE_WATCHERS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 8 |
| `28` | LVL_ROCKS_OFF | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 28 |
| `100` | LVL_THE_CAVE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 100 |
| `1023` | LVL_THE_LIFT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1023 |
| `1024` | LVL_URBAN_JUNGLE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1024 |
| `1026` | LVL_THE_TREBUCHET | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1026 |
| `1027` | LVL_DROP_ZONE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1027 |
| `1029` | LVL_FORT_RUINS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1029 |
| `1031` | LVL_WALL_CRACK | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1031 |
| `1032` | LVL_DUST_BOWL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1032 |
| `1033` | LVL_THREE_BRIDGES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1033 |
| `1034` | LVL_OLD_CITY_WALL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1034 |
| `1036` | LVL_MARKET_STREET | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1036 |
| `1037` | LVL_ROOFTOPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1037 |
| `1040` | LVL_BURNYARD | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1040 |
| `1041` | LVL_PIPELINE_CAMP | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1041 |
| `1045` | LVL_LOST_PLAYGROUND | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1045 |
| `1048` | LVL_WOLF_DEN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1048 |
| `1050` | LVL_GHOST_TOWN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1050 |
| `1051` | LVL_THE_BEAMERY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1051 |
| `1052` | LVL_STEAM_QUARTER | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1052 |
| `1054` | LVL_CRACKED_RESERVOIR | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1054 |
| `1055` | LVL_CRANE_PEEK | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1055 |
| `1056` | LVL_BOUNCY_HILLS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1056 |
| `1062` | LVL_MOONLIGHT_TOWERS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1062 |
| `1068` | LVL_PARCHED_CLIFF | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1068 |
| `1069` | LVL_WELL_PARK | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1069 |
| `1070` | LVL_PIPE_BASIN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1070 |
| `1072` | LVL_DEADWOOD_VALLEY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1072 |
| `1074` | LVL_DESERT_GONDOLA | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1074 |
| `1075` | LVL_THE_ARCHES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1075 |
| `1082` | LVL_CRANE_YARD | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1082 |
| `1083` | LVL_SMUGGLER_TUNNEL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1083 |
| `1084` | LVL_THE_REFINERY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1084 |
| `1085` | LVL_PLANKS_AND_MOZZIES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1085 |
| `1087` | LVL_HINGED_PATHWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1087 |
| `1088` | LVL_CANNON_RIDGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1088 |
| `1089` | LVL_THE_TANKTOPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1089 |
| `1090` | LVL_ROCK_WALL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1090 |
| `1091` | LVL_SEWAGE_TREATMENT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1091 |
| `1092` | LVL_TROJAN_GIRAFFE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1092 |
| `1093` | LVL_THE_STACKS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1093 |
| `1094` | LVL_THE_PURIFIER | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1094 |
| `1095` | LVL_LOOKOUT_POINT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1095 |
| `1097` | LVL_CAVE_ENTRANCE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1097 |
| `1098` | LVL_TREE_HOUSES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1098 |
| `1099` | LVL_BURNING_BUSHES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1099 |
| `1100` | LVL_THE_MILL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1100 |
| `1101` | LVL_THE_GRINDHOUSE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1101 |
| `1102` | LVL_SPINNERS_ALLEY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1102 |
| `1103` | LVL_SCORCHED_BATTLEMENT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1103 |
| `1105` | LVL_COAL_TOWN — WST_COAL_TOWN_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1105 |
| `1106` | LVL_THE_AQUEDUCT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1106 |
| `1107` | LVL_CANARY_STREET — WST_CANARY_STREET_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1107 |
| `1108` | LVL_CANNON_END — WST_CANNON_END_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1108 |
| `1109` | LVL_WOOD_SWITCH_CITY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1109 |
| `1110` | LVL_BALANCE_AVENUE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1110 |
| `1111` | LVL_HILLTOP_CHETTO | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1111 |
| `1112` | LVL_TRAPEZE_CHURN — WST_TRAPEZE_CHURN_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1112 |
| `1113` | LVL_FLOODED_HIGHWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1113 |
| `1115` | LVL_THE_WATERWHEEL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1115 |
| `1116` | LVL_BACKYARD_CATWALK | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1116 |
| `1119` | LVL_TROLL_LAIR | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1119 |
| `1120` | LVL_STEEPLE_RUN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1120 |
| `1121` | LVL_COASTER_CANYON | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1121 |
| `1122` | LVL_CASINO_ROOFTOP | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1122 |
| `1123` | LVL_BARREL_CHASE — WST_BARREL_CHASE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1123 |
| `1124` | LVL_FANG_WALL — WST_FANG_WALL_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1124 |
| `1125` | LVL_SUNSHINE_DISTRICT — WST_SUNSHINE_DISTRICT_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1125 |
| `1126` | LVL_ROCKY_ROAD | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1126 |
| `1127` | LVL_LOGGING_CAMP — WST_LOGGING_CAMP_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1127 |
| `1129` | LVL_DRIFTER_VALLEY — WST_DRIFTER_VALLEY_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1129 |
| `1130` | LVL_GARBAGE_ROUTE — WST_GARBAGE_ROUTE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1130 |
| `1131` | LVL_CAVE_DWELLER | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1131 |
| `1132` | LVL_LAZY_CATAPULT — WST_LAZY_CATAPULT_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1132 |
| `1133` | LVL_SUNSET_DUNGEON | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1133 |
| `1134` | LVL_ROAD_TO_RUIN — LVL_ROAD_TO_RUIN | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1134 |
| `1135` | LVL_CITY_OUTSKIRTS — WST_CITY_OUTSKIRTS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1135 |
| `1136` | LVL_ARCH_RUINS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1136 |
| `1137` | LVL_RISKY_ROOFTOPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1137 |
| `1138` | LVL_VAULT_CRAWL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1138 |
| `1139` | LVL_VILLAINOUS_HIDEOUT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1139 |
| `1140` | LVL_BUZZSAW_PARADISE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1140 |
| `1141` | LVL_FIRE_OASIS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1141 |
| `1142` | LVL_TRASH_TOPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1142 |
| `1143` | LVL_DARK_MACHINE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1143 |
| `1144` | LVL_THE_PENDULUM | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1144 |
| `1145` | LVL_MARSH_EDGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1145 |
| `1146` | LVL_ELEPHANT_GRAVEYARD — WST_ELEPHANT_GRAVEYARD_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1146 |
| `1147` | LVL_THE_QUAGMIRE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1147 |
| `1148` | LVL_BUGGY_TRACK | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1148 |
| `1149` | LVL_SERPENT_SLOUGH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1149 |
| `1150` | LVL_MONSTER_LAKE — LVL_MONSTER_LAKE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1150 |
| `1151` | LVL_MUSHROOM_HEIGHTS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1151 |
| `1152` | LVL_FLOWER_HILLS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1152 |
| `1153` | LVL_FROG_VILLAGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1153 |
| `1154` | LVL_MUD_CAKES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1154 |
| `1155` | LVL_FIREFLY_LANDING | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1155 |
| `1156` | LVL_CRASHED_CASTLE — WST_CRASHED_CASTLE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1156 |
| `1157` | LVL_TOAD_HOLE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1157 |
| `1158` | LVL_HOMEGROWN — WST_TORN_HOMEGROWN_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1158 |
| `1159` | LVL_ITCHY_JAWS — LVL_ITCHY_JAWS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1159 |
| `1160` | LVL_FENLAND_FLAIL — LVL_FENLAND_FLAIL | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1160 |
| `1161` | LVL_EXILE_PASS — LVL_EXILE_PASS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1161 |
| `1163` | LVL_TRIBAL_HOMESTEAD — WST_TRIBAL_HOMESTEAD_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1163 |
| `1164` | LVL_OPEN_JAW_BOG — LVL_OPEN_JAW_BOG | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1164 |
| `1165` | LVL_RAVENOUS_RAM | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1165 |
| `1166` | LVL_CRACKED_PLATEAU — WST_CRACKED_PLATEAU_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1166 |
| `1167` | LVL_STILTED_PATHWAY — WST_STILTED_PATHWAY_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1167 |
| `1168` | LVL_FAULT_VILLAGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1168 |
| `1169` | LVL_GREASE_TRANSIT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1169 |
| `1170` | LVL_DAREDEVIL_PARADISE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1170 |
| `1171` | LVL_MELANCHOLY_TEMPLE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1171 |
| `1172` | LVL_REFINERY_ABYSS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1172 |
| `1173` | LVL_FATALITY_LANE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1173 |
| `1174` | LVL_MERCHANDISE_STASH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1174 |
| `1175` | LVL_STUNTMAN_PLAZA | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1175 |
| `1176` | LVL_GRAND_MOONSHINE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1176 |
| `1177` | LVL_GIRDER_PRECINCT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1177 |
| `1178` | LVL_FLAMING_FREEWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1178 |
| `1179` | LVL_ALPHA_STREET | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1179 |
| `1180` | LVL_ROTTEN_RAILWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1180 |
| `1181` | LVL_DIAMOND_DASH — WST_DIAMOND_DASH_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1181 |
| `1182` | LVL_WIDOWMAKER | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1182 |
| `1183` | LVL_RITE_PASSAGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1183 |
| `1184` | LVL_MADHOUSE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1184 |
| `1185` | LVL_WOODWORK_CONCLAVE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1185 |
| `1186` | LVL_HOPE_SURRENDERS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1186 |
| `1187` | LVL_TORN_CANYON — WST_TORN_CANYON_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1187 |
| `1188` | LVL_CHOKING_HAZARD | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1188 |
| `1189` | LVL_DOOM_DROP — WST_DOOM_DROP_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1189 |
| `1190` | Prod30 Maria 1 | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1190 |
| `1191` | LVL_MINECART_DUMP — WST_MINECART_DUMP_TITLE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1191 |
| `1192` | LVL_EXPLOSIVE_STORAGE — WST_EXPLOSIVE_STORAGE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1192 |
| `1193` | LVL_CAVE_CROSSING — WST_CAVE_CROSSING_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1193 |
| `1194` | LVL_DELIVERY_LINE — WST_DELIVERY_LINE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1194 |
| `1195` | LVL_UNSTABLE_TUNNEL — WST_UNSTABLE_TUNNEL_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1195 |
| `1196` | LVL_CRYSTAL_KINGDOM — WST_CRYSTAL_KINGDOM_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1196 |
| `1197` | LVL_ABANDONED_MINE — WST_ABANDONED_MINE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1197 |
| `1198` | LVL_THE_SHAFT — WST_THE_SHAFT_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1198 |
| `1199` | LVL_FORBIDDEN_PATH — WST_FORBIDDEN_PATH_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1199 |
| `1201` | LVL_TRACTION_TESTGROUND — WST_TRACTION_TESTGROUND_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1201 |
| `1202` | LVL_WRECKED_TRACKS — WST_WRECKED_TRACKS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1202 |
| `1203` | LVL_WASTE_DISPOSAL — WST_WASTE_DISPOSAL_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1203 |
| `1204` | LVL_TERROR_TOWER — WST_TERROR_TOWER_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1204 |
| `1205` | LVL_HAUNTED_HALLOWS — WST_HAUNTED_HALLOWS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1205 |
| `1206` | LVL_PUMPKIN_PATCH — WST_PUMPKIN_PATCH_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1206 |
| `1207` | LVL_NIGHTMARE_GROTTO — WST_NIGHTMARE_GROTTO_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1207 |
| `1208` | LVL_SMELTING_POTS — WST_SMELTING_POTS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1208 |
| `1209` | LVL_UNDERGROUND_SLOPES — WST_UNDERGROUND_SLOPES_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1209 |
| `1210` | LVL_PROCESSING_CENTER — WST_PROCESSING_CENTER_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1210 |
| `1211` | LVL_SINE_CITY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1211 |
| `1212` | LVL_HILL_CLIMB | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1212 |
| `1213` | LVL_REDRUM_HILLS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1213 |
| `1214` | LVL_PEACEFUL_PUMMEL — LVL_PEACEFUL_PUMMEL | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1214 |
| `1215` | LVL_TOXIN_HARVEST — WST_TOXIN_HARVEST_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1215 |
| `1216` | LVL_ROOT_CANAL — LVL_ROOT_CANAL | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1216 |
| `1217` | LVL_GRAVITON_SWAMP | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1217 |
| `1218` | Flat | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1218 |
| `1219` | LVL_SUNKEN_SANCTUARY — LVL_SUNKEN_SANCTUARY | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1219 |
| `1220` | LVL_AMUSEMENT_PIT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1220 |
| `1221` | LVL_CONCEALED_ENTRYWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1221 |
| `1222` | LVL_CRYSTAL_CROSSING — LVL_CRYSTAL_CROSSING | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1222 |
| `1223` | LVL_ICE_BLOCKADE — WST_ICE_BLOCKADE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1223 |
| `1224` | LVL_PERMAFROST_CLIMB — WST_PERMAFROST_CLIMB_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1224 |
| `1225` | LVL_SLEDRIDGE_GORGE — WST_SLEDRIDGE_GORGE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1225 |
| `1226` | LVL_GREAT_WALL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1226 |
| `1227` | LVL_ICY_FOOTHILLS — WST_ICY_FOOTHILLS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1227 |
| `1228` | LVL_CONTAINER_GROUNDS — WST_CONTAINER_GROUNDS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1228 |
| `1229` | LVL_CHILLED_CLIFFS — WST_CHILLED_CLIFFS_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1229 |
| `1230` | LVL_SNOWBALL_RIDE — WST_SNOWBALL_RIDE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1230 |
| `1231` | LVL_FROSTY_PLUMBING — WST_FROSTY_PLUMBING_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1231 |
| `1232` | LVL_ICEBOUND_HAMLET — WST_ICEBOUND_HAMLET_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1232 |
| `1233` | LVL_BUNNYHOP | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1233 |
| `1234` | LVL_PENGUIN_LANDING — WST_PENGUIN_LANDING_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1234 |
| `1235` | LVL_CHOPPING_DISTRICT — WST_CHOPPING_DISTRICT_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1235 |
| `1236` | LVL_SQUALL_SLIDE — WST_SQUALL_SLIDE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1236 |
| `1237` | LVL_FROZEN_FACILITY — WST_FROZEN_FACILITY_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1237 |
| `1238` | LVL_SNOWMAN_HAVEN — WST_SNOWMAN_HAVEN_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1238 |
| `1239` | LVL_WALRUS_ROAD — WST_WALRUS_ROAD_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1239 |
| `1240` | LVL_FROSTMOORE — WST_FROSTMOORE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1240 |
| `1241` | LVL_TRIAL_OF_COURAGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1241 |
| `1242` | LVL_PLANT_FOOD — LVL_PLANT_FOOD | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1242 |
| `1243` | LVL_THE_ASSUMPTION — LVL_THE_ASSUMPTION | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1243 |
| `1244` | LVL_INDIGENOUS_VILLAGE — LVL_INDIGENOUS_VILLAGE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1244 |
| `1245` | LVL_FORGOTTEN_FACTORY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1245 |
| `1246` | LVL_METAL_MAYHEM — WST_METAL_MAYHEM_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1246 |
| `1247` | LVL_ENDLESS_WEALTH — LVL_ENDLESS_WEALTH | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1247 |
| `1248` | LVL_GEM_QUARRY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1248 |
| `1249` | LVL_PAIN_MARSH — LVL_PAIN_MARSH | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1249 |
| `1250` | LVL_LONGSHOT_LAKE — LVL_LONGSHOT_LAKE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1250 |
| `1251` | LVL_BARREN_STEPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1251 |
| `1252` | LVL_THE_BIG_SWING — WST_THE_BIG_SWING_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1252 |
| `1253` | LVL_THE_BELL_PIT — LVL_THE_BELL_PIT | 地图/赛道 (Track, catalog `Type` **1**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1253 |
| `1254` | LVL_NIGHTWATCH_HAVEN — Track: Nightwatch Haven | 地图/赛道 (Track, catalog `Type` **1**, grantable via `giftbox.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1254 |
| `1255` | Prod45 Ukkis 1 | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1255 |
| `1256` | LVL_COLLAPSED_ORCHARD | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1256 |
| `1257` | LVL_PRESENT_VILLAGE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1257 |
| `1258` | LVL_RIGGED_ROADWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1258 |
| `1259` | LVL_CROW_NEST | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1259 |
| `1260` | LVL_IMPACT_ATTICS — LVL_IMPACT_ATTICS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1260 |
| `1261` | LVL_ROADWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1261 |
| `1262` | LVL_VAGRANT_CAMP | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1262 |
| `1263` | LVL_NAUSEA_NIGHT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1263 |
| `1264` | LVL_OVERDOSE — LVL_OVERDOSE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1264 |
| `1265` | LVL_CITY_BLUES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1265 |
| `1266` | LVL_HOPS_OF_FURY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1266 |
| `1267` | LVL_PUMPKIN_DESERT — LVL_PUMPKIN_DESERT | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1267 |
| `1268` | LVL_CURVES_OF_DESTINY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1268 |
| `1269` | LVL_FEST_MINE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1269 |
| `1270` | LVL_RUINS_OF_DESPAIR — LVL_RUINS_OF_DESPAIR | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1270 |
| `1271` | LVL_DEATH_WHEEL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1271 |
| `1272` | LVL_DEVIL_HOPPING — LVL_DEVIL_HOPPING | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1272 |
| `1273` | LVL_CROW_ROOFS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1273 |
| `1274` | LVL_DARK_SANDS — LVL_DARK_SANDS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1274 |
| `1275` | LVL_BLACK_FOREST — LVL_BLACK_FOREST | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1275 |
| `1276` | LVL_LIFT_OF_DOOM — LVL_LIFT_OF_DOOM | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1276 |
| `1277` | LVL_SPIDER_KINGDOM — LVL_SPIDER_KINGDOM | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1277 |
| `1278` | LVL_HEADHURT_BLUFF | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1278 |
| `1279` | LVL_WORKSHOP_PATH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1279 |
| `1280` | LVL_SLICK_SLALOM | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1280 |
| `1281` | LVL_CANDYLAND — LVL_CANDYLAND | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1281 |
| `1282` | LVL_FROST_CARNIVAL — Track: Frost Carnival | 地图/赛道 (Track, catalog `Type` **1**, grantable via `giftbox.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1282 |
| `1283` | LVL_SKATER_PARADISE — LVL_LOST_DESCENT | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1283 |
| `1284` | LVL_THE_NAUGHTY_LIST — Track: The Naughty List | 地图/赛道 (Track, catalog `Type` **1**, grantable via `giftbox.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1284 |
| `1285` | LVL_BELL_TOWER — Track: Bell Tower | 地图/赛道 (Track, catalog `Type` **1**, grantable via `giftbox.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1285 |
| `1286` | LVL_SLED_LOADING_BAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1286 |
| `1287` | LVL_PEAKS_OF_PERIL — LVL_PEAKS_OF_PERIL | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1287 |
| `1288` | LVL_AVALANCHE_STREW — LVL_AVALANCHE_STREW | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1288 |
| `1289` | LVL_HIGH_TIDE_HEIGHTS — LVL_HIGH_TIDE_HEIGHTS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1289 |
| `1290` | LVL_LEAPING_HOLLOWS — LVL_LEAPING_HOLLOWS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1290 |
| `1291` | LVL_PETROL_FALLS_PATH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1291 |
| `1292` | LVL_MUDDY_MOUNDS — LVL_MUDDY_MOUNDS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1292 |
| `1293` | LVL_ENDURANCE_RUN — LVL_ENDURANCE_RUN | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1293 |
| `1294` | LVL_LOST_RACE_TRACK — LVL_LOST_RACE_TRACK | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1294 |
| `1295` | Donkey lvl | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1295 |
| `1296` | LVL_KTM_COURSE — WST_KTM_COURSE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1296 |
| `1297` | LVL_FACEPLANT_PRECINCT — LVL_FACEPLANT_PRECINCT | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1297 |
| `1298` | LVL_DERAILED — LVL_DERAILED | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1298 |
| `1299` | Prod55 Maria 3 | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1299 |
| `1300` | LVL_REJECTION_BLUES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1300 |
| `1301` | LVL_SAFE_ESCAPE — WST_SAFE_ESCAPE_TITLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1301 |
| `1302` | LVL_PEACE_HAMMER — LVL_PEACE_HAMMER | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1302 |
| `1303` | LVL_COLD_CUT_CORNER — LVL_COLD_CUT_CORNER | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1303 |
| `1304` | LVL_BAYOU_BOATRIDE — LVL_BAYOU_BOATRIDE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1304 |
| `1305` | LVL_ACROBAT_QUARTER — LVL_ACROBAT_QUARTER | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1305 |
| `1306` | LVL_RAZOR_DUNES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1306 |
| `1307` | LVL_TREACHERY — LVL_TREACHERY | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1307 |
| `1308` | LVL_LOST_DESCENT — LVL_LOST_DESCENT | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1308 |
| `1309` | LVL_FAIR_WINDS — LVL_FAIR_WINDS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1309 |
| `1310` | LVL_LOLLYGAGGING — LVL_LOLLYGAGGING | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1310 |
| `1311` | LVL_DARK_SMOKE — LVL_DARK_SMOKE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1311 |
| `1312` | Prod58 Maria 5 | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1312 |
| `1313` | LVL_SWAMP_BREATH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1313 |
| `1314` | LVL_SUNDOWN_SLAM | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1314 |
| `1315` | LVL_KAIJU_CANYON | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1315 |
| `1316` | LVL_BREAK_AND_ENTER — LVL_BREAK_AND_ENTER | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1316 |
| `1317` | LVL_BROKEN_SKULL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1317 |
| `1318` | LVL_RABBIT_HELL — LVL_RABBIT_HELL | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1318 |
| `1319` | LVL_MILE_HIGH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1319 |
| `1320` | LVL_FROZEN_RAPIDS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1320 |
| `1321` | LVL_ICY_ALTAR | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1321 |
| `1322` | LVL_SNOWCAP_SMACKDOWN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1322 |
| `1323` | LVL_FATAL_FUNGUS — LVL_FATAL_FUNGUS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1323 |
| `1324` | LVL_AZTEC_TRANCE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1324 |
| `1325` | LVL_ROWDY_ROOFING | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1325 |
| `1326` | LVL_PINBALL_PAINS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1326 |
| `1327` | LVL_SUSPENDED_GETAWAY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1327 |
| `1328` | LVL_SPELUNKER_GRAVES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1328 |
| `1329` | LVL_ACID_BATH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1329 |
| `1330` | LVL_REST_IN_PIECES — LVL_REST_IN_PIECES | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1330 |
| `1331` | LVL_DISTILLED_HOPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1331 |
| `1332` | LVL_MIDNIGHT_BREWERY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1332 |
| `1333` | LVL_FERMENTED_CAVES — LVL_FERMENTED_CAVES | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1333 |
| `1334` | LVL_DUAL_HOPS — LVL_DUAL_HOPS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1334 |
| `1335` | LVL_HANGING_GARDENS — LVL_HANGING_GARDENS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1335 |
| `1336` | LVL_MUSHROOM_BOOM — LVL_MUSHROOM_BOOM | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1336 |
| `1337` | LVL_SKYLINE_FLING | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1337 |
| `1338` | LVL_RAMPANT_RAMPS — LVL_RAMPANT_RAMPS | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1338 |
| `1339` | LVL_X_FACTOR | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1339 |
| `1340` | LVL_X_TERMINATE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1340 |
| `1341` | LVL_LOTUS_SWAMP — LVL_LOTUS_SWAMP | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1341 |
| `1342` | LVL_RADICAL_ROADWORKS — LVL_RADICAL_ROADWORKS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1342 |
| `1343` | LVL_CLIFF_HANGER — LVL_CLIFF_HANGER | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1343 |
| `1344` | LVL_DOUBLE_BARREL — LVL_DOUBLE_BARREL | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1344 |
| `1345` | LVL_SLOPPY_SLOPES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1345 |
| `1346` | LVL_TERRACE_FARMING | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1346 |
| `1347` | LVL_SPARE_RIBS — LVL_SPARE_RIBS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1347 |
| `1348` | LVL_NUCLEAR_CAVE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1348 |
| `1349` | LVL_LOPSIDED — LVL_LOPSIDED | 地图/赛道 (Track, catalog `Type` **1**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1349 |
| `1350` | LVL_AIR_ASSAULT — LVL_AIR_ASSAULT | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1350 |
| `1351` | LVL_REVERSE_ENGINEERING — LVL_REVERSE_ENGINEERING | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1351 |
| `1352` | LVL_FEROCIOUS_FLIPS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1352 |
| `1353` | LVL_FLOOR_IS_LAVA | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1353 |
| `1354` | LVL_KICK_BACK — LVL_KICK_BACK | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1354 |
| `1355` | LVL_SURPRISE_SURPRISE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1355 |
| `1356` | LVL_TWISTED_CURVES | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1356 |
| `1357` | LVL_DOWNTOWN_LOVE — LVL_DOWNTOWN_LOVE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1357 |
| `1358` | LVL_COLD_SHOULDER | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1358 |
| `1359` | LVL_TOXIC_GARDEN — LVL_TOXIC_GARDEN | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1359 |
| `1360` | LVL_TEMPLE_OF_DOOM — LVL_TEMPLE_OF_DOOM | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1360 |
| `1361` | LVL_CRESCENT_NIGHT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1361 |
| `1362` | LVL_SLIPPERY_ICE — LVL_SLIPPERY_ICE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1362 |
| `1363` | LVL_PERILOUS_PITFALLS | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1363 |
| `1364` | LVL_DARK_ICE_VALLEY — LVL_DARK_ICE_VALLEY | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1364 |
| `1365` | LVL_SNOWMAN_PEAKS — LVL_SNOWMAN_PEAKS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1365 |
| `1366` | LVL_ADAGIO_FLOW — LVL_ADAGIO_FLOW | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1366 |
| `1367` | LVL_WACKY_RIFTS — LVL_WACKY_RIFTS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_chip_store.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1367 |
| `1368` | LVL_LA_PAUSA — LVL_LA_PAUSA | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1368 |
| `1369` | LVL_INFECTED_CAVERN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1369 |
| `1370` | LVL_AIR_SNATCHER | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1370 |
| `1371` | LVL_CROOKED_GRIND — LVL_CROOKED_GRIND | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1371 |
| `1372` | LVL_NIGHT_CRAWLING — LVL_NIGHT_CRAWLING | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1372 |
| `1374` | LVL_GOLDEN_DIRT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1374 |
| `1375` | LVL_BOMBER_BLISS — LVL_BOMBER_BLISS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1375 |
| `1376` | LVL_MT_WHIPLASH — LVL_MT_WHIPLASH | 地图/赛道 (Track, catalog `Type` **1**, grantable via `dailyrewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1376 |
| `1377` | LVL_THE_SWITCHBLADE — LVL_THE_SWITCHBLADE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1377 |
| `1378` | LVL_SMURFIN_LEDGES — LVL_SMURFIN_LEDGES | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1378 |
| `1379` | LVL_CURVED_HINGES — LVL_CURVED_HINGES | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1379 |
| `1380` | LVL_BLOSSOM_GROVE — LVL_BLOSSOM_GROVE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1380 |
| `1381` | LVL_CRYSTAL_FLOW — LVL_CRYSTAL_FLOW | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1381 |
| `1382` | LVL_DOMINO_DASH | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1382 |
| `1383` | LVL_NIGHT_LIGHTS — LVL_NIGHT_LIGHTS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1383 |
| `1384` | LVL_CITY_CHAOS — LVL_CITY_CHAOS | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1384 |
| `1385` | LVL_CRYSTAL_EXTRACTION — LVL_CRYSTAL_EXTRACTION | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1385 |
| `1386` | LVL_BUMPY_MOUNTAIN — LVL_BUMPY_MOUNTAIN | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1386 |
| `1387` | LVL_HAUNTED_RAMPS — LVL_HAUNTED_RAMPS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1387 |
| `1388` | LVL_FACE_FIRST — LVL_FACE_FIRST | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1388 |
| `1389` | LVL_FLORAL_LANE — LVL_FLORAL_LANE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1389 |
| `1390` | LVL_HAPPY_FLING — LVL_HAPPY_FLING | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1390 |
| `1391` | LVL_CATACLYSM | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1391 |
| `1392` | LVL_SNOWBALL_SURPRISE — LVL_SNOWBALL_SURPRISE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1392 |
| `1393` | LVL_SNOW_ALLEY | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1393 |
| `1394` | LVL_CITY_HALLWAY — LVL_CITY_HALLWAY | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1394 |
| `1395` | LVL_WILDWOOD_ESCAPE — LVL_WILDWOOD_ESCAPE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1395 |
| `1396` | LVL_PEAK_ROUTE — LVL_PEAK_ROUTE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1396 |
| `1397` | LVL_RAY_OF_DECEPTION — LVL_RAY_OF_DECEPTION | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1397 |
| `1398` | LVL_FROSTBITE — LVL_FROSTBITE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1398 |
| `1399` | LVL_BARTER_TOWN — LVL_BARTER_TOWN | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1399 |
| `1400` | LVL_DOOM_RACE — LVL_DOOM_RACE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1400 |
| `1401` | LVL_CITY_RUN — LVL_CITY_RUN | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1401 |
| `1402` | LVL_HOMELAND_EXPRESS — LVL_HOMELAND_EXPRESS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1402 |
| `1403` | LVL_FROZEN_CLIFFS — LVL_FROZEN_CLIFFS | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1403 |
| `1404` | LVL_SWAMP_FATHOM — LVL_SWAMP_FATHOM | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1404 |
| `1405` | LVL_RUSTY_CAVE | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1405 |
| `1406` | LVL_ROCKY_CHAMBERS — LVL_ROCKY_CHAMBERS | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1406 |
| `1407` | LVL_WASTELAND — LVL_WASTELAND | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1407 |
| `1408` | LVL_URBAN_SMASH — LVL_URBAN_SMASH | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1408 |
| `1409` | LVL_DUAL_SNOWFEST — LVL_DUAL_SNOWFEST | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1409 |
| `1410` | LVL_FORTUNE_WHEEL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1410 |
| `1411` | LVL_BLAZING_HOP — LVL_BLAZING_HOP | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1411 |
| `1412` | LVL_FLORA_CROSSING — LVL_FLORA_CROSSING | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1412 |
| `1413` | LVL_HIGH_VILLE — LVL_HIGH_VILLE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1413 |
| `1414` | LVL_DESERT_PUNK — LVL_DESERT_PUNK | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1414 |
| `1415` | LVL_FROST_POINT — LVL_FROST_POINT | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1415 |
| `1416` | LVL_MINESHAFT | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1416 |
| `1417` | LVL_MEAN_STREET — LVL_MEAN_STREET | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1417 |
| `1418` | LVL_GOLDEN_RIDE — LVL_GOLDEN_RIDE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1418 |
| `1419` | LVL_DUSTZONE — LVL_DUSTZONE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1419 |
| `1420` | LVL_TOWNSCAPE — LVL_TOWNSCAPE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wts_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1420 |
| `1421` | LVL_ALPINE — LVL_ALPINE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1421 |
| `1422` | LVL_TOWNSHIP — LVL_TOWNSHIP | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1422 |
| `1423` | LVL_ABANDONED_COLONY — LVL_ABANDONED_COLONY | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1423 |
| `1424` | LVL_TIPTOP — LVL_TIPTOP | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1424 |
| `1425` | LVL_ORBICULAR_ESCAPE — LVL_ORBICULAR_ESCAPE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1425 |
| `1426` | LVL_DOLOMITE — LVL_DOLOMITE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1426 |
| `1427` | LVL_BALL_RUN | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1427 |
| `1428` | LVL_HURDLES_FROM_HELL | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1428 |
| `1429` | LVL_STREETSCAPE — LVL_STREETSCAPE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1429 |
| `1430` | LVL_APOSTATIZE — LVL_APOSTATIZE | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1430 |
| `1431` | LVL_VIADUCT — LVL_VIADUCT | 地图/赛道 (Track Piece, catalog `Type` **3**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1431 |
| `1432` | LVL_URBAN_SPRAWL — LVL_URBAN_SPRAWL | 地图/赛道 (Track, catalog `Type` **1**, grantable via `wheelspecials.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1432 |
| `1433` | LVL_SNOW_FLURRY — LVL_SNOW_FLURRY | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1433 |
| `1434` | LVL_HEAVENWARD — LVL_HEAVENWARD | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1434 |
| `1435` | LVL_WILD_ZONE — LVL_WILD_ZONE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1435 |
| `1436` | LVL_DUTSCHERS_DEN — LVL_DUTSCHERS_DEN | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1436 |
| `1437` | LVL_URBAN_COMPLEX — LVL_URBAN_COMPLEX | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1437 |
| `1438` | LVL_MARSH_RIDE — LVL_MARSH_RIDE | 地图/赛道 (Track, catalog `Type` **1**, grantable via `pvp_match_rewards.txt`) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 1438 |
| `65010` | LVL_LUMBER_YARD | 地图/赛道 (level, catalog `Type` **1**; not in a reward catalog) | `content.dat entry #18 (/conf/levels.txt) @0x012214` Levels ID 65010 |

### 6b. West-side (WST_) tracks sold for PVP chips — `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14`

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `1209` | WST_UNDERGROUND_SLOPES_TITLE (chip price 200) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1197` | WST_ABANDONED_MINE_TITLE (chip price 500) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1195` | WST_UNSTABLE_TUNNEL_TITLE (chip price 1000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1210` | WST_PROCESSING_CENTER_TITLE (chip price 1500) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1193` | WST_CAVE_CROSSING_TITLE (chip price 2500) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1199` | WST_FORBIDDEN_PATH_TITLE (chip price 5000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1194` | WST_DELIVERY_LINE_TITLE (chip price 7500) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1196` | WST_CRYSTAL_KINGDOM_TITLE (chip price 10000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1208` | WST_SMELTING_POTS_TITLE (chip price 12500) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1207` | WST_NIGHTMARE_GROTTO_TITLE (chip price 15000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1192` | WST_EXPLOSIVE_STORAGE_TITLE (chip price 17500) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1191` | WST_MINECART_DUMP_TITLE (chip price 20000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1202` | WST_WRECKED_TRACKS_TITLE (chip price 25000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1198` | WST_THE_SHAFT_TITLE (chip price 30000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1203` | WST_WASTE_DISPOSAL_TITLE (chip price 35000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1201` | WST_TRACTION_TESTGROUND_TITLE (chip price 40000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1250` | LVL_LONGSHOT_LAKE (chip price 45000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1264` | LVL_OVERDOSE (chip price 50000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1134` | LVL_ROAD_TO_RUIN (chip price 55000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1367` | LVL_WACKY_RIFTS (chip price 56000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |
| `1366` | LVL_ADAGIO_FLOW (chip price 63000) | 地图/赛道 / track | `content.dat entry #23 (/conf/pvp_chip_store.txt) @0x01cc14` PVPChipStoreTracks |

### 6c. Track IDs used by the robot-man/offline missions (`content.dat entry #25 (/conf/robotman.txt) @0x01f9f4`)

| key | TrackID | MissionNum | OfflineMissionTracks | where it came from |
|---|---|---|---|---|
| 0 | 1152 | 3 | [1032, 1090, 1051] | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[0] |
| 1 | 1148 | 3 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[1] |
| 2 | 1149 | 6 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[2] |
| 3 | 1153 | 6 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[3] |
| 4 | 1145 | 12 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[4] |
| 5 | 1151 | 15 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[5] |
| 6 | 1154 | 21 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[6] |
| 7 | 1155 | 24 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[7] |
| 8 | 1150 | 27 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[8] |
| 9 | 1157 | 30 | None | `content.dat entry #25 (/conf/robotman.txt) @0x01f9f4` Levels[9] |

---

## 7. Other grantable items (tickets, boosts, consumables)

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `135` | PVP Golden Ticket `/MENUZ/ITEM/TICKET.PNG` | ticket/currency | `content.dat entry #10 (/conf/dailyrewards.txt) @0x00d894`; `content.dat entry #49 (/conf/wts_rewards.txt) @0x02c514` Reward_4 ID 413 (x5) |
| `145` | SPECIAL PVP REWARD ITEM `/MENUZ/ITEM/QUESTIONMARK.PNG` | random/unidentified | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 100 |
| `635` | Daily Coin Magnet `/MENUZ/ITEM/BOOSTS_1.PNG` | consumable boost | `content.dat entry #49 (/conf/wts_rewards.txt) @0x02c514` Reward_4 ID 414 “Daily Coin Magnet” |
| `637` | Rarified Fuel `/MENUZ/ITEM/BOOSTS_3.PNG` | consumable boost | `content.dat entry #49 (/conf/wts_rewards.txt) @0x02c514` Reward_5 ID 514 |
| `IID 30` | Doughnut `/MENUZ/ITEM/DOUGHNUT.PNG` | consumable | `content.dat entry #15 (/conf/giftbox.txt) @0x011774` Items ID 60 |
| `IID 127 IL 0` | Coin Magnet x5 | consumable boost | `content.dat entry #15 (/conf/giftbox.txt) @0x011774` Items ID 25 |
| `IID 127 IL 2` | Rarified Fuel | consumable boost | `content.dat entry #15 (/conf/giftbox.txt) @0x011774` Items ID 26 |
| `170 …` | `IID 170 IL 1` + `IC` = track item ID | track wrapper | `content.dat entry #15 (/conf/giftbox.txt) @0x011774` Items 1–7, CompGiftItems |

### 7b. Remaining item IDs referenced by reward catalogs

Every `ItemId` used anywhere in `/conf/wts_rewards.txt`, `/conf/wheelspecials.txt`,
`/conf/pvp_match_rewards.txt`, `/conf/dailyrewards.txt`, `/conf/giftbox.txt` and `/conf/pvp_chip_store.txt`
that is not already covered by §2 (parts), §3 (paints), §4 (outfits), §5 (blueprints) or §6 (tracks).

| ID | name/key | item type | where it came from |
|---|---|---|---|
| `118` | Special Event Item - Currently Pumpkin | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `131` | Kindling Set I | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `132` | Magnifying Glass Set I | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `133` | Yeti Fur Set I | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `134` | Pumpkin Set I | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `145` | SPECIAL PVP REWARD ITEM | item/consumable (see `reward catalog`) | `pvp_match_rewards.txt` @0x01d4f4 |
| `150` | Dough-nut | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `151` | Bronco Buck Set I | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `152` | Event Point Set I | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `171` | VIP membership badge | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `179` | Check if its actually using otherwise can be reused | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `635` | Daily Coin Magnet | item/consumable (see `RewardTypes`) | `wts_rewards.txt` @0x02c514 |
| `637` | Rarified Fuel | item/consumable (see `RewardTypes`) | `wts_rewards.txt` @0x02c514 |
| `1170` | Rally Ticket Silver Medal | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |
| `1174` | Event Ticket | item/consumable (see `WheelRewards`) | `wheelspecials.txt` @0x02a354 |

---

## 8. Leaderboard rank → reward mapping

### 8a. The PVP ladder wheel — `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` → `PVPMatchRewards`

Four rank keys exist in this build, each a 5-slot weighted wheel: `{ RewardID, Amount, WheelChance }`.
`RewardID` indexes `PVPMatchRewardTypes` in the same file.

| rank key | slot | RewardID | → item | amount | chance | source |
|---|---|---|---|---|---|---|
| BRONZE0 | 0 | 1 | see PVPMatchRewardTypes ID 1 | 50 | 0.5 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[BRONZE0][0] |
| BRONZE0 | 1 | 1 | see PVPMatchRewardTypes ID 1 | 100 | 0.3 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[BRONZE0][1] |
| BRONZE0 | 2 | 5 | see PVPMatchRewardTypes ID 5 | 1 | 0.001 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[BRONZE0][2] |
| BRONZE0 | 3 | 1 | see PVPMatchRewardTypes ID 1 | 150 | 0.15 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[BRONZE0][3] |
| BRONZE0 | 4 | 2 | see PVPMatchRewardTypes ID 2 | 200 | 0.05 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[BRONZE0][4] |
| SILVER0 | 0 | 100 | see PVPMatchRewardTypes ID 100 | 1 | 0.05 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[SILVER0][0] |
| SILVER0 | 1 | 1 | see PVPMatchRewardTypes ID 1 | 100 | 0.5 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[SILVER0][1] |
| SILVER0 | 2 | 5 | see PVPMatchRewardTypes ID 5 | 1 | 0.01 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[SILVER0][2] |
| SILVER0 | 3 | 2 | see PVPMatchRewardTypes ID 2 | 250 | 0.35 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[SILVER0][3] |
| SILVER0 | 4 | 3 | see PVPMatchRewardTypes ID 3 | 500 | 0.1 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[SILVER0][4] |
| GOLD0 | 0 | 100 | see PVPMatchRewardTypes ID 100 | 1 | 0.1 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[GOLD0][0] |
| GOLD0 | 1 | 1 | see PVPMatchRewardTypes ID 1 | 500 | 0.4 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[GOLD0][1] |
| GOLD0 | 2 | 5 | see PVPMatchRewardTypes ID 5 | 1 | 0.03 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[GOLD0][2] |
| GOLD0 | 3 | 2 | see PVPMatchRewardTypes ID 2 | 750 | 0.28 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[GOLD0][3] |
| GOLD0 | 4 | 3 | see PVPMatchRewardTypes ID 3 | 1000 | 0.15 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[GOLD0][4] |
| PLATINUM0 | 0 | 100 | see PVPMatchRewardTypes ID 100 | 1 | 0.15 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[PLATINUM0][0] |
| PLATINUM0 | 1 | 1 | see PVPMatchRewardTypes ID 1 | 1000 | 0.45 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[PLATINUM0][1] |
| PLATINUM0 | 2 | 5 | see PVPMatchRewardTypes ID 5 | 1 | 0.03 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[PLATINUM0][2] |
| PLATINUM0 | 3 | 2 | see PVPMatchRewardTypes ID 2 | 1500 | 0.3 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[PLATINUM0][3] |
| PLATINUM0 | 4 | 3 | see PVPMatchRewardTypes ID 3 | 2000 | 0.1 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewards[PLATINUM0][4] |

Referenced `PVPMatchRewardTypes` rows (grant these item IDs):

| RewardID (=catalog ID) | name/key | ItemId | item type | where it came from |
|---|---|---|---|---|
| `100` | SPECIAL PVP REWARD ITEM | `145` | item/currency | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 100 |
| `1` | Tiny coin reward | `1` | item/currency | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 1 |
| `2` | Small coin reward | `1` | item/currency | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 2 |
| `3` | Medium coin reward | `1` | item/currency | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 3 |
| `5` | A gem | `2` | item/currency | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 5 |

So the ladder pays out, per rank key: coin packs (`ItemId 1`, Amount 50…2000), one gem
(`ItemId 2`, `RewardID 5`, Amount 1, chance 0.1 % bronze → 3 % gold/platinum), and the
“SPECIAL PVP REWARD ITEM” (`RewardID 100` → `ItemId 145`, Amount 1, `/MENUZ/ITEM/QUESTIONMARK.PNG`).
The bronze wheel has no `RewardID 100` slot at all — the random special item is a silver-and-up payout.

### 8b. Rank-tier special rewards — `PVPMatchSpecialRewards`

| name/key | RewardIDs (→ PVPMatchRewardTypes) | SpecialRewardLevel | where it came from |
|---|---|---|---|
| Crafting Item Tier 2 | [20003, 20008, 20013, 20018, 20023, 20028, 20033, 20038, 20043, 20048] | 0.0 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |
| Crafting Item Tier 3 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | 1.0 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |
| Soylent Bike Skin | [202] | 2.0 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |
| Donkey Blueprint | [220] | 100.0 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |
| Luchador Bikeskin | [203] | 3.9 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |
| Crafting Item Tier 4 | [20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046] | 4.0 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |
| Crafting Item lvl 5 | [20000, 20005, 20010, 20015, 20020, 20025, 20030, 20035, 20040, 20045] | 6.0 | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchSpecialRewards |

The special-reward IDs `20000`–`20054` are themselves rows in `PVPMatchRewardTypes`:

| RewardID | name/key | ItemId | item type | where it came from |
|---|---|---|---|---|
| `20004` | Crafting Item (Tier 0 Chain       ) | `5` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20004 |
| `20003` | Crafting Item (Tier 1 Chain       ) | `6` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20003 |
| `20002` | Crafting Item (Tier 2 Chain       ) | `7` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20002 |
| `20001` | Crafting Item (Tier 3 Chain       ) | `8` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20001 |
| `20000` | Crafting Item (Tier 4 Chain       ) | `9` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20000 |
| `20009` | Crafting Item (Tier 0 Spring      ) | `10` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20009 |
| `20008` | Crafting Item (Tier 1 Spring      ) | `11` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20008 |
| `20007` | Crafting Item (Tier 2 Spring      ) | `12` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20007 |
| `20006` | Crafting Item (Tier 3 Spring      ) | `13` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20006 |
| `20005` | Crafting Item (Tier 4 Spring      ) | `14` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20005 |
| `20014` | Crafting Item (Tier 0 Bolt        ) | `15` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20014 |
| `20013` | Crafting Item (Tier 1 Bolt        ) | `16` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20013 |
| `20012` | Crafting Item (Tier 2 Bolt        ) | `17` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20012 |
| `20011` | Crafting Item (Tier 3 Bolt        ) | `18` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20011 |
| `20010` | Crafting Item (Tier 4 Bolt        ) | `19` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20010 |
| `20019` | Crafting Item (Tier 0 Nut         ) | `20` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20019 |
| `20018` | Crafting Item (Tier 1 Nut         ) | `21` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20018 |
| `20017` | Crafting Item (Tier 2 Nut         ) | `22` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20017 |
| `20016` | Crafting Item (Tier 3 Nut         ) | `23` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20016 |
| `20015` | Crafting Item (Tier 4 Nut         ) | `24` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20015 |
| `20024` | Crafting Item (Tier 0 Metal Sheet ) | `25` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20024 |
| `20023` | Crafting Item (Tier 1 Metal Sheet ) | `26` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20023 |
| `20022` | Crafting Item (Tier 2 Metal Sheet ) | `27` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20022 |
| `20021` | Crafting Item (Tier 3 Metal Sheet ) | `28` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20021 |
| `20020` | Crafting Item (Tier 4 Metal Sheet ) | `29` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20020 |
| `20029` | Crafting Item (Tier 0 Spark Plug  ) | `30` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20029 |
| `20028` | Crafting Item (Tier 1 Spark Plug  ) | `31` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20028 |
| `20027` | Crafting Item (Tier 2 Spark Plug  ) | `32` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20027 |
| `20026` | Crafting Item (Tier 3 Spark Plug  ) | `33` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20026 |
| `20025` | Crafting Item (Tier 4 Spark Plug  ) | `34` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20025 |
| `20034` | Crafting Item (Tier 0 Pipe        ) | `35` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20034 |
| `20033` | Crafting Item (Tier 1 Pipe        ) | `36` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20033 |
| `20032` | Crafting Item (Tier 2 Pipe        ) | `37` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20032 |
| `20031` | Crafting Item (Tier 3 Pipe        ) | `38` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20031 |
| `20030` | Crafting Item (Tier 4 Pipe        ) | `39` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20030 |
| `20039` | Crafting Item (Tier 0 Ball Bearing) | `40` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20039 |
| `20038` | Crafting Item (Tier 1 Ball Bearing) | `41` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20038 |
| `20037` | Crafting Item (Tier 2 Ball Bearing) | `42` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20037 |
| `20036` | Crafting Item (Tier 3 Ball Bearing) | `43` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20036 |
| `20035` | Crafting Item (Tier 4 Ball Bearing) | `44` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20035 |
| `20044` | Crafting Item (Tier 0 Piston      ) | `45` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20044 |
| `20043` | Crafting Item (Tier 1 Piston      ) | `46` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20043 |
| `20042` | Crafting Item (Tier 2 Piston      ) | `47` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20042 |
| `20041` | Crafting Item (Tier 3 Piston      ) | `48` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20041 |
| `20040` | Crafting Item (Tier 4 Piston      ) | `49` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20040 |
| `20049` | Crafting Item (Tier 0 Gear        ) | `50` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20049 |
| `20048` | Crafting Item (Tier 1 Gear        ) | `51` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20048 |
| `20047` | Crafting Item (Tier 2 Gear        ) | `52` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20047 |
| `20046` | Crafting Item (Tier 3 Gear        ) | `53` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20046 |
| `20045` | Crafting Item (Tier 4 Gear        ) | `54` | 零件 / crafting part | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` PVPMatchRewardTypes ID 20045 |

### 8c. League medal XP multipliers — `content.dat entry #50 (/conf/xp.txt) @0x02dc74` → `XpConf`

| key | value | meaning | where it came from |
|---|---|---|---|
| `M_PLAT` | 20.0 | platinum medal XP multiplier | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` XpConf |
| `M_GOLD` | 8.0 | gold medal XP multiplier | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` XpConf |
| `M_SILV` | 3.0 | silver medal XP multiplier | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` XpConf |
| `M_BRON` | 0.5 | bronze medal XP multiplier | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` XpConf |

### 8d. Missing-reward fallback — `MissingRewardFallbackRewards`

25 keys `"1"`…`"25"`, each a 10-element list of `PVPMatchRewardTypes` IDs — used when the ladder
has no reward for a slot.

| key | RewardIDs (→ PVPMatchRewardTypes) | where it came from |
|---|---|---|
| 1 | [20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[1] |
| 2 | [20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[2] |
| 3 | [20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[3] |
| 4 | [20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[4] |
| 5 | [20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[5] |
| 6 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[6] |
| 7 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[7] |
| 8 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[8] |
| 9 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[9] |
| 10 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[10] |
| 11 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[11] |
| 12 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[12] |
| 13 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[13] |
| 14 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[14] |
| 15 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[15] |
| 16 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[16] |
| 17 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[17] |
| 18 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[18] |
| 19 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[19] |
| 20 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[20] |
| 21 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[21] |
| 22 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[22] |
| 23 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[23] |
| 24 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[24] |
| 25 | [20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047] | `content.dat entry #24 (/conf/pvp_match_rewards.txt) @0x01d4f4` MissingRewardFallbackRewards[25] |

### 8e. XP-level reward ladder — `content.dat entry #50 (/conf/xp.txt) @0x02dc74` → `Xp`

| level | XP required | ROBO_XP | reward items (`IID/IL/IC`) | where it came from |
|---|---|---|---|---|
| 0 | 0 | 5 |  | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[0] |
| 1 | 20 | 5 | 0/1/20 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[1] |
| 2 | 60 | 5 | 0/1/30 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[2] |
| 3 | 235 | 5 | 0/1/50 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[3] |
| 4 | 700 | 5 | 0/1/300 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[4] |
| 5 | 1275 | 5 | 0/1/1000 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[5] |
| 6 | 2200 | 5 | 0/1/2000 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[6] |
| 7 | 3400 | 20 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[7] |
| 8 | 5500 | 21 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[8] |
| 9 | 7500 | 22 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[9] |
| 10 | 10000 | 23 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[10] |
| 11 | 13000 | 24 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[11] |
| 12 | 17000 | 25 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[12] |
| 13 | 23000 | 26 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[13] |
| 14 | 30000 | 27 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[14] |
| 15 | 38000 | 28 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[15] |
| 16 | 47000 | 29 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[16] |
| 17 | 57000 | 30 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[17] |
| 18 | 68000 | 31 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[18] |
| 19 | 80000 | 32 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[19] |
| 20 | 93000 | 33 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[20] |
| 21 | 107000 | 34 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[21] |
| 22 | 121000 | 35 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[22] |
| 23 | 136000 | 36 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[23] |
| 24 | 152000 | 37 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[24] |
| 25 | 169000 | 38 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[25] |
| 26 | 190000 | 39 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[26] |
| 27 | 210000 | 40 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[27] |
| 28 | 230000 | 41 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[28] |
| 29 | 260000 | 42 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[29] |
| 30 | 295000 | 43 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[30] |
| 31 | 340000 | 44 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[31] |
| 32 | 400000 | 45 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[32] |
| 33 | 480000 | 46 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[33] |
| 34 | 585000 | 47 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[34] |
| 35 | 720000 | 48 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[35] |
| 36 | 890000 | 49 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[36] |
| 37 | 1100000 | 50 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[37] |
| 38 | 1355000 | 51 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[38] |
| 39 | 1660000 | 52 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[39] |
| 40 | 2020000 | 60 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[40] |
| 41 | 2440000 | 65 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[41] |
| 42 | 2920000 | 75 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[42] |
| 43 | 3480000 | 80 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[43] |
| 44 | 4110000 | 85 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[44] |
| 45 | 4820000 | 90 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[45] |
| 46 | 5615000 | 95 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[46] |
| 47 | 6500000 | 100 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[47] |
| 48 | 7480000 | 125 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[48] |
| 49 | 8560000 | 130 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[49] |
| 50 | 9745000 | 135 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[50] |
| 51 | 11040000 | 140 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[51] |
| 52 | 12450000 | 145 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[52] |
| 53 | 13980000 | 150 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[53] |
| 54 | 15635000 | 155 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[54] |
| 55 | 17420000 | 160 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[55] |
| 56 | 19340000 | 165 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[56] |
| 57 | 21400000 | 170 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[57] |
| 58 | 23600000 | 175 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[58] |
| 59 | 25960000 | 180 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[59] |
| 60 | 28470000 | 185 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[60] |
| 61 | 31140000 | 190 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[61] |
| 62 | 33970000 | 195 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[62] |
| 63 | 36980000 | 200 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[63] |
| 64 | 40160000 | 205 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[64] |
| 65 | 43520000 | 210 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[65] |
| 66 | 47060000 | 215 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[66] |
| 67 | 50800000 | 220 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[67] |
| 68 | 54730000 | 225 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[68] |
| 69 | 58860000 | 230 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[69] |
| 70 | 63190000 | 235 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[70] |
| 71 | 67740000 | 240 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[71] |
| 72 | 72500000 | 245 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[72] |
| 73 | 77480000 | 250 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[73] |
| 74 | 82680000 | 25500 | 0/2/5 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[74] |
| 75 | 2147483647 | 260 | 0/2/5 0/3/1 | `content.dat entry #50 (/conf/xp.txt) @0x02dc74` Xp[75] |

---

## 9. Provenance — decoded container entries used above

| entry # | internal path | uncompressed | blob offset in content.dat |
|---|---|---|---|
| 2 | `/conf/bikes.txt` | 34113 | 0x009774 |
| 3 | `/conf/consumables.txt` | 1024 | 0x00a6f4 |
| 5 | `(unknown, Crafting)` | 703 | 0x00aa74 |
| 6 | `/conf/currency.txt` | 2254 | 0x00ab14 |
| 7 | `/conf/customization.txt` | 106148 | 0x00af74 |
| 10 | `/conf/dailyrewards.txt` | 49433 | 0x00d894 |
| 15 | `/conf/giftbox.txt` | 23414 | 0x011774 |
| 16 | `/conf/itemdb.txt` | 1632 | 0x011f54 |
| 18 | `/conf/levels.txt` | 131643 | 0x012214 |
| 19 | `/conf/level_rewards.txt` | 18334 | 0x015d94 |
| 23 | `/conf/pvp_chip_store.txt` | 26800 | 0x01cc14 |
| 24 | `/conf/pvp_match_rewards.txt` | 125010 | 0x01d4f4 |
| 25 | `/conf/robotman.txt` | 6138 | 0x01f9f4 |
| 26 | `/conf/settings.json` | 63515 | 0x01fcd4 |
| 28 | `/conf/slotmachine.txt` | 124491 | 0x0229f4 |
| 30 | `/conf/store.txt` | 4670 | 0x023ff4 |
| 40 | `/conf/store_daily.txt` | 20142 | 0x025634 |
| 42 | `/conf/store_offers.txt` | 20931 | 0x025c14 |
| 43 | `/conf/textureatlas.txt` | 4838 | 0x0264f4 |
| 45 | `/conf/upgrades.txt` | 173717 | 0x027bf4 |
| 47 | `/conf/wheeleventspecial.txt` | 7418 | 0x029ff4 |
| 48 | `/conf/wheelspecials.txt` | 107237 | 0x02a354 |
| 49 | `/conf/wts_rewards.txt` | 99258 | 0x02c514 |
| 50 | `/conf/xp.txt` | 10002 | 0x02dc74 |

Related files not in the table above: `tmp\packout\itemids_report.txt` (full raw dump),
`tmp\packout\all\` (2494 decompressed entries), `tmp\packout\all_index.txt`, `tmp\pack_keys.py`.

---

### Items explicitly NOT resolved

- **Bike blueprint IDs for atlas slots nn = 3–8 and 11** — no reward catalog in this build grants
  them, so `384 / 389 / 394 / 399 / 404 / 409 / 424` are *inferred* from `369 + 5*nn` only.
- **Bike blueprints 1–18 for the lowest-tier bikes (Armadillo, Jackal, Mantis, …)** — not present as
  explicit ItemIds anywhere in the reward tables.
- **`ItemId 145` “SPECIAL PVP REWARD ITEM”** — the concrete item it resolves to at runtime is unknown.
- **Outfit part IDs that never appear in a reward catalog** have no entry here; §4a lists every
  outfit-part ID that *is* referenced by a reward table, which is the set a server can safely grant.
  → **已被 §9 取代**：这类 id 现在可以从 `/conf/customization.txt` 推导（`ItemType*5+tier`），
  而且其中 165/240 个在真机存档 `items2` 里出现过 —— 「没在任何奖励表里出现」不等于不能下发。
- **Entry #5 (the Crafting table, 703 B)** has no recovered internal path — its hash matched none of
  the 296 candidate path strings in `libTrialsGo.strings.txt`.
---

## 9. 服装套装表（`/conf/customization.txt`）与部件 id 公式

解包条目 `0007_27884168.bin`（106148 B）= `/conf/customization.txt`，顶层 `{"Rider": [80 条]}`。
**脚本按内容嗅探（同时含 `"Rider"` 与 `"NameStringId"`），不认文件名哈希**（`tools/build_item_catalog.py`
的 `find_customization()`）。

每套的字段（并集）：`ID`、`Comment`、`StringOverride`、`HelmetOnIcon/OffIcon`、`Upper*`、`Lower*`、
`Menu*Texture/Offset`、`NameStringId`、`DescriptionStringId`、**`BonusPowerDescriptionStringId`**、
`BonusPower`、`Order`、`R`、`ItemType`、`UnlockType`、`CanBeBought0/1/2`、`MissionUnlock`、
`UnlockMissionIds`、`LeaderboardHilight`、`SpecialFX`、`TR_SFX_VOICE_*`、`VOPitchMultiplier`。

### 部件 id 公式

```
部件 id = ItemType * 5 + tier        tier: 0 = 头盔 / 1 = 上衣(Middle) / 2 = 裤装(Bottom)
LOCF 键 = ITEM_<ItemType>_<tier>     （绝大多数没有文本，显示的是套装名）
```

* **Rider ID 0–19 那批记录里没有 `ItemType`**，用 `type = 40 + Rider ID`
  （Dogfighter ID1→41→205/206/207 … Pumpkin King ID19→59→295/296/297）。
  验证：`ITEM_57_0/1/2` = "The Eggman Helmet/Middle/Bottom Piece" ↔ Eggman ID17→57→285/286/287。
* **`Rider ID` 与 `OUTFIT_nn` 序号不是一回事**：只能走 `NameStringId` 映射
  （ID0→OUTFIT_00、ID1→06、ID2→05、ID18→21、ID19→19、ID20→18、ID33/36→OUTFIT_34、ID34/37→OUTFIT_35）。
* 80 套 × 3 = **240 个 id 互不冲突**；其中 **99 个不在任何奖励/商店配置里**（隐藏与未上架套装），
  **165/240 在真机存档 `items2` 里出现过**（4 个存档分别是 210 / 3 / 576 / 293 个键）。
* **与「赛道解锁」条目有 19 个编号撞车**（1130/1135/1146/1187/1191/1192/1195/1196/1197/1201/1202/
  1207/1210/1215/1216/1222/1231/1287/1296）—— 例如 1130 既是 Wurst Racer 头盔又是 "Garbage Route"。
  `ItemId` 只在同一个 `Type` 内唯一，而 `items2` 只有 id 一维；赛道实际是靠 `chips.<pid>.tracks`
  解锁的（不走 items2），所以**按服装归类**，旧名字记进 `alias` / `source.overlap_ids`。
  同类撞车另一例：id 635 = 消耗品 "Super Magnet"（金币加倍器）= type 127 的 tier 0。

### 套装效果（`BonusPower`，24 套有）

格式 `"<EFFECT> <args>"`，文案在 `BonusPowerDescriptionStringId = OUTFIT_%02d_POWER`，
所有文案都写 "Outfit does not need to be equipped" ⇒ **集齐即账号级生效，不用穿着**。

| 套装 | 效果 |
|---|---|
| ID39 **The High Roller**（隐藏，`MULTIPLY_FUEL_REFILL_TIME 0.006`）| 无限汽油 |
| ID6 Samsarian | `INCREASE_MISSION_REWARD_XP 1.2` |
| ID10 Rebel | `INCREASE_LEVEL_REWARD_XP 1.1` |
| ID11 Priest | `WHEEL_GEM_REWARD_BONUS 1` |
| ID12 Enforcer | `INCREASE_LOOT_WHEEL_IMPACT 1.15` |
| ID13 Goon | `CHECKPOINT_COIN_MULTIPLY 1.5` |
| ID14 Cyberpunk | `MULTIPLY_SLOTMACHINE_COOLDOWN_TIME 0.8` |
| ID15 Platinum Knight | `MULTIPLY_FUEL_REFILL_TIME 0.666666` |
| ID16 Cyborg | `MULTIPLY_UPGRADE_WAIT_TIME 0.9` |
| ID21 Manbird | `CHECKPOINT_COIN_MULTIPLY 2.0` |
| ID22 Cornelius | `MULTIPLY_PVP_CHIPSTORE_PRICES 0.9` |
| ID29 Cowgirl | `MULTIPLY_LOOT_WHEEL_REWARD 151 2.0` |
| ID30 Native Warrior | `PVP_EXTRA_MATCH_SLOT 1` |
| ID33/36 Henchman | `MULTIPLY_LOOT_WHEEL_CHANCE 419 2.0` |
| ID34/37 Super Spy | `MULTIPLY_UPGRADE_WAIT_TIME 0.5` |
| ID43 Christmas Gal | `REDUCE_GIFT_OPENING_PRICE 0.5` |
| ID44 Sugar Daddy | `UPGRADE_WAIT_TIME_TO 1.0` |
| ID51 Dealbreaker（内部代号 HALLOWEEN_MAN）| `MULTIPLY_FREE_CHALLENGE_RETRY 2.0` |
| ID59 Reputed Hunter | `MULTIPLY_STARTING_REPUTATION 1.5` |
| ID76 Space Suit（内部代号 MOONRIDER）| `SPECIAL_ABILITY_TIME_MULTIPLIER 11 0.5 cooldown` |
| ID78 Dr. Cuul | `REMOVE_HUNT_DECOY_TRACKS 2` |
| ID79 Madcap Elf | `MULTIPLY_RALLY_TICKETS 2` |

### 上架状态

`UnlockType` 是 3 元数组：`[4,4,4]` = 不可购买 = **隐藏套装（46 套）**，`[0,0,0]` / `[2,2,2]` /
`[3,3,3]` = 可买 / 任务解锁（价格看 `CanBeBought0/1/2`，隐藏的为 `None`）；
`MissionUnlock: 10000` 是「永不」哨兵值。`Comment`（内部代号）与官方名常常不一样：
ID46 `MUMMY_BOY`→"The Desert King"、ID48 `THE_KING`→"King of the Wastes"、
ID51 `HALLOWEEN_MAN`→"The Dealbreaker"、ID76 `MOONRIDER`→"Space Suit"、ID78 `Dr Cool`→"Dr. Cuul"。
**ID33/36 与 ID34/37 各共用一个 `OUTFIT_nn` 名**（Henchman Uniform / Super Spy 的黑白两套），
所以钥匙必须带 type（`OUTFIT_34_NAME#116`）。

### 复现

```bash
python tools/build_item_catalog.py            # 产出 server/admin/items.json（500 条物品 + 80 套服装）
```
