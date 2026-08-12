from typing import TypeAlias

from project_memory.memory_service import MemoryService
from project_memory.project_resolver import resolve_project_context
from project_memory.schemas import (
    MemoryCreate,
    MemoryIndexedSearchRequest,
    MemoryListRequest,
    MemorySearchRequest,
    MemoryUpdate,
    ProjectContextRequest,
)


# MCP araçlarının döndüreceği tek bir hafıza kaydının tipi.
# Hafıza kayıtlarında metin ve sayı değerleri bulunur.
MemoryToolResult: TypeAlias = dict[str, object]


# Hafıza servisini bir kez oluşturuyoruz.
# MemoryService başlatıldığında SQLite tablolarının
# hazır olduğundan emin olunur.
memory_service = MemoryService()


def normalize_category(category: str | None) -> str | None:
    """
    MCP istemcisinden gelen kategori değerini temizler.

    Örnek dönüşümler:
        " technology "   -> "technology"
        "TECHNOLOGY"     -> "technology"
        '"technology"'   -> "technology"
        ""               -> None
        None             -> None
    """

    if category is None:
        return None

    cleaned_category = category.strip()

    # Inspector kategori değerini bazen tırnaklı gönderebilir.
    # Baştaki ve sondaki tırnakları temizler.
    if (
        len(cleaned_category) >= 2
        and cleaned_category[0] == cleaned_category[-1]
        and cleaned_category[0] in {'"', "'"}
    ):
        cleaned_category = cleaned_category[1:-1].strip()

    cleaned_category = cleaned_category.lower()

    # Boş metni None değerine dönüştürür.
    # Recall işleminde None, kategori filtresi uygulanmayacağı anlamına gelir.
    return cleaned_category or None


def normalize_owner_id(owner_id: str | None) -> str | None:
    if owner_id is None:
        return None
    cleaned_owner_id = owner_id.strip()
    return cleaned_owner_id or None


def remember_memory(
    content: str,
    category: str,
    importance: int = 5,
    scope: str = "shared",
) -> MemoryToolResult:
    """
    Aktif projeye kalıcı bir hafıza kaydeder.

    Args:
        content:
            Gelecekte hatırlanması gereken proje bilgisi.

        category:
            Hafızanın kategorisi. Geçerli kategoriler:
            decision, architecture, technology, error_solution,
            todo, preference ve session_summary.

        importance:
            Bilginin 1 ile 10 arasındaki önem seviyesi.

    Returns:
        Oluşturulan veya daha önce mevcut olan hafıza kaydı.
    """

    # OpenCode veya başka bir MCP istemcisinin
    # çalıştığı aktif proje klasörünü bulur.
    context = resolve_project_context()

    # İçeriğin başındaki ve sonundaki gereksiz
    # boşlukları temizler.
    normalized_content = content.strip()

    # Kategori değerini standart biçime dönüştürür.
    normalized_category = normalize_category(category)

    # remember işleminde kategori zorunludur.
    if normalized_category is None:
        raise ValueError(
            "Kategori boş bırakılamaz. "
            "Geçerli kategoriler: decision, architecture, technology, "
            "error_solution, todo, preference, session_summary."
        )

    # Temizlenmiş verileri Pydantic modeliyle doğrular.
    memory = MemoryCreate(
        content=normalized_content,
        category=normalized_category,
        importance=importance,
        scope=scope.strip().lower(),
    )

    # Doğrulanan hafızayı SQLite veritabanına kaydeder.
    result = memory_service.remember(
        context=context,
        memory=memory,
    )

    # Pydantic modelini MCP tarafından gönderilebilecek
    # JSON uyumlu bir sözlüğe dönüştürür.
    return result.model_dump(mode="json")


