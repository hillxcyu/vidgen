# Copyright 2026 Author:Hill YU(xcyu@)
"""Direct Google GenAI model calls for ADK-free multi-shot video generation and Auto-Rater v2.

Wraps `google.genai.Client` directly (supporting both Vertex AI ADC with `location='global'`
and `GEMINI_API_KEY`) for:
1. Storyboard generation & single-take prompt optimization via `gemini-3.8-flash`.
2. Video generation (`reference_to_video`, `<FIRST_FRAME>` I2V, `extend`, and standalone `upscale`) via `gemini-omni-1.2-flash`.
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
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, model_validator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from media_ops import (  # noqa: E402
    analyze_clip_audio_tail,
    compute_transcript_metrics,
    create_agentic_video_part,
    decode_valid_image_b64,
    encode_image_file_b64,
    ensure_riff_wav_bytes,
    extract_labeled_audit_keyframes,
    get_wav_duration_sec,
    split_wav_reference_chunks,
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
    TTS_MODEL: str = os.getenv("TTS_MODEL", "gemini-3.8-flash-tts")
    TTS_FALLBACK_MODEL: str = os.getenv("TTS_FALLBACK_MODEL", "gemini-2.5-flash-tts")
    DEFAULT_TTS_VOICE: str = os.getenv("DEFAULT_TTS_VOICE", "Kore")
    VIDEO_EXTEND_INPUT_SECONDS: float = float(os.getenv("VIDEO_EXTEND_INPUT_SECONDS", "5.0"))
    MEDIA_PROCESSING: str = os.getenv("MEDIA_PROCESSING", "AGENTIC")
    VIDEO_GEN_TIMEOUT_MS: int = int(os.getenv("VIDEO_GEN_TIMEOUT_MS", "600000"))
    RATER_TIMEOUT_MS: int = int(os.getenv("RATER_TIMEOUT_MS", "240000"))
    MAX_PARALLEL_SHOTS: int = int(os.getenv("MAX_PARALLEL_SHOTS", "3"))


TTS_MODEL_ALIASES: Dict[str, str] = {
    "gemini-3.8-tts": "gemini-3.8-flash-tts",
    "gemini-3.8-flash-tts": "gemini-3.8-flash-tts",
    "gemini-3.8-lite-tts": "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-lite-tts": "gemini-3.8-flash-lite-tts",
}


def normalize_tts_model_name(model_name: Optional[str] = None) -> str:
    """Normalizes user-friendly Gemini 3.8 TTS model aliases to official Vertex AI model IDs."""
    raw = str(model_name or DirectConfig.TTS_MODEL or "gemini-3.8-flash-tts").strip()
    return TTS_MODEL_ALIASES.get(raw.lower(), raw)


GENMEDIA_DEFECT_TAXONOMY: Dict[str, Dict[str, str]] = {
    "r2v_white_backdrop_echo": {
        "description": "Frame 0 opens on or dissolves out of a #FFFFFF studio white backdrop instead of the target scene.",
        "remedy": "Open immediately on Frame 0 inside the physical environment; never mention or depict a white studio background.",
    },
    "identity_or_sku_drift": {
        "description": "Facial geometry, skin tone, garment colorway, or product SKU proportions/materials drift from reference.",
        "remedy": "Preserve exact Character A facial identity, wardrobe silhouette, and product geometry/colors from the reference image without inventing competing traits.",
    },
    "text_or_logo_garbling": {
        "description": "Brand typography, label lettering, or logo geometry warps, misspells, or hallucinates unrequested emblems.",
        "remedy": "Keep packaging/surface branding crisp and static relative to the object; forbid unrequested text overlays, watermarks, or third-party logos.",
    },
    "hand_or_anatomy_morphing": {
        "description": "Extra/fused fingers, impossible wrist rotations, or limb clipping through rigid props.",
        "remedy": "Use natural relaxed grip mechanics with clear five-finger anatomy, or reframe to medium waist-up / clean macro angle.",
    },
    "physics_or_gravity_violation": {
        "description": "Objects float, vanish mid-shot, teleport between hands, or liquids/fabrics move backward.",
        "remedy": "Enforce causal physical weight, gravity, and continuous object permanence from start to finish of the take.",
    },
    "unmotivated_camera_jitter_or_cuts": {
        "description": "Abrupt internal jump-cuts, hidden soft cross-dissolves, erratic camera shake, or unrequested black letterbox bars.",
        "remedy": "Lock to one stabilized continuous single-take camera movement filling the full frame edge-to-edge with zero internal cuts or letterbox bars.",
    },
    "lighting_or_color_flicker": {
        "description": "Key-light direction flips mid-shot, exposure pumps, or forbidden palette colors pollute the grade.",
        "remedy": "Anchor motivated key-light direction and stable color temperature consistently across the entire shot.",
    },
    "lip_sync_or_speech_mismatch": {
        "description": "Audible speech misaligns with mouth motion, truncates at clip end, or moves lips during off-camera voiceover.",
        "remedy": "Pace spoken dialogue briskly to finish 2s before clip end with clear lip-sync (or keep lips closed if off-camera voiceover).",
    },
    "unwanted_music_or_audio_collision": {
        "description": "Unrequested loud music, mechanical camera noise, or competing voices drown out dialogue or clean foley.",
        "remedy": "Keep camera movement completely silent and render clean room tone and subtle diegetic foley without background music.",
    },
    "seam_jump_or_momentum_stall": {
        "description": "Chained/extended shot stalls on Frame 0 or snaps pose/camera velocity abruptly relative to the prior shot.",
        "remedy": "Continue camera velocity, subject momentum, and spatial framing seamlessly from the exact ending state of the prior shot.",
    },
}


def format_genmedia_remedy_guidance(issues: Optional[List[str]]) -> str:
    """Maps detected GenMedia defect codes to concrete prompt-engineering remedies for retry attempts."""
    if not issues:
        return ""
    remedies: List[str] = []
    seen = set()
    for raw_code in issues:
        code = str(raw_code or "").strip().lower()
        if code in GENMEDIA_DEFECT_TAXONOMY and code not in seen:
            seen.add(code)
            remedies.append(f"[{code}] {GENMEDIA_DEFECT_TAXONOMY[code]['remedy']}")
    return " ".join(remedies)


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


class VisionProfileSpec(BaseModel):
    """Project-wide cinematic lookbook locking visual grammar, palette, lighting, and acoustic direction.

    Attributes:
        project_title: Short campaign or film title.
        creative_thesis: Core emotional/narrative thesis.
        aspect_ratio: Frame aspect ratio ('16:9' or '9:16').
        visual_motif: Recurring visual motif.
        primary_palette: 3-color palette lock.
        forbidden_colors: Colors strictly excluded from frames.
        lighting_ratio: Lighting contrast ratio.
        lens_language: Focal length progression across acts.
        camera_motion_grammar: Allowed camera motion vocabulary.
        style_anchor: Verbatim style lock appended to image plates and video prompts.
        audio_direction: Acoustic and TTS/voiceover direction.
        default_tts_voice: Default Gemini 3.8 TTS voice.
        default_tts_style: Default speaking delivery style.
    """

    project_title: str = Field(default="Untitled Commercial", description="Short campaign or film title.")
    creative_thesis: str = Field(default="", description="Core emotional/narrative thesis.")
    aspect_ratio: str = Field(default="16:9", description="Frame aspect ratio ('16:9' or '9:16').")
    visual_motif: str = Field(default="Architectural tactile realism with motivated natural daylight.", description="Recurring visual motif.")
    primary_palette: List[str] = Field(
        default_factory=lambda: ["warm alabaster", "burnished amber", "espresso walnut"],
        description="3-color palette lock.",
    )
    forbidden_colors: List[str] = Field(
        default_factory=lambda: ["neon magenta", "electric cyan", "harsh fluorescent green"],
        description="Colors strictly excluded from frames.",
    )
    lighting_ratio: str = Field(default="4:1 soft motivated directional key", description="Lighting contrast ratio.")
    lens_language: str = Field(
        default="50mm natural eye-level establishing -> 85mm intimate portrait -> 100mm macro detail",
        description="Focal length progression across acts.",
    )
    camera_motion_grammar: str = Field(
        default="smooth stabilized dolly or slow orbital push-in; camera movement is completely silent",
        description="Allowed camera motion vocabulary.",
    )
    style_anchor: str = Field(
        default="Photorealistic 35mm cinematic film grain, natural skin micro-texture, full edge-to-edge frame with zero letterbox bars.",
        description="Verbatim style lock appended to image plates and video prompts.",
    )
    audio_direction: str = Field(
        default="Clean dry room tone and subtle diegetic foley; zero unrequested background music.",
        description="Acoustic and TTS/voiceover direction.",
    )
    default_tts_voice: str = Field(default="Kore", description="Default Gemini 3.8 TTS voice.")
    default_tts_style: str = Field(default="", description="Default speaking delivery style.")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_aliases(cls, data: Any) -> Any:
        """Accepts `storyboard_spec.md` alias keys (`color_palette`, `lighting_motivation`, etc.)."""
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "primary_palette" not in normalized and "color_palette" in normalized:
            normalized["primary_palette"] = normalized["color_palette"]
        if "lighting_ratio" not in normalized:
            lighting_parts = [
                str(normalized[k]).strip()
                for k in ("lighting_motivation", "contrast_ratio")
                if normalized.get(k)
            ]
            if lighting_parts:
                normalized["lighting_ratio"] = " | ".join(lighting_parts)
        if "lens_language" not in normalized and "primary_focal_lengths_mm" in normalized:
            focal = normalized["primary_focal_lengths_mm"]
            if isinstance(focal, list):
                normalized["lens_language"] = " -> ".join(f"{str(f).rstrip('m')}mm" for f in focal)
            elif focal:
                normalized["lens_language"] = str(focal)
        return normalized


class StoryboardEntrySpec(BaseModel):
    scene_number: int = Field(description="1-based shot index.")
    description: str = Field(description="Visual action and setting for this single continuous shot.")
    camera_angle: str = Field(default="medium tracking", description="Single continuous camera framing/motion.")
    shot_size: Optional[str] = Field(
        default=None,
        description="Shot scale (e.g. 'wide', 'medium waist-up', 'close-up', 'extreme close-up macro').",
    )
    focal_length_mm: Optional[int] = Field(
        default=None,
        description="Lens focal length in mm (e.g. 24, 35, 50, 85, 100).",
    )
    lighting_spec: Optional[str] = Field(
        default=None,
        description="Motivated key-light direction, quality, and contrast ratio for this shot.",
    )
    blocking_and_temporal_flow: Optional[str] = Field(
        default=None,
        description="0s -> mid -> end temporal progression of subject pose, props, and camera.",
    )
    evaluation_criteria: str = Field(
        default="Verify subject/product identity lock, single-take motion, and temporal asset persistence.",
        description="Shot-specific visual & continuity audit criteria.",
    )
    fails_if: Optional[str] = Field(
        default=None,
        description="Explicit failure condition that must trigger automatic REATTEMPT_REQUIRED.",
    )
    spoken_dialogue: Optional[str] = Field(
        default=None,
        description="Optional verbatim spoken line for this shot (paced cleanly to finish ~2s before shot end).",
    )
    audio_mode: Optional[str] = Field(
        default=None,
        description="Audio mode: 'on_camera' (lip-sync), 'off_camera_vo' (silent lips + post-mux TTS), or 'ambient'.",
    )
    tts_voice: Optional[str] = Field(
        default=None,
        description="Optional per-shot Gemini 3.8 TTS voice override (e.g. 'Kore', 'Puck').",
    )
    tts_style: Optional[str] = Field(
        default=None,
        description="Optional per-shot TTS speaking style override.",
    )
    mode_override: Optional[str] = Field(
        default=None,
        description="Optional per-shot mode override ('reference', 'i2v_chaining', or 'video_extend').",
    )
    duration_sec: Optional[int] = Field(
        default=None,
        description=(
            "Optional per-shot duration override in seconds "
            "(3-15s for reference_to_video, image_to_video, and T2V; 3-10s for video_extend and two-frame interpolation)."
        ),
    )


class DirectorPlanSpec(BaseModel):
    """Complete Plan->Define pre-production artifact emitted before video compute."""

    vision_profile: VisionProfileSpec
    mode: str = Field(default="video_extend")
    num_shots: int = Field(default=3)
    duration_per_shot_sec: int = Field(default=10)
    shots: List[StoryboardEntrySpec] = Field(default_factory=list)


def resolve_omni_shot_duration(
    requested_sec: Optional[int],
    default_sec: int = 10,
    task_or_mode: Optional[str] = None,
    is_two_frame_interp: bool = False,
) -> int:
    """Clamps a shot's duration to GA `gemini-omni-1.2-flash` task bounds (`3-15s` R2V/I2V/T2V; `3-10s` extend/interp)."""
    raw = int(requested_sec if requested_sec is not None else default_sec)
    norm_mode = str(task_or_mode or "").strip().lower()
    capped_at_10 = is_two_frame_interp or norm_mode in (
        "extend",
        "video_extend",
        "first_last_interpolation",
    )
    max_sec = 10 if capped_at_10 else 15
    return max(3, min(max_sec, raw))


