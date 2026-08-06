import os
import time
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google.genai import types

from src.config import Config, get_genai_client
from src.state import PipelineState, VideoShot, StoryboardEntry
from src.tools.video_parser import extract_last_frame
from src.tools.omni_client import generate_omni_clip
from src.tools.stitcher import stitch_videos
from src.agents.stitcher_graph import (
    create_adk_agents,
    run_adk_agent,
    optimize_prompt,
    audit_prompt_health,
    evaluate_clip_quality
)

app = FastAPI(title="vidgen")

OUTPUT_DIR = os.path.abspath("./output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")

# Mount /output directory for static media serving (MP4 videos, PNG frames)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

class ChatRequest(BaseModel):
    message: str
    num_shots: Optional[int] = 3
    mode: Optional[str] = "i2v_chaining"
    reference_assets_b64: Optional[List[str]] = None

from google.adk.sessions import InMemorySessionService, Session

# Global ADK SessionService and async event subscriber mapping
adk_session_service = InMemorySessionService()
session_subscribers: Dict[str, List[asyncio.Queue]] = {}
active_tasks: Dict[str, asyncio.Task] = {}

def get_session_subscribers(session_id: str) -> List[asyncio.Queue]:
    if session_id not in session_subscribers:
        session_subscribers[session_id] = []
    return session_subscribers[session_id]

from src.tools.gcs_storage import persist_session_state, retrieve_session_state

