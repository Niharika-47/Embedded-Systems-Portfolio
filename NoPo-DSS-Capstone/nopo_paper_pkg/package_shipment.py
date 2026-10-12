"""
nopo_paper_pkg / package_shipment.py
------------------------------------
Packages the complete, production-ready HiPCO KAN project into a clean,
shippable ZIP archive: HiPCO_KAN_Shipment_Package.zip
"""

import os
import zipfile

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
zip_dest = os.path.join(root_dir, "HiPCO_KAN_Shipment_Package.zip")

INCLUDE_FILES = [
    "README.md",
    "RUN_APP.bat",
    "RUN_APP.sh",
    "launcher.py",
    "hipco_kan_dss_app.html",
    "HiPCO_KAN_Comprehensive_Guide.pdf",
    "HiPCO_KAN_Review_Panel_Presentation.pptx",
    "review_panel_presentation.html"
]

INCLUDE_DIRS = [
    "nopo_paper_pkg"
]

EXCLUDE_EXTENSIONS = {
    ".pyc", ".log", ".tmp"
}

EXCLUDE_DIRS = {
    "__pycache__", ".git", ".gemini", ".idea", ".vscode"
}

def create_shipment_zip():
    print(f"[1/2] Compiling files for shipment package...")
    with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add root files
        for fname in INCLUDE_FILES:
            fpath = os.path.join(root_dir, fname)
            if os.path.exists(fpath):
                zf.write(fpath, arcname=fname)
                print(f"   + Included root file: {fname}")

        # Add package directory
        for dir_name in INCLUDE_DIRS:
            base_folder = os.path.join(root_dir, dir_name)
            for root, dirs, files in os.walk(base_folder):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for file in files:
                    ext = os.path.splitext(file)[1]
                    if ext in EXCLUDE_EXTENSIONS:
                        continue
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, root_dir)
                    zf.write(full_path, arcname=rel_path)
                    
    file_size_mb = os.path.getsize(zip_dest) / (1024 * 1024)
    print(f"\n[2/2] [SUCCESS] Created Shippable Zip Archive: {zip_dest} ({file_size_mb:.2f} MB)")

if __name__ == "__main__":
    create_shipment_zip()
