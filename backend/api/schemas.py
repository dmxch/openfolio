"""Shared Pydantic models used across multiple API routers."""

from pydantic import BaseModel, Field


class RecalculateRequest(BaseModel):
    tickers: list[str] | None = None


class ValidateTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=500)
