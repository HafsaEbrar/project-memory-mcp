"""chat/ai_service.py katmanı için unit testler.

Gerçek (ücretli) LLM API çağrısı YAPILMAZ. Provider parse katmanı
httpx.MockTransport ile sahte OpenAI-compatible yanıtlarla,
ChatAgent ise sahte provider + sahte memory client ile test edilir.
SQLite'a veya production MCP veritabanına hiç dokunulmaz.
"""

import asyncio
import json

import httpx
from mcp.types import Tool

from chat.ai_service import (
    AIServiceError,
    ChatAgent,
    LLMProviderError,
    LLMResponse,
    MaxToolCallLimitError,
    OpenAICompatibleProvider,
    ToolCall,
    ToolCallArgumentError,
    build_provider,
    mcp_tools_to_openai_tools,
    parse_tool_arguments,
)
from chat.config import load_settings
from chat.memory_client import ToolResult

# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------


def _text_response(content: str, finish_reason: str = "stop") -> dict:
    """
    Davranışına göre normal metin yanıtı üretir.
    """

    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
    }


def _tool_call_response(
    name: str,
    arguments: str,
    call_id: str,
    content: str | None = None,
    finish_reason: str = "tool_calls",
) -> dict:
    """
    Tek bir tool call içeren yanıt üretir.
    """

    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    ],
                },
                "finish_reason": finish_reason,
            }
        ],
    }


def _provider_with_handler(
    handler,
) -> OpenAICompatibleProvider:
    """
    Sahte yanıt handler'ı üzerinde çalışan gerçek provider kurar.

    httpx.MockTransport sayesinde hiçbir ağ isteği gitmez; provider'ın
    HTTP payload üretme ve yanıt parse davranışı birebir test edilir.
    """

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)

    return OpenAICompatibleProvider(
        api_key="test-api-key",
        model="test-model",
        base_url="https://api.example.com/v1",
        http_client=http_client,
    )


# İki gerçek MCP aracının şemasını yansıtan Tool nesneleri.
SEARCH_TOOL = Tool(
    name="search_memories",
    description="Hafızalarda SQLite FTS5 tabanlı indeksli arama yapar.",
    input_schema={
        "properties": {
            "terms": {"items": {"type": "string"}, "title": "Terms", "type": "array"},
            "category": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Category"},
            "limit": {"default": 5, "title": "Limit", "type": "integer"},
        },
        "required": ["terms"],
        "type": "object",
        "title": "search_memoriesArguments",
    },
)

REMEMBER_TOOL = Tool(
    name="remember",
    description="Aktif projeye önemli bir bilgiyi kalıcı olarak kaydeder.",
    input_schema={
        "properties": {
            "content": {"title": "Content", "type": "string"},
            "category": {"title": "Category", "type": "string"},
            "importance": {"default": 5, "title": "Importance", "type": "integer"},
        },
        "required": ["content", "category"],
        "type": "object",
        "title": "rememberArguments",
    },
)


# ----------------------------------------------------------------------
# Config testleri (senkron)
# ----------------------------------------------------------------------


def test_load_settings_environment() -> None:
    settings = load_settings(
        env={
            "LLM_PROVIDER": "openai_compatible",
            "LLM_API_KEY": "sk-test",
            "LLM_MODEL": "gpt-test-model",
            "LLM_BASE_URL": "https://api.example.com/v1",
            "LLM_MAX_TOOL_CALLS": "5",
        }
    )

    assert settings.provider == "openai_compatible"
    assert settings.api_key == "sk-test"
    assert settings.model == "gpt-test-model"
    assert settings.base_url == "https://api.example.com/v1"
    assert settings.max_tool_calls == 5


def test_load_settings_defaults() -> None:
    settings = load_settings(env={})

    assert settings.provider == "openai_compatible"
    assert settings.api_key is None
    assert settings.model == "gpt-4o-mini"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.max_tool_calls == 8


def test_load_settings_unsupported_provider() -> None:
    try:
        load_settings(env={"LLM_PROVIDER": "anthropic"})
        raise AssertionError("Desteklenmeyen sağlayıcı hata vermeliydi.")
    except ValueError as exc:
        assert "Desteklenmeyen" in str(exc)


def test_load_settings_invalid_max_tool_calls() -> None:
    try:
        load_settings(env={"LLM_MAX_TOOL_CALLS": "abc"})
        raise AssertionError("Boş olmayan tam sayı hata vermeliydi.")
    except ValueError as exc:
        assert "tam sayı" in str(exc)


