# Trials Frontier（特技摩托前线）离线化整合包

育碧已于 2023 年关闭《Trials Frontier》的服务器，官方客户端现在**连不上任何东西**：
开机就弹「下载暂停」「警报！逮到你了，呆子！」，之后卡在标题界面。

这个整合包让 **7.9.4（versionCode 561，arm64-v8a）** 版本重新变成一只能离线玩的单机游戏：
所有联网请求改指向你自己电脑上的一个 Python 服务器，广告与遥测被摘掉，
反作弊校验关闭，软货币实际上无限。

---

## 一、目录里有什么

```
dist/
├─ TrialsFrontier-offline.apk   改好的完整 APK（已签名，直接装）
├─ README.md                    本文件
├─ patcher/                     自己动手打补丁用的工具（纯 Python，无第三方依赖）
│   ├─ tfpatcher.py             一键 patcher（入口）
│   ├─ patch_native.py          native 库上的 7 处定点补丁
│   ├─ patch_dex.py             classes.dex 里的 2 个 Java 方法体改写
│   ├─ patch_dynaddr.py         给 .so 注入 DT_INIT，运行期读服务器地址文件
│   ├─ patch_urls.py            静态改写 libplayground.so 里的 URL
│   ├─ patch_manifest.py        改 AndroidManifest.xml
│   ├─ build_apk.py             逐条目重写 zip
│   └─ keystore/trials.jks      自用签名密钥（别名 trials；仓库不含密钥文件）
└─ server/
    ├─ tf_server.py             本地服务器（纯标准库）
    └─ rules.json               各个端点的响应规则，可热改
```

---

## 二、最快跑起来（三步）

前提：手机和电脑在同一个局域网；手机开着「USB 调试」。

### 1) 电脑上启动本地服务器

```powershell
cd dist\server
python tf_server.py
```

看到监听 8000 就行。**不要关这个窗口**，游戏全程要和它说话。
（首次运行如果被 Windows 防火墙拦，选「允许专用网络」。）

### 2) 装 APK

```powershell
adb install -r dist\TrialsFrontier-offline.apk
```

装好后**先别启动**，看一眼服务器地址：

* **走 USB（推荐，最稳）**：
  ```powershell
  adb reverse tcp:8000 tcp:8000
  ```
  这样手机上的 `127.0.0.1:8000` 会直通电脑的 8000 端口。带去的 APK 里**编译期默认地址就是
  `127.0.0.1:8000`**，所以这条路**不用建任何文件**，装完直接玩。

* **走 Wi-Fi（不用数据线）**：把电脑的局域网 IP 告诉游戏。在手机上建一个文本文件：

  ```
  /sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt
  ```

  内容就是一行地址，例如：

  ```
  192.168.1.100:8000
  ```

  用 adb 推最省事：

  ```powershell
  adb shell "mkdir -p /sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files"
  "192.168.1.100:8000" | Out-File -Encoding ascii tf_server.txt
  adb push tf_server.txt /sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt
  ```

  查电脑 IP：`ipconfig`，找 WLAN 那一节的 IPv4 地址。

### 3) 启动游戏

第一次进游戏会黑一会儿（在初始化）。能进到「村庄 / 大厅」就算成功。
任务、车库、比赛、改装、每日奖励都是通的。

---

## 三、改服务器地址不用重装

APK 里的服务器地址**不是写死在代码里**的。三个 native 库里各注入了一段 `DT_INIT` 钩子，
在库被加载的瞬间读上面那个 `tf_server.txt`，然后**就地改写 `.rodata` 里的所有育碧 URL**。

所以：

* 电脑 IP 变了 → 只改 `tf_server.txt` 那一行 → **重启游戏**即可，不用重装、不用重新签名。
* 文件不存在或者格式不对 → 回退到编译期写进去的默认地址，游戏不至于打不开。

文件格式很宽松：一行地址，前后空白会被忽略，例如 `192.168.1.100:8000` 或 `127.0.0.1:8000`。
不要写 `http://`（协议头由程序自己补）。

