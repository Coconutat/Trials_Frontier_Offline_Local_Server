# -*- coding: utf-8 -*-
"""AIO 补丁器（tools/tfpatch_aio）的回归：功能开关、载荷清单、签名密钥、日志回流。

不碰真实 APK、不调 build-tools、不联网：全部用临时目录里的假数据。
跑法：python -m unittest discover -s tests
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.tfpatch_aio import cliutil, features, payload, signer  # noqa: E402
from tools.tfpatch_aio.vendored import native  # noqa: E402


class FeatureModel(unittest.TestCase):
    """功能开关是 GUI 复选框、CLI --features、流水线三处共用的唯一真相。"""

    def test_defaults_is_the_minimal_offline_set(self):
        """默认只勾「能离线玩」：offline + 去广告/去遥测，其余都手选。"""
        self.assertEqual(features.defaults(), ["offline", "noads"])

    def test_offline_is_required_and_always_present(self):
        self.assertTrue(features.BY_KEY["offline"].required)
        for sel in ([], ["fuel"], ["iap", "vip"]):
            keys, _, _, labels = features.resolve(sel)
            self.assertIn("offline", keys)
            self.assertEqual(len(labels), len(keys))

    def test_resolve_keeps_declaration_order(self):
        keys, _, _, _ = features.resolve(["vip", "fuel"])
        self.assertEqual(keys, ["offline", "fuel", "vip"])

    def test_resolve_collects_patches_and_actions(self):
        _, patches, actions, _ = features.resolve(["money", "iap"])
        self.assertIn(features.P_SPEND_ADDS, patches)
        for p in features.P_IAP:
            self.assertIn(p, patches)
        self.assertIn(features.ACT_MANIFEST_TARGETSDK, actions)   # 来自 offline
        self.assertNotIn(features.ACT_DEX, actions)               # 那要勾上 noads
        self.assertNotIn(features.ACT_BUNDLE, actions)

    def test_resolve_patch_order_matches_native(self):
        """补丁顺序 = native.py 的 PATCHES 顺序，日志才和单脚本跑一样好读。"""
        sel = ["vip", "fuel", "money"]
        _, patches, _, _ = features.resolve(sel)
        want = [p for p in features.ALL_PATCH_IDS if p in set(patches)]
        self.assertEqual(patches, want)
        self.assertEqual(patches[-3:], list(features.P_VIP_SHOP))

    def test_bundle_pulls_in_app_class_swap(self):
        _, _, actions, _ = features.resolve(["bundle"])
        self.assertIn(features.ACT_BUNDLE, actions)
        self.assertIn(features.ACT_SET_APPCLASS, actions)


class PatchIdsMatchNative(unittest.TestCase):
    """两边对不上的后果：GUI 勾了却什么都不改（native 用 --only 过滤，静默跳过）。"""

    def native_ids(self):
        return [p["id"] for p in native.PATCHES]

    def test_every_feature_patch_exists_in_native(self):
        missing = [p for p in features.ALL_PATCH_IDS if p not in self.native_ids()]
        self.assertEqual(missing, [])

    def test_no_orphan_patch_in_native(self):
        """native 里多出来的补丁 = 谁都开不了它，等于白改。"""
        orphans = [p for p in self.native_ids() if p not in features.ALL_PATCH_IDS]
        self.assertEqual(orphans, [])

    def test_no_duplicate_ids_in_native(self):
        ids = self.native_ids()
        self.assertEqual(len(ids), len(set(ids)))


class PayloadManifest(unittest.TestCase):
    """payload.txt 的格式必须和 make_selfcontained.ps1 / OfflinePayloadSetup 逐字一致。"""

    def make_root(self, tmp):
        root = os.path.join(tmp, "pack")
        os.makedirs(os.path.join(root, "appdata", "files"))
        os.makedirs(os.path.join(root, "obb"))
        with open(os.path.join(root, "appdata", "files", "save.dat"), "wb") as f:
            f.write(b"x" * 10)
        with open(os.path.join(root, "appdata", "top.txt"), "wb") as f:
            f.write(b"y" * 5)
        with open(os.path.join(root, "obb", payload.OBBNAME), "wb") as f:
            f.write(b"z" * 20)
        return root

    def test_collect_and_write_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            entries = payload.collect(root, "192.168.5.2:8123", tmp, log=lambda s: None)
            kinds = [k for k, _, _ in entries]
            self.assertEqual(kinds[-2:], ["e", "f"])
            self.assertIn("o", kinds)
            self.assertEqual(kinds.count("r"), 2)

            man = os.path.join(tmp, "assets", "tf", "payload.txt")
            rows = payload.write_manifest(entries, man)
            self.assertEqual(rows[0][2], "p/0000")
            self.assertEqual(rows[-1][2], "p/%04d" % (len(entries) - 1))

            with open(man, "rb") as f:
                raw = f.read()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "payload.txt 不能带 BOM")
            text = raw.decode("utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(len(text.strip().split("\n")), len(entries))
            for line in text.strip().split("\n"):
                self.assertEqual(len(line.split("\t")), 3)

            srv = [e for e in entries if e[0] == "e"][0][2]
            with open(srv, encoding="ascii") as f:
                self.assertEqual(f.read(), "192.168.5.2:8123")

    def test_obb_must_be_exactly_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            os.remove(os.path.join(root, "obb", payload.OBBNAME))
            with self.assertRaises(payload.PayloadError) as cm:
                payload.collect(root, "a:1", tmp, log=lambda s: None)
            self.assertIn("正好一个文件", str(cm.exception))

    def test_missing_appdata_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(payload.looks_like_root(tmp))
            with self.assertRaises(payload.PayloadError):
                payload.collect(tmp, "a:1", tmp, log=lambda s: None)

    def test_find_root_looks_one_level_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            outer = os.path.join(tmp, "outer")
            os.makedirs(outer)
            self.assertEqual(payload.find_root(outer), None)   # 载荷不在这儿
            self.assertEqual(payload.find_root(tmp), root)

    def test_zip_with_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            z = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("../evil.txt", b"nope")
            with self.assertRaises(payload.PayloadError) as cm:
                payload.materialize(z, os.path.join(tmp, "work"), log=lambda s: None)
            self.assertIn("不安全的路径", str(cm.exception))


class KeystoreChoice(unittest.TestCase):
    """签名密钥选错 = 产物装不上去（覆盖安装被拒），必须优先复用已有那把。"""

    def test_prefers_existing_dev_keystore(self):
        with tempfile.TemporaryDirectory() as tmp:
            dev = os.path.join(tmp, "work", "trials-frontier", "keystore", "trials.jks")
            os.makedirs(os.path.dirname(dev))
            open(dev, "wb").close()
            root = os.path.join(tmp, "keystore", "trials.jks")
            with unittest.mock.patch.object(signer, "_candidates", lambda: [root, dev]):
                self.assertEqual(signer.default_keystore(), dev)
            os.remove(dev)
            with unittest.mock.patch.object(signer, "_candidates", lambda: [root, dev]):
                self.assertEqual(signer.default_keystore(), root)

    def test_dist_layout_finds_the_shipped_keystore(self):
        """exe 摆在 dist\\ 里跑时，签名密钥是 dist\\patcher\\keystore 那把。

        找不到就会现场自签一把新的 —— 产物换签名，手机上覆盖安装被拒（存档一起没）。
        """
        rel = [os.path.relpath(p, cliutil.app_dir()).replace("\\", "/")
               for p in signer._candidates()]
        self.assertIn("patcher/keystore/trials.jks", rel)

    def test_picked_keystore_is_the_installed_apps_key(self):
        """本仓库真有那份密钥时，选中的必须是它（本地调试密钥，手机上装的就是它签的）。"""
        shipped = REPO / "dist" / "patcher" / "keystore" / "trials.jks"
        if not shipped.is_file():
            self.skipTest("dist/patcher/keystore 不在（干净检出或已清理）")
        with mock.patch.object(cliutil, "app_dir", lambda: str(REPO / "dist")):
            self.assertTrue(os.path.samefile(signer.default_keystore(), shipped))


class LogPlumbing(unittest.TestCase):
    """脚本的 print 要流进日志框，而日志回调本身往往就是 print。"""

    def test_cli_log_is_not_captured_by_its_own_sink(self):
        """★ RecursionError 回归：logger = print，而 sys.stdout 正是 sink。"""
        out = io.StringIO()
        saved = sys.stdout
        try:
            sink = cliutil._LineSink(lambda s: print(s, file=out), saved)
            sys.stdout = sink
            print("第一行")
            print("第二行")
        finally:
            sys.stdout = saved
        self.assertEqual(out.getvalue().strip().split("\n"), ["第一行", "第二行"])

    def test_run_cli_collects_stdout_and_restores(self):
        class Fake(object):
            @staticmethod
            def main():
                print("a")
                print("b")
                return 0

        seen = []
        before = sys.stdout
        rc = cliutil.run_cli(Fake, ["--x"], log=seen.append)
        self.assertEqual(rc.rc, 0)
        self.assertEqual(seen, ["a", "b"])
        self.assertIs(sys.stdout, before)

    def test_run_cli_reports_systemexit_code(self):
        class Boom(object):
            @staticmethod
            def main():
                raise SystemExit(2)

        self.assertEqual(cliutil.run_cli(Boom, [], log=None).rc, 2)


class SourcesStayUntouched(unittest.TestCase):
    """用户要求「老脚本不动做参考」：vendored 只是副本，原脚本必须还在。"""

    def test_original_scripts_still_exist(self):
        for name in ("patch_native.py", "patch_dynaddr.py", "patch_urls.py",
                     "patch_manifest.py", "patch_dex.py", "build_apk.py", "tfpatcher.py"):
            self.assertTrue((REPO / "tools" / name).is_file(), name)

    def test_vendored_copies_are_present(self):
        for name in ("native.py", "dynaddr.py", "urls.py", "axml.py", "dex.py", "zipbuild.py"):
            self.assertTrue((REPO / "tools" / "tfpatch_aio" / "vendored" / name).is_file(), name)

    def test_prebuilt_payload_dex_ships_with_the_package(self):
        """自包含打包靠它换 Application 类；缺了 exe 运行时才炸就太晚了。"""
        dex = REPO / "tools" / "tfpatch_aio" / "assets" / "payload_setup.dex"
        self.assertTrue(dex.is_file())
        blob = dex.read_bytes()
        self.assertEqual(blob[:8], b"dex\n035\x00")
        self.assertGreater(len(blob), 1024)


if __name__ == "__main__":
    unittest.main()
