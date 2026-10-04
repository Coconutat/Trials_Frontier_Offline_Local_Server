#!/usr/bin/env python3
"""_gotres.py <so> <0xgot_addr> [...] -- resolve GOT/data slots (RELATIVE & symbol relocs) to names"""
import sys, struct

raw = open(sys.argv[1], 'rb').read()
targets = [int(a, 16) for a in sys.argv[2:]]

e_shoff = struct.unpack_from("<Q", raw, 0x28)[0]
e_shentsize = struct.unpack_from("<H", raw, 0x3a)[0]
e_shnum = struct.unpack_from("<H", raw, 0x3c)[0]
e_shstrndx = struct.unpack_from("<H", raw, 0x3e)[0]
secs = []
for i in range(e_shnum):
    o = e_shoff + i * e_shentsize
    name, typ, flags, addr, off, size, link, info, align, entsize = \
        struct.unpack_from("<IIQQQQIIQQ", raw, o)
    secs.append(dict(name=name, typ=typ, flags=flags, addr=addr, off=off,
                     size=size, link=link, entsize=entsize))
sh = secs[e_shstrndx]
def sname(n):
    s = sh['off'] + n
    return raw[s:raw.index(b'\0', s)].decode()
for s in secs:
    s['n'] = sname(s['name'])
by = {s['n']: s for s in secs}

# dynsym: idx -> (name, value, size)
dynsym = by['.dynsym']
dstr = secs[dynsym['link']]
def dsym(idx):
    o = dynsym['off'] + idx * 24
    nm, info, other, shndx, val, sz = struct.unpack_from('<IBBHQQ', raw, o)
    p = raw.index(b'\0', dstr['off'] + nm)
    return raw[dstr['off'] + nm:p].decode('utf8', 'replace'), val, sz

# addr -> name (all syms)
allnames = {}
for sn in ('.dynsym', '.symtab'):
    s = by.get(sn)
    if not s:
        continue
    strs = secs[s['link']]
    for k in range(s['size'] // 24):
        o = s['off'] + k * 24
        nm, info, other, shndx, val, sz = struct.unpack_from('<IBBHQQ', raw, o)
        if not val:
            continue
        p = raw.index(b'\0', strs['off'] + nm)
        name = raw[strs['off'] + nm:p].decode('utf8', 'replace')
        if name:
            allnames.setdefault(val, name)

def near(a):
    best = None
    for v, n in allnames.items():
        if v <= a and (best is None or v > best[0]):
            best = (v, n)
    return ("%s+0x%x" % (best[1], a - best[0])) if best else "0x%x" % a

relmap = {}
for sn in ('.rela.dyn', '.rela.plt'):
    s = by.get(sn)
    if not s:
        continue
    for k in range(s['size'] // 24):
        o = s['off'] + k * 24
        r_off, r_info, r_add = struct.unpack_from("<QQq", raw, o)
        relmap.setdefault(r_off, []).append((sn, r_info & 0xFFFFFFFF, r_info >> 32, r_add))

for t in targets:
    print("== slot 0x%08x ==" % t)
    for sn, rtype, rsym, r_add in relmap.get(t, []):
        if rtype == 1027:
            print("   %s RELATIVE -> 0x%08x  %s" % (sn, r_add, near(r_add)))
        else:
            nm, val, sz = dsym(rsym)
            print("   %s type=%d -> %s (0x%08x sz=%d) addend=0x%x" % (sn, rtype, nm, val, sz, r_add))
    if t not in relmap:
        print("   (no relocation; raw=0x%08x)" % struct.unpack_from("<Q", raw, t - 0x10000)[0])
