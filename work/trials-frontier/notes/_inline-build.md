### A. 钻石/宝石 + currency

| ID | name/key | type | source |
|---|---|---|---|
| 1 | Coins ITEM_0_1 | currency Type0 | itemdb.txt / dailyrewards.txt MonthlyRewards ID1 |
| 2 | **Gems/Diamonds ITEM_0_2** | premium currency Type0 | dailyrewards.txt MonthlyRewards ID2; pvp_match_rewards.txt ID5 "A gem" |
| 135 | PVP Golden Ticket ITEM_27_0 | currency Type0 | dailyrewards.txt MonthlyRewards ID3 |
| 234 | Event Currency ITEM_234_* | currency Type0 | ItemManager::getNameForItemType @0x437458 |

### B. 零件 crafting parts — ItemId = ITEM_TYPE*5 + TIER (all 50, Type 0)

| ItemId | key | ItemId | key | ItemId | key | ItemId | key | ItemId | key |
|---|---|---|---|---|---|---|---|---|---|
| 5 | ITEM_1_0 Chain T0 | 6 | ITEM_1_1 Chain T1 | 7 | ITEM_1_2 Chain T2 | 8 | ITEM_1_3 Chain T3 | 9 | ITEM_1_4 Chain T4 |
| 10 | ITEM_2_0 Spring T0 | 11 | ITEM_2_1 Spring T1 | 12 | ITEM_2_2 Spring T2 | 13 | ITEM_2_3 Spring T3 | 14 | ITEM_2_4 Spring T4 |
| 15 | ITEM_3_0 Bolt T0 | 16 | ITEM_3_1 Bolt T1 | 17 | ITEM_3_2 Bolt T2 | 18 | ITEM_3_3 Bolt T3 | 19 | ITEM_3_4 Bolt T4 |
| 20 | ITEM_4_0 Nut T0 | 21 | ITEM_4_1 Nut T1 | 22 | ITEM_4_2 Nut T2 | 23 | ITEM_4_3 Nut T3 | 24 | ITEM_4_4 Nut T4 |
| 25 | ITEM_5_0 Metal Sheet T0 | 26 | ITEM_5_1 Metal Sheet T1 | 27 | ITEM_5_2 Metal Sheet T2 | 28 | ITEM_5_3 Metal Sheet T3 | 29 | ITEM_5_4 Metal Sheet T4 |
| 30 | ITEM_6_0 Spark Plug T0 | 31 | ITEM_6_1 Spark Plug T1 | 32 | ITEM_6_2 Spark Plug T2 | 33 | ITEM_6_3 Spark Plug T3 | 34 | ITEM_6_4 Spark Plug T4 |
| 35 | ITEM_7_0 Pipe T0 | 36 | ITEM_7_1 Pipe T1 | 37 | ITEM_7_2 Pipe T2 | 38 | ITEM_7_3 Pipe T3 | 39 | ITEM_7_4 Pipe T4 |
| 40 | ITEM_8_0 Ball Bearing T0 | 41 | ITEM_8_1 Ball Bearing T1 | 42 | ITEM_8_2 Ball Bearing T2 | 43 | ITEM_8_3 Ball Bearing T3 | 44 | ITEM_8_4 Ball Bearing T4 |
| 45 | ITEM_9_0 Piston T0 | 46 | ITEM_9_1 Piston T1 | 47 | ITEM_9_2 Piston T2 | 48 | ITEM_9_3 Piston T3 | 49 | ITEM_9_4 Piston T4 |
| 50 | ITEM_10_0 Gear T0 | 51 | ITEM_10_1 Gear T1 | 52 | ITEM_10_2 Gear T2 | 53 | ITEM_10_3 Gear T3 | 54 | ITEM_10_4 Gear T4 |

### C. 喷漆 bike paints/skins (108, catalog Type 2, IDs = SkinData ID)

