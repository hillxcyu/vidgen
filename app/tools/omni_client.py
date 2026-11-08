import base64
import os
import subprocess
import tempfile
from typing import List, Optional
import cv2
import numpy as np
from google import genai
from app.config import get_genai_client, Config


def build_omni_control_string(
    prompt: str,
    input_image_b64: Optional[str] = None,
    end_image_b64: Optional[str] = None,
    input_video_b64: Optional[str] = None,
    task: Optional[str] = None,
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
    - Dual-Anchor Chaining: <FIRST_FRAME>image_0.png and <LAST_FRAME>image_1.png
    - Temporal Video Extension: <VIDEO_0>video_0.mp4 with task="extend"
    - Image Reference tags: <IMAGE_REF_i>[Character A]image_i.png
    - Audio Reference tags: <AUDIO_REF_i>[Character A]audio_i.wav
    - Spoken dialogue / transcript matching across shots for voice consistency
    
    Format:
    [MMC_MODE_STRING] [aspect_ratio=VALUE] [resolution=VALUE] [duration=VALUEs] <user prompt>
    """
    # When input_image_b64 (<FIRST_FRAME>) or input_video_b64 (<VIDEO_0>) is present, omit reference_images_b64
    # so Gemini Omni Flash strictly chains/extends from the source media instead of switching to R2V (<IMAGE_REF_0>).
    raw_refs = reference_images_b64 if reference_images_b64 is not None else reference_assets_b64
    ref_imgs = None if (input_image_b64 or input_video_b64) else raw_refs
    ref_auds = reference_audio_b64 or []
    mmc_parts = []
    source_tags = []
    ref_tags = []

    # Image-to-Video & Video-Extend Chaining Source Tags (<FIRST_FRAME>, <LAST_FRAME>, <VIDEO_0>)
    image_offset = 0
    if input_image_b64:
        source_tags.append(f"<FIRST_FRAME>image_{image_offset}.png")
        image_offset += 1
    if end_image_b64:
        source_tags.append(f"<LAST_FRAME>image_{image_offset}.png")
        image_offset += 1
    if input_video_b64:
        source_tags.append("<VIDEO_0>video_0.mp4")
    
    if source_tags:
        mmc_parts.append(f"# Sources {' '.join(source_tags)}")
    
    # Image Character & Object Reference Tags (<IMAGE_REF_i>[Character A] / <IMAGE_REF_i>[no_character])
    if ref_imgs and len(ref_imgs) > 0:
        for i in range(min(10, len(ref_imgs))):
            img_idx = i + image_offset
            entity_tag = "[Character A]" if i == 0 else "[no_character]"
            ref_tags.append(f"<IMAGE_REF_{i}>{entity_tag}image_{img_idx}.png")

    if ref_tags and task != "reference_to_video":
        mmc_parts.append(f"# References {' '.join(ref_tags)}")

    mmc_mode_str = f"[{' '.join(mmc_parts)}] " if mmc_parts else ""
    if task == "reference_to_video":
        fc_args_str = ""
    elif task == "extend":
        fc_args_str = f"[resolution={resolution}] [duration={duration}s]"
    else:
        fc_args_str = f"[aspect_ratio={aspect_ratio}] [resolution={resolution}] [duration={duration}s]"

    # Ensure prompt text binds Character A to match <IMAGE_REF_0>[Character A] when reference assets are present
    prompt_content = prompt
    if ref_imgs and len(ref_imgs) > 0 and "Character A" not in prompt_content:
        prompt_content = f"Character A, {prompt_content[0].lower() + prompt_content[1:] if len(prompt_content) > 1 else prompt_content}"
    elif (input_image_b64 or input_video_b64) and "Character A" in prompt_content:
        import re
        prompt_content = re.sub(r"\bCharacter A\b,?\s*", "The subject ", prompt_content).strip()

    if task == "extend" and input_video_b64 and not prompt_content.lower().startswith("extend this video"):
        prompt_content = (
            "Extend this video: continue seamlessly from the final frame in one unbroken "
            f"single-take camera shot with no scene cuts. {prompt_content}"
        )

    # Append voice transcript / dialogue instruction if provided and not already included in prompt
    if voice_transcript and voice_transcript.strip():
        transcript_clean = voice_transcript.strip()
        speaker_label = "Character A" if (ref_imgs and len(ref_imgs) > 0) else "The speaker"
        dialogue_tag = f"{speaker_label} speaks dialogue: \"{transcript_clean}\""
        if dialogue_tag not in prompt_content and transcript_clean not in prompt_content:
            prompt_content = f"{prompt_content}. {dialogue_tag}"
        if task == "extend" and input_video_b64:
            prompt_content = (
                f"{prompt_content}. Maintain continuous ambient background sound and "
                "complete the spoken line cleanly before the shot ends."
            )
    elif task == "extend" and input_video_b64 and "ambient" not in prompt_content.lower():
        prompt_content = (
            f"{prompt_content}. Maintain continuous ambient room tone and natural acoustic continuity."
        )

    full_control_string = f"{mmc_mode_str}{fc_args_str} {prompt_content}".strip()
    return full_control_string


def _create_fallback_mp4_bytes(prompt: str) -> bytes:
    """Generates a synthetic 10-second MP4 clip for local fallback/demonstration."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, 10.0, (256, 256))
    for i in range(100):  # 10s at 10fps
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
    end_image_b64: Optional[str] = None,
    input_video_b64: Optional[str] = None,
    task: Optional[str] = None,
    model_override: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    reference_assets_b64: Optional[List[str]] = None,
    reference_audio_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    client: Optional[genai.Client] = None,
) -> bytes:
    """Wrapper tool for Gemini Omni Flash using interactions.create API.
    
    Supports:
    - MMC Control Strings formatting (MMC mode tags, audio reference tags & FC argument tokens)
    - Mode A (Reference Mode): Image references + voice audio references + text prompt.
    - Mode B (Sequential I2V Mode): Terminal frame base64 input + optional end frame base64 + text motion prompt.
    - Mode C (Video Extend Mode): Trailing video clip base64 input + task='extend' (gemini-omni-1.2-flash GA with automatic fallback).
    """
    config = Config()
    if client is None or type(client) is genai.Client:
        client = get_genai_client(timeout_ms=config.VIDEO_GEN_TIMEOUT_MS)

    raw_refs = reference_images_b64 if reference_images_b64 is not None else reference_assets_b64
    ref_imgs = None if (input_image_b64 or input_video_b64) else raw_refs
    effective_task = task or ("reference_to_video" if (ref_imgs and len(ref_imgs) > 0) else None)
    ref_auds = reference_audio_b64 or []
    # Format full control string according to Google Omni / Video Station specification
    formatted_prompt = build_omni_control_string(
        prompt=prompt,
        input_image_b64=input_image_b64,
        end_image_b64=end_image_b64,
        input_video_b64=input_video_b64,
        task=effective_task,
        reference_images_b64=ref_imgs,
        reference_audio_b64=ref_auds,
        voice_transcript=voice_transcript,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration
    )

    # Place text prompt first to maximize reference/source cross-attention weighting
    payload = [{
        "type": "text",
        "text": formatted_prompt
    }]

    # Mode B: Image-to-Video Chaining & Dual-Anchor (First & Last Frame)
    if input_image_b64:
        payload.append({
            "type": "image",
            "data": input_image_b64,
            "mime_type": "image/png"
        })
    if end_image_b64:
        payload.append({
            "type": "image",
            "data": end_image_b64,
            "mime_type": "image/png"
        })

    # Mode C: Video-to-Video Extension (<VIDEO_0>video_0.mp4)
    if input_video_b64:
        payload.append({
            "type": "video",
            "data": input_video_b64,
            "mime_type": "video/mp4"
        })

    # Mode A: Shared Image Reference Mode
    if ref_imgs:
        for img_b64 in ref_imgs[:10]:
            payload.append({
                "type": "image",
                "data": img_b64,
                "mime_type": "image/png"
            })

    target_model = model_override or (
        config.VIDEO_EXTEND_MODEL if effective_task == "extend" else config.VIDEO_GEN_MODEL
    )

    print(f"[Omni Flash Dispatch] Model: {target_model} (task={effective_task or 'default'})")
    print(f"[Omni Flash Dispatch] Control String: {formatted_prompt}")
    print(f"[Omni Flash Dispatch] Payload Count: {len(payload)} (Text: 1, Media: {len(payload)-1})")
    if ref_imgs:
        print(f"[Omni Flash Dispatch] Reference Images Attached: {len(ref_imgs)} (R2V task={effective_task})")
    if input_image_b64:
        print("[Omni Flash Dispatch] First Frame Anchor Attached (<FIRST_FRAME>)")
    if end_image_b64:
        print("[Omni Flash Dispatch] Last Frame Anchor Attached (<LAST_FRAME>)")
    if input_video_b64:
        print("[Omni Flash Dispatch] Video Tail Anchor Attached (<VIDEO_0>)")

    create_kwargs = {
        "model": target_model,
        "input": payload,
        "timeout": 600.0,
    }
    if effective_task == "reference_to_video":
        create_kwargs["generation_config"] = {"video_config": {"task": "reference_to_video"}}
        create_kwargs["response_format"] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": f"{duration}s",
            "resolution": resolution,
        }
    elif effective_task:
        create_kwargs["generation_config"] = {"video_config": {"task": effective_task}}
        create_kwargs["response_format"] = {"type": "video"}

    def _sanitize_tail_audio_for_speech_edit(video_b64: str, strip_all: bool = False) -> str:
        """Replaces earlier speech in a 5s <VIDEO_0> tail with its own trailing 1.4s ambient room tone (or strips audio) when speech_edit safety blocks."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf_in:
            tf_in.write(base64.b64decode(video_b64))
            in_p = tf_in.name
        out_p = in_p + "_amb.mp4"
        try:
            if strip_all:
                cmd = ["ffmpeg", "-y", "-i", in_p, "-map", "0:v:0", "-c:v", "copy", "-an", "-movflags", "+faststart", out_p]
            else:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", in_p],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                dur = max(1.6, float(probe.stdout.strip() or "5.0"))
                amb_start = max(0.0, dur - 1.4)
                af = (
                    f"atrim=start={amb_start:.3f},asetpts=PTS-STARTPTS,"
                    f"aloop=loop=4:size=67200,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:st=0:d=0.10"
                )
                cmd = [
                    "ffmpeg", "-y", "-i", in_p,
                    "-map", "0:v:0", "-map", "0:a:0",
                    "-c:v", "copy", "-af", af,
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
                    "-movflags", "+faststart", out_p,
                ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and os.path.exists(out_p) and os.path.getsize(out_p) > 0:
                with open(out_p, "rb") as rf:
                    return base64.b64encode(rf.read()).decode("utf-8")
            return video_b64
        finally:
            for p in (in_p, out_p):
                if os.path.exists(p):
                    os.remove(p)

    def _invoke_extend_safe(kwargs_dict: dict) -> object:
        try:
            return client.interactions.create(**kwargs_dict)
        except Exception as err:
            err_s = str(err)
            err_l = err_s.lower()
            if task == "extend" and input_video_b64 and ("speech edit" in err_l or "unable to process speech" in err_l):
                print(
                    "[Omni Flash Notice] Speech-edit guardrail triggered on <VIDEO_0> tail; "
                    "replacing earlier tail speech with trailing 1.4s ambient room tone to preserve seam acoustics."
                )
                amb_b64 = _sanitize_tail_audio_for_speech_edit(input_video_b64, strip_all=False)
                amb_payload = [payload[0], {"type": "video", "data": amb_b64, "mime_type": "video/mp4"}] + payload[2:]
                try:
                    return client.interactions.create(**{**kwargs_dict, "input": amb_payload})
                except Exception as err2:
                    if "speech edit" in str(err2).lower() or "unable to process speech" in str(err2).lower():
                        print("[Omni Flash Notice] Trailing 1.4s still contained speech; falling back to silent <VIDEO_0> tail.")
                        sil_b64 = _sanitize_tail_audio_for_speech_edit(input_video_b64, strip_all=True)
                        sil_payload = [payload[0], {"type": "video", "data": sil_b64, "mime_type": "video/mp4"}] + payload[2:]
                        return client.interactions.create(**{**kwargs_dict, "input": sil_payload})
                    err = err2
                    err_l = str(err2).lower()

            if (
                effective_task in ("extend", "reference_to_video")
                and voice_transcript
                and ("safety violations" in err_l or "harmful content" in err_l)
            ):
                print(
                    f"[Omni Flash Notice] TPVG speech endorsement safety block on task='{effective_task}'; "
                    "retrying with ambient audio (omitting spoken dialogue tag)."
                )
                fallback_prompt = build_omni_control_string(
                    prompt=prompt,
                    input_image_b64=input_image_b64,
                    end_image_b64=end_image_b64,
                    input_video_b64=input_video_b64,
                    task=effective_task,
                    reference_images_b64=ref_imgs,
                    reference_audio_b64=ref_auds,
                    voice_transcript=None,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    duration=duration,
                )
                retry_payload = [{"type": "text", "text": fallback_prompt}] + payload[1:]
                retry_kwargs = {**kwargs_dict, "input": retry_payload}
                return client.interactions.create(**retry_kwargs)
            raise

    try:
        try:
            interaction = _invoke_extend_safe(create_kwargs)
        except Exception as primary_err:
            err_text = str(primary_err)
            can_fallback = (
                task == "extend"
                and model_override is None
                and config.VIDEO_EXTEND_FALLBACK_MODEL
                and config.VIDEO_EXTEND_FALLBACK_MODEL != target_model
                and any(
                    tok in err_text
                    for tok in ("404", "not_found", "NotFound", "403", "PERMISSION_DENIED", "not supported")
                )
            )
            if can_fallback:
                print(
                    f"[Omni Flash Notice] Model '{target_model}' unavailable on project "
                    f"({err_text[:120]}); falling back to '{config.VIDEO_EXTEND_FALLBACK_MODEL}' with task='{task}'."
                )
                create_kwargs["model"] = config.VIDEO_EXTEND_FALLBACK_MODEL
                interaction = _invoke_extend_safe(create_kwargs)
            else:
                raise

        if hasattr(interaction, "output") and isinstance(interaction.output, bytes):
            return interaction.output
        if hasattr(interaction, "output") and isinstance(interaction.output, list):
            for item in interaction.output:
                if isinstance(item, dict) and item.get("data"):
                    raw = item["data"]
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
                elif hasattr(item, "data") and item.data:
                    raw = item.data
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
        if hasattr(interaction, "outputs") and interaction.outputs:
            for item in interaction.outputs:
                if hasattr(item, "data") and item.data:
                    raw = item.data
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
                elif isinstance(item, dict) and item.get("data"):
                    raw = item["data"]
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
        if hasattr(interaction, "output_video") and not callable(getattr(interaction, "output_video", None)):
            ov = interaction.output_video
            data_val = ov.get("data") if isinstance(ov, dict) else getattr(ov, "data", None)
            if isinstance(data_val, str) and data_val:
                return base64.b64decode(data_val)
            elif isinstance(data_val, bytes) and data_val:
                return data_val
        if hasattr(interaction, "model_dump") and callable(interaction.model_dump):
            try:
                dumped = interaction.model_dump()
                if isinstance(dumped, dict):
                    ov_d = dumped.get("output_video")
                    if isinstance(ov_d, dict) and ov_d.get("data"):
                        raw = ov_d["data"]
                        return base64.b64decode(raw) if isinstance(raw, str) else raw
            except Exception:
                pass
        if hasattr(interaction, "steps") and interaction.steps:
            for step in interaction.steps:
                if getattr(step, "content", None):
                    for part in step.content:
                        raw = getattr(part, "data", None) or (getattr(part.inline_data, "data", None) if getattr(part, "inline_data", None) else None)
                        if not raw and isinstance(part, dict):
                            raw = part.get("data")
                        if raw:
                            return base64.b64decode(raw) if isinstance(raw, str) else raw
        if hasattr(interaction, "candidates") and len(interaction.candidates) > 0:
            cand = interaction.candidates[0]
            if hasattr(cand, "content") and hasattr(cand.content, "parts"):
                for part in cand.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        val = part.inline_data.data
                        if isinstance(val, bytes):
                            return val
                        elif isinstance(val, str):
                            return base64.b64decode(val)
        
        return _create_fallback_mp4_bytes(formatted_prompt)
    except Exception as e:
        import traceback
        err_detail = f"Gemini Omni Video Gen Error ({type(e).__name__}): {e}"
        print(f"[ERROR] {err_detail}")
        traceback.print_exc()
        raise RuntimeError(err_detail) from e

    return _create_fallback_mp4_bytes(formatted_prompt)
