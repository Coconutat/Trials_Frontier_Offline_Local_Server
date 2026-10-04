# -*- coding: utf-8 -*-
"""扫描 server/data/ghosts/<track>/*.bin，解析头部并输出 Markdown 索引。"""
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GH = os.path.join(ROOT, "server", "data", "ghosts")

NAME_RE = re.compile(r"^ghost_([0-9A-Fa-f]+)_(\d+)\.bin$")

OWNER_NOTE = {
    "0": "本机占位（游戏自己写的最佳线路，owner 哈希为 0）",
    "6f857655": "好友 6F857655 的真幽灵（唯一来自「别人」的数据）",
    "99511744": "本账号（onlineId 哈希 99511744）跑出来的线路",
}


def probe(path):
    d = open(path, "rb").read()
    ver, tag, rawlen, zero = struct.unpack_from("<IIII", d, 0)
    ok = False
    dt = fr = -1
    try:
        plain = zlib.decompress(d[16:])
        ok = (len(plain) == rawlen)
        dt, fr, _z = struct.unpack_from("<III", plain, 4)
    except Exception as e:  # noqa: BLE001
        print("  !! %s: %s" % (path, e), file=sys.stderr)
    return dict(size=len(d), ver=ver, tag=tag, declen=rawlen, dt=dt, fr=fr, ok=ok)


def main():
    rows = []
    for track_dir in sorted(os.listdir(GH)):
        full = os.path.join(GH, track_dir)
        if not (os.path.isdir(full) and track_dir.isdigit()):
            continue
        for name in sorted(os.listdir(full)):
            if not name.endswith(".bin"):
                continue
            m = NAME_RE.match(name)
            owner = m.group(1) if m else "?"
            info = probe(os.path.join(full, name))
            rows.append((int(track_dir), owner, name, info))

    out = []
    out.append("# 幽灵清单（server/data/ghosts/）\n")
    out.append("本文件由 `tmp/ghost_index.py` 生成，列出仓库里所有静态幽灵文件。\n")
    out.append("格式：`[track, drive_time, frames, size]`，`drive_time` 单位毫秒。\n")
    out.append("| 赛道 | owner | 文件 | drive_time | frames | size | 解压 | tag | 校验 |")
    out.append("|---:|---|---|---:|---:|---:|---:|---|---|")
    for track, owner, name, i in rows:
        out.append("| %d | `%s` | `%s` | %d | %d | %d | %d | `%08x` | %s |" % (
            track, owner, name, i["dt"], i["fr"], i["size"], i["declen"], i["tag"],
            "ok" if i["ok"] else "**FAIL**"))
    out.append("\n合计 **%d** 个文件 / **%d** 条赛道。\n" % (
        len(rows), len({r[0] for r in rows})))
    out.append("## owner 含义\n")
    for k, v in OWNER_NOTE.items():
        out.append("- `%s` —— %s" % (k, v))
    out.append("")
    text = "\n".join(out)
    dst = os.path.join(GH, "INDEX.md")
    open(dst, "w", encoding="utf-8", newline="\n").write(text)
    print(text)
    print("-> %s" % dst)


if __name__ == "__main__":
    main()
