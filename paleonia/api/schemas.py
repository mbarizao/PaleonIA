from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PartIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    text: str = ""
    confirmed: bool = False
    skipped: bool = False


class LineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    box: list[float]
    include: bool = True
    parts: list[PartIn] = Field(default_factory=list)


class LinesBody(BaseModel):
    lines: list[LineIn]
    sensitivity: float | None = None


class DetectBody(BaseModel):
    sensitivity: float | None = None


class TranscribeBody(BaseModel):
    only_empty: bool = True


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""
