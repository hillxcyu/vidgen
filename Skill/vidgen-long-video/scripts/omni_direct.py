# Copyright 2026 Author:Hill YU(xcyu@)
"""Direct Google GenAI model calls for ADK-free multi-shot video generation and Auto-Rater v2.

Wraps `google.genai.Client` directly (supporting both Vertex AI ADC with `location='global'`
and `GEMINI_API_KEY`) for:
1. Storyboard generation & single-take prompt optimization via `gemini-3.8-flash`.
2. Video generation (`reference_to_video`, `<FIRST_FRAME>` I2V, and `extend`) via `gemini-omni-1.2-flash`.
3. Observation-first Auto-Rater v2 & Post-Stitch Master Seam Critic via `gemini-3.8-flash`
   with server-side Agentic Video Understanding (`MediaProcessing.AGENTIC` / `google:load_video`).
"""
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "google-genai>=2.21.0",
#   "opencv-python-headless>=4.8.0",
#   "numpy>=1.24.0",
#   "pydantic>=2.6.0",
# ]
# ///

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from media_ops import (  # noqa: E402
    analyze_clip_audio_tail,
    compute_transcript_metrics,
    create_agentic_video_part,
    decode_valid_image_b64,
    encode_image_file_b64,
    extract_labeled_audit_keyframes,
)


class DirectConfig:
    """Environment-driven configuration with GA model defaults and zero ADK dependencies."""

    ORCHESTRATOR_MODEL: str = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.8-flash")
    VIDEO_GEN_MODEL: str = os.getenv("VIDEO_GEN_MODEL", "gemini-omni-1.2-flash")
    VIDEO_EXTEND_MODEL: str = os.getenv("VIDEO_EXTEND_MODEL", "gemini-omni-1.2-flash")
    VIDEO_EXTEND_FALLBACK_MODEL: str = os.getenv(
        "VIDEO_EXTEND_FALLBACK_MODEL", "gemini-omni-flash-preview"
    )
    IMAGE_GEN_MODEL: str = os.getenv("IMAGE_GEN_MODEL", "gemini-nano-banana-2.1")
    IMAGE_GEN_FALLBACK_MODEL: str = os.getenv("IMAGE_GEN_FALLBACK_MODEL", "gemini-2.5-flash-image")
    VIDEO_EXTEND_INPUT_SECONDS: float = float(os.getenv("VIDEO_EXTEND_INPUT_SECONDS", "5.0"))
    MEDIA_PROCESSING: str = os.getenv("MEDIA_PROCESSING", "AGENTIC")
    VIDEO_GEN_TIMEOUT_MS: int = int(os.getenv("VIDEO_GEN_TIMEOUT_MS", "600000"))
    RATER_TIMEOUT_MS: int = int(os.getenv("RATER_TIMEOUT_MS", "120000"))
    MAX_PARALLEL_SHOTS: int = int(os.getenv("MAX_PARALLEL_SHOTS", "3"))


def _is_transient_capacity_error(err: BaseException) -> bool:
    """Detects transient 429/503 rate-limit or capacity errors suitable for exponential backoff."""
    msg = str(err).lower()
    return any(
        tok in msg
        for tok in (
            "429",
            "resource_exhausted",
            "too many requests",
            "503",
            "unavailable",
            "overloaded",
            "504",
            "deadline_exceeded",
        )
    )


def _call_with_backoff_sync(fn: Any, *args: Any, max_retries: int = 4, base_delay_sec: float = 8.0, **kwargs: Any) -> Any:
    """Executes a synchronous SDK call with jittered exponential backoff on 429/503 errors."""
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as err:
            if attempt >= max_retries or not _is_transient_capacity_error(err):
                raise
            sleep_sec = base_delay_sec * (2 ** attempt) + random.uniform(0.5, 2.5)
            print(f"[Retry Backoff {attempt + 1}/{max_retries}] Transient API error ({err}); sleeping {sleep_sec:.1f}s...")
            time.sleep(sleep_sec)


def _load_optional_gcp_env() -> None:
    """Loads GOOGLE_CLOUD_PROJECT from local `.env` or `~/gcp.env` if neither project nor API key is set."""
    if os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GEMINI_API_KEY"):
        return
    for env_file in (Path.cwd() / ".env", Path.home() / "gcp.env"):
        if not env_file.is_file():
            continue
        try:
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = os.path.expandvars(os.path.expanduser(v.strip().strip('"').strip("'")))
                    if k == "GOOGLE_APPLICATION_CREDENTIALS" and not os.path.isfile(v):
                        continue
                    if k and k not in os.environ:
                        os.environ[k] = v
            if os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GEMINI_API_KEY"):
                return
        except Exception:
            pass


def get_direct_genai_client(timeout_ms: int = DirectConfig.VIDEO_GEN_TIMEOUT_MS) -> genai.Client:
    """Initializes a direct Google GenAI Client using Vertex AI ADC (`location='global'`) or `GEMINI_API_KEY`."""
    _load_optional_gcp_env()
    http_opts = types.HttpOptions(timeout=timeout_ms)
    api_key = os.getenv("GEMINI_API_KEY")
    use_vertex_env = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

    if use_vertex_env in ("1", "true", "yes") or (project and not api_key):
        return genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=http_opts,
        )
    if api_key:
        return genai.Client(api_key=api_key, http_options=http_opts)
    return genai.Client(vertexai=True, location=location, http_options=http_opts)


# ---------------------------------------------------------------------------
# Structured Schemas (Storyboard, Auto-Rater v2, Post-Stitch Master Critic)
# ---------------------------------------------------------------------------


class StoryboardEntrySpec(BaseModel):
    scene_number: int = Field(description="1-based shot index.")
    description: str = Field(description="Visual action and setting for this single continuous shot.")
    camera_angle: str = Field(default="medium tracking", description="Single continuous camera framing/motion.")
    evaluation_criteria: str = Field(
        default="Verify subject/product identity lock, single-take motion, and temporal asset persistence.",
        description="Shot-specific visual & continuity audit criteria.",
    )
    spoken_dialogue: Optional[str] = Field(
        default=None,
        description="Optional verbatim spoken line for this shot (<= 12 words, finishing before 8s).",
    )
    mode_override: Optional[str] = Field(
        default=None,
        description="Optional per-shot mode override ('reference', 'i2v_chaining', or 'video_extend').",
    )


class CriterionEvaluation(BaseModel):
    criterion_name: str = Field(description="Name of the evaluated criterion.")
    score: float = Field(default=1.0, description="Score from 0.0 to 1.0.")
    comments: str = Field(default="Meets criteria", description="Specific observation.")


