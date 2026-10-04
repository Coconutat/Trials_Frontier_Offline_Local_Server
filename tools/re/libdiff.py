#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐字节 diff 两个 ELF64 .so，并把差异段归到所在函数上。

用 A 的符号表定位「这段差异落在哪个函数里」，所以 A 应该是**有符号**的那一份
（例如原版 libTrialsGo.so），B 是打过补丁/换过版本的。最后按函数聚合，
直接告诉你「哪几个函数被动过」。

用法:
    python tools/re/libdiff.py <原版.so> <改过.so>
"""
import struct, sys, collections

if len(sys.argv) < 3:
    sys.exit(__doc__)

a_path, b_path = sys.argv[1], sys.argv[2]
A = open(a_path, 'rb').read()
B = open(b_path, 'rb').read()
print(f'sizeA={len(A)} sizeB={len(B)}')

# ---- ELF64 symbol table of A ----
def elf_symbols(data):
    if data[:4] != b'\x7fELF':
        return [], 0
    is64 = data[4] == 2
    assert is64, 'only ELF64'
    e_shoff = struct.unpack_from('<Q', data, 0x28)[0]
    e_shentsize = struct.unpack_from('<H', data, 0x3a)[0]
    e_shnum = struct.unpack_from('<H', data, 0x3c)[0]
    e_shstrndx = struct.unpack_from('<H', data, 0x3e)[0]
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from('<IIQQQQIIQQ', data, o)
        secs.append(dict(name=name, typ=typ, addr=addr, off=off, size=size, link=link, entsize=entsize, idx=i))
    shstr = secs[e_shstrndx]
    def sname(x):
        e = data.index(b'\0', shstr['off'] + x)
        return data[shstr['off'] + x:e].decode('latin1')
    syms = []
    total = 0
    for s in secs:
        if s['typ'] in (2, 11) and s['entsize']:
            strtab = secs[s['link']]
            n = s['size'] // s['entsize']
            total += n
            for i in range(n):
                o = s['off'] + i * s['entsize']
                nm, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', data, o)
                if nm == 0 or value == 0:
                    continue
                e = data.index(b'\0', strtab['off'] + nm)
                name = data[strtab['off'] + nm:e].decode('latin1')
                syms.append((value, size, name, s['typ'] == 2))
    return syms, total

syms, total = elf_symbols(A)
funcs = [(v, sz, n) for (v, sz, n, is_symtab) in syms if sz > 0]
funcs.sort()
print(f'symbols with size: {len(funcs)}')
starts = [f[0] for f in funcs]

import bisect
def find_sym(off):
    i = bisect.bisect_right(starts, off) - 1
    if i < 0:
        return None
    v, sz, n = funcs[i]
    if v <= off < v + sz:
        return (n, v, sz, off - v)
    return None

# ---- diff ----
diffs = []
i = 0
n = min(len(A), len(B))
while i < n:
    if A[i] != B[i]:
        j = i
        while j < n and A[j] != B[j]:
            j += 1
        diffs.append((i, j - i))
        i = j
    else:
        i += 1
print(f'diff runs={len(diffs)} total differing bytes={sum(d[1] for d in diffs)}')
for off, ln in diffs[:400]:
    s = find_sym(off)
    tag = f'{s[0]}  (+0x{s[3]:x} of 0x{s[2]:x})' if s else '<无符号/非函数区>'
    print(f'  0x{off:08x} len={ln:<6} {tag}')
if len(diffs) > 400:
    print(f'  ... 还有 {len(diffs)-400} 段')

# group by symbol
by = collections.OrderedDict()
for off, ln in diffs:
    s = find_sym(off)
    k = s[0] if s else '<无符号>'
    if k not in by:
        by[k] = [0, 0]
    by[k][0] += 1
    by[k][1] += ln
print('\n=== 按函数聚合（按差异字节数降序） ===')
for k, (cnt, nb) in sorted(by.items(), key=lambda x: -x[1][1]):
    print(f'{nb:8d} 字节 / {cnt:4d} 段   {k}')
