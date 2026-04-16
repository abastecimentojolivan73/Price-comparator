@echo off
echo ============================================================
echo  Compilando ComparadorPrecos com PyInstaller
echo ============================================================

pip install pyinstaller customtkinter lxml openpyxl fpdf2 requests

pyinstaller ^
    --onefile ^
    --windowed ^
    --name="ComparadorPrecos" ^
    --collect-all customtkinter ^
    --hidden-import=core ^
    --hidden-import=core.database ^
    --hidden-import=core.api_service ^
    --hidden-import=core.xml_processor ^
    --hidden-import=core.comparator ^
    --hidden-import=core.reports ^
    --hidden-import=ui ^
    --hidden-import=ui.app ^
    --hidden-import=utils ^
    --hidden-import=utils.helpers ^
    --hidden-import=lxml ^
    --hidden-import=lxml.etree ^
    --hidden-import=openpyxl ^
    --hidden-import=fpdf ^
    --hidden-import=requests ^
    main.py

echo.
echo ============================================================
echo  Build concluido! Executavel em: dist\ComparadorPrecos.exe
echo ============================================================
pause
