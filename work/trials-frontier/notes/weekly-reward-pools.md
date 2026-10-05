# 午夜杯奖励池（`wts_rewards.txt`）对照表 —— 供 WebUI 控制用

本文由 `python tools/wts_reward_doc.py` 生成（数据源：客户端内容包里的 `/conf/wts_rewards.txt`，本机抽取副本 `tmp/packout/wts_rewards.txt`）。机器可读版本：`server/data/wts_rewards.json`。

## 1. 这张表是什么 / 不是什么

- **是**客户端本地表：`WeeklyChallengeManager::loadConfig` @`0x006307ac` 用 `datapack::DataFilePack::searchFile('/conf/wts_rewards.txt')` 读进来，再 `WeeklyChallengeManager::parseJson` 解析。
- **不是**服务端能改的东西：服务端只能决定「第几档奖杯用哪个 `Reward_N` 池子」（`weekly.reward_ids` / `reward_slots`）。池子里的**内容**在客户端。
- 池子里**没有**喷漆/蓝图/皮肤（15 个池子全扫过，`paint`/`blueprint`/`skin`/`livery`/`decal` 零命中）。原版那些是从商店/报价/探险等别的系统出的。

## 2. 档位 → 百分位（客户端 `getPlayerTrophyType` @`0x006353c8`）

| 奖杯档 | 触发条件（服务端 `getPlayerRankPercent` @`0x00634548` 算出的百分位）| 默认池（第 i 档 → `Reward_{方案*5+i+1}`，方案 0/1/2）|
|---|---|---|
| `platinum` | platinum（≤1%） | `Reward_1` / `Reward_6` / `Reward_11` |
| `gold` | gold（≤10%） | `Reward_2` / `Reward_7` / `Reward_12` |
| `silver` | silver（≤25%） | `Reward_3` / `Reward_8` / `Reward_13` |
| `bronze` | bronze（其余，较好那半） | `Reward_4` / `Reward_9` / `Reward_14` |
| `wood` | wood（其余，最差档） | `Reward_5` / `Reward_10` / `Reward_15` |

## 3. 15 个池子的内容（完整）

### `Reward_1`（23 件，档位 `platinum`，方案 0）

| 名字 | item id | 数量 |
|---|---|---|
| Track Reward - Urban Smash | 1408 | 1 |
| Track Reward - City Hallway | 1394 | 1 |
| Track Reward - Bomber Bliss | 1375 | 1 |
| Track Reward - Crystal Flow | 1381 | 1 |
| Track Reward - Crystal Extraction | 1385 | 1 |
| Track Reward - Haunted Ramps | 1387 | 1 |
| Track Reward - Fatal Fungus | 1323 | 1 |
| Track Reward – Endless Wealth | 1247 | 1 |
| Track Reward - Impact Attics | 1260 | 1 |
| Track Reward - Leaping Hallows | 1290 | 1 |
| Track Reward - Faceplant Precinct | 1297 | 1 |
| Track Reward - High Tide Heights | 1289 | 1 |
| Track Reward - Derailed | 1298 | 1 |
| Track Reward - Itchy Jaws | 1159 | 1 |
| Track Reward - Exile Pass | 1161 | 1 |
| Track Piece Reward - La Pausa | 1368 | 1 |
| Track Piece Reward - Crooked Grind | 1371 | 1 |
| Track Piece Reward - Kick back | 1354 | 1 |
| Track Piece Reward - Break and Enter | 1316 | 1 |
| Track Piece Reward - Downtown Love | 1357 | 1 |
| Track Piece Reward - City Chaos | 1384 | 1 |
| Track piece Reward -  Face First | 1388 | 1 |
| Track Reward - Night Lights | 1383 | 1 |

### `Reward_2`（30 件，档位 `gold`，方案 0）

| 名字 | item id | 数量 |
|---|---|---|
| The Gunslinger | 735, 736, 737 | 1 |
| The Undead Rider | 775, 776, 777 | 1 |
| The Sheriff | 575, 576, 577 | 1 |
| Ninja | 820, 821, 822 | 1 |
| The Convict | 570, 571, 572 | 1 |
| Henchman Uniform Orange | 725, 726, 727 | 1 |
| The Cowgirl | 560, 561, 562 | 1 |
| The Yeti | 550, 551, 552 | 1 |
| Mr. Bones | 24 | 1 |
| Aloha | 18 | 1 |
| Stitch | 27 | 1 |
| Wasp | 13 | 1 |
| Nutcracker | 54 | 1 |
| Spirits | 29 | 1 |