def recall_memories(
    query: str,
    category: str | None = None,
    limit: int = 5,
    owner_id: str | None = None,
) -> list[MemoryToolResult]:
    """
    Aktif projeye ait hafızalarda arama yapar.

    Args:
        query:
            Hafıza içeriklerinde aranacak kelime veya ifade.

        category:
            İsteğe bağlı kategori filtresi.
            Boş bırakılırsa bütün kategorilerde arama yapılır.

        limit:
            Döndürülecek en fazla sonuç sayısı.

    Returns:
        Arama ifadesiyle eşleşen hafıza kayıtları.
    """

    # Aktif proje klasörünü otomatik olarak bulur.
    context = resolve_project_context()

    # Arama ifadesinin başındaki ve sonundaki
    # gereksiz boşlukları temizler.
    normalized_query = query.strip()

    # Boş sorguların veritabanına gönderilmesini engeller.
    if not normalized_query:
        raise ValueError("Arama ifadesi boş bırakılamaz.")

    # Kategori verilmişse temizler.
    # Boş bırakılmışsa None döner ve kategori filtresi uygulanmaz.
    normalized_category = normalize_category(category)

    # Arama parametrelerini Pydantic modeliyle doğrular.
    search = MemorySearchRequest(
        query=normalized_query,
        category=normalized_category,
        limit=limit,
        owner_id=normalize_owner_id(owner_id),
    )

    # SQLite üzerinde hafıza araması yapar.
    results = memory_service.recall(
        context=context,
        search=search,
    )

    # Hafıza modellerini MCP için JSON uyumlu
    # sözlüklere dönüştürür.
    return [
        memory.model_dump(mode="json")
        for memory in results
    ]


def search_memories(
    terms: list[str],
    category: str | None = None,
    limit: int = 5,
    owner_id: str | None = None,
) -> list[dict[str, object]]:
    """
    Aktif projeye ait hafızalarda SQLite FTS5 tabanlı indeksli arama yapar.

    Verilen terimler OR mantığıyla aranır; terimlerden en az biriyle
    eşleşen hafızalar sonuca dahil edilir. Semantik embedding modeli
    kullanılmaz, yalnızca kelime/terim indekslemesi yapılır.

    Args:
        terms:
            Hafızalarda aranacak kelime veya terimler. En az bir
            geçerli (boş olmayan) terim verilmelidir.

        category:
            İsteğe bağlı kategori filtresi.
            Boş bırakılırsa bütün kategorilerde arama yapılır.

        limit:
            Döndürülecek en fazla sonuç sayısı.

    Returns:
        Sıralanmış arama sonuçları. Her sonuç, hafıza kaydı bilgilerine
        ek olarak bm25() sıralama puanını taşıyan "rank" alanını içerir.
        DİKKAT: rank değeri düşükse eşleşme o kadar iyidir.

    Raises:
        ValueError:
            Hiçbir geçerli arama terimi verilmezse.
    """

    # Aktif proje klasörünü otomatik olarak bulur.
    context = resolve_project_context()

    # Kategori verilmişse temizler.
    normalized_category = normalize_category(category)

    # Terimlerin başındaki ve sonundaki gereksiz boşlukları temizler,
    # boş kalan terimleri listeden çıkarır.
    cleaned_terms = [
        term.strip()
        for term in terms
        if term.strip()
    ]

    # Hiç geçerli terim kalmazsa açık hata verir.
    if not cleaned_terms:
        raise ValueError(
            "Arama için en az bir geçerli terim verilmelidir. "
            "Boş terimler kabul edilmez."
        )

    # Arama parametrelerini Pydantic modeliyle doğrular.
    search = MemoryIndexedSearchRequest(
        terms=cleaned_terms,
        category=normalized_category,
        limit=limit,
        owner_id=normalize_owner_id(owner_id),
    )

    # FTS5 indeksi üzerinde hafıza araması yapar.
    results = memory_service.search_memories(
        context=context,
        search=search,
    )

    # Her sonucu MCP için JSON uyumlu bir sözlüğe dönüştürür.
    # rank alanı hafıza bilgileriyle aynı sözlükte döndürülür.
    return [
        {
            "rank": result.rank,
            **result.memory.model_dump(mode="json"),
        }
        for result in results
    ]


