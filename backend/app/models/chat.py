from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized


class ThreadRenameRequest(BaseModel):
    title: str


class Source(BaseModel):
    title: str
    url: str
    type: Literal["knowledge", "web"]


class StatusPayload(BaseModel):
    step: Literal["analyze", "retrieve", "search", "web_search", "evaluate", "generate"]
    text: str


class TokenPayload(BaseModel):
    text: str


class DonePayload(BaseModel):
    thread_id: str
    message_id: str
    sources: list[Source]


class ErrorPayload(BaseModel):
    message: str
