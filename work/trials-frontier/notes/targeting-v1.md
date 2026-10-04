# Trials Frontier 7.9.4 — `targeting/v1` 端点族逆向报告

- **对象**：`libTrialsGo.so`（AArch64 / IL2CPP），Trials Frontier（Android）7.9.4
- **样本**：`tmp/libcmp/orig-libTrialsGo.so`，14901128 字节
- **地址约定**：`.text`（VA `0x3661b0`）与 `.rodata`（VA `0xb3b840`）的 **VA == 文件偏移**；从 `.init_array` 起 **VA − 0x10000 == 文件偏移**（`.data.rel.ro` VA `0xdba140` / off `0xdaa140`；`.data` VA `0xe23000` / off `0xe13000`）
- **方法**：IL2CPP 符号表（`.dynsym` 未剥离）+ `.rela.dyn`/`.rela.plt` 重定位解析 + Capstone 全函数反汇编。**每一条结论都可回溯到具体地址与指令**，未从其它 IL2CPP 游戏泛化。

---

## 0. 结论速览

| # | 结论 | 关键证据 |
|---|---|---|
| 1 | `.rodata` 中 `/targeting/v1/` 的 op 字面量**只有 7 个**：`configuration`（2 种形式）、`condition_items`、`vip_registration`、`direct_vip_registration`、`vip_validation`、`vip_badge_option` | 全二进制 ASCII 扫描，命中区间见 §2 |
| 2 | `/public/targeting/v1/configuration` 是 **POST**，cmd = **0x49 (73)**，body 是拼出来的 JSON（末尾 `,` 被就地改成 `}`） | `0x4ee790 bl OnlineCore::postJson`，`0x4ee780 mov w4,#0x49` |
| 3 | 同一个 cmd **0x49** 也用于 **GET** 形式 `/public/targeting/v1/configuration?pid=%d&random_group=%f&...`（匿名配置）；两者的响应走**同一个 handler** | `0x4ee9e0 mov w3,#0x49`（`getAnonymousConfiguration`） |
| 4 | `/public/targeting/v1/condition_items` 是 **GET**，cmd = **0x85 (133)**，且 **`type=bundles` 是硬编码字面量**，客户端只会发这一种 `type` | `0x516020 mov w3,#0x85`；路径字面量 `0xb88e97` 直接内嵌 `?type=bundles` |
| 5 | `condition_items` 的响应**根必须是 JSON 数组**，元素**必须是整数**；这份整数列表就是**礼包（bundle）id 白名单**，被 `StoreItem::unlockConditionsOK` 消费 | `parseConfigData` `0x515e34 cmp w8,#2`（根必须是 ARRAY）；`0x515e58 cmp w8,#4`（元素必须是整数） |
| 6 | `configuration` 的响应根是**对象**，且**一个响应同时承载 4 件事**：商店限购表（`limited_purchases`）、静默登录开关（`login.enabled`）、最低版本门限（`update` / `update_platform`）、**配置包下载清单**（`metadata.downloadurl`） | `OnlineConfiguration::parseJsonResponse` `0x4eeb50` |
| 7 | `pay_times` 是 `configuration` 里**唯一直接影响 StoreItem 是否解锁**的键（写入 `OnlinePlayer+0x6c68`，在 `StoreItem::unlockConditionsOK` 里与条件字段比较） | `0x60:0x6099e0 mov w10,#0x6c68` / `0x6099f0 ldr w9,[x9,x10]` |
| 8 | **崩溃风险极低**：`tr::json_strcmp` 对 NULL 有保护；`json_parse` 任何失败路径都返回 NULL；所有解析器都显式判 NULL / 判类型。**没有发现「缺 key ⇒ 无条件解引用」的模式**——与项目此前 `reward_config` 的 bug 不同 | `0x569138`（json_strcmp 全文 20 字节）；`0x88b730 mov x0,xzr` |
| 9 | `metadata.downloadurl` 让**服务器可以命令客户端下载并写入任意 URL**（逗号分隔、URL-decode 后逐条 GET，cmd 0x4a），这是本端点族里权限最大的一处 | `0x4eeda8 strtok(..., ",")`；`0x4ef034 mov w3,#0x4a` |
| 10 | 礼包真正变成可见弹窗的链路是：`MenuzStateMain::onBecomeTopmostState` → `ProfileEligibilityManager::fetchConfig` → `GetBundleConfig`(cmd 0x85) → `parseConfigData` → `isBundleEligible` → `StoreItem::unlockConditionsOK` → `OfferManager::pushPopup/checkDoubleOfferPopup/checkRetentionOfferPopup` → `UserTracker::openBundleOfferPopup` | 见 §6 |

---

## 1. 类归属与 vtable

### 1.1 网络层（`mz::NetworkDataListener` 子类）

`mz::NetworkDataListener` 接口本身（vtable `_ZTVN2mz19NetworkDataListenerE` @ `0xdfbc18`，56 字节）除析构外只有 **3 个虚函数**，相对对象 vptr 的索引为：

| idx | 函数 |
|---|---|
| 0 | `D2`（complete destructor） |
| 1 | `D0`（deleting destructor） |
| 2 | `onNetworkError(MZ_NETWORK_ERROR, uint, uint, void*)` |
| 3 | `onNetworkServerTimeUpdated(uint)`（`0x4eb384`，基类实现） |
| 4 | `onNetworkDataReceived(uchar*, uint, int, int, void*)` |

#### `tr::OnlineConfiguration`（`configuration` 的网络层 + 配置包下载器）

- vtable `_ZTVN2tr19OnlineConfigurationE` @ **`0xdd7980`**（`.data.rel.ro`，176 字节 = 22 槽 = 主 vtable 13 槽 + 次 vtable 9 槽）
- typeinfo `_ZTIN2tr19OnlineConfigurationE` @ `0xdd7a30`
- 主 vtable（槽 0..12）：`[0]`=offset-to-top、`[1]`=typeinfo、`[2]`=`D2`、`[3]`=`D0`、`[4]`=`onNetworkError`、`[5]`=基类 `onNetworkServerTimeUpdated`、`[6]`=`onNetworkDataReceived`、`[7]`=`onDataReceived(TR_ONLINE_ERROR, char const*, int)`、`[8]`=`onQueryCompleted`、`[9]`=`onDataDeleted`、`[10]`=`onDataAdded`、`[11]`=`onDataSent`、`[12]`=`onMetaDataReceived`
- 次 vtable（槽 13..21）：`[13]`=offset-to-top、`[14]`=typeinfo、`[15..20]`=6 个 `_ZThn8_` thunk、`[21]`=`OnlineUserStorageListener::onMetaDataUpdated(TR_ONLINE_ERROR)`（基类实现）
  ⇒ 本类有**两个基类 vptr**：主接口在 `+0x00`，另一个基类子对象在 `+0x08`（由 `_ZThn8_` 推得）。

**对象布局（`tr::OnlineConfiguration`）**——由 `getConfiguration`/`parseJsonResponse`/`onNetworkDataReceived` 的写入点归纳：

| 偏移 | 类型 | 含义 |
|---|---|---|
| `+0x00` | vptr | 主接口 |
| `+0x08` | vptr | 次接口 |
| `+0x10` | `OnlineConfigurationListener*` | 用户监听器（`0x4ee574 str x1,[x19,#0x10]`）。**7.9.4 中未见任何地方调用它**（全类范围无 `ldr x8,[x19,#0x10]; ldr x8,[x8]; blr x8` 序列），能查到该类型的只有两个 `get*Configuration` 签名，`.rodata` 里**没有** `_ZTIN2tr27OnlineConfigurationListenerE` |
| `+0x20` | `char**` | 配置包 URL 指针数组（每项 `operator new[](len+0x20)` 得到） |
| `+0x60` | `int` | 配置包 URL 个数 |
| `+0x64` | `int` | 已发起的配置包下载序号 |
| `+0x68` | `int` | 已成功写入的配置包个数（由 `writeConfiguration` @ `0x4ef1d8` 维护：`0x4ef204 ldr w8,[x19,#0x64]` / `0x4ef29c ldr w8,[x19,#0x68]` → `0x4ef2a4 str w8,[x19,#0x68]`） |
| `+0x6c` | `int` | 配置版本号（来自 `metadata.version`），若请求挂起标志置位则 `orr #0x1000000` |
| `+0x70` | `char[0x80]` | 配置包名（来自 `metadata.name`，`strncpy(...,0x80)`） |
| `+0xf0` | `bool` | 请求挂起标志（`getConfiguration` 尾部 `strb w21,[x19,#0xf0]`；`getAnonymousConfiguration` 置 0） |

