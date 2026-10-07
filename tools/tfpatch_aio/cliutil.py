# -*- coding: utf-8 -*-
"""AIO 补丁器的公共设施：路径、外部工具探测、子进程、把 vendored 脚本当函数调用。

设计约束（见 tools/README.md 的 AIO 一节）：
* 打包成 exe 后**不允许**再依赖解释器，所以所有 python 侧逻辑都走 import，
  绝不 spawn 一个 `python` 出来。
* 但仍然允许调用**系统已装好的**外部工具：zipalign / apksigner / java / keytool
  （签名器不自己实现，那是给用户埋雷）。
"""

import os
import subprocess
import sys

# ------------------------------------------------------------------ 路径

def _frozen():
    return bool(getattr(sys, "frozen", False)) or \
        globals().get("__compiled__") is not None


HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(HERE)
REPO_DIR = os.path.dirname(TOOLS_DIR)
FROZEN = _frozen()


def app_dir():
    """用户看得见的「程序所在目录」：exe 旁边，或源码态的仓库根。"""
    if FROZEN:
        # PyInstaller onefile / Nuitka onefile 都把真正的落点放在环境变量里
        d = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
        if d and os.path.isdir(d):
            return d
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
    return REPO_DIR


def asset(name):
    """assets/ 下的随包文件。PyInstaller 会把它们解到 sys._MEIPASS。"""
    if FROZEN:
        base = getattr(sys, "_MEIPASS", None) or os.path.join(HERE, "assets")
        p = os.path.join(base, "tfpatch_aio", "assets", name)
        if not os.path.exists(p):
            p = os.path.join(base, "assets", name)
        return p
    return os.path.join(HERE, "assets", name)


# ------------------------------------------------------- 外部工具探测

def _first_file(paths, names=("",)):
    for d in paths:
        if not d:
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None


def find_build_tools(explicit=None):
    """返回 build-tools 目录（含 zipalign/apksigner/d8 的那个版本目录）。"""
    roots = []
    if explicit:
        if os.path.isdir(explicit) and os.path.basename(
                os.path.dirname(os.path.abspath(explicit))).lower() == "build-tools":
            return explicit
        roots.append(explicit)
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_SDK"):
        v = os.environ.get(env)
        if v:
            roots.append(os.path.join(v, "build-tools"))
    la = os.environ.get("LOCALAPPDATA")
    if la:
        roots.append(os.path.join(la, "Android", "Sdk", "build-tools"))
    roots += [
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Android", "Sdk",
                     "build-tools"),
        "/usr/lib/android-sdk/build-tools",
        os.path.join(os.path.expanduser("~"), "Library", "Android", "sdk",
                     "build-tools"),
    ]
    cands = []
    for r in roots:
        if os.path.isdir(r):
            for name in os.listdir(r):
                d = os.path.join(r, name)
                if os.path.isdir(d) and os.path.isfile(os.path.join(d, "zipalign.exe")):
                    cands.append((name, d))
                elif os.path.isdir(d) and os.path.isfile(os.path.join(d, "zipalign")):
                    cands.append((name, d))
    if not cands:
        return None

    def key(t):
        try:
            return tuple(int(x) for x in t[0].split("-")[0].split("."))
        except ValueError:
            return (0,)
    cands.sort(key=key)
    return cands[-1][1]