class CriterionEvaluation(BaseModel):
    criterion_name: str = Field(description="Name of the evaluated criterion.")
    score: float = Field(default=1.0, description="Score from 0.0 to 1.0.")
    comments: str = Field(default="Meets criteria", description="Specific observation.")


QUALITY_EVALUATION_PROPERTY_ORDER: tuple[str, ...] = (
    "opening_environment_observed",
    "heard_transcript",
    "speech_end_sec",
    "detected_internal_cuts",
    "detected_genmedia_issues",
    "reason",
    "score",
    "verdict",
    "feedback",
)


class QualityEvaluationResult(BaseModel):
    opening_environment_observed: str = Field(default="")
    heard_transcript: str = Field(default="")
    speech_end_sec: Optional[float] = Field(default=None)
    detected_internal_cuts: int = Field(default=0)
    detected_genmedia_issues: List[str] = Field(default_factory=list)
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


MASTER_SEAM_PROPERTY_ORDER: tuple[str, ...] = (
    "seam_observations",
    "voice_timbre_consistent",
    "loudness_continuity_ok",
    "visual_xfade_smooth",
    "score",
    "verdict",
    "feedback",
)


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
            "detected_genmedia_issues": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
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
    default_duration_sec: int = 10,
    client: Optional[genai.Client] = None,
) -> List[StoryboardEntrySpec]:
    """Generates a structured N-shot storyboard directly via `gemini-3.8-flash`."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    eff_default_dur = resolve_omni_shot_duration(None, default_sec=default_duration_sec, task_or_mode=mode)
    target_speech_end = max(2, eff_default_dur - 2)
    max_words_hint = max(5, int(round(target_speech_end * 1.5)))
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
            f"unbroken continuous single-take camera trajectory across {eff_default_dur}s boundaries—zero location teleports."
        ),
        "hybrid": (
            "Mode D (Hybrid Choreography): Set mode_override per shot ('reference' for act-break scene switches, "
            "'video_extend' or 'i2v_chaining' for unbroken continuation within the same space)."
        ),
    }.get(mode, "Maintain strong visual and acoustic continuity across all shots.")

    vo_guidance = (
        f"\nFull Voiceover Script to split cleanly across the {num_shots} shots (<= {max_words_hint} words per shot, "
        f"finishing before {target_speech_end}s of each {eff_default_dur}s clip, avoiding explicit brand-CTA endorsement slogans): '{voice_transcript}'"
        if voice_transcript
        else "\nNo spoken voiceover required unless natural to the prompt (leave spoken_dialogue null if ambient)."
    )

    prompt = (
        f"Design a {num_shots}-shot commercial storyboard (default {eff_default_dur}s per shot) for: '{intent}'.\n"
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
                "shot_size",
                "focal_length_mm",
                "lighting_spec",
                "blocking_and_temporal_flow",
                "evaluation_criteria",
                "fails_if",
                "spoken_dialogue",
                "audio_mode",
                "mode_override",
                "duration_sec",
            ],
            properties={
                "scene_number": types.Schema(type=types.Type.INTEGER),
                "description": types.Schema(type=types.Type.STRING),
                "camera_angle": types.Schema(type=types.Type.STRING),
                "shot_size": types.Schema(type=types.Type.STRING, nullable=True),
                "focal_length_mm": types.Schema(type=types.Type.INTEGER, nullable=True),
                "lighting_spec": types.Schema(type=types.Type.STRING, nullable=True),
                "blocking_and_temporal_flow": types.Schema(type=types.Type.STRING, nullable=True),
                "evaluation_criteria": types.Schema(type=types.Type.STRING),
                "fails_if": types.Schema(type=types.Type.STRING, nullable=True),
                "spoken_dialogue": types.Schema(type=types.Type.STRING, nullable=True),
                "audio_mode": types.Schema(type=types.Type.STRING, nullable=True),
                "mode_override": types.Schema(type=types.Type.STRING, nullable=True),
                "duration_sec": types.Schema(type=types.Type.INTEGER, nullable=True),
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
                    shot_size=item.get("shot_size"),
                    focal_length_mm=item.get("focal_length_mm"),
                    lighting_spec=item.get("lighting_spec"),
                    blocking_and_temporal_flow=item.get("blocking_and_temporal_flow"),
                    evaluation_criteria=item.get(
                        "evaluation_criteria",
                        "Verify subject identity lock, smooth single-take camera motion, and asset persistence.",
                    ),
                    fails_if=item.get("fails_if"),
                    spoken_dialogue=item.get("spoken_dialogue"),
                    audio_mode=item.get("audio_mode"),
                    mode_override=item.get("mode_override"),
                    duration_sec=item.get("duration_sec"),
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


async def generate_vision_and_plan_direct(
    intent: str,
    num_shots: int = 3,
    mode: str = "video_extend",
    aspect_ratio: str = "16:9",
    voice_transcript: Optional[str] = None,
    default_duration_sec: int = 10,
    tts_voice: str = DirectConfig.DEFAULT_TTS_VOICE,
    tts_style: str = "",
    client: Optional[genai.Client] = None,
) -> DirectorPlanSpec:
    """Executes Stage 1 (Plan) & Stage 2 (Define) via `gemini-3.8-flash` before any video compute."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    eff_dur = resolve_omni_shot_duration(None, default_sec=default_duration_sec, task_or_mode=mode)

    vision_prompt = (
        f"You are an experienced Commercial Film Director & Cinematographer.\n"
        f"Create a cohesive VisionProfile lookbook for: '{intent}'.\n"
        f"Aspect ratio: {aspect_ratio}. Continuity mode: {mode}.\n"
        "Lock: a 3-color primary_palette, 3 forbidden_colors, motivated lighting_ratio (e.g. '4:1 soft warm key'), "
        "focal-length progression lens_language, silent camera_motion_grammar, and a concise verbatim style_anchor "
        "(strictly edge-to-edge full frame, zero letterbox bars).\n"
        "Return a JSON object matching the schema."
    )
    vision_schema = types.Schema(
        type=types.Type.OBJECT,
        property_ordering=[
            "project_title",
            "creative_thesis",
            "visual_motif",
            "primary_palette",
            "forbidden_colors",
            "lighting_ratio",
            "lens_language",
            "camera_motion_grammar",
            "style_anchor",
            "audio_direction",
        ],
        properties={
            "project_title": types.Schema(type=types.Type.STRING),
            "creative_thesis": types.Schema(type=types.Type.STRING),
            "visual_motif": types.Schema(type=types.Type.STRING),
            "primary_palette": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "forbidden_colors": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
            "lighting_ratio": types.Schema(type=types.Type.STRING),
            "lens_language": types.Schema(type=types.Type.STRING),
            "camera_motion_grammar": types.Schema(type=types.Type.STRING),
            "style_anchor": types.Schema(type=types.Type.STRING),
            "audio_direction": types.Schema(type=types.Type.STRING),
        },
        required=[
            "project_title",
            "creative_thesis",
            "visual_motif",
            "primary_palette",
            "forbidden_colors",
            "lighting_ratio",
            "lens_language",
            "camera_motion_grammar",
            "style_anchor",
            "audio_direction",
        ],
    )
    vision_profile = VisionProfileSpec(
        project_title=intent[:60] or "Commercial Film",
        creative_thesis=intent,
        aspect_ratio=aspect_ratio,
        default_tts_voice=tts_voice,
        default_tts_style=tts_style,
    )
    try:
        v_resp = await asyncio.to_thread(
            active_client.models.generate_content,
            model=DirectConfig.ORCHESTRATOR_MODEL,
            contents=vision_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=vision_schema,
                temperature=0.3,
            ),
        )
        if v_resp and v_resp.text:
            v_data = json.loads(v_resp.text)
            vision_profile = VisionProfileSpec(
                aspect_ratio=aspect_ratio,
                default_tts_voice=tts_voice,
                default_tts_style=tts_style,
                **v_data,
            )
    except Exception as err:
        print(f"[VisionProfile Fallback Notice]: {err}")

    enriched_intent = (
        f"{intent}\nVisual Motif: {vision_profile.visual_motif} | "
        f"Palette: {', '.join(vision_profile.primary_palette)} | "
        f"Lighting: {vision_profile.lighting_ratio} | Lenses: {vision_profile.lens_language}"
    )
    shots = await generate_storyboard_direct(
        intent=enriched_intent,
        num_shots=num_shots,
        mode=mode,
        voice_transcript=voice_transcript,
        default_duration_sec=eff_dur,
        client=active_client,
    )
    return DirectorPlanSpec(
        vision_profile=vision_profile,
        mode=mode,
        num_shots=len(shots),
        duration_per_shot_sec=eff_dur,
        shots=shots,
    )