---

## 四、用 patcher 自己打一份

如果你已经有原版 APK（不想用我这份），可以自己生成一个：

```powershell
python dist\patcher\tfpatcher.py --apk 你的原版.apk --out 改好.apk
```

* 默认会校验原版 native 库的 SHA256（7.9.4 专用）。版本不符会拒绝，确认无误可加 `--force`。
* `--host 192.168.1.100:8000` 可以改「编译期默认地址」。
* `--no-sign` 只出未签名包；`--keep-v7a` 保留 32 位库（不推荐）。
* 需要 Android SDK 的 `zipalign` / `apksigner`（会自动在 `ANDROID_HOME`、`ANDROID_SDK_ROOT`
  或常见安装位置里找；找不到就退化成输出未签名 APK）。
* 签名密钥默认用 `patcher/keystore/trials.jks`；没有的话会尝试用 `keytool` 现场生成一个。

> 想覆盖安装在同一个应用上（保住存档），必须用**同一个签名密钥**。
> 本包附带 APK 是用一把自签的本地调试密钥（别名 `trials`）签的；
> **密钥文件与口令不随仓库分发**，只保留在本地 `patcher/keystore/`。

---

## 五、到底改了什么

### libTrialsGo.so —— 7 处定点字节补丁（合计 45 字节）

| 函数 | 改动 | 效果 |
|---|---|---|
| `tr::AntiCheating::isValid()` | `mov w0,#1; ret` | 反作弊校验恒通过 |
| `tr::ConsumableManager::isUnlimitedFuel(int)` | `mov w0,#1; ret` | **无限燃油** |
| `tr::OfferData::isBlackListed(int,bool)` | `mov w0,#0; ret` | 没有任何 offer 被拉黑 |
| `tr::PlayerItems::remove(int,int)` | `sub w11,w11,w2` → `add w11,w11,w2` | **花货币道具不减反增**（软货币实际无限） |
| `tr::DLContentManager::isDLReady()` | `mov w0,#1; ret` | 内容包视为就绪，不弹「下载暂停」 |
| `tr::MenuzStateMain::isUserBlackListed()` | `mov w0,#0; ret` | 不弹「警报！逮到你了，呆子！」 |
| `tr::AdInterface::initAndroid()` | `cbz` → `b`（直接跳到函数尾提前返回） | 原生侧广告永不初始化 |

最后一条很关键：全库**唯一**调用 `mz::TapjoyManager::init` / `mz::AdMobRewardedVideoManager::init` /
`mz::AdMobManager::init` 的地方就是 `AdInterface::initAndroid()`，掐掉这里，
Tapjoy 广告墙、AdMob 插屏/激励视频、Flurry、AdColony 全部不会再加载，
`placements.tapjoy.com` 之类的广告网络流量也一并消失。

> 补充：**Flurry 与 AdColony 在零售版里本来就是空壳**（`init` 就是一条 `ret`），
> 所有 `mz::AdXTracker::*` 遥测函数也都是空壳。真正还活着的广告只有 Tapjoy 与 AdMob。

### classes.dex —— 6 处改写（Java 侧广告 + 遥测）

四个方法体整体变成 `return-void`：

| 方法 | 原实现 | 效果 |
|---|---|---|
| `CustomNativeActivity.initAdMobRewardedVideoAds` | `MobileAds.getRewardedVideoAdInstance` + `setUserId` + `setRewardedVideoAdListener` | 不再初始化 Google Mobile Ads |
| `CustomNativeActivity.tapjoyInit` | `Tapjoy.connect` + 建 `TJPlacement` | 不再连接 Tapjoy 广告网络 |
| `Crashlytics.log` / `Crashlytics.logException` / `Crashlytics.setString` | 走 `checkInitialized()` → `Fabric.getKit()` 并写埋点 | 埋点变空操作 |

外加把 `CustomNativeActivity.onCreate` 里的**一条**指令换成 `nop`：

