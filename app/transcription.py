from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple

from .extractors import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS, VIDEO_EXTENSIONS


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_audio(source: Path, output_dir: Path) -> Tuple[Path | None, str]:
    if source.suffix.lower() not in MEDIA_EXTENSIONS:
        return None, ""
    if not has_ffmpeg():
        return None, "未找到 ffmpeg，无法从媒体文件提取音频。"

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{source.stem}.wav"

    if source.suffix.lower() in AUDIO_EXTENSIONS and source.suffix.lower() == ".wav":
        return source, "音频文件已可用于转写。"

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return None, f"ffmpeg 提取音频失败：{completed.stderr[-600:]}"
    return target, "已提取 16kHz 单声道音频。"


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcribe_audio(audio_path: Path) -> Tuple[str, str]:
    if os.getenv("ENABLE_WHISPER", "").lower() not in {"1", "true", "yes"}:
        return "", "已保留音频。设置 ENABLE_WHISPER=1 并安装 faster-whisper 后可自动转写。"

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return "", "ENABLE_WHISPER 已启用，但未安装 faster-whisper。"

    model_size = os.getenv("WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "auto")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "default")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(str(audio_path), language="zh", vad_filter=True)
    lines = [f"# language={info.language} probability={info.language_probability:.2f}"]
    for segment in segments:
        lines.append(f"[{format_timestamp(segment.start)}] {segment.text.strip()}")
    return "\n".join(lines), f"Whisper 转写完成，模型：{model_size}。"


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True
