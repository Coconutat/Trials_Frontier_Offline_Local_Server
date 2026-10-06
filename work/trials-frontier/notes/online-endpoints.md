# Trials Frontier 在线端点清单（逆向所得）

来源：`libTrialsGo.so` / `libubiservices.so` 的 `.rodata` 字符串池 + 反汇编。
所有 `%s/%s/...` 里的第一个 `%s` 是基址（已被 `tools/patch_dynaddr.py` 在运行期指向
`tf_server.txt` 里的地址），第二个 `%s` 是命名空间（实测是 `public`）。

## 已实现（`server/rules.json` / `server/tf_server.py`）

| 端点 | 说明 |
|---|---|
| `GET /` （带 `?product=101&portal=Google&version=…`） | gamecfg，Java 侧 DLC 配置 |
| `GET /v1/applications/<appid>/configuration` | Ubiservices 应用配置；`configuration.sandboxes[].friendlyName` 必须是 `triag_an_lnch61_a_ws` 或 `android_beta`，否则 `setserverAddress` 不会被调用 |
| `POST /v3/profiles/sessions`、`GET/POST /v1/profiles/sessions` | 伪造育碧会话（ticket / sessionId / spaceId / profileId） |
| `GET /v1/profiles/`、`GET /v2/profiles/me` | profile 列表 / 当前用户 |
| `GET /v2/profiles/me/friends` | **好友列表**。形状必须 `{"<key>": [ {...} ]}`；返回 `{}` 会让 `OnlineFriends::onFriendlistRecieved`（0x51cee8）在 `ldr x28,[x8,#0x10]` 处解引用 NULL → SIGSEGV（`fault addr 0x10`）。字段：`pid`、`nameOnPlatform`、`state`（`PendingReceivedInvite` 计入待处理请求数） |
| `GET /v3/policies/<COUNTRY>` | 策略列表 |
| `GET /public/timeservice/v1/gettime` | 反作弊时钟；`ret`+`time_now`+`checksum = md5(str(time_now)+TS_SALT)`，`TS_SALT = c8f68210a7247676aaee552cb6d81c8a` |
| `GET /public/receiptvalidation/v1/product/configuration` | 内购凭据校验（目前走兜底） |
| `GET /dlcontent_frontier_android/<ver>/info.json` | 可下载内容清单（目前走兜底 → 不下载任何东西） |
| 任意 `*.png/.jpg/...` | 占位图（原素材所在 S3 bucket 已消失） |

## ★ 幽灵 / 排行（未实现，已定位）

排行榜与幽灵都挂在 **`resultservice` / `playerstats`** 下，格式串在 `.rodata`：

```
%s/%s/resultservice/v1                                        @0xb87b2a  基址
%s/%s/resultservice/v1/robot_replaydata?track_id=%d&time=%d&player=%s   @0xb87a48  ← 取某个玩家的机器人回放（幽灵本体）
get_ghost?track_id=%d&players=%s&limit=1                       @0xb87a8e
get_ghost_timed?track_id=%d&players=%s&drive_time=%d&limit=1   @0xb87ab7
get_pvp_ghost?track_id=%d&players=%s&limit=1&pvpid=%d          @0xb87af4
%s/%s/resultservice/v1/leaderboard_percent?track_id=%s         @0xb8829a
%s/%s/resultservice/v1/enhancestats/%s                         @0xb87ea0
%s/%s/resultservice/v1/enhancestats/track%d                    @0xb87f66
%s/%s/resultservice/v1/enhancestats/batch_update               @0xb88034
%s/%s/playerstats/v1/ranking/%s?range=%d,%d                    @0xb88065
%s/%s/playerstats/v1/ranking/%s?around=%s,%d                   @0xb88091
%s/%s/playerstats/v1/ranking/%s?players=<pid,pid,…>            @0xb880be  ← 好友榜（"Friend leaderboard callback: %d" @0xb8f4b3）
%s/%s/playerstats/v1/stats/%s?players=%s                       @0xb880e7
%s/%s/playerstats/v1/ranking/legends?range=%d,%d               @0xb86867
%s/%s/playerstats/v1/ranking/legends?around=%s,%d              @0xb86898
%s/%s/pvp/v1/opponent?leaderboard=%d                           @0xb86302
%s/%s/friends/v1/update                                        @0xb897a8
%s/me/friends?fields=installed,first_name,last_name&access_token=%s  @0xb887ed   Facebook 好友
```

