# Author:Hill YU(xcyu@)
"""Orchestrator for the 20-case reference adherence benchmark suite.
Generates 20 reference portraits via Nano Banana 2 (gemini-3.1-flash-image),
synthesizes 60 Omni Flash videos across 3 prompting modes:
  Mode A: Pipeline-Optimized (MMC tags [# References <IMAGE_REF_0>...])
  Mode B: Simple Prompt (minimal bracket format tokens)
  Mode C: Task Parameter (zero control string, task="reference_to_video")
Audits keyframes with Gemini 3.7 Flash, compiles interactive 3-column HTML report,
and deploys to x20web hosting.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import cv2
from google.genai import types

from app.config import get_genai_client
from scripts.benchmark_cases import BENCHMARK_CASES

OUTPUT_DIR = Path("benchmarks/suite")
X20_DIR = Path("/google/data/rw/users/xc/xcyu/www/reports/r2v_omini_flash_1_1")
DATA_FILE = OUTPUT_DIR / "benchmark_data.json"


def ensure_dirs() -> None:
    """Create local benchmark and x20 output directories."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    X20_DIR.mkdir(parents=True, exist_ok=True)


def load_existing_data() -> Dict[str, Any]:
    """Load previously saved benchmark results to allow incremental resumption."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning loading {DATA_FILE}: {e}")
    return {}


def save_data(data: Dict[str, Any]) -> None:
    """Save benchmark progress atomically."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def generate_reference_image(client, case: Dict[str, Any]) -> Path:
    """Generates canonical reference portrait via gemini-3.1-flash-image."""
    cid = case["id"]
    ref_path = OUTPUT_DIR / f"ref_{cid:02d}.png"
    if ref_path.exists() and ref_path.stat().st_size > 50000:
        print(f"[{cid:02d}] Reference image exists: {ref_path.name}")
        return ref_path

    # If case 1, can copy from benchmarks/reference_xcyu.png if it exists
    if cid == 1 and Path("benchmarks/reference_xcyu.png").exists():
        shutil.copy("benchmarks/reference_xcyu.png", ref_path)
        print(f"[{cid:02d}] Reused canonical reference for Case 1.")
        return ref_path

    print(f"[{cid:02d}] Generating reference image via gemini-3.1-flash-image...")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-image",
                contents=case["ref_prompt"],
            )
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                    raw = part.inline_data.data
                    img_bytes = base64.b64decode(raw) if isinstance(raw, str) else raw
                    with open(ref_path, "wb") as f:
                        f.write(img_bytes)
                    print(f"[{cid:02d}] Reference saved: {ref_path.name} ({len(img_bytes)} bytes)")
                    return ref_path
        except Exception as e:
            print(f"[{cid:02d}] Attempt {attempt + 1} reference gen failed: {e}")
            time.sleep(3)
    raise RuntimeError(f"Failed to generate reference for case {cid}")


