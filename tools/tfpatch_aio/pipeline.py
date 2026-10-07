# -*- coding: utf-8 -*-
"""把原版 APK 变成「本地私服 + 自选破解」APK 的完整流水线。

对应老的 7 步（tools/tfpatcher.py + tools/make_selfcontained.ps1），但
* 全部在进程内跑，不 spawn python；
* 每一步按 GUI 的勾选选择是否执行；native 补丁按 id 取子集；
* 自包含载荷从 exe 旁边的 payload/ 或 payload.zip 里取。
"""

import json
import os
import shutil
import tempfile
import time
import zipfile

from . import cliutil, features, payload as payload_mod, signer
from .cliutil import ToolError
from .vendored import axml, dex as dexmod, dynaddr, native, urls, zipbuild

ABI_DIR = "lib/arm64-v8a"
V7A_DIR = "lib/armeabi-v7a"
NEWAPP = "com.ubisoft.redlynx.trialsgo.OfflinePayloadSetup"
OLDAPP = "com.ubisoft.redlynx.trialsgo.DexApplicationClass"


class Options(object):
    def __init__(self, **kw):
        self.apk_in = kw.get("apk_in") or ""
        self.apk_out = kw.get("apk_out") or ""
        self.server = kw.get("server") or "192.168.1.100:8000"
        self.selected = list(kw.get("selected") or features.defaults())
        self.payload = kw.get("payload") or ""
        self.work = kw.get("work") or ""
        self.keystore = kw.get("keystore") or ""
        self.alias = kw.get("alias") or "trials"
        self.store_pass = kw.get("store_pass") or "trialsfrontier"
        self.build_tools = kw.get("build_tools") or ""
        self.force = bool(kw.get("force"))
        self.keep_v7a = bool(kw.get("keep_v7a"))
        self.skip_sign = bool(kw.get("skip_sign"))
        self.log = kw.get("log") or (lambda s: None)


def default_out(apk_in=""):
    d = cliutil.app_dir()
    out = os.path.join(d, "dist")
    try:
        os.makedirs(out, exist_ok=True)
    except OSError:
        out = d
    return os.path.join(out, "TrialsFrontier-patched-%s.apk"
                        % time.strftime("%Y%m%d-%H%M"))


def default_work():
    return os.path.join(tempfile.gettempdir(), "tfpatch-aio")


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract(apk, inner, dest):
    with zipfile.ZipFile(apk) as z:
        try:
            data = z.read(inner)
        except KeyError:
            return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def _app_class(man_path):
    """读 <application android:name="..."> 的字符串值（读不到返回 ""）。"""
    try:
        data = open(man_path, "rb").read()
        s, _resmap, els = axml.parse_chunks(data)
        strs = s["strings"]

        def txt(i):
            return strs[i] if 0 <= i < len(strs) else ""

        for e in els:
            if txt(e["name"]) != "application":
                continue
            for a in e["attrs"]:
                if txt(a["name"]) == "name" and a["dtype"] == 0x03:
                    return txt(a["data"])
            return ""
    except Exception:  # 清单坏了/格式意外：交给后面的 setstr 去报错
        return None
    return ""