| 指令 | 效果 |
|---|---|
| `invoke-static {v0}, Lio/fabric/sdk/android/Fabric;->with(...)` | Fabric 永不初始化 → Crashlytics 崩溃上报与 Fabric/Answers 分析遥测全部不启动 |

改完 logcat 里 `Tapjoy|Flurry|AdMob|AdColony|offerwall|placements|E/Ads|MobileAds`
以及本进程的 `Crashlytics|Fabric|Answers` **全部零命中**。

> 只砍 `Fabric.with(...)` 而不管 `Crashlytics.*` 会让游戏**直接崩**：`onCreate` 后面还会调
> `Crashlytics.setString("Build_Type", ...)`，它内部 `checkInitialized() -> getInstance()
> -> Fabric.getKit() -> Fabric.singleton()` 在 Fabric 未初始化时抛
> `IllegalStateException: Must Initialize Fabric before using singleton()`。
> 所以必须把那三个静态方法一并变空方法（只有 `CustomNativeActivity` 与 `Crashlytics` 自己引用这个类）。

> dex 实现细节（踩过的坑）：方法体是**只把 `insns[0]` 写成 `return-void`、其余 code unit 全部填 `nop`**，
> **`insns_size` 一个字节都不动**。实测如果缩短 `insns_size`，ART 会直接拒绝整份 `classes.dex`
> （启动即 `ClassNotFoundException`，`DexPathList` 里一个类都找不到）。
> 填 `nop` 而不是按指令宽度截断，是为了不依赖 opcode→宽度表；
> 单条 `nop` 替换则要求"匹配到的指令必须正好 1 条"，宁可不改也不误伤。

### AndroidManifest.xml

`targetSdkVersion` **30 → 27**。targetSdk < 28 的应用默认允许明文 HTTP，
这样 Java 侧的 DLC / 内购校验也能走 `http://` 连你的本地服务器。
（`minSdkVersion=16` 未动；没有加 `usesCleartextTraffic`，也没有加 `networkSecurityConfig`。）

### 服务器地址重定向

三处：

* `libTrialsGo.so` 与 `libubiservices.so`：注入 `DT_INIT` 钩子，运行期读 `tf_server.txt`
  并就地改写 `.rodata` 里所有育碧 URL（14 + 1 处）。
* `libplayground.so`：这个库**代码段已被完全填满**（没有任何 ≥64 字节的零洞，可执行段里也没有空隙），
  塞不进钩子，只能编译期静态改写（1 处）。

### 还被丢掉的

* `lib/armeabi-v7a/` 下 7 个 32 位库（它们没打补丁；丢掉可保证 64 位设备一定用到改过的库）。
* 旧的 `META-INF/*.SF|RSA|MF` 签名（重打包后必须重签）。

---

## 六、本地服务器现在实现到什么程度

`server/tf_server.py` 是个「记录一切、能回答的都回答」的桩服务器：

| 端点 | 状况 |
|---|---|
| `GET /public/timeservice/v1/gettime` | **真实现**。返回 `{ret, time_now, checksum}`，`checksum = md5(str(time_now) + "c8f68210a7247676aaee552cb6d81c8a")`。这个盐是从 `libTrialsGo.so` 里挖出来的，不匹配或时间对不上就弹「每日奖励」失败并重启反作弊校验 |
| `POST /v3/profiles/sessions`、`GET /v1/profiles/sessions` | **伪造的育碧账号会话**（ticket / profileId / sessionId 全套），SDK 层认为已登录 |
| `GET /v1/applications/<appid>/configuration` | **真实现**。返回 `configuration.sandboxes.<name>.{name,friendlyName,url}`。客户端 `parseConfigurationJson` 只认 `friendlyName == "triag_an_lnch61_a_ws"` 或 `"android_beta"` 的 sandbox，写错就不生效 |
| `GET /`（gamecfg）、`/ingame/.../News/`、`/public/targeting/...`、`/dlcontent_.../info.json` | 桩（返回 `{}`），够用 |
| `GET /public/receiptvalidation/v1/product/configuration` | 目前走兜底返回 `{}` |
| 其它任何请求 | 兜底 200 `{}` |

