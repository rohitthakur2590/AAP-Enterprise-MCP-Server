from __future__ import annotations
from typing import Dict, List

def execute_plan(plan: Dict[str, List[str]]) -> Dict[str, str]:
    # Simulated; replace with ansible-runner calls later
    return {host: f"Executed {len(steps)} step(s) (simulated)" for host, steps in plan.items()}
