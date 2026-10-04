# Trials Frontier `gift/v1` 端点族逆向报告

对象：`libTrialsGo.so`（7.9.4 Android / IL2CPP，AArch64，`tmp/libcmp/orig-libTrialsGo.so`）
方法：`.rodata` 字符串池 + `.rela.dyn` 重定位解析 + capstone 逐指令反汇编（`tmp/disasm.py` / `syms.py` / `callers.py`）。

**地址约定（重要，与旧笔记不同）**：`.text`(0x3661b0)、`.rodata`(0xb3b840) 的 VA == 文件偏移；
但从 `.init_array` 起（VA 0xdb9dc8 / off 0xda9dc8）全部 **VA − 0x10000 = 文件偏移**：
`.data.rel.ro` VA 0xdba140 / off 0xdaa140、`.got` VA 0xe08eb0 / off 0xdf8eb0、`.data` VA 0xe23000 / off 0xe13000、
`.bss` VA 0xe457a0 / off 0xe357a0。本报告所有 `.data.rel.ro` 地址均已按此换算。

---

## 0. 结论速览

| # | 结论 |
|---|---|
| 1 | 端点族属于 **`tr::OnlineGifting`**（网络层，`mz::NetworkDataListener` 子类），消费方/UI 是 **`tr::GiftingManager`**（`tr::OnlineGiftingListener` 子类）。 |
| 2 | 共 **6** 个 op：GET `get_gifts`(cmd 0x40) / `gifts`(0x42)，GET+query `claim?type=`(0x41)，POST `give_golden_ticket`(0x3e) / `send_gifts`(0x3f) / `ad_reward`(0x43)。 |
| 3 | URL 一律 `snprintf(buf, 0x80, "%s/%s/gift/v1/<op>", [OnlineCore+0x28], "public")`，**无任何 query 参数**（get_gifts / gifts）。 |
| 4 | **响应只解析 3 个 cmd：0x40 / 0x42 / 0x43。** POST（0x3e/0x3f）的响应体**完全不解析**，客户端只做本地记账并回调 `error=0`。 |
| 5 | `get_gifts` 的响应 **根节点必须是 JSON 数组**（type tag == 2）。服务器现在返回的 `{"data": []}`（对象）会让 `parseGiftArray` 第一行就 `b.ne` 退出 → 静默变成"没有礼物"，**不会报错、不会重试**。 |
| 6 | 5.3 秒轮询的成因已定位：`MenuzStateWarRoom::updateGiftingIndicator` 里 `[m_appTicker] % 300 == 0` → `GiftingManager::requestUpdate()`。因为 `GiftingManager::isUptoDate()` 依赖 `OnlineGifting+0x28`（server_time），而该字段**只有 `gifts`(0x42) 的响应才会写入**，所以只要 `get_gifts` 一直在被调用，UI 就永远认为数据过期，每 300 帧（≈5.32 s）重发一次。**是 UI 刷新循环，不是解析失败的 retry。** |

---

## 1. 类归属

### 1.1 网络层 `tr::OnlineGifting`

- typeinfo `_ZTIN2tr13OnlineGiftingE` @0xdd9620；vtable `_ZTVN2tr13OnlineGiftingE` @ `.data.rel.ro` 0xdd95e0（56 B，重定位后）：

| 槽 | 内容 |
|---|---|
| +0x00 | 0（offset-to-top） |
| +0x08 | `&_ZTIN2tr13OnlineGiftingE` |
| +0x10 | `OnlineGiftingD2Ev` |
| +0x18 | `OnlineGiftingD0Ev` |
| +0x20 | `OnlineGifting::onNetworkError` |
| +0x28 | `mz::NetworkDataListener::onNetworkServerTimeUpdated(unsigned int)`（4 B stub） |
| +0x30 | `OnlineGifting::onNetworkDataReceived` |

即引擎通过 **`[listener + 0x20]` 虚槽** 调 `onNetworkDataReceived`。
`getRequest`/`postJson` 的第一个参数就是 `this`（`OnlineGifting` 自身实现 listener 接口）。

### 1.2 监听器接口 `tr::OnlineGiftingListener`

name @0xb851a0，typeinfo @0xdd7560。**没有虚析构槽**（三个实现类的 vtable 都是 2 头 + 4 槽 = 48 B）：

| 槽 | 签名 |
|---|---|
| `[vptr+0x00]` | `onGiftSubmitted(TR_ONLINE_ERROR, char const*, int)` |
| `[vptr+0x08]` | `onGiftsReceived(TR_ONLINE_ERROR, mt::Array<OnlineGiftItem> const*)` |
| `[vptr+0x10]` | `onGiftsClaimed(TR_ONLINE_ERROR, OnlineGiftItem::GIFT_TYPE)` |
| `[vptr+0x18]` | `onAdvertisementTicketEarned(TR_ONLINE_ERROR)` |

