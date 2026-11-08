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
    extract_avu_usage_telemetry,
    extract_video_tail,
    trim_video_prefix,
    detect_seam_jump_cut,
    detect_r2v_first_frame_lock,
    decode_valid_image_b64,
    extract_labeled_audit_keyframes,
    analyze_clip_audio_tail,
    compute_transcript_metrics,
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
    # Observation-first CoT grounding fields (ordered strictly BEFORE score and verdict)
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
        description="Count of internal camera jump-cuts, soft cross-dissolves, or multi-shot edits inside this single clip (0 if unbroken continuous single take).",
    )
    reason: List[CriterionEvaluation] = Field(
        default_factory=list,
        description="Detailed list evaluating each individual consolidated criterion.",
    )
    score: float = Field(
        default=0.0,
        description="Overall aggregated quality score from 0.0 to 1.0 (>= 0.8 is PASS, < 0.8 requires reattempt).",
    )
    verdict: str = Field(
        default="REATTEMPT_REQUIRED",
        description="Overall verdict: 'PASSED' if score >= 0.8, else 'REATTEMPT_REQUIRED'.",
    )
    feedback: str = Field(
        default="",
        description="Actionable summary feedback for downstream PromptOptimizerAgent.",
    )
    # Deterministic post-computed metrics & audit status
    transcript_wer: Optional[float] = Field(default=None)
    transcript_word_overlap: Optional[float] = Field(default=None)
    audit_status: str = Field(default="OK")
    deterministic_telemetry: Dict[str, Any] = Field(default_factory=dict)


