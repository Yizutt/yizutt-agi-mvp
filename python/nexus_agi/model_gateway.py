import json
import os
import urllib.error
import urllib.request


class ModelGateway:
    def __init__(self) -> None:
        self.openai_model = os.getenv("NEXUS_OPENAI_MODEL", "gpt-5.4-mini")
        self.anthropic_model = os.getenv("NEXUS_ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        self.openai_base_url = os.getenv("NEXUS_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_api_style = os.getenv("NEXUS_OPENAI_API_STYLE") or (
            "responses" if self.openai_base_url == "https://api.openai.com/v1" else "chat"
        )
        self.local_url = os.getenv("NEXUS_LOCAL_MODEL_URL", "")

    def choose(self, task: str, preferred: str | None = None) -> str:
        if preferred:
            if preferred == "openai" and not self._openai_api_key():
                raise RuntimeError("OPENAI_API_KEY is not set")
            if preferred == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            if preferred == "local" and not self.local_url:
                raise RuntimeError("NEXUS_LOCAL_MODEL_URL is not set")
            return preferred
        text = task.lower()
        if self.local_url and ("local" in text or "offline" in text):
            return "local"
        if "long" in text or "analysis" in text or "architect" in text:
            if os.getenv("ANTHROPIC_API_KEY"):
                return "anthropic"
            if self._openai_api_key():
                return "openai"
        if self._openai_api_key():
            return "openai"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if self.local_url:
            return "local"
        raise RuntimeError("No model provider configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or NEXUS_LOCAL_MODEL_URL.")

    def complete(self, prompt: str, provider: str | None = None, system: str = "You are Nexus AGI.") -> str:
        selected = self.choose(prompt, provider)
        if selected == "openai":
            return self._openai(prompt, system)
        if selected == "anthropic":
            return self._anthropic(prompt, system)
        if selected == "local":
            return self._local(prompt, system)
        raise RuntimeError(f"unknown provider {selected}")

    def _openai(self, prompt: str, system: str) -> str:
        api_key = self._openai_api_key()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        if self.openai_api_style == "chat":
            return self._openai_chat(prompt, system, api_key)
        payload = {
            "model": self.openai_model,
            "instructions": system,
            "input": prompt,
            "store": False,
        }
        data = self._post_json(f"{self.openai_base_url}/responses", payload, {
            "Authorization": f"Bearer {api_key}",
        })
        return self._extract_openai_text(data)

    def _openai_chat(self, prompt: str, system: str, api_key: str) -> str:
        payload = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        data = self._post_json(f"{self.openai_base_url}/chat/completions", payload, {
            "Authorization": f"Bearer {api_key}",
        })
        return self._extract_chat_text(data)

    def _anthropic(self, prompt: str, system: str) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        payload = {
            "model": self.anthropic_model,
            "system": system,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = self._post_json("https://api.anthropic.com/v1/messages", payload, {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })
        return "".join(block.get("text", "") for block in data.get("content", []))

    def _local(self, prompt: str, system: str) -> str:
        if not self.local_url:
            raise RuntimeError("NEXUS_LOCAL_MODEL_URL is not set")
        data = self._post_json(self.local_url, {"system": system, "prompt": prompt}, {})
        return data.get("text") or data.get("response") or json.dumps(data, ensure_ascii=False)

    def _openai_api_key(self) -> str:
        if os.getenv("OPENAI_API_KEY"):
            return os.environ["OPENAI_API_KEY"]
        if self.openai_base_url != "https://api.openai.com/v1" and os.getenv("PROXY_API_KEY"):
            return os.environ["PROXY_API_KEY"]
        return ""

    @staticmethod
    def _post_json(url: str, payload: dict, headers: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            **headers,
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Provider HTTP {exc.code}: {detail}") from exc

    @staticmethod
    def _extract_openai_text(data: dict) -> str:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        chunks: list[str] = []
        for item in data.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        if chunks:
            return "".join(chunks)
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _extract_chat_text(data: dict) -> str:
        chunks: list[str] = []
        for choice in data.get("choices", []):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message", {})
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                chunks.append(message["content"])
            elif isinstance(choice.get("text"), str):
                chunks.append(choice["text"])
        if chunks:
            return "".join(chunks)
        return json.dumps(data, ensure_ascii=False)
