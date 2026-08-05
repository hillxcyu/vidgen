import base64
from unittest.mock import MagicMock
from src.tools.omni_client import generate_omni_clip, build_omni_control_string

def test_build_omni_control_string_i2v():
    ctrl_str = build_omni_control_string(
        prompt="A panda skiing down a hill",
        input_image_b64="fake_b64_image_data",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10
    )
    assert ctrl_str == "[# Sources <FIRST_FRAME>image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=10s] A panda skiing down a hill"

def test_build_omni_control_string_reference_mode():
    ctrl_str = build_omni_control_string(
        prompt="A panda riding a skateboard",
        reference_images_b64=["ref1_b64", "ref2_b64"],
        aspect_ratio="9:16",
        resolution="1080p",
        duration=5
    )
    assert ctrl_str == "[# References <IMAGE_REF_0>[Character A]image_0.png <IMAGE_REF_1>[Character A]image_1.png] [aspect_ratio=9:16] [resolution=1080p] [duration=5s] A panda riding a skateboard"

def test_build_omni_control_string_voice_transcript():
    ctrl_str = build_omni_control_string(
        prompt="A character speaking on stage",
        reference_images_b64=["ref1_b64"],
        voice_transcript="Hello world, welcome to GenMedia!",
        aspect_ratio="16:9",
        resolution="720p",
        duration=10
    )
    assert "[# References <IMAGE_REF_0>[Character A]image_0.png]" in ctrl_str
    assert "Character A speaks dialogue: \"Hello world, welcome to GenMedia!\"" in ctrl_str

def test_generate_omni_clip_i2v_mode():
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    fake_mp4_bytes = b"fake_mp4_video_data"
    mock_interaction.output_video.data = base64.b64encode(fake_mp4_bytes).decode("utf-8")
    mock_client.interactions.create.return_value = mock_interaction

    result = generate_omni_clip(
        prompt="A panda skiing down a hill",
        input_image_b64="fake_b64_image_data",
        client=mock_client
    )

    assert result == fake_mp4_bytes
    mock_client.interactions.create.assert_called_once()
    call_args = mock_client.interactions.create.call_args[1]
    assert call_args["model"] == "gemini-omni-flash-preview"
    assert len(call_args["input"]) == 2
    assert call_args["input"][0]["type"] == "image"
    assert call_args["input"][1]["type"] == "text"
    assert call_args["input"][1]["text"] == "[# Sources <FIRST_FRAME>image_0.png] [aspect_ratio=16:9] [resolution=720p] [duration=10s] A panda skiing down a hill"

def test_generate_omni_clip_reference_mode():
    mock_client = MagicMock()
    mock_interaction = MagicMock()
    fake_mp4_bytes = b"fake_mp4_reference_video"
    mock_interaction.output_video.data = base64.b64encode(fake_mp4_bytes).decode("utf-8")
    mock_client.interactions.create.return_value = mock_interaction

    result = generate_omni_clip(
        prompt="A panda riding a skateboard",
        reference_images_b64=["ref1_b64", "ref2_b64"],
        client=mock_client
    )

    assert result == fake_mp4_bytes
    call_args = mock_client.interactions.create.call_args[1]
    assert len(call_args["input"]) == 3
    assert call_args["input"][0]["type"] == "image"
    assert call_args["input"][1]["type"] == "image"
    assert call_args["input"][2]["type"] == "text"
    assert call_args["input"][2]["text"] == "[# References <IMAGE_REF_0>[Character A]image_0.png <IMAGE_REF_1>[Character A]image_1.png] [aspect_ratio=16:9] [resolution=720p] [duration=10s] A panda riding a skateboard"
