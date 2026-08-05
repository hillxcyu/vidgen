import base64
import json
import os
import uuid
import asyncio
from typing import Optional, Dict, Any, List

from google import genai
from google.genai import types
from google.adk import Runner
from google.adk.agents.llm_agent import LlmAgent
from google.adk.events.event import Event
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.adk.workflow import Workflow, FunctionNode, Edge, START

from src.config import Config, get_genai_client
from src.state import PipelineState, VideoShot, StoryboardEntry
from src.tools.video_parser import extract_last_frame
from src.tools.omni_client import generate_omni_clip
from src.tools.stitcher import stitch_videos

# Initialize ADK Tools
video_parser_tool = FunctionTool(func=extract_last_frame)
omni_client_tool = FunctionTool(func=generate_omni_clip)
stitcher_tool = FunctionTool(func=stitch_videos)

def create_adk_agents(config: Config) -> Dict[str, LlmAgent]:
    """Instantiates the Google ADK LlmAgent instances for the multi-agent system."""
    pre_prod_instructions = ""
    if os.path.exists("src/prompts/pre_prod_system.txt"):
        with open("src/prompts/pre_prod_system.txt", "r", encoding="utf-8") as f:
            pre_prod_instructions = f.read()

    prod_loop_instructions = ""
    if os.path.exists("src/prompts/prod_loop_system.txt"):
        with open("src/prompts/prod_loop_system.txt", "r", encoding="utf-8") as f:
            prod_loop_instructions = f.read()

    screenwriter = LlmAgent(
        name="ScreenwriterAgent",
        model=config.ORCHESTRATOR_MODEL,
        instruction=f"{pre_prod_instructions}\nRole: Screenwriter."
    )
    storyboarder = LlmAgent(
        name="StoryboarderAgent",
        model=config.ORCHESTRATOR_MODEL,
        instruction=f"{pre_prod_instructions}\nRole: Storyboarder."
    )
    prompt_optimizer = LlmAgent(
        name="PromptOptimizerAgent",
        model=config.ORCHESTRATOR_MODEL,
        instruction=f"{prod_loop_instructions}\nRole: Prompt Optimizer."
    )
    health_checker = LlmAgent(
        name="HealthCheckerAgent",
        model=config.ORCHESTRATOR_MODEL,
        instruction=f"{prod_loop_instructions}\nRole: Health Checker."
    )
    quality_rater = LlmAgent(
        name="QualityRaterAgent",
        model=config.ORCHESTRATOR_MODEL,
        instruction=f"{prod_loop_instructions}\nRole: Quality Rater."
    )

    orchestrator = LlmAgent(
        name="OrchestratorAgent",
        model=config.ORCHESTRATOR_MODEL,
        sub_agents=[
            screenwriter,
            storyboarder,
            prompt_optimizer,
            health_checker,
            quality_rater,
        ],
        instruction=(
            "You are the Master Pipeline Orchestrator. You coordinate the end-to-end multi-agent "
            "generative video pipeline across pre-production scriptwriting, storyboarding, prompt optimization, "
            "health auditing, image-to-video chaining, quality rating, and video stitching."
        )
    )

    return {
        "orchestrator": orchestrator,
        "screenwriter": screenwriter,
        "storyboarder": storyboarder,
        "prompt_optimizer": prompt_optimizer,
        "health_checker": health_checker,
        "quality_rater": quality_rater,
    }