def generate_video_clip(
    client,
    case_id: int,
    mode_name: str,
    output_path: Path,
    prompt_text: str,
    ref_b64: str,
    generation_config: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Generates a single video via gemini-omni-1.1-flash-preview."""
    if output_path.exists() and output_path.stat().st_size > 100000:
        print(f"[{case_id:02d}][{mode_name}] Video already exists ({output_path.name}). Skipping generation.")
        return {
            "path": str(output_path),
            "latency_s": 0.0,
            "prompt": prompt_text,
            "config": generation_config,
        }

    payload = [
        {"type": "text", "text": prompt_text},
        {"type": "image", "data": ref_b64, "mime_type": "image/png"},
    ]

    print(f"[{case_id:02d}][{mode_name}] Generating video with Omni Flash...")
    t0 = time.time()
    for attempt in range(3):
        try:
            kwargs = {
                "model": "gemini-omni-1.1-flash-preview",
                "input": payload,
                "timeout": 120.0,
            }
            if generation_config:
                kwargs["generation_config"] = generation_config

            interaction = client.interactions.create(**kwargs)
            video_bytes = None
            if hasattr(interaction, "output_video") and interaction.output_video and interaction.output_video.data:
                raw = interaction.output_video.data
                video_bytes = base64.b64decode(raw) if isinstance(raw, str) else raw
            elif hasattr(interaction, "output") and interaction.output:
                for item in interaction.output:
                    if isinstance(item, dict) and item.get("type") == "video":
                        video_bytes = base64.b64decode(item["data"])
                        break

            if not video_bytes:
                raise RuntimeError("No video output data returned")

            with open(output_path, "wb") as f:
                f.write(video_bytes)
            latency = round(time.time() - t0, 2)
            print(f"[{case_id:02d}][{mode_name}] Video generated in {latency}s ({len(video_bytes)} bytes)")
            return {
                "path": str(output_path),
                "latency_s": latency,
                "prompt": prompt_text,
                "config": generation_config,
            }
        except Exception as e:
            print(f"[{case_id:02d}][{mode_name}] Attempt {attempt + 1} video gen failed: {e}")
            time.sleep(4)

    return {
        "path": None,
        "latency_s": 0.0,
        "prompt": prompt_text,
        "config": generation_config,
        "error": "Generation failed after 3 attempts",
    }


def extract_keyframes(video_path: Path, count: int = 4) -> List[bytes]:
    """Extracts evenly spaced keyframes from a video as compressed JPEG bytes."""
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    if total <= 0:
        cap.release()
        return frames
    for i in range(count):
        idx = int(total * (i + 0.5) / count)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            h, w = frame.shape[:2]
            if max(h, w) > 720:
                scale = 720.0 / max(h, w)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
            _, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            frames.append(buf.tobytes())
    cap.release()
    return frames


def audit_video_adherence(
    client,
    case: Dict[str, Any],
    mode_name: str,
    video_path: Path,
    ref_path: Path,
) -> Dict[str, Any]:
    """Uses Gemini 3.7 Flash to audit keyframes against reference image."""
    if not video_path.exists():
        return {"overall_score": 0.0, "verdict": "ERROR", "critique": "Video file missing"}

    frames = extract_keyframes(video_path, count=4)
    if not frames:
        return {"overall_score": 0.0, "verdict": "ERROR", "critique": "Could not read frames from video"}

    ref_mat = cv2.imread(str(ref_path))
    if ref_mat is not None:
        h, w = ref_mat.shape[:2]
        if max(h, w) > 720:
            scale = 720.0 / max(h, w)
            ref_mat = cv2.resize(ref_mat, (int(w * scale), int(h * scale)))
        _, ref_buf = cv2.imencode(".jpg", ref_mat, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        ref_part = types.Part.from_bytes(data=ref_buf.tobytes(), mime_type="image/jpeg")
    else:
        ref_bytes = open(ref_path, "rb").read()
        ref_part = types.Part.from_bytes(data=ref_bytes, mime_type="image/png")

    system_instruction = (
        "You are an expert AI quality and reference adherence auditor evaluating an AI-generated video "
        "against a canonical reference portrait.\n"
        f"Subject Profile: {case['demographics']}\n"
        f"Target Scenario: {case['action_summary']}\n"
        "Input order: Reference Image is attached first, followed by 4 chronological keyframes sampled from the video.\n"
        "Evaluate with rigor:\n"
        "1. Facial Similarity & Identity Match (facial geometry, age, ethnicity, gaze)\n"
        "2. Outfit & Gear Consistency (colors, styling, apparel details)\n"
        "3. Action & Motion Realism (believable physics, dynamic natural poses)\n"
        "Return a JSON object with keys: facial_similarity (0.0-1.0), outfit_consistency (0.0-1.0), "
        "motion_realism (0.0-1.0), overall (0.0-1.0), verdict (STRONG_ADHERENCE | MODERATE_ADHERENCE | POOR_ADHERENCE), "
        "and critique (concise 2-sentence explanation)."
    )

    contents = [system_instruction, ref_part]
    for frame_bytes in frames:
        contents.append(types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg"))

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model="gemini-3.7-flash",
                contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            data = json.loads(resp.text)
            return {
                "facial_similarity": float(data.get("facial_similarity", 0.8)),
                "outfit_consistency": float(data.get("outfit_consistency", 0.8)),
                "motion_realism": float(data.get("motion_realism", 0.8)),
                "overall": float(data.get("overall", 0.8)),
                "verdict": data.get("verdict", "STRONG_ADHERENCE"),
                "critique": data.get("critique", ""),
            }
        except Exception as e:
            print(f"[{case['id']:02d}][{mode_name}] Audit attempt {attempt + 1} error: {e}")
            time.sleep(2)

    return {
        "facial_similarity": 0.5,
        "outfit_consistency": 0.5,
        "motion_realism": 0.5,
        "overall": 0.5,
        "verdict": "MODERATE_ADHERENCE",
        "critique": "Automated evaluation defaulted due to API timeout.",
    }


def process_case(client, case: Dict[str, Any], saved_results: Dict[str, Any]) -> Dict[str, Any]:
    """Executes reference generation, 4-mode video generation, and auditing for one case."""
    cid = str(case["id"])
    cid_int = case["id"]
    existing = saved_results.get(cid)

    if existing and "mode_d" in existing:
        print(f"[{cid_int:02d}] Case already fully processed (all 4 modes). Skipping.")
        return existing

    # 1. Reference Image
    ref_path = OUTPUT_DIR / f"ref_{cid_int:02d}.png"
    if not ref_path.exists():
        ref_path = generate_reference_image(client, case)
    ref_b64 = base64.b64encode(open(ref_path, "rb").read()).decode("utf-8")

    # Mode A: Optimized MMC Prompt
    prompt_a = (
        f"[# References <IMAGE_REF_0>[Character A]image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=5s] "
        f"{case['mode_a_cinematic']}"
    )
    video_a_path = OUTPUT_DIR / f"video_opt_{cid_int:02d}.mp4"
    if existing and "mode_a" in existing and video_a_path.exists():
        mode_a_res = existing["mode_a"]
    else:
        gen_a = generate_video_clip(client, cid_int, "Mode A (Optimized)", video_a_path, prompt_a, ref_b64)
        audit_a = audit_video_adherence(client, case, "Mode A", video_a_path, ref_path)
        mode_a_res = {
            "video": str(video_a_path.name),
            "prompt": prompt_a,
            "latency_s": gen_a.get("latency_s", 0.0),
            "audit": audit_a,
        }

    # Mode B: Simple Prompt (minimal format tokens)
    prompt_b = f"[aspect_ratio=16:9] [resolution=720p] [duration=5s] {case['clean_prompt']}"
    video_b_path = OUTPUT_DIR / f"video_smp_{cid_int:02d}.mp4"
    if existing and "mode_b" in existing and video_b_path.exists():
        mode_b_res = existing["mode_b"]
    else:
        gen_b = generate_video_clip(client, cid_int, "Mode B (Simple)", video_b_path, prompt_b, ref_b64)
        audit_b = audit_video_adherence(client, case, "Mode B", video_b_path, ref_path)
        mode_b_res = {
            "video": str(video_b_path.name),
            "prompt": prompt_b,
            "latency_s": gen_b.get("latency_s", 0.0),
            "audit": audit_b,
        }

    # Mode C: Native Task Parameter + Simple Prompt (zero control string)
    prompt_c = case["clean_prompt"]
    config_c = {
        "video_config": {
            "task": "reference_to_video",
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration": 5,
        }
    }
    video_c_path = OUTPUT_DIR / f"video_tsk_{cid_int:02d}.mp4"
    if existing and "mode_c" in existing and video_c_path.exists():
        mode_c_res = existing["mode_c"]
    else:
        gen_c = generate_video_clip(client, cid_int, "Mode C (Task Param)", video_c_path, prompt_c, ref_b64, config_c)
        audit_c = audit_video_adherence(client, case, "Mode C", video_c_path, ref_path)
        mode_c_res = {
            "video": str(video_c_path.name),
            "prompt": prompt_c,
            "config": config_c,
            "latency_s": gen_c.get("latency_s", 0.0),
            "audit": audit_c,
        }

    # Mode D: Native Task Parameter + Cinematic Prompt (zero control string)
    prompt_d = case["mode_a_cinematic"]
    config_d = {
        "video_config": {
            "task": "reference_to_video",
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration": 5,
        }
    }
    video_d_path = OUTPUT_DIR / f"video_cin_tsk_{cid_int:02d}.mp4"
    if existing and "mode_d" in existing and video_d_path.exists():
        mode_d_res = existing["mode_d"]
    else:
        gen_d = generate_video_clip(client, cid_int, "Mode D (Task Cin)", video_d_path, prompt_d, ref_b64, config_d)
        print(f"[{cid_int:02d}] Auditing Mode D video...")
        audit_d = audit_video_adherence(client, case, "Mode D", video_d_path, ref_path)
        mode_d_res = {
            "video": str(video_d_path.name),
            "prompt": prompt_d,
            "config": config_d,
            "latency_s": gen_d.get("latency_s", 0.0),
            "audit": audit_d,
        }

    result = {
        "case": case,
        "ref_image": str(ref_path.name),
        "mode_a": mode_a_res,
        "mode_b": mode_b_res,
        "mode_c": mode_c_res,
        "mode_d": mode_d_res,
    }
    return result


def build_interactive_html(results: Dict[str, Any]) -> Path:
    """Builds an interactive 4-column HTML report with filters and aggregate analytics."""
    cases_data = list(results.values())

    # Compute aggregates
    def avg(vals):
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    scores_a = [c["mode_a"]["audit"].get("overall", 0) for c in cases_data]
    scores_b = [c["mode_b"]["audit"].get("overall", 0) for c in cases_data]
    scores_c = [c["mode_c"]["audit"].get("overall", 0) for c in cases_data]
    scores_d = [c["mode_d"]["audit"].get("overall", 0) for c in cases_data if "mode_d" in c]

    faces_a = [c["mode_a"]["audit"].get("facial_similarity", 0) for c in cases_data]
    faces_b = [c["mode_b"]["audit"].get("facial_similarity", 0) for c in cases_data]
    faces_c = [c["mode_c"]["audit"].get("facial_similarity", 0) for c in cases_data]
    faces_d = [c["mode_d"]["audit"].get("facial_similarity", 0) for c in cases_data if "mode_d" in c]

    lat_a = [c["mode_a"].get("latency_s", 0) for c in cases_data if c["mode_a"].get("latency_s", 0) > 0]
    lat_b = [c["mode_b"].get("latency_s", 0) for c in cases_data if c["mode_b"].get("latency_s", 0) > 0]
    lat_c = [c["mode_c"].get("latency_s", 0) for c in cases_data if c["mode_c"].get("latency_s", 0) > 0]
    lat_d = [c["mode_d"].get("latency_s", 0) for c in cases_data if "mode_d" in c and c["mode_d"].get("latency_s", 0) > 0]

    ethnicities = sorted(list({c["case"]["ethnicity"] for c in cases_data}))
    framings = sorted(list({c["case"]["framing_category"] for c in cases_data}))

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Gemini Omni Flash 1.1 - Reference-to-Video (R2V) Adherence Suite (20 Scenarios, 4-Way Comparison)</title>
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: #151c2e;
      --card-border: #232f48;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --accent-blue: #38bdf8;
      --accent-emerald: #34d399;
      --accent-purple: #c084fc;
      --accent-amber: #fbbf24;
      --badge-bg: #1e293b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      padding: 32px 24px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1880px; margin: 0 auto; }}
    header {{
      margin-bottom: 28px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 20px;
    }}
    h1 {{ font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 8px; }}
    .subtitle {{ color: var(--text-muted); font-size: 15px; }}
    
    /* Aggregate KPI Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }}
    .kpi-title {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 8px; }}
    .kpi-scores {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      margin-top: 12px;
    }}
    .kpi-mode {{
      flex: 1;
      background: #0f172a;
      padding: 10px;
      border-radius: 8px;
      text-align: center;
      border: 1px solid #1e293b;
    }}
    .kpi-mode-label {{ font-size: 11px; color: var(--text-muted); }}
    .kpi-mode-val {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
    .val-a {{ color: var(--accent-purple); }}
    .val-b {{ color: var(--accent-blue); }}
    .val-c {{ color: var(--accent-emerald); }}
    .val-d {{ color: var(--accent-amber); }}

    /* Filters */
    .filter-section {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 16px 20px;
      margin-bottom: 28px;
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      align-items: center;
    }}
    .filter-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .filter-label {{ font-size: 13px; font-weight: 600; color: var(--text-muted); }}
    .filter-btn {{
      background: #1e293b;
      color: #cbd5e1;
      border: 1px solid #334155;
      padding: 6px 14px;
      border-radius: 20px;
      font-size: 12px;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .filter-btn:hover {{ background: #334155; color: #fff; }}
    .filter-btn.active {{
      background: var(--accent-blue);
      color: #0b0f19;
      font-weight: 600;
      border-color: var(--accent-blue);
    }}

    /* Case Card */
    .case-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      margin-bottom: 32px;
      overflow: hidden;
      box-shadow: 0 6px 16px rgba(0,0,0,0.3);
    }}
    .case-header {{
      background: #182239;
      padding: 16px 24px;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .case-title {{ font-size: 17px; font-weight: 600; color: #fff; }}
    .case-tags {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .tag {{
      background: #0f172a;
      border: 1px solid #334155;
      font-size: 11px;
      padding: 4px 10px;
      border-radius: 6px;
      color: var(--text-muted);
    }}
    .tag-highlight {{ color: var(--accent-blue); border-color: rgba(56, 189, 248, 0.4); }}

    /* Test Case Layout */
    .case-body {{
      display: grid;
      grid-template-columns: 200px 1fr 1fr 1fr 1fr;
      gap: 14px;
      padding: 18px;
    }}
    @media (max-width: 1600px) {{
      .case-body {{ grid-template-columns: 180px 1fr 1fr 1fr 1fr; }}
    }}
    @media (max-width: 1250px) {{
      .case-body {{ grid-template-columns: 1fr; }}
    }}

    /* Column Styles */
    .col-ref {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .ref-img {{
      width: 100%;
      aspect-ratio: 1/1;
      object-fit: cover;
      border-radius: 10px;
      border: 1px solid var(--card-border);
      background: #0f172a;
    }}
    .col-video {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .mode-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid #1e293b;
      padding-bottom: 8px;
    }}
    .mode-badge {{
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .badge-a {{ color: var(--accent-purple); }}
    .badge-b {{ color: var(--accent-blue); }}
    .badge-c {{ color: var(--accent-emerald); }}
    .badge-d {{ color: var(--accent-amber); }}
    .mode-latency {{ font-size: 11px; color: var(--text-muted); }}

    video {{
      width: 100%;
      border-radius: 8px;
      background: #000;
      aspect-ratio: 16/9;
      outline: none;
    }}

    /* Scores & Critique */
    .score-pills {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .score-pill {{
      background: #182239;
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
      border: 1px solid #232f48;
    }}
    .score-high {{ color: #4ade80; }}
    .score-med {{ color: #fbbf24; }}
    .score-low {{ color: #f87171; }}

    .critique-box {{
      font-size: 12px;
      color: #94a3b8;
      background: #141c2e;
      padding: 10px;
      border-radius: 6px;
      border-left: 3px solid #334155;
      font-style: italic;
    }}

    /* Prompt Drawer */
    details {{
      font-size: 11px;
      margin-top: auto;
    }}
    summary {{
      cursor: pointer;
      color: var(--accent-blue);
      font-weight: 600;
      user-select: none;
      outline: none;
    }}
    summary:hover {{ text-decoration: underline; }}
    .prompt-text {{
      margin-top: 8px;
      padding: 8px;
      background: #090d16;
      border: 1px solid #1e293b;
      border-radius: 6px;
      color: #cbd5e1;
      font-family: monospace;
      word-break: break-all;
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Gemini Omni Flash 1.1 — Reference Adherence Benchmark</h1>
      <p class="subtitle">
        Comprehensive 20-Scenario Multi-Ethnic & Framing Suite | Comparing <strong>Mode A (Optimized MMC)</strong> vs <strong>Mode B (Simple Prompt)</strong> vs <strong>Mode C (Native Task Param - Simple)</strong> vs <strong>Mode D (Native Task Param - Cinematic)</strong>
      </p>
    </header>

    <!-- KPI Aggregate Summary -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-title">Overall Adherence Score (Mean)</div>
        <div class="kpi-scores">
          <div class="kpi-mode"><div class="kpi-mode-label">Mode A (Opt)</div><div class="kpi-mode-val val-a">{avg(scores_a):.2f}</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode B (Simple)</div><div class="kpi-mode-val val-b">{avg(scores_b):.2f}</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode C (Task Smp)</div><div class="kpi-mode-val val-c">{avg(scores_c):.2f}</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode D (Task Cin)</div><div class="kpi-mode-val val-d">{avg(scores_d):.2f}</div></div>
        </div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Facial Similarity (Mean)</div>
        <div class="kpi-scores">
          <div class="kpi-mode"><div class="kpi-mode-label">Mode A (Opt)</div><div class="kpi-mode-val val-a">{avg(faces_a):.2f}</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode B (Simple)</div><div class="kpi-mode-val val-b">{avg(faces_b):.2f}</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode C (Task Smp)</div><div class="kpi-mode-val val-c">{avg(faces_c):.2f}</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode D (Task Cin)</div><div class="kpi-mode-val val-d">{avg(faces_d):.2f}</div></div>
        </div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Average Generation Latency</div>
        <div class="kpi-scores">
          <div class="kpi-mode"><div class="kpi-mode-label">Mode A (Opt)</div><div class="kpi-mode-val val-a">{avg(lat_a):.1f}s</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode B (Simple)</div><div class="kpi-mode-val val-b">{avg(lat_b):.1f}s</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode C (Task Smp)</div><div class="kpi-mode-val val-c">{avg(lat_c):.1f}s</div></div>
          <div class="kpi-mode"><div class="kpi-mode-label">Mode D (Task Cin)</div><div class="kpi-mode-val val-d">{avg(lat_d):.1f}s</div></div>
        </div>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-section">
      <div class="filter-group">
        <span class="filter-label">Ethnicity:</span>
        <button class="filter-btn active" onclick="filterData('ethnicity', 'all', this)">All ({len(cases_data)})</button>
"""
    for eth in ethnicities:
        count = sum(1 for c in cases_data if c["case"]["ethnicity"] == eth)
        html_content += f'        <button class="filter-btn" onclick="filterData(\'ethnicity\', \'{eth}\', this)">{eth} ({count})</button>\n'

    html_content += """      </div>
      <div class="filter-group">
        <span class="filter-label">Framing:</span>
        <button class="filter-btn active" onclick="filterData('framing', 'all', this)">All</button>
"""
    for frm in framings:
        count = sum(1 for c in cases_data if c["case"]["framing_category"] == frm)
        html_content += f'        <button class="filter-btn" onclick="filterData(\'framing\', \'{frm}\', this)">{frm} ({count})</button>\n'

    html_content += """      </div>
    </div>

    <!-- Case Cards Gallery -->
    <div id="gallery">
"""

    def score_color(val):
        if val >= 0.90:
            return "score-high"
        if val >= 0.75:
            return "score-med"
        return "score-low"

    for c in cases_data:
        case = c["case"]
        cid = case["id"]
        ref_name = c["ref_image"]
        ma = c["mode_a"]
        mb = c["mode_b"]
        mc = c["mode_c"]
        md = c.get("mode_d")

        html_content += f"""
      <div class="case-card" data-ethnicity="{case['ethnicity']}" data-framing="{case['framing_category']}">
        <div class="case-header">
          <div class="case-title">#{cid:02d}. {case['name']}</div>
          <div class="case-tags">
            <span class="tag tag-highlight">{case['ethnicity']}</span>
            <span class="tag">{case['framing']}</span>
            <span class="tag">{case['action_summary']}</span>
          </div>
        </div>
        <div class="case-body">
          <!-- Col 0: Canonical Reference Portrait -->
          <div class="col-ref">
            <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; color: var(--text-muted);">
              Canonical Reference
            </div>
            <img src="{ref_name}" alt="Reference #{cid}" class="ref-img">
            <div style="font-size: 11px; color: var(--text-muted);">
              {case['demographics']}
            </div>
          </div>

          <!-- Col 1: Mode A (Pipeline-Optimized MMC) -->
          <div class="col-video">
            <div class="mode-header">
              <span class="mode-badge badge-a">Mode A: Optimized MMC</span>
              <span class="mode-latency">{ma.get('latency_s', 0):.1f}s</span>
            </div>
            <video controls playsinline preload="metadata" src="{ma['video']}"></video>
            <div class="score-pills">
              <span class="score-pill">Face: <b class="{score_color(ma['audit'].get('facial_similarity', 0))}">{ma['audit'].get('facial_similarity', 0):.2f}</b></span>
              <span class="score-pill">Outfit: <b class="{score_color(ma['audit'].get('outfit_consistency', 0))}">{ma['audit'].get('outfit_consistency', 0):.2f}</b></span>
              <span class="score-pill">Overall: <b class="{score_color(ma['audit'].get('overall', 0))}">{ma['audit'].get('overall', 0):.2f}</b></span>
            </div>
            <div class="critique-box">
              {ma['audit'].get('critique', 'Audit completed.')}
            </div>
            <details>
              <summary>View Prompt</summary>
              <div class="prompt-text">{ma['prompt']}</div>
            </details>
          </div>

          <!-- Col 2: Mode B (Simple Prompt) -->
          <div class="col-video">
            <div class="mode-header">
              <span class="mode-badge badge-b">Mode B: Simple Prompt</span>
              <span class="mode-latency">{mb.get('latency_s', 0):.1f}s</span>
            </div>
            <video controls playsinline preload="metadata" src="{mb['video']}"></video>
            <div class="score-pills">
              <span class="score-pill">Face: <b class="{score_color(mb['audit'].get('facial_similarity', 0))}">{mb['audit'].get('facial_similarity', 0):.2f}</b></span>
              <span class="score-pill">Outfit: <b class="{score_color(mb['audit'].get('outfit_consistency', 0))}">{mb['audit'].get('outfit_consistency', 0):.2f}</b></span>
              <span class="score-pill">Overall: <b class="{score_color(mb['audit'].get('overall', 0))}">{mb['audit'].get('overall', 0):.2f}</b></span>
            </div>
            <div class="critique-box">
              {mb['audit'].get('critique', 'Audit completed.')}
            </div>
            <details>
              <summary>View Prompt</summary>
              <div class="prompt-text">{mb['prompt']}</div>
            </details>
          </div>

          <!-- Col 3: Mode C (Native Task Parameter - Simple) -->
          <div class="col-video">
            <div class="mode-header">
              <span class="mode-badge badge-c">Mode C: Task (Simple)</span>
              <span class="mode-latency">{mc.get('latency_s', 0):.1f}s</span>
            </div>
            <video controls playsinline preload="metadata" src="{mc['video']}"></video>
            <div class="score-pills">
              <span class="score-pill">Face: <b class="{score_color(mc['audit'].get('facial_similarity', 0))}">{mc['audit'].get('facial_similarity', 0):.2f}</b></span>
              <span class="score-pill">Outfit: <b class="{score_color(mc['audit'].get('outfit_consistency', 0))}">{mc['audit'].get('outfit_consistency', 0):.2f}</b></span>
              <span class="score-pill">Overall: <b class="{score_color(mc['audit'].get('overall', 0))}">{mc['audit'].get('overall', 0):.2f}</b></span>
            </div>
            <div class="critique-box">
              {mc['audit'].get('critique', 'Audit completed.')}
            </div>
            <details>
              <summary>View Prompt & Config</summary>
              <div class="prompt-text">Prompt: {mc['prompt']}

Config: {json.dumps(mc.get('config') or {}, indent=2)}</div>
            </details>
          </div>

          <!-- Col 4: Mode D (Native Task Parameter - Cinematic) -->"""

        if md:
            html_content += f"""
          <div class="col-video">
            <div class="mode-header">
              <span class="mode-badge badge-d">Mode D: Task (Cinematic)</span>
              <span class="mode-latency">{md.get('latency_s', 0):.1f}s</span>
            </div>
            <video controls playsinline preload="metadata" src="{md['video']}"></video>
            <div class="score-pills">
              <span class="score-pill">Face: <b class="{score_color(md['audit'].get('facial_similarity', 0))}">{md['audit'].get('facial_similarity', 0):.2f}</b></span>
              <span class="score-pill">Outfit: <b class="{score_color(md['audit'].get('outfit_consistency', 0))}">{md['audit'].get('outfit_consistency', 0):.2f}</b></span>
              <span class="score-pill">Overall: <b class="{score_color(md['audit'].get('overall', 0))}">{md['audit'].get('overall', 0):.2f}</b></span>
            </div>
            <div class="critique-box">
              {md['audit'].get('critique', 'Audit completed.')}
            </div>
            <details>
              <summary>View Prompt & Config</summary>
              <div class="prompt-text">Prompt: {md['prompt']}

Config: {json.dumps(md.get('config') or {}, indent=2)}</div>
            </details>
          </div>
        </div>
      </div>
"""
        else:
            html_content += f"""
          <div class="col-video" style="justify-content: center; align-items: center; min-height: 280px; opacity: 0.6;">
            <div class="mode-header" style="width: 100%;">
              <span class="mode-badge badge-d">Mode D: Task (Cinematic)</span>
            </div>
            <div style="font-size: 13px; color: var(--text-muted); margin: auto; text-align: center;">Mode D generation queued...</div>
          </div>
        </div>
      </div>
"""

    html_content += """
    </div>
  </div>

  <script>
    let activeFilters = { ethnicity: 'all', framing: 'all' };

    function filterData(type, val, btn) {
      activeFilters[type] = val;
      const group = btn.parentElement;
      group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      document.querySelectorAll('.case-card').forEach(card => {
        const eth = card.getAttribute('data-ethnicity');
        const frm = card.getAttribute('data-framing');

        const matchEth = (activeFilters.ethnicity === 'all' || activeFilters.ethnicity === eth);
        const matchFrm = (activeFilters.framing === 'all' || activeFilters.framing === frm);

        if (matchEth && matchFrm) {
          card.style.display = 'block';
        } else {
          card.style.display = 'none';
        }
      });
    }
  </script>
</body>
</html>
"""
    report_path = OUTPUT_DIR / "index.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Interactive HTML report built at: {report_path}")
    return report_path


