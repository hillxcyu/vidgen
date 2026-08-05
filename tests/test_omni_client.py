import base64
from unittest.mock import MagicMock
from src.tools.omni_client import generate_omni_clip

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
    assert call_args["input"][1]["text"] == "A panda skiing down a hill"

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
    assert call_args["input"][2]["text"] == "A panda riding a skateboard"
