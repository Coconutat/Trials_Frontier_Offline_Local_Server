# Trials Frontier `friends` 端点族逆向报告

对象：`libTrialsGo.so`（7.9.4 Android / IL2CPP，AArch64，14901128 B，`tmp/libcmp/orig-libTrialsGo.so`）
方法：`.rodata` 字符串池 + `.rela.dyn` 重定位解析（vtable 槽名）+ capstone 逐指令反汇编（`tmp/disasm.py` / `syms.py` / `callers.py` / `fx.py`）+ 跳转表按 `.rodata` 内 int32 相对偏移数值求解。

**地址约定（重要，与旧笔记不同）**：`.text`(0x3661b0)、`.rodata`(0xb3b840) 的 VA == 文件偏移；
但从 `.init_array` 起（VA 0xdb9dc8 / off 0xda9dc8）全部 **VA − 0x10000 = 文件偏移**：
`.data.rel.ro` VA 0xdba140 / off 0xdaa140、`.got` VA 0xe08eb0 / off 0xdf8eb0、`.data` VA 0xe23000 / off 0xe13000、
`.bss` VA 0xe457a0 / off 0xe357a0。本报告所有 `.data.rel.ro` 地址均已按此换算。

---

## 0. 结论速览

| # | 结论 |
|---|---|
| 1 | 端点族有两个所有者：**`tr::OnlineUbiservices`** 发出 `GET /v2/profiles/me/friends`（网络层，`mz::NetworkDataListener` + `OnlineUbiservicesListener` 双接口），**`tr::OnlineFriends`** 发出 `POST .../friends/v1/update`（它内嵌了一个 `OnlineUbiservices` 子对象在 `+0x50`）。消费方/UI 是 **`tr::PopupStateGiftBox`**（War Room 送礼页）。 |
| 2 | 共 **3** 个网络 op：GET `%s/v2/profiles/me/friends`（**cmd 0x50**，只读好友列表）、POST `%s/%s/friends/v1/update`（**cmd 0x65**，上报本地好友 id 清单）、GET `%s/v1/profiles?idOnPlatform=`（**cmd 0x4b**，把 FB 好友 id 解析成 profile）。 |
| 3 | **cmd 0x50 的响应根必须是「非空 JSON 对象」，且第一个成员的值必须是数组，数组元素必须是对象，`pid` 必须排在 `nameOnPlatform` 之前，三个值都必须是字符串。** 违反任意一条 → `ldr x8,[x1,#0x10]` / `ldr x28,[x8,#0x10]` 解引用 **NULL+0x10** → SIGSEGV。 |
| 4 | 端点 1 的 host 是**硬编码** `https://public-ubiservices.ubi.com`（0xb85565），不走 `[OnlineCore+0x28]`。私服只能靠 DNS/hosts 劫持或证书代理命中 `GET /v2/profiles/me/friends`。端点 2 的 base 才是 `[OnlineCore+0x28]`。 |
| 5 | **cmd 0x65（friends/v1/update）的响应解析对非法 JSON 和 `{}` 都有 `cbz` 保护**，是唯一「怎么回都不会崩」的 friends 端点；但它的副作用很关键：本地 `[p+0xac]&2` 的好友若其 pid **没有**出现在响应 `uplay` 数组里，会被 `str wzr,[x9,#0xac]` **清零并删除**。 |
| 6 | `server/rules.json:98-121` 的 `"GET /v2/profiles/me/friends"` stub **形状是正确的**（`pid` 在 `nameOnPlatform` 之前、全字符串、`state:"Friend"` 不会触发 pending 计数）。UI 里的假名 `GhostRider` / `TangoPro` 就来自这里，问题只是**ID/名字硬编码**，不是形状。 |
| 7 | `OnlineFriendInfo` 结构大小 **0xdc**（220 B），显示名 `+0x00`(0x81)，查找键(pid) `+0x81`(≈0x2b，**`strcpy` 无界 → pid ≥ 43 B 会堆溢出**)，标志 `+0xac`，fb id `+0xb4`(0x28)。 |

---

## 1. 类归属

### 1.1 `tr::OnlineUbiservices` —— 端点 1 的发出者

- vtable `_ZTVN2tr17OnlineUbiservicesE` @ `.data.rel.ro` **0xdd9200**，vptr（object vptr）= **0xdd9210**（跳过 2 个 rtti 头槽）。
- 引擎通过 **`[listener + 0x20]`** 虚槽调 `onNetworkDataReceived`；在 0xdd9210 基础上就是 0xdd9230 → `OnlineUbiservices::onNetworkDataReceived` @0x517fec。

| 函数 | 地址 | 大小 |
|---|---|---|
| `getFriendList(OnlineUbiservicesListener*, char const* sessionId, char const* authHeader)` | `0x51776c` | 380 |
| `getPlayerProfilesById(OnlineUbiservicesListener*, UBI_PLATFORM, int, char const**)` | `0x517274` | 468 |
| `onNetworkDataReceived(unsigned char*, unsigned, int, int, void*)` | `0x517fec` | 356 |
| `parseJsonResponse(int cmd, char* data, int len, OnlineUbiservicesListener*)` | `0x518150` | 1448 |
| `parseProfilesJson(json_value*, ProfileQueryData*, int)` | `0x5187f4` | 176 |
| `parseProfileJson(json_value*, OnlineUbiservicesProfile&)` | `0x5188a4` | 444 |

### 1.2 `tr::OnlineFriends` —— 端点 2 的发出者 + 端点 1 的消费方

typeinfo `_ZTIN2tr13OnlineFriendsE` @0xdd9590；`_ZTSN2tr13OnlineFriendsE` @0xb89930；vtable 头 `_ZTVN2tr13OnlineFriendsE` @ `.data.rel.ro` **0xdd9390**（272 B）。

构造 `_ZN2tr13OnlineFriendsC2Ev` @0x51bb14 里的布局（逐指令）：

```
0x51bb3c adrp x8,#0xe21000 ; ldr x8,[x8,#0x310]   ; x8 = GOT[0xe21310] = &_ZTVN2tr13OnlineFriendsE = 0xdd9390
0x51bb48 str  q0,[this]                            ; q0 = {0xdd93a0, 0xdd9428}
0x51bb4c str  x9,[x19,#0x10]!                      ; x9 = 0xdd9390+0xe8 = 0xdd9478
0x51bb58 adrp x9,#0xe22000 ; ldr x9,[x9,#0x8d0]   ; x9 = GOT[0xe228d0] = &_ZTVN2tr17OnlineUbiservicesE = 0xdd9200
0x51bb64 str  x8,[x21,#0x50]!                      ; x8 = 0xdd9200+0x10 = 0xdd9210
```

→ **三个 vptr + 一个内嵌子对象**：

| 偏移 | 内容 | vptr |
|---|---|---|
| `+0x00` | `OnlineFriends` 主对象（`OnlineFacebookClientListener` + `OnlineFriendsListener` 接口） | **0xdd93a0** |
| `+0x08` | `OnlineUbiservicesListener` 次基类子对象 | **0xdd9428** |
| `+0x10` | `mz::NetworkDataListener` 次基类子对象 | **0xdd9478** |
| `+0x50` | 内嵌 `OnlineUbiservices` 子对象 | **0xdd9210** |
| `+0x58` | `ProfileQueryData`（内嵌） | — |

#### 主 vtable（vptr 0xdd93a0，槽名由 `.rela.dyn` 的 R_AARCH64_RELATIVE 逐槽解析）

| 槽 | 目标 |
|---|---|
| `+0x00` | `OnlineFriends::onFacebookFriendQueryCompleted` @0x51d6c0 |
| `+0x08` | `OnlineFriends::onFacebookFriendPictureReceived` @0x51d74c |
| `+0x10` | `OnlineFacebookClientListener::onFacebookLikeQueryCompleted` @0x502ba0 |
| `+0x18` | `OnlineFacebookClientListener::onFacebookLikeCompleted` @0x502ba4 |
| `+0x20` | `OnlineFacebookClientListener::onFacebookShareCompleted` @0x502ba8 |
| `+0x28` | `OnlineFacebookClientListener::onFacebookFriendsInvited` @0x502bac |
| `+0x30` | `OnlineFacebookClientListener::onFacebookAuthenticationComplete` @0x502bb0 |
| `+0x38` | **`OnlineFriends::onUPlayFriendQueryCompleted(TR_ONLINE_ERROR, int)`** @0x51d660 |
| `+0x40` | `OnlineFriends::onProfilesQueryCompleted(TR_ONLINE_ERROR, ProfileQueryData*)` @0x51d4bc |
| `+0x48` | `OnlineFriends::onPictureReceived` @0x51d658 |
| `+0x50` | `OnlineFriends::onNetworkError` @0x51d75c |
| `+0x58` | `OnlineFriends::onNetworkDataReceived` @0x51d784 |
| `+0x60` | `OnlineFriends::onFriendlistRecieved(json_value*)` @0x51cee8 |
| `+0x68` | `OnlineFriends::D2Ev` @0x51e1a8 |
| `+0x70` | `OnlineFriends::D0Ev` @0x51e220 |

