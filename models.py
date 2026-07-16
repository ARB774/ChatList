from __future__ import annotations

from dataclasses import dataclass
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


class ModelRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_models(self, active_only: bool | None = None) -> list[ModelConfig]:
        records = self.database.list_models(active_only=active_only)
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

    def seed_defaults(self, models: Iterable[ModelConfig] = DEFAULT_MODEL_CATALOG) -> None:
        existing_names = {model.name for model in self.list_models()}
        for model in models:
            if model.name in existing_names:
                continue
            self.add_model(model)
