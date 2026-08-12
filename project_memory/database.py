import os
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

# Veritabanı dosyasının varsayılan (production) tam yolu:
# project-memory-mcp/data/memories.db
DATABASE_PATH = DATA_DIR / "memories.db"

# Testlerde geçici bir veritabanı kullanmak istenirse
# bu ortam değişkeniyle veritabanı yolu değiştirilebilir.
DB_PATH_ENV = "PROJECT_MEMORY_DB_PATH"


def get_database_path() -> Path:
    """
    Kullanılacak SQLite veritabanı dosyasının yolunu döndürür.

    PROJECT_MEMORY_DB_PATH ortam değişkeni ayarlanmışsa
    bu dosya kullanılır. Aksi halde varsayılan production
    yolu (data/memories.db) kullanılır.
    """

    environment_path = os.environ.get(DB_PATH_ENV)

    if environment_path:
        return Path(environment_path)

    return DATABASE_PATH


def create_connection() -> sqlite3.Connection:
    """
    SQLite veritabanına yeni bir bağlantı oluşturur.

    Her çağrıldığında yeni bir bağlantı döndürür.
    """

    database_path = get_database_path()

    # Veritabanı dosyasının bulunduğu klasör yoksa otomatik oluşturur.
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        database_path,
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

                scope TEXT NOT NULL DEFAULT 'shared' CHECK (
                    scope IN ('shared', 'user')
                ),

                owner_id TEXT,

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


            -- Anahtar/değer deposu.
            -- FTS indeksinin hangi şema sürümüyle oluşturulduğunu
            -- hatırlamak için kullanılır.
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );


            -- FTS5 arama indeksi.
            --
            -- Yalnızca memories.content alanını indeksler.
            -- external-content yaklaşımı kullanır:
            --   * content='memories'   -> asıl metin memories tablosunda durur
            --   * content_rowid='id'   -> memories.id ile eşleşir
            --
            -- memories tablosu ana veri kaynağı olmaya devam eder.
            -- memories_fts yalnızca hızlı tam metin araması için kullanılır.
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                content='memories',
                content_rowid='id',
                tokenize='unicode61'
            );


            -- FTS indeksini memories tablosuyla senkron tutan trigger'lar.
            --
            -- Yalnızca content alanı değiştiğinde tetiklenir.
            -- Sadece category veya importance değişirse FTS indeksi
            -- gereksiz yere yeniden oluşturulmaz.

            CREATE TRIGGER IF NOT EXISTS memories_ai
            AFTER INSERT ON memories
            BEGIN
                INSERT INTO memories_fts (rowid, content)
                VALUES (new.id, new.content);
            END;


            CREATE TRIGGER IF NOT EXISTS memories_ad
            AFTER DELETE ON memories
            BEGIN
                INSERT INTO memories_fts (memories_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END;


            CREATE TRIGGER IF NOT EXISTS memories_au
            AFTER UPDATE OF content ON memories
            BEGIN
                INSERT INTO memories_fts (memories_fts, rowid, content)
                VALUES ('delete', old.id, old.content);

                INSERT INTO memories_fts (rowid, content)
                VALUES (new.id, new.content);
            END;
            """
        )

        _migrate_memory_ownership(connection)

        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_memories_project_scope_owner
            ON memories(project_id, scope, owner_id);
            """
        )

        _sync_fts_index(connection)


def _migrate_memory_ownership(connection: sqlite3.Connection) -> None:
    """Eski memories tablolarına kayıpsız scope/owner alanları ekler."""

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(memories)").fetchall()
    }

    if "scope" not in columns:
        connection.execute(
            "ALTER TABLE memories "
            "ADD COLUMN scope TEXT NOT NULL DEFAULT 'shared'"
        )

    if "owner_id" not in columns:
        connection.execute("ALTER TABLE memories ADD COLUMN owner_id TEXT")


# FTS indeks şemasının sürüm numarası.
#
# FTS tablosunun yapısı veya tokenizer ayarı değiştiğinde bu değer
# artırılır. Sürüm eşleşmediğinde indeks, memories tablosunun tamamından
# yeniden oluşturulur.
FTS_SCHEMA_VERSION = "1"


def _get_meta_value(
    connection: sqlite3.Connection,
    key: str,
) -> str | None:
    """
    meta tablosundan tek bir anahtarın değerini okur.
    """

    row = connection.execute(
        "SELECT value FROM meta WHERE key = ?",
        (key,),
    ).fetchone()

    return row[0] if row is not None else None


def _set_meta_value(
    connection: sqlite3.Connection,
    key: str,
    value: str,
) -> None:
    """
    meta tablosuna bir anahtar/değer yazar veya mevcut değeri günceller.
    """

    connection.execute(
        """
        INSERT INTO meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE
        SET value = excluded.value
        """,
        (key, value),
    )


def _sync_fts_index(connection: sqlite3.Connection) -> None:
    """
    FTS indeksini gerekirse memories tablosundan yeniden oluşturur.

    meta tablosunda saklanan FTS şema sürümü, mevcut FTS_SCHEMA_VERSION
    değeriyle eşleşmiyorsa indeks rebuild edilir ve sürüm güncellenir.

    Not: memories_fts dışsal içerikli (external-content) bir tablo
    olduğu için "SELECT COUNT(*) FROM memories_fts" satır sayısını
    memories tablosundan döndürür; bu yüzden senkron durumu satır
    sayısıyla anlaşılamaz. Sürüm işareti bu sorunu ortadan kaldırır.

    Bu sayede FTS indeksi eklenmeden önce kaydedilmiş eski hafıza
    kayıtları da indekslenir; kullanıcının memories.db dosyasını
    silmesi gerekmez.
    """

    current_version = _get_meta_value(
        connection,
        "fts_schema_version",
    )

    if current_version == FTS_SCHEMA_VERSION:
        return

    connection.execute(
        "INSERT INTO memories_fts (memories_fts) VALUES ('rebuild')"
    )

    _set_meta_value(
        connection,
        "fts_schema_version",
        FTS_SCHEMA_VERSION,
    )


def rebuild_fts_index() -> None:
    """
    FTS indeksini memories tablosunun tamamından yeniden oluşturur.

    Senkronu bozan durumlarda (ör. trigger'ların devreye giremediği
    bir durum) arama indeksini sıfırdan eski haline getirmek için
    kullanılabilir.
    """

    with get_database() as connection:
        connection.execute(
            "INSERT INTO memories_fts (memories_fts) VALUES ('rebuild')"
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
        print(f"Veritabanı hazır: {get_database_path()}")
    else:
        print("Veritabanı bağlantısı kurulamadı.")