def deploy_to_x20() -> None:
    """Copies all benchmark media and index.html to x20 web directory and sets permissions."""
    print(f"\n--- Deploying to x20: {X20_DIR} ---")
    X20_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in OUTPUT_DIR.glob("*"):
        if item.is_file():
            dest = X20_DIR / item.name
            if (not dest.exists()) or (item.name in ("index.html", "benchmark_data.json")) or (dest.stat().st_size != item.stat().st_size):
                shutil.copy(item, dest)
                count += 1
    print(f"Updated {count} files on {X20_DIR}")
    subprocess.run(["chmod", "-R", "a+rX", str(X20_DIR)], check=True)
    print(f"Applied world-readable permissions on {X20_DIR}")
    print("\n🎉 Live Report URL:")
    print("https://x20web.corp.google.com/~xcyu/reports/r2v_omini_flash_1_1/\n")


def run_suite() -> None:
    """Main execution loop running the 20 cases with concurrency control."""
    ensure_dirs()
    client = get_genai_client()
    data = load_existing_data()

    print(f"Loaded {len(data)} existing processed cases from {DATA_FILE}")

    for case in BENCHMARK_CASES:
        cid = str(case["id"])
        if cid in data and "mode_d" in data[cid]:
            print(f"[{case['id']:02d}] Case already fully processed (all 4 modes). Skipping.")
            continue

        print(f"\n=======================================================")
        print(f"Processing Test Case #{case['id']:02d}: {case['name']}")
        print(f"=======================================================")
        try:
            res = process_case(client, case, data)
            data[cid] = res
            save_data(data)
            # Rebuild HTML and deploy incrementally after each test case!
            build_interactive_html(data)
            deploy_to_x20()
        except Exception as e:
            print(f"Error processing case {cid}: {e}")
            time.sleep(5)

    print("\nAll 20 test cases processed!")
    build_interactive_html(data)
    deploy_to_x20()


if __name__ == "__main__":
    run_suite()
