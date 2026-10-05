package com.ubisoft.redlynx.trialsgo;

import android.content.Context;
import android.util.Log;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 首次启动时，把嵌在 APK 里的离线数据摊到磁盘上。
 *
 * 为什么要这么绕：普通用户拿不到 /data/data 的写权限，也没 root，所以数据不能靠
 * adb push 进去 —— 但**进程自己**有权限。于是把数据塞进 APK 的 assets/，让
 * Application 一启动就自己搬过去，全程不需要 root、不需要 adb。
 *
 * 挂载点是 AndroidManifest.xml 里 &lt;application android:name=...&gt; 指向的那个类：
 * 它被 patch_manifest.py setstr 换成了本类（名字等长，字符串池偏移一点没动），
 * 它被 patch_manifest.py setstr 换成了本类，本类继承原来的 DexApplicationClass，
 * 只在 onCreate 之前插一段解包。
 *
 * **类名长度是硬约束**：设备上的清单是二进制 AXML，字符串池里每条字符串都有自己
 * 的偏移，改长度就要重排它后面所有偏移，动静太大。所以本类名必须和
 * com.ubisoft.redlynx.trialsgo.DexApplicationClass 一样长（48 字符，简单名 19 字符）。
 * 改名前先数一遍字符。
 *
 * assets/tf/payload.txt 每行三列，TAB 分隔：
 *
 *     &lt;kind&gt; \t &lt;目标相对路径&gt; \t &lt;assets/tf/ 里面的名字&gt;
 *
 * kind：
 *     f  getFilesDir()              /data/data/&lt;pkg&gt;/files
 *     r  getFilesDir() 的父目录       /data/data/&lt;pkg&gt;
 *     e  getExternalFilesDir(null)  /sdcard/Android/data/&lt;pkg&gt;/files
 *     o  getObbDir()                /sdcard/Android/obb/&lt;pkg&gt;
 *
 * kind=o 的条目拷完之后还会被就地解 zip 到 getExternalFilesDir()，因为引擎读的是
 * 解出来的 content.dat / contentSFX.dat / textures_android.dat，而不是 .obb 本身 ——
 * 两种读法都喂饱，省得为了兼容再多塞一份 64 MB。
 *
 * 全部搬完后写 getFilesDir()/.tf_payload_v1 做标记，以后每次启动直接跳过。
 * 只要有任何一步没成功就不写标记，下次启动重来（宁可多搬一次，不可半途而废）。
 */
public class OfflinePayloadSetup extends DexApplicationClass {

    private static final String TAG = "TFUnpack";
    private static final String ASSETS = "tf";
    private static final String MANIFEST = ASSETS + "/payload.txt";
    private static final String MARKER = ".tf_payload_v1";
    private static final int BUF = 1 << 20;

    @Override
    public void onCreate() {
        try {
            unpack(this);
        } catch (Throwable t) {
            Log.e(TAG, "解包失败（游戏继续启动）", t);
        }
        super.onCreate();
    }

    private static void unpack(Context ctx) throws Exception {
        File files = ctx.getFilesDir();
        if (files == null) {
            Log.e(TAG, "getFilesDir() 是 null，放弃");
            return;
        }
        if (new File(files, MARKER).exists()) {
            Log.i(TAG, "数据早就在了，跳过");
            return;
        }
        File appRoot = files.getParentFile();
        File ext = ctx.getExternalFilesDir(null);
        File obb = ctx.getObbDir();
        Log.i(TAG, "第一次启动，开始搬数据: files=" + files + " ext=" + ext + " obb=" + obb);

        List<String[]> lines = readManifest(ctx);
        List<String[]> zips = new ArrayList<String[]>();
        long total = 0;
        int done = 0, failed = 0;
        for (String[] f : lines) {
            String kind = f[0], rel = f[1], asset = f[2];
            File destDir;
            if ("f".equals(kind)) {
                destDir = files;
            } else if ("r".equals(kind)) {
                destDir = appRoot;
            } else if ("e".equals(kind)) {
                destDir = ext;
            } else if ("o".equals(kind)) {
                destDir = obb;
            } else {
                Log.w(TAG, "不认识的 kind=" + kind + "，跳过 " + rel);
                continue;
            }
            if (destDir == null) {
                Log.w(TAG, "kind=" + kind + " 的目标目录拿不到（外部存储没挂载？），跳过 " + rel);
                failed++;
                continue;
            }
            File out = new File(destDir, rel);
            // payload.txt 第三列是 assets/tf/ 里面的名字，AssetManager 要的是带 tf/ 前缀的路径
            if (copyAsset(ctx, ASSETS + "/" + asset, out)) {
                done++;
                total += out.length();
                Log.i(TAG, "  " + kind + " " + rel + "  " + out.length() + " 字节");
            } else {
                failed++;
            }
            if ("o".equals(kind)) {
                zips.add(new String[] { rel, asset });
            }
        }
        Log.i(TAG, "拷贝完成: 成功 " + done + " 个 / " + total + " 字节，失败 " + failed + " 个");

        if (ext != null) {
            for (String[] z : zips) {
                File src = new File(obb, z[0]);
                if (!src.isFile()) {
                    Log.w(TAG, "OBB 不在: " + src);
                    failed++;
                    continue;
                }
                if (!unzipInto(src, ext)) {
                    failed++;
                }
            }
        }

        if (failed == 0) {
            writeMarker(new File(files, MARKER));
            Log.i(TAG, "全部就位，写了标记 " + MARKER);
        } else {
            Log.e(TAG, "有 " + failed + " 个失败，不写标记，下次启动重试");
        }
    }

