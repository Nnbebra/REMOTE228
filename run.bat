@echo off
chcp 65001 >nul
title StudyRemote — Web Remote Desktop

echo ========================================================
echo   ⚡ StudyRemote — Запуск сервера удалённого доступа
echo ========================================================
echo.
echo Выберите режим запуска:
echo [1] Запустить скомпилированный EXE (по умолчанию, порт 8080, PIN 1234)
echo [2] Запустить с публичным туннелем Cloudflare (доступ из любой точки мира)
echo [3] Запустить из исходного кода через Python (app.py)
echo.
set /p mode="Ваш выбор (1-3, Enter = 1): "

if "%mode%"=="2" (
    echo.
    echo Запуск с туннелем...
    if exist "%~dp0dist\StudyRemote.exe" (
        "%~dp0dist\StudyRemote.exe" --tunnel
    ) else (
        python "%~dp0app.py" --tunnel
    )
) else if "%mode%"=="3" (
    echo.
    echo Запуск через Python...
    python "%~dp0app.py"
) else (
    echo.
    echo Запуск StudyRemote.exe...
    if exist "%~dp0dist\StudyRemote.exe" (
        "%~dp0dist\StudyRemote.exe"
    ) else (
        python "%~dp0app.py"
    )
)

pause