#### `OnlineUbiservicesListener` 次 vtable（vptr 0xdd9428，8 槽）

| 槽 | 目标 |
|---|---|
| `+0x00` | `_ZThn8_OnlineFriends::onProfilesQueryCompleted` @0x51d650 |
| `+0x08` | `OnlineUbiservicesListener::onConfigurationQueryCompleted` @0x4064e4（4 B 桩） |
| `+0x10` | `_ZThn8_OnlineFriends::onPictureReceived` @0x51d65c |
| `+0x18` | `OnlineUbiservicesListener::onUserDataReceived` @0x4064ec（4 B 桩） |
| `+0x20` | `OnlineUbiservicesListener::onProfileLinkCreated` @0x4ec6b0（4 B 桩） |
| `+0x28` | `OnlineUbiservicesListener::onAuthenticationTicketRenewed` @0x4f89e0 |
| `+0x30` | `OnlineUbiservicesListener::onUserNameValidated` @0x4064f0（4 B 桩） |
| **`+0x38`** | **`_ZThn8_OnlineFriends::onFriendlistRecieved(json_value*)` @0x51d0a8** |

基类桩 `_ZN2tr25OnlineUbiservicesListener20onFriendlistRecievedEPN4json10json_valueE` @0x4064f4（4 B 纯 `ret`）。

#### `mz::NetworkDataListener` 次 vtable（vptr 0xdd9478）

| 槽 | 目标 |
|---|---|
| `+0x00` | `_ZThn16_OnlineFriends::D1Ev` @0x51e2a0 |
| `+0x08` | `_ZThn16_OnlineFriends::D0Ev` @0x51e314 |
| `+0x10` | `_ZThn16_OnlineFriends::onNetworkError` @0x51d770 |
| `+0x18` | `mz::NetworkDataListener::onNetworkServerTimeUpdated` @0x4eb384 |
| **`+0x20`** | **`_ZThn16_OnlineFriends::onNetworkDataReceived` @0x51ddd4** |
| `+0x28` | （无重定位 → 0） |

#### `OnlineFriends` 方法表

| 函数 | 地址 | 大小 |
|---|---|---|
| `init()` | 0x51bbe4 | — |
| `getPendingFriendRequestNum()` | 0x51bda8 | — |
| `resetGameFriends()` | 0x51bdb0 | — |
| `uninit()` | 0x51be14 | — |
| `addFriend(char const* key)` | `0x51bed4` | 444 |
| `addFacebookFriend(ExternalProfileInfo*)` | 0x51c110 | 456 |
| `getFriend(char const*)` | `0x51c090` | 128 |
| `getFriendByName` | 0x51c3fc | — |
| `getFriendByExternalId` | 0x51c340 | — |
| `getFriendIndex(OnlineFriendInfo&)` | 0x51c470 | — |
| `getFriendsByOnlineIdHash` | 0x51bbe8 | — |
| `getFacebookFriend` | 0x51c2d8 | — |
| `getMyPicture` / `getPicture` | 0x51c4d8 / 0x51c98c | — |
| `loadCache()` / `saveCache()` | `0x51cbfc` / `0x51db08` | 748 / 716 |
| `updateFriendList(OnlineFriendsListener*)` | `0x51cb38` | 196 |
| `syncFriendList()` | `0x51d0ac` | 728 |
| `resolveOnlineIds()` | `0x51d384` | 256 |
| `finishFriendQueries()` | 0x51d484 | 56 |
| `onFriendlistRecieved(json_value*)` | `0x51cee8` | 448 |
| `onProfilesQueryCompleted(TR_ONLINE_ERROR, ProfileQueryData*)` | `0x51d4bc` | 404 |
| `onUPlayFriendQueryCompleted(TR_ONLINE_ERROR, int)` | `0x51d660` | 96 |
| `onFacebookFriendQueryCompleted(TR_ONLINE_ERROR)` | 0x51d6c0 | 140 |
| `onNetworkDataReceived(unsigned char*, unsigned, int, int, void*)` | `0x51d784` | 900 |
| `onNetworkError(MZ_NETWORK_ERROR, unsigned, unsigned, void*)` | 0x51d75c | 20 |
| `printList()` / `getCacheFileName()` | 0x51ddf0 / 0x51dfa0 | — |
| `refreshProfileImage` / `refreshOldestFriendImage` | 0x51de70 / 0x51dfd4 | — |

`tr::OnlineFriendsListener`（接口）在 `.dynsym` 与 `.rodata` 中**没有** `_ZTVN` / `_ZTSN` 符号，只出现在 `updateFriendList(OnlineFriendsListener*)` / `getPicture` / `getMyPicture` 的 mangled 名里。

### 1.3 消费方（送礼 / War Room UI）

| 符号 | 地址 | 大小 | 作用 |
|---|---|---|---|
| `tr::PopupStateGiftBox::getFriendsSortedByHallOfFameRank` | `0x7f3e94` | 816 | 读 `OnlineFriends+0x30`(数) / `+0x38`(数组)，**`ldr w9,[x8,#0xac]; cbz w9` 跳过标志为 0 的条目** |
| `tr::PopupStateGiftBox::createFriendEntryToSendGiftArea(OnlineFriendInfo const&, float)` | `0x7f41c4` | 1612 | 渲染单个好友条目 |

`OnlineFriends::getFriend(char const*)` @0x51c090 的调用点（选摘）：0x4ee2b0/0x4ee2e4（`OnlineAuthenticationUPlay::onFriendRemoved`）、0x4fd78c/0x4fd844（`OnlinePVPMatchQuery::resolveOpponentNames`）、0x4fea20（`OnlinePVP::parseFriendLeaderboard`）、0x50ac5c/0x50ad2c（`OnlineLeaderboards::resolveFriendNames`）、0x50b6c8（`OnlineLeaderboards::parseJsonResponse`）、0x51f6b4/0x51fe5c（`OnlineGifting::parseJsonResponse` / `parseGiftData`）、0x520344（`OnlineUserPictures::getUserPicture`）、0x597e14、0x77db54、0x7d4fa0、0x81379c。

### 1.4 全局单例（`.rela.dyn` type 257 解析）

| GOT 槽 | 指向 |
|---|---|
| 0xe21310 | `_ZTVN2tr13OnlineFriendsE` @0xdd9390 |
| 0xe228d0 | `_ZTVN2tr17OnlineUbiservicesE` @0xdd9200 |
| 0xe1f060 | `_ZN2tr10OnlineCore9m_friendsE` @**0xe69b60**（静态对象地址本身 = `OnlineFriends` 单例） |
| 0xe1fe80 | `_ZN2tr10OnlineCore13m_ubiservicesE` @0xe6b538 |
| 0xe22958 | `_ZN2tr10OnlineCore16m_facebookClientE` @0xe6cf90 |
| 0xe20bb8 | `_ZN2tr10GlobalData12m_onlineCoreE` @0xe674c0（`ldr x,[x,#0xbb8]` 取出，再 `ldr x0,[x8]` 得 `OnlineCore*`） |
| 0xe20420 | `_ZN2tr10GlobalData8m_playerE` @0xe59b30 |
| 0xe1f910 | `_ZN2tr10OnlineCore16m_authenticationE` @0xe69b00 |
| 0xe21f38 | `_ZN2tr19OnlineDataContainer17m_facebookProfileE` @0xe7cee0（内联 char 数组，**首字节 0 = 未登录 FB**） |

---

## 2. URL / 方法 / opcode 全表

