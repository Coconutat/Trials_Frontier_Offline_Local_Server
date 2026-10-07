#!/usr/bin/env python3
"""从 APK 里抠出启动图标，转成多尺寸 .ico（给打包好的 exe 当图标用）。

为什么单独一个脚本而不是塞进打包脚本：**Pillow 只在开发机上需要**。
产物 `tools/assets/tf_icon.ico` 是提交进仓库的，打包脚本只引用它，
这样「打 exe」这条链上不需要任何图像库。

用法：
    python tools/make_icon.py                        # 用仓库里那份真原版
    python tools/make_icon.py --apk <别的.apk>
    python tools/make_icon.py --entry res/mipmap-xxxhdpi-v4/ic_launcher.png
    python tools/make_icon.py --list                 # 只列出 APK 里所有候选图标

候选规则：`res/mipmap-*-v4/ic_launcher.png` 里**像素面积最大**的那个
（mipmap 优先于 drawable；APK 里最大的那份是 192×192 的 xxxhdpi）。
"""
import argparse
import io
import os
import re
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_APK = os.path.join(
    ROOT, "dist", "原版APK",
    "com.ubisoft.redlynx.trialsfrontier.ggp_7.9.4-561_minAPI16(arm64-v8a,armeabi-v7a)(nodpi)_apkmirror.com.apk")
DEFAULT_OUT = os.path.join(HERE, "assets", "tf_icon.ico")
# 16/24/32/48 = 资源管理器与任务栏的常用档，64/128/192/256 = 大图标视图。
# 256 是从 192 放大的（原包最大的启动图只有 192×192）—— 不放大的话 Windows 自己
# 会用更糙的滤波拉一遍，不如我们拿 LANCZOS 先做。
SIZES = (16, 24, 32, 48, 64, 128, 192, 256)

CANDIDATE = re.compile(r"^res/(mipmap|drawable)-([a-z]+)-v[0-9]+/ic_launcher\.png$")


def pick_source(zf, want=None):
    """返回 (entry, (w, h), bytes)。want 给定就直接取那一条。"""
    from PIL import Image
    if want:
        if want not in zf.namelist():
            raise SystemExit("APK 里没有这条：%s" % want)
        data = zf.read(want)
        return want, Image.open(io.BytesIO(data)).size, data
    best = None
    for name in zf.namelist():
        m = CANDIDATE.match(name)
        if not m:
            continue
        data = zf.read(name)
        try:
            size = Image.open(io.BytesIO(data)).size
        except Exception:
            continue
        # mipmap 优先，其次比像素面积
        rank = (1 if m.group(1) == "mipmap" else 0, size[0] * size[1])
        if best is None or rank > best[0]:
            best = (rank, name, size, data)
    if best is None:
        raise SystemExit("这份 APK 里找不到 res/(mipmap|drawable)-*/ic_launcher.png")
    return best[1], best[2], best[3]


def list_candidates(zf):
    from PIL import Image
    rows = []
    for name in zf.namelist():
        if not CANDIDATE.match(name):
            continue
        data = zf.read(name)
        try:
            size = Image.open(io.BytesIO(data)).size
        except Exception:
            continue
        rows.append((size[0] * size[1], size, len(data), name))
    for _, size, n, name in sorted(rows, reverse=True):
        print("  %sx%s  %6d B  %s" % (size[0], size[1], n, name))
    return len(rows)


def write_ico(path, src, sizes):
    """自己写 ICO 容器：**每一档都用 BMP 条目**（32bpp BGRA + AND 掩码）。

    为什么不用 Pillow 的 `save(format="ICO")`：它把这些档位全写成 PNG 条目。
    PNG 条目只有 256×256 那一档是 Windows 明确支持的，小尺寸的 PNG 条目在
    资源管理器/任务栏上可能整片渲染不出来（图标变白板），风险不值当。
    BMP 条目是 1995 年就有的格式，所有版本通吃。

    布局：ICONDIR(6) + N×ICONDIRENTRY(16) + 各档 BITMAPINFOHEADER(40)
          + 自下而上的 BGRA 像素 + 4 字节对齐的 AND 掩码（1 = 透明）。
    """
    from PIL import Image
    frames = []
    for n in sizes:
        frame = src.resize((n, n), Image.LANCZOS)
        # XOR 位图：自下而上、BGRA
        xor = frame.transpose(Image.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
        # AND 掩码：alpha == 0 的像素置 1（32bpp 下用不到，但老渲染器会读它）
        m = (frame.getchannel("A").point(lambda a: 255 if a == 0 else 0)
             .convert("1", dither=Image.Dither.NONE))
        mb = m.tobytes()
        row_bytes = (n + 7) // 8
        stride = ((n + 31) // 32) * 4
        and_mask = bytearray()
        for y in range(n - 1, -1, -1):
            row = mb[y * row_bytes:(y + 1) * row_bytes]
            and_mask += row + b"\x00" * (stride - len(row))
        header = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0,
                             len(xor) + len(and_mask), 0, 0, 0, 0)
        frames.append((n, header + xor + bytes(and_mask)))

    offset = 6 + 16 * len(frames)
    head = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    blob = bytearray()
    for n, data in frames:
        wh = 0 if n >= 256 else n          # 256 在字段里写 0
        head += struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(data), offset + len(blob))
        blob += data
    with open(path, "wb") as fp:
        fp.write(bytes(head) + bytes(blob))
    return [(n, len(d)) for n, d in frames]


def main(argv=None):
    # 开发机控制台默认是 GBK（cp936），脚本里的中文/⚠ 直接 print 会 UnicodeEncodeError。
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="从 APK 提取图标 → 多尺寸 .ico")
    ap.add_argument("--apk", default=DEFAULT_APK, help="源 APK（默认：仓库里的真原版）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 .ico（默认 tools/assets/tf_icon.ico）")
    ap.add_argument("--entry", help="指定 APK 内的条目（默认自动挑最大的 ic_launcher.png）")
    ap.add_argument("--sizes", default=",".join(str(n) for n in SIZES), help="逗号分隔的尺寸")
    ap.add_argument("--list", action="store_true", help="只列出候选，不写文件")
    args = ap.parse_args(argv)

    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("需要 Pillow（只在这条一次性命令里用）：pip install pillow")

    if not os.path.exists(args.apk):
        raise SystemExit("找不到 APK：%s" % args.apk)
    with zipfile.ZipFile(args.apk) as zf:
        if args.list:
            n = list_candidates(zf)
            print("%d 个候选" % n)
            return 0
        entry, size, data = pick_source(zf, args.entry)

    sizes = tuple(sorted({int(x) for x in str(args.sizes).split(",") if x.strip()}))
    src = Image.open(io.BytesIO(data)).convert("RGBA")
    print("源：%s  %sx%s" % (entry, size[0], size[1]))
    if max(sizes) > max(size):
        print("  ⚠ 源图只有 %d×%d，%d 那一档是放大出来的" % (size[0], size[1], max(sizes)))

    # 逐档从**原图**重采样（不是逐级放大）；写 BMP 条目的理由见 write_ico()。
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    written = write_ico(args.out, src, sizes)
    print("写出：%s  %d B  %d 档 %s" % (
        args.out, os.path.getsize(args.out), len(written),
        " ".join("%dx%d" % (n, n) for n, _ in written)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