三个实现：`_ZTVN2tr14GiftingManagerE` @ `.data.rel.ro` 0xdd9f70（+0x08 = &typeinfo `_ZTIN2tr14GiftingManagerE` @0xdd9fa0；+0x10=`GiftingManager::onGiftSubmitted` **0x59c1ac**(476)、+0x18=`GiftingManager::onGiftsReceived` 0x59b90c(256)、+0x20=`GiftingManager::onGiftsClaimed` 0x59b88c(104)、+0x28=`GiftingManager::onAdvertisementTicketEarned` 0x59c388 4 B stub，四个函数在内存里首尾相连）；
`_ZTVN2tr17MenuzStateWarRoom13GiftingHelperE` @0xdeb448（+0x18=`GiftingHelper::onGiftsReceived` @0x73ad18，其余 3 个是 4 B `ret`）；
`tr::AdInterface`（0x4eb370..0x4eb380 注册）。

### 1.3 `tr::OnlineGifting` 方法表

| 函数 | 地址 | 大小 |
|---|---|---|
| `init()` | 0x51e534 | 52 |
| `reset()` | 0x51e568 | 104 |
| `update(Listener*)` | 0x51e5d0 | 208 |
| `queryGifts(Listener*)` | 0x51e6a0 | 196 |
| `submitGoldenTicket(Listener*, char const*)` | 0x51e764 | 368 |
| `createCheckSum(char*, char const*, char const*)` | 0x51e8d4 | 168 |
| `submitItem(Listener*, char const*, int, int)` | 0x51e97c | 404 |
| `claimGifts(Listener*, unsigned char)` | 0x51eb10 | 328 |
| `getSentGifts(Listener*)` | 0x51ec58 | 192 |
| `earnAdvertisementTicket(Listener*, int)` | 0x51ed18 | 360 |
| `createRewardCheckSum(char*, int)` | 0x51ee80 | 204 |
| `canGift(char const*, int)` / `hasSentGiftTo(...)` / `findGivenGift(...)` | 0x51ef4c / 0x51ef8c / 0x51f0dc | 64 / 336 / 148 |
| `onNetworkError(MZ_NETWORK_ERROR, unsigned int, unsigned int, void*)` | 0x51f170 | 200 |
| `onNetworkDataReceived(unsigned char*, unsigned int, int, int, void*)` | 0x51f238 | 440 |
| `parseJsonResponse(int cmd, char* body, void* ctx)` | 0x51f528 | 604 |
| `parseGiftArray(json_value*, mt::Array<OnlineGiftItem>&)` | 0x51f784 | 260 |
| `parseSentGifts(json_value*, mt::Array<OnlineGiftItem>&)` | 0x51f888 | 1004 |
| `parseGiftData(json_value*, mt::Array<OnlineGiftItem>&)` | 0x51fc74 | 664 |

成员布局（推断）：`+0x08` `mt::Array<OnlineGiftItem>`（size / data ptr / owns 三连，`+0x08/+0x10/+0x18`）、`+0x20` lastQueryTime、`+0x24` queryInterval、`+0x28` **server_time**、`+0x2c` localTime。`OnlineGiftItem` 步长 **0xC4**。

### 1.4 调用方（`callers.py` 实测）

| 请求函数 | 唯一/全部调用点 |
|---|---|
| `queryGifts` | `GiftingManager::requestUpdate` @0x59aee0（唯一）|
| `submitGoldenTicket` | `GiftingManager::sendGift` @0x59c02c |
| `submitItem` | `GiftingManager::sendGift` @0x59c054 |
| `claimGifts` | `GiftingManager::requestClaimAllGifts` @0x59b778 |
| `getSentGifts` | `OnlineCore::onAuthenticationComplete(bool)` @0x56c2b0（登录时一次 → 对应日志里 33 次 `GET gifts`）|
| `earnAdvertisementTicket` | `AdInterface::videoForCurrencyCompleted` @0x4e9f44/0x4ea0bc、`PVPManager::tryAwardSlotMachineGoldenTicketReward` @0x5e0944 |
| `update` | **0 个调用点（死代码）** |

---

## 2. URL / 方法 / opcode 全表

URL 模板（`.rodata`，VA == 文件偏移）：

| op | 模板 | 地址 | 方法 | cmd |
|---|---|---|---|---|
| give_golden_ticket | `%s/%s/gift/v1/give_golden_ticket` | 0xb8998d | POST | **0x3e** (62) |
| send_gifts | `%s/%s/gift/v1/send_gifts` | 0xb899ae | POST | **0x3f** (63) |
| get_gifts | `%s/%s/gift/v1/get_gifts` | 0xb899f7 | GET | **0x40** (64) |
| claim | `%s/%s/gift/v1/claim?type=%s` | 0xb89a0f | GET | **0x41 \| (typeMask << 16)** (65) |
| gifts | `%s/%s/gift/v1/gifts` | 0xb89a2b | GET | **0x42** (66) |
| ad_reward | `%s/%s/gift/v1/ad_reward` | 0xb89a67 | POST | **0x43** (67) |

两个 `%s`：第 1 个 = `[OnlineCore + 0x28]`（服务器基址，运行期由 `tools/patch_dynaddr.py` 指向 `tf_server.txt`），第 2 个 = 字面量 `"public"` @0xb85227。**最终 URL 形如 `http://<host>/public/gift/v1/get_gifts`，不带 query、不带 body。**

HTTP 层签名：