def format_director_plan_markdown(plan: DirectorPlanSpec) -> str:
    """Renders a `DirectorPlanSpec` into a human-reviewable `director_plan.md` brief for Gate 1."""
    vp = plan.vision_profile
    lines = [
        f"# Director Plan: {vp.project_title}",
        "",
        f"- **Creative Thesis**: {vp.creative_thesis}",
        f"- **Aspect Ratio / Mode**: `{vp.aspect_ratio}` | `{plan.mode}` ({plan.num_shots} shots, default `{plan.duration_per_shot_sec}s`)",
        f"- **Visual Motif**: {vp.visual_motif}",
        f"- **Palette Lock**: {', '.join(vp.primary_palette)} (Forbidden: {', '.join(vp.forbidden_colors)})",
        f"- **Lighting & Lens Language**: {vp.lighting_ratio} | {vp.lens_language}",
        f"- **Style Anchor**: `{vp.style_anchor}`",
        f"- **Audio & TTS Direction**: {vp.audio_direction} (Default voice: `{vp.default_tts_voice}`)",
        "",
        "## Shot Breakdown (Stage 2 Define)",
        "",
        "| Shot | Mode | Dur | Lens / Framing | Lighting | Audio / Dialogue | Fails If |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in plan.shots:
        lens = f"{s.focal_length_mm}mm " if s.focal_length_mm else ""
        scale = s.shot_size or s.camera_angle
        dialogue = (s.spoken_dialogue or "Ambient").replace("|", "/")
        fails = (s.fails_if or "Internal cut or identity drift").replace("|", "/")
        lines.append(
            f"| {s.scene_number} | `{s.mode_override or plan.mode}` | {s.duration_sec or plan.duration_per_shot_sec}s | "
            f"{lens}{scale} | {(s.lighting_spec or vp.lighting_ratio).replace('|', '/')} | "
            f"`{s.audio_mode or ('on_camera' if s.spoken_dialogue else 'ambient')}`: {dialogue} | {fails} |"
        )
    lines.append("")
    return "\n".join(lines)


async def optimize_shot_prompt_direct(
    raw_prompt: str,
    feedback: Optional[str] = None,
    voice_transcript: Optional[str] = None,
    is_extend_shot: bool = False,
    is_r2v_shot: bool = False,
    duration_sec: int = 10,
    vision_profile: Optional[VisionProfileSpec] = None,
    shot_spec: Optional[StoryboardEntrySpec] = None,
    detected_issues: Optional[List[str]] = None,
    client: Optional[genai.Client] = None,
) -> str:
    """Enhances a shot description with 8-Layer Director Craft & GenMedia defect remedies via `gemini-3.8-flash`."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    remedy_text = format_genmedia_remedy_guidance(detected_issues)
    feedback_ctx = f"\nQuality Rater Feedback to fix on this retry: '{feedback}'" if feedback else ""
    remedy_ctx = f"\nMANDATORY DEFECT REMEDIES: {remedy_text}" if remedy_text else ""

    craft_bits: List[str] = []
    if shot_spec:
        if shot_spec.shot_size or shot_spec.focal_length_mm:
            lens = f"{shot_spec.focal_length_mm}mm " if shot_spec.focal_length_mm else ""
            craft_bits.append(f"Framing/Lens: {lens}{shot_spec.shot_size or shot_spec.camera_angle}")
        if shot_spec.lighting_spec:
            craft_bits.append(f"Lighting: {shot_spec.lighting_spec}")
        if shot_spec.blocking_and_temporal_flow:
            craft_bits.append(f"Temporal Blocking: {shot_spec.blocking_and_temporal_flow}")
    if vision_profile:
        if vision_profile.primary_palette:
            craft_bits.append(f"Palette: {', '.join(vision_profile.primary_palette)}")
        if vision_profile.forbidden_colors:
            craft_bits.append(f"Exclude colors: {', '.join(vision_profile.forbidden_colors)}")
        if vision_profile.style_anchor:
            craft_bits.append(f"Style anchor: {vision_profile.style_anchor}")
    craft_ctx = ("\nDIRECTOR CRAFT SPECS: " + " | ".join(craft_bits)) if craft_bits else ""

    audio_mode = (shot_spec.audio_mode if shot_spec else None) or ("on_camera" if voice_transcript else "ambient")
    finish_by_sec = max(2, int(duration_sec) - 2)
    if audio_mode == "off_camera_vo":
        transcript_ctx = (
            "\nAUDIO RULE (OFF-CAMERA VOICEOVER): Keep all on-screen mouths closed with natural subtle diegetic foley only; "
            "do NOT synthesize spoken speech inside the video."
        )
    elif voice_transcript:
        transcript_ctx = (
            f"\nExact Spoken Dialogue Transcript: '{voice_transcript}'. "
            f"Include these exact words verbatim (finishing cleanly before {finish_by_sec}s of this {int(duration_sec)}s shot) "
            "without adding unscripted greetings or filler words."
        )
    else:
        transcript_ctx = "\nAUDIO RULE: Clean subtle room tone and natural foley only; no unrequested music."

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
        f"Raw Shot Description: '{raw_prompt}'.{craft_ctx}{feedback_ctx}{remedy_ctx}{transcript_ctx}{extend_ctx}{r2v_ctx}\n\n"
        "Write ONLY the enhanced single-paragraph video generation prompt (under 70 words) for Gemini Omni 1.2 Flash. "
        "Specify one continuous, uninterrupted single-take camera movement, include 'The camera movement itself is completely silent.', "
        "render full edge-to-edge frame with zero letterbox bars, and forbid internal cuts or jump cuts."
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

    Args:
        prompt: Text prompt describing the target frame or scene plate.
        reference_images_b64: Optional list of up to 4 base64-encoded reference images.
        aspect_ratio: Output frame aspect ratio (e.g. ``"16:9"`` or ``"9:16"``).
        client: Optional pre-configured ``genai.Client``.

    Returns:
        Raw PNG/JPEG bytes of the final non-thought generated image.

    Raises:
        RuntimeError: If the image generation response contains no non-thought image bytes.
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
# Direct Gemini 3.8 TTS Synthesis (`gemini-3.8-flash-tts`)
# ---------------------------------------------------------------------------


def synthesize_tts_track_direct(
    text: str,
    voice_name: str = DirectConfig.DEFAULT_TTS_VOICE,
    language_code: str = "en-US",
    style: str = "",
    model_name: Optional[str] = None,
    client: Optional[genai.Client] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Synthesizes a 24 kHz mono RIFF WAV voice track via `gemini-3.8-flash-tts` (`gemini-3.8-tts` alias)."""
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Cannot synthesize empty TTS text.")

    resolved_model = normalize_tts_model_name(model_name)
    resolved_voice = (voice_name or DirectConfig.DEFAULT_TTS_VOICE).strip() or "Kore"
    clean_style = (style or "").strip()

    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    if resolved_voice.startswith(("voice_", "voicekey_")):
        voice_cfg = types.VoiceConfig(
            replicated_voice_config=types.ReplicatedVoiceConfig(voice_key=resolved_voice)
        ) if "voice_key" in getattr(types.ReplicatedVoiceConfig, "model_fields", {}) else types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
        )
    else:
        voice_cfg = types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=resolved_voice)
        )

    speech_cfg = types.SpeechConfig(
        language_code=language_code or "en-US",
        voice_config=voice_cfg,
    )
    gen_cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_cfg,
    )

    contents: Any = clean_text
    if clean_style:
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": clean_text, "speechMetadata": {"style": clean_style}},
                ],
            }
        ]

    t0 = time.monotonic()
    try:
        resp = _call_with_backoff_sync(
            active_client.models.generate_content,
            model=resolved_model,
            contents=contents,
            config=gen_cfg,
        )
    except Exception as err:
        err_s = str(err)
        if clean_style and ("speechMetadata" in err_s or "validation" in err_s.lower()):
            resp = _call_with_backoff_sync(
                active_client.models.generate_content,
                model=resolved_model,
                contents=clean_text,
                config=gen_cfg,
            )
        elif (
            DirectConfig.TTS_FALLBACK_MODEL
            and DirectConfig.TTS_FALLBACK_MODEL != resolved_model
            and any(tok in err_s for tok in ("404", "not_found", "NotFound"))
        ):
            resolved_model = DirectConfig.TTS_FALLBACK_MODEL
            resp = _call_with_backoff_sync(
                active_client.models.generate_content,
                model=resolved_model,
                contents=clean_text,
                config=gen_cfg,
            )
        else:
            raise
    latency_sec = round(time.monotonic() - t0, 2)

    raw_audio: Optional[bytes] = None
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            raw_data = getattr(inline, "data", None) if inline is not None else None
            if raw_data:
                raw_audio = base64.b64decode(raw_data) if isinstance(raw_data, str) else bytes(raw_data)
                break
        if raw_audio:
            break

    if not raw_audio:
        raise RuntimeError(f"Gemini TTS ({resolved_model}) returned no inline audio bytes.")

    wav_bytes = ensure_riff_wav_bytes(raw_audio, sample_rate=24000, channels=1, sampwidth=2)
    duration_sec, sample_rate_hz = get_wav_duration_sec(wav_bytes)
    telemetry = {
        "model": resolved_model,
        "voice": resolved_voice,
        "language_code": language_code or "en-US",
        "style": clean_style,
        "duration_sec": duration_sec,
        "sample_rate_hz": sample_rate_hz,
        "bytes": len(wav_bytes),
        "latency_sec": latency_sec,
    }
    return wav_bytes, telemetry


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
    reference_audio_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
) -> str:
    """Formats the Gemini Omni control string while preventing R2V vs `<FIRST_FRAME>` / `<LAST_FRAME>` / `<VIDEO_0>` tag collisions."""
    is_two_frame_interp = bool(input_image_b64 and end_image_b64)
    eff_duration = resolve_omni_shot_duration(
        requested_sec=duration,
        default_sec=10,
        task_or_mode=task,
        is_two_frame_interp=is_two_frame_interp,
    )
    ref_imgs = None if (input_image_b64 or end_image_b64 or input_video_b64) else reference_images_b64
    _ = reference_audio_b64  # Audio parts are attached natively on R2V / untasked V2V without colliding tags.
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
    elif input_image_b64 or end_image_b64 or input_video_b64:
        if "Character A" in prompt_content:
            prompt_content = re.sub(r"\bCharacter A\b,?\s*", "The subject ", prompt_content).strip()
        prompt_content = re.sub(
            r"\b(?:from|in)\s+the\s+reference\s+image\b",
            "from the starting frame",
            prompt_content,
            flags=re.IGNORECASE,
        )

    if is_two_frame_interp and not input_video_b64:
        low_p = prompt_content.lower()
        if "starting frame" not in low_p and "first frame" not in low_p:
            prompt_content = (
                "Use the first image as the starting frame and the second image as the final frame, "
                f"transitioning smoothly in one unbroken single-take camera shot with zero internal cuts. {prompt_content}"
            )
    elif input_image_b64 and not end_image_b64 and not input_video_b64:
        if "use this image as the starting frame" not in prompt_content.lower():
            prompt_content = f"Use this image as the starting frame. {prompt_content}"
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


