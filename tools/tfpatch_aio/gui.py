# -*- coding: utf-8 -*-
"""图形界面（tkinter，纯标准库）。

窗口只有一件事：勾功能 → 点「开始打补丁」→ 看日志。所有参数都给默认值，
最省事的用法是把原版 APK 拖进来、按开始。
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from . import cli, cliutil, features, payload as payload_mod, pipeline, signer

APP_TITLE = "Trials Frontier 离线补丁器"
HINT_DIRTEXT = ("手机上要填的私服地址。APK 里的 URL 会指向它；"
                "游戏里还能改 "
                "Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt")


class App(object):
    def __init__(self, root):
        self.root = root
        self.log_q = queue.Queue()
        self.running = False
        root.title(APP_TITLE)
        root.minsize(760, 640)
        self.fv = {f.key: tk.BooleanVar(value=f.default or f.required)
                   for f in features.FEATURES}
        self.p = {k: tk.StringVar() for k in
                  ("apk_in", "apk_out", "server", "payload", "work", "keystore",
                   "alias", "store_pass", "build_tools",
                   "force", "keep_v7a", "skip_sign")}
        self.p["server"].set("192.168.1.100:8000")
        self.p["alias"].set("trials")
        self.p["store_pass"].set("trialsfrontier")
        self.p["keystore"].set(signer.default_keystore())
        self._build()
        self.root.after(80, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log("程序目录：%s%s" % (cliutil.app_dir(),
                                   "（打包后的 exe）" if cliutil.FROZEN else "（源码态）"))
        self.log("点「环境自检」先看本机缺什么；只有签名那步需要 Java（apksigner）。")

    # ------------------------------------------------------------ 搭建界面
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        files = ttk.LabelFrame(outer, text="文件", padding=8)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        self._row(files, 0, "原版 APK", "apk_in", browse=self._pick_apk,
                  hint="你自备的原版安装包（不是已经打过补丁的那个）")
        self._row(files, 1, "输出到", "apk_out", browse=self._pick_out,
                  hint="留空 = dist/TrialsFrontier-patched-<时间>.apk")
        self._row(files, 2, "服务器地址", "server", hint=HINT_DIRTEXT)

        feat = ttk.LabelFrame(outer, text="功能", padding=8)
        feat.pack(fill="x", pady=(8, 0))
        self.bundle_hint = None
        for i, f in enumerate(features.FEATURES):
            cb = ttk.Checkbutton(feat, text=f.label, variable=self.fv[f.key],
                                 command=self._on_feature)
            cb.grid(row=i, column=0, sticky="w", padx=(0, 6), pady=1)
            mark = "（必选）" if f.required else ""
            ttk.Label(feat, text=mark + f.hint, foreground="#666",
                      wraplength=620, justify="left").grid(
                row=i, column=1, sticky="w", pady=1)
            if f.required:
                cb.state(["disabled"])

        self.pay = ttk.LabelFrame(outer, text="自包含载荷（勾了「打包成自包含完整 APK」才用）",
                                  padding=8)
        self.pay.pack(fill="x", pady=(8, 0))
        self.pay.columnconfigure(1, weight=1)
        self._row(self.pay, 0, "载荷位置", "payload", browse=self._pick_payload,
                  hint="放着 appdata/ 和 obb/ 的目录，或它们的 zip；留空 = "
                       "自动找程序旁边的 payload/ 或 payload.zip")
        self._pay_visible(False)

        adv = ttk.LabelFrame(outer, text="高级（一般不用动）", padding=8)
        adv.pack(fill="x", pady=(8, 0))
        adv.columnconfigure(1, weight=1)
        self._row(adv, 0, "build-tools", "build_tools", browse=self._pick_bt,
                  hint="Android SDK 的 build-tools 目录（zipalign/apksigner）")
        self._row(adv, 1, "签名密钥", "keystore", browse=self._pick_ks,
                  hint="不存在就自动生成一个自签证书；换了密钥要卸载重装")
        self._row(adv, 2, "别名 / 口令", None, two=("alias", "store_pass"))
        self._row(adv, 3, "工作目录", "work", browse=self._pick_work,
                  hint="中间文件（默认系统临时目录）")
        checks = ttk.Frame(adv)
        checks.grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Checkbutton(checks, text="忽略原版校验（版本不认识时用）",
                        variable=self.p["force"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(checks, text="保留 armeabi-v7a（不推荐）",
                        variable=self.p["keep_v7a"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(checks, text="只出未签名 APK",
                        variable=self.p["skip_sign"]).pack(side="left")

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 4))
        self.btn_go = ttk.Button(bar, text="开始打补丁", command=self.start)
        self.btn_go.pack(side="left")
        ttk.Button(bar, text="环境自检", command=self.check_env).pack(side="left", padx=6)
        ttk.Button(bar, text="打开输出目录", command=self.open_out).pack(side="left")
        ttk.Button(bar, text="清空日志", command=self._clear).pack(side="left", padx=6)
        self.bar = ttk.Progressbar(bar, mode="indeterminate", length=180)
        self.bar.pack(side="right")

        box = ttk.LabelFrame(outer, text="日志", padding=4)
        box.pack(fill="both", expand=True, pady=(6, 0))
        self.txt = tk.Text(box, height=18, wrap="word", font=("Consolas", 9),
                           background="#101418", foreground="#d8dee6",
                           insertbackground="#d8dee6")
        sb = ttk.Scrollbar(box, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)
        self.txt.configure(state="disabled")

    def _row(self, parent, r, label, key, browse=None, hint="", two=None):
        """第 r 组控件占两行：控件在 2r，提示在 2r+1（否则提示会盖住下一行）。"""
        top = r * 2
        ttk.Label(parent, text=label).grid(row=top, column=0, sticky="w", padx=(0, 6))
        if two:
            cell = ttk.Frame(parent)
            cell.grid(row=top, column=1, columnspan=2, sticky="we")
            for i, k in enumerate(two):
                ttk.Label(cell, text=("别名" if i == 0 else "口令")).pack(side="left")
                ttk.Entry(cell, textvariable=self.p[k], width=18,
                          show="" if i == 0 else "*").pack(side="left", padx=(2, 12))
            return
        e = ttk.Entry(parent, textvariable=self.p[key])
        e.grid(row=top, column=1, sticky="we")
        col = 2
        if browse:
            ttk.Button(parent, text="浏览…", command=browse).grid(
                row=top, column=col, padx=(6, 0))
            col += 1
        if hint:
            ttk.Label(parent, text=hint, foreground="#777", wraplength=620,
                      justify="left").grid(row=top + 1, column=1, columnspan=col,
                                           sticky="w", pady=(0, 4))

    # ---------------------------------------------------------------- 日志
    def log(self, s):
        self.log_q.put(str(s))

    def _pump(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.txt.configure(state="normal")
                self.txt.insert("end", line + "\n")
                self.txt.configure(state="disabled")
                self.txt.see("end")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _clear(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    # ------------------------------------------------------------ 文件选择
    def _pick_apk(self):
        p = filedialog.askopenfilename(title="选原版 APK",
                                       filetypes=[("Android 包", "*.apk"),
                                                  ("所有文件", "*.*")])
        if p:
            self.p["apk_in"].set(p)

    def _pick_out(self):
        p = filedialog.asksaveasfilename(title="输出 APK", defaultextension=".apk",
                                         filetypes=[("Android 包", "*.apk")])
        if p:
            self.p["apk_out"].set(p)

    def _pick_payload(self):
        p = filedialog.askdirectory(title="选载荷目录（含 appdata/ 和 obb/）")
        if not p:
            return
        self.p["payload"].set(p)

    def _pick_bt(self):
        p = filedialog.askdirectory(title="选 build-tools 目录")
        if p:
            self.p["build_tools"].set(p)

    def _pick_ks(self):
        p = filedialog.asksaveasfilename(title="签名密钥位置", defaultextension=".jks",
                                         filetypes=[("Java 密钥库", "*.jks")])
        if p:
            self.p["keystore"].set(p)

    def _pick_work(self):
        p = filedialog.askdirectory(title="选工作目录")
        if p:
            self.p["work"].set(p)

    # ---------------------------------------------------------------- 状态
    def _on_feature(self):
        self._pay_visible(bool(self.fv["bundle"].get()))

    def _pay_visible(self, show):
        if show:
            self.pay.pack(fill="x", pady=(8, 0), after=self._pay_anchor())
        else:
            self.pay.pack_forget()

    def _pay_anchor(self):
        # 让「自包含载荷」永远贴在「功能」框下面
        for w in self.root.winfo_children()[0].winfo_children():
            if isinstance(w, ttk.LabelFrame) and w.cget("text") == "功能":
                return w
        return None

    def _selected(self):
        return [f.key for f in features.FEATURES if self.fv[f.key].get()]

    def _options(self):
        g = lambda k: self.p[k].get().strip()
        return pipeline.Options(
            apk_in=g("apk_in"),
            apk_out=g("apk_out") or (pipeline.default_out(g("apk_in"))
                                     if g("apk_in") else ""),
            server=g("server") or "192.168.1.100:8000",
            selected=self._selected(),
            payload=g("payload"), work=g("work"), keystore=g("keystore"),
            alias=g("alias") or "trials",
            store_pass=g("store_pass") or "trialsfrontier",
            build_tools=g("build_tools"),
            force=bool(self.p["force"].get()),
            keep_v7a=bool(self.p["keep_v7a"].get()),
            skip_sign=bool(self.p["skip_sign"].get()),
            log=self.log)

    # ---------------------------------------------------------------- 动作
    def check_env(self):
        cfg = {"build_tools": self.p["build_tools"].get().strip(),
               "keystore": self.p["keystore"].get().strip(),
               "payload": self.p["payload"].get().strip()}
        self.log("")
        cli.print_environment(self.log, cfg)
        info = cli.environment(cfg)
        if not info["build_tools"]:
            self.log("  !! 没有 build-tools：能出未签名 APK，但装不上。")
        if not info["java"]:
            self.log("  !! 没有 java：apksigner 跑不起来。装个 JDK 或设 JAVA_HOME。")

    def open_out(self):
        o = self._options()
        d = os.path.dirname(os.path.abspath(o.apk_out or cliutil.app_dir()))
        if not os.path.isdir(d):
            d = cliutil.app_dir()
        try:
            if os.name == "nt":
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except OSError as exc:
            self.log("打不开目录 %s: %s" % (d, exc))

    def start(self):
        if self.running:
            return
        o = self._options()
        if not o.apk_in or not os.path.isfile(o.apk_in):
            messagebox.showerror(APP_TITLE, "先选一个原版 APK。")
            return
        if os.path.abspath(o.apk_in) == os.path.abspath(o.apk_out):
            messagebox.showerror(APP_TITLE, "输出不能覆盖输入。")
            return
        if "bundle" in o.selected:
            if not messagebox.askyesno(
                    APP_TITLE,
                    "自包含包会把离线数据（约 300 MB）塞进 APK，成品约 320 MB，"
                    "整个过程要几分钟。\n要继续吗？"):
                return
        self.running = True
        self.btn_go.state(["disabled"])
        self.bar.start(12)
        self.log("\n" + "=" * 64)
        threading.Thread(target=self._work, args=(o,), daemon=True).start()

    def _work(self, o):
        try:
            pipeline.run(o)
            self.log("\n[OK] 全部完成。")
        except cliutil.ToolError as exc:
            self.log("\n[X] %s" % exc)
        except Exception:
            self.log("\n[X] 意外错误：\n" + traceback.format_exc())
        finally:
            self.root.after(0, self._done)

    def _done(self):
        self.running = False
        self.bar.stop()
        self.btn_go.state(["!disabled"])

    def _on_close(self):
        if self.running and not messagebox.askyesno(
                APP_TITLE, "补丁还在跑，确定要关掉吗？"):
            return
        self.root.destroy()


def main(argv=None):
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0