| # | 方法 | URL 模板（.rodata） | opcode | 发出函数 | 目标主机 |
|---|---|---|---|---|---|
| 1 | **GET** | `%s/v2/profiles/me/friends` @**0xb89151**，`%s` = `https://public-ubiservices.ubi.com` @**0xb85565** | **0x50** | `OnlineUbiservices::getFriendList` @0x51776c | Ubisoft 官方（硬编码） |
| 2 | **POST** | `%s/%s/friends/v1/update` @**0xb897a8**，`%s`#1 = `[OnlineCore+0x28]`，`%s`#2 = `public` @**0xb85227** | **0x65** | `OnlineFriends::syncFriendList` @0x51d0ac | 私服 |
| 3 | GET | `%s/v1/profiles?idOnPlatform=` @**0xb89109** / `%s/v1/profiles?profileId=` @**0xb89064**，`%s` = 0xb85565 | **0x4b** | `OnlineUbiservices::getPlayerProfilesById` @0x517274 | Ubisoft 官方（硬编码） |
| — | GET | `%s/me/friends?fields=installed,first_name,last_name&access_token=%s` @0xb887ed | — | Facebook Graph（非本服务器） | graph.facebook.com |

### 2.1 端点 1 —— `OnlineUbiservices::getFriendList(listener, sessionId, authHeader)` @0x51776c (380)

调用方唯一：`OnlineFriends::updateFriendList` 里 `0x51cbe8`。

```
0x5177bc  add  x1, sp, #8
0x5177c4  mov  w2, #0x200 ; x25 = 0xb85565 (base)
0x5177cc  adrp x2, #0xb89000 ; add x2, x2, #0x151   ; x2 = 0xb89151 "%s/v2/profiles/me/friends"
0x5177d0  adrp x3, #0xb85000 ; add x3, x3, #0x565   ; x3 = 0xb85565
0x5177d8  bl   snprintf                       ; snprintf(sp+8, 0x200, "%s/v2/profiles/me/friends", "https://public-ubiservices.ubi.com")
0x5177ec  adrp x8, #0xe20000 ; ldr x8,[x8,#0xbb8]  ; &GlobalData::m_onlineCore
0x5177f0  ldr  x8, [x8, #0xbb8]                    ; GlobalData::m_onlineCore 内偏移 0xbb8 → OnlineCore*
0x5177f4  add  x2, sp, #8                          ; url
0x5177fc  mov  w3, #0x50                           ; ★ cmd = 0x50
0x517800  ldr  x0, [x8]                            ; x0 = OnlineCore*
0x517804  mov  w5, #1
0x517808  movk w6, #3, lsl #16                     ; w6 = 0x34bc0
0x51780c  mov  x1, x23                            ; ★ x23 = this（OnlineUbiservices 自身），不是用户 listener
0x517810  mov  w4, wzr
0x517814  bl   OnlineCore::getRequest
0x51781c  adrp x1, #0xb85000 ; add x1, x1, #0x594  ; "Ubi-AppId"
0x517824  adrp x26, #0xb85000 ; add x26, x26, #0x3a6 ; "1c91448e-c62e-45ec-b97b-898dc967f2c1"
0x517834  adrp x1, #0xb89000 ; add x1, x1, #0x16b  ; "Ubi-SessionId"
0x517838  mov  x2, x20                             ; x20 = authHeader
0x5178a8  str  x19, [x23, #0x470]                  ; ★ 把用户 listener 存进 NetworkRequest+0x470（回包时作为 ctx 传回）
```
**GET，无请求体。** Header：`Ubi-AppId: 1c91448e-c62e-45ec-b97b-898dc967f2c1`、`Ubi-SessionId: <authHeader>`。

### 2.2 端点 2 —— `OnlineFriends::syncFriendList()` @0x51d0ac (728)

```
0x51d0d8  add  x22, x19, #0x19b6
0x51d0e4  ldrb w8, [x22]                 ; [this+0x19b6]
0x51d0e8  cbz  w8, #0x51d128
0x51d0ec  mov  w8, #1 ; strb w8,[x22] ; ... return 0    ; 已在同步中 → 直接返回
0x51d128  ldrb w8, [x19, #0x19b7]
0x51d12c  cbz  w8, #0x51d0ec             ; [this+0x19b7]==0（未认证）→ 置位并返回，不发请求
0x51d144  bl   OnlineCore::checkGameServerConnection(0x80, false)
0x51d150  ldr  w8,[x19,#0x18] ; ldr w9,[x19,#0x30]     ; fb 数 + uplay 数
0x51d15c  add  w8, w8, w9 ; add w8, w8, #1 ; lsl #8 ; add #0x100
0x51d170  bl   operator new[](size)                    ; body 缓冲区
0x51d1a8  ... 两次 8 字节重叠 store → 写入 0xb8979b  '{',' ','"','u','p','l','a','y','"',':',' ','[',0
0x51d1b0  snprintf(sp+0x48, 0x200, 0xb897a8 "%s/%s/friends/v1/update",
                   x3 = [OnlineCore+0x28], x4 = 0xb85227 "public")
```
**uplay 循环**（`w24` = 已写入数量，`w26` = 索引，`w27` = `','`，`w28` = `'"'`）：
```
0x51d1d4  ldr  x23, [x19, #0x38]                 ; OnlineFriendInfo* 数组
0x51d1d8  ldr  x9,  [x23, x25, lsl #3]
0x51d1dc  ldrb w10, [x9, #0xac]
0x51d1e0  tbz  w10, #1, #0x51d234                ; 只上报 bit1(2) 置位的好友
0x51d1e4  ldrb w9,  [x9, #0x81]
0x51d1e8  cbz  w9,  #0x51d234                    ; 且查找键非空
0x51d1f0  cmp  w26, #1 ; b.lt #0x51d208
0x51d1f8  strh w27, [buf+strlen(buf)]            ; 逗号（第一项除外）
0x51d208  strh w28, [buf+strlen(buf)]            ; 开引号
0x51d214  strcat(buf, [x9+0x81])                 ; ★ 写入 pid
0x51d224  strh w28, [buf+strlen(buf)]            ; 闭引号
```
**facebook 循环**（元素本身即 `char*`）：
```
0x51d250  ... 写入 0xb897c0  ']',',','"','f','a','c','e','b','o','o','k','"',':','[',0
0x51d290  ldrb w9, [x9, #0xa8] ; tbz w9,#0 → skip ; 只上报 bit0 置位的 FB 条目
0x51d2c0  strcat(buf, [x23, x25, lsl #3])        ; 写入 FB 好友 id
```
**结尾**：
```
0x51d2e8  adrp x8, #0xe21000 ; ldr x8,[x8,#0xf38]  ; &OnlineDataContainer::m_facebookProfile (0xe7cee0)
0x51d2f0  ldrb w8, [x8]
0x51d2f4  cbz  w8, #0x51d318
0x51d2f8  snprintf(sp+8, 0x40, 0xb897cf "],\"fbid\":\"%s\"}", x3 = *[0xe21f38])
0x51d318  strncpy(sp+8, 0xb87f63 "]}", 0x40)
0x51d334  strcat(buf, sp+8)
0x51d338  cmp  w24, #1 ; b.lt #0x51d368           ; 一个 id 都没有 → 不发请求
0x51d348  add  x1, x19, #0x10                     ; ★ listener = OnlineFriends+0x10（mz::NetworkDataListener 子对象）
0x51d34c  add  x2, sp, #0x48                      ; url
0x51d350  mov  w4, #0x65                          ; ★ cmd = 0x65
0x51d354  ldr  x0, [x8]                           ; OnlineCore*
0x51d358  mov  w5, #1
0x51d35c  mov  x3, x20                            ; body
0x51d360  bl   OnlineCore::postJson
0x51d368  mov  w8, #1 ; strb w8,[x22]             ; 置 [this+0x19b6]=1
0x51d370  bl   operator delete[](buf) ; return 0
```
最终 body 为 `{ "uplay": ["id1","id2"],"facebook":["fb1"]` + （`],"fbid":"<x>"}` 或 `]}`）。
**uplay 数组元素是字符串；facebook 数组元素也是字符串（FB 好友 id 指针本身）。**

### 2.3 端点 3 —— `OnlineUbiservices::getPlayerProfilesById` @0x517274 (468)

