# Network Health AI — AAP Enterprise MCP Server

An AI-powered network health monitoring and anomaly detection platform built on top of Red Hat Ansible Automation Platform (AAP), integrated with the **Model Context Protocol (MCP)**. Designed to showcase how Claude can act as an intelligent orchestration layer over AAP infrastructure.

---

## What This Is

This project demonstrates a **bidirectional MCP architecture** for AAP:

| Direction | Repo | What it does |
|-----------|------|--------------|
| **AAP → AI** | `ansible/aap-mcp-server` | Exposes AAP (Controller, EDA, Galaxy, Gateway) as MCP tools that Claude can call |
| **AI → Ansible** | `ansible-collections/ansible.mcp` | Lets Ansible playbooks call Claude via `run_tool` module |

On top of this, `network_analytics.py` adds a **FastMCP analytics server** that performs AI-driven anomaly detection on network device telemetry — and exposes results via a live dashboard.

---

## Demo: Network Health AI Dashboard

The dashboard ingests network device inventory + healthcheck reports, runs **Isolation Forest** anomaly detection, and renders a real-time UI showing device health, anomalies, and AI findings.

### Starting the Demo

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc

# Install Python dependencies
cd AAP-Enterprise-MCP-Server
uv sync

# Start the dashboard
uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** in your browser.

> **Quick start with sample data**: Copy files from `sample_reports/` into `uploads/` to pre-load 8 demo devices with 3 injected anomalies.

```bash
cp sample_reports/* uploads/
```

### Full Demo Stack (4 services)

Use the included orchestration script to run all services at once:

```bash
# From the network-mcp-tools/ root
./demo-start.sh start     # Start all services
./demo-start.sh stop      # Stop all services
./demo-start.sh status    # Check service health
./demo-start.sh logs      # Tail all logs
```

| Service | Port | Description |
|---------|------|-------------|
| Mock AAP Server | 8080 | Simulates AAP Controller + EDA APIs |
| AAP MCP Server | 3000 | MCP-over-HTTP bridge for AAP tools |
| Network Analytics MCP | 7778 | FastMCP stdio server for anomaly detection |
| Network Health Dashboard | 8000 | FastAPI + Jinja2 live dashboard |

---

## Architecture

The platform is a full-stack, AI-in-the-loop network operations system. Data flows from physical network devices up through Ansible collection and analysis, into an MCP layer that Claude reasons over, and finally surfaces in a web dashboard or chat interface.

