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
  * 涂装(type 2) **不是** items2 的键，见下面 ★ 涂装；赛道(type 1) / 赛道碎片(type 3)：
    id 与别的名字空间挤在一起，存档里也没找到可信的写法 ⇒ 标 verified=false，界面上如实说明。

★ 服装（`outfits`）另有一条来源，因为**整整一半的套装部件从来没在任何配置里出现过**
（隐藏/未上架的套装：High Roller、Henchman Black、Polar Vortex …），奖励表里挖不到：

  * `/conf/customization.txt`（`0007_*`）一条 Rider = 一整套，字段里有官方名
    (`NameStringId` = `OUTFIT_%02d_NAME`)、描述、**套装效果** `BonusPower` +
    `BonusPowerDescriptionStringId` = `OUTFIT_%02d_POWER`、`UnlockType`、`ItemType`。
  * **部件 id = `ItemType * 5 + tier`，tier 0/1/2 = 头盔 / 上衣 / 裤装**。部件名的 LOCF 键就是
    `ITEM_<ItemType>_<tier>`（`ITEM_111_0` = "Arctic Explorer Helmet Piece"/北极探险家头盔），
    但只有极少数套装给部件单独起过名，其余部件显示的就是套装名。
  * 最早那批套装（Rider ID 0–19：Survivor / Stuntman / Samsarian / Rebel / Priest …）的记录里
    **没有 `ItemType` 字段**，它们的 type = `40 + Rider ID`（DOGFIGHTER ID 1 → 41 → 205/206/207、
    Eggman ID 17 → 57 → 285/286/287，而 `ITEM_57_*` 的官方部件名正是 "The Eggman … Piece"；
    真机存档里 200-202 / 215-217 / 250-252 … 这些块也都确实存在）⇒ 80 套全部能定位。
  * 名称空间有重叠（`ItemId` 只在同一个 Type 内唯一：635 = 消耗品 "Super Magnet"，
    同时又是 type 127 的 tier 0），所以**只能按「套」下发**，不能靠 id 区间猜类别。

★ 涂装（`paints`）同样另有一条来源，而且**它的编号根本不是 items2 的键**：

  * `/conf/bikes.txt`（`0002_*`）里 `SkinData` = 全部 108 款涂装（`ID` 0..107），每条
        {"ID": 3, "Name": "Snakebite", "BikeID": 7, "SkinIndex": 0,
         "TextureName": "/GFX/OBJECT/BIKE/BIKE_06_B.PNG", 可选 "DiamondCost"/"MissionUnlock"}
    `BikeData` = 19 辆车，键就是 `BikeID`，名字在 `Comment`（Armadillo / Tango / … / Donkey）。
  * 奖励/商店条目里 `Type == 2` 的 `ItemId` 指的就是 `SkinData.ID`（配置自己的注释：
    "ItemId points to ID defined in bikeskins.txt"）—— 108 款里有 66 款上过架，能拿到官方
    中英文名；剩下的只有 SkinData 的内部名（英文），没有官方译文。
  * ★★ 存档里的编码（真机存档 + 反汇编双向确认）：
        items2 键 = `664 + BikeID`（= `665 + (BikeID-1)`，`PlayerItems::getCustomBikeTextureItemId`）
        值 = `((当前装备的 SkinIndex + 1) << 24) | 拥有位掩码`（位 i = `SkinIndex == i` 已拥有）
    ccb 的档里 665/666/668/677/678/680 六条逐位解出来全部自洽（active 都 ∈ mask，且每个位都
    对得上真实存在的 (BikeID, SkinIndex)）⇒ 这是**明文**，反汇编里的 XOR/rotate 只是内存内的
    混淆（`m_items[i] = 0x0AB1D4F5 ^ rol(M, 7)` 之类，0x0AB1D4F5 是全库通用的常量）。
    ⇒ 涂装**只能按「车」下发**（置一位），不能按 id 写 `items2[id]`；id 3–107 里有一半还同时是
    零件 id（5–54）⇒ 按 id 下发不但无效，还会写到别人的计数上。
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
    for _ in range(16):                            # 0010 那份奖励表有 12 处漏逗号，6 处不够
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

# 最早那批套装（Rider ID 0–19）的记录里没有 ItemType 字段，type 恰好是 40 + Rider ID。
OLD_OUTFIT_TYPE_BASE = 40


def find_customization(packout):
    """按内容找 /conf/customization.txt（不认文件名哈希，那是构建期随机串）。"""
    for p in sorted(glob.glob(os.path.join(packout, "*.bin"))):
        raw = open(p, "rb").read()
        if b'"NameStringId"' in raw and b'"Rider"' in raw:
            return p
    return None


