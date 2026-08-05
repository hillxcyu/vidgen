import os
import subprocess
import tempfile
from typing import List

def stitch_videos(video_paths: List[str], output_path: str) -> str:
    """Stitches multiple MP4 video files together into a single MP4 video file
    using FFMPEG stream copy (without re-encoding).
    """
    if not video_paths:
        raise ValueError("video_paths list cannot be empty")

    for path in video_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Input video file not found: {path}")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Create temporary concat manifest file
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        manifest_path = f.name
        for path in video_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", manifest_path,
        "-c", "copy",
        os.path.abspath(output_path)
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFMPEG stitching failed: {e.stderr.decode('utf-8')}") from e
    finally:
        if os.path.exists(manifest_path):
            os.remove(manifest_path)

    return os.path.abspath(output_path)
