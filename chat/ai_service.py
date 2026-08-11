"""Provider-bağımsız LLM hizmet katmanı.

Normal chat backend'i LLM'i tek bir sağlayıcıya sıkı bağlamaz. Bu
modülde ortak bir ``LLMProvider`` arayüzü ve MVP sağlayıcısı olan
``OpenAICompatibleProvider`` bulunur. Sağlayıcı, OpenAI-compatible
chat completions API'sini httpx ile çağırır; ek SDK bağımlılığı
kullanılmaz.

Ayrıca:

- MCP ``list_tools`` sonucu OpenAI function tool formatına dönüştürülür.
- Modelin ürettiği tool call'lar güvenli biçimde parse edilir.
- ``ChatAgent``, LLM + ProjectMemory MCP araç döngüsünü yürütür.

Kullanım:

    settings = load_settings()
    provider = build_provider(settings)
    response = await provider.chat(
        messages=[{"role": "user", "content": "..."}],
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )

``ChatAgent`` döngüsü:

    LLM -> tool_calls? -> evet -> ilgili MCP aracını çağır
    -> araç sonucu LLM'e geri ver -> LLM -> final text
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx
from mcp.types import Tool

from chat.config import Settings, load_settings
from chat.prompts import SYSTEM_PROMPT, build_tool_message


class AIServiceError(Exception):
    """
    AI servis katmanındaki temel hata.
    """


class LLMProviderError(AIServiceError):
    """
    LLM sağlayıcı isteği veya yanıtıyla ilgili hatalar.
    """


class ToolCallArgumentError(AIServiceError, ValueError):
    """
    Bir tool call'un arguments alanı JSON olarak
    güvenli biçimde parse edilemediğinde oluşur.
    """


class MaxToolCallLimitError(AIServiceError):
    """
    Tek mesaj için izin verilen maksimum araç çağrısı
    sayısı aşıldığında oluşur. Sonsuz döngüyü engeller.
    """


@dataclass
class ToolCall:
    """
    Modelin ürettiği tek bir tool call.

    arguments her zaman dict'tir; hatalı JSON zaten
    ``ToolCallArgumentError`` ile parse sırasında yakalanır.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """
    LLM sağlayıcısından dönen normalize edilmiş yanıt.

    content:
        Final metin yanıtı. Tool call üretildiyse None olabilir.

    tool_calls:
        Modelin ürettiği tool call listesi.

    finish_reason:
        Sağlayıcının finish_reason değeri (ör. stop, tool_calls).

    raw_message:
        Sağlayıcı yanıtındaki ham assistant mesajı. ChatAgent,
        mesaj geçmişine eklemek ve tool_call_id eşleştirmek için
        bunu aynen kullanır.
    """

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    raw_message: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """
    Her LLM sağlayıcının uyguladığı ortak arayüz.

    messages:
        OpenAI-compatible mesaj listesi (role/content üçlüsü).

    tools:
        OpenAI function tool formatında araç şemaları.

    system_prompt:
        Sistem promptu. Verilirse sağlayıcı mesajların başına
        bir system mesajı olarak ekler.
    """

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse: ...


@runtime_checkable
class MemoryToolClient(Protocol):
    """
    ChatAgent'ın kullandığı araç arayüzü.

    Gerçek ProjectMemoryClient bu arayüzle uyumludur; testlerde
    sahte bir nesne verilebilir.
    """

    tools: list[Tool]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any: ...


# ----------------------------------------------------------------------
# Tool arguments ve yanıt parse
# ----------------------------------------------------------------------


def parse_tool_arguments(raw: str) -> dict[str, Any]:
    """
    Tool call arguments alanını güvenli biçimde JSON olarak parse eder.

    Boş veya None girdi boş sözlük olarak döner. Geçersiz JSON veya
    sözlük olmayan değerler anlaşılır ``ToolCallArgumentError`` üretir.
    """

    if raw is None:
        return {}

    raw = raw.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolCallArgumentError(
            f"Tool arguments JSON olarak parse edilemedi: {raw!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ToolCallArgumentError(
            "Tool arguments bir nesne (JSON object) olmalıdır. "
            f"Alınan: {type(parsed).__name__}"
        )

    return parsed


def _parse_message_text(message: dict[str, Any]) -> str | None:
    """
    Assistant mesajındaki content değerini güvenli biçimde döndürür.
    """

    content = message.get("content")

    if isinstance(content, str):
        return content

    # Bazı sağlayıcılar content yerine bölümlü listeler dönebilir.
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))
        return "".join(text_parts) or None

    return None


