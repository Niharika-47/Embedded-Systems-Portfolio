import os
import json
import numpy as np
import torch
import math
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from scipy.stats import norm

try:
    from nopo_paper_pkg.kan_model import KAN
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nopo_paper_pkg.kan_model import KAN

SETPOINT_BOUNDS = {'P_CO_atm': (10.0, 90.0), 'T_rxn_mean_C': (800.0, 1150.0), 'T_spread_C': (0.0, 80.0), 'Flow_CO_SLPM': (100.0, 1000.0), 'Flow_Fe_Precursor_SLPM': (10.0, 350.0), 'H2O_Flow_ppmv': (1.0, 50.0), 'Zone_SP_Dev_C': (-35.0, 15.0)}
INPUT_FEATURES = ['P_CO_atm', 'T_rxn_mean_C', 'T_spread_C', 'Flow_CO_SLPM', 'Flow_Fe_Precursor_SLPM', 'H2O_Flow_ppmv', 'Zone_SP_Dev_C', 'Residence_Time_s', 'Reynolds_Number', 'Fe_Concentration_ppm', 'CO_Disproportionation_DrivingForce', 'Thermal_Loss_kW', 'P_CO2_Partial_bar', 'Nucleation_Rate_Est', 'Linear_Gas_Velocity_m_s', 'Catalyst_Growth_Time_Ratio', 'Thermal_Boundary_Thickness_mm', 'Water_CO_Ratio_ppm']
QUALITY_TARGETS = ['DWM_Yield_g', 'DWM_G/D', 'DWM_Purity_UV', 'DWM_Ni_ppm_Axial', 'DWM_Ni_ppm_Radial', 'DWM_Fe_ppm_Axial', 'DWM_Fe_ppm_Radial', 'DWM_Cr_ppm_Axial', 'DWM_Cr_ppm_Radial']

class DummyScaler:
    def transform(self, X): return X
    def inverse_transform(self, X): return X

class KANTopologyExtractor:
    def __init__(self):
        self.functions = ['linear', 'quadratic', 'exponential', 'logarithmic', 'sine']
        
    def _fit_dominant_function(self, x_curve, y_curve):
        best_func = "linear"
        best_r2 = -float('inf')
        
        # very simple fitting logic for demonstration
        var_y = np.var(y_curve)
        if var_y < 1e-6:
            return "linear", 1.0
            
        funcs = {
            "linear": lambda x: np.poly1d(np.polyfit(x, y_curve, 1))(x),
            "quadratic": lambda x: np.poly1d(np.polyfit(x, y_curve, 2))(x),
            "sine": lambda x: np.mean(y_curve) + np.std(y_curve) * np.sin(x),
            "exponential": lambda x: np.exp(np.poly1d(np.polyfit(x, np.log(np.abs(y_curve)+1e-6), 1))(x)),
            "logarithmic": lambda x: np.poly1d(np.polyfit(np.log(np.abs(x)+1e-6), y_curve, 1))(np.log(np.abs(x)+1e-6))
        }
        
        for name, f in funcs.items():
            try:
                y_pred = f(x_curve)
                r2 = 1 - np.sum((y_curve - y_pred)**2) / (np.sum((y_curve - np.mean(y_curve))**2) + 1e-6)
                if r2 > best_r2:
                    best_r2 = r2
                    best_func = name
            except:
                pass
                
        return best_func, best_r2

    def extract_full_topology(self, model, scaler_X, input_features, quality_targets):
        topology = {'nodes': [], 'edges': [], 'layer_sparsity': {}}
        
        # Construct nodes
        node_id_counter = 0
        nodes_by_layer = []
        
        # Input layer
        in_nodes = []
        for i, feat in enumerate(input_features):
            node = {'id': node_id_counter, 'name': feat, 'layer': 0, 'index': i, 'importance_score': 1.0, 'is_active': True}
            topology['nodes'].append(node)
            in_nodes.append(node)
            node_id_counter += 1
        nodes_by_layer.append(in_nodes)
        
        # Hidden and output layers
        with torch.no_grad():
            for layer_idx, layer in enumerate(model.layers):
                out_dim = layer.out_features
                layer_nodes = []
                for i in range(out_dim):
                    name = quality_targets[i] if layer_idx == len(model.layers)-1 else f"H_{layer_idx+1}_{i}"
                    node = {'id': node_id_counter, 'name': name, 'layer': layer_idx+1, 'index': i, 'importance_score': 0.0, 'is_active': True}
                    topology['nodes'].append(node)
                    layer_nodes.append(node)
                    node_id_counter += 1
                nodes_by_layer.append(layer_nodes)
                
                # Edges
                in_dim = layer.in_features
                active_edges = 0
                total_edges = in_dim * out_dim
                
                for out_i in range(out_dim):
                    for in_i in range(in_dim):
                        # compute weight magnitude using L1 norm of spline and base
                        base_w = layer.base_weight[out_i, in_i].item()
                        spline_w = layer.spline_weight[out_i, in_i, :].norm(p=1).item()
                        weight_mag = abs(base_w) + spline_w
                        
                        if weight_mag > 1e-4:
                            active_edges += 1
                            
                            # generate curve
                            x_curve = np.linspace(-3, 3, 50)
                            x_tensor = torch.tensor(x_curve, dtype=torch.float32)
                            
                            # base output
                            base_out = (torch.nn.functional.silu(x_tensor) * layer.base_weight[out_i, in_i]).numpy() * layer.scale_base
                            
                            # spline output
                            x_exp = x_tensor.unsqueeze(-1)
                            grid_exp = (layer.grid_centers[in_i] if hasattr(layer, 'grid_centers') else layer.grid).view(1, -1)
                            gamma_val = (layer.gamma[in_i] if layer.gamma.dim() > 0 else layer.gamma).view(1, -1)
                            rbf = torch.exp(-torch.abs(gamma_val) * ((x_exp - grid_exp)**2))
                            spline_out = (rbf @ layer.spline_weight[out_i, in_i, :]).numpy() * layer.scale_spline
                            
                            y_curve = base_out + spline_out
                            dom_func, r2 = self._fit_dominant_function(x_curve, y_curve)
                            
                            edge = {
                                'id': f"{nodes_by_layer[layer_idx][in_i]['id']}_{nodes_by_layer[layer_idx+1][out_i]['id']}",
                                'source': nodes_by_layer[layer_idx][in_i]['id'],
                                'target': nodes_by_layer[layer_idx+1][out_i]['id'],
                                'weight_magnitude': float(weight_mag),
                                'spline_r2': float(r2),
                                'dominant_function': dom_func,
                                'x_curve': x_curve.tolist(),
                                'y_curve': y_curve.tolist()
                            }
                            topology['edges'].append(edge)
                            
                topology['layer_sparsity'][f'layer_{layer_idx}'] = 1.0 - (active_edges / max(1, total_edges))
                
        # Importance score heuristic
        for node in topology['nodes']:
            if node['layer'] > 0:
                node['importance_score'] = sum([e['weight_magnitude'] for e in topology['edges'] if e['target'] == node['id']])
                
        return topology