def test_build_provider_requires_api_key() -> None:
    settings = load_settings(env={})

    try:
        build_provider(settings=settings)
        raise AssertionError("Anahtarsız sağlayıcı hata vermeliydi.")
    except AIServiceError as exc:
        assert "API anahtarı" in str(exc)


def test_build_provider_openai_compatible() -> None:
    settings = load_settings(
        env={
            "LLM_API_KEY": "sk-test",
            "LLM_BASE_URL": "https://api.example.com/v1",
        }
    )

    provider = build_provider(settings=settings)

    assert isinstance(provider, OpenAICompatibleProvider)


# ----------------------------------------------------------------------
# Schema dönüşümü ve arguments parse (senkron)
# ----------------------------------------------------------------------


def test_mcp_tools_to_openai_tools() -> None:
    converted = mcp_tools_to_openai_tools(
        [SEARCH_TOOL, REMEMBER_TOOL]
    )

    assert len(converted) == 2

    search_schema = converted[0]
    assert search_schema["type"] == "function"
    assert search_schema["function"]["name"] == "search_memories"
    assert (
        search_schema["function"]["description"]
        == SEARCH_TOOL.description
    )
    # Gerçek MCP input_schema birebir parameters olarak taşınır.
    assert (
        search_schema["function"]["parameters"]
        is SEARCH_TOOL.input_schema
    )

    remember_schema = converted[1]
    assert remember_schema["function"]["name"] == "remember"
    assert (
        "content"
        in remember_schema["function"]["parameters"]["required"]
    )
    assert (
        "category"
        in remember_schema["function"]["parameters"]["required"]
    )


def test_mcp_tools_to_openai_tools_empty() -> None:
    assert mcp_tools_to_openai_tools([]) == []


def test_parse_tool_arguments_valid() -> None:
    parsed = parse_tool_arguments(
        '{"terms": ["backend", "framework"], "limit": 5}'
    )

    assert parsed == {
        "terms": ["backend", "framework"],
        "limit": 5,
    }


def test_parse_tool_arguments_empty() -> None:
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments("   ") == {}
    assert parse_tool_arguments(None) == {}


def test_parse_tool_arguments_invalid_json() -> None:
    try:
        parse_tool_arguments('{"terms": ["backend"')
        raise AssertionError("Bozuk JSON hata vermeliydi.")
    except ToolCallArgumentError as exc:
        assert "parse edilemedi" in str(exc)


def test_parse_tool_arguments_non_object() -> None:
    try:
        parse_tool_arguments('"merhaba"')
        raise AssertionError("Sözlük olmayan arguments hata vermeliydi.")
    except ToolCallArgumentError as exc:
        assert "nesne" in str(exc)


# ----------------------------------------------------------------------
# Provider parse testleri (async, httpx.MockTransport)
# ----------------------------------------------------------------------


async def test_provider_normal_text_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_text_response("Merhaba!"))

    provider = _provider_with_handler(handler)

    response = await provider.chat(
        messages=[{"role": "user", "content": "merhaba"}],
        tools=mcp_tools_to_openai_tools([SEARCH_TOOL]),
        system_prompt="Test sistem promptu",
    )

    # A) Normal text response düzgün parse edilir.
    assert response.content == "Merhaba!"
    assert response.tool_calls == []
    assert response.finish_reason == "stop"

    # İstek gövdesi doğru kurulmuş olmalı.
    body_messages = captured["body"]["messages"]
    assert body_messages[0] == {
        "role": "system",
        "content": "Test sistem promptu",
    }
    assert body_messages[1] == {"role": "user", "content": "merhaba"}
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["tools"][0]["function"]["name"] == "search_memories"
    assert captured["auth"] == "Bearer test-api-key"

    await provider.aclose()


async def test_provider_search_tool_call_parse() -> None:
    arguments = json.dumps(
        {"terms": ["backend", "framework", "api"], "limit": 5}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_tool_call_response(
                name="search_memories",
                arguments=arguments,
                call_id="call_search_1",
            ),
        )

    provider = _provider_with_handler(handler)

    response = await provider.chat(
        messages=[{"role": "user", "content": "Backend framework neydi?"}],
        tools=mcp_tools_to_openai_tools([SEARCH_TOOL]),
    )

    # B) search_memories tool call parse edilir.
    assert response.content is None
    assert len(response.tool_calls) == 1

    tool_call = response.tool_calls[0]
    assert tool_call.id == "call_search_1"
    assert tool_call.name == "search_memories"
    assert tool_call.arguments == {
        "terms": ["backend", "framework", "api"],
        "limit": 5,
    }

    # F) raw_message assistant mesajını aynen taşır.
    assert response.raw_message["role"] == "assistant"
    assert (
        response.raw_message["tool_calls"][0]["function"]["name"]
        == "search_memories"
    )

    await provider.aclose()


