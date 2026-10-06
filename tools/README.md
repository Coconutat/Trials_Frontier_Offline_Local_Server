# tools/ — 补丁工具与逆向工具

两条独立的流水线，放在同一个目录里：

* **`tools/*.py`（顶层）** —— 打 APK。把用户自备的原版 Trials Frontier 变成可离线游玩的包。
* **`tools/re/*.py`** —— 逆 `libTrialsGo.so`。定位/反汇编/解析 vtable，用来搞清楚游戏要什么。

两者的输出都是可复现的：顶层工具每处修改都会先校验原始字节，对不上就退出；`tools/re/`
的工具是只读的。

---

## 1. 快速开始

```bash
pip install pyelftools          # patch_urls.py 解析 ELF 节表用

python tools/tfpatcher.py --apk 原版.apk --out TrialsFrontier-offline.apk
```

一条命令跑完全部 7 个步骤。常用参数：

| 参数 | 作用 |
|---|---|
| `--host 192.168.1.100:8000` | 写进 .so 的**编译期默认**服务器地址 |
| `--no-sign` | 只出未签名 APK（没有 Android SDK 时） |
| `--build-tools <dir>` | 指定 Android build-tools 目录 |
| `--keystore/--alias/--store-pass` | 指定签名密钥（默认自动生成自用密钥） |
| `--keep-v7a` | 保留 `armeabi-v7a` 的库（**不推荐**） |
| `--force` | 跳过原版 .so 的 SHA256 校验 |

装到手机后，**服务器地址以运行期文本文件为准**（见 §3.4），改文件即生效，不用重装：

```
/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/tf_server.txt
第一行 = <PC 的 IP>:8000
```

原版 APK 原本以 `APKS/特技摩托前线/Main_APK_Backup.7z.001…011`（11 卷、318 MB）入库，
现已从版本控制移出（体积 + 截图属个人信息，见 `.gitignore` 的 `APKS/` 规则），
但**磁盘上仍在**，解出来的内嵌 APK 依旧被流水线当作 base。

---

## 2. 打 APK 流水线（`tfpatcher.py` 的 7 步）

| 步 | 做什么 | 工具 |
|---|---|---|
| 1/7 | 校验原版 APK 指纹，抽出 `libTrialsGo.so` / `libubiservices.so` / `libplayground.so` / `AndroidManifest.xml` / `classes.dex` | `tfpatcher.py` 内联 |
| 2/7 | `libTrialsGo.so`：**17 处**定点字节补丁 | `patch_native.py` |
| 3/7 | 注入服务器地址钩子（DT_INIT 运行期改写） | `patch_dynaddr.py` ×2、`patch_urls.py` ×1 |
| 4/7 | `AndroidManifest.xml`：`targetSdkVersion 30 → 27`（放开明文 HTTP） | `patch_manifest.py` |
| 5/7 | `classes.dex`：Java 侧广告与遥测改成 `return-void` / `nop` | `patch_dex.py` |
| 6/7 | 重写 zip（逐条目搬运，丢弃旧 `META-INF` 与 v7a 库） | `build_apk.py` |
| 7/7 | zipalign + apksigner（v1/v2/v3 全开） | Android SDK |

原版库的期望指纹（7.9.4 / versionCode 561，写死在 `tfpatcher.py`）：

| 库 | 大小 | SHA256 |
|---|---|---|
| `libTrialsGo.so` | 14901128 | `743f945c…70fb7f4` |
| `libubiservices.so` | 10665936 | — |
| `libplayground.so` | 2950640 | — |

### 2.1 `patch_native.py` —— 17 处定点补丁

每个补丁都声明 `original` 字节序列，改之前逐字节比对；`--dry-run` 只校验不写文件，
`--report <json>` 输出结果。`tools/make_apk.ps1` 生成的报告就是它写的。

**玩法 / 联网（7 处）**

| id | 符号 | 做什么 / 为什么 |
|---|---|---|
| `anticheating-off` | `tr::AntiCheating::isValid()` | 恒 `true` → 关掉反作弊、签名与时钟校验 |
| `unlimited-fuel` | `tr::ConsumableManager::isUnlimitedFuel(int)` | 恒 `true` → 无限燃油 |
| `no-offer-blacklist` | `tr::OfferData::isBlackListed(int,bool)` | 恒 `false` → 没有 offer 被拉黑 |
| `spend-adds-instead-of-subtracts` | `tr::PlayerItems::remove(int,int)` | `sub w11,w11,w2` 改成 `add` → 花货币道具不减反增 |
| `dl-content-always-ready` | `tr::DLContentManager::isDLReady()` | 恒 `true` → 内容包视为就绪，不再弹「下载暂停」，解锁周赛/关卡前置检查 |
| `no-blacklist-popup` | `tr::MenuzStateMain::isUserBlackListed()` | 恒 `false` → 不再弹「警报！」。原逻辑比对安装器白名单 + apk 签名，重签名 + adb 安装必然两条全中 |
| `no-ads` | `tr::AdInterface::initAndroid()` | `cbz w0` 改成无条件 `b`，提前返回。全库唯一初始化 Tapjoy / AdMob / Flurry / AdColony 的地方就是这里，于是广告全不加载、也不再产生广告网络流量 |

