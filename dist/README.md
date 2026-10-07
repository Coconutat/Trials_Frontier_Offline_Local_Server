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
├─ 原版APK/                      apkmirror 下的**未改动原版**（打补丁认准它当 base）
├─ TrialsFrontierPatcher.exe    带界面的打补丁器（不用装 Python，见第四节）
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

看到横幅里的「监听 0.0.0.0（所有网卡…）:8123」就行（**默认端口是 8123**；带去的 APK 编译期默认地址是
`127.0.0.1:8000`，想跟它对齐就用 `python tf_server.py --port 8000`，或干脆按 §三 写一份 `tf_server.txt`）。
**不要关这个窗口**，游戏全程要和它说话。
（首次运行如果被 Windows 防火墙拦，选「允许专用网络」。）

> **连不上**（手机 / 别人的电脑打不开 `http://<IP>:<端口>/__ping`）？按这个顺序排：
> 1. **端口**：默认 8123（服务器读 `<程序目录>/port.txt`，`--port` 可覆盖）。对方要填的是**启动横幅印出来的那个**。
> 2. **同一个局域网**：`192.168.x.x` 只在同一个路由器下有效，不能跨网段、更不能走公网；
>    手机连的是访客网络 / 开了 AP 隔离也一样连不上。
> 3. **防火墙**：Windows 的入站放行是**按程序绝对路径**记的 —— 把 exe 换个目录会再弹一次，
>    这次点「取消」就一直连不上。去「允许应用通过防火墙」里确认列表里有那个 exe（专用 + 公用都勾）。
> 4. **别用 `--host 127.0.0.1`**：那等于只让本机连。
>
> 启动横幅会直接印出「手机/其它设备用： `http://<IP>:<端口>/__admin`」和这几个排查点；
> `/__ping` 返回 `pong` 才算网络通，而且**控制台会留下一行 `来源IP  PING  pong`** ——
> 对方说「连不上」时，先看有没有这一行：有 = 包到了（问题在客户端的地址配置），没有 = 没到（网络/防火墙）。

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
* **base 认准 `原版APK/` 里那份**（apkmirror 的原始包，34 312 425 字节，sha256
  `EDDD7DF0C482279B523255498DB448F5CE27609D8BCB1E0B94C45D5948225580`，`libTrialsGo.so` = `743f945c…`）。
  ⚠ **别拿 `TrialsFrontier-offline.apk` / `TrialsFrontier-offline-full.apk` 当「干净 base」**：这两个是
  **已经改过的产物**（`libTrialsGo.so` = `e9f2fa1a…`、targetSdk 已是 27、v7a 已删），
  这个 SHA256 校验会直接拒绝它们 —— 想复现原始改动就得用 `原版APK/` 那份。
* `--host 192.168.1.100:8000` 可以改「编译期默认地址」。
* `--no-sign` 只出未签名包；`--keep-v7a` 保留 32 位库（不推荐）。
* 需要 Android SDK 的 `zipalign` / `apksigner`（会自动在 `ANDROID_HOME`、`ANDROID_SDK_ROOT`
  或常见安装位置里找；找不到就退化成输出未签名 APK）。
* 签名密钥默认用 `patcher/keystore/trials.jks`；没有的话会尝试用 `keytool` 现场生成一个。

> 想覆盖安装在同一个应用上（保住存档），必须用**同一个签名密钥**。
> 本包附带 APK 是用一把自签的本地调试密钥（别名 `trials`）签的；
> **密钥文件与口令不随仓库分发**，只保留在本地 `patcher/keystore/`。

### 不想敲命令：`TrialsFrontierPatcher.exe`（带界面，不用装 Python）

`dist\TrialsFrontierPatcher.exe` 是上面那套脚本的图形版，双击就开（`-console.exe` 是同内容的命令行版）：

1. **原版 APK** 选你的包（**要自包含打包的话必须是未加固的原版**，加固包会在第 4 步报错让你换包）；
2. **功能** 勾选 —— 默认只勾「离线可玩（核心）」和「去广告 / 去遥测」，
   另外可选 `无限汽油` / `货币不减反增` / `破解内购` / `解锁骑士俱乐部 VIP` / `打包成自包含完整 APK`；
