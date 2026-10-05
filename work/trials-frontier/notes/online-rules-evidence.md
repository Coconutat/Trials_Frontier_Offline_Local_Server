# Trials Frontier — server-decided online rules: documented evidence

> **这份文档服务 `ROADMAP.md:3`（在线功能完善）。** 私服要"还原"的那些数值（赛季多长、榜截断多少、事件几个 leg、门票怎么消耗……）**只能靠外部史料**定，因为客户端 `.so` 里只有规则引擎、没有数值。本文就是那批数值的唯一来源。
>
> * **抓取时间**：2026-10（游戏已于 2025-11-04 从商店下架）。
> * **原始抓取件**：`_research/`（92 文件 15.4 MB，**已 gitignore**）。本文的表格数据对应 `_research/yt_*_meta.tsv`、`_research/yahoo_mine.txt`。
> * **方法**：见 `work/trials-frontier/notes/web-research-toolkit.md`（本机 `web_search`/`web_fetch` 不可用，必须走 `Invoke-WebRequest -Proxy http://127.0.0.1:7890`）。
> * **纪律**：每个数值都带 URL + 原文引用；**查不到的一律写 "not documented anywhere found"，绝不编**。见 §5。
> * **对我们的直接影响**：§2 末条「**No source describes racing a recorded ghost of another player.**」⇒ 我们的"幽灵对手"是自创还原，不是原作机制；原作匹配是**总分/段位**驱动。

Scope: quantities, cooldowns, cadences and season structure — what the **server** decided. Client-embedded tables are out of scope. Each value carries a URL and the literal text behind it; player claims are labelled.

## 1. Concrete numbers found

