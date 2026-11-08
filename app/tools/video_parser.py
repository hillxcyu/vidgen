import base64
import os
import subprocess
import tempfile
from typing import Optional, List, Any, Dict
import cv2


def extract_first_frame(video_path: str, output_image_path: Optional[str] = None) -> str:
    """Extracts the initial (first) frame of an MP4 video file and returns it as a base64 encoded PNG string.
    Optionally saves the extracted frame to disk if output_image_path is provided.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError(f"Failed to read the first frame from: {video_path}")

    if output_image_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
        cv2.imwrite(output_image_path, frame)

    success, buffer = cv2.imencode(".png", frame)
    if not success:
        raise RuntimeError("Failed to encode frame as PNG")

    return base64.b64encode(buffer.tobytes()).decode("utf-8")


def extract_last_frame(video_path: str, output_image_path: Optional[str] = None) -> str:
    """Extracts the final frame of an MP4 video file and returns it as a base64 encoded string.
    Optionally saves the extracted frame to disk if output_image_path is provided.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        raise ValueError(f"Video file has no valid frames: {video_path}")

    # Seek to last frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError(f"Failed to read the last frame from: {video_path}")

    if output_image_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
        cv2.imwrite(output_image_path, frame)

    success, buffer = cv2.imencode(".png", frame)
    if not success:
        raise RuntimeError("Failed to encode frame as PNG")

    return base64.b64encode(buffer.tobytes()).decode("utf-8")


def extract_keyframes(video_path: str, num_keyframes: int = 3) -> List[str]:
    """Extracts evenly spaced keyframe image samples across an MP4 video file
    and returns a list of base64 PNG encoded strings for multi-frame subject drift auditing.
    """
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []

    sample_indices = [
        max(0, min(total_frames - 1, int(total_frames * (i + 1) / (num_keyframes + 1))))
        for i in range(num_keyframes)
    ]

    keyframes_b64 = []
    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            success, buffer = cv2.imencode(".png", frame)
            if success:
                keyframes_b64.append(base64.b64encode(buffer.tobytes()).decode("utf-8"))

    cap.release()
    return keyframes_b64


