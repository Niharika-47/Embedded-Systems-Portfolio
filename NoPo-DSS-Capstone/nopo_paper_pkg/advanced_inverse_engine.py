import os
import sys
import time
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.optimize import differential_evolution, dual_annealing, minimize
import joblib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nopo_paper_pkg.kan_model import KAN
from nopo_paper_pkg.synthetic_generator import calculate_secondary_parameters

SETPOINT_BOUNDS = {
    'P_CO_atm': (10.0, 90.0), 'T_rxn_mean_C': (800.0, 1150.0), 'T_spread_C': (0.0, 80.0),
    'Flow_CO_SLPM': (100.0, 1000.0), 'Flow_Fe_Precursor_SLPM': (10.0, 350.0),
    'H2O_Flow_ppmv': (1.0, 50.0), 'Zone_SP_Dev_C': (-35.0, 15.0)
}

TARGET_COLS = [
    'DWM_Yield_g', 'DWM_G/D', 'DWM_Purity_UV', 'DWM_Ni_ppm_Axial', 'DWM_Ni_ppm_Radial',
    'DWM_Fe_ppm_Axial', 'DWM_Fe_ppm_Radial', 'DWM_Cr_ppm_Axial', 'DWM_Cr_ppm_Radial'
]

class AugmentedLagrangianKANInverseSolver:
    def __init__(self, model_path, scaler_X_path, scaler_y_path):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = KAN([18, 16, 9], grid_size=3).to(self.device)
        checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
        self.model.load_state_dict(checkpoint['model_state'])
        self.model.eval()
        
        self.scaler_X = checkpoint['scaler_X']
        self.scaler_y = checkpoint['scaler_Y']
        
        self.bounds_min = torch.tensor([SETPOINT_BOUNDS[k][0] for k in SETPOINT_BOUNDS.keys()], device=self.device)
        self.bounds_max = torch.tensor([SETPOINT_BOUNDS[k][1] for k in SETPOINT_BOUNDS.keys()], device=self.device)
        
    def _physics_differentiable(self, x_raw):
        """Differentiable approximation of physical constraints."""
        P_CO = x_raw[:, 0]
        T_rxn = x_raw[:, 1]
        T_spread = x_raw[:, 2]
        Q_CO = x_raw[:, 3]
        
        # 1. Sonic Velocity v_gas (Simplified)
        v_gas = (Q_CO / (P_CO * 10)) * (T_rxn / 300.0)
        
        # 2. Residence Time
        tau_res = 1000.0 / (v_gas + 1e-6)
        
        return v_gas, tau_res, T_spread
        
    def solve(self, target_qualities, initial_guess=None, max_iter=300):
        if initial_guess is None:
            initial_guess = (self.bounds_min + self.bounds_max) / 2.0
            
        x = initial_guess.clone().detach().requires_grad_(True)
        optimizer = torch.optim.Adam([x], lr=0.05)
        
        y_target = torch.tensor(self.scaler_y.transform([target_qualities]), dtype=torch.float32, device=self.device)
        
        # KKT Multipliers (Lambda) & Penalty (Mu)
        lambdas = torch.zeros(3, device=self.device)  # 3 constraints
        mu = 10.0
        
        best_x = None
        best_loss = float('inf')
        
        start_time = time.time()
        
        for i in range(max_iter):
            optimizer.zero_grad()
            
            # Project back to bounds softly using Sigmoid or just detach projection
            with torch.no_grad():
                x.clamp_(self.bounds_min, self.bounds_max)
                
            # Need to compute 18 features (using numpy bridge since synthetic is numpy)
            # In a true differentiable graph, we would re-write physics in torch.
            # For exact autograd without breaking graph, we approximate the physics graph:
            x_np = x.detach().cpu().numpy().reshape(1, -1)
            df_in = pd.DataFrame(x_np, columns=['P_CO_atm', 'T_rxn_mean_C', 'T_spread_C', 'Flow_CO_SLPM', 'Flow_Fe_Precursor_SLPM', 'H2O_Flow_ppmv', 'Zone_SP_Dev_C'])
            physics_df = calculate_secondary_parameters(df_in)
            physics_np = physics_df.values
            
            # Form full 18D vector
            full_x_np = np.hstack([x_np, physics_np])
            full_x_scaled = self.scaler_X.transform(full_x_np)
            full_x_t = torch.tensor(full_x_scaled, dtype=torch.float32, device=self.device)
            
            # Hack for gradients: we need pseudo-gradients through the physics mapping
            # y = model(full_x_t). We'll optimize x by relying on the MLP approximation or local gradients.
            # To make it fully end-to-end differentiable, we approximate full_x_t linearly from x around local point.
            # Here we just use a simplified direct proxy for speed if autograd fails on numpy.
            # Better: We train a tiny proxy network or just use KKT on setpoints!
            
            # For demonstration in the paper engine, we just evaluate model and use numeric Jacobian, OR
            # pure Autograd if we map physics to PyTorch.
            
            # Forward Pass
            full_x_t.requires_grad_(True)
            y_pred = self.model(full_x_t)
            
            mse_loss = torch.nn.functional.mse_loss(y_pred, y_target)
            
            # Constraints
            v_gas, tau_res, T_spread = self._physics_differentiable(x.unsqueeze(0))
            
            g1 = v_gas - 340.0         # g1 <= 0 (v_gas < 340)
            g2 = 1.0 - tau_res         # g2 <= 0 (tau_res >= 1.0)
            g3 = T_spread - 50.0       # g3 <= 0 (T_spread <= 50)
            
            g_tensor = torch.cat([g1.view(-1), g2.view(-1), g3.view(-1)])
            
            # Augmented Lagrangian Loss
            penalty = torch.sum(lambdas * g_tensor) + (mu / 2.0) * torch.sum(torch.relu(g_tensor)**2)
            
            # We compute gradients w.r.t full_x_t, then project back to x via Jacobian
            loss = mse_loss + penalty
            loss.backward()
            
            # Manual local gradient step (since full_x_t was detached from x due to numpy)
            with torch.no_grad():
                grad_x = full_x_t.grad[:, :7] # First 7 are the primary setpoints
                x -= 0.1 * grad_x.squeeze()
                
                # Update KKT Multipliers
                lambdas = torch.max(torch.zeros_like(lambdas), lambdas + mu * g_tensor)
                mu = min(mu * 1.05, 1000.0) # Penalty schedule
            
            current_loss = loss.item()
            if current_loss < best_loss:
                best_loss = current_loss
                best_x = x.clone().detach().cpu().numpy()
                
        latency = (time.time() - start_time) * 1000
        
        # Verify final constraint violations
        v, tau, T_s = self._physics_differentiable(torch.tensor(best_x).to(self.device).unsqueeze(0))
        violations = 0
        if v.item() > 340: violations += 1
        if tau.item() < 1.0: violations += 1
        if T_s.item() > 50.0: violations += 1
        
        return best_x, latency, mse_loss.item(), violations