```
┌──────────────────────────────────────────────────────────────┐
│                      Network Devices                         │
│           IOS-XR · NX-OS · EOS · Junos · IOS-XE             │
└──────────────────────────┬───────────────────────────────────┘
                           │  telemetry, configs, health stats
                           ▼
┌──────────────────────────────────────────────────────────────┐
│               Ansible Automation Platform (AAP)              │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────────────┐  │
│  │ Backup / Col- │  │ Restore Role  │  │  Scoring Engine │  │
│  │ lection Role  │  │               │  │  (health check) │  │
│  └───────────────┘  └───────────────┘  └─────────────────┘  │
│                                                              │
│  Mock AAP (:8080) — Controller + EDA APIs (demo mode)       │
└──────────────────────────┬───────────────────────────────────┘
                           │  structured JSON reports
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     MCP Server Layer                         │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │          AAP MCP Server  (:3000)                    │    │
│  │  Tools: job_templates · jobs · inventories · hosts  │    │
│  │         eda.activations · stdout · job_events        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │       Network Analytics MCP  (stdio / :7778)        │    │
│  │  Tools: detect_anomalies · run_pipeline_local       │    │
│  │         export_to_ui · run_reports_controller       │    │
│  │  Engine: Isolation Forest + IQR anomaly detection   │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬───────────────────────────────────┘
                           │  tool calls + results
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                  AI Assistant — Claude                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Natural Language Understanding · Reasoning           │  │
│  │  Anomaly Interpretation · Remediation Recommendations │  │
│  │  Tool Orchestration across AAP + Analytics MCP        │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────┘
                           │  findings + actions
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                      User Interface                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────┐  │
│  │  Network Health │  │  Ansible          │  │   Chat /  │  │
│  │  Dashboard      │  │  Workflow         │  │   Claude  │  │
│  │  (:8000)        │  │                  │  │   Desktop │  │
│  │  FastAPI+Jinja2 │  │                  │  │           │  │
│  └─────────────────┘  └──────────────────┘  └───────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Demo Service Map

| Service | Port | Role in Architecture |
|---------|------|----------------------|
| Mock AAP Server | 8080 | Stands in for a live AAP Controller + EDA during demo |
| AAP MCP Server | 3000 | Translates Claude tool calls into AAP REST API requests |
| Network Analytics MCP | 7778 | Runs anomaly detection; exposes results as MCP tools |
| Network Health Dashboard | 8000 | Visualises device health, anomalies, and AI findings |

### MCP Tools — Network Analytics

| Tool | Description |
|------|-------------|
| `run_reports_controller` | Execute network data collection playbooks via AAP |
| `detect_anomalies` | Run Isolation Forest + IQR on device telemetry |
| `run_pipeline_local` | Full local pipeline: load → analyze → export |
| `export_to_ui` | Push analysis results to the dashboard |
| `start_ui` | Launch the dashboard server |
| `stop_ui` | Stop the dashboard server |

### MCP Tools — AAP Controller (via `aap-mcp-server`)

| Tool | Description |
|------|-------------|
| `job_templates_list` | List available job templates |
| `job_templates_launch_create` | Launch a job template |
| `jobs_list` | List job executions |
| `jobs_retrieve` | Get job details and status |
| `jobs_stdout_retrieve` | Stream job output logs |
| `inventories_list` | List AAP inventories |
| `hosts_list` | List hosts within an inventory |
| `eda.activations_list` | List EDA activations |

---

## Sample Data & Anomaly Detection

The `sample_reports/` directory contains 16 files representing an 8-device network:

| Device | OS | Role | Injected Anomaly |
|--------|----|------|-----------------|
| `iosxr-core-01` | IOS-XR | Core Router | — (healthy) |
| `iosxr-core-02` | IOS-XR | Core Router | — (healthy) |
| `iosxr-edge-01` | IOS-XR | Edge Router | ⚠ CPU 91.4% (threshold 80%) |
| `iosxr-edge-02` | IOS-XR | Edge Router | — (healthy) |
| `iosxr-pe-01` | IOS-XR | PE Router | ⚠ Uptime 0d (just rebooted) + Temp 68.4°C |
| `iosxr-pe-02` | IOS-XR | PE Router | — (healthy) |
| `nxos-agg-01` | NX-OS | Aggregation | ⚠ Mem 91.5% + 0 BGP peers |
| `nxos-agg-02` | NX-OS | Aggregation | — (healthy) |

Isolation Forest is trained on the full feature matrix (CPU, memory, temperature, uptime, BGP peer count, interface counts) and flags the 3 anomalous hosts automatically.

### Report File Format

Each device requires two files in `uploads/`:

```
{host}_inventory.json               # Device inventory (interfaces, BGP, etc.)
{host}_{tag}_healthchecks.json      # Health metrics (CPU, mem, temp, uptime)
```

**Inventory JSON structure:**
```json
{
  "all_gathered_resources": {
    "device_info": { "os_type": "iosxr", "model": "NCS-5501", "version": "7.9.2" },
    "interfaces": [...],
    "bgp_global": { "as_number": 65000, "router_id": "10.0.0.1" },
    "bgp_address_family": [{ "afi": "ipv4", "neighbors": [...] }]
  }
}
```

**Healthcheck JSON structure:**
```json
{
  "cpu_1min": 45.2,
  "cpu_5min": 42.1,
  "cpu_threshold": 80,
  "mem_util": 67.3,
  "mem_threshold": 85,
  "env_temp": 42.0,
  "env_temp_threshold": 65,
  "uptime_min": 14400,
  "uptime_min_threshold": 60,
  "result": "PASS",
  "fail_count": 0
}
```

---

## Ansible Workflow Integration

This demo is designed to integrate with Ansible-native workflow orchestration, where each workflow step can be an MCP-powered Claude reasoning action:

```yaml
- name: detect_network_anomalies
  mcp_tool: detect_anomalies
  server: network_analytics
  inputs:
    report_dir: "{{ aap_job_output_path }}"
  outputs:
    anomalies: "{{ detected_anomalies }}"

- name: trigger_remediation
  mcp_tool: job_templates_launch_create
  server: aap_controller
  when: "{{ anomalies | length > 0 }}"
  inputs:
    template_id: "{{ remediation_template_id }}"
    extra_vars:
      affected_hosts: "{{ anomalies | map(attribute='host') | list }}"
```

### ansible.mcp Collection

The `ansible-collections/ansible.mcp` collection lets Ansible playbooks call MCP tools directly:

```yaml
- name: Run anomaly detection via Claude MCP
  ansible.mcp.run_tool:
    server_url: "http://localhost:7778"
    tool: detect_anomalies
    arguments:
      report_dir: /tmp/network_reports
  connection: ansible.mcp.mcp
  register: anomaly_results

- name: Show detected anomalies
  debug:
    msg: "{{ anomaly_results.output }}"
```

---

## Additional MCP Servers

This repo also includes standalone MCP servers for other Red Hat ecosystem integrations:

### Ansible Automation Platform (`ansible.py`)
Full AAP Controller integration — inventory management, job execution, project management, ad-hoc commands, and Galaxy collection discovery.

```bash
# MCP client config (Claude Desktop / Cursor)
{
  "mcpServers": {
    "ansible": {
      "command": "uv",
      "args": ["--directory", "/path/to/AAP-Enterprise-MCP-Server", "run", "ansible.py"],
      "env": {
        "AAP_TOKEN": "your-aap-api-token",
        "AAP_URL": "https://your-aap-server.com/api/controller/v2"
      }
    }
  }
}
```

### Event-Driven Ansible (`eda.py`)
EDA activation management, rulebook queries, decision environment control, and event stream monitoring.

```bash
{
  "mcpServers": {
    "eda": {
      "command": "uv",
      "args": ["--directory", "/path/to/AAP-Enterprise-MCP-Server", "run", "eda.py"],
      "env": {
        "EDA_TOKEN": "your-eda-api-token",
        "EDA_URL": "https://your-aap-server.com/api/eda/v1"
      }
    }
  }
}
```

### Ansible Lint (`ansible-lint.py`)
Real-time playbook linting with progressive quality profiles (basic → moderate → production), syntax validation, and full project structure analysis.

### Red Hat Documentation (`redhat_docs.py`)
Domain-validated access to 50+ official Red Hat documentation sites with PDF-first strategy, hybrid search, and telco/edge specialization.

---

## Installation

### Prerequisites
- Python 3.11+
- `uv` package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- Node.js 18+ (for `aap-mcp-server`)

### Install uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc  # or ~/.bashrc
```

