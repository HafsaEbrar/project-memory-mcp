from mcp.server import MCPServer

from project_memory.tools import (
    forget_memory as forget_memory_tool,
    get_project_context as get_project_context_tool,
    list_memories as list_memories_tool,
    recall_memories,
    remember_memory,
    search_memories as search_memories_tool,
    update_memory as update_memory_tool,
)


# MCP sunucumuzu oluşturuyoruz.
mcp = MCPServer("ProjectMemory")


@mcp.tool()
def remember(
    content: str,
    category: str,
    importance: int = 5,
    scope: str = "shared",
) -> dict[str, object]:
    """
    Aktif projeye önemli bir bilgiyi kalıcı olarak kaydeder.

    Args:
        content:
            Gelecekte hatırlanması gereken açık proje bilgisi.

        category:
            decision, architecture, technology, error_solution,
            todo, preference veya session_summary değerlerinden biri.

        importance:
            Bilginin 1 ile 10 arasındaki önem seviyesi.
    """

    return remember_memory(
        content=content,
        category=category,
        importance=importance,
        scope=scope,
    )


@mcp.tool()
def recall(
    query: str,
    category: str | None = None,
    limit: int = 5,
    owner_id: str | None = None,
) -> list[dict[str, object]]:
    """
    Aktif projeye ait geçmiş hafızalarda arama yapar.

    Args:
        query:
            Hafızalarda aranacak kısa kelime veya ifade.

        category:
            İsteğe bağlı hafıza kategorisi.

        limit:
            Döndürülecek en fazla sonuç sayısı.
    """

    return recall_memories(
        query=query,
        category=category,
        limit=limit,
        owner_id=owner_id,
    )


@mcp.tool()
def search_memories(
    terms: list[str],
    category: str | None = None,
    limit: int = 5,
    owner_id: str | None = None,
) -> list[dict[str, object]]:
    """
    Aktif projeye ait hafızalarda SQLite FTS5 tabanlı indeksli arama yapar.

    Bu araç semantik embedding modeli kullanmaz; yalnızca verilen
    terimleri FTS5 kelime indeksi üzerinden eşleştirir.

    Agent, kullanıcının sorusundan mümkünse birkaç anlamlı anahtar
    kelime veya eş anlamlı üretmelidir (örneğin "database" ve
    "veritabanı" gibi). Semantik anlam çıkarımı ajanın görevidir.

    Args:
        terms:
            Aranacak kelime veya terimler. Terimlerden en az biriyle
            eşleşen hafızalar döndürülür (OR mantığı).

        category:
            İsteğe bağlı hafıza kategorisi.

        limit:
            Döndürülecek en fazla sonuç sayısı.
    """

    return search_memories_tool(
        terms=terms,
        category=category,
        limit=limit,
        owner_id=owner_id,
    )


@mcp.tool()
def update_memory(
    memory_id: int,
    content: str | None = None,
    category: str | None = None,
    importance: int | None = None,
) -> dict[str, object]:
    """
    Aktif projeye ait kayıtlı bir hafızayı günceller.

    Args:
        memory_id:
            Güncellenecek hafızanın kimliği.

        content:
            İsteğe bağlı yeni içerik.

        category:
            İsteğe bağlı yeni kategori. Geçerli kategoriler:
            decision, architecture, technology, error_solution,
            todo, preference veya session_summary.

        importance:
            İsteğe bağlı yeni önem seviyesi (1 ile 10 arası).
    """

    return update_memory_tool(
        memory_id=memory_id,
        content=content,
        category=category,
        importance=importance,
    )


@mcp.tool()
def forget(
    memory_id: int,
) -> dict[str, object]:
    """
    Aktif projeye ait kayıtlı bir hafızayı kalıcı olarak siler.

    Bu işlem geri alınamaz. Hafıza kaydı veritabanından tamamen
    kaldırılır. Yanlış kayıt silmemek için hangi kaydın
    silineceği netleşmediyse önce list_memories veya recall
    ile doğru kaydı bulun.

    Args:
        memory_id:
            Silinecek hafızanın kimliği.
    """

    return forget_memory_tool(
        memory_id=memory_id,
    )


@mcp.tool()
def list_memories(
    category: str | None = None,
    limit: int = 20,
    owner_id: str | None = None,
) -> list[dict[str, object]]:
    """
    Aktif projeye ait geçmiş hafızaları listeler.

    Args:
        category:
            İsteğe bağlı hafıza kategorisi.
            Boş bırakılırsa bütün kategoriler listelenir.

        limit:
            Döndürülecek en fazla sonuç sayısı.
    """

    return list_memories_tool(
        category=category,
        limit=limit,
        owner_id=owner_id,
    )


@mcp.tool()
def get_project_context(limit: int = 10) -> dict[str, object]:
    """Shared ve current-user hafızalarından proje context'i döndürür."""

    return get_project_context_tool(limit=limit)


if __name__ == "__main__":
    mcp.run()
