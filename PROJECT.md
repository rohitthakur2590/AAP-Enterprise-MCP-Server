## 1. What Is This Project?

A working proof-of-concept demonstrating that **Claude AI can act as a first-class reasoning and orchestration node inside Ansible workflows** — not as a chatbot sitting outside, but as a participant that calls AAP APIs, interprets results, and drives automation decisions.

**Network health monitoring** is the concrete use case: a complete closed loop where Claude collects telemetry from network devices, detects anomalies with unsupervised ML, generates remediation plans, launches the right AAP job templates, and verifies the result.

The project is composed of three repos that work together:

| Repo | Language | Role |
|------|----------|------|
| `aap-mcp-server` | TypeScript | Exposes AAP REST APIs as MCP tools Claude can call |
| `ansible.mcp` | Python | Lets Ansible playbooks call Claude mid-execution via `run_tool` |
| `AAP-Enterprise-MCP-Server` | Python | Custom analytics MCP + Network Health Dashboard |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        NETWORK DEVICES                          │
│         IOS-XR · NX-OS · EOS · Junos · IOS-XE                  │
│  BGP tables, interface state, CPU/mem, temperature, uptime      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ SSH / NETCONF (via Ansible playbook)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              ANSIBLE AUTOMATION PLATFORM  (AAP)                 │
│  Runs playbooks → produces JSON reports → creates GitHub PR     │
│                                                                 │
│  Mock AAP Server :8080  (for local demo, no real AAP needed)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌──────────────────────┐         ┌─────────────────────────────┐
│  aap-mcp-server :3000│         │  network_analytics.py       │
│  (TypeScript)        │         │  Analytics MCP (stdio/7778) │
│  Auto-generated from │         │  IsolationForest · pipeline │
│  AAP OpenAPI spec    │         │  GitHub PR ingest · UI ctrl │
│  779 tools total     │         └────────────────┬────────────┘
│  network_health      │                          │
│  toolset active      │                          ▼
└──────────┬───────────┘         ┌─────────────────────────────┐
           │                     │  Dashboard :8000            │
           │                     │  FastAPI + Jinja2           │
           │                     │  Anomaly scan UI            │
           │                     └─────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CLAUDE  (AI Reasoning Layer)                  │
│  Calls MCP tools · Interprets results · Decides what to do next │
│                                                                 │
│  ┌───────────────────────────────────────┐                      │
│  │  ansible.mcp collection               │                      │
│  │  run_tool module — Ansible → Claude   │                      │
│  └───────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

**Key design insight — bidirectionality:**

| Direction | How | Who is in control |
|-----------|-----|------------------|
| Claude → AAP | `aap-mcp-server` exposes AAP REST as MCP tools | Claude drives the loop |
| Ansible → Claude | `ansible.mcp.run_tool` module in a playbook | Playbook drives, Claude reasons |

Both directions can be **composed**: a workflow canvas node can be a playbook (Ansible in control) that calls Claude for a reasoning decision, while Claude is simultaneously monitoring the job from outside via AAP MCP.

---

## 3. Implementation Details — How Claude Talks to AAP

### 3.1 The MCP Transport Layer — `aap-mcp-server`

The TypeScript `aap-mcp-server` reads the **AAP OpenAPI specifications** and generates MCP tools automatically. No hand-coded tool definitions.

**Configuration — `aap-mcp.yaml`:**

```yaml
services:
  - name: controller
    local_path: data/controller-schema.json   # AAP Controller REST API spec
    enabled: true
  - name: eda
    local_path: data/eda-openapi.json          # Event-Driven Ansible API spec
    enabled: true
  - name: galaxy
    local_path: data/galaxy-openapi.json
    enabled: false
  - name: gateway
    local_path: data/gateway-schema.json
    enabled: false

toolsets:
  network_health:
    # List & inspect job templates
    - controller.job_templates_list
    - controller.job_templates_retrieve
    - controller.job_templates_launch_retrieve
    # Launch jobs
    - controller.job_templates_launch_create
    # Poll status & fetch output
    - controller.jobs_list
    - controller.jobs_retrieve
    - controller.jobs_stdout_retrieve
    - controller.jobs_job_events_list
    - controller.jobs_cancel_create
    # Projects
    - controller.projects_list
    - controller.projects_retrieve
    - controller.projects_playbooks_retrieve
    - controller.projects_update_create
    # Inventory & hosts
    - controller.inventories_list
    - controller.inventories_retrieve
    - controller.hosts_list
    - controller.hosts_retrieve
    # EDA — event-triggered remediations
    - eda.activations_list
    - eda.activation_instances_list
    - eda.activation_instances_logs_list
```

