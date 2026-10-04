# 幽灵仓库（`server/data/ghosts/`）

这个目录是离线服务器存放**比赛幽灵**的地方。幽灵 = 一次跑图的逐帧回放数据，
游戏用它在一场比赛里复现另一个玩家的跑法。

## 目录结构

```
server/data/ghosts/
├── README.md            本文件
├── INDEX.md             全部静态幽灵的清单（由 tools/ghost_index.py 生成）
├── <赛道id>/            ① 静态幽灵：随仓库分发，服务器按赛道直接取用
│   └── ghost_<owner哈希>_<赛道id>.bin
├── store/               ② 运行期仓库：客户端通过 userstorage v2 上传的幽灵
│   └── <contentId>.bin
├── index.json           运行期：contentId → 幽灵元数据映射（不入库）
├── replays.json         运行期：replay_id 登记（不入库）
└── inbox/               运行期：落单的裸二进制上传（不入库）
```

①②是同一个文件格式，服务器对客户端一视同仁；区别只是 ① 随仓库分发、
② 由客户端动态上传。`server/tflocal_accounts.py` 的 `ghost_any_for_track()`
优先看 ②，没有才回落 ①。

`.gitignore` 里 **`<赛道id>/*.bin` 已解除屏蔽**（这些是游戏自带的静态数据，
是离线环境唯一能让比赛出现「别人的幽灵」的素材，必须入库）；
`store/`、`index.json`、`replays.json`、`inbox/` 是玩家运行期数据，仍然不入库。

## 文件格式（已实测解出）

```
偏移   类型   含义
0x00   u32    version = 3
0x04   u32    tag（每个文件不同，疑似校验和/唯一 id）
0x08   u32    解压后的长度
0x0c   u32    0
0x10   ...    zlib 流（首两字节恒为 78 da）
```

解压后的载荷（`zlib.decompress(d[16:])`）：

```
0x00   u32    = 1
0x04   u32    这一次跑的时间，单位毫秒
0x08   u32    帧数
0x0c   u32    = 0
0x10   ...    帧数据
```

自检判据：`len(zlib.decompress(open(p,'rb').read()[16:])) == struct.unpack_from('<I', open(p,'rb').read(), 8)[0]`。

例：`1041/ghost_6f857655_1041.bin` 1888 字节 → 解压 2404 字节，
解压后 @0x04 = 0x6438 = 25656，与存档里 `highscores2` 中赛道 1041 的成绩
`[1041,25656,...]` 完全一致 ⇒ 确认 @0x04 就是该次跑的时间。

解析脚本见 `tools/ghost_index.py` 的 `probe()`。

## 命名约定

游戏自己用的文件名是 `ghost_<玩家 onlineId 哈希的十六进制>_<赛道id>.bin`：

* 哈希 `0` —— 本机最佳线路（游戏自己写出来的，不是从服务器下载的）
* 其它值 —— 该玩家的幽灵（例如 `6f857655` 是好友 6F857655，`99511744` 是本账号）

## 现在里面有什么

**44 个文件 / 30 条赛道 / 79441 字节**，全部通过 zlib 自检（逐条清单见 `INDEX.md`）：

* `6f857655` 4 个 —— 好友 6F857655 的真幽灵，**唯一真正来自「别人」的数据**：
  track 100 (11014ms)、1041 (25656ms)、1097 (22041ms)、66633 (22653ms)
* `0` 14 个 —— 本机占位幽灵：2, 4, 1024, 1033, 1036, 1037, 1041, 1062, 1068,
  1069, 1075, 1090, 1097, 1106
* `99511744` 26 个 —— 本账号跑出/上传过的线路：2, 4, 100, 1023, 1024, 1032, 1033,
  1036, 1051, 1062, 1068, 1069, 1070, 1075, 1087, 1088, 1090, 1097, 1099, 1123,
  1133, 1221, 1241, 1291, 65636, 66659

这三组都是从原版游戏真机上提取的，设备路径
`/data/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/`（需要 `adb -s <设备序列号> root`）。
**必须用 `adb pull`**：`adb exec-out "cat $f" | Set-Content -AsByteStream` 会把二进制
弄坏成 0 字节，`adb exec-out ... > "tmp\$f"` 会因为设备路径里的斜杠被当成子目录而失败。

## ★ 比赛幽灵在客户端是怎么被加载的（逆向结论）

给后来的人省一遍功夫。以下全部来自对 `tmp/libcmp/orig-libTrialsGo.so` 的反汇编。

唯一决策点是 **`tr::GameWorld::initGhostReplay(bool)` @`0x004c434c`**（3652 字节），
四个触发时机：`GameWorld::init`、`IngameStateSelectBike::beginRacing`（选车界面按开始）、
`LoadingStateLevel::update`、`GameWorldInterface::restartFromRewardScreen`（结算界面重跑）。

