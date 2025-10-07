from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from agent.loader import load_dir, load_healthchecks

# from agent.detector import detect_outliers
from agent.actions import suggest_actions
from agent.runner import execute_plan

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
BASE = Path(__file__).parent.resolve()
UPLOADS = (BASE / "uploads").resolve()
SAMPLES = (BASE / "sample_reports").resolve()
UPLOADS.mkdir(parents=True, exist_ok=True)
SAMPLES.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Network AI Agent — Local Demo")
templates = Jinja2Templates(directory=str(BASE / "templates"))

import requests
import yaml
from urllib.parse import urlparse

def _guess_host_name(data: dict, fallback: str) -> str:
    """Best-effort host name for per-host file naming."""
    return (
        data.get("all_gathered_resources", {})
            .get("device_info", {})
            .get("device_name")
        or data.get("host")
        or Path(fallback).stem
    )

def _save_host_json(data: dict, hint_name: str, out_dir: str) -> str:
    host = _guess_host_name(data, hint_name)
    path = os.path.join(out_dir, f"{host}_inventory.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path

def _fetch_text(url: str, timeout: int = 30) -> str:
    """Fetch raw text; no special auth needed for public raw URLs."""
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def _parse_payload(text: str, filename_hint: str):
    """
    Parse YAML/JSON text. Supports:
      - YAML single doc   -> dict
      - YAML multi docs   -> list[dict]
      - JSON              -> dict/list
    Returns a list of dicts (one per host doc).
    """
    name = filename_hint.lower()
    docs: list[dict] = []

    # JSON first if obvious
    if name.endswith(".json"):
        obj = json.loads(text)
        if isinstance(obj, list):
            docs = [d for d in obj if isinstance(d, dict)]
        elif isinstance(obj, dict):
            docs = [obj]
        else:
            docs = [{"_raw": obj}]
        return docs

    # Try YAML (handles *.yaml, *.yml, and anything else if it parses)
    try:
        loaded = list(yaml.safe_load_all(text))
        # Normalize to list of dicts
        for idx, d in enumerate(loaded):
            if isinstance(d, dict):
                docs.append(d)
            elif isinstance(d, list):
                docs.extend([x for x in d if isinstance(x, dict)])
            else:
                docs.append({"_raw": d})
        return docs
    except Exception:
        # Fall back to raw if nothing parsed
        return [{"_raw": text}]


def _fmt_uptime(row: dict) -> str:
    d = row.get("uptime_days")
    h = row.get("uptime_hours")
    parts = []
    if isinstance(d, (int, float)):
        parts.append(f"{int(d)}d")
    if isinstance(h, (int, float)):
        parts.append(f"{int(h)}h")
    return " ".join(parts) if parts else "–"

templates.env.filters["fmt_uptime"] = _fmt_uptime

# -----------------------------------------------------------------------------
# UI: Home
# -----------------------------------------------------------------------------
# top of file
from agent.detector import detect_outliers_iforest, detect_outliers_iqr  # ensure both are importable

from agent.detector import detect_outliers_iforest, detect_outliers_iqr
# ... keep the rest of your imports

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    rows = load_dir(str(UPLOADS))

    anomalies, features, scores = [], [], []
    if rows:
        # 1) Try ML first (more sensitive on small datasets)
        #    You can tune contamination between 0.10–0.30 for small N.
        anomalies, features, scores = detect_outliers_iforest(
            rows, contamination=0.20, random_state=42
        )

        # 2) If ML finds nothing, fall back to simple, useful rules
        if not anomalies:
            print("Into Manual Mode")
            def rule_flags(rs):
                flagged = []
                for r in rs:
                    lic_bad = (r.get("license_expired") == 1)
                    many_disabled = (
                        (r.get("iface_total", 0) > 0)
                        and (r.get("iface_enabled_ratio", 1.0) < 0.6)
                    )
                    mem_high = (
                        r.get("mem_used_pct") is not None
                        and r.get("mem_used_pct") >= 85.0
                    )
                    if lic_bad or many_disabled or mem_high:
                        flagged.append(r)
                return flagged

            anomalies = rule_flags(rows)
            features = ["license_expired", "iface_enabled_ratio", "mem_used_pct"]
            scores = None

        # 3) (Optional) If you prefer IQR preview, comment the iforest call
        #    above and use this line instead (lower k to increase sensitivity):
        # anomalies, features, _ = detect_outliers_iqr(rows, k=1.2)

    actions = suggest_actions(anomalies) if anomalies else {}
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "rows": rows,
            "features": features,
            "anomalies": anomalies,
            "actions": actions,
            "now": datetime.datetime.utcnow().isoformat() + "Z",
        },
    )