When Claude calls `controller.job_templates_list`, the server translates it to:

```
GET https://<aap>/api/controller/v2/job_templates/
Authorization: Bearer <token>
```

Claude never touches the REST API directly — it calls the named MCP tool and gets back structured data.

---

### 3.2 MCP Tools Exposed to Claude

Complete tool catalogue for the `network_health` toolset:

#### Controller — Job Templates

| MCP Tool | REST Equivalent | What Claude does with it |
|----------|----------------|--------------------------|
| `job_templates_list` | `GET /api/v2/job_templates/` | "What automation jobs are available?" |
| `job_templates_retrieve` | `GET /api/v2/job_templates/{id}/` | "Tell me about job template 9" |
| `job_templates_launch_create` | `POST /api/v2/job_templates/{id}/launch/` | "Run the network inventory report job" |
| `job_templates_launch_retrieve` | `GET /api/v2/job_templates/{id}/launch/` | Check what extra_vars a template accepts |

#### Controller — Jobs (Status & Output)

| MCP Tool | REST Equivalent | What Claude does with it |
|----------|----------------|--------------------------|
| `jobs_list` | `GET /api/v2/jobs/` | "Show me recent job executions" |
| `jobs_retrieve` | `GET /api/v2/jobs/{id}/` | Poll status: pending → running → successful |
| `jobs_stdout_retrieve` | `GET /api/v2/jobs/{id}/stdout/?format=txt` | Stream full playbook output |
| `jobs_job_events_list` | `GET /api/v2/jobs/{id}/job_events/` | Task-level events: which tasks passed/failed |
| `jobs_cancel_create` | `POST /api/v2/jobs/{id}/cancel/` | Abort a running job |

#### Controller — Projects

| MCP Tool | REST Equivalent | What Claude does with it |
|----------|----------------|--------------------------|
| `projects_list` | `GET /api/v2/projects/` | "What AAP projects do we have?" |
| `projects_retrieve` | `GET /api/v2/projects/{id}/` | Get project SCM URL, last sync status |
| `projects_playbooks_retrieve` | `GET /api/v2/projects/{id}/playbooks/` | List playbooks in a project |
| `projects_update_create` | `POST /api/v2/projects/{id}/update/` | Trigger a Git sync |

#### Controller — Inventory & Hosts

| MCP Tool | REST Equivalent | What Claude does with it |
|----------|----------------|--------------------------|
| `inventories_list` | `GET /api/v2/inventories/` | "What inventories exist?" |
| `inventories_retrieve` | `GET /api/v2/inventories/{id}/` | Get hosts count, variables |
| `hosts_list` | `GET /api/v2/hosts/` | "How many devices are in the network inventory?" |
| `hosts_retrieve` | `GET /api/v2/hosts/{id}/` | Get host variables, last job status |

#### EDA — Event-Driven Ansible

| MCP Tool | REST Equivalent | What Claude does with it |
|----------|----------------|--------------------------|
| `eda.activations_list` | `GET /api/eda/v1/activations/` | "Are any EDA activations running?" |
| `eda.activation_instances_list` | `GET /api/eda/v1/activation-instances/` | Check which rulebooks are active |
| `eda.activation_instances_logs_list` | `GET /api/eda/v1/activation-instances/{id}/logs/` | Read EDA event logs |

---

### 3.3 How a Job Gets Launched via MCP

When Claude says "run the network inventory report job", here is exactly what happens in code:

**Step 1 — Claude calls the MCP tool:**
```
Tool: controller.job_templates_launch_create
Args: { "id": 9, "extra_vars": {} }
```

**Step 2 — `network_analytics.py` fires the AAP REST call:**

```python
# network_analytics.py — run_job_template()

def run_job_template(template_id: int, extra_vars: Optional[dict] = None) -> dict:
    """Fire a JT on Controller (simple happy-path) and wait for completion."""
    launch_url = f"{AAP_URL}/job_templates/{template_id}/launch/"

    # POST to launch
    res = _http("POST", launch_url, {"extra_vars": extra_vars or {}})
    job_id = res["job"]

    # Poll until terminal state
    while True:
        j = _http("GET", f"{AAP_URL}/jobs/{job_id}/")
        status = j.get("status")
        if status in {"successful", "failed", "error", "canceled"}:
            break
        time.sleep(2)

    # Fetch stdout
    stdout_resp = _http("GET", f"{AAP_URL}/jobs/{job_id}/stdout/?format=txt")
    return {"ok": status == "successful", "status": status, "job_id": job_id, "stdout": stdout_resp}
```

