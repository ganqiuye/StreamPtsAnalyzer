from __future__ import annotations

import numpy as np


def lttb_downsample(
    x: np.ndarray, y: np.ndarray, n_out: int
) -> tuple[np.ndarray, np.ndarray]:
    """Largest-Triangle-Three-Buckets downsampling."""
    if len(x) <= n_out or n_out < 3:
        return x, y

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    bucket_size = (n - 2) / (n_out - 2)
    sampled = [0]
    a = 0

    for i in range(1, n_out - 1):
        start = int((i - 1) * bucket_size) + 1
        end = int(i * bucket_size) + 1
        end = min(end, n)
        bucket_x = x[start:end]
        bucket_y = y[start:end]
        if len(bucket_x) == 0:
            continue

        next_start = int(i * bucket_size) + 1
        next_end = int((i + 1) * bucket_size) + 1
        next_end = min(next_end, n)
        avg_x = float(np.mean(x[next_start:next_end])) if next_end > next_start else x[-1]
        avg_y = float(np.mean(y[next_start:next_end])) if next_end > next_start else y[-1]

        ax, ay = x[a], y[a]
        areas = np.abs(
            (ax - avg_x) * (bucket_y - ay) - (ax - bucket_x) * (avg_y - ay)
        )
        idx = int(np.argmax(areas))
        a = start + idx
        sampled.append(a)

    sampled.append(n - 1)
    idxs = np.array(sampled, dtype=int)
    return x[idxs], y[idxs]
