# -*- coding: utf-8 -*-
"""
Gage FlyBrain anomaly detection layer.

Built on flycns (pip install flycns), which implements the published
whole-brain leaky integrate-and-fire model (Shiu et al., Nature 2024) over
the real MaleCNS v1.0 connectome (Berg et al., Cell 2026, 166,700 neurons,
25.6M connections, DOI 10.1016/j.cell.2026.08.015, CC BY 4.0).

WHAT THIS DOES
---------------
1. Takes a farm sensor reading (temperature, humidity, soil moisture, etc.)
2. Encodes it as a driven input into a subset of "sensory" neurons
3. Runs the real connectome's LIF simulation forward
4. Compares the resulting network-wide firing pattern against a learned
   baseline (built from the farm's own historical normal readings)
5. Returns an anomaly score: how far this reading's neural response is
   from what "normal" looks like for this specific field

WHAT THIS IS HONEST ABOUT
---------------------------
Mapping agricultural sensor channels onto the fly's real sensory neuron
types (which evolved for smell, vision, touch, not soil moisture) is a
genuine design choice, not an established, validated correspondence.
The encoding used here (random consistent projection into a driven neuron
subset) is a defensible, simple, honest starting point: it uses the real
connectome's topology and dynamics, but makes no claim that this is the
biologically "correct" way to present agricultural data to fly neurons.
Say this plainly in any writeup, do not oversell it as biologically
validated.

RUNNING ON THE REAL CONNECTOME VS. A SYNTHETIC TEST GRAPH
------------------------------------------------------------
This module works identically on:
  - A small synthetic test graph (default here, no download needed,
    good for demos, CI, fast iteration)
  - The real compiled MaleCNS v1.0 connectome (166,700 neurons), once
    you have run the flycns compilation step on the real Janelia tables
    (see `load_real_malecns()` below, requires ~14GB disk + a slow
    download from Janelia/Google Cloud Storage -- do this on your own
    machine or a Kaggle/Colab session with enough disk, not somewhere
    with restricted network access)

Only the graph passed into FlyBrainAnomalyDetector changes between the
two cases. Everything else (encoding, scoring) is unchanged.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from pathlib import Path

from flycns.dynamics.lif import LIFReference, Drive, LIFParams


# ============================================================
# Synthetic test graph (no download, works offline, for demos/CI)
# ============================================================
def build_synthetic_graph(n_neurons: int = 2000, n_edges: int = 15000, seed: int = 42):
    """A small random sparse connectome, structurally shaped like a real
    compiled graph (CSR format), for testing and demos without the ~14GB
    real MaleCNS download. NOT the real connectome -- swap for
    load_real_malecns() before claiming results are on real fly data."""
    rng = np.random.default_rng(seed)
    edges_per_neuron = rng.multinomial(n_edges, np.ones(n_neurons) / n_neurons)
    indptr = np.concatenate([[0], np.cumsum(edges_per_neuron)])
    indices = rng.integers(0, n_neurons, size=n_edges)
    weights_mv = rng.choice([1, -1], size=n_edges) * rng.uniform(0.1, 0.5, size=n_edges)
    return indptr, indices, weights_mv, n_neurons


# ============================================================
# Real MaleCNS v1.0 connectome loader (requires download, run once,
# then cache locally -- do NOT run this in a network-restricted sandbox)
# ============================================================
def load_real_malecns(raw_tables_dir: str, compiled_cache_dir: str):
    """Compile (once) and load the real 166,700-neuron MaleCNS v1.0
    connectome. raw_tables_dir must contain the four locked Janelia
    tables (see flycns.release.malecns_v1.TABLES for exact filenames,
    sizes, and download URLs -- total ~14GB). This step is slow and
    disk-heavy; run it once, then reuse compiled_cache_dir afterward.

    Returns (indptr, indices, weights_mv, n_neurons) in the same shape
    build_synthetic_graph() returns, so it's a drop-in swap.
    """
    from flycns.compiled import read_compiled
    from flycns.dynamics.lif import synaptic_weights
    from flycns.release.malecns_v1 import compile_malecns_v1

    compiled_path = Path(compiled_cache_dir)
    if not (compiled_path / "manifest.json").exists():
        # The neuron-to-neuron graph needs only the annotations, transmitter
        # and weights tables. The 13 GB synapse-point table only supplies
        # synapse centroids as positions for neurons without a soma location
        # (flycns reads it for nothing else here), so it is skipped.
        compile_malecns_v1(Path(raw_tables_dir), compiled_path,
                           synapse_centroids_for_missing=False, progress=print)

    graph = read_compiled(compiled_path)
    indptr = graph["csr_indptr"]
    indices = graph["csr_indices"]
    # flycns's own rule: presynaptic sign x synapse count x w_syn (0.275 mV).
    weights_mv = synaptic_weights(indptr, indices, graph["csr_count"], graph["neuron_sign"],
                                  LIFParams().w_syn_mv)
    n_neurons = len(indptr) - 1
    return indptr, indices, weights_mv, n_neurons


# ============================================================
# Sensor encoding: map a farm reading into driven neuron rates
# ============================================================
@dataclass
class SensorEncoder:
    """Maps named sensor channels to a consistent, fixed subset of driven
    neurons, so the same channel always drives the same neurons across
    runs (required for the baseline comparison to be meaningful)."""

    n_neurons: int
    channels: tuple[str, ...] = ("temperature", "humidity", "soil_moisture")
    neurons_per_channel: int = 20
    seed: int = 7
    rate_scale_hz: float = 4.0  # Hz per unit of normalized sensor value

    _channel_neurons: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        rng = np.random.default_rng(self.seed)
        for ch in self.channels:
            self._channel_neurons[ch] = rng.choice(
                self.n_neurons, size=self.neurons_per_channel, replace=False
            )

    def encode(self, readings: dict) -> Drive:
        """readings: dict of channel -> normalized value (expect roughly
        0 to 1 range; normalize against this field's own historical range
        before calling, so "unusual" is relative to THIS field, not a
        fixed global threshold)."""
        activate = {}
        for ch, value in readings.items():
            if ch not in self._channel_neurons:
                continue
            rate = max(0.0, float(value)) * self.rate_scale_hz * 50.0  # base rate + scaled drive
            for neuron_id in self._channel_neurons[ch]:
                activate[int(neuron_id)] = rate
        return Drive(activate=activate)


# ============================================================
# The anomaly detector itself
# ============================================================
class FlyBrainAnomalyDetector:
    def __init__(self, graph, encoder: SensorEncoder, sim_steps: int = 2000,
                 params: LIFParams | None = None, engine: str = "numpy"):
        indptr, indices, weights_mv, n_neurons = graph
        if engine == "torch":
            # flycns's PyTorch engine (float32, CUDA if available): same step rule.
            from flycns.dynamics.lif import LIFTorch

            self.engine = LIFTorch(indptr, indices, weights_mv, params or LIFParams())
        else:
            self.engine = LIFReference(indptr=indptr, indices=indices,
                                        weights_mv=weights_mv, params=params or LIFParams())
        self.encoder = encoder
        self.sim_steps = sim_steps
        self.n_neurons = n_neurons
        self._baseline_rates: np.ndarray | None = None
        self._baseline_std: np.ndarray | None = None

    def _simulate(self, readings: dict, seed: int = 0) -> np.ndarray:
        drive = self.encoder.encode(readings)
        run = self.engine.run(steps=self.sim_steps, drive=drive, seed=seed)
        return run.rates_hz()

    def fit_baseline(self, historical_readings: list[dict], seeds: list[int] | None = None):
        """Run the simulation over a farm's own historical "normal"
        readings, and store the resulting mean and spread of network
        activity as this field's baseline."""
        seeds = seeds or list(range(len(historical_readings)))
        all_rates = np.stack([
            self._simulate(r, seed=s) for r, s in zip(historical_readings, seeds)
        ])
        self._baseline_rates = all_rates.mean(axis=0)
        self._baseline_std = all_rates.std(axis=0) + 1e-6  # avoid divide-by-zero

    def score(self, current_readings: dict, seed: int = 999) -> dict:
        """Returns an anomaly score for a new reading, relative to this
        field's own fitted baseline. Higher score = more unusual."""
        if self._baseline_rates is None:
            raise RuntimeError("Call fit_baseline() first with this field's historical readings.")

        current_rates = self._simulate(current_readings, seed=seed)
        z_scores = (current_rates - self._baseline_rates) / self._baseline_std
        anomaly_score = float(np.sqrt(np.mean(z_scores ** 2)))  # RMS z-score across all neurons

        most_affected = np.argsort(-np.abs(z_scores))[:10]
        return {
            "anomaly_score": anomaly_score,
            "is_anomalous": anomaly_score > 2.0,  # starting threshold, tune on real data
            "most_affected_neurons": most_affected.tolist(),
            "current_mean_rate_hz": float(current_rates.mean()),
            "baseline_mean_rate_hz": float(self._baseline_rates.mean()),
        }


