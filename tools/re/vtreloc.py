#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump `.data.rel.ro` 区段，并把每个 8 字节槽按重定位解析成符号名。

这是找 C++ vtable（以及任何 const 全局对象表）的主武器。要点，都是踩过的坑：

  * `_ZTV*`（vtable 符号）在 libTrialsGo.so 的 `.dynsym` 里**不存在**，
    所以只能按内容 / 重定位来找，不能按符号找。
  * 相关的是 `.rela.dyn`（**section index 7，不是 4**），槽类型是
    `R_AARCH64_ABS64` = **257**（不是 `R_AARCH64_RELATIVE` = 1027）。
  * `r_offset` 是 **VA**，不是文件偏移。

用法:
    python tools/re/vtreloc.py <libTrialsGo.so> 0xdedb00 0xdedc00
"""
import struct
import sys

if len(sys.argv) < 4:
    sys.exit(__doc__)

SO, LO, HI = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
raw = open(SO, "rb").read()

e_shoff = struct.unpack_from("<Q", raw, 0x28)[0]
e_shnum = struct.unpack_from("<H", raw, 0x3c)[0]
e_shstrndx = struct.unpack_from("<H", raw, 0x3e)[0]

secs = []
for i in range(e_shnum):
    o = e_shoff + i * 64
    nm, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from(
        "<IIQQQQIIQQ", raw, o
    )
    secs.append(dict(name=nm, addr=addr, off=off, size=size, link=link))

sh = secs[e_shstrndx]


def sn(x):
    s = sh["off"] + x
    return raw[s:raw.index(b"\0", s)].decode()


for s in secs:
    s["n"] = sn(s["name"])
by = {s["n"]: s for s in secs}

d = by[".dynsym"]
st = secs[d["link"]]
syms = []
for i in range(d["size"] // 24):
    o = d["off"] + i * 24
    nameoff, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", raw, o)
    k = raw[st["off"] + nameoff:raw.index(b"\0", st["off"] + nameoff)].decode()
    syms.append((k, value))

rela = by[".rela.dyn"]
rel = {}
for i in range(rela["size"] // 24):
    o = rela["off"] + i * 24
    r_off, r_info, r_add = struct.unpack_from("<QQq", raw, o)
    typ = r_info & 0xFFFFFFFF
    if typ == 257:
        k, val = syms[r_info >> 32]
        rel[r_off] = (k + "+0x%x" % r_add if r_add else k)
    elif typ == 1027:
        rel[r_off] = "REL:0x%x" % r_add

for va in range(LO, HI, 8):
    print("0x%08x  %s" % (va, rel.get(va, "(none)")))