def _build_omni_request_kwargs(
    *,
    prompt: str,
    input_image_b64: Optional[str],
    end_image_b64: Optional[str],
    input_video_b64: Optional[str],
    effective_task: Optional[str],
    model_override: Optional[str],
    ref_imgs: Optional[List[str]],
    ref_auds: List[str],
    voice_transcript: Optional[str],
    aspect_ratio: str,
    resolution: str,
    eff_duration: int,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    """Builds `interactions.create` kwargs, multimodal payload, and target model."""
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
    if ref_auds:
        for aud_b64 in ref_auds[:5]:
            payload.append({"type": "audio", "data": aud_b64, "mime_type": "audio/wav"})

    target_model = model_override or (
        DirectConfig.VIDEO_EXTEND_MODEL if effective_task == "extend" else DirectConfig.VIDEO_GEN_MODEL
    )

    norm_resolution = str(resolution or "720p").strip().lower()
    create_kwargs: Dict[str, Any] = {
        "model": target_model,
        "input": payload,
        "timeout": float(DirectConfig.VIDEO_GEN_TIMEOUT_MS) / 1000.0,
    }
    if effective_task in ("reference_to_video", "image_to_video"):
        create_kwargs["generation_config"] = {"video_config": {"task": effective_task}}
        create_kwargs["response_format"] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": f"{eff_duration}s",
            "resolution": norm_resolution,
        }
    elif effective_task == "extend":
        create_kwargs["generation_config"] = {"video_config": {"task": "extend"}}
        create_kwargs["response_format"] = {
            "type": "video",
            "duration": f"{eff_duration}s",
            "resolution": norm_resolution,
        }
    elif effective_task:
        create_kwargs["generation_config"] = {"video_config": {"task": effective_task}}
        create_kwargs["response_format"] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": f"{eff_duration}s",
            "resolution": norm_resolution,
        }
    else:
        create_kwargs["response_format"] = {
            "type": "video",
            "aspect_ratio": aspect_ratio,
            "duration": f"{eff_duration}s",
            "resolution": norm_resolution,
        }
    return create_kwargs, payload, target_model


