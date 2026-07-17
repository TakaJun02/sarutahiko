from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.agent.campus_map import ORIGIN_SELECT_LABELS


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None
    origin_node: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message is required")
        return normalized

    @field_validator("origin_node")
    @classmethod
    def validate_origin_node(cls, value: str | None) -> str | None:
        if value is not None and value not in ORIGIN_SELECT_LABELS:
            raise ValueError("unknown campus map node")
        return value


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


class MapLocationPayload(BaseModel):
    node: str
    label: str
    room: str | None = None
    floor: int | None = None


class MapPathPayload(BaseModel):
    nodes: list[str]
    edges: list[str]


class MapPayload(BaseModel):
    mode: Literal["route", "place", "ask_origin"]
    origin: MapLocationPayload | None = None
    destination: MapLocationPayload | None = None
    path: MapPathPayload | None = None
    steps: list[str] | None = None
    prompt: str | None = None
    question: str | None = None


class DonePayload(BaseModel):
    thread_id: str
    message_id: str
    sources: list[Source]


class ErrorPayload(BaseModel):
    message: str
