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
from typing import Dict, Any, Optional, List

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.config import Config
from app.tools.video_parser import extract_last_frame, extract_keyframes
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.stitcher import stitch_videos
from app.state import PipelineState, VideoShot, StoryboardEntry


MODEL = os.getenv("ORCHESTRATOR_MODEL", "gemini-3.7-flash")


async def generate_multi_shot_video(
    prompt: str,
    num_shots: int = 3,
    mode: str = "i2v_chaining",
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 10,
) -> Dict[str, Any]:
    """Generates a multi-shot stitched video using the ADK 2.0 multi-agent pipeline.

    Args:
        prompt: High-level narrative description of the video to create.
        num_shots: Number of sequential shots (between 1 and 10).
        mode: Video generation mode ('i2v_chaining' or 'reference').
        aspect_ratio: Output video aspect ratio ('16:9' or '9:16').
        resolution: Output video resolution ('720p' or '1080p').
        duration: Duration of each shot in seconds (default 10).

    Returns:
        Dictionary containing the generated video path, shot summaries, and execution metrics.
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
    return {
        "status": "success",
        "stitched_video_path": result_state.stitched_video_path,
        "num_shots": len(result_state.shots),
        "quality_rating": result_state.quality_rating,
        "attempts": result_state.attempt_counter,
    }


def parse_terminal_frame(video_path: str) -> str:
    """Extracts the final terminal frame of a video clip for Image-to-Video chaining."""
    return extract_last_frame(video_path)


def concatenate_video_clips(video_paths: List[str], output_path: str) -> str:
    """Concatenates video clips into a single continuous video with FFMPEG stream copy."""
    return stitch_videos(video_paths, output_path)


screenwriter_agent = Agent(
    name="ScreenwriterAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert cinematic screenwriter for short-form AI generative media. "
        "Break down user prompts into a structured multi-scene screenplay with visual motifs, camera angles, and character progression."
    ),
    description="Expands high-level video prompts into multi-scene screenplays."
)

storyboarder_agent = Agent(
    name="StoryboarderAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert AI video storyboarder and prompt engineer. "
        "Convert screenplays into structured JSON shot specifications including scene number, description, camera angle, and quality evaluation criteria."
    ),
    description="Converts screenplays into structured shot specifications."
)

prompt_optimizer_agent = Agent(
    name="PromptOptimizerAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are an expert generative video prompt optimizer specialized in Gemini Omni Flash. "
        "Enhance shot descriptions with vivid lighting, motion descriptors, camera direction, and style cues. "
        "STRICT SINGLE-SHOT RULE: Enforce a single continuous take without cuts or edits. "
        "STRICT DIALOGUE RULE: If dialogue is provided, ensure exact spoken words are preserved without filler or truncated speech."
    ),
    description="Optimizes visual shot descriptions for Gemini Omni Flash."
)

health_checker_agent = Agent(
    name="HealthCheckerAgent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are a safety and policy guardrail evaluator. "
        "Inspect candidate prompts to ensure compliance with content safety policies, non-violence, and structural requirements."
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
        "Assess video consistency, character identity preservation, motion smoothness, temporal asset persistence, and adherence to user intent. "
        "Provide a quality score between 0.0 and 1.0 with actionable feedback."
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
        "You are the Master Pipeline Orchestrator for Multi-Agent Generative Video (vidgen-omni). "
        "When the user requests to generate or create a video sequence, extract their narrative intent, desired number of shots, and mode, "
        "then invoke the `generate_multi_shot_video` tool to execute the multi-agent generation pipeline. "
        "Once complete, summarize the final stitched video path, shot details, and quality rating to the user."
    ),
    tools=[
        generate_multi_shot_video,
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