def load_outfits(packout, en, cn):
    """→ {setKey: {...}}；setKey = "OUTFIT_34#116"（黑/橙两套共用同一个 OUTFIT 名）。"""
    path = find_customization(packout)
    if not path:
        return {}
    doc = load_json_tolerant(open(path, "rb").read()) or {}
    loc = lambda key: (en.get(gh(key), ""), cn.get(gh(key), ""))
    out = {}
    for r in doc.get("Rider") or []:
        oid = r.get("NameStringId") or ""
        m = re.fullmatch(r"OUTFIT_(\d+)_NAME", oid)
        if not m:
            continue
        idx = int(m.group(1))
        typ, src = r.get("ItemType"), "ItemType"
        if not isinstance(typ, int):
            typ, src = OLD_OUTFIT_TYPE_BASE + int(r.get("ID") or 0), "40+ID"
        e, c = loc(oid)
        de, dc = loc("OUTFIT_%02d_DESCRIPTION" % idx)
        pe, pc = loc("OUTFIT_%02d_POWER" % idx)
        parts = [typ * 5 + k for k in range(3)]
        pnames = {str(parts[k]): loc("ITEM_%d_%d" % (typ, k)) for k in range(3)}
        ut = r.get("UnlockType")
        out["%s#%d" % (oid, typ)] = {
            "key": oid, "id": int(r.get("ID") or 0), "idx": idx,
            "en": e, "cn": c, "comment": (r.get("Comment") or "").strip(),
            "desc_en": de, "desc_cn": dc,
            "bonus": (r.get("BonusPower") or "").strip(),
            "bonus_en": pe, "bonus_cn": pc,
            "type": typ, "type_src": src, "parts": parts, "part_names": pnames,
            "unlock": ut, "hidden": bool(ut) and all(x == 4 for x in ut),
        }
    # 同一个官方名对应两套（Henchman Uniform 黑/橙）时，用 Comment 的尾巴区分开。
    dup = collections.Counter(o["en"] for o in out.values() if o["en"])
    for o in out.values():
        if o["en"] and dup[o["en"]] > 1 and o["comment"].lower().startswith(o["en"].lower()):
            tail = o["comment"][len(o["en"]):].strip()
            if tail:
                o["en"], o["cn"] = "%s (%s)" % (o["en"], tail), "%s（%s）" % (o["cn"], tail)
    return out


def find_bikes(packout):
    """按内容找 /conf/bikes.txt（`SkinData` = 全部 108 款涂装，`BikeData` = 19 辆车）。"""
    for p in sorted(glob.glob(os.path.join(packout, "*.bin"))):
        if b'"SkinData"' in open(p, "rb").read():
            return p
    return None


def load_paints(packout, en, cn, shop):
    """→ {str(SkinData.ID): {...}}，全部 108 款（商店里只卖过 66 款）。

    ★ 涂装**不是 items2 的键**：存档里每辆车一个 24 位拥有位掩码，键 = `664 + BikeID`、
    位 = `SkinIndex`（见模块开头 ★ 涂装）。所以每条都带上 `key`/`bit`/`slot` 给后台用。
    shop = {SkinData.ID: 商店/奖励条目}，用来拿官方中英文名；没上过架的只有内部英文名。
    """
    path = find_bikes(packout)
    if not path:
        return {}
    doc = load_json_tolerant(open(path, "rb").read()) or {}
    bikes = {}
    for k, v in (doc.get("BikeData") or {}).items():
        if str(k).isdigit():
            bikes[int(k)] = ((v or {}).get("Comment") or "").strip()
    out = {}
    for s in doc.get("SkinData") or []:
        sid, bid, slot = s.get("ID"), s.get("BikeID"), s.get("SkinIndex")
        if not isinstance(sid, int) or not isinstance(bid, int) or not isinstance(slot, int):
            continue
        rec = shop.get(sid) or {}
        nid = rec.get("NameId") or ""
        e = en.get(gh(nid), "") if nid else ""
        c = cn.get(gh(nid), "") if nid else ""
        name = (s.get("Name") or "").strip()
        p = {
            "id": sid, "bike": bid, "bike_en": bikes.get(bid, ""), "slot": slot,
            "key": 664 + bid, "bit": 1 << slot, "name": name, "nameid": nid,
            "en": e or name, "cn": c, "verified": bool(c),
            "comment": (rec.get("Comment") or "").strip(),
        }
        if isinstance(s.get("DiamondCost"), int):
            p["diamond"] = s["DiamondCost"]
        if isinstance(rec.get("MissionUnlock"), int):
            p["mission_unlock"] = rec["MissionUnlock"]
        out[str(sid)] = p
    return out


