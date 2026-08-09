@echo off
REM ============================================================
REM SmartNoteGen 一键安装脚本（Windows）
REM 用途：创建 venv + 安装运行/开发依赖 + 可编辑安装项目
REM 用法：在项目根目录执行  scripts\install.bat
REM ============================================================
setlocal
cd /d "%~dp0.."

echo [1/4] 创建虚拟环境 venv ...
if not exist venv (
    python -m venv venv
    if errorlevel 1 goto :fail
) else (
    echo       已存在 venv，跳过
)

echo [2/4] 安装运行依赖 requirements/base.txt ...
call venv\Scripts\python.exe -m pip install --upgrade pip
call venv\Scripts\python.exe -m pip install -r requirements\base.txt
if errorlevel 1 goto :fail

echo [3/4] 安装开发依赖 requirements/dev.txt（可选，用于测试/覆盖率）...
call venv\Scripts\python.exe -m pip install -r requirements\dev.txt
if errorlevel 1 goto :fail

echo [4/4] 可编辑安装 smartnotegen ...
call venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 goto :fail

echo.
echo ✅ 安装完成！请确认以下外部资源：
echo   - module\fluidsynth\bin\fluidsynth.exe（FluidSynth win64，含 libfluidsynth-3.dll / SDL3.dll / sndfile.dll）
echo   - module\GeneralUser_GS\GeneralUser-GS\GeneralUser-GS.sf2（默认音色库 A）
echo   - module\GeneralUser_GS\ColomboGMGS2_SF2\ColomboGMGS2.sf2（备选音色库 B）
echo.
echo 快速验证：
echo   venv\Scripts\smartnotegen.exe --help
echo   venv\Scripts\smartnotegen.exe pipeline
goto :eof

:fail
echo.
echo ❌ 安装失败，请检查上方错误信息。
exit /b 1
