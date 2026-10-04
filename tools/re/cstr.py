# -*- coding: utf-8 -*-
"""按虚拟地址 dump .rodata 里的 C 字符串。

在 libTrialsGo.so 上 `.text` / `.rodata` 的 VA == 文件偏移，所以这里可以直接把
VA 当偏移用；对其它 .so（或 `.init_array` 之后的段）请改用 segmap.py 换算。

用法:
    python tools/re/cstr.py <libTrialsGo.so> 0xb87b58 0xb87ba9 0xb85227
"""
import sys

if len(sys.argv) < 3:
    sys.exit(__doc__)

SO = sys.argv[1]
raw = open(SO, "rb").read()
for a in sys.argv[2:]:
    off = int(a, 16)
    e = raw.find(b"\x00", off)
    if e < 0:
        e = len(raw)
    print("%s (%d B): %r" % (a, e - off, raw[off:e].decode("utf-8", "replace")))
