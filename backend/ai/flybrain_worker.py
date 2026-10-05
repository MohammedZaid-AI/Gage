"""FlyBrain simulations, run in a separate worker process (see
services/anomaly.py). The LIF loop is CPU-bound Python/NumPy that holds the
interpreter lock; in the server process it slowed sensor uploads during the
daily baseline fit (p95 344 ms vs ~100 ms without it, 2026-10-05). Here it
cannot. Everything passed in and out is small and picklable: readings as
dicts, baselines as arrays, scores as floats. The graph is built (or loaded)
once per worker process and cached.
"""
import numpy as np

_cache: dict = {}


def _detector(graph_spec: tuple, sim_steps: int, engine: str):
    from backend.ai import flybrain

    key = (graph_spec, sim_steps, engine)
    if key not in _cache:
        if graph_spec[0] == "malecns":
            graph = flybrain.load_real_malecns(graph_spec[1], graph_spec[2])
        else:
            graph = flybrain.build_synthetic_graph(n_neurons=2000, n_edges=15000)
        _cache.clear()      # one graph per worker: the real one is ~0.5 GB
        _cache[key] = flybrain.FlyBrainAnomalyDetector(
            graph, flybrain.SensorEncoder(n_neurons=graph[3]), sim_steps=sim_steps, engine=engine)
    return _cache[key]


def fit(graph_spec: tuple, sim_steps: int, engine: str, base: list[dict],
        heldout: list[dict]) -> dict:
    """Fit the baseline on `base` and score `heldout` against it."""
    det = _detector(graph_spec, sim_steps, engine)
    det.fit_baseline(base)
    return {"rates": det._baseline_rates, "std": det._baseline_std,
            "heldout_scores": [det.score(r)["anomaly_score"] for r in heldout]}


def score(graph_spec: tuple, sim_steps: int, engine: str, rates: np.ndarray, std: np.ndarray,
          reading: dict) -> float:
    det = _detector(graph_spec, sim_steps, engine)
    det._baseline_rates, det._baseline_std = rates, std
    return float(det.score(reading)["anomaly_score"])
