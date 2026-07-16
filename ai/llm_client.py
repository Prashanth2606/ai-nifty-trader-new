from anthropic import Anthropic
from config import CLAUDE_API_KEY


class LLMClient:

    def __init__(self):

        self.client = Anthropic(
            api_key=CLAUDE_API_KEY
        )

    def get_trade_recommendation(self, prompt):

        response = self.client.messages.create(
            model="claude-sonnet-5",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        for block in response.content:
            if block.type == "text":
                return block.text

        # No text block at all (e.g. the response was entirely reasoning/thinking
        # content, or got cut off before any text was written) - surface this as
        # an explicit error rather than silently returning "", so the caller's
        # error handling reports the real cause instead of a generic parse failure.
        block_types = [getattr(b, "type", "unknown") for b in response.content]
        raise RuntimeError(
            f"Claude response had no text content "
            f"(stop_reason={response.stop_reason}, block_types={block_types})"
        )