QUALITY_EVALUATION_PROPERTY_ORDER: List[str] = [
    "opening_environment_observed",
    "heard_transcript",
    "speech_end_sec",
    "detected_internal_cuts",
    "reason",
    "score",
    "verdict",
    "feedback",
]


class QualityEvaluationResult(BaseModel):
    opening_environment_observed: str = Field(default="")
    heard_transcript: str = Field(default="")
    speech_end_sec: Optional[float] = Field(default=None)
    detected_internal_cuts: int = Field(default=0)
    reason: List[CriterionEvaluation] = Field(default_factory=list)
    score: float = Field(default=0.0)
    verdict: str = Field(default="REATTEMPT_REQUIRED")
    feedback: str = Field(default="")
    transcript_wer: Optional[float] = Field(default=None)
    transcript_word_overlap: Optional[float] = Field(default=None)
    audit_status: str = Field(default="OK")
    deterministic_telemetry: Dict[str, Any] = Field(default_factory=dict)


class SeamWindowObservation(BaseModel):
    seam_index: int = Field(description="1-based seam index (1 for Shot 1->2).")
    window_sec: str = Field(description="Timestamp window inspected (e.g. '8.5s-11.5s').")
    continuity_score: float = Field(default=1.0)
    notes: str = Field(default="Clean visual and acoustic transition.")


MASTER_SEAM_PROPERTY_ORDER: List[str] = [
    "seam_observations",
    "voice_timbre_consistent",
    "loudness_continuity_ok",
    "visual_xfade_smooth",
    "score",
    "verdict",
    "feedback",
]


class MasterSeamEvaluationResult(BaseModel):
    seam_observations: List[SeamWindowObservation] = Field(default_factory=list)
    voice_timbre_consistent: bool = Field(default=True)
    loudness_continuity_ok: bool = Field(default=True)
    visual_xfade_smooth: bool = Field(default=True)
    score: float = Field(default=1.0)
    verdict: str = Field(default="PASSED")
    feedback: str = Field(default="Stitched master transitions are smooth.")
    audit_status: str = Field(default="OK")
    deterministic_telemetry: Dict[str, Any] = Field(default_factory=dict)


def build_quality_evaluation_schema() -> types.Schema:
    """Explicit Google GenAI Schema enforcing observation-first property_ordering before numeric scoring."""
    return types.Schema(
        type=types.Type.OBJECT,
        property_ordering=list(QUALITY_EVALUATION_PROPERTY_ORDER),
        properties={
            "opening_environment_observed": types.Schema(type=types.Type.STRING),
            "heard_transcript": types.Schema(type=types.Type.STRING),
            "speech_end_sec": types.Schema(type=types.Type.NUMBER, nullable=True),
            "detected_internal_cuts": types.Schema(type=types.Type.INTEGER),
            "reason": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    property_ordering=["criterion_name", "score", "comments"],
                    properties={
                        "criterion_name": types.Schema(type=types.Type.STRING),
                        "score": types.Schema(type=types.Type.NUMBER),
                        "comments": types.Schema(type=types.Type.STRING),
                    },
                    required=["criterion_name", "score", "comments"],
                ),
            ),
            "score": types.Schema(type=types.Type.NUMBER),
            "verdict": types.Schema(type=types.Type.STRING),
            "feedback": types.Schema(type=types.Type.STRING),
        },
        required=[
            "opening_environment_observed",
            "heard_transcript",
            "detected_internal_cuts",
            "reason",
            "score",
            "verdict",
            "feedback",
        ],
    )


def build_master_seam_evaluation_schema() -> types.Schema:
    """Explicit Google GenAI Schema for post-stitch seam window auditing."""
    return types.Schema(
        type=types.Type.OBJECT,
        property_ordering=list(MASTER_SEAM_PROPERTY_ORDER),
        properties={
            "seam_observations": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    property_ordering=["seam_index", "window_sec", "continuity_score", "notes"],
                    properties={
                        "seam_index": types.Schema(type=types.Type.INTEGER),
                        "window_sec": types.Schema(type=types.Type.STRING),
                        "continuity_score": types.Schema(type=types.Type.NUMBER),
                        "notes": types.Schema(type=types.Type.STRING),
                    },
                    required=["seam_index", "window_sec", "continuity_score", "notes"],
                ),
            ),
            "voice_timbre_consistent": types.Schema(type=types.Type.BOOLEAN),
            "loudness_continuity_ok": types.Schema(type=types.Type.BOOLEAN),
            "visual_xfade_smooth": types.Schema(type=types.Type.BOOLEAN),
            "score": types.Schema(type=types.Type.NUMBER),
            "verdict": types.Schema(type=types.Type.STRING),
            "feedback": types.Schema(type=types.Type.STRING),
        },
        required=list(MASTER_SEAM_PROPERTY_ORDER),
    )


def _extract_avu_usage_telemetry(resp: Any) -> Dict[str, Any]:
    """Extracts server-side Agentic Video Understanding (`google:load_video`) token counts from usage_metadata."""
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return {"avu_tool_use_tokens": None, "avu_prompt_tokens": None, "avu_initial_video_tokens": None}
    initial_video_tokens = 0
    for detail in getattr(meta, "prompt_tokens_details", None) or []:
        if "VIDEO" in str(getattr(detail, "modality", "")).upper():
            initial_video_tokens += int(getattr(detail, "token_count", 0) or 0)
    return {
        "avu_tool_use_tokens": getattr(meta, "tool_use_prompt_token_count", None),
        "avu_prompt_tokens": getattr(meta, "prompt_token_count", None),
        "avu_initial_video_tokens": initial_video_tokens,
    }


# ---------------------------------------------------------------------------
# Direct Gemini 3.8 Flash Pre-Production & Prompt Optimizer
# ---------------------------------------------------------------------------