**真钱内购（2 处）**

| id | 符号 | 做什么 / 为什么 |
|---|---|---|
| `iap-failed-redirects-to-complete` | `tr::StoreManager::onPurchaseFailed(int, mz::IAPItemInfo*)` | 函数头改成尾调用 `onPurchaseComplete`（`x2 = IAPReceipt*` 传 NULL） |
| `iap-cancel-redirects-to-complete` | `tr::StoreManager::onPurchaseCancel(mz::IAPItemInfo*)` | 同上，覆盖取消路径 |

> 为什么不是「让服务器回购买成功」：反汇编证明 `StoreManager::onNetworkDataReceived`
> 的 cmd 0x17 分支只是**再调一次** `mz::IAPManager::purchase()`，仍然走 Google Play。
> 真正无条件发奖的是 `StoreManager::onPurchaseComplete`（@`0x579940`，3296 字节，
> 全程不校验收据、不联网）。它在 `IAPManagerListener` vtable 的槽 0，
> 失败/取消分别是槽 `0x08`/`0x10`。把这两个入口改成尾调用它，
> Google Play 的失败回调就变成「谢谢你的购买！」并正常发奖。
> `onPurchaseComplete` 内 `0x579ad0`/`0x579e90` 两处 `cbz x20` 有 NULL 保护，所以传 NULL 收据安全。

**VIP / 骑士俱乐部（8 处）**

| id | 符号 / 地址 | 做什么 / 为什么 |
|---|---|---|
| `vip-membership-null-guard-slot0-a/b/c` | `tr::VIPManager::getPlayerMembership()` +0x78/+0x7C/+0x80 | 把 `ldr w8,[x0]` 前移成开头的 `cbz x0`，用冗余槽补回原 `cbz w8` |
| `vip-membership-null-guard-slot1-a/b` | 同函数 +0xF4/+0xF8 | 第二个会员槽位的同一处空指针解引用 |
| `vip-shop-offer-iap-stub-call` | `tr::OfferManager::findVIPOffers(…, u16)` +0xC0 | 把那一处 `bl IAPManager::getProductInfoEnabled` 改跳代码洞 |
| `vip-shop-offer-iap-stub` | `0x0096D85C` | 代码洞（4084 字节空闲区）：`adrp/add` 返回伪造结构指针，`ret` |
| `vip-shop-offer-iap-fakeinfo` | `0x0096D86C` | 伪造的 `IAPItemInfo`（`+0x84 = 1`，即 `getProductInfoEnabled` 认可的 bit0） |

> 前 5 处是 `ROADMAP` 第 1 条「联网闪退」的真凶：`GlobalData::init → UserTracker::init →
> sessionStart → DNAManager::sendDnaEvent → updateCommonAttributes → getMembershipDate →
> getPlayerMembership`，崩溃在 `+120`。该函数有三道闸（网络已连接、反作弊有效、
> `PlayerItems::getItemCount(0x80,0)` 为真），过了闸之后解引用会员计时器指针 ——
> 那个指针要等 `VIPManager::activateMembership()` 创建，而 `GlobalData::init` 比
> `VIPManager::init` 早约 `0x1D4` 字节，所以启动早期必然是 NULL。
> 这里插 NULL 保护而不是把返回值涂成常量，是为了**保留真实 VIP 状态上报**的能力。
>
> 后 3 处让离线商店也出现 VIP 档位：`VIPManager::isVIPStoreOfferAvailable()` 要求
> `findVIPOffers` 两个出参都非 NULL，而离线没有 Google Play，
> `mz::IAPManagerAndroid::LoadStore` 一个产品都没加载，`getProductInfoEnabled` 永远返回 NULL。
> 只改 `findVIPOffers` 里那一条 `bl`，其它 IAP 调用点（尤其 `0x0088a3e4` 的购买校验）完全不动。

### 2.2 `patch_urls.py` —— 静态改写域名

`.rodata` 里的 URL 是「`scheme://host` + 路径」整串存的，本工具只替换**前段**，路径原样保留，
剩余空间 NUL 补齐。**新串不得比旧串长**，否则报错退出 —— 绝不越界改写。

```bash
python tools/patch_urls.py --so in.so --out out.so --base 127.0.0.1:8000
```

用在 `libplayground.so` 上，因为**该库空间已满，无法注入 DT_INIT**（见 2.3）。

### 2.3 `patch_dynaddr.py` —— 运行期服务器地址（Design H）

