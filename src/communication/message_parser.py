from __future__ import annotations

from typing import Any, Dict


def format_state_update(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": state.get("status", "IDLE"),
        "traffic_light": state.get("traffic_light", "RED"),
        "elapsed_time": state.get("elapsed_time", 0.0),
        "lap": state.get("lap", 0),
        "team": state.get("current_team", {}).get("team_name", "N/A"),
    }


def parse_state_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return format_state_update(payload)
