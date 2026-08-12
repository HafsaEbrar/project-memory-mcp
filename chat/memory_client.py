"""ProjectMemory MCP sunucusuna stdio üzerinden bağlanan istemci.

Normal web chat backend'i, hafıza işlemlerini doğrudan SQLite üzerinden
yapmaz. Bu sınıf, mevcut ``server.py`` MCP sunucusunu bir alt süreç
olarak başlatır ve tüm hafıza işlemlerini MCP araçları üzerinden
gerçekleştirir.

Kullanım:

    client = ProjectMemoryClient()
    await client.connect()

    result = await client.remember(...)
    result = await client.search_memories(terms=[...])

    await client.close()

``server.py`` hiçbir şekilde değiştirilmez; tamamen yeniden kullanılır.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool

logger = logging.getLogger(__name__)

# Bu dosyanın bulunduğu klasör:
# project-memory-mcp/chat/
CHAT_DIR = Path(__file__).resolve().parent

# Projenin ana klasörü:
# project-memory-mcp/
PROJECT_ROOT = CHAT_DIR.parent

# Ortam değişkeni adları.
# MCP subprocess'e aktarılacak aktif proje klasörü.
PROJECT_ROOT_ENV = "PROJECT_MEMORY_ROOT"

# MCP sunucusunu başlatacak Python yorumlayıcısı.
PYTHON_EXECUTABLE_ENV = "MCP_PYTHON"

# Başlatılacak MCP sunucusu dosyasının yolu.
SERVER_PATH_ENV = "MCP_SERVER_PATH"


class ProjectMemoryClientError(RuntimeError):
    """
    ProjectMemoryClient bağlantısı veya araç çağrısı
    sırasında oluşan hatalar.
    """


@dataclass
class ToolResult:
    """
    Bir MCP araç çağrısının normalize edilmiş sonucu.

    data:
        Aracın döndürdüğü yapılandırılmış değer (dict, list, str...).

    is_error:
        Sunucu aracın hata döndürdüğünü bildirdiyse True.

    raw:
        Doğrudan MCP SDK'dan gelen CallToolResult nesnesi.
        Gerekirse ham erişim için saklanır.
    """

    data: Any
    is_error: bool = False
    raw: CallToolResult | None = None


class ProjectMemoryClient(AbstractAsyncContextManager["ProjectMemoryClient"]):
    """
    Mevcut ProjectMemory MCP sunucusunu (server.py) stdio üzerinden
    başlatan ve hafıza araçlarını çağıran uzun yaşayan istemci.

    Lifecycle:

        client = ProjectMemoryClient(...)
        await client.connect()
        await client.call_tool(...)   # birden fazla
        await client.close()

    ``connect()`` yalnızca bir kez çağrılır; sonraki ``call_tool``
    çağrıları aynı subprocess/session üzerinden gider. Her mesajda
    sunucuyu yeniden başlatmaz.

    Proje yolları hard-code edilmez:

        project_root:
            PROJECT_MEMORY_ROOT ortam değişkeni, verilmezse repository root.

        python_executable:
            MCP_PYTHON ortam değişkeni, verilmezse sys.executable.

        server_path:
            MCP_SERVER_PATH ortam değişkeni, verilmezse
            PROJECT_ROOT/server.py.
    """

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        python_executable: str | Path | None = None,
        server_path: str | Path | None = None,
    ) -> None:
        self._project_root_override = (
            Path(project_root) if project_root is not None else None
        )
        self._python_executable_override = (
            Path(python_executable) if python_executable is not None else None
        )
        self._server_path_override = (
            Path(server_path) if server_path is not None else None
        )

        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._call_lock: asyncio.Lock | None = None
        self._tools: list[Tool] | None = None

    # ------------------------------------------------------------------
    # Yol çözümleme
    # ------------------------------------------------------------------

    @property
    def project_root(self) -> Path:
        """
        Aktif proje klasörünü döndürür.

        Öncelik sırası:
        1. Kurucuya verilen project_root
        2. PROJECT_MEMORY_ROOT ortam değişkeni
        3. Repository root (bu dosyanın iki üst klasörü)
        """

        if self._project_root_override is not None:
            return self._project_root_override.resolve()

        environment_root = os.getenv(PROJECT_ROOT_ENV)
        if environment_root:
            return Path(environment_root).resolve()

        return PROJECT_ROOT.resolve()

    @property
    def python_executable(self) -> Path:
        """
        MCP sunucusunu başlatacak Python yorumlayıcısını döndürür.

        Öncelik sırası:
        1. Kurucuya verilen python_executable
        2. MCP_PYTHON ortam değişkeni
        3. sys.executable (çalışan yorumlayıcı)
        """

        if self._python_executable_override is not None:
            return self._python_executable_override.resolve()

        environment_python = os.getenv(PYTHON_EXECUTABLE_ENV)
        if environment_python:
            return Path(environment_python).resolve()

        return Path(sys.executable).resolve()

    @property
    def server_path(self) -> Path:
        """
        Başlatılacak MCP sunucusu dosyasının yolunu döndürür.

        Öncelik sırası:
        1. Kurucuya verilen server_path
        2. MCP_SERVER_PATH ortam değişkeni
        3. project_root/server.py
        """

        if self._server_path_override is not None:
            return self._server_path_override.resolve()

        environment_server = os.getenv(SERVER_PATH_ENV)
        if environment_server:
            return Path(environment_server).resolve()

        return self.project_root / "server.py"

    # ------------------------------------------------------------------
    # Bağlantı durumu
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """
        Bağlantının kurulup kurulmadığını döndürür.
        """

        return (
            self._exit_stack is not None
            and self._session is not None
            and self._tools is not None
        )

    @property
    def tool_names(self) -> list[str]:
        """
        Bağlantı kurulduğunda sunucudan listelenen
        MCP araç isimlerini döndürür.
        """

        if self._tools is None:
            return []

        return [tool.name for tool in self._tools]

    @property
    def tools(self) -> list[Tool]:
        """
        Bağlantı kurulduğunda sunucudan listelenen
        ham MCP araç nesnelerini döndürür.
        """

        return list(self._tools) if self._tools is not None else []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """
        server.py MCP sunucusunu stdio subprocess olarak başlatır.

        - StdioServerParameters oluşturulur.
        - stdio_client ile subprocess'e bağlanılır.
        - ClientSession kurulur.
        - initialize() ile handshake yapılır.
        - list_tools() ile araç listesi çekilir ve cache'lenir.

        Bağlantı başarısız olursa açılan kaynaklar kapatılır ve
        anlaşılır bir ProjectMemoryClientError yükseltilir.
        """

        if self.is_connected:
            return

        project_root = self.project_root
        python_executable = self.python_executable
        server_path = self.server_path

        if not project_root.is_dir():
            raise ProjectMemoryClientError(
                f"Proje klasörü bulunamadı: {project_root}"
            )

        if not python_executable.is_file():
            raise ProjectMemoryClientError(
                f"Python yorumlayıcısı bulunamadı: {python_executable}"
            )

        if not server_path.is_file():
            raise ProjectMemoryClientError(
                f"MCP sunucusu dosyası bulunamadı: {server_path}"
            )

        parameters = StdioServerParameters(
            command=str(python_executable),
            args=[str(server_path)],
            cwd=str(project_root),
            env={
                # Aktif proje, MCP sunucusunun resolve_project_context
                # fonksiyonuna PROJECT_MEMORY_ROOT üzerinden iletilir.
                PROJECT_ROOT_ENV: str(project_root),
                # Ortamdaki diğer değişkenler de aynen aktarılır.
                # Örneğin testlerin ayarladığı PROJECT_MEMORY_DB_PATH
                # sayesinde geçici veritabanı kullanılabilir.
                **os.environ,
            },
        )

        self._exit_stack = AsyncExitStack()

        try:
            read_stream, write_stream = (
                await self._exit_stack.enter_async_context(
                    stdio_client(parameters)
                )
            )

            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            # MCP handshake: initialize + initialized notification.
            await self._session.initialize()

            # Araç listesini bir kez çekip cache'ler.
            tools_result = await self._session.list_tools()
            self._tools = list(tools_result.tools)

            # Eşzamanlı call_tool çağrılarını serileştirmek için kilit.
            self._call_lock = asyncio.Lock()

        except Exception as exc:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            raise ProjectMemoryClientError(
                "ProjectMemory MCP sunucusuna bağlanılamadı. "
                f"Detay: {exc}"
            ) from exc

        logger.info(
            "ProjectMemory MCP sunucusuna bağlanıldı. "
            "Araçlar: %s",
            ", ".join(self.tool_names),
        )

    async def close(self) -> None:
        """
        MCP session'ı ve subprocess'i düzgün şekilde kapatır.

        AsyncExitStack, açılış sırasının tersine kapanmayı garanti eder
        (session -> subprocess -> stream'ler). Windows'ta açık
        process/handle bırakmaz.
        """

        self._call_lock = None
        self._tools = None

        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None

        self._session = None

        logger.info("ProjectMemory MCP bağlantısı kapatıldı.")

    # ------------------------------------------------------------------
    # Araç çağrısı
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        """
        Generic MCP araç çağrısı.

        Bağlantı kurulmadan çağrılırsa açık hata yükseltilir.
        Eşzamanlı çağrılar bir asyncio.Lock üzerinden serileştirilir.
        Sonuç, ToolResult ile normalize edilmiş biçimde döndürülür.
        """

        if not self.is_connected or self._session is None:
            raise ProjectMemoryClientError(
                "MCP bağlantısı kurulmadı. "
                "Önce await client.connect() çağırın."
            )

        try:
            async with self._call_lock:
                result = await self._session.call_tool(
                    name,
                    arguments,
                )
        except Exception as exc:
            raise ProjectMemoryClientError(
                f"MCP araç çağrısı başarısız oldu ({name}). Detay: {exc}"
            ) from exc

        return ToolResult(
            data=self._parse_tool_result(result),
            is_error=result.is_error,
            raw=result,
        )

    @staticmethod
    def _parse_tool_result(result: CallToolResult) -> Any:
        """
        MCP araç sonucunu güvenli biçimde normalize eder.

        Öncelik sırası:
        1. structured_content varsa olduğu gibi kullanılır.
        2. Aksi halde textual content içindeki JSON parse edilir.
        3. Parse edilemezse okunabilir metin fallback olarak döndürülür.
        4. Hiçbir içerik yoksa None döndürülür.
        """

        if result.structured_content is not None:
            return result.structured_content

        text_parts: list[str] = []
        for block in result.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)

        if text_parts:
            joined_text = "".join(text_parts)

            try:
                return json.loads(joined_text)
            except (json.JSONDecodeError, ValueError):
                return joined_text

        if result.is_error:
            return "MCP araç çağrısı hata döndürdü."

        return None

    # ------------------------------------------------------------------
    # Convenience wrapper'lar
    #
    # Bunlar yalnızca generic call_tool'u kullanır; ProjectMemory'nin
    # iş mantığı (duplicate kontrolü vb.) chat tarafında tekrar
    # implement edilmez.
    # ------------------------------------------------------------------

    async def remember(
        self,
        content: str,
        category: str,
        importance: int = 5,
    ) -> ToolResult:
        """
        remember MCP aracını çağırır.
        """

        return await self.call_tool(
            "remember",
            {
                "content": content,
                "category": category,
                "importance": importance,
            },
        )

    async def recall(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> ToolResult:
        """
        recall MCP aracını çağırır.
        """

        arguments: dict[str, Any] = {
            "query": query,
            "limit": limit,
        }

        if category is not None:
            arguments["category"] = category

        return await self.call_tool("recall", arguments)

    async def search_memories(
        self,
        terms: list[str],
        category: str | None = None,
        limit: int = 5,
    ) -> ToolResult:
        """
        search_memories MCP aracını çağırır.

        Arama terimleri, cevabı BİLİNMEYEN değerlerden üretilmemelidir.
        Örneğin "Backend framework neydi?" sorusunda cevabın FastAPI
        olduğu bilinmiyorsa "fastapi" arama terimi olarak KULLANILMAZ;
        bunun yerine ["backend", "framework", "api"] gibi sorudan
        çıkarılan genel terimler kullanılır. Bu karar LLM tarafında
        verilir; burada yalnızca aracı çağırmak yeterlidir.
        """

        arguments: dict[str, Any] = {
            "terms": terms,
            "limit": limit,
        }

        if category is not None:
            arguments["category"] = category

        return await self.call_tool("search_memories", arguments)

    async def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
    ) -> ToolResult:
        """
        list_memories MCP aracını çağırır.
        """

        arguments: dict[str, Any] = {
            "limit": limit,
        }

        if category is not None:
            arguments["category"] = category

        return await self.call_tool("list_memories", arguments)

    async def get_project_context(self, limit: int = 10) -> ToolResult:
        return await self.call_tool("get_project_context", {"limit": limit})

    async def update_memory(
        self,
        memory_id: int,
        content: str | None = None,
        category: str | None = None,
        importance: int | None = None,
    ) -> ToolResult:
        """
        update_memory MCP aracını çağırır.

        Yalnızca verilen alanlar güncellenir; boş bırakılanlar
        değiştirilmez.
        """

        arguments: dict[str, Any] = {
            "memory_id": memory_id,
        }

        if content is not None:
            arguments["content"] = content

        if category is not None:
            arguments["category"] = category

        if importance is not None:
            arguments["importance"] = importance

        return await self.call_tool("update_memory", arguments)

    async def forget(self, memory_id: int) -> ToolResult:
        """
        forget MCP aracını çağırır.
        """

        return await self.call_tool(
            "forget",
            {
                "memory_id": memory_id,
            },
        )

    # ------------------------------------------------------------------
    # Async context manager desteği
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ProjectMemoryClient":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        await self.close()
