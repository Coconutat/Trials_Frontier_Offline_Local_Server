#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 Trials Frontier 原版 libTrialsGo.so 打补丁。

输入必须是育碧官方签名原版 APK 里的 lib/arm64-v8a/libTrialsGo.so。
脚本会校验文件大小、SHA256 以及每一处补丁位置的原始字节，
任何一项对不上就报错退出，绝不盲改。

用法:
    python tools/patch_native.py --so libTrialsGo.so --out libTrialsGo.patched.so
    python tools/patch_native.py --so libTrialsGo.so --dry-run     # 只校验不改
"""
import argparse
import hashlib
import os
import struct
import sys

# ---------------------------------------------------------------- 输入指纹

EXPECTED_SIZE = 14901128
EXPECTED_SHA256 = "743f945cd7e3378dbf78eadc9d864de0c465b558bda8a54923b46a8f170fb7f4"

# ---------------------------------------------------------------- 补丁表
#
# 每一处补丁用 "符号名 + 函数内字节偏移" 定位，并附带原始字节用于自校验。
# 前三条是整函数替换，第四条只改一条 ARM64 指令里的一个字节。
#
#   0x4B02016B = sub w11, w11, w2     (原版：消耗道具时做减法)
#   0x0B02016B = add w11, w11, w2     (补丁：消耗道具时做加法 → 不减反增)
#
# mov w0, #1 ; ret  = 20 00 80 52 c0 03 5f d6
# mov w0, #0 ; ret  = 00 00 80 52 c0 03 5f d6

RET1 = "20 00 80 52 c0 03 5f d6"
RET0 = "00 00 80 52 c0 03 5f d6"

PATCHES = [
    {
        "id": "anticheating-off",
        "symbol": "_ZN2tr12AntiCheating7isValidEv",
        "offset": 0x00,
        "original": "08 45 00 d0 08 25 40 f9",
        "patched": RET1,
        "why": "tr::AntiCheating::isValid() 恒返回 true → 关闭反作弊与签名/时钟校验",
    },
    {
        "id": "unlimited-fuel",
        "symbol": "_ZN2tr17ConsumableManager15isUnlimitedFuelEi",
        "offset": 0x00,
        "original": "f4 4f be a9 fd 7b 01 a9",
        "patched": RET1,
        "why": "tr::ConsumableManager::isUnlimitedFuel(int) 恒返回 true → 无限燃油",
    },
    {
        "id": "no-offer-blacklist",
        "symbol": "_ZN2tr9OfferData13isBlackListedEib",
        "offset": 0x00,
        "original": "ff c3 01 d1 f9 13 00 f9",
        "patched": RET0,
        "why": "tr::OfferData::isBlackListed(int,bool) 恒返回 false → 没有 offer 被拉黑",
    },
    {
        "id": "spend-adds-instead-of-subtracts",
        "symbol": "_ZN2tr11PlayerItems6removeEii",
        "offset": 0x43,
        "original": "4b",
        "patched": "0b",
        "why": "tr::PlayerItems::remove(int,int) 内 sub w11,w11,w2 改成 add → 花费货币道具不减反增",
    },
    {
        "id": "dl-content-always-ready",
        "symbol": "_ZN2tr16DLContentManager9isDLReadyEv",
        "offset": 0x00,
        "original": "f7 0f 1c f8 f6 57 01 a9",
        "patched": RET1,
        "why": "tr::DLContentManager::isDLReady() 恒返回 true → 内容包视为已就绪，"
               "不再弹「下载暂停」，解锁 weekly challenge / 关卡进入前置检查",
    },
    {
        "id": "no-blacklist-popup",
        "symbol": "_ZN2tr14MenuzStateMain17isUserBlackListedEv",
        "offset": 0x00,
        "original": "ff 03 01 d1 f4 4f 02 a9",
        "patched": RET0,
        "why": "tr::MenuzStateMain::isUserBlackListed() 恒返回 0（未拉黑）→ 不再弹「警报！」弹窗。"
               "原逻辑：读设置 enable_security_check（默认 1），非 com.android.vending/"
               "com.google.android.feedback 安装器 → 返回 3；再比对 apk_signature，不符 → 返回 1。"
               "重签名 + adb 安装必然两条全中。全库仅 MenuzStateMain::activate 一处调用。",
    },
    {
        "id": "no-ads",
        "symbol": "_ZN2tr11AdInterface11initAndroidEv",
        "offset": 0x44,
        "original": "e0 00 00 34",   # cbz w0, #0x4e69f4
        "patched": "07 00 00 14",    # b   #0x4e69f4（无条件跳到提前返回）
        "why": "tr::AdInterface::initAndroid() 开头读 GlobalSettings 的 'Ads_enabled'"
               "（默认值本来就是 0），命中 0 时 cbz 跳到函数尾提前返回。"
               "改成无条件 b 后广告永不初始化：全库唯一调用 TapjoyManager::init / "
               "AdMobRewardedVideoManager::init / AdMobManager::init 的地方就是这里，"
               "于是 Tapjoy 广告墙、AdMob 插屏/激励视频、Flurry、AdColony 全部不加载，"
               "也不再产生 placements.tapjoy.com 等广告网络流量。",
    },
    {
        "id": "iap-failed-redirects-to-complete",
        "symbol": "_ZN2tr12StoreManager16onPurchaseFailedEiPN2mz11IAPItemInfoE",
        "offset": 0x0,
        # 0x0057a9a8: str x19,[sp,#-0x20]! ; stp x29,x30,[sp,#0x10] ; add x29,sp,#0x10
        "original": "f3 0f 1e f8 fd 7b 01 a9 fd 43 00 91",
        # mov x1, x2 ; mov x2, xzr ; b #0x579940 (StoreManager::onPurchaseComplete)
        "patched": "e1 03 02 aa e2 03 1f aa e4 fb ff 17",
        "why": "真钱内购的完整破解。反汇编证明：StoreManager::onNetworkDataReceived(0x57b0cc) 的"
               "cmd 0x17 分支只是再调一次 mz::IAPManager::purchase（仍走 Google Play），"
               "所以「让服务器下发购买结果」这条路拿不到物品；真正无条件发奖的是"
               " StoreManager::onPurchaseComplete(0x579940，3296 字节，全程不校验收据、不联网)。"
               "它在 IAPManagerListener vtable 的槽 0，失败/取消则分别走槽 0x08/0x10，即"
               " onPurchaseFailed(0x57a9a8) 与 onPurchaseCancel(0x57aa04)，这两个函数只做"
               " UserTracker 打点并弹「购买失败。」。把这两个入口改成尾调用 onPurchaseComplete"
               "（x2 = IAPReceipt* 传 NULL，函数内 0x579ad0/0x579e90 两处 `cbz x20` 有 NULL 保护），"
               "Google Play 的失败回调就变成「谢谢你的购买！」并正常发奖。",
    },
    {
        "id": "iap-cancel-redirects-to-complete",
        "symbol": "_ZN2tr12StoreManager16onPurchaseCancelEPN2mz11IAPItemInfoE",
        "offset": 0x0,
        # 0x0057aa04: str x19,[sp,#-0x20]! ; stp x29,x30,[sp,#0x10]
        "original": "f3 0f 1e f8 fd 7b 01 a9",
        # mov x2, xzr ; b #0x579940 (StoreManager::onPurchaseComplete)
        "patched": "e2 03 1f aa ce fb ff 17",
        "why": "同上，覆盖取消路径（IAPManagerListener vtable 槽 0x10）。",
    },
    {
        "id": "vip-membership-null-guard-slot0-a",
        "symbol": "_ZN2tr10VIPManager19getPlayerMembershipEv",
        "offset": 0x78,
        # 0x0062e63c 原是 `ldr w8, [x0]` —— 空指针解引用点，挪到 +0x7C 处的空槽
        "original": "08 00 40 b9",
        # cbz x0, #0x62e670（空会员列表出口）
        "patched": "a0 01 00 b4",
        "why": "ROADMAP 第 1 条「联网闪退」的真凶 + VIP 下发的正确修法。tombstone 指向 "
               "tr::VIPManager::getPlayerMembership()+120，栈为 "
               "GlobalData::init -> UserTracker::init -> sessionStart -> DNAManager::sendDnaEvent "
               "-> updateCommonAttributes -> getMembershipDate -> getPlayerMembership。"
               "反汇编显示该函数开头有三道闸：NetworkChecker::getNetworkType() 必须非 0 且非 -1"
               "（所以断网启动不崩）、AntiCheating::isValid() 必须为真、"
               "PlayerItems::getItemCount(0x80,0) 必须为真；过了三道闸后执行"
               "`ldr x0,[x21]` / `ldr w8,[x0]` —— 会员计时器指针由 VIPManager::activateMembership()"
               " 创建（正常由服务器下发触发）。启动早期 GlobalData::init 先调 UserTracker::init"
               "（崩溃帧）再调 VIPManager::init（晚约 0x1D4 字节），所以那一刻指针必然是 NULL。"
               "本补丁把 `ldr w8,[x0]` 前移成开头的 `cbz x0`，既躲开空指针、"
               "又保留「VIPManager::init 跑过之后如实上报真实会员状态」的能力"
               "（不同于早期 m14 把整个函数结果涂成常量空列表的做法）。",
    },
    {
        "id": "vip-membership-null-guard-slot0-b",
        "symbol": "_ZN2tr10VIPManager19getPlayerMembershipEv",
        "offset": 0x7C,
        # 0x0062e640 原是 `cbz w8, #0x62e670`
        "original": "88 01 00 34",
        # ldr w8, [x0]
        "patched": "08 00 40 b9",
        "why": "上一条的配对：把原先紧跟的 cbz 位置让给 load。",
    },
    {
        "id": "vip-membership-null-guard-slot0-c",
        "symbol": "_ZN2tr10VIPManager19getPlayerMembershipEv",
        "offset": 0x80,
        # 0x0062e644 原是 `mov x20, xzr`（冗余槽，x20 在 0x62e62c 刚被置 0）
        "original": "f4 03 1f aa",
        # cbz w8, #0x62e670
        "patched": "68 01 00 34",
        "why": "占用冗余槽补回 `cbz w8, #0x62e670`，于是改成 "
               "`ldr x0,[x21]` -> `cbz x0` -> `ldr w8,[x0]` -> `cbz w8` -> `bl getRemainingTime` -> `cbz w0`，"
               "与原始语义完全一致且不再解引用 NULL。",
    },
    {
        "id": "vip-membership-null-guard-slot1-a",
        "symbol": "_ZN2tr10VIPManager19getPlayerMembershipEv",
        "offset": 0xF4,
        # 0x0062e6b8 原是 `ldr w8, [x0]`
        "original": "08 00 40 b9",
        # cbz x0, #0x62e760（第二个空会员列表出口）
        "patched": "40 05 00 b4",
        "why": "第二个会员槽位（0x0062e6b4 `ldr x0,[x21,#8]`）的同一空指针解引用。",
    },
    {
        "id": "vip-membership-null-guard-slot1-b",
        "symbol": "_ZN2tr10VIPManager19getPlayerMembershipEv",
        "offset": 0xF8,
        # 0x0062e6bc 原是 `cbz w8, #0x62e760`（此处没有空槽可用，该 cbz 被丢弃）
        "original": "28 05 00 34",
        # ldr w8, [x0]
        "patched": "08 00 40 b9",
        "why": "把 load 移到 cbz 原来的位置；slot1 的 `cbz w8` 无处安放被丢弃，"
               "但未启动的 TimedAction 偏移 0/8 全为 0，紧随其后的 `bl getRemainingTime` + `cbz w0` 已能兜住。",
    },
    # ------------------------------------------------------------------
    # m16：让离线商店也出现 VIP（骑士俱乐部）档位，从而触发 VIP 下发
    #
    #   tr::VIPManager::isVIPStoreOfferAvailable() @0x0062edd4
    #       -> OfferManager::findVIPOffers(StoreItem*&, mz::IAPItemInfo*&, u16) @0x00601920
    #              ... found: x0 = IAPManager* ; x1 = item+4 (productIdentifier)
    #              0x006019e0  bl IAPManager::getProductInfoEnabled
    #              0x006019e4  str x0,[x19]        ; *outIap = 返回值（不判 NULL）
    #       return (si != NULL) && (iap != NULL);
    #
    #   离线没有 Google Play，mz::IAPManagerAndroid::LoadStore 一个产品都没往
    #   mt::Array<mz::IAPItemInfo>（基类 this+0x10 count / this+0x18 data，stride 0x88）
    #   里插过，所以 getProductInfoEnabled 永远走 0x0088a22c `mov x19,xzr` 返回 NULL
    #   => *outIap == NULL => isVIPStoreOfferAvailable() 恒 false => 骑士俱乐部两档
    #   只有「剩余时间：未知（离线）」。
    #
    #   取法：只改 findVIPOffers 里那一条 bl，让它跳进代码洞；洞里直接返回一个
    #   伪造的 IAPItemInfo（+0x84 = 1 即 getProductInfoEnabled 认可的 bit0）。
    #   其它 IAP 调用点（尤其 0x0088a3e4 那处购买校验）完全不动。
    # ------------------------------------------------------------------
    {
        "id": "vip-shop-offer-iap-stub-call",
        "symbol": "_ZN2tr12OfferManager13findVIPOffersERPNS_9StoreItemERPN2mz11IAPItemInfoEt",
        "offset": 0xC0,
        # 0x006019e0 原为 `bl 0x00365950`（PLT: mz::IAPManager::getProductInfoEnabled）
        "original": "dc 8f f5 97",
        # bl 0x0096d85c（下面的代码洞 stub）
        "patched": "9f af 0d 94",
        "why": "把 VIP offer 的 IAP 查询改到代码洞 stub，直接返回伪造的 IAPItemInfo，"
               "使 isVIPStoreOfferAvailable() 离线也能为真。",
    },
    {
        "id": "vip-shop-offer-iap-stub",
        "addr": 0x0096D85C,
        # caves.py 报出的 4084 字节空闲区（0x96d85c..0x96e850），原内容全 0
        "original": "00 00 00 00 00 00 00 00 00 00 00 00",
        # adrp x0, #0x96d000 ; add x0, x0, #0x86c ; ret
        "patched": "00 00 00 90 00 b0 21 91 c0 03 5f d6",
        "why": "返回 0x0096d86c 处伪造结构的指针。",
    },
    {
        "id": "vip-shop-offer-iap-fakeinfo",
        "addr": 0x0096D86C,
        "original": "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00 "
                    "00 00 00 00 00 00 00 00",
        # +0x00 "tfr.vip.member"  +0x40 int -1  +0x84 u32 1
        "patched": "74 66 72 2e 76 69 70 2e "
                   "6d 65 6d 62 65 72 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "ff ff ff ff 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 00 00 00 00 "
                   "00 00 00 00 01 00 00 00",
        "why": "mz::IAPItemInfo（0x88 字节）：+0x00 内联 productIdentifier、"
               "+0x40 int（原生初值 -1）、+0x84 flags 的 bit0 = enabled。",
    },
]

# ---------------------------------------------------------------- ELF64 解析

SHT_SYMTAB = 2
SHT_DYNSYM = 11
PT_LOAD = 1


class Elf64(object):
    def __init__(self, data):
        self.data = data
        if data[:4] != b"\x7fELF":
            raise ValueError("不是 ELF 文件")
        if data[4] != 2:
            raise ValueError("不是 ELF64")
        if data[5] != 1:
            raise ValueError("不是小端 ELF")
        (self.e_phoff,) = struct.unpack_from("<Q", data, 0x20)
        (self.e_shoff,) = struct.unpack_from("<Q", data, 0x28)
        (self.e_phentsize,) = struct.unpack_from("<H", data, 0x36)
        (self.e_phnum,) = struct.unpack_from("<H", data, 0x38)
        (self.e_shentsize,) = struct.unpack_from("<H", data, 0x3A)
        (self.e_shnum,) = struct.unpack_from("<H", data, 0x3C)
        self._loads = self._read_loads()
        self._sections = self._read_sections()

    def _read_loads(self):
        out = []
        for i in range(self.e_phnum):
            off = self.e_phoff + i * self.e_phentsize
            (p_type, _flags, p_offset, p_vaddr, _p_paddr, p_filesz,
             _p_memsz, _p_align) = struct.unpack_from("<IIQQQQQQ", self.data, off)
            if p_type == PT_LOAD:
                out.append((p_vaddr, p_offset, p_filesz))
        return out

    def _read_sections(self):
        out = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            (sh_name, sh_type, _sh_flags, sh_addr, sh_offset, sh_size,
             _sh_link, _sh_info, _sh_addralign, sh_entsize) = struct.unpack_from(
                "<IIQQQQIIQQ", self.data, off)
            out.append({
                "name_off": sh_name, "type": sh_type, "addr": sh_addr,
                "offset": sh_offset, "size": sh_size, "entsize": sh_entsize,
            })
        return out

    def vaddr_to_offset(self, vaddr):
        for p_vaddr, p_offset, p_filesz in self._loads:
            if p_vaddr <= vaddr < p_vaddr + p_filesz:
                return p_offset + (vaddr - p_vaddr)
        raise ValueError("虚地址 0x%x 不在任何 PT_LOAD 段内" % vaddr)

    def symbols(self):
        """返回 [(name, value, size)]，合并 symtab 与 dynsym。"""
        out = []
        for idx, sec in enumerate(self._sections):
            if sec["type"] not in (SHT_SYMTAB, SHT_DYNSYM):
                continue
            if sec["entsize"] == 0:
                continue
            out.extend(self._symbols_in(idx, sec))
        return out

    def _symbols_in(self, idx, sec):
        # 符号表关联的字符串表由 sh_link（节头 +0x28）指向
        link = struct.unpack_from("<I", self.data,
                                  self.e_shoff + idx * self.e_shentsize + 0x28)[0]
        if link >= len(self._sections):
            return []
        strsec = self._sections[link]
        out = []
        n = sec["size"] // sec["entsize"]
        for i in range(n):
            off = sec["offset"] + i * sec["entsize"]
            (st_name, _st_info, _st_other, _st_shndx, st_value, st_size) = \
                struct.unpack_from("<IBBHQQ", self.data, off)
            if st_name == 0:
                continue
            end = self.data.index(b"\x00", strsec["offset"] + st_name)
            name = self.data[strsec["offset"] + st_name:end].decode("utf-8", "replace")
            out.append((name, st_value, st_size))
        return out


# ---------------------------------------------------------------- 主流程

def parse_hex(s):
    return bytes(int(t, 16) for t in s.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", required=True, help="待补丁的 libTrialsGo.so")
    ap.add_argument("--out", help="输出路径；不给则只校验")
    ap.add_argument("--dry-run", action="store_true", help="只校验，不写文件")
    ap.add_argument("--report", help="把结果写成 JSON")
    ap.add_argument("--only", default=None,
                    help="只应用这些补丁 id（逗号分隔）；AIO 用它按 GUI 勾选做子集")
    ap.add_argument("--force", action="store_true",
                    help="跳过整库 size/SHA256 前置校验（每处补丁仍逐字节比对）")
    args = ap.parse_args()
    only = [t.strip() for t in args.only.split(",") if t.strip()] if args.only else None

    with open(args.so, "rb") as f:
        data = bytearray(f.read())

    problems = []
    if not args.force:
        if len(data) != EXPECTED_SIZE:
            problems.append("文件大小 %d != 期望 %d" % (len(data), EXPECTED_SIZE))
        sha = hashlib.sha256(data).hexdigest()
        if sha != EXPECTED_SHA256:
            problems.append("SHA256 %s != 期望 %s" % (sha, EXPECTED_SHA256))
    else:
        sha = hashlib.sha256(data).hexdigest()
        print("[WARN] --force：跳过整库校验（实际 %d 字节 sha256 %s）"
              % (len(data), sha))

    elf = Elf64(bytes(data))
    symmap = {}
    for name, value, size in elf.symbols():
        if name not in symmap or size > symmap[name][1]:
            symmap[name] = (value, size)

    results = []
    for p in PATCHES:
        if only is not None and p["id"] not in only:
            continue
        want = parse_hex(p["original"])
        new = parse_hex(p["patched"])
        if len(want) != len(new):
            problems.append("%s: 原始/补丁字节长度不一致" % p["id"])
            continue
        # 两种定位方式：symbol+offset（函数体内），或 addr（绝对虚拟地址，
        # 用于落在代码洞里的补丁 —— 那里没有任何符号可以挂靠）。
        if "addr" in p:
            value = p["addr"]
            off = 0
            label = "(code cave)"
        else:
            if p["symbol"] not in symmap:
                problems.append("%s: 符号 %s 不存在（可能是被 strip 过或版本不符）"
                                % (p["id"], p["symbol"]))
                continue
            # 注意：symtab 里记录的函数长度有时偏小，所以不拿 size 做硬校验，
            # 只靠"原始字节必须逐字节吻合"来保证打在对的位置。
            value, _size = symmap[p["symbol"]]
            label = p["symbol"]
        off = p.get("offset", 0)
        try:
            foff = elf.vaddr_to_offset(value + off)
        except ValueError as e:
            problems.append("%s: %s" % (p["id"], e))
            continue
        got = bytes(data[foff:foff + len(want)])
        if got == new:
            # 第三方重打包（民间汉化/整合版）常常已经改过这几处 —— 当成已满足，
            # 不能报错，否则 AIO 就彻底用不了现成的 APK。
            results.append({
                "id": p["id"], "symbol": label,
                "vaddr": "0x%08x" % (value + off),
                "file_offset": foff, "already": True,
                "original": want.hex(" "), "patched": new.hex(" "),
                "why": p["why"],
            })
            continue
        ok = (got == want)
        if not ok:
            problems.append("%s: 0x%08x 处原始字节 %s != 期望 %s"
                            % (p["id"], value + off,
                               got.hex(" "), want.hex(" ")))
            continue
        results.append({
            "id": p["id"], "symbol": label,
            "vaddr": "0x%08x" % (value + off),
            "file_offset": foff,
            "original": want.hex(" "), "patched": new.hex(" "),
            "why": p["why"],
        })
        if not args.dry_run:
            data[foff:foff + len(new)] = new

    for r in results:
        tag = "SKIP" if r.get("already") else "OK  "
        print("[%s] %-38s %s (文件偏移 0x%x)" % (tag, r["id"], r["vaddr"], r["file_offset"]))
        if r.get("already"):
            print("       已经是目标状态，跳过")
        else:
            print("       %s" % r["why"])
    for msg in problems:
        print("[ERR] %s" % msg)

    if problems:
        print("\n有 %d 项校验失败，未产生任何输出。" % len(problems))
        return 2

    if args.out and not args.dry_run:
        with open(args.out, "wb") as f:
            f.write(bytes(data))
        outsha = hashlib.sha256(bytes(data)).hexdigest()
        changed = [r for r in results if not r.get("already")]
        print("\n已写出 %s (%d 字节, sha256 %s)" % (args.out, len(data), outsha))
        print("已改动 %d 处（另有 %d 处本来就是目标状态），共 %d 字节。"
              % (len(changed), len(results) - len(changed),
                 sum(len(parse_hex(r["patched"])) for r in changed)))

    if args.report:
        import json
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"source": os.path.basename(args.so),
                       "source_sha256": sha,
                       "patches": results}, f, ensure_ascii=False, indent=2)
        print("报告已写入 %s" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