def _parse_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    """
    Assistant mesajındaki tool_calls alanını ToolCall listesine çevirir.
    """

    tool_calls: list[ToolCall] = []

    for raw_call in message.get("tool_calls") or []:
        if not isinstance(raw_call, dict):
            raise LLMProviderError(
                "Tool call bir nesne olmalıdır."
            )

        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise LLMProviderError(
                "Tool call function alanı eksik."
            )

        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise LLMProviderError(
                "Tool call fonksiyon adı boş olamaz."
            )

        tool_calls.append(
            ToolCall(
                id=str(raw_call.get("id") or ""),
                name=name.strip(),
                arguments=parse_tool_arguments(function.get("arguments")),
            )
        )

    return tool_calls


def _parse_chat_response(data: dict[str, Any]) -> LLMResponse:
    """
    OpenAI-compatible chat completions yanıtını LLMResponse'a çevirir.
    """

    try:
        choices = data["choices"]
        choice = choices[0]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError(
            "LLM yanıtı geçerli 'choices' alanı içermiyor."
        ) from exc

    if not isinstance(choice, dict):
        raise LLMProviderError(
            "LLM yanıtındaki choise bir nesne olmalıdır."
        )

    message = choice.get("message")
    if not isinstance(message, dict):
        raise LLMProviderError(
            "LLM yanıtı 'message' alanı içermiyor."
        )

    return LLMResponse(
        content=_parse_message_text(message),
        tool_calls=_parse_tool_calls(message),
        finish_reason=choice.get("finish_reason"),
        raw_message=message,
    )


# ----------------------------------------------------------------------
# MCP tool şeması -> OpenAI function tool formatı
# ----------------------------------------------------------------------


def mcp_tools_to_openai_tools(
    tools: list[Tool],
) -> list[dict[str, Any]]:
    """
    MCP ``list_tools`` sonucunu OpenAI-compatible function tool
    formatına dönüştürür.

    Beklenen çıktı biçimi (her araç için):

        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": {...gerçek MCP input_schema...}
            }
        }

    Araç içeriği yeniden implement edilmez; yalnızca MCP'nin ürettiği
    `input_schema` olduğu gibi parameters olarak taşınır.
    """

    converted: list[dict[str, Any]] = []

    for tool in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.title or "",
                    "parameters": tool.input_schema
                    or {"type": "object", "properties": {}},
                },
            }
        )

    return converted


# ----------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------


