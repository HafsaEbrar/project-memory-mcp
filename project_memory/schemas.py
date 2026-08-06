from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MemoryCategory(str, Enum):
    """
    Hafızaya kaydedilebilecek bilgi kategorileri.

    Enum kullanarak kategori isimlerinin rastgele
    yazılmasını engelliyoruz.
    """

    DECISION = "decision"
    ARCHITECTURE = "architecture"
    TECHNOLOGY = "technology"
    ERROR_SOLUTION = "error_solution"
    TODO = "todo"
    PREFERENCE = "preference"
    SESSION_SUMMARY = "session_summary"


class ProjectContext(BaseModel):
    """
    Coding agent'ın açık olduğu aktif projeyi temsil eder.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(
        min_length=1,
        max_length=120,
        description="Aktif projenin adı",
    )

    root_path: str = Field(
        min_length=1,
        max_length=1000,
        description="Aktif projenin tam klasör yolu",
    )


class MemoryCreate(BaseModel):
    """
    Yeni bir hafıza oluşturulurken gereken bilgiler.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    content: str = Field(
        min_length=3,
        max_length=3000,
        description="Gelecekte hatırlanması gereken bilgi",
    )

    category: MemoryCategory = Field(
        description="Hafızanın kategorisi",
    )

    importance: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Bilginin 1 ile 10 arasındaki önem seviyesi",
    )


class MemoryUpdate(BaseModel):
    """
    Daha önce kaydedilmiş bir hafızayı güncellemek
    için kullanılır.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    content: str | None = Field(
        default=None,
        min_length=3,
        max_length=3000,
    )

    category: MemoryCategory | None = None

    importance: int | None = Field(
        default=None,
        ge=1,
        le=10,
    )


class MemorySearchRequest(BaseModel):
    """
    Hafızalarda arama yaparken kullanılan bilgiler.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Hafızalarda aranacak ifade",
    )

    category: MemoryCategory | None = Field(
        default=None,
        description="İsteğe bağlı kategori filtresi",
    )

    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="En fazla kaç sonuç döndürüleceği",
    )


class ProjectRecord(BaseModel):
    """
    SQLite veritabanından okunan tam proje kaydı.
    """

    id: int
    name: str
    root_path: str
    created_at: datetime
    updated_at: datetime


class MemoryRecord(BaseModel):
    """
    SQLite veritabanından okunan tam hafıza kaydı.
    """

    id: int
    project_id: int
    content: str
    category: MemoryCategory
    importance: int
    created_at: datetime
    updated_at: datetime


class ProjectContextResponse(BaseModel):
    """
    get_project_context MCP aracının döndüreceği sonuç.
    """

    project: ProjectRecord
    total_memories: int
    memories: list[MemoryRecord]