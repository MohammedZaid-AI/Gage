"""Part 5.2: one FlyBrain simulation per reading on the real graph, GPU engine (flycns LIFTorch)."""
import sys, time
sys.path.insert(0, ".")
import torch
from backend.ai import flybrain
from backend.config import get_settings
steps = get_settings().flybrain_sim_steps
g = flybrain.load_real_malecns("./models/malecns/raw", "./models/malecns/compiled")
reading = {"temperature": 0.5, "humidity": 0.5, "soil_moisture": 0.5}
det = flybrain.FlyBrainAnomalyDetector(g, flybrain.SensorEncoder(n_neurons=g[3]), sim_steps=steps, engine="torch")
print("device:", det.engine.device, "| GPU memory after load MB:", round(torch.cuda.memory_allocated() / 2**20))
times = []
for seed in range(3):
    t = time.time(); r = det._simulate(reading, seed=seed); torch.cuda.synchronize(); times.append(time.time() - t)
print(f"malecns_v1 torch/{det.engine.device}: {steps} steps per reading: {', '.join(f'{x:.2f}s' for x in times)}; "
      f"mean rate {r.mean():.3f} Hz", flush=True)
