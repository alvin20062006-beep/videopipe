import asyncio
import json

import pytest

import app as videopipe_app
from app import JOBS, LinkRequest, active_job_count, analyze, choose_media_candidates, clean_error, concurrent_job_limit, discovered_media_result, extract_url, inspect_hls_manifest, is_douyin_url, is_hls_url, is_manifest_url, is_probable_ad, is_wechat_share_url, media_request_headers, preview_url, quality_allowed, resolve_wechat_sync, rewrite_hls_manifest, score_media_candidate, start_wechat_service


def test_share_text_url_extraction():
    assert extract_url("复制链接 https://example.com/watch?v=1，一起看看") == "https://example.com/watch?v=1"
    assert quality_allowed("best")
    assert quality_allowed("480")
    assert not quality_allowed("4k-member")
    assert concurrent_job_limit() == 3
    assert clean_error(Exception("\x1b[31m失败\x1b[0m")) == "失败"
    assert is_manifest_url("https://cdn.example/video/master.m3u8?token=1")
    assert is_hls_url("https://cdn.example/video/master.m3u8?token=1")
    assert not is_hls_url("https://cdn.example/video/manifest.mpd")
    assert not is_manifest_url("https://example.com/watch/123")
    assert is_wechat_share_url("https://weixin.qq.com/sph/Axv548mzBF")
    assert not is_wechat_share_url("https://example.com/sph/Axv548mzBF")
    assert is_douyin_url("https://v.douyin.com/abc")
    assert not is_douyin_url("https://www.tiktok.com/video/1")


def test_parallel_job_count():
    JOBS.update({"a": {"status": "downloading"}, "b": {"status": "completed"}, "c": {"status": "queued"}})
    assert active_job_count() == 2
    JOBS.clear()


def test_manifest_quality_regex_does_not_match_1080():
    assert not __import__("re").match(r".*x(480|[1-3][0-9]{2}|[1-9][0-9]?)$", "1920x1080")
    assert __import__("re").match(r".*x(480|[1-3][0-9]{2}|[1-9][0-9]?)$", "854x480")


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit=-1):
        return self.body


def test_hls_manifest_requires_real_segments(monkeypatch):
    manifest = "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\npart-1.ts\n#EXTINF:9.5,\npart-2.ts\n"
    monkeypatch.setattr(videopipe_app, "urlopen", lambda *_args, **_kwargs: FakeResponse(manifest))
    result = inspect_hls_manifest("https://cdn.example/show/main.m3u8", {})
    assert result["segment_count"] == 2
    assert result["duration"] == 19.5


def test_hls_manifest_accepts_extensionless_segments(monkeypatch):
    manifest = "#EXTM3U\n#EXTINF:10,\nsegment/1001?token=x\n#EXTINF:10,\nsegment/1002?token=x\n"
    monkeypatch.setattr(videopipe_app, "urlopen", lambda *_args, **_kwargs: FakeResponse(manifest))
    assert inspect_hls_manifest("https://cdn.example/show/main.m3u8", {})["segment_count"] == 2


def test_hls_manifest_rejects_blank_placeholder(monkeypatch):
    monkeypatch.setattr(videopipe_app, "urlopen", lambda *_args, **_kwargs: FakeResponse("#EXTM3U\n#EXT-X-ENDLIST\n"))
    with pytest.raises(RuntimeError, match="媒体分片"):
        inspect_hls_manifest("https://cdn.example/show/blank.m3u8", {})


def test_hls_master_rejects_when_all_variants_are_invalid(monkeypatch):
    manifests = {
        "https://cdn.example/master.m3u8": "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\nmissing.m3u8\n",
        "https://cdn.example/missing.m3u8": "#EXTM3U\n#EXT-X-ENDLIST\n",
    }
    monkeypatch.setattr(videopipe_app, "urlopen", lambda request, **_kwargs: FakeResponse(manifests[request.full_url]))
    with pytest.raises(RuntimeError, match="没有可用的视频线路"):
        inspect_hls_manifest("https://cdn.example/master.m3u8", {})


