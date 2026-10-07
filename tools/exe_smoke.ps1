# 冒烟测试：把打好的 exe 放进一个空目录，当成「玩家第一次拿到」来跑。
# 检查：零依赖启动 / 端口走 port.txt / data\ 落在 exe 旁边 / 只播种白名单 / admin 能登录 /
#       请求日志落在 exe 旁的 logs\ / 退出后不留残余进程。
#
# 用法：pwsh tools\exe_smoke.ps1 -Exe dist\TrialsFrontierServer.exe [-Port 8199]
#      pwsh tools\exe_smoke.ps1 -Exe dist\TrialsFrontierServer-nuitka.exe -Port 8201
#
# ★ 这里用 `--no-browser` 启动，免得每次冒烟都在开发机上弹一个浏览器标签；
#   自动打开管理页那条路径靠人工验一次（见 tools\README.md）。
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Exe,
    [int]$Port = 8199,
    [switch]$SkipKill
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$root = Split-Path -Parent $PSScriptRoot
if (-not [IO.Path]::IsPathRooted($Exe)) { $Exe = Join-Path $root $Exe }
if (-not (Test-Path $Exe)) { throw "找不到 exe：$Exe" }

$box = Join-Path $root 'tmp\exe\smoke'
if (Test-Path $box) { Remove-Item $box -Recurse -Force }
New-Item -ItemType Directory -Force -Path $box | Out-Null
$name = Split-Path -Leaf $Exe
Copy-Item $Exe (Join-Path $box $name)
# 端口用 port.txt 给（就是玩家双击时的方式，不传 --port）
Set-Content (Join-Path $box 'port.txt') "$Port`n" -Encoding ascii
# 故意清掉 Python 相关环境变量：证明它不靠机器上装的 Python
$env:PYTHONHOME = ''
$env:PYTHONPATH = ''
$env:PYTHONSTARTUP = ''

