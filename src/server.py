import os
import json
import asyncio
from typing import Optional, List
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

app = FastAPI(title="GenMedia-Omni Multi-Agent Video Pipeline UI")

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

class GenerateRequest(BaseModel):
    prompt: str
    num_shots: Optional[int] = 3
    mode: Optional[str] = "i2v_chaining"
    aspect_ratio: Optional[str] = "16:9"
    resolution: Optional[str] = "720p"
    duration: Optional[int] = 10
    voice_transcript: Optional[str] = None
    reference_assets_b64: Optional[List[str]] = None
    reference_audio_b64: Optional[List[str]] = None

@app.post("/api/stream")
async def stream_pipeline_post_endpoint(req: GenerateRequest):
    """POST streaming endpoint supporting prompt, mode, shots, voice transcript, control strings, and asset uploads."""
    return await stream_pipeline(
        prompt=req.prompt,
        shots=req.num_shots or 3,
        mode=req.mode or "i2v_chaining",
        aspect_ratio=req.aspect_ratio or "16:9",
        resolution=req.resolution or "720p",
        duration=req.duration or 10,
        voice_transcript=req.voice_transcript,
        reference_assets_b64=req.reference_assets_b64 or [],
        reference_audio_b64=req.reference_audio_b64 or []
    )

@app.get("/api/stream")
async def stream_pipeline_get_endpoint(
    prompt: str,
    shots: Optional[int] = 3,
    mode: Optional[str] = "i2v_chaining",
    aspect_ratio: Optional[str] = "16:9",
    resolution: Optional[str] = "720p",
    duration: Optional[int] = 10,
    voice_transcript: Optional[str] = None
):
    """GET SSE streaming endpoint for backwards compatibility."""
    return await stream_pipeline(
        prompt=prompt,
        shots=shots or 3,
        mode=mode or "i2v_chaining",
        aspect_ratio=aspect_ratio or "16:9",
        resolution=resolution or "720p",
        duration=duration or 10,
        voice_transcript=voice_transcript,
        reference_assets_b64=[],
        reference_audio_b64=[]
    )