### `Reward_3`（8 件，档位 `silver`，方案 0）

| 名字 | item id | 数量 |
|---|---|---|
| Boogeyman | 30 | 1 |
| Hippie | 50 | 1 |
| Venom | 23 | 1 |
| Noble | 33 | 1 |
| HD Electric x2 | 454 | 2 |
| Agent x2 | 419 | 2 |
| Donkey x2 | 459 | 2 |
| HD XG750R x2 | 449 | 2 |

### `Reward_4`（14 件，档位 `bronze`，方案 0）

| 名字 | item id | 数量 |
|---|---|---|
| Big Gem pack | 2 | 20 |
| Crafting Item (Tier 4 Chain) | 9 | 3 |
| Crafting Item (Tier 4 Spring) | 14 | 3 |
| Crafting Item (Tier 4 Bolt) | 19 | 3 |
| Crafting Item (Tier 4 Nut) | 24 | 3 |
| Crafting Item (Tier 4 Metal Sheet) | 29 | 3 |
| Crafting Item (Tier 4 Spark Plug) | 34 | 3 |
| Crafting Item (Tier 4 Pipe) | 39 | 3 |
| Crafting Item (Tier 4 Ball Bearing) | 44 | 3 |
| Crafting Item (Tier 4 Piston) | 49 | 3 |
| Crafting Item (Tier 4 Gear) | 54 | 3 |
| Big coin pack | 1 | 25000 |
| Golden ticket stack | 135 | 5 |
| Daily Coin Magnet | 635 | 1 |

### `Reward_5`（14 件，档位 `wood`，方案 0）

| 名字 | item id | 数量 |
|---|---|---|
| Small Gem Pack | 2 | 5 |
| Crafting Item (Tier 3 Chain) | 8 | 3 |
| Crafting Item (Tier 3 Spring) | 13 | 3 |
| Crafting Item (Tier 3 Bolt) | 18 | 3 |
| Crafting Item (Tier 3 Nut) | 23 | 3 |
| Crafting Item (Tier 3 Metal Sheet) | 28 | 3 |
| Crafting Item (Tier 3 Spark Plug) | 33 | 3 |
| Crafting Item (Tier 3 Pipe) | 38 | 3 |
| Crafting Item (Tier 3 Ball Bearing) | 43 | 3 |
| Crafting Item (Tier 3 Piston) | 48 | 3 |
| Crafting Item (Tier 3 Gear) | 53 | 3 |
| Small coin pack | 1 | 10000 |
| Golden ticket pack | 135 | 3 |
| Rarified Fuel | 637 | 1 |

### `Reward_6`（23 件，档位 `platinum`，方案 1）

| 名字 | item id | 数量 |
|---|---|---|
| Track Reward - Swamp Fathom | 1404 | 1 |
| Track Reward - Wasteland | 1407 | 1 |
| Track Reward - Toxic Garden | 1359 | 1 |
| Track Reward - Rocky Chambers | 1406 | 1 |
| Track Reward - Flora Crossing | 1412 | 1 |
| Track Reward - Haunted Ramps | 1387 | 1 |
| Track Reward - Fatal Fungus | 1323 | 1 |
| Track Reward – Endless Wealth | 1247 | 1 |
| Track Reward - Impact Attics | 1260 | 1 |
| Track Reward - Leaping Hallows | 1290 | 1 |
| Track Reward - Faceplant Precinct | 1297 | 1 |
| Track Reward - High Tide Heights | 1289 | 1 |
| Track Reward - Derailed | 1298 | 1 |
| Track Reward - Itchy Jaws | 1159 | 1 |
| Track Reward - Exile Pass | 1161 | 1 |
| Track Piece Reward - La Pausa | 1368 | 1 |
| Track Piece Reward - Crooked Grind | 1371 | 1 |
| Track Piece Reward - Kick back | 1354 | 1 |
| Track Piece Reward - Break and Enter | 1316 | 1 |
| Track Piece Reward - Downtown Love | 1357 | 1 |
| Track Piece Reward - City Chaos | 1384 | 1 |
| Track piece Reward -  Face First | 1388 | 1 |
| Track Reward -  Crystal Extraction | 1385 | 1 |