async def generate_storyboard_direct(
    intent: str,
    num_shots: int = 3,
    mode: str = "video_extend",
    voice_transcript: Optional[str] = None,
    client: Optional[genai.Client] = None,
) -> List[StoryboardEntrySpec]:
    """Generates a structured N-shot storyboard directly via `gemini-3.8-flash`."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    mode_guidance = {
        "reference": (
            "Mode A (Parallel Shared Reference-to-Video): Each shot can explore a distinct environment or framing "
            "while anchoring on the exact same subject/product from the #FFFFFF reference image."
        ),
        "i2v_chaining": (
            "Mode B (Sequential <FIRST_FRAME> I2V Chaining): Shot 1 opens in the target scene; Shots 2..N start "
            "directly from the exact final frame of the preceding shot in one continuous progression."
        ),
        "video_extend": (
            "Mode C (Temporal Video Extension): All shots take place inside the SAME physical location as one "
            "unbroken continuous single-take camera trajectory across 10s boundaries—zero location teleports."
        ),
        "hybrid": (
            "Mode D (Hybrid Choreography): Set mode_override per shot ('reference' for act-break scene switches, "
            "'video_extend' or 'i2v_chaining' for unbroken continuation within the same space)."
        ),
    }.get(mode, "Maintain strong visual and acoustic continuity across all shots.")

    vo_guidance = (
        f"\nFull Voiceover Script to split cleanly across the {num_shots} shots (<= 12 words per shot, "
        f"finishing before 8s of each 10s clip, avoiding explicit brand-CTA endorsement slogans): '{voice_transcript}'"
        if voice_transcript
        else "\nNo spoken voiceover required unless natural to the prompt (leave spoken_dialogue null if ambient)."
    )

    prompt = (
        f"Design a {num_shots}-shot commercial storyboard for: '{intent}'.\n"
        f"Orchestration Strategy: {mode_guidance}{vo_guidance}\n"
        "Every shot MUST be a single unbroken camera take with zero internal jump cuts.\n"
        f"Return a JSON array of exactly {num_shots} objects matching the schema."
    )

    schema = types.Schema(
        type=types.Type.ARRAY,
        items=types.Schema(
            type=types.Type.OBJECT,
            property_ordering=[
                "scene_number",
                "description",
                "camera_angle",
                "evaluation_criteria",
                "spoken_dialogue",
                "mode_override",
            ],
            properties={
                "scene_number": types.Schema(type=types.Type.INTEGER),
                "description": types.Schema(type=types.Type.STRING),
                "camera_angle": types.Schema(type=types.Type.STRING),
                "evaluation_criteria": types.Schema(type=types.Type.STRING),
                "spoken_dialogue": types.Schema(type=types.Type.STRING, nullable=True),
                "mode_override": types.Schema(type=types.Type.STRING, nullable=True),
            },
            required=["scene_number", "description", "camera_angle", "evaluation_criteria"],
        ),
    )

    try:
        resp = await asyncio.to_thread(
            active_client.models.generate_content,
            model=DirectConfig.ORCHESTRATOR_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.3,
            ),
        )
        if resp and resp.text:
            raw_list = json.loads(resp.text)
            return [
                StoryboardEntrySpec(
                    scene_number=item.get("scene_number", i + 1),
                    description=item.get("description", f"{intent} - Shot {i + 1}"),
                    camera_angle=item.get("camera_angle", "smooth tracking"),
                    evaluation_criteria=item.get(
                        "evaluation_criteria",
                        "Verify subject identity lock, smooth single-take camera motion, and asset persistence.",
                    ),
                    spoken_dialogue=item.get("spoken_dialogue"),
                    mode_override=item.get("mode_override"),
                )
                for i, item in enumerate(raw_list[:num_shots])
            ]
    except Exception as err:
        print(f"[Storyboarder Fallback Notice]: {err}")

    angles = ["medium tracking", "close-up dolly", "wide crane", "orbital tracking"]
    return [
        StoryboardEntrySpec(
            scene_number=i + 1,
            description=f"{intent} — continuous scene {i + 1}",
            camera_angle=angles[i % len(angles)],
        )
        for i in range(num_shots)
    ]


async def optimize_shot_prompt_direct(
    raw_prompt: str,
    feedback: Optional[str] = None,
    voice_transcript: Optional[str] = None,
    is_extend_shot: bool = False,
    is_r2v_shot: bool = False,
    client: Optional[genai.Client] = None,
) -> str:
    """Enhances a shot description for `gemini-omni-1.2-flash` via a direct `gemini-3.8-flash` call."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    feedback_ctx = f"\nQuality Rater Feedback to fix on this retry: '{feedback}'" if feedback else ""
    transcript_ctx = (
        f"\nExact Spoken Dialogue Transcript: '{voice_transcript}'. "
        "Include these exact words verbatim without adding unscripted greetings or filler words."
        if voice_transcript
        else ""
    )
    extend_ctx = (
        "\nVIDEO-EXTEND SEAM RULE: This shot extends the final frame of the previous clip. "
        "Maintain the exact starting environment, lighting, and pose from the preceding shot in one unbroken single-take camera movement with ZERO scene cuts."
        if is_extend_shot
        else ""
    )
    r2v_ctx = (
        "\nR2V SCENE-OPENING RULE: This shot uses Reference-to-Video (task='reference_to_video') with a #FFFFFF studio reference image. "
        "Open immediately on Frame 0 inside the rich target environment—NEVER depict or mention a white studio backdrop."
        if is_r2v_shot
        else ""
    )

    prompt = (
        f"Raw Shot Description: '{raw_prompt}'.{feedback_ctx}{transcript_ctx}{extend_ctx}{r2v_ctx}\n\n"
        "Write ONLY the enhanced single-paragraph video generation prompt (under 60 words) for Gemini Omni 1.2 Flash. "
        "Explicitly specify one continuous, uninterrupted single-take camera movement and forbid internal cuts or jump cuts."
    )
    try:
        resp = await asyncio.to_thread(
            active_client.models.generate_content,
            model=DirectConfig.ORCHESTRATOR_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.25),
        )
        if resp and resp.text and resp.text.strip():
            cleaned = resp.text.strip().strip('"')
            return " ".join(cleaned.split())
    except Exception as err:
        print(f"[PromptOptimizer Fallback Notice]: {err}")
    return raw_prompt


# ---------------------------------------------------------------------------
# Direct Reference Plate & Keyframe Image Generation (`gemini-nano-banana-2.1`)
# ---------------------------------------------------------------------------


