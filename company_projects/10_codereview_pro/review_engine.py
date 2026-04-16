from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage

class ReviewEngine:
    MODEL = "gpt-4o"
    MAX_DIFF_LINES = 500

    def __init__(self, api_key: str):
        self.llm = ChatOpenAI(model=self.MODEL, openai_api_key=api_key)

    def review_diff(self, diff: str) -> str:
        if len(diff.splitlines()) > self.MAX_DIFF_LINES:
            diff = "\n".join(diff.splitlines()[:self.MAX_DIFF_LINES])
        msg = HumanMessage(content=f"Review this code diff:\n{diff}")
        return self.llm([msg]).content
