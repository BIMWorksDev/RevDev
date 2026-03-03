@echo off
setlocal enabledelayedexpansion

:: Configuration
set "REPO_URL=https://github.com/BIMWorksDev/RevDev.git"
set "EXTENSION_NAME=ToolsByGimhanPy.extension"
set "TARGET_EXT_DIR=%APPDATA%\pyRevit\Extensions"
set "INSTALL_PATH=%TARGET_EXT_DIR%\%EXTENSION_NAME%"

echo ====================================================
echo   Revit Tools One-Click Installer
echo ====================================================
echo.

:: 1. Check for Git
echo [1/3] Checking for Git...
where git >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Git is not installed!
    echo Please install Git from https://git-scm.com/ and try again.
    pause
    exit /b 1
)
echo [OK] Git is available.

:: 2. Prepare Extensions Directory
echo [2/3] Preparing pyRevit Extensions directory...
if not exist "%TARGET_EXT_DIR%" (
    echo Creating directory: %TARGET_EXT_DIR%
    mkdir "%TARGET_EXT_DIR%"
)
echo [OK] Directory ready.

:: 3. Clone or Update Repository
echo [3/3] Deploying extension tools...
if exist "%INSTALL_PATH%" (
    echo Existing installation found at %INSTALL_PATH%
    echo Updating to latest version...
    cd /d "%INSTALL_PATH%"
    git pull origin master
    if !ERRORLEVEL! neq 0 (
        echo [WARNING] Update failed. You might have local changes or network issues.
    )
) else (
    echo Cloning tools from %REPO_URL%...
    git clone "%REPO_URL%" "%INSTALL_PATH%"
    if !ERRORLEVEL! neq 0 (
        echo [ERROR] Failed to clone repository.
        pause
        exit /b 1
    )
)

echo.
echo ====================================================
echo   INSTALLATION SUCCESSFUL!
echo ====================================================
echo.
echo Please restart Revit or run 'pyRevit Reload' to see the new tools.
echo.
pause
