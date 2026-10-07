# -*- coding: utf-8 -*-
"""无界面入口：`tfpatch-aio.exe --cli --apk ... --out ...`。

GUI 与命令行共用同一个 pipeline，方便我写回归测试，也方便批量重打包。
"""

import argparse
import os
import sys

from . import cliutil, features, payload as payload_mod, pipeline, signer


def build_parser():
    ap = argparse.ArgumentParser(
        prog="tfpatch-aio",
        description="Trials Frontier 离线补丁器（AIO）：一个命令把原版 APK 变成"
                    "连本地私服的破解版，或直接出「装上就能玩」的自包含 APK。")
    ap.add_argument("--cli", action="store_true", help="强制走命令行（默认无界面时自动）")
    ap.add_argument("--apk", help="你自备的原版 APK")
    ap.add_argument("--out", help="输出 APK（默认 dist/TrialsFrontier-patched-<时间>.apk）")
    ap.add_argument("--server", default="192.168.1.100:8000",
                    help="私服地址 host:port（默认 192.168.1.100:8000）")
    ap.add_argument("--features", default=",".join(features.defaults()),
                    help="逗号分隔的功能开关；all = 全开，none = 只要核心。可用："
                         + ", ".join(f.key for f in features.FEATURES))
    ap.add_argument("--list-features", action="store_true", help="列出功能开关后退出")
    ap.add_argument("--payload", default="", help="自包含载荷目录或 zip（默认程序旁边自动找）")
    ap.add_argument("--work", default="", help="工作目录（默认系统临时目录下的 tfpatch-aio）")
    ap.add_argument("--keystore", default="", help="签名密钥（默认程序旁边的 keystore/trials.jks）")
    ap.add_argument("--alias", default="trials")
    ap.add_argument("--store-pass", default="trialsfrontier")
    ap.add_argument("--build-tools", default="", help="Android build-tools 目录")
    ap.add_argument("--force", action="store_true",
                    help="忽略原版 .so 的 size/SHA256 校验（每处补丁仍逐字节比对）")
    ap.add_argument("--keep-v7a", action="store_true", help="保留 armeabi-v7a（不推荐）")
    ap.add_argument("--skip-sign", action="store_true", help="只出未签名 APK")
    ap.add_argument("--check", action="store_true", help="只做环境自检")
    return ap


def parse_features(spec):
    spec = (spec or "").strip()
    if spec in ("all", "*"):
        return [f.key for f in features.FEATURES]
    if spec in ("none", ""):
        return features.defaults()
    known = set(features.BY_KEY)
    out = []
    for tok in spec.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok not in known:
            raise SystemExit("不认识的功能开关：%s（可用：%s）"
                             % (tok, ", ".join(sorted(known))))
        out.append(tok)
    return out


def environment(cfg=None):
    """把「本机能不能干活」查清楚，GUI 和 CLI 都用这一份。"""
    cfg = cfg or {}
    info = {}
    info["build_tools"] = cliutil.find_build_tools(cfg.get("build_tools") or None)
    info["java"] = cliutil.find_java()
    info["keytool"] = cliutil.find_keytool()
    info["keystore"] = cfg.get("keystore") or signer.default_keystore()
    info["has_keystore"] = os.path.isfile(info["keystore"])
    hint = cfg.get("payload") or payload_mod.default_hint()
    root = payload_mod.find_root(hint) if hint else None
    info["payload_hint"] = hint or ""
    info["payload_root"] = root or ""
    return info


def print_environment(log=print, cfg=None):
    info = environment(cfg)
    log("环境自检")
    log("  程序目录      %s%s" % (cliutil.app_dir(),
                                 "（打包后的 exe）" if cliutil.FROZEN else "（源码态）"))
    log("  随包 dex      %s" % cliutil.asset("payload_setup.dex"))
    log("  build-tools   %s" % (info["build_tools"] or "没找到（zipalign/apksigner 不可用）"))
    log("  java          %s" % (info["java"] or "没找到（apksigner 跑不起来）"))
    log("  keytool       %s" % (info["keytool"] or "没找到（不能自动生成密钥）"))
    log("  签名密钥      %s%s" % (info["keystore"],
                                 "" if info["has_keystore"] else "（下次运行时自动生成）"))
    log("  离线载荷      %s" % (info["payload_root"] or "没找到（只在勾自包含时用得上）"))
    return info


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_features:
        for f in features.FEATURES:
            print("%-8s %-28s %s%s" % (
                f.key, f.label,
                "★必选 " if f.required else ("默认开 " if f.default else ""),
                f.hint))
        return 0

    if args.check:
        print_environment()
        return 0

    if not args.apk:
        build_parser().error("缺少 --apk（或者不带 --cli 直接运行以打开图形界面）")

    o = pipeline.Options(
        apk_in=args.apk, apk_out=args.out or pipeline.default_out(args.apk),
        server=args.server, selected=parse_features(args.features),
        payload=args.payload, work=args.work, keystore=args.keystore,
        alias=args.alias, store_pass=args.store_pass,
        build_tools=args.build_tools, force=args.force, keep_v7a=args.keep_v7a,
        skip_sign=args.skip_sign,
        # ★ 必须写 sys.__stdout__：run_cli 期间 sys.stdout 是 _LineSink，
        # 用 print(...) 会把日志再喂回 sink，直接递归爆栈。
        log=lambda s: print(s, file=sys.__stdout__, flush=True))
    try:
        pipeline.run(o)
    except cliutil.ToolError as exc:
        print("\n[X] %s" % exc, file=sys.stderr)
        return 1
    return 0
