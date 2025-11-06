@echo off
REM Format code using development tools (Windows)
REM Usage: scripts\format.bat [check|fix]

set MODE=%1
if "%MODE%"=="" set MODE=fix

if "%MODE%"=="check" (
    echo Checking code formatting...
    black --check .
    isort --check-only .
    flake8 .
) else if "%MODE%"=="fix" (
    echo Formatting code...
    black .
    isort .
    echo Checking with flake8...
    flake8 .
    echo Done!
) else (
    echo Usage: %~n0 [check^|fix]
    exit /b 1
)