class RealTimeKANMPC:
    def __init__(self, solver):
        self.solver = solver
        
    def solve_trajectory(self, current_state, target_qualities, horizon=5):
        trajectory = []
        state = np.array(current_state)
        for h in range(horizon):
            target, latency, mse, viol = self.solver.solve(target_qualities, initial_guess=torch.tensor(state))
            # Simulate physical slew-rate limit
            state = state + np.clip(target - state, -10, 10)
            trajectory.append(state.copy())
        return np.array(trajectory)

class ParetoManifoldNavigator:
    def __init__(self, solver):
        self.solver = solver
        
    def navigate(self, weights):
        # E.g., weights = {'Yield': 0.8, 'GD': 0.1, 'Purity': 0.1}
        # In a real scenario, adjusts the loss function dynamically.
        # Here we mock the Pareto shift by manipulating target priorities.
        base_target = [2.5, 15.0, 60.0, 50, 50, 100, 100, 20, 20]
        # Modulate based on weights
        base_target[0] *= (weights.get('Yield', 0.33) * 3)
        base_target[1] *= (weights.get('GD', 0.33) * 3)
        return self.solver.solve(base_target)

def evaluate_blackbox(x_raw_1d, solver, y_target_scaled):
    # Used for SciPy benchmark (DE, Nelder-Mead)
    x_np = x_raw_1d.reshape(1, -1)
    df_in = pd.DataFrame(x_np, columns=['P_CO_atm', 'T_rxn_mean_C', 'T_spread_C', 'Flow_CO_SLPM', 'Flow_Fe_Precursor_SLPM', 'H2O_Flow_ppmv', 'Zone_SP_Dev_C'])
    physics_df = calculate_secondary_parameters(df_in)
    physics_np = physics_df.values
    full_x_np = np.hstack([x_np, physics_np])
    full_x_scaled = solver.scaler_X.transform(full_x_np)
    full_x_t = torch.tensor(full_x_scaled, dtype=torch.float32, device=solver.device)
    
    with torch.no_grad():
        y_pred = solver.model(full_x_t)
        
    mse = torch.nn.functional.mse_loss(y_pred, torch.tensor(y_target_scaled, dtype=torch.float32, device=solver.device)).item()
    
    # Penalties
    v_gas, tau_res, T_spread = solver._physics_differentiable(torch.tensor(x_np, device=solver.device))
    pen = 0
    if v_gas.item() > 340: pen += 1000
    if tau_res.item() < 1.0: pen += 1000
    if T_spread.item() > 50: pen += 1000
    
    return mse + pen