**Step 3 — Auth is injected via bearer token:**

```python
# network_analytics.py — _http()

AAP_URL   = os.environ.get("AAP_URL")    # e.g. https://aap.example.com/api/controller/v2
AAP_TOKEN = os.environ.get("AAP_TOKEN")  # AAP OAuth token or PAT

def _http(method: str, url: str, data: Optional[dict] = None) -> dict:
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {AAP_TOKEN}")
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data else None
    with urllib.request.urlopen(req, data=body) as r:
        return json.loads(r.read().decode("utf-8"))
```

**Step 4 — The MCP tool in `network_analytics.py` wraps it:**

```python
@mcp.tool()
def run_reports_controller(
    template_id: int,
    extra_vars_json: Optional[str] = None
) -> dict:
    """
    Run a Controller Job Template and wait for completion.
    """
    ev = json.loads(extra_vars_json) if extra_vars_json else None
    return run_job_template(template_id, ev)
```

Claude calls `run_reports_controller(template_id=9)` → MCP routes to this function → HTTP POST to AAP → polls until done → returns result to Claude.

---

### 3.4 The Analytics MCP Server — `network_analytics.py`

This is a **FastMCP server** (Python) that exposes the full detect → pipeline → export loop as MCP tools Claude can call. It runs as a stdio process and Claude Desktop connects to it via the MCP stdio transport.

**All tools exposed by this server:**

| Tool | What It Does | Key Parameters |
|------|-------------|----------------|
| `run_reports_local` | Run `ansible-playbook` locally | `playbook_path`, `inventory`, `out_file` |
| `run_reports_controller` | Launch AAP Job Template and wait | `template_id`, `extra_vars_json` |
| `detect_anomalies` | Run IsolationForest over JSON glob | `input_glob`, `contamination`, `id_field` |
| `run_pipeline_local` | Local playbook → auto detect anomalies | `playbook_path`, `inventory`, `contamination` |
| `export_to_ui` | Copy output files to dashboard uploads/ | `ui_dir` (optional) |
| `start_ui` | Launch FastAPI dashboard via uvicorn | `app_path`, `port`, `host` |
| `stop_ui` | Stop the dashboard process | — |
| `ui_status` | Check if dashboard is running | — |
| `ingest_github_pr` | Pull report files from a GitHub PR | `pr_url`, `include_glob` |
| `ingest_raw_url` | Fetch YAML/JSON report from any URL | `url`, `save_as` |

**How Claude connects to this server (Claude Desktop config):**

```json
{
  "mcpServers": {
    "aap-network": {
      "type": "http",
      "url": "http://localhost:3000/mcp/network_health"
    },
    "network-analytics": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/AAP-Enterprise-MCP-Server",
        "run",
        "network_analytics.py"
      ]
    }
  }
}
```

---

### 3.5 ML Anomaly Detection Engine — `agent/detector.py`

The core anomaly detection runs **IsolationForest** from scikit-learn on every page load of the dashboard, and is also callable directly as the `detect_anomalies` MCP tool.

**Feature matrix — 18 candidates per device:**

```python
# agent/detector.py — _build_feature_matrix()

candidates = [
    # From inventory reports
    "mem_used_pct",          # Memory usage %
    "license_expired",       # 0 or 1 (bool)
    "iface_total",           # Total interface count
    "iface_enabled",         # Enabled interfaces
    "iface_enabled_ratio",   # Ratio (enabled / total)
    "bgp_peers",             # BGP neighbor count
    "v4nets",                # IPv4 route count
    "v6nets",                # IPv6 route count
    "uptime_days",           # Device uptime in days

    # From healthcheck reports (hc_ prefix)
    "hc_cpu_1min",           # CPU 1-min average
    "hc_cpu_5min",           # CPU 5-min average
    "hc_cpu_threshold",      # Configured CPU threshold
    "hc_mem_util",           # Memory utilization %
    "hc_mem_threshold",      # Configured memory threshold
    "hc_env_temp",           # Environment temperature
    "hc_env_temp_threshold", # Temperature threshold
    "hc_uptime_min",         # Uptime in minutes
    "hc_uptime_min_threshold", # Minimum uptime SLO
]
```

