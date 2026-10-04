#!/usr/bin/env python3
"""disasm.py <so> <0xaddr> [len] [--bl-only] -- 反汇编一个函数，BL/B 目标自动标注符号名

用法:
  python tools/re/disasm.py tmp/libcmp/orig-libTrialsGo.so 0x4e6994 2012 --bl-only
"""
import sys, struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

def load(path):
    raw = open(path, "rb").read()
    e_shoff = struct.unpack_from("<Q", raw, 0x28)[0]
    e_shentsize = struct.unpack_from("<H", raw, 0x3a)[0]
    e_shnum = struct.unpack_from("<H", raw, 0x3c)[0]
    e_shstrndx = struct.unpack_from("<H", raw, 0x3e)[0]
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        f = struct.unpack_from("<IIQQQQIIQQ", raw, o)
        secs.append(dict(name=f[0], typ=f[1], flags=f[2], addr=f[3], off=f[4],
                         size=f[5], link=f[6], info=f[7]))
    sh = secs[e_shstrndx]
    for s in secs:
        s["n"] = raw[sh["off"] + s["name"]:raw.index(b"\0", sh["off"] + s["name"])].decode()
    return raw, secs, {s["n"]: s for s in secs}

raw, secs, by = load(sys.argv[1])
syms = {}
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
        if name and (val not in syms or (sz and not syms[val][0])):
            syms[val] = (sz, name)

# PLT 映射
rel_plt = by.get(".rela.plt")
slot = {}
if rel_plt:
    rs = secs[rel_plt["link"]]
    strs = secs[rs["link"]]
    for k in range(rel_plt["size"] // 24):
        o = rel_plt["off"] + k * 24
        r_off, r_info, _ = struct.unpack_from("<QQq", raw, o)
        si = r_info >> 32
        n = struct.unpack_from("<I", raw, rs["off"] + si * 24)[0]
        nm = raw[strs["off"] + n:raw.index(b"\0", strs["off"] + n)].decode("utf8", "replace")
        slot[r_off] = nm
plt = by[".plt"]
pltmap = {}
va = plt["addr"] + 0x20
while va < plt["addr"] + plt["size"] - 16:
    off = plt["off"] + (va - plt["addr"])
    w0, w1 = struct.unpack_from("<II", raw, off)
    if (w0 & 0x9F00001F) == 0x90000010 and (w1 & 0xFFC00000) == 0xF9400000:
        immlo = (w0 >> 29) & 3
        immhi = (w0 >> 5) & 0x7FFFF
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= 1 << 21
        page = (va & ~0xFFF) + (imm << 12)
        g = page + ((w1 >> 10) & 0xFFF) * 8
        if g in slot:
            pltmap[va] = slot[g]
    va += 16

def name_of(a):
    if a in pltmap:
        return "PLT:" + pltmap[a]
    best = None
    for v, (sz, n) in syms.items():
        if sz and v <= a < v + sz:
            if best is None or v > best[0]:
                best = (v, n, sz)
    if best:
        return "0x%08x+%d %s" % (best[0], a - best[0], best[1])
    return "0x%08x" % a

addr = int(sys.argv[2], 16)
n = int(sys.argv[3], 0) if len(sys.argv) > 3 and not sys.argv[3].startswith("-") else 64
bl_only = "--bl-only" in sys.argv
code = raw[addr:addr + n]
md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True
for ins in md.disasm(code, addr):
    is_b = ins.mnemonic in ("bl", "b") or ins.mnemonic.startswith("b.")
    if bl_only and not is_b:
        continue
    extra = ""
    if is_b and ins.operands and ins.operands[0].type == 2:
        extra = "   -> " + name_of(ins.operands[0].imm)
    print("0x%08x  %-8s %-28s%s" % (ins.address, ins.mnemonic, ins.op_str, extra))
