import os
import subprocess
import tempfile
from typing import List
import cv2


def _video_stream_duration(path: str) -> float:
    """Returns the video stream duration in seconds via OpenCV."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0.0
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps <= 0 or frames <= 0:
        return 0.0
    return float(frames / fps)


def _has_audio_stream(path: str) -> bool:
    """Checks whether an MP4 file contains at least one audio stream."""
    try:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=index", "-of", "csv=p=0", path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return bool(res.stdout.decode("utf-8", errors="ignore").strip())
    except Exception:
        return False


def _stitch_filter_complex(
    video_paths: List[str],
    output_path: str,
    crossfade_seconds: float = 0.08,
) -> None:
    """Normalizes heterogeneous clips and applies seamless boundary xfade + equal-power acrossfade."""
    n = len(video_paths)
    has_audio_flags = [_has_audio_stream(p) for p in video_paths]
    any_have_audio = any(has_audio_flags)
    durations = [max(0.1, _video_stream_duration(p)) for p in video_paths]

    # Probe target dimensions from clip 0
    cap = cv2.VideoCapture(video_paths[0])
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    cap.release()
    w = max(2, w - (w % 2))
    h = max(2, h - (h % 2))
    fps_int = max(1, int(round(fps)))

    use_crossfade = (
        n > 1
        and crossfade_seconds > 0.0
        and all(d >= max(0.5, crossfade_seconds * 4.0) for d in durations)
    )
    xf_dur = round(crossfade_seconds, 4) if use_crossfade else 0.0

    cmd = ["ffmpeg", "-y"]
    for p in video_paths:
        cmd.extend(["-i", os.path.abspath(p)])

    filter_parts = []
    for idx in range(n):
        d_idx = durations[idx]
        filter_parts.append(
            f"[{idx}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={fps_int},settb=1/{fps_int},format=yuv420p,setsar=1,"
            f"trim=duration={d_idx:.6f},setpts=PTS-STARTPTS[v{idx}]"
        )
        if any_have_audio:
            if has_audio_flags[idx]:
                filter_parts.append(
                    f"[{idx}:a:0]aresample=48000,"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"apad=whole_dur={d_idx:.6f},atrim=0:{d_idx:.6f},asetpts=PTS-STARTPTS[a{idx}]"
                )
            else:
                filter_parts.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=0:{d_idx:.6f},asetpts=PTS-STARTPTS[a{idx}]"
                )

    if use_crossfade:
        prev_v = "[v0]"
        cum_dur = durations[0]
        for idx in range(1, n):
            offset = max(0.0, cum_dur - xf_dur)
            out_v = "[outv]" if idx == n - 1 else f"[vx{idx}]"
            filter_parts.append(
                f"{prev_v}[v{idx}]xfade=transition=fade:duration={xf_dur:.4f}:offset={offset:.4f}{out_v}"
            )
            cum_dur = offset + durations[idx]
            prev_v = out_v

        if any_have_audio:
            prev_a = "[a0]"
            for idx in range(1, n):
                out_a = "[outa]" if idx == n - 1 else f"[ax{idx}]"
                filter_parts.append(
                    f"{prev_a}[a{idx}]acrossfade=d={xf_dur:.4f}:c1=qsin:c2=qsin{out_a}"
                )
                prev_a = out_a
    else:
        if any_have_audio:
            concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
            filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")
        else:
            concat_inputs = "".join(f"[v{i}]" for i in range(n))
            filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[outv]")

    filter_complex = ";".join(filter_parts)
    if any_have_audio:
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
            "-video_track_timescale", "90000",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            os.path.abspath(output_path),
        ])
    else:
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
            "-video_track_timescale", "90000",
            "-movflags", "+faststart",
            os.path.abspath(output_path),
        ])

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def stitch_videos(
    video_paths: List[str],
    output_path: str,
    crossfade_seconds: float = 0.08,
) -> str:
    """Stitches multiple MP4 video files together into a single MP4 video file.

    When multi-clip inputs carry audio tracks, normalizes streams via `filter_complex`
    and applies a synchronized micro-crossfade (`xfade` + equal-power `acrossfade`) to
    prevent 10s boundary audio clicks/cutoffs and container timescale mismatches.
    """
    if not video_paths:
        raise ValueError("video_paths list cannot be empty")

    for path in video_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Input video file not found: {path}")

    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    expected_dur = sum(_video_stream_duration(p) for p in video_paths)
    any_have_audio = len(video_paths) > 1 and any(_has_audio_stream(p) for p in video_paths)

    if any_have_audio:
        try:
            _stitch_filter_complex(video_paths, abs_out, crossfade_seconds=crossfade_seconds)
            return abs_out
        except subprocess.CalledProcessError as re_err:
            raise RuntimeError(
                f"FFMPEG audio-crossfade stitching failed: {re_err.stderr.decode('utf-8', errors='ignore')}"
            ) from re_err

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
        abs_out,
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        actual_dur = _video_stream_duration(abs_out)
        if expected_dur > 0 and abs(actual_dur - expected_dur) > max(1.0, 0.1 * expected_dur):
            print(
                f"[FFMPEG Stitcher Notice] Stream-copy duration mismatch "
                f"(expected {expected_dur:.2f}s, got {actual_dur:.2f}s); re-stitching via filter_complex."
            )
            _stitch_filter_complex(video_paths, abs_out, crossfade_seconds=0.0)
    except subprocess.CalledProcessError as e:
        try:
            _stitch_filter_complex(video_paths, abs_out, crossfade_seconds=0.0)
        except subprocess.CalledProcessError as re_err:
            raise RuntimeError(f"FFMPEG stitching failed: {re_err.stderr.decode('utf-8')}") from e
    finally:
        if os.path.exists(manifest_path):
            os.remove(manifest_path)

    return abs_out