方法表（`_ZN2tr19OnlineConfiguration*`）：

| 地址 | 大小 | 符号 |
|---|---|---|
| `0x4ee320` | 112 | `C1`/`C2` |
| `0x4ee394` | 160 | `reset()` |
| `0x4ee434` | 272 | `deleteConfigurations()` |
| **`0x4ee544`** | 652 | **`getConfiguration(OnlineConfigurationListener*)`** |
| `0x4ee7d0` | 44 | `getUniqueIdentifier(char*)` |
| `0x4ee7fc` | 12 | `getPlaform()` |
| **`0x4ee808`** | 564 | **`getAnonymousConfiguration(OnlineConfigurationListener*)`** |
| **`0x4eeb50`** | 1472 | **`parseJsonResponse(int cmd, char* body)`** |
| `0x4ef110` | 180 | `downloadNextFile()` |
| `0x4ef1c4` | 20 | `onDataReceived(TR_ONLINE_ERROR, char const*, int)` |
| `0x4ef1d8` | 324 | `writeConfiguration(void* data, int len)` |
| **`0x4ef334`** | 8 | **`onQueryCompleted(TR_ONLINE_ERROR, char const*)`** |
| `0x4ef348` | 128 | `onNetworkError(MZ_NETWORK_ERROR, uint, uint, void*)` |
| **`0x4ef3c8`** | 256 | **`onNetworkDataReceived(uchar*, uint, int, int, void*)`** |
| `0x4ef4c8` | 52 | `downloadConfiguration(char const*)` |

#### `tr::OnlineProfileEligibilityManager`（`condition_items` 的网络层）

- vtable `_ZTVN2tr31OnlineProfileEligibilityManagerE` @ **`0xdd90d0`**（56 字节 = 7 槽）
- typeinfo `_ZTIN2tr31OnlineProfileEligibilityManagerE` @ `0xdd9110`（16 字节，单继承）

| 槽 | 目标 |
|---|---|
| 0 | offset-to-top |
| 1 | typeinfo |
| 2 | `D2` |
| 3 | `D0` |
| 4 | `onNetworkError(MZ_NETWORK_ERROR, uint, uint, void*)` |
| 5 | `NetworkDataListener::onNetworkServerTimeUpdated(uint)`（未覆盖） |
| 6 | `onNetworkDataReceived(uchar*, uint, int, int, void*)` |

方法表：

| 地址 | 大小 | 符号 |
|---|---|---|
| `0x515c54` | 28 | `C1`/`C2` |
| `0x515c70` / `0x515cac` | 60 / 68 | `D1`/`D2` / `D0` |
| `0x515cf0` | 12 | `uninit()` |
| `0x515cfc` | 68 | `onNetworkError(MZ_NETWORK_ERROR, uint, uint, void*)` |
| **`0x515d40`** | 136 | **`onNetworkDataReceived(uchar*, uint, int, int, void*)`** |
| **`0x515dc8`** | 452 | **`parseConfigData(uchar*, uint)`** |
| **`0x515f8c`** | 604 | **`GetBundleConfig(OnlineProfileEligibilityListner*)`** |

**对象布局**（40 字节，`0xe6ddb0`）：`+0x00` vptr、`+0x08` `OnlineProfileEligibilityListner*`、`+0x10`/`+0x18`/`+0x20` = `std::vector<int>` 的 begin/end/cap_end。

### 1.2 消费方（UI / 服务层）

#### `tr::ProfileEligibilityManager`（实现 `OnlineProfileEligibilityListner`）

- vtable `_ZTVN2tr25ProfileEligibilityManagerE` @ **`0xdd9e70`**（24 字节 = 3 槽）：`[0]`=offset-to-top、`[1]`=typeinfo @ `0xdd9e90`、`[2]`= **`onReceivedBundleConfig(TR_ONLINE_ERROR)`**
- ⇒ **`tr::OnlineProfileEligibilityListner` 接口只有 1 个虚函数**（槽索引 0，相对 vptr）：`onReceivedBundleConfig(TR_ONLINE_ERROR)`
- 方法表：

| 地址 | 大小 | 符号 |
|---|---|---|
| `0x5955b0` | 32 | `C1`/`C2` |
| `0x5955d0` | 4 | `D1`/`D2` |
| `0x5955d4` | 12 | `init()` |
| `0x5955e0` | 8 | `uinit()` |
| **`0x5955e8`** | 76 | **`isBundleEligible(int)`** |
| **`0x595634`** | 20 | **`onReceivedBundleConfig(TR_ONLINE_ERROR)`** |
| **`0x595648`** | 36 | **`fetchConfig(FEATURE_TYPE)`** |

对象布局（24 字节，`0xe696e0`）：`+0x00` vptr、`+0x08`/`+0x10` 两个字段，其中 `+0x10` 是「已请求过」字节标志。

#### `tr::StoreManager`（配置响应里的商店限购表消费者）

- vtable `_ZTVN2tr12StoreManagerE` @ `0xdd9c60`（152 字节），typeinfo @ `0xdd9d00`
- 全局单例：`GOT 0xe220c8` → `_ZN2tr10GlobalData14m_storeManagerE`（`0xe674c8`，size 232）。`OnlineConfiguration::parseJsonResponse` 在 `0x4eebf0` 用 `[0xe22000+0xc8]` 取它
- 方法表：

| 地址 | 大小 | 符号 |
|---|---|---|
| `0x579470` | 152 | `reloadStoreConfig()` |
| `0x57accc` | 48 | `onProductsReceived` |
| `0x57b0cc` | 272 | `onNetworkDataReceived` |
| `0x57b1dc` | 276 | `parseResponse(int, char*)` |
| **`0x57b30c`** | 1272 | **`parseStoreConfiguration(json::json_value*)`** |
| `0x57b804` | 124 | `isServerStoreItem(char const*)` |
| **`0x57b880`** | 152 | **`hasReachedPurchaseLimit(char const*)`** |
| `0x57b918` | 592 | `getPuchaseAmountsStr` |

对象布局（232 字节）：`+0x00` vptr、`+0x08` 网络监听器子对象（`reloadStoreConfig` 传 `add x1,x19,#8` 作 listener）、`+0xd0`/`+0xd8` = `std::vector<tr::ServerStoreItemData>` 的 begin/end（**元素步长 0x20**，见 `0x57b458 add x21,x21,#0x20`、`0x57b8a0 lsr x9,x9,#5`）。

---

## 2. URL / 方法 / opcode 全表

`.rodata` 中 `/targeting/v1/` 的全部字面量（二进制 ASCII 扫描，7 个 op）：`0xb85793`、`0xb857b4`、`0xb88e9f`、`0xb89641`、`0xb8967f`、`0xb896ac`、`0xb896da`。

| # | URL（完整形态） | 方法 | cmd | 触发函数 | URL 格式串 VA |
|---|---|---|---|---|---|
| 1 | `{serverBase}/public/targeting/v1/configuration` | **POST** (`postJson`) | **0x49 = 73** | `OnlineConfiguration::getConfiguration` `0x4ee544` | `0xb8578d` `%s/%s/targeting/v1/configuration`；`public`=`0xb85227` |
| 2 | `{serverBase}/public/targeting/v1/configuration?pid=%d&random_group=%f&player_name=%s&game_version=%d&device=%s&total_play_time=%d&xp=%d&gender=x&uid=%s&platform=%s&language=%s` | **GET** (`getRequest`) | **0x49 = 73** | `OnlineConfiguration::getAnonymousConfiguration` `0x4ee808`（xref `0x4ee9a0`） | `0xb857ae` |
| 3 | `{serverBase}/public/targeting/v1/condition_items?type=bundles` | **GET** (`getRequest`) | **0x85 = 133** | `OnlineProfileEligibilityManager::GetBundleConfig` `0x515f8c` | `%s%s` @ `0xbb35c9` + 路径 `0xb88e97` |
| 4 | 由响应 `metadata.downloadurl` 指定的**任意绝对 URL** | **GET** (`getRequest`) | **0x4a = 74** | `OnlineConfiguration::onNetworkDataReceived` `0x4ef3c8`；`downloadConfiguration` `0x4ef4c8` | 无格式串，URL 直接取自 JSON |
| 5 | `{serverBase}/public/targeting/v1/vip_registration` | POST | 0x72 = 114 | `VIPLeaderboardBadgeService::registerMembership()` `0x51ab68` | `0xb89639` |
| 6 | `{serverBase}/private/targeting/v1/direct_vip_registration` | POST | 0x72 = 114 | 同上（反作弊关闭分支） | `0xb89676` |
| 7 | `{serverBase}/public/targeting/v1/vip_validation?profiles=` | GET | 0x73 = 115 | `sendMembershipQuery(...)` `0x51ad70` | `0xb896a4` |
| 8 | `{serverBase}/public/targeting/v1/vip_badge_option` | POST | 0x74 = 116 | `sendBadgeOption(bool)` `0x51afe8` | `0xb896d2` |
| 9 | `{serverBase}/public/targeting/v1/vip_badge_option` | GET | 0x74 = 116 | `getBadgeOption()` `0x51af50` | `0xb896d2` |

