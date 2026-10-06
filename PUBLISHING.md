# 开源前检查清单（仓库安全）

> **这个仓库现在是私有的**（匿名访问 GitHub 网页与 API 都是 404）。本文件是「哪天要公开、要发给别人之前，必须过一遍」的清单，也是仓库安全现状的记录。
> 最近一次审查：**2026-10-06**（当时 `origin/DEMO` = 122 个文件 / 2.15 MB，无大二进制、无机密）。

## 0. 结论摘要

- ✅ **没有机密**：管理员口令 `tflocal-admin-1` 零命中；无 `PRIVATE KEY`；无 api_key / access token 明文（`work/trials-frontier/notes/real-server-samples.md` 早已把真 token 脱敏成 `<ubimobi_access_token>`）。`tests/test_admin_webui.py` 里的 `correct-horse-9` / `fresh-secret-1` 只是测试夹具。
- ✅ **管理员口令不硬编码**：走 `server/data/admin.json`（口令哈希 + 盐，已 ignore），`--reset-admin` 时由 `acct.admin_new_password()` 随机生成。别为了省事把它写回代码或文档。
- ✅ **远端没有 APK / 大二进制**：`origin/main` 只有 `LICENSE` + `.gitattributes`；`origin/DEMO` 最大的文件是 `server/tf_server.py`（349 KB）。本地 `.git` 里的原版 APK 副本已清（§6）。
- ⚠️ 库里有一批**游戏版权物**（§1）与**个人信息残留**（§3）：私有仓库无碍，公开前必须处理。

## 1. 已跟踪的游戏版权物（公开前必须摘掉）

| 路径 | 是什么 | 为什么危险 |
| --- | --- | --- |
| `server/admin/items.json` | WebUI 的物品 / 赛道 / 车 / 奖励目录（478 物品、382 赛道、19 车、309 奖励） | 含**游戏自带的 CN/EN 本地化文案**，是从原版内容包抽出来的 |
| `server/data/wts_rewards.json` | 午夜杯奖池表（3 套方案 × 5 档），WebUI 读它渲染「池子里有什么」 | 同样是从 `/conf/wts_rewards.txt` 抽出来的游戏数据 |
| `server/data/ghosts/<赛道id>/*.bin` | 46 个**游戏自带的静态幽灵** | 原版 DLC 数据；这是离线环境唯一能让比赛出现「别人的幽灵」的素材，所以当初特意解除了屏蔽 |
| `work/trials-frontier/notes/*.md` | 逆向笔记（反汇编地址、字段偏移、文案 hash） | 是**我们的**成果，不含游戏资产；但公开等于把汉化/数据表的来源讲透，自行判断 |

摘掉（磁盘文件保留，服务照跑）：

```bash
git rm --cached server/admin/items.json
git rm --cached server/data/wts_rewards.json
git rm -r --cached server/data/ghosts    # 只摘 <赛道id>/*.bin 与两个 md；store/ 之类本来就不入库
```

摘完必须补 `.gitignore`（否则下次 `git add -A` 又进去）：

```
server/admin/items.json
server/data/wts_rewards.json
server/data/ghosts/
!server/data/ghosts/README.md
!server/data/ghosts/INDEX.md
```

让使用者自己从**自己的** APK / 内容包生成（工具都在库里）：

- `python tools/build_item_catalog.py` → `server/admin/items.json`（见 `tools/README.md` §5.1 的数据来源）
- `python tools/wts_reward_doc.py` → `server/data/wts_rewards.json`
- 静态幽灵：从自己的内容包提取，或干脆只用玩家上传的 `server/data/ghosts/store/`

## 2. 运行期私有数据（已 ignore，**别动这些规则**）

| 路径 | 内容 |
| --- | --- |
| `server/data/accounts.json` / `sessions.json` / `remember.json` | 本地账号（用户名 / 盐 / 口令哈希）、会话票据、记住我 |
| `server/data/devices.json` / `bindings.json` | 设备槽、客户端绑定表（按 IP / 设备 id 记住账号） |
| `server/data/admin.json` | 后台管理页管理员账号（口令哈希 + 盐） |
| `server/data/pvp_state.json` | 筹码余额与局内票（含真实 profile id） |
| `server/data/leaderboards.json` / `player_levels.json` | 榜单与玩家上报的等级 |
| `server/data/config_audit.jsonl` / `templates.json` | 运营参数审计（最近 300 条）与整页参数模板 |
| `server/data/save/` | **玩家真实存档**（金币、赛道纪录、identifier） |
| `server/data/ghosts/store/` / `index.json` / `replays.json` / `inbox/` | 玩家上传的幽灵与登记表 |
| `server/data/tf_config.json` | **线上手调参数**（已改成不入库，见 §7） |
| `APKS/` / `tmp/` / `dist/*`（除 `dist/README.md`）/ `pvp_docs/` | 原版 APK 备份与手机截图 / 构建中间产物 / 交付包 / 超范围设计稿 |

