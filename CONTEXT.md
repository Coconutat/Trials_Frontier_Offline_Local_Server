# CONTEXT — 术语表

> 本项目**只在这里**定义术语。实现细节不进本文件。
> 术语一旦确定立即写入；有歧义先讨论再写入。

## 对象

- **原版（干净原版 / clean original）**
  `com.ubisoft.redlynx.trialsfrontier.ggp` v7.9.4（versionCode 561）由 Ubisoft 官方签名的完整 APK，
  当前以 `assets/ERRKGc5F/aUiMEPVatQ.apk` 形式内嵌在 mod 包中。
  自包含：含 `classes.dex`/`classes2.dex`/`classes3.dex`、`resources.arsc`、完整 `res/`、`assets/`、
  以及 `lib/arm64-v8a` 与 `lib/armeabi-v7a` 两套原生库。
  **不含** `libSecShell.so` / `libsupi.so` / `libSignatureKiller.so`。

- **mod 包（外壳包 / shell build）**
  `APKS\特技摩托前线\7.9.4 带剧情不减反增车不全.apk`。
  第三方重打包产物：外层是网易易盾 SecShell 加固壳 + 内嵌原版 + `libSignatureKiller.so`，
  签名是自签 `C=CN`。特征是"货币不减反增、车辆不全、带剧情"。

- **基线（baseline）**
  本项目选定的改造底座 = **原版**。已决定不再在 mod 包上打补丁。

- **补丁包（patch build）**
  本项目最终产出的 APK，由基线重建而来：剥离广告与遥测、关闭反作弊、开放内容、接入本地服务器地址。

- **两形态（两种交付形态）**
  同一套改造成果的两种交付方式：①**完整 APK**（`dist/TrialsFrontier-offline.apk`，开箱即用）；
  ②**patcher**（`dist/patcher/`，用户拿自己的原版 APK 在本地重新生成）。
  两种形态必须能产出**逐字节相同**的原生库 —— 这是工具链正确性的验收标准。

## 结构

- **壳（shell / 加固）**
  指 SecShell 那一层：内存中加载匿名 dex（`Anonymous-DexFile@*.jar`）、逐级 `System.loadLibrary`、
  解密并释放真正的 `libTrialsGo.so`。删掉壳 = 让原版替我们做它本来就在做的事。

- **签名杀手（signature killer）**
  `libSignatureKiller.so`。读 `/proc/self/maps` 定位已加载的 `.so` 并改写其内存/节表，
  用于让客户端的签名校验失效。是 mod 包自带的可疑组件，**不属于基线**。

- **代码洞（code cave）**
  原生库里既没有被引用、也不会被执行到的连续空白字节区。用于就地追加指令或伪造结构体，
  代价远小于新增节或改段表（那会破坏加载布局）。

- **反作弊（AntiCheating）**
  原生 `tr::AntiCheating`，会做 NTP 对时并校验系统时间偏移。
  已决定（Q9=b）：**打补丁关掉**。

- **离线模式（offline mode）**
  游戏内建的、无需登录即可游玩的一整套逻辑（`tr::RobotmanManager::goOffline`、
  `enableOfflineOpponent`、`generateOfflineMission` 等），离线对手由本机生成。
  已确认"不登录也能玩"是设计内功能，不是残缺状态。

- **育碧身份服务（Ubisoft Identity）**
  登录关卡。实测对老客户端返回 `Forbidden`（Ubisoft 错误码 263），
  即后端存活但拒绝该客户端。是"复刻在线体验"这条路上真正的第一道墙。

## 机制

- **服务器地址注入（server-address injection）**
  取代原设想中"VPN/劫持层"的做法：游戏侧 `OnlineCore::setserverAddress` 的地址本来就是空的
  （表现为 `/public/receiptvalidation/v1/product/configuration` 报 `no protocol`），
  因此由**补丁包自身**从一个用户可编辑的本地来源读取服务器地址。
  已决定（Q2=d）：不做 VPN，不给用户增加代理配置负担。

- **本地服务器（local server）**
  本项目自建的、替代已停服后端的服务端。定位：**每个端点都既能"打桩"也能"真实现"**，
  永远不强制依赖云端。

- **内购（IAP）**
  本项目语境下指 **解锁内容**（让原本付费的内容归用户所有），而非伪造支付回调。
  已知用户希望保留"点一下购买"的手感，因此允许做一个纯本地的"购买 → 立即成功"演出。

- **会员（VIP membership）**
  两档付费会员：「未来的会员」与「道路队长」。在游戏里表现为一个道具位掩码 + 一个 30 天计时器。
  **下发（grant）**指让这份状态在客户端真正生效；本项目的要求是「用户买了 VIP 就激活 VIP 事件」。

- **进度（progress）与进度同步（progress sync）**
  玩家存档在服务器侧的副本，以及它在客户端与服务器之间往返的整套协议。
  客户端有一套「本地版本 / 服务器版本」比对，比对结果决定它**把本地推上去**还是**把云端拉下来**；
  判错方向就会覆盖掉玩家真实存档。

- **幽灵（ghost）**
  排行榜与对局里「别的玩家的跑法」回放数据。服务端既可以原样回存真实数据，
  也可以自行生成（本项目已选：优先原样回存）。

- **广告结局**
  广告 SDK 不再加载，**且广告原本提供的奖励照常发放**（Q4=b），
  以免"看广告换金币/续关/双倍"这类入口静默消失。

## 已废弃的提法

- **劫持层（VPN/DNS 重定向叠加层）**：曾被设想为独立 App，供无 root 用户填入 IP/端口/域名。
  因服务器地址本就可注入而**降级为备选**，不再是主交付物。
