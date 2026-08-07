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

        assert "list_memories" in tool_names, (
            "MCP araç listesinde list_memories bulunmalı."
        )

        assert "update_memory" in tool_names, (
            "MCP araç listesinde update_memory bulunmalı."
        )

        assert "forget" in tool_names, (
            "MCP araç listesinde forget bulunmalı."
        )

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

        assert remember_result.structured_content is not None, (
            "remember çağrısı kayıt döndürmeli."
        )

        memory_id = remember_result.structured_content["id"]

        update_result = await client.call_tool(
            "update_memory",
            {
                "memory_id": memory_id,
                "content": (
                    "ProjectMemory MCP sunucusu Python ile "
                    "geliştiriliyor ve pytest ile test ediliyor."
                ),
                "importance": 9,
            },
        )

        print(
            "Update hata durumu:",
            update_result.is_error,
        )

        print(
            "Update sonucu:",
            update_result.structured_content,
        )

        assert not update_result.is_error, (
            "update_memory çağrısı hata vermemeli."
        )

        assert update_result.structured_content is not None, (
            "update_memory çağrısı güncellenmiş kaydı döndürmeli."
        )

        assert update_result.structured_content["id"] == memory_id, (
            "Güncellenen kaydın kimliği aynı kalmalı."
        )

        assert update_result.structured_content["importance"] == 9, (
            "Önem seviyesi güncellenmiş olmalı."
        )

        assert "pytest" in update_result.structured_content["content"], (
            "İçerik güncellenmiş olmalı."
        )

        missing_update_result = await client.call_tool(
            "update_memory",
            {
                "memory_id": 999_999,
                "content": "Varolmayan bir kaydın içeriği.",
            },
        )

        print(
            "Kayıp kayıt update hata durumu:",
            missing_update_result.is_error,
        )

        assert missing_update_result.is_error, (
            "Varolmayan bir hafıza güncellenmeye çalışıldığında "
            "hata dönülmeli."
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

        list_result = await client.call_tool(
            "list_memories",
            {
                "category": "technology",
                "limit": 20,
            },
        )

        print(
            "List hata durumu:",
            list_result.is_error,
        )

        print(
            "List sonucu:",
            list_result.structured_content,
        )

        assert not list_result.is_error, (
            "list_memories çağrısı hata vermemeli."
        )

        assert list_result.structured_content is not None, (
            "list_memories çağrısı kayıt döndürmeli."
        )

        # Silme (forget) testi için geçici bir hafıza oluşturur.
        forget_memory_result = await client.call_tool(
            "remember",
            {
                "content": (
                    "Silme testi için oluşturulan geçici hafıza."
                ),
                "category": "technology",
                "importance": 3,
            },
        )

        assert not forget_memory_result.is_error, (
            "Silme testi için hafıza oluşturulurken hata olmamalı."
        )

        assert forget_memory_result.structured_content is not None, (
            "Silme testi için hafıza kaydı döndürülmeli."
        )

        forget_memory_id = forget_memory_result.structured_content["id"]

        forget_result = await client.call_tool(
            "forget",
            {
                "memory_id": forget_memory_id,
            },
        )

        print(
            "Forget hata durumu:",
            forget_result.is_error,
        )

        print(
            "Forget sonucu:",
            forget_result.structured_content,
        )

        assert not forget_result.is_error, (
            "forget çağrısı hata vermemeli."
        )

        assert forget_result.structured_content is not None, (
            "forget çağrısı silinen kaydı döndürmeli."
        )

        assert forget_result.structured_content["id"] == forget_memory_id, (
            "Silinen kaydın kimliği doğru olmalı."
        )

        # Silinen kaydın artık bulunmadığını recall ile doğrular.
        forgotten_recall_result = await client.call_tool(
            "recall",
            {
                "query": "Silme testi",
                "category": "technology",
                "limit": 5,
            },
        )

        assert not forgotten_recall_result.is_error, (
            "Silme sonrası recall çağrısı hata vermemeli."
        )

        forgotten_ids = [
            memory["id"]
            for memory in forgotten_recall_result.structured_content["result"]
        ]

        assert forget_memory_id not in forgotten_ids, (
            "Silinen kayıt recall sonuçlarında bulunmamalı."
        )

        # Silinen kaydın list_memories ile de bulunmadığını doğrular.
        forgotten_list_result = await client.call_tool(
            "list_memories",
            {
                "category": "technology",
                "limit": 100,
            },
        )

        assert not forgotten_list_result.is_error, (
            "Silme sonrası list_memories çağrısı hata vermemeli."
        )

        forgotten_list_ids = [
            memory["id"]
            for memory in forgotten_list_result.structured_content["result"]
        ]

        assert forget_memory_id not in forgotten_list_ids, (
            "Silinen kayıt list_memories sonuçlarında bulunmamalı."
        )

        # Varolmayan bir hafıza silinmeye çalışıldığında hata dönmeli.
        missing_forget_result = await client.call_tool(
            "forget",
            {
                "memory_id": 999_999,
            },
        )

        print(
            "Kayıp kayıt forget hata durumu:",
            missing_forget_result.is_error,
        )

        assert missing_forget_result.is_error, (
            "Varolmayan bir hafıza silinmeye çalışıldığında "
            "hata dönülmeli."
        )


if __name__ == "__main__":
    asyncio.run(main())