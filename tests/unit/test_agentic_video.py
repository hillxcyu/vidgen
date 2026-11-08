import pytest
from google.genai import types
from app.config import Config
from app.tools.video_parser import create_agentic_video_part, extract_avu_usage_telemetry
from src.tools.video_parser import (
    create_agentic_video_part as create_agentic_video_part_src,
    extract_avu_usage_telemetry as extract_avu_usage_telemetry_src,
)


def test_config_media_processing_default():
    cfg = Config()
    assert cfg.MEDIA_PROCESSING == "agentic"


def test_create_agentic_video_part_gs_uri():
    part = create_agentic_video_part("gs://my-bucket/test_shot.mp4", media_processing="agentic")
    assert part.file_data is not None
    assert part.file_data.file_uri == "gs://my-bucket/test_shot.mp4"
    assert part.file_data.mime_type == "video/mp4"
    assert str(part.media_processing).upper() in ["AGENTIC", "MEDIAPROCESSING.AGENTIC"]


def test_create_agentic_video_part_https_url():
    part = create_agentic_video_part(
        "https://storage.googleapis.com/vital-octagon-19612-vidgen-showcase/showcase/shots/shot_1.mp4",
        media_processing="agentic"
    )
    assert part.file_data is not None
    assert part.file_data.file_uri == "gs://vital-octagon-19612-vidgen-showcase/showcase/shots/shot_1.mp4"
    assert part.file_data.mime_type == "video/mp4"
    assert str(part.media_processing).upper() in ["AGENTIC", "MEDIAPROCESSING.AGENTIC"]


def test_create_agentic_video_part_inline_bytes():
    fake_bytes = b"\x00\x00\x00\x18ftypmp42"
    part = create_agentic_video_part(
        "/tmp/nonexistent.mp4",
        video_bytes=fake_bytes,
        media_processing="agentic"
    )
    assert part.inline_data is not None
    assert part.inline_data.data == fake_bytes
    assert part.inline_data.mime_type == "video/mp4"
    assert str(part.media_processing).upper() in ["AGENTIC", "MEDIAPROCESSING.AGENTIC"]


def test_create_agentic_video_part_static_mode():
    part = create_agentic_video_part(
        "gs://my-bucket/sports_clip.mp4",
        media_processing="static"
    )
    assert part.file_data is not None
    assert part.file_data.file_uri == "gs://my-bucket/sports_clip.mp4"
    assert str(part.media_processing).upper() in ["STATIC", "MEDIAPROCESSING.STATIC"]


def test_src_create_agentic_video_part_parity():
    part = create_agentic_video_part_src(
        "https://storage.googleapis.com/bucket/clip.mp4",
        media_processing="agentic"
    )
    assert part.file_data.file_uri == "gs://bucket/clip.mp4"
    assert str(part.media_processing).upper() in ["AGENTIC", "MEDIAPROCESSING.AGENTIC"]


def test_create_agentic_video_part_cloud_console_url_and_enum():
    part = create_agentic_video_part(
        "https://storage.cloud.google.com/vital-octagon-19612-vidgen-showcase/showcase/shot_1.mp4?authuser=0",
        media_processing=types.MediaProcessing.AGENTIC,
    )
    assert part.file_data is not None
    assert part.file_data.file_uri == "gs://vital-octagon-19612-vidgen-showcase/showcase/shot_1.mp4"
    assert part.media_processing == types.MediaProcessing.AGENTIC


def test_extract_avu_usage_telemetry():
    class _DummyUsage:
        tool_use_prompt_token_count = 4154
        prompt_token_count = 726
        total_token_count = 5120

    class _DummyResp:
        usage_metadata = _DummyUsage()

    tel = extract_avu_usage_telemetry(_DummyResp())
    assert tel["avu_active"] is True
    assert tel["avu_tool_use_tokens"] == 4154
    assert tel["avu_prompt_tokens"] == 726
    assert tel["avu_total_tokens"] == 5120
    assert extract_avu_usage_telemetry_src(_DummyResp()) == tel
    assert extract_avu_usage_telemetry(None) == {}

