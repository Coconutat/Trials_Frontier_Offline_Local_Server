#!/usr/bin/env python3
"""callers.py <so> <0xaddr|symbol> [...] -- 找出所有 BL 调用点（含经 PLT 的导出符号调用）

用法:
  python tools/re/callers.py tmp/libcmp/orig-libTrialsGo.so 0x4e6994
  python tools/re/callers.py tmp/libcmp/orig-libTrialsGo.so _ZN2tr11AdInterface11initAndroidEv
  python tools/re/callers.py tmp/libcmp/orig-libTrialsGo.so --sym Ad_          # 列符号
"""
import sys, struct

def load(path):
    raw = open(path, "rb").read()
    e_shoff = struct.unpack_from("<Q", raw, 0x28)[0]
    e_shentsize = struct.unpack_from("<H", raw, 0x3a)[0]
    e_shnum = struct.unpack_from("<H", raw, 0x3c)[0]
    e_shstrndx = struct.unpack_from("<H", raw, 0x3e)[0]
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from("<IIQQQQIIQQ", raw, o)
        secs.append(dict(name=name, typ=typ, flags=flags, off=off, size=size,
                         addr=addr, entsize=entsize, link=link, info=info))
    sh = secs[e_shstrndx]
    for s in secs:
        p = raw.index(b"\0", sh["off"] + s["name"])
        s["n"] = raw[sh["off"] + s["name"]:p].decode()
    by = {s["n"]: s for s in secs}
    return raw, secs, by

def symbols(raw, secs, by):
    """返回 {addr: (size, name)} 与 {name: (addr, size)}，合并 .dynsym + .symtab"""
    out = {}
    byname = {}
    for sn in (".dynsym", ".symtab"):
        s = by.get(sn)
        if not s:
            continue
        strs = secs[s["link"]]
        for k in range(s["size"] // 24):
            o = s["off"] + k * 24
            n, info, other, shndx, val, sz = struct.unpack_from("<IBBHQQ", raw, o)
            if val == 0:
                continue
            p = raw.index(b"\0", strs["off"] + n)
            name = raw[strs["off"] + n:p].decode("utf8", "replace")
            if not name:
                continue
            if val not in out or (sz and not out[val][0]):
                out[val] = (sz, name)
            if name not in byname or (sz and not byname[name][1]):
                byname[name] = (val, sz)
    return out, byname

def pltmap(raw, secs, by, syms, byname):
    """PLT stub 地址 -> 目标符号名"""
    plt = by.get(".plt")
    got = by.get(".got")
    if not plt or not got:
        return {}
    gotaddr = got["addr"]
    # .rela.plt: r_offset(8) r_info(8) r_addend(8)
    rp = by.get(".rela.plt")
    slot2sym = {}
    if rp:
        rs = secs[rp["link"]]
        for k in range(rp["size"] // 24):
            o = rp["off"] + k * 24
            r_off, r_info, r_add = struct.unpack_from("<QQq", raw, o)
            si = r_info >> 32
            o2 = rs["off"] + si * 24
            n = struct.unpack_from("<I", raw, o2)[0]
            p = raw.index(b"\0", raw.index(b"\0", 0) if False else 0)  # placeholder
            # 取字符串表
            strs = secs[rs["link"]]
            p = raw.index(b"\0", strs["off"] + n)
            name = raw[strs["off"] + n:p].decode("utf8", "replace")
            slot2sym[r_off] = name
    m = {}
    va = plt["addr"] + 0x20
    end = plt["addr"] + plt["size"]
    while va < end:
        off = plt["off"] + (va - plt["addr"])
        if off + 16 > len(raw):
            break
        w0, w1 = struct.unpack_from("<II", raw, off)
        if (w0 & 0x9F00001F) == 0x90000010:  # adrp x16, ...
            immlo = (w0 >> 29) & 3
            immhi = (w0 >> 5) & 0x7FFFF
            imm = (immhi << 2) | immlo
            if imm & (1 << 20):
                imm -= 1 << 21
            page = (va & ~0xFFF) + (imm << 12)
            if (w1 & 0xFFC00000) == 0xF9400000:  # ldr x17, [x16, #imm]
                g = page + ((w1 >> 10) & 0xFFF) * 8
                m[va] = slot2sym.get(g, slot2sym.get(g - gotaddr + gotaddr, None)) or slot2sym.get(g)
        va += 16
    return m

def branch_targets(raw, by):
    """扫描可执行节，返回 {目标地址: [来源地址...]}（B/BL）"""
    tgt = {}
    for s in by.values():
        if not (s["flags"] & 0x4) or s["n"] not in (".text", ".plt", ".init", ".fini"):
            continue
        for k in range(s["size"] // 4):
            off = s["off"] + k * 4
            if off + 4 > len(raw):
                break
            w = struct.unpack_from("<I", raw, off)[0]
            if (w & 0x7C000000) in (0x14000000, 0x94000000):
                imm = w & 0x03FFFFFF
                if imm & (1 << 25):
                    imm -= 1 << 26
                t = s["addr"] + k * 4 + imm * 4
                tgt.setdefault(t, []).append(s["addr"] + k * 4)
    return tgt

def owner(syms, addr):
    best = None
    for a, (sz, n) in syms.items():
        if sz and a <= addr < a + sz:
            if best is None or a > best[0]:
                best = (a, n, a + sz)
    return best

def main():
    path = sys.argv[1]
    raw, secs, by = load(path)
    syms, byname = symbols(raw, secs, by)
    if sys.argv[2] == "--sym":
        pat = sys.argv[3] if len(sys.argv) > 3 else ""
        for a, (sz, n) in sorted(syms.items()):
            if pat in n:
                print("%08x %6d %s" % (a, sz, n))
        return
    pm = pltmap(raw, secs, by, syms, byname)
    tgts = branch_targets(raw, by)
    for arg in sys.argv[2:]:
        if arg.startswith("0x"):
            addr = int(arg, 16)
            ow0 = owner(syms, addr)
            label = ow0[1] if ow0 else arg
        else:
            if arg not in byname:
                print("!! 未知符号", arg); continue
            addr = byname[arg][0]
            label = arg
        roots = {addr}
        for st, name in pm.items():
            if name == label or (label.startswith("_Z") and name == label):
                roots.add(st)
        # 也接受符号名匹配的 PLT
        print("==", label, "@0x%08x" % addr, "roots=%s" % ", ".join("0x%08x" % r for r in sorted(roots)))
        seen = set()
        for r in sorted(roots):
            for src in tgts.get(r, []):
                if src in seen:
                    continue
                seen.add(src)
                ow = owner(syms, src)
                print("   0x%08x <- %s" % (src, ("0x%08x %s" % (ow[0], ow[1])) if ow else "(无名)"))

main()