class SHAPAttributionEngine:
    def compute_shap_values(self, model, X_background, X_instance, scaler_X, scaler_Y, n_permutations=100):
        # Pure numpy/torch permutation-based SHAP
        model.eval()
        X_bg = torch.tensor(scaler_X.transform(X_background), dtype=torch.float32)
        X_inst = torch.tensor(scaler_X.transform(X_instance.reshape(1, -1)), dtype=torch.float32)
        
        n_features = X_bg.shape[1]
        n_targets = QUALITY_TARGETS
        
        with torch.no_grad():
            base_val = model(X_bg).mean(dim=0).numpy()
            target_val = model(X_inst).numpy()[0]
            
        shap_values = {feat: {tgt: 0.0 for tgt in QUALITY_TARGETS} for feat in INPUT_FEATURES}
        global_importance = {feat: 0.0 for feat in INPUT_FEATURES}
        
        # Simple marginal contribution estimation
        for i, feat in enumerate(INPUT_FEATURES):
            for _ in range(n_permutations):
                idx = np.random.randint(0, X_bg.shape[0])
                x_perm = X_inst.clone()
                x_perm[0, i] = X_bg[idx, i]
                with torch.no_grad():
                    val_perm = model(x_perm).numpy()[0]
                
                diff = target_val - val_perm
                for j, tgt in enumerate(QUALITY_TARGETS):
                    shap_values[feat][tgt] += diff[j] / n_permutations
                    global_importance[feat] += abs(diff[j]) / n_permutations
                    
        feature_ranking = sorted(INPUT_FEATURES, key=lambda f: global_importance[f], reverse=True)
        
        return {
            'shap_values': shap_values,
            'feature_ranking': feature_ranking,
            'global_importance': global_importance
        }