### 分数上报格式（游戏 → 服务器，POST body 模板）
```
{"updates": [ {"stats": {"data": %u,"drivetime": %d, "global_score": %f,"upgrades": %u,"submittime": %u, "extradata": %u }}]}   @0xb87ee8
{"updates": [ {"stats": {"data": %u,"drivetime": %d, "global_score": %f,"upgrades": %u,"submittime": %u }}]}                  @0xb87f92
,"track_name":"track%d"     @0xb88004
```
（`enhancestats/batch_update` 用它批量同步；日志串 `SYNCING %d LEADERBOARDS` @0xb8801c）

### ★ `data` / `extradata` / `upgrades` 的位布局（反汇编定论）
信源：`tr::LeaderBoardData::parseData(int)` @0x006250fc · `encodeData()` @0x00625178 ·
`parseData2(int)` @0x00625134（= `extradata`）· `encodeUpgrades()` @0x00625150；
`setOutfit(int,int)` @0x00625210 / `getOutfit(int) const` @0x00625250、
`setBikeSkin(int)` @0x0062526c / `getBikeSkin() const` @0x00625294。

```
data    : bits 0..7   = A（encodeData 夹到 ≤99，真机恒 0）
          bits 8..13  = C（6 位；掩码全 0 时 parseData 解出 1，encodeData 把 ≤1 归 0）
          bits 14..19 / 20..25 / 26..31 = 骑手 outfit 的 part2 / part1 / part0（各 6 位）
          ⇒ 低 6 位在 [x0+0x20..0x22]，part 的高 2 位在 [x0+0x29] 的第 part*2 位
          ⇒ outfit = 3×8 位 = 24 位 = 存档 `content.profile.outfit`（`& 0xFFFFFF`）
extradata: bits 0..3 = bikeSkin 低 4 位；bits 12..19 = [x0+0x29]（outfit 高位 + bikeSkin 高位）
          ⇒ **bikeSkin 只从 extradata 来**
upgrades: bit0..5 未用；bits 6..15 = 10 位；bits 16..19 / 20..23 / 24..27 / 28..31 = 四个 4 位
          （对应存档模板 "upgrades":{"bike_id","bike_lean","bike_speed","bike_grip",
           "bike_acceleration"} 里的四个数值，@0xb8c1e2）
```
- 实机校验：ccb `content.profile.outfit = 0x121212`（三个 18）↔ 榜行 `data = 0x49248100`
  解出 (18,18,18)；anon `0x171717` ↔ `0x5D75C200` → (23,23,23)。**榜行记的是那一场跑的时候
  穿的那套**，同一玩家会变（ccb 38 行里有 (47,47,47)/(23,23,23)/(18,18,18)/(8,8,8)）。
- 真行里观测到的 part 取值只有 8/18/23/47/48（**非 0**）；`outfit=0`（从未改装过的号，
  如华为账号 11 行全是）才出现 parts (0,0,0)，此时 `data=0x100`，而 `encodeData` 把 C≤1 归 0
  ⇒ **`data=0` 与 `0x100` 对客户端等价**、且 `0` 不是客户端会产生的值。
- 排行榜行的 stats 模板里**只有 `data`+`upgrades`**
  （`"stats": { "data": %u,"drivetime": %d, "global_score": %u,"upgrades": %u,"submittime": %u }`
  @0xb88339，另一份用 `score_value` @0xb88394）⇒ 客户端能从榜行读到的外观就这两个位域；
  `m_ghostBikeId` 在榜行里**没有载体**。
