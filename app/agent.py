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
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.genai import types

from app.config import Config, get_genai_client
from app.tools.video_parser import extract_last_frame, extract_keyframes
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.stitcher import stitch_videos
from app.state import PipelineState, VideoShot, StoryboardEntry


MODEL = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.7-flash")
OUTPUT_DIR = os.getenv("VIDGEN_OUTPUT_DIR", "/tmp/vidgen_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


async def generate_video_shot_clip(
    prompt: str,
    shot_index: int = 1,
    input_image_path: Optional[str] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Generates a single video clip for a given shot using Gemini Omni Flash.

    Args:
        prompt: Optimized visual prompt for the shot.
        shot_index: Index number of the shot (e.g. 1, 2, 3).
        input_image_path: Optional path to initial/anchor frame image.
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

    clip_bytes = generate_omni_clip(
        prompt=prompt,
        input_image_b64=input_image_b64,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
        client=client
    )

    clip_name = f"shot_{shot_index}.mp4"
    clip_path = os.path.join(OUTPUT_DIR, clip_name)
    with open(clip_path, "wb") as f:
        f.write(clip_bytes)

    # 1. Register native ADK Artifact for Agent Runtime / Gemini Enterprise
    artifact_saved = False
    if tool_context:
        try:
            part = types.Part.from_bytes(data=clip_bytes, mime_type="video/mp4")
            await tool_context.save_artifact(clip_name, part)
            artifact_saved = True
        except Exception as art_err:
            print(f"[Artifact Save Notice]: {art_err}")

    # 2. Upload to GCS showcase for public HTTPS URL
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

    return {
        "shot_index": shot_index,
        "video_path": clip_path,
        "video_url": gcs_url,
        "artifact_name": clip_name,
        "artifact_exposed": artifact_saved,
        "duration": duration,
        "status": "completed"
    }


def parse_terminal_frame(video_path: str) -> Dict[str, Any]:
    """Extracts the final terminal frame of a video clip for Image-to-Video chaining."""
    shot_name = os.path.splitext(os.path.basename(video_path))[0]
    out_frame_path = os.path.join(OUTPUT_DIR, f"{shot_name}_last_frame.png")
    frame_b64 = extract_last_frame(video_path, output_image_path=out_frame_path)
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

    # 1. Register native ADK Artifact for Agent Runtime / Gemini Enterprise
    artifact_saved = False
    if tool_context and os.path.exists(stitched_path):
        try:
            with open(stitched_path, "rb") as vf:
                stitched_bytes = vf.read()
            part = types.Part.from_bytes(data=stitched_bytes, mime_type="video/mp4")
            await tool_context.save_artifact(os.path.basename(stitched_path), part)
            artifact_saved = True
        except Exception as art_err:
            print(f"[Artifact Save Notice]: {art_err}")

    # 2. Upload to GCS showcase for public HTTPS URL
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
        if tool_context:
            try:
                with open(result_state.stitched_video_path, "rb") as vf:
                    stitched_bytes = vf.read()
                part = types.Part.from_bytes(data=stitched_bytes, mime_type="video/mp4")
                await tool_context.save_artifact(filename, part)
                artifact_saved = True
            except Exception as art_err:
                print(f"[Artifact Save Notice]: {art_err}")

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


screenwriter_agent = Agent(
    name="ScreenwriterAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert cinematic screenwriter for short-form AI generative media. "
        "When given a video concept or narrative prompt, break it down into a structured multi-scene screenplay. "
        "Detail the narrative arc, visual motifs, camera motion, and character progression for each scene. "
        "Output the complete screenplay clearly formatted with scene headings (e.g. SCENE 1: ESTABLISHING, SCENE 2: ACTION, SCENE 3: RESOLUTION)."
    ),
    description="Expands high-level video prompts into multi-scene cinematic screenplays."
)

storyboarder_agent = Agent(
    name="StoryboarderAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert AI video storyboarder and prompt engineer. "
        "Convert screenplays into structured shot specifications. "
        "For each shot, specify: shot_index, scene description, camera angle (e.g. wide tracking, close-up), "
        "character actions, and specific quality evaluation criteria (e.g. subject consistency, lighting continuity)."
    ),
    description="Converts screenplays into structured shot specifications and visual prompts."
)

