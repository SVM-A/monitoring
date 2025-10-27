# app/db/camera_registry.py
# Lightweight registry/DAO for camera capabilities, settings, and runtime applied state.
# Uses sqlite3 directly, reads DB_PATH from constants.py.
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.constants import DB_PATH_CAMERAS


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS camera_capabilities (
        camera_id TEXT PRIMARY KEY,
        caps_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS camera_settings (
        camera_id TEXT PRIMARY KEY,
        settings_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS camera_runtime (
        camera_id TEXT PRIMARY KEY,
        applied_json TEXT NOT NULL,
        applied_at TEXT NOT NULL
    );
    """
]

def _connect() -> sqlite3.Connection:
    db_path = Path(DB_PATH_CAMERAS)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    for stmt in SCHEMA:
        conn.execute(stmt)
    conn.commit()
    return conn

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

@dataclass
class CameraCapabilities:
    data: Dict[str, Any]

    @classmethod
    def load(cls, camera_id: str) -> Optional['CameraCapabilities']:
        with _connect() as c:
            cur = c.execute("SELECT caps_json FROM camera_capabilities WHERE camera_id=?", (camera_id,))
            row = cur.fetchone()
            if not row:
                return None
            return cls(json.loads(row[0]))

    @classmethod
    def save(cls, camera_id: str, caps: Dict[str, Any]) -> None:
        payload = json.dumps(caps, ensure_ascii=False)
        with _connect() as c:
            c.execute(
                """
                INSERT INTO camera_capabilities(camera_id, caps_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET caps_json=excluded.caps_json, updated_at=excluded.updated_at
                """,
                (camera_id, payload, _now_iso())
            )
            c.commit()

@dataclass
class CameraSettings:
    data: Dict[str, Any]

    @classmethod
    def load(cls, camera_id: str) -> Optional['CameraSettings']:
        with _connect() as c:
            cur = c.execute("SELECT settings_json FROM camera_settings WHERE camera_id=?", (camera_id,))
            row = cur.fetchone()
            if not row:
                return None
            return cls(json.loads(row[0]))

    @classmethod
    def save(cls, camera_id: str, settings: Dict[str, Any]) -> None:
        payload = json.dumps(settings, ensure_ascii=False)
        with _connect() as c:
            c.execute(
                """
                INSERT INTO camera_settings(camera_id, settings_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at
                """,
                (camera_id, payload, _now_iso())
            )
            c.commit()

@dataclass
class CameraRuntime:
    data: Dict[str, Any]

    @classmethod
    def load(cls, camera_id: str) -> Optional['CameraRuntime']:
        with _connect() as c:
            cur = c.execute("SELECT applied_json FROM camera_runtime WHERE camera_id=?", (camera_id,))
            row = cur.fetchone()
            if not row:
                return None
            return cls(json.loads(row[0]))

    @classmethod
    def save(cls, camera_id: str, applied: Dict[str, Any]) -> None:
        payload = json.dumps(applied, ensure_ascii=False)
        with _connect() as c:
            c.execute(
                """
                INSERT INTO camera_runtime(camera_id, applied_json, applied_at)
                VALUES(?, ?, ?)
                ON CONFLICT(camera_id) DO UPDATE SET applied_json=excluded.applied_json, applied_at=excluded.applied_at
                """,
                (camera_id, payload, _now_iso())
            )
            c.commit()
