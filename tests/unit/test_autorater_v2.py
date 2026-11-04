# Copyright 2026 Author:Hill YU(xcyu@)
"""Unit tests for Auto-Rater v2 (observation-first schema, ground-truth attachments, WER/cutoff guardrails, Best-of-K retries, post-stitch seam audit, parallel Mode A, and hybrid choreography)."""

import asyncio
import base64
import json
import os
import tempfile
import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from app.agents.pipeline import (
    QUALITY_EVALUATION_PROPERTY_ORDER,
    build_master_seam_evaluation_schema,
    build_quality_evaluation_schema,
    evaluate_clip_quality,
    evaluate_stitched_master,
    run_production_loop_async,
)
from app.state import PipelineState, StoryboardEntry, VideoShot
from app.tools.video_parser import compute_transcript_metrics, decode_valid_image_b64


def _make_png_b64(bgr_color: tuple = (255, 255, 255), size: int = 64) -> str:
    img = np.full((size, size, 3), bgr_color, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _make_mp4_bytes(bgr_color: tuple = (45, 90, 140), frames: int = 60, fps: float = 10.0) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        path = tmp.name
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(path, fourcc, fps, (64, 64))
        for _ in range(frames):
            writer.write(np.full((64, 64, 3), bgr_color, dtype=np.uint8))
        writer.release()
        with open(path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_schema_observation_first_property_ordering():
    schema = build_quality_evaluation_schema()
    order = list(schema.property_ordering)
    assert order == QUALITY_EVALUATION_PROPERTY_ORDER
    score_idx = order.index("score")
    verdict_idx = order.index("verdict")
    for obs_field in (
        "opening_environment_observed",
        "heard_transcript",
        "speech_end_sec",
        "detected_internal_cuts",
        "reason",
    ):
        assert order.index(obs_field) < score_idx
        assert order.index(obs_field) < verdict_idx

    seam_schema = build_master_seam_evaluation_schema()
    seam_order = list(seam_schema.property_ordering)
    assert seam_order.index("seam_observations") < seam_order.index("score")
    assert seam_order.index("voice_timbre_consistent") < seam_order.index("score")


@pytest.mark.asyncio
async def test_ground_truth_reference_and_boundary_attachment():
    white_anchor_b64 = _make_png_b64((255, 255, 255))
    prior_frame_b64 = _make_png_b64((60, 120, 180))
    mp4_bytes = _make_mp4_bytes((50, 100, 160), frames=20)

    # Verify decode_valid_image_b64 rejects mock strings and accepts real PNGs
    assert decode_valid_image_b64("fake_ref_b64") is None
    assert decode_valid_image_b64(white_anchor_b64) is not None

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(mp4_bytes)
        clip_path = tmp.name

    try:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "opening_environment_observed": "Sunlit terracotta street with spokesperson in sage linen jacket",
            "heard_transcript": "Welcome to our spring showcase",
            "speech_end_sec": 1.2,
            "detected_internal_cuts": 0,
            "reason": [{"criterion_name": "SKU Lock", "score": 0.94, "comments": "Matches anchor"}],
            "score": 0.94,
            "verdict": "PASSED",
            "feedback": "Clean continuity.",
        })
        mock_client.models.generate_content.return_value = mock_resp

        res = await evaluate_clip_quality(
            shot_index=2,
            prompt="Medium tracking shot of spokesperson walking down sunlit street",
            video_path=clip_path,
            spoken_dialogue="Welcome to our spring showcase",
            reference_images_b64=[white_anchor_b64],
            prev_last_frame_b64=prior_frame_b64,
            deterministic_signals={"r2v_f0_mae": 74.5, "seam_mae": 8.2},
            is_r2v_shot=True,
            client=mock_client,
        )

        assert res["score"] == 0.94
        assert res["verdict"] == "PASSED"
        assert res["transcript_wer"] == 0.0
        assert res["transcript_word_overlap"] == 1.0

        call_kwargs = mock_client.models.generate_content.call_args.kwargs
        contents = call_kwargs["contents"]
        text_labels = [c for c in contents if isinstance(c, str)]
        joined_labels = "\n".join(text_labels)
        assert "CANONICAL REFERENCE ANCHOR" in joined_labels
        assert "PRIOR SHOT TERMINAL FRAME" in joined_labels
        assert "KEY FRAME A" in joined_labels
        assert "KEY FRAME M" in joined_labels
        assert "KEY FRAME B" in joined_labels
        assert "r2v_f0_mae" in joined_labels

        # Also verify mock base64 strings do not crash attachment
        mock_client.models.generate_content.reset_mock()
        res_mock_ref = await evaluate_clip_quality(
            shot_index=1,
            prompt="Test mock ref string",
            video_path=clip_path,
            reference_images_b64=["fake_ref_b64"],
            client=mock_client,
        )
        assert res_mock_ref["verdict"] == "PASSED"
    finally:
        if os.path.exists(clip_path):
            os.remove(clip_path)


