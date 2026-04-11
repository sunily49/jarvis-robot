"""
Anomaly Detection Service — baseline learning + threshold alerts.

Phase 1: Statistical thresholds (mean ± 2σ)
Phase 2 (future): ML classifier
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

BASELINE_WINDOW = 1000  # Number of samples for baseline


@dataclass
class AnomalyResult:
    is_anomaly: bool
    severity: str       # "none", "low", "medium", "high"
    description: str
    sensor: str
    value: float
    threshold_low: float
    threshold_high: float


class AnomalyService:
    """Statistical anomaly detection with adaptive baselines."""

    def __init__(self) -> None:
        self._baselines: dict[str, deque] = defaultdict(lambda: deque(maxlen=BASELINE_WINDOW))
        self._stats: dict[str, dict] = {}  # {sensor: {mean, std}}
        logger.info("Anomaly service initialized")

    def record(self, sensor: str, value: float) -> None:
        """Record a sensor reading for baseline learning."""
        self._baselines[sensor].append(value)
        if len(self._baselines[sensor]) >= 50:
            values = np.array(self._baselines[sensor])
            self._stats[sensor] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values)),
            }

    def check(self, sensor: str, value: float) -> dict:
        """Check if a value is anomalous for the given sensor."""
        self.record(sensor, value)

        stats = self._stats.get(sensor)
        if not stats:
            return {"is_anomaly": False, "severity": "none", "description": "Insufficient baseline data"}

        mean = stats["mean"]
        std = max(stats["std"], 0.01)  # Avoid div by zero

        z_score = abs(value - mean) / std
        low = mean - 2 * std
        high = mean + 2 * std

        if z_score < 2:
            severity = "none"
            is_anomaly = False
        elif z_score < 3:
            severity = "low"
            is_anomaly = True
        elif z_score < 4:
            severity = "medium"
            is_anomaly = True
        else:
            severity = "high"
            is_anomaly = True

        description = ""
        if is_anomaly:
            direction = "above" if value > mean else "below"
            description = f"{sensor} is {z_score:.1f}σ {direction} baseline ({value:.1f} vs mean {mean:.1f})"

        return {
            "is_anomaly": is_anomaly,
            "severity": severity,
            "description": description,
            "sensor": sensor,
            "value": value,
            "threshold_low": round(low, 2),
            "threshold_high": round(high, 2),
            "z_score": round(z_score, 2),
        }

    def get_baselines(self) -> dict:
        """Get current baseline stats for all sensors."""
        return {
            sensor: {
                "mean": round(s["mean"], 2),
                "std": round(s["std"], 2),
                "samples": len(self._baselines[sensor]),
            }
            for sensor, s in self._stats.items()
        }
