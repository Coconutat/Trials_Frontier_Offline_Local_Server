# -*- coding: utf-8 -*-
"""Brute-force the loc KEY string whose mt::String::getHashCode == target.

Loc ids are 32-bit hashes of an ASCII key (see tools/re/locdump.py:get_hash_code).
Pass 1 hashes every printable ASCII run in the .so; pass 2 (only if pass 1
misses) hashes substrings, capped so it stays interactive.

usage: python tools/re/lockey.py [9e474b4a] [so] [--sub]
"""
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
DO_SUB = "--sub" in sys.argv
TARGET = int(args[0], 16) if len(args) > 0 else 0x9E474B4A
SO = args[1] if len(args) > 1 else r"tmp/libcmp/orig-libTrialsGo.so"


def get_hash_code(s):
    if isinstance(s, str):
        s = s.encode("utf-8")
    w8 = len(s) & 0xFFFFFFFF
    h = 0
    for ch in s:
        h = (w8 * ch + h) & 0xFFFFFFFF
        w8 = ((w8 & 0xFFFF) * 0x4650 + (w8 >> 16)) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


def main():
    data = open(SO, "rb").read()
    print("so=%s  target=0x%08x" % (SO, TARGET))
    runs = re.findall(rb"[\x20-\x7e]{4,120}", data)
    print("printable runs: %d" % len(runs))

    hits = []
    n = 0
    for r in runs:
        n += 1
        if get_hash_code(r) == TARGET:
            hits.append(r)
    print("pass1 hashed %d full runs, hits=%d" % (n, len(hits)))
    for h in sorted(set(hits)):
        print("   HIT(full):", h.decode("ascii", "replace"))

    if hits or not DO_SUB:
        if not hits:
            print("no full-run hit; rerun with --sub to scan substrings")
        return

    CAP = 40_000_000
    seen = set()
    cands = 0
    for r in runs:
        L = len(r)
        for i in range(L):
            for j in range(i + 5, min(L, i + 48) + 1):
                s = r[i:j]
                if s in seen:
                    continue
                seen.add(s)
                cands += 1
                if get_hash_code(s) == TARGET:
                    hits.append(s)
                    print("   HIT(sub):", s.decode("ascii", "replace"))
                if cands >= CAP:
                    print("cap reached at %d candidates" % cands)
                    return
    print("pass2 hashed %d substrings, total hits=%d" % (cands, len(hits)))


main()
