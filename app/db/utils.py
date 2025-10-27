# app/db/utils.py

import json
import sqlite3
from datetime import datetime

from app.core.constants import DB_PATH_DETECTION


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