# Research toolkit — Trials Frontier online-rule preservation

> **这台机器出网的正确姿势（2026-10 实测）。** `web_search` 报 HTTP 402 余额不足、`web_fetch` 报 `TypeError: fetch failed` —— **两个内置工具在本环境完全不可用**，不要浪费时间重试。唯一能出网的路子是 `pwsh` + 显式 HTTP 代理。
>
> 产物落在 `_research/`（已 gitignore）。可入库的结论见 `work/trials-frontier/notes/online-rules-evidence.md`。
>
> **死胡同已记录在下面「Blocked / useless」一节** —— 尤其：Reddit 主站全线 403（只能走 redlib 镜像，且十个切题帖仍读不到，ID 见 `online-rules-evidence.md` §5）；Wayback **回放**被 IP 封（429 bot flag）但 **CDX API 可用**，赛季/事件目录就是靠它拿到的；`trialsfrontier.fandom.com` 根本不存在。

Session: danger-full-access file policy, approval prompts DISABLED (never request sandbox escalation).
OS: Windows, PowerShell (`pwsh` tool). Working dir: <repo>

## Network reality (verified 2026-10)
- The built-in `web_search` tool FAILS (DeepSeek HTTP 402 Insufficient Balance).
- The built-in `web_fetch` tool FAILS (`TypeError: fetch failed`).
- **Use `pwsh` + `Invoke-WebRequest` instead.** This machine needs an explicit HTTP proxy:

```powershell
$UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 60 -Proxy "http://127.0.0.1:7890" -Headers @{"User-Agent"=$UA}
```

- Some hosts work WITHOUT the proxy, some only WITH it. When a fetch fails, RETRY WITH THE PROXY before calling it unreachable.

## What works

| Route | How |
|---|---|
| **Yahoo search** (primary general search) | `https://search.yahoo.com/search?p=QUERY&b=1` — encode spaces as `+` ONLY. `%20` and extra params (`pz`,`ei`) cause HTTP 500 INKApi Error. Paginate with `&b=11,&b=21`. |
| **Bing** | `https://www.bing.com/search?q=...` (works, but often returns unrelated fillers — low trust) |
| **Qwant** | `https://www.qwant.com/?q=...&t=web` |
| **Fandom MediaWiki API** | `https://trials.fandom.com/api.php?action=query&...&format=json` — works. HTML `/wiki/` pages are 403. This wiki is near-empty for Frontier. |
| **Wayback CDX API** | `https://web.archive.org/cdx/search/cdx?url=DOMAIN&output=text&limit=200&collapse=timestamp:6` — works well, use it to enumerate snapshots. |
| **Wayback playback** | `https://web.archive.org/web/<timestamp>id_/<url>` — frequently 429; retry / slow down. |
| **Reddit mirror (redlib)** | `https://redlib.privacyredirect.com/r/<sub>` and `/r/<sub>/search?q=...&restrict_sr=on&sort=relevance` — works. Try also `redlib.catsarch.com`, `safereddit.com`. |
| **tf.lforo.com** | Third-party PvP leaderboard archive (HTTP only, no TLS). |
| **YouTube** | `https://www.youtube.com/@handle/videos` returns raw HTML with `ytInitialData` even without JS. |

## Blocked / useless (do not re-try)
- `google.com/search` — returns a JS-required shell, no results in HTML.
- `reddit.com` and `old.reddit.com` directly — 403 Blocked / login wall (even via proxy).
- `trialsfrontier.fandom.com` — does not exist (404 on api.php).
- `archivedwiki.miraheze.org` — different game (Library of Ruina), coincidental "Chip Boards" page.
- `toucharcade.com` forums — 403.
- `mojeek.com`, `ecosia.org` — 403.
- `searx.be`, `safereddit.com`, `startpage.com` — Anubis proof-of-work wall.
- `r.jina.ai` — 403.

## Yahoo result parser (copy this)
```powershell
$UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
$q="your+query+here"
$r=Invoke-WebRequest -Uri "https://search.yahoo.com/search?p=$q&b=1" -UseBasicParsing -TimeoutSec 60 -Proxy "http://127.0.0.1:7890" -Headers @{"User-Agent"=$UA}
$c=$r.Content
foreach($m in [regex]::Matches($c,'<div class="compTitle[^"]*"[^>]*>([\s\S]*?)</div>')){
  $blk=$m.Groups[1].Value
  $a=[regex]::Match($blk,'href="([^"]+)"')
  $d=[regex]::Match($a.Groups[1].Value,'RU=([^/]+)/RK=')
  $dest= if($d.Success){[uri]::UnescapeDataString($d.Groups[1].Value)}else{$a.Groups[1].Value}
  $t=($blk -replace '<[^>]+>','') -replace '&amp;','&'
  if($dest -notmatch 'yahoo\.com'){ "URL: $dest"; "T: $t"; "" }
}
# snippet text usually carries the actual numbers -> also dump every compText span
foreach($m in [regex]::Matches($c,'class="[^"]*compText[^"]*"[^>]*>([\s\S]{20,400}?)</')){ ($m.Groups[1].Value -replace '<[^>]+>','') }
```

## CRITICAL RULES for this task
- NEVER invent or "reconstruct" a number. If not found, write "not documented anywhere found".
- Label provenance: official (Ubisoft/RedLynx/Facebook/Play Store) vs wiki vs player comment vs video.
- Quote the literal supporting sentence for every number, with its URL.
- We want SERVER-decided rules: quantities, cooldowns, cadences, season length, tier/league counts,
  stars-per-promotion, ticket counts+refill, retry counts, costs, trophy tier rewards, matchmaking method.
- Continuous values / earning curves are NOT required (they'll be our own defaults).