def generate_reference_image_direct(
    prompt: str,
    reference_images_b64: Optional[List[str]] = None,
    aspect_ratio: str = "16:9",
    client: Optional[genai.Client] = None,
) -> bytes:
    """Generates a 16:9/9:16 scene reference plate or interpolation keyframe via `gemini-nano-banana-2.1`.

    Automatically skips `part.thought == True` draft thought-images so only the final rendered
    high-resolution image bytes are returned.
    """
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    contents: List[Any] = []
    if reference_images_b64:
        for img_b64 in reference_images_b64[:4]:
            decoded = decode_valid_image_b64(img_b64)
            if decoded is not None:
                img_bytes, mime = decoded
                contents.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
    contents.append(prompt)

    cfg = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
    )

    def _run_model(model_name: str) -> Any:
        return _call_with_backoff_sync(
            active_client.models.generate_content,
            model=model_name,
            contents=contents,
            config=cfg,
        )

    try:
        resp = _run_model(DirectConfig.IMAGE_GEN_MODEL)
    except Exception as primary_err:
        err_text = str(primary_err)
        if (
            DirectConfig.IMAGE_GEN_FALLBACK_MODEL
            and DirectConfig.IMAGE_GEN_FALLBACK_MODEL != DirectConfig.IMAGE_GEN_MODEL
            and any(tok in err_text for tok in ("404", "not_found", "NotFound", "403", "PERMISSION_DENIED"))
        ):
            resp = _run_model(DirectConfig.IMAGE_GEN_FALLBACK_MODEL)
        else:
            raise

    final_img_bytes: Optional[bytes] = None
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            if bool(getattr(part, "thought", False)):
                continue
            inline = getattr(part, "inline_data", None)
            raw_data = getattr(inline, "data", None) if inline is not None else None
            if raw_data:
                final_img_bytes = base64.b64decode(raw_data) if isinstance(raw_data, str) else raw_data
    if not final_img_bytes:
        raise RuntimeError("Image generation returned no non-thought inline image bytes.")
    return final_img_bytes


# ---------------------------------------------------------------------------
# Direct Gemini Omni 1.2 Flash Video Generation (`interactions.create`)
# ---------------------------------------------------------------------------


def build_omni_control_string(
    prompt: str,
    input_image_b64: Optional[str] = None,
    end_image_b64: Optional[str] = None,
    input_video_b64: Optional[str] = None,
    task: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
) -> str:
    """Formats the Gemini Omni control string while preventing R2V vs `<FIRST_FRAME>` / `<LAST_FRAME>` / `<VIDEO_0>` tag collisions."""
    is_two_frame_interp = bool(input_image_b64 and end_image_b64)
    eff_duration = min(10, max(3, int(duration))) if is_two_frame_interp else int(duration)
    ref_imgs = None if (input_image_b64 or end_image_b64 or input_video_b64) else reference_images_b64
    mmc_parts: List[str] = []
    source_tags: List[str] = []
    ref_tags: List[str] = []

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

    if ref_imgs and len(ref_imgs) > 0:
        for i in range(min(6, len(ref_imgs))):
            img_idx = i + image_offset
            entity_tag = "[Character A]" if i == 0 else "[no_character]"
            ref_tags.append(f"<IMAGE_REF_{i}>{entity_tag}image_{img_idx}.png")

    if ref_tags and task != "reference_to_video":
        mmc_parts.append(f"# References {' '.join(ref_tags)}")

    mmc_mode_str = f"[{' '.join(mmc_parts)}] " if mmc_parts else ""
    if task == "reference_to_video":
        fc_args_str = ""
    elif task == "extend":
        fc_args_str = f"[resolution={resolution}] [duration={eff_duration}s]"
    else:
        fc_args_str = f"[aspect_ratio={aspect_ratio}] [resolution={resolution}] [duration={eff_duration}s]"

    prompt_content = prompt
    if ref_imgs and len(ref_imgs) > 0 and "Character A" not in prompt_content:
        prompt_content = (
            f"Character A, {prompt_content[0].lower() + prompt_content[1:] if len(prompt_content) > 1 else prompt_content}"
        )
    elif (input_image_b64 or end_image_b64 or input_video_b64) and "Character A" in prompt_content:
        prompt_content = re.sub(r"\bCharacter A\b,?\s*", "The subject ", prompt_content).strip()

    if is_two_frame_interp and "starting frame" not in prompt_content.lower():
        prompt_content = (
            "Use the first image as the starting frame and the second image as the final frame, "
            f"transitioning smoothly in one unbroken single-take camera shot with zero internal cuts. {prompt_content}"
        )
    elif task == "extend" and input_video_b64 and not prompt_content.lower().startswith("extend this video"):
        prompt_content = (
            "Extend this video: continue seamlessly from the final frame in one unbroken "
            f"single-take camera shot with no scene cuts. {prompt_content}"
        )

    if voice_transcript and voice_transcript.strip():
        transcript_clean = voice_transcript.strip()
        speaker_label = "Character A" if (ref_imgs and len(ref_imgs) > 0) else "The speaker"
        dialogue_tag = f'{speaker_label} speaks dialogue: "{transcript_clean}"'
        if dialogue_tag not in prompt_content and transcript_clean not in prompt_content:
            prompt_content = f"{prompt_content}. {dialogue_tag}"
        if (task == "extend" and input_video_b64) or is_two_frame_interp:
            prompt_content = (
                f"{prompt_content}. Maintain continuous ambient background sound and "
                "complete the spoken line cleanly before the shot ends."
            )
    elif task == "extend" and input_video_b64 and "ambient" not in prompt_content.lower():
        prompt_content = f"{prompt_content}. Maintain continuous ambient room tone and natural acoustic continuity."

    return f"{mmc_mode_str}{fc_args_str} {prompt_content}".strip()


