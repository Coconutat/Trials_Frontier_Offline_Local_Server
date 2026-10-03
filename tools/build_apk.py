#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从干净原版 APK 重新打包一个改好的 APK（只重写 zip，签名交给 apksigner）。

用法:
    python tools/build_apk.py --base 原版.apk --out 改好.apk \
        --replace lib/arm64-v8a/libTrialsGo.so=打过补丁的.so \
        --drop-prefix lib/armeabi-v7a/

设计原则:
  * 逐条目原样搬运，保留每一条自己的压缩方式与 external_attr；
  * 默认丢弃旧的 META-INF 签名文件（apksigner 会写新的）；
  * 不做任何"顺手优化"，改了什么就是什么。
"""
import argparse
import os
import sys
import zipfile

# 会被丢弃的旧签名文件后缀
SIG_SUFFIXES = (".SF", ".RSA", ".DSA", ".EC", ".MF")


def is_old_signature(name):
    if not name.upper().startswith("META-INF/"):
        return False
    if "/" in name[len("META-INF/"):]:
        return False
    return name.upper().endswith(SIG_SUFFIXES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="干净原版 APK")
    ap.add_argument("--out", required=True, help="输出 APK")
    ap.add_argument("--replace", action="append", default=[],
                    metavar="APK内路径=本地文件",
                    help="用本地文件替换包内某个条目（可重复）")
    ap.add_argument("--drop-prefix", action="append", default=[],
                    metavar="前缀",
                    help="丢弃该前缀下的所有条目（可重复）")
    ap.add_argument("--keep-old-signatures", action="store_true",
                    help="保留旧的 META-INF 签名文件（默认丢弃）")
    args = ap.parse_args()

    replacements = {}
    for spec in args.replace:
        if "=" not in spec:
            print("--replace 需要写成 包内路径=本地文件 的形式: %s" % spec)
            return 2
        inner, local = spec.split("=", 1)
        if not os.path.isfile(local):
            print("找不到替换用的文件: %s" % local)
            return 2
        replacements[inner] = local

    for p in args.drop_prefix:
        if p.startswith("/") or ".." in p:
            print("--drop-prefix 不接受绝对路径: %s" % p)
            return 2

    if os.path.exists(args.out):
        os.remove(args.out)

    replaced_names, dropped_names = set(), []
    with zipfile.ZipFile(args.base, "r") as zin:
        infos = zin.infolist()
        with zipfile.ZipFile(args.out, "w", allowZip64=True) as zout:
            for info in infos:
                name = info.filename

                if any(name.startswith(p) for p in args.drop_prefix):
                    dropped_names.append(name)
                    continue
                if not args.keep_old_signatures and is_old_signature(name):
                    dropped_names.append(name)
                    continue

                if name in replacements:
                    with open(replacements[name], "rb") as f:
                        payload = f.read()
                    replaced_names.add(name)
                else:
                    payload = zin.read(name)

                new = zipfile.ZipInfo(name, date_time=info.date_time)
                new.compress_type = info.compress_type
                new.external_attr = info.external_attr
                new.internal_attr = info.internal_attr
                new.create_system = info.create_system
                zout.writestr(new, payload)

    missing = set(replacements) - replaced_names
    if missing:
        print("这些要替换的条目在原包里不存在: %s" % ", ".join(sorted(missing)))
        return 2

    print("基础包 : %s (%d 字节)" % (args.base, os.path.getsize(args.base)))
    print("输出   : %s (%d 字节)" % (args.out, os.path.getsize(args.out)))
    for name in sorted(replaced_names):
        print("  替换 %-45s <- %s" % (name, replacements[name]))
    for name in dropped_names:
        print("  丢弃 %s" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
