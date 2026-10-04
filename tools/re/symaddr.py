"""tools/re/symaddr.py <so> <符号名或子串> [...]  -- 打印符号地址/大小（.dynsym + .symtab）

用法:
    python tools/re/symaddr.py tmp\\libcmp\\orig-libTrialsGo.so _ZN2tr12StoreManager23parseStoreConfigurationEPN4json10json_valueE
    python tools/re/symaddr.py tmp\\libcmp\\orig-libTrialsGo.so --sub StoreManager
"""
import struct
import sys


def load(path):
    d = open(path, 'rb').read()
    e_shoff = struct.unpack_from('<Q', d, 0x28)[0]
    e_shentsize = struct.unpack_from('<H', d, 0x3a)[0]
    e_shnum = struct.unpack_from('<H', d, 0x3c)[0]
    e_shstrndx = struct.unpack_from('<H', d, 0x3e)[0]
    secs = []
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        name, typ, flags, addr, off, size, link, info, align, entsize = \
            struct.unpack_from('<IIQQQQIIQQ', d, o)
        secs.append(dict(name=name, typ=typ, flags=flags, addr=addr, off=off,
                         size=size, link=link, entsize=entsize))
    shstr = secs[e_shstrndx]

    def sname(n):
        s = shstr['off'] + n
        return d[s:d.index(b'\0', s)].decode('utf-8', 'replace')

    for s in secs:
        s['sname'] = sname(s['name'])
    out = {}
    for s in secs:
        if s['typ'] not in (2, 11):          # SYMTAB / DYNSYM
            continue
        strs = secs[s['link']]
        ents = s['entsize'] or 24
        for i in range(s['size'] // ents):
            o = s['off'] + i * ents
            nm, info, other, shndx, val, sz = struct.unpack_from('<IBBHQQ', d, o)
            st = strs['off'] + nm
            name = d[st:d.index(b'\0', st)].decode('utf-8', 'replace')
            if name and val:
                out.setdefault(name, (val, sz))
    return out


def main():
    so = sys.argv[1]
    args = sys.argv[2:]
    syms = load(so)
    if args and args[0] == '--sub':
        needle = args[1]
        hits = sorted(((v[0], v[1], k) for k, v in syms.items() if needle in k))
        for a, sz, k in hits:
            print("0x%08x  %6d  %s" % (a, sz, k))
        print("共 %d 个" % len(hits))
        return
    for name in args:
        v = syms.get(name)
        print(("0x%08x  %6d  " % v) + name if v else "NOT FOUND  " + name)


if __name__ == '__main__':
    main()
