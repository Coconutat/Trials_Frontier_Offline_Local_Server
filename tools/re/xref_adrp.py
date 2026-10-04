#!/usr/bin/env python3
"""_tgtxref.py <so> <target_va> [target_va ...]
Robust ADRP(+ADD/LDR) xref scanner: linear-scan .text tracking per-register ADRP page.
Handles ADRP and ADD/LDR separated by other instructions.

用法:
  python tools/re/xref_adrp.py tmp/libcmp/orig-libTrialsGo.so 0xb8578d
"""
import sys, struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from capstone.arm64 import ARM64_OP_REG, ARM64_OP_IMM, ARM64_OP_MEM

PATH = sys.argv[1]
TARGETS = set(int(a, 16) for a in sys.argv[2:])
raw = open(PATH, "rb").read()

# sections
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

# symbols for naming
syms = {}
for sn in ('.dynsym', '.symtab'):
    s = by.get(sn)
    if not s:
        continue
    strs = secs[s['link']]
    for k in range(s['size'] // 24):
        o = s['off'] + k * 24
        nm, info, other, shndx, val, sz = struct.unpack_from('<IBBHQQ', raw, o)
        if val == 0:
            continue
        p = raw.index(b'\0', strs['off'] + nm)
        name = raw[strs['off'] + nm:p].decode('utf8', 'replace')
        if name and (val not in syms or (sz and not syms[val][0])):
            syms[val] = (sz, name)

def name_of(a):
    best = None
    for v, (sz, n) in syms.items():
        if sz and v <= a < v + sz:
            if best is None or v > best[0]:
                best = (v, n, sz)
    if best:
        return "0x%08x+%d %s" % (best[0], a - best[0], best[1])
    return "(nosym)"

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True

# names of registers
def rn(op):
    return md.reg_name(op.reg)

def rr(regid):
    return md.reg_name(regid)

hits = {}
text = by['.text']
data = raw[text['off']:text['off'] + text['size']]
base = text['addr']

page = {}          # reg -> (page_addr, addr_of_adrp)
prev_adrp = None
prev_adrp_reg = None
prev_adrp_addr = None
for ins in md.disasm(data, base):
    m = ins.mnemonic
    if m == 'adrp':
        page[rn(ins.operands[0])] = ins.operands[1].imm
        prev_adrp_reg = rn(ins.operands[0])
        prev_adrp_addr = ins.address
        prev_adrp = ins.operands[1].imm
        continue
    tgt = None
    if m in ('add', 'ldr', 'ldrb', 'ldrh', 'ldrsw', 'str', 'strb', 'strh', 'adds', 'sub', 'cmp'):
        ops = ins.operands
        # add Xd, Xn, #imm
        if m in ('add', 'adds', 'sub', 'cmp') and len(ops) == 3 and ops[2].type == ARM64_OP_IMM \
                and ops[1].type == ARM64_OP_REG and rn(ops[1]) in page:
            tgt = page[rn(ops[1])] + ops[2].imm
        elif len(ops) >= 2 and ops[-1].type == ARM64_OP_MEM:
            mem = ops[-1].mem
            if mem.base != 0 and rr(mem.base) in page:
                tgt = page[rr(mem.base)] + mem.disp
    if tgt is not None and tgt in TARGETS:
        hits.setdefault(tgt, []).append((ins.address, m, ins.op_str))
    # invalidate dest register's page on write (dest != source)
    if ins.operands and ins.operands[0].type == ARM64_OP_REG and m not in ('cmp', 'tst', 'str', 'strb', 'strh'):
        d = rn(ins.operands[0])
        # add Xd, Xn, #imm keeps page if Xd==Xn
        if m in ('add', 'sub') and len(ins.operands) == 3 and ins.operands[1].type == ARM64_OP_REG \
                and rn(ins.operands[1]) == d and ins.operands[2].type == ARM64_OP_IMM:
            pass
        else:
            page.pop(d, None)

for t in sorted(TARGETS):
    print("==== target 0x%08x ====" % t)
    for a, m, ops in hits.get(t, []):
        print("   xref 0x%08x  %-6s %-40s  in %s" % (a, m, ops, name_of(a)))
    if t not in hits:
        print("   (none)")