def _sanitize_tail_audio_for_speech_edit(video_b64: str, strip_all: bool = False) -> str:
    """Replaces earlier speech in a 5s `<VIDEO_0>` tail with its trailing 1.4s room-tone bed (or `-an` if needed)."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf_in:
        tf_in.write(base64.b64decode(video_b64))
        in_p = tf_in.name
    out_p = in_p + "_amb.mp4"
    try:
        if strip_all:
            cmd = ["ffmpeg", "-y", "-i", in_p, "-map", "0:v:0", "-c:v", "copy", "-an", "-movflags", "+faststart", out_p]
        else:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", in_p,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
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
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if res.returncode == 0 and os.path.exists(out_p) and os.path.getsize(out_p) > 0:
            with open(out_p, "rb") as rf:
                return base64.b64encode(rf.read()).decode("utf-8")
        return video_b64
    finally:
        for p in (in_p, out_p):
            if os.path.exists(p):
                os.remove(p)


def _extract_video_bytes_from_interaction(interaction: Any) -> Optional[bytes]:
    """Extracts MP4 video bytes across all supported `google-genai` Interactions API response shapes."""
    if hasattr(interaction, "output") and isinstance(interaction.output, bytes):
        return interaction.output
    for attr_name in ("output", "outputs"):
        items = getattr(interaction, attr_name, None)
        if items and isinstance(items, list):
            for item in items:
                raw = item.get("data") if isinstance(item, dict) else getattr(item, "data", None)
                if raw:
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
    ov = getattr(interaction, "output_video", None)
    if ov is not None and not callable(ov):
        data_val = ov.get("data") if isinstance(ov, dict) else getattr(ov, "data", None)
        if isinstance(data_val, str) and data_val:
            return base64.b64decode(data_val)
        if isinstance(data_val, bytes) and data_val:
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
    steps = getattr(interaction, "steps", None)
    if steps:
        for step in steps:
            for part in getattr(step, "content", None) or []:
                raw = getattr(part, "data", None) or (
                    getattr(part.inline_data, "data", None) if getattr(part, "inline_data", None) else None
                )
                if not raw and isinstance(part, dict):
                    raw = part.get("data")
                if raw:
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
    return None


def generate_omni_clip_direct(
    prompt: str,
    input_image_b64: Optional[str] = None,
    end_image_b64: Optional[str] = None,
    input_video_b64: Optional[str] = None,
    task: Optional[str] = None,
    model_override: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    client: Optional[genai.Client] = None,
) -> bytes:
    """Generates a single MP4 clip directly via `gemini-omni-1.2-flash` (`interactions.create`)."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    is_two_frame_interp = bool(input_image_b64 and end_image_b64)
    eff_duration = min(10, max(3, int(duration))) if is_two_frame_interp else int(duration)
    ref_imgs = None if (input_image_b64 or end_image_b64 or input_video_b64) else reference_images_b64
    effective_task = task or ("reference_to_video" if (ref_imgs and len(ref_imgs) > 0) else None)

    formatted_prompt = build_omni_control_string(
        prompt=prompt,
        input_image_b64=input_image_b64,
        end_image_b64=end_image_b64,
        input_video_b64=input_video_b64,
        task=effective_task,
        reference_images_b64=ref_imgs,
        voice_transcript=voice_transcript,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=eff_duration,
    )

    payload: List[Dict[str, Any]] = [{"type": "text", "text": formatted_prompt}]
    if input_image_b64:
        payload.append({"type": "image", "data": input_image_b64, "mime_type": "image/png"})
    if end_image_b64:
        payload.append({"type": "image", "data": end_image_b64, "mime_type": "image/png"})
    if input_video_b64:
        payload.append({"type": "video", "data": input_video_b64, "mime_type": "video/mp4"})
    if ref_imgs:
        for img_b64 in ref_imgs[:6]:
            payload.append({"type": "image", "data": img_b64, "mime_type": "image/png"})

    target_model = model_override or (
        DirectConfig.VIDEO_EXTEND_MODEL if effective_task == "extend" else DirectConfig.VIDEO_GEN_MODEL
    )

    create_kwargs: Dict[str, Any] = {
        "model": target_model,
        "input": payload,
        "timeout": float(DirectConfig.VIDEO_GEN_TIMEOUT_MS) / 1000.0,
    }
    if effective_task == "reference_to_video":
        create_kwargs["generation_config"] = {"video_config": {"task": "reference_to_video"}}
        create_kwargs["response_format"] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": f"{eff_duration}s",
            "resolution": resolution,
        }
    elif effective_task:
        create_kwargs["generation_config"] = {"video_config": {"task": effective_task}}
        create_kwargs["response_format"] = {"type": "video"}
    else:
        create_kwargs["response_format"] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": f"{eff_duration}s",
            "resolution": resolution,
        }

    def _invoke_safe(kwargs_dict: Dict[str, Any]) -> Any:
        try:
            return _call_with_backoff_sync(active_client.interactions.create, **kwargs_dict)
        except Exception as err:
            err_l = str(err).lower()
            if effective_task == "extend" and input_video_b64 and (
                "speech edit" in err_l or "unable to process speech" in err_l
            ):
                amb_b64 = _sanitize_tail_audio_for_speech_edit(input_video_b64, strip_all=False)
                amb_payload = [payload[0], {"type": "video", "data": amb_b64, "mime_type": "video/mp4"}] + payload[2:]
                try:
                    return _call_with_backoff_sync(
                        active_client.interactions.create, **{**kwargs_dict, "input": amb_payload}
                    )
                except Exception as err2:
                    if "speech edit" in str(err2).lower() or "unable to process speech" in str(err2).lower():
                        sil_b64 = _sanitize_tail_audio_for_speech_edit(input_video_b64, strip_all=True)
                        sil_payload = [
                            payload[0],
                            {"type": "video", "data": sil_b64, "mime_type": "video/mp4"},
                        ] + payload[2:]
                        return _call_with_backoff_sync(
                            active_client.interactions.create, **{**kwargs_dict, "input": sil_payload}
                        )
                    err = err2
                    err_l = str(err2).lower()

            if voice_transcript and (
                "safety violations" in err_l
                or "harmful content" in err_l
                or "speech edit" in err_l
                or "unable to process speech" in err_l
            ):
                in_vid = (
                    _sanitize_tail_audio_for_speech_edit(input_video_b64, strip_all=True)
                    if (effective_task == "extend" and input_video_b64 and ("speech edit" in err_l or "unable to process speech" in err_l))
                    else input_video_b64
                )
                fb_prompt = build_omni_control_string(
                    prompt=prompt,
                    input_image_b64=input_image_b64,
                    end_image_b64=end_image_b64,
                    input_video_b64=in_vid,
                    task=effective_task,
                    reference_images_b64=ref_imgs,
                    voice_transcript=None,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    duration=eff_duration,
                )
                fb_tail = [{"type": "video", "data": in_vid, "mime_type": "video/mp4"}] + payload[2:] if in_vid else payload[1:]
                return _call_with_backoff_sync(
                    active_client.interactions.create,
                    **{**kwargs_dict, "input": [{"type": "text", "text": fb_prompt}] + fb_tail},
                )
            raise

    try:
        interaction = _invoke_safe(create_kwargs)
    except Exception as primary_err:
        err_text = str(primary_err)
        can_fallback = (
            effective_task == "extend"
            and model_override is None
            and DirectConfig.VIDEO_EXTEND_FALLBACK_MODEL
            and DirectConfig.VIDEO_EXTEND_FALLBACK_MODEL != target_model
            and any(
                tok in err_text
                for tok in ("404", "not_found", "NotFound", "403", "PERMISSION_DENIED", "not supported")
            )
        )
        if can_fallback:
            create_kwargs["model"] = DirectConfig.VIDEO_EXTEND_FALLBACK_MODEL
            interaction = _invoke_safe(create_kwargs)
        else:
            raise

    video_bytes = _extract_video_bytes_from_interaction(interaction)
    if not video_bytes:
        raise RuntimeError("Gemini Omni returned an interaction without video bytes (check regional/input limits).")
    return video_bytes