def bt_exe(bt_dir, name):
    if not bt_dir:
        return None
    for cand in (name + ".exe", name + ".bat", name):
        p = os.path.join(bt_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def find_java():
    jh = os.environ.get("JAVA_HOME")
    if jh:
        p = _first_file([os.path.join(jh, "bin")], ("java.exe", "java"))
        if p:
            return p
    for d in ("C:\\Program Files\\Zulu\\zulu-25\\bin",
              "C:\\Program Files\\Java\\jdk-21\\bin",
              "C:\\Program Files\\Android\\Android Studio\\jbr\\bin",
              "/usr/bin"):
        p = _first_file([d], ("java.exe", "java"))
        if p:
            return p
    return _which("java")


def find_keytool():
    jh = os.environ.get("JAVA_HOME")
    if jh:
        p = _first_file([os.path.join(jh, "bin")], ("keytool.exe", "keytool"))
        if p:
            return p
    for d in ("C:\\Program Files\\Zulu\\zulu-25\\bin",
              "C:\\Program Files\\Java\\jdk-21\\bin",
              "C:\\Program Files\\Android\\Android Studio\\jbr\\bin"):
        p = _first_file([d], ("keytool.exe", "keytool"))
        if p:
            return p
    return _which("keytool")


def _which(name):
    from shutil import which
    return which(name)


# ------------------------------------------------------------- 子进程

class ToolError(Exception):
    pass


def utf8_streams():
    """把 stdout/stderr 掰成 UTF-8 + errors=replace。

    中文 Windows 的默认控制台编码是 GBK：我们的日志里有「»」之类的字符、
    外部工具的输出里又混着 OEM 编码的乱码，不换编码就会在 print 上炸
    UnicodeEncodeError（实测 keytool 那一步）。
    """
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is None:
            # --windowed 打包的 exe 里这两个是 None，print/argparse 会炸。
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _decode(raw):
    """外部工具的输出：先按 UTF-8 试，不像就按系统 ANSI 代码页解。"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        import locale
        enc = locale.getpreferredencoding(False) or "utf-8"
        try:
            return raw.decode(enc, "replace")
        except (LookupError, UnicodeDecodeError):
            return raw.decode("utf-8", "replace")


def call(argv, log=None, cwd=None, env=None, check=True):
    """跑一个外部程序，逐行回显到 log。返回 (rc, 合并输出)。"""
    if log:
        log("  $ " + " ".join('"%s"' % a if " " in a else a for a in argv))
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           cwd=cwd, env=e, creationflags=flags)
    except OSError as exc:
        raise ToolError("启动失败 %s: %s" % (argv[0], exc))
    out = _decode(p.stdout or b"")
    if log:
        for line in out.splitlines():
            line = line.strip()
            if line:
                log("    " + line)
    if check and p.returncode != 0:
        raise ToolError("%s 退出码 %d" % (os.path.basename(argv[0]), p.returncode))
    return p.returncode, out


# ------------------------------------------- 把 vendored 脚本当函数调用

class CliResult(object):
    def __init__(self, rc, err):
        self.rc = rc
        self.err = err


def run_cli(mod, argv, log=None):
    """vendored 的 6 个脚本都只有 argparse 的 main()，这里临时换掉 sys.argv 调它。

    比给每个脚本重构成库更短的路径；老脚本保持原样（它们仍是参考实现）。
    """
    old_argv, old_out = sys.argv, sys.stdout
    sink = None
    if log:
        sink = _LineSink(log, old_out)
    sys.argv = [getattr(mod, "__name__", "tool")] + [str(a) for a in argv]
    sys.stdout = sink or old_out
    rc = 0
    try:
        r = mod.main()
        if isinstance(r, int):
            rc = r
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        if sink is not None:
            sink.flush()
        sys.argv, sys.stdout = old_argv, old_out
        sys.stdout = old_out
    return CliResult(rc, None)


class _LineSink(object):
    """把脚本的 print 收进 logger（GUI 的日志框），按行切。

    ★ 关键：logger 本身往往就是 `print`（CLI 侧），而此时 `sys.stdout` 正是
    本 sink —— 直接调 `self._log` 会无限递归（RecursionError）。所以喂日志前
    把 `sys.stdout` 临时还原成真正的 stdout。
    """

    def __init__(self, log, real_out=None):
        self._log = log
        self._real = real_out if real_out is not None else sys.__stdout__
        self._buf = ""

    def _emit(self, line):
        saved = sys.stdout
        sys.stdout = self._real
        try:
            self._log(line)
        finally:
            sys.stdout = saved

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._emit(line.rstrip())

    def flush(self):
        if self._buf.strip():
            self._emit(self._buf.rstrip())
        self._buf = ""

    def isatty(self):
        return False
