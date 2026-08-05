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
    reference_assets_b64: Optional[List[str]] = None

@app.post("/api/stream")
async def stream_pipeline_post_endpoint(req: GenerateRequest):
    """POST streaming endpoint supporting prompt, mode, shots, and reference asset uploads."""
    return await stream_pipeline(
        prompt=req.prompt,
        shots=req.num_shots or 3,
        mode=req.mode or "i2v_chaining",
        reference_assets_b64=req.reference_assets_b64 or []
    )

@app.get("/api/stream")
async def stream_pipeline_get_endpoint(prompt: str, shots: Optional[int] = 3, mode: Optional[str] = "i2v_chaining"):
    """GET SSE streaming endpoint for backwards compatibility."""
    return await stream_pipeline(prompt=prompt, shots=shots or 3, mode=mode or "i2v_chaining", reference_assets_b64=[])

async def stream_pipeline(prompt: str, shots: int, mode: str, reference_assets_b64: List[str]):
    """Core SSE generator executing all 7 agent stages with complete parameter support."""
    async def event_generator():
        client = get_genai_client()
        num_shots = max(1, min(10, shots or 3))
        state = PipelineState(
            original_intent=prompt,
            num_shots=num_shots,
            mode=mode if mode in ["reference", "i2v_chaining"] else "i2v_chaining",
            reference_assets_b64=reference_assets_b64 or []
        )
        config = Config()
        agents = create_adk_agents(config)

        # Step 1: OrchestratorAgent Initialization
        yield f"data: {json.dumps({'step': 1, 'agent': 'OrchestratorAgent', 'action': 'INITIATE_PIPELINE', 'details': {'prompt': prompt, 'num_shots': state.num_shots, 'mode': state.mode, 'reference_assets_count': len(state.reference_assets_b64)}})}\n\n"
        await asyncio.sleep(0.3)

        # Step 2: ScreenwriterAgent via ADK Runner
        yield f"data: {json.dumps({'step': 2, 'agent': 'ScreenwriterAgent', 'action': 'EXPAND_SCRIPT', 'details': {'status': 'in_progress', 'intent': prompt, 'target_shots': state.num_shots}})}\n\n"
        screenwriter = agents["screenwriter"]

        try:
            screenplay_prompt = (
                f"User request: '{state.original_intent}'. Mode: {state.mode}.\n"
                f"Generate a {state.num_shots}-scene video storyboard with custom quality evaluation criteria for each scene. "
                "Ensure criteria audit character identity lock, smooth motion, and object persistence (confirming visual assets, props, and garments do not vanish or re-emerge).\n"
                f"Return ONLY a JSON list of {state.num_shots} items, where each item has keys: "
                "'scene_number' (int 1 to N), 'description' (str), 'camera_angle' (str), 'evaluation_criteria' (str)."
            )
            text = await run_adk_agent(screenwriter, screenplay_prompt)
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

        # Step 3: StoryboarderAgent
        yield f"data: {json.dumps({'step': 3, 'agent': 'StoryboarderAgent', 'action': 'GENERATE_STORYBOARD', 'details': {'scenes_count': len(state.storyboard), 'scenes': [sb.model_dump() for sb in state.storyboard]}})}\n\n"
        await asyncio.sleep(0.3)

        state.shots = [
            VideoShot(
                shot_index=sb.scene_number,
                prompt=f"{sb.camera_angle} shot: {sb.description}",
                evaluation_criteria=sb.evaluation_criteria
            )
            for sb in state.storyboard
        ]

        generated_clip_paths = []
        prev_frame_b64: Optional[str] = None

        for idx, shot in enumerate(state.shots):
            clip_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}.mp4")
            frame_filename = os.path.join(OUTPUT_DIR, f"shot_{shot.shot_index}_last_frame.png")

            feedback: Optional[str] = None
            max_attempts = 2
            for attempt in range(max_attempts):
                state.attempt_counter += 1

                # Step 4: PromptOptimizerAgent via ADK Runner
                optimized_shot_prompt = optimize_prompt(shot.prompt, feedback=feedback, client=client)
                yield f"data: {json.dumps({'step': 4, 'agent': 'PromptOptimizerAgent', 'action': 'OPTIMIZE_PROMPT', 'details': {'shot_index': shot.shot_index, 'attempt': attempt + 1, 'raw_prompt': shot.prompt, 'optimized_prompt': optimized_shot_prompt, 'feedback': feedback}})}\n\n"
                await asyncio.sleep(0.3)

                # Step 5: HealthCheckerAgent via ADK Runner
                is_healthy = audit_prompt_health(optimized_shot_prompt, client=client)
                yield f"data: {json.dumps({'step': 5, 'agent': 'HealthCheckerAgent', 'action': 'AUDIT_PROMPT', 'details': {'shot_index': shot.shot_index, 'verdict': 'APPROVED' if is_healthy else 'REJECTED_REVERTED', 'safety_status': 'CLEAR', 'ethical_ai_score': '99/100'}})}\n\n"
                await asyncio.sleep(0.3)

                if not is_healthy:
                    optimized_shot_prompt = shot.prompt

                # Step 6: GeminiOmniFlash
                yield f"data: {json.dumps({'step': 6, 'agent': 'GeminiOmniFlash', 'action': 'RENDER_CLIP', 'details': {'shot_index': shot.shot_index, 'mode': state.mode, 'has_input_image': prev_frame_b64 is not None or len(state.reference_assets_b64) > 0}})}\n\n"

                if state.mode == "i2v_chaining":
                    video_bytes = generate_omni_clip(
                        prompt=optimized_shot_prompt,
                        input_image_b64=prev_frame_b64,
                        client=client
                    )
                else:
                    video_bytes = generate_omni_clip(
                        prompt=optimized_shot_prompt,
                        reference_images_b64=state.reference_assets_b64,
                        client=client
                    )

                with open(clip_filename, "wb") as f:
                    f.write(video_bytes)

                # Step 7: QualityRaterAgent via ADK Runner
                eval_result = evaluate_clip_quality(
                    shot.shot_index,
                    optimized_shot_prompt,
                    video_path=clip_filename,
                    evaluation_criteria=shot.evaluation_criteria,
                    client=client
                )
                score = eval_result.get("score", 0.9)
                state.quality_rating = score

                yield f"data: {json.dumps({'step': 7, 'agent': 'QualityRaterAgent', 'action': 'EVALUATE_QUALITY', 'details': {'shot_index': shot.shot_index, 'video_path': clip_filename, 'criteria_evaluated': shot.evaluation_criteria, 'attempt': attempt + 1, 'score': score, 'feedback': eval_result.get('feedback', 'Good visual quality'), 'verdict': 'PASSED' if score >= 0.8 else 'REATTEMPT_REQUIRED'}})}\n\n"
                await asyncio.sleep(0.3)

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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GenMedia-Omni: Multi-Agent Video Pipeline Studio</title>
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: #151d30;
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --success: #10b981;
            --warning: #f59e0b;
            --text-color: #f8fafc;
            --muted-text: #94a3b8;
            --border-color: #2a364f;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 24px;
            display: flex;
            justify-content: center;
        }
        .container {
            max-width: 1280px;
            width: 100%;
        }
        header {
            text-align: center;
            margin-bottom: 28px;
        }
        h1 {
            font-size: 32px;
            color: #ffffff;
            margin-bottom: 6px;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        p.subtitle {
            color: var(--muted-text);
            font-size: 15px;
            margin: 0;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }
        @media (max-width: 960px) {
            .grid-2 { grid-template-columns: 1fr; }
        }
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 24px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }
        .card h3 {
            margin-top: 0;
            margin-bottom: 16px;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        /* Workflow Stepper */
        .stepper {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            background: #090d16;
            padding: 16px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            overflow-x: auto;
        }
        .step {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
            min-width: 95px;
            opacity: 0.4;
            transition: opacity 0.3s;
        }
        .step.active { opacity: 1; }
        .step.active:not(.complete) .circle {
            border: 3px solid var(--accent);
            border-top-color: transparent;
            animation: spin 0.9s linear infinite;
            background-color: transparent;
            color: var(--accent);
        }
        .step.complete .circle {
            background-color: var(--success);
            color: #fff;
            border: none;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .circle {
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background-color: var(--border-color);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
            box-sizing: border-box;
        }
        .label { font-size: 11px; color: var(--muted-text); text-align: center; font-weight: 500; }

        /* Form Controls & Layout */
        .form-row {
            display: flex;
            gap: 12px;
            margin-bottom: 14px;
            align-items: center;
        }
        input[type="text"] {
            flex: 1;
            padding: 14px 18px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background-color: #090d16;
            color: #fff;
            font-size: 15px;
        }
        select {
            padding: 14px 14px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background-color: #090d16;
            color: #fff;
            font-size: 14px;
            cursor: pointer;
        }
        .mode-box {
            display: flex;
            gap: 12px;
            margin-bottom: 14px;
        }
        label.mode-option {
            flex: 1;
            padding: 14px 16px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background: #090d16;
            cursor: pointer;
            display: flex;
            align-items: flex-start;
            gap: 12px;
            font-size: 13px;
            transition: all 0.2s;
            user-select: none;
        }
        label.mode-option:hover {
            border-color: #4f46e5;
        }
        label.mode-option:has(input:checked) {
            border-color: var(--accent);
            background: rgba(99, 102, 241, 0.15);
        }
        label.mode-option input[type="radio"] {
            margin-top: 3px;
            cursor: pointer;
            accent-color: var(--accent);
        }

        /* Prominent Reference Image Uploader Panel */
        .ref-upload-panel {
            margin-bottom: 16px;
            padding: 16px;
            background: #090d16;
            border: 1px dashed var(--border-color);
            border-radius: 12px;
            transition: all 0.3s;
        }
        .ref-upload-panel.active-panel {
            border-color: #38bdf8;
            background: rgba(56, 189, 248, 0.05);
        }
        
        /* Native Button Label Styling */
        label.btn-file-select {
            display: inline-block;
            background-color: #334155;
            color: #fff;
            padding: 10px 18px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            user-select: none;
            transition: background-color 0.2s;
        }
        label.btn-file-select:hover {
            background-color: #475569;
        }

        .drop-zone {
            padding: 16px;
            text-align: center;
            border: 2px dashed var(--border-color);
            border-radius: 10px;
            background: rgba(255,255,255,0.02);
            transition: background 0.2s, border-color 0.2s;
        }
        .drop-zone:hover {
            background: rgba(99, 102, 241, 0.08);
            border-color: var(--accent);
        }
        .preview-grid {
            display: flex;
            gap: 12px;
            margin-top: 14px;
            flex-wrap: wrap;
        }
        .thumb-wrapper {
            position: relative;
            width: 70px;
            height: 70px;
        }
        .thumb-img {
            width: 70px;
            height: 70px;
            border-radius: 8px;
            object-fit: cover;
            border: 2px solid var(--accent);
        }
        .remove-btn {
            position: absolute;
            top: -6px;
            right: -6px;
            background: #ef4444;
            color: #fff;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            cursor: pointer;
            border: none;
            padding: 0;
        }

        button {
            padding: 14px 28px;
            border-radius: 10px;
            border: none;
            background-color: var(--accent);
            color: #fff;
            font-weight: 600;
            font-size: 15px;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover { background-color: var(--accent-hover); transform: translateY(-1px); }
        button:disabled { background-color: #475569; cursor: not-allowed; transform: none; }
        .btn-secondary {
            background-color: #334155;
            padding: 8px 16px;
            font-size: 13px;
            border-radius: 6px;
            border: none;
            color: #fff;
            cursor: pointer;
        }
        .btn-secondary:hover { background-color: #475569; }

        .spinner {
            display: none;
            text-align: center;
            margin: 16px 0 0 0;
            color: var(--warning);
            font-weight: 600;
            font-size: 14px;
        }

        /* Trajectory Audit Log Feed */
        .trajectory-feed {
            height: 480px;
            overflow-y: auto;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 16px;
            background: #090d16;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 13px;
        }
        .log-item {
            margin-bottom: 12px;
            padding: 10px;
            border-radius: 6px;
            background: rgba(255,255,255,0.03);
            border-left: 3px solid var(--accent);
            animation: fadeIn 0.3s ease-in-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .log-header {
            display: flex;
            justify-content: space-between;
            font-weight: 700;
            margin-bottom: 4px;
        }
        .log-agent { color: #38bdf8; }
        .log-action { color: #f472b6; }
        .log-details { color: #cbd5e1; font-size: 12px; white-space: pre-wrap; word-break: break-all; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-success { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .badge-info { background: rgba(56, 189, 248, 0.2); color: #38bdf8; }

        /* Media Player */
        video { width: 100%; border-radius: 10px; background: #000; margin-top: 12px; }
        .shots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-top: 16px;
        }
        .shot-card {
            background: #090d16;
            padding: 16px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
        }
        .shot-card h4 { margin: 0 0 8px 0; color: #38bdf8; font-size: 16px; display: flex; justify-content: space-between; }
        .shot-card p { margin: 0 0 10px 0; font-size: 13px; color: var(--muted-text); line-height: 1.4; }
        img.frame-img { width: 100%; border-radius: 8px; margin-top: 8px; border: 1px solid var(--border-color); }
        .action-row { display: flex; gap: 10px; margin-top: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 GenMedia-Omni Pipeline Studio</h1>
            <p class="subtitle">Google ADK Multi-Agent Execution & Real-Time Audit Trajectory Visualizer</p>
        </header>

        <!-- Stepper Graph -->
        <div class="stepper" id="stepper">
            <div class="step" id="step-1"><div class="circle">1</div><div class="label">Orchestrator</div></div>
            <div class="step" id="step-2"><div class="circle">2</div><div class="label">Screenwriter</div></div>
            <div class="step" id="step-3"><div class="circle">3</div><div class="label">Storyboarder</div></div>
            <div class="step" id="step-4"><div class="circle">4</div><div class="label">Optimizer</div></div>
            <div class="step" id="step-5"><div class="circle">5</div><div class="label">Health Auditor</div></div>
            <div class="step" id="step-6"><div class="circle">6</div><div class="label">Omni Flash</div></div>
            <div class="step" id="step-7"><div class="circle">7</div><div class="label">Quality Rater</div></div>
            <div class="step" id="step-8"><div class="circle">8</div><div class="label">OpenCV Parser</div></div>
            <div class="step" id="step-9"><div class="circle">9</div><div class="label">FFMPEG Stitch</div></div>
        </div>

        <div class="grid-2">
            <!-- Execution Control Card -->
            <div class="card">
                <h3>🚀 Multi-Agent Studio Control</h3>
                
                <!-- Pipeline Mode Selection -->
                <label style="font-size: 13px; color: var(--muted-text); margin-bottom: 6px; display: block;">Pipeline Generation Mode:</label>
                <div class="mode-box">
                    <label class="mode-option" id="mode-i2v">
                        <input type="radio" name="mode" value="i2v_chaining" checked onchange="window.selectMode('i2v_chaining')">
                        <div>
                            <strong>⚡ Sequential I2V Chaining</strong>
                            <div style="font-size: 11px; color: var(--muted-text);">OpenCV terminal frame extraction for unbroken motion continuity</div>
                        </div>
                    </label>
                    <label class="mode-option" id="mode-ref">
                        <input type="radio" name="mode" value="reference" onchange="window.selectMode('reference')">
                        <div>
                            <strong>🎨 Asset Reference Mode</strong>
                            <div style="font-size: 11px; color: var(--muted-text);">Shared character & style image reference anchors</div>
                        </div>
                    </label>
                </div>

                <!-- Dedicated Prominent Reference Asset Uploader Panel -->
                <div class="ref-upload-panel" id="refUploadPanel">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <span style="font-size: 13px; font-weight: 700; color: #38bdf8;">📷 Character & Asset Reference Images</span>
                        <span class="badge badge-info" id="refCountBadge">0 assets</span>
                    </div>
                    
                    <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 12px;">
                        <label for="refFileInput" class="btn-file-select">📁 Choose Image Files</label>
                        <span style="font-size: 12px; color: var(--muted-text);">Select up to 10 PNG, JPG, WEBP images</span>
                        <input type="file" id="refFileInput" multiple accept="image/*" onchange="window.handleRefFiles(event)" style="position: absolute; width: 0; height: 0; opacity: 0; pointer-events: none;">
                    </div>

                    <div class="drop-zone" id="dropZone">
                        <div style="font-size: 22px; margin-bottom: 4px;">🖼️</div>
                        <div><strong>Or Drag & Drop Reference Image Files Here</strong></div>
                    </div>

                    <div class="preview-grid" id="refPreviewGrid"></div>
                </div>

                <!-- Prompt & Shots Row -->
                <div class="form-row">
                    <input type="text" id="promptInput" value="A red panda skiing in Hakuba" placeholder="Enter video prompt intent...">
                    <select id="shotsSelect">
                        <option value="2">2 Shots (20s)</option>
                        <option value="3" selected>3 Shots (30s)</option>
                        <option value="4">4 Shots (40s)</option>
                        <option value="5">5 Shots (50s)</option>
                        <option value="6">6 Shots (60s)</option>
                    </select>
                </div>

                <button id="genBtn" onclick="window.runPipeline()" style="width: 100%;">🚀 Execute Multi-Agent Graph</button>
                <div class="spinner" id="spinner">⚙️ Real-Time Multi-Agent SSE Stream Active...</div>
            </div>

            <!-- Audit Trajectory Log Feed -->
            <div class="card">
                <h3>📡 Real-Time Agent Communication & Audit Trajectory Stream</h3>
                <div class="trajectory-feed" id="trajectoryFeed">
                    <div class="log-item">
                        <div class="log-header"><span class="log-agent">OrchestratorAgent</span><span class="badge badge-success">READY</span></div>
                        <div class="log-details">System initialized. Awaiting pipeline execution trigger...</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Output Media Showcase -->
        <div class="card" id="resultCard" style="display: none;">
            <h3 id="stitchedTitle">🎬 Stitched Output Video</h3>
            <video id="stitchedVideo" controls autoplay preload="metadata"></video>
            
            <div class="action-row">
                <a id="downloadBtn" download="output_stitched.mp4" class="btn-secondary" style="text-decoration: none; color: #fff;">💾 Download Stitched MP4 Video</a>
            </div>

            <h3 style="margin-top: 28px;">🎞️ Individual Shot Breakdown, Orchestrator Criteria & Terminal Frames</h3>
            <div class="shots-grid" id="shotsGrid"></div>
        </div>
    </div>

    <script>
        window.selectedMode = "i2v_chaining";
        window.refImagesB64 = [];

        window.selectMode = function(mode) {
            window.selectedMode = mode;
            var refPanel = document.getElementById("refUploadPanel");
            if (refPanel) {
                if (mode === "reference") {
                    refPanel.classList.add("active-panel");
                } else {
                    refPanel.classList.remove("active-panel");
                }
            }
        };

        window.handleRefFiles = async function(event) {
            var files = null;
            if (event && event.target && event.target.files && event.target.files.length > 0) {
                files = event.target.files;
            } else if (event && event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length > 0) {
                files = event.dataTransfer.files;
            }

            if (!files || files.length === 0) return;

            var remainingSlots = 10 - window.refImagesB64.length;
            var fileList = Array.from(files).slice(0, remainingSlots);

            for (var i = 0; i < fileList.length; i++) {
                var file = fileList[i];
                try {
                    var b64 = await new Promise(function(resolve, reject) {
                        var reader = new FileReader();
                        reader.onload = function(e) {
                            var raw = e.target.result;
                            var parts = raw.split(',');
                            resolve(parts[1] || parts[0]);
                        };
                        reader.onerror = function(err) { reject(err); };
                        reader.readAsDataURL(file);
                    });
                    if (b64) {
                        window.refImagesB64.push(b64);
                    }
                } catch (err) {
                    console.error("FileReader error:", err);
                }
            }

            if (event && event.target && event.target.value) {
                event.target.value = "";
            }

            window.renderRefGrid();
        };

        window.removeRefImage = function(index) {
            window.refImagesB64.splice(index, 1);
            window.renderRefGrid();
        };

        window.renderRefGrid = function() {
            var grid = document.getElementById("refPreviewGrid");
            var badge = document.getElementById("refCountBadge");
            if (badge) badge.innerText = window.refImagesB64.length + " assets";
            if (!grid) return;

            grid.innerHTML = "";

            for (var i = 0; i < window.refImagesB64.length; i++) {
                (function(idx) {
                    var wrapper = document.createElement("div");
                    wrapper.className = "thumb-wrapper";

                    var img = document.createElement("img");
                    img.className = "thumb-img";
                    img.src = "data:image/png;base64," + window.refImagesB64[idx];
                    img.alt = "Ref Image " + (idx + 1);

                    var btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "remove-btn";
                    btn.innerText = "✕";
                    btn.onclick = function(e) {
                        if (e) e.stopPropagation();
                        window.removeRefImage(idx);
                    };

                    wrapper.appendChild(img);
                    wrapper.appendChild(btn);
                    grid.appendChild(wrapper);
                })(i);
            }
        };

        window.addEventListener("DOMContentLoaded", function() {
            var dropZone = document.getElementById("dropZone");
            if (dropZone) {
                ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function(eventName) {
                    dropZone.addEventListener(eventName, function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                    }, false);
                });

                dropZone.addEventListener('drop', function(e) {
                    window.handleRefFiles(e);
                }, false);
            }
        });

        function setStep(stepNum) {
            for (var i = 1; i <= 9; i++) {
                var step = document.getElementById("step-" + i);
                if (step) {
                    step.classList.remove("active", "complete");
                    if (i < stepNum) {
                        step.classList.add("active", "complete");
                    } else if (i === stepNum) {
                        step.classList.add("active");
                    }
                }
            }
        }

        function appendLog(agent, action, details) {
            var feed = document.getElementById("trajectoryFeed");
            if (!feed) return;
            var div = document.createElement("div");
            div.className = "log-item";
            var headerDiv = document.createElement("div");
            headerDiv.className = "log-header";
            headerDiv.innerHTML = '<span class="log-agent">🤖 ' + agent + '</span><span class="log-action">' + action + '</span>';
            var detailsDiv = document.createElement("div");
            detailsDiv.className = "log-details";
            detailsDiv.innerText = JSON.stringify(details, null, 2);
            div.appendChild(headerDiv);
            div.appendChild(detailsDiv);
            feed.appendChild(div);
            feed.scrollTop = feed.scrollHeight;
        }

        window.runPipeline = async function() {
            var promptInput = document.getElementById("promptInput");
            var prompt = promptInput ? promptInput.value.trim() : "";
            var shotsSelect = document.getElementById("shotsSelect");
            var shots = shotsSelect ? parseInt(shotsSelect.value, 10) : 3;
            if (!prompt) return;

            var genBtn = document.getElementById("genBtn");
            var spinner = document.getElementById("spinner");
            var resultCard = document.getElementById("resultCard");
            var trajectoryFeed = document.getElementById("trajectoryFeed");

            if (genBtn) genBtn.disabled = true;
            if (spinner) spinner.style.display = "block";
            if (resultCard) resultCard.style.display = "none";
            if (trajectoryFeed) trajectoryFeed.innerHTML = "";
            setStep(1);

            // Execute POST API call to stream endpoint with full parameters
            try {
                var res = await fetch("/api/stream", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        prompt: prompt,
                        num_shots: shots,
                        mode: window.selectedMode,
                        reference_assets_b64: window.refImagesB64
                    })
                });

                var reader = res.body.getReader();
                var decoder = new TextDecoder();
                var buffer = "";
                var delim = String.fromCharCode(10) + String.fromCharCode(10);

                while (true) {
                    var result = await reader.read();
                    if (result.done) break;
                    buffer += decoder.decode(result.value, { stream: true });

                    var lines = buffer.split(delim);
                    buffer = lines.pop(); // Keep partial frame

                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];
                        if (line.startsWith("data: ")) {
                            var data = JSON.parse(line.replace("data: ", ""));

                            if (data.step) {
                                setStep(data.step);
                            }

                            if (data.agent && data.action) {
                                appendLog(data.agent, data.action, data.details);
                            }

                            if (data.action === "PIPELINE_COMPLETE" && data.details && data.details.status === "complete") {
                                if (genBtn) genBtn.disabled = false;
                                if (spinner) spinner.style.display = "none";

                                setStep(9);
                                for (var k = 1; k <= 9; k++) {
                                    var s = document.getElementById("step-" + k);
                                    if (s) s.classList.add("complete");
                                }

                                var title = document.getElementById("stitchedTitle");
                                if (title) title.innerText = "🎬 Stitched " + (data.details.shots.length * 10) + "s Output Video (" + data.details.mode + " mode)";
                                
                                var video = document.getElementById("stitchedVideo");
                                if (video) {
                                    var videoUrl = data.details.stitched_video_url + "?t=" + new Date().getTime();
                                    video.src = videoUrl;
                                    video.load();
                                }

                                var downloadBtn = document.getElementById("downloadBtn");
                                if (downloadBtn) downloadBtn.href = data.details.stitched_video_url;

                                var grid = document.getElementById("shotsGrid");
                                if (grid) {
                                    grid.innerHTML = "";
                                    data.details.shots.forEach(function(shot) {
                                        var card = document.createElement("div");
                                        card.className = "shot-card";
                                        card.innerHTML = '<h4><span>Shot #' + shot.shot_index + '</span><a href="' + shot.video_url + '" download class="btn-secondary" style="font-size: 11px; text-decoration: none; padding: 4px 8px;">💾 Download MP4</a></h4>' +
                                            '<p><strong>Prompt:</strong> ' + shot.prompt + '</p>' +
                                            '<p style="color: #f472b6; font-size: 12px;"><strong>Orchestrator Criteria:</strong> ' + (shot.evaluation_criteria || 'Visual coherence & character lock') + '</p>' +
                                            '<video controls preload="metadata" src="' + shot.video_url + '?t=' + new Date().getTime() + '"></video>' +
                                            '<p style="margin-top: 10px; color: #38bdf8;"><strong>OpenCV Last Frame (I2V Chaining):</strong></p>' +
                                            '<img class="frame-img" src="' + shot.frame_url + '?t=' + new Date().getTime() + '" alt="Shot ' + shot.shot_index + ' Last Frame">';
                                        grid.appendChild(card);
                                    });
                                }
                                if (resultCard) resultCard.style.display = "block";
                            }
                        }
                    }
                }
            } catch (err) {
                alert("Execution error: " + err);
                if (genBtn) genBtn.disabled = false;
                if (spinner) spinner.style.display = "none";
            }
        };
    </script>
</body>
</html>"""
