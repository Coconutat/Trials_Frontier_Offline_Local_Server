#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二进制 AndroidManifest.xml (AXML) 读写工具。

只做我们能证明的事：
  * dump   —— 打印字符串池、资源映射，以及每个 <element> 的属性（带绝对偏移）
  * set    —— 就地改某个属性的数值（不改变文件长度，因此不需要修 chunk size）

用法:
    python tools/patch_manifest.py dump 原版AndroidManifest.xml [--grep targetSdk]
    python tools/patch_manifest.py set  in.xml out.xml targetSdkVersion=27
    python tools/patch_manifest.py get  in.xml targetSdkVersion
"""
import argparse
import struct
import sys

RES_XML_TYPE = 0x0003
RES_STRING_POOL_TYPE = 0x0001
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_XML_START_ELEMENT_TYPE = 0x0102

TYPE_NAMES = {0x00: "NULL", 0x01: "REFERENCE", 0x02: "ATTRIBUTE", 0x03: "STRING",
              0x04: "FLOAT", 0x05: "DIMENSION", 0x06: "FRACTION", 0x10: "INT_DEC",
              0x11: "INT_HEX", 0x12: "INT_BOOLEAN", 0x1C: "INT_COLOR_ARGB8"}
NO_INDEX = 0xFFFFFFFF


def u16(d, o):
    return struct.unpack_from("<H", d, o)[0]


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def parse_string_pool(d, off):
    typ, hs, sz = struct.unpack_from("<HHI", d, off)
    assert typ == RES_STRING_POOL_TYPE, "offset 0x%x 不是字符串池" % off
    cnt, styc, flags, strstart, stystart = struct.unpack_from("<IIIII", d, off + 8)
    utf8 = bool(flags & (1 << 8))
    offs = struct.unpack_from("<%dI" % cnt, d, off + 28) if cnt else ()
    base = off + strstart
    out = []
    for o in offs:
        p = base + o
        try:
            if utf8:
                n = d[p]
                if n & 0x80:
                    n = ((n & 0x7F) << 8) | d[p + 1]
                    p += 2
                else:
                    p += 1
                out.append(d[p:p + n].decode("utf-8", "replace"))
            else:
                n = u16(d, p)
                if n & 0x8000:
                    n = ((n & 0x7FFF) << 16) | u16(d, p + 2)
                    p += 4
                else:
                    p += 2
                out.append(d[p:p + n * 2].decode("utf-16-le", "replace"))
        except Exception as e:  # noqa
            out.append("<decode error %s>" % e)
    return {"count": cnt, "utf8": utf8, "strings": out, "end": off + sz}


def parse_chunks(d):
    """返回 (strings, resource_map, elements)。elements 是 dict 列表。"""
    typ, hs, total = struct.unpack_from("<HHI", d, 0)
    if typ != RES_XML_TYPE:
        raise SystemExit("不是 AXML（type=0x%04x）" % typ)
    strings = None
    resmap = []
    elements = []
    pos = hs
    while pos + 8 <= total:
        ctyp, chs, csz = struct.unpack_from("<HHI", d, pos)
        if csz < 8:
            break
        if ctyp == RES_STRING_POOL_TYPE:
            strings = parse_string_pool(d, pos)
        elif ctyp == RES_XML_RESOURCE_MAP_TYPE:
            n = (csz - chs) // 4
            resmap = list(struct.unpack_from("<%dI" % n, d, pos + chs)) if n else []
        elif ctyp == RES_XML_START_ELEMENT_TYPE:
            line = u32(d, pos + 8)
            ns_i = u32(d, pos + 16)
            name_i = u32(d, pos + 20)
            astart = u16(d, pos + 24)
            asize = u16(d, pos + 26)
            acount = u16(d, pos + 28)
            attrs = []
            abase = pos + 16 + astart
            for k in range(acount):
                ao = abase + k * asize
                attrs.append({
                    "off": ao,
                    "ns": u32(d, ao),
                    "name": u32(d, ao + 4),
                    "raw": u32(d, ao + 8),
                    "vsize": u16(d, ao + 12),
                    "res0": d[ao + 14],
                    "dtype": d[ao + 15],
                    "data": u32(d, ao + 16),
                })
            elements.append({"chunk_off": pos, "line": line, "ns": ns_i,
                             "name": name_i, "attrs": attrs})
        pos += csz
    return strings, resmap, elements


def attr_resid(name_index, resmap):
    if name_index < len(resmap):
        return resmap[name_index]
    return None


def fmt_val(d, s, a):
    t = a["dtype"]
    if t == 0x03:
        i = a["data"]
        return "string[%d]=%r" % (i, s["strings"][i] if i < len(s["strings"]) else "?")
    if t in (0x10, 0x11):
        return str(a["data"])
    if t == 0x12:
        return "true" if a["data"] else "false"
    if t == 0x01:
        return "@ref 0x%08x" % a["data"]
    return "type=%s data=0x%x" % (TYPE_NAMES.get(t, hex(t)), a["data"])


def cmd_dump(args):
    d = open(args.xml, "rb").read()
    s, resmap, els = parse_chunks(d)
    typ, hs, total = struct.unpack_from("<HHI", d, 0)
    print("文件 %s  %d 字节  声明总长 %d  (headerSize=%d)" % (args.xml, len(d), total, hs))
    print("字符串池: %d 条, %s" % (s["count"], "UTF-8" if s["utf8"] else "UTF-16"))
    print("资源映射: %d 条" % len(resmap))
    for e in els:
        nm = s["strings"][e["name"]] if e["name"] < len(s["strings"]) else "?"
        line = "  <%s>" % nm
        if args.grep and args.grep.lower() not in line.lower():
            keep = [a for a in e["attrs"]
                    if args.grep.lower() in (s["strings"][a["name"]] if a["name"] < len(s["strings"]) else "").lower()]
            if not keep:
                continue
            for a in keep:
                an = s["strings"][a["name"]] if a["name"] < len(s["strings"]) else "?"
                rid = attr_resid(a["name"], resmap)
                print("  <%s> @0x%06x  %-28s resid=0x%08x  raw=%s  %s"
                      % (nm, a["off"], "android:" + an, rid or 0, hex(a["raw"]), fmt_val(d, s, a)))
            continue
        print(line + "  chunk@0x%06x line=%d ns=%d name_idx=%d attrs=%d"
              % (e["chunk_off"], e["line"], e["ns"], e["name"], len(e["attrs"])))
        for a in e["attrs"]:
            if args.grep and args.grep.lower() not in (s["strings"][a["name"]] if a["name"] < len(s["strings"]) else "").lower():
                continue
            an = s["strings"][a["name"]] if a["name"] < len(s["strings"]) else "?"
            rid = attr_resid(a["name"], resmap)
            print("      attr@0x%06x  %-26s resid=0x%08x  raw=%s  %s"
                  % (a["off"], "android:" + an, rid or 0, hex(a["raw"]), fmt_val(d, s, a)))
    return 0


def find_attr(d, s, resmap, els, name):
    idx = [i for i, x in enumerate(s["strings"]) if x == name]
    if not idx:
        return None, None, None
    idx = idx[0]
    for e in els:
        for a in e["attrs"]:
            if a["name"] == idx:
                return e, a, attr_resid(idx, resmap)
    return None, None, None


def cmd_get(args):
    d = open(args.xml, "rb").read()
    s, resmap, els = parse_chunks(d)
    for nv in args.items:
        name = nv.split("=")[0]
        el, a, rid = find_attr(d, s, resmap, els, name)
        if not a:
            print("%-28s 未找到" % name)
            continue
        en = s["strings"][el["name"]]
        print("<%s> %-20s resid=0x%08x type=%s value=%s (data@0x%06x)"
              % (en, name, rid or 0, TYPE_NAMES.get(a["dtype"], hex(a["dtype"])), fmt_val(d, s, a), a["off"] + 16))
    return 0


def cmd_set(args):
    d = bytearray(open(args.xml, "rb").read())
    s, resmap, els = parse_chunks(bytes(d))
    rc = 0
    for nv in args.items:
        name, val = nv.split("=", 1)
        el, a, rid = find_attr(bytes(d), s, resmap, els, name)
        if not a:
            print("未找到属性 %s" % name)
            rc = 2
            continue
        if a["dtype"] not in (0x10, 0x11, 0x12):
            print("属性 %s 不是整数/布尔（type=%s），拒绝改" % (name, TYPE_NAMES.get(a["dtype"])))
            rc = 2
            continue
        new = int(val, 0)
        old = a["data"]
        struct.pack_into("<I", d, a["off"] + 16, new)
        en = s["strings"][el["name"]]
        print("改 <%s> android:%-24s %d -> %d  (写 @0x%06x)" % (en, name, old, new, a["off"] + 16))
    if rc == 0 and args.out != args.xml:
        open(args.out, "wb").write(bytes(d))
        print("已写出 %s (%d 字节)" % (args.out, len(d)))
    elif rc == 0:
        open(args.xml, "wb").write(bytes(d))
        print("已就地写回 %s" % args.xml)
    return rc


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump")
    p.add_argument("xml")
    p.add_argument("--grep", default=None)
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("get")
    p.add_argument("xml")
    p.add_argument("items", nargs="+")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set")
    p.add_argument("xml")
    p.add_argument("out")
    p.add_argument("items", nargs="+")
    p.set_defaults(func=cmd_set)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