这是让「同一份 APK 指向任意服务器、改文本文件即生效」的关键：

1. 在可执行节里找一块**全零的代码洞**，写入一个小例程。
2. 把 `.dynamic` 里一个空闲的 `DT_NULL` 槽改成 `DT_INIT` 指向它。动态链接器加载该库时先跑它。
3. 例程用**裸 syscall**（`openat`/`read`/`close`，不依赖任何导入符号）读
   `/sdcard/Android/data/<pkg>/files/tf_server.txt`，取第一行并修剪首尾空白；
   读不到就回落到构建期默认地址（`--base`）。
4. 对本库每个 URL 字面量：先把覆盖它的页 `mprotect` 成 RW，再就地重写成
   `"http://" + 地址 + 原来的路径尾巴`，余下 NUL 补齐。

`--dump-asm tmp/last_asm.s` 会把生成的汇编存出来看。

用在 `libTrialsGo.so` 与 `libubiservices.so` 上。

### 2.4 `patch_manifest.py` —— 二进制 AXML 读写

只做能证明的事：`dump` 打印字符串池与每个 `<element>` 的属性（带绝对偏移）；
`set` **就地**改属性数值（不改变文件长度，因此不需要修 chunk size）；`get` 读一个值。

```bash
python tools/patch_manifest.py dump 原版AndroidManifest.xml --grep targetSdk
python tools/patch_manifest.py set  in.xml out.xml targetSdkVersion=27
```

### 2.5 `patch_dex.py` —— dex 外科手术

把指定方法体的**第一条指令**改成 `return-void`（`0x0e`）；对 `onCreate` 这种大方法，
则只把某条 `invoke-static` 换成 `nop`。只改写目标方法的 `code_item.insns`，
dex 其余字节一个不动，改完重算 header 的 Adler-32 checksum 与 SHA-1 signature。

> **为什么不重编译 smali**：`apktool b` 会重新编码整个 dex（本工程实测
> `classes.dex` 8872856 → 8820212，`classes2/3` 也各变几 KB），改动面覆盖全部 17835 个类。
> 这里风险面只有两个方法。

写入 dex 的 6 处改动：

| 类 | 方法 | 方式 |
|---|---|---|
| `CustomNativeActivity` | `initAdMobRewardedVideoAds` | `return-void` |
| `CustomNativeActivity` | `tapjoyInit` | `return-void` |
| `Crashlytics` | `log` / `logException` / `setString` | `return-void` |
| `CustomNativeActivity` | `onCreate` 里的 `Fabric.with(...)` | `invoke` 改 `nop` |

> 为什么 `Crashlytics` 三个方法也要砍：光把 `onCreate` 里的 `Fabric.with(...)` 换成 `nop`
> 会让 App 直接崩 —— 后面还会调 `Crashlytics.setString(...)`，它内部走
> `checkInitialized() → getInstance() → Fabric.getKit() → Fabric.singleton()`，
> Fabric 没初始化就抛 `IllegalStateException("Must Initialize Fabric before using singleton()")`。

### 2.6 `build_apk.py` / `make_apk.ps1`

`build_apk.py` 从干净原版 APK 重写 zip：逐条目原样搬运，**保留每一条自己的压缩方式与
`external_attr`**，默认丢弃旧 `META-INF`（apksigner 会写新的），不做任何「顺手优化」。

```bash
python tools/build_apk.py --base 原版.apk --out 改好.apk \
    --replace lib/arm64-v8a/libTrialsGo.so=打过补丁的.so \
    --drop-prefix lib/armeabi-v7a/
```

`make_apk.ps1` 是早期的手工打包流水线，现在 `tfpatcher.py` 已覆盖它的功能；保留是为了
「只有 `.so` 改了、想快速重打包」的场景。

```powershell
pwsh -File tools\make_apk.ps1 -Name m3
```

### 2.7 `ghost_index.py` / `gref_global.py`

* `ghost_index.py` 扫 `server/data/ghosts/<track>/*.bin`（`ghost_<owner>_<id>.bin`），
  解析头部后重新生成 `server/data/ghosts/INDEX.md`。改过幽灵仓库后跑一下。
  `OWNER_NOTE` 把 owner 哈希映射成人话：`0` = 本机占位、`6f857655` = 好友的真幽灵、
  `99511744` = 本账号。
* `gref_global.py` 扫 `.text` 里 `adrp Xn,<page>; ldr Xn,[Xn,#off]` 形式的全局引用。
  定位某个全局槽（GOT/data）在哪里被读时用，比线性反汇编抗数据段干扰。

```bash
python tools/gref_global.py <so> 0xe20000 0x420
```

---

## 3. 设备侧脚本

游戏把运行期数据放在私有目录 `/data/data/<pkg>/files`，而 `tf_server.txt` 需要能被
PC/用户改。这两个脚本把**私有 `files/`** 与共享存储里的目录 bind-mount 到一起。