$out = Join-Path $box 'stdout.log'
$err = Join-Path $box 'stderr.log'
# ★ 端口必须真的是空的：Windows 上 allow_reuse_address 会让两个进程都能绑同一个端口，
#   请求却可能落到那个「上次没杀干净」的旧进程上（踩过：一个旧原型进程占着 8199，
#   登录一直 401 invalid-credentials，查了半天其实是拿别人的服务器在验口令）。
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    $who = (Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -First 1).OwningProcess
    $info = Get-Process -Id $who -ErrorAction SilentlyContinue
    throw "端口 $Port 已经被 PID $who（$($info.ProcessName) $($info.Path)）占着，先杀掉它再跑。"
}
Write-Host "== $name（空目录 $box，端口来自 port.txt=$Port）"
$p = Start-Process -FilePath (Join-Path $box $name) -ArgumentList '--no-browser' `
    -WorkingDirectory $box -RedirectStandardOutput $out -RedirectStandardError $err -PassThru

$fail = 0
function Check([string]$what, [bool]$ok, [string]$detail = '') {
    if ($ok) { Write-Host "  [OK]   $what $detail" -ForegroundColor Green }
    else { Write-Host "  [FAIL] $what $detail" -ForegroundColor Red; $script:fail++ }
}
function Wait-Port([int]$port, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { return $true }
        if ($p.HasExited) { return $false }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

$sess = $null
try {
    if (-not (Wait-Port $Port 90)) {
        $o = if (Test-Path $out) { Get-Content $out -Raw } else { '' }
        $e = if (Test-Path $err) { Get-Content $err -Raw } else { '' }
        throw "90 秒内没起来。stdout=`n$o`nstderr=`n$e"
    }
    Check 'port.txt 的端口生效' $true

    # 横幅是逐步往 stdout.log 写的：等它写完（末行是「忘了口令就重跑」），
    # 否则可能只读到半截口令 → 登录必然 401。
    $stdoutText = ''
    for ($i = 0; $i -lt 40; $i++) {
        $stdoutText = [string](Get-Content $out -Raw)
        if ($stdoutText -match '忘了口令就重跑') { break }
        Start-Sleep -Milliseconds 250
    }
    Check '控制台有横幅' ([bool]($stdoutText -match 'Trials Frontier 本地服务器已启动'))
    Check '打印了数据目录' ([bool]($stdoutText -match '数据目录：'))
    # ★ 横幅必须给出「能填进手机」的地址：0.0.0.0 只是绑定地址，旧横幅印 http://0.0.0.0:8123
    #   会把人带进沟里（有人报「192.168.x.x:8123 连不上」时查到的第一处误导）。
    Check '打印了手机/其它设备用的地址' ([bool]($stdoutText -match '手机/其它设备用：\s*http://(192\.168|10\.|172)\.'))
    Check '没把 0.0.0.0 当可用地址印出来' (-not [bool]($stdoutText -match '已启动：\s*http://0\.0\.0\.0'))
    Check '打印了连不上排查口诀' ([bool]($stdoutText -match '连不上先查三件事'))
    $pw = $null
    if ($stdoutText -match '口\s*令\s*[:：]\s*([0-9a-f]{6,})') { $pw = $Matches[1] }
    Check '首次运行打印了随机口令' ([bool]$pw) "(长度 $(@($pw)[0].Length))"

    $data = Join-Path $box 'data'
    Check '在 exe 旁建了 data\' (Test-Path $data)
    Check '播种了 tf_config.json' (Test-Path (Join-Path $data 'tf_config.json'))
    Check '播种了 wts_rewards.json' (Test-Path (Join-Path $data 'wts_rewards.json'))
    $ghosts = Join-Path $data 'ghosts'
    Check '播种了 ghosts\' (Test-Path $ghosts)
    if (Test-Path $ghosts) {
        $tracked = @(& git -C $root ls-files 'server/data/ghosts').Count
        $n = (Get-ChildItem $ghosts -Recurse -File).Count
        Check "幽灵数量 = 入库的 $tracked 个" ($n -eq $tracked) "实际 $n"
    }
    Check '没有开发机的存档 save\' (-not (Test-Path (Join-Path $data 'save')))
    Check '没有开发机的审计 config_audit.jsonl' (-not (Test-Path (Join-Path $data 'config_audit.jsonl')))
    Check '没有开发机的对局状态 pvp_state.json' (-not (Test-Path (Join-Path $data 'pvp_state.json')))
    Check 'exe 旁没有 admin\（前端在包内）' (-not (Test-Path (Join-Path $box 'admin')))
    Check 'exe 旁没有 rules.json（只读资产在包内）' (-not (Test-Path (Join-Path $box 'rules.json')))
    # 播种的是内置默认值，不是开发机手调过的那份
    $cfg = [string](Get-Content (Join-Path $data 'tf_config.json') -Raw)
    Check '播种的配置是内置默认（时长 21600）' ([bool]($cfg -match '21600'))

    $adminPage = Invoke-WebRequest "http://127.0.0.1:$Port/__admin" -UseBasicParsing -TimeoutSec 20
    Check '/__admin 200' ($adminPage.StatusCode -eq 200) "($($adminPage.RawContentLength) B)"
    # 前端必须是包内那份源码的字节数（不是解包残骸、也不是外挂目录）
    $jsWant = (Get-Item (Join-Path $root 'server\admin\app.js')).Length
    $js = Invoke-WebRequest "http://127.0.0.1:$Port/__admin/app.js" -UseBasicParsing -TimeoutSec 20
    Check "app.js 200 且 $jsWant B" ($js.StatusCode -eq 200 -and $js.RawContentLength -eq $jsWant) "($($js.RawContentLength) B)"

    if ($pw) {
        $body = @{ username = 'admin'; password = $pw } | ConvertTo-Json -Compress
        $login = Invoke-WebRequest "http://127.0.0.1:$Port/__api/admin/login" -Method Post -Body $body `
            -ContentType 'application/json' -UseBasicParsing -TimeoutSec 20 -SessionVariable s
        $sess = $s
        Check '随机口令能登录' ([bool]($login.StatusCode -eq 200 -and $login.Content -match '"ok"\s*:\s*true'))
        foreach ($api in 'bunker', 'weekly', 'social') {
            $r = Invoke-WebRequest "http://127.0.0.1:$Port/__api/admin/$api" -UseBasicParsing `
                -WebSession $sess -TimeoutSec 20
            Check "后台接口 /$api 200" ($r.StatusCode -eq 200)
        }
    }
    Check '没往 stderr 吐异常' ([bool]("$(Get-Content $err -Raw)".Trim().Length -eq 0))
    # ★ 管理后台的请求不走请求日志（那是客户端流量的账本），要验日志得打一个客户端接口。
    # ★ 专门带上 /v2/profiles/me/friends：这条已经**不是** rules.json 里的死桩了（2026-10-07
    #   起由 pick_dynamic 动态路由按登录者查 data/friends.json），打它等于同时验证包里的
    #   只读 rules.json 与动态路由在冻结态下都还活着 —— 坏了客户端就看不到好友列表。
    foreach ($u in '/', '/public/pvp_matches/v1/matches', '/v2/profiles/me/friends') {
        $r = Invoke-WebRequest "http://127.0.0.1:$Port$u" -UseBasicParsing -TimeoutSec 20
        Check "客户端接口 $u 200" ($r.StatusCode -eq 200)
    }
    $reqlog = Join-Path $box 'logs\requests.jsonl'
    Check '日志落到 exe 旁的 logs\requests.jsonl' (Test-Path $reqlog)
    if (Test-Path $reqlog) {
        $rows = @(Get-Content $reqlog | ForEach-Object { $_ | ConvertFrom-Json })
        $paths = @($rows | ForEach-Object { $_.path })
        Check '日志里记到了客户端请求' ($paths -contains '/public/pvp_matches/v1/matches') "($($paths.Count) 行)"
        Check '日志里记到了好友列表请求' ($paths -contains '/v2/profiles/me/friends')
        # ★ 「他的包到底到没到」只能靠这两条回答：来源 IP 进日志 + /__ping 留痕。
        $clients = @($rows | ForEach-Object { "$($_.client)" })
        Check '日志条目带来源 IP' (-not ($clients -contains '') -and ($clients -contains '127.0.0.1')) `
            "(client=$([string]::Join(',', ($clients | Select-Object -Unique))))"
    }
    $pong = Invoke-WebRequest "http://127.0.0.1:$Port/__ping" -UseBasicParsing -TimeoutSec 20
    Check '/__ping 返回 pong' ($pong.StatusCode -eq 200 -and $pong.Content -match 'pong')
    $stdout2 = [string](Get-Content $out -Raw)
    Check '/__ping 在控制台留了来源 IP' ([bool]($stdout2 -match '127\.0\.0\.1\s+PING\s+pong'))
}
finally {
    if (-not $SkipKill) {
        # ★ PyInstaller 的 onefile 会自己 fork 一个子进程干活，Stop-Process 只杀得掉外壳，
        #   子进程会继续占着端口 —— 必须整棵树一起杀。
        & taskkill /PID $p.Id /T /F 2>&1 | Out-Null
        Start-Sleep -Milliseconds 800
        $left = Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and $_.Path.StartsWith($box, 'OrdinalIgnoreCase')
        }
        Check '退出后没留残余进程' (@($left).Count -eq 0) "$(@($left | Select-Object -Expand Id) -join ',')"
    }
}
Write-Host ''
if ($fail) { Write-Host "冒烟失败 $fail 项" -ForegroundColor Red; exit 1 }
Write-Host '冒烟全绿' -ForegroundColor Green
