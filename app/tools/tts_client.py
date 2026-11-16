# Copyright 2026 Author:Hill YU(xcyu@)
"""Direct Gemini 3.8 TTS synthesis and RIFF WAV chunking utilities for Hosted ADK 2.0 Studio.

Synthesizes 24 kHz mono PCM/RIFF WAV speech via Vertex AI `gemini-3.8-flash-tts`
(accepting `gemini-3.8-tts` / `gemini-3.8-lite-tts` aliases) and slices WAV tracks into
<= 3.0s RIFF WAV chunks for Gemini Omni Reference-to-Video (`tpvg_tts`) conditioning.
"""

import base64
import io
import os
from typing import Any, Dict, List, Optional, Tuple
import wave

from google import genai
from google.genai import types

from app.config import Config, get_genai_client

TTS_MODEL_ALIASES: Dict[str, str] = {
    "gemini-3.8-tts": "gemini-3.8-flash-tts",
    "gemini-3.8-flash-tts": "gemini-3.8-flash-tts",
    "gemini-3.8-lite-tts": "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-lite-tts": "gemini-3.8-flash-lite-tts",
}


def normalize_tts_model_name(model_name: Optional[str] = None) -> str:
    """Normalizes friendly Gemini 3.8 TTS aliases to official Vertex AI model IDs."""
    raw = str(model_name or getattr(Config, "TTS_MODEL", "gemini-3.8-flash-tts") or "gemini-3.8-flash-tts").strip()
    return TTS_MODEL_ALIASES.get(raw.lower(), raw)


def ensure_riff_wav_bytes(
    audio_bytes: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sampwidth: int = 2,
) -> bytes:
    """Wraps raw 24 kHz L16 PCM bytes in a RIFF/WAVE header if not already RIFF WAV."""
    if not audio_bytes:
        raise ValueError("Cannot wrap empty audio bytes into RIFF WAV.")
    raw = bytes(audio_bytes)
    if raw.startswith(b"RIFF") and b"WAVE" in raw[:16]:
        return raw
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(max(1, int(channels)))
        wf.setsampwidth(max(1, int(sampwidth)))
        wf.setframerate(max(8000, int(sample_rate)))
        wf.writeframes(raw)
    return buf.getvalue()


def split_wav_reference_chunks(
    wav_bytes: bytes,
    chunk_sec: float = 3.0,
    max_chunks: int = 5,
    min_tail_sec: float = 0.35,
) -> List[str]:
    """Slices a WAV track into up to `max_chunks` base64-encoded RIFF WAV chunks (`<= chunk_sec`)."""
    riff = ensure_riff_wav_bytes(wav_bytes)
    with wave.open(io.BytesIO(riff), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate() or 24000
        total_frames = wf.getnframes()
        all_pcm = wf.readframes(total_frames)

    bytes_per_frame = max(1, nchannels * sampwidth)
    frames_per_chunk = max(1, int(round(max(0.5, float(chunk_sec)) * framerate)))
    min_tail_frames = max(1, int(round(max(0.05, float(min_tail_sec)) * framerate)))

    chunks_b64: List[str] = []
    offset_frames = 0
    while offset_frames < total_frames and len(chunks_b64) < max(1, int(max_chunks)):
        end_frames = min(total_frames, offset_frames + frames_per_chunk)
        seg_frames = end_frames - offset_frames
        if seg_frames < min_tail_frames and chunks_b64:
            break
        seg_pcm = all_pcm[offset_frames * bytes_per_frame : end_frames * bytes_per_frame]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out_wf:
            out_wf.setnchannels(nchannels)
            out_wf.setsampwidth(sampwidth)
            out_wf.setframerate(framerate)
            out_wf.writeframes(seg_pcm)
        chunks_b64.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        offset_frames = end_frames
    return chunks_b64


def synthesize_tts_wav(
    text: str,
    voice_name: str = "Kore",
    language_code: str = "en-US",
    style: str = "",
    model_name: Optional[str] = None,
    client: Optional[genai.Client] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Synthesizes a 24 kHz mono RIFF WAV voice track via Vertex AI `gemini-3.8-flash-tts`."""
    clean_text = (text or "").strip()
    if not clean_text:
        raise ValueError("Cannot synthesize empty TTS text.")
    resolved_model = normalize_tts_model_name(model_name)
    resolved_voice = (voice_name or "Kore").strip() or "Kore"
    clean_style = (style or "").strip()

    active_client = client or get_genai_client(timeout_ms=Config.RATER_TIMEOUT_MS)
    speech_cfg = types.SpeechConfig(
        language_code=language_code or "en-US",
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=resolved_voice)
        ),
    )
    gen_cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_cfg,
    )
    contents: Any = clean_text
    if clean_style:
        contents = [{"role": "user", "parts": [{"text": clean_text, "speechMetadata": {"style": clean_style}}]}]

    try:
        resp = active_client.models.generate_content(
            model=resolved_model,
            contents=contents,
            config=gen_cfg,
        )
    except Exception as err:
        if clean_style and ("speechMetadata" in str(err) or "validation" in str(err).lower()):
            resp = active_client.models.generate_content(
                model=resolved_model,
                contents=clean_text,
                config=gen_cfg,
            )
        else:
            raise

    raw_audio: Optional[bytes] = None
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            raw_data = getattr(inline, "data", None) if inline is not None else None
            if raw_data:
                raw_audio = base64.b64decode(raw_data) if isinstance(raw_data, str) else bytes(raw_data)
                break
        if raw_audio:
            break

    if not raw_audio:
        raise RuntimeError(f"Gemini TTS ({resolved_model}) returned no inline audio bytes.")

    wav_bytes = ensure_riff_wav_bytes(raw_audio, sample_rate=24000, channels=1, sampwidth=2)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or 24000
        dur_sec = round(frames / float(rate), 3) if rate > 0 else 0.0

    return wav_bytes, {
        "model": resolved_model,
        "voice": resolved_voice,
        "language_code": language_code or "en-US",
        "duration_sec": dur_sec,
        "sample_rate_hz": int(rate),
        "bytes": len(wav_bytes),
    }
