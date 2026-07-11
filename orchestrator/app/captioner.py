import base64

CAPTION_PROMPT = (
    "Describe this lab-guide screenshot in 1-3 sentences for a learner who "
    "cannot see it: name the screen or portal blade, the highlighted/numbered "
    "UI elements, and where they are located on the screen."
)

class Captioner:
    def __init__(self, client, deployment: str):
        self.client = client
        self.deployment = deployment

    def caption(self, image_bytes: bytes, mime: str = "image/png") -> str:
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": CAPTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_completion_tokens=800,  # includes reasoning tokens on gpt-5.x
        )
        return resp.choices[0].message.content.strip()

def make_openai_client(settings):
    from openai import AzureOpenAI
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
