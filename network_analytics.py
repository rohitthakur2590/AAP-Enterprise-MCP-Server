# network_analytics.py
#
# MCP server for network inventory reports + anomaly detection.
# - Local mode: run playbooks with ansible-playbook
# - Controller mode: run AAP job templates via REST if AAP_TOKEN/AAP_URL are set
#
# Env (optional):
#   AAP_URL       = https://<host>/api/controller/v2
#   AAP_TOKEN     = <controller OAuth token or PAT>
#   NETWORK_OUT   = absolute path for artifacts (default: ./outputs)
#   NETWORK_UI    = path to UI uploads dir (for export_to_ui)
#   GITHUB_TOKEN  = token for GitHub API/rate limits (optional)
#   PYTHONUTF8    = 1
#   PYTHONIOENCODING = utf-8
#   LANG / LC_ALL = en_US.UTF-8

from __future__ import annotations

import os
import io
import re
import sys
import json
import glob
import time
import yaml
import uuid
import shutil
import signal
import pandas as pd  # optional, used for CSV export (ok if installed)
import requests
import subprocess

from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

# ---- your helpers
from anomaly import isolation_forest_detect
from ansible_runner import run_playbook as run_playbook_local

APP_NAME = "aap-network-analytics"

BASE: Path = Path(__file__).parent.resolve()
OUT_DIR = os.environ.get("NETWORK_OUT", str(BASE / "outputs"))
UI_DIR_DEFAULT = os.environ.get("NETWORK_UI", str(BASE / "uploads"))
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
Path(UI_DIR_DEFAULT).mkdir(parents=True, exist_ok=True)

mcp = FastMCP(APP_NAME)
ts = lambda: datetime.utcnow().strftime("%Y%m%d-%H%M%S")

# ---------------------------------------------------------------------------
# UTF-8 & response safety helpers
# ---------------------------------------------------------------------------

def _ascii_safe(obj):
    """
    Recursively convert strings to ASCII-safe (backslash-escaped).
    Prevents transport layers that assume latin-1 from crashing on unicode.
    """
    if isinstance(obj, str):
        return obj.encode("ascii", "backslashreplace").decode("ascii")
    if isinstance(obj, dict):
        return { _ascii_safe(k): _ascii_safe(v) for k, v in obj.items() }
    if isinstance(obj, list):
        return [ _ascii_safe(x) for x in obj ]
    return obj

def _write_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# AAP (Controller) REST helpers
# ---------------------------------------------------------------------------

import urllib.request, urllib.error

AAP_URL = os.environ.get("AAP_URL")     # e.g. https://aap.example.com/api/controller/v2
AAP_TOKEN = os.environ.get("AAP_TOKEN")