> #5–#9（VIP 徽章）已有独立报告 `tmp/vip_badge_service_spec.md`，本报告只做登记；注意它们的 cmd 0x72/0x73/0x74 **属于 `tr::VIPLeaderboardBadgeService` 自己的分发**，与 #1/#3 的 cmd 0x49/0x85 不冲突（监听器类不同）。

**与礼包/商店直接相关的「外挂」端点**（不属于 `targeting/v1`，但必须交叉引用）：

| URL | 方法 | cmd | 触发函数 | 格式串 VA |
|---|---|---|---|---|
| `{serverBase}/public/receiptvalidation/v1/product/configuration` | GET | **0x19 = 25** | `StoreManager::reloadStoreConfig()` `0x579470`（`0x5794cc mov w3,#0x19`） | `0xb8c7d8` |
| 同上 | — | 0x16 = 22 | `StoreManager::parseResponse` `0x57b1dc` 的 0x16 分支 | — |

`StoreManager::parseResponse(int cmd, char* body)` @ `0x57b1dc` 的 cmd 分发：

- `cmp w20,#0x16`（`0x57b248`）→ `0x57b268`：遍历 `root->first_child`，把每个成员的 key 与 `0xb8bef0`（`status`）比、value 与 `0xb85b68`（`Fail`）比，**两次比较结果均被丢弃**（`cbnz w0,0x57b29c` 后直接落到 `0x57b29c`），实测为死代码。
- `cmp w20,#0x19`（`0x57b250`）→ `0x57b258`：`StoreManager::parseStoreConfiguration(this, root)`。

⇒ **`parseStoreConfiguration` 既被 `receiptvalidation/v1/product/configuration`(cmd 0x19) 调用，也被 `targeting/v1/configuration`(cmd 0x49) 调用。** 也就是说 `limited_purchases` 表可以从任一端点投喂。

---

## 3. 请求体格式

### 3.1 `POST /public/targeting/v1/configuration`（cmd 0x49）

格式串 `0xb856b0`：

```
{ "silent_login":"%s", "game_version":"%d", "xp":%d, "total_play_time":%d, "device":"%s","uid":"%s","platform":"%s","language":"%s",
```

后续按条件拼接三段，最后把末尾的 `,` 就地改成 `}`：

| 追加串 | `.rodata` | 条件 |
|---|---|---|
| `"player_name":"%s",` | `0xb85735` | `[OnlinePlayer+0x10]` 首字节非 0 |
| `"gender":"female",` | `0xb85749` | `[OnlinePlayer+0x4814] == 2` |
| `"gender":"male",` | `0xb8575c` | 否则 |
| `"fb_name":"%s",` | `0xb8576d` | `[OnlineCore::m_authentication+0x18]` 非 0 **且** `OnlineData::getSilentLoginName()`（`OnlineCore+0x6be0`）首字节非 0 |

收尾：`0x4ee73c mov w9,#0x7d; 0x4ee748 sturb w9,[x8,#-1]`（`strlen(body)-1` 处写 `}`），再 `DebugOut::add("config json: %s", body)`（`0xb8577d`）。

**实参来源（`0x4ee590`..`0x4ee658`）**：

| 字段 | 来源指令 |
|---|---|
| `silent_login` | `0x4ee5d8 bl OnlineCore::isSilentLoginUser()` → `tst w0,#1` → `csel x23,x9,x8,ne`，x9=`"true"`@`0xbabd3b`，x8=`"false"`@`0xbabd71` |
| `game_version` | `0x4ee5c8 ldr x8,[0xe21620]` → `_ZN2tr7MainApp12m_versionIntE`；`0x4ee5d0 ldr w21,[x8]` |
| `xp` | `0x4ee5b4 add x0,x8,#0x90c; mov w1,#0x46; bl PlayerItems::getItemCount(int,int)`（x8=`GlobalData::m_player`） |
| `total_play_time` | `0x4ee64c mov w6,wzr` —— **硬编码 0** |
| `device` | `0x4ee630 add x7,x7,#0x850` → `"google"`@`0xb85850` |
| `uid` | `_getUUID()` → `strncpy(sp+0x28, ..., 0x80)` |
| `platform` | `0x4ee650 stp x28,x7,[sp]` → 与 `device` 同一个 `"google"` |
| `language` | `0x4ee620 bl Localizator::getSelectedLanguageCode()`，`0x4ee62c str x0,[sp,#0x10]` |
| `uid`/`platform` 是栈上传参 | `stp x28,x7,[sp]` |

与抓到的实际 body **完全一致**（`device` 与 `platform` 都恒为 `google`，`total_play_time` 恒为 0）。

### 3.2 `GET /public/targeting/v1/condition_items?type=bundles`（cmd 0x85）

**无 body**，**无客户端可变参数**——`type=bundles` 硬编码在路径字面量 `0xb88e97` 里，`snprintf(buf,0x400,"%s%s", [OnlineCore+0x28], path)`。客户端**永远不会**请求 `type=items`/`offers`/`products`。

---

## 4. 响应分发（cmd → handler）

### 4.1 `OnlineConfiguration::onNetworkDataReceived` @ `0x4ef3c8`

```asm
0x4ef3d8  cmp  w3, #0x4a          ; cmd 0x4a(74) = 配置包分片
0x4ef3e0  b.eq 0x4ef414
0x4ef3e4  cmp  w3, #0x49          ; cmd 0x49(73) = configuration 响应
0x4ef3e8  b.ne 0x4ef4b8           ; 其它 cmd 直接返回 1
0x4ef3f0  add  x0, x0, #0x8ce     ; 0xb858ce "CONFIGURATION QUERY: %s"
0x4ef3fc  bl   DebugOut::add
0x4ef40c  bl   OnlineConfiguration::parseJsonResponse(0x49, body)
```

- **cmd 0x49** → NUL 终止 body（`strb wzr,[x20,w2,uxtw]`）→ `parseJsonResponse(0x49, body)`
- **cmd 0x4a** → `writeConfiguration(body, len)`；随后若 `[this+0x60] > [this+0x64]` 就取 `[this+0x20+0x64*8]` 作为 URL，`0x4ef440 mov w3,#0x4a` 再发一次 GET，并把 `[this+0x64]++`
- 两条路径都会走到 `0x4ef46c`：若 `[this+0x68] >= 1` 则 `GlobalData::onDataPacksUpdated()`，按 `[this+0xf0]` 决定是否给 `[this+0x6c]` 打 `bit24`，然后 `str w8,[OnlinePlayer+0x4800]`、`str mt::String::getHashCode(this+0x70),[OnlinePlayer+0x4870]`
- 返回值恒为 `1`（`0x4ef4bc mov w0,#1`）

`OnlineConfiguration::onQueryCompleted(TR_ONLINE_ERROR, char const*)` @ `0x4ef334`：
```asm
0x4ef334  mov w1, #0x1c
0x4ef338  b   OnlineConfiguration::parseJsonResponse
```
⇒ cmd 0x1c 也会进 `parseJsonResponse`，但因为 `parseJsonResponse` 只认 0x49（`0x4eebe0 cmp w22,#0x49` / `0x4eebe4 b.ne 0x4ef0a4`），实际什么都不做。

`OnlineConfiguration::onNetworkError` @ `0x4ef348`：`DebugOut::add("CONGFIG REQUEST ERROR: %d", err)`（`0xb858b4`）；若 `err == 0x193` 且当前菜单状态非 `0x83`，则 `MenuzStateMachine::getState(0x83)` → `PopupStateBlacklist::setBlacklistReason(1)` → `setStateStatus(0)` → `push(0x83,2,0)`。**配置请求失败会弹黑名单提示。**

