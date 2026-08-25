import os
import tempfile
import cv2
import numpy as np
import pytest
from app.tools.stitcher import stitch_videos


def create_dummy_clip(filename: str, color: int):
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, 10.0, (64, 64))
    for _ in range(10):
        frame = np.full((64, 64, 3), color, dtype=np.uint8)
        out.write(frame)
    out.release()


def test_stitch_videos():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as c1, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as c2, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out:
        c1_path, c2_path, out_path = c1.name, c2.name, out.name

    try:
        create_dummy_clip(c1_path, 50)
        create_dummy_clip(c2_path, 150)

        result_path = stitch_videos([c1_path, c2_path], out_path)
        assert os.path.exists(result_path)
        assert os.path.getsize(result_path) > 0
    finally:
        for p in [c1_path, c2_path, out_path]:
            if os.path.exists(p):
                os.remove(p)


def test_stitch_videos_empty():
    with pytest.raises(ValueError):
        stitch_videos([], "/tmp/out.mp4")
