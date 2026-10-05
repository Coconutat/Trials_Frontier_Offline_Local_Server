#!/usr/bin/env python3
"""把客户端那张午夜杯奖励表转成"给人看 + 给 WebUI 用"的两份产物。

来源：客户端内容包里的 `/conf/wts_rewards.txt`（JSON，`{"RewardTypes":[{"Reward_N":[…]}]}`）。
本机抽取副本在 `tmp/packout/wts_rewards.txt`（`tmp/` 不入库，所以这里生成入库的摘要）。

产出：
  · `server/data/wts_rewards.json` —— 机器可读摘要（WebUI 直接读它渲染"池子里有什么"）
  · `work/trials-frontier/notes/weekly-reward-pools.md` —— 人读文档（含完整池子清单）

用法：
    python tools/wts_reward_doc.py [抽取出来的 wts_rewards.txt]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tmp", "packout", "wts_rewards.txt")
JSON_OUT = os.path.join(ROOT, "server", "data", "wts_rewards.json")
DOC_OUT = os.path.join(ROOT, "work", "trials-frontier", "notes", "weekly-reward-pools.md")

TIERS = ("platinum", "gold", "silver", "bronze", "wood")
TIER_CN = {"platinum": "platinum（≤1%）", "gold": "gold（≤10%）", "silver": "silver（≤25%）",
           "bronze": "bronze（其余，较好那半）", "wood": "wood（其余，最差档）"}


def load_pools(path):
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    pools = {}
    for block in raw.get("RewardTypes") or []:
        for key, items in (block or {}).items():
            pairs = []
            for it in items or []:
                pairs.append({
                    "item_id": it.get("ItemId"),
                    "amount": it.get("ItemAmount"),
                    "type": it.get("Type"),
                    "name": (it.get("Comment") or "").strip(),
                })
            pools[key] = pairs
    return pools


def pool_no(key):
    try:
        return int(str(key).rsplit("_", 1)[-1])
    except ValueError:
        return 999


def group(pairs):
    """按名字归并（同一件衣服有 3 个等级 → 3 个 id），保持首次出现顺序。"""
    out = []
    for p in pairs:
        for g in out:
            if g["name"] == p["name"]:
                g["ids"].append(p["item_id"])
                break
        else:
            out.append({"name": p["name"], "ids": [p["item_id"]], "amount": p["amount"]})
    return out


def variant_diff(pools):
    """每档的 3 套方案（`Reward_{i+1}` / `{i+6}` / `{i+11}`）之间到底差什么。

    返回 {tier: {"identical": bool, "pools": {key: {"unique": [{item_id,name}], "shared": [name]}}}}
    —— 「三套完全相同」的档位（真机上青铜/木头就是）轮换池子没有任何效果。
    """
    out = {}
    for i, tier in enumerate(TIERS):
        keys = ["Reward_%d" % (i + 1 + 5 * v) for v in range(3)]
        sets = [{(p["item_id"], p["name"]) for p in pools.get(k, [])} for k in keys]
        inter = set.intersection(*sets) if all(sets) else set()
        identical = len({frozenset(s) for s in sets}) == 1
        per = {}
        for k, s in zip(keys, sets):
            others = [o for k2, o in zip(keys, sets) if k2 != k]
            only = s - (others[0] | others[1])              # 真·独有：另两套都没有
            semi = ((s & others[0]) | (s & others[1])) - inter   # 只和另一套共享
            per[k] = {
                "only_this": [{"item_id": i2, "name": n} for i2, n in sorted(only)],
                "shared_with_one": [{"item_id": i2, "name": n} for i2, n in sorted(semi)],
                "shared_with_all": [{"item_id": i2, "name": n} for i2, n in sorted(inter)],
            }
        out[tier] = {"identical": identical, "pools": per}
    return out


def doc(pools):
    lines = []
    lines.append("# 午夜杯奖励池（`wts_rewards.txt`）对照表 —— 供 WebUI 控制用\n")
    lines.append("本文由 `python tools/wts_reward_doc.py` 生成（数据源：客户端内容包里的 "
                 "`/conf/wts_rewards.txt`，本机抽取副本 `tmp/packout/wts_rewards.txt`）。"
                 "机器可读版本：`server/data/wts_rewards.json`。\n")
    lines.append("## 1. 这张表是什么 / 不是什么\n")
    lines.append("- **是**客户端本地表：`WeeklyChallengeManager::loadConfig` @`0x006307ac` 用 "
                 "`datapack::DataFilePack::searchFile('/conf/wts_rewards.txt')` 读进来，"
                 "再 `WeeklyChallengeManager::parseJson` 解析。")
    lines.append("- **不是**服务端能改的东西：服务端只能决定「第几档奖杯用哪个 `Reward_N` 池子」"
                 "（`weekly.reward_ids` / `reward_slots`）。池子里的**内容**在客户端。")
    lines.append("- 池子里**没有**喷漆/蓝图/皮肤（15 个池子全扫过，`paint`/`blueprint`/`skin`/"
                 "`livery`/`decal` 零命中）。原版那些是从商店/报价/探险等别的系统出的。\n")
    lines.append("## 2. 档位 → 百分位（客户端 `getPlayerTrophyType` @`0x006353c8`）\n")
    lines.append("| 奖杯档 | 触发条件（服务端 `getPlayerRankPercent` @`0x00634548` 算出的百分位）| "
                 "默认池（第 i 档 → `Reward_{方案*5+i+1}`，方案 0/1/2）|")
    lines.append("|---|---|---|")
    for i, t in enumerate(TIERS):
        lines.append("| `%s` | %s | `Reward_%d` / `Reward_%d` / `Reward_%d` |"
                     % (t, TIER_CN[t], i + 1, i + 6, i + 11))
    lines.append("")
    lines.append("## 3. 15 个池子的内容（完整）\n")
    for key in sorted(pools, key=pool_no):
        pairs = pools[key]
        groups = group(pairs)
        n = pool_no(key)
        tier = TIERS[(n - 1) % 5] if n <= 15 else "?"
        lines.append("### `%s`（%d 件，档位 `%s`，方案 %d）\n"
                     % (key, len(pairs), tier, (n - 1) // 5))
        lines.append("| 名字 | item id | 数量 |")
        lines.append("|---|---|---|")
        for g in groups:
            ids = ", ".join(str(x) for x in g["ids"])
            lines.append("| %s | %s | %s |" % (g["name"] or "?", ids, g["amount"]))
        lines.append("")
    lines.append("## 4. 三套方案（方案 0/1/2）之间到底差什么\n")
    lines.append("客户端要的是 `reward_config/<上周周号>`，原版服务器按那一周回**对应的一套**"
                 "（也就是内容随周/赛季轮换：基础套 / 圣诞·情人节套 / 万圣节·圣诞套）。"
                 "所以 `Reward_1` 与 `Reward_6`、`Reward_11` 的区别就是**限时/节日物品 + 几条赛道·几台车**，"
                 "其余条目三套共享。\n")
    diff = variant_diff(pools)
    for i, tier in enumerate(TIERS):
        info = diff[tier]
        keys = ["Reward_%d" % (i + 1 + 5 * v) for v in range(3)]
        lines.append("### `%s`：%s\n" % (tier, "**三套完全相同 ⇒ 轮换池子没有任何效果**"
                                        if info["identical"] else "三套有差别"))
        if info["identical"]:
            lines.append("（这三套的内容逐条一样，想让这一档有变化只能用 `reward_slots` 多给几件，"
                         "或把这一档改指到别的池子。）\n")
            continue
        lines.append("| 池 | **真·独有**（另两套都没有） | 只和另一套共享 |")
        lines.append("|---|---|---|")
        for k in keys:
            uniq = info["pools"][k]["only_this"]
            semi = info["pools"][k]["shared_with_one"]
            f = lambda lst: "、".join("%s(%s)" % (u["name"], u["item_id"]) for u in lst) or "（无）"
            lines.append("| `%s` | %s | %s |" % (k, f(uniq), f(semi)))
        shared = info["pools"][keys[0]]["shared_with_all"]
        lines.append("")
        lines.append("三套共享（%d 条）：%s\n" % (len(shared),
                   "、".join("%s(%s)" % (u["name"], u["item_id"]) for u in shared) or "（无）"))
    lines.append("## 5. 服务端怎么用（WebUI 要写的两个键）\n")
    lines.append("```json")
    lines.append('"reward_slots": 1,                      // 1..8：每档一次发几件（每个槽 = 一个池子的一件）')
    lines.append('"reward_ids": {"platinum": [3, 2, 4]}   // 按档位写死池子（循环使用）；空 = 内置规则')
    lines.append("```\n")
    lines.append("- **想给更多只能加槽**：每件的**数量**（20 宝石 / 25000 金币 / 车×2 / 5 张金票）"
                 "写死在客户端表的 `ItemAmount` 里，wire 上 pair 的第二个数**不是数量** —— "
                 "`getRewardItemForSlot` @`0x00635880` 里它唯一一次被用是 "
                 "`0x00635b80 lsr x3, x20, #0x20`（当「本地查不到时的后备池号」）。"
                 "所以「更多宝石」= 多叠几个宝石池的槽（`reward_slots` 调大 + `reward_ids` 里重复写 `4`/`9`/`14`）。")
    lines.append("- 槽数 > 该档池子个数时池子会**循环**（例如只给 3 个池子却要 5 槽 ⇒ 前三个池子出现两次）。")
    lines.append("- `reward_ids` 的每个值是**池子编号数组**（1..15，非法值会被忽略并回退内置规则）。")
    lines.append("- 内置规则：第 `i` 档（0..4）用 `Reward_{v*5+i+1}`，`v = (base+k)%3`，"
                 "`k` 是槽序号，`base` 按 pid 每次请求轮转 —— 这是为了绕开客户端那个"
                 "**不播种的 `rand()`**（见下）。")
    lines.append("- 想「每档都指定」就把五档都写上；只写一档时其余走内置规则。\n")
    lines.append("## 6. 三个必须知道的坑\n")
    lines.append("1. **客户端 `rand()` 不播种**：`getRewardItemForSlot` @`0x00635880` 里 "
                 "`bl rand` → `rand() % (池子件数)` 挑一件；glibc 首个 `rand()` 恒为 `1804289383`，"
                 "`% 23 = 11` ⇒ 池子不变就**永远是同一件**（真机 bug：连领两次同一张地图）。"
                 "所以服务端要换池子，或一次给多个槽。")
    lines.append("2. **一次进入模式只拉一次 `reward_config`**：客户端会缓存到离开模式为止 —— "
                 "改了配置要让玩家**退出午夜杯再进**才生效（不用重启游戏）。")
    lines.append("3. **wire 形状不能乱**：根对象每个成员 = 一个奖杯档，值必须是对象且"
                 "`reward` 为**第一个成员**、再带一个**等长**兄弟数组"
                 "（`parseRewardsSlot` @`0x00505d28` 无条件读 `first_child->next`，只给一个成员会崩）。"
                 "槽数量 = 数组长度，每个槽发一件。")
    lines.append("")
    lines.append("## 7. 建议的 WebUI 交互\n")
    lines.append("- 五档各一行：下拉/多选池子（选项直接读 `server/data/wts_rewards.json` 渲染内容预览），"
                 "外加一个 1..8 的槽数滑块 → 写回 `tf_config.json` 的 `weekly.reward_ids` / "
                 "`weekly.reward_slots`（服务端会把槽数夹在 1..8）。")
    lines.append("- 校验：池子编号 1..15、数组非空、槽数 1..8；保存后提示「玩家需退出午夜杯再进」。")
    lines.append("- 预设：`整车×3 = [3,8,13]`、`服装×3 = [2,7,12]`、`宝石/金票×3 = [4,9,14]`、"
                 "`混合 = [3,2,4]`（默认）。\n")
    return "\n".join(lines) + "\n"


def main():
    pools = load_pools(SRC)
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    payload = {
        "_note": "午夜杯奖励池摘要，由 tools/wts_reward_doc.py 从客户端 /conf/wts_rewards.txt 生成；"
                 "服务端只用来选池子（weekly.reward_ids / reward_slots），池子内容在客户端本地。",
        "tiers": {t: [i + 1, i + 6, i + 11] for i, t in enumerate(TIERS)},
        "variant_diff": variant_diff(pools),
        "pools": {k: pools[k] for k in sorted(pools, key=pool_no)},
    }
    with open(JSON_OUT, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(DOC_OUT), exist_ok=True)
    with open(DOC_OUT, "w", encoding="utf-8") as fp:
        fp.write(doc(pools))
    print("写了 %s（%d 个池子）" % (JSON_OUT, len(pools)))
    print("写了 %s" % DOC_OUT)


if __name__ == "__main__":
    main()
