"""Part 5.2: compile the real MaleCNS v1.0 graph from the three finished tables."""
import sys, time
sys.path.insert(0, ".")
from backend.ai import flybrain
t = time.time()
indptr, indices, w, n = flybrain.load_real_malecns("./models/malecns/raw", "./models/malecns/compiled")
print(f"LOADED neurons={n} edges={len(indices)} weight range mV [{w.min():.3f}, {w.max():.3f}] "
      f"excitatory edges {int((w > 0).sum())} inhibitory {int((w < 0).sum())} zero {int((w == 0).sum())} "
      f"in {time.time() - t:.0f}s", flush=True)
