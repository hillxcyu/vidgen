import base64
import os
from typing import Optional
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