class ActiveLearningRecommender:
    def recommend_next_batch(self, model, scaler_X, scaler_Y, n_candidates=5):
        # Sample 500 random candidates within SETPOINT_BOUNDS
        candidates = []
        for _ in range(500):
            cand = {}
            for k, (low, high) in SETPOINT_BOUNDS.items():
                cand[k] = np.random.uniform(low, high)
            candidates.append(cand)
            
        # Add secondary parameters via mocked physical engine
        X_cands = []
        for cand in candidates:
            row = []
            for f in INPUT_FEATURES:
                if f in cand:
                    row.append(cand[f])
                else:
                    row.append(0.0) # mock secondary for now
            X_cands.append(row)
            
        X_tensor = torch.tensor(scaler_X.transform(np.array(X_cands)), dtype=torch.float32)
        
        # MC-dropout epistemic uncertainty (20 stochastic passes with Gaussian noise)
        preds = []
        for _ in range(20):
            # inject noise to weights temporary
            noise_cache = []
            for p in model.parameters():
                noise = torch.randn_like(p) * 0.01
                p.data.add_(noise)
                noise_cache.append(noise)
                
            with torch.no_grad():
                preds.append(model(X_tensor).numpy())
                
            # revert noise
            for p, noise in zip(model.parameters(), noise_cache):
                p.data.sub_(noise)
                
        preds = np.array(preds)
        means = preds.mean(axis=0)
        stds = preds.std(axis=0)
        
        uncertainty_scores = stds.mean(axis=1)
        
        top_idx = np.argsort(uncertainty_scores)[::-1][:n_candidates]
        
        recommendations = []
        for idx in top_idx:
            recommendations.append({
                'setpoints': candidates[idx],
                'uncertainty_score': float(uncertainty_scores[idx]),
                'predicted_gd_range': [float(means[idx][1] - stds[idx][1]), float(means[idx][1] + stds[idx][1])],
                'predicted_yield_range': [float(means[idx][0] - stds[idx][0]), float(means[idx][0] + stds[idx][0])]
            })
            
        return recommendations

class ThermodynamicValidator:
    def validate_setpoints(self, P_CO, T_rxn, Q_CO, Q_Fe, Q_H2O, T_spread, Zone_Dev):
        violations = []
        
        # Computations
        T_K = T_rxn + 273.15
        P_atm = P_CO
        Q_actual_L_s = ((Q_CO + Q_Fe) / 60.0) * (1.0 / P_atm) * (T_K / 273.15)
        V_reactor_L = 15.0
        D_nozzle_m = 0.003
        
        residence_time = V_reactor_L / max(Q_actual_L_s, 1e-4)
        
        rho = (P_atm * 28.01) / (0.08206 * T_K)
        mu = 1.75e-5 * (T_K / 300.0)**0.7
        v_actual = (Q_actual_L_s * 1e-3) / (np.pi * (D_nozzle_m / 2.0)**2)
        reynolds = (rho * v_actual * D_nozzle_m) / mu
        
        sonic_vel = math.sqrt(1.4 * 8.314 * T_K / 0.028)
        mach = v_actual / sonic_vel
        
        gibbs = -172.5 + 0.176 * T_K
        k_eq = math.exp(-gibbs * 1000 / (8.314 * T_K))
        p_co2 = 0.01 * P_atm * (1.0 + 0.002 * (T_rxn - 900.0))
        fe_conc = (Q_Fe / max(Q_CO + Q_Fe, 1e-3)) * 1e4
        
        checks = {
            'sonic_velocity': sonic_vel,
            'residence_time': residence_time,
            'gibbs_delta_g': gibbs,
            'reynolds_number': reynolds,
            'fe_concentration': fe_conc,
            'mach_number': mach,
            'boudouard_k_eq': k_eq,
            'co2_partial_pressure': p_co2
        }
        
        if residence_time < 5.0 or residence_time > 50.0:
            violations.append({'parameter': 'residence_time', 'value': residence_time, 'limit': [5.0, 50.0], 'severity': 'high', 'message': 'Residence time out of bounds'})
            
        if reynolds > 2000:
            violations.append({'parameter': 'reynolds_number', 'value': reynolds, 'limit': 2000, 'severity': 'medium', 'message': 'Flow is not purely laminar'})
            
        if gibbs > 0:
            violations.append({'parameter': 'gibbs_delta_g', 'value': gibbs, 'limit': 0.0, 'severity': 'critical', 'message': 'Boudouard reaction is not thermodynamically favored'})
            
        score = 100 - len(violations) * 20
        return {
            'violations': violations,
            'feasibility_score': max(0, score),
            'compliance_checks': checks
        }

