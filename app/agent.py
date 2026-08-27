# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time
from typing import Dict, Any, Optional, List

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext, AgentTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from app.config import Config, get_genai_client
from app.tools.video_parser import extract_first_frame, extract_last_frame, extract_keyframes
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.stitcher import stitch_videos
from app.state import PipelineState, VideoShot, StoryboardEntry


MODEL = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.7-flash")
OUTPUT_DIR = os.getenv("VIDGEN_OUTPUT_DIR", "/tmp/vidgen_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


async def init_session_state(callback_context: CallbackContext) -> None:
    """Initializes default pipeline state, user preferences, and app metrics on session start."""
    state = callback_context.state
    if "pipeline_stage" not in state:
        state["pipeline_stage"] = "pre_production"
    if "shots" not in state:
        state["shots"] = {}
    if "user:directing_mode" not in state:
        state["user:directing_mode"] = "interactive"
    if "user:preferred_aspect_ratio" not in state:
        state["user:preferred_aspect_ratio"] = "16:9"
    if "user:preferred_resolution" not in state:
        state["user:preferred_resolution"] = "720p"
    if "user:default_mode" not in state:
        state["user:default_mode"] = "i2v_chaining"
    if "user:cinematic_style" not in state:
        state["user:cinematic_style"] = "cinematic 16:9, volumetric lighting, rich color palette, natural motion"
    if "user:character_bible" not in state:
        state["user:character_bible"] = {}
    if "user:total_videos_created" not in state:
        state["user:total_videos_created"] = 0
    if "user:total_shots_generated" not in state:
        state["user:total_shots_generated"] = 0
    if "app:total_videos_rendered" not in state:
        state["app:total_videos_rendered"] = 0
    if "app:total_shots_generated" not in state:
        state["app:total_shots_generated"] = 0


async def sync_session_to_memory(callback_context: CallbackContext) -> None:
    """Persists session events, character lore, and directorial preferences to ADK MemoryBank."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as mem_err:
        print(f"[Memory Sync Notice]: {mem_err}")



async def generate_video_shot_clip(
    prompt: str,
    shot_index: int = 1,
    input_image_path: Optional[str] = None,
    end_image_path: Optional[str] = None,
    reference_image_path: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Generates a single video clip for a given shot using Gemini Omni Flash.

    Args:
        prompt: Optimized visual prompt for the shot.
        shot_index: Index number of the shot (e.g. 1, 2, 3).
        input_image_path: Optional path to starting/anchor frame image (e.g. last frame of shot k-1).
        end_image_path: Optional path to ending/anchor frame image (e.g. first frame of shot k+1).
        reference_image_path: Optional path to canonical character reference image for cross-shot identity locking.
        aspect_ratio: Video aspect ratio ('16:9' or '9:16').
        resolution: Video resolution ('720p' or '1080p').
        duration: Clip duration in seconds (default 10).
        tool_context: Optional ADK tool execution context for artifact registration.

    Returns:
        Dictionary containing shot index, generated video file path, public video URL, artifact info, and status.
    """
    import base64
    client = get_genai_client()
    input_image_b64 = None
    if input_image_path and os.path.exists(input_image_path):
        with open(input_image_path, "rb") as img_f:
            input_image_b64 = base64.b64encode(img_f.read()).decode("utf-8")

    end_image_b64 = None
    if end_image_path and os.path.exists(end_image_path):
        with open(end_image_path, "rb") as end_f:
            end_image_b64 = base64.b64encode(end_f.read()).decode("utf-8")

    # Canonical character reference for cross-shot facial and clothing locking
    ref_img_path = reference_image_path
    if not ref_img_path and tool_context and "canonical_character_reference" in tool_context.state:
        ref_img_path = tool_context.state.get("canonical_character_reference")

    ref_imgs_b64 = None
    if ref_img_path and os.path.exists(ref_img_path):
        with open(ref_img_path, "rb") as ref_f:
            ref_imgs_b64 = [base64.b64encode(ref_f.read()).decode("utf-8")]

    clip_bytes = generate_omni_clip(
        prompt=prompt,
        input_image_b64=input_image_b64,
        end_image_b64=end_image_b64,
        reference_images_b64=ref_imgs_b64,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
        client=client
    )

    clip_name = f"shot_{shot_index}.mp4"
    clip_path = os.path.join(OUTPUT_DIR, clip_name)
    with open(clip_path, "wb") as f:
        f.write(clip_bytes)

    # Automatically extract canonical reference frame from Shot 1 if not already established
    if shot_index == 1:
        try:
            anchor_frame = extract_first_frame(clip_path)
            if anchor_frame and tool_context:
                tool_context.state["canonical_character_reference"] = anchor_frame
                if "user:character_bible" in tool_context.state and isinstance(tool_context.state["user:character_bible"], dict):
                    tool_context.state["user:character_bible"]["main_character_frame"] = anchor_frame
        except Exception as anchor_err:
            print(f"[Anchor Extraction Notice]: {anchor_err}")

    # 1. Upload to GCS showcase for public HTTPS URL
    gcs_url = None
    try:
        from app.tools.gcs_storage import get_storage_client, get_default_bucket_name, ensure_gcs_bucket, upload_file_to_gcs
        gcs_client = get_storage_client()
        bucket_name = get_default_bucket_name()
        if gcs_client:
            bucket = ensure_gcs_bucket(gcs_client, bucket_name)
            if bucket:
                gcs_url = upload_file_to_gcs(bucket, clip_path, f"showcase/shots/{clip_name}")
    except Exception:
        pass
    if not gcs_url:
        bucket_name = os.getenv("GCS_SHOWCASE_BUCKET", "universal-trail-492014-n5-vidgen-showcase")
        gcs_url = f"https://storage.googleapis.com/{bucket_name}/showcase/shots/{clip_name}"

    # 2. Register native lightweight URI ADK Artifact and update state
    artifact_saved = False
    if tool_context:
        try:
            part = types.Part.from_uri(file_uri=gcs_url, mime_type="video/mp4")
            await tool_context.save_artifact(clip_name, part)
            artifact_saved = True
        except Exception as art_err:
            print(f"[Artifact Save Notice]: {art_err}")

        # --- STATE UPDATES (Session, Temp, User, App Scopes) ---
        shots_state = dict(tool_context.state.get("shots", {}))
        shots_state[str(shot_index)] = {
            "shot_index": shot_index,
            "video_path": clip_path,
            "video_url": gcs_url,
            "artifact_name": clip_name,
            "duration": duration,
            "status": "completed"
        }
        tool_context.state["shots"] = shots_state
        tool_context.state["pipeline_stage"] = "production"

        # Turn/Temp scope
        tool_context.state["temp:latest_rendered_shot"] = clip_path
        tool_context.state["temp:latest_shot_index"] = shot_index

        # App & User metrics
        tool_context.state["app:total_shots_generated"] = tool_context.state.get("app:total_shots_generated", 0) + 1
        tool_context.state["user:total_shots_generated"] = tool_context.state.get("user:total_shots_generated", 0) + 1

    return {
        "shot_index": shot_index,
        "video_path": clip_path,
        "video_url": gcs_url,
        "artifact_name": clip_name,
        "artifact_exposed": artifact_saved,
        "duration": duration,
        "status": "completed"
    }


def parse_initial_frame(video_path: str, tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """Extracts the initial (first) frame of a video clip for dual-anchor visual continuity."""
    shot_name = os.path.splitext(os.path.basename(video_path))[0]
    out_frame_path = os.path.join(OUTPUT_DIR, f"{shot_name}_first_frame.png")
    frame_b64 = extract_first_frame(video_path, output_image_path=out_frame_path)
    if tool_context:
        tool_context.state["temp:first_frame_anchor"] = out_frame_path
    return {
        "video_path": video_path,
        "frame_image_path": out_frame_path,
        "has_frame": bool(frame_b64)
    }


def parse_terminal_frame(video_path: str, tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """Extracts the final terminal frame of a video clip for Image-to-Video chaining."""
    shot_name = os.path.splitext(os.path.basename(video_path))[0]
    out_frame_path = os.path.join(OUTPUT_DIR, f"{shot_name}_last_frame.png")
    frame_b64 = extract_last_frame(video_path, output_image_path=out_frame_path)
    if tool_context:
        tool_context.state["temp:last_frame_anchor"] = out_frame_path
    return {
        "video_path": video_path,
        "frame_image_path": out_frame_path,
        "has_frame": bool(frame_b64)
    }


async def concatenate_video_clips(
    video_paths: List[str],
    output_filename: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Concatenates video clips into a single continuous video with FFMPEG stream copy and registers artifacts.

    Args:
        video_paths: List of local video clip file paths in sequence.
        output_filename: Optional custom output filename.
        tool_context: Optional ADK tool execution context for artifact registration.

    Returns:
        Dictionary containing stitched video path, public video URL, artifact details, and status.
    """
    valid_clips = [p for p in video_paths if os.path.exists(p) and os.path.getsize(p) > 0]
    if not valid_clips:
        return {"error": "No valid video clips found to concatenate", "status": "failed"}

    target_name = output_filename or f"output_stitched_{len(valid_clips)*10}s.mp4"
    out_path = os.path.join(OUTPUT_DIR, target_name)
    stitched_path = stitch_videos(valid_clips, out_path)

    # 1. Upload to GCS showcase for public HTTPS URL
    run_id = f"vidgen_{int(time.time())}"
    gcs_url = None
    try:
        from app.tools.gcs_storage import get_storage_client, get_default_bucket_name, ensure_gcs_bucket, upload_file_to_gcs
        gcs_client = get_storage_client()
        bucket_name = get_default_bucket_name()
        if gcs_client:
            bucket = ensure_gcs_bucket(gcs_client, bucket_name)
            if bucket:
                gcs_url = upload_file_to_gcs(bucket, stitched_path, f"showcase/{run_id}/{os.path.basename(stitched_path)}")
    except Exception:
        pass
    if not gcs_url:
        bucket_name = os.getenv("GCS_SHOWCASE_BUCKET", "universal-trail-492014-n5-vidgen-showcase")
        gcs_url = f"https://storage.googleapis.com/{bucket_name}/showcase/{run_id}/{os.path.basename(stitched_path)}"

    # 2. Register native lightweight URI ADK Artifact for Agent Runtime / Gemini Enterprise
    artifact_saved = False
    if tool_context and os.path.exists(stitched_path):
        try:
            part = types.Part.from_uri(file_uri=gcs_url, mime_type="video/mp4")
            await tool_context.save_artifact(os.path.basename(stitched_path), part)
            artifact_saved = True
        except Exception as art_err:
            print(f"[Artifact Save Notice]: {art_err}")

        # --- STATE UPDATES (Session, User, App Scopes) ---
        tool_context.state["stitched_video_path"] = stitched_path
        tool_context.state["stitched_video_url"] = gcs_url
        tool_context.state["pipeline_stage"] = "post_production"
        tool_context.state["app:total_videos_rendered"] = tool_context.state.get("app:total_videos_rendered", 0) + 1
        tool_context.state["user:total_videos_created"] = tool_context.state.get("user:total_videos_created", 0) + 1

    return {
        "stitched_video_path": stitched_path,
        "video_url": gcs_url,
        "artifact_name": os.path.basename(stitched_path),
        "artifact_exposed": artifact_saved,
        "clips_count": len(valid_clips),
        "total_duration": f"{len(valid_clips)*10}s",
        "status": "success"
    }


async def generate_multi_shot_video(
    prompt: str,
    num_shots: int = 3,
    mode: str = "i2v_chaining",
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """All-in-one multi-shot video generation pipeline.

    Args:
        prompt: High-level narrative description of the video to create.
        num_shots: Number of sequential shots (between 1 and 10).
        mode: Video generation mode ('i2v_chaining' or 'reference').
        aspect_ratio: Output video aspect ratio ('16:9' or '9:16').
        resolution: Output video resolution ('720p' or '1080p').
        duration: Duration of each shot in seconds (default 10).
        tool_context: Optional ADK tool execution context for artifact registration.

    Returns:
        Dictionary containing the generated video path, public video URL, artifact info, shot summaries, and execution metrics.
    """
    from app.agents.pipeline import run_pipeline_async
    state = PipelineState(
        original_intent=prompt,
        num_shots=num_shots,
        mode=mode if mode in ["reference", "i2v_chaining"] else "i2v_chaining",
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration
    )
    result_state = await run_pipeline_async(state)

    artifact_saved = False
    gcs_url = None
    if result_state.stitched_video_path and os.path.exists(result_state.stitched_video_path):
        filename = os.path.basename(result_state.stitched_video_path)
        run_id = f"vidgen_{int(time.time())}"
        try:
            from app.tools.gcs_storage import get_storage_client, get_default_bucket_name, ensure_gcs_bucket, upload_file_to_gcs
            gcs_client = get_storage_client()
            bucket_name = get_default_bucket_name()
            if gcs_client:
                bucket = ensure_gcs_bucket(gcs_client, bucket_name)
                if bucket:
                    gcs_url = upload_file_to_gcs(bucket, result_state.stitched_video_path, f"showcase/{run_id}/{filename}")
        except Exception:
            pass
        if not gcs_url:
            bucket_name = os.getenv("GCS_SHOWCASE_BUCKET", "universal-trail-492014-n5-vidgen-showcase")
            gcs_url = f"https://storage.googleapis.com/{bucket_name}/showcase/{run_id}/{filename}"

        if tool_context:
            try:
                part = types.Part.from_uri(file_uri=gcs_url, mime_type="video/mp4")
                await tool_context.save_artifact(filename, part)
                artifact_saved = True
            except Exception as art_err:
                print(f"[Artifact Save Notice]: {art_err}")

    return {
        "status": "success",
        "stitched_video_path": result_state.stitched_video_path,
        "video_url": gcs_url,
        "artifact_name": os.path.basename(result_state.stitched_video_path) if result_state.stitched_video_path else None,
        "artifact_exposed": artifact_saved,
        "num_shots": len(result_state.shots),
        "quality_rating": result_state.quality_rating,
        "attempts": result_state.attempt_counter,
    }


UNIFIED_BASE_SYSTEM_INSTRUCTION = (
    "You are an expert AI agent in the VidGen-Omni Multi-Agent Generative Video Production System.\n"
    "System Architecture & Pipeline Roles:\n"
    "- ScreenwriterAgent: Expands narrative ideas into structured multi-scene screenplays with clear scene headings, maintaining visual continuity with recurrent universe lore from `{user:character_bible}` and `{user:cinematic_style}`.\n"
    "- StoryboarderAgent: Converts screenplays into shot breakdown tables with camera angles, visual descriptions, character actions, and rubrics.\n"
    "- PromptOptimizerAgent: Enhances visual prompts for Gemini Omni Flash (`gemini-omni-flash-preview`), enforcing single-shot continuous motion without cuts, incorporating previous QualityRater feedback on retries/modifications, and preserving dialogue.\n"
    "- HealthCheckerAgent: Audits candidate prompts for content safety, policy compliance, and visual feasibility.\n"
    "- generate_video_shot_clip (Tool): Renders a video clip from prompt with optional start and end frame anchors (`input_image_path`, `end_image_path`).\n"
    "- parse_initial_frame (Tool): Extracts the initial (first) frame of a video clip for dual-anchor visual continuity.\n"
    "- parse_terminal_frame (Tool): Extracts the terminal (last) frame of a video clip for Image-to-Video chaining.\n"
    "- concatenate_video_clips (Tool): Stitches individual video clips into the final video file.\n"
    "- PreloadMemoryTool (Tool): Automatically retrieves long-term directorial style preferences, recurring character lore, and project history from ADK MemoryBank.\n"
    "- QualityRaterAgent: Audits individual video clips and the complete final stitched video using multimodal vision (`evaluate_video_clip_quality` tool).\n"
    "- vidgen_orchestrator: Master pipeline coordinator that manages sub-agents, orchestrates interactive directing checkpoints, manages dual-anchor shot modifications, and delivers video links and player to the user.\n\n"
    "CRITICAL VISIBILITY REQUIREMENT: Every agent in this system MUST output its complete, formatted markdown report directly in the chat stream so the user sees all progress in real-time."
)


screenwriter_agent = Agent(
    name="ScreenwriterAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        f"{UNIFIED_BASE_SYSTEM_INSTRUCTION}\n\n"
        "YOUR ACTIVE ROLE: ScreenwriterAgent\n"
        "TASK: When given a video concept or narrative prompt, break it down into a structured multi-scene screenplay.\n"
        "Detail the narrative arc, visual motifs, camera motion, and character progression for each scene.\n"
        "CRITICAL VISIBILITY RULE: You MUST output the complete, beautifully formatted screenplay draft in your response text with scene headings (e.g. `### 🎬 SCENE 1: ESTABLISHING`, `### 🎬 SCENE 2: ACTION`, `### 🎬 SCENE 3: RESOLUTION`) so the user can read the screenplay in the chat.\n"
        "After presenting the complete screenplay to the user, transfer control back to `vidgen_orchestrator` using `transfer_to_agent(agent_name='vidgen_orchestrator')`."
    ),
    description="Expands high-level video prompts into multi-scene cinematic screenplays.",
    output_key="screenplay",
    disallow_transfer_to_peers=True,
    disallow_transfer_to_parent=False,
)

storyboarder_agent = Agent(
    name="StoryboarderAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        f"{UNIFIED_BASE_SYSTEM_INSTRUCTION}\n\n"
        "YOUR ACTIVE ROLE: StoryboarderAgent\n"
        "TASK: Convert screenplays into structured shot specifications.\n"
        "CRITICAL VISIBILITY RULE: You MUST output a structured storyboard breakdown table in your response text for the user, detailing:\n"
        "| Shot # | Camera Angle | Visual Description | Character Action | Quality Rubric Criteria |\n"
        "After presenting the complete storyboard table to the user, transfer control back to `vidgen_orchestrator` using `transfer_to_agent(agent_name='vidgen_orchestrator')`."
    ),
    description="Converts screenplays into structured shot specifications and visual prompts.",
    output_key="storyboard",
    disallow_transfer_to_peers=True,
    disallow_transfer_to_parent=False,
)

prompt_optimizer_agent = Agent(
    name="PromptOptimizerAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        f"{UNIFIED_BASE_SYSTEM_INSTRUCTION}\n\n"
        "YOUR ACTIVE ROLE: PromptOptimizerAgent\n"
        "TASK: Given a shot description (and optional previous feedback/critique from QualityRaterAgent or user modification instructions), enhance it with vivid lighting, motion descriptors, camera direction, and style cues for Gemini Omni Flash.\n"
        "FEEDBACK-DRIVEN OPTIMIZATION: When previous QualityRater feedback or user modification notes are provided, you MUST directly address and fix the identified flaws (e.g. lighting stability, character movement speed, object consistency).\n"
        "STRICT SINGLE-SHOT RULE: Enforce a single continuous take without cuts, transitions, or edits.\n"
        "STRICT DIALOGUE RULE: If spoken dialogue is provided, ensure exact spoken words are preserved without filler.\n"
        "CRITICAL VISIBILITY RULE: You MUST output your prompt optimization report in your response text for the user, highlighting:\n"
        "- **Shot #**: index\n"
        "- **Optimized Visual Prompt**: the enhanced cinematic prompt\n"
        "- **Cinematic Enhancements**: camera motion, volumetric lighting, texture/style descriptors\n"
        "- **Feedback Addressed**: how previous critique/user instructions were incorporated\n"
        "After presenting the optimization details to the user, transfer control back to `vidgen_orchestrator` using `transfer_to_agent(agent_name='vidgen_orchestrator')`."
    ),
    description="Optimizes visual shot descriptions for Gemini Omni Flash video generation.",
    disallow_transfer_to_peers=True,
    disallow_transfer_to_parent=False,
)

health_checker_agent = Agent(
    name="HealthCheckerAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        f"{UNIFIED_BASE_SYSTEM_INSTRUCTION}\n\n"
        "YOUR ACTIVE ROLE: HealthCheckerAgent\n"
        "TASK: Inspect candidate prompts to ensure compliance with content safety policies, non-violence, and structural requirements.\n"
        "CRITICAL VISIBILITY RULE: You MUST output your safety audit confirmation in your response text for the user, stating:\n"
        "- **Safety Verdict**: `APPROVED` (or `REJECTED`)\n"
        "- **Checks Verified**: Safety Filters, Single-Shot Continuity, Motion Feasibility\n"
        "After presenting your audit report to the user, transfer control back to `vidgen_orchestrator` using `transfer_to_agent(agent_name='vidgen_orchestrator')` so the video clip can be generated with the `generate_video_shot_clip` tool."
    ),
    description="Audits candidate prompts for safety and policy compliance.",
    disallow_transfer_to_peers=True,
    disallow_transfer_to_parent=False,
)

async def evaluate_video_clip_quality(
    video_path: str,
    prompt: str,
    evaluation_criteria: Optional[str] = None,
    reference_image_path: Optional[str] = None,
    tool_context: Optional[ToolContext] = None,
) -> dict:
    """Inspects and audits an actual MP4 video clip file using Gemini multimodal vision.

    Args:
        video_path: Local filesystem path or public URL of the generated .mp4 video clip.
        prompt: The visual prompt describing what should happen in the shot.
        evaluation_criteria: Specific quality criteria or character/lighting requirements.
        reference_image_path: Optional path to canonical character reference image for cross-shot continuity audit.
        tool_context: Optional ADK tool execution context for state tracking.

    Returns:
        Structured evaluation result with numerical score (0.0 to 1.0), rubric breakdown, verdict (PASSED/RETRY), and detailed perceptual critique.
    """
    from app.config import get_genai_client
    from google.genai import types
    import urllib.request
    import json
    import re

    video_bytes = None
    candidates = [
        video_path,
        os.path.join(OUTPUT_DIR, os.path.basename(video_path)),
        os.path.join("/tmp/vidgen_output", os.path.basename(video_path)),
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.path.isfile(c):
            try:
                with open(c, "rb") as fp:
                    video_bytes = fp.read()
                break
            except Exception:
                pass

    if not video_bytes and video_path.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(video_path, timeout=15) as resp:
                video_bytes = resp.read()
        except Exception as e:
            print(f"[Video Download Error]: {e}")

    if not video_bytes:
        res = {
            "score": 0.0,
            "verdict": "RETRY",
            "rubric_breakdown": {
                "subject_identity_consistency": 0.0,
                "motion_smoothness": 0.0,
                "prompt_adherence": 0.0,
                "temporal_asset_persistence": 0.0
            },
            "feedback": f"Could not open video file at {video_path} for visual inspection.",
            "criteria_evaluated": evaluation_criteria,
        }
        if tool_context:
            tool_context.state["quality_rating"] = 0.0
            tool_context.state["quality_verdict"] = "RETRY"
            tool_context.state["rater_feedback"] = res["feedback"]
        return res

    # Resolve canonical reference image for cross-shot continuity checking
    ref_img_path = reference_image_path
    if not ref_img_path and tool_context and "canonical_character_reference" in tool_context.state:
        ref_img_path = tool_context.state.get("canonical_character_reference")

    ref_img_bytes = None
    if ref_img_path and os.path.exists(ref_img_path):
        try:
            with open(ref_img_path, "rb") as ref_f:
                ref_img_bytes = ref_f.read()
        except Exception as ref_read_err:
            print(f"[Ref Image Read Notice]: {ref_read_err}")

    client = get_genai_client()
    criteria_str = f"Specific Scene Goal: {evaluation_criteria}" if evaluation_criteria else "Standard quality audit."
    
    continuity_rubric = ""
    if ref_img_bytes:
        continuity_rubric = (
            "CRITICAL CROSS-SHOT CONTINUITY CHECK (REFERENCE IMAGE ATTACHED):\n"
            "- Facial Identity: Compare the character in the video to the attached Reference Image. Facial features, hair color, facial hair, skin tone, and character ethnicity MUST match the reference image.\n"
            "- Wardrobe & Colors: Clothing style, jacket color, shirt, pants, and accessories MUST be consistent with the reference image.\n"
            "- MANDATORY PENALTY: If the character's face morphs into a different person, hair changes color, or clothing changes color/style unexpectedly, assign score < 0.60, verdict 'RETRY', and explicitly detail the continuity discrepancy in 'feedback'.\n\n"
        )

    eval_prompt = (
        "You are the QualityRaterAgent evaluating an actual AI-generated MP4 video clip.\n"
        f"Target Shot Prompt: '{prompt}'\n"
        f"{criteria_str}\n\n"
        f"{continuity_rubric}"
        "Inspect the provided video clip across 4 key evaluation rubrics:\n"
        "1. Subject Identity Consistency (character/object consistency throughout the shot and against reference image)\n"
        "2. Motion Smoothness & Dynamics (natural pacing, no jitter or abrupt morphs)\n"
        "3. Visual Prompt Adherence (visual elements match the target prompt)\n"
        "4. Temporal Asset Persistence (lighting, clothing, background stability)\n\n"
        "Return ONLY a JSON object with keys:\n"
        "- score: float between 0.0 and 1.0 (overall quality score)\n"
        "- verdict: string ('PASSED' if score >= 0.8 else 'RETRY')\n"
        "- rubric_breakdown: dict with float scores for subject_identity_consistency, motion_smoothness, prompt_adherence, temporal_asset_persistence\n"
        "- feedback: detailed paragraph describing specific visual observations from the video"
    )

    contents = [eval_prompt]
    if ref_img_bytes:
        mime = "image/jpeg" if ref_img_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
        contents.append(types.Part.from_bytes(data=ref_img_bytes, mime_type=mime))
    contents.append(types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"))

    result_data = None
    try:
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.7-flash",
            contents=contents
        )
        if resp and resp.text:
            text = resp.text
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else text
            data = json.loads(clean_text)
            result_data = {
                "score": float(data.get("score", 0.0)),
                "verdict": str(data.get("verdict", "RETRY")).upper(),
                "rubric_breakdown": data.get("rubric_breakdown", {}),
                "feedback": data.get("feedback", "Video inspected."),
                "criteria_evaluated": evaluation_criteria,
            }
    except Exception as e:
        print(f"[Multimodal Video Evaluation Notice]: {e}")

    if not result_data:
        result_data = {
            "score": 0.0,
            "verdict": "RETRY",
            "rubric_breakdown": {
                "subject_identity_consistency": 0.0,
                "motion_smoothness": 0.0,
                "prompt_adherence": 0.0,
                "temporal_asset_persistence": 0.0
            },
            "feedback": "Multimodal video analysis failed to parse. Retry required.",
            "criteria_evaluated": evaluation_criteria,
        }

    if tool_context:
        tool_context.state["quality_rating"] = result_data["score"]
        tool_context.state["quality_verdict"] = result_data["verdict"]
        tool_context.state["rater_feedback"] = result_data["feedback"]
        tool_context.state["rubric_breakdown"] = result_data["rubric_breakdown"]

    return result_data


quality_rater_agent = Agent(
    name="QualityRaterAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        f"{UNIFIED_BASE_SYSTEM_INSTRUCTION}\n\n"
        "YOUR ACTIVE ROLE: QualityRaterAgent\n"
        "TASK: Evaluate the quality of a generated video clip or the complete final stitched video at `video_path` across Subject Identity Consistency, Motion Smoothness, Prompt Adherence, and Temporal Asset Persistence.\n"
        "CRITICAL TOOL INSTRUCTION: Whenever you are asked to evaluate a video clip or stitched video, you MUST invoke the `evaluate_video_clip_quality(video_path=..., prompt=..., evaluation_criteria=...)` tool to inspect and audit the actual MP4 video file using multimodal vision.\n"
        "FOR FINAL STITCHED VIDEO: When auditing the full stitched video, evaluate overall narrative pacing, cross-shot visual continuity, color grading stability, and audio flow.\n"
        "CRITICAL VISIBILITY RULE: You MUST output your full quality evaluation report in your response text for the user, including:\n"
        "- **Quality Score**: X.XX / 1.0\n"
        "- **Verdict**: `PASSED` (if score >= 0.8) or `RETRY`\n"
        "- **Rubric Breakdown**: Subject Consistency, Motion Smoothness, Prompt Adherence, Temporal Persistence\n"
        "- **Feedback / Critique & Suggestions**: specific visual observations and actionable suggestions for prompt refinement\n"
        "After presenting your quality rating report to the user, transfer control back to `vidgen_orchestrator` using `transfer_to_agent(agent_name='vidgen_orchestrator')`."
    ),
    description="Evaluates video clip and final stitched video quality by inspecting actual video files using multimodal vision.",
    tools=[evaluate_video_clip_quality],
    disallow_transfer_to_peers=True,
    disallow_transfer_to_parent=False,
)

root_agent = Agent(
    name="vidgen_orchestrator",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        f"{UNIFIED_BASE_SYSTEM_INSTRUCTION}\n\n"
        "YOUR ACTIVE ROLE: vidgen_orchestrator (Master Pipeline Coordinator)\n"
        "You coordinate a specialized team of AI sub-agents to produce high-fidelity multi-shot generative videos.\n\n"
        "=== WORKFLOW A: INITIAL MULTI-SHOT GENERATION ===\n"
        "When the user requests to create or generate a new video, execute the following exact pipeline step-by-step:\n\n"
        "--- PHASE 1: PRE-PRODUCTION & DIRECTING REVIEW ---\n"
        "1. Delegate to `ScreenwriterAgent` to expand the narrative concept into a structured screenplay (recalling persistent lore from `{user:character_bible}` and `{user:cinematic_style}`).\n"
        "2. Delegate to `StoryboarderAgent` to convert the screenplay into structured shot specifications (scenes 1 to N).\n"
        "3. INTERACTIVE DIRECTING CHECKPOINT:\n"
        "   - If `user:directing_mode == 'interactive'` (default) and the user has not explicitly commanded immediate batch execution:\n"
        "     Present the full storyboard table and ask the user for confirmation:\n"
        "     '🎬 **Storyboard Ready for Director's Review**:\n"
        "      Review the shot breakdown table above. Reply **Approve** (or **Proceed**) to begin rendering these shots with Gemini Omni Flash, or reply with any adjustments to camera angles, lighting, or dialogue.'\n"
        "   - Once the user approves or confirms (or if in `autonomous` mode), proceed immediately to Phase 2.\n\n"
        "--- PHASE 2: PRODUCTION LOOP & PER-SHOT DIRECTING REVIEW ---\n"
        "For each shot index `k` from 1 to N:\n"
        "   Step 2.1 - OPTIMIZE: Delegate to `PromptOptimizerAgent` to optimize the visual prompt for Gemini Omni Flash (pass QualityRater feedback if retrying).\n"
        "   Step 2.2 - AUDIT: Delegate to `HealthCheckerAgent` to verify safety and policy compliance.\n"
        "   Step 2.3 - CRITICAL TOOL CALL (RENDER): Invoke tool `generate_video_shot_clip(prompt=..., shot_index=k, input_image_path=..., reference_image_path=...)`.\n"
        "              CRITICAL RULE: You MUST invoke `generate_video_shot_clip` immediately after `HealthCheckerAgent`. NEVER transfer to `QualityRaterAgent` before this tool call has finished and returned `video_path`.\n"
        "   Step 2.4 - RATE & CROSS-SHOT AUDIT: Delegate to `QualityRaterAgent` passing `video_path` and `reference_image_path` to audit face/wardrobe consistency.\n"
        "   Step 2.5 - PER-SHOT INTERACTIVE DIRECTING CHECKPOINT:\n"
        "              - Deliver Shot `k` preview immediately in the chat stream: embed `<video controls width=\"100%\" src=\"https://...\"></video>`, provide clickable link, and display the quality rating score & verdict.\n"
        "              - If `user:directing_mode == 'interactive'` (default) and user did not specify immediate autonomous batch execution:\n"
        "                PAUSE the turn and ask the director for review:\n"
        "                '🎬 **Shot #{k} Ready for Director Review (Score: {score}/1.0)**:\n"
        "                 - Watch the clip above.\n"
        "                 - Reply **Approve** (or **Proceed**) to continue to Shot #{k+1} (or final assembly if last shot).\n"
        "                 - Or reply with custom modification notes to regenerate Shot #{k} using dual-anchor constraints.'\n"
        "              - When user replies 'Approve' / 'Proceed' (or in `autonomous` mode):\n"
        "                If mode is 'i2v_chaining' and k < N, invoke tool `parse_terminal_frame(video_path=...)` to extract anchor frame for shot k+1, then proceed to shot k+1.\n"
        "                If k == N, proceed to Phase 3.\n"
        "              - When user requests modifications on Shot `k`: Trigger Workflow B (Dual-Anchor regeneration) and present the revised shot for approval.\n\n"
        "--- PHASE 3: POST-PRODUCTION & FINAL EVALUATION ---\n"
        "1. STITCH: Invoke tool `concatenate_video_clips(video_paths=[...])` with the final valid clip paths from all shots.\n"
        "2. FINAL QUALITY EVALUATION (CRITICAL STEP): Delegate to `QualityRaterAgent` passing `video_path=stitched_video_path` to evaluate the complete final video across narrative pacing, cross-shot visual continuity, and color grading.\n"
        "3. DELIVER: Present the final summary to the user with full media accessibility:\n"
        "   - ALWAYS provide a prominent clickable markdown link to the final video using the actual video_url returned by the tool: [▶️ Click here to watch / download the final video](https://...)\n"
        "   - ALWAYS embed an HTML5 video player tag so users can watch directly inside chat: <video controls width=\"100%\" src=\"https://...\"></video> (using the actual HTTPS video_url)\n"
        "   - Mention that the video file is also exposed as an attached ADK session artifact file.\n"
        "   - List each generated shot with its prompt, duration, individual clip link, and quality score.\n"
        "   - Display the overall final video quality score and verdict.\n\n"
        "=== WORKFLOW B: SHOT MODIFICATION & REGENERATION (DUAL-ANCHOR I2V) ===\n"
        "When the user requests to modify, revise, or re-generate a specific shot `k` (where 1 <= k <= N):\n"
        "1. OPTIMIZE WITH FEEDBACK: Delegate to `PromptOptimizerAgent` passing the user's modification instructions AND the suggestions/critique from previous `QualityRaterAgent` runs.\n"
        "2. AUDIT: Delegate to `HealthCheckerAgent` to verify safety and policy compliance.\n"
        "3. DUAL-ANCHOR FRAME EXTRACTION:\n"
        "   - First Frame Anchor (Starting Frame): If preceding shot `k-1` exists, invoke tool `parse_terminal_frame(video_path='...shot_{k-1}.mp4')` to extract its last frame as `input_image_path`.\n"
        "   - Last Frame Anchor (Ending Frame): If succeeding shot `k+1` exists, invoke tool `parse_initial_frame(video_path='...shot_{k+1}.mp4')` to extract its first frame as `end_image_path`.\n"
        "   (This dual-anchor constraint guarantees that newly generated shot `k` seamlessly connects to both shot `k-1` and shot `k+1` without breaking narrative and visual flow).\n"
        "4. DUAL-ANCHOR RENDER: Invoke tool `generate_video_shot_clip(prompt=..., shot_index=k, input_image_path=..., end_image_path=..., reference_image_path=...)`.\n"
        "5. RATE: Delegate to `QualityRaterAgent` passing the newly generated `video_path` and `reference_image_path` to audit shot `k`.\n"
        "6. INTERACTIVE REVIEW: Present the revised shot clip with player and rating to the user for approval.\n"
        "7. RE-STITCH (Upon approval): Invoke tool `concatenate_video_clips(video_paths=[...])` with the updated list of shot video paths.\n"
        "8. FINAL EVALUATION: Delegate to `QualityRaterAgent` to audit the newly stitched final video.\n"
        "9. DELIVER: Present the updated final video with clickable link, embedded HTML5 player, updated shot metrics, and final quality rating."
    ),
    before_agent_callback=init_session_state,
    after_agent_callback=sync_session_to_memory,
    tools=[
        PreloadMemoryTool(),
        generate_video_shot_clip,
        parse_initial_frame,
        parse_terminal_frame,
        concatenate_video_clips,
    ],
    sub_agents=[
        screenwriter_agent,
        storyboarder_agent,
        prompt_optimizer_agent,
        health_checker_agent,
        quality_rater_agent,
    ],
)

app = App(
    root_agent=root_agent,
    name="vidgen-omni",
)

