# Copyright 2026 Author:Hill YU(xcyu@)
"""Unit and CLI integration tests for the standalone ADK-free skill (`Skill/vidgen-long-video`).

Verifies:
1. Zero `google.adk` or `google.cloud.storage` imports across all files in `Skill/vidgen-long-video/`.
2. Symlink resolution between `.agents/skills/vidgen-long-video` and `Skill/vidgen-long-video`.
3. End-to-end OpenCV + FFMPEG operations and CLI subcommands in `media_ops.py` (frames, 5s tail,
   pixel-MAE seam trim, R2V Frame-0 white-lock guard, audio tail RMS cutoff, WER, and 80ms xfade stitch).
4. Direct GenAI control string rules, `MediaProcessing.AGENTIC` part construction, AVU token telemetry,
   and mocked end-to-end orchestration in `omni_direct.py` and `run_vidgen_workflow.py`.
"""

import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "Skill" / "vidgen-long-video"
SYMLINK_DIR = REPO_ROOT / ".agents" / "skills" / "vidgen-long-video"
SCRIPTS_DIR = SKILL_DIR / "scripts"


def _load_skill_module(module_name: str):
    script_path = SCRIPTS_DIR / f"{module_name}.py"
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    mod_key = f"standalone_{module_name}"
    spec = importlib.util.spec_from_file_location(mod_key, script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_key] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_test_mp4_with_audio(
    path: Path,
    duration_sec: float = 2.0,
    start_bgr=(40, 120, 200),
    end_bgr=(40, 120, 200),
    tone_hz: int = 440,
) -> None:
    """Synthesizes an H.264 + 48kHz AAC MP4 clip with smooth frame-by-frame BGR progression."""
    fps = 24
    n_frames = max(1, int(round(duration_sec * fps)))
    raw_vid = path.with_suffix(".raw.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(raw_vid), fourcc, float(fps), (320, 180))
    for i in range(n_frames):
        alpha = i / float(max(1, n_frames - 1))
        bgr = tuple(int(round((1.0 - alpha) * s + alpha * e)) for s, e in zip(start_bgr, end_bgr))
        frame = np.full((180, 320, 3), bgr, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_vid),
        "-f", "lavfi", "-i", f"sine=frequency={tone_hz}:sample_rate=48000:duration={duration_sec}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "12",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        str(path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    if raw_vid.exists():
        raw_vid.unlink()


def test_skill_zero_adk_or_gcs_dependencies():
    assert SKILL_DIR.is_dir(), "Canonical Skill/vidgen-long-video folder missing"
    assert SYMLINK_DIR.is_symlink(), ".agents/skills/vidgen-long-video symlink missing"
    assert (SYMLINK_DIR / "SKILL.md").resolve() == (SKILL_DIR / "SKILL.md").resolve()

    py_files = list(SCRIPTS_DIR.glob("*.py"))
    assert len(py_files) == 3
    for py_file in py_files:
        src = py_file.read_text(encoding="utf-8")
        assert src.startswith("# Copyright 2026 Author:Hill YU(xcyu@)")
        code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        code_body = "\n".join(code_lines)
        assert "google.adk" not in code_body, f"Forbidden ADK import found in {py_file.name}"
        assert "google_adk" not in code_body
        assert "google.cloud.storage" not in code_body, f"Forbidden GCS import found in {py_file.name}"

    req_lines = [
        ln.strip()
        for ln in (SKILL_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert any(ln.startswith("google-genai") for ln in req_lines)
    assert not any("google-adk" in ln for ln in req_lines)
    assert not any("google-cloud-storage" in ln for ln in req_lines)


def test_media_ops_cli_and_primitives(tmp_path: Path):
    media_ops = _load_skill_module("media_ops")

    # Shot 1 progresses from (20, 60, 120) -> (100, 160, 220) over 2.0s
    clip1 = tmp_path / "shot_1.mp4"
    _make_test_mp4_with_audio(
        clip1, duration_sec=2.0, start_bgr=(20, 60, 120), end_bgr=(100, 160, 220), tone_hz=440
    )

    # 1. Extract last frame via CLI (color ~ (100, 160, 220))
    lf_png = tmp_path / "shot_1_last.png"
    rc = media_ops.main(["extract-frame", "--video", str(clip1), "--output", str(lf_png), "--position", "last"])
    assert rc == 0 and lf_png.is_file()

    # 2. Extract 1.0s tail via CLI
    tail_mp4 = tmp_path / "shot_1_tail.mp4"
    rc = media_ops.main(["extract-tail", "--video", str(clip1), "--seconds", "1.0", "--output", str(tail_mp4)])
    assert rc == 0 and tail_mp4.is_file()
    assert 0.8 <= media_ops.get_video_duration(str(tail_mp4)) <= 1.25

    # Build simulated 3.0s extended clip: 1.0s echoed tail + 2.0s continuation (100, 160, 220) -> (180, 200, 240)
    ext_part = tmp_path / "ext_part.mp4"
    _make_test_mp4_with_audio(
        ext_part, duration_sec=2.0, start_bgr=(100, 160, 220), end_bgr=(180, 200, 240), tone_hz=520
    )
    clip2_ext_raw = tmp_path / "shot_2_raw_ext.mp4"
    media_ops.stitch_videos([str(tail_mp4), str(ext_part)], str(clip2_ext_raw), crossfade_seconds=0.0)

    # 3. Trim echoed 1.0s prefix via OpenCV MAE seam alignment CLI -> should yield ~2.0s clip locked to lf_png
    trimmed_mp4 = tmp_path / "shot_2_trimmed.mp4"
    rc = media_ops.main([
        "trim-seam",
        "--video", str(clip2_ext_raw),
        "--trim-seconds", "1.0",
        "--expected-ext-seconds", "1.5",
        "--ref-last-frame", str(lf_png),
        "--output", str(trimmed_mp4),
    ])
    assert rc == 0 and trimmed_mp4.is_file()
    assert 1.8 <= media_ops.get_video_duration(str(trimmed_mp4)) <= 2.2

    # 4. Seam jump-cut check & R2V #FFFFFF lock check
    white_anchor = tmp_path / "white_anchor.png"
    cv2.imwrite(str(white_anchor), np.full((180, 320, 3), 255, dtype=np.uint8))
    locked, f0_mae = media_ops.detect_r2v_first_frame_lock(
        media_ops.encode_image_file_b64(str(white_anchor)), str(clip1)
    )
    assert not locked and f0_mae > 50.0

    has_jump, seam_mae, _ = media_ops.detect_seam_jump_cut(
        media_ops.encode_image_file_b64(str(lf_png)), str(trimmed_mp4)
    )
    assert not has_jump and seam_mae < 8.0

    # 5. Audio tail telemetry + WER + 80ms xfade stitch
    aud = media_ops.analyze_clip_audio_tail(str(clip1), tail_sec=0.20)
    assert aud["has_audio"] is True
    assert aud["trailing_rms_db"] is not None

    wer_metrics = media_ops.compute_transcript_metrics(
        "One golden drop awakens radiance.", "One golden drop awakens radiance"
    )
    assert wer_metrics["transcript_wer"] == 0.0
    assert wer_metrics["transcript_word_overlap"] == 1.0

    stitched = tmp_path / "stitched.mp4"
    rc = media_ops.main([
        "stitch", "--videos", str(clip1), str(trimmed_mp4), "--crossfade", "0.08", "--output", str(stitched)
    ])
    assert rc == 0 and stitched.is_file()
    assert media_ops.get_video_duration(str(stitched)) >= 3.6

    # 6. Agentic Video Part normalization
    part = media_ops.create_agentic_video_part(
        "https://storage.cloud.google.com/demo-bucket/showcase/clip.mp4",
        media_processing="agentic",
    )
    assert part.file_data.file_uri == "gs://demo-bucket/showcase/clip.mp4"
    assert "AGENTIC" in str(part.media_processing).upper()


def test_omni_direct_and_end_to_end_workflow_mocked(tmp_path: Path, monkeypatch):
    omni_direct = _load_skill_module("omni_direct")
    workflow = _load_skill_module("run_vidgen_workflow")

    assert omni_direct.DirectConfig.VIDEO_GEN_MODEL == "gemini-omni-1.2-flash"
    assert omni_direct.DirectConfig.VIDEO_EXTEND_MODEL == "gemini-omni-1.2-flash"
    assert omni_direct.DirectConfig.ORCHESTRATOR_MODEL == "gemini-3.8-flash"

    # Verify control string strips # References and Character A when <FIRST_FRAME> or <VIDEO_0> is present
    ctrl_i2v = omni_direct.build_omni_control_string(
        prompt="Character A walks forward",
        input_image_b64="ZmFrZQ==",
        reference_images_b64=["cmVm"],
    )
    assert "<FIRST_FRAME>image_0.png" in ctrl_i2v
    assert "IMAGE_REF" not in ctrl_i2v
    assert "Character A" not in ctrl_i2v

    ctrl_ext = omni_direct.build_omni_control_string(
        prompt="Character A turns toward window",
        input_video_b64="dmlk",
        task="extend",
        reference_images_b64=["cmVm"],
        voice_transcript="Pure radiance.",
    )
    assert "<VIDEO_0>video_0.mp4" in ctrl_ext
    assert "IMAGE_REF" not in ctrl_ext
    assert "Extend this video:" in ctrl_ext

    # Build real synthetic MP4 bytes + white anchor to exercise full standalone pipeline async loop
    sample_mp4 = tmp_path / "sample.mp4"
    _make_test_mp4_with_audio(sample_mp4, duration_sec=2.0, start_bgr=(60, 140, 220), end_bgr=(60, 140, 220))
    mp4_bytes = sample_mp4.read_bytes()
    b64_mp4 = base64.b64encode(mp4_bytes).decode("utf-8")

    anchor_png = tmp_path / "anchor.png"
    cv2.imwrite(str(anchor_png), np.full((180, 320, 3), 255, dtype=np.uint8))

    class _FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(outputs=[{"data": b64_mp4}])

    class _FakeModels:
        def generate_content(self, *, model: str, contents: Any, config: Any = None):
            assert model == "gemini-3.8-flash"
            schema = getattr(config, "response_schema", None)
            usage = SimpleNamespace(tool_use_prompt_token_count=3210, prompt_token_count=512)
            if schema is None:
                return SimpleNamespace(text="Smooth single-take tracking shot in sunlit stone studio.", usage_metadata=usage)
            props = getattr(schema, "properties", None) or {}
            if "opening_environment_observed" in props:
                payload = {
                    "opening_environment_observed": "Sunlit stone studio with zero white backdrop.",
                    "heard_transcript": "Pure botanical radiance.",
                    "speech_end_sec": 1.2,
                    "detected_internal_cuts": 0,
                    "reason": [{"criterion_name": "SKU Lock", "score": 0.96, "comments": "Exact match"}],
                    "score": 0.96,
                    "verdict": "PASSED",
                    "feedback": "Clean shot.",
                }
                return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)
            if "seam_observations" in props:
                payload = {
                    "seam_observations": [
                        {"seam_index": 1, "window_sec": "0.5s-3.5s", "continuity_score": 0.95, "notes": "Smooth xfade"}
                    ],
                    "voice_timbre_consistent": True,
                    "loudness_continuity_ok": True,
                    "visual_xfade_smooth": True,
                    "score": 0.95,
                    "verdict": "PASSED",
                    "feedback": "Seamless master.",
                }
                return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)
            sb = [
                {
                    "scene_number": 1,
                    "description": "Hero opens bottle in sunlit stone bathroom",
                    "camera_angle": "medium tracking",
                    "evaluation_criteria": "Check bottle & wardrobe lock",
                    "spoken_dialogue": "Pure botanical radiance.",
                    "mode_override": None,
                },
                {
                    "scene_number": 2,
                    "description": "Camera glides closer as golden oil drop catches sunlight",
                    "camera_angle": "close-up dolly",
                    "evaluation_criteria": "Check seam continuity",
                    "spoken_dialogue": "Pure botanical radiance.",
                    "mode_override": None,
                },
            ]
            return SimpleNamespace(text=json.dumps(sb), usage_metadata=usage)

    fake_client = SimpleNamespace(interactions=_FakeInteractions(), models=_FakeModels())
    monkeypatch.setattr(workflow, "evaluate_clip_quality_direct", omni_direct.evaluate_clip_quality_direct)
    monkeypatch.setattr(omni_direct, "analyze_clip_audio_tail", lambda *a, **kw: {
        "clip_duration_sec": 2.0,
        "has_audio": True,
        "mid_rms_db": -18.0,
        "trailing_rms_db": -42.0,
        "tail_window_sec": 0.2,
        "speech_cutoff_detected": False,
    })

    out_dir = tmp_path / "run_out"
    manifest = asyncio.run(
        workflow.run_standalone_pipeline_async(
            prompt="2-shot beauty skincare commercial",
            output_dir=str(out_dir),
            mode="i2v_chaining",
            num_shots=2,
            duration=2,
            reference_paths=[str(anchor_png)],
            max_attempts=2,
            gen_client=fake_client,
            rater_client=fake_client,
        )
    )

    assert manifest.stitched_video_path and os.path.exists(manifest.stitched_video_path)
    assert len(manifest.shots) == 2
    assert all(s.quality_score == 0.96 for s in manifest.shots)
    assert manifest.shots[0].evaluation_report["deterministic_telemetry"]["avu_tool_use_tokens"] == 3210
    assert manifest.master_seam_report["score"] == 0.95
    assert (out_dir / "run_manifest.json").is_file()


def test_multi_scene_workflow_and_first_last_interpolation_repair(tmp_path: Path, monkeypatch):
    omni_direct = _load_skill_module("omni_direct")
    workflow = _load_skill_module("run_vidgen_workflow")

    # 1. Verify <FIRST_FRAME> + <LAST_FRAME> control string & response_format contract
    ctrl_interp = omni_direct.build_omni_control_string(
        prompt="Character A warms golden oil on fingertips",
        input_image_b64="ZmZfcG5n",
        end_image_b64="bGZfcG5n",
        reference_images_b64=["cmVm"],
        duration=10,
    )
    assert "<FIRST_FRAME>image_0.png" in ctrl_interp
    assert "<LAST_FRAME>image_1.png" in ctrl_interp
    assert "IMAGE_REF" not in ctrl_interp
    assert "Character A" not in ctrl_interp
    assert "starting frame" in ctrl_interp and "final frame" in ctrl_interp

    # 2. Verify generate_reference_image_direct skips thought=True draft images
    png_buf_ok, png_arr = cv2.imencode(".png", np.full((180, 320, 3), (210, 225, 240), dtype=np.uint8))
    assert png_buf_ok
    final_png_bytes = png_arr.tobytes()
    draft_png_bytes = b"THOUGHT_DRAFT_SHOULD_BE_SKIPPED"

    sample_mp4 = tmp_path / "sample_scene.mp4"
    _make_test_mp4_with_audio(sample_mp4, duration_sec=2.0, start_bgr=(70, 130, 190), end_bgr=(70, 130, 190))
    mp4_bytes = sample_mp4.read_bytes()
    b64_mp4 = base64.b64encode(mp4_bytes).decode("utf-8")

    interp_mp4 = tmp_path / "sample_interp.mp4"
    _make_test_mp4_with_audio(interp_mp4, duration_sec=2.0, start_bgr=(90, 160, 210), end_bgr=(90, 160, 210))
    interp_mp4_bytes = interp_mp4.read_bytes()
    b64_interp_mp4 = base64.b64encode(interp_mp4_bytes).decode("utf-8")

    hero_anchor = tmp_path / "hero_anchor.png"
    cv2.imwrite(str(hero_anchor), np.full((180, 320, 3), 255, dtype=np.uint8))
    scene_plate = tmp_path / "scene1_ref.png"
    scene_plate.write_bytes(final_png_bytes)

    captured_interactions: list = []
    shot2_eval_count = {"n": 0}

    class _FakeInteractions:
        def create(self, **kwargs):
            captured_interactions.append(kwargs)
            txt = kwargs["input"][0]["text"]
            if "<FIRST_FRAME>" in txt and "<LAST_FRAME>" in txt:
                return SimpleNamespace(outputs=[{"data": b64_interp_mp4}])
            return SimpleNamespace(outputs=[{"data": b64_mp4}])

    class _FakeModels:
        def generate_content(self, *, model: str, contents: Any, config: Any = None):
            mods = getattr(config, "response_modalities", None) or []
            if "IMAGE" in mods:
                parts = [
                    SimpleNamespace(thought=True, inline_data=SimpleNamespace(data=draft_png_bytes)),
                    SimpleNamespace(thought=False, inline_data=SimpleNamespace(data=final_png_bytes)),
                ]
                return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])

            schema = getattr(config, "response_schema", None)
            usage = SimpleNamespace(tool_use_prompt_token_count=4120, prompt_token_count=640)
            if schema is None:
                return SimpleNamespace(text="Smooth single-take push-in inside sunlit travertine bathroom.", usage_metadata=usage)

            props = getattr(schema, "properties", None) or {}
            if "opening_environment_observed" in props:
                prompt_blob = str(contents[0])
                # Force initial Shot #2 score to 0.65 (< 0.80), then 0.97 on <FIRST_FRAME>+<LAST_FRAME> interpolation!
                if "Shot #2" in prompt_blob:
                    shot2_eval_count["n"] += 1
                    is_interp_eval = "first_last_frame" in prompt_blob
                    sc = 0.97 if is_interp_eval else 0.65
                else:
                    sc = 0.95
                payload = {
                    "opening_environment_observed": "Sunlit travertine bathroom.",
                    "heard_transcript": "Silky botanicals melt weightlessly.",
                    "speech_end_sec": 1.1,
                    "detected_internal_cuts": 0,
                    "reason": [{"criterion_name": "Continuity", "score": sc, "comments": "Audited"}],
                    "score": sc,
                    "verdict": "PASSED" if sc >= 0.8 else "REATTEMPT_REQUIRED",
                    "feedback": "Fix mid-shot drift." if sc < 0.8 else "Clean bridge.",
                }
                return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)

            payload = {
                "seam_observations": [
                    {"seam_index": 1, "window_sec": "0.5s-3.5s", "continuity_score": 0.94, "notes": "Smooth"}
                ],
                "voice_timbre_consistent": True,
                "loudness_continuity_ok": True,
                "visual_xfade_smooth": True,
                "score": 0.94,
                "verdict": "PASSED",
                "feedback": "Clean seams.",
            }
            return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)

    fake_client = SimpleNamespace(interactions=_FakeInteractions(), models=_FakeModels())
    gen_img_bytes = omni_direct.generate_reference_image_direct(
        prompt="Sunlit travertine bathroom vanity, 16:9, no people",
        aspect_ratio="16:9",
        client=fake_client,
    )
    assert gen_img_bytes == final_png_bytes

    monkeypatch.setattr(workflow, "evaluate_clip_quality_direct", omni_direct.evaluate_clip_quality_direct)
    monkeypatch.setattr(workflow, "evaluate_stitched_master_direct", omni_direct.evaluate_stitched_master_direct)
    monkeypatch.setattr(workflow, "generate_omni_clip_direct", omni_direct.generate_omni_clip_direct)
    monkeypatch.setattr(workflow, "generate_reference_image_direct", omni_direct.generate_reference_image_direct)
    monkeypatch.setattr(omni_direct, "analyze_clip_audio_tail", lambda *a, **kw: {
        "clip_duration_sec": 2.0,
        "has_audio": True,
        "mid_rms_db": -18.0,
        "trailing_rms_db": -42.0,
        "tail_window_sec": 0.2,
        "speech_cutoff_detected": False,
    })

    scenes = [
        workflow.SceneSpec(
            scene_id="scene_1",
            title="Morning Sanctuary",
            mode="i2v_chaining",
            reference_paths=[str(hero_anchor), str(scene_plate)],
            shots=[
                workflow.StoryboardEntrySpec(
                    scene_number=1,
                    description="Spokesperson opens amber serum bottle",
                    camera_angle="medium close-up",
                    evaluation_criteria="Verify bottle lock",
                    spoken_dialogue="Silky botanicals melt weightlessly.",
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=2,
                    description="Continuous push-in warming golden drop",
                    camera_angle="close-up push-in",
                    evaluation_criteria="Verify smooth continuation",
                    spoken_dialogue="Silky botanicals melt weightlessly.",
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=3,
                    description="Orbital close-up holding bottle beside radiant skin",
                    camera_angle="orbital close-up",
                    evaluation_criteria="Verify closing pose",
                    spoken_dialogue="Silky botanicals melt weightlessly.",
                ),
            ],
        ),
        workflow.SceneSpec(
            scene_id="scene_2",
            title="Botanical Atelier",
            mode="i2v_chaining",
            reference_paths=[str(hero_anchor), str(scene_plate)],
            shots=[
                workflow.StoryboardEntrySpec(
                    scene_number=1,
                    description="Spokesperson stands at sunlit botanical atelier table",
                    camera_angle="medium tracking",
                    evaluation_criteria="Verify bottle lock",
                    spoken_dialogue="Silky botanicals melt weightlessly.",
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=2,
                    description="Smooth dolly along chamomile stems",
                    camera_angle="lateral dolly",
                    evaluation_criteria="Verify smooth continuation",
                    spoken_dialogue="Silky botanicals melt weightlessly.",
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=3,
                    description="Hero rests bottle on limestone counter",
                    camera_angle="close-up dolly",
                    evaluation_criteria="Verify closing pose",
                    spoken_dialogue="Silky botanicals melt weightlessly.",
                ),
            ],
        ),
    ]

    multi_out = tmp_path / "multi_scene_out"
    multi_manifest = asyncio.run(
        workflow.run_multi_scene_pipeline_async(
            scenes=scenes,
            output_dir=str(multi_out),
            original_intent="2-scene skincare test with interpolation repair",
            duration=3,
            max_attempts=1,
            max_parallel_scenes=2,
            quality_threshold=0.80,
            gen_client=fake_client,
            rater_client=fake_client,
        )
    )

    assert multi_manifest.master_video_path and os.path.exists(multi_manifest.master_video_path)
    assert len(multi_manifest.scenes) == 2
    for sc_rec in multi_manifest.scenes:
        assert len(sc_rec.interpolation_repairs) == 1
        rep = sc_rec.interpolation_repairs[0]
        assert rep.shot_index == 2
        assert rep.original_score == 0.65
        assert rep.interpolated_score == 0.97
        assert rep.accepted is True
        assert rep.original_video_path and os.path.exists(rep.original_video_path)
        assert rep.original_video_path.endswith("shot_2_failed_before_heal.mp4")
        assert Path(rep.original_video_path).read_bytes() == mp4_bytes
        assert Path(sc_rec.shots[1].video_path).read_bytes() == interp_mp4_bytes
        assert sc_rec.shots[1].effective_mode == "first_last_interpolation"
        assert sc_rec.shots[1].quality_score == 0.97

    # Confirm at least two interactions calls passed both <FIRST_FRAME> and <LAST_FRAME> with explicit response_format
    interp_calls = [
        c for c in captured_interactions
        if "<FIRST_FRAME>" in c["input"][0]["text"] and "<LAST_FRAME>" in c["input"][0]["text"]
    ]
    assert len(interp_calls) == 2
    assert interp_calls[0]["response_format"]["duration"] == "3s"
    assert "generation_config" not in interp_calls[0]


