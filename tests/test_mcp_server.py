import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    """
    MCP sunucusuna bellek içinde bağlanır.

    Araçları listeler, bir hafıza kaydeder
    ve ardından bu hafızayı tekrar arar.
    """

    async with Client(mcp) as client:
        tools_result = await client.list_tools()

        tool_names = [
            tool.name
            for tool in tools_result.tools
        ]

        print("MCP araçları:", tool_names)

        remember_result = await client.call_tool(
            "remember",
            {
                "content": (
                    "ProjectMemory MCP sunucusu "
                    "Python ile geliştiriliyor."
                ),
                "category": "technology",
                "importance": 8,
            },
        )

        print(
            "Remember hata durumu:",
            remember_result.is_error,
        )

        print(
            "Remember sonucu:",
            remember_result.structured_content,
        )

        recall_result = await client.call_tool(
            "recall",
            {
                "query": "MCP",
                "category": "technology",
                "limit": 5,
            },
        )

        print(
            "Recall hata durumu:",
            recall_result.is_error,
        )

        print(
            "Recall sonucu:",
            recall_result.structured_content,
        )


if __name__ == "__main__":
    asyncio.run(main())