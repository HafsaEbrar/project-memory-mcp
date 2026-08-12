import asyncio
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from mcp import Client

from project_memory.database import (
    DATABASE_PATH,
    get_database_path,
    initialize_database,
)


# ÖNEMLİ: "from server import mcp" satırı import edildiğinde tools modülü
# MemoryService'i oluşturur ve bu da veritabanını başlatır. Bu yüzden
# PROJECT_MEMORY_DB_PATH ortam değişkeni server import edilmeden ÖNCE
# ayarlanmalıdır. Aksi halde başlangıçtaki init gerçek data/memories.db
# dosyası üzerinde çalışır.
#
# Test veritabanı geçici bir klasörde oluşturulur; test bittiğinde
# klasör silinir ve ortam değişkeni temizlenir.
_TEMP_DB_DIR = tempfile.TemporaryDirectory()
_TEST_DB_PATH = Path(_TEMP_DB_DIR.name) / "test_memories.db"
os.environ["PROJECT_MEMORY_DB_PATH"] = str(_TEST_DB_PATH)

print(f"Test database: {_TEST_DB_PATH}")

from server import mcp  # noqa: E402


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


def _direct_connection() -> sqlite3.Connection:
    """
    FTS indeksini bilinçli olarak bozmak için
    veritabanına doğrudan bağlantı açar.
    """

    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row
    return connection


def _test_ownership_migration() -> None:
    active_db = os.environ["PROJECT_MEMORY_DB_PATH"]
    legacy_db = Path(_TEMP_DB_DIR.name) / "legacy-memories.db"
    with closing(sqlite3.connect(legacy_db)) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO projects (name, root_path) VALUES ('legacy', '/legacy');
            INSERT INTO memories (project_id, content, category, importance)
            VALUES (1, 'Korunacak production benzeri kayıt.', 'decision', 8);
            """
        )
        connection.commit()

    try:
        os.environ["PROJECT_MEMORY_DB_PATH"] = str(legacy_db)
        initialize_database()
        with closing(sqlite3.connect(legacy_db)) as connection:
            row = connection.execute(
                "SELECT content, scope, owner_id FROM memories"
            ).fetchone()
        assert row == ("Korunacak production benzeri kayıt.", "shared", None)
    finally:
        os.environ["PROJECT_MEMORY_DB_PATH"] = active_db


async def _search_memories(
    client: Client,
    terms: list[str],
    category: str | None = None,
    limit: int = 5,
) -> list[dict[str, object]]:
    """
    search_memories aracını çağırır ve sonuç listesini döndürür.
    """

    arguments: dict[str, object] = {
        "terms": terms,
        "limit": limit,
    }

    if category is not None:
        arguments["category"] = category

    result = await client.call_tool("search_memories", arguments)

    assert not result.is_error, (
        "search_memories çağrısı hata vermemeli."
    )

    assert result.structured_content is not None, (
        "search_memories çağrısı sonuç döndürmeli."
    )

    return result.structured_content["result"]


async def _test_project_context(client: Client) -> None:
    original_root = os.environ.get("PROJECT_MEMORY_ROOT")
    project_a = Path(_TEMP_DB_DIR.name) / "context-project-a"
    project_b = Path(_TEMP_DB_DIR.name) / "context-project-b"
    project_a.mkdir()
    project_b.mkdir()

    try:
        os.environ["PROJECT_MEMORY_ROOT"] = str(project_a)
        empty = await client.call_tool("get_project_context", {})
        assert not empty.is_error
        assert empty.structured_content["memories"] == []

        records = [
            ("Aynı exact proje kararı.", "technology", 10),
            ("Mimari sınırlar modüllerle korunur.", "architecture", 9),
            ("Aynı exact proje kararı.", "decision", 9),
            ("Yüksek önemde teknoloji kaydı 1.", "technology", 8),
            ("Yüksek önemde teknoloji kaydı 2.", "technology", 8),
            ("Yüksek önemde teknoloji kaydı 3.", "technology", 8),
            ("Düşük önemde farklı kategori.", "preference", 4),
        ]
        for content, category, importance in records:
            result = await client.call_tool(
                "remember",
                {"content": content, "category": category,
                 "importance": importance},
            )
            assert not result.is_error

        context = await client.call_tool("get_project_context", {"limit": 5})
        memories = context.structured_content["memories"]
        assert [memory["importance"] for memory in memories] == [10, 9, 8, 8, 8]
        assert sum(memory["content"] == "Aynı exact proje kararı." for memory in memories) == 1
        assert "Düşük önemde farklı kategori." not in {
            memory["content"] for memory in memories
        }

        os.environ["PROJECT_MEMORY_ROOT"] = str(project_b)
        isolated = await client.call_tool("get_project_context", {})
        assert isolated.structured_content["memories"] == []
    finally:
        if original_root is None:
            os.environ.pop("PROJECT_MEMORY_ROOT", None)
        else:
            os.environ["PROJECT_MEMORY_ROOT"] = original_root


async def _test_memory_ownership(client: Client) -> None:
    original_root = os.environ.get("PROJECT_MEMORY_ROOT")
    original_user = os.environ.get("PROJECT_MEMORY_USER_ID")
    project_root = Path(_TEMP_DB_DIR.name) / "ownership-project"
    project_root.mkdir()

    try:
        os.environ["PROJECT_MEMORY_ROOT"] = str(project_root)
        os.environ["PROJECT_MEMORY_USER_ID"] = "ebrar"

        shared = await client.call_tool(
            "remember",
            {"content": "SQLite ortak karar olarak kullanılacak.",
             "category": "decision", "importance": 9, "scope": "shared"},
        )
        ebrar = await client.call_tool(
            "remember",
            {"content": "Aynı içerikli kişisel çalışma kaydı.",
             "category": "todo", "importance": 7, "scope": "user"},
        )
        assert not shared.is_error and not ebrar.is_error
        assert shared.structured_content["owner_id"] is None
        assert ebrar.structured_content["owner_id"] == "ebrar"

        os.environ["PROJECT_MEMORY_USER_ID"] = "ayse"
        ayse = await client.call_tool(
            "remember",
            {"content": "Aynı içerikli kişisel çalışma kaydı.",
             "category": "todo", "importance": 7, "scope": "user"},
        )
        ayse_fts = await client.call_tool(
            "remember",
            {"content": "Ayşe ownership API testlerini düzenledi.",
             "category": "session_summary", "importance": 8, "scope": "user"},
        )
        assert not ayse.is_error and not ayse_fts.is_error
        assert ayse.structured_content["id"] != ebrar.structured_content["id"]
        assert ayse.structured_content["owner_id"] == "ayse"
        ayse_context = await client.call_tool(
            "get_project_context", {"limit": 20}
        )
        ayse_context_ids = {
            item["id"]
            for item in ayse_context.structured_content["memories"]
        }
        assert shared.structured_content["id"] in ayse_context_ids
        assert ebrar.structured_content["id"] not in ayse_context_ids

        os.environ["PROJECT_MEMORY_USER_ID"] = "ebrar"
        default_list = await client.call_tool("list_memories", {"limit": 20})
        default_recall = await client.call_tool(
            "recall", {"query": "kişisel çalışma", "limit": 20}
        )
        default_search = await client.call_tool(
            "search_memories", {"terms": ["ownership"], "limit": 20}
        )
        context = await client.call_tool("get_project_context", {"limit": 20})

        default_ids = {item["id"] for item in default_list.structured_content["result"]}
        assert shared.structured_content["id"] in default_ids
        assert ebrar.structured_content["id"] in default_ids
        assert ayse.structured_content["id"] not in default_ids
        assert [item["owner_id"] for item in default_recall.structured_content["result"]] == ["ebrar"]
        assert default_search.structured_content["result"] == []
        context_ids = {item["id"] for item in context.structured_content["memories"]}
        assert shared.structured_content["id"] in context_ids
        assert ebrar.structured_content["id"] in context_ids
        assert ayse.structured_content["id"] not in context_ids

        explicit_list = await client.call_tool(
            "list_memories", {"owner_id": "ayse", "limit": 20}
        )
        explicit_recall = await client.call_tool(
            "recall", {"query": "kişisel çalışma", "owner_id": "ayse"}
        )
        explicit_search = await client.call_tool(
            "search_memories", {"terms": ["ownership"], "owner_id": "ayse"}
        )
        explicit_ids = {
            item["id"] for item in explicit_list.structured_content["result"]
        }
        assert ayse.structured_content["id"] in explicit_ids
        assert shared.structured_content["id"] not in explicit_ids
        assert explicit_recall.structured_content["result"][0]["owner_id"] == "ayse"
        assert explicit_search.structured_content["result"][0]["owner_id"] == "ayse"

        denied_update = await client.call_tool(
            "update_memory",
            {"memory_id": ayse.structured_content["id"], "importance": 10},
        )
        denied_forget = await client.call_tool(
            "forget", {"memory_id": ayse.structured_content["id"]}
        )
        assert denied_update.is_error
        assert denied_forget.is_error

        other_project = Path(_TEMP_DB_DIR.name) / "ownership-other-project"
        other_project.mkdir()
        os.environ["PROJECT_MEMORY_ROOT"] = str(other_project)
        isolated_list = await client.call_tool("list_memories", {"limit": 20})
        assert isolated_list.structured_content["result"] == []
    finally:
        if original_root is None:
            os.environ.pop("PROJECT_MEMORY_ROOT", None)
        else:
            os.environ["PROJECT_MEMORY_ROOT"] = original_root
        if original_user is None:
            os.environ.pop("PROJECT_MEMORY_USER_ID", None)
        else:
            os.environ["PROJECT_MEMORY_USER_ID"] = original_user


async def main() -> None:
    """
    MCP sunucusuna bellek içinde bağlanır.

    Araçları listeler, bir hafıza kaydeder
    ve ardından bu hafızayı tekrar arar.
    """

    _test_ownership_migration()

    async with Client(mcp) as client:
        tools_result = await client.list_tools()

        tool_names = [
            tool.name
            for tool in tools_result.tools
        ]

        print("MCP araçları:", tool_names)

        assert "search_memories" in tool_names, (
            "MCP araç listesinde search_memories bulunmalı."
        )

        assert "list_memories" in tool_names, (
            "MCP araç listesinde list_memories bulunmalı."
        )

        assert "update_memory" in tool_names, (
            "MCP araç listesinde update_memory bulunmalı."
        )

        assert "forget" in tool_names, (
            "MCP araç listesinde forget bulunmalı."
        )

        assert "get_project_context" in tool_names
        await _test_project_context(client)
        await _test_memory_ownership(client)

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

        # ------------------------------------------------------------
        # SQLite FTS5 tabanlı indeksli arama (search_memories) testleri
        # ------------------------------------------------------------

        # FTS5'in görevi kelime/terim indekslemesidir.
        # Burada embedding semantic similarity testi yapılmaz.
        fts_memory_result = await client.call_tool(
            "remember",
            {
                "content": (
                    "ProjectMemory projesinde veritabanı olarak "
                    "SQLite kullanılacak."
                ),
                "category": "technology",
                "importance": 7,
            },
        )

        assert not fts_memory_result.is_error, (
            "FTS testi için hafıza oluşturulurken hata olmamalı."
        )

        assert fts_memory_result.structured_content is not None, (
            "FTS testi için hafıza kaydı döndürülmeli."
        )

        fts_memory_id = fts_memory_result.structured_content["id"]

        # İki terimden herhangi biriyle eşleşen kayıt bulunmalı.
        # "veritabanı" kelimesi FTS indeksinde olduğu için
        # "database" ile eşleşmese bile bu kayıt bulunmalıdır.
        fts_search_results = await _search_memories(
            client,
            terms=["database", "veritabanı"],
            limit=5,
        )

        fts_search_ids = [
            memory["id"]
            for memory in fts_search_results
        ]

        assert fts_memory_id in fts_search_ids, (
            "Remember ile kaydedilen hafıza FTS aramasında "
            "bulunmalıdır (veritabanı terimi eşleşir)."
        )

        for memory in fts_search_results:
            assert "rank" in memory, (
                "Arama sonucu rank alanı içermelidir."
            )

            assert isinstance(memory["rank"], (int, float)), (
                "Arama sonucunun rank alanı sayı olmalıdır."
            )

        # Content güncellenince FTS indeksi de güncellenmeli.
        update_fts_result = await client.call_tool(
            "update_memory",
            {
                "memory_id": fts_memory_id,
                "content": (
                    "ProjectMemory projesinde canlitestrakam olarak "
                    "PostgreSQL kullanılacak."
                ),
            },
        )

        assert not update_fts_result.is_error, (
            "FTS testi için hafıza güncellenirken hata olmamalı."
        )

        old_term_results = await _search_memories(
            client,
            terms=["veritabanı"],
            limit=5,
        )

        old_term_ids = [
            memory["id"]
            for memory in old_term_results
        ]

        assert fts_memory_id not in old_term_ids, (
            "Content güncellendikten sonra eski kelimeyle "
            "hafıza bulunmamalıdır."
        )

        new_term_results = await _search_memories(
            client,
            terms=["canlitestrakam"],
            limit=5,
        )

        new_term_ids = [
            memory["id"]
            for memory in new_term_results
        ]

        assert fts_memory_id in new_term_ids, (
            "Content güncellendikten sonra yeni kelimeyle "
            "hafıza bulunmalıdır."
        )

        # Forget sonrası kayıt FTS sonuçlarından kaybolmalı.
        forget_fts_result = await client.call_tool(
            "forget",
            {
                "memory_id": fts_memory_id,
            },
        )

        assert not forget_fts_result.is_error, (
            "FTS testi için hafıza silinirken hata olmamalı."
        )

        after_forget_results = await _search_memories(
            client,
            terms=["canlitestrakam"],
            limit=5,
        )

        after_forget_ids = [
            memory["id"]
            for memory in after_forget_results
        ]

        assert fts_memory_id not in after_forget_ids, (
            "Forget sonrası silinen kayıt FTS sonuçlarında "
            "bulunmamalıdır."
        )

        # Existing eski DB kayıtlarının rebuild/backfill ile
        # bulunabilmesi testi.
        #
        # 1. Hafıza kaydedilir ve FTS indekslenir.
        # 2. FTS kaydı bilinçli olarak silinerek "FTS eklenmeden
        #    önce kaydedilmiş eski kayıt" durumu simüle edilir.
        # 3. Şema sürümü eskiye çekilip veritabanı yeniden başlatılır;
        #    rebuild/backfill FTS indeksini doldurur.
        # 4. Arama sonucunda kayıt tekrar bulunur.
        backfill_memory_result = await client.call_tool(
            "remember",
            {
                "content": (
                    "Rebuild testi için backfillcanary42 "
                    "kelimesi kaydediliyor."
                ),
                "category": "technology",
                "importance": 6,
            },
        )

        assert not backfill_memory_result.is_error, (
            "Backfill testi için hafıza oluşturulurken hata olmamalı."
        )

        backfill_memory_id = backfill_memory_result.structured_content["id"]

        with closing(_direct_connection()) as connection:
            connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?",
                (backfill_memory_id,),
            )
            connection.commit()

        before_rebuild_results = await _search_memories(
            client,
            terms=["backfillcanary42"],
            limit=5,
        )

        before_rebuild_ids = [
            memory["id"]
            for memory in before_rebuild_results
        ]

        assert backfill_memory_id not in before_rebuild_ids, (
            "FTS indeksi bozulduğunda kayıt aramada bulunmamalıdır."
        )

        with closing(_direct_connection()) as connection:
            connection.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('fts_schema_version', 'eski-surum')
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value
                """,
            )
            connection.commit()

        # Veritabanı yeniden başlatıldığında FTS sürümü eşleşmediği için
        # backfill/rebuild çalışır ve eski kayıtlar indekslenir.
        initialize_database()

        after_rebuild_results = await _search_memories(
            client,
            terms=["backfillcanary42"],
            limit=5,
        )

        after_rebuild_ids = [
            memory["id"]
            for memory in after_rebuild_results
        ]

        assert backfill_memory_id in after_rebuild_ids, (
            "Rebuild/backfill sonrası eski kayıt FTS aramasında "
            "bulunmalıdır."
        )

        # Backfill testi için oluşturulan kaydı temizler.
        clean_backfill_result = await client.call_tool(
            "forget",
            {
                "memory_id": backfill_memory_id,
            },
        )

        assert not clean_backfill_result.is_error, (
            "Backfill testi için hafıza silinirken hata olmamalı."
        )

        # Kategori filtresi testi.
        category_memory_result = await client.call_tool(
            "remember",
            {
                "content": "Kategori filtresi testi catfiltercanary77.",
                "category": "decision",
                "importance": 5,
            },
        )

        assert not category_memory_result.is_error, (
            "Kategori filtresi testi için hafıza oluşturulurken "
            "hata olmamalı."
        )

        category_memory_id = category_memory_result.structured_content["id"]

        wrong_category_results = await _search_memories(
            client,
            terms=["catfiltercanary77"],
            category="technology",
            limit=5,
        )

        wrong_category_ids = [
            memory["id"]
            for memory in wrong_category_results
        ]

        assert category_memory_id not in wrong_category_ids, (
            "Yanlış kategorideki kayıt aramada bulunmamalıdır."
        )

        right_category_results = await _search_memories(
            client,
            terms=["catfiltercanary77"],
            category="decision",
            limit=5,
        )

        right_category_ids = [
            memory["id"]
            for memory in right_category_results
        ]

        assert category_memory_id in right_category_ids, (
            "Doğru kategorideki kayıt aramada bulunmalıdır."
        )

        clean_category_result = await client.call_tool(
            "forget",
            {
                "memory_id": category_memory_id,
            },
        )

        assert not clean_category_result.is_error, (
            "Kategori testi için hafıza silinirken hata olmamalı."
        )

        # Limit testi.
        limit_memory_one_result = await client.call_tool(
            "remember",
            {
                "content": "Limit testi limitcanary birinci kayıt.",
                "category": "technology",
                "importance": 5,
            },
        )

        limit_memory_two_result = await client.call_tool(
            "remember",
            {
                "content": "Limit testi limitcanary ikinci kayıt.",
                "category": "technology",
                "importance": 5,
            },
        )

        assert not limit_memory_one_result.is_error, (
            "Limit testi için hafıza oluşturulurken hata olmamalı."
        )

        assert not limit_memory_two_result.is_error, (
            "Limit testi için hafıza oluşturulurken hata olmamalı."
        )

        limit_memory_one_id = limit_memory_one_result.structured_content["id"]
        limit_memory_two_id = limit_memory_two_result.structured_content["id"]

        limit_one_results = await _search_memories(
            client,
            terms=["limitcanary"],
            limit=1,
        )

        assert len(limit_one_results) == 1, (
            "limit=1 verildiğinde tek sonuç dönülmelidir."
        )

        limit_five_results = await _search_memories(
            client,
            terms=["limitcanary"],
            limit=5,
        )

        limit_five_ids = [
            memory["id"]
            for memory in limit_five_results
        ]

        assert limit_memory_one_id in limit_five_ids, (
            "Limit testi birinci kaydı aramada bulunmalıdır."
        )

        assert limit_memory_two_id in limit_five_ids, (
            "Limit testi ikinci kaydı aramada bulunmalıdır."
        )

        clean_limit_one_result = await client.call_tool(
            "forget",
            {
                "memory_id": limit_memory_one_id,
            },
        )

        clean_limit_two_result = await client.call_tool(
            "forget",
            {
                "memory_id": limit_memory_two_id,
            },
        )

        assert not clean_limit_one_result.is_error, (
            "Limit testi için hafıza silinirken hata olmamalı."
        )

        assert not clean_limit_two_result.is_error, (
            "Limit testi için hafıza silinirken hata olmamalı."
        )

        # Birden fazla terimin OR mantığıyla aranması testi.
        or_memory_one_result = await client.call_tool(
            "remember",
            {
                "content": "OR testi orangecanary meyve kaydı.",
                "category": "technology",
                "importance": 5,
            },
        )

        or_memory_two_result = await client.call_tool(
            "remember",
            {
                "content": "OR testi bananacanary meyve kaydı.",
                "category": "technology",
                "importance": 5,
            },
        )

        assert not or_memory_one_result.is_error, (
            "OR testi için hafıza oluşturulurken hata olmamalı."
        )

        assert not or_memory_two_result.is_error, (
            "OR testi için hafıza oluşturulurken hata olmamalı."
        )

        or_memory_one_id = or_memory_one_result.structured_content["id"]
        or_memory_two_id = or_memory_two_result.structured_content["id"]

        or_results = await _search_memories(
            client,
            terms=["orangecanary", "bananacanary"],
            limit=5,
        )

        or_result_ids = [
            memory["id"]
            for memory in or_results
        ]

        assert or_memory_one_id in or_result_ids, (
            "Birinci terimle eşleşen kayıt OR aramasında bulunmalıdır."
        )

        assert or_memory_two_id in or_result_ids, (
            "İkinci terimle eşleşen kayıt OR aramasında bulunmalıdır."
        )

        single_term_results = await _search_memories(
            client,
            terms=["orangecanary"],
            limit=5,
        )

        single_term_ids = [
            memory["id"]
            for memory in single_term_results
        ]

        assert or_memory_one_id in single_term_ids, (
            "Tek terimle eşleşen kayıt bulunmalıdır."
        )

        assert or_memory_two_id not in single_term_ids, (
            "Tek terimle eşleşmeyen kayıt bulunmamalıdır."
        )

        clean_or_one_result = await client.call_tool(
            "forget",
            {
                "memory_id": or_memory_one_id,
            },
        )

        clean_or_two_result = await client.call_tool(
            "forget",
            {
                "memory_id": or_memory_two_id,
            },
        )

        assert not clean_or_one_result.is_error, (
            "OR testi için hafıza silinirken hata olmamalı."
        )

        assert not clean_or_two_result.is_error, (
            "OR testi için hafıza silinirken hata olmamalı."
        )

        # FTS özel karakterli girdiler hata/crash üretmemeli.
        special_char_results = await _search_memories(
            client,
            terms=['" OR NEAR * - : ^', "catfiltercanary77"],
            limit=5,
        )

        assert isinstance(special_char_results, list), (
            "Özel karakterli girdiler hata vermeden sonuç dönmeli."
        )

        # Boş terimler açık hata vermeli.
        empty_terms_result = await client.call_tool(
            "search_memories",
            {
                "terms": ["   ", ""],
                "limit": 5,
            },
        )

        assert empty_terms_result.is_error, (
            "Tüm terimler boşsa search_memories hata vermelidir."
        )

        missing_terms_result = await client.call_tool(
            "search_memories",
            {
                "terms": [],
                "limit": 5,
            },
        )

        assert missing_terms_result.is_error, (
            "Boş terim listesi search_memories hata vermelidir."
        )


if __name__ == "__main__":
    # Test başlamadan önce production veritabanının durumunu kaydeder.
    production_db_before = _file_state(DATABASE_PATH)

    try:
        asyncio.run(main())
    finally:
        # Test bitince ortam değişkenini temizler ve
        # geçici test veritabanını siler.
        os.environ.pop("PROJECT_MEMORY_DB_PATH", None)
        _TEMP_DB_DIR.cleanup()

    # Testler bittikten sonra production veritabanının
    # değişmediğini doğrular.
    production_db_after = _file_state(DATABASE_PATH)

    assert production_db_before == production_db_after, (
        "Production veritabanı test sırasında değiştirilmemelidir: "
        f"{DATABASE_PATH}"
    )

    print(f"Production database değişmedi: {DATABASE_PATH}")
