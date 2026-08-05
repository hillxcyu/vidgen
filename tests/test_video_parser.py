import os
import tempfile
import cv2
import numpy as np
import pytest
from src.tools.video_parser import extract_last_frame, extract_audio_reference

@pytest.fixture
def sample_video_path():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name

    # Create synthetic 5-frame video
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, 10.0, (64, 64))
    for i in range(5):
        frame = np.full((64, 64, 3), i * 50, dtype=np.uint8)
        out.write(frame)
    out.release()

    yield path

    if os.path.exists(path):
        os.remove(path)

def test_extract_last_frame_success(sample_video_path):
    b64_frame = extract_last_frame(sample_video_path)
    assert isinstance(b64_frame, str)
    assert len(b64_frame) > 0

def test_extract_last_frame_save_file(sample_video_path):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_out:
        out_path = tmp_out.name

    b64_frame = extract_last_frame(sample_video_path, output_image_path=out_path)
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0
    if os.path.exists(out_path):
        os.remove(out_path)

def test_extract_last_frame_invalid_path():
    with pytest.raises(FileNotFoundError):
        extract_last_frame("/non/existent/video.mp4")

def test_extract_audio_reference_non_existent():
    res = extract_audio_reference("/non/existent/video_path_9999.mp4")
    assert res is None
