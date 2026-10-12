@echo off
title HiPCO KAN Cyber-Physical Decision Support System
color 0B

echo =========================================================================
echo       HiPCO KAN CYBER-PHYSICAL DIGITAL TWIN & DECISION SUPPORT SYSTEM
echo =========================================================================
echo.
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in PATH!
    echo Opening standalone web dashboard directly in your default browser...
    start "" "%~dp0hipco_kan_dss_app.html"
    pause
    exit /b
)

echo [2/3] Checking dependencies (torch, pandas, numpy, scipy)...
python -c "import torch, pandas, numpy, scipy; print('   [OK] Core dependencies verified.')" >nul 2>&1
if %errorlevel% neq 0 (
    echo    [NOTICE] Some advanced Python packages missing. Installing if needed...
    pip install torch pandas numpy scipy scikit-learn python-pptx reportlab >nul 2>&1
)

echo [3/3] Launching HiPCO KAN Web Application...
echo.
echo Application will open at: http://localhost:8050/
echo (Press Ctrl+C in this terminal window to stop the server when done)
echo.

start "" "http://localhost:8050/"
python "%~dp0nopo_paper_pkg\run_gui.py"

pause