def update_memory(
    memory_id: int,
    content: str | None = None,
    category: str | None = None,
    importance: int | None = None,
) -> MemoryToolResult:
    """
    Aktif projeye ait bir hafızayı günceller.

    Args:
        memory_id:
            Güncellenecek hafıza kaydının kimliği.

        content:
            İsteğe bağlı yeni içerik.

        category:
            İsteğe bağlı yeni kategori. Geçerli kategoriler:
            decision, architecture, technology, error_solution,
            todo, preference ve session_summary.

        importance:
            İsteğe bağlı yeni önem seviyesi (1 ile 10 arası).

    Returns:
        Güncellenen hafıza kaydı.

    Raises:
        ValueError:
            Hiçbir alan verilmezse veya hafıza kaydı
            aktif projede bulunamazsa.
    """

    # Aktif proje klasörünü otomatik olarak bulur.
    context = resolve_project_context()

    # Yalnızca verilen alanları temizler.
    # Verilmeyen alanlar None kalır ve güncellenmez.
    normalized_content = (
        content.strip()
        if content is not None
        else None
    )

    normalized_category = normalize_category(category)

    # Güncelleme parametrelerini Pydantic modeliyle doğrular.
    # En az bir alan verilmediğinde model hata verir.
    update = MemoryUpdate(
        content=normalized_content,
        category=normalized_category,
        importance=importance,
    )

    # SQLite üzerinde aktif projeye ait hafızayı günceller.
    result = memory_service.update_memory(
        context=context,
        memory_id=memory_id,
        update=update,
    )

    # Pydantic modelini MCP tarafından gönderilebilecek
    # JSON uyumlu bir sözlüğe dönüştürür.
    return result.model_dump(mode="json")


def forget_memory(
    memory_id: int,
) -> MemoryToolResult:
    """
    Aktif projeye ait bir hafızayı kalıcı olarak siler.

    Args:
        memory_id:
            Silinecek hafıza kaydının kimliği.
            Pozitif bir tam sayı olmalıdır.

    Returns:
        Silinen hafıza kaydı.

    Raises:
        ValueError:
            memory_id pozitif bir tam sayı değilse
            veya hafıza kaydı aktif projede bulunamazsa.
    """

    # Silinecek kaydın kimliği pozitif bir tam sayı olmalıdır.
    if (
        isinstance(memory_id, bool)
        or not isinstance(memory_id, int)
        or memory_id <= 0
    ):
        raise ValueError(
            "memory_id pozitif bir tam sayı olmalıdır."
        )

    # Aktif proje klasörünü otomatik olarak bulur.
    context = resolve_project_context()

    # SQLite üzerinde aktif projeye ait hafızayı siler.
    result = memory_service.forget_memory(
        context=context,
        memory_id=memory_id,
    )

    # Pydantic modelini MCP tarafından gönderilebilecek
    # JSON uyumlu bir sözlüğe dönüştürür.
    return result.model_dump(mode="json")


def list_memories(
    category: str | None = None,
    limit: int = 20,
    owner_id: str | None = None,
) -> list[MemoryToolResult]:
    """
    Aktif projeye ait hafızaları listeler.

    Args:
        category:
            İsteğe bağlı kategori filtresi.
            Boş bırakılırsa bütün kategorilerdeki
            hafızalar listelenir.

        limit:
            Döndürülecek en fazla sonuç sayısı.

    Returns:
        Önem ve güncellenme tarihine göre sıralanmış
        hafıza kayıtları.
    """

    # Aktif proje klasörünü otomatik olarak bulur.
    context = resolve_project_context()

    # Kategori verilmişse temizler.
    # Boş bırakılmışsa None döner ve kategori filtresi uygulanmaz.
    normalized_category = normalize_category(category)

    # Liste parametrelerini Pydantic modeliyle doğrular.
    list_request = MemoryListRequest(
        category=normalized_category,
        limit=limit,
        owner_id=normalize_owner_id(owner_id),
    )

    # SQLite üzerinde aktif projenin hafızalarını listeler.
    results = memory_service.list_memories(
        context=context,
        list_request=list_request,
    )

    # Hafıza modellerini MCP için JSON uyumlu
    # sözlüklere dönüştürür.
    return [
        memory.model_dump(mode="json")
        for memory in results
    ]


def get_project_context(limit: int = 10) -> dict[str, object]:
    context = resolve_project_context()
    request = ProjectContextRequest(limit=limit)
    result = memory_service.get_project_context(context=context, request=request)
    return result.model_dump(mode="json")