| 脚本 | 作用 |
|---|---|
| `tf_redirect_mount.sh` | `/data/data/<PKG>/files` ← `/data/media/0/Android/data/<PKG>/files` |
| `tf_redirect_unmount.sh` | 还原成私有目录 |

两条**必须遵守**的规则，都是踩出来的：

* **用 ext4 路径 `/data/media/0/...`，不要用 `/sdcard/...`**：后者是 sdcardfs 视图，
  会改变权限/属主语义。
* **chown 的对象必须正确**：mount 之后**每个文件**都要 chown 成 app uid + group
  `sdcard_rw`，root-owned 的文件会让游戏启动后段错误。
  unmount 时 uid **必须从包目录推导，绝不能从 `$DST`** —— mkdir 之后私有目录可能是
  root-owned，会让整个游戏数据被 chown 成 root，症状是 `IAPManager_CallInit` 段错误。

OBB / expansion（`content.dat`、`contentSFX.dat`、`textures_android.dat`、`tf_server.txt`、
`vungle_cache`）本来就该在共享存储，留在原地不动。

---

## 4. `tools/re/` —— 逆向工具箱

全部只读。**无依赖的放前面**，需要 `pyelftools` / `capstone` 的另标。

### 4.1 反汇编与符号

| 工具 | 依赖 | 用法 |
|---|---|---|
| `disasm.py` | capstone | `disasm.py <so> <0xaddr> [len] [--bl-only]` —— 反汇编一段，自动把 `bl`/`b` 目标标成符号名 |
| `syms.py` | pyelftools | `syms.py <so> <子串…>` —— 列 `.symtab`/`.dynsym` 符号 |
| `symaddr.py` | 无 | `symaddr.py <so> <符号名\|子串> [--sub]` —— 打印地址/大小 |
| `callers.py` | 无 | `callers.py <so> <0xaddr\|symbol>` —— 找所有 `bl` 调用点（含经 PLT 的导出符号调用），顺带标出所在函数 |

```bash
python tools/re/callers.py libTrialsGo.so 0x5070cc
#   0x006341cc <- tr::WeeklyChallengeManager::onReceivedPlayerStats
#   0x006fa4fc <- tr::IngameStateLeaderboard::setupRaceButton
#   0x0077e1dc <- tr::MenuzStateMap::setupRaceButton
```

### 4.2 定位字符串 / 常量 / 全局引用

| 工具 | 用法 |
|---|---|
| `cstr.py` | `cstr.py <so> <0xva…>` —— 按 VA dump C 字符串 |
| `strs.py` | `strs.py <so> <子串…>` —— 列文件里所有含该子串的 C 字符串（含偏移） |
| `imm.py` | `imm.py <9e474b4a> [so]` —— 扫 `.text` 找组装出该 32 位常量的 `MOVZ`/`MOVK` 立即数对 |
| `gref.py` | `gref.py <so> <0xva…>` —— 找 `adrp(+add)` 解析到该 VA 的位置（纯位运算，不做线性反汇编） |
| `xref_adrp.py` | capstone | `xref_adrp.py <so> <0xva…>` —— 健壮版 `adrp+add/ldr` 引用扫描，逐寄存器跟踪 ADRP 页，容忍中间夹其它指令，并标出所在函数 |

> `imm.py` 是找本地化 KEY 的主力：游戏把 loc id 当 32 位常量 `movz/movk` 进寄存器。
> 例如找 `M_RACE_GHOST`：先 `mt_hash.py M_RACE_GHOST` → `0x9E474B4A`，再 `imm.py 9e474b4a`。

### 4.3 C++ vtable / 重定位

| 工具 | 用法 |
|---|---|
| `vtreloc.py` | `vtreloc.py <so> <0xstart> <0xend>` —— dump `.data.rel.ro` 区段，把每个 8 字节槽按**重定位**解析成符号名 |
| `gotres.py` | `gotres.py <so> <0xgot…>` —— 把 GOT/data 槽解析成符号名 |
| `reloc.py` | `reloc.py <so> <0xtarget>` —— 找 `addend == target` 的 `R_AARCH64_RELATIVE` 重定位（定位虚函数在哪个 vtable 槽） |

**`vtreloc.py` 是找 vtable 的主武器**，因为 `_ZTV*`（vtable 符号）在
`libTrialsGo.so` 的 `.dynsym` 里**不存在**，只能靠内容/重定位找。三个坑：

* 相关的是 `.rela.dyn`（**section index 7，不是 4**）；
* 槽类型是 `R_AARCH64_ABS64` = **257**（不是 `R_AARCH64_RELATIVE` = 1027）；
* `r_offset` 是 **VA**，不是文件偏移。