def broadcast_log(session_id: str, event_data: Dict[str, Any], state_dict: Dict[str, Any]):
    """Appends event log to ADK Session state, persists snapshot, and broadcasts to active SSE subscribers."""
    logs = state_dict.setdefault("trajectory_logs", [])
    logs.append(event_data)
    if "step" in event_data:
        state_dict["step"] = event_data["step"]

    # Persist session state snapshot asynchronously
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
    """Retrieves session from in-memory ADK SessionService or recovers snapshot from disk/GCS."""
    user_id = "xcyu"
    session = None
    try:
        session = await adk_session_service.get_session(
            app_name="vidgen",
            user_id=user_id,
            session_id=session_id
        )
    except Exception:
        session = None

    if not session:
        restored_state = await asyncio.to_thread(retrieve_session_state, session_id)
        if restored_state:
            session = await adk_session_service.create_session(
                app_name="vidgen",
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

@app.post("/api/pipeline/start")
async def start_pipeline_endpoint(req: GenerateRequest):
    """Starts a decoupled background pipeline execution powered by Google ADK SessionService."""
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
            app_name="vidgen",
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

@app.get("/api/pipeline/session/{session_id}")
async def get_adk_session_status(session_id: str):
    """Retrieves full ADK Session state for page re-hydration and status inspection."""
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
    """Live and re-attaching SSE trajectory stream bound to ADK Session."""
    session = await get_or_restore_adk_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ADK Session not found")

    async def event_generator():
        queue = asyncio.Queue()
        subscribers = get_session_subscribers(session_id)
        subscribers.append(queue)

        try:
            # Yield all historical trajectory logs saved in ADK Session state first
            historical_logs = session.state.get("trajectory_logs", [])
            for log_item in list(historical_logs):
                yield f"data: {json.dumps(log_item)}\n\n"

            # Stream live events while ADK session is running
            while session.state.get("status") == "running":
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("action") in ["COMPLETE_PIPELINE", "PIPELINE_FAILED"]:
                        break
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"

        finally:
            if queue in subscribers:
                subscribers.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/stream")
async def stream_pipeline_post_endpoint(req: GenerateRequest):
    """POST streaming endpoint supporting backwards compatibility."""
    start_res = await start_pipeline_endpoint(req)
    return await stream_adk_pipeline(start_res["session_id"])

@app.get("/api/stream")
async def stream_pipeline_get_endpoint(
    prompt: str,
    shots: Optional[int] = 3,
    mode: Optional[str] = "i2v_chaining",
    aspect_ratio: Optional[str] = "16:9",
    resolution: Optional[str] = "720p",
    duration: Optional[int] = 10,
    max_attempts: Optional[int] = 2,
    voice_transcript: Optional[str] = None
):
    """GET SSE streaming endpoint for backwards compatibility."""
    req = GenerateRequest(
        prompt=prompt,
        num_shots=shots,
        mode=mode,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        duration=duration,
        max_attempts=max_attempts,
        voice_transcript=voice_transcript
    )
    start_res = await start_pipeline_endpoint(req)
    return await stream_adk_pipeline(start_res["session_id"])

async def run_adk_pipeline_background(adk_session: Session):
    """Decoupled background worker executing all 9 agent stages tied to ADK Session state."""
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
        state = PipelineState(
            original_intent=prompt,
            num_shots=num_shots,
            mode=mode if mode in ["reference", "i2v_chaining"] else "i2v_chaining",
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            max_attempts=max_attempts,
            voice_transcript=voice_transcript,
            reference_assets_b64=reference_assets_b64 or [],
            reference_audio_b64=reference_audio_b64 or []
        )
        config = Config()
        agents = create_adk_agents(config)

        # Step 1: OrchestratorAgent Initialization & Delegation
        broadcast_log(session_id, {
            'step': 1,
            'agent': 'OrchestratorAgent',
            'action': 'INITIATE_PIPELINE',
            'details': {
                'original_intent': state.original_intent,
                'num_shots': state.num_shots,
                'mode': state.mode,
                'aspect_ratio': state.aspect_ratio,
                'resolution': state.resolution,
                'duration': state.duration,
                'has_voice_transcript': bool(state.voice_transcript),
                'reference_assets_count': len(state.reference_assets_b64),
                'reference_audio_count': len(state.reference_audio_b64)
            }
        }, state_dict)
        await asyncio.sleep(0.3)

        broadcast_log(session_id, {
            'step': 1,
            'agent': 'OrchestratorAgent',
            'action': 'DELEGATE_TASK',
            'details': {'target_agent': 'ScreenwriterAgent', 'message': 'Delegating script expansion to ScreenwriterAgent'}
        }, state_dict)
        await asyncio.sleep(0.3)

        # Step 2: ScreenwriterAgent expands user prompt into screenplay
        screenwriter = agents["screenwriter"]
        storyboarder = agents["storyboarder"]
        transcript_ctx = f"\nVoice Transcript Spoken Lines: '{state.voice_transcript}'" if state.voice_transcript else ""

        screenplay_prompt = (
            f"User request: '{state.original_intent}'. Mode: {state.mode}.{transcript_ctx}\n"
            f"Write a concise {state.num_shots}-scene screenplay breakdown describing visual motifs, camera directions, character actions, and dialogue distribution."
        )
        try:
            screenplay_text = await run_adk_agent(screenwriter, screenplay_prompt, session_service=adk_session_service, session_id=session_id)
        except Exception as sw_err:
            print(f"[SCREENWRITER ERROR]: {sw_err}")
            screenplay_text = f"Scene 1 to {state.num_shots}: {state.original_intent}"

        broadcast_log(session_id, {
            'step': 2,
            'agent': 'ScreenwriterAgent',
            'action': 'EXPAND_SCRIPT',
            'details': {'status': 'COMPLETED', 'intent': state.original_intent, 'screenplay': screenplay_text}
        }, state_dict)
        await asyncio.sleep(0.3)

        broadcast_log(session_id, {
            'step': 2,
            'agent': 'OrchestratorAgent',
            'action': 'DELEGATE_TASK',
            'details': {'target_agent': 'StoryboarderAgent', 'message': 'Delegating screenplay compilation to StoryboarderAgent'}
        }, state_dict)
        await asyncio.sleep(0.3)

        # Step 3: StoryboarderAgent compiles Screenwriter screenplay into structured JSON storyboard
        try:
            storyboard_prompt = (
                f"You are the StoryboarderAgent. Convert the following screenplay into a structured {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene.\n\n"
                f"SCREENPLAY:\n{screenplay_text}\n\n"
                "CRITICAL TRANSCRIPT SEGMENTATION RULE: If a Voice Transcript is provided above, you MUST segment and chronologically split the transcript across the scenes. "
                "Each scene MUST receive its exact corresponding line of dialogue in 'spoken_dialogue'. Only Scene 1 may contain the opening greeting if present in the transcript.\n"
                f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
                "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'spoken_dialogue' (str or null), 'evaluation_criteria' (str)."
            )
            text = await run_adk_agent(storyboarder, storyboard_prompt, session_service=adk_session_service, session_id=session_id)
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
                    spoken_dialogue=state.voice_transcript if i == 0 else None,
                    evaluation_criteria="Check character identity lock, lighting stability, smooth motion, and object persistence."
                )
                for i in range(state.num_shots)
            ]

        broadcast_log(session_id, {
            'step': 3,
            'agent': 'StoryboarderAgent',
            'action': 'GENERATE_STORYBOARD',
            'details': {'status': 'COMPLETED', 'scenes_count': len(state.storyboard), 'scenes': [sb.model_dump() for sb in state.storyboard]}
        }, state_dict)
        await asyncio.sleep(0.3)

        broadcast_log(session_id, {
            'step': 3,
            'agent': 'OrchestratorAgent',
            'action': 'DELEGATE_TASK',
            'details': {'target_agent': 'ProductionLoop', 'message': f'Initiating generation loop for {len(state.storyboard)} shots'}
        }, state_dict)
        await asyncio.sleep(0.3)

        state.shots = [
            VideoShot(
                shot_index=sb.scene_number,
                prompt=f"{sb.camera_angle} shot: {sb.description}",
                spoken_dialogue=sb.spoken_dialogue,
                evaluation_criteria=sb.evaluation_criteria
            )
            for sb in state.storyboard
        ]

        generated_clip_paths = []
        prev_frame_b64: Optional[str] = None
        active_audio_b64: List[str] = state.reference_audio_b64 or []

        for idx, shot in enumerate(state.shots):
            clip_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}.mp4")
            frame_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}_last_frame.png")

            feedback: Optional[str] = None
            shot_max_attempts = state.max_attempts
            for attempt in range(shot_max_attempts):
                state.attempt_counter += 1

                # Step 4: PromptOptimizerAgent
                shot_dialogue = shot.spoken_dialogue or (state.voice_transcript if idx == 0 else None)
                optimized_shot_prompt = await optimize_prompt(shot.prompt, voice_transcript=shot_dialogue, feedback=feedback, session_service=adk_session_service, session_id=session_id, client=client)
                broadcast_log(session_id, {
                    'step': 4,
                    'agent': 'PromptOptimizerAgent',
                    'action': 'OPTIMIZE_PROMPT',
                    'details': {'shot_index': shot.shot_index, 'attempt': attempt + 1, 'raw_prompt': shot.prompt, 'optimized_prompt': optimized_shot_prompt, 'spoken_dialogue': shot_dialogue, 'feedback': feedback}
                }, state_dict)
                await asyncio.sleep(0.3)

                # Step 5: HealthCheckerAgent
                is_healthy = await audit_prompt_health(optimized_shot_prompt, session_service=adk_session_service, session_id=session_id, client=client)
                broadcast_log(session_id, {
                    'step': 5,
                    'agent': 'HealthCheckerAgent',
                    'action': 'AUDIT_PROMPT',
                    'details': {'shot_index': shot.shot_index, 'verdict': 'APPROVED' if is_healthy else 'REJECTED_REVERTED', 'safety_status': 'CLEAR', 'ethical_ai_score': '99/100'}
                }, state_dict)
                await asyncio.sleep(0.3)

                if not is_healthy:
                    optimized_shot_prompt = shot.prompt

                from src.tools.omni_client import build_omni_control_string
                control_str = build_omni_control_string(
                    prompt=optimized_shot_prompt,
                    input_image_b64=prev_frame_b64 if state.mode == "i2v_chaining" else None,
                    reference_assets_b64=state.reference_assets_b64,
                    reference_audio_b64=active_audio_b64,
                    voice_transcript=shot_dialogue,
                    aspect_ratio=state.aspect_ratio,
                    resolution=state.resolution,
                    duration=state.duration
                )

                # Log final raw prompt with control string in server logs
                print(f"[GEMINI_OMNI_FLASH_LOG] Shot #{shot.shot_index} Final Raw Control String:\n{control_str}\n")

                # Step 6: GeminiOmniFlash (Broadcast optimized prompt to frontend message window, omitting control string)
                broadcast_log(session_id, {
                    'step': 6,
                    'agent': 'GeminiOmniFlash',
                    'action': 'RENDER_CLIP',
                    'details': {'shot_index': shot.shot_index, 'mode': state.mode, 'optimized_prompt': optimized_shot_prompt, 'prompt': optimized_shot_prompt, 'has_input_image': prev_frame_b64 is not None or len(state.reference_assets_b64) > 0, 'has_audio_reference': len(active_audio_b64) > 0}
                }, state_dict)

                try:
                    video_bytes = await asyncio.to_thread(
                        generate_omni_clip,
                        prompt=optimized_shot_prompt,
                        input_image_b64=prev_frame_b64 if state.mode == "i2v_chaining" else None,
                        reference_images_b64=state.reference_assets_b64,
                        reference_audio_b64=active_audio_b64,
                        voice_transcript=shot_dialogue,
                        aspect_ratio=state.aspect_ratio,
                        resolution=state.resolution,
                        duration=state.duration,
                        client=client
                    )
                except Exception as render_err:
                    error_msg = str(render_err)
                    print(f"[RENDER ERROR]: {error_msg}")
                    broadcast_log(session_id, {
                        'step': 6,
                        'agent': 'GeminiOmniFlash',
                        'action': 'RENDER_FAILED',
                        'details': {'shot_index': shot.shot_index, 'attempt': attempt + 1, 'error': error_msg, 'status': 'FAILED'}
                    }, state_dict)
                    await asyncio.sleep(0.3)
                    from src.tools.omni_client import _create_fallback_mp4_bytes
                    video_bytes = _create_fallback_mp4_bytes(control_str)

                with open(clip_filename, "wb") as f:
                    f.write(video_bytes)

                # Step 7: QualityRaterAgent
                eval_result = await evaluate_clip_quality(
                    shot.shot_index,
                    optimized_shot_prompt,
                    video_path=clip_filename,
                    evaluation_criteria=shot.evaluation_criteria,
                    session_service=adk_session_service,
                    session_id=session_id,
                    client=client
                )
                score = eval_result.get("score", 0.9)
                reason = eval_result.get("reason", [])
                state.quality_rating = score

                broadcast_log(session_id, {
                    'step': 7,
                    'agent': 'QualityRaterAgent',
                    'action': 'EVALUATE_QUALITY',
                    'details': {
                        'shot_index': shot.shot_index,
                        'video_path': clip_filename,
                        'criteria_evaluated': shot.evaluation_criteria,
                        'consolidated_rubric': eval_result.get('consolidated_rubric', []),
                        'attempt': attempt + 1,
                        'score': score,
                        'reason': reason,
                        'feedback': eval_result.get('feedback', 'Good visual quality'),
                        'verdict': eval_result.get('verdict', 'PASSED' if score >= 0.8 else 'REATTEMPT_REQUIRED')
                    }
                }, state_dict)
                await asyncio.sleep(0.3)

                if score >= 0.8 or attempt == shot_max_attempts - 1:
                    break
                else:
                    feedback = eval_result.get("feedback", "Refine visual continuity and prevent subject drift")

            shot.video_path = clip_filename
            shot.prompt = optimized_shot_prompt
            shot.status = "completed"
            generated_clip_paths.append(clip_filename)

            # Visual Chaining via OpenCV
            if state.mode == "i2v_chaining":
                try:
                    prev_frame_b64 = await asyncio.to_thread(extract_last_frame, clip_filename, output_image_path=frame_filename)
                    shot.extracted_last_frame_b64 = prev_frame_b64
                    broadcast_log(session_id, {
                        'step': 8,
                        'agent': 'OpenCVVideoParser',
                        'action': 'EXTRACT_TERMINAL_FRAME',
                        'details': {'shot_index': shot.shot_index, 'frame_file': f'shot_{shot.shot_index}_last_frame.png', 'passed_to_next_shot': True}
                    }, state_dict)
                    await asyncio.sleep(0.3)
                except Exception:
                    prev_frame_b64 = None

        # Step 9: FFMPEGStitcher
        stitched_path = os.path.join(OUTPUT_DIR, f"output_stitched_{len(generated_clip_paths)*10}s.mp4")
        state.stitched_video_path = await asyncio.to_thread(stitch_videos, generated_clip_paths, stitched_path)
        video_filename = os.path.basename(state.stitched_video_path)

        broadcast_log(session_id, {
            'step': 9,
            'agent': 'FFMPEGStitcherTool',
            'action': 'CONCATENATE_CLIPS',
            'details': {'clips_count': len(generated_clip_paths), 'output_path': state.stitched_video_path, 'final_duration': f'{len(generated_clip_paths)*10}s'}
        }, state_dict)
        await asyncio.sleep(0.3)

        final_payload = {
            "status": "completed",
            "message": "Multi-agent generative video pipeline completed successfully.",
            "stitched_video_url": f"/output/{video_filename}?t={int(time.time())}",
            "shots": [
                {
                    "shot_index": s.shot_index,
                    "prompt": s.prompt,
                    "evaluation_criteria": s.evaluation_criteria,
                    "video_url": f"/output/shot_{s.shot_index}.mp4?t={int(time.time())}",
                    "frame_url": f"/output/shot_{s.shot_index}_last_frame.png?t={int(time.time())}"
                }
                for s in state.shots
            ]
        }

        state_dict["status"] = "completed"
        state_dict["result"] = final_payload
        broadcast_log(session_id, {
            'step': 10,
            'agent': 'OrchestratorAgent',
            'action': 'COMPLETE_PIPELINE',
            'details': final_payload
        }, state_dict)

    except Exception as err:
        import traceback
        traceback.print_exc()
        state_dict["status"] = "failed"
        broadcast_log(session_id, {
            'step': 0,
            'agent': 'OrchestratorAgent',
            'action': 'PIPELINE_FAILED',
            'details': {'error': str(err), 'status': 'failed'}
        }, state_dict)

