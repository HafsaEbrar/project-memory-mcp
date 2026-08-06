from mcp.server import MCPServer

from project_memory.tools import (
    recall_memories,
    remember_memory,
)


# MCP sunucumuzu oluşturuyoruz.
mcp = MCPServer("ProjectMemory")


@mcp.tool()
def remember(
    content: str,
    category: str,
    importance: int = 5,
) -> dict[str, str | int]:
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
    )


@mcp.tool()
def recall(
    query: str,
    category: str | None = None,
    limit: int = 5,
) -> list[dict[str, str | int]]:
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
    )


if __name__ == "__main__":
    mcp.run()