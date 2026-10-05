"""Part 5.2: time one FlyBrain simulation per reading on the real graph vs synthetic."""
import sys, time
sys.path.insert(0, ".")
from backend.ai import flybrain
from backend.config import get_settings
steps = get_settings().flybrain_sim_steps
reading = {"temperature": 0.5, "humidity": 0.5, "soil_moisture": 0.5}
for name, loader in (("synthetic", lambda: flybrain.build_synthetic_graph(2000, 15000)),
                     ("malecns_v1 (no synapse positions)",
                      lambda: flybrain.load_real_malecns("./models/malecns/raw", "./models/malecns/compiled"))):
    t = time.time(); g = loader(); load = time.time() - t
    det = flybrain.FlyBrainAnomalyDetector(g, flybrain.SensorEncoder(n_neurons=g[3]), sim_steps=steps)
    times = []
    for seed in range(2):
        t = time.time(); det._simulate(reading, seed=seed); times.append(time.time() - t)
    print(f"{name}: load {load:.1f}s, {steps} steps per reading: {', '.join(f'{x:.2f}s' for x in times)}", flush=True)
