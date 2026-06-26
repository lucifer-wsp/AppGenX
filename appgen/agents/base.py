from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TypeVar

from appgen.constants import LLM_PROFILE_DEFAULT, LLMProfileKind
from appgen.llm import LLMClient
from appgen.models import PipelineRun, PipelineStage
from appgen.storage import ArtifactStore

T = TypeVar("T")


class BaseAgent(ABC):
    stage: PipelineStage
    name: str
    description: str

    def __init__(self, llm: LLMClient, store: ArtifactStore) -> None:
        self.llm = llm
        self.store = store

    async def llm_chat_json(
        self,
        system: str,
        user: str,
        model_type: type[T],
        *,
        temperature: float = 0.3,
        on_progress: Callable[[str, int], None] | None = None,
        profile: LLMProfileKind = LLM_PROFILE_DEFAULT,
    ) -> T:
        """在线程池中调用 LLM，避免阻塞 FastAPI 事件循环。"""
        return await asyncio.to_thread(
            self.llm.chat_json,
            system,
            user,
            model_type,
            temperature=temperature,
            on_progress=on_progress,
            profile=profile,
        )

    @abstractmethod
    async def run(self, run: PipelineRun) -> PipelineRun:
        ...
