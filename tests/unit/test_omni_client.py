from unittest.mock import MagicMock
from app.tools.omni_client import generate_omni_clip, build_omni_control_string


def test_build_omni_control_string_i2v():
    ctrl = build_omni_control_string(
        prompt="A red panda jumps onto a snowbank",
        input_image_b64="fake_base64_png",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10
    )
    assert "# Sources <FIRST_FRAME>image_0.png" in ctrl
    assert "[aspect_ratio=16:9]" in ctrl
    assert "[resolution=720p]" in ctrl
    assert "[duration=10s]" in ctrl
    assert "A red panda jumps onto a snowbank" in ctrl


def test_build_omni_control_string_dual_anchor():
    ctrl = build_omni_control_string(
        prompt="A red panda adjusts goggles between shots",
        input_image_b64="fake_first_frame",
        end_image_b64="fake_last_frame",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10
    )
    assert "# Sources <FIRST_FRAME>image_0.png <LAST_FRAME>image_1.png" in ctrl
    assert "[aspect_ratio=16:9]" in ctrl
    assert "A red panda adjusts goggles between shots" in ctrl


def test_build_omni_control_string_reference():
    ctrl = build_omni_control_string(
        prompt="skis down the mountain",
        reference_images_b64=["fake_ref_1", "fake_ref_2"],
        aspect_ratio="16:9",
        resolution="720p",
        duration=10
    )
    assert "# References <IMAGE_REF_0>[Character A]image_0.png <IMAGE_REF_1>[no_character]image_1.png" in ctrl
    assert "Character A, skis down the mountain" in ctrl


def test_build_omni_control_string_first_frame_precedence_over_reference():
    ctrl = build_omni_control_string(
        prompt="The runner accelerates across the bridge",
        input_image_b64="extracted_last_frame_b64",
        reference_images_b64=["original_studio_anchor_b64"],
        aspect_ratio="16:9",
        resolution="720p",
        duration=10
    )
    assert "# Sources <FIRST_FRAME>image_0.png" in ctrl
    assert "# References" not in ctrl
    assert "<IMAGE_REF_0>" not in ctrl
    assert "Character A" not in ctrl



def test_generate_omni_clip_mock_client():
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = b"fake_mp4_bytes"
    mock_client.interactions.create.return_value = mock_interaction

    clip_bytes = generate_omni_clip(
        prompt="Red panda skiing",
        client=mock_client
    )
    assert clip_bytes == b"fake_mp4_bytes"
    assert mock_client.interactions.create.called


def test_build_omni_control_string_video_extend():
    ctrl = build_omni_control_string(
        prompt="Character A sprints across the wet asphalt track",
        input_video_b64="fake_tail_video_b64",
        task="extend",
        reference_images_b64=["studio_white_anchor_b64"],
        voice_transcript="Built for race day speed.",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10,
    )
    assert "# Sources <VIDEO_0>video_0.mp4" in ctrl
    assert "# References" not in ctrl
    assert "[aspect_ratio=" not in ctrl
    assert "[resolution=720p]" in ctrl
    assert "[duration=10s]" in ctrl
    assert "Extend this video:" in ctrl
    assert "Character A" not in ctrl
    assert "Built for race day speed." in ctrl


def test_generate_omni_clip_video_extend_fallback():
    import base64 as _b64

    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = None
    mock_interaction.outputs = None
    mock_interaction.output_video = {
        "type": "video",
        "mime_type": "video/mp4",
        "data": _b64.b64encode(b"extended_mp4_bytes").decode("utf-8"),
    }
    mock_client.interactions.create.side_effect = [
        RuntimeError("404 Publisher model macaron-cookie not_found"),
        mock_interaction,
    ]

    clip_bytes = generate_omni_clip(
        prompt="Continue walking forward",
        input_video_b64="fake_tail_b64",
        task="extend",
        client=mock_client,
    )
    assert clip_bytes == b"extended_mp4_bytes"
    assert mock_client.interactions.create.call_count == 2
    first_call_kwargs = mock_client.interactions.create.call_args_list[0].kwargs
    second_call_kwargs = mock_client.interactions.create.call_args_list[1].kwargs
    assert first_call_kwargs["generation_config"] == {"video_config": {"task": "extend"}}
    assert first_call_kwargs["response_format"] == {"type": "video"}
    assert second_call_kwargs["model"] != first_call_kwargs["model"]