```bash
python tools/re/vtreloc.py libTrialsGo.so 0xdedbb0 0xdedbe0
# 0x00dedbb0  _ZTIN2tr13MenuzStateMapE
# 0x00dedbb8  OnlineGhostManagerListener::onGhostMetaDataReceived
# 0x00dedbc0  OnlineGhostManagerListener::onGhostReceived
# 0x00dedbc8  OnlineGhostManagerListener::onGhostSent
# 0x00dedbd0  _ZThn392_MenuzStateMap::onGhostQuery      ← vtable 槽 +0x18
```

（Itanium ABI：`_ZTV` 头两槽是 offset-to-top 与 typeinfo，所以
`address point = 0xdedbb8`，即第一个虚函数所在处。）

### 4.4 本地化

| 工具 | 用法 |
|---|---|
| `locdump.py` | `locdump.py dump` / `locdump.py item [maxid] [maxlvl]` / `locdump.py key <KEY>` |
| `lockey.py` | `lockey.py <0xhash> [so]` —— 反过来：扫 `.so` 里所有可打印 ASCII 串，找 `hash == target` 的 loc KEY |
| `mt_hash.py` | `mt_hash.py <KEY…>` —— `mt::String::getHashCode` @`0x8695ac` 的移植（单文件版） |

LOCF 文件来自 `content.dat` 的 `/gen/lang/<lang>_strings.bin` 成员，解包后放在 `tmp/lang/`。
`dump` 会写成 `tmp/lang/all_<lang>.txt`（`hash<TAB>text`）。

```bash
python tools/re/mt_hash.py M_RACE_GHOST     # 9E474B4A
python tools/re/lockey.py 9e474b4a          # HIT(full): M_RACE_GHOST
python tools/re/locdump.py key M_RACE_GHOST # english 'Race Ghost'
```

### 4.5 二进制比对

| 工具 | 用法 |
|---|---|
| `libdiff.py` | `libdiff.py <原版.so> <改过.so>` —— 逐字节 diff，按函数聚合，直接告诉你哪几个函数被动过 |

先给 `patch_native.py` 打过补丁的库跑一下 `libdiff.py`，是检查「补丁到底动了哪些字节」
最省事的办法。

### 4.6 逆向坐标约定

`libTrialsGo.so`（7.9.4，AArch64，14901128 字节）：

* `.text`（VA `0x3661b0`）、`.rodata`（VA `0xb3b840`）的 **VA == 文件偏移**
  —— 所以 `cstr.py` / `strs.py` 可以直接把偏移当 VA 用。
* 从 `.init_array` 起（VA `0xdb9dc8`）全部 **VA − 0x10000 = 文件偏移**：
  `.data.rel.ro` VA `0xdba140`、`.got` VA `0xe08eb0`、`.data` VA `0xe23000`。

### 4.7 `pack_write.py` —— `datapack::DataFilePack` 容器读写

```powershell
python tools/re/pack_write.py selftest                      # 内置往返自检（不需要任何输入文件）
python tools/re/pack_write.py read <pack.dat> <内部路径>     # 解出某个成员到 stdout / 文件
python tools/re/pack_write.py build <out.dat> <内部路径>=<本地文件> [...] [--word0 0x...]
```

容器格式（`0x00 u32 word0` / `0x04 u32 count` / `0x08 u32 recsize` / 表项
`{u32 uncompressedSize, u32 dataOffset, u32 nameHash}` / blob `{u32 size, u8 flag, 3 pad, payload}`，
16 字节对齐、`0xba` 填充，`nameHash = mt::String::getHashCode(path)`）见
`work/trials-frontier/notes/item-ids.md` §0；`getHashCode` 在脚本里是逐字节移植的。

**用途：做「覆盖包」** —— 往设备的 `/data/data/<pkg>/files/` 里丢一个
`TrialsContentExtraDL_*.dat`（例如只放改过的 `/conf/pvp_match_rewards.txt` 或 LOCF），
引擎会把它一起挂载，**不用重打 `content.dat`、不用重签 APK**。
挂载顺序：`GlobalData::initAdditionalDataPacks @0x4cfdd0` 把找到的名字排序后 `reverse` 逐个挂载，
`DataFilePack::searchFile @0x844a78` 从末尾往前扫 ⇒ **文件名字典序最小的那个赢**（所以探针叫
`_0probe`）。真机验证与回滚方式见 `work/trials-frontier/notes/selfcontained-apk.md`「覆盖包的插槽」节、
赛季奖励的实验见 `work/trials-frontier/notes/pvp-reward-contract.md` §5d。
`selftest` 会拿 `tmp/obb/content.dat`（若在）做往返比对，不在也能跑（只用合成数据）。

---

## 5. 素材与中间产物

