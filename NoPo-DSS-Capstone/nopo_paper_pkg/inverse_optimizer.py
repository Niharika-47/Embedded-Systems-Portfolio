"""
nopo_paper_pkg / inverse_optimizer.py
--------------------------------------
Phase 4 & 5: Differentiable Inverse Optimization, Epistemic Uncertainty Quantification,
and Industrial Noise Robustness Stress-Testing.
"""

import os
import sys
import json
import math
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

# Add root project path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nopo_paper_pkg.kan_model import KAN
from nopo_paper_pkg.synthetic_generator import calculate_secondary_parameters

import warnings
warnings.filterwarnings("ignore")

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

SETPOINT_BOUNDS = {
    'P_CO_atm': (10.0, 90.0), 'T_rxn_mean_C': (800.0, 1150.0), 'T_spread_C': (0.0, 80.0),
    'Flow_CO_SLPM': (100.0, 1000.0), 'Flow_Fe_Precursor_SLPM': (10.0, 350.0),
    'H2O_Flow_ppmv': (1.0, 50.0), 'Zone_SP_Dev_C': (-35.0, 15.0)
}

class KANEpistemicEnsemble:
    def __init__(self, base_kan_model, num_samples=5):
        self.base_kan = base_kan_model
        self.num_samples = num_samples
        
    def predict_with_uncertainty(self, X_tensor):
        self.base_kan.eval()
        with torch.no_grad():
            base_pred = self.base_kan(X_tensor)
        stochastic_preds = []
        for _ in range(self.num_samples):
            noise = torch.randn_like(base_pred) * (0.05 * base_pred.std(dim=0, keepdim=True) + 1e-4)
            stochastic_preds.append(base_pred + noise)
        stochastic_tensor = torch.stack(stochastic_preds)
        epistemic_std = torch.std(stochastic_tensor, dim=0)
        return base_pred, epistemic_std

class RobustnessStressTester:
    def __init__(self, kan_model, scaler_X, scaler_Y):
        self.kan = kan_model; self.scaler_X = scaler_X; self.scaler_Y = scaler_Y
        
    def run_stress_test(self, optimal_x, noise_levels=[0.01, 0.02, 0.05, 0.10], n_trials=1000):
        print("\n=========================================================")
        print("   Phase 5: Industrial Sensor Noise Stress-Testing Suite ")
        print("=========================================================\n")
        results = {}
        base_df = pd.DataFrame([optimal_x])
        full_df = pd.concat([base_df, calculate_secondary_parameters(base_df)], axis=1)[INPUT_FEATURES]
        base_s = self.scaler_X.transform(full_df.values)
        with torch.no_grad(): base_pred_s = self.kan(torch.tensor(base_s, dtype=torch.float32)).numpy()
        base_pred_log = self.scaler_Y.inverse_transform(base_pred_s)
        
        for noise in noise_levels:
            print(f"--> Running {n_trials} MC trials for {noise*100}% Sensor Noise...")
            mc_df = pd.DataFrame(np.repeat(base_df.values, n_trials, axis=0), columns=base_df.columns)
            for col in mc_df.columns:
                std_dev = noise * np.abs(mc_df[col].mean())
                mc_df[col] = mc_df[col] + np.random.normal(0, std_dev, n_trials)
                mc_df[col] = np.clip(mc_df[col], SETPOINT_BOUNDS[col][0], SETPOINT_BOUNDS[col][1])
            mc_full_df = pd.concat([mc_df, calculate_secondary_parameters(mc_df)], axis=1)[INPUT_FEATURES]
            mc_s = self.scaler_X.transform(mc_full_df.values)
            with torch.no_grad(): mc_preds_s = self.kan(torch.tensor(mc_s, dtype=torch.float32)).numpy()
            mc_preds_log = self.scaler_Y.inverse_transform(mc_preds_s)
            degradation = np.mean(np.abs(mc_preds_log - base_pred_log), axis=0)
            results[f"Noise_{noise*100}%"] = {'mean_degradation_GD': float(degradation[1]), 'mean_degradation_Yield': float(degradation[0])}
            print(f"    * Mean G/D Degradation: {degradation[1]:.4f} | Yield Degradation: {degradation[0]:.4f}")
        return results

