"""
launcher.py
------------
Cross-Platform 1-Click Python Launcher for HiPCO KAN DSS Application.
Runs on Windows, macOS, and Linux.
"""

import os
import sys
import subprocess
import webbrowser
import time

def main():
    print("=" * 75)
    print("      HiPCO KAN CYBER-PHYSICAL DIGITAL TWIN & DECISION SUPPORT SYSTEM     ")
    print("=" * 75)
    
    root_dir = os.path.dirname(os.path.abspath(__file__))
    html_file = os.path.join(root_dir, "hipco_kan_dss_app.html")
    server_script = os.path.join(root_dir, "nopo_paper_pkg", "run_gui.py")
    
    print("\n[1/2] Checking core Python dependencies...")
    try:
        import torch
        import pandas
        import numpy
        import scipy
        print("   [OK] PyTorch, Pandas, NumPy, SciPy verified.")
    except ImportError as e:
        print(f"   [NOTICE] Missing package ({e.name}). Installing required dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "torch", "pandas", "numpy", "scipy", "scikit-learn", "python-pptx", "reportlab"])

    print("\n[2/2] Launching HiPCO KAN Server on port 8050...")
    print("   -> Dashboard URL: http://localhost:8050/")
    print("   -> (Press Ctrl+C in this terminal to stop the application)\n")
    
    time.sleep(0.5)
    webbrowser.open("http://localhost:8050/")
    
    try:
        subprocess.run([sys.executable, server_script])
    except KeyboardInterrupt:
        print("\n[INFO] Application closed successfully.")

if __name__ == "__main__":
    main()