def _better_record(new, old):
    """同一个 ItemId 在多份配置里出现时留哪条：**非涂装记录优先**（涂装另有 SkinData 那张
    表、而且不是 items2 的键），同类里再优先带本地化键的。"""
    na, oa = new.get("Type") == 2, old.get("Type") == 2
    if na != oa:
        return oa
    return bool(new.get("NameId")) and not old.get("NameId")


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

    entries, files, bad, shop = {}, collections.Counter(), [], {}
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
            if node.get("Type") == 2:                # 涂装：另走 SkinData 那张表（load_paints）
                prev = shop.get(iid)
                if prev is None or (not prev.get("NameId") and node.get("NameId")):
                    shop[iid] = node
            prev = entries.get(iid)
            if prev is None or _better_record(node, prev):
                entries[iid] = node                  # 有本地化键的记录优先
            files[os.path.basename(p)] += 1

    items, cats = {}, collections.Counter()
    for iid, node in sorted(entries.items()):
        if iid == 135:                               # 「Pack of Tickets」= 竞技场金票，
            continue                                 # 走 pvp_state.json，不进存档 items2
        if node.get("Type") == 2:                    # 涂装没有 items2 编号（见 load_paints）
            continue
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

    # 服装：80 套 × 3 件。部件 id 有整整一半从没在任何配置里出现过（隐藏套装），
    # 只能按 customization.txt 的公式补出来；id 与别的名字空间撞车时（19 个 id 同时是
    # 某个「赛道解锁」条目）以服装为准，旧名字收进 alias 留证。
    outfits = load_outfits(args.packout, en, cn)
    overlap = []
    for sk, o in sorted(outfits.items(), key=lambda kv: kv[1]["id"]):
        o["set"] = sk
        for k, pid in enumerate(o["parts"]):
            ne, nc = o["part_names"].get(str(pid), ("", ""))
            it = items.get(str(pid))
            if it is None:
                items[str(pid)] = {
                    "id": pid, "cat": "outfit", "t": 0, "set": sk, "part": k,
                    "en": ne or o["en"], "cn": nc or o["cn"] or o["en"],
                    "key": ("ITEM_%d_%d" % (o["type"], k)) if (ne or nc) else o["key"],
                    "verified": False, "derived": True,
                }
                cats["outfit"] += 1
                continue
            if it["cat"] != "outfit":
                old = it["en"] or it["cn"]
                overlap.append({"id": pid, "was": it["cat"], "alias": old})
                it["alias"] = old
                cats[it["cat"]] -= 1
                cats["outfit"] += 1
            it["cat"], it["set"], it["part"] = "outfit", sk, k
            if ne:
                it["en"], it["cn"], it["key"] = ne, nc or ne, "ITEM_%d_%d" % (o["type"], k)
            elif "alias" in it:
                # 撞车改名后没有官方部件名 ⇒ 显示套装名，旧名字留在 alias 里。
                it["en"], it["cn"] = o["en"], o["cn"] or o["en"]
        # 这一套里有几件是从套装表推导出来的（隐藏套装在任何配置里都没有这些 id）。
        o["derived"] = sum(1 for p in o["parts"] if items[str(p)].get("derived"))

    # 涂装：108 款，编号不是 items2 的键（键 = 664 + 车号，位 = 该车第几款），单独一张表。
    paints = load_paints(args.packout, en, cn, shop)

    # 赛道碎片 id 与「赛道」同族，合到一张卡里给运维看，别单开一类天天被点错。
    out = {
        "source": {"packout": os.path.basename(args.packout),
                   "en": "1516", "cn": "1523",
                   "items": len(items), "outfits": len(outfits), "paints": len(paints),
                   "overlap_ids": overlap, "skipped_files": bad},
        "categories": [
            {"key": "currency", "en": "Currency", "cn": "货币"},
            {"key": "consumable", "en": "Consumables & boosts", "cn": "消耗品 / 加速"},
            {"key": "parts", "en": "Bike parts", "cn": "摩托车零件"},
            {"key": "outfit", "en": "Rider outfits", "cn": "骑手服装"},
            {"key": "blueprint", "en": "Bike blueprints", "cn": "摩托蓝图"},
            {"key": "track", "en": "Tracks & pieces (unverified)", "cn": "赛道与碎片（未验证）"},
        ],
        "outfits": outfits,
        "paints": paints,
        "items": items,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.write("\n")

    named = sum(1 for v in items.values() if v["en"])
    bonus = sum(1 for o in outfits.values() if o["bonus"])
    print("写入 %s：%d 条物品（有英文名 %d）+ %d 套服装（%d 套有套装效果，隐藏 %d）"
          "+ %d 款涂装（%d 款有官方中文名，%d 辆车）"
          % (args.out, len(items), named, len(outfits), bonus,
             sum(1 for o in outfits.values() if o["hidden"]),
             len(paints), sum(1 for p in paints.values() if p["verified"]),
             len({p["bike"] for p in paints.values()})))
    print("分类 %s；%d 个配置解析失败；%d 个 id 与赛道解锁撞车（已按服装归类）"
          % (dict(cats), len(bad), len(overlap)))
    for b in bad[:5]:
        print("  失败 %s" % b)


if __name__ == "__main__":
    main()