| ID | name (bike/slot) | ID | name (bike/slot) | ID | name (bike/slot) | ID | name (bike/slot) |
|---|---|---|---|---|---|---|---|
| 0 | Flaming Tango (2/0) | 1 | America (1/0) | 2 | Poopdeck (6/0) | 3 | Snakebite (7/0) |
| 4 | Chester (8/0) | 5 | Camo (4/0) | 6 | Vanilla Glow (4/1) | 7 | Marine (5/0) |
| 8 | Golden Mantis (5/1) | 9 | Union Jack (2/1) | 10 | Bastille (2/2) | 11 | Mad Bird (7/1) |
| 12 | 8-Ball (3/1) | 13 | Wasp (3/0) | 14 | Neon (2/3) | 15 | Sailor (3/2) |
| 16 | Medic (3/3) | 17 | Soylent (2/4) | 18 | Aloha (3/4) | 19 | Luchador (3/5) |
| 20 | Kaleidoscope (3/6) | 21 | Mithril Mantis (5/2) | 22 | Pumpkin King (5/3) | 23 | Venom (8/1) |
| 24 | Mr. Bones (4/2) | 25 | Scales (6/1) | 26 | Lava (1/1) | 27 | Stitch (2/5) |
| 28 | The Gourd (7/2) | 29 | Spirits (8/2) | 30 | Boogeyman (1/2) | 31 | Raven (3/7) |
| 32 | Heartbreaker (3/8) | 33 | Noble (9/0) | 34 | Winter1 (1/3) | 35 | Winter2 (4/3) |
| 36 | Winter3 (6/2) | 37 | Winter4 (9/1) | 38 | Rodeo1 (5/4) | 39 | Fallout Donkey (19/0) |
| 40 | Molten Donkey (19/1) | 41 | 4thJuly (3/9) | 42 | Cruise Red (11/0) | 43 | Spec Ops Agent (11/1) |
| 44 | Cruise White (11/2) | 45 | Palomino Stallion (10/0) | 46 | Snowy Stallion (10/1) | 47 | Black Stallion (10/2) |
| 48 | Cowhide Armadillo (1/4) | 49 | Ceremonial Feathers (9/2) | 50 | Hippie (7/3) | 51 | Redlynx (2/6) |
| 52 | Undead Horse (10/3) | 53 | Batbike (8/3) | 54 | Nutcracker (2/7) | 55 | Winter Wolf (6/3) |
| 56 | Blizzard Donkey (19/2) | 57 | Candy Cane Donkey (19/3) | 58 | Fanny Pack (5/5) | 59 | Edge (4/4) |
| 60 | KTM_white (13/0) | 61 | Cheetah (7/4) | 62 | Saurus (9/3) | 63 | Hungry Shark (1/5) |
| 64 | Cyclops (9/4) | 65 | The Revenant (7/5) | 66 | Hard Rocker (8/4) | 67 | The Dead Of Day (5/6) |
| 68 | KTM NEON (13/1) | 69 | RED BULL (14/0) | 70 | VENGEANCE KNIGHT (9/5) | 71 | FEASTER DONKEY (19/4) |
| 72 | CAMO_BANDITO (15/0) | 73 | THE RENOWNED BERSERKAR (8/5) | 74 | RED_BMW F800 GS (16/0) | 75 | Ausx_Mantis (5/7) |
| 76 | Ausx_Tango (2/8) | 77 | SANDSTORM (5/8) | 78 | THUNDERSTORM (15/1) | 79 | VALENTINE_IN (6/4) |
| 80 | CLAWRIDE (7/6) | 81 | ICY X (5/9) | 82 | RIPTIDE X-18 (7/7) | 83 | PURPLE DUST (13/2) |
| 84 | DARK_HORSE (16/1) | 85 | DARKMAGIC (8/6) | 86 | TRANZIT_PAINTJOB (5/10) | 87 | CRIMSON_CRUISER (9/6) |
| 88 | RISING_STREAKS (5/11) | 89 | GOLDEN_DIRT (7/8) | 90 | EXTRATERRESTRIAL (6/5) | 91 | HD-2 (17/0) |
| 92 | YELLOW_SUBMARINE (9/7) | 93 | BLACKJACK BRONCO (3/10) | 94 | ALPACA (6/6) | 95 | TURTLE (2/9) |
| 96 | BAD BONE (3/11) | 97 | OPERA (9/8) | 98 | Stache (7/9) | 99 | Christmas Bandito (15/2) |
| 100 | Green Donkey (19/5) | 101 | Blossom (9/9) | 102 | Fudge (2/10) | 103 | Firestarter (8/7) |
| 104 | Nocturnal (6/7) | 105 | Beluga (15/3) | 106 | Sheriff (7/10) | 107 | Dawn Breaker (14/1) |

### D. 服装 rider outfit parts (catalog Type 0) — 146 IDs, 3 per outfit

