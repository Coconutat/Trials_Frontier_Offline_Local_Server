package com.ubisoft.redlynx.trialsgo;

/**
 * 编译期用的影子类，只为让 javac 认得出 OfflinePayloadSetup 的父类。
 *
 * 真正的 com.ubisoft.redlynx.trialsgo.DexApplicationClass 在 APK 的 classes.dex 里，
 * 反编译回去是这样（见 tmp/_dexinfo.py 的输出）：
 *
 *     public class DexApplicationClass extends androidx.multidex.MultiDexApplication {
 *         public void onCreate()V   // code=0x3f274c，唯一的方法
 *     }
 *
 * 影子继承 android.app.Application 而不是 MultiDexApplication，是为了编译时不用
 * 去凑 androidx 的 jar —— 对生成字节码的 invoke-super 目标没有任何影响（super 调用
 * 解析成 DexApplicationClass.onCreate，与影子写的父类无关）。
 *
 * 这个类不会被 d8 打进 APK，只是个 javac 的脚手板。
 */
public class DexApplicationClass extends android.app.Application {
    @Override
    public void onCreate() {
        super.onCreate();
    }
}