3. 要自包含就把 `payload\` 放在 exe 同目录（里面有 `appdata\` 与 `obb\`，即
   `TrialsFrontier-clean-pack` 里那两份），GUI 会自动认出来；
4. 填服务器地址 → 点「开始打补丁」，日志实时打在窗口里，产物旁会写一份 `<产物>.report.json`。

命令行同样能用（不带参数 = 开界面）：

```powershell
TrialsFrontierPatcher-console.exe --check                       # 环境自检
TrialsFrontierPatcher-console.exe --list-features
TrialsFrontierPatcher-console.exe --cli --apk 原版.apk --out out.apk `
    --server 192.168.5.2:8123 --features offline,noads,fuel
```

exe 里已含 AArch64 汇编器与 ELF 解析（不需要 `pip install`），但**仍然需要**：
Android SDK 的 `zipalign`/`apksigner`，以及任意一个 JDK（`java`/`keytool`）。
签名密钥与源码态共用 `patcher/keystore/trials.jks`，没有就现场自签一把。

---

## 五、到底改了什么

### libTrialsGo.so —— 17 处定点字节补丁（合计 237 字节）

| 函数 | 改动 | 效果 |
|---|---|---|
| `tr::AntiCheating::isValid()` | `mov w0,#1; ret` | 反作弊校验恒通过 |
| `tr::ConsumableManager::isUnlimitedFuel(int)` | `mov w0,#1; ret` | **无限燃油** |
| `tr::OfferData::isBlackListed(int,bool)` | `mov w0,#0; ret` | 没有任何 offer 被拉黑 |
| `tr::PlayerItems::remove(int,int)` | `sub w11,w11,w2` → `add w11,w11,w2` | **花货币道具不减反增**（软货币实际无限） |
| `tr::DLContentManager::isDLReady()` | `mov w0,#1; ret` | 内容包视为就绪，不弹「下载暂停」 |
| `tr::MenuzStateMain::isUserBlackListed()` | `mov w0,#0; ret` | 不弹「警报！逮到你了，呆子！」 |
| `tr::AdInterface::initAndroid()` | `cbz` → `b`（直接跳到函数尾提前返回） | 原生侧广告永不初始化 |
| `tr::StoreManager::onPurchaseFailed(int,mz::IAPItemInfo*)` | 头部改成 `mov x1,x2; mov x2,xzr; b onPurchaseComplete` | **真钱内购失败即当成功**（见 §10） |
| `tr::StoreManager::onPurchaseCancel(mz::IAPItemInfo*)` | 头部改成 `mov x2,xzr; b onPurchaseComplete` | 同上，覆盖取消路径 |
| `tr::VIPManager::getPlayerMembership()` ×5 | 把两处 `ldr w8,[x0]` 前移成 `cbz x0` 守卫 | **修掉联网闪退，并让真实会员状态可被读取**（见 §11、§12.2） |
| `tr::OfferManager::findVIPOffers(...)` + 代码洞 | 那条 `bl IAPManager::getProductInfoEnabled` 改跳进 `0x0096d85c` 的代码洞，洞里 `adrp/add/ret` 返回一个伪造的 `IAPItemInfo` | **离线也让 `isVIPStoreOfferAvailable()` 为真 → 骑士俱乐部档位出现并可购买 → 触发 VIP 下发**（见 §12.2） |

