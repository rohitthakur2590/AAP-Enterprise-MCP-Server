# agent/loader.py
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Any

def _mb(v):
    try:
        return float(v)
    except Exception:
        return None

def _mem_used_pct(dev):
    mem = dev.get("memory", {}) if isinstance(dev, dict) else {}
    tot = _mb(mem.get("total_mb"))
    free = _mb(mem.get("free_mb"))
    if tot is None or free is None:
        return None
    used = max(tot - free, 0.0)
    return (used / tot) * 100.0 if tot else None

def _iface_counts(agr):
    ifaces = agr.get("interfaces", []) or []
    total = len(ifaces)
    enabled = sum(1 for i in ifaces if i.get("enabled") is True)
    ratio = (enabled / total) if total else 1.0
    return total, enabled, ratio

def _bgp_features(agr):
    bgp_g = agr.get("bgp_global") or {}
    bgp_af = agr.get("bgp_address_family") or {}
    peers = len(bgp_g.get("neighbors") or [])
    v4 = 0; v6 = 0
    for af in (bgp_af.get("address_family") or []):
        if af.get("afi") == "ipv4":
            v4 += len(af.get("networks") or [])
        elif af.get("afi") == "ipv6":
            v6 += len(af.get("networks") or [])
    timers = (bgp_g.get("timers") or {}).get("bgp") or {}
    keepalive = timers.get("keepalive")
    hold = timers.get("holdtime")
    return peers, v4, v6, keepalive, hold

def _device_info_obj(agr):
    di = agr.get("device_info")
    if isinstance(di, list) and di:
        di = di[0]
    return di or {}

# -------------------------
# Healthchecks integration
# -------------------------
_HEALTH_RE = re.compile(r"^(?P<host>[^_]+)_.+_healthchecks\.json$", re.IGNORECASE)

def _host_from_health_filename(p: Path) -> str | None:
    m = _HEALTH_RE.match(p.name)
    return m.group("host") if m else None

def _safe_num(x):
    try:
        return float(x)
    except Exception:
        return None

def _merge_health(hout: Dict[str, Any], hc: Dict[str, Any]):
    """Merge a single health_checks block into accumulator for a host."""
    checks = hc.get("health_checks", {}) or {}

    # CPU
    if "cpu_utilization" in checks:
        cpu = checks["cpu_utilization"] or {}
        hout["hc_cpu_1min"] = _safe_num(cpu.get("1_min_avg"))
        hout["hc_cpu_5min"] = _safe_num(cpu.get("5_min_avg"))
        hout["hc_cpu_threshold"] = _safe_num(cpu.get("threshold"))

    # Memory
    if "memory_utilization" in checks:
        mu = checks["memory_utilization"] or {}
        hout["hc_mem_util"] = _safe_num(mu.get("current_utilization"))
        hout["hc_mem_threshold"] = _safe_num(mu.get("threshold"))

    if "memory_free" in checks:
        mf = checks["memory_free"] or {}
        hout["hc_mem_free"] = _safe_num(mf.get("current_free"))
        hout["hc_mem_free_mb"] = _safe_num(mf.get("free_mb"))

    if "memory_buffers" in checks:
        mb = checks["memory_buffers"] or {}
        hout["hc_mem_buffers"] = _safe_num(mb.get("current_buffers"))
        hout["hc_mem_buffers_mb"] = _safe_num(mb.get("buffers_mb"))

    if "memory_cache" in checks:
        mc = checks["memory_cache"] or {}
        hout["hc_mem_cache"] = _safe_num(mc.get("current_cache"))
        hout["hc_mem_cache_mb"] = _safe_num(mc.get("cache_mb"))

    # Uptime
    if "uptime" in checks:
        up = checks["uptime"] or {}
        hout["hc_uptime_min"] = _safe_num(up.get("current_uptime"))
        hout["hc_uptime_min_threshold"] = _safe_num(up.get("min_uptime"))

    # Environment
    if "environment" in checks:
        ev = checks["environment"] or {}
        temp = ev.get("temperature", {}) or {}
        cur_t = _safe_num(temp.get("current_temp"))
        thr_t = _safe_num(temp.get("threshold"))
        hout["hc_env_temp"] = cur_t
        hout["hc_env_temp_threshold"] = thr_t
        if cur_t is not None and thr_t is not None:
            hout["hc_env_over"] = max(cur_t - thr_t, 0.0)
        fans = ev.get("fans", {}) or {}
        hout["hc_fans_status"] = fans.get("status")
        power = ev.get("power", {}) or {}
        hout["hc_power_ok"] = 1.0 if str(power.get("status","")).upper() == "OK" else 0.0

    # Rollup status/result
    result = checks.get("result")
    if result:
        result = str(result).upper()
        if "hc_result" not in hout:
            hout["hc_result"] = result
        else:
            # If any sub-file says FAIL, roll up to FAIL
            if result == "FAIL":
                hout["hc_result"] = "FAIL"

    # Count failures in statuses where available
    fail_cnt = 0
    for k,v in checks.items():
        if k in ("result", "uptime_status_summary"):  # ignore these
            continue
        if isinstance(v, dict):
            st = str(v.get("status","")).upper()
            if st == "FAIL":
                fail_cnt += 1
    # threshold breach on temperature also counts
    if hout.get("hc_env_over", 0) and hout["hc_env_over"] > 0:
        fail_cnt += 1

    hout["hc_fail_count"] = float(hout.get("hc_fail_count", 0) or 0) + fail_cnt

