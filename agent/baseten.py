"""Baseten adapter for Meta Muse Spark Open hackathon access."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict

from .providers import Provider, ProviderDecision, ProviderError, ToolCall

DEFAULT_BASE_URL = "https://inference.baseten.co/v1/chat/completions"
DEFAULT_MODEL = "meta-models/muse-spark-open-1026"

SYSTEM_PROMPT = """You are the reasoning engine inside Hack the World, an evidence-driven
technology troubleshooting agent.

You do NOT give a one-shot diagnosis. You operate through the available diagnostic tools.

Rules:
1. Call exactly one tool each turn.
2. Maintain multiple plausible causes until evidence distinguishes them.
3. Never invent an observation or test result. If evidence is missing, request it.
4. After new evidence arrives, reassess existing hypotheses before asking unnecessary tests.
5. Prefer safe, high-information, low-effort diagnostic tests.
6. Only submit a recommendation when a hypothesis is supported or confirmed by cited evidence.
7. Use the exact hypothesis and evidence IDs present in the session.
8. Keep user-facing requested tests short and practical.
9. Do not claim certainty that the recorded evidence does not support.
"""


class BasetenMuseProvider(Provider):
    """Use the hackathon Muse Spark Open endpoint as the agent decision maker."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        image_data_url: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = 90,
    ):
        self._api_key = api_key or os.environ.get("BASETEN_API_KEY")
        if not self._api_key:
            raise ProviderError("BASETEN_API_KEY is not set")
        self._image_data_url = image_data_url
        self._base_url = base_url
        self._model = model
        self._timeout = timeout

    def decide(self, request):
        tools = [
            {"type": "function", "function": tool}
            for tool in request.tools
        ]

        state_json = json.dumps(asdict(request.session), indent=2, default=str)
        feedback_json = json.dumps(
            [asdict(item) for item in request.feedback],
            indent=2,
            default=str,
        )

        instruction = (
            "Choose the single best next diagnostic action.\n\n"
            f"Problem:\n{request.problem}\n\n"
            f"Authoritative session state:\n{state_json}\n\n"
            f"Recent execution feedback:\n{feedback_json}\n\n"
            f"Remaining provider steps: {request.remaining_provider_steps}\n"
        )

        user_content = [{"type": "text", "text": instruction}]
        if self._image_data_url:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": self._image_data_url,
                        "detail": "auto",
                    },
                }
            )

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "tools": tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "temperature": 0.2,
            "max_tokens": 1200,
        }

        http_request = urllib.request.Request(
            self._base_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Baseten HTTP {exc.code}: {detail[:600]}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Baseten connection error: {exc.reason}") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Baseten response error: {exc}") from exc

        try:
            message = body["choices"][0]["message"]
            raw_calls = message.get("tool_calls") or []
            calls = []
            for call in raw_calls:
                function = call["function"]
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                calls.append(ToolCall(function["name"], arguments))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                "Muse Spark Open returned an unusable tool-call response"
            ) from exc

        return ProviderDecision(tuple(calls))
