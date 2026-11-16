# Copyright 2026 Author:Hill YU(xcyu@)
"""Standalone OpenCV and FFMPEG media processing utilities and CLI for multi-shot video generation.

Provides deterministic frame extraction, 5.0s audio-intact video tail extraction, OpenCV pixel-MAE
seam frame alignment and frame-exact FFMPEG prefix trimming, R2V studio-white Frame-0 lock detection,
post-seam jump-cut detection, labeled audit keyframe extraction (KEY FRAME A/M/B), trailing 0.20s
RMS audio cutoff telemetry, Levenshtein WER scoring, Agentic Video Understanding Part construction,
and 80ms xfade/acrossfade multi-clip stitching with zero ADK framework dependencies.
"""
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "google-genai>=2.21.0",
#   "opencv-python-headless>=4.8.0",
#   "numpy>=1.24.0",
# ]
# ///

import argparse
import base64
from collections import Counter
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import wave

import cv2
import numpy as np


def encode_image_file_b64(image_path: str) -> str:
    """Reads a local image file and returns its base64-encoded UTF-8 string."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")
    with open(image_path, "rb") as fp:
        return base64.b64encode(fp.read()).decode("utf-8")


def decode_valid_image_b64(b64_str: Optional[str]) -> Optional[Tuple[bytes, str]]:
    """Decodes a base64 image string and validates PNG/JPEG/WebP magic bytes."""
    if not b64_str or not isinstance(b64_str, str):
        return None
    cleaned = b64_str.strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1].strip()
    try:
        raw = base64.b64decode(cleaned, validate=True)
    except Exception:
        return None
    if len(raw) < 12:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw, "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return raw, "image/jpeg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return raw, "image/webp"
    return None


def get_video_duration(video_path: str) -> float:
    """Returns the duration of an MP4 video file in seconds via OpenCV."""
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return 0.0
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps <= 0 or frames <= 0:
        return 0.0
    return float(frames / fps)


def extract_first_frame(video_path: str, output_image_path: Optional[str] = None) -> str:
    """Extracts Frame 0 of an MP4 video as a base64 PNG string (and optionally writes to disk)."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError(f"Failed to read first frame from: {video_path}")
    if output_image_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
        cv2.imwrite(output_image_path, frame)
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Failed to encode first frame as PNG")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def extract_last_frame(video_path: str, output_image_path: Optional[str] = None) -> str:
    """Extracts the final frame of an MP4 video as a base64 PNG string (and optionally writes to disk)."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        raise ValueError(f"Video file has no valid frames: {video_path}")
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError(f"Failed to read last frame from: {video_path}")
    if output_image_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
        cv2.imwrite(output_image_path, frame)
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Failed to encode last frame as PNG")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def extract_labeled_audit_keyframes(video_path: str) -> List[Tuple[str, bytes]]:
    """Extracts high-res PNG stills for KEY FRAME A (t=0.00s), KEY FRAME M (mid-shot), and KEY FRAME B (terminal)."""
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    if fps <= 0.0:
        fps = 24.0
    if total_frames <= 0:
        cap.release()
        return []

    mid_idx = max(0, total_frames // 2)
    last_idx = max(0, total_frames - 1)
    targets = [
        (0, "KEY FRAME A (t=0.00s, opening frame)"),
        (mid_idx, f"KEY FRAME M (t={mid_idx / fps:.2f}s, mid-shot)"),
        (last_idx, f"KEY FRAME B (t={last_idx / fps:.2f}s, terminal frame)"),
    ]
    results: List[Tuple[str, bytes]] = []
    seen = set()
    for idx, label in targets:
        if idx in seen and len(targets) > 1:
            continue
        seen.add(idx)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            ok, buf = cv2.imencode(".png", frame)
            if ok:
                results.append((label, buf.tobytes()))
    cap.release()
    return results


def create_agentic_video_part(
    video_path_or_uri: str,
    video_bytes: Optional[bytes] = None,
    media_processing: str = "AGENTIC",
) -> Any:
    """Builds a Google GenAI Part with MediaProcessing.AGENTIC (triggers server-side google:load_video on Gemini 3.8 Flash)."""
    from google.genai import types

    norm_mode_str = str(media_processing or "AGENTIC").strip().upper()
    if hasattr(types, "MediaProcessing"):
        resolved_mode = (
            types.MediaProcessing.STATIC
            if norm_mode_str.endswith("STATIC")
            else types.MediaProcessing.AGENTIC
        )
    else:
        resolved_mode = "static" if norm_mode_str.endswith("STATIC") else "agentic"

    file_uri = None
    if video_path_or_uri.startswith("gs://"):
        file_uri = video_path_or_uri
    elif video_path_or_uri.startswith("https://storage.googleapis.com/"):
        file_uri = "gs://" + video_path_or_uri.removeprefix("https://storage.googleapis.com/")
    elif video_path_or_uri.startswith("https://storage.cloud.google.com/"):
        file_uri = "gs://" + video_path_or_uri.removeprefix("https://storage.cloud.google.com/")

    if file_uri:
        return types.Part(
            file_data=types.FileData(file_uri=file_uri, mime_type="video/mp4"),
            media_processing=resolved_mode,
        )

    data = video_bytes
    if not data and os.path.exists(video_path_or_uri) and os.path.isfile(video_path_or_uri):
        with open(video_path_or_uri, "rb") as fp:
            data = fp.read()

    if data:
        return types.Part(
            inline_data=types.Blob(data=data, mime_type="video/mp4"),
            media_processing=resolved_mode,
        )

    return types.Part(
        file_data=types.FileData(file_uri=video_path_or_uri, mime_type="video/mp4"),
        media_processing=resolved_mode,
    )


def extract_video_tail(
    video_path: str,
    tail_seconds: float = 5.0,
    strip_audio: bool = False,
    output_video_path: Optional[str] = None,
) -> Tuple[str, float]:
    """Extracts the trailing `tail_seconds` subclip as base64 MP4 (preserving 48kHz stereo AAC audio by default)."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at: {video_path}")

    total_dur = get_video_duration(video_path)
    start_sec = max(0.0, total_dur - tail_seconds) if total_dur > 0 else 0.0

    cleanup = False
    if output_video_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        output_video_path = tmp.name
        tmp.close()
        cleanup = True
    else:
        os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)

    cmd = ["ffmpeg", "-y", "-ss", f"{start_sec:.3f}", "-i", video_path, "-map", "0:v:0"]
    if strip_audio:
        cmd.append("-an")
    else:
        cmd.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
    cmd.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-video_track_timescale", "90000",
        output_video_path,
    ])

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        actual_dur = get_video_duration(output_video_path)
        if actual_dur <= 0:
            actual_dur = min(tail_seconds, total_dur) if total_dur > 0 else tail_seconds
        with open(output_video_path, "rb") as fp:
            b64_str = base64.b64encode(fp.read()).decode("utf-8")
        return b64_str, actual_dur
    finally:
        if cleanup and output_video_path and os.path.exists(output_video_path):
            os.remove(output_video_path)