```
tr::OnlineCore::getRequest(mz::NetworkDataListener*, char const* url, unsigned int cmd, int, bool, unsigned int)   @0x56caec (PLT 0x33f1d0)
tr::OnlineCore::postJson  (mz::NetworkDataListener*, char const* url, char const* body, unsigned int cmd, bool)   @0x352770
tr::OnlineCore::checkGameServerConnection(OnlineAuthentication::TR_AUTHENTICATION_ACCESS, bool)                  @0x344bb0
```

`checkGameServerConnection(1,false) != 0` 时**直接放弃、不发请求**（所有 6 个请求函数开头都有这段）。

### 2.1 GET `get_gifts`（cmd 0x40）

`queryGifts` 0x51e6a0：

```asm
0x51e6a0  bl   mt::time::Time::getTimeOfDay      ; → 0x8830dc
0x51e6b4  str  w0, [x20, #0x20]                  ; lastQueryTime = now
          ... ldr x8,[0xe20bb8] → [x8] = OnlineCore* ; checkGameServerConnection(1,false)
0x51e700  snprintf(sp+8, 0x80, "%s/%s/gift/v1/get_gifts"@0xb899f7, [core+0x28], "public"@0xb85227)
0x51e718  mov  w3, #0x40                         ; ← cmd
0x51e71c  mov  w5, #1
0x51e724  mov  w4, wzr
0x51e728  mov  w6, wzr
0x51e72c  bl   OnlineCore::getRequest
0x51e734  str  x19, [x0, #0x470]                 ; 把 listener 挂在 request 对象 +0x470
```

无 query、无 body。返回 0。
`OnlineGifting::update` 0x51e5d0 发**完全相同的请求**（`mov w3,#0x40`），但它先做节流：`delta = now − [this+0x20]; if (delta < [this+0x24]) return;`，间隔来自设置 `Gifting_Query_Interval`（`init()` 0x51e534 读取，默认 0x384 = 900 **秒**）。**该函数无任何调用点**（`callers.py` 结果为空），即线上看到的轮询**不是**它发出的。

### 2.2 POST `give_golden_ticket`（cmd 0x3e）

`submitGoldenTicket` 0x51e764：URL 同上替换模板；body 由 `sprintf(sp+0x88, "{\"friend\":\"%s\",%s}"@0xb8997a, friend, checksumJson)` 生成；`mov w4,#0x3e` → `bl postJson`；随后 `operator new(0x38)` 建挂起结构 `{listener@+0, type=0x87@+8, strncpy(name,friend,0x2a)@+0xc}` 存到 `[req+0x470]`。

### 2.3 POST `send_gifts`（cmd 0x3f）

`submitItem(Listener*, char const* friend, int chestKind, int amount)` 0x51e97c（下方为**节选/伪代码**，行首地址是真实指令地址，部分参数填充写成伪码）：

```text
0x51e9b4  ldr  x26, [0xe20bb8]       ; &GlobalData::m_onlineCoreE → [x26] = OnlineCore*
0x51e9d4  bl   checkGameServerConnection(1,false) ; cbnz → 直接返回
0x51e9dc  cbz  w20, #0x51e9e8        ; chestKind == 0 ? → 走 checksum 分支（fuel）
0x51e9e0  mov  x3, xzr               ; chestKind != 0 → type 字符串 = NULL
0x51e9e4  b    #0x51ea64
; --- chestKind == 0 分支 ---
0x51e9f0  x2 = "%s%u%s%s"@0xb89aad, x3 = friend, w4 = AntiCheating::getSystemTime(),
          x5 = "f"@0xb4b36f, x6 = "18e3548c59ad40dd03907b7aeee71d67"@0xb86ca1   (snprintf, 0x100)
0x51ea1c  calculateMD5(sp+0x48 → buf)
0x51ea28  OnlineChecksum::formatToJson(sp+8, md5hex, w2 = systemTime)
0x51ea38  snprintf(sp+... , 0x80, "%s/%s/gift/v1/send_gifts", [core+0x28], "public")
0x51ea5c  x3 = "fuel"@0xb899c7
; --- 汇合 ---
0x51ea64  sprintf(sp+0x88, "{\"friend\":\"%s\",\"type\":\"%s\",\"amount\":%d,%s}"@0xb899cc,
                  friend, typeStr, amount, checksumJson)
0x51ea8c  mov  w4, #0x3f             ; ← cmd
0x51ea90  mov  w5, #1
0x51ea98  bl   OnlineCore::postJson
0x51eacc  str  w20, [x23, #8]        ; 挂起结构存 chestKind
```

**注意**：`chestKind == 0` 时 type 字符串 = `"fuel"`；`chestKind != 0` 时 x3 保持 NULL（`"type":"(null)"`）—— 这是**疑似潜在 bug**。唯一调用者 `GiftingManager::sendGift` 只在 `GIFT_TYPE == 4`（fuel）时走这条路，并传入来自服务器礼物的 `item+0x04` 字段，而 `parseGiftData` 对 fuel 正好写 **0**（golden_ticket 写 0x87），所以实际线上永远是 `chestKind == 0` → `"type":"fuel"`，与 `f` 校验 tag 自洽。

### 2.4 GET `claim?type=`（cmd 0x41）

`claimGifts(Listener*, unsigned char typeMask)` 0x51eb10：按位拼 `type` 字符串 —— `bit0` → `golden_ticket`@0xb899a0，`bit2` → `fuel`@0xb899c7，中间加 `,`；URL `snprintf(sp+0x48,0x100,"%s/%s/gift/v1/claim?type=%s"@0xb89a0f, base, "public", typeStr)`；然后：

