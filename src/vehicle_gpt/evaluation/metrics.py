from __future__ import annotations

import statistics


def classification_metrics(gold: list[str], predicted: list[str]) -> dict:
    if len(gold) != len(predicted) or not gold:
        raise ValueError("gold and prediction lists must have equal non-zero length")
    labels = sorted(set(gold) | set(predicted))
    per = {}
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, predicted))
        fp = sum(g != label and p == label for g, p in zip(gold, predicted))
        fn = sum(g == label and p != label for g, p in zip(gold, predicted))
        per[label] = {
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "support": sum(g == label for g in gold),
        }
    return {
        "accuracy": sum(g == p for g, p in zip(gold, predicted)) / len(gold),
        "macro_precision": statistics.fmean(x["precision"] for x in per.values()),
        "macro_recall": statistics.fmean(x["recall"] for x in per.values()),
        "per_class": per,
        "n": len(gold),
    }


def latency_metrics(values_ms: list[float]) -> dict:
    if not values_ms:
        return {"count": 0, "median_ms": None, "p95_ms": None}
    ordered = sorted(values_ms)
    idx = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999) - 1))
    return {
        "count": len(ordered),
        "median_ms": statistics.median(ordered),
        "p95_ms": ordered[idx],
    }
