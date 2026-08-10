import sqlite3

from project_memory.database import get_database, initialize_database
from project_memory.schemas import (
    MemoryCreate,
    MemoryIndexedSearchRequest,
    MemoryListRequest,
    MemoryRecord,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryUpdate,
    ProjectContext,
    ProjectRecord,
)


class MemoryService:
    """
    Proje ve hafıza işlemlerinin iş mantığını yönetir.

    MCP araçları doğrudan SQL sorgusu çalıştırmak yerine
    bu servisteki metotları kullanacak.
    """

    def __init__(self) -> None:
        """
        Servis oluşturulduğunda veritabanı tablolarının
        hazır olduğundan emin olur.
        """

        initialize_database()

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> ProjectRecord:
        """
        SQLite satırını ProjectRecord modeline dönüştürür.
        """

        return ProjectRecord.model_validate(dict(row))

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> MemoryRecord:
        """
        SQLite satırını MemoryRecord modeline dönüştürür.
        """

        return MemoryRecord.model_validate(dict(row))

    def get_or_create_project(
        self,
        context: ProjectContext,
    ) -> ProjectRecord:
        """
        Projeyi root_path değerine göre arar.

        Proje daha önce kaydedilmişse mevcut kaydı döndürür.
        Kayıtlı değilse yeni proje oluşturur.
        """

        with get_database() as connection:
            project_row = connection.execute(
                """
                SELECT
                    id,
                    name,
                    root_path,
                    created_at,
                    updated_at
                FROM projects
                WHERE root_path = ?
                """,
                (context.root_path,),
            ).fetchone()

            if project_row is not None:
                return self._project_from_row(project_row)

            cursor = connection.execute(
                """
                INSERT INTO projects (
                    name,
                    root_path
                )
                VALUES (?, ?)
                """,
                (
                    context.name,
                    context.root_path,
                ),
            )

            created_project_row = connection.execute(
                """
                SELECT
                    id,
                    name,
                    root_path,
                    created_at,
                    updated_at
                FROM projects
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        if created_project_row is None:
            raise RuntimeError(
                "Proje oluşturuldu ancak tekrar okunamadı."
            )

        return self._project_from_row(created_project_row)

    def remember(
        self,
        context: ProjectContext,
        memory: MemoryCreate,
    ) -> MemoryRecord:
        """
        Aktif projeye yeni bir hafıza kaydeder.

        Aynı projede aynı içerik ve kategori daha önce kayıtlıysa
        yeni kayıt oluşturmak yerine mevcut kaydı döndürür.
        """

        project = self.get_or_create_project(context)

        with get_database() as connection:
            existing_memory_row = connection.execute(
                """
                SELECT
                    id,
                    project_id,
                    content,
                    category,
                    importance,
                    created_at,
                    updated_at
                FROM memories
                WHERE project_id = ?
                  AND content = ?
                  AND category = ?
                """,
                (
                    project.id,
                    memory.content,
                    memory.category.value,
                ),
            ).fetchone()

            if existing_memory_row is not None:
                return self._memory_from_row(existing_memory_row)

            cursor = connection.execute(
                """
                INSERT INTO memories (
                    project_id,
                    content,
                    category,
                    importance
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    project.id,
                    memory.content,
                    memory.category.value,
                    memory.importance,
                ),
            )

            created_memory_row = connection.execute(
                """
                SELECT
                    id,
                    project_id,
                    content,
                    category,
                    importance,
                    created_at,
                    updated_at
                FROM memories
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        if created_memory_row is None:
            raise RuntimeError(
                "Hafıza oluşturuldu ancak tekrar okunamadı."
            )

        return self._memory_from_row(created_memory_row)

    def recall(
        self,
        context: ProjectContext,
        search: MemorySearchRequest,
    ) -> list[MemoryRecord]:
        """
        Aktif projeye ait hafızalarda metin araması yapar.

        Sonuçlar önce önem puanına, sonra güncellenme
        tarihine göre sıralanır.
        """

        project = self.get_or_create_project(context)

        sql = """
            SELECT
                id,
                project_id,
                content,
                category,
                importance,
                created_at,
                updated_at
            FROM memories
            WHERE project_id = ?
              AND LOWER(content) LIKE LOWER(?)
        """

        parameters: list[object] = [
            project.id,
            f"%{search.query}%",
        ]

        if search.category is not None:
            sql += """
              AND category = ?
            """
            parameters.append(search.category.value)

        sql += """
            ORDER BY
                importance DESC,
                updated_at DESC
            LIMIT ?
        """

        parameters.append(search.limit)

        with get_database() as connection:
            memory_rows = connection.execute(
                sql,
                tuple(parameters),
            ).fetchall()

        return [
            self._memory_from_row(row)
            for row in memory_rows
        ]

    @staticmethod
    def _fts_phrase(term: str) -> str:
        """
        Arama terimini FTS5 sorgusu için güvenli bir tırnaklı ifadeye çevirir.

        Terim, FTS5 sorgu sözdizimi özel karakterlerinden arındırılmadan
        doğrudan sorguya eklenmez. Terim çift tırnak içine alınır ve içindeki
        çift tırnaklar FTS5 kurallarına göre ikiye katlanır. Bu sayede kullanıcı
        girdisi tehlikeli FTS5 sorgusu üretemez; girdi yalnızca bir sözcük
        (phrase) olarak ele alınır.
        """

        return f'"{term.replace(chr(34), chr(34) * 2)}"'

    def search_memories(
        self,
        context: ProjectContext,
        search: MemoryIndexedSearchRequest,
    ) -> list[MemorySearchResult]:
        """
        Aktif projeye ait hafızalarda FTS5 tabanlı indeksli arama yapar.

        Verilen terimler OR mantığıyla aranır: terimlerden en az biriyle
        eşleşen hafıza kayıtları sonuca dahil edilir.

        Sıralama:
        1. bm25() puanı (küçük değer daha iyi eşleşmedir)
        2. eşitlik durumunda importance DESC
        3. son olarak updated_at DESC

        Bu arama semantik embedding kullanmaz; yalnızca kelime/terim
        indekslemesi yapar.
        """

        project = self.get_or_create_project(context)

        # Her terimi FTS5 için güvenli hale getirir ve OR ile birleştirir.
        match_query = " OR ".join(
            self._fts_phrase(term)
            for term in search.terms
        )

        sql = """
            SELECT
                m.id,
                m.project_id,
                m.content,
                m.category,
                m.importance,
                m.created_at,
                m.updated_at,
                bm25(memories_fts) AS rank
            FROM memories_fts
            JOIN memories AS m
              ON m.id = memories_fts.rowid
            WHERE memories_fts MATCH ?
              AND m.project_id = ?
        """

        parameters: list[object] = [
            match_query,
            project.id,
        ]

        if search.category is not None:
            sql += """
              AND m.category = ?
            """
            parameters.append(search.category.value)

        sql += """
            ORDER BY
                rank,
                m.importance DESC,
                m.updated_at DESC
            LIMIT ?
        """

        parameters.append(search.limit)

        with get_database() as connection:
            memory_rows = connection.execute(
                sql,
                tuple(parameters),
            ).fetchall()

        results: list[MemorySearchResult] = []

        for row in memory_rows:
            row_dict = dict(row)
            rank = row_dict.pop("rank")

            results.append(
                MemorySearchResult(
                    memory=self._memory_from_row(row_dict),
                    rank=rank,
                )
            )

        return results

    def update_memory(
        self,
        context: ProjectContext,
        memory_id: int,
        update: MemoryUpdate,
    ) -> MemoryRecord:
        """
        Aktif projeye ait bir hafıza kaydını günceller.

        Yalnızca aktif projeye ait hafızalar güncellenebilir.
        Güncellenecek hafıza başka bir projeye aitse veya
        hiç yoksa açık bir hata verir. Güncelleme sırasında
        updated_at değeri güncellenir.
        """

        project = self.get_or_create_project(context)

        set_clauses: list[str] = []
        parameters: list[object] = []

        if update.content is not None:
            set_clauses.append("content = ?")
            parameters.append(update.content)

        if update.category is not None:
            set_clauses.append("category = ?")
            parameters.append(update.category.value)

        if update.importance is not None:
            set_clauses.append("importance = ?")
            parameters.append(update.importance)

        if not set_clauses:
            raise ValueError(
                "Güncellenecek alan bulunamadı. "
                "content, category veya importance "
                "alanlarından en az biri verilmelidir."
            )

        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

        parameters.append(memory_id)
        parameters.append(project.id)

        with get_database() as connection:
            cursor = connection.execute(
                f"""
                UPDATE memories
                SET {", ".join(set_clauses)}
                WHERE id = ?
                  AND project_id = ?
                """,
                tuple(parameters),
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Güncellenecek hafıza kaydı bulunamadı. "
                    "Hafızalar yalnızca kendi projeleri "
                    "içinden güncellenebilir."
                )

            updated_memory_row = connection.execute(
                """
                SELECT
                    id,
                    project_id,
                    content,
                    category,
                    importance,
                    created_at,
                    updated_at
                FROM memories
                WHERE id = ?
                  AND project_id = ?
                """,
                (memory_id, project.id),
            ).fetchone()

        if updated_memory_row is None:
            raise RuntimeError(
                "Hafıza güncellendi ancak tekrar okunamadı."
            )

        return self._memory_from_row(updated_memory_row)

    def forget_memory(
        self,
        context: ProjectContext,
        memory_id: int,
    ) -> MemoryRecord:
        """
        Aktif projeye ait bir hafıza kaydını kalıcı olarak siler.

        Yalnızca aktif projeye ait hafızalar silinebilir.
        Silinecek hafıza başka bir projeye aitse veya
        hiç yoksa açık bir hata verir.

        Silmeden önce kaydı okuyarak silinen hafızanın
        bilgilerini MemoryRecord olarak saklar ve işlem
        başarılıysa bu kaydı geri döndürür.

        Not: Silme işlemi geri alınamaz.
        """

        project = self.get_or_create_project(context)

        with get_database() as connection:
            memory_row = connection.execute(
                """
                SELECT
                    id,
                    project_id,
                    content,
                    category,
                    importance,
                    created_at,
                    updated_at
                FROM memories
                WHERE id = ?
                  AND project_id = ?
                """,
                (memory_id, project.id),
            ).fetchone()

            if memory_row is None:
                raise ValueError(
                    "Silinecek hafıza kaydı bulunamadı. "
                    "Hafızalar yalnızca kendi projeleri "
                    "içinden silinebilir."
                )

            connection.execute(
                """
                DELETE FROM memories
                WHERE id = ?
                  AND project_id = ?
                """,
                (memory_id, project.id),
            )

        return self._memory_from_row(memory_row)

    def list_memories(
        self,
        context: ProjectContext,
        list_request: MemoryListRequest,
    ) -> list[MemoryRecord]:
        """
        Aktif projeye ait hafızaları listeler.

        Kategori verilmişse yalnızca o kategorideki
        hafızalar döndürülür. Sonuçlar önce önem puanına,
        sonra güncellenme tarihine göre sıralanır.
        """

        project = self.get_or_create_project(context)

        sql = """
            SELECT
                id,
                project_id,
                content,
                category,
                importance,
                created_at,
                updated_at
            FROM memories
            WHERE project_id = ?
        """

        parameters: list[object] = [project.id]

        if list_request.category is not None:
            sql += """
              AND category = ?
            """
            parameters.append(list_request.category.value)

        sql += """
            ORDER BY
                importance DESC,
                updated_at DESC
            LIMIT ?
        """

        parameters.append(list_request.limit)

        with get_database() as connection:
            memory_rows = connection.execute(
                sql,
                tuple(parameters),
            ).fetchall()

        return [
            self._memory_from_row(row)
            for row in memory_rows
        ]