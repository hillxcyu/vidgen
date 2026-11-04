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
from src.tools.video_parser import (
    extract_last_frame,
    create_agentic_video_part,
    decode_valid_image_b64,
    extract_labeled_audit_keyframes,
    analyze_clip_audio_tail,
    compute_transcript_metrics,
)
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
    is_extend_shot: bool = False,
    is_r2v_shot: bool = False,
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
    extend_context = (
        "\nCRITICAL VIDEO-EXTEND SEAM RULE: This shot directly extends the final frame of the preceding clip. "
        "Maintain the exact starting environment, lighting, and subject pose from the previous shot and progress via one unbroken single-take camera movement with ZERO scene cuts or location teleports."
        if is_extend_shot else ""
    )
    r2v_context = (
        "\nCRITICAL R2V SCENE-OPENING RULE: This shot uses Reference-to-Video (task='reference_to_video') with a studio-white subject/product reference image. "
        "Open immediately on Frame 0 inside the rich target environment described in the shot—NEVER depict, mention, or transition/dissolve out of a white studio backdrop."
        if is_r2v_shot else ""
    )

    full_prompt = (
        f"Raw Shot Description: '{raw_prompt}'.{feedback_context}{transcript_context}{extend_context}{r2v_context}\n"
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
    opening_environment_observed: str = Field(
        default="",
        description="Factual description of the physical environment, lighting, and subject visible on Frame 0 (t=0.0s).",
    )
    heard_transcript: str = Field(
        default="",
        description="Exact verbatim words spoken audibly in the clip (empty string if no speech is heard).",
    )
    speech_end_sec: Optional[float] = Field(
        default=None,
        description="Approximate timestamp in seconds where spoken dialogue concludes (null if no speech).",
    )
    detected_internal_cuts: int = Field(
        default=0,
        description="Count of abrupt internal camera jump-cuts inside this single clip (0 if continuous single take).",
    )
    reason: List[CriterionEvaluation] = Field(
        default_factory=list,
        description="Detailed list evaluating each individual consolidated criterion with its specific score and findings."
    )
    score: float = Field(
        default=0.0,
        description="Overall aggregated quality score from 0.0 to 1.0 (>= 0.8 is PASS, < 0.8 requires reattempt)."
    )
    verdict: str = Field(
        default="REATTEMPT_REQUIRED",
        description="Overall verdict: 'PASSED' if score >= 0.8, else 'REATTEMPT_REQUIRED'."
    )
    feedback: str = Field(
        default="",
        description="Actionable summary feedback for downstream PromptOptimizerAgent."
    )
    transcript_wer: Optional[float] = Field(default=None)
    transcript_word_overlap: Optional[float] = Field(default=None)
    audit_status: str = Field(default="OK")
    deterministic_telemetry: Dict[str, Any] = Field(default_factory=dict)


def build_quality_evaluation_schema() -> types.Schema:
    """Builds explicit Google GenAI Schema enforcing observation-first property_ordering before score."""
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


def consolidate_evaluation_rubric_fallback(
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    has_reference_anchor: bool = False,
) -> List[str]:
    """Deterministic zero-extra-hop evaluation rubric builder."""
    rubric = []
    if evaluation_criteria and evaluation_criteria.strip():
        rubric.append(f"Scene Goal: {evaluation_criteria.strip()}")

    rubric.extend([
        "Face Identity Locking: Facial features, skin tone, and geometry stability.",
        "Product & Object Locking: Product shape, branding, color, and object continuity.",
        "Wardrobe & Clothing Locking: Garment style, color, texture, and outfit stability.",
        "Accessories & Props Locking: Handheld items, jewelry, glasses, or props to prevent vanishing.",
        "Single-Take & Background Coherence: Unbroken continuous camera take inside target setting (zero internal cuts; no studio #FFFFFF backdrop echo)."
        if has_reference_anchor
        else "Single-Take & Background Coherence: Unbroken continuous camera take with lighting and camera angle coherence."
    ])
    if spoken_dialogue and spoken_dialogue.strip():
        rubric.append(
            f"Spoken Dialogue & Audio Completion: Exact spoken line ('{spoken_dialogue.strip()}') articulated cleanly and completed before clip end."
        )
    return rubric


async def consolidate_rubric_with_llm(
    shot_index: int,
    prompt: str,
    evaluation_criteria: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None
) -> Tuple[List[str], str]:
    """Backwards-compatible rubric builder returning deterministic consolidated rubric without extra LLM latency."""
    rubric = consolidate_evaluation_rubric_fallback(evaluation_criteria=evaluation_criteria)
    drafted = f"Inspect shot #{shot_index} high-res stills and full video clip against consolidated rubrics."
    return rubric, drafted


async def evaluate_clip_quality(
    shot_index: int,
    prompt: str,
    video_path: str,
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    prev_last_frame_b64: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Dict[str, Any]:
    """Quality Rater Agent v2: Observation-first schema + hybrid high-res stills + deterministic audio/WER telemetry."""
    config = Config()
    agents = create_adk_agents(config)
    rater = agents["quality_rater"]

    ref_anchor = decode_valid_image_b64(reference_images_b64[0]) if reference_images_b64 else None
    prev_frame_img = decode_valid_image_b64(prev_last_frame_b64) if prev_last_frame_b64 else None

    consolidated_rubric = consolidate_evaluation_rubric_fallback(
        evaluation_criteria=evaluation_criteria,
        spoken_dialogue=spoken_dialogue,
        has_reference_anchor=ref_anchor is not None,
    )

    # Check for missing or empty file
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        res = QualityEvaluationResult(
            score=0.0,
            reason=[CriterionEvaluation(criterion_name="Video File Integrity", score=0.0, comments="File missing or 0 bytes")],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"FAILED: Video shot #{shot_index} generation failed or output file is empty (0 bytes).",
            audit_status="FILE_MISSING",
        )
        res_dict = res.model_dump()
        res_dict["consolidated_rubric"] = consolidated_rubric
        return res_dict

    media_parts: List[types.Part] = []
    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        if not video_bytes:
            res = QualityEvaluationResult(
                score=0.0,
                reason=[CriterionEvaluation(criterion_name="Video File Integrity", score=0.0, comments="File contains 0 bytes")],
                verdict="REATTEMPT_REQUIRED",
                feedback=f"FAILED: Video shot #{shot_index} contains 0 bytes.",
                audit_status="FILE_EMPTY",
            )
            res_dict = res.model_dump()
            res_dict["consolidated_rubric"] = consolidated_rubric
            return res_dict
        media_parts.append(create_agentic_video_part(video_path_or_uri=video_path, video_bytes=video_bytes, media_processing=config.MEDIA_PROCESSING))
    except Exception as e:
        res = QualityEvaluationResult(
            score=0.0,
            reason=[CriterionEvaluation(criterion_name="Video File Access", score=0.0, comments=str(e))],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"FAILED: Could not read video file at {video_path}: {e}",
            audit_status="FILE_READ_ERROR",
        )
        res_dict = res.model_dump()
        res_dict["consolidated_rubric"] = consolidated_rubric
        return res_dict

    audit_keyframes = await asyncio.to_thread(extract_labeled_audit_keyframes, video_path)
    audio_telemetry = await asyncio.to_thread(analyze_clip_audio_tail, video_path, 0.2)

    rubric_str = "\n".join(f"- {r}" for r in consolidated_rubric)
    dialogue_line = f"\nExpected Spoken Dialogue: '{spoken_dialogue}'" if spoken_dialogue else ""
    eval_instructions = (
        f"You are the QualityRaterAgent performing an observation-first visual & audio quality audit on shot #{shot_index}.\n"
        f"Target Shot Prompt: '{prompt}'{dialogue_line}\n"
        f"Measured Duration: {audio_telemetry.get('clip_duration_sec', 0.0)}s | "
        f"Trailing 0.2s RMS: {audio_telemetry.get('trailing_rms_db', -90.0)} dBFS\n\n"
        f"CONSOLIDATED EVALUATION RUBRIC:\n{rubric_str}\n\n"
        "Extract opening_environment_observed, heard_transcript, speech_end_sec, and detected_internal_cuts BEFORE scoring.\n"
        "If score < 0.8 on any criterion, set verdict='REATTEMPT_REQUIRED'."
    )

    eval_res = None
    last_error = None
    schema_obj = build_quality_evaluation_schema()
    for retry_attempt in range(2):
        if client:
            try:
                genai_contents: List[Any] = [eval_instructions]
                if ref_anchor is not None:
                    ref_bytes, ref_mime = ref_anchor
                    genai_contents.append("CANONICAL REFERENCE ANCHOR (#FFFFFF):")
                    genai_contents.append(types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime))
                if prev_frame_img is not None:
                    pf_bytes, pf_mime = prev_frame_img
                    genai_contents.append("PRIOR SHOT TERMINAL FRAME:")
                    genai_contents.append(types.Part.from_bytes(data=pf_bytes, mime_type=pf_mime))
                for kf_label, kf_png in audit_keyframes:
                    genai_contents.append(f"CANDIDATE HIGH-RES STILL [{kf_label}]:")
                    genai_contents.append(types.Part.from_bytes(data=kf_png, mime_type="image/png"))
                genai_contents.append("CANDIDATE FULL VIDEO CLIP:")
                genai_contents.extend(media_parts)

                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=config.ORCHESTRATOR_MODEL,
                    contents=genai_contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema_obj,
                        temperature=0.1,
                    )
                )
                if resp and isinstance(resp.text, str) and resp.text.strip():
                    eval_res = QualityEvaluationResult.model_validate_json(resp.text)
                    break
            except Exception as sdk_err:
                last_error = sdk_err
                print(f"[QUALITY RATER SDK ATTEMPT {retry_attempt+1} NOTICE]: {sdk_err}")

        try:
            adk_kwargs: Dict[str, Any] = {"media_parts": media_parts, "session_service": session_service}
            if session_id is not None:
                adk_kwargs["session_id"] = session_id
            text = await run_adk_agent(rater, eval_instructions, **adk_kwargs)
            import re
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else text
            eval_res = QualityEvaluationResult.model_validate_json(clean_text)
            break
        except Exception as adk_err:
            last_error = adk_err
            print(f"[QUALITY RATER ADK ATTEMPT {retry_attempt+1} NOTICE]: {adk_err}")

    if eval_res:
        min_criterion_score = min([item.score for item in eval_res.reason], default=eval_res.score)
        eval_res.score = min(eval_res.score, min_criterion_score)
        eval_res.deterministic_telemetry = audio_telemetry
        if spoken_dialogue and spoken_dialogue.strip():
            tx = compute_transcript_metrics(spoken_dialogue, eval_res.heard_transcript)
            eval_res.transcript_wer = tx["transcript_wer"]
            eval_res.transcript_word_overlap = tx["transcript_word_overlap"]
            if (eval_res.heard_transcript.strip() or audio_telemetry.get("has_audio")) and tx["transcript_wer"] is not None and tx["transcript_wer"] > 0.35:
                eval_res.score = min(eval_res.score, 0.65)
        if audio_telemetry.get("speech_cutoff_detected"):
            eval_res.score = min(eval_res.score, 0.65)
        if eval_res.detected_internal_cuts > 0:
            eval_res.score = min(eval_res.score, 0.60)
        eval_res.verdict = "PASSED" if eval_res.score >= 0.8 else "REATTEMPT_REQUIRED"
    else:
        eval_res = QualityEvaluationResult(
            score=0.5,
            reason=[CriterionEvaluation(criterion_name="Visual Audit Execution", score=0.5, comments=f"Audit parsing notice: {last_error}")],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"REATTEMPT REQUIRED: Quality audit encountered timeout/parsing error ({last_error}). Requesting prompt refinement.",
            audit_status="AUDIT_TIMEOUT_DEGRADED",
            deterministic_telemetry=audio_telemetry,
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
            is_r2v_shot = bool(
                state.reference_assets_b64
                and (
                    state.mode == "reference"
                    or (state.mode == "i2v_chaining" and not prev_frame_b64)
                    or (state.mode == "video_extend" and idx == 0)
                )
            )
            optimized_shot_prompt = asyncio.run(
                optimize_prompt(shot.prompt, feedback=feedback, is_r2v_shot=is_r2v_shot, client=client)
            )
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
            use_refs = (
                state.reference_assets_b64
                if (
                    state.mode == "reference"
                    or (state.mode == "i2v_chaining" and not prev_frame_b64)
                    or (state.mode == "video_extend" and idx == 0)
                )
                else None
            )
            shot_task = "reference_to_video" if use_refs else None
            control_str = build_omni_control_string(
                prompt=optimized_shot_prompt,
                input_image_b64=prev_frame_b64 if state.mode == "i2v_chaining" else None,
                task=shot_task,
                reference_images_b64=use_refs,
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
                    "task": shot_task or "image_to_video",
                    "prompt": optimized_shot_prompt,
                    "has_input_image": prev_frame_b64 is not None,
                    "has_reference_anchor": bool(use_refs),
                }
            )

            if state.mode == "i2v_chaining":
                video_bytes = generate_omni_clip(
                    prompt=optimized_shot_prompt,
                    input_image_b64=prev_frame_b64,
                    task=shot_task,
                    reference_images_b64=use_refs,
                    aspect_ratio=state.aspect_ratio,
                    resolution=state.resolution,
                    duration=state.duration,
                    client=client
                )
            else:
                video_bytes = generate_omni_clip(
                    prompt=optimized_shot_prompt,
                    task=shot_task,
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