### `Reward_7`（30 件，档位 `gold`，方案 1）

| 名字 | item id | 数量 |
|---|---|---|
| Heartbreak Kit | 845, 846, 847 | 1 |
| Holiday Scarf | 795, 796, 797 | 1 |
| The Sheriff | 575, 576, 577 | 1 |
| Ninja | 820, 821, 822 | 1 |
| The Convict | 570, 571, 572 | 1 |
| Henchman Uniform Orange | 725, 726, 727 | 1 |
| The Cowgirl | 560, 561, 562 | 1 |
| The Yeti | 550, 551, 552 | 1 |
| Mr. Bones | 24 | 1 |
| Aloha | 18 | 1 |
| Stitch | 27 | 1 |
| Wasp | 13 | 1 |
| Nutcracker | 54 | 1 |
| Spirits | 29 | 1 |

### `Reward_8`（12 件，档位 `silver`，方案 1）

| 名字 | item id | 数量 |
|---|---|---|
| Boogeyman | 30, 30 | 1 |
| Hippie | 50 | 1 |
| Venom | 23 | 1 |
| Noble | 33 | 1 |
| Rodeo1 | 38 | 1 |
| Ceremonial Feathers | 49 | 1 |
| HD Electric x2 | 454 | 2 |
| BMW F800 GS x2 | 444 | 2 |
| Donkey x2 | 459 | 2 |
| HD XG750R x2 | 449 | 2 |
| KTM 450 x2 | 434 | 2 |

### `Reward_9`（14 件，档位 `bronze`，方案 1）

| 名字 | item id | 数量 |
|---|---|---|
| Big Gem pack | 2 | 20 |
| Crafting Item (Tier 4 Chain) | 9 | 3 |
| Crafting Item (Tier 4 Spring) | 14 | 3 |
| Crafting Item (Tier 4 Bolt) | 19 | 3 |
| Crafting Item (Tier 4 Nut) | 24 | 3 |
| Crafting Item (Tier 4 Metal Sheet) | 29 | 3 |
| Crafting Item (Tier 4 Spark Plug) | 34 | 3 |
| Crafting Item (Tier 4 Pipe) | 39 | 3 |
| Crafting Item (Tier 4 Ball Bearing) | 44 | 3 |
| Crafting Item (Tier 4 Piston) | 49 | 3 |
| Crafting Item (Tier 4 Gear) | 54 | 3 |
| Big coin pack | 1 | 25000 |
| Golden ticket stack | 135 | 5 |
| Daily Coin Magnet | 635 | 1 |

### `Reward_10`（14 件，档位 `wood`，方案 1）

| 名字 | item id | 数量 |
|---|---|---|
| Small Gem Pack | 2 | 5 |
| Crafting Item (Tier 3 Chain) | 8 | 3 |
| Crafting Item (Tier 3 Spring) | 13 | 3 |
| Crafting Item (Tier 3 Bolt) | 18 | 3 |
| Crafting Item (Tier 3 Nut) | 23 | 3 |
| Crafting Item (Tier 3 Metal Sheet) | 28 | 3 |
| Crafting Item (Tier 3 Spark Plug) | 33 | 3 |
| Crafting Item (Tier 3 Pipe) | 38 | 3 |
| Crafting Item (Tier 3 Ball Bearing) | 43 | 3 |
| Crafting Item (Tier 3 Piston) | 48 | 3 |
| Crafting Item (Tier 3 Gear) | 53 | 3 |
| Small coin pack | 1 | 10000 |
| Golden ticket pack | 135 | 3 |
| Rarified Fuel | 637 | 1 |

### `Reward_11`（22 件，档位 `platinum`，方案 2）

