---
name: videopipe
description: Guide users through installing, starting, using, updating, and troubleshooting the VideoPipe Windows application. Use when a user mentions VideoPipe, asks how to download or run its portable release, encounters startup or download errors, needs to locate downloaded files, wants to update safely, or wants privacy and bandwidth guidance for VideoPipe.
---

# VideoPipe

Help users operate VideoPipe safely and with minimal unnecessary downloads. Treat this as an instruction-only skill: it does not run the Windows application or download media inside ChatGPT.

## Choose the workflow

1. Determine whether the user has the Windows portable release or a source checkout.
2. Preserve existing downloads, task records, configuration, and unrelated repository changes.
3. Prefer inspection and repair over reinstalling or downloading dependencies.
4. Ask before downloading the approximately 128 MiB portable package or performing destructive cleanup.

## Install the portable release

Use these official locations:

- Product website: `https://alvin20062006-beep.github.io/videopipe/`
- Release page: `https://github.com/alvin20062006-beep/videopipe/releases/tag/v1.0`
- Windows package: `https://github.com/alvin20062006-beep/videopipe/releases/download/v1.0/VideoPipe-1.0-Windows-x64-portable.zip`

Tell the user to:

1. Download the ZIP once.
2. Extract the entire archive to a normal writable folder.
3. Keep `runtime`, `static`, and `vendor` beside `VideoPipe.cmd`.
4. Double-click `VideoPipe.cmd`.

Do not tell portable-release users to install Python, FFmpeg, yt-dlp, aria2, or N_m3u8DL-RE separately; the package already includes them. Windows 10/11 64-bit and Microsoft Edge WebView2 Runtime are required.

## Run from source

Use the repository instructions only when the user explicitly wants source development. Distinguish source setup from the portable release and warn before dependency installation because it uses network traffic.

Repository: `https://github.com/alvin20062006-beep/videopipe`

## Troubleshoot

Start with the exact error message, screenshot, affected URL type, and whether the problem occurs before or after the window opens.

For startup failures:

1. Confirm the ZIP was fully extracted.
2. Confirm `runtime/pythonw.exe`, `desktop.py`, `static/`, and `vendor/` exist.
3. Check whether Microsoft Edge WebView2 Runtime is available.
4. To expose a hidden startup error, run `runtime\python.exe desktop.py` from the extracted VideoPipe directory and capture the output.
5. Avoid deleting `data/` unless the user explicitly approves losing local task records.

For download failures:

1. Confirm the user owns or is authorized to download the content.
2. Record the selected quality and whether the source is a normal page, direct media URL, HLS, DASH, or MSS stream.
3. Preserve completed files and inspect the task state before retrying.
4. Do not automatically restart completed downloads after an application restart.
5. Explain expected network usage before retrying a large download.

## Privacy and safety

Never request cookies, passwords, private account links, or downloaded media. Redact sensitive query parameters from logs and screenshots. Remind users that VideoPipe contacts the linked website during parsing and that some public WeChat Channels links may use a third-party resolver.

Only assist with content the user owns, purchased, or is authorized to use. Do not provide instructions for bypassing DRM, authentication, paywalls, or access controls.
