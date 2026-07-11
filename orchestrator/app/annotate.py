import base64
import io
import json
import re

LOCATE_PROMPT = (
    "Locate this UI element in the screenshot: {target}\n"
    'Reply with ONLY JSON: {{"found": true|false, "box": [x0, y0, x1, y1]}} '
    "where box is the element's bounding rectangle in pixel coordinates of "
    "this image. If the element is not visible, use found=false and box=null."
)

JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

def locate_element(client, deployment: str, image_bytes: bytes, target: str,
                   mime: str = "image/png") -> list[int] | None:
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    resp = client.chat.completions.create(
        model=deployment,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": LOCATE_PROMPT.format(target=target)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        max_completion_tokens=600,  # includes reasoning tokens on gpt-5.x
    )
    m = JSON_RE.search(resp.choices[0].message.content)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    box = data.get("box")
    if not data.get("found") or not isinstance(box, list) or len(box) != 4:
        return None
    return [int(v) for v in box]

def draw_box(image_bytes: bytes, box: list[int]) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    ImageDraw.Draw(img).rectangle(box, outline=(255, 59, 48), width=4)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