### 4.2 `OnlineProfileEligibilityManager::onNetworkDataReceived` @ `0x515d40`

```asm
0x515d58  cmp w3, #0x85 ; b.ne 0x515db4      ; 只认 cmd 0x85
0x515d64  adrp x1,#0xbb7000 ; add x1,x1,#0x80c  ; 0xbb780c = "null"
0x515d70  bl strcmp
0x515d74  cbz w0, 0x515d9c                   ; body 恰为 "null" → w1 = 7（错误码）
0x515d78  bl parseConfigData(data, len)
0x515d88  ldr x0,[x19,#8] ; cbz x0, 0x515db4 ; listener 为空 → 安全返回
0x515dac  ldr x8,[x8] ; blr x8               ; ★ listener vptr[0] = onReceivedBundleConfig(TR_ONLINE_ERROR)
```
成功路径 `w1 = 0`，`"null"` 路径 `w1 = 7`。返回值恒为 1。

---

## 5. `condition_items` 响应 schema

### 5.1 解析器 `OnlineProfileEligibilityManager::parseConfigData(uchar*, uint)` @ `0x515dc8`

```asm
0x515df8  bl   json::block_allocator::block_allocator(uint)   ; 1KB 栈上分配器
0x515e04  stp  xzr, xzr, [sp,#8]        ; root = NULL, end = NULL
0x515e08  str  wzr, [sp,#4]             ; error = 0
0x515e0c  strb wzr, [x20, w2, uxtw]     ; data[len] = 0   ← 就地 NUL 终止
0x515e28  bl   json::json_parse
0x515e2c  cbz  x0, 0x515f30             ; ★ 解析失败 → 清理退出
0x515e30  ldr  w8, [x0, #0x30]          ; root->type
0x515e34  cmp  w8, #2
0x515e38  b.ne 0x515f30                 ; ★ 根必须是 ARRAY(type==2)，否则安全退出
0x515e44  ldr  x23, [x0, #0x10]         ; root->first_child
0x515e48  cbz  x23, 0x515f30            ; ★ 空数组 → 安全退出
0x515e54  ldr  w8, [x23, #0x30]
0x515e58  cmp  w8, #4
0x515e5c  b.ne 0x515f28                 ; ★ 元素必须是整数(type==4)，否则跳过该元素
0x515e70  ldr  w9, [x23, #0x28]         ; 元素整数值
0x515e74  str  w9, [x8], #4             ; push_back 到 std::vector<int>
0x515f28  ldr  x23, [x23, #8]           ; 下一个兄弟
0x515f2c  cbnz x23, 0x515e54
0x515f30  bl   json::block_allocator::~block_allocator()
```

### 5.2 精确 schema

```json
[ 101, 102, 205 ]
```

- **根节点必须是 JSON 数组**（`json_value.type == 2`）；根是对象 / 标量 / `null` / 空数组 → 一律**安全退出，不崩溃**，等价于「无任何礼包可用」。
- 元素**必须是整数**（`type == 4`）；非整数元素被**静默跳过**（不报错、不崩溃）。
- 每个整数被 `push_back` 进 `OnlineProfileEligibilityManager+0x10` 的 `std::vector<int>`。

### 5.3 语义：这是「礼包 id 白名单」

消费点 `tr::ProfileEligibilityManager::isBundleEligible(int)` @ `0x5955e8`：

```asm
0x5955e8  adrp x9,#0xe20000 ; ldr x9,[x9,#0xdf0]   ; GlobalData::m_onlineProfileEligibilityManager
0x5955f0  ldp  x8, x9, [x9, #0x10]                  ; vector begin / end
0x5955f4  cmp  x9, x8 ; b.ne 0x595604
0x5955fc  mov  w0, wzr ; ret                        ; 空 → false
0x595608  ldr  w10,[x8],#4
0x59560c  cmp  w10, w1 ; b.eq 0x59562c
0x59562c  mov  w0,#1 ; ret                          ; 命中 → true
```

唯一调用者：`tr::StoreItem::unlockConditionsOK(bool)` @ `0x6094b8` 的 `0x609a20`：

```asm
0x609a0c  ldr  w21, [x26, #8]           ; 条件字段 B
0x609a10  cbz  w21, 0x609a3c
0x609a14  ldrb w1,  [x20, #0x208]       ; ★ bundle id（单字节，0..255）
0x609a18  adrp x0, #0xe21000 ; 0x609a1c ldr x0,[x0,#0x398]   ; GlobalData::m_profileEligibilityManager
0x609a20  bl   ProfileEligibilityManager::isBundleEligible(int)
0x609a24  cmp  w21, #1 ; cset w8,eq
0x609a2c  eor  w8, w8, w0
0x609a30  tbz  w8, #0, 0x609a38         ; 条件字段 B 与 isBundleEligible 结果一致 → 继续
0x609a34  tbz  w19, #0, 0x609544        ; 不一致 → 若传入 bool 的 bit0 为 0 → 判定不解锁
```

同一函数里 `configuration` 的 `pay_times` 也被消费（见 §6.3）：

```asm
0x6099d0  ldr  w8, [x26]                ; 条件字段 A
0x6099d4  cbz  w8, 0x609a0c
0x6099d8  adrp x9,#0xe20000 ; 0x6099dc ldr x9,[x9,#0x420]   ; GlobalData::m_player
0x6099e0  mov  w10, #0x6c68
0x6099e4  cmp  w8, #1 ; cset w8,eq
0x6099ec  ldr  x9, [x9] ; 0x6099f0 ldr w9,[x9,x10]          ; OnlinePlayer+0x6c68 = pay_times
0x6099f4  cmp  w9, #0 ; cset w9,ne
0x6099fc  eor  w8, w8, w9
0x609a00  cmp  w8, #1 ; b.ne 0x609a0c
0x609a08  tbz  w19, #0, 0x609544
```

---

## 6. `configuration` 响应 schema

### 6.1 分发入口 `OnlineConfiguration::parseJsonResponse(int cmd, char* body)` @ `0x4eeb50`

```asm
0x4eebb8  bl  json::block_allocator::block_allocator(0x400)
0x4eebd8  bl  json::json_parse
0x4eebdc  mov x23, x0
0x4eebe0  cmp w22, #0x49 ; b.ne 0x4ef0a4   ; 只认 cmd 0x49
0x4eebe8  cbz x23, 0x4ef0a4                ; root == NULL → 退出
0x4eebf0  ldr x0, [0xe22000+0xc8]          ; GlobalData::m_storeManager
0x4eebf8  bl  StoreManager::parseStoreConfiguration(root)     ; ★ 先交给 StoreManager
0x4eebfc  ldr x23, [x23, #0x10]            ; root->first_child
0x4eec00  cbz x23, 0x4eef3c                ; 空对象 → 走默认值路径
; ---- 遍历 root 的每个成员，按 key 分派 ----
```

**根节点类型未被检查**：`x23` 只判了 NULL。若根是数组，`root->first_child` 是数组元素（`+0x20` 的 key 为 NULL）→ 走到 `json_strcmp(NULL, "metadata")`。**因为 `json_strcmp` 对 NULL 有保护（见 §7.1），这不会崩**，但会退化成「所有 key 都不匹配」。

### 6.2 顶层 key 表

| key | `.rodata` | 期望 JSON 类型 | 驱动的客户端状态 | 取用指令 |
|---|---|---|---|---|
| `limited_purchases` | `0xb8c8e5` | **array of object** | 清空并填充 `StoreManager+0xd0` 的 `std::vector<tr::ServerStoreItemData>` | `0x57b688 add x1,x1,#0x8e5`；`0x57b464 str x19,[x23,#0xd8]`（clear）；`0x57b5b4 bl vector::_M_emplace_back_aux` |
| `metadata` | `0xb85860` | object | 见 §6.4 | `0x4eec2c cbz w0,0x4eed2c` |
| `update` | `0xb897b9` | int | `w24` = 最低要求客户端版本（**仅当 w24 仍为 0 时生效**） | `0x4eec40`；`0x4eee3c cbnz w24` / `0x4eee40 ldr w24,[x23,#0x28]` |
| `country` | `0xb8ae4e` | string | 取前 2 字节（`ldrh`）写入 `OnlinePlayer+0x6c70`（2 字母国家码打包） | `0x4eec54`；`0x4eee70 ldrh w8,[x27]` / `0x4eef24 str w8,[x9,#0x6c70]` |
| `pay_times` | `0xb85875` | int | 写入 `OnlinePlayer+0x6c68` —— **直接影响 StoreItem 解锁** | `0x4eec68`；`0x4eeec0 str w9,[x8,#0x6c68]` |
| `login` | `0xb8b854` | object | 见 §6.5（值类型非 object 则整段跳过：`0x4eec84 cmp w8,#1; b.ne 0x4eee78`） | `0x4eec7c cbnz w0,0x4eee78` |
| `update_platform` | `0xb8587f` | object | 子键 `google` (int) → `w24`（**覆盖 `update`**） | `0x4eee84 cbz w0,0x4eeed4` |
| `timestamp` | `0xbb48b9` | int | 写入 `OnlinePlayer+0x48f0`；置 `w25 = 1` | `0x4eee9c cbnz w0,0x4eef30`；`0x4eeeac mov w25,#1` / `0x4eeeb0 str w9,[x8,#0x48f0]` |

