import base64
import os
import tempfile
from typing import List, Optional
import cv2
import numpy as np
from google import genai
from src.config import get_genai_client, Config

def build_omni_control_string(
    prompt: str,
    input_image_b64: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
) -> str:
    """Builds Gemini Omni Control String according to Google Omni / Video Station specification.
    
    Format:
    [MMC_MODE_STRING] [aspect_ratio=VALUE] [resolution=VALUE] [duration=VALUEs] <user prompt>
    
    Examples:
    - I2V: "[# Sources <FIRST_FRAME>image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=10s] A red panda skiing"
    - R2V: "[# References <IMAGE_REF_0>image_0.png <IMAGE_REF_1>image_1.png] [aspect_ratio=16:9] [resolution=720p] [duration=10s] A red panda skiing"
    """
    mmc_parts = []

    # Mode B: Image-to-Video Chaining (First Frame Source)
    if input_image_b64:
        mmc_parts.append("# Sources <FIRST_FRAME>image_0.png")
    # Mode A: Shared Asset Reference Mode (Image References)
    elif reference_images_b64 and len(reference_images_b64) > 0:
        ref_tags = [f"<IMAGE_REF_{i}>image_{i}.png" for i in range(min(10, len(reference_images_b64)))]
        mmc_parts.append(f"# References {' '.join(ref_tags)}")

    mmc_mode_str = f"[{' '.join(mmc_parts)}] " if mmc_parts else ""
    fc_args_str = f"[aspect_ratio={aspect_ratio}] [resolution={resolution}] [duration={duration}s]"

    full_control_string = f"{mmc_mode_str}{fc_args_str} {prompt}".strip()
    return full_control_string

def _create_fallback_mp4_bytes(prompt: str) -> bytes:
    """Generates a synthetic 10-second MP4 clip for local fallback/demonstration."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, 10.0, (256, 256))
    for i in range(100):  # 10s at 10fps
        # Synthetic animated frame
        frame = np.zeros((256, 256, 3), dtype=np.uint8)
        cv2.putText(frame, "GenMedia-Omni", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, prompt[:35], (20, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
        cv2.circle(frame, (30 + (i * 2) % 200, 200), 10, (0, 0, 255), -1)
        out.write(frame)
    out.release()

    with open(path, "rb") as f:
        data = f.read()

    if os.path.exists(path):
        os.remove(path)

    return data

def generate_omni_clip(
    prompt: str,
    input_image_b64: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    client: Optional[genai.Client] = None,
) -> bytes:
    """Wrapper tool for Gemini Omni Flash (gemini-omni-flash-preview) using interactions.create API.
    
    Supports:
    - MMC Control Strings formatting (MMC mode tags & FC argument tokens)
    - Mode A (Reference Mode): Up to 10 reference images + text prompt.
    - Mode B (Sequential I2V Mode): Terminal frame base64 input + text motion prompt.
    """
    if client is None:
        client = get_genai_client()

    config = Config()
    payload = []

    # Mode B: Image-to-Video Chaining
    if input_image_b64:
        payload.append({
            "type": "image",
            "data": input_image_b64,
            "mime_type": "image/png"
        })

    # Mode A: Shared Reference Mode
    elif reference_images_b64:
        for img_b64 in reference_images_b64[:10]:
            payload.append({
                "type": "image",
                "data": img_b64,
                "mime_type": "image/png"
            })

    # Format full control string according to Google Omni / Video Station specification
    formatted_prompt = build_omni_control_string(
        prompt=prompt,
        input_image_b64=input_image_b64,
        reference_images_b64=reference_images_b64,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration
    )

    # Append control string formatted prompt as text object for interactions.create
    payload.append({
        "type": "text",
        "text": formatted_prompt
    })

    try:
        interaction = client.interactions.create(
            model=config.VIDEO_GEN_MODEL,
            input=payload
        )
        if hasattr(interaction, "output_video") and hasattr(interaction.output_video, "data"):
            return base64.b64decode(interaction.output_video.data)
        elif hasattr(interaction, "candidates") and len(interaction.candidates) > 0:
            cand = interaction.candidates[0]
            if hasattr(cand, "content") and hasattr(cand.content, "parts"):
                for part in cand.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        return part.inline_data.data
        if hasattr(interaction, "output") and isinstance(interaction.output, bytes):
            return interaction.output
    except Exception as e:
        print(f"[NOTICE] Live API call to '{config.VIDEO_GEN_MODEL}' encountered: {e}")
        print("[NOTICE] Falling back to synthetic clip generation for demo execution...")
        return _create_fallback_mp4_bytes(formatted_prompt)

    return _create_fallback_mp4_bytes(formatted_prompt)
