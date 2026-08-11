"""Normal chat MCP istemcisi (ProjectMemoryClient) smoke testi.

Bu test, chat/  paketindeki istemcinin mevcut server.py MCP sunucusuna
stdio üzerinden gerçekten bağlanabildiğini ve hafıza işlemlerini MCP
araçları üzerinden yapabildiğini kanıtlar.

Test akışı:
    A) connect
    B) list_tools ile 6 aracın varlığı
    C) remember
    D) search_memories ile kaydı bul
    E) update_memory ile içeriği güncelle
    F) search_memories ile güncel halini bul
    G) forget ile sil
    H) search_memories ile silindiğini doğrula
    I) connection düzgün kapanır

Veritabanı izolasyonu:
    MCP subprocess'ine PROJECT_MEMORY_DB_PATH ortam değişkeni geçirilir.
    Bu sayede gerçek data/memories.db dosyasına hiç dokunulmaz; testler
    geçici bir klasördeki veritabanında koşar.

Production güvenliği:
    Testten önce data/memories.db boyutu ve değiştirilme zamanı
    kaydedilir; test sonunda değişmediği doğrulanır.
"""

import asyncio
import os
import tempfile
from pathlib import Path

from project_memory.database import DATABASE_PATH

from chat.memory_client import (
    ProjectMemoryClient,
    ProjectMemoryClientError,
)

# Geçici test veritabanı. MCP subprocess'i bu yolu PROJECT_MEMORY_DB_PATH
# ortam değişkeni üzerinden alır; production veritabanı kullanılmaz.
_TEMP_DB_DIR = tempfile.TemporaryDirectory()
_TEST_DB_PATH = Path(_TEMP_DB_DIR.name) / "test_chat_memories.db"
os.environ["PROJECT_MEMORY_DB_PATH"] = str(_TEST_DB_PATH)

print(f"Chat test database: {_TEST_DB_PATH}")

EXPECTED_TOOL_NAMES = {
    "remember",
    "recall",
    "search_memories",
    "list_memories",
    "update_memory",
    "forget",
}


def _file_state(path: Path) -> tuple[int, float] | None:
    """
    Bir dosyanın boyutunu ve son değiştirilme zamanını döndürür.

    Dosya yoksa None döner. Production veritabanının test boyunca
    değişmediğini doğrulamak için kullanılır.
    """

    try:
        stat = path.stat()
    except FileNotFoundError:
        return None

    return stat.st_size, stat.st_mtime


def _search_ids(result) -> list[int]:
    """
    search_memories sonucundaki hafıza kimliklerini döndürür.
    """

    assert not result.is_error, "search_memories çağrısı hata vermemeli."
    assert result.data is not None, "search_memories sonuç döndürmeli."

    return [
        memory["id"]
        for memory in result.data["result"]
    ]


