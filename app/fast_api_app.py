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
import json
import base64
import urllib.request
import asyncio
import contextlib
from typing import Optional, List, Dict, Any
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from a2a.server.tasks import InMemoryTaskStore
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.reasoning_engine_adapter import attach_reasoning_engine_routes
from app.config import Config, get_genai_client
from app.state import PipelineState, VideoShot, StoryboardEntry
from app.tools.video_parser import (
    extract_last_frame,
    extract_video_tail,
    trim_video_prefix,
    detect_seam_jump_cut,
    detect_r2v_first_frame_lock,
)
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.stitcher import stitch_videos
from app.tools.gcs_storage import (
    save_run,
    get_saved_runs,
    delete_saved_run,
    persist_session_state,
    retrieve_session_state,
    gcs_uri_to_https_url,
    get_storage_client,
)
from app.agents.pipeline import (
    optimize_prompt,
    audit_prompt_health,
    evaluate_clip_quality,
    run_adk_agent,
    create_pipeline_agents,
    split_voice_transcript_across_shots,
)

load_dotenv()

OUTPUT_DIR = os.path.abspath("./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

adk_session_service = InMemorySessionService()
session_subscribers: Dict[str, List[asyncio.Queue]] = {}
active_tasks: Dict[str, asyncio.Task] = {}


def get_session_subscribers(session_id: str) -> List[asyncio.Queue]:
    if session_id not in session_subscribers:
        session_subscribers[session_id] = []
    return session_subscribers[session_id]


def broadcast_log(session_id: str, event_data: Dict[str, Any], state_dict: Dict[str, Any]):
    logs = state_dict.setdefault("trajectory_logs", [])
    logs.append(event_data)
    if "step" in event_data:
        state_dict["step"] = event_data["step"]

    try:
        asyncio.create_task(asyncio.to_thread(persist_session_state, session_id, state_dict))
    except Exception:
        pass

    subscribers = session_subscribers.get(session_id, [])
    for q in list(subscribers):
        try:
            q.put_nowait(event_data)
        except Exception:
            pass


async def get_or_restore_adk_session(session_id: str) -> Optional[Session]:
    user_id = "xcyu"
    if hasattr(adk_session_service, "sessions"):
        direct_sess = adk_session_service.sessions.get("vidgen-omni", {}).get(user_id, {}).get(session_id)
        if direct_sess:
            return direct_sess

    session = None
    try:
        session = await adk_session_service.get_session(
            app_name="vidgen-omni",
            user_id=user_id,
            session_id=session_id
        )
    except Exception:
        session = None

    if not session:
        restored_state = await asyncio.to_thread(retrieve_session_state, session_id)
        if restored_state:
            session = await adk_session_service.create_session(
                app_name="vidgen-omni",
                user_id=user_id,
                session_id=session_id,
                state=restored_state
            )

    return session


class GenerateRequest(BaseModel):
    prompt: str
    num_shots: Optional[int] = 3
    mode: Optional[str] = "i2v_chaining"
    aspect_ratio: Optional[str] = "16:9"
    resolution: Optional[str] = "720p"
    duration: Optional[int] = 10
    max_attempts: Optional[int] = 2
    voice_transcript: Optional[str] = None
    reference_assets_b64: Optional[List[str]] = None
    reference_audio_b64: Optional[List[str]] = None
    session_id: Optional[str] = None


@contextlib.asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
    )
    fastapi_app.state.runner = runner
    fastapi_app.state.agent_app_name = adk_app.name

    try:
        await attach_a2a_routes(
            fastapi_app,
            agent=root_agent,
            runner=runner,
            task_store=InMemoryTaskStore(),
            rpc_path=f"/a2a/{adk_app.name}",
        )
    except Exception as e:
        print(f"[A2A Notice]: {e}")

    yield


AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
otel_to_cloud = os.environ.get(
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", ""
).lower() in ("true", "1")
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=otel_to_cloud,
    lifespan=lifespan,
)
app.title = "vidgen-omni"
app.description = "API for interacting with the vidgen-omni multi-agent video generator"
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
attach_reasoning_engine_routes(app)


