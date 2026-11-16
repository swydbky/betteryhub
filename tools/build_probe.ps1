# 手工构建探针 APK —— 不依赖 Gradle，只用 aapt2 / javac / d8 / zipalign / apksigner。
# 这样绕开了 sdkmanager（它在本机拉不到仓库清单）和 Gradle 的依赖下载。
#
# 用法:  powershell -ExecutionPolicy Bypass -File tools\build_probe.ps1

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent

$sdk  = Join-Path $Root 'vendor\android-sdk'
$jdk  = (Get-ChildItem (Join-Path $Root 'vendor') -Directory | Where-Object { $_.Name -like 'jdk*' } | Select-Object -First 1).FullName
$bt   = (Get-ChildItem (Join-Path $sdk 'build-tools') -Directory | Select-Object -First 1).FullName
$aj   = Join-Path $sdk 'platforms\android-35\android.jar'
$proj = Join-Path $Root 'android\probe'
$out  = Join-Path $Root 'android\out'

foreach ($p in @($jdk, $bt, $aj, (Join-Path $proj 'AndroidManifest.xml'))) {
    if (-not (Test-Path $p)) { throw "缺少: $p" }
}

New-Item -ItemType Directory -Force -Path $out, (Join-Path $out 'classes'), (Join-Path $out 'dex') | Out-Null
Remove-Item (Join-Path $out 'classes\*') -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $out 'dex\*') -Recurse -Force -ErrorAction SilentlyContinue

$env:JAVA_HOME = $jdk
$env:PATH = "$jdk\bin;" + $env:PATH

Write-Host "[1/6] 生成地址资源 + aapt2 link"
# 地址清单不放进仓库：从 hub_urls.txt（gitignore）读取，回退到 example
$urlsFile = Join-Path $proj 'hub_urls.txt'
$urlsEx = Join-Path $proj 'hub_urls.example.txt'
$src = if (Test-Path $urlsFile) { $urlsFile } else { $urlsEx }
$urls = ((Get-Content $src -Encoding UTF8) | Where-Object { $_ -and -not $_.TrimStart().StartsWith('#') }) -join ','
$stringsXml = @"
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="hub_urls" translatable="false">$urls</string>
</resources>
"@
[IO.File]::WriteAllText((Join-Path $proj 'res\values\strings.xml'), $stringsXml,
    (New-Object Text.UTF8Encoding($false)))

$resDir = Join-Path $proj 'res'
$resZip = Join-Path $out 'res.zip'
if (Test-Path $resDir) {
    & (Join-Path $bt 'aapt2.exe') compile --dir $resDir -o $resZip
    if ($LASTEXITCODE -ne 0) { throw "aapt2 compile 失败" }
    & (Join-Path $bt 'aapt2.exe') link -o (Join-Path $out 'base.apk') `
        --manifest (Join-Path $proj 'AndroidManifest.xml') `
        -I $aj --min-sdk-version 31 --target-sdk-version 35 --auto-add-overlay $resZip
} else {
    & (Join-Path $bt 'aapt2.exe') link -o (Join-Path $out 'base.apk') `
        --manifest (Join-Path $proj 'AndroidManifest.xml') `
        -I $aj --min-sdk-version 31 --target-sdk-version 35
}
if ($LASTEXITCODE -ne 0) { throw "aapt2 失败" }

Write-Host "[2/6] javac"
$srcs = Get-ChildItem (Join-Path $proj 'src') -Recurse -Filter *.java | ForEach-Object { $_.FullName }
& (Join-Path $jdk 'bin\javac.exe') -source 8 -target 8 -bootclasspath $aj `
    -encoding UTF-8 -nowarn -d (Join-Path $out 'classes') $srcs
if ($LASTEXITCODE -ne 0) { throw "javac 失败" }

Write-Host "[3/6] jar + d8"
& (Join-Path $jdk 'bin\jar.exe') cf (Join-Path $out 'classes.jar') -C (Join-Path $out 'classes') .
if ($LASTEXITCODE -ne 0) { throw "jar 失败" }
& (Join-Path $bt 'd8.bat') --lib $aj --min-api 31 --output (Join-Path $out 'dex') (Join-Path $out 'classes.jar')
if ($LASTEXITCODE -ne 0) { throw "d8 失败" }

Write-Host "[4/6] 把 classes.dex 塞进 apk"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$apk = Join-Path $out 'base.apk'
$zip = [System.IO.Compression.ZipFile]::Open($apk, 'Update')
try {
    $dex = Join-Path $out 'dex\classes.dex'
    if (-not (Test-Path $dex)) { throw "没有生成 classes.dex" }
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $dex, 'classes.dex') | Out-Null
} finally { $zip.Dispose() }

Write-Host "[5/6] zipalign + 签名"
& (Join-Path $bt 'zipalign.exe') -f -p 4 $apk (Join-Path $out 'aligned.apk')
if ($LASTEXITCODE -ne 0) { throw "zipalign 失败" }

$ks = Join-Path $out 'debug.keystore'
if (-not (Test-Path $ks)) {
    & (Join-Path $jdk 'bin\keytool.exe') -genkeypair -keystore $ks -alias androiddebugkey `
        -storepass android -keypass android -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US"
}

& (Join-Path $bt 'apksigner.bat') sign --ks $ks --ks-pass pass:android --key-pass pass:android `
    --out (Join-Path $out 'probe.apk') (Join-Path $out 'aligned.apk')
if ($LASTEXITCODE -ne 0) { throw "apksigner 失败" }

Write-Host "[6/6] 完成"
$final = Join-Path $out 'probe.apk'
Write-Host ("APK: {0}  ({1} KB)" -f $final, [math]::Round((Get-Item $final).Length / 1KB, 1))
