import base64
from app.captioner import Captioner

class FakeCompletions:
    def __init__(self):
        self.last_kwargs = None
    def create(self, **kwargs):
        self.last_kwargs = kwargs
        class Msg: content = "Azure portal search bar with AI Search typed."
        class Choice: message = Msg()
        class Resp: choices = [Choice()]
        return Resp()

class FakeClient:
    def __init__(self):
        self.chat = type("C", (), {"completions": FakeCompletions()})()

def test_caption_sends_data_url_and_returns_text():
    client = FakeClient()
    cap = Captioner(client, "gpt-4o")
    out = cap.caption(b"\x89PNG fake", mime="image/png")
    assert out == "Azure portal search bar with AI Search typed."
    kwargs = client.chat.completions.create.__self__.last_kwargs
    assert kwargs["model"] == "gpt-4o"
    image_part = kwargs["messages"][0]["content"][1]
    assert image_part["type"] == "image_url"
    expected_b64 = base64.b64encode(b"\x89PNG fake").decode()
    assert image_part["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"
