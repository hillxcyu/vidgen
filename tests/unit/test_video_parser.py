import base64
import os
import subprocess
import tempfile
import cv2
import numpy as np
import pytest
from app.tools.video_parser import (
    extract_first_frame,
    extract_last_frame,
    extract_keyframes,
    extract_video_tail,
    trim_video_prefix,
    detect_seam_jump_cut,
    get_video_duration,
)


@pytest.fixture
def dummy_video_file():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, 10.0, (64, 64))
    for i in range(20):
        frame = np.full((64, 64, 3), i * 10, dtype=np.uint8)
        out.write(frame)
    out.release()

    yield path

    if os.path.exists(path):
        os.remove(path)


def test_extract_first_frame(dummy_video_file):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out_png = tmp.name

    b64_str = extract_first_frame(dummy_video_file, output_image_path=out_png)
    assert b64_str is not None
    assert len(b64_str) > 0
    assert os.path.exists(out_png)
    assert os.path.getsize(out_png) > 0

    if os.path.exists(out_png):
        os.remove(out_png)


def test_extract_last_frame(dummy_video_file):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out_png = tmp.name

    b64_str = extract_last_frame(dummy_video_file, output_image_path=out_png)
    assert b64_str is not None
    assert len(b64_str) > 0
    assert os.path.exists(out_png)
    assert os.path.getsize(out_png) > 0

    if os.path.exists(out_png):
        os.remove(out_png)


def test_extract_keyframes(dummy_video_file):
    keyframes = extract_keyframes(dummy_video_file, num_keyframes=3)
    assert len(keyframes) == 3
    for kf in keyframes:
        assert len(kf) > 0


def test_extract_last_frame_invalid():
    with pytest.raises(FileNotFoundError):
        extract_last_frame("/invalid/path/video.mp4")


def test_extract_video_tail_and_trim_prefix():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        src_path = tmp.name

    # Create a 6.0-second dummy video (60 frames @ 10fps)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(src_path, fourcc, 10.0, (64, 64))
    for i in range(60):
        frame = np.full((64, 64, 3), min(255, i * 4), dtype=np.uint8)
        out.write(frame)
    out.release()

    try:
        tail_b64, tail_dur = extract_video_tail(src_path, tail_seconds=2.0, strip_audio=True)
        assert len(tail_b64) > 0
        assert 1.5 <= tail_dur <= 2.5

        with open(src_path, "rb") as f:
            raw_bytes = f.read()

        # Simulate [2s echoed tail + 4s extension = 6s] and trim 2s prefix
        trimmed = trim_video_prefix(raw_bytes, trim_seconds=2.0, expected_extension_seconds=3.0)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out_tmp:
            trimmed_path = out_tmp.name
            out_tmp.write(trimmed)
        try:
            trimmed_dur = get_video_duration(trimmed_path)
            assert 3.5 <= trimmed_dur <= 4.5
        finally:
            if os.path.exists(trimmed_path):
                os.remove(trimmed_path)
    finally:
        if os.path.exists(src_path):
            os.remove(src_path)


def test_trim_prefix_opencv_seam_alignment_and_jump_cut_detection():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        raw_ext_path = tmp.name

    # Build a 60-frame @ 10fps (6.0s) video where the echoed terminal frame is at index 18 (1.8s)
    # rather than index 20 (2.0s), followed by smooth progression (180 -> 182 -> 184 ...).
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(raw_ext_path, fourcc, 10.0, (64, 64))
    for i in range(60):
        if i <= 18:
            val = 80 + i * 5  # reaches 170 at frame 18
        else:
            val = min(255, 170 + (i - 18) * 2)
        frame = np.full((64, 64, 3), val, dtype=np.uint8)
        out.write(frame)
    out.release()

    ref_frame = np.full((64, 64, 3), 170, dtype=np.uint8)
    _, buf = cv2.imencode(".png", ref_frame)
    ref_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    try:
        with open(raw_ext_path, "rb") as f:
            raw_bytes = f.read()

        trimmed_bytes = trim_video_prefix(
            raw_bytes,
            trim_seconds=2.0,
            expected_extension_seconds=3.0,
            reference_last_frame_b64=ref_b64,
        )
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as t_out:
            trimmed_path = t_out.name
            t_out.write(trimmed_bytes)

        try:
            has_cut, f0_mae, peak_mae = detect_seam_jump_cut(ref_b64, trimmed_path, max_mae=28.0)
            assert not has_cut
            assert f0_mae < 6.0
            assert peak_mae < 15.0
        finally:
            if os.path.exists(trimmed_path):
                os.remove(trimmed_path)

        # Now synthesize a clip with a hard jump-cut on frame 1 (170 -> 10)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as jc_tmp:
            jc_path = jc_tmp.name
        out_jc = cv2.VideoWriter(jc_path, fourcc, 10.0, (64, 64))
        out_jc.write(np.full((64, 64, 3), 170, dtype=np.uint8))
        for _ in range(9):
            out_jc.write(np.full((64, 64, 3), 10, dtype=np.uint8))
        out_jc.release()
        try:
            has_cut_jc, _, peak_jc = detect_seam_jump_cut(ref_b64, jc_path, max_mae=28.0)
            assert has_cut_jc is True
            assert peak_jc > 100.0
        finally:
            if os.path.exists(jc_path):
                os.remove(jc_path)
    finally:
        if os.path.exists(raw_ext_path):
            os.remove(raw_ext_path)


def test_extract_video_tail_preserves_audio_by_default():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        av_path = tmp.name
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=24:d=3.0",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3.0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                av_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        tail_b64, tail_dur = extract_video_tail(av_path, tail_seconds=1.5)
        assert 1.2 <= tail_dur <= 1.8
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tail_tmp:
            tail_path = tail_tmp.name
            tail_tmp.write(base64.b64decode(tail_b64))
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=codec_name", "-of", "csv=p=0", tail_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            assert "aac" in probe.stdout.decode("utf-8").lower()
        finally:
            if os.path.exists(tail_path):
                os.remove(tail_path)
    finally:
        if os.path.exists(av_path):
            os.remove(av_path)


def test_detect_r2v_first_frame_lock():
    import cv2
    import numpy as np
    from app.tools.video_parser import detect_r2v_first_frame_lock

    white_anchor = np.full((64, 64, 3), 255, dtype=np.uint8)
    white_anchor[16:48, 24:40] = (40, 90, 210)
    _, buf = cv2.imencode(".png", white_anchor)
    anchor_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as lock_tmp:
        locked_vid = lock_tmp.name
    out_locked = cv2.VideoWriter(locked_vid, fourcc, 10.0, (64, 64))
    for _ in range(10):
        out_locked.write(white_anchor)
    out_locked.release()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as scene_tmp:
        scene_vid = scene_tmp.name
    out_scene = cv2.VideoWriter(scene_vid, fourcc, 10.0, (64, 64))
    scene_frame = np.full((64, 64, 3), 65, dtype=np.uint8)
    scene_frame[16:48, 24:40] = (40, 90, 210)
    for _ in range(10):
        out_scene.write(scene_frame)
    out_scene.release()

    try:
        is_locked, mae_locked = detect_r2v_first_frame_lock(anchor_b64, locked_vid, mae_threshold=12.0)
        assert is_locked is True
        assert mae_locked < 5.0

        is_locked_scene, mae_scene = detect_r2v_first_frame_lock(anchor_b64, scene_vid, mae_threshold=12.0)
        assert is_locked_scene is False
        assert mae_scene > 100.0
    finally:
        for p in (locked_vid, scene_vid):
            if os.path.exists(p):
                os.remove(p)