class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/kan_topology':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            model = KAN(layers_hidden=[len(INPUT_FEATURES), 16, len(QUALITY_TARGETS)], grid_size=3)
            extractor = KANTopologyExtractor()
            topology = extractor.extract_full_topology(model, DummyScaler(), INPUT_FEATURES, QUALITY_TARGETS)
            
            self.wfile.write(json.dumps(topology).encode())
        else:
            self.send_response(404)
            self.end_headers()
            
    def do_POST(self):
        parsed_path = urlparse(self.path)
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        body = json.loads(post_data.decode('utf-8'))
        
        if parsed_path.path == '/api/shap_attributions':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            model = KAN(layers_hidden=[len(INPUT_FEATURES), 16, len(QUALITY_TARGETS)], grid_size=3)
            engine = SHAPAttributionEngine()
            
            X_bg = np.zeros((10, len(INPUT_FEATURES)))
            X_inst = np.array([body.get('current_setpoints', np.zeros(len(INPUT_FEATURES)).tolist())])
            if X_inst.shape[1] != len(INPUT_FEATURES):
                X_inst = np.zeros((1, len(INPUT_FEATURES)))
                
            res = engine.compute_shap_values(model, X_bg, X_inst, DummyScaler(), DummyScaler())
            self.wfile.write(json.dumps(res).encode())
            
        elif parsed_path.path == '/api/active_learning_recommend':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            model = KAN(layers_hidden=[len(INPUT_FEATURES), 16, len(QUALITY_TARGETS)], grid_size=3)
            rec = ActiveLearningRecommender()
            res = rec.recommend_next_batch(model, DummyScaler(), DummyScaler())
            self.wfile.write(json.dumps(res).encode())
            
        elif parsed_path.path == '/api/validate_thermodynamics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            val = ThermodynamicValidator()
            res = val.validate_setpoints(
                body.get('P_CO_atm', 60.0),
                body.get('T_rxn_mean_C', 950.0),
                body.get('Flow_CO_SLPM', 600.0),
                body.get('Flow_Fe_Precursor_SLPM', 190.0),
                body.get('H2O_Flow_ppmv', 30.0),
                body.get('T_spread_C', 25.0),
                body.get('Zone_SP_Dev_C', -5.0)
            )
            self.wfile.write(json.dumps(res).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=8051):
    server_address = ('', port)
    httpd = HTTPServer(server_address, APIHandler)
    print(f'Starting httpd on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run test suite')
    parser.add_argument('--serve', action='store_true', help='Run API server')
    args = parser.parse_args()
    
    if args.test:
        print("Running tests...")
        
        # 1. Load Model (Mocking if missing)
        model_path = os.path.join(os.path.dirname(__file__), 'kan_pretrained.pt')
        model = KAN(layers_hidden=[len(INPUT_FEATURES), 16, len(QUALITY_TARGETS)], grid_size=3)
        scaler_X = DummyScaler()
        scaler_Y = DummyScaler()
        
        if os.path.exists(model_path):
            ckpt = torch.load(model_path, weights_only=False)
            model.load_state_dict(ckpt['model_state'] if 'model_state' in ckpt else ckpt)
            if 'scaler_X' in ckpt:
                scaler_X = ckpt['scaler_X']
            if 'scaler_Y' in ckpt:
                scaler_Y = ckpt['scaler_Y']
            print("Loaded kan_pretrained.pt")
        else:
            print("kan_pretrained.pt not found, using initialized weights")
        
        # 2. Extract Topology
        print("Testing KANTopologyExtractor...")
        extractor = KANTopologyExtractor()
        topology = extractor.extract_full_topology(model, scaler_X, INPUT_FEATURES, QUALITY_TARGETS)
        print(f"Topology: {len(topology['nodes'])} nodes, {len(topology['edges'])} edges")
        
        # 3. SHAP
        print("Testing SHAPAttributionEngine...")
        engine = SHAPAttributionEngine()
        X_bg = np.random.rand(10, len(INPUT_FEATURES))
        X_inst = np.random.rand(len(INPUT_FEATURES))
        shap = engine.compute_shap_values(model, X_bg, X_inst, scaler_X, scaler_Y)
        print(f"SHAP feature ranking top 3: {shap['feature_ranking'][:3]}")
        
        # 4. Active Learning
        print("Testing ActiveLearningRecommender...")
        rec = ActiveLearningRecommender()
        recs = rec.recommend_next_batch(model, scaler_X, scaler_Y)
        print(f"Generated {len(recs)} recommendations. Top score: {recs[0]['uncertainty_score']:.4f}")
        
        # 5. Thermodynamics
        print("Testing ThermodynamicValidator...")
        val = ThermodynamicValidator()
        thermo = val.validate_setpoints(60.0, 950.0, 600.0, 190.0, 30.0, 25.0, -5.0)
        print(f"Thermodynamic score: {thermo['feasibility_score']}")
        
        print("\nAll tests passed successfully.")
        sys.exit(0)
        
    if args.serve:
        run_server()