    private static List<String[]> readManifest(Context ctx) throws Exception {
        List<String[]> out = new ArrayList<String[]>();
        InputStream in = ctx.getAssets().open(MANIFEST);
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"), 8192);
            String line;
            while ((line = r.readLine()) != null) {
                if (line.length() == 0 || line.charAt(0) == '#') {
                    continue;
                }
                String[] p = line.split("\t");
                if (p.length == 3) {
                    out.add(p);
                } else {
                    Log.w(TAG, "清单行格式不对，跳过: " + line);
                }
            }
        } finally {
            in.close();
        }
        return out;
    }

    private static boolean copyAsset(Context ctx, String asset, File out) {
        InputStream in = null;
        OutputStream os = null;
        try {
            File dir = out.getParentFile();
            if (dir != null && !dir.isDirectory() && !dir.mkdirs() && !dir.isDirectory()) {
                Log.e(TAG, "建目录失败: " + dir);
                return false;
            }
            in = ctx.getAssets().open(asset);
            os = new FileOutputStream(out);
            byte[] buf = new byte[BUF];
            int n;
            while ((n = in.read(buf)) > 0) {
                os.write(buf, 0, n);
            }
            os.flush();
            return true;
        } catch (Throwable t) {
            Log.e(TAG, "拷 " + asset + " -> " + out + " 失败", t);
            return false;
        } finally {
            close(os);
            close(in);
        }
    }

    /** 把 OBB 里的条目原样解到 destDir（条目名就是 content.dat 之类，不带目录）。 */
    private static boolean unzipInto(File zip, File destDir) {
        ZipInputStream zis = null;
        try {
            zis = new ZipInputStream(new FileInputStream(zip));
            byte[] buf = new byte[BUF];
            ZipEntry e;
            int done = 0;
            while ((e = zis.getNextEntry()) != null) {
                String name = e.getName();
                if (e.isDirectory() || name.contains("..") || name.startsWith("/")) {
                    zis.closeEntry();
                    continue;
                }
                File out = new File(destDir, name);
                File dir = out.getParentFile();
                if (dir != null && !dir.isDirectory()) {
                    dir.mkdirs();
                }
                FileOutputStream os = new FileOutputStream(out);
                try {
                    int n;
                    while ((n = zis.read(buf)) > 0) {
                        os.write(buf, 0, n);
                    }
                    os.flush();
                } finally {
                    close(os);
                }
                done++;
                zis.closeEntry();
            }
            Log.i(TAG, zip.getName() + " 解开 " + done + " 个条目 -> " + destDir);
            return true;
        } catch (Throwable t) {
            Log.e(TAG, "解 " + zip + " 失败", t);
            return false;
        } finally {
            close(zis);
        }
    }

    private static void writeMarker(File f) {
        OutputStream os = null;
        try {
            os = new FileOutputStream(f);
            os.write('1');
            os.flush();
        } catch (Throwable t) {
            Log.e(TAG, "写标记失败: " + f, t);
        } finally {
            close(os);
        }
    }

    private static void close(Object c) {
        try {
            if (c instanceof java.io.Closeable) {
                ((java.io.Closeable) c).close();
            }
        } catch (Throwable ignored) {
            // 关闭失败无关紧要
        }
    }
}