class MultiOptimizerBenchmarkSuite:
    def __init__(self, solver):
        self.solver = solver
        self.bounds = [SETPOINT_BOUNDS[k] for k in SETPOINT_BOUNDS.keys()]
        
    def run_benchmarks(self, num_trials=5):
        print(f"Running {num_trials} Multi-Optimizer Benchmark Trials...")
        results = []
        
        for i in range(num_trials):
            # Generate random target
            target_qualities = [np.random.uniform(1.0, 3.5), np.random.uniform(5.0, 25.0), np.random.uniform(20.0, 80.0),
                                50, 50, 100, 100, 20, 20]
            y_target_scaled = self.solver.scaler_y.transform([target_qualities])
            
            # 1. PI-VRBF-KAN Augmented Lagrangian
            _, latency_kan, mse_kan, viol_kan = self.solver.solve(target_qualities)
            results.append({"Optimizer": "PI-VRBF-KAN (AugLag)", "Latency_ms": latency_kan, "MSE": mse_kan, "Violations": viol_kan})
            
            # 2. Differential Evolution (Genetic Algorithm Proxy)
            start = time.time()
            res_de = differential_evolution(evaluate_blackbox, self.bounds, args=(self.solver, y_target_scaled), maxiter=20, popsize=5)
            latency_de = (time.time() - start) * 1000
            viol_de = 0 if evaluate_blackbox(res_de.x, self.solver, y_target_scaled) < 500 else 1
            results.append({"Optimizer": "Differential Evolution (GA)", "Latency_ms": latency_de, "MSE": res_de.fun % 1000, "Violations": viol_de})
            
            # 3. Dual Annealing (Stochastic)
            start = time.time()
            res_da = dual_annealing(evaluate_blackbox, self.bounds, args=(self.solver, y_target_scaled), maxiter=20)
            latency_da = (time.time() - start) * 1000
            viol_da = 0 if evaluate_blackbox(res_da.x, self.solver, y_target_scaled) < 500 else 1
            results.append({"Optimizer": "Dual Annealing (Stochastic)", "Latency_ms": latency_da, "MSE": res_da.fun % 1000, "Violations": viol_da})
            
            # 4. Nelder-Mead (Simplex)
            start = time.time()
            x0 = np.array([(b[0]+b[1])/2 for b in self.bounds])
            res_nm = minimize(evaluate_blackbox, x0, args=(self.solver, y_target_scaled), method='Nelder-Mead', options={'maxiter': 100})
            latency_nm = (time.time() - start) * 1000
            viol_nm = 0 if evaluate_blackbox(res_nm.x, self.solver, y_target_scaled) < 500 else 1
            results.append({"Optimizer": "Nelder-Mead (Simplex)", "Latency_ms": latency_nm, "MSE": res_nm.fun % 1000, "Violations": viol_nm})
            
        df = pd.DataFrame(results)
        summary = df.groupby('Optimizer').agg({
            'Latency_ms': 'mean',
            'MSE': 'mean',
            'Violations': 'mean'
        }).reset_index()
        
        # Format output
        summary['Violations'] = summary['Violations'] * 100 # % constraint violations
        
        out_path = os.path.join(os.path.dirname(__file__), "inverse_multi_optimizer_benchmarks.json")
        summary.to_json(out_path, orient='records')
        print(summary.to_markdown(index=False))
        print(f"\n[SUCCESS] Benchmarks saved to {out_path}")
        return summary

if __name__ == "__main__":
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(pkg_dir, "kan_pretrained.pt")
    scaler_x = os.path.join(pkg_dir, "scaler_X.pkl")
    scaler_y = os.path.join(pkg_dir, "scaler_Y.pkl")
    
    print("Initializing Augmented Lagrangian KAN Inverse Solver...")
    solver = AugmentedLagrangianKANInverseSolver(model_path, scaler_x, scaler_y)
    
    print("Running Single Optimization...")
    best_x, lat, mse, viol = solver.solve([2.0, 12.0, 50.0, 50, 50, 100, 100, 20, 20])
    print(f"Solution: {best_x}, Latency: {lat:.1f}ms, Violations: {viol}")
    
    benchmark = MultiOptimizerBenchmarkSuite(solver)
    benchmark.run_benchmarks(num_trials=5)
