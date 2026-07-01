import json
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent / "poker.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            winner TEXT,
            result TEXT,
            user_stack INTEGER,
            bot_stack INTEGER,
            pot INTEGER,
            user_cards TEXT,
            bot_cards TEXT,
            board TEXT,
            notes TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hand_id INTEGER NOT NULL,
            street TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            amount INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(hand_id) REFERENCES hands(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def set_meta(key: str, value: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_meta(key: str) -> Optional[str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else None


def save_state(state: dict) -> None:
    set_meta("state", json.dumps(state))


def load_state() -> Optional[dict]:
    raw = get_meta("state")
    if not raw:
        return None
    return json.loads(raw)


def clear_state() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM meta WHERE key = 'state'")
    conn.commit()
    conn.close()


def create_hand() -> int:
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO hands(started_at) VALUES(?)",
        (now,),
    )
    hand_id = cur.lastrowid
    conn.commit()
    conn.close()
    return hand_id


def finish_hand(hand_id: int, data: dict, notes: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()

    user_cards = []
    bot_cards = []
    if data.get("players"):
        for p in data["players"]:
            if p.get("is_user"):
                user_cards = p.get("cards", [])
            elif not bot_cards:
                bot_cards = p.get("cards", [])

    user_stack = 0
    bot_stack = 0
    if data.get("players"):
        for p in data["players"]:
            if p.get("is_user"):
                user_stack = p.get("stack", 0)
            else:
                bot_stack += p.get("stack", 0)

    cur.execute(
        """
        UPDATE hands
        SET ended_at = ?, winner = ?, result = ?, user_stack = ?, bot_stack = ?, pot = ?,
            user_cards = ?, bot_cards = ?, board = ?, notes = ?
        WHERE id = ?
        """,
        (
            now,
            data.get("winner"),
            data.get("result"),
            user_stack,
            bot_stack,
            data.get("pot"),
            json.dumps(user_cards),
            json.dumps(bot_cards),
            json.dumps(data.get("board")),
            notes,
            hand_id,
        ),
    )
    conn.commit()
    conn.close()



def add_action(hand_id: int, street: str, actor: str, action: str, amount: int | None = None) -> None:
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO actions(hand_id, street, actor, action, amount, created_at) VALUES(?, ?, ?, ?, ?, ?)",
        (hand_id, street, actor, action, amount, now),
    )
    conn.commit()
    conn.close()


def get_recent_hands(limit: int = 20) -> List[Dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, started_at, ended_at, winner, result, user_stack, bot_stack, pot, notes FROM hands ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_actions(hand_id: int) -> List[Dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, street, actor, action, amount, created_at FROM actions WHERE hand_id = ? ORDER BY id ASC",
        (hand_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_last_finished_hand() -> Optional[Dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, started_at, ended_at, winner, result, user_stack, bot_stack, pot, user_cards, bot_cards, board, notes "
        "FROM hands WHERE ended_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    for key in ("user_cards", "bot_cards", "board"):
        try:
            data[key] = json.loads(data.get(key) or "[]")
        except Exception:
            data[key] = []
    return data

