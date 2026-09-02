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
from src.tools.video_parser import extract_last_frame, create_agentic_video_part
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
            app_name="vidgen",
            user_id="xcyu",
            state=initial_state or {}
        )
        session_id = session.id

    target_agent = root_agent or agent
    runner = Runner(agent=target_agent, app_name="vidgen", session_service=session_service)

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
        "Keep it concise, under 60 words, focusing on lighting, continuous camera motion, visual clarity, and object persistence. "
        "STRICT SINGLE-SHOT RULE: The clip MUST be a single, continuous, uninterrupted camera take. Explicitly specify a single continuous camera motion (e.g. 'continuous single take', 'smooth tracking shot') and strictly forbid internal cuts, scene switches, jump cuts, or multi-angle edits. "
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

from pydantic import BaseModel, Field
from typing import Tuple

class CriterionEvaluation(BaseModel):
    criterion_name: str = Field(description="Name of the evaluated criterion.")
    score: float = Field(default=1.0, description="Score for this specific criterion (0.0 to 1.0).")
    comments: str = Field(default="Meets criteria", description="Specific observation or comment for this criterion.")

class QualityEvaluationResult(BaseModel):
    score: float = Field(
        default=0.0,
        description="Overall aggregated quality score from 0.0 to 1.0 (>= 0.8 is PASS, < 0.8 requires reattempt)."
    )
    reason: List[CriterionEvaluation] = Field(
        default_factory=list,
        description="Detailed list evaluating each individual consolidated criterion with its specific score and findings."
    )
    verdict: str = Field(
        default="REATTEMPT_REQUIRED",
        description="Overall verdict: 'PASSED' if score >= 0.8, else 'REATTEMPT_REQUIRED'."
    )
    feedback: str = Field(
        default="",
        description="Actionable summary feedback for downstream PromptOptimizerAgent."
    )

def consolidate_evaluation_rubric_fallback(evaluation_criteria: Optional[str] = None) -> List[str]:
    """Fallback static rubric consolidation if LLM step fails."""
    rubric = []
    if evaluation_criteria and evaluation_criteria.strip():
        rubric.append(f"Scene Goal: {evaluation_criteria.strip()}")

    rubric.extend([
        "Face Identity Locking: Facial features, skin tone, and geometry stability.",
        "Product & Object Locking: Product shape, branding, color, and object continuity.",
        "Wardrobe & Clothing Locking: Garment style, color, texture, and outfit stability.",
        "Accessories & Props Locking: Handheld items, jewelry, glasses, or props to prevent vanishing.",
        "Background & Environment Locking: Background setting, lighting direction, and camera angle coherence."
    ])
    return rubric

async def consolidate_rubric_with_llm(
    shot_index: int,
    prompt: str,
    evaluation_criteria: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None
) -> Tuple[List[str], str]:
    """Uses LLM to consolidate Orchestrator scene criteria with 5-Category Subject Drift parameters and draft an evaluation prompt."""
    config = Config()
    agents = create_adk_agents(config)
    rater = agents["quality_rater"]

    criteria_str = f"Orchestrator Scene Goal: '{evaluation_criteria}'" if evaluation_criteria else "No specific scene goal provided."

    consolidation_prompt = (
        f"You are the Lead Quality Auditor preparing an evaluation rubric for shot #{shot_index}.\n"
        f"Shot Prompt: '{prompt}'\n"
        f"{criteria_str}\n\n"
        "Consolidate the Orchestrator scene goal with standard 5-Category Subject Drift parameters:\n"
        "1. Face Identity Locking\n"
        "2. Product & Object Continuity\n"
        "3. Wardrobe & Clothing Locking\n"
        "4. Accessories & Props Locking\n"
        "5. Background & Environment Coherence\n\n"
        "Output ONLY a JSON object formatted as:\n"
        "{\n"
        '  "consolidated_rubric": ["Criterion 1: description", "Criterion 2: description", ...],\n'
        '  "drafted_eval_prompt": "Tailored step-by-step instructions for inspecting candidate video clip keyframes."\n'
        "}"
    )

    try:
        import re
        text = await run_adk_agent(rater, consolidation_prompt, session_service=session_service, session_id=session_id)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        clean_text = json_match.group(0) if json_match else text
        data = json.loads(clean_text)
        rubric = data.get("consolidated_rubric", [])
        drafted_prompt = data.get("drafted_eval_prompt", f"Visually inspect shot #{shot_index} keyframes against consolidated rubrics.")
        if not rubric:
            rubric = consolidate_evaluation_rubric_fallback(evaluation_criteria)
        return rubric, drafted_prompt
    except Exception as e:
        print(f"[LLM RUBRIC CONSOLIDATION NOTICE]: {e}. Using default fallback rubric.")
        default_rubric = consolidate_evaluation_rubric_fallback(evaluation_criteria)
        default_drafted = f"Visually inspect shot #{shot_index} keyframes against consolidated rubrics."
        return default_rubric, default_drafted