```asm
0x51ebfc  mov  w3, #0x41             ; cmd = 65
0x51ec00  bfi  w3, w24, #0x10, #8    ; cmd |= (typeMask & 0xff) << 16   ← 高位携带 GIFT_TYPE 位掩码
0x51ec04  mov  w4, wzr ; mov w5, #1 ; mov w6, wzr
0x51ec18  bl   OnlineCore::getRequest
```

### 2.5 GET `gifts`（cmd 0x42）

`getSentGifts` 0x51ec58：URL `%s/%s/gift/v1/gifts`@0xb89a2b，`mov w3,#0x42` @0x51eccc → `bl getRequest`，listener 挂 `[req+0x470]`。仅由 `OnlineCore::onAuthenticationComplete` 调用。

### 2.6 POST `ad_reward`（cmd 0x43）

`earnAdvertisementTicket(Listener*, int amount)` 0x51ed18：amount 最小值钳到 **20**（`cmp w21,#0x14; csel`）；checksum 输入 `snprintf(sp+0x108,0x100,"%s%u%d%d%s"@0xb89ab6, [player+0x110], getSystemTime(), [X+0x134], amount, salt@0xb86ca1)`，并 `DebugOut::add("INPUT STRING: %s"@0xb89ac1,…)`；body `sprintf(sp+0x88,"{\"type\":\"golden_ticket\",\"amount\":%d,%s}"@0xb89a3f, amount, checksumJson)`；`mov w4,#0x43` → `bl postJson`。

---

## 3. 请求体与 checksum 算法

`OnlineChecksum::formatToJson` @0x569058 只是一个 `snprintf(out, 0x80, fmt, md5hex, timestamp)` 转发：

```asm
0x569058  mov  w8, w2          ; w8 = timestamp
0x56905c  mov  x9, x1          ; x9 = md5 hex
0x569060  adrp x2, #0xb8b000 ; add x2, x2, #0x53c
0x569068  mov  w1, #0x80
0x56906c  mov  x3, x9
0x569070  mov  w4, w8
0x569074  b    snprintf
```

格式串 @0xb8b53c = **`"checksum":"%s","timestamp":%u`**。

`OnlineChecksum::calculateMD5(char* out, char const* in)` @0x569078：`MD5_Init / strlen / MD5_Update / MD5_Final`，然后 16 字节循环 `sprintf(sp+8, "%02X"@0xbb1396, byte); strcat(...)` ⇒ **32 位大写十六进制**。

盐（salt）常量 @0xb86ca1 = `18e3548c59ad40dd03907b7aeee71d67`。时间来自 `tr::AntiCheating::getSystemTime()` @0x34bd20。

| 端点 | body（`%s` 省略校验片段） | MD5 输入明文 |
|---|---|---|
| `give_golden_ticket` | `{"friend":"<friend>","checksum":"<MD5>","timestamp":<t>}` | `<friend><t>gt18e3548c59ad40dd03907b7aeee71d67` |
| `send_gifts` | `{"friend":"<friend>","type":"fuel","amount":<n>,"checksum":"<MD5>","timestamp":<t>}` | `<friend><t>f18e3548c59ad40dd03907b7aeee71d67` |
| `ad_reward` | `{"type":"golden_ticket","amount":<n>,"checksum":"<MD5>","timestamp":<t>}` | `<playerName><t><[X+0x134]><n>18e3548c59ad40dd03907b7aeee71d67` |

（模板常量地址：`{"friend":"%s",%s}` @0xb8997a、`{"friend":"%s","type":"%s","amount":%d,%s}` @0xb899cc、`{"type":"golden_ticket","amount":%d,%s}` @0xb89a3f、`%s%u%s%s` @0xb89aad、`%s%u%d%d%s` @0xb89ab6。）

**服务器不需要校验 checksum 就能让客户端满意** —— 客户端从不解析 POST 的响应体（见 §4）。

---

## 4. 响应分发：cmd → handler

### 4.1 `OnlineGifting::onNetworkDataReceived` 0x51f238

```asm
0x51f238  mov  x8, x1
0x51f240  and  w1, w3, #0xffff        ; cmd = a3 的低 16 位
0x51f24c  sub  w9, w1, #0x3e
0x51f250  cmp  w9, #5
0x51f254  b.hi 0x51f3a4               ; 只处理 0x3e..0x43
0x51f258  mov  w10, #1 ; lsl w9, w10, w9   ; bitmask
0x51f264  and  w10, w9, #0x34         ; 0b110100 → cmd 0x40 / 0x42 / 0x43
          cbz → …
0x51f2a0  strb wzr, [x8, x2, uxtw]    ; 用 len 把 body 截断成 C 字符串
0x51f2a4  bl   parseJsonResponse(w1=cmd, x2=data, x3=ctx)
```

