import os
import sys
import json
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nopo_paper_pkg.kan_model import KAN

pkg_dir = os.path.dirname(os.path.abspath(__file__))
chk_path = os.path.join(pkg_dir, "kan_pretrained.pt")
data_path = os.path.join(pkg_dir, "SWCNT_synthetic_50_matched.csv")

chk = torch.load(chk_path, weights_only=False)
model = KAN([18, 16, 9], grid_size=3)
model.load_state_dict(chk['model_state'])
model.eval()

scaler_X = chk['scaler_X']
scaler_Y = chk['scaler_Y']

df = pd.read_csv(data_path).bfill().ffill()

INPUT_FEATURES = [
    'P_CO_atm', 'T_rxn_mean_C', 'T_spread_C', 'Flow_CO_SLPM', 'Flow_Fe_Precursor_SLPM', 'H2O_Flow_ppmv', 'Zone_SP_Dev_C',
    'Residence_Time_s', 'Reynolds_Number', 'Fe_Concentration_ppm', 'CO_Disproportionation_DrivingForce', 'Thermal_Loss_kW',
    'P_CO2_Partial_bar', 'Nucleation_Rate_Est', 'Linear_Gas_Velocity_m_s', 'Catalyst_Growth_Time_Ratio',
    'Thermal_Boundary_Thickness_mm', 'Water_CO_Ratio_ppm'
]

QUALITY_TARGETS = [
    'DWM_Yield_g', 'DWM_G/D', 'DWM_Purity_UV', 'DWM_Ni_ppm_Axial', 'DWM_Ni_ppm_Radial',
    'DWM_Fe_ppm_Axial', 'DWM_Fe_ppm_Radial', 'DWM_Cr_ppm_Axial', 'DWM_Cr_ppm_Radial'
]

X = df[INPUT_FEATURES].values
Y = df[QUALITY_TARGETS].values

X_s = scaler_X.transform(X)
with torch.no_grad():
    pred_s = model(torch.tensor(X_s, dtype=torch.float32)).numpy()

pred_Y = scaler_Y.inverse_transform(pred_s)

print("=== ACTUAL DATASET MODEL TEST REPORT (50 Matched Batches) ===")
metrics = []
for i, target in enumerate(QUALITY_TARGETS):
    y_true = Y[:, i]
    y_pred = pred_Y[:, i]
    r2 = r2_score(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mae = mean_absolute_error(y_true, y_pred)
    mape = np.mean(np.abs((y_true - y_pred) / (y_true + 1e-6))) * 100
    metrics.append({
        'Target': target,
        'Mean_True': round(float(np.mean(y_true)), 2),
        'Mean_Pred': round(float(np.mean(y_pred)), 2),
        'R2_Score': round(float(r2), 4),
        'RMSE': round(float(rmse), 2),
        'MAE': round(float(mae), 2),
        'MAPE_%': round(float(mape), 2)
    })

df_metrics = pd.DataFrame(metrics)
print(df_metrics.to_markdown(index=False))