| 路径 | 是什么 | 入库？ |
|---|---|---|
| `APKS/特技摩托前线/Main_APK_Backup.7z.001…011` | 原版 APK（分卷 7z，318 MB） | ❌ 已移出版本控制（`.gitignore`），磁盘保留 |
| `server/data/ghosts/<track>/*.bin` | 游戏自带静态幽灵文件 | ✅ |
| `tmp/` | 反编译树、解包产物、解出来的 `.so`、基线库 | ❌ 4.6 GB，`.gitignore` 排除 |
| `tmp/libcmp/orig-libTrialsGo.so` | **RE 基线库**（未打补丁的原版库），上面所有 `tools/re/` 例子都用它 | ❌ |
| `work/` | 工作区（`src/` 反编译、`evidence/`、签名密钥） | ❌ 只有 `work/trials-frontier/notes/*.md` 入库 |

要让 `tools/re/` 的工具跑起来，先准备一份基线库：

```bash
# 从本地保留的原版 APK 备份解出来（该目录已不入库，需自己备份一份）
7z x APKS/特技摩托前线/Main_APK_Backup.7z.001 -o tmp/extract
# 或者直接取内嵌 APK 里的库
```

然后所有 `tools/re/` 工具的第一个参数都传这个 `.so` 路径。

### 5.1 `build_item_catalog.py` —— 官方物品目录（后台「下发物品」用）

```bash
python tools/build_item_catalog.py                       # 默认读 tmp/packout/all，写 server/admin/items.json
python tools/build_item_catalog.py --packout <dir> --out <file>
```

数据全部来自游戏自己的文件，没有任何猜测：

* **物品 id ← 奖励/商店表**：扫解包目录里所有含 `"ItemId"` 的 JSON，那个 `ItemId` 就是存档
  `items2` 的键（`id = Type*5 + Tier` 那套公式也吻合）。
* **物品名 ← LOCF 本地化表**：`1516` = en、`1523` = zh-CN（繁体 1525，另有 pt/fr/de/it/ja/ko/ru/es）。
  格式 = `LOCF` + u8 版本 + u32 条数，随后 `[u32 hash][u16 len][len 字节含结尾 NUL]`；
  记录用**名字键**索引，键的哈希与 `content.dat` 条目名同一个函数（`mt::String::getHashCode`，
  脚本里的 `gh()`）。表里只有 `ITEM_<type>_<tier>`、`OUTFIT_%02d_NAME`、`LVL_<NAME>`
  这些键，所以名字必须靠 `NameId` 反查，不能直接匹配英文原文。
* **分类 + `verified`**：分类是按 `Type` 与贴图路径推的；`verified` 表示「这个类的存档写法
  **在真机上确认过**」——只剩赛道（Type 1/3）是 `false`，后台会给它挂「未验证」警告。
  改判定就改脚本里的 `category()`。★ 涂装（Type 2）**不再是条目**：它不走 `items2` 的键
  （见下），混在物品里发下去会写到零件计数上，所以 `category()` 里那条分支已删。
  蓝图是个例外：它的存档写法同样是确认过的，但 `verified` 取的是「**有没有官方文案**」
  （Tango / Bronco / Berserker 三辆没有，界面显示「无官方名」）。
* **服装 ← `/conf/customization.txt`**（`0007_*.bin`，脚本按内容找、不认文件名哈希）：`Rider` 数组
  80 条，每条 `NameStringId = OUTFIT_%02d_NAME`、`BonusPowerDescriptionStringId = OUTFIT_%02d_POWER`。
  **套装部件 id = `ItemType * 5 + tier`**（tier 0/1/2 = 头盔 / 上衣 / 裤装）；
  Rider ID 0–19 那批记录里**没有 `ItemType` 字段**，用 `type = 40 + Rider ID`（部件名反查验证过：
  `ITEM_57_0` = "The Eggman Helmet Piece"）。这套公式必须对：隐藏套装的部件 id
  **在任何配置里都不出现**（80 套 240 件里 99 件如此），挖不出来只能推。
* **`outfits` 段**：`{setKey: {key,id,idx,en,cn,comment,desc_*,bonus,bonus_*,type,type_src,parts,
  part_names,unlock,hidden,derived}}`，`setKey = "OUTFIT_34_NAME#116"`（同名两套用 `Comment`
  尾巴区分，如 Henchman Uniform 黑/橙）。`hidden` = `UnlockType` 全是 4（没上架过），
  目前 46 套；`bonus` 是效果原文（`MULTIPLY_FUEL_REFILL_TIME 0.006` = High Roller 的无限汽油），
  带效果的有 24 套。部件 id 与「赛道解锁」条目**有 20 个编号撞车**（如 1130 既是 Garbage Route
  又是 Wurst Racer 头盔）：按服装归类，旧名字记进条目的 `alias` 与 `source.overlap_ids`。