- **0x40 / 0x42 / 0x43** → 补 NUL 后交给 `parseJsonResponse`。
- **0x3e / 0x3f**（`and w8,w9,#3`）：`w23 = (cmd==0x3f ? 4 : (cmd==0x3e ? 1 : 0))` = GIFT_TYPE；从 `[ctx+0]` 取 listener，`[vptr+0]` = **`onGiftSubmitted(0, friend /*ctx+0xc*/, chestKind /*ctx+8*/)`**；**响应体被完全忽略**。随后 0x51f318–0x51f3a0 做本地记账：遍历 `this+8` 数组（步长 0xC4），若 `json_strcmp(item+0x18, friend)==0 && item+4 == ctx->chestKind` → `item+0x14 = Time::getTimeOfDay()`；否则插入新项 `{+0=GIFT_TYPE, +4=ctx->chestKind, +0x14=now, +0x18=friend}`。
- **0x41**（`and w8,w9,#8`）：`ldr x8,[x20]; ldr x8,[x8,#0x10]; mov x0,x20; mov w1,wzr; mov w2,w4; blr x8` = **`onGiftsClaimed(0, type)`**（claim 的 ctx 就是 listener 本身，因为 `claimGifts` 直接把 listener 存进 `[req+0x470]`）。

### 4.2 `OnlineGifting::onNetworkError` 0x51f170（跳表）

`.rodata` **0xb89948** 处 6 个 int32 自相对偏移（表尾紧邻 `Gifting_Query_Interval`@0xb89960），按 cmd 0x3e..0x43 索引：

| cmd | 目标 | 动作 |
|---|---|---|
| 0x3e | 0x51f1b8 | `onGiftSubmitted(error, ctx->friend, ctx->chestKind)` |
| 0x3f | 0x51f1b8 | 同上 |
| 0x40 | 0x51f1e8 | `onGiftsReceived(error, NULL)` |
| 0x41 | 0x51f204 | `lsr w2,w20,#0x10` → `onGiftsClaimed(error, a3>>16)` ← 反证 claim 的 cmd 高位 = GIFT_TYPE 掩码 |
| 0x42 | 0x51f1dc | 直接 `ret`（无回调） |
| 0x43 | 0x51f220 | `onAdvertisementTicketEarned`（`[vptr+0x18]`） |

入口先 `bl tr::OnlineError::getError(int)` @0x35c3c0 把 MZ 错误码翻译成 `TR_ONLINE_ERROR`；`ctx == NULL` 时直接返回。

### 4.3 `OnlineGifting::parseJsonResponse` 0x51f528

```asm
0x51f538  block_allocator(0x400)  在栈上 sp+0x38
0x51f588  json::json_parse(body, &root /*sp+0x18*/, &err /*sp+0x10*/, &errline /*sp+0xc*/, &alloc)
0x51f590  cmp w21, #0x40  → 0x51f5c4
0x51f59c  cmp w21, #0x42  → 0x51f618
0x51f5a4  cmp w21, #0x43  → 0x51f5a8
0x51f5ac  b.ne 0x51f708        ; 其它 cmd：什么都不做
```

**json_parse 的返回值和 `err`/`errline` 从不检查。** 解析失败 → `root == NULL` → 对应的解析函数被跳过 → 结果就是"空列表 + error=0"。**客户端不会因响应非法而重试或报错。**

---

## 5. 响应 JSON schema

### 5.1 cmd 0x40 `GET /public/gift/v1/get_gifts`

`parseGiftArray` 0x51f784：

```asm
0x51f784  ldr  w8, [x1, #0x30]
0x51f788  cmp  w8, #2
0x51f78c  b.ne → 结束          ; ★ 根节点必须是 JSON 数组（type tag == 2）
```

**根 = 数组**，每个元素交给 `parseGiftData`；只有 `parseGiftData 返回 1 且临时数组非空` 才把元素并入结果（`insert`，步长 0xC4）。

元素 = JSON **对象**，含 4 个 key（三个"值集合" + 一个字符串），**全部必须同名同大小写**：

| key | `.rodata` | 值类型 | 说明 |
|---|---|---|---|
| `type` | 0xb425d3 | **字符串** | 必须等于 `golden_ticket`@0xb899a0 或 `fuel`@0xb899c7；其它值 → 整个元素被丢弃（`mov w0,wzr; ret`） |
| `amount` | 0xb49efd | **集合（数组/对象）** | `[node+0x10]` 取首个子节点，再沿 `[child+0x08]` 遍历兄弟；**每个子节点的整数值产生一个礼物条目**（`ldr w8,[child+0x28]` → item+0x08）。标量 `"amount": 5` 一个条目都不产生 |
| `time_stamp` | 0xb89a9c | **集合（整数）** | 同样按子节点遍历，第 i 个值写入第 i 个条目的 `item+0x10`（循环上界 = 已生成的条目数） |
| `friend` | 0xb8977e | **集合（字符串）** | 同上，第 i 个字符串 `strncpy(item+0x18, …, 0x29)`，再用 `OnlineFriends::getFriend()` 解析显示名写 `item+0x42`（找不到则用本地化串 `getIndexByKey(0xc96c7d28)`） |

三个集合是**按索引并列**的：一个元素可以一次带回 N 份同类礼物。

例子（**可被解析**）：

```json
[
  {
    "type": "golden_ticket",
    "amount": [1, 2],
    "time_stamp": [1700000000, 1700000100],
    "friend": ["PlayerOne", "PlayerTwo"]
  },
  { "type": "fuel", "amount": [2], "time_stamp": [1700000200], "friend": ["SomeoneElse"] }
]
```