| 名字 | item id | 数量 |
|---|---|---|
| Track Reward - City Chaos | 1384 | 1 |
| Track Reward - Frostbite | 1398 | 1 |
| Track Reward - Bumpy Mountain | 1386 | 1 |
| Track Reward - Townscape | 1420 | 1 |
| Track Reward - Crystal Extraction | 1385 | 1 |
| Track Reward - Haunted Ramps | 1387 | 1 |
| Track Reward - Fatal Fungus | 1323 | 1 |
| Track Reward – Endless Wealth | 1247 | 1 |
| Track Reward - Impact Attics | 1260 | 1 |
| Track Reward - Leaping Hallows | 1290 | 1 |
| Track Reward - Faceplant Precinct | 1297 | 1 |
| Track Reward - High Tide Heights | 1289 | 1 |
| Track Reward - Derailed | 1298 | 1 |
| Track Reward - Itchy Jaws | 1159 | 1 |
| Track Reward - Exile Pass | 1161 | 1 |
| Track Piece Reward - La Pausa | 1368 | 1 |
| Track Piece Reward - Crooked Grind | 1371 | 1 |
| Track Piece Reward - Kick back | 1354 | 1 |
| Track Piece Reward - Break and Enter | 1316 | 1 |
| Track Piece Reward - Downtown Love | 1357 | 1 |
| Track piece Reward -  Face First | 1388 | 1 |
| Track Reward -  Ray of Deception | 1397 | 1 |

### `Reward_12`（31 件，档位 `gold`，方案 2）

| 名字 | item id | 数量 |
|---|---|---|
| Halloween Lady | 830, 831, 832 | 1 |
| Holiday Scarf | 795, 796, 797 | 1 |
| The Sheriff | 575, 576, 577 | 1 |
| Ninja | 820, 821, 822 | 1 |
| Christmas Gal | 785, 786, 787 | 1 |
| Henchman Uniform Orange | 725, 726, 727 | 1 |
| The Cowgirl | 560, 561, 562 | 1 |
| The Yeti | 550, 551, 552 | 1 |
| Mr. Bones | 24 | 1 |
| Aloha | 18 | 1 |
| Stitch | 27 | 1 |
| Wasp | 13 | 1 |
| Nutcracker | 54 | 1 |
| Spirits | 29 | 1 |
| Batbike | 53 | 1 |

### `Reward_13`（11 件，档位 `silver`，方案 2）

| 名字 | item id | 数量 |
|---|---|---|
| Boogeyman | 30 | 1 |
| Hippie | 50 | 1 |
| Venom | 23 | 1 |
| Noble | 33 | 1 |
| Rodeo1 | 38 | 1 |
| Ceremonial Feathers | 49 | 1 |
| HD Electric x2 | 454 | 2 |
| Agent x2 | 419 | 2 |
| Stallion x2 | 414 | 2 |
| HD XG750R x2 | 449 | 2 |
| KTM 500 x2 | 429 | 2 |

### `Reward_14`（14 件，档位 `bronze`，方案 2）

| 名字 | item id | 数量 |
|---|---|---|
| Big Gem pack | 2 | 20 |
| Crafting Item (Tier 4 Chain) | 9 | 3 |
| Crafting Item (Tier 4 Spring) | 14 | 3 |
| Crafting Item (Tier 4 Bolt) | 19 | 3 |
| Crafting Item (Tier 4 Nut) | 24 | 3 |
| Crafting Item (Tier 4 Metal Sheet) | 29 | 3 |
| Crafting Item (Tier 4 Spark Plug) | 34 | 3 |
| Crafting Item (Tier 4 Pipe) | 39 | 3 |
| Crafting Item (Tier 4 Ball Bearing) | 44 | 3 |
| Crafting Item (Tier 4 Piston) | 49 | 3 |
| Crafting Item (Tier 4 Gear) | 54 | 3 |
| Big coin pack | 1 | 25000 |
| Golden ticket stack | 135 | 5 |
| Daily Coin Magnet | 635 | 1 |

### `Reward_15`（14 件，档位 `wood`，方案 2）

| 名字 | item id | 数量 |
|---|---|---|
| Small Gem Pack | 2 | 5 |
| Crafting Item (Tier 3 Chain) | 8 | 3 |
| Crafting Item (Tier 3 Spring) | 13 | 3 |
| Crafting Item (Tier 3 Bolt) | 18 | 3 |
| Crafting Item (Tier 3 Nut) | 23 | 3 |
| Crafting Item (Tier 3 Metal Sheet) | 28 | 3 |
| Crafting Item (Tier 3 Spark Plug) | 33 | 3 |
| Crafting Item (Tier 3 Pipe) | 38 | 3 |
| Crafting Item (Tier 3 Ball Bearing) | 43 | 3 |
| Crafting Item (Tier 3 Piston) | 48 | 3 |
| Crafting Item (Tier 3 Gear) | 53 | 3 |
| Small coin pack | 1 | 10000 |
| Golden ticket pack | 135 | 3 |
| Rarified Fuel | 637 | 1 |

