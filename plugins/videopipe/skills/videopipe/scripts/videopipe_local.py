from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


INSTALL_NAMES = (
    "VideoPipe",
    "videopipe",
    "VideoPipe-1.0-Windows-x64-portable",
)


def is_installation(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "app.py").is_file()
        and (path / "desktop.py").is_file()
        and (path / "static").is_dir()
    )


def add_candidate(results: list[Path], candidate: Path) -> None:
    try:
        resolved = candidate.expanduser().resolve()
    except OSError:
        return
    if is_installation(resolved) and resolved not in results:
        results.append(resolved)


def find_installations(explicit_root: str | None = None) -> list[Path]:
    results: list[Path] = []
    if explicit_root:
        add_candidate(results, Path(explicit_root))

    configured = os.environ.get("VIDEOPIPE_HOME")
    if configured:
        add_candidate(results, Path(configured))

    current = Path.cwd()
    for candidate in (current, *current.parents):
        add_candidate(results, candidate)

    script = Path(__file__).resolve()
    for candidate in script.parents:
        add_candidate(results, candidate)

    home = Path.home()
    bases = [
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "OneDrive",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "Documents",
        Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")),
    ]
    for base in bases:
        add_candidate(results, base)
        for name in INSTALL_NAMES:
            add_candidate(results, base / name)
        if base.is_dir():
            try:
                for child in base.glob("VideoPipe*"):
                    add_candidate(results, child)
            except OSError:
                pass
    return results


def python_for(root: Path) -> Path:
    candidates = (
        root / "runtime" / "python.exe",
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def ensure_mp4(videopipe: Any, job: dict[str, Any]) -> Path:
    source = Path(job["path"]).resolve()
    if source.suffix.lower() == ".mp4":
        return source

    target = source.with_suffix(".mp4")
    ffmpeg = videopipe.imageio_ffmpeg.get_ffmpeg_exe()
    copy_result = subprocess.run(
        [ffmpeg, "-y", "-i", str(source), "-c", "copy", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if copy_result.returncode != 0:
        transcode_result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if transcode_result.returncode != 0:
            error = transcode_result.stderr.strip() or copy_result.stderr.strip()
            raise RuntimeError(f"VideoPipe downloaded the media but MP4 conversion failed: {error[-500:]}")
    videopipe.update_job(job, path=str(target), filename=target.name)
    return target


def detect_command(args: argparse.Namespace) -> int:
    installations = find_installations(args.root)
    emit(
        {
            "found": bool(installations),
            "installations": [
                {"root": str(root), "python": str(python_for(root))}
                for root in installations
            ],
        }
    )
    return 0 if installations else 1


def run_worker(root: Path, url: str, quality: str) -> int:
    command = [
        str(python_for(root)),
        str(Path(__file__).resolve()),
        "_worker",
        url,
        "--quality",
        quality,
        "--root",
        str(root),
    ]
    completed = subprocess.run(command, cwd=root, check=False)
    return completed.returncode


def download_command(args: argparse.Namespace) -> int:
    installations = find_installations(args.root)
    if not installations:
        emit(
            {
                "status": "not_installed",
                "message": "VideoPipe was not found. Ask before downloading the portable package.",
            }
        )
        return 2
    if len(installations) > 1 and not args.root:
        emit(
            {
                "status": "multiple_installations",
                "installations": [str(path) for path in installations],
                "message": "Run again with --root and the intended installation path.",
            }
        )
        return 3
    return run_worker(installations[0], args.url, args.quality)


def worker_command(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if not is_installation(root):
        emit({"status": "error", "error": f"Invalid VideoPipe installation: {root}"})
        return 4

    os.chdir(root)
    sys.path.insert(0, str(root))
    try:
        import app as videopipe

        videopipe.init_storage()
        videopipe.JOBS.clear()
        videopipe.load_jobs()
        source_url = videopipe.validate_public_url(videopipe.extract_url(args.url))

        for job in videopipe.JOBS.values():
            existing_path = job.get("path")
            if (
                job.get("status") == "completed"
                and job.get("source_url") == source_url
                and job.get("quality") == args.quality
                and existing_path
                and Path(existing_path).is_file()
            ):
                output = ensure_mp4(videopipe, job)
                emit(
                    {
                        "status": "completed",
                        "reused": True,
                        "job_id": job["id"],
                        "filename": output.name,
                        "path": str(output),
                        "videopipe_root": str(root),
                    }
                )
                return 0

        analysis = asyncio.run(videopipe.analyze(videopipe.LinkRequest(text=source_url)))
        resolved_url = analysis.get("resolved_url") or source_url
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "quality": args.quality,
            "url": resolved_url,
            "title": (analysis.get("title") or source_url)[:200],
            "thumbnail": analysis.get("thumbnail"),
            "platform": analysis.get("platform"),
            "engine": (
                "yt-dlp HLS"
                if videopipe.is_hls_url(resolved_url)
                else (
                    "N_m3u8DL-RE"
                    if videopipe.is_manifest_url(resolved_url)
                    else ("yt-dlp + Aria2" if videopipe.ARIA2_EXE.exists() else "yt-dlp")
                )
            ),
            "source_url": source_url,
            "headers": analysis.get("headers") or {},
            "created_at": time.time(),
        }
        videopipe.JOBS[job_id] = job
        videopipe.save_job(job)
        videopipe.download_sync(job_id, resolved_url, args.quality)
        result = videopipe.JOBS[job_id]
        if result.get("status") != "completed":
            emit(
                {
                    "status": result.get("status", "failed"),
                    "job_id": job_id,
                    "error": result.get("error", "VideoPipe did not complete the download."),
                    "videopipe_root": str(root),
                }
            )
            return 5
        output = ensure_mp4(videopipe, result)
        emit(
            {
                "status": "completed",
                "reused": False,
                "job_id": job_id,
                "filename": result.get("filename"),
                "path": str(output),
                "videopipe_root": str(root),
            }
        )
        return 0
    except Exception as exc:
        emit(
            {
                "status": "error",
                "error": str(exc)[:1000],
                "videopipe_root": str(root),
            }
        )
        return 6


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find and operate a local VideoPipe installation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="Find local VideoPipe installations.")
    detect.add_argument("--root", help="Check this installation path first.")
    detect.set_defaults(handler=detect_command)

    download = subparsers.add_parser("download", help="Download an authorized media URL with VideoPipe.")
    download.add_argument("url")
    download.add_argument("--quality", choices=("best", "720", "480"), default="best")
    download.add_argument("--root", help="Use this VideoPipe installation.")
    download.set_defaults(handler=download_command)

    worker = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("url")
    worker.add_argument("--quality", choices=("best", "720", "480"), required=True)
    worker.add_argument("--root", required=True)
    worker.set_defaults(handler=worker_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