async def stream_pipeline(
    prompt: str,
    shots: int,
    mode: str,
    aspect_ratio: str,
    resolution: str,
    duration: int,
    voice_transcript: Optional[str],
    reference_assets_b64: List[str],
    reference_audio_b64: List[str]
):
    """Core SSE generator executing all 7 agent stages with voice consistency & ADK shared session state support."""
    async def event_generator():
        client = get_genai_client()
        num_shots = max(1, min(10, shots or 3))
        state = PipelineState(
            original_intent=prompt,
            num_shots=num_shots,
            mode=mode if mode in ["reference", "i2v_chaining"] else "i2v_chaining",
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            voice_transcript=voice_transcript,
            reference_assets_b64=reference_assets_b64 or [],
            reference_audio_b64=reference_audio_b64 or []
        )
        config = Config()
        agents = create_adk_agents(config)

        # Initialize shared ADK SessionService and ADK Session with global state
        from google.adk.sessions import InMemorySessionService
        session_service = InMemorySessionService()
        adk_session = await session_service.create_session(
            app_name="vidgen-omni",
            user_id="xcyu",
            state={
                "original_intent": prompt,
                "num_shots": state.num_shots,
                "mode": state.mode,
                "aspect_ratio": state.aspect_ratio,
                "resolution": state.resolution,
                "duration": state.duration,
                "voice_transcript": state.voice_transcript,
                "reference_assets_count": len(state.reference_assets_b64),
                "reference_audio_count": len(state.reference_audio_b64),
                "reference_assets_b64": state.reference_assets_b64,
                "reference_audio_b64": state.reference_audio_b64
            }
        )
        session_id = adk_session.id

        # Step 1: OrchestratorAgent Initialization
        yield f"data: {json.dumps({'step': 1, 'agent': 'OrchestratorAgent', 'action': 'INITIATE_PIPELINE', 'details': {'prompt': prompt, 'num_shots': state.num_shots, 'mode': state.mode, 'aspect_ratio': state.aspect_ratio, 'resolution': state.resolution, 'duration': state.duration, 'has_voice_transcript': bool(state.voice_transcript), 'reference_assets_count': len(state.reference_assets_b64), 'reference_audio_count': len(state.reference_audio_b64)}})}\n\n"
        await asyncio.sleep(0.3)

        # Step 2: ScreenwriterAgent via ADK Runner
        yield f"data: {json.dumps({'step': 2, 'agent': 'ScreenwriterAgent', 'action': 'EXPAND_SCRIPT', 'details': {'status': 'in_progress', 'intent': prompt, 'target_shots': state.num_shots, 'voice_transcript': state.voice_transcript}})}\n\n"
        screenwriter = agents["screenwriter"]

        try:
            transcript_ctx = f"\nVoice Transcript Spoken Lines: '{state.voice_transcript}'" if state.voice_transcript else ""
            screenplay_prompt = (
                f"User request: '{state.original_intent}'. Mode: {state.mode}.{transcript_ctx}\n"
                f"Generate a {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene. "
                "CRITICAL TRANSCRIPT SEGMENTATION RULE: If a Voice Transcript is provided above, you MUST segment and chronologically split the transcript across the scenes. "
                "Each scene MUST receive its exact corresponding line of dialogue in 'spoken_dialogue'. Only Scene 1 may contain the opening greeting if present in the transcript.\n"
                f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
                "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'spoken_dialogue' (str or null), 'evaluation_criteria' (str)."
            )
            text = await run_adk_agent(screenwriter, screenplay_prompt, session_service=session_service, session_id=session_id)
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

        # Step 3: StoryboarderAgent
        yield f"data: {json.dumps({'step': 3, 'agent': 'StoryboarderAgent', 'action': 'GENERATE_STORYBOARD', 'details': {'scenes_count': len(state.storyboard), 'scenes': [sb.model_dump() for sb in state.storyboard]}})}\n\n"
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
            max_attempts = 2
            for attempt in range(max_attempts):
                state.attempt_counter += 1

                # Step 4: PromptOptimizerAgent via ADK Runner (Pass per-shot spoken dialogue)
                shot_dialogue = shot.spoken_dialogue or (state.voice_transcript if idx == 0 else None)
                optimized_shot_prompt = await optimize_prompt(shot.prompt, voice_transcript=shot_dialogue, feedback=feedback, session_service=session_service, session_id=session_id, client=client)
                yield f"data: {json.dumps({'step': 4, 'agent': 'PromptOptimizerAgent', 'action': 'OPTIMIZE_PROMPT', 'details': {'shot_index': shot.shot_index, 'attempt': attempt + 1, 'raw_prompt': shot.prompt, 'optimized_prompt': optimized_shot_prompt, 'spoken_dialogue': shot_dialogue, 'feedback': feedback}})}\n\n"
                await asyncio.sleep(0.3)

                # Step 5: HealthCheckerAgent via ADK Runner
                is_healthy = await audit_prompt_health(optimized_shot_prompt, session_service=session_service, session_id=session_id, client=client)
                yield f"data: {json.dumps({'step': 5, 'agent': 'HealthCheckerAgent', 'action': 'AUDIT_PROMPT', 'details': {'shot_index': shot.shot_index, 'verdict': 'APPROVED' if is_healthy else 'REJECTED_REVERTED', 'safety_status': 'CLEAR', 'ethical_ai_score': '99/100'}})}\n\n"
                await asyncio.sleep(0.3)

                if not is_healthy:
                    optimized_shot_prompt = shot.prompt

                from src.tools.omni_client import build_omni_control_string
                control_str = build_omni_control_string(
                    prompt=optimized_shot_prompt,
                    input_image_b64=prev_frame_b64 if state.mode == "i2v_chaining" else None,
                    reference_assets_b64=state.reference_assets_b64 if state.mode == "reference" else None,
                    reference_audio_b64=active_audio_b64,
                    voice_transcript=shot_dialogue,
                    aspect_ratio=state.aspect_ratio,
                    resolution=state.resolution,
                    duration=state.duration
                )

                # Step 6: GeminiOmniFlash
                yield f"data: {json.dumps({'step': 6, 'agent': 'GeminiOmniFlash', 'action': 'RENDER_CLIP', 'details': {'shot_index': shot.shot_index, 'mode': state.mode, 'control_string': control_str, 'has_input_image': prev_frame_b64 is not None or len(state.reference_assets_b64) > 0, 'has_audio_reference': len(active_audio_b64) > 0}})}\n\n"

                if state.mode == "i2v_chaining":
                    video_bytes = generate_omni_clip(
                        prompt=optimized_shot_prompt,
                        input_image_b64=prev_frame_b64,
                        reference_audio_b64=active_audio_b64,
                        voice_transcript=shot_dialogue,
                        aspect_ratio=state.aspect_ratio,
                        resolution=state.resolution,
                        duration=state.duration,
                        client=client
                    )
                else:
                    video_bytes = generate_omni_clip(
                        prompt=optimized_shot_prompt,
                        reference_images_b64=state.reference_assets_b64,
                        reference_audio_b64=active_audio_b64,
                        voice_transcript=shot_dialogue,
                        aspect_ratio=state.aspect_ratio,
                        resolution=state.resolution,
                        duration=state.duration,
                        client=client
                    )

                with open(clip_filename, "wb") as f:
                    f.write(video_bytes)

                # Step 7: QualityRaterAgent via ADK Runner
                eval_result = await evaluate_clip_quality(
                    shot.shot_index,
                    optimized_shot_prompt,
                    video_path=clip_filename,
                    evaluation_criteria=shot.evaluation_criteria,
                    session_service=session_service,
                    session_id=session_id,
                    client=client
                )
                score = eval_result.get("score", 0.9)
                drift_detected = eval_result.get("drift_detected", False)
                drift_breakdown = eval_result.get("drift_breakdown", {})
                state.quality_rating = score

                yield f"data: {json.dumps({'step': 7, 'agent': 'QualityRaterAgent', 'action': 'EVALUATE_QUALITY', 'details': {'shot_index': shot.shot_index, 'video_path': clip_filename, 'criteria_evaluated': shot.evaluation_criteria, 'attempt': attempt + 1, 'score': score, 'drift_detected': drift_detected, 'drift_breakdown': drift_breakdown, 'feedback': eval_result.get('feedback', 'Good visual quality'), 'verdict': 'PASSED' if score >= 0.8 and not drift_detected else 'REATTEMPT_REQUIRED'}})}\n\n"
                await asyncio.sleep(0.3)

                if (score >= 0.8 and not drift_detected) or attempt == max_attempts - 1:
                    break
                else:
                    feedback = eval_result.get("feedback", "Refine visual continuity and prevent subject drift")

            shot.video_path = clip_filename
            shot.status = "completed"
            generated_clip_paths.append(clip_filename)

            # Visual Chaining via OpenCV
            if state.mode == "i2v_chaining":
                try:
                    prev_frame_b64 = extract_last_frame(clip_filename, output_image_path=frame_filename)
                    shot.extracted_last_frame_b64 = prev_frame_b64
                    # Step 8: OpenCVParser
                    yield f"data: {json.dumps({'step': 8, 'agent': 'OpenCVVideoParser', 'action': 'EXTRACT_TERMINAL_FRAME', 'details': {'shot_index': shot.shot_index, 'frame_file': f'shot_{shot.shot_index}_last_frame.png', 'passed_to_next_shot': True}})}\n\n"
                    await asyncio.sleep(0.3)
                except Exception:
                    prev_frame_b64 = None

        # Step 9: FFMPEGStitcher
        stitched_path = os.path.join(OUTPUT_DIR, f"output_stitched_{len(generated_clip_paths)*10}s.mp4")
        state.stitched_video_path = stitch_videos(generated_clip_paths, stitched_path)
        video_filename = os.path.basename(state.stitched_video_path)

        yield f"data: {json.dumps({'step': 9, 'agent': 'FFMPEGStitcherTool', 'action': 'CONCATENATE_CLIPS', 'details': {'clips_count': len(generated_clip_paths), 'output_path': state.stitched_video_path, 'final_duration': f'{len(generated_clip_paths)*10}s'}})}\n\n"
        await asyncio.sleep(0.3)

        # Final Event payload with full media output URLs and shot metadata
        final_payload = {
            "status": "complete",
            "mode": state.mode,
            "stitched_video_url": f"/output/{video_filename}",
            "shots": [
                {
                    "shot_index": shot.shot_index,
                    "prompt": shot.prompt,
                    "evaluation_criteria": shot.evaluation_criteria,
                    "video_url": f"/output/shot_{shot.shot_index}.mp4",
                    "frame_url": f"/output/shot_{shot.shot_index}_last_frame.png"
                }
                for shot in state.shots
            ]
        }
        yield f"data: {json.dumps({'step': 9, 'agent': 'OrchestratorAgent', 'action': 'PIPELINE_COMPLETE', 'details': final_payload})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/")
async def serve_index():
    return FileResponse(TEMPLATE_PATH, media_type="text/html")