| RIDER_nn art | helmet | upper | lower | name |
|---|---|---|---|---|
| RIDER_01 | 205 | 206 | 207 | Dogfighter Top |
| RIDER_02 | — | 241 | 242 | Scarf Middle |
| RIDER_04 | 215 | 216 | 217 | Gladiator Top |
| RIDER_05 | 220 | 221 | 222 | Butcher Top |
| RIDER_06 | 235 | 236 | 237 | Hipster Helmet |
| RIDER_07 | 225 | 226 | 227 | Cooler Top |
| RIDER_10 | — | 246 | 247 | Diver Middle |
| RIDER_19 | 295 | 296 | 297 | Pumpkin King top |
| RIDER_21 | 290 | 291 | 292 | The Soldier Head |
| RIDER_25 | — | — | 542 | Snowfox Lower |
| RIDER_26 | 545 | 546 | 547 | Polar Vortex Head |
| RIDER_27 | 530 | 531 | 532 | Death Knight Head |
| RIDER_28 | 550 | 551 | 552 | The Yeti |
| RIDER_29 | 555 | 556 | 557 | Arctic Explorer Top |
| RIDER_30 | 560 | 561 | 562 | The Cowgirl |
| RIDER_32 | 570 | 571 | 572 | The Convict |
| RIDER_33 | 575 | 576 | 577 | The Sheriff |
| RIDER_36 | 720 | 721 | 722 | Indie Rider Head |
| RIDER_37 | 725 | 726 | 727 | Henchman Uniform Orange |
| RIDER_44 | 735 | 736 | 737 | The Gunslinger |
| RIDER_48 | 775 | 776 | 777 | The Undead Rider |
| RIDER_49 | 780 | 781 | 782 | The Hillbilly top |
| RIDER_50 | 785 | 786 | 787 | Christmas Gal |
| RIDER_53 | 795 | 796 | 797 | Holiday Scarf |
| RIDER_54 | 805 | 806 | 807 | KTM Gear Head |
| RIDER_56 | 815 | 816 | 817 | The Temple Rider Top |
| RIDER_57 | 820 | 821 | 822 | Ninja |
| RIDER_59 | 830 | 831 | 832 | Halloween Lady |
| RIDER_61 | — | — | 842 | Redbull Leg |
| RIDER_62 | 845 | 846 | 847 | Heartbreak Kit |
| RIDER_63 | — | 1101 | 1102 | VENGEANCE KNIGHT Uniform Bottom |
| RIDER_64 | 1105 | 1106 | 1107 | Feaster Bunny Head |
| RIDER_65 | 1110 | 1111 | 1112 | BUTCH SUTE Head |
| RIDER_66 | 1115 | 1116 | 1117 | Reputed Hero Top |
| RIDER_67 | 1120 | 1121 | 1122 | Neon Freeze Head |
| RIDER_68 | 1125 | 1126 | 1127 | Neon Blaze Top |
| RIDER_69 | 1130 | 1131 | 1132 | The Wurst Racer |
| RIDER_72 | 1140 | 1141 | 1142 | Ted- Top |
| RIDER_74 | 1185 | 1186 | 1187 | The Sno-Rider Top |
| RIDER_75 | 1190 | 1191 | 1192 | Chris Wheels Caper Top |
| RIDER_76 | 1195 | 1196 | 1197 | The Deputy Head |
| RIDER_77 | 1200 | 1201 | 1202 | Nutjob frank - Top |
| RIDER_78 | 1205 | 1206 | 1207 | The Speedrunner Head |
| RIDER_79 | 1210 | 1211 | 1212 | Bad Bone SR-HEAD |
| RIDER_81 | 1220 | 1221 | 1222 | The Trials Rising Head |
| RIDER_82 | 1225 | 1226 | 1227 | Orbie Top |
| RIDER_83 | 1230 | 1231 | 1232 | HD-Asphalt Feeder - Top |
| RIDER_84 | 1280 | 1281 | 1282 | Moonrider - Top |
| RIDER_85 | 1285 | 1286 | 1287 | JUNGLE_EXPLORER - Top |
| RIDER_86 | 1290 | 1291 | 1292 | Dr Cool - Top |
| RIDER_87 | 1295 | 1296 | 1297 | Madcap Elf - Top |

### E. 摩托蓝图 bike blueprints (catalog Type 0) — ItemId = 369 + 5*nn