```
0x5172a0  cmp  w2, #2 ; csel x8, x8, xzr, eq     ; x8 预置 = 0xb890d4 "uplay"
0x5172ac  add  x9, x9, #0x106                    ; x9 = 0xb89106 "fb"
0x5172b4  cmp  w2, #1 ; csel x22, x9, x8, eq     ; platform 1 → "fb"；2 → "uplay"；其它 → NULL
0x5172cc  csel w19, w3, w8(=0x14), lt            ; 最多 20 个 id
0x5172e0  cbz  x22, #0x5172f0
0x5172e8  x2 = 0xb89109 "%s/v1/profiles?idOnPlatform="
0x5172f0  x2 = 0xb89064 "%s/v1/profiles?profileId="
0x5172f8  x3 = 0xb85565 base ; bl snprintf(sp+0x58, 0x400, x2, x3)
0x51731c  ldr  x23, [x21, x26, lsl #3]           ; ids[i]
0x517344  cmp  x26, #1 ; b.lt                    ; 首项不加分隔符
0x517354  strh w19(=0x2c ','), [x28, x0]         ; 其余用 ',' 分隔
0x517360  strcat(buf, ids[i])
0x517374  sprintf(sp+0x18, 0xb89126 "&platformType=%s", x22) ; strcat
0x5173c8  ldr  x0, [GOT 0xe1f910 = 0xe69b00] ; bl OnlineAuthentication::isAuthenticated()
0x5173d0  and  w5, w0, #1                        ; ★ 认证结果直接当 getRequest 的 w5
0x5173d8  mov  w3, #0x4b                         ; ★ cmd = 0x4b
0x5173dc  bl   OnlineCore::getRequest
```
最终 URL：`<base>/v1/profiles?idOnPlatform=<id1>,<id2>&platformType=fb`（无 platform 时用 `profileId=`、无 `platformType=`）。
调用点：0x4fd8c4（`OnlinePVPMatchQuery::resolveOpponentNames`）、0x4fef28（`OnlinePVP::parseLegendsLeaderboard`）、0x51a060（`TreasureHuntLeaderboard::resolveLeaderBoardNames`）、**0x51d418（`OnlineFriends::resolveOnlineIds`）**。

---

## 3. 请求体语义

`POST /public/friends/v1/update` 的 body 是一个**「客户端本地好友 id 上报清单」**：

```json
{ "uplay": ["<pid1>","<pid2>"], "facebook": ["<fbid1>"], "fbid": "<自己的FB id>" }
```

- `uplay` 数组：**客户端自己已经记住的好友 pid**（`OnlineFriendInfo+0x81`），只包含 `[+0xac]&2`（来自 `/v2/profiles/me/friends`）且键非空的条目。**这既不是「要查询」，也不是「要添加」——它是客户端声明「我本地有这些好友」。** 服务器语义上应当把它当作查询键，并把仍在好友关系里的 id **原样回显**（回显后 `0x51d850 cbz w0` 命中 → `[x9+0xac]` 保持不动 → 收尾 `tbnz #3` 通过 → 好友保留）。未回显的 id → `0x51d864 str wzr,[x9,#0xac]` → `[+0xac]=0` → 收尾循环（`0x51da30 tbnz w12,#3`）判定为删除 → 好友从列表消失。
- `facebook` 数组：客户端本地 FB 好友条目（`[+0xa8]&1`）的 id **字符串**。`resolveOnlineIds` 会把这些 id 拿去 `GET /v1/profiles?idOnPlatform=<ids>&platformType=fb` 换成 profile，再用 `idOnPlatform` 与响应里的 `idOnPlatform` 做 `strcmp` 匹配（`onProfilesQueryCompleted` `0x51d538`）。
- `fbid`：自己的 FB 登录 id，未登录时整个键省略（走 `0x51d318 strncpy(sp+8, "]}", 0x40)`）。**私服可以忽略它。**
- 请求体**没有 checksum**（与 `gift/v1` 不同）。

**opcode 0x65 的响应客户端只做三件事**：① 用 `uplay` 数组回显比对、② 用 `facebook` 对象数组补全 FB 好友、③ 压缩 `[this+0x38]` 并 `saveCache()`。响应内容**不会**产生任何新的好友（除了 facebook 分支），也**不会**写显示名到既有 uplay 好友（`stp` 只在 facebook 分支里写 `+0x00`）。

---

## 4. 请求 → 响应 分发链（`cmd` → handler）

| cmd | 发出 | 引擎回调的 listener 子对象与槽 | 最终 handler |
|---|---|---|---|
| **0x50** | `getFriendList` 里 `x1 = x23 = this`（`OnlineUbiservices` 对象，vptr **0xdd9210**） | `[vptr+0x20]` = 0xdd9230 → `OnlineUbiservices::onNetworkDataReceived` @0x517fec | `parseJsonResponse(0x50, data, len, listener)`（`listener` = 请求里 `+0x470` 存的 `OnlineFriends+8`）→ cmd 0x50 分支 0x5182a8 → `listener->vptr[+0x38]` → **`_ZThn8_OnlineFriends::onFriendlistRecieved`** @0x51d0a8 → `OnlineFriends::onFriendlistRecieved` @0x51cee8 |
| **0x65** | `syncFriendList` 里 `x1 = this+0x10`（`mz::NetworkDataListener` 子对象，vptr **0xdd9478**） | `[vptr+0x20]` = 0xdd9498 → `_ZThn16_OnlineFriends::onNetworkDataReceived` @0x51ddd4 | **`OnlineFriends::onNetworkDataReceived`** @0x51d784（只认 `cmp w3,#0x65`） |
| **0x4b** | `getPlayerProfilesById` 里 `x1 = listener`（`OnlineFriends+8`，来自 `resolveOnlineIds` 的 `x1=this+8`） | 同 0x50 路径 → `parseJsonResponse` cmd 0x4b 分支 0x518264 | `listener->vptr[+0x00]` → **`_ZThn8_OnlineFriends::onProfilesQueryCompleted`** @0x51d650 → `OnlineFriends::onProfilesQueryCompleted` @0x51d4bc |

`OnlineCore::onNetworkDataReceived` @0x56c04c (104 B) **只是 DebugOut 日志**（cmd 4 / cmd 2 / 其它三支，`mov w0,#1; ret`），**不做任何分发**。真正的分发在 `OnlineUbiservices::onNetworkDataReceived`（cmd 0x50 与 0x4b 命中同一跳转表），以及 mz 引擎直接按 `[listener+0x20]` 虚调。

### 4.1 跳转表数值求解（`.rodata` 内相对 int32）

`OnlineUbiservices::onNetworkDataReceived` @0x517fec：`sub w8,w3,#0x4b; cmp w8,#0xd; b.hi`，表 @**0xb88fd0**（14 项）：

| cmd | 目标 |
|---|---|
| 0x4b / 0x4d / 0x4e / 0x51 / 0x55 / 0x56 / 0x57 / 0x58 | 0x518034（补 NUL 后 `parseJsonResponse(原 cmd, …)`） |
| 0x4c | 0x518138（无操作） |
| 0x4f | 0x518074 |
| **0x50** | **0x5180e8**（补 NUL + `mov w1,#0x50` → 0x518040） |
| 0x52 / 0x53 | 0x518054 |
| 0x54 | 0x518108 |

`OnlineUbiservices::parseJsonResponse(cmd=w23, data=x2, len=w3, listener=x19)` @0x518150 (1448)。`0x5181bc bl json_parse` → `0x5181c0 mov x21,x0`；跳转表 @**0xb89008**：

| cmd | 目标 |
|---|---|
| 0x4b | 0x518264（profiles 数组解析，**有 NULL 保护**） |
| 0x4c / 0x52 / 0x53 / 0x54 | 0x518674（清理/返回） |
| 0x4d / 0x4e | 0x5181e4 |
| 0x4f | 0x518288 |
| **0x50** | **0x5182a8（无 NULL 保护）** |
| 0x51 | 0x5182c0 |
| 0x55 | 0x51830c |
| 0x56 | 0x518404 |
| 0x57 | 0x51844c |
| 0x58 | 0x518454 |

---

## 5. 响应 JSON schema

json_value 内存布局（本 binary 多处实测一致）：

