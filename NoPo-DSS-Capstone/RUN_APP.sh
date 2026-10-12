#!/bin/bash
echo "========================================================================="
echo "      HiPCO KAN CYBER-PHYSICAL DIGITAL TWIN & DECISION SUPPORT SYSTEM    "
echo "========================================================================="
echo ""

# Check python
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "[ERROR] Python not found. Opening standalone HTML dashboard directly..."
    xdg-open "./hipco_kan_dss_app.html" 2>/dev/null || open "./hipco_kan_dss_app.html"
    exit 1
fi

echo "[1/2] Checking core Python dependencies..."
$PYTHON_CMD -c "import torch, pandas, numpy, scipy; print('   [OK] Core dependencies verified.')" 2>/dev/null || {
    echo "   [NOTICE] Installing required packages..."
    pip install torch pandas numpy scipy scikit-learn python-pptx reportlab
}

echo "[2/2] Launching Web Application at http://localhost:8050/..."
echo "(Press Ctrl+C to terminate the server)"
echo ""

# Open browser in background
(sleep 1 && (xdg-open "http://localhost:8050/" 2>/dev/null || open "http://localhost:8050/")) &

$PYTHON_CMD "./nopo_paper_pkg/run_gui.py"
