"""Offline economic regressions: python -m unittest discover -s tests -v.

All writes go to a TemporaryDirectory; no device or live server is used.
"""
import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import tf_server as srv

BASE = "/public/pvp_matches/v1/"
PLAYER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class PVPEconomyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1800000000
        config = copy.deepcopy(srv._TF_CONFIG_DEFAULTS)
        # 关掉「按赛道产币」，让货币断言只看对局结算（要测产币的用例自己打开）。
        config["chips"].update(per_track_seconds=0)
        self.config = config
        config["matchmaking"]["track_ids"] = [1041, 1062, 1024]
        for name in ("_pvp_matches", "_pvp_search", "_pvp_chips", "_pvp_tickets",
                     "_pvp_reward_data", "_pvp_players"):
            state = getattr(srv, name, None)
            if isinstance(state, dict):
                state.clear()
        srv._pvp_next_id[0] = 1
        srv._pvp_dirty[0] = False
        srv._pvp_saved_at[0] = 0
        for p in (patch.object(srv, "PVP_STATE_PATH", str(Path(self.tmp.name) / "pvp.json")),
                  patch.object(srv, "tf_config", return_value=config),
                  patch.object(srv, "_ghost_caller", return_value=PLAYER),
                  patch.object(srv, "_pvp_real_players", return_value=set()),
                  patch.object(srv, "_pvp_online_others", return_value=[]),
                  patch.object(srv.time, "time", side_effect=lambda: self.now)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: srv._pvp_dirty.__setitem__(0, False))

    def call(self, method, endpoint, payload=None):
        endpoint, _, query = endpoint.partition("?")
        path = BASE + endpoint
        handler, _ = srv.pick_dynamic(method, path)
        self.assertIsNotNone(handler, "Missing dynamic route: " + path)
        return handler(path, query, json.dumps(payload).encode() if payload is not None else b"", {})

    def match(self):
        self.call("GET", "new_ranked")
        status, _, result = self.call("GET", "matches")
        self.assertEqual(status, 200)
        return result["matches"][0]

    def race(self, mid, tid=1041):
        self.assertEqual(self.call("POST", "start_race", {"match_id": mid, "track": tid,
                         "golden_ticket": "False"})[0], 200)
        result = self.call("POST", "race", {"match_id": mid, "track": tid,
                         "score": srv._pvp_score_int(30000), "bike_data": 1, "timestamp": self.now})
        self.assertEqual(result[0], 200)
        return result

    def close(self, mid, create_new="False"):
        return self.call("POST", "close", {"match_id": mid, "create_new": create_new,
                        "ticket": "False", "outfit": 0, "param": 0})

    def test_season_rewards_have_nested_item_pairs(self):
        season = self.call("GET", "pvp_config")[2]["current_season"]
        self.assertTrue(season["rewards"])
        self.assertIn("rewards", season["rewards"][0])
        self.assertEqual([row["rank"] for row in season["rewards"]], list(range(26)))
        self.assertEqual(season["rewards"][1]["rewards"][0], {"item_id": 1, "amount": 500})

    def test_six_hour_match_survives_queue_timeout(self):
        mid = self.match()["id"]
        self.now += 1801
        matches = self.call("GET", "matches")[2]["matches"]
        self.assertEqual([m["id"] for m in matches], [mid])

    def test_races_do_not_settle_before_deadline(self):
        mid = self.match()["id"]
        for tid in (1041, 1062, 1024):
            self.race(mid, tid)
        self.assertFalse(srv._pvp_matches[mid].get("_banked"), "Three results are not the six-hour deadline")
        self.assertEqual(srv._pvp_chips_for(PLAYER), 0)

    def test_reward_submission_survives_match_refresh(self):
        mid = self.match()["id"]
        self.race(mid)
        self.call("POST", "increase_rewards", {"match_id": mid, "race_id": mid,
                  "coin": 725, "gem": 4, "special": 2, "reward_data": 20008, "timestamp": self.now})
        result = self.call("GET", "matches/" + str(mid))[2]
        self.assertEqual(result["rewards"], [725, 4, 2])
        self.assertEqual(result["player1"]["reward_data"], 20008)

    def test_match_and_results_survive_reload(self):
        match = self.match()
        self.race(match["id"])
        srv._pvp_state_save(force=True)
        srv._pvp_matches.clear()
        srv._pvp_search.clear()
        srv._pvp_state_load()
        matches = self.call("GET", "matches")[2]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["start_time"], match["start_time"])
        self.assertEqual(matches[0]["tracks"][0]["result_p1"]["score"], srv._pvp_score_int(30000))

    def test_start_race_consumes_free_ticket_not_match_creation(self):
        mid = self.match()["id"]
        self.assertEqual(srv._pvp_tickets_for(PLAYER)[0], 3)
        self.call("POST", "start_race", {"match_id": mid, "track": 1041, "golden_ticket": "False"})
        self.assertEqual(self.call("GET", "matches/" + str(mid))[2]["player1"]["tickets"], 2)


    def test_close_settles_once_and_hides_claimed_match(self):
        mid = self.match()["id"]
        for tid in (1041, 1062, 1024):
            self.race(mid, tid)
        self.assertEqual(self.close(mid)[0], 409)
        self.now += 21600
        reply = self.close(mid)
        self.assertEqual(reply[0], 200)
        self.assertEqual(reply[2]["last_match_winner"], PLAYER)
        self.assertEqual(reply[2]["ownership_changes"], 3)
        expected = 3 * srv._chips_at(21600)
        self.assertEqual(srv._pvp_chips_for(PLAYER), expected)
        self.assertEqual(self.call("GET", "matches")[2]["matches"], [])
        self.assertEqual(self.call("GET", "matches/" + str(mid))[0], 404)
        srv._pvp_state_save(force=True)
        srv._pvp_matches.clear()
        srv._pvp_chips.clear()
        srv._pvp_players.clear()
        srv._pvp_state_load()
        self.now += 86400
        self.assertEqual(self.close(mid), reply)
        self.assertEqual(srv._pvp_chips_for(PLAYER), expected)
        self.assertEqual(srv._pvp_players[PLAYER]["star"], 1)

    def test_reward_deltas_retry_semantics_and_expiry(self):
        mid = self.match()["id"]
        rid = self.race(mid)[2]["race_id"]
        payload = {"match_id": mid, "race_id": rid, "coin": 725, "gem": 4,
                   "special": 2, "reward_data": 20008, "timestamp": self.now}
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 200)
        payload["timestamp"] += 1
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 200)
        self.assertEqual(srv._pvp_matches[mid]["rewards"], [725, 4, 2])
        payload["coin"] += 1
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 409)
        rid2 = self.race(mid, 1062)[2]["race_id"]
        payload.update(race_id=rid2, coin=100, gem=1, special=0)
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 200)
        self.assertEqual(srv._pvp_matches[mid]["rewards"], [825, 5, 2])
        self.now += 21600
        payload.update(race_id=0, coin=0, gem=0, reward_data=30001)
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 409)

    def test_unknown_race_cannot_mint_currency(self):
        mid = self.match()["id"]
        self.assertEqual(self.call("POST", "race", {"match_id": mid, "track": 1041,
                         "score": srv._pvp_score_int(30000)})[0], 409)
        for rid in (0, 999):
            with self.subTest(rid=rid):
                status = self.call("POST", "increase_rewards", {"match_id": mid,
                    "race_id": rid, "coin": 100, "gem": 1, "special": 0, "reward_data": 1})[0]
                self.assertGreaterEqual(status, 400)
        self.assertEqual(srv._pvp_matches[mid]["rewards"], [0, 0, 0])

    def test_chip_spending_uses_native_key_and_rejects_overspend(self):
        srv._pvp_chips_state(PLAYER)["chips"] = 1000
        self.assertEqual(self.call("POST", "chips", {"use_chips": 300})[2], {"chips": 700})
        for bad in ({"use_chips": 701}, {"use_chips": -1}, {"use_chips": True},
                    {"use_chips": 1.5}, {"price": 100}, []):
            self.assertGreaterEqual(self.call("POST", "chips", bad)[0], 400)
        self.assertEqual(srv._pvp_chips_for(PLAYER), 700)

    def test_golden_ticket_purchase_and_race_debit(self):
        mid = self.match()["id"]
        srv._pvp_chips_state(PLAYER)["chips"] = 100
        self.assertEqual(self.call("GET", "purchase_tickets?num=5&price=3")[2],
                         {"chips": 85, "golden_ticket": 8})
        body = {"match_id": mid, "track": 1041, "golden_ticket": "True"}
        self.assertEqual(self.call("POST", "start_race", body)[0], 200)
        self.assertEqual(self.call("POST", "start_race", body)[0], 200)
        self.assertEqual(srv._pvp_player_state(PLAYER)["golden_ticket"], 7)
        self.assertEqual(self.call("GET", "matches/" + str(mid))[2]["player1"]["tickets"], 3)
        # 基价 3：客户端穿折扣套装时送来的单价更低（`total//num`）是合法的，
        # 抬价不合法 —— 上界由服务端价表钉死。
        self.assertEqual(self.call("GET", "purchase_tickets?num=5&price=1")[0], 200)
        self.assertEqual(self.call("GET", "purchase_tickets?num=5&price=4")[0], 400)

    def test_start_retry_abort_and_refill(self):
        mid = self.match()["id"]
        body = {"match_id": mid, "track": 1041, "golden_ticket": "False"}
        for _ in range(2):
            self.assertEqual(self.call("POST", "start_race", body)[0], 200)
        body["track"] = 1062
        self.assertEqual(self.call("POST", "start_race", body)[0], 200)
        self.assertEqual(self.call("GET", "matches/" + str(mid))[2]["player1"]["tickets"], 1)
        self.now += 3600
        self.assertEqual(self.call("GET", "matches/" + str(mid))[2]["player1"]["tickets"], 2)

    def test_legend_promotion_and_streak(self):
        mid = self.match()["id"]
        state = srv._pvp_player_state(PLAYER)
        state.update(rank=1, star=5, win_streak=2)
        for tid in (1041, 1062):
            self.race(mid, tid)
        self.now += 21600
        self.assertEqual(self.close(mid)[0], 200)
        info = self.call("GET", "player/" + PLAYER)[2]
        self.assertEqual((info["rank"], info["star"], info["win_streak"]), (0, 0, 3))

    def test_third_win_adds_two_stars_and_match_reflects_rank(self):
        mid = self.match()["id"]
        srv._pvp_player_state(PLAYER).update(rank=5, star=1, win_streak=2)
        self.assertEqual(self.call("GET", "matches/" + str(mid))[2]["player1"]["rank"], 5)
        for tid in (1041, 1062):
            self.race(mid, tid)
        self.now += 21600
        self.close(mid)
        self.assertEqual(srv._pvp_player_state(PLAYER)["star"], 3)

    def test_season_window_is_stable_and_previous_rank_survives_close(self):
        first = self.call("GET", "pvp_config")[2]["current_season"]
        state = srv._pvp_player_state(PLAYER)
        state["rank"] = 12
        self.now += 10
        self.assertEqual(first, self.call("GET", "pvp_config")[2]["current_season"])
        self.now = first["end_time"]
        self.assertEqual(self.call("POST", "close_season", {})[2], {"rank": 25, "star": 0})
        old = self.call("GET", "season/" + str(first["id"]))[2]
        self.assertEqual(old["rank"], 12)
        self.assertEqual(old["end_time"], first["end_time"])

    def test_failed_write_rolls_back_and_retry_debits_once(self):
        srv._pvp_chips_state(PLAYER)["chips"] = 1000
        srv._pvp_state_save(force=True)
        before = Path(srv.PVP_STATE_PATH).read_bytes()
        with patch.object(srv.os, "replace", side_effect=OSError("simulated disk failure")):
            self.assertEqual(self.call("POST", "chips", {"use_chips": 300})[0], 503)
        self.assertEqual(srv._pvp_chips_for(PLAYER), 1000)
        self.assertEqual(Path(srv.PVP_STATE_PATH).read_bytes(), before)
        self.assertEqual(self.call("POST", "chips", {"use_chips": 300})[2], {"chips": 700})

    def test_concurrent_spending_cannot_overdraw(self):
        from concurrent.futures import ThreadPoolExecutor
        srv._pvp_chips_state(PLAYER)["chips"] = 100
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.call("POST", "chips", {"use_chips": 80})[0], range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(srv._pvp_chips_for(PLAYER), 20)

    def test_no_cross_player_match_access_or_invalid_auth_side_effects(self):
        mid = self.match()["id"]
        with patch.object(srv, "_ghost_caller", return_value="stranger"):
            self.assertEqual(self.call("GET", "matches/" + str(mid))[0], 404)
            self.assertEqual(self.close(mid)[0], 404)
        with patch.object(srv, "_ghost_caller", return_value=None):
            self.assertEqual(self.call("POST", "pvp_init", {})[0], 401)
            self.assertEqual(self.call("POST", "close_season", {})[0], 401)
        self.assertNotIn(None, srv._pvp_players)
        self.assertIsNone(srv.pick_dynamic("POST", BASE + "close_typo")[0])


    def test_zero_race_progress_sync_does_not_add_rewards(self):
        mid = self.match()["id"]
        payload = {"match_id": mid, "race_id": 0, "coin": 0, "gem": 0,
                   "special": 0, "reward_data": 20008}
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 200)
        self.assertEqual(self.call("POST", "increase_rewards", payload)[0], 200)
        result = self.call("GET", "matches/" + str(mid))[2]
        self.assertEqual(result["rewards"], [0, 0, 0])
        self.assertEqual(result["player1"]["reward_data"], 20008)

    def test_loss_rank_protection_matches_native_animation(self):
        for rank, star, expected in ((20, 1, (20, 1)), (15, 0, (15, 0)),
                                     (14, 0, (15, 2)), (0, 0, (0, 0))):
            with self.subTest(rank=rank):
                mid = srv._pvp_make_match([PLAYER, srv._pvp_bot_id()], bot=True)
                match = srv._pvp_matches[mid]
                match["results"][srv._pvp_bot_id()] = {
                    tid: {"score": srv._pvp_score_int(30000)} for tid in match["tracks"]}
                srv._pvp_player_state(PLAYER).update(rank=rank, star=star)
                self.now += 21600
                self.assertEqual(self.close(mid)[0], 200)
                info = self.call("GET", "player/" + PLAYER)[2]
                self.assertEqual((info["rank"], info["star"]), expected)

    def test_http_reward_and_close_contract(self):
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        with patch.object(srv, "LOG_PATH", str(Path(self.tmp.name) / "http.jsonl")):
            http = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            def request(method, endpoint, data=None):
                req = Request("http://127.0.0.1:%d%s%s" % (http.server_port, BASE, endpoint),
                              data=json.dumps(data).encode() if data is not None else None,
                              headers={"Content-Type": "application/json"}, method=method)
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status, json.load(response)
                except HTTPError as response:
                    return response.code, json.load(response)
            try:
                self.assertEqual(request("GET", "new_ranked")[0], 200)
                mid = request("GET", "matches")[1]["matches"][0]["id"]
                for tid in (1041, 1062):
                    self.assertEqual(request("POST", "start_race", {"match_id": mid,
                                     "track": tid, "golden_ticket": "False"})[0], 200)
                    status, race = request("POST", "race", {"match_id": mid, "track": tid,
                        "score": srv._pvp_score_int(30000), "timestamp": self.now})
                    self.assertEqual(status, 200)
                    self.assertEqual(request("POST", "increase_rewards", {"match_id": mid,
                        "race_id": race["race_id"], "coin": 100, "gem": 1, "special": 0,
                        "reward_data": 20008})[0], 200)
                self.assertEqual(request("GET", "matches/" + str(mid))[1]["rewards"], [200, 2, 0])
                self.now += 21600
                status, result = request("POST", "close", {"match_id": mid,
                    "create_new": "False", "ticket": "False", "outfit": 0, "param": 0})
                self.assertEqual(status, 200)
                self.assertEqual(result["last_match_winner"], PLAYER)
            finally:
                http.shutdown()
                http.server_close()
                thread.join(timeout=3)


    def test_match_slot_shows_wallet_plus_in_match_chips(self):
        """对局槽里的数字 = 入场时钱包余额 + 局内占赛道产的筹码。

        2026-10-05 用户确认的模型是「按赛道产币」（m03154）+「赢家夺走对面已有的
        筹码」（m04835），所以槽位不是从 0 起算，钱包也不会在开局被清空。
        """
        srv._pvp_chips_state(PLAYER)["chips"] = 114514
        srv._pvp_chips_state(srv._pvp_bot_id())["chips"] = 500
        match = self.match()
        self.assertEqual((match["player1"]["chips"], match["player2"]["chips"]),
                         (114514, 500))
        self.assertEqual(self.call("GET", "player/" + PLAYER)[2]["chips"], 114514)
        self.assertEqual(match["player1"]["tickets"], 3)

    def test_three_races_spend_three_tickets_and_only_bank_at_close(self):
        """三次跑图花三张票；局内筹码只是「显示」，钱包要到 close 才动。"""
        srv._pvp_chips_state(PLAYER)["chips"] = 114514
        mid = self.match()["id"]
        for count, tid in enumerate((1041, 1062, 1024), 1):
            self.race(mid, tid)
            self.now += 20
            match = self.call("GET", "matches/" + str(mid))[2]
            self.assertEqual(match["player1"]["tickets"], 3 - count)
            self.assertEqual(self.call("GET", "player/" + PLAYER)[2]["chips"], 114514)
        self.assertEqual(match["player1"]["chips"],
                         114514 + sum(srv._chips_at(t) for t in (60, 40, 20)))
        self.assertEqual(match["player2"]["chips"], 0)
        srv._pvp_state_save(force=True)
        srv._pvp_matches.clear()
        srv._pvp_state_load()
        restored = self.call("GET", "matches/" + str(mid))[2]
        self.assertEqual(restored["player1"]["tickets"], 0)
        self.assertEqual(restored["player1"]["chips"], match["player1"]["chips"])
        self.assertEqual(self.call("POST", "start_race", {"match_id": mid, "track": 1041,
                         "golden_ticket": "False"})[0], 409)

    def test_winner_takes_half_of_the_losers_in_match_chips_not_wallet(self):
        """掠夺的是**这一局里**输家占赛道产出的 (100-keep)%，不是他的钱包余额。

        用户 2026-10-05 纠正：「掠夺的是对局的…就是开赛道的生成中的筹码」。
        所以钱包里原有的钱一分不能动，只有这一局的产出会被分走一半。
        """
        keep = self.config["chips"]["match_loser_keeps_pct"]
        bot = srv._pvp_bot_id()
        srv._pvp_chips_state(PLAYER)["chips"] = 1000
        srv._pvp_chips_state(bot)["chips"] = 777          # 钱包余额：不许被按比例割走
        mid = self.match()["id"]
        m = srv._pvp_matches[mid]
        t0, t1, t2 = m["tracks"]
        m["results"] = {
            # 玩家三条都跑（40 s，慢）；人机只在 t0 上更快 ⇒ 玩家占 t1/t2 赢这一局
            PLAYER: {t: {"score": srv._pvp_score_int(40000)} for t in (t0, t1, t2)},
            bot: {t0: {"score": srv._pvp_score_int(30000)}},
        }
        m["owner_at"] = {t: self.now for t in (t0, t1, t2)}
        self.now += 21600
        per_track = srv._chips_at(21600)
        self.assertGreater(per_track, 0)
        self.assertEqual(self.close(mid)[0], 200)
        stolen = per_track * (100 - keep) // 100
        # 赢家 = 自己两条的产出 + 掠夺来的；输家 = 自己一条的产出 − 被掠走的
        self.assertEqual(srv._pvp_chips_for(PLAYER), 1000 + 2 * per_track + stolen)
        self.assertEqual(srv._pvp_chips_for(bot), 777 + per_track - stolen)
        # 旧实现会按钱包 777 割一半（-388），这条断言就是防它回来
        self.assertGreater(srv._pvp_chips_for(bot), 777 - per_track)
        self.close(mid)
        self.assertEqual(srv._pvp_chips_for(PLAYER), 1000 + 2 * per_track + stolen)
        self.assertEqual(srv._pvp_chips_for(bot), 777 + per_track - stolen)

    def test_wallet_accrues_from_owned_tracks(self):
        """每 per_track_seconds 秒、每条已解锁赛道产 1 枚；没有赛道就不产。"""
        self.config["chips"].update(per_track_seconds=3600)
        state = srv._pvp_chips_state(PLAYER)
        state.update(chips=100, tracks=[1041, 1062], ts=self.now, acc=0)
        self.assertEqual(self.call("GET", "player/" + PLAYER)[2]["chips"], 100)
        self.now += 7200                       # 2 条赛道 × 2 小时 = 4 枚
        self.assertEqual(self.call("GET", "player/" + PLAYER)[2]["chips"], 104)
        self.now += 1800                       # 再半小时 = 又 1 枚（余数留到下轮）
        self.assertEqual(self.call("GET", "player/" + PLAYER)[2]["chips"], 105)


    def test_abc_actual_client_string_tracks_spend_three_tickets(self):
        mid = self.match()["id"]
        for count, track in enumerate(("1041", "1062", "1024"), 1):
            self.assertEqual(self.call("POST", "start_race", {"match_id": mid,
                "track": track, "golden_ticket": "False"})[0], 200)
            self.assertEqual(self.call("POST", "race", {"match_id": mid,
                "track": track, "score": srv._pvp_score_int(30000), "timestamp": self.now})[0], 200)
            self.assertEqual(self.call("GET", "matches/" + str(mid))[2]["player1"]["tickets"], 3 - count)

    def test_season_rewards_have_nested_item_pairs(self):
        season = self.call("GET", "pvp_config")[2]["current_season"]
        self.assertTrue(season["rewards"])
        self.assertIn("rewards", season["rewards"][0])
        self.assertEqual([row["rank"] for row in season["rewards"]], list(range(26)))
        self.assertEqual(season["rewards"][1]["rewards"][0], {"item_id": 1, "amount": 500})
        # ★ 将来 WebUI 会直接生成这张表，所以两条硬约束必须由测试守住：
        #   1) rank 0..25 每一档都得有东西（客户端结算的是 index>=R 之和，缺档=白给）；
        #   2) 同一档里 (item_id, amount) 不许重复（写重=多发）。
        for row in season["rewards"]:
            with self.subTest(rank=row["rank"]):
                self.assertTrue(row["rewards"], "rank %d 没有任何奖励" % row["rank"])
        pairs = [(row["rank"], it["item_id"], it["amount"])
                 for row in season["rewards"] for it in row["rewards"]]
        self.assertEqual(len(pairs), len(set(pairs)), "季奖配置里有重复条目")

    def test_duplicate_season_reward_rows_are_deduped(self):
        """配置里复制粘贴写重一条时，服务端只发一份（并打印告警）。"""
        self.config["season"]["rewards"] = [
            {"rank": 1, "item_id": 1, "amount": 500},
            {"rank": 1, "item_id": 1, "amount": 500},      # 重复
            {"rank": 1, "item_id": 145, "amount": 220},
        ]
        row = self.call("GET", "pvp_config")[2]["current_season"]["rewards"][1]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["rewards"], [{"item_id": 1, "amount": 500},
                                         {"item_id": 145, "amount": 220}])

    def test_gamecfg_returns_bare_array_and_stable_device_tokens(self):
        """`GET /`（gamecfg）回裸 `[]`；`?action=register_device` 回 43 字符 base62 双 token。

        形状来自真实样本（work/trials-frontier/notes/real-server-samples.md §1/§2）。
        """
        handler, _ = srv.pick_dynamic("GET", "/")
        self.assertIs(handler, srv.h_gamecfg)
        status, _, body = handler("/", "product=101&portal=Google&version=7.9.4", b"", {})
        self.assertEqual((status, body), (200, []))

        q = "action=register_device&productid=101&devicetype=google&deviceuid=abc-123"
        first = srv.h_gamecfg("/", q, b"", {})[2]["device"]
        second = srv.h_gamecfg("/", q, b"", {})[2]["device"]
        self.assertEqual(first, second, "同一台设备必须拿到同一串 token")
        for value in first.values():
            self.assertEqual(len(value), 43)
            self.assertTrue(all(c.isalnum() for c in value), "必须是 base62")

    def test_client_without_credentials_keeps_the_account_identity(self):
        """同一台客户端登录过账号后，不带凭据的请求也归它名下。

        真机日志：7360 条请求里 1737 条没有 Authorization、1489 条只用我们的匿名票，
        于是 PVP/存档状态被劈成「账号槽 + 匿名槽」两半 —— 用户说的「时好时坏」。
        """
        tmp = Path(self.tmp.name)
        hdrs = {"X-TF-Client": "10.0.0.9"}
        with patch.object(srv.acct, "ACCOUNTS", str(tmp / "accounts.json")), \
                patch.object(srv.acct, "SESSIONS", str(tmp / "sessions.json")), \
                patch.object(srv.acct, "REMEMBER", str(tmp / "remember.json")), \
                patch.object(srv.acct, "BINDINGS", str(tmp / "bindings.json")):
            acc, err = srv.acct.register_account("tester", "pw123456")
            self.assertIsNone(err)
            auth = "Ubi_v1 t=" + base64.b64encode(b"tester:pw123456").decode()
            status, _, sess = srv.h_session("/v3/profiles/sessions", "",
                                            json.dumps({"rememberMe": True}).encode(),
                                            dict(hdrs, Authorization=auth))
            self.assertEqual(status, 200)
            self.assertEqual(sess["profileId"], acc["profileId"])
            # 不带任何凭据（真机常态）→ 仍然是同一个 profileId
            info, err = srv.acct.resolve_identity(dict(hdrs))
            self.assertIsNone(err)
            self.assertEqual(info["profileId"], acc["profileId"])
            # 另一台客户端没登录过，仍然是匿名槽
            other, _ = srv.acct.resolve_identity({"X-TF-Client": "10.0.0.99"})
            self.assertEqual(other["profileId"], srv.acct.ANON_PROFILE_ID)
            # ★ 长期凭据（rm_v1）的静默换会话也必须建立绑定：真机冷启动**第一条**
            #   会话就是这条路径，漏了它，紧随其后的设备请求照样拿到设备槽。
            fresh = {"X-TF-Client": "10.0.0.10",
                     "Authorization": "rm_v1 t=" + sess["rememberMeTicket"]}
            st2, _, sess2 = srv.h_session("/v3/profiles/sessions", "",
                                          json.dumps({"rememberMe": True}).encode(), fresh)
            self.assertEqual((st2, sess2["profileId"]), (200, acc["profileId"]))
            dev_auth = "UbiMobile_v1 t=" + base64.b64encode(
                b"c83d8341-b556-40d6-b806-eae792556571:t:0").decode()
            st3, _, sess3 = srv.h_session("/v3/profiles/sessions", b"{}", b"",
                                          dict(fresh, Authorization=dev_auth))
            self.assertEqual((st3, sess3["profileId"]), (200, acc["profileId"]))
            # 明确的口令错误不许被 IP 绑定洗白
            bad = "Ubi_v1 t=" + base64.b64encode(b"tester:wrong").decode()
            _, err3 = srv.acct.resolve_identity(dict(hdrs, Authorization=bad))
            self.assertEqual(err3, "invalid-credentials")

    def test_app_configuration_sandbox_url_follows_request_host(self):
        """`/v1/applications/<appid>/configuration` 的 sandbox url 必须按 Host 回显。

        那个 url 就是客户端 `setserverAddress` 的基址：写死 127.0.0.1 会让 Java 侧
        （DLC/内购）永远连手机自己，必须靠 adb reverse 才能启动 —— 2026-10-05 的
        「碉堡四面板转圈」就是这条导致的。
        """
        handler, _ = srv.pick_dynamic("GET", "/v1/applications/abc/configuration")
        self.assertIs(handler, srv.h_app_configuration)
        for host in ("192.168.5.2:8000", "127.0.0.1:8000"):
            body = handler("/v1/applications/abc/configuration", "", b"", {"Host": host})[2]
            box = body["configuration"]["sandboxes"]["triag_an_lnch61_a_ws"]
            self.assertEqual(box["friendlyName"], "triag_an_lnch61_a_ws")
            self.assertEqual(box["url"], "http://%s/" % host)

    def test_wallet_does_not_grow_without_a_settled_match(self):
        """默认配置下，钱包不能因为「有已解锁赛道」就自己长大。

        真机反馈原话：「都没结束。都没结算哪来的筹码」。默认 `per_track_seconds = 0`，
        筹码只从「占住赛道 → 整局到期 close」来（`_pvp_bank_match_chips`）。
        """
        self.assertEqual(self.config["chips"]["per_track_seconds"], 0)
        state = srv._pvp_chips_state(PLAYER)
        state.update(chips=100, tracks=[1041, 1062, 1023], ts=self.now - 86400, acc=0)
        self.assertEqual(self.call("GET", "player/" + PLAYER)[2]["chips"], 100)

    def test_second_new_ranked_opens_a_second_concurrent_match(self):
        """再点一次「全新对决」要**真开一条新对局**，不是把旧的原样回给他。

        真机症状（2026-10-05）：打了一局后再点，matches 回的仍是同一 match id，
        看起来就是「新对局覆盖了上一个」。
        """
        first = self.match()["id"]
        self.call("GET", "new_ranked")
        matches = self.call("GET", "matches")[2]["matches"]
        self.assertEqual(len(matches), 2)
        self.assertNotEqual(matches[0]["id"], first, "新开的那条要排在最前面")
        self.assertEqual(matches[1]["id"], first)
        # 免费名额之外要花黄金门票；没票就停在免费名额上
        slots = self.config["matchmaking"]["ranked_match_slots"]
        srv._pvp_player_state(PLAYER)["golden_ticket"] = 0
        for _ in range(slots + 2):
            self.call("GET", "new_ranked")
            self.call("GET", "matches")
        ids = [m["id"] for m in self.call("GET", "matches")[2]["matches"]]
        self.assertEqual(len(ids), slots, "免费名额 = ranked_match_slots，没金票到此为止")
        self.assertEqual(len(set(ids)), slots)

    def test_extra_match_beyond_slots_costs_a_golden_ticket(self):
        """第 4 条起的新对局收 1 张黄金门票，且同一张「新开」意图只收一次。"""
        slots = self.config["matchmaking"]["ranked_match_slots"]
        self.assertEqual(self.config["matchmaking"]["additional_match_cost"], 1)
        srv._pvp_player_state(PLAYER)["golden_ticket"] = 0
        for _ in range(slots + 1):
            self.call("GET", "new_ranked")
            self.call("GET", "matches")
        self.assertEqual(len(self.call("GET", "matches")[2]["matches"]), slots)
        srv._pvp_player_state(PLAYER)["golden_ticket"] = 2
        self.call("GET", "new_ranked")
        self.assertEqual(len(self.call("GET", "matches")[2]["matches"]), slots + 1)
        self.assertEqual(srv._pvp_player_state(PLAYER)["golden_ticket"], 1)
        # 再轮询几次（new 标记已清）不能重复收费
        for _ in range(3):
            self.call("GET", "matches")
        self.assertEqual(len(self.call("GET", "matches")[2]["matches"]), slots + 1)
        self.assertEqual(srv._pvp_player_state(PLAYER)["golden_ticket"], 1)
        # 客户端拿到的 pvp_match_settings 必须和服务端同一份口径
        settings = self.call("GET", "pvp_config")[2]["pvp_match_settings"]
        self.assertEqual(settings["ranked_match_slots"], slots)
        self.assertEqual(settings["additional_match_cost"], 1)
        self.assertEqual(settings["ranked_match_limit"],
                         self.config["matchmaking"]["ranked_match_limit"])

    def test_repeated_or_bogus_track_ids_do_not_add_production_lines(self):
        """`pvp_init` 的 tracks 串必须去重、并滤掉明显不是赛道的 id。

        真机 body 实测 `…,1097,1097,…` 有重复，且混着 `1,2,4`；重复一条就多一条
        产币线（筹码凭空变多）。
        """
        self.call("POST", "pvp_init", {"tracks": "1041,1041,1,2,4,1062,1097,1097"})
        self.assertEqual(srv._pvp_chips_state(PLAYER)["tracks"], [1041, 1062, 1097])


if __name__ == "__main__":
    unittest.main()
