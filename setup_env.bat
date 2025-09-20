@echo off
setlocal EnableExtensions
pushd "%~dp0"

REM ================= 用户参数 =================
set "VENV_DIR=venv"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
REM （可注释）UTF-8 控制台，中文更友好
chcp 65001 >nul

set "PY_CMD="
set "HAD_ERROR=0"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_ACT=%VENV_DIR%\Scripts\activate.bat"

echo(
echo ============================================================
echo(【0】脚本开始：setup_env.bat
echo(    目标：创建 "%VENV_DIR%"（Python 3.12）并安装依赖（清华源）
echo(    说明：报错也不会退出窗口；所有安装均明确指向 venv。
echo ============================================================
echo(

echo(【1】检查并锁定 Python 3.12 解释器...
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 -V >nul 2>&1 && set "PY_CMD=py -3.12"
)
if not defined PY_CMD (
  where python >nul 2>&1
  if errorlevel 1 (
    echo([错误] 未找到 Python；请安装 Python 3.12 或 Windows Python Launcher。
    set "HAD_ERROR=1"
  ) else (
    for /f "tokens=1,* delims= " %%A in ('python -V 2^>^&1') do (
      echo(    已检测：%%A %%B
      echo(%%A %%B | findstr /R /C:" 3\.12\." >nul 2>&1 && set "PY_CMD=python"
    )
    if not defined PY_CMD (
      echo([错误] 当前 python 不是 3.12；建议安装 3.12 或使用 py -3.12。
      set "HAD_ERROR=1"
    )
  )
)
if defined PY_CMD echo(    → 使用解释器：%PY_CMD%
echo(

echo(【2】检查是否存在 venv："%VENV_DIR%"
if exist "%VENV_PY%" (
  echo(    已检测到 venv
  set "ANS="
  set /p ANS="    是否删除并重建？输入 Y 或 N 回车（默认 N）： "
  if "%ANS%"=="" set "ANS=N"
  set "ANS=%ANS:~0,1%"
  if /I "%ANS%"=="Y" (
    echo(    → 删除旧 venv ...
    rmdir /S /Q "%VENV_DIR%"
    if errorlevel 1 (
      echo([错误] 删除失败，可能被占用或权限不足。
      set "HAD_ERROR=1"
    )
  ) else (
    echo(    → 保留现有 venv
  )
) else (
  echo(    未检测到 venv，将新建。
)
echo(

if not exist "%VENV_PY%" (
  echo(【3】创建 Python 3.12 虚拟环境："%VENV_DIR%"
  if defined PY_CMD (
    %PY_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
      echo([错误] 创建 venv 失败（权限/安全软件/安装不完整等）。
      set "HAD_ERROR=1"
    ) else (
      echo(    → venv 已创建
    )
  ) else (
    echo(    [跳过] 未锁定到 3.12，未创建 venv。
    set "HAD_ERROR=1"
  )
  echo(
)

echo(【4】升级 venv 内 pip/setuptools/wheel（使用清华源）
if exist "%VENV_PY%" (
  "%VENV_PY%" -V
  "%VENV_PY%" -m pip install --upgrade pip setuptools wheel -i "%PIP_INDEX%"
  if errorlevel 1 (
    echo([警告] 升级出现问题，将继续后续步骤。
    set "HAD_ERROR=1"
  )
) else (
  echo([错误] 未找到 "%VENV_PY%"，请检查 venv 是否创建成功。
  set "HAD_ERROR=1"
)
echo(

echo(【5】安装项目依赖 requirements.txt（清华源）
echo(    开始安装 paddlepaddle-gpu==3.2.0（使用 Paddle 官方源）...
"%VENV_PY%" -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
if errorlevel 1 (
  echo([错误] paddlepaddle-gpu 安装失败；可手动重试：
  echo(      "%VENV_PY%" -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
  set "HAD_ERROR=1"
) else (
  echo(    → paddlepaddle-gpu 安装成功
)

if exist "requirements.txt" (
  echo(    检测到 requirements.txt，开始安装（明确用 venv 的 pip）...
  "%VENV_PY%" -m pip install -r requirements.txt -i "%PIP_INDEX%"
  if errorlevel 1 (
    echo([错误] 依赖安装失败；可手动重试：
    echo(      "%VENV_PY%" -m pip install -r requirements.txt -i %PIP_INDEX%
    set "HAD_ERROR=1"
  ) else (
    echo(    → 依赖安装成功
  )
) else (
  echo(    [提醒] 未找到 requirements.txt，已跳过依赖安装。
  echo(           手动示例： "%VENV_PY%" -m pip install pandas -i %PIP_INDEX%
)
echo(


echo(【6】安装路径与 pip 归属验证（确认没装到系统）
if exist "%VENV_PY%" (
  echo(    → Python 可执行文件：
  "%VENV_PY%" -c "import sys; print(sys.executable)"
  echo(    → pip 版本与归属（应指向 venv）：
  "%VENV_PY%" -m pip -V
)
echo(

echo(【7】后续使用说明
echo(    激活（当前会话）：  call "%VENV_ACT%"
echo(    退出虚拟环境：      deactivate
echo(    再次安装依赖：      "%VENV_PY%" -m pip install -r requirements.txt -i %PIP_INDEX%
echo(

echo ============================================================
if "%HAD_ERROR%"=="0" (
  echo(✔ 完成：所有安装均通过 venv 的 Python/pip 执行。
) else (
  echo(▲ 流程结束：期间出现错误或警告，请按提示检查后重试相应步骤。
)
echo ============================================================
echo(
pause

popd
endlocal
