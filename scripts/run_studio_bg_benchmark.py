# Author:Hill YU(xcyu@)
"""Studio White Background vs Contextual Background Reference Benchmark.

Evaluates whether isolating a reference character against a solid white studio backdrop
affects video generation quality, character identity, wardrobe retention, and scene
relighting realism in Gemini Omni Flash 1.1 (gemini-omni-1.1-flash-preview).
"""

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
from google import genai
from google.genai import types

from scripts.benchmark_cases import BENCHMARK_CASES, STUDIO_SUBSET_IDS

GCP_PROJECT = "vital-octagon-19612"
LOCATION = "global"

OUTPUT_DIR = Path("benchmarks/studio_bg")
SUITE_DIR = Path("benchmarks/suite")
DATA_FILE = OUTPUT_DIR / "studio_benchmark_data.json"
HTML_FILE = OUTPUT_DIR / "index.html"

X20_TARGET = Path("/google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1/studio_bg_comparison")
REPORT_URL = "https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/studio_bg_comparison/"


def get_client() -> genai.Client:
    return genai.Client(vertexai=True, project=GCP_PROJECT, location=LOCATION)


def generate_reference_image(client: genai.Client, prompt: str, output_path: Path) -> Path:
    if output_path.exists() and output_path.stat().st_size > 10_000:
        print(f"  [Skip] Studio reference image exists: {output_path.name}")
        return output_path

    print(f"  Generating studio reference image via gemini-3.1-flash-image...")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-image",
                contents=prompt,
            )
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                    raw = part.inline_data.data
                    img_bytes = base64.b64decode(raw) if isinstance(raw, str) else raw
                    with open(output_path, "wb") as f:
                        f.write(img_bytes)
                    print(f"  Studio reference saved: {output_path.name} ({len(img_bytes)} bytes)")
                    return output_path
        except Exception as e:
            print(f"  Attempt {attempt + 1} studio ref gen failed: {e}")
            time.sleep(3)
    raise RuntimeError(f"No image returned for {output_path.name}")


