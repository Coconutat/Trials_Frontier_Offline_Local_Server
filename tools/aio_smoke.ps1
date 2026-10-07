# AIO 补丁器 exe 的冒烟：在**空目录**里、**清掉 Python 环境变量**跑，证明它
# 不依赖开发机上的 Python / pip 包，也不偷偷读源码树。
#
# 用法：
#   pwsh tools\aio_smoke.ps1                    # 补丁路径（默认，~1 分钟）
#   pwsh tools\aio_smoke.ps1 -Full              # 加跑自包含打包（约 5 分钟，+300 MB 磁盘）
#   pwsh tools\aio_smoke.ps1 -Exe dist\TrialsFrontierPatcher-console.exe
#
# 零依赖的边界（两样绕不过去，脚本会检查）：
#   * build-tools 里的 zipalign / apksigner
#   * 一个 JDK（apksigner 要 java）
#
# 默认 base = apkmirror 下的**未改动原版**（`libTrialsGo.so` = 743f945c…，与 tfpatcher.py 的
# 期望指纹一致）。别拿 dist\TrialsFrontier-offline.apk 当 base：它是已打补丁的产物。
# 注意：PowerShell 要求 param 是脚本的第一条语句，所以这份默认值只能写进 param 里。

[CmdletBinding()]
param(
    [string]$Exe = 'dist\TrialsFrontierPatcher-console.exe',
    [string]$Base = 'dist\原版APK\com.ubisoft.redlynx.trialsfrontier.ggp_7.9.4-561_minAPI16(arm64-v8a,armeabi-v7a)(nodpi)_apkmirror.com.apk',
    [string]$Payload = '',
    [string]$BuildTools = '',
    [string]$Port = '8123',
    [switch]$Full,
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$sx = if ([System.IO.Path]::IsPathRooted($Exe)) { $Exe } else { Join-Path $root $Exe }
$sb = if ([System.IO.Path]::IsPathRooted($Base)) { $Base } else { Join-Path $root $Base }
if (-not (Test-Path $sx)) { throw "找不到 exe：$sx（先跑 pwsh tools\build_aio.ps1）" }
if (-not (Test-Path $sb)) {
    throw "找不到基准 APK：$sb`n用 -Base 指一份未改动的原版（7.9.4/561）。"
}

$smoke = Join-Path $root 'tmp\aio\smoke'
if (Test-Path $smoke) { Remove-Item $smoke -Recurse -Force }
New-Item -ItemType Directory -Force -Path $smoke | Out-Null

$fail = 0
function Check([string]$what, [bool]$ok, [string]$extra = '') {
    if ($ok) { Write-Host "[OK] $what" -ForegroundColor Green }
    else { Write-Host "[X ] $what $extra" -ForegroundColor Red; $script:fail++ }
}

# ---------------------------------------------------------------- 摆好场地
$exe = Join-Path $smoke ([System.IO.Path]::GetFileName($sx))
Copy-Item $sx $exe
# 清掉 Python 环境：冻结的 exe 不该受宿主 Python 影响（也不该找到它）
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$env:PYTHONSTARTUP = $null
$env:PYTHONNOUSERSITE = '1'

Write-Host "exe      : $exe" -ForegroundColor Cyan
Write-Host "基准 APK : $sb" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1 自检
$log = Join-Path $smoke 'check.log'
& $exe --check *> $log
Check '环境自检退出码 0' ($LASTEXITCODE -eq 0) "(实际 $LASTEXITCODE)"
$txt = Get-Content $log -Raw -Encoding UTF8
Check '自检认出了「打包后的 exe」' ($txt -match '打包后的 exe')
Check '自检能定位随包 dex' ($txt -match 'payload_setup\.dex')
Check '自检找到了 build-tools' ($txt -match 'build-tools')
Check '自检找到了 java' ($txt -match 'java')

$log = Join-Path $smoke 'features.log'
& $exe --list-features *> $log
Check '--list-features 退出码 0' ($LASTEXITCODE -eq 0) "(实际 $LASTEXITCODE)"
$txt = Get-Content $log -Raw -Encoding UTF8
foreach ($k in 'offline', 'noads', 'fuel', 'money', 'iap', 'vip', 'bundle') {
    Check "功能清单里有 $k" ($txt -match ("(?m)^" + $k + "\s"))
}

# ---------------------------------------------------------------- 2 真打一次
$apk = Join-Path $smoke 'base.apk'
Copy-Item $sb $apk
$out = Join-Path $smoke 'out.apk'
$work = Join-Path $smoke 'work'
$alog = Join-Path $smoke 'patch.log'
$extra = @()
if ($BuildTools) { $extra += @('--build-tools', $BuildTools) }

Write-Host '跑一次真实补丁（offline,noads）…' -ForegroundColor Cyan
& $exe --cli --apk $apk --out $out --work $work --server ("192.168.5.2:" + $Port) `
    --features offline,noads @extra *> $alog
Check '补丁退出码 0' ($LASTEXITCODE -eq 0) "(实际 $LASTEXITCODE，日志 $alog)"
$txt = Get-Content $alog -Raw -Encoding UTF8

if (Test-Path $out) {
    Check '产出了补丁版 APK' $true
    $rep = "$out.report.json"
    Check '写了明细报告' (Test-Path $rep)
    if (Test-Path $rep) {
        $j = Get-Content $rep -Raw -Encoding UTF8 | ConvertFrom-Json
        Check '报告里记了 native 步骤' (@($j.steps | Where-Object { $_.step -eq 'native' }).Count -eq 1)
    }
    Check '日志里 apksigner 验签通过（Verifies）' ($txt -match 'Verifies')
    Check '日志里 v1/v2/v3 全 true' (($txt -match 'v1 scheme \(JAR signing\): true') -and
                                     ($txt -match 'v2 scheme \(APK Signature Scheme v2\): true') -and
                                     ($txt -match 'v3 scheme \(APK Signature Scheme v3\): true'))
    # 只勾了 offline,noads：不该出现自包含载荷的痕迹
    $z = [System.IO.Compression.ZipFile]::OpenRead($out)
    try {
        $names = $z.Entries | ForEach-Object { $_.FullName }
        Check '没塞入 assets/tf（本次没勾自包含）' (-not ($names | Where-Object { $_ -like 'assets/tf/*' }))
        Check '没引入 classes4.dex（本次没勾自包含）' (-not ($names -contains 'classes4.dex'))
        Check '抽掉的旧签名没回来' (-not ($names | Where-Object { $_ -like 'META-INF/CERT.*' }))
    }
    finally { $z.Dispose() }
}
else {
    Check '产出了补丁版 APK' $false
}

# ------------------------------------------------- 2b 脏 base 必须被拦住
# 「没勾货币不减反增，成品里却还是有」的成因：拿已打过补丁的产物当 base。
# 补丁器只加不减，所以默认必须报错，而不是默默放行。
$dirty = Join-Path $root 'dist\TrialsFrontier-offline.apk'
if (Test-Path $dirty) {
    $dlog = Join-Path $smoke 'dirty.log'
    & $exe --cli --apk $dirty --out (Join-Path $smoke 'dirty-out.apk') `
        --work (Join-Path $smoke 'dirty-work') --features offline,noads @extra *> $dlog
    $dtxt = Get-Content $dlog -Raw -Encoding UTF8
    Check '拿已打补丁的产物当 base 会拒绝（退出码非 0）' ($LASTEXITCODE -ne 0) "(实际 $LASTEXITCODE)"
    Check '拒绝理由点明「不是未改动的原版」' ($dtxt -match '不是未改动的原版')
    Check '拒绝理由列出 base 里已有的「货币不减反增」' ($dtxt -match '货币不减反增')
    Check '拒绝理由指了该换哪份原版' ($dtxt -match '原版APK')
    Check '脏 base 没产出 APK' (-not (Test-Path (Join-Path $smoke 'dirty-out.apk')))
}
else {
    Write-Host "跳过脏 base 的检查（没有 $dirty）" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 3 自包含（可选）
if ($Full) {
    $pl = $Payload
    if (-not $pl) {
        foreach ($c in @((Join-Path $root 'tmp\pack\TrialsFrontier-clean-pack'),
                         (Join-Path $smoke 'payload'))) {
            if (Test-Path (Join-Path $c 'appdata')) { $pl = $c; break }
        }
    }
    if (-not $pl) {
        Check '找到离线载荷（appdata/ + obb/）' $false '（用 -Payload 指定，或跳过 -Full）'
    }
    else {
        Write-Host "跑一次自包含打包（payload = $pl）…" -ForegroundColor Cyan
        $out2 = Join-Path $smoke 'out-full.apk'
        $flog = Join-Path $smoke 'full.log'
        & $exe --cli --apk $apk --out $out2 --work (Join-Path $smoke 'work-full') `
            --server ("192.168.5.2:" + $Port) --features offline,bundle `
            --payload $pl @extra *> $flog
        Check '自包含打包退出码 0' ($LASTEXITCODE -eq 0) "(实际 $LASTEXITCODE，日志 $flog)"
        $txt = Get-Content $flog -Raw -Encoding UTF8
        if (Test-Path $out2) {
            $z = [System.IO.Compression.ZipFile]::OpenRead($out2)
            try {
                $names = @($z.Entries | ForEach-Object { $_.FullName })
                $tf = @($names | Where-Object { $_ -like 'assets/tf/p/*' })
                Check '塞进了 assets/tf/payload.txt' ($names -contains 'assets/tf/payload.txt')
                Check '塞进了 70 个载荷分片' ($tf.Count -eq 70) "(实际 $($tf.Count))"
                Check '塞进了 classes4.dex（载荷安装器）' ($names -contains 'classes4.dex')
            }
            finally { $z.Dispose() }
            Check '日志里 Application 类换成了 OfflinePayloadSetup' ($txt -match 'OfflinePayloadSetup')
        }
        else { Check '产出了自包含 APK' $false }
    }
}

# ---------------------------------------------------------------- 4 GUI 能起来
# 窗口版一般都和 -console 版躺在同一个目录里；没有就跳过（-Exe 指到别处时）。
$guiExe = Join-Path (Split-Path -Parent $sx) (([System.IO.Path]::GetFileName($sx)) -replace '-console', '')
if (-not (Test-Path $guiExe)) {
    Write-Host '[--] 没找到窗口版 exe，跳过 GUI 冒烟' -ForegroundColor Yellow
}
else {
    $g = Join-Path $smoke ([System.IO.Path]::GetFileName($guiExe))
    Copy-Item $guiExe $g
    $gui = Join-Path $smoke 'gui.log'
    $p = Start-Process -FilePath $g -PassThru -WindowStyle Hidden `
        -RedirectStandardError $gui -ErrorAction SilentlyContinue
    if ($p) {
        Start-Sleep -Seconds 5
        $alive = -not $p.HasExited
        Check 'GUI（窗口版）启动后没崩' $alive
        if ($alive) {
            # ★ 必须 /T：PyInstaller onefile 是「外壳 + 干活的孩子」两个进程，
            # 只 Stop-Process 外壳会留下孩子占着 stderr 管道 ⇒ 调用方（CI/本脚本的父进程）永远等不到 EOF。
            taskkill /PID $p.Id /T /F 2>&1 | Out-Null
        }
    }
    else { Check 'GUI（窗口版）能启动' $false }
}

# ---------------------------------------------------------------- 收尾
if (-not $Keep) {
    Remove-Item (Join-Path $smoke 'work'), (Join-Path $smoke 'work-full') -Recurse -Force -ErrorAction SilentlyContinue
    # 产物是几百 MB 的 APK，验完就删（要看就加 -Keep）
    Remove-Item (Join-Path $smoke 'base.apk') -Force -ErrorAction SilentlyContinue
    Get-ChildItem $smoke -Filter 'out*.apk*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}
Write-Host ''
if ($fail -eq 0) { Write-Host '冒烟全绿。' -ForegroundColor Green; exit 0 }
Write-Host "冒烟有 $fail 项没过。" -ForegroundColor Red
exit 1
