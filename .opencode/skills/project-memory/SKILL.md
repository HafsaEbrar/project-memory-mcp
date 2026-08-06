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

## Ne zaman recall kullanılmalı?

Aşağıdaki durumlarda cevap vermeden önce `project_memory_recall` aracını kullan:

- Kullanıcı daha önce alınan bir kararı soruyorsa
- Önceden seçilen teknoloji, veritabanı veya kütüphane soruluyorsa
- Projenin mimarisi veya klasör yapısı hakkında geçmiş bilgi gerekiyorsa
- Daha önce çözülen bir hata tekrar ortaya çıktıysa
- Önceki oturumdan kalan görevler veya tercihler soruluyorsa
- Kullanıcı “daha önce”, “hangi teknolojiyi seçmiştik”, “nerede kalmıştık”
  gibi geçmişe yönelik ifadeler kullanıyorsa

Arama sorgusunda kullanıcının sorusundaki en anlamlı ve kısa anahtar kelimeyi kullan.

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