def run(o):
    log = o.log
    keys, patches, actions, labels = features.resolve(o.selected)
    if not o.apk_in or not os.path.isfile(o.apk_in):
        raise ToolError("找不到输入 APK：%s" % (o.apk_in or "(空)"))
    if not o.apk_out:
        o.apk_out = default_out(o.apk_in)
    if not o.work:
        o.work = default_work()
    work = os.path.abspath(o.work)
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(o.apk_out)) or ".", exist_ok=True)

    log("输入 APK ：%s (%.1f MB)"
        % (o.apk_in, os.path.getsize(o.apk_in) / 1048576.0))
    log("输出 APK ：%s" % o.apk_out)
    log("服务器   ：%s" % o.server)
    log("工作目录 ：%s" % work)
    log("启用的功能：")
    for lab in labels:
        log("   + %s" % lab)
    report = {"apk_in": o.apk_in, "apk_out": o.apk_out, "server": o.server,
              "features": keys, "patches": patches, "steps": []}

    # ---------------------------------------------------------- 1 抽库
    log("\n[1/8] 校验原版 APK 并抽出 native 库")
    with zipfile.ZipFile(o.apk_in) as z:
        names = set(z.namelist())
    if "AndroidManifest.xml" not in names or (ABI_DIR + "/libTrialsGo.so") not in names:
        raise ToolError("这不像是 Trials Frontier 的 APK"
                        "（缺 AndroidManifest.xml 或 %s/libTrialsGo.so）" % ABI_DIR)
    libs = {}
    for fn in ("libTrialsGo.so", "libubiservices.so", "libplayground.so"):
        inner = "%s/%s" % (ABI_DIR, fn)
        if inner not in names:
            raise ToolError("APK 里没有 %s" % inner)
        p = _extract(o.apk_in, inner, os.path.join(work, "orig", fn))
        libs[fn] = p
        log("    %-20s %10d 字节  sha256 %s"
            % (fn, os.path.getsize(p), _sha256(p)[:16]))
    man_in = _extract(o.apk_in, "AndroidManifest.xml",
                      os.path.join(work, "AndroidManifest.orig.xml"))
    dex_names = sorted([n for n in names
                        if n.startswith("classes") and n.endswith(".dex")],
                       key=lambda n: (len(n), n))
    log("    清单 %d 字节；%d 个 dex：%s"
        % (os.path.getsize(man_in), len(dex_names), ", ".join(dex_names) or "无"))

    # ------------------------------------------------------- 2 native
    log("\n[2/8] libTrialsGo.so 定点补丁（%d 处）" % len(patches))
    ltg1 = os.path.join(work, "libTrialsGo.1.so")
    sha_ltg = _sha256(libs["libTrialsGo.so"])
    force = o.force
    if not force and sha_ltg != getattr(native, "EXPECTED_SHA256", ""):
        force = True
        log("    原版 libTrialsGo.so 的 sha256 与基准不同（民间重打包版？），"
            "自动放行整库校验；每处补丁仍逐字节比对。")
    argv = ["--so", libs["libTrialsGo.so"], "--out", ltg1,
            "--only", ",".join(patches),
            "--report", os.path.join(work, "native-report.json")]
    if force:
        argv.append("--force")
    r = cliutil.run_cli(native, argv, log)
    if r.rc != 0:
        raise ToolError("native 补丁失败（退出码 %s）：原版字节对不上，"
                        "多半是 APK 版本不对。确认无误可勾「忽略版本校验」。" % r.rc)
    report["steps"].append({"step": "native", "patches": patches})

    # ------------------------------------------------- 3 服务器地址 / URL
    # 这几个脚本「没有可改的地方」时**不写输出文件**（实测 libubiservices.so 在所有
    # 字面量都改过之后就一个都不匹配），所以每个产物都要回退到上一版，否则后面
    # build_apk 会因为找不到替换文件而退出码 2。
    def _keep(dst, src, what):
        if os.path.isfile(dst):
            return dst
        log("    %s 没有可改写的地方，沿用原库" % what)
        return src

    def _fresh(p):
        """跑之前先删：否则上一轮的旧产物会让 _keep 误判成「这轮成功写的」。"""
        if os.path.exists(p):
            os.remove(p)
        return p

    if features.ACT_DYN_ADDR in actions:
        log("\n[3/8] 注入服务器地址钩子（运行期读 tf_server.txt）")
        ltg2 = _fresh(os.path.join(work, "libTrialsGo.2.so"))
        r = cliutil.run_cli(dynaddr, ["--so", ltg1, "--out", ltg2,
                                      "--base", o.server], log)
        if r.rc != 0:
            raise ToolError("libTrialsGo.so 注入失败（退出码 %s）" % r.rc)
        ltg2 = _keep(ltg2, ltg1, "libTrialsGo.so")
        ubis = _fresh(os.path.join(work, "libubiservices.2.so"))
        r = cliutil.run_cli(dynaddr, ["--so", libs["libubiservices.so"],
                                      "--out", ubis, "--base", o.server], log)
        if r.rc != 0:
            raise ToolError("libubiservices.so 注入失败（退出码 %s）" % r.rc)
        ubis = _keep(ubis, libs["libubiservices.so"], "libubiservices.so")
    else:
        ltg2, ubis = ltg1, libs["libubiservices.so"]

    if features.ACT_URLS in actions:
        log("    libplayground.so 静态改写（该库空间已满，无法注入）")
        pg = _fresh(os.path.join(work, "libplayground.2.so"))
        r = cliutil.run_cli(urls, ["--so", libs["libplayground.so"],
                                   "--out", pg, "--base", o.server], log)
        if r.rc != 0:
            raise ToolError("libplayground.so 改写失败（退出码 %s）" % r.rc)
        pg = _keep(pg, libs["libplayground.so"], "libplayground.so")
    else:
        pg = libs["libplayground.so"]

    # -------------------------------------------------------- 4 清单
    log("\n[4/8] 改写 AndroidManifest.xml")
    man_cur = os.path.join(work, "AndroidManifest.xml")
    man_argv = []
    if features.ACT_SET_APPCLASS in actions:
        cur = _app_class(man_in)
        log("    当前 Application 类：%s" % (cur or "（无）"))
        if cur is not None and cur != OLDAPP:
            # 实测：民间「车不全」整合版是 SecShell 加固的，Application 是
            # com.SecShell.SecShell.AW（25 字符），塞不下 48 字符的新类名；
            # 就算塞得下也没用 —— 我们的载荷类是 extends DexApplicationClass 的。
            why = ("槽位太短（%d < %d）" % (len(cur), len(NEWAPP))
                   if len(cur) < len(NEWAPP) else "不是基准类名")
            raise ToolError(
                "自包含打包换不了 Application 类：这个 APK 的是 %r，%s。\n"
                "    加固/整合版把启动类藏在壳里，改不动。请换**未加固的原版**做 base\n"
                "    （本仓库现成的：dist\\TrialsFrontier-offline.apk 或 tmp\\build\\tf-m16.apk），\n"
                "    或者取消勾选「自包含离线载荷」只出补丁版 APK（其它功能不受影响）。"
                % (cur, why))
        man_argv.append(("setstr", [man_in, man_cur, "%s=%s" % (OLDAPP, NEWAPP)]))
        man_argv.append(("set", [man_cur, man_cur, "minSdkVersion=21"]))
        src = man_cur
    else:
        src = man_in
    if features.ACT_MANIFEST_TARGETSDK in actions:
        man_argv.append(("set", [src, man_cur, "targetSdkVersion=27"]))
        src = man_cur
    if not man_argv:
        shutil.copyfile(man_in, man_cur)
    else:
        for cmd, a in man_argv:
            r = cliutil.run_cli(axml, [cmd] + a, log)
            if r.rc != 0:
                raise ToolError("清单改写 %s 失败（退出码 %s）" % (cmd, r.rc))
    man_out = man_cur if man_argv else man_in

    # --------------------------------------------------------- 5 dex
    dex_out = {}
    if features.ACT_DEX in actions:
        log("\n[5/8] 改写 classes*.dex（Java 侧广告 / 遥测）")
        hit = 0
        n_methods = 0
        with zipfile.ZipFile(o.apk_in) as z:
            for name in dex_names:
                blob = z.read(name)
                patched, info = dexmod.patch_dex_bytes(blob)
                n = sum(1 for m in info.get("methods", [])
                        if m.get("status") == "patched")
                n_methods += n
                log("    %-14s 补 %d 个方法" % (name, n))
                if patched != blob:
                    p = os.path.join(work, "dex", name)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "wb") as f:
                        f.write(patched)
                    dex_out[name] = p
                    hit += 1
        log("    共改动 %d 个 dex" % hit)
        if n_methods == 0:
            # 实测：民间的「车不全」整合版把真正的游戏 dex 放在 OBB/外置数据里，
            # APK 里只剩一个 574 KB 的加载器 dex —— 这时去广告/去遥测就是空转。
            log("    [WARN] APK 里一个 dex 目标都没找到：广告 / 遥测可能不在这几个 dex 里"
                "（民间整合版常把游戏 dex 放进 OBB 或外置数据包）。"
                "其它功能不受影响。")
        report["steps"].append({"step": "dex", "changed": sorted(dex_out),
                                "methods": n_methods})

    # ------------------------------------------------------ 6 自包含载荷
    replace = [(ABI_DIR + "/libTrialsGo.so", ltg2),
               (ABI_DIR + "/libubiservices.so", ubis),
               (ABI_DIR + "/libplayground.so", pg),
               ("AndroidManifest.xml", man_out)]
    for name, p in dex_out.items():
        replace.append((name, p))
    add = []
    if features.ACT_BUNDLE in actions:
        log("\n[6/8] 塞入自包含离线载荷")
        hint = o.payload or payload_mod.default_hint()
        root = payload_mod.find_root(hint)
        if not root:
            raise ToolError("勾了「自包含完整 APK」但找不到载荷。\n"
                            "请把 payload/（里面是 appdata/ 和 obb/）或 payload.zip "
                            "放在程序旁边，或在界面上指定路径。")
        entries = payload_mod.collect(root, o.server, work, log)
        man = payload_mod.write_manifest(entries, os.path.join(
            work, "assets", "tf", "payload.txt"))
        # classes4.dex：预先编好的 OfflinePayloadSetup，避免运行时依赖 javac/d8
        used = set(dex_names)
        n = 4
        while ("classes%d.dex" % n) in used:
            n += 1
        dexname = "classes%d.dex" % n
        setup = cliutil.asset("payload_setup.dex")
        if not os.path.isfile(setup):
            raise ToolError("随包资源丢了：%s" % setup)
        log("    %s <- %s (%d 字节)"
            % (dexname, os.path.basename(setup), os.path.getsize(setup)))
        add.append((dexname, setup))
        by_key = {(k, r): l for (k, r, l) in entries}
        for (kind, rel, asset) in man:
            add.append(("assets/tf/%s" % asset, by_key[(kind, rel)]))
        add.append(("assets/tf/payload.txt",
                    os.path.join(work, "assets", "tf", "payload.txt")))
        report["steps"].append({"step": "bundle", "entries": len(man),
                                "dex": dexname})
    else:
        log("\n[6/8] 跳过自包含载荷（只出补丁版 APK）")

    # ------------------------------------------------------- 7 重打包
    log("\n[7/8] 重写 zip（逐条目搬运，丢弃旧签名）")
    unsigned = os.path.join(work, "unsigned.apk")
    argv = ["--base", o.apk_in, "--out", unsigned]
    for inner, local in replace:
        argv += ["--replace", "%s=%s" % (inner, local)]
    for inner, local in add:
        argv += ["--add", "%s=%s" % (inner, local)]
    if not o.keep_v7a:
        argv += ["--drop-prefix", V7A_DIR + "/"]
    r = cliutil.run_cli(zipbuild, argv, log)
    if r.rc != 0:
        raise ToolError("重写 zip 失败（退出码 %s）" % r.rc)

    # ------------------------------------------------------- 8 对齐 + 签名
    log("\n[8/8] zipalign + 签名")
    bt = cliutil.find_build_tools(o.build_tools or None)
    if not bt:
        log("!! 没找到 Android build-tools（zipalign/apksigner）。")
        log("   装上 Android SDK 后重跑，或在界面上指定 build-tools 目录。")
    out_abs = os.path.abspath(o.apk_out)
    if not bt or o.skip_sign:
        shutil.copyfile(unsigned, out_abs)
        log("未签名产物：%s (%.1f MB)"
            % (out_abs, os.path.getsize(out_abs) / 1048576.0))
        log("未签名的 APK 装不上（系统会直接拒绝）。")
        report["signed"] = False
        return report

    aligned = signer.align(bt, unsigned, os.path.join(work, "aligned.apk"), log)
    ks = o.keystore or signer.default_keystore()
    try:
        signer.ensure_keystore(ks, o.alias, o.store_pass, log)
    except ToolError as exc:
        log("!! %s" % exc)
        shutil.copyfile(aligned, out_abs)
        report["signed"] = False
        return report
    signer.sign(bt, aligned, out_abs, ks, o.alias, o.store_pass, log)
    rc, _ = signer.verify(bt, out_abs, log)
    sha = _sha256(out_abs)
    log("\n完成：%s" % out_abs)
    log("  %.1f MB  sha256 %s" % (os.path.getsize(out_abs) / 1048576.0, sha))
    if rc != 0:
        log("!! apksigner verify 没通过，包可能有问题")
    report.update({"signed": rc == 0, "sha256": sha,
                   "size": os.path.getsize(out_abs)})
    rp = out_abs + ".report.json"
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log("明细报告：%s" % rp)
    return report
