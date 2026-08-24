from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class StructuredLLMClient(Protocol):
    """A chat model that returns output validated against a pydantic schema."""

    async def parse(self, *, system: str, user_content: str, output_model: type[BaseModel]) -> BaseModel: ...