最后两条配合起来才完整：`getPlayerMembership` 的守卫负责「读得到会员状态」，
`findVIPOffers` 的代码洞负责「离线也能买到会员」。只修前者时，骑士俱乐部两档
都显示「剩余时间：未知（离线）」且没有购买按钮。

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
| `GET /public/receiptvalidation/v1/product/configuration` | **真实现**。客户端 `StoreManager::parseStoreConfiguration` @`0x0057b30c` 只认顶层键 `limited_purchases`（数组，元素字段 `name` / `product_id` / `limit` / `counter` / `fake_counter`）。空数组是安全的 |
| `POST /v3/profiles/sessions`（登录） | **真实现 + 登录固化**。响应里必须带 `rememberMeTicket`，客户端会把它存进安全存储，下次启动静默换会话，不必再手输账号 |
| `POST /public/resultservice/v1/enhancestats/track<ID>` | **真实现**。真实跑图成绩落库，按「账号 + 赛道」唯一，只保留更快的 `drivetime` |
| `GET /public/playerstats/v1/ranking/<board>`、`.../stats/<board>` | **真实现**。赛道榜读落库数据；`global_stats` / `global_stats_donkey` 由赛道记录**实时聚合**（不落库），没跑过的赛道与账号不会出现 |
| `POST /public/resultservice/v1/enhancestats/batch_update` | **真实现**。逐条取 `stats.drivetime > 0` 的更新入库（`drivetime` 为 0 的是「解锁但没跑」的占位行，必须丢） |
| `POST /public/userstorage/v2/content/ghost` | **真实现**。建幽灵容器并回 `{"contentId": N}`（客户端拿它当后续 PUT/GET 的 id；回空数组会退化成 id 0） |
| `PUT /public/userstorage/v2/content/ghost/<N>/payload` | **真实现**。收幽灵二进制本体（`application/octet-stream`），写 `data/ghosts/store/<N>.bin` |
| `PUT /public/userstorage/v2/content/ghost/<N>` | **真实现**。metadata **合并**（该请求体里没有 `track_id`，覆盖会丢赛道号） |
| `GET /public/userstorage/v2/search/ghost/get_ghost`（及 `_timed` / `get_pvp_ghost`）| **真实现**。回 `{"contents":[{"contentId":N,"metadata":{…}}]}`；没有候选回 `{"contents":[]}`。`metadata` 必须是 JSON 对象 |
| `GET /public/userstorage/v2/content/ghost/<N>/payload` | **真实现**。按 id 回幽灵二进制 |
| `GET /public/resultservice/v1/replaydata/<track_id>`、`robot_replaydata`、`pvp_replaydata` | **真实现**。按 `track_id` 找幽灵，原样二进制发回 |
| `GET /public/resultservice/v1/replaydata?track_id=<ID>` | **故意回 `{"data": []}`**。它是 `submitGhost` 的上传前检查（问「服务器上有没有我的回放」），回「有」客户端就不传了 |
| `POST /public/resultservice/v1/replay_id` | **真实现**。登记「谁在哪条赛道交过幽灵」，供检索与对手挑选 |
| 其它任何请求 | 兜底 200 `{}` |

想看游戏到底在请求什么：

* 浏览器打开 `http://127.0.0.1:8000/__log` → 最近 100 条请求的完整记录。
* `http://127.0.0.1:8000/__leaderboards` → 落库的每条赛道记录 + 主界面总榜的聚合结果。
* `http://127.0.0.1:8000/__ghosts` → 幽灵索引、仓库文件、最近的 `replay_id` 登记。
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
* **联机功能部分可用**（官方早已停服，这些全是本地服务器自己造的）：
  **排行榜已通** —— 你真实跑过的赛道会落库，主界面大榜单由这些真实成绩聚合而成；
  没跑过的赛道、以及没有真实成绩的好友位都不会出现在榜单里。
  **幽灵已通** —— 跑完一场比赛客户端会把幽灵上传到服务器的 `contentId` 仓库，
  比赛时服务器再把幽灵下发给客户端（详见 8.3 / 9.3）。
  **好友列表**按后台维护的真关系下发（2026-10-07 起：`/__admin` 的「账号」页可以加/删好友、
  改昵称；游戏里没有加好友的功能，那步原本走育碧 UPlay 覆盖层）；邮件/社交仍是空数据。
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
   > 2026-10-07 起这条**不再由 `rules.json` 的桩提供**：改成动态处理器
   > `h_friends_list`，按登录者回 `server/data/friends.json` 里的真关系（见 §七 的好友列表）。
   > 形状约束不变 —— 空列表也必须回 `{"friends":[]}`。
2. 新增 `GET /v3/policies/`、`POST /v1/profiles/sessions`、`GET /v2/profiles/me`、
   `GET /v1/profiles`。
3. **把兜底 `"*"` 从 `{}` 改成 `{"data": []}`**。`{}` 是最危险的选择：所有
   「两级解引用」式解析器都会撞 NULL。改成 `{"data": []}` 后 `root->child` 非空、
   它的 child 是空数组（NULL），这类解析器会走 `cbz` 安全跳过。