未列出的顶层 key 一律被忽略（`0x4eef30 ldr x23,[x23,#8]` 前进到下一个成员）。

**尾部（`0x4eef48`..`0x4ef0a4`）**：

```asm
0x4eef50  cmp  w21, #0x640      ; w21 = Device::getOSVersionInt()
0x4eef54  ldr  x9, [x28]        ; OnlinePlayer*
0x4eef58  cset w10, lt          ; w10 = (OSVersion < 1600)
0x4eef5c  ldr  w8, [x8]         ; MainApp::m_versionInt
0x4eef60  orn  w10, w10, w20    ; w20 = PlayerSettings::isSupportedArch()
0x4eef64  cmp  w8, w24
0x4eef68  cset w11, lt
0x4eef6c  tst  w10, w11
0x4eef70  mov  w10, #0x486c
0x4eef74  csinv w11, w24, wzr, eq
0x4eef78  str  w11, [x9, x10]   ; OnlinePlayer+0x486c = 版本门限结果
0x4eef7c  mov  w10, #0x6de4     ; ldrb/orr #1/strb → OnlinePlayer+0x6de4 |= 1
0x4eef8c  mov  w10, #0x64
0x4eef94  mul  w10, w8, w10     ; 客户端版本 × 100
0x4eef98  cmp  w24, w10
0x4eef9c  add  x10, x9, #0x48f0
0x4eefa0  b.lt 0x4eefb0
0x4eefa4  tbz  w25, #0, 0x4eefb0
0x4eefb0  mov  w9, wzr ; str wzr, [x10]   ; 清掉 timestamp
```

随后 `0x4eefc4`：`mt::String::getHashCode(this+0x70)`（配置包名 hash）与 `OnlinePlayer+0x4870` 比；`0x4eefe4 and w9,w9,#0xffffff` 取 `OnlinePlayer+0x4800` 的低 24 位与 `w27`（= `metadata.version`）比。**两者都相同 → 直接返回（跳过下载）；否则**：

```asm
0x4ef000  ldr  w1, [x19, #0x60]        ; URL 个数
0x4ef008  add  x0, x0, #0x88f          ; 0xb8588f "STARTING TO DOWNLOAD %d CONFIG FILES"
0x4ef00c  str  w27, [x19, #0x6c]       ; this+0x6c = 新版本号
0x4ef010  bl   DebugOut::add
0x4ef030  ldr  x2, [x8, #0x20]         ; 第 [this+0x64] 个 URL
0x4ef038  mov  w3, #0x4a
0x4ef040  mov  x1, x19
0x4ef04c  bl   OnlineCore::getRequest   ; GET cmd 0x4a
```

### 6.3 `limited_purchases` 元素 schema（`StoreManager::parseStoreConfiguration` @ `0x57b30c`）

外层循环只找 key == `limited_purchases` 的顶层成员（`0x57b688` / `0x57b690 cbz w0,0x57b39c`），其余顶层 key 在这层被忽略。

```asm
0x57b340  cbz  x1, 0x57b6a0        ; root == NULL → 返回
0x57b344  ldr  x9, [x1, #0x10]
0x57b348  cbz  x9, 0x57b6a0        ; root->first_child == NULL → 返回
...
0x57b464  str  x19, [x23, #0xd8]   ; ★ vector.clear()
0x57b468  ldr  x8,  [sp, #0x38]    ; 当前顶层成员
0x57b46c  ldr  x19, [x8, #0x10]    ; value 节点（= 数组第一个元素）
0x57b470  cbz  x19, 0x57b694       ; NULL 保护
0x57b474  ldr  x23, [x19, #0x10]   ; 元素对象 -> first_child
0x57b478  cbz  x23, 0x57b508       ; 空对象 → 全用默认值
; 遍历该元素的成员：
0x57b498  add  x1, x1, #0xf5e      ; 0xbb3f5e "name"          -> x21
0x57b4b0  add  x1, x1, #0xa7d      ; 0xbaaa7d "product_id"    -> x28
0x57b4c4  mov  x1, x24             ; 0xbb3a74 "limit"         -> w22
0x57b4d8  mov  x1, x25             ; 0xb8c8fc "counter"       -> w20
0x57b4ec  mov  x1, x27             ; 0xb8c8f7 "fake_counter"  -> w26
0x57b4fc  ldr  x23, [x23, #8] ; cbnz x23, 0x57b490
0x57b5b4  bl   vector<tr::ServerStoreItemData>::_M_emplace_back_aux   ; 推入一个元素
0x57b5e0  ldr  x19, [x19, #8] ; cbnz x19, 0x57b474                   ; 下一个数组元素
```

⇒ **`limited_purchases` 必须是「对象组成的数组」**。

`tr::ServerStoreItemData`（步长 **0x20**，由 `0x57b458 add x21,x21,#0x20` 与 `0x57b8a0 lsr x9,x9,#5` 确定）：

| 偏移 | 类型 | JSON key | `.rodata` | 写入指令 |
|---|---|---|---|---|
| `+0x00` | `mt::String`（8 字节） | `name` | `0xbb3f5e` | `0x57b538 add x0,sp,#0x50` + `0x57b540 bl 0xb15adc` |
| `+0x08` | `mt::String`（8 字节） | `product_id` | `0xbaaa7d` | `0x57b554 ldr x0,[sp,#0x40]`（= `sp+0x58`）+ `0x57b55c bl 0xb15adc` |
| `+0x10` | `int` | `limit` | `0xbb3a74` | `0x57b528 str w22,[sp,#0x60]` |
| `+0x14` | `int` | `counter` | `0xb8c8fc` | `0x57b560 stp w20,w26,[sp,#0x64]` |
| `+0x18` | `int` | `fake_counter` | `0xb8c8f7` | 同上（第二个） |

被谁消费：

- `StoreManager::hasReachedPurchaseLimit(char const* product_id)` @ `0x57b880`：线性查找 `product_id`（`ldr x1,[x8,#8]`），返回
  ```asm
  0x57b8f4  ldp  w9, w10, [x8, #0x14]    ; w9 = counter, w10 = fake_counter
  0x57b8f8  ldr  w8,  [x8, #0x10]        ; w8 = limit
  0x57b8fc  add  w9, w10, w9
  0x57b900  cmp  w9, w8
  0x57b904  cset w0, ge                  ; (counter+fake_counter) >= limit
  ```
- `StoreManager::isServerStoreItem(char const* product_id)` @ `0x57b804`：同样的线性查找，命中返回 1（`0x57b86c mov w0,#1`）。

### 6.4 `metadata` 子 schema

| 子 key | `.rodata` | 类型 | 去向 | 指令 |
|---|---|---|---|---|
| `downloadurl` | `0xb85869` | string | 用 `strtok(..., ",")`（分隔串 `,` @ `0xb8576b`）切分；每段 `operator new[](strlen+0x20)`（`0x4eedc8 bl _Znam`），存入 `[this+0x20 + [this+0x60]*8]`（`0x4eedd4 str x0,[x9,x8,lsl#3]`），再 `tr::__urlDecode`（`0x4eede4`），`[this+0x60]++`（`0x4eeda0`） | `0x4eed40 cbz w0,0x4eed7c` |
| `version` | `0xb4056d` | int | `w27` = 配置版本 | `0x4eed54 cbz w0,0x4eedec`；`0x4eedec ldr w27,[x22,#0x28]` |
| `name` | `0xbb3f5e` | string | `strncpy(this+0x70, value, 0x80)` | `0x4eed68 cbz w0,0x4eee20`；`0x4eee2c bl strncpy`（`mov w2,#0x80`） |

