from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
AUDIO_DIR = DATA_DIR / "audio"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "qimo_agent.sqlite3"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def init_storage() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, AUDIO_DIR, REPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id TEXT PRIMARY KEY,
                course TEXT NOT NULL,
                kind TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                status TEXT NOT NULL,
                transcript TEXT,
                extracted_text TEXT,
                audio_path TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                course TEXT NOT NULL,
                payload TEXT NOT NULL,
                report_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_material(material: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_iso()
    material = {
        **material,
        "created_at": material.get("created_at", timestamp),
        "updated_at": material.get("updated_at", timestamp),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO materials (
                id, course, kind, original_name, stored_path, status,
                transcript, extracted_text, audio_path, notes, created_at, updated_at
            )
            VALUES (
                :id, :course, :kind, :original_name, :stored_path, :status,
                :transcript, :extracted_text, :audio_path, :notes, :created_at, :updated_at
            )
            """,
            material,
        )
    return get_material(material["id"]) or material


def update_material(material_id: str, **updates: Any) -> dict[str, Any] | None:
    if not updates:
        return get_material(material_id)

    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    params = {**updates, "id": material_id}
    with connect() as conn:
        conn.execute(f"UPDATE materials SET {assignments} WHERE id = :id", params)
    return get_material(material_id)


def get_material(material_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    return row_to_dict(row)


def list_materials(course: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM materials"
    params: tuple[Any, ...] = ()
    if course:
        sql += " WHERE course = ?"
        params = (course,)
    sql += " ORDER BY created_at DESC"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def delete_material(material_id: str) -> bool:
    material = get_material(material_id)
    if not material:
        return False

    with connect() as conn:
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))

    for key in ("stored_path", "audio_path"):
        value = material.get(key)
        if value:
            try:
                path = Path(value)
                if path.exists() and DATA_DIR in path.resolve().parents:
                    path.unlink()
            except OSError:
                pass
    return True


def save_analysis(analysis_id: str, title: str, course: str, payload: dict[str, Any], report_path: Path) -> dict[str, Any]:
    created_at = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO analyses (id, title, course, payload, report_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (analysis_id, title, course, json.dumps(payload, ensure_ascii=False), str(report_path), created_at),
        )
    return get_analysis(analysis_id) or {
        "id": analysis_id,
        "title": title,
        "course": course,
        "payload": payload,
        "report_path": str(report_path),
        "created_at": created_at,
    }


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    result = row_to_dict(row)
    if result and isinstance(result.get("payload"), str):
        result["payload"] = json.loads(result["payload"])
    return result


def latest_analysis(course: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT * FROM analyses"
    params: tuple[Any, ...] = ()
    if course:
        sql += " WHERE course = ?"
        params = (course,)
    sql += " ORDER BY created_at DESC LIMIT 1"
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    result = row_to_dict(row)
    if result and isinstance(result.get("payload"), str):
        result["payload"] = json.loads(result["payload"])
    return result


def list_analyses(course: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT id, title, course, report_path, created_at FROM analyses"
    params: tuple[Any, ...] = ()
    if course:
        sql += " WHERE course = ?"
        params = (course,)
    sql += " ORDER BY created_at DESC"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
