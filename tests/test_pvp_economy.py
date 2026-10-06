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
        # 存档也指向临时目录：`_pvp_outfit_of()` 要读 `content.profile.outfit`，
        # 不隔离的话就会去读真机存档（测试会随真数据飘）。
        self.save_dir = Path(self.tmp.name) / "saves"
        self.save_dir.mkdir()
        for p in (patch.object(srv, "PVP_STATE_PATH", str(Path(self.tmp.name) / "pvp.json")),
                  patch.object(srv.acct, "SAVE_DIR", str(self.save_dir)),
                  patch.object(srv, "tf_config", return_value=config),
                  patch.object(srv, "_ghost_caller", return_value=PLAYER),
                  patch.object(srv, "_pvp_real_players", return_value=set()),
                  patch.object(srv, "_pvp_online_others", return_value=[]),
                  patch.object(srv.time, "time", side_effect=lambda: self.now)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: srv._pvp_dirty.__setitem__(0, False))

    def write_save(self, pid, outfit):
        """在临时存档目录里造一份只带 `content.profile.outfit` 的存档。"""
        d = self.save_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.json").write_text(
            json.dumps({"content": {"profile": {"outfit": outfit}}}), encoding="utf-8")

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

    def test_race_records_the_clients_own_bike_and_outfit(self):
        # 客户端在 `pvp_matches/v1/race` 里报自己的车身字节与骑手外观
        # （模板 `{"…","outfit": %d,"bike_data": %d}` @0xb86637）；以前我们把配置里的
        # `matchmaking.bike_id` 当车身发回去，于是对手看到的永远是那辆默认车。
        mid = self.match()["id"]
        tid = 1041
        self.assertEqual(self.call("POST", "start_race", {"match_id": mid, "track": tid,
                         "golden_ticket": "False"})[0], 200)
        self.assertEqual(self.call("POST", "race", {"match_id": mid, "track": tid,
                         "score": srv._pvp_score_int(30000), "bike_data": 200,
                         "outfit": 0x121212, "timestamp": self.now})[0], 200)
        track = [t for t in srv._pvp_match_json(PLAYER, mid)["tracks"] if t["track"] == tid][0]
        self.assertEqual(track["result_p1"]["bike_data"], 200)
        self.assertEqual(track["result_p1"]["outfit"], 0x121212)

    def test_junk_bike_and_outfit_fall_back(self):
        mid = self.match()["id"]
        tid = 1062
        self.assertEqual(self.call("POST", "start_race", {"match_id": mid, "track": tid,
                         "golden_ticket": "False"})[0], 200)
        self.assertEqual(self.call("POST", "race", {"match_id": mid, "track": tid,
                         "score": srv._pvp_score_int(31000), "bike_data": "x",
                         "outfit": -5, "timestamp": self.now})[0], 200)
        track = [t for t in srv._pvp_match_json(PLAYER, mid)["tracks"] if t["track"] == tid][0]
        self.assertNotIn("outfit", track["result_p1"])
        self.assertEqual(track["result_p1"]["bike_data"],
                         srv.cfg_int("matchmaking", "bike_id", default=1))

    def test_match_slots_carry_the_owners_real_outfit(self):
        # 碉堡界面上两侧的骑手立绘读的是 player1/player2 槽里的 `outfit`
        # （见 `_pvp_outfit_of` 的注释）；发 0 会把对手画成默认那套。
        self.write_save(PLAYER, 0x121212)
        mid = self.match()["id"]
        slots = srv._pvp_match_json(PLAYER, mid)
        self.assertEqual(slots["player1"]["outfit"], 0x121212)
        # 对手（人机兜底档）没有存档 -> 0 号部件，也就是客户端本来就画的那套。
        self.assertEqual(slots["player2"]["outfit"], 0)

    def test_junk_outfit_in_save_is_not_forwarded(self):
        self.write_save(PLAYER, "x")
        mid = self.match()["id"]
        self.assertEqual(srv._pvp_match_json(PLAYER, mid)["player1"]["outfit"], 0)

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


    def test_match_slots_start_at_zero_chips(self):
        """对局槽里的数字从 0 起算，**不带入**局外钱包余额。

        用户 2026-10-06 纠正（m01903）：「局外筹码是局外筹码。局内筹码是0，
        只有赢得一条赛道，那个赛道开始产出筹码才会增加。怎么可能是直接从玩家
        局外筹码同步。」——客户端画的数字 = `chip_base + 局内产出的筹码`，
        而 `chip_base` 恒为 0。
        老实现把钱包余额灌进 `chip_base`，于是对手头像下面直接显示你的存款
        （真机：ccb 115313 / 华为 999999）。
        """
        srv._pvp_chips_state(PLAYER)["chips"] = 114514
        srv._pvp_chips_state(srv._pvp_bot_id())["chips"] = 500
        match = self.match()
        self.assertEqual((match["player1"]["chips"], match["player2"]["chips"]),
                         (0, 0))
        # 局外钱包一分不动，`pvp_matches/v1/player/<pid>` 仍报真余额。
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
                         sum(srv._chips_at(t) for t in (60, 40, 20)))
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

    def test_weekly_config_hands_the_client_a_real_leaderboard_id(self):
        """`week_settings.week_leaderboard` 必须 >= 1 —— 发 0 客户端就认定「本模式没有榜」。

        证据（libTrialsGo.so）：`WeeklyChallengeManager::hasLeaderboard` @0x006316fc、
        `getLeaderboard` @0x00634500、`getPlayerRankPercent` @0x00634548 开头都是
        `id < 1 → 空 / -1.0f`，而 `getPlayerTrophyType(-1.0f)` = 5 = wood（最低奖杯）；
        id→榜名由 `OnlineLeaderboards::getLeaderboardName` @0x00509604 决定
        （0→global_stats、0x10000→donkey、0x100000→crazy、bits17-19→event_stats<N>、其余→track<id>）。
        """
        path = "/public/liveevents/v1/weekly_track_system/config/0"
        settings = srv.h_liveevents_config(path, "", b"", {})[2]["week_settings"]
        # 默认 0 = 自动用本周赛道 ⇒ 客户端会去拉 ranking/track1041（那张榜上有人，也有自己）
        self.assertEqual(settings["week_leaderboard"], self.config["weekly"]["track_id"])
        self.assertGreaterEqual(settings["week_leaderboard"], 1)
        # 显式配了就照发（0x20000 = event_stats1，留给以后换活动榜）
        self.config["weekly"]["leaderboard_id"] = 0x20000
        self.assertEqual(srv.h_liveevents_config(path, "", b"", {})[2]
                         ["week_settings"]["week_leaderboard"], 0x20000)

    def test_global_crazy_is_aggregated_like_the_other_global_boards(self):
        """第三个总榜 `global_stats_crazy` 走聚合，而不是被当成赛道榜（上报还会吃 400）。

        `getLeaderboardName` 的 id 表里 `0x100000 → "global_stats_crazy"`，与
        `0 → global_stats`、`0x10000 → global_stats_donkey` 并列 —— 之前这个集合里
        少一个 crazy，于是它的成绩上报会命中 `h_result_stats` 的
        `400 {"error": "invalid-track"}`。
        """
        self.assertIn("global_stats_crazy", srv.GLOBAL_LEADERBOARDS)
        db = {"track1041": {PLAYER: {"player": PLAYER, "drivetime": 24000, "data": 0,
                                     "upgrades": 0, "submittime": 0, "extradata": 0,
                                     "updated": 0, "score_value": 7}}}
        with patch.object(srv, "LEADERBOARD_PATH", str(Path(self.tmp.name) / "lb.json")), \
                patch.object(srv, "_OPPONENT_CACHE", ({}, {})):
            srv._save_leaderboards(db)
            rows, total = srv._stored_entries("global_stats_crazy", keep_total=True)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["player"], PLAYER)
        self.assertEqual(rows[0]["rank"], 1)
        # global_score 由单赛道 score_value 聚合出来，不生成任何额外赛道记录
        self.assertEqual(rows[0]["global_score"], 7.0)

    def test_basic_info_flips_the_week_to_joined_once_the_player_is_on_the_board(self):
        """榜上有名 ⇒ `(last_participated_week, lb)` 报成"本周 + 本周榜 id"。

        证据（libTrialsGo.so）：`WeeklyChallengeManager::updateStateEv` @0x00631000
        只有在 `lb != 0` 时才给出 state 3/4，而 state 2 经 `changeSubState` @0x007b125c
        映射到 UI 3 = `loadJoinState` —— 就是真机上那屏「加入午夜杯！」。
        恒发 lb=0 的后果：按下按钮直接开赛，跑完回到同一屏，循环（2026-10-05 真机复现）。
        """
        path = "/public/liveevents/v1/weekly_track_system/basic_info"
        pid = srv._caller_profile({})
        with patch.object(srv, "LEADERBOARD_PATH", str(Path(self.tmp.name) / "lb.json")), \
                patch.object(srv, "_OPPONENT_CACHE", ({}, {})):
            # ① 还没上榜：原样回客户端报上来的值
            srv._WEEKLY_LAST[pid] = (2961, 0)
            payload = srv.h_liveevents_basic_info(path, "", b"", {})[2]
            self.assertEqual(payload["last_participated_week"], 2961)
            self.assertEqual(payload["last_participated_week_lb"], 0)
            # ② 榜上有名（本周赛道榜里有他）：报成本周 + 本周榜 id
            srv._save_leaderboards({"track1041": {pid: {"player": pid, "drivetime": 24000}}})
            payload = srv.h_liveevents_basic_info(path, "", b"", {})[2]
            self.assertEqual(payload["last_participated_week"], srv._week_index()[1])
            self.assertEqual(payload["last_participated_week_lb"],
                             srv._weekly_leaderboard_id())
            self.assertGreaterEqual(payload["last_participated_week_lb"], 1)

    def test_find_opponent_returns_a_pid_and_his_ghost_id(self):
        """`find_opponent` 必须回 pid + 该 pid 在本周赛道上的幽灵 contentId。

        真机日志 2026-10-05 23:27：回显示名 "TangoPro" 后客户端拿它去查
        `stats/track1041?players=TangoPro`（服务端按 profileId 存行 ⇒ 永远查不到），
        并以 ~30 次/秒死循环重试 `find_opponent` + `stats` + `ghost/0/payload`(404)。
        """
        pid = "55555555-5555-5555-5555-555555555555"
        with patch.object(srv, "_OPPONENT_CACHE", (
                {pid: {"track1041": {"player": pid, "drivetime": 25000}}},
                {pid: {"track1041": 42}})):
            path = "/public/liveevents/v1/weekly_track_system/find_opponent"
            payload = srv.h_liveevents_find_opponent(path, "", b"", {})[2]
        self.assertEqual(payload["opponent"], pid)
        self.assertEqual(payload["replay_id"], 42)

    def test_weekly_fake_field_fills_the_board_without_persisting(self):
        """合成对手：进榜视图、加大 playerCount、不落盘、不进总榜、同周恒定。

        ★ 动机：客户端用「名次 / playerCount」算百分位（`getPlayerRankPercent` @0x00634548），
          榜上只有 3 行时最好也只能显示「前 34%」——"进全球 1%"在物理上不可能。
        """
        self.config["weekly"].update(fake_field=40, fake_field_fast_pct=3,
                                     fake_field_slow_pct=25, fake_field_base_ms=0)
        with patch.object(srv, "LEADERBOARD_PATH", str(Path(self.tmp.name) / "lb.json")), \
                patch.object(srv, "_OPPONENT_CACHE", ({}, {})), \
                patch.object(srv, "_WEEKLY_FAKE_CACHE", {"key": None, "rows": {}}), \
                patch.object(srv, "_WEEKLY_FAKE_PIDS", set()), \
                patch.object(srv, "_WEEKLY_FAKE_NAMES", {}):
            srv._save_leaderboards({"track1041": {PLAYER: {"player": PLAYER,
                                                           "drivetime": 24404}}})
            first = srv._weekly_fake_field()
            second = srv._weekly_fake_field()
            self.assertEqual(len(first), len(second))
            self.assertEqual(first, second, "同一周内合成的行必须完全一致")
            board = srv._load_ranked_boards()["track1041"]
            self.assertEqual(len(board), 41)                  # 1 真实 + 40 合成
            self.assertNotIn(PLAYER, srv._WEEKLY_FAKE_PIDS)
            # 不落盘：磁盘上永远只有真实那一行
            self.assertEqual(len(srv._load_leaderboards()["track1041"]), 1)
            # 合成行不进总榜（那是碉堡的天梯）
            self.assertEqual([r["player"] for r in srv._aggregate_global_entries()], [PLAYER])
            # 时间以基准（这里没有内置幽灵 ⇒ 30000ms）为轴：往快 3%、往慢 25%
            rows_for_board = first["track1041"]
            self.assertEqual(len(rows_for_board), 40)
            times = sorted(r["drivetime"] for r in rows_for_board.values())
            self.assertGreaterEqual(times[0], 30000 * 0.97 - 1)
            self.assertLessEqual(times[-1], 30000 * 1.25 + 1)
            self.assertEqual(len({r["player"] for r in rows_for_board.values()}), 40)
            self.assertEqual(len(set(srv._WEEKLY_FAKE_NAMES.values())), 40)
            # ★ 关键：最快的合成行不会比基准快太多 —— 否则玩家永远够不到全球 1%
            #   （用户 2026-10-05：「改一下排行记录，我跑不到 22 秒内」）。
            self.assertGreaterEqual(times[0], 30000 * 0.95)
            # 显式写死基准也要生效
            self.config["weekly"]["fake_field_base_ms"] = 20000
            explicit = srv._weekly_fake_field()["track1041"]
            self.assertGreater(min(r["drivetime"] for r in explicit.values()), 19000)
            self.assertLess(min(r["drivetime"] for r in explicit.values()), 20001)

    def test_weekly_attempts_are_server_authoritative(self):
        """每周次数由服务端扣：start_race 扣一次、skip_cooldown 补满、refill 加次数。

        客户端会用它算「2/3 次机会」；次数用完 basic_info 回 0 + last_attempt_time，
        冷却**时长**在 config 的 global_cooldown_time。
        """
        base = "/public/liveevents/v1/weekly_track_system/"
        pid = srv._caller_profile({})
        with patch.object(srv, "_WEEKLY_ATTEMPTS", {}):
            left = lambda: srv.h_liveevents_basic_info(base + "basic_info", "", b"", {})[2][
                "left_retry_times"]
            self.assertEqual(left(), 3)
            for expect in (2, 1, 0):
                srv.h_liveevents_accept(base + "start_race", "", b'{"gem":false}', {})
                self.assertEqual(left(), expect)
            # 次数用完再 start_race 不该扣成负数；last_attempt_time 记下了最后一次
            srv.h_liveevents_accept(base + "start_race", "", b"{}", {})
            payload = srv.h_liveevents_basic_info(base + "basic_info", "", b"", {})[2]
            self.assertEqual(payload["left_retry_times"], 0)
            self.assertEqual(payload["last_attempt_time"], self.now)
            self.assertEqual(srv._weekly_attempt_state(pid)[1], 3)
            # 宝石跳冷却 = 次数补满
            srv.h_liveevents_accept(base + "skip_cooldown", "", b'{"gem":true}', {})
            self.assertEqual(left(), 3)
            # 补次数
            srv.h_liveevents_accept(base + "refill_retry_count", "",
                                    json.dumps({"retry_times": "2"}).encode(), {})
            self.assertEqual(left(), 5)
            config = srv.h_liveevents_config(base + "config/0", "", b"", {})[2]["week_settings"]
            self.assertEqual(config["global_retry_count"], 3)
            self.assertEqual(config["global_cooldown_time"], 3600)

    def test_appcfg_never_hands_out_a_loopback_base(self):
        """`sandboxes[].url` 绝不回环 —— 否则 Java/DLC + Ubi SDK 全被钉在 127.0.0.1。

        用户 2026-10-05 的原话："为啥还要 adb 转发，插线可不行啊"：
        只要有一次 appcfg 是从回环进来的，客户端就会一直用 127.0.0.1（`libplayground.so`
        里那个写死的 `http://127.0.0.1:8000/{version}` 更是没得改），于是必须插线。
        """
        path = "/v1/applications/1c91448e-c62e-45ec-b97b-898dc967f2c1/configuration"
        self.config["appcfg"]["public_host"] = "10.0.0.7:8000"
        url = srv.h_app_configuration(path, "", b"", {"Host": "127.0.0.1:8000"})[2][
            "configuration"]["sandboxes"]["triag_an_lnch61_a_ws"]["url"]
        self.assertEqual(url, "http://10.0.0.7:8000/")
        for bad in ("localhost:8000", "[::1]:8000", "0.0.0.0:8000"):
            with self.subTest(host=bad):
                self.assertNotIn("127.0.0.1", srv.h_app_configuration(
                    path, "", b"", {"Host": bad})[2]["configuration"]["sandboxes"][
                        "triag_an_lnch61_a_ws"]["url"])
        # 非回环照旧回显（局域网自举：客户端怎么找到我们，就继续用它）
        self.config["appcfg"]["public_host"] = ""
        self.assertEqual(srv.h_app_configuration(path, "", b"", {"Host": "192.168.5.2:8000"})[2]
                         ["configuration"]["sandboxes"]["triag_an_lnch61_a_ws"]["url"],
                         "http://192.168.5.2:8000/")

    def test_week_offset_simulates_the_week_rollover(self):
        """`weekly.week_offset = 1` = 模拟翻周：报出去的是**上一周**，好走结算/敲奖杯。

        客户端 `updateStateEv` 的 `w9 != w10 && lb > 0 → state 4` 就是"上一周结束了"，
        所以周号必须取**榜行 `updated` 反推的那一周**，而不是当前周。
        """
        path = "/public/liveevents/v1/weekly_track_system/basic_info"
        pid = srv._caller_profile({})
        self.config["weekly"]["week_offset"] = 0
        with patch.object(srv, "LEADERBOARD_PATH", str(Path(self.tmp.name) / "lb.json")), \
                patch.object(srv, "_OPPONENT_CACHE", ({}, {})), \
                patch.object(srv, "_WEEKLY_FAKE_CACHE", {"key": None, "rows": {}}), \
                patch.object(srv, "_WEEKLY_FAKE_PIDS", set()), \
                patch.object(srv, "_WEEKLY_FAKE_NAMES", {}):
            srv._save_leaderboards({"track1041": {pid: {"player": pid, "drivetime": 24000,
                                                        "updated": self.now}}})
            same_week = srv.h_liveevents_basic_info(path, "", b"", {})[2]
            self.assertEqual(same_week["last_participated_week"], same_week["week_index"])
            self.config["weekly"]["week_offset"] = 1          # 服务器"翻到下一周"
            rolled = srv.h_liveevents_basic_info(path, "", b"", {})[2]
            self.assertEqual(rolled["week_index"], same_week["week_index"] + 1)
            self.assertEqual(rolled["week_start"],
                             same_week["week_start"] + 7 * 24 * 3600)
            self.assertEqual(rolled["last_participated_week"], same_week["week_index"])
            self.assertNotEqual(rolled["last_participated_week"], rolled["week_index"])
            self.assertEqual(rolled["last_participated_week_lb"],
                             srv._weekly_leaderboard_id())
            self.assertGreaterEqual(rolled["last_participated_week_lb"], 1)

    def test_config_can_be_asked_for_a_previous_week(self):
        """`config/<week>` 要的是那一周的配置 —— 翻周后客户端会要上一周。

        真机 2026-10-05 23:56（`week_offset=1` 模拟翻周）：客户端反复
        `GET …/config/2961`（上一周），我们一律回本周 2962 ⇒ 它判定"配置不属于当前周"，
        卡在「查看进度…」并每秒重试好几次。
        """
        path = "/public/liveevents/v1/weekly_track_system/config/%d"
        cur = srv.h_liveevents_config(path % 0, "", b"", {})[2]
        self.assertEqual(cur["week_index"], srv._week_index()[1])
        prev = srv.h_liveevents_config(path % (cur["week_index"] - 1), "", b"", {})[2]
        self.assertEqual(prev["week_index"], cur["week_index"] - 1)
        self.assertEqual(prev["week_settings"]["week_start"],
                         (cur["week_index"] - 1) * 7 * 24 * 3600)
        self.assertEqual(prev["week_settings"]["week_end"],
                         prev["week_settings"]["week_start"] + 7 * 24 * 3600)
        # 榜 id / 赛道 这些"本周挑战"的内容不变（客户端只用它渲染那一周的榜）
        self.assertEqual(prev["week_settings"]["week_leaderboard"],
                         srv._weekly_leaderboard_id())

    def test_shipped_config_file_is_valid_json_with_the_weekly_keys(self):
        """`server/data/tf_config.json` 必须是合法 JSON —— 否则服务器**静默**退回内置默认值。

        2026-10-05 踩到过：往 `weekly._note` 里写了一个 ASCII 双引号，整份配置解析失败，
        `tf_config()` 打了句 `[cfg] … 读不了，先用内置默认值` 就继续跑 —— 表现是
        `fake_field` 变回 0（榜上又只有 3 个人）、`week_offset` 变回 0，查半天才发现。
        """
        path = Path(__file__).resolve().parents[1] / "server" / "data" / "tf_config.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key in ("fake_field", "fake_field_fast_pct", "fake_field_slow_pct",
                    "fake_field_base_ms", "leaderboard_id", "week_offset",
                    "left_retry_times", "cooldown_seconds", "track_id"):
            with self.subTest(key=key):
                self.assertIn(key, raw["weekly"])
        self.assertIn("public_host", raw["appcfg"])
        self.assertIsInstance(raw["weekly"]["fake_field"], int)

    def test_reward_config_rotates_the_pool_every_time(self):
        """奖励池必须**每次下发都换**：客户端的 `rand()` 不播种，池子不变就永远是同一件。

        真机 bug（User m01488）：「最高奖励也只有一个地图，我领取了两次是同一个地图」。
        `getRewardItemForSlot @0x00635880`：`bl rand` → `w8 = rand() % (size/0x44)`
        —— 挑池内那一件用的是客户端自己的 rand()，第一次恒为 1804289383 ⇒ `% 23 = 11`。
        我们能控制的只有"给哪个池子"（`Reward_{k*5+i+1}`）。
        """
        path = "/public/liveevents/v1/weekly_track_system/reward_config/2961"
        with patch.object(srv, "_REWARD_ROTATION", {}):
            first = srv.h_liveevents_reward_config(path, "", b"", {})[2]
            second = srv.h_liveevents_reward_config(path, "", b"", {})[2]
            third = srv.h_liveevents_reward_config(path, "", b"", {})[2]
        self.assertEqual(set(first), set(srv._WEEKLY_TROPHIES))
        for name in srv._WEEKLY_TROPHIES:
            for body in (first, second, third):
                self.assertEqual(len(body[name]["reward"]), 1)
                self.assertEqual(body[name]["reward"], body[name]["n"])   # 两个等长数组
                self.assertTrue(1 <= body[name]["reward"][0] <= 15)
            # 同一个奖杯连续三次必须落到**三个不同池子**上
            self.assertEqual(len({first[name]["reward"][0], second[name]["reward"][0],
                                  third[name]["reward"][0]}), 3)

    def test_reward_slots_can_grant_several_items_at_once(self):
        """`weekly.reward_slots` 让一档一次给多件（每个槽 = 一个池子的一件）。"""
        self.config["weekly"]["reward_slots"] = 3
        path = "/public/liveevents/v1/weekly_track_system/reward_config/2961"
        with patch.object(srv, "_REWARD_ROTATION", {}):
            body = srv.h_liveevents_reward_config(path, "", b"", {})[2]
        for name in srv._WEEKLY_TROPHIES:
            ids = body[name]["reward"]
            self.assertEqual(len(ids), 3)
            self.assertEqual(len(set(ids)), 3, "三个槽应该是三个不同池子")
            self.assertEqual(body[name]["n"], ids)

    def test_reward_ids_can_remap_what_a_tier_hands_out(self):
        """`weekly.reward_ids` 可以按档位换池子（客户端本地表的**内容**改不了，只能换池子）。

        用户（m01552）问「最高奖励就一个地图？没有喷漆、蓝图啥的？」——
        `/conf/wts_rewards.txt` 里 15 个池子只有 赛道/碎片、服装、整台车×2、宝石/改件/金币/黄金票，
        **没有喷漆/蓝图/皮肤**；能调整的只有"哪一档给哪个池子"。
        """
        self.config["weekly"]["reward_ids"] = {"platinum": [3, 8, 13]}
        path = "/public/liveevents/v1/weekly_track_system/reward_config/2961"
        with patch.object(srv, "_REWARD_ROTATION", {}):
            body = srv.h_liveevents_reward_config(path, "", b"", {})[2]
        self.assertIn(body["platinum"]["reward"][0], (3, 8, 13))
        # 其它档位不受影响，仍按内置规则
        self.assertIn(body["gold"]["reward"][0], (2, 7, 12))
        # 非法值被忽略 → 回退内置规则
        self.config["weekly"]["reward_ids"] = {"platinum": [0, 99, "x"]}
        with patch.object(srv, "_REWARD_ROTATION", {}):
            body = srv.h_liveevents_reward_config(path, "", b"", {})[2]
        self.assertIn(body["platinum"]["reward"][0], (1, 6, 11))

    def test_reward_pools_reference_and_config_stay_in_sync(self):
        """`server/data/wts_rewards.json`（WebUI 读它渲染池子内容）与配置必须自洽。

        · 15 个池子 `Reward_1..15` 都在；
        · `tiers` 把五档映射到 `{i+1, i+6, i+11}`（= 客户端本地表 3 套方案的排布）；
        · 配置里 `reward_ids` 写的池子必须真实存在、`reward_slots` 在 1..3；
        · 内置规则（不配 `reward_ids` 时）第 i 档 = `Reward_{i+1}`。
        """
        path = Path(__file__).resolve().parents[1] / "server" / "data" / "wts_rewards.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        pools = data["pools"]
        self.assertEqual(sorted(pools, key=lambda k: int(k.rsplit("_", 1)[-1])),
                         ["Reward_%d" % i for i in range(1, 16)])
        for i, name in enumerate(srv._WEEKLY_TROPHIES):
            with self.subTest(tier=name):
                self.assertEqual(data["tiers"][name], [i + 1, i + 6, i + 11])
                self.assertEqual(srv._reward_pool_ids(name, i, 0, 1), [i + 1])
                self.assertTrue(pools["Reward_%d" % (i + 1)], "池子不能是空的")
                for item in pools["Reward_%d" % (i + 1)]:
                    self.assertIsInstance(item["item_id"], int)
                    self.assertIsInstance(item["amount"], int)
        cfg_path = Path(__file__).resolve().parents[1] / "server" / "data" / "tf_config.json"
        weekly = json.loads(cfg_path.read_text(encoding="utf-8"))["weekly"]
        self.assertTrue(1 <= weekly["reward_slots"] <= 8)
        for tier, ids in (weekly["reward_ids"] or {}).items():
            with self.subTest(tier=tier):
                self.assertIn(tier, srv._WEEKLY_TROPHIES)
                self.assertTrue(ids)
                for pool_id in ids:
                    self.assertIn("Reward_%d" % pool_id, pools)
        # ★ 三套方案的差异表（WebUI 要用它判断"轮换到底有没有区别"）：
        #   真机事实：bronze/wood 的三套**逐条一样**，platinum/gold/silver 才有区别。
        diff = data["variant_diff"]
        for tier in srv._WEEKLY_TROPHIES:
            with self.subTest(tier=tier):
                self.assertIn(tier, diff)
                self.assertEqual(set(diff[tier]["pools"]),
                                 {"Reward_%d" % n for n in data["tiers"][tier]})
        self.assertTrue(diff["bronze"]["identical"])
        self.assertTrue(diff["wood"]["identical"])
        self.assertFalse(diff["platinum"]["identical"])
        self.assertFalse(diff["gold"]["identical"])
        self.assertTrue(diff["platinum"]["pools"]["Reward_1"]["only_this"],
                        "platinum 第一套应当有独有赛道")

    def test_reward_slots_are_clamped_to_eight(self):
        """槽数上限 8（每槽 = 一个池子的一件）；超了夹回、小的夹到 1。

        ★ 只能靠"多给几个槽"加量：每件的**数量**（20 宝石 / 25000 金币 / 车×2）写死在客户端
          的 `ItemAmount` 里，wire 上 pair 的第二个数也不是数量 —— `getRewardItemForSlot`
          @`0x00635880` 里它唯一一次被用是 `0x00635b80 lsr x3, x20, #0x20`（当"本地查不到时的
          后备池号"）。想要每件更多宝石只能多叠几个宝石池的槽。
        """
        path = "/public/liveevents/v1/weekly_track_system/reward_config/2961"
        for want, expect in ((99, 8), (8, 8), (1, 1), (0, 1)):
            with self.subTest(want=want):
                self.config["weekly"]["reward_slots"] = want
                with patch.object(srv, "_REWARD_ROTATION", {}):
                    body = srv.h_liveevents_reward_config(path, "", b"", {})[2]
                for name in srv._WEEKLY_TROPHIES:
                    self.assertEqual(len(body[name]["reward"]), expect)
                    self.assertEqual(len(body[name]["n"]), expect)

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
        """`/v1/applications/<appid>/configuration` 的 sandbox url 按 Host 回显。

        那个 url 就是客户端 `setserverAddress` 的基址：写死 127.0.0.1 会让 Java 侧
        （DLC/内购）永远连手机自己，必须靠 adb reverse 才能启动 —— 2026-10-05 的
        「碉堡四面板转圈」就是这条导致的。
        ★ 回环 Host 不回环（换成局域网 IP）见 test_appcfg_never_hands_out_a_loopback_base。
        """
        handler, _ = srv.pick_dynamic("GET", "/v1/applications/abc/configuration")
        self.assertIs(handler, srv.h_app_configuration)
        for host in ("192.168.5.2:8000", "10.1.2.3:9000"):
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


