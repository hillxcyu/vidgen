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
    detect_r2v_first_frame_lock,
    detect_seam_jump_cut,
    encode_image_file_b64,
    extract_first_frame,
    extract_last_frame,
    extract_video_tail,
    get_video_duration,
    stitch_videos,
    trim_video_prefix,
)
from omni_direct import (  # noqa: E402
    DirectConfig,
    StoryboardEntrySpec,
    evaluate_clip_quality_direct,
    evaluate_stitched_master_direct,
    generate_omni_clip_direct,
    generate_reference_image_direct,
    generate_storyboard_direct,
    get_direct_genai_client,
    optimize_shot_prompt_direct,
)


class ShotRecord(BaseModel):
    shot_index: int
    effective_mode: str
    prompt: str
    evaluation_criteria: str
    spoken_dialogue: Optional[str] = None
    attempts_used: int = 0
    quality_score: Optional[float] = None
    verdict: str = "PENDING"
    video_path: Optional[str] = None
    first_frame_path: Optional[str] = None
    last_frame_path: Optional[str] = None
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
    reference_paths: List[str] = Field(default_factory=list, description="Per-scene reference images (e.g., [hero_anchor.png, scene_plate.png]).")
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
    orchestrator_model: str = DirectConfig.ORCHESTRATOR_MODEL
    video_gen_model: str = DirectConfig.VIDEO_GEN_MODEL
    media_processing: str = DirectConfig.MEDIA_PROCESSING
    elapsed_sec: float = 0.0
    output_dir: str
    reference_anchor_path: Optional[str] = None
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
    orchestrator_model: str = DirectConfig.ORCHESTRATOR_MODEL
    video_gen_model: str = DirectConfig.VIDEO_GEN_MODEL
    media_processing: str = DirectConfig.MEDIA_PROCESSING
    elapsed_sec: float = 0.0
    output_dir: str
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