**`downloadurl` 是权限最大的一处**：它是逗号分隔的**任意绝对 URL** 列表，客户端会对每条发 `GET`（cmd 0x4a）并把响应体交给 `writeConfiguration` 落盘。`__urlDecode`（`0x4eea3c`，272 字节）还有一个可疑实现：它对 `%3?` 前缀做 `strtol(...,16)`（`0x4eeac4 cmp w9,#0x25` / `0x4eead4 cmp w9,#0x33` / `0x4eeafc bl strtol`），所以**不要**在 `downloadurl` / `name` 里放百分号，否则解码结果可能不是你以为的东西。

### 6.5 `login` 子 schema

| 子 key | `.rodata` | 类型 | 去向 | 指令 |
|---|---|---|---|---|
| `enabled` | `0xb8cb60` | int（`cmp w8,#1`，要求值 == 1） | 若 `OnlinePlayer+0x6c74 != 3` → 置 1 并 `OnlineCore::activateSilentLogin()` | `0x4eecb8 cbnz`；`0x4eecc0 cmp w8,#1`；`0x4eecdc mov w9,#1` / `0x4eece0 str w9,[x8]`；`0x4eecf0 bl OnlineCore::activateSilentLogin` |
| `access` | `0xb3eb64` | int | `[[OnlineCore::m_authentication]+0x28] + 0x10 = value` | `0x4eed08 cbnz`；`0x4eed0c ldr x8,[0xe1f910]`；`0x4eed18 ldr x8,[x8,#0x28]`；`0x4eed1c str w9,[x8,#0x10]` |

### 6.6 完整响应样例

```json
{
  "limited_purchases": [
    { "name": "promo_1", "product_id": "com.ubisoft.trialsfrontier.bundle1",
      "limit": 1, "counter": 0, "fake_counter": 0 }
  ],
  "pay_times": 1,
  "country": "CN",
  "update": 794,
  "update_platform": { "google": 794 },
  "timestamp": 1700000000,
  "login": { "enabled": 0, "access": 0 },
  "metadata": {
    "version": 1,
    "name": "config_1",
    "downloadurl": "https://example.invalid/none.bin"
  }
}
```

（`pay_times` / `update` / `country` / `timestamp` / `login` / `update_platform` 全部可省；`metadata` 也可省。可省性依据：§6.2 每个分支都在 key 不匹配时直接跳到下一个成员，且所有字段在「从未被赋值」时走 `0x4eef3c` 的默认值路径。）

---

## 7. 崩溃风险审计

> **总结论：本端点族的两个解析器都做了 NULL 检查和类型检查，且底层库对 NULL 有保护。未发现任何「缺 key / 类型错 ⇒ 无条件解引用」的模式。** 与项目此前 `reward_config` 的 `ldr x8,[x22+8]; ldr x25,[x8+0x10]`（无保护）**不同**。

### 7.1 底层保护（关键前提）

**`tr::json_strcmp(char const*, char const*)` @ `0x569138`（全文 20 字节）——对 NULL 完全安全**：

```asm
0x569138  cbz x0, 0x569144      ; a == NULL → 返回 -1
0x56913c  cbz x1, 0x569144      ; b == NULL → 返回 -1
0x569140  b   strcmp
0x569144  mov w0, #-1
0x569148  ret
```

⇒ **所有 `json_strcmp(node->key, "literal")` 都不会因为 key 为 NULL 而崩溃。**（`json_value+0x20` 在数组元素、或任何未设置 key 的节点上就是 NULL。）

**`json::json_parse(char*, char**, json_value**, int*, block_allocator*)` @ `0x88aa94`（3264 字节）在任何失败路径都返回 NULL**：

```asm
0x88b3ec  ldr  x8, [sp, #0x10]
0x88b3f4  str  x21, [x8]              ; *end = 出错位置
0x88b400  add  x8, x8, #0x76f          ; 0xba776f "Mismatch closing brace/bracket"
0x88b404  str  x8, [x10]               ; *error = 错误串
0x88b418  str  w8, [x10]               ; *error_code
...
0x88b724  mov  x0, xzr
0x88b730  mov  x0, xzr                 ; 返回 NULL
0x88b750  ret
```

`json_value` 结构（大小 **0x38**，`0x38` 在 `bl block_allocator::malloc` 前用 `mov w1,#0x38` 传入）：

| 偏移 | 含义 |
|---|---|
| `+0x00` | parent |
| `+0x08` | next（兄弟） |
| `+0x10` | first_child |
| `+0x18` | last_child |
| `+0x20` | key（成员名，`char*`；**数组元素 / 未命名节点为 NULL**） |
| `+0x28` | value（int32 / bool / double / `char*` 共用） |
| `+0x30` | type |

`type` 枚举（全部由指令确定）：`0`=NULL、`1`=OBJECT（`0x88ac78 cmp w8,#0x7b` + `cinc`）、`2`=ARRAY、`3`=STRING（`0x88b148 mov w8,#3`）、`4`=整数（`0x88ab1c mov w8,#4`）、`5`=带指数浮点（`0x88ab78 cmp w9,#0x65`）、`6`=BOOL（`0x88ad60`/`0x88ad30`）。

### 7.2 逐个 key 的读取保护性质

| 端点 | key / 访问 | 保护性质 | 证据 |
|---|---|---|---|
| `condition_items` | 根节点 | **安全跳过**（根 type != 2 就退出） | `0x515e30` `ldr w8,[x0,#0x30]` → `0x515e34 cmp w8,#2` → `0x515e38 b.ne 0x515f30` |
| `condition_items` | 元素 | **安全跳过**（type != 4 跳过该元素，继续下一个兄弟） | `0x515e54` → `0x515e58 cmp w8,#4` → `0x515e5c b.ne 0x515f28` |
| `condition_items` | 空数组 | **安全跳过** | `0x515e44 ldr x23,[x0,#0x10]` → `0x515e48 cbz x23,0x515f30` |
| `condition_items` | `json_parse` 失败 | **安全跳过** | `0x515e2c cbz x0,0x515f30` |
| `condition_items` | body == `"null"` | **安全跳过**，listener 收到错误码 7 | `0x515d64`/`0x515d70` strcmp；`0x515da8 mov w1,#7` |
| `condition_items` | listener 指针 | **安全跳过** | `0x515d88 ldr x0,[x19,#8]` → `0x515d8c cbz x0,0x515db4` |
| `configuration` | 根节点 | **安全跳过** | `0x4eebe8 cbz x23,0x4ef0a4` |
| `configuration` | 根的所有成员 key | **安全**（`json_strcmp` NULL 保护） | `0x4eec28` 等全部走 `0x569138` |
| `configuration` | 空对象 | **安全跳过**（走默认值路径） | `0x4eec00 cbz x23,0x4eef3c` → `0x4eef3c mov w24,wzr; mov w25,wzr; mov w27,#-1` |
| `configuration` | `metadata` 的 value | **安全跳过** | `0x4eed2c ldr x22,[x23,#0x10]` → `0x4eed30 cbz x22,0x4eef08` |
| `configuration` | `metadata.*` 的子 key | **安全**（`json_strcmp` NULL 保护） | `0x4eed40`/`0x4eed54`/`0x4eed68` |
| `configuration` | `login` 的 value | **安全跳过** | `0x4eeca0 ldr x22,[x23,#0x10]` → `0x4eeca4 cbz x22,0x4eef08` |
| `configuration` | `login` 值类型必须是 OBJECT | **有类型检查** | `0x4eec80 ldr w8,[x23,#0x30]` → `0x4eec84 cmp w8,#1` → `0x4eec88 b.ne 0x4eee78` |
| `configuration` | `update_platform` 的 value | **安全跳过** | `0x4eeed4 ldr x22,[x23,#0x10]` → `0x4eeed8 cbz x22,0x4eef08` |
| `configuration` | `country` 值类型 | **有类型检查**（非 STRING 或长度 < 2 → 写 0） | `0x4eee48 ldr w8,[x23,#0x30]` → `0x4eee4c cmp w8,#3` → `0x4eee50 b.ne 0x4eeecc`；`0x4eee64 bl strnlen` → `0x4eee68 cmp x0,#2` → `0x4eee6c b.lo 0x4eef14` |
| `configuration` | `limited_purchases`：`root` / `root->first_child` | **安全跳过** | `0x57b340 cbz x1`；`0x57b348 cbz x9` |
| `configuration` | `limited_purchases` 的 value / 空对象 | **安全跳过** | `0x57b470 cbz x19,0x57b694`；`0x57b478 cbz x23,0x57b508` |
| `configuration` | `limited_purchases[i]` 的成员 key | **安全**（`json_strcmp` NULL 保护） | `0x57b49c` 等走 `0x569138` |
| `configuration` | `metadata.version` 与 `timestamp` / `pay_times` / `limit` 等整数字段 | **无类型检查，但不会崩**：直接把 `node->value`（`+0x28`）按 `int`/`w` 读出。若发字符串，读到的是**指针低 32 位**（脏数据，非崩溃） | `0x4eeeb0 str w9,[x8,x10]`；`0x4eedec ldr w27,[x22,#0x28]` |

