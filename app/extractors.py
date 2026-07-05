from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Tuple
from xml.etree import ElementTree


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".srt", ".vtt", ".csv", ".json"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "upload"
    return re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", name)[:160]


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def extract_docx(path: Path) -> str:
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as package:
        xml = package.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def extract_pdf(path: Path) -> Tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "缺少 pypdf，无法解析 PDF。请先安装 requirements.txt。"

    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"\n[第 {index} 页]\n{text.strip()}")
    if not pages:
        return "", "PDF 未提取到文本，可能是扫描版，需要 OCR。"
    return "\n".join(pages), ""


def extract_text_from_file(path: Path) -> Tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return read_text_file(path), ""
    if suffix == ".docx":
        try:
            return extract_docx(path), ""
        except Exception as exc:  # noqa: BLE001
            return "", f"DOCX 解析失败：{exc}"
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in MEDIA_EXTENSIONS:
        return "", "媒体文件已保存，可提取音频；需要转写后才能分析。"
    return "", "该文件类型暂不支持自动解析，可粘贴文字稿继续分析。"