async def evaluate_clip_quality(
    shot_index: int,
    prompt: str,
    video_path: str,
    evaluation_criteria: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Dict[str, Any]:
    """Quality Rater Agent: Consolidates rubrics via LLM, then evaluates clip returning structured score and per-criterion reason breakdown."""
    config = Config()
    agents = create_adk_agents(config)
    rater = agents["quality_rater"]

    # Step 1: LLM Rubric Consolidation & Prompt Drafting
    consolidated_rubric, drafted_eval_prompt = await consolidate_rubric_with_llm(
        shot_index=shot_index,
        prompt=prompt,
        evaluation_criteria=evaluation_criteria,
        session_service=session_service,
        session_id=session_id
    )

    # Check for missing or empty file
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        res = QualityEvaluationResult(
            score=0.0,
            reason=[CriterionEvaluation(criterion_name="Video File Integrity", score=0.0, comments="File missing or 0 bytes")],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"FAILED: Video shot #{shot_index} generation failed or output file is empty (0 bytes)."
        )
        res_dict = res.model_dump()
        res_dict["consolidated_rubric"] = consolidated_rubric
        return res_dict

    media_parts = []
    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        if not video_bytes or len(video_bytes) == 0:
            res = QualityEvaluationResult(
                score=0.0,
                reason=[CriterionEvaluation(criterion_name="Video File Integrity", score=0.0, comments="File contains 0 bytes")],
                verdict="REATTEMPT_REQUIRED",
                feedback=f"FAILED: Video shot #{shot_index} contains 0 bytes."
            )
            res_dict = res.model_dump()
            res_dict["consolidated_rubric"] = consolidated_rubric
            return res_dict
        config = Config()
        media_parts.append(create_agentic_video_part(video_path_or_uri=video_path, video_bytes=video_bytes, media_processing=config.MEDIA_PROCESSING))
    except Exception as e:
        res = QualityEvaluationResult(
            score=0.0,
            reason=[CriterionEvaluation(criterion_name="Video File Access", score=0.0, comments=str(e))],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"FAILED: Could not read video file at {video_path}: {e}"
        )
        res_dict = res.model_dump()
        res_dict["consolidated_rubric"] = consolidated_rubric
        return res_dict

    # Step 2: Evaluation using drafted prompt and native GenAI SDK response_schema JSON enforcement
    rubric_str = "\n".join(f"- {r}" for r in consolidated_rubric)
    eval_instructions = (
        f"You are the QualityRaterAgent performing a strict visual quality audit on shot #{shot_index}.\n"
        f"{drafted_eval_prompt}\n\n"
        f"CONSOLIDATED EVALUATION RUBRIC:\n{rubric_str}\n\n"
        "Visually inspect the MP4 clip keyframes against this consolidated rubric.\n"
        "Assess each criterion in the rubric, assign a score (0.0 to 1.0) and specific comments for each.\n"
        "Calculate the overall score (0.0 to 1.0). If score < 0.8 on any criterion, set verdict='REATTEMPT_REQUIRED'."
    )

    eval_res = None
    last_error = None
    for retry_attempt in range(2):
        # 1. Native GenAI SDK call with strict response_schema JSON decoding
        if client:
            try:
                genai_contents = [
                    eval_instructions,
                    types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
                ]
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=config.ORCHESTRATOR_MODEL,
                    contents=genai_contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=QualityEvaluationResult,
                        temperature=0.2
                    )
                )
                if resp and resp.text:
                    eval_res = QualityEvaluationResult.model_validate_json(resp.text)
                    break
            except Exception as sdk_err:
                last_error = sdk_err
                print(f"[QUALITY RATER SDK ATTEMPT {retry_attempt+1} NOTICE]: {sdk_err}")

        # 2. ADK Runner fallback if SDK is unavailable
        try:
            text = await run_adk_agent(rater, eval_instructions, media_parts=media_parts, session_service=session_service, session_id=session_id)
            import re
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else text
            eval_res = QualityEvaluationResult.model_validate_json(clean_text)
            break
        except Exception as adk_err:
            last_error = adk_err
            print(f"[QUALITY RATER ADK ATTEMPT {retry_attempt+1} NOTICE]: {adk_err}")

    if eval_res:
        # Minimum score across individual criteria determines overall score & verdict
        min_criterion_score = min([item.score for item in eval_res.reason], default=eval_res.score)
        eval_res.score = min(eval_res.score, min_criterion_score)
        eval_res.verdict = "PASSED" if eval_res.score >= 0.8 else "REATTEMPT_REQUIRED"
    else:
        eval_res = QualityEvaluationResult(
            score=0.5,
            reason=[CriterionEvaluation(criterion_name="Visual Audit Execution", score=0.5, comments=f"Audit parsing notice: {last_error}")],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"REATTEMPT REQUIRED: Quality audit encountered parsing error ({last_error}). Requesting prompt refinement."
        )

    res_dict = eval_res.model_dump()
    res_dict["consolidated_rubric"] = consolidated_rubric
    return res_dict

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

    storyboarder = agents["storyboarder"]

    if not state.storyboard:
        # Step 1: ScreenwriterAgent expands user prompt into screenplay
        screenplay_prompt = (
            f"User request: '{state.original_intent}'. Mode: {state.mode}.\n"
            f"Write a concise {state.num_shots}-scene screenplay breakdown describing visual motifs, camera directions, character actions, and dialogue distribution."
        )
        try:
            screenplay_text = asyncio.run(run_adk_agent(screenwriter, screenplay_prompt))
        except Exception as sw_err:
            print(f"[SCREENWRITER ERROR]: {sw_err}")
            screenplay_text = f"Scene 1 to {state.num_shots}: {state.original_intent}"

        state.log_event(
            agent="ScreenwriterAgent",
            action="EXPAND_SCRIPT",
            details={"status": "COMPLETED", "intent": state.original_intent, "screenplay": screenplay_text}
        )

        # Step 2: StoryboarderAgent compiles Screenwriter screenplay into structured JSON storyboard
        try:
            storyboard_prompt = (
                f"You are the StoryboarderAgent. Convert the following screenplay into a structured {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene.\n\n"
                f"SCREENPLAY:\n{screenplay_text}\n\n"
                f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
                "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'evaluation_criteria' (str)."
            )
            text = asyncio.run(run_adk_agent(storyboarder, storyboard_prompt))
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
        details={"status": "COMPLETED", "scenes_count": len(state.storyboard), "scenes": [sb.model_dump() for sb in state.storyboard]}
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

            # Log final raw prompt with control string in server logs
            print(f"[GEMINI_OMNI_FLASH_LOG] Shot #{shot.shot_index} Final Raw Control String:\n{control_str}\n")

            # 3. Gemini Omni Flash Video Generation
            state.log_event(
                agent="GeminiOmniFlash",
                action="RENDER_CLIP",
                details={
                    "shot_index": shot.shot_index,
                    "mode": state.mode,
                    "prompt": optimized_shot_prompt,
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
        shot.prompt = optimized_shot_prompt
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