def _http(method: str, url: str, data: Optional[dict] = None, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, method=method)
    if AAP_TOKEN:
        req.add_header("Authorization", f"Bearer {AAP_TOKEN}")
    req.add_header("Content-Type", "application/json")
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as r:
            ctype = r.headers.get_content_type()
            raw = r.read()
            if ctype == "application/json":
                return json.loads(raw.decode("utf-8", errors="replace"))
            return {"status": r.status, "text": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def _controller_available() -> bool:
    return bool(AAP_URL and AAP_TOKEN)

def run_job_template(template_id: int, extra_vars: Optional[dict] = None) -> dict:
    """Fire a JT on Controller (simple happy-path) and wait for completion."""
    if not _controller_available():
        return {"ok": False, "error": "AAP_URL/AAP_TOKEN not set"}
    launch_url = f"{AAP_URL}/job_templates/{template_id}/launch/"
    res = _http("POST", launch_url, {"extra_vars": extra_vars or {}})
    if "job" not in res:
        return {"ok": False, "error": res}
    job_id = res["job"]
    # poll
    while True:
        j = _http("GET", f"{AAP_URL}/jobs/{job_id}/")
        status = j.get("status")
        if status in {"successful", "failed", "error", "canceled"}:
            break
        time.sleep(2)
    # fetch stdout (optional)
    stdout_resp = _http("GET", f"{AAP_URL}/jobs/{job_id}/stdout/?format=txt")
    stdout = stdout_resp.get("text") if isinstance(stdout_resp, dict) else None
    return {"ok": status == "successful", "status": status, "job_id": job_id, "stdout": stdout}

# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def _gh_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": APP_NAME,
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _fetch_text(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=_gh_headers(), timeout=timeout)
    r.encoding = "utf-8"  # force UTF-8
    r.raise_for_status()
    return r.text

def _gh_get_json(url: str, timeout: int = 30) -> dict:
    r = requests.get(url, headers=_gh_headers(), timeout=timeout)
    r.encoding = "utf-8"
    r.raise_for_status()
    return r.json()

def _parse_pr_url(pr_url: str) -> Tuple[str, str, int]:
    """
    Return (owner, repo, pr_number)
    e.g., https://github.com/owner/repo/pull/123
    """
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        raise ValueError(f"Unrecognized PR URL: {pr_url}")
    return m.group(1), m.group(2), int(m.group(3))

def _raw_url(owner: str, repo: str, ref: str, path: str) -> str:
    # Resolve raw content from a given commit/branch (ref)
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"

def _flatten(obj, prefix=""):
    """
    Flatten nested dict/list for CSV-friendly rows.
    dict -> dotted.keys, list -> dotted[0], dotted[1], ...
    """
    flat = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            flat.update(_flatten(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{prefix}[{i}]"
            flat.update(_flatten(v, p))
    else:
        flat[prefix or "_"] = obj
    return flat

# ---------------------------------------------------------------------------
# Naming & per-host save helpers
# ---------------------------------------------------------------------------

def _guess_host_name(data: dict, fallback: str) -> str:
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
    _write_json(path, data)  # UTF-8, ensure_ascii=False
    return path

# ---------------------------------------------------------------------------
# TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
def run_reports_local(
    playbook_path: str,
    inventory: str,
    out_file: str = "outputs/report.json",
    extra_vars_json: Optional[str] = None,
    timeout: int = 1800
) -> dict:
    """
    Run a *local* ansible-playbook to produce a JSON report at out_file.
    """
    try:
        extra_vars = json.loads(extra_vars_json) if extra_vars_json else None
        out_file_abs = os.path.abspath(out_file if os.path.isabs(out_file) else os.path.join(str(BASE), out_file))
        os.makedirs(os.path.dirname(out_file_abs), exist_ok=True)

        if extra_vars is None:
            extra_vars = {}
        extra_vars.setdefault("out_file", out_file_abs)

        res = run_playbook_local(playbook_path, inventory, extra_vars, OUT_DIR, timeout)
        res["out_file"] = out_file_abs
        return _ascii_safe(res)
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

@mcp.tool()
def run_reports_controller(
    template_id: int,
    extra_vars_json: Optional[str] = None
) -> dict:
    """
    Run a *Controller* Job Template and wait for completion.
    Assumes your job writes artifacts (stdout, artifact_data, or an external path).
    """
    try:
        ev = json.loads(extra_vars_json) if extra_vars_json else None
        run = run_job_template(template_id, ev)
        return _ascii_safe(run)
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

@mcp.tool()
def detect_anomalies(
    input_glob: str,
    id_field: Optional[str] = None,
    numeric_fields_json: Optional[str] = None,
    contamination: float = 0.10,
    random_state: int = 42,
    output_basename: Optional[str] = None
) -> dict:
    """
    Run IsolationForest over a file or glob (JSON/NDJSON). Writes anomalies JSON to OUT_DIR.
    """
    try:
        numeric_fields = json.loads(numeric_fields_json) if numeric_fields_json else None
        pattern = os.path.abspath(input_glob if os.path.isabs(input_glob) else os.path.join(str(BASE), input_glob))
        out = None
        if output_basename:
            out = os.path.join(OUT_DIR, f"{output_basename}_anomalies_{ts()}.json")
        res = isolation_forest_detect(pattern, id_field=id_field,
                                      numeric_fields=numeric_fields,
                                      contamination=contamination,
                                      random_state=random_state,
                                      output_path=out)
        if out:
            res["anomalies_file"] = out
        return _ascii_safe(res)
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

@mcp.tool()
def run_pipeline_local(
    playbook_path: str,
    inventory: str,
    out_file: str = "outputs/pipeline.json",
    id_field: str = "host",
    contamination: float = 0.10
) -> dict:
    """
    Convenience: run a local playbook -> detect anomalies on its output.
    """
    try:
        r = run_reports_local(playbook_path, inventory, out_file=out_file)
        if r.get("rc", 1) != 0:
            return _ascii_safe({"ok": False, "step": "reports", "detail": r})
        anoms = detect_anomalies(r["out_file"], id_field=id_field, contamination=contamination)
        return _ascii_safe({"ok": True, "step": "detect", "detail": anoms})
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

@mcp.tool()
def export_to_ui(ui_dir: Optional[str] = None) -> dict:
    """
    Copy *.json/*.csv from OUT_DIR to the UI 'uploads' folder.
    """
    try:
        ui_dir = ui_dir or UI_DIR_DEFAULT
        ui_dir = os.path.abspath(ui_dir)
        os.makedirs(ui_dir, exist_ok=True)
        copied = []
        for fp in glob.glob(os.path.join(OUT_DIR, "*")):
            if fp.endswith((".json", ".csv")):
                shutil.copy2(fp, os.path.join(ui_dir, os.path.basename(fp)))
                copied.append(os.path.basename(fp))
        return _ascii_safe({"ok": True, "ui_dir": ui_dir, "copied": copied})
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

# --- manage local FastAPI UI (uvicorn) ---

PIDS_DIR = os.path.join(OUT_DIR, ".pids"); os.makedirs(PIDS_DIR, exist_ok=True)
LOG_FILE = os.path.join(OUT_DIR, "ui.log")
UI_PID_FILE = os.path.join(PIDS_DIR, "ui.pid")

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

@mcp.tool()
def start_ui(app_path: str, port: int = 8000, host: str = "127.0.0.1", reload: bool = False) -> dict:
    try:
        app_path = os.path.abspath(app_path)
        if not os.path.exists(app_path):
            return _ascii_safe({"ok": False, "error": f"app not found: {app_path}"})
        if os.path.exists(UI_PID_FILE):
            try:
                pid = int(open(UI_PID_FILE, "r", encoding="utf-8").read().strip())
                if _pid_alive(pid):
                    return _ascii_safe({"ok": True, "status": "already running", "pid": pid,
                                        "url": f"http://{host}:{port}", "log": LOG_FILE})
            except Exception:
                pass
        workdir = os.path.dirname(app_path)
        cmd = [sys.executable, "-m", "uvicorn", "app:app", "--host", host, "--port", str(port)]
        if reload:
            cmd.append("--reload")
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        logf = open(LOG_FILE, "ab")
        proc = subprocess.Popen(cmd, cwd=workdir, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        with open(UI_PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
        return _ascii_safe({"ok": True, "status": "started", "pid": proc.pid,
                            "url": f"http://{host}:{port}", "log": LOG_FILE})
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

@mcp.tool()
def stop_ui() -> dict:
    try:
        if not os.path.exists(UI_PID_FILE):
            return _ascii_safe({"ok": True, "status": "not running"})
        try:
            pid = int(open(UI_PID_FILE, "r", encoding="utf-8").read().strip())
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            os.remove(UI_PID_FILE)
        except Exception:
            pass
        return _ascii_safe({"ok": True, "status": "stopped"})
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

@mcp.tool()
def ui_status() -> dict:
    try:
        if os.path.exists(UI_PID_FILE):
            try:
                pid = int(open(UI_PID_FILE, "r", encoding="utf-8").read().strip())
                return _ascii_safe({"running": _pid_alive(pid), "pid": pid, "log": LOG_FILE})
            except Exception:
                return _ascii_safe({"running": False, "pid": None, "log": LOG_FILE})
        return _ascii_safe({"running": False, "pid": None, "log": LOG_FILE})
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

# ---------------------------------------------------------------------------
# Ingest: GitHub PR
# ---------------------------------------------------------------------------

@mcp.tool()
def ingest_github_pr(
    pr_url: str,
    include_glob: str = "host_vars/*.yaml",
    export_to_ui_bool: bool = True,
    start_ui_after: bool = False,
    ui_app_path: Optional[str] = None,
    ui_port: int = 8000
) -> dict:
    """
    Read files from a GitHub PR, normalize, and export artifacts for the UI.

    - pr_url: PR like https://github.com/<owner>/<repo>/pull/<num>
    - include_glob: which PR files to ingest (e.g., 'host_vars/*.yaml', 'reports/*.json')
    - export_to_ui_bool: copy JSON/CSV artifacts from OUT_DIR to NETWORK_UI
    - start_ui_after: optionally start the local UI with uvicorn
    - ui_app_path: path to your FastAPI app.py (only used if start_ui_after=True)
    - ui_port: port to run the UI on
    """
    try:
        owner, repo, pr_num = _parse_pr_url(pr_url)

        # get PR head SHA
        pr_api = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}"
        pr = _gh_get_json(pr_api)
        head_sha = pr.get("head", {}).get("sha")
        if not head_sha:
            return _ascii_safe({"ok": False, "error": "Cannot resolve PR head SHA"})

        # list PR files
        files_api = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}/files"
        pr_files = _gh_get_json(files_api)

        matched = []
        rows = []
        raw_docs = []
        per_host_files = []

        for f in pr_files:
            path = f.get("filename")
            status = f.get("status")
            if status not in {"added", "modified", "renamed"}:
                continue
            if not re.match(fnmatch_translate(include_glob), path):
                continue

            raw_url = _raw_url(owner, repo, head_sha, path)
            raw_text = _fetch_text(raw_url)

            # parse
            if path.endswith((".yaml", ".yml")):
                data = yaml.safe_load(raw_text) or {}
            elif path.endswith(".json"):
                data = json.loads(raw_text)
            else:
                data = {"_raw": raw_text}

            raw_docs.append({"file": path, "data": data})
            rows.append({"file": path, **_flatten(data)})
            matched.append(path)

            # write one JSON per host into OUT_DIR
            if isinstance(data, list):
                for idx, d in enumerate(data):
                    per_host_files.append(_save_host_json(d, f"{Path(path).stem}_{idx}", OUT_DIR))
            else:
                per_host_files.append(_save_host_json(data, path, OUT_DIR))

        if not matched:
            return _ascii_safe({"ok": False, "reason": f"No files matched glob '{include_glob}' in PR"})

        stamp = ts()
        base_name = f"pr_{repo}_{pr_num}_{stamp}"

        merged_json = os.path.join(OUT_DIR, f"{base_name}.json")
        _write_json(merged_json, raw_docs)

        flat_json = os.path.join(OUT_DIR, f"{base_name}_flat.json")
        _write_json(flat_json, rows)

        csv_path = None
        try:
            df = pd.DataFrame(rows)
            csv_path = os.path.join(OUT_DIR, f"{base_name}.csv")
            df.to_csv(csv_path, index=False)
        except Exception:
            csv_path = None

        exported = []
        if export_to_ui_bool:
            exported = export_to_ui().get("copied", [])

        ui_info = None
        if start_ui_after and ui_app_path:
            ui_info = start_ui(ui_app_path, port=ui_port)

        return _ascii_safe({
            "ok": True,
            "matched_files": matched,
            "per_host_files": per_host_files,
            "merged_json": merged_json,
            "flat_json": flat_json,
            "csv": csv_path,
            "exported": exported,
            "ui": ui_info,
        })
    except Exception as e:
        return _ascii_safe({"ok": False, "error": str(e)})

def fnmatch_translate(pat: str) -> str:
    """Translate a shell PATTERN to a regular expression (like fnmatch.translate but local)."""
    import fnmatch as _fn
    return _fn.translate(pat)

# ---------------------------------------------------------------------------
# Ingest: raw URL(s)
# ---------------------------------------------------------------------------

def _parse_payload(text: str) -> List[dict]:
    """
    Try YAML first, then JSON; return a list of documents.
    """
    try:
        doc = yaml.safe_load(text)
        if doc is None:
            return []
        if isinstance(doc, list):
            return doc
        return [doc]
    except Exception:
        try:
            doc = json.loads(text)
            if isinstance(doc, list):
                return doc
            return [doc]
        except Exception:
            # last resort: wrap raw text
            return [{"_raw": text}]

import re
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter, Retry
import unicodedata

# ---------- helpers (drop these near the top with your other helpers) ----------

def _safe_filename(name: str) -> str:
    # normalize to ascii-ish and strip bad chars
    norm = unicodedata.normalize("NFKD", name)
    norm = "".join(c for c in norm if ord(c) >= 32)  # drop control chars
    norm = re.sub(r"[^\w.\-+]+", "_", norm)          # keep letters, digits, _ . - +
    return norm.strip("._") or "file"

def _http_get_text(url: str, timeout: int = 30) -> str:
    sess = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    sess.mount("http://", HTTPAdapter(max_retries=retry))
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    headers = {
        "User-Agent": f"{APP_NAME}/1.0",
        "Accept": "text/plain, application/x-yaml, application/json; q=0.9, */*; q=0.1",
    }
    r = sess.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    # decode explicitly to avoid locale/default codec surprises
    return r.content.decode("utf-8", errors="replace")

def _parse_payload_text(text: str, url_hint: str | None = None) -> list[dict]:
    """
    Return a list of dicts. Supports:
      - YAML (single or multi-doc)
      - JSON (single object or list-of-objects)
    If neither parse works, returns [].
    """
    # Decide preferred parser by URL suffix if available
    lower = (url_hint or "").lower()

    def _parse_yaml(t: str):
        docs = [d for d in yaml.safe_load_all(t) if d is not None]
        # if single dict -> [dict]; if list-of-dicts -> flatten; else wrap
        if len(docs) == 1:
            d = docs[0]
            if isinstance(d, list):
                return [x for x in d if isinstance(x, dict)]
            return [d] if isinstance(d, dict) else []
        out = []
        for d in docs:
            if isinstance(d, dict):
                out.append(d)
            elif isinstance(d, list):
                out.extend([x for x in d if isinstance(x, dict)])
        return out

    def _parse_json(t: str):
        obj = json.loads(t)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        return []

    parsers = []
    if lower.endswith((".yaml", ".yml")):
        parsers = (_parse_yaml, _parse_json)
    elif lower.endswith(".json"):
        parsers = (_parse_json, _parse_yaml)
    else:
        parsers = (_parse_yaml, _parse_json)

    for p in parsers:
        try:
            docs = p(text)
            if docs:
                return docs
        except Exception:
            continue
    return []

def _guess_host_name(data: dict, fallback: str) -> str:
    return (
        data.get("all_gathered_resources", {})
            .get("device_info", {})
            .get("device_name")
        or data.get("host")
        or Path(fallback).stem
        or "ingested"
    )

def _save_host_json(data: dict, hint_name: str, out_dir: str) -> str:
    # Ensure UTF-8 write and a safe filename
    safe = _safe_filename(_guess_host_name(data, hint_name)) + "_inventory.json"
    path = os.path.join(out_dir, safe)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path

def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

# ---------- improved tool ----------

@mcp.tool()
def ingest_raw_url(
    url: str,
    save_as: Optional[str] = None,
    export_to_ui_bool: bool = True,
    start_ui_after: bool = False,
    ui_app_path: Optional[str] = None,
    ui_port: int = 8800,
) -> dict:
    """
    Fetch a YAML or JSON document from a URL, save per-host JSON(s) into OUT_DIR,
    optionally export to UI and start the UI server.
    """
    try:
        # 1) fetch robustly (UTF-8 decode, with headers & retries)
        text = _http_get_text(url)

        # 2) parse (YAML multi-doc / JSON)
        docs = _parse_payload_text(text, url_hint=url)
        if not docs:
            return {"ok": False, "error": "No parsable content from URL"}

        # 3) choose a base hint for filenames
        base_hint = save_as or Path(urlparse(url).path).name or f"ingested_{ts()}"
        base_hint = _safe_filename(base_hint)

        # 4) save one JSON per host (normalized name)
        saved_files = []
        if len(docs) == 1:
            saved_files.append(_save_host_json(docs[0], base_hint, OUT_DIR))
        else:
            for idx, d in enumerate(docs):
                saved_files.append(_save_host_json(d, f"{base_hint}_{idx}", OUT_DIR))

        # 5) also persist a merged dump for debugging
        merged = os.path.join(OUT_DIR, f"{base_hint}_merged_{ts()}.json")
        _write_json(merged, docs)

        # 6) export to UI uploads (optional)
        exported = []
        if export_to_ui_bool:
            exported = export_to_ui().get("copied", [])

        # 7) start UI (optional)
        ui_info = None
        if start_ui_after and ui_app_path:
            ui_info = start_ui(ui_app_path, port=ui_port)

        return {
            "ok": True,
            "saved": saved_files,
            "merged": merged,
            "exported": exported,
            "ui": ui_info,
        }
    except requests.HTTPError as e:
        # include status/text for GitHub 404/403 debugging
        return {"ok": False, "error": f"HTTPError {e.response.status_code}: {e.response.text[:200]}..."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# @mcp.tool()
# def ingest_raw_urls(
#     urls: List[str],
#     export_to_ui_bool: bool = True,
#     start_ui_after: bool = False,
#     ui_app_path: Optional[str] = None,
#     ui_port: int = 8000
# ) -> dict:
#     """
#     Fetch one or more raw URLs (YAML/JSON), produce per-host JSON files in OUT_DIR,
#     then optionally export to UI and start the UI.
#     """
#     try:
#         if not urls:
#             return _ascii_safe({"ok": False, "error": "No URLs provided"})

#         saved_files = []
#         errors = []

#         for url in urls:
#             try:
#                 text = _fetch_text(url)
#                 docs = _parse_payload(text)
#                 if not docs:
#                     errors.append({"url": url, "error": "No parsable documents"})
#                     continue

#                 filename_hint = Path(urlparse(url).path).name or f"ingested_{ts()}"
#                 if len(docs) == 1:
#                     saved_files.append(_save_host_json(docs[0], filename_hint, OUT_DIR))
#                 else:
#                     for idx, d in enumerate(docs):
#                         saved_files.append(_save_host_json(d, f"{Path(filename_hint).stem}_{idx}", OUT_DIR))

#             except Exception as e:
#                 errors.append({"url": url, "error": str(e)})

#         exported = []
#         if export_to_ui_bool:
#             exported = export_to_ui().get("copied", [])

#         ui_info = None
#         if start_ui_after and ui_app_path:
#             ui_info = start_ui(ui_app_path, port=ui_port)

#         return _ascii_safe({
#             "ok": len(saved_files) > 0 and len(errors) == 0,
#             "saved": saved_files,
#             "errors": errors,
#             "exported": exported,
#             "ui": ui_info,
#         })
#     except Exception as e:
#         return _ascii_safe({"ok": False, "error": str(e)})

# ---------------------------------------------------------------------------
# Server main
# ---------------------------------------------------------------------------

import asyncio
import inspect

async def _main():
    async with stdio_server() as (stdin, stdout):
        res = mcp.run(stdin, stdout)
        if inspect.isawaitable(res):
            await res

if __name__ == "__main__":
    result = mcp.run()
    if inspect.isawaitable(result):
        asyncio.run(result)