def test_cookie_headers_are_scoped_to_media_domain():
    cookies = [{"name": "session", "value": "secret", "domain": ".yifan.tv"}]
    same_site = media_request_headers("https://www.yifan.tv/play/1", "https://media.yifan.tv/main.m3u8", "ua", cookies)
    cross_site = media_request_headers("https://www.yifan.tv/play/1", "https://cdn.example/main.m3u8", "ua", cookies)
    assert same_site["Cookie"] == "session=secret"
    assert "Cookie" not in cross_site


def test_long_main_video_scores_above_short_ad():
    main = {"kind": "hls", "url": "https://cdn.example/main.m3u8", "hits": 6, "dom_source": True, "inspection": {"duration": 1800, "segment_count": 30, "is_master": True}}
    ad = {"kind": "hls", "url": "https://cdn.example/ads/preroll.m3u8", "hits": 10, "dom_source": False, "inspection": {"duration": 15, "segment_count": 3, "is_master": False}}
    assert score_media_candidate(main) > score_media_candidate(ad) + 100
    assert is_probable_ad(ad)
    assert not is_probable_ad(main)


def test_candidate_selection_drops_blank_and_short_ad(monkeypatch):
    manifests = {
        "https://cdn.example/blank.m3u8": "#EXTM3U\n#EXT-X-ENDLIST\n",
        "https://cdn.example/ads/preroll.m3u8": "#EXTM3U\n#EXTINF:10,\na.ts\n#EXTINF:10,\nb.ts\n",
        "https://cdn.example/main.m3u8": "#EXTM3U\n#EXTINF:60,\na.ts\n#EXTINF:60,\nb.ts\n",
    }
    monkeypatch.setattr(videopipe_app, "validate_public_url", lambda value: value)
    monkeypatch.setattr(videopipe_app, "urlopen", lambda request, **_kwargs: FakeResponse(manifests[request.full_url]))
    selected = choose_media_candidates([
        {"kind": "hls", "url": "https://cdn.example/blank.m3u8", "hits": 8, "dom_source": True},
        {"kind": "hls", "url": "https://cdn.example/ads/preroll.m3u8", "hits": 20, "dom_source": True},
        {"kind": "hls", "url": "https://cdn.example/main.m3u8", "hits": 2, "dom_source": False},
    ], "https://www.yifan.tv/play/1", "ua", [])
    assert [candidate["url"] for candidate in selected] == ["https://cdn.example/main.m3u8"]


def test_latest_signed_candidate_wins_deduplication(monkeypatch):
    manifest = "#EXTM3U\n#EXTINF:60,\na.ts\n#EXTINF:60,\nb.ts\n"
    monkeypatch.setattr(videopipe_app, "validate_public_url", lambda value: value)
    monkeypatch.setattr(videopipe_app, "urlopen", lambda *_args, **_kwargs: FakeResponse(manifest))
    selected = choose_media_candidates([
        {"kind": "hls", "url": "https://cdn.example/main.m3u8?token=old", "hits": 5, "dom_source": False, "last_seen": 1},
        {"kind": "hls", "url": "https://cdn.example/main.m3u8?token=new", "hits": 1, "dom_source": False, "last_seen": 2},
    ], "https://www.yifan.tv/play/1", "ua", [])
    assert selected[0]["url"].endswith("token=new")