def load_healthchecks(dir_path: str) -> Dict[str, Dict[str, Any]]:
    """Return merged health data per host from *_healthchecks.json files."""
    root = Path(dir_path)
    agg: Dict[str, Dict[str, Any]] = {}
    for p in sorted(root.glob("*_healthchecks.json")):
        host = _host_from_health_filename(p)
        if not host:
            continue
        try:
            obj = json.loads(p.read_text())
        except Exception:
            continue
        d = agg.setdefault(host, {})
        _merge_health(d, obj)
    return agg

def parse_report(path: Path) -> dict:
    obj = json.loads(Path(path).read_text())
    agr = obj.get("all_gathered_resources", {})
    dev = _device_info_obj(agr)

    host = dev.get("device_name") or dev.get("hostname") or path.stem
    os_type = dev.get("os_type")
    version = dev.get("version")
    image = dev.get("nxos_image_file") or dev.get("system_image")
    model = (dev.get("hardware") or {}).get("model")
    serial = (dev.get("hardware") or {}).get("serial_number")
    lic = (dev.get("license") or {}).get("status", "")
    lic_expired = 1 if str(lic).upper() in ("EXPIRED", "EVAL EXPIRED", "INVALID") else 0

    mem_used_pct = _mem_used_pct(dev)
    iface_total, iface_enabled, iface_ratio = _iface_counts(agr)
    peers, v4nets, v6nets, ka, hold = _bgp_features(agr)

    up = dev.get("uptime") or {}
    uptime_d = up.get("days")
    uptime_h = up.get("hours")

    return {
        "host": host,
        "os_type": os_type,
        "version": version,
        "image": image,
        "model": model,
        "serial": serial,
        "license_status": lic or "UNKNOWN",
        "license_expired": lic_expired,
        "mem_used_pct": mem_used_pct if mem_used_pct is not None else None,
        "iface_total": iface_total,
        "iface_enabled": iface_enabled,
        "iface_enabled_ratio": iface_ratio,
        "bgp_peers": peers,
        "v4nets": v4nets,
        "v6nets": v6nets,
        "bgp_keepalive": ka,
        "bgp_hold": hold,
        "uptime_days": uptime_d,
        "uptime_hours": uptime_h,
        "source": str(path),
        "raw": obj,
    }

def load_dir(dir_path: str) -> List[dict]:
    root = Path(dir_path)
    rows = []
    for p in sorted(root.glob("*.json")):
        # exclude *_healthchecks.json (handled by load_healthchecks)
        if p.name.endswith("_healthchecks.json"):
            continue
        try:
            rows.append(parse_report(p))
        except Exception as e:
            print(f"[load_dir] failed {p.name}: {e}")

    # merge health data into inventory rows
    health_by_host = load_healthchecks(dir_path)
    for r in rows:
        h = health_by_host.get(r["host"])
        if h:
            r.update(h)
    return rows
