# CONTEXT — 术语表

> 本项目**只在这里**定义术语。实现细节不进本文件。
> 术语一旦确定立即写入；有歧义先讨论再写入。

## 对象

- **原版（干净原版 / clean original）**
  `com.ubisoft.redlynx.trialsfrontier.ggp` v7.9.4（versionCode 561）由 Ubisoft 官方签名的完整 APK。
  自包含：含 `classes.dex`/`classes2.dex`/`classes3.dex`、`resources.arsc`、完整 `res/`、`assets/`、
  以及 `lib/arm64-v8a` 与 `lib/armeabi-v7a` 两套原生库。
  **不含** `libSecShell.so` / `libsupi.so` / `libSignatureKiller.so`。
  两份等价来源（2026-10-07 逐条目比对：**1234 个条目的 CRC32 与长度全部相同**，
  只有 zip 容器压缩方式差 4 KB，`libTrialsGo.so` 均为 `743f945cd7e3378d…`）：
  ① 用户从 apkmirror 下的
  `dist\原版APK\com.ubisoft.redlynx.trialsfrontier.ggp_7.9.4-561_minAPI16(arm64-v8a,armeabi-v7a)(nodpi)_apkmirror.com.apk`
  （34 312 425 字节，sha256 `EDDD7DF0C482279B523255498DB448F5CE27609D8BCB1E0B94C45D5948225580`，
  minSdk 16 / targetSdk 30，原签名 `CN=Ubisoft`，v1+v2+v3）；
  ② 本仓库离线载荷里的 `tmp\pack\TrialsFrontier-clean-pack\appdata\aUiMEPVatQ.apk`
  （34 316 521 字节，sha256 `3E62EF058C90CD03B896B84E0E9699576ACB970AB648275097ED6018FDF9F812`，
  即 mod 包内嵌的那份被壳解密出来的原版）。

- **打补丁的 base 认谁**
  只认上面①/②两份**未改动**的原版（`libTrialsGo.so` = `743f945cd7e3378d…`，= `tools/tfpatcher.py:69`
  写死的期望指纹）。**`dist/TrialsFrontier-offline.apk` / `-full.apk` / `tmp/build/tf-m16.apk` 不是干净 base**：
  它们是已打补丁的产物（`libTrialsGo.so` = `e9f2fa1a4e90ac07…`、targetSdk 已改成 27、v7a 已删），
  `tfpatcher.py` 的 SHA256 校验会直接拒绝。
  ★ **AIO 把它变成了硬拦截**（`tools/tfpatch_aio/pipeline.py` 的 [2/8]）：指纹对不上基准时先跑一遍全表
  dry-run，把 base 里「已经是改好状态」的补丁列出来，没勾「忽略原版校验」就 `raise ToolError`。
  理由是**补丁器只加不减** —— base 里已经有的 `spend-adds-instead-of-subtracts`（货币不减反增）
  改不回来，于是「没勾却还是有」。勾了 `--force` 才放行，并换成 `[WARN]` + 列出已带的补丁。

- **mod 包（外壳包 / shell build）**
  `APKS\特技摩托前线\7.9.4 带剧情不减反增车不全.apk`。
  第三方重打包产物：外层是网易易盾 SecShell 加固壳 + 内嵌原版 + `libSignatureKiller.so`，
  签名是自签 `C=CN`。特征是"货币不减反增、车辆不全、带剧情"。

- **基线（baseline）**
  本项目选定的改造底座 = **原版**。已决定不再在 mod 包上打补丁。

- **补丁包（patch build）**
  本项目最终产出的 APK，由基线重建而来：剥离广告与遥测、关闭反作弊、开放内容、接入本地服务器地址。

- **两形态（两种交付形态）**
  同一套改造成果的两种交付方式：①**完整 APK**（`dist/TrialsFrontier-offline-full.apk` 全自包含 / 
  `dist/TrialsFrontier-offline.apk` 瘦包，开箱即用）；
  ②**patcher**（`dist/patcher/` 或带界面的 `dist/TrialsFrontierPatcher.exe`，用户拿自己的原版 APK 在本地重新生成）。
  两种形态必须能产出**逐字节相同**的原生库 —— 这是工具链正确性的验收标准。
  （2026-10-07 已用真原版实测两条路并对上结构，见 `tools/README.md` §9.6。）

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

