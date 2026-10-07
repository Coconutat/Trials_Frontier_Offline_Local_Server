#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 Android dex 做"外科手术式"补丁：把指定方法体的第一条指令改成 `return-void`。

为什么不重新编译 smali：
    apktool b 会把整个 dex 重新编码（本工程实测 classes.dex 8872856 -> 8820212，
    classes2/3 也各变了几 KB），改动面覆盖全部 17835 个类。这里只改写目标方法
    code_item 里的 insns，dex 中其余字节一个不动，改完重算 header 的 Adler-32
    checksum 与 SHA-1 signature，风险面只有那两个方法。

用法：
    python tools/patch_dex.py --apk <原版.apk> --out <改后.apk>     # 直接在 APK 里替换 dex
    python tools/patch_dex.py --dex classes.dex --out classes-patched.dex
    python tools/patch_dex.py --dex classes.dex --report dex-report.json

纯标准库。
"""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

# (类描述符, 方法名, 说明)  —— 只要名字/描述符对得上就打，不校验原型
TARGETS = [
    ("Lcom/ubisoft/redlynx/trialsgo/CustomNativeActivity;",
     "initAdMobRewardedVideoAds",
     "不再初始化 Google Mobile Ads 激励视频（原实现会 getRewardedVideoAdInstance + setUserId + setRewardedVideoAdListener）"),
    ("Lcom/ubisoft/redlynx/trialsgo/CustomNativeActivity;",
     "tapjoyInit",
     "不再连接 Tapjoy 广告网络（原实现会 Tapjoy.connect + 建 TJPlacement）"),
    # 遥测：光把 onCreate 里的 Fabric.with(...) 换成 nop 会让 App 直接崩 ——
    # onCreate 后面还会调 Crashlytics.setString(...)，它内部走
    # checkInitialized() -> getInstance() -> Fabric.getKit() -> Fabric.singleton()，
    # Fabric 没初始化就抛 IllegalStateException("Must Initialize Fabric before using singleton()")。
    # 所以把 App 实际会调到的三个 Crashlytics 静态方法一并变成空方法。
    # （只有 CustomNativeActivity 与 Crashlytics 自己引用这个类，改动面极小。）
    ("Lcom/crashlytics/android/Crashlytics;", "log",
     "Crashlytics 崩溃/分析上报已停用，日志埋点变空操作"),
    ("Lcom/crashlytics/android/Crashlytics;", "logException",
     "Crashlytics 崩溃/分析上报已停用，异常埋点变空操作"),
    ("Lcom/crashlytics/android/Crashlytics;", "setString",
     "Crashlytics 崩溃/分析上报已停用，自定义键值埋点变空操作"),
]

RETURN_VOID = 0x000E          # dex opcode 0x0e = return-void
NO_INDEX = 0xFFFFFFFF

# 只把「方法体里唯一的那条 invoke 指令」换成 nop 的目标。
# 用在 onCreate 这种大方法里：里面混着 UI 初始化等一堆正常逻辑，不能整条方法砍掉，
# 但有一条 invoke-static Fabric.with(...) 会把 Crashlytics 遥测整个启动起来。
# 格式: (宿主类, 宿主方法, 被调类描述符, 被调方法名, 说明)
NOP_INVOKES = [
    ("Lcom/ubisoft/redlynx/trialsgo/CustomNativeActivity;", "onCreate",
     "Lio/fabric/sdk/android/Fabric;", "with",
     "不再调用 Fabric.with(...)，Crashlytics 崩溃上报与 Fabric/Answers 分析遥测都不会启动"
     "（只剩前面那条 new CrashlyticsNdk 的构造，Fabric 不启动就完全不联网）"),
]


def u2(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u4(b, o):
    return struct.unpack_from("<I", b, o)[0]


def read_uleb128(b, o):
    result = 0
    shift = 0
    while True:
        byte = b[o]
        o += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, o


def read_mutf8(b, o):
    """string_data_item: uleb128 utf16_len，随后 MUTF-8 字节，以 0 结尾。"""
    _, o = read_uleb128(b, o)
    end = b.index(b"\x00", o)
    return b[o:end].decode("utf-8", "replace"), end + 1


class Dex:
    def __init__(self, blob):
        if blob[:4] != b"dex\n":
            raise ValueError("不是 dex 文件（magic=%r）" % blob[:8])
        self.b = bytearray(blob)
        b = self.b
        self.file_size = u4(b, 0x20)
        if self.file_size != len(b):
            raise ValueError("dex 头部 file_size=%d 与实际 %d 不符" % (self.file_size, len(b)))
        self.string_ids_size = u4(b, 0x38)
        self.string_ids_off = u4(b, 0x3C)
        self.type_ids_size = u4(b, 0x40)
        self.type_ids_off = u4(b, 0x44)
        self.method_ids_size = u4(b, 0x58)
        self.method_ids_off = u4(b, 0x5C)
        self.class_defs_size = u4(b, 0x60)
        self.class_defs_off = u4(b, 0x64)

    def string(self, idx):
        return read_mutf8(self.b, u4(self.b, self.string_ids_off + 4 * idx))[0]

    def type_descriptor(self, idx):
        if idx == NO_INDEX:
            return None
        return self.string(u4(self.b, self.type_ids_off + 4 * idx))

    def method(self, idx):
        o = self.method_ids_off + 8 * idx
        class_idx, proto_idx, name_idx = struct.unpack_from("<HHI", self.b, o)
        return (self.type_descriptor(class_idx), proto_idx, self.string(name_idx))

    def class_data(self, class_idx):
        """返回 (direct_methods, virtual_methods)，元素为 (method_idx, access_flags, code_off)。"""
        o = self.class_defs_off + 32 * class_idx
        class_data_off = u4(self.b, o + 24)
        if class_data_off == 0:
            return [], []
        p = class_data_off
        static_fields, p = read_uleb128(self.b, p)
        instance_fields, p = read_uleb128(self.b, p)
        direct_count, p = read_uleb128(self.b, p)
        virtual_count, p = read_uleb128(self.b, p)

        def fields(count, p):
            idx = 0
            for _ in range(count):
                diff, p = read_uleb128(self.b, p)
                _, p = read_uleb128(self.b, p)
                idx += diff
            return p

        def methods(count, p):
            out = []
            idx = 0
            for _ in range(count):
                diff, p = read_uleb128(self.b, p)
                access, p = read_uleb128(self.b, p)
                code_off, p = read_uleb128(self.b, p)
                idx += diff
                out.append((idx, access, code_off))
            return out, p

        p = fields(static_fields, p)
        p = fields(instance_fields, p)
        direct, p = methods(direct_count, p)
        virtual, p = methods(virtual_count, p)
        return direct, virtual

    def classes(self):
        out = []
        for i in range(self.class_defs_size):
            out.append((i, self.type_descriptor(u4(self.b, self.class_defs_off + 32 * i))))
        return out

    def find_method_ids(self, cls_desc, name):
        """按 class 描述符 + 方法名找出所有匹配的 method_id 下标。"""
        out = []
        for i in range(self.method_ids_size):
            c, _, n = self.method(i)
            if c == cls_desc and n == name:
                out.append(i)
        return out

    def method_code_off(self, cls_desc, meth_name):
        """返回类里某个方法的 code_off；找不到返回 (None, status)。"""
        class_idx = None
        for i in range(self.class_defs_size):
            if self.type_descriptor(u4(self.b, self.class_defs_off + 32 * i)) == cls_desc:
                class_idx = i
                break
        if class_idx is None:
            return None, "class-not-found"
        direct, virtual = self.class_data(class_idx)
        for method_idx, _access, code_off in direct + virtual:
            c, _proto, name = self.method(method_idx)
            if c == cls_desc and name == meth_name:
                return code_off, "ok"
        return None, "method-not-found"

    def nop_invoke(self, code_off, callee_ids, what):
        """把方法体里**唯一**一条指向 callee_ids 中任一下标的 invoke 指令整条换成 nop。

        callee_ids 是集合：同一个「类->方法名」在 method_ids 里可能有多条（原型不同），
        例如 `Fabric->with(Fabric)` 与 `Fabric->with(Context, Kit...)` 各占一条。
        命中数不是 1 就拒绝改写（宁可不改，也不要误伤别的调用）。
        invoke-*/invoke-*/range 都是 3 个 code unit、方法下标在第二个 unit 的低 16 位。
        """
        if code_off == 0:
            raise ValueError("%s 没有 code_item" % what)
        insns_size = u4(self.b, code_off + 12)
        begin = code_off + 16
        hits = []
        for k in range(max(0, insns_size - 1)):
            op = u2(self.b, begin + 2 * k) & 0xFF
            if not (0x6E <= op <= 0x72 or 0x74 <= op <= 0x78):
                continue
            if u2(self.b, begin + 2 * (k + 1)) in callee_ids:
                hits.append(k)
        if len(hits) != 1:
            raise ValueError("%s 里匹配到 %d 条目标 invoke，需要正好 1 条，拒绝改写"
                             % (what, len(hits)))
        k = hits[0]
        old = bytes(self.b[begin + 2 * k: begin + 2 * k + 6])
        self.b[begin + 2 * k: begin + 2 * k + 6] = b"\x00" * 6
        return k, old

    def force_return_void(self, code_off, what):
        """把方法体变成 `return-void` + 全 nop，但 **不动 insns_size**。

        踩过的坑：一开始是把 insns_size 缩到 1（只留那条 return-void），结果 ART
        直接拒绝整份 classes.dex（应用启动即 ClassNotFoundException，DexPathList
        里一个类都找不到）。实机二分证明：只要改动 insns_size 就必挂，保持
        insns_size 不变、把第一条指令写成 return-void 并把其余 code unit 全部
        填成 nop(0x0000) 就完全正常。填满 nop 而不是只覆盖原第一条指令的宽度，
        是为了不依赖"这条指令占几个 code unit"的格式表，任何 opcode 都不会被
        截成半条。
        """
        if code_off == 0:
            raise ValueError("%s 没有 code_item（abstract/native？）" % what)
        tries_size = u2(self.b, code_off + 6)
        insns_size = u4(self.b, code_off + 12)
        if tries_size:
            raise ValueError("%s 带 try/catch（tries_size=%d），本工具拒绝改写以免破坏 try 表"
                             % (what, tries_size))
        if insns_size < 1:
            raise ValueError("%s 的 insns_size=%d，异常" % (what, insns_size))
        begin = code_off + 16
        end = begin + 2 * insns_size
        old_insns = bytes(self.b[begin:end])
        struct.pack_into("<H", self.b, begin, RETURN_VOID)
        if insns_size > 1:
            self.b[begin + 2:end] = b"\x00" * (2 * (insns_size - 1))   # nop 填满
        return old_insns

    def rehash(self):
        """重算 header 的 SHA-1 signature（0x20 起）与 Adler-32 checksum（0x0C 起）。"""
        body = bytes(self.b)
        sig = hashlib.sha1(body[32:]).digest()
        self.b[12:32] = sig
        chk = zlib.adler32(bytes(self.b[12:])) & 0xFFFFFFFF
        struct.pack_into("<I", self.b, 8, chk)
        return chk, sig.hex()

    def verify(self):
        body = bytes(self.b)
        if hashlib.sha1(body[32:]).digest() != body[12:32]:
            raise ValueError("SHA-1 signature 自校验失败")
        if (zlib.adler32(body[12:]) & 0xFFFFFFFF) != u4(self.b, 8):
            raise ValueError("Adler-32 checksum 自校验失败")


def patch_dex_bytes(blob):
    dex = Dex(blob)
    by_name = {}
    for class_idx, desc in dex.classes():
        if desc in by_name:
            continue
        by_name.setdefault(desc, class_idx)

    done = []
    for desc, meth_name, why in TARGETS:
        class_idx = by_name.get(desc)
        if class_idx is None:
            done.append({"class": desc, "method": meth_name, "status": "class-not-found"})
            continue
        direct, virtual = dex.class_data(class_idx)
        hit = None
        for method_idx, access, code_off in direct + virtual:
            c, proto_idx, name = dex.method(method_idx)
            if c == desc and name == meth_name:
                hit = (method_idx, access, code_off)
                break
        if hit is None:
            done.append({"class": desc, "method": meth_name, "status": "method-not-found"})
            continue
        method_idx, access, code_off = hit
        try:
            old = dex.force_return_void(code_off, "%s->%s" % (desc, meth_name))
        except ValueError as exc:
            done.append({"class": desc, "method": meth_name, "status": "skipped: %s" % exc})
            continue
        done.append({
            "class": desc,
            "method": meth_name,
            "status": "patched",
            "code_off": code_off,
            "old_insns_size": len(old) // 2,
            "old_insns_hex": old[:16].hex(" "),
            "why": why,
        })
    for cls_desc, meth_name, callee_desc, callee_name, why in NOP_INVOKES:
        callee = "%s->%s" % (callee_desc, callee_name)
        code_off, status = dex.method_code_off(cls_desc, meth_name)
        if code_off is None:
            done.append({"class": cls_desc, "method": meth_name, "callee": callee,
                         "status": status})
            continue
        ids = dex.find_method_ids(callee_desc, callee_name)
        if not ids:
            done.append({"class": cls_desc, "method": meth_name, "callee": callee,
                         "status": "callee-not-found"})
            continue
        what = "%s->%s" % (cls_desc, meth_name)
        k, old = dex.nop_invoke(code_off, set(ids), what)
        done.append({
            "class": cls_desc,
            "method": meth_name,
            "callee": callee,
            "status": "patched",
            "code_off": code_off,
            "insn_index": k,
            "old_insns_hex": old.hex(" "),
            "why": why,
        })
    chk, sig = dex.rehash()
    dex.verify()
    return bytes(dex.b), {"checksum": "0x%08x" % chk, "signature_sha1": sig, "methods": done}


def patch_apk(apk_in, apk_out, report_path=None, keep_old_signatures=False):
    if not os.path.exists(apk_in):
        sys.exit("[X] 找不到 %s" % apk_in)
    tmp = tempfile.mkdtemp(prefix="tfdex-")
    replacements = []
    report = {"apk_in": apk_in, "apk_out": apk_out, "dex": []}
    try:
        with zipfile.ZipFile(apk_in) as z:
            names = [n for n in z.namelist() if n.startswith("classes") and n.endswith(".dex")]
            if not names:
                sys.exit("[X] %s 里没有 classes*.dex" % apk_in)
            names.sort(key=lambda n: (len(n), n))
            for name in names:
                blob = z.read(name)
                patched, info = patch_dex_bytes(blob)
                info["name"] = name
                info["size_before"] = len(blob)
                info["size_after"] = len(patched)
                info["changed"] = patched != blob
                report["dex"].append(info)
                if patched != blob:
                    local = os.path.join(tmp, os.path.basename(name))
                    with open(local, "wb") as fh:
                        fh.write(patched)
                    replacements.append("%s=%s" % (name, local))
        outdir = os.path.dirname(os.path.abspath(apk_out))
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        cmd = [sys.executable, os.path.join(HERE, "build_apk.py"),
               "--base", apk_in, "--out", apk_out]
        if keep_old_signatures:
            cmd.append("--keep-old-signatures")
        for r in replacements:
            cmd += ["--replace", r]
        print("  -> %s" % " ".join(os.path.basename(c) if c.startswith(HERE) else c for c in cmd))
        subprocess.run(cmd, check=True)
        if report_path:
            rdir = os.path.dirname(os.path.abspath(report_path))
            if rdir:
                os.makedirs(rdir, exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            print("  -> 报告已写入 %s" % report_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def main():
    ap = argparse.ArgumentParser(description="dex 方法体外科手术：把目标方法改成 return-void")
    ap.add_argument("--apk", help="输入 APK（会替换其中的 classes*.dex）")
    ap.add_argument("--out", help="输出 APK / dex")
    ap.add_argument("--dex", action="append", default=[], help="单个 dex 输入（可重复）")
    ap.add_argument("--report", help="写 JSON 报告")
    ap.add_argument("--keep-old-signatures", action="store_true")
    args = ap.parse_args()

    if args.apk:
        if not args.out:
            sys.exit("[X] --apk 需要配 --out")
        print("[dex] %s" % args.apk)
        rep = patch_apk(args.apk, args.out, args.report, args.keep_old_signatures)
        for d in rep["dex"]:
            mark = "改" if d["changed"] else "未变"
            print("  %-16s %8d -> %8d  %s" % (d["name"], d["size_before"], d["size_after"], mark))
            for m in d["methods"]:
                print("      %-34s %s" % (m["method"], m["status"]))
        return

    if not args.dex:
        sys.exit("[X] 需要 --apk 或 --dex")
    out = args.out or args.dex[0]
    blob = open(args.dex[0], "rb").read()
    patched, info = patch_dex_bytes(blob)
    with open(out, "wb") as fh:
        fh.write(patched)
    print("[dex] %s -> %s   %d -> %d 字节  checksum=%s"
          % (args.dex[0], out, len(blob), len(patched), info["checksum"]))
    for m in info["methods"]:
        print("      %-34s %s" % (m["method"], m["status"]))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(info, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
