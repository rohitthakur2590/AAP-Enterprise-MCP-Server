# agent/detector.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import math

# scikit-learn only (no numpy required here)
try:
    from sklearn.ensemble import IsolationForest
except Exception:  # pragma: no cover
    IsolationForest = None  # handled below


# ----------------------------
# Helpers
# ----------------------------

_EXCLUDE_FOR_IQR = {
    "host", "source", "raw", "os_type", "image", "model", "serial",
    "license_status", "version", "version_major", "version_minor", "version_patch",
}

def _num(x):
    try:
        return float(x)
    except Exception:
        return None

def _bool01(x):
    if x is None:
        return None
    return 1.0 if bool(x) else 0.0

def _build_feature_matrix(rows: List[Dict[str, Any]]) -> Tuple[List[List[float]], List[str]]:
    """
    Build a robust numeric feature matrix from device facts + healthchecks.
    Missing values are median-imputed; zero-variance columns are dropped.
    """
    candidates = [
        # inventory-ish
        "mem_used_pct",
        "license_expired",             # 0/1
        "iface_total",
        "iface_enabled",
        "iface_enabled_ratio",
        "bgp_peers",
        "v4nets",
        "v6nets",
        "uptime_days",

        # healthchecks (if present)
        "hc_cpu_1min",
        "hc_cpu_5min",
        "hc_cpu_threshold",
        "hc_mem_util",
        "hc_mem_threshold",
        "hc_env_temp",
        "hc_env_temp_threshold",
        "hc_uptime_min",
        "hc_uptime_min_threshold",
    ]

    # Raw (with None)
    raw: List[List[float | None]] = []
    for r in rows:
        vec: List[float | None] = []
        for k in candidates:
            if k == "license_expired":
                v = _bool01(r.get(k))
            else:
                v = _num(r.get(k))
            vec.append(v)
        raw.append(vec)

    if not raw:
        return [], []

    n = len(rows)
    m = len(candidates)

    # Column-wise median impute & zero-variance drop
    cols = [[raw[i][j] for i in range(n)] for j in range(m)]

    medians: List[float | None] = []
    keep_mask: List[bool] = []
    for j, col in enumerate(cols):
        vals = [v for v in col if isinstance(v, (int, float))]
        if not vals:
            medians.append(None)
            keep_mask.append(False)
            continue
        vals.sort()
        L = len(vals)
        mid = L // 2
        if L % 2 == 1:
            med = float(vals[mid])
        else:
            med = 0.5 * (vals[mid - 1] + vals[mid])
        medians.append(med)
        keep_mask.append(not math.isclose(vals[0], vals[-1]))

    kept_names: List[str] = []
    X: List[List[float]] = []
    for i in range(n):
        row_vec: List[float] = []
        for j in range(m):
            if not keep_mask[j]:
                continue
            v = raw[i][j]
            if v is None:
                v = medians[j]
            # if still None (shouldn't happen), use 0
            row_vec.append(float(v if v is not None else 0.0))
        X.append(row_vec)

    for j in range(m):
        if keep_mask[j]:
            kept_names.append(candidates[j])

    return X, kept_names


# ----------------------------
# IsolationForest detector
# ----------------------------

def detect_outliers_iforest(
    rows: List[Dict[str, Any]],
    contamination: float = 0.10,
    random_state: int = 42,
) -> Tuple[List[Dict[str, Any]], List[str], List[float]]:
    """
    IsolationForest with robust preprocessing:
      - median-impute missing values
      - drop zero-variance columns
      - if predict() returns none, return top-k most anomalous by score_samples
    Returns (anomalies, feature_names, scores_for_those_anomalies).
    """
    if IsolationForest is None or not rows:
        return [], [], []

    X, feats = _build_feature_matrix(rows)
    if not feats or not X or not X[0]:
        return [], feats, []

    n = len(rows)
    # keep contamination sane
    contamination = float(max(0.01, min(0.5, contamination)))
    top_k = max(1, int(round(n * contamination)))

    clf = IsolationForest(
        n_estimators=300,
        contamination=contamination,
        max_features=1.0,
        bootstrap=False,
        random_state=random_state,
    )
    clf.fit(X)

    pred = clf.predict(X)             # -1 anomaly, 1 normal
    scores = clf.score_samples(X)     # higher = less anomalous

    idxs = [i for i, p in enumerate(pred) if p == -1]
    if not idxs:
        # force top-k lowest scores (most anomalous)
        ranked = sorted(range(n), key=lambda i: scores[i])
        idxs = ranked[:top_k]

    anomalies = [rows[i] for i in idxs]
    for i in idxs:
        rows[i]["_iforest_score"] = float(scores[i])  # optional: for UI

    return anomalies, feats, [float(scores[i]) for i in idxs]


# ----------------------------
# IQR detector (kept for your /scan route)
# ----------------------------

def _candidate_numeric_cols(rows: List[Dict[str, Any]]) -> List[str]:
    if not rows:
        return []
    keys = set().union(*[set(r.keys()) for r in rows]) - _EXCLUDE_FOR_IQR
    cols: List[str] = []
    for k in sorted(keys):
        vals = [r.get(k) for r in rows]
        nums = [v for v in vals if isinstance(v, (int, float))]
        if len(nums) < 4:
            continue
        if len(set(nums)) < 3:  # drop binary/near-constant
            continue
        cols.append(k)
    return cols

def feature_names(rows: List[Dict[str, Any]]) -> List[str]:
    """Helper used by UI if needed."""
    return _candidate_numeric_cols(rows)

def _iqr_flags(values: List[Any], k: float = 1.5) -> List[bool]:
    nums = [v for v in values if isinstance(v, (int, float))]
    n = len(nums)
    if n < 4:
        return [False] * len(values)
    nums = sorted(nums)

    def pct(p: float) -> float:
        idx = (n - 1) * p
        lo, hi = int(math.floor(idx)), int(math.ceil(idx))
        w = idx - lo
        return nums[lo] * (1 - w) + nums[hi] * w

    q1, q3 = pct(0.25), pct(0.75)
    iqr = max(q3 - q1, 1e-9)
    lo, hi = q1 - k * iqr, q3 + k * iqr
    out = []
    for v in values:
        out.append(False if not isinstance(v, (int, float)) else not (lo <= v <= hi))
    return out

def detect_outliers_iqr(
    rows: List[Dict[str, Any]],
    k: float = 1.5
) -> Tuple[List[Dict[str, Any]], List[str], List[float]]:
    """
    Simple IQR across all numeric columns with some variance.
    Returns (anomalies, feature_names, scores=[]).
    """
    cols = _candidate_numeric_cols(rows)
    if not rows or not cols:
        return [], cols, []

    flags_any = [False] * len(rows)
    for c in cols:
        vals = [r.get(c) for r in rows]
        flags = _iqr_flags(vals, k=k)
        flags_any = [a or b for a, b in zip(flags_any, flags)]

    anomalies = [r for r, fl in zip(rows, flags_any) if fl]
    return anomalies, cols, []
