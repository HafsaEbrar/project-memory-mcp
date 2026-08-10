# ProjectMemory MCP

Python, SQLite ve Model Context Protocol (MCP) kullanılarak geliştirilmiş, yapay zekâ ajanları için kalıcı hafıza sistemi.

ProjectMemory, yapay zekâ ajanlarının önemli proje bilgilerini kaydetmesini ve farklı oturumlarda bu bilgileri tekrar hatırlamasını sağlar.

## Genel Bakış

Yapay zekâ ajanları genellikle oturumlar arasında önemli proje bağlamını kaybedebilir.

ProjectMemory, MCP uyumlu yapay zekâ uygulamalarına bağlanabilen kalıcı bir hafıza katmanı sağlar.

Örneğin bir yapay zekâ ajanı şu bilgileri kaydedebilir:

- Proje kararları
- Teknoloji seçimleri
- Mimari bilgiler
- Hata çözümleri
- Yapılacak işler
- Kullanıcı tercihleri
- Oturum özetleri

Daha sonraki oturumlarda ihtiyaç duyulduğunda bu bilgiler tekrar çağrılabilir.

## Nasıl Çalışır?

```text
Yapay Zekâ Ajanı
       |
       | MCP
       v
ProjectMemory MCP Sunucusu
       |
       +-- remember
       |
       +-- recall
       |
       v
SQLite Veritabanı
```

## Mimari

```text
OpenCode --------\
                  > ProjectMemory MCP -> SQLite + FTS5
Antigravity -----/
```

- Yapay zekâ ajanı doğal dili yorumlar.
- ProjectMemory MCP, hafıza araçlarını sağlar.
- SQLite kalıcı hafızayı saklar.
- FTS5 indeksli metin araması yapar.
- ProjectMemory içinde ayrı bir embedding modeli yoktur; arama, FTS5
  kelime indeksi üzerinden yapılır.
- Hafıza bir agente ait değildir; kayıtlar ProjectMemory'ye aittir.
  Böylece farklı MCP istemcileri aynı hafızayı paylaşabilir.

### Mimari Prensip

- **Agent** = yorumlama / zeka katmanı
- **MCP server** = araç ve veri erişimi katmanı
- **SQLite + FTS5** = kalıcı depolama ve indeksli retrieval katmanı

Bu yaklaşım, Codebase-MCP benzeri bir agent/tool ayrımı kullanır; ancak
ProjectMemory, Codebase MCP'nin birebir kopyası değildir. ProjectMemory
yapay zekâ ajanları için kalıcı, proje bazlı hafıza sağlamaya odaklanır.

## Test Edilen Agentlar

Aşağıdaki agentlar aynı ProjectMemory MCP sunucusuna ve aynı SQLite
hafızasına bağlanarak gerçek olarak test edilmiştir:

- OpenCode
- Antigravity CLI

MCP uyumlu diğer istemciler de aynı sunucuya bağlanabilir; ancak henüz
test edilmemiş istemciler "destekleniyor" olarak kesin şekilde ifade
edilmez.

## OpenCode kurulumu

Örnek yapılandırma `integrations/opencode.example.json` dosyasında
bulunur. İçerisindeki `<PROJECT_ROOT>` değerini kendi proje yolunla
değiştirip dosyayı `opencode.json` olarak proje köküne kopyala:

```json
{
  "mcp": {
    "project_memory": {
      "type": "local",
      "command": [
        "<PROJECT_ROOT>/.venv/Scripts/python.exe",
        "<PROJECT_ROOT>/server.py"
      ],
      "cwd": "<PROJECT_ROOT>",
      "enabled": true
    }
  }
}
```

`opencode.json` bilgisayara özeldir ve `.gitignore` ile Git'ten hariç
tutulur.

## Antigravity CLI kurulumu

Antigravity, workspace config olarak `.agents/mcp_config.json` dosyasını
kullanır. Örnek yapılandırma `integrations/antigravity.example.json`
dosyasında bulunur:

```json
{
  "mcpServers": {
    "project_memory": {
      "command": "<PROJECT_ROOT>/.venv/Scripts/python.exe",
      "args": [
        "<PROJECT_ROOT>/server.py"
      ],
      "cwd": "<PROJECT_ROOT>"
    }
  }
}
```

`<PROJECT_ROOT>` değerini kendi proje yolunla değiştir. Bu dosya da
bilgisayara özeldir ve `.gitignore` ile Git'ten hariç tutulur.

Antigravity içinde bağlantıyı `/mcp` komutuyla kontrol edebilirsin.

Beklenen araçlar:

- remember
- recall
- search_memories
- list_memories
- update_memory
- forget

## Cross-Agent Demo

Bu senaryo, ProjectMemory'nin tek bir agente bağlı olmadığını kanıtlayan
gerçek bir testtir.

1. **Antigravity**:

   > Bu projede ikinci MCP agentı olarak Antigravity kullanılıyor.
   > Bunu proje hafızasına kaydet.

   → `project_memory/remember`
   → `SQLite memories.db`

2. **OpenCode** (daha sonraki bir oturumda):

   > Bu projede ikinci MCP agentı olarak hangisini kullanıyoruz?

   → ProjectMemory'den kayıt okunur
   → **Antigravity**

Bir agentın yazdığı kayıt, başka bir agent tarafından doğru şekilde
okunabildi. Bu, hafızanın tek bir agente ait olmadığını, ProjectMemory
katmanında paylaşıldığını gösterir.