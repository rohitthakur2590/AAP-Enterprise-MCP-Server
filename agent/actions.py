# agent/actions.py
from __future__ import annotations
from typing import Dict, List, Any, Optional

def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) else None

def _str(x: Any) -> str:
    return str(x) if x is not None else ""

def suggest_actions(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Produce per-host suggestions, using only fields that are actually present.
    Safe against None/missing keys. Extends your original logic with healthcheck-
    driven hints (CPU, memory, uptime, environment, power/fans).
    """
    actions: Dict[str, List[str]] = {}

    for r in rows:
        host = r.get("host", "unknown")
        sug: List[str] = []

        # -----------------
        # Inventory-derived
        # -----------------
        # License
        lic_status = r.get("license_status")  # None means not present
        lic_expired = r.get("license_expired")
        if lic_status is not None and lic_expired == 1:
            sug.append("License expired/invalid: renew or correct device licensing.")

        # Memory pressure (inventory mem_used_pct)
        mem = _num(r.get("mem_used_pct"))
        if mem is not None and mem >= 85:
            sug.append("High memory usage (≥85%): review processes, collect tech-support, consider maintenance window.")

        # Interface enablement ratio
        iface_total = r.get("iface_total")
        iface_enabled = r.get("iface_enabled")
        iface_ratio = r.get("iface_enabled_ratio")
        if isinstance(iface_total, int) and isinstance(iface_enabled, int) and isinstance(iface_ratio, (int, float)):
            if iface_total > 0 and iface_ratio < 0.5:
                disabled = iface_total - iface_enabled
                sug.append(
                    f"Low interface enablement: {disabled}/{iface_total} interfaces disabled. "
                    "Audit unused/err-disabled ports."
                )

        # BGP presence & timers sanity (only if BGP exists)
        bgp_peers = r.get("bgp_peers")
        if bgp_peers is not None:
            if isinstance(bgp_peers, int) and bgp_peers == 0:
                sug.append("BGP configured but 0 neighbors up: verify neighbor config/reachability.")
            ka = _num(r.get("bgp_keepalive"))
            hold = _num(r.get("bgp_hold"))
            # Typical rule of thumb: hold >= 3 * keepalive
            if ka is not None and hold is not None and hold < 3 * ka:
                sug.append(f"BGP timers unusual (hold={hold}, keepalive={ka}): confirm with policy.")

        # Uptime from inventory (coarse)
        uptime_days = r.get("uptime_days")
        if isinstance(uptime_days, int) and uptime_days < 1:
            sug.append("Device recently rebooted (<1 day): review change history/maintenance.")

        # -----------------
        # Healthcheck-derived (hc_*)
        # -----------------
        # CPU thresholds
        cpu_1m = _num(r.get("hc_cpu_1min"))
        cpu_thr = _num(r.get("hc_cpu_threshold"))
        if cpu_1m is not None and cpu_thr is not None:
            if cpu_1m >= cpu_thr:
                sug.append(f"CPU at/over threshold ({cpu_1m} ≥ {cpu_thr}). Investigate busy processes and control-plane load.")
            elif cpu_1m >= 0.9 * cpu_thr:
                sug.append(f"CPU nearing threshold ({cpu_1m}/{cpu_thr}). Monitor and plan capacity.")

        # Memory utilization vs threshold (from healthchecks)
        hc_mem_util = _num(r.get("hc_mem_util"))
        hc_mem_thr  = _num(r.get("hc_mem_threshold"))
        if hc_mem_util is not None and hc_mem_thr is not None and hc_mem_util >= hc_mem_thr:
            sug.append(f"Memory utilization high ({hc_mem_util}% ≥ {hc_mem_thr}%). Investigate processes/leaks and traffic patterns.")

        # Uptime minutes vs minimum (healthchecks)
        up_min = _num(r.get("hc_uptime_min"))
        up_min_thr = _num(r.get("hc_uptime_min_threshold"))
        if up_min is not None and up_min_thr is not None and up_min < up_min_thr:
            sug.append(f"Uptime below SLO ({int(up_min)} < {int(up_min_thr)} minutes). Review reboot cause and stability.")

        # Environment temperature
        env_over = _num(r.get("hc_env_over"))
        env_cur  = _num(r.get("hc_env_temp"))
        env_thr  = _num(r.get("hc_env_temp_threshold"))
        if env_over is not None and env_over > 0:
            if env_cur is not None and env_thr is not None:
                sug.append(
                    f"Environment temperature high ({env_cur} > {env_thr}). "
                    "Check airflow, fans, room cooling, and dust filters."
                )
            else:
                sug.append("Environment temperature high. Check airflow, fans, room cooling, and dust filters.")

        # Power/fans
        power_ok = _num(r.get("hc_power_ok"))
        if power_ok is not None and power_ok == 0:
            sug.append("Power health not OK: check PSUs and power feeds.")
        fans_status = _str(r.get("hc_fans_status")).lower()
        if fans_status and fans_status not in ("ok", "pass", "supported", "notsupported"):
            sug.append(f"Fans report '{fans_status}': verify fan modules and speeds.")

        # Roll-up result: if FAIL and nothing specific caught it, add a generic
        hc_result = _str(r.get("hc_result")).upper()
        if hc_result == "FAIL" and not sug:
            sug.append("Health check failure detected. Review CPU/memory/uptime/environment details.")

        actions[host] = sug or ["No immediate action; monitor and learn baseline."]

    return actions