| 偏移 | 含义 |
|---|---|
| `+0x08` | next sibling |
| `+0x10` | first child |
| `+0x20` | key 字符串指针 |
| `+0x28` | value（字符串指针 / 整数，**与类型无关地共用同一槽位**） |
| `+0x30` | type tag（`0` = 非字符串/null，`1` = 字符串，`2` = 数组，`3` = 对象） |

### 5.1 cmd 0x50 —— `GET /v2/profiles/me/friends` → `OnlineFriends::onFriendlistRecieved(root)` @0x51cee8

```
0x51cf18  ldr  x8,  [x1, #0x10]     ; x8 = root->child              ← 无 NULL 检查
0x51cf1c  ldr  x28, [x8, #0x10]     ; x28 = x8->child               ← 无 NULL 检查
0x51cf20  cbz  x28, #0x51d050       ; 空 → 安全
0x51cf44  x20 = 0xb85ac1 "state" ; x21 = 0xb89785 "PendingReceivedInvite"
0x51cf4c  x22 = 0xb87ce7 "pid"   ; x23 = 0xb85478 "nameOnPlatform" ; x24 = 0xb9096b "0"
```
结构：**对象 → 第一个成员的值为数组 → 元素为对象 → 对象成员（顺序敏感）**。

| 层级 | 要求 | 地址证据 |
|---|---|---|
| root | 必须是 **JSON 对象**（非空） | 0x51cf18 `ldr x8,[x1,#0x10]` |
| root 的第一个成员 | 键名**任意**（只有 `[root+0x10]` 被使用，其余兄弟被忽略） | 循环 A 起点 0x51cf1c |
| 该成员的值 | 必须是 **JSON 数组**（`[+0x10]` 取首个元素） | 0x51cf1c |
| 数组元素 | 必须是 **JSON 对象**（`[+0x10]` 取首个成员） | 0x51cf68 `ldr x26,[x28,#0x10]` |

成员键表（在**每个数组元素对象**内）：

| 键（.rodata 地址） | 值类型 | 写入的目标 | 指令 |
|---|---|---|---|
| `state` @**0xb85ac1** | string | 不入结构体；仅当值 == `PendingReceivedInvite` @**0xb89785** 时 `w19++` | 0x51d008 `json_strcmp([x26,#0x28], 0xb89785)`；0x51d018 `cinc w19,w19,eq` |
| `pid` @**0xb87ce7** | string | **512 B 栈缓冲 `sp+0x18`**（作为 `nameOnPlatform` 分支的 `addFriend` 查找键） | 0x51d020 `ldr x27,[x26,#0x28]`；0x51d028 `bl strlen`；0x51d038 `strncpy(sp+0x18, x27, len)` |
| `nameOnPlatform` @**0xb85478** | string | `OnlineFriendInfo+0x00`（char[0x81] 显示名）+ 标志 `+0xac \|= 2` | 0x51cfb8 `addFriend(sp+0x18)`；0x51cfd4 `strncpy(x27+0x00, [x26,#0x28], 0x81)`；0x51cfec `[x27+0xac] \|= 2` |

其他：哨兵串 `"0"` @**0xb9096b**（`pid` 初值/复位值，`strcmp(buf,"0")==0` 时跳过并复位）；DebugOut `ADDED UPLAY FRIEND  %s / %s` @**0xb8561f**。

**顺序依赖（最容易踩的坑）**：`pid` 必须在 `nameOnPlatform` **之前**。`nameOnPlatform` 分支用 `sp+0x18` 里的内容当 `addFriend` 的键；若 `pid` 尚未写入，`sp+0x18` 仍是 `"0"` → `strcmp(buf,"0")==0` → **整条记录被静默跳过**。反过来 `pid` 已写入但缺 `nameOnPlatform` → 记录不会被创建。

结尾：`0x51d054 x0 = *[GOT 0xe1f060] = 0xe69b60`（`OnlineCore::m_friends` 单例）→ `0x51d05c ldr x8,[x0]; ldr x8,[x8,#0x38]; x1=0; x2=w19; blr x8` → **`OnlineFriends::onUPlayFriendQueryCompleted(0, pendingInviteCount)`** @0x51d660 → 置 `[+0x19b5]=1`、`[+0x19b0]=w2` → 若 `[+0x19b4]!=0` 则尾调用 **`syncFriendList()`**（即收到好友列表后立刻发 `friends/v1/update`）。

### 5.2 cmd 0x65 —— `POST .../friends/v1/update` → `OnlineFriends::onNetworkDataReceived` @0x51d784

```
0x51d7b4  cmp  w3, #0x65 ; b.ne #0x51daa0   ; 只处理 0x65
0x51d7d0  strb wzr, [x20, w2, uxtw]         ; 补 NUL
0x51d7ec  bl   json::json_parse
0x51d7f0  cbz  x0, #0x51da0c                ; ★ 解析失败 → 安全
0x51d7f4  ldr  x23, [x0, #0x10]             ; x23 = root->child
0x51d7f8  cbz  x23, #0x51da0c               ; ★ {} → 安全
0x51d808  x22 = 0xb890d4 "uplay" ; x25 = 0xb8982f "facebook" ; x24 = 0xb89838 "fbid"
```

顶层成员扫描（`0x51d9e4` 起，`ldr x23,[x23,#8]` 沿兄弟链）：

| 顶层键（.rodata） | 值类型 | 语义 |
|---|---|---|
| `uplay` @**0xb890d4** | **数组 of 字符串** | 存活的好友 pid 清单 |
| `facebook` @**0xb8982f** | **数组 of 对象** | FB 好友，元素含 `uplay` @0xb890d4 / `fbid` @**0xb89838** 两个字符串键 |

uplay 分支（0x51d818）逐指令：

```
0x51d818  ldr  w8, [this, #0x30] ; cmp w8,#1 ; b.lt #0x51d9f4
0x51d82c  ldr  x9, [x23(=[this+0x38]), x8, lsl #3]   ; 本地第 i 个好友
0x51d830  ldrb w10, [x9, #0xac] ; tbz w10,#1 → 跳过  ; 只检查 bit1 的条目
0x51d838  ldr  x21, [x23, #0x10]                     ; 响应 uplay 数组首元素
0x51d83c  cbz  x21, #0x51d864                        ; 空数组 → 清零
0x51d844  json_strcmp([x21,#0x28], x9+0x81)
0x51d850  cbz  w0, #0x51d868                         ; 匹配 → 保留
0x51d854  ldr  x21, [x21, #0x8] ; cbnz → 0x51d840    ; 下一个元素
0x51d864  str  wzr, [x9, #0xac]                      ; ★ 一个都没匹配 → 标志清零（好友将被删除）
```

facebook 分支（0x51d87c）逐指令：

```
0x51d8e8  ldr  x8,[this+0x20] ; ldr x25,[x8, x9, lsl #3]  ; FB 条目（char*）
0x51d8ec  ldr  x21,[x23,#0x10]
0x51d8f8  cbz  x21, #0x51d964
0x51d8fc  ldr  x20,[x21,#0x10]        ; 元素必须是对象
0x51d900  cbz  x20, #0x51d944         ; 非对象 → x26=x27=0
0x51d90c  成员键与 x24 "fbid" 比 → 0x51d934 x27 = [x20,#0x28]
0x51d91c  成员键与 x22 "uplay" 比 → 0x51d92c x26 = [x20,#0x28]
0x51d94c  json_strcmp(x25, x27)       ; 本地 fb id == 响应 fbid
0x51d898  x26 = OnlineFriends::addFriend(x26)          ; 键 = 响应里的 uplay 值
0x51d8b0  strncpy(x26+0x00, x25+0x28, 0x80)            ; 显示名
0x51d8c0  strncpy(x26+0xb4, x25, 0x27)                 ; fb id
0x51d8c8  strh #2, [x25, #0xaa]
0x51d8e0  [x26+0xac] |= 4                              ; 标记为 facebook 来源
0x51d9c0  DebugOut::add(0xb8985b "Found facebook friend: %s", x25+0x28)
```

收尾（`0x51da0c`，解析失败 / `{}` / 正常都经过）：