## 4. 三套方案（方案 0/1/2）之间到底差什么

客户端要的是 `reward_config/<上周周号>`，原版服务器按那一周回**对应的一套**（也就是内容随周/赛季轮换：基础套 / 圣诞·情人节套 / 万圣节·圣诞套）。所以 `Reward_1` 与 `Reward_6`、`Reward_11` 的区别就是**限时/节日物品 + 几条赛道·几台车**，其余条目三套共享。

### `platinum`：三套有差别

| 池 | **真·独有**（另两套都没有） | 只和另一套共享 |
|---|---|---|
| `Reward_1` | Track Reward - Bomber Bliss(1375)、Track Reward - Crystal Flow(1381)、Track Reward - Night Lights(1383)、Track Reward - City Hallway(1394)、Track Reward - Urban Smash(1408) | Track Piece Reward - City Chaos(1384)、Track Reward - Crystal Extraction(1385) |
| `Reward_6` | Track Reward - Toxic Garden(1359)、Track Reward -  Crystal Extraction(1385)、Track Reward - Swamp Fathom(1404)、Track Reward - Rocky Chambers(1406)、Track Reward - Wasteland(1407)、Track Reward - Flora Crossing(1412) | Track Piece Reward - City Chaos(1384) |
| `Reward_11` | Track Reward - City Chaos(1384)、Track Reward - Bumpy Mountain(1386)、Track Reward -  Ray of Deception(1397)、Track Reward - Frostbite(1398)、Track Reward - Townscape(1420) | Track Reward - Crystal Extraction(1385) |

三套共享（16 条）：Track Reward - Itchy Jaws(1159)、Track Reward - Exile Pass(1161)、Track Reward – Endless Wealth(1247)、Track Reward - Impact Attics(1260)、Track Reward - High Tide Heights(1289)、Track Reward - Leaping Hallows(1290)、Track Reward - Faceplant Precinct(1297)、Track Reward - Derailed(1298)、Track Piece Reward - Break and Enter(1316)、Track Reward - Fatal Fungus(1323)、Track Piece Reward - Kick back(1354)、Track Piece Reward - Downtown Love(1357)、Track Piece Reward - La Pausa(1368)、Track Piece Reward - Crooked Grind(1371)、Track Reward - Haunted Ramps(1387)、Track piece Reward -  Face First(1388)

### `gold`：三套有差别

| 池 | **真·独有**（另两套都没有） | 只和另一套共享 |
|---|---|---|
| `Reward_2` | The Gunslinger(735)、The Gunslinger(736)、The Gunslinger(737)、The Undead Rider(775)、The Undead Rider(776)、The Undead Rider(777) | The Convict(570)、The Convict(571)、The Convict(572) |
| `Reward_7` | Heartbreak Kit(845)、Heartbreak Kit(846)、Heartbreak Kit(847) | The Convict(570)、The Convict(571)、The Convict(572)、Holiday Scarf(795)、Holiday Scarf(796)、Holiday Scarf(797) |
| `Reward_12` | Batbike(53)、Christmas Gal(785)、Christmas Gal(786)、Christmas Gal(787)、Halloween Lady(830)、Halloween Lady(831)、Halloween Lady(832) | Holiday Scarf(795)、Holiday Scarf(796)、Holiday Scarf(797) |

三套共享（21 条）：Wasp(13)、Aloha(18)、Mr. Bones(24)、Stitch(27)、Spirits(29)、Nutcracker(54)、The Yeti(550)、The Yeti(551)、The Yeti(552)、The Cowgirl(560)、The Cowgirl(561)、The Cowgirl(562)、The Sheriff(575)、The Sheriff(576)、The Sheriff(577)、Henchman Uniform Orange(725)、Henchman Uniform Orange(726)、Henchman Uniform Orange(727)、Ninja(820)、Ninja(821)、Ninja(822)

