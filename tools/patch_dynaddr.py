#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把"服务器地址来自本地文本文件"的能力注入原生库（Design H）。

原理
----
libTrialsGo.so / libubiservices.so 的 .rodata 里存着硬编码的育碧 URL 字面量。
本工具在库的可执行节里找一块全零的"代码洞"，写入一个小例程，并把 .dynamic 里
一个空闲的 DT_NULL 槽改成 DT_INIT 指向它。动态链接器加载该库时会先调用这个例程：

  1. 用**裸 syscall**（openat/read/close，无需任何导入符号）读
     /sdcard/Android/data/<pkg>/files/tf_server.txt，取第一行并做首尾空白修剪；
     读不到就回落到构建期默认地址。
  2. 对本库每个 URL 字面量：先 mprotect 覆盖它的页为 RW，再就地重写成
     "http://" + 文件里的地址 + 原来的路径尾巴，余下用 NUL 补齐。

于是**同一份 APK 可以指向任意服务器**，用户改一个文本文件即可，不必重新打补丁/重签名。
构建期仍会把字面量改写成默认地址，保证文件不存在时也能跑。

安全约束
--------
* 只改 .rodata 里的字面量，且新串必须放得进原串占的字节数（绝不越界）。
* mprotect 的页范围会校验**不与任何含代码的页重叠**，避免代码页失去 X。
* 只用裸 syscall，不引入任何新的导入符号、不新增重定位、不动 .init_array。

用法
----
    python tools/patch_dynaddr.py --so <in.so> --out <out.so> \
        --base 127.0.0.1:8000 [--report r.json] [--dry-run]