```
0x51da20  从 [this+0x30]-1 往前遍历 [this+0x38]:
0x51da28    ldrb w13,[x12,#0x81] ; cbz → 删除            ; 键为空 → 删
0x51da30    ldrb w12,[x12,#0xac] ; tbnz w12,#3 → 保留     ; ★ 必须带 bit3(8)
            （删除 = 内存前移 0x51da5c..0x51da74，w10--）
0x51da78  str  w10, [this, #0x30]
0x51da88  strh #1, [this, #0x19b6]
0x51da94  bl   OnlineFriends::saveCache()
0x51dac8  mov  w0, #1 ; ret
```

### 5.3 cmd 0x4b —— `GET /v1/profiles?...` → `parseJsonResponse` 0x518264 + `parseProfileJson` @0x5188a4

- root 对象，顶层键 **`profiles`** @**0xb427a4**，值为**数组**，元素为对象，最多 **0x14 = 20** 条，stride **0x144**。

| 键（.rodata 地址） | 值类型 | 写入 `OnlineUbiservicesProfile` 的偏移 |
|---|---|---|
| `userId` @**0xb89398** | string（且 `cbz w8,[x28,#0x30]` 要求类型标签非 0） | `+0x00`（char[0x40]），并置 `w26=1` |
| `nameOnPlatform` @**0xb85478** | string | `+0x40`（char[0x80]） |
| `idOnPlatform` @**0xb8939f** | string（类型标签非 0） | `+0xc0`（char[0x80]） |
| `platformType` @**0xb89381** | string；== `ubimobile` @**0xb8938e** → `w27=3`，否则 2 | 不入结构体（决定是否第三遍读 `profileId`） |
| `profileId` @**0xb8546e** | string（**仅当 `w27==3` 或 `w26!=0` 才读**） | `+0x00`（覆盖 userId），并置 `w26=1` |

返回 `0` 成功 / `7` = `TR_ONLINE_ERROR`（`tst w26,#1; csel w0, wzr, 7, ne`）。

`OnlineUbiservices::ProfileQueryData`：`+0x00` int count、`+0x04` int flag（`onProfilesQueryCompleted` 要求 `==1`）、`+0x08` 记录数组。
`OnlineFriends::onProfilesQueryCompleted(err=w1, data=x20)` @0x51d4bc：`err==7` 或 `err!=0` 或 `flag!=1` 或 `count<1` → 走 0x51d5c0；否则对每条记录用 `strcmp(记录+i*0x144+0xc8 /*idOnPlatform*/, FB条目+0x28)` 匹配，命中则 `addFriend(记录+8 /*userId*/)`、`strncpy(x23+0x00, x22+0x28, 0x80)`、`strncpy(x23+0xb4, x22, 0x27)`、`strh #2,[x22+0xaa]`、`[x23+0xac] |= 4`、DebugOut(`FIGURED OUT PLAYER: %s -> %s` @0xb897de)。

### 5.4 `OnlineFriendInfo` 结构（大小 **0xdc** = 220 B）

| 偏移 | 类型 | 内容 | 证据 |
|---|---|---|---|
| `+0x00` | char[0x81] | 显示名 `nameOnPlatform` | `0x51cfd4 strncpy(x27+0x00, 值, 0x81)` |
| `+0x81` | char[≈0x2b] | 查找键 / pid（`addFriend` 的 key） | `addFriend` `0x51bf5c strcpy(x20+0x81, key)`；`syncFriendList` `0x51d214 strcat(buf, p+0x81)` |
| `+0x9d..+0xa7` | — | 未使用（`memset(x20,0,0xa9)`） | `addFriend` |
| `+0xa8` | u8 | FB 条目「待查询」bit0(1) | `0x51d3d0 tbz w14,#0`；`0x51d290 tbz w9,#0` |
| `+0xaa` | u16 | 0=未处理 / 1=已收集待查 / 2=已处理 | `0x51d3dc strh #1`；`0x51d8c8 / 0x51d58c strh #2` |
| `+0xac` | u32 | bit1(2)=来自好友列表；bit2(4)=facebook；**bit3(8)=`addFriend` 无条件置的保留位** | `0x51cfec \|=2`；`0x51d8e0 \|=4`；`0x51c03c \|=8` |
| `+0xb4` | char[0x28] | facebook id | `0x51d8c0 strncpy(x26+0xb4, x25, 0x27)` |

`addFriend(char const* key)` @0x51bed4 (444)：
```
若 key==NULL 或 *key==0 → 直接新建
否则 for i in 0..[this+0x30]-1: p=[this+0x38][i]; 若 [p+0x81]!=0 且 json_strcmp(key, p+0x81)==0 → 复用 p
新建: x20 = operator new(0xdc)
      memset(x20, 0, 0xa9)
      strcpy(x20+0x81, key)          ; ★ 无长度限制
      strb wzr, [x20+0xb4]
      stur xzr, [x20+0xac]
      （扩容 [this+0x38]，容量 [this+0x34]，拥有标志 [this+0x40]）
0x51c028 str x20, [data + w22*8] ; [this+0x30] = w22+1
0x51c034 [x20+0xac] |= 8           ; ★ 成功出口无条件置 bit3 → 新建的好友一定带 bit3
0x51c038 ret x20
```

### 5.5 `OnlineFriends` 自身偏移

| 偏移 | 含义 |
|---|---|
| `+0x00` | 主 vptr 0xdd93a0 |
| `+0x08` | `OnlineUbiservicesListener` 子对象（vptr 0xdd9428） |
| `+0x10` | `mz::NetworkDataListener` 子对象（vptr 0xdd9478） |
| `+0x18` | facebook 好友数量 |
| `+0x20` | facebook 好友指针数组（元素为 `char*`） |
| `+0x28` / `+0x40` | 「已拥有」标志（ctor 均置 1） |
| `+0x30` | uplay 好友数量 |
| `+0x34` | uplay 数组容量 |
| `+0x38` | uplay 好友指针数组（`OnlineFriendInfo*`） |
| `+0x48` | `OnlineFriendsListener*` —— **ctor 置 0，全 binary 无其它写入 → 恒 NULL，`vptr[+8](0)` 回调实际永不触发** |
| `+0x50` | 内嵌 `OnlineUbiservices` 子对象（vptr 0xdd9210） |
| `+0x58` | `ProfileQueryData` |
| `+0x19b0` | int，pending 邀请数（`onUPlayFriendQueryCompleted` 写入） |
| `+0x19b4` / `+0x19b5` / `+0x19b6` / `+0x19b7` | 阶段标志；ctor 后仅 `+0x19b7 = 1` |

`updateFriendList(OnlineFriendsListener*)` @0x51cb38 (196)：`checkGameServerConnection(0x80,false)` → 非 0 返回；`OnlineFacebookClient::getPlayingFriends`（条件 `[this+0x19b4]==0` 或 FB client 的 `[+0x20]==0`）→ `loadCache()` → `[+0x19b5]=0` → DebugOut(`calling get friend` @0xb89772) → `getFriendList(x0 = *[GOT 0xe1fe80] = OnlineUbiservices*, x1 = this+8, x2 = [*[GOT 0xe1f910]+0x10], x3 = [*[GOT 0xe20420]+0x138])`。
调用点：`0x4ec3f0`（`OnlineAuthentication::setAuthenticated` @0x4ec228）、`0x4ec69c`（`OnlineAuthentication::onProfileConverted` @0x4ec5c8）、`0x8a2dc4`（`_Z17_updateFriendListv` @0x8a2db8）——**三处都传 `listener = NULL`（`mov x1,xzr`）**。

---

## 6. 崩溃风险审计（重点）

### 6.1 cmd 0x50（`GET /v2/profiles/me/friends`）—— 有一条致命的无保护链

**致命链 A：响应体非法 JSON 或为空**

```
0x5182a8  ldr  x8, [x19]          ; listener vptr
0x5182ac  ldr  x8, [x8, #0x38]    ; slot +0x38
0x5182b0  mov  x0, x19
0x5182b4  mov  x1, x21            ; ★ x21 = json_parse 返回值，可能是 NULL，此处无 cbz
0x5182b8  blr  x8
```
→ `OnlineFriends::onFriendlistRecieved(root = NULL)`：
```
0x51cf18  ldr  x8, [x1, #0x10]    ; NULL + 0x10 → 读地址 0x10 → SIGSEGV
```
对比 **cmd 0x4b 分支有保护**：`0x51826c cbz x21, 0x5185b4`。**cmd 0x50 没有。**

**致命链 B：响应是 `{}`（空对象）**

