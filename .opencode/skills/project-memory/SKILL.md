---
name: project-memory
description: Projeye ait kalıcı kararları, teknolojileri, mimari bilgileri, hata çözümlerini, yapılacak işleri ve tercihleri ProjectMemory MCP araçlarıyla kaydetmek ve geçmiş proje bilgilerini geri çağırmak için kullanılır.
compatibility: opencode
metadata:
  mcp-server: project_memory
---

# ProjectMemory Kullanım Kuralları

Bu skill, aktif projeye ait kalıcı bilgilerin ProjectMemory MCP sunucusunda
saklanmasını ve gerektiğinde geri çağrılmasını sağlar.

Kullanılacak MCP araçları:

- `project_memory_remember`
- `project_memory_recall`
- `project_memory_search_memories`
- `project_memory_list_memories`
- `project_memory_update_memory`
- `project_memory_forget`

## Yeni bilgi kaydetmeden önce: SAME / CHANGED / NEW

Kalıcı bir bilgiyi kaydetmeden önce mutlaka duplicate/conflict
kontrolü yap:

1. Yeni bilgiden 2-5 anlamlı anahtar terim üret (gerekirse
   Türkçe/İngilizce karşılıklarını ekle).
2. Bu terimlerle `project_memory_search_memories` çağır.
3. Dönen sonuçları yeni bilgiyle karşılaştır ve aşağıdaki
   üç sınıftan birine karar ver:

**SAME** — Aynı konu, aynı temel karar/değer:

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

- `project_memory_remember` çağırma.
- `project_memory_update_memory` çağırma.
- Mevcut kayıt aynen kalsın.

**CHANGED** — Aynı konu fakat yeni bilgi eski kararın yerini
alıyor veya onunla çelişiyor (temel karar/değer değişmiş):

- Yeni `project_memory_remember` çağırma (çift kayıt oluşturma).
- İlgili eski kaydın `memory_id` değerini bul ve
  `project_memory_update_memory` ile yeni içeriği eski kayda yaz.

**NEW** — Gerçekten yeni/farklı bir konu:

- `project_memory_remember` ile yeni hafıza oluştur.

Arama ilgili bir sonuç döndürmezse sınıf **NEW**'dir.

Not: `project_memory_remember` içinde birebir aynı içerik/kategori
için ayrıca bir duplicate kontrolü vardır; bu yalnızca ikinci bir
güvenlik katmanıdır. Asıl duplicate/conflict kararı yukarıdaki
adımlarla verilir.

Örnek:

Mevcut kayıt:

> "Veritabanı olarak SQLite kullanılacak."

Yeni bilgi:

> "Artık veritabanı olarak PostgreSQL kullanılacak."

```text
project_memory_search_memories(
    terms=["database", "veritabanı"],
    category="technology",
    limit=5
)
```

→ SQLite kaydı bulunur
→ **CHANGED**
→ `project_memory_update_memory` ile eski kayıt PostgreSQL
  olarak güncellenir, yeni kayıt oluşturulmaz.

## Geçmiş bilgi sorularında tercih sırası

Geçmiş proje bilgisi sorularında araçları şu sırayla dene:

1. Önce `project_memory_search_memories`
2. Yetersizse `project_memory_recall`
3. `project_memory_list_memories` yalnızca geniş bir listeleme gerektiğinde

Doğrudan bütün hafızaları `project_memory_list_memories` ile çekmek ilk
tercih değildir.

## Ne zaman search_memories kullanılmalı?

`project_memory_search_memories`, hafızalar üzerinde SQLite FTS5 tabanlı
indeksli (tam metin) arama yapar. Semantik embedding modeli kullanmaz;
yalnızca verilen terimleri kelime indeksi üzerinden OR mantığıyla eşleştirir.

Aşağıdaki durumlarda recall yerine `project_memory_search_memories`
kullanılabilir:

- Kullanıcı geçmiş proje bilgisini doğal, cümle hâlinde bir soruyla
  soruyorsa (ör. "Hangi database çözümünü seçmiştik?")
- Tam ifade değil de birkaç anahtar kelimeyle arama yapmak gerekiyorsa

Kullanım kuralları:

- Kullanıcının sorusundan 2-5 kısa ve anlamlı arama terimi üret.
- Gerekirse Türkçe/İngilizce karşılıklarını ekle.
- Bilmediğin kesin cevabı arama terimi olarak uydurma. Örneğin SQLite'ın
  seçildiğini önceden bilmiyorsan "sqlite" terimini ekleme.
- Sonuç bulunamazsa daha genel veya alternatif terimlerle tekrar dene.
- Tam kelime/ifade araması gerektiğinde mevcut recall aracını kullanmaya
  devam edebilirsin.

Örnek:

Kullanıcı:

> Hangi database çözümünü seçmiştik?

Araç çağrısı:

```text
project_memory_search_memories(
    terms=["database", "veritabanı"],
    category="technology",
    limit=5
)
```

## Ne zaman recall kullanılmalı?

`project_memory_search_memories` ile sonuç bulunamazsa veya yetersizse
`project_memory_recall` kullanılır. Aşağıdaki durumlarda da cevap
vermeden önce `project_memory_recall` aracını kullan:

