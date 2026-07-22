from __future__ import annotations

import os
import sys
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

from app_paths import get_app_base_dir, get_app_data_dir, unique_paths
from models import ModelConfig


DEFAULT_ENV_PATH = get_app_data_dir() / ".env"
ENV_FILENAMES = (".env", ".env.local", ".env.development", ".env.dev")


@dataclass(slots=True)
class NetworkResult:
    model: ModelConfig
    response_text: str
    status: str
    error_text: str | None = None
    raw_response: dict[str, Any] | None = None


def get_env_search_dirs() -> list[Path]:
    dirs = [
        Path.cwd(),
        get_app_data_dir(),
        get_app_base_dir(),
        get_app_base_dir().parent,
    ]
    try:
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            dirs.extend([exe_dir, exe_dir.parent])
    except Exception:
        pass
    return unique_paths(dirs)


def get_env_search_paths(env_path: str | Path | None = None) -> list[Path]:
    paths: list[Path] = []
    if env_path is not None:
        paths.append(Path(env_path))
    for directory in get_env_search_dirs():
        for filename in ENV_FILENAMES:
            paths.append(directory / filename)
    return unique_paths(paths)


def load_environment(env_path: str | Path = DEFAULT_ENV_PATH) -> list[Path]:
    loaded: list[Path] = []
    for candidate in get_env_search_paths(env_path):
        if not candidate.exists():
            continue

        if load_dotenv is not None:
            load_dotenv(candidate, override=False)
            loaded.append(candidate)
            continue

        for raw_line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        loaded.append(candidate)

    return loaded


class NetworkClient:
    def __init__(
        self, env_path: str | Path = DEFAULT_ENV_PATH, timeout: float = 60.0
    ) -> None:
        self.env_path = Path(env_path)
        self.timeout = timeout
        self.loaded_env_files = load_environment(self.env_path)

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

        api_key = self._resolve_api_key(model)
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
        headers = self._build_headers(model.api_url, api_key)

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
    def _build_headers(api_url: str, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in api_url:
            headers["HTTP-Referer"] = "https://github.com/ARB774/ChatList"
            headers["X-Title"] = "ChatList"
        return headers

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

    @staticmethod
    def _resolve_api_key(model: ModelConfig) -> str | None:
        direct_key = os.getenv(model.api_key_env)
        if direct_key:
            return direct_key

        aliases: list[str] = []
        normalized_name = model.name.lower()
        normalized_url = model.api_url.lower()

        if "openrouter" in normalized_name or "openrouter" in normalized_url:
            aliases.extend(["OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"])
        if "openai" in normalized_name or "openai.com" in normalized_url:
            aliases.append("OPENAI_API_KEY")
        if "deepseek" in normalized_name or "deepseek.com" in normalized_url:
            aliases.append("DEEPSEEK_API_KEY")
        if "groq" in normalized_name or "groq.com" in normalized_url:
            aliases.append("GROQ_API_KEY")
        if "huggingface" in normalized_name or "hugging face" in normalized_name:
            aliases.extend(
                [
                    "HUGGINGFACE_API_TOKEN",
                    "HUGGINGFACE_API_KEY",
                    "HF_TOKEN",
                    "HF_API_TOKEN",
                ]
            )
        if "huggingface.co" in normalized_url:
            aliases.extend(
                [
                    "HUGGINGFACE_API_TOKEN",
                    "HUGGINGFACE_API_KEY",
                    "HF_TOKEN",
                    "HF_API_TOKEN",
                ]
            )

        for alias in aliases:
            api_key = os.getenv(alias)
            if api_key:
                return api_key

        return None
