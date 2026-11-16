# Copyright 2026 Author:Hill YU(xcyu@)
"""End-to-end standalone ADK-free multi-shot video orchestration CLI (`vidgen-long-video`).

Executes pre-production storyboarding (`gemini-3.8-flash`), multi-shot video synthesis
(`gemini-omni-1.2-flash` across Mode A parallel R2V, Mode B `<FIRST_FRAME>` I2V chaining,
Mode C `5.0s` audio-intact `video_extend`, and Mode D per-shot `hybrid`), OpenCV continuity
guards, Auto-Rater v2 (`gemini-3.8-flash` with `MediaProcessing.AGENTIC` & Best-of-K retries),
80ms FFMPEG `xfade`/`acrossfade` stitching, and Post-Stitch Master Seam Critic auditing,
writing all artifacts and `run_manifest.json` strictly to a local output directory.
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
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List, Optional

from google import genai
from pydantic import BaseModel, Field

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from media_ops import (  # noqa: E402
    build_contact_sheet,
    detect_r2v_first_frame_lock,
    detect_seam_jump_cut,
    encode_image_file_b64,
    extract_first_frame,
    extract_last_frame,
    extract_video_tail,
    get_video_duration,
    mix_voiceover_onto_video,
    split_wav_reference_chunks,
    stitch_videos,
    trim_video_prefix,
)
from omni_direct import (  # noqa: E402
    DirectConfig,
    DirectorPlanSpec,
    StoryboardEntrySpec,
    VisionProfileSpec,
    evaluate_clip_quality_direct,
    evaluate_stitched_master_direct,
    format_director_plan_markdown,
    generate_omni_clip_direct,
    generate_reference_image_direct,
    generate_storyboard_direct,
    generate_vision_and_plan_direct,
    get_direct_genai_client,
    normalize_tts_model_name,
    optimize_shot_prompt_direct,
    resolve_omni_shot_duration,
    synthesize_tts_track_direct,
    upscale_omni_clip_direct,
    validate_upscale_transition,
)


class ShotRecord(BaseModel):
    shot_index: int
    effective_mode: str
    duration_sec: int = 10
    prompt: str
    evaluation_criteria: str
    spoken_dialogue: Optional[str] = None
    audio_mode: Optional[str] = None
    tts_audio_path: Optional[str] = None
    tts_duration_sec: Optional[float] = None
    attempts_used: int = 0
    quality_score: Optional[float] = None
    verdict: str = "PENDING"
    detected_genmedia_issues: List[str] = Field(default_factory=list)
    video_path: Optional[str] = None
    draft_video_path: Optional[str] = None
    first_frame_path: Optional[str] = None
    last_frame_path: Optional[str] = None
    render_sec: float = 0.0
    avu_sec: float = 0.0
    upscale_sec: float = 0.0
    upscale_telemetry: Optional[Dict[str, Any]] = None
    evaluation_report: Optional[Dict[str, Any]] = None


class InterpolationRepairRecord(BaseModel):
    shot_index: int
    trigger_reason: str
    original_score: float
    interpolated_score: float
    accepted: bool
    first_frame_path: str
    last_frame_path: str
    candidate_video_path: str
    original_video_path: Optional[str] = None
    evaluation_report: Optional[Dict[str, Any]] = None


class SceneSpec(BaseModel):
    scene_id: str = Field(description="Short slug such as 'scene_1'.")
    title: str = Field(default="", description="Human-readable scene chapter title.")
    mode: str = Field(default="video_extend", description="Scene continuity mode ('video_extend', 'i2v_chaining', 'reference', 'hybrid').")
    duration_sec: Optional[int] = Field(
        default=None,
        description="Optional default per-shot duration in seconds for shots in this scene (overrides CLI --duration when shot.duration_sec is unset).",
    )
    reference_paths: List[str] = Field(default_factory=list, description="Per-scene reference images (e.g., [hero_anchor.png, scene_plate.png]).")
    scene_plate_prompt: Optional[str] = Field(
        default=None,
        description="Optional prompt for `--stage plates` to synthesize a missing architectural scene plate via Nano Banana 2.1.",
    )
    opening_keyframe_prompt: Optional[str] = Field(
        default=None,
        description="Optional prompt to synthesize a grounded 16:9 opening keyframe if Shot 1 requires <FIRST_FRAME>+<LAST_FRAME> interpolation.",
    )
    closing_keyframe_prompt: Optional[str] = Field(
        default=None,
        description="Optional prompt to synthesize a grounded 16:9 closing keyframe if the final shot requires <FIRST_FRAME>+<LAST_FRAME> interpolation.",
    )
    shots: List[StoryboardEntrySpec] = Field(default_factory=list)


class WorkflowManifest(BaseModel):
    created_at_utc: str
    original_intent: str
    mode: str
    num_shots: int
    duration_per_shot_sec: int = 10
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    draft_mode: bool = False
    draft_resolution: Optional[str] = None
    orchestrator_model: str = DirectConfig.ORCHESTRATOR_MODEL
    video_gen_model: str = DirectConfig.VIDEO_GEN_MODEL
    media_processing: str = DirectConfig.MEDIA_PROCESSING
    elapsed_sec: float = 0.0
    draft_and_avu_sec: float = 0.0
    interpolation_repair_sec: float = 0.0
    upscale_sec: float = 0.0
    stitch_and_seam_audit_sec: float = 0.0
    output_dir: str
    reference_anchor_path: Optional[str] = None
    tts_model: Optional[str] = None
    tts_voice: Optional[str] = None
    qa_contact_sheet_path: Optional[str] = None
    escalation_report_path: Optional[str] = None
    human_review_required: bool = False
    stitched_video_path: Optional[str] = None
    stitched_duration_sec: float = 0.0
    shots: List[ShotRecord] = Field(default_factory=list)
    interpolation_repairs: List[InterpolationRepairRecord] = Field(default_factory=list)
    master_seam_report: Optional[Dict[str, Any]] = None


class SceneManifestRecord(BaseModel):
    scene_id: str
    title: str
    output_dir: str
    scene_video_path: Optional[str] = None
    scene_duration_sec: float = 0.0
    elapsed_sec: float = 0.0
    draft_and_avu_sec: float = 0.0
    interpolation_repair_sec: float = 0.0
    upscale_sec: float = 0.0
    stitch_and_seam_audit_sec: float = 0.0
    reference_paths: List[str] = Field(default_factory=list)
    shots: List[ShotRecord] = Field(default_factory=list)
    interpolation_repairs: List[InterpolationRepairRecord] = Field(default_factory=list)
    scene_seam_report: Optional[Dict[str, Any]] = None


class MultiSceneWorkflowManifest(BaseModel):
    created_at_utc: str
    original_intent: str
    num_scenes: int
    total_shots: int
    duration_per_shot_sec: int = 10
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    draft_mode: bool = False
    draft_resolution: Optional[str] = None
    orchestrator_model: str = DirectConfig.ORCHESTRATOR_MODEL
    video_gen_model: str = DirectConfig.VIDEO_GEN_MODEL
    media_processing: str = DirectConfig.MEDIA_PROCESSING
    elapsed_sec: float = 0.0
    sum_scene_draft_and_avu_sec: float = 0.0
    sum_scene_repair_sec: float = 0.0
    sum_scene_upscale_sec: float = 0.0
    master_stitch_and_seam_audit_sec: float = 0.0
    output_dir: str
    tts_model: Optional[str] = None
    tts_voice: Optional[str] = None
    qa_contact_sheet_path: Optional[str] = None
    escalation_report_path: Optional[str] = None
    human_review_required: bool = False
    master_video_path: Optional[str] = None
    master_duration_sec: float = 0.0
    scenes: List[SceneManifestRecord] = Field(default_factory=list)
    master_seam_report: Optional[Dict[str, Any]] = None


def _segment_voiceover(voice_transcript: Optional[str], num_shots: int) -> List[Optional[str]]:
    """Splits a multi-sentence voiceover transcript evenly across N shots when per-shot lines are unset."""
    if not voice_transcript or not voice_transcript.strip():
        return [None] * num_shots
    text = voice_transcript.strip()
    if num_shots <= 1:
        return [text]
    import re
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) >= num_shots:
        buckets: List[List[str]] = [[] for _ in range(num_shots)]
        for i, sent in enumerate(sentences):
            buckets[min(num_shots - 1, int(i * num_shots / len(sentences)))].append(sent)
        return [" ".join(b) if b else None for b in buckets]
    words = text.split()
    chunk = max(1, (len(words) + num_shots - 1) // num_shots)
    out: List[Optional[str]] = []
    for i in range(num_shots):
        seg = " ".join(words[i * chunk:(i + 1) * chunk]).strip()
        out.append(seg if seg else None)
    return out


def validate_production_spec(
    storyboard_specs: Optional[List[StoryboardEntrySpec]] = None,
    scene_specs: Optional[List[SceneSpec]] = None,
    default_mode: str = "video_extend",
    default_duration: int = 10,
    ignore_missing_plate_paths: bool = False,
) -> Dict[str, Any]:
    """Validates storyboard/scene specs before video compute (`--check-spec` pre-flight)."""
    errors: List[str] = []
    warnings: List[str] = []
    total_shots = 0
    total_duration_sec = 0

    groups: List[tuple] = []
    if scene_specs:
        for sc in scene_specs:
            groups.append((sc.scene_id, sc.mode or default_mode, sc.duration_sec or default_duration, sc.reference_paths, sc.scene_plate_prompt, sc.shots))
    elif storyboard_specs:
        groups.append(("single_scene", default_mode, default_duration, [], None, storyboard_specs))

    for sc_id, sc_mode, sc_dur, ref_paths, plate_prompt, shots in groups:
        for rp in ref_paths or []:
            if rp and not os.path.exists(rp):
                if ignore_missing_plate_paths and plate_prompt:
                    warnings.append(f"[{sc_id}] Plate '{rp}' not yet rendered; will synthesize in --stage plates.")
                else:
                    errors.append(f"[{sc_id}] Missing reference asset on disk: '{rp}'.")

        prev_angle: Optional[str] = None
        for idx, sh in enumerate(shots):
            total_shots += 1
            eff_m = _resolve_effective_shot_mode(sc_mode, sh.mode_override, idx, bool(ref_paths))
            raw_dur = sh.duration_sec if sh.duration_sec is not None else sc_dur
            if eff_m == "video_extend" and raw_dur > 10:
                warnings.append(
                    f"[{sc_id} Shot #{sh.scene_number}] Requested duration {raw_dur}s exceeds GA 10s video_extend cap; clamped to 10s."
                )
            elif raw_dur < 3 or raw_dur > 15:
                warnings.append(
                    f"[{sc_id} Shot #{sh.scene_number}] Requested duration {raw_dur}s outside GA 3-15s bounds; clamped."
                )
            eff_dur = resolve_omni_shot_duration(
                requested_sec=sh.duration_sec,
                default_sec=sc_dur,
                task_or_mode=eff_m,
            )
            total_duration_sec += eff_dur

            if not (sh.evaluation_criteria and sh.evaluation_criteria.strip()):
                errors.append(f"[{sc_id} Shot #{sh.scene_number}] Empty evaluation_criteria.")

            if sh.spoken_dialogue and sh.spoken_dialogue.strip():
                words = len(sh.spoken_dialogue.strip().split())
                speech_window = max(1.5, float(eff_dur) - 2.0)
                wps = words / speech_window
                if wps > 2.4:
                    warnings.append(
                        f"[{sc_id} Shot #{sh.scene_number}] Spoken dialogue ({words} words in {eff_dur}s, {wps:.2f} wps > 2.4 wps) risks end-of-clip cutoff."
                    )

            cur_angle = (sh.shot_size or sh.camera_angle or "").strip().lower()
            if prev_angle and cur_angle and cur_angle == prev_angle and eff_m == "reference":
                warnings.append(
                    f"[{sc_id} Shot #{sh.scene_number}] Repeats identical camera angle '{cur_angle}' across hard cut (15-degree / shot-scale change rule)."
                )
            prev_angle = cur_angle

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_shots": total_shots,
        "total_duration_sec": total_duration_sec,
    }


def _resolve_effective_shot_mode(
    pipeline_mode: str,
    shot_override: Optional[str],
    idx: int,
    has_references: bool,
) -> str:
    """Determines the exact generation conditioning mode for shot `idx` (0-based)."""
    raw = (shot_override or pipeline_mode or "reference").strip().lower()
    if raw in ("hybrid", "tpvg_tts"):
        return "reference" if idx == 0 else "video_extend"
    if idx == 0 and raw in ("i2v_chaining", "video_extend"):
        return "reference" if has_references else raw
    return raw


async def _execute_single_shot(
    idx: int,
    spec: StoryboardEntrySpec,
    effective_mode: str,
    reference_images_b64: Optional[List[str]],
    aspect_ratio: str,
    resolution: str,
    duration: int,
    max_attempts: int,
    output_dir: str,
    prev_frame_b64: Optional[str] = None,
    prev_last_frame_b64: Optional[str] = None,
    prev_video_tail_b64: Optional[str] = None,
    prev_video_tail_sec: float = 0.0,
    vision_profile: Optional[VisionProfileSpec] = None,
    tpvg_tts_enabled: bool = False,
    tts_model: str = DirectConfig.TTS_MODEL,
    tts_voice: str = DirectConfig.DEFAULT_TTS_VOICE,
    tts_style: str = "",
    tts_language: str = "en-US",
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
) -> ShotRecord:
    """Executes TTS pre-synthesis (in tpvg_tts mode), Director Prompt optimization, Omni render, OpenCV guards, and Auto-Rater v2."""
    shot_idx = spec.scene_number
    raw_prompt = f"{spec.camera_angle} shot: {spec.description}"
    clip_path = os.path.join(output_dir, f"shot_{shot_idx}.mp4")
    ff_path = os.path.join(output_dir, f"shot_{shot_idx}_first_frame.png")
    lf_path = os.path.join(output_dir, f"shot_{shot_idx}_last_frame.png")

    is_extend_shot = effective_mode == "video_extend" and idx > 0 and prev_video_tail_b64 is not None
    is_i2v_shot = effective_mode == "i2v_chaining" and idx > 0 and prev_frame_b64 is not None
    is_r2v_shot = bool(reference_images_b64 and not is_extend_shot and not is_i2v_shot)

    resolved_mode_label = "video_extend" if is_extend_shot else ("i2v_chaining" if is_i2v_shot else "reference")
    eff_duration = resolve_omni_shot_duration(
        requested_sec=spec.duration_sec,
        default_sec=duration,
        task_or_mode=resolved_mode_label,
        is_two_frame_interp=False,
    )

    eff_audio_mode = (spec.audio_mode or ("on_camera" if (spec.spoken_dialogue and spec.spoken_dialogue.strip()) else "ambient")).strip().lower()
    tts_wav_path: Optional[str] = None
    tts_dur_sec: Optional[float] = None
    tts_chunks_b64: Optional[List[str]] = None

    if tpvg_tts_enabled and spec.spoken_dialogue and spec.spoken_dialogue.strip() and eff_audio_mode in ("on_camera", "off_camera_vo"):
        shot_voice = spec.tts_voice or (vision_profile.default_tts_voice if vision_profile else tts_voice) or DirectConfig.DEFAULT_TTS_VOICE
        shot_style = spec.tts_style if spec.tts_style is not None else (vision_profile.default_tts_style if vision_profile else tts_style)
        wav_bytes, tts_meta = await asyncio.to_thread(
            synthesize_tts_track_direct,
            text=spec.spoken_dialogue.strip(),
            voice_name=shot_voice,
            language_code=tts_language,
            style=shot_style,
            model_name=tts_model,
            client=rater_client,
        )
        tts_wav_path = os.path.join(output_dir, f"shot_{shot_idx}_tts.wav")
        with open(tts_wav_path, "wb") as tfp:
            tfp.write(wav_bytes)
        tts_dur_sec = float(tts_meta.get("duration_sec") or 0.0)
        if eff_audio_mode == "on_camera" and is_r2v_shot:
            tts_chunks_b64 = split_wav_reference_chunks(wav_bytes, chunk_sec=3.0, max_chunks=5)
        print(
            f"[Shot #{shot_idx} TTS] model={tts_meta.get('model')} voice={shot_voice} "
            f"dur={tts_dur_sec:.2f}s audio_mode={eff_audio_mode} chunks={len(tts_chunks_b64 or [])}"
        )

    record = ShotRecord(
        shot_index=shot_idx,
        effective_mode=resolved_mode_label,
        duration_sec=eff_duration,
        prompt=raw_prompt,
        evaluation_criteria=spec.evaluation_criteria,
        spoken_dialogue=spec.spoken_dialogue,
        audio_mode=eff_audio_mode,
        tts_audio_path=os.path.abspath(tts_wav_path) if tts_wav_path else None,
        tts_duration_sec=tts_dur_sec,
    )

    best_score: float = -1.0
    best_bytes: Optional[bytes] = None
    best_prompt: str = raw_prompt
    best_eval: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None
    detected_issues: Optional[List[str]] = None

    omni_dialogue = None if (tpvg_tts_enabled and eff_audio_mode == "off_camera_vo") else spec.spoken_dialogue

    for attempt in range(max(1, max_attempts)):
        record.attempts_used = attempt + 1
        opt_prompt = await optimize_shot_prompt_direct(
            raw_prompt=raw_prompt,
            feedback=feedback,
            voice_transcript=omni_dialogue,
            is_extend_shot=is_extend_shot,
            is_r2v_shot=is_r2v_shot,
            duration_sec=eff_duration,
            vision_profile=vision_profile,
            shot_spec=spec,
            detected_issues=detected_issues,
            client=rater_client,
        )

        shot_refs = reference_images_b64 if is_r2v_shot else None
        shot_task = (
            "extend"
            if is_extend_shot
            else ("image_to_video" if is_i2v_shot else ("reference_to_video" if shot_refs else None))
        )
        shot_in_img = prev_frame_b64 if is_i2v_shot else None
        shot_in_vid = prev_video_tail_b64 if is_extend_shot else None
        shot_aud_refs = tts_chunks_b64 if (is_r2v_shot and tts_chunks_b64) else None

        print(
            f"[Shot #{shot_idx} | Attempt {attempt + 1}/{max_attempts}] "
            f"mode={record.effective_mode} task={shot_task or 't2v'} dur={eff_duration}s res={resolution}"
            + (f" tpvg_audio_chunks={len(shot_aud_refs)}" if shot_aud_refs else "")
        )

        t_ren0 = time.monotonic()
        video_bytes = await asyncio.to_thread(
            generate_omni_clip_direct,
            prompt=opt_prompt,
            input_image_b64=shot_in_img,
            input_video_b64=shot_in_vid,
            task=shot_task,
            reference_images_b64=shot_refs,
            reference_audio_b64=shot_aud_refs,
            voice_transcript=omni_dialogue,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=eff_duration,
            client=gen_client,
        )

        if is_extend_shot and prev_video_tail_sec > 0:
            video_bytes = await asyncio.to_thread(
                trim_video_prefix,
                video_bytes,
                prev_video_tail_sec,
                float(eff_duration),
                prev_last_frame_b64,
            )
        attempt_render_sec = time.monotonic() - t_ren0
        record.render_sec = round(record.render_sec + attempt_render_sec, 2)

        with open(clip_path, "wb") as fp:
            fp.write(video_bytes)

        if tpvg_tts_enabled and eff_audio_mode == "off_camera_vo" and tts_wav_path and os.path.exists(tts_wav_path):
            await asyncio.to_thread(mix_voiceover_onto_video, clip_path, tts_wav_path, clip_path)
            with open(clip_path, "rb") as fp:
                video_bytes = fp.read()

        det_signals: Dict[str, Any] = {}
        if is_r2v_shot and reference_images_b64:
            locked_to_ref, r2v_f0_mae = await asyncio.to_thread(
                detect_r2v_first_frame_lock, reference_images_b64[0], clip_path, 12.0
            )
            det_signals["r2v_f0_mae"] = r2v_f0_mae
            det_signals["locked_to_ref"] = locked_to_ref
            if locked_to_ref:
                if 0.35 > best_score:
                    best_score = 0.35
                    best_bytes = video_bytes
                    best_prompt = opt_prompt
                if attempt < max_attempts - 1:
                    detected_issues = ["r2v_white_backdrop_echo"]
                    feedback = (
                        f"Frame 0 echoed the #FFFFFF studio reference image (MAE={r2v_f0_mae:.2f}). "
                        "Open immediately inside the full target environment—never show a white backdrop."
                    )
                    continue

        boundary_ref_b64 = prev_frame_b64 if is_i2v_shot else prev_last_frame_b64
        if (is_extend_shot or is_i2v_shot) and boundary_ref_b64:
            has_jump_cut, seam_mae, peak_mae = await asyncio.to_thread(
                detect_seam_jump_cut, boundary_ref_b64, clip_path, 28.0, 5
            )
            det_signals["seam_mae"] = seam_mae
            det_signals["peak_early_mae"] = peak_mae
            det_signals["has_jump_cut"] = has_jump_cut
            if is_extend_shot and has_jump_cut:
                if 0.40 > best_score:
                    best_score = 0.40
                    best_bytes = video_bytes
                    best_prompt = opt_prompt
                if attempt < max_attempts - 1:
                    detected_issues = ["seam_jump_or_momentum_stall"]
                    feedback = (
                        f"Hard jump-cut detected at extension boundary (peak MAE={peak_mae:.1f}). "
                        "Continue seamlessly from the exact ending frame and room in one unbroken camera shot."
                    )
                    continue

        t_avu0 = time.monotonic()
        eval_res = await evaluate_clip_quality_direct(
            shot_index=shot_idx,
            prompt=opt_prompt,
            video_path=clip_path,
            evaluation_criteria=spec.evaluation_criteria,
            spoken_dialogue=spec.spoken_dialogue,
            reference_images_b64=reference_images_b64,
            prev_last_frame_b64=boundary_ref_b64,
            deterministic_signals=det_signals,
            is_r2v_shot=is_r2v_shot,
            is_extend_shot=is_extend_shot,
            fails_if=spec.fails_if,
            audio_mode=eff_audio_mode,
            client=rater_client,
        )
        attempt_avu_sec = time.monotonic() - t_avu0
        record.avu_sec = round(record.avu_sec + attempt_avu_sec, 2)
        score = float(eval_res.get("score", 0.0))
        avu_toks = (eval_res.get("deterministic_telemetry") or {}).get("avu_tool_use_tokens")
        print(
            f"  -> Score={score:.2f} ({eval_res.get('verdict')}) | "
            f"WER={eval_res.get('transcript_wer')} | AVU_tokens={avu_toks} | "
            f"render={attempt_render_sec:.1f}s avu={attempt_avu_sec:.1f}s"
        )

        if score > best_score:
            best_score = score
            best_bytes = video_bytes
            best_prompt = opt_prompt
            best_eval = eval_res

        if score >= 0.8 or attempt == max_attempts - 1:
            break
        detected_issues = list(eval_res.get("detected_genmedia_issues") or [])
        feedback = eval_res.get("feedback", "Improve subject continuity and single-take smoothness.")

    if best_bytes is not None:
        with open(clip_path, "wb") as fp:
            fp.write(best_bytes)
        await asyncio.to_thread(extract_first_frame, clip_path, ff_path)
        await asyncio.to_thread(extract_last_frame, clip_path, lf_path)
        record.video_path = os.path.abspath(clip_path)
        record.first_frame_path = os.path.abspath(ff_path)
        record.last_frame_path = os.path.abspath(lf_path)
        record.prompt = best_prompt
        record.quality_score = round(best_score, 3)
        record.verdict = (best_eval or {}).get("verdict", "PASSED" if best_score >= 0.8 else "COMPLETED_BEST_OF_K")
        record.detected_genmedia_issues = list((best_eval or {}).get("detected_genmedia_issues") or [])
        record.evaluation_report = best_eval

    return record


async def _upscale_manifest_shots_async(
    manifest: WorkflowManifest,
    source_resolution: str,
    target_resolution: str,
    max_parallel_upscales: int = 3,
    crossfade_seconds: float = 0.08,
    upscale_sem: Optional[asyncio.Semaphore] = None,
    gen_client: Optional[genai.Client] = None,
) -> WorkflowManifest:
    """Concurrently upscales winning shots in `manifest` via standalone `task='upscale'` and re-stitches the scene."""
    src_res, tgt_res = validate_upscale_transition(source_resolution, target_resolution)
    active_gen_client = gen_client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    sem = upscale_sem or asyncio.Semaphore(max(1, max_parallel_upscales))
    t_up0 = time.monotonic()

    async def _upscale_one(rec: ShotRecord) -> None:
        if not rec.video_path or not os.path.exists(rec.video_path):
            return
        draft_archive = os.path.join(manifest.output_dir, f"shot_{rec.shot_index}_draft_{src_res}.mp4")
        if os.path.exists(draft_archive) and os.path.getsize(draft_archive) > 10_000:
            rec.draft_video_path = os.path.abspath(draft_archive)
            print(f"[Upscale Shot #{rec.shot_index}] Reusing already-upscaled {rec.video_path} (draft={draft_archive})")
            return

        shutil.copyfile(rec.video_path, draft_archive)
        rec.draft_video_path = os.path.abspath(draft_archive)
        async with sem:
            with open(draft_archive, "rb") as fp:
                draft_bytes = fp.read()
            print(f"[Upscale Shot #{rec.shot_index}] Promoting {src_res} -> {tgt_res} via task='upscale'...")
            up_bytes, telemetry = await asyncio.to_thread(
                upscale_omni_clip_direct,
                draft_bytes,
                tgt_res,
                src_res,
                None,
                True,
                active_gen_client,
            )
            with open(rec.video_path, "wb") as fp:
                fp.write(up_bytes)
            if rec.first_frame_path:
                await asyncio.to_thread(extract_first_frame, rec.video_path, rec.first_frame_path)
            if rec.last_frame_path:
                await asyncio.to_thread(extract_last_frame, rec.video_path, rec.last_frame_path)
            rec.upscale_sec = float(telemetry.get("upscale_sec", 0.0))
            rec.upscale_telemetry = telemetry
            print(
                f"  -> [Upscale Shot #{rec.shot_index} Done] {src_res}->{tgt_res} in {rec.upscale_sec:.2f}s "
                f"(in_tok={telemetry.get('total_input_tokens')}, out_tok={telemetry.get('total_output_tokens')})"
            )

    await asyncio.gather(*(_upscale_one(r) for r in manifest.shots))
    manifest.upscale_sec = round(manifest.upscale_sec + (time.monotonic() - t_up0), 2)
    manifest.resolution = tgt_res
    manifest.draft_mode = True
    manifest.draft_resolution = src_res

    valid_records = [r for r in manifest.shots if r.video_path and os.path.exists(r.video_path)]
    valid_clips = [r.video_path for r in valid_records if r.video_path]
    if valid_clips:
        nominal_sec = sum(int(r.duration_sec or manifest.duration_per_shot_sec) for r in valid_records)
        stitched_name = f"output_stitched_{nominal_sec}s.mp4"
        target_stitched = manifest.stitched_video_path or os.path.join(manifest.output_dir, stitched_name)
        t_st0 = time.monotonic()
        stitched_path = await asyncio.to_thread(stitch_videos, valid_clips, target_stitched, crossfade_seconds)
        manifest.stitch_and_seam_audit_sec = round(
            manifest.stitch_and_seam_audit_sec + (time.monotonic() - t_st0), 2
        )
        manifest.stitched_video_path = stitched_path
        manifest.stitched_duration_sec = round(get_video_duration(stitched_path), 2)

    manifest_path = os.path.join(manifest.output_dir, "run_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fp:
        fp.write(manifest.model_dump_json(indent=2))
    return manifest


async def run_standalone_pipeline_async(
    prompt: str,
    output_dir: str,
    mode: str = "video_extend",
    num_shots: int = 3,
    duration: int = 10,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    reference_paths: Optional[List[str]] = None,
    voice_transcript: Optional[str] = None,
    storyboard_specs: Optional[List[StoryboardEntrySpec]] = None,
    vision_profile: Optional[VisionProfileSpec] = None,
    tts_model: str = DirectConfig.TTS_MODEL,
    tts_voice: str = DirectConfig.DEFAULT_TTS_VOICE,
    tts_style: str = "",
    tts_language: str = "en-US",
    quality_threshold: float = 0.80,
    auto_approve: bool = True,
    max_attempts: int = 3,
    max_parallel: int = DirectConfig.MAX_PARALLEL_SHOTS,
    crossfade_seconds: Optional[float] = None,
    draft_mode: bool = False,
    draft_resolution: str = "360p",
    max_parallel_upscales: int = 3,
    resume: bool = False,
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
    _defer_upscale: bool = False,
) -> WorkflowManifest:
    """Runs the complete ADK-free multi-shot generation, rating, optional standalone upscaling, and stitching pipeline locally."""
    t0 = time.monotonic()
    abs_out_dir = os.path.abspath(output_dir)
    os.makedirs(abs_out_dir, exist_ok=True)
    tpvg_tts_enabled = str(mode or "").strip().lower() == "tpvg_tts"
    resolved_tts_model = normalize_tts_model_name(tts_model) if tpvg_tts_enabled else None

    tgt_res = str(resolution or "720p").strip().lower()
    drf_res = str(draft_resolution or "360p").strip().lower()
    active_draft = bool(draft_mode and drf_res != tgt_res)
    if active_draft:
        validate_upscale_transition(drf_res, tgt_res)
    render_res = drf_res if active_draft else tgt_res

    active_gen_client = gen_client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    active_rater_client = rater_client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)

    reference_b64s: Optional[List[str]] = None
    saved_anchor_path: Optional[str] = None
    if reference_paths:
        reference_b64s = [encode_image_file_b64(p) for p in reference_paths]
        saved_anchor_path = os.path.join(abs_out_dir, "reference_anchor.png")
        shutil.copyfile(reference_paths[0], saved_anchor_path)

    if storyboard_specs:
        specs = list(storyboard_specs)
        num_shots = len(specs)
    else:
        specs = await generate_storyboard_direct(
            intent=prompt,
            num_shots=num_shots,
            mode=mode,
            voice_transcript=voice_transcript,
            default_duration_sec=duration,
            client=active_rater_client,
        )

    if voice_transcript and all(not s.spoken_dialogue for s in specs):
        seg_lines = _segment_voiceover(voice_transcript, len(specs))
        for s, line in zip(specs, seg_lines):
            s.spoken_dialogue = line

    effective_modes = [
        _resolve_effective_shot_mode(mode, s.mode_override, i, bool(reference_b64s))
        for i, s in enumerate(specs)
    ]
    can_parallel = all(m == "reference" for m in effective_modes) and len(specs) > 1 and not tpvg_tts_enabled

    t_draft0 = time.monotonic()
    shot_records: List[ShotRecord] = []
    if can_parallel:
        sem = asyncio.Semaphore(max(1, max_parallel))

        async def _worker(i: int, sp: StoryboardEntrySpec) -> ShotRecord:
            async with sem:
                return await _execute_single_shot(
                    idx=i,
                    spec=sp,
                    effective_mode="reference",
                    reference_images_b64=reference_b64s,
                    aspect_ratio=aspect_ratio,
                    resolution=render_res,
                    duration=duration,
                    max_attempts=max_attempts,
                    output_dir=abs_out_dir,
                    vision_profile=vision_profile,
                    tpvg_tts_enabled=tpvg_tts_enabled,
                    tts_model=tts_model,
                    tts_voice=tts_voice,
                    tts_style=tts_style,
                    tts_language=tts_language,
                    gen_client=active_gen_client,
                    rater_client=active_rater_client,
                )

        shot_records = list(await asyncio.gather(*(_worker(i, s) for i, s in enumerate(specs))))
    else:
        prev_frame_b64: Optional[str] = None
        prev_last_frame_b64: Optional[str] = None
        prev_tail_b64: Optional[str] = None
        prev_tail_sec: float = 0.0

        for i, sp in enumerate(specs):
            eff_m = effective_modes[i]
            existing_clip = os.path.join(abs_out_dir, f"shot_{i + 1}.mp4")
            if resume and os.path.exists(existing_clip) and os.path.getsize(existing_clip) > 50_000:
                ff_p = os.path.join(abs_out_dir, f"shot_{i + 1}_first_frame.png")
                lf_p = os.path.join(abs_out_dir, f"shot_{i + 1}_last_frame.png")
                if not os.path.exists(ff_p):
                    await asyncio.to_thread(extract_first_frame, existing_clip, ff_p)
                if not os.path.exists(lf_p):
                    await asyncio.to_thread(extract_last_frame, existing_clip, lf_p)
                t_av = time.monotonic()
                eval_res = await evaluate_clip_quality_direct(
                    shot_index=i + 1,
                    prompt=sp.description,
                    video_path=existing_clip,
                    evaluation_criteria=sp.evaluation_criteria,
                    spoken_dialogue=sp.spoken_dialogue,
                    reference_images_b64=reference_b64s,
                    prev_last_frame_b64=prev_last_frame_b64 if i > 0 else None,
                    is_r2v_shot=(eff_m == "reference"),
                    is_extend_shot=(eff_m == "video_extend"),
                    fails_if=sp.fails_if,
                    audio_mode=sp.audio_mode,
                    client=active_rater_client,
                )
                avu_dt = round(time.monotonic() - t_av, 2)
                sc_val = round(float(eval_res.get("score", 0.0)), 3)
                resumed_dur = resolve_omni_shot_duration(
                    requested_sec=sp.duration_sec,
                    default_sec=duration,
                    task_or_mode=eff_m,
                    is_two_frame_interp=False,
                )
                print(f"[Resume Shot #{i + 1}] Reusing saved {existing_clip} -> Score={sc_val:.2f}")
                rec = ShotRecord(
                    shot_index=i + 1,
                    effective_mode=eff_m,
                    duration_sec=resumed_dur,
                    prompt=sp.description,
                    evaluation_criteria=sp.evaluation_criteria,
                    spoken_dialogue=sp.spoken_dialogue,
                    audio_mode=sp.audio_mode,
                    attempts_used=1,
                    quality_score=sc_val,
                    verdict=eval_res.get("verdict", "PASSED" if sc_val >= 0.8 else "COMPLETED_BEST_OF_K"),
                    detected_genmedia_issues=list(eval_res.get("detected_genmedia_issues") or []),
                    video_path=os.path.abspath(existing_clip),
                    first_frame_path=os.path.abspath(ff_p),
                    last_frame_path=os.path.abspath(lf_p),
                    avu_sec=avu_dt,
                    evaluation_report=eval_res,
                )
            else:
                rec = await _execute_single_shot(
                    idx=i,
                    spec=sp,
                    effective_mode=eff_m,
                    reference_images_b64=reference_b64s,
                    aspect_ratio=aspect_ratio,
                    resolution=render_res,
                    duration=duration,
                    max_attempts=max_attempts,
                    output_dir=abs_out_dir,
                    prev_frame_b64=prev_frame_b64 if eff_m == "i2v_chaining" else None,
                    prev_last_frame_b64=prev_last_frame_b64,
                    prev_video_tail_b64=prev_tail_b64 if eff_m == "video_extend" else None,
                    prev_video_tail_sec=prev_tail_sec if eff_m == "video_extend" else 0.0,
                    vision_profile=vision_profile,
                    tpvg_tts_enabled=tpvg_tts_enabled,
                    tts_model=tts_model,
                    tts_voice=tts_voice,
                    tts_style=tts_style,
                    tts_language=tts_language,
                    gen_client=active_gen_client,
                    rater_client=active_rater_client,
                )
            shot_records.append(rec)
            if rec.video_path and os.path.exists(rec.video_path):
                if rec.last_frame_path and os.path.exists(rec.last_frame_path):
                    prev_last_frame_b64 = encode_image_file_b64(rec.last_frame_path)
                    prev_frame_b64 = prev_last_frame_b64
                next_m = effective_modes[i + 1] if (i + 1) < len(effective_modes) else None
                if eff_m == "video_extend" or next_m == "video_extend":
                    prev_tail_b64, prev_tail_sec = await asyncio.to_thread(
                        extract_video_tail,
                        rec.video_path,
                        DirectConfig.VIDEO_EXTEND_INPUT_SECONDS,
                        False,
                    )

    draft_and_avu_sec = round(time.monotonic() - t_draft0, 2)
    resolved_xfade = (
        crossfade_seconds
        if crossfade_seconds is not None
        else (0.0 if all(m == "reference" for m in effective_modes) else 0.08)
    )

    manifest = WorkflowManifest(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        original_intent=prompt,
        mode=mode,
        num_shots=len(specs),
        duration_per_shot_sec=duration,
        aspect_ratio=aspect_ratio,
        resolution=render_res,
        draft_mode=active_draft,
        draft_resolution=drf_res if active_draft else None,
        draft_and_avu_sec=draft_and_avu_sec,
        output_dir=abs_out_dir,
        reference_anchor_path=saved_anchor_path,
        shots=shot_records,
    )

    if active_draft and not _defer_upscale:
        manifest = await _upscale_manifest_shots_async(
            manifest=manifest,
            source_resolution=drf_res,
            target_resolution=tgt_res,
            max_parallel_upscales=max_parallel_upscales,
            crossfade_seconds=resolved_xfade,
            gen_client=active_gen_client,
        )
        valid_records = [r for r in manifest.shots if r.video_path and os.path.exists(r.video_path)]
        valid_clips = [r.video_path for r in valid_records if r.video_path]
        if len(valid_clips) >= 2 and manifest.stitched_video_path:
            t_sm0 = time.monotonic()
            manifest.master_seam_report = await evaluate_stitched_master_direct(
                stitched_video_path=manifest.stitched_video_path,
                num_shots=len(valid_clips),
                shot_duration_sec=float(duration),
                original_intent=prompt,
                voice_transcript=voice_transcript,
                reference_images_b64=reference_b64s,
                shot_durations_sec=[float(r.duration_sec or duration) for r in valid_records],
                crossfade_sec=resolved_xfade,
                client=active_rater_client,
            )
            manifest.stitch_and_seam_audit_sec = round(
                manifest.stitch_and_seam_audit_sec + (time.monotonic() - t_sm0), 2
            )
    else:
        valid_records = [r for r in manifest.shots if r.video_path and os.path.exists(r.video_path)]
        valid_clips = [r.video_path for r in valid_records if r.video_path]
        if valid_clips:
            nominal_sec = sum(int(r.duration_sec or duration) for r in valid_records)
            stitched_name = f"output_stitched_{nominal_sec}s.mp4"
            target_stitched = os.path.join(abs_out_dir, stitched_name)
            t_st0 = time.monotonic()
            stitched_path = await asyncio.to_thread(stitch_videos, valid_clips, target_stitched, resolved_xfade)
            stitched_dur = round(get_video_duration(stitched_path), 2)
            master_report: Optional[Dict[str, Any]] = None
            if len(valid_clips) >= 2:
                master_report = await evaluate_stitched_master_direct(
                    stitched_video_path=stitched_path,
                    num_shots=len(valid_clips),
                    shot_duration_sec=float(duration),
                    original_intent=prompt,
                    voice_transcript=voice_transcript,
                    reference_images_b64=reference_b64s,
                    shot_durations_sec=[float(r.duration_sec or duration) for r in valid_records],
                    crossfade_sec=resolved_xfade,
                    client=active_rater_client,
                )
            manifest.stitch_and_seam_audit_sec = round(time.monotonic() - t_st0, 2)
            manifest.stitched_video_path = stitched_path
            manifest.stitched_duration_sec = stitched_dur
            manifest.master_seam_report = master_report

    manifest.tts_model = resolved_tts_model
    manifest.tts_voice = tts_voice if tpvg_tts_enabled else None

    if valid_clips:
        qa_items = [
            {
                "path": r.video_path,
                "label": f"Shot {r.shot_index} ({r.effective_mode})",
                "score": r.quality_score,
                "status": "PASSED" if (r.quality_score or 0.0) >= quality_threshold else "ESCALATED",
            }
            for r in manifest.shots
            if r.video_path and os.path.exists(r.video_path)
        ]
        if qa_items:
            qa_sheet_path = os.path.join(abs_out_dir, "qa_contact_sheet.png")
            await asyncio.to_thread(build_contact_sheet, qa_items, qa_sheet_path, 3)
            manifest.qa_contact_sheet_path = qa_sheet_path

    if not _defer_upscale and not auto_approve:
        unresolved = [
            {
                "shot_index": r.shot_index,
                "score": r.quality_score,
                "verdict": r.verdict,
                "detected_genmedia_issues": r.detected_genmedia_issues,
                "feedback": (r.evaluation_report or {}).get("feedback", ""),
                "video_path": r.video_path,
            }
            for r in manifest.shots
            if float(r.quality_score or 0.0) < quality_threshold
        ]
        master_score = (manifest.master_seam_report or {}).get("score")
        if unresolved or (master_score is not None and float(master_score) < 0.75):
            esc_path = os.path.join(abs_out_dir, "escalation_report.json")
            esc_payload = {
                "status": "human_review_required",
                "quality_threshold": quality_threshold,
                "unresolved_shots": unresolved,
                "master_seam_score": master_score,
                "qa_contact_sheet_path": manifest.qa_contact_sheet_path,
                "stitched_video_path": manifest.stitched_video_path,
            }
            Path(esc_path).write_text(json.dumps(esc_payload, indent=2), encoding="utf-8")
            manifest.escalation_report_path = esc_path
            manifest.human_review_required = True

    manifest.elapsed_sec = round(time.monotonic() - t0, 2)
    manifest_path = os.path.join(abs_out_dir, "run_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fp:
        fp.write(manifest.model_dump_json(indent=2))

    print(
        f"[Completed] Stitched Master: {manifest.stitched_video_path} "
        f"({manifest.stitched_duration_sec}s, res={manifest.resolution}) | Manifest: {manifest_path}"
    )
    return manifest


def _select_shots_for_interpolation_repair(
    manifest: WorkflowManifest,
    quality_threshold: float = 0.80,
) -> List[tuple]:
    """Identifies 0-based shot indices requiring `<FIRST_FRAME>+<LAST_FRAME>` interpolation repair."""
    flagged: Dict[int, str] = {}
    for k, rec in enumerate(manifest.shots):
        score = float(rec.quality_score if rec.quality_score is not None else 0.0)
        if score < quality_threshold or not rec.video_path or not os.path.exists(rec.video_path):
            flagged[k] = f"shot_score={score:.2f} < {quality_threshold:.2f}"

    seam_rep = manifest.master_seam_report or {}
    for obs in seam_rep.get("seam_observations") or []:
        c_score = float(obs.get("continuity_score", 1.0))
        seam_idx = int(obs.get("seam_index", 0))  # 1-based: seam_idx=1 is Shot 1 -> Shot 2
        if c_score < 0.70 and 1 <= seam_idx < len(manifest.shots):
            target_k = seam_idx  # Prefer re-bridging the downstream shot (e.g. Shot 2 at k=1)
            cur_s = float(manifest.shots[target_k].quality_score or 0.0)
            if target_k not in flagged and cur_s < 0.86:
                flagged[target_k] = (
                    f"seam_{seam_idx}_to_{seam_idx + 1}_continuity={c_score:.2f} "
                    f"({obs.get('notes', 'rough seam')})"
                )

    return sorted(flagged.items(), key=lambda item: item[0])


def _build_default_boundary_keyframe_prompt(
    shot_spec: StoryboardEntrySpec,
    position: str = "opening",
    num_refs: int = 0,
    aspect_ratio: str = "16:9",
) -> str:
    """Builds a domain-neutral Shot-1 opening or Shot-N closing keyframe synthesis prompt."""
    pos_label = "opening film still" if position == "opening" else "closing hero film still"
    if num_refs >= 2:
        grounding = (
            "Preserve exact subject or product identity, proportions, colorway, branding, and wardrobe/materials "
            "from the first reference image, grounded naturally inside the architectural environment and lighting "
            "of the second reference image. Photorealistic natural lighting, zero text overlays, zero white studio backdrop."
        )
    elif num_refs == 1:
        grounding = (
            "Preserve exact subject or product identity, proportions, colorway, branding, and wardrobe/materials "
            "from the reference image, placed naturally inside the target scene environment. "
            "Photorealistic natural lighting, zero text overlays, zero white studio backdrop."
        )
    else:
        grounding = "Photorealistic natural lighting, coherent cinematic scene composition, zero text overlays."
    return f"Cinematic {aspect_ratio} {pos_label} for: {shot_spec.description}. {grounding}"


async def _repair_scene_shots_with_interpolation(
    scene_spec: SceneSpec,
    manifest: WorkflowManifest,
    quality_threshold: float = 0.80,
    crossfade_seconds: float = 0.08,
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
) -> WorkflowManifest:
    """Regenerates sub-threshold shots in a scene via `<FIRST_FRAME>+<LAST_FRAME>` interpolation (`gemini-omni-1.2-flash`)."""
    candidates = _select_shots_for_interpolation_repair(manifest, quality_threshold=quality_threshold)
    if not candidates or len(manifest.shots) < 2:
        return manifest

    active_gen_client = gen_client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    active_rater_client = rater_client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    scene_ref_b64s = [encode_image_file_b64(p) for p in scene_spec.reference_paths if os.path.exists(p)] or None
    num_scene_refs = len(scene_ref_b64s) if scene_ref_b64s else 0
    scene_default_dur = int(
        scene_spec.duration_sec if scene_spec.duration_sec is not None else manifest.duration_per_shot_sec
    )
    any_accepted = False
    n_shots = len(manifest.shots)

    for k, trigger_reason in candidates:
        rec = manifest.shots[k]
        shot_spec = scene_spec.shots[k] if k < len(scene_spec.shots) else StoryboardEntrySpec(
            scene_number=rec.shot_index,
            description=rec.prompt,
            evaluation_criteria=rec.evaluation_criteria,
            spoken_dialogue=rec.spoken_dialogue,
            duration_sec=rec.duration_sec,
        )
        orig_score = float(rec.quality_score if rec.quality_score is not None else 0.0)
        print(
            f"[{scene_spec.scene_id} | Interpolation Repair Shot #{rec.shot_index}] "
            f"Trigger: {trigger_reason}"
        )

        # Resolve <FIRST_FRAME> and <LAST_FRAME> boundary PNGs
        ff_path: Optional[str] = None
        lf_path: Optional[str] = None

        if 0 < k < n_shots - 1:
            ff_path = manifest.shots[k - 1].last_frame_path
            lf_path = manifest.shots[k + 1].first_frame_path
        elif k == 0:
            lf_path = manifest.shots[1].first_frame_path
            gen_start_path = os.path.join(manifest.output_dir, "shot_1_interp_start.png")
            start_prompt = scene_spec.opening_keyframe_prompt or _build_default_boundary_keyframe_prompt(
                shot_spec=shot_spec,
                position="opening",
                num_refs=num_scene_refs,
                aspect_ratio=manifest.aspect_ratio,
            )
            start_bytes = await asyncio.to_thread(
                generate_reference_image_direct,
                prompt=start_prompt,
                reference_images_b64=scene_ref_b64s,
                aspect_ratio=manifest.aspect_ratio,
                client=active_rater_client,
            )
            with open(gen_start_path, "wb") as fp:
                fp.write(start_bytes)
            ff_path = gen_start_path
        else:
            ff_path = manifest.shots[k - 1].last_frame_path
            gen_end_path = os.path.join(manifest.output_dir, f"shot_{rec.shot_index}_interp_end.png")
            end_prompt = scene_spec.closing_keyframe_prompt or _build_default_boundary_keyframe_prompt(
                shot_spec=shot_spec,
                position="closing",
                num_refs=num_scene_refs,
                aspect_ratio=manifest.aspect_ratio,
            )
            end_bytes = await asyncio.to_thread(
                generate_reference_image_direct,
                prompt=end_prompt,
                reference_images_b64=scene_ref_b64s,
                aspect_ratio=manifest.aspect_ratio,
                client=active_rater_client,
            )
            with open(gen_end_path, "wb") as fp:
                fp.write(end_bytes)
            lf_path = gen_end_path

        if not ff_path or not lf_path or not os.path.exists(ff_path) or not os.path.exists(lf_path):
            print(f"  -> Skipping Shot #{rec.shot_index} interpolation (missing boundary frames).")
            continue

        ff_b64 = encode_image_file_b64(ff_path)
        lf_b64 = encode_image_file_b64(lf_path)
        interp_dur = resolve_omni_shot_duration(
            requested_sec=shot_spec.duration_sec if shot_spec.duration_sec is not None else rec.duration_sec,
            default_sec=scene_default_dur,
            task_or_mode="first_last_interpolation",
            is_two_frame_interp=True,
        )
        prev_feedback = (rec.evaluation_report or {}).get("feedback")
        interp_prompt = await optimize_shot_prompt_direct(
            raw_prompt=f"{shot_spec.camera_angle} shot: {shot_spec.description}",
            feedback=(
                f"Bridge smoothly from starting frame to final frame in one continuous single-take shot. "
                f"{prev_feedback or ''}"
            ).strip(),
            voice_transcript=shot_spec.spoken_dialogue,
            is_extend_shot=False,
            is_r2v_shot=False,
            duration_sec=interp_dur,
            client=active_rater_client,
        )

        interp_bytes = await asyncio.to_thread(
            generate_omni_clip_direct,
            prompt=interp_prompt,
            input_image_b64=ff_b64,
            end_image_b64=lf_b64,
            task=None,
            voice_transcript=shot_spec.spoken_dialogue,
            aspect_ratio=manifest.aspect_ratio,
            resolution=manifest.resolution,
            duration=interp_dur,
            client=active_gen_client,
        )

        cand_path = os.path.join(manifest.output_dir, f"shot_{rec.shot_index}_interp.mp4")
        with open(cand_path, "wb") as fp:
            fp.write(interp_bytes)

        has_jump, seam_mae, peak_mae = await asyncio.to_thread(
            detect_seam_jump_cut, ff_b64, cand_path, 28.0, 5
        )
        eval_res = await evaluate_clip_quality_direct(
            shot_index=rec.shot_index,
            prompt=interp_prompt,
            video_path=cand_path,
            evaluation_criteria=shot_spec.evaluation_criteria,
            spoken_dialogue=shot_spec.spoken_dialogue,
            reference_images_b64=scene_ref_b64s,
            prev_last_frame_b64=ff_b64,
            deterministic_signals={
                "interpolation_mode": "first_last_frame",
                "seam_mae": seam_mae,
                "peak_early_mae": peak_mae,
                "has_jump_cut": has_jump,
            },
            is_r2v_shot=False,
            is_extend_shot=False,
            client=active_rater_client,
        )
        interp_score = round(float(eval_res.get("score", 0.0)), 3)
        accepted = bool(interp_score > orig_score)
        print(
            f"  -> Interpolation Shot #{rec.shot_index}: orig={orig_score:.2f} -> interp={interp_score:.2f} "
            f"({'ACCEPTED' if accepted else 'KEPT_ORIGINAL'})"
        )

        orig_backup_path: Optional[str] = None
        if accepted and rec.video_path and os.path.exists(rec.video_path):
            orig_backup_path = os.path.join(
                manifest.output_dir, f"shot_{rec.shot_index}_failed_before_heal.mp4"
            )
            shutil.copyfile(rec.video_path, orig_backup_path)

        manifest.interpolation_repairs.append(
            InterpolationRepairRecord(
                shot_index=rec.shot_index,
                trigger_reason=trigger_reason,
                original_score=orig_score,
                interpolated_score=interp_score,
                accepted=accepted,
                first_frame_path=os.path.abspath(ff_path),
                last_frame_path=os.path.abspath(lf_path),
                candidate_video_path=os.path.abspath(cand_path),
                original_video_path=os.path.abspath(orig_backup_path) if orig_backup_path else None,
                evaluation_report=eval_res,
            )
        )

        if accepted and rec.video_path:
            shutil.copyfile(cand_path, rec.video_path)
            if rec.first_frame_path:
                await asyncio.to_thread(extract_first_frame, rec.video_path, rec.first_frame_path)
            if rec.last_frame_path:
                await asyncio.to_thread(extract_last_frame, rec.video_path, rec.last_frame_path)
            rec.effective_mode = "first_last_interpolation"
            rec.duration_sec = interp_dur
            rec.prompt = interp_prompt
            rec.attempts_used += 1
            rec.quality_score = interp_score
            rec.verdict = eval_res.get("verdict", "PASSED" if interp_score >= 0.8 else "COMPLETED_INTERP")
            rec.evaluation_report = eval_res
            any_accepted = True

    if any_accepted:
        valid_records = [r for r in manifest.shots if r.video_path and os.path.exists(r.video_path)]
        valid_clips = [r.video_path for r in valid_records if r.video_path]
        if valid_clips and manifest.stitched_video_path:
            await asyncio.to_thread(stitch_videos, valid_clips, manifest.stitched_video_path, crossfade_seconds)
            manifest.stitched_duration_sec = round(get_video_duration(manifest.stitched_video_path), 2)
            if len(valid_clips) >= 2:
                vo_lines = " ".join(
                    s.spoken_dialogue.strip() for s in scene_spec.shots if s.spoken_dialogue and s.spoken_dialogue.strip()
                ) or None
                manifest.master_seam_report = await evaluate_stitched_master_direct(
                    stitched_video_path=manifest.stitched_video_path,
                    num_shots=len(valid_clips),
                    shot_duration_sec=float(scene_default_dur),
                    original_intent=scene_spec.title or manifest.original_intent,
                    voice_transcript=vo_lines,
                    reference_images_b64=scene_ref_b64s,
                    shot_durations_sec=[float(r.duration_sec or scene_default_dur) for r in valid_records],
                    crossfade_sec=crossfade_seconds,
                    client=active_rater_client,
                )
        manifest_path = os.path.join(manifest.output_dir, "run_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fp:
            fp.write(manifest.model_dump_json(indent=2))

    return manifest


async def run_multi_scene_pipeline_async(
    scenes: List[SceneSpec],
    output_dir: str,
    original_intent: str = "",
    duration: int = 10,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    max_attempts: int = 3,
    max_parallel_scenes: int = 2,
    quality_threshold: float = 0.80,
    shot_crossfade_seconds: float = 0.08,
    scene_crossfade_seconds: float = 0.0,
    draft_mode: bool = False,
    draft_resolution: str = "360p",
    max_parallel_upscales: int = 3,
    vision_profile: Optional[VisionProfileSpec] = None,
    tts_model: str = DirectConfig.TTS_MODEL,
    tts_voice: str = DirectConfig.DEFAULT_TTS_VOICE,
    tts_style: str = "",
    tts_language: str = "en-US",
    auto_approve: bool = True,
    resume: bool = False,
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
) -> MultiSceneWorkflowManifest:
    """Executes hierarchical multi-scene generation (e.g., 3x30s -> 90s) with AVU scene rating, `<FIRST_FRAME>+<LAST_FRAME>` self-healing, and optional Draft->Upscale."""
    t0 = time.monotonic()
    abs_out_dir = os.path.abspath(output_dir)
    os.makedirs(abs_out_dir, exist_ok=True)

    tgt_res = str(resolution or "720p").strip().lower()
    drf_res = str(draft_resolution or "360p").strip().lower()
    active_draft = bool(draft_mode and drf_res != tgt_res)
    if active_draft:
        validate_upscale_transition(drf_res, tgt_res)

    active_gen_client = gen_client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    active_rater_client = rater_client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    sem = asyncio.Semaphore(max(1, max_parallel_scenes))
    upscale_sem = asyncio.Semaphore(max(1, max_parallel_upscales))

    async def _run_one_scene(idx: int, sc: SceneSpec) -> SceneManifestRecord:
        async with sem:
            t_sc0 = time.monotonic()
            scene_slug = sc.scene_id or f"scene_{idx + 1}"
            scene_dir = os.path.join(abs_out_dir, scene_slug)
            saved_sc_mf = os.path.join(scene_dir, "run_manifest.json")
            scene_default_dur = int(sc.duration_sec if sc.duration_sec is not None else duration)
            has_sc_refs = bool(sc.reference_paths)
            if sc.shots:
                est_scene_sec = sum(
                    resolve_omni_shot_duration(
                        requested_sec=s.duration_sec,
                        default_sec=scene_default_dur,
                        task_or_mode=_resolve_effective_shot_mode(sc.mode, s.mode_override, j, has_sc_refs),
                        is_two_frame_interp=False,
                    )
                    for j, s in enumerate(sc.shots)
                )
            else:
                est_scene_sec = 3 * scene_default_dur
            top_scene_mp4 = os.path.join(abs_out_dir, f"{scene_slug}_{est_scene_sec}s.mp4")
            if resume and os.path.exists(saved_sc_mf):
                sc_manifest = WorkflowManifest.model_validate_json(Path(saved_sc_mf).read_text(encoding="utf-8"))
                mf_sec = sum(int(r.duration_sec or scene_default_dur) for r in sc_manifest.shots) or est_scene_sec
                alt_top_mp4 = os.path.join(abs_out_dir, f"{scene_slug}_{mf_sec}s.mp4")
                resumed_top = top_scene_mp4 if os.path.exists(top_scene_mp4) else (alt_top_mp4 if os.path.exists(alt_top_mp4) else None)
                if resumed_top:
                    print(f"\n=== [{scene_slug}] Resumed completed scene ({sc_manifest.stitched_duration_sec}s) ===")
                    return SceneManifestRecord(
                        scene_id=scene_slug,
                        title=sc.title,
                        output_dir=scene_dir,
                        scene_video_path=resumed_top,
                        scene_duration_sec=sc_manifest.stitched_duration_sec,
                        elapsed_sec=sc_manifest.elapsed_sec,
                        draft_and_avu_sec=sc_manifest.draft_and_avu_sec,
                        interpolation_repair_sec=sc_manifest.interpolation_repair_sec,
                        upscale_sec=sc_manifest.upscale_sec,
                        stitch_and_seam_audit_sec=sc_manifest.stitch_and_seam_audit_sec,
                        reference_paths=[os.path.abspath(p) for p in sc.reference_paths if os.path.exists(p)],
                        shots=sc_manifest.shots,
                        interpolation_repairs=sc_manifest.interpolation_repairs,
                        scene_seam_report=sc_manifest.master_seam_report,
                    )

            scene_vo = " ".join(
                s.spoken_dialogue.strip() for s in sc.shots if s.spoken_dialogue and s.spoken_dialogue.strip()
            ) or None
            scene_prompt = sc.title or (" / ".join(s.description for s in sc.shots))
            res_banner = f"{drf_res} draft -> {tgt_res} upscale" if active_draft else tgt_res
            print(
                f"\n=== [{scene_slug}] Starting {est_scene_sec}s Scene ({res_banner}): "
                f"{sc.title or scene_slug} ==="
            )

            sc_manifest = await run_standalone_pipeline_async(
                prompt=scene_prompt,
                output_dir=scene_dir,
                mode=sc.mode,
                num_shots=len(sc.shots) or 3,
                duration=scene_default_dur,
                aspect_ratio=aspect_ratio,
                resolution=tgt_res,
                reference_paths=sc.reference_paths or None,
                voice_transcript=scene_vo,
                storyboard_specs=sc.shots or None,
                vision_profile=vision_profile,
                tts_model=tts_model,
                tts_voice=tts_voice,
                tts_style=tts_style,
                tts_language=tts_language,
                quality_threshold=quality_threshold,
                auto_approve=True,
                max_attempts=max_attempts,
                crossfade_seconds=shot_crossfade_seconds,
                draft_mode=active_draft,
                draft_resolution=drf_res,
                max_parallel_upscales=max_parallel_upscales,
                resume=resume,
                gen_client=active_gen_client,
                rater_client=active_rater_client,
                _defer_upscale=active_draft,
            )

            t_rep0 = time.monotonic()
            sc_manifest = await _repair_scene_shots_with_interpolation(
                scene_spec=sc,
                manifest=sc_manifest,
                quality_threshold=quality_threshold,
                crossfade_seconds=shot_crossfade_seconds,
                gen_client=active_gen_client,
                rater_client=active_rater_client,
            )
            sc_manifest.interpolation_repair_sec = round(time.monotonic() - t_rep0, 2)

            if active_draft:
                sc_manifest = await _upscale_manifest_shots_async(
                    manifest=sc_manifest,
                    source_resolution=drf_res,
                    target_resolution=tgt_res,
                    max_parallel_upscales=max_parallel_upscales,
                    crossfade_seconds=shot_crossfade_seconds,
                    upscale_sem=upscale_sem,
                    gen_client=active_gen_client,
                )

            sc_manifest.elapsed_sec = round(time.monotonic() - t_sc0, 2)
            with open(saved_sc_mf, "w", encoding="utf-8") as fp:
                fp.write(sc_manifest.model_dump_json(indent=2))

            exported_scene_video: Optional[str] = sc_manifest.stitched_video_path
            if sc_manifest.stitched_video_path and os.path.exists(sc_manifest.stitched_video_path):
                actual_nominal_sec = sum(int(r.duration_sec or scene_default_dur) for r in sc_manifest.shots) or est_scene_sec
                top_scene_mp4 = os.path.join(abs_out_dir, f"{scene_slug}_{actual_nominal_sec}s.mp4")
                shutil.copyfile(sc_manifest.stitched_video_path, top_scene_mp4)
                exported_scene_video = top_scene_mp4

            return SceneManifestRecord(
                scene_id=scene_slug,
                title=sc.title,
                output_dir=scene_dir,
                scene_video_path=exported_scene_video,
                scene_duration_sec=sc_manifest.stitched_duration_sec,
                elapsed_sec=sc_manifest.elapsed_sec,
                draft_and_avu_sec=sc_manifest.draft_and_avu_sec,
                interpolation_repair_sec=sc_manifest.interpolation_repair_sec,
                upscale_sec=sc_manifest.upscale_sec,
                stitch_and_seam_audit_sec=sc_manifest.stitch_and_seam_audit_sec,
                reference_paths=[os.path.abspath(p) for p in sc.reference_paths if os.path.exists(p)],
                shots=sc_manifest.shots,
                interpolation_repairs=sc_manifest.interpolation_repairs,
                scene_seam_report=sc_manifest.master_seam_report,
            )

    scene_records = list(await asyncio.gather(*(_run_one_scene(i, s) for i, s in enumerate(scenes))))

    valid_scene_records = [
        sr for sr in scene_records if sr.scene_video_path and os.path.exists(sr.scene_video_path)
    ]
    scene_videos = [sr.scene_video_path for sr in valid_scene_records if sr.scene_video_path]
    total_shots = sum(len(sr.shots) for sr in scene_records)
    master_video_path: Optional[str] = None
    master_dur: float = 0.0
    master_report: Optional[Dict[str, Any]] = None
    master_stitch_sec: float = 0.0

    if scene_videos:
        t_ms0 = time.monotonic()
        nominal_total_sec = (
            sum(int(sh.duration_sec or duration) for sr in scene_records for sh in sr.shots)
            or (total_shots * duration)
        )
        target_master = os.path.join(abs_out_dir, f"output_master_{nominal_total_sec}s.mp4")
        master_video_path = await asyncio.to_thread(
            stitch_videos, scene_videos, target_master, scene_crossfade_seconds
        )
        master_dur = round(get_video_duration(master_video_path), 2)

        if len(scene_videos) >= 2:
            hero_ref_b64s: Optional[List[str]] = None
            for sc in scenes:
                if sc.reference_paths and os.path.exists(sc.reference_paths[0]):
                    hero_ref_b64s = [encode_image_file_b64(sc.reference_paths[0])]
                    break
            full_vo = " ".join(
                s.spoken_dialogue.strip()
                for sc in scenes
                for s in sc.shots
                if s.spoken_dialogue and s.spoken_dialogue.strip()
            ) or None
            avg_scene_dur = round(master_dur / float(len(scene_videos)), 2) if master_dur > 0 else float(3 * duration)
            per_scene_durs = [
                float(sr.scene_duration_sec)
                if sr.scene_duration_sec > 0
                else float(sum(int(sh.duration_sec or duration) for sh in sr.shots) or (3 * duration))
                for sr in valid_scene_records
            ]
            master_report = await evaluate_stitched_master_direct(
                stitched_video_path=master_video_path,
                num_shots=len(scene_videos),
                shot_duration_sec=avg_scene_dur,
                original_intent=original_intent or " / ".join(sc.title or sc.scene_id for sc in scenes),
                voice_transcript=full_vo,
                reference_images_b64=hero_ref_b64s,
                shot_durations_sec=per_scene_durs,
                crossfade_sec=scene_crossfade_seconds,
                client=active_rater_client,
            )
        master_stitch_sec = round(time.monotonic() - t_ms0, 2)

    any_tpvg_tts = any(str(sc.mode or "").strip().lower() == "tpvg_tts" for sc in scenes)
    qa_items = [
        {
            "path": sh.video_path,
            "label": f"{sr.scene_id} S{sh.shot_index}",
            "score": sh.quality_score,
            "status": "PASSED" if float(sh.quality_score or 0.0) >= quality_threshold else "ESCALATED",
        }
        for sr in scene_records
        for sh in sr.shots
        if sh.video_path and os.path.exists(sh.video_path)
    ]
    qa_sheet_path: Optional[str] = None
    if qa_items:
        qa_sheet_path = os.path.join(abs_out_dir, "qa_contact_sheet.png")
        await asyncio.to_thread(build_contact_sheet, qa_items, qa_sheet_path, 3)

    esc_path: Optional[str] = None
    human_review_req = False
    if not auto_approve:
        unresolved = [
            {
                "scene_id": sr.scene_id,
                "shot_index": sh.shot_index,
                "score": sh.quality_score,
                "verdict": sh.verdict,
                "detected_genmedia_issues": sh.detected_genmedia_issues,
                "feedback": (sh.evaluation_report or {}).get("feedback", ""),
                "video_path": sh.video_path,
            }
            for sr in scene_records
            for sh in sr.shots
            if float(sh.quality_score or 0.0) < quality_threshold
        ]
        m_score = (master_report or {}).get("score")
        if unresolved or (m_score is not None and float(m_score) < 0.75):
            esc_path = os.path.join(abs_out_dir, "escalation_report.json")
            Path(esc_path).write_text(
                json.dumps(
                    {
                        "status": "human_review_required",
                        "quality_threshold": quality_threshold,
                        "unresolved_shots": unresolved,
                        "master_seam_score": m_score,
                        "qa_contact_sheet_path": qa_sheet_path,
                        "master_video_path": master_video_path,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            human_review_req = True

    multi_manifest = MultiSceneWorkflowManifest(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        original_intent=original_intent or " / ".join(sc.title or sc.scene_id for sc in scenes),
        num_scenes=len(scenes),
        total_shots=total_shots,
        duration_per_shot_sec=duration,
        aspect_ratio=aspect_ratio,
        resolution=tgt_res,
        draft_mode=active_draft,
        draft_resolution=drf_res if active_draft else None,
        elapsed_sec=round(time.monotonic() - t0, 2),
        sum_scene_draft_and_avu_sec=round(sum(sr.draft_and_avu_sec for sr in scene_records), 2),
        sum_scene_repair_sec=round(sum(sr.interpolation_repair_sec for sr in scene_records), 2),
        sum_scene_upscale_sec=round(sum(sr.upscale_sec for sr in scene_records), 2),
        master_stitch_and_seam_audit_sec=master_stitch_sec,
        output_dir=abs_out_dir,
        tts_model=normalize_tts_model_name(tts_model) if any_tpvg_tts else None,
        tts_voice=tts_voice if any_tpvg_tts else None,
        qa_contact_sheet_path=qa_sheet_path,
        escalation_report_path=esc_path,
        human_review_required=human_review_req,
        master_video_path=master_video_path,
        master_duration_sec=master_dur,
        scenes=scene_records,
        master_seam_report=master_report,
    )
    manifest_path = os.path.join(abs_out_dir, "run_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fp:
        fp.write(multi_manifest.model_dump_json(indent=2))

    print(
        f"\n[Multi-Scene Completed] Master Video: {master_video_path} ({master_dur}s, res={tgt_res}, "
        f"elapsed={multi_manifest.elapsed_sec}s) | Manifest: {manifest_path}"
    )
    return multi_manifest


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone ADK-free Multi-Shot & Multi-Scene Video Production Pipeline (Gemini Omni 1.2 Flash + Gemini 3.8 Flash AVU)."
    )
    parser.add_argument("--prompt", default="", help="Commercial brief or visual narrative prompt.")
    parser.add_argument("--storyboard-json", help="Optional path to single-scene pre-structured JSON storyboard list.")
    parser.add_argument(
        "--scenes-json",
        help="Optional path to hierarchical multi-scene JSON spec (e.g., 3 scenes x 3 shots = 90s with interpolation repair).",
    )
    parser.add_argument("--reference", nargs="*", help="Optional #FFFFFF reference image path(s).")
    parser.add_argument(
        "--mode",
        choices=["reference", "i2v_chaining", "video_extend", "hybrid", "tpvg_tts"],
        default="video_extend",
        help="Multi-shot continuity mode (tpvg_tts = Gemini 3.8 TTS + Omni TPVG/Mux hybrid).",
    )
    parser.add_argument(
        "--stage",
        choices=["plan", "plates", "execute"],
        default="execute",
        help="Production stage: 'plan' (VisionProfile + Storyboard), 'plates' (render scene plates + contact sheet), or 'execute' (render + audit).",
    )
    parser.add_argument(
        "--check-spec",
        action="store_true",
        help="Validate storyboard/scenes spec (WPM pacing, GA duration bounds, missing assets, angle cuts) and exit without video compute.",
    )
    parser.add_argument("--vision-json", default=None, help="Optional path to director_plan.json / VisionProfileSpec JSON.")
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Bypass Dual HITL Gate 2 pause (returns exit code 0 even if shots need human review).",
    )
    parser.add_argument("--tts-model", default=DirectConfig.TTS_MODEL, help="TTS model ID or alias (gemini-3.8-tts -> gemini-3.8-flash-tts).")
    parser.add_argument("--tts-voice", default=DirectConfig.DEFAULT_TTS_VOICE, help="Default TTS voice (Kore, Puck, Aoede, Charon, Fenrir, Leda, Zephyr).")
    parser.add_argument("--tts-style", default="", help="Optional TTS speaking style directive.")
    parser.add_argument("--tts-language", default="en-US", help="BCP-47 TTS language code (default: en-US).")
    parser.add_argument("--shots", type=int, default=3, help="Number of shots (ignored if --storyboard-json set).")
    parser.add_argument(
        "--duration",
        type=int,
        default=10,
        help="Default duration per shot in seconds (3-15s for R2V/I2V/T2V; auto-clamped to 3-10s for extend/interp).",
    )
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16"])
    parser.add_argument("--resolution", default="720p", choices=["360p", "720p", "1080p", "4k"])
    parser.add_argument(
        "--draft-mode",
        action="store_true",
        help="Enable Omni 1.2 Draft Mode: draft, AVU-audit, retry & self-heal at --draft-resolution (360p), then standalone task='upscale' winning clips to --resolution.",
    )
    parser.add_argument(
        "--draft-resolution",
        default="360p",
        choices=["360p", "720p"],
        help="Draft resolution used during candidate generation and AVU agentic loop when --draft-mode is active (default: 360p).",
    )
    parser.add_argument(
        "--max-parallel-upscales",
        type=int,
        default=3,
        help="Max concurrent standalone task='upscale' calls when --draft-mode promotes winning clips (default: 3).",
    )
    parser.add_argument("--voice-transcript", default=None, help="Optional full spoken voiceover script.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Best-of-K retry budget per shot.")
    parser.add_argument("--max-parallel", type=int, default=3, help="Max concurrent shots in Mode A (reference).")
    parser.add_argument("--max-parallel-scenes", type=int, default=2, help="Max concurrent scenes when --scenes-json is used.")
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=0.80,
        help="Shot quality threshold below which post-scene <FIRST_FRAME>+<LAST_FRAME> interpolation repair triggers.",
    )
    parser.add_argument(
        "--crossfade",
        type=float,
        default=None,
        help="Crossfade duration in seconds within a scene (default: 0.08s for B/C/Hybrid, 0.0s hard-cut for Mode A R2V).",
    )
    parser.add_argument(
        "--scene-crossfade",
        type=float,
        default=0.0,
        help="Crossfade duration in seconds between distinct scenes in --scenes-json mode (default: 0.0s clean cut).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse already-completed scene manifests and saved shot_k.mp4 clips in --output-dir.",
    )
    parser.add_argument("--output-dir", required=True, help="Local directory for rendered clips and run_manifest.json.")
    return parser


def _load_optional_vision_profile(vision_json_path: Optional[str]) -> Optional[VisionProfileSpec]:
    if not vision_json_path or not os.path.exists(vision_json_path):
        return None
    raw = json.loads(Path(vision_json_path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "vision_profile" in raw:
        return VisionProfileSpec.model_validate(raw["vision_profile"])
    return VisionProfileSpec.model_validate(raw)


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    abs_out_dir = os.path.abspath(args.output_dir)
    os.makedirs(abs_out_dir, exist_ok=True)
    vision_profile = _load_optional_vision_profile(args.vision_json)

    if args.stage == "plan":
        prompt_text = args.prompt.strip()
        if not prompt_text:
            parser.error("--stage plan requires --prompt.")
        plan = asyncio.run(
            generate_vision_and_plan_direct(
                intent=prompt_text,
                num_shots=args.shots,
                mode=args.mode,
                aspect_ratio=args.aspect_ratio,
                voice_transcript=args.voice_transcript,
                default_duration_sec=args.duration,
                tts_voice=args.tts_voice,
                tts_style=args.tts_style,
            )
        )
        plan_json_p = os.path.join(abs_out_dir, "director_plan.json")
        plan_md_p = os.path.join(abs_out_dir, "director_plan.md")
        sb_json_p = os.path.join(abs_out_dir, "storyboard_defined.json")
        Path(plan_json_p).write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        Path(plan_md_p).write_text(format_director_plan_markdown(plan), encoding="utf-8")
        Path(sb_json_p).write_text(json.dumps([s.model_dump() for s in plan.shots], indent=2), encoding="utf-8")
        spec_check = validate_production_spec(
            storyboard_specs=plan.shots,
            default_mode=args.mode,
            default_duration=args.duration,
        )
        print(json.dumps({
            "status": "plan_ready",
            "director_plan_json": plan_json_p,
            "director_plan_md": plan_md_p,
            "storyboard_defined_json": sb_json_p,
            "spec_check": spec_check,
        }, indent=2))
        return 0

    if args.stage == "plates":
        plate_items: List[Dict[str, Any]] = []
        style_suffix = f" {vision_profile.style_anchor}" if (vision_profile and vision_profile.style_anchor) else ""
        if args.scenes_json:
            raw_scenes_doc = json.loads(Path(args.scenes_json).read_text(encoding="utf-8"))
            raw_scenes_list = raw_scenes_doc.get("scenes", []) if isinstance(raw_scenes_doc, dict) else raw_scenes_doc
            scene_specs = [SceneSpec.model_validate(item) for item in raw_scenes_list]
            for sc in scene_specs:
                sc_dir = os.path.join(abs_out_dir, sc.scene_id)
                os.makedirs(sc_dir, exist_ok=True)
                target_plate = sc.reference_paths[-1] if (sc.scene_plate_prompt and len(sc.reference_paths) >= 2) else (
                    sc.reference_paths[0] if (sc.scene_plate_prompt and len(sc.reference_paths) == 1) else os.path.join(sc_dir, "scene_plate.png")
                )
                if sc.scene_plate_prompt and not os.path.exists(target_plate):
                    cond_refs = [encode_image_file_b64(p) for p in sc.reference_paths if p != target_plate and os.path.exists(p)] or None
                    img_bytes = generate_reference_image_direct(
                        prompt=f"{sc.scene_plate_prompt.strip()}{style_suffix}".strip(),
                        reference_images_b64=cond_refs,
                        aspect_ratio=args.aspect_ratio,
                    )
                    os.makedirs(os.path.dirname(os.path.abspath(target_plate)), exist_ok=True)
                    Path(target_plate).write_bytes(img_bytes)
                for p in (sc.reference_paths or [target_plate]):
                    if p and os.path.exists(p):
                        plate_items.append({"path": os.path.abspath(p), "label": f"{sc.scene_id}: {os.path.basename(p)}", "status": "PLATE"})
        else:
            for p in (args.reference or []):
                if os.path.exists(p):
                    plate_items.append({"path": os.path.abspath(p), "label": os.path.basename(p), "status": "PLATE"})
        if not plate_items:
            parser.error("--stage plates found no scene_plate_prompt or existing reference images to render.")
        sheet_p = os.path.join(abs_out_dir, "plates_contact_sheet.png")
        build_contact_sheet(plate_items, sheet_p, cols=min(3, len(plate_items)))
        print(json.dumps({
            "status": "plates_ready",
            "plates_contact_sheet_path": sheet_p,
            "plates_count": len(plate_items),
        }, indent=2))
        return 0

    if args.scenes_json:
        raw_scenes_doc = json.loads(Path(args.scenes_json).read_text(encoding="utf-8"))
        if isinstance(raw_scenes_doc, dict):
            intent_str = args.prompt.strip() or raw_scenes_doc.get("original_intent", "")
            raw_scenes_list = raw_scenes_doc.get("scenes", [])
        else:
            intent_str = args.prompt.strip()
            raw_scenes_list = raw_scenes_doc
        scene_specs = [SceneSpec.model_validate(item) for item in raw_scenes_list]
        if not scene_specs:
            parser.error("--scenes-json contained zero scenes.")

        spec_check = validate_production_spec(
            scene_specs=scene_specs,
            default_mode=args.mode,
            default_duration=args.duration,
        )
        if args.check_spec:
            print(json.dumps(spec_check, indent=2))
            return 0 if spec_check["valid"] else 1

        multi_manifest = asyncio.run(
            run_multi_scene_pipeline_async(
                scenes=scene_specs,
                output_dir=args.output_dir,
                original_intent=intent_str,
                duration=args.duration,
                aspect_ratio=args.aspect_ratio,
                resolution=args.resolution,
                max_attempts=args.max_attempts,
                max_parallel_scenes=args.max_parallel_scenes,
                quality_threshold=args.quality_threshold,
                shot_crossfade_seconds=args.crossfade if args.crossfade is not None else 0.08,
                scene_crossfade_seconds=args.scene_crossfade,
                draft_mode=args.draft_mode,
                draft_resolution=args.draft_resolution,
                max_parallel_upscales=args.max_parallel_upscales,
                vision_profile=vision_profile,
                tts_model=args.tts_model,
                tts_voice=args.tts_voice,
                tts_style=args.tts_style,
                tts_language=args.tts_language,
                auto_approve=args.auto_approve,
                resume=args.resume,
            )
        )
        print(json.dumps({
            "status": "human_review_required" if multi_manifest.human_review_required else "ok",
            "master_video_path": multi_manifest.master_video_path,
            "master_duration_sec": multi_manifest.master_duration_sec,
            "resolution": multi_manifest.resolution,
            "draft_mode": multi_manifest.draft_mode,
            "draft_resolution": multi_manifest.draft_resolution,
            "tts_model": multi_manifest.tts_model,
            "tts_voice": multi_manifest.tts_voice,
            "qa_contact_sheet_path": multi_manifest.qa_contact_sheet_path,
            "escalation_report_path": multi_manifest.escalation_report_path,
            "elapsed_sec": multi_manifest.elapsed_sec,
            "sum_scene_draft_and_avu_sec": multi_manifest.sum_scene_draft_and_avu_sec,
            "sum_scene_repair_sec": multi_manifest.sum_scene_repair_sec,
            "sum_scene_upscale_sec": multi_manifest.sum_scene_upscale_sec,
            "master_stitch_and_seam_audit_sec": multi_manifest.master_stitch_and_seam_audit_sec,
            "manifest_path": os.path.join(multi_manifest.output_dir, "run_manifest.json"),
            "scene_scores": [
                {
                    "scene_id": s.scene_id,
                    "elapsed_sec": s.elapsed_sec,
                    "draft_and_avu_sec": s.draft_and_avu_sec,
                    "interpolation_repair_sec": s.interpolation_repair_sec,
                    "upscale_sec": s.upscale_sec,
                    "shot_scores": [sh.quality_score for sh in s.shots],
                    "repairs": len(s.interpolation_repairs),
                    "scene_seam_score": (s.scene_seam_report or {}).get("score"),
                }
                for s in multi_manifest.scenes
            ],
            "master_score": (multi_manifest.master_seam_report or {}).get("score"),
        }, indent=2))
        return 2 if multi_manifest.human_review_required else 0

    specs: Optional[List[StoryboardEntrySpec]] = None
    if args.storyboard_json:
        raw_data = json.loads(Path(args.storyboard_json).read_text(encoding="utf-8"))
        specs = [StoryboardEntrySpec.model_validate(item) for item in raw_data]

    if args.check_spec:
        if not specs:
            parser.error("--check-spec requires --storyboard-json or --scenes-json.")
        spec_check = validate_production_spec(
            storyboard_specs=specs,
            default_mode=args.mode,
            default_duration=args.duration,
        )
        print(json.dumps(spec_check, indent=2))
        return 0 if spec_check["valid"] else 1

    prompt_text = args.prompt.strip()
    if not prompt_text and specs:
        prompt_text = " / ".join(s.description for s in specs)
    if not prompt_text:
        parser.error("Provide --prompt, --storyboard-json, or --scenes-json.")

    manifest = asyncio.run(
        run_standalone_pipeline_async(
            prompt=prompt_text,
            output_dir=args.output_dir,
            mode=args.mode,
            num_shots=args.shots,
            duration=args.duration,
            aspect_ratio=args.aspect_ratio,
            resolution=args.resolution,
            reference_paths=args.reference,
            voice_transcript=args.voice_transcript,
            storyboard_specs=specs,
            vision_profile=vision_profile,
            tts_model=args.tts_model,
            tts_voice=args.tts_voice,
            tts_style=args.tts_style,
            tts_language=args.tts_language,
            quality_threshold=args.quality_threshold,
            auto_approve=args.auto_approve,
            max_attempts=args.max_attempts,
            max_parallel=args.max_parallel,
            crossfade_seconds=args.crossfade,
            draft_mode=args.draft_mode,
            draft_resolution=args.draft_resolution,
            max_parallel_upscales=args.max_parallel_upscales,
            resume=args.resume,
        )
    )
    print(json.dumps({
        "status": "human_review_required" if manifest.human_review_required else "ok",
        "stitched_video_path": manifest.stitched_video_path,
        "stitched_duration_sec": manifest.stitched_duration_sec,
        "resolution": manifest.resolution,
        "draft_mode": manifest.draft_mode,
        "draft_resolution": manifest.draft_resolution,
        "tts_model": manifest.tts_model,
        "tts_voice": manifest.tts_voice,
        "qa_contact_sheet_path": manifest.qa_contact_sheet_path,
        "escalation_report_path": manifest.escalation_report_path,
        "elapsed_sec": manifest.elapsed_sec,
        "draft_and_avu_sec": manifest.draft_and_avu_sec,
        "upscale_sec": manifest.upscale_sec,
        "manifest_path": os.path.join(manifest.output_dir, "run_manifest.json"),
        "shot_scores": [s.quality_score for s in manifest.shots],
        "master_score": (manifest.master_seam_report or {}).get("score"),
    }, indent=2))
    return 2 if manifest.human_review_required else 0


if __name__ == "__main__":
    sys.exit(main())