想看游戏到底在请求什么：

* 浏览器打开 `http://127.0.0.1:8000/__log` → 最近 100 条请求的完整记录。
* 或者看 `work/trials-frontier/notes/server-log.jsonl`（每行一条 JSON，含请求头/请求体/响应体/耗时）。
* `http://127.0.0.1:8000/__ping` → `pong`，用来确认服务器活着。

`rules.json` **每次请求都重新读**，改完存盘立刻生效，不用重启服务器。

---

## 七、已知限制

* **只能 arm64-v8a**。32 位库没打补丁，且包里已经删掉。
* **原版数据包必须还在**。这游戏的内容（赛道、模型）是下载到
  `/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/` 下的 `content.dat`
  等文件里的，删了就没内容了 —— **只能删存档，不能删数据包**。
* **真钱内购（Google Play IAP）没有伪造**。`tr::StoreManager::purchase` 有两条路径：
  标为 server item 的走「服务器发奖」，其余的走 Google Play。后者没有做假的成功回调。
  不过实机上软货币已经无限（`PlayerItems::remove` 被改成加法），普通商店里能用货币买的东西全部免费。
* **联机功能不可用**（本来就已停服）：排行榜、好友、邮件、社交这些只是返回空数据或少数写死的假数据。
* 服务器是**开发用桩**，不适合直接暴露到公网。

---

## 八、本轮修复（登录崩溃）与仍然缺的东西

### 8.1 已修：登录育碧账号会崩游戏

根因：登录成功后 `tr::OnlineAuthentication::setAuthenticated`（`libTrialsGo.so` @`0x4ec228`）
会调 `tr::OnlineFriends::updateFriendList`（@`0x51cb38`），后者请求
`GET <服务器>/v2/profiles/me/friends`，响应用
`tr::OnlineFriends::onFriendlistRecieved(json_value*)`（@`0x51cee8`）解析。

那个解析器**没有检查第一层节点是否为空**：
```
0x51cf18  ldr x8, [x0, #0x10]     ; root->child
0x51cf1c  ldr x28, [x8, #0x10]    ; child->child  ← root->child 若为 NULL 就炸在这里
```
服务器以前对未知路径一律回 `{}`，于是 `root->child == NULL`，
`ldr x28,[x8,#0x10]` 读地址 `0x10` → `SIGSEGV, fault addr 0x10` → **游戏秒崩**。

修复（`server/rules.json`）：

1. 新增 `GET /v2/profiles/me/friends` → `{"friends": [...]}`（形状必须是
   `{"<任意键>": [ {对象}, … ]}`；字段 `pid` / `nameOnPlatform` / `state`）。
2. 新增 `GET /v3/policies/`、`POST /v1/profiles/sessions`、`GET /v2/profiles/me`、
   `GET /v1/profiles`。
3. **把兜底 `"*"` 从 `{}` 改成 `{"data": []}`**。`{}` 是最危险的选择：所有
   「两级解引用」式解析器都会撞 NULL。改成 `{"data": []}` 后 `root->child` 非空、
   它的 child 是空数组（NULL），这类解析器会走 `cbz` 安全跳过。

实测（`adb`）：登录后 `GET /v2/profiles/me/friends` 返回 200，
**进程存活、无 SIGSEGV**，并且弹出的「好友」面板（全部好友 / 建议 / 要求三个标签）可以正常打开。

> 默认给的是两个写死的假好友（`GhostRider` / `TangoPro`）。如果哪个客户端因此出问题，
> 把 `rules.json` 里那条规则的 `body` 换回 `{"friends": []}` 即可 —— 空列表是绝对安全的。

### 8.2 仍然缺：商店 /「特供商品」里的动态 offer 图

这些图不走本地纹理包，而是远程拉的：

```
https://s3.amazonaws.com/frontieronlinecontent/<offer_id>.png
```