```
0x51cf18  ldr  x8,  [x1, #0x10]   ; x8 = root->child = NULL（空对象没有成员）
0x51cf1c  ldr  x28, [x8, #0x10]   ; NULL + 0x10 → 读地址 0x10 → SIGSEGV
```
→ `cbz x28` @0x51cf20 **只保护 x28**，不保护 x8。

**致命链 C：`pid` / `nameOnPlatform` / `state` 的值不是字符串**

解析器**完全不检查 `json_value+0x30` 的类型标签**，直接 `ldr x27,[x26,#0x28]` 当 `char*`：
- `pid` 分支：`0x51d020 ldr x27,[x26,#0x28]` → `0x51d028 bl strlen` → **`strlen(<整数/垃圾指针>)` → SIGSEGV 或越界读**。
- `nameOnPlatform` 分支：`0x51cfa4 strcmp(buf,"0")`、`0x51cfd4 strncpy(x27+0x00, [x26,#0x28], 0x81)`。
- `state` 分支：`json_strcmp([x26,#0x28], ...)` —— `json_strcmp` @0x569138 **NULL 安全**（`cbz x0,0x569144; cbz x1,0x569144; b strcmp`，返回 −1），所以 `state` 缺失/为 null **不崩**。

对照 `parseProfileJson` @0x5188a4 里对 `userId`/`idOnPlatform` 有 `ldr w8,[x28,#0x30]; cbz w8, 跳过` 的类型标签检查——**`onFriendlistRecieved` 没有做任何等价检查**。

**致命链 D：`pid` 长度 ≥ 43 字节**

`addFriend` 的 `0x51bf5c strcpy(x20+0x81, key)` 无边界检查，目标字段仅约 `0x2b` 字节（下一个已知字段在 `+0xac`）→ **堆溢出/踩坏 `+0xac` 标志，进而堆破坏**。同理 `nameOnPlatform` 走的是 `strncpy(..., 0x81)`，是安全的。

**安全的情形**：
- `{"friends":[]}` —— `0x51cf20 cbz x28` 命中，w19=0，随后回调 `onUPlayFriendQueryCompleted(0, 0)`，无好友。
- 第一个成员的值是空数组 / 字符串 / 数字（导致 `[x8+0x10] == 0`）→ `cbz x28` 命中。
- root 是数组 `[...]`：`[x1+0x10]` 是元素、`[x8+0x10]` 又取该元素的子节点，不会按预期解析，**行为未定，未实测**（不建议）。

### 6.2 cmd 0x65（`POST /public/friends/v1/update`）—— 无已知崩溃路径

| 位置 | 指令 | 效果 |
|---|---|---|
| `0x51d7f0` | `cbz x0, #0x51da0c` | 非法 JSON → 安全跳过 |
| `0x51d7f8` | `cbz x23, #0x51da0c` | `{}` → 安全跳过 |
| `0x51d83c` | `cbz x21, #0x51d864` | uplay 数组为空 → 仅清零，不崩 |
| `0x51d8f8` | `cbz x21, #0x51d964` | facebook 数组为空 → 安全 |
| `0x51d900` | `cbz x20, #0x51d944` | facebook 元素非对象 → `x26=x27=0` |
| `0x51d9e4`/`0x51d9f4` | `json_strcmp([x23+0x20], "uplay"/"facebook")` | 键/值为 null → `json_strcmp` NULL 安全 |

元素类型不匹配（uplay 元素是对象、facebook 元素是字符串）→ `[x,#0x28]` 交给 `json_strcmp` → 不崩，只是匹配不上。
`0x51d7d0 strb wzr,[x20, w2, uxtw]` 只写 `data[size]`，在引擎给出的缓冲内，无越界。

**结论：端点 2 的响应没有已知崩溃路径**，最安全回复是 `{}`。

### 6.3 行为风险（不崩但会毁数据）

**最危险的一条**：cmd 0x65 的响应假如返回 `{"uplay":[]}`（或缺少 `uplay` 键），则所有本地 `[+0xac]&2` 的好友都会被 `0x51d864 str wzr,[x9,#0xac]` 清零，并在收尾 `0x51da30 tbnz w12,#3` 处**被从前端列表删除**（`[this+0x30]` 递减）。所以这个端点不能随便回空数组；要么回 `{}`（`cbz x23` 直接跳过整个解析，一条都不处理），要么**原样回显客户端发来的 id**。

---

## 7. 服务器应该返回什么

### 7.1 `GET /v2/profiles/me/friends`（cmd 0x50）

**必须**：HTTP 200 + `Content-Type: application/json`，body 是**合法 JSON 的非空对象**。

让 2 个好友出现的**最小可用 body**：

```json
{"friends":[
  {"pid":"44444444-4444-4444-4444-444444444444","nameOnPlatform":"GhostRider","state":"Friend"},
  {"pid":"55555555-5555-5555-5555-555555555555","nameOnPlatform":"TangoPro","state":"Friend"}
]}
```

约束（每一条都对应上面的指令）：
1. root 必须是对象，且**第一个成员**就是承载好友数组的那个键；
2. 键名任意（`friends` / `data` / 任何名字都行），但**只能有一个成员**承载数据时才最保险（其余兄弟不会被读）；
3. 该成员的值必须是**数组**；
4. 数组元素必须是**对象**；
5. 每个对象里 **`pid` 必须出现在 `nameOnPlatform` 之前**；
6. `pid`、`nameOnPlatform`、`state` 的值**必须是 JSON 字符串**；
7. `pid` 长度 < 43 字节（`strlen` 走的是 `strncpy(sp+0x18, pid, strlen(pid))` 到 512 B 缓冲，安全；但 `addFriend` 里是 `strcpy` 到 +0x81，有界）；
8. `state` 用来数 pending 邀请：值为 `"PendingReceivedInvite"` 会让 `onUPlayFriendQueryCompleted(0, N)` 收到 N>0；其它值（如 `"Friend"`）计数为 0。

不想要任何好友：`{"friends":[]}`（安全）。
**绝不要**返回：空 body、`{}`、非 JSON、把 `pid`/`nameOnPlatform` 写成数字/对象/数组/null。

> 关于「出现几个好友」：解析器**只读 root 的第一个成员**，所以「N 个顶层键」只会取到第一个；要 N 个好友必须写成**一个数组成员含 N 个对象**。`server/rules.json` 现在正是这个形状（2 个对象在同一个 `friends` 数组里），所以两个假名都显示出来了。

### 7.2 `POST /public/friends/v1/update`（cmd 0x65）

最安全：`{}`（`0x51d7f8 cbz x23` 直接跳过，不改动本地好友）。

要让好友不被删掉（推荐）：**原样回显请求体里的 `uplay` 数组**：

```json
{"uplay":["44444444-4444-4444-4444-444444444444","55555555-5555-5555-5555-555555555555"],"facebook":[]}
```

- `uplay` 元素必须是**字符串**；`facebook` 没有 FB 好友时给 `[]`（若给元素，必须是对象 `{"uplay":"…","fbid":"…"}`，两个值都是字符串）。
- 客户端只会检查「本地已有好友的 pid 是否出现在 `uplay` 里」，所以多余的 id 是无害的，缺 id 才会删好友。

### 7.3 `GET /v1/profiles?idOnPlatform=…&platformType=fb`（cmd 0x4b）

只有当客户端走到 FB 分支（`[this+0x18] > 0` 且有 `[+0xa8]&1` 的条目）才会发出。本私服基本不会有 FB 好友，返回 `{"profiles":[]}` 即可，**不会崩**（0x4b 分支对 NULL 与空数组都有 `cbz` 保护）。若要支持，按 §5.3 的表填：

```json
{"profiles":[{"userId":"44444444-4444-4444-4444-444444444444","nameOnPlatform":"GhostRider","idOnPlatform":"44444444-4444-4444-4444-444444444444","platformType":"ubimobile"}]}
```
注意 `onProfilesQueryCompleted` 要求 `ProfileQueryData::flag == 1`（由 `parseProfilesJson` 在成功解析后置位），且要用 `idOnPlatform` 与客户端本地 `[this+0x20]` 里的 fb id 做 `strcmp`；`platformType` 只有在等于 `ubimobile` 时才允许第三遍读 `profileId`（`w27=3`）。

### 7.4 `server/rules.json` 现状评估