"""

import argparse
import json
import os
import re
import struct
import sys

try:
    from elftools.elf.elffile import ELFFile
except ImportError:
    print("需要 pyelftools: python -m pip install pyelftools", file=sys.stderr)
    sys.exit(2)

try:
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
except ImportError:
    print("需要 keystone-engine: python -m pip install keystone-engine", file=sys.stderr)
    sys.exit(2)

# 与 tools/patch_urls.py 保持一致的目标筛选规则
HOST_SUFFIXES = (".ubi.com",)
HOST_EXACT = ("s3.amazonaws.com",)
HOST_SKIP = ("legal.ubi.com", "forums.ubi.com", "ubisoft-avatars.akamaized.net")
LIT_RE = re.compile(rb"https?://([A-Za-z0-9_{}.\-]+)((?:/[^\x00]*)?)")

CONF_PATH = ("/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp"
             "/files/tf_server.txt")

SYS_OPENAT = 56
SYS_CLOSE = 57
SYS_READ = 63
SYS_MPROTECT = 226
AT_FDCWD = -100
PROT_RW = 3


# ---------------------------------------------------------------- ELF helpers

def load_elf(path):
    with open(path, 'rb') as f:
        raw = bytearray(f.read())
    elf = ELFFile(open(path, 'rb'))
    return raw, elf


def rodata_sections(elf):
    """进内存、可读、不可执行的节（字面量所在的只读数据）。"""
    for sec in elf.iter_sections():
        fl = sec['sh_flags']
        if not (fl & 0x2):      # SHF_ALLOC
            continue
        if fl & 0x4:            # SHF_EXECINSTR
            continue
        yield sec


def is_standalone(data, start, end):
    before_ok = start == 0 or data[start - 1] == 0
    after_ok = end >= len(data) or data[end] == 0
    return before_ok and after_ok


def find_literals(elf):
    """返回 [(va, old_bytes, host, tail)]。"""
    out = []
    for sec in rodata_sections(elf):
        data = sec.data()
        sec_va = sec['sh_addr']
        for m in LIT_RE.finditer(data):
            host = m.group(1).decode('ascii', 'replace')
            tail = m.group(2)
            plain = host.lstrip('{env}').lstrip('_')
            if host in HOST_SKIP or plain in HOST_SKIP:
                continue
            if not (any(host.endswith(s) or plain.endswith(s) for s in HOST_SUFFIXES)
                    or host in HOST_EXACT or plain in HOST_EXACT):
                continue
            start, end = m.start(), m.end()
            if not is_standalone(data, start, end):
                continue
            out.append((sec_va + start, m.group(0), host, tail))
    return out


# ------------------------------------------------------- code-space / hooks

def exec_segments(elf):
    for p in elf.iter_segments():
        if p['p_type'] == 'PT_LOAD' and (p['p_flags'] & 0x1):
            yield p


def branch_targets(elf):
    """所有直接分支（B/BL/B.cond/CBZ/CBNZ/TBZ/TBNZ）的目标 vaddr 集合。

    洞必须避开这些地址 —— 否则会覆盖掉别人要跳进来的指令。
    """
    tgts = set()
    for sec in elf.iter_sections():
        if not (sec['sh_flags'] & 0x4) or not sec['sh_size']:
            continue
        data = sec.data()
        va = sec['sh_addr']
        for i in range(0, len(data) - 3, 4):
            w = struct.unpack_from('<I', data, i)[0]
            off = None
            if (w & 0x7C000000) == 0x14000000:          # B / BL
                off = w & 0x03FFFFFF
                if off & 0x02000000:
                    off -= 0x04000000
            elif (w & 0xFF000010) == 0x54000000:        # B.cond
                off = (w >> 5) & 0x7FFFF
                if off & 0x40000:
                    off -= 0x80000
            elif (w & 0x7E000000) == 0x34000000:        # CBZ / CBNZ
                off = (w >> 5) & 0x7FFFF
                if off & 0x40000:
                    off -= 0x80000
            elif (w & 0x7E000000) == 0x36000000:        # TBZ / TBNZ
                off = (w >> 5) & 0x3FFF
                if off & 0x2000:
                    off -= 0x4000
            if off is not None:
                tgts.add(va + i + off * 4)
    return tgts


def find_cave(elf, raw, size):
    """在**可执行节**（.text/.plt）内部找 size 字节的全零连续段。

    只认 SHF_EXECINSTR 的节 —— .eh_frame / .rodata / .gcc_except_table 虽然也在
    可执行段里，但它们是活数据，往里写会破坏展开信息。
    """
    cands = []
    tgts = branch_targets(elf)
    for sec in elf.iter_sections():
        fl = sec['sh_flags']
        if not (fl & 0x4) or not (fl & 0x2) or not sec['sh_size']:
            continue
        data = sec.data()
        base_va, base_off = sec['sh_addr'], sec['sh_offset']
        run = None
        for i in range(len(data) + 1):
            z = i < len(data) and data[i] == 0
            if z and run is None:
                run = i
            elif not z and run is not None:
                if i - run >= size and not any(
                        (base_va + r) in tgts for r in range(run, i)):
                    cands.append((base_va + run, i - run, base_off + run))
                run = None
    return cands


def spare_dynamic_slots(elf):
    """返回 .dynamic 里空闲的 DT_NULL 槽 [(file_off, va)]。"""
    dyn = elf.get_section_by_name('.dynamic')
    if dyn is None:
        return []
    data = dyn.data()
    out = []
    for i in range(0, len(data) - 15, 16):
        tag, val = struct.unpack_from('<QQ', data, i)
        if tag == 0:
            out.append((dyn['sh_offset'] + i, dyn['sh_addr'] + i))
    return out


def text_pages(path_raw, elf):
    """所有含代码（SHF_EXECINSTR）的页号集合。"""
    pages = set()
    for sec in elf.iter_sections():
        if not (sec['sh_flags'] & 0x4) or not sec['sh_size']:
            continue
        a = sec['sh_addr'] & ~0xFFF
        b = (sec['sh_addr'] + sec['sh_size'] + 0xFFF) & ~0xFFF
        for p in range(a, b, 0x1000):
            pages.add(p)
    return pages


# ------------------------------------------------------------ routine build

def build_routine(cave_va, entries, default_host, conf_path):
    """用 keystone 汇编出注入例程。entries: [(dest_va, cap, tail_bytes)]"""
    if len(entries) > 200:
        raise SystemExit("字面量太多")

    lines = []
    a = lines.append
    a("tfinit:")
    a("  stp x29, x30, [sp, #-0xc0]!")
    a("  mov x29, sp")
    a("  stp x19, x20, [sp, #0x10]")
    a("  stp x21, x22, [sp, #0x20]")
    a("  stp x23, x24, [sp, #0x30]")
    a("  stp x25, x26, [sp, #0x40]")
    a("  stp x27, x28, [sp, #0x50]")
    # 定位加载基址：本函数的链接期地址 vs 运行期地址
    a("  adr x19, tfinit")
    a("  movz x20, #%d" % (cave_va & 0xFFFF))
    a("  movk x20, #%d, lsl #16" % ((cave_va >> 16) & 0xFFFF))
    a("  sub x19, x19, x20")
    # 默认地址
    a("  adr x23, s_default")
    # openat(AT_FDCWD, conf_path, O_RDONLY, 0)
    a("  mov x0, #%d" % AT_FDCWD)
    a("  adr x1, s_path")
    a("  mov w2, #0")
    a("  mov w3, #0")
    a("  mov x8, #%d" % SYS_OPENAT)
    a("  svc #0")
    a("  cmp x0, #0")
    a("  b.lt Lstrlen")
    a("  mov x21, x0")
    # read(fd, sp+0x60, 0x3f)
    a("  mov x0, x21")
    a("  add x1, sp, #0x60")
    a("  mov w2, #0x3f")
    a("  mov x8, #%d" % SYS_READ)
    a("  svc #0")
    a("  mov x22, x0")
    # close(fd)
    a("  mov x0, x21")
    a("  mov x8, #%d" % SYS_CLOSE)
    a("  svc #0")
    a("  cmp x22, #1")
    a("  b.lt Lstrlen")
    # 截断 + 去尾部空白（含 CR/LF/空格/Tab）
    a("  add x23, sp, #0x60")
    a("  strb wzr, [x23, x22]")
    a("Ltrim:")
    a("  cbz x22, Lstrlen")
    a("  sub x22, x22, #1")
    a("  ldrb w20, [x23, x22]")
    a("  cmp w20, #0x20")
    a("  b.hi Llead")
    a("  strb wzr, [x23, x22]")
    a("  b Ltrim")
    # 去首部空白
    a("Llead:")
    a("  mov x24, x23")
    a("Lskipl:")
    a("  ldrb w20, [x24]")
    a("  cmp w20, #0x20")
    a("  b.hi Lgot")
    a("  cbz w20, Lstrlen")
    a("  add x24, x24, #1")
    a("  b Lskipl")
    a("Lgot:")
    a("  mov x23, x24")
    # 求 host 长度
    a("Lstrlen:")
    a("  mov x24, x23")
    a("  mov x28, #0")
    a("Lscan_loop:")
    a("  ldrb w20, [x24, x28]")
    a("  cbz w20, Lsldone")
    a("  add x28, x28, #1")
    a("  cmp x28, #64")
    a("  b.lo Lscan_loop")
    a("Lsldone:")
    a("  cbz x28, Lend")
    # 遍历表
    a("  adr x24, table")
    a("  mov x25, #%d" % len(entries))
    a("Lloop:")
    a("  ldr w26, [x24]")
    a("  ldr w27, [x24, #4]")
    a("  ldr w20, [x24, #8]")
    a("  ldr w21, [x24, #12]")
    a("  sub x22, x27, #7")
    a("  subs x22, x22, x21")
    a("  b.lo Lnext")
    a("  cmp x28, x22")
    a("  b.hi Lnext")
    a("  add x26, x19, x26")
    a("  add x20, x19, x20")
    # mprotect(align_down(dest), align_up(dest+total)-align_down(dest), RW)
    a("  add x22, x28, #7")
    a("  add x22, x22, x21")
    a("  movz x3, #0xfff")
    a("  mov x0, x26")
    a("  bic x0, x0, x3")
    a("  add x1, x26, x22")
    a("  add x1, x1, x3")
    a("  bic x1, x1, x3")
    a("  sub x1, x1, x0")
    a("  mov w2, #%d" % PROT_RW)
    a("  mov x8, #%d" % SYS_MPROTECT)
    a("  svc #0")
    # "http://"
    a("  adr x0, s_scheme")
    a("  mov x1, x26")
    a("  mov x2, #7")
    a("  bl Lcopy")
    # host
    a("  mov x0, x23")
    a("  add x1, x26, #7")
    a("  mov x2, x28")
    a("  bl Lcopy")
    # tail
    a("  mov x0, x20")
    a("  add x1, x26, #7")
    a("  add x1, x1, x28")
    a("  mov x2, x21")
    a("  bl Lcopy")
    # 余下补 NUL
    a("  add x0, x26, #7")
    a("  add x0, x0, x28")
    a("  add x0, x0, x21")
    a("  add x1, x26, x27")
    a("Lpad:")
    a("  cmp x0, x1")
    a("  b.hs Lnext")
    a("  strb wzr, [x0]")
    a("  add x0, x0, #1")
    a("  b Lpad")
    a("Lnext:")
    a("  add x24, x24, #16")
    a("  subs x25, x25, #1")
    a("  b.ne Lloop")
    # 收尾
    a("Lend:")
    a("  ldp x27, x28, [sp, #0x50]")
    a("  ldp x25, x26, [sp, #0x40]")
    a("  ldp x23, x24, [sp, #0x30]")
    a("  ldp x21, x22, [sp, #0x20]")
    a("  ldp x19, x20, [sp, #0x10]")
    a("  ldp x29, x30, [sp], #0xc0")
    a("  ret")
    # 内部拷贝例程（避免引入 memcpy 导入）
    a("Lcopy:")
    a("  cbz x2, Lcopyret")
    a("Lcopyl:")
    a("  ldrb w3, [x0]")
    a("  strb w3, [x1]")
    a("  add x0, x0, #1")
    a("  add x1, x1, #1")
    a("  subs x2, x2, #1")
    a("  b.ne Lcopyl")
    a("Lcopyret:")
    a("  ret")

    # ---- 数据 ----
    a("  .balign 8")
    a("s_scheme:")
    a('  .asciz "http://"')
    a("  .balign 8")
    a("s_path:")
    a('  .asciz "%s"' % conf_path)
    a("  .balign 8")
    a("s_default:")
    a('  .asciz "%s"' % default_host)
    a("  .balign 8")
    for i, (dest, cap, tail) in enumerate(entries):
        a("tt%d:" % i)
        a('  .asciz "%s"' % tail.decode('ascii').replace('\\', '\\\\').replace('"', '\\"'))
    a("  .balign 8")
    a("table:")
    for i, (dest, cap, tail) in enumerate(entries):
        a("  .word %d" % dest)          # 目标字面量的链接期 vaddr
        a("  .word %d" % cap)           # 可写容量（= 原字面量字节数）
        a("  .word tt%d" % i)            # 路径尾巴的链接期 vaddr
        a("  .word %d" % len(tail))     # 尾巴长度
    src = "\n".join(lines)

    ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
    try:
        enc, cnt = ks.asm(src, addr=cave_va)
    except Exception as e:
        try:
            with open('tmp/last_asm.s', 'w', encoding='utf-8') as f:
                f.write(src)
            print("  汇编源码已存到 tmp/last_asm.s", file=sys.stderr)
        except OSError:
            pass
        raise SystemExit("keystone 汇编失败: %r" % (e,))
    return src, bytes(enc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--so', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--base', default='127.0.0.1:8000')
    ap.add_argument('--path', default=CONF_PATH)
    ap.add_argument('--cave', default=None, help='十六进制注入地址；默认自动选最大的洞')
    ap.add_argument('--report')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    raw, elf = load_elf(args.so)
    base = args.base.strip()
    for pre in ('http://', 'https://'):
        if base.startswith(pre):
            base = base[len(pre):]
    new_prefix = ('http://' + base).encode('ascii')

    lits = find_literals(elf)
    if not lits:
        print("%s: 没有找到可改写的字面量" % os.path.basename(args.so))
        return

    changed, entries, skipped = [], [], []
    for va, old, host, tail in lits:
        cap = len(old)
        new_lit = new_prefix + tail
        if len(new_lit) > cap:
            skipped.append({'va': va, 'old': old.decode('ascii', 'replace'),
                            'reason': '默认地址放不下 %d > %d' % (len(new_lit), cap)})
            continue
        entries.append((va, cap, tail))
        changed.append({'va': va, 'old': old.decode('ascii', 'replace'),
                        'new': new_lit.decode('ascii', 'replace'), 'cap': cap,
                        'tail': tail.decode('ascii', 'replace'),
                        'max_host': cap - 7 - len(tail)})

    if not entries:
        print("%s: 所有字面量都放不下默认地址（%s）" % (os.path.basename(args.so), base))
        for s in skipped:
            print("   ! 0x%08x %s  (%s)" % (s['va'], s['old'], s['reason']))
        raise SystemExit(1)

    caves = find_cave(elf, raw, 512)
    if not caves:
        raise SystemExit("%s: 找不到 ≥512 字节的可执行代码洞" % os.path.basename(args.so))
    caves.sort(key=lambda c: -c[1])
    if args.cave:
        want = int(args.cave, 16)
        cand = [c for c in caves if c[0] == want]
        if not cand:
            raise SystemExit("%s: 指定的洞 0x%x 不可用" % (os.path.basename(args.so), want))
        cave = cand[0]
    else:
        cave = caves[0]
    cave_va, cave_len, cave_foff = cave

    src, blob = build_routine(cave_va, entries, base, args.path)
    if len(blob) > cave_len:
        raise SystemExit("%s: 例程 %d 字节 > 洞 %d 字节"
                         % (os.path.basename(args.so), len(blob), cave_len))

    # 安全校验：mprotect 覆盖的页不得含代码
    codepages = text_pages(raw, elf)
    for va, cap, tail in entries:
        a = va & ~0xFFF
        b = (va + cap + 0xFFF) & ~0xFFF
        for p in range(a, b, 0x1000):
            if p in codepages:
                raise SystemExit("危险：字面量 0x%x 所在页 0x%x 含代码，拒绝 mprotect" % (va, p))

    slots = spare_dynamic_slots(elf)
    need = 2   # DT_INIT + 至少要留一个 DT_NULL 终止
    if len(slots) < need:
        raise SystemExit("%s: .dynamic 里没有足够的空闲 DT_NULL 槽" % os.path.basename(args.so))
    slot_foff, slot_va = slots[0]

    seg = next((p for p in exec_segments(elf)), None)
    if seg is None:
        raise SystemExit("没有可执行 PT_LOAD")
    if seg['p_offset'] != seg['p_vaddr']:
        # 只有 off==va 时 file_off 才等于 va
        raise SystemExit("%s: 可执行段 off(0x%x) != va(0x%x)，需要额外的映射换算"
                         % (os.path.basename(args.so), seg['p_offset'], seg['p_vaddr']))

    print("%s" % args.so)
    print("  默认地址 %s   配置文件 %s" % (base, args.path))
    print("  代码洞   0x%08x  (%d 字节可用, 例程 %d 字节)" % (cave_va, cave_len, len(blob)))
    print("  DT_INIT  写入 .dynamic 文件偏移 0x%x (va 0x%x) -> 0x%x" % (slot_foff, slot_va, cave_va))
    for c in changed:
        print("    0x%08x cap=%-3d max_host=%-3d %s" % (
            c['va'], c['cap'], c['max_host'], c['old']))
    for s in skipped:
        print("    ! 跳过 0x%08x %s (%s)" % (s['va'], s['old'], s['reason']))

    if args.dry_run:
        print("  (dry-run，未写出文件)")
        if args.report:
            with open(args.report, 'w', encoding='utf-8') as f:
                json.dump({'so': args.so, 'base': base, 'cave': cave_va,
                           'routine_len': len(blob), 'changed': changed,
                           'skipped': skipped, 'asm': src}, f,
                          ensure_ascii=False, indent=2)
        return

    # ---- 落盘 ----
    for va, cap, tail in entries:
        new_lit = new_prefix + tail
        padded = new_lit + b'\x00' * (cap - len(new_lit))
        raw[va:va + cap] = padded          # off == va（上面已校验）
    raw[cave_foff:cave_foff + len(blob)] = blob
    struct.pack_into('<QQ', raw, slot_foff, 12, cave_va)   # DT_INIT

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'wb') as f:
        f.write(bytes(raw))
    print("  -> %s (%d 字节)" % (args.out, len(raw)))

    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump({'so': args.so, 'out': args.out, 'base': base, 'cave': cave_va,
                       'routine_len': len(blob), 'changed': changed,
                       'skipped': skipped}, f, ensure_ascii=False, indent=2)
        print("  明细: %s" % args.report)


if __name__ == '__main__':
    main()