## 在线模式

- **碉堡（The Bunker）**
  异步 1v1 段位赛模式（客户端 `tr::PVPManager`，服务端 `/pvp/*`）。有**赛季**、段位（Rank 25 → Rank 1，再上为 Legend）、
  星章、连胜、筹码与金票；奖励分两层：**赛季奖励表**（按名次）与**每局奖励**（客户端本地发）。

- **午夜杯（Midnight Circuit）**
  客户端里的**周赛**（`weekly_track_system`）。**没有赛季、没有 leg、没有门票、没有积分**：
  一周一届，一条本周赛道，成绩上榜取名次百分位 → 五档奖杯 → 奖励池。
  ⚠ `pvp_docs/午夜杯.md` 把它写成有赛季 / 3~4 Legs / 午夜杯门票 / 积分的锦标赛，**与实测不符、未证实**，不作为术语依据。

- **一届（午夜杯的一届）** 与 **赛季（碉堡的赛季）**
  两个**不可混用**的时间概念：午夜杯只有「届」（默认 7 天，窗口按 epoch 周对齐）；
  碉堡才有「赛季」（默认 30 天）。说「赛季」时永远指碉堡。

- **赛季编号（season number）与显示编号（display number）**
  赛季编号是**纯 epoch 除法**算出来的内部计数（无起始日锚点）；**显示编号**是发给客户端、玩家在界面看到的那个号。
  运营页要能「把当前这一刻标成第 N 赛季」——即在**下发边界**套偏移，内部编号与赛季边界都不动。

- **推进计数（`season.advance`）**
  让**当前这一届的窗口整体往前挪一轮**的计数器（不是赛季历史、不是多届并存）。
  玩家下次进游戏时按新窗口结算并复位段位。

- **挑战规则（午夜杯）**
  午夜杯这一格里唯一服务端管得住的「时长类」东西：**每周次数** + **冷却时长**。
  单条赛道的计时在客户端**原表**里，服务端改不了，界面只作只读说明。

- **奖励池（reward pool）与奖励物品（reward item）**
  午夜杯服务端只下发**池子编号 1..15**；池子里的**物品本体**是客户端**原表**（`/conf/wts_rewards.txt`），服务端改不了。
  所以「奖励物品」这一格能控的是**用哪个池子**，不是物品本身。

- **赛季奖励表（`season.rewards`）**
  碉堡按名次发的奖励：扁平 `{rank, item_id, amount}`（rank 0..25，同 rank 可多对）。
  ⚠ `item_id 145` 的 `amount` 是 `RewardID`（不是库存物品 id、不是数量）；金币/钻石才是真 `item_id`。
  **每局**的金币/钻石/特殊奖励不在服务端，由客户端本地发放。

- **特殊奖励编号（`item_id 145` 的 `amount`）与官方 43 个**
  赛季奖励里 `item_id 145` 的 `amount` 是客户端原表 `/conf/pvp_match_rewards.txt` 的 `RewardID`。
  原表 `PVPMatchSpecialRewards` 固定 7 组共 **43 个**编号（零件 4 档 + `202` Soylent 涂装 +
  `203` Luchador 涂装 + `220` 毛驴图纸），运营页给它们标 ★。
  这只是「官方赛季会发哪些」，**不是**可填范围的限制：物品表里存在的编号现在都能填
  （服务端只拒物品表里查不到的编号）。

- **兜底奖励（`Fallback`）与显示规则**
  原表每条奖励可以声明一个 `Fallback`。客户端画赛季奖励时先看玩家**有没有**这件物品：
  没有就画真实图标，**已经有了**就画该编号自己的兜底奖励 ——
  原表 309 行里 237 行带 `Fallback`，其中 215 行是 `221`（Doughnut = 「毛驴轮胎」）、22 行是 `-2`。
  ⇒ 同一个编号在不同账号上长得不一样，**这不是配置坏了**。
  （2026-10-06 用覆盖包 `TrialsContentExtraDL_0probe.dat` 真机验证：把 `220` 改指向 Stallion 图纸
  并删掉它的 `Fallback` 后，游戏里那一档就画出了 Stallion 图纸。）
  ★ 想稳定发喷漆 / 衣服 / 整车，仍然走「下发物品」页。

