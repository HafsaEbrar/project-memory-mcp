import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


# Bu dosyanın bulunduğu klasör:
# project-memory-mcp/project_memory/
PACKAGE_DIR = Path(__file__).resolve().parent

# Projenin ana klasörü:
# project-memory-mcp/
BASE_DIR = PACKAGE_DIR.parent

# SQLite dosyasını saklayacağımız klasör:
# project-memory-mcp/data/
DATA_DIR = BASE_DIR / "data"

# Veritabanı dosyasının tam yolu:
# project-memory-mcp/data/memories.db
DATABASE_PATH = DATA_DIR / "memories.db"


def create_connection() -> sqlite3.Connection:
    """
    SQLite veritabanına yeni bir bağlantı oluşturur.

    Her çağrıldığında yeni bir bağlantı döndürür.
    """

    # data klasörü yoksa otomatik oluşturur.
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
    )

    # Sorgu sonuçlarına sütun adıyla erişmemizi sağlar.
    # Örneğin: row["content"]
    connection.row_factory = sqlite3.Row

    # SQLite'ta foreign key kontrolü varsayılan olarak kapalıdır.
    connection.execute("PRAGMA foreign_keys = ON;")

    return connection


@contextmanager
def get_database() -> Generator[sqlite3.Connection, None, None]:
    """
    Veritabanı bağlantısını güvenli şekilde yönetir.

    İşlem başarılıysa commit yapar.
    Hata oluşursa rollback yapar.
    Her durumda bağlantıyı kapatır.
    """

    connection = create_connection()

    try:
        yield connection
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def initialize_database() -> None:
    """
    Proje için gerekli tabloları ve indeksleri oluşturur.

    Tablolar zaten varsa tekrar oluşturmaz.
    """

    with get_database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                root_path TEXT NOT NULL UNIQUE,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );


            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                project_id INTEGER NOT NULL,

                content TEXT NOT NULL,

                category TEXT NOT NULL CHECK (
                    category IN (
                        'decision',
                        'architecture',
                        'technology',
                        'error_solution',
                        'todo',
                        'preference',
                        'session_summary'
                    )
                ),

                importance INTEGER NOT NULL DEFAULT 5 CHECK (
                    importance BETWEEN 1 AND 10
                ),

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE
            );


            CREATE INDEX IF NOT EXISTS idx_memories_project_id
            ON memories(project_id);


            CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories(category);


            CREATE INDEX IF NOT EXISTS idx_memories_importance
            ON memories(importance);
            """
        )


def database_health_check() -> bool:
    """
    SQLite bağlantısının çalışıp çalışmadığını kontrol eder.
    """

    try:
        with get_database() as connection:
            result = connection.execute("SELECT 1").fetchone()

        return result is not None and result[0] == 1

    except sqlite3.Error:
        return False


if __name__ == "__main__":
    initialize_database()

    if database_health_check():
        print(f"Veritabanı hazır: {DATABASE_PATH}")
    else:
        print("Veritabanı bağlantısı kurulamadı.")