prompt_optimizer_agent = Agent(
    name="PromptOptimizerAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert generative video prompt optimizer specialized in Gemini Omni Flash (`gemini-omni-flash-preview`). "
        "Given a shot description, enhance it with vivid lighting, motion descriptors, camera direction, and style cues. "
        "STRICT SINGLE-SHOT RULE: Enforce a single continuous take without cuts, transitions, or edits. "
        "STRICT DIALOGUE RULE: If spoken dialogue is provided, ensure exact spoken words are preserved without filler."
    ),
    description="Optimizes visual shot descriptions for Gemini Omni Flash video generation."
)

health_checker_agent = Agent(
    name="HealthCheckerAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are a content safety, policy, and guardrail evaluator. "
        "Inspect candidate prompts to ensure compliance with content safety policies, non-violence, and structural requirements. "
        "Return an audit confirmation (e.g. APPROVED or REJECTED with reason)."
    ),
    description="Audits prompts for safety compliance and content guardrails."
)

quality_rater_agent = Agent(
    name="QualityRaterAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an AI media quality evaluator. "
        "Assess video clip quality across: 1) Subject Identity Consistency, 2) Motion Smoothness, 3) Prompt Adherence, 4) Temporal Asset Persistence. "
        "Provide a numerical quality rating between 0.0 and 1.0, a concise verdict (PASSED / RETRY), and actionable feedback."
    ),
    description="Evaluates video clip quality and provides rubric scores."
)

root_agent = Agent(
    name="vidgen_orchestrator",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the Master Pipeline Orchestrator for Multi-Agent Generative Video (`vidgen-omni`).\n"
        "You coordinate a specialized team of AI sub-agents to produce high-fidelity multi-shot generative videos.\n\n"
        "When the user requests to create or generate a multi-shot video:\n"
        "1. STEP 1 - SCREENWRITING: Delegate to `ScreenwriterAgent` to expand the narrative concept into a structured screenplay.\n"
        "2. STEP 2 - STORYBOARDING: Delegate to `StoryboarderAgent` to convert the screenplay into structured shot specifications.\n"
        "3. STEP 3 - PRODUCTION FOR EACH SHOT:\n"
        "   a. Delegate to `PromptOptimizerAgent` to optimize the visual prompt for Gemini Omni Flash.\n"
        "   b. Delegate to `HealthCheckerAgent` to verify safety and policy compliance.\n"
        "   c. Invoke `generate_video_shot_clip` to generate the clip for this shot.\n"
        "   d. Delegate to `QualityRaterAgent` to inspect and rate the generated clip.\n"
        "   e. If Image-to-Video chaining, invoke `parse_terminal_frame` to extract the terminal frame for the next shot.\n"
        "4. STEP 4 - STITCHING: Invoke `concatenate_video_clips` to merge all shot clips into the final video.\n"
        "5. STEP 5 - DELIVERY:\n"
        "   Present the final video summary to the user with full media accessibility.\n"
        "   MANDATORY DELIVERY FORMATTING RULES:\n"
        "   - ALWAYS provide a prominent clickable markdown link to the final video using its `video_url`: `[▶️ Click here to watch / download the final video]({video_url})`\n"
        "   - ALWAYS embed an HTML5 video player tag so users can watch directly inside chat: `<video controls width=\"100%\" src=\"{video_url}\"></video>`\n"
        "   - Mention that the video file is also exposed as an attached ADK session artifact (`{artifact_name}`).\n"
        "   - List each generated shot with its prompt, duration, individual clip link (`[Shot Clip]({video_url})`), and quality score.\n\n"
        "Note: You may also invoke `generate_multi_shot_video` if an all-in-one automated batch execution is explicitly requested."
    ),
    tools=[
        generate_video_shot_clip,
        parse_terminal_frame,
        concatenate_video_clips,
        generate_multi_shot_video,
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