def _find_best_seam_frame_index(
    video_path: str,
    trim_seconds: float,
    reference_last_frame_b64: Optional[str],
) -> Tuple[int, float, float]:
    """Scans [-0.45s, +0.25s] around `trim_seconds` to locate the exact echoed terminal frame via OpenCV pixel MAE."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0, trim_seconds, -1.0

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    default_idx = max(0, min(total_frames - 1, int(round(trim_seconds * fps)) - 1))

    if not reference_last_frame_b64 or total_frames <= 2:
        cap.release()
        return default_idx, default_idx / fps, -1.0

    try:
        ref_arr = np.frombuffer(base64.b64decode(reference_last_frame_b64), dtype=np.uint8)
        ref_img = cv2.imdecode(ref_arr, cv2.IMREAD_COLOR)
    except Exception:
        ref_img = None

    if ref_img is None:
        cap.release()
        return default_idx, default_idx / fps, -1.0

    center_idx = int(round(trim_seconds * fps))
    lo = max(0, center_idx - int(round(0.45 * fps)))
    hi = min(total_frames - 1, center_idx + int(round(0.25 * fps)))

    best_idx = default_idx
    best_mae = 999.0
    for idx in range(lo, hi + 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frm = cap.read()
        if ret and frm is not None:
            if frm.shape != ref_img.shape:
                frm = cv2.resize(frm, (ref_img.shape[1], ref_img.shape[0]))
            mae = float(np.mean(np.abs(ref_img.astype(float) - frm.astype(float))))
            if mae < best_mae:
                best_mae = mae
                best_idx = idx

    cap.release()
    return best_idx, best_idx / fps, round(best_mae, 2)


def trim_video_prefix(
    video_bytes: bytes,
    trim_seconds: float,
    expected_extension_seconds: float = 10.0,
    reference_last_frame_b64: Optional[str] = None,
) -> bytes:
    """Trims the echoed prefix from a Gemini Omni `task='extend'` output using frame-exact OpenCV seam alignment."""
    if not video_bytes or trim_seconds <= 0:
        return video_bytes

    in_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    out_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    in_path, out_path = in_tmp.name, out_tmp.name
    in_tmp.write(video_bytes)
    in_tmp.close()
    out_tmp.close()

    try:
        total_dur = get_video_duration(in_path)
        threshold = (
            expected_extension_seconds + (0.5 * trim_seconds)
            if expected_extension_seconds > 0
            else trim_seconds + 1.0
        )
        if total_dur < threshold or total_dur <= trim_seconds + 0.5:
            return video_bytes

        start_idx, start_sec, _ = _find_best_seam_frame_index(
            in_path, trim_seconds, reference_last_frame_b64
        )

        probe_a = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=index", "-of", "csv=p=0", in_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        has_audio = bool(probe_a.stdout.decode("utf-8", errors="ignore").strip())

        cmd = [
            "ffmpeg", "-y", "-i", in_path,
            "-vf", f"select='gte(n,{start_idx})',setpts=PTS-STARTPTS",
        ]
        if has_audio:
            cmd.extend([
                "-af", f"atrim=start={start_sec:.6f},asetpts=PTS-STARTPTS",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-shortest",
            ])
        else:
            cmd.append("-an")

        cmd.extend([
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
            "-video_track_timescale", "90000",
            out_path,
        ])
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            with open(out_path, "rb") as fp:
                return fp.read()
        return video_bytes
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                os.remove(p)


def detect_seam_jump_cut(
    reference_last_frame_b64: Optional[str],
    trimmed_video_path: str,
    max_mae: float = 28.0,
    check_frames: int = 5,
) -> Tuple[bool, float, float]:
    """Checks the first `check_frames` frames of a chained/extended shot against the prior shot's terminal frame."""
    if not reference_last_frame_b64 or not os.path.exists(trimmed_video_path):
        return False, 0.0, 0.0
    try:
        ref_arr = np.frombuffer(base64.b64decode(reference_last_frame_b64), dtype=np.uint8)
        ref_img = cv2.imdecode(ref_arr, cv2.IMREAD_COLOR)
    except Exception:
        return False, 0.0, 0.0
    if ref_img is None:
        return False, 0.0, 0.0

    cap = cv2.VideoCapture(trimmed_video_path)
    if not cap.isOpened():
        return False, 0.0, 0.0

    f0_mae = 0.0
    worst_mae = 0.0
    for idx in range(max(1, check_frames)):
        ret, frm = cap.read()
        if not ret or frm is None:
            break
        if frm.shape != ref_img.shape:
            frm = cv2.resize(frm, (ref_img.shape[1], ref_img.shape[0]))
        mae = float(np.mean(np.abs(ref_img.astype(float) - frm.astype(float))))
        if idx == 0:
            f0_mae = mae
        if mae > worst_mae:
            worst_mae = mae
    cap.release()
    return worst_mae > max_mae, round(f0_mae, 2), round(worst_mae, 2)