`OnlineGiftItem` 布局（0xC4 = 196 B；本机写入点：`parseGiftData`/`parseSentGifts`/`onNetworkDataReceived`）：

| 偏移 | 类型 | 含义 |
|---|---|---|
| +0x00 | u32 | `GIFT_TYPE`：1 = golden_ticket，4 = fuel |
| +0x04 | u32 | chest kind：0x87（golden_ticket）/ 0（fuel） |
| +0x08 | u32 | amount |
| +0x10 | u32 | time_stamp（服务端给的秒） |
| +0x14 | u32 | 本机最后一次赠送时间（本地记账写入） |
| +0x18 | char[0x2A] | 原始 friend 名 |
| +0x42 | char[0x80] | 解析后的显示名（`OnlineFriends::getFriend` 或本地化占位） |

解析后 `parseJsonResponse` 0x51f5c4 分支：`onGiftsReceived(error=0, &array)`（`[ctx_vptr+0x08]`），只有当 `ctx != NULL` 时才回调；随后释放临时缓冲。

### 5.2 cmd 0x42 `GET /public/gift/v1/gifts`（已送出的礼物 + 配置）

`parseSentGifts` 0x51f888，从 **根对象** 的孩子里找 key：

| key | `.rodata` | 嵌套 | 类型 |
|---|---|---|---|
| `gifts` | 0xb89a39 | 数组，元素为对象 | 元素内：`time_stamp`@0xb89a9c（整数 → item+0x10）、`type`@0xb425d3（字符串 `golden_ticket`/`fuel` → item+0x00/+0x04）、`friend`@0xb8977e（字符串 → item+0x18）、`limit`@0xbb3a74（整数） |
| `server_time` | 0xb8695c | 根的直接子 | 整数 → `[this+0x28]`（**这是让 `isUptoDate()` 变真的唯一来源**） |
| `config` | 0xb8691c | 对象 → 子 key `types`@0xb89aa7 | `types` 数组的每个元素：`type`@0xb425d3（`golden_ticket`→kind 0x87 / `fuel`→0）、`limit`@0xbb3a74、`interval`@0xb86a3d（整数）。按 kind 写入 `std::map<int,GiftParams>`（`[GlobalSettings…]+0xa0`，值 = `limit \| (interval << 32)`） |

解析完后：`Time::getTimeOfDay()` → `[this+0x2c]`；再对 `this+8` 里每个条目调 `OnlineFriends::getFriend(item+0x18)` 并 `DebugOut::add("GAVE %s TO %s %d SECONDS AGO"@0xb89a7f, typeStr, friend, server_time − item+0x10)`。
**没有 listener 回调**（0x42 不发任何通知，只更新内部状态）。

### 5.3 cmd 0x43 `POST /public/gift/v1/ad_reward`

**完全不解析 JSON**：

```asm
0x51f5a8  cbz  x20, →结束          ; ctx == NULL 直接返回
0x51f5ac  ldr  x8, [x20]
0x51f5b4  ldr  x8, [x8, #0x18]      ; [vptr+0x18] = onAdvertisementTicketEarned
0x51f5b8  mov  x0, x20 ; mov w1, wzr
0x51f5bc  blr  x8
```

响应体**可以是任意内容**（甚至空体），只要 HTTP 层不报错就会以 `error=0` 回调。

### 5.4 cmd 0x3e / 0x3f（两个 POST）

响应体被丢弃（`§4.1`）。挂起结构（`[req+0x470]`）：`{listener@+0, chestKind@+8, friend[0x2a]@+0xc}`，`onGiftSubmitted(error=0, friend, chestKind)`。

---

## 6. 5.3 秒轮询的成因（问题 5 的答案）

### 6.1 轮询不是 `OnlineGifting::update`

`update`（900 s 间隔，读 `Gifting_Query_Interval`）**没有任何调用点**，是死代码。`queryGifts` 的唯一调用点是 `GiftingManager::requestUpdate`（0x59af98）。

### 6.2 `requestUpdate` 的节流形同虚设

`GiftingManager::requestUpdate` 0x59aee0：

```asm
0x59af30  bl   mt::time::Time::getTimeOfDay      ; 0x8830dc = gettimeofday(&tv,NULL); return tv_sec  → 秒
0x59af34  mov  w20, w0
          ... w0 = mt::String::getHashCode(m_player + 0x110)
0x59af6c  sub  w8, w20, [x19+0x5c]               ; delta = now − lastQueryTime
0x59af70  cmp  w8, #0x3b                         ; 59 秒
0x59af74  b.gt → 发请求
0x59af78  ldr  w8,[x19+0x50]; cmp w0,w8; b.eq → return   ; 同一玩家且 59 s 内 → 不发
```

但 `GiftingManager` 构造函数 0x59adf0 里 `stur q0,[x0,#0x5c]` 把 +0x5c 清 0，而**全二进制没有任何指令写 `+0x5c`** → `delta = now(epoch 秒) − 0` 恒 ≫ 59 → 59 秒闸门**永远放行**。实际频率完全由调用者的帧计数决定。

### 6.3 真正的两个定时器

- `MenuzStateWarRoom::updateGiftingIndicator` @0x7399a4：开头 `bl GiftingManager::isUptoDate()`，若返回 **false** 则走到结尾：