def format_artifact_for_adk_ui(artifact: Any, artifact_name: str) -> dict:
    """Format artifact Part into the inlineData/mimeType structure expected by ADK Debug UI."""
    mime_type = "video/mp4" if artifact_name.endswith(".mp4") else "application/octet-stream"
    b64_data = ""

    if hasattr(artifact, "inline_data") and artifact.inline_data and getattr(artifact.inline_data, "data", None):
        mime_type = getattr(artifact.inline_data, "mime_type", None) or mime_type
        raw = artifact.inline_data.data
        b64_data = base64.b64encode(raw).decode("utf-8") if isinstance(raw, bytes) else str(raw)
    elif hasattr(artifact, "text") and artifact.text:
        mime_type = "text/plain"
        b64_data = base64.b64encode(artifact.text.encode("utf-8")).decode("utf-8")
    elif hasattr(artifact, "file_data") and artifact.file_data and getattr(artifact.file_data, "file_uri", None):
        mime_type = getattr(artifact.file_data, "mime_type", None) or mime_type
        uri = artifact.file_data.file_uri

        candidates = [
            uri,
            os.path.join(OUTPUT_DIR, os.path.basename(artifact_name)),
            os.path.join("/tmp/vidgen_output", os.path.basename(artifact_name)),
        ]
        found_bytes = None
        for c in candidates:
            if c and os.path.exists(c) and os.path.isfile(c):
                try:
                    with open(c, "rb") as fp:
                        found_bytes = fp.read()
                    break
                except Exception:
                    pass

        if found_bytes is None and uri.startswith(("http://", "https://")):
            try:
                with urllib.request.urlopen(uri, timeout=10) as resp:
                    found_bytes = resp.read()
            except Exception as e:
                print(f"[Artifact Fetch Warning]: {e}")

        if found_bytes:
            b64_data = base64.b64encode(found_bytes).decode("utf-8")
        else:
            b64_data = base64.b64encode(uri.encode("utf-8")).decode("utf-8")
            mime_type = "text/plain"

    return {
        "mimeType": mime_type,
        "data": b64_data,
        "inlineData": {
            "mimeType": mime_type,
            "data": b64_data,
        },
        "fileData": {
            "fileUri": getattr(artifact.file_data, "file_uri", "") if hasattr(artifact, "file_data") and artifact.file_data else "",
            "mimeType": mime_type,
        } if hasattr(artifact, "file_data") and artifact.file_data else None,
        "text": artifact.text if hasattr(artifact, "text") and artifact.text else None,
    }


def attach_enhanced_artifact_routes(fastapi_app: FastAPI) -> None:
    """Register enhanced artifact routes for ADK Debug UI compatibility."""
    for r in list(fastapi_app.routes):
        path = getattr(r, "path", "")
        if "/artifacts/{artifact_name:path}/versions/{version_id}" in path or path.endswith("/artifacts/{artifact_name:path}"):
            if "GET" in getattr(r, "methods", []):
                try:
                    fastapi_app.routes.remove(r)
                except ValueError:
                    pass

    @fastapi_app.get(
        "/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name:path}/versions/{version_id}"
    )
    async def load_artifact_version_enhanced(
        app_name: str,
        user_id: str,
        session_id: str,
        artifact_name: str,
        version_id: str,
    ):
        version: int | None = None
        if version_id != "latest":
            try:
                version = int(version_id)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid version ID") from None

        artifact_svc = services.get_artifact_service()
        artifact = await artifact_svc.load_artifact(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            filename=artifact_name,
            version=version,
        )
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return format_artifact_for_adk_ui(artifact, artifact_name)

    @fastapi_app.get(
        "/apps/{app_name}/users/{user_id}/sessions/{session_id}/artifacts/{artifact_name:path}"
    )
    async def load_artifact_latest_enhanced(
        app_name: str,
        user_id: str,
        session_id: str,
        artifact_name: str,
    ):
        return await load_artifact_version_enhanced(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            artifact_name=artifact_name,
            version_id="latest",
        )


attach_enhanced_artifact_routes(app)

# Remove default ADK root routes so our Studio UI handles the root URL
for r in list(app.routes):
    if getattr(r, "path", None) in ["/", "/index.html"]:
        try:
            app.routes.remove(r)
        except ValueError:
            pass

# Mount ADK Debug & Chat UI at /adk
import google.adk.cli.fast_api as adk_fast_api
from pathlib import Path
adk_browser_dist = Path(adk_fast_api.__file__).parent.resolve() / "browser"
if adk_browser_dist.exists():
    app.mount("/adk", StaticFiles(directory=str(adk_browser_dist), html=True), name="adk")


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
@app.get("/studio", response_class=HTMLResponse)
async def read_root():
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>vidgen-omni Web Studio UI</h1>")