def test_standalone_upscale_and_draft_mode_multi_scene_workflow(tmp_path: Path, monkeypatch):
    omni_direct = _load_skill_module("omni_direct")
    workflow = _load_skill_module("run_vidgen_workflow")

    # 1. Verify GA upscale transition guardrails (360p -> 4k and 1080p -> 4k rejected)
    assert omni_direct.validate_upscale_transition("360p", "720p") == ("360p", "720p")
    assert omni_direct.validate_upscale_transition("360p", "1080p") == ("360p", "1080p")
    assert omni_direct.validate_upscale_transition("720p", "4K") == ("720p", "4k")
    try:
        omni_direct.validate_upscale_transition("360p", "4k")
        raise AssertionError("Expected ValueError for unsupported single-hop 360p -> 4k")
    except ValueError as err:
        assert "360p" in str(err) and "4k" in str(err)

    draft_mp4 = tmp_path / "draft_360p.mp4"
    _make_test_mp4_with_audio(draft_mp4, duration_sec=2.0, start_bgr=(50, 110, 180), end_bgr=(50, 110, 180))
    draft_bytes = draft_mp4.read_bytes()
    b64_draft = base64.b64encode(draft_bytes).decode("utf-8")

    upscaled_mp4 = tmp_path / "upscaled_720p.mp4"
    _make_test_mp4_with_audio(upscaled_mp4, duration_sec=2.0, start_bgr=(80, 150, 225), end_bgr=(80, 150, 225))
    upscaled_bytes = upscaled_mp4.read_bytes()
    b64_upscaled = base64.b64encode(upscaled_bytes).decode("utf-8")

    png_ok, png_arr = cv2.imencode(".png", np.full((180, 320, 3), (210, 225, 240), dtype=np.uint8))
    assert png_ok
    scene_plate = tmp_path / "plate.png"
    scene_plate.write_bytes(png_arr.tobytes())
    hero_anchor = tmp_path / "anchor.png"
    cv2.imwrite(str(hero_anchor), np.full((180, 320, 3), 255, dtype=np.uint8))

    captured_calls: list = []

    class _FakeInteractions:
        def create(self, **kwargs):
            captured_calls.append(kwargs)
            gen_cfg = kwargs.get("generation_config") or {}
            v_task = (gen_cfg.get("video_config") or {}).get("task")
            if v_task == "upscale":
                usage = SimpleNamespace(total_input_tokens=0, total_output_tokens=5792, total_thought_tokens=0)
                return SimpleNamespace(outputs=[{"data": b64_upscaled}], usage=usage)
            return SimpleNamespace(outputs=[{"data": b64_draft}])

    class _FakeModels:
        def generate_content(self, *, model: str, contents: Any, config: Any = None):
            schema = getattr(config, "response_schema", None)
            usage = SimpleNamespace(tool_use_prompt_token_count=2800, prompt_token_count=490)
            if schema is None:
                return SimpleNamespace(text="Continuous single-take shot in sunlit studio.", usage_metadata=usage)
            props = getattr(schema, "properties", None) or {}
            if "opening_environment_observed" in props:
                prompt_blob = str(contents[0])
                is_shot2 = "Shot #2" in prompt_blob
                is_interp = "first_last_frame" in prompt_blob
                sc = (0.98 if is_interp else 0.62) if is_shot2 else 0.94
                payload = {
                    "opening_environment_observed": "Sunlit studio.",
                    "heard_transcript": "Pure botanical care.",
                    "speech_end_sec": 1.1,
                    "detected_internal_cuts": 0,
                    "reason": [{"criterion_name": "SKU Lock", "score": sc, "comments": "Checked"}],
                    "score": sc,
                    "verdict": "PASSED" if sc >= 0.8 else "REATTEMPT_REQUIRED",
                    "feedback": "Retry bridge." if sc < 0.8 else "Clean.",
                }
                return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)
            payload = {
                "seam_observations": [
                    {"seam_index": 1, "window_sec": "0.5s-3.5s", "continuity_score": 0.93, "notes": "Smooth"}
                ],
                "voice_timbre_consistent": True,
                "loudness_continuity_ok": True,
                "visual_xfade_smooth": True,
                "score": 0.93,
                "verdict": "PASSED",
                "feedback": "Clean seams.",
            }
            return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)

    fake_client = SimpleNamespace(interactions=_FakeInteractions(), models=_FakeModels())

    # 2. Direct upscale_omni_clip_direct test
    up_out, up_tel = omni_direct.upscale_omni_clip_direct(
        draft_bytes,
        target_resolution="720p",
        source_resolution="360p",
        return_telemetry=True,
        client=fake_client,
    )
    assert up_out == upscaled_bytes
    assert up_tel["total_input_tokens"] == 0
    assert up_tel["total_output_tokens"] == 5792
    assert captured_calls[-1]["generation_config"] == {"video_config": {"task": "upscale"}}
    assert captured_calls[-1]["response_format"] == {"type": "video", "resolution": "720p"}

    # 3. End-to-end --draft-mode multi-scene workflow (360p draft + 360p <FIRST_FRAME>+<LAST_FRAME> heal + concurrent 720p upscale)
    captured_calls.clear()
    monkeypatch.setattr(workflow, "evaluate_clip_quality_direct", omni_direct.evaluate_clip_quality_direct)
    monkeypatch.setattr(workflow, "evaluate_stitched_master_direct", omni_direct.evaluate_stitched_master_direct)
    monkeypatch.setattr(workflow, "generate_omni_clip_direct", omni_direct.generate_omni_clip_direct)
    monkeypatch.setattr(workflow, "upscale_omni_clip_direct", omni_direct.upscale_omni_clip_direct)
    monkeypatch.setattr(omni_direct, "analyze_clip_audio_tail", lambda *a, **kw: {
        "clip_duration_sec": 2.0,
        "has_audio": True,
        "mid_rms_db": -19.0,
        "trailing_rms_db": -41.0,
        "tail_window_sec": 0.2,
        "speech_cutoff_detected": False,
    })

    scenes = [
        workflow.SceneSpec(
            scene_id="act_1",
            title="Act 1 Draft->Upscale Test",
            mode="video_extend",
            reference_paths=[str(hero_anchor), str(scene_plate)],
            shots=[
                workflow.StoryboardEntrySpec(
                    scene_number=1,
                    description="Spokesperson holds serum bottle",
                    camera_angle="medium tracking",
                    evaluation_criteria="Verify bottle",
                    spoken_dialogue="Pure botanical care.",
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=2,
                    description="Camera pushes in on serum drop",
                    camera_angle="close-up push-in",
                    evaluation_criteria="Verify smooth continuation",
                    spoken_dialogue="Pure botanical care.",
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=3,
                    description="Bottle rests on sunlit stone plinth",
                    camera_angle="macro dolly",
                    evaluation_criteria="Verify plinth close",
                    spoken_dialogue="Pure botanical care.",
                ),
            ],
        )
    ]

    draft_out_dir = tmp_path / "draft_multi_out"
    manifest = asyncio.run(
        workflow.run_multi_scene_pipeline_async(
            scenes=scenes,
            output_dir=str(draft_out_dir),
            original_intent="Draft mode test",
            duration=3,
            resolution="720p",
            draft_mode=True,
            draft_resolution="360p",
            max_attempts=1,
            max_parallel_scenes=1,
            max_parallel_upscales=3,
            quality_threshold=0.80,
            gen_client=fake_client,
            rater_client=fake_client,
        )
    )

    assert manifest.draft_mode is True
    assert manifest.draft_resolution == "360p"
    assert manifest.resolution == "720p"
    assert manifest.master_video_path and os.path.exists(manifest.master_video_path)

    # Verify all generation & interpolation calls ran at 360p, and ONLY the 3 winning clips were upscaled to 720p!
    non_upscale_calls = [
        c for c in captured_calls
        if ((c.get("generation_config") or {}).get("video_config") or {}).get("task") != "upscale"
    ]
    upscale_calls = [
        c for c in captured_calls
        if ((c.get("generation_config") or {}).get("video_config") or {}).get("task") == "upscale"
    ]
    assert len(non_upscale_calls) == 4  # 3 draft shots + 1 <FIRST_FRAME>+<LAST_FRAME> heal, all at 360p!
    assert all(c["response_format"]["resolution"] == "360p" for c in non_upscale_calls)
    assert len(upscale_calls) == 3  # Only the 3 final winning clips upscaled!
    assert all(c["response_format"] == {"type": "video", "resolution": "720p"} for c in upscale_calls)

    sc_rec = manifest.scenes[0]
    assert len(sc_rec.interpolation_repairs) == 1
    assert sc_rec.interpolation_repairs[0].accepted is True
    for sh in sc_rec.shots:
        assert sh.draft_video_path and sh.draft_video_path.endswith("_draft_360p.mp4")
        assert os.path.exists(sh.draft_video_path)
        assert Path(sh.video_path).read_bytes() == upscaled_bytes
        assert sh.upscale_telemetry["total_input_tokens"] == 0
