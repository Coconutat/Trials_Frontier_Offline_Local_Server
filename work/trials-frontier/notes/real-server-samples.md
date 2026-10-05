# 真实服务器响应样本（全仓库仅两份）

> **一句话**：这个仓库里**几乎没有**来自 Ubisoft 真实服务器的数据。本文记录唯一两份能确证的样本，以及"找不到停服前样本"这件事本身的证据。
>
> 用途：给私服定规则时，这是**唯一的外部事实来源**（其余全靠 `.so` 反汇编 + `online-rules-evidence.md` 的史料）。
>
> 采集：2026-10，真机 `<设备序列号>`；来源是 logcat 与 app 自身的 Volley 缓存。

## 0. 先说反面结论：没有停服前的样本

* **没有任何 2021 停服前的响应样本。** 全设备 Trials 相关文件 mtime 全部 ≥ `2026-10-02`。
* `find /data /sdcard ! -newermt 2026-01-01` ⇒ **零命中**。
* 判定：**"从设备上恢复一份停服前真实响应"这条路已经走死**，不要再试。

## 1. 样本 A：真实鉴权响应（唯一带真实凭证的样本）

请求（logcat 里重复出现约 20 次）：

```
POST https://gamecfg-mob.ubi.com/profile/?action=register_device&productid=101&devicetype=google&deviceuid=<deviceuid>
```

响应：

```json
{"device":{"federated_id":"<federated_id>",
           "ubimobi_access_token":"<ubimobi_access_token>"}}
```

* 证据位置：`tmp/logcat_m1.txt:2676`（以及同文件其它约 20 处）。
* 形态要点：响应根是 `{"device": {...}}`，两个字段都是**字符串**。
* `deviceuid` 与我们 `shared_prefs/ubisoftData.xml` 里的 `ubiduid` 同源（`<deviceuid>`）。
* 注意：这两个 token 属于**游客身份**、早已作废，仅作协议形状参照。

## 2. 样本 B：`profile/?epoch=1` 的空载荷

请求：

```
GET https://gamecfg-mob.ubi.com/profile/?epoch=1
```

响应体：`[]`

* 设备上的 Volley 缓存实体：`/data/data/com.ubisoft.redlynx.trialsfrontier.ggp/cache/volley/1901969349596218263`（**1009 B**）；本地副本 `tmp/scout/cache__volley__1901969349596218263`。
* 响应头（缓存里保留下来的）：`Ubisoft-CA: OK`、`Ubisoft-Zone: CN`、`Server-Time: 1791170808`、`X-Android-Response-Source: NETWORK 200`。
* ⇒ **`Server-Time` 是服务器权威时间**；`Ubisoft-Zone: CN` 与我们区域相关。

## 3. 该端点在 2026 年仍然在线

实时验证（2026-10）：

* `gamecfg-mob.ubi.com/profile/?epoch=1` → **302** → `geoip-0-prod.houston-services.ubi.com`
* 该根路径 **HTTP 200，返回 `[]`** —— 与设备缓存里的字节**完全一致**。

⇒ 也就是说：虽然游戏 2025-11-04 下架，Ubisoft 的移动端配置/鉴权域名**至今仍然活着**。将来若要抓真实行为，这是唯一还开着的门。

## 4. 这些字符串在本仓库此前零命中

在全部 `*.md` / `*.txt` 中检索
`federated_id|ubimobi_access_token|register_device|houston-services|geoip-0`
⇒ **零命中**。

即：本文是项目首次记录这批数据。

## 5. 已排除的候选（都不是真实服务器响应）

| 候选 | 实际是什么 |
|---|---|
| `cache/lbstorage.bin`（721 B） | **我们自己合成的榜单**（里面有 "GhostRider" / "TangoPro"） |
| `files/request.json` | CDN **资源清单**（`static-ww.cdn.ubi.com`），不是 API 响应 |
| `files/friend-*.cache` | 不可解密文 |
| `databases/*` | Vungle / Downloads **广告 SDK** 的库 |
| `tmp/pvp_match_rewards.txt` + `tmp/packout/` | 游戏自带数据表提取，**不是**网络响应 |
| `tmp/cap.txt` / `tf2.pcap` | 只有 TLS，无明文 |
| `cache/volley/-1661412709-*` | Google Ads 的 JS |

## 6. 结论

1. **没有停服前的真实响应可挖**（已证明）。私服规则的数值来源只能是：`.so` 反汇编 + `online-rules-evidence.md` 的外部史料 + 我们自己定。
2. **唯一的外部地面真值** = 本文 §1/§2 两份样本 + §3 那个仍活着的端点。
3. 若将来需要真实行为，走 `gamecfg-mob.ubi.com` → `geoip-0-prod.houston-services.ubi.com` 这条线（协议见 `web-research-toolkit.md` 的代理用法）。