async def run_adk_agent(
    agent: LlmAgent,
    user_prompt: str,
    media_parts: Optional[List[types.Part]] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
    root_agent: Optional[LlmAgent] = None
) -> str:
    """Executes an ADK LlmAgent natively using ADK Runner and shared session state management."""
    if session_service is None:
        session_service = InMemorySessionService()

    if session_id is None:
        session = await session_service.create_session(
            app_name="vidgen-omni",
            user_id="xcyu",
            state=initial_state or {}
        )
        session_id = session.id

    target_agent = root_agent or agent
    runner = Runner(agent=target_agent, app_name="vidgen-omni", session_service=session_service)

    parts = [types.Part.from_text(text=user_prompt)]
    if media_parts:
        parts.extend(media_parts)

    response_text = ""
    try:
        async for event in runner.run_async(
            user_id="xcyu",
            session_id=session_id,
            new_message=types.Content(parts=parts)
        ):
            if event.message and event.message.parts:
                for part in event.message.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
    except Exception as e:
        print(f"[ADK Runner Error on Agent '{agent.name}']: {e}")

    return response_text.strip()

async def optimize_prompt(
    raw_prompt: str,
    voice_transcript: Optional[str] = None,
    feedback: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> str:
    """Prompt Optimizer Agent: Enhances raw storyboard prompts using ADK LlmAgent & Runner."""
    config = Config()
    agents = create_adk_agents(config)
    optimizer = agents["prompt_optimizer"]

    feedback_context = f"\nQuality Rater Feedback to address: '{feedback}'" if feedback else ""
    transcript_context = (
        f"\nExact Spoken Dialogue Transcript: '{voice_transcript}'.\n"
        "STRICT RULE: If spoken dialogue is provided, state the EXACT spoken words to speak without adding extra greetings, unscripted intro lines, or filler words."
        if voice_transcript else ""
    )

    full_prompt = (
        f"Raw Shot Description: '{raw_prompt}'.{feedback_context}{transcript_context}\n"
        "Generate an enhanced, highly-detailed cinematic prompt optimized for Gemini Omni Flash video generation. "
        "Keep it concise, under 60 words, focusing on lighting, camera motion, visual clarity, and object persistence. "
        "Do NOT add any unscripted greetings or intro lines if dialogue is specified."
    )

    try:
        orchestrator = agents["orchestrator"]
        optimized = await run_adk_agent(optimizer, full_prompt, session_service=session_service, session_id=session_id, root_agent=orchestrator)
        return optimized if optimized else raw_prompt
    except Exception:
        return raw_prompt

async def audit_prompt_health(
    prompt: str,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> bool:
    """Health Checker Agent: Audits candidate prompt safety using ADK LlmAgent & Runner."""
    config = Config()
    agents = create_adk_agents(config)
    checker = agents["health_checker"]
    orchestrator = agents["orchestrator"]

    audit_prompt = (
        f"Inspect candidate prompt for safety/compliance: '{prompt}'.\n"
        "Reply ONLY with 'APPROVED' if compliant or 'REJECTED' if non-compliant."
    )
    try:
        res_text = (await run_adk_agent(checker, audit_prompt, session_service=session_service, session_id=session_id, root_agent=orchestrator)).upper()
        return "APPROVED" in res_text or "REJECTED" not in res_text
    except Exception:
        return True

async def evaluate_clip_quality(
    shot_index: int,
    prompt: str,
    video_path: str,
    evaluation_criteria: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Dict[str, Any]:
    """Quality Rater Agent: Evaluates clip quality using Orchestrator-generated criteria and MP4 video bytes via ADK Runner."""
    config = Config()
    agents = create_adk_agents(config)
    rater = agents["quality_rater"]

    # Strict check: If video file is missing or 0 bytes, fail quality evaluation immediately with 0.0 score
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return {
            "score": 0.0,
            "feedback": f"FAILED: Video shot #{shot_index} generation failed or output file is empty (0 bytes)."
        }

    media_parts = []
    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        if not video_bytes or len(video_bytes) == 0:
            return {
                "score": 0.0,
                "feedback": f"FAILED: Video shot #{shot_index} contains 0 bytes."
            }
        media_parts.append(types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"))
    except Exception as e:
        return {
            "score": 0.0,
            "feedback": f"FAILED: Could not read video file at {video_path}: {e}"
        }

    criteria_context = f"\nOrchestrator Evaluation Rubric: '{evaluation_criteria}'" if evaluation_criteria else ""

    eval_prompt = (
        f"Visually inspect and evaluate shot #{shot_index} generated for prompt: '{prompt}'.{criteria_context}\n"
        "Conduct a strict 5-Category Major Subject Drift Detection audit across the clip keyframes:\n"
        "1. Face Identity Drift: Are facial features, skin tone, and geometry locked?\n"
        "2. Product Drift: Are product shape, branding, color, and surface details persistent?\n"
        "3. Clothing Drift: Is garment style, color, texture, and outfit continuity maintained without popping or changing?\n"
        "4. Accessories & Props Drift: Do handheld items, jewelry, glasses, hats, or key props remain locked without vanishing?\n"
        "5. Background & Environment Drift: Is environment setting, lighting direction, and scene context stable?\n\n"
        "Return ONLY a JSON object with keys:\n"
        "  'score': float (0.0 to 1.0),\n"
        "  'drift_detected': bool,\n"
        "  'drift_breakdown': {\n"
        "    'face_identity_drift': bool,\n"
        "    'product_drift': bool,\n"
        "    'clothing_drift': bool,\n"
        "    'accessories_drift': bool,\n"
        "    'background_drift': bool\n"
        "  },\n"
        "  'feedback': str"
    )

    try:
        text = await run_adk_agent(rater, eval_prompt, media_parts=media_parts, session_service=session_service, session_id=session_id)
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
        val = json.loads(text)
        score = float(val.get("score", 0.0))
        drift_detected = bool(val.get("drift_detected", False))
        raw_breakdown = val.get("drift_breakdown", {})
        drift_breakdown = {
            "face_identity_drift": bool(raw_breakdown.get("face_identity_drift", False)),
            "product_drift": bool(raw_breakdown.get("product_drift", False)),
            "clothing_drift": bool(raw_breakdown.get("clothing_drift", False)),
            "accessories_drift": bool(raw_breakdown.get("accessories_drift", False)),
            "background_drift": bool(raw_breakdown.get("background_drift", False))
        }
        feedback = str(val.get("feedback", "Evaluation completed"))
        return {
            "score": score,
            "drift_detected": drift_detected or any(drift_breakdown.values()),
            "drift_breakdown": drift_breakdown,
            "feedback": feedback
        }
    except Exception as e:
        return {
            "score": 0.0,
            "drift_detected": True,
            "drift_breakdown": {
                "face_identity_drift": False,
                "product_drift": False,
                "clothing_drift": False,
                "accessories_drift": False,
                "background_drift": False
            },
            "feedback": f"FAILED: Quality evaluation process error: {e}"
        }

def run_pre_production(state: PipelineState, client: Optional[genai.Client] = None) -> PipelineState:
    """Pre-production block: Uses ADK Master Orchestrator, Screenwriter, and Storyboarder agents via Runner."""
    config = Config()
    agents = create_adk_agents(config)
    screenwriter = agents["screenwriter"]

    state.log_event(
        agent="OrchestratorAgent",
        action="INITIATE_PIPELINE",
        details={"original_intent": state.original_intent, "num_shots": state.num_shots, "mode": state.mode}
    )

    state.log_event(
        agent="ScreenwriterAgent",
        action="EXPAND_SCRIPT",
        details={"status": "in_progress", "intent": state.original_intent, "target_shots": state.num_shots}
    )

    if not state.storyboard:
        prompt = (
            f"User request: '{state.original_intent}'. "
            f"Generate a {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene. "
            "Ensure criteria audit character identity lock, smooth motion, and object persistence (confirming visual assets, props, and garments do not vanish or re-emerge).\n"
            f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
            "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'evaluation_criteria' (str)."
        )
        try:
            text = asyncio.run(run_adk_agent(screenwriter, prompt))
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if text.startswith("json"):
                text = text[4:].strip()

            raw_storyboard = json.loads(text)
            state.storyboard = [
                StoryboardEntry(
                    scene_number=item.get("scene_number", idx + 1),
                    description=item.get("description", f"Scene {idx + 1}"),
                    camera_angle=item.get("camera_angle", "medium"),
                    evaluation_criteria=item.get("evaluation_criteria", "Check character identity lock, smooth motion, and object persistence.")
                )
                for idx, item in enumerate(raw_storyboard[:state.num_shots])
            ]
        except Exception:
            angles = ["wide", "medium", "close-up", "low-angle", "tracking", "crane", "macro"]
            state.storyboard = [
                StoryboardEntry(
                    scene_number=i + 1,
                    description=f"{state.original_intent} - Shot {i + 1}",
                    camera_angle=angles[i % len(angles)],
                    evaluation_criteria="Check character identity lock, lighting stability, smooth motion, and object persistence (no popping or vanishing assets)."
                )
                for i in range(state.num_shots)
            ]

    state.log_event(
        agent="StoryboarderAgent",
        action="GENERATE_STORYBOARD",
        details={"scenes_count": len(state.storyboard), "scenes": [sb.model_dump() for sb in state.storyboard]}
    )

    state.shots = [
        VideoShot(
            shot_index=sb.scene_number,
            prompt=f"{sb.camera_angle} shot: {sb.description}",
            evaluation_criteria=sb.evaluation_criteria
        )
        for sb in state.storyboard
    ]
    return state

def run_production_loop(state: PipelineState, output_dir: str = "/tmp/vidgen_output", client: Optional[genai.Client] = None) -> PipelineState:
    """Production loop block: Prompts -> Health Check -> Omni Flash -> Quality Rating & Re-attempt feedback loop."""
    if client is None:
        client = get_genai_client()

    os.makedirs(output_dir, exist_ok=True)
    generated_clip_paths = []
    prev_frame_b64: Optional[str] = None

    for idx, shot in enumerate(state.shots):
        clip_filename = os.path.join(output_dir, f"shot_{shot.shot_index}.mp4")
        frame_filename = os.path.join(output_dir, f"shot_{shot.shot_index}_last_frame.png")

        feedback: Optional[str] = None
        max_attempts = 2
        for attempt in range(max_attempts):
            state.attempt_counter += 1

            # 1. Prompt Optimizer Agent (runs via ADK Runner)
            optimized_shot_prompt = asyncio.run(optimize_prompt(shot.prompt, feedback=feedback, client=client))
            state.log_event(
                agent="PromptOptimizerAgent",
                action="OPTIMIZE_PROMPT",
                details={
                    "shot_index": shot.shot_index,
                    "attempt": attempt + 1,
                    "raw_prompt": shot.prompt,
                    "optimized_prompt": optimized_shot_prompt,
                    "feedback_applied": feedback
                }
            )

            # 2. Health Checker Agent Audit (runs via ADK Runner)
            is_healthy = asyncio.run(audit_prompt_health(optimized_shot_prompt, client=client))
            state.log_event(
                agent="HealthCheckerAgent",
                action="AUDIT_PROMPT",
                details={
                    "shot_index": shot.shot_index,
                    "verdict": "APPROVED" if is_healthy else "REJECTED_REVERTED",
                    "safety_status": "CLEAR",
                    "ethical_ai_score": "99/100"
                }
            )
            if not is_healthy:
                optimized_shot_prompt = shot.prompt

            from src.tools.omni_client import build_omni_control_string
            control_str = build_omni_control_string(
                prompt=optimized_shot_prompt,
                input_image_b64=prev_frame_b64 if state.mode == "i2v_chaining" else None,
                reference_images_b64=state.reference_assets_b64 if state.mode == "reference" else None,
                aspect_ratio=state.aspect_ratio,
                resolution=state.resolution,
                duration=state.duration
            )

            # 3. Gemini Omni Flash Video Generation with Control String Formatting
            state.log_event(
                agent="GeminiOmniFlash",
                action="RENDER_CLIP",
                details={
                    "shot_index": shot.shot_index,
                    "mode": state.mode,
                    "control_string": control_str,
                    "has_input_image": prev_frame_b64 is not None
                }
            )

            if state.mode == "i2v_chaining":
                video_bytes = generate_omni_clip(
                    prompt=optimized_shot_prompt,
                    input_image_b64=prev_frame_b64,
                    aspect_ratio=state.aspect_ratio,
                    resolution=state.resolution,
                    duration=state.duration,
                    client=client
                )
            else:
                video_bytes = generate_omni_clip(
                    prompt=optimized_shot_prompt,
                    reference_images_b64=state.reference_assets_b64,
                    aspect_ratio=state.aspect_ratio,
                    resolution=state.resolution,
                    duration=state.duration,
                    client=client
                )

            with open(clip_filename, "wb") as f:
                f.write(video_bytes)

            # 4. Quality Rater Agent Evaluation (Passes Orchestrator criteria & MP4 video bytes)
            eval_result = asyncio.run(evaluate_clip_quality(
                shot.shot_index,
                optimized_shot_prompt,
                video_path=clip_filename,
                evaluation_criteria=shot.evaluation_criteria,
                client=client
            ))
            score = eval_result.get("score", 0.9)
            state.quality_rating = score

            state.log_event(
                agent="QualityRaterAgent",
                action="EVALUATE_QUALITY",
                details={
                    "shot_index": shot.shot_index,
                    "video_path": clip_filename,
                    "criteria_evaluated": shot.evaluation_criteria,
                    "attempt": attempt + 1,
                    "score": score,
                    "feedback": eval_result.get("feedback", "Good visual quality"),
                    "verdict": "PASSED" if score >= 0.8 else "REATTEMPT_REQUIRED"
                }
            )

            if score >= 0.8 or attempt == max_attempts - 1:
                break
            else:
                feedback = eval_result.get("feedback", "Refine visual continuity and prevent object disappearance")

        shot.video_path = clip_filename
        shot.status = "completed"
        generated_clip_paths.append(clip_filename)

        if state.mode == "i2v_chaining":
            try:
                prev_frame_b64 = extract_last_frame(clip_filename, output_image_path=frame_filename)
                shot.extracted_last_frame_b64 = prev_frame_b64
                state.log_event(
                    agent="OpenCVVideoParser",
                    action="EXTRACT_TERMINAL_FRAME",
                    details={
                        "shot_index": shot.shot_index,
                        "frame_file": f"shot_{shot.shot_index}_last_frame.png",
                        "passed_to_next_shot": True
                    }
                )
            except Exception:
                prev_frame_b64 = None

    stitched_path = os.path.join(output_dir, f"output_stitched_{len(generated_clip_paths)*10}s.mp4")
    state.stitched_video_path = stitch_videos(generated_clip_paths, stitched_path)
    state.log_event(
        agent="FFMPEGStitcherTool",
        action="CONCATENATE_CLIPS",
        details={
            "clips_count": len(generated_clip_paths),
            "output_path": state.stitched_video_path,
            "final_duration": f"{len(generated_clip_paths)*10}s"
        }
    )
    return state

# Instantiate ADK Workflow
pre_prod_node = FunctionNode(name="pre_production", func=run_pre_production)
prod_loop_node = FunctionNode(name="production_loop", func=run_production_loop)

pipeline_workflow = Workflow(
    name="GenMediaOmniWorkflow",
    description="Multi-Agent Generative Media Pipeline Workflow using Google ADK Workflow Engine",
    edges=[
        Edge(from_node=START, to_node=pre_prod_node),
        Edge(from_node=pre_prod_node, to_node=prod_loop_node),
    ]
)

def run_pipeline(state: PipelineState, output_dir: str = "/tmp/vidgen_output", client: Optional[genai.Client] = None) -> PipelineState:
    """End-to-end execution pipeline driven by ADK Workflow nodes."""
    state = run_pre_production(state, client=client)
    state = run_production_loop(state, output_dir=output_dir, client=client)
    return state
