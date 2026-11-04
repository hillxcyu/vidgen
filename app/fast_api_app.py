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
    run_pipeline_async,
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
    """Unified background worker delegating directly to app.agents.pipeline.run_pipeline_async."""
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

    action_step_map: Dict[str, int] = {
        "INITIATE_PIPELINE": 1,
        "EXPAND_SCRIPT": 2,
        "GENERATE_STORYBOARD": 3,
        "OPTIMIZE_PROMPT": 4,
        "AUDIT_PROMPT": 5,
        "RENDER_CLIP": 6,
        "VERIFY_R2V_SCENE_OPENING": 6,
        "VERIFY_SEAM_CONTINUITY": 6,
        "EVALUATE_QUALITY": 7,
        "EXTRACT_TERMINAL_FRAME": 8,
        "EXTRACT_VIDEO_TAIL": 8,
        "CONCATENATE_CLIPS": 9,
        "EVALUATE_MASTER_SEAMS": 9,
    }

    try:
        client = get_genai_client()
        num_shots = max(1, min(10, shots or 3))
        valid_mode = (
            mode
            if mode in ["reference", "i2v_chaining", "video_extend", "hybrid"]
            else "i2v_chaining"
        )
        pipeline_state = PipelineState(
            original_intent=prompt,
            num_shots=num_shots,
            mode=valid_mode,
            aspect_ratio=aspect_ratio or "16:9",
            resolution=resolution or "720p",
            duration=duration or 10,
            max_attempts=max_attempts or 2,
            voice_transcript=voice_transcript,
            reference_assets_b64=reference_assets_b64,
            reference_audio_b64=reference_audio_b64,
        )

        def _on_pipeline_event(ev: Dict[str, Any]) -> None:
            action = ev.get("action", "PIPELINE_EVENT")
            agent = ev.get("agent", "OrchestratorAgent")
            step_num = action_step_map.get(action, state_dict.get("step", 1))
            details = ev.get("details")
            if details is None and isinstance(ev.get("state"), dict):
                t_logs = ev["state"].get("trajectory_logs") or []
                if t_logs:
                    details = t_logs[-1].get("details", {})
            broadcast_log(
                session_id,
                {
                    "step": step_num,
                    "agent": agent,
                    "action": action,
                    "details": details or {},
                },
                state_dict,
            )

        pipeline_state = await run_pipeline_async(
            pipeline_state,
            output_dir=OUTPUT_DIR,
            client=client,
            event_callback=_on_pipeline_event,
            is_stopped=lambda: state_dict.get("status") == "stopped",
        )

        completed_shots = [s for s in pipeline_state.shots if s.status == "completed" and s.video_path]
        if state_dict.get("status") != "stopped" and pipeline_state.stitched_video_path and completed_shots:
            stitched_filename = os.path.basename(pipeline_state.stitched_video_path)
            shots_data = [
                {
                    "shot_index": s.shot_index,
                    "prompt": s.prompt,
                    "evaluation_criteria": s.evaluation_criteria,
                    "mode_override": s.mode_override,
                    "quality_score": s.quality_score,
                    "video_path": f"/output/shot_{s.shot_index}.mp4",
                    "video_url": f"/output/shot_{s.shot_index}.mp4",
                    "frame_path": f"/output/shot_{s.shot_index}_last_frame.png",
                    "frame_url": f"/output/shot_{s.shot_index}_last_frame.png",
                    "status": s.status,
                }
                for s in pipeline_state.shots
            ]

            result_summary = {
                "status": "completed",
                "stitched_video": f"/output/{stitched_filename}",
                "stitched_video_url": f"/output/{stitched_filename}",
                "stitched_video_path": f"/output/{stitched_filename}",
                "final_duration": f"{len(completed_shots) * 10}s",
                "shots": shots_data,
                "master_quality_report": pipeline_state.master_quality_report,
            }
            state_dict["status"] = "completed"
            state_dict["result"] = result_summary

            broadcast_log(
                session_id,
                {
                    "step": 9,
                    "agent": "OrchestratorAgent",
                    "action": "COMPLETE_PIPELINE",
                    "details": result_summary,
                },
                state_dict,
            )

            await asyncio.to_thread(
                save_run,
                run_id=session_id,
                original_intent=prompt,
                num_shots=num_shots,
                mode=valid_mode,
                stitched_video_path=pipeline_state.stitched_video_path,
                shots=shots_data,
                trajectory_logs=state_dict.get("trajectory_logs", []),
                voice_transcript=voice_transcript,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration=duration,
                output_dir=OUTPUT_DIR,
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        state_dict["status"] = "failed"
        state_dict["error"] = str(e)
        broadcast_log(
            session_id,
            {
                "step": 0,
                "agent": "OrchestratorAgent",
                "action": "PIPELINE_FAILED",
                "details": {"error": str(e)},
            },
            state_dict,
        )


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