def extract_audio_reference(video_path: str, output_wav_path: Optional[str] = None) -> Optional[str]:
    """Extracts the audio track from an MP4 video file as a WAV audio file using ffmpeg
    and returns it as a base64 encoded string for voice reference chaining across shots.
    """
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return None

    cleanup = False
    if output_wav_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        output_wav_path = tmp.name
        tmp.close()
        cleanup = True

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        output_wav_path
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if os.path.exists(output_wav_path) and os.path.getsize(output_wav_path) > 0:
            with open(output_wav_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            if cleanup and os.path.exists(output_wav_path):
                os.remove(output_wav_path)
            return b64
    except Exception as e:
        print(f"[NOTICE] Audio extraction via ffmpeg from {video_path} encountered: {e}")
        if cleanup and os.path.exists(output_wav_path):
            os.remove(output_wav_path)
        return None

    return None


def _resolve_media_processing_enum(media_processing: Any):
    """Normalizes string or enum media_processing values to Google GenAI MediaProcessing enum."""
    from google.genai import types

    if isinstance(media_processing, types.MediaProcessing):
        return media_processing
    norm = str(media_processing or "agentic").strip().upper()
    if norm in ("AGENTIC", "MEDIAPROCESSING.AGENTIC"):
        return types.MediaProcessing.AGENTIC
    if norm in ("STATIC", "MEDIAPROCESSING.STATIC"):
        return types.MediaProcessing.STATIC
    return media_processing


def extract_avu_usage_telemetry(resp: Any) -> Dict[str, Any]:
    """Extracts Agentic Video Understanding (google:load_video) token telemetry from GenerateContentResponse."""
    um = getattr(resp, "usage_metadata", None) if resp is not None else None
    if um is None:
        return {}
    raw_tool = getattr(um, "tool_use_prompt_token_count", None)
    raw_prompt = getattr(um, "prompt_token_count", None)
    raw_total = getattr(um, "total_token_count", None)
    tool_tokens = int(raw_tool) if isinstance(raw_tool, (int, float)) else 0
    prompt_tokens = int(raw_prompt) if isinstance(raw_prompt, (int, float)) else 0
    total_tokens = int(raw_total) if isinstance(raw_total, (int, float)) else 0
    if tool_tokens == 0 and prompt_tokens == 0 and total_tokens == 0:
        return {}
    return {
        "avu_active": tool_tokens > 0,
        "avu_tool_use_tokens": tool_tokens,
        "avu_prompt_tokens": prompt_tokens,
        "avu_total_tokens": total_tokens,
    }


def create_agentic_video_part(
    video_path_or_uri: str,
    video_bytes: Optional[bytes] = None,
    media_processing: Any = "agentic"
):
    """Builds a Google GenAI Part with explicit media_processing (types.MediaProcessing.AGENTIC or STATIC)
    for advanced multimodal video understanding (invoking server-side google:load_video on Gemini 3.8 Flash).

    Supports:
    - GCS file URIs: gs://bucket/path/to/clip.mp4
    - GCS HTTPS showcase URLs: https://storage.googleapis.com/... or https://storage.cloud.google.com/... (converted to gs://)
    - Raw byte buffers (inline_data Blob with media_processing)
    - Local file paths (reads bytes into inline_data Blob with media_processing)
    """
    from google.genai import types

    resolved_mp = _resolve_media_processing_enum(media_processing)

    # 1. Normalize GCS HTTPS showcase URLs to native gs:// URI
    file_uri = None
    if video_path_or_uri.startswith("gs://"):
        file_uri = video_path_or_uri
    elif video_path_or_uri.startswith("https://storage.googleapis.com/"):
        file_uri = "gs://" + video_path_or_uri.removeprefix("https://storage.googleapis.com/").split("?", 1)[0]
    elif video_path_or_uri.startswith("https://storage.cloud.google.com/"):
        file_uri = "gs://" + video_path_or_uri.removeprefix("https://storage.cloud.google.com/").split("?", 1)[0]

    if file_uri:
        return types.Part(
            file_data=types.FileData(file_uri=file_uri, mime_type="video/mp4"),
            media_processing=resolved_mp
        )

    # 2. Local bytes or file
    data = video_bytes
    if not data and os.path.exists(video_path_or_uri) and os.path.isfile(video_path_or_uri):
        try:
            with open(video_path_or_uri, "rb") as fp:
                data = fp.read()
        except Exception:
            pass

    if data:
        return types.Part(
            inline_data=types.Blob(data=data, mime_type="video/mp4"),
            media_processing=resolved_mp
        )

    # 3. Fallback to file_data with original URI
    return types.Part(
        file_data=types.FileData(file_uri=video_path_or_uri, mime_type="video/mp4"),
        media_processing=resolved_mp
    )


def get_video_duration(video_path: str) -> float:
    """Returns the duration of a video file in seconds using OpenCV."""
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


def extract_video_tail(
    video_path: str,
    tail_seconds: float = 5.0,
    strip_audio: bool = False,
    output_video_path: Optional[str] = None,
) -> tuple[str, float]:
    """Extracts the trailing `tail_seconds` subclip of an MP4 video as base64 MP4 and returns `(b64_str, actual_duration_s)`.

    Keeps the original audio track intact by default (`strip_audio=False`) so Gemini Omni
    `task='extend'` conditions on Shot k-1's room tone, musical bed, and speaker voice timbre
    for seamless audio continuation across 10s boundaries.
    """
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
        with open(output_video_path, "rb") as f:
            b64_str = base64.b64encode(f.read()).decode("utf-8")
        return b64_str, actual_dur
    finally:
        if cleanup and output_video_path and os.path.exists(output_video_path):
            os.remove(output_video_path)


def _find_best_seam_frame_index(
    video_path: str,
    trim_seconds: float,
    reference_last_frame_b64: Optional[str],
) -> tuple[int, float, float]:
    """Finds the exact frame index in `video_path` matching `reference_last_frame_b64` around `trim_seconds`.

    Returns `(start_frame_idx, start_time_sec, match_mae)`.
    """
    import numpy as np

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
        ref_bytes = base64.b64decode(reference_last_frame_b64)
        ref_arr = np.frombuffer(ref_bytes, dtype=np.uint8)
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
    return best_idx, best_idx / fps, best_mae


def detect_seam_jump_cut(
    reference_last_frame_b64: Optional[str],
    trimmed_video_path: str,
    max_mae: float = 28.0,
    check_frames: int = 5,
) -> tuple[bool, float, float]:
    """Checks the first `check_frames` frames of a trimmed `video_extend` shot against the previous shot's last frame.

    Returns `(has_jump_cut, frame0_mae, worst_mae_in_window)` so the pipeline can automatically retry
    if Omni inserted a hard scene switch right after the echoed tail.
    """
    import numpy as np

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
) -> tuple[bool, float]:
    """Detects if Frame 0 of an R2V shot erroneously locked onto the literal reference image as <FIRST_FRAME>.

    Returns `(is_locked_to_ref, frame0_mae)`. Lower MAE (< `mae_threshold`, e.g. 2.9-4.8 on #FFFFFF studio refs)
    indicates the model treated the reference portrait as a literal opening frame instead of R2V scene synthesis.
    """
    import numpy as np

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