# -----------------------------------------------------------------------------
# Upload / Samples
# -----------------------------------------------------------------------------
@app.post("/upload", response_class=RedirectResponse)
async def upload(files: List[UploadFile] = File(...)):
    """Handle multi-file upload (matches <input name="files" multiple>)."""
    for uf in files:
        if not uf.filename:
            continue
        dest = UPLOADS / uf.filename
        data = await uf.read()
        dest.write_bytes(data)
    return RedirectResponse(url="/", status_code=303)

@app.post("/load-samples", response_class=RedirectResponse)
def load_samples():
    for f in SAMPLES.glob("*.json"):
        target = UPLOADS / f.name
        if not target.exists():
            target.write_text(f.read_text())
    return RedirectResponse(url="/", status_code=303)

# -----------------------------------------------------------------------------
# Ingest (API)
# -----------------------------------------------------------------------------
@app.post("/ingest", response_class=JSONResponse)
async def ingest(payload: dict):
    host = (
        payload.get("all_gathered_resources", {})
        .get("device_info", {})
        .get("device_name")
        or payload.get("host")
        or "ingested"
    )
    dest = UPLOADS / f"{host}_inventory.json"
    dest.write_text(json.dumps(payload, indent=2))
    return {"saved": str(dest)}

# -----------------------------------------------------------------------------
# Scan
# -----------------------------------------------------------------------------
from typing import List  # add this at the top

# ...

@app.post("/scan", response_class=HTMLResponse)
async def scan(
    request: Request,
    algo: str = Form("iqr"),
    contamination: float = Form(0.1),
    host: str = Form(None),
    hosts: List[str] = Form(None),
):
    all_rows = load_dir(str(UPLOADS))

    anomalies, features, scores = [], [], []
    if all_rows:
        if algo == "iforest":
            from agent.detector import detect_outliers_iforest
            anomalies, features, scores = detect_outliers_iforest(
                all_rows, contamination=contamination, random_state=42
            )
        else:
            from agent.detector import detect_outliers_iqr
            anomalies, features, scores = detect_outliers_iqr(all_rows, k=1.5)

    # Optional focus filtering (keeps current behavior)
    focus = []
    if host:
        focus.append(host)
    if hosts:
        focus.extend(hosts)

    pairs = list(zip(anomalies, scores if scores else [None] * len(anomalies)))
    if focus:
        focus_set = set(focus)
        pairs = [p for p in pairs if p[0].get("host") in focus_set]

    actions = suggest_actions([r for r, _ in pairs]) if pairs else {}

    return templates.TemplateResponse(
        "anomalies.html",
        {
            "request": request,
            "rows": all_rows,
            "features": features,
            "anomalies": pairs,   # list of (row, score)
            "actions": actions,
            "focus_hosts": focus,
        },
    )


# -----------------------------------------------------------------------------
# Execute (simulated)
# -----------------------------------------------------------------------------
@app.post("/execute", response_class=HTMLResponse)
def execute(request: Request):
    rows = load_dir(str(UPLOADS))

    if rows:
        from agent.detector import detect_outliers_iqr
        anomalies, features, scores = detect_outliers_iqr(rows, k=1.5)
    else:
        anomalies = []

    actions = suggest_actions(anomalies) if anomalies else {}
    results = execute_plan(actions)

    return templates.TemplateResponse(
        "plan.html",
        {"request": request, "actions": actions, "results": results},
    )


