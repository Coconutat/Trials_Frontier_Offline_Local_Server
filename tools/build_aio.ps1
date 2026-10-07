# 把「AIO 补丁器」（tools/tfpatch_aio）打包成零依赖 exe。
#
# 产物：
#   dist\TrialsFrontierPatcher.exe          —— 双击出图形界面（无控制台窗口）
#   dist\TrialsFrontierPatcher-console.exe  —— 带控制台，命令行 / 排错用
#
# 目标机器不需要装 Python、不需要装任何 pip 包。**但仍然需要**（缺一不可）：
#   * Android SDK build-tools 里的 zipalign / apksigner（见 tools/README.md）
#   * 一个 JDK（apksigner 要 java，签名密钥不存在时还要 keytool）
# 这两样是「给 APK 签名」绕不过去的外部依赖，不塞进 exe（几十 MB，且版本要跟
# 用户的设备对上）。签名仍然走系统 apksigner，不自研签名器。
#
# 用法：
#   pwsh tools\build_aio.ps1                 # 两个都出
#   pwsh tools\build_aio.ps1 -Mode windowed  # 只要 GUI 版
#   pwsh tools\build_aio.ps1 -SkipTests

[CmdletBinding()]
param(
    [ValidateSet('windowed', 'console', 'both')][string]$Mode = 'both',
    [string]$Name = 'TrialsFrontierPatcher',
    [string]$Python = '',
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$distDir = Join-Path $root 'dist'
$workDir = Join-Path $root 'tmp\aio\build'
$entry = Join-Path $root 'tools\aio_launcher.py'

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    $Python = if ($cmd) { $cmd.Source } else { 'C:\Python314\python.exe' }
}
if (-not (Test-Path $Python)) { throw "找不到 Python：$Python" }
if (-not (Test-Path $entry)) { throw "找不到入口脚本：$entry" }
$pyver = & $Python -c "import sys;print(sys.version.split()[0])"
Write-Host "Python $pyver ($Python)" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $distDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root 'tmp\aio') | Out-Null

# ★ 随包的 assets（预编好的 payload_setup.dex）：运行期不需要 javac/d8，
#   全靠这个 dex 把离线载荷装进 /data/data。缺了它自包含打包会失败。
$assets = Join-Path $root 'tools\tfpatch_aio\assets'
if (-not (Test-Path (Join-Path $assets 'payload_setup.dex'))) {
    throw "缺少随包 dex：$assets\payload_setup.dex"
}

if (-not $SkipTests) {
    Write-Host '[1/3] 跑回归（打包不应该改变任何行为）…' -ForegroundColor Cyan
    & $Python -m unittest discover -s (Join-Path $root 'tests') 2>&1 | Select-Object -Last 3 |
        ForEach-Object { "      $_" }
}

function New-OneFile {
    param([string]$Kind)

    $suffix = if ($Kind -eq 'console') { '-console.exe' } else { '.exe' }
    $mode = if ($Kind -eq 'console') { '--console' } else { '--windowed' }
    Write-Host "[2/3] PyInstaller onefile（$Kind）…" -ForegroundColor Cyan
    $log = Join-Path $root "tmp\aio\pyinstaller-$Kind.log"

    # --collect-all keystone：keystone.dll 是二进制，PyInstaller 默认不会带上；
    #   漏了它 patch_dynaddr（注入 tf_server.txt 钩子）在目标机上直接 ImportError。
    & $Python -m PyInstaller --onefile --noconfirm --clean $mode `
        --name "$Name$suffix" --distpath $distDir --workpath (Join-Path $workDir $Kind) `
        --specpath $workDir --paths $root `
        --add-data "$assets;tfpatch_aio\assets" `
        --collect-all keystone --hidden-import elftools `
        $entry 2>&1 | Tee-Object -FilePath $log | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（日志：$log）" }

    $exe = Join-Path $distDir "$Name$suffix"
    if (-not (Test-Path $exe)) { throw "没生成产物：$exe（日志：$log）" }
    return $exe
}

$built = @()
if ($Mode -eq 'windowed' -or $Mode -eq 'both') { $built += New-OneFile 'windowed' }
if ($Mode -eq 'console' -or $Mode -eq 'both') { $built += New-OneFile 'console' }

# ------------------------------------------------------------------ 3 自检
Write-Host '[3/3] 冒烟 + 校验和…' -ForegroundColor Cyan
$lines = @()
foreach ($exe in $built) {
    $leaf = Split-Path -Leaf $exe
    $h = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    $lines += "$h  $leaf"
    Write-Host ("      {0}  {1} MB  sha256={2}" -f $leaf, $mb, $h.Substring(0, 16)) -ForegroundColor Green
    "$h  $leaf" | Set-Content "$exe.sha256" -Encoding ascii -NoNewline
}

# 控制台版才有 stdout：用它跑真自检（列功能 + 环境自检），窗口版只验能启动。
$probe = $built | Where-Object { $_ -like '*console.exe' } | Select-Object -First 1
if ($probe) {
    Write-Host "      自检 $([System.IO.Path]::GetFileName($probe))"
    & $probe --list-features | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "自检失败：--list-features 退出码 $LASTEXITCODE" }
    & $probe --check | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "自检失败：--check 退出码 $LASTEXITCODE" }
}

# SHA256SUMS.txt：同名行替换，不重复追加
$sums = Join-Path $distDir 'SHA256SUMS.txt'
$old = if (Test-Path $sums) { Get-Content $sums } else { @() }
$names = $lines | ForEach-Object { ($_ -split '  ')[1] }
$keep = $old | Where-Object { $_ -and (((($_ -split '  ')[1])) -notin $names) }
(($keep + $lines) | Where-Object { $_ }) | Set-Content $sums -Encoding utf8
Write-Host "      已更新 $sums" -ForegroundColor Green

Write-Host ''
Write-Host '完成。把 exe 和（要出自包含 APK 时的）payload 文件夹放在同一个目录里即可：' -ForegroundColor Cyan
Write-Host '  payload\  ← 里面要有 appdata\ 和 obb\（就是解开的 TrialsFrontier-clean-pack）' -ForegroundColor Cyan
