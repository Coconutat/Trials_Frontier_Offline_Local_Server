#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""LOCF localization dumper / ITEM_ key resolver for Trials Frontier.

LOCF 文件来自 `content.dat` 的 `/gen/lang/<lang>_strings.bin` 成员（解包后放在
`tmp/lang/`）。id 就是 `mt::String::getHashCode(KEY)`，本文件内自带移植实现。

Usage:
  python tools/re/locdump.py dump                   -> 写 tmp/lang/all_en.txt / all_zh.txt（hash<TAB>text）
  python tools/re/locdump.py item [maxid] [maxlvl]  -> 爆破 ITEM_<id>_<lvl>(_<n>) 并输出对照表
  python tools/re/locdump.py key <KEY>              -> 反查单个本地化键
"""
import struct, sys, os


def _find_root(start):
    """向上找到含 server/tf_server.py 的仓库根（tmp/ 是相对它定位的）。"""
    d = start
    for _ in range(6):
        if os.path.exists(os.path.join(d, 'server', 'tf_server.py')):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return os.path.dirname(os.path.dirname(start))


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))


def get_hash_code(s):
    """mt::String::getHashCode @0x008695ac, ported byte-exact."""
    if isinstance(s, str):
        s = s.encode('utf-8')
    w8 = len(s) & 0xFFFFFFFF
    h = 0
    for ch in s:
        h = (w8 * ch + h) & 0xFFFFFFFF
        w8 = ((w8 & 0xFFFF) * 0x4650 + (w8 >> 16)) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


def load(path):
    """Parse a LOCF file (trailer of content.dat member /gen/lang/<lang>_strings.bin)."""
    b = open(path, 'rb').read()
    assert b[:4] == b'LOCF', 'bad magic %r' % b[:4]
    ver = b[4]
    n = struct.unpack_from('<I', b, 5)[0]
    q = 9
    d = {}
    for _ in range(n):
        h = struct.unpack_from('<I', b, q)[0]; q += 4
        L = struct.unpack_from('<H', b, q)[0]; q += 2
        s = b[q:q + L]; q += L
        d[h] = s.rstrip(b'\x00').decode('utf-8', 'replace')
    assert q == len(b), (q, len(b))
    return d


LANGS = ['english', 'simp_chinese', 'trad_chinese', 'french', 'german', 'italian',
         'spanish', 'russian', 'braz_portuguese', 'korean', 'japanese']


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'dump'
    if cmd == 'dump':
        out = os.path.join(ROOT, 'tmp', 'lang')
        os.makedirs(out, exist_ok=True)
        for tag in LANGS:
            p = os.path.join(out, '%s.bin' % tag)
            if not os.path.exists(p):
                continue
            d = load(p)
            with open(os.path.join(out, 'all_%s.txt' % tag), 'w', encoding='utf-8') as f:
                for h, v in d.items():
                    f.write('%08x\t%s\n' % (h, v))
            print(tag, len(d), 'entries ->', 'tmp/lang/all_%s.txt' % tag)
    elif cmd == 'key':
        for tag in ('english', 'simp_chinese'):
            d = load(os.path.join(ROOT, 'tmp', 'lang', '%s.bin' % tag))
            print(tag, repr(d.get(get_hash_code(sys.argv[2]))))
    elif cmd == 'item':
        maxid = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
        maxlvl = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        en = load(os.path.join(ROOT, 'tmp', 'lang', 'english.bin'))
        zh = load(os.path.join(ROOT, 'tmp', 'lang', 'simp_chinese.bin'))
        hits = []
        for i in range(maxid + 1):
            for l in range(maxlvl + 1):
                h = get_hash_code('ITEM_%d_%d' % (i, l))
                if h in en:
                    hits.append((i, l, None, en[h], zh.get(h, '')))
                for n in range(6):
                    h = get_hash_code('ITEM_%d_%d_%d' % (i, l, n))
                    if h in en:
                        hits.append((i, l, n, en[h], zh.get(h, '')))
        out = os.path.join(ROOT, 'tmp', 'packout')
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, 'item_names.tsv'), 'w', encoding='utf-8') as f:
            f.write('item_id\tlevel\tvariant\tenglish\tsimp_chinese\n')
            for i, l, n, e, z in hits:
                f.write('%d\t%s\t%s\t%s\t%s\n' % (i, l, '' if n is None else n, e, z))
        print('hits', len(hits), '-> tmp/packout/item_names.tsv')
        for row in hits[:40]:
            print(row)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
