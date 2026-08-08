from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import imageio_ffmpeg
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DOWNLOAD_DIR = DATA_DIR / "jobs"
DATABASE = DATA_DIR / "videopipe.db"
NM3U8_EXE = ROOT / "vendor" / "N_m3u8DL-RE" / "N_m3u8DL-RE.exe"
ARIA2_EXE = ROOT / "vendor" / "aria2" / "aria2-1.37.0-win-64bit-build1" / "aria2c.exe"
QUALITY_FORMATS = {
    "best": "bestvideo*+bestaudio/best",
    "720": "bestvideo*[height<=720]+bestaudio/best[height<=720]/best",
    "480": "bestvideo*[height<=480]+bestaudio/best[height<=480]/best",
}
JOBS: dict[str, dict] = {}
ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
DOWNLOAD_SEMAPHORE: asyncio.Semaphore | None = None
URL_RE = re.compile(r"https?://[^\s<>\"'，。；：！？、（）【】《》「」『』]+", re.IGNORECASE)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
WECHAT_RESOLVER = "https://sph.litao.workers.dev/api/fetch_video_profile"

class LinkRequest(BaseModel):
    text: str


class DownloadRequest(LinkRequest):
    quality: str
    title: str | None = None
    thumbnail: str | None = None
    platform: str | None = None
    resolved_url: str | None = None
    headers: dict[str, str] | None = None


def extract_url(text: str) -> str:
    match = URL_RE.search(text.strip())
    if not match:
        raise ValueError("没有找到有效的视频链接")
    return match.group(0).rstrip(".,;:!?，。；：！？)]}》」』")


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持网页链接或包含网页链接的分享文本")
    if parsed.username or parsed.password:
        raise ValueError("链接不能包含账号或密码")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as exc:
        raise ValueError("无法解析链接域名") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("不能访问本机或内网地址")
    return url


def quality_allowed(quality: str) -> bool:
    # Future membership/ad unlock belongs here; the test version keeps every quality open.
    return quality in QUALITY_FORMATS


def concurrent_job_limit() -> int:
    # Future membership limit belongs here; the test version allows three parallel jobs.
    return 3


def active_job_count() -> int:
    return sum(job["status"] not in {"completed", "failed", "cancelled", "delivered"} for job in JOBS.values())


def clean_error(error: Exception) -> str:
    return ANSI_RE.sub("", str(error)).strip()[:500]


def stop_process_tree(job_id: str) -> None:
    process = ACTIVE_PROCESSES.get(job_id)
    if not process or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()


def run_download_process(job: dict, command: list[str], error_message: str) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    ACTIVE_PROCESSES[job["id"]] = process
    try:
        assert process.stdout is not None
        line = ""
        while True:
            character = process.stdout.read(1)
            if not character:
                if not line:
                    break
            elif character not in "\r\n":
                line += character
                continue
            if job.get("cancel_requested"):
                stop_process_tree(job["id"])
                raise RuntimeError("任务已取消")
            percentages = re.findall(r"(\d+(?:\.\d+)?)%", ANSI_RE.sub("", line))
            if percentages:
                percent = min(99, max(float(value) for value in percentages))
                job.update(status="downloading", progress=percent)
                if int(percent) > job.get("_saved_percent", -1):
                    job["_saved_percent"] = int(percent)
                    save_job(job)
            line = ""
            if not character:
                break
        return_code = process.wait()
    finally:
        if ACTIVE_PROCESSES.get(job["id"]) is process:
            ACTIVE_PROCESSES.pop(job["id"], None)
    if job.get("cancel_requested"):
        raise RuntimeError("任务已取消")
    if return_code != 0:
        raise RuntimeError(error_message)


def init_storage() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as db:
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")


def save_job(job: dict) -> None:
    stored = {key: value for key, value in job.items() if not key.startswith("_")}
    with sqlite3.connect(DATABASE) as db:
        db.execute(
            "INSERT INTO jobs(id, data) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (job["id"], json.dumps(stored, ensure_ascii=False)),
        )


def update_job(job: dict, **values) -> None:
    job.update(values)
    save_job(job)


def public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key not in {"path", "directory", "url"} and not key.startswith("_")}


def load_jobs() -> None:
    with sqlite3.connect(DATABASE) as db:
        rows = db.execute("SELECT data FROM jobs").fetchall()
    for (payload,) in rows:
        job = json.loads(payload)
        if job["status"] in {"downloading", "queued"}:
            job["status"] = "queued"
        JOBS[job["id"]] = job