- **幽灵与榜行预检（`ghosts` / `board_rows`）**
  午夜杯现状卡上的两个只读计数 + 警告。赛道上一个幽灵都没有时服务端只能回 `replay_id=0`，
  客户端会反复去要一个不存在的幽灵（表现：卡在「加入午夜杯」）——
  所以换赛道前先看这两个数，或者先让玩家在这条赛道上跑一圈。

- **对局时长（match duration）**
  碉堡的一局长度（`matchmaking.match_duration_seconds`，同时当 `total_time` 与 `ranked_match_duration` 用；
  好友局另有 `matchmaking.friendly_match_duration`）。只影响**新开的局**；与「单条赛道时限」不是一回事
  （后者在客户端原表）。到点后客户端的下一次 `/start_race` 会吃 409 `match-ended`，它据此收局 ——
  ★ 所以**时长就是「突然结束」的第一嫌疑**：碉堡屏给这个字段配了四个预设（5 分钟 / 30 分钟 / 1 小时 /
  还原 6 小时）+ 数字框随便填，现状卡还有一条「300 秒 = 测试值」的红字警告。

- **对局胜负（占得多就赢）**
  `_pvp_match_won`：**占住的赛道比对手多**就算赢，`1:0` 与 `2:1` 都算，`0:0`（谁都没跑出成绩）是平局
  ⇒ 不写 `last_match_winner`、段位与连胜不动。判定口径与客户端屏幕完全同一套：逐赛道比 score
  （`_pvp_owner_of` ↔ `parseMatch` 0x4fe0dc）。2026-10-06 之前是「3 条里占住 ≥2 条」，在「到点被
  截断、只跑完 1 条」的真机局里会算出平局而与屏幕（判胜利）打架 —— 见 `[pvp] close …` 那行日志。

- **昵称（`nameOnPlatform`）与好友关系**
  昵称 = 别的玩家在排行榜 / 好友列表里看到的名字，存在 `accounts.json` / `devices.json`
  （没注册账号的静默设备也有，默认 `Player-XXXXXX`）；**3–24 字符、大小写不敏感去重**。
  好友关系存在 `server/data/friends.json`，**双向**（A 加 B ⇒ B 的列表里也有 A），
  由 `/__admin` 的「账号」页（`GET|POST /__api/admin/social`）维护 ——
  ★ 游戏里**没有**「加好友」这个动作：唯一接口 `tr::OnlineFriends::addFriend @0x51bed4`
  的调用者只有育碧 UPlay 覆盖层那条线（原版就是把好友请求交给 UPlay），私服接不到。
  客户端只负责**显示** `GET /v2/profiles/me/friends` 给的那份列表，服务器没给的条目会被它删掉。
  空列表必须回 `{"friends":[]}`（回 `{}` 会让解析器读 NULL+0x10 直接 SIGSEGV）。

- **车辆级别（tier）与图的车辆级别（`B`）**
  每辆车在原表 `/conf/bikes.txt` 里有 `Tier`（0 / 1 / 2，**255 = 不限**）；每张图在
  `/conf/levels.txt` 里有 `B` = 这张图要求的车辆级别（**255 = 不限**）。
  客户端 `LevelManager::isCorrectBikeTier @0x47c170` 要求两者**相等**（图为 255 或车为 255 时放行）——
  所以「1 级车跑一级图」。车的级别是**原表**，服务端只能读、不能改。

- **剧情车（story bike）**
  车号 1..9 那批（`Armadillo`…`Phantom`），也就是玩家沿剧情解锁的三档各三辆。
  10/11/12/19（`Stallion`/`BMW`/`Moonrover`/`Donkey`）是 `Tier = 255` 的特殊车：
  它们能跑任何图，但**随机发车时默认不出场**。

- **发车方式（bike assignment）**
  服务端决定一局里每条赛道发哪辆车，三档开关：
  **按赛道级别随机**（`matchmaking.bike_random`，默认开，池子 = 玩家**已拥有**且级别匹配的车）、
  **只放剧情车**（`matchmaking.bike_story_only`，默认开）、
  **全场固定一辆**（关掉随机后所有赛道都发 `matchmaking.bike_id` —— ★ 这台车必须能跑每张候选图）。
  「已拥有」来自客户端上报的车库位图（bit i = 车号 i+1），不是服务端猜的。
  抽签结果在对局记录里固化（换局才重抽），所以同一局不会换车。

