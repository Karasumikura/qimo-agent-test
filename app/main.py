from __future__ import annotations

import shutil
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import analyze_materials, build_markdown_report
from .downloader import RemoteImportError, download_remote_media, plan_import_path, validate_remote_media_url
from .extractors import MEDIA_EXTENSIONS, extract_text_from_file, safe_filename
from .jlu_connector import JluLearningConnector
from .llm import LlmConfig, LlmError, enrich_analysis_with_llm
from .storage import (
    AUDIO_DIR,
    REPORT_DIR,
    ROOT_DIR,
    UPLOAD_DIR,
    create_material,
    delete_material,
    get_analysis,
    get_material,
    init_storage,
    latest_analysis,
    list_analyses,
    list_materials,
    now_iso,
    save_analysis,
    update_material,
)
from .transcription import extract_audio, has_ffmpeg, transcribe_audio, whisper_available


STATIC_DIR = ROOT_DIR / "static"
DEFAULT_COURSE = "未命名课程"

app = FastAPI(title="Qimo Review Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class TextMaterialPayload(BaseModel):
    course: str = ""
    kind: str = "transcript"
    title: str = "pasted-text.txt"
    text: str


class TranscriptPayload(BaseModel):
    transcript: str


class AnalyzePayload(BaseModel):
    course: str = ""
    material_ids: list[str] = []
    llm: "LlmSettings | None" = None


class LlmSettings(BaseModel):
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2


class RemoteImportPayload(BaseModel):
    course: str = ""
    title: str = ""
    url: str = ""
    page_url: str = ""
    kind: str = "lecture_video"
    auto_analyze: bool = True
    detected_urls: list[str] = []
    transcript_text: str = ""
    transcript_title: str = ""
    llm: LlmSettings | None = None


@app.middleware("http")
async def add_private_network_cors_header(request: Request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.on_event("startup")
def startup() -> None:
    init_storage()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/system")
def system_status() -> dict[str, Any]:
    connector = JluLearningConnector()
    return {
        "ffmpeg": has_ffmpeg(),
        "whisper_installed": whisper_available(),
        "public_entrypoints": [resource.__dict__ for resource in connector.list_public_entrypoints()],
    }


@app.get("/api/materials")
def materials(course: str = "") -> list[dict[str, Any]]:
    return list_materials(course or None)


@app.post("/api/materials")
async def upload_material(
    course: str = Form(""),
    kind: str = Form("lecture_video"),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    init_storage()
    material_id = uuid.uuid4().hex
    original_name = safe_filename(file.filename or "upload")
    stored_path = UPLOAD_DIR / f"{material_id}_{original_name}"
    with stored_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)

    create_material(
        {
            "id": material_id,
            "course": course.strip() or DEFAULT_COURSE,
            "kind": kind,
            "original_name": original_name,
            "stored_path": str(stored_path),
            "status": "processing",
            "transcript": None,
            "extracted_text": None,
            "audio_path": None,
            "notes": "本地文件已上传，正在处理。",
        }
    )
    return process_stored_material(material_id, stored_path, kind)


@app.post("/api/materials/text")
def create_text_material(payload: TextMaterialPayload) -> dict[str, Any]:
    init_storage()
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    material_id = uuid.uuid4().hex
    title = safe_filename(payload.title or "pasted-text.txt")
    if "." not in title:
        title += ".txt"
    stored_path = UPLOAD_DIR / f"{material_id}_{title}"
    stored_path.write_text(payload.text, encoding="utf-8")

    is_exam = payload.kind == "past_exam"
    return create_material(
        {
            "id": material_id,
            "course": payload.course.strip() or DEFAULT_COURSE,
            "kind": payload.kind,
            "original_name": title,
            "stored_path": str(stored_path),
            "status": "ready",
            "transcript": None if is_exam else payload.text,
            "extracted_text": payload.text,
            "audio_path": None,
            "notes": "手动粘贴文本。",
        }
    )


@app.post("/api/imports/from-url")
def import_from_url(payload: RemoteImportPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return queue_remote_import(payload, background_tasks)


@app.post("/api/imports/from-page")
def import_from_page(payload: RemoteImportPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return queue_remote_import(payload, background_tasks)


@app.post("/api/imports/from-extension")
def import_from_extension(payload: RemoteImportPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return queue_remote_import(payload, background_tasks)


def queue_remote_import(payload: RemoteImportPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    init_storage()
    candidates = clean_url_candidates(payload)
    if not candidates and not payload.transcript_text.strip():
        raise HTTPException(status_code=400, detail="没有检测到可导入的视频地址或文字稿。")
    if candidates:
        try:
            validate_remote_media_url(candidates[0])
        except RemoteImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    material_id = uuid.uuid4().hex
    title = payload.title.strip() or "学在吉大视频"
    planned_path = plan_import_path(UPLOAD_DIR, material_id, title, candidates[0] if candidates else f"{title}.txt")
    material = create_material(
        {
            "id": material_id,
            "course": payload.course.strip() or DEFAULT_COURSE,
            "kind": payload.kind,
            "original_name": planned_path.name,
            "stored_path": str(planned_path),
            "status": "downloading",
            "transcript": None,
            "extracted_text": payload.transcript_text.strip() or None,
            "audio_path": None,
            "notes": "远程页面导入任务已创建。",
        }
    )
    background_tasks.add_task(run_remote_import, material_id, payload, planned_path)
    return {
        "material": material,
        "message": "下载任务已创建。完成后会自动进入转写和分析流程。",
    }


def run_remote_import(material_id: str, payload: RemoteImportPayload, target_path: Path) -> None:
    notes: list[str] = []
    candidates = clean_url_candidates(payload)
    errors: list[str] = []
    transcript_text = payload.transcript_text.strip()
    try:
        if transcript_text:
            save_transcript_sidecar(material_id, payload, transcript_text)
            notes.append(f"已导入页面文字稿 {len(transcript_text)} 字。")

        if not candidates:
            update_material(
                material_id,
                status="ready",
                transcript=transcript_text,
                extracted_text=transcript_text,
                notes="\n".join(notes + ["未检测到视频地址，仅导入文字稿。"]),
            )
            return

        for candidate in candidates:
            try:
                notes.extend(download_remote_media(candidate, target_path, payload.page_url))
                break
            except RemoteImportError as exc:
                errors.append(f"{candidate}: {exc}")
        else:
            if transcript_text:
                update_material(
                    material_id,
                    status="ready",
                    transcript=transcript_text,
                    extracted_text=transcript_text,
                    notes="\n".join(notes + ["视频下载失败，已保留页面文字稿。", *errors[-3:]]),
                )
                return
            raise RemoteImportError(errors[-1] if errors else "没有可下载的视频地址。")

        if errors:
            notes.append(f"已跳过 {len(errors)} 个不可下载候选地址。")
        update_material(
            material_id,
            original_name=target_path.name,
            stored_path=str(target_path),
            status="processing",
            transcript=transcript_text or None,
            extracted_text=transcript_text or None,
            notes="\n".join(notes + ["正在提取音频和转写。"]),
        )
        process_stored_material(material_id, target_path, payload.kind, notes)
        if payload.auto_analyze:
            with suppress(Exception):
                generate_analysis(payload.course.strip() or DEFAULT_COURSE, llm_settings=payload.llm)
    except RemoteImportError as exc:
        update_material(material_id, status="error", notes=f"导入失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        update_material(material_id, status="error", notes=f"导入失败：{exc}")


def clean_url_candidates(payload: RemoteImportPayload) -> list[str]:
    candidates = []
    for url in [payload.url, *payload.detected_urls]:
        value = (url or "").strip()
        if not value or value.startswith("blob:") or value.startswith("data:"):
            continue
        if value.startswith("//"):
            value = "https:" + value
        if value.startswith("http://") or value.startswith("https://"):
            candidates.append(value)
    return list(dict.fromkeys(candidates))[:80]


def save_transcript_sidecar(material_id: str, payload: RemoteImportPayload, text: str) -> Path:
    title = safe_filename(payload.transcript_title or payload.title or "page-transcript")
    if "." not in title:
        title += ".txt"
    sidecar = UPLOAD_DIR / f"{material_id}_{title}"
    sidecar.write_text(text, encoding="utf-8")
    return sidecar


def process_stored_material(
    material_id: str,
    stored_path: Path,
    kind: str,
    initial_notes: list[str] | None = None,
) -> dict[str, Any]:
    notes = list(initial_notes or [])
    try:
        extracted_text, note = extract_text_from_file(stored_path)
        if note:
            notes.append(note)
        transcript = extracted_text if kind == "transcript" else None
        audio_path: Path | None = None
        status = "ready" if extracted_text else "needs_text"

        if stored_path.suffix.lower() in MEDIA_EXTENSIONS or kind in {"lecture_video", "lecture_audio"}:
            audio_path, audio_note = extract_audio(stored_path, AUDIO_DIR)
            if audio_note:
                notes.append(audio_note)
            if audio_path:
                transcript_text, transcript_note = transcribe_audio(audio_path)
                if transcript_note:
                    notes.append(transcript_note)
                if transcript_text:
                    transcript = transcript_text
                    status = "ready"
                else:
                    status = "needs_transcript"

        if kind != "past_exam" and extracted_text and not transcript:
            transcript = extracted_text

        updated = update_material(
            material_id,
            status=status,
            transcript=transcript,
            extracted_text=extracted_text,
            audio_path=str(audio_path) if audio_path else None,
            notes="\n".join(notes),
        )
        if not updated:
            raise HTTPException(status_code=404, detail="material not found")
        return updated
    except Exception as exc:  # noqa: BLE001
        updated = update_material(material_id, status="error", notes="\n".join(notes + [f"处理失败：{exc}"]))
        if not updated:
            raise
        return updated


@app.put("/api/materials/{material_id}/transcript")
def set_transcript(material_id: str, payload: TranscriptPayload) -> dict[str, Any]:
    material = get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail="material not found")
    updated = update_material(material_id, transcript=payload.transcript, status="ready")
    if not updated:
        raise HTTPException(status_code=404, detail="material not found")
    return updated


@app.delete("/api/materials/{material_id}")
def remove_material(material_id: str) -> dict[str, bool]:
    return {"deleted": delete_material(material_id)}


@app.post("/api/analyze")
def analyze(payload: AnalyzePayload) -> dict[str, Any]:
    return generate_analysis(payload.course, payload.material_ids, payload.llm)


def generate_analysis(
    course_input: str = "",
    material_ids: list[str] | None = None,
    llm_settings: LlmSettings | None = None,
) -> dict[str, Any]:
    init_storage()
    if material_ids:
        selected = [get_material(material_id) for material_id in material_ids]
        materials = [item for item in selected if item]
    else:
        materials = list_materials(course_input or None)

    if not materials:
        raise HTTPException(status_code=400, detail="no materials to analyze")

    course = course_input.strip() or materials[0]["course"] or DEFAULT_COURSE
    analysis = analyze_materials(materials, course=course)
    if llm_settings and llm_settings.enabled:
        try:
            config = LlmConfig(
                enabled=llm_settings.enabled,
                base_url=llm_settings.base_url,
                api_key=llm_settings.api_key,
                model=llm_settings.model,
                temperature=llm_settings.temperature,
            )
            analysis = enrich_analysis_with_llm(analysis, materials, config)
        except LlmError as exc:
            analysis["llm"] = {
                "enabled": True,
                "status": "error",
                "model": llm_settings.model,
                "base_url": llm_settings.base_url,
                "error": str(exc),
            }
            analysis.setdefault("warnings", []).append(f"LLM 分析失败：{exc}")
    else:
        analysis.setdefault("llm", {"enabled": False, "status": "skipped"})
    report = build_markdown_report(analysis)
    analysis_id = uuid.uuid4().hex
    report_path = REPORT_DIR / f"{analysis_id}.md"
    report_path.write_text(report, encoding="utf-8")
    saved = save_analysis(
        analysis_id=analysis_id,
        title=f"{course} 期末重点报告 {now_iso()}",
        course=course,
        payload=analysis,
        report_path=report_path,
    )
    return {
        "analysis": analysis,
        "analysis_id": analysis_id,
        "report": report,
        "report_url": f"/api/reports/{analysis_id}.md",
        "created_at": saved["created_at"],
    }


@app.get("/api/analyses")
def analyses(course: str = "") -> list[dict[str, Any]]:
    return list_analyses(course or None)


@app.get("/api/analyses/latest")
def get_latest_analysis(course: str = "") -> dict[str, Any] | None:
    return latest_analysis(course or None)


@app.get("/api/reports/{analysis_id}.md")
def report(analysis_id: str) -> PlainTextResponse:
    analysis = get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="analysis not found")
    path = Path(analysis["report_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="report file not found")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