`.gitignore` 末尾用 `server/data/*.json` 兜底，**例外放行** `!server/data/wts_rewards.json`（游戏奖励表，WebUI 要用，必须入库）。

## 3. 个人信息残留

- 设备序列号 `bdca0e2a`：2026-10-06 已换成 `<设备序列号>`（`work/trials-frontier/notes/item-ids.md`、`work/trials-frontier/notes/pvp-reward-contract.md`）。
- 本机路径 `F:\Code\…` / `C:\Users\…`：已换 `<repo>` / `<用户目录>`（`notes/2026-10-05_pvp-economy-report.md`、`notes/web-research-toolkit.md`、`scope.md`）。`notes/selfcontained-apk.md` 里的 `C:\Users\<user>\…` 本来就是占位符，没有用户名。
- 内网地址 `192.168.5.2`：**故意留着** —— 离线服务器的地址本来就要写进文档（`server/README.md`、`dist/README.md`、`tools/README.md`、`tests/`）。公开前若在意，`git grep -l '192\.168\.'` 一把换掉。
- 真机 profile UUID（`2e08f776-…`）从来没入过库；`zhangsan` 只是文档里的示例账号名。
- ⚠️ 改只能改**新提交**：历史旧值仍在（§5）。

## 4. 每次 push 前的自检（三行）

```bash
git grep -l -I -E 'BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key|access_token|tflocal-admin-1'
git grep -l -I -E 'bdca0e2a|2e08f776|192\.168\.|F:\\Code|C:\\Users'
git status --short
```

第三条的输出应该只有被 ignore 的运行期文件（`server/data/tf_config.json` 之类，`git status` 里根本不会出现）。

> ★ `git grep` 一律加 `-l`：`server/admin/items.json` 是**单行 219 KB**，`-n` 会把整个文件喷到终端。

## 5. 历史里的东西 `rm --cached` 删不掉

`git rm --cached` 只影响之后的提交；旧提交里的 `items.json`、幽灵、路径仍然在，`git log -p` / 深链接都能翻出来。真要公开：

- **推荐**：另建一个干净仓库 —— 取当前工作树做首次提交即可
  ```bash
  git archive HEAD | tar -x -C /tmp/clean && cd /tmp/clean && git init && git add -A && git commit -m "Initial"
  ```
- 或重写历史（需 `git-filter-repo`）：
  ```bash
  git filter-repo --path server/admin/items.json --path server/data/ghosts --invert-paths
  ```
  然后强推，并通知所有协作者**重新克隆**（旧克隆会带着旧历史）。

私有仓库不值得做这件事；公开前再做。

## 6. 本地 `.git` 体积（2026-10-06 已清）

当时 `git count-objects -vH` 的 `size-pack` = **307.69 MiB**，而全部文件才 2.15 MB。原因是 pack 里躺着 10 个正好 30 MiB 的 blob —— `APKS/特技摩托前线/Main_APK_Backup.7z.001-010` 的旧副本（早期 `git add` 过、之后 `rm --cached`，**从未提交、从未推送**），另有 3 个 760 KB 手机截图 PNG 与 1 个 3.5 MB 未知二进制。

```bash
git reflog expire --expire-unreachable=now --all
git gc --prune=now
```

清理前把两个悬空 stash 提交救成了分支 `wip/rewards-probe`（`On DEMO: wip-rewards-probe` = `222e1ab`、`index on DEMO` = `5331a90`），确认没用就 `git branch -D wip/rewards-probe` 再 gc 一次。

**注意**：磁盘上的 APK 原件还在 `APKS/`（已忽略），`.git` 里只是副本，清掉不丢东西。**永远不要 `git add APKS/`。**

## 7. 血泪教训（别做的事）

- **别 `git add -A` 一把梭**：`APKS/`、`tmp/`、`dist/*`、`server/data/save/` 里全是不能上传的东西。
- **别把 `server/data/tf_config.json` 提交回去**：那是线上手调值（含局域网地址），已从版本库摘掉并加进 `.gitignore`；以后改动只会出现在 `git status` 里。
- 别把管理员口令、真实 profile id、设备序列号写进文档 / 脚本 / 测试夹具（夹具用假值）。
- 交付/开源之前，先跑一遍 §4 的三行自检。
