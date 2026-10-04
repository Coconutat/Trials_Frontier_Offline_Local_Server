#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trials Frontier（特技摩托前线）离线化 patcher。

把用户自备的**原版** APK 变成可离线游玩的改好版本。全程只做定点字节修改，
不重编译 smali、不重新编码 dex。

依赖：Python 3.8+ 标准库、`pyelftools`（patch_urls.py 解析 ELF 节表时用）、
以及 Android SDK 的 zipalign / apksigner（没有 SDK 时可用 --no-sign 出未签名包）。

用法:
    python tools/tfpatcher.py --apk 原版.apk --out 改好.apk

常用可选参数:
    --host 192.168.1.100:8000 写进 .so 的"编译期默认服务器地址"
                              （运行期仍以 tf_server.txt 为准，见 README）
    --no-sign                 只产出未签名 APK（没有 Android SDK 时用）
    --build-tools <dir>       指定 Android build-tools 目录
    --keystore/--alias/--store-pass
                              指定签名密钥（默认自动生成一个自用密钥）
    --keep-v7a                保留 armeabi-v7a 的库（不推荐，见下）
    --force                   跳过原版 .so 的 SHA256 校验

做了什么（逐条依据见 tools/README.md 与 work/trials-frontier/notes/）:
  1. libTrialsGo.so 上 17 处定点字节补丁（每处都校验原始字节，对不上就退出）：
       AntiCheating::isValid()            -> 恒 true（关掉反作弊时钟校验）
       ConsumableManager::isUnlimitedFuel -> 恒 true（无限燃油）
       OfferData::isBlackListed           -> 恒 false（不拉黑任何 offer）
       PlayerItems::remove                -> sub 改 add（花货币道具不减反增）
       DLContentManager::isDLReady()      -> 恒 true（内容包视为就绪）
       MenuzStateMain::isUserBlackListed()-> 恒 false（不弹"警报！"）
       AdInterface::initAndroid()         -> 提前返回（原生广告永不初始化）
       —— 真钱内购（2 处）——
       StoreManager::onPurchaseFailed     -> 尾调用 onPurchaseComplete（失败直接发奖）
       StoreManager::onPurchaseCancel     -> 尾调用 onPurchaseComplete（取消直接发奖）
       —— VIP / 骑士俱乐部（8 处，其中 3 处写进代码洞）——
       VIPManager::getPlayerMembership()+0x78/+0x7C/+0x80/+0xF4/+0xF8
                                          -> 插 NULL 保护：修掉开屏闪退，同时保留真实 VIP 上报
       OfferManager::findVIPOffers        -> IAP 查询跳进代码洞，返回伪造 IAPItemInfo
                                            （离线也能出现 VIP 档位 → 触发服务器下发 VIP）
  1b. classes.dex 里 6 处改写（Java 侧广告 + 遥测）：
       CustomNativeActivity.initAdMobRewardedVideoAds -> return-void（不再初始化 Google Mobile Ads）
       CustomNativeActivity.tapjoyInit               -> return-void（不再连接 Tapjoy 广告网络）
       Crashlytics.{log,logException,setString}      -> return-void（埋点变空操作）
       CustomNativeActivity.onCreate 里的 Fabric.with(...) -> nop
                                     （Fabric/Crashlytics 崩溃与分析遥测永不启动）
  2. 服务器地址：在所有 Ubisoft URL 字面量里插入 DT_INIT 钩子，库加载时读
     /sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt
     并就地改写 .rodata，把请求指向你自己的服务器（改文本文件即生效，不用重装）。
  3. AndroidManifest.xml: targetSdkVersion 30 -> 27，放开 Java 侧明文 HTTP。
  4. 丢弃旧的 META-INF 签名与 armeabi-v7a 库（保证 64 位设备一定用到改过的库）。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = "com.ubisoft.redlynx.trialsfrontier.ggp"
SERVER_FILE = ("/sdcard/Android/data/%s/files/tf_server.txt" % PKG)

# 原版库的期望指纹（7.9.4 / versionCode 561）
LIBS = {
    "libTrialsGo.so": (14901128,
                       "743f945cd7e3378dbf78eadc9d864de0c465b558bda8a54923b46a8f170fb7f4"),
    "libubiservices.so": (10665936, None),
    "libplayground.so": (2950640, None),
}
ABI_DIR = "lib/arm64-v8a"
V7A_DIR = "lib/armeabi-v7a"


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log("错误: " + msg)
    sys.exit(2)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, what):
    log(">>> " + what)
    log("    " + " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc != 0:
        fail("%s 失败 (exit %d)" % (what, rc))


def script(name):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        fail("找不到配套脚本 %s（请把 tools/ 整个目录一起带走）" % p)
    return p


def find_build_tools(explicit):
    cands = []
    if explicit:
        cands.append(explicit)
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK"):
        root = os.environ.get(env)
        if root:
            bt = os.path.join(root, "build-tools")
            if os.path.isdir(bt):
                for d in sorted(os.listdir(bt), reverse=True):
                    cands.append(os.path.join(bt, d))
    # 本项目开发机上的固定位置，作为最后的兜底
    cands.append(r"C:\Users\<user>\AppData\Local\Android\Sdk\build-tools\36.0.0")
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "zipalign.exe" if os.name == "nt"
                                            else "zipalign")):
            return c
    return None


