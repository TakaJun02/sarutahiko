from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["highschool", "parent", "other"]


class User(BaseModel):
    id: str
    name: str
    role: Role


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    role: Role

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != value:
            raise ValueError("name must not contain leading or trailing whitespace")
        if not normalized:
            raise ValueError("name is required")
        return normalized


class LoginRequest(BaseModel):
    name: str = Field(min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != value:
            raise ValueError("name must not contain leading or trailing whitespace")
        if not normalized:
            raise ValueError("name is required")
        return normalized


class AuthResponse(BaseModel):
    token: str
    user: User


class MeResponse(BaseModel):
    user: User
