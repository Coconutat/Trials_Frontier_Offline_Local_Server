# 把服务器打包成「零依赖单文件 exe」（用户 m09238 / m09240）。
#
# 产物：dist\<名字>.exe —— 目标机器不需要装 Python、不需要装任何包；
#       双击即在 exe 所在目录建 data\（存档、tf_config.json、幽灵库、日志都在这儿）。
#
# ★ 白名单是安全边界：只打包「源码 + admin 前端 + rules.json + 奖励表 + 已入库的静态幽灵」。
#   真机存档（server\data\save\）、管理员口令哈希（admin.json）、对局状态、登录会话、
#   审计与日志**一律不进包**（脚本末尾会硬性检查，命中就中止）。
#
# 用法：
#   pwsh tools\build_exe.ps1                     # PyInstaller onefile（默认）
#   pwsh tools\build_exe.ps1 -Packer nuitka      # Nuitka 真编译（自动找 MSVC）
#   pwsh tools\build_exe.ps1 -Packer both        # 两个都出，方便比体积/启动
#
# ★ 编译器：Nuitka 4.2.2 **在 Python ≥3.13 上不允许用 MinGW**（官方解释器是 MSVC ABI），
#   报错原文 `FATAL: Error, cannot use '--mingw64' on Python version 3.13 or higher.`
#   所以默认让 Nuitka 自己找 MSVC（Visual Studio 生成工具）；`-MinGW` 只在 Python ≤3.12 有意义。
#
# 反逆向：PyInstaller 只是把字节码压缩塞进 exe（能解出来），Nuitka 是真编译成机器码。
# 两者都请把「防止逆向」理解为抬高成本，不是安全边界：详见 PUBLISHING.md。

[CmdletBinding()]
param(
    [ValidateSet('pyinstaller', 'nuitka', 'both')][string]$Packer = 'pyinstaller',
    [string]$Name = 'TrialsFrontierServer',
    [string]$Python = '',
    [string]$MinGW = '',
    [switch]$SkipTests,
    [switch]$KeepStage
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $root 'tmp\exe\stage'
$distDir = Join-Path $root 'dist'
$workDir = Join-Path $root 'tmp\exe\build'

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    $Python = if ($cmd) { $cmd.Source } else { 'C:\Python314\python.exe' }
}
if (-not (Test-Path $Python)) { throw "找不到 Python：$Python" }
$pyver = & $Python -c "import sys;print(sys.version.split()[0])"
Write-Host "Python $pyver ($Python)" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. 暂存白名单
Write-Host "[1/4] 暂存要打包的文件（只挑白名单）…" -ForegroundColor Cyan
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'data') | Out-Null
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

Copy-Item (Join-Path $root 'server\admin') (Join-Path $stage 'admin') -Recurse
Copy-Item (Join-Path $root 'server\rules.json') (Join-Path $stage 'rules.json')
Copy-Item (Join-Path $root 'server\data\wts_rewards.json') (Join-Path $stage 'data\wts_rewards.json')

