# 自包含 APK：把数据塞进 APK 由 app 自己展开

**产出**：`dist/TrialsFrontier-offline-full.apk`（336 531 425 B，SHA256 `4A76FAA8…6049FA`）
**为什么**：普通用户拿不到 `/data/data/<pkg>` 的写权限（需要 root），所以外部搬运方案不可交付。但 **app 自己有那个权限** —— 数据只要进得了 APK，就能在首次启动时由 app 自己搬进去，全程不需要 root / adb / 电脑。

---

## 一句话原理

在 `AndroidManifest.xml` 里把 `<application android:name>` 从 `DexApplicationClass` **就地改成我们自己的 `OfflinePayloadSetup`**（等长改写字符串池，不动任何偏移），这个类只覆盖 `onCreate()`，先解包再 `super.onCreate()`。载荷以未压缩条目放进 `assets/tf/`。

## 三个关键设计决定

1. **挂点用 Application 名，不用 `System.loadLibrary` 或 native。**
   `DexApplicationClass` 位于 `classes.dex`，`public`，父类 `androidx.multidex.MultiDexApplication`，**只定义了一个方法** `onCreate()V` —— 继承它只覆盖 `onCreate` 是最小、最安全的改动。它在 `onCreate` 之前不覆盖 `attachBaseContext`，所以没有更早的钩子可抢，也不需要。

2. **等长改名，只改字符串池里那一条。**
   `com.ubisoft.redlynx.trialsgo.DexApplicationClass` 与 `…OfflinePayloadSetup` 都是 48 字符。
   不等长会牵动字符串池的 `size` / `offsets[]` / XML chunk size 以及之后所有偏移 —— 改动面和风险都大一个数量级。改完用 0 补齐槽位末尾即可。

3. **只带 OBB，不带那三个 `.dat`。**
   OBB（64 MB）本身是个 stored 无压缩的 zip，里面正好就是 `content.dat` + `contentSFX.dat` + `textures_android.dat`。Java 先把 OBB 拷到 `/sdcard/Android/obb/<pkg>/`，再用 `ZipInputStream` 就地解到 `/sdcard/Android/data/<pkg>/files/`。
   这样**"引擎自己解 OBB"和"引擎直接读 files/ 下的 .dat"两种路径都被覆盖**，而 APK 只多 64 MB 而不是 128 MB。
   （`.so` 里 `\.obb` 零命中、`main\.\d+\.` 零命中 ⇒ 原生代码从不直接读 OBB，只按文件名找目录。OBB 名里的 `561` 来自 `versionCode`。）

## 载荷布局

```
assets/tf/payload.txt   70 行，制表符分隔三列
assets/tf/p/NNNN        70 个载荷文件（ZIP_STORED，zipalign 对齐）
```

`payload.txt` 每行 `<kind>\t<相对路径>\t<assets 名>`：

| kind | 目标目录 | 内容 |
|---|---|---|
| `f` | `Context.getFilesDir()` | `/data/data/<pkg>/files/` 里的内容 |
| `r` | `getFilesDir().getParentFile()` | `/data/data/<pkg>/` 包根（`.cache/`、`shaders/`、`shared_prefs/`、`aUiMEPVatQ.apk`） |
| `e` | `getExternalFilesDir(null)` | `/sdcard/Android/data/<pkg>/files/` |
| `o` | `getObbDir()` | OBB，拷完后再就地解包 |

共 **70 条 / 309 569 087 字节（295.2 MB）**：`appdata/` 67 文件 242 324 703 B → `r`；OBB 67 244 348 B → `o`；生成的 `tf_server.txt` 18 B → `e` 和 `f` 各一份（`f` 最后写，所以 `/data/data/.../files/tf_server.txt` 里是生成的那份）。

**只有全部成功才写标记** `getFilesDir()/.tf_payload_v1`；失败则下次启动重试，不会半途而废地"假装完成了"。

## 源码

| 文件 | 作用 |
|---|---|
| `tools/apkpayload/OfflinePayloadSetup.java` | 自解包 Application；TAG `TFUnpack`，`BUF=1<<20` |
| `tools/apkpayload/stub/DexApplicationClass.java` | **编译期影子类**，只为让 javac 认父类与 `@Override`；**不参与 d8** |
| `tools/make_selfcontained.ps1` | 一条命令走完全流程 |
| `tools/build_apk.py` | 加了 `--add APK内路径=本地文件`，以 `ZIP_STORED` 写入（store 条目才能被 zipalign 4 字节对齐），并检查与原有条目重名 |
| `tools/patch_manifest.py` | 加了 `setstr in.xml out.xml 旧串=新串` 子命令 |

## 构建