def detect_r2v_first_frame_lock(
    reference_image_b64: Optional[str],
    generated_video_path: str,
    mae_threshold: float = 12.0,
) -> Tuple[bool, float]:
    """Detects if Frame 0 of an R2V shot echoed the literal #FFFFFF reference image (`MAE < 12.0`)."""
    if not reference_image_b64 or not os.path.exists(generated_video_path):
        return False, 999.0
    try:
        ref_arr = np.frombuffer(base64.b64decode(reference_image_b64), dtype=np.uint8)
        ref_img = cv2.imdecode(ref_arr, cv2.IMREAD_COLOR)
    except Exception:
        return False, 999.0
    if ref_img is None:
        return False, 999.0

    cap = cv2.VideoCapture(generated_video_path)
    if not cap.isOpened():
        return False, 999.0
    ret, f0 = cap.read()
    cap.release()
    if not ret or f0 is None:
        return False, 999.0
    if f0.shape != ref_img.shape:
        ref_img = cv2.resize(ref_img, (f0.shape[1], f0.shape[0]))
    mae = float(np.mean(np.abs(f0.astype(float) - ref_img.astype(float))))
    return mae < mae_threshold, round(mae, 2)


def analyze_clip_audio_tail(video_path: str, tail_sec: float = 0.20) -> Dict[str, Any]:
    """Computes clip duration, mid-shot RMS dBFS, trailing 0.20s RMS dBFS, and speech-cutoff detection."""
    clip_duration = round(get_video_duration(video_path), 2)
    telemetry: Dict[str, Any] = {
        "clip_duration_sec": clip_duration,
        "has_audio": False,
        "mid_rms_db": None,
        "trailing_rms_db": None,
        "tail_window_sec": round(tail_sec, 2),
        "speech_cutoff_detected": False,
    }
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return telemetry

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = tmp.name
    tmp.close()

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 44:
            return telemetry

        with wave.open(wav_path, "rb") as wf:
            sr = wf.getframerate() or 16000
            n_frames = wf.getnframes()
            if n_frames <= 0:
                return telemetry
            raw_pcm = wf.readframes(n_frames)

        samples = struct.unpack(f"<{n_frames}h", raw_pcm)
        if not samples:
            return telemetry

        telemetry["has_audio"] = True
        if clip_duration <= 0.0:
            telemetry["clip_duration_sec"] = round(n_frames / float(sr), 2)

        def _rms_db(chunk: Tuple[int, ...]) -> float:
            if not chunk:
                return -90.0
            mean_sq = sum(s * s for s in chunk) / float(len(chunk))
            rms = math.sqrt(mean_sq) / 32768.0
            if rms <= 1e-9:
                return -90.0
            return round(20.0 * math.log10(rms), 1)

        tail_count = max(1, int(round(tail_sec * sr)))
        trailing_db = _rms_db(samples[-tail_count:])
        mid_start = min(len(samples), int(round(0.5 * sr)))
        mid_end = max(mid_start + 1, len(samples) - int(round(0.5 * sr)))
        mid_chunk = samples[mid_start:mid_end] if mid_end > mid_start else samples
        mid_db = _rms_db(mid_chunk)

        telemetry["mid_rms_db"] = mid_db
        telemetry["trailing_rms_db"] = trailing_db
        telemetry["speech_cutoff_detected"] = bool(
            trailing_db > -26.0 and trailing_db >= (mid_db - 6.0)
        )
        return telemetry
    except Exception:
        return telemetry
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def compute_transcript_metrics(
    expected_dialogue: Optional[str],
    heard_transcript: Optional[str],
) -> Dict[str, Optional[float]]:
    """Computes word-level Levenshtein WER and recall word-overlap between expected and heard dialogue."""
    def _tokenize(text: Optional[str]) -> List[str]:
        if not text:
            return []
        return re.findall(r"[a-z0-9']+", text.lower())

    ref_words = _tokenize(expected_dialogue)
    if not ref_words:
        return {"transcript_wer": None, "transcript_word_overlap": None}

    hyp_words = _tokenize(heard_transcript)
    if not hyp_words:
        return {"transcript_wer": 1.0, "transcript_word_overlap": 0.0}

    m, n = len(ref_words), len(hyp_words)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev_diag = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            cost = 0 if ref_words[i - 1] == hyp_words[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev_diag + cost)
            prev_diag = temp

    wer = round(min(1.0, dp[n] / float(m)), 3)
    hyp_counts = Counter(hyp_words)
    matched = 0
    for w in ref_words:
        if hyp_counts[w] > 0:
            matched += 1
            hyp_counts[w] -= 1
    overlap = round(matched / float(m), 3)
    return {"transcript_wer": wer, "transcript_word_overlap": overlap}


def _has_audio_stream(path: str) -> bool:
    """Checks whether an MP4 file contains at least one audio stream via ffprobe."""
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
    """Normalizes multi-clip video/audio streams and stitches with 80ms xfade + equal-power acrossfade."""
    n = len(video_paths)
    has_audio_flags = [_has_audio_stream(p) for p in video_paths]
    any_have_audio = any(has_audio_flags)
    durations = [max(0.1, get_video_duration(p)) for p in video_paths]

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

    filter_parts: List[str] = []
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
    cmd.extend(["-filter_complex", filter_complex, "-map", "[outv]"])
    if any_have_audio:
        cmd.extend(["-map", "[outa]"])
    cmd.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18",
        "-video_track_timescale", "90000",
    ])
    if any_have_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
    cmd.extend(["-movflags", "+faststart", os.path.abspath(output_path)])

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def stitch_videos(
    video_paths: List[str],
    output_path: str,
    crossfade_seconds: float = 0.08,
) -> str:
    """Stitches multiple MP4 clips into a single master MP4 using synchronized 80ms xfade + acrossfade."""
    if not video_paths:
        raise ValueError("video_paths list cannot be empty")
    for path in video_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Input video file not found: {path}")

    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    expected_dur = sum(get_video_duration(p) for p in video_paths)
    any_have_audio = len(video_paths) > 1 and any(_has_audio_stream(p) for p in video_paths)

    if any_have_audio or (len(video_paths) > 1 and crossfade_seconds > 0.0):
        try:
            _stitch_filter_complex(video_paths, abs_out, crossfade_seconds=crossfade_seconds)
            return abs_out
        except subprocess.CalledProcessError as re_err:
            raise RuntimeError(
                f"FFMPEG filter_complex stitching failed: {re_err.stderr.decode('utf-8', errors='ignore')}"
            ) from re_err

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fp:
        manifest_path = fp.name
        for path in video_paths:
            fp.write(f"file '{os.path.abspath(path)}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", manifest_path, "-c", "copy", abs_out]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        actual_dur = get_video_duration(abs_out)
        if expected_dur > 0 and abs(actual_dur - expected_dur) > max(1.0, 0.1 * expected_dur):
            _stitch_filter_complex(video_paths, abs_out, crossfade_seconds=0.0)
    except subprocess.CalledProcessError as err:
        _stitch_filter_complex(video_paths, abs_out, crossfade_seconds=0.0)
    finally:
        if os.path.exists(manifest_path):
            os.remove(manifest_path)

    return abs_out


