# -*- coding: utf-8 -*-
"""扫描 .so 的 .text，找出所有 `adrp Xn, <page>; ldr Xn, [Xn, #<off>]` 形式的全局引用。

用法: python tmp/gref_global.py <so> <page_hex> <offset_hex>
例:   python tmp/gref_global.py tmp/libcmp/orig-libTrialsGo.so 0xe20000 0x420
"""
import struct
import sys


def load(path):
    d = open(path, "rb").read()
    e_phoff = struct.unpack_from("<Q", d, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", d, 0x36)[0]
    e_phnum = struct.unpack_from("<H", d, 0x38)[0]
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", d, off)[0]
        if p_type != 1:
            continue
        p_flags = struct.unpack_from("<I", d, off + 4)[0]
        p_offset, p_vaddr = struct.unpack_from("<QQ", d, off + 8)
        p_filesz = struct.unpack_from("<Q", d, off + 32)[0]
        segs.append((p_offset, p_vaddr, p_filesz, p_flags))
    return d, segs


def sext(v, bits):
    if v & (1 << (bits - 1)):
        v -= (1 << bits)
    return v


def scan(d, segs, page, offset):
    hits = []
    for p_offset, p_vaddr, p_filesz, _flags in segs:
        if not (_flags & 1):  # 只要可执行段（PF_X = 1）
            continue
        base = p_offset - p_vaddr
        for va in range(p_vaddr, p_vaddr + p_filesz, 4):
            w = struct.unpack_from("<I", d, base + va)[0]
            if (w & 0x9F000000) != 0x90000000:
                continue
            rd = w & 0x1F
            immhi = (w >> 5) & 0x7FFFF
            immlo = (w >> 29) & 3
            imm = sext((immhi << 2) | immlo, 21) << 12
            pc_page = va & ~0xFFF
            target_page = pc_page + imm
            if target_page != page:
                continue
            # 往后 10 条指令内找 ldr Xrd, [Xrd, #offset]
            for k in range(1, 11):
                a2 = va + k * 4
                if a2 >= p_vaddr + p_filesz:
                    break
                w2 = struct.unpack_from("<I", d, base + a2)[0]
                if (w2 & 0xFFC00000) != 0xF9400000:
                    continue
                rn = (w2 >> 5) & 0x1F
                rt = w2 & 0x1F
                imm12 = (w2 >> 10) & 0xFFF
                if rn == rd and rt == rd and imm12 * 8 == offset:
                    hits.append(va)
                    break
    return hits


def scan_all(d, segs, page):
    """返回所有 (adrp_va, ldr_offset) —— adrp 到该页后 12 条指令内的整数 ldr。"""
    out = []
    for p_offset, p_vaddr, p_filesz, _flags in segs:
        if not (_flags & 2):
            continue
        base = p_offset - p_vaddr
        for va in range(p_vaddr, p_vaddr + p_filesz, 4):
            w = struct.unpack_from("<I", d, base + va)[0]
            if (w & 0x9F000000) != 0x90000000:
                continue
            rd = w & 0x1F
            immhi = (w >> 5) & 0x7FFFF
            immlo = (w >> 29) & 3
            imm = sext((immhi << 2) | immlo, 21) << 12
            if (va & ~0xFFF) + imm != page:
                continue
            for k in range(1, 13):
                a2 = va + k * 4
                if a2 >= p_vaddr + p_filesz:
                    break
                w2 = struct.unpack_from("<I", d, base + a2)[0]
                if (w2 & 0xFFC00000) != 0xF9400000:
                    continue
                rn = (w2 >> 5) & 0x1F
                rt = w2 & 0x1F
                if rn == rd and rt == rd:
                    out.append((va, ((w2 >> 10) & 0xFFF) * 8))
                    break
    return out


def main():
    path = sys.argv[1]
    page = int(sys.argv[2], 16)
    offset = int(sys.argv[3], 16) if len(sys.argv) > 3 else None
    d, segs = load(path)
    if offset is None:
        hits = scan_all(d, segs, page)
        hits.sort()
        print("== adrp 到 0x%x 之后的 ldr 偏移统计（%d 处）：" % (page, len(hits)))
        from collections import Counter
        c = Counter(h[1] for h in hits)
        for off, n in c.most_common(40):
            print("   0x%04x  x%d" % (off, n))
        return
    hits = scan(d, segs, page, offset)
    print("== *(0x%x+0x%x) 的引用点：%d 处" % (page, offset, len(hits)))
    for h in hits:
        print("   0x%08x" % h)


if __name__ == "__main__":
    main()