# ============================================================
# Demo / self-test, using the synthetic graph (no download needed)
# ============================================================
if __name__ == "__main__":
    graph = build_synthetic_graph(n_neurons=2000, n_edges=15000)
    n_neurons = graph[3]
    encoder = SensorEncoder(n_neurons=n_neurons)
    detector = FlyBrainAnomalyDetector(graph, encoder, sim_steps=1500)

    # Simulate 10 days of "normal" readings for one field
    rng = np.random.default_rng(1)
    normal_history = [
        {"temperature": rng.uniform(0.4, 0.6), "humidity": rng.uniform(0.4, 0.6),
         "soil_moisture": rng.uniform(0.4, 0.6)}
        for _ in range(10)
    ]
    print("Fitting baseline from 10 historical normal readings...")
    detector.fit_baseline(normal_history)
    print("Baseline fitted.\n")

    # Test 1: a normal-looking new reading
    normal_test = {"temperature": 0.52, "humidity": 0.48, "soil_moisture": 0.55}
    result_normal = detector.score(normal_test)
    print("NORMAL reading test:")
    print(f"  anomaly_score: {result_normal['anomaly_score']:.3f}")
    print(f"  is_anomalous:  {result_normal['is_anomalous']}\n")

    # Test 2: a genuinely unusual reading (e.g. severe drought signal)
    anomalous_test = {"temperature": 0.95, "humidity": 0.05, "soil_moisture": 0.02}
    result_anomaly = detector.score(anomalous_test)
    print("ANOMALOUS reading test (simulated drought):")
    print(f"  anomaly_score: {result_anomaly['anomaly_score']:.3f}")
    print(f"  is_anomalous:  {result_anomaly['is_anomalous']}")
