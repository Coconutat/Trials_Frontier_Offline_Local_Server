#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按子串列符号（`.symtab` + `.dynsym`，同名去重），打印 `节 名字 地址 大小`。

需要 pyelftools。找错位/找 vtable 符号的第一步；注意 `_ZTV*`（vtable 符号）
在这类经过 strip 的 .so 里常常只存在于 `.symtab`，甚至完全不存在。

用法:
    python tools/re/syms.py <libTrialsGo.so> onGhostQuery
    python tools/re/syms.py <libTrialsGo.so> StoreManager parse
"""
import sys
from elftools.elf.elffile import ELFFile

if len(sys.argv) < 3:
    sys.exit(__doc__)

path = sys.argv[1]
pats = sys.argv[2:]
f = open(path, 'rb')
e = ELFFile(f)
out = []
for secname in ('.symtab', '.dynsym'):
    s = e.get_section_by_name(secname)
    if not s:
        continue
    for sym in s.iter_symbols():
        n = sym.name
        if not n:
            continue
        if any(p in n for p in pats):
            out.append((secname, n, sym['st_value'], sym['st_size']))
seen = set()
for secname, n, v, sz in out:
    if n in seen:
        continue
    seen.add(n)
    print('%s  %-90s 0x%08x  %d' % (secname, n, v, sz))
print('total', len(seen))