@pytest.mark.asyncio
async def test_transcript_wer_and_post_rater_guardrails():
    m_exact = compute_transcript_metrics("Discover timeless linen tailoring today.", "discover timeless linen tailoring today")
    assert m_exact["transcript_wer"] == 0.0
    assert m_exact["transcript_word_overlap"] == 1.0

    m_partial = compute_transcript_metrics("One two three four", "one two")
    assert m_partial["transcript_wer"] == 0.5
    assert m_partial["transcript_word_overlap"] == 0.5

    mp4_bytes = _make_mp4_bytes((40, 80, 120), frames=20)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(mp4_bytes)
        clip_path = tmp.name

    try:
        # Case 1: High WER (> 0.35) forces score < 0.8 -> REATTEMPT_REQUIRED even if LLM returned 0.92
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "opening_environment_observed": "Cafe interior",
            "heard_transcript": "Completely wrong words spoken",
            "speech_end_sec": 5.0,
            "detected_internal_cuts": 0,
            "reason": [{"criterion_name": "Visual", "score": 0.92, "comments": "Looks nice"}],
            "score": 0.92,
            "verdict": "PASSED",
            "feedback": "Visuals look good.",
        })
        mock_client.models.generate_content.return_value = mock_resp

        res_wer = await evaluate_clip_quality(
            shot_index=1,
            prompt="Spokesperson speaking line",
            video_path=clip_path,
            spoken_dialogue="Discover breathable organic linen for summer",
            client=mock_client,
        )
        assert res_wer["transcript_wer"] > 0.35
        assert res_wer["score"] <= 0.68
        assert res_wer["verdict"] == "REATTEMPT_REQUIRED"
        assert "WER=" in res_wer["feedback"]

        # Case 2: Internal jump-cuts > 0 caps score <= 0.60 -> REATTEMPT_REQUIRED
        mock_resp.text = json.dumps({
            "opening_environment_observed": "Boutique showroom",
            "heard_transcript": "",
            "speech_end_sec": None,
            "detected_internal_cuts": 2,
            "reason": [{"criterion_name": "Motion", "score": 0.90, "comments": "Two angles"}],
            "score": 0.90,
            "verdict": "PASSED",
            "feedback": "Nice lighting.",
        })
        res_cuts = await evaluate_clip_quality(
            shot_index=1,
            prompt="Single continuous tracking shot",
            video_path=clip_path,
            client=mock_client,
        )
        assert res_cuts["score"] <= 0.60
        assert res_cuts["verdict"] == "REATTEMPT_REQUIRED"

        # Case 3: Timeout / exception triggers AUDIT_TIMEOUT_DEGRADED instead of silent PASS
        failing_client = MagicMock()
        failing_client.models.generate_content.side_effect = TimeoutError("Deadline exceeded 120s")
        res_timeout = await evaluate_clip_quality(
            shot_index=1,
            prompt="Timeout test",
            video_path=clip_path,
            client=failing_client,
        )
        assert res_timeout["audit_status"] == "AUDIT_TIMEOUT_DEGRADED"
        assert res_timeout["verdict"] == "AUDIT_TIMEOUT_DEGRADED"
    finally:
        if os.path.exists(clip_path):
            os.remove(clip_path)