async def test_provider_text_and_tool_call_together() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_tool_call_response(
                name="recall",
                arguments='{"query": "backend", "limit": 2}',
                call_id="call_recall_1",
                content="Araçlarımı kullanacağım.",
            ),
        )

    provider = _provider_with_handler(handler)

    response = await provider.chat(
        messages=[{"role": "user", "content": "neydi?"}],
    )

    # F) Metin ve tool call aynı yanıtta doğru temsil edilir.
    assert response.content == "Araçlarımı kullanacağım."
    assert response.tool_calls[0].name == "recall"
    assert response.tool_calls[0].arguments == {
        "query": "backend",
        "limit": 2,
    }

    await provider.aclose()


async def test_provider_broken_tool_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_tool_call_response(
                name="remember",
                arguments='{"content": "eksik',  # bozuk JSON
                call_id="call_bad_1",
            ),
        )

    provider = _provider_with_handler(handler)

    try:
        await provider.chat(
            messages=[{"role": "user", "content": "bunu hatırla"}],
        )
        raise AssertionError("Bozuk arguments hata vermeliydi.")
    except ToolCallArgumentError as exc:
        assert "parse edilemedi" in str(exc)

    await provider.aclose()


async def test_provider_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit")

    provider = _provider_with_handler(handler)

    try:
        await provider.chat(
            messages=[{"role": "user", "content": "test"}],
        )
        raise AssertionError("HTTP hata yanıtı LLMProviderError üretmeliydi.")
    except LLMProviderError as exc:
        assert "429" in str(exc)

    await provider.aclose()


# ----------------------------------------------------------------------
# ChatAgent (sahte provider + sahte memory client)
# ----------------------------------------------------------------------


class FakeMemoryClient:
    """
    tools ve call_tool arayüzünü sağlayan sahte memory client.
    Hiçbir MCP/SQLite bağlantısı kurmaz.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))

        if name == "search_memories":
            # Çağrı görevi boş döndürsün: arama sonucu yok.
            return ToolResult(data={"result": []}, is_error=False)

        if name == "remember":
            return ToolResult(
                data={
                    "id": 7,
                    "content": arguments.get("content"),
                    "category": arguments.get("category"),
                },
                is_error=False,
            )

        raise AssertionError(f"Beklenmeyen araç çağrısı: {name}")


class FakeProvider:
    """
    Hazır LLMResponse listesini sırayla döndüren sahte provider.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *, messages, tools=None, system_prompt=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "system_prompt": system_prompt,
            }
        )

        if not self._responses:
            raise AssertionError("Beklenmeyen ekstra LLM çağrısı.")

        return self._responses.pop(0)


