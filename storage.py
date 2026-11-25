"""일정 데이터 저장소.

앱의 모든 데이터 읽기/쓰기는 이 모듈을 통해서만 이루어진다.
나중에 외부 저장소(Google Sheets, Supabase 등)로 바꿀 때는 이 파일만 교체하면 된다.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_FILE = DATA_DIR / "schedules.json"
KST = timezone(timedelta(hours=9))

# Streamlit은 모든 브라우저 탭을 한 프로세스의 스레드로 처리한다.
# 읽기-수정-쓰기 사이에 다른 탭의 저장이 끼어들어 변경이 사라지지 않도록 잠금으로 묶는다.
_lock = threading.RLock()

# 카테고리 이름 -> 배지 이모지 (표시 순서 유지)
CATEGORIES: dict[str, str] = {
    "업무": "💼",
    "여행": "✈️",
    "개인": "🏠",
    "공부": "📚",
    "운동": "🏃",
    "기타": "📌",
}
DEFAULT_CATEGORY = "기타"

# 카테고리 배지 배경색 (흰 글씨와 대비 4.5:1 이상, 라이트/다크 테마 공통)
CATEGORY_COLORS: dict[str, str] = {
    "업무": "#2563eb",
    "여행": "#15803d",
    "개인": "#c2410c",
    "공부": "#7c3aed",
    "운동": "#dc2626",
    "기타": "#4b5563",
}

# 사용자가 수정할 수 있는 필드 (id, created_at 등 시스템 필드는 제외)
EDITABLE_FIELDS = ("title", "date", "start_time", "end_time", "category", "memo")


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def normalize_category(name: object) -> str:
    """목록에 없는 카테고리(파일 직접 수정, 삭제된 사용자 카테고리 등)는 '기타'로 취급한다."""
    return name if name in CATEGORIES else DEFAULT_CATEGORY


def load_events() -> list[dict]:
    """저장된 일정 목록을 읽는다. 파일이 없거나 손상되었으면 빈 목록을 반환한다."""
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and "id" in e]


def save_events(events: list[dict]) -> None:
    """일정 목록 전체를 원자적으로 저장한다 (임시 파일에 쓴 뒤 교체)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, prefix=".schedules-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DATA_FILE)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def add_event(event: dict) -> dict:
    """새 일정을 추가하고, id/created_at/updated_at이 채워진 일정을 반환한다."""
    now = _now()
    new_event = {field: event.get(field, "") for field in EDITABLE_FIELDS}
    new_event["category"] = normalize_category(new_event["category"])
    new_event.update(id=str(uuid.uuid4()), created_at=now, updated_at=now)

    with _lock:
        events = load_events()
        events.append(new_event)
        save_events(events)
    return new_event


def update_event(event_id: str, changes: dict) -> dict | None:
    """일정을 수정한다. 대상이 없으면 None을 반환한다."""
    with _lock:
        events = load_events()
        for event in events:
            if event["id"] == event_id:
                event.update({k: v for k, v in changes.items() if k in EDITABLE_FIELDS})
                event["updated_at"] = _now()
                save_events(events)
                return event
    return None


def delete_event(event_id: str) -> bool:
    """일정을 삭제한다. 삭제했으면 True, 대상이 없으면 False."""
    with _lock:
        events = load_events()
        remaining = [e for e in events if e["id"] != event_id]
        if len(remaining) == len(events):
            return False
        save_events(remaining)
    return True