**那个 S3 bucket 已经 `NoSuchBucket` 了**（path-style / virtual-host / us-east-1 全试过，都是 404），
素材永久丢失。游戏日志里能看到它请求过的名字：
`donkey_kick_bundle`、`offer_item_flamingtango`、`offer_item_retention_pack`、`redbull_outfit`、
`50_milliion_downloads`、`70_fuel_upgrade`、`grid_domination`、`holiday_haze`、
`minievent_1_graphic`、`mithril_mantis_bike_skin`。

现在服务器对**任何** `*.png/.jpg/…` 以及 `…/picture?...` 请求回一张自绘的占位图
（`tf_server.py` 的 `_placeholder_png()`，棕底金框斜纹，2868 字节），
所以页面不会出现空白或破图，但**不是原来的美术资源**。

> 顺带查明：另一条育碧静态 CDN `http://static-ww.cdn.ubi.com/0068/trialsfrontier/<sha>.zip`
> **还活着**（来自 `/data/data/<pkg>/files/request.json`，305198 字节，md5 一致），
> 但里面只有交叉推广素材（6 张图 + 3 个 HTML），不是 offer 图。

### 8.3 仍然缺：幽灵（Ghost / 对手回放）

幽灵和排行榜都挂在 `resultservice` / `playerstats` 下，端点已经全部定位（见
`work/trials-frontier/notes/online-endpoints.md`）：

```
<base>/<ns>/resultservice/v1/robot_replaydata?track_id=%d&time=%d&player=%s   ← 幽灵本体
<base>/<ns>/resultservice/v1/get_ghost?track_id=%d&players=%s&limit=1
<base>/<ns>/resultservice/v1/get_ghost_timed?track_id=%d&players=%s&drive_time=%d&limit=1
<base>/<ns>/resultservice/v1/get_pvp_ghost?track_id=%d&players=%s&limit=1&pvpid=%d
<base>/<ns>/playerstats/v1/ranking/%s?range=%d,%d
<base>/<ns>/playerstats/v1/ranking/%s?players=<pid,pid,…>      ← 好友榜
<base>/<ns>/pvp/v1/opponent?leaderboard=%d
```

本地幽灵文件形态：`ghost_%x_%d.bin`（`%x` = 玩家 online-id 哈希，`%d` = 赛道 id），
设备上实测有 `ghost_0_1024.bin`、`ghost_6f857655_1041.bin` 等 14 个，在
`/data/data/<pkg>/files/` 下。

**还没有实现**：这些端点现在返回兜底 `{"data": []}`，所以游戏里没有幽灵、没有排行榜名次。
要做的话得先搞清 `robot_replaydata` 的响应二进制格式。

### 8.4 关于「数据包不完整」的实测结论

`/data/data/<pkg>/files/` 下确实有约 200 MB 的内容（`TrialsContentExtraDL_*.dat`、
`TrialsTexturesDL_android*.dat`、`ghost_*.bin`、`player.bin`、`dl_content.state` 等），
外部 `/sdcard/Android/data/<pkg>/files/` 下另有 `content.dat`(24 MB)、
`contentSFX.dat`(5.6 MB)、`textures_android.dat`(37 MB)。

但**offer 图不在这些包里**：`TrialsTexturesDL_android_offericons.dat`（2.1 MB）是私有格式
（24 字节头 + 记录表 + 内部 zlib 流），里面**没有** offer id 明文，也没有 `.png` 字样。

所以「村庄英雄包没图」不是数据包没下完，而是**那张图本来就在已经死掉的 S3 上**。

**重要**：新装用户如果原版数据包没下过（服务器上 `dlcontent_frontier_android/…/info.json`
现在是兜底空响应），内容就下不下来。请把 `/data/data/<pkg>/files/` 与
`/sdcard/Android/data/<pkg>/files/` 整个备份，换机时一起拷过去。

---

## 九、本地账号 / 存档 / 幽灵 / 内购（新）

### 9.1 账号系统（用户名 + 密码 + 票据）

服务器现在会真的校验账号。数据全在 `server/data/`：

