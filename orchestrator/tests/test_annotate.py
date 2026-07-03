import io

from PIL import Image

from app.annotate import draw_box, locate_element

def _tiny_png(size=(20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()

class FakeClient:
    def __init__(self, reply: str):
        self.reply = reply
        outer = self
        class Completions:
            def create(self, **kwargs):
                outer.last_kwargs = kwargs
                class Msg: content = outer.reply
                class Choice: message = Msg()
                class Resp: choices = [Choice()]
                return Resp()
        self.chat = type("C", (), {"completions": Completions()})()

def test_locate_element_parses_box():
    client = FakeClient('Sure! {"found": true, "box": [2, 3, 10, 12]}')
    box = locate_element(client, "gpt", _tiny_png(), "the save button")
    assert box == [2, 3, 10, 12]
    # vision call carries the image and the target description
    content = client.last_kwargs["messages"][0]["content"]
    assert any(p.get("type") == "image_url" for p in content)
    assert "the save button" in next(p["text"] for p in content if p.get("type") == "text")

def test_locate_element_not_found_returns_none():
    client = FakeClient('{"found": false, "box": null}')
    assert locate_element(client, "gpt", _tiny_png(), "x") is None

def test_locate_element_garbage_reply_returns_none():
    client = FakeClient("I cannot see anything useful here.")
    assert locate_element(client, "gpt", _tiny_png(), "x") is None

def test_draw_box_paints_red_rectangle():
    out = draw_box(_tiny_png(), [4, 4, 15, 15])
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG"
    assert img.convert("RGB").getpixel((4, 4)) == (255, 59, 48)   # on the outline
    assert img.convert("RGB").getpixel((0, 0)) == (255, 255, 255)  # untouched corner