```
initGhostReplay(bool):
  w23 = *(*(0xe20000+0xa90) + 0x28c)          # 本局要跑的 ghost id
  if (w23 != 0 && OnlineDataContainer.ghostId(*(0xe20000+0x90)+0xefcc) == w23):
        GhostReplay::loadFromMemory(ODC)       # A. 内存里已装好的幽灵
        GhostReplay::initFromOnlineDataContainer()
        return
  if (!MissionManager::checkGhostOverride(w23, &r1..&r6, bool)):   # B. 覆盖项
        GhostReplay::uninit()                  # ★ 没有幽灵，清掉
        return
  slot = r5                                    # 命中的 slot 序号
  if (slot == -1):  GhostReplay::loadFromFile(ushort, ushort, int, int)  # B1. 内置关卡幽灵
  else:             OnlineGhostMissionManager::getOnlineGhostMissionGhostFileName(...)
                    GhostReplay::loadFromFile(name1, name2, ...)   # B2. 在线任务幽灵
```

三类来源：

| 来源 | 触发条件 | 代码路径 |
|---|---|---|
| **内存幽灵** | 在线对局实时收到，或 PvP `setGhostData(file, id)` | `GhostReplay::loadFromMemory` + `initFromOnlineDataContainer` |
| **在线任务幽灵** | `checkGhostOverride` 命中非 -1 的 slot，且该 section type==6 且子类型 2/3 | `OnlineGhostMissionManager` 哈希表 → `GhostReplay::loadFromFile(name...)` |
| **内置关卡幽灵** | `checkGhostOverride` 命中但 slot == -1 | `GhostReplay::loadFromFile(ushort, ushort, int, int)` → `mission_%d_%d%s.bin`，即 datapack 的 `/level/ghost/` |

要点：

1. **`checkGhostOverride` 返回 false ⇒ 这场比赛干脆没有幽灵**（走 `GhostReplay::uninit`）。
   所以「离线自己跑图看不到幽灵」不是 bug，是设计：幽灵只出现在带 ghost override
   的任务 / 在线对局里。`MissionManager::checkGhostOverride` @`0x005cb6e0` 是按任务 id
   在 `*(0xe20000+0x420)+0x2380` 处的 64 个 slot（stride 0x3c）里做**加权随机**
   （PRNG `ror(x ^ 0x1F00AEF3, 7)` / `ror(x ^ 0x4F4B5816, 7)`）挑一个覆盖项。
2. **「下载到的幽灵落盘」** = `OnlineDataContainer::saveGhostDataToFile` @`0x0056ec08`，
   只有三处调用：`OnlineMissionQuery::onGhostReceived`、`OnlinePVPRaceRequest::onGhostReceived`、
   `OnlineMultipleGhostObject::onGhostReceived` ⇒ 与服务器的 `userstorage/v2` /
   `resultservice/v1/robot_replaydata` 协议是同一条链。
3. **普通单人跑图不下载幽灵**：`PopupStateLoadGhost` 只有三个入口（在线任务 / 排行榜），
   而 `LeaderboardPlayerItem+0x84`（排行榜「点某人跑其幽灵」要用的 contentId）
   在客户端**从来没有任何地方从服务器 JSON 填过**（构造函数写 -1），
   所以那条路在客户端内部就是死的。
4. 关卡属性 **`OnlineGhost_OfflineGhost_Files`**（描述原文：「Comma separated list of
   ghost file names (as many files as ghosts). Tracks must be located in /level/ghost
   in a datapack just like all mission ghost files.」）是官方给的「离线内置幽灵」开关；
   设备上的 `TrialsContentExtraDL_LevelGhost.dat`（877168 字节，magic `734ce91d`，
   头 `[magic][291 条][entry size 12][data offset 0x930]`，**恰好 291 条 zlib 流**，
   解压总长 1214772 字节）就是配套的 DLC 数据包。
5. 尚未定位：`*(0xe20000+0x420)+0x2380` 那 64 个 slot 由谁填充
   —— 这决定了能否让**普通离线比赛**也出现幽灵。

## 服务器怎么用这些文件

* `GET /public/userstorage/v2/search/ghost/get_ghost?track_id=T&players=P&limit=1`
  → `{"contents":[{"contentId":N,"metadata":{...}}]}`
* `GET /public/userstorage/v2/content/ghost/<id>/payload` → 原始二进制
* `GET /public/resultservice/v1/replaydata/<track_id>` → 原始二进制
  （按 `ghost_any_for_track()` 取；没有就回 `{"data": []}`）
* `GET /public/resultservice/v1/replaydata?track_id=T` → **故意**回 `{"data": []}`，
  这是客户端上传前问「服务器上有没有我这条赛道的回放」，回「没有」才会把新幽灵传上来。
* 排障：`GET /__ghosts`（列出静态目录、`store/`、最近的 replay_id 登记）