### Install Python dependencies
```bash
cd AAP-Enterprise-MCP-Server
uv sync
```

### Environment Variables (optional — only needed for live AAP)
```bash
export AAP_TOKEN="your-aap-api-token"
export AAP_URL="https://your-aap-server.com/api/controller/v2"
export EDA_TOKEN="your-eda-api-token"
export EDA_URL="https://your-aap-server.com/api/eda/v1"
```

> The demo works fully with the included mock AAP server — no live AAP instance required.

---

## Usage Examples

### Detect Anomalies via MCP
```python
# Claude calls the anomaly detection MCP tool
result = await detect_anomalies(report_dir="uploads/")
# Returns: list of anomalous hosts with scores and AI findings
```

### Launch a Remediation Job via AAP
```python
# After anomalies are detected, Claude triggers a job template
job = await job_templates_launch_create(
    id=42,
    extra_vars={
        "target_hosts": ["iosxr-edge-01", "nxos-agg-01"],
        "action": "cpu_throttle_check"
    }
)

# Poll for completion
status = await jobs_retrieve(id=job["job"])
logs = await jobs_stdout_retrieve(id=job["job"])
```

### Galaxy Content Discovery
```python
# Find the right collection for your use case
suggestions = await suggest_ansible_content(
    use_case="Configure BGP routing on Cisco IOS-XR devices"
)

# Get collection details
details = await get_collection_details(namespace="cisco", name="iosxr")
```

### EDA Event-Driven Remediation
```python
# Check active EDA rulebook activations
activations = await list_activations()

# Enable network anomaly response activation
await enable_activation(activation_id=5)
```

---

## Dashboard UI

The dashboard at `http://127.0.0.1:8000` includes:

- **Status summary bar** — Total hosts, Healthy, Anomalies, Critical counts
- **Device table** — OS type, Memory %, CPU, Interfaces, BGP peers, Uptime with live status dots
- **Anomaly section** — Amber-highlighted rows with Isolation Forest score bars and AI findings
- **Health grid** — Per-device PASS/FAIL cards with threshold markers on progress bars
- **Upload panel** — Drop new report files to trigger live re-analysis

---

## Troubleshooting

**Dashboard shows no data**
Make sure report files are in `uploads/` with the correct naming pattern: `{host}_{tag}_healthchecks.json` (e.g., `iosxr-edge-01_network_healthchecks.json`). The `_network_` tag segment is required.

**`uv` command not found**
Run: `curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.zshrc`

**SSL errors connecting to AAP**
The server auto-disables SSL verification for lab environments with self-signed certificates.

**MCP client not picking up tools**
Restart your MCP client (Claude Desktop / Cursor) after any config changes.

---

## Project Structure

```
AAP-Enterprise-MCP-Server/
├── app.py                    # FastAPI dashboard server
├── network_analytics.py      # FastMCP analytics MCP server
├── ansible.py                # AAP Controller MCP server
├── eda.py                    # Event-Driven Ansible MCP server
├── ansible-lint.py           # Ansible Lint MCP server
├── redhat_docs.py            # Red Hat Documentation MCP server
├── agent/
│   ├── loader.py             # Report parser (inventory + healthchecks)
│   └── detector.py           # Isolation Forest + IQR anomaly detection
├── templates/
│   ├── base.html             # Shared layout (dark navbar, Ansible branding)
│   ├── index.html            # Main dashboard (summary cards + device table)
│   ├── anomalies_table.html  # Anomaly detail view with AI scores
│   └── health_grid.html      # Per-device health card grid
├── sample_reports/           # 8-device mock dataset (16 files)
├── uploads/                  # Active report directory (dashboard reads from here)
└── pyproject.toml            # uv/pip dependency manifest
```

---

## Related Projects

- [ansible/aap-mcp-server](https://github.com/ansible/aap-mcp-server) — AAP as an MCP server (TypeScript, mock AAP included)
- [ansible-collections/ansible.mcp](https://github.com/ansible-collections/ansible.mcp) — Ansible as an MCP client (collection)
- [Model Context Protocol](https://modelcontextprotocol.io/) — Open standard for AI tool integration
- [FastMCP](https://github.com/punkpeye/fastmcp) — Python MCP server framework

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*AI-powered network operations via Ansible + MCP* 🚀
