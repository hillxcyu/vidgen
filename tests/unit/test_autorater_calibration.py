# Copyright 2026 Author:Hill YU(xcyu@)
"""Golden calibration test suite verifying Auto-Rater v2 deterministic audio/visual telemetry on real OpenCV + FFMPEG clips."""

import base64
import json
import math
import os
import struct
import subprocess
import tempfile
import wave
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from app.agents.pipeline import evaluate_clip_quality
from app.tools.video_parser import (
    analyze_clip_audio_tail,
    detect_r2v_first_frame_lock,
    detect_seam_jump_cut,
)


def _synthesize_calibrated_mp4(
    output_path: str,
    duration_sec: float = 4.0,
    fps: float = 10.0,
    speech_end_sec: float = 3.0,
    frame_colors_fn=None,
) -> None:
    """Builds a real H.264/MP4 + AAC/PCM audio clip where vocal sine energy runs until speech_end_sec."""
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_vid = os.path.join(tmpdir, "raw_vid.mp4")
        raw_wav = os.path.join(tmpdir, "raw_aud.wav")

        total_frames = int(round(duration_sec * fps))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(raw_vid, fourcc, fps, (96, 96))
        for idx in range(total_frames):
            bgr = frame_colors_fn(idx) if frame_colors_fn else (60, 110, 170)
            writer.write(np.full((96, 96, 3), bgr, dtype=np.uint8))
        writer.release()

        sr = 16000
        total_samples = int(round(duration_sec * sr))
        speech_samples = int(round(speech_end_sec * sr))
        pcm = []
        for i in range(total_samples):
            t = i / float(sr)
            if 0.2 * sr <= i <= speech_samples:
                # Active vocal energy (~ -12 dBFS)
                amp = int(8200 * math.sin(2.0 * math.pi * 220.0 * t))
            else:
                # Quiet ambient room tone (~ -58 dBFS)
                amp = int(40 * math.sin(2.0 * math.pi * 110.0 * t))
            pcm.append(amp)

        with wave.open(raw_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                raw_vid,
                "-i",
                raw_wav,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                output_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )


def _encode_png_b64(bgr: tuple) -> str:
    img = np.full((96, 96, 3), bgr, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("utf-8")


@pytest.mark.asyncio
async def test_calibration_clean_clip_vs_trailing_speech_cutoff():
    white_anchor_b64 = _encode_png_b64((255, 255, 255))

    with tempfile.TemporaryDirectory() as tmpdir:
        clean_clip = os.path.join(tmpdir, "clean_4s.mp4")
        cutoff_clip = os.path.join(tmpdir, "cutoff_4s.mp4")

        # 1. Clean clip: speech ends cleanly at 2.8s out of 4.0s (quiet 1.2s room-tone tail)
        _synthesize_calibrated_mp4(clean_clip, duration_sec=4.0, speech_end_sec=2.8)
        clean_tel = analyze_clip_audio_tail(clean_clip, tail_sec=0.20)
        assert clean_tel["has_audio"] is True
        assert clean_tel["trailing_rms_db"] < -35.0
        assert clean_tel["speech_cutoff_detected"] is False

        # 2. Abrupt cutoff clip: speech still hot right through 3.8s-4.0s boundary!
        _synthesize_calibrated_mp4(cutoff_clip, duration_sec=4.0, speech_end_sec=4.0)
        cutoff_tel = analyze_clip_audio_tail(cutoff_clip, tail_sec=0.20)
        assert cutoff_tel["has_audio"] is True
        assert cutoff_tel["trailing_rms_db"] > -24.0
        assert cutoff_tel["speech_cutoff_detected"] is True

        # Verify Auto-Rater v2 passes clean clip and deterministically rejects cutoff clip
        mock_client = MagicMock()
        optimistic_resp = MagicMock()
        optimistic_resp.text = json.dumps({
            "opening_environment_observed": "Warm sunlit espresso bar",
            "heard_transcript": "Crafted for mornings that inspire",
            "speech_end_sec": 2.8,
            "detected_internal_cuts": 0,
            "reason": [{"criterion_name": "Overall", "score": 0.93, "comments": "Clean"}],
            "score": 0.93,
            "verdict": "PASSED",
            "feedback": "Looks and sounds great.",
        })
        mock_client.models.generate_content.return_value = optimistic_resp

        res_clean = await evaluate_clip_quality(
            shot_index=1,
            prompt="Barista presenting espresso machine",
            video_path=clean_clip,
            spoken_dialogue="Crafted for mornings that inspire",
            reference_images_b64=[white_anchor_b64],
            is_r2v_shot=True,
            client=mock_client,
        )
        assert res_clean["verdict"] == "PASSED"
        assert res_clean["score"] >= 0.80

        res_cutoff = await evaluate_clip_quality(
            shot_index=1,
            prompt="Barista presenting espresso machine",
            video_path=cutoff_clip,
            spoken_dialogue="Crafted for mornings that inspire",
            reference_images_b64=[white_anchor_b64],
            is_r2v_shot=True,
            client=mock_client,
        )
        assert res_cutoff["score"] <= 0.65
        assert res_cutoff["verdict"] == "REATTEMPT_REQUIRED"
        assert "trailing_rms_db" in res_cutoff["feedback"]


def test_calibration_r2v_white_lock_and_seam_jump_cut():
    white_anchor_b64 = _encode_png_b64((255, 255, 255))
    prior_end_b64 = _encode_png_b64((40, 80, 120))

    with tempfile.TemporaryDirectory() as tmpdir:
        white_locked_clip = os.path.join(tmpdir, "white_locked.mp4")
        jump_cut_clip = os.path.join(tmpdir, "jump_cut.mp4")

        # Scenario 3: Frame 0 locked to #FFFFFF studio background
        _synthesize_calibrated_mp4(
            white_locked_clip,
            duration_sec=2.0,
            speech_end_sec=0.0,
            frame_colors_fn=lambda idx: (254, 254, 254) if idx < 5 else (50, 90, 130),
        )
        locked, f0_mae = detect_r2v_first_frame_lock(white_anchor_b64, white_locked_clip, mae_threshold=12.0)
        assert locked is True
        assert f0_mae < 12.0

        # Scenario 4: Extension clip that teleports to bright orange on Frame 2 (hard jump-cut)
        _synthesize_calibrated_mp4(
            jump_cut_clip,
            duration_sec=2.0,
            speech_end_sec=0.0,
            frame_colors_fn=lambda idx: (40, 80, 120) if idx == 0 else (20, 200, 245),
        )
        has_jump, seam_mae, peak_mae = detect_seam_jump_cut(
            prior_end_b64, jump_cut_clip, 28.0, 5
        )
        assert has_jump is True
        assert peak_mae > 50.0
