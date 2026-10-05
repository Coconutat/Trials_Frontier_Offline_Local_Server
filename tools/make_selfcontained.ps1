# 打一个「装上就能玩」的自包含 APK：
#   1. 从基线 APK 里抠出 AndroidManifest.xml，把 <application android:name> 等长改成
#      我们的 OfflinePayloadSetup，并把 minSdkVersion 抬到 21（multidex 加载 Application
#      要求 API>=21）；
#   2. javac + d8 编出 classes4.dex；
#   3. 把裁剪好的离线数据（appdata 树 + OBB）作为 assets/tf/p/NNNN 以 store 方式塞进 APK，
#      同时生成 assets/tf/payload.txt 说明每个条目该落到哪；
#   4. zipalign + apksigner。
#
# 为什么走 assets 而不是别的：普通用户没有 /data/data 的写权限、也没有 root，
# 但进程自己有 —— 数据只要进得了 APK，Application 第一次启动就能自己搬过去。
#
# 用法:
#   pwsh -File tools\make_selfcontained.ps1
#   pwsh -File tools\make_selfcontained.ps1 -Server 192.168.1.100:8000 -Name sc2
param(
  [string]$Name = 'selfcontained',
  [string]$Base = 'tmp\build\tf-m16.apk',
  [string]$PayloadDir = 'tmp\pack\TrialsFrontier-clean-pack',
  [string]$Work = 'tmp\selfcontained',
  [string]$Server = '192.168.1.100:8000',
  [string]$KeyStore = 'work\trials-frontier\keystore\trials.jks',
  [string]$Alias = 'trials',
  [string]$StorePass = $env:TF_STOREPASS,
  [switch]$SkipSign
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:JAVA_TOOL_OPTIONS = '-Duser.language=en -Duser.country=US'

$BT   = 'C:\Users\<user>\AppData\Local\Android\Sdk\build-tools\36.0.0'
$AJ   = 'C:\Users\<user>\AppData\Local\Android\Sdk\platforms\android-37.0\android.jar'
$ZULU = 'C:\Program Files\Zulu\zulu-25\bin'

$OLDAPP = 'com.ubisoft.redlynx.trialsgo.DexApplicationClass'
$NEWAPP = 'com.ubisoft.redlynx.trialsgo.OfflinePayloadSetup'
$PKG    = 'com.ubisoft.redlynx.trialsfrontier.ggp'
$OBBNAME = 'main.561.com.ubisoft.redlynx.trialsfrontier.ggp.obb'

if ($OLDAPP.Length -ne $NEWAPP.Length) { throw "Application 类名必须等长：$OLDAPP vs $NEWAPP" }
if (-not (Test-Path $Base)) { throw "找不到基线 APK: $Base" }
if (-not (Test-Path $PayloadDir)) { throw "找不到载荷目录: $PayloadDir" }

$unaligned = "tmp\build\tf-$Name-unsigned.apk"
$aligned   = "tmp\build\tf-$Name-aligned.apk"
$final     = "tmp\build\tf-$Name.apk"

Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$Work\classes","$Work\dex","$Work\assets\tf" | Out-Null

# ---------- 1. 清单 ----------
Write-Host ">>> 清单" -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $Base))
try {
  $ent = $zip.GetEntry('AndroidManifest.xml')
  if (-not $ent) { throw "基线 APK 里没有 AndroidManifest.xml" }
  [System.IO.Compression.ZipFileExtensions]::ExtractToFile($ent, "$Work\AndroidManifest.xml", $true)
} finally { $zip.Dispose() }

python tools\patch_manifest.py setstr "$Work\AndroidManifest.xml" "$Work\AndroidManifest.xml" "$OLDAPP=$NEWAPP"
if ($LASTEXITCODE -ne 0) { throw "patch_manifest setstr 失败" }
python tools\patch_manifest.py set "$Work\AndroidManifest.xml" "$Work\AndroidManifest.xml" 'minSdkVersion=21'
if ($LASTEXITCODE -ne 0) { throw "patch_manifest set 失败" }
python tools\patch_manifest.py get "$Work\AndroidManifest.xml" minSdkVersion targetSdkVersion
python tools\patch_manifest.py dump "$Work\AndroidManifest.xml" --grep name | Select-String -Pattern 'OfflinePayloadSetup|DexApplicationClass' | Select-Object -First 3

# ---------- 2. classes4.dex ----------
Write-Host ">>> classes4.dex" -ForegroundColor Cyan
& "$ZULU\javac.exe" -nowarn -source 8 -target 8 -bootclasspath $AJ -encoding UTF-8 `
  -d "$Work\stubclass" "tools\apkpayload\stub\DexApplicationClass.java"
if ($LASTEXITCODE -ne 0) { throw "javac(stub) 失败" }
& "$ZULU\javac.exe" -nowarn -source 8 -target 8 -bootclasspath $AJ -classpath "$Work\stubclass" -encoding UTF-8 `
  -d "$Work\classes" "tools\apkpayload\OfflinePayloadSetup.java"
