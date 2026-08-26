import os
import tempfile
import cv2
import numpy as np
import pytest
from app.tools.video_parser import extract_first_frame, extract_last_frame, extract_keyframes


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
