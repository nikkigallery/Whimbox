@echo off
setlocal EnableExtensions
pushd "%~dp0"

REM --- 基本参数（可改） ---
set "ENV_DIR=conda_env"
set "PY_VER=3.12"
set "PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu126/"

REM --- 控制台编码（可注释） ---
chcp 65001 >nul

set "HAD_ERROR=0"
set "ENV_PREFIX=%CD%\%ENV_DIR%"
set "CONDA_EXE="

echo.
echo ============================================================
echo [0] 开始：在当前目录创建 Conda 环境
echo     目标 Python: %PY_VER%
echo     环境目录   : %ENV_PREFIX%
echo ============================================================
echo.

REM [1] 查找 conda.exe（避免调用 conda.bat 引发递归）
for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
  if not defined CONDA_EXE set "CONDA_EXE=%%~fI"
)

if not defined CONDA_EXE (
  echo [错误] 未找到 conda.exe
  echo   解决：确保 Miniconda/Anaconda 已安装，并且 conda.exe 在 PATH 中。
  echo   常见位置示例：
  echo     %%USERPROFILE%%\miniconda3\condabin\conda.exe
  echo     %%USERPROFILE%%\anaconda3\condabin\conda.exe
  set "HAD_ERROR=1"
) else (
  echo [1] 使用的 conda.exe: %CONDA_EXE%
)
echo.

REM [2] 处理已存在的环境
if exist "%ENV_PREFIX%\python.exe" (
  echo [2] 已检测到环境：%ENV_PREFIX%
  set "ANS="
  set /p ANS="    是否删除并重建？输入 Y 或 N 回车（默认 N）： "
  if "%ANS%"=="" set "ANS=N"
  set "ANS=%ANS:~0,1%"
  if /I "%ANS%"=="Y" (
    echo     -> 正在删除旧环境...
    rmdir /S /Q "%ENV_PREFIX%"
    if errorlevel 1 (
      echo [错误] 删除失败（文件被占用/权限不足）。
      set "HAD_ERROR=1"
    )
  ) else (
    echo     -> 保留现有环境
  )
) else (
  echo [2] 未检测到现有环境，将新建。
)
echo.

REM [3] 创建环境（仅当不存在或刚被删除）
if not exist "%ENV_PREFIX%\python.exe" (
  if defined CONDA_EXE (
    echo [3] 创建 Conda 环境（Python %PY_VER%）...
    "%CONDA_EXE%" create -y -p "%ENV_PREFIX%" python=%PY_VER%
    if errorlevel 1 (
      echo [错误] 创建环境失败（网络/源/权限）。
      set "HAD_ERROR=1"
    ) else (
      echo     -> 环境已创建：%ENV_PREFIX%
    )
  ) else (
    echo [跳过] 未找到 conda.exe，无法创建环境。
    set "HAD_ERROR=1"
  )
)
echo.

REM [4] 升级基础工具
if exist "%ENV_PREFIX%\python.exe" (
  echo [4] 升级 pip/setuptools/wheel ...
  "%CONDA_EXE%" run -p "%ENV_PREFIX%" python -V
  "%CONDA_EXE%" run -p "%ENV_PREFIX%" python -m pip install --upgrade pip setuptools wheel -i "%PIP_INDEX%"
  if errorlevel 1 (
    echo [警告] 升级失败，将继续后续步骤。
    set "HAD_ERROR=1"
  )
) else (
  echo [错误] 环境内未找到 python.exe
  set "HAD_ERROR=1"
)
echo.

REM [5] 安装 requirements（清华源）
if exist "%ENV_PREFIX%\python.exe" (
  if exist "requirements.txt" (
    echo [5] 检测到 requirements.txt，开始安装（清华源）...
    "%CONDA_EXE%" run -p "%ENV_PREFIX%" python -m pip install -r requirements.txt -i "%PIP_INDEX%"
    if errorlevel 1 (
      echo [错误] requirements 安装失败；可手动重试：
      echo        "%CONDA_EXE%" run -p "%ENV_PREFIX%" python -m pip install -r requirements.txt -i "%PIP_INDEX%"
      set "HAD_ERROR=1"
    ) else (
      echo     -> 依赖安装成功
    )
  ) else (
    echo     [提醒] 未发现 requirements.txt，已跳过依赖安装。
  )
)
echo.


REM [6] 验证安装归属与环境目录
if exist "%ENV_PREFIX%\python.exe" (
  echo [6] Python 可执行路径（应为当前目录的环境）：
  "%CONDA_EXE%" run -p "%ENV_PREFIX%" python -c "import sys; print(sys.executable)"
  echo     pip 版本与归属：
  "%CONDA_EXE%" run -p "%ENV_PREFIX%" python -m pip -V
  echo     环境目录：
  echo       %ENV_PREFIX%
)
echo.

echo ============================================================
if "%HAD_ERROR%"=="0" (
  echo ✔ 完成：Conda 环境已创建在当前目录并安装依赖。
) else (
  echo ▲ 完成（含错误/警告）：请根据日志检查并重试相应步骤。
)
echo ============================================================
echo.
pause

popd
endlocal
