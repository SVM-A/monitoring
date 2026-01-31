# app/db/camera_registry.py
# Lightweight registry/DAO for camera capabilities, settings, and runtime applied state.
# Uses sqlite3 directly, reads DB_PATH from config_cams.py.
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config_cams import DB_PATH_CAMERAS
from app.core.config_cams import DB_PATH_DETECTION


def init_db(path=DB_PATH_DETECTION):
    conn = sqlite3.connect(path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT,
        timestamp TEXT,
        plate TEXT,
        bbox TEXT,
        extra TEXT
    )
    """)
    conn.commit()
    return conn


def save_detection(conn, camera_id, plate, bbox=None, extra=None):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO detections (camera_id, timestamp, plate, bbox, extra) VALUES (?, ?, ?, ?, ?)",
        (camera_id, datetime.utcnow().isoformat(), plate, json.dumps(bbox), json.dumps(extra))
    )
    conn.commit()


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


# -----------------------------------------------------------------------------
# PlateGate settings (persistent)
# -----------------------------------------------------------------------------

# app/db/camera_registry.py

PLATEGATE_SETTINGS_ID = "__plategate__"

def load_plategate_settings() -> dict:
    """
    Формат:
      {
        "control_source_id": "...",
        "recognition_enabled": bool,
        "detect_mode": "perf" | "accuracy",
        "accuracy_interval_sec": float
      }

    Миграция:
      - если было старое "control_camera_id" -> считаем что это base без ROI
    """
    obj = CameraSettings.load(PLATEGATE_SETTINGS_ID)
    data = (obj.data if obj else {}) or {}

    control_source_id = str(data.get("control_source_id") or "")
    if not control_source_id:
        control_source_id = str(data.get("control_camera_id") or "")

    detect_mode = str(data.get("detect_mode") or "perf").lower()
    if detect_mode not in ("perf", "accuracy"):
        detect_mode = "perf"

    try:
        accuracy_interval_sec = float(data.get("accuracy_interval_sec") or 1.0)
    except Exception:
        accuracy_interval_sec = 1.0

    # защита
    if accuracy_interval_sec < 0.2:
        accuracy_interval_sec = 0.2
    if accuracy_interval_sec > 10.0:
        accuracy_interval_sec = 10.0

    return {
        "control_source_id": control_source_id,
        "recognition_enabled": bool(data.get("recognition_enabled") or False),
        "detect_mode": detect_mode,
        "accuracy_interval_sec": accuracy_interval_sec,
    }


def save_plategate_settings(
    *,
    control_source_id: str,
    recognition_enabled: bool,
    detect_mode: str = "perf",
    accuracy_interval_sec: float = 1.0,
) -> None:
    detect_mode = str(detect_mode or "perf").lower()
    if detect_mode not in ("perf", "accuracy"):
        detect_mode = "perf"

    try:
        accuracy_interval_sec = float(accuracy_interval_sec)
    except Exception:
        accuracy_interval_sec = 1.0

    if accuracy_interval_sec < 0.2:
        accuracy_interval_sec = 0.2
    if accuracy_interval_sec > 10.0:
        accuracy_interval_sec = 10.0

    CameraSettings.save(
        PLATEGATE_SETTINGS_ID,
        {
            "control_source_id": str(control_source_id or ""),
            "recognition_enabled": bool(recognition_enabled),
            "detect_mode": detect_mode,
            "accuracy_interval_sec": accuracy_interval_sec,
        }
    )
