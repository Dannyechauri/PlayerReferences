import os
import sqlite3
import sys
from datetime import datetime, timezone
from contextlib import contextmanager

# Keep the DB next to the executable (frozen) or the source file (dev)
_BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
DB_PATH = os.path.join(_BASE_DIR, "players.db")


def init_db():
    with _connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opponents (
                profile_id  INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opponent_name_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id  INTEGER NOT NULL,
                name        TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_opp_name_hist
            ON opponent_name_history(profile_id, recorded_at)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                my_pid      INTEGER NOT NULL,
                match_key   TEXT NOT NULL,
                map_name    TEXT,
                started_at  TEXT,
                is_live     INTEGER DEFAULT 0,
                my_won      INTEGER,
                scraped_at  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_key
            ON matches(my_pid, match_key)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS match_opponents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id    INTEGER NOT NULL REFERENCES matches(id),
                profile_id  INTEGER,
                name        TEXT NOT NULL,
                team_id     INTEGER,
                civ_name    TEXT,
                rating      INTEGER,
                won         INTEGER
            )
        """)
        # Detect and fix old match_opponents schema (opponent_pid → profile_id)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(match_opponents)").fetchall()}
        if "opponent_pid" in cols and "profile_id" not in cols:
            conn.execute("DROP TABLE match_opponents")
            conn.execute("""
                CREATE TABLE match_opponents (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id    INTEGER NOT NULL REFERENCES matches(id),
                    profile_id  INTEGER,
                    name        TEXT NOT NULL,
                    team_id     INTEGER,
                    civ_name    TEXT,
                    rating      INTEGER,
                    won         INTEGER
                )
            """)
        # Detect and fix old matches schema (tracked_profile_id → my_pid)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
        if "tracked_profile_id" in cols and "my_pid" not in cols:
            conn.execute("DROP TABLE IF EXISTS match_opponents")
            conn.execute("DROP TABLE matches")
            conn.execute("""
                CREATE TABLE matches (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    my_pid      INTEGER NOT NULL,
                    match_key   TEXT NOT NULL,
                    map_name    TEXT,
                    started_at  TEXT,
                    is_live     INTEGER DEFAULT 0,
                    my_won      INTEGER,
                    scraped_at  TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_key
                ON matches(my_pid, match_key)
            """)
            conn.execute("""
                CREATE TABLE match_opponents (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id    INTEGER NOT NULL REFERENCES matches(id),
                    profile_id  INTEGER,
                    name        TEXT NOT NULL,
                    team_id     INTEGER,
                    civ_name    TEXT,
                    rating      INTEGER,
                    won         INTEGER
                )
            """)
        # Migrate existing tables if columns are missing
        for _col, _def in [
            ("map_name", "TEXT"), ("my_won", "INTEGER"),
        ]:
            try:
                conn.execute(f"ALTER TABLE matches ADD COLUMN {_col} {_def}")
            except Exception:
                pass
        for _col, _def in [
            ("team_id", "INTEGER"), ("civ_name", "TEXT"),
            ("rating", "INTEGER"), ("won", "INTEGER"),
        ]:
            try:
                conn.execute(f"ALTER TABLE match_opponents ADD COLUMN {_col} {_def}")
            except Exception:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opponent_notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id  INTEGER NOT NULL,
                note_text   TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)
        _prune_noteless_opponents(conn)


def _prune_noteless_opponents(conn: sqlite3.Connection):
    """Keep only players that have at least one note."""
    conn.execute(
        """DELETE FROM opponent_name_history
           WHERE profile_id NOT IN (SELECT profile_id FROM opponent_notes)"""
    )
    conn.execute(
        """DELETE FROM opponents
           WHERE profile_id NOT IN (SELECT profile_id FROM opponent_notes)"""
    )


@contextmanager
def _connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── App config ────────────────────────────────────────────────────────────────

def get_my_profile_id() -> int | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_config WHERE key = 'my_profile_id'"
        ).fetchone()
        return int(row["value"]) if row else None


def set_my_profile_id(pid: int):
    with _connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES ('my_profile_id', ?)",
            (str(pid),),
        )


# ── Match / opponent persistence ──────────────────────────────────────────────

def save_matches(my_pid: int, matches: list[dict]) -> tuple[int, int]:
    """
    Persist scraped matches and their opponents.
    Returns (new_matches_saved, new_opponents_discovered).
    Each match dict: {match_key, map_name, started_at, is_live, my_won, opponents}
    opponents items: {pid, name, team, civ, rating}
    """
    now = _now()
    new_matches = 0
    new_opponents = 0

    with _connection() as conn:
        for m in matches:
            match_key = m.get("match_key", "")
            if not match_key:
                continue

            try:
                cur = conn.execute(
                    """INSERT INTO matches
                       (my_pid, match_key, map_name, started_at, is_live, my_won, scraped_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        my_pid, match_key, m.get("map_name"),
                        m.get("started_at"),
                        1 if m.get("is_live") else 0,
                        1 if m.get("my_won") is True else (0 if m.get("my_won") is False else None),
                        now,
                    ),
                )
                match_id = cur.lastrowid
                is_new_match = True
                new_matches += 1
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id FROM matches WHERE my_pid = ? AND match_key = ?",
                    (my_pid, match_key),
                ).fetchone()
                match_id = row["id"] if row else None
                is_new_match = False
                if match_id:
                    # Refresh state so finished matches stop showing as live
                    conn.execute(
                        """UPDATE matches
                           SET is_live = ?, my_won = ?, map_name = COALESCE(?, map_name),
                               started_at = COALESCE(?, started_at), scraped_at = ?
                           WHERE id = ?""",
                        (
                            1 if m.get("is_live") else 0,
                            1 if m.get("my_won") is True else (0 if m.get("my_won") is False else None),
                            m.get("map_name"),
                            m.get("started_at"),
                            now,
                            match_id,
                        ),
                    )

            for opp in m.get("opponents", []):
                pid = opp.get("pid")
                name = (opp.get("name") or "").strip()
                if not name:
                    continue

                if match_id and is_new_match:
                    conn.execute(
                        """INSERT INTO match_opponents
                           (match_id, profile_id, name, team_id, civ_name, rating, won)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            match_id, pid, name,
                            opp.get("team"), opp.get("civ"), opp.get("rating"),
                            None,  # won stored at match level via my_won
                        ),
                    )

                if not pid:
                    continue

                # Only players with at least one note are kept in `opponents`
                existing = conn.execute(
                    "SELECT name FROM opponents WHERE profile_id = ?", (pid,)
                ).fetchone()

                if existing is None:
                    continue

                conn.execute(
                    "UPDATE opponents SET last_seen = ?, name = ? WHERE profile_id = ?",
                    (now, name, pid),
                )
                if existing["name"] != name:
                    conn.execute(
                        "INSERT INTO opponent_name_history (profile_id, name, recorded_at) VALUES (?,?,?)",
                        (pid, name, now),
                    )

    return new_matches, new_opponents


def get_match_history(my_pid: int, limit: int = 30) -> list[dict]:
    """Return recent matches with players grouped by team."""
    with _connection() as conn:
        matches = conn.execute(
            """SELECT id, match_key, map_name, started_at, is_live, my_won, scraped_at
               FROM matches WHERE my_pid = ?
               ORDER BY is_live DESC, started_at DESC
               LIMIT ?""",
            (my_pid, limit),
        ).fetchall()

        result = []
        for m in matches:
            players = conn.execute(
                """SELECT profile_id, name, team_id, civ_name, rating
                   FROM match_opponents WHERE match_id = ?
                   ORDER BY team_id, name""",
                (m["id"],),
            ).fetchall()

            teams: dict[int, list[dict]] = {}
            for p in players:
                tid = p["team_id"] or 0
                teams.setdefault(tid, []).append(dict(p))

            result.append({**dict(m), "teams": teams})
        return result


def ensure_opponent(profile_id: int, name: str):
    """Insert opponent if not already known (used when adding notes from match view)."""
    now = _now()
    with _connection() as conn:
        existing = conn.execute(
            "SELECT profile_id FROM opponents WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO opponents (profile_id, name, first_seen, last_seen) VALUES (?,?,?,?)",
                (profile_id, name, now, now),
            )
            conn.execute(
                "INSERT INTO opponent_name_history (profile_id, name, recorded_at) VALUES (?,?,?)",
                (profile_id, name, now),
            )


def get_opponents(my_pid: int, search: str = "") -> list[dict]:
    """Return all opponents sorted by times_met desc, with note_count."""
    params: list = [my_pid]
    search_clause = ""

    if search:
        search_clause = "AND (o.name LIKE ? OR CAST(o.profile_id AS TEXT) LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]

    with _connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                o.profile_id,
                o.name,
                o.first_seen,
                o.last_seen,
                (SELECT COUNT(DISTINCT mo.match_id)
                 FROM match_opponents mo
                 JOIN matches mx ON mx.id = mo.match_id
                 WHERE mo.profile_id = o.profile_id AND mx.my_pid = ?) AS times_met,
                (SELECT COUNT(*) FROM opponent_notes n
                 WHERE n.profile_id = o.profile_id) AS note_count
            FROM opponents o
            WHERE 1=1 {search_clause}
            ORDER BY times_met DESC, o.name COLLATE NOCASE
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_name_history(profile_id: int) -> list[dict]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT name, recorded_at FROM opponent_name_history"
            " WHERE profile_id = ? ORDER BY recorded_at ASC",
            (profile_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Notes ─────────────────────────────────────────────────────────────────────

def add_note(profile_id: int, note_text: str):
    with _connection() as conn:
        conn.execute(
            "INSERT INTO opponent_notes (profile_id, note_text, created_at) VALUES (?, ?, ?)",
            (profile_id, note_text.strip(), _now()),
        )


def get_notes(profile_id: int) -> list[dict]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, note_text, created_at FROM opponent_notes"
            " WHERE profile_id = ? ORDER BY created_at ASC",
            (profile_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_note(note_id: int):
    with _connection() as conn:
        conn.execute("DELETE FROM opponent_notes WHERE id = ?", (note_id,))
        _prune_noteless_opponents(conn)
