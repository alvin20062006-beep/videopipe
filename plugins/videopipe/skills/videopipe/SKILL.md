---
name: videopipe
description: Find, install with permission, start, operate, update, and troubleshoot the VideoPipe Windows application. Use when a user explicitly asks VideoPipe to analyze or download a media URL, asks for an MP4, wants the completed local file or path, needs the portable release, or encounters a VideoPipe startup or download error.
---

# VideoPipe

Operate VideoPipe locally instead of merely explaining its UI. Keep downloads, task records, configuration, and unrelated repository changes intact.

## Download a user-provided link

1. Treat the user's explicit request to download a supplied URL as permission to start; do not ask a redundant confirmation question. Never bypass DRM, authentication, paywalls, private-account access, or other access controls.
2. Run `python scripts/videopipe_local.py detect` from this skill directory.
3. If VideoPipe is found, reuse that installation. Do not reinstall dependencies or download the portable package.
4. If it is not found, explain that the official portable ZIP is approximately 128 MiB and ask before downloading it. After approval, download it once from the official release URL, extract the complete archive into a normal writable folder, then run detection again.
5. Run `python scripts/videopipe_local.py download "<URL>" --quality best`. Use `--quality 720` or `--quality 480` only when requested. Pass `--root "<path>"` when detection returns multiple installations and the intended one is known.
6. Wait for the command to finish. It returns JSON containing `status`, `path`, `filename`, and whether an existing completed file was reused.
7. Verify that the returned absolute path exists. Give the user the clickable absolute path first. When the client supports local media rendering or attachments and the file size permits it, also present the MP4 directly; never upload it to a third party without permission.

The helper launches VideoPipe's own bundled `runtime/python.exe` or source `.venv` and calls the existing VideoPipe downloader. It does not contain a second download engine. It checks the local task database first and must reuse a matching completed file instead of downloading it again.

## Find or install VideoPipe

The helper checks an explicit `--root`, `VIDEOPIPE_HOME`, the current repository, and common Windows Desktop, Documents, Downloads, OneDrive, and local-app folders. A valid installation contains `app.py`, `desktop.py`, and `static/`.

Official locations:

- Product website: `https://alvin20062006-beep.github.io/videopipe/`
- Release page: `https://github.com/alvin20062006-beep/videopipe/releases/tag/v1.0`
- Portable ZIP: `https://github.com/alvin20062006-beep/videopipe/releases/download/v1.0/VideoPipe-1.0-Windows-x64-portable.zip`

For an approved installation:

1. Download the ZIP once.
2. Extract the entire archive without overwriting an existing installation.
3. Keep `runtime`, `static`, and `vendor` beside `VideoPipe.cmd`.
4. Do not separately install Python, FFmpeg, yt-dlp, aria2, or N_m3u8DL-RE; the portable package includes them.

Windows 10/11 64-bit and Microsoft Edge WebView2 Runtime are required for the desktop window. Headless local downloads use the bundled runtime and do not require opening the window.

## Preserve state and bandwidth

- Never delete `data/` or a completed file unless the user explicitly asks and confirms the exact target.
- Never call `/api/jobs/{job_id}/file` just to obtain a local result; that delivery endpoint removes the job directory after delivery.
- Do not restart completed jobs after an application or computer restart.
- Inspect a failed or interrupted job before retrying it and explain the expected network usage before a large retry.
- Redact sensitive query parameters from logs and screenshots. Never request cookies, passwords, private links, or downloaded media.

## Troubleshoot

For startup failures, confirm the ZIP was fully extracted and that `runtime/pythonw.exe`, `desktop.py`, `static/`, and `vendor/` exist. Run `runtime\python.exe desktop.py` from the installation directory only when the user asks to diagnose startup and capture the exact error. Preserve `data/` throughout repair.

For download failures, report the affected URL type, selected quality, VideoPipe path, and exact sanitized error. Do not silently fall back to an unrelated downloader.