* **涂装 ← `/conf/bikes.txt`**（`0002_*.bin`，顶层 `{"BikeData": …, "SkinData": […]}`）：`SkinData`
  正好 108 款、`ID` 连续 0..107，每款 `{ID, Name, BikeID, SkinIndex, TextureName, PaintCanTexture,
  [DiamondCost], [MissionUnlock]}`；官方名来自**商店/奖励表里 `Type == 2` 记录的 `NameId`**
  （那个记录的 `ItemId` 就是 `SkinData.ID`），108 款里只有 66 款被商店引用过、67 款有官方中文名，
  其余的显示内部名（`SkinData.Name`）。
  ★★ **涂装不进 `items2` 的键空间**：存档里每辆车只有一条
  `items2[664 + BikeID] = ((当前装备的 SkinIndex + 1) << 24) | 已拥有位掩码`（位 i = 第 i 款），
  位掩码只有 24 位。这是反汇编 + 真机存档（ccb 的 665/666/668/677/678/680 六条）双向确认的；
  反汇编里那些 XOR/rotate 只是内存内的混淆，**JSON 里存的是明文**。
  所以 `paints` 段的字段是 `{id,bike,bike_en,slot,key,bit,name,nameid,en,cn,verified,comment,
  [diamond],[mission_unlock]}`，`key = 664 + bike`、`bit = 1 << slot`；后台按「车」分组列，
  勾一款 = 给那一位置 1（`tflocal_accounts._paint_value()`）。
* **蓝图 ← `/conf/upgrades.txt`**（脚本按内容找 `"Upgrades"` + `"BP"`）：`Upgrades` 每条
  `{ID, N, F, S, BP, …}`，**`BP` = 这辆车的蓝图碎片需求量**（Tango 4、Bronco 20、KTM 450 RALLY 30、
  Stallion 50…），与官方文案里 7 处 "Collect N to build" 逐条吻合。
  ★★ 蓝图是**碎片计数器**（真机档里 379 = 7 片、404 = 3 片、429 = 1004 片），编号
  `id = (车号 + 72) * 5 + 4`；反汇编印证：`MenuzComponentGarageBike::hadleBlueprintPurchase()`
  @`0x00663110` 里 `bikeID + 0x48` → `×5` → `+4` 后调 `PlayerItems::add(..., 1, ...)`，
  `MenuzBlueprintRenderer::init()` @`0x007c3060` 用 `BikeUpgrade::getUpgradeID(bikeID, 4)` 读已拥有、
  车记录 `[+0x58]` 读需求量，`blueprintComplete()` @`0x007c4e5c` 比两者是否相等。
  19 辆车里只有 12 辆有碎片编号，另外 7 辆（Armadillo / Jackal / Mantis / Marauder / Riptide /
  Phantom / Moonrover）在任何配置里都不出现（只能金币买，编号 369/384/389/394/399/409/424），
  `source.no_blueprint_bikes` 记着它们。
  `blueprints` 段字段 `{id,cat,t,en,cn,key,verified,bike,bike_en,[need],[alias]}`；
  374/379/439 的官方名被 RedLynx 写成了 Tango 的 Redlynx 涂装名，脚本换成规范名、旧名留在 `alias`。
  ★ 紧凑形式 `{IID,IL,IC}` 只有**蓝图这一族**验证过 `平面编号 = IID * 5 + IL`：赛道（`IID 170`）
  用 `IC` 装赛道 id、涂装（`IID 133/134/136`）用 `IC` 装涂装序号、零件礼包（`IID 70`）用 `IC`
  装零件号 —— 一律按公式硬算会造出 851、350 这类**不存在**的编号（试过，目录立刻多出 25 条垃圾），
  所以 `walk_itemids()` 的紧凑分支只收 `blueprint_bike(IID * 5 + IL)` 为真的节点。
* **赛道名 ← `/conf/levels.txt`**（`Levels` + `Villages`）：`Levels[]` 每条取 `ID`（赛道号，
  就是午夜杯 `weekly.track_id`、匹配池 `candidate_tracks` / `track_ids` 用的那个）与 `N`（LOCF 键），
  名字走 LOCF 两份语言包 ⇒ `levels = {"<LevelID>": {key, en, cn}}`，382 条。
  有少数条目没有本地化文本，所以前端必须能退化成显示编号。**它单独成段、不进 `items`**，
  免得 `by_cat["track"] == 157` 这类断言被赛道表搅乱。
* **奖励下拉 ← `/conf/pvp_match_rewards.txt`**：`PVPMatchRewardTypes` 是 `RewardID → 名字 → ItemId`
  的映射（1..4 是金币、5 是钻石、100 = 占位问号、20000..20049 是零件）。
  后台「赛季奖励」的特殊奖励下拉用它（`item_id 145` 的 `amount` 装的是这里面那个 **RewardID**）；
  金币/钻石（`item_id 1/2`）从下拉里排除。输出 `rewards = {"<RewardID>": {...}}`，309 条。
  ⚠ 客户端固定表 `PVPMatchSpecialRewards` 里只有 7 组 **43 个**编号（`202/203/220` + 零件 4 档），
  这是「官方赛季发过哪些」的清单，**不是**可填范围的限制 ——
  2026-10-06 真机实验（覆盖包）证明：填别的编号客户端**照样解析**，玩家看到「毛驴轮胎」的真因是
  **已经拥有**该物品时改画它自带的兜底奖励（`Fallback`，237 行里有 215 行是 `221` Doughnut）。
  所以现在后台下拉给**全部 309 条**（按类别分组、43 个官方编号标 ★），服务端只拒
  「物品表里查不到」的编号。详见 `work/trials-frontier/notes/pvp-reward-contract.md` §5d。
