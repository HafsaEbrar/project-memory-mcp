from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def at_least_one_field_must_be_set(self) -> "MemoryUpdate":
        """
        Güncelleme yapılırken en az bir alanın değiştirilmesini zorlar.
        """

        if (
            self.content is None
            and self.category is None
            and self.importance is None
        ):
            raise ValueError(
                "Güncellenecek alan bulunamadı. "
                "content, category veya importance "
                "alanlarından en az biri verilmelidir."
            )

        return self


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


class MemoryIndexedSearchRequest(BaseModel):
    """
    SQLite FTS5 tabanlı indeksli arama için kullanılan bilgiler.

    Terimler OR mantığıyla aranır; yani verilen terimlerden en az biriyle
    eşleşen hafızalar sonuca dahil edilir. Semantik anlam eşleşmesi
    yapılmaz, yalnızca kelime/terim indekslemesi kullanılır.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    terms: list[str] = Field(
        min_length=1,
        max_length=20,
        description=(
            "Hafızalarda aranacak kelime veya terimler. "
            "Terimlerden en az biriyle eşleşen hafızalar bulunur (OR)."
        ),
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

    @model_validator(mode="after")
    def clean_and_validate_terms(self) -> "MemoryIndexedSearchRequest":
        """
        Her terimi temizler ve boş terimleri çıkarır.

        Tüm terimler boşsa açık bir hata verir.
        """

        cleaned_terms: list[str] = []

        for term in self.terms:
            cleaned_term = term.strip()
            if cleaned_term:
                cleaned_terms.append(cleaned_term)

        if not cleaned_terms:
            raise ValueError(
                "En az bir geçerli arama terimi verilmelidir. "
                "Boş terimler arama için kabul edilmez."
            )

        self.terms = cleaned_terms
        return self


class MemoryListRequest(BaseModel):
    """
    Hafızaları listelerken kullanılan bilgiler.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    category: MemoryCategory | None = Field(
        default=None,
        description="İsteğe bağlı kategori filtresi",
    )

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="En fazla kaç sonuç döndürüleceği",
    )


class ProjectContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=100)


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


class MemorySearchResult(BaseModel):
    """
    FTS5 tabanlı indeksli aramadan dönen tek bir sonuç.

    rank alanı bm25() işlevinin döndürdüğü sıralama puanıdır.
    DİKKAT: FTS5 bm25() değerinde DÜŞÜK (küçük) değer daha iyi sonuç
    anlamına gelir. Yani rank ne kadar küçükse eşleşme o kadar iyidir.
    """

    memory: MemoryRecord

    rank: float = Field(
        description=(
            "FTS5 bm25() sıralama puanı. Düşük değer daha iyi eşleşme demektir."
        ),
    )


class ProjectContextResponse(BaseModel):
    project: ProjectRecord
    total_memories: int
    memories: list[MemoryRecord]


class ProjectContextResponse(BaseModel):
    """
    get_project_context MCP aracının döndüreceği sonuç.
    """

    project: ProjectRecord
    total_memories: int
    memories: list[MemoryRecord]