# 幽灵只拷 git 里已入库的那些：开发机上 server\data\ghosts 还混着真机上传的幽灵，
# 整目录拷会把玩家的幽灵一起发出去。
$ghosts = & git -C $root ls-files 'server/data/ghosts'
if ($LASTEXITCODE -ne 0) { throw 'git ls-files 失败（打包脚本需要 git 仓库）' }
$ghostCount = 0
foreach ($rel in $ghosts) {
    if (-not $rel) { continue }
    $src = Join-Path $root ($rel -replace '/', '\')
    $dst = Join-Path $stage ($rel -replace '^server/data/', 'data/' -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item $src $dst
    $ghostCount++
}

$manifest = Get-ChildItem $stage -Recurse -File | ForEach-Object { $_.FullName.Substring($stage.Length + 1) }
$manifest | Set-Content (Join-Path $root 'tmp\exe\stage-manifest.txt') -Encoding utf8
Write-Host "      暂存 $($manifest.Count) 个文件（其中幽灵 $ghostCount 个）"

# ---------------------------------------------------------------- 2. 硬性检查
Write-Host "[2/4] 安全检查（私有数据一个都不许进包）…" -ForegroundColor Cyan
$forbidden = @('admin.json', 'accounts.json', 'sessions.json', 'devices.json', 'remember.json',
    'bindings.json', 'pvp_state.json', 'leaderboards.json', 'config_audit.jsonl', 'tf_config.json',
    'player_levels.json', 'templates.json', 'save', 'server.log', 'server.err.log')
$hit = $manifest | Where-Object {
    $leaf = Split-Path -Leaf $_
    ($forbidden -contains $leaf) -or ($_ -match '(^|\\)(save|logs)(\\|$)')
}
if ($hit) {
    throw ("暂存目录里混进了私有数据，已中止：`n  " + ($hit -join "`n  "))
}
Write-Host '      干净：没有存档/口令/对局状态/日志' -ForegroundColor Green

# ---------------------------------------------------------------- 3. 打包
function New-OneFile {
    param([string]$Which)
    if ($Which -eq 'pyinstaller') {
        Write-Host '[3/4] PyInstaller onefile …' -ForegroundColor Cyan
        & $Python -m PyInstaller --noconfirm --onefile --console --name $Name `
            --distpath $distDir --workpath (Join-Path $workDir 'pyinstaller') `
            --specpath (Join-Path $root 'tmp\exe') --paths (Join-Path $root 'server') `
            --add-data "$stage\admin;admin" --add-data "$stage\rules.json;." `
            --add-data "$stage\data;data" `
            (Join-Path $root 'server\tf_server.py')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败' }
        return (Join-Path $distDir "$Name.exe")
    }

    Write-Host '[3/4] Nuitka onefile（真编译，需要 C 编译器）…' -ForegroundColor Cyan
    $ccArgs = @()
    if ($MinGW) {
        if (-not (Test-Path $MinGW)) { throw "找不到 MinGW：$MinGW" }
        $minor = [int]($pyver.Split('.')[1])
        if ([int]($pyver.Split('.')[0]) -ge 3 -and $minor -ge 13) {
            Write-Host "      忽略 -MinGW：Nuitka 不支持在 Python $pyver 上用 MinGW，改用 MSVC" -ForegroundColor Yellow
        }
        else {
            $env:PATH = "$MinGW;$env:PATH"
            $ccArgs = @('--mingw64')
            Write-Host "      用 MinGW：$MinGW"
        }
    }
    elseif (-not $env:CC -and -not $env:CL) {
        $cl = Get-ChildItem 'C:\Program Files*\Microsoft Visual Studio\*\BuildTools\VC\Tools\MSVC\*\bin\Hostx64\x64\cl.exe' `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cl) { Write-Host "      用 MSVC：$($cl.FullName)" }
        else { Write-Host '      没找到 MSVC：Nuitka 会自己找，找不到就装「Visual Studio 生成工具」的 C++ 负载' -ForegroundColor Yellow }
    }
    # ★ 用 --include-raw-dir，**不要**用 --include-data-dir：Nuitka 的 data-dir 会按
    #   `default_ignored_suffixes` 静默跳过「看起来像代码」的后缀，那张表里有 `.bin` ——
    #   幽灵库全是 `ghost_*.bin`，用 --include-data-dir 会整批丢掉（真机踩过：冒烟
    #   「幽灵数量 = 入库的 46 个 实际 2」）。staging 目录本身就是白名单，Nuitka 不必再过滤。
    $nlog = Join-Path $root 'tmp\exe\nuitka.log'
    & $Python -m nuitka --onefile @ccArgs --assume-yes-for-downloads `
        --python-flag=-OO --lto=yes --remove-output --windows-console-mode=force `
        --output-dir=$distDir --output-filename="$Name-nuitka.exe" `
        --include-raw-dir="$stage\admin=admin" --include-raw-dir="$stage\data=data" `
        --include-data-files="$stage\rules.json=rules.json" `
        (Join-Path $root 'server\tf_server.py') 2>&1 | Tee-Object -FilePath $nlog | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Nuitka 编译失败' }
    # Nuitka 对文件少的目录逐个打印 `Included data file '…'`，文件多时只打一行
    # `Included 47 data files due to specified raw dir '…'`，两种都要数。
    $included = @(Select-String -Path $nlog -Pattern "Included data file '" -AllMatches).Count
    foreach ($m in (Select-String -Path $nlog -Pattern 'Included (\d+) data files? due to' -AllMatches)) {
        foreach ($mm in $m.Matches) { $included += [int]$mm.Groups[1].Value }
    }
    Write-Host "      内嵌数据文件 $included 个（暂存 $($manifest.Count) 个）"
    if ($included -lt $manifest.Count) {
        throw ("Nuitka 少内嵌了 $($manifest.Count - $included) 个数据文件，产物是残的" +
            "（日志：$nlog）。多半是又踩到按后缀过滤的坑，检查要不要 --include-raw-dir。")
    }
    return (Join-Path $distDir "$Name-nuitka.exe")
}

if (-not $SkipTests) {
    Write-Host '      跑回归（打包不应该改变任何行为）…'
    & $Python -m unittest discover -s (Join-Path $root 'tests') 2>&1 | Select-Object -Last 3 |
        ForEach-Object { "      $_" }
}

$built = @()
if ($Packer -eq 'pyinstaller' -or $Packer -eq 'both') { $built += New-OneFile 'pyinstaller' }
if ($Packer -eq 'nuitka' -or $Packer -eq 'both') { $built += New-OneFile 'nuitka' }

# ---------------------------------------------------------------- 4. 校验和 / 签名
Write-Host '[4/4] 校验和…' -ForegroundColor Cyan
$lines = @()
foreach ($exe in $built) {
    if (-not (Test-Path $exe)) { throw "没生成产物：$exe" }
    $h = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    $lines += "$h  $(Split-Path -Leaf $exe)"
    Write-Host ("      {0}  {1} MB  sha256={2}" -f (Split-Path -Leaf $exe), $mb, $h.Substring(0, 16)) `
        -ForegroundColor Green
}
$lines | Set-Content (Join-Path $distDir 'SHA256SUMS.txt') -Encoding ascii

# 有正规代码签名证书时顺手签上（防「别人往你的 exe 里塞木马再转发」）。
# 自签名证书不算解法：Windows 照样报「未知发布者」，只会更吓人。
if ($env:TF_SIGN_PFX) {
    $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signtool) {
        Write-Host '      跳过签名：找不到 signtool.exe（装 Windows SDK 后重跑）' -ForegroundColor Yellow
    }
    else {
        foreach ($exe in $built) {
            & $signtool sign /f $env:TF_SIGN_PFX /p $env:TF_SIGN_PASSWORD /fd SHA256 $exe
            if ($LASTEXITCODE -ne 0) { throw "签名失败：$exe" }
            Write-Host "      已签名：$(Split-Path -Leaf $exe)" -ForegroundColor Green
        }
    }
}
else {
    Write-Host '      未签名（要签名就设 $env:TF_SIGN_PFX / $env:TF_SIGN_PASSWORD）' -ForegroundColor DarkGray
}

if (-not $KeepStage) { Remove-Item $stage -Recurse -Force }
Write-Host ''
Write-Host '完成。用法：把 exe 拷到任意目录（别放 C:\Program Files）双击运行，' -ForegroundColor Cyan
Write-Host '它会自己建 data\ 存存档与配置，控制台会打印手机要用的局域网地址。' -ForegroundColor Cyan