| ItemId | BLUEPRINT atlas | bike |
|---|---|---|
| 374 | BLUEPRINT_TIERI | ? (Tango Blueprint Piece) |
| 379 | BLUEPRINT_TIERI | ? (Bronco Blueprint Piece) |
| 414 | BLUEPRINT_9 | STALLION (Stallion x2) |
| 419 | BLUEPRINT_10 | AGENT (Agent x2) |
| 429 | BLUEPRINT_12 | KTM 500-EXC (KTM 500 x2) |
| 434 | BLUEPRINT_13 | KTM 450 Rally (KTM 450 x2) |
| 439 | BLUEPRINT_14 | BANDITO (Bandito Bike Blueprint Piece) |
| 444 | BLUEPRINT_15 | BMW F 800 GS (BMW F800 GS x2) |
| 449 | BLUEPRINT_16 | HARLEY-DAVIDSON XG750R (HD XG750R x2) |
| 454 | BLUEPRINT_17 | HARLEY-DAVIDSON EV (HD Electric x2) |
| 459 | BLUEPRINT_18 | DONKEY (Donkey x2) |
| 384/389/394/399/404/409/424 | nn 3–8, 11 | **INFERRED** from the formula only |

### F. 摩托 bike catalogue (BikeData keys 1–19; not item IDs)

| key | bike | key | bike | key | bike | key | bike |
|---|---|---|---|---|---|---|---|
| 1 | Armadillo | 2 | Tango |
| 3 | Bronco | 4 | Jackal |
| 5 | Mantis | 6 | Marauder |
| 7 | Riptide | 8 | Berserker |
| 9 | Phantom | 10 | Stallion |
| 11 | BMW | 12 | Moonrover |
| 13 | KTM 500 EXC | 14 | KTM 450 RALLY |
| 15 | BANDITO | 16 | BMW F800 GS |
| 17 | HD | 18 | HD EV |
| 19 | Donkey |    |

### G. 地图/赛道 tracks — grantable ones (catalog Type 1 = track, 3 = piece)