实测（`adb`）：登录后 `GET /v2/profiles/me/friends` 返回 200，
**进程存活、无 SIGSEGV**，并且弹出的「好友」面板（全部好友 / 建议 / 要求三个标签）可以正常打开。

> 现在的默认是**空列表**（`{"friends": []}`，2026-10-07 起关系由后台维护），
> 空列表是绝对安全的 —— 当年固定回 `GhostRider` / `TangoPro` 两个假好友只是为了证明
> 「形状对了就不崩」。真要让某个玩家看到好友，在 `/__admin` 的「账号」页加。

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

### 8.3 幽灵（Ghost / 对手回放）——已实现

幽灵真正的协议**不在 `resultservice` 下**，而是走 `userstorage/v2` 的内容仓库
（`tr::OnlineUserStorage`）。从 `libTrialsGo.so` 里解出来的完整链路是：

```
# 上传（跑完一场比赛后客户端自动走这条链，4 步）
POST /public/userstorage/v2/content/ghost              body={"metadata":{"track_id":T,"drive_time":D,"checksum":C,"version":V}}
     ← 必须回 {"contentId": N}，客户端拿它当容器 id；回空数组就会一路用 id 0
PUT  /public/userstorage/v2/content/ghost/<N>/payload  body=幽灵二进制裸数据（首 4 字节 03 00 00 00）
PUT  /public/userstorage/v2/content/ghost/<N>          body={"metadata":{"drive_time":D,"checksum":C,"version":V}}
     # 注意：这一步没有 track_id，服务器必须做「合并」而不是覆盖，否则赛道号会丢
POST /public/resultservice/v1/replay_id                body={"profile_id":…,"track_name":"track100","drive_time":…,"faults":…,"bike":…}

# 下载（比赛时取幽灵）
GET /public/userstorage/v2/search/ghost/get_ghost?track_id=T&players=<csv>&limit=1
     ← 回 {"contents":[{"contentId":N,"metadata":{…原样回显…}}]}；没有就回 {"contents":[]}
GET /public/userstorage/v2/search/ghost/get_ghost_timed?track_id=T&players=<csv>&drive_time=D&limit=1
GET /public/userstorage/v2/search/ghost/get_pvp_ghost?track_id=T&players=<csv>&limit=1&pvpid=P
GET /public/userstorage/v2/content/ghost/<N>/payload   ← 幽灵二进制本体
GET /public/resultservice/v1/replaydata/<track_id>     ← 匿名幽灵的另一条路
```

`replaydata?track_id=<ID>`（**查询式**）**故意保持回 `{"data":[]}`**：xref 显示它被
`OnlineGhostManager::submitGhost` 内部引用，是「服务器上有没有我这条赛道的回放」的
**上传前检查**——回「有」客户端就不传了。真正下发给客户端的是**路径式**
`replaydata/<track>`（`getGhostAnonymous`）。

`metadata` 必须是 JSON **对象**：`GhostQueryObject::onQueryCompleted` 会把
`[metadata_value+0x10]` 当成员链表头继续读，传字符串会读到野指针。

幽灵文件形态：`ghost_%x_%d.bin`（`%x` = 玩家 online-id 哈希，`%d` = 赛道 id），
游戏自己用的命名。服务器的新仓库不按文件名存，改用 `contentId` 索引。

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
| `data/ghosts/<赛道id>/*.bin` | 内置幽灵文件（见 9.3，服务器启动后会自动登记进索引） |
| `data/ghosts/index.json` | 幽灵索引：`{next_id, items{<contentId>: {track_id, owner, metadata, size, frames, builtin, stored}}}` |
| `data/ghosts/store/<contentId>.bin` | 客户端上传的幽灵本体（`contentId` 由服务器分配） |
| `data/ghosts/replays.json` | `replay_id` 登记（谁在哪条赛道交过幽灵，保留最近 500 条） |
| `data/ghosts/inbox/` | 没有匹配到容器的、落单的二进制上传（运行期诊断用） |

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

服务器怎么用（两条路都通了）：

