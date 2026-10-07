# -*- coding: utf-8 -*-
"""Trials Frontier 离线补丁器（AIO）。

一个进程里干完老的 tools/tfpatcher.py + tools/make_selfcontained.ps1 两件事，
并按功能勾选做子集。老脚本保持原样，仍可作为参考/回退。
"""

__all__ = ["features", "pipeline", "cliutil", "payload", "signer", "cli", "gui"]