```powershell
pwsh -NoProfile -File tools\make_selfcontained.ps1
```

流程：从基线 APK 取出 `AndroidManifest.xml` → `setstr` 换 Application 名 → `set minSdkVersion=21` → javac + d8 产出 `classes4.dex` → 生成 `payload.txt` → `build_apk --replace AndroidManifest.xml` + 70 条 `--add` → `zipalign -p -f 4` → `apksigner`（v1/v2/v3）→ `tmp/build/tf-selfcontained.apk`。

工具链（本机实测可用，别再摸索）：

```powershell
$env:JAVA_TOOL_OPTIONS='-Duser.language=en -Duser.country=US'   # 否则 javac 报错是 GBK 乱码
$AJ = 'C:\Users\<user>\AppData\Local\Android\Sdk\platforms\android-37.0\android.jar'
javac -nowarn -source 8 -target 8 -bootclasspath $AJ -encoding UTF-8 -classpath <影子class目录> -d <out> <主类>.java
& '<...>\build-tools\36.0.0\d8.bat' --min-api 21 --lib $AJ --output <dex输出目录> <每个 .class 的绝对路径>
```

- JDK 25 会警告 source/target 8 过时 —— 能编，忽略。
- d8 会警告 `Type com.ubisoft.redlynx.trialsgo.DexApplicationClass was not found, it is required for default or static interface methods desugaring` —— **无害**，运行时那个类在 `classes.dex` 里。
- 本机**没有** apktool、**没有** NDK/clang，所以走的是 dex 注入而不是全量重编码。

## 踩过的两个坑（别再踩）

1. **`AssetManager.open()` 要的是真路径，不是相对名。**
   `payload.txt` 第三列写 `p/0068`，但 APK 里的实际条目是 `assets/tf/p/0068`。第一版直接把 `p/0068` 丢进 `AssetManager.open()`，真机上 70 个文件全报 `java.io.FileNotFoundException: p/0068`。
   → `copyAsset(ctx, ASSETS + "/" + asset, out)`。
   失败栈长这样：`AssetManager.nativeOpenAsset` → `AssetManager.open` → `copyAsset` → `unpack` → `onCreate` → `Instrumentation.callApplicationOnCreate` → `ActivityThread.handleBindApplication`。

2. **别拿相对路径去 `Substring` 绝对路径。**
   `$f.FullName.Substring($appdata.Length + 1)` 里 `$appdata` 是相对路径（42 字符）、`$f.FullName` 是绝对路径，算出来的"相对路径"是 `ack/TrialsFrontier-clean-pack/appdata/.cache/classes.dve` 这种垃圾。
   → `$appdata = (Resolve-Path (Join-Path $PayloadDir 'appdata')).Path`，并加断言 `if ($rel.Contains(':') -or $rel.Contains('..')) { throw }`。

## 为什么要 `minSdkVersion 21`

API < 21 时框架无法从 `classes2.dex` 及以后加载 Application 类（`MultiDex.install` 要等 `MultiDexApplication.attachBaseContext` 才跑，而那时 Application 类已经被解析了）。我们把新类放进 `classes4.dex`，所以必须抬到 21。代价是放弃 Android 4.x/5.0；目标是现代设备与模拟器，可接受。

## 真机验证（`<设备序列号>`，2026-10-05）

装完启动的完整日志（**E 级 0 条**）：

```
I TFUnpack:   r .cache/classes.jar  <n> 字节        × 70 行
I TFUnpack:   o main.561.com.ubisoft.redlynx.trialsfrontier.ggp.obb  67244348 字节
I TFUnpack:   e tf_server.txt  18 字节
I TFUnpack:   f tf_server.txt  18 字节
I TFUnpack: 拷贝完成: 成功 70 个 / 309569087 字节，失败 0 个
I TFUnpack: main.561.com.ubisoft.redlynx.trialsfrontier.ggp.obb 解开 3 个条目 -> /storage/emulated/0/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files
I TFUnpack: 全部就位，写了标记 .tf_payload_v1
```

核对过的副作用：

- `/data/data/<pkg>/files/player.bin` **存活**（4141 B，载荷里已裁剪掉，不会被覆盖）。
- 三个 `.dat` 与 OBB 属主正确：`u0_a296:sdcard_rw` —— 这一点很重要，见 `tools/tf_redirect_mount.sh` 里的血泪教训：属主错了游戏约 5 秒后 segfault 且零网络流量。
- 二次启动打印 `数据早就在了，跳过`。
- 游戏正常进村庄界面（截图 `tmp/sc_after_unpack.png`），存档完好（457/457、16840907、9072272、等级 14）。
- `logcat -b crash` 里只有指纹 HAL（`android.hardware.biometrics.fingerprint-service.xiaomi`）的老噪声，与本游戏无关。