| ID | name | type | catalog | ID | name | type | catalog |
|---|---|---|---|---|---|---|---|
| 1105 | WST_COAL_TOWN_TITLE | T1 | wheelspecials | 1107 | WST_CANARY_STREET_TITLE | T1 | wheelspecials |
| 1108 | WST_CANNON_END_TITLE | T1 | wheelspecials | 1112 | WST_TRAPEZE_CHURN_TITLE | T1 | wheelspecials |
| 1123 | WST_BARREL_CHASE_TITLE | T1 | wheelspecials | 1124 | WST_FANG_WALL_TITLE | T1 | wheelspecials |
| 1125 | WST_SUNSHINE_DISTRICT_TITLE | T1 | wheelspecials | 1127 | WST_LOGGING_CAMP_TITLE | T1 | wheelspecials |
| 1129 | WST_DRIFTER_VALLEY_TITLE | T1 | wheelspecials | 1130 | WST_GARBAGE_ROUTE_TITLE | T1 | wheelspecials |
| 1132 | WST_LAZY_CATAPULT_TITLE | T1 | wheelspecials | 1134 | LVL_ROAD_TO_RUIN | T1 | pvp_chip_store |
| 1135 | WST_CITY_OUTSKIRTS_TITLE | T1 | wheelspecials | 1146 | WST_ELEPHANT_GRAVEYARD_TITLE | T1 | wheelspecials |
| 1150 | LVL_MONSTER_LAKE | T1 | dailyrewards | 1156 | WST_CRASHED_CASTLE_TITLE | T1 | wheelspecials |
| 1158 | WST_TORN_HOMEGROWN_TITLE | T1 | pvp_match_rewards | 1159 | LVL_ITCHY_JAWS | T1 | wts_rewards |
| 1160 | LVL_FENLAND_FLAIL | T1 | pvp_match_rewards | 1161 | LVL_EXILE_PASS | T1 | wts_rewards |
| 1163 | WST_TRIBAL_HOMESTEAD_TITLE | T1 | wheelspecials | 1164 | LVL_OPEN_JAW_BOG | T1 | pvp_match_rewards |
| 1166 | WST_CRACKED_PLATEAU_TITLE | T1 | wheelspecials | 1167 | WST_STILTED_PATHWAY_TITLE | T1 | wheelspecials |
| 1181 | WST_DIAMOND_DASH_TITLE | T1 | wheelspecials | 1187 | WST_TORN_CANYON_TITLE | T1 | pvp_match_rewards |
| 1189 | WST_DOOM_DROP_TITLE | T1 | wheelspecials | 1191 | WST_MINECART_DUMP_TITLE | T3 | dailyrewards |
| 1192 | WST_EXPLOSIVE_STORAGE_TITLE | T1 | pvp_chip_store | 1193 | WST_CAVE_CROSSING_TITLE | T1 | pvp_chip_store |
| 1194 | WST_DELIVERY_LINE_TITLE | T1 | pvp_chip_store | 1195 | WST_UNSTABLE_TUNNEL_TITLE | T1 | pvp_chip_store |
| 1196 | WST_CRYSTAL_KINGDOM_TITLE | T1 | pvp_chip_store | 1197 | WST_ABANDONED_MINE_TITLE | T1 | pvp_chip_store |
| 1198 | WST_THE_SHAFT_TITLE | T1 | pvp_chip_store | 1199 | WST_FORBIDDEN_PATH_TITLE | T1 | pvp_chip_store |
| 1201 | WST_TRACTION_TESTGROUND_TITLE | T1 | pvp_chip_store | 1202 | WST_WRECKED_TRACKS_TITLE | T1 | pvp_chip_store |
| 1203 | WST_WASTE_DISPOSAL_TITLE | T1 | pvp_chip_store | 1204 | WST_TERROR_TOWER_TITLE | T1 | wheelspecials |
| 1205 | WST_HAUNTED_HALLOWS_TITLE | T1 | wheelspecials | 1206 | WST_PUMPKIN_PATCH_TITLE | T1 | wheelspecials |
| 1207 | WST_NIGHTMARE_GROTTO_TITLE | T1 | pvp_chip_store | 1208 | WST_SMELTING_POTS_TITLE | T1 | dailyrewards |
| 1209 | WST_UNDERGROUND_SLOPES_TITLE | T1 | pvp_chip_store | 1210 | WST_PROCESSING_CENTER_TITLE | T1 | pvp_chip_store |
| 1214 | LVL_PEACEFUL_PUMMEL | T3 | wheelspecials | 1215 | WST_TOXIN_HARVEST_TITLE | T1 | wheelspecials |
| 1216 | LVL_ROOT_CANAL | T1 | pvp_match_rewards | 1219 | LVL_SUNKEN_SANCTUARY | T1 | pvp_match_rewards |
| 1222 | LVL_CRYSTAL_CROSSING | T1 | pvp_match_rewards | 1223 | WST_ICE_BLOCKADE_TITLE | T1 | wheelspecials |
| 1224 | WST_PERMAFROST_CLIMB_TITLE | T1 | wheelspecials | 1225 | WST_SLEDRIDGE_GORGE_TITLE | T1 | wheelspecials |
| 1227 | WST_ICY_FOOTHILLS_TITLE | T1 | wheelspecials | 1228 | WST_CONTAINER_GROUNDS_TITLE | T1 | wheelspecials |
| 1229 | WST_CHILLED_CLIFFS_TITLE | T1 | wheelspecials | 1230 | WST_SNOWBALL_RIDE_TITLE | T1 | wheelspecials |
| 1231 | WST_FROSTY_PLUMBING_TITLE | T1 | wheelspecials | 1232 | WST_ICEBOUND_HAMLET_TITLE | T1 | wheelspecials |
| 1234 | WST_PENGUIN_LANDING_TITLE | T1 | wheelspecials | 1235 | WST_CHOPPING_DISTRICT_TITLE | T1 | wheelspecials |
| 1236 | WST_SQUALL_SLIDE_TITLE | T1 | wheelspecials | 1237 | WST_FROZEN_FACILITY_TITLE | T1 | wheelspecials |
| 1238 | WST_SNOWMAN_HAVEN_TITLE | T1 | wheelspecials | 1239 | WST_WALRUS_ROAD_TITLE | T1 | wheelspecials |
| 1240 | WST_FROSTMOORE_TITLE | T1 | wheelspecials | 1242 | LVL_PLANT_FOOD | T3 | wheelspecials |
| 1243 | LVL_THE_ASSUMPTION | T1 | wheelspecials | 1244 | LVL_INDIGENOUS_VILLAGE | T1 | pvp_match_rewards |
| 1246 | WST_METAL_MAYHEM_TITLE | T1 | pvp_match_rewards | 1247 | LVL_ENDLESS_WEALTH | T1 | wts_rewards |
| 1249 | LVL_PAIN_MARSH | T1 | pvp_match_rewards | 1250 | LVL_LONGSHOT_LAKE | T1 | pvp_chip_store |
| 1252 | WST_THE_BIG_SWING_TITLE | T1 | wheelspecials | 1253 | LVL_THE_BELL_PIT | T1 | dailyrewards |
| 1254 | Track: Nightwatch Haven | T1 | giftbox | 1260 | LVL_IMPACT_ATTICS | T1 | wts_rewards |
| 1264 | LVL_OVERDOSE | T1 | pvp_chip_store | 1267 | LVL_PUMPKIN_DESERT | T1 | wheelspecials |
| 1270 | LVL_RUINS_OF_DESPAIR | T1 | wheelspecials | 1272 | LVL_DEVIL_HOPPING | T1 | wheelspecials |
| 1274 | LVL_DARK_SANDS | T1 | wheelspecials | 1275 | LVL_BLACK_FOREST | T1 | pvp_match_rewards |
| 1276 | LVL_LIFT_OF_DOOM | T1 | wheelspecials | 1277 | LVL_SPIDER_KINGDOM | T1 | wheelspecials |
| 1281 | LVL_CANDYLAND | T3 | dailyrewards | 1282 | Track: Frost Carnival | T1 | giftbox |
| 1283 | LVL_LOST_DESCENT | T3 | dailyrewards | 1284 | Track: The Naughty List | T1 | giftbox |
| 1285 | Track: Bell Tower | T1 | giftbox | 1287 | LVL_PEAKS_OF_PERIL | T1 | pvp_match_rewards |
| 1288 | LVL_AVALANCHE_STREW | T1 | pvp_match_rewards | 1289 | LVL_HIGH_TIDE_HEIGHTS | T1 | wts_rewards |
| 1290 | LVL_LEAPING_HOLLOWS | T1 | wts_rewards | 1292 | LVL_MUDDY_MOUNDS | T1 | wheelspecials |
| 1293 | LVL_ENDURANCE_RUN | T1 | wheelspecials | 1294 | LVL_LOST_RACE_TRACK | T1 | wheelspecials |
| 1296 | WST_KTM_COURSE_TITLE | T1 | pvp_match_rewards | 1297 | LVL_FACEPLANT_PRECINCT | T1 | wts_rewards |
| 1298 | LVL_DERAILED | T1 | wts_rewards | 1301 | WST_SAFE_ESCAPE_TITLE | T1 | pvp_match_rewards |
| 1302 | LVL_PEACE_HAMMER | T1 | wheelspecials | 1303 | LVL_COLD_CUT_CORNER | T1 | pvp_match_rewards |
| 1304 | LVL_BAYOU_BOATRIDE | T1 | wheelspecials | 1305 | LVL_ACROBAT_QUARTER | T1 | pvp_match_rewards |
| 1307 | LVL_TREACHERY | T1 | pvp_match_rewards | 1308 | LVL_LOST_DESCENT | T3 | wheelspecials |
| 1309 | LVL_FAIR_WINDS | T1 | wheelspecials | 1310 | LVL_LOLLYGAGGING | T1 | pvp_match_rewards |
| 1311 | LVL_DARK_SMOKE | T3 | wheelspecials | 1316 | LVL_BREAK_AND_ENTER | T3 | wts_rewards |
| 1318 | LVL_RABBIT_HELL | T1 | pvp_match_rewards | 1323 | LVL_FATAL_FUNGUS | T1 | wts_rewards |
| 1330 | LVL_REST_IN_PIECES | T1 | pvp_match_rewards | 1333 | LVL_FERMENTED_CAVES | T1 | pvp_match_rewards |
| 1334 | LVL_DUAL_HOPS | T1 | wheelspecials | 1335 | LVL_HANGING_GARDENS | T1 | wheelspecials |
| 1336 | LVL_MUSHROOM_BOOM | T1 | wheelspecials | 1338 | LVL_RAMPANT_RAMPS | T3 | wheelspecials |
| 1341 | LVL_LOTUS_SWAMP | T1 | wheelspecials | 1342 | LVL_RADICAL_ROADWORKS | T1 | wheelspecials |
| 1343 | LVL_CLIFF_HANGER | T1 | wheelspecials | 1344 | LVL_DOUBLE_BARREL | T3 | wheelspecials |
| 1347 | LVL_SPARE_RIBS | T1 | wheelspecials | 1349 | LVL_LOPSIDED | T1 | dailyrewards |
| 1350 | LVL_AIR_ASSAULT | T3 | wheelspecials | 1351 | LVL_REVERSE_ENGINEERING | T3 | wheelspecials |
| 1354 | LVL_KICK_BACK | T3 | wts_rewards | 1357 | LVL_DOWNTOWN_LOVE | T3 | wts_rewards |
| 1359 | LVL_TOXIC_GARDEN | T1 | wts_rewards | 1360 | LVL_TEMPLE_OF_DOOM | T1 | pvp_match_rewards |
| 1362 | LVL_SLIPPERY_ICE | T1 | pvp_match_rewards | 1364 | LVL_DARK_ICE_VALLEY | T1 | pvp_match_rewards |
| 1365 | LVL_SNOWMAN_PEAKS | T1 | pvp_match_rewards | 1366 | LVL_ADAGIO_FLOW | T1 | pvp_chip_store |
| 1367 | LVL_WACKY_RIFTS | T1 | pvp_chip_store | 1368 | LVL_LA_PAUSA | T3 | wts_rewards |
| 1371 | LVL_CROOKED_GRIND | T3 | wts_rewards | 1372 | LVL_NIGHT_CRAWLING | T1 | pvp_match_rewards |
| 1375 | LVL_BOMBER_BLISS | T1 | wts_rewards | 1376 | LVL_MT_WHIPLASH | T1 | dailyrewards |
| 1377 | LVL_THE_SWITCHBLADE | T1 | pvp_match_rewards | 1378 | LVL_SMURFIN_LEDGES | T1 | pvp_match_rewards |
| 1379 | LVL_CURVED_HINGES | T1 | pvp_match_rewards | 1380 | LVL_BLOSSOM_GROVE | T1 | pvp_match_rewards |
| 1381 | LVL_CRYSTAL_FLOW | T1 | wts_rewards | 1383 | LVL_NIGHT_LIGHTS | T1 | wts_rewards |
| 1384 | LVL_CITY_CHAOS | T3 | wts_rewards | 1385 | LVL_CRYSTAL_EXTRACTION | T1 | wts_rewards |
| 1386 | LVL_BUMPY_MOUNTAIN | T1 | wts_rewards | 1387 | LVL_HAUNTED_RAMPS | T1 | wts_rewards |
| 1388 | LVL_FACE_FIRST | T3 | wts_rewards | 1389 | LVL_FLORAL_LANE | T1 | pvp_match_rewards |
| 1390 | LVL_HAPPY_FLING | T1 | pvp_match_rewards | 1392 | LVL_SNOWBALL_SURPRISE | T1 | pvp_match_rewards |
| 1394 | LVL_CITY_HALLWAY | T1 | wts_rewards | 1395 | LVL_WILDWOOD_ESCAPE | T3 | wheelspecials |
| 1396 | LVL_PEAK_ROUTE | T3 | wheelspecials | 1397 | LVL_RAY_OF_DECEPTION | T1 | wts_rewards |
| 1398 | LVL_FROSTBITE | T1 | wts_rewards | 1399 | LVL_BARTER_TOWN | T3 | wheelspecials |
| 1400 | LVL_DOOM_RACE | T1 | wheelspecials | 1401 | LVL_CITY_RUN | T1 | wheelspecials |
| 1402 | LVL_HOMELAND_EXPRESS | T1 | pvp_match_rewards | 1403 | LVL_FROZEN_CLIFFS | T3 | wheelspecials |
| 1404 | LVL_SWAMP_FATHOM | T1 | wts_rewards | 1406 | LVL_ROCKY_CHAMBERS | T1 | wts_rewards |
| 1407 | LVL_WASTELAND | T1 | wts_rewards | 1408 | LVL_URBAN_SMASH | T1 | wts_rewards |
| 1409 | LVL_DUAL_SNOWFEST | T1 | pvp_match_rewards | 1411 | LVL_BLAZING_HOP | T1 | pvp_match_rewards |
| 1412 | LVL_FLORA_CROSSING | T1 | wts_rewards | 1413 | LVL_HIGH_VILLE | T1 | pvp_match_rewards |
| 1414 | LVL_DESERT_PUNK | T1 | pvp_match_rewards | 1415 | LVL_FROST_POINT | T1 | pvp_match_rewards |
| 1417 | LVL_MEAN_STREET | T1 | pvp_match_rewards | 1418 | LVL_GOLDEN_RIDE | T3 | wheelspecials |
| 1419 | LVL_DUSTZONE | T3 | wheelspecials | 1420 | LVL_TOWNSCAPE | T1 | wts_rewards |
| 1421 | LVL_ALPINE | T1 | wheelspecials | 1422 | LVL_TOWNSHIP | T3 | wheelspecials |
| 1423 | LVL_ABANDONED_COLONY | T3 | wheelspecials | 1424 | LVL_TIPTOP | T3 | wheelspecials |
| 1425 | LVL_ORBICULAR_ESCAPE | T3 | wheelspecials | 1426 | LVL_DOLOMITE | T3 | wheelspecials |
| 1429 | LVL_STREETSCAPE | T3 | wheelspecials | 1430 | LVL_APOSTATIZE | T3 | wheelspecials |
| 1431 | LVL_VIADUCT | T3 | wheelspecials | 1432 | LVL_URBAN_SPRAWL | T1 | wheelspecials |
| 1433 | LVL_SNOW_FLURRY | T1 | pvp_match_rewards | 1434 | LVL_HEAVENWARD | T1 | pvp_match_rewards |
| 1435 | LVL_WILD_ZONE | T1 | pvp_match_rewards | 1436 | LVL_DUTSCHERS_DEN | T1 | pvp_match_rewards |
| 1437 | LVL_URBAN_COMPLEX | T1 | pvp_match_rewards | 1438 | LVL_MARSH_RIDE | T1 | pvp_match_rewards |

