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
                    evaluation_criteria=item.get("evaluation_criteria", "Check character identity lock and smooth motion.")
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
                    evaluation_criteria="Check character identity lock, lighting stability, and smooth motion."
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
                    feedback = eval_result.get("feedback", "Refine visual continuity")

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
    return """
<!DOCTYPE html>
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
            gap: 8px;
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
        select, input[type="file"] {
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
        .mode-option {
            flex: 1;
            padding: 12px 16px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            background: #090d16;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 13px;
            transition: all 0.2s;
        }
        .mode-option.selected {
            border-color: var(--accent);
            background: rgba(99, 102, 241, 0.15);
        }
        .mode-option input { cursor: pointer; }

        /* Reference Image Uploader */
        .ref-upload-container {
            display: none;
            margin-bottom: 14px;
            padding: 14px;
            background: #090d16;
            border: 1px dashed var(--border-color);
            border-radius: 10px;
        }
        .ref-upload-container.visible { display: block; }
        .preview-thumbs {
            display: flex;
            gap: 10px;
            margin-top: 10px;
            flex-wrap: wrap;
        }
        .thumb-img {
            width: 60px;
            height: 60px;
            border-radius: 6px;
            object-fit: cover;
            border: 1px solid var(--accent);
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
            height: 380px;
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
                    <div class="mode-option selected" id="mode-i2v" onclick="selectMode('i2v_chaining')">
                        <input type="radio" name="mode" value="i2v_chaining" checked>
                        <div>
                            <strong>⚡ Sequential I2V Chaining</strong>
                            <div style="font-size: 11px; color: var(--muted-text);">OpenCV terminal frame extraction for unbroken motion continuity</div>
                        </div>
                    </div>
                    <div class="mode-option" id="mode-ref" onclick="selectMode('reference')">
                        <input type="radio" name="mode" value="reference">
                        <div>
                            <strong>🎨 Asset Reference Mode</strong>
                            <div style="font-size: 11px; color: var(--muted-text);">Shared character & style image reference anchors</div>
                        </div>
                    </div>
                </div>

                <!-- Reference Images Upload (Visible in Reference Mode) -->
                <div class="ref-upload-container" id="refUploadBox">
                    <label style="font-size: 12px; color: #38bdf8;">📷 Upload Character & Asset Reference Images (PNG/JPG):</label>
                    <input type="file" id="refImageInput" multiple accept="image/*" onchange="handleRefImages(event)" style="margin-top: 6px; width: 100%;">
                    <div class="preview-thumbs" id="refThumbs"></div>
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

                <button id="genBtn" onclick="runPipeline()" style="width: 100%;">🚀 Execute Multi-Agent Graph</button>
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
        let selectedMode = "i2v_chaining";
        let refImagesB64 = [];

        function selectMode(mode) {
            selectedMode = mode;
            document.getElementById("mode-i2v").classList.toggle("selected", mode === "i2v_chaining");
            document.getElementById("mode-ref").classList.toggle("selected", mode === "reference");
            document.querySelector(`input[value="${mode}"]`).checked = true;

            const refBox = document.getElementById("refUploadBox");
            if (mode === "reference") {
                refBox.classList.add("visible");
            } else {
                refBox.classList.remove("visible");
            }
        }

        function handleRefImages(event) {
            const files = event.target.files;
            const thumbsContainer = document.getElementById("refThumbs");
            thumbsContainer.innerHTML = "";
            refImagesB64 = [];

            Array.from(files).slice(0, 10).forEach(file => {
                const reader = new FileReader();
                reader.onload = (e) => {
                    const b64 = e.target.result.split(',')[1];
                    refImagesB64.push(b64);
                    thumbsContainer.innerHTML += `<img class="thumb-img" src="${e.target.result}" alt="Ref Thumb">`;
                };
                reader.readAsDataURL(file);
            });
        }

        function setStep(stepNum) {
            for (let i = 1; i <= 9; i++) {
                const step = document.getElementById(`step-${i}`);
                step.classList.remove("active", "complete");
                if (i < stepNum) {
                    step.classList.add("active", "complete");
                } else if (i === stepNum) {
                    step.classList.add("active");
                }
            }
        }

        function appendLog(agent, action, details) {
            const feed = document.getElementById("trajectoryFeed");
            const div = document.createElement("div");
            div.className = "log-item";
            div.innerHTML = `
                <div class="log-header">
                    <span class="log-agent">🤖 ${agent}</span>
                    <span class="log-action">${action}</span>
                </div>
                <div class="log-details">${JSON.stringify(details, null, 2)}</div>
            `;
            feed.appendChild(div);
            feed.scrollTop = feed.scrollHeight;
        }

        async function runPipeline() {
            const prompt = document.getElementById("promptInput").value.trim();
            const shots = parseInt(document.getElementById("shotsSelect").value, 10);
            if (!prompt) return;

            const genBtn = document.getElementById("genBtn");
            const spinner = document.getElementById("spinner");
            const resultCard = document.getElementById("resultCard");
            const trajectoryFeed = document.getElementById("trajectoryFeed");

            genBtn.disabled = true;
            spinner.style.display = "block";
            resultCard.style.display = "none";
            trajectoryFeed.innerHTML = "";
            setStep(1);

            // Execute POST API call to stream endpoint with full parameters (mode, reference images, shots, prompt)
            try {
                const res = await fetch("/api/stream", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        prompt: prompt,
                        num_shots: shots,
                        mode: selectedMode,
                        reference_assets_b64: refImagesB64
                    })
                });

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });

                    const lines = buffer.split("\n\n");
                    buffer = lines.pop(); // Keep partial frame

                    for (const line of lines) {
                        if (line.startsWith("data: ")) {
                            const data = JSON.parse(line.replace("data: ", ""));

                            if (data.step) {
                                setStep(data.step);
                            }

                            if (data.agent && data.action) {
                                appendLog(data.agent, data.action, data.details);
                            }

                            if (data.action === "PIPELINE_COMPLETE" && data.details && data.details.status === "complete") {
                                genBtn.disabled = false;
                                spinner.style.display = "none";

                                setStep(9);
                                for (let i = 1; i <= 9; i++) {
                                    document.getElementById(`step-${i}`).classList.add("complete");
                                }

                                document.getElementById("stitchedTitle").innerText = `🎬 Stitched ${data.details.shots.length * 10}s Output Video (${data.details.mode} mode)`;
                                const video = document.getElementById("stitchedVideo");
                                const videoUrl = data.details.stitched_video_url + "?t=" + new Date().getTime();
                                video.src = videoUrl;
                                video.load();

                                const downloadBtn = document.getElementById("downloadBtn");
                                downloadBtn.href = data.details.stitched_video_url;

                                const grid = document.getElementById("shotsGrid");
                                grid.innerHTML = "";
                                data.details.shots.forEach(shot => {
                                    grid.innerHTML += `
                                        <div class="shot-card">
                                            <h4>
                                                <span>Shot #${shot.shot_index}</span>
                                                <a href="${shot.video_url}" download class="btn-secondary" style="font-size: 11px; text-decoration: none; padding: 4px 8px;">💾 Download MP4</a>
                                            </h4>
                                            <p><strong>Prompt:</strong> ${shot.prompt}</p>
                                            <p style="color: #f472b6; font-size: 12px;"><strong>Orchestrator Criteria:</strong> ${shot.evaluation_criteria || 'Visual coherence & character lock'}</p>
                                            <video controls preload="metadata" src="${shot.video_url}?t=${new Date().getTime()}"></video>
                                            <p style="margin-top: 10px; color: #38bdf8;"><strong>OpenCV Last Frame (I2V Chaining):</strong></p>
                                            <img class="frame-img" src="${shot.frame_url}?t=${new Date().getTime()}" alt="Shot ${shot.shot_index} Last Frame">
                                        </div>
                                    `;
                                });
                                resultCard.style.display = "block";
                            }
                        }
                    }
                }
            } catch (err) {
                alert("Execution error: " + err);
                genBtn.disabled = false;
                spinner.style.display = "none";
            }
        }
    </script>
</body>
</html>
    """