def ydl_base_options() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "cachedir": False,
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
    }


def is_manifest_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(extension in path for extension in (".m3u8", ".mpd", ".ism"))


def is_hls_url(url: str) -> bool:
    return ".m3u8" in urlparse(url).path.lower()


def is_wechat_share_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == "weixin.qq.com" and parsed.path.startswith("/sph/")


def resolve_wechat_sync(url: str) -> dict:
    request = Request(
        WECHAT_RESOLVER,
        data=json.dumps({"url": url}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "VideoPipe/1.0"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("微信视频号公开解析服务暂时不可用") from exc
    data = payload.get("data") or {}
    if "feedInfo" not in data:
        data = data.get("data") or {}
    feed = data.get("feedInfo") or {}
    video_url = feed.get("videoUrl") or (feed.get("h264VideoInfo") or {}).get("videoUrl")
    if not video_url:
        raise RuntimeError("这个微信视频号分享链接没有返回可下载的视频")
    validate_public_url(video_url)
    title = (feed.get("description") or "微信视频号").strip().splitlines()[0][:200]
    headers = {"Referer": "https://channels.weixin.qq.com/"}
    return {
        "url": video_url,
        "source_url": url,
        "resolved_url": video_url,
        "headers": headers,
        "title": title,
        "platform": "微信视频号",
        "duration": None,
        "thumbnail": feed.get("coverUrl"),
        "max_height": None,
        "qualities": [
            {"id": "best", "label": "最佳画质", "detail": "最高可用"},
            {"id": "720", "label": "720P", "detail": "高清"},
            {"id": "480", "label": "480P", "detail": "流畅"},
        ],
    }


def analyze_sync(url: str, headers: dict[str, str] | None = None) -> dict:
    with yt_dlp.YoutubeDL({**ydl_base_options(), "skip_download": True, "http_headers": headers or {}}) as ydl:
        info = ydl.extract_info(url, download=False)
    heights = sorted({f.get("height") for f in info.get("formats", []) if f.get("height")})
    return {
        "url": url,
        "title": info.get("title") or "未命名视频",
        "platform": info.get("extractor_key") or info.get("extractor") or "媒体链接",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "max_height": heights[-1] if heights else None,
        "qualities": [
            {"id": "best", "label": "最佳画质", "detail": f"最高 {heights[-1]}P" if heights else "最高可用"},
            {"id": "720", "label": "720P", "detail": "高清", "available": not heights or any(h <= 720 for h in heights)},
            {"id": "480", "label": "480P", "detail": "流畅", "available": not heights or any(h <= 480 for h in heights)},
        ],
    }


def discover_media_sync(url: str) -> tuple[str, dict[str, str], dict]:
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        edge = Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        raise RuntimeError("没有找到可用于媒体发现的 Edge 浏览器")

    candidates: list[tuple[int, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(edge), headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()

            def capture(response) -> None:
                media_url = response.url
                content_type = (response.header_value("content-type") or "").lower()
                path = urlparse(media_url).path.lower()
                if ".m3u8" in path or "mpegurl" in content_type:
                    candidates.append((3, media_url))
                elif ".mpd" in path or "dash+xml" in content_type:
                    candidates.append((3, media_url))
                elif path.endswith((".mp4", ".webm", ".mov")) or content_type.startswith("video/"):
                    candidates.append((2, media_url))

            page.on("response", capture)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(8_000)
            except PlaywrightTimeoutError:
                pass
            video = page.locator("video")
            try:
                source = video.first.get_attribute("src", timeout=1_000) if video.count() else None
            except PlaywrightTimeoutError:
                source = None
            if source and source.startswith(("http://", "https://")):
                candidates.append((1, source))
            cookies = context.cookies()
            user_agent = page.evaluate("navigator.userAgent")
            page_meta = page.evaluate("""() => ({
                title: document.title,
                thumbnail: document.querySelector('meta[property="og:image"]')?.content || null
            })""")
        finally:
            browser.close()

    if not candidates:
        raise RuntimeError("浏览器加载了页面，但没有发现可下载的媒体流")
    media_url = max(candidates, key=lambda item: item[0])[1]
    validate_public_url(media_url)
    headers = {"Referer": url, "User-Agent": user_agent}
    if cookies:
        headers["Cookie"] = "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)
    return media_url, headers, page_meta


def download_manifest(job: dict, url: str, quality: str, output_dir: Path) -> None:
    if not NM3U8_EXE.exists():
        raise RuntimeError("N_m3u8DL-RE 尚未安装")
    selectors = {
        "best": "best",
        "720": "res=.*x(720|[1-6][0-9]{2}|[1-9][0-9]?)$:for=best",
        "480": "res=.*x(480|[1-3][0-9]{2}|[1-9][0-9]?)$:for=best",
    }
    command = [
        str(NM3U8_EXE), url,
        "--save-dir", str(output_dir),
        "--tmp-dir", str(output_dir / "segments"),
        "--save-name", "videopipe",
        "--select-video", selectors[quality],
        "--select-audio", "best",
        "--force-ansi-console",
        "--no-ansi-color",
        "--no-log",
        "--log-level", "INFO",
        "--ffmpeg-binary-path", imageio_ffmpeg.get_ffmpeg_exe(),
        "--mux-after-done", "format=mp4:muxer=ffmpeg:skip_sub=true",
    ]
    for name, value in (job.get("headers") or {}).items():
        command.extend(["--header", f"{name}: {value}"])
    run_download_process(job, command, "N_m3u8DL-RE 下载失败")


def download_sync(job_id: str, url: str, quality: str) -> None:
    job = JOBS[job_id]
    output_dir = DOWNLOAD_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = yt_dlp.utils.sanitize_filename(job["title"], restricted=True)[:80].rstrip(". ") or job_id

    def yt_dlp_command(use_aria2: bool) -> list[str]:
        command = [
            sys.executable, "-m", "yt_dlp",
            "--newline", "--progress", "--progress-delta", "0.2", "--no-color", "--no-warnings", "--no-playlist",
            "--progress-template", "download:%(progress._percent_str)s",
            "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
            "--format", QUALITY_FORMATS[quality],
            "--output", str(output_dir / f"{safe_title}.%(ext)s"),
            "--merge-output-format", "mp4/mkv",
        ]
        for name, value in (job.get("headers") or {}).items():
            command.extend(["--add-header", f"{name}:{value}"])
        if use_aria2:
            command.extend([
                "--downloader", str(ARIA2_EXE),
                "--downloader-args", "aria2c:-x 8 -s 8 -k 1M --file-allocation=none --summary-interval=1",
            ])
        command.append(url)
        return command
    try:
        if job.get("cancel_requested"):
            raise RuntimeError("任务已取消")
        if is_manifest_url(url) and not is_hls_url(url):
            download_manifest(job, url, quality, output_dir)
        else:
            use_aria2 = ARIA2_EXE.exists() and not is_hls_url(url)
            try:
                run_download_process(job, yt_dlp_command(use_aria2), "yt-dlp 下载失败")
            except RuntimeError:
                if not use_aria2 or job.get("cancel_requested"):
                    raise
                for partial in output_dir.iterdir():
                    if partial.is_file():
                        partial.unlink()
                run_download_process(job, yt_dlp_command(False), "yt-dlp 下载失败")
        if job.get("cancel_requested"):
            raise RuntimeError("任务已取消")
        files = [p for p in output_dir.iterdir() if p.is_file() and p.suffix not in {".part", ".ytdl"}]
        if not files:
            raise RuntimeError("下载完成但没有生成文件")
        result = max(files, key=lambda path: path.stat().st_mtime)
        update_job(job, status="completed", progress=100, filename=result.name, path=str(result), directory=str(output_dir))
    except Exception as exc:
        if job.get("cancel_requested"):
            update_job(job, status="cancelled", error="任务已取消")
        else:
            update_job(job, status="failed", error=clean_error(exc))


async def run_download(job_id: str, url: str, quality: str) -> None:
    assert DOWNLOAD_SEMAPHORE is not None
    async with DOWNLOAD_SEMAPHORE:
        job = JOBS[job_id]
        if job.get("cancel_requested"):
            return
        update_job(job, status="downloading")
        await asyncio.to_thread(download_sync, job_id, url, quality)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global DOWNLOAD_SEMAPHORE
    init_storage()
    load_jobs()
    DOWNLOAD_SEMAPHORE = asyncio.Semaphore(concurrent_job_limit())
    for job in list(JOBS.values()):
        if job["status"] == "queued":
            asyncio.create_task(run_download(job["id"], job["url"], job["quality"]))
    yield


app = FastAPI(title="VideoPipe", lifespan=lifespan)


@app.post("/api/analyze")
async def analyze(request: LinkRequest) -> dict:
    try:
        url = validate_public_url(extract_url(request.text))
        if is_wechat_share_url(url):
            return await asyncio.to_thread(resolve_wechat_sync, url)
        try:
            return await asyncio.to_thread(analyze_sync, url)
        except yt_dlp.utils.DownloadError:
            media_url, headers, page_meta = await asyncio.to_thread(discover_media_sync, url)
            result = await asyncio.to_thread(analyze_sync, media_url, headers)
            site = (urlparse(url).hostname or "网页").removeprefix("www.")
            page_title = page_meta.get("title")
            if page_title and result["title"].lower() in {"chunklist", "master", "index", "playlist", "playback1"}:
                result["title"] = page_title.split("-免费在线观看", 1)[0]
            if page_meta.get("thumbnail"):
                result["thumbnail"] = page_meta["thumbnail"]
            result.update(source_url=url, resolved_url=media_url, headers=headers, platform=f"{site} · 浏览器发现")
            return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except yt_dlp.utils.DownloadError as exc:
        raise HTTPException(422, f"暂时无法解析这个链接：{clean_error(exc)}") from exc
    except (RuntimeError, PlaywrightTimeoutError) as exc:
        raise HTTPException(422, f"暂时无法解析这个链接：{clean_error(exc)}") from exc


@app.post("/api/jobs", status_code=202)
async def create_job(request: DownloadRequest) -> dict:
    try:
        source_url = validate_public_url(extract_url(request.text))
        url = validate_public_url(request.resolved_url) if request.resolved_url else source_url
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not quality_allowed(request.quality):
        raise HTTPException(400, "画质选项无效")
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "quality": request.quality,
        "url": url,
        "title": (request.title or url)[:200],
        "thumbnail": request.thumbnail,
        "platform": request.platform,
        "engine": "yt-dlp HLS" if is_hls_url(url) else ("N_m3u8DL-RE" if is_manifest_url(url) else ("yt-dlp + Aria2" if ARIA2_EXE.exists() else "yt-dlp")),
        "source_url": source_url,
        "headers": request.headers or {},
        "created_at": time.time(),
    }
    save_job(JOBS[job_id])
    asyncio.create_task(run_download(job_id, url, request.quality))
    return public_job(JOBS[job_id])


@app.get("/api/jobs")
async def list_jobs() -> list[dict]:
    return [public_job(job) for job in sorted(JOBS.values(), key=lambda item: item.get("created_at", 0), reverse=True)]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    if job_id not in JOBS:
        raise HTTPException(404, "任务不存在")
    return public_job(JOBS[job_id])


@app.post("/api/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job or job["status"] not in {"failed", "cancelled"}:
        raise HTTPException(409, "这个任务当前不能重试")
    job.pop("cancel_requested", None)
    update_job(job, status="queued", error=None)
    asyncio.create_task(run_download(job_id, job["url"], job["quality"]))
    return public_job(job)


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job or job["status"] in {"completed", "failed", "cancelled", "delivered"}:
        raise HTTPException(409, "这个任务当前不能取消")
    update_job(job, cancel_requested=True)
    if job["status"] == "queued":
        update_job(job, status="cancelled", error="任务已取消")
    else:
        update_job(job, status="cancelling")
        await asyncio.to_thread(stop_process_tree, job_id)
    return public_job(job)


@app.delete("/api/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job["status"] not in {"completed", "failed", "cancelled", "delivered"}:
        raise HTTPException(409, "请先取消正在运行的任务")
    directory = job.get("directory") or str(DOWNLOAD_DIR / job_id)
    shutil.rmtree(directory, ignore_errors=True)
    JOBS.pop(job_id, None)
    with sqlite3.connect(DATABASE) as db:
        db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


@app.get("/api/jobs/{job_id}/file")
async def get_file(job_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    job = JOBS.get(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(409, "文件尚未准备完成")
    path = Path(job["path"])
    background_tasks.add_task(finalize_delivery, job_id)
    return FileResponse(path, filename=job["filename"], background=background_tasks)


def finalize_delivery(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    shutil.rmtree(job["directory"], ignore_errors=True)
    update_job(job, status="delivered", path=None, directory=None)


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
