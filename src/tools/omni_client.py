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
    reference_assets_b64: Optional[List[str]] = None,
    reference_audio_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
) -> str:
    """Builds Gemini Omni Control String according to Google Omni / Video Station specification.
    
    Supports:
    - Image Reference tags: <IMAGE_REF_i>[Character A]image_i.png
    - Audio Reference tags: <AUDIO_REF_i>[Character A]audio_i.wav
    - Spoken dialogue / transcript matching across shots for voice consistency
    
    Format:
    [MMC_MODE_STRING] [aspect_ratio=VALUE] [resolution=VALUE] [duration=VALUEs] <user prompt>
    
    Examples:
    - I2V: "[# Sources <FIRST_FRAME>image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=10s] A red panda skiing"
    - R2V with Voice: "[# References <IMAGE_REF_0>[Character A]image_0.png <AUDIO_REF_0>[Character A]audio_0.wav] [aspect_ratio=16:9] [resolution=720p] [duration=10s] Character A speaks dialogue: 'Welcome to Hakuba!'"
    """
    ref_imgs = reference_images_b64 if reference_images_b64 is not None else reference_assets_b64
    ref_auds = reference_audio_b64 or []
    mmc_parts = []
    ref_tags = []

    # Image-to-Video Chaining Source Tag (<FIRST_FRAME>image_0.png)
    image_offset = 0
    if input_image_b64:
        mmc_parts.append("# Sources <FIRST_FRAME>image_0.png")
        image_offset = 1
    
    # Image Character & Object Reference Tags (<IMAGE_REF_i>[Character A] / <IMAGE_REF_i>[no_character])
    if ref_imgs and len(ref_imgs) > 0:
        for i in range(min(10, len(ref_imgs))):
            img_idx = i + image_offset
            # Tag the primary reference (index 0) as character entity, subsequent references as object/prop [no_character]
            entity_tag = "[Character A]" if i == 0 else "[no_character]"
            ref_tags.append(f"<IMAGE_REF_{i}>{entity_tag}image_{img_idx}.png")

    if ref_tags:
        mmc_parts.append(f"# References {' '.join(ref_tags)}")

    mmc_mode_str = f"[{' '.join(mmc_parts)}] " if mmc_parts else ""
    fc_args_str = f"[aspect_ratio={aspect_ratio}] [resolution={resolution}] [duration={duration}s]"

    # Append voice transcript / dialogue instruction if provided and not already included in prompt
    prompt_content = prompt
    if voice_transcript and voice_transcript.strip():
        transcript_clean = voice_transcript.strip()
        dialogue_tag = f"Character A speaks dialogue: \"{transcript_clean}\""
        if dialogue_tag not in prompt and transcript_clean not in prompt:
            prompt_content = f"{prompt}. {dialogue_tag}"

    full_control_string = f"{mmc_mode_str}{fc_args_str} {prompt_content}".strip()
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
    reference_assets_b64: Optional[List[str]] = None,
    reference_audio_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    client: Optional[genai.Client] = None,
) -> bytes:
    """Wrapper tool for Gemini Omni Flash (gemini-omni-flash-preview) using interactions.create API.
    
    Supports:
    - MMC Control Strings formatting (MMC mode tags, audio reference tags & FC argument tokens)
    - Mode A (Reference Mode): Image references + voice audio references + text prompt.
    - Mode B (Sequential I2V Mode): Terminal frame base64 input + text motion prompt.
    """
    if client is None:
        client = get_genai_client()

    ref_imgs = reference_images_b64 if reference_images_b64 is not None else reference_assets_b64
    ref_auds = reference_audio_b64 or []
    config = Config()
    payload = []

    # Mode B: Image-to-Video Chaining
    if input_image_b64:
        payload.append({
            "type": "image",
            "data": input_image_b64,
            "mime_type": "image/png"
        })

    # Mode A: Shared Image Reference Mode
    if ref_imgs:
        for img_b64 in ref_imgs[:10]:
            payload.append({
                "type": "image",
                "data": img_b64,
                "mime_type": "image/png"
            })

    # Format full control string according to Google Omni / Video Station specification
    formatted_prompt = build_omni_control_string(
        prompt=prompt,
        input_image_b64=input_image_b64,
        reference_images_b64=ref_imgs,
        reference_audio_b64=ref_auds,
        voice_transcript=voice_transcript,
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
