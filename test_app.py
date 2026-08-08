from app import JOBS, active_job_count, clean_error, concurrent_job_limit, extract_url, is_hls_url, is_manifest_url, is_wechat_share_url, quality_allowed


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


def test_parallel_job_count():
    JOBS.update({"a": {"status": "downloading"}, "b": {"status": "completed"}, "c": {"status": "queued"}})
    assert active_job_count() == 2
    JOBS.clear()


def test_manifest_quality_regex_does_not_match_1080():
    assert not __import__("re").match(r".*x(480|[1-3][0-9]{2}|[1-9][0-9]?)$", "1920x1080")
    assert __import__("re").match(r".*x(480|[1-3][0-9]{2}|[1-9][0-9]?)$", "854x480")