def trim_video_prefix(
    video_bytes: bytes,
    trim_seconds: float,
    expected_extension_seconds: float = 10.0,
    reference_last_frame_b64: Optional[str] = None,
) -> bytes:
    """Trims the echoed leading overlap from an extended MP4 clip using exact OpenCV seam-frame alignment.

    When `reference_last_frame_b64` (Shot k-1's last frame) is provided, scans around `trim_seconds`
    to find the exact echoed terminal frame `best_idx` (minimum pixel MAE) and trims via frame-exact
    `select='gte(n,best_idx)'` + `atrim=start=...` so Frame 0 of Shot k is pixel-locked to Shot k-1's last frame.
    """
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

        start_idx, start_sec, match_mae = _find_best_seam_frame_index(
            in_path, trim_seconds, reference_last_frame_b64
        )
        if match_mae >= 0:
            print(
                f"[VideoExtend Seam Lock] Matched echoed anchor at frame #{start_idx} "
                f"(t={start_sec:.3f}s, MAE={match_mae:.2f})"
            )

        # Probe whether input clip contains an audio stream
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
            "ffmpeg", "-y",
            "-i", in_path,
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
            with open(out_path, "rb") as f:
                return f.read()
        return video_bytes
    except Exception as e:
        print(f"[NOTICE] trim_video_prefix skipped due to: {e}")
        return video_bytes
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                os.remove(p)


def decode_valid_image_b64(b64_str: Optional[str]) -> Optional[tuple]:
    """Decodes a base64 image string and validates image magic bytes (PNG/JPEG/WebP).

    Returns (raw_bytes, mime_type) if valid, else None (gracefully ignoring mock test strings).
    """
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


def extract_labeled_audit_keyframes(video_path: str) -> List[tuple]:
    """Extracts high-resolution boundary and mid-shot PNG stills with explicit temporal labels.

    Returns a list of (label, png_bytes) tuples for KEY FRAME A (t=0.00s), KEY FRAME M (mid-shot),
    and KEY FRAME B (terminal frame) to pair with Agentic Video Understanding payloads.
    """
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

    results: List[tuple] = []
    seen_indices = set()
    for idx, label in targets:
        if idx in seen_indices and len(targets) > 1:
            continue
        seen_indices.add(idx)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            ok, buf = cv2.imencode(".png", frame)
            if ok:
                results.append((label, buf.tobytes()))
    cap.release()
    return results


def analyze_clip_audio_tail(video_path: str, tail_sec: float = 0.20) -> dict:
    """Computes deterministic clip duration and RMS dBFS energy in mid-clip vs. trailing window (e.g. 9.8s-10.0s).

    Detects active speech cutoffs when high vocal RMS energy persists right up to the final 0.20s boundary.
    """
    import math
    import struct
    import wave

    clip_duration = round(get_video_duration(video_path), 2)
    telemetry = {
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
        audio_dur = n_frames / float(sr)
        if clip_duration <= 0.0:
            telemetry["clip_duration_sec"] = round(audio_dur, 2)

        def _rms_db(chunk) -> float:
            if not chunk:
                return -90.0
            mean_sq = sum(s * s for s in chunk) / float(len(chunk))
            rms = math.sqrt(mean_sq) / 32768.0
            if rms <= 1e-9:
                return -90.0
            return round(20.0 * math.log10(rms), 1)

        tail_samples_count = max(1, int(round(tail_sec * sr)))
        tail_chunk = samples[-tail_samples_count:]
        trailing_db = _rms_db(tail_chunk)

        mid_start = min(len(samples), int(round(0.5 * sr)))
        mid_end = max(mid_start + 1, len(samples) - int(round(0.5 * sr)))
        mid_chunk = samples[mid_start:mid_end] if mid_end > mid_start else samples
        mid_db = _rms_db(mid_chunk)

        telemetry["mid_rms_db"] = mid_db
        telemetry["trailing_rms_db"] = trailing_db
        # High trailing vocal energy (> -26 dBFS) without decay relative to mid-clip indicates an abrupt speech cutoff
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
) -> dict:
    """Computes deterministic word-level Levenshtein WER and recall word-overlap between expected and heard dialogue."""
    import re

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

    # Standard Levenshtein word-level edit distance
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

    # Recall word-overlap (accounting for multiset counts)
    from collections import Counter
    hyp_counts = Counter(hyp_words)
    matched = 0
    for w in ref_words:
        if hyp_counts[w] > 0:
            matched += 1
            hyp_counts[w] -= 1
    overlap = round(matched / float(m), 3)
    return {"transcript_wer": wer, "transcript_word_overlap": overlap}
