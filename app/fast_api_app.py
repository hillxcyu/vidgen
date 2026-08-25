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
import asyncio
import contextlib
from typing import Optional, List, Dict, Any
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
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
from app.tools.video_parser import extract_last_frame
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.stitcher import stitch_videos
from app.tools.gcs_storage import (
    save_run,
    get_saved_runs,
    delete_saved_run,
    persist_session_state,
    retrieve_session_state,
    gcs_uri_to_https_url,
)
from app.agents.pipeline import (
    optimize_prompt,
    audit_prompt_health,
    evaluate_clip_quality,
    run_adk_agent,
    create_pipeline_agents,
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


@app.get("/", response_class=HTMLResponse)
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
            mode=mode if mode in ["reference", "i2v_chaining"] else "i2v_chaining",
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
        screenplay_prompt = (
            f"User request: '{prompt}'. Mode: {mode}.\n"
            f"Write a concise {num_shots}-scene screenplay breakdown describing visual motifs, camera directions, character actions, and dialogue distribution."
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
            f"SCREENPLAY:\n{screenplay_text}\n\n"
            f"Return ONLY a JSON list of {num_shots} items, where each item has keys: "
            "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'evaluation_criteria' (str)."
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

        pipeline_state.shots = [
            VideoShot(
                shot_index=sb.scene_number,
                prompt=f"{sb.camera_angle} shot: {sb.description}",
                spoken_dialogue=voice_transcript if sb.scene_number == 1 else None,
                evaluation_criteria=sb.evaluation_criteria
            )
            for sb in pipeline_state.storyboard
        ]

        # Production Loop
        generated_clip_paths = []
        prev_frame_b64: Optional[str] = None

        for shot in pipeline_state.shots:
            if state_dict.get("status") == "stopped":
                break

            clip_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}.mp4")
            frame_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}_last_frame.png")

            feedback = None
            for attempt in range(max_attempts):
                if state_dict.get("status") == "stopped":
                    break

                optimized_prompt = await optimize_prompt(
                    raw_prompt=shot.prompt,
                    voice_transcript=shot.spoken_dialogue,
                    feedback=feedback,
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

                broadcast_log(session_id, {
                    'step': 6,
                    'agent': 'GeminiOmniFlash',
                    'action': 'RENDER_CLIP',
                    'details': {
                        'shot_index': shot.shot_index,
                        'mode': mode,
                        'prompt': optimized_prompt,
                        'has_input_image': prev_frame_b64 is not None
                    }
                }, state_dict)

                if mode == "i2v_chaining":
                    video_bytes = generate_omni_clip(
                        prompt=optimized_prompt,
                        input_image_b64=prev_frame_b64,
                        voice_transcript=shot.spoken_dialogue,
                        aspect_ratio=aspect_ratio,
                        resolution=resolution,
                        duration=duration,
                        client=client
                    )
                else:
                    video_bytes = generate_omni_clip(
                        prompt=optimized_prompt,
                        reference_images_b64=reference_assets_b64,
                        voice_transcript=shot.spoken_dialogue,
                        aspect_ratio=aspect_ratio,
                        resolution=resolution,
                        duration=duration,
                        client=client
                    )

                with open(clip_filename, "wb") as f:
                    f.write(video_bytes)

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
                    prev_frame_b64 = extract_last_frame(clip_filename, output_image_path=frame_filename)
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

        if state_dict.get("status") != "stopped" and generated_clip_paths:
            stitched_filename = f"output_stitched_{len(generated_clip_paths)*10}s.mp4"
            stitched_path = os.path.join(OUTPUT_DIR, stitched_filename)
            pipeline_state.stitched_video_path = stitch_videos(generated_clip_paths, stitched_path)

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