### 7.3 唯一被「无条件」解引用的地方（已确认安全）

```asm
; OnlineConfiguration::parseJsonResponse
0x4eebfc  ldr x23, [x23, #0x10]     ; root->first_child，无 first_child NULL 检查
0x4eec20  ldr x0,  [x23, #0x20]     ; member->key，无类型检查
```
`0x4eebfc` 之前 x23 已在 `0x4eebe8` 判过非 NULL，**所以 `+0x10` 解引用是安全的**；`0x4eec20` 读出的可能是 NULL，但 `json_strcmp` 会拦住。

**唯一真实的崩溃面**：`OnlinePlayer` / `OnlineCore::m_authentication` 是长寿命全局对象，`configuration` 会往里写 `+0x486c`、`+0x48f0`、`+0x6c68`、`+0x6c70`、`+0x6c74`、`+0x6de4`、`+0x4800`、`+0x4870`，以及 `[[m_authentication]+0x28]+0x10`（`0x4eed1c`，**未判 `[m_authentication+0x28]` 是否为 NULL**）。这些偏移取决于客户端版本自身的结构体布局，**不随服务器 JSON 变化**；只要服务器发的是格式合法的 JSON，就不会崩。

**不是崩溃但会「毁号」的一处**：`downloadurl` 会让客户端写盘（`mt::file::SaveFile::writeSystemFile`，`0x4ef250`）。若服务器返回拒绝服务的地址或垃圾内容，可能污染本地配置缓存并触发 `GlobalData::onDataPacksUpdated()` 重载。**建议服务器永远省略 `metadata`，或让 `metadata` 里不含 `downloadurl`。**

---

## 8. 服务器应该回什么（最小响应）

### 8.1 `GET /public/targeting/v1/condition_items?type=bundles`（cmd 0x85）

**最小安全响应（什么都不解锁）**：

```
[]
```

`Content-Type` 建议 `application/json`。**不要**返回 `{}`（根不是数组 → 直接退出，效果相同但不合语义）、`null`、空 body、或 `"null"` 字面量（后者会让 listener 收到错误码 7）。

**要让礼包可见**：返回 bundle id 数组。bundle id 的取值域由 `0x609a14 ldrb w1,[x20,#0x208]`（**单字节**）确定为 **0..255**，所以：

```
[0,1,2,...,255]
```

即可让**所有**「条件字段 B == 1」的 StoreItem 通过 `isBundleEligible` 检查。实际生效的 id 集合定义在客户端资源里（不在 `.so`），无法从二进制枚举 —— 见 §9。

### 8.2 `POST /public/targeting/v1/configuration`（cmd 0x49）

**绝对最小安全响应**：

```
{}
```

效果：`StoreManager::parseStoreConfiguration` 立即返回；`root->first_child == NULL` → 走 `0x4eef3c` 默认值路径（`w24=0, w25=0, w27=-1`）；`w27 == -1` → `0x4eefd0 cmn w27,#1; b.eq 0x4ef0a4` **跳过整个配置包下载**，也不会调 `onDataPacksUpdated()`。只会在 `OnlinePlayer` 上写几个版本门限字段。

**让礼包/商店正常工作的推荐响应**（数组顺序不敏感，除 `update` 必须在 `update_platform` 之前，若两者都要给）：

```json
{
  "pay_times": 1,
  "country": "CN",
  "update": 794,
  "update_platform": { "google": 794 },
  "timestamp": 1700000000,
  "login": { "enabled": 0, "access": 0 },
  "limited_purchases": []
}
```

要点：
- `pay_times` 必须存在且为整数，才能让「条件字段 A == 1」的 StoreItem 通过 `0x6099f4 cmp w9,#0`；若想让「条件字段 A == 0」的 StoreItem 通过则填 `0`。这就是原抓包里 `"xp":12` 之外唯一影响商店可见性的 targeting 字段。
- `update` / `update_platform.google` 应 **≤ 客户端 `MainApp::m_versionInt`**（7.9.4 实测为 794）。填大于客户端的值会走 `0x4eef74 csinv` 分支写出版本门限值。
- `timestamp` 可省；省掉后 `w25 = 0`，`0x4eefa4 tbz w25,#0` 会清掉 `OnlinePlayer+0x48f0`。**所以要想让时间戳持久化，必须带 `timestamp`。**
- **`limited_purchases`**：想让某商品受「限购 N 次」约束就按 §6.3 给；不想约束就省略或给 `[]`。**注意 `parseStoreConfiguration` 每次见到 `limited_purchases` 都会先 `vector.clear()`**，所以不要指望靠重复顶层 key 追加。
- **`metadata` 强烈建议整段省略**（会触发写盘 + `downloadurl` 下载，见 §7.3）。

### 8.3 其它 targeting op

| op | 建议响应 |
|---|---|
| `GET .../configuration?pid=...&random_group=...`（匿名配置，cmd 0x49） | 与 §8.2 相同（共用 handler） |
| `POST /public/targeting/v1/vip_registration`（cmd 0x72） | `{}` —— 该 cmd 不被 `VIPLeaderboardBadgeService::onNetworkDataReceived` 接受，内容无人解析 |
| `POST /private/targeting/v1/direct_vip_registration`（cmd 0x72） | 同上 |
| `GET /public/targeting/v1/vip_validation?profiles=`（cmd 0x73） | 必须回 `{"player":..., "badge_display":...}`，细节见 `tmp/vip_badge_service_spec.md` |
| `POST|GET /public/targeting/v1/vip_badge_option`（cmd 0x74） | `{}`（该 cmd 不被处理） |

---

## 9. 未确定事项

1. **礼包 id 的实际取值**。`ldrb w1,[x20,#0x208]` 证明 bundle id 是单字节（0..255），但**具体哪个 id 对应哪个礼包**由客户端资源（`StoreItem` 定义，来自 `metadata`/数据包而非 `.so`）决定。我在 `.so` 里**找不到**任何 `bundleId → StoreItem` 的静态映射表（`StoreManager+0xd0` 里只有 `product_id` 字符串，不是 bundle id）。**结论：无法从 `libTrialsGo.so` 枚举，必须从游戏数据包或运行时 dump 得到。** 应急做法是回 `[0..255]` 全量。
2. **`StoreItem::unlockConditionsOK` 的完整条件结构未解析**。`x26` 指向的条件结构（`+0x00` 字段 A 与 `+0x08` 字段 B）来自 `0x609a38 ldr x26,[x24,#0x10]`，其持有者 `x24` 的来历我没有回溯（函数长度 > 2400 字节，超出本次侦察预算）。因此**「字段 A / 字段 B 各是什么语义（pay_times 门槛 / bundle 门槛）已经确定，但它们各自对应哪种礼包类别未确定」**。
3. **`OnlineConfiguration+0x68` 的精确写入点**。`writeConfiguration` @ `0x4ef1d8` 里同时出现 `ldr w8,[x19,#0x68]`（`0x4ef29c`）与 `str w8,[x19,#0x68]`（`0x4ef2a4`），中间的分支逻辑我只做了指令过滤（`Select-String`），**没有逐条确认它是「成功 +1」还是「写入字节数累加」**。这不影响服务器侧（我们不打算用 `metadata`）。
4. **`OnlinePlayer+0x486c` 的语义**。`0x4eef6c tst w10,w11` + `0x4eef74 csinv w11,w24,wzr,eq` 的组合我按字面记录（`w10 = (OSVersion<1600) | ~isSupportedArch()`，`w11 = (m_versionInt < w24)`）。由于 `~w20` 让 `w10` 恒为非零，`tst` 实际退化为「客户端版本 < 服务器要求版本」。**该字段的下游读者我没有找到**（按 `mov wN,#0x486c` 模式未定位到读取点），因此不能断言它到底门控什么 UI。
5. **`OnlineConfigurationListener` 接口槽布局无法给出**。7.9.4 里该类型**没有 vtable、没有 typeinfo**，且 `getConfiguration` 存进 `+0x10` 的指针在整个 `OnlineConfiguration` 类中**从未被调用**。我只能确认「这个监听器在当前版本是死参数」。若上游需要「UI 消费者类名」，能确认的只有 `GlobalData::onDataPacksUpdated()`（`0x35edb0`）与 `GlobalData::m_storeManager`；`GlobalData` 里具体哪个 UI 组件响应 `onDataPacksUpdated` 未回溯。
6. **`StoreManager::parseResponse` 的 cmd 0x16 分支是死代码**。两次 `json_strcmp` 的结果都被丢弃（对比 `status`/`Fail`）。我无法确定这是编译器消除了一个 `DebugOut`，还是源码本来就漏了赋值 —— **猜测成分，不作为结论**。
7. **`type=` 的其它取值**。客户端只硬编码 `bundles`。`/public/targeting/v1/condition_items?type=items` 这类请求**在二进制中不存在**，所以「还有哪些合法 type」这个问题在本客户端**无意义**（服务器可以接受，但客户端不会发）。
8. **VIP 五个 op 的细节**（cmd、`checksum`、响应 schema）我不重复逆向，直接指向已有的 `tmp/vip_badge_service_spec.md`；本报告只登记 URL/cmd/触发函数。
9. **`tr::__urlDecode` @ `0x4eea3c` 的 `%3?` 处理看起来是 bug**（`0x4eead4 cmp w9,#0x33`，只对 `%3` 前缀走 `strtol(...,16)`）。我没有找调用者来确认影响面，**因此只作为「使用时避免百分号」的运维建议，不作为逆向结论**。