```asm
0x739a9c  ldr  w8, [x19]          ; GlobalData::m_appTicker（+0xe21410 → 计数器 @0xe59afc）
0x739aa0  add  w8, w8, #1
0x739aa4  str  w8, [x19]
          ...  w8 % 300 == 0 →  tail-call GiftingManager::requestUpdate()   @0x739ab4
```

  ⇒ **车库/战争房间界面打开时，每 300 帧发一次 `get_gifts`**。设备实测帧率 ≈ 56.4 fps → 300 / 56.4 ≈ **5.32 s**，与日志中 482/576 个间隔 < 8 s、众数 5.30–5.36 s 完全吻合。
- `tr::MainApp::update` @0x843274：同一计数器 `% 18000 == 0`（`mov w9,#0x52d5; movk w9,#0xe904,lsl#16` → magic 除法，0x4650 = 18000）→ `GiftingManager::requestUpdate()` @0x843438。18000 帧 ≈ **319 s**，对应日志里 53 个 70–400 s 的大间隔。
- 其它调用点：`OnlineCore::onAuthenticationComplete(bool)` 0x56c2bc、`MenuzStateWarRoom::transitionEnter` 0x73a44c、`PopupStateGiftBox::activate` 0x7f4918。

### 6.4 为什么永远"数据过期"

`GiftingManager::isUptoDate()` @0x59afdc：

```asm
0x59afe8  ldrb w8,[x19,#0x58] ; cbz → 返回 0            ; mDataValid
0x59aff4  getHashCode(m_player+0x110) != [x19+0x50] → 清 mDataValid, 返回 0
0x59b00c  ldr  x8, [0xe21930]                           ; OnlineGifting 实例
0x59b014  ldp  w8, w9, [x8, #0x28]                      ; +0x28 server_time, +0x2c localTime
0x59b020  w0 = (w9 != 0) && (w8 != 0)
```

而 `OnlineGifting+0x28`（server_time）**只有 cmd 0x42（`gifts`）的响应会写**（`str w8,[this+0x28]` @0x51f62c 附近），0x40 的响应从不写它。
⇒ 只要玩家在战争房间界面，`isUptoDate()` 恒为 false → **每 300 帧再发一次 `get_gifts`**，循环不止。

### 6.5 日志数据的解释

`work/trials-frontier/notes/server-log.jsonl`：577 次 `GET /public/gift/v1/get_gifts`，`query={}`、全部命中 `*` 兜底、返回 200 `{"data": []}`；576 个间隔中 482 个 < 8 s（尖峰 5.32 s），53 个落在 70–400 s，6 个 > 1000 s；66 个 burst（其中 185 次/17.1 min 等长 burst）；33 次 `GET /public/gift/v1/gifts`（对应登录/鉴权完成）；**整份抓包里没有任何 gift 端点的 POST**（说明当时的玩法没有触发赠送/广告奖励）。

**结论：这是 UI 刷新循环（战争房间每 300 帧 + MainApp 每 18000 帧），不是"响应无法解析所以重试"。** 无论服务器返回什么，客户端失败都是**静默降级成空列表**，绝不会因为 500/非法 JSON 而重试或报错。

---

## 7. 服务器应该返回什么

按重要性排列：

1. **`GET /public/gift/v1/get_gifts`（cmd 0x40）＝ 顶层 JSON 数组**，元素形状见 §5.1。**不要再返回 `{"data": [...]}`**——`parseGiftArray` 第一行就要求根 tag==2，对象会被静默忽略。真正的响应体就是数组本身。
2. `POST /public/gift/v1/give_golden_ticket`（0x3e）、`POST /public/gift/v1/send_gifts`（0x3f）：**响应体内容无关紧要**（客户端不解析）；返回 200 即可，客户端会以 `error=0` 回调并在本地记账。若要"显得真实"，返回 `{}` 或 `{"data":[]}` 都行。
3. `POST /public/gift/v1/ad_reward`（0x43）：同样不解析，200 即可。
4. `GET /public/gift/v1/claim?type=golden_ticket,fuel`（0x41）：解析代码里**没有 0x41 分支**（`parseJsonResponse` 只处理 0x40/0x42/0x43）→ 无论返回什么都不会被解析；客户端以 `error=0` 回调 `onGiftsClaimed(0, type)`。返回 `{}` 即可。
5. `GET /public/gift/v1/gifts`（0x42）：如果希望 **停止 5.3 秒轮询**，这是唯一能改状态的地方——必须返回含 **`server_time`（整数）** 的对象（`{"server_time": 1700000000, "gifts": [...], "config": {"types": [...]}}`），这样 `OnlineGifting+0x28` 被写入、`isUptoDate()` 变真、战争房间不再每 300 帧重发。`gifts`/`config` 可缺省（缺省只是数组/映射为空）。

最小可用返回（让 `get_gifts` 有效且不炸）：

```json
[]
```

最小可用返回（让 `get_gifts` 给出 1 份 golden ticket，并让 5.3 s 轮询停下需要额外一次 0x42）：

```json
[ {"type":"golden_ticket","amount":[1],"time_stamp":[1700000000],"friend":["OfflineBot"]} ]
```

