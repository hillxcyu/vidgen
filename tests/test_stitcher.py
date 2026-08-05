import os
import tempfile
import cv2
import numpy as np
import pytest
from src.tools.stitcher import stitch_videos

@pytest.fixture
def sample_clip_paths():
    paths = []
    for idx in range(2):
        with tempfile.NamedTemporaryFile(suffix=f"_clip_{idx}.mp4", delete=False) as tmp:
            path = tmp.name
            paths.append(path)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(path, fourcc, 10.0, (64, 64))
        for _ in range(5):
            frame = np.full((64, 64, 3), (idx + 1) * 80, dtype=np.uint8)
            out.write(frame)
        out.release()

    yield paths

    for p in paths:
        if os.path.exists(p):
            os.remove(p)

def test_stitch_videos_success(sample_clip_paths):
    with tempfile.NamedTemporaryFile(suffix="_stitched.mp4", delete=False) as tmp_out:
        out_path = tmp_out.name

    result_path = stitch_videos(sample_clip_paths, out_path)
    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 0

    # Verify frame count of stitched video using OpenCV
    cap = cv2.VideoCapture(result_path)
    assert cap.isOpened()
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert total_frames == 10  # 5 frames + 5 frames

    if os.path.exists(out_path):
        os.remove(out_path)

def test_stitch_videos_empty_list():
    with pytest.raises(ValueError):
        stitch_videos([], "/tmp/out.mp4")

def test_stitch_videos_missing_file():
    with pytest.raises(FileNotFoundError):
        stitch_videos(["/non/existent/clip.mp4"], "/tmp/out.mp4")