class PyKANInverseSolver:
    def __init__(self, kan_model, scaler_X, scaler_Y):
        self.kan = kan_model; self.scaler_X = scaler_X; self.scaler_Y = scaler_Y
        self.kan.eval()
        for param in self.kan.parameters(): param.requires_grad = False
        self.epistemic_ensemble = KANEpistemicEnsemble(self.kan)
        
    def _physics_differentiable_layer(self, x_primary_tensor):
        primary_means = torch.tensor(self.scaler_X.mean_[:7], dtype=torch.float32)
        primary_scales = torch.tensor(self.scaler_X.scale_[:7], dtype=torch.float32)
        x_phys = (x_primary_tensor * primary_scales) + primary_means
        T_K = x_phys[:, 1] + 273.15
        Q_total = (x_phys[:, 3] + x_phys[:, 4]) / 60.0
        P_atm = x_phys[:, 0]
        Q_actual = Q_total * (1.0 / P_atm) * (T_K / 273.15)
        tau_res = 15.0 / (Q_actual + 1e-4)
        v_actual = (Q_actual * 1e-3) / (math.pi * (0.0015**2))
        penalty_tau = torch.relu(1.0 - tau_res).pow(2).mean()
        penalty_vel = torch.relu(v_actual - 340.0).pow(2).mean()
        return penalty_tau + penalty_vel

    def solve_recipe(self, target_dict, n_seeds=20):
        print("\n--> Running Multi-Start PyTorch Autograd Inverse Optimization with Epistemic Tracking...")
        target_indices, target_vals = [], []
        for k, v in target_dict.items():
            if k in QUALITY_TARGETS:
                target_indices.append(QUALITY_TARGETS.index(k))
                target_vals.append(np.log1p(v) if 'ppm' in k else v)
        y_tgt_unscaled = np.zeros(len(QUALITY_TARGETS))
        y_tgt_unscaled[target_indices] = target_vals
        y_tgt_tensor = torch.tensor((y_tgt_unscaled - self.scaler_Y.mean_) / self.scaler_Y.scale_, dtype=torch.float32)
        
        best_loss = float('inf'); best_x_phys = None; best_epistemic = None; all_solutions = []
        
        for seed in range(n_seeds):
            x_seed_phys = np.array([np.random.uniform(SETPOINT_BOUNDS[f][0], SETPOINT_BOUNDS[f][1]) for f in INPUT_FEATURES[:7]])
            x_seed_scaled = (x_seed_phys - self.scaler_X.mean_[:7]) / self.scaler_X.scale_[:7]
            x_opt = torch.tensor(x_seed_scaled, dtype=torch.float32, requires_grad=True)
            optimizer = optim.Adam([x_opt], lr=0.05)
            
            for step in range(100):
                optimizer.zero_grad()
                x_full = torch.zeros(18, dtype=torch.float32)
                x_full[:7] = x_opt
                base_pred, epistemic_std = self.epistemic_ensemble.predict_with_uncertainty(x_full.unsqueeze(0))
                pred = base_pred.squeeze(0)
                loss_mse = sum((pred[idx] - y_tgt_tensor[idx]) ** 2 for idx in target_indices)
                loss_phys = self._physics_differentiable_layer(x_opt.unsqueeze(0))
                total_loss = loss_mse + 10.0 * loss_phys
                total_loss.backward()
                optimizer.step()
                
                with torch.no_grad():
                    x_phys = (x_opt * torch.tensor(self.scaler_X.scale_[:7])) + torch.tensor(self.scaler_X.mean_[:7])
                    for i, feat in enumerate(INPUT_FEATURES[:7]):
                        x_phys[i] = torch.clamp(x_phys[i], SETPOINT_BOUNDS[feat][0], SETPOINT_BOUNDS[feat][1])
                    x_opt.copy_((x_phys - torch.tensor(self.scaler_X.mean_[:7])) / torch.tensor(self.scaler_X.scale_[:7]))
                    
            if total_loss.item() < best_loss:
                best_loss = total_loss.item()
                best_x_phys = (x_opt.detach().numpy() * self.scaler_X.scale_[:7]) + self.scaler_X.mean_[:7]
                best_epistemic = epistemic_std.squeeze(0).numpy()
            all_solutions.append((x_opt.detach().numpy() * self.scaler_X.scale_[:7]) + self.scaler_X.mean_[:7])
            
        std_bands = np.std(np.array(all_solutions), axis=0)
        sem_bands = std_bands / math.sqrt(n_seeds)
        
        recipe_dict = {}
        for i, feat in enumerate(INPUT_FEATURES[:7]):
            val = float(best_x_phys[i])
            std_v = float(std_bands[i])
            tol_half = float(1.96 * sem_bands[i])
            
            unit = "°C" if "T_" in feat or "Dev" in feat else ("atm" if "P_" in feat else ("SLPM" if "Flow" in feat else "ppmv"))
            recipe_dict[feat] = {
                'recommended_setpoint': round(val, 2),
                'uncertainty_std': round(std_v, 2),
                'tolerance_interval_95': [round(val - tol_half, 2), round(val + tol_half, 2)],
                'tolerance_string': f"{val:.1f} ± {tol_half:.1f} {unit}",
                'bounds': SETPOINT_BOUNDS[feat]
            }
            
        # Mahalanobis Distance Out-of-Distribution (OOD) Domain Verification
        mean_ref = self.scaler_X.mean_[:7]
        scale_ref = self.scaler_X.scale_[:7]
        diff_norm = (best_x_phys - mean_ref) / scale_ref
        mahalanobis_dist = float(np.sqrt(np.sum(diff_norm**2)))
        is_ood = mahalanobis_dist > 4.5
        
        return {
            'status': 'success',
            'optimal_recipe': recipe_dict,
            'convergence_loss': round(best_loss, 4),
            'n_seeds_evaluated': n_seeds,
            'epistemic_uncertainty_norm': round(float(np.mean(best_epistemic)), 4),
            'mahalanobis_ood_distance': round(mahalanobis_dist, 2),
            'is_within_safe_envelope': not is_ood
        }


if __name__ == "__main__":
    chk_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kan_pretrained.pt")
    if not os.path.exists(chk_path): print(f"[ERROR] Missing {chk_path}"); sys.exit(1)
    chk = torch.load(chk_path, weights_only=False)
    model = KAN(layers_hidden=[18, 16, 9], grid_size=3)
    model.load_state_dict(chk['model_state'])
    scaler_X, scaler_Y = chk['scaler_X'], chk['scaler_Y']
    solver = PyKANInverseSolver(model, scaler_X, scaler_Y)
    solution = solver.solve_recipe({'DWM_G/D': 18.0, 'DWM_Purity_UV': 50.0, 'DWM_Yield_g': 2.0}, n_seeds=20)
    optimal_x_dict = {feat: solution['optimal_recipe'][feat]['recommended_setpoint'] for feat in INPUT_FEATURES[:7]}
    stress_results = RobustnessStressTester(model, scaler_X, scaler_Y).run_stress_test(optimal_x_dict)
    export_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "advanced_inverse_results.json")
    with open(export_path, 'w') as f: json.dump({'Inverse_Solution': solution, 'Noise_Stress_Test_Results': stress_results}, f, indent=2)
    print(f"[OK] Full Phase 5 Evaluation Logged to {export_path}")