* `/conf/dailyrewards.txt` 有 RedLynx 原厂的漏逗号（`item-ids.md` 里记过），
  所以脚本带 `load_json_tolerant()`：去尾逗号 / 去 `//` 注释 / 按报错位置插逗号重试（最多 16 次，
  `0010_1854657d.bin` 需要 12 次）。**还有 3 个文件解析不了**，如实记进 `source.skipped_files`：
  `0005_c40462b7.bin` 是 `"I": 01`（前导零的非法数字，插逗号救不了，Crafting 表）、
  `0040_2ad9129d.bin`（`StoreCategories`，带 `Price:[{PH,PS}]`）与 `0050_fae155bb.bin`（`XpConf`）
  都在**补了尾逗号之后**又报 `Expecting ',' delimiter`（重试守卫只认这一种报错）。这 3 个文件在
  本轮之前从来没被读过，所以不算回归；要修就修加载器，与目录本身无关。

**金票（135）被显式跳过**：它不在存档 `items2` 里，走 `server/data/pvp_state.json`。

生成的 `server/admin/items.json`（478 条物品 + 80 套服装 + 108 款涂装 + 12 个蓝图 + 382 条赛道 +
309 条奖励名）同时被这些地方消费：
后台的折叠清单与物品选择器、`tflocal_accounts.grantable_items()`、`tflocal_accounts.grantable_paints()`
（可下发集合）、`tf_server.track_catalog()`（午夜杯/碉堡的赛道下拉）、`tf_server._bunker_catalogs()`
（碉堡的奖励与车辆下拉）、`tests/test_admin_webui.py::ItemCatalog` / `::OutfitSets` / `::Paints` /
`::Blueprints` / `::WeeklyOps` / `::Bunker`（形状与公式自检）。
**改了物品表 / 套装表 / 车表 / 赛道表就重跑它。**

---

## 6. 依赖

| 依赖 | 谁需要 | 说明 |
|---|---|---|
| Python 3.8+ | 全部 | 只用标准库的：`patch_native.py`、`patch_dex.py`、`patch_dynaddr.py`、`patch_manifest.py`、`build_apk.py`、`ghost_index.py`、`build_item_catalog.py`、`gref_global.py` 以及 `tools/re/` 里除下表外的脚本 |
| `pyelftools` | `patch_urls.py`、`tools/re/syms.py` | `pip install pyelftools` |
| `capstone` | `tools/re/disasm.py`、`tools/re/xref_adrp.py` | `pip install capstone` |
| Android SDK build-tools | `tfpatcher.py` 最后一步 | zipalign + apksigner；没有就用 `--no-sign` |

---

## 7. 约定

* **任何写入都先验原始字节**。`patch_native.py` / `patch_dex.py` 对不上就退出，
  `patch_urls.py` 的新串不得比旧串长 —— 宁可失败也不要越界写到别的数据上。
* **不重编译、不重新编码**。改 dex 只动目标方法的 `insns`，改 zip 只重写条目。
* **新增 native 补丁要写 `why`**。`PATCHES` 里每个条目的 `why` 就是它的文档，
  带上符号名、地址和反汇编依据；没有依据的补丁不要加。
* **窗口路径与编码**：脚本会在 Windows 上跑，`tools/make_apk.ps1` 已设
  `[Console]::OutputEncoding = UTF8`；`tools/re/` 的脚本打印非 ASCII 时用
  `ascii`/`utf-8` 显式编码，避免 `UnicodeEncodeError: 'gbk' codec`。
* 本仓库在 Windows 上偶发 `ReplaceFileW EIO (Win32 1175)`，**直接重试**即可。

---

## 8. 相关文档

* `../ROADMAP.md` —— 要做什么（唯一的目标清单）
* `../ROADMAP_STATUS.md` —— 做到哪一步了；§3.x 记的是每个真实 bug 的完整逆向链路
* `../server/README.md` —— 服务器侧的端点契约与被这些补丁打开的功能
* `../CONTEXT.md` —— 项目背景
* `../work/trials-frontier/notes/` —— 分册逆向笔记（`online-endpoints.md` 是全端点台账；
  `gift-v1.md` / `friends-v1.md` / `targeting-v1.md` / `_inline-build.md` / `item-ids.md` 按功能分册）
