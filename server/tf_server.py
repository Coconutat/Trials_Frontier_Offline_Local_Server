#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trials Frontier 本地服务器（本地存档/离线后端）

阶段目标：先把客户端所有请求记录下来，再逐个端点填响应。

用法：
    python server/tf_server.py --host 0.0.0.0 --port 8000

响应规则放在 server/rules.json（可热改，每次请求重新读取）：
    {
      "POST /v2/profiles/sessions": {
        "status": 200,
        "headers": {"Content-Type": "application/json"},
        "body": {...}
      },
      "*": {"status": 200, "body": {...}}
    }
键格式 "<METHOD> <路径前缀>"；"*" 是兜底。body 是 dict/list 则序列化成 JSON，
是字符串则原样发送（便于塞任意文本）。

日志：
  - 控制台
  - work/trials-frontier/notes/server-log.jsonl（每条请求一行 JSON，含请求/响应体）
"""

import argparse
import atexit
import copy
import functools
import hashlib
import json
import os
import random
import re
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_PATH = os.path.join(ROOT, "work", "trials-frontier", "notes", "server-log.jsonl")
RULES_PATH = os.path.join(HERE, "rules.json")

# ------------------------------------------------------------------ 可调参数
# 匹配/赛季这些「运营参数」不写死在代码里，集中放 server/data/tf_config.json。
# 按 mtime 热加载：WebUI（未来）或人手改完存盘即可生效，不用重启服务器。
CONFIG_PATH = os.path.join(HERE, "data", "tf_config.json")

# 内置默认值 = 发布版 tf_config.json 的内容；文件缺失/写坏时兜底，保证服务器照常起。
_TF_CONFIG_DEFAULTS = {
    "matchmaking": {
        "enabled": True,
        # 服务器上还有别的真人「在线」（见 active_window_seconds）但没有排队时，
        # 最多等这么久再发人机；没有别的真人时立刻发人机，不等。
        "bot_wait_seconds": 60,
        "active_window_seconds": 300,
        # 查询队列/对局的过期时间，防止玩家强杀进程后留下僵尸队列。
        "search_ttl_seconds": 1800,
        # ★ 能同时开几条 PVP 对局（= 客户端 `pvp_match_settings.ranked_match_slots`，
        #   同一份配置两处共用）。用户回忆的机制：**免费 3 条**，超过之后每开一条
        #   要花一张黄金门票（`additional_match_cost`），到 `ranked_match_limit` 封顶。
        "ranked_match_slots": 3,
        # 第 4 条起每条新对局收几张黄金门票（0 = 免费无限开）。
        "additional_match_cost": 1,
        # 并行对局的硬上限（防止客户端狂点「全新对决」把状态撑爆）。
        "ranked_match_limit": 10,
        # 人机对局用的赛道（幽灵库里必须存在这一条赛道）。
        "track_id": 1041,
        "bot_profile_id": "44444444-4444-4444-4444-444444444444",
        "bot_name": "GhostRider",
        # 对局时长（秒）——PVPMatch+0x198，客户端用 start_time+该值 算剩余时间
        # （`PVPMatch::getRemainingTime` @0x5ed1e4 = start_time + total_time - now）。
        # 用户 m04404：一整轮是 **6 小时**，慢慢计时到 0。
        # ★ 必须同时让 start_time 稳定（见 `_pvp_make_match` 的 `start`）：每轮都回
        #   now 会让剩余时间永远是满值，症状就是「过几秒又跳回满值」。
        "match_duration_seconds": 21600,
        # 友军对局（非排位）的时长。用户 m03981：这个值以前硬编码在 `_pvp_season()`
        # 里（3600），现在搬进配置，WebUI 能改。
        "friendly_match_duration": 3600,
        # 一局 3 条赛道（用户 m04404 引同服玩家 Assassins-Cry 实测：开一局 3 条赛道，
        # 倒计时结束前赢下 2 条就赢这一局）。
        # ★ `parseMatch` 的 tracks 循环没有边界检查（0x4fddc0 起 `madd x9,x28,#0x34,x21`），
        #   >3 条会一路写穿到 PVPMatch+0xa4（chips）/ +0xa8（tickets）。**最多 3 条。**
        # 用户 m04586：PVP 一局是**随机地图** —— 所以这里默认留空，让 `_pvp_tracks()`
        # 每局从 `candidate_tracks` 里随机抽 3 条。填了就固定用填的那三条。
        "track_ids": [],
        # 可以出现在 PVP 对局里的赛道池。★ 必须是幽灵库里真有幽灵的赛道，否则
        # `_pvp_ghost_time` 会退到 30 s 的兜底值（人机成绩会显得很假）。
        "candidate_tracks": [
            1023, 1024, 1032, 1033, 1036, 1037, 1041, 1051, 1062, 1068, 1069, 1070,
            1075, 1087, 1088, 1090, 1097, 1099, 1106, 1123, 1133, 1221, 1241, 1291,
        ],
        # ── AI 控制（用户 m04835：留给 WebUI 配置）──
        # 人机成绩 = 玩家成绩 × bot_time_margin_pct + bot_time_margin_ms。
        # ★ 必须 ≥ 1.0（`_pvp_bot_time` 会强制夹回去）：人机比玩家快 → parseMatch
        #   0x4fe0dc 的 score 比较会把赛道判给人机，真机症状是「跑完以后幽灵比我快」。
        "bot_time_margin_pct": 1.018,
        "bot_time_margin_ms": 400,
        # 对局赛道里发给客户端的车种 ID（1 起始，见 UpgradeManager::getBikeIndexByID = id-1）。
        # ★ 必须写进 tracks[].owner_change_time：PVPManager::onStartRaceSent @0x5e59ec 是
        #   `ldr w9,[match+0x24]; str w9,[GameWorld+0x1efc]`，而 match+0x24 就是
        #   第 0 条轨道 +0x20（= setOwner 写的那个字段）。填 0 → getBike(0)=NULL →
        #   EffectManager::checkNeedForSpecialEffects 解引用 [x0+0x100] 崩。
        # ⚠ `bike_random = True`（默认）时这个值只在「随机不出任何车」时兜底 ——
        #   每场比赛的车由 `_pvp_pick_bikes()` 按**每条赛道自己的车级别**（`levels[].bike`）
        #   现挑。`bike_random = False` 时它就是全部赛道的车（老行为）。
        "bike_id": 1,
        # 发车方式：True（默认，原版行为）= 每条赛道按自己的车级别从玩家**已拥有**的
        #   剧情车里随机发一台；False = 全部赛道都发上面那个 bike_id。
        # ★ 原版规则（用户 m07949）：车和地图是随机的，**车级别跟地图级别挂钩**
        #   （1 级车跑 1 级图…）。客户端把关的是 `LevelManager::isCorrectBikeTier
        #   @0x47c170`：车 Tier == 图的 `B`，或车 Tier 是 255（特殊车），或图的 `B`
        #   是 255 才放行 —— 发错级别的车 = 玩家进不去 / 跑起来是别人的车。
        "bike_random": True,
        # 随机发车的池子：只发**剧情默认车**（1..9，Armadillo…Phantom）。
        #   用户 m08106：「随机最好只有游戏默认的可以在剧情里获得车…这是一个兜底的安全范围」。
        #   `story_only = False` 时会把商店/DLC 车也放进池子（T255 的特殊车算单独一档，
        #   见 `_pvp_pick_bikes()`）。
        "bike_story_only": True,
        # 局内票（免费票）：满 N 张，每 interval 秒回 1 张，用完才动黄金票。
        "free_tickets_max": 3,
        "free_tickets_initial": 3,
        "free_tickets_interval_seconds": 3600,
        # 天梯起始等级。25 = 最低级；0 = Legend，不能作为普通新号初始值。
        #   `MenuzStatePVPPostMatch::increaseOneStar`
        #   @0x730698 一看到 0 就直接返回，晋级动画永远不会触发。
        #   总共 25 级（`MissingRewardFallbackRewards` 恰好 25 个键 "1".."25"）。
        "start_rank": 25,
    },
    "season": {
        "track_id": 1041,
        "title_text": "Trials Frontier",
        "banner_path": "/pvp_banner/season.png",
        "duration_days": 30,
        # ── 碉堡运营（用户 m03981：要能写「这是第几个赛季」、要能推进赛季）──
        # `advance` = 「推进到下一赛季」按了几次。届号本来是时间派生的
        #   （`int(time.time())//duration + 1`），这里加一个整数偏移就够：窗口跟着
        #   届号走（`_pvp_season_window` 由届号反推 start/end），所以推进一次 =
        #   本届窗口整体前移一个 duration；玩家下次 `close_season` 时发现届号变了，
        #   就按旧届结算并复位段位（`h_pvp_close_season`）。
        #   ★ 只加在**自动推导**分支：显式传届号（`h_pvp_season_data` 的历史查询）
        #     必须拿到自己那个届的真实窗口。
        "advance": 0,
        # `display_offset` = 只改**下发给客户端的届号**（= 能自己编号：内部第 692 届
        #   想显示成第 1 赛季就填 -691）。内部届号、start/end、玩家档案里的 season
        #   全都不动 —— 客户端只拿这个数字当横幅缓存文件名（`season_banner%d.bnr`），
        #   真正的"第 N 赛季"文字在客户端里没有显示点（见 CONTEXT.md「赛季编号」）。
        "display_offset": 0,
        # ★ `star_array` @0xb86be8 —— 扁平 int 数组，最多 26 个
        #   （`parseSeason` @0x4fd694：struct(0x00e21c78)+428+i*4，`cmp i,#0x19; b.gt` 停）。
        #   `PVPManager::getStarCountForRank(rank)` @0x5e16e8 读的是
        #   `PVPManager+0x1ac + 4*(rank-1)`，也就是 **star_array[rank-1]**
        #   = 「从该 rank 升上去需要几颗星」。index 0 = rank 1（最高），
        #   index 24 = rank 25（最低）。不发/发空 → 客户端读未初始化内存。
        # 用户 m04404（引同服玩家 Assassins-Cry 2026-10-04 的实测）：
        #   25→15 每级 2 星 / 15→10 每级 3 星 / 10→5 每级 4 星 / 5→传奇 每级 5 星。
        # 即 rank 1..5 = 5 星、6..10 = 4 星、11..15 = 3 星、16..25 = 2 星。
        "star_array": [5, 5, 5, 5, 5, 4, 4, 4, 4, 4,
                       3, 3, 3, 3, 3, 2, 2, 2, 2, 2,
                       2, 2, 2, 2, 2],
        # ★ `product_list` @0xb86bf3 —— `[{"product_id": "<商城 id>", "amount": int}]`，
        #   `parseSeason` @0x4fd230 处理；`chip_shop.goldentickets` @0xb86c00 是特例
        #   （给黄金参赛票 item id 0x87=135 重定价），其余 product_id 在
        #   UpgradeItemData 注册表里查不到就被静默忽略 —— 所以这里只放确定存在的 id。
        "product_list": [{"product_id": "chip_shop.goldentickets", "amount": 3}],
        # ★ 筹码曲线（`pvp_match_settings.chip_equation_x/y`）。
        #   客户端 `PVPManager::getNumChipsTotal(t)` @0x5e1838 = `pow(t, x) * y`，
        #   t = `now - PVPTrack+0x20`（owner_change_time，unix 秒）。
        #   同一曲线既决定**筹码枚数**，也决定**圆环填充进度**
        #   （`PVPMatch::getChipProgress` @0x5ed8c4 返回它的小数部分）。
        #   x=0.5 / y=0.5：占住 t 秒产 floor(0.5*sqrt(t)) 枚 ——
        #   4 秒第一枚、16 秒第二枚、36 秒第三枚、1 小时约 30 枚、6 小时约 73 枚，
        #   符合用户 m04404 转述的「前期累积快，然后慢慢变慢」。
        #   发 0/0 会让圆环永远空着（m04710 的真机症状），**绝对不要回退成 0**。
        "chip_equation_x": 0.5,
        "chip_equation_y": 0.5,
        # ★ `current_season.rewards` @0xb8d6de —— `parseSeasonData` @0x4fe4f4 的
        #   这里是扁平运营配置；wire 由 _pvp_season_rewards 转成嵌套 rewards 数组。
        #   （按 `rank` 归组进外层 vector，同一 rank 可给多个 (item_id, amount)；
        #   `rank < 0` 跳过）。item_id 的语义沿用 `tr::PVPReward`：
        #     1 = 金币、2 = 钻石；145 的 amount = 原表 RewardID。
        #     库存 ItemId 不能冒充季奖 RewardID；每档数额为增量，客户端累加已达成档位。
        #   ⚠ `ItemId` 只在同一个 `Type` 内唯一，这里发的是物品栏 item id（Type 0）。
        "rewards": [
            # ★ 客户端对 rank R 结算的是「**index >= R 的所有档之和**」（见
            #   pvp-reward-contract.md：`getCombinedSeasonRewards @0x5e7364`），
            #   所以 0..25 **每一档都要有**，缺档就等于那一级什么都不给。
            #   形状刻意保持扁平 `{rank,item_id,amount}` —— 未来的 WebUI 直接编辑
            #   这张表并导出成模板即可，不需要懂嵌套 wire 格式（wire 由
            #   `_pvp_season_rewards()` 转成 nested）。
            #   item_id: 1=金币、2=钻石；**145 的 amount 是 RewardID，不是物品数量**。
            {"rank": 0, "item_id": 1, "amount": 1000},     # Legend
            {"rank": 1, "item_id": 1, "amount": 500},
            {"rank": 2, "item_id": 1, "amount": 400},
            {"rank": 3, "item_id": 1, "amount": 300},
            {"rank": 4, "item_id": 1, "amount": 275},
            {"rank": 5, "item_id": 1, "amount": 250},
            {"rank": 6, "item_id": 1, "amount": 240},
            {"rank": 7, "item_id": 1, "amount": 230},
            {"rank": 8, "item_id": 1, "amount": 220},
            {"rank": 9, "item_id": 1, "amount": 210},
            {"rank": 10, "item_id": 1, "amount": 200},
            {"rank": 11, "item_id": 1, "amount": 190},
            {"rank": 12, "item_id": 1, "amount": 180},
            {"rank": 13, "item_id": 1, "amount": 170},
            {"rank": 14, "item_id": 1, "amount": 160},
            {"rank": 15, "item_id": 1, "amount": 150},
            {"rank": 16, "item_id": 1, "amount": 140},
            {"rank": 17, "item_id": 1, "amount": 130},
            {"rank": 18, "item_id": 1, "amount": 120},
            {"rank": 19, "item_id": 1, "amount": 110},
            {"rank": 20, "item_id": 1, "amount": 100},
            {"rank": 21, "item_id": 1, "amount": 90},
            {"rank": 22, "item_id": 1, "amount": 80},
            {"rank": 23, "item_id": 1, "amount": 70},
            {"rank": 24, "item_id": 1, "amount": 60},
            {"rank": 25, "item_id": 1, "amount": 50},
            # 钻石：只在最低三段给（原有运营配置，未改动）。
            {"rank": 1, "item_id": 2, "amount": 5},
            {"rank": 2, "item_id": 2, "amount": 4},
            {"rank": 3, "item_id": 2, "amount": 3},
            # 特殊季奖：item_id 145 + amount=RewardID。每档**只能有一条**，
            # 写重了就是双发（曾经真的写重过，见 _pvp_season_rewards 的去重保护）。
            {"rank": 1, "item_id": 145, "amount": 220},
            {"rank": 5, "item_id": 145, "amount": 20040},
            {"rank": 10, "item_id": 145, "amount": 20035},
            {"rank": 15, "item_id": 145, "amount": 20030},
            {"rank": 20, "item_id": 145, "amount": 20025},
            {"rank": 25, "item_id": 145, "amount": 20020},
        ],
    },
    # 筹码（chips）。
    # 用户 m03154 的规则：筹码不是开局白送的 200，是「按赛道定期生成的硬件」
    # —— 每拥有一条赛道上就跑一条产线，定期产出一枚筹码；天梯最低（25 级）
    # 起步是 0，升到某个等级才额外给一点。
    #
    # ★ 局内筹码曲线在 `season.chip_equation_x/y`（客户端与服务端共用同一条曲线，
    #   客户端还会拿它画赢家头像上那个顺时针填充的圆环 —— 见 `_chip_curve` 与
    #   `_pvp_season` 的注释）。早期的「PVPTrack+0x20 同时是车种 ID、所以只能发
    #   0/0」结论是把 `PVPTrack+0x24`(bike) 与 `PVPTrack+0x20`(owner_change_time)
    #   搞混了，已在 m04710 修正。
    "chips": {
        # 起步筹码（用户规则：最低天梯 0）。
        "start": 0,
        # 每条已拥有赛道每隔这么多秒产 1 枚（0 = 不产）。
        # ★ 2026-10-05 真机复核后关掉（=0）：它会**在没有任何对局结算的情况下**让钱包
        #   自己长大（玩家原话「都没结束。都没结算哪来的筹码」），而且和客户端画的那个
        #   圆环是**两套并行的产币机制** —— 圆环那条（`chip_equation_x/y`，占住赛道后
        #   随时间产、整局到期由 `_pvp_bank_match_chips` 入账）已经实现了「谁占了赛道
        #   谁就产币」这个规则。要重新打开就把这个值设回 3600（或 WebUI 里调）。
        "per_track_seconds": 0,
        # 上限（0 = 不限）。★ 别再用 200：筹码商店里最贵的一条赛道 63000 筹码，
        # 顶到 200 会让商店永久锁死。
        "max": 0,
        # ── 局内筹码（用户 m04404 引同服玩家 Assassins-Cry 的实测规则）：
        #   拿到这条赛道就开始累积，**前期快、后面越来越慢**；对手把赛道抢回去 →
        #   累积速度重置，又从快开始变慢；整局跑完才结算成 `chips` 余额。
        #   曲线见 `season.chip_equation_x/y`（`_pvp_match_chips` 用的就是它）。
        #
        # ── 人机不另给筹码（曾经为「对手头像下的红筹码」播种 500，是调试值）。
        #   它的余额就是上次结算剩下的；真人这边照常按赛道产币。
        # 整局结算时**输家保住**的比例（%），其余归赢家。
        # ★ 客户端 `getChipHeritage @0x5dec48` 里那两个系数是硬编码的 0.5/0.1，
        #   只影响赛后界面文案，真正的转移比例由这里决定。
        "match_loser_keeps_pct": 50,
    },
    "weekly": {
        "track_id": 1041,
        # 0 = 自动用本周赛道（见 _weekly_leaderboard_id）；>=1 = 显式榜 id。
        "leaderboard_id": 0,
        # 合成对手数量（0 = 关）、时间基准（0 = 自动取最快内置幽灵）与两侧幅度（%）；
        # fast 只放开一点点，否则玩家永远够不到 1%（见 _weekly_fake_field）。
        "fake_field": 0,
        "fake_field_base_ms": 0,
        "fake_field_fast_pct": 3,
        "fake_field_slow_pct": 25,
        # 每周次数上限（= left_retry_times）与用完后的冷却时长（秒）。
        "left_retry_times": 3,
        "cooldown_seconds": 3600,
        # 模拟翻周：1 = 假装"这一周已经结束、服务器进到下一周"（真机验奖励/敲奖杯）。
        "week_offset": 0,
        # 每档奖杯一次发几件（1..3）。客户端在池子里用**它自己的 rand()** 挑一件，
        # 而那个 rand() 不播种 ⇒ 每次同一件；多给几个槽就等于多给几件（见 reward_config）。
        "reward_slots": 1,
        # 按档位写死池子（可选）。空 = 内置规则（第 i 档 → Reward_{v*5+i+1}）。
        # 例：{"platinum": [3, 8, 13]} = 最高奖改发"整台车×2"那三套池子。
        "reward_ids": {},
        # 一届（=一周）的长度，天。7 = 原版；★ 非 7 天**没有真机验证过**（客户端把窗口
        # 时间戳写进存档物品 1165/1166），后台界面要如实标注「实验性」。
        "window_days": 7,
        # ── 本届的车（用户 m07949 / m08106）──
        # 原版规则：午夜杯**整周一台车**（游戏自带文案："you are given one track and
        #   one bike to play"），车级别跟着赛道级别走。0 = 按赛道的车级别自动随机
        #   （用届号当种子 ⇒ 整周不变）；>=1 = 整届固定发这台（客户端
        #   `LevelManager::isCorrectBikeTier @0x47c170` 会卡级别，填错玩家进不去）。
        "bike_id": 0,
        # 租借升级：玩家没这台车、或自己那台升级更低时，客户端按这个级数给一台
        #   「租借车」（游戏文案：loan bike，「will not go to your garage」）。
        #   ★ 单位 = 升级级数（0..10），四个部件同值；`force_upgrade` 固定发 0
        #   ⇒ 客户端取 `max(玩家当前, 这个值)`：玩家升级更高就用玩家自己的，
        #   更低就用租借值 —— 「给你保底跑」（用户 m07949）。
        #   用户 m08106：四个部件各 5 级。
        "loan_upgrade": 5,
    },
    "appcfg": {
        # `h_app_configuration` 发给 Java/DLC 的基址：请求 Host 是回环时代替成它。
        # 留空 = 自动探测本机局域网 IP（见 _public_host / _lan_ip）。
        "public_host": "",
    },
}

_CONFIG_LOCK = threading.Lock()
_CONFIG_CACHE = {"mtime": None, "data": None}

# profileId -> 最近一次带认证请求的时间戳。用来判断「服务器上到底有没有别的真人」。
ACTIVE_PLAYERS = {}


def _deep_merge(base, over):
    out = dict(base)
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def tf_config():
    """读 server/data/tf_config.json（mtime 变了才重读），缺项用内置默认值补齐。"""
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        mtime = None
    with _CONFIG_LOCK:
        if _CONFIG_CACHE["data"] is not None and _CONFIG_CACHE["mtime"] == mtime:
            return _CONFIG_CACHE["data"]
        raw = {}
        if mtime is not None:
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                    raw = json.load(fp)
            except Exception as exc:
                print("[cfg] %s 读不了，先用内置默认值：%r" % (CONFIG_PATH, exc), flush=True)
                raw = {}
        data = _deep_merge(_TF_CONFIG_DEFAULTS, raw if isinstance(raw, dict) else {})
        _CONFIG_CACHE["mtime"] = mtime
        _CONFIG_CACHE["data"] = data
        return data


def cfg(*path, **kw):
    """按路径取配置项：cfg("matchmaking", "bot_wait_seconds", default=60)。"""
    node = tf_config()
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return kw.get("default")
        node = node[key]
    return node


def cfg_int(*path, **kw):
    """取整数配置项；值非法（写了个字符串之类）时回退默认值。"""
    default = kw.get("default", 0)
    try:
        return int(cfg(*path, default=default))
    except (TypeError, ValueError):
        return int(default)


def cfg_set(path, value, kind="config"):
    """就地改配置并落盘——WebUI 的运营参数页就靠它。path 是键列表。

    `kind` 只影响审计记录里的分类（"weekly" / "pvp" / "undo" …），界面按它筛"最近改动"。
    """
    if not isinstance(path, (list, tuple)) or not path:
        raise ValueError("path 不能为空")
    path = [str(k) for k in path]
    with _CONFIG_LOCK:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                raw = json.load(fp)
            if not isinstance(raw, dict):
                raw = {}
        except Exception:
            raw = {}
        node = raw
        for key in path[:-1]:
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                node[key] = nxt
            node = nxt
        existed = path[-1] in node
        before = node.get(path[-1])
        node[path[-1]] = value
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(raw, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        os.replace(tmp, CONFIG_PATH)
        _CONFIG_CACHE["mtime"] = None      # 下次访问强制重读
        _CONFIG_CACHE["data"] = None
    _audit_append(kind, path, before, existed, value)
    return value


def cfg_unset(path, kind="config"):
    """删掉一个配置键，让代码里的默认值重新生效（撤销"这个键本来是新增的"）。

    -> (before, existed)；键本来就不存在时什么都不写。
    """
    if not isinstance(path, (list, tuple)) or not path:
        raise ValueError("path 不能为空")
    path = [str(k) for k in path]
    with _CONFIG_LOCK:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                raw = json.load(fp)
            if not isinstance(raw, dict):
                raw = {}
        except Exception:
            raw = {}
        node = raw
        for key in path[:-1]:
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                return None, False
            node = nxt
        if path[-1] not in node:
            return None, False
        before = node.pop(path[-1])
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(raw, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        os.replace(tmp, CONFIG_PATH)
        _CONFIG_CACHE["mtime"] = None
        _CONFIG_CACHE["data"] = None
    _audit_append(kind, path, before, True, None)
    return before, True


# ------------------------------------------------------------ 运营参数的审计与撤销
# ★ 为什么需要它：运营参数是"即改即生效"的（`tf_config()` 按 mtime 热读），改错一个数
#   立刻影响线上玩家。所以每次写入都追加一条 `server/data/config_audit.jsonl`，
#   界面上的「最近改动」直接读它，每行一个"撤销"（= 把 before 写回去）。
AUDIT_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "config_audit.jsonl")
AUDIT_KEEP = 300


def _audit_append(kind, path, before, existed, after):
    """追加一条审计记录。**审计写不进去也绝不能让配置改动失败**（只打日志）。"""
    rec = {
        "id": "%d-%04x" % (int(time.time() * 1000), random.getrandbits(16)),
        "at": int(time.time()),
        "at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "path": [str(k) for k in path],
        "before": before,
        "existed": bool(existed),
        "after": after,
    }
    try:
        lines = []
        if os.path.exists(AUDIT_PATH):
            with open(AUDIT_PATH, "r", encoding="utf-8") as fp:
                lines = [ln for ln in fp.read().splitlines() if ln.strip()]
        lines = (lines + [json.dumps(rec, ensure_ascii=False)])[-AUDIT_KEEP:]
        os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
        tmp = AUDIT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write("\n".join(lines) + "\n")
        os.replace(tmp, AUDIT_PATH)
    except Exception as exc:
        print("[cfg] 审计写不进去（忽略）：%r" % (exc,), flush=True)
    return rec


def audit_log(limit=20, kind=None):
    """最近的参数改动，**新的在前**。kind 用来按页筛（"weekly" / "pvp" / "undo"）。"""
    out = []
    try:
        with open(AUDIT_PATH, "r", encoding="utf-8") as fp:
            for ln in fp:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if kind and rec.get("kind") != kind:
                    continue
                out.append(rec)
    except OSError:
        return []
    out.reverse()
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    return out[:max(0, limit)]


def admin_undo(audit_id):
    """按审计记录撤销一次参数改动 -> (结果, 错误)。

    记录里带 `existed`：原来是"新增的键"就把它删掉（让代码默认值重新生效），
    否则把 `before` 写回去。撤销本身也会记一条审计（kind="undo"），所以：
      · 对**同一条**记录再撤一次是幂等的（还是写回同一个 before）；
      · 想来回切就撤销那条 undo 记录（它的 before 就是被撤掉的值）。
    """
    if not audit_id:
        return None, "bad-id"
    rec = None
    for item in audit_log(AUDIT_KEEP):
        if item.get("id") == audit_id:
            rec = item
            break
    if rec is None:
        return None, "not-found"
    path = rec.get("path") or []
    if not path:
        return None, "bad-record"
    try:
        if rec.get("existed"):
            cfg_set(path, rec.get("before"), kind="undo")
        else:
            cfg_unset(path, kind="undo")
    except Exception as exc:
        return None, repr(exc)
    return {"undo_of": audit_id, "path": path, "restored": rec.get("before"),
            "kind": rec.get("kind")}, None


# ★ Windows 控制台默认是 GBK，而二进制上传（幽灵 payload）被解码成含 U+FFFD 的
# 字符串后 print 会抛 UnicodeEncodeError —— 虽然响应已经发出去了，但那条日志会
# 丢掉，控制台还会刷一堆 Traceback。统一把标准流改成 UTF-8 + errors="replace"。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 记录最近 N 条请求，便于 /__log 查看
RECENT = []
RECENT_MAX = 400
LOG_LOCK = threading.Lock()

MAX_BODY_LOG = 8192


def load_rules():
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:  # 规则坏了也要能跑，只是打日志
        print("[rules] 解析失败: %r" % (e,), flush=True)
        return {}


# ------------------------------------------------------------------ 动态端点
# 静态 rules.json 表达不了的响应（要现算）放这里。
# 处理器签名：(path, query, body, headers) -> (status, headers, body_obj)
# body_obj 交给 render() 序列化，所以可以是 dict / str / "@文件"。

# tr::OnlineTimeService::verifyChecksum 的盐（libTrialsGo.so @0x00b8526f）
TS_SALT = "c8f68210a7247676aaee552cb6d81c8a"


def h_timeservice(path, query, body, headers):
    """反作弊时钟源。响应被 tr::OnlineTimeService::parseJsonResponse (cmd 0x67) 解析：
    必须同时满足 ret==1、checksum==md5("<time_now>" + TS_SALT)、且 time_now 与设备时钟接近
    （tr::OnlineCore::checkDeviceDate）。缺 checksum 或对象为空 => onTimeServiceResponse(err=7)
    => AntiCheating::newState(0) => 「警报！」反作弊弹窗。"""
    now = int(time.time())
    digest = hashlib.md5(("%d%s" % (now, TS_SALT)).encode("utf-8")).hexdigest()
    return 200, {}, {"ret": True, "time_now": now, "checksum": digest}


# --------------------------------------------------- gamecfg（启动期配置/游客身份）# 客户端启动序列的第一步（真机日志）：`GET /?product=101&portal=Google&version=7.9.4`
# 与 `GET /?product=101&portal=Google&version=1.5.1`。以前这两条落 rules.json 的
# `*` 兜底、回 `{"data": []}`，服务端等于没实现。
#
# ★ 形状有真实样本（`work/trials-frontier/notes/real-server-samples.md` §1/§2，
#   来源是设备上残留的 Volley 缓存 + logcat，不是猜的）：
#     GET  https://gamecfg-mob.ubi.com/profile/?epoch=1     → 裸 `[]`
#          响应头带 `Ubisoft-CA: OK` / `Ubisoft-Zone: CN` / `Server-Time: <unix>`
#          （该端点 2026-10 仍然在线，实测返回 `[]`，与缓存字节一致）
#     POST https://gamecfg-mob.ubi.com/profile/?action=register_device&productid=101
#          &devicetype=google&deviceuid=<uuid>
#          → {"device":{"federated_id":"<43 字符 base62>","ubimobi_access_token":"<43 字符 base62>"}}
_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _base62(seed, length):
    """确定性地生成 `length` 个 base62 字符。

    ★ 必须**按设备稳定**：客户端会把 federated_id 当自己的游客身份存下来，
      每次随机换一串等于每次开机换个人（和 PVP 状态被劈成两半是同一类毛病）。
    ★ 长度照真实样本给 43：客户端读这两个字段的缓冲区是按真实长度开的。
    """
    out = []
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    while len(out) < length:
        for byte in h:
            out.append(_B62[byte % 62])
            if len(out) >= length:
                break
        h = hashlib.sha256(h).digest()
    return "".join(out)


def h_gamecfg(path, query, body, headers):
    """`GET|POST /` —— gamecfg：Java 侧 DLC 配置 + 游客设备注册。"""
    q = dict(parse_qsl(query or "", keep_blank_values=True))
    hdrs = {
        "Content-Type": "application/json",
        "Ubisoft-CA": "OK",
        "Ubisoft-Zone": "CN",
        "Server-Time": str(int(time.time())),
    }
    if (q.get("action") or "").lower() == "register_device":
        uid = q.get("deviceuid") or q.get("deviceId") or "local"
        return 200, hdrs, {"device": {
            "federated_id": _base62("tf-federated:" + uid, 43),
            "ubimobi_access_token": _base62("tf-token:" + uid, 43),
        }}
    print("[gamecfg] %s?%s -> []" % (path, query), flush=True)
    return 200, hdrs, []          # 真实服务器这里就是一个裸空数组


def h_app_configuration(path, query, body, headers):
    """`GET /v1/applications/<appid>/configuration` —— Ubiservices 应用配置。

    ★ 这里的 `sandboxes[].url` 就是客户端 `setserverAddress(...)` 拿到的**服务器基址**
      （依据：`friendlyName` 必须是 `triag_an_lnch61_a_ws` 或 `android_beta`，否则
      `setserverAddress` 根本不会被调用 —— notes/online-endpoints.md:12）。
      ⚠ 以前这条写在 `server/rules.json` 里、写死 `http://127.0.0.1:8000/`：
        原生侧的地址被 `tf_server.txt` 钩子改成了局域网 IP，**Java 侧（DLC/内购）
        却永远拿着 127.0.0.1** ⇒ 必须开 `adb reverse tcp:8000 tcp:8000` 才能启动，
        否则 Java DLC 一直 `ConnectException: Failed to connect to /127.0.0.1:8000`
        重试，启动链走不到 `pvp_init`，碉堡四个面板永远转圈（2026-10-05 真机定位）。
      ⇒ 现在按请求的 Host 回显：客户端用什么地址找到我们，就让它继续用那个地址。
        真机 Host 就是 `tf_server.txt` 里那一条，所以这条路不再需要 adb reverse。
      ★ 但**回环地址一律不发**（`_public_host`）：一旦客户端被钉在 127.0.0.1，
        Java/DLC 与 Ubi SDK（`libplayground.so` 写死 127.0.0.1）就都得靠 adb reverse
        才能用 —— 用户明确不要"插线才能玩"。
    """
    host = _public_host(headers)
    print("[appcfg] sandbox url -> http://%s/" % host, flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "configuration": {
            "sandboxes": {
                "triag_an_lnch61_a_ws": {
                    "name": "triag_an_lnch61_a_ws",
                    "friendlyName": "triag_an_lnch61_a_ws",
                    "url": "http://%s/" % host,
                }
            },
            "Anticheating_Enabled": False,
            "setOnlineConfigured": True,
        }
    }


# ------------------------------------------------------------ 占位图片
# 商店 / 特供商品里的动态 offer 图，原始地址是
#   https://s3.amazonaws.com/frontieronlinecontent/<name>.png
# 该 bucket 现在返回 NoSuchBucket（素材永久丢失），本地纹理包
# TrialsTexturesDL_android_offericons.dat 里也没有这些动态图，
# 所以这里现画一张占位图发回去，免得页面上出现空白/破图。
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_PLACEHOLDER_PNG = None
_BANNER_PNG = None


def _placeholder_png():
    global _PLACEHOLDER_PNG
    if _PLACEHOLDER_PNG is not None:
        return _PLACEHOLDER_PNG
    import struct
    import zlib
    w = h = 256
    rows = bytearray()
    for y in range(h):
        rows.append(0)                      # 每行的 filter type = 0
        for x in range(w):
            edge = min(x, y, w - 1 - x, h - 1 - y)
            if edge < 6:
                r, g, b = 0xC8, 0xA0, 0x5A  # 金色外框
            elif edge < 9:
                r, g, b = 0x24, 0x16, 0x0E  # 深色内衬
            else:
                fy = y / (h - 1)
                r = int(0x3A + 0x42 * (1 - fy))
                g = int(0x24 + 0x24 * (1 - fy))
                b = int(0x18 + 0x10 * (1 - fy))
                if ((x + y) // 24) % 2 == 0:  # 淡淡的斜纹，避免纯色块
                    r = min(255, r + 8)
                    g = min(255, g + 6)
                    b = min(255, b + 4)
            rows += bytes((r, g, b))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    _PLACEHOLDER_PNG = (b"\x89PNG\r\n\x1a\n"
                        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
                        + chunk(b"IEND", b""))
    return _PLACEHOLDER_PNG


def h_placeholder_image(path, query, body, headers):
    return 200, {"Content-Type": "image/png"}, _placeholder_png()


# ------------------------------------------------------------ 赛季横幅
# 「碉堡 → 赛季横幅」在原本设计里是 `current_season.banner_url` 指向运营素材。
# 取图链路（已反汇编）：
#   `OnlinePVP::parseSeason` @0x4fcfb4 把 `banner_url`@0xb86c60 拷进出参，
#   `OnlinePVP::parseJsonResponse` 的 cmd 0x27 分支发现它非空就调
#   `OnlinePVP::getSeasonBanner` @0x4fabf0 —— 它**把 banner_url 原样**交给
#   `OnlineCore::getRequest(..., cmd=0x32, 0,0,0)`（还置了二进制标志）。
#   响应不走 JSON：`OnlinePVP::onNetworkDataReceived` @0x4fbeac 里 cmd 0x32
#   分支用 `SaveFile` 把**原始字节**落盘成缓存文件，缓存名 =
#   `mt::String::getHashCode(banner_url)`；`PVPManager::loadSeasonBannerTexture`
#   再把它当贴图读进去。
# 所以服务器只要在 banner_url 上回一张 PNG 原图即可，不需要任何 JSON 包装。
_BANNER_PATH = "/pvp_banner/season.png"


def _banner_path():
    """横幅在服务器上的路径（可被 season.banner_path 覆盖）。

    路由按 `/pvp_banner/` 前缀注册，所以改名（仍在这个前缀下）不用改代码。
    """
    return cfg("season", "banner_path", default=None) or _BANNER_PATH


def _req_host(headers):
    """从请求头取 Host —— 它就是客户端的 base URL（设备侧靠 adb reverse）。

    ⚠ 不能用写死的 127.0.0.1：PC 局域网部署时客户端连的是 192.168.x.x，
    banner_url 里若是 127.0.0.1 就会去连手机自己。
    ⚠ 真机上（`http.server`）headers 是 `email.message.Message`，**不是 dict** ——
    只认 dict 的话这里永远取不到 Host，于是 `_public_host` 每次都退回默认端口。
    真机实测：服务器跑在 8123，发出去的地址却是 `http://192.168.x.x:8000/…`。
    """
    if isinstance(headers, dict):
        for k, v in headers.items():
            if k.lower() == "host" and v:
                return v
    else:
        get = getattr(headers, "get", None)
        v = get("Host") if get else None       # Message.get 大小写不敏感
        if v:
            return v
    return "127.0.0.1:8000"


def _lan_ip():
    """本机在局域网里的 IPv4（一次 UDP connect 取对外网卡地址，不发任何包）。"""
    for probe in (lambda: (lambda s: (s.connect(("8.8.8.8", 80)), s.getsockname()[0])[1])(
                      socket.socket(socket.AF_INET, socket.SOCK_DGRAM)),
                  lambda: socket.gethostbyname(socket.gethostname())):
        try:
            ip = probe()
        except OSError:
            continue
        if ip and not ip.startswith("127."):
            return ip
    return "127.0.0.1"          # 探测不出来就给个能看的，别让 URL 变成 "http://:8123"


def _public_host(headers):
    """给 `h_app_configuration` 用的基址 host —— **绝不把回环地址发出去**。

    ★ 为什么必须这么做：`sandboxes[].url` 是 Java/DLC 侧的 base（客户端
      `setserverAddress` 拿它），而 Ubi SDK 所在的 `libplayground.so` 里更是只有
      编译期写死的 `http://127.0.0.1:8000/{version}`（该库没有运行期地址改写）。
      以前这里是"客户端用哪个地址找到我们，就让它继续用哪个" —— 于是**只要有一次**
      请求是从回环进来的（`tf_server.txt` 写着 127.0.0.1，或者开着 `adb reverse`），
      Java/SDK 侧就被钉死在 127.0.0.1，**必须插线**才能玩（2026-10-05 用户报的
      "为啥还要 adb 转发，插线可不行"）。
      现在回环一律换成局域网 IP；想写死就配 `appcfg.public_host`。
    """
    host = _req_host(headers)
    head, _, tail = host.rpartition(":")
    if not head or not tail.isdigit():          # 没带端口（或 IPv6 字面量）就整体当 host
        head, tail = host, "8000"
    if head.strip("[]").lower() not in ("127.0.0.1", "localhost", "::1", "0.0.0.0", ""):
        return host
    override = str(cfg("appcfg", "public_host", default="") or "").strip()
    if override:                                # 可以只写 IP，也可以写 IP:端口
        return override if ":" in override else "%s:%s" % (override, tail)
    return "%s:%s" % (_lan_ip() or "127.0.0.1", tail)


def _banner_url(headers):    # 路径走配置（season.banner_path），方便以后把横幅换成自己的图。
    return "http://%s%s" % (_req_host(headers), _banner_path())


def _placeholder_banner_png():
    """现画一张 640x128 的赛季横幅占位图（手搓 PNG，不依赖 Pillow）。

    ⚠ 必须做小：客户端下载后走 `SaveFile` 落盘，那个路径给的缓冲上限是
    0x800（2048）字节。所以图案**只随 y 变化**（每行是纯色）：这样 Up 滤波后
    一行里除首像素外全 0，同样的行在 deflate 里被彻底折叠，实测 300 字节上下。
    早先版本带 x 方向渐变的斜纹，光靠滤波只能压到 3155 字节，仍然超限。
    """
    global _BANNER_PNG
    if _BANNER_PNG is not None:
        return _BANNER_PNG
    import struct
    import zlib
    w, h = 640, 128

    def row_color(y):
        fy = y / (h - 1)
        if y < 3 or y >= h - 3:             # 上下两条金线
            return 0xE8, 0xC0, 0x6A
        if y < 8 or y >= h - 8:             # 深色内衬
            return 0x2A, 0x18, 0x0C
        # 中段是一条更亮的「标题带」
        band = 0x14 if (0.30 * h <= y < 0.70 * h) else 0x00
        return (min(255, int(0xD2 - 0x54 * fy) + band) & 0xFF,
                min(255, int(0x86 - 0x42 * fy) + band // 2) & 0xFF,
                max(0, int(0x2A - 0x14 * fy)) & 0xFF)

    rows = bytearray()
    prev = bytes(3 * w)                     # 上一行的**原始**像素（Up 滤波器要求）
    for y in range(h):
        # ⚠ PNG filter type = 2（Up）：与上一行相减后行内几乎全 0，deflate 折叠。
        rows.append(2)
        r, g, b = row_color(y)
        row = bytes((r, g, b)) * w
        cur = bytearray()
        for i in range(3 * w):
            cur.append((row[i] - prev[i]) & 0xFF)
        rows += cur
        prev = row

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    _BANNER_PNG = (b"\x89PNG\r\n\x1a\n"
                   + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                   + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
                   + chunk(b"IEND", b""))
    return _BANNER_PNG


def h_pvp_banner(path, query, body, headers):
    """GET /pvp_banner/<名字>.png —— 赛季横幅原图（cmd 0x32 的响应体）。

    想换成自己的图：把 PNG 放进 `server/data/banner/`，再把 `season.banner_path`
    指到 `/pvp_banner/<文件名>`。★ 路径（URL）本身是客户端的缓存键
    （`OnlinePVP::getSeasonBanner` 比对 URL hash），所以换图必须换文件名。
    文件不在就回内置占位图（客户端不会因为 404 报错，但会看到同一张图）。
    """
    name = os.path.basename(path or "")
    if name.endswith(".png") and name not in (".", ".."):
        try:
            with open(os.path.join(os.path.dirname(CONFIG_PATH), "banner", name), "rb") as fh:
                return 200, {"Content-Type": "image/png"}, fh.read()
        except OSError:
            pass
    return 200, {"Content-Type": "image/png"}, _placeholder_banner_png()


# ------------------------------------------------------ 本地账号 / 存档 / 幽灵
# 见 server/tflocal_accounts.py。三个动态端点的角色：
#   POST /v1/profiles/sessions     用户名密码登录（凭据真的会被校验）
#   POST /v3/profiles/sessions     设备静默登录（匿名，沿用固定 profileId）
#   POST /public/playerprogress/v1/progress   客户端上传的完整存档，落盘
try:
    import tflocal_accounts as acct
except ImportError:  # 允许把 tf_server.py 单独拷走
    sys.path.insert(0, HERE)
    import tflocal_accounts as acct

ANON_TICKET = "tf-local-ticket-0001"


def _json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


def h_session(path, query, body, headers):
    """育碧会话端点。用户名密码来自 Authorization: Ubi_v1 t=base64("user:pass")。"""
    info = acct.parse_authorization(headers)
    js = _json_body(body)
    username = info.get("username") or js.get("username") or js.get("email")
    password = info.get("password") or js.get("password")
    remember = bool(js.get("rememberMe"))

    if info.get("kind") == "basic" and username:
        # ROADMAP 第 2 条：登录只查库，**不再自动注册**。
        # 账号必须先在 http://<服务器>:8000/__register 上注册。
        acc, err = acct.login_account(username, password)
        if acc is None:
            print("[acct] 会话请求被拒：%s（%s）" % (username, err), flush=True)
            return 401, {"Content-Type": "application/json"}, {
                "error": err or "invalid-credentials",
                "errorCode": "NOT_REGISTERED" if err == "not-found" else "INVALID_CREDENTIALS",
                "message": ("此账号尚未在本地服务器注册，请先打开 "
                            "http://<服务器IP>:8000/__register 注册" if err == "not-found"
                            else "用户名或密码不正确"),
            }
        ticket = acct.issue_session(acc)
        # ★ 登录固化：把长期凭据一并发下去，客户端会存进安全存储，
        #   下次启动就能静默换会话，不必再让玩家手输账号（见 tflocal_accounts
        #   里 issue_remember_ticket 的反汇编依据）。
        rm = acct.issue_remember_ticket(acc)
        # 记住「这台客户端 = 这个账号」：客户端随后的请求里有一半不带 Authorization
        # 或只用我们发的匿名票，靠这条绑定才能落回同一个槽（见 resolve_identity）。
        acct.bind_client(acc, _client_ip(headers), info.get("device_id"))
        return 200, {"Content-Type": "application/json"}, \
            acct.session_body(acc, ticket, remember, remember_ticket=rm)

    # ★ 这台客户端绑定过谁？（见 tflocal_accounts 的绑定注释）
    #   凡是「认不出是谁」的兜底路径（设备票 / 设备静默 / 匿名）都先问它。
    #   2026-10-05 真机实测：冷启动第一条会话是 `rm_v1 t=tf-rm-…`（长期凭据），
    #   走的是下面的 bearer 分支 —— 那里以前**没有**建绑定，紧接着的设备请求就
    #   照样拿到了设备槽，等于白修。所以三条路径都要过这里。
    def _bound_reply():
        bound = acct.account_by_client(_client_ip(headers), info.get("device_id"))
        if bound is None:
            return None
        rm = acct.issue_remember_ticket(bound)
        return 200, {"Content-Type": "application/json"}, \
            acct.session_body(bound, acct.issue_session(bound), remember, remember_ticket=rm)

    # ★ 登录固化的静默换会话：客户端拿我们发过的长期凭据（rememberMeTicket）
    #   或普通会话票来换新会话，不该再退化成匿名槽。
    #   依据：Playground::Credentials::Convert() @0x1903c4 的 type=7 分支
    #   会把 rememberMeTicket 当票据重新走一次会话建立。
    # 登录固化：票据既可能出现在 Authorization 头，也可能被放在请求体里，
    # 两条路径都要认（SDK 的 PlayerCredentials 走头，但保不齐换个版本走体）。
    body_tok = js.get("rememberMeTicket") or js.get("ticket")
    if info.get("kind") == "bearer" or (body_tok and not username):
        tok = info.get("ticket") or body_tok
        acc = acct.account_by_remember_ticket(tok) or acct.account_by_ticket(tok)
        if acc is not None:
            rm = acct.issue_remember_ticket(acc)
            acct.bind_client(acc, _client_ip(headers), info.get("device_id"))
            return 200, {"Content-Type": "application/json"}, \
                acct.session_body(acc, acct.issue_session(acc), True, remember_ticket=rm)
        dev = acct.device_by_ticket(tok)
        if dev is not None:
            reply = _bound_reply()
            if reply is not None:
                return reply
            return 200, {"Content-Type": "application/json"}, \
                acct.session_body(dev, dev["ticket"], remember)

    # 设备静默登录：按设备 id 分配独立的 profileId，
    # 这样不登录的多台设备不会挤在同一个槽里互相覆盖存档。
    # ⚠ 但这台客户端**登录过账号**时必须优先回账号：真机日志里空 body 的会话请求
    #   会拿到设备槽 224c7c78-…，客户端随后就拿它去发 PVP/存档请求，于是状态被
    #   劈成两半 —— 用户看到的「时好时坏」。
    reply = _bound_reply()
    if reply is not None:
        return reply

    if info.get("kind") == "device":
        dev = acct.ensure_device(info.get("device_id"))
        if dev is not None:
            return 200, {"Content-Type": "application/json"}, \
                acct.session_body(dev, dev["ticket"], remember)

    # 既没有凭据也没有设备 id：保持旧的匿名槽（兼容已存在的老存档）
    acc = acct.account_by_ticket(ANON_TICKET)
    return 200, {"Content-Type": "application/json"}, acct.session_body(acc, ANON_TICKET, remember)


def h_progress(path, query, body, headers):
    """客户端把完整存档 POST 上来。归属严格按凭据走，凭据不对回 401。

    ★ 响应形状不是随便写的：`OnlinePlayerProgress::parseResponse` @0x57433c 的
      **cmd 0x21**（syncProgress @0x573798 那条 POST）分支只读两个 int 键 ——
      `version`@0xb4056d 和 `time_stamp`@0xb89a9c，读到后 `DebugOut::add(
      "SYNCED TO VERSION %d")` 并写进 `Player+0x4864`（客户端记的"本地版本"）。
      以前回 `{"data": []}` ⇒ 本地版本恒为 0 ⇒ 客户端每次都认为"和服务器一致"，
      于是把自己的存档推上来（这才是覆盖服务器存档的元凶）。
    """
    pid, brief, err = acct.save_progress(headers, body, _client_ip(headers))
    if err:
        print("[save] 拒绝越权/无效凭据的存档上报：%s" % err, flush=True)
        return 401, {"Content-Type": "application/json"}, {"error": err}
    if pid:
        brief["ok"] = True
        # ★ 排行榜的数据源：存档里的 highscores2 是**玩家自己的最佳成绩表**，
        #   真正跑过的图 drivetime > 0，没跑过的是 `[track, 0, 256, 0, 0]`。
        #   直接从存档同步，榜单就和玩家的实际进度永远一致，
        #   也不会出现"客户端只提交了一部分成绩"导致榜单缺图的情况。
        n = _ingest_highscores(pid, _json_body(body))
        if n:
            print("[rank-save] profile=%s 从存档同步了 %d 条赛道成绩" % (pid, n), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "version": int(brief.get("server_version") or 0),
        "time_stamp": int(brief.get("saved_at") or 0),
    }


def h_progress_version(path, query, body, headers):
    """GET /public/playerprogress/v1/progress/version —— 版本比对（cmd 0x22）。

    响应必须是 `{"version": N, "time_stamp": T}`（见 acct.progress_version 的说明）。
    N == 客户端本地版本（或 0）时客户端会把本地存档推上来；
    N 不同且非 0 时游戏会拉起自己的"进度同步"界面，让玩家选择用云端还是用本地。
    真机清档事故后，这里改成回**真实服务器版本**，玩家才有恢复入口。
    """
    pid, ver, ts, note = acct.progress_version(headers, _client_ip(headers))
    print("[save] 版本比对：pid=%s note=%s -> version=%d time_stamp=%d"
          % (pid, note, ver, ts), flush=True)
    return 200, {"Content-Type": "application/json"}, {"version": ver, "time_stamp": ts}


# 玩家等级（客户端的 "xp"）的唯一来源：它会自己上报，而不是我们存下来的。
# 客户端每次启动都发 POST /public/targeting/v1/configuration，body 里带
# {"xp": N, "player_name": ...}，实测随游玩递增：ccb@ccb.com 0→8→11→12→13→14、
# HuaweiLover=3、LocalPlayer=8。★ 别再去存档里找了 —— items2 / profile /
# settings / statistics2 / dailyexperience 全部翻过，没有这个数（见 b24）。
# ★ 必须落盘。我原先判断"客户端每次启动都会重报，内存够了"是错的：用户每轮
#   改完代码都会重启服务器，而他不会为了这个重开游戏 —— 于是云端摘要在
#   「重启后、客户端下次上报前」这段空窗期里回 0，界面上又变成「等级 1」，
#   正是他报的那个"很危险"的现象（m01175）。一个几十字节的文件换掉这类误判，值。
_PLAYER_XP_PATH = os.path.join(HERE, "data", "player_levels.json")


def _player_xp_load():
    """读不出来就当他没有 —— 这只是个显示用的数字，绝不因为坏文件让服务器起不来。"""
    try:
        with open(_PLAYER_XP_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    return {str(k): int(v) for k, v in obj.items()
            if isinstance(v, int) or (isinstance(v, str) and v.lstrip("-").isdigit())}


def _player_xp_save():
    try:
        os.makedirs(os.path.dirname(_PLAYER_XP_PATH), exist_ok=True)
        tmp = _PLAYER_XP_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_player_xp, f)
        os.replace(tmp, _PLAYER_XP_PATH)
    except Exception:
        pass


_player_xp = _player_xp_load()


def _remember_player_xp(headers, body):
    """从 targeting 上报里记下玩家等级。

    解析不出来就静默放过 —— 这只是个给「云端进度摘要」显示用的数字，不值得
    为它把请求打回去。见 `_player_xp` 的注释。
    """
    try:
        xp = int(json.loads(body.decode("utf-8")).get("xp"))
    except Exception:
        return
    if xp < 0:
        return
    try:
        pid = acct.serve_progress(headers, _client_ip(headers))[0]
    except Exception:
        return
    # 同一次会话里客户端会把同一个数报很多遍，只有真变了才写盘。
    if pid and _player_xp.get(pid) != xp:
        _player_xp[pid] = xp
        _player_xp_save()


def h_progress_status(path, query, body, headers):
    """GET /public/playerprogress/v1/progress/status —— 云端进度摘要（cmd 0x25）。

    `OnlinePlayerProgress::parseStatus` @0x00574d7c 按成员名取 5 个 int：
      coins@0 / diamonds@4 / missions_completed@8 / player_level@0xc / player_points@0x18。
    返回值是 `[status+8] != 0`（即 missions_completed 非 0 才算"有效"），
    `parseResponse` 里 `tbz w0,#0` 为 0 时走 error 分支。金币/宝石从 items2 里取
    （实测 items2 的 id 1 = 金币、id 2 = 宝石）。
    """
    pid, content, note = acct.serve_progress(headers, _client_ip(headers))
    coins = gems = 0
    items = (content or {}).get("items2") or []
    for i in range(0, len(items) - 1, 2):
        if items[i] == 1:
            coins = int(items[i + 1] or 0)
        elif items[i] == 2:
            gems = int(items[i + 1] or 0)
    missions = len(((content or {}).get("missions2") or {}).get("solved") or [])
    # ★ 这里以前写死 0，于是**每个**账号的「云端存档摘要」都显示最低等级 ——
    # 玩家看到"云端的等级变成 1 了"会以为存档被清空，转头去点「用本地」，
    # 正好把服务端的下发取消掉。玩家等级用客户端自己上报的那个数（见 _player_xp）。
    level = _player_xp.get(pid, 0)
    print("[save] 云端摘要：pid=%s note=%s coins=%d gems=%d missions=%d level=%d"
          % (pid, note, coins, gems, missions, level), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "coins": coins,
        "diamonds": gems,
        "missions_completed": missions,
        "player_level": level,
        "player_points": 0,
    }


def h_progress_latest(path, query, body, headers):
    """GET /public/playerprogress/v1/progress —— **下发给客户端的存档**。

    ★★ 这是真机清档事故的那个端点，必须看成"会把玩家本地存档覆盖成我返回的东西"：
       tr::OnlinePlayerProgress::parseResponse @0x57433c（cmd 0x24）解析完 JSON 之后
       会无条件调用 tr::Player::save() @0x362bc0。所以：
         · 有存档 -> 原样回客户端当初 POST 上来的那份 content（键名天然一致）；
         · 一份都没有 -> 回 **404**（让客户端走 onNetworkError @0x574198），
           **绝对不能回 {} / {"data": []}**，那等于把玩家进度清零。
       响应键就是 parseProgress @0x574780 认识的那套（客户端上传用的同一套）：
       version / game_version / items(2) / missions(2) / statistics(2) / achievements(2) /
       tutorials(2) / timers(2) / highscores(2) / upgrades / store_bonus /
       dailyexperience / robotman / profile / settings / identifier。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    pid, content, note = acct.serve_progress(headers, _client_ip(headers))
    if not content:
        print("[save] 下发请求但没有可用存档（%s）-> 404，避免客户端清档" % note, flush=True)
        return 404, {"Content-Type": "application/json"}, {"error": "no saved progress"}
    keys = [k for k in ("version", "game_version", "identifier") if k in content]
    print("[save] 下发存档 pid=%s note=%s 顶层键=%d %s"
          % (pid, note, len(content), ",".join(keys)), flush=True)
    if q.get("download") not in ("1", "true", "yes"):
        # 不带 download 参数也照发：客户端只在这一条路径上取存档，
        # 早期"默认回空"的做法正是清档的元凶。
        pass
    return 200, {"Content-Type": "application/json"}, content


def h_progress_swap(path, query, body, headers):
    """POST /public/playerprogress/v1/swap —— 账号切换时"换进度所有者"。

    tr::OnlinePlayerProgress::switchProgressOwner @0x5740b0 发这个请求（cmd 0x26），
    响应由 parseResponse @0x57433c 里 0x57459c 那段处理：找成员名 `identifier`
    (@0xba7808)，它的字符串值必须 **长度 ≥ 6**，然后 strcpy 进 Player+0x6be0、
    以 error=0 回调 onProgressSwap、再 Player::save()。

    所以只要回 {"identifier": "<≥6 字符>"} 就是成功。这里顺便先跑一次收养，
    保证换 owner 之后立刻能拿到（或继承到）存档。
    """
    pid, content, note = acct.serve_progress(headers, _client_ip(headers))
    ident = (content or {}).get("identifier") or pid or ""
    if len(str(ident)) < 6:
        ident = pid or acct.ANON_PROFILE_ID
    print("[swap] 进度换 owner：owner=%s note=%s -> identifier=%s"
          % (pid, note, ident), flush=True)
    return 200, {"Content-Type": "application/json"}, {"identifier": ident}


def _client_ip(headers):
    """从请求头里掏客户端 IP（tf_server 会把真实来源塞进 X-TF-Client）。"""
    return (headers or {}).get("X-TF-Client") or None


def _caller_profile(headers):
    info, err = acct.resolve_identity(headers)
    if info:
        return info["profileId"]
    return acct.ANON_PROFILE_ID


def h_profile_me(path, query, body, headers):
    info, _ = acct.authenticate(headers)
    acc = None
    if info and info["kind"] == "account":
        acc = acct.lookup_account(info["who"])
    elif info and info["kind"] == "device":
        acc = acct.device_by_profile(info["profileId"])
    return 200, {"Content-Type": "application/json"}, acct.profile_body(acc)


def h_profiles_query(path, query, body, headers):
    """OnlineFriends::resolveOnlineIds 走 %s/v1/profiles?profileId=…（.rodata @0xb89064）。"""
    me = h_profile_me(path, query, body, headers)[2]
    wanted = []
    for k, v in parse_qsl(query, keep_blank_values=True):
        if k.lower() == "profileid":
            wanted += [x for x in v.split(",") if x]
    out = [me]
    seen = {me["profileId"]}
    for pid in wanted:
        if pid in seen:
            continue
        seen.add(pid)
        out.append({
            "profileId": pid, "userId": pid, "platformType": "ubimobile",
            "idOnPlatform": pid,
            # 真人名字**必须**排在兜底池前面：否则别人在榜上看到的是
            # 「Player53eb」这种由 pid 拼出来的假名，而不是 ccb@ccb.com（真机 m01172）。
            "nameOnPlatform": (acct.name_for_profile(pid)
                               or FRIEND_NAMES.get(pid) or _WEEKLY_FAKE_NAMES.get(pid)
                               or "Player" + pid[:4]),
        })
    return 200, {"Content-Type": "application/json"}, {"profiles": out}


FRIEND_NAMES = {
    "44444444-4444-4444-4444-444444444444": "GhostRider",
    "55555555-5555-5555-5555-555555555555": "TangoPro",
    "66666666-6666-6666-6666-666666666666": "IronGear",
}


# -------------------------------------------------------------- 幽灵 / 内购
# 幽灵文件格式（实测解出，见 server/data/ghosts/README.md）：
#   0x00 u32 version=3 ; 0x04 u32 tag ; 0x08 u32 解压后长度 ; 0x0c u32 0
#   0x10 ... zlib 流；解压后 0x00 u32=1, 0x04 u32=该次跑的时间(ms),
#   0x08 u32=帧数, 0x0c u32=0, 0x10 起是帧数据。
# 客户端侧 tr::OnlineGhostManagerListener::onGhostReceived(TR_ONLINE_ERROR,int,void*,int,int)
# 说明幽灵是以「原始字节 + 长度」回调的，所以这里直接把 .bin 原样发回去。
_GHOST_HINT = ("ghost", "replaydata")

# 幽灵协议（反汇编 tmp/libcmp/orig-libTrialsGo.so 得到，见 notes）：
#   tr::OnlineUserStorage 的资源名恒为 "ghost"，URL 模板 @0xb8c6d4 / 0xb8c6f4 /
#   0xb8c71f / 0xb8c741：
#     %s/%s/userstorage/v2/content/%s                建容器（POST，需回 contentId）
#     %s/%s/userstorage/v2/content/%s/%d/payload     取/传二进制
#     %s/%s/userstorage/v2/content/%s/%d             取/改/删 metadata
#     %s/%s/userstorage/v2/search/%s/%s              按 tag 检索
#   tag @0xb87a8e / 0xb87ab7 / 0xb87af4：
#     get_ghost?track_id=%d&players=%s&limit=1
#     get_ghost_timed?track_id=%d&players=%s&drive_time=%d&limit=1
#     get_pvp_ghost?track_id=%d&players=%s&limit=1&pvpid=%d
#   建容器的响应由 parseJsonResponse @0x578a08 解析，只认**顶层整型键 contentId**
#   （@0xb87d21）；检索的响应由 GhostQueryObject::onQueryCompleted @0x508288 解析，
#   要的是 {"contents":[{"contentId":<int>,"metadata":{...}}]}（contents @0xb87d18，
#   metadata 必须是**对象**，字符串会让它按成员链表去读而崩）。
_USERSTORAGE_RE = re.compile(r"^/public/userstorage/v2/(content|search)/ghost(?:/(.*))?$")


def _looks_like_ghost(path):
    p = path.lower()
    return any(h in p for h in _GHOST_HINT)


def _ghost_caller(headers):
    """取调用者的 profileId（认不出就返回 None，不影响功能）。

    ⚠ 走 `acct.resolve_identity`：客户端在一次冷启动里会混用「带账号票 / 不带
    Authorization / 我们发的匿名票」三种身份（2026-10-05 真机日志：7360 条请求里
    1737 条无 Authorization、1489 条用匿名票），直接 `authenticate` 会把一半请求
    判成匿名槽，PVP 状态被劈成两半（「时好时坏」）。绑定逻辑见 tflocal_accounts。
    """
    try:
        info, _err = acct.resolve_identity(headers)
    except Exception:
        info = None
    if isinstance(info, dict):
        pid = info.get("profileId")
        # 顺手记「这台服务器上最近还有谁在活动」——匹配逻辑靠它判断
        # 「有没有别的真人」。放这里最省事：所有带认证的请求都会经过。
        if pid:
            ACTIVE_PLAYERS[pid] = int(time.time())
        return pid
    return None


def _ghost_metadata(body):
    """客户端发的 body 是 {"metadata": {...}}；兼容直接给 metadata 的情况。

    ⚠ 处理器拿到的 body 是**原始字节**（`_handle` 只读流、不做解析），
    所以这里必须先自己 JSON 解析——踩过这个坑：不解析会静默拿到空元数据，
    赛道号丢失，幽灵就永远检索不到。
    """
    if isinstance(body, (bytes, bytearray)):
        body = _json_body(body)
    if isinstance(body, dict):
        md = body.get("metadata")
        if isinstance(md, dict):
            return md
    return {}


def _ghost_meta_out(rec, drive_time=None):
    """把幽灵记录拼成客户端要的 `metadata` 对象。

    ★ `size` **必须有且 >= 1**：`tr::GhostQueryObject::onQueryCompleted` @0x508288
      的 type 3 分支 `0x5083b8 str w8,[sp,#0x14]` 读键 `size`@0xb4317f，
      `size < 1` 直接判失败。内置幽灵以前只有 metadata、从来没写过 size，
      所以排行榜上点「挑战」永远取不到幽灵。
    ★ `drive_time` 必须与请求方期望的一致：紧接着 `0x508594` 会比对，
      不等就打 `GHOST DRIVE TIME DOES NOT MATCH: %d vs %d`@0xb87d5b 并失败。
      `get_ghost_timed?…&drive_time=N` / `checkGhost(…, drive_time, …)` 传的
      就是排行榜那一行显示的成绩，所以直接把请求值回显即可。
    """
    md = dict(rec.get("metadata") or {})
    if md.get("track_id") is None:
        md["track_id"] = rec.get("track_id")
    if not md.get("size"):
        n = rec.get("size") or 0
        if not n:
            blob = acct.ghost_payload(rec.get("contentId"))
            n = len(blob) if blob else 0
        md["size"] = int(n or 0)
    if md.get("pvpid") is None and rec.get("pvpid") is not None:
        md["pvpid"] = rec.get("pvpid")
    if drive_time:
        md["drive_time"] = int(drive_time)
    return md


def h_userstorage(method, path, query, body, headers):
    """userstorage v2 的幽灵内容仓库（客户端上传/检索自己的幽灵走这条）。"""
    m = _USERSTORAGE_RE.match(path)
    if not m:
        return 200, {"Content-Type": "application/json"}, {"data": []}
    kind, rest = m.group(1), (m.group(2) or "").strip("/")
    q = dict(parse_qsl(query, keep_blank_values=True))
    owner = _ghost_caller(headers)

    if kind == "content":
        parts = [p for p in rest.split("/") if p] if rest else []
        cid = None
        if parts and parts[0].lstrip("-").isdigit():
            cid = int(parts[0])
            tail = parts[1] if len(parts) > 1 else ""
        else:
            tail = ""

        # POST /content/ghost —— 建容器，必须回真实 contentId
        if method == "POST" and cid is None:
            md = _ghost_metadata(body)
            track = md.get("track_id")
            try:
                track = int(track) if track is not None else None
            except Exception:
                track = None
            new_id = acct.ghost_create(track, owner, md)
            print("[ghost] create 赛道 %s -> contentId=%d owner=%s"
                  % (track, new_id, owner), flush=True)
            return 200, {"Content-Type": "application/json"}, {"contentId": new_id}

        if cid is None:
            return 200, {"Content-Type": "application/json"}, {"data": []}

        # PUT /content/ghost/<id>/payload —— 传二进制
        if tail == "payload" and method == "PUT":
            raw = body if isinstance(body, (bytes, bytearray)) else b""
            rec = acct.ghost_put_payload(cid, bytes(raw))
            if rec is None:
                print("[ghost] payload id=%d 不存在，仍然接收（%d 字节）" % (cid, len(raw)),
                      flush=True)
                return 200, {"Content-Type": "application/json"}, {"contentId": cid}
            print("[ghost] payload id=%d 赛道 %s %d 字节 drive_time=%s frames=%s"
                  % (cid, rec.get("track_id"), len(raw), rec.get("drive_time"),
                     rec.get("frames")), flush=True)
            return 200, {"Content-Type": "application/json"}, {"contentId": cid}

        # GET /content/ghost/<id>/payload —— 回二进制
        if tail == "payload":
            blob = acct.ghost_payload(cid)
            if blob:
                print("[ghost] 下发幽灵 id=%d (%d 字节)" % (cid, len(blob)), flush=True)
                return 200, {"Content-Type": "application/octet-stream"}, blob
            # ★ 千万不要回 JSON 兜底：cmd 29（`OnlineUserStorage::onNetworkDataReceived`
            #   @0x5789e0 → vptr[3] = `GhostQueryObject::onDataReceived` @0x507fb8）
            #   **没有任何长度/魔数校验**，12 字节的 `{"data": []}` 会被当成幽灵数据
            #   直接喂给引擎。留空体比喂垃圾安全。
            print("[ghost] payload id=%d 不存在 -> 404" % cid, flush=True)
            return 404, {"Content-Type": "application/octet-stream"}, b""

        # PUT /content/ghost/<id> —— 更新 metadata（body 里没有 track_id，靠合并）
        if method == "PUT" and not tail:
            md = _ghost_metadata(body)
            rec = acct.ghost_update(cid, md, owner)
            if rec is None:
                new_id = acct.ghost_create(None, owner, md)
                print("[ghost] update id=%d 不存在，补建 contentId=%d" % (cid, new_id),
                      flush=True)
                return 200, {"Content-Type": "application/json"}, {"contentId": new_id}
            print("[ghost] 更新 metadata id=%d 赛道 %s drive_time=%s"
                  % (cid, rec.get("track_id"), rec.get("drive_time")), flush=True)
            return 200, {"Content-Type": "application/json"}, {"contentId": cid}

        if method == "DELETE" and not tail:
            acct.ghost_delete(cid)
            return 200, {"Content-Type": "application/json"}, {"data": []}

        # GET /content/ghost/<id> —— 取 metadata
        rec = acct.ghost_get(cid)
        if rec:
            # 形状（`GhostQueryObject::onMetaDataReceived` @0x50802c，**扁平**对象）：
            #   顶层 `"profileId"`@0xb8546e 字符串 + 顶层 `"metadata"`@0xb85860 对象，
            #   后者子键 `track_id`@0xb87757 / `pvpid`@0xb87ce5 / `size`@0xb4317f。
            #   消费方 `OnlineStateGhost::onGhostMetaDataReceived` @0x7c8f58 把 track_id
            #   存进 [this+0x184] 并拿它做下一跳 getGhost(…, track=track_id, …)@0x7c8fa4。
            return 200, {"Content-Type": "application/json"}, {
                "contentId": cid,
                "profileId": rec.get("owner") or "",
                "metadata": _ghost_meta_out(rec),
            }
        return 200, {"Content-Type": "application/json"}, {"data": []}

    # search/<tag>?...
    tag = rest or ""
    def _num(name, default=None):
        try:
            return int(q.get(name))
        except Exception:
            return default

    track = _num("track_id")
    limit = _num("limit", 1)
    drive_time = _num("drive_time")
    # ★ PVP 专用对手位：`get_pvp_ghost?track_id=%d&players=%s&limit=1&pvpid=%d`@0xb87af4。
    #   以前完全不读它 ⇒ pvpid=1 和 pvpid=2 拿到同一批幽灵。
    pvpid = _num("pvpid")
    if pvpid is None:
        pvpid = _num("pvp_id")
    # ★ 但 `players` 在 PVP 查询里是**请求者自己**的 pid（真机实测），
    #   拿去当 owner 过滤等于把 named 变成永远空集、静默回落到全部。
    #   只有 `get_ghost[_timed]` 这两个按名检索的变体才该用 players 过滤 owner。
    named_query = "pvp" not in tag
    rows = acct.ghost_search(track_id=track,
                             players=(q.get("players") if named_query else None),
                             limit=limit, drive_time=drive_time, pvpid=pvpid)
    print("[ghost] search %s 赛道 %s players=%s pvpid=%s -> %d 个"
          % (tag, track, q.get("players"), pvpid, len(rows)), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "contents": [{"contentId": r.get("contentId"),
                      "metadata": _ghost_meta_out(r, drive_time)} for r in rows]
    }


def h_ghost(path, query, body, headers):
    """resultservice 下的幽灵端点：这些回的是**原始幽灵字节**。

    实测调用顺序（玩家跑完一条赛道）：
      POST .../enhancestats/track<ID>            成绩落库
      GET  .../replaydata?track_id=<ID>          问「服务器上有没有我这条赛道的回放」
      （随后客户端才走 userstorage 上传幽灵，见 h_userstorage）
    所以 replaydata 的 query 形式**故意继续回 {"data": []}**：这是在问
    「有没有」，回「没有」客户端才会老老实实把新幽灵传上来。真正的下载走
    userstorage 的 search/content，以及 replaydata 的路径形式。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    seg = path.rstrip("/").split("/")[-1]
    track = q.get("track_id") or (seg if seg.isdigit() else "")
    tracking = int(track) if str(track).isdigit() else None

    # ★ 客户端会在赛道 ID 上叠高位标志位，幽灵库里存的却是裸 ID：
    #     | 0x800000 (8388608)  PVP 对手幽灵 —— OnlinePVP::parseJsonResponse cmd 0x2c
    #                          分支 `orr w2,w8,#0x800000` → getPVPGhost() →
    #                          resultservice/v1/pvp_replaydata?track_id=8389649&player=…&pvp_id=…
    #     | 0x10000  (65536)    排行榜（周赛）变体，如 track66633 = 65536 + 1097
    #     | 0x100000 (1048576)  排行榜（另一套）变体，如 track1049609 = 1048576 + 1033
    #   不掩掉就永远精确匹配不上（ghost_search 用的是 `rec["track_id"] != track_id`），
    #   于是 PVP 局里下不到对手幽灵、排行榜也拿不到幽灵。
    #   赛道真实 ID 目前最大 1438，掩到 0xFFFF 足够安全。
    if tracking:
        tracking &= 0xFFFF

    if "/replaydata" in path and not seg.isdigit() and q.get("track_id"):
        # ★ 客户端 cmd 13（`tr::GhostQueryObject::onNetworkDataReceived` @0x5088a8）
        #   读的是 **snake_case** 的 `"content_id"`@0xb87d85：
        #     >= 1 → `OnlineUserStorage::sendData`（PUT payload 到那个 id = 更新已有）
        #     < 1  → `createMetaData` + `OnlineUserStorage::addData`（POST 新建）
        #   以前这里永远回 `{"data": []}`（本意是「问有没有，说没有才会老实上传」），
        #   结果每跑一场就 +1 条新记录：真机 23/23 次全空，index.json 里同一玩家
        #   攒了 20 条（cid 47–66）。答「有」才能收敛到一条、客户端才学得到自己的 id。
        mine = None
        pid = _ghost_caller(headers)
        if pid and tracking:
            rows = acct.ghost_search(track_id=tracking, owner=pid, limit=1)
            if rows:
                mine = rows[0].get("contentId")
        if mine:
            print("[ghost] replaydata 赛道 %s 已有本人幽灵 cid=%s，让客户端更新"
                  % (tracking, mine), flush=True)
            return 200, {"Content-Type": "application/json"}, {"content_id": int(mine)}
        return 200, {"Content-Type": "application/json"}, {"data": []}

    if tracking:
        # ★ 二进制幽灵端点发的是 **`player`（单数）**，只有 userstorage 的 search
        #   家族才用 `players`。真机实测：
        #     /resultservice/v1/pvp_replaydata    {track_id, player, pvp_id}  13 次
        #     /resultservice/v1/robot_replaydata  {track_id, time, player}    35 次
        #   以前只读 players ⇒ 对手 pid / 对手名 / time / pvp_id 全被丢掉，
        #   永远落到下面「该赛道随便挑一条」的兜底。
        who = q.get("players") or q.get("player") or ""
        players = [p.strip() for p in str(who).split(",") if p.strip()]
        if players:
            # 排行榜上的对手行点「挑战」时客户端会把那一行的 player 带过来。
            # 先按 pid→contentId 精确回**同一条**幽灵，榜上显示的时间才跑得对。
            _, ghost_of = _opponent_entries()
            board = "track%d" % tracking
            for pid in players:
                cid = (ghost_of.get(pid) or {}).get(board)
                blob = acct.ghost_payload(cid) if cid else None
                if blob:
                    print("[ghost] %s 赛道 %s -> 对手 %s 的幽灵 cid=%s (%d 字节)"
                          % (path, tracking, pid, cid, len(blob)), flush=True)
                    return 200, {"Content-Type": "application/octet-stream"}, blob
        pvpid = q.get("pvpid") if q.get("pvpid") is not None else q.get("pvp_id")
        want = q.get("time") if q.get("time") is not None else q.get("drive_time")
        try:
            pvpid = int(pvpid) if pvpid is not None else None
        except (TypeError, ValueError):
            pvpid = None
        try:
            want = int(want) if want is not None else None
        except (TypeError, ValueError):
            want = None
        rows = acct.ghost_search(track_id=tracking, limit=1,
                                 drive_time=want, pvpid=pvpid)
        rec = rows[0] if rows else None
        if rec is None:
            # ★ 该赛道一条都没有时**必须**跨赛道兜底，不能回 12 字节的
            #   `{"data": []}`：cmd 15/16/18 的分支（都在 0x508854）带
            #   `cmp w8,#0x65; b.lo 0x5089fc` —— 响应体小于 101 字节就判 err=7，
            #   于是「检索对手中…」永远卡住、幽灵缺失。幽灵 blob 里不含赛道号，
            #   跨赛道下发在结构上客户端发现不了。
            rec = acct.ghost_any()
        if rec:
            blob = acct.ghost_payload(rec.get("contentId"))
            if blob:
                print("[ghost] %s 赛道 %s -> contentId=%s (%d 字节)"
                      % (path, tracking, rec.get("contentId"), len(blob)), flush=True)
                return 200, {"Content-Type": "application/octet-stream"}, blob
        print("[ghost] %s 赛道 %s 库里一条可用幽灵都没有" % (path, tracking), flush=True)
        return 404, {"Content-Type": "application/octet-stream"}, b""
    return 200, {"Content-Type": "application/json"}, {"data": []}


# ---------------------------------------------------------------------------
# A.N.B.A（Robotman）支线的假机器人对手
# ---------------------------------------------------------------------------
# 客户端链路（`tmp/libcmp/orig-libTrialsGo.so` 逐指令反汇编确认）：
#   tr::OnlineRobotMission::findOpponent(track, range, flag)          @0x501fcc
#     -> tr::MatchMaking::getRobot(listener, track, range, offset)    @0x4f8fdc
#        URL @0xb86327 = "%s/%s/match/v1/robot?track_name=track%d&range=%d&offset=%d"
#        cmd = 0x47
#     -> tr::MatchMaking::parseJsonResponse(cmd=0x47) 分支：
#        parseMatchMakingResult()，把 result[0] 置 3，err 恒 0
#     -> tr::OnlineRobotMission::onMatchMakingComplete(err, res)      @0x5021fc
#          res[0] 必须 == 3
#          strcpy(this+0xad, res+0x85)   <- 对手显示名
#          this+0xec = res+0xc8          <- drivetime
#        -> tr::OnlineGhostManager::getRobotGhost(this+8, track, name, drivetime)
#           URL @0xb87a48 = ".../resultservice/v1/robot_replaydata?track_id=%d&time=%d&player=%s"
#        -> onGhostReceived(...) 落盘 robot_ghost-<hash(name)>-<track>.robot
#        -> OnlineUbiservices::getPlayerProfile(this+0x10, name)      @0x517448
#           URL @0xb89137 = "<ubi>/v1/profiles/%s"
#        -> onProfilesQueryCompleted: strcpy(this+0x2c, ProfileQueryData+0x48)
#           （ProfileQueryData+0x48 == profile+0x40 == nameOnPlatform）
#        -> OnlineFacebookClient::getUserPicture(name, 73, 73)        @0x50ef8c
#           URL @0xb887cc = "<graph.facebook.com>/%s/picture?width=%d&height=%d"
#           失败回退 OnlineUbiservices::getUserPicture(name, 0)       @0x517c10
#           URL @0xb89267 = "<akamaized>/%s/default_146_146.png"
#        -> tr::OnlineRobotMission::onPictureReceived                 @0x5027f4
#           ★ if (err != 0) return;  —— 不清 [+0x120]、不回 state 2，界面永远停在
#              「检索对手中」。所以 graph.facebook.com / ubisoft-avatars.akamaized.net
#              这两个域名必须由打补丁时重写到本地服务器（见 dist/patcher/patch_dynaddr.py
#              的 HOST_EXACT）。
#
# 响应形状：tr::MatchMaking::parseMatchMakingResult @0x4f94a8 **只认根对象的扁平
# 成员键**，而且**不做任何 JSON 类型检查**（值一律按 32 位字从 [node+0x28] 读：
# 字符串就是指针，数字就是整数）：
#   "player"      -> strcpy(res+0x85)                            对手名，必须非空
#   "drivetime"   -> *(int*)(res+0xc8)                           幽灵请求里的 time=
#   "upgrades"    -> LeaderBoardData::parseUpgrades(res+0xb4)     车辆升级位域
#   "data"        -> LeaderBoardData::parseData(res+0xb4)         外观/数据位域
#   "score_value" -> *(int*)(res+0xcc)
#   "replay_id"   -> *(int*)(res+0xe4)
# 所以 data/upgrades 必须是 JSON **整数**：之前的兜底 `{"data": []}` 会让
# parseData 把数组节点的指针当位域用。
# ★★ LeaderBoardData 的 `data`/`upgrades` 是**位域**，不是普通数字：
#   `LeaderBoardData::parseData(res+0xb4)` / `parseUpgrades(res+0xb4)` 直接把它们解成
#   外观与车辆升级，`tr::LeaderBoardData::getOutfit(int)` / `getBikeSkin()` 就是从解出来的
#   结构里取值，在线解析出的对象随后被搬进
#   `tr::OnlineDataContainer::{m_ghostOutfit, m_ghostBikeId, m_ghostBikeSkinIndex}`。
#   反汇编 `encodeData()`@0x625178 与 `parseData()`@0x6250fc 得到 `data` 的布局：
#     bits 0..7  = A  （encodeData 把它夹到 ≤0x63；真机所有行恒 0）
#     bits 8..13 = C  （6 位，0x3F 是哨兵；真机取值 1/2/4/13）
#     bits 14..19 / 20..25 / 26..31 = 骑手 outfit 的 part2 / part1 / part0，各 6 位
#   part 的高 2 位与 bikeSkin 只在 `extradata` 里（`parseData2()`@0x625134）。
#   真机 61 条真成绩 + 163 条占位行里 `data` **从没出现过 0**（最小 0x100，那是占位行 =
#   三个 part 全 0，而 part==0 表示"没有这个部件"）——所以 `"data": 0` 解出来就是
#   「幽灵服装/车身喷漆不对、骑手甚至没有脑袋」。
def _lb_data(parts, c=1, a=0):
    """按 `data` 的位布局拼一个值（`parts` = 骑手 part0/part1/part2，各 6 位）。"""
    p0, p1, p2 = parts
    return ((a & 0xFF) | ((c & 0x3F) << 8) | ((p2 & 0x3F) << 14)
            | ((p1 & 0x3F) << 20) | ((p0 & 0x3F) << 26))


# 真机实测出现过的整套骑手 part（part 0-79 有效，0 = 空）。
_LB_GHOST_OUTFITS = (18, 23, 47, 8, 48)


def _lb_ghost_data(owner):
    """内置幽灵（owner 是 `6f857655` 这类 online-id 哈希）没有真成绩行可查时用的 `data`。

    挑的都是客户端自己会产生的那几套骑手 part，并按 owner 稳定地分散，免得所有 AI 幽灵
    穿同一件衣服。`upgrades` 的占位值本来就是 0。
    """
    seed = 0
    for ch in str(owner or ""):
        seed = (seed * 131 + ord(ch)) & 0xFFFFFFFF
    p = _LB_GHOST_OUTFITS[seed % len(_LB_GHOST_OUTFITS)]
    return _lb_data((p, p, p))


def _ghost_appearance(track, rec, rows=None):
    """幽灵的 `(data, upgrades)` 位域：优先用幽灵主人的**真实成绩行**，取不到退回基线。

    `rows` 可以传一份已经读好的 leaderboards.json，免得每条幽灵都重读一次盘。
    """
    own = str((rec or {}).get("owner") or "")
    if own and own not in OPPONENT_PIDS:
        table = rows if rows is not None else _load_leaderboards()
        row = ((table.get("track%d" % track) or {}).get(own) or {})
        if row:
            return int(row.get("data", 0) or 0), int(row.get("upgrades", 0) or 0)
    return _lb_ghost_data(own), 0


_ROBOT_NAMES = (
    "Robotman", "IronGear", "BrakeLess", "SandStorm", "GhostRider", "TangoPro",
    "HiVoltage", "RustBucket", "NitroNina", "WheelieKing", "CliffHanger",
    "TwoStroke", "BackflipBob", "MudSlinger", "AxleRose", "SpokeSlinger",
)


def _robot_opponent(track):
    """给一条赛道挑一个稳定的假对手 -> (名字, 用时ms, 幽灵记录或 None)。

    名字必须对同一条赛道保持稳定：客户端拿到名字后会立刻用
    `.../robot_replaydata?...&player=<名字>` 和 `GET /v1/profiles/<名字>` 回查，
    每次换名字会让对手资料/幽灵文件名对不上号。
    """
    rec = acct.ghost_any_for_track(track) if track else None
    seed = (track or 0) & 0xFFFFFFFF
    if rec:
        seed = (seed * 31 + int(rec.get("contentId") or 0)) & 0xFFFFFFFF
    name = _ROBOT_NAMES[seed % len(_ROBOT_NAMES)]
    drive = int((rec or {}).get("drive_time") or 0)
    if drive <= 0:
        # 这条赛道还没有真幽灵时编一个像样的成绩，避免 time=0
        # （客户端会用 time 去请求幽灵，0 容易被当异常成绩丢掉）。
        drive = 45000 + (seed % 60000)
    return name, drive, rec


def h_match_robot(path, query, body, headers):
    """GET /public/match/v1/robot —— A.N.B.A（Robotman）支线的对手查询。

    见上面 `_ROBOT_NAMES` 处的长注释：这是「检索对手中」卡死链路的**第一环**。
    空响应会让对手名变成空串，后续头像 URL 退化成 `//...`，`onPictureReceived`
    拿到 err != 0 直接 return，状态机永远停在「检索对手中」。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    raw = (q.get("track_name") or "").strip()
    if raw.startswith("track"):
        raw = raw[5:]
    try:
        track = int(raw)
    except Exception:
        track = None
    if track is None:
        try:
            track = int(q.get("track_id") or "")
        except Exception:
            track = None

    name, drive, rec = _robot_opponent(track)
    lb_data, lb_upgrades = _ghost_appearance(track, rec)
    print("[robot] %s 赛道 %s range=%s offset=%s -> 对手 %s (%d ms%s)"
          % (path, track, q.get("range"), q.get("offset"), name, drive,
             ", 幽灵 contentId=%s" % rec.get("contentId") if rec else ", 无幽灵"),
          flush=True)
    return 200, {"Content-Type": "application/json"}, {
        # ★ player 必须非空：它决定对手名、robot_ghost-<hash(name)>-<track>.robot
        #   的文件名，以及头像 URL 里的路径段。
        "player": name,
        "drivetime": drive,
        # upgrades/data 是 LeaderBoardData 的位域整数，见 `_lb_data`：
        # 发 0 会被 parseData 解成「没有外观」→ 对手服装/车身喷漆不对、甚至没有脑袋。
        "upgrades": lb_upgrades,
        "data": lb_data,
        # score_value 用 1：parseJsonResponse 在调用 parseMatchMakingResult 之前
        # 就把 res+0xcc 预置成 1，说明这是客户端认的「有效」值。
        "score_value": 1,
        "replay_id": 0,
    }


# ------------------------------------------------- 限时活动 / 赛季（weekly_track_system）
# 客户端调用链（反汇编 tr::OnlineWeeklyChallenge，全部经 OnlineCore::getRequest）：
#   requestWeekIndex           cmd 0x76  %s/%s/liveevents/v1/weekly_track_system/basic_info
#   requestWeeklyConfiguration cmd 0x77  %s/%s/liveevents/v1/weekly_track_system/config/%d
#   requestOpponentId          cmd 0x78  %s/%s/liveevents/v1/weekly_track_system/find_opponent
#   requestRewardConfig        cmd 0x79  "%s%s%d"（base + reward_config/ + 槽位数）
# 响应由 OnlineWeeklyChallenge::parseJsonResponse @0x504ef4 分派：
#   sub w8, cmd, #0x76 ; cmp w8, #9 ; 跳转表 @0xb8710c
#   0x76 -> 0x504f7c（basic_info） 0x77 -> 0x505124（config）
#   0x78 -> 0x505164（opponent）   0x79 -> 0x5051e8（reward_config）
# ⚠ 所有数值字段都必须带 JSON **整数**类型标签（客户端逐个判 [node+0x30] == 4），
#   给字符串或 null 会被当成「这个键不存在」。
_WEEK_SECONDS = 7 * 24 * 3600


def _week_span():
    """一届午夜杯的长度（秒）。`weekly.window_days` 可改，默认 7 天（= `_WEEK_SECONDS`）。

    ★ 实验性：客户端把窗口时间戳写进存档物品 1165/1166，非 7 天的窗口**没有真机验证过**，
      所以界面必须如实标注；改它会让周号与窗口边界一起跳变（榜按周号分桶）。
    """
    days = cfg_int("weekly", "window_days", default=7) or 7
    return max(1, min(30, days)) * 24 * 3600


def _week_index():
    """-> (week_start, week_index)。basic_info 与 config 必须给出同一个周，
    否则客户端会认为「配置不属于当前周」而拒绝开赛。

    ★ `weekly.week_offset`（默认 0）是**模拟/测试**用的：设成 1 就等于"这一周已经结束、
      服务器翻到下一周" —— 客户端于是走 `updateStateEv` 的 `w9 != w10 && lb > 0` 分支
      → state 4 → 上一周的结算画面（敲奖杯 / 发奖）。真机验证奖励流程就靠它。
      WebUI 上的「立刻结束本届 / 开新一届」就是把它 +1（可撤销）。
    """
    span = _week_span()
    week = int(time.time()) // span + cfg_int("weekly", "week_offset", default=0)
    week_start = week * span
    return week_start, week & 0xFFFFFF


def _weekly_track_id():
    """本周挑战的赛道，可在 `server/data/tf_config.json` 的 `weekly.track_id` 里改
    （热加载，所以每次读）。默认 1041：必须挑一条游戏真能加载、且玩家跑过的赛道，
    1041 在幽灵库里（owner 0 / 6f857655 / 99511744 都有它的幽灵），真机日志里也出现过
    `GET /public/playerstats/v1/ranking/track1041` 与 ghost_*_1041.bin。"""
    return cfg_int("weekly", "track_id", default=1041) or 1041


def _weekly_loan_upgrade():
    """午夜杯的「租借升级」：玩家没这台车（或自己那台更低）时客户端按它给保底车。

    `weekly.loan_upgrade` = 升级级数（0..10），四个部件同值；`force_upgrade` 固定发 0
    ⇒ 客户端 `WeeklyChallengeManager::setBikeUpgradeLevel @0x636710` 取
    `max(玩家当前, 这个值)`（force≠0 才是无条件覆盖）。用户 m07949：
    「午夜杯则是车升级不够或者没这个车给一个这个赛季临时租给你的车…给你保底跑」；
    m08106 定成四个部件各 5 级。
    """
    try:
        lvl = int(cfg_int("weekly", "loan_upgrade", default=5) or 0)
    except (TypeError, ValueError):
        lvl = 5
    lvl = max(0, min(10, lvl))
    return {"handle": lvl, "engine": lvl, "wheel": lvl, "frame": lvl}


def _weekly_bike_id():
    """本届午夜杯发哪台车（`weekly.bike_id`：0 = 按本周赛道的车级别自动随机）。

    ★ 原版是**整周一台车**（游戏自带文案："you are given one track and one bike to
      play"），所以自动模式用**届号**当随机种子：同一周里谁来问、问几次都是同一台，
      翻周才换。池子 = 剧情默认车（1..9）；图的级别由 `levels[].bike` 给
      （客户端 `LevelManager::isCorrectBikeTier @0x47c170` 卡的就是这个）。
      挑不出来（车表读不到 / 图是 255 = 不限级别）就退回第一台剧情车，最后退 1
      —— 车号 0 会让客户端 `getBike(0)` 返回 NULL 后解引用崩（见下面的老注释）。
    """
    try:
        want = int(cfg_int("weekly", "bike_id", default=0) or 0)
    except (TypeError, ValueError):
        want = 0
    cats = bike_catalog()
    if want > 0:
        if not cats or want in cats:
            return want
        print("[weekly] bike_id=%d 不在车表里，改成按级别自动挑" % want, flush=True)
    if not cats:
        return 1
    tier = _track_bike_tier(_weekly_track_id())
    pool = _pvp_bike_pool(tier, None, True)
    if not pool:
        pool = [b for b in sorted(cats) if cats[b].get("story")]
    if not pool:
        return 1
    _, week = _week_index()
    return random.Random("weekly-bike|%s" % week).choice(pool)


def _weekly_leaderboard_id():
    """发给客户端的 `week_settings.week_leaderboard` —— 午夜杯排行榜的**数字 id**。

    客户端拿它去 `tr::OnlineLeaderboards::getLeaderboardName(char*, int)` @0x00509604 换榜名：
    `0`→`global_stats`、`0x10000`→`global_stats_donkey`、`0x100000`→`global_stats_crazy`、
    bits17-19 → `event_stats<N>`、其余 → `track<id>`；再按**同一个 id** 在本地
    `LeaderboardManager` 里查这张榜。而
    `WeeklyChallengeManager::hasLeaderboard` @0x006316fc / `getLeaderboard` @0x00634500 /
    `getPlayerRankPercent` @0x00634548 三个函数第一件事都是 `if (id < 1) return null / -1.0f`
    —— 所以**发 0 等于告诉客户端「本模式没有榜」**：榜区空白、`getPlayerRankPercent()`
    返回 -1.0f ⇒ 底部 TOP 1% 条无数据、周奖杯被 `getPlayerTrophyType(-1)` 判成
    5 = wood（最低档）；同时它仍然会用 `getLeaderboardName(0)` 的名字去拉
    `ranking/global_stats`，所以真机日志里能看到"拉榜了但屏上没有"。

    默认 0 = 自动用本周赛道（`weekly.track_id`）：赛道规则原文「每个人在午夜杯的赛道都是
    一样的…每周的挑战都是全球性」⇒ 榜 = 本周赛道的全球榜，而服务端这张 `track<id>` 榜
    本来就有真实行（玩家 + 内置幽灵折出来的对手，见 `_opponent_entries`），玩家自己的行也在，
    `getPlayerRankPercent` 才能算出百分位。
    """
    lb = cfg_int("weekly", "leaderboard_id", default=0)
    return lb if lb and lb > 0 else _weekly_track_id()


def _weekly_joined(profile_id):
    """-> `(他参加的那一周号, 那个榜 id)`；没参加过就是 None。

    ★ 为什么需要它：客户端把 `basic_info` 里的
      `(last_participated_week, last_participated_week_lb)` 原样喂给
      `WeeklyChallengeManager::updateStateEv` @0x00631000：
        w9 = [this+0x8c]（上次参与的周号）/ w8 = [this+0x94]（那个榜）/ w10 = [this+0x90]（本周周号）
        w9 == -1   -> state = (w8 > 0) ? 4 : 0
        w9 != w10  -> state = (w8 > 0) ? 4 : 2
        w9 == w10  -> state = (w8 != 0) ? 3 : 2
      `MenuzStateWeeklyChallenge::changeSubState` @0x007b125c 再把 state 映射成 UI 子状态
      （跳转表 @0xb9c750：0→1、1→2、2→3、3→5、4→6），`loadSubState` @0x007b3080 的
      UI 表 @0xb9c778 里 UI 3 = `loadJoinState`（"加入午夜杯！"那一屏）、UI 4 =
      `loadInProgressState`（带全球榜/Next Challenger 的那一屏）。
      于是 `lb` 恒发 0 ⇒ 永远 state 2 ⇒ 永远停在加入屏：按下按钮直接开赛，跑完又回到同一屏
      （2026-10-05 真机复现的"加入→比赛→加入→…"循环）。
      真实服务器在玩家加入后会把"参加过的周 + 那个榜"记下来发回，state 才会变 3/4。

    ★ 周号从榜行的 `updated`（我们记下这条成绩的时刻）反推，**不是**"当前周"：
      这样 `weekly.week_offset = 1`（模拟翻周）时报出去的仍是**上一周**，客户端的
      `w9 != w10` 分支才成立 —— 也就是"上一周结束 → 结算/敲奖杯"那条路。
    """
    try:
        board = "track%d" % _weekly_track_id()
        rows = _load_ranked_boards().get(board) or {}
    except Exception as exc:                 # 榜坏了也不该把周赛拖垮
        print("[liveevent] 本周榜读取失败：%r" % exc, flush=True)
        return None
    row = rows.get(profile_id) if profile_id else None
    if not row:
        return None
    try:
        week = (int(row.get("updated") or 0) // _week_span()) & 0xFFFFFF
    except (TypeError, ValueError):
        week = 0
    return (week or _week_index()[1]), _weekly_leaderboard_id()

# 奖杯序号（1..5）→ `calculateReward` 用来查 reward_config 那张 map 的键名。
# 跳转表 @0xb91880（`sub w8,w20,#1; cmp w8,#4; b.hi` 越界直接跳过）已按跳转目标
# 逐条解码（adrp 取页 + add 立即数，长度就是 memcpy 的第三个参数）：
#   trophy 1 -> 0xb877f4 'platinum'(8)   trophy 2 -> 0xb877fd 'gold'(4)
#   trophy 3 -> 0xb87802 'silver'(6)     trophy 4 -> 0xb87809 'bronze'(6)
#   trophy 5 -> 0xb87810 'wood'(4)
_WEEKLY_TROPHIES = ("platinum", "gold", "silver", "bronze", "wood")


# 周赛的「上周成绩」是本玩家上一次打完那周留下的，服务端不产生它，只是**记住客户端
# 报上来的值再原样还回去**。为什么必须记：
#   `updateLastWeekIndex` @0x6335cc 用 `last_participated_week` 决定要不要再发 POST
#   （`w8 < 1` → 发；`w8 == week_index` → 不发）。一直回 0 就永远满足 `w8 < 1`，
#   客户端每次进游戏都重发一次 `submitLastWeekData`（真机日志里成百上千次），
#   而且 `reward_config` 的轮换方案锁死在方案 0。
# 不落盘：客户端自己会把值存进存档，服务重启后它重报一次即可自愈。
# ★ 唯一的例外：玩家本周已经在本周榜上留名时，`h_liveevents_basic_info` 会把
#   `(last_participated_week, last_participated_week_lb)` 报成"本周 + 本周那个榜"，
#   否则客户端永远算不出 state 3/4、永远停在「加入午夜杯！」那一屏（见 _weekly_joined）。
_WEEKLY_LAST = {}          # profile_id -> (last_participated_week, last_participated_week_lb)


def h_liveevents_basic_info(path, query, body, headers):
    """GET|POST /public/liveevents/v1/weekly_track_system/basic_info —— 限时活动的「门」。

    ⚠ 同一个 URL 服务两条命令，响应形状共用：
      · GET  → cmd **0x76**（`requestWeekIndex` → `GET …/basic_info`）：客户端逐个
        解析下面的键，回调 `vtable[3]` → `OnlineWeeklyChallenge::onReceivedWeekIndex`
        @0x633674`(err, week_index, week_start, weeK_end, last_participated_week,
         last_participated_week_lb, left_retry_times, midnight_circuit_start_time,
         midnight_circuit_end_time, last_attempt_time)`。
      · POST → cmd **0x7f**（`postLastWeekData` / `submitLastWeekData`，URL 同样是
        basic_info，只是走 postJson —— cmd 由 `OnlineCore::postJson` 的第 4 个参数
        带进去，不是 URL 决定的）：客户端报上它的「上周成绩」。回调走
        `vtable[7]` → `onReceivedLastWeekSetup` @0x633970，**只读三个键**：
        `last_participated_week` / `last_participated_week_lb` / `left_retry_times`
        （解析点 @0x505258，`x8=[x8,#0x38]` 即 vtable 下标 7）。
      POST 的 body 有**两种**形状，都要接（.rodata 常量已确认）：
        `{"additional_retry":%d}`                                  @0xb87596
        `{"last_participated_week":%d,"last_participated_week_lb":%d,"additional_retry":%d}`
                                                                    @0xb87465
        `additional_retry` 是客户端本地装扮加成（`getCurrentChallengeRetryBonus`
        @0x58281c，本机算出 256），**不可信、也不该计入**，直接丢弃。

    客户端契约（`OnlineWeeklyChallenge::parseJsonResponse` cmd 0x76 @0x504f7c）：
    根对象成员逐个 json_strcmp，命中后取值，最后一次性回调上面那个函数。
    所有数值字段都必须是 JSON **整数**（客户端逐个判 `[node+0x30] == 4`）。

    ⚠ 两个坑：
      1. 键名是 `weeK_end`（**大写 K**，.rodata @0xb8763a 就是这么拼的，全库唯一）。
         写成 `week_end` 客户端收不到；`week_end` 那个拼法只出现在 config 里
         （@0xb876f0）。
      2. `midnight_circuit_start_time` / `midnight_circuit_end_time` 是**午夜杯**
         （Midnight Circuit）的时间窗，留 0 等于「永不开放」。而且**必须按周钉死**：
         客户端会把这对时间戳写进自己的物品表（真机存档实测 = 物品 **1165 / 1166**，
         `setUpWeeklyChallengeMissionTiming` @0x5c45f0 再把它们读回来当那三个周赛
         任务 451/452/453 的 type-6（ON_CUSTOM_TIME）条件）。以前这里给的是
         `now-3600 ~ now+24h` 的**滑动**窗口，于是每存一次档 1166 就往后挪一点
         （存档 history 里 `1166 - 1165` 恒为 90000 且两端一起前进），倒计时永远不减少。
    """
    week_start, week_index = _week_index()
    pid = _caller_profile(headers)
    parsed = _json_body(body) or {}
    if parsed.get("last_participated_week") is not None:
        _WEEKLY_LAST[pid] = (int(parsed.get("last_participated_week") or 0),
                             int(parsed.get("last_participated_week_lb") or 0))
        print("[liveevent] 记录上周成绩 pid=%s last=%d lb=%d" % ((pid,) + _WEEKLY_LAST[pid]),
              flush=True)
    last, last_lb = _WEEKLY_LAST.get(pid, (0, 0))
    joined = _weekly_joined(pid)
    if joined:
        # ★ 榜上有名 = 参加过 —— 报"**他实际参加的那一周** + 那个榜"（周号从榜行的
        #   `updated` 反推，见 _weekly_joined）。本周参加 ⇒ w9==w10 ⇒ state 3（已加入屏）；
        #   服务器翻到下一周（`weekly.week_offset=1`）⇒ w9!=w10 ⇒ state 4（上周结算/敲奖杯）。
        last, last_lb = joined
    payload = {
        "week_index": week_index,
        "week_start": week_start,
        "weeK_end": week_start + _week_span(),   # ★大写 K
        "last_participated_week": last,
        "last_participated_week_lb": last_lb,
        # 次数是服务端权威的（`start_race` 扣一次，见 _weekly_attempt_state）：
        # 用完回 0 + last_attempt_time，客户端据此算冷却剩余（时长在 config 的
        # `global_cooldown_time`），`skip_cooldown` / `refill_retry_count` 能补回来。
        "left_retry_times": _weekly_left(pid),
        # 午夜杯 = 周赛：窗口 = 本周（week_start ~ week_end），一周内恒定。
        "midnight_circuit_start_time": week_start,
        "midnight_circuit_end_time": week_start + _week_span(),
        "last_attempt_time": _weekly_attempt_state(pid)[3],
    }
    print("[liveevent] basic_info week_index=%s last=%d lb=%d" %
          (payload["week_index"], last, last_lb), flush=True)
    return 200, {"Content-Type": "application/json"}, payload


def h_liveevents_config(path, query, body, headers):
    """GET /public/liveevents/v1/weekly_track_system/config/<n> —— 本周挑战配置。

    响应契约（`parseChallengeConfiguration` @0x5055f0，键地址已逐个反汇编确认）：
        week_index                                        -> cfg+0x00
        week_settings{week_start, week_end, week_leaderboard,
                      global_cooldown_time, global_retry_count,
                      global_gem_amount}                  -> cfg+0x04..0x14, 0x70
        challenge_settings{track_id, bike_id, bike_skin,
                           bike_upgrade{handle,engine,wheel,frame},
                           force_upgrade, task[]}         -> cfg+0x18..0x34, 0x38/0x40
        extra_settings{ad_reward_skip_cooldown_time,
                       ad_reward_retry_count}             -> cfg+0x68/0x6c
        retry_pool[{retry,gems}]                          -> cfg+0x48/0x50/0x58
    ⚠ 收尾会做 `strcmp(json, "null")`：**响应体字面为 "null" 时回调 err=7** 直接失败。
    ⚠ 路径末段那个 %d 是客户端传进来的（周号），我们忽略即可，任何值都回同一份配置。
    """
    week_start, week_index = _week_index()
    # ★ 路径末段是客户端要的**周号**：平时就是本周（`config/0` 是"当前周"的意思），
    #   但翻周之后它会拿 `last_participated_week` 去要**上一周**的配置（用来渲染
    #   刚结束那一周的成绩/结算）。以前这里一律回"本周"，于是客户端判定
    #   "配置不属于当前周"并死循环重试（真机 2026-10-05 23:56 每秒好几次 config/2961，
    #   界面卡在「查看进度…」）。所以：末段是合法周号且不等于本周时，按那一周回。
    try:
        req_week = int(path.rstrip("/").rsplit("/", 1)[-1])
    except (AttributeError, ValueError):
        req_week = 0
    if req_week > 0 and req_week != week_index:
        week_index = req_week
        week_start = req_week * _week_span()
        print("[liveevent] config 要的是第 %d 周（非本周）—— 按那一周回" % req_week,
              flush=True)
    payload = {
        "week_index": week_index,
        "week_settings": {
            "week_start": week_start,
            "week_end": week_start + _week_span(),
            # ★ 午夜杯排行榜的数字 id（客户端自己 id→榜名，见 _weekly_leaderboard_id）。
            #   发 0 等于「没有榜」：榜区空白 + TOP 1% / 周奖杯一起退化。默认 0 = 本周赛道。
            "week_leaderboard": _weekly_leaderboard_id(),
            # 冷却/重试：冷却时长与每周次数都是**规则**，实际剩余次数走 basic_info 的
            # left_retry_times（见 _weekly_attempt_state）。
            "global_cooldown_time": _weekly_cooldown_seconds(),
            "global_retry_count": _weekly_retry_limit(),
            "global_gem_amount": 1,
        },
        "challenge_settings": {
            "track_id": _weekly_track_id(),
            # ⚠ bike_id 必须是 /conf/bikes.txt 里的合法车号（1..19，没有 0）。
            # 真机实测 bike_id=0 必崩：`MenuzStateWeeklyChallenge::loadIntroState`
            # 把这里的 bike_id 直接喂给
            #   `MenuzComponentWeeklyChallengeBike::setBike(int,int)` @0x6cbee4
            #     -> `UpgradeManager::getBike(unsigned short)` @0x62ac2c
            # 该函数遍历 UpgradeManager 里由 `parseBikeData` @0x62a190 从
            # /conf/bikes.txt 建出来的车表，逐个比对 `[bike+0x3e]`（uint16 车号），
            # 查不到就 `mov x0,xzr; ret` 返回 NULL。调用方紧接着
            #   `0x6cbf20  ldr w8,[x0,#0xb0]`
            # 于是 SIGSEGV / SEGV_MAPERR，fault addr 0xb0，崩在 GLThread。
            # （`getBikeIndexByID` @0x62a12c 就是 `sub w0,w1,#1`，佐证车号从 1 开始。
            #  `/conf/bikes.txt` 恰好 19 台，1..19 连续，无 0。）
            "bike_id": _weekly_bike_id(),
            "bike_skin": 0,
            "bike_upgrade": _weekly_loan_upgrade(),
            # 0 = 不做强制改装（= 保底模式：玩家升级比租借车高就用玩家自己的）。
            # ★ 这不影响 bike_id：上面那台车永远会被 setBike 拿去查表，所以 bike_id
            #   必须合法，跟 force_upgrade 无关。
            "force_upgrade": 0,
            # task 保持空：`parseChallengeConfiguration` @0x5058c8 只把数组元素
            # 读成 {mt::String skill; int count;} 存进 cfg+0x38/0x40，解析期不查
            # MissionDB、也没有解引用，填了也没人用——真正驱动周赛任务的是
            # MissionDB 里写死的 3 个任务 451/452/453（`setUpWeeklyChallengeMissionTiming`
            # @0x5c45f0 用午夜杯时间窗改写它们的 type-6 条件），纯客户端逻辑。
            "task": [],
        },
        "extra_settings": {
            "ad_reward_skip_cooldown_time": 0,
            "ad_reward_retry_count": 1,
        },
        "retry_pool": [{"retry": 1, "gems": 1}],
    }
    print("[liveevent] config -> 赛道 %d / 榜 id %d / 周号 %d" %
          (_weekly_track_id(), _weekly_leaderboard_id(), week_index), flush=True)
    return 200, {"Content-Type": "application/json"}, payload


def _weekly_opponent():
    """本周的 Next Challenger —— 返回 `(对手标识, 他在本周赛道上的幽灵 contentId)`。

    ★ 为什么必须是 **pid** 而不是显示名（真机日志 2026-10-05 23:27 实证）：
      客户端拿到 `find_opponent` 的 `"TangoPro"` 后立刻去查那个人的成绩
      `GET /public/playerstats/v1/stats/track1041?players=TangoPro`；而服务端的榜行
      是按 **profileId** 存的，用显示名永远查不到 ⇒ 客户端**死循环重试**
      （同一秒里 `find_opponent` + `stats?players=TangoPro` + `ghost/0/payload` 各刷 ~30 次）。
      pid 两边都对得上；显示名客户端会自己用 `/v1/profiles/<pid>` 解析。

    ★ `replay_id` 必须是这个对手在**本周赛道**上的幽灵 contentId：客户端拿它去
      `GET /public/userstorage/v2/content/ghost/<id>/payload`。回 0 就是 404 再加一轮
      死循环（日志里 `ghost/0/payload -> 404` 与上面那对请求同步出现）。
      pid→contentId 的映射由 `_opponent_entries()` 从内置幽灵库建出来（见那里的注释）。

    榜上还没有别人（或那条赛道没有内置幽灵）时回落到原来的机器人名字 + 0。
    """
    board = "track%d" % _weekly_track_id()
    rows, ghosts = _opponent_entries()
    for pid in OPPONENT_PIDS:
        rec = (rows.get(pid) or {}).get(board)
        cid = (ghosts.get(pid) or {}).get(board)
        if rec and cid is not None:
            return pid, int(cid)
    name, _drive, _rec = _robot_opponent(_weekly_track_id())
    return name, 0


# ------------------------------------------------- 本周榜单的"其他玩家"（合成行）
# ★ 为什么非要造：午夜杯的百分位是客户端自己算的
#   （`WeeklyChallengeManager::getPlayerRankPercent` @0x00634548 → 名次/榜行数），
#   榜上只有 3 行时最好的成绩也只能显示「前 34%」，"进全球 1%"在物理上不可能。
#   原始服务器上有几万人，我们只有几个真实账号 —— 这块就是补这个差距的。
# ★ 三个硬约束：
#   1) **不落盘**：合成行只在 `_load_ranked_boards()` 的视图里，`_record_result` 走的是
#      原始 `_load_leaderboards()`，所以 leaderboards.json 永远干净（与 OPPONENT_PIDS 同）。
#   2) **同周内恒定**：种子 = (week_index, track_id)，重启/多进程都长一样 ——
#      客户端会缓存名字与成绩，行一变界面就闪。
#   3) **不进总榜**：`_aggregate_global_entries()` 跳过这些 pid，免得 120 个假人
#      把碉堡的天梯榜也算进去（那是另一个模式的数据）。
_WEEKLY_FAKE_NAME_POOL = (
    # pvp.png 里那几条真名（原始服务器 2016 年的榜）+ 本机机器人名池
    "Uschard", "Fevves", "CHG420", "Sandholm", "dnz15", "Bakerboah123", "accelman",
) + _ROBOT_NAMES
_WEEKLY_FAKE_NAMES = {}          # pid -> 显示名（h_profiles_query 用）
_WEEKLY_FAKE_PIDS = set()
_WEEKLY_FAKE_CACHE = {"key": None, "rows": {}}


def _weekly_fake_base_ms(track):
    """合成行的基准时间 = 这条赛道上**最快的内置幽灵**的真实成绩。

    挑幽灵而不是随便编一个数：这样"跑得比内置幽灵快的人才能排前面"这件事是有依据的
    （真机 1041：内置幽灵 25.656s / 28.577s ⇒ 基准 25656ms）。
    """
    board = "track%d" % track
    rows, _ = _opponent_entries()
    times = [int((r or {}).get("drivetime") or 0)
             for boards in rows.values() for b, r in boards.items() if b == board]
    times = [t for t in times if t > 0]
    return min(times) if times else 30000


def _weekly_fake_names():
    """名字池：`weekly.fake_names`（数组，将来 WebUI 可改）优先，否则用内置池。"""
    names = cfg("weekly", "fake_names", default=None)
    if not isinstance(names, list) or not names:
        names = list(_WEEKLY_FAKE_NAME_POOL)
    return [str(x) for x in names if str(x).strip()]


def _weekly_fake_field():
    """-> {board: {pid: row}}；`weekly.fake_field` <= 0 时是空表（默认关）。

    时间分布（**基准是固定的**，所以不是"水涨船高"的跑步机）：
      `fake_field_base_ms`（0 = 自动 = 这条赛道最快的内置幽灵）为基准，
      往快的一侧只放开 `fake_field_fast_pct`%（默认 3），往慢的一侧放到
      `fake_field_slow_pct`%（默认 25）。
      真机 1041：基准 25656ms ⇒ 合成行落在 24886 ~ 32070ms。
      玩家 24.368s ⇒ 直接第一（1/123 = 0.8% = TOP 1%）；想有点挑战就把
      fast_pct 调大（比如 8 ⇒ 最快 23604ms，得再快 3% 才第一）。
      ⚠ 基准**不要**取玩家自己的成绩 —— 那样他一进步整个榜也跟着变，永远差那一点。
    """
    n = cfg_int("weekly", "fake_field", default=0)
    if n <= 0:
        return {}
    track = _weekly_track_id()
    board = "track%d" % track
    fast = max(0, min(50, cfg_int("weekly", "fake_field_fast_pct", default=3)))
    slow = max(0, min(200, cfg_int("weekly", "fake_field_slow_pct", default=25)))
    base = cfg_int("weekly", "fake_field_base_ms", default=0) or _weekly_fake_base_ms(track)
    week = _week_index()[1]
    key = (week, track, n, fast, slow, base, tuple(_weekly_fake_names()))
    if _WEEKLY_FAKE_CACHE["key"] == key:
        return _WEEKLY_FAKE_CACHE["rows"]
    rnd = random.Random("weekly-%d-%d" % (week, track))
    pool = _weekly_fake_names()
    week_start = _week_index()[0]
    per_board, names = {}, {}
    for i in range(n):
        pid = "%08x-%04x-4%03x-8%03x-%012x" % (
            rnd.getrandbits(32), rnd.getrandbits(16), rnd.getrandbits(12),
            rnd.getrandbits(12), rnd.getrandbits(48))
        name = pool[i % len(pool)]
        if i >= len(pool):                     # 名字不够就给后缀，保证不重名
            name = "%s%d" % (name, 10 + i // len(pool) + 1)
        drive = max(1000, int(base * (1.0 + rnd.uniform(-fast, slow) / 100.0)))
        per_board[pid] = {
            "player": pid, "drivetime": drive, "submittime": week_start,
            "data": 0, "upgrades": 0, "extradata": 0, "updated": week_start,
        }
        names[pid] = name
    rows = {board: per_board}
    _WEEKLY_FAKE_NAMES.clear()
    _WEEKLY_FAKE_NAMES.update(names)
    _WEEKLY_FAKE_PIDS.clear()
    _WEEKLY_FAKE_PIDS.update(names)
    _WEEKLY_FAKE_CACHE["key"] = key
    _WEEKLY_FAKE_CACHE["rows"] = rows
    print("[liveevent] 本周榜合成 %d 个对手（基准 %d ms，快 %d%% / 慢 %d%%）" %
          (n, base, fast, slow), flush=True)
    return rows


# --------------------------------------------------------- 本周比赛次数（服务端权威）
# 规则（帮助原文）：每周 3 次机会，用完进冷却，可用宝石补次/跳冷却。
# ★ 不落盘：重启 = 新的一周重新给满次数。私有服可接受，也省掉一个要维护的状态文件；
#   代价写在 `ponytail:` 里，将来要持久化就把它挪进 server/data/。
# ponytail: 次数只在内存里；重启服务器会白送满次数。
_WEEKLY_ATTEMPTS = {}            # pid -> [week_index, used, bonus, last_attempt_ts]


def _weekly_retry_limit():
    return max(0, cfg_int("weekly", "left_retry_times", default=3))


def _weekly_cooldown_seconds():
    return max(0, cfg_int("weekly", "cooldown_seconds", default=3600))


def _weekly_attempt_state(pid):
    """-> [week_index, used, bonus, last_attempt_ts]；跨周自动清零。"""
    week = _week_index()[1]
    st = _WEEKLY_ATTEMPTS.get(pid)
    if st is None or st[0] != week:
        st = [week, 0, 0, 0]
        _WEEKLY_ATTEMPTS[pid] = st
    return st


def _weekly_left(pid):
    st = _weekly_attempt_state(pid)
    return max(0, _weekly_retry_limit() + st[2] - st[1])


# pid -> 下一次 reward_config 用哪套轮换方案（3 套奖励池）。客户端挑池内那一件用的是
# 它自己的 rand()（不播种 ⇒ 每次都同一件），所以我们只能靠"换池子"给变化 —— 见
# h_liveevents_reward_config 的 ★★ 段。
_REWARD_ROTATION = {}


def h_liveevents_find_opponent(path, query, body, headers):
    """GET /public/liveevents/v1/weekly_track_system/find_opponent —— 本周对手。

    响应契约（`OnlineWeeklyChallenge::parseJsonResponse` cmd 0x78 @0x505164）：
        {"opponent": "<str>", "replay_id": <int>}
    → `ChallengeOpponent+0x00`（mt::String::operator=）/ `+0x20`（int），然后
      `listener->vtable[1](listener, err=0)`。
    ⚠ `"opponent"` 在 .rodata 里是 `/find_opponent` 的尾巴子串（@0xb871fe），
      别被字符串搜索误导成独立常量。
    名字必须对同一周稳定：客户端会拿它去查头像和幽灵。
    ★ 两种"名字"的区别见 `_weekly_opponent()`：必须是 **pid**，且 `replay_id`
      必须是他在本周赛道上的**幽灵 contentId**，否则客户端会每秒刷三十次。
    """
    player, replay_id = _weekly_opponent()
    print("[liveevent] find_opponent -> %s (replay_id=%d)" % (player, replay_id), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "opponent": player,
        "replay_id": replay_id,
    }


def h_liveevents_reward_config(path, query, body, headers):
    """GET /public/liveevents/v1/weekly_track_system/reward_config/<n> —— 奖励表。

    响应契约（cmd 0x79 @0x5051e8 → `parseRewardsSlot` @0x505d28）：
      根对象的每个一级成员 = 一个奖杯槽；成员名必须是 `calculateReward` 查表用的
      键（见 _WEEKLY_TROPHIES），成员值形如 `{"reward":[N,...], "<任意名>":[c,...]}`。
      `reward` **必须是槽对象的第一个成员**（parseRewardsSlot 拿 first_child 的
      key 去 strcmp("reward")），两个数组按 index 配成 pair(reward[i], sibling[i])。

    pair 的语义（`getRewardItemForSlot` @0x635880）：
      pair.first  → `snprintf("Reward_%d", first)` 查本地 /conf/wts_rewards.txt；
      pair.second → 本地查不到时的后备编号（0x635b7c 分支）。
    所以两个数都必须是 1..15 之间、本地表里真实存在的 Reward_N。

    `Reward_<n>` 的排布 = 3 个轮换方案 × 5 个奖杯，已按内容核对：
      Reward_{k*5+1} 赛道(23)   +2 服装(30)   +3 服装/摩托(8~12)
      +4 宝石/金币/金券(14)     +5 同款但更少(14)

    ★★ 轮换方案必须**每次下发都换**（真机 bug，User m01488：「最高奖励也只有一个地图，
      我领取了两次是同一个地图」）：
      `getRewardItemForSlot` 里挑池内那一件的逻辑是
        `0x00635be8 bl rand` → `w8 = rand() % (vector_size / 0x44)`（一个 68 字节的条目）
      也就是**用客户端的 `rand()`**。而游戏没有（或没在正确时机）`srand()`，第一次 `rand()`
      恒为 1804289383 ⇒ `% 23 = 11` ⇒ **每次都是同一件**。
      客户端的随机数我们改不了，能改的只有"给哪个池子" —— 所以这里按请求轮转方案
      （`(base+k) % 3`），同一个池内下标就会落到不同内容上；`weekly.reward_slots`
      （默认 1，可到 3）还能让一档一次给多件（每个槽 = 一个池子的一件）。

    ⚠ 槽对象只给一个成员会崩：parseRewardsSlot 在 0x505d7c 无条件执行
      `ldr x25, [x8, #0x10]`，x8 = first_child->next，没有兄弟成员时那里是空指针。
      所以每个槽固定给两个等长数组（`reward` 第一 + 一个同名长度的兄弟）。
    """
    try:
        n = int(path.rstrip("/").rsplit("/", 1)[-1])
    except (AttributeError, ValueError):
        n = 0
    # 按 pid 轮转"用哪套方案打头"，保证连续几次领取/进入拿到的是不同的池子。
    pid = _caller_profile(headers)
    base = _REWARD_ROTATION.get(pid, n % 3 if n > 0 else 0) % 3
    _REWARD_ROTATION[pid] = (base + 1) % 3
    slots = max(1, min(8, cfg_int("weekly", "reward_slots", default=1)))
    payload = {}
    for i, name in enumerate(_WEEKLY_TROPHIES):
        ids = _reward_pool_ids(name, i, base, slots)
        payload[name] = {"reward": ids, "n": ids}
    print("[liveevent] reward_config %s -> 方案 %d(+%d 槽) %s" %
          (path, base, slots, " ".join("%s=%s" % (k, v["reward"])
                                       for k, v in payload.items())), flush=True)
    return 200, {"Content-Type": "application/json"}, payload


def _reward_pool_ids(name, tier, base, slots):
    """某一档奖杯这次发哪几个池子（`Reward_N` 的 N）。

    默认规则：第 tier 档（0..4）= 轮换方案 `(base+k)%3` 的 `Reward_{v*5+tier+1}`，
    与客户端本地表 `/conf/wts_rewards.txt` 的排布一致（3 套方案 × 5 档）。

    `weekly.reward_ids` 可以按档位写死一组池子（数组，循环使用），例如
      `{"platinum": [3, 8, 13], "gold": [2, 7, 12]}`
    —— 想换"最高奖励是什么"就改这里（客户端那张表的**内容**我们改不了，能换的只有
    给哪个池子）。内置表里可选的池子：
      Reward_{1,6,11} 赛道/赛道碎片(23)   Reward_{2,7,12} 服装(30)
      Reward_{3,8,13} **整台车×2**(8~12)  Reward_{4,9,14} 宝石/改件/金币/黄金票
      Reward_{5,10,15} 上一档的小号版本
    """
    custom = (cfg("weekly", "reward_ids", default=None) or {})
    pool = custom.get(name) if isinstance(custom, dict) else None
    ids = []
    if isinstance(pool, list):
        for raw in pool:
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue
            if 1 <= val <= 15:
                ids.append(val)
    if not ids:
        return [((base + k) % 3) * 5 + tier + 1 for k in range(slots)]
    return [ids[(base + k) % len(ids)] for k in range(slots)]


# ============================================ 午夜杯 · 后台运营参数（/__api/admin/weekly）
# 这一段只服务后台的「午夜杯」页：读一份"当前生效值"、按字段批量改（改一个键记一条审计、
# 界面上一键撤销）、整页参数的模板存取。
# ★ 客户端契约一个字都没改：动的仍然只有 `weekly.*` 那几个键，真正下发给客户端的东西在
#   `h_liveevents_basic_info` / `h_liveevents_reward_config` 里 —— 客户端**每进一次模式**
#   才拉一次 reward_config，所以改完要让玩家退出午夜杯再进来。
_WEEKLY_KEYS = {
    "track_id": (1, 10 ** 6),
    "leaderboard_id": (0, 0xFFFFFF),
    "fake_field": (0, 500),
    "fake_field_base_ms": (0, 3600 * 1000),
    "fake_field_fast_pct": (0, 50),
    "fake_field_slow_pct": (0, 200),
    "left_retry_times": (0, 99),
    "cooldown_seconds": (0, 30 * 24 * 3600),
    "week_offset": (-520, 520),
    "reward_slots": (1, 8),
    "window_days": (1, 30),
    # 本届的车：0 = 按赛道级别自动随机（见 `_weekly_bike_id()`），>=1 = 整届固定这台。
    "bike_id": (0, 64),
    # 租借升级级数（0..10，四个部件同值；0 = 不发租借车，纯玩家自己的升级）。
    "loan_upgrade": (0, 10),
}
# 键不在配置文件里时界面上显示什么（必须与 _TF_CONFIG_DEFAULTS["weekly"] 一致）。
_WEEKLY_FALLBACK = {
    "track_id": 1041, "leaderboard_id": 0, "fake_field": 0, "fake_field_base_ms": 0,
    "fake_field_fast_pct": 3, "fake_field_slow_pct": 25, "left_retry_times": 3,
    "cooldown_seconds": 3600, "week_offset": 0, "reward_slots": 1, "window_days": 7,
    "bike_id": 0, "loan_upgrade": 5,
}
# 「只套用奖励方案」套的就是这两个键。
_WEEKLY_REWARD_KEYS = ("reward_slots", "reward_ids")

_TRACK_CATALOG_PATH = os.path.join(HERE, "admin", "items.json")
_TRACK_CACHE = {"mtime": None, "rows": []}


def _coerce_int(key, raw):
    """界面来的数字 -> int。**不悄悄退回默认值**：填错了必须报错，不能装作改成了。"""
    if isinstance(raw, bool):
        raise ValueError(key)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if raw != int(raw):
            raise ValueError(key)
        return int(raw)
    txt = str(raw).strip()
    if not re.fullmatch(r"[+-]?\d{1,12}", txt):
        raise ValueError(key)
    return int(txt, 10)


def _weekly_reward_ids(raw):
    """校验并规整 `weekly.reward_ids`（档位 -> 池子编号数组，编号 1..15）。-> (值, 错误码)。"""
    out = {}
    if raw is None or raw == {} or raw == []:
        return {}, None
    if not isinstance(raw, dict):
        return None, "bad-reward-ids"
    for name, pool in raw.items():
        name = str(name)
        if name not in _WEEKLY_TROPHIES:
            return None, "bad-tier:%s" % name
        if not isinstance(pool, list):
            return None, "bad-pool:%s" % name
        ids = []
        for item in pool:
            try:
                val = int(item)
            except (TypeError, ValueError):
                return None, "bad-pool:%s" % name
            if not 1 <= val <= 15:
                return None, "bad-pool:%s" % name
            ids.append(val)
        if ids:
            out[name] = ids[:32]
    return out, None


def weekly_values():
    """午夜杯页的「当前生效值」：配置里有什么用什么，缺的补代码默认值。只读。"""
    vals = {}
    for key, (lo, hi) in _WEEKLY_KEYS.items():
        raw = cfg("weekly", key, default=None)
        if raw is None:
            vals[key] = _WEEKLY_FALLBACK[key]
            continue
        try:
            val = _coerce_int(key, raw)
        except (TypeError, ValueError):
            val = _WEEKLY_FALLBACK[key]
        vals[key] = max(lo, min(hi, val))
    ids, err = _weekly_reward_ids(cfg("weekly", "reward_ids", default=None))
    vals["reward_ids"] = {} if err else ids
    return vals


def _latest_audit_id(path):
    """刚写进去的那条审计的 id（界面靠它给「撤销」按钮）。找不到就 None。"""
    want = [str(k) for k in path]
    for rec in audit_log(AUDIT_KEEP):
        if rec.get("path") == want:
            return rec.get("id")
    return None


def audit_for(prefix, limit=20):
    """某一页管着的键最近被改了些什么（按 path 前缀筛；撤销记录也算进来）。"""
    pre = [str(k) for k in prefix]
    out = []
    for rec in audit_log(AUDIT_KEEP):
        if (rec.get("path") or [])[:len(pre)] == pre:
            out.append(rec)
            if len(out) >= max(1, int(limit)):
                break
    return out


def admin_weekly_apply(fields):
    """午夜杯页的写入：`fields = {键: 值}`，值为 null ⇒ 删掉这个键（回到代码默认值）。

    -> (结果, 错误码)。**先全部校验、再动手**：宁可一个都不改，也不要改一半留一半
    （一次页面保存十几个字段，改一半最难解释）。
    错误码：bad-request / unknown-key:<k> / bad-value:<k> / range:<k>:<lo>-<hi> /
           bad-reward-ids / bad-tier:<t> / bad-pool:<t>（_param_message 翻成中文）。
    """
    if not isinstance(fields, dict) or len(fields) > 40:
        return None, "bad-request"
    ops = []
    for raw_key, raw_val in fields.items():
        key = str(raw_key)
        if key == "reward_ids":
            if raw_val is None:
                ops.append((["weekly", key], None, key))
                continue
            ids, err = _weekly_reward_ids(raw_val)
            if err:
                return None, err
            ops.append((["weekly", key], ids, key))
            continue
        if key not in _WEEKLY_KEYS:
            return None, "unknown-key:%s" % key
        lo, hi = _WEEKLY_KEYS[key]
        if raw_val is None:
            ops.append((["weekly", key], None, key))
            continue
        try:
            val = _coerce_int(key, raw_val)
        except (TypeError, ValueError):
            return None, "bad-value:%s" % key
        if not lo <= val <= hi:
            return None, "range:%s:%d-%d" % (key, lo, hi)
        # 0 = 自动（按赛道级别随机），>0 必须是真车号：不存在的车号客户端拿不到车 → 崩。
        if key == "bike_id" and val > 0:
            catalog = bike_catalog()
            if catalog and val not in catalog:
                return None, "bad-bike:%d" % val
        ops.append((["weekly", key], val, key))
    applied = []
    for path, val, key in ops:
        if val is None:
            before, existed = cfg_unset(path, kind="weekly")
            if not existed:               # 本来就是默认值，没什么可撤的
                applied.append({"key": key, "before": None, "after": None, "audit": None})
                continue
        else:
            before = cfg("weekly", key, default=None)
            cfg_set(path, val, kind="weekly")
        applied.append({"key": key, "before": before, "after": val,
                        "audit": _latest_audit_id(path)})
    return {"applied": applied, "values": weekly_values()}, None


def track_catalog():
    """赛道 id -> 名字（`server/admin/items.json` 的 `levels` 段）。

    后台赛道下拉靠它；**没有 `levels` 段就返回空表**（前端退化成手填数字，绝不猜名字）。
    """
    try:
        stamp = os.path.getmtime(_TRACK_CATALOG_PATH)
    except OSError:
        return []
    if _TRACK_CACHE["mtime"] == stamp:
        return _TRACK_CACHE["rows"]
    rows = []
    try:
        with open(_TRACK_CATALOG_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        for raw_id, node in (data.get("levels") or {}).items():
            if not isinstance(node, dict):
                continue
            try:
                lid = int(raw_id)
            except (TypeError, ValueError):
                continue
            rows.append({"id": lid,
                         "name": node.get("en") or node.get("cn") or "",
                         "name_cn": node.get("cn") or node.get("en") or "",
                         # 这张图要求的车级别（`levels[].bike` = 表里的 `B`）；
                         # 255 = 不限，None = 表里没这个字段（退化成不限）。
                         "bike": node.get("bike")})
        rows.sort(key=lambda r: r["id"])
    except (OSError, ValueError, AttributeError):
        return []
    if not rows:
        return []                          # 没建表就别缓存"空"，建完表立刻能认出来
    _TRACK_CACHE["mtime"] = stamp
    _TRACK_CACHE["rows"] = rows
    return rows


_BIKE_CACHE = {"mtime": None, "rows": {}}


def bike_catalog():
    """车号 -> 车表一行（`server/admin/items.json` 的 `bikes` 段，源自 `/conf/bikes.txt`）。

    字段：`name`/`name_cn` 车名、`tier` 车级别（0/1/2，255 = 特殊车）、`story` 是否
    剧情默认车（1..9）。**按地图级别发车就靠这张表**（规则见客户端
    `LevelManager::isCorrectBikeTier @0x47c170`）。表读不到就返回空 dict —— 调用方
    必须退化成固定 `bike_id`，绝不猜车号（真机 bike_id=0 会崩，见 h_liveevents_config）。
    """
    try:
        stamp = os.path.getmtime(_TRACK_CATALOG_PATH)
    except OSError:
        return {}
    if _BIKE_CACHE["mtime"] == stamp:
        return _BIKE_CACHE["rows"]
    rows = {}
    try:
        with open(_TRACK_CATALOG_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        for raw_id, node in (data.get("bikes") or {}).items():
            if not isinstance(node, dict):
                continue
            try:
                bid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if bid < 1:
                continue
            tier = node.get("tier")
            rows[bid] = {
                "id": bid,
                "name": node.get("en") or node.get("cn") or ("Bike %d" % bid),
                "name_cn": node.get("cn") or node.get("en") or ("车 %d" % bid),
                "tier": tier if isinstance(tier, int) else None,
                "story": bool(node.get("story")),
            }
    except (OSError, ValueError, AttributeError):
        return {}
    if not rows:
        return {}                              # 没建表就别缓存"空"，建完表立刻能认出来
    _BIKE_CACHE["mtime"] = stamp
    _BIKE_CACHE["rows"] = rows
    return rows


def _track_bike_tier(track):
    """这张图要求的车级别（0/1/2；255 = 不限；None = 表里没有 = 当不限）。"""
    try:
        track = int(track)
    except (TypeError, ValueError):
        return None
    for row in track_catalog():
        if row["id"] == track:
            tier = row.get("bike")
            return tier if isinstance(tier, int) else None
    return None


def _weekly_track_health(track):
    """赛道在服务器上有没有能用的数据 -> (能挑战的幽灵条数, 榜单真实行数)。

    午夜杯的预检就靠这两个数：**没有幽灵**的赛道，玩家点「挑战」时服务端只能回
    `replay_id = 0`，客户端会一直去要 `ghost/0/payload`（每秒几十次 404），
    表现就是卡在「加入午夜杯」那一屏出不来。2026-10-06 用户把赛道换成 1258 就踩了这个。
    """
    board = "track%d" % track
    try:
        _, gmap = _opponent_entries()
        ghosts = sum(1 for m in gmap.values() if m.get(board) is not None)
    except Exception as exc:
        print("[weekly] 幽灵库读取失败：%s" % exc, flush=True)
        ghosts = -1
    try:
        rows = len(_load_leaderboards().get(board) or {})
    except Exception:
        rows = -1
    return ghosts, rows


def admin_weekly_status():
    """午夜杯「现状卡」：本周是哪一周、榜上有多少行、谁还能跑几次。全部只读。"""
    week_start, week = _week_index()
    span = _week_span()
    track = _weekly_track_id()
    board = "track%d" % track
    _, total = _stored_entries(board, None, keep_total=True)
    fake = _weekly_fake_field().get(board) or {}
    limit = _weekly_retry_limit()
    ghosts, board_rows = _weekly_track_health(track)
    warnings = []
    if ghosts == 0:
        warnings.append({
            "cn": ("赛道 #%d 上一个幽灵都没有（内置和玩家上传的都没有）：玩家点「挑战」时服务端只能回"
                   "幽灵编号 0，游戏会反复去要一个不存在的幽灵（每秒几十次 404），表现是卡在"
                   "「加入午夜杯」进不去。先让玩家在这条赛道上跑一圈上传幽灵，或者把赛道换回 1041"
                   "（它带一套内置幽灵）。" % track),
            "en": ("Track #%d has no ghosts at all (neither built-in nor player-uploaded): the server can "
                   "only return ghost id 0, so the client loops requesting a ghost that does not exist "
                   "(dozens of 404s per second) and never gets past the Midnight Cup join screen. Have a "
                   "player upload a ghost on that track first, or switch back to 1041." % track)})
    elif board_rows == 0:
        warnings.append({
            "cn": ("赛道 #%d 的榜单上还没有真实成绩（只有陪跑对手）：玩家进去看到的榜是假的，"
                   "结算前不会有真名次。" % track),
            "en": ("Track #%d has no real leaderboard rows yet (only the fake field): the board players see "
                   "is synthetic until someone sets a real time." % track)})
    lb = _weekly_leaderboard_id()
    if lb != track:
        warnings.append({
            "cn": ("周榜 ID 是 #%d，跟赛道号 #%d 不一样（配置里填了非 0 值）：客户端会去查 #%d 那张榜。"
                   "那个榜上没数据的话，榜区就是空的、TOP 1%% 奖励会退化。" % (lb, track, lb)),
            "en": ("Weekly leaderboard id is #%d while the track is #%d (a non-zero override): the client "
                   "reads board #%d, so an empty board means a blank list and degraded top-1%% rewards."
                   % (lb, track, lb))})
    if span != _WEEK_SECONDS:
        warnings.append({
            "cn": "窗口不是 7 天（现在是 %d 天）：客户端只真机验过 7 天，其它天数是实验模式。" % (span // 86400),
            "en": ("The window is not 7 days (currently %d): only 7 days is device-verified; other values "
                   "are experimental." % (span // 86400))})
    players = []
    for pid, st in list(_WEEKLY_ATTEMPTS.items())[:500]:
        if not isinstance(st, (list, tuple)) or len(st) < 4:
            continue
        this_week = st[0] == week
        players.append({
            "profile": str(pid),
            "used": int(st[1]),
            "left": max(0, limit + int(st[2]) - int(st[1])) if this_week else limit,
            "last_attempt": int(st[3]),
            "this_week": this_week,
        })
    players.sort(key=lambda p: (-p["last_attempt"], p["profile"]))
    return {
        "week_index": week,
        "week_start": week_start,
        "week_end": week_start + span,
        "now": int(time.time()),
        "window_days": span // 86400,
        # 非 7 天 = 实验性（客户端把窗口写进存档物品 1165/1166，只有 7 天真机验过）。
        "experimental": span != _WEEK_SECONDS,
        "track_id": track,
        "board": board,
        "leaderboard_id": lb,
        # 本周实际发给所有人的车（`_weekly_bike_id()`：配置填了就用它，0 = 按赛道
        # 级别从剧情车里挑、按周号播种整周不变）。`track_bike` = 赛道要求的车辆级别
        # （255/None = 不限），界面拿它解释「本周为什么是这台车」。
        "effective_bike": _weekly_bike_id(),
        "track_bike": _track_bike_tier(track),
        "bikes": sorted(bike_catalog().values(), key=lambda b: b["id"]),
        "ghosts": ghosts,
        "board_rows": board_rows,
        "warnings": warnings,
        "base_ms": (cfg_int("weekly", "fake_field_base_ms", default=0)
                    or _weekly_fake_base_ms(track)),
        "entries": total,
        "fake": len(fake),
        "players": players[:50],
        "rotation": [{"profile": str(p), "next_base": b}
                     for p, b in list(_REWARD_ROTATION.items())[:50]],
        "retry_limit": limit,
        "cooldown_seconds": _weekly_cooldown_seconds(),
    }


# ==================================================== 参数模板（午夜杯/碉堡共用一份文件）
# 模板 = 整页参数的**快照**，存在服务端文件里（不落进 tf_config.json）。
# 设计取舍：
#   · 存 / 改名 / 删**不进审计** —— 那只是草稿，不影响线上玩家；
#   · 只有「套用」才逐个键写配置、逐键记审计（于是套错了还能一条条撤回来）；
#   · 一个文件存两页：`{"weekly": {名字: {…}}, "pvp": {…}}`（见 m04000 的确认）。
TEMPLATES_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "templates.json")
_TEMPLATE_NAME_MAX = 40


def _template_name(raw):
    """模板名 -> (干净的名字, 错误码)。挡住控制字符：名字要进界面和日志。"""
    if not isinstance(raw, str):
        return None, "bad-name"
    name = raw.replace("\r", " ").replace("\n", " ").strip()
    if not name or len(name) > _TEMPLATE_NAME_MAX:
        return None, "bad-name"
    if any(ord(ch) < 32 for ch in name):
        return None, "bad-name"
    return name, None


def _templates_read():
    """-> {页: {名字: {saved_at, saved_iso, values}}}；文件坏了当成空表（不抛）。"""
    try:
        with open(TEMPLATES_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for page, group in data.items():
        if not isinstance(group, dict):
            continue
        keep = {}
        for name, node in group.items():
            if isinstance(node, dict) and isinstance(node.get("values"), dict):
                keep[str(name)] = {"saved_at": int(node.get("saved_at") or 0),
                                   "saved_iso": str(node.get("saved_iso") or ""),
                                   "values": node["values"]}
        out[str(page)] = keep
    return out


def _templates_write(data):
    """原子写回。-> 错误码 or None。"""
    try:
        os.makedirs(os.path.dirname(TEMPLATES_PATH), exist_ok=True)
        tmp = TEMPLATES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2, sort_keys=True)
            fp.write("\n")
        os.replace(tmp, TEMPLATES_PATH)
    except OSError as exc:
        print("[templates] 存不进去：%r" % (exc,), flush=True)
        return "save-failed"
    return None


def templates_for(page=None):
    """给界面用的模板清单（**不带 values**，只有名字和时间）。"""
    data = _templates_read()
    out = {}
    for pid in _PAGE_HOOKS:
        if page and pid != page:
            continue
        group = data.get(pid, {})
        out[pid] = [{"name": name, "saved_at": node["saved_at"], "saved_iso": node["saved_iso"]}
                    for name, node in sorted(group.items(),
                                             key=lambda kv: (-kv[1]["saved_at"], kv[0]))]
    return out


def admin_templates(page=None):
    """GET /__api/admin/templates 的载荷：有哪些页、各页有哪些模板、当前生效值。"""
    if page and page not in _PAGE_HOOKS:
        return None, "bad-page"
    pages = [{"id": pid, "label": hook["label"], "keys": list(hook["keys"])}
             for pid, hook in _PAGE_HOOKS.items() if not page or pid == page]
    current = {pid: hook["values"]() for pid, hook in _PAGE_HOOKS.items()
               if not page or pid == page}
    return {"pages": pages, "templates": templates_for(page), "current": current}, None


def admin_template_save(page, name, values=None):
    """存模板：不给 values 就取**当前生效值**（界面上的「存为模板」）。-> (结果, 错误码)。"""
    hook = _PAGE_HOOKS.get(page)
    if hook is None:
        return None, "bad-page"
    name, err = _template_name(name)
    if err:
        return None, err
    if values is None:
        values = hook["values"]()
    elif not isinstance(values, dict):
        return None, "bad-request"
    # 只留这一页管得着的键：模板里混进来的旧键直接丢掉，不当错误。
    values = {k: values[k] for k in hook["keys"] if k in values}
    data = _templates_read()
    overwritten = name in data.get(page, {})
    data.setdefault(page, {})[name] = {"saved_at": int(time.time()),
                                       "saved_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "values": values}
    err = _templates_write(data)
    if err:
        return None, err
    return {"page": page, "name": name, "overwritten": overwritten, "values": values}, None


def admin_template_delete(page, name):
    if page not in _PAGE_HOOKS:
        return None, "bad-page"
    name, err = _template_name(name)
    if err:
        return None, err
    data = _templates_read()
    if name not in data.get(page, {}):
        return None, "not-found"
    del data[page][name]
    err = _templates_write(data)
    if err:
        return None, err
    return {"page": page, "name": name}, None


def admin_template_copy(page, name, new_name):
    """复制模板：把源模板的**快照值**另存一份。列模板时不下发 values（列表要轻），
    所以「复制」只能由服务端读源份来存。-> (结果, 错误码)。"""
    if page not in _PAGE_HOOKS:
        return None, "bad-page"
    name, err = _template_name(name)
    if err:
        return None, err
    new_name, err = _template_name(new_name)
    if err:
        return None, err
    data = _templates_read()
    src = data.get(page, {}).get(name)
    if src is None:
        return None, "not-found"
    if new_name in data[page]:
        return None, "exists"
    values = dict(src.get("values") or {})
    # 副本是新快照，saved_at 记此刻；值本身照抄。
    data[page][new_name] = {"saved_at": int(time.time()),
                            "saved_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "values": values}
    err = _templates_write(data)
    if err:
        return None, err
    return {"page": page, "name": new_name, "was": name, "values": values}, None


def admin_template_rename(page, name, new_name):
    if page not in _PAGE_HOOKS:
        return None, "bad-page"
    name, err = _template_name(name)
    if err:
        return None, err
    new_name, err = _template_name(new_name)
    if err:
        return None, err
    data = _templates_read()
    if name not in data.get(page, {}):
        return None, "not-found"
    if new_name in data[page]:
        return None, "exists"
    # 改名**不动** saved_at/saved_iso：改的是名字，快照还是那份快照。
    data[page][new_name] = data[page].pop(name)
    err = _templates_write(data)
    if err:
        return None, err
    return {"page": page, "name": new_name, "was": name}, None


def admin_template_apply(page, name, parts="all"):
    """套用模板：`parts="all"` 整页、`"rewards"` 只套奖励方案。-> (结果, 错误码)。

    ★ 走的是与界面手改**同一条**校验+审计路径（`hook["apply"]`），所以套模板改错了
      照样能一条条撤销，不需要第二套回滚逻辑。
    """
    hook = _PAGE_HOOKS.get(page)
    if hook is None:
        return None, "bad-page"
    name, err = _template_name(name)
    if err:
        return None, err
    parts = str(parts or "all")
    if parts not in ("all", "rewards"):
        return None, "bad-parts"
    node = _templates_read().get(page, {}).get(name)
    if node is None:
        return None, "not-found"
    keys = set(hook["keys"]) if parts == "all" else set(hook["reward_keys"])
    fields = {k: v for k, v in node["values"].items() if k in keys}
    if not fields:
        return None, "empty"
    res, err = hook["apply"](fields)
    if res is None:
        return None, err
    return {"page": page, "name": name, "parts": parts, **res}, None


def _param_message(err):
    """错误码 -> 给人看的中文（界面直接把这句话显示出来）。"""
    err = str(err or "")
    if err.startswith("range:"):
        parts = err.split(":")
        return "%s 只能填 %s" % (parts[1], parts[2] if len(parts) > 2 else "")
    if err.startswith("bad-pool:"):
        return "%s 的奖励池子编号只能是 1..15" % err.split(":", 1)[1]
    if err.startswith("bad-tier:"):
        return "没有这个档位：%s（只有 %s）" % (err.split(":", 1)[1], "/".join(_WEEKLY_TROPHIES))
    if err.startswith("unknown-key:"):
        return "不认识的参数：%s" % err.split(":", 1)[1]
    if err.startswith("bad-value:"):
        return "这个参数要填整数：%s" % err.split(":", 1)[1]
    if err.startswith("bad-reward-item:"):
        return ("奖励物品只能选金币（1）/ 钻石（2）/ 特殊奖励（145），"
                "收到的是 %s" % err.split(":", 1)[1])
    if err.startswith("dup-special:"):
        return "第 %s 名的特殊奖励写了两遍（客户端会发两次，请删掉一条）" % err.split(":", 1)[1]
    if err.startswith("bad-bike:"):
        return ("没有 %s 号车（车号见界面下拉，1..19）。填不存在的车号客户端拿不到这台车，"
                "加载关卡时会崩" % err.split(":", 1)[1])
    if err.startswith("bad-special:"):
        return ("奖励编号 %s 在物品表里查不到（server/admin/items.json 的 rewards），游戏解析不出来。"
                "编号请从下拉里选" % err.split(":", 1)[1])
    return {"bad-request": "请求不合法",
            "bad-page": "没有这一页",
            "bad-name": "模板名不能为空或带换行，最长 %d 个字" % _TEMPLATE_NAME_MAX,
            "not-found": "找不到这个模板",
            "exists": "已经有同名的模板了",
            "bad-parts": "套用范围只能是 all（整页）或 rewards（只奖励）",
            "bad-action": "不认识这个操作",
            "bad-reward-ids": "奖励池子要写成 {档位: [池子编号]}",
            "empty": "这个模板里没有这一页认识的参数",
            "save-failed": "模板文件写不进去（看服务器日志）",
            "bad-pipe": "赛季名里不能有竖线 |（客户端只显示第一个 | 后面的部分）",
            "bad-banner": "横幅路径要写成 /pvp_banner/xxx.png（图片放 server/data/banner/）",
            "bad-stars": "星章表要正好 25 格整数（每格 0..100）",
            "bad-rewards": "奖励表要写成 [{名次, 物品, 数量}]（名次 0..25）",
            "bad-products": "礼包要写成 [{product_id, 数量}]",
            }.get(err, "改不动：" + err)


# ── 碉堡（PVP 运营）后台 ──────────────────────────────────────────────────
# ★ 字段表是唯一事实来源：服务器拿它校验、WebUI 拿它画输入框。加一个参数 =
#   在 `_BUNKER_FIELDS` 里加一行（界面不用动）。
#   标签是中英双语写在表里的，**不是** i18n.json —— 那里面只放静态界面文案，
#   而且前台约定不许动态拼 t() 的 key（tests 的 FeatureInvariants 盯着）。
# kind 决定控件：int/float/bool = 数字与开关、text = 单行文本、banner = 图片路径、
#   ids = 赛道编号多选、stars = 星章表（25 格）、rewards = 赛季奖励表、
#   products = 礼包表。
# ★ 故意**不**暴露的死键：`season.track_id`、`matchmaking.bot_name`（代码里没有
#   任何地方读它们，摆到界面上等于骗运营）。


def _bf(card, key, kind, lo, hi, cn, en, hint_cn="", hint_en=""):
    """一条碉堡参数。`key` 用 "段.键"（= 配置路径），text/banner 的 hi 是长度上限。"""
    return {"card": card, "key": key, "kind": kind, "min": lo, "max": hi,
            "cn": cn, "en": en, "hint_cn": hint_cn, "hint_en": hint_en}


_BUNKER_CARDS = (
    ("now", "现状", "Status"),
    ("season", "赛季", "Season"),
    ("duration", "对局时长", "Match duration"),
    ("rank", "段位与星章", "Ranks & stars"),
    ("match", "匹配与 AI", "Matchmaking & AI"),
    ("chips", "筹码与曲线", "Chips & curve"),
    ("rewards", "赛季奖励", "Season rewards"),
    ("templates", "模板", "Templates"),
)

_BUNKER_FIELDS = (
    _bf("duration", "matchmaking.match_duration_seconds", "int", 60, 2592000,
        "排位对局时长（秒）", "Ranked match duration (s)",
        "只影响改动之后新开的局：进行中的局在开赛时就把时长发给客户端了。",
        "Only affects matches created after the change."),
    _bf("duration", "matchmaking.friendly_match_duration", "int", 60, 2592000,
        "友军对局时长（秒）", "Friendly match duration (s)",
        "原来写死在代码里的 3600，现在能改。", "Was hardcoded to 3600."),
    _bf("season", "season.duration_days", "int", 1, 365,
        "赛季长度（天）", "Season length (days)",
        "届号按「开服以来的天数」推导：改长度会让届号重新对齐，只影响之后的届。",
        "The season number derives from elapsed days; affects future seasons only."),
    _bf("season", "season.display_offset", "int", -1000000, 1000000,
        "显示编号偏移", "Display number offset",
        "只改客户端看到的届号：想让它显示「第 1 赛季」就填 -(现在内部第几届 - 1)。"
        "内部届号、窗口起止、玩家档案全都不动。",
        "Only changes the number clients see; internal id and window stay put."),
    _bf("season", "season.advance", "int", 0, 999,
        "推进计数", "Advance counter",
        "「推进到下一赛季」每按一次 +1：本届窗口整体往前挪一轮，玩家下次进碉堡时"
        "按旧届结算并复位段位。", "Incremented by the advance-season button."),
    _bf("season", "season.title_text", "text", 0, 60,
        "赛季名", "Season title",
        "原样显示、不走翻译。★ 不能含竖线 | —— 客户端只显示第一个 | 后面的部分。",
        "Shown verbatim. Must not contain '|'."),
    _bf("season", "season.banner_path", "banner", 0, 80,
        "横幅图片路径", "Banner image path",
        "★ 换图必须换路径：客户端按 URL 的 hash 判缓存。把 PNG 放进 "
        "server/data/banner/ 再把这里指过去，就能用自己的图。",
        "Changing the image requires changing the path."),
    _bf("rank", "season.star_array", "stars", 0, 100,
        "升阶星章表（25 档）", "Stars per rank (25 cells)",
        "第 1 格 = rank 1（最高），第 25 格 = rank 25（最低）。每格 0..100。",
        "Cell 1 = rank 1 (highest); each cell 0..100."),
    _bf("rewards", "season.rewards", "rewards", 0, 0,
        "赛季奖励表", "Season rewards",
        "金币/钻石的「数量」就是发多少；特殊奖励的「数量」是原表 RewardID（下拉里挑）。"
        "★ 金额是**每档增量**：客户端会把名次 R 及以上的档位累加起来发。",
        "Amounts are per-rank increments; the client sums rank R and above."),
    _bf("rewards", "season.product_list", "products", 0, 0,
        "礼包（商城商品）", "Bundles (store products)",
        "product_id 是商城商品 id（chip_shop.goldentickets = 金票）。原表里没有的 id "
        "客户端会静默忽略。", "Unknown product ids are silently ignored by the client."),
    _bf("chips", "season.chip_equation_x", "float", 0, 10,
        "筹码曲线 x", "Chip curve x",
        "筹码 = pow(经过的秒数, x) × y。x=0 是固定总量（不随时间涨），x=1 才是线性。",
        "chips = pow(elapsed, x) * y; x=0 gives a flat total."),
    _bf("chips", "season.chip_equation_y", "float", 0, 1000000,
        "筹码曲线 y", "Chip curve y", "见 x 的说明。", "See x."),
    _bf("rank", "matchmaking.start_rank", "int", 1, 25,
        "起始段位", "Starting rank",
        "25 = 最低。0 = 传奇，不能当新号初始值（晋级动画永远不触发）。",
        "25 = lowest. Never 0: the promotion animation would never fire."),
    _bf("match", "matchmaking.enabled", "bool", 0, 1,
        "匹配总开关", "Matchmaking master switch",
        "关掉后所有匹配请求都不放行（调试用）。", "Off blocks every matchmaking request."),
    _bf("match", "matchmaking.bot_wait_seconds", "int", 0, 3600,
        "等真人多久后放 AI（秒）", "Wait before a bot joins (s)",
        "排队超过这么多秒就塞一个 AI 进来。", "A bot joins after this long in the queue."),
    _bf("match", "matchmaking.active_window_seconds", "int", 0, 86400,
        "在线判定窗口（秒）", "Online window (s)",
        "多久没请求就算离线。", "How long after the last request a player counts as offline."),
    _bf("match", "matchmaking.search_ttl_seconds", "int", 0, 86400,
        "排队条目过期（秒）", "Queue entry TTL (s)",
        "排队条目放太久就清掉。", "Stale queue entries are dropped."),
    _bf("match", "matchmaking.track_ids", "ids", 1, 1000000,
        "固定赛道", "Fixed tracks",
        "填了就每局固定用这几条（一局最多 3 条，多的会被丢掉；留空 = 每局随机）。",
        "One match uses up to 3 tracks; empty = random."),
    _bf("match", "matchmaking.candidate_tracks", "ids", 1, 1000000,
        "候选赛道池", "Candidate track pool",
        "随机时从这个池里抽 3 条。必须是幽灵库里真有幽灵的赛道，否则 AI 成绩会很假。",
        "3 tracks are sampled from this pool."),
    _bf("match", "matchmaking.track_id", "int", 0, 1000000,
        "兜底赛道", "Fallback track",
        "上面两个都空的时候用它。", "Used when both lists above are empty."),
    _bf("match", "matchmaking.bot_time_margin_pct", "float", 0.5, 10,
        "AI 成绩倍率", "Bot time multiplier",
        "AI 成绩 = 玩家成绩 × 倍率 + 毫秒数。★ 要 ≥ 1，否则 AI 比玩家快，"
        "客户端会把赛道判给 AI。",
        "Must be >= 1, otherwise the bot beats the player."),
    _bf("match", "matchmaking.bot_time_margin_ms", "int", -600000, 600000,
        "AI 成绩增减（毫秒）", "Bot time delta (ms)", "", ""),
    _bf("match", "matchmaking.bike_random", "bool", 0, 1,
        "按赛道级别随机发车", "Random bike per track tier",
        "开（默认，原版行为）：每条赛道按自己的车辆级别（图 1 级 = 1 级车…）从**这个玩家"
        "已拥有**的剧情车里随机发一台；玩家没有那个级别的车就换一张有车的图。"
        "关：全部赛道都发下面那台固定车（老行为）。",
        "On: each track gets a random bike of its own tier, picked from the player's own "
        "story bikes; tracks whose tier the player cannot field are swapped out. Off: the "
        "fixed bike below."),
    _bf("match", "matchmaking.bike_story_only", "bool", 0, 1,
        "随机池只放剧情车", "Story bikes only in the pool",
        "开（默认）：随机池只有剧情里能拿到的 9 台（犰狳…幽灵），这是最安全的范围。"
        "关：把 KTM、月球车、毛驴等非剧情车也放进池子（255 级特殊车算单独一档）。",
        "On: only the 9 story bikes. Off: also shop/DLC bikes."),
    _bf("match", "matchmaking.bike_id", "int", 1, 64,
        "固定车辆", "Fixed bike",
        "只在「按赛道级别随机发车」关掉时用（开着时它只是随机不出车时的兜底）。"
        "★ 不能填 0：客户端拿到空车再解引用，直接崩。"
        "★ 关掉随机后这台车要能跑每张图（车级别 = 图的级别，或车是 255 级特殊车），"
        "否则客户端判为不符。", "Only used when random bike assignment is off."),
    _bf("match", "matchmaking.ranked_match_slots", "int", 0, 8,
        "并行对局槽", "Parallel match slots",
        "同时能开几局。", "How many matches a player can keep open."),
    _bf("match", "matchmaking.ranked_match_limit", "int", 0, 99,
        "排位局上限", "Ranked match limit", "", ""),
    _bf("match", "matchmaking.additional_match_cost", "int", 0, 99,
        "加时局金票价", "Extra match ticket cost", "", ""),
    _bf("match", "matchmaking.free_tickets_initial", "int", 0, 99,
        "新玩家送票", "Free tickets on join", "", ""),
    _bf("match", "matchmaking.free_tickets_max", "int", 0, 99,
        "免费票上限", "Free ticket cap", "", ""),
    _bf("match", "matchmaking.free_tickets_interval_seconds", "int", 0, 604800,
        "免费票恢复间隔（秒）", "Free ticket refill (s)", "", ""),
    _bf("match", "matchmaking.bot_profile_id", "text", 0, 40,
        "AI 用哪个档案", "Bot profile id",
        "空 = 用内置的 GhostRider。", "Empty = the built-in GhostRider."),
    _bf("chips", "chips.start", "int", 0, 10000000,
        "起始筹码", "Starting chips", "", ""),
    _bf("chips", "chips.per_track_seconds", "int", 0, 1000000,
        "每条赛道产币周期（秒）", "Chip gain period (s)",
        "0 = 关闭挂机产币（现在就是关的）。填 3600 = 每小时每条赛道回一批。",
        "0 disables idle chip farming."),
    _bf("chips", "chips.max", "int", 0, 10000000,
        "筹码上限", "Chip cap", "0 = 不设上限。", "0 = no cap."),
    _bf("chips", "chips.match_loser_keeps_pct", "int", 0, 100,
        "败方保留比例（%）", "Loser keeps (%)", "", ""),
)

_BUNKER_KEYS = tuple(f["key"] for f in _BUNKER_FIELDS)
_BUNKER_REWARD_KEYS = ("season.rewards", "season.product_list")
_BUNKER_BY_KEY = {f["key"]: f for f in _BUNKER_FIELDS}
_BUNKER_STARS = 25                    # 客户端能读 26 格，我们按 25 档存


class _BadParam(Exception):
    """参数没通过校验；`code` 交给 `_param_message()` 翻成人话。"""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def _bunker_rewards_read():
    """赛季奖励表的**扁平**读法（编辑器用）：配置里怎么写就怎么读，只清洗类型。

    跟 `_pvp_season_rewards()`（下发用的分组/补档/去重）分开：这里是给人看的原始表。
    """
    vals = cfg("season", "rewards", default=None) or []
    out = []
    for it in vals:
        if not isinstance(it, dict):
            continue
        try:
            out.append({"rank": int(it.get("rank")), "item_id": int(it.get("item_id")),
                        "amount": int(it.get("amount", 1))})
        except (TypeError, ValueError):
            continue
    return out


def _bunker_get(key):
    """当前生效值（配置合并后的结果；缺的补代码默认值）。"""
    sec, k = key.split(".", 1)
    if k == "star_array":
        return _pvp_star_array()
    if k == "rewards":
        return _bunker_rewards_read()
    if k == "product_list":
        return _pvp_product_list()
    raw = cfg(sec, k, default=None)
    if raw is None:
        return _bunker_default(key)
    return raw


def _bunker_default(key):
    sec, k = key.split(".", 1)
    return (_TF_CONFIG_DEFAULTS.get(sec) or {}).get(k)


def _bunker_check(spec, raw):
    """校验并归一化一个值；不合法就抛 `_BadParam`。"""
    key, kind = spec["key"], spec["kind"]
    lo, hi = spec["min"], spec["max"]
    if kind == "rewards":
        return _bunker_rewards_check(raw)
    if kind == "products":
        return _bunker_products_check(raw)
    if kind == "stars":
        if not isinstance(raw, (list, tuple)) or not _BUNKER_STARS <= len(raw) <= _BUNKER_STARS + 1:
            raise _BadParam("bad-stars")
        out = []
        for v in raw:
            if isinstance(v, bool):
                raise _BadParam("bad-stars")
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise _BadParam("bad-stars")
            if not lo <= iv <= hi:
                raise _BadParam("range:%s:%s-%s" % (key, lo, hi))
            out.append(iv)
        return out[:_BUNKER_STARS]
    if kind == "ids":
        if raw is None or raw == "":
            return []
        if not isinstance(raw, (list, tuple)):
            raise _BadParam("bad-value:" + key)
        out = []
        for v in raw:
            if isinstance(v, bool):
                raise _BadParam("bad-value:" + key)
            try:
                iv = int(str(v).strip() if isinstance(v, str) else v)
            except (TypeError, ValueError):
                raise _BadParam("bad-value:" + key)
            if not lo <= iv <= hi:
                raise _BadParam("range:%s:%s-%s" % (key, lo, hi))
            if iv not in out:
                out.append(iv)
        return out[:3] if key == "matchmaking.track_ids" else out
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        if isinstance(raw, str) and raw.strip() in ("0", "1", "true", "false"):
            return raw.strip() in ("1", "true")
        raise _BadParam("bad-value:" + key)
    if kind in ("text", "banner"):
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raise _BadParam("bad-value:" + key)
        val = raw.strip()
        if len(val) > hi or "\n" in val or "\r" in val:
            raise _BadParam("range:%s:0-%s" % (key, hi))
        if key == "season.title_text" and "|" in val:
            raise _BadParam("bad-pipe")
        if kind == "banner" and val:
            if not (val.startswith("/pvp_banner/") and val.endswith(".png")):
                raise _BadParam("bad-banner")
        return val
    # int / float
    if isinstance(raw, bool):
        raise _BadParam("bad-value:" + key)
    try:
        val = float(raw) if kind == "float" else int(str(raw).strip() if isinstance(raw, str) else raw)
        if kind == "int" and isinstance(raw, float) and raw != int(raw):
            raise ValueError
    except (TypeError, ValueError):
        raise _BadParam("bad-value:" + key)
    if not lo <= val <= hi:
        raise _BadParam("range:%s:%s-%s" % (key, lo, hi))
    # 车号要真存在：`1..64` 只是形状，填 40 号客户端 `getBike(40)` 拿不到车 → 崩。
    # 车表读不到（没建 items.json）时不拦，宁可放行也不要因为缺表全站改不动。
    if key == "matchmaking.bike_id":
        catalog = bike_catalog()
        if catalog and val not in catalog:
            raise _BadParam("bad-bike:%d" % val)
    return val


def _bunker_rewards_check(raw):
    """赛季奖励表：整表替换。金币/钻石同档相加；特殊奖励同档重复直接报错。"""
    if not isinstance(raw, (list, tuple)) or not raw:
        raise _BadParam("bad-rewards")
    if len(raw) > 200:
        raise _BadParam("bad-rewards")
    acc = {}
    for row in raw:
        if not isinstance(row, dict):
            raise _BadParam("bad-rewards")
        if isinstance(row.get("rank"), bool) or isinstance(row.get("item_id"), bool):
            raise _BadParam("bad-rewards")
        try:
            rank = int(row.get("rank"))
            item = int(row.get("item_id"))
            amt = int(row.get("amount"))
        except (TypeError, ValueError):
            raise _BadParam("bad-rewards")
        if not 0 <= rank <= 25:
            raise _BadParam("range:season.rewards(名次):0-25")
        if item not in (1, 2, 145):
            raise _BadParam("bad-reward-item:%d" % item)
        if item == 145:
            known = _known_reward_ids()
            if known and amt not in known:
                # 只挡「物品表里根本没有的编号」—— 那种编号游戏一定解析不出来。
                # 表外的编号（不在官方 43 个里）**放行**：显示什么由玩家有没有该物品决定。
                raise _BadParam("bad-special:%d" % amt)
        if not 0 <= amt <= 1000000000:
            raise _BadParam("range:season.rewards(数量):0-1000000000")
        if (rank, item) in acc:
            if item == 145:
                # 客户端会把两条都发出去（`getCombinedSeasonRewards` 是纯累加）
                raise _BadParam("dup-special:%d" % rank)
            acc[(rank, item)] += amt
        else:
            acc[(rank, item)] = amt
    return [{"rank": r, "item_id": i, "amount": a} for (r, i), a in sorted(acc.items())]


def _bunker_products_check(raw):
    """礼包表：`[{"product_id": str, "amount": int}]` 整表替换。"""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) > 20:
        raise _BadParam("bad-products")
    out = []
    for row in raw:
        if not isinstance(row, dict):
            raise _BadParam("bad-products")
        pid = row.get("product_id")
        if not isinstance(pid, str) or not pid.strip() or len(pid.strip()) > 60:
            raise _BadParam("bad-products")
        if isinstance(row.get("amount"), bool):
            raise _BadParam("bad-products")
        try:
            amt = int(row.get("amount", 1))
        except (TypeError, ValueError):
            raise _BadParam("bad-products")
        if not 0 <= amt <= 1000000:
            raise _BadParam("range:season.product_list(数量):0-1000000")
        out.append({"product_id": pid.strip(), "amount": amt})
    return out


def bunker_values():
    """碉堡页的「当前生效值」（模板存的也是这个扁平结构）。只读。"""
    return {key: _bunker_get(key) for key in _BUNKER_KEYS}


def admin_bunker_apply(fields):
    """碉堡页写入：`fields = {"season.duration_days": 30, …}`（列表类整表替换）。

    -> (结果, 错误码)。跟午夜杯一样**先全部校验、再动手**。
    错误码：bad-request / unknown-key:<k> / bad-value:<k> / range:<k>:<lo>-<hi> /
            bad-pipe / bad-banner / bad-stars / bad-rewards / bad-reward-item:<i> /
            dup-special:<rank> / bad-products
    """
    if not isinstance(fields, dict) or not fields or len(fields) > len(_BUNKER_FIELDS) + 4:
        return None, "bad-request"
    ops = []
    for raw_key, raw_val in fields.items():
        key = str(raw_key)
        spec = _BUNKER_BY_KEY.get(key)
        if spec is None:
            return None, "unknown-key:" + key
        if raw_val is None and spec["kind"] in ("int", "float"):
            ops.append((key, key.split(".", 1), None))     # 清空数字框 = 删掉这个键，回到代码默认值
            continue
        try:
            val = _bunker_check(spec, raw_val)
        except _BadParam as exc:
            return None, exc.code
        ops.append((key, key.split(".", 1), val))
    applied = []
    for key, path, val in ops:
        before = _bunker_get(key)
        if val is None:
            _, existed = cfg_unset(path, kind="bunker")
            if not existed:                  # 本来就是默认值，没什么可撤的
                applied.append({"key": key, "before": before, "after": before, "audit": None})
                continue
        else:
            cfg_set(path, val, kind="bunker")
        applied.append({"key": key, "before": before, "after": _bunker_get(key),
                        "audit": _latest_audit_id(path)})
    return {"applied": applied, "values": bunker_values()}, None


_BUNKER_CATALOG = {"mtime": None, "specials": []}

# 客户端的赛季特殊奖励表：原表 `/conf/pvp_match_rewards.txt` 的 PVPMatchSpecialRewards，
# 7 组共 43 个编号（名字是组里那个 Comment）。★ 这 43 个是**客户端的固定表**，
# 服务端改不了；但「填了别的编号就变毛驴轮胎」这条因果 2026-10-06 被真机实验推翻
# （真因是「玩家已经拥有该物品 ⇒ 显示它自带的兜底奖励」，见
# `work/trials-frontier/notes/pvp-reward-contract.md` §5d）。所以现在：
#   · 奖励编号**都能填**（只挡物品表里查不到的编号）；
#   · 界面把官方 43 个标出来，用了表外编号时给一条提示，不再拒收。
_PVP_SPECIAL_GROUPS = (
    ("Crafting Item Tier 2", "零件 · 档位 2",
     (20003, 20008, 20013, 20018, 20023, 20028, 20033, 20038, 20043, 20048)),
    ("Crafting Item Tier 3", "零件 · 档位 3",
     (20002, 20007, 20012, 20017, 20022, 20027, 20032, 20037, 20042, 20047)),
    ("Soylent Bike Skin", "涂装 · Soylent（Tango*）", (202,)),
    ("Luchador Bikeskin", "涂装 · Luchador（Bronco）", (203,)),
    ("Donkey Blueprint", "蓝图 · 毛驴图纸", (220,)),
    ("Crafting Item Tier 4", "零件 · 档位 4",
     (20001, 20006, 20011, 20016, 20021, 20026, 20031, 20036, 20041, 20046)),
    ("Crafting Item lvl 5", "零件 · 档位 5",
     (20000, 20005, 20010, 20015, 20020, 20025, 20030, 20035, 20040, 20045)),
)
_PVP_SPECIAL_IDS = frozenset(i for _, _, ids in _PVP_SPECIAL_GROUPS for i in ids)

# 奖励编号（`items.json` 的 `rewards`）按类别分组给下拉用，顺序 = 运营最常发的排前面。
_REWARD_CAT_CN = {"parts": "零件", "blueprint": "蓝图", "outfit": "服装", "track": "赛道",
                  "consumable": "消耗品", "other": "其它（涂装/皮肤）", "coin": "金币",
                  "gem": "钻石", "special": "特殊"}
_REWARD_CAT_ORDER = ("parts", "blueprint", "outfit", "track", "consumable", "other",
                     "coin", "gem", "special")


def _bunker_catalogs():
    """`items.json` 派生的奖励编号下拉：**全部**编号（`official` 标出官方 43 个）。

    ★ 以前这里只放官方 43 个、服务端也硬拦别的编号。2026-10-06 的真机实验推翻了那条
      因果（见 `work/trials-frontier/notes/pvp-reward-contract.md` §5d）：**显示什么由
      「玩家有没有这件物品」决定** —— 没有就画真图标，已经有就画该编号自带的兜底奖励
      （大多是「毛驴轮胎」甜甜圈）。表外编号游戏解析不出来，也可能一直是兜底物，
      所以只**提示**、不再拦。
    ★ 车辆下拉不再从这里派生（旧版拿 `paints[].bike` 凑出 17 台、还没有中文名）：
      现在直接用 `bike_catalog()`（`/conf/bikes.txt` 的 19 台，带级别）。
    """
    try:
        stamp = os.path.getmtime(_TRACK_CATALOG_PATH)
    except OSError:
        return []
    if _BUNKER_CATALOG["mtime"] == stamp:
        return _BUNKER_CATALOG["specials"]
    rewards = []
    try:
        with open(_TRACK_CATALOG_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        for raw_id, node in (data.get("rewards") or {}).items():
            if not isinstance(node, dict):
                continue
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                continue
            cat = str(node.get("cat") or "other")
            rewards.append({"id": rid, "cat": cat,
                            "cat_cn": _REWARD_CAT_CN.get(cat, cat),
                            "name": node.get("name") or "",
                            "name_cn": node.get("cn") or node.get("name") or "",
                            "item_id": node.get("item_id"), "type": node.get("type"),
                            "official": rid in _PVP_SPECIAL_IDS})
        rewards.sort(key=lambda r: (_REWARD_CAT_ORDER.index(r["cat"])
                                    if r["cat"] in _REWARD_CAT_ORDER else len(_REWARD_CAT_ORDER),
                                    r["id"]))
    except (OSError, ValueError, AttributeError):
        return []
    if rewards:
        _BUNKER_CATALOG.update(mtime=stamp, specials=rewards)
    return rewards


def _known_reward_ids():
    """物品表（`items.json` 的 `rewards`）里所有奖励编号。表读不到就返回空集合 = 不拦。"""
    return frozenset(r["id"] for r in _bunker_catalogs())


def bunker_audit(limit=30):
    """碉堡页管着的三段（season/matchmaking/chips）最近被改了什么。"""
    secs = ("season", "matchmaking", "chips")
    out = []
    for rec in audit_log(AUDIT_KEEP):
        path = rec.get("path") or []
        if path and path[0] in secs:
            out.append(rec)
            if len(out) >= max(1, int(limit)):
                break
    return out


def admin_bunker_status():
    """碉堡「现状卡」：届号/窗口、玩家档案、对局与队列、票与筹码池、警示。只读。"""
    sid, start, end = _pvp_season_window()
    now = int(time.time())
    players = []
    for pid in sorted(_pvp_players):
        st = _pvp_players.get(pid) or {}
        players.append({"profile": pid, "rank": st.get("rank"), "star": st.get("star"),
                        "season": st.get("season"), "this_season": st.get("season") == sid,
                        "golden_ticket": st.get("golden_ticket"),
                        "win_streak": st.get("win_streak"), "chips": _pvp_chips_for(pid)})
    tickets = [{"profile": p, "tickets": (st or {}).get("tickets")}
               for p, st in sorted(_pvp_tickets.items())]
    matches = [{"id": mid, "players": m.get("players"), "track": m.get("track"),
                "bot": m.get("bot"), "age": now - m.get("at", now)}
               for mid, m in sorted(_pvp_matches.items())]
    queue = [{"profile": p, "waited": now - (e.get("at", now) if isinstance(e, dict)
                                             else int(e or now))}
             for p, e in _pvp_search.items()]
    win = cfg_int("matchmaking", "active_window_seconds", default=300) or 300
    active = [{"profile": p, "seen_ago": now - ts}
              for p, ts in sorted(ACTIVE_PLAYERS.items()) if now - ts <= win]
    warnings = []
    if (cfg_int("matchmaking", "match_duration_seconds", default=21600) or 0) == 300:
        warnings.append({"cn": "排位对局时长现在是 300 秒（测试值），正式玩请改回 21600（6 小时）。",
                         "en": "Ranked match duration is 300 s (a test value); use 21600 (6 h) for real play."})
    if not (cfg_int("chips", "per_track_seconds", default=0) or 0):
        warnings.append({"cn": "挂机产币是关的（每条赛道产币周期 0）：玩家自己不会涨筹码，只能靠对局赢。",
                         "en": "Idle chip farming is off (period 0): players only gain chips from matches."})
    warnings.append({"cn": "玩家的段位/星章/金票只走这个页面改；直接编辑 pvp_state.json 会被服务器下次写盘覆盖。",
                     "en": "Change player rank/star/tickets here only; editing pvp_state.json gets overwritten."})
    # 奖励表里用了官方 43 个编号之外的编号：能发，但游戏很可能画成兜底物（毛驴轮胎）。
    # 说清楚是「玩家已有该物品」优先，别让运营以为配置坏了（§5d）。
    odd = sorted({int(r.get("amount") or 0) for r in (_bunker_rewards_read() or [])
                  if int(r.get("item_id") or 0) == 145 and int(r.get("amount") or 0)
                  and int(r.get("amount") or 0) not in _PVP_SPECIAL_IDS})
    if odd:
        warnings.append({
            "cn": ("奖励表里有 %d 个编号不在官方的赛季特殊奖表（43 个）里：%s。"
                   "游戏显示什么由「玩家有没有这件物品」决定 —— 没有就画真图标，已经有了就画该编号自带的"
                   "兜底奖励（大多是「毛驴轮胎」甜甜圈）；表外编号也可能一直是兜底物。"
                   "想让它们在赛季列表里稳定显示，用「下发物品」页发更稳。"
                   % (len(odd), "、".join("#%d" % i for i in odd))),
            "en": ("%d reward id(s) are outside the client's 43 official season specials: %s. "
                   "The client draws the real icon only for items the player does NOT own; otherwise it "
                   "draws the id's own fallback (usually the Donkey Doughnut), and ids outside the client "
                   "table may always show the fallback. Use the Grant screen for those items."
                   % (len(odd), ", ".join("#%d" % i for i in odd)))})
    return {"now": now, "season": sid, "display_id": _pvp_display_season(sid),
            "duration_days": max(1, cfg_int("season", "duration_days", default=30)),
            "start": start, "end": end,
            "players": players, "matches": matches, "matches_total": len(matches),
            "queue": queue, "tickets": tickets, "active": active,
            "chips_pool": sum(p["chips"] for p in players if p["chips"]),
            "tickets_pool": sum(t["tickets"] or 0 for t in tickets),
            "warnings": warnings}


def bunker_payload():
    """碉堡页要的全部只读数据：界面照着它画，不用自己拼默认值。"""
    rewards = _bunker_catalogs()
    return {"cards": [{"id": c, "cn": cn, "en": en} for c, cn, en in _BUNKER_CARDS],
            "fields": [dict(f, default=_bunker_default(f["key"]), now=_bunker_get(f["key"]))
                       for f in _BUNKER_FIELDS],
            "values": bunker_values(),
            "status": admin_bunker_status(),
            "tracks": track_catalog(),
            "rewards": rewards,
            # 车表 = `/conf/bikes.txt` 的 19 台（带级别与「剧情车」标记）：固定车辆
            # 下拉、以及界面上解释「为什么发这台车」都用它（旧版从 paints 凑的 17 台）。
            "bikes": sorted(bike_catalog().values(), key=lambda b: b["id"]),
            "templates": templates_for("bunker").get("bunker", []),
            "audit": bunker_audit(30)}


# 页面注册表：模板 / 撤销端点靠它知道"这一页管哪些键、怎么读、怎么写"。
# （碉堡页落地时在这里加一条 "pvp" 即可，模板与撤销端点不用改。）
_PAGE_HOOKS = {
    "weekly": {
        "label": "午夜杯",
        "keys": tuple(_WEEKLY_KEYS) + ("reward_ids",),
        "reward_keys": _WEEKLY_REWARD_KEYS,
        "values": weekly_values,
        "apply": admin_weekly_apply,
    },
    "bunker": {
        "label": "碉堡",
        "keys": tuple(k for k in _BUNKER_KEYS if k not in _BUNKER_REWARD_KEYS),
        "reward_keys": _BUNKER_REWARD_KEYS,
        "values": bunker_values,
        "apply": admin_bunker_apply,
    },
}


def h_liveevents_accept(path, query, body, headers):
    """weekly_track_system 里那几个 POST（start_race / end_race / skip_cooldown /
    refill_retry_count / last_week_data …）的宽容接收端。

    为什么可以只回 `{"data": []}`：
      · 这些请求走 `OnlineCore::postJson`（POST + JSON body），
      · 响应 cmd 落在 0x7a–0x7e，`OnlineWeeklyChallenge::parseJsonResponse`
        的跳转表把这一段全部指向 **0x5053d8**，而那里只有函数收尾（ret/析构），
        **一个字节都不解析**——客户端只关心 HTTP 成功。
    请求体（.rodata 常量，反汇编已确认，逗号后带空格）：
      start_race       {"gem":%s,"checksum":"%s","timestamp":%u, "restart":%s}
      end_race         {"score":%u,"checksum":"%s","timestamp":%u}
      skip_cooldown    {"gem":%s,"skiptimer":%s,"checksum":"%s","timestamp":%u}
      refill_retry_count {"checksum":"%s","retry_times":"%d","timestamp":%u}
    checksum 是客户端算的 MD5（`OnlineChecksum::calculateMD5`），我们不做校验。
    ⚠ 上传周数据（`postLastWeekData`，body 见上面 last_participated_week 那条）
      **不是独立端点**：它的 URL 也是 basic_info（反汇编 0x503800 `add x2,x2,#0x16c`），
      只是走 POST + cmd 0x7f。所以由 `h_liveevents_basic_info` 一并覆盖。
    """
    b = _json_body(body)
    pid = _caller_profile(headers)
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    # 比赛次数（服务端权威）：start_race 扣一次、skip_cooldown 补满、
    # refill_retry_count 按客户端报的 retry_times 加次数（见 _weekly_attempt_state）。
    if tail == "start_race":
        st = _weekly_attempt_state(pid)
        if _weekly_left(pid) > 0:
            st[1] += 1
            st[3] = int(time.time())
            print("[liveevent] start_race pid=%s 用掉第 %d 次，剩 %d" %
                  (pid, st[1], _weekly_left(pid)), flush=True)
        else:
            print("[liveevent] start_race pid=%s 次数已用完（未扣）" % pid, flush=True)
    elif tail == "skip_cooldown":
        st = _weekly_attempt_state(pid)
        st[1], st[2] = 0, 0
        print("[liveevent] skip_cooldown pid=%s -> 次数补满 %d" % (pid, _weekly_left(pid)),
              flush=True)
    elif tail == "refill_retry_count":
        try:
            extra = int(str(b.get("retry_times", 1)))
        except (TypeError, ValueError):
            extra = 1
        st = _weekly_attempt_state(pid)
        st[2] += max(1, min(9, extra))
        print("[liveevent] refill_retry_count pid=%s +%d -> 剩 %d" %
              (pid, extra, _weekly_left(pid)), flush=True)
    print("[liveevent] %s %s <- %s -> data:[]" % (path, query, b), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


# ---------------------------------------------------------------------------
# 碉堡 / PVP —— /public/pvp_matches/v1/*
#
# 请求 → (方法, URL, cmd) 全表（cmd 已逐个反汇编确认；getRequest 的 cmd 在 w3，
# postJson 的在 w4）：
#   POST pvp_init                    0x27  OnlinePVP::initMatches      @0x4f9bd8
#   POST tracks                      0x2e  submitUnlockedTracks       @0x4f9ac0
#   GET  matches/%d                  0x29  queryMatch                 @0x4f9ffc
#   GET  matches                     0x2a  queryMatches               @0x4fa118
#   GET  player/%s                   0x2b  queryPlayerRanking         @0x4fa768
#   GET  new_ranked?…                0x28  startRankedMatch           @0x4f9d88
#   POST race                        0x2d  submitMatchResult          @0x4fa528
#   GET  pvp_config?lang=%s          0x30  getSeasonData              @0x4fa9f0
#   GET  season/%d?lang=%s           0x31  getSeasonDataById          @0x4faaec
#   GET  …（2KB 缓冲，横幅）          0x32  getSeasonBanner            @0x4fabf0
#   POST increase_rewards            0x33  submitMatchRewards         @0x4faf94
#   POST chips                       0x34  spendChips                 @0x4fb1f8
#   POST close_season                0x36  closeSeason                @0x4fb994
#   GET  players?profiles=           0x37  getFriendLeaderboard       @0x4fb650
#
# 响应分派：`OnlinePVP::parseJsonResponse` @0x4fc108，跳转表 @0xb86448，
# `sub w8, cmd, #0x27; cmp w8, #0x11`。**碉堡的总闸是 cmd 0x27（pvp_init）**：
# 它的响应是一个根对象，只看三个成员键（0x4fc1c4 的循环里只有三次 json_strcmp）：
#   "player_info" @0xb86901 -> parseRankingData(node, PVPPlayerData@query+0x44)
#   "match_info"  @0xb8690d -> parseMatches(node, vector<PVPMatch>@query+0x78)
#   "pvp_config"  @0xb86918 -> parseSeason(node, PVPSeason@query+0xa0, &banner_url)
# 循环结束后 `OnlinePVPMatchQuery::resolveOpponentNames()`，随后若 banner_url 非空
# 就再拉一次 getSeasonBanner（cmd 0x32），最后回调 listener。
#
# ⚠ 客户端 JSON 解析器**不做类型检查**，一律按 32 位字从 `[node+0x28]` 读，
#   所以「对象形态不明的键」宁可**不发**（字段保持默认值），也不要发错类型。
#   `star_array` / `product_list` / `rewards` 就是这么处理的。
# ---------------------------------------------------------------------------


def _pvp_outfit_of(pid):
    """这个玩家的骑手外观（24 位 = 3 个 8 位部件），取存档 `content.profile.outfit`。

    ★ 为什么要它：对局界面（碉堡里那两张骑手立绘）由 `parseMatch` @0x4fd9d0 的
      `player1`/`player2` 槽喂数据，槽里的 `outfit` 就是**对手穿的那套**。
      原来这里发 0 → 客户端把对手画成 0 号部件（默认那套）。
      真机证据（用户 m01793 的两张截图）：华为机上两侧骑手长得一模一样（都是自己
      那套），ccb 机上是正常的骷髅白装 vs 黄盔迷彩 —— 因为 ccb 的存档
      `profile.outfit = 0x121212` 而华为的是 0，发 0 时恰好把华为画对了、把 ccb 画错。
      位布局（bits 26..31/20..25/14..19 = part0/1/2）见 `_lb_data`。
    """
    if not pid:
        return 0
    prof = ((acct.load_progress(pid) or {}).get("content") or {}).get("profile") or {}
    try:
        return int(prof.get("outfit") or 0) & 0xFFFFFF
    except (TypeError, ValueError):
        return 0


def _pvp_player_info(chips=None, tickets=3, rank=None, pid=None):
    """`parseRankingData` @0x4fc918 的响应契约（键地址已逐个确认）。

    +0x00 `rank`(0xb869b5) / +0x04 `star`(0xb86947) / +0x08 `elo_rank`(0xb869b1)
    / +0x0c `season`(0xb868e5) / +0x10 `golden_ticket`(0xb899a0)
    / +0x14 `chips`(0xb49233) / +0x18 `win_streak`(0xb86a12)。
    ⚠ 另有一个键 `elo`(0xb86a0e) 走 `ldr d0,[node+0x28]; fcvtzs`，即**值是 double**。
      它和 `elo_rank` 写同一个字段（+0x08），所以我们只发整数版的 `elo_rank`。
    `chips=None` 时取服务器记的余额（见 `_pvp_chips_for`）。
    `rank=None` 时取 `matchmaking.start_rank`（默认 25 = 最低级）。
    rank=0 是 Legend；初始 rank=25，真正晋升后允许0。
    """
    if chips is None:
        chips = cfg_int("chips", "start", default=0)
    if rank is None:
        rank = cfg_int("matchmaking", "start_rank", default=25)
    state = _pvp_player_state(pid) if pid else {}
    return {
        "rank": state.get("rank", rank),
        "star": state.get("star", 0),
        "elo_rank": 1000,
        "season": state.get("season", _pvp_season_window()[0]),
        "golden_ticket": state.get("golden_ticket", tickets),
        "chips": chips,
        "win_streak": state.get("win_streak", 0),
    }


def _pvp_season_window(season_id=None):
    duration = max(1, cfg_int("season", "duration_days", default=30)) * 86400
    if season_id is not None:
        sid = int(season_id)
    else:
        # `season.advance` 是「推进到下一赛季」按出来的偏移：届号是时间派生的，
        # 加一个整数就够（窗口由届号反推，所以推进一次 = 本届整体前移一轮）。
        adv = cfg_int("season", "advance", default=0) or 0
        sid = int(time.time()) // duration + 1 + adv
    return sid, (sid - 1) * duration, sid * duration


def _pvp_display_season(sid):
    """内部届号 -> 下发给客户端的显示编号（`season.display_offset`）。只影响那个数字。"""
    try:
        off = cfg_int("season", "display_offset", default=0) or 0
    except (TypeError, ValueError):
        off = 0
    return int(sid) + int(off)


# 新玩家初始金票数。老服务器的广告值就是 3，`_pvp_player_state()` 建新档要用，
# 后台（WebUI）在玩家还没建过 PVP 档时也要显示同一个数，所以提成常量。
_PVP_DEFAULT_GOLDEN_TICKET = 3


def _pvp_player_state(pid):
    if pid not in _pvp_players:
        _pvp_players[pid] = {
            "rank": max(1, min(25, cfg_int("matchmaking", "start_rank", default=25))),
            "star": 0, "season": _pvp_season_window()[0], "win_streak": 0,
            # Preserve the old server's advertised initial golden-ticket balance.
            "golden_ticket": _PVP_DEFAULT_GOLDEN_TICKET,
        }
        _pvp_mark_dirty()
    return _pvp_players[pid]


def _pvp_star_array():
    """`star_array` @0xb86be8 —— 扁平 int 数组，最多 26 项，`parseSeason` @0x4fd694。"""
    vals = cfg("season", "star_array", default=None)
    vals = vals if isinstance(vals, list) else []
    out = list(_TF_CONFIG_DEFAULTS["season"]["star_array"])
    for index, value in enumerate(vals[:25]):
        if type(value) is int and 0 < value <= 100:
            out[index] = value
    return out


def _pvp_product_list():
    """`product_list` @0xb86bf3 —— `[{"product_id": str, "amount": int}]`，@0x4fd230。"""
    vals = cfg("season", "product_list", default=None) or []
    out = []
    for it in vals:
        if not isinstance(it, dict):
            continue
        pid = it.get("product_id")
        if not isinstance(pid, str) or not pid:
            continue
        try:
            amt = int(it.get("amount", 1))
        except (TypeError, ValueError):
            amt = 1
        out.append({"product_id": pid, "amount": amt})
    return out


def _pvp_season_rewards():
    """`current_season.rewards` @0xb8d6de —— `parseSeasonData` @0x4fe4f4。

    配置为扁平条目，wire 按rank分组并补足0..25共26档。
    item_id=145 时 amount 是原表RewardID；不是库存物品数量。
    """
    vals = cfg("season", "rewards", default=None) or []
    out = []
    for it in vals:
        if not isinstance(it, dict):
            continue
        try:
            rk = int(it.get("rank"))
            iid = int(it.get("item_id"))
            amt = int(it.get("amount", 1))
        except (TypeError, ValueError):
            continue
        if not 0 <= rk <= 25 or not 0 <= iid <= 65535 or not 0 <= amt <= 2147483647:
            continue
        out.append({"rank": rk, "item_id": iid, "amount": amt})
    grouped = {rank: [] for rank in range(26)}
    seen = set()
    for item in out:
        key = (item["rank"], item["item_id"], item["amount"])
        if key in seen:
            # ★ 同一档、同一 item_id、同一 amount 写两遍 = 客户端收两份。真发生过
            #   （rank 5/10/15/20/25 的 item_id:145 各写重一条）。这里去重并吵一声，
            #   免得运营表里的复制粘贴变成多发的季奖；WebUI 生成的模板也走这条保护。
            print("[pvp] 季奖配置重复条目已忽略：rank=%d item_id=%d amount=%d" % key,
                  flush=True)
            continue
        seen.add(key)
        grouped.setdefault(item["rank"], []).append(
            {"item_id": item["item_id"], "amount": item["amount"]})
    return [{"rank": rank, "rewards": items} for rank, items in sorted(grouped.items())]


def _pvp_season(banner_url=""):
    """`parseSeason` @0x4fcfb4 的响应契约。

    根对象两个键：
      `pvp_match_settings` @0xb86a1d —— 内层是 22 个标量键，全部按 int 读：
        free_tickets_interval @0xb86a30 / Pvp_skill_counter @0xb86a46 /
        free_tickets_max @0xb86a58 / free_tickets_initial @0xb86a69 /
        chip_equation_x @0xb86a7e / chip_equation_y @0xb86a8e /
        winner_chip_heritage @0xb86a9e / loser_chip_heritage @0xb86ab3 /
        ranked_match_duration @0xb86ac7 / friendly_match_duration @0xb86add /
        ranked_match_slots @0xb86af5 / ranked_match_limit @0xb86b08 /
        game_mode @0xb86b1b / pvp_skill_time_bonus_seconds @0xb86b25 /
        pvp_skill_fault_punishment_factor @0xb86b42 /
        pvp_skill_decay_in_fanpoint @0xb86b64 / pvp_skill_fanpoints @0xb86b80 /
        chip_store_specials_refresh_interval_hours @0xb86b94 /
        additional_match_cost @0xb86bbf / match_price_factor @0xb86bd5
        （`star_array` @0xb86be8 / `product_list` @0xb86bf3 见 `_pvp_star_array` /
          `_pvp_product_list`，取值走 `tf_config.json` 的 `season.star_array` /
          `season.product_list`）
      `current_season` @0xb86c18 —— 交给 `parseSeasonData` @0x4fe4f4 解析：
        end_time @0xb876b2 / title_text @0xb86c55 / banner_url @0xb86c60 /
        rewards @0xb8d6de（= 天梯奖励栏，`[{"rank","item_id","amount"}]`，
        见 `_pvp_season_rewards`）/ rank @0xb869b5。
    ⚠ `banner_url` 留空字符串：非空会触发一次 `getSeasonBanner`（cmd 0x32）去下图。
    ⚠ `chip_equation_x/y` 是**筹码曲线的系数**，客户端拿它自己算筹码与「圆环填充进度」：
      `PVPManager::getNumChipsTotal(double t)` @0x5e1838 = `pow(t, x) * y`
      （x = [+0xb0], y = [+0xb4]，见 `ldp s2, s1, [x8, #0xb0]`）。
      `PVPMatch::getChipProgress(int i, double)` @0x5ed8c4 返回
      `frac(getNumChipsTotal(now - PVPTrack+0x20))` —— 就是赢家头像上那个
      **顺时针填充的圆环**（`MenuzComponentPVPTrackWidget::updateChipProgress` @0x714a68
      → 填充值下降时调 `animateChips()` @0x714b08 产出一枚筹码）。
      ★ 以前这里发 0/0 是错的（当时的判断是「t 的基准 PVPTrack+0x20 被当成车种 ID」，
        见下方历史备注）。真机 m04710 的实际症状就是**圆环永远不填充**。
      ★ 真相（`PVPTrack::setOwner` @0x5ddfa4 = `str w1,[x0,#4]; str w2,[x0,#0x20]`）：
        `PVPTrack+0x04` = owner，`PVPTrack+0x20` = **owner_change_time（unix 秒）**，
        `PVPTrack+0x24` = **车种 ID**（`onStartRaceSent` @0x5e59ec 读的是 `[track+0x24]`，
        x20 是 PVPTrack* 而不是 PVPMatch*，所以那个「车种 ID」结论属于另一个偏移）。
        两者互不冲突，可以同时发对。
      ⇒ 服务器必须发**真时间戳**的 `owner_change_time`（见 `_pvp_track_json`），
        并且 `_pvp_match_chips` 用**同一条曲线**算 `server_time` 时刻的筹码快照，
        客户端再把它从 `server_time` 外推到 `now`（`getPlayerChips` @0x5ed6f8 的
        `- floor(f(server_time)) + floor(f(now))`）。
    """
    season_id, season_start, season_end = _pvp_season_window()
    ftk_max = cfg_int("matchmaking", "free_tickets_max", default=3)
    ftk_init = cfg_int("matchmaking", "free_tickets_initial", default=ftk_max)
    ftk_iv = cfg_int("matchmaking", "free_tickets_interval_seconds", default=3600)
    _cx, _cy = _chip_curve()
    settings = {
        "free_tickets_interval": ftk_iv if ftk_iv > 0 else 3600,
        "Pvp_skill_counter": 0,
        "free_tickets_max": ftk_max if ftk_max > 0 else 3,
        "free_tickets_initial": ftk_init,
        "chip_equation_x": _cx,
        "chip_equation_y": _cy,
        # 这两个只影响赛后界面的文案（`getChipHeritage @0x5dec48` 的系数是客户端
        # 硬编码的），但文案得跟服务端真正干的事一致 ⇒ loser 直接取掠夺配置。
        "winner_chip_heritage": 100,
        "loser_chip_heritage": cfg_int("chips", "match_loser_keeps_pct", default=50),
        "ranked_match_duration": cfg_int("matchmaking", "match_duration_seconds", default=3600) or 3600,
        "friendly_match_duration": cfg_int("matchmaking", "friendly_match_duration", default=3600) or 3600,
        "ranked_match_slots": cfg_int("matchmaking", "ranked_match_slots", default=3),
        "ranked_match_limit": cfg_int("matchmaking", "ranked_match_limit", default=10),
        "game_mode": 0,
        "pvp_skill_time_bonus_seconds": 0,
        "pvp_skill_fault_punishment_factor": 1,
        "pvp_skill_decay_in_fanpoint": 0,
        "pvp_skill_fanpoints": 0,
        "chip_store_specials_refresh_interval_hours": 24,
        "additional_match_cost": cfg_int("matchmaking", "additional_match_cost", default=1),
        "match_price_factor": 1,
    }
    sa = _pvp_star_array()
    if sa:
        settings["star_array"] = sa
    pl = _pvp_product_list()
    if pl:
        settings["product_list"] = pl
    season = {
        # ★ 发出去的是**显示编号**（内部届号 + `season.display_offset`）：用户 m03981
        #   要求能自己写「这是第几个赛季」。内部届号 / start / end / 玩家档案里的
        #   season 全不动，所以赛季边界与结算逻辑一点没变。
        "id": _pvp_display_season(season_id),
        "start_time": season_start, "end_time": season_end,
        "title_text": cfg("season", "title_text", default=None) or "Trials Frontier",
        "banner_url": banner_url,
        "rank": 0,
    }
    rw = _pvp_season_rewards()
    if rw:
        season["rewards"] = rw
    return {"pvp_match_settings": settings, "current_season": season}


# --- 匹配（new_ranked → matches）-------------------------------------------
# `PVPManager::startNewRankedMatch(bool)` @0x5e1880 的调用顺序是
#   OnlinePVP::startRankedMatch(listener, outfit, …)         cmd 0x28 = new_ranked
#   → Time::getTimeOfDay()
#   → OnlinePVP::queryMatches(listener, vector<PVPMatch>*)   cmd 0x2a = matches
# 也就是说 new_ranked 只负责「下单」，客户端真正拿来当对手的是紧随其后的
# matches（cmd 0x28 解析完 `b 0x4fc864`，压根不回调 listener）。
#
# 规则（用户 m02663 指定，参数全部走 tf_config.json，留给未来 WebUI 调）：
#   ① 队列里有别的真人 → 立刻配对，两边共用一条 match id（各自视角 player1=自己）
#   ② 服务器上没有别的真人在活动 → 100% 发人机，不等
#   ③ 有别的真人在活动但没排队 → 等 matchmaking.bot_wait_seconds 秒，超时发人机
# 客户端在搜索阶段短促重试（真机日志：2 秒内 new_ranked+matches 各 4 次），
# 所以「等 60 秒」只能由服务端记状态：等待期间回空列表，超时后下一次 matches
# 调用直接给人机。
_PVP_MATCH_RE = re.compile(r"^/public/pvp_matches/v1/matches/(\d+)$")
_PVP_ROBOT_ID = "44444444-4444-4444-4444-444444444444"   # = FRIEND_NAMES 的 GhostRider
_PVP_QUEUE_TTL = 1800                 # 队列/对局的墙钟过期（秒）；也可由配置覆盖
_pvp_search = {}                      # profileId -> {"at": 下单时刻, "match_id": id|None}
_pvp_matches = {}                     # match_id -> {"players":[pid, …], "at", "track", "bot"}
_pvp_id_lock = threading.Lock()
_pvp_next_id = [1]                    # 用列表包一层，方便就地自增
_pvp_tickets = {}                     # profileId -> {"tickets": n, "ts": 回票基准时刻(0=已满)}
_pvp_chips = {}                       # profileId -> {"chips": n, "ts": 上次结算时刻, "acc": 余数, "tracks": [赛道 id]}
_pvp_players = {}                     # profileId -> rank/star/season/win_streak

PVP_STATE_PATH = os.path.join(HERE, "data", "pvp_state.json")
_pvp_state_lock = threading.RLock()
_pvp_in_request = [False]
_pvp_dirty = [False]
_pvp_saved_at = [0.0]
_PVP_SAVE_MIN_INTERVAL = 10


def _pvp_mark_dirty():
    _pvp_dirty[0] = True


def _pvp_state_load():
    """兼容旧 chips/tickets 文件；对局内赛道键从 JSON 字符串恢复成整数。"""
    try:
        with open(PVP_STATE_PATH, "r", encoding="utf-8") as f:
            blob = json.load(f)
    except FileNotFoundError:
        return
    if not isinstance(blob, dict):
        raise ValueError("Invalid PVP state: expected object")
    for key, dst in (("chips", _pvp_chips), ("tickets", _pvp_tickets),
                     ("search", _pvp_search), ("players", _pvp_players)):
        dst.update(blob.get(key) or {})
    for key, match in (blob.get("matches") or {}).items():
        for name in ("owner", "owner_at"):
            match[name] = {int(t): v for t, v in match.get(name, {}).items()}
        match["results"] = {p: {int(t): v for t, v in rows.items()}
                            for p, rows in match.get("results", {}).items()}
        _pvp_matches[int(key)] = match
    _pvp_next_id[0] = max(int(blob.get("next_id", 1)), max(_pvp_matches, default=0) + 1)


def _pvp_state_save(force=False):
    """一次替换写入经济状态与幂等标记；失败不能假报结算成功。"""
    if not _pvp_dirty[0] or (_pvp_in_request[0] and not force):
        return
    now = time.time()
    if not force and now - _pvp_saved_at[0] < _PVP_SAVE_MIN_INTERVAL:
        return
    with _pvp_state_lock:
        blob = {"chips": _pvp_chips, "tickets": _pvp_tickets,
                "matches": _pvp_matches, "search": _pvp_search,
                "players": _pvp_players, "next_id": _pvp_next_id[0]}
        os.makedirs(os.path.dirname(PVP_STATE_PATH), exist_ok=True)
        tmp = PVP_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            # 紧凑写：这个文件每个成功请求都要整份重写一遍（force=True），
            # `indent=1` 白占一倍体积。人读可以用 /__pvp 内省端点。
            json.dump(blob, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, PVP_STATE_PATH)
        _pvp_dirty[0] = False
        _pvp_saved_at[0] = now


def _pvp_request(handler):
    """ponytail: 单文件全局锁；吞吐量需要时再迁移 SQLite 事务。"""
    @functools.wraps(handler)
    def run(path, query, body, headers):
        # 包住读端点：轮询也会补票/结算，不能和 POST 并发改余额。
        with _pvp_state_lock:
            if not _ghost_caller(headers):
                return _pvp_error(401, "unauthenticated")
            states = (_pvp_chips, _pvp_tickets, _pvp_matches, _pvp_search, _pvp_players)
            before = copy.deepcopy(states)
            next_id = _pvp_next_id[0]
            dirty = _pvp_dirty[0]
            _pvp_in_request[0] = True
            try:
                result = handler(path, query, body, headers)
                if result[0] >= 400:
                    for dst, old in zip(states, before):
                        dst.clear()
                        dst.update(old)
                    _pvp_next_id[0] = next_id
                    _pvp_dirty[0] = dirty
                else:
                    if states != before:
                        _pvp_mark_dirty()
                    _pvp_state_save(force=True)
                return result
            except Exception as exc:
                for dst, old in zip(states, before):
                    dst.clear()
                    dst.update(old)
                _pvp_next_id[0] = next_id
                _pvp_dirty[0] = dirty
                if not isinstance(exc, OSError):
                    raise
                print("[pvp] transaction not saved: %s" % exc, flush=True)
                return 503, {"Content-Type": "application/json"}, {"error": "state-not-saved"}
            finally:
                _pvp_in_request[0] = False
    return run


_pvp_state_load()
atexit.register(lambda: _pvp_state_save(force=True))


# --- 局内票（免费票）--------------------------------------------------------
# 用户 m02890 的规则：开局每人 3 张局内票，每 1h 回 1 张，回满 3 张为止；
# 每次比赛/重试优先消耗局内票，用完才消耗黄金票。
#
# 客户端算法（`PVPMatch::getPlayerTickets` @0x5ed494 / `getTimeUntilNextFreeTicket`
# @0x5ed37c / `updateCurrentPlayerTicketCount` @0x5ed298，三者同一套）：
#     tickets = PVPMatch+0xa8 ; ticket_increased = PVPMatch+0x19c
#     max      = [PVPManager+0xc4]  ← pvp_match_settings.free_tickets_max
#     interval = [PVPManager+0xc0]  ← pvp_match_settings.free_tickets_interval
#     if (ticket_increased == 0) return tickets          # 0 = 已满/无需回票
#     if (tickets >= max) { ticket_increased = 0; return tickets }
#     if (now - ticket_increased < interval) return tickets
#     每满 interval 秒 tickets++ 并把 ticket_increased += interval（循环到 max）
# 所以服务端只要给出「当前票数」和「最近一次回票/开始计时的时刻」即可。
#
# 黄金票判定在 `MenuzStatePVPMatch::onRaceButtonPressed` @0x72d7c8：
#     if (getPlayerTickets() == 0) w3 = 1   # w3 = 使用黄金票
#     → PVPManager::requestStartLevel(..., w3, ...)
# 之前玩家槽只发 profile_id → PVPMatch+0xa8 = 0 → 每局都扣黄金票。
def _pvp_ticket_limits():
    maxn = cfg_int("matchmaking", "free_tickets_max", default=3)
    if maxn <= 0:
        maxn = 3
    interval = cfg_int("matchmaking", "free_tickets_interval_seconds", default=3600)
    if interval <= 0:
        interval = 3600
    return maxn, interval


def _pvp_tickets_for(pid, match=None):
    """返回 (tickets, ticket_increased)。ticket_increased == 0 表示已回满。"""
    if not pid:
        # 人机没有账号，永远给它「满票」——它也不该显示倒计时。
        return _pvp_ticket_limits()[0], 0
    maxn, interval = _pvp_ticket_limits()
    now = int(time.time())
    tickets_by_player = _pvp_tickets if match is None else match.setdefault("tickets", {})
    st = tickets_by_player.get(pid)
    if st is None:
        init = cfg_int("matchmaking", "free_tickets_initial", default=maxn)
        st = {"tickets": max(0, min(maxn, init)), "ts": 0}
        tickets_by_player[pid] = st
        _pvp_mark_dirty()
    if st["tickets"] < maxn:
        if not st["ts"]:
            st["ts"] = now                      # 从不满的这一刻开始计时
        else:
            gained = (now - st["ts"]) // interval
            if gained > 0:
                st["tickets"] = min(maxn, st["tickets"] + gained)
                st["ts"] = st["ts"] + gained * interval
                _pvp_mark_dirty()
    if st["tickets"] >= maxn:
        st["ts"] = 0                            # 满了就不再回
    _pvp_state_save()
    return st["tickets"], st["ts"]


def _pvp_consume_ticket(pid, match=None):
    """开一局就消耗一张局内票；返回扣完之后还剩几张。"""
    if not pid:
        return 0
    tickets, _ts = _pvp_tickets_for(pid, match)
    maxn, _iv = _pvp_ticket_limits()
    st = (_pvp_tickets if match is None else match["tickets"]).get(pid)
    if st is None or st["tickets"] <= 0:
        return 0
    if st["tickets"] >= maxn:
        st["ts"] = int(time.time())             # 从满票掉下来，回票从现在开始计
    st["tickets"] -= 1
    _pvp_mark_dirty()
    _pvp_state_save()
    return st["tickets"]


def _pvp_track():
    return cfg_int("matchmaking", "track_id", default=1041) or 1041


def _pvp_chips_state(pid):
    st = _pvp_chips.get(pid)
    if st is None:
        st = {
            "chips": max(0, cfg_int("chips", "start", default=0) or 0),
            "ts": int(time.time()),
            "acc": 0,
            "tracks": [],
        }
        _pvp_chips[pid] = st
        _pvp_mark_dirty()
    return st


def _pvp_set_tracks(pid, ids):
    """记下这个玩家已解锁的赛道清单（来自 pvp_init 的 body），筹码按条数产。

    ★ 必须去重：真机 body 实测有重复项（`…,1097,1097,…`），重复一条就多一条产线。
    ★ 必须滤掉明显不是赛道的 id：body 里混着 `1,2,4` 这种小号，而真实赛道 id 都在
      1000+（见 notes 里 TRACK_MASK 的说明「真实赛道 ID 目前最大 1438」）。
      ponytail: 100 是「一眼不是赛道」的分界；真要精确就等 WebUI 里配允许清单。
    """
    if not pid:
        return
    seen, out = set(), []
    for tid in ids or []:
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            continue
        if tid < 100 or tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
    st = _pvp_chips_state(pid)
    st["tracks"] = out
    _pvp_mark_dirty()
    _pvp_state_save()


def _pvp_chips_for(pid):
    """返回该玩家的筹码余额。

    产筹码完全在服务端：`chips.per_track_seconds` 秒 / 每一条已解锁赛道 / 1 枚。
    用户 m03154：「筹码是硬件定期生成的，比如我赢了一局，这条赛道定期生成一个筹码」，
    2026-10-05 再次确认「按赛道产币那套是对的」。
    ⚠ 人机没有账号也没有赛道，所以它不产币、余额就是它上次结算剩下的（同一个函数，
      不再给它特殊播种 —— 曾经为「对手头像下的红筹码」播种 500，那是调试值）。
    """
    if not pid:
        return 0
    st = _pvp_chips_state(pid)
    now = int(time.time())
    period = cfg_int("chips", "per_track_seconds", default=3600)
    ntrack = len(st.get("tracks") or [])
    if period and period > 0 and ntrack > 0:
        st["acc"] += max(0, now - st["ts"]) * ntrack
        st["ts"] = now
        if st["acc"] >= period:
            gained = st["acc"] // period
            st["acc"] -= gained * period
            top = cfg_int("chips", "max", default=0)
            st["chips"] += gained
            if top and top > 0 and st["chips"] > top:
                st["chips"] = top
            _pvp_mark_dirty()
    else:
        st["ts"] = now
    _pvp_state_save()
    return st["chips"]


def _pvp_spend_chips(pid, amount):
    """`POST /chips`（cmd 0x34）用：扣筹码，返回扣完的余额。"""
    if not pid:
        return 0
    st = _pvp_chips_state(pid)
    _pvp_chips_for(pid)
    try:
        amount = int(amount or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount > 0:
        st["chips"] = max(0, st["chips"] - amount)
        _pvp_mark_dirty()
    _pvp_state_save()
    return st["chips"]


# ---------------------------------------------- 后台（WebUI）改 PVP 服务端状态
# 为什么 PVP 余额可以「下发即生效」而存档物品不行（真机实测，m00702）：
#   存档 items2 是**客户端**整份上报覆盖的，服务端改了 version 也只能指望
#   客户端弹冲突界面让玩家选「用云端」；实测冷启动路径上客户端拿到
#   remote=115 之后仍然直接 POST 了自己的本地档，下发当场被抹掉。
#   PVP 余额正相反：客户端**只发增减指令**（开局扣一张、礼物加 N 张），
#   余额真源一直在服务端的 pvp_state.json，下次读 PVP 响应就看到了。
PVP_GRANTABLE = ("golden_ticket", "chips")


def pvp_read(profile_id):
    """后台展示用：该玩家 id 的 PVP 服务端余额。不建档（只读不产生副作用）。

    没建过 PVP 档时 golden_ticket 报**客户端会看到的默认值**
    `_PVP_DEFAULT_GOLDEN_TICKET`，而不是 None —— 界面上要显示的就是玩家
    此刻在游戏里看到的那个数。
    """
    st = _pvp_players.get(profile_id) or {}
    ch = _pvp_chips.get(profile_id) or {}
    return {
        "known": profile_id in _pvp_players,
        "golden_ticket": int(st.get("golden_ticket", _PVP_DEFAULT_GOLDEN_TICKET) or 0),
        "chips": int(ch.get("chips", 0) or 0),
        "rank": st.get("rank"),
        "star": st.get("star"),
        "season": st.get("season"),
        "win_streak": st.get("win_streak"),
    }


def pvp_grant(profile_id, fields, mode="add"):
    """后台改 PVP 服务端余额并**立刻落盘**。返回 (summary, error)。

    fields: {"golden_ticket": 2000, "chips": 5000}；mode: "add" | "set"。
    先整份校验再动手，避免只写了一半。
    """
    if not profile_id or not isinstance(fields, dict) or not fields:
        return None, "bad-request"
    if mode not in ("add", "set"):
        return None, "bad-mode"
    plan = []
    for name, raw in fields.items():
        if name not in PVP_GRANTABLE:
            return None, "not-grantable:" + str(name)
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return None, "bad-value:" + str(name)
        if val < 0:
            return None, "negative:" + str(name)
        plan.append((name, val))
    out = []
    for name, val in plan:
        if name == "golden_ticket":
            st = _pvp_player_state(profile_id)     # 按需建档（会标脏）
            before = int(st.get("golden_ticket") or 0)
            st["golden_ticket"] = val if mode == "set" else before + val
        else:
            st = _pvp_chips_state(profile_id)
            # 必须先把「按时间产出」的那部分结算掉再覆盖，否则会把挂账的筹码吞掉。
            _pvp_chips_for(profile_id)
            before = int(st.get("chips") or 0)
            st["chips"] = val if mode == "set" else before + val
        _pvp_mark_dirty()
        out.append({"field": name, "before": before, "after": int(st["golden_ticket"]
                   if name == "golden_ticket" else st["chips"])})
    _pvp_state_save(force=True)                    # 后台改动立刻持久化，不等 10 秒节流
    return {"applied": out, "mode": mode, "player": pvp_read(profile_id)}, None


def _pvp_bot_id():
    return cfg("matchmaking", "bot_profile_id", default=None) or _PVP_ROBOT_ID


def _pvp_entry(pid):
    """队列项统一成 dict（旧版本存的是裸时间戳，兼容一下）。"""
    e = _pvp_search.get(pid)
    if isinstance(e, dict):
        return e
    if e is None:
        return None
    return {"at": int(e), "match_id": None}


def _pvp_new_id():
    with _pvp_id_lock:
        mid = _pvp_next_id[0]
        _pvp_next_id[0] = mid + 1
        return mid


def _pvp_prune(now):
    """清掉过期的队列项与对局，免得玩家强杀进程后留下僵尸队列。"""
    ttl = cfg_int("matchmaking", "search_ttl_seconds", default=_PVP_QUEUE_TTL) or _PVP_QUEUE_TTL
    for pid, entry in list(_pvp_search.items()):
        if not entry.get("match_id") and now - entry.get("at", 0) > ttl:
            _pvp_search.pop(pid, None)
    # 已配对/待领取的对局不得按搜索 TTL 删除；close 收据也保留用于重试。


def _pvp_real_players():
    """服务器上真实注册过的 profileId（人机、假好友都不在 accounts.json 里）。"""
    try:
        return {a.get("profileId") for a in acct.list_accounts_public() if a.get("profileId")}
    except Exception:
        return set()


def _pvp_online_others(pid):
    """除自己外，最近 active_window_seconds 秒内还在发请求的真人。"""
    now = int(time.time())
    win = cfg_int("matchmaking", "active_window_seconds", default=300) or 300
    return [p for p, ts in list(ACTIVE_PLAYERS.items()) if p != pid and now - ts <= win]


def _pvp_view(pid, mid):
    """把内部对局渲染成 pid 视角的扁平对局对象。"""
    m = _pvp_matches.get(mid)
    if not m or pid not in m.get("players", []) or pid in m.get("closed", {}):
        return None
    opp = None
    for p in m.get("players") or []:
        if p != pid:
            opp = p
            break
    return _pvp_match_json(pid, mid, opp or _pvp_bot_id(), m.get("track"))


def _pvp_rewards(values):
    """把配置里的 `[金币, 钻石, 特殊奖励等级]` 规范化成 3 个整数。

    `OnlinePVP::parseMatch` @0x4fdd78 最多读 3 个元素且**不做类型检查**：
    `w10 = [node+0x28]` 直接当 int 用，所以给字符串/float 会把指针当数字。
    少给的补 0（parseMatch 会 `str wzr,[sp,#0xc0]` 预清零，等价）。
    """
    out = []
    for v in list(values or [])[:3]:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return out


def _pvp_score_int(time_ms, faults=0):
    """把「用时 + 失误数」打包成客户端要的 int score。

    编码来自 `ScoreCalculator::calculateOnlineScoreInt(int,int,int)` @0x5f5edc：
        score = (99 - faults) * 3600000 + (3600000 - time_ms)
    反向（`getTimeFromIntScore` @0x5f5f2c / `getFaultsFromIntScore` @0x5f5f50）：
        time_ms = 3600000 - (score % 3600000)
        faults  = 99 - score / 3600000
    实测真机跑一局的 `score`=359974879 → 99*3600000 起，即 0 失误、25121 ms ✓。
    """
    t = max(1, min(3600000, int(time_ms or 0) or 1))
    f = max(0, min(99, int(faults or 0)))
    return (99 - f) * 3600000 + (3600000 - t)


def _pvp_track_result(time_ms, faults=0, bike_data=None, additional_score=0,
                      outfit=0, opp_attempts=0):
    """`tracks[i].result_pN` 子对象的契约（`parseMatch` @0x4fd9d0 内层循环）。

    键都靠 `json_strcmp` 比：`score`@0xb88169 → 存进按 result_p1/p2 分槽的数组，
    收尾时 `getTimeFromIntScore`/`getFaultsFromIntScore` 解出时间与失误数，写进
    `PVPTrack+0x08`（对手用时）与 `PVPTrack+0x0C`（自己用时）；`bike_data`@0xb869e0
    → `PVPTrack+0x2C`（**按字节读** `ldrb`）；`additional_score`@0xb869ea、
    `outfit`@0xb8afa0、`opp_attempts`@0xb869fb 各有各的槽。

    ★ 这两个对象是**对手幽灵能不能下下来的唯一开关**：
      `OnlinePVP::startRace` @0x4fa22c 在 `/start_race` 之前先算
          req+0x62 = (*(u32*)(match + trackIndex*0x34 + 0x10) != 0)   // = PVPTrack+0x0C
      然后 cmd 0x2c 分支 @0x4fc358：`cbz` 就整段跳过，
      `OnlineGhostManager::getPVPGhost()` 根本不会被调用。
      不发 result_pN → +0x08/+0x0C 都是 0 → 比赛里没有对手幽灵（m05071 的根因）。
    """
    out = {"score": _pvp_score_int(time_ms, faults), "additional_score": int(additional_score or 0)}
    if bike_data is not None:
        out["bike_data"] = int(bike_data) & 0xFF
    if outfit:
        out["outfit"] = int(outfit) & 0xFFFFFF
    if opp_attempts:
        out["opp_attempts"] = int(opp_attempts)
    return out


def _pvp_time_of_score(score):
    """`_pvp_score_int` 的逆：score → 用时(ms)。"""
    score = int(score or 0)
    return max(0, 3600000 - (score % 3600000))


def _pvp_faults_of_score(score):
    """`_pvp_score_int` 的逆：score → 失误数。"""
    score = int(score or 0)
    return max(0, min(99, 99 - score // 3600000))


def _pvp_ghost_time(tid):
    """幽灵库里这条赛道的 drive_time（ms）；没有就退到 30 s。"""
    try:
        rec = acct.ghost_any_for_track(tid)
    except Exception:
        rec = None
    ms = int((rec or {}).get("drive_time") or 0)
    if ms < 1000 or ms > 3600000:
        ms = 30000
    return ms


def _pvp_bike_random():
    """发车方式：True（默认）= 按每条赛道自己的车级别随机；False = 全用 `bike_id`。"""
    return cfg("matchmaking", "bike_random", default=True) is not False


def _pvp_owned_bikes(pid):
    """这个玩家拥有的车号集合（`pvp_init` 上报的 `bikes` 位图，bit i = 车号 i+1）。

    ★ 位图语义是反汇编确认的：`OnlinePVP::getBikeAndTrackLists @0x4f96c0` 里
      `w20 |= 1 << index` 而 `UpgradeManager::getBikeIDbyIndex @0x62c4d8` = `index + 1`。
    没有记录（玩家没进过碉堡 / 老存档）就返回 None = **不筛车**（宁可用别人的车池，
    也不要因为不知道就一台都发不出来）。
    """
    if not pid:
        return None
    try:
        mask = (_pvp_chips_state(pid) or {}).get("bikes")
    except Exception:
        return None
    if isinstance(mask, bool) or not isinstance(mask, int) or mask <= 0:
        return None
    return {i + 1 for i in range(32) if mask & (1 << i)}


def _pvp_set_bikes(pid, mask):
    """记下 `pvp_init` 上报的 `bikes` 位图（<=0 视为没上报，保留旧值）。"""
    if not pid:
        return
    try:
        mask = int(mask)
    except (TypeError, ValueError):
        return
    if mask <= 0:
        return
    _pvp_chips_state(pid)["bikes"] = mask
    _pvp_mark_dirty()
    _pvp_state_save()


def _pvp_bike_pool(tier, owned=None, story_only=True):
    """能跑级别 `tier` 这张图的车号（升序）。

    规则照客户端 `LevelManager::isCorrectBikeTier @0x47c170`：
      车 tier == 图的 `B`、或车 tier == 255（特殊车能跑任何图）、或图的 `B` == 255 / 未知
      （不限级别）。`owned` = 玩家拥有的车号集合（None = 不筛）；`story_only` = 只发
      剧情默认车（1..9，用户 m08106 的「兜底安全范围」）。
    """
    cats = bike_catalog()
    if not cats:
        return []
    free = tier is None or tier == 255          # 不限级别的图
    out = []
    for bid in sorted(cats):
        b = cats[bid]
        if b.get("tier") is None:
            continue
        if owned is not None and bid not in owned:
            continue
        if story_only and not b.get("story"):
            continue
        if not free and b["tier"] != tier and b["tier"] != 255:
            continue
        out.append(bid)
    return out


def _pvp_default_bike(tier):
    """这张图的兜底车：该级别第一台剧情车；表读不到就 None（调用方再退固定 bike_id）。"""
    pool = _pvp_bike_pool(tier, None, True)
    return pool[0] if pool else None


def _pvp_pick_bikes(tracks, owned=None, seed=None):
    """给这局的每条赛道各随机挑一台车 -> {track_id: bike_id}。

    用户 m08106 定下的口径：**每条赛道按自己的级别各发一台**；池子只放剧情默认车；
    「如果玩家暂时没有其中几个车，就随机到有车的地图」⇒ 挑不出车的赛道**不进结果**，
    由调用方换图。挑不出任何车（车表读不到 / 玩家一台都没有）时返回空 dict，调用方
    退回固定 `matchmaking.bike_id` —— 绝不发 0（真机 bike_id=0 崩，见 h_liveevents_config）。
    """
    if not _pvp_bike_random() or not bike_catalog():
        return {}
    rnd = random.Random(seed) if seed is not None else random
    story_only = cfg("matchmaking", "bike_story_only", default=True) is not False
    out = {}
    for tid in tracks or []:
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            continue
        if tid in out:
            continue
        pool = _pvp_bike_pool(_track_bike_tier(tid), owned, story_only)
        if pool:
            out[tid] = rnd.choice(pool)
    return out


def _pvp_owned_for_match(players):
    """这场对局里「真人玩家都发得出来车」的车号集合（人机不参与 = 不限）。

    人机没有账号也没有车库，拿 None 当「不限」，交集时跳过它。
    """
    owned = None
    for pid in players or []:
        if not pid or pid == _pvp_bot_id():
            continue
        mine = _pvp_owned_bikes(pid)
        if mine is None:
            return None                          # 有一个玩家没上报 -> 谁都不筛，别把图挑没了
        owned = mine if owned is None else (owned & mine)
    return owned


def _pvp_tracks(owned=None):
    """本局要发的赛道清单（最多 3 条，理由见 matchmaking.track_ids 的注释）。

    用户 m04586：PVP 一局是**随机地图、随机车辆**。所以 `track_ids` 留空时从
    `candidate_tracks` 里随机抽 3 条；填了就固定用填的。

    ★ `owned` = 这场对局可用的车号集合（见 `_pvp_owned_for_match`）：发车方式为
      `random` 时，玩家在那个级别一台车都没有的图会被**换掉**（用户 m08106：
      「替换地图为有车的地图」）。车表读不到时不过滤（退化成老行为）。
    """
    def _ints(seq):
        out = []
        if isinstance(seq, (list, tuple)):
            for v in seq:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
                if v > 0:
                    out.append(v)
        return out

    out = _ints(cfg("matchmaking", "track_ids", default=None))
    if not out:
        cand = _ints(cfg("matchmaking", "candidate_tracks", default=None))
        if cand and _pvp_bike_random() and bike_catalog():
            story_only = cfg("matchmaking", "bike_story_only", default=True) is not False
            ok = [t for t in cand
                  if _pvp_bike_pool(_track_bike_tier(t), owned, story_only)]
            if ok:
                if len(ok) < len(cand):
                    print("[pvp] 发车池筛掉 %d 条没有对应级别车的赛道 → %d 条候选"
                          % (len(cand) - len(ok), len(ok)), flush=True)
                cand = ok
        if cand:
            out = random.sample(cand, min(3, len(cand)))
    if not out:
        out = [_pvp_track()]
    while len(out) < 3:
        out.append(out[-1])
    return out[:3]


def _pvp_side_score(m, who, tid):
    """这条赛道上 `who` 的 score（int）；没跑过就是 0。

    ★ 用户 m04586 纠正了这里的模型：「PVP 数据是一局随机地图、随机车辆，
      **谁跑了谁有数据**，不是直接读本地幽灵」。所以这里**只认客户端真报上来的成绩**，
      绝对不要拿幽灵/合成值预先占位 —— 那会让玩家一进局就看见对手有自己没有的成绩
      （「他甚至直接有比我快的记录，可我压根没跑」）。
      人机那一侧由 `_pvp_bot_runs()` 在玩家交完成绩后补一条自己的成绩。
    """
    rec = ((m.get("results") or {}).get(who) or {}).get(int(tid)) or {}
    try:
        return int(rec.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _pvp_bot_time(m, tid, my_ms=None):
    """人机在这条赛道上的用时（ms）—— **永远比玩家慢，默认真人赢**。

    用户 m04710（verbatim）：
      「跑完以后幽灵比我快。一般来说 PVP 的人机根本不跑图。默认真人赢。」

    所以人机这一条成绩只起两个作用：① 让这条赛道有个「可被挑战的记录」，
    ② 让 `/start_race` 的 `PVPTrack+0x0C != 0` 闸门通过、对手幽灵能下发。
    它**绝不能比玩家快**，否则 `parseMatch` 0x4fe0dc 的 score 比较会把赛道判给
    人机（真机症状：3 条赛道里 2 条显示 `+0:01.660` 是红色的，玩家跑完还是输）。

    以前这里是幽灵库那条幽灵的真实 `drive_time` —— 真机跑下来幽灵比玩家快，
    于是「跑完以后幽灵比我快」。现在改成「玩家成绩 + 一点余量」。
    """
    base = 0
    try:
        base = int(my_ms or 0)
    except (TypeError, ValueError):
        base = 0
    if base <= 0:
        # 理论上走不到（只有玩家先交成绩才会叫人机跑），留个兜底免得算出 0。
        base = _pvp_ghost_time(tid)
    # 余量可配置（用户 m04835：AI 控制留给 WebUI）。默认 +1.8% + 400ms，
    # 大约慢 1~3 秒，视觉上像「差一点点」而不是被吊打。
    try:
        pct = float(cfg("matchmaking", "bot_time_margin_pct", default=1.018))
    except (TypeError, ValueError):
        pct = 1.018
    try:
        add = int(cfg("matchmaking", "bot_time_margin_ms", default=400))
    except (TypeError, ValueError):
        add = 400
    if pct < 1.0:
        pct = 1.0          # 不允许比玩家快，见上面的用户规则
    t = int(base * pct) + max(0, add)
    return max(1, min(3599000, t))


def _pvp_bot_runs(m, tid, now=None, my_ms=None):
    """让这一局的人机「跑一次」这条赛道（玩家交完成绩后由 `h_pvp_race` 调用）。

    用户 m04586 描述的机制就是这样：谁跑了谁才有数据。玩家先跑 → 人机再跑 →
    两条成绩一比自己算归属（`parseMatch` 0x4fe0dc 的 score 比较），
    玩家想再抢回来时才会去下对手幽灵（`/start_race` 的 PVPTrack+0x0C 闸门）。
    `my_ms` 是玩家刚交的用时，用来把人机的成绩压在玩家之后（见 `_pvp_bot_time`）。
    """
    if not m or not tid:
        return
    if _pvp_bot_id() not in (m.get("players") or []):
        return
    by = m.setdefault("results", {}).setdefault(_pvp_bot_id(), {})
    tid = int(tid)
    if tid in by:
        return
    bt = _pvp_bot_time(m, tid, my_ms)
    by[tid] = {
        "score": _pvp_score_int(bt, 0),
        "additional_score": 0,
        "bike_data": cfg_int("matchmaking", "bike_id", default=1) or 1,
        "at": int(now or time.time()),
    }
    print("[pvp] 人机跑了赛道 %s -> %s ms" % (tid, bt), flush=True)


def _pvp_owner_of(m, tid):
    """这条赛道归谁；两边都还没成绩时返回 None。

    ★ 与客户端同一套判定：`parseMatch` 0x4fe0dc 起拿两个 result 的 score 比大小后调
      `PVPTrack::setOwner(...)`；score 越大越快（`_pvp_score_int`），谁快谁占。
    """
    pids = list(m.get("players") or [])
    if len(pids) < 2:
        pids = (pids + [_pvp_bot_id()])[:2]
    best, bestsc = None, -1
    for p in pids:
        sc = _pvp_side_score(m, p, tid)
        if sc > bestsc:
            best, bestsc = p, sc
    if bestsc <= 0:
        return None
    return best


def _pvp_match_won(m, who):
    """这局 `who` 赢了吗 —— **占住的赛道比对手多**就算赢。

    ★ 2026-10-06 由「3 条里占住 ≥2 条」改成「比对手占得多」（用户 m08968 真机）：
      那一局是到点截断的（`matchmaking.match_duration_seconds = 300` 的测试值），
      3 条赛道只跑完 1 条、玩家占住它 —— 客户端屏幕判**胜利**，老规则却算出 0 个
      赢家 ⇒ 服务端当平局：星章不动、连胜清零，和屏幕完全对不上。
      现在 1:0 与 2:1 都算赢，**0:0 仍是平局**（谁都没跑出成绩）。
      份额完全取自 `_pvp_owner_of`（与客户端 `parseMatch` 同一套 score 比较）。
    """
    pids = list(m.get("players") or [])
    if len(pids) < 2:
        pids = (pids + [_pvp_bot_id()])[:2]
    if who not in pids:
        return False
    mine = theirs = 0
    for tid in (m.get("tracks") or []):
        o = _pvp_owner_of(m, tid)
        if o == who:
            mine += 1
        elif o is not None and o in pids:
            theirs += 1
    return mine > theirs


def _chip_curve():
    """`(chip_equation_x, chip_equation_y)` —— 全局唯一的筹码曲线系数。

    客户端与服务端**必须用同一条曲线**：客户端拿它把服务器给的筹码快照
    从 `server_time` 外推到 `now`（`PVPMatch::getPlayerChips` @0x5ed6f8 的
    `- floor(f(server_time)) + floor(f(now))`），并画那个顺时针填充的圆环。
    """
    def _f(key, dflt):
        v = cfg("season", key, default=dflt)
        try:
            return float(v)
        except (TypeError, ValueError):
            return dflt
    x = _f("chip_equation_x", 0.5)
    y = _f("chip_equation_y", 0.5)
    if x <= 0 or y <= 0:  # 发 0 → 圆环永不填充，见 _TF_CONFIG_DEFAULTS 的注释
        x, y = 0.5, 0.5
    return x, y


def _chips_at(seconds, x=None, y=None):
    """`pow(t, x) * y` 的整数部分 —— 与客户端 `getNumChipsTotal` 一致。"""
    if x is None or y is None:
        x, y = _chip_curve()
    t = float(seconds)
    if t < 0:
        return 0
    try:
        return int((t ** float(x)) * float(y))
    except (OverflowError, ValueError):
        return 0


def _pvp_match_chips(m, who, now=None):
    """本局 `who` 从「自己占着的赛道」上产出的筹码；`m` 为空时返回 None。

    用户 m04404（引同服玩家 Assassins-Cry 的实测规则）：
      * 拿到这条赛道就开始累积，**前期快、后面越来越慢**；
      * 对手把赛道抢回去 → 累积速度**重置**，又从快开始变慢；
      * 整局跑完才结算成筹码余额（见 `_pvp_bank_match_chips`）。

    ★ 数值必须与客户端用同一条曲线（`_chip_curve`），否则赢家头像上那个
      圆环与数字会对不上（m04710）。
    """
    if not m or not who:
        return None
    now = int(now or time.time())
    x, y = _chip_curve()
    now = min(now, int(m["start"]) + int(m["dur"]))
    total = int((m.get("chip_base") or {}).get(who) or 0) + int(m.get("earned", {}).get(who, 0))
    at_map = m.get("owner_at") or {}
    start = int(m.get("start") or now)
    for tid in (m.get("tracks") or []):
        tid = int(tid)
        if _pvp_owner_of(m, tid) != who:
            continue
        at = at_map.get(tid)
        if at is None:
            at = at_map.get(str(tid))
        dt = max(0, now - int(at if at else start))
        total += _chips_at(dt, x, y)
    return total


def _pvp_bank_match_chips(m):
    """整局跑完 → 把局内筹码结算进 `_pvp_chips`（幂等）。

    结算分两步：
      1. **局内新产的筹码**进各自余额 —— 只加 `_pvp_match_chips - chip_base` 这一段差值。
         `chip_base` 恒为 0（局内筹码从 0 起算，见建局处），所以差值就是本局产出；
      2. **赢家掠夺输家这一局里产出的筹码**：`chips.match_loser_keeps_pct`（默认 50）
         是输家保住的比例，其余转给赢家。
         ⚠ 抢的是**这一局里对方占赛道产出的那部分**（`gains`），
           **不是对方的钱包余额** —— 用户 2026-10-05 纠正过：掠夺的对象是「对局里
           正在生成的筹码」，钱包里原有的钱不该被按比例割走。
           `match_loser_keeps_pct` 留作将来 WebUI 的可调项。
    """
    if not m or m.get("_banked"):
        return
    m["_banked"] = True
    now = int(m["start"]) + int(m["dur"])
    players = [p for p in (m.get("players") or []) if p]
    base_map = m.get("chip_base") or {}

    # 先算清每人在这一局里产了多少，并各自入账（别动别人的钱包）。
    gains = {}
    for p in players:
        base = int(base_map.get(p) or 0)
        got = int(_pvp_match_chips(m, p, now) or 0)
        gain = max(0, got - base)
        gains[p] = gain
        if gain > 0:
            st = _pvp_chips_state(p)
            st["chips"] = int(st["chips"] or 0) + gain
            _pvp_mark_dirty()
            print("[pvp] 结算局内筹码 %s +%d -> %d" % (p, gain, st["chips"]), flush=True)

    # 再把输家**这一局的产出**按比例转给赢家（3 条赛道占住 ≥2 条者为赢家）。
    winner = None
    for p in players:
        if _pvp_match_won(m, p):
            winner = p
            break
    if not winner:
        _pvp_state_save()
        return
    keep = cfg_int("chips", "match_loser_keeps_pct", default=50)
    try:
        keep = max(0, min(100, int(keep)))
    except (TypeError, ValueError):
        keep = 50
    for p in players:
        if p == winner:
            continue
        stolen = gains.get(p, 0) * (100 - keep) // 100
        if stolen <= 0:
            continue
        lst = _pvp_chips_state(p)
        lst["chips"] = int(lst["chips"] or 0) - stolen
        wst = _pvp_chips_state(winner)
        wst["chips"] = int(wst["chips"] or 0) + stolen
        _pvp_mark_dirty()
        print("[pvp] 掠夺局内筹码 %s -%d -> %d ; %s +%d -> %d"
              % (p, stolen, lst["chips"], winner, stolen, wst["chips"]), flush=True)
    _pvp_state_save()


def _pvp_slim_match(m):
    """所有参与者都领完 → 丢掉这局的大块数据，只留重放要用的领取回执。

    ★ 对局本来会**永远**留在 `_pvp_matches` 里（只有搜索队列有 TTL），而每局都带
      results / races / race_receipts / reward_receipts / rewarded_races；
      `_pvp_state_save(force=True)` 又在每个成功请求后整份重写 ⇒ 越玩越慢。
      收尾时瘦身就够，先别上 SQLite（`_pvp_request` 的注释里留了这条升级路径）。
    """
    if not m:
        return
    for key in ("results", "owner", "owner_at", "earned", "races", "pending_races",
                "race_receipts", "reward_receipts", "rewarded_races",
                "ownership_changes", "chip_base"):
        m.pop(key, None)
    m["slim"] = True


def _pvp_match_json(profile_id, match_id=1, opponent_id=None, track=None):
    """一条合成对局——根对象契约来自 `OnlinePVP::parseMatch` @0x4fd9d0。

    第一遍遍历根成员读 `id` @0xb86c8a / `server_time` @0xb8695c /
    `total_time` @0xb86979 / `player1` @0xb86984 / `player2` @0xb8698c；
    第二遍读 `start_time` @0xb8d564 / `rewards` @0xb8d6de / `tracks` @0xb49d2b
    （子键 `track`/`bike`/`owner_change_time`）。
    玩家子对象只发 `profile_id` @0xb86951 —— 收尾时 `strcpy(match+0x131, …)`
    拷的就是「对手」那个槽的 profile_id，`rank`/`chips` 那些一旦类型发错就会
    被当位域用，所以宁可不发。
    ⚠ `PVPMatch+0x00` 就是 match id，`parseMatches` 用它查重，所以 id 要稳定。

    ★ `total_time` @0xb86979 是**对局时长（秒）**，不是已用时间！parseMatch 用它算
      `match+0x1a4 = 1 + (server_time - start_time >= total_time)`，而出参 1/2 的语义是
      「进行中 / 已结束」（`PVPManager::canStartNewRankedMatch` @0x5e3978 要求它 ∈{1,2}，
      `PVPMatch::getRemainingTime` @0x5ed1e4 算的是 `start_time + total_time - now`）。
      早先发 0 → server_time==start_time 时判定 0>=0 → `+0x1a4 = 2`＝「已结束」，
      这就是「匹配上对手立马就结束」的另一半原因。
    """
    now = int(time.time())
    # 本局状态（`_pvp_make_match` 建的）。`.get` 也兼容「服务器重启后客户端手上那条
    # 未找到的对局由路由返回404，不再制造新对局覆盖客户端。
    _m = _pvp_matches.get(match_id) or {}
    dur = int(_m.get("dur") or 0) or cfg_int("matchmaking", "match_duration_seconds",
                                             default=21600) or 21600
    # ★ start_time 必须**每条对局固定**：每轮都回 now 会让
    #   `PVPMatch::getRemainingTime` @0x5ed1e4（= start_time + total_time - now）
    #   永远等于满值 —— 真机症状就是「倒计时过几秒又跳回满值」（用户 m04404）。
    start = int(_m.get("start") or 0) or now
    fixed_bike = cfg_int("matchmaking", "bike_id", default=1)
    if not isinstance(fixed_bike, int) or fixed_bike < 1:
        fixed_bike = 1
    # 一局 3 条赛道；`track` 仍作兜底（服务器重启后补建的对局没有 tracks）。
    tlist = _m.get("tracks")
    if not isinstance(tlist, list) or not tlist:
        tlist = _pvp_tracks() if track is None else [int(track)]
    tlist = [int(t) for t in list(tlist)[:3] if int(t) > 0] or [_pvp_track()]
    # ★ 发车表按**每个玩家**各定一份并记进对局（`_m["bikes"][pid]`）：这个函数每条
    #   `matches` 轮询都会被调，现挑就会一局之内来回换车。挑不出来（车表读不到 / 玩家
    #   一台车都没有 / `bike_random = False`）就退回「该级别第一台剧情车」，再退
    #   `matchmaking.bike_id` —— **绝不发 0**（真机 bike_id=0 必崩）。
    mine = {}
    if _m and profile_id:
        allb = _m.setdefault("bikes", {})
        if profile_id not in allb:
            allb[profile_id] = _pvp_pick_bikes(tlist, _pvp_owned_bikes(profile_id),
                                               seed="%s|%s" % (match_id, profile_id))
            _pvp_mark_dirty()
        mine = allb.get(profile_id) or {}
    _rw = _m.get("rewards", [0, 0, 0])

    def _track_json(tid):
        """一条赛道。★ 只发**双方真跑过的成绩**，绝不预先占位。

        `parseMatch` 0x4fe0dc 起就是拿两个 result 的 score 比大小后调
        `PVPTrack::setOwner(...)` —— score 越大越快（`_pvp_score_int`），谁快谁占这条赛道。
        这里以前恒定发 `对手用时 * 1.06`（永远比对手慢）：一是玩家跑得再快，
        下一轮 `matches` 回来还是同一组合成值、赛道永远不换主（「我跑的记录不会被记录，
        超越他了也依然没法打败他」m04404）；二是**玩家还没跑就先看见对手有成绩**
        （「他甚至直接有比我快的记录，可我压根没跑」m04586）。

        ★ 用户 m04586 的模型：一局随机地图随机车，**谁跑了谁才有数据**。
          所以两边都没跑过时，`result_p1`/`result_p2` **一个都不发** ——
          这样 PVPTrack+0x08/+0x0C 都是 0，客户端就不会去下对手幽灵
          （`startRace` @0x4fa22c 读 `PVPTrack+0x0C`），符合「没人跑过就没幽灵」。
          玩家交完成绩后 `h_pvp_race` 会让人机也跑一次（`_pvp_bot_runs`），
          那时两条成绩都在，玩家再跑这条赛道才会拿到对手幽灵。
        """
        tid = int(tid)
        # ★ `owner_change_time` = **「当前归属者是什么时候拿到这条赛道的」unix 秒**
        #   （`PVPTrack::setOwner` @0x5ddfa4 = `str w1,[x0,#4]; str w2,[x0,#0x20]`
        #     ⇒ +0x04 = owner、+0x20 = owner_change_time）。
        #   客户端 `PVPMatch::getChipProgress` @0x5ed8c4 / `getPlayerChips` @0x5ed6f8
        #   都拿它当时间基准：`now - owner_change_time` 才是筹码累积的秒数。
        #   `getChipProgress` 还要求 owner != -1 且该值 != 0，否则直接返回 0
        #   ⇒ **无主赛道必须发 0**（这样圆环不画，与「谁都没跑过」一致）。
        #   ⚠ 曾经这里发的是车种 ID（=1）：那是把 `PVPTrack+0x24`（bike）和
        #     `PVPTrack+0x20`（owner_change_time）搞混了 —— `onStartRaceSent`
        #     @0x5e59ec 读的 `[x20+0x24]` 里 x20 是 **PVPTrack***，所以它取的是 bike。
        #     两个字段互不冲突，可以同时发对。
        oc = 0
        if _pvp_owner_of(_m, tid) is not None:
            raw = (_m.get("owner_at") or {}).get(tid)
            if raw is None:
                raw = (_m.get("owner_at") or {}).get(str(tid))
            try:
                oc = int(raw or 0)
            except (TypeError, ValueError):
                oc = 0
        # ★ 这条赛道的车：先看这局给这个玩家定的（按图的级别从剧情车里随机），
        #   再退该级别第一台剧情车 —— 但**只限随机发车**：关掉随机时无论级别都用
        #   配置里的 `matchmaking.bike_id`（要按级别发就该开着随机）。
        bike = mine.get(tid)
        if not isinstance(bike, int) or bike < 1:
            bike = (_pvp_default_bike(_track_bike_tier(tid))
                    if _pvp_bike_random() else None) or fixed_bike
        out = {
            "track": tid,
            "bike": bike,
            # ★ 车种 ID：onStartRaceSent @0x5e59ec 把它写进 GameWorld+0x1efc；
            #   填 0 → UpgradeManager::getBike(0) 为 NULL → 加载关卡时崩。
            "owner_change_time": oc,
        }
        for slot, pid in (("result_p1", profile_id), ("result_p2", opponent_id)):
            rec = ((_m.get("results") or {}).get(pid) or {}).get(tid) or {}
            try:
                sc = int(rec.get("score") or 0)
            except (TypeError, ValueError):
                sc = 0
            if sc > 0:
                out[slot] = _pvp_track_result(_pvp_time_of_score(sc),
                                              _pvp_faults_of_score(sc),
                                              bike_data=(rec.get("bike_data") or bike),
                                              outfit=(rec.get("outfit") or 0))
        return out

    # Each slot has its own tickets/rank; rewards remains a shared match pool.
    def _slot(pid):
        # 筹码：局内按「自己占着的赛道」随时间产（用户 m04404 的规则），
        # 没有对局（服务器重启后的补建）才退回账号总额。
        chips = _pvp_match_chips(_m, pid, now) if _m else None
        if chips is None:
            chips = _pvp_chips_for(pid)
        info = _pvp_player_info(pid=pid)
        slot_tickets, slot_ts = _pvp_tickets_for(pid, _m)
        return {
            "profile_id": pid,
            "tickets": slot_tickets,
            "ticket_increased": slot_ts,
            "chips": chips,
            "rank": info["rank"],
            "elo_rank": info["elo_rank"],
            # ★ 对手的骑手外观：必须发这个玩家的真值，发 0 = 画成默认那套
            #   （见 `_pvp_outfit_of` 的真机证据）。
            "outfit": _pvp_outfit_of(pid),
            # Native +0x1b8: per-player special-reward progress, not the shared pool.
            "reward_data": int(_m.get("reward_data", {}).get(pid, 0)),
        }
    return {
        "id": match_id,
        "server_time": now,
        "total_time": dur,
        # ★ 本机必须正好出现在一个槽里：parseMatch 只用 `strcmp(本地名, player2.profile_id)`
        #   决定本地是 p1 还是 p2（不相等 → 本地 = player1），错了就会读错 chips /
        #   tickets / reward_data / 对手 profile_id（strcpy 到 match+0x131 的那个）。
        #   同理 result_pN 也是按槽位归属：本机是 player1 时，result_p1 = 本机成绩。
        "player1": _slot(profile_id or _pvp_bot_id()),
        "player2": _slot(opponent_id or _pvp_bot_id()),
        "start_time": start,
        "tracks": [_track_json(t) for t in tlist],
        # ★ 赛后奖励 = [金币, 钻石, 特殊奖励等级]；parseMatch 拼成
        #   {(1,coins),(2,gems),(145,special)} 塞进 PVPMatch+0x170，
        #   赛后界面 setupComponents @0x7308f0 直接把它搬过去显示。
        #   不发 → 打完一局金币/钻石留空、特殊奖励 setAsEmpty。
        "rewards": _pvp_rewards(_rw),
    }


def _pvp_make_match(players, track=None, bot=False):
    """建一条对局并登记，返回 match id。

    ★ 对局状态里必须**固定** `start` / `dur` / `tracks`：`_pvp_match_json` 每轮
      （`matches`、`new_ranked`…）都会被调用，如果每次都拿 `now` 当 start_time，客户端算
      `PVPMatch::getRemainingTime` @0x5ed1e4（= start_time + total_time - now）就永远是
      满值 —— 真机症状正是「倒计时过几秒又跳回满值」（用户 m04404）。
    `results` 存每条赛道双方真报上来的成绩；`owner_at` 记每条赛道「当前归属者是什么时候
    拿到它的」，供 `_pvp_match_chips` 算筹码（换主即重置累积速度，同样来自 m04404）。
    """
    now = int(time.time())
    mid = _pvp_new_id()
    # 发车：先按「这场对局里真人都有车的级别」筛掉挑不出车的赛道（用户 m08106：
    # 「替换地图为有车的地图」），再按每条赛道自己的级别各挑一台（见 `_pvp_pick_bikes`）。
    owned = _pvp_owned_for_match(players)
    tracks = _pvp_tracks(owned) if track is None else [int(track)]
    tracks = [int(t) for t in list(tracks)[:3] if int(t) > 0] or [_pvp_track()]
    dur = cfg_int("matchmaking", "match_duration_seconds", default=21600) or 21600
    _pvp_matches[mid] = {
        "players": list(players),
        "at": now,
        "start": now,
        "dur": int(dur),
        "tracks": tracks,
        "track": tracks[0],
        # {profile_id: {track_id: bike_id}} —— 每人一份，`_pvp_match_json` 第一次要的时候
        # 按各自的车型/拥有情况定下来（同一局里反复取必须拿到同一台，否则一局内换车）。
        "bikes": {},
        # {profile_id: {track_id: {"score": int, "additional_score": int,
        #                          "bike_data": int, "at": unix}}}
        "results": {},
        # {track_id: profile_id} 当前归属（真值仍由 `_pvp_owner_of` 按 score 算）
        "owner": {},
        # {track_id: 归属者拿到它的 unix 时间} —— 换主时重置，筹码累积速度随之重置
        "owner_at": {},
        "rewards": [0, 0, 0], "reward_data": {}, "earned": {},
        "chip_base": {},
        "bot": bool(bot),
    }
    for p in players:
        if not p:
            continue
        # ★ `chip_base` 恒为 0：**局内筹码和局外钱包是两笔钱**（用户 m01903：
        #   「局外筹码是局外筹码。局内筹码是0，只有赢得一条赛道，那个赛道开始产出
        #   筹码才会增加。怎么可能是直接从玩家局外筹码同步」）。
        #   客户端画的数字 = `chip_base + 局内占赛道产出的筹码`，所以发 0 时那个数字
        #   就从 0 起步、只随占住的赛道长大。曾经把钱包余额灌进来，结果对手头像下面
        #   直接显示你的存款（真机：115313 / 999999）。
        #   结算不受影响：`_pvp_bank_match_chips` 只加「本局产出」= match − base。
        _pvp_matches[mid]["chip_base"][p] = 0
    _pvp_mark_dirty()
    # Log one line per match: 用户 m08968「对局突然结束」这类问题，靠 stdout 里的
    # `open` / `close` 两行就能定位（开局时间、时长、赛道、是否人机）。
    print("[pvp] open mid=%s players=%s tracks=%s dur=%ss bot=%s"
          % (mid, ",".join(players), ",".join(str(t) for t in tracks), dur, bool(bot)),
          flush=True)
    return mid


def _pvp_pair_with_human(pid, now):
    """队列里有没有别的真人可以立刻配；有就建共享对局并回 id。"""
    real = _pvp_real_players()
    for other in list(_pvp_search):
        if other == pid or other not in real:
            continue
        e = _pvp_entry(other)
        if not e or e.get("match_id"):
            continue
        if now - e.get("at", 0) > cfg_int("matchmaking", "search_ttl_seconds", default=_PVP_QUEUE_TTL):
            continue
        mid = _pvp_make_match([other, pid], bot=False)
        e["match_id"] = mid
        e["new"] = False
        entry = _pvp_entry(pid) or {"at": now}
        entry["match_id"] = mid
        entry["new"] = False
        _pvp_search[pid] = entry
        print("[pvp] 真人配对 match=%d %s <-> %s" % (mid, other, pid), flush=True)
        return mid
    return None


def _pvp_give_bot(pid, now, reason=""):
    entry = _pvp_entry(pid) or {"at": now}
    mid = _pvp_make_match([pid, _pvp_bot_id()], bot=True)
    entry["match_id"] = mid
    entry["new"] = False
    _pvp_search[pid] = entry
    print("[pvp] 发人机 match=%d pid=%s (%s)" % (mid, pid, reason), flush=True)
    return mid


def _pvp_charge_extra_match(pid, cost):
    """并行对局超出免费名额时收黄金门票（用户回忆的机制：第 4 条起要一张金票）。

    ★ 必须在**对局真的建出来之后**才调：等真人的那几十秒里 new 标记还挂着，
      每次轮询都进这里，先扣就会被重复收票。
    """
    if not pid or not cost:
        return None
    player = _pvp_player_state(pid)
    player["golden_ticket"] = max(0, int(player.get("golden_ticket") or 0) - int(cost))
    _pvp_mark_dirty()
    print("[pvp] 超出免费并行名额，收 %d 张黄金门票 -> 剩 %d pid=%s"
          % (cost, player["golden_ticket"], pid), flush=True)
    return player["golden_ticket"]


def _pvp_match_info(profile_id=None, allow_create=False):
    """`parseMatches` @0x4fcad0 的响应契约。

    根对象两个键（已反汇编确认）：`waiting_requests` @0xb8695c（int）、
    `matches` @0xb86562（**JSON 数组**，每个元素交给 `parseMatch` @0x4fd9d0，
    元素结构体 `PVPMatch` 大小 0x1d8）。
    没有对局时回**空数组**——`parseMatches` 对空数组走的是纯清理分支。
    给出对局后 `PVPManager::validateMatches()` @0x5e3e20 会把每条对局的
    `+0x1ac` 置 1（`parseMatch` 恒置 0），置 1 之后 `isAllMatchesValid()` 才认它有效。

    `allow_create=False`（pvp_init 用）：只汇报已有对局，不主动开新局——
    免得玩家刚进碉堡、还没点「全新对决」就被塞一条对局。

    ★ 并行多局：`h_pvp_new_ranked` 每次被调用都会打一个「new」标记（一次显式开新局）。
      以前只要已有未关闭对局就把旧的原样回给他，于是玩家再点「全新对决」看到的还是
      那一局 —— 真机症状「再开一个对局会覆盖上一个对局」。免费名额
      `matchmaking.ranked_match_slots`（= 发给客户端的 `ranked_match_slots`），
      超出后每条收 `additional_match_cost` 张黄金门票，硬上限 `ranked_match_limit`。
      新开的那条排在最前面。
    """
    if not profile_id:
        return {"matches": [], "waiting_requests": 0}
    now = int(time.time())
    _pvp_prune(now)

    views = [_pvp_view(profile_id, mid) for mid, match in _pvp_matches.items()
             if profile_id in match.get("players", []) and profile_id not in match.get("closed", {})]
    entry = _pvp_entry(profile_id)
    want_new = bool(entry and entry.get("new"))
    if not want_new:
        if views or not allow_create or not entry:
            return {"matches": views, "waiting_requests": 0}
    elif not allow_create:
        return {"matches": views, "waiting_requests": 0}

    # ★ 并行名额：前 `ranked_match_slots` 条免费，之后每开一条收
    #   `additional_match_cost` 张黄金门票（用户回忆的机制），到 `ranked_match_limit` 封顶。
    #   钱在对局真的建出来之后才扣（见 _pvp_charge_extra_match）。
    cost = 0
    if want_new:
        slots = max(0, cfg_int("matchmaking", "ranked_match_slots", default=3))
        limit = max(slots, cfg_int("matchmaking", "ranked_match_limit", default=10))
        if len(views) >= limit:
            entry["new"] = False
            print("[pvp] 并行对局已达上限 %d，不再开新局 pid=%s" % (limit, profile_id), flush=True)
            return {"matches": views, "waiting_requests": 0}
        if len(views) >= slots:
            cost = max(0, cfg_int("matchmaking", "additional_match_cost", default=1))
            if cost and int(_pvp_player_state(profile_id).get("golden_ticket") or 0) < cost:
                entry["new"] = False
                print("[pvp] 免费并行名额已满 %d 且黄金门票不足（需 %d）pid=%s"
                      % (slots, cost, profile_id), flush=True)
                return {"matches": views, "waiting_requests": 0}

    if not (cfg("matchmaking", "enabled", default=True) is not False):
        return {"matches": views, "waiting_requests": 0}

    mid = _pvp_pair_with_human(profile_id, now)
    if mid:
        _pvp_charge_extra_match(profile_id, cost)
        return {"matches": [_pvp_view(profile_id, mid)] + views, "waiting_requests": 0}

    # ② 服务器上没有别的真人在活动 → 100% 人机，不等
    others = _pvp_online_others(profile_id)
    if not others:
        mid = _pvp_give_bot(profile_id, now, "no-other-human")
        _pvp_charge_extra_match(profile_id, cost)
        return {"matches": [_pvp_view(profile_id, mid)] + views, "waiting_requests": 0}

    # ③ 有真人在活动但没排队 → 等 bot_wait_seconds，超时转人机
    wait = cfg_int("matchmaking", "bot_wait_seconds", default=60)
    if wait < 0:
        wait = 0
    if now - entry.get("at", now) >= wait:
        mid = _pvp_give_bot(profile_id, now, "timeout %ds, %d other(s) online" % (wait, len(others)))
        _pvp_charge_extra_match(profile_id, cost)
        return {"matches": [_pvp_view(profile_id, mid)] + views, "waiting_requests": 0}

    print("[pvp] 等待真人 pid=%s 已等 %ds/%ds，在线他人 %d"
          % (profile_id, now - entry.get("at", now), wait, len(others)), flush=True)
    return {"matches": views, "waiting_requests": 1}


def h_pvp_new_ranked(path, query, body, headers):
    """GET /public/pvp_matches/v1/new_ranked?outfit=&ticket=&param= —— 下单（cmd 0x28）。

    响应契约来自 `OnlinePVP::parseRankedOpponent` @0x4fd8fc：根对象成员键只有
    `self` @0xb8694c 和 `opponent` @0xb871fe，两个成员**自己就是 player_info
    对象**（`parseRankingData(x1=成员节点, x2=…+0x18)` 直接吃它；内层那个
    `profile_id` 比较没有分支，是编译器产物）。
    ⚠ cmd 0x28 解析完 `b 0x4fc864` **不回调 listener**，所以「匹配到人」这件事
    必须在随后的 matches 里体现——这里只负责「下单」：把队列里的时刻重置成现在，
    顺带清掉上一轮的 match_id（重新匹配＝开新局）。
    """
    pid = _ghost_caller(headers)
    print("[pvp] new_ranked pid=%s q=%s" % (pid, query), flush=True)
    if pid:
        _pvp_prune(int(time.time()))
        # ★ 每次「全新对决」都是**一次显式开新局**，无条件打 new 标记。
        #   以前只有「手上没有未关闭对局」时才排队 ⇒ 已有对局时再点一次，
        #   matches 只会把旧对局回给他（真机症状「再开一个对局会覆盖上一个」）。
        _pvp_search[pid] = {"at": int(time.time()), "match_id": None, "new": True}
    info = _pvp_player_info(_pvp_chips_for(pid), pid=pid)
    return 200, {"Content-Type": "application/json"}, {
        "self": dict(info),
        "opponent": dict(info),
    }


def h_pvp_init(path, query, body, headers):
    """POST /public/pvp_matches/v1/pvp_init —— 碉堡的总闸（cmd 0x27）。

    请求体（真机实测）：{"tracks":"1024,2,4,…","bikes":521227,"lang":"zh_Hans"}。
    对局、奖池、票与筹码通过 _pvp_request 统一原子持久化。
    ⚠ 这里 `allow_create=False`：刚进碉堡只汇报已有对局，不主动开新局。
    """
    b = _json_body(body)
    print("[pvp] pvp_init <- %s" % (b,), flush=True)
    pid = _ghost_caller(headers)
    if isinstance(b, dict) and isinstance(b.get("tracks"), str):
        # "1024,2,4,…" —— 玩家已解锁的赛道清单，筹码按条数产（见 _pvp_chips_for）。
        ids = []
        for part in b["tracks"].split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        if ids:
            _pvp_set_tracks(pid, ids)
    if isinstance(b, dict) and "bikes" in b:
        # `bikes` = 拥有的车辆位图（bit i = 车号 i+1，见 `_pvp_owned_bikes`）。
        # 发随机车时只从玩家真有的车里挑（用户 m08106）。
        _pvp_set_bikes(pid, b.get("bikes"))
    return 200, {"Content-Type": "application/json"}, {
        "player_info": _pvp_player_info(_pvp_chips_for(pid), pid=pid),
        "match_info": _pvp_match_info(pid, allow_create=False),
        "pvp_config": _pvp_season(_banner_url(headers)),
    }


def h_pvp_matches(path, query, body, headers):
    """GET /public/pvp_matches/v1/matches[/<id>] —— 对局列表 / 单条对局。

    ⚠ 两条路径的响应**形状不同**，必须分开：
      * `matches`（cmd 0x2a，@0x4fc2c8）→ `parseMatches` 要的是
        `{"matches":[…],"waiting_requests":N}` 这个**列表包装**；
      * `matches/<id>`（cmd 0x29，@0x4fc274）→
        `PVPManager::getMatchById(id)` 拿到本地对局后直接
        `parseMatch(json_root, query, match, 0)`，**不剥壳**，所以响应体必须与
        列表里的那个元素**同构**（扁平的单个对局对象）。
    以前只按前缀注册了 `matches`，`/matches/1` 被它吃掉后客户端拿到的是列表对象，
    `parseMatch` 在根成员里找不到 `id`/`tracks` → 对局一条赛道都没有 →
    开局立刻结束、点「结束」崩（真机 m02488 反馈，日志 21:15:50 那行）。
    """
    pid = _ghost_caller(headers)
    m = _PVP_MATCH_RE.match(path)
    if m:
        mid = int(m.group(1))
        print("[pvp] match/%s pid=%s" % (mid, pid), flush=True)
        view = _pvp_view(pid, mid)
        if view:
            return 200, {"Content-Type": "application/json"}, view
        return _pvp_error(404, "match-not-found")
    print("[pvp] matches pid=%s" % (pid,), flush=True)
    return 200, {"Content-Type": "application/json"}, _pvp_match_info(pid, allow_create=True)


def h_pvp_player(path, query, body, headers):
    """GET /public/pvp_matches/v1/player/<profileId> —— 对手/自己的资料（cmd 0x2b）。

    解析器：`parseRankingData(node, PVPPlayerData@query+0x40)`（0x4fc318），
    所以根对象就是 player_info 那一套键。之后还会走
    `OnlineUbiservices::getPlayerProfile` + `OnlineGhostManager::getPVPGhost`。
    """
    print("[pvp] player %s" % path, flush=True)
    who = path.rstrip("/").rsplit("/", 1)[-1]
    return 200, {"Content-Type": "application/json"}, _pvp_player_info(_pvp_chips_for(who), pid=who)


def h_pvp_players(path, query, body, headers):
    """GET /public/pvp_matches/v1/players?profiles=<pid,pid,…> —— 碉堡的好友榜（cmd 0x37）。

    ⚠ 这个端点以前注册在 `h_pvp_accept` 上，回 `{"data": []}` —— **对象**。而解析器
    `tr::OnlinePVP::parseFriendLeaderboard` @0x4fe88c 第一件事就是：

        0x4fe8c0  ldr w8, [x1, #0x30]      ; json_value->type
        0x4fe8c4  ... cmp w8, #2           ; 2 = array
        0x4fe8c8  b.ne #0x4fea98           ; 不是数组 → 一个字都不解析

    于是「进碉堡一直转圈」：请求发得出去（真机 2026-10-05 13:12:17 已见），
    响应类型不对，客户端永远等不到 `onFriendLeaderboardReceived`。
    ⇒ **根必须是 JSON 数组**，元素对象逐成员比对这 5 个键：

        rank        0xb869b5  → u16（0x4fe99c `strh w8,[sp,#0x2c]`）
        elo_rank    0xb869b1  → int（0x4fe9a8 `str w8,[sp,#0x28]`）
        star        0xb86947  → u16（0x4fe9b4 `strh w8,[sp,#0x2e]`）
        profile_id  0xb86951  → 字符串，`0x4fe9c0 ldr x1,[x27,#0x28]; strcpy`
        season      0xb868e5  → int（0x4fe990；缺键时 memset 留下的默认是 -1）

    之后 0x4fea20 用 `OnlineFriends::getFriend(profile_id)` 换显示名；换不到、且
    profile_id 也不等于本机玩家（对比 `[GlobalData+0x420]->[0]+0x110`）时才 `b` 跳过
    那一条。⇒ 所以 **每个请求到的 profile 都要回一条**，`profile_id` 必须与请求里
    的字符串逐字节一致（它随后还要拿去查头像）。

    发起者是 `tr::OnlinePVP::getFriendLeaderboard(OnlinePVPFriendLeaderboardQuery*)`
    @0x4fb650：URL 模板 @0xb86840、`0x4fb77c mov w3,#0x37`（cmd 0x37）、
    `0x4fb6c8 ldr w24,[x19,#0x38]` 是起始下标、`0x4fb788` 那组最多凑 0x13+1=20 条。
    """
    pid = _ghost_caller(headers)
    listing = []
    seen = set()
    raw = dict(parse_qsl(query or "", keep_blank_values=True)).get("profiles")
    if isinstance(raw, str):
        for who in raw.split(","):
            who = who.strip()
            if not who or who in seen:
                continue
            seen.add(who)
            info = _pvp_player_info(_pvp_chips_for(who), pid=who)
            info["profile_id"] = who
            listing.append(info)
    print("[pvp] players pid=%s -> %d 条 %s"
          % (pid, len(listing), [it["profile_id"] for it in listing]), flush=True)
    return 200, {"Content-Type": "application/json"}, listing


def h_pvp_config(path, query, body, headers):
    """GET /public/pvp_matches/v1/pvp_config?lang=%s —— 赛季配置（cmd 0x30）。

    ⚠ 名字有误导：这个请求函数在符号表里叫 `getSeasonData` @0x4fa9f0，但它拼的
      URL 是 `%s/%s/pvp_matches/v1/pvp_config?lang=%s`（0x4faa7c `add x2,x2,#0x6de`）。
      真正拼 `season/%d?lang=` 的是 `getSeasonDataById` @0x4faaec（cmd 0x31）。
    """
    return 200, {"Content-Type": "application/json"}, _pvp_season(_banner_url(headers))


def h_pvp_season_data(path, query, body, headers):
    try:
        sid = int(path.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        return _pvp_error(400, "invalid-season")
    pid = _ghost_caller(headers)
    if sid < 1:
        sid = _pvp_player_state(pid)["season"]
    current = _pvp_season(_banner_url(headers))["current_season"]
    current["id"], current["start_time"], current["end_time"] = _pvp_season_window(sid)
    current["id"] = _pvp_display_season(current["id"])
    state = _pvp_player_state(pid)
    current["rank"] = state.get("season_history", {}).get(str(sid), {}).get("rank", state["rank"])
    return 200, {"Content-Type": "application/json"}, current


def h_pvp_close_season(path, query, body, headers):
    # Native sends {}. Currency is granted locally by the season animation callback.
    state = _pvp_player_state(_ghost_caller(headers))
    current = _pvp_season_window()[0]
    if state["season"] != current:
        state.setdefault("season_history", {})[str(state["season"])] = {"rank": state["rank"], "star": state["star"]}
        state.update(season=current, rank=max(1, min(25, cfg_int("matchmaking", "start_rank", default=25))),
                     star=0, win_streak=0)
    return 200, {"Content-Type": "application/json"}, {"rank": state["rank"], "star": state["star"]}


def _pvp_error(status, error):
    return status, {"Content-Type": "application/json"}, {"error": error}


def _pvp_post_match(body, headers):
    data = _json_body(body)
    pid = _ghost_caller(headers)
    mid = data.get("match_id") if isinstance(data, dict) else None
    # JSON integers only: bool and floats must not turn into valid ids.
    match = _pvp_matches.get(mid) if type(mid) is int else None
    if not match or pid not in match.get("players", []):
        return data, pid, None
    return data, pid, match


def _pvp_receipt(pid, data):
    return pid + ":" + hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def h_pvp_start_race(path, query, body, headers):
    data, pid, match = _pvp_post_match(body, headers)
    if match is None:
        return _pvp_error(404, "match-not-found")
    if time.time() >= match["start"] + match["dur"] or pid in match.get("closed", {}):
        return _pvp_error(409, "match-ended")
    tid = data.get("track")
    # ★ 真机发的是**字符串**：`{"match_id": 1,"golden_ticket": "False","track": "1062"}`
    #   （日志 2026-10-05 14:12:00 实测）。这里曾经写死 `type(tid) is not int` ⇒ 一律
    #   400，客户端点「开赛」直接失败。h_pvp_race 早就容忍数字串，这里对齐，
    #   并且**统一存成 int**（否则 h_pvp_race 的 `pending["track"] != tid` 会 409）。
    if not (type(tid) is int or isinstance(tid, str) and tid.isdigit()):
        return _pvp_error(400, "invalid-race")
    tid = int(tid)
    if tid not in match["tracks"] or data.get("golden_ticket") not in ("True", "False"):
        return _pvp_error(400, "invalid-race")
    norm = dict(data, track=tid)
    pending = match.setdefault("pending_races", {})
    # ponytail: 协议无开赛事务 id；同一未完赛请求按重试处理，换赛道是新尝试。
    if pending.get(pid) == norm:
        return 200, {"Content-Type": "application/json"}, {}
    if data["golden_ticket"] == "True":
        player = _pvp_player_state(pid)
        if player["golden_ticket"] < 1:
            return _pvp_error(409, "insufficient-tickets")
        player["golden_ticket"] -= 1
    else:
        if _pvp_tickets_for(pid, match)[0] < 1:
            return _pvp_error(409, "insufficient-tickets")
        _pvp_consume_ticket(pid, match)
    pending[pid] = norm
    return 200, {"Content-Type": "application/json"}, {}


def _pvp_reported(value, mask, fallback=0):
    """客户端在对局上报里带过来的外观字段。

    `bike_data` 按字节读（`PVPTrack+0x2C`，0xb869e0），`outfit` 是 24 位 = 3×8 位骑手部件
    （见 `_lb_data` 的位布局注释）。**只认整数**，类型不对或超范围一律回退 —— 这两个值
    后面会被当位域/字节用，放进去一个字符串等于让客户端去解一个指针。
    """
    return value if type(value) is int and 0 <= value <= mask else fallback


def h_pvp_race(path, query, body, headers):
    data, pid, match = _pvp_post_match(body, headers)
    if match is None:
        return _pvp_error(404, "match-not-found")
    receipt = _pvp_receipt(pid, data)
    receipts = match.setdefault("race_receipts", {})
    if receipt in receipts:
        return 200, {"Content-Type": "application/json"}, receipts[receipt]
    now = int(time.time())
    if now >= match["start"] + match["dur"] or pid in match.get("closed", {}):
        return _pvp_error(409, "match-ended")
    raw_track = data.get("track")
    if not (type(raw_track) is int or isinstance(raw_track, str) and raw_track.isdigit()):
        return _pvp_error(400, "invalid-track")
    tid, score = int(raw_track), data.get("score")
    if tid not in match["tracks"] or type(score) is not int or not 0 < score < 360000000:
        return _pvp_error(400, "invalid-result")
    pending = match.get("pending_races", {}).get(pid)
    if not pending or pending.get("track") != tid:
        return _pvp_error(409, "race-not-started")
    previous_owner = _pvp_owner_of(match, tid)
    by = match.setdefault("results", {}).setdefault(pid, {})
    if score > int(by.get(tid, {}).get("score", 0)):
        # ★ `bike_data` / `outfit` 是**客户端自己报上来的**（模板 `{"…","outfit": %d,
        #   "bike_data": %d}` @0xb86637 就在 `pvp_matches/v1/race` 的上报体里）。以前这里
        #   写死 `matchmaking.bike_id`，于是不管你骑哪辆车、穿哪套衣服，对手看到的都是
        #   那辆默认车 —— 「车子喷漆是错的」在 PvP 这条路上就是这么来的。
        by[tid] = {"score": score, "additional_score": 0,
                   "bike_data": _pvp_reported(data.get("bike_data"), 0xFF,
                                              cfg_int("matchmaking", "bike_id", default=1)),
                   "outfit": _pvp_reported(data.get("outfit"), 0xFFFFFF),
                   "at": now}
    _pvp_bot_runs(match, tid, now=now, my_ms=_pvp_time_of_score(score))
    owner = _pvp_owner_of(match, tid)
    changed = owner != previous_owner
    if changed:
        if previous_owner:
            earned = match.setdefault("earned", {})
            earned[previous_owner] = earned.get(previous_owner, 0) + _chips_at(now - match["owner_at"][tid])
        match.setdefault("owner", {})[tid] = owner
        match.setdefault("owner_at", {})[tid] = now
        changes = match.setdefault("ownership_changes", {})
        changes[pid] = changes.get(pid, 0) + 1
    race_id = match.get("next_race_id", 1)
    match["next_race_id"] = race_id + 1
    match.setdefault("races", {})[str(race_id)] = pid
    match.setdefault("pending_races", {}).pop(pid, None)
    result = {"ownership_changed": "True" if changed else "False", "race_id": race_id}
    receipts[receipt] = result
    return 200, {"Content-Type": "application/json"}, result


def h_pvp_accept(path, query, body, headers):
    # tracks is just an upload acknowledgement. Reward mutation has its own handler.
    return 200, {"Content-Type": "application/json"}, {}


def h_pvp_increase_rewards(path, query, body, headers):
    data, pid, match = _pvp_post_match(body, headers)
    if match is None:
        return _pvp_error(404, "match-not-found")
    semantic = {k: data.get(k) for k in ("race_id", "coin", "gem", "special", "reward_data")}
    receipt = _pvp_receipt(pid, semantic)
    seen = match.setdefault("reward_receipts", [])
    if receipt in seen:
        return 200, {"Content-Type": "application/json"}, {}
    if match.get("_banked") or time.time() >= match["start"] + match["dur"]:
        return _pvp_error(409, "match-ended")
    if any(type(data.get(k)) is not int or not 0 <= data[k] <= 2147483647
           for k in ("coin", "gem", "special", "reward_data", "race_id")):
        return _pvp_error(400, "invalid-reward")
    rid = data["race_id"]
    # Native recovery/checkMatchSpecialReward sends only reward_data with race_id=0.
    # Offline validation policy: monetary/special deltas need a completed paid race.
    if rid == 0 and any(data[k] for k in ("coin", "gem", "special")):
        return _pvp_error(409, "reward-without-race")
    if rid and match.get("races", {}).get(str(rid)) != pid:
        return _pvp_error(409, "unknown-race")
    rewarded = match.setdefault("rewarded_races", [])
    if rid and rid in rewarded:
        return _pvp_error(409, "race-reward-already-recorded")
    # Success callback increases the same shared PVPMatch pool; refresh returns totals.
    rewards = [a + data[k] for a, k in zip(match.get("rewards", [0, 0, 0]), ("coin", "gem", "special"))]
    if any(v > 2147483647 for v in rewards):
        return _pvp_error(400, "reward-overflow")
    match["rewards"] = rewards
    match.setdefault("reward_data", {})[pid] = data["reward_data"]
    seen.append(receipt)
    # ponytail: 只留最近 128 个重试指纹 —— 客户端的重放窗口是「立刻重发」，
    # 128 次请求之外的旧回执没有实用价值，留着只会让状态文件无限长大。
    if len(seen) > 128:
        del seen[:-128]
    if rid:
        rewarded.append(rid)
    return 200, {"Content-Type": "application/json"}, {}


def h_pvp_close(path, query, body, headers):
    # OnlinePVP::endMatch @0x4fa87c -> /close, cmd0x2f; not a generic 200 stub.
    data, pid, match = _pvp_post_match(body, headers)
    if match is None:
        return _pvp_error(404, "match-not-found")
    closed = match.setdefault("closed", {})
    if pid in closed:
        return 200, {"Content-Type": "application/json"}, closed[pid]
    if time.time() < match["start"] + match["dur"]:
        return _pvp_error(409, "match-not-ended")
    if data.get("create_new") not in ("True", "False") or data.get("ticket") not in ("True", "False"):
        return _pvp_error(400, "invalid-close")
    _pvp_bank_match_chips(match)
    winner = next((p for p in match["players"] if _pvp_match_won(match, p)), "")
    # ★ 一行对局总结（用户 m08968：对局「突然结束」必须有据可查）。到点后客户端的
    #   下一次 start_race 会吃 409 `match-ended`（见 h_pvp_start_race），它据此收局；
    #   所以这里打 `elapsed` 与「跑出成绩的赛道数」，一眼就能看出是不是被计时器截断的。
    _mid = next((k for k, v in _pvp_matches.items() if v is match), "?")
    _owners = ",".join("%s=%s" % (tid, (_pvp_owner_of(match, tid) or "-")[:8])
                       for tid in (match.get("tracks") or []))
    _done = sum(1 for tid in (match.get("tracks") or [])
                if any(tid in ((match.get("results") or {}).get(p) or {})
                       for p in match["players"]))
    print("[pvp] close mid=%s closer=%s dur=%ss elapsed=%ss winner=%s tracks=%s done=%d/%d"
          % (_mid, pid, match["dur"], int(time.time()) - int(match["start"]),
             winner or "-", _owners, _done, len(match.get("tracks") or [])), flush=True)
    state = _pvp_player_state(pid)
    rank = state["rank"]
    caps = _pvp_star_array()
    if winner == pid:
        state["win_streak"] += 1
        for _ in range(2 if state["win_streak"] >= 3 else 1):
            rank = state["rank"]
            if rank == 0:
                state["star"] = 0
            elif state["star"] >= caps[rank - 1]:
                state["rank"], state["star"] = rank - 1, 1
            else:
                state["star"] += 1
    elif winner:
        state["win_streak"] = 0
        if 0 < rank < 20:
            if state["star"] == 0 and rank < 15:
                state["rank"], state["star"] = rank + 1, max(0, caps[rank] - 1)
            else:
                state["star"] = max(0, state["star"] - 1)
    result = {"ownership_changes": match.get("ownership_changes", {}).get(pid, 0)}
    if winner:
        result["last_match_winner"] = winner
    closed[pid] = result
    # 双方都领完了 → 瘦身（必须等最后一个人算完胜负，否则 _pvp_match_won 读不到成绩）。
    if all(p in closed for p in (match.get("players") or [])):
        _pvp_slim_match(match)
    _pvp_search.pop(pid, None)
    if data["create_new"] == "True":
        # 客户端要求「再来一局」→ 和「全新对决」同一条路：打 new 标记后由
        # _pvp_match_info 真开一条（并行上限见 matchmaking.ranked_match_slots）。
        _pvp_search[pid] = {"at": int(time.time()), "match_id": None, "new": True}
        _pvp_match_info(pid, allow_create=True)
    # onMatchEndSent grants this match's coins/gems/special locally. Never add to save here.
    return 200, {"Content-Type": "application/json"}, result


def h_pvp_chips(path, query, body, headers):
    # OnlinePVP::spendChips @0x4fb1f8 sends exactly {"use_chips": N}.
    data = _json_body(body)
    amount = data.get("use_chips") if isinstance(data, dict) else None
    if type(amount) is not int or not 0 < amount <= 2147483647:
        return _pvp_error(400, "invalid-chip-amount")
    pid = _ghost_caller(headers)
    if not pid:
        return _pvp_error(401, "unauthenticated")
    if _pvp_chips_for(pid) < amount:
        return _pvp_error(409, "insufficient-chips")
    left = _pvp_spend_chips(pid, amount)
    return 200, {"Content-Type": "application/json"}, {"chips": left}


def h_pvp_purchase_tickets(path, query, body, headers):
    data = dict(parse_qsl(query or ""))
    try:
        num, price = int(data["num"]), int(data["price"])
    except (KeyError, TypeError, ValueError):
        return _pvp_error(400, "invalid-ticket-purchase")
    unit_price = next((v["amount"] for v in _pvp_product_list()
                       if v["product_id"] == "chip_shop.goldentickets"), 0)
    # 客户端算法（`purchaseChipstoreItem @0x5e6e1c` + UI @0x6451f4）：
    #     total = int(float(num * amount) * multiplier + 0.5) ; price = total // num
    # multiplier 来自**玩家拥有的 type9 套装**（`getCurrentPVPChipStorePriceMultiplier
    # @0x582040`），服务端不重建这套持有关系。所以合法的 price 是 `0 < price <= 基价`
    # —— 上界由服务端价表钉死（不许抬价），下界只可能是客户端自己的折扣。
    # 原来要求 price == unit_price，穿折扣套装买金票一律 400。
    if num <= 0 or not 0 < price <= unit_price or num * price > 2147483647:
        return _pvp_error(400, "invalid-ticket-purchase")
    pid = _ghost_caller(headers)
    if not pid:
        return _pvp_error(401, "unauthenticated")
    state = _pvp_player_state(pid)
    if state["golden_ticket"] + num > 2147483647 or _pvp_chips_for(pid) < num * price:
        return _pvp_error(409, "insufficient-chips")
    left = _pvp_spend_chips(pid, num * price)
    state["golden_ticket"] += num
    return 200, {"Content-Type": "application/json"}, {"chips": left, "golden_ticket": state["golden_ticket"]}


def h_ghost_upload(path, query, body, headers):
    """PUT .../payload 之外落单的二进制上传（老路径），落盘到 inbox 备用。"""
    q = dict(parse_qsl(query, keep_blank_values=True))
    track = q.get("track_id") or ""
    raw = body if isinstance(body, (bytes, bytearray)) else b""
    if track and raw[:4] == b"\x03\x00\x00\x00":
        p = acct.store_ghost(track, "upload_%s_%d.bin"
                             % (q.get("player", "anon")[:12], int(time.time())), bytes(raw))
        print("[ghost] 收到上传 赛道 %s -> %s (%d 字节)" % (track, p, len(raw)), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


def h_replay_id(path, query, body, headers):
    """POST /public/resultservice/v1/replay_id —— 登记「谁在哪条赛道跑了多少」。

    ★★ 必须回 `{"replay_id": <int >= 1>}`，这是「比赛幽灵」按钮能点亮的关键。
       链路（反汇编 tmp/libcmp/orig-libTrialsGo.so）：
         tr::OnlineGhostManager::checkGhost @0x5070cc 发本条 POST
           -> tr::GhostQueryObject::onNetworkDataReceived @0x508800
              cmd 0x0e(14) 分支 @0x50895c：遍历响应根的孩子找整型键
              "replay_id"@0xb87bc0，取 *(int*)(node+0x28) 存进 w20；
              ★ `cmp w20,#1; b.lt 0x508a68` —— **小于 1 一律走失败分支**，
              只有 >=1 才回调 listener->vtable[0x18](err=0, id=w20, name)。
           -> tr::MenuzStateMap::onGhostQuery @0x77f900 把 w20 写进选中行的
              `LeaderboardPlayerItem+0x84`。
           -> 之后每次 tr::MenuzStateMap::setupRaceButton @0x77e01c 里
              `ldr w8,[x21,#0x84]; cmn w8,#1; b.ne 0x77e288` —— **只有
              +0x84 != -1 才跳过硬 disable 按钮的那一段**。
       回 `{"data": []}`（本函数旧行为）⇒ 没有 replay_id 键 ⇒ w20=0 ⇒
       按钮永远灰着、点不动。真机 31 次调用全被这条坑掉。

    ★ 回的这个 id 会被 tr::OnlineGhostManager::getGhost @0x506e48 当成
       **userstorage 的 contentId** 去取幽灵：
         OnlineUserStorage::getData(listener, "ghost", id) @0x578780
           -> GET %s/%s/userstorage/v2/content/ghost/%d     （元数据）
           -> 拿到 contentId 后再取 .../<id>/payload        （二进制）
       所以必须回幽灵库里**真实存在**的 contentId，不能瞎编。
    """
    b = _json_body(body)
    client_ip = None
    try:
        client_ip = headers.get("_client_ip") or headers.get("X-Real-IP")
    except Exception:
        pass
    rec = acct.ghost_record_replay(b.get("profile_id"), b.get("track_name"),
                                   b.get("drive_time"), b.get("faults"), b.get("bike"),
                                   client_ip)
    pid = b.get("profile_id")
    board = b.get("track_name")
    if isinstance(board, (int, float)):
        board = "track%d" % int(board)
    elif board and not str(board).startswith("track"):
        board = "track%s" % board
    board = board or ""

    _rows, ghost_of = _opponent_entries()
    cid = (ghost_of.get(pid) or {}).get(board)
    if not cid:
        # 榜外的 pid（玩家自己）或没折成对手的赛道 —— 回该赛道任意一条兜底，
        # 至少让按钮能点亮、能进「加载幽灵」界面。
        try:
            tid = int(str(board).replace("track", "") or 0)
        except Exception:
            tid = 0
        g = acct.ghost_any_for_track(tid) if tid else None
        cid = g.get("contentId") if g else None

    if not cid:
        g = acct.ghost_any()
        cid = g.get("contentId") if g else None

    if not cid:
        # 库里真的一条幽灵都没有（理论上不会：`ghost_sync_legacy` 启动时总会导入内置幽灵）。
        # ★ 但即使这样也**绝不能**回 `{"data": []}`：cmd 14 @0x50895c 读键
        #   `"replay_id"`@0xb87bc0 后紧跟 `cmp w20,#1; b.lt 0x508a68`，
        #   小于 1 一律走 err=7 ⇒ 按钮永久灰着。宁可给一个必定取不到 payload 的 id，
        #   至少让按钮亮起来、界面进得去。
        print("[ghost] replay_id %s %s -> 库里一条幽灵都没有，回兜底 id=1"
              % (pid, board), flush=True)
        return 200, {"Content-Type": "application/json"}, {"replay_id": 1}

    print("[ghost] replay_id %s %s %s ms -> replay_id=%d"
          % (rec.get("profile_id"), rec.get("track_name"), rec.get("drive_time"), cid),
          flush=True)
    return 200, {"Content-Type": "application/json"}, {"replay_id": int(cid)}


def h_iap_verify(path, query, body, headers):
    """收据校验。原来走兜底 {"data": []}（等于失败），这里改成明确放行。

    端点由 .rodata @0xb8c81c 的 '%s/public/receiptvalidation/v1/%s?pid=%s&uid=%s&transaction_id=%s'
    拼出，第二个 %s 实测值是 'verify_android'（@0xb8c80d）。日志串：
    'VALIDATION RESPONSE: %d' / 'VALIDATION RESPONSE: %s'（@0xb8c89c / @0xb8c8cd）。
    ⚠ 响应字段名没有实测验证过，这里是尽力而为的放行写法。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    print("[iap] verify_android pid=%s uid=%s tx=%s"
          % (q.get("pid"), q.get("uid"), q.get("transaction_id")), flush=True)
    return 200, {"Content-Type": "application/json"}, {
        "valid": True, "status": 0, "errorCode": 0, "ret": True,
        "product_list": [], "data": [],
    }


def h_iap_products(path, query, body, headers):
    """内购商品表 / 限购配置。响应形状已从 `tr::StoreManager::parseResponse`

    （libTrialsGo.so @0x57b1dc，cmd 0x19 分支直接把 **json 根** 交给
    `parseStoreConfiguration` @0x57b30c）反汇编出来：

        parseResponse: json_parse(text) -> root；cmd==0x19 -> parseStoreConfiguration(this, root)
        parseStoreConfiguration: 遍历 root 的顶层成员，找名为 "limited_purchases"
            (@0xb8c8e5) 的成员；命中后遍历它的每个元素对象，逐个读这 5 个键：
              "name"          @0xbb3f5e  (字符串)
              "product_id"    @0xbaaa7d  (字符串)
              "limit"         @0xbb3a74  (int)
              "counter"       @0xb8c8fc  (int)
              "fake_counter"  @0xb8c8f7  (int)
            每个元素被 _M_emplace_back_aux 追加进 std::vector<tr::ServerStoreItemData>。

    所以正确的响应是 **顶层键** `limited_purchases`（不是 "product_list"）：

        {"limited_purchases": [ {"name":..., "product_id":..., "limit":N,
                                 "counter":N, "fake_counter":N}, ... ]}

    返回空数组是安全的（遍历零次），而且比 `{}` 安全得多。
    （`product_list` @0xb86bf3 那个串其实属于 `tr::OnlinePVP::parseSeason`，跟内购无关 ——
     早期笔记把它误记成内购键了。）
    """
    print("[iap] product/configuration 被请求", flush=True)
    return 200, {"Content-Type": "application/json"}, {"limited_purchases": []}


def h_targeting_bundle_config(path, query, body, headers):
    """礼包解锁白名单 —— ROADMAP 3「现时内购礼包」的真正开关。

    反汇编依据 `OnlineProfileEligibilityManager::GetBundleConfig` @0x515f8c（cmd 0x85）
    与解析器 `parseConfigData` @0x515dc8：
      - **根必须是 JSON 数组**（0x515e34 `cmp w8,#2`），元素**必须是整数**
        （0x515e58 `cmp w8,#4`，非整数静默跳过）。
      - 每个整数 push 进 `OnlineProfileEligibilityManager+0x10` 的 std::vector<int>，
        即「礼包 id 白名单」。
      - 消费：`ProfileEligibilityManager::isBundleEligible(int)` @0x5955e8 线性查找，
        唯一调用者是 `StoreItem::unlockConditionsOK` @0x609a20。
      - bundle id 取值域 = 0..255（0x609a14 `ldrb w1,[x20,#0x208]` 是单字节）。

    链路：MenuzStateMain::onBecomeTopmostState 0x76d128 → fetchConfig 0x595648
    → GetBundleConfig 0x515f8c → parseConfigData 0x515dc8
    → onReceivedBundleConfig 0x595634 → isBundleEligible ← unlockConditionsOK
    → OfferManager::pushPopup 0x5ff750（礼包弹窗就是这么出来的）。

    ⚠ 这里以前落到 rules.json 的 "*" 兜底 {"data": []} —— 那是个 **JSON 对象**，
    根类型判等直接失败，白名单恒为空 ⇒ **礼包功能整体是死的**。
    回 0..255 即「全部礼包有条件可选」；回 [] 是最小安全值。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    print("[targeting] condition_items type=%s" % q.get("type"), flush=True)
    return 200, {"Content-Type": "application/json"}, list(range(256))


def h_targeting_configuration(path, query, body, headers):
    """在线配置包（GET getAnonymousConfiguration 0x4ee808 / POST getConfiguration
    0x4ee544，两者共用 cmd 0x49，由 `OnlineConfiguration::parseJsonResponse`
    @0x4eeb50 解析）。

    识别的最完整形状（据 targeting-v1.md §3）：
        {"limited_purchases": [{"name":..,"product_id":..,"limit":..,
                                "counter":..,"fake_counter":..}],
         "pay_times": N, "country": "CN", "update": 794,
         "update_platform": {"google": 794}, "timestamp": 1700000000,
         "login": {"enabled": 0, "access": 0}}

    回 `{}` 是**明确安全的最小值**：root->first_child == NULL 时走 0x4eef3c
    的默认值路径（w27 = -1），而 0x4eefd0 的 `cmn w27,#1; b.eq` 会**跳过整个
    配置包下载**。这正是离线想要的。

    ⚠ 永远**不要**发 `metadata`：它里面的 `downloadurl` 会让客户端对任意绝对
    URL 发 GET 并 `SaveFile::writeSystemFile` 落盘（0x4ef250），随后触发
    `GlobalData::onDataPacksUpdated()` —— 既污染本地状态又指向真实 S3。

    ⚠ 唯一真实崩溃面在别处：0x4eed1c `str w9,[x8,#0x10]`（写 `login.access`）
    **没有判 `OnlineCore::m_authentication+0x28` 是否为 NULL**。所以本端点要么
    连带 `login` 一起省掉（现在这样），要么确保登录态已建立后再让它带 `login`。
    """
    print("[targeting] configuration body=%s"
          % body[:200].decode("utf-8", "replace"), flush=True)
    # 顺手把客户端报的玩家等级记下来，给 /progress/status 的「云端摘要」用。
    _remember_player_xp(headers, body)
    return 200, {"Content-Type": "application/json"}, {}


def h_vip_registration(path, query, body, headers):
    """VIP 排行榜徽章注册。

    反汇编依据（libTrialsGo.so `tr::VIPLeaderboardBadgeService::registerMembership`
    @0x51ab68，360 字节，尾部 0x51ac70..0x51accc）：
      if (GlobalSettings::getSetting(hash("Anticheating_Enabled"), 1) != 0) {
          ts = AntiCheating::getSystemTime();
          snprintf(buf1, 0x100, "%s%uvip%s", <base>, ts,
                   "18e3548c59ad40dd03907b7aeee71d67");      // 盐 @0xb86ca1
          OnlineChecksum::calculateMD5(md5, buf1);
          OnlineChecksum::formatToJson(json, md5, ts);
          snprintf(body, 0x400, "{\\"badge_display\\":true,%s}", json);   // fmt @0xb8961f
      } else {
          snprintf(body, 0x400, "{\\"badge_display\\":true}");           // @0xb8965f
      }
      snprintf(url, 0x400, "%s%s", <serverAddr>, "/public/targeting/v1/vip_registration"); // @0xb89639
      DebugOut::add("%s\\n%s", url, body);                                // @0xb89555
      OnlineCore::postJson(listener, url, body, /*cmd=*/0x72, /*needAuth=*/1);  // PLT 0x352770

    响应由同一个类的 `onNetworkDataReceived` @0x51b0ac 处理，它只认 **cmd 0x73**
    （`cmp w3,#0x73`），所以本端点的响应其实不会被解析 —— 但按 `parseJsonData`
    认识的形状回一个 `badge_display` 最稳妥。
    """
    print("[vip] vip_registration body=%s"
          % body[:200].decode("utf-8", "replace"), flush=True)
    return 200, {"Content-Type": "application/json"}, {"badge_display": True}


def h_vip_validation(path, query, body, headers):
    """VIP 成员查询 —— 这是唯一会被 `parseJsonData` 解析响应的端点。

    `tr::VIPLeaderboardBadgeService::sendMembershipQuery` @0x51ad70（340 字节）：
    URL 以 `%s%s` 拼 `<serverAddr>` + `/public/targeting/v1/vip_validation?profiles=`
    （@0xb896a4），然后把 `char const** profiles` 里每个字符串用 `strcat` 依次追加
    （0x51ae38），最后
      OnlineCore::getRequest(listener, listener, url, /*cmd=*/0x73, 0, /*needAuth=*/1, 0)
    （0x51ae54 `mov w3,#0x73`、0x51ae6c PLT 0x33f1d0）。

    `parseJsonData(unsigned char* text, uint len)` @0x51b0fc（972 字节）只认两个顶层键：
      "player"        @0xb882f8  字符串值 → 追加进一个 std::string 缓冲
      "badge_display" @0xb89738  **只看键是否存在**（0x51b1d8 `cset w8,eq` /
                                 0x51b1dc `orr w26,w26,w8`），值本身没读
    之后每个 profile 组装成 `VIPLeaderboardBadgeService::ProfileData`（16 字节，
    badgeDisplay 在 +8）插进 `mt::Array<ProfileData>`（`this+0x10` 计数、`this+0x18` 数据）。
    不返回 "player" 就只是不插任何 ProfileData，是安全的。
    """
    q = dict(parse_qsl(query, keep_blank_values=True))
    profiles = q.get("profiles") or ""
    print("[vip] vip_validation profiles=%s" % profiles, flush=True)
    # 两个键都是根对象的直接成员。不返回任何键的话 parseJsonData 会静默 return、
    # 不回调 listener，界面会一直等；所以至少把这两个键给出去。
    return 200, {"Content-Type": "application/json"}, {
        "player": profiles,
        "badge_display": True,
    }


def h_vip_badge_option(path, query, body, headers):
    """VIP 徽章显示开关。

    `tr::VIPLeaderboardBadgeService::sendBadgeOption(bool)` @0x51afe8（184 字节）：
      body = on ? "{\\"badge_display\\":true}"  (@0xb8965f)
                : "{\\"badge_display\\":false}" (@0xb896f8)
      url  = <serverAddr> + "/public/targeting/v1/vip_badge_option" (@0xb896d2)
      OnlineCore::postJson(listener, url, body, /*cmd=*/0x74, /*needAuth=*/1)  // 0x51b068
    这里把客户端请求里的 badge_display 原样回显（解析失败就回 true）。
    """
    try:
        req = json.loads(body.decode("utf-8", "replace") or "{}")
        val = bool(req.get("badge_display", True))
    except Exception:
        val = True
    print("[vip] vip_badge_option badge_display=%s" % val, flush=True)
    return 200, {"Content-Type": "application/json"}, {"badge_display": val}


def h_friends_update(path, query, body, headers):
    """好友同步回执 —— 必须**原样回显请求里的 `uplay` id**，否则好友被删。

    反汇编依据 `tr::OnlineFriends::onNetworkDataReceived` @0x51d784（cmd 0x65）：
      - `uplay` @0xb890d4 数组，元素必须是**字符串**；
      - 客户端拿本地好友表的每个 pid（条目 +0x81）去回包里比对
        （`0x51d844 json_strcmp([x21+0x28], x9+0x81)`）；
      - **未匹配就把该条目的标志位清零**（`0x51d864 str wzr,[x9,#0xac]`），
        收尾 `0x51da30 tbnz #3` 判定失败 ⇒ **好友被删除**。

    所以「什么都不回」等于「回 `{"uplay":[]}`」＝ **清空好友列表**。
    这里把请求的 id 原样回显，全部匹配，谁都不删。

    触发链：登录 → `GET /v2/profiles/me/friends`（规则桩，见 rules.json:98）
    → `OnlineFriends::onFriendlistRecieved` @0x51cee8 → 尾调用 `syncFriendList()`
    @0x51d0ac（cmd 0x65）→ 本端点。

    ⚠ 本端点走 `[OnlineCore+0x28]`（私服地址），而 `/v2/profiles/me/friends`
    的 base 是**硬编码** `https://public-ubiservices.ubi.com` @0xb85565，
    只能靠 DNS/hosts 劫持接管 —— 两者不是同一个 host。
    """
    try:
        req = json.loads(body.decode("utf-8", "replace") or "{}")
        uplay = [x for x in req.get("uplay") or [] if isinstance(x, str)]
    except Exception:
        uplay = []
    print("[friends] update → echo %d uplay id(s)" % len(uplay), flush=True)
    return 200, {"Content-Type": "application/json"}, {"uplay": uplay}


LEADERBOARD_PATH = os.path.join(HERE, "data", "leaderboards.json")
LEADERBOARD_LOCK = threading.Lock()


def _load_leaderboards():
    try:
        with open(LEADERBOARD_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------- 幽灵对手（排行榜）
# ★ 为什么要有这一块：真机导出的**内置幽灵**（index.json 里 builtin=True / 带
#   legacy_path，54 条、30+ 条赛道）owner 全是 `6f857655` —— 那是幽灵库里唯一
#   来自「别人」的数据（其余的 owner 都是玩家自己上传的 `<player-profile-id>`，见
#   server/data/ghosts/INDEX.md 的 owner 说明）。但排行榜是按 player pid 建行的，
#   幽灵从来就没进过榜，于是「全球 / 所有玩家」里永远只有玩家自己一行，
#   点进去也没有对手可以挑战。
#   这里把内置幽灵折成对手行：同一赛道按 drive_time 升序分给 OPPONENT_PIDS 里的
#   身份，drivetime 用幽灵自己的真实时间；pid→contentId 记在对手表里，
#   h_ghost 优先按它回**同一条**幽灵 —— 榜上显示的时间和实际跑出来的幽灵一致。
OPPONENT_PIDS = list(FRIEND_NAMES)          # 44444444 GhostRider / 55555555 TangoPro / 66666666 IronGear
_OPPONENT_CACHE = None


def _opponent_entries():
    """扫幽灵库，返回 ({pid: {board: row}}, {pid: {board: contentId}})，只算一次。"""
    global _OPPONENT_CACHE
    if _OPPONENT_CACHE is not None:
        return _OPPONENT_CACHE
    rows, ghosts = {}, {}
    try:
        records = acct.ghost_list()
    except Exception as exc:                 # 幽灵库坏了也不该把排行榜拖垮
        print("[opponent] 幽灵库读取失败：%s" % exc, flush=True)
        records = []
    by_track = {}
    for rec in records:
        if not (rec.get("stored") or rec.get("legacy_path")):
            continue                         # 只有 metadata、没有二进制的容器不算
        # ★ 赛道号在这里也掩一次：客户端会叠 0x800000 / 0x10000 / 0x100000 标志位，
        #   而 `h_ghost` 查询侧是按掩码后的裸 ID 找 `board = "track%d"` 的。
        #   之前两边一个掩一个不掩，表里是 track66633、查的是 track1097 ⇒ 永远 miss。
        track = acct.mask_track(rec.get("track_id"))
        time_ms = rec.get("drive_time") or rec.get("payload_drive_time")
        if not track or not time_ms:
            continue
        by_track.setdefault(track, []).append(rec)
    for track, recs in by_track.items():
        board = "track%d" % track
        recs.sort(key=lambda r: (r.get("drive_time") or 0, r.get("contentId") or 0))
        # 内置幽灵才折成假对手，撑起排行榜的行（行为与以前一致）。
        builtins = [r for r in recs if r.get("builtin") or r.get("legacy_path")]
        real_rows = _load_leaderboards()      # 一次读好，别在循环里重读盘
        for pid, rec in zip(OPPONENT_PIDS, builtins):
            lb_data, lb_upgrades = _ghost_appearance(track, rec, real_rows)
            rows.setdefault(pid, {})[board] = {
                "player": pid,
                "drivetime": int(rec.get("drive_time") or 0),
                "submittime": int(rec.get("created") or 0),
                # ★ 不能发 0：见 `_lb_data` —— data 是 LeaderBoardData 的
                #   外观位域，发 0 点进去挑战的幽灵就会「服装/车身喷漆不对、没有脑袋」。
                "data": lb_data,
                "upgrades": lb_upgrades,
                "extradata": 0,
                "updated": int(rec.get("updated") or 0),
            }
            ghosts.setdefault(pid, {})[board] = rec.get("contentId")
        # ★ 玩家自己/好友上传的幽灵按**真实 owner** 单独建索引。
        #   以前 `if not rec.get("builtin") and not rec.get("legacy_path"): continue`
        #   把这些记录整条丢掉 ⇒ 刚上传的幽灵既进不了 `ghost_of`、`h_replay_id`
        #   也只会回失败形状，等于「自己的幽灵永远无法被挑战、也拿不到自己的 id」。
        for rec in recs:
            own = str(rec.get("owner") or "")
            if own and own not in OPPONENT_PIDS:
                ghosts.setdefault(own, {})[board] = rec.get("contentId")
    _OPPONENT_CACHE = (rows, ghosts)
    print("[opponent] 内置幽灵折成 %d 个对手 / %d 条赛道" %
          (len(rows), len(by_track)), flush=True)
    return _OPPONENT_CACHE


def _load_ranked_boards():
    """真实榜单 + 幽灵对手行。

    ★ 对手**不进** leaderboards.json：_record_result 走的是原始
      _load_leaderboards()，_save_leaderboards 也就永远不会把对手固化到磁盘上，
      改幽灵库后对手榜会自动跟着变。
    """
    db = _load_leaderboards()
    rows, _ = _opponent_entries()
    for pid, boards in rows.items():
        for board, row in boards.items():
            db.setdefault(board, {}).setdefault(pid, row)
    # ★ 合成的"其他玩家"（午夜杯榜单）同样只在视图里，不落盘 —— 见 _weekly_fake_field。
    for board, entries in _weekly_fake_field().items():
        db.setdefault(board, {}).update(entries)
    return db


def _save_leaderboards(obj):
    os.makedirs(os.path.dirname(LEADERBOARD_PATH), exist_ok=True)
    # ★ Windows 上 os.replace 偶发 WinError 5（杀软/索引器短暂占用目标文件），
    #   事务性写盘因此要重试，否则会留下 leaderboards.json.tmp 且丢一次成绩。
    tmp = "%s.%d.tmp" % (LEADERBOARD_PATH, os.getpid())
    last = None
    for attempt in range(6):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            os.replace(tmp, LEADERBOARD_PATH)
            return
        except OSError as exc:            # PermissionError 也是 OSError
            last = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass
    print("[rank-save] 榜单落盘失败：%s" % last, flush=True)


def _record_result(profile_id, track_name, stats):
    """保存一条真实成绩；同一账号/赛道只保留最佳 drivetime。

    ★ 两个来源字段并不一致，所以是**合并**而不是整条覆盖：
        · 存档 highscores2 行 = [track, drivetime, data, upgrades, submittime]
          —— 有 drivetime/data/upgrades，**没有 score_value**；
        · batch_update 的 JSON —— 有 drivetime/score_value/data/upgrades。
      如果谁后到就把整条覆盖，score_value 会被存档同步清零。
      规则：drivetime 更小才算新纪录；时间相同则补齐缺失字段；时间更差直接丢弃。
    """
    if not profile_id or not track_name or not isinstance(stats, dict):
        return False
    try:
        drivetime = int(stats.get("drivetime", 0))
    except (TypeError, ValueError):
        return False
    if drivetime <= 0:
        return False
    clean = {
        "player": profile_id,
        "drivetime": drivetime,
        "submittime": int(stats.get("submittime", 0) or 0),
        "data": int(stats.get("data", 0) or 0),
        "upgrades": int(stats.get("upgrades", 0) or 0),
        "extradata": int(stats.get("extradata", 0) or 0),
        "updated": int(time.time()),
    }
    # 只有来源真的带了这个字段才写，避免用"不存在的 0"覆盖已有数据。
    for key in ("score_value", "global_score"):
        if key in stats and stats[key] is not None:
            try:
                clean[key] = float(stats[key]) if key == "global_score" else int(stats[key])
            except (TypeError, ValueError):
                pass
    if "_client_submittime" in stats:
        clean["_client_submittime"] = int(stats["_client_submittime"] or 0)
    with LEADERBOARD_LOCK:
        db = _load_leaderboards()
        board = db.setdefault(track_name, {})
        old = board.get(profile_id)
        if old is not None:
            old_time = int(old.get("drivetime", 0))
            if old_time < drivetime:
                return False                      # 更慢的一次，直接丢
            if old_time == drivetime:
                merged = dict(old)
                for k, v in clean.items():
                    if k in ("player", "drivetime", "updated"):
                        continue
                    if not merged.get(k) and v:
                        merged[k] = v             # 补齐缺失字段，不覆盖已有值
                if merged == old:
                    return False
                board[profile_id] = merged
                _save_leaderboards(db)
                return True
        board[profile_id] = clean
        _save_leaderboards(db)
    return True


def _u32(v):
    """存档里的 data/upgrades 是有符号 int，按 32 位无符号回放。"""
    try:
        return int(v) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 0


def _record_highscores_row(profile_id, row):
    """把存档 highscores2 的一行 [track, drivetime, data, upgrades, submittime] 入库。

    ★ 这一行是不是"跑过"完全看 drivetime：客户端给没跑过的赛道写成 0
      （实测 191 行里 163 行是 `[track, 0, 256, 0, 0]` 占位）。
      所以 drivetime > 0 就是"真的跑过"的唯一判据，不需要别的推断。
    """
    if not isinstance(row, (list, tuple)) or len(row) < 2:
        return False
    try:
        track = int(row[0])
        drivetime = int(row[1])
    except (TypeError, ValueError):
        return False
    if drivetime <= 0 or track <= 0:
        return False
    return _record_result(profile_id, "track%d" % track, {
        "drivetime": drivetime,
        "data": _u32(row[2] if len(row) > 2 else 0),
        "upgrades": _u32(row[3] if len(row) > 3 else 0),
        # ★ 存档行的 submittime 恒为 0（客户端从没填过）。直接回显会让榜单
        #   显示 1970-01-01，所以填"服务器收到这条成绩的时间" —— 真实值，不是编的。
        "submittime": int(time.time()),
        "_client_submittime": int(row[4] or 0) if len(row) > 4 else 0,
    })


def _ingest_highscores(profile_id, content):
    """从玩家上报的存档里同步成绩表。只收 drivetime > 0 的赛道。"""
    if not isinstance(content, dict):
        return 0
    rows = content.get("highscores2") or content.get("highscores") or []
    if not isinstance(rows, list):
        return 0
    n = 0
    for row in rows:
        if _record_highscores_row(profile_id, row):
            n += 1
    return n


def h_result_stats(path, query, body, headers):
    """接收真实跑图成绩。只收真正跑过的图，不制造任何记录。"""
    payload = _json_body(body)
    caller, err = acct.authenticate(headers)
    if err or not caller or caller.get("kind") != "account":
        return 401, {"Content-Type": "application/json"}, {"error": "invalid-credentials"}
    profile_id = caller["profileId"]
    endpoint = path.rstrip("/").rsplit("/", 1)[-1]
    accepted = 0

    if endpoint == "batch_update":
        # ★ 批量同步是启动/进度同步时把本地整张 highscores 表发上来。
        #   表里有 191 行，但**只有真正跑过的图 drivetime > 0**，
        #   其余 163 行是 [track, 0, 256, 0, 0] 的占位（解锁但没跑）。
        #   以前这里一律入库，就是"我没跑的也有记录"的根源。
        #   现在只收 drivetime > 0 的行，未跑过的图永远不会出现在榜单里。
        for item in (payload.get("updates") or []):
            if not isinstance(item, dict):
                continue
            track = str(item.get("track_name") or "")
            stats = item.get("stats") or {}
            if not re.fullmatch(r"track[0-9]+", track) or not isinstance(stats, dict):
                continue
            try:
                if int(stats.get("drivetime", 0) or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            if _record_result(profile_id, track, stats):
                accepted += 1
        print("[rank-save] profile=%s batch_update accepted=%d" % (profile_id, accepted),
              flush=True)
        return 200, {"Content-Type": "application/json"}, {"data": []}

    if endpoint in GLOBAL_LEADERBOARDS:
        # ★ 主界面总榜客户端**自己也会 POST 一份**上来（body 形状与 batch_update 相同，
        #   但 stats 里只有 data/global_score/drivetime/upgrades/submittime，**没有 track**）。
        #   以前它落到下面的 `track[0-9]+` 正则 → 400 invalid-track（实测 16 次全失败）。
        #   总榜在本服务器是**实时聚合视图**、不落库（见 _aggregate_global_entries 与
        #   _record_result 的 docstring），所以这份上传本来就无处可存：接受并丢弃。
        #   丢弃是安全的——聚合完全由单赛道记录算出来，不依赖这条自报数据。
        #   （GLOBAL_LEADERBOARDS 定义在本函数之后，函数体里引用它按调用时求值，没问题。）
        return 200, {"Content-Type": "application/json"}, {"data": []}

    track = endpoint.strip()
    if not re.fullmatch(r"track[0-9]+", track):
        return 400, {"Content-Type": "application/json"}, {"error": "invalid-track"}
    updates = payload.get("updates", []) if isinstance(payload, dict) else []
    if isinstance(updates, list) and updates:
        # 单赛道请求的 body 通常是 updates:[{stats:...}]；忽略其中可能
        # 被篡改的 track_name，赛道身份以 URL 为准。
        for item in updates:
            if isinstance(item, dict) and _record_result(profile_id, track, item.get("stats") or {}):
                accepted += 1
    elif isinstance(payload, dict):
        stats = payload.get("stats") or payload
        if _record_result(profile_id, track, stats):
            accepted = 1
    print("[rank-save] profile=%s track=%s accepted=%d" %
          (profile_id, track, accepted), flush=True)
    return 200, {"Content-Type": "application/json"}, {"data": []}


# ★ crazy 也在这套里：客户端 `OnlineLeaderboards::getLeaderboardName` @0x00509604 的
#   id 空间里 `0x100000 → "global_stats_crazy"`（与 0 → global_stats、0x10000 → donkey
#   并列），少一个它就会被当成普通 `track<N>` 榜去聚合/落库，对它的成绩上报还会吃
#   `400 invalid-track`（h_result_stats 只认 `track[0-9]+`）。
GLOBAL_LEADERBOARDS = {"global_stats", "global_stats_donkey", "global_stats_crazy"}


def _aggregate_global_entries():
    """从真实单赛道记录计算主界面总榜；不为未跑赛道创建行。"""
    with LEADERBOARD_LOCK:
        db = _load_ranked_boards()
    totals = {}
    for board, records in db.items():
        if board in GLOBAL_LEADERBOARDS or not board.startswith("track"):
            continue
        for profile_id, row in (records or {}).items():
            # ★ 午夜杯榜单里的合成对手不进总榜：那是碉堡的天梯，混进 120 个假人
            #   会把另一套玩法的名次彻底弄乱（合成行由 _weekly_fake_field 产生）。
            if profile_id in _WEEKLY_FAKE_PIDS:
                continue
            try:
                drivetime = int(row.get("drivetime", 0))
            except (TypeError, ValueError):
                continue
            if drivetime <= 0:
                continue
            out = totals.setdefault(profile_id, {
                "player": profile_id,
                "data": 0,
                "upgrades": 0,
                "submittime": 0,
                "drivetime": 0,
                "score_value": 0,
                "extradata": 0,
                "global_score": 0.0,
                "updated": 0,
                "tracks": 0,
            })
            # ★ data 是 LeaderBoardData 的**外观位域**（parseData/getOutfit/getBikeSkin
            #   直接解它），绝不能拿它当「跑过几条赛道」的计数器 —— 那样真人总榜行的
            #   data 只剩个位数，客户端解出来就是「服装/车身喷漆不对、骑手没有脑袋」。
            #   跟 upgrades/extradata 一样按位合并，计数另开 `tracks`（`_rank_entry`
            #   的白名单会把它挡在响应之外）。
            out["data"] |= int(row.get("data", 0) or 0)
            # upgrades/extradata 是位掩码，合并而非相加。
            out["upgrades"] |= int(row.get("upgrades", 0) or 0)
            out["extradata"] |= int(row.get("extradata", 0) or 0)
            out["tracks"] += 1
            out["submittime"] = max(out["submittime"], int(row.get("submittime", 0) or 0))
            out["drivetime"] += drivetime
            out["score_value"] += int(row.get("score_value", 0) or 0)
            if "global_score" in row:
                out["global_score"] += float(row.get("global_score") or 0)
            else:
                # 客户端单图提交没有 global_score；总榜分数用真实单图
                # score_value 的和推导，不生成任何额外赛道记录。
                out["global_score"] += float(row.get("score_value", 0) or 0)
            out["updated"] = max(out["updated"], int(row.get("updated", 0) or 0))
    rows = list(totals.values())
    rows.sort(key=lambda r: (-float(r["global_score"]), -int(r["tracks"]), r["player"]))
    return [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]


def _stored_entries(board, requested_players=None, keep_total=False):
    if board in GLOBAL_LEADERBOARDS:
        rows = _aggregate_global_entries()
    else:
        with LEADERBOARD_LOCK:
            rows = list((_load_ranked_boards().get(board) or {}).values())
        rows.sort(key=lambda r: (int(r.get("drivetime", 0)), str(r.get("player", ""))))
        rows = [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]
    total = len(rows)
    wanted = set(requested_players or [])
    if wanted:
        # 注意：过滤掉的只是**要展示给客户端的行**，rank 保持在全榜中的真实名次。
        rows = [r for r in rows if r.get("player") in wanted]
    return (rows, total) if keep_total else rows


def _rank_entry(row):
    return {
        "player": row["player"],
        "rank": int(row["rank"]),
        "stats": {k: row[k] for k in (
            "data", "upgrades", "submittime", "drivetime",
            "score_value", "extradata", "global_score") if k in row},
    }


def h_playerstats_ranking(path, query, body, headers):
    board = path.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    q = dict(parse_qsl(query, keep_blank_values=True))
    players = [x for x in (q.get("players") or "").split(",") if x]
    rows, total = _stored_entries(board, players, keep_total=True)
    # ★ playerCount 必须是**全榜人数**，不是过滤后给这个客户端看的行数：
    #   客户端拿它算「你超过了前 X%」，回过滤后的 1 会让百分位永远显示 100%。
    return 200, {"Content-Type": "application/json"}, {
        "leaderboard": board, "playerCount": total, "httpCode": 200,
        "results": [_rank_entry(r) for r in rows],
    }


def h_playerstats_stats(path, query, body, headers):
    board = path.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    q = dict(parse_qsl(query, keep_blank_values=True))
    players = [x for x in (q.get("players") or "").split(",") if x]
    rows = _stored_entries(board, players or [_caller_profile(headers)])
    return 200, {"Content-Type": "application/json"}, {
        "statboard": board,
        "results": [_rank_entry(rows[0])] if rows else [],
    }


def h_gift(path, query, body, headers):
    """礼物链 —— 反汇编见 `work/trials-frontier/notes/gift-v1.md`。

    URL = `<base>/public/gift/v1/<op>`，op 与 cmd 一一对应
    （`OnlineGifting::onNetworkDataReceived` 0x51f238 只认 0x3e..0x43）：

      0x3e give_golden_ticket (POST) ┐
      0x3f send_gifts         (POST) ├ 响应体客户端**一个字节都不解析**
      0x41 claim?type=%s      (GET)  │ （0x51f2b0–0x51f2e8 只把 body 截断成
      0x43 ad_reward          (POST) ┘   C 字符串就完事）→ 回 200 即可
      0x40 get_gifts          (GET)  → `parseGiftArray` 0x51f784
      0x42 gifts              (GET)  → `parseSentGifts` 0x51f888

    两处与兜底 `{"data": []}` 不兼容、必须单独处理的地方：

    1. **0x40 的响应根必须是 JSON 数组**。`parseGiftArray` 第一条指令
       `ldr w8,[x1,#0x30]; cmp w8,#2; b.ne` 就是判「根节点 type tag == 2（数组）」，
       回 `{"data": []}` 是个对象 → 第一跳就收工 → 永远「没有礼物」且静默无错。
       （安全：不是数组只是返回空列表，不崩。）

    2. **0x42 是唯一能写 `OnlineGifting+0x28`（server_time）的响应**。
       `GiftingManager::isUptoDate()` 读的正是 +0x28，而 0x40 从不写它，
       所以缺了 `server_time` 就会让
       `MenuzStateWarRoom::updateGiftingIndicator` 0x73999c 的
       `[m_appTicker] % 300 == 0`（300 帧 @56.4fps ≈ **5.32 秒**）
       永远为真 —— 战争房间无限重发 get_gifts。
       `gifts` / `config.types` 按 key 名查找，缺省只是空数组/空 map，一并给出更保险。
    """
    op = path.rstrip("/").rsplit("/", 1)[-1]
    if op == "gifts":
        return 200, {"Content-Type": "application/json"}, {
            "server_time": int(time.time()),
            "gifts": [],
            "config": {"types": []},
        }
    if op == "get_gifts":
        return 200, {"Content-Type": "application/json"}, []
    return 200, {"Content-Type": "application/json"}, {}


DYNAMIC_EXACT = [
    # gamecfg：启动序列的第一条（`GET /?product=101&portal=Google&version=…`）以及
    # 游客设备注册（`POST /?action=register_device&deviceuid=…`）。见 h_gamecfg。
    ("GET", "/", h_gamecfg),
    ("POST", "/", h_gamecfg),
    ("POST", "/public/resultservice/v1/enhancestats/batch_update", h_result_stats),
    ("POST", "/public/resultservice/v1/enhancestats/track", h_result_stats),
    ("POST", "/public/playerprogress/v1/progress", h_progress),
    ("GET", "/public/playerprogress/v1/progress", h_progress_latest),
    ("GET", "/public/playerprogress/v1/progress/version", h_progress_version),
    ("GET", "/public/playerprogress/v1/progress/status", h_progress_status),
    ("POST", "/public/playerprogress/v1/swap", h_progress_swap),
    ("GET", "/v2/profiles/me", h_profile_me),
    # ★ 会话端点必须注册为动态处理，否则会落到 rules.json 里那条写死的匿名桩：
    #   返回固定 profileId 11111111-… 且**没有 rememberMeTicket**，
    #   症状就是「每次重启都要重新登录」「登录了也没有分数记录和在线服务」。
    #   v1 = 用户名密码登录（真校验），v3 = 设备静默登录；GET 是会话续期。
    ("POST", "/v1/profiles/sessions", h_session),
    ("POST", "/v2/profiles/sessions", h_session),
    ("POST", "/v3/profiles/sessions", h_session),
    ("GET", "/v1/profiles/sessions", h_session),
    ("GET", "/v1/profiles", h_profiles_query),
    ("GET", "/public/receiptvalidation/v1/product/configuration", h_iap_products),
    ("GET", "/public/receiptvalidation/v1/verify_android", h_iap_verify),
    ("POST", "/public/receiptvalidation/v1/verify_android", h_iap_verify),
    # VIP 排行榜徽章（tr::VIPLeaderboardBadgeService，见三个处理器的 docstring）：
    #   registerMembership 走 /public/...；反作弊关闭时改走 /private/...direct_...
    ("POST", "/public/targeting/v1/vip_registration", h_vip_registration),
    ("POST", "/private/targeting/v1/direct_vip_registration", h_vip_registration),
    ("GET", "/public/targeting/v1/vip_validation", h_vip_validation),
    # sendBadgeOption 是 POST、getBadgeOption 是 GET，两者 URL 相同（ELF 里查不到
    # 调用点，是虚表调用），所以两种方法都要支持。
    ("GET", "/public/targeting/v1/vip_badge_option", h_vip_badge_option),
    ("POST", "/public/targeting/v1/vip_badge_option", h_vip_badge_option),
    # 礼包解锁白名单（ROADMAP 3「现时内购礼包」）。两个 configuration 变体共用
    # cmd 0x49，所以 GET/POST 都指向同一个处理器。
    ("GET", "/public/targeting/v1/condition_items", h_targeting_bundle_config),
    ("GET", "/public/targeting/v1/configuration", h_targeting_configuration),
    ("POST", "/public/targeting/v1/configuration", h_targeting_configuration),
    # 好友同步回执（必须原样回显 uplay，否则客户端删好友）。
    ("POST", "/public/friends/v1/update", h_friends_update),
]

DYNAMIC = [
    # 应用配置：里面的 sandbox url 是客户端 `setserverAddress` 的基址，
    # 必须按请求 Host 回显（否则 Java 侧永远拿 127.0.0.1）。见 h_app_configuration。
    ("GET", "/v1/applications/", h_app_configuration),
    ("GET", "/public/timeservice/v1/gettime", h_timeservice),
    # 排行榜与玩家统计（板名在路径末段，只能用前缀匹配）：
    #   /public/playerstats/v1/ranking/{track66633|track1097|legends|global_stats…}
    #   /public/playerstats/v1/stats/{...}?players=
    ("GET", "/public/playerstats/v1/ranking/", h_playerstats_ranking),
    ("GET", "/public/playerstats/v1/stats/", h_playerstats_stats),
    # A.N.B.A（Robotman）支线的对手查询。前缀匹配顺带兜住 robot_v2
    # （"%s/%s/match/v1/robot_v2?track_name=%s&score=%lu&range=%d" @0xb86362）。
    ("GET", "/public/match/v1/robot", h_match_robot),
    # 限时活动/赛季：basic_info 是整条支线的入口（POST 与 GET 两个版本真机都发过）。
    # 它此前落到 rules.json 的 "*" 兜底 {"data": []}，客户端拿到的 week_index 全是 0，
    # 于是活动列表恒为空。
    ("GET", "/public/liveevents/v1/weekly_track_system/basic_info", h_liveevents_basic_info),
    ("POST", "/public/liveevents/v1/weekly_track_system/basic_info", h_liveevents_basic_info),
    # 活动配置：URL 末段带周号（`config/%d`），只能前缀匹配。
    ("GET", "/public/liveevents/v1/weekly_track_system/config/", h_liveevents_config),
    ("POST", "/public/liveevents/v1/weekly_track_system/config/", h_liveevents_config),
    # 本周对手（无反汇编出来的参数，纯 GET；POST 变体一并用宽容端兜住）。
    ("GET", "/public/liveevents/v1/weekly_track_system/find_opponent", h_liveevents_find_opponent),
    ("POST", "/public/liveevents/v1/weekly_track_system/find_opponent", h_liveevents_find_opponent),
    # 奖励表：URL 末段是槽位数（`reward_config/%d`）。
    ("GET", "/public/liveevents/v1/weekly_track_system/reward_config/", h_liveevents_reward_config),
    ("POST", "/public/liveevents/v1/weekly_track_system/reward_config/", h_liveevents_reward_config),
    # 开赛/完赛/跳冷却/补重试次数——响应在客户端侧完全不被解析，见 h_liveevents_accept。
    ("POST", "/public/liveevents/v1/weekly_track_system/start_race", h_liveevents_accept),
    ("POST", "/public/liveevents/v1/weekly_track_system/end_race", h_liveevents_accept),
    ("POST", "/public/liveevents/v1/weekly_track_system/skip_cooldown", h_liveevents_accept),
    ("POST", "/public/liveevents/v1/weekly_track_system/refill_retry_count", h_liveevents_accept),
    # --- 碉堡 / PVP ---------------------------------------------------------
    # pvp_init 是总闸：它的响应里同时带 player_info + match_info + pvp_config。
    ("POST", "/public/pvp_matches/v1/pvp_init", h_pvp_init),
    ("POST", "/public/pvp_matches/v1/tracks", h_pvp_accept),
    ("GET", "/public/pvp_matches/v1/matches", h_pvp_matches),
    # 匹配下单（cmd 0x28）——见 h_pvp_new_ranked 上方注释：真正出对手的是 matches。
    ("GET", "/public/pvp_matches/v1/new_ranked", h_pvp_new_ranked),
    # 赛季横幅：注意它还要在 pick_dynamic 的「图片通配」之前判一次，见那里的注释。
    # 按前缀注册，改名（season.banner_path）不用改代码。
    ("GET", "/pvp_banner/", h_pvp_banner),
    # ⚠ 顺序有讲究：`players?profiles=` 的 path 是 /…/players，
    # 它是 /…/player/ 的前缀，必须排在前面，否则会被 h_pvp_player 抢走。
    # 回的是**数组**不是 {"data": …} —— 见 h_pvp_players 的注释（回对象就转圈）。
    ("GET", "/public/pvp_matches/v1/players", h_pvp_players),
    ("GET", "/public/pvp_matches/v1/player/", h_pvp_player),
    ("GET", "/public/pvp_matches/v1/pvp_config", h_pvp_config),
    ("GET", "/public/pvp_matches/v1/season/", h_pvp_season_data),
    ("POST", "/public/pvp_matches/v1/close_season", h_pvp_close_season),
    # 开赛（cmd 0x2c）：`OnlinePVP::startRace` @0x4fa22c 用 postJson 发
    # {"match_id":%d,"golden_ticket":"True"|"False","track":%d}；响应侧
    # @0x4fc358 不解析回包，但成功会开赛；服务器仍必须验证并持久扣票。
    ("POST", "/public/pvp_matches/v1/start_race", h_pvp_start_race),
    ("POST", "/public/pvp_matches/v1/race", h_pvp_race),
    ("POST", "/public/pvp_matches/v1/increase_rewards", h_pvp_increase_rewards),
    ("POST", "/public/pvp_matches/v1/close", h_pvp_close),
    ("GET", "/public/pvp_matches/v1/purchase_tickets", h_pvp_purchase_tickets),
    # --- 礼物 / 战争房间 ------------------------------------------------------
    # URL 末段是 op（get_gifts / gifts / claim?type= / give_golden_ticket /
    # send_gifts / ad_reward），只能前缀匹配；GET 与 POST 都要注册。
    ("GET", "/public/gift/v1/", h_gift),
    ("POST", "/public/gift/v1/", h_gift),
    ("POST", "/public/pvp_matches/v1/chips", h_pvp_chips),
]


DYNAMIC = [(method, prefix, _pvp_request(fn) if prefix.startswith("/public/pvp_matches/v1/") else fn)
           for method, prefix, fn in DYNAMIC]


def pick_dynamic(method, path):
    # 赛季横幅必须抢在下面那条「图片通配」前面：它的路径以 .png 结尾，
    # 否则会被 h_placeholder_image 吃掉，客户端下到的是 256x256 的占位方块，
    # 而且 2868 字节超过了 SaveFile 的 0x800（2048）上限。
    if method == "GET" and path.startswith("/pvp_banner/"):
        return h_pvp_banner, "dyn:pvp-banner"
    # 图片与好友头像：<base>/<pid>/picture?width=..&height=..（见 .rodata @0xb887cc）
    if method == "GET" and (path.lower().endswith(_IMAGE_EXT) or path.endswith("/picture")):
        return h_placeholder_image, "dyn:placeholder-image"
    # 结尾斜杠容错：真机确实会发 `GET /v1/profiles/`（OnlineRobotMissionProfileQuery
    # 查对手资料那条链），而 rules.json 里的静态桩只认 `/v1/profiles/` 之外的形式，
    # 不归一化就会回匿名档 11111111-1111-1111-1111-111111111111。
    stripped = path.rstrip("/") or path
    for m, p, fn in DYNAMIC_EXACT:
        if m == method and (path == p or (path != stripped and stripped == p)):
            return fn, "dyn:%s %s" % (m, p)
    if method == "POST" and path.startswith("/public/resultservice/v1/enhancestats/"):
        return h_result_stats, "dyn:result-stats"
    # 幽灵：userstorage v2 的内容仓库（客户端上传/检索自己的幽灵）。
    # 这一个处理器要按 HTTP 方法分派建/取/改/删，所以把 method 绑进去。
    if path.startswith("/public/userstorage/v2/"):
        return (lambda p, q, b, h: h_userstorage(method, p, q, b, h)), "dyn:userstorage-ghost"
    # 幽灵：resultservice 下的 ghost / replaydata / replay_id
    # （replay_id 这条路径里不含 ghost/replaydata 字样，必须单独先判，
    #   否则会掉进 resultservice 的通配规则里，登记就丢了）
    if path.endswith("/replay_id") and path.startswith("/public/resultservice/"):
        return h_replay_id, "dyn:replay-id"
    if _looks_like_ghost(path) and path.startswith("/public/resultservice/"):
        return (h_ghost_upload if method == "POST" else h_ghost), "dyn:ghost"
    for m, prefix, fn in DYNAMIC:
        if m == method and path.startswith(prefix):
            if prefix.startswith("/public/pvp_matches/v1/"):
                # Mutations must match the endpoint, not e.g. /close_typo.
                if not prefix.endswith("/") and stripped != prefix:
                    if not (prefix.endswith("/matches") and _PVP_MATCH_RE.fullmatch(stripped)):
                        continue
            return fn, "dyn:%s" % prefix
    return None, None


def pick_rule(rules, method, path):
    key = "%s %s" % (method, path)
    if key in rules:
        return rules[key], key
    # 前缀匹配，取最长
    best = None
    for k in rules:
        if k == "*" or " " not in k:
            continue
        m, _, p = k.partition(" ")
        if m != method:
            continue
        if path.startswith(p):
            if best is None or len(p) > len(best[1]):
                best = (rules[k], p)
    if best:
        return best[0], "prefix:%s" % best[1]
    if method + " *" in rules:
        return rules[method + " *"], method + " *"
    if "*" in rules:
        return rules["*"], "*"
    # 默认：200 空 JSON 对象
    return {"status": 200, "headers": {"Content-Type": "application/json"}, "body": {}}, "default"


def render(rule):
    status = int(rule.get("status", 200))
    headers = dict(rule.get("headers") or {})
    body = rule.get("body", {})
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    elif isinstance(body, (dict, list)):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif body is None:
        raw = b""
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = str(body).encode("utf-8")
    # allow <path>:bodyfile 形式的外部文件
    if isinstance(body, str) and body.startswith("@"):
        p = body[1:]
        p = p if os.path.isabs(p) else os.path.join(HERE, p)
        try:
            with open(p, "rb") as f:
                raw = f.read()
        except Exception as e:
            print("[rules] 读不到 body 文件 %s: %r" % (p, e), flush=True)
    return status, headers, raw


_WEBUI_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trials Frontier 本地私服</title>
<style>
 body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#1d1712;color:#eee;margin:0;padding:24px}
 h1{font-size:20px;margin:0 0 4px} .sub{color:#a99;font-size:13px;margin-bottom:20px}
 .card{background:#2a221b;border:1px solid #463829;border-radius:10px;padding:18px;max-width:760px;margin-bottom:18px}
 label{display:block;margin:10px 0 4px;font-size:13px;color:#cbb}
 input{width:100%;box-sizing:border-box;padding:9px;border-radius:6px;border:1px solid #54432f;background:#181310;color:#eee;font-size:14px}
 button{margin-top:14px;padding:10px 18px;border:0;border-radius:6px;background:#c8892b;color:#241a0c;font-weight:700;font-size:14px;cursor:pointer}
 button:hover{background:#e0a040}
 table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #3a2e22}
 #msg{margin-top:12px;font-size:14px;min-height:20px}
 .ok{color:#6ad06a} .bad{color:#e86a6a}
 code{background:#181310;padding:2px 5px;border-radius:4px}
</style></head><body>
<h1>特技摩托：前线 · 本地私服</h1>
<div class="sub">ROADMAP 第 2 条 —— 账号注册与登录已分离：<b>必须先在这里注册，游戏里才能登录。</b></div>

<div class="card">
  <h2 style="font-size:16px;margin:0">注册账号</h2>
  <label>账号（游戏里登录用，建议邮箱格式）</label><input id="u" autocomplete="off" placeholder="you@example.com">
  <label>密码</label><input id="p" type="password" placeholder="至少 6 位">
  <label>游戏内显示名（可留空）</label><input id="n" autocomplete="off" placeholder="留空则与账号相同">
  <button onclick="reg()">注册</button>
  <div id="msg"></div>
</div>

<div class="card">
  <h2 style="font-size:16px;margin:0">已注册账号</h2>
  <div id="list">载入中…</div>
  <button onclick="load()">刷新</button>
</div>

<script>
function say(t, ok){var m=document.getElementById('msg');m.textContent=t;m.className=ok?'ok':'bad';}
async function reg(){
  var u=document.getElementById('u').value.trim(), p=document.getElementById('p').value,
      n=document.getElementById('n').value.trim();
  if(!u||!p){say('账号和密码都要填。',false);return;}
  var r=await fetch('/__api/register',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:u,password:p,nameOnPlatform:n||u})});
  var j=await r.json();
  say(j.message||j.error||('HTTP '+r.status), !!j.ok);
  if(j.ok){document.getElementById('p').value='';load();}
}
async function load(){
  var r=await fetch('/__accounts'); var j=await r.json();
  var h='<table><tr><th>账号</th><th>显示名</th><th>profileId</th><th>注册时间</th></tr>';
  (j.accounts||[]).forEach(function(a){
    h+='<tr><td>'+a.username+'</td><td>'+(a.nameOnPlatform||'')+'</td><td><code>'+(a.profileId||'').slice(0,8)+'…</code></td><td>'+(a.created_iso||'')+'</td></tr>';
  });
  document.getElementById('list').innerHTML=h+'</table>';
}
load();
</script></body></html>
"""


# ------------------------------------------------ 后台管理页（/__admin）
# 页面本体与静态资源都放在 server/admin/ 下的**真实文件**里，不再往 Python
# 字符串里塞 HTML —— 改界面不用碰这个文件，也不引入任何构建步骤（纯标准库）。
#
# ★ 用「路径 -> 文件名」的白名单字典，而不是把 path 拼到目录后面：
#   拼路径就等于把 `..%2f..%2ftf_server.py` 这类穿越交给 OS 去判断，
#   白名单表里查不到就是 404，穿越无从谈起。
_ADMIN_DIR = os.path.join(HERE, "admin")
_ADMIN_FILES = {
    "/__admin": ("index.html", "text/html; charset=utf-8"),
    "/__admin/": ("index.html", "text/html; charset=utf-8"),
    "/__admin/app.css": ("app.css", "text/css; charset=utf-8"),
    "/__admin/app.js": ("app.js", "application/javascript; charset=utf-8"),
    # 文案单独放 JSON：Python 侧的离线自检能直接 load 它并核对中英键是否一一对应。
    "/__admin/i18n.json": ("i18n.json", "application/json; charset=utf-8"),
    # 官方物品目录（401 条，含中英名与分类），由 tools/build_item_catalog.py 生成。
    # 它只是游戏自带表的导出，没有玩家数据，所以跟静态资源一起裸给。
    "/__admin/items.json": ("items.json", "application/json; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "TFLocal/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):  # 关掉默认 stderr 噪声
        pass

    # ---------- 工具 ----------
    def _read_body(self):
        n = self.headers.get("Content-Length")
        if n:
            try:
                return self.rfile.read(int(n))
            except Exception:
                return b""
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            chunks = []
            while True:
                line = self.rfile.readline().strip()
                try:
                    sz = int(line.split(b";")[0], 16)
                except Exception:
                    break
                if sz == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(sz))
                self.rfile.readline()
            return b"".join(chunks)
        return b""

    def _handle(self, method):
        t0 = time.time()
        raw_path = self.path
        sp = urlsplit(raw_path)
        path, query = sp.path, sp.query
        body = self._read_body()

        # 内省端点
        # ★ /__log 不在这里抄近路：它必须和别的 /__* 一样过 _introspect 里的门禁，
        #   在 _handle 里提前 return 等于绕过访问控制（日志里有全部请求路径）。
        if path == "/__ping":
            self._send(200, {"Content-Type": "text/plain"}, b"pong\n")
            return
        if path.startswith("/__"):
            if self._introspect(path, query, body):
                return

        dyn, which = pick_dynamic(method, path)
        if dyn is not None:
            hdrs = {k: v for k, v in self.headers.items()}
            # 把真实来源 IP 塞进请求头，供 save_progress / serve_progress 判断
            # "同一台设备"（登录后继承匿名槽存档）用。客户端自己发的同名头会被覆盖。
            hdrs["X-TF-Client"] = self.client_address[0] if self.client_address else ""
            st, hd, obj = dyn(path, query, body, hdrs)
            status, headers, raw = render({"status": st, "headers": hd, "body": obj})
        else:
            rules = load_rules()
            rule, which = pick_rule(rules, method, path)
            status, headers, raw = render(rule)
        self._send(status, headers, raw)

        entry = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "method": method,
            "url": raw_path,
            "path": path,
            "query": dict(parse_qsl(query, keep_blank_values=True)),
            "req_headers": {k: v for k, v in self.headers.items()},
            "req_body": body[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "req_body_len": len(body),
            "rule": which,
            "status": status,
            "resp_body": ("<binary %d bytes>" % len(raw)) if which.startswith("dyn:placeholder-image")
                         else raw[:MAX_BODY_LOG].decode("utf-8", "replace"),
            "ms": round((time.time() - t0) * 1000, 1),
        }
        line = json.dumps(entry, ensure_ascii=False)
        with LOG_LOCK:
            RECENT.append(entry)
            if len(RECENT) > RECENT_MAX:
                del RECENT[: len(RECENT) - RECENT_MAX]
            try:
                os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass
        # 控制台精简输出
        mark = "" if which == "default" else ("  <- " + which)
        print(
            "%-6s %-70s -> %d  %4dms%s"
            % (method, (path + ("?" + query if query else ""))[:70], status, entry["ms"], mark),
            flush=True,
        )
        if body:
            print("        REQ  %s" % body[:400].decode("utf-8", "replace").replace("\n", " "), flush=True)
        if which == "default":
            print("        RESP %s" % raw[:200].decode("utf-8", "replace").replace("\n", " "), flush=True)
        elif which == "dyn:placeholder-image":
            print("        RESP <占位 PNG %d bytes>" % len(raw), flush=True)

    def _introspect(self, path, query, body=b""):
        """本地管理端点：/__accounts /__saves /__save /__sessions /__ghosts …"""
        q = dict(parse_qsl(query, keep_blank_values=True))
        if path == "/__ping":
            self._send(200, {"Content-Type": "text/plain"}, b"pong\n")
            return True

        def js(obj, status=200):
            self._send(status, {"Content-Type": "application/json"},
                       json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
            return True

        # ------------------------------------------------ 后台管理页 /__admin
        # ★ 静态页放在门禁**之前**：登录表单本身要先能加载出来。
        #   它不含任何数据，所有数据都走下面那些被门禁护住的 JSON 端点。
        if path in _ADMIN_FILES:
            name, ctype = _ADMIN_FILES[path]
            try:
                with open(os.path.join(_ADMIN_DIR, name), "rb") as f:
                    blob = f.read()
            except OSError as exc:
                return js({"ok": False, "error": "admin-ui-missing",
                           "path": os.path.join(_ADMIN_DIR, name), "detail": str(exc)}, 404)
            self._send(200, {"Content-Type": ctype, "Cache-Control": "no-store"}, blob)
            return True

        def set_admin_cookie(status, obj, token=None):
            """带 Cookie 的 JSON 响应：token=None 表示清除。"""
            cookie = "tf_admin=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (
                token or "", acct.ADMIN_SESSION_TTL if token else 0)
            # ★ 没有 Secure 标志是**故意**的：这个服务器只能走明文 HTTP（客户端
            #   manifest 也只允许明文），带 Secure 浏览器就不会回传 Cookie，
            #   登录会静默失效。HttpOnly + SameSite=Strict 已经够用。
            self._send(status, {"Content-Type": "application/json", "Set-Cookie": cookie},
                       json.dumps(obj, ensure_ascii=False).encode("utf-8"))
            return True

        if path == "/__api/admin/login":
            form = _json_body(body) or {}
            token, err = acct.admin_login(form.get("username"), form.get("password"))
            if token is None:
                return js({"ok": False, "error": err,
                           "message": "管理员账号或口令不对"}, 401)
            return set_admin_cookie(200, {"ok": True, "username": form.get("username"),
                                          "ttl": acct.ADMIN_SESSION_TTL}, token)
        if path == "/__api/admin/logout":
            acct.admin_logout(self._admin_token())
            return set_admin_cookie(200, {"ok": True})
        if path == "/__api/admin/me":
            who = acct.admin_by_token(self._admin_token())
            return js({"ok": bool(who), "username": (who or {}).get("username")})

        # ★★ 访问控制边界。服务器绑 0.0.0.0（局域网里谁都能连），这里就是唯一的墙。
        #    「公开」= 玩家在游戏里自助注册必须能打到，以及登录页自身。
        #    其余 /__* 全部要管理员 —— 其中包括改前是裸奔的 /__config(POST)、
        #    /__restore、/__api/login、/__api/password、/__api/delete。
        #    代价：在局域网里用同一台机器开两个客户端互测时要先登录一次，可接受。
        _PUBLIC = ("/__ping", "/__ui", "/__register", "/__api/register")
        # 用 startswith 而不是白名单表：新增端点默认是**关**的，忘了加门禁也不会漏。
        if path.startswith("/__") and path not in _PUBLIC:
            if not acct.admin_by_token(self._admin_token()):
                return js({"ok": False, "error": "admin-required",
                           "message": "需要管理员登录（在 /__admin 登录）"}, 401)

        if path == "/__accounts":
            return js({"count": len(acct.list_accounts_public()),
                       "accounts": acct.list_accounts_public()})
        if path == "/__log":
            with LOG_LOCK:
                return js(list(RECENT[-100:]))
        if path in ("/__register", "/__ui"):
            self._send(200, {"Content-Type": "text/html; charset=utf-8"},
                       _WEBUI_HTML.encode("utf-8"))
            return True
        if path == "/__api/register":
            form = {}
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                form = _json_body(body) or {}
            else:
                form = dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
            acc, err = acct.register_account(form.get("username"), form.get("password"),
                                            form.get("nameOnPlatform"))
            if acc is None:
                msg = {"bad-request": "用户名和密码都不能为空",
                       "exists": "这个账号名已经被注册了，换一个",
                       }.get(err, err or "注册失败")
                return js({"ok": False, "error": err, "message": msg}, 400)
            return js({"ok": True, "username": acc["username"],
                       "profileId": acc["profileId"], "message": "注册成功，可以在游戏里登录了"})
        if path == "/__api/login":
            form = _json_body(body) or {}
            acc, err = acct.login_account(form.get("username"), form.get("password"))
            if acc is None:
                return js({"ok": False, "error": err}, 401)
            return js({"ok": True, "username": acc["username"], "profileId": acc["profileId"]})
        if path == "/__api/password":
            form = _json_body(body) or {}
            acc, err = acct.set_password(form.get("username"), form.get("password"))
            if acc is None:
                return js({"ok": False, "error": err}, 400)
            return js({"ok": True, "username": acc["username"], "message": "口令已更新"})
        if path == "/__api/delete":
            form = _json_body(body) or {}
            who, err = acct.delete_account(form.get("username"))
            if who is None:
                return js({"ok": False, "error": err}, 400)
            return js({"ok": True, "username": who, "message": "账号已删除（存档目录保留）"})

        # ---------------------------------------------- 后台运维动作（要管理员）
        if path == "/__api/admin/info":
            # 后台要显示的「玩家注册入口 / 手机上的后台入口」——这两条地址是要发给
            # 别人的，所以基址复用 _public_host()：它**绝不回环**（在 PC 上用
            # 127.0.0.1 打开后台，这里也会换成局域网地址，正好是能发给玩家那种），
            # 并尊重 appcfg.public_host 覆盖。
            base = _public_host(self.headers)
            return js({"ok": True,
                       "username": (acct.admin_by_token(self._admin_token()) or {}).get("username"),
                       "register_url": "http://%s/__ui" % base,
                       "admin_url": "http://%s/__admin" % base})
        if path == "/__api/admin/grant":
            form = _json_body(body) or {}
            res, err = acct.grant_items(form.get("profile"), form.get("items") or [],
                                        form.get("paints") or [])
            if res is None:
                return js({"ok": False, "error": err,
                           "message": {"no-save": "这个存档槽没有 latest.json",
                                       "bad-profile": "没指定存档槽",
                                       "bad-grant": "下发内容不合法",
                                       "no-items2": "这个存档没有 items2",
                                       }.get(err, "下发失败：" + str(err))}, 400)
            return js({"ok": True, **res})
        if path == "/__api/admin/pvp":
            # 竞技场余额：改的是服务端 pvp_state.json，不需要玩家做任何操作。
            form = _json_body(body) or {}
            # GET 从查询串取存档槽，POST 从 JSON body 取。
            pid = q.get("profile") if self.command == "GET" else form.get("profile")
            if self.command == "GET":
                if not pid:
                    return js({"ok": False, "error": "bad-profile",
                               "message": "没指定存档槽"}, 400)
                return js({"ok": True, "player": pvp_read(pid)})
            res, err = pvp_grant(pid, form.get("fields") or {}, form.get("mode") or "add")
            if res is None:
                return js({"ok": False, "error": err,
                           "message": {"bad-request": "没指定存档槽或没填数量",
                                       "bad-mode": "模式只能是 add 或 set",
                                       }.get(err, "下发失败：" + str(err))}, 400)
            return js({"ok": True, **res})
        if path == "/__api/admin/weekly":
            # 午夜杯运营页：GET = 读（配置 + 现状 + 模板 + 最近改动），POST = 改参数。
            # ★ 改的参数**即改即生效**（配置按 mtime 热加载），但客户端那边的
            #   reward_config 要玩家退出午夜杯再进才刷新。
            if self.command == "POST":
                form = _json_body(body) or {}
                res, err = admin_weekly_apply(form.get("fields") or {})
                if res is None:
                    return js({"ok": False, "error": err, "message": _param_message(err)}, 400)
                payload = {"ok": True, **res}
            else:
                payload = {"ok": True}
            payload.update({
                "config": weekly_values(),
                "status": admin_weekly_status(),
                "tracks": track_catalog(),
                "templates": templates_for("weekly").get("weekly", []),
                "audit": audit_for(["weekly"], 20),
            })
            return js(payload)
        if path == "/__api/admin/bunker":
            # 碉堡运营页：GET = 读（字段表 + 现状 + 赛道/奖励/车辆下拉 + 模板 + 最近改动），
            # POST {fields:{…}} = 改参数。字段表在 `_BUNKER_FIELDS`，界面照着它画。
            payload = {"ok": True, "applied": []}
            if self.command == "POST":
                form = _json_body(body) or {}
                res, err = admin_bunker_apply(form.get("fields") or {})
                if res is None:
                    return js({"ok": False, "error": err, "message": _param_message(err)}, 400)
                payload.update(res)
            payload.update(bunker_payload())
            return js(payload)
        if path == "/__api/admin/undo":
            # 一条审计记录的撤销（两页共用；撤销本身也记审计，所以能来回切）。
            form = _json_body(body) or {}
            res, err = admin_undo(form.get("id") or q.get("id"))
            if res is None:
                return js({"ok": False, "error": err,
                           "message": {"bad-id": "没给审计编号",
                                       "not-found": "这条记录太旧了（只留最近 %d 条）" % AUDIT_KEEP,
                                       "bad-record": "这条记录没法撤销",
                                       }.get(err, "撤销失败：" + str(err))}, 400)
            return js({"ok": True, **res, "config": weekly_values()})
        if path == "/__api/admin/templates":
            # 参数模板：GET 列出（可按页筛），POST 存/套用/改名/删。
            if self.command == "POST":
                form = _json_body(body) or {}
                action = str(form.get("action") or "")
                page = str(form.get("page") or "weekly")
                name = form.get("name")
                if action == "save":
                    res, err = admin_template_save(page, name, form.get("values"))
                elif action == "apply":
                    res, err = admin_template_apply(page, name, form.get("parts") or "all")
                elif action == "copy":
                    res, err = admin_template_copy(page, name, form.get("new_name"))
                elif action == "rename":
                    res, err = admin_template_rename(page, name, form.get("new_name"))
                elif action == "delete":
                    res, err = admin_template_delete(page, name)
                else:
                    res, err = None, "bad-action"
                if res is None:
                    return js({"ok": False, "error": err, "message": _param_message(err)}, 400)
                # 套用会改配置 ⇒ 顺手把刷新过的生效值一起回给界面。
                hook = _PAGE_HOOKS.get(page) or {}
                return js({"ok": True, **res,
                           "templates": templates_for(page).get(page, []),
                           "config": hook["values"]() if hook.get("values") else None})
            res, err = admin_templates(q.get("page"))
            if res is None:
                return js({"ok": False, "error": err, "message": _param_message(err)}, 400)
            return js({"ok": True, **res})
        if path == "/__api/admin/rollback":
            form = _json_body(body) or {}
            snap, err = acct.rollback_save(form.get("profile"), form.get("ts"))
            if err:
                return js({"ok": False, "error": err}, 400)
            # ★ 把恢复点名字回给前端，界面才能立刻给出「撤销这次回滚」。
            return js({"ok": True, "profileId": form.get("profile"), "snapshot": snap,
                       "server_version":
                           (acct.load_progress(form.get("profile")) or {}).get("version")})
        if path == "/__api/admin/revert":
            form = _json_body(body) or {}
            res, err = acct.restore_snapshot(form.get("profile"), form.get("snapshot"))
            if res is None:
                return js({"ok": False, "error": err}, 400)
            return js({"ok": True, **res})
        if path == "/__api/admin/sessions/clear":
            form = _json_body(body) or {}
            n = acct.clear_sessions(form.get("username"))
            return js({"ok": True, "removed": n})
        if path == "/__api/admin/password":
            form = _json_body(body) or {}
            me = acct.admin_by_token(self._admin_token()) or {}
            pw = (form.get("password") or "").strip()
            if len(pw) < 8:
                return js({"ok": False, "error": "too-short",
                           "message": "管理员口令至少 8 位"}, 400)
            # ★ force=True：这是改自己的口令。admin_create 会顺手踢掉自己所有旧
            #   会话（包括当前这张），所以下面要重新签发一张，否则改完立刻被登出。
            who, err = acct.admin_create(me.get("username"), pw, force=True)
            if who is None:
                return js({"ok": False, "error": err}, 400)
            token, _ = acct.admin_login(who, pw)
            return set_admin_cookie(200, {"ok": True, "username": who,
                                          "message": "管理员口令已更新，其它设备的登录已失效"},
                                    token)

        if path == "/__devices":
            devs = acct.list_devices()
            return js({"count": len(devs), "devices": devs})
        if path == "/__sessions":
            db = acct._load(acct.SESSIONS, {})
            return js({"count": len(db), "sessions": db})
        if path == "/__saves":
            return js({"saves": acct.list_saves()})
        if path == "/__save":
            pid = q.get("profile") or acct.ANON_PROFILE_ID
            got = acct.load_progress(pid)
            if not got:
                return js({"error": "no save for %s" % pid}, 404)
            return js(got)
        if path == "/__history":
            pid = q.get("profile") or acct.ANON_PROFILE_ID
            return js({"profileId": pid, "history": acct.list_history(pid)})
        if path == "/__restore":
            pid = q.get("profile") or acct.ANON_PROFILE_ID
            ts = q.get("ts") or "latest"
            got = acct.restore_save(pid, ts)
            if not got:
                return js({"error": "no snapshot %s for %s" % (ts, pid)}, 404)
            return js({"ok": True, "profileId": pid, "ts": ts})
        if path == "/__leaderboards":
            # 排行榜诊断：track 榜是原始落库数据，global_stats 是实时聚合视图。
            db = _load_leaderboards()
            tracks = {}
            for board, records in sorted(db.items()):
                rows = sorted((records or {}).values(),
                              key=lambda r: int(r.get("drivetime", 0)))
                tracks[board] = [{"rank": i, "player": r.get("player"),
                                  "drivetime": r.get("drivetime"),
                                  "score_value": r.get("score_value")}
                                 for i, r in enumerate(rows, 1)]
            global_rows = [{"rank": r["rank"], "player": r["player"],
                            "tracks": r["data"], "total_drivetime": r["drivetime"],
                            "global_score": r["global_score"]}
                           for r in _aggregate_global_entries()]
            return js({"tracks": tracks,
                       "global_stats": global_rows,
                       "note": "global_stats 由真实单赛道记录实时聚合，不落库"})
        if path == "/__ghosts":
            root = acct.GHOST_DIR
            out = {}
            if os.path.isdir(root):
                for t in sorted(os.listdir(root)):
                    if t in ("store", "inbox") or not os.path.isdir(os.path.join(root, t)):
                        continue
                    out[t] = acct.list_ghosts(t)
            store = [{"contentId": r.get("contentId"), "track_id": r.get("track_id"),
                      "owner": r.get("owner"), "drive_time": r.get("drive_time"),
                      "frames": r.get("frames"), "size": r.get("size"),
                      "builtin": bool(r.get("builtin")), "stored": bool(r.get("stored"))}
                     for r in acct.ghost_list()]
            return js({"ghosts": out, "store": store,
                       "replays": acct.ghost_replays()[-20:],
                       "note": "ghosts=<赛道>/内置文件；store=客户端上传的内容仓库"})
        if path == "/__config":
            # 运营参数（匹配/赛季/限时活动）都住在这里。GET 看、POST 改——
            # 未来 WebUI 直接调这两个就够，不用重启服务器（mtime 热加载）。
            if self.command == "POST":
                try:
                    payload = json.loads((body or b"{}").decode("utf-8"))
                except Exception as exc:
                    return js({"ok": False, "error": "body 不是 JSON: %r" % (exc,)}, 400)
                key_path = payload.get("path")
                if isinstance(key_path, str):
                    key_path = [key_path]
                if not isinstance(key_path, list) or not key_path:
                    return js({"ok": False, "error": "path 必须是键列表，如 [\"matchmaking\",\"bot_wait_seconds\"]"}, 400)
                if "value" not in payload:
                    return js({"ok": False, "error": "缺少 value"}, 400)
                try:
                    cfg_set(key_path, payload["value"])
                except Exception as exc:
                    return js({"ok": False, "error": repr(exc)}, 400)
                print("[cfg] %s = %r" % (".".join(key_path), payload["value"]), flush=True)
                return js({"ok": True, "path": key_path, "value": payload["value"],
                           "config": tf_config()})
            now = int(time.time())
            win = cfg_int("matchmaking", "active_window_seconds", default=300) or 300
            rt = {
                "queue": [{"profileId": p,
                           "waited": now - (e.get("at", now) if isinstance(e, dict) else int(e or now)),
                           "match_id": e.get("match_id") if isinstance(e, dict) else None}
                          for p, e in _pvp_search.items()],
                "matches": [{"id": mid, "players": m.get("players"), "track": m.get("track"),
                             "bot": m.get("bot"), "age": now - m.get("at", now)}
                            for mid, m in sorted(_pvp_matches.items())],
                "active_players": [{"profileId": p, "seen_ago": now - ts}
                                   for p, ts in sorted(ACTIVE_PLAYERS.items()) if now - ts <= win],
                "tickets": [{"profileId": p, "tickets": st.get("tickets"),
                             "next_in": max(0, st.get("ts", 0) + (_pvp_ticket_limits()[1]) - now)
                             if st.get("ts") else 0}
                            for p, st in sorted(_pvp_tickets.items())],
                "chips": [{"profileId": p, "chips": _pvp_chips_for(p),
                           "tracks": len(st.get("tracks") or []),
                           "next_in": max(0, (cfg_int("chips", "per_track_seconds", default=3600) or 3600)
                                          - st.get("acc", 0))}
                          for p, st in sorted(_pvp_chips.items())],
                "config_path": CONFIG_PATH,
            }
            return js({"config": tf_config(), "runtime": rt,
                       "note": "POST /__config {path:[…],value:…} 即改即生效（mtime 热加载）"})
        if path == "/__help":
            # ★ 这是用户唯一的自发现入口：新增端点必须同步加到这里。
            #   带 [admin] 的要管理员 Cookie，不带的是公开的。
            return js({
                "admin_ui": "/__admin",
                "note": "除 [public] 外都需要先登录 /__admin（HttpOnly Cookie tf_admin，7 天）。",
                "endpoints": [
                    "[public] /__ping", "[public] /__ui", "[public] /__register",
                    "[public] POST /__api/register {username,password,nameOnPlatform}",
                    "POST /__api/admin/login {username,password} -> Set-Cookie",
                    "POST /__api/admin/logout", "GET /__api/admin/me",
                    "GET /__api/admin/info -> {register_url,admin_url}（发给玩家的地址）",
                    "POST /__api/admin/password {password}",
                    "POST /__api/admin/grant {profile,items:[{item_id,amount,mode}]}（存档物品，要玩家选「用云端」）",
                    "GET|POST /__api/admin/pvp {profile,fields:{golden_ticket,chips},mode}（竞技场余额，即时生效）",
                    "GET|POST /__api/admin/weekly（午夜杯运营：GET 配置+现状+模板+最近改动；POST {fields:{…}} 即改即生效）",
                    "GET|POST /__api/admin/bunker（碉堡运营：GET 字段表+现状+赛道/奖励/车辆下拉；POST {fields:{…}}，列表类整表替换）",
                    "POST /__api/admin/undo {id}（撤销一条参数改动，id 来自上面的 audit）",
                    "GET|POST /__api/admin/templates（参数模板：GET ?page=weekly|bunker；POST {page,action:save|apply|copy|rename|delete,name,new_name,parts}）",
                    "POST /__api/admin/rollback {profile,ts} -> {snapshot}",
                    "POST /__api/admin/revert {profile,snapshot}",
                    "POST /__api/admin/sessions/clear {username?}",
                    "/__log", "/__accounts", "/__devices",
                    "/__sessions", "/__saves", "/__save?profile=<pid>",
                    "/__history?profile=<pid>",
                    "/__restore?profile=<pid>&ts=<时间戳|latest>",
                    "/__ghosts（内置幽灵文件 + 上传的幽灵仓库 + replay_id 登记）",
                    "/__leaderboards（排行榜落库与主榜聚合）",
                    "/__config（匹配/赛季运营参数；POST {path,value} 即改即生效）",
                    "POST /__api/login {username,password}",
                    "POST /__api/password {username,password}",
                    "POST /__api/delete {username}"]})
        return False

    def _admin_token(self):
        """从 Cookie 里取管理员票据。只认 tf_admin 这一个键。"""
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "tf_admin":
                return v.strip()
        return ""

    def _send(self, status, headers, raw):
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            if not any(k.lower() == "content-length" for k in headers):
                self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_OPTIONS(self):
        self._handle("OPTIONS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reset-admin", nargs="?", const="", default=None, metavar="口令",
                    help="重建管理员口令并退出。不带值则随机生成一个。")
    args = ap.parse_args()

    if not os.path.exists(RULES_PATH):
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            json.dump({"*": {"status": 200, "body": {}}}, f, indent=2)

    # ★ 忘了管理员口令的兜底出口。不做「网页上重置」——那又变成一个无窗口期的
    #   后门，能跑这条命令的人本来就有控制台权限。
    if args.reset_admin is not None:
        pw = args.reset_admin or acct.admin_new_password()
        if len(pw) < 8:
            print("口令至少 8 位。", flush=True)
            return 1
        who, err = acct.admin_create("admin", pw, force=True)
        if who is None:
            print("重建管理员失败：%s" % err, flush=True)
            return 1
        print("管理员口令已重置： %s / %s" % (who, pw), flush=True)
        print("现在可以正常启动服务器了。", flush=True)
        return 0

    boot = acct.admin_bootstrap()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("Trials Frontier 本地服务器已启动： http://%s:%d" % (args.host, args.port), flush=True)
    print("规则文件： %s" % RULES_PATH, flush=True)
    print("请求日志： %s" % LOG_PATH, flush=True)
    print("后台管理页： http://127.0.0.1:%d/__admin  （手机用 http://%s:%d/__admin）"
          % (args.port, _lan_ip(), args.port), flush=True)
    if boot:
        user, pw = boot
        print("", flush=True)
        print("=" * 66, flush=True)
        print("  第一次启动：已创建后台管理员账号（口令只显示这一次）", flush=True)
        print("", flush=True)
        print("      用户名： %s" % user, flush=True)
        print("      口  令： %s" % pw, flush=True)
        print("", flush=True)
        print("  打开 http://127.0.0.1:%d/__admin 登录。" % args.port, flush=True)
        print("  忘了口令就重跑： python tf_server.py --reset-admin", flush=True)
        print("=" * 66, flush=True)
        print("", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("停止。", flush=True)
    return 0


if __name__ == "__main__":
    main()