def bt_exe(bt, name):
    for cand in (name + ".exe", name, name + ".bat"):
        p = os.path.join(bt, cand)
        if os.path.isfile(p):
            return p
    return None


def default_keystore():
    """按优先级找一个已存在的签名密钥；都没有就返回将要自动生成的位置。"""
    cands = [
        # 开发仓库里的位置
        os.path.join(os.path.dirname(HERE), "work", "trials-frontier",
                     "keystore", "trials.jks"),
        # 发布包 patcher/keystore/trials.jks
        os.path.join(HERE, "keystore", "trials.jks"),
    ]
    for p in cands:
        if os.path.isfile(p):
            return p
    return cands[-1]


def ensure_keystore(path, alias, store_pass):
    if os.path.isfile(path):
        return True
    keytool = shutil.which("keytool")
    if not keytool:
        return False
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    log(">>> 生成自用签名密钥 %s" % path)
    rc = subprocess.call([keytool, "-genkeypair", "-keystore", path,
                          "-alias", alias, "-keyalg", "RSA", "-keysize", "2048",
                          "-validity", "10000", "-storepass", store_pass,
                          "-keypass", store_pass,
                          "-dname", "CN=Trials Frontier Offline, OU=Local, O=Local, C=CN"])
    return rc == 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--apk", required=True, help="你自备的原版 APK")
    ap.add_argument("--out", required=True, help="输出的改好 APK")
    ap.add_argument("--host", default="127.0.0.1:8000",
                    help="写进 .so 的默认服务器地址 host[:port]")
    ap.add_argument("--work", default=None, help="中间文件目录（默认临时目录）")
    ap.add_argument("--build-tools", default=None)
    ap.add_argument("--keystore", default=None,
                    help="签名密钥（默认用自带的 patcher/keystore/trials.jks，"
                         "找不到就用 keytool 自动生成一个）")
    ap.add_argument("--alias", default="trials")
    ap.add_argument("--store-pass", default="trialsfrontier")
    ap.add_argument("--keep-v7a", action="store_true")
    ap.add_argument("--no-sign", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    args.keystore = args.keystore or default_keystore()

    if not os.path.isfile(args.apk):
        fail("找不到 %s" % args.apk)
    if not zipfile.is_zipfile(args.apk):
        fail("%s 不是 zip/APK" % args.apk)

    work = args.work or tempfile.mkdtemp(prefix="tfpatch-")
    os.makedirs(work, exist_ok=True)
    log("工作目录: %s" % work)

    # ---------- 1. 校验并抽出原版库 ----------
    log("\n[1/7] 校验原版 APK 并抽出 native 库")
    with zipfile.ZipFile(args.apk, "r") as z:
        names = set(z.namelist())
        if ("AndroidManifest.xml" not in names
                or (ABI_DIR + "/libTrialsGo.so") not in names):
            fail("这不像是 Trials Frontier 的 APK（缺 AndroidManifest.xml 或 %s/libTrialsGo.so）"
                 % ABI_DIR)
        src = {}
        for fn, (size, want) in LIBS.items():
            inner = "%s/%s" % (ABI_DIR, fn)
            if inner not in names:
                fail("APK 里没有 %s" % inner)
            p = os.path.join(work, fn)
            with open(p, "wb") as f:
                f.write(z.read(inner))
            got_size = os.path.getsize(p)
            got = sha256_file(p)
            ok = (got_size == size) and (want is None or got == want)
            log("    %-20s %9d 字节  sha256 %s  %s"
                % (fn, got_size, got[:16], "OK" if ok else "不匹配"))
            if not ok and not args.force:
                fail("%s 与原版不一致（版本不对？）。确认无误可加 --force 强制继续。" % fn)
            src[fn] = p
        man_in = os.path.join(work, "AndroidManifest.orig.xml")
        with open(man_in, "wb") as f:
            f.write(z.read("AndroidManifest.xml"))
        dex_in = None
        if "classes.dex" in names:
            dex_in = os.path.join(work, "classes.orig.dex")
            with open(dex_in, "wb") as f:
                f.write(z.read("classes.dex"))
            log("    %-20s %9d 字节" % ("classes.dex", os.path.getsize(dex_in)))
        else:
            log("    !! APK 里没有 classes.dex，Java 侧广告补丁将跳过")

    # ---------- 2. libTrialsGo.so: 17 处定点补丁 ----------
    ltg = os.path.join(work, "libTrialsGo.1.so")
    run([sys.executable, script("patch_native.py"),
         "--so", src["libTrialsGo.so"], "--out", ltg,
         "--report", os.path.join(work, "native-report.json")],
        "给 libTrialsGo.so 打 17 处定点补丁")

    # ---------- 3. 服务器地址：注入 DT_INIT 运行期改写 ----------
    log("\n[3/7] 注入服务器地址钩子（运行期读 tf_server.txt）")
    ltg2 = os.path.join(work, "libTrialsGo.2.so")
    run([sys.executable, script("patch_dynaddr.py"),
         "--so", ltg, "--out", ltg2, "--base", args.host],
        "libTrialsGo.so 注入 DT_INIT")
    ubis = os.path.join(work, "libubiservices.2.so")
    run([sys.executable, script("patch_dynaddr.py"),
         "--so", src["libubiservices.so"], "--out", ubis, "--base", args.host],
        "libubiservices.so 注入 DT_INIT")
    pg = os.path.join(work, "libplayground.2.so")
    run([sys.executable, script("patch_urls.py"),
         "--so", src["libplayground.so"], "--out", pg, "--base", args.host],
        "libplayground.so 静态改写（该库空间已满，无法注入）")

    # ---------- 4. 清单：targetSdkVersion -> 27 ----------
    man_out = os.path.join(work, "AndroidManifest.xml")
    run([sys.executable, script("patch_manifest.py"), "set",
         man_in, man_out, "targetSdkVersion=27"],
        "清单 targetSdkVersion 30 -> 27（放开明文 HTTP）")

    # ---------- 5. classes.dex：Java 侧广告方法改成 return-void ----------
    log("\n[5/7] 改写 classes.dex（Java 侧广告）")
    dex_out = None
    if dex_in:
        dex_out = os.path.join(work, "classes.patched.dex")
        run([sys.executable, script("patch_dex.py"),
             "--dex", dex_in, "--out", dex_out,
             "--report", os.path.join(work, "dex-report.json")],
            "把 CustomNativeActivity.{initAdMobRewardedVideoAds,tapjoyInit} 改成 return-void")

    # ---------- 6. 重新打包 ----------
    log("\n[6/7] 重新打包 APK")
    unsigned = os.path.join(work, "unsigned.apk")
    cmd = [sys.executable, script("build_apk.py"),
           "--base", args.apk, "--out", unsigned,
           "--replace", "%s/libTrialsGo.so=%s" % (ABI_DIR, ltg2),
           "--replace", "%s/libubiservices.so=%s" % (ABI_DIR, ubis),
           "--replace", "%s/libplayground.so=%s" % (ABI_DIR, pg),
           "--replace", "AndroidManifest.xml=%s" % man_out]
    if dex_out:
        cmd += ["--replace", "classes.dex=%s" % dex_out]
    if not args.keep_v7a:
        cmd += ["--drop-prefix", V7A_DIR + "/"]
    run(cmd, "重写 zip（逐条目搬运，丢弃旧签名）")

    # ---------- 7. zipalign + 签名 ----------
    log("\n[7/7] zipalign + 签名")
    out_abs = os.path.abspath(args.out)
    out_dir = os.path.dirname(out_abs)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    bt = find_build_tools(args.build_tools)
    if args.no_sign or not bt:
        if not args.no_sign:
            log("!! 没找到 Android build-tools（zipalign/apksigner），改为输出未签名 APK。")
            log("   装上 Android SDK 后重跑，或用 --build-tools 指定目录。")
        shutil.copyfile(unsigned, out_abs)
        log("\n未签名产物: %s (%d 字节)" % (out_abs, os.path.getsize(out_abs)))
        log("浏览器/文件管理器装不上未签名 APK，请用 apksigner 签一下。")
        return 0

    aligned = os.path.join(work, "aligned.apk")
    run([bt_exe(bt, "zipalign"), "-p", "-f", "4", unsigned, aligned], "zipalign")

    if not ensure_keystore(args.keystore, args.alias, args.store_pass):
        log("!! 没能准备签名密钥（缺 keytool？），输出未签名 APK。")
        shutil.copyfile(aligned, out_abs)
        return 0

    run([bt_exe(bt, "apksigner"), "sign",
         "--ks", args.keystore, "--ks-key-alias", args.alias,
         "--ks-pass", "pass:" + args.store_pass,
         "--key-pass", "pass:" + args.store_pass,
         "--v1-signing-enabled", "true",
         "--v2-signing-enabled", "true",
         "--v3-signing-enabled", "true",
         "--out", out_abs, aligned], "apksigner")

    log("")
    subprocess.call([bt_exe(bt, "apksigner"), "verify", "--print-certs", out_abs])
    log("\n完成: %s (%d 字节)" % (out_abs, os.path.getsize(out_abs)))
    log("")
    log("下一步：")
    log("  1) 在 PC 上启动本地服务器:  python server/tf_server.py")
    log("  2) 手机与 PC 同一个局域网；把 <PC的IP>:8000 写进手机上的")
    log("     %s" % SERVER_FILE)
    log("  3) adb install -r \"%s\"" % out_abs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