**Preprocessing before ML:**
- Missing values → **median imputed** (not dropped — works with partial data)
- Zero-variance columns → **dropped** (e.g. if all devices have same BGP count)

**IsolationForest configuration:**

```python
# agent/detector.py — detect_outliers_iforest()

clf = IsolationForest(
    n_estimators=300,         # 300 trees = stable scoring
    contamination=0.20,       # Expect 20% of fleet to be anomalous
    max_features=1.0,
    bootstrap=False,
    random_state=42           # Reproducible
)
clf.fit(X)

pred   = clf.predict(X)       # -1 = anomaly, 1 = normal
scores = clf.score_samples(X) # lower score = more anomalous
```

**Fallback to rule-based detection** if ML finds nothing (works on very small fleets):

```python
# app.py — index()

if not anomalies:
    # Rule-based fallback
    for r in rows:
        lic_bad      = r.get("license_expired") == 1
        many_disabled = r.get("iface_enabled_ratio", 1.0) < 0.6
        mem_high     = r.get("mem_used_pct", 0) >= 85.0
        if lic_bad or many_disabled or mem_high:
            flagged.append(r)
```

---

### 3.6 Remediation Action Generator — `agent/actions.py`

After anomaly detection, `suggest_actions()` analyzes each flagged device and generates human-readable fix recommendations. These feed both the dashboard UI and the `execute_plan` step.

**Decision logic per device:**

```python
# agent/actions.py — suggest_actions()

# License
if lic_expired == 1:
    → "License expired/invalid: renew or correct device licensing."

# Memory (inventory)
if mem_used_pct >= 85:
    → "High memory usage (≥85%): review processes, collect tech-support..."

# Interface ratio
if iface_enabled_ratio < 0.5:
    → f"Low interface enablement: {disabled}/{total} interfaces disabled..."

# BGP neighbors
if bgp_peers == 0:
    → "BGP configured but 0 neighbors up: verify neighbor config/reachability."

# BGP timers
if hold < 3 * keepalive:
    → f"BGP timers unusual (hold={hold}, keepalive={keepalive})"

# CPU (from healthchecks)
if cpu_1min >= cpu_threshold:
    → f"CPU at/over threshold ({cpu_1min} ≥ {cpu_threshold}). Investigate..."
elif cpu_1min >= 0.9 * cpu_threshold:
    → "CPU nearing threshold. Monitor and plan capacity."

# Memory (from healthchecks)
if hc_mem_util >= hc_mem_threshold:
    → f"Memory utilization high ({hc_mem_util}% ≥ {hc_mem_threshold}%)..."

# Uptime SLO
if hc_uptime_min < hc_uptime_min_threshold:
    → f"Uptime below SLO ({uptime} < {threshold} minutes)..."

# Temperature
if hc_env_over > 0:
    → f"Environment temperature high ({temp} > {threshold})..."

# Power / Fans
if hc_power_ok == 0:
    → "Power health not OK: check PSUs and power feeds."
```

---

### 3.7 The Dashboard — `app.py`

A **FastAPI + Jinja2** web server running at `:8000`. ML detection runs on every page load so the view is always current.

**Route map:**

| Route | Method | What it does |
|-------|--------|-------------|
| `GET /` | page load | Load all JSON → run IsolationForest → render device grid with anomalies |
| `POST /scan` | button | Re-run with user-chosen algo (IForest or IQR) + optional host filter |
| `POST /execute` | button | Re-detect with IQR → generate actions → `execute_plan()` → show results |
| `GET /reports` | nav | List all uploaded JSON reports |
| `GET /report?host=...` | drill-down | Full device data + health badges |
| `GET /health?host=...` | drill-down | Raw healthcheck metrics per device |
| `POST /upload` | file drop | Accept multi-file upload of JSON reports |
| `POST /ingest` | API | Accept a single device JSON payload |
| `POST /load-samples` | button | Load bundled sample data from `sample_reports/` |

---

### 3.8 Ansible → Claude Direction — `ansible.mcp` Collection

The `ansible.mcp` collection is the **reverse channel**: standard Ansible playbooks can call any MCP server mid-execution for a reasoning step. This is the key integration point for the Ansible Orchestrator.

**The module is `ansible.mcp.run_tool`:**

