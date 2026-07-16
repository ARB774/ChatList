from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
    from requests import RequestException
except ImportError:  # pragma: no cover - handled at runtime if dependency is missing.
    requests = None

    class RequestException(Exception):
        pass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - manual fallback is used.
    load_dotenv = None

from models import ModelConfig


DEFAULT_ENV_PATH = Path(__file__).with_name(".env")


@dataclass(slots=True)
class NetworkResult:
    model: ModelConfig
    response_text: str
    status: str
    error_text: str | None = None
    raw_response: dict[str, Any] | None = None


def load_environment(env_path: str | Path = DEFAULT_ENV_PATH) -> None:
    resolved_path = Path(env_path)
    if not resolved_path.exists():
        return

    if load_dotenv is not None:
        load_dotenv(resolved_path, override=False)
        return

    for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class NetworkClient:
    def __init__(
        self, env_path: str | Path = DEFAULT_ENV_PATH, timeout: float = 60.0
    ) -> None:
        self.env_path = Path(env_path)
        self.timeout = timeout
        load_environment(self.env_path)

    def send_prompt(
        self,
        model: ModelConfig,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> NetworkResult:
        if requests is None:
            return NetworkResult(
                model=model,
                response_text="",
                status="dependency_error",
                error_text="The 'requests' package is not installed.",
            )

        api_key = os.getenv(model.api_key_env)
        if not api_key:
            return NetworkResult(
                model=model,
                response_text="",
                status="missing_api_key",
                error_text=(
                    f"Environment variable '{model.api_key_env}' was not found."
                ),
            )

        payload = model.build_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        headers = self._build_headers(api_key)

        try:
            response = requests.post(
                model.api_url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except RequestException as exc:
            return NetworkResult(
                model=model,
                response_text="",
                status="network_error",
                error_text=str(exc),
            )

        try:
            data = response.json()
        except ValueError:
            data = None

        if not response.ok:
            error_text = self._extract_error_text(data) or response.text
            return NetworkResult(
                model=model,
                response_text="",
                status=f"http_{response.status_code}",
                error_text=error_text,
                raw_response=data if isinstance(data, dict) else None,
            )

        if not isinstance(data, dict):
            return NetworkResult(
                model=model,
                response_text="",
                status="invalid_response",
                error_text="The API response is not valid JSON.",
            )

        response_text = self._extract_response_text(data)
        if response_text is None:
            return NetworkResult(
                model=model,
                response_text="",
                status="invalid_response",
                error_text="Could not extract text from the API response.",
                raw_response=data,
            )

        return NetworkResult(
            model=model,
            response_text=response_text,
            status="success",
            raw_response=data,
        )

    def send_prompt_to_models(
        self,
        models: Iterable[ModelConfig],
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> list[NetworkResult]:
        return [
            self.send_prompt(
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
            )
            for model in models
        ]

    @staticmethod
    def _build_headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_error_text(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None

        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        if isinstance(error, str):
            return error
        return None

    @staticmethod
    def _extract_response_text(data: dict[str, Any]) -> str | None:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content.strip()
                    if isinstance(content, list):
                        parts: list[str] = []
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            text = item.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                        if parts:
                            return "\n".join(parts).strip()

                text = first_choice.get("text")
                if isinstance(text, str):
                    return text.strip()

        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text.strip()

        response_text = data.get("response")
        if isinstance(response_text, str):
            return response_text.strip()

        return None
