@echo off
setlocal EnableExtensions
pushd "%~dp0"

REM =====================================================
REM  run.bat
REM  功能：激活 venv 并运行 whimbox.py
REM  要求：setup_env.bat 已经创建好 venv 并安装依赖
REM =====================================================

set "VENV_PY=venv\Scripts\python.exe"
set "VENV_ACT=venv\Scripts\activate.bat"

echo(
echo ============================================
echo(【运行】whimbox.py (通过 venv)
echo ============================================
echo(

REM 检查虚拟环境 Python 是否存在
if not exist "%VENV_PY%" (
  echo [错误] 未找到 %VENV_PY%
  echo 请先运行 setup_env.bat 创建虚拟环境！
  pause
  goto :END
)

REM 激活 venv（可选，方便用户在当前会话继续用）
call "%VENV_ACT%"

REM 运行 whimbox.py
"%VENV_PY%" whimbox.py
if errorlevel 1 (
  echo(
  echo [错误] whimbox.py 执行失败，请检查报错信息。
) else (
  echo(
  echo [完成] whimbox.py 已执行完毕。
)

echo(
echo ============================================
echo( 脚本执行结束，按任意键关闭窗口...
echo ============================================
echo(
pause

:END
popd
endlocal