| 文件 | 内容 |
| --- | --- |
| `data/accounts.json` | 账号表：用户名、盐、口令散列（sha256(盐+用户名+口令)）、profileId、nameOnPlatform |
| `data/sessions.json` | 已签发的会话票据（保留最近 200 张） |
| `data/save/<profileId>/latest.json` | 该账号最近一次上报的存档 |
| `data/save/<profileId>/history/<时间戳>.json` | 历史存档（保留最近 20 份） |
| `data/ghosts/<赛道id>/*.bin` | 幽灵文件（见 9.3） |

* **登录怎么走**：客户端把 `用户名:口令` base64 后放进
  `Authorization: Ubi_v1 t=<base64>`，POST 到 `/v1/profiles/sessions` 或
  `/v3/profiles/sessions`。
* **第一次登录某个用户名 = 自动注册**（`salt` 随机、`profileId` 由用户名
  uuid5 派生，所以同一个用户名永远是同一个存档槽）。
* **口令不对 → HTTP 401**，游戏会走登录失败分支。
* 登录成功后服务器发票据 `tf-local-<用户名>-<随机>`；之后所有请求带
  `Authorization: Ubi_v1 t=<票据>`，服务器据此知道"这是谁"。
* 游戏自己那种**设备静默登录**（`Authorization: UbiMobile_v1 t=...`）会被
  当成匿名账号，沿用固定的 `11111111-1111-1111-1111-111111111111`，
  这样以前存的进度不会因为升级服务器而"换人"丢失。

管理端点（浏览器/curl 直接看）：

```bash
curl http://127.0.0.1:8000/__accounts   # 账号列表（不含口令/盐）
curl http://127.0.0.1:8000/__sessions   # 在线票据
curl http://127.0.0.1:8000/__saves      # 有存档的账号概览
curl http://127.0.0.1:8000/__save?profile=<profileId>   # 取回完整存档
curl http://127.0.0.1:8000/__ghosts     # 幽灵库
curl http://127.0.0.1:8000/__help
```

实测：

```bash
# 第一次登录 = 注册
curl -i -X POST http://127.0.0.1:8000/v3/profiles/sessions \
     -H "Authorization: Ubi_v1 t=$(printf 'zhangsan:<口令>' | base64)" \
     -H 'Content-Type: application/json' -d '{}'
# 口令错 → 401
```

存档本身是游戏主动 POST 上来的：

```
POST /public/playerprogress/v1/progress
{"items2":[...], "highscores2":[[赛道id, 时间毫秒, ...], ...],
 "statistics2":{...}, "achievements2":[...], "checksum":"...",
 "identifier":"...", "game_version":795, ...}
```

服务器把它原样落盘。**注意**：目前只做"存"，还没做"自动下发恢复"——
`GET /public/playerprogress/v1/progress` 要带 `?download=1` 才会回真实存档，
这是故意的：云端恢复的响应形状没在真机上验证过，改错会让游戏崩。

### 9.2 内购（IAP）

* `GET /public/receiptvalidation/v1/verify_android?pid=..&uid=..&transaction_id=..`
  → 现在**一律放行**（`{"valid":true,"status":0,"errorCode":0,"ret":true}`）。
  原来的兜底响应是 `{"data": []}`，等于校验失败。
* `GET /public/receiptvalidation/v1/product/configuration` → 仍然返回空商品表。
  **商品表的响应形状没有逆向出来**（只知道顶层键 `product_list`、条目里有
  `ubi_product_id`、商品 id 形如 `tfr.mission.wheelofortune`），
  **没有把握的事不做**，所以先保持原样并打日志。
* 真正要"破解内购"还差一步：Google Play 结算走 **Java 侧**，`mz::IAPManagerAndroid`
  通过 JNI 调它。要么继续逆 Java 结算类，要么把 `mz::IAPManagerAndroid::queryProducts`
  / `purchase` 在原生层改写掉。这条没做完。