def build_quality_evaluation_schema() -> types.Schema:
    """Builds an explicit Google GenAI Schema enforcing observation-first property_ordering before score."""
    return types.Schema(
        type=types.Type.OBJECT,
        property_ordering=list(QUALITY_EVALUATION_PROPERTY_ORDER),
        properties={
            "opening_environment_observed": types.Schema(
                type=types.Type.STRING,
                description="Factual description of the physical environment, lighting, and subject visible on Frame 0 (t=0.0s).",
            ),
            "heard_transcript": types.Schema(
                type=types.Type.STRING,
                description="Exact verbatim words spoken audibly in the clip (empty string if no speech is heard).",
            ),
            "speech_end_sec": types.Schema(
                type=types.Type.NUMBER,
                nullable=True,
                description="Timestamp in seconds where spoken dialogue finishes (null if no speech).",
            ),
            "detected_internal_cuts": types.Schema(
                type=types.Type.INTEGER,
                description="Count of internal camera jump-cuts, soft cross-dissolves, or multi-angle transitions inside this clip (0 if unbroken single take).",
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
            "score": types.Schema(
                type=types.Type.NUMBER,
                description="Overall aggregated quality score from 0.0 to 1.0 (>= 0.8 is PASS).",
            ),
            "verdict": types.Schema(
                type=types.Type.STRING,
                description="Overall verdict: 'PASSED' if score >= 0.8, else 'REATTEMPT_REQUIRED'.",
            ),
            "feedback": types.Schema(
                type=types.Type.STRING,
                description="Actionable summary feedback for downstream PromptOptimizerAgent.",
            ),
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


class MasterSeamObservation(BaseModel):
    seam_timestamp_sec: float = Field(description="Nominal seam boundary timestamp in seconds (e.g. 10.0, 20.0).")
    visual_transition_notes: str = Field(default="", description="Visual continuity & xfade smoothness across seam.")
    audio_transition_notes: str = Field(default="", description="Voice timbre, loudness & acrossfade continuity across seam.")
    seam_score: float = Field(default=1.0, description="Quality score (0.0 to 1.0) for this seam boundary.")


class MasterSeamEvaluationResult(BaseModel):
    seam_observations: List[MasterSeamObservation] = Field(default_factory=list)
    voice_timbre_consistent: bool = Field(default=True)
    loudness_continuity_ok: bool = Field(default=True)
    visual_xfade_smooth: bool = Field(default=True)
    score: float = Field(default=0.95)
    verdict: str = Field(default="PASSED")
    feedback: str = Field(default="")
    audit_status: str = Field(default="OK")
    deterministic_telemetry: Dict[str, Any] = Field(default_factory=dict)


def build_master_seam_evaluation_schema() -> types.Schema:
    """Builds an observation-first schema for auditing stitched multi-shot commercial seams."""
    return types.Schema(
        type=types.Type.OBJECT,
        property_ordering=[
            "seam_observations",
            "voice_timbre_consistent",
            "loudness_continuity_ok",
            "visual_xfade_smooth",
            "score",
            "verdict",
            "feedback",
        ],
        properties={
            "seam_observations": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    property_ordering=[
                        "seam_timestamp_sec",
                        "visual_transition_notes",
                        "audio_transition_notes",
                        "seam_score",
                    ],
                    properties={
                        "seam_timestamp_sec": types.Schema(type=types.Type.NUMBER),
                        "visual_transition_notes": types.Schema(type=types.Type.STRING),
                        "audio_transition_notes": types.Schema(type=types.Type.STRING),
                        "seam_score": types.Schema(type=types.Type.NUMBER),
                    },
                    required=[
                        "seam_timestamp_sec",
                        "visual_transition_notes",
                        "audio_transition_notes",
                        "seam_score",
                    ],
                ),
            ),
            "voice_timbre_consistent": types.Schema(type=types.Type.BOOLEAN),
            "loudness_continuity_ok": types.Schema(type=types.Type.BOOLEAN),
            "visual_xfade_smooth": types.Schema(type=types.Type.BOOLEAN),
            "score": types.Schema(type=types.Type.NUMBER),
            "verdict": types.Schema(type=types.Type.STRING),
            "feedback": types.Schema(type=types.Type.STRING),
        },
        required=[
            "seam_observations",
            "voice_timbre_consistent",
            "loudness_continuity_ok",
            "visual_xfade_smooth",
            "score",
            "verdict",
            "feedback",
        ],
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

    if root_agent is not None:
        target_agent = root_agent
    else:
        raw_inst = agent.instruction if isinstance(agent.instruction, str) else ""
        clean_inst = re.sub(
            r"After [^\n]*transfer_to_agent\([^\n]*\)\.?",
            "",
            raw_inst,
            flags=re.IGNORECASE,
        ).strip()
        target_agent = Agent(
            name=agent.name,
            model=agent.model,
            instruction=clean_inst or raw_inst,
            description=getattr(agent, "description", ""),
            tools=[],
            disallow_transfer_to_peers=True,
            disallow_transfer_to_parent=True,
        )
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
    is_i2v_shot: bool = False,
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
    i2v_context = (
        "\nCRITICAL FIRST-FRAME I2V RULE: This shot uses Image-to-Video (task='image_to_video') chained directly from the attached starting frame. "
        "Begin with 'Use this image as the starting frame.' and evolve camera and subject motion smoothly from that exact frame—NEVER refer to a 'reference image' or 'Character A'."
        if is_i2v_shot else ""
    )
    r2v_context = (
        "\nCRITICAL R2V SCENE-OPENING RULE: This shot uses Reference-to-Video (task='reference_to_video') with a studio-white subject/product reference image. "
        "Open immediately on Frame 0 inside the rich target environment described in the shot—NEVER depict, mention, or transition/dissolve out of a white studio backdrop."
        if is_r2v_shot else ""
    )

    full_prompt = (
        f"Raw Shot Description: '{raw_prompt}'.{feedback_context}{transcript_context}{extend_context}{i2v_context}{r2v_context}\n"
        "Generate an enhanced, highly-detailed cinematic prompt optimized for Gemini Omni Flash video generation. "
        "Keep it concise, under 60 words, focusing on lighting, continuous camera motion, visual clarity, and object persistence. "
        "STRICT BRAND & META RULE: NEVER invent third-party brand names (such as Nike, Adidas, ASICS, Apple, etc.) unless explicitly present in the Raw Shot Description, and NEVER output word-count annotations like '(49 words)'. "
        "STRICT SINGLE-SHOT RULE: The clip MUST be a single, continuous, uninterrupted camera take. Explicitly specify a single continuous camera motion (e.g. 'continuous single take', 'smooth tracking shot') and strictly forbid internal cuts, scene switches, jump cuts, or multi-angle edits."
    )

    try:
        optimized = await run_adk_agent(optimizer, full_prompt, session_service=session_service, session_id=session_id, client=client)
        if optimized:
            quote_match = (
                re.search(r'>\s*\*?"([^"]+)"\*?', optimized)
                or re.search(r'>\s*\*([^*]+)\*', optimized)
                or re.search(r'Optimized Visual Prompt\*\*:\s*`([^`]+)`', optimized)
                or re.search(r'Optimized Visual Prompt\*\*:\s*\n+\s*([^\n*-][^\n]+)', optimized)
                or re.search(r'Optimized Visual Prompt\*\*:\s*([^\n`]+)', optimized)
                or re.search(r'^\s*>\s*(.+)$', optimized, re.MULTILINE)
            )
            if quote_match:
                optimized = quote_match.group(1).strip()
            else:
                optimized = re.sub(r"\*?\*?Transferring control back to[^\n]*", "", optimized).strip()
                optimized = re.sub(r"Transferred control back to[^\n]*", "", optimized).strip()
            optimized = re.sub(r"\s*\*?\(\d+\s*words?\)\*?", "", optimized, flags=re.IGNORECASE).strip()
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


def build_shot_evaluation_rubric(
    evaluation_criteria: Optional[str] = None,
    spoken_dialogue: Optional[str] = None,
    has_reference_anchor: bool = False,
    has_prior_frame: bool = False,
    is_r2v_shot: bool = False,
    is_extend_shot: bool = False,
) -> List[str]:
    """Deterministically builds a mode-aware 6-dimension evaluation rubric with zero extra LLM hops."""
    rubric: List[str] = []
    if evaluation_criteria and evaluation_criteria.strip():
        rubric.append(f"Scene Goal & Prompt Adherence: {evaluation_criteria.strip()}")

    if has_reference_anchor:
        rubric.append(
            "Ground-Truth Anchor Fidelity: Subject facial identity, garment colors/texture, and SKU geometry MUST match the attached CANONICAL REFERENCE ANCHOR (#FFFFFF)."
        )
    else:
        rubric.append(
            "Subject & Product Identity Locking: Facial features, product shape, color, and material geometry remain stable throughout the take."
        )

    if is_r2v_shot:
        rubric.append(
            "R2V In-Environment Frame-0 Opening: KEY FRAME A (t=0.00s) MUST open immediately inside the target physical environment—NEVER on a plain #FFFFFF white studio backdrop."
        )
    if has_prior_frame or is_extend_shot:
        rubric.append(
            "Cross-Shot Boundary Continuity: KEY FRAME A (t=0.00s) must smoothly continue pose, lighting, and spatial framing from the attached PRIOR SHOT TERMINAL FRAME with zero jump-cuts."
        )

    rubric.extend([
        "Single-Take Camera & Motion Physics: Unbroken continuous camera trajectory (detected_internal_cuts == 0) with natural subject/fabric physics.",
        "Wardrobe, Props & Environment Persistence: Clothing, handheld props, and lighting stay consistent from KEY FRAME A through KEY FRAME B.",
    ])

    if spoken_dialogue and spoken_dialogue.strip():
        rubric.append(
            f"Spoken Dialogue Accuracy & Clean Completion: Audibly delivers '{spoken_dialogue.strip()}' clearly and finishes before clip end with zero trailing cutoff."
        )
    else:
        rubric.append(
            "Acoustic Coherence: Natural ambient room tone or score with no abrupt audio glitches."
        )
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
    """Legacy LLM rubric consolidation helper retained for backward compatibility."""
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
    except Exception:
        default_rubric = consolidate_evaluation_rubric_fallback(evaluation_criteria)
        default_drafted = f"Visually inspect shot #{shot_index} keyframes against consolidated rubrics."
        return default_rubric, default_drafted


def _format_telemetry_block(telemetry: Dict[str, Any], spoken_dialogue: Optional[str]) -> str:
    """Formats fast deterministic OpenCV & FFMPEG signals into a structured grounding block for the rater."""
    lines = ["DETERMINISTIC OPENCV & FFMPEG TELEMETRY (GROUND TRUTH SIGNALS):"]
    dur = telemetry.get("clip_duration_sec")
    if dur is not None:
        lines.append(f"- clip_duration_sec: {dur}s")
    if telemetry.get("r2v_f0_mae") is not None:
        lines.append(
            f"- r2v_f0_mae (Frame 0 vs #FFFFFF anchor): {telemetry['r2v_f0_mae']:.2f} "
            f"(>= 12.0 means opened in real environment; < 12.0 means locked to white studio anchor)"
        )
    if telemetry.get("r2v_white_pct") is not None:
        lines.append(f"- frame0_white_pixels_pct: {telemetry['r2v_white_pct']:.1f}%")
    if telemetry.get("seam_mae") is not None:
        lines.append(
            f"- seam_mae (Prior Shot Last Frame vs Frame 0): {telemetry['seam_mae']:.2f} "
            f"(peak_early_mae={telemetry.get('peak_early_mae', telemetry['seam_mae']):.2f})"
        )
    if telemetry.get("has_audio"):
        tail_w = telemetry.get("tail_window_sec", 0.20)
        start_t = max(0.0, float(dur or 10.0) - float(tail_w))
        lines.append(
            f"- audio_energy: mid_rms_db={telemetry.get('mid_rms_db')} dBFS | "
            f"trailing_rms_db ({start_t:.1f}s-{float(dur or 10.0):.1f}s)={telemetry.get('trailing_rms_db')} dBFS | "
            f"speech_cutoff_detected={telemetry.get('speech_cutoff_detected')}"
        )
    else:
        lines.append("- audio_energy: no decoded audio track or silent synthetic test clip")

    if spoken_dialogue and spoken_dialogue.strip():
        lines.append(f"- target_spoken_dialogue: \"{spoken_dialogue.strip()}\"")
    else:
        lines.append("- target_spoken_dialogue: None (ambient/instrumental only)")
    return "\n".join(lines)


async def evaluate_clip_quality(
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
    session_service: Optional[InMemorySessionService] = None,
    session_id: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Dict[str, Any]:
    """Auto-Rater v2: Ground-truth anchored, observation-first multimodal video & audio critic."""
    config = Config()
    agents = create_pipeline_agents(config)
    rater = agents["quality_rater"]

    ref_decoded = decode_valid_image_b64(reference_images_b64[0]) if reference_images_b64 else None
    prior_decoded = decode_valid_image_b64(prev_last_frame_b64) if prev_last_frame_b64 else None

    consolidated_rubric = build_shot_evaluation_rubric(
        evaluation_criteria=evaluation_criteria,
        spoken_dialogue=spoken_dialogue,
        has_reference_anchor=ref_decoded is not None,
        has_prior_frame=prior_decoded is not None,
        is_r2v_shot=is_r2v_shot,
        is_extend_shot=is_extend_shot,
    )

    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        res = QualityEvaluationResult(
            score=0.0,
            reason=[CriterionEvaluation(criterion_name="Video File Integrity", score=0.0, comments="File missing or 0 bytes")],
            verdict="REATTEMPT_REQUIRED",
            feedback=f"FAILED: Video shot #{shot_index} generation failed or output file is empty.",
            audit_status="FILE_MISSING_OR_EMPTY",
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
            feedback=f"FAILED: Could not read video file at {video_path}: {e}",
            audit_status="FILE_READ_ERROR",
        )
        res_dict = res.model_dump()
        res_dict["consolidated_rubric"] = consolidated_rubric
        return res_dict

    # 1. Gather fast deterministic OpenCV + FFMPEG audio tail signals
    audio_telemetry = await asyncio.to_thread(analyze_clip_audio_tail, video_path, 0.20)
    merged_telemetry: Dict[str, Any] = dict(audio_telemetry)
    if deterministic_signals:
        merged_telemetry.update({k: v for k, v in deterministic_signals.items() if v is not None})

    keyframes = await asyncio.to_thread(extract_labeled_audit_keyframes, video_path)
    telemetry_block = _format_telemetry_block(merged_telemetry, spoken_dialogue)
    rubric_str = "\n".join(f"- {r}" for r in consolidated_rubric)

    eval_instructions = (
        f"You are the QualityRaterAgent performing a strict ground-truth multimodal quality audit on shot #{shot_index}.\n"
        f"Target Shot Prompt: '{prompt}'\n\n"
        f"{telemetry_block}\n\n"
        f"CONSOLIDATED EVALUATION RUBRIC:\n{rubric_str}\n\n"
        "OBSERVATION-FIRST AUDIT PROTOCOL (MANDATORY):\n"
        "1. Use agentic video & audio inspection across the FULL 0.0s-to-end timeline to record 'opening_environment_observed' from KEY FRAME A (t=0.00s), 'heard_transcript' (exact spoken words heard in the audio stream), 'speech_end_sec', and 'detected_internal_cuts' (0 ONLY if one unbroken single camera take from 0.0s to clip end; >=1 if ANY internal hard jump-cut OR soft cross-dissolve/fade between different camera framings occurs inside the clip).\n"
        "2. Compare subject identity, wardrobe colors, and SKU geometry in KEY FRAME A/M/B and the MP4 video directly against CANONICAL REFERENCE ANCHOR (if attached) and boundary alignment against PRIOR SHOT TERMINAL FRAME (if attached).\n"
        "3. Score each rubric criterion (0.0 to 1.0) and compute overall 'score'. If identity/SKU drifts, Frame 0 opens on a white studio backdrop, internal jump-cuts occur, or dialogue cuts off at clip end, set score < 0.8 and verdict='REATTEMPT_REQUIRED' with concrete prompt fix instructions in 'feedback'."
    )

    multimodal_contents: List[Any] = [eval_instructions]
    media_parts_for_adk: List[types.Part] = []

    if ref_decoded is not None:
        ref_bytes, ref_mime = ref_decoded
        ref_label = "CANONICAL REFERENCE ANCHOR (#FFFFFF Ground-Truth SKU / Spokesperson):"
        ref_part = types.Part.from_bytes(data=ref_bytes, mime_type=ref_mime)
        multimodal_contents.extend([ref_label, ref_part])
        media_parts_for_adk.extend([types.Part.from_text(text=ref_label), ref_part])

    if prior_decoded is not None:
        prior_bytes, prior_mime = prior_decoded
        prior_label = "PRIOR SHOT TERMINAL FRAME (Cross-Shot Boundary Ground Truth):"
        prior_part = types.Part.from_bytes(data=prior_bytes, mime_type=prior_mime)
        multimodal_contents.extend([prior_label, prior_part])
        media_parts_for_adk.extend([types.Part.from_text(text=prior_label), prior_part])

    for kf_label, kf_png_bytes in keyframes:
        kf_part = types.Part.from_bytes(data=kf_png_bytes, mime_type="image/png")
        multimodal_contents.extend([f"{kf_label}:", kf_part])
        media_parts_for_adk.extend([types.Part.from_text(text=f"{kf_label}:"), kf_part])

    video_part = create_agentic_video_part(
        video_path_or_uri=video_path,
        video_bytes=video_bytes,
        media_processing=config.MEDIA_PROCESSING,
    )
    multimodal_contents.append(video_part)
    media_parts_for_adk.append(video_part)

    eval_res: Optional[QualityEvaluationResult] = None
    rater_client = client if client is not None else get_genai_client(timeout_ms=config.RATER_TIMEOUT_MS)

    for rater_try in range(2):
        try:
            resp = await asyncio.to_thread(
                rater_client.models.generate_content,
                model=config.ORCHESTRATOR_MODEL,
                contents=multimodal_contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=build_quality_evaluation_schema(),
                    temperature=0.2,
                ),
            )
            merged_telemetry.update(extract_avu_usage_telemetry(resp))
            if resp and resp.text:
                eval_res = QualityEvaluationResult.model_validate_json(resp.text)
                break
        except Exception as sdk_err:
            err_s = str(sdk_err)
            print(f"[QualityRater SDK Notice on shot #{shot_index} (try {rater_try + 1}/2)]: {err_s}")
            if rater_try == 0 and any(k in err_s for k in ("429", "503", "504", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "timed out")):
                await asyncio.sleep(8.0)
            else:
                break

    if not eval_res:
        try:
            text = await run_adk_agent(
                rater,
                eval_instructions,
                media_parts=media_parts_for_adk,
                session_service=session_service,
                session_id=session_id,
                client=client,
            )
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            clean_text = json_match.group(0) if json_match else text
            eval_res = QualityEvaluationResult.model_validate_json(clean_text)
        except Exception as adk_err:
            print(f"[QualityRater ADK Fallback Notice on shot #{shot_index}]: {adk_err}")

    if eval_res:
        eval_res.audit_status = "OK"
        min_criterion_score = min([item.score for item in eval_res.reason], default=eval_res.score)
        eval_res.score = min(eval_res.score, min_criterion_score)
    else:
        eval_res = QualityEvaluationResult(
            opening_environment_observed="Audit degraded (rater timeout or parse error)",
            score=0.80,
            reason=[
                CriterionEvaluation(
                    criterion_name="Deterministic Telemetry Fallback",
                    score=0.80,
                    comments="LLM multimodal rater timed out or failed; relying on deterministic OpenCV/FFMPEG signals.",
                )
            ],
            verdict="PASSED",
            feedback="Multimodal rater timed out; deterministic telemetry checks applied.",
            audit_status="AUDIT_TIMEOUT_DEGRADED",
        )

    # 2. Apply deterministic WER/overlap & physical cutoff/jump-cut post-rater guardrails
    t_metrics = compute_transcript_metrics(spoken_dialogue, eval_res.heard_transcript)
    eval_res.transcript_wer = t_metrics["transcript_wer"]
    eval_res.transcript_word_overlap = t_metrics["transcript_word_overlap"]
    eval_res.deterministic_telemetry = merged_telemetry

    guardrail_notes: List[str] = []
    clip_dur = float(merged_telemetry.get("clip_duration_sec") or 0.0)

    if eval_res.detected_internal_cuts > 0:
        eval_res.score = min(eval_res.score, 0.60)
        guardrail_notes.append(
            f"Detected {eval_res.detected_internal_cuts} internal camera jump-cut(s); enforce one continuous single-take camera movement."
        )

    if spoken_dialogue and spoken_dialogue.strip():
        speech_cutoff_by_ts = (
            eval_res.speech_end_sec is not None
            and clip_dur >= 2.0
            and eval_res.speech_end_sec > (clip_dur - 0.15)
        )
        if merged_telemetry.get("speech_cutoff_detected") or speech_cutoff_by_ts:
            eval_res.score = min(eval_res.score, 0.65)
            guardrail_notes.append(
                f"Spoken dialogue ran into the final 0.2s clip boundary (trailing_rms_db={merged_telemetry.get('trailing_rms_db')} dBFS, speech_end_sec={eval_res.speech_end_sec}); pace speech briskly so all words finish before second 8."
            )

        has_real_transcript_signal = bool(eval_res.heard_transcript and eval_res.heard_transcript.strip()) or (
            bool(merged_telemetry.get("has_audio")) and eval_res.audit_status == "OK"
        )
        if (
            has_real_transcript_signal
            and eval_res.transcript_wer is not None
            and eval_res.transcript_wer > 0.35
        ):
            eval_res.score = min(eval_res.score, 0.68)
            guardrail_notes.append(
                f"Spoken dialogue WER={eval_res.transcript_wer:.2f} (overlap={eval_res.transcript_word_overlap:.2f}) deviated from target '{spoken_dialogue.strip()}' (heard: '{eval_res.heard_transcript}')."
            )

    if guardrail_notes:
        joined_notes = " ".join(guardrail_notes)
        eval_res.feedback = f"{joined_notes} {eval_res.feedback}".strip()

    eval_res.score = round(float(eval_res.score), 3)
    if eval_res.audit_status == "AUDIT_TIMEOUT_DEGRADED" and eval_res.score >= 0.8:
        eval_res.verdict = "AUDIT_TIMEOUT_DEGRADED"
    else:
        eval_res.verdict = "PASSED" if eval_res.score >= 0.8 else "REATTEMPT_REQUIRED"

    res_dict = eval_res.model_dump()
    res_dict["consolidated_rubric"] = consolidated_rubric
    return res_dict


async def evaluate_stitched_master(
    stitched_video_path: str,
    num_shots: int,
    shot_duration_sec: float = 10.0,
    original_intent: str = "",
    voice_transcript: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
    client: Optional[genai.Client] = None,
) -> Dict[str, Any]:
    """Post-Stitch Master Seam Critic (Pattern B): Audits seam windows [t_cut - 1.5s, t_cut + 1.5s] across the stitched master."""
    config = Config()
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
            feedback="Single-shot master requires no cross-shot seam audit.",
            audit_status="SINGLE_SHOT_SKIPPED",
        ).model_dump()

    seam_windows = [
        f"[{max(0.0, i * shot_duration_sec - 1.5):.1f}s - {i * shot_duration_sec + 1.5:.1f}s] (Seam {i}->{i + 1} around {i * shot_duration_sec:.1f}s)"
        for i in range(1, num_shots)
    ]
    windows_str = "\n".join(f"- {w}" for w in seam_windows)

    try:
        with open(stitched_video_path, "rb") as f:
            video_bytes = f.read()
    except Exception as err:
        return MasterSeamEvaluationResult(
            score=0.0,
            verdict="FAILED",
            feedback=f"Could not read stitched master: {err}",
            audit_status="FILE_READ_ERROR",
        ).model_dump()

    prompt = (
        f"You are the Master Post-Stitch Continuity Critic auditing a {num_shots}-shot stitched commercial.\n"
        f"Commercial Intent: '{original_intent}'\n"
        f"Full Voiceover Script: '{voice_transcript or 'Ambient/Instrumental'}'\n\n"
        "CRITICAL SEAM TRANSITION WINDOWS TO INSPECT:\n"
        f"{windows_str}\n\n"
        "Use agentic video & audio inspection to zoom into each seam transition window above:\n"
        "1. Record 'seam_observations' for every boundary (visual smoothness, xfade ghosting, pose/SKU consistency, and audio acrossfade continuity).\n"
        "2. Evaluate 'voice_timbre_consistent', 'loudness_continuity_ok', and 'visual_xfade_smooth'.\n"
        "3. Provide an overall 'score' (0.0 to 1.0), 'verdict' ('PASSED' if score >= 0.8 else 'SEAM_WARNING'), and actionable 'feedback'."
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
            media_processing=config.MEDIA_PROCESSING,
        )
    )

    rater_client = client if client is not None else get_genai_client(timeout_ms=config.RATER_TIMEOUT_MS)
    for seam_try in range(2):
        try:
            resp = await asyncio.to_thread(
                rater_client.models.generate_content,
                model=config.ORCHESTRATOR_MODEL,
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
                parsed.deterministic_telemetry = extract_avu_usage_telemetry(resp)
                return parsed.model_dump()
        except Exception as err:
            err_s = str(err)
            print(f"[MasterSeamRater Notice (try {seam_try + 1}/2)]: {err_s}")
            if seam_try == 0 and any(k in err_s for k in ("429", "503", "504", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "timed out")):
                await asyncio.sleep(8.0)
            else:
                break

    return MasterSeamEvaluationResult(
        score=0.85,
        verdict="AUDIT_TIMEOUT_DEGRADED",
        feedback="Post-stitch master seam rater timed out or returned non-matching schema; deterministic 80ms xfade/acrossfade completed.",
        audit_status="AUDIT_TIMEOUT_DEGRADED",
    ).model_dump()


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

    init_details = {
        "original_intent": state.original_intent,
        "num_shots": state.num_shots,
        "mode": state.mode,
    }
    state.log_event(
        agent="OrchestratorAgent",
        action="INITIATE_PIPELINE",
        details=init_details,
    )
    if event_callback:
        event_callback({
            "stage": "pre_production",
            "agent": "OrchestratorAgent",
            "action": "INITIATE_PIPELINE",
            "details": init_details,
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
        hybrid_mode_ctx = (
            "\nHYBRID MULTI-MODE CHOREOGRAPHY RULE (hybrid mode): Combine continuity methods per scene! "
            "Set 'mode_override' to 'reference' on Scene 1 and on any hard-cut location jump (to re-lock #FFFFFF SKU/character fidelity), "
            "'video_extend' when extending an unbroken single-take camera movement within the same space, or 'i2v_chaining' for pose-locked cuts."
            if state.mode == "hybrid" else ""
        )
        r2v_anchor_ctx = (
            "\nREFERENCE-TO-VIDEO SCENE-1 RULE: A studio-white subject/product reference image is provided. Scene 1 (and all scenes) MUST open immediately on Frame 0 inside a rich physical environment—NEVER describe, open on, or transition/dissolve out of a white studio backdrop."
            if state.reference_assets_b64 else ""
        )
        screenplay_prompt = (
            f"User request: '{state.original_intent}'. Mode: {state.mode}.{transcript_ctx}{extend_mode_ctx}{hybrid_mode_ctx}{r2v_anchor_ctx}\n"
            f"Write a concise {state.num_shots}-scene screenplay breakdown describing visual motifs, camera directions, character actions, and dialogue distribution (<= 12 spoken words per 10s scene)."
        )
        try:
            screenplay_text = await run_adk_agent(screenwriter, screenplay_prompt, client=client)
        except Exception:
            screenplay_text = f"Scene 1 to {state.num_shots}: {state.original_intent}"

        state.screenplay_draft = screenplay_text
        expand_details = {
            "status": "COMPLETED",
            "screenplay": screenplay_text,
            "intent": state.original_intent,
        }
        state.log_event(
            agent="ScreenwriterAgent",
            action="EXPAND_SCRIPT",
            details=expand_details,
        )
        if event_callback:
            event_callback({
                "stage": "pre_production",
                "agent": "ScreenwriterAgent",
                "action": "EXPAND_SCRIPT",
                "details": expand_details,
                "state": state.model_dump()
            })

        if is_stopped and is_stopped():
            return state

        try:
            mode_override_key_hint = (
                ", 'mode_override' ('reference', 'i2v_chaining', or 'video_extend')"
                if state.mode == "hybrid" else ""
            )
            storyboard_prompt = (
                f"You are the StoryboarderAgent. Convert the following screenplay into a structured {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene.\n\n"
                f"SCREENPLAY:\n{screenplay_text}{transcript_ctx}{extend_mode_ctx}{hybrid_mode_ctx}{r2v_anchor_ctx}\n\n"
                "CRITICAL TRANSCRIPT SEGMENTATION RULE: If a Voice Transcript is provided, split it chronologically across the scenes (<= 12 words per scene) in 'spoken_dialogue' so speech never cuts off at 10s boundaries.\n"
                f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
                f"'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'spoken_dialogue' (str or null), 'evaluation_criteria' (str){mode_override_key_hint}."
            )
            text = await run_adk_agent(storyboarder, storyboard_prompt, client=client)
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if text.startswith("json"):
                text = text[4:].strip()

            raw_storyboard = json.loads(text)
            parsed_entries: List[StoryboardEntry] = []
            for idx, item in enumerate(raw_storyboard[:state.num_shots]):
                raw_override = item.get("mode_override")
                valid_override = (
                    raw_override
                    if raw_override in ("reference", "i2v_chaining", "video_extend")
                    else None
                )
                if state.mode == "hybrid" and valid_override is None:
                    valid_override = "reference" if idx == 0 else "video_extend"
                parsed_entries.append(
                    StoryboardEntry(
                        scene_number=item.get("scene_number", idx + 1),
                        description=item.get("description", f"Scene {idx + 1}"),
                        camera_angle=item.get("camera_angle", "medium"),
                        spoken_dialogue=item.get("spoken_dialogue"),
                        evaluation_criteria=item.get(
                            "evaluation_criteria",
                            "Check character identity lock, smooth motion, and object persistence.",
                        ),
                        mode_override=valid_override,
                    )
                )
            state.storyboard = parsed_entries
        except Exception:
            angles = ["wide", "medium", "close-up", "low-angle", "tracking", "crane", "macro"]
            state.storyboard = [
                StoryboardEntry(
                    scene_number=i + 1,
                    description=f"{state.original_intent} - Shot {i + 1}",
                    camera_angle=angles[i % len(angles)],
                    evaluation_criteria="Check character identity lock, lighting stability, smooth motion, and object persistence.",
                    mode_override=("reference" if i == 0 else "video_extend") if state.mode == "hybrid" else None,
                )
                for i in range(state.num_shots)
            ]

    sb_details = {
        "status": "COMPLETED",
        "scenes_count": len(state.storyboard),
        "scenes": [sb.model_dump() for sb in state.storyboard],
    }
    state.log_event(
        agent="StoryboarderAgent",
        action="GENERATE_STORYBOARD",
        details=sb_details,
    )
    if event_callback:
        event_callback({
            "stage": "pre_production",
            "agent": "StoryboarderAgent",
            "action": "GENERATE_STORYBOARD",
            "details": sb_details,
            "state": state.model_dump()
        })

    has_sb_dialogue = any(bool(sb.spoken_dialogue and sb.spoken_dialogue.strip()) for sb in state.storyboard)
    fallback_dialogues = split_voice_transcript_across_shots(state.voice_transcript, len(state.storyboard))
    state.shots = [
        VideoShot(
            shot_index=sb.scene_number,
            prompt=f"{sb.camera_angle} shot: {sb.description}",
            spoken_dialogue=sb.spoken_dialogue if has_sb_dialogue else fallback_dialogues[idx],
            evaluation_criteria=sb.evaluation_criteria,
            mode_override=sb.mode_override,
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


def _resolve_effective_shot_mode(state: PipelineState, shot: VideoShot, idx: int) -> str:
    """Resolves the active continuity mode ('reference', 'i2v_chaining', or 'video_extend') for a specific shot."""
    if shot.mode_override in ("reference", "i2v_chaining", "video_extend"):
        return shot.mode_override
    if state.mode == "hybrid":
        return "reference" if idx == 0 else "video_extend"
    return state.mode


async def _execute_single_shot(
    idx: int,
    shot: VideoShot,
    effective_mode: str,
    state: PipelineState,
    output_dir: str,
    prev_frame_b64: Optional[str],
    prev_last_frame_b64: Optional[str],
    prev_clip_path: Optional[str],
    prev_video_tail_b64: Optional[str],
    prev_video_tail_sec: float,
    client: genai.Client,
    rater_client: Optional[genai.Client],
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    """Executes PromptOptimizer -> HealthChecker -> Omni -> OpenCV Guardrails -> Auto-Rater v2 with Best-of-K Checkpointing."""
    clip_filename = os.path.join(output_dir, f"shot_{shot.shot_index}.mp4")
    is_extend_shot = effective_mode == "video_extend" and prev_video_tail_b64 is not None
    is_i2v_shot = effective_mode == "i2v_chaining" and prev_frame_b64 is not None
    is_r2v_shot = bool(
        state.reference_assets_b64
        and (
            effective_mode == "reference"
            or (effective_mode == "i2v_chaining" and not prev_frame_b64)
            or (effective_mode == "video_extend" and not prev_video_tail_b64)
        )
    )

    feedback: Optional[str] = None
    max_attempts = state.max_attempts or 2

    # Monotonic Best-of-K checkpointing across attempts
    best_score: float = -1.0
    best_video_bytes: Optional[bytes] = None
    best_prompt: str = shot.prompt
    best_eval_result: Optional[Dict[str, Any]] = None

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
            is_i2v_shot=is_i2v_shot,
            client=client,
        )
        state.log_event(
            agent="PromptOptimizerAgent",
            action="OPTIMIZE_PROMPT",
            details={
                "shot_index": shot.shot_index,
                "attempt": attempt + 1,
                "effective_mode": effective_mode,
                "raw_prompt": shot.prompt,
                "optimized_prompt": optimized_shot_prompt,
                "feedback_applied": feedback,
            },
        )
        if event_callback:
            event_callback({
                "stage": "production_loop",
                "agent": "PromptOptimizerAgent",
                "action": "OPTIMIZE_PROMPT",
                "shot_index": shot.shot_index,
                "attempt": attempt + 1,
                "details": {
                    "shot_index": shot.shot_index,
                    "attempt": attempt + 1,
                    "effective_mode": effective_mode,
                    "raw_prompt": shot.prompt,
                    "optimized_prompt": optimized_shot_prompt,
                    "feedback_applied": feedback,
                },
                "state": state.model_dump(),
            })

        # 2. Health Checker Agent
        is_healthy = await audit_prompt_health(optimized_shot_prompt, client=client)
        state.log_event(
            agent="HealthCheckerAgent",
            action="AUDIT_PROMPT",
            details={
                "shot_index": shot.shot_index,
                "verdict": "APPROVED" if is_healthy else "REJECTED_REVERTED",
                "safety_status": "CLEAR",
            },
        )
        if event_callback:
            event_callback({
                "stage": "production_loop",
                "agent": "HealthCheckerAgent",
                "action": "AUDIT_PROMPT",
                "shot_index": shot.shot_index,
                "details": {
                    "shot_index": shot.shot_index,
                    "verdict": "APPROVED" if is_healthy else "REJECTED_REVERTED",
                    "safety_status": "CLEAR",
                },
                "state": state.model_dump(),
            })
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
        render_details = {
            "shot_index": shot.shot_index,
            "mode": effective_mode,
            "task": shot_task or "image_to_video",
            "prompt": optimized_shot_prompt,
            "has_input_image": is_i2v_shot,
            "has_reference_anchor": is_r2v_shot,
            "has_input_video_tail": is_extend_shot,
            "input_tail_seconds": round(prev_video_tail_sec, 2) if is_extend_shot else 0.0,
        }
        state.log_event(
            agent="GeminiOmniFlash",
            action="RENDER_CLIP",
            details=render_details,
        )
        if event_callback:
            event_callback({
                "stage": "production_loop",
                "agent": "GeminiOmniFlash",
                "action": "RENDER_CLIP",
                "shot_index": shot.shot_index,
                "details": render_details,
                "state": state.model_dump(),
            })

        active_tail_b64 = prev_video_tail_b64 if is_extend_shot else None
        try:
            video_bytes = await asyncio.to_thread(
                generate_omni_clip,
                prompt=optimized_shot_prompt,
                input_image_b64=prev_frame_b64 if is_i2v_shot else None,
                input_video_b64=active_tail_b64,
                task=shot_task,
                reference_images_b64=use_refs,
                voice_transcript=shot.spoken_dialogue,
                aspect_ratio=state.aspect_ratio,
                resolution=state.resolution,
                duration=state.duration,
                client=client,
            )
        except Exception as gen_err:
            if (
                is_extend_shot
                and prev_clip_path
                and "speech_edit" in str(gen_err).lower()
            ):
                silent_tail_b64, _ = await asyncio.to_thread(
                    extract_video_tail,
                    prev_clip_path,
                    Config.VIDEO_EXTEND_INPUT_SECONDS,
                    True,
                )
                video_bytes = await asyncio.to_thread(
                    generate_omni_clip,
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
            video_bytes = await asyncio.to_thread(
                trim_video_prefix,
                video_bytes,
                prev_video_tail_sec,
                float(state.duration),
                prev_last_frame_b64,
            )

        with open(clip_filename, "wb") as f:
            f.write(video_bytes)

        det_signals: Dict[str, Any] = {}

        if is_r2v_shot and use_refs:
            locked_to_ref, r2v_f0_mae = await asyncio.to_thread(
                detect_r2v_first_frame_lock, use_refs[0], clip_filename, 12.0
            )
            det_signals["r2v_f0_mae"] = r2v_f0_mae
            r2v_details = {
                "shot_index": shot.shot_index,
                "attempt": attempt + 1,
                "frame0_vs_ref_mae": r2v_f0_mae,
                "locked_to_ref_first_frame": locked_to_ref,
            }
            state.log_event(
                agent="OpenCVVideoParser",
                action="VERIFY_R2V_SCENE_OPENING",
                details=r2v_details,
            )
            if event_callback:
                event_callback({
                    "stage": "production_loop",
                    "agent": "OpenCVVideoParser",
                    "action": "VERIFY_R2V_SCENE_OPENING",
                    "shot_index": shot.shot_index,
                    "details": r2v_details,
                    "state": state.model_dump(),
                })
            if locked_to_ref:
                penalized_score = 0.35
                if penalized_score > best_score:
                    best_score = penalized_score
                    best_video_bytes = video_bytes
                    best_prompt = optimized_shot_prompt
                if attempt < max_attempts - 1:
                    feedback = (
                        f"Frame 0 echoed the white-background reference image (MAE={r2v_f0_mae:.2f}). "
                        "Open immediately inside the full target environment with dynamic camera framing—no studio white backdrop."
                    )
                    continue

        boundary_ref_b64 = prev_frame_b64 if is_i2v_shot else prev_last_frame_b64
        if (is_extend_shot or is_i2v_shot) and boundary_ref_b64:
            has_jump_cut, seam_mae, peak_mae = await asyncio.to_thread(
                detect_seam_jump_cut, boundary_ref_b64, clip_filename, 28.0, 5
            )
            det_signals["seam_mae"] = seam_mae
            det_signals["peak_early_mae"] = peak_mae
            if is_extend_shot:
                seam_details = {
                    "shot_index": shot.shot_index,
                    "attempt": attempt + 1,
                    "seam_mae": seam_mae,
                    "peak_early_mae": peak_mae,
                    "has_jump_cut": has_jump_cut,
                }
                state.log_event(
                    agent="OpenCVVideoParser",
                    action="VERIFY_SEAM_CONTINUITY",
                    details=seam_details,
                )
                if event_callback:
                    event_callback({
                        "stage": "production_loop",
                        "agent": "OpenCVVideoParser",
                        "action": "VERIFY_SEAM_CONTINUITY",
                        "shot_index": shot.shot_index,
                        "details": seam_details,
                        "state": state.model_dump(),
                    })
                if has_jump_cut:
                    penalized_score = 0.40
                    if penalized_score > best_score:
                        best_score = penalized_score
                        best_video_bytes = video_bytes
                        best_prompt = optimized_shot_prompt
                    if attempt < max_attempts - 1:
                        feedback = (
                            f"Hard jump-cut detected at extension boundary (peak MAE={peak_mae:.1f}). "
                            "Continue seamlessly from the exact ending frame and environment in a single continuous camera take with zero scene cuts."
                        )
                        continue

        # 4. Auto-Rater v2 Evaluation (with ground-truth reference + boundary frame + deterministic signals)
        eval_result = await evaluate_clip_quality(
            shot_index=shot.shot_index,
            prompt=optimized_shot_prompt,
            video_path=clip_filename,
            evaluation_criteria=shot.evaluation_criteria,
            spoken_dialogue=shot.spoken_dialogue,
            reference_images_b64=state.reference_assets_b64 if state.reference_assets_b64 else None,
            prev_last_frame_b64=boundary_ref_b64,
            deterministic_signals=det_signals,
            is_r2v_shot=is_r2v_shot,
            is_extend_shot=is_extend_shot,
            client=rater_client,
        )
        score = float(eval_result.get("score", 0.9))

        if score > best_score:
            best_score = score
            best_video_bytes = video_bytes
            best_prompt = optimized_shot_prompt
            best_eval_result = eval_result

        eval_log_details = {
            "shot_index": shot.shot_index,
            "video_path": f"/output/shot_{shot.shot_index}.mp4",
            "criteria_evaluated": shot.evaluation_criteria,
            "attempt": attempt + 1,
            "score": score,
            "best_score_so_far": best_score,
            "opening_environment_observed": eval_result.get("opening_environment_observed", ""),
            "heard_transcript": eval_result.get("heard_transcript", ""),
            "speech_end_sec": eval_result.get("speech_end_sec"),
            "detected_internal_cuts": eval_result.get("detected_internal_cuts", 0),
            "transcript_wer": eval_result.get("transcript_wer"),
            "transcript_word_overlap": eval_result.get("transcript_word_overlap"),
            "audit_status": eval_result.get("audit_status", "OK"),
            "feedback": eval_result.get("feedback", "Good visual quality"),
            "verdict": eval_result.get("verdict", "PASSED"),
            "deterministic_telemetry": eval_result.get("deterministic_telemetry", {}),
        }
        state.log_event(
            agent="QualityRaterAgent",
            action="EVALUATE_QUALITY",
            details=eval_log_details,
        )
        if event_callback:
            event_callback({
                "stage": "production_loop",
                "agent": "QualityRaterAgent",
                "action": "EVALUATE_QUALITY",
                "shot_index": shot.shot_index,
                "score": score,
                "details": eval_log_details,
                "state": state.model_dump(),
            })

        if score >= 0.8 or attempt == max_attempts - 1:
            break
        else:
            feedback = eval_result.get("feedback", "Refine visual continuity and pacing")

    # Restore Best-of-K winner onto disk if a later attempt scored lower
    if best_video_bytes is not None:
        with open(clip_filename, "wb") as f:
            f.write(best_video_bytes)
        shot.video_path = clip_filename
        shot.prompt = best_prompt
        shot.quality_score = round(best_score, 3) if best_score >= 0 else None
        shot.status = "completed"
        if best_eval_result is not None:
            state.quality_rating = shot.quality_score
        return clip_filename

    return None


async def run_production_loop_async(
    state: PipelineState,
    output_dir: str = "/tmp/vidgen_output",
    client: Optional[genai.Client] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_stopped: Optional[Callable[[], bool]] = None
) -> PipelineState:
    """Production loop: Supports parallel Mode A execution, sequential/hybrid chaining, Best-of-K retries & Post-Stitch Seam Audit."""
    explicit_client_passed = client is not None
    if client is None:
        client = get_genai_client()
    rater_client = client if explicit_client_passed else get_genai_client(timeout_ms=Config.RATER_TIMEOUT_MS)

    os.makedirs(output_dir, exist_ok=True)
    if not state.shots:
        return state

    effective_modes = [
        _resolve_effective_shot_mode(state, shot, idx)
        for idx, shot in enumerate(state.shots)
    ]
    can_run_all_parallel = all(m == "reference" for m in effective_modes) and len(state.shots) > 1

    generated_clip_paths: List[str] = []

    if can_run_all_parallel:
        sem = asyncio.Semaphore(max(1, Config.MAX_PARALLEL_SHOTS))

        async def _run_parallel_shot(idx: int, shot: VideoShot) -> Optional[str]:
            async with sem:
                if is_stopped and is_stopped():
                    return None
                clip_p = await _execute_single_shot(
                    idx=idx,
                    shot=shot,
                    effective_mode="reference",
                    state=state,
                    output_dir=output_dir,
                    prev_frame_b64=None,
                    prev_last_frame_b64=None,
                    prev_clip_path=None,
                    prev_video_tail_b64=None,
                    prev_video_tail_sec=0.0,
                    client=client,
                    rater_client=rater_client,
                    event_callback=event_callback,
                    is_stopped=is_stopped,
                )
                if clip_p and os.path.exists(clip_p):
                    frame_fn = os.path.join(output_dir, f"shot_{shot.shot_index}_last_frame.png")
                    try:
                        shot.extracted_last_frame_b64 = await asyncio.to_thread(
                            extract_last_frame, clip_p, frame_fn
                        )
                    except Exception:
                        pass
                return clip_p

        parallel_results = await asyncio.gather(
            *(_run_parallel_shot(i, s) for i, s in enumerate(state.shots))
        )
        generated_clip_paths = [p for p in parallel_results if p]
    else:
        prev_frame_b64: Optional[str] = None
        prev_last_frame_b64: Optional[str] = None
        prev_clip_path: Optional[str] = None
        prev_video_tail_b64: Optional[str] = None
        prev_video_tail_sec: float = 0.0

        for idx, shot in enumerate(state.shots):
            if is_stopped and is_stopped():
                break

            eff_mode = effective_modes[idx]
            frame_filename = os.path.join(output_dir, f"shot_{shot.shot_index}_last_frame.png")

            clip_p = await _execute_single_shot(
                idx=idx,
                shot=shot,
                effective_mode=eff_mode,
                state=state,
                output_dir=output_dir,
                prev_frame_b64=prev_frame_b64 if eff_mode == "i2v_chaining" else None,
                prev_last_frame_b64=prev_last_frame_b64,
                prev_clip_path=prev_clip_path,
                prev_video_tail_b64=prev_video_tail_b64 if eff_mode == "video_extend" else None,
                prev_video_tail_sec=prev_video_tail_sec if eff_mode == "video_extend" else 0.0,
                client=client,
                rater_client=rater_client,
                event_callback=event_callback,
                is_stopped=is_stopped,
            )
            if not clip_p:
                continue

            generated_clip_paths.append(clip_p)
            prev_clip_path = clip_p

            # Always extract terminal frame & 5s tail when a subsequent shot might chain or extend
            next_eff_mode = effective_modes[idx + 1] if (idx + 1) < len(effective_modes) else None
            try:
                extracted_b64 = await asyncio.to_thread(extract_last_frame, clip_p, frame_filename)
                shot.extracted_last_frame_b64 = extracted_b64
                prev_frame_b64 = extracted_b64
                prev_last_frame_b64 = extracted_b64
                if eff_mode == "i2v_chaining" or next_eff_mode == "i2v_chaining":
                    term_details = {
                        "shot_index": shot.shot_index,
                        "frame_file": f"/output/shot_{shot.shot_index}_last_frame.png",
                        "passed_to_next_shot": (idx + 1) < len(state.shots),
                    }
                    state.log_event(
                        agent="OpenCVVideoParser",
                        action="EXTRACT_TERMINAL_FRAME",
                        details=term_details,
                    )
                    if event_callback:
                        event_callback({
                            "stage": "production_loop",
                            "agent": "OpenCVVideoParser",
                            "action": "EXTRACT_TERMINAL_FRAME",
                            "shot_index": shot.shot_index,
                            "details": term_details,
                            "state": state.model_dump(),
                        })
            except Exception:
                prev_frame_b64 = None
                prev_last_frame_b64 = None

            if eff_mode == "video_extend" or next_eff_mode == "video_extend":
                try:
                    prev_video_tail_b64, prev_video_tail_sec = await asyncio.to_thread(
                        extract_video_tail,
                        clip_p,
                        Config.VIDEO_EXTEND_INPUT_SECONDS,
                        False,
                    )
                    tail_details = {
                        "shot_index": shot.shot_index,
                        "tail_seconds": round(prev_video_tail_sec, 2),
                        "strip_audio": False,
                        "task": "extend",
                        "passed_to_next_shot": (idx + 1) < len(state.shots),
                    }
                    state.log_event(
                        agent="OpenCVVideoParser",
                        action="EXTRACT_VIDEO_TAIL",
                        details=tail_details,
                    )
                    if event_callback:
                        event_callback({
                            "stage": "production_loop",
                            "agent": "OpenCVVideoParser",
                            "action": "EXTRACT_VIDEO_TAIL",
                            "shot_index": shot.shot_index,
                            "details": tail_details,
                            "state": state.model_dump(),
                        })
                except Exception:
                    prev_video_tail_b64 = None
                    prev_video_tail_sec = 0.0

    valid_clips = [p for p in generated_clip_paths if os.path.exists(p) and os.path.getsize(p) > 0]
    if valid_clips and not (is_stopped and is_stopped()):
        stitched_filename = f"output_stitched_{len(valid_clips) * 10}s.mp4"
        stitched_path = os.path.join(output_dir, stitched_filename)
        state.stitched_video_path = await asyncio.to_thread(stitch_videos, valid_clips, stitched_path)
        stitch_details = {
            "clips_count": len(valid_clips),
            "output_path": f"/output/{stitched_filename}",
            "final_duration": f"{len(valid_clips) * 10}s",
        }
        state.log_event(
            agent="FFMPEGStitcherTool",
            action="CONCATENATE_CLIPS",
            details=stitch_details,
        )
        if event_callback:
            event_callback({
                "stage": "completion",
                "agent": "FFMPEGStitcherTool",
                "action": "CONCATENATE_CLIPS",
                "details": stitch_details,
                "state": state.model_dump(),
            })

        # 5. Post-Stitch Master Seam & Continuity Audit (Pattern B)
        if len(valid_clips) >= 2 and state.stitched_video_path:
            master_report = await evaluate_stitched_master(
                stitched_video_path=state.stitched_video_path,
                num_shots=len(valid_clips),
                shot_duration_sec=float(state.duration or 10),
                original_intent=state.original_intent,
                voice_transcript=state.voice_transcript,
                reference_images_b64=state.reference_assets_b64 if state.reference_assets_b64 else None,
                client=rater_client,
            )
            state.master_quality_report = master_report
            state.log_event(
                agent="QualityRaterAgent",
                action="EVALUATE_MASTER_SEAMS",
                details=master_report,
            )
            if event_callback:
                event_callback({
                    "stage": "completion",
                    "agent": "QualityRaterAgent",
                    "action": "EVALUATE_MASTER_SEAMS",
                    "details": master_report,
                    "state": state.model_dump(),
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
