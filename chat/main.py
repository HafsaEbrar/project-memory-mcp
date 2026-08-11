"""ProjectMemory normal chat FastAPI backend'i.

Kalıcı hafıza erişimi yalnızca ChatAgent ve ProjectMemoryClient üzerinden
MCP araçlarıyla yapılır. SessionStore ise process ömrüyle sınırlı, geçici
sohbet geçmişini tutar.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from chat.ai_service import ChatAgent, LLMProvider, LLMProviderError, build_provider
from chat.config import Settings, load_settings
from chat.memory_client import ProjectMemoryClient, ProjectMemoryClientError
from chat.session_store import SessionStore

logger = logging.getLogger(__name__)

SettingsLoader = Callable[[], Settings]
MemoryClientFactory = Callable[[], ProjectMemoryClient]
ProviderFactory = Callable[[Settings], LLMProvider]


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str
    session_id: str | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("message boş olamaz")
        return value

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        return value or None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class HealthResponse(BaseModel):
    status: str


class DeleteSessionResponse(BaseModel):
    deleted: bool
    session_id: str


def _default_provider_factory(settings: Settings) -> LLMProvider:
    return build_provider(settings=settings)


def create_app(
    *,
    settings_loader: SettingsLoader = load_settings,
    memory_client_factory: MemoryClientFactory = ProjectMemoryClient,
    provider_factory: ProviderFactory = _default_provider_factory,
) -> FastAPI:
    """Uygulamayı oluşturur; fabrikalar testlerde güvenle değiştirilebilir."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = settings_loader()
        memory_client = memory_client_factory()

        await memory_client.connect()
        try:
            application.state.settings = settings
            application.state.memory_client = memory_client
            application.state.provider = provider_factory(settings)
            application.state.session_store = SessionStore()
            yield
        finally:
            provider = getattr(application.state, "provider", None)
            close_provider = getattr(provider, "aclose", None)
            if callable(close_provider):
                await close_provider()
            await memory_client.close()

    application = FastAPI(title="ProjectMemory Chat API", lifespan=lifespan)

    @application.exception_handler(LLMProviderError)
    async def handle_provider_error(
        request: Request,
        exc: LLMProviderError,
    ) -> JSONResponse:
        logger.warning("LLM provider isteği başarısız oldu.")
        return JSONResponse(
            status_code=502,
            content={"detail": "LLM sağlayıcısına erişilemedi."},
        )

    @application.exception_handler(ProjectMemoryClientError)
    async def handle_memory_client_error(
        request: Request,
        exc: ProjectMemoryClientError,
    ) -> JSONResponse:
        logger.warning("ProjectMemory MCP isteği başarısız oldu.")
        return JSONResponse(
            status_code=503,
            content={"detail": "ProjectMemory MCP servisine erişilemedi."},
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Chat API beklenmeyen bir hata üretti.")
        return JSONResponse(
            status_code=500,
            content={"detail": "Beklenmeyen bir sunucu hatası oluştu."},
        )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        store: SessionStore = request.app.state.session_store

        session_id = payload.session_id
        if session_id is None:
            session_id = store.create_session()
        elif not store.has_session(session_id):
            raise HTTPException(status_code=404, detail="Oturum bulunamadı.")

        agent = ChatAgent(
            provider=request.app.state.provider,
            memory_client=request.app.state.memory_client,
            max_tool_calls=request.app.state.settings.max_tool_calls,
            history=store.get_messages(session_id),
        )
        result = await agent.send(payload.message)

        if not result.content or not result.content.strip():
            raise LLMProviderError("LLM boş final yanıt döndürdü.")

        response_text = result.content.strip()
        store.add_message(session_id, "user", payload.message)
        store.add_message(session_id, "assistant", response_text)

        return ChatResponse(response=response_text, session_id=session_id)

    @application.delete(
        "/api/sessions/{session_id}",
        response_model=DeleteSessionResponse,
    )
    async def delete_session(
        session_id: str,
        request: Request,
    ) -> DeleteSessionResponse:
        store: SessionStore = request.app.state.session_store
        if not store.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Oturum bulunamadı.")

        return DeleteSessionResponse(deleted=True, session_id=session_id)

    return application


app = create_app()