* **新路（`contentId` 仓库）**：客户端 `POST /public/userstorage/v2/content/ghost`
  建容器 → 服务器回 `{"contentId": N}` 并把 create 时的 metadata（含 `track_id`）
  和 N 绑定 → 客户端 `PUT .../ghost/N/payload` 传本体、`PUT .../ghost/N` 补 metadata
  （**合并**，不能覆盖，否则 `track_id` 丢）→
  比赛时 `GET /public/userstorage/v2/search/ghost/get_ghost?track_id=T&players=<csv>`
  由服务器回 `{"contents":[{"contentId":N,"metadata":{…}}]}`，客户端再
  `GET .../ghost/N/payload` 取本体。
* **老路（内置文件）**：`GET /public/resultservice/v1/replaydata/<赛道id>`
  （`getGhostAnonymous`）与 `robot_replaydata` 按 `track_id` 去
  `data/ghosts/<赛道id>/` 挑一个 `.bin` **原样二进制发回**（`application/octet-stream`）。
  依据：`tr::OnlineGhostManagerListener::onGhostReceived(TR_ONLINE_ERROR,int,void*,int,int)`
  和 `submitGhost(..., void*, ...)` 都是"原始字节 + 长度"。
* 目录里没有该赛道的文件 → 退回 `{"data": []}`（客户端能安全消化）。
* 索引完 `data/ghosts/index.json` 里的记录会优先于老文件；老目录改动靠
  `ghost_sync_legacy()` 在每次检索时增量登记，**不用重启**。

`players=<csv>` 过滤的注意点：单机离线环境下**永远只有自己一个玩家 id**，所以
服务器在「按 players 过滤后一个都没命中」时会回落到全部候选幽灵，否则竞速永远
没有对手。只有真的命中了某个指定玩家才会收紧。

**现在库里有什么**：`data/ghosts/1041/` 和 `data/ghosts/66633/` 各有一个
真的从原版游戏设备上抓下来的**别人的**幽灵（`ghost_6f857655_*.bin`），
服务器启动后第一次检索时会把它们登记进索引（`builtin: true`）。
想加更多：把 `.bin` 丢进 `data/ghosts/<赛道id>/` 就行，不用重启。

排障：`curl http://127.0.0.1:8000/__ghosts` 能看到索引、仓库文件和最近的
`replay_id` 登记。

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
| 幽灵文件格式 / 回放数据下发 | ✅ 完成（上传/检索/下发全链路）|
| 幽灵 `userstorage/v2/*` 协议 | ✅ 完成（`contentId` 契约 + `contents` 数组）|
| 排行榜 / 好友成绩页 | ✅ 完成（真实成绩落库 + 主榜实时聚合）|
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
`TrialsFrontier-offline.apk` 含上述两条补丁，并已随第十一章的闪退修复与第十二章的账号/VIP 更新
一起升到 **m16**（SHA-256 `EA77B0B420BF790BB626189F74A3BC64BB384607C2A273F36ADBF558FD8EAB53`，
26 906 224 字节）。历史备份：`tmp\build\tf-m15-release-backup.apk`（只有 VIP 空指针守卫、
没有骑士俱乐部购买入口的那版）、`tmp\build\tf-m14-release-backup.apk`（会员守卫的旧版）、
`tmp\build\tf-m13-release-backup.apk`（仅有 IAP 修复）、
`tmp\build\tf-m8-release-backup.apk`（只修了「下载暂停」的老基线）。
`tools/patch_native.py` 的 `PATCHES` 已同步到 **17 条**，`--dry-run` 自检全 `[OK]`；
用它从原版 `libTrialsGo.so` 重新生成的产物与 `tmp\m16\libTrialsGo.so`
**逐字节一致**（除了另行施加的服务器地址/URL 重写那几段）。

---

## 十一、联网闪退（ROADMAP 第 1 条）—— 已修复并实机验证

### 11.1 症状与用户观察
> 经过测试，如果联网就会闪退，关闭 wlan 等启动就能进入，再开启网络即可。
> 可能是连接谷歌服务，我们要劫持这一部分网络，让它来到我们服务器。

### 11.2 根因（tombstone 实证，跟谷歌服务无关）
闪退是 `tr::VIPManager::getPlayerMembership()` 里的**空指针解引用**：

