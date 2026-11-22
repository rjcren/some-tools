@echo off
setlocal EnableExtensions EnableDelayedExpansion

@REM  批量执行当前目录下所有python脚本，使用虚拟环境并将输出写入日志文件

echo 请勿关闭

cd /d "%~dp0"
set "LOG_FILE=%~dp0run_all.log"
set "PYTHON_CMD="
set "FAILED=0"
set "EXIT_CODE=0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" goto use_venv

set "VENV_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" goto use_venv

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto python_ready
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto python_ready
)

>>"%LOG_FILE%" echo [%date% %time%] ERROR: No working Python interpreter or .venv was found.
echo No working Python interpreter or .venv was found. See "%LOG_FILE%".
set "EXIT_CODE=1"
goto finish

:use_venv
set "PYTHON_CMD="%VENV_PYTHON%""

:python_ready
echo Starting Python scripts in "%~dp0"
echo Using interpreter: !PYTHON_CMD!
>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo [%date% %time%] Starting Python scripts in "%~dp0"
>>"%LOG_FILE%" echo [%date% %time%] Using interpreter: !PYTHON_CMD!

for %%F in ("%~dp0*.py") do (
    if exist "%%~fF" (
        echo Running %%~nxF
        >>"%LOG_FILE%" echo [%date% %time%] Running %%~nxF
        call !PYTHON_CMD! "%%~fF"
        set "SCRIPT_EXIT=!errorlevel!"
        if !SCRIPT_EXIT! EQU 0 (
            echo Finished %%~nxF
            >>"%LOG_FILE%" echo [%date% %time%] Finished %%~nxF
        ) else (
            set "FAILED=1"
            echo FAILED: %%~nxF - exit code !SCRIPT_EXIT!
            >>"%LOG_FILE%" echo [%date% %time%] FAILED: %%~nxF - exit code !SCRIPT_EXIT!
        )
    )
)

if "!FAILED!"=="1" (
    >>"%LOG_FILE%" echo [%date% %time%] Completed with one or more errors.
    echo Completed with one or more errors. See "%LOG_FILE%".
    set "EXIT_CODE=1"
) else (
    >>"%LOG_FILE%" echo [%date% %time%] All scripts completed successfully.
    echo All scripts completed successfully.
)

:finish
if /I not "%~1"=="--scheduled" (
    echo.
    pause
)
exit /b !EXIT_CODE!
