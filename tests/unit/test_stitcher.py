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


def test_stitch_videos_with_audio_crossfade():
    import subprocess
    from app.tools.stitcher import _has_audio_stream, _video_stream_duration

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as c1, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as c2, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out:
        c1_path, c2_path, out_path = c1.name, c2.name, out.name

    try:
        for path, color, freq in [(c1_path, "red", 440), (c2_path, "blue", 554)]:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=128x72:r=24:d=2.0",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration=2.0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k",
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

        stitched = stitch_videos([c1_path, c2_path], out_path, crossfade_seconds=0.08)
        assert os.path.exists(stitched)
        assert _has_audio_stream(stitched) is True
        dur = _video_stream_duration(stitched)
        assert 3.7 <= dur <= 4.1
    finally:
        for p in [c1_path, c2_path, out_path]:
            if os.path.exists(p):
                os.remove(p)