## 一个必须知道的事实：启动 Activity 是 `ExpansionDownloaderActivity`，不是 `CustomNativeActivity`

```
cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER <pkg>
→ com.ubisoft.redlynx.trialsfrontier.ggp/com.ubisoft.redlynx.trialsgo.ExpansionDownloaderActivity
```

`CustomNativeActivity` 挂的是自定义 action `com.ubisoft.redlynx.trialsfrontier.ggp.MESSAGE`，**不在 LAUNCHER 里**（早前"它不是入口"的判断是错的）。

**这恰恰是挂 Application 而不是挂 Activity 的理由**：`Application.onCreate()` 一定先于任何 Activity 跑，所以等 `ExpansionDownloaderActivity` 去做扩展包检查时，OBB 已经躺在 `/sdcard/Android/obb/<pkg>/` 了。如果挂点选在 Activity 上，就会先被下载器拦下来。

（清单里**没有** `ExpansionSize` / `ExpansionVersionCode` meta-data，所以没人校验 OBB 的字节大小 —— 这也是能这么干的前提之一。）

## 模拟器验证（`emulator-5554`：x86_64 + houdini，全新安装）

这是**真正的冷启动测试**：模拟器上前所未有地干净 —— 没装过游戏、没有存档、没有 OBB、没有任何 data 区文件。整套流程只有一步：`adb install dist\TrialsFrontier-offline-full.apk`。

结果（**安装后 app 自己起来了，我甚至没来得及点图标**）：

```
10-05 12:27:53.118  3340 I TFUnpack: main.561.…obb 解开 3 个条目 -> /storage/emulated/0/Android/data/…/files
10-05 12:27:53.119  3340 I TFUnpack: 全部就位，写了标记 .tf_payload_v1
10-05 12:27:53.736   361 I ActivityTaskManager: Displayed …/ExpansionDownloaderActivity for user 0: +2s483ms
10-05 12:28:00.751  3340 I houdini : [3340] Expected CPU feature >> AES << is not supported.
10-05 12:28:01.770   361 I ActivityTaskManager: Displayed …/CustomNativeActivity for user 0: +1s25ms
```

连 `houdini` 都打日志了 —— 说明 **arm64-v8a 的 native 库真的在 x86_64 模拟器上跑起来了**（模拟器的 `ro.product.cpu.abilist` 是 `x86_64,arm64-v8a,x86,armeabi-v7a,armeabi`，`ro.dalvik.vm.native.bridge=libhoudini.so`）。所以**不需要**再打一份 armeabi-v7a 进去。

落盘核对：

| 位置 | 内容 | 属主 |
|---|---|---|
| `/data/data/<pkg>/files/` | 68 项 195 MB，含引擎自己展开出的 `TrialsContentExtraDL_*.dat` / `TrialsTexturesDL_*.dat` | `u0_a70` |
| `/sdcard/Android/data/<pkg>/files/` | `content.dat` 24397972 · `contentSFX.dat` 5651152 · `textures_android.dat` 37194884 · `tf_server.txt` 18 | `u0_a70:ext_data_rw` |
| `/sdcard/Android/obb/<pkg>/` | `main.561.…obb` 67244348 | `u0_a70:ext_obb_rw` |
| `/sdcard/ubisoft/` | `ubisoftGlobalSave.dat` **90 B**（干净安装后游戏自己新建的存档） | `media_rw` |

`logcat -b crash` 空。`CustomNativeActivity` 是 `topResumedActivity`，截图 `tmp/emu_after_unpack.png` 显示**已经进了教程第一关的实机画面**（骑手 + 沙漠岩石场景）—— 不是菜单、不是黑屏，是真正的游戏内容在渲染。

> `/data/data/<pkg>/files/` 里那些 `TrialsContentExtraDL_*.dat` / `TrialsTexturesDL_*.dat` 是**引擎自己**从 OBB 展开出来的（我们的载荷里没有这些文件），这反过来证明引擎确实找到了 OBB 并正常消费了它。

## 已知边界

- 载荷清单是**构建时快照**。若今后改了 `tmp/pack/TrialsFrontier-clean-pack/` 的内容，必须重跑构建，否则 APK 里还是旧数据。
- 展开是"拷贝覆盖"而非"增量合并"：APK 里的旧文件会盖掉设备上的同名文件。因此 `player.bin` 这类存档**必须留在载荷之外**（当前已排除），否则每次重装都会重置进度。
- `tf_server.txt` 由构建脚本生成（默认 `192.168.1.100:8000`），不来自 payload 目录，用户改 IP 时两处（`/data/data/...` 与 `/sdcard/...`）都改最保险。