def _resolve_effective_shot_mode(
    pipeline_mode: str,
    shot_override: Optional[str],
    idx: int,
    has_references: bool,
) -> str:
    """Determines the exact generation conditioning mode for shot `idx` (0-based)."""
    raw = (shot_override or pipeline_mode or "reference").strip().lower()
    if raw == "hybrid":
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
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
) -> ShotRecord:
    """Executes prompt optimization, generation, OpenCV seam/R2V checks, Auto-Rater v2, and Best-of-K checkpointing."""
    shot_idx = spec.scene_number
    raw_prompt = f"{spec.camera_angle} shot: {spec.description}"
    clip_path = os.path.join(output_dir, f"shot_{shot_idx}.mp4")
    ff_path = os.path.join(output_dir, f"shot_{shot_idx}_first_frame.png")
    lf_path = os.path.join(output_dir, f"shot_{shot_idx}_last_frame.png")

    is_extend_shot = effective_mode == "video_extend" and idx > 0 and prev_video_tail_b64 is not None
    is_i2v_shot = effective_mode == "i2v_chaining" and idx > 0 and prev_frame_b64 is not None
    is_r2v_shot = bool(reference_images_b64 and not is_extend_shot and not is_i2v_shot)

    record = ShotRecord(
        shot_index=shot_idx,
        effective_mode="video_extend" if is_extend_shot else ("i2v_chaining" if is_i2v_shot else "reference"),
        prompt=raw_prompt,
        evaluation_criteria=spec.evaluation_criteria,
        spoken_dialogue=spec.spoken_dialogue,
    )

    best_score: float = -1.0
    best_bytes: Optional[bytes] = None
    best_prompt: str = raw_prompt
    best_eval: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None

    for attempt in range(max(1, max_attempts)):
        record.attempts_used = attempt + 1
        opt_prompt = await optimize_shot_prompt_direct(
            raw_prompt=raw_prompt,
            feedback=feedback,
            voice_transcript=spec.spoken_dialogue,
            is_extend_shot=is_extend_shot,
            is_r2v_shot=is_r2v_shot,
            client=rater_client,
        )

        shot_refs = reference_images_b64 if is_r2v_shot else None
        shot_task = "extend" if is_extend_shot else ("reference_to_video" if shot_refs else None)
        shot_in_img = prev_frame_b64 if is_i2v_shot else None
        shot_in_vid = prev_video_tail_b64 if is_extend_shot else None

        print(
            f"[Shot #{shot_idx} | Attempt {attempt + 1}/{max_attempts}] "
            f"mode={record.effective_mode} task={shot_task or 'i2v/t2v'}"
        )

        video_bytes = await asyncio.to_thread(
            generate_omni_clip_direct,
            prompt=opt_prompt,
            input_image_b64=shot_in_img,
            input_video_b64=shot_in_vid,
            task=shot_task,
            reference_images_b64=shot_refs,
            voice_transcript=spec.spoken_dialogue,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            client=gen_client,
        )

        if is_extend_shot and prev_video_tail_sec > 0:
            video_bytes = await asyncio.to_thread(
                trim_video_prefix,
                video_bytes,
                prev_video_tail_sec,
                float(duration),
                prev_last_frame_b64,
            )

        with open(clip_path, "wb") as fp:
            fp.write(video_bytes)

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
                    feedback = (
                        f"Hard jump-cut detected at extension boundary (peak MAE={peak_mae:.1f}). "
                        "Continue seamlessly from the exact ending frame and room in one unbroken camera shot."
                    )
                    continue

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
            client=rater_client,
        )
        score = float(eval_res.get("score", 0.0))
        avu_toks = (eval_res.get("deterministic_telemetry") or {}).get("avu_tool_use_tokens")
        print(
            f"  -> Score={score:.2f} ({eval_res.get('verdict')}) | "
            f"WER={eval_res.get('transcript_wer')} | AVU_tokens={avu_toks}"
        )

        if score > best_score:
            best_score = score
            best_bytes = video_bytes
            best_prompt = opt_prompt
            best_eval = eval_res

        if score >= 0.8 or attempt == max_attempts - 1:
            break
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
        record.evaluation_report = best_eval

    return record


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
    max_attempts: int = 3,
    max_parallel: int = DirectConfig.MAX_PARALLEL_SHOTS,
    crossfade_seconds: Optional[float] = None,
    resume: bool = False,
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
) -> WorkflowManifest:
    """Runs the complete ADK-free multi-shot generation, rating, and stitching pipeline locally."""
    t0 = time.monotonic()
    abs_out_dir = os.path.abspath(output_dir)
    os.makedirs(abs_out_dir, exist_ok=True)

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
    can_parallel = all(m == "reference" for m in effective_modes) and len(specs) > 1

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
                    resolution=resolution,
                    duration=duration,
                    max_attempts=max_attempts,
                    output_dir=abs_out_dir,
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
                    client=active_rater_client,
                )
                sc_val = round(float(eval_res.get("score", 0.0)), 3)
                print(f"[Resume Shot #{i + 1}] Reusing saved {existing_clip} -> Score={sc_val:.2f}")
                rec = ShotRecord(
                    shot_index=i + 1,
                    effective_mode=eff_m,
                    prompt=sp.description,
                    evaluation_criteria=sp.evaluation_criteria,
                    spoken_dialogue=sp.spoken_dialogue,
                    attempts_used=1,
                    quality_score=sc_val,
                    verdict=eval_res.get("verdict", "PASSED" if sc_val >= 0.8 else "COMPLETED_BEST_OF_K"),
                    video_path=os.path.abspath(existing_clip),
                    first_frame_path=os.path.abspath(ff_p),
                    last_frame_path=os.path.abspath(lf_p),
                    evaluation_report=eval_res,
                )
            else:
                rec = await _execute_single_shot(
                    idx=i,
                    spec=sp,
                    effective_mode=eff_m,
                    reference_images_b64=reference_b64s,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    duration=duration,
                    max_attempts=max_attempts,
                    output_dir=abs_out_dir,
                    prev_frame_b64=prev_frame_b64 if eff_m == "i2v_chaining" else None,
                    prev_last_frame_b64=prev_last_frame_b64,
                    prev_video_tail_b64=prev_tail_b64 if eff_m == "video_extend" else None,
                    prev_video_tail_sec=prev_tail_sec if eff_m == "video_extend" else 0.0,
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

    valid_clips = [r.video_path for r in shot_records if r.video_path and os.path.exists(r.video_path)]
    stitched_path: Optional[str] = None
    stitched_dur: float = 0.0
    master_report: Optional[Dict[str, Any]] = None

    if valid_clips:
        # Default to 0.0s hard-cut for pure multi-location R2V montages to avoid pose ghosting, else 0.08s xfade
        resolved_xfade = (
            crossfade_seconds
            if crossfade_seconds is not None
            else (0.0 if all(m == "reference" for m in effective_modes) else 0.08)
        )
        stitched_name = f"output_stitched_{len(valid_clips) * duration}s.mp4"
        target_stitched = os.path.join(abs_out_dir, stitched_name)
        stitched_path = await asyncio.to_thread(stitch_videos, valid_clips, target_stitched, resolved_xfade)
        stitched_dur = round(get_video_duration(stitched_path), 2)

        if len(valid_clips) >= 2:
            master_report = await evaluate_stitched_master_direct(
                stitched_video_path=stitched_path,
                num_shots=len(valid_clips),
                shot_duration_sec=float(duration),
                original_intent=prompt,
                voice_transcript=voice_transcript,
                reference_images_b64=reference_b64s,
                client=active_rater_client,
            )

    manifest = WorkflowManifest(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        original_intent=prompt,
        mode=mode,
        num_shots=len(specs),
        duration_per_shot_sec=duration,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        elapsed_sec=round(time.monotonic() - t0, 2),
        output_dir=abs_out_dir,
        reference_anchor_path=saved_anchor_path,
        stitched_video_path=stitched_path,
        stitched_duration_sec=stitched_dur,
        shots=shot_records,
        master_seam_report=master_report,
    )
    manifest_path = os.path.join(abs_out_dir, "run_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fp:
        fp.write(manifest.model_dump_json(indent=2))

    print(f"[Completed] Stitched Master: {stitched_path} ({stitched_dur}s) | Manifest: {manifest_path}")
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
    any_accepted = False
    n_shots = len(manifest.shots)

    for k, trigger_reason in candidates:
        rec = manifest.shots[k]
        shot_spec = scene_spec.shots[k] if k < len(scene_spec.shots) else StoryboardEntrySpec(
            scene_number=rec.shot_index,
            description=rec.prompt,
            evaluation_criteria=rec.evaluation_criteria,
            spoken_dialogue=rec.spoken_dialogue,
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
            start_prompt = scene_spec.opening_keyframe_prompt or (
                f"Cinematic 16:9 opening film still for: {shot_spec.description}. "
                "Keep exact spokesperson face, champagne-ivory satin blazer, and amber serum dropper bottle "
                "from the first reference image inside the architectural environment of the second reference image. "
                "Photorealistic natural daylight, zero text overlays, zero white studio backdrop."
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
            end_prompt = scene_spec.closing_keyframe_prompt or (
                f"Cinematic 16:9 closing hero film still for: {shot_spec.description}. "
                "Keep exact spokesperson face, champagne-ivory satin blazer, and amber serum dropper bottle "
                "from the first reference image inside the architectural environment of the second reference image. "
                "Photorealistic lighting, zero text overlays, zero white studio backdrop."
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
            client=active_rater_client,
        )

        interp_dur = min(10, max(3, int(manifest.duration_per_shot_sec)))
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
            rec.prompt = interp_prompt
            rec.attempts_used += 1
            rec.quality_score = interp_score
            rec.verdict = eval_res.get("verdict", "PASSED" if interp_score >= 0.8 else "COMPLETED_INTERP")
            rec.evaluation_report = eval_res
            any_accepted = True

    if any_accepted:
        valid_clips = [r.video_path for r in manifest.shots if r.video_path and os.path.exists(r.video_path)]
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
                    shot_duration_sec=float(manifest.duration_per_shot_sec),
                    original_intent=scene_spec.title or manifest.original_intent,
                    voice_transcript=vo_lines,
                    reference_images_b64=scene_ref_b64s,
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
    resume: bool = False,
    gen_client: Optional[genai.Client] = None,
    rater_client: Optional[genai.Client] = None,
) -> MultiSceneWorkflowManifest:
    """Executes hierarchical multi-scene generation (e.g., 3x30s -> 90s) with AVU scene rating & `<FIRST_FRAME>+<LAST_FRAME>` self-healing."""
    t0 = time.monotonic()
    abs_out_dir = os.path.abspath(output_dir)
    os.makedirs(abs_out_dir, exist_ok=True)

    active_gen_client = gen_client or get_direct_genai_client(timeout_ms=DirectConfig.VIDEO_GEN_TIMEOUT_MS)
    active_rater_client = rater_client or get_direct_genai_client(timeout_ms=DirectConfig.RATER_TIMEOUT_MS)
    sem = asyncio.Semaphore(max(1, max_parallel_scenes))

    async def _run_one_scene(idx: int, sc: SceneSpec) -> SceneManifestRecord:
        async with sem:
            scene_slug = sc.scene_id or f"scene_{idx + 1}"
            scene_dir = os.path.join(abs_out_dir, scene_slug)
            saved_sc_mf = os.path.join(scene_dir, "run_manifest.json")
            top_scene_mp4 = os.path.join(abs_out_dir, f"{scene_slug}_{(len(sc.shots) or 3) * duration}s.mp4")
            if resume and os.path.exists(saved_sc_mf) and os.path.exists(top_scene_mp4):
                sc_manifest = WorkflowManifest.model_validate_json(Path(saved_sc_mf).read_text(encoding="utf-8"))
                print(f"\n=== [{scene_slug}] Resumed completed scene ({sc_manifest.stitched_duration_sec}s) ===")
                return SceneManifestRecord(
                    scene_id=scene_slug,
                    title=sc.title,
                    output_dir=scene_dir,
                    scene_video_path=top_scene_mp4,
                    scene_duration_sec=sc_manifest.stitched_duration_sec,
                    reference_paths=[os.path.abspath(p) for p in sc.reference_paths if os.path.exists(p)],
                    shots=sc_manifest.shots,
                    interpolation_repairs=sc_manifest.interpolation_repairs,
                    scene_seam_report=sc_manifest.master_seam_report,
                )

            scene_vo = " ".join(
                s.spoken_dialogue.strip() for s in sc.shots if s.spoken_dialogue and s.spoken_dialogue.strip()
            ) or None
            scene_prompt = sc.title or (" / ".join(s.description for s in sc.shots))
            print(f"\n=== [{scene_slug}] Starting {len(sc.shots) * duration}s Scene: {sc.title or scene_slug} ===")

            sc_manifest = await run_standalone_pipeline_async(
                prompt=scene_prompt,
                output_dir=scene_dir,
                mode=sc.mode,
                num_shots=len(sc.shots) or 3,
                duration=duration,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                reference_paths=sc.reference_paths or None,
                voice_transcript=scene_vo,
                storyboard_specs=sc.shots or None,
                max_attempts=max_attempts,
                crossfade_seconds=shot_crossfade_seconds,
                resume=resume,
                gen_client=active_gen_client,
                rater_client=active_rater_client,
            )

            sc_manifest = await _repair_scene_shots_with_interpolation(
                scene_spec=sc,
                manifest=sc_manifest,
                quality_threshold=quality_threshold,
                crossfade_seconds=shot_crossfade_seconds,
                gen_client=active_gen_client,
                rater_client=active_rater_client,
            )

            exported_scene_video: Optional[str] = sc_manifest.stitched_video_path
            if sc_manifest.stitched_video_path and os.path.exists(sc_manifest.stitched_video_path):
                top_scene_mp4 = os.path.join(abs_out_dir, f"{scene_slug}_{len(sc_manifest.shots) * duration}s.mp4")
                shutil.copyfile(sc_manifest.stitched_video_path, top_scene_mp4)
                exported_scene_video = top_scene_mp4

            return SceneManifestRecord(
                scene_id=scene_slug,
                title=sc.title,
                output_dir=scene_dir,
                scene_video_path=exported_scene_video,
                scene_duration_sec=sc_manifest.stitched_duration_sec,
                reference_paths=[os.path.abspath(p) for p in sc.reference_paths if os.path.exists(p)],
                shots=sc_manifest.shots,
                interpolation_repairs=sc_manifest.interpolation_repairs,
                scene_seam_report=sc_manifest.master_seam_report,
            )

    scene_records = list(await asyncio.gather(*(_run_one_scene(i, s) for i, s in enumerate(scenes))))

    scene_videos = [
        sr.scene_video_path for sr in scene_records if sr.scene_video_path and os.path.exists(sr.scene_video_path)
    ]
    total_shots = sum(len(sr.shots) for sr in scene_records)
    master_video_path: Optional[str] = None
    master_dur: float = 0.0
    master_report: Optional[Dict[str, Any]] = None

    if scene_videos:
        nominal_total_sec = total_shots * duration
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
            master_report = await evaluate_stitched_master_direct(
                stitched_video_path=master_video_path,
                num_shots=len(scene_videos),
                shot_duration_sec=avg_scene_dur,
                original_intent=original_intent or " / ".join(sc.title or sc.scene_id for sc in scenes),
                voice_transcript=full_vo,
                reference_images_b64=hero_ref_b64s,
                client=active_rater_client,
            )

    multi_manifest = MultiSceneWorkflowManifest(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        original_intent=original_intent or " / ".join(sc.title or sc.scene_id for sc in scenes),
        num_scenes=len(scenes),
        total_shots=total_shots,
        duration_per_shot_sec=duration,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        elapsed_sec=round(time.monotonic() - t0, 2),
        output_dir=abs_out_dir,
        master_video_path=master_video_path,
        master_duration_sec=master_dur,
        scenes=scene_records,
        master_seam_report=master_report,
    )
    manifest_path = os.path.join(abs_out_dir, "run_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fp:
        fp.write(multi_manifest.model_dump_json(indent=2))

    print(
        f"\n[Multi-Scene Completed] Master Video: {master_video_path} ({master_dur}s) | "
        f"Manifest: {manifest_path}"
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
        choices=["reference", "i2v_chaining", "video_extend", "hybrid"],
        default="video_extend",
        help="Multi-shot continuity mode.",
    )
    parser.add_argument("--shots", type=int, default=3, help="Number of shots (ignored if --storyboard-json set).")
    parser.add_argument("--duration", type=int, default=10, help="Duration per shot in seconds (3-10 for extend/interp).")
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16"])
    parser.add_argument("--resolution", default="720p", choices=["360p", "720p", "1080p", "4k"])
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)

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
                resume=args.resume,
            )
        )
        print(json.dumps({
            "status": "ok",
            "master_video_path": multi_manifest.master_video_path,
            "master_duration_sec": multi_manifest.master_duration_sec,
            "manifest_path": os.path.join(multi_manifest.output_dir, "run_manifest.json"),
            "scene_scores": [
                {
                    "scene_id": s.scene_id,
                    "shot_scores": [sh.quality_score for sh in s.shots],
                    "repairs": len(s.interpolation_repairs),
                    "scene_seam_score": (s.scene_seam_report or {}).get("score"),
                }
                for s in multi_manifest.scenes
            ],
            "master_score": (multi_manifest.master_seam_report or {}).get("score"),
        }, indent=2))
        return 0

    specs: Optional[List[StoryboardEntrySpec]] = None
    if args.storyboard_json:
        raw_data = json.loads(Path(args.storyboard_json).read_text(encoding="utf-8"))
        specs = [StoryboardEntrySpec.model_validate(item) for item in raw_data]

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
            max_attempts=args.max_attempts,
            max_parallel=args.max_parallel,
            crossfade_seconds=args.crossfade,
        )
    )
    print(json.dumps({
        "status": "ok",
        "stitched_video_path": manifest.stitched_video_path,
        "stitched_duration_sec": manifest.stitched_duration_sec,
        "manifest_path": os.path.join(manifest.output_dir, "run_manifest.json"),
        "shot_scores": [s.quality_score for s in manifest.shots],
        "master_score": (manifest.master_seam_report or {}).get("score"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