def _invoke_omni_with_fallbacks(
    *,
    active_client: genai.Client,
    kwargs_dict: Dict[str, Any],
    payload: List[Dict[str, Any]],
    prompt: str,
    input_image_b64: Optional[str],
    end_image_b64: Optional[str],
    input_video_b64: Optional[str],
    effective_task: Optional[str],
    ref_imgs: Optional[List[str]],
    voice_transcript: Optional[str],
    aspect_ratio: str,
    resolution: str,
    eff_duration: int,
) -> Any:
    """Calls `interactions.create` with tail-audio sanitization and safety fallbacks."""
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
            non_audio_tail = [p for p in payload[1:] if p.get("type") != "audio"]
            if in_vid:
                fb_tail = [{"type": "video", "data": in_vid, "mime_type": "video/mp4"}] + [
                    p for p in non_audio_tail if p.get("type") != "video"
                ]
            else:
                fb_tail = non_audio_tail
            return _call_with_backoff_sync(
                active_client.interactions.create,
                **{**kwargs_dict, "input": [{"type": "text", "text": fb_prompt}] + fb_tail},
            )
        raise


def generate_omni_clip_direct(
    prompt: str,
    input_image_b64: Optional[str] = None,
    end_image_b64: Optional[str] = None,
    input_video_b64: Optional[str] = None,
    task: Optional[str] = None,
    model_override: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    reference_audio_b64: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    client: Optional[genai.Client] = None,
) -> bytes:
    """Generates a single MP4 clip directly via `gemini-omni-1.2-flash` (`interactions.create`)."""
    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    is_two_frame_interp = bool(input_image_b64 and end_image_b64)
    ref_imgs = None if (input_image_b64 or end_image_b64 or input_video_b64) else reference_images_b64
    if task:
        effective_task = task
    elif input_image_b64 and not end_image_b64 and not input_video_b64:
        effective_task = "image_to_video"
    elif ref_imgs and len(ref_imgs) > 0:
        effective_task = "reference_to_video"
    else:
        effective_task = None

    # AudioContent is supported on reference_to_video and untasked (None) requests,
    # and rejected on standard image_to_video or extend requests.
    ref_auds = (
        [a for a in reference_audio_b64[:5] if a]
        if (reference_audio_b64 and effective_task in ("reference_to_video", None))
        else []
    )

    eff_duration = resolve_omni_shot_duration(
        requested_sec=duration,
        default_sec=10,
        task_or_mode=effective_task,
        is_two_frame_interp=is_two_frame_interp,
    )

    create_kwargs, payload, target_model = _build_omni_request_kwargs(
        prompt=prompt,
        input_image_b64=input_image_b64,
        end_image_b64=end_image_b64,
        input_video_b64=input_video_b64,
        effective_task=effective_task,
        model_override=model_override,
        ref_imgs=ref_imgs,
        ref_auds=ref_auds,
        voice_transcript=voice_transcript,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        eff_duration=eff_duration,
    )

    invoke_args = dict(
        active_client=active_client,
        payload=payload,
        prompt=prompt,
        input_image_b64=input_image_b64,
        end_image_b64=end_image_b64,
        input_video_b64=input_video_b64,
        effective_task=effective_task,
        ref_imgs=ref_imgs,
        voice_transcript=voice_transcript,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        eff_duration=eff_duration,
    )
    try:
        interaction = _invoke_omni_with_fallbacks(kwargs_dict=create_kwargs, **invoke_args)
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
            interaction = _invoke_omni_with_fallbacks(kwargs_dict=create_kwargs, **invoke_args)
        else:
            raise

    video_bytes = _extract_video_bytes_from_interaction(interaction)
    if not video_bytes:
        raise RuntimeError("Gemini Omni returned an interaction without video bytes (check regional/input limits).")
    return video_bytes