def test_split_voice_transcript_across_shots():
    from app.agents.pipeline import split_voice_transcript_across_shots

    parts = split_voice_transcript_across_shots(
        "Engineered for cold mornings. Responsive cushion on wet pavement. Finish strong in the city.",
        3,
    )
    assert len(parts) == 3
    assert parts[0] == "Engineered for cold mornings."
    assert parts[1] == "Responsive cushion on wet pavement."
    assert parts[2] == "Finish strong in the city."


def test_generate_omni_clip_speech_edit_fallback():
    import base64 as _b64

    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = None
    mock_interaction.outputs = None
    mock_interaction.output_video = {
        "type": "video",
        "mime_type": "video/mp4",
        "data": _b64.b64encode(b"speech_safe_extended_mp4").decode("utf-8"),
    }
    mock_client.interactions.create.side_effect = [
        RuntimeError("400 The model is currently unable to process speech edits."),
        mock_interaction,
    ]

    clip_bytes = generate_omni_clip(
        prompt="Continue walking forward",
        input_video_b64=_b64.b64encode(b"not_a_real_mp4_so_returns_orig").decode("utf-8"),
        task="extend",
        voice_transcript="Warm in winter wind.",
        model_override="gemini-omni-flash-preview",
        client=mock_client,
    )
    assert clip_bytes == b"speech_safe_extended_mp4"
    assert mock_client.interactions.create.call_count == 2


def test_generate_omni_clip_r2v_uses_native_task_parameter():
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = b"r2v_scene_mp4_bytes"
    mock_client.interactions.create.return_value = mock_interaction

    clip_bytes = generate_omni_clip(
        prompt="walks out of a warm urban boutique cafe onto a misty winter sidewalk",
        reference_images_b64=["studio_white_anchor_b64"],
        voice_transcript="Engineered for the city street.",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10,
        client=mock_client,
    )
    assert clip_bytes == b"r2v_scene_mp4_bytes"
    call_kwargs = mock_client.interactions.create.call_args.kwargs
    assert call_kwargs["generation_config"] == {
        "video_config": {"task": "reference_to_video"}
    }
    assert call_kwargs["response_format"] == {
        "type": "video",
        "aspect_ratio": "16:9",
        "duration": "10s",
        "resolution": "720p",
    }
    sent_text = call_kwargs["input"][0]["text"]
    assert "Character A" in sent_text
    assert "Engineered for the city street." in sent_text
    assert "<FIRST_FRAME>" not in sent_text
    assert "# References" not in sent_text
    assert "[aspect_ratio=" not in sent_text


def test_generate_omni_clip_i2v_shot2_omits_r2v_task_and_refs():
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = b"i2v_shot2_mp4_bytes"
    mock_client.interactions.create.return_value = mock_interaction

    clip_bytes = generate_omni_clip(
        prompt="Continuing seamlessly, the model stands inside an ascending mountain gondola",
        input_image_b64="shot1_last_frame_b64",
        reference_images_b64=["studio_white_anchor_b64"],
        aspect_ratio="16:9",
        resolution="720p",
        duration=10,
        client=mock_client,
    )
    assert clip_bytes == b"i2v_shot2_mp4_bytes"
    call_kwargs = mock_client.interactions.create.call_args.kwargs
    assert "generation_config" not in call_kwargs
    sent_text = call_kwargs["input"][0]["text"]
    assert "# Sources <FIRST_FRAME>image_0.png" in sent_text
    assert "# References" not in sent_text


def test_generate_omni_clip_extend_shot2_omits_ref_images_and_sets_extend_task():
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output = b"extend_shot2_mp4_bytes"
    mock_client.interactions.create.return_value = mock_interaction

    clip_bytes = generate_omni_clip(
        prompt="Continue walking forward smoothly inside the boutique cafe",
        input_video_b64="shot1_tail_5s_b64",
        task="extend",
        reference_images_b64=["studio_white_anchor_b64"],
        model_override="gemini-omni-flash-preview",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10,
        client=mock_client,
    )
    assert clip_bytes == b"extend_shot2_mp4_bytes"
    call_kwargs = mock_client.interactions.create.call_args.kwargs
    assert call_kwargs["generation_config"] == {"video_config": {"task": "extend"}}
    assert len(call_kwargs["input"]) == 2
    assert [p["type"] for p in call_kwargs["input"]] == ["text", "video"]
    sent_text = call_kwargs["input"][0]["text"]
    assert "# Sources <VIDEO_0>video_0.mp4" in sent_text
    assert "# References" not in sent_text

