# -*- coding: utf-8 -*-
"""自包含 APK 的离线载荷：找目录 / 解 zip / 生成条目清单。

条目形状与 tools/make_selfcontained.ps1 完全一致（payload.txt 每行 TAB 分隔）：
    kind \t rel \t asset
kind: r = 应用私有目录（/data/data/<pkg>/ 下的 rel）
      o = OBB（落到 getObbDir()）
      e = 外部 files/（/sdcard/Android/data/<pkg>/files/rel）
      f = 内部 files/（getFilesDir()/rel）—— patch_dynaddr 读的是外部那份
"""

import os
import zipfile

PKG = "com.ubisoft.redlynx.trialsfrontier.ggp"
OBBNAME = "main.561.com.ubisoft.redlynx.trialsfrontier.ggp.obb"
SKIP_TOP = {".tf_payload_v1"}


class PayloadError(Exception):
    pass


def looks_like_root(d):
    return os.path.isdir(os.path.join(d, "appdata"))


def find_root(hint):
    """在 hint 本身、它的子目录（深 2 层）里找直接含 appdata/ 的那个目录。"""
    if not hint:
        return None
    if os.path.isfile(hint) and hint.lower().endswith(".zip"):
        return hint
    if looks_like_root(hint):
        return hint
    if os.path.isdir(hint):
        for name in sorted(os.listdir(hint)):
            sub = os.path.join(hint, name)
            if looks_like_root(sub):
                return sub
            if os.path.isdir(sub):
                for n2 in sorted(os.listdir(sub)):
                    s2 = os.path.join(sub, n2)
                    if looks_like_root(s2):
                        return s2
    return None


def default_hint():
    """exe 旁边的约定位置；源码态再兜几个仓库里现成的位置。"""
    from . import cliutil
    names = ("payload", "payload.zip", "trials-payload", "clean-pack",
             "TrialsFrontier-clean-pack")
    for d in (cliutil.app_dir(), os.getcwd()):
        for name in names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    for rel in (os.path.join("tmp", "pack"), os.path.join("tmp", "pack", "TrialsFrontier-clean-pack"),
                "payload"):
        p = os.path.join(cliutil.app_dir(), rel)
        if find_root(p):
            return p
    return ""


def materialize(root, work, log=print):
    """zip → 解到 work/payload；目录 → 原样返回。"""
    if not os.path.isfile(root):
        return root
    dest = os.path.join(work, "payload")
    if looks_like_root(dest):
        log("载荷 zip 之前已解开：%s" % dest)
        return dest
    log("解压载荷 zip（约 300 MB，稍等）：%s" % root)
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(root) as z:
        bad = [n for n in z.namelist()
               if n.startswith("/") or ".." in n.replace("\\", "/").split("/")]
        if bad:
            raise PayloadError("zip 里有不安全的路径：%s" % bad[:3])
        z.extractall(dest)
    inner = find_root(dest)
    if inner is None:
        raise PayloadError("解开后仍然找不到 appdata/：%s" % dest)
    return inner


def server_file(work, server, log=print):
    p = os.path.join(work, "tf_server.txt")
    with open(p, "w", encoding="ascii", newline="") as f:
        f.write(server)
    log("服务器地址文件：%s = %s" % (p, server))
    return p


def collect(root, server, work, log=print):
    """返回 [(kind, rel, local_path), ...]，顺序即 assets/tf/p/NNNN 的编号。"""
    root = materialize(root, work, log)
    if not looks_like_root(root):
        raise PayloadError("载荷目录里没有 appdata/：%s" % root)

    entries = []
    appdata = os.path.join(root, "appdata")
    n = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(appdata):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, appdata).replace("\\", "/")
            if rel.split("/")[0] in SKIP_TOP:
                continue
            if ":" in rel or ".." in rel.split("/"):
                raise PayloadError("相对路径不像话：%s" % rel)
            entries.append(("r", rel, full))
            n += 1
            try:
                total += os.path.getsize(full)
            except OSError:
                pass
    if not entries:
        raise PayloadError("appdata/ 是空的：%s" % appdata)

    obbdir = os.path.join(root, "obb")
    obbs = [f for f in sorted(os.listdir(obbdir))
            if os.path.isfile(os.path.join(obbdir, f))] if os.path.isdir(obbdir) else []
    if len(obbs) != 1:
        raise PayloadError("obb/ 下应该正好一个文件，实际 %d 个" % len(obbs))
    entries.append(("o", OBBNAME, os.path.join(obbdir, obbs[0])))
    total += os.path.getsize(os.path.join(obbdir, obbs[0]))

    srv = server_file(work, server, log)
    entries.append(("e", "tf_server.txt", srv))
    entries.append(("f", "tf_server.txt", srv))

    log("载荷 %d 个条目，共 %.1f MB" % (len(entries), total / (1024.0 * 1024.0)))
    return entries


def write_manifest(entries, path):
    """payload.txt：UTF-8 无 BOM，LF，行尾不留空。返回 [(kind, rel, asset)]。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = []
    lines = []
    for i, (kind, rel, _local) in enumerate(entries):
        a = "p/%04d" % i
        out.append((kind, rel, a))
        lines.append("%s\t%s\t%s" % (kind, rel, a))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return out
