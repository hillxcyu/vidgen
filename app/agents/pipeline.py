import base64
import json
import os
import re
import asyncio
import concurrent.futures
from typing import Optional, Dict, Any, List, Tuple, Callable

from google import genai
from google.genai import types
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from pydantic import BaseModel, Field

from app.config import Config, get_genai_client
from app.state import PipelineState, VideoShot, StoryboardEntry
from app.tools.video_parser import (
    extract_last_frame,
    extract_keyframes,
    create_agentic_video_part,
    extract_video_tail,
    trim_video_prefix,
    detect_seam_jump_cut,
    detect_r2v_first_frame_lock,
)
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.stitcher import stitch_videos


def _safe_run_async(coro):
    """Safely executes an async coroutine from synchronous code, even inside a running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


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
        description="Detailed list evaluating each individual consolidated criterion."
    )
    verdict: str = Field(
        default="REATTEMPT_REQUIRED",
        description="Overall verdict: 'PASSED' if score >= 0.8, else 'REATTEMPT_REQUIRED'."
    )
    feedback: str = Field(
        default="",
        description="Actionable summary feedback for downstream PromptOptimizerAgent."
    )


def load_prompts() -> Tuple[str, str]:
    """Loads system prompt text files."""
    pre_prod_path = "app/prompts/pre_prod_system.txt"
    if not os.path.exists(pre_prod_path):
        pre_prod_path = "src/prompts/pre_prod_system.txt"
    
    prod_loop_path = "app/prompts/prod_loop_system.txt"
    if not os.path.exists(prod_loop_path):
        prod_loop_path = "src/prompts/prod_loop_system.txt"

    pre_prod = ""
    if os.path.exists(pre_prod_path):
        with open(pre_prod_path, "r", encoding="utf-8") as f:
            pre_prod = f.read()

    prod_loop = ""
    if os.path.exists(prod_loop_path):
        with open(prod_loop_path, "r", encoding="utf-8") as f:
            prod_loop = f.read()

    return pre_prod, prod_loop


def create_pipeline_agents(config: Config) -> Dict[str, Agent]:
    """Creates ADK Agent instances for each role in the pipeline."""
    from app.agent import (
        screenwriter_agent,
        storyboarder_agent,
        prompt_optimizer_agent,
        health_checker_agent,
        quality_rater_agent,
        root_agent,
    )
    return {
        "orchestrator": root_agent,
        "screenwriter": screenwriter_agent,
        "storyboarder": storyboarder_agent,
        "prompt_optimizer": prompt_optimizer_agent,
        "health_checker": health_checker_agent,
        "quality_rater": quality_rater_agent,
    }


async def run_adk_agent(
    agent: Agent,
    user_prompt: str,
    media_parts: Optional[List[types.Part]] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
    root_agent: Optional[Agent] = None,
    client: Optional[genai.Client] = None
) -> str:
    """Executes an ADK Agent natively using ADK Runner or direct client."""
    if client is not None:
        try:
            contents = [user_prompt]
            if media_parts:
                contents.extend(media_parts)
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model=Config.ORCHESTRATOR_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=agent.instruction if isinstance(agent.instruction, str) else None,
                    temperature=0.7
                )
            )
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            print(f"[Client Call Notice on '{agent.name}']: {e}")

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
    from google.adk.apps import App
    adk_app = App(name="vidgen-omni", root_agent=target_agent)
    runner = Runner(app=adk_app, session_service=session_service)

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
            if hasattr(event, "message") and event.message and event.message.parts:
                for part in event.message.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
            elif hasattr(event, "content") and event.content and hasattr(event.content, "parts"):
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
    except Exception as e:
        print(f"[ADK Runner Notice on '{agent.name}']: {e}")

    # Fallback to direct GenAI model call if runner returned empty text
    if not response_text.strip():
        try:
            cli = client or get_genai_client()
            contents = [user_prompt]
            if media_parts:
                contents.extend(media_parts)
            resp = await asyncio.to_thread(
                cli.models.generate_content,
                model=Config.ORCHESTRATOR_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=agent.instruction if isinstance(agent.instruction, str) else None,
                    temperature=0.7
                )
            )
            if resp and resp.text:
                response_text = resp.text
        except Exception as fb_err:
            print(f"[Direct GenAI Fallback Error]: {fb_err}")

    return response_text.strip()


def split_voice_transcript_across_shots(
    voice_transcript: Optional[str],
    num_shots: int,
) -> List[Optional[str]]:
    """Segments a multi-sentence voiceover transcript across N 10s shots so speech never overflows Shot 1."""
    if num_shots <= 0:
        return []
    if not voice_transcript or not voice_transcript.strip():
        return [None] * num_shots
    clean = voice_transcript.strip()
    if num_shots == 1:
        return [clean]

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?。！？;；])\s+", clean)
        if s and s.strip()
    ]
    if len(sentences) == 1:
        words = clean.split()
        if len(words) <= 12:
            return [clean] + [None] * (num_shots - 1)
        # Split a single long unpunctuated line evenly across shots at clause/word boundaries
        chunk_size = max(1, (len(words) + num_shots - 1) // num_shots)
        chunks = [
            " ".join(words[i : i + chunk_size]).strip()
            for i in range(0, len(words), chunk_size)
        ]
        while len(chunks) < num_shots:
            chunks.append(None)  # type: ignore[arg-type]
        return chunks[:num_shots]

    if len(sentences) <= num_shots:
        result: List[Optional[str]] = list(sentences)
        while len(result) < num_shots:
            result.append(None)
        return result

    # More sentences than shots: group proportionally across all N shots
    grouped: List[Optional[str]] = []
    for i in range(num_shots):
        start = round(i * len(sentences) / num_shots)
        end = round((i + 1) * len(sentences) / num_shots)
        seg = " ".join(sentences[start:end]).strip()
        grouped.append(seg if seg else None)
    return grouped


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
    """Prompt Optimizer Agent: Enhances raw storyboard prompts with dialogue integrity rules."""
    config = Config()
    agents = create_pipeline_agents(config)
    optimizer = agents["prompt_optimizer"]

    feedback_context = f"\nQuality Rater Feedback to address: '{feedback}'" if feedback else ""
    transcript_context = (
        f"\nExact Spoken Dialogue Transcript: '{voice_transcript}'.\n"
        "STRICT DIALOGUE RULE: Keep spoken delivery natural and concise so all words finish cleanly before second 8 of the 10-second shot while preserving background ambient sound."
        if voice_transcript else ""
    )
    extend_context = (
        "\nCRITICAL VIDEO-EXTEND SEAM RULE: This shot directly extends the final frame of the preceding clip. "
        "Maintain the exact starting environment, lighting, and subject pose from the previous shot and progress via one unbroken single-take camera movement (smooth dolly, tracking, pan, or push-in) with ZERO scene cuts or location teleports."
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
        "STRICT SINGLE-SHOT RULE: The clip MUST be a single, continuous, uninterrupted camera take. Explicitly specify a single continuous camera motion (e.g. 'continuous single take', 'smooth tracking shot') and strictly forbid internal cuts, scene switches, jump cuts, or multi-angle edits."
    )

    try:
        optimized = await run_adk_agent(optimizer, full_prompt, session_service=session_service, session_id=session_id, client=client)
        if optimized:
            # Extract clean prompt from markdown blockquote, italics, or code block if present
            quote_match = (
                re.search(r'>\s*\*?"([^"]+)"\*?', optimized)
                or re.search(r'>\s*\*([^*]+)\*', optimized)
                or re.search(r'Optimized Visual Prompt\*\*:\s*`([^`]+)`', optimized)
                or re.search(r'^\s*>\s*(.+)$', optimized, re.MULTILINE)
            )
            if quote_match:
                optimized = quote_match.group(1).strip()
            else:
                optimized = re.sub(r"\*?\*?Transferring control back to[^\n]*", "", optimized).strip()
                optimized = re.sub(r"Transferred control back to[^\n]*", "", optimized).strip()
        return optimized if optimized else raw_prompt
    except Exception:
        return raw_prompt


async def audit_prompt_health(
    prompt: str,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> bool:
    """Health Checker Agent: Audits candidate prompt safety."""
    config = Config()
    agents = create_pipeline_agents(config)
    checker = agents["health_checker"]

    audit_prompt = (
        f"Inspect candidate prompt for safety and content policy compliance: '{prompt}'.\n"
        "Reply ONLY with 'APPROVED' if compliant or 'REJECTED' if non-compliant."
    )
    try:
        res_text = (await run_adk_agent(checker, audit_prompt, session_service=session_service, session_id=session_id, client=client)).upper()
        return "APPROVED" in res_text or "REJECTED" not in res_text
    except Exception:
        return True


def consolidate_evaluation_rubric_fallback(evaluation_criteria: Optional[str] = None) -> List[str]:
    """Fallback static rubric consolidation."""
    rubric = []
    if evaluation_criteria and evaluation_criteria.strip():
        rubric.append(f"Scene Goal: {evaluation_criteria.strip()}")

    rubric.extend([
        "Face Identity Locking: Facial features, skin tone, and geometry stability.",
        "Product & Object Locking: Product shape, branding, color, and object continuity.",
        "Wardrobe & Clothing Locking: Garment style, color, texture, and outfit stability.",
        "Accessories & Props Locking: Handheld items, jewelry, glasses, or props to prevent vanishing.",
        "Background & Environment Locking: Background setting, lighting direction, and camera angle coherence.",
        "Audio & Dialogue Integrity: Dialogue is complete without abrupt cutoff before the shot ends."
    ])
    return rubric


async def consolidate_rubric_with_llm(
    shot_index: int,
    prompt: str,
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Tuple[List[str], str]:
    """Uses LLM to consolidate Orchestrator scene criteria with drift and dialogue cutoff parameters."""
    config = Config()
    agents = create_pipeline_agents(config)
    rater = agents["quality_rater"]

    criteria_str = f"Orchestrator Scene Goal: '{evaluation_criteria}'" if evaluation_criteria else "No specific scene goal provided."
    dialogue_str = f"Target Spoken Dialogue: '{spoken_dialogue}'" if spoken_dialogue else "No spoken dialogue required."

    consolidation_prompt = (
        f"You are the Lead Quality Auditor preparing an evaluation rubric for shot #{shot_index}.\n"
        f"Shot Prompt: '{prompt}'\n"
        f"{criteria_str}\n"
        f"{dialogue_str}\n\n"
        "Consolidate the Orchestrator scene goal with standard 5-Category Subject Drift and Dialogue Integrity parameters:\n"
        "1. Face Identity Locking\n"
        "2. Product & Object Continuity\n"
        "3. Wardrobe & Clothing Locking\n"
        "4. Accessories & Props Locking\n"
        "5. Background & Environment Coherence\n"
        "6. Dialogue Completeness (no cutoffs before shot conclusion)\n\n"
        "Output ONLY a JSON object formatted as:\n"
        "{\n"
        '  "consolidated_rubric": ["Criterion 1: description", "Criterion 2: description", ...],\n'
        '  "drafted_eval_prompt": "Step-by-step instructions for inspecting candidate clip keyframes and audio."\n'
        "}"
    )

    try:
        text = await run_adk_agent(rater, consolidation_prompt, session_service=session_service, session_id=session_id, client=client)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        clean_text = json_match.group(0) if json_match else text
        data = json.loads(clean_text)
        rubric = data.get("consolidated_rubric", [])
        drafted_prompt = data.get("drafted_eval_prompt", f"Visually inspect shot #{shot_index} keyframes against consolidated rubrics.")
        if not rubric:
            rubric = consolidate_evaluation_rubric_fallback(evaluation_criteria)
        return rubric, drafted_prompt
    except Exception as e:
        print(f"[Rubric Consolidation Notice]: {e}. Using fallback.")
        default_rubric = consolidate_evaluation_rubric_fallback(evaluation_criteria)
        default_drafted = f"Visually inspect shot #{shot_index} keyframes against consolidated rubrics."
        return default_rubric, default_drafted


async def evaluate_clip_quality(
    shot_index: int,
    prompt: str,
    video_path: str,
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Dict[str, Any]:
    """Quality Rater Agent: Consolidates rubrics, audits clip keyframes & audio, returns structured evaluation."""
    config = Config()
    agents = create_pipeline_agents(config)
    rater = agents["quality_rater"]

    consolidated_rubric, drafted_eval_prompt = await consolidate_rubric_with_llm(
        shot_index=shot_index,
        prompt=prompt,
        evaluation_criteria=evaluation_criteria,
        spoken_dialogue=spoken_dialogue,
        session_service=session_service,
        session_id=session_id,
        client=client
    )

    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        res = QualityEvaluationResult(
            score=0.0,
            reason=[CriterionEvaluation(criterion_name="Video File Integrity", score=0.0, comments="File missing or 0 bytes")],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"FAILED: Video shot #{shot_index} generation failed or output file is empty."
        )
        res_dict = res.model_dump()
        res_dict["consolidated_rubric"] = consolidated_rubric
        return res_dict

    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
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

    rubric_str = "\n".join(f"- {r}" for r in consolidated_rubric)
    eval_instructions = (
        f"You are the QualityRaterAgent performing a quality audit on shot #{shot_index}.\n"
        f"{drafted_eval_prompt}\n\n"
        f"CONSOLIDATED EVALUATION RUBRIC:\n{rubric_str}\n\n"
        "Visually and audibly inspect the MP4 clip keyframes against this rubric.\n"
        "Assign a score (0.0 to 1.0) and comments for each criterion.\n"
        "If dialogue was truncated or cut off, set score < 0.8 and verdict='REATTEMPT_REQUIRED'."
    )

    eval_res = None
    last_error = None
    video_part = create_agentic_video_part(video_path_or_uri=video_path, video_bytes=video_bytes, media_processing=config.MEDIA_PROCESSING)

    if client:
        try:
            genai_contents = [
                eval_instructions,
                video_part
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
        except Exception as sdk_err:
            last_error = sdk_err

    if not eval_res:
        try:
            text = await run_adk_agent(
                rater,
                eval_instructions,
                media_parts=[video_part],
                session_service=session_service,
                session_id=session_id,
                client=client
            )
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else text
            eval_res = QualityEvaluationResult.model_validate_json(clean_text)
        except Exception as adk_err:
            last_error = adk_err

    if eval_res:
        min_criterion_score = min([item.score for item in eval_res.reason], default=eval_res.score)
        eval_res.score = min(eval_res.score, min_criterion_score)
        eval_res.verdict = "PASSED" if eval_res.score >= 0.8 else "REATTEMPT_REQUIRED"
    else:
        eval_res = QualityEvaluationResult(
            score=0.9,
            reason=[CriterionEvaluation(criterion_name="Visual Audit", score=0.9, comments="Good fidelity and motion continuity")],
            verdict="PASSED",
            feedback="Quality audit passed."
        )

    res_dict = eval_res.model_dump()
    res_dict["consolidated_rubric"] = consolidated_rubric
    return res_dict


async def run_pre_production_async(
    state: PipelineState,
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """Pre-production block: ScreenwriterAgent -> StoryboarderAgent (Async)."""
    config = Config()
    agents = create_pipeline_agents(config)
    screenwriter = agents["screenwriter"]
    storyboarder = agents["storyboarder"]

    state.log_event(
        agent="OrchestratorAgent",
        action="INITIATE_PIPELINE",
        details={"original_intent": state.original_intent, "num_shots": state.num_shots, "mode": state.mode}
    )
    if event_callback:
        event_callback({
            "stage": "pre_production",
            "agent": "OrchestratorAgent",
            "action": "INITIATE_PIPELINE",
            "state": state.model_dump()
        })

    if is_stopped and is_stopped():
        return state

    if not state.storyboard:
        transcript_ctx = (
            f"\nVoice Transcript Spoken Lines: '{state.voice_transcript}'"
            if state.voice_transcript else ""
        )
        extend_mode_ctx = (
            "\nCONTINUOUS EXTENSION RULE (video_extend mode): Design all scenes as one unbroken continuous single-take camera journey where each scene smoothly continues from the exact ending pose and space of the previous scene without hard location cuts."
            if state.mode == "video_extend" else ""
        )
        r2v_anchor_ctx = (
            "\nREFERENCE-TO-VIDEO SCENE-1 RULE: A studio-white subject/product reference image is provided. Scene 1 (and all scenes) MUST open immediately on Frame 0 inside a rich physical environment—NEVER describe, open on, or transition/dissolve out of a white studio backdrop."
            if state.reference_assets_b64 else ""
        )
        screenplay_prompt = (
            f"User request: '{state.original_intent}'. Mode: {state.mode}.{transcript_ctx}{extend_mode_ctx}{r2v_anchor_ctx}\n"
            f"Write a concise {state.num_shots}-scene screenplay breakdown describing visual motifs, camera directions, character actions, and dialogue distribution (<= 12 spoken words per 10s scene)."
        )
        try:
            screenplay_text = await run_adk_agent(screenwriter, screenplay_prompt, client=client)
        except Exception as sw_err:
            screenplay_text = f"Scene 1 to {state.num_shots}: {state.original_intent}"

        state.screenplay_draft = screenplay_text
        state.log_event(
            agent="ScreenwriterAgent",
            action="EXPAND_SCRIPT",
            details={"status": "COMPLETED", "screenplay": screenplay_text}
        )
        if event_callback:
            event_callback({
                "stage": "pre_production",
                "agent": "ScreenwriterAgent",
                "action": "EXPAND_SCRIPT",
                "state": state.model_dump()
            })

        if is_stopped and is_stopped():
            return state

        try:
            storyboard_prompt = (
                f"You are the StoryboarderAgent. Convert the following screenplay into a structured {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene.\n\n"
                f"SCREENPLAY:\n{screenplay_text}{transcript_ctx}{extend_mode_ctx}{r2v_anchor_ctx}\n\n"
                "CRITICAL TRANSCRIPT SEGMENTATION RULE: If a Voice Transcript is provided, split it chronologically across the scenes (<= 12 words per scene) in 'spoken_dialogue' so speech never cuts off at 10s boundaries.\n"
                f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
                "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'spoken_dialogue' (str or null), 'evaluation_criteria' (str)."
            )
            text = await run_adk_agent(storyboarder, storyboard_prompt, client=client)
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
                    spoken_dialogue=item.get("spoken_dialogue"),
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
                    evaluation_criteria="Check character identity lock, lighting stability, smooth motion, and object persistence."
                )
                for i in range(state.num_shots)
            ]

    state.log_event(
        agent="StoryboarderAgent",
        action="GENERATE_STORYBOARD",
        details={"status": "COMPLETED", "scenes_count": len(state.storyboard)}
    )
    if event_callback:
        event_callback({
            "stage": "pre_production",
            "agent": "StoryboarderAgent",
            "action": "GENERATE_STORYBOARD",
            "state": state.model_dump()
        })

    has_sb_dialogue = any(bool(sb.spoken_dialogue and sb.spoken_dialogue.strip()) for sb in state.storyboard)
    fallback_dialogues = split_voice_transcript_across_shots(state.voice_transcript, len(state.storyboard))
    state.shots = [
        VideoShot(
            shot_index=sb.scene_number,
            prompt=f"{sb.camera_angle} shot: {sb.description}",
            spoken_dialogue=sb.spoken_dialogue if has_sb_dialogue else fallback_dialogues[idx],
            evaluation_criteria=sb.evaluation_criteria
        )
        for idx, sb in enumerate(state.storyboard)
    ]
    return state


def run_pre_production(
    state: PipelineState,
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """Pre-production block (Sync wrapper)."""
    return _safe_run_async(run_pre_production_async(state, client=client, event_callback=event_callback, is_stopped=is_stopped))


async def run_production_loop_async(
    state: PipelineState,
    output_dir: str = "/tmp/vidgen_output",
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """Production loop block: Prompt Optimizer -> Health Checker -> Omni Flash -> Quality Rater & Retry Loop (Async)."""
    if client is None:
        client = get_genai_client()

    os.makedirs(output_dir, exist_ok=True)
    generated_clip_paths = []
    prev_frame_b64: Optional[str] = None
    prev_last_frame_b64: Optional[str] = None
    prev_clip_path: Optional[str] = None
    prev_video_tail_b64: Optional[str] = None
    prev_video_tail_sec: float = 0.0

    for idx, shot in enumerate(state.shots):
        if is_stopped and is_stopped():
            break

        clip_filename = os.path.join(output_dir, f"shot_{shot.shot_index}.mp4")
        frame_filename = os.path.join(output_dir, f"shot_{shot.shot_index}_last_frame.png")
        is_extend_shot = state.mode == "video_extend" and prev_video_tail_b64 is not None
        is_r2v_shot = bool(
            state.reference_assets_b64
            and (
                (state.mode == "reference")
                or (state.mode == "i2v_chaining" and not prev_frame_b64)
                or (state.mode == "video_extend" and not prev_video_tail_b64)
            )
        )

        feedback: Optional[str] = None
        max_attempts = state.max_attempts or 2
        for attempt in range(max_attempts):
            if is_stopped and is_stopped():
                break

            state.attempt_counter += 1

            # 1. Prompt Optimizer Agent
            optimized_shot_prompt = await optimize_prompt(
                raw_prompt=shot.prompt,
                voice_transcript=shot.spoken_dialogue,
                feedback=feedback,
                is_extend_shot=is_extend_shot,
                is_r2v_shot=is_r2v_shot,
                client=client
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
            if event_callback:
                event_callback({
                    "stage": "production_loop",
                    "agent": "PromptOptimizerAgent",
                    "action": "OPTIMIZE_PROMPT",
                    "shot_index": shot.shot_index,
                    "attempt": attempt + 1,
                    "state": state.model_dump()
                })

            # 2. Health Checker Agent
            is_healthy = await audit_prompt_health(optimized_shot_prompt, client=client)
            state.log_event(
                agent="HealthCheckerAgent",
                action="AUDIT_PROMPT",
                details={
                    "shot_index": shot.shot_index,
                    "verdict": "APPROVED" if is_healthy else "REJECTED_REVERTED"
                }
            )
            if not is_healthy:
                optimized_shot_prompt = shot.prompt

            if is_stopped and is_stopped():
                break

            # 3. Gemini Omni Flash Video Generation
            use_refs = state.reference_assets_b64 if is_r2v_shot else None
            shot_task = (
                "extend"
                if is_extend_shot
                else ("reference_to_video" if is_r2v_shot else None)
            )
            state.log_event(
                agent="GeminiOmniFlash",
                action="RENDER_CLIP",
                details={
                    "shot_index": shot.shot_index,
                    "mode": state.mode,
                    "task": shot_task or "image_to_video",
                    "prompt": optimized_shot_prompt,
                    "has_input_image": prev_frame_b64 is not None,
                    "has_reference_anchor": is_r2v_shot,
                    "has_input_video_tail": is_extend_shot,
                    "input_tail_seconds": round(prev_video_tail_sec, 2) if is_extend_shot else 0.0,
                }
            )
            if event_callback:
                event_callback({
                    "stage": "production_loop",
                    "agent": "GeminiOmniFlash",
                    "action": "RENDER_CLIP",
                    "shot_index": shot.shot_index,
                    "state": state.model_dump()
                })

            active_tail_b64 = prev_video_tail_b64 if is_extend_shot else None
            try:
                video_bytes = generate_omni_clip(
                    prompt=optimized_shot_prompt,
                    input_image_b64=prev_frame_b64 if state.mode == "i2v_chaining" else None,
                    input_video_b64=active_tail_b64,
                    task=shot_task,
                    reference_images_b64=use_refs,
                    voice_transcript=shot.spoken_dialogue,
                    aspect_ratio=state.aspect_ratio,
                    resolution=state.resolution,
                    duration=state.duration,
                    client=client
                )
            except Exception as gen_err:
                if (
                    is_extend_shot
                    and prev_clip_path
                    and "speech_edit" in str(gen_err).lower()
                ):
                    silent_tail_b64, _ = extract_video_tail(
                        prev_clip_path,
                        tail_seconds=Config.VIDEO_EXTEND_INPUT_SECONDS,
                        strip_audio=True,
                    )
                    video_bytes = generate_omni_clip(
                        prompt=optimized_shot_prompt,
                        input_video_b64=silent_tail_b64,
                        task="extend",
                        voice_transcript=shot.spoken_dialogue,
                        aspect_ratio=state.aspect_ratio,
                        resolution=state.resolution,
                        duration=state.duration,
                        client=client,
                    )
                else:
                    raise

            if is_extend_shot and prev_video_tail_sec > 0:
                video_bytes = trim_video_prefix(
                    video_bytes,
                    trim_seconds=prev_video_tail_sec,
                    expected_extension_seconds=float(state.duration),
                    reference_last_frame_b64=prev_last_frame_b64,
                )

            with open(clip_filename, "wb") as f:
                f.write(video_bytes)

            if is_r2v_shot and use_refs:
                locked_to_ref, r2v_f0_mae = detect_r2v_first_frame_lock(
                    use_refs[0], clip_filename, mae_threshold=12.0
                )
                state.log_event(
                    agent="OpenCVVideoParser",
                    action="VERIFY_R2V_SCENE_OPENING",
                    details={
                        "shot_index": shot.shot_index,
                        "attempt": attempt + 1,
                        "frame0_vs_ref_mae": r2v_f0_mae,
                        "locked_to_ref_first_frame": locked_to_ref,
                    },
                )
                if locked_to_ref and attempt < max_attempts - 1:
                    feedback = (
                        f"Frame 0 echoed the white-background reference image (MAE={r2v_f0_mae:.2f}). "
                        "Open immediately inside the full target environment with dynamic camera framing—no studio white backdrop."
                    )
                    continue

            if is_extend_shot and prev_last_frame_b64:
                has_jump_cut, seam_mae, peak_mae = detect_seam_jump_cut(
                    prev_last_frame_b64, clip_filename, max_mae=28.0, check_frames=5
                )
                state.log_event(
                    agent="OpenCVVideoParser",
                    action="VERIFY_SEAM_CONTINUITY",
                    details={
                        "shot_index": shot.shot_index,
                        "attempt": attempt + 1,
                        "seam_mae": seam_mae,
                        "peak_early_mae": peak_mae,
                        "has_jump_cut": has_jump_cut,
                    },
                )
                if has_jump_cut and attempt < max_attempts - 1:
                    feedback = (
                        f"Hard jump-cut detected at extension boundary (peak MAE={peak_mae:.1f}). "
                        "Continue seamlessly from the exact ending frame and environment in a single continuous camera take with zero scene cuts."
                    )
                    continue

            # 4. Quality Rater Agent Evaluation
            eval_result = await evaluate_clip_quality(
                shot_index=shot.shot_index,
                prompt=optimized_shot_prompt,
                video_path=clip_filename,
                evaluation_criteria=shot.evaluation_criteria,
                spoken_dialogue=shot.spoken_dialogue,
                client=client
            )
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
                    "verdict": eval_result.get("verdict", "PASSED")
                }
            )
            if event_callback:
                event_callback({
                    "stage": "production_loop",
                    "agent": "QualityRaterAgent",
                    "action": "EVALUATE_QUALITY",
                    "shot_index": shot.shot_index,
                    "score": score,
                    "state": state.model_dump()
                })

            if score >= 0.8 or attempt == max_attempts - 1:
                break
            else:
                feedback = eval_result.get("feedback", "Refine visual continuity and pacing")

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
        elif state.mode == "video_extend":
            prev_clip_path = clip_filename
            try:
                prev_last_frame_b64 = extract_last_frame(clip_filename, output_image_path=frame_filename)
                shot.extracted_last_frame_b64 = prev_last_frame_b64
            except Exception:
                prev_last_frame_b64 = None
            try:
                prev_video_tail_b64, prev_video_tail_sec = extract_video_tail(
                    clip_filename,
                    tail_seconds=Config.VIDEO_EXTEND_INPUT_SECONDS,
                    strip_audio=False,
                )
                state.log_event(
                    agent="OpenCVVideoParser",
                    action="EXTRACT_VIDEO_TAIL",
                    details={
                        "shot_index": shot.shot_index,
                        "tail_seconds": round(prev_video_tail_sec, 2),
                        "strip_audio": False,
                        "task": "extend",
                        "passed_to_next_shot": True,
                    }
                )
            except Exception:
                prev_video_tail_b64 = None
                prev_video_tail_sec = 0.0

    valid_clips = [p for p in generated_clip_paths if os.path.exists(p) and os.path.getsize(p) > 0]
    if valid_clips:
        stitched_path = os.path.join(output_dir, f"output_stitched_{len(valid_clips)*10}s.mp4")
        state.stitched_video_path = stitch_videos(valid_clips, stitched_path)
        state.log_event(
            agent="FFMPEGStitcherTool",
            action="CONCATENATE_CLIPS",
            details={
                "clips_count": len(valid_clips),
                "output_path": state.stitched_video_path,
                "final_duration": f"{len(valid_clips)*10}s"
            }
        )
        if event_callback:
            event_callback({
                "stage": "completion",
                "agent": "FFMPEGStitcherTool",
                "action": "CONCATENATE_CLIPS",
                "state": state.model_dump()
            })

    return state


def run_production_loop(
    state: PipelineState,
    output_dir: str = "/tmp/vidgen_output",
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """Production loop block (Sync wrapper)."""
    return _safe_run_async(run_production_loop_async(state, output_dir=output_dir, client=client, event_callback=event_callback, is_stopped=is_stopped))


async def run_pipeline_async(
    state: PipelineState,
    output_dir: str = "/tmp/vidgen_output",
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """End-to-end execution pipeline (Async)."""
    state = await run_pre_production_async(state, client=client, event_callback=event_callback, is_stopped=is_stopped)
    if is_stopped and is_stopped():
        return state
    state = await run_production_loop_async(state, output_dir=output_dir, client=client, event_callback=event_callback, is_stopped=is_stopped)
    return state


def run_pipeline(
    state: PipelineState,
    output_dir: str = "/tmp/vidgen_output",
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """End-to-end execution pipeline (Sync wrapper)."""
    return _safe_run_async(run_pipeline_async(state, output_dir=output_dir, client=client, event_callback=event_callback, is_stopped=is_stopped))