```
#00 tr::VIPManager::getPlayerMembership()+120   ← 读 0x0，崩溃点
#01 tr::UserTracker::getMembershipDate()+88
#02 tr::UserTracker::updateCommonAttributes()+44
#03 mz::DNAManager::sendDnaEvent(...)+168
#04 tr::UserTracker::sessionStart()+1492
#05 tr::UserTracker::init()+320
#06 tr::GlobalData::init(mz::InputPointerState*)+1236
#07 tr::MainApp::init()+112
#08 resize+420
#09 art_jni_trampoline+112
#11 com.ubisoft.redlynx.trialsgo.GL2View$Renderer.onSurfaceChanged+10
#13 android.opengl.GLSurfaceView$GLThread.guardedRun+994
```

`getPlayerMembership()` @`0x0062e5c4` 的关键片段：

```
0x62e5f0  bl NetworkChecker::getNetworkType ; cbz w0     -> 空返回   ← 断网就跳过，故只有联网才崩
0x62e60c  bl AntiCheating::isValid          ; tbz w0,#0   -> 空返回
0x62e630  bl PlayerItems::getItemCount      ; tbz w0,#0   -> 空返回   ← 存档里有会员道具才继续
0x62e638  ldr x0, [x21]        ; x0 = this->[0]  ← slot0 会员计时器
0x62e63c  ldr w8, [x0]         ; ★ 崩在这（x0 == NULL）
0x62e6b4  ldr x0, [x21, #8]    ; slot1 同一模式
0x62e6b8  ldr w8, [x0]         ; ★ 同样会崩
```

会员计时器由 `VIPManager::activateMembership()` 创建，**正常由服务器下发触发**；
离线私服从不激活会员，但存档里存在会员道具（item 0x80），于是 `[this]` / `[this+8]`
两个计时器指针恒为 NULL，联网时一读即 SIGSEGV。

### 11.3 修复（5 × 4 字节，m15 起）

早期 m14 用的是「把结果涂成常量空列表」的粗暴办法（`ldr w8,[x0]` → `mov w8,#0`，2 × 4 字节）。
它能止崩，但副作用是**会员状态永远读不出来**，VIP 下发就无从谈起。m15 换成等价语义的空指针守卫：

| 补丁 id | 文件偏移 | 原始 → 补丁 | 含义 |
| --- | --- | --- | --- |
| `vip-membership-null-guard-slot0-a` | `0x0062e63c` | `08 00 40 b9` → `a0 01 00 b4` | `ldr w8,[x0]` → `cbz x0, #0x62e670` |
| `vip-membership-null-guard-slot0-b` | `0x0062e640` | `88 01 00 34` → `08 00 40 b9` | `cbz w8,#0x62e670` → `ldr w8,[x0]` |
| `vip-membership-null-guard-slot0-c` | `0x0062e644` | `f4 03 1f aa` → `68 01 00 34` | 冗余的 `mov x20,xzr` → `cbz w8, #0x62e670` |
| `vip-membership-null-guard-slot1-a` | `0x0062e6b8` | `08 00 40 b9` → `40 05 00 b4` | `ldr w8,[x0]` → `cbz x0, #0x62e760` |
| `vip-membership-null-guard-slot1-b` | `0x0062e6bc` | `28 05 00 34` → `08 00 40 b9` | `cbz w8,#0x62e760` → `ldr w8,[x0]` |

改完 slot0 的指令序列是
`ldr x0,[x21]` → `cbz x0,空返回` → `ldr w8,[x0]` → `cbz w8,空返回` → `bl getRemainingTime` → `cbz w0,空返回`，
与原始逻辑完全一致，只是不再解引用 NULL。slot1 没有空指令槽可借，`cbz w8` 被丢掉，
但未启动的 `TimedAction` 前 16 字节全 0，`getRemainingTime()` 必返回 0，紧随的 `cbz w0` 已能兜住。

**效果**：`VIPManager::init()` 跑过之后（它给 4 个计时器指针赋值），
`getPlayerMembership()` 会**如实返回真实会员状态** —— 这正是 VIP 下发能生效的前提。

### 11.4 实机验证（联网状态，`192.168.1.100:8000`）
- 进程存活 135 秒以上，`am_crash` / `am_proc_died` **零条**。
- 服务器收到完整启动序列：`GET /` → `/dlcontent_frontier_android/794/info.json`
  → `/v1/applications/<appid>/configuration` → `POST /v3/profiles/sessions`
  → `/frontieronlinecontent/loc.json` → News。**以前到 `GET /` 就崩。**
