#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`mt::String::getHashCode` @0x008695ac 的移植（单文件版，无依赖）。

游戏用这个函数把字符串（本地化 KEY、在线存储键名等）压成 32 位 id。
`tools/re/locdump.py` 里有一份等价实现，本文件方便单独 import / 命令行算。

用法:
    python tools/re/mt_hash.py M_RACE_GHOST ITEM_1_2
    python tools/re/mt_hash.py                       # 无参数时跑内置自检样本
"""
import sys


def mt_hash(s):
    b = s.encode() if isinstance(s, str) else s
    if not b or b[0] == 0:
        return 0
    h = 0
    L = len(b)
    for c in b:
        h = (L * c + h) & 0xFFFFFFFF
        L = (((L & 0xFFFF) * 0x4650) + (L >> 16)) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


if __name__ == '__main__':
    if len(sys.argv) > 1:
        for s in sys.argv[1:]:
            print('%-40s %08X' % (s, mt_hash(s)))
    else:
        for s in ['OnlineGhost_OfflineGhost_Files', 'OnlineGhost_Difficulty_Type',
                  'OnlineGhost_Difficulty_Value', 'OnlineGhost_Extra_Ghost_Num',
                  'OnlineGhost_SpecialLB', 'OnlineGhost_Leading_Appearance',
                  'OnlineGhost_SpinningWheelRewards']:
            print('%-40s %08X' % (s, mt_hash(s)))
        print('target FEB78B09')
