@echo off
chcp 65001 >nul
echo ========================================================
echo   Компиляция StudyRemote в автономный .exe файл
echo ========================================================
echo.

echo [1/3] Проверка окружения Python...
python --version
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Python не найден!
    pause
    exit /b 1
)

echo [2/3] Запуск сборки через PyInstaller...
pyinstaller --noconfirm --clean --onefile --console ^
    --name "StudyRemote" ^
    --add-data "web;web" ^
    --hidden-import "tornado" ^
    --hidden-import "mss" ^
    --hidden-import "pyautogui" ^
    --hidden-import "PIL" ^
    --hidden-import "psutil" ^
    app.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo [УСПЕХ] Сборка успешно завершена!
    echo Исполняемый файл находится в: dist\StudyRemote.exe
    echo ========================================================
) else (
    echo.
    echo [ОШИБКА] Во время компиляции произошла ошибка.
)

pause