@pytest.mark.asyncio
async def test_monotonic_best_of_k_checkpointing():
    attempt_1_mp4 = _make_mp4_bytes((30, 180, 60), frames=15)   # Distinct Attempt 1 clip
    attempt_2_mp4 = _make_mp4_bytes((180, 30, 30), frames=15)   # Regressed Attempt 2 clip

    mock_client = MagicMock()
    int_1 = MagicMock()
    int_1.output = attempt_1_mp4
    int_2 = MagicMock()
    int_2.output = attempt_2_mp4
    mock_client.interactions.create.side_effect = [int_1, int_2]

    # Sequence of generate_content responses:
    # Attempt 1: optimizer -> health -> rater (0.76)
    # Attempt 2: optimizer -> health -> rater (0.52 - worse!)
    def _make_text_resp(txt: str):
        m = MagicMock()
        m.text = txt
        return m

    rater_1 = json.dumps({
        "opening_environment_observed": "Good cafe scene",
        "heard_transcript": "",
        "speech_end_sec": None,
        "detected_internal_cuts": 0,
        "reason": [{"criterion_name": "Continuity", "score": 0.76, "comments": "Minor motion blur"}],
        "score": 0.76,
        "verdict": "REATTEMPT_REQUIRED",
        "feedback": "Reduce motion blur slightly.",
    })
    rater_2 = json.dumps({
        "opening_environment_observed": "Drifted background",
        "heard_transcript": "",
        "speech_end_sec": None,
        "detected_internal_cuts": 1,
        "reason": [{"criterion_name": "Continuity", "score": 0.52, "comments": "Jump cut introduced"}],
        "score": 0.52,
        "verdict": "REATTEMPT_REQUIRED",
        "feedback": "Eliminate internal jump cut.",
    })
    mock_client.models.generate_content.side_effect = [
        _make_text_resp("Attempt 1 optimized cinematic prompt"),
        _make_text_resp("APPROVED"),
        _make_text_resp(rater_1),
        _make_text_resp("Attempt 2 regressed prompt"),
        _make_text_resp("APPROVED"),
        _make_text_resp(rater_2),
    ]

    state = PipelineState(
        original_intent="Single shot Best-of-K test",
        num_shots=1,
        mode="i2v_chaining",
        max_attempts=2,
        shots=[VideoShot(shot_index=1, prompt="Raw shot 1")],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        final_state = await run_production_loop_async(state, output_dir=tmpdir, client=mock_client)
        shot = final_state.shots[0]
        assert shot.quality_score == 0.76
        assert shot.prompt == "Attempt 1 optimized cinematic prompt"
        with open(shot.video_path, "rb") as f:
            saved_bytes = f.read()
        assert saved_bytes == attempt_1_mp4


@pytest.mark.asyncio
async def test_post_stitch_master_seam_audit():
    mp4_bytes = _make_mp4_bytes((80, 110, 140), frames=30)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(mp4_bytes)
        master_path = tmp.name

    try:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "seam_observations": [
                {
                    "seam_timestamp_sec": 10.0,
                    "visual_transition_notes": "Clean 80ms dissolve",
                    "audio_transition_notes": "Natural room tone across seam",
                    "seam_score": 0.93,
                },
                {
                    "seam_timestamp_sec": 20.0,
                    "visual_transition_notes": "Smooth tracking handoff",
                    "audio_transition_notes": "Consistent voice timbre",
                    "seam_score": 0.95,
                },
            ],
            "voice_timbre_consistent": True,
            "loudness_continuity_ok": True,
            "visual_xfade_smooth": True,
            "score": 0.94,
            "verdict": "PASSED",
            "feedback": "Seamless 30s master commercial.",
        })
        mock_client.models.generate_content.return_value = mock_resp

        report = await evaluate_stitched_master(
            stitched_video_path=master_path,
            num_shots=3,
            shot_duration_sec=10.0,
            original_intent="30s luxury espresso commercial",
            client=mock_client,
        )
        assert report["score"] == 0.94
        assert report["verdict"] == "PASSED"
        assert len(report["seam_observations"]) == 2

        prompt_sent = mock_client.models.generate_content.call_args.kwargs["contents"][0]
        assert "[8.5s - 11.5s]" in prompt_sent
        assert "[18.5s - 21.5s]" in prompt_sent
    finally:
        if os.path.exists(master_path):
            os.remove(master_path)