class OpenAICompatibleProvider:
    """
    OpenAI-compatible chat completions API'sini httpx ile çağıran
    MVP sağlayıcısı.

    Aynı arayüz; base_url ve model değiştirilerek OpenAI, GitHub Models,
    Ollama, OpenRouter gibi sağlayıcılara bağlanabilir.

    http_client verilirse sağlayıcı onu KAPATMAZ (sahibi çağırandır);
    bu, testlerin httpx.MockTransport enjekte etmesine izin verir.
    Verilmezse sağlayıcı kendi istemcisini ilk çağrıda oluşturur ve
    ``aclose()`` ile kapatabilirsiniz.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise AIServiceError(
                "LLM API anahtarı verilmedi. "
                "LLM_API_KEY ortam değişkenini veya api_key parametresini ayarlayın."
            )

        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = http_client

    async def aclose(self) -> None:
        """
        Sağlayıcının oluşturduğu HTTP istemcisini kapatır.
        """

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds)
            )

        request_messages: list[dict[str, Any]] = []

        if system_prompt:
            request_messages.append(
                {"role": "system", "content": system_prompt}
            )

        request_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": request_messages,
        }

        # OpenAI API boş tools listesini reddeder;
        # yalnızca gerçek araç varsa eklenir.
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                "LLM isteği zaman aşımına uğradı."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                f"LLM isteği iletilemedi: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise LLMProviderError(
                "LLM sağlayıcı hata döndürdü "
                f"({response.status_code}): {response.text[:500]}"
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                "LLM yanıtı geçerli JSON değil."
            ) from exc

        if not isinstance(data, dict):
            raise LLMProviderError(
                "LLM yanıtı bir JSON nesnesi olmalıdır."
            )

        return _parse_chat_response(data)


# ----------------------------------------------------------------------
# Sağlayıcı fabrikası
# ----------------------------------------------------------------------


def build_provider(
    *,
    settings: Settings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> LLMProvider:
    """
    Yapılandırmaya göre uygun LLM sağlayıcısını kurar.

    MVP'de tek sağlayıcı (openai_compatible) vardır; yeni sağlayıcılar
    buraya eklenir. http_client verilirse sağlayıcıya enjekte edilir.
    """

    settings = settings if settings is not None else load_settings()

    if settings.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            http_client=http_client,
        )

    raise AIServiceError(
        f"Desteklenmeyen LLM sağlayıcı: {settings.provider!r}"
    )


# ----------------------------------------------------------------------
# ChatAgent
# ----------------------------------------------------------------------


def _assistant_message_from(response: LLMResponse) -> dict[str, Any]:
    """
    Ham assistant mesajı olmadığında LLMResponse'tan OpenAI-compatible
    assistant mesajı kurar.
    """

    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content,
    }

    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(
                        tool_call.arguments,
                        ensure_ascii=False,
                    ),
                },
            }
            for tool_call in response.tool_calls
        ]

    return message


def _serialize_tool_result(tool_result: Any) -> str:
    """
    Bir MCP araç sonucunu LLM mesajı için JSON metnine çevirir.
    """

    data = getattr(tool_result, "data", tool_result)

    if isinstance(data, str):
        return data

    return json.dumps(data, ensure_ascii=False, default=str)


class ChatAgent:
    """
    LLM + ProjectMemory MCP araçlarını birleştiren küçük orchestrator.

    Akış:

        kullanıcı mesajı -> LLM
        LLM tool_calls üretti mi?
            evet -> her call'ı memory_client.call_tool ile çalıştır
                    -> araç sonucu LLM'e "tool" mesajı olarak geri ver
                    -> LLM
            hayır -> final text döndür

    Maksimum araç çağrısı sayısı ``max_tool_calls`` ile sınırlıdır;
    sınır aşılırsa ``MaxToolCallLimitError`` yükseltilir (sonsuz döngü
    oluşmaz).

    memory_client, ``MemoryToolClient`` arayüzüne uyan herhangi bir
    nesne olabilir; bu sayede testlerde sahte nesne kullanılabilir.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        memory_client: MemoryToolClient,
        system_prompt: str | None = None,
        max_tool_calls: int = 8,
        tools: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        if max_tool_calls < 1:
            raise AIServiceError(
                "max_tool_calls en az 1 olmalıdır."
            )

        self._provider = provider
        self._memory_client = memory_client
        self._system_prompt = system_prompt or SYSTEM_PROMPT
        self._max_tool_calls = int(max_tool_calls)

        if tools is not None:
            self._tools = list(tools)
        else:
            self._tools = mcp_tools_to_openai_tools(memory_client.tools)

        # Oturum geçmişi (user/assistant dönüşleri) ile başlatılabilir;
        # verilmezse boş geçmişle olur (geriye uyumlu davranış).
        self._history: list[dict[str, Any]] = (
            [dict(message) for message in history]
            if history
            else []
        )

    @property
    def history(self) -> list[dict[str, Any]]:
        """
        Şimdiye kadar birikmiş OpenAI-compatible mesaj geçmişi.
        """

        return list(self._history)

    def clear_history(self) -> None:
        """
        Mesaj geçmişini temizler.
        """

        self._history = []

    async def send(self, user_message: str) -> LLMResponse:
        """
        Bir kullanıcı mesajını işler ve final LLMResponse döndürür.

        Kullanıcı mesajı geçmişe eklenir; gerektiğinde MCP araçları
        çağrılır ve en son geçmişteki bağlama göre model final yanıtı
        üretir.
        """

        self._history.append(
            {"role": "user", "content": user_message}
        )

        return await self._run()

    async def _run(self) -> LLMResponse:
        """
        Tool loop'unu yürütür.

        Her döngüde LLM çağrılır. Tool call üretilmediyse bu, final
        yanıttır ve geri döner. Üretildiyse araçlar çalıştırılır ve
        sonuçlar mesaj geçmişine eklenir.
        """

        for _ in range(self._max_tool_calls):
            response = await self._provider.chat(
                messages=self._history,
                tools=self._tools,
                system_prompt=self._system_prompt,
            )

            if not response.tool_calls:
                assistant_message = (
                    response.raw_message
                    if response.raw_message is not None
                    else _assistant_message_from(response)
                )
                self._history.append(assistant_message)
                return response

            assistant_message = (
                response.raw_message
                if response.raw_message is not None
                else _assistant_message_from(response)
            )
            self._history.append(assistant_message)

            for tool_call in response.tool_calls:
                tool_result = await self._memory_client.call_tool(
                    tool_call.name,
                    tool_call.arguments,
                )

                self._history.append(
                    build_tool_message(
                        tool_call.id,
                        _serialize_tool_result(tool_result),
                    )
                )

        raise MaxToolCallLimitError(
            "Maksimum araç çağrısı limiti aşıldı "
            f"({self._max_tool_calls}). Sonsuz döngü engellendi."
        )
