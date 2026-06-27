@echo off
setlocal

set "ROOT=%~dp0"
set "DEPLOY=%ROOT%deploy"

echo ============================================
echo   iptv-all-in-one Build Deploy Package
echo ============================================
echo.

echo [1/4] Cleaning deploy folder...
if exist "%DEPLOY%" rd /s /q "%DEPLOY%"

echo [2/4] Building frontend dist...
cd /d "%ROOT%frontend"
if errorlevel 1 (
    echo ERROR: frontend folder not found
    goto :fail
)
call npm run build
if errorlevel 1 (
    echo ERROR: Frontend build failed
    goto :fail
)
echo Frontend build OK.
echo.

echo [3/4] Preparing deploy folder...
mkdir "%DEPLOY%"
mkdir "%DEPLOY%\output"

echo [4/4] Copying files...
cd /d "%ROOT%"

xcopy /e /i /q "engine"                "%DEPLOY%\engine"
xcopy /e /i /q "web"                   "%DEPLOY%\web"
xcopy /e /i /q "scanner_integration"   "%DEPLOY%\scanner_integration"
xcopy /e /i /q "database"              "%DEPLOY%\database"
del /q "%DEPLOY%\database\db_config.json" 2>nul

xcopy /e /i /q "dist"                  "%DEPLOY%\dist"

copy /y "requirements.txt"    "%DEPLOY%\"
copy /y "basic_auth.json"     "%DEPLOY%\"
copy /y "Dockerfile"          "%DEPLOY%\"
copy /y "docker-compose.yml"  "%DEPLOY%\"
copy /y ".env.example"        "%DEPLOY%\"
copy /y "generate_env.py"     "%DEPLOY%\"

for /d /r "%DEPLOY%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)

echo.
echo ============================================
echo   Done! Deploy folder: deploy\
echo ============================================
echo.
dir /b "%DEPLOY%"
echo.
echo Copy the deploy folder to server and run:
echo   python -m web
echo.
pause
exit /b 0

:fail
echo.
echo Build failed!
pause
exit /b 1