---

## 10. 关键反汇编证据

### 10.1 `OnlineConfiguration::getConfiguration` 尾部（POST cmd 0x49）

```asm
0x4ee634  add  x2, x2, #0x6b0          ; 0xb856b0 主体格式串
0x4ee63c  mov  w1, #0x400              ; buf = sp+0xa8
0x4ee640  mov  x3, x23                 ; silent_login ("true"/"false")
0x4ee644  mov  w4, w21                 ; game_version = MainApp::m_versionInt
0x4ee648  mov  w5, w22                 ; xp = PlayerItems::getItemCount(m_player+0x90c, 0x46, 0)
0x4ee64c  mov  w6, wzr                 ; total_play_time = 0
0x4ee650  stp  x28, x7, [sp]           ; uid(sp+0x28), "google"
0x4ee658  bl   snprintf
0x4ee748  sturb w9, [x8, #-1]          ; 末尾 ',' → '}'  (w9 = 0x7d)
0x4ee74c  bl   DebugOut::add("config json: %s")
0x4ee75c  add  x2, x2, #0x78d          ; 0xb8578d "%s/%s/targeting/v1/configuration"
0x4ee760  add  x3, x8, #0x28           ; [OnlineCore+0x28] 服务器基址
0x4ee764  add  x4, x4, #0x227          ; 0xb85227 "public"
0x4ee768  bl   snprintf                ; buf = sp+0x4a8, size 0x200
0x4ee77c  add  x3, sp, #0xa8           ; body
0x4ee780  mov  w4, #0x49               ; ★ cmd = 73
0x4ee784  mov  w5, #1                  ; needAuth = true
0x4ee788  mov  x1, x19                 ; listener = this
0x4ee790  bl   OnlineCore::postJson
0x4ee794  strb w21, [x19, #0xf0]       ; 请求挂起标志 = 1
```

### 10.2 `OnlineProfileEligibilityManager::GetBundleConfig`（GET cmd 0x85）

```asm
0x515ff0  ldr  x20, [x20, #0xbb8]      ; GlobalData::m_onlineCoreE
0x515ffc  add  x2, x2, #0x5c9          ; 0xbb35c9 "%s%s"
0x516000  ldr  x8, [x20]               ; OnlineCore*
0x516004  add  x4, x4, #0xe97          ; 0xb88e97 "/public/targeting/v1/condition_items?type=bundles"
0x516010  add  x3, x8, #0x28           ; [OnlineCore+0x28]
0x516014  bl   snprintf                ; buf = sp+0x18, size 0x400
0x516020  mov  w3, #0x85               ; ★ cmd = 133
0x516024  mov  w5, #1                  ; needAuth = true
0x516028  mov  x1, x19                 ; listener = this
0x516034  bl   OnlineCore::getRequest
```

### 10.3 链路：菜单 → 拉取 → 解析 → 解锁 → 弹窗

```asm
; tr::MenuzStateMain::onBecomeTopmostState() @ 0x76cfb8
0x76d128  bl   ProfileEligibilityManager::fetchConfig(FEATURE_TYPE)

; ProfileEligibilityManager::fetchConfig @ 0x595648
0x59564c  cbnz w1, 0x595658                 ; w1 != 0 → 直接返回（只处理 FEATURE_TYPE 0）
0x595650  ldrb w9, [x8, #0x10]
0x595654  cbz  w9, 0x59565c                 ; 已请求过 → 返回
0x595660  ldr  x0, [0xe20df0]               ; GlobalData::m_onlineProfileEligibilityManager（对象本体）
0x595664  mov  x1, x8                       ; listener = this
0x595668  b    OnlineProfileEligibilityManager::GetBundleConfig

; ProfileEligibilityManager::onReceivedBundleConfig @ 0x595634
0x595634  cbz  w1, 0x59563c
0x595638  ret                              ; err != 0 → 什么都不做
0x59563c  mov  w8, #1
0x595640  strb w8, [x0, #0x10]              ; 置「已拉取」标志

; 弹窗出口（UserTracker::openBundleOfferPopup 的调用者）
0x5ff750  <- OfferManager::pushPopup(bool, StoreItem*, IAPItemInfo*, int) @ 0x5ff608
0x5fff88  <- OfferManager::checkDoubleOfferPopup(bool, StoreItem*, IAPItemInfo*, int) @ 0x5ffd9c
0x600ce0  <- OfferManager::checkRetentionOfferPopup(bool, StoreItem*, IAPItemInfo*, int) @ 0x600c24
```

### 10.4 全局单例 GOT 表（本次用到）

| GOT 槽 | 符号 | 地址/大小 |
|---|---|---|
| `0xe20420` | `_ZN2tr10GlobalData8m_playerE` | `0xe59b30` / 8 |
| `0xe20bb8` | `_ZN2tr10GlobalData12m_onlineCoreE` | `0xe674c0` / 8 |
| `0xe220c8` | `_ZN2tr10GlobalData14m_storeManagerE` | `0xe674c8` / 232 |
| `0xe21398` | `_ZN2tr10GlobalData27m_profileEligibilityManagerE` | `0xe696e0` / 24 |
| `0xe20df0` | `_ZN2tr10OnlineCore33m_onlineProfileEligibilityManagerE` | `0xe6ddb0` / 40 |
| `0xe1f910` | `_ZN2tr10OnlineCore16m_authenticationE` | `0xe69b00` / 64 |
| `0xe21620` | `_ZN2tr7MainApp12m_versionIntE` | `0xeb1c08` / 4 |
| `0xe1d9c0` | `_ZN2tr11json_strcmpEPKcS1_`（PLT） | `0x569138` / 20 |

### 10.5 本次使用的临时工具

| 工具 | 用途 |
|---|---|
| `tmp/_tgtxref.py <so> <0xva>...` | 健壮 ADRP(+ADD/LDR) xref 扫描（处理 ADRP 与 ADD 不相邻的情况） |
| `tmp/_vtreloc.py <so> <0xvt> <n>` | **解析 `.data.rel.ro` 中的 vtable 必须用它**：原始文件字节全为 0，真实指针在 `.rela.dyn` 的 r_offset/r_addend 里 |
| `tmp/_gotres.py <so> <0xgot>...` | 解析某 GOT 槽的重定位（`type=1025` = R_AARCH64_ABS64 直接给符号；`1027` = RELATIVE 需用 addend 就近符号） |
| `tmp/_str.py <so> <0xaddr>...` | 打印从该地址到第一个 NUL 的精确 C 字符串（**必需**：链接器合并了字符串后缀，很多 key 是别的字面量的尾部，例如 `country` = `user_country` 的尾部、`enabled` = `AntiCheating is enabled` 的尾部） |
| `tmp/disasm.py <so> <0xaddr> <len_bytes> [--bl-only]` | 反汇编。**第 3 个参数是字节长度，不是结束地址** |