- **租借升级（loan upgrade）与保底车**
  午夜杯只有**一辆**本周车：玩家没有这辆车、或者自己的升级**不如**本周的车，就开那辆带固定升级的
  **租借车**（不进玩家真实车库）；自己车更强的玩家照常用自己的升级。
  客户端 `WeeklyChallengeManager::setBikeUpgradeLevel @0x636710` 在 `force_upgrade == 0` 时
  对四个部件取 `max(玩家自己的升级, 配置值)` —— 服务端发 5/5/5/5 + `force_upgrade = 0` 即为此语义，
  **不需要**单独的「租赁」标志位。`weekly.bike_id = 0` = 按本周赛道级别自动随机（整周同一辆）。

- **礼包 / 商城商品（`season.product_list`）**
  赛季相关的一次性商品（`{product_id, amount}`）。`product_id` 是**商城商品 id**（如
  `chip_shop.goldentickets` = 金票），不是物品 id；原表里没有的 id 客户端**静默忽略**。

- **模板（template）**
  一页运营参数的**快照**，存服务端，可命名、套用（整页或只套奖励方案）、复用。
  内置模板只读（至少含一份「当前生效值」快照）作为后悔药。

- **现状卡（status card）**
  运营页顶部的**只读**实况卡：当前生效值 + 真人/合成分离的计数 + 进程内状态提醒。
  它必须如实标出「当前值是测试档 / 已被关闭」这类事实（例如碉堡的 3 分钟对局时长、午夜杯的挂机产币已关）。

- **GUI 优先（no-JSON editing）**
  运营参数一律用图形控件编辑（数字框、分段控件、下拉、可增删的表格行），**不提供 JSON 文本框**。
  目标用户是不懂 JSON 的人；JSON 只作为内部存储与导出格式存在。

- **冻结（frozen）与两类目录：只读资源 / 运行期数据**
  「冻结」= 代码被打成 exe 跑（PyInstaller 看 `sys.frozen`，Nuitka 看 `__compiled__`）。冻结后路径分两类：
  **只读资源**（`admin/` 前端、`rules.json`、`items.json`、已入库的静态幽灵）从包内 `HERE` 读；
  **运行期数据**（存档、`tf_config.json`、对局状态、`logs/`）写到 `<exe 目录>/data`。
  源码运行时两者都在 `server/` 下、布局与打包前一致。

- **播种（seed）与打包白名单**
  首次运行把缺的文件补上（`tf_config.json` 用**内置默认值**、拷 `wts_rewards.json` 与 46 个已入库幽灵），
  **只补缺、从不覆盖** ⇒ 换新版 exe 直接替换文件。打包白名单（`tools/build_exe.ps1`）是安全边界：
  真机存档、`admin.json`、`accounts.json`、`pvp_state.json`、审计与日志一律不进包，脚本带硬性检查。

- **AIO 补丁器（`tfpatch_aio`）与两条打补丁路线**
  给玩家用的那个带 GUI 的 exe（`dist/TrialsFrontierPatcher.exe`）：勾功能 → 出包。两条路线的 base 要求**不同**：
  **补丁版**只改 `.so` 与清单，任何原版/整合版都能当 base；
  **自包含版**（`bundle`）还要把启动类换成 `OfflinePayloadSetup`，而 AXML 改字符串是**等长原地改**
  ⇒ base 的 `<application android:name>` 必须正好是 48 字符的 `DexApplicationClass`。
  **加固包**（启动类在壳里，如 `com.SecShell.SecShell.AW`）因此做不了自包含 —— 流水线会提前报错让人换 base，
  这不是待修的 bug。老脚本（`tools/*.py`）保持原样，AIO 用的只是它们的副本（`tfpatch_aio/vendored/`）。

- **离线载荷（payload）**
  自包含 APK 要的那 300 MB 数据（`appdata/` + `obb/`）。**不内嵌进 exe**，放 exe 同目录的
  `payload\` 或 `payload.zip` 由 GUI 自动识别；打进去后由首启的 `OfflinePayloadSetup` 搬到应用私有目录。

## 已废弃的提法

- **劫持层（VPN/DNS 重定向叠加层）**：曾被设想为独立 App，供无 root 用户填入 IP/端口/域名。
  因服务器地址本就可注入而**降级为备选**，不再是主交付物。
