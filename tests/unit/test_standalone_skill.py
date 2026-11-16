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



def test_single_image_i2v_task_routing_domain_neutral_repairs_and_variable_durations(
    tmp_path: Path, monkeypatch
):
    omni_direct = _load_skill_module("omni_direct")
    workflow = _load_skill_module("run_vidgen_workflow")

    # 1. Verify GA duration bounds helper: [3, 15] for R2V/I2V/T2V vs [3, 10] for extend/interp
    assert omni_direct.resolve_omni_shot_duration(15, default_sec=10, task_or_mode="reference_to_video") == 15
    assert omni_direct.resolve_omni_shot_duration(14, default_sec=10, task_or_mode="image_to_video") == 14
    assert omni_direct.resolve_omni_shot_duration(18, default_sec=10, task_or_mode=None) == 15
    assert omni_direct.resolve_omni_shot_duration(14, default_sec=10, task_or_mode="extend") == 10
    assert omni_direct.resolve_omni_shot_duration(12, default_sec=10, task_or_mode="video_extend") == 10
    assert omni_direct.resolve_omni_shot_duration(15, default_sec=10, is_two_frame_interp=True) == 10
    assert omni_direct.resolve_omni_shot_duration(1, default_sec=10, task_or_mode="reference") == 3

    # 2. Verify single-image <FIRST_FRAME> control string prepends starting-frame cue & sanitizes "reference image"
    ctrl_single_ff = omni_direct.build_omni_control_string(
        prompt="Character A walks forward keeping the sneaker from the reference image in sharp focus",
        input_image_b64="ZmFrZV9mZg==",
        reference_images_b64=["cmVm"],
        duration=12,
        resolution="1080p",
    )
    assert "<FIRST_FRAME>image_0.png" in ctrl_single_ff
    assert "IMAGE_REF" not in ctrl_single_ff
    assert "Character A" not in ctrl_single_ff
    assert "reference image" not in ctrl_single_ff.lower()
    assert "from the starting frame" in ctrl_single_ff
    assert "Use this image as the starting frame." in ctrl_single_ff
    assert "[duration=12s]" in ctrl_single_ff

    # 3. Verify domain-neutral Shot-1 opening & Shot-N closing fallback prompts (zero beauty/blazer/serum tokens)
    footwear_shot = omni_direct.StoryboardEntrySpec(
        scene_number=1,
        description="Carbon-plated running shoe splashes across wet urban asphalt at dusk",
        camera_angle="low-angle tracking",
        evaluation_criteria="Verify outsole geometry",
    )
    for n_refs in (0, 1, 2):
        for pos in ("opening", "closing"):
            p_txt = workflow._build_default_boundary_keyframe_prompt(
                shot_spec=footwear_shot,
                position=pos,
                num_refs=n_refs,
                aspect_ratio="9:16",
            )
            low_txt = p_txt.lower()
            assert "9:16" in p_txt
            assert "blazer" not in low_txt
            assert "serum" not in low_txt
            assert "dropper" not in low_txt
            assert "spokesperson face" not in low_txt
            if n_refs >= 2:
                assert "first reference image" in low_txt and "second reference image" in low_txt
            elif n_refs == 1:
                assert "from the reference image" in low_txt

    # 4. Verify variable cumulative seam window calculation
    seam_wins = omni_direct.compute_seam_transition_windows(
        num_shots=3,
        shot_durations_sec=[15.0, 8.0, 10.0],
        crossfade_sec=0.0,
    )
    assert len(seam_wins) == 2
    assert "around 15.0s" in seam_wins[0] and "[13.5s - 16.5s]" in seam_wins[0]
    assert "around 23.0s" in seam_wins[1] and "[21.5s - 24.5s]" in seam_wins[1]

    # 5. End-to-end mocked check:
    #    - Direct single-image <FIRST_FRAME> call dispatches task="image_to_video" + full response_format (12s, 1080p)
    #    - Multi-scene workflow with variable shot/scene durations + Shot-1 & Shot-3 interpolation keyframe fallbacks
    sample_mp4 = tmp_path / "var_dur_sample.mp4"
    _make_test_mp4_with_audio(sample_mp4, duration_sec=2.0, start_bgr=(45, 115, 195), end_bgr=(45, 115, 195))
    b64_mp4 = base64.b64encode(sample_mp4.read_bytes()).decode("utf-8")

    png_ok, png_arr = cv2.imencode(".png", np.full((180, 320, 3), (200, 215, 230), dtype=np.uint8))
    assert png_ok
    final_png_bytes = png_arr.tobytes()

    anchor = tmp_path / "shoe_anchor.png"
    cv2.imwrite(str(anchor), np.full((180, 320, 3), 255, dtype=np.uint8))
    plate = tmp_path / "track_plate.png"
    plate.write_bytes(final_png_bytes)

    captured_interactions: list = []
    captured_image_prompts: list = []
    captured_master_prompts: list = []

    class _FakeInteractions:
        def create(self, **kwargs):
            captured_interactions.append(kwargs)
            return SimpleNamespace(outputs=[{"data": b64_mp4}])

    class _FakeModels:
        def generate_content(self, *, model: str, contents: Any, config: Any = None):
            mods = getattr(config, "response_modalities", None) or []
            if "IMAGE" in mods:
                captured_image_prompts.append(str(contents[-1]))
                parts = [SimpleNamespace(thought=False, inline_data=SimpleNamespace(data=final_png_bytes))]
                return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))])

            schema = getattr(config, "response_schema", None)
            usage = SimpleNamespace(tool_use_prompt_token_count=2500, prompt_token_count=410)
            if schema is None:
                return SimpleNamespace(text="Low-angle continuous tracking shot on rain-slicked track.", usage_metadata=usage)

            props = getattr(schema, "properties", None) or {}
            if "opening_environment_observed" in props:
                prompt_blob = str(contents[0])
                is_interp = "first_last_frame" in prompt_blob
                # Trigger Shot #1 and Shot #3 boundary repairs on initial pass (< 0.80), then pass at 0.96!
                if ("Shot #1" in prompt_blob or "Shot #3" in prompt_blob) and not is_interp:
                    sc = 0.62
                else:
                    sc = 0.96
                payload = {
                    "opening_environment_observed": "Rain-slicked running track.",
                    "heard_transcript": "Engineered for speed.",
                    "speech_end_sec": 1.0,
                    "detected_internal_cuts": 0,
                    "reason": [{"criterion_name": "SKU Lock", "score": sc, "comments": "Checked"}],
                    "score": sc,
                    "verdict": "PASSED" if sc >= 0.8 else "REATTEMPT_REQUIRED",
                    "feedback": "Re-anchor framing." if sc < 0.8 else "Clean.",
                }
                return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage)

            captured_master_prompts.append(str(contents[0]))
            payload = {
                "seam_observations": [
                    {"seam_index": 1, "window_sec": "13.5s-16.5s", "continuity_score": 0.94, "notes": "Smooth"}
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

    # 5a. Direct single-image <FIRST_FRAME> call -> must set task="image_to_video" + full response_format!
    omni_direct.generate_omni_clip_direct(
        prompt="Camera glides along the carbon outsole from the reference image",
        input_image_b64=omni_direct.encode_image_file_b64(str(plate)),
        aspect_ratio="9:16",
        resolution="1080p",
        duration=12,
        client=fake_client,
    )
    i2v_call = captured_interactions[-1]
    assert i2v_call["generation_config"] == {"video_config": {"task": "image_to_video"}}
    assert i2v_call["response_format"] == {
        "type": "video",
        "aspect_ratio": "9:16",
        "duration": "12s",
        "resolution": "1080p",
    }
    assert "Use this image as the starting frame." in i2v_call["input"][0]["text"]
    assert "reference image" not in i2v_call["input"][0]["text"].lower()

    # 5b. Multi-scene run with variable durations:
    #     Shot 1: R2V 15s (repaired via Shot-1 opening keyframe -> clamped to 10s on two-frame interpolation!)
    #     Shot 2: i2v_chaining 12s (stays 12s via task="image_to_video"!)
    #     Shot 3: video_extend requested 14s -> auto-clamped to 10s, then repaired via Shot-3 closing keyframe!
    captured_interactions.clear()
    monkeypatch.setattr(workflow, "evaluate_clip_quality_direct", omni_direct.evaluate_clip_quality_direct)
    monkeypatch.setattr(workflow, "evaluate_stitched_master_direct", omni_direct.evaluate_stitched_master_direct)
    monkeypatch.setattr(workflow, "generate_omni_clip_direct", omni_direct.generate_omni_clip_direct)
    monkeypatch.setattr(workflow, "generate_reference_image_direct", omni_direct.generate_reference_image_direct)
    monkeypatch.setattr(omni_direct, "analyze_clip_audio_tail", lambda *a, **kw: {
        "clip_duration_sec": 2.0,
        "has_audio": True,
        "mid_rms_db": -19.0,
        "trailing_rms_db": -42.0,
        "tail_window_sec": 0.2,
        "speech_cutoff_detected": False,
    })

    scenes = [
        workflow.SceneSpec(
            scene_id="footwear_act_1",
            title="Urban Track Launch",
            mode="hybrid",
            duration_sec=8,
            reference_paths=[str(anchor), str(plate)],
            shots=[
                workflow.StoryboardEntrySpec(
                    scene_number=1,
                    description="Runner launches off starting blocks in carbon racing shoe",
                    camera_angle="low-angle tracking",
                    evaluation_criteria="Verify shoe geometry",
                    spoken_dialogue="Engineered for speed.",
                    mode_override="reference",
                    duration_sec=15,
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=2,
                    description="Side-profile tracking along wet tartan track",
                    camera_angle="lateral dolly",
                    evaluation_criteria="Verify smooth continuation",
                    spoken_dialogue="Engineered for speed.",
                    mode_override="i2v_chaining",
                    duration_sec=12,
                ),
                workflow.StoryboardEntrySpec(
                    scene_number=3,
                    description="Close-up stride finish across painted finish line",
                    camera_angle="close-up tracking",
                    evaluation_criteria="Verify outsole lock",
                    spoken_dialogue="Engineered for speed.",
                    mode_override="video_extend",
                    duration_sec=14,  # Should clamp to 10s for video_extend & interpolation!
                ),
            ],
        )
    ]

    var_out_dir = tmp_path / "var_dur_out"
    multi_mf = asyncio.run(
        workflow.run_multi_scene_pipeline_async(
            scenes=scenes,
            output_dir=str(var_out_dir),
            original_intent="Footwear variable duration & neutral repair test",
            duration=10,
            max_attempts=1,
            quality_threshold=0.80,
            shot_crossfade_seconds=0.0,
            gen_client=fake_client,
            rater_client=fake_client,
        )
    )

    # Verify initial calls used 15s (R2V), 12s (image_to_video), and 10s (clamped extend),
    # and the two Shot-1 / Shot-3 interpolation repairs clamped to 10s!
    assert len(captured_interactions) == 5
    assert captured_interactions[0]["generation_config"] == {"video_config": {"task": "reference_to_video"}}
    assert captured_interactions[0]["response_format"]["duration"] == "15s"
    assert captured_interactions[1]["generation_config"] == {"video_config": {"task": "image_to_video"}}
    assert captured_interactions[1]["response_format"]["duration"] == "12s"
    assert captured_interactions[2]["generation_config"] == {"video_config": {"task": "extend"}}
    assert captured_interactions[2]["response_format"]["duration"] == "10s"
    assert "generation_config" not in captured_interactions[3]
    assert captured_interactions[3]["response_format"]["duration"] == "10s"
    assert "generation_config" not in captured_interactions[4]
    assert captured_interactions[4]["response_format"]["duration"] == "10s"

    # Verify synthesized Shot-1 opening & Shot-3 closing keyframe prompts were 100% domain-neutral
    assert len(captured_image_prompts) == 2
    for img_p in captured_image_prompts:
        assert "blazer" not in img_p.lower()
        assert "serum" not in img_p.lower()
        assert "carbon" in img_p.lower() or "finish line" in img_p.lower()

    # After Shot 1 repaired (15s -> 10s interp), Shot 2 kept (12s), Shot 3 repaired (10s interp):
    # Final shot durations = [10, 12, 10], repaired scene seam critic must inspect 10.0s and 22.0s!
    sc_rec = multi_mf.scenes[0]
    assert [sh.duration_sec for sh in sc_rec.shots] == [10, 12, 10]
    assert "around 10.0s" in captured_master_prompts[-1]
    assert "around 22.0s" in captured_master_prompts[-1]
    assert os.path.basename(multi_mf.master_video_path) == "output_master_32s.mp4"


def _make_sine_pcm_bytes(duration_sec: float = 7.2, sample_rate: int = 24000) -> bytes:
    n_samples = int(round(duration_sec * sample_rate))
    t = np.arange(n_samples, dtype=np.float32) / float(sample_rate)
    samples = (0.25 * 32767.0 * np.sin(2.0 * np.pi * 440.0 * t)).astype("<i2")
    return samples.tobytes()


def test_director_craft_plan_spec_contact_sheet_and_hitl_gate2(tmp_path: Path, monkeypatch):
    media_ops = _load_skill_module("media_ops")
    omni_direct = _load_skill_module("omni_direct")
    workflow = _load_skill_module("run_vidgen_workflow")

    # 1. Defect taxonomy & remedy mapping
    remedy = omni_direct.format_genmedia_remedy_guidance(
        ["r2v_white_backdrop_echo", "lip_sync_or_speech_mismatch", "unknown_code"]
    )
    assert "r2v_white_backdrop_echo" in remedy
    assert "lip_sync_or_speech_mismatch" in remedy
    assert "unknown_code" not in remedy

    # 2. Pre-flight --check-spec validation (WPM warning, extend duration cap, duplicate angle, missing plate)
    bad_specs = [
        workflow.StoryboardEntrySpec(
            scene_number=1,
            description="Wide lobby walk",
            camera_angle="wide",
            evaluation_criteria="Verify identity",
            spoken_dialogue=" ".join(["word"] * 25),  # > 2.4 wps over 8s
            mode_override="reference",
        ),
        workflow.StoryboardEntrySpec(
            scene_number=2,
            description="Second shot same angle",
            camera_angle="wide",
            evaluation_criteria="",  # Empty -> error!
            mode_override="reference",
            duration_sec=14,
        ),
    ]
    chk = workflow.validate_production_spec(storyboard_specs=bad_specs, default_mode="reference", default_duration=10)
    assert chk["valid"] is False
    assert any("Empty evaluation_criteria" in e for e in chk["errors"])
    assert any("2.4 wps" in w for w in chk["warnings"])
    assert any("15-degree" in w for w in chk["warnings"])

    # 3. Contact sheet rendering from PNG + MP4
    img_p = tmp_path / "plate.png"
    cv2.imwrite(str(img_p), np.full((180, 320, 3), (200, 180, 160), dtype=np.uint8))
    vid_p = tmp_path / "clip.mp4"
    _make_test_mp4_with_audio(vid_p, duration_sec=2.0, start_bgr=(50, 120, 180), end_bgr=(50, 120, 180))
    sheet_p = tmp_path / "qa_sheet.png"
    out_sheet = media_ops.build_contact_sheet(
        items=[
            {"path": str(img_p), "label": "Plate 1", "status": "PLATE"},
            {"path": str(vid_p), "label": "Shot 1", "score": 0.62, "status": "ESCALATED"},
        ],
        output_path=str(sheet_p),
        cols=2,
    )
    assert os.path.exists(out_sheet)
    rendered = cv2.imread(out_sheet)
    assert rendered is not None and rendered.shape[0] > 270 and rendered.shape[1] > 960

    # 4. Gate 2 Escalation (exit code 2 when auto_approve=False and shot < threshold; 0 when auto_approve=True)
    b64_mp4 = base64.b64encode(vid_p.read_bytes()).decode("utf-8")

    class _FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(outputs=[{"data": b64_mp4}])

    class _FakeModels:
        def generate_content(self, *, model: str, contents: Any, config: Any = None):
            schema = getattr(config, "response_schema", None)
            usage = SimpleNamespace(tool_use_prompt_token_count=1200, prompt_token_count=300)
            if schema is None:
                return SimpleNamespace(text="Smooth single-take push-in. The camera movement itself is completely silent.", usage_metadata=usage)
            props = getattr(schema, "properties", None) or {}
            if "opening_environment_observed" in props:
                return SimpleNamespace(
                    text=json.dumps({
                        "opening_environment_observed": "Sunlit studio room.",
                        "heard_transcript": "",
                        "speech_end_sec": None,
                        "detected_internal_cuts": 0,
                        "detected_genmedia_issues": ["hand_or_anatomy_morphing"],
                        "reason": [{"criterion_name": "Anatomy", "score": 0.62, "comments": "Extra finger"}],
                        "score": 0.62,
                        "verdict": "REATTEMPT_REQUIRED",
                        "feedback": "Use relaxed hand grip.",
                    }),
                    usage_metadata=usage,
                )
            return SimpleNamespace(
                text=json.dumps({
                    "project_title": "Test Film",
                    "creative_thesis": "Minimalist precision.",
                    "visual_motif": "Warm stone.",
                    "primary_palette": ["ivory", "amber", "walnut"],
                    "forbidden_colors": ["neon pink", "cyan", "lime"],
                    "lighting_ratio": "4:1 warm key",
                    "lens_language": "50mm -> 85mm",
                    "camera_motion_grammar": "silent dolly",
                    "style_anchor": "35mm natural daylight, zero letterbox bars.",
                    "audio_direction": "Clean room tone.",
                }),
                usage_metadata=usage,
            )

    fake_client = SimpleNamespace(interactions=_FakeInteractions(), models=_FakeModels())
    monkeypatch.setattr(omni_direct, "get_direct_genai_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(workflow, "get_direct_genai_client", lambda *a, **kw: fake_client)
    monkeypatch.setattr(workflow, "evaluate_clip_quality_direct", omni_direct.evaluate_clip_quality_direct)
    monkeypatch.setattr(omni_direct, "analyze_clip_audio_tail", lambda *a, **kw: {
        "clip_duration_sec": 2.0,
        "has_audio": True,
        "mid_rms_db": -22.0,
        "trailing_rms_db": -45.0,
        "tail_window_sec": 0.2,
        "speech_cutoff_detected": False,
    })

    sb_json = tmp_path / "sb.json"
    sb_json.write_text(json.dumps([{
        "scene_number": 1,
        "description": "Hero picks up bottle",
        "camera_angle": "medium tracking",
        "evaluation_criteria": "Verify hand anatomy",
        "fails_if": "Extra fingers",
    }]), encoding="utf-8")

    esc_dir = tmp_path / "esc_out"
    rc_gate2 = workflow.main([
        "--storyboard-json", str(sb_json),
        "--mode", "reference",
        "--duration", "3",
        "--max-attempts", "1",
        "--output-dir", str(esc_dir),
    ])
    assert rc_gate2 == 2
    assert (esc_dir / "escalation_report.json").is_file()
    assert (esc_dir / "qa_contact_sheet.png").is_file()

    auto_dir = tmp_path / "auto_out"
    rc_auto = workflow.main([
        "--storyboard-json", str(sb_json),
        "--mode", "reference",
        "--duration", "3",
        "--max-attempts", "1",
        "--auto-approve",
        "--output-dir", str(auto_dir),
    ])
    assert rc_auto == 0
    assert not (auto_dir / "escalation_report.json").exists()


def test_tpvg_tts_synthesis_chunking_r2v_v2v_dub_and_vo_mux(tmp_path: Path, monkeypatch):
    media_ops = _load_skill_module("media_ops")
    omni_direct = _load_skill_module("omni_direct")
    workflow = _load_skill_module("run_vidgen_workflow")

    # 1. Model alias normalization & raw PCM -> RIFF WAV -> <=3s x 5 chunking
    assert omni_direct.normalize_tts_model_name("gemini-3.8-tts") == "gemini-3.8-flash-tts"
    assert omni_direct.normalize_tts_model_name("gemini-3.8-lite-tts") == "gemini-3.8-flash-lite-tts"

    raw_pcm_7s = _make_sine_pcm_bytes(duration_sec=7.2, sample_rate=24000)
    riff_wav = media_ops.ensure_riff_wav_bytes(raw_pcm_7s, sample_rate=24000)
    assert riff_wav.startswith(b"RIFF")
    dur_s, sr = media_ops.get_wav_duration_sec(riff_wav)
    assert 7.0 <= dur_s <= 7.4 and sr == 24000

    chunks = media_ops.split_wav_reference_chunks(riff_wav, chunk_sec=3.0, max_chunks=5)
    assert len(chunks) == 3
    for ch_b64 in chunks:
        ch_bytes = base64.b64decode(ch_b64)
        assert ch_bytes.startswith(b"RIFF")
        ch_dur, _ = media_ops.get_wav_duration_sec(ch_bytes)
        assert ch_dur <= 3.01

    # 2. Hybrid tpvg_tts workflow: Shot 1 on_camera (R2V + audio refs), Shot 2 off_camera_vo (muxed WAV, no speech in Omni)
    anchor = tmp_path / "hero.png"
    cv2.imwrite(str(anchor), np.full((180, 320, 3), 255, dtype=np.uint8))
    sample_mp4 = tmp_path / "base.mp4"
    _make_test_mp4_with_audio(sample_mp4, duration_sec=2.0, start_bgr=(60, 120, 180), end_bgr=(60, 120, 180))
    b64_mp4 = base64.b64encode(sample_mp4.read_bytes()).decode("utf-8")

    captured_interactions: list = []

    class _FakeInteractions:
        def create(self, **kwargs):
            captured_interactions.append(kwargs)
            return SimpleNamespace(outputs=[{"data": b64_mp4}])

    class _FakeModels:
        def generate_content(self, *, model: str, contents: Any, config: Any = None):
            mods = getattr(config, "response_modalities", None) or []
            if "AUDIO" in mods:
                assert model == "gemini-3.8-flash-tts"
                return SimpleNamespace(
                    candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                        SimpleNamespace(inline_data=SimpleNamespace(data=raw_pcm_7s))
                    ]))]
                )
            schema = getattr(config, "response_schema", None)
            usage = SimpleNamespace(tool_use_prompt_token_count=900, prompt_token_count=200)
            if schema is None:
                return SimpleNamespace(text="Smooth continuous take. The camera movement itself is completely silent.", usage_metadata=usage)
            props = getattr(schema, "properties", None) or {}
            if "opening_environment_observed" in props:
                return SimpleNamespace(
                    text=json.dumps({
                        "opening_environment_observed": "Sunlit studio.",
                        "heard_transcript": "Pure botanical radiance.",
                        "speech_end_sec": 1.2,
                        "detected_internal_cuts": 0,
                        "detected_genmedia_issues": [],
                        "reason": [{"criterion_name": "Continuity", "score": 0.94, "comments": "Good"}],
                        "score": 0.94,
                        "verdict": "PASSED",
                        "feedback": "Clean.",
                    }),
                    usage_metadata=usage,
                )
            return SimpleNamespace(
                text=json.dumps({
                    "seam_observations": [{"seam_index": 1, "window_sec": "0.5s-3.5s", "continuity_score": 0.95, "notes": "Clean"}],
                    "voice_timbre_consistent": True,
                    "loudness_continuity_ok": True,
                    "visual_xfade_smooth": True,
                    "score": 0.95,
                    "verdict": "PASSED",
                    "feedback": "Clean master.",
                }),
                usage_metadata=usage,
            )

    fake_client = SimpleNamespace(interactions=_FakeInteractions(), models=_FakeModels())
    monkeypatch.setattr(workflow, "evaluate_clip_quality_direct", omni_direct.evaluate_clip_quality_direct)
    monkeypatch.setattr(workflow, "evaluate_stitched_master_direct", omni_direct.evaluate_stitched_master_direct)
    monkeypatch.setattr(omni_direct, "analyze_clip_audio_tail", lambda *a, **kw: {
        "clip_duration_sec": 2.0,
        "has_audio": True,
        "mid_rms_db": -18.0,
        "trailing_rms_db": -42.0,
        "tail_window_sec": 0.2,
        "speech_cutoff_detected": False,
    })

    sb = [
        workflow.StoryboardEntrySpec(
            scene_number=1,
            description="Spokesperson holds amber serum bottle in sunlit loft",
            camera_angle="medium tracking",
            evaluation_criteria="Verify identity and lip-sync",
            spoken_dialogue="Pure botanical radiance.",
            audio_mode="on_camera",
            mode_override="reference",
        ),
        workflow.StoryboardEntrySpec(
            scene_number=2,
            description="Macro bottle on travertine plinth while sunlight shifts",
            camera_angle="macro orbit",
            evaluation_criteria="Zero human faces",
            spoken_dialogue="Cold-pressed botanical clarity.",
            audio_mode="off_camera_vo",
            mode_override="reference",
        ),
    ]
    out_dir = tmp_path / "tpvg_out"
    manifest = asyncio.run(
        workflow.run_standalone_pipeline_async(
            prompt="TPVG hybrid test",
            output_dir=str(out_dir),
            mode="tpvg_tts",
            duration=3,
            reference_paths=[str(anchor)],
            storyboard_specs=sb,
            tts_model="gemini-3.8-tts",
            tts_voice="Aoede",
            max_attempts=1,
            auto_approve=True,
            gen_client=fake_client,
            rater_client=fake_client,
        )
    )

    assert manifest.tts_model == "gemini-3.8-flash-tts"
    assert manifest.tts_voice == "Aoede"
    assert len(captured_interactions) == 2

    # Shot 1 (on_camera R2V) must attach type='audio' parts!
    s1_types = [p["type"] for p in captured_interactions[0]["input"]]
    assert "audio" in s1_types
    assert captured_interactions[0]["generation_config"] == {"video_config": {"task": "reference_to_video"}}

    # Shot 2 (off_camera_vo) must NOT pass type='audio' or spoken_dialogue into Omni; it muxes WAV via FFMPEG!
    s2_types = [p["type"] for p in captured_interactions[1]["input"]]
    assert "audio" not in s2_types
    assert "Cold-pressed" not in captured_interactions[1]["input"][0]["text"]
    assert manifest.shots[0].tts_audio_path and os.path.exists(manifest.shots[0].tts_audio_path)
    assert manifest.shots[1].tts_audio_path and os.path.exists(manifest.shots[1].tts_audio_path)

    # 3. Standalone untasked V2V dubbing (`dub_omni_clip_direct`)
    captured_interactions.clear()
    dub_bytes = omni_direct.dub_omni_clip_direct(
        video_path_or_bytes=str(sample_mp4),
        voice_wav_path_or_bytes=manifest.shots[0].tts_audio_path,
        voice_transcript="Pure botanical radiance.",
        duration=3,
        client=fake_client,
    )
    assert len(dub_bytes) > 0
    dub_call = captured_interactions[0]
    assert "generation_config" not in dub_call  # Untasked TASK_UNSPECIFIED for V2V speech editing
    assert [p["type"] for p in dub_call["input"]].count("audio") == 3
    assert [p["type"] for p in dub_call["input"]][1] == "video"

