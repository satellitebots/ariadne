"""Generator: call the local OpenAI-compatible completion endpoint."""

import requests


class Generator:
    """Wrapper around the local completion model (OpenAI-compatible API)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8090/v1",
                 model: str = "qwen3.6-35b-a3b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(self, messages: list[dict],
                 temperature: float = 0.3) -> str:
        """Generate a completion from a list of chat messages.

        Parameters
        ----------
        messages: list of {"role": "user"/"system"/"assistant", "content": str}
        temperature: sampling temperature (0.0 = deterministic).

        Returns
        -------
        The assistant's response text.
        """
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 1024,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