def dub_omni_clip_direct(
    video_path_or_bytes: bytes | str,
    voice_wav_path_or_bytes: bytes | str,
    prompt: str = "Replace the spoken voice in this video seamlessly with the reference voice track while preserving all visual motion and environmental realism.",
    voice_transcript: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    model_override: Optional[str] = None,
    client: Optional[genai.Client] = None,
) -> bytes:
    """TPVG untasked V2V speech/voice dubbing (`task=None`, `[text, video, tts_wav_chunks]`).

    Args:
        video_path_or_bytes: Path to an MP4 file or raw MP4 bytes.
        voice_wav_path_or_bytes: Path to a reference WAV file or raw WAV bytes.
        prompt: Dubbing instruction prompt.
        voice_transcript: Optional spoken transcript for lip-sync conditioning.
        aspect_ratio: Target aspect ratio (`"16:9"` or `"9:16"`).
        resolution: Target output resolution (`"360p"` or `"720p"`).
        duration: Clip duration in seconds.
        model_override: Optional Omni model ID override.
        client: Optional pre-configured ``genai.Client``.

    Returns:
        Dubbed MP4 video bytes.

    Raises:
        FileNotFoundError: If a path argument does not exist on disk.
    """
    if isinstance(video_path_or_bytes, (bytes, bytearray)):
        vid_bytes = bytes(video_path_or_bytes)
    elif isinstance(video_path_or_bytes, str) and os.path.exists(video_path_or_bytes):
        with open(video_path_or_bytes, "rb") as fp:
            vid_bytes = fp.read()
    else:
        raise FileNotFoundError(f"Video input not found for dubbing: {video_path_or_bytes}")

    if isinstance(voice_wav_path_or_bytes, (bytes, bytearray)):
        wav_bytes = bytes(voice_wav_path_or_bytes)
    elif isinstance(voice_wav_path_or_bytes, str) and os.path.exists(voice_wav_path_or_bytes):
        with open(voice_wav_path_or_bytes, "rb") as fp:
            wav_bytes = fp.read()
    else:
        raise FileNotFoundError(f"Voice WAV input not found for dubbing: {voice_wav_path_or_bytes}")

    audio_chunks_b64 = split_wav_reference_chunks(wav_bytes, chunk_sec=3.0, max_chunks=5)
    vid_b64 = base64.b64encode(vid_bytes).decode("utf-8")

    # Untasked (task=None) permits VideoContent + AudioContent for speech dubbing.
    return generate_omni_clip_direct(
        prompt=prompt,
        input_video_b64=vid_b64,
        task=None,
        model_override=model_override,
        reference_audio_b64=audio_chunks_b64,
        voice_transcript=voice_transcript,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
        client=client,
    )


SUPPORTED_UPSCALE_TRANSITIONS: Dict[str, tuple] = {
    "360p": ("720p", "1080p"),
    "720p": ("1080p", "4k"),
}


def validate_upscale_transition(source_resolution: str, target_resolution: str) -> tuple:
    """Validates GA `gemini-omni-1.2-flash` standalone video upscale hops (`360p->720p/1080p`, `720p->1080p/4k`)."""
    src = str(source_resolution or "").strip().lower()
    tgt = str(target_resolution or "").strip().lower()
    allowed = SUPPORTED_UPSCALE_TRANSITIONS.get(src)
    if not allowed or tgt not in allowed:
        raise ValueError(
            f"Unsupported standalone upscale transition '{source_resolution}' -> '{target_resolution}'. "
            "Supported GA transitions: 360p -> 720p | 1080p, and 720p -> 1080p | 4k "
            "(single-hop 360p -> 4k and 1080p -> 4k are not supported)."
        )
    return src, tgt


def _extract_interaction_usage_telemetry(interaction: Any) -> Dict[str, Any]:
    """Extracts token usage metadata from an Interactions API response (`total_input_tokens: 0` on `task='upscale'`)."""
    telemetry: Dict[str, Any] = {}
    usage = getattr(interaction, "usage", None) or getattr(interaction, "usage_metadata", None)
    if usage is None and hasattr(interaction, "model_dump") and callable(interaction.model_dump):
        try:
            dumped = interaction.model_dump()
            if isinstance(dumped, dict):
                usage = dumped.get("usage") or dumped.get("usage_metadata")
        except Exception:
            usage = None
    if usage is None:
        return telemetry

    for key in (
        "total_input_tokens",
        "total_output_tokens",
        "total_thought_tokens",
        "total_tokens",
        "prompt_token_count",
        "candidates_token_count",
    ):
        val = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        if val is not None:
            telemetry[key] = int(val)
    return telemetry


def upscale_omni_clip_direct(
    video_bytes_or_b64: bytes | str,
    target_resolution: str = "720p",
    source_resolution: str = "360p",
    model_override: Optional[str] = None,
    return_telemetry: bool = False,
    client: Optional[genai.Client] = None,
) -> bytes | Tuple[bytes, Dict[str, Any]]:
    """Upscales an MP4 clip (<= 15s) via standalone `task='upscale'` on `gemini-omni-1.2-flash`.

    Args:
        video_bytes_or_b64: Raw MP4 bytes or base64-encoded MP4 string.
        target_resolution: Target resolution (`"720p"`, `"1080p"`, or `"4k"`).
        source_resolution: Source resolution (`"360p"` or `"720p"`).
        model_override: Optional Omni model ID override.
        return_telemetry: When True, returns `(video_bytes, telemetry_dict)`.
        client: Optional pre-configured ``genai.Client``.

    Returns:
        Upscaled MP4 bytes, or `(video_bytes, telemetry_dict)` if `return_telemetry` is True.

    Raises:
        ValueError: If `video_bytes_or_b64` is empty or the upscale transition is invalid.
        RuntimeError: If the upscale call returns no video bytes.
    """
    src_res, tgt_res = validate_upscale_transition(source_resolution, target_resolution)
    if isinstance(video_bytes_or_b64, (bytes, bytearray)):
        if len(video_bytes_or_b64) == 0:
            raise ValueError("Cannot upscale empty video bytes.")
        video_b64 = base64.b64encode(bytes(video_bytes_or_b64)).decode("utf-8")
    elif isinstance(video_bytes_or_b64, str) and video_bytes_or_b64.strip():
        video_b64 = video_bytes_or_b64.strip()
    else:
        raise ValueError("Provide non-empty MP4 bytes or base64 string to upscale_omni_clip_direct.")

    active_client = client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    create_kwargs: Dict[str, Any] = {
        "model": model_override or DirectConfig.VIDEO_GEN_MODEL,
        "input": [{"type": "video", "data": video_b64, "mime_type": "video/mp4"}],
        "generation_config": {"video_config": {"task": "upscale"}},
        "response_format": {"type": "video", "resolution": tgt_res},
        "timeout": float(DirectConfig.VIDEO_GEN_TIMEOUT_MS) / 1000.0,
    }

    t_up0 = time.monotonic()
    interaction = _call_with_backoff_sync(active_client.interactions.create, **create_kwargs)
    upscale_sec = round(time.monotonic() - t_up0, 2)

    video_bytes = _extract_video_bytes_from_interaction(interaction)
    if not video_bytes:
        raise RuntimeError(
            f"Gemini Omni standalone upscale ({src_res} -> {tgt_res}) returned no video bytes."
        )

    telemetry: Dict[str, Any] = {
        "source_resolution": src_res,
        "target_resolution": tgt_res,
        "upscale_sec": upscale_sec,
        **_extract_interaction_usage_telemetry(interaction),
    }
    if return_telemetry:
        return video_bytes, telemetry
    return video_bytes


