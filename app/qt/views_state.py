# app/qt/views_state.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import json
from pathlib import Path
from app.core.config import BASE_PATH

VIEWS_PATH = Path(BASE_PATH) / "views.json"

@dataclass
class ViewSpec:
    id: str
    name: str
    # Новая модель: список выбранных источников (камер/виджетов/половинок cam:A/cam:B)
    selected_ids: Optional[List[str]] = None

def _migrate_item(item: dict) -> ViewSpec:
    """
    Миграция со старого формата (selected_id: str | null) к новому (selected_ids: list[str]).
    """
    vid = item.get("id") or "view-1"
    name = item.get("name") or "Окно"
    if "selected_ids" in item and isinstance(item["selected_ids"], list):
        sel = [str(x) for x in item["selected_ids"] if x]
    else:
        # старый формат: одно поле selected_id
        sid = item.get("selected_id")
        sel = [sid] if isinstance(sid, str) and sid else []
    return ViewSpec(id=vid, name=name, selected_ids=sel)

def load_views() -> List[ViewSpec]:
    if not VIEWS_PATH.exists():
        # дефолт: одно окно без выбранных источников
        return [ViewSpec(id="view-1", name="Окно 1", selected_ids=[])]
    try:
        data = json.loads(VIEWS_PATH.read_text("utf-8"))
        out: List[ViewSpec] = []
        for item in (data or []):
            out.append(_migrate_item(item or {}))
        return out or [ViewSpec(id="view-1", name="Окно 1", selected_ids=[])]
    except Exception:
        return [ViewSpec(id="view-1", name="Окно 1", selected_ids=[])]

def save_views(items: List[ViewSpec]) -> None:
    VIEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        dict(id=v.id, name=v.name, selected_ids=list(v.selected_ids or []))
        for v in items
    ]
    VIEWS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def next_view_id(items: List[ViewSpec]) -> str:
    base = "view-"
    i = 1
    ids = {v.id for v in items}
    while f"{base}{i}" in ids:
        i += 1
    return f"{base}{i}"