### `silver`：三套有差别

| 池 | **真·独有**（另两套都没有） | 只和另一套共享 |
|---|---|---|
| `Reward_3` | （无） | Agent x2(419)、Donkey x2(459) |
| `Reward_8` | KTM 450 x2(434)、BMW F800 GS x2(444) | Rodeo1(38)、Ceremonial Feathers(49)、Donkey x2(459) |
| `Reward_13` | Stallion x2(414)、KTM 500 x2(429) | Rodeo1(38)、Ceremonial Feathers(49)、Agent x2(419) |

三套共享（6 条）：Venom(23)、Boogeyman(30)、Noble(33)、Hippie(50)、HD XG750R x2(449)、HD Electric x2(454)

### `bronze`：**三套完全相同 ⇒ 轮换池子没有任何效果**

（这三套的内容逐条一样，想让这一档有变化只能用 `reward_slots` 多给几件，或把这一档改指到别的池子。）

### `wood`：**三套完全相同 ⇒ 轮换池子没有任何效果**

（这三套的内容逐条一样，想让这一档有变化只能用 `reward_slots` 多给几件，或把这一档改指到别的池子。）

## 5. 服务端怎么用（WebUI 要写的两个键）

```json
"reward_slots": 1,                      // 1..8：每档一次发几件（每个槽 = 一个池子的一件）
"reward_ids": {"platinum": [3, 2, 4]}   // 按档位写死池子（循环使用）；空 = 内置规则
```

- **想给更多只能加槽**：每件的**数量**（20 宝石 / 25000 金币 / 车×2 / 5 张金票）写死在客户端表的 `ItemAmount` 里，wire 上 pair 的第二个数**不是数量** —— `getRewardItemForSlot` @`0x00635880` 里它唯一一次被用是 `0x00635b80 lsr x3, x20, #0x20`（当「本地查不到时的后备池号」）。所以「更多宝石」= 多叠几个宝石池的槽（`reward_slots` 调大 + `reward_ids` 里重复写 `4`/`9`/`14`）。
- 槽数 > 该档池子个数时池子会**循环**（例如只给 3 个池子却要 5 槽 ⇒ 前三个池子出现两次）。
- `reward_ids` 的每个值是**池子编号数组**（1..15，非法值会被忽略并回退内置规则）。
- 内置规则：第 `i` 档（0..4）用 `Reward_{v*5+i+1}`，`v = (base+k)%3`，`k` 是槽序号，`base` 按 pid 每次请求轮转 —— 这是为了绕开客户端那个**不播种的 `rand()`**（见下）。
- 想「每档都指定」就把五档都写上；只写一档时其余走内置规则。

## 6. 三个必须知道的坑

1. **客户端 `rand()` 不播种**：`getRewardItemForSlot` @`0x00635880` 里 `bl rand` → `rand() % (池子件数)` 挑一件；glibc 首个 `rand()` 恒为 `1804289383`，`% 23 = 11` ⇒ 池子不变就**永远是同一件**（真机 bug：连领两次同一张地图）。所以服务端要换池子，或一次给多个槽。
2. **一次进入模式只拉一次 `reward_config`**：客户端会缓存到离开模式为止 —— 改了配置要让玩家**退出午夜杯再进**才生效（不用重启游戏）。
3. **wire 形状不能乱**：根对象每个成员 = 一个奖杯档，值必须是对象且`reward` 为**第一个成员**、再带一个**等长**兄弟数组（`parseRewardsSlot` @`0x00505d28` 无条件读 `first_child->next`，只给一个成员会崩）。槽数量 = 数组长度，每个槽发一件。

## 7. 建议的 WebUI 交互

- 五档各一行：下拉/多选池子（选项直接读 `server/data/wts_rewards.json` 渲染内容预览），外加一个 1..8 的槽数滑块 → 写回 `tf_config.json` 的 `weekly.reward_ids` / `weekly.reward_slots`（服务端会把槽数夹在 1..8）。
- 校验：池子编号 1..15、数组非空、槽数 1..8；保存后提示「玩家需退出午夜杯再进」。
- 预设：`整车×3 = [3,8,13]`、`服装×3 = [2,7,12]`、`宝石/金票×3 = [4,9,14]`、`混合 = [3,2,4]`（默认）。