- Kullanıcı daha önce alınan bir kararı soruyorsa
- Önceden seçilen teknoloji, veritabanı veya kütüphane soruluyorsa
- Projenin mimarisi veya klasör yapısı hakkında geçmiş bilgi gerekiyorsa
- Daha önce çözülen bir hata tekrar ortaya çıktıysa
- Önceki oturumdan kalan görevler veya tercihler soruluyorsa
- Kullanıcı “daha önce”, “hangi teknolojiyi seçmiştik”, “nerede kalmıştık”
  gibi geçmişe yönelik ifadeler kullanıyorsa

Arama sorgusunda kullanıcının sorusundaki en anlamlı ve kısa anahtar kelimeyi kullan.

## Ne zaman list_memories kullanılmalı?

`project_memory_list_memories` öncelikli arama aracı değildir; yalnızca
geniş listeleme gerektiğinde kullanılır. Aşağıdaki durumlarda kullan:

- Kullanıcı proje hakkında kayıtlı hafızaların tamamını görmek istiyorsa
- Kayıtlı hafızaların genel bir özeti veya dökümü isteniyorsa
- Belirli bir kategoride (ör. technology, decision) ne kadar bilgi kayıtlı
  olduğu soruluyorsa
- Arama ifadesi belirsizken hangi hafızaların olduğunu görmek isteniyorsa

Kullanıcı arama kelimesi belirtmeden "ne biliyorsun", "ne kayıtlı", "ne
kararlar vardı" gibi genel ifadeler kullanıyorsa recall yerine
`project_memory_list_memories` tercih edilir.

Örnek:

Kullanıcı:

> Hangi teknoloji kararları kayıtlı?

Araç çağrısı:

```text
project_memory_list_memories(
    category="technology",
    limit=20
)
```

Örnek:

Kullanıcı:

> Hangi veritabanını kullanıyorduk?

Araç çağrısı:

```text
project_memory_recall(
    query="veritabanı",
    category="technology",
    limit=5
)
```

## Ne zaman update_memory kullanılmalı?

Aşağıdaki durumlarda `project_memory_update_memory` aracını kullan:

- Kayıtlı bir hafızanın içeriği değiştiyse veya yanlış/eksik yazıldıysa
- Bir hafızanın kategorisi yanlış kategorideyse ve düzeltilmesi gerekiyorsa
- Bir hafızanın önem seviyesi (importance) güncellenmek istendiğinde
- Kullanıcı kayıtlı bir bilgiyi "düzelt", "güncelle" veya "değiştir"
  gibi ifadelerle güncellemek istiyorsa

Dikkat:

- Güncelleme her zaman `memory_id` ile yapılır. Kimliği bilinmeyen bir
  kaydı güncellemek için önce `project_memory_list_memories` veya
  `project_memory_recall` ile kaydın kimliğini bul.
- Yalnızca aktif projeye ait hafızalar güncellenebilir.
- `content`, `category` ve `importance` alanlarının en az biri verilmek
  zorundadır; verilmeyen alanlar değiştirilmez.
- Yanlış kimlikle güncelleme yapılmaya çalışılırsa araç hata döndürür.

Örnek:

Kullanıcı:

> Hafızadaki pytest kararının önemini 9'a çıkar.

Araç çağrısı:

```text
project_memory_list_memories(
    category="decision",
    limit=20
)
```

```text
project_memory_update_memory(
    memory_id=<bulunan kayıt kimliği>,
    importance=9
)
```

## Ne zaman forget kullanılmalı?

`project_memory_forget` aracı, aktif projeye ait bir hafıza kaydını
veritabanından kalıcı olarak siler.

Aşağıdaki durumlarda kullanılır:

- Kullanıcı kayıtlı bir hafızayı açıkça "sil", "kaldır", "unut"
  gibi ifadelerle silmek istiyorsa
- Kullanıcı belirli bir hafıza kaydının `memory_id` değerini veriyorsa
- Yanlış ya da artık geçerli olmayan bir hafıza kaydının
  kaldırılması açıkça isteniyorsa

Önemli kurallar:

- `project_memory_forget` geri alınamaz bir işlemdir. Silinen
  hafıza bir daha geri getirilemez.
- Agent, kullanıcı açıkça silme/unutma istemediği sürece hiçbir
  hafızayı otomatik olarak silmemelidir.
- Belirsiz bir istekte hangi hafızanın silineceği tahmin edilmemelidir.
  Hangi kaydın silineceği netleşmediyse önce
  `project_memory_list_memories` veya `project_memory_recall` ile
  doğru kaydın kimliğini bul.
- Yalnızca aktif projeye ait hafızalar silinebilir. Yanlış kimlikle
  silme yapılmaya çalışılırsa araç hata döndürür.
- Silme isteğinden önce kaydın gerçekten silinmek istenen kayıt
  olduğundan emin olmak için içeriğini teyit et.

Örnek:

Kullanıcı:

> Hafıza kaydını unut, artık gerek yok.

Araç çağrısı (önce doğru kayıt bulunur):

```text
project_memory_list_memories(
    limit=20
)
```

```text
project_memory_forget(
    memory_id=<bulunan kayıt kimliği>
)
```