def ensure_riff_wav_bytes(
    audio_bytes: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sampwidth: int = 2,
) -> bytes:
    """Ensures audio bytes have a valid RIFF/WAVE header (wrapping raw L16 PCM if needed)."""
    if not audio_bytes:
        raise ValueError("Cannot wrap empty audio bytes into RIFF WAV.")
    raw = bytes(audio_bytes)
    if raw.startswith(b"RIFF") and b"WAVE" in raw[:16]:
        return raw
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(max(1, int(channels)))
        wf.setsampwidth(max(1, int(sampwidth)))
        wf.setframerate(max(8000, int(sample_rate)))
        wf.writeframes(raw)
    return buf.getvalue()


def get_wav_duration_sec(wav_bytes: bytes, fallback_sample_rate: int = 24000) -> Tuple[float, int]:
    """Returns `(duration_sec, sample_rate_hz)` for RIFF WAV or raw PCM audio bytes."""
    riff = ensure_riff_wav_bytes(wav_bytes, sample_rate=fallback_sample_rate)
    with wave.open(io.BytesIO(riff), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or fallback_sample_rate
        dur = round(frames / float(rate), 3) if rate > 0 else 0.0
    return dur, int(rate)


def split_wav_reference_chunks(
    wav_bytes: bytes,
    chunk_sec: float = 3.0,
    max_chunks: int = 5,
    min_tail_sec: float = 0.35,
) -> List[str]:
    """Slices a WAV track into up to `max_chunks` base64-encoded RIFF WAV clips (`<= chunk_sec` each).

    Gemini Omni Reference-to-Video (`task='reference_to_video'`) accepts up to 5 reference audio
    clips of up to ~3.0 seconds each (`type='audio'`, `mime_type='audio/wav'`).
    """
    riff = ensure_riff_wav_bytes(wav_bytes)
    with wave.open(io.BytesIO(riff), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate() or 24000
        total_frames = wf.getnframes()
        all_pcm = wf.readframes(total_frames)

    bytes_per_frame = max(1, nchannels * sampwidth)
    frames_per_chunk = max(1, int(round(max(0.5, float(chunk_sec)) * framerate)))
    min_tail_frames = max(1, int(round(max(0.05, float(min_tail_sec)) * framerate)))

    chunks_b64: List[str] = []
    offset_frames = 0
    while offset_frames < total_frames and len(chunks_b64) < max(1, int(max_chunks)):
        end_frames = min(total_frames, offset_frames + frames_per_chunk)
        seg_frames = end_frames - offset_frames
        if seg_frames < min_tail_frames and chunks_b64:
            break
        byte_start = offset_frames * bytes_per_frame
        byte_end = end_frames * bytes_per_frame
        seg_pcm = all_pcm[byte_start:byte_end]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out_wf:
            out_wf.setnchannels(nchannels)
            out_wf.setsampwidth(sampwidth)
            out_wf.setframerate(framerate)
            out_wf.writeframes(seg_pcm)
        chunks_b64.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        offset_frames = end_frames
    return chunks_b64


def mix_voiceover_onto_video(
    video_path: str,
    voice_wav_path: str,
    output_path: str,
    env_duck_gain: float = 0.28,
    apply_formant_notch: bool = True,
) -> str:
    """Mixes a dry TTS WAV voiceover onto a video clip with 1100 Hz vocal-formant notch & ducking.

    Normalizes voiceover loudness (`-16 LUFS`, `48 kHz` stereo AAC) and locks output duration
    strictly to `video_path` (`-c:v copy`). Safe when `output_path` equals `video_path`.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not os.path.exists(voice_wav_path):
        raise FileNotFoundError(f"Voice WAV file not found: {voice_wav_path}")

    abs_vid = os.path.abspath(video_path)
    abs_wav = os.path.abspath(voice_wav_path)
    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)

    vid_dur = max(0.5, get_video_duration(abs_vid))
    has_env = _has_audio_stream(abs_vid)
    duck = max(0.0, min(1.0, float(env_duck_gain)))

    vo_chain = (
        f"[1:a:0]loudnorm=I=-16:TP=-1.5:LRA=11,"
        f"aresample=48000,pan=stereo|c0=c0|c1=c0,"
        f"apad,atrim=0:{vid_dur:.3f},asetpts=PTS-STARTPTS"
    )
    if has_env:
        notch = "bandreject=f=1100:width_type=h:w=1800," if apply_formant_notch else ""
        env_chain = (
            f"[0:a:0]{notch}volume={duck:.3f},"
            f"aresample=48000,aformat=channel_layouts=stereo,"
            f"apad,atrim=0:{vid_dur:.3f},asetpts=PTS-STARTPTS[env]"
        )
        filter_complex = (
            f"{env_chain};{vo_chain}[vo];"
            f"[env][vo]amix=inputs=2:duration=first:dropout_transition=0.08:normalize=0[aout]"
        )
    else:
        filter_complex = f"{vo_chain}[aout]"

    in_place = abs_out == abs_vid
    tmp_out = abs_out + ".mux_tmp.mp4" if in_place else abs_out
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        abs_vid,
        "-i",
        abs_wav,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        tmp_out,
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if in_place:
            os.replace(tmp_out, abs_out)
    finally:
        if in_place and os.path.exists(tmp_out):
            os.remove(tmp_out)
    return abs_out


def _read_media_tile_bgr(path: str, tile_w: int, tile_h: int) -> np.ndarray:
    """Loads an image or MP4 midpoint frame and center-crops/resizes to `(tile_h, tile_w, 3)` BGR."""
    img: Optional[np.ndarray] = None
    if path and os.path.exists(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
            cap = cv2.VideoCapture(path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total > 2:
                cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                img = frame
        else:
            loaded = cv2.imread(path, cv2.IMREAD_COLOR)
            if loaded is not None:
                img = loaded

    if img is None or img.size == 0:
        canvas = np.full((tile_h, tile_w, 3), (43, 29, 20), dtype=np.uint8)
        cv2.putText(
            canvas,
            "MISSING ASSET",
            (max(16, tile_w // 4), tile_h // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (180, 190, 210),
            2,
            cv2.LINE_AA,
        )
        return canvas

    src_h, src_w = img.shape[:2]
    scale = max(tile_w / float(max(1, src_w)), tile_h / float(max(1, src_h)))
    resized_w = max(tile_w, int(round(src_w * scale)))
    resized_h = max(tile_h, int(round(src_h * scale)))
    resized = cv2.resize(img, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    x0 = max(0, (resized_w - tile_w) // 2)
    y0 = max(0, (resized_h - tile_h) // 2)
    return resized[y0:y0 + tile_h, x0:x0 + tile_w].copy()


def build_contact_sheet(
    items: List[Dict[str, Any]],
    output_path: str,
    cols: int = 3,
    tile_w: int = 480,
    tile_h: int = 270,
    gutter: int = 8,
) -> str:
    """Renders a labeled multi-tile PNG contact sheet for HITL Gate 1 (plates) and Gate 2 (QA).

    Each item dict accepts: `path` (image or MP4 path), `label` (str), optional `score` (float),
    and optional `status` ('PASSED', 'ESCALATED', 'PLATE', etc.).
    """
    if not items:
        raise ValueError("build_contact_sheet requires at least one item.")
    cols = max(1, min(int(cols), len(items)))
    rows = (len(items) + cols - 1) // cols
    tile_w = max(160, int(tile_w))
    tile_h = max(90, int(tile_h))
    gutter = max(2, int(gutter))

    sheet_w = cols * tile_w + (cols + 1) * gutter
    sheet_h = rows * tile_h + (rows + 1) * gutter
    sheet = np.full((sheet_h, sheet_w, 3), (28, 20, 15), dtype=np.uint8)

    for idx, item in enumerate(items):
        r = idx // cols
        c = idx % cols
        tile = _read_media_tile_bgr(str(item.get("path") or ""), tile_w, tile_h)

        # Top translucent HUD bar
        bar_h = min(36, max(26, tile_h // 8))
        overlay = tile.copy()
        cv2.rectangle(overlay, (0, 0), (tile_w, bar_h), (18, 18, 22), -1)
        cv2.addWeighted(overlay, 0.76, tile, 0.24, 0, tile)

        score = item.get("score")
        status = str(item.get("status") or "").upper()
        if score is not None:
            try:
                sc_f = float(score)
                accent_bgr = (94, 197, 34) if sc_f >= 0.80 else (68, 85, 239)
            except (TypeError, ValueError):
                accent_bgr = (235, 145, 55)
        elif status in ("PASSED", "OK", "APPROVED"):
            accent_bgr = (94, 197, 34)
        elif status in ("ESCALATED", "FAILED", "REATTEMPT_REQUIRED", "HUMAN_REVIEW_REQUIRED"):
            accent_bgr = (68, 85, 239)
        else:
            accent_bgr = (235, 145, 55)

        cv2.rectangle(tile, (0, 0), (6, bar_h), accent_bgr, -1)
        raw_label = str(item.get("label") or f"Tile {idx + 1}")
        if score is not None and f"{score}" not in raw_label:
            try:
                raw_label = f"{raw_label} | {float(score):.2f}"
            except (TypeError, ValueError):
                pass
        if status and status not in raw_label.upper():
            raw_label = f"{raw_label} [{status}]"
        clean_ascii = raw_label.encode("ascii", errors="ignore").decode("ascii")[:52]
        cv2.putText(
            tile,
            clean_ascii,
            (14, int(bar_h * 0.70)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (248, 250, 252),
            1,
            cv2.LINE_AA,
        )

        y_off = gutter + r * (tile_h + gutter)
        x_off = gutter + c * (tile_w + gutter)
        sheet[y_off:y_off + tile_h, x_off:x_off + tile_w] = tile

    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    if not cv2.imwrite(abs_out, sheet):
        raise RuntimeError(f"Failed to write contact sheet PNG to {abs_out}")
    return abs_out


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone OpenCV + FFMPEG media utilities for multi-shot video generation."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_frame = sub.add_parser("extract-frame", help="Extract first or last PNG frame from an MP4.")
    p_frame.add_argument("--video", required=True, help="Input MP4 path.")
    p_frame.add_argument("--output", required=True, help="Output PNG path.")
    p_frame.add_argument("--position", choices=["first", "last"], default="last")

    p_tail = sub.add_parser("extract-tail", help="Extract trailing N-second subclip for video_extend.")
    p_tail.add_argument("--video", required=True, help="Input MP4 path.")
    p_tail.add_argument("--output", required=True, help="Output tail MP4 path.")
    p_tail.add_argument("--seconds", type=float, default=5.0)
    p_tail.add_argument("--strip-audio", action="store_true")

    p_trim = sub.add_parser("trim-seam", help="Trim echoed prefix from extended MP4 using OpenCV MAE alignment.")
    p_trim.add_argument("--video", required=True, help="Raw extended MP4 path.")
    p_trim.add_argument("--output", required=True, help="Trimmed MP4 output path.")
    p_trim.add_argument("--trim-seconds", type=float, default=5.0)
    p_trim.add_argument("--expected-ext-seconds", type=float, default=10.0)
    p_trim.add_argument("--ref-last-frame", help="Optional PNG path of prior shot's last frame.")

    p_r2v = sub.add_parser("check-r2v", help="Detect if Frame 0 locked onto a #FFFFFF reference image.")
    p_r2v.add_argument("--video", required=True, help="Generated R2V MP4 path.")
    p_r2v.add_argument("--reference", required=True, help="Reference PNG/JPEG path.")
    p_r2v.add_argument("--threshold", type=float, default=12.0)

    p_seam = sub.add_parser("check-seam", help="Check post-seam jump-cut MAE against prior last frame.")
    p_seam.add_argument("--video", required=True, help="Trimmed/chained MP4 path.")
    p_seam.add_argument("--ref-last-frame", required=True, help="Prior shot terminal PNG path.")
    p_seam.add_argument("--max-mae", type=float, default=28.0)
    p_seam.add_argument("--frames", type=int, default=5)

    p_aud = sub.add_parser("analyze-audio", help="Measure duration, RMS dBFS, and trailing speech cutoff.")
    p_aud.add_argument("--video", required=True, help="Input MP4 path.")
    p_aud.add_argument("--tail-sec", type=float, default=0.20)

    p_wer = sub.add_parser("wer", help="Compute word-level Levenshtein WER and overlap.")
    p_wer.add_argument("--expected", required=True)
    p_wer.add_argument("--heard", required=True)

    p_stitch = sub.add_parser("stitch", help="Stitch multiple MP4 clips with 80ms xfade + acrossfade.")
    p_stitch.add_argument("--videos", nargs="+", required=True, help="Ordered MP4 clip paths.")
    p_stitch.add_argument("--output", required=True, help="Output stitched master MP4 path.")
    p_stitch.add_argument("--crossfade", type=float, default=0.08, help="Crossfade seconds (0 to hard-cut).")

    p_mux = sub.add_parser(
        "mux-voiceover",
        help="Mix a dry TTS WAV voiceover onto an MP4 clip with 1100 Hz vocal-formant notch & ducking.",
    )
    p_mux.add_argument("--video", required=True, help="Input MP4 path.")
    p_mux.add_argument("--voice", required=True, help="Input TTS WAV path.")
    p_mux.add_argument("--output", required=True, help="Output MP4 path (may equal --video).")
    p_mux.add_argument("--duck-gain", type=float, default=0.28, help="Environmental bed gain (default: 0.28).")
    p_mux.add_argument("--no-formant-notch", action="store_true", help="Disable 1100 Hz bandreject notch filter.")

    p_cs = sub.add_parser("contact-sheet", help="Render a labeled multi-tile PNG contact sheet for plates or QA.")
    p_cs.add_argument("--inputs", nargs="+", required=True, help="Ordered PNG/JPG/MP4 paths.")
    p_cs.add_argument("--labels", nargs="*", default=None, help="Optional per-tile label strings.")
    p_cs.add_argument("--scores", nargs="*", type=float, default=None, help="Optional per-tile numeric scores.")
    p_cs.add_argument("--cols", type=int, default=3, help="Grid columns (default: 3).")
    p_cs.add_argument("--tile-width", type=int, default=480)
    p_cs.add_argument("--tile-height", type=int, default=270)
    p_cs.add_argument("--output", required=True, help="Output PNG contact sheet path.")

    p_chunk = sub.add_parser("chunk-wav", help="Slice a WAV file into <= 3.0s RIFF WAV chunks for Omni R2V audio refs.")
    p_chunk.add_argument("--audio", required=True, help="Input WAV path.")
    p_chunk.add_argument("--chunk-sec", type=float, default=3.0)
    p_chunk.add_argument("--max-chunks", type=int, default=5)
    p_chunk.add_argument("--output-dir", default=None, help="Optional directory to write chunk_k.wav files.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "extract-frame":
        fn = extract_first_frame if args.position == "first" else extract_last_frame
        fn(args.video, args.output)
        print(json.dumps({"status": "ok", "position": args.position, "output": os.path.abspath(args.output)}))
        return 0

    if args.command == "extract-tail":
        _, actual_dur = extract_video_tail(
            args.video,
            tail_seconds=args.seconds,
            strip_audio=args.strip_audio,
            output_video_path=args.output,
        )
        print(json.dumps({
            "status": "ok",
            "output": os.path.abspath(args.output),
            "actual_duration_sec": round(actual_dur, 3),
            "strip_audio": bool(args.strip_audio),
        }))
        return 0

    if args.command == "trim-seam":
        with open(args.video, "rb") as fp:
            raw_bytes = fp.read()
        ref_b64 = encode_image_file_b64(args.ref_last_frame) if args.ref_last_frame else None
        trimmed = trim_video_prefix(
            raw_bytes,
            trim_seconds=args.trim_seconds,
            expected_extension_seconds=args.expected_ext_seconds,
            reference_last_frame_b64=ref_b64,
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "wb") as fp:
            fp.write(trimmed)
        print(json.dumps({
            "status": "ok",
            "output": os.path.abspath(args.output),
            "duration_sec": round(get_video_duration(args.output), 3),
        }))
        return 0

    if args.command == "check-r2v":
        ref_b64 = encode_image_file_b64(args.reference)
        locked, mae = detect_r2v_first_frame_lock(ref_b64, args.video, mae_threshold=args.threshold)
        print(json.dumps({"locked_to_reference": locked, "frame0_mae": mae, "threshold": args.threshold}))
        return 0

    if args.command == "check-seam":
        ref_b64 = encode_image_file_b64(args.ref_last_frame)
        has_jump, f0_mae, peak_mae = detect_seam_jump_cut(
            ref_b64, args.video, max_mae=args.max_mae, check_frames=args.frames
        )
        print(json.dumps({"has_jump_cut": has_jump, "seam_mae": f0_mae, "peak_early_mae": peak_mae}))
        return 0

    if args.command == "analyze-audio":
        print(json.dumps(analyze_clip_audio_tail(args.video, tail_sec=args.tail_sec)))
        return 0

    if args.command == "wer":
        print(json.dumps(compute_transcript_metrics(args.expected, args.heard)))
        return 0

    if args.command == "stitch":
        out = stitch_videos(args.videos, args.output, crossfade_seconds=args.crossfade)
        print(json.dumps({
            "status": "ok",
            "output": out,
            "duration_sec": round(get_video_duration(out), 3),
            "clips_count": len(args.videos),
        }))
        return 0

    if args.command == "mux-voiceover":
        out = mix_voiceover_onto_video(
            video_path=args.video,
            voice_wav_path=args.voice,
            output_path=args.output,
            env_duck_gain=args.duck_gain,
            apply_formant_notch=not bool(args.no_formant_notch),
        )
        print(json.dumps({
            "status": "ok",
            "output": out,
            "duration_sec": round(get_video_duration(out), 3),
        }))
        return 0

    if args.command == "contact-sheet":
        labels = args.labels or []
        scores = args.scores or []
        items = []
        for idx, inp in enumerate(args.inputs):
            lbl = labels[idx] if idx < len(labels) else os.path.basename(inp)
            sc = scores[idx] if idx < len(scores) else None
            items.append({"path": inp, "label": lbl, "score": sc})
        out = build_contact_sheet(
            items=items,
            output_path=args.output,
            cols=args.cols,
            tile_w=args.tile_width,
            tile_h=args.tile_height,
        )
        print(json.dumps({"status": "ok", "output": out, "tiles": len(items)}))
        return 0

    if args.command == "chunk-wav":
        with open(args.audio, "rb") as fp:
            raw_wav = fp.read()
        dur_sec, sr = get_wav_duration_sec(raw_wav)
        chunks_b64 = split_wav_reference_chunks(
            raw_wav,
            chunk_sec=args.chunk_sec,
            max_chunks=args.max_chunks,
        )
        written_files: List[str] = []
        if args.output_dir:
            abs_dir = os.path.abspath(args.output_dir)
            os.makedirs(abs_dir, exist_ok=True)
            for idx, b64_c in enumerate(chunks_b64):
                cp = os.path.join(abs_dir, f"chunk_{idx + 1}.wav")
                with open(cp, "wb") as fp:
                    fp.write(base64.b64decode(b64_c))
                written_files.append(cp)
        print(json.dumps({
            "status": "ok",
            "duration_sec": dur_sec,
            "sample_rate_hz": sr,
            "chunks_count": len(chunks_b64),
            "chunk_files": written_files,
        }))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
