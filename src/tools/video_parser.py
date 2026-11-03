import base64
import os
import subprocess
import tempfile
from typing import Optional, List
import cv2

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


def create_agentic_video_part(
    video_path_or_uri: str,
    video_bytes: Optional[bytes] = None,
    media_processing: str = "agentic"
):
    """Builds a Google GenAI Part with explicit media_processing ('agentic' or 'static')
    for advanced multimodal video understanding.

    Supports:
    - GCS file URIs: gs://bucket/path/to/clip.mp4
    - GCS HTTPS showcase URLs: https://storage.googleapis.com/bucket/path/to/clip.mp4 (converted to gs://)
    - Raw byte buffers (inline_data Blob with media_processing)
    - Local file paths (reads bytes into inline_data Blob with media_processing)
    """
    from google.genai import types

    # 1. Normalize GCS HTTPS showcase URLs to native gs:// URI
    file_uri = None
    if video_path_or_uri.startswith("gs://"):
        file_uri = video_path_or_uri
    elif video_path_or_uri.startswith("https://storage.googleapis.com/"):
        file_uri = "gs://" + video_path_or_uri.removeprefix("https://storage.googleapis.com/")

    if file_uri:
        return types.Part(
            file_data=types.FileData(file_uri=file_uri, mime_type="video/mp4"),
            media_processing=media_processing
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
            media_processing=media_processing
        )

    # 3. Fallback to file_data with original URI
    return types.Part(
        file_data=types.FileData(file_uri=video_path_or_uri, mime_type="video/mp4"),
        media_processing=media_processing
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
    """Extracts the trailing `tail_seconds` subclip of an MP4 video as base64 MP4 and returns `(b64_str, actual_duration_s)`."""
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
    """Finds the exact frame index in `video_path` matching `reference_last_frame_b64` around `trim_seconds`."""
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
    return best_idx, best_idx / fps, best_mae


def detect_seam_jump_cut(
    reference_last_frame_b64: Optional[str],
    trimmed_video_path: str,
    max_mae: float = 28.0,
    check_frames: int = 5,
) -> tuple[bool, float, float]:
    """Checks the first `check_frames` frames of a trimmed `video_extend` shot against the previous shot's last frame."""
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
    """Detects if Frame 0 of an R2V shot erroneously locked onto the literal reference image as <FIRST_FRAME>."""
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
    """Trims the echoed leading overlap from an extended MP4 clip using exact OpenCV seam-frame alignment."""
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