class PlayerLevelAndNameTest(unittest.TestCase):
    """云端进度摘要里的 player_level，以及「榜上别人看到你叫什么」。

    两件事都是真机上暴露出来的（m01054 等级变成 1、m01172 榜单把 ccb@ccb.com
    显示成 Player53eb），而且都很容易在重构时悄悄退化，所以钉住契约。
    """

    PID = "53ebbd18-818e-5c2c-a865-773262f736e5"
    ANON = "11111111-1111-1111-1111-111111111111"
    BOT = "44444444-4444-4444-4444-444444444444"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.accounts = root / "accounts.json"
        self.accounts.write_text(json.dumps({"users": {
            self.PID: {"username": "ccb@ccb.com", "nameOnPlatform": "ccb@ccb.com",
                       "profileId": self.PID, "created": 1, "logins": 1},
        }}), encoding="utf-8")
        self.devices = root / "devices.json"
        self.devices.write_text(json.dumps({}), encoding="utf-8")
        self.xp = root / "player_levels.json"
        for p in (patch.object(srv.acct, "ACCOUNTS", str(self.accounts)),
                  patch.object(srv.acct, "DEVICES", str(self.devices)),
                  patch.object(srv.acct, "REMEMBER", str(root / "remember.json")),
                  patch.object(srv, "_PLAYER_XP_PATH", str(self.xp)),
                  patch.dict(srv._player_xp, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    # ---------------------------------------------------------------- 名字
    def test_real_account_name_wins_over_pid_fallback(self):
        """★ 回归：`Player` + pid[:4] 这个兜底必须排在真人后面。"""
        self.assertEqual(srv.acct.name_for_profile(self.PID), "ccb@ccb.com")
        # 兜底池里的 pid 不归账号管，返回 None 让调用方自己兜。
        self.assertIsNone(srv.acct.name_for_profile(self.BOT))
        self.assertIsNone(srv.acct.name_for_profile(""))
        self.assertIsNone(srv.acct.name_for_profile(None))

    def test_profiles_query_shows_real_name_and_keeps_bots(self):
        """客户端就是靠这个端点把榜上的 pid 翻成名字的（x70+ 次/会话）。"""
        _, _, body = srv.h_profiles_query(
            "", "profileId=%s,%s" % (self.PID, self.BOT), b"", {})
        got = {p["profileId"]: p["nameOnPlatform"] for p in body["profiles"]}
        self.assertEqual(got[self.PID], "ccb@ccb.com")
        self.assertEqual(got[self.BOT], srv.FRIEND_NAMES[self.BOT])
        self.assertNotIn("Player" + self.PID[:4], got.values())

    # ---------------------------------------------------------------- 等级
    def test_remember_player_xp_persists_across_restart(self):
        """★ 回归：等级必须活过服务器重启。

        用户每轮都在"改完代码 → 重启服务器 → 不重开游戏"之间测试，内存版的
        等级会变回 0，界面又显示「等级 1」—— 他会以为存档被清了（m01175）。
        """
        headers = {"Authorization": "Ubi_v1 t=x"}
        with patch.object(srv.acct, "serve_progress",
                          return_value=(self.PID, {}, "own")):
            srv._remember_player_xp(headers, json.dumps({"xp": 14}).encode("utf-8"))
        self.assertEqual(srv._player_xp[self.PID], 14)
        self.assertTrue(self.xp.exists(), "等级没落盘，重启就丢")
        # 模拟重启：清空内存再从文件读回来。
        srv._player_xp.clear()
        self.assertEqual(srv._player_xp_load(), {self.PID: 14})

    def test_remember_player_xp_ignores_junk_and_negative(self):
        with patch.object(srv.acct, "serve_progress",
                          return_value=(self.PID, {}, "own")):
            for bad in (b"", b"not json", b"{}", b'{"xp": null}',
                        b'{"xp": -1}', b'{"xp": "abc"}'):
                srv._remember_player_xp({"Authorization": "Ubi_v1 t=x"}, bad)
        self.assertEqual(srv._player_xp, {})
        self.assertFalse(self.xp.exists(), "坏数据不该建文件")
        # 缺 xp 但 JSON 合法时不能炸，也不能写脏值。
        with patch.object(srv.acct, "serve_progress",
                          return_value=(self.PID, {}, "own")):
            srv._remember_player_xp({"Authorization": "Ubi_v1 t=x"},
                                    b'{"player_name": "ccb@ccb.com"}')
        self.assertEqual(srv._player_xp, {})

    def test_progress_status_reports_recorded_level(self):
        pid, content = self.PID, {"items2": [1, 100, 2, 7],
                                 "missions2": {"solved": [1, 2, 3]}}
        with patch.object(srv.acct, "serve_progress",
                          return_value=(pid, content, "own")):
            srv._player_xp[self.PID] = 14
            _, _, body = srv.h_progress_status("", "", b"", {})
        self.assertEqual(body["coins"], 100)
        self.assertEqual(body["diamonds"], 7)
        self.assertEqual(body["missions_completed"], 3)
        self.assertEqual(body["player_level"], 14)
        self.assertIn("player_points", body)

    def test_progress_status_zero_when_level_unknown(self):
        """没上报过就回 0，不猜、不动存档（这是显示用数字，不是存档里的字段）。"""
        with patch.object(srv.acct, "serve_progress",
                          return_value=(self.PID, {"items2": [1, 1]}, "own")):
            _, _, body = srv.h_progress_status("", "", b"", {})
        self.assertEqual(body["player_level"], 0)

    def test_level_file_junk_does_not_take_the_server_down(self):
        for blob in ("not json at all", "[]", '{"p": "abc"}', "null", ""):
            self.xp.write_text(blob, encoding="utf-8")
            self.assertEqual(srv._player_xp_load(), {})
        self.xp.unlink()
        self.assertEqual(srv._player_xp_load(), {})


class GhostAppearanceTest(unittest.TestCase):
    """★ 幽灵/对手的 `data`/`upgrades` 是**外观位域**，不是可以随便填 0 的数字。

    真机证据：61 条真成绩 + 163 条占位行里 `data` 最小值是 `0x100`，客户端从来不
    产生 0；而客户端的 `tr::LeaderBoardData::getOutfit(int)` / `getBikeSkin()` 直接
    解这个位域，解出来的东西再被搬进 `tr::OnlineDataContainer::m_ghostOutfit`。
    我们以前在三处发 0（内置幽灵折成的对手行 / `match/v1/robot` / 总榜聚合把它当
    「跑过几条赛道」的计数器），真机表现就是「幽灵服装、车身喷漆不对，骑手没有脑袋」
    （m01329）。
    """

    PID = "53ebbd18-818e-5c2c-a865-773262f736e5"
    BUILTIN_OWNER = "6f857655"      # 内置幽灵的 owner 是 online-id 哈希，不是 pid

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lb = Path(self.tmp.name) / "leaderboards.json"
        p = patch.object(srv, "LEADERBOARD_PATH", str(self.lb))
        p.start()
        self.addCleanup(p.stop)

    def write_boards(self, boards):
        self.lb.write_text(json.dumps(boards), encoding="utf-8")

    @staticmethod
    def parts(data):
        """按反汇编出来的 `data` 布局解出骑手 part0/part1/part2。"""
        return ((data >> 26) & 0x3F, (data >> 20) & 0x3F, (data >> 14) & 0x3F)

    def test_layout_matches_real_rows(self):
        """布局取自 `encodeData()`@0x625178 / `parseData()`@0x6250fc 的反汇编，
        必须能解出真机成绩行里那几套骑手 part。"""
        for data, want in ((0x49248100, (18, 18, 18)),   # ccb（profile.outfit 0x121212）
                           (0x5D75C200, (23, 23, 23)),   # anon（profile.outfit 0x171717）
                           (0xBEFBCD00, (47, 47, 47)),
                           (0x20820100, (8, 8, 8)),
                           (0x00000100, (0, 0, 0))):     # 占位行
            self.assertEqual(self.parts(data), want)
        # 反过来拼：布局的自检
        self.assertEqual(srv._lb_data((18, 18, 18)), 0x49248100)

    def test_fallback_is_a_value_the_client_produces(self):
        """兜底值必须是客户端自己也会发的：三个 part 都非 0（0 = 没有这个部件）。"""
        for owner in (self.BUILTIN_OWNER, "", None, "99511744", self.PID):
            data = srv._lb_ghost_data(owner)
            self.assertNotEqual(data, 0)
            self.assertNotIn(0, self.parts(data), "part 为 0 → 客户端解出「没有脑袋」")
            self.assertEqual(data, srv._lb_ghost_data(owner), "同一个 owner 要稳定")
        # 不同幽灵不该穿同一件衣服
        vary = {srv._lb_ghost_data(o) for o in
                ("6f857655", "99511744", "53ebbd18-818e-5c2c-a865-773262f736e5", "0")}
        self.assertGreater(len(vary), 1)

    def test_uses_the_ghost_owners_real_row(self):
        self.write_boards({"track1041": {self.PID: {
            "data": 0xBEFBCD00, "upgrades": 0xAAAA0380}}})
        self.assertEqual(srv._ghost_appearance(1041, {"owner": self.PID}),
                         (0xBEFBCD00, 0xAAAA0380))

    def test_falls_back_to_baseline_when_owner_is_a_hash_or_unknown(self):
        self.write_boards({})
        self.assertEqual(srv._ghost_appearance(1041, {"owner": self.BUILTIN_OWNER}),
                         (srv._lb_ghost_data(self.BUILTIN_OWNER), 0))
        self.assertEqual(srv._ghost_appearance(1041, {}),
                         (srv._lb_ghost_data(""), 0))
        self.assertEqual(srv._ghost_appearance(1041, None),
                         (srv._lb_ghost_data(""), 0))
        # owner 是 pid、但那条赛道没跑过 → 还是兜底，不是 0。
        self.write_boards({"track1041": {self.PID: {"data": 0xBEFBCD00}}})
        self.assertEqual(srv._ghost_appearance(999, {"owner": self.PID}),
                         (srv._lb_ghost_data(self.PID), 0))

    def test_builtin_ghosts_folded_into_opponents_never_get_data_zero(self):
        records = [
            {"track_id": tid, "drive_time": 20000 + tid, "builtin": True,
             "owner": self.BUILTIN_OWNER, "contentId": 100 + i, "stored": True}
            for i, tid in enumerate((1041, 1024, 4))
        ]
        with patch.object(srv.acct, "ghost_list", return_value=records), \
                patch.object(srv, "_OPPONENT_CACHE", None):
            rows, _ghosts = srv._opponent_entries()
        self.assertTrue(rows, "内置幽灵没折成对手行")
        bad = [(pid, b) for pid, bs in rows.items() for b, r in bs.items()
               if int(r.get("data") or 0) == 0]
        self.assertEqual(bad, [], "对手行的 data 发 0 = 点进去挑战的幽灵没有脑袋")

    def test_match_robot_never_sends_data_zero(self):
        self.write_boards({"track1041": {self.PID: {
            "data": 0xBEFBCD00, "upgrades": 0xAAAA0380}}})
        for rec, want in (({"owner": self.PID, "contentId": 1}, 0xBEFBCD00),
                          ({"owner": self.BUILTIN_OWNER},
                           srv._lb_ghost_data(self.BUILTIN_OWNER)),
                          (None, srv._lb_ghost_data(""))):
            with patch.object(srv, "_robot_opponent",
                              return_value=("GhostRider", 25000, rec)):
                _, _, body = srv.h_match_robot("/public/match/v1/robot",
                                               "track_name=track1041", b"", {})
            self.assertEqual(body["data"], want)
            self.assertNotEqual(body["data"], 0)

    def test_global_aggregate_or_merges_data_and_counts_tracks(self):
        """★ 回归：`data` 被当成计数器时真人总榜行的外观位域只剩个位数。"""
        boards = {
            "track1041": {self.PID: {"drivetime": 25000, "data": 0x20820100,
                                     "upgrades": 0x00000140, "score_value": 10}},
            "track1024": {self.PID: {"drivetime": 30000, "data": 0x00000100,
                                     "upgrades": 0x122000c0, "score_value": 5}},
        }
        with patch.object(srv, "_load_ranked_boards", return_value=boards):
            rows = srv._aggregate_global_entries()
        row = [r for r in rows if r["player"] == self.PID][0]
        self.assertEqual(row["data"], 0x20820100 | 0x00000100)
        self.assertEqual(row["tracks"], 2)
        self.assertNotEqual(row["data"], 2)

    def test_rank_entry_does_not_leak_the_tracks_counter(self):
        entry = srv._rank_entry({"player": "p", "rank": 1, "data": 1,
                                 "upgrades": 0, "tracks": 37})
        self.assertNotIn("tracks", entry["stats"])


if __name__ == "__main__":
    unittest.main()
