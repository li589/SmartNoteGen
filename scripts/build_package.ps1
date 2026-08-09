# ============================================================
# SmartNoteGen 打包脚本（Windows / PyInstaller）
# 用法：在 PowerShell 中执行  powershell -ExecutionPolicy Bypass -File scripts\build_package.ps1
# 产物：dist\smartnotegen.exe（可分发 CLI）
#
# 重要：module/ 资源（fluidsynth 二进制 + SoundFont）不随单文件 exe 内嵌，
# 必须与 exe 同目录分发，并保持相对路径不变：
#   dist\smartnotegen.exe
#   dist\module\fluidsynth\bin\fluidsynth.exe（含 libfluidsynth-3.dll / SDL3.dll / sndfile.dll）
#   dist\module\GeneralUser_GS\GeneralUser-GS\GeneralUser-GS.sf2
#   dist\module\GeneralUser_GS\ColomboGMGS2_SF2\ColomboGMGS2.sf2
# 否则执行 render/pipeline 会报「渲染环境不完整（错误码 7）」。
# ============================================================
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[1/4] 检查 PyInstaller ..."
& .\venv\Scripts\python.exe -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    & .\venv\Scripts\python.exe -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "安装 PyInstaller 失败" }
}

Write-Host "[2/4] 打包 smartnotegen ..."
& .\venv\Scripts\python.exe -m PyInstaller `
    --onefile `
    --name smartnotegen `
    --paths src `
    --collect-submodules smartnotegen `
    src\smartnotegen\__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

Write-Host "[3/4] 复制 module 资源（fluidsynth + SoundFont，保持相对路径）..."
$Dist = Join-Path $Root "dist"
if (Test-Path (Join-Path $Root "module")) {
    Copy-Item -Recurse -Force (Join-Path $Root "module") (Join-Path $Dist "module")
} else {
    Write-Host "警告: 项目根下未找到 module/ 目录，产物将不含渲染资源（需自行补装）。"
}

Write-Host "[4/4] 生成资源说明 README-EXE.txt ..."
@"
SmartNoteGen 单文件 CLI 分发说明
================================
1. 运行: dist\smartnotegen.exe --help
2. 本产物为单文件 exe，但渲染依赖外部资源，需保持以下相对路径：
   - dist\module\fluidsynth\bin\fluidsynth.exe （含 libfluidsynth-3.dll / SDL3.dll / sndfile.dll）
   - dist\module\GeneralUser_GS\GeneralUser-GS\GeneralUser-GS.sf2
   - dist\module\GeneralUser_GS\ColomboGMGS2_SF2\ColomboGMGS2.sf2
3. 缺失资源时 render/pipeline 报「渲染环境不完整（错误码 7）」并给出修复指引。
4. 配置 [paths] 支持相对项目根（即 exe 所在目录）解析，见 config\default.toml。
"@ | Set-Content -Encoding UTF8 (Join-Path $Dist "README-EXE.txt")

Write-Host "✅ 打包完成：dist\smartnotegen.exe"
Write-Host "   验证: dist\smartnotegen.exe --help"
