# -*- coding: utf-8 -*-
"""入口：双击 = 图形界面；带命令行参数 = 命令行。

`python -m tools.tfpatch_aio` / 打包后的 exe 都走这里。
"""

import sys


def main():
    from .cliutil import utf8_streams
    utf8_streams()
    argv = sys.argv[1:]
    # 拖一个 apk 到 exe 上：当成「预填好输入文件」打开界面，而不是报参数错
    if len(argv) == 1 and argv[0].lower().endswith(".apk"):
        from . import gui
        import tkinter as tk
        root = tk.Tk()
        app = gui.App(root)
        app.p["apk_in"].set(argv[0])
        root.mainloop()
        return 0
    if argv:
        from .cli import main as cli_main
        return cli_main(argv)
    from .gui import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