**现在免费买买买靠什么**：`PlayerItems::remove` 的 `sub` 被改成 `add`
（第 4 条 native 补丁），花金币/零件类道具时数量不减反增；
`ConsumableManager::isUnlimitedFuel` 恒真所以燃油永远满。
宝石（高级货币）走的是另一条扣款路径，**没有被这条补丁覆盖**，
所以宝石是真的会减少——商店里标💎的东西买多了会用完。

### 9.3 幽灵（Ghost）

**幽灵文件格式已经解出来了**：

```
偏移   类型   含义
0x00   u32    version = 3
0x04   u32    tag（每个文件不同，疑似校验和/唯一 id）
0x08   u32    解开后的长度
0x0c   u32    0
0x10   ...    zlib 流（首两字节恒为 78 da）
```

解开之后：

```
0x00   u32    = 1
0x04   u32    这一次跑的时间，单位毫秒
0x08   u32    帧数
0x0c   u32    = 0
0x10   ...    帧数据（每条轨迹的采样）
```

自检：`len(zlib.decompress(open(p,'rb').read()[16:])) == u32@0x08`。

验证：`ghost_6f857655_1041.bin` 里 @0x04 = 0x6438 = **25656 毫秒**，
和存档 `highscores2` 里赛道 1041 的成绩 `25656` 一模一样 ⇒ 确认这个字段就是成绩。

服务器怎么用：

* 游戏请求 `GET /public/resultservice/v1/.../robot_replaydata?track_id=..&time=..&player=..`
  （以及 `get_ghost` / `get_ghost_timed` / `get_pvp_ghost`）时，
  服务器按 `track_id` 去 `data/ghosts/<赛道id>/` 里挑一个 `.bin`，**原样二进制发回**
  （`Content-Type: application/octet-stream`）。
  依据：`tr::OnlineGhostManagerListener::onGhostReceived(TR_ONLINE_ERROR,int,void*,int,int)`
  和 `submitGhost(..., void*, ...)` 都是"原始字节 + 长度"。
* 目录里没有该赛道的文件 → 退回 `{"data": []}`（和以前一样，客户端能安全消化）。
* 如果游戏反过来上传幽灵（POST），前 4 字节是 `03 00 00 00` 就会被存进库里。

**现在库里有什么**：`data/ghosts/1041/` 和 `data/ghosts/66633/` 各有一个
真的从原版游戏设备上抓下来的**别人的**幽灵（`ghost_6f857655_*.bin`）。
想加更多：把 `.bin` 丢进 `data/ghosts/<赛道id>/` 就行，不用重启。

**还没做的**：`OnlineGhostManager::getGhost` 那条链不走 URL，走的是育碧的
`userstorage/v2/*` 协议（`/userstorage/v2/search/...`、`/userstorage/v2/content/.../payload`），
要先把那套协议实现了才能在"排行榜/好友成绩"里看到别人的幽灵。
现在排行榜页还是显示"没人做出成绩"。

### 9.4 已知不足（老实说）

| 功能 | 状态 |
| --- | --- |
| 去广告 + 去遥测 | ✅ 完成（native 补丁 + dex 改写，两种路线都实测无日志） |
| 反作弊弹窗 / 下载暂停弹窗 | ✅ 已消除 |
| 免费软货币（金币/零件）| ✅ `PlayerItems::remove` sub→add |
| 无限燃油 | ✅ |
| 宝石（高级货币）| ❌ 没破解，真的会扣 |
| 真钱内购（Google Play）| ❌ 没做完（Java 结算类没逆） |
| 账号 / 密码 / 票据 | ✅ 完成 |
| 存档上传落盘 | ✅ 完成 |
| 存档自动恢复下发 | ⚠️ 代码在（`?download=1`），默认关着，因为响应形状没验证 |
| 幽灵文件格式 / 回放数据下发 | ✅ 完成 |
| 排行榜 / 好友成绩页 | ❌ 需要 `userstorage/v2` 协议 |
| 商店/offer 图片 | ⚠️ 原始素材在原育碧 S3 上已永久丢失（`NoSuchBucket`），服务器改成发占位图 |

---

## 十、真钱内购（IAP）完整破解 —— 已实机验证