> 注意 `friend` 的名字应尽量与 `/v2/profiles/me/friends` 返回的玩家名一致：`parseGiftData` 会用 `OnlineFriends::getFriend()` 解析显示名，解析不到时用本地化兜底串（不会崩溃，但 UI 会显示占位文本）。
> `time_stamp` 是**绝对 unix 秒**（UI/日志用 `server_time − time_stamp` 计算"多久前"）。

---

## 8. 未能确定 / 存疑

1. **`onGiftsClaimed` 成功路径的 `type` 参数来源**：错误路径用 `a3>>16`（明确 = GIFT_TYPE 掩码，见 §4.2），但成功路径用的是 `onNetworkDataReceived` 的第 4 个参数 `w4`。没有定位到引擎里调用 `[listener+0x20]`（`onNetworkDataReceived`）的站点，因此 `w4` 的取值未验证。若 `w4` 不是类型掩码，claim 成功回调里的 type 可能是无效值。**服务器行为不受影响**（claim 响应本来就不被解析）。
2. **`amount` / `time_stamp` / `friend` 到底是 JSON 数组还是"对象 + 若干子节点"**：解析代码只要求"有子节点、沿 `+0x08` 遍历兄弟"，两种写法都能通过。没有真实的 gift 响应样本可比对（`work/trials-frontier/notes/` 里只有 `{"data": []}` 兜底日志；`tmp/tf2.pcap`（420 KB）尚未分析）。数组是最自然的写法，也符合 `[node+0x10]` + `[x+8]` 链式遍历。
3. **`%s&platformType=uplay`@0xb890c4 的归属**：我的 ADRP+ADD 扫描器对已知被引用的字符串（如 0xb899f7）也返回空，说明扫描实现不可靠（ADRP 与 ADD 不相邻时会漏），因此无法确认该串被哪个函数使用。它在 `.rodata` 里与 gift 串不属于同一簇，且设备抓包中 gift 请求**不含**该参数，**不属于 `gift/v1` 族**。
4. **`GiftingManager+0x50` 的"同一玩家 + 59 秒"闸门**：`[+0x5c]` 从不被写入所以我判断闸门恒放行；若存在运行期通过反射/原生补丁写入它的路径（不在本二进制内），轮询频率会受 59 s 限制。
5. **`GiftingManager::onGiftSubmitted`（0x59b1c0）与 `onGiftsClaimed`（0x59b88c）的 UI 行为**未逐指令分析（与本报告协议层面结论无关）。
6. `tr::OnlineCore::m_giftingE`（GOT 0xe21930）与 `GlobalData::m_onlineCoreE`（GOT 0xe20bb8）的精确类型（是"静态对象含指针"还是"指针"）只做了行为学推断；代码里是 `ldr x8,[0xe20bb8]` 再 `ldr x8,[x8]` 两次解引用取 OnlineCore*。

---

## 9. 关键反汇编证据（非显然结论）

**(a) 根必须是数组** —— `OnlineGifting::parseGiftArray` 0x51f784：

```asm
0x0051f784  ldr   w8, [x1, #0x30]     ; json_value::type
0x0051f788  cmp   w8, #2              ; 2 == JSON array
0x0051f78c  b.ne  #0x51f880           ; 不是数组 → 直接收工（空列表）
```

服务器当前返回 `{"data": []}` → 根是对象 → 这一分支直接退出 → `onGiftsReceived(0, 空数组)`。**这就是"礼物永远为空"的直接原因。**

**(b) POST 响应体被丢弃** —— `onNetworkDataReceived` 0x51f2b0–0x51f2e8 只做：

```asm
0x0051f2dc  ldr  w3, [x20, #8]!       ; chestKind
0x0051f2e0  add  x21, x20, #4         ; → friend
0x0051f2e4  ldr  x8, [x8]             ; [vptr+0]
0x0051f2e8  blr  x8                   ; onGiftSubmitted(0, friend, chestKind)
```

没有任何 `parseJsonResponse` 调用，body 指针也不再被使用。

**(c) json 解析错误被忽略** —— `parseJsonResponse` 0x51f588：

```asm
0x0051f588  bl  json::json_parse      ; x0=body, x1=&root, x2=&err, x3=&errline, x4=&alloc
0x0051f58c  ...                       ; 返回值/err 从未被读取
```

**(d) 5.3 s 的帧计数闸门** —— `MenuzStateWarRoom::updateGiftingIndicator`：

```asm
0x00739a9c  ldr  w8, [x19]
0x00739aa0  add  w8, w8, #1
0x00739aa4  str  w8, [x19]
            ; magic-divide 求 w8 % 300，余 0 才继续
0x00739ab4  b    GiftingManager::requestUpdate
```

**(e) claim 的 cmd 高位 = 类型掩码** —— `claimGifts` 0x51ebfc：

```asm
0x0051ebfc  mov  w3, #0x41
0x0051ec00  bfi  w3, w24, #0x10, #8   ; cmd |= typeMask << 16
```

与之对应的错误路径反证：`onNetworkError` @0x51f204 `lsr w2, w20, #0x10` → `onGiftsClaimed(error, cmd>>16)`。

**(f) checksum 的样子** —— `OnlineChecksum::formatToJson` 的格式串 @0xb8b53c = `"checksum":"%s","timestamp":%u`，`calculateMD5` 用 `%02X`（大写）。
