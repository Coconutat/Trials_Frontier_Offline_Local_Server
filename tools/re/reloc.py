#!/usr/bin/env python3
"""reloc.py <so> <0xtarget> -- find R_AARCH64_RELATIVE relocations whose addend == target
(used to locate which vtable slot holds a given virtual function)"""
import sys, struct

raw = open(sys.argv[1], "rb").read()
target = int(sys.argv[2], 16)

e_shoff = struct.unpack_from("<Q", raw, 0x28)[0]
e_shentsize = struct.unpack_from("<H", raw, 0x3a)[0]
e_shnum = struct.unpack_from("<H", raw, 0x3c)[0]
e_shstrndx = struct.unpack_from("<H", raw, 0x3e)[0]
secs = []
for i in range(e_shnum):
    o = e_shoff + i * e_shentsize
    f = struct.unpack_from("<IIQQQQIIQQ", raw, o)
    secs.append(dict(name=f[0], typ=f[1], flags=f[2], addr=f[3], off=f[4], size=f[5], link=f[6]))
sh = secs[e_shstrndx]
for s in secs:
    s["n"] = raw[sh["off"] + s["name"]:raw.index(b"\0", sh["off"] + s["name"])].decode()
by = {s["n"]: s for s in secs}

hits = []
for sn in (".rela.dyn", ".rela.plt"):
    s = by.get(sn)
    if not s:
        continue
    for k in range(s["size"] // 24):
        o = s["off"] + k * 24
        r_off, r_info, r_add = struct.unpack_from("<QQq", raw, o)
        if r_add == target:
            hits.append((sn, r_off, r_info & 0xFFFFFFFF, r_info >> 32))

for sn, r_off, rtype, rsym in hits:
    print("%s  r_offset=0x%08x type=%d sym=%d   (r_offset-0xdd9c60)/8 = %s" % (
        sn, r_off, rtype, rsym,
        ("%d" % ((r_off - 0xDD9C60) // 8)) if 0xDD9C60 <= r_off < 0xDD9C60 + 0x200 else "-"))
if not hits:
    print("no R_AARCH64_RELATIVE relocation with addend 0x%08x" % target)