- 真实上报里 **`extradata` 恒缺**（`server-log.jsonl` 11058 条里只有 4 条是手写测试体）
  ⇒ `bikeSkin` 永远是 0。唯一带 `bike` 的上报是
  `{"profile_id":"%s","track_name":"track%d","drive_time":%d,"faults":%d,"bike":%d}` @0xb87b82
  （`resultservice/v1/replay_id`，实测 50 次）。
- 幽灵搜索端的响应键是 **`contents` / `contentId` / `content_id` / `pvpid`**（@0xb87d18 一带，
  **没有引号**，所以按 `"contents"` 搜会 0 命中）—— 那里也**没有任何外观字段**。
- 服务端实现：`server/tf_server.py:1395-1429`（`_lb_data` / `_LB_GHOST_OUTFITS` /
  `_lb_ghost_data` / `_ghost_appearance`）。
- 复现（用仓库里现成的工具，别再写临时脚本）：
  `python tools/re/symaddr.py <libTrialsGo.so> LeaderBoardData --sub` 拿地址 →
  `python tools/re/disasm.py <libTrialsGo.so> 0x6250fc 56` 看 `parseData`；
  `tools/re/callers.py <so> <符号>` 能追到**经 PLT** 的调用点。

### 幽灵的本地文件形态
```
ghost_%x_%d.bin                       @0xb87586   %x = 玩家 online-id 哈希，%d = 赛道 id
                                      → 设备上实测：ghost_0_1024.bin / ghost_6f857655_1041.bin 等 14 个，位于
                                        /data/data/<pkg>/files/
ghost_temp.bin                        @0xb879f1
/level/ghost/mission_%d_%d%s.bin      @0xb4e615   datapack 里的本地幽灵
pvp_ghost_%d_%d_%d.bin                @0xb8f61b
temp_mission_ghost-%X-%X.robo         @0xb861b5
robot_ghost-%X-%X.robot               @0xb87010
```
- 关键符号：`tr::OnlineDataContainer::{m_ghost, m_ghostName, m_ghostOnlineId, m_ghostBikeId, m_ghostOutfit, m_ghostBikeSkinIndex}`、
  `tr::GhostReplay::m_ghostAppearanceDefinitions`、`tr::OnlineCore::m_ghostManager`、
  `tr::RobotmanManager::ghostExistsFor(char const*, int)`、`tr::OnlineMission`。
- 响应里出现的字段名：`ghost_id` @0xb88519；错误串 `OnlineMultipleGhost : Ghost data missing` /
  `Failed to receive ghost data` / `OnNetworkError : %d`。
- 配置项（`/conf/ghostreplay.txt`、`mission_ghosts.txt`、`mission_ghosts_data_table.txt`）里有
  "ghost difficulty"、"Comma separated list of ghost file names …Tracks must be located in /level/ghost"。

### 幽灵 UI 入口
- 世界地图右侧「好友」标签页 = 好友成绩/幽灵；空列表时的文案是
  「没人做出成绩，赶快来新赛道抢独占鳌头！」（截图 `tmp/e4.png`）。
- 具体赛道页显示「可获得物品」+「N 开始竞赛」（截图 `tmp/e7.png`）。

## 商店 / offer 图片
- 三个字面量（`libTrialsGo.so`）：`https://s3.amazonaws.com/%s/info.json` @0xb85aea、
  `%s/%s.png` @0xb85da2、`%s/loc.json` @0xb85f75；`%s` = `frontieronlinecontent`。
- **bucket `frontieronlinecontent` 已 `NoSuchBucket`** —— path-style / virtual-host / us-east-1 全是 404。
- 另一条 CDN 线：`http://static-ww.cdn.ubi.com/0068/trialsfrontier/<sha>.zip`
  （来自 `/data/data/<pkg>/files/request.json`）**仍然活着**（HTTP 200，305198 字节，md5 与 request.json 一致），
  但内容只是交叉推广素材（6 张图 + 3 个 HTML），**不是** offer 图。
- 本地纹理包 `TrialsTexturesDL_android_offericons.dat`（2133660 字节）是私有格式（24 字节头 + 记录表，
  内部有 zlib 流），**不含** offer id 明文。
