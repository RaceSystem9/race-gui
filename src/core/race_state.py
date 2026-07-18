from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["RaceEvent", "RaceState"]


@dataclass
class RaceEvent:
    name: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RaceState:
    current_team: Dict[str, Any] = field(default_factory=dict)
    next_team: Dict[str, Any] = field(default_factory=dict)
    next_next_team: Dict[str, Any] = field(default_factory=dict)
    status: str = "IDLE"
    traffic_light: str = "RED"
    elapsed_time: float = 0.0
    lap: int = 0
    best_lap: Optional[float] = None
    rank: Optional[int] = None
    penalty_points: int = 0
    mission_scores: Dict[str, int] = field(default_factory=dict)
    mission_penalty_seconds: float = 0.0
    final_time: Optional[float] = None
    disqualified: bool = False
    event_log: List[str] = field(default_factory=list)
    timer_running: bool = False
    countdown: int = 0
    last_update: float = field(default_factory=time.time)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current_team": self.current_team,
            "next_team": self.next_team,
            "next_next_team": self.next_next_team,
            "status": self.status,
            "traffic_light": self.traffic_light,
            "elapsed_time": self.elapsed_time,
            "lap": self.lap,
            "best_lap": self.best_lap,
            "rank": self.rank,
            "penalty_points": self.penalty_points,
            "mission_scores": dict(self.mission_scores),
            "mission_penalty_seconds": self.mission_penalty_seconds,
            "final_time": self.final_time,
            "disqualified": self.disqualified,
            "event_log": list(self.event_log),
            "timer_running": self.timer_running,
            "countdown": self.countdown,
            "last_update": self.last_update,
        }

    def append_log(self, message: str) -> None:
        self.event_log.append(message)
        self.last_update = time.time()