### 10.1 为什么不能靠服务器
反汇编 `libTrialsGo.so` 证明：`tr::StoreManager::onNetworkDataReceived` @`0x0057b0cc` 的
`cmd == 0x17` 分支**只是再调一次 `mz::IAPManager::purchase()`**（代码在 `0x0057b1a4`，
失败则 `MenuzStateMachine::popInstant(0)` + `OnlineError::showOnlineError(3)`）。
所以要靠"我们自己的服务器回一个成功响应"来发奖是走不通的。
另外 `StoreManager::purchase(listener, productId, viaServer)` @`0x00579508` 里
`viaServer = strstr(productId, "goldenticket") != NULL`——只有黄金门票走服务器，
其余真钱商品一律走 Google Play。

### 10.2 为什么"改道本地货币路径"也不行
`tryPurchaseItem` / `purchaseItem` 里的 `cbz x22, <本地路径>` 确实是个分岔，
但真钱礼包的 `getPriceHard/getPriceSoft/getPriceChips` 全是 0（价格来自 Google Play 商品表），
改道过去只会**静默返回**：不扣钱、不弹窗、什么都没有——用户看到的就是"点了没反应"。
这两条补丁已废弃。

### 10.3 正确的补丁（两条，各 8/12 字节）
真正**无条件发奖**的是 `tr::StoreManager::onPurchaseComplete(IAPItemInfo*, IAPReceipt*)`
@`0x00579940`（3296 字节）：全程不读收据、不发任何网络请求，直接
`PlayerItems::setItemCount` + `StoreItemManager::handleItemPurchase` + `switchServer`。
它是 `mz::IAPManagerListener` vtable 的**槽 0**；失败/取消路径分别走槽 `0x08` / `0x10`，
即 `onPurchaseFailed(int, IAPItemInfo*)` @`0x0057a9a8` 与
`onPurchaseCancel(IAPItemInfo*)` @`0x0057aa04`，这两个函数只做 UserTracker 打点并弹「购买失败。」。

把它们改成尾调用 `onPurchaseComplete`：

| 补丁 id | 符号 | 字节改动 |
| --- | --- | --- |
| `iap-failed-redirects-to-complete` | `_ZN2tr12StoreManager16onPurchaseFailedEiPN2mz11IAPItemInfoE` | `f3 0f 1e f8 fd 7b 01 a9 fd 43 00 91` → `e1 03 02 aa e2 03 1f aa e4 fb ff 17`（`mov x1,x2 ; mov x2,xzr ; b 0x579940`） |
| `iap-cancel-redirects-to-complete` | `_ZN2tr12StoreManager16onPurchaseCancelEPN2mz11IAPItemInfoE` | `f3 0f 1e f8 fd 7b 01 a9` → `e2 03 1f aa ce fb ff 17`（`mov x2,xzr ; b 0x579940`） |

`x2 = IAPReceipt*` 传 NULL 是安全的：`onPurchaseComplete` 内部 `0x00579ad0` 与 `0x00579e90`
两处都是 `cbz x20, ...` 先判空再解引用。

### 10.4 实机结果（小米 8 / LineageOS 22.2，无 Google Play 服务）
- 商店 → 宝石 → 「宝石城堡 5 800 宝石 11.00 $」→ **弹出「谢谢你的购买！ 5 800 宝石」**，
  HUD 宝石数当场 `27 475 → 33 275`（正好 +5 800）。
- 全程**没有**任何购买相关的服务器请求（这条链路完全在客户端本地完成）。
- 截图 `tmp\m13f.png`。

### 10.5 交付物
`TrialsFrontier-offline.apk` 已更新为含上述两条补丁的版本
（SHA-256 `8077D174C0A47EC2AE4CCF9112AE1317D07C736FDE7BB717CF1C6676D063E93D`，
26 906 224 字节）。旧的基线版备份在 `tmp\build\tf-m8-release-backup.apk`。
`tools/patch_native.py` 的 `PATCHES` 已同步，`--dry-run` 自检 10 条全 `[OK]`。
