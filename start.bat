@echo off
chcp 65001 >nul
title 股票估值系统 - 一键启动
cd /d "%~dp0"

echo ==========================================
echo   股票估值系统 一键启动（A股·美股·港股）
echo ==========================================
echo.

rem ---- 环境检查 ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python。请安装 https://www.python.org/downloads/
    echo        安装时务必勾选 "Add python.exe to PATH"，装完后重新双击本文件。
    pause
    exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Node.js。请安装 https://nodejs.org/ 的 LTS 版本，装完后重新双击本文件。
    pause
    exit /b 1
)

rem ---- 后端依赖（已装过则跳过）----
python -c "import fastapi, uvicorn, sqlalchemy, pydantic_settings" >nul 2>nul
if errorlevel 1 (
    echo [1/4] 首次运行：安装后端依赖（约 1-2 分钟）...
    python -m pip install -r backend\requirements.txt -q
    if errorlevel 1 (
        echo       官方源较慢，改用清华镜像重试...
        python -m pip install -r backend\requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    )
) else (
    echo [1/4] 后端依赖已就绪
)

rem ---- 启动后端 ----
echo [2/4] 启动后端 API（会弹出一个新窗口，使用期间请勿关闭）...
pushd backend
start "估值系统-后端(勿关)" cmd /k python -m uvicorn app.main:app --port 8000
popd

rem ---- 前端依赖（已装过则跳过）----
if not exist "frontend\node_modules" (
    echo [3/4] 首次运行：安装前端依赖（约 2-5 分钟，请耐心等待）...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo       官方源较慢，改用国内镜像重试...
        call npm install --registry=https://registry.npmmirror.com
    )
    popd
) else (
    echo [3/4] 前端依赖已就绪
)

rem ---- 启动前端 ----
echo [4/4] 启动前端（会弹出一个新窗口，使用期间请勿关闭）...
pushd frontend
start "估值系统-前端(勿关)" cmd /k npm run dev
popd

rem ---- 等后端就绪后打开浏览器 ----
echo.
echo 等待服务启动（首次启动会自动导入 9 家样例公司数据）...
set /a tries=0
:wait_backend
set /a tries+=1
curl -s -o nul http://localhost:8000/health 2>nul
if not errorlevel 1 goto backend_ready
if %tries% geq 45 goto backend_ready
timeout /t 2 /nobreak >nul
goto wait_backend
:backend_ready

timeout /t 3 /nobreak >nul
start http://localhost:3000

echo.
echo ==========================================
echo   启动完成！浏览器已打开 http://localhost:3000
echo   如页面暂时报错，等几秒刷新一下即可。
echo   退出系统：关闭弹出的"后端""前端"两个黑色窗口。
echo   下次使用：直接双击本文件，几秒即可启动。
echo ==========================================
pause
