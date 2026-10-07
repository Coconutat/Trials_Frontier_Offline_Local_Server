# -*- coding: utf-8 -*-
"""AIO 补丁器的功能开关定义。

每个开关 = 一组「原生库定点补丁 id」+ 若干「额外流水线动作」。
补丁 id 必须与 vendored/native.py 的 PATCHES 一一对应（native.py 用 --only 取子集）。
"""

# 原生补丁 id（照抄 vendored/native.py 的 "id"）
P_ANTICHEAT = "anticheating-off"
P_OFFER_WHITELIST = "no-offer-blacklist"
P_DL_READY = "dl-content-always-ready"
P_NO_BLACKLIST_POPUP = "no-blacklist-popup"
P_NO_ADS = "no-ads"
P_VIP_NULL_GUARD = (
    "vip-membership-null-guard-slot0-a",
    "vip-membership-null-guard-slot0-b",
    "vip-membership-null-guard-slot0-c",
    "vip-membership-null-guard-slot1-a",
    "vip-membership-null-guard-slot1-b",
)
P_UNLIMITED_FUEL = "unlimited-fuel"
P_SPEND_ADDS = "spend-adds-instead-of-subtracts"
P_IAP = ("iap-failed-redirects-to-complete",
         "iap-cancel-redirects-to-complete")
P_VIP_SHOP = ("vip-shop-offer-iap-stub-call",
              "vip-shop-offer-iap-stub",
              "vip-shop-offer-iap-fakeinfo")

# 流水线动作位
ACT_MANIFEST_TARGETSDK = "manifestTargetSdk"   # targetSdkVersion = 27
ACT_DYN_ADDR = "dynaddr"                       # 注入「服务器地址读本地 txt」例程
ACT_URLS = "urls"                              # 静态把硬编码 URL 改成本地地址
ACT_DEX = "dex"                                # 去广告/去遥测的 dex 手术
ACT_BUNDLE = "bundle"                          # 塞离线载荷 + classes4.dex + minSdk 21
ACT_SET_APPCLASS = "setAppClass"               # 换 Application 类名（自包含必需）


class Feature(object):
    def __init__(self, key, label, hint, patches=(), actions=(),
                 default=False, required=False):
        self.key = key
        self.label = label
        self.hint = hint
        self.patches = tuple(patches)
        self.actions = tuple(actions)
        self.default = default
        self.required = required


FEATURES = [
    Feature(
        "offline", "离线可玩（核心）",
        "关反作弊、放行商店/内容、去掉黑名单弹窗、修 VIP 空指针崩溃、"
        "把服务器地址改成你自己填的那个",
        patches=(P_ANTICHEAT, P_OFFER_WHITELIST, P_DL_READY,
                 P_NO_BLACKLIST_POPUP) + P_VIP_NULL_GUARD,
        actions=(ACT_MANIFEST_TARGETSDK, ACT_DYN_ADDR, ACT_URLS),
        default=True, required=True),
    Feature(
        "noads", "去广告 / 去遥测",
        "不初始化 AdMob/Tapjoy，屏蔽 Crashlytics 上报（不影响离线玩法）",
        patches=(P_NO_ADS,), actions=(ACT_DEX,), default=True),
    Feature(
        "fuel", "无限汽油",
        "ConsumableManager::isUnlimitedFuel() 恒真，加油不消耗库存",
        patches=(P_UNLIMITED_FUEL,), default=False),
    Feature(
        "money", "货币不减反增",
        "PlayerItems::remove() 里把减法改成加法：花钱反而涨钱",
        patches=(P_SPEND_ADDS,), default=False),
    Feature(
        "iap", "破解内购（点击购买即成功）",
        "购买失败/取消一律改走 onPurchaseComplete —— 不校验票据、不联网。"
        "仅供单机自娱",
        patches=P_IAP, default=False),
    Feature(
        "vip", "解锁骑士俱乐部 VIP",
        "商店里的 VIP 商品直接返回一个假的会员条目，不经过 Google Play",
        patches=P_VIP_SHOP, default=False),
    Feature(
        "bundle", "打包成自包含完整 APK（装上就能玩）",
        "把 payload 里的离线数据（appdata + OBB，约 300 MB）塞进 APK 的 "
        "assets/tf/，首次启动自动搬到应用私有目录",
        actions=(ACT_BUNDLE, ACT_SET_APPCLASS), default=False),
]

BY_KEY = {f.key: f for f in FEATURES}

ALL_PATCH_IDS = tuple(p for f in FEATURES for p in f.patches)


def resolve(selected):
    """selected: 可迭代的 feature key → (patch_ids, actions, 回显用的 label 列表)"""
    keys = []
    for f in FEATURES:                     # 保持声明顺序，required 永远入选
        if f.required or f.key in selected:
            keys.append(f.key)
    patches, actions, labels = [], [], []
    for k in keys:
        f = BY_KEY[k]
        labels.append(f.label)
        for p in f.patches:
            if p not in patches:
                patches.append(p)
        for a in f.actions:
            if a not in actions:
                actions.append(a)
    # 保持与 native.py 的 PATCHES 同序，日志读起来和单脚本一致
    order = {p: i for i, p in enumerate(ALL_PATCH_IDS)}
    patches.sort(key=lambda p: order.get(p, 999))
    return keys, patches, actions, labels


def defaults():
    return [f.key for f in FEATURES if f.default or f.required]