| Value | What it is | Decider | Source & supporting quote |
|---|---|---|---|
| **PvP opened 11–12 Dec 2014** | Showdown launch | Ubisoft | [youtube.com/watch?v=ikXmGd6G7Kc](https://www.youtube.com/watch?v=ikXmGd6G7Kc) (official trailer, 2014-12-11): "Zudina has finally thrown open the doors to her Bunker and a deadly competition awaits inside!… climb the season rankings to become a LEGEND OF THE FRONTIER." |
| **Season 1: 12/12/2014 00:00 → 09/02/2015 00:00 = 59 days** | season length, early | Server | [bonxy `the-bunker/Opening+Season-1`](http://trials.bonxy.net/the-bunker/Opening+Season-1): "Start: 12/12/2014 00:00 - End: 09/02/2015 00:00" |
| **2,121 Legends (iOS 1,279 / Android 842)** | season-1 top tier size | Server | same: "Legends: 2,121 iOS: 1,279 - Android: 842" |
| **Season 83: 22/03/2021 21:00 → 19/04/2021 10:00 = 28 days** | season length, late | Server | [bonxy `the-bunker/Desert+Storm+Season-83`](http://trials.bonxy.net/the-bunker/Desert+Storm+Season-83): "Start: 22/03/2021 21:00 - End: 19/04/2021 10:00" |
| **199 Legends (Apple 58 / Android 141); first Legend `RF_Gladiator`** | season-83 top tier | Server | same: "Legends: 199 … Apple 58 RF_Gladiator Android 141" |
| **≥83 numbered seasons** | ladder periods | Server | Wayback CDX of `trials.bonxy.net/the-bunker*`; pages `…-1` … `…-83` |
| **Top tier "Legend"; board `/leaderboards/legends`** | tier naming | Server | trailer above + CDX of `trials.bonxy.net/leaderboards*` |
| **"Get to rank 3 in the Bunker to own this wicked new paintjob"** | rank → reward | Server | [facebook.com/trialsfrontier.game/posts/1123670137799356](https://www.facebook.com/trialsfrontier.game/posts/1123670137799356/) (headline only; body blocked) |
| **Board depth 10,000 ranks (hidden PvP tracks) / 30,000 (Global)** | board caps | Server | [tf.lforo.com/android](http://tf.lforo.com/android): "leaderboards with first 10 000 ranks of hidden PvP tracks and 30 000 of Global Leaderboard" |
| **261 tracks feed Global Score; 273 on record** | track counts | Server | tf.lforo.com "Tracks with rank in top 500 (261 tracks total)"; [profile/114740](http://tf.lforo.com/android/profile/114740) "Results by tracks (33 of 273)" |
| **Tickets board 13,894 riders; Diamonds 13,913** | PvP-currency populations | Server | bonxy `/leaderboards/tickets` (`20170503024854`), `/leaderboards/diamonds` (`20170505085128`) |
| **Top ticket holdings 2,147,483,647 (int32 max)** | clamp / cheater marker | Server | bonxy tickets: "the total Tickets a rider has. It can be used to identify cheaters" |
| **"Golden Tickets" = PvP entry consumable; iOS purchase blocked at least once** | ranked entry currency | Client+server | [watch?v=zIudTtrM1Mw](https://www.youtube.com/watch?v=zIudTtrM1Mw): "burn through some Golden Tickets while also winning some races… keep watching your earlier matches"; [facebook post 960488827450822](https://www.facebook.com/trialsfrontier.game/posts/960488827450822/): "Riders on iOS, you'll not be able to purchase golden tickets for the Bunker…" |
| **Midnight Club runs numbered WEEKLY rounds** | weekly cadence | Server | bonxy tickets page: "Midnight Club: Week 10 - MC is back! Click here to see where you rank!" |
| **Midnight Club = server event `event/22`** | mode identity | Server | same page, `title="View Midnight Club Event"` → `trials.bonxy.net/event/22` |
| **KTM Rally = 4 legs; leg cadence ≈7 days** (2017-01-11/19/25, 02-02) | event structure | Server | [lforo android/event/ktm](http://tf.lforo.com/android/event/ktm): "Results of KTM Event week 1 week 2 week 3 week 4"; upload dates of the four "KTM Rally Challenge n of 4" videos |
| **KTM board cuts at best 3,000/track; 219,892 riders** | board caps | Server | same: "Only best 3000 results of each track were collected."; "KTM Global … 219 892" |
| **Events numbered `/event/1` … `/event/123+`, multi-leg (2–6)** | event catalogue | Server | CDX: `Dakar+Rally/1…/6`, `BMW+F800/1…/4`, `Harley-Davidson+Rally/1…/5`, `Bandito+Rally/1…/3` |
| **Difficulty tiers Normal / Donkey / Crazy** | ladder split | Client+server | tf.lforo.com selector labels "Normal Donkey Crazy" |
| **Per-track server populations** — Dust Bowl 4,407,940; Concealed Entryway 3,282,967; Old City Wall 2,621,329; Lost Playground 1,954,253; Underground Slopes 1,092,828; Bell Tower 57,718; Wrecked Tracks 11,982; Choking Hazared 8,407 | riders on a track | Server | lforo profile/track tables, column "Total player" |
| **Build markers in unreleased tracks: `Prod30`, `Prod45`, `Prod55`, `Prod58`; `!!!-Donkey lvl 239`** | internal build gating | Server | [lforo android/tracks/normal/unreleased](http://tf.lforo.com/android/tracks/normal/unreleased): "!!-Prod30 Maria", "!!!-Prod45 Ukkis", "!!!-Prod55 Maria 3", "!!!-Prod58 Maria 5" |
| **"Usually, I accumulate around 10k chips"** — *player statement* | chip magnitude | Server | r/TrialsGames `ap35o3` snippet |
| **PvP shop reset at season boundaries is unresolved** | shop cadence | Server | r/TrialsGames `zpv3f8` "Do chips in PvP shop reset when the season ends?" |
| **Last captured season Apr 2021; lforo data to 2022-04-13; delisted 4 Nov 2025** | timeline | — | tf.lforo.com "Last update: 2022-04-13"; trials.fandom.com "as of November 4, 2025, Trials Frontiers has been delisted" |

## 2. Qualitative-only descriptions

- **"Showdown" is the head-to-head PvP match; the Bunker is its venue.**
- **Seasons are named, roughly monthly, and names recycle**: Resolution 42/68/81; Desert Storm 58/70/83; Campfire 49/78; Blitz 3/6/10/17 — only the number is a key (bonxy CDX).
- **Season rollover pays out the previous standing**: "Campfire Season has started in the bunker. It's time to see what I've gained from the previous season" ([bj5rWZwIR0I](https://www.youtube.com/watch?v=bj5rWZwIR0I), 2018-08-23).
- **Midnight Circuit is a limited recurring window, not permanent**: "I can't believe that the midnight circuit is back! … while it's still on" ([aW2yckHqF3c](https://www.youtube.com/watch?v=aW2yckHqF3c), 2017-03-14); "The Midnight circut actually back" ([XiguyJ8TXO0](https://www.youtube.com/watch?v=XiguyJ8TXO0), 2016-12-24).
- **Matchmaking is score/rank-driven** — the archive exists to "Find your bunker opponent in Total or compare yourself with others!" (tf.lforo.com). **No source describes racing a recorded ghost of another player.**
- **Events are licensed rally/sport themed and server-scheduled**: KTM, BMW F800, Dakar, Harley-Davidson, Bandito, Easter Egg Hunt, Orbies Quest, Mission Impossible, Treasure Hunt, Love Express, Rodeo, Bikes and Fire, Holiday Run, X Games Norway (season 46) and Minneapolis 2018 (CDX; "looking at the rewards from the X Games Minneapolis 2018 event", [7M7_uvdkmt0](https://www.youtube.com/watch?v=7M7_uvdkmt0)).
- **A "Time Capsule" mode coexisted with Showdowns** (Dec 2016, [qTJLIPyi1hU](https://www.youtube.com/watch?v=qTJLIPyi1hU)).
- **PvP tracks are hidden from normal play** ("hidden PvP tracks", tf.lforo.com), consistent with PvP sets not being browsable in the campaign.
- **Daily missions were server-tracked** (`/leaderboards/missions`); content unrecovered.

## 3. Video inventory

Channel `kasparplayz8898` = **UCq_pgOPh3_ck-qOgCEtZ_dQ**. Its `/videos` tab exposes only 30 items and a continuation POST returned 0, so the uploads playlist `youtube.com/playlist?list=UUq_pgOPh3_ck-qOgCEtZ_dQ` was used: **100 videos with title, duration, views, date — 47 Trials Frontier.** Titles run to `#56` and `S2 E18`, so older episodes sit behind pagination and were not retrieved. Links are `youtube.com/watch?v=<id>`.

**Area 1 (PvP/season):** `bj5rWZwIR0I` CAMPFIRE SEASON! S2 E18 ⚑ · `KQyznX9VQ_E` \*NEW\* Trials Frontier SEASON 2 · `WuVOlEjU6Yg` TIME CAPSULE & DECEMBER UPDATE!!! #33 ⚑ · `Kf1wey4q5SE` SHOWDOWN TIME!!! #34 ⚑ · `qTJLIPyi1hU` TIME CAPSULE & SHOWDOWNS #35 ⚑
**Area 2 (Midnight Circuit):** `aW2yckHqF3c` SPRING BREAK MIDNIGHT CIRCUIT!!! #55 (2017-03-14, 1.9K) ⚑ · `XiguyJ8TXO0` THE MIDNIGHT CIRCUIT IS BACK & RIPTIDE #37 (2016-12-24, 2.8K) ⚑
**Area 5 (limited events):** `u7UfPkw8dn8` OP BIKE! KTM 1 of 4 #43 · `7yaEXtqywAo` LEG 2 IS HERE!!! KTM 2 of 4 #45 · `_zmvLofFv2E` I BELIEVE I CAN FLY! KTM 3 of 4 #47 · `Tjss6fu9R9Q` I HATE THE SWAMP!!! KTM 4 of 4 #49 · `7M7_uvdkmt0` LONGEST JUMP… S2 E13 ⚑ · `vdbOHHfCU5g` X GAMES RAGE! S2 E7 · `l-pUtEqIKaE` Hidden Christmas Tracks!?! #32 · `ZHksELkebQU` TERRACOTTA RIDER DEFEATED! S2 E10 · `XKfjY9Pp5Hc` BERSERKER!!! S2 E17 · `FvaWKSGHXz8` NEW MAPS! S2 E9 · `pcnOiHACkWE` NEW TRACKS! #41
**Areas 6/7 (quests, purchases, bikes):** `5z1lQEd10ho` NEW QUESTS! S2 E3 · `vHNs084acDw` VERBAL VOMIT GRINDING! S2 E6 · `vQ-igqRpxnE` NEW TIER 3 BIKE S2 E4 ⚑ · `6of4fibJCUI` MARAUDER!!! #42 · `8RRDj2QeYT8` RIPTIDE!!! #39 · `cVUuIWegPAg` New Paintjob for the Jackal!!! #28 · `iCTKkexsIy8` The Bronco!! #27
**Non-rule episodes** (the remaining 10 of 47 TF videos are collectible/misc, no online rules): collectible guides `KXheC-CmNWQ`, `9hWpPbCY6hU`, `p5b9WYgGznY`, `tmjrSCSHXZs`, `rJcHTicD6YI`, `wjDTucbnbHc`, `rkErOdxb8mg`, `FUh_0Ke6fwc`; misc `G0YIHvXIBQ4`, `JjWuXcHsg5Y`, `WoknZiUxjus`, `KCVCLYiRyFg`, `bVEC39w5Lao`, `kxp33k17S6k`, `LLNbeolutVQ`, `zGkVgDtTSEE`, `2kznA4OXw94`, `Fnu1bMU00EU`, `kmVzLfcy4sw`.

⚑ = indicates a visible reward, standing or shop screen.

**Other channels / official media:** `ikXmGd6G7Kc` "Trials Frontier -- PvP Trailer [INT]" — **official Ubisoft trailer**, 2014-12-11 (areas 1/8, the highest-value primary source) · `zIudTtrM1Mw` "Trials Frontier - PvP Blitz Season" (University Of Trials/FatShady, 2015-05-18) — Golden Tickets + earlier-match replays · `fKt5brnn8Uk` "Hacking pvp chips" (2020-06-21) — links a bonxy player-stats page · `wWqEVZFhays` "Trials frontier midnight circuit tries" (2019-11-27) · `y2FSuw_nEsA` "Trials Frontier-Bunker Part #2 (Pirate Season)" · [vimeo.com/745702481](https://vimeo.com/745702481) "Trials Frontier Bunker" · channel `UCTj-41J4-8IfCrwxKyYL6aQ` (not enumerated).

## 4. Contradictions / version drift

- **Season length shrank: 59 days (season 1, Dec 2014) → 28 days (season 83, Mar–Apr 2021).**
- **Board depths disagree on one site**: lforo's banner claims "first 10 000 ranks of hidden PvP tracks and 30 000 of Global Leaderboard", while its profiles say "Only best 2000 results of each track were collected" and its KTM page "Only best 3000". Read 10,000/30,000 as *server* depth, 2,000/3,000 as the *archive's* stored depth.
- **Season names repeat**, so a name alone cannot identify a season; **seasons 65 and 73 appear in no CDX capture**.
- **"Tranzit Marathon - Leg 1" and "Leg 2" were themselves numbered seasons (52, 53)** — one event spanning two ladder periods.
- **PvP did not ship at launch**: trailer 2014-12-11 and season 1 start 12/12/2014, versus the April 2014 release.
- **Golden Tickets: Android purchasable, iOS blocked** at least once (official Facebook post).

## 5. Dead ends (do not re-check)

- **`trialsfrontier.fandom.com` does not exist** (403 `/wiki/…`, 404 `api.php`). **`trials.fandom.com`** works: 25 pages, exactly **one** Trials Frontier page (pageid 2203) — cosmetics/bike gallery; API searches for PVP/Chips/Midnight/reward/ticket return zero. Still yields events `Halloween 2014`, `Christmas 2015`, an `Offers` image gallery (no text), version **7.9.0** (hidden developer track editor, 7 environments), and the delisting note.
- **`archivedwiki.miraheze.org`** — all 694 pages enumerated; Library of Ruina / Limbus Company. "Chip Boards" was a name collision.
- **Reddit unreadable by every route**: `reddit.com/*.json` 403; `old.reddit.com/…json` login shell; `redlib.privacyredirect.com` Anubis PoW; `reddit.nerdvpn.de` Gandalf PoW; 429/403/410 also on `redlib.catsarch.com`, `redlib.freedit.eu`, `l.opnxng.com`, `redlib.perennialte.ch`, `libreddit.kavin.rocks`, `safereddit.com`, `redlib.tiekoetter.com`. **Unread threads**: `zpv3f8`, `ap35o3`, `eplesu`, `bkw605`, `12690gr`, `gn1fas`, `fw1pgv`, `nreidc`, `zshc4b`, `l9n8j2`.
- **Wayback playback is IP-blocked** — persistent 429 "flagged it as suspected abusive bot traffic" even after 90 s cooldowns; the **CDX API still works** and produced the season/event catalogue. Playback loss blocked remaining bonxy season pages, `notes/change-log`, the Facebook post bodies and archived `support.ubisoft.com` FAQ pages. archive.today is a stub; `timetravel.mementoweb.org` 502.
- **Ubisoft support is JavaScript-walled**: `support.ubisoft.com/Faqs/…` and `ubisoft.com/en-us/help/…` return the same ~45 KB React shell, no text, no `__NEXT_DATA__`; `/api/v1/faqs/…` is a 3 KB 404 shell. The bundle exposes `help.akin.ubisoft.com` (live, probed paths 404) and Contentful creds (`cms-cache.ubisoft.com/GraphQL/`, space `p0f8o8d25gmk`) needing `ubi-appid`/`ubi-appname` headers and disabling introspection; that space's 160 content types are website types. **Official FAQ text — "Trials Frontier Multiplayer Information" (000021957 / 000077772), "What's new in Trials Frontier PvP seasons?" — not recovered.**
- **Facebook** 400 on `www`/`mbasic` (headlines only). **VK** three URL forms, all JS shells. **Stores gone**: Play `com.ubisoft.trials.frontier` 404, App Store `id653085614` 404 — no release notes exist.
- **Search engines exhausted**: `web_search` 402, `web_fetch` failed; Google/Bing give a JS shell or filler; DuckDuckGo CAPTCHA; Mojeek/Ecosia 403; Brave 429; Startpage/searx.be/safereddit Anubis; `r.jina.ai` 403; `api.pushshift.io` SSL error. **Yahoo was last working and now 307→beacon→500.**
- **`bonxystuff.com/trials/`** serves only the farewell notice. `/leaderboards/missions` never played back.

## 6. Bottom line

Safe to hard-code: **PvP opened 11–12 Dec 2014**; **83+ numbered seasons**; **59-day seasons early, 28-day by 2021**; **"Legend" is the top tier, with a per-season Legends count**; **Golden Tickets are the ranked-entry consumable**; **Midnight Club ran in numbered weekly rounds as server event id 22**; **KTM Rally = 4 roughly weekly legs with a 3,000-per-track board cut**; **events are numbered and 2–6 legs**; **the ladder splits Normal / Donkey / Crazy**; **matchmaking resolved opponents via the player's total score**.

Still unknown — **not documented anywhere found**: tiers *below* Legend and their names; stars/points per promotion; tickets granted and their refill cadence; coin/gem magnitudes of post-race PvP rewards; chip earn/spend rates; the daily login reward chain; daily-mission structure; contents/timing of limited-time purchase bundles.
