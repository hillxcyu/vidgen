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
