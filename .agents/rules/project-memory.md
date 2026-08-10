---
name: memory-quality
description: Yeni bir hafızayı ProjectMemory'ye kaydetmeden önce duplicate/conflict kontrolü yapmayı sağlar. Agent, yeni bilgiyi SAME / CHANGED / NEW olarak sınıflandırır ve buna göre yalnızca gerekli MCP aracını çağırır.
trigger: always_on
---

# Memory Quality: SAME / CHANGED / NEW

ProjectMemory, kalıcı proje bilgilerini SQLite üzerinde saklar ve
arama yapar. Bu sistem bir AI modeli veya embedding kullanmaz;
bilgilerin anlamını yorumlamak ve duplicate/conflict kararı vermek
**ajanın görevidir**.

Yeni bir bilgiyi `project_memory/remember` ile kaydetmeden önce
aşağıdaki adımları uygula:

## 1. Arama

Yeni bilgiden 2-5 anlamlı anahtar terim üret. Gerekirse Türkçe ve
İngilizce karşılıklarını da ekle. Önce

```text
project_memory/search_memories(
    terms=["veritabanı", "database"],
    category="technology",
    limit=5
)
```

çağrısını yap. Dönen sonuçlardaki `content` alanlarını yeni bilgiyle
karşılaştır.

## 2. Sınıflandır

Bulunan her ilgili hafıza için tek bir sınıfa karar ver:

### SAME — aynı konu, aynı temel karar/değer

Sınıflandırmada cümlenin kelimelerine değil, taşıdığı temel karar
veya değere bak. Aşağıdaki durumlar CHANGED değildir, SAME kabul
edilir:

- Aynı kararın yeniden ifade edilmesi (paraphrase)
- Aynı kararın daha açıklayıcı yazılması
- Eş anlamlı kelimeler kullanılması
- Cümle yapısının değiştirilmesi

Örnek:

> Mevcut: "Projenin arayüz rengi mavi olacak."
> Yeni: "Proje arayüz renginin mavi olmasına karar verildi."
> → SAME (temel karar aynı: mavi)

SAME durumunda **hiçbir yazma işlemi yapma**:

- `project_memory/remember` **çağırma**.
- `project_memory/update_memory` **çağırma**.
- Mevcut hafıza olduğu gibi kalsın.

### CHANGED — aynı konu, çelişen/yeni karar

Yeni bilgi, mevcut hafızanın kararıyla çelişiyorsa veya o kararın
yerini alıyorsa (temel karar/değer değişmiş):

- Yeni `project_memory/remember` **çağırma** (çift kayıt oluşturma).
- İlgili mevcut hafızanın `memory_id` değerini kullanarak
  `project_memory/update_memory` çağır ve yeni içeriği o kayda yaz:

```text
project_memory/update_memory(
    memory_id=<bulunan kaydın kimliği>,
    content="Artık veritabanı olarak PostgreSQL kullanılacak."
)
```

### NEW — gerçekten yeni bir konu

Arama ilgili bir kayıt döndürmezse veya bulunan kayıtlar farklı bir
konuya aitse:

- `project_memory/remember` ile yeni hafıza oluştur.

## Örnek

Mevcut kayıt:

> "Veritabanı olarak SQLite kullanılacak."

Yeni bilgi:

> "Artık veritabanı olarak PostgreSQL kullanılacak."

- `project_memory/search_memories(["database", "veritabanı"])`
  → SQLite kaydı bulunur
- Sınıf: **CHANGED**
- `project_memory/update_memory(memory_id=..., content="Artık veritabanı olarak PostgreSQL kullanılacak.")`
- Yeni kayıt oluşturulmaz; eski kayıt PostgreSQL olarak güncellenir.

## Güvenlik katmanı

`project_memory/remember` sunucu tarafında birebir aynı içerik ve
kategori için ayrıca bir duplicate kontrolü yapar. Bu yalnızca ikinci
bir güvenlik katmanıdır; asıl SAME/CHANGED/NEW kararı yukarıdaki
adımlarla verilir.