- 游戏正常进村庄，截图 `tmp\m14a.png`。

### 11.5 走过的弯路（别再重复）
- **不是** `tf_server.txt` 地址串太长溢出（`patch_dynaddr.py` 的例程有 63 字节读上限与容量检查）。
- **不是**局域网路由/防火墙问题（设备 `curl http://192.168.1.100:8000/__ping` → `pong`）。
- **不是**内购补丁引起（装不含 IAP 补丁的 `tf-m8-release-backup.apk` 照样崩）。
- **不是** Google / 阿里 DoT 流量引起（`iptables` 把 wlan0 出网全封只放行本机服务器，**仍然崩**）。
- ⇒ 真正起作用的只是「Android 是否报告有可用网络」这一个事实 —— 因为
  `NetworkChecker::getNetworkType()` 是那道最外层的闸。

### 11.6 取证技巧（可复用）
`debuggerd` 一开始不为游戏落 tombstone（只能看到无关的指纹 HAL SIGABRT）。先执行
```
adb shell "cmd package compile -m speed -f com.ubisoft.redlynx.trialsfrontier.ggp"
```
强制 AOT 重编译，之后 `adb logcat -d` 里的 `F DEBUG` 行就是游戏的完整 native 栈。

---

## 十二、账号系统重构 + VIP 下发（ROADMAP 第 2 条）

### 12.1 注册与登录彻底分开

以前「登录一个没见过的用户名」= 直接给你建号，于是永远打错密码也不会被拒。
现在（`server/tflocal_accounts.py`）：

| 函数 | 语义 |
| --- | --- |
| `register_account(user, pw, name?)` | 只注册。用户名或口令为空 → `bad-request`；已存在 → `exists` |
| `login_account(user, pw)` | **只查库，绝不建号**。查不到 → `not-found`；口令不符 → `invalid-credentials` |
| `set_password(user, pw)` | 换新 salt 重算哈希 |
| `delete_account(user)` | 删账号，**不动它的存档目录** |
| `list_accounts_public()` | 去掉 `pw`/`salt`，附 `created_iso`/`last_login_iso` |

`POST /v3/profiles/sessions` 带 `Authorization: Basic <b64(user:pw)>` 时走 `login_account`，
失败一律 **401** 并给出可读原因：

```json
{"error":"not-found","errorCode":"NOT_REGISTERED",
 "message":"此账号尚未在本地服务器注册，请先打开 http://<服务器IP>:8000/__register 注册"}
```

### 12.2 VIP 下发：链路本来就在，缺的是「能买到」+「能读到」

- 买下商店里的骑士俱乐部档位 → `StoreManager::onPurchaseComplete`
  → `StoreManager::pushItemPurchasedPopup` → **`VIPManager::activateMembership(type)`**
  （`activateMembership` 全库只有这两个调用点，都在 `pushItemPurchasedPopup` 里封着）。
- `activateMembership` 会 `PlayerItems::setItemCount(0x80, 0, ... | (1<<type))` 并
  `timers[type]->start(now, dur, 0, 0)` —— **道具 id 0x80（=128）就是会员位掩码**，
  bit0 / bit1 分别对应「未来的会员」/「道路队长」；时长取自
  `GlobalSettings::getSetting(<hash>, 0x278d00)`（=2592000 秒 = 30 天）。
- `getPlayerMembership()` 只认这个位掩码 + 计时器剩余时间。
  所以 §11.3 把「涂成常量」换成**空指针守卫**之后，会员状态才第一次可能被如实读出来。