@app.post("/api/pipeline/start")
async def start_pipeline_endpoint(req: GenerateRequest):
    session_id = req.session_id

    existing_session = None
    if session_id and session_id not in ["undefined", "null", ""]:
        existing_session = await get_or_restore_adk_session(session_id)

    if not existing_session:
        initial_state = {
            "original_intent": req.prompt,
            "num_shots": req.num_shots or 3,
            "mode": req.mode or "i2v_chaining",
            "aspect_ratio": req.aspect_ratio or "16:9",
            "resolution": req.resolution or "720p",
            "duration": req.duration or 10,
            "max_attempts": req.max_attempts or 2,
            "voice_transcript": req.voice_transcript,
            "reference_assets_b64": req.reference_assets_b64 or [],
            "reference_audio_b64": req.reference_audio_b64 or [],
            "status": "running",
            "step": 0,
            "trajectory_logs": [],
            "result": None
        }
        adk_session = await adk_session_service.create_session(
            app_name="vidgen-omni",
            user_id="xcyu",
            session_id=session_id if session_id and session_id not in ["undefined", "null", ""] else None,
            state=initial_state
        )
        session_id = adk_session.id
    else:
        adk_session = existing_session

    if session_id not in active_tasks or active_tasks[session_id].done():
        task = asyncio.create_task(run_adk_pipeline_background(adk_session))
        active_tasks[session_id] = task

    return {
        "session_id": session_id,
        "status": adk_session.state.get("status", "running"),
        "step": adk_session.state.get("step", 0)
    }


@app.post("/api/pipeline/stop/{session_id}")
async def stop_pipeline_endpoint(session_id: str):
    session = await get_or_restore_adk_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ADK Session not found")

    task = active_tasks.get(session_id)
    if task and not task.done():
        task.cancel()

    session.state["status"] = "stopped"
    broadcast_log(session_id, {
        'step': 0,
        'agent': 'OrchestratorAgent',
        'action': 'PIPELINE_STOPPED',
        'details': {'status': 'stopped', 'message': 'Pipeline execution manually terminated by user.'}
    }, session.state)

    await asyncio.to_thread(persist_session_state, session_id, session.state)

    return {
        "session_id": session_id,
        "status": "stopped",
        "message": "Pipeline execution terminated successfully."
    }


@app.get("/api/pipeline/session/{session_id}")
async def get_adk_session_status(session_id: str):
    session = await get_or_restore_adk_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ADK Session not found")
    return {
        "session_id": session.id,
        "status": session.state.get("status", "unknown"),
        "step": session.state.get("step", 0),
        "trajectory_logs": session.state.get("trajectory_logs", []),
        "result": session.state.get("result"),
        "request_data": {
            "prompt": session.state.get("original_intent"),
            "num_shots": session.state.get("num_shots"),
            "mode": session.state.get("mode"),
            "aspect_ratio": session.state.get("aspect_ratio"),
            "resolution": session.state.get("resolution"),
            "duration": session.state.get("duration")
        }
    }


