from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class User(BaseModel):
    id: str
    name: str


class RegisterRequest(BaseModel):
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
