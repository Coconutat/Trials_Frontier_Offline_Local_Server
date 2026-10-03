# 打包流水线：内嵌原版 APK + native 替换 + 清单替换 -> zipalign -> 签名
# 用法:
#   pwsh -File tools\make_apk.ps1 -Name m3
#   pwsh -File tools\make_apk.ps1 -Name m4 -Manifest tmp\m4\AndroidManifest.xml -Extra @('lib/arm64-v8a/libTrialsGo.so=tmp\m4\libTrialsGo.so')
param(
  [Parameter(Mandatory=$true)][string]$Name,
  [string]$Manifest = '',
  [string[]]$Extra = @(),
  [string]$Base = 'tmp\extract\aUiMEPVatQ.apk',
  [string]$NativeDir = 'tmp\m2',
  [string]$KeyStore = 'work\trials-frontier\keystore\trials.jks',
  [string]$Alias = 'trials',
  [string]$StorePass = $env:TF_STOREPASS,
  [switch]$SkipSign
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$BT = 'C:\Users\<user>\AppData\Local\Android\Sdk\build-tools\36.0.0'
$unaligned = "tmp\build\tf-$Name-unsigned.apk"
$aligned   = "tmp\build\tf-$Name-aligned.apk"
$final     = "tmp\build\tf-$Name.apk"

$args = @('tools\build_apk.py', '--base', $Base, '--out', $unaligned)
foreach ($lib in @('libTrialsGo','libubiservices','libplayground')) {
  $p = "$NativeDir\$lib.so"
  if (Test-Path $p) { $args += @('--replace', "lib/arm64-v8a/$lib.so=$p") }
}
if ($Manifest -ne '') { $args += @('--replace', "AndroidManifest.xml=$Manifest") }
foreach ($e in $Extra) { $args += @('--replace', $e) }
$args += @('--drop-prefix', 'lib/armeabi-v7a/')

Write-Host ">>> build_apk" -ForegroundColor Cyan
python @args
if ($LASTEXITCODE -ne 0) { throw "build_apk 失败 ($LASTEXITCODE)" }

Write-Host ">>> zipalign" -ForegroundColor Cyan
& "$BT\zipalign.exe" -p -f 4 $unaligned $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign 失败 ($LASTEXITCODE)" }

if ($SkipSign) { Write-Host "已跳过签名: $aligned"; exit 0 }

Write-Host ">>> apksigner" -ForegroundColor Cyan
& "$BT\apksigner.bat" sign --ks $KeyStore --ks-key-alias $Alias `
  --ks-pass "pass:$StorePass" --key-pass "pass:$StorePass" `
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true `
  --out $final $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner 失败 ($LASTEXITCODE)" }

& "$BT\apksigner.bat" verify --print-certs $final
Get-Item $final | Select-Object FullName, Length