- 但只修 `getPlayerMembership` 还不够：离线商店里「骑士俱乐部」两档显示
  **「剩余时间：未知（离线）」**、**没有购买按钮**。根因在
  `VIPManager::isVIPStoreOfferAvailable()` @`0x0062edd4`，它返回
  `(StoreItem != NULL) && (IAPItemInfo != NULL)`：
  - `StoreItem` 来自本地数据包（`/conf/store_offers.txt` 那一套），离线是有的；
  - `IAPItemInfo` 来自 `OfferManager::findVIPOffers` @`0x00601920` 里的
    `mz::IAPManager::getProductInfoEnabled(item+4)`；
  - 离线没有 Google Play，`mz::IAPManagerAndroid::LoadStore` 一个产品都没往
    `mt::Array<IAPItemInfo>`（`this+0x10` count / `this+0x18` data，stride `0x88`）
    里插过，于是它永远走 `0x0088a22c  mov x19,xzr` 返回 **NULL**。
    （顺带查清：`addProduct` 置的是 flag 的 **bit1**，而 `getProductInfoEnabled`
    查的是 **bit0**，所以「先 addProduct 再查表」这条路根本走不通。）
- **m16 的修法**：只把 `findVIPOffers` 里那一条 `bl getProductInfoEnabled`
  （`0x006019e0`）改跳进代码洞 `0x0096d85c`，洞里 3 条指令
  `adrp x0,#0x96d000 ; add x0,x0,#0x86c ; ret` 直接返回 `0x0096d86c` 处一个
  伪造的 `IAPItemInfo`（`+0x00` 内联 id、`+0x40` int −1、`+0x84` **bit0 = 1**）。
  其它任何 IAP 调用点都不受影响（尤其 `0x0088a3e4` 那处购买校验仍走原生逻辑）。
- **实机结果（2026-10-04 11:32，小米 8 / LineageOS 22.2）**：
  - 骑士俱乐部两档都从「未知（离线）」变成 **「剩余时间：29天」**；
  - 进村庄弹出 **「每日登录奖励」65💎 + 65000🪙，剩余时间 29 天**；
  - 服务器日志在同一秒收到客户端主动发出的
    `POST /public/targeting/v1/vip_registration`、
    `POST /private/targeting/v1/direct_vip_registration`、
    `GET /public/targeting/v1/vip_validation`、
    `GET|POST /public/targeting/v1/vip_badge_option` ——
    而 `registerMembership()` 在整库中**只有 `VIPManager::activateMembership` 一个调用者**，
    这就证明**两档会员都被真正激活了**（`activateMembership(0)` 与 `(1)` 各一次；
    两次走了不同端点，是因为第一次调用时配置还没加载完，`Anticheating_Enabled` 仍是默认值 1）。
- 服务器侧对应实现（`server/tf_server.py`）：`h_vip_registration`、`h_vip_validation`、
  `h_vip_badge_option` 三个动态处理器，注册在 `DYNAMIC_EXACT` 里共 5 条
  （两个 registration 的 POST、validation 的 GET、badge_option 的 GET + POST）。
  唯一会被客户端解析的是 `vip_validation`（`onNetworkDataReceived` @`0x0051b0ac`
  里只有 `cmp w3,#0x73` 一个分支），响应必须含顶层键 `player` 与 `badge_display`，
  否则 `parseJsonData` 静默 return、不回调 listener。

### 12.3 内置 WebUI（ROADMAP 第 4 条起了个头）

浏览器打开 `http://<服务器IP>:8000/__ui`（或 `/__register`）即可注册账号、查看已注册账号。

> 注意：`GET /` 被游戏自己的 gamecfg 端点占用（`/?product=101&portal=Google&version=7.9.4`），
> 所以网页只能挂在 `/__ui`、`/__register` 这类路径上。

API：`POST /__api/register`、`POST /__api/login`、`POST /__api/password`、`POST /__api/delete`。
账号/存档/幽灵的管理端点：`/__accounts`、`/__devices`、`/__sessions`、`/__saves`、
`/__save?profile=`、`/__history?profile=`、`/__restore?profile=&ts=`、`/__ghosts`、`/__help`。

### 12.4 还没做完

- VIP **激活后本地存档的上传**：`activateMembership` 是本地生效的，
  服务端存档里目前还看不到 item 128（等客户端下一次上报会把会员位与计时器带上来）。
- 服务端主动**免费发放会员**的管理接口（`/__api/grant` 之类）尚未做 ——
  目前 `activateMembership` 只能由客户端自己的购买/恢复流程触发。
- ROADMAP 第 3 条在线功能（幽灵 `userstorage/v2/*` 链、排行榜、限时活动、碉堡/午夜杯）。
- ROADMAP 第 5 条：一键开服打包成 exe。

