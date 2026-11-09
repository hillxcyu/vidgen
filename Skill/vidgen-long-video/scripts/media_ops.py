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

    return 1


if __name__ == "__main__":
    sys.exit(main())