def test_browser_hls_analysis_does_not_create_download_job(monkeypatch):
    JOBS.clear()
    monkeypatch.setattr(videopipe_app, "validate_public_url", lambda value: value)
    monkeypatch.setattr(videopipe_app, "analyze_sync", lambda *_args, **_kwargs: (_ for _ in ()).throw(videopipe_app.yt_dlp.utils.DownloadError("unsupported")))
    selected = {"url": "https://cdn.example/main.m3u8", "kind": "hls", "headers": {"Referer": "https://example.com/watch"}, "inspection": {"duration": 120, "max_height": 720}}
    monkeypatch.setattr(videopipe_app, "discover_media_sync", lambda _url: (selected["url"], selected["headers"], {"title": "Show", "thumbnail": None, "selected_candidate": selected}))
    result = asyncio.run(analyze(LinkRequest(text="https://example.com/watch")))
    assert result["resolved_url"] == selected["url"]
    assert JOBS == {}


def test_wechat_uses_local_parse_endpoint(monkeypatch):
    payload = {"data": {"data": {"feedInfo": {"originVideoUrl": "https://cdn.example/video.mp4", "description": "测试视频"}}}}
    seen = {}
    monkeypatch.setattr(videopipe_app, "WECHAT_RESOLVER", "http://127.0.0.1:2022/api/channels/parse_sph")
    monkeypatch.setattr(videopipe_app, "validate_public_url", lambda value: value)
    monkeypatch.setattr(videopipe_app, "urlopen", lambda request, **_kwargs: (seen.update(request=request) or FakeResponse(json.dumps(payload))))
    result = resolve_wechat_sync("https://weixin.qq.com/sph/abc")
    assert "api/channels/parse_sph?url=https%3A%2F%2Fweixin.qq.com%2Fsph%2Fabc" in seen["request"].full_url
    assert result["resolved_url"] == "https://cdn.example/video.mp4"


def test_browser_candidates_require_confirmation_when_scores_are_close():
    first = {"url": "https://cdn.example/one.m3u8", "headers": {}, "score": 140, "inspection": {"duration": 60, "max_height": 720}}
    second = {"url": "https://cdn.example/two.m3u8", "headers": {}, "score": 120, "inspection": {"duration": 60, "max_height": 720}}
    result = discovered_media_result("https://example.com/watch", {"title": "Show", "thumbnail": None, "candidates": [first, second]}, first)
    assert [item["resolved_url"] for item in result["alternatives"]] == [first["url"], second["url"]]


def test_hls_preview_rewrites_every_media_request_through_local_proxy():
    manifest = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"\nsegments/one.ts\n'
    rewritten = rewrite_hls_manifest("preview1", "https://cdn.example/live/master.m3u8", manifest)
    assert preview_url("preview1", "https://cdn.example/live/keys/key.bin") in rewritten
    assert preview_url("preview1", "https://cdn.example/live/segments/one.ts") in rewritten


def test_bundled_wechat_service_starts_only_when_local_resolver_is_free(monkeypatch):
    calls = []

    class FakeProcess:
        def poll(self):
            return None

    monkeypatch.setattr(videopipe_app, "local_wechat_resolver", lambda: True)
    monkeypatch.setattr(videopipe_app, "wechat_service_running", lambda: False)
    monkeypatch.setattr(videopipe_app, "WECHAT_EXE", __import__("pathlib").Path(__file__))
    monkeypatch.setattr(videopipe_app.subprocess, "Popen", lambda command, **kwargs: (calls.append((command, kwargs)) or FakeProcess()))
    start_wechat_service()
    assert calls[0][0][1] == "server"
    videopipe_app.WECHAT_PROCESS = None


def test_douyin_does_not_fall_back_to_browser_sniffing(monkeypatch):
    monkeypatch.setattr(videopipe_app, "validate_public_url", lambda value: value)
    monkeypatch.setattr(videopipe_app, "analyze_sync", lambda *_args: (_ for _ in ()).throw(videopipe_app.yt_dlp.utils.DownloadError("blocked")))
    monkeypatch.setattr(videopipe_app, "discover_media_sync", lambda *_args: pytest.fail("Douyin must not sniff page media"))
    with pytest.raises(Exception, match="避免误下载广告"):
        asyncio.run(analyze(LinkRequest(text="https://v.douyin.com/abc")))
