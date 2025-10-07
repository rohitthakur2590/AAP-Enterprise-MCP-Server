# agent/actions.py
from __future__ import annotations
from typing import Dict, List, Any, Optional

def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) else None

def suggest_actions(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Produce per-host suggestions, but only for features that are present.
    Uses None-safe checks to avoid type errors with optional fields.
    """
    actions: Dict[str, List[str]] = {}

    for r in rows:
        host = r.get("host", "unknown")
        sug: List[str] = []

        # License: only if license_status exists in the report
        lic_status = r.get("license_status")  # None means not present in report
        lic_expired = r.get("license_expired")
        if lic_status is not None and lic_expired == 1:
            sug.append("License expired/invalid: renew or correct device licensing.")

        # Memory pressure
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
                sug.append(f"Low interface enablement: {disabled}/{iface_total} interfaces disabled. Audit unused/err-disabled ports.")

        # BGP presence & health (None => BGP not configured)
        bgp_peers = r.get("bgp_peers")
        if bgp_peers is not None:
            if isinstance(bgp_peers, int) and bgp_peers == 0:
                sug.append("BGP configured but 0 neighbors up: verify neighbor config/reachability.")
            ka = _num(r.get("bgp_keepalive"))
            hold = _num(r.get("bgp_hold"))
            # Simple sanity: hold should typically be >= 3x keepalive
            if ka is not None and hold is not None and hold < 3 * ka:
                sug.append(f"BGP timers unusual (hold={hold}, keepalive={ka}): confirm with policy.")

        # Uptime
        uptime_days = r.get("uptime_days")
        if isinstance(uptime_days, int) and uptime_days < 1:
            sug.append("Device recently rebooted (<1 day): review change history/maintenance.")

        actions[host] = sug or ["No immediate action; monitor and learn baseline."]

    return actions