if ($LASTEXITCODE -ne 0) { throw "javac 失败" }
$classFiles = (Get-ChildItem "$Work\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName })
& "$BT\d8.bat" --min-api 21 --lib $AJ --output "$Work\dex" $classFiles
if ($LASTEXITCODE -ne 0) { throw "d8 失败" }
if (-not (Test-Path "$Work\dex\classes.dex")) { throw "d8 没产出 classes.dex" }
Write-Host ("    classes4.dex = {0} 字节" -f (Get-Item "$Work\dex\classes.dex").Length)

# ---------- 3. 载荷清单 ----------
Write-Host ">>> 载荷清单" -ForegroundColor Cyan
$entries = New-Object System.Collections.Generic.List[object]

# 注意：$f.FullName 是绝对路径，所以这里必须换成绝对路径再减，否则算出来的相对路径
# 会从中间截断（真出过一次，写出来是 ack/TrialsFrontier-clean-pack/appdata/...）。
$appdata = (Resolve-Path (Join-Path $PayloadDir 'appdata')).Path
foreach ($f in (Get-ChildItem $appdata -Recurse -File | Sort-Object FullName)) {
  # appdata/ 下的顶层目录（files/ shaders/ shared_prefs/ .cache/）和设备上一样位于包根
  $rel = $f.FullName.Substring($appdata.Length + 1) -replace '\\', '/'
  if ($rel.Contains(':') -or $rel.Contains('..')) { throw "算出来的相对路径不像话: $rel" }
  $entries.Add([pscustomobject]@{ Kind = 'r'; Rel = $rel; Local = $f.FullName })
}

$obbFile = Get-ChildItem (Join-Path $PayloadDir 'obb') -File
if ($obbFile.Count -ne 1) { throw "obb/ 下应该只有一个文件，实际 $($obbFile.Count) 个" }
$entries.Add([pscustomobject]@{ Kind = 'o'; Rel = $OBBNAME; Local = $obbFile.FullName })

# tf_server.txt：内部 files/ 与外部 files/ 各放一份（patch_dynaddr 读的是外部那份）
$srv = Join-Path $Work 'tf_server.txt'
Set-Content -Path $srv -Value $Server -NoNewline -Encoding ascii
$entries.Add([pscustomobject]@{ Kind = 'e'; Rel = 'tf_server.txt'; Local = $srv })
$entries.Add([pscustomobject]@{ Kind = 'f'; Rel = 'tf_server.txt'; Local = $srv })

$lines = New-Object System.Collections.Generic.List[string]
$i = 0
foreach ($e in $entries) {
  $e | Add-Member -NotePropertyName Asset -NotePropertyValue ('p/{0:d4}' -f $i) -Force
  $lines.Add(("{0}`t{1}`t{2}" -f $e.Kind, $e.Rel, $e.Asset))
  $i++
}
[System.IO.File]::WriteAllLines("$Work\assets\tf\payload.txt", $lines, (New-Object System.Text.UTF8Encoding($false)))
$bytes = ($entries | ForEach-Object { (Get-Item $_.Local).Length } | Measure-Object -Sum).Sum
Write-Host ("    {0} 个条目，共 {1:N0} 字节（{2:N1} MB）" -f $entries.Count, $bytes, ($bytes / 1MB))

# ---------- 4. 打包 ----------
Write-Host ">>> build_apk" -ForegroundColor Cyan
$pyArgs = @('tools\build_apk.py', '--base', $Base, '--out', $unaligned,
            '--replace', "AndroidManifest.xml=$Work\AndroidManifest.xml")
foreach ($e in $entries) {
  $pyArgs += @('--add', "assets/tf/$($e.Asset)=$($e.Local)")
}
$pyArgs += @('--add', "assets/tf/payload.txt=$Work\assets\tf\payload.txt")
$pyArgs += @('--add', "classes4.dex=$Work\dex\classes.dex")
python @pyArgs
if ($LASTEXITCODE -ne 0) { throw "build_apk 失败 ($LASTEXITCODE)" }

Write-Host ">>> zipalign" -ForegroundColor Cyan
& "$BT\zipalign.exe" -p -f 4 $unaligned $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign 失败 ($LASTEXITCODE)" }

if ($SkipSign) { Write-Host "已跳过签名: $aligned" -ForegroundColor Yellow; exit 0 }

Write-Host ">>> apksigner" -ForegroundColor Cyan
& "$BT\apksigner.bat" sign --ks $KeyStore --ks-key-alias $Alias `
  --ks-pass "pass:$StorePass" --key-pass "pass:$StorePass" `
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true `
  --out $final $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner 失败 ($LASTEXITCODE)" }

& "$BT\apksigner.bat" verify --print-certs $final
Get-Item $final | Format-List FullName, Length
