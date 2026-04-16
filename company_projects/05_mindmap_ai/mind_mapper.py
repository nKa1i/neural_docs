from openai import OpenAI
class MindMapper:
    MODEL = "gpt-4o"  # conflicts with concept_notes [7] which says Mistral 7B local
    MAX_TOKENS = 2048

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def generate_map(self, text: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.MODEL,
            messages=[{"role": "user", "content": f"Build a mind map JSON from: {text}"}],
            max_tokens=self.MAX_TOKENS,
        )
        return {"raw": resp.choices[0].message.content}
