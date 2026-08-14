"""
Scraper for aoe2companion.com.

Match data uses the public REST API (no Selenium needed for matches).
Selenium is kept only for player profile name lookups as fallback.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "https://www.aoe2companion.com"
_API_BASE = "https://data.aoe2companion.com/api"
_HEADERS = {"User-Agent": "PlayerReferences/1.0"}
WAIT_TIMEOUT = 15


# -- Data classes --------------------------------------------------------------

@dataclass
class PlayerInfo:
    profile_id: int
    name: str
    steam_id: str | None = None


@dataclass
class MatchPlayer:
    profile_id: int
    name: str
    team_id: int
    civ_name: str | None = None
    rating: int | None = None
    won: bool | None = None
    is_me: bool = False


@dataclass
class MatchInfo:
    match_key: str
    all_players: list[MatchPlayer] = field(default_factory=list)
    map_name: str | None = None
    started_at: str | None = None
    is_live: bool = False
    my_won: bool | None = None

    @property
    def opponents(self) -> list[dict]:
        return [
            {
                "pid": p.profile_id,
                "name": p.name,
                "team": p.team_id,
                "civ": p.civ_name,
                "rating": p.rating,
            }
            for p in self.all_players
            if not p.is_me
        ]

    @property
    def teams_dict(self) -> dict[int, list[MatchPlayer]]:
        result: dict[int, list[MatchPlayer]] = {}
        for p in self.all_players:
            result.setdefault(p.team_id, []).append(p)
        return result


# -- API-based match fetching --------------------------------------------------

def get_player_matches(profile_id: int, count: int = 20) -> list[MatchInfo]:
    """
    Fetch recent matches for a player via the public aoe2companion API.
    Returns a list of MatchInfo; live matches appear first.
    """
    try:
        resp = requests.get(
            f"{_API_BASE}/matches",
            params={"profile_ids": profile_id, "count": count},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Error en la API: {exc}") from exc

    results: list[MatchInfo] = []
    for m in data.get("matches", []):
        players: list[MatchPlayer] = []
        my_won: bool | None = None

        for team in m.get("teams", []):
            team_id = team.get("teamId", 0)
            for p in team.get("players", []):
                pid = p.get("profileId")
                is_me = pid == profile_id
                won_val = p.get("won")
                if is_me and won_val is not None:
                    my_won = bool(won_val)
                players.append(
                    MatchPlayer(
                        profile_id=pid,
                        name=p.get("name") or str(pid),
                        team_id=team_id,
                        civ_name=p.get("civName"),
                        rating=p.get("rating"),
                        won=None if won_val is None else bool(won_val),
                        is_me=is_me,
                    )
                )

        results.append(
            MatchInfo(
                match_key=str(m["matchId"]),
                all_players=players,
                map_name=m.get("mapName"),
                started_at=m.get("started"),
                is_live=m.get("finished") is None,
                my_won=my_won,
            )
        )

    return results


def get_player_name_api(profile_id: int) -> str | None:
    """Quick player name lookup via API."""
    try:
        resp = requests.get(
            f"{_API_BASE}/profiles/{profile_id}",
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("name")
    except Exception:
        pass
    return None


# -- Selenium helpers (kept for optional web interaction) ----------------------

def build_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    driver.implicitly_wait(0)
    return driver
