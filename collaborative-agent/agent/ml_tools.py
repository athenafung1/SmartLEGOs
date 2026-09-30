"""Local ML analysis tools. Only aggregates leave the node, never raw rows."""

import glob
import json
import os
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

MIN_GROUP = 5  # suppress group-level stats for groups smaller than this


@lru_cache(maxsize=1)
def _read(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def _df() -> pd.DataFrame:
    path = os.environ.get("NODE_DATA_PATH")
    if not path:
        raise RuntimeError("NODE_DATA_PATH is not set on this node")
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "*.csv")))
        if len(files) != 1:
            raise RuntimeError(f"Expected exactly one CSV in {path}, found {len(files)}")
        path = files[0]
    return _read(path)


def _check(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Unknown columns {missing}; available: {list(df.columns)}")


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    _check(df, cols)
    out = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if out.empty:
        raise ValueError(f"No numeric rows for columns {cols}")
    return out


def _f(x: Any) -> float | None:
    return float(x) if pd.notna(x) else None


# ---------------------------------------------------------------- tools
def describe_dataset(a: dict[str, Any]) -> dict[str, Any]:
    df = _df()
    num = df.select_dtypes("number")
    return {
        "rows": len(df),
        "columns": [
            {"name": c, "dtype": str(df[c].dtype), "missing": int(df[c].isna().sum())}
            for c in df.columns
        ],
        "numeric_summary": {
            c: {k: _f(v) for k, v in num[c].agg(["min", "max", "mean", "median", "std"]).items()}
            for c in num.columns
        },
    }


def column_range(a: dict[str, Any]) -> dict[str, Any]:
    col = a["column"]
    x = _num(_df(), [col])[col]
    return {
        "column": col,
        "min": _f(x.min()),
        "max": _f(x.max()),
        "mean": _f(x.mean()),
        "median": _f(x.median()),
        "rows_used": len(x),
    }


def detect_anomalies(a: dict[str, Any]) -> dict[str, Any]:
    cols = a["columns"]
    X = _num(_df(), cols)
    model = IsolationForest(contamination=a.get("contamination", 0.02), random_state=0).fit(X)
    flags = model.predict(X) == -1
    n = int(flags.sum())
    res: dict[str, Any] = {"rows_analyzed": len(X), "anomalies": n, "fraction": n / len(X)}
    if n >= MIN_GROUP:
        res["anomaly_mean"] = {c: _f(X.loc[flags, c].mean()) for c in cols}
        res["normal_mean"] = {c: _f(X.loc[~flags, c].mean()) for c in cols}
    return res


def cluster_profile(a: dict[str, Any]) -> dict[str, Any]:
    cols, k = a["columns"], int(a.get("k", 3))
    X = _num(_df(), cols)
    if k < 2 or k > len(X):
        raise ValueError("k must be between 2 and the number of rows")
    labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(
        StandardScaler().fit_transform(X)
    )
    clusters = []
    for i in range(k):
        mask = labels == i
        size = int(mask.sum())
        entry: dict[str, Any] = {"cluster": i, "size": size}
        if size >= MIN_GROUP:
            entry["mean"] = {c: _f(v) for c, v in X[mask].mean().items()}
        else:
            entry["note"] = "stats suppressed (small group)"
        clusters.append(entry)
    return {"rows_analyzed": len(X), "clusters": clusters}


def feature_importance(a: dict[str, Any]) -> dict[str, Any]:
    df = _df()
    target = a["target"]
    _check(df, [target])
    feats = [f for f in (a.get("features") or df.select_dtypes("number").columns) if f != target]
    _check(df, feats)
    work = df[[target, *feats]].apply(pd.to_numeric, errors="coerce")
    dt = a.get("datetime_column")
    if dt:
        _check(df, [dt])
        ts = pd.to_datetime(df[dt], errors="coerce")
        work["hour"], work["weekday"], work["month"] = ts.dt.hour, ts.dt.weekday, ts.dt.month
    work = work.dropna(axis=1, how="all").dropna()
    if len(work) < 20 or work.shape[1] < 2:
        raise ValueError("Not enough usable rows/features for modeling")
    X, y = work.drop(columns=[target]), work[target]
    model = RandomForestRegressor(n_estimators=100, random_state=0, n_jobs=-1)
    r2 = cross_val_score(model, X, y, cv=min(5, len(work) // 4), scoring="r2")
    model.fit(X, y)
    ranked = sorted(zip(X.columns, model.feature_importances_), key=lambda t: -t[1])
    return {
        "target": target,
        "rows_used": len(work),
        "cv_r2_mean": _f(r2.mean()),
        "importances": [{"feature": f, "importance": float(v)} for f, v in ranked],
    }


# ---------------------------------------------------------------- registry
def _tool(name: str, desc: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": desc,
        "parameters": {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        },
    }


_STR_LIST = {"type": "array", "items": {"type": "string"}}
_HINT = " Call describe_dataset first and use exact column names."

LOCAL_TOOLS = [
    _tool("describe_dataset",
          "Return column names, dtypes, missing counts, and numeric summary stats "
          "(min/max/mean/median/std) for this node's dataset.", {}, []),
    _tool("column_range",
          "Min, max, mean, median of one numeric column (e.g. max occupancy)." + _HINT,
          {"column": {"type": "string"}}, ["column"]),
    _tool("detect_anomalies",
          "Isolation Forest anomaly detection over numeric columns. Returns counts only." + _HINT,
          {"columns": _STR_LIST, "contamination": {"type": "number"}}, ["columns"]),
    _tool("cluster_profile",
          "KMeans clustering over numeric columns; returns cluster sizes and mean profiles "
          "(e.g. usage patterns)." + _HINT,
          {"columns": _STR_LIST, "k": {"type": "integer"}}, ["columns"]),
    _tool("feature_importance",
          "Random Forest showing which columns best explain a numeric target (e.g. occupancy), "
          "with cross-validated R². Optional datetime_column adds hour/weekday/month features."
          + _HINT,
          {"target": {"type": "string"}, "features": _STR_LIST,
           "datetime_column": {"type": "string"}}, ["target"]),
]
LOCAL_TOOL_NAMES = {t["name"] for t in LOCAL_TOOLS}
_HANDLERS = {
    "describe_dataset": describe_dataset,
    "column_range": column_range,
    "detect_anomalies": detect_anomalies,
    "cluster_profile": cluster_profile,
    "feature_importance": feature_importance,
}


def call_local_tool(item: dict[str, Any]) -> dict[str, Any]:
    """Run a local tool call and return a function_call_output item."""
    try:
        result = _HANDLERS[item["name"]](json.loads(item.get("arguments") or "{}"))
    except Exception as e:  # keep the agent loop alive
        result = {"error": str(e)}
    return {
        "type": "function_call_output",
        "call_id": item["call_id"],
        "output": json.dumps(result),
    }