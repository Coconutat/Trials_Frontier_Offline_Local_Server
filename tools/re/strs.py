# -*- coding: utf-8 -*-
"""列出一个文件里所有包含指定子串的 C 字符串（含文件偏移）。

用途：在 .so 里找 URL 模板 / JSON 键名 / 本地化字面量。偏移即 VA（见 cstr.py 说明）。

用法:
    python tools/re/strs.py <libTrialsGo.so> replay ghost_id content_id
"""
import re
import sys

if len(sys.argv) < 3:
    sys.exit(__doc__)

SO = sys.argv[1]
pats = [a.encode() for a in sys.argv[2:]]
raw = open(SO, "rb").read()
for m in re.finditer(rb"[\x20-\x7e]{3,200}", raw):
    s = m.group()
    if any(p in s for p in pats):
        print("0x%08x  %s" % (m.start(), s.decode("ascii", "replace")))
