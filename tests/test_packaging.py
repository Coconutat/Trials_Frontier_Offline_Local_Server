"""打包成 exe 的回归：运行期路径规则、首次播种白名单、端口优先级。

跑法：python -m unittest discover -s tests
所有写入都进 TemporaryDirectory，不碰 server/data 里的真实数据。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import tf_server as srv
import tflocal_accounts as acct

REPO = Path(__file__).resolve().parents[1]


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class RuntimePaths(unittest.TestCase):
    """源码运行时（未冻结）所有路径必须与打包改造前逐字一致。

    否则线上那份手调 tf_config.json / pvp_state.json 就被搬到别处了 —— 症状是
    「配置突然全变默认值、存档像是新人」，但服务器照样起得来，极难查。
    """

    def test_not_frozen(self):
        self.assertFalse(srv.FROZEN)
        self.assertIsNone(srv.EXE_DIR)

    def test_data_paths_stay_in_server_data(self):
        data = REPO / "server" / "data"
        self.assertTrue(same(srv.DATA_DIR, data))
        self.assertTrue(same(srv.CONFIG_PATH, data / "tf_config.json"))
        self.assertTrue(same(srv.PVP_STATE_PATH, data / "pvp_state.json"))
        self.assertTrue(same(srv._PLAYER_XP_PATH, data / "player_levels.json"))
        self.assertTrue(same(srv.LEADERBOARD_PATH, data / "leaderboards.json"))
        self.assertTrue(same(srv.TEMPLATES_PATH, data / "templates.json"))

    def test_accounts_module_follows_the_server(self):
        """tflocal_accounts 自己派生一套 DATA，两边必须指向同一个目录。

        忘了同步的话，存档写一处读另一处：玩家登录进去看到空车库。
        """
        self.assertTrue(same(acct.DATA, srv.DATA_DIR))
        self.assertTrue(same(acct.SAVE_DIR, os.path.join(srv.DATA_DIR, "save")))
        self.assertTrue(same(acct.GHOST_DIR, os.path.join(srv.DATA_DIR, "ghosts")))

    def test_readonly_assets_stay_in_the_bundle(self):
        """admin/ 前端、rules.json、items.json 是只读资源，仍从 HERE（包内）读。"""
        self.assertTrue(same(srv.RULES_PATH, REPO / "server" / "rules.json"))
        self.assertTrue(same(srv._ADMIN_DIR, REPO / "server" / "admin"))
        self.assertTrue(same(srv._TRACK_CATALOG_PATH, REPO / "server" / "admin" / "items.json"))
        self.assertTrue(same(acct._ITEM_CATALOG_PATH, REPO / "server" / "admin" / "items.json"))

    def test_frozen_exe_dir_prefers_the_nuitka_onefile_directory(self):
        """Nuitka onefile 的 sys.executable 是临时解包的 python.exe（真机踩过）。

        照它算 exe 目录，存档/日志/配置会落到 %TEMP%\\onefile_… 里、退出即丢；
        bootstrap 把真目录放在 NUITKA_ONEFILE_DIRECTORY 里，必须优先用它。
        """
        with tempfile.TemporaryDirectory() as real:
            with mock.patch.dict(os.environ, {"NUITKA_ONEFILE_DIRECTORY": real}):
                self.assertTrue(same(srv._frozen_exe_dir(), real))
                self.assertTrue(same(acct._frozen_exe_dir(), real))

    def test_frozen_exe_dir_falls_back_to_sys_executable(self):
        """PyInstaller（以及没设那个变量的 Nuitka）走 dirname(sys.executable)。"""
        env = {k: v for k, v in os.environ.items() if k != "NUITKA_ONEFILE_DIRECTORY"}
        with mock.patch.dict(os.environ, env, clear=True):
            want = os.path.dirname(os.path.abspath(sys.executable))
            self.assertTrue(same(srv._frozen_exe_dir(), want))
            self.assertTrue(same(acct._frozen_exe_dir(), want))
        bogus = os.path.join(tempfile.gettempdir(), "tf-no-such-dir-8f3a1c")
        with mock.patch.dict(os.environ, {"NUITKA_ONEFILE_DIRECTORY": bogus}):
            self.assertFalse(same(srv._frozen_exe_dir(), bogus), "不存在的目录不该被当成 exe 目录")


class SeedDataDir(unittest.TestCase):
    """首次运行的播种：只补缺、绝不覆盖，且白名单之外的东西一个都不许带。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tfseed-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_first_run_seeds_config_rewards_and_ghosts(self):
        done = srv.seed_data_dir(self.tmp)
        self.assertIn("tf_config.json", done)
        self.assertIn("wts_rewards.json", done)
        self.assertTrue(any(name.startswith("ghosts/") for name in done), done)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "tf_config.json")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "wts_rewards.json")))
        self.assertGreaterEqual(len(os.listdir(os.path.join(self.tmp, "ghosts"))), 1)

    def test_seed_is_idempotent(self):
        self.assertTrue(srv.seed_data_dir(self.tmp))
        self.assertEqual(srv.seed_data_dir(self.tmp), [])

    def test_seed_never_overwrites_user_data(self):
        srv.seed_data_dir(self.tmp)
        for name in ("tf_config.json", "wts_rewards.json"):
            with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fp:
                fp.write("MINE")
        ghost_dir = os.path.join(self.tmp, "ghosts")
        track = sorted(n for n in os.listdir(ghost_dir)
                       if os.path.isdir(os.path.join(ghost_dir, n)))[0]
        ghost = os.path.join(ghost_dir, track, sorted(os.listdir(os.path.join(ghost_dir, track)))[0])
        with open(ghost, "wb") as fp:
            fp.write(b"MINE")
        srv.seed_data_dir(self.tmp)
        for name in ("tf_config.json", "wts_rewards.json"):
            with open(os.path.join(self.tmp, name), encoding="utf-8") as fp:
                self.assertEqual(fp.read(), "MINE", name)
        with open(ghost, "rb") as fp:
            self.assertEqual(fp.read(), b"MINE")

    def test_seeded_config_is_the_builtin_default_not_the_live_one(self):
        """★ 发布版必须用内置默认值。把开发机上那份手调的 tf_config.json 发出去，
        等于把线上参数（还有我调试时留下的值）一起送人。"""
        srv.seed_data_dir(self.tmp)
        with open(os.path.join(self.tmp, "tf_config.json"), encoding="utf-8") as fp:
            seeded = json.load(fp)
        self.assertEqual(seeded, srv._TF_CONFIG_DEFAULTS)
        self.assertNotEqual(seeded, srv.tf_config())

    def test_private_files_are_never_seeded(self):
        """★ 安全边界：真机存档、管理员口令哈希、对局状态、登录会话、审计与日志
        一律不进包也不播种 —— 否则发给朋友的包里就带着我自己的账号和存档。"""
        srv.seed_data_dir(self.tmp)
        for name in ("admin.json", "accounts.json", "sessions.json", "devices.json",
                     "remember.json", "bindings.json", "pvp_state.json", "leaderboards.json",
                     "config_audit.jsonl", "templates.json", "save", "server.log"):
            self.assertFalse(os.path.exists(os.path.join(self.tmp, name)), name)