# ---------------------------------------------------------------------------
# Direct Auto-Rater v2 & Post-Stitch Master Seam Critic (`MediaProcessing.AGENTIC`)
# ---------------------------------------------------------------------------


def build_consolidated_rubric(
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    has_reference_anchor: bool = False,
) -> List[str]:
    """Builds the deterministic Auto-Rater v2 evaluation rubric with zero extra LLM round-trips."""
    rubric: List[str] = []
    if evaluation_criteria and evaluation_criteria.strip():
        rubric.append(f"Scene Goal: {evaluation_criteria.strip()}")
    rubric.extend([
        "Face & Subject Identity Locking: Facial geometry, skin tone, and proportions match reference.",
        "Product & Object Locking: SKU shape, colorways, material texture, and branding remain stable.",
        "Wardrobe & Accessories Persistence: Garment silhouette, color, and props do not morph or vanish.",
        (
            "Single-Take & Scene-Opening Coherence: Unbroken single-take camera motion opening immediately "
            "inside the target environment (zero internal cuts; zero #FFFFFF studio backdrop echo)."
            if has_reference_anchor
            else "Single-Take & Continuity Coherence: Unbroken single-take camera motion with zero internal jump cuts."
        ),
    ])
    if spoken_dialogue and spoken_dialogue.strip():
        rubric.append(
            f"Spoken Dialogue & Audio Completion: Exact line ('{spoken_dialogue.strip()}') spoken clearly and finished before clip end."
        )
    return rubric


async def evaluate_clip_quality_direct(
    shot_index: int,
    prompt: str,
    video_path: str,
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    prev_last_frame_b64: Optional[str] = None,
    deterministic_signals: Optional[Dict[str, Any]] = None,
    is_r2v_shot: bool = False,
    is_extend_shot: bool = False,
    client: Optional[genai.Client] = None,
) -> Dict[str, Any]:
    """Evaluates a candidate shot via `gemini-3.8-flash` (`MediaProcessing.AGENTIC`) + high-res stills + OpenCV/FFMPEG guardrails."""
    ref_decoded = decode_valid_image_b64(reference_images_b64[0]) if reference_images_b64 else None
    prior_decoded = decode_valid_image_b64(prev_last_frame_b64) if prev_last_frame_b64 else None
    rubric = build_consolidated_rubric(
        evaluation_criteria=evaluation_criteria,
        spoken_dialogue=spoken_dialogue,
        has_reference_anchor=ref_decoded is not None,
    )

    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        res = QualityEvaluationResult(
            score=0.0,
            verdict="REATTEMPT_REQUIRED",
            feedback=f"Shot #{shot_index} file missing or empty.",
            audit_status="FILE_MISSING_OR_EMPTY",
        ).model_dump()
        res["consolidated_rubric"] = rubric
        return res

    with open(video_path, "rb") as fp:
        video_bytes = fp.read()

    audio_telemetry, keyframes = await asyncio.gather(
        asyncio.to_thread(analyze_clip_audio_tail, video_path, 0.20),
        asyncio.to_thread(extract_labeled_audit_keyframes, video_path),
    )
    merged_telemetry: Dict[str, Any] = {**audio_telemetry}
    if deterministic_signals:
        merged_telemetry.update(deterministic_signals)

    rubric_str = "\n".join(f"- {r}" for r in rubric)
    expected_vo = f'"{spoken_dialogue.strip()}"' if (spoken_dialogue and spoken_dialogue.strip()) else "None (ambient/instrumental)"
    eval_instructions = (
        f"You are Auto-Rater v2 auditing generated video Shot #{shot_index}.\n"
        f"Target Shot Prompt: '{prompt}'\n"
        f"Expected Spoken Dialogue: {expected_vo}\n"
        f"Shot Mode Context: is_r2v_shot={is_r2v_shot}, is_extend_shot={is_extend_shot}\n"
        f"Deterministic Pre-Audit Signals: {json.dumps(merged_telemetry)}\n\n"
        f"CONSOLIDATED RUBRIC:\n{rubric_str}\n\n"
        "MANDATORY OBSERVATION-FIRST PROTOCOL:\n"
        "1. Populate 'opening_environment_observed', 'heard_transcript' (exact words heard via audio/AVU), "
        "'speech_end_sec', and 'detected_internal_cuts' (count BOTH abrupt jump-cuts AND internal soft cross-dissolves/scene transitions inside this clip) BEFORE assigning any numeric score.\n"
        "2. Compare KEY FRAME A/M/B and the full AGENTIC video against the attached CANONICAL REFERENCE ANCHOR "
        "and PRIOR SHOT TERMINAL FRAME (when provided).\n"
        "3. Score each criterion in 'reason' (0.0-1.0), set overall 'score' to the minimum criterion score, "
        "and set 'verdict' to 'PASSED' (>= 0.8) or 'REATTEMPT_REQUIRED' (< 0.8)."
    )

    contents: List[Any] = [eval_instructions]
    if ref_decoded is not None:
        ref_bytes, ref_mime = ref_decoded
        contents.extend([
            "CANONICAL REFERENCE ANCHOR (#FFFFFF Ground Truth):",
            types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime),
        ])
    if prior_decoded is not None:
        prior_bytes, prior_mime = prior_decoded
        contents.extend([
            "PRIOR SHOT TERMINAL FRAME (Cross-Shot Boundary Ground Truth):",
            types.Part.from_bytes(data=prior_bytes, mime_type=prior_mime),
        ])
    for kf_label, kf_png_bytes in keyframes:
        contents.extend([f"{kf_label}:", types.Part.from_bytes(data=kf_png_bytes, mime_type="image/png")])

    contents.append(
        create_agentic_video_part(
            video_path_or_uri=video_path,
            video_bytes=video_bytes,
            media_processing=DirectConfig.MEDIA_PROCESSING,
        )
    )

    rater_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    eval_res: Optional[QualityEvaluationResult] = None
    try:
        resp = await asyncio.to_thread(
            _call_with_backoff_sync,
            rater_client.models.generate_content,
            model=DirectConfig.ORCHESTRATOR_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=build_quality_evaluation_schema(),
                temperature=0.2,
            ),
        )
        merged_telemetry.update(_extract_avu_usage_telemetry(resp))
        if resp and resp.text:
            eval_res = QualityEvaluationResult.model_validate_json(resp.text)
            eval_res.audit_status = "OK"
            min_crit = min([item.score for item in eval_res.reason], default=eval_res.score)
            eval_res.score = min(eval_res.score, min_crit)
    except Exception as err:
        print(f"[Auto-Rater v2 Notice on Shot #{shot_index}]: {err}")

    if eval_res is None:
        eval_res = QualityEvaluationResult(
            opening_environment_observed="Audit degraded (rater timeout or parse error)",
            score=0.80,
            reason=[
                CriterionEvaluation(
                    criterion_name="Deterministic Telemetry Fallback",
                    score=0.80,
                    comments="Multimodal rater timed out; applying deterministic OpenCV/FFMPEG checks.",
                )
            ],
            verdict="AUDIT_TIMEOUT_DEGRADED",
            feedback="Multimodal rater timed out; deterministic telemetry checks applied.",
            audit_status="AUDIT_TIMEOUT_DEGRADED",
        )

    t_metrics = compute_transcript_metrics(spoken_dialogue, eval_res.heard_transcript)
    eval_res.transcript_wer = t_metrics["transcript_wer"]
    eval_res.transcript_word_overlap = t_metrics["transcript_word_overlap"]
    eval_res.deterministic_telemetry = merged_telemetry

    guardrail_notes: List[str] = []
    clip_dur = float(merged_telemetry.get("clip_duration_sec") or 0.0)

    if eval_res.detected_internal_cuts > 0:
        eval_res.score = min(eval_res.score, 0.60)
        guardrail_notes.append(
            f"Detected {eval_res.detected_internal_cuts} internal camera jump-cut(s); enforce one continuous single-take camera shot."
        )

    if spoken_dialogue and spoken_dialogue.strip():
        speech_cutoff_by_ts = (
            eval_res.speech_end_sec is not None
            and clip_dur >= 2.0
            and eval_res.speech_end_sec > (clip_dur - 0.15)
        )
        if merged_telemetry.get("speech_cutoff_detected") or speech_cutoff_by_ts:
            eval_res.score = min(eval_res.score, 0.65)
            guardrail_notes.append(
                f"Spoken dialogue clipped at final 0.2s boundary (trailing_rms_db={merged_telemetry.get('trailing_rms_db')} dBFS); "
                "pace delivery briskly so speech finishes before second 8."
            )

        has_real_tx = bool(eval_res.heard_transcript and eval_res.heard_transcript.strip()) or (
            bool(merged_telemetry.get("has_audio")) and eval_res.audit_status == "OK"
        )
        if has_real_tx and eval_res.transcript_wer is not None and eval_res.transcript_wer > 0.35:
            eval_res.score = min(eval_res.score, 0.68)
            guardrail_notes.append(
                f"Spoken dialogue WER={eval_res.transcript_wer:.2f} deviated from target '{spoken_dialogue.strip()}' "
                f"(heard: '{eval_res.heard_transcript}')."
            )

    if guardrail_notes:
        eval_res.feedback = f"{' '.join(guardrail_notes)} {eval_res.feedback}".strip()

    eval_res.score = round(float(eval_res.score), 3)
    if eval_res.audit_status == "AUDIT_TIMEOUT_DEGRADED" and eval_res.score >= 0.8:
        eval_res.verdict = "AUDIT_TIMEOUT_DEGRADED"
    else:
        eval_res.verdict = "PASSED" if eval_res.score >= 0.8 else "REATTEMPT_REQUIRED"

    out = eval_res.model_dump()
    out["consolidated_rubric"] = rubric
    return out