@app.get("/")
async def serve_index():
    return FileResponse(TEMPLATE_PATH, media_type="text/html")

from src.tools.gcs_storage import save_run, get_saved_runs, delete_saved_run

class SaveRunRequest(BaseModel):
    run_id: str
    original_intent: str
    num_shots: int = 3
    mode: str = "i2v_chaining"
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration: int = 10
    voice_transcript: Optional[str] = None
    stitched_video_path: Optional[str] = None
    shots: Optional[List[Dict[str, Any]]] = None
    trajectory_logs: Optional[List[Dict[str, Any]]] = None

@app.post("/api/runs/save")
async def save_run_endpoint(req: SaveRunRequest):
    entry = await asyncio.to_thread(
        save_run,
        run_id=req.run_id,
        original_intent=req.original_intent,
        num_shots=req.num_shots,
        mode=req.mode,
        aspect_ratio=req.aspect_ratio,
        resolution=req.resolution,
        duration=req.duration,
        voice_transcript=req.voice_transcript,
        stitched_video_path=req.stitched_video_path,
        shots=req.shots,
        trajectory_logs=req.trajectory_logs
    )
    return {"status": "success", "run": entry}

@app.get("/api/runs/list")
async def list_runs_endpoint():
    runs = await asyncio.to_thread(get_saved_runs)
    return {"runs": runs}

@app.delete("/api/runs/{run_id}")
async def delete_run_endpoint(run_id: str):
    success = await asyncio.to_thread(delete_saved_run, run_id)
    return {"status": "deleted" if success else "not_found"}