# -----------------------------------------------------------------------------
# Simple report browser
# -----------------------------------------------------------------------------
def list_reports():
    items = []
    for p in sorted(UPLOADS.glob("*.json")):
        host = p.stem
        try:
            obj = json.loads(p.read_text())
            agr = obj.get("all_gathered_resources", obj)
            dev = agr.get("device_info", {})
            host = dev.get("device_name") or obj.get("host") or p.stem
        except Exception:
            obj = None
        st = p.stat()
        items.append(
            {
                "host": host,
                "filename": p.name,
                "path": str(p),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "mtime_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            }
        )
    return items

def get_report_by_host(host: str):
    for it in list_reports():
        if it["host"] == host:
            p = UPLOADS / it["filename"]
            try:
                obj = json.loads(p.read_text())
            except Exception:
                obj = {"_error": f"Could not parse JSON in {it['filename']}"}
            return it, obj
    return None, None

@app.get("/reports", response_class=HTMLResponse)
async def reports(request: Request):
    items = list_reports()
    return templates.TemplateResponse("reports.html", {"request": request, "items": items})

# @app.get("/report", response_class=HTMLResponse)
# async def report(request: Request, host: str | None = None, filename: str | None = None):
#     meta, obj = None, None
#     if host:
#         meta, obj = get_report_by_host(host)
#         if not obj:
#             return templates.TemplateResponse(
#                 "report.html",
#                 {"request": request, "error": f"No report found for host '{host}'"},
#             )
#     elif filename:
#         p = UPLOADS / filename
#         if not p.exists():
#             return templates.TemplateResponse(
#                 "report.html",
#                 {"request": request, "error": f"File not found: {filename}"},
#             )
#         try:
#             obj = json.loads(p.read_text())
#         except Exception as e:
#             obj = {"_error": f"Could not parse JSON: {e}"}
#         meta = {
#             "host": (
#                 obj.get("all_gathered_resources", obj)
#                 .get("device_info", {})
#                 .get("device_name")
#                 or obj.get("host")
#                 or Path(filename).stem
#             ),
#             "filename": filename,
#         }
#     else:
#         return templates.TemplateResponse(
#             "report.html",
#             {"request": request, "error": "Provide ?host=... or ?filename=..."},
#         )

#     pretty = json.dumps(obj, indent=2, sort_keys=True)
#     return templates.TemplateResponse("report.html", {"request": request, "meta": meta, "pretty": pretty})

# app.py  — replace your /report handler with this version
@app.get("/report", response_class=HTMLResponse)
async def report(request: Request, host: str | None = None, filename: str | None = None):
    meta, obj = None, None

    # We'll also pass the merged 'row' (from loader) so health badges can be shown.
    row_agg = None
    try:
        all_rows = load_dir(str(UPLOADS))
    except Exception:
        all_rows = []

    if host:
        meta, obj = get_report_by_host(host)
        if not obj:
            return templates.TemplateResponse(
                "report.html",
                {"request": request, "error": f"No report found for host '{host}'"}
            )
        # Find merged row for this host (contains health fields)
        row_agg = next((r for r in all_rows if r.get("host") == host), None)

    elif filename:
        p = UPLOADS / filename
        if not p.exists():
            return templates.TemplateResponse(
                "report.html",
                {"request": request, "error": f"File not found: {filename}"}
            )
        try:
            obj = json.loads(p.read_text())
        except Exception as e:
            obj = {"_error": f"Could not parse JSON: {e}"}
        meta = {
            "host": (obj.get("all_gathered_resources", obj).get("device_info", {}).get("device_name")
                     or obj.get("host") or Path(filename).stem),
            "filename": filename,
        }
        # Best-effort match by host
        row_agg = next((r for r in all_rows if r.get("host") == meta["host"]), None)
    else:
        return templates.TemplateResponse(
            "report.html",
            {"request": request, "error": "Provide ?host=... or ?filename=..."}
        )

    pretty = json.dumps(obj, indent=2, sort_keys=True)
    return templates.TemplateResponse(
        "report.html",
        {"request": request, "meta": meta, "pretty": pretty, "row": row_agg}
    )


# -----------------------------------------------------------------------------
# Download with strict path safety
# -----------------------------------------------------------------------------
def _resolve_download(name: str) -> Path:
    safe = Path(name).name  # prevent traversal
    for root in (UPLOADS, SAMPLES):
        cand = (root / safe).resolve()
        if cand.is_file() and str(cand).startswith(str(root)):
            return cand
    raise HTTPException(status_code=404, detail=f"File not found: {safe}")

@app.get("/download/{name}")
async def download(name: str):
    p = _resolve_download(name)
    return FileResponse(path=p, media_type="application/json", filename=p.name)


@app.get("/health", response_class=HTMLResponse)
def health(request: Request, host: str):
    # read all to ensure we can show inventory + pull the health map
    rows = load_dir(str(UPLOADS))
    health_map = load_healthchecks(str(UPLOADS))
    h = health_map.get(host)
    if not h:
        raise HTTPException(status_code=404, detail=f"No healthchecks found for host '{host}'")
    return templates.TemplateResponse("health.html", {
        "request": request,
        "host": host,
        "health": h,
    })