@pytest.mark.asyncio
async def test_parallel_reference_mode_concurrency_and_order(monkeypatch):
    import threading

    mp4_bytes = _make_mp4_bytes((70, 120, 90), frames=20)
    anchor_b64 = _make_png_b64((255, 255, 255))

    lock = threading.Lock()
    active_count = 0
    peak_concurrency = 0

    def slow_generate_omni_clip(**kwargs):
        nonlocal active_count, peak_concurrency
        with lock:
            active_count += 1
            peak_concurrency = max(peak_concurrency, active_count)
        try:
            time.sleep(0.55)
            return mp4_bytes
        finally:
            with lock:
                active_count -= 1

    def fast_stitch(clips, out_path):
        with open(out_path, "wb") as f:
            f.write(mp4_bytes)
        return out_path

    monkeypatch.setattr("app.agents.pipeline.generate_omni_clip", slow_generate_omni_clip)
    monkeypatch.setattr("app.agents.pipeline.stitch_videos", fast_stitch)

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "opening_environment_observed": "Modern kitchen counter",
        "heard_transcript": "",
        "speech_end_sec": None,
        "detected_internal_cuts": 0,
        "reason": [{"criterion_name": "SKU", "score": 0.95, "comments": "Exact"}],
        "score": 0.95,
        "verdict": "PASSED",
        "feedback": "Great.",
    })
    mock_client.models.generate_content.return_value = mock_resp

    state = PipelineState(
        original_intent="Parallel Mode A benchmark",
        num_shots=3,
        mode="reference",
        max_attempts=1,
        reference_assets_b64=[anchor_b64],
        shots=[
            VideoShot(shot_index=1, prompt="Shot 1"),
            VideoShot(shot_index=2, prompt="Shot 2"),
            VideoShot(shot_index=3, prompt="Shot 3"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        t0 = time.monotonic()
        final_state = await run_production_loop_async(state, output_dir=tmpdir, client=mock_client)
        elapsed = time.monotonic() - t0
        # Verify true concurrent execution across all 3 Mode A shots and deterministic order
        assert peak_concurrency == 3
        assert elapsed < 1.55  # Sequential 3 x 0.55s alone would take >= 1.65s + subprocess overhead
        assert [s.shot_index for s in final_state.shots] == [1, 2, 3]
        assert final_state.stitched_video_path is not None
        assert final_state.master_quality_report is not None


@pytest.mark.asyncio
async def test_hybrid_per_shot_mode_override_choreography():
    mp4_bytes = _make_mp4_bytes((50, 95, 130), frames=60, fps=10.0)
    white_anchor_b64 = _make_png_b64((255, 255, 255))

    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = mp4_bytes
    mock_client.interactions.create.return_value = mock_interaction

    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "opening_environment_observed": "Sunlit patio",
        "heard_transcript": "",
        "speech_end_sec": None,
        "detected_internal_cuts": 0,
        "reason": [{"criterion_name": "Continuity", "score": 0.95, "comments": "Smooth"}],
        "score": 0.95,
        "verdict": "PASSED",
        "feedback": "Approved.",
    })
    mock_client.models.generate_content.return_value = mock_resp

    # Shot 1: R2V anchor -> Shot 2: Video Extend continuous -> Shot 3: Hard cut R2V re-anchor
    state = PipelineState(
        original_intent="Hybrid choreography test",
        num_shots=3,
        mode="hybrid",
        max_attempts=1,
        reference_assets_b64=[white_anchor_b64],
        shots=[
            VideoShot(shot_index=1, prompt="Shot 1 patio opening", mode_override="reference"),
            VideoShot(shot_index=2, prompt="Shot 2 continuous camera push", mode_override="video_extend"),
            VideoShot(shot_index=3, prompt="Shot 3 hard cut rooftop evening", mode_override="reference"),
        ],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        final_state = await run_production_loop_async(state, output_dir=tmpdir, client=mock_client)
        assert final_state.stitched_video_path is not None
        calls = mock_client.interactions.create.call_args_list
        assert len(calls) == 3

        # Shot 1: reference_to_video with image anchor
        assert calls[0].kwargs["generation_config"] == {"video_config": {"task": "reference_to_video"}}
        assert [p["type"] for p in calls[0].kwargs["input"]] == ["text", "image"]

        # Shot 2: extend with 5s video tail
        assert calls[1].kwargs["generation_config"] == {"video_config": {"task": "extend"}}
        assert [p["type"] for p in calls[1].kwargs["input"]] == ["text", "video"]

        # Shot 3: re-anchored reference_to_video with #FFFFFF image anchor
        assert calls[2].kwargs["generation_config"] == {"video_config": {"task": "reference_to_video"}}
        assert [p["type"] for p in calls[2].kwargs["input"]] == ["text", "image"]
