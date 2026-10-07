# -*- coding: utf-8 -*-
"""PyInstaller 入口：把 tools.tfpatch_aio 当**包**导入，再交给它的 main()。

不能直接把 `tools/tfpatch_aio/__main__.py` 喂给 PyInstaller —— 那样它会被当成
顶层的 `__main__` 模块执行，包内的 `from . import gui` 相对导入会直接崩
（`ImportError: attempted relative import with no known parent package`）。
"""

import os
import sys

# 源码态：脚本在 tools/ 下，仓库根要能 import。冻结态这行是空操作。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tfpatch_aio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
