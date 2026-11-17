from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TeamRef:
    id: int
    name: str
    code: str = ""
    league_id: int = 0
    season: int = 0


@dataclass(frozen=True)
class Match:
    id: int
    date: datetime
    league_id: int
    season: int
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    home_goals: int | None = None
    away_goals: int | None = None
    status: str = "NS"
    referee_id: int | None = None
    referee_name: str = ""
    venue: str = ""
    round: str = ""

    @property
    def played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None

    @property
    def result(self) -> str:
        if not self.played:
            return ""
        if self.home_goals > self.away_goals:
            return "H"
        if self.home_goals < self.away_goals:
            return "A"
        return "D"

    def scoreline(self, team_id: int) -> str:
        if not self.played:
            return "-"
        if team_id == self.home_id:
            return f"{self.home_goals}-{self.away_goals}"
        return f"{self.away_goals}-{self.home_goals}"


@dataclass
class StandingRow:
    team_id: int
    position: int
    played: int
    points: int
    goals_for: int
    goals_against: int
    form: str = ""
    description: str = ""


@dataclass
class GoalProfile:
    penalties_scored: int = 0
    penalties_conceded: int = 0
    own_goals: int = 0
    first_half_for: int = 0
    second_half_for: int = 0
    first_half_against: int = 0
    second_half_against: int = 0
    xg_for: float | None = None
    xg_against: float | None = None
    big_chances_for: float | None = None
    big_chances_against: float | None = None


@dataclass
class TeamStats:
    team_id: int
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    gf: int = 0
    ga: int = 0
    gf_home: int = 0
    ga_home: int = 0
    gf_away: int = 0
    ga_away: int = 0
    form: list[tuple[str, str]] = field(default_factory=list)  # (W/D/L, "2-1")
    clean_sheets: int = 0
    btts: int = 0
    possession: float | None = None
    shots: float | None = None
    shots_on_target: float | None = None
    cards: float | None = None
    goals: GoalProfile = field(default_factory=GoalProfile)
    formation: str = ""
    style: str = ""


@dataclass
class RefereeStats:
    referee_id: int | None
    name: str = ""
    matches: int = 0
    avg_yellow: float = 0.0
    avg_red: float = 0.0
    avg_fouls: float = 0.0
    avg_penalties: float = 0.0
    home_win_rate: float = 0.0
    over25_rate: float = 0.0


@dataclass
class Injury:
    team_id: int
    player: str
    position: str = ""
    reason: str = ""
    importance: float = 1.0  # 0..1, estimated from appearances/goals when available


@dataclass
class FixtureContext:
    match: Match
    home: TeamStats
    away: TeamStats
    h2h: list[Match]
    standings: dict[int, StandingRow]
    injuries: dict[int, list[Injury]]
    referee: RefereeStats
    home_team: TeamRef
    away_team: TeamRef
    league_name: str = ""
    importance_flags: list[str] = field(default_factory=list)
    data_quality: float = 1.0
    history: list[Match] = field(default_factory=list)
    provider_error: str = ""
