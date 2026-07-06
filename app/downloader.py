from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from .extractors import MEDIA_EXTENSIONS, safe_filename
from .transcription import has_ffmpeg


class RemoteImportError(Exception):
    """Raised when an authorized remote media import cannot be completed."""


HLS_EXTENSIONS = {".m3u8"}
PARTIAL_MEDIA_EXTENSIONS = {".m4s", ".ts"}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)
MAX_IMPORT_BYTES = int(os.getenv("MAX_IMPORT_BYTES", str(4 * 1024 * 1024 * 1024)))


def plan_import_path(output_dir: Path, material_id: str, title: str, url: str) -> Path:
    parsed = urllib.parse.urlparse(url)
    source_suffix = Path(parsed.path).suffix.lower()
    suffix = ".mp4" if source_suffix in HLS_EXTENSIONS | PARTIAL_MEDIA_EXTENSIONS else source_suffix
    if suffix not in MEDIA_EXTENSIONS:
        suffix = ".mp4"

    base = safe_filename(title or Path(parsed.path).stem or "jlu-video")
    if Path(base).suffix.lower():
        base = Path(base).stem
    return output_dir / f"{material_id}_{base}{suffix}"


def validate_remote_media_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise RemoteImportError("只支持 http/https 视频地址。")
    if not parsed.hostname:
        raise RemoteImportError("视频地址缺少主机名。")
    if parsed.username or parsed.password:
        raise RemoteImportError("视频地址不能包含用户名或密码。")

    allow_private = os.getenv("ALLOW_PRIVATE_IMPORT_URLS", "").lower() in {"1", "true", "yes"}
    if not allow_private:
        for ip in resolve_ips(parsed.hostname, parsed.port):
            if is_private_ip(ip):
                raise RemoteImportError("为避免本地网络探测，不能导入内网或本机地址。")
    return parsed


def resolve_ips(hostname: str, port: int | None) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RemoteImportError(f"无法解析视频地址主机：{hostname}") from exc
    seen: set[str] = set()
    for info in infos:
        ip_text = info[4][0]
        if ip_text in seen:
            continue
        seen.add(ip_text)
        try:
            yield ipaddress.ip_address(ip_text)
        except ValueError:
            continue


def is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def download_remote_media(
    url: str,
    target_path: Path,
    page_url: str = "",
    extra_headers: dict[str, str] | None = None,
) -> list[str]:
    parsed = validate_remote_media_url(url)
    suffix = Path(parsed.path).suffix.lower()
    notes = [f"来源页面：{page_url}" if page_url else "来源：手动视频地址"]

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if suffix in HLS_EXTENSIONS:
        notes.append(download_hls(url, target_path, page_url, extra_headers))
    elif suffix in PARTIAL_MEDIA_EXTENSIONS:
        raise RemoteImportError("检测到分片地址，请在视频页导入完整 mp4 或 m3u8 播放列表。")
    else:
        notes.append(download_file(url, target_path, page_url, extra_headers))

    reject_html_download(target_path)
    notes.append("已导入本地资料库。")
    return notes


def download_file(
    url: str,
    target_path: Path,
    page_url: str = "",
    extra_headers: dict[str, str] | None = None,
) -> str:
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"}
    if page_url:
        headers["Referer"] = page_url
        origin = origin_from_url(page_url)
        if origin:
            headers["Origin"] = origin
    if extra_headers:
        headers.update({key: value for key, value in extra_headers.items() if value})

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                raise RemoteImportError("下载结果是登录页/网页，不是视频文件。请在视频页重新导入可播放资源。")
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_IMPORT_BYTES:
                raise RemoteImportError("视频文件超过当前导入大小限制。")

            written = 0
            with target_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_IMPORT_BYTES:
                        raise RemoteImportError("视频文件超过当前导入大小限制。")
                    output.write(chunk)
    except urllib.error.HTTPError as exc:
        raise RemoteImportError(f"视频下载失败：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RemoteImportError(f"视频下载失败：{exc.reason}") from exc

    return "已下载远程视频文件。"


def download_hls(
    url: str,
    target_path: Path,
    page_url: str = "",
    extra_headers: dict[str, str] | None = None,
) -> str:
    if not has_ffmpeg():
        raise RemoteImportError("检测到 m3u8，但本机没有 ffmpeg，无法合并 HLS 视频。")

    command = [
        "ffmpeg",
        "-y",
        "-user_agent",
        DEFAULT_USER_AGENT,
    ]
    header_lines = []
    if page_url:
        header_lines.append(f"Referer: {page_url}")
        origin = origin_from_url(page_url)
        if origin:
            header_lines.append(f"Origin: {origin}")
    for key, value in (extra_headers or {}).items():
        if value and key.lower() not in {"referer", "origin"}:
            header_lines.append(f"{key}: {value}")
    if header_lines:
        command.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
    command.extend(["-i", url, "-c", "copy", str(target_path)])

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr[-800:]
        raise RemoteImportError(f"HLS 下载或合并失败：{stderr}")
    return "已通过 ffmpeg 合并 m3u8 视频。"


def origin_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def reject_html_download(path: Path) -> None:
    with path.open("rb") as source:
        sample = source.read(512).lstrip().lower()
    if sample.startswith(b"<!doctype html") or sample.startswith(b"<html") or b"<title>" in sample[:256]:
        try:
            path.unlink()
        except OSError:
            pass
        raise RemoteImportError("下载到的是网页内容，不是视频文件。")
