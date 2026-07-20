from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from db import Database


@dataclass(slots=True)
class ModelConfig:
    name: str
    api_url: str
    api_id: str
    api_key_env: str
    is_active: bool = True
    id: int | None = None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "ModelConfig":
        return cls(
            id=record.get("id"),
            name=str(record["name"]),
            api_url=str(record["api_url"]),
            api_id=str(record["api_id"]),
            api_key_env=str(record["api_key_env"]),
            is_active=bool(record["is_active"]),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "api_url": self.api_url,
            "api_id": self.api_id,
            "api_key_env": self.api_key_env,
            "is_active": int(self.is_active),
        }

    def build_messages(
        self, prompt: str, system_prompt: str | None = None
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def build_payload(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.api_id,
            "messages": self.build_messages(prompt, system_prompt),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return payload


DEFAULT_MODEL_CATALOG: tuple[ModelConfig, ...] = (
    ModelConfig(
        name="OpenRouter Auto",
        api_url="https://openrouter.ai/api/v1/chat/completions",
        api_id="openrouter/auto",
        api_key_env="OPENROUTER_API_KEY",
        is_active=True,
    ),
    ModelConfig(
        name="Hugging Face Chat",
        api_url="https://router.huggingface.co/v1/chat/completions",
        api_id="meta-llama/Llama-3.1-8B-Instruct",
        api_key_env="HUGGINGFACE_API_TOKEN",
        is_active=False,
    ),
    ModelConfig(
        name="OpenAI GPT-4o mini",
        api_url="https://api.openai.com/v1/chat/completions",
        api_id="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        is_active=False,
    ),
    ModelConfig(
        name="DeepSeek Chat",
        api_url="https://api.deepseek.com/chat/completions",
        api_id="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        is_active=False,
    ),
    ModelConfig(
        name="Groq Llama 3.1 8B",
        api_url="https://api.groq.com/openai/v1/chat/completions",
        api_id="llama-3.1-8b-instant",
        api_key_env="GROQ_API_KEY",
        is_active=False,
    ),
)


def load_model_environment(env_path: str | Path | None = None) -> None:
    root_dir = Path(__file__).parent
    candidate_files = (
        [Path(env_path)] if env_path is not None else []
    ) + [
        root_dir / ".env",
        root_dir / ".env.local",
        root_dir / ".env.development",
        root_dir / ".env.dev",
    ]

    seen_paths: set[Path] = set()
    for candidate_file in candidate_files:
        resolved_path = Path(candidate_file)
        if resolved_path in seen_paths or not resolved_path.exists():
            continue
        seen_paths.add(resolved_path)

        for raw_line in resolved_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def discover_env_variable_names(base_dir: str | Path | None = None) -> set[str]:
    root_dir = Path(base_dir or Path(__file__).parent)
    candidate_files = [
        root_dir / ".env",
        root_dir / ".env.local",
        root_dir / ".env.development",
        root_dir / ".env.dev",
    ]
    names = set(os.environ.keys())

    for candidate_file in candidate_files:
        if not candidate_file.exists():
            continue
        for raw_line in candidate_file.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _value = line.split("=", 1)
            names.add(key.strip())

    return names


def suggest_api_key_env_name(
    model: ModelConfig, available_names: Iterable[str]
) -> str | None:
    available_set = {name for name in available_names if name}
    if model.api_key_env in available_set:
        return model.api_key_env

    normalized_name = model.name.lower()
    normalized_url = model.api_url.lower()
    aliases: list[str] = []

    if "openrouter" in normalized_name or "openrouter" in normalized_url:
        aliases.extend(
            [
                "OPENROUTER_API_KEY",
                "OPEN_ROUTER_API_KEY",
                "OPENROUTER_KEY",
                "OPEN_ROUTER_KEY",
            ]
        )
    if "openai" in normalized_name or "openai.com" in normalized_url:
        aliases.extend(["OPENAI_API_KEY", "OPENAI_KEY"])
    if "deepseek" in normalized_name or "deepseek.com" in normalized_url:
        aliases.extend(["DEEPSEEK_API_KEY", "DEEPSEEK_KEY"])
    if "groq" in normalized_name or "groq.com" in normalized_url:
        aliases.extend(["GROQ_API_KEY", "GROQ_KEY"])
    if "hugging face" in normalized_name or "huggingface" in normalized_name:
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
        if alias in available_set:
            return alias

    for env_name in sorted(available_set):
        upper_name = env_name.upper()
        if "OPENROUTER" in normalized_name.upper() or "OPENROUTER" in normalized_url.upper():
            if (
                "OPENROUTER" in upper_name or "OPEN_ROUTER" in upper_name
            ) and ("KEY" in upper_name or "TOKEN" in upper_name):
                return env_name
        if "OPENAI" in normalized_name.upper() and "OPENAI" in upper_name and (
            "KEY" in upper_name or "TOKEN" in upper_name
        ):
            return env_name
        if "DEEPSEEK" in normalized_name.upper() and "DEEPSEEK" in upper_name and (
            "KEY" in upper_name or "TOKEN" in upper_name
        ):
            return env_name
        if "GROQ" in normalized_name.upper() and "GROQ" in upper_name and (
            "KEY" in upper_name or "TOKEN" in upper_name
        ):
            return env_name
        if (
            "HUGGINGFACE" in normalized_name.upper()
            or "HUGGING FACE" in normalized_name.upper()
            or "HUGGINGFACE.CO" in normalized_url.upper()
        ) and (
            "HUGGINGFACE" in upper_name or upper_name.startswith("HF_")
        ) and ("KEY" in upper_name or "TOKEN" in upper_name):
            return env_name

    return None


class ModelRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_models(
        self, active_only: bool | None = None, search: str | None = None
    ) -> list[ModelConfig]:
        records = self.database.list_models(active_only=active_only, search=search)
        return [ModelConfig.from_record(record) for record in records]

    def list_active_models(self) -> list[ModelConfig]:
        return self.list_models(active_only=True)

    def get_model(self, model_id: int) -> ModelConfig | None:
        record = self.database.get_model(model_id)
        if record is None:
            return None
        return ModelConfig.from_record(record)

    def add_model(self, model: ModelConfig) -> int:
        return self.database.create_model(
            name=model.name,
            api_url=model.api_url,
            api_id=model.api_id,
            api_key_env=model.api_key_env,
            is_active=model.is_active,
        )

    def update_model(self, model: ModelConfig) -> None:
        if model.id is None:
            raise ValueError("Model ID is required for update.")

        self.database.update_model(
            model.id,
            name=model.name,
            api_url=model.api_url,
            api_id=model.api_id,
            api_key_env=model.api_key_env,
            is_active=model.is_active,
        )

    def delete_model(self, model_id: int) -> None:
        self.database.delete_model(model_id)

    def seed_defaults(
        self, models: Iterable[ModelConfig] = DEFAULT_MODEL_CATALOG
    ) -> None:
        existing_names = {model.name for model in self.list_models()}
        for model in models:
            if model.name in existing_names:
                continue
            self.add_model(model)

    def activate_models_with_available_keys(self) -> None:
        load_model_environment()
        for model in self.list_models():
            if os.getenv(model.api_key_env):
                model.is_active = True
                self.update_model(model)

    def auto_configure_api_key_env_names(self) -> list[tuple[str, str, str]]:
        load_model_environment()
        available_names = discover_env_variable_names()
        changes: list[tuple[str, str, str]] = []

        for model in self.list_models():
            suggested_name = suggest_api_key_env_name(model, available_names)
            if suggested_name and suggested_name != model.api_key_env:
                old_name = model.api_key_env
                model.api_key_env = suggested_name
                self.update_model(model)
                changes.append((model.name, old_name, suggested_name))
        return changes
