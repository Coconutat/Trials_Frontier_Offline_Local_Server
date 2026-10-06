r"""把游戏自带的物品目录抽成后台能用的清单：server/admin/items.json

用法：
    python tools\\build_item_catalog.py                      # → server/admin/items.json  (Windows)
    python tools/build_item_catalog.py --packout <目录> --out <文件>

真源是 content.dat 里解出来的两个官方表（`tmp/packout/all/`，见 notes/item-ids.md 第 0 节）：

  * 各 `*.bin` 配置里的奖励/商店条目 —— 每条形如
        {"Type": 0, "ItemId": 275, "ItemAmount": 1,
         "TextureName": "/MENUZ/HOMESHACK/RIDER_19_HELMET_ON.PNG",
         "NameId": "WSO_PUMPKINKING_TO..."}
    `ItemId` 就是存档 items2 的键（真机校对过：295/735/235/570 全对），`NameId` 是本地化键。

  * LOCF 本地化表 `1516_*` = 英文、`1523_*` = 简体中文。格式：
        'LOCF' + u8 版本 + u32 条目数 + [u32 keyHash][u16 len][len 字节，含结尾 NUL]…
    键哈希 = mt::String::getHashCode（下面那个 `gh`），跟 content.dat 的路径哈希同一个函数。

用法：
    python tools\\build_item_catalog.py                      # → server/admin/items.json
    python tools\\build_item_catalog.py --packout <目录> --out <文件>

⚠ 这不是构建步骤，是**偶尔重跑一次**的取材工具：产物 items.json 已入库，服务器只读它。
   重跑需要先把 content.dat 解包到 tmp/packout/all/（`python tmp\itemdb_extract.py`）。

分类的「verified」是**真机证据强度**，不是猜的：
  * 计数类（货币/零件/消耗品）：真机存档里就是 5=1、6=8、150=109 这样的计数。
  * 0/1 类（服装部件/蓝图）：真机存档里 205=0、225=1、414=0，客户端自己「获得物品」也写 +id=1。
  * 涂装(type 2) / 赛道(type 1) / 赛道碎片(type 3)：**存档里没找到可信的写法**，
    而且涂装的 id（3–107）与零件 id（5–54）挤在同一个 items2 键空间里，
    按 id 下发给谁看都分不清 ⇒ 标 verified=false，界面上如实说「不保证生效」。
"""
import argparse
import collections
import glob
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def gh(s):
    """mt::String::getHashCode（32 位，UTF-8 逐字节）。"""
    w8 = len(s) & 0xFFFFFFFF
    h = 0
    for ch in s.encode("utf-8", "replace"):
        h = (w8 * ch + h) & 0xFFFFFFFF
        w8 = (((w8 & 0xFFFF) * 0x4650) + (w8 >> 16)) & 0xFFFFFFFF
    return h


def parse_locf(path):
    """→ {keyHash: text}；顺序解析，坏文件返回空表而不是抛。"""
    data = open(path, "rb").read()
    if data[:4] != b"LOCF":
        return {}
    count = struct.unpack_from("<I", data, 5)[0]
    p, out, n = 9, {}, 0
    while p + 6 <= len(data) and n < count:
        h, ln = struct.unpack_from("<IH", data, p)
        if ln == 0 or p + 6 + ln > len(data):
            break
        out[h] = data[p + 6:p + 6 + ln].rstrip(b"\x00").decode("utf-8", "replace")
        p += 6 + ln
        n += 1
    return out


def find_table(pat, packout):
    hits = sorted(glob.glob(os.path.join(packout, pat + "_*.bin")))
    if not hits:
        sys.exit("找不到本地化表 %s_*.bin（%s）" % (pat, packout))
    return hits[0]


def load_json_tolerant(raw):
    """游戏自带的几个文本表有原厂手写瑕疵（尾逗号、// 注释、漏逗号），逐个策略重试。"""
    txt = raw.decode("utf-8", "replace")
    cands = [
        txt,
        re.sub(r",(\s*[}\]])", r"\1", txt),
        re.sub(r"//[^\n]*", "", txt),
        re.sub(r"//[^\n]*", "", re.sub(r",(\s*[}\]])", r"\1", txt)),
    ]
    for c in cands:
        try:
            return json.loads(c)
        except Exception:
            pass
    c = cands[1]                                   # 按报错位置插逗号（漏逗号那种 typo）
    for _ in range(6):
        try:
            return json.loads(c)
        except json.JSONDecodeError as e:
            if "Expecting" not in e.msg and "delimiter" not in e.msg:
                return None
            c = c[:e.pos] + "," + c[e.pos:]
        except Exception:
            return None
    return None