async def main() -> None:
    """
    Gerçek MCP subprocess'i üzerinden smoke test akışını koşar.
    """

    # Bağlantı kurulmadan call_tool çağrılırsa açık hata verilmeli.
    unconnected_client = ProjectMemoryClient()
    try:
        await unconnected_client.call_tool("list_memories")
        raise AssertionError(
            "Bağlantı kurulmadan call_tool açık hata vermelidir."
        )
    except ProjectMemoryClientError:
        pass

    async with ProjectMemoryClient() as client:
        # A) connect (async context manager __aenter__ ile yapılır)
        assert client.is_connected, "connect sonrası is_connected True olmalı."

        # B) list_tools
        print("MCP araçları:", sorted(client.tool_names))

        assert set(client.tool_names) == EXPECTED_TOOL_NAMES, (
            "MCP araç listesinde beklenen 6 aracın tamamı bulunmalıdır."
        )

        # C) remember
        original_content = "Normal chat MCP bağlantı testi başarılı."
        remember_result = await client.remember(
            content=original_content,
            category="technology",
            importance=7,
        )

        print("Remember hata durumu:", remember_result.is_error)
        print("Remember sonucu:", remember_result.data)

        assert not remember_result.is_error, (
            "remember çağrısı hata vermemeli."
        )
        assert remember_result.data is not None, (
            "remember çağrısı kayıt döndürmeli."
        )

        memory_id = remember_result.data["id"]
        assert remember_result.data["content"] == original_content, (
            "Kaydedilen içerik doğru olmalı."
        )

        # D) search_memories ile kaydı bul
        found_result = await client.search_memories(
            terms=["normal", "chat", "bağlantı"],
            limit=5,
        )

        assert memory_id in _search_ids(found_result), (
            "Remember ile kaydedilen hafıza search_memories ile "
            "bulunmalıdır."
        )

        # E) update_memory ile içeriği güncelle
        updated_content = "Normal chat MCP bağlantı ve update testi başarılı."
        update_result = await client.update_memory(
            memory_id=memory_id,
            content=updated_content,
        )

        print("Update hata durumu:", update_result.is_error)
        print("Update sonucu:", update_result.data)

        assert not update_result.is_error, (
            "update_memory çağrısı hata vermemeli."
        )
        assert update_result.data["id"] == memory_id, (
            "Güncellenen kaydın kimliği aynı kalmalı."
        )
        assert update_result.data["content"] == updated_content, (
            "İçerik güncellenmiş olmalı."
        )

        # F) search_memories ile güncel halini bul.
        # "update" kelimesi yalnızca güncelleme sonrası içerikte vardır;
        # bu, FTS indeksinin güncellendiğini de doğrular.
        after_update_result = await client.search_memories(
            terms=["update"],
            limit=5,
        )

        assert memory_id in _search_ids(after_update_result), (
            "Güncellenen hafıza yeni içerikle search_memories ile "
            "bulunmalıdır."
        )

        matching_memories = [
            memory
            for memory in after_update_result.data["result"]
            if memory["id"] == memory_id
        ]
        assert matching_memories, (
            "Arama sonucunda kayıt bulunmalıdır."
        )
        assert matching_memories[0]["content"] == updated_content, (
            "Arama sonucu güncel içeriği döndürmelidir."
        )

        # G) forget ile sil
        forget_result = await client.forget(memory_id=memory_id)

        print("Forget hata durumu:", forget_result.is_error)
        print("Forget sonucu:", forget_result.data)

        assert not forget_result.is_error, (
            "forget çağrısı hata vermemeli."
        )
        assert forget_result.data["id"] == memory_id, (
            "Silinen kaydın kimliği doğru olmalı."
        )

        # H) search_memories ile silindiğini doğrula
        after_forget_result = await client.search_memories(
            terms=["update"],
            limit=5,
        )

        assert memory_id not in _search_ids(after_forget_result), (
            "Forget sonrası silinen kayıt search_memories ile "
            "bulunmamalıdır."
        )

    # I) connection düzgün kapanmış olmalı
    assert not client.is_connected, (
        "close sonrası is_connected False olmalı."
    )

    print("Smoke test akışı (A-I) başarıyla tamamlandı.")


if __name__ == "__main__":
    # Testten önce production veritabanının durumunu kaydeder.
    production_db_before = _file_state(DATABASE_PATH)
    temp_db_dir_path = Path(_TEMP_DB_DIR.name)

    try:
        asyncio.run(main())
    finally:
        # Ortam değişkenini temizler ve geçici test veritabanını siler.
        os.environ.pop("PROJECT_MEMORY_DB_PATH", None)
        _TEMP_DB_DIR.cleanup()

    # Production veritabanı değişmemiş olmalı.
    production_db_after = _file_state(DATABASE_PATH)

    assert production_db_before == production_db_after, (
        "Production veritabanı test sırasında değiştirilmemelidir: "
        f"{DATABASE_PATH}"
    )

    # Geçici test veritabanı silinebilmiş olmalı
    # (açık process/handle bırakılmamalı).
    assert not temp_db_dir_path.exists(), (
        "Geçici test veritabanı klasörü silinebilmelidir."
    )

    print(f"Production database değişmedi: {DATABASE_PATH}")
    print(f"Geçici test veritabanı silindi: {temp_db_dir_path}")
