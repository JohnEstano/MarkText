"""Request and response shapes for the MarkText API."""

from typing import Any, Literal

from pydantic import BaseModel, Field

Mode = Literal["normal", "watermarked"]
Source = Literal["manual", "file", "batch", "legacy"]


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    max_new_tokens: int = Field(default=300, ge=50, le=2000)
    mode: Mode = "watermarked"
    seed: int | None = None


class SaveRequest(BaseModel):
    generation: dict[str, Any]          # the dict returned by /generate


class DetectRequest(BaseModel):
    text: str = Field(min_length=1)
    filename: str = ""
    source: Source = "manual"
    extra: dict[str, Any] = Field(default_factory=dict)


class RecordUpdate(BaseModel):
    note: str | None = None
    filename: str | None = None


class ExperimentRequest(BaseModel):
    n_prompts: int = Field(default=100, ge=1, le=1000)
    lengths: list[int] = Field(default_factory=lambda: [150])
    runs: int = Field(default=1, ge=1, le=5)
    seed_base: int = Field(default=100, ge=0)
    resume: str | None = None
    modes: list[Mode] = Field(default_factory=lambda: ["normal", "watermarked"])
