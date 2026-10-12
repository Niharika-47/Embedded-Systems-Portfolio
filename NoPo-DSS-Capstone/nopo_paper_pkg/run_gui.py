"""
nopo_paper_pkg / run_gui.py
----------------------------
Interactive Web Application GUI Server for HiPCO KAN Decision Support System.
Includes REST API Endpoints:
- GET  /                     -> Serves hipco_kan_dss_app.html
- POST /api/upload_and_train -> Accepts custom CSV dataset, executes Fast RBF-KAN pre-training/fine-tuning, and returns updated metrics.
- POST /api/solve_inverse    -> Executes PyTorch autograd gradient inverse optimization (20 multi-start seeds) to recommend optimal reactor setpoints.
"""

import os
import sys
import json
import io
import webbrowser
import http.server
import socketserver
import threading
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nopo_paper_pkg.kan_model import KAN
from nopo_paper_pkg.synthetic_generator import calculate_secondary_parameters
from nopo_paper_pkg.inverse_optimizer import PyKANInverseSolver, SETPOINT_BOUNDS

HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hipco_kan_dss_app.html")
PRETRAINED_CHECKPOINT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kan_pretrained.pt")
PORT = 8050

INPUT_FEATURES = [
    'P_CO_atm', 'T_rxn_mean_C', 'T_spread_C', 'Flow_CO_SLPM', 'Flow_Fe_Precursor_SLPM', 'H2O_Flow_ppmv', 'Zone_SP_Dev_C',
    'Residence_Time_s', 'Reynolds_Number', 'Fe_Concentration_ppm', 'CO_Disproportionation_DrivingForce', 'Thermal_Loss_kW',
    'P_CO2_Partial_bar', 'Nucleation_Rate_Est', 'Linear_Gas_Velocity_m_s', 'Catalyst_Growth_Time_Ratio',
    'Thermal_Boundary_Thickness_mm', 'Water_CO_Ratio_ppm'
]

REAL_INPUT_MAP = {
    'PT01': 'P_CO_atm',
    'Feat_Mean_RxTemp': 'T_rxn_mean_C',
    'Feat_RxTemp_Spread': 'T_spread_C',
    'Feat_Total_CO_Flow': 'Flow_CO_SLPM',
    'MFC-03-CO-IN': 'Flow_Fe_Precursor_SLPM',
    'BUBBLER_SV': 'H2O_Flow_ppmv',
    'Feat_Zone1_SP_Deviation': 'Zone_SP_Dev_C'
}

QUALITY_TARGETS = [
    'DWM_Yield_g', 'DWM_G/D', 'DWM_Purity_UV', 'DWM_Ni_ppm_Axial', 'DWM_Ni_ppm_Radial',
    'DWM_Fe_ppm_Axial', 'DWM_Fe_ppm_Radial', 'DWM_Cr_ppm_Axial', 'DWM_Cr_ppm_Radial'
]

class DSSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/hipco_kan_dss_app.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(HTML_PATH, 'rb') as f:
                self.wfile.write(f.read())
        else:
            super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        if self.path == '/api/solve_inverse':
            try:
                data_json = json.loads(post_data.decode('utf-8'))
                target_gd = float(data_json.get('target_gd', 18.0))
                target_purity = float(data_json.get('target_purity', 50.0))
                target_yield = float(data_json.get('target_yield', 2.0))

                # Load pretrained KAN & scalers
                if os.path.exists(PRETRAINED_CHECKPOINT):
                    chk = torch.load(PRETRAINED_CHECKPOINT, weights_only=False)
                    model = KAN(layers_hidden=[len(INPUT_FEATURES), 16, len(QUALITY_TARGETS)], grid_size=3)
                    model.load_state_dict(chk['model_state'])
                    scaler_X, scaler_Y = chk['scaler_X'], chk['scaler_Y']
                else:
                    scaler_X, scaler_Y = StandardScaler(), StandardScaler()
                    model = KAN(layers_hidden=[len(INPUT_FEATURES), 16, len(QUALITY_TARGETS)], grid_size=3)

                solver = PyKANInverseSolver(model, scaler_X, scaler_Y)
                target_dict = {
                    'DWM_G/D': target_gd,
                    'DWM_Purity_UV': target_purity,
                    'DWM_Yield_g': target_yield
                }

                solution = solver.solve_recipe(target_dict, n_seeds=20)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(solution).encode('utf-8'))

            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

        elif self.path == '/api/upload_and_train':
            try:
                data_json = json.loads(post_data.decode('utf-8'))
                csv_content = data_json.get('csv_text', '')
                
                df = pd.read_csv(io.StringIO(csv_content))
                row_count = len(df)
                
                sub_df = pd.DataFrame()
                for orig_col, target_col in REAL_INPUT_MAP.items():
                    if orig_col in df.columns:
                        sub_df[target_col] = pd.to_numeric(df[orig_col], errors='coerce')
                    elif target_col in df.columns:
                        sub_df[target_col] = pd.to_numeric(df[target_col], errors='coerce')
                    else:
                        sub_df[target_col] = 60.0 if 'P_CO' in target_col else 950.0
                
                sub_df = sub_df.ffill().bfill().fillna(0.0)
                df_sec = calculate_secondary_parameters(sub_df)
                X_df = pd.concat([sub_df, df_sec], axis=1)[INPUT_FEATURES]
                
                Y_df = pd.DataFrame()
                for tgt in QUALITY_TARGETS:
                    if tgt in df.columns:
                        Y_df[tgt] = pd.to_numeric(df[tgt], errors='coerce')
                    else:
                        Y_df[tgt] = 1.5 if 'Yield' in tgt else (15.0 if 'G/D' in tgt else 40.0)
                Y_df = Y_df.ffill().bfill().fillna(1.0)
                
                X_vals = X_df.values
                Y_vals = Y_df.values
                
                scaler_X = StandardScaler()
                scaler_Y = StandardScaler()
                X_s = scaler_X.fit_transform(X_vals)
                
                Y_log = Y_vals.copy()
                metal_indices = [i for i, t in enumerate(QUALITY_TARGETS) if 'ppm' in t]
                for m_i in metal_indices:
                    Y_log[:, m_i] = np.log1p(Y_log[:, m_i])
                Y_s = scaler_Y.fit_transform(Y_log)
                
                model = KAN(layers_hidden=[18, 16, 9], grid_size=5)
                optimizer = optim.AdamW(model.parameters(), lr=0.003, weight_decay=1e-3)
                criterion = nn.MSELoss()
                
                losses = []
                for epoch in range(30):
                    optimizer.zero_grad()
                    out = model(torch.tensor(X_s, dtype=torch.float32))
                    loss = criterion(out, torch.tensor(Y_s, dtype=torch.float32))
                    loss.backward()
                    optimizer.step()
                    losses.append(round(float(loss.item()), 4))
                    
                model.eval()
                with torch.no_grad():
                    preds_s = model(torch.tensor(X_s, dtype=torch.float32)).numpy()
                    preds_log = scaler_Y.inverse_transform(preds_s)
                    for m_i in metal_indices:
                        preds_log[:, m_i] = np.expm1(preds_log[:, m_i])
                        
                mae_list = [mean_absolute_error(Y_vals[:, i], preds_log[:, i]) for i in range(9)]
                mean_mae = round(float(np.mean(mae_list)), 4)
                
                torch.save({'model_state': model.state_dict(), 'scaler_X': scaler_X, 'scaler_Y': scaler_Y}, PRETRAINED_CHECKPOINT)
                
                response_payload = {
                    'status': 'success',
                    'row_count': row_count,
                    'final_loss': losses[-1],
                    'loss_history': losses,
                    'mean_mae': mean_mae,
                    'quality_targets': QUALITY_TARGETS
                }
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response_payload).encode('utf-8'))
                
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))

def run_server():
    os.chdir(os.path.dirname(HTML_PATH))
    with socketserver.TCPServer(("", PORT), DSSRequestHandler) as httpd:
        print(f"[OK] HiPCO KAN DSS Web Application running at http://localhost:{PORT}/")
        print("  - POST /api/upload_and_train (Custom CSV Training)")
        print("  - POST /api/solve_inverse    (PyTorch Autograd Inverse Recipe Solver)")
        httpd.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    webbrowser.open(f"http://localhost:{PORT}/")
    print("\n=========================================================")
    print("   HiPCO KAN Decision Support System (DSS) GUI Launched! ")
    print(f"   URL: http://localhost:{PORT}/")
    print("=========================================================\n")
    try:
        t.join()
    except KeyboardInterrupt:
        sys.exit(0)
