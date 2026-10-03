#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把原生库里的硬编码服务器域名重写成用户自己的地址（默认走明文 http，免装 CA 证书）。

原理：这些域名是 .rodata 里的 NUL 结尾字面量，路径与域名在同一个字面量里
（例如 "https://api-ubiservices.ubi.com/v2/profiles/sessions"）。
只替换 "scheme://host" 这一段，后面的路径原样保留，剩余空间用 NUL 补齐。
新串必须不比旧串长，否则报错退出 —— 绝不越界改写。

用法：
    python tools/patch_urls.py --so <in.so> --out <out.so> --base 127.0.0.1:8000
    # 可重复 --so/--out 成对使用；也可 --so a.so:b.so 形式逐个跑

退出码 0 = 成功（含"没找到可改的串"），非 0 = 校验失败。
"""

import argparse
import json
import os
import re
import sys

try:
    from elftools.elf.elffile import ELFFile
except ImportError:
    print("需要 pyelftools: python -m pip install pyelftools", file=sys.stderr)
    sys.exit(2)

# 目标域名后缀 / 精确主机名
HOST_SUFFIXES = (".ubi.com",)
HOST_EXACT = ("s3.amazonaws.com",)
# 明确不动的主机
HOST_SKIP = ("legal.ubi.com", "forums.ubi.com", "ubisoft-avatars.akamaized.net")

LIT_RE = re.compile(rb"https?://([A-Za-z0-9_{}.\-]+)((?:/[^\x00]*)?)")


def rodata_sections(elf):
    for sec in elf.iter_sections():
        # 进内存的只读/可写数据段都可能放字面量；跳过代码段
        if not (sec["sh_flags"] & 0x2):
            continue
        if sec["sh_flags"] & 0x4:
            continue
        yield sec


def is_standalone(data, start, end):
    """字面量必须前后都是 NUL（或段边界），避免改坏相邻数据"""
    before_ok = start == 0 or data[start - 1] == 0
    after_ok = end >= len(data) or data[end] == 0
    return before_ok and after_ok


def patch_file(path, base, report):
    with open(path, "rb") as f:
        raw = bytearray(f.read())
    elf = ELFFile(open(path, "rb"))

    base = base.strip()
    if base.startswith("http://"):
        base = base[len("http://"):]
    elif base.startswith("https://"):
        base = base[len("https://"):]
    new_prefix = ("http://" + base).encode("ascii")
    if not base or len(new_prefix) < 8:
        raise SystemExit("--base 不合法: %r" % base)

    changes = []
    for sec in rodata_sections(elf):
        data = sec.data()
        sec_off = sec["sh_offset"]
        sec_va = sec["sh_addr"]
        for m in LIT_RE.finditer(data):
            host = m.group(1).decode("ascii", "replace")
            tail = m.group(2)
            plain_host = host.lstrip("{env}").lstrip("_")
            if any(host == s or plain_host == s for s in HOST_SKIP) or host in HOST_SKIP:
                continue
            if not (any(host.endswith(sfx) or plain_host.endswith(sfx) for sfx in HOST_SUFFIXES)
                    or host in HOST_EXACT or plain_host in HOST_EXACT):
                continue
            start, end = m.start(), m.end()
            if not is_standalone(data, start, end):
                continue
            new_lit = new_prefix + tail
            if len(new_lit) > end - start:
                changes.append({
                    "va": sec_va + start,
                    "old": m.group(0).decode("ascii", "replace"),
                    "new": new_lit.decode("ascii", "replace"),
                    "ok": False,
                    "reason": "太长 %d > %d" % (len(new_lit), end - start),
                })
                continue
            padded = new_lit + b"\x00" * (end - start - len(new_lit))
            raw[sec_off + start: sec_off + end] = padded
            changes.append({
                "va": sec_va + start,
                "old": m.group(0).decode("ascii", "replace"),
                "new": new_lit.decode("ascii", "replace"),
                "ok": True,
                "pad": end - start - len(new_lit),
            })

    bad = [c for c in changes if not c["ok"]]
    if bad:
        for c in bad:
            print("  !! 无法改写（%s）: %s" % (c["reason"], c["old"]), file=sys.stderr)
        raise SystemExit("补丁失败：有字面量放不下，未写出任何文件")

    out = report.get("out")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(bytes(raw))

    report.setdefault("files", []).append({
        "in": os.path.abspath(path),
        "out": os.path.abspath(out),
        "base": base,
        "n_changed": len([c for c in changes if c["ok"]]),
        "changes": changes,
    })
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", action="append", required=True, help="输入 .so（可重复）")
    ap.add_argument("--out", action="append", required=True, help="输出 .so（与 --so 顺序一一对应）")
    ap.add_argument("--base", required=True, help="host[:port]，例如 192.168.1.100:8000")
    ap.add_argument("--report", help="把改写明细写成 json")
    args = ap.parse_args()

    if len(args.so) != len(args.out):
        raise SystemExit("--so 与 --out 数量必须一致")

    report = {}
    for src, dst in zip(args.so, args.out):
        report["out"] = dst
        changes = patch_file(src, args.base, report)
        ok = [c for c in changes if c["ok"]]
        print("%s -> %s   改写 %d 处" % (os.path.basename(src), os.path.basename(dst), len(ok)))
        for c in ok:
            print("    @0x%08x  %s" % (c["va"], c["old"]))
            print("        -> %s" % c["new"])
        if not changes:
            print("    (没有匹配的域名)")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("明细: %s" % args.report)


if __name__ == "__main__":
    main()