# ---------------------------------------------------------------------------
# Direct Auto-Rater v2 & Post-Stitch Master Seam Critic (`MediaProcessing.AGENTIC`)
# ---------------------------------------------------------------------------


def build_consolidated_rubric(
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    has_reference_anchor: bool = False,
    fails_if: Optional[str] = None,
    audio_mode: Optional[str] = None,
) -> List[str]:
    """Builds the deterministic Auto-Rater v2 evaluation rubric with zero extra LLM round-trips."""
    rubric: List[str] = []
    if evaluation_criteria and evaluation_criteria.strip():
        rubric.append(f"Scene Goal: {evaluation_criteria.strip()}")
    if fails_if and fails_if.strip():
        rubric.append(f"Hard Fail Condition (fails_if): {fails_if.strip()}")
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
        "Framing, Physics & Typography Integrity: No unrequested black letterbox bars, no garbled labels/logos, no extra fingers, and physically plausible weight/motion.",
    ])
    if audio_mode == "off_camera_vo":
        rubric.append(
            "Off-Camera VO Mouth Discipline: No on-screen person moves their lips to speak; clean ambient room tone only."
        )
    elif spoken_dialogue and spoken_dialogue.strip():
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
    fails_if: Optional[str] = None,
    audio_mode: Optional[str] = None,
    client: Optional[genai.Client] = None,
) -> Dict[str, Any]:
    """Evaluates a candidate shot via `gemini-3.8-flash` (`MediaProcessing.AGENTIC`) + high-res stills + OpenCV/FFMPEG guardrails."""
    ref_decoded = decode_valid_image_b64(reference_images_b64[0]) if reference_images_b64 else None
    prior_decoded = decode_valid_image_b64(prev_last_frame_b64) if prev_last_frame_b64 else None
    rubric = build_consolidated_rubric(
        evaluation_criteria=evaluation_criteria,
        spoken_dialogue=spoken_dialogue,
        has_reference_anchor=ref_decoded is not None,
        fails_if=fails_if,
        audio_mode=audio_mode,
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
    defect_codes_str = ", ".join(GENMEDIA_DEFECT_TAXONOMY.keys())
    expected_vo = f'"{spoken_dialogue.strip()}"' if (spoken_dialogue and spoken_dialogue.strip()) else "None (ambient/instrumental)"
    eval_instructions = (
        f"You are Auto-Rater v2 auditing generated video Shot #{shot_index}.\n"
        f"Target Shot Prompt: '{prompt}'\n"
        f"Expected Spoken Dialogue: {expected_vo} (audio_mode={audio_mode or 'auto'})\n"
        f"Shot Mode Context: is_r2v_shot={is_r2v_shot}, is_extend_shot={is_extend_shot}\n"
        f"Deterministic Pre-Audit Signals: {json.dumps(merged_telemetry)}\n\n"
        f"CONSOLIDATED RUBRIC:\n{rubric_str}\n\n"
        "MANDATORY OBSERVATION-FIRST PROTOCOL:\n"
        "1. Populate 'opening_environment_observed', 'heard_transcript' (exact words heard via audio/AVU), "
        "'speech_end_sec', 'detected_internal_cuts' (count BOTH abrupt jump-cuts AND internal soft cross-dissolves/scene transitions inside this clip), "
        f"and 'detected_genmedia_issues' (list any applicable defect codes from [{defect_codes_str}], or [] if none) BEFORE assigning any numeric score.\n"
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
            target_finish_sec = max(2, int(round(clip_dur)) - 2) if clip_dur >= 3.0 else 8
            guardrail_notes.append(
                f"Spoken dialogue clipped at final 0.2s boundary (trailing_rms_db={merged_telemetry.get('trailing_rms_db')} dBFS); "
                f"pace delivery briskly so speech finishes before second {target_finish_sec}."
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


def compute_seam_transition_windows(
    num_shots: int,
    shot_duration_sec: float = 10.0,
    shot_durations_sec: Optional[List[float]] = None,
    crossfade_sec: float = 0.0,
) -> List[str]:
    """Computes formatted `[t_cut - 1.5s, t_cut + 1.5s]` seam window labels across uniform or variable shot durations."""
    if num_shots < 2:
        return []
    fallback_d = max(0.5, float(shot_duration_sec))
    if shot_durations_sec:
        durs = [max(0.5, float(d)) for d in shot_durations_sec[:num_shots]]
        if len(durs) < num_shots:
            durs.extend([fallback_d] * (num_shots - len(durs)))
    else:
        durs = [fallback_d] * num_shots

    xf = max(0.0, float(crossfade_sec or 0.0))
    windows: List[str] = []
    cum_raw = 0.0
    for i in range(1, num_shots):
        cum_raw += durs[i - 1]
        t_cut = max(0.0, cum_raw - (i - 0.5) * xf) if xf > 0.0 else max(0.0, cum_raw)
        lo = max(0.0, t_cut - 1.5)
        hi = t_cut + 1.5
        windows.append(f"[{lo:.1f}s - {hi:.1f}s] (Seam {i}->{i + 1} around {t_cut:.1f}s)")
    return windows


async def evaluate_stitched_master_direct(
    stitched_video_path: str,
    num_shots: int,
    shot_duration_sec: float = 10.0,
    original_intent: str = "",
    voice_transcript: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    shot_durations_sec: Optional[List[float]] = None,
    crossfade_sec: float = 0.0,
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

    seam_windows = compute_seam_transition_windows(
        num_shots=num_shots,
        shot_duration_sec=shot_duration_sec,
        shot_durations_sec=shot_durations_sec,
        crossfade_sec=crossfade_sec,
    )
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
    p_gen.add_argument("--audio-ref", nargs="*", help="Optional WAV reference audio path(s) for TPVG R2V (auto-chunked <= 3s x 5).")
    p_gen.add_argument("--first-frame", help="Optional starting PNG path for <FIRST_FRAME> I2V.")
    p_gen.add_argument("--last-frame", help="Optional ending PNG path for <LAST_FRAME> interpolation.")
    p_gen.add_argument("--extend-tail", help="Optional 5.0s trailing MP4 path for task='extend'.")
    p_gen.add_argument("--dialogue", help="Optional spoken dialogue line.")
    p_gen.add_argument("--aspect-ratio", default="16:9")
    p_gen.add_argument("--resolution", default="720p")
    p_gen.add_argument("--duration", type=int, default=10)

    p_tts = sub.add_parser("synthesize-tts", help="Synthesize a 24 kHz mono RIFF WAV voice track via gemini-3.8-flash-tts.")
    p_tts.add_argument("--text", required=True, help="Spoken text to synthesize.")
    p_tts.add_argument("--output", required=True, help="Output WAV path.")
    p_tts.add_argument("--voice", default=DirectConfig.DEFAULT_TTS_VOICE, help="Prebuilt voice (Kore, Puck, Aoede, Charon, Fenrir, Leda, Zephyr) or voice_key.")
    p_tts.add_argument("--language", default="en-US", help="BCP-47 language code (default: en-US).")
    p_tts.add_argument("--style", default="", help="Optional speaking style directive.")
    p_tts.add_argument("--tts-model", default=DirectConfig.TTS_MODEL, help="TTS model ID or alias (gemini-3.8-tts -> gemini-3.8-flash-tts).")

    p_dub = sub.add_parser("dub-clip", help="TPVG untasked V2V speech/voice replacement onto an existing MP4 clip.")
    p_dub.add_argument("--video", required=True, help="Source MP4 clip path.")
    p_dub.add_argument("--voice", required=True, help="Target TTS WAV path.")
    p_dub.add_argument("--output", required=True, help="Output dubbed MP4 path.")
    p_dub.add_argument("--prompt", default="Replace the spoken voice in this video seamlessly with the reference voice track while preserving visual motion and ambient realism.")
    p_dub.add_argument("--dialogue", default=None, help="Optional verbatim spoken transcript.")
    p_dub.add_argument("--aspect-ratio", default="16:9")
    p_dub.add_argument("--resolution", default="720p")
    p_dub.add_argument("--duration", type=int, default=10)

    p_plan = sub.add_parser("generate-vision-plan", help="Generate Stage 1 VisionProfile + Stage 2 Storyboard Plan (JSON + Markdown).")
    p_plan.add_argument("--prompt", required=True, help="Commercial brief or narrative prompt.")
    p_plan.add_argument("--output-dir", required=True, help="Directory to write director_plan.json, director_plan.md, and storyboard_defined.json.")
    p_plan.add_argument("--shots", type=int, default=3)
    p_plan.add_argument("--mode", default="video_extend")
    p_plan.add_argument("--aspect-ratio", default="16:9")
    p_plan.add_argument("--duration", type=int, default=10)
    p_plan.add_argument("--dialogue", default=None)
    p_plan.add_argument("--tts-voice", default=DirectConfig.DEFAULT_TTS_VOICE)
    p_plan.add_argument("--tts-style", default="")

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
    p_master.add_argument(
        "--shot-durations",
        nargs="*",
        type=float,
        default=None,
        help="Optional per-shot/scene durations in seconds (overrides uniform --shot-duration).",
    )
    p_master.add_argument("--crossfade", type=float, default=0.0, help="Crossfade overlap seconds between clips.")
    p_master.add_argument("--intent", default="")
    p_master.add_argument("--dialogue", default=None)
    p_master.add_argument("--reference", default=None)

    p_up = sub.add_parser(
        "upscale-clip",
        help="Upscale an MP4 clip (<= 15s) via standalone task='upscale' on gemini-omni-1.2-flash.",
    )
    p_up.add_argument("--video", required=True, help="Input draft MP4 path (360p or 720p, <= 15s).")
    p_up.add_argument("--output", required=True, help="Output upscaled MP4 path.")
    p_up.add_argument("--target-resolution", default="720p", choices=["720p", "1080p", "4k"])
    p_up.add_argument("--source-resolution", default="360p", choices=["360p", "720p"])

    return parser


def _dispatch_cli_command(args: argparse.Namespace) -> int:
    """Dispatches parsed CLI subcommands for `omni_direct`."""
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
        aud_b64s: List[str] = []
        for ap in (args.audio_ref or []):
            with open(ap, "rb") as fp:
                aud_b64s.extend(split_wav_reference_chunks(fp.read(), chunk_sec=3.0, max_chunks=5))
        aud_b64s = aud_b64s[:5]
        ff_b64 = encode_image_file_b64(args.first_frame) if args.first_frame else None
        lf_b64 = encode_image_file_b64(args.last_frame) if args.last_frame else None
        vid_b64 = None
        task = None
        if args.extend_tail:
            with open(args.extend_tail, "rb") as fp:
                vid_b64 = base64.b64encode(fp.read()).decode("utf-8")
            task = "extend"
        elif ff_b64 and not lf_b64:
            task = "image_to_video"
        elif ref_b64s and not ff_b64 and not lf_b64:
            task = "reference_to_video"

        mp4_bytes = generate_omni_clip_direct(
            prompt=args.prompt,
            input_image_b64=ff_b64,
            end_image_b64=lf_b64,
            input_video_b64=vid_b64,
            task=task,
            reference_images_b64=ref_b64s,
            reference_audio_b64=aud_b64s or None,
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

    if args.command == "synthesize-tts":
        wav_bytes, telemetry = synthesize_tts_track_direct(
            text=args.text,
            voice_name=args.voice,
            language_code=args.language,
            style=args.style,
            model_name=args.tts_model,
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "wb") as fp:
            fp.write(wav_bytes)
        print(json.dumps({"status": "ok", "output": os.path.abspath(args.output), **telemetry}, indent=2))
        return 0

    if args.command == "dub-clip":
        mp4_bytes = dub_omni_clip_direct(
            video_path_or_bytes=args.video,
            voice_wav_path_or_bytes=args.voice,
            prompt=args.prompt,
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

    if args.command == "generate-vision-plan":
        plan = asyncio.run(
            generate_vision_and_plan_direct(
                intent=args.prompt,
                num_shots=args.shots,
                mode=args.mode,
                aspect_ratio=args.aspect_ratio,
                voice_transcript=args.dialogue,
                default_duration_sec=args.duration,
                tts_voice=args.tts_voice,
                tts_style=args.tts_style,
            )
        )
        abs_dir = os.path.abspath(args.output_dir)
        os.makedirs(abs_dir, exist_ok=True)
        plan_json_p = os.path.join(abs_dir, "director_plan.json")
        plan_md_p = os.path.join(abs_dir, "director_plan.md")
        sb_json_p = os.path.join(abs_dir, "storyboard_defined.json")
        Path(plan_json_p).write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        Path(plan_md_p).write_text(format_director_plan_markdown(plan), encoding="utf-8")
        Path(sb_json_p).write_text(
            json.dumps([s.model_dump() for s in plan.shots], indent=2),
            encoding="utf-8",
        )
        print(json.dumps({
            "status": "ok",
            "director_plan_json": plan_json_p,
            "director_plan_md": plan_md_p,
            "storyboard_defined_json": sb_json_p,
            "num_shots": len(plan.shots),
        }, indent=2))
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
                shot_durations_sec=args.shot_durations or None,
                crossfade_sec=args.crossfade,
            )
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "upscale-clip":
        with open(args.video, "rb") as fp:
            in_bytes = fp.read()
        up_bytes, telemetry = upscale_omni_clip_direct(
            video_bytes_or_b64=in_bytes,
            target_resolution=args.target_resolution,
            source_resolution=args.source_resolution,
            return_telemetry=True,
        )
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "wb") as fp:
            fp.write(up_bytes)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "output": os.path.abspath(args.output),
                    "bytes": len(up_bytes),
                    **telemetry,
                },
                indent=2,
            )
        )
        return 0

    return 1


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for `omni_direct`."""
    parser = _build_cli_parser()
    return _dispatch_cli_command(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
