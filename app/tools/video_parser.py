import base64
import os
import subprocess
import tempfile
from typing import Optional, List
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
