# -*- coding: utf-8 -*-
"""对齐 + 签名 + 验签。

不自己实现签名器：v2/v3 的签名块格式、APK Signing Block 的对齐、以及
「v1 之后 v2 摘要必须覆盖 zip 中央目录」这些坑不值得重写一遍。
v1+v2+v3 全开是为了兼容 Android 5/6（它们只认 v1）。
"""

import os

from . import cliutil
from .cliutil import ToolError, call


def _candidates():
    root = cliutil.app_dir()
    return [
        os.path.join(root, "keystore", "trials.jks"),   # 一把都没有时在这里现场生成
        # 开发态：仓库里本来就有的那把私服签名密钥，用它才能覆盖安装
        os.path.join(root, "work", "trials-frontier", "keystore", "trials.jks"),
        # 交付态：exe 和 dist\patcher\ 摆在一起，密钥就在 patcher 里面
        os.path.join(root, "patcher", "keystore", "trials.jks"),
        os.path.join(root, "trials.jks"),
    ]


def default_keystore():
    """优先用已经存在的那把；一把都没有才用第一个位置并在那里新建。"""
    for p in _candidates():
        if os.path.isfile(p):
            return p
    return _candidates()[0]


def ensure_keystore(ks, alias, store_pass, log=print):
    if os.path.isfile(ks):
        log("签名密钥已存在：%s" % ks)
        return ks
    kt = cliutil.find_keytool()
    if not kt:
        raise ToolError("找不到 keytool（装个 JDK，或设 JAVA_HOME）")
    os.makedirs(os.path.dirname(os.path.abspath(ks)), exist_ok=True)
    log("生成签名密钥（自签，首次运行只做一次）：%s" % ks)
    call([kt, "-genkeypair", "-keystore", ks, "-alias", alias,
          "-keyalg", "RSA", "-keysize", "2048", "-validity", "36500",
          "-storepass", store_pass, "-keypass", store_pass,
          "-dname", "CN=Trials Frontier Local Server, OU=Local, O=Local, C=CN"],
         log=log)
    return ks


def align(build_tools, src, dst, log=print):
    exe = cliutil.bt_exe(build_tools, "zipalign")
    if not exe:
        raise ToolError("build-tools 里没有 zipalign：%s" % build_tools)
    if os.path.exists(dst):
        os.remove(dst)
    # -p: 页对齐 .so（Android 6+ 才会 mmap 它）；-f: 覆盖；4: 4 字节对齐
    call([exe, "-p", "-f", "4", src, dst], log=log)
    if not os.path.isfile(dst):
        raise ToolError("zipalign 没产出 %s" % dst)
    return dst


def sign(build_tools, aligned, out, ks, alias, store_pass, log=print):
    exe = cliutil.bt_exe(build_tools, "apksigner")
    if not exe:
        raise ToolError("build-tools 里没有 apksigner：%s" % build_tools)
    if os.path.exists(out):
        os.remove(out)
    call([exe, "sign", "--ks", ks, "--ks-key-alias", alias,
          "--ks-pass", "pass:" + store_pass, "--key-pass", "pass:" + store_pass,
          "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
          "--v3-signing-enabled", "true", "--out", out, aligned], log=log)
    if not os.path.isfile(out):
        raise ToolError("apksigner 没产出 %s" % out)
    return out


def verify(build_tools, apk, log=print):
    exe = cliutil.bt_exe(build_tools, "apksigner")
    rc, out = call([exe, "verify", "--verbose", "--print-certs", apk],
                   log=log, check=False)
    return rc, out
