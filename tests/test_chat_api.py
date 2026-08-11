"""FastAPI chat backend testleri; gerçek LLM veya MCP kullanmaz."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from mcp.types import Tool

from chat.ai_service import LLMProviderError, LLMResponse, ToolCall
from chat.config import Settings
from chat.main import create_app
from chat.memory_client import ProjectMemoryClientError


def _settings() -> Settings:
    return Settings(
        provider="openai_compatible",
        api_key="test-only-key",
        model="fake-model",
        base_url="https://example.invalid/v1",
        max_tool_calls=8,
        timeout_seconds=1.0,
    )


class FakeMemoryClient:
    def __init__(self) -> None:
        self.tools: list[Tool] = []
        self.connect_count = 0
        self.close_count = 0

    async def connect(self) -> None:
        self.connect_count += 1

    async def close(self) -> None:
        self.close_count += 1

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        return {"ok": True}


class FailingMemoryClient(FakeMemoryClient):
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        raise ProjectMemoryClientError("gizli MCP detayı")


class RecordingProvider:
    def __init__(self) -> None:
        self.histories: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self.histories.append([dict(message) for message in messages])
        text = f"Yanıt: {messages[-1]['content']}"
        return LLMResponse(
            content=text,
            raw_message={"role": "assistant", "content": text},
        )


class FailingProvider(RecordingProvider):
    async def chat(self, **kwargs: Any) -> LLMResponse:
        raise LLMProviderError("gizli provider detayı")


class ToolCallingProvider(RecordingProvider):
    async def chat(self, **kwargs: Any) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="search_memories",
                    arguments={"terms": ["test"]},
                )
            ],
        )


def _build_client(provider: RecordingProvider):
    memory_client = FakeMemoryClient()
    app = create_app(
        settings_loader=_settings,
        memory_client_factory=lambda: memory_client,
        provider_factory=lambda settings: provider,
    )
    return TestClient(app, raise_server_exceptions=False), app, memory_client


def _build_client_with_memory(
    provider: RecordingProvider,
    memory_client: FakeMemoryClient,
):
    app = create_app(
        settings_loader=_settings,
        memory_client_factory=lambda: memory_client,
        provider_factory=lambda settings: provider,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_health() -> None:
    client, _, memory_client = _build_client(RecordingProvider())
    with client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert memory_client.connect_count == 1
    assert memory_client.close_count == 1


def test_chat_creates_session_and_preserves_history() -> None:
    provider = RecordingProvider()
    client, _, _ = _build_client(provider)

    with client:
        first = client.post("/api/chat", json={"message": "Merhaba"})
        assert first.status_code == 200
        assert first.json()["response"]
        session_id = first.json()["session_id"]
        assert session_id

        second = client.post(
            "/api/chat",
            json={"message": "Nasılsın?", "session_id": session_id},
        )
        assert second.status_code == 200
        assert provider.histories[1] == [
            {"role": "user", "content": "Merhaba"},
            {"role": "assistant", "content": "Yanıt: Merhaba"},
            {"role": "user", "content": "Nasılsın?"},
        ]


def test_blank_message_returns_422() -> None:
    client, _, _ = _build_client(RecordingProvider())
    with client:
        response = client.post("/api/chat", json={"message": "   "})
        assert response.status_code == 422


def test_provider_error_returns_502_without_details() -> None:
    client, _, _ = _build_client(FailingProvider())
    with client:
        response = client.post("/api/chat", json={"message": "Merhaba"})
        assert response.status_code == 502
        assert "gizli" not in response.text


def test_memory_error_returns_503_without_details() -> None:
    client = _build_client_with_memory(
        ToolCallingProvider(),
        FailingMemoryClient(),
    )
    with client:
        response = client.post("/api/chat", json={"message": "Merhaba"})
        assert response.status_code == 503
        assert "gizli" not in response.text


def test_delete_session_removes_history() -> None:
    client, app, _ = _build_client(RecordingProvider())
    with client:
        created = client.post("/api/chat", json={"message": "Merhaba"})
        session_id = created.json()["session_id"]
        assert app.state.session_store.get_messages(session_id)

        deleted = client.delete(f"/api/sessions/{session_id}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True, "session_id": session_id}
        assert app.state.session_store.get_messages(session_id) == []


def main() -> None:
    test_health()
    test_chat_creates_session_and_preserves_history()
    test_blank_message_returns_422()
    test_provider_error_returns_502_without_details()
    test_memory_error_returns_503_without_details()
    test_delete_session_removes_history()
    print("Tüm chat API testleri geçti.")


if __name__ == "__main__":
    main()