class PortResolution(unittest.TestCase):
    """端口：命令行 > port.txt 第一行 > 8123。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tfport-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_explicit_wins(self):
        with open(os.path.join(self.tmp, "port.txt"), "w", encoding="utf-8") as fp:
            fp.write("7000\n")
        self.assertEqual(srv._resolve_port(9001, self.tmp), (9001, "命令行"))

    def test_port_txt_beats_the_default(self):
        with open(os.path.join(self.tmp, "port.txt"), "w", encoding="utf-8") as fp:
            fp.write("# 想换端口就改这里\n7000\n")
        self.assertEqual(srv._resolve_port(None, self.tmp), (7000, "port.txt"))

    def test_default_is_8123(self):
        self.assertEqual(srv._resolve_port(None, self.tmp), (8123, "默认"))

    def test_garbage_falls_back_without_raising(self):
        """有人把 port.txt 写成别的东西时，服务器还得起得来（只是回到 8123）。"""
        with open(os.path.join(self.tmp, "port.txt"), "w", encoding="utf-8") as fp:
            fp.write("八百\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(srv._resolve_port(None, self.tmp), (8123, "默认"))
        self.assertIn("port.txt", buf.getvalue())


class AdminPageOpen(unittest.TestCase):
    """打包版启动后自动开后台管理页（`--no-browser` 关掉）。

    这里测的是「调对了地址、失败不拦服务」——真机开窗那一步是系统默认浏览器的事：
    `tools/exe_smoke.ps1` 一律用 `--no-browser`，所以那条路径靠本测试守。
    """

    def test_opens_the_admin_page_on_the_right_port(self):
        seen = []
        with mock.patch.object(srv.webbrowser, "open", lambda url: seen.append(url) or True):
            self.assertTrue(srv._open_admin_page(8123))
        self.assertEqual(seen, ["http://127.0.0.1:8123/__admin"])

    def test_a_broken_browser_never_kills_the_server(self):
        """没有桌面会话时 `os.startfile` 会抛 —— 必须吞掉（服务照跑）。"""
        def boom(url):
            raise OSError("no desktop session")
        with mock.patch.object(srv.webbrowser, "open", boom):
            self.assertFalse(srv._open_admin_page(8123))
        with mock.patch.object(srv.webbrowser, "open", lambda url: False):
            self.assertFalse(srv._open_admin_page(8123))


if __name__ == "__main__":
    unittest.main()