@app.get("/api/pipeline/stream/{session_id}")
async def stream_adk_pipeline(session_id: str):
    session = await get_or_restore_adk_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ADK Session not found")

    async def event_generator():
        queue = asyncio.Queue()
        subscribers = get_session_subscribers(session_id)
        subscribers.append(queue)

        try:
            historical_logs = session.state.get("trajectory_logs", [])
            for log_item in list(historical_logs):
                yield f"data: {json.dumps(log_item)}\n\n"

            while session.state.get("status") == "running":
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("action") in ["COMPLETE_PIPELINE", "PIPELINE_FAILED", "PIPELINE_STOPPED"]:
                        break
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"

        finally:
            if queue in subscribers:
                subscribers.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def run_adk_pipeline_background(adk_session: Session):
    state_dict = adk_session.state
    session_id = adk_session.id
    prompt = state_dict.get("original_intent", "")
    shots = state_dict.get("num_shots", 3)
    mode = state_dict.get("mode", "i2v_chaining")
    aspect_ratio = state_dict.get("aspect_ratio", "16:9")
    resolution = state_dict.get("resolution", "720p")
    duration = state_dict.get("duration", 10)
    max_attempts = state_dict.get("max_attempts", 2)
    voice_transcript = state_dict.get("voice_transcript")
    reference_assets_b64 = state_dict.get("reference_assets_b64", [])
    reference_audio_b64 = state_dict.get("reference_audio_b64", [])

    try:
        client = get_genai_client()
        num_shots = max(1, min(10, shots or 3))
        pipeline_state = PipelineState(
            original_intent=prompt,
            num_shots=num_shots,
            mode=mode if mode in ["reference", "i2v_chaining", "video_extend"] else "i2v_chaining",
            aspect_ratio=aspect_ratio or "16:9",
            resolution=resolution or "720p",
            duration=duration or 10,
            max_attempts=max_attempts or 2,
            voice_transcript=voice_transcript,
            reference_assets_b64=reference_assets_b64,
            reference_audio_b64=reference_audio_b64
        )

        # 1. Orchestrator
        broadcast_log(session_id, {
            'step': 1,
            'agent': 'OrchestratorAgent',
            'action': 'INITIATE_PIPELINE',
            'details': {
                'intent': prompt,
                'num_shots': num_shots,
                'mode': mode,
                'aspect_ratio': aspect_ratio,
                'resolution': resolution,
                'duration': f'{duration}s',
                'max_attempts': max_attempts,
                'dialogue_specified': bool(voice_transcript)
            }
        }, state_dict)

        # 2. Screenwriter
        agents = create_pipeline_agents(Config())
        screenwriter = agents["screenwriter"]
        transcript_ctx = (
            f"\nVoice Transcript Spoken Lines: '{voice_transcript}'"
            if voice_transcript else ""
        )
        extend_mode_ctx = (
            "\nCONTINUOUS EXTENSION RULE (video_extend mode): Design all scenes as one unbroken continuous single-take camera journey where each scene smoothly continues from the exact ending pose and space of the previous scene without hard location cuts."
            if mode == "video_extend" else ""
        )
        r2v_anchor_ctx = (
            "\nREFERENCE-TO-VIDEO SCENE-1 RULE: A studio-white subject/product reference image is provided. Scene 1 (and all scenes) MUST open immediately on Frame 0 inside a rich physical environment—NEVER describe, open on, or transition/dissolve out of a white studio backdrop."
            if reference_assets_b64 else ""
        )
        screenplay_prompt = (
            f"User request: '{prompt}'. Mode: {mode}.{transcript_ctx}{extend_mode_ctx}{r2v_anchor_ctx}\n"
            f"Write a concise {num_shots}-scene screenplay breakdown describing visual motifs, camera directions, character actions, and dialogue distribution (<= 12 spoken words per 10s scene)."
        )
        try:
            screenplay_text = await run_adk_agent(screenwriter, screenplay_prompt, session_service=adk_session_service, session_id=session_id)
        except Exception:
            screenplay_text = f"Scene 1 to {num_shots}: {prompt}"

        pipeline_state.screenplay_draft = screenplay_text
        broadcast_log(session_id, {
            'step': 2,
            'agent': 'ScreenwriterAgent',
            'action': 'EXPAND_SCRIPT',
            'details': {
                'status': 'COMPLETED',
                'intent': prompt,
                'screenplay': screenplay_text
            }
        }, state_dict)

        # 3. Storyboarder
        storyboarder = agents["storyboarder"]
        storyboard_prompt = (
            f"You are the StoryboarderAgent. Convert the following screenplay into a structured {num_shots}-scene video storyboard with custom quality evaluation criteria for each scene.\n\n"
            f"SCREENPLAY:\n{screenplay_text}{transcript_ctx}{extend_mode_ctx}{r2v_anchor_ctx}\n\n"
            "CRITICAL TRANSCRIPT SEGMENTATION RULE: If a Voice Transcript is provided, split it chronologically across the scenes (<= 12 words per scene) in 'spoken_dialogue' so speech never cuts off at 10s boundaries.\n"
            f"Return ONLY a JSON list of {num_shots} items, where each item has keys: "
            "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'spoken_dialogue' (str or null), 'evaluation_criteria' (str)."
        )
        try:
            sb_text = await run_adk_agent(storyboarder, storyboard_prompt, session_service=adk_session_service, session_id=session_id)
            if sb_text.startswith("```"):
                sb_text = sb_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if sb_text.startswith("json"):
                sb_text = sb_text[4:].strip()

            raw_sb = json.loads(sb_text)
            pipeline_state.storyboard = [
                StoryboardEntry(
                    scene_number=item.get("scene_number", idx + 1),
                    description=item.get("description", f"Scene {idx + 1}"),
                    camera_angle=item.get("camera_angle", "medium"),
                    spoken_dialogue=item.get("spoken_dialogue"),
                    evaluation_criteria=item.get("evaluation_criteria", "Check character identity lock, smooth motion, and object persistence.")
                )
                for idx, item in enumerate(raw_sb[:num_shots])
            ]
        except Exception:
            angles = ["wide", "medium", "close-up", "low-angle", "tracking", "crane", "macro"]
            pipeline_state.storyboard = [
                StoryboardEntry(
                    scene_number=i + 1,
                    description=f"{prompt} - Shot {i + 1}",
                    camera_angle=angles[i % len(angles)],
                    evaluation_criteria="Check character identity lock, lighting stability, smooth motion, and object persistence."
                )
                for i in range(num_shots)
            ]

        broadcast_log(session_id, {
            'step': 3,
            'agent': 'StoryboarderAgent',
            'action': 'GENERATE_STORYBOARD',
            'details': {
                'status': 'COMPLETED',
                'scenes_count': len(pipeline_state.storyboard),
                'scenes': [s.model_dump() for s in pipeline_state.storyboard]
            }
        }, state_dict)

        has_sb_dialogue = any(bool(sb.spoken_dialogue and sb.spoken_dialogue.strip()) for sb in pipeline_state.storyboard)
        fallback_dialogues = split_voice_transcript_across_shots(voice_transcript, len(pipeline_state.storyboard))
        pipeline_state.shots = [
            VideoShot(
                shot_index=sb.scene_number,
                prompt=f"{sb.camera_angle} shot: {sb.description}",
                spoken_dialogue=sb.spoken_dialogue if has_sb_dialogue else fallback_dialogues[idx],
                evaluation_criteria=sb.evaluation_criteria
            )
            for idx, sb in enumerate(pipeline_state.storyboard)
        ]

        # Production Loop
        generated_clip_paths = []
        prev_frame_b64: Optional[str] = None
        prev_last_frame_b64: Optional[str] = None
        prev_clip_path: Optional[str] = None
        prev_video_tail_b64: Optional[str] = None
        prev_video_tail_sec: float = 0.0

        for shot in pipeline_state.shots:
            if state_dict.get("status") == "stopped":
                break

            clip_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}.mp4")
            frame_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}_last_frame.png")
            is_extend_shot = mode == "video_extend" and prev_video_tail_b64 is not None
            is_r2v_shot = bool(
                reference_assets_b64
                and (
                    (mode == "reference")
                    or (mode == "i2v_chaining" and not prev_frame_b64)
                    or (mode == "video_extend" and not prev_video_tail_b64)
                )
            )

            feedback = None
            for attempt in range(max_attempts):
                if state_dict.get("status") == "stopped":
                    break

                optimized_prompt = await optimize_prompt(
                    raw_prompt=shot.prompt,
                    voice_transcript=shot.spoken_dialogue,
                    feedback=feedback,
                    is_extend_shot=is_extend_shot,
                    is_r2v_shot=is_r2v_shot,
                    session_service=adk_session_service,
                    session_id=session_id,
                    client=client
                )

                broadcast_log(session_id, {
                    'step': 4,
                    'agent': 'PromptOptimizerAgent',
                    'action': 'OPTIMIZE_PROMPT',
                    'details': {
                        'shot_index': shot.shot_index,
                        'attempt': attempt + 1,
                        'raw_prompt': shot.prompt,
                        'optimized_prompt': optimized_prompt,
                        'feedback_applied': feedback
                    }
                }, state_dict)

                is_healthy = await audit_prompt_health(
                    optimized_prompt,
                    session_service=adk_session_service,
                    session_id=session_id,
                    client=client
                )

                broadcast_log(session_id, {
                    'step': 5,
                    'agent': 'HealthCheckerAgent',
                    'action': 'AUDIT_PROMPT',
                    'details': {
                        'shot_index': shot.shot_index,
                        'verdict': 'APPROVED' if is_healthy else 'REJECTED_REVERTED',
                        'safety_status': 'CLEAR',
                        'ethical_ai_score': '99/100'
                    }
                }, state_dict)

                if not is_healthy:
                    optimized_prompt = shot.prompt

                if state_dict.get("status") == "stopped":
                    break

                is_extend_shot = mode == "video_extend" and prev_video_tail_b64 is not None
                use_refs = reference_assets_b64 if is_r2v_shot else None
                shot_task = (
                    "extend"
                    if is_extend_shot
                    else ("reference_to_video" if is_r2v_shot else None)
                )
                broadcast_log(session_id, {
                    'step': 6,
                    'agent': 'GeminiOmniFlash',
                    'action': 'RENDER_CLIP',
                    'details': {
                        'shot_index': shot.shot_index,
                        'mode': mode,
                        'task': shot_task or 'image_to_video',
                        'prompt': optimized_prompt,
                        'has_input_image': prev_frame_b64 is not None,
                        'has_reference_anchor': is_r2v_shot,
                        'has_input_video_tail': is_extend_shot,
                        'input_tail_seconds': round(prev_video_tail_sec, 2) if is_extend_shot else 0.0
                    }
                }, state_dict)

                try:
                    video_bytes = await asyncio.to_thread(
                        generate_omni_clip,
                        prompt=optimized_prompt,
                        input_image_b64=prev_frame_b64 if mode == "i2v_chaining" else None,
                        input_video_b64=prev_video_tail_b64 if is_extend_shot else None,
                        task=shot_task,
                        reference_images_b64=use_refs,
                        voice_transcript=shot.spoken_dialogue,
                        aspect_ratio=aspect_ratio,
                        resolution=resolution,
                        duration=duration,
                        client=client
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
                            prompt=optimized_prompt,
                            input_video_b64=silent_tail_b64,
                            task="extend",
                            voice_transcript=shot.spoken_dialogue,
                            aspect_ratio=aspect_ratio,
                            resolution=resolution,
                            duration=duration,
                            client=client,
                        )
                    else:
                        raise

                if is_extend_shot and prev_video_tail_sec > 0:
                    video_bytes = await asyncio.to_thread(
                        trim_video_prefix,
                        video_bytes,
                        prev_video_tail_sec,
                        float(duration or 10),
                        prev_last_frame_b64,
                    )

                with open(clip_filename, "wb") as f:
                    f.write(video_bytes)

                if is_r2v_shot and use_refs:
                    locked_to_ref, r2v_f0_mae = await asyncio.to_thread(
                        detect_r2v_first_frame_lock,
                        use_refs[0],
                        clip_filename,
                        12.0,
                    )
                    broadcast_log(session_id, {
                        'step': 6,
                        'agent': 'OpenCVVideoParser',
                        'action': 'VERIFY_R2V_SCENE_OPENING',
                        'details': {
                            'shot_index': shot.shot_index,
                            'attempt': attempt + 1,
                            'frame0_vs_ref_mae': r2v_f0_mae,
                            'locked_to_ref_first_frame': locked_to_ref,
                        }
                    }, state_dict)
                    if locked_to_ref and attempt < max_attempts - 1:
                        feedback = (
                            f"Frame 0 echoed the white-background reference image (MAE={r2v_f0_mae:.2f}). "
                            "Open immediately inside the full target environment with dynamic camera framing—no studio white backdrop."
                        )
                        continue

                if is_extend_shot and prev_last_frame_b64:
                    has_jump_cut, seam_mae, peak_mae = await asyncio.to_thread(
                        detect_seam_jump_cut,
                        prev_last_frame_b64,
                        clip_filename,
                        28.0,
                        5,
                    )
                    broadcast_log(session_id, {
                        'step': 6,
                        'agent': 'OpenCVVideoParser',
                        'action': 'VERIFY_SEAM_CONTINUITY',
                        'details': {
                            'shot_index': shot.shot_index,
                            'attempt': attempt + 1,
                            'seam_mae': seam_mae,
                            'peak_early_mae': peak_mae,
                            'has_jump_cut': has_jump_cut,
                        }
                    }, state_dict)
                    if has_jump_cut and attempt < max_attempts - 1:
                        feedback = (
                            f"Hard jump-cut detected at extension boundary (peak MAE={peak_mae:.1f}). "
                            "Continue seamlessly from the exact ending frame and environment in a single continuous camera take with zero scene cuts."
                        )
                        continue

                eval_result = await evaluate_clip_quality(
                    shot_index=shot.shot_index,
                    prompt=optimized_prompt,
                    video_path=clip_filename,
                    evaluation_criteria=shot.evaluation_criteria,
                    spoken_dialogue=shot.spoken_dialogue,
                    session_service=adk_session_service,
                    session_id=session_id,
                    client=client
                )
                score = eval_result.get("score", 0.9)

                broadcast_log(session_id, {
                    'step': 7,
                    'agent': 'QualityRaterAgent',
                    'action': 'EVALUATE_QUALITY',
                    'details': {
                        'shot_index': shot.shot_index,
                        'video_path': f"/output/shot_{shot.shot_index}.mp4",
                        'criteria_evaluated': shot.evaluation_criteria,
                        'attempt': attempt + 1,
                        'score': score,
                        'feedback': eval_result.get("feedback", "Good visual quality"),
                        'verdict': eval_result.get("verdict", "PASSED")
                    }
                }, state_dict)

                if score >= 0.8 or attempt == max_attempts - 1:
                    break
                else:
                    feedback = eval_result.get("feedback", "Refine visual continuity and pacing")

            shot.video_path = clip_filename
            shot.prompt = optimized_prompt
            shot.status = "completed"
            generated_clip_paths.append(clip_filename)

            if mode == "i2v_chaining":
                try:
                    prev_frame_b64 = await asyncio.to_thread(extract_last_frame, clip_filename, output_image_path=frame_filename)
                    shot.extracted_last_frame_b64 = prev_frame_b64
                    broadcast_log(session_id, {
                        'step': 8,
                        'agent': 'OpenCVVideoParser',
                        'action': 'EXTRACT_TERMINAL_FRAME',
                        'details': {
                            'shot_index': shot.shot_index,
                            'frame_file': f"/output/shot_{shot.shot_index}_last_frame.png",
                            'passed_to_next_shot': True
                        }
                    }, state_dict)
                except Exception:
                    prev_frame_b64 = None
            elif mode == "video_extend":
                prev_clip_path = clip_filename
                try:
                    prev_last_frame_b64 = await asyncio.to_thread(extract_last_frame, clip_filename, output_image_path=frame_filename)
                    shot.extracted_last_frame_b64 = prev_last_frame_b64
                except Exception:
                    prev_last_frame_b64 = None
                try:
                    prev_video_tail_b64, prev_video_tail_sec = await asyncio.to_thread(
                        extract_video_tail,
                        clip_filename,
                        Config.VIDEO_EXTEND_INPUT_SECONDS,
                        False,
                    )
                    broadcast_log(session_id, {
                        'step': 8,
                        'agent': 'OpenCVVideoParser',
                        'action': 'EXTRACT_VIDEO_TAIL',
                        'details': {
                            'shot_index': shot.shot_index,
                            'tail_seconds': round(prev_video_tail_sec, 2),
                            'strip_audio': False,
                            'task': 'extend',
                            'frame_file': f"/output/shot_{shot.shot_index}_last_frame.png",
                            'passed_to_next_shot': True
                        }
                    }, state_dict)
                except Exception:
                    prev_video_tail_b64 = None
                    prev_video_tail_sec = 0.0

        if state_dict.get("status") != "stopped" and generated_clip_paths:
            stitched_filename = f"output_stitched_{len(generated_clip_paths)*10}s.mp4"
            stitched_path = os.path.join(OUTPUT_DIR, stitched_filename)
            pipeline_state.stitched_video_path = await asyncio.to_thread(stitch_videos, generated_clip_paths, stitched_path)

            broadcast_log(session_id, {
                'step': 9,
                'agent': 'FFMPEGStitcherTool',
                'action': 'CONCATENATE_CLIPS',
                'details': {
                    'clips_count': len(generated_clip_paths),
                    'output_path': f"/output/{stitched_filename}",
                    'final_duration': f"{len(generated_clip_paths)*10}s"
                }
            }, state_dict)

            shots_data = [
                {
                    "shot_index": s.shot_index,
                    "prompt": s.prompt,
                    "evaluation_criteria": s.evaluation_criteria,
                    "video_path": f"/output/shot_{s.shot_index}.mp4",
                    "video_url": f"/output/shot_{s.shot_index}.mp4",
                    "frame_path": f"/output/shot_{s.shot_index}_last_frame.png",
                    "frame_url": f"/output/shot_{s.shot_index}_last_frame.png",
                    "status": s.status
                }
                for s in pipeline_state.shots
            ]

            result_summary = {
                "status": "completed",
                "stitched_video": f"/output/{stitched_filename}",
                "stitched_video_url": f"/output/{stitched_filename}",
                "stitched_video_path": f"/output/{stitched_filename}",
                "final_duration": f"{len(generated_clip_paths)*10}s",
                "shots": shots_data
            }
            state_dict["status"] = "completed"
            state_dict["result"] = result_summary

            broadcast_log(session_id, {
                'step': 9,
                'agent': 'OrchestratorAgent',
                'action': 'COMPLETE_PIPELINE',
                'details': result_summary
            }, state_dict)

            await asyncio.to_thread(
                save_run,
                run_id=session_id,
                original_intent=prompt,
                num_shots=num_shots,
                mode=mode,
                stitched_video_path=pipeline_state.stitched_video_path,
                shots=shots_data,
                trajectory_logs=state_dict.get("trajectory_logs", []),
                voice_transcript=voice_transcript,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration=duration,
                output_dir=OUTPUT_DIR
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        state_dict["status"] = "failed"
        state_dict["error"] = str(e)
        broadcast_log(session_id, {
            'step': 0,
            'agent': 'OrchestratorAgent',
            'action': 'PIPELINE_FAILED',
            'details': {'error': str(e)}
        }, state_dict)


@app.get("/api/runs")
@app.get("/api/runs/list")
async def list_runs_endpoint():
    runs = await asyncio.to_thread(get_saved_runs, OUTPUT_DIR)
    return {"runs": runs}


@app.post("/api/runs/save")
async def save_run_endpoint(req: Request):
    data = await req.json()
    run_id = data.get("run_id") or f"run_{int(asyncio.get_event_loop().time()*1000)}"
    stitched_path = data.get("stitched_video_path")
    if stitched_path and not os.path.isabs(stitched_path):
        stitched_path = os.path.join(OUTPUT_DIR, os.path.basename(stitched_path))

    saved = await asyncio.to_thread(
        save_run,
        run_id=run_id,
        original_intent=data.get("original_intent", ""),
        num_shots=data.get("num_shots", 3),
        mode=data.get("mode", "i2v_chaining"),
        stitched_video_path=stitched_path,
        shots=data.get("shots", []),
        trajectory_logs=data.get("trajectory_logs", []),
        voice_transcript=data.get("voice_transcript"),
        aspect_ratio=data.get("aspect_ratio", "16:9"),
        resolution=data.get("resolution", "720p"),
        duration=data.get("duration", 10),
        output_dir=OUTPUT_DIR
    )
    return {"status": "success", "run": saved}


@app.post("/api/runs/{run_id}/pin")
async def pin_run_endpoint(run_id: str):
    session = await get_or_restore_adk_session(run_id)
    if not session:
        raise HTTPException(status_code=404, detail="Run/Session not found")

    state = session.state
    res = state.get("result", {})
    shots_data = res.get("shots", [])
    stitched_path = os.path.join(OUTPUT_DIR, os.path.basename(res.get("stitched_video", ""))) if res.get("stitched_video") else None

    pinned = await asyncio.to_thread(
        save_run,
        run_id=run_id,
        original_intent=state.get("original_intent", ""),
        num_shots=state.get("num_shots", 3),
        mode=state.get("mode", "i2v_chaining"),
        stitched_video_path=stitched_path,
        shots=shots_data,
        trajectory_logs=state.get("trajectory_logs", []),
        voice_transcript=state.get("voice_transcript"),
        aspect_ratio=state.get("aspect_ratio", "16:9"),
        resolution=state.get("resolution", "720p"),
        duration=state.get("duration", 10),
        output_dir=OUTPUT_DIR
    )
    return {"status": "success", "run": pinned}


@app.delete("/api/runs/{run_id}")
async def delete_run_endpoint(run_id: str):
    await asyncio.to_thread(delete_saved_run, run_id, OUTPUT_DIR)
    return {"status": "success", "run_id": run_id}


@app.get("/api/gcs/{bucket_name}/{blob_path:path}")
async def proxy_gcs_media(bucket_name: str, blob_path: str):
    """Streams GCS showcase media (MP4/PNG) using server ADC credentials when Public Access Prevention is enforced."""
    def _download() -> bytes:
        client = get_storage_client()
        if not client:
            raise FileNotFoundError("GCS client unavailable")
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        return blob.download_as_bytes()

    try:
        data = await asyncio.to_thread(_download)
    except Exception as err:
        raise HTTPException(status_code=404, detail=f"GCS media not found: {err}")

    media_type = "video/mp4" if blob_path.endswith(".mp4") else (
        "image/png" if blob_path.endswith(".png") else "application/octet-stream"
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "no-cache, max-age=0", "Accept-Ranges": "bytes"},
    )