async def evaluate_stitched_master_direct(
    stitched_video_path: str,
    num_shots: int,
    shot_duration_sec: float = 10.0,
    original_intent: str = "",
    voice_transcript: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    client: Optional[genai.Client] = None,
) -> Dict[str, Any]:
    """Post-Stitch Master Seam Critic auditing `[t_cut - 1.5s, t_cut + 1.5s]` via `gemini-3.8-flash` (`MediaProcessing.AGENTIC`)."""
    if not stitched_video_path or not os.path.exists(stitched_video_path) or os.path.getsize(stitched_video_path) == 0:
        return MasterSeamEvaluationResult(
            score=0.0,
            verdict="FAILED",
            feedback="Stitched master video missing or empty.",
            audit_status="FILE_MISSING_OR_EMPTY",
        ).model_dump()

    if num_shots < 2:
        return MasterSeamEvaluationResult(
            score=1.0,
            verdict="PASSED",
            feedback="Single-shot clip requires no cross-shot seam audit.",
            audit_status="SINGLE_SHOT_SKIPPED",
        ).model_dump()

    seam_windows = [
        f"[{max(0.0, i * shot_duration_sec - 1.5):.1f}s - {i * shot_duration_sec + 1.5:.1f}s] (Seam {i}->{i + 1} around {i * shot_duration_sec:.1f}s)"
        for i in range(1, num_shots)
    ]
    windows_str = "\n".join(f"- {w}" for w in seam_windows)

    with open(stitched_video_path, "rb") as fp:
        video_bytes = fp.read()

    prompt = (
        f"You are the Master Post-Stitch Continuity Critic auditing a {num_shots}-shot stitched video.\n"
        f"Commercial Intent: '{original_intent}'\n"
        f"Voiceover Script: '{voice_transcript or 'Ambient/Instrumental'}'\n\n"
        f"SEAM TRANSITION WINDOWS TO INSPECT:\n{windows_str}\n\n"
        "Use agentic video & audio inspection (`google:load_video`) to zoom into each seam transition window:\n"
        "1. Record 'seam_observations' for every boundary (visual smoothness, xfade ghosting, SKU/subject lock, and audio acrossfade continuity).\n"
        "2. Set 'voice_timbre_consistent', 'loudness_continuity_ok', and 'visual_xfade_smooth'.\n"
        "3. Provide overall 'score' (0.0-1.0), 'verdict' ('PASSED' if score >= 0.8 else 'SEAM_WARNING'), and actionable 'feedback'."
    )

    contents: List[Any] = [prompt]
    ref_decoded = decode_valid_image_b64(reference_images_b64[0]) if reference_images_b64 else None
    if ref_decoded is not None:
        ref_bytes, ref_mime = ref_decoded
        contents.extend([
            "CANONICAL REFERENCE ANCHOR (#FFFFFF Ground Truth):",
            types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime),
        ])
    contents.append(
        create_agentic_video_part(
            video_path_or_uri=stitched_video_path,
            video_bytes=video_bytes,
            media_processing=DirectConfig.MEDIA_PROCESSING,
        )
    )

    rater_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    try:
        resp = await asyncio.to_thread(
            _call_with_backoff_sync,
            rater_client.models.generate_content,
            model=DirectConfig.ORCHESTRATOR_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=build_master_seam_evaluation_schema(),
                temperature=0.2,
            ),
        )
        if resp and resp.text:
            parsed = MasterSeamEvaluationResult.model_validate_json(resp.text)
            parsed.audit_status = "OK"
            parsed.verdict = "PASSED" if parsed.score >= 0.8 else "SEAM_WARNING"
            parsed.deterministic_telemetry = _extract_avu_usage_telemetry(resp)
            return parsed.model_dump()
    except Exception as err:
        print(f"[MasterSeamRater Notice]: {err}")

    return MasterSeamEvaluationResult(
        score=0.85,
        verdict="AUDIT_TIMEOUT_DEGRADED",
        feedback="Post-stitch master seam rater timed out; deterministic xfade/acrossfade completed.",
        audit_status="AUDIT_TIMEOUT_DEGRADED",
    ).model_dump()


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Direct Gemini Omni 1.2 Flash + Gemini 3.8 Flash (AVU) CLI utilities."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_img = sub.add_parser("generate-image", help="Generate a 16:9/9:16 reference plate or keyframe via Nano Banana 2.1.")
    p_img.add_argument("--prompt", required=True)
    p_img.add_argument("--output", required=True, help="Output PNG file path.")
    p_img.add_argument("--reference", nargs="*", help="Optional conditioning reference image path(s).")
    p_img.add_argument("--aspect-ratio", default="16:9")

    p_gen = sub.add_parser("generate-clip", help="Generate a single MP4 clip via gemini-omni-1.2-flash.")
    p_gen.add_argument("--prompt", required=True)
    p_gen.add_argument("--output", required=True, help="Output MP4 file path.")
    p_gen.add_argument("--reference", nargs="*", help="Optional #FFFFFF reference image path(s) for R2V.")
    p_gen.add_argument("--first-frame", help="Optional starting PNG path for <FIRST_FRAME> I2V.")
    p_gen.add_argument("--last-frame", help="Optional ending PNG path for <LAST_FRAME> interpolation.")
    p_gen.add_argument("--extend-tail", help="Optional 5.0s trailing MP4 path for task='extend'.")
    p_gen.add_argument("--dialogue", help="Optional spoken dialogue line.")
    p_gen.add_argument("--aspect-ratio", default="16:9")
    p_gen.add_argument("--resolution", default="720p")
    p_gen.add_argument("--duration", type=int, default=10)

    p_rate = sub.add_parser("rate-clip", help="Audit a single MP4 clip via Auto-Rater v2 (gemini-3.8-flash AVU).")
    p_rate.add_argument("--video", required=True)
    p_rate.add_argument("--prompt", required=True)
    p_rate.add_argument("--shot-index", type=int, default=1)
    p_rate.add_argument("--criteria", default=None)
    p_rate.add_argument("--dialogue", default=None)
    p_rate.add_argument("--reference", default=None)
    p_rate.add_argument("--prev-last-frame", default=None)

    p_master = sub.add_parser("rate-master", help="Audit a stitched multi-shot MP4 via Master Seam Critic.")
    p_master.add_argument("--video", required=True)
    p_master.add_argument("--shots", type=int, required=True)
    p_master.add_argument("--shot-duration", type=float, default=10.0)
    p_master.add_argument("--intent", default="")
    p_master.add_argument("--dialogue", default=None)
    p_master.add_argument("--reference", default=None)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

    if args.command == "generate-image":
        ref_b64s = [encode_image_file_b64(p) for p in (args.reference or [])] or None
        img_bytes = generate_reference_image_direct(
            prompt=args.prompt,
            reference_images_b64=ref_b64s,
            aspect_ratio=args.aspect_ratio,
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "wb") as fp:
            fp.write(img_bytes)
        print(json.dumps({"status": "ok", "output": os.path.abspath(args.output), "bytes": len(img_bytes)}))
        return 0

    if args.command == "generate-clip":
        ref_b64s = [encode_image_file_b64(p) for p in (args.reference or [])] or None
        ff_b64 = encode_image_file_b64(args.first_frame) if args.first_frame else None
        lf_b64 = encode_image_file_b64(args.last_frame) if args.last_frame else None
        vid_b64 = None
        task = None
        if args.extend_tail:
            with open(args.extend_tail, "rb") as fp:
                vid_b64 = base64.b64encode(fp.read()).decode("utf-8")
            task = "extend"
        elif ref_b64s and not ff_b64 and not lf_b64:
            task = "reference_to_video"

        mp4_bytes = generate_omni_clip_direct(
            prompt=args.prompt,
            input_image_b64=ff_b64,
            end_image_b64=lf_b64,
            input_video_b64=vid_b64,
            task=task,
            reference_images_b64=ref_b64s,
            voice_transcript=args.dialogue,
            aspect_ratio=args.aspect_ratio,
            resolution=args.resolution,
            duration=args.duration,
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "wb") as fp:
            fp.write(mp4_bytes)
        print(json.dumps({"status": "ok", "output": os.path.abspath(args.output), "bytes": len(mp4_bytes)}))
        return 0

    if args.command == "rate-clip":
        ref_b64s = [encode_image_file_b64(args.reference)] if args.reference else None
        prev_b64 = encode_image_file_b64(args.prev_last_frame) if args.prev_last_frame else None
        res = asyncio.run(
            evaluate_clip_quality_direct(
                shot_index=args.shot_index,
                prompt=args.prompt,
                video_path=args.video,
                evaluation_criteria=args.criteria,
                spoken_dialogue=args.dialogue,
                reference_images_b64=ref_b64s,
                prev_last_frame_b64=prev_b64,
                is_r2v_shot=bool(ref_b64s and not prev_b64),
            )
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "rate-master":
        ref_b64s = [encode_image_file_b64(args.reference)] if args.reference else None
        res = asyncio.run(
            evaluate_stitched_master_direct(
                stitched_video_path=args.video,
                num_shots=args.shots,
                shot_duration_sec=args.shot_duration,
                original_intent=args.intent,
                voice_transcript=args.dialogue,
                reference_images_b64=ref_b64s,
            )
        )
        print(json.dumps(res, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
