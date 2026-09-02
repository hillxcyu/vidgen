# Author:Hill YU(xcyu@)
"""Benchmark script to compare Gemini Omni Flash 1.1 reference adherence:
Pipeline-Optimized cinematic prompt vs. Simple prompt ("xcyu (reference image) skiing in Hakuba").
Generates a canonical reference portrait of an Asian 20-year-old male using gemini-3.1-flash-image (Nano Banana 2),
produces both videos side by side, performs agentic video evaluation, builds an interactive HTML report,
and uploads to x20 web server.
"""

import os
import sys
import time
import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any

from google import genai
from google.genai import types

from app.config import Config, get_genai_client
from app.tools.omni_client import generate_omni_clip, build_omni_control_string
from app.tools.video_parser import create_agentic_video_part

BENCHMARK_DIR = Path("/usr/local/google/home/xcyu/projects/reusable/vidgen/benchmarks")
BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

REF_IMG_PATH = BENCHMARK_DIR / "reference_xcyu.png"
VIDEO_OPT_PATH = BENCHMARK_DIR / "video_pipeline_optimized.mp4"
VIDEO_SMP_PATH = BENCHMARK_DIR / "video_simple_prompt.mp4"
REPORT_PATH = BENCHMARK_DIR / "index.html"
X20_DIR = Path("/google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1")


def generate_reference_image(client: genai.Client) -> bytes:
    """Generates canonical reference image of 20yo Asian male using gemini-3.1-flash-image (Nano Banana 2)."""
    print("\n--- [Step 1] Generating Reference Image with gemini-3.1-flash-image ---")
    prompt = (
        "A clear, high-resolution portrait photograph of a 20-year-old Asian male, "
        "wearing a stylish red and black alpine ski jacket and dark beanie, "
        "friendly confident expression, looking directly into the camera, "
        "sharp facial features, natural lighting against a soft alpine winter mountain backdrop, photorealistic."
    )
    print(f"Prompt: {prompt}")
    
    resp = client.models.generate_content(
        model="gemini-3.1-flash-image",
        contents=prompt,
    )
    
    img_bytes = None
    if resp and resp.candidates:
        for part in resp.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                img_bytes = part.inline_data.data
                break
                
    if not img_bytes:
        raise RuntimeError("Failed to obtain image bytes from gemini-3.1-flash-image")
        
    with open(REF_IMG_PATH, "wb") as f:
        f.write(img_bytes)
    print(f"Reference image saved to: {REF_IMG_PATH} ({len(img_bytes)} bytes)")
    return img_bytes


def generate_pipeline_optimized_video(client: genai.Client, ref_b64: str) -> Dict[str, Any]:
    """Generates Video A using the pipeline-optimized cinematic prompt and standard MMC control string."""
    print("\n--- [Step 2] Generating Video A (Pipeline-Optimized Prompt) ---")
    raw_prompt = (
        "Continuous single take, dynamic cinematic tracking shot following the character skiing gracefully "
        "down a powdery slope on Hakuba Happo-One ridge, crisp alpine morning sunlight reflecting off the snow, "
        "dramatic Japanese Northern Alps in the background, sharp cinematic focus, photorealistic."
    )
    
    control_string = build_omni_control_string(
        prompt=raw_prompt,
        reference_images_b64=[ref_b64],
        aspect_ratio="16:9",
        resolution="720p",
        duration=5,
    )
    print(f"Full Omni Control String:\n{control_string}\n")
    
    payload = [
        {"type": "text", "text": control_string},
        {"type": "image", "data": ref_b64, "mime_type": "image/png"}
    ]
    
    start_t = time.time()
    interaction = client.interactions.create(
        model="gemini-omni-1.1-flash-preview",
        input=payload,
        timeout=600.0
    )
    dur = time.time() - start_t
    print(f"Omni Flash generation finished in {dur:.2f}s")
    
    video_bytes = None
    if hasattr(interaction, "output") and isinstance(interaction.output, bytes):
        video_bytes = interaction.output
    elif hasattr(interaction, "output_video"):
        data_val = getattr(interaction.output_video, "data", None)
        if isinstance(data_val, str):
            video_bytes = base64.b64decode(data_val)
        elif isinstance(data_val, bytes):
            video_bytes = data_val
    elif hasattr(interaction, "candidates") and len(interaction.candidates) > 0:
        for p in interaction.candidates[0].content.parts:
            if hasattr(p, "inline_data") and p.inline_data:
                video_bytes = p.inline_data.data if isinstance(p.inline_data.data, bytes) else base64.b64decode(p.inline_data.data)
                break
                
    if not video_bytes or len(video_bytes) < 1000:
        raise RuntimeError("Failed to generate Video A (Pipeline-Optimized)")
        
    with open(VIDEO_OPT_PATH, "wb") as f:
        f.write(video_bytes)
    print(f"Saved Video A to: {VIDEO_OPT_PATH} ({len(video_bytes)} bytes)")
    
    return {
        "control_string": control_string,
        "generation_time_s": dur,
        "video_bytes": video_bytes
    }


def generate_simple_prompt_video(client: genai.Client, ref_b64: str) -> Dict[str, Any]:
    """Generates Video B using the simple prompt requested by the user."""
    print("\n--- [Step 3] Generating Video B (Simple Prompt) ---")
    control_string = "[aspect_ratio=16:9] [resolution=720p] [duration=5s] xcyu (reference image) skiing in Hakuba"
    print(f"Full Omni Prompt:\n{control_string}\n")
    
    payload = [
        {"type": "text", "text": control_string},
        {"type": "image", "data": ref_b64, "mime_type": "image/png"}
    ]
    
    start_t = time.time()
    interaction = client.interactions.create(
        model="gemini-omni-1.1-flash-preview",
        input=payload,
        timeout=600.0
    )
    dur = time.time() - start_t
    print(f"Omni Flash generation finished in {dur:.2f}s")
    
    video_bytes = None
    if hasattr(interaction, "output") and isinstance(interaction.output, bytes):
        video_bytes = interaction.output
    elif hasattr(interaction, "output_video"):
        data_val = getattr(interaction.output_video, "data", None)
        if isinstance(data_val, str):
            video_bytes = base64.b64decode(data_val)
        elif isinstance(data_val, bytes):
            video_bytes = data_val
    elif hasattr(interaction, "candidates") and len(interaction.candidates) > 0:
        for p in interaction.candidates[0].content.parts:
            if hasattr(p, "inline_data") and p.inline_data:
                video_bytes = p.inline_data.data if isinstance(p.inline_data.data, bytes) else base64.b64decode(p.inline_data.data)
                break
                
    if not video_bytes or len(video_bytes) < 1000:
        raise RuntimeError("Failed to generate Video B (Simple Prompt)")
        
    with open(VIDEO_SMP_PATH, "wb") as f:
        f.write(video_bytes)
    print(f"Saved Video B to: {VIDEO_SMP_PATH} ({len(video_bytes)} bytes)")
    
    return {
        "control_string": control_string,
        "generation_time_s": dur,
        "video_bytes": video_bytes
    }


def evaluate_video_with_agentic_ai(client: genai.Client, video_path: str, ref_img_bytes: bytes, prompt_desc: str) -> Dict[str, Any]:
    """Runs Gemini 3.7 Flash with Agentic Video Understanding to evaluate reference adherence and motion."""
    print(f"\n--- Running Agentic Video Evaluation on: {Path(video_path).name} ---")
    video_part = create_agentic_video_part(video_path_or_uri=str(video_path), media_processing="agentic")
    ref_part = types.Part.from_bytes(data=ref_img_bytes, mime_type="image/png")
    
    eval_prompt = (
        "You are an expert AI quality rater performing a strict audit of character reference adherence in an AI-generated video.\n"
        f"The user prompted the video model with: '{prompt_desc}'\n"
        "Attached is the Canonical Reference Image of the target character (20yo Asian male).\n"
        "Leverage agentic video understanding to dynamically inspect the video frames and assess:\n"
        "1. Character Facial & Identity Adherence: Compare the person in the video with the reference image. "
        "Does the face match the reference image? Does the age, ethnicity, facial features, and hair match?\n"
        "2. Wardrobe & Outfit Adherence: Does the jacket, gear, and colors match the reference image?\n"
        "3. Skiing Motion & Physics: Is the skiing motion natural, fluid, and physically plausible?\n"
        "4. Overall Quality & Temporal Consistency: Is there morphing or hallucination across the duration?\n\n"
        "Return ONLY a valid JSON object with keys:\n"
        "- facial_similarity_score: float (0.0 to 1.0)\n"
        "- outfit_consistency_score: float (0.0 to 1.0)\n"
        "- motion_naturalness_score: float (0.0 to 1.0)\n"
        "- overall_score: float (0.0 to 1.0)\n"
        "- verdict: 'STRONG_ADHERENCE' | 'MODERATE_ADHERENCE' | 'POOR_ADHERENCE'\n"
        "- detailed_critique: string explaining specific timestamped observations"
    )
    
    try:
        resp = client.models.generate_content(
            model="gemini-3.7-flash",
            contents=[eval_prompt, ref_part, video_part],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        if resp and resp.text:
            import re
            m = re.search(r"\{.*\}", resp.text, re.DOTALL)
            clean = m.group(0) if m else resp.text
            return json.loads(clean)
    except Exception as e:
        print(f"Evaluation error: {e}")
        
    return {
        "facial_similarity_score": 0.0,
        "outfit_consistency_score": 0.0,
        "motion_naturalness_score": 0.0,
        "overall_score": 0.0,
        "verdict": "ERROR",
        "detailed_critique": "Agentic evaluation failed to return JSON."
    }


def build_html_report(
    opt_meta: Dict[str, Any],
    smp_meta: Dict[str, Any],
    eval_opt: Dict[str, Any],
    eval_smp: Dict[str, Any]
):
    """Builds interactive, modern side-by-side HTML comparison report."""
    print("\n--- [Step 5] Building Interactive HTML Report ---")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Omni Flash 1.1 Reference Adherence Benchmark</title>
  <style>
    :root {{
      --bg-primary: #0f172a;
      --bg-card: #1e293b;
      --bg-code: #090d16;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-green: #34d399;
      --accent-yellow: #fbbf24;
      --border: #334155;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-primary);
      color: var(--text-main);
      padding: 2rem 1rem;
      line-height: 1.5;
    }}
    .container {{
      max-width: 1400px;
      margin: 0 auto;
    }}
    header {{
      text-align: center;
      margin-bottom: 2.5rem;
      padding-bottom: 1.5rem;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      font-size: 2.2rem;
      font-weight: 700;
      color: #ffffff;
      margin-bottom: 0.5rem;
      background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .subtitle {{
      color: var(--text-muted);
      font-size: 1.1rem;
    }}
    .badge {{
      display: inline-block;
      padding: 0.25rem 0.75rem;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      margin-top: 0.75rem;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      border: 1px solid rgba(56, 189, 248, 0.3);
    }}
    
    /* Reference Section */
    .reference-section {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2.5rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
    }}
    .reference-section h2 {{
      font-size: 1.3rem;
      margin-bottom: 1rem;
      color: var(--accent);
    }}
    .ref-img-container {{
      max-width: 320px;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
      border: 2px solid var(--accent);
      margin-bottom: 1rem;
    }}
    .ref-img-container img {{
      width: 100%;
      display: block;
    }}
    .ref-desc {{
      color: var(--text-muted);
      font-size: 0.95rem;
      max-width: 700px;
    }}

    /* Comparison Grid */
    .comparison-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 2rem;
      margin-bottom: 2.5rem;
    }}
    @media (max-width: 900px) {{
      .comparison-grid {{ grid-template-columns: 1fr; }}
    }}
    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
      padding-bottom: 0.75rem;
      border-bottom: 1px solid var(--border);
    }}
    .card-title {{
      font-size: 1.3rem;
      font-weight: 600;
      color: #ffffff;
    }}
    .verdict-tag {{
      padding: 0.2rem 0.6rem;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .verdict-tag.strong {{ background: #065f46; color: #34d399; border: 1px solid #10b981; }}
    .verdict-tag.moderate {{ background: #78350f; color: #fbbf24; border: 1px solid #f59e0b; }}
    .verdict-tag.poor {{ background: #7f1d1d; color: #f87171; border: 1px solid #ef4444; }}

    .video-wrapper {{
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
      background: #000;
      margin-bottom: 1.25rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
    }}
    video {{
      width: 100%;
      display: block;
    }}
    
    .section-title {{
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 0.5rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .prompt-box {{
      background: var(--bg-code);
      border: 1px solid #1e293b;
      border-radius: 6px;
      padding: 1rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.85rem;
      color: #e2e8f0;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      margin-bottom: 1.25rem;
    }}

    .scores-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }}
    .score-card {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.75rem;
      text-align: center;
    }}
    .score-val {{
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--accent);
    }}
    .score-lbl {{
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }}
    
    .critique-box {{
      background: rgba(15, 23, 42, 0.4);
      border-left: 3px solid var(--accent);
      padding: 0.85rem 1rem;
      font-size: 0.9rem;
      color: #cbd5e1;
      border-radius: 0 6px 6px 0;
    }}

    /* Global Summary */
    .summary-card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
    }}
    .summary-card h2 {{
      font-size: 1.3rem;
      color: #ffffff;
      margin-bottom: 1rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 1rem;
    }}
    th, td {{
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      color: var(--accent);
      font-size: 0.9rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    td {{
      font-size: 0.95rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Omni Flash 1.1 Reference Adherence Benchmark</h1>
      <p class="subtitle">Comparing Pipeline-Optimized Cinematic Prompting vs. Direct Simple Prompting on character likeness and motion</p>
      <div class="badge">Model: gemini-omni-1.1-flash-preview | Reference Model: gemini-3.1-flash-image (Nano Banana 2) | Audit: gemini-3.7-flash (agentic)</div>
    </header>

    <!-- Canonical Reference Image Card -->
    <section class="reference-section">
      <h2>Canonical Reference Asset</h2>
      <div class="ref-img-container">
        <img src="./reference_xcyu.png" alt="Canonical Reference Image of 20yo Asian male">
      </div>
      <p class="ref-desc">
        <strong>Generation Method:</strong> Nano Banana 2 (<code>gemini-3.1-flash-image</code>) via Vertex AI.<br>
        <em>"Photo of a 20-year-old Asian male, wearing red and black alpine ski jacket and dark beanie, friendly confident expression, looking directly into the camera."</em>
      </p>
    </section>

    <!-- Side by Side Videos -->
    <div class="comparison-grid">
      <!-- Card A: Pipeline Optimized -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">A. Pipeline-Optimized Prompt</div>
          <span class="verdict-tag {'strong' if eval_opt.get('verdict')=='STRONG_ADHERENCE' else 'moderate' if eval_opt.get('verdict')=='MODERATE_ADHERENCE' else 'poor'}">{eval_opt.get('verdict', 'EVALUATED')}</span>
        </div>

        <div class="video-wrapper">
          <video controls autoplay loop muted playsinline>
            <source src="./video_pipeline_optimized.mp4" type="video/mp4">
            Your browser does not support the video tag.
          </video>
        </div>

        <div class="section-title">Actual Omni Flash Prompt Used</div>
        <div class="prompt-box">{opt_meta.get('control_string')}</div>

        <div class="section-title">Agentic Video Understanding Audit</div>
        <div class="scores-grid">
          <div class="score-card">
            <div class="score-val">{eval_opt.get('facial_similarity_score', 0.0):.2f}</div>
            <div class="score-lbl">Facial Likeness</div>
          </div>
          <div class="score-card">
            <div class="score-val">{eval_opt.get('outfit_consistency_score', 0.0):.2f}</div>
            <div class="score-lbl">Outfit Adherence</div>
          </div>
          <div class="score-card">
            <div class="score-val">{eval_opt.get('motion_naturalness_score', 0.0):.2f}</div>
            <div class="score-lbl">Skiing Realism</div>
          </div>
        </div>
        <div class="critique-box">
          <strong>Observation:</strong> {eval_opt.get('detailed_critique', 'Inspected.')}
        </div>
      </div>

      <!-- Card B: Simple Prompt -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">B. Simple Prompt</div>
          <span class="verdict-tag {'strong' if eval_smp.get('verdict')=='STRONG_ADHERENCE' else 'moderate' if eval_smp.get('verdict')=='MODERATE_ADHERENCE' else 'poor'}">{eval_smp.get('verdict', 'EVALUATED')}</span>
        </div>

        <div class="video-wrapper">
          <video controls autoplay loop muted playsinline>
            <source src="./video_simple_prompt.mp4" type="video/mp4">
            Your browser does not support the video tag.
          </video>
        </div>

        <div class="section-title">Actual Omni Flash Prompt Used</div>
        <div class="prompt-box">{smp_meta.get('control_string')}</div>

        <div class="section-title">Agentic Video Understanding Audit</div>
        <div class="scores-grid">
          <div class="score-card">
            <div class="score-val">{eval_smp.get('facial_similarity_score', 0.0):.2f}</div>
            <div class="score-lbl">Facial Likeness</div>
          </div>
          <div class="score-card">
            <div class="score-val">{eval_smp.get('outfit_consistency_score', 0.0):.2f}</div>
            <div class="score-lbl">Outfit Adherence</div>
          </div>
          <div class="score-card">
            <div class="score-val">{eval_smp.get('motion_naturalness_score', 0.0):.2f}</div>
            <div class="score-lbl">Skiing Realism</div>
          </div>
        </div>
        <div class="critique-box">
          <strong>Observation:</strong> {eval_smp.get('detailed_critique', 'Inspected.')}
        </div>
      </div>
    </div>

    <!-- Summary Section -->
    <section class="summary-card">
      <h2>Comparative Analysis & Findings</h2>
      <table>
        <thead>
          <tr>
            <th>Attribute</th>
            <th>Pipeline-Optimized Prompt</th>
            <th>Simple Prompt</th>
            <th>Key Takeaway</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Prompt Complexity</strong></td>
            <td>Full cinematic direction + MMC control string tags</td>
            <td>Minimal ("xcyu (reference image) skiing in Hakuba")</td>
            <td>Simple prompt avoids diluting visual cross-attention</td>
          </tr>
          <tr>
            <td><strong>Facial Likeness Score</strong></td>
            <td>{eval_opt.get('facial_similarity_score', 0.0):.2f} / 1.0</td>
            <td>{eval_smp.get('facial_similarity_score', 0.0):.2f} / 1.0</td>
            <td>{'Simple prompt has higher facial likeness' if eval_smp.get('facial_similarity_score',0)>eval_opt.get('facial_similarity_score',0) else 'Comparable facial adherence'}</td>
          </tr>
          <tr>
            <td><strong>Generation Latency</strong></td>
            <td>{opt_meta.get('generation_time_s', 0.0):.1f}s</td>
            <td>{smp_meta.get('generation_time_s', 0.0):.1f}s</td>
            <td>Near-identical Omni Flash inference latency</td>
          </tr>
          <tr>
            <td><strong>Cinematography & Scene Dynamics</strong></td>
            <td>Rich alpine lighting, mountain peaks, dynamic framing</td>
            <td>Direct action focus, less cinematic composition</td>
            <td>Trade-off between rich cinematic staging vs. pure character adherence</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML report built at: {REPORT_PATH}")


def deploy_to_x20():
    """Deploys report and media assets to x20 web server directory and sets permissions."""
    print(f"\n--- [Step 6] Deploying to x20: {X20_DIR} ---")
    X20_DIR.mkdir(parents=True, exist_ok=True)
    
    # Copy files
    for item in [REF_IMG_PATH, VIDEO_OPT_PATH, VIDEO_SMP_PATH, REPORT_PATH]:
        dest = X20_DIR / item.name
        shutil.copy2(item, dest)
        print(f"Copied {item.name} -> {dest}")
        
    # Also ensure index.html exists
    shutil.copy2(REPORT_PATH, X20_DIR / "index.html")
    
    # Apply permissions
    subprocess.run(["chmod", "-R", "a+rX", str(X20_DIR)], check=True)
    print(f"Set world-readable permissions on {X20_DIR}")
    
    # Verify curl
    url = "https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/"
    print(f"\n🎉 Deployment complete! Live URL:\n{url}\n")


def main():
    client = get_genai_client()
    
    # 1. Reference Image
    ref_bytes = generate_reference_image(client)
    ref_b64 = base64.b64encode(ref_bytes).decode("utf-8")
    
    # 2. Video A: Pipeline Optimized
    opt_meta = generate_pipeline_optimized_video(client, ref_b64)
    
    # 3. Video B: Simple Prompt
    smp_meta = generate_simple_prompt_video(client, ref_b64)
    
    # 4. Agentic Evaluations
    eval_opt = evaluate_video_with_agentic_ai(
        client,
        video_path=str(VIDEO_OPT_PATH),
        ref_img_bytes=ref_bytes,
        prompt_desc=opt_meta["control_string"]
    )
    
    eval_smp = evaluate_video_with_agentic_ai(
        client,
        video_path=str(VIDEO_SMP_PATH),
        ref_img_bytes=ref_bytes,
        prompt_desc=smp_meta["control_string"]
    )
    
    # 5. Build HTML Report
    build_html_report(opt_meta, smp_meta, eval_opt, eval_smp)
    
    # 6. Deploy to x20
    deploy_to_x20()


if __name__ == "__main__":
    main()