```yaml
# Example playbook task

- name: Detect anomalies via Claude MCP
  ansible.mcp.run_tool:
    name: detect_anomalies
    args:
      input_glob: "/tmp/network_reports/*"
      contamination: 0.10
  connection: ansible.mcp.mcp
  vars:
    ansible_mcp_server_url: "http://localhost:7778"
  register: anomaly_result

- name: Launch remediation job if critical anomalies found
  ansible.mcp.run_tool:
    name: job_templates_launch_create
    args:
      id: "{{ remediation_template_id }}"
      extra_vars:
        affected_hosts: "{{ anomaly_result.output.anomalies | map(attribute='host') | list }}"
  connection: ansible.mcp.mcp
  vars:
    ansible_mcp_server_url: "{{ aap_mcp_url }}"
  when: anomaly_result.output.anomaly_count | int > 0
```

**Plugins provided:**

| Plugin | Type | Purpose |
|--------|------|---------|
| `ansible.mcp.mcp` | Connection | Establishes stdio or HTTP transport to an MCP server |
| `ansible.mcp.run_tool` | Module | Calls a named tool on the connected MCP server |
| `ansible.mcp.server_info` | Module | Returns metadata about the connected MCP server |
| `ansible.mcp.tools_info` | Module | Lists all tools available on the connected server |

---

## 4. Full Data Flow: The 6-Step Network Health Loop

This is the complete closed loop when Claude drives the full operations cycle:

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 1 — COLLECT                                               │
│                                                                 │
│  Claude calls: run_reports_controller(template_id=9)            │
│                        ↓                                        │
│  network_analytics.py:                                          │
│    POST /api/v2/job_templates/9/launch/                         │
│    Bearer: AAP_TOKEN                                            │
│    Polls: GET /api/v2/jobs/{id}/  every 2s                      │
│    Fetches: GET /api/v2/jobs/{id}/stdout/?format=txt            │
│                        ↓                                        │
│  AAP runs playbook on IOS-XR / NX-OS devices                   │
│  Writes: {host}_inventory.json + {host}_healthchecks.json       │
│  Creates GitHub PR with the output files                        │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 2 — DETECT                                                │
│                                                                 │
│  Claude calls: detect_anomalies(input_glob="uploads/*")         │
│                        ↓                                        │
│  agent/loader.py: parse inventory + healthcheck JSON files      │
│  agent/detector.py:                                             │
│    - Build 18-feature matrix                                    │
│    - Median-impute missing values                               │
│    - Drop zero-variance columns                                 │
│    - IsolationForest(n_estimators=300, contamination=0.10)      │
│    - Returns: anomalous hosts + _iforest_score per host         │
│                                                                 │
│  Example result:                                                │
│    iosxr-core-01  score=-0.43  ← ANOMALY                        │
│    nxos-agg-01    score=+0.12  ← normal                         │
│    nxos-agg-02    score=+0.09  ← normal                         │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 3 — REASON                                                │
│                                                                 │
│  Claude interprets scores in natural language (no tool call):   │
│                                                                 │
│  "iosxr-core-01 has score −0.43. It shows:                      │
│   - Memory at 87% (threshold: 85%)                              │
│   - License: EVAL EXPIRED                                       │
│   - Uptime: 5 days (below 7-day SLA)                           │
│   This combination suggests license failure causing resource    │
│   pressure. Priority: high."                                    │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 4 — REMEDIATE                                             │
│                                                                 │
│  Claude calls: job_templates_list()                             │
│  Claude calls: job_templates_launch_create(                     │
│                  id=10,                                         │
│                  extra_vars={"affected_host": "iosxr-core-01"}  │
│                )                                                │
│                        ↓                                        │
│  AAP runs remediation playbook on iosxr-core-01                 │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 5 — MONITOR                                               │
│                                                                 │
│  Claude calls: jobs_retrieve(id=<job_id>)        ← poll status  │
│  Claude calls: jobs_stdout_retrieve(id=<job_id>) ← stream logs  │
│  Claude calls: jobs_job_events_list(id=<job_id>) ← task events  │
└─────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 6 — VERIFY                                                │
│                                                                 │
│  Claude calls: detect_anomalies(input_glob="uploads/*")         │
│  Confirms: iosxr-core-01 anomaly score improved                 │
│  Claude calls: export_to_ui()                                   │
│  Dashboard refreshes with updated device health status          │
└─────────────────────────────────────────────────────────────────┘
```

**Every step above is a Claude reasoning action over an MCP tool. This IS an Ansible-native AI workflow.**