# 货币的名字：官方商店条目里给的是「大型金币包」这种礼包名，这里用最直白的叫法。
NAME_OVERRIDE = {1: ("Coins", "金币"), 2: ("Gems", "钻石")}


def walk_itemids(node, out):
    if isinstance(node, dict):

        if isinstance(node.get("ItemId"), int):
            out.append(node)
        for v in node.values():
            walk_itemids(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_itemids(v, out)


def category(iid, node):
    """①排序即优先级。返回 (cat_key, verified)。"""
    if iid in (1, 2):
        return "currency", True
    tex = (node.get("TextureName") or "").upper()
    typ = node.get("Type")
    if typ == 2:
        return "paint", False
    if typ in (1, 3):                            # 赛道与其碎片合成一张卡（都是未验证）
        return "track", False
    if 5 <= iid <= 54:
        return "parts", True
    if "HOMESHACK/RIDER_" in tex:
        return "outfit", True
    if "ITEM/BLUEPRINT_" in tex:
        return "blueprint", True
    return "consumable", True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packout", default=os.path.join(ROOT, "tmp", "packout", "all"))
    ap.add_argument("--out", default=os.path.join(ROOT, "server", "admin", "items.json"))
    args = ap.parse_args()

    en = parse_locf(find_table("1516", args.packout))
    cn = parse_locf(find_table("1523", args.packout))
    if not en or not cn:
        sys.exit("本地化表解析失败（en=%d cn=%d 条）" % (len(en), len(cn)))

    entries, files, bad = {}, collections.Counter(), []
    for p in sorted(glob.glob(os.path.join(args.packout, "*.bin"))):
        raw = open(p, "rb").read()
        if raw[:4] == b"LOCF" or b'"ItemId"' not in raw:
            continue
        doc = load_json_tolerant(raw)
        if doc is None:
            bad.append(os.path.basename(p))
            continue
        found = []
        walk_itemids(doc, found)
        for node in found:
            iid = node["ItemId"]
            prev = entries.get(iid)
            if prev is None or (not prev.get("NameId") and node.get("NameId")):
                entries[iid] = node                  # 有本地化键的记录优先
            files[os.path.basename(p)] += 1

    items, cats = {}, collections.Counter()
    for iid, node in sorted(entries.items()):
        if iid == 135:                               # 「Pack of Tickets」= 竞技场金票，
            continue                                 # 走 pvp_state.json，不进存档 items2
        key = node.get("NameId") or ""
        e = en.get(gh(key), "") if key else ""
        c = cn.get(gh(key), "") if key else ""
        e, c = NAME_OVERRIDE.get(iid, (e, c))    # 货币用最直白的叫法，不用商店礼包名
        cat, verified = category(iid, node)
        cats[cat] += 1
        items[str(iid)] = {
            "id": iid, "cat": cat, "t": node.get("Type"),
            "en": e or (node.get("Comment") or "").strip(),
            "cn": c or e or (node.get("Comment") or "").strip(),
            "key": key, "verified": verified,
        }

    # 赛道碎片 id 与「赛道」同族，合到一张卡里给运维看，别单开一类天天被点错。
    out = {
        "source": {"packout": os.path.basename(args.packout),
                   "en": "1516", "cn": "1523",
                   "items": len(items), "skipped_files": bad},
        "categories": [
            {"key": "currency", "en": "Currency", "cn": "货币"},
            {"key": "consumable", "en": "Consumables & boosts", "cn": "消耗品 / 加速"},
            {"key": "parts", "en": "Bike parts", "cn": "摩托车零件"},
            {"key": "outfit", "en": "Rider outfits", "cn": "骑手服装"},
            {"key": "blueprint", "en": "Bike blueprints", "cn": "摩托蓝图"},
            {"key": "paint", "en": "Bike paints (unverified)", "cn": "车漆涂装（未验证）"},
            {"key": "track", "en": "Tracks & pieces (unverified)", "cn": "赛道与碎片（未验证）"},
        ],
        "items": items,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.write("\n")

    named = sum(1 for v in items.values() if v["en"])
    print("写入 %s：%d 条物品（有英文名 %d），分类 %s，%d 个配置解析失败"
          % (args.out, len(items), named, dict(cats), len(bad)))
    for b in bad[:5]:
        print("  失败 %s" % b)


if __name__ == "__main__":
    main()