Total grantable track/track-piece IDs: 196. The full 382-row level list (ID → LVL_* name) is in the `item-ids.md` §6 table.

### H. Leaderboard rank → reward mapping (PVPMatchRewards)

| rank key | slot | RewardID | item granted | amount | chance |
|---|---|---|---|---|---|
| BRONZE0 | 0 | 1 | coins ItemId 1 | 50 | 0.5 |
| BRONZE0 | 1 | 1 | coins ItemId 1 | 100 | 0.3 |
| BRONZE0 | 2 | 5 | gem ItemId 2 | 1 | 0.001 |
| BRONZE0 | 3 | 1 | coins ItemId 1 | 150 | 0.15 |
| BRONZE0 | 4 | 2 | coins ItemId 1 | 200 | 0.05 |
| SILVER0 | 0 | 100 | SPECIAL PVP REWARD -> ItemId 145 | 1 | 0.05 |
| SILVER0 | 1 | 1 | coins ItemId 1 | 100 | 0.5 |
| SILVER0 | 2 | 5 | gem ItemId 2 | 1 | 0.01 |
| SILVER0 | 3 | 2 | coins ItemId 1 | 250 | 0.35 |
| SILVER0 | 4 | 3 | coins ItemId 1 | 500 | 0.1 |
| GOLD0 | 0 | 100 | SPECIAL PVP REWARD -> ItemId 145 | 1 | 0.1 |
| GOLD0 | 1 | 1 | coins ItemId 1 | 500 | 0.4 |
| GOLD0 | 2 | 5 | gem ItemId 2 | 1 | 0.03 |
| GOLD0 | 3 | 2 | coins ItemId 1 | 750 | 0.28 |
| GOLD0 | 4 | 3 | coins ItemId 1 | 1000 | 0.15 |
| PLATINUM0 | 0 | 100 | SPECIAL PVP REWARD -> ItemId 145 | 1 | 0.15 |
| PLATINUM0 | 1 | 1 | coins ItemId 1 | 1000 | 0.45 |
| PLATINUM0 | 2 | 5 | gem ItemId 2 | 1 | 0.03 |
| PLATINUM0 | 3 | 2 | coins ItemId 1 | 1500 | 0.3 |
| PLATINUM0 | 4 | 3 | coins ItemId 1 | 2000 | 0.1 |

| league medal | XP multiplier |
|---|---|
| M_PLAT | 20.0 |
| M_GOLD | 8.0 |
| M_SILV | 3.0 |
| M_BRON | 0.5 |

### I. Misc grantable IDs (catalog Type 0)

| ID | name | ID | name |
|---|---|---|---|
| 118 | Special Event Item (Pumpkin) | 131 | Kindling Set I |
| 132 | Magnifying Glass Set I | 133 | Yeti Fur Set I |
| 134 | Pumpkin Set I | 145 | SPECIAL PVP REWARD ITEM |
| 150 | Doughnut | 151 | Bronco Buck Set I |
| 152 | Event Point Set I | 171 | VIP membership badge |
| 179 | unknown (placeholder comment) | 635 | Coin Magnet boost |
| 637 | Rarified Fuel boost | 1170 | Rally Ticket Silver Medal |
| 1174 | Event Ticket | — | — |