import sqlite3

from project_memory.database import get_database, initialize_database
from project_memory.schemas import (
    MemoryCreate,
    MemoryRecord,
    MemorySearchRequest,
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