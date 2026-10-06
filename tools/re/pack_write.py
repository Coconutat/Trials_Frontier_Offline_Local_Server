#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""datapack::DataFilePack container writer (+ round-trip reader + selftest).

Layout (little endian, recovered from libTrialsGo.so; see
work/trials-frontier/notes/item-ids.md §0 and pvp-reward-contract.md §5c):

  0x00 u32 word0   (per-pack id/version - NOT validated by DataPack::open @0x8456b8;
                    content.dat = 0xdbf7dddb, TrialsContentExtraDL_Cave.dat = 0xe3d964e8,
                    TrialsTexturesDL_android.dat = 0)
  0x04 u32 count
  0x08 u32 recsize (12 for content/config packs, 24 for texture packs)
  0x0C table[count] x recsize bytes = { u32 uncompressedSize, u32 dataOffset, u32 nameHash }
  end_of_table = 12 + count*recsize
  blob @ end_of_table + dataOffset = { u32 payloadSize, u8 flag(1=zlib, 0=stored), 3 pad, payload }
  dataOffset is always a multiple of 16; the file is padded with 0xba.

Mount rule (GlobalData::initAdditionalDataPacks @0x4cfdd0 -> findFilePacks @0x4d23a0):
every *.dat in the app's internal files dir whose name is `TrialsContentExtraDL_*`
(prefix compare + '_' at that index, see 0x4d2580-0x4d25b8) is mounted as an extra pack;
DataFilePack::searchFile @0x844a78 walks m_instances from the end, so the pack built LAST
wins -> and initAdditionalDataPacks sorts+reverses the names, so the lexicographically
SMALLEST file name wins among the extras.

Usage:
  python tools/re/pack_write.py selftest
  python tools/re/pack_write.py build <out.dat> <internal/path>=<localfile> [...] [--word0 0x...]
  python tools/re/pack_write.py read <pack.dat> <internal/path> [<outfile>]
"""
import json
import os
import struct
import sys
import zlib

MAGIC_CONTENT = 0xDBF7DDDB


def get_hash_code(s) -> int:
    """mt::String::getHashCode(const char*) @0x008695ac, ported byte-exact."""
    if isinstance(s, str):
        s = s.encode('utf-8')
    w8 = len(s) & 0xFFFFFFFF
    h = 0
    for ch in s:
        h = (w8 * ch + h) & 0xFFFFFFFF
        w8 = ((w8 & 0xFFFF) * 0x4650 + (w8 >> 16)) & 0xFFFFFFFF
    return h


def build(entries, word0=0, recsize=12, align=16):
    """entries: [(internal path, bytes)] -> packed image (stored, flag=0)."""
    table = bytearray()
    blob = bytearray()
    for path, payload in entries:
        key = path.encode('utf-8') if isinstance(path, str) else path
        table += struct.pack('<III', len(payload), len(blob), get_hash_code(key))
        blob += struct.pack('<IB3x', len(payload), 0) + payload
        blob += b'\xba' * ((-len(blob)) % align)
    out = struct.pack('<III', word0, len(entries), recsize) + bytes(table) + bytes(blob)
    return out + b'\xba' * ((-len(out)) % align)


def entry_paths(data, recsize=12):
    """Yield (record index, nameHash, uncompressedSize, dataOffset)."""
    _w0, count, rs = struct.unpack_from('<III', data, 0)
    rs = recsize or rs
    for i in range(count):
        size, doff, h = struct.unpack_from('<III', data, 12 + i * rs)
        yield i, h, size, doff


def read_entry(data, path, recsize=12):
    """Return the decoded payload for an internal path, or None."""
    want = get_hash_code(path)
    _w0, count, rs = struct.unpack_from('<III', data, 0)
    rs = recsize or rs
    table_end = 12 + count * rs
    for _i, h, size, doff in entry_paths(data, rs):
        if h != want:
            continue
        pos = table_end + doff
        comp, flag = struct.unpack_from('<IB', data, pos)
        raw = data[pos + 8:pos + 8 + comp]
        return zlib.decompress(raw) if flag == 1 else raw[:size]
    return None


def _selftest():
    a = b'{"hello": "world"}\r\n'
    b = bytes(range(256)) * 40
    img = build([('/conf/pvp_match_rewards.txt', a), ('/gen/lang/english_strings.bin', b)],
                word0=0)
    # offsets must be 16-aligned and the table must tile the image
    _w0, count, rs = struct.unpack_from('<III', img, 0)
    assert (count, rs, _w0) == (2, 12, 0), (count, rs, _w0)
    table_end = 12 + count * rs
    for _i, _h, size, doff in entry_paths(img, rs):
        assert doff % 16 == 0, doff
        assert table_end + doff <= len(img)
    assert read_entry(img, '/conf/pvp_match_rewards.txt') == a
    assert read_entry(img, '/gen/lang/english_strings.bin') == b
    assert read_entry(img, '/conf/not_there.txt') is None
    assert get_hash_code('/conf/pvp_match_rewards.txt') == 0xA7EBC782
    # real container (optional): the same recipe must reproduce content.dat's members
    real_path = 'tmp/obb/content.dat'
    if os.path.exists(real_path):
        with open(real_path, 'rb') as fh:
            real = fh.read()
        t = read_entry(real, '/conf/pvp_match_rewards.txt')
        assert t and len(t) == 125010, len(t or b'')
        assert json.loads(t)['PVPMatchSpecialRewards']
        extra = 'content.dat member %d bytes' % len(t)
    else:
        extra = '%s absent -> synthetic round-trip only' % real_path
    print('selftest ok  (built %d bytes, %s)' % (len(img), extra))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == 'selftest':
        return _selftest()
    if cmd == 'build':
        out = sys.argv[2]
        word0 = 0
        args = []
        for a in sys.argv[3:]:
            if a.startswith('--word0'):
                word0 = int(a.split('=')[1], 0) if '=' in a else 0
            else:
                args.append(a)
        entries = []
        for a in args:
            path, _, src = a.partition('=')
            entries.append((path, open(src, 'rb').read()))
        img = build(entries, word0=word0)
        open(out, 'wb').write(img)
        print('wrote %s  %d bytes  %d entries  word0=%08x' % (out, len(img), len(entries), word0))
        for p, payload in entries:
            print('   %-40s %8d bytes  hash=%08x' % (p, len(payload), get_hash_code(p)))
        return 0
    if cmd == 'read':
        data = open(sys.argv[2], 'rb').read()
        blob = read_entry(data, sys.argv[3])
        if blob is None:
            print('ABSENT %s' % sys.argv[3])
            return 2
        if len(sys.argv) > 4:
            open(sys.argv[4], 'wb').write(blob)
            print('wrote %s (%d bytes)' % (sys.argv[4], len(blob)))
        else:
            print('%s -> %d bytes' % (sys.argv[3], len(blob)))
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main())
