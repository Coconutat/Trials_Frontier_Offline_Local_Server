"""gref.py <so> <target_va> [target_va ...] —— 找出 adrp(+add) 解析到目标地址的位置。

按 4 字节对齐扫描整段映像，直接位运算解 adrp 编码（不做线性反汇编，
避免数据段把反汇编器带偏）。找到 adrp 之后在其后 32 字节内找配对的 add。
"""
import struct
import sys

so = sys.argv[1]
targets = {int(a, 16): [] for a in sys.argv[2:]}
data = open(so, "rb").read()
n = len(data) & ~3


def sign_ext(v, bits):
    m = 1 << (bits - 1)
    return (v ^ m) - m


for i in range(0, n, 4):
    w = struct.unpack_from("<I", data, i)[0]
    if (w & 0x9F000000) != 0x90000000:
        continue
    rd = w & 0x1F
    immlo = (w >> 29) & 3
    immhi = (w >> 5) & 0x7FFFF
    imm = sign_ext((immhi << 2) | immlo, 21) << 12
    page = (i & ~0xFFF) + imm
    # 这个 adrp 指向的页面上有没有我们的目标
    hot = [t for t in targets if (t & ~0xFFF) == page]
    if not hot:
        continue
    # 往后 32 字节里找 add Rd, Rd, #off
    for j in range(i + 4, min(i + 36, n), 4):
        w2 = struct.unpack_from("<I", data, j)[0]
        # add (immediate): sf 0 0 100010 sh imm12 Rn Rd
        if (w2 & 0x7F800000) != 0x11000000:
            continue
        if (w2 & 0x1F) != rd or ((w2 >> 5) & 0x1F) != rd:
            continue
        sh = (w2 >> 22) & 1
        imm12 = (w2 >> 10) & 0xFFF
        va = page + (imm12 << (12 if sh else 0))
        if va in targets:
            targets[va].append(i)

for t in sorted(targets):
    print("== 0x%08x ==" % t)
    for a in targets[t]:
        print("   adrp@0x%08x" % a)
    if not targets[t]:
        print("   (无)")
