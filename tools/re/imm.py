# -*- coding: utf-8 -*-
"""Scan .text for MOVZ/MOVK immediates that assemble into a 32-bit constant.

usage: python tools/re/imm.py [9e474b4a] [so]

Finds both single-instruction forms (MOVZ/MOVN/MOV-wide) and the two-instruction
MOVZ low + MOVK lsl#16 pair used for arbitrary 32-bit constants.
"""
import struct
import sys

args = [a for a in sys.argv[1:] if not a.startswith("-")]
TARGET = int(args[0], 16) if args else 0x9E474B4A
SO = args[1] if len(args) > 1 else r"tmp/libcmp/orig-libTrialsGo.so"

raw = open(SO, "rb").read()

# --- section table ---
e_shoff = struct.unpack_from("<Q", raw, 0x28)[0]
e_shentsize = struct.unpack_from("<H", raw, 0x3A)[0]
e_shnum = struct.unpack_from("<H", raw, 0x3C)[0]
e_shstrndx = struct.unpack_from("<H", raw, 0x3E)[0]
secs = []
for i in range(e_shnum):
    o = e_shoff + i * e_shentsize
    nameoff, typ, flags, addr, off, size = struct.unpack_from("<IIQQQQ", raw, o)
    secs.append((nameoff, addr, off, size))
sh = secs[e_shstrndx]
strtab = raw[sh[2]:sh[2] + sh[3]]


def nm(o):
    e = strtab.find(b"\x00", o)
    return strtab[o:e].decode()


text = None
for nameoff, addr, off, size in secs:
    if nm(nameoff) == ".text":
        text = (addr, off, size)
print("so=%s  .text va=0x%x off=0x%x size=0x%x  target=0x%08x"
      % (SO, text[0], text[1], text[2], TARGET))

va, off, size = text
lo = TARGET & 0xFFFF
hi = (TARGET >> 16) & 0xFFFF
print("  expect MOVZ imm16=0x%04x hw=0   and MOVK imm16=0x%04x hw=1" % (lo, hi))

found = []
for p in range(off, off + size - 4, 4):
    w = struct.unpack_from("<I", raw, p)[0]
    op = w & 0x7F800000
    if op not in (0x52800000, 0x72800000):   # MOVZ / MOVK (32-bit)
        continue
    hw = (w >> 21) & 3
    imm16 = (w >> 5) & 0xFFFF
    rd = w & 0x1F
    if (op == 0x52800000 and hw == 0 and imm16 == lo) or \
       (op == 0x72800000 and hw == 1 and imm16 == hi):
        found.append((p - off + va, w, "MOVZ" if op == 0x52800000 else "MOVK", rd, imm16))

for a, w, k, rd, i in found:
    print("  0x%08x  %s w%d, #0x%04x   (word 0x%08x)" % (a, k, rd, i, w))
print("total %d partial matches" % len(found))