`server/rules.json:96-121` 的 `"GET /v2/profiles/me/friends"` 规则：

```json
{"friends":[{"pid":"…","userId":"…","idOnPlatform":"…","nameOnPlatform":"GhostRider","platformType":"ubimobile","state":"Friend"}, {…"TangoPro"…}]}
```

- **形状完全正确**：对象 → `friends` 数组 → 对象元素；`pid` 在 `nameOnPlatform` 之前；所有值都是字符串；`state:"Friend"`（不等于 `PendingReceivedInvite`，pending 计数为 0）。额外的 `userId` / `idOnPlatform` / `platformType` 键**不会被 cmd 0x50 的解析器读**（它只认 `state` / `pid` / `nameOnPlatform`），但**无害**。
- 第 96–97 行的注释（`//friends` 说 `onFriendlistRecieved` 遍历 `root->child->child` 并读 `pid` / `nameOnPlatform` / `state`）**描述正确**。
- 第 97 行注释（`//friends2`）说「形状必须是 `{"<任意键>": [ {..}, .. ]}`；返回空数组最安全（不会触发头像/资料查询）」——**前半句正确**；「返回空数组最安全」也对，但**不完整**：空数组会让好友列表为空，而且它没有提到**`pid` 必须先于 `nameOnPlatform`**、以及 **`{}` / 空 body / 非字符串值都会 SIGSEGV** 这两条关键约束。
- 唯一的实际缺陷是**名字/ID 是硬编码的假名**（`GhostRider` / `TangoPro`），这正是 UI 里显示假名的原因。

### 7.5 host 问题（部署必读）

`getFriendList` 的 URL 是 `snprintf(..., "%s/v2/profiles/me/friends", "https://public-ubiservices.ubi.com")` —— **base 是硬编码字面量 0xb85565，不是 `[OnlineCore+0x28]`**。所以 `/v2/profiles/me/friends` 是打到 Ubisoft 官方域名的，私服要接管只能靠 DNS/hosts 劫持该域名（或证书代理）。相对地，`/public/friends/v1/update` 的 base 来自 `[OnlineCore+0x28]`（运行时可变，私服已经能命中，说明这一路是通的）。`/v1/profiles` 同样走 0xb85565。

---

## 8. 未能确定 / 存疑

1. **`tr::OnlineFriendsListener` 接口的 vtable 与槽位名**：`.dynsym` 与 `.rodata` 中都**没有** `_ZTVN2tr21OnlineFriendsListenerE` / `_ZTSN2tr21OnlineFriendsListenerE`，只能从 `updateFriendList(OnlineFriendsListener*)`、`getPicture`、`getMyPicture` 的 mangled 名确认接口存在。`OnlineFriends+0x48` 上那个 listener（`resolveOnlineIds`/`onUPlayFriendQueryCompleted`/`finishFriendQueries` 里调 `[x0]->vptr[+8](0)` 的对象）**具体是哪一类、那个槽叫什么名字，未能确定** —— 而且该指针在 ctor 里被置 0 且全 binary 无其它写入，**实际恒为 NULL，该回调永不触发**。这个「3 个实现类」的清单也无法列出。
2. **`[OnlineCore+0x28]` 的运行时取值**：只能静态确认 `snprintf(..., "%s/%s/friends/v1/update", [OnlineCore+0x28], "public")`；实际的 base URL 字符串在运行时才写入，静态看不到，**无法回答它是否就是私服地址**（但从「私服能收到这个请求」反推，它是）。
3. **Facebook 链路未展开**：`OnlineFacebookClient::getPlayingFriends`、`ExternalProfileInfo` 的布局、`[this+0x20]` 数组元素指向的对象结构（只知道它的 `+0x28` 起是显示名字符串、它本身被当作 fb id 传给 `strncpy(x+0xb4, x25, 0x27)`），以及 `addFacebookFriend` @0x51c110 的语义，都没有逐指令解读。
4. **`OnlineFriends+0x19b0` ~ `+0x19b7` 的完整语义**：只确定了 `+0x19b0` = pending 邀请数（`onUPlayFriendQueryCompleted` 写入）、`+0x19b4` = 「FB 查询已启动」、`+0x19b5` = 「FB 查询已完成」、`+0x19b6` = 「friends/v1/update 已发出/进行中」的重入锁、`+0x19b7` = 认证就绪（ctor 唯一置 1 的）。`+0x19b1`/`+0x19b2`/`+0x19b3` 未见任何读写。
5. **cmd 0x65 的 `facebook` 元素对象同时缺 `uplay` 和 `fbid` 键**：`json_strcmp(x25, x27)` 里 x27 会是 0 或前一次循环残留值（`x27` 只在匹配到 `fbid` 键时才赋值，`0x51d944` 分支把 `x26=x27=0`），随后若偶然相等会调 `addFriend(NULL/x26)` 建一条无键记录（`[+0x81]` 为空 → 收尾时会被删除）。**具体后果未实测**，只是推断。
6. **root 是 JSON 数组（而非对象）时的行为**：`[x1+0x10]` 取元素、再 `[x8+0x10]` 取该元素的子节点，会得到不成对的数据，**不会按预期解析**；是否可能偶发崩溃未实测。
7. **`pid` 越界（≥43 B）的实际后果**：只能从 `strcpy(x20+0x81, key)` 无界 + 下一个已知字段在 `+0xac` 推出会踩到标志位/堆元数据，**未做运行时验证**。
8. **`[OnlineCore+0x28]` 之外，`w6 = 0x34bc0` / `w4 = 0` / `w5 = 1` 这些 `getRequest` 参数的确切含义**（超时？重试？优先级？）未从 `mz::NetworkEngine::addRequest` 侧确认。

---

## 9. 关键反汇编证据

### 9.1 `json_strcmp` @0x569138（NULL 安全，20 B）

```
0x569138  cbz  x0, #0x569144
0x56913c  cbz  x1, #0x569144
0x569140  b    strcmp            ; PLT 0x340150
0x569144  mov  w0, #-1
0x569148  ret
```

### 9.2 `parseJsonResponse` cmd 0x50 分支（无 NULL 检查）

```
0x5181bc  bl   json::json_parse
0x5181c0  mov  x21, x0
...
; cmd 0x50 → 0x5182a8
0x5182a8  ldr  x8, [x19]
0x5182ac  ldr  x8, [x8, #0x38]
0x5182b0  mov  x0, x19
0x5182b4  mov  x1, x21          ; x21 可能是 NULL
0x5182b8  blr  x8
0x5182bc  b    #0x518674
```
对比 cmd 0x4b 分支：
```
0x518264  cbz  x19, #0x518674
0x518268  add  x23, x20, #8
0x51826c  cbz  x21, #0x5185b4    ; ★ 有保护
0x518270  ldr  x25, [x21, #0x10]
0x518274  cbz  x25, #0x5185b4
```

### 9.3 `OnlineFriends::onFriendlistRecieved` 开头（两条无保护解引用）

```
0x51cf18  ldr  x8,  [x1, #0x10]   ; root->child        （x1==NULL 时读 0x10）
0x51cf1c  ldr  x28, [x8, #0x10]   ; x8->child          （x8==NULL 时读 0x10）
0x51cf20  cbz  x28, #0x51d050     ; 只保护 x28
```

### 9.4 `OnlineFriends::addFriend` 的 `strcpy`

```
0x51bf5c  bl   strcpy              ; strcpy(x20+0x81, key)，无长度限制
0x51c03c  ldr  w8, [x20, #0xac] ; orr w8,w8,#8 ; str w8,[x20,#0xac]   ; 无条件置 bit3
```

### 9.5 cmd 0x65 的两处 `cbz`（端点 2 安全的依据）

```
0x51d7f0  cbz  x0,  #0x51da0c     ; json_parse 失败
0x51d7f8  cbz  x23, #0x51da0c     ; {}
```

### 9.6 cmd 0x65 的「未回显即删除」

```
0x51d854  ldr  x21, [x21, #0x8]
0x51d858  cbnz x21, #0x51d840
0x51d864  str  wzr, [x9, #0xac]   ; 找不到 → 标志清零
; 收尾
0x51da30  ldrb w12, [x12, #0xac]
0x51da34  tbnz w12, #3, 保留
          ; 否则内存前移删除，w10-- → 0x51da78 str w10,[this+0x30]
```