async def test_chat_agent_memory_protocol_flow() -> None:
    """
    G) LLM -> search_memories -> boş sonuç -> remember -> final text
    akışı uçtan uca doğrulanır.
    """

    search_call = ToolCall(
        id="call_search",
        name="search_memories",
        arguments={
            "terms": ["backend", "framework", "api"],
            "category": "technology",
            "limit": 5,
        },
    )
    remember_call = ToolCall(
        id="call_remember",
        name="remember",
        arguments={
            "content": "Backend için FastAPI kullanılacak.",
            "category": "technology",
            "importance": 7,
        },
    )

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[search_call],
            finish_reason="tool_calls",
            raw_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_search",
                        "type": "function",
                        "function": {
                            "name": "search_memories",
                            "arguments": json.dumps(search_call.arguments),
                        },
                    }
                ],
            },
        ),
        LLMResponse(
            content=None,
            tool_calls=[remember_call],
            finish_reason="tool_calls",
            raw_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_remember",
                        "type": "function",
                        "function": {
                            "name": "remember",
                            "arguments": json.dumps(remember_call.arguments),
                        },
                    }
                ],
            },
        ),
        LLMResponse(
            content="Kaydettim: backend olarak FastAPI kullanılacak.",
            tool_calls=[],
            finish_reason="stop",
            raw_message={
                "role": "assistant",
                "content": "Kaydettim: backend olarak FastAPI kullanılacak.",
            },
        ),
    ]

    provider = FakeProvider(responses)
    memory_client = FakeMemoryClient([SEARCH_TOOL, REMEMBER_TOOL])

    agent = ChatAgent(
        provider=provider,
        memory_client=memory_client,
        system_prompt="Test memory quality promptu",
        max_tool_calls=5,
    )

    final = await agent.send(
        "Backend için FastAPI kullanacağız, bunu hatırla."
    )

    assert final.content == "Kaydettim: backend olarak FastAPI kullanılacak."
    assert final.tool_calls == []

    # LLM toplam 3 kez çağrıldı (2 tool turu + 1 final).
    assert len(provider.calls) == 3

    # Memory client, Memory Quality protokolüne uygun çağrıldı:
    # önce search_memories, sonra remember.
    assert memory_client.calls == [
        (
            "search_memories",
            {
                "terms": ["backend", "framework", "api"],
                "category": "technology",
                "limit": 5,
            },
        ),
        (
            "remember",
            {
                "content": "Backend için FastAPI kullanılacak.",
                "category": "technology",
                "importance": 7,
            },
        ),
    ]

    # Geçmiş: 1 user + 2 assistant(tool_call) + 2 tool + 1 assistant(final).
    role_counts: dict[str, int] = {}
    for message in agent.history:
        role_counts[message["role"]] = role_counts.get(message["role"], 0) + 1

    assert role_counts == {"user": 1, "assistant": 3, "tool": 2}

    # Aracın MCP şemaları OpenAI tool formatına dönüştürülüp iletilmiş.
    assert provider.calls[0]["tools"][0]["function"]["name"] == "search_memories"
    assert provider.calls[0]["system_prompt"] == "Test memory quality promptu"

    # Tool mesajları tool_call_id ile eşleşmeli.
    tool_ids = [
        message["tool_call_id"]
        for message in agent.history
        if message["role"] == "tool"
    ]
    assert tool_ids == ["call_search", "call_remember"]


class InfiniteToolLoopProvider:
    """
    Her çağrıda aynı tool call'ı döndürerek sonsuz döngüyü taklit eder.
    """

    async def chat(self, *, messages, tools=None, system_prompt=None):
        search_call = ToolCall(
            id="call_search",
            name="search_memories",
            arguments={"terms": ["x"]},
        )
        return LLMResponse(
            content=None,
            tool_calls=[search_call],
            finish_reason="tool_calls",
            raw_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_search",
                        "type": "function",
                        "function": {
                            "name": "search_memories",
                            "arguments": '{"terms": ["x"]}',
                        },
                    }
                ],
            },
        )


async def test_chat_agent_max_tool_calls_limit() -> None:
    """
    Maksimum tool loop sayısı sınırı: sonsuz döngü MaxToolCallLimitError
    üretmeli.
    """

    provider = InfiniteToolLoopProvider()
    memory_client = FakeMemoryClient([SEARCH_TOOL])

    agent = ChatAgent(
        provider=provider,
        memory_client=memory_client,
        max_tool_calls=2,
    )

    try:
        await agent.send("sonsuza kadar ara")
        raise AssertionError("Tool loop limiti aşılınca hata vermeliydi.")
    except MaxToolCallLimitError as exc:
        assert "limit" in str(exc).lower()

    # Sınır kadar araç çağrısı yapılmış olmalı.
    assert len(memory_client.calls) == 2


# ----------------------------------------------------------------------
# Çalıştırıcı
# ----------------------------------------------------------------------


def main() -> None:
    test_load_settings_environment()
    test_load_settings_defaults()
    test_load_settings_unsupported_provider()
    test_load_settings_invalid_max_tool_calls()
    test_build_provider_requires_api_key()
    test_build_provider_openai_compatible()

    test_mcp_tools_to_openai_tools()
    test_mcp_tools_to_openai_tools_empty()
    test_parse_tool_arguments_valid()
    test_parse_tool_arguments_empty()
    test_parse_tool_arguments_invalid_json()
    test_parse_tool_arguments_non_object()

    asyncio.run(_run_async_tests())

    print("Tüm chat ai_service testleri geçti.")


async def _run_async_tests() -> None:
    await test_provider_normal_text_response()
    await test_provider_search_tool_call_parse()
    await test_provider_text_and_tool_call_together()
    await test_provider_broken_tool_arguments()
    await test_provider_http_error()
    await test_chat_agent_memory_protocol_flow()
    await test_chat_agent_max_tool_calls_limit()


if __name__ == "__main__":
    main()