def generate_video(client: genai.Client, prompt: str, ref_image_path: Path, output_path: Path) -> float:
    if output_path.exists() and output_path.stat().st_size > 100_000:
        print(f"  [Skip] Video exists: {output_path.name}")
        return 0.0

    print(f"  Generating video with Omni Flash (ref: {ref_image_path.name})...")
    with open(ref_image_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode("utf-8")

    t0 = time.time()
    interaction = client.interactions.create(
        model="gemini-omni-1.1-flash-preview",
        input=[
            {"type": "text", "text": prompt},
            {"type": "image", "data": ref_b64, "mime_type": "image/png"},
        ],
        generation_config={
            "video_config": {
                "task": "reference_to_video",
            }
        },
        response_format={
            "type": "video",
            "aspect_ratio": "16:9",
            "duration": "5s",
            "resolution": "720p",
        },
        timeout=180.0,
    )
    latency = time.time() - t0

    video_data = None
    if hasattr(interaction, "output_video") and interaction.output_video:
        video_data = getattr(interaction.output_video, "data", None)
    if not video_data and hasattr(interaction, "steps"):
        for step in interaction.steps:
            if step.type == "model_output" and step.content:
                for part in step.content:
                    if hasattr(part, "data") and part.data:
                        video_data = part.data
                        break
                    elif hasattr(part, "inline_data") and part.inline_data:
                        video_data = part.inline_data.data
                        break

    if not video_data:
        raise RuntimeError(f"No video data returned for {output_path.name}")

    raw_bytes = base64.b64decode(video_data)
    with open(output_path, "wb") as f:
        f.write(raw_bytes)
    print(f"  Video saved: {output_path.name} ({len(raw_bytes)} bytes in {latency:.1f}s)")
    return latency


def extract_compact_keyframes(video_path: Path, num_frames: int = 5) -> List[bytes]:
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []

    indices = [int(i * total_frames / (num_frames + 1)) for i in range(1, num_frames + 1)]
    encoded_frames = []

    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        h, w = frame.shape[:2]
        if h > 720:
            scale = 720.0 / h
            frame = cv2.resize(frame, (int(w * scale), 720), interpolation=cv2.INTER_AREA)
        success, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if success:
            encoded_frames.append(buffer.tobytes())

    cap.release()
    return encoded_frames


def compress_ref_image(ref_path: Path) -> bytes:
    img = cv2.imread(str(ref_path))
    if img is None:
        return ref_path.read_bytes()
    h, w = img.shape[:2]
    if h > 720:
        scale = 720.0 / h
        img = cv2.resize(img, (int(w * scale), 720), interpolation=cv2.INTER_AREA)
    success, buffer = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return buffer.tobytes() if success else ref_path.read_bytes()


def audit_video_adherence(
    client: genai.Client,
    ref_image_path: Path,
    video_path: Path,
    prompt: str,
    ref_bg_type: str,
) -> Dict[str, Any]:
    print(f"  Auditing {video_path.name} ({ref_bg_type}) with gemini-3.7-flash...")
    keyframes = extract_compact_keyframes(video_path, num_frames=5)
    ref_bytes = compress_ref_image(ref_image_path)

    system_instruction = (
        "You are an expert film director and AI video quality rater. "
        "You evaluate AI video generation fidelity against an input reference character portrait. "
        "Pay special attention to whether the background of the reference image affected the video generation: "
        "Specifically analyze: "
        "1. Facial Similarity (0.00-1.00): Accurate facial geometry, eyes, ethnicity, hair, expression. "
        "2. Outfit Consistency (0.00-1.00): Accurate garment style, color, fabric patterns. "
        "3. Environment Integration & Relighting Realism (0.00-1.00): Does the subject naturally integrate into "
        "the target scene lighting? Or is there any white halo, cutout edge matte line, or flat studio lighting bleed? "
        "4. Motion Realism (0.00-1.00): Fluid, physically believable kinematics. "
        "5. Overall Adherence (0.00-1.00): Composite score. "
        "Return ONLY a valid JSON object."
    )

    eval_prompt = f"""Evaluate this video against the reference character portrait.
Target Scene Prompt: {prompt}
Reference Background Type: {ref_bg_type} (e.g. contextual environment vs seamless white studio)

Respond strictly in JSON:
{{
  "facial_similarity": float,
  "outfit_consistency": float,
  "relighting_realism": float,
  "motion_realism": float,
  "overall": float,
  "verdict": "STRONG_ADHERENCE" | "MODERATE_ADHERENCE" | "WEAK_ADHERENCE",
  "critique": "Detailed critique focusing on identity preservation, outfit accuracy, and environment relighting (noting whether white studio background caused any haloing or flat lighting bleed vs natural scene relighting)."
}}
"""

    contents: List[Any] = [
        types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg"),
        "Input Reference Portrait:",
    ]
    for i, frame in enumerate(keyframes):
        contents.append(f"Video Keyframe {i+1}:")
        contents.append(types.Part.from_bytes(data=frame, mime_type="image/jpeg"))
    contents.append(eval_prompt)

    resp = client.models.generate_content(
        model="gemini-3.7-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    clean_text = resp.text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    return json.loads(clean_text)


def build_interactive_html(data):
    cases = list(data.values())
    
    # Calculate aggregate metrics
    metrics = {
        "arm_context_smp": {"overall": [], "face": [], "outfit": [], "relight": []},
        "arm_studio_smp": {"overall": [], "face": [], "outfit": [], "relight": []},
        "arm_context_cin": {"overall": [], "face": [], "outfit": [], "relight": []},
        "arm_studio_cin": {"overall": [], "face": [], "outfit": [], "relight": []},
    }
    
    for item in cases:
        for arm_key in metrics.keys():
            if arm_key in item and "audit" in item[arm_key]:
                aud = item[arm_key]["audit"]
                if "overall" in aud:
                    metrics[arm_key]["overall"].append(aud.get("overall", 0))
                    metrics[arm_key]["face"].append(aud.get("facial_similarity", 0))
                    metrics[arm_key]["outfit"].append(aud.get("outfit_consistency", 0))
                    metrics[arm_key]["relight"].append(aud.get("relighting_realism", aud.get("motion_realism", 0)))
    
    avg = {}
    for arm_key, m_dict in metrics.items():
        avg[arm_key] = {
            k: (sum(vals) / len(vals) if vals else 0.0) for k, vals in m_dict.items()
        }
    
    delta_smp_ov = avg["arm_studio_smp"]["overall"] - avg["arm_context_smp"]["overall"]
    delta_smp_fa = avg["arm_studio_smp"]["face"] - avg["arm_context_smp"]["face"]
    delta_smp_ou = avg["arm_studio_smp"]["outfit"] - avg["arm_context_smp"]["outfit"]
    delta_smp_re = avg["arm_studio_smp"]["relight"] - avg["arm_context_smp"]["relight"]

    delta_cin_ov = avg["arm_studio_cin"]["overall"] - avg["arm_context_cin"]["overall"]
    delta_cin_fa = avg["arm_studio_cin"]["face"] - avg["arm_context_cin"]["face"]
    delta_cin_ou = avg["arm_studio_cin"]["outfit"] - avg["arm_context_cin"]["outfit"]
    delta_cin_re = avg["arm_studio_cin"]["relight"] - avg["arm_context_cin"]["relight"]

    def fmt_d(d):
        color = "#10b981" if d > 0.005 else ("#ef4444" if d < -0.005 else "#94a3b8")
        sign = "+" if d > 0 else ""
        return f'<span style="color: {color}; font-weight: 700;">{sign}{d*100:.1f}%</span>'

    html_cards = []
    for item in cases:
        c = item["case"]
        cid = c["id"]
        name = c["name"]
        eth = c["ethnicity"]
        framing = c.get("framing_category", "Unknown")
        action = c.get("action_summary", "")

        def render_col(arm_key, badge_cls, badge_lbl):
            arm_data = item.get(arm_key, {})
            aud = arm_data.get("audit", {})
            ov = aud.get("overall", 0.0)
            fa = aud.get("facial_similarity", 0.0)
            ou = aud.get("outfit_consistency", 0.0)
            re = aud.get("relighting_realism", aud.get("motion_realism", 0.0))
            crit = aud.get("critique", "No critique available.")
            v_src = arm_data.get("video", "")
            prompt = arm_data.get("prompt", "")

            return f"""
            <div class="video-col">
              <div class="video-header">
                <span class="badge {badge_cls}">{badge_lbl}</span>
                <span class="score-main">★ {ov:.2f}</span>
              </div>
              <div class="video-wrapper">
                <video src="{v_src}" controls preload="metadata" playsinline></video>
              </div>
              <div class="score-pills">
                <span class="pill" title="Facial Similarity">Face: {fa:.2f}</span>
                <span class="pill" title="Outfit Consistency">Outfit: {ou:.2f}</span>
                <span class="pill" title="Scene Relighting Realism">Relight: {re:.2f}</span>
              </div>
              <details class="details-drawer">
                <summary>Prompt & Audit</summary>
                <div class="drawer-content">
                  <div class="prompt-box"><strong>Prompt:</strong> {prompt}</div>
                  <div class="critique-box"><strong>Judge Critique:</strong> {crit}</div>
                </div>
              </details>
            </div>
            """

        card_html = f"""
        <div class="case-card" data-framing="{framing}" data-ethnicity="{eth}">
          <div class="case-header">
            <div class="case-title">
              <span class="case-id">#{cid:02d}</span>
              <h3>{name}</h3>
              <span class="framing-badge">{framing}</span>
              <span class="demog-tag">{eth}</span>
            </div>
            <div class="case-action">Target Action: <strong>{action}</strong></div>
          </div>

          <!-- Paired References Row -->
          <div class="ref-row">
            <div class="ref-box">
              <div class="ref-label">Contextual Reference (Original)</div>
              <img src="{item.get('ref_context', '')}" alt="Contextual Reference" loading="lazy">
            </div>
            <div class="ref-box">
              <div class="ref-label studio-label">Studio White Reference (Seamless)</div>
              <img src="{item.get('ref_studio', '')}" alt="Studio White Reference" loading="lazy">
            </div>
          </div>

          <!-- 4-Way Video Comparison Matrix -->
          <div class="videos-grid">
            {render_col('arm_context_smp', 'badge-context-smp', 'Contextual Ref · Simple')}
            {render_col('arm_studio_smp', 'badge-studio-smp', 'Studio White Ref · Simple')}
            {render_col('arm_context_cin', 'badge-context-cin', 'Contextual Ref · Cinematic')}
            {render_col('arm_studio_cin', 'badge-studio-cin', 'Studio White Ref · Cinematic')}
          </div>
        </div>
        """
        html_cards.append(card_html)

    cards_str = "\n".join(html_cards)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gemini Omni Flash 1.1: Studio White vs Contextual Background Benchmark</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #111827;
      --card-border: #1f2937;
      --text: #f3f4f6;
      --text-dim: #9ca3af;
      --primary: #38bdf8;
      --accent: #818cf8;
      --success: #10b981;
      --warning: #f59e0b;
      --studio: #ec4899;
      --context: #3b82f6;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 32px 24px;
    }}
    .container {{ max-width: 1720px; margin: 0 auto; }}
    
    .header {{
      background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
      border: 1px solid #312e81;
      border-radius: 16px;
      padding: 32px;
      margin-bottom: 28px;
    }}
    .header h1 {{ font-size: 28px; font-weight: 800; color: #fff; margin-bottom: 8px; }}
    .header p {{ color: #cbd5e1; font-size: 15px; max-width: 1100px; }}
    .header .meta-bar {{
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      font-size: 13px;
      color: #94a3b8;
    }}
    .meta-bar span {{ background: rgba(255,255,255,0.06); padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 18px;
      margin-bottom: 28px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
    }}
    .kpi-title {{ font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); margin-bottom: 12px; }}
    .kpi-compare {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .kpi-box {{
      background: rgba(255,255,255,0.03);
      padding: 12px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.05);
    }}
    .kpi-box .lbl {{ font-size: 11px; color: var(--text-dim); }}
    .kpi-box .val {{ font-size: 22px; font-weight: 800; margin-top: 2px; }}
    .kpi-deltas {{
      font-size: 12px;
      color: var(--text-dim);
      border-top: 1px solid rgba(255,255,255,0.06);
      padding-top: 10px;
      display: flex;
      justify-content: space-between;
    }}

    /* Filters */
    .filter-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 24px;
      align-items: center;
    }}
    .filter-btn {{
      background: #1e293b;
      color: #94a3b8;
      border: 1px solid #334155;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .filter-btn:hover, .filter-btn.active {{
      background: #38bdf8;
      color: #090d16;
      border-color: #38bdf8;
      font-weight: 700;
    }}

    /* Case Card */
    .case-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px;
      margin-bottom: 28px;
    }}
    .case-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 18px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding-bottom: 14px;
    }}
    .case-title {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .case-id {{ background: #2563eb; color: #fff; font-size: 12px; font-weight: 800; padding: 3px 8px; border-radius: 6px; }}
    .case-title h3 {{ font-size: 18px; font-weight: 700; }}
    .framing-badge {{ background: #374151; color: #e5e7eb; font-size: 11px; padding: 3px 8px; border-radius: 4px; }}
    .demog-tag {{ background: #1e293b; color: #94a3b8; font-size: 11px; padding: 3px 8px; border-radius: 4px; }}
    .case-action {{ font-size: 13px; color: #94a3b8; }}

    /* Ref Row */
    .ref-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
      background: #0f172a;
      padding: 14px;
      border-radius: 12px;
      border: 1px solid #1e293b;
    }}
    .ref-box {{ text-align: center; }}
    .ref-label {{ font-size: 12px; font-weight: 700; color: #60a5fa; margin-bottom: 8px; }}
    .ref-label.studio-label {{ color: #f472b6; }}
    .ref-box img {{
      max-height: 200px;
      width: auto;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.1);
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    }}

    /* Video Grid */
    .videos-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }}
    @media (max-width: 1200px) {{
      .videos-grid {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 768px) {{
      .videos-grid {{ grid-template-columns: 1fr; }}
      .ref-row {{ grid-template-columns: 1fr; }}
    }}

    .video-col {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 12px;
      display: flex;
      flex-direction: column;
    }}
    .video-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }}
    .badge {{
      font-size: 10px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .badge-context-smp {{ background: #1e3a8a; color: #93c5fd; }}
    .badge-studio-smp {{ background: #831843; color: #fbcfe8; }}
    .badge-context-cin {{ background: #14532d; color: #86efac; }}
    .badge-studio-cin {{ background: #713f12; color: #fde047; }}
    .score-main {{ font-size: 14px; font-weight: 800; color: #fbbf24; }}

    .video-wrapper {{
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #000;
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 8px;
    }}
    .video-wrapper video {{ width: 100%; height: 100%; object-fit: cover; display: block; }}

    .score-pills {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }}
    .pill {{
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.08);
      font-size: 11px;
      padding: 2px 6px;
      border-radius: 4px;
      color: #cbd5e1;
    }}

    .details-drawer {{ margin-top: auto; }}
    .details-drawer summary {{
      font-size: 11px;
      color: #64748b;
      cursor: pointer;
      font-weight: 600;
      padding: 4px 0;
    }}
    .details-drawer summary:hover {{ color: #94a3b8; }}
    .drawer-content {{
      margin-top: 6px;
      font-size: 11px;
      background: #090d16;
      padding: 8px;
      border-radius: 6px;
      border: 1px solid #1e293b;
    }}
    .prompt-box {{ margin-bottom: 6px; color: #94a3b8; font-family: 'JetBrains Mono', monospace; font-size: 10px; word-break: break-word; }}
    .critique-box {{ color: #cbd5e1; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Gemini Omni Flash 1.1: Studio White vs Contextual Background Benchmark</h1>
      <p>
        Systematic investigation into whether isolating a reference character against a solid white studio backdrop
        affects video generation quality, character identity, wardrobe retention, and scene relighting realism in Gemini Omni Flash 1.1.
      </p>
      <div class="meta-bar">
        <span>Model: <strong>gemini-omni-1.1-flash-preview</strong></span>
        <span>Reference Model: <strong>gemini-3.1-flash-image</strong></span>
        <span>Evaluator: <strong>gemini-3.7-flash</strong></span>
        <span>API Schema: <strong>generation_config.video_config.task + response_format</strong></span>
        <span>Scenarios: <strong>{len(cases)} Cases (40 Video Clips)</strong></span>
      </div>
    </div>

    <!-- KPI Summary Grid -->
    <div class="kpi-grid">
      <!-- Simple Prompt Comparison -->
      <div class="kpi-card">
        <div class="kpi-title">Simple Prompts: Contextual vs Studio White</div>
        <div class="kpi-compare">
          <div class="kpi-box">
            <div class="lbl">Contextual Ref</div>
            <div class="val" style="color: #60a5fa;">{avg['arm_context_smp']['overall']:.3f}</div>
          </div>
          <div class="kpi-box">
            <div class="lbl">Studio White Ref</div>
            <div class="val" style="color: #f472b6;">{avg['arm_studio_smp']['overall']:.3f}</div>
          </div>
        </div>
        <div class="kpi-deltas">
          <span>Overall: {fmt_d(delta_smp_ov)}</span>
          <span>Face: {fmt_d(delta_smp_fa)}</span>
          <span>Outfit: {fmt_d(delta_smp_ou)}</span>
          <span>Relight: {fmt_d(delta_smp_re)}</span>
        </div>
      </div>

      <!-- Cinematic Prompt Comparison -->
      <div class="kpi-card">
        <div class="kpi-title">Cinematic Prompts: Contextual vs Studio White</div>
        <div class="kpi-compare">
          <div class="kpi-box">
            <div class="lbl">Contextual Ref</div>
            <div class="val" style="color: #4ade80;">{avg['arm_context_cin']['overall']:.3f}</div>
          </div>
          <div class="kpi-box">
            <div class="lbl">Studio White Ref</div>
            <div class="val" style="color: #facc15;">{avg['arm_studio_cin']['overall']:.3f}</div>
          </div>
        </div>
        <div class="kpi-deltas">
          <span>Overall: {fmt_d(delta_cin_ov)}</span>
          <span>Face: {fmt_d(delta_cin_fa)}</span>
          <span>Outfit: {fmt_d(delta_cin_ou)}</span>
          <span>Relight: {fmt_d(delta_cin_re)}</span>
        </div>
      </div>
    </div>

    <!-- Filter Buttons -->
    <div class="filter-bar">
      <span style="font-size: 12px; font-weight: 700; color: #64748b;">FRAMING:</span>
      <button class="filter-btn active" onclick="filterCases('all', this)">All ({len(cases)})</button>
      <button class="filter-btn" onclick="filterCases('Headshot', this)">Headshot</button>
      <button class="filter-btn" onclick="filterCases('Medium', this)">Bust / Medium</button>
      <button class="filter-btn" onclick="filterCases('Three-Quarter', this)">Three-Quarter</button>
      <button class="filter-btn" onclick="filterCases('Full-Body', this)">Full-Body</button>
    </div>

    <!-- Cases Gallery -->
    <div id="cases-container">
      {cards_str}
    </div>
  </div>

  <script>
    function filterCases(framing, btn) {{
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.case-card').forEach(card => {{
        if (framing === 'all' || card.getAttribute('data-framing') === framing) {{
          card.style.display = 'block';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}
  </script>
</body>
</html>"""
    
    HTML_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HTML_FILE, "w") as f:
        f.write(html_content)
    print(f"Interactive HTML report built at: {HTML_FILE}")
    return HTML_FILE


def deploy_to_x20():
    print(f"\n--- Deploying to x20: {X20_TARGET} ---")
    X20_TARGET.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in OUTPUT_DIR.iterdir():
        if p.is_file():
            dst = X20_TARGET / p.name
            if dst.exists() and dst.stat().st_size == p.stat().st_size:
                continue
            shutil.copy2(p, dst)
            copied += 1
    print(f"Updated {copied} files on {X20_TARGET}")
    subprocess.run(["chmod", "-R", "a+rX", str(X20_TARGET)], check=False, capture_output=True)
    print(f"Applied world-readable permissions on {X20_TARGET}")
    print(f"\n🎉 Live Report URL:\n{REPORT_URL}\n")


def run_benchmark():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = get_client()

    data = {}
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                data = json.load(f)
            print(f"Loaded existing data for {len(data)} cases.")
        except Exception as e:
            print(f"Warning loading data: {e}")

    subset_cases = [c for c in BENCHMARK_CASES if c["id"] in STUDIO_SUBSET_IDS]
    print(f"Running Studio Background Benchmark for {len(subset_cases)} cases...")

    for case in subset_cases:
        cid = case["id"]
        cid_str = str(cid)
        print(f"\n{'='*55}\nProcessing Case #{cid:02d}: {case['name']}\n{'='*55}")

        if cid_str not in data:
            data[cid_str] = {"case": case}

        # 1. Setup Contextual Reference & Baseline Videos
        ref_context_file = f"ref_context_{cid:02d}.png"
        ref_context_path = OUTPUT_DIR / ref_context_file
        src_context_ref = SUITE_DIR / f"ref_{cid:02d}.png"
        if src_context_ref.exists() and not ref_context_path.exists():
            shutil.copy2(src_context_ref, ref_context_path)
        data[cid_str]["ref_context"] = ref_context_file

        # Arm 1: Contextual Simple Baseline
        vid_context_smp_file = f"video_context_smp_{cid:02d}.mp4"
        vid_context_smp_path = OUTPUT_DIR / vid_context_smp_file
        src_context_smp = SUITE_DIR / f"video_tsk_{cid:02d}.mp4"
        if src_context_smp.exists() and not vid_context_smp_path.exists():
            shutil.copy2(src_context_smp, vid_context_smp_path)

        # Arm 3: Contextual Cinematic Baseline
        vid_context_cin_file = f"video_context_cin_{cid:02d}.mp4"
        vid_context_cin_path = OUTPUT_DIR / vid_context_cin_file
        src_context_cin = SUITE_DIR / f"video_cin_tsk_{cid:02d}.mp4"
        if src_context_cin.exists() and not vid_context_cin_path.exists():
            shutil.copy2(src_context_cin, vid_context_cin_path)

        # 2. Generate Studio White Reference Image
        ref_studio_file = f"ref_studio_{cid:02d}.png"
        ref_studio_path = OUTPUT_DIR / ref_studio_file
        generate_reference_image(client, case["ref_studio_prompt"], ref_studio_path)
        data[cid_str]["ref_studio"] = ref_studio_file

        # 3. Generate Arm 2: Studio White Ref + Simple Prompt
        vid_studio_smp_file = f"video_studio_smp_{cid:02d}.mp4"
        vid_studio_smp_path = OUTPUT_DIR / vid_studio_smp_file
        lat_studio_smp = generate_video(client, case["clean_prompt"], ref_studio_path, vid_studio_smp_path)

        # 4. Generate Arm 4: Studio White Ref + Cinematic Prompt
        vid_studio_cin_file = f"video_studio_cin_{cid:02d}.mp4"
        vid_studio_cin_path = OUTPUT_DIR / vid_studio_cin_file
        lat_studio_cin = generate_video(client, case["mode_a_cinematic"], ref_studio_path, vid_studio_cin_path)

        # 5. Audits
        # Arm 1 Audit (Contextual Simple)
        if "arm_context_smp" not in data[cid_str] or "audit" not in data[cid_str]["arm_context_smp"]:
            aud_context_smp = audit_video_adherence(client, ref_context_path, vid_context_smp_path, case["clean_prompt"], "Contextual Environment")
            data[cid_str]["arm_context_smp"] = {
                "video": vid_context_smp_file,
                "prompt": case["clean_prompt"],
                "audit": aud_context_smp,
            }

        # Arm 2 Audit (Studio Simple)
        if "arm_studio_smp" not in data[cid_str] or "audit" not in data[cid_str]["arm_studio_smp"]:
            aud_studio_smp = audit_video_adherence(client, ref_studio_path, vid_studio_smp_path, case["clean_prompt"], "Seamless White Studio Backdrop")
            data[cid_str]["arm_studio_smp"] = {
                "video": vid_studio_smp_file,
                "prompt": case["clean_prompt"],
                "latency_s": lat_studio_smp,
                "audit": aud_studio_smp,
            }

        # Arm 3 Audit (Contextual Cinematic)
        if "arm_context_cin" not in data[cid_str] or "audit" not in data[cid_str]["arm_context_cin"]:
            aud_context_cin = audit_video_adherence(client, ref_context_path, vid_context_cin_path, case["mode_a_cinematic"], "Contextual Environment")
            data[cid_str]["arm_context_cin"] = {
                "video": vid_context_cin_file,
                "prompt": case["mode_a_cinematic"],
                "audit": aud_context_cin,
            }

        # Arm 4 Audit (Studio Cinematic)
        if "arm_studio_cin" not in data[cid_str] or "audit" not in data[cid_str]["arm_studio_cin"]:
            aud_studio_cin = audit_video_adherence(client, ref_studio_path, vid_studio_cin_path, case["mode_a_cinematic"], "Seamless White Studio Backdrop")
            data[cid_str]["arm_studio_cin"] = {
                "video": vid_studio_cin_file,
                "prompt": case["mode_a_cinematic"],
                "latency_s": lat_studio_cin,
                "audit": aud_studio_cin,
            }

        # Persist data checkpoint
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

        # Incrementally build HTML & deploy
        build_interactive_html(data)
        deploy_to_x20()

    print("\nAll 10 benchmark scenarios completed successfully!")
    build_interactive_html(data)
    deploy_to_x20()


if __name__ == "__main__":
    run_benchmark()
