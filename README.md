# ProjectMemory MCP

Python, SQLite ve Model Context Protocol (MCP) kullanılarak geliştirilmiş, yapay zekâ ajanları ve normal chat uygulamaları için proje bazlı kalıcı hafıza katmanı.

ProjectMemory, farklı yapay zekâ ajanlarının, farklı oturumların ve normal chat uygulamalarının aynı proje bazlı kalıcı hafızayı paylaşmasını sağlayan MCP tabanlı bir memory layer'dır; önemli proje bilgileri kaydedilir ve gerektiğinde tekrar hatırlanır.

ProjectMemory içinde ayrı bir embedding modeli, vector database veya gömülü bir AI modeli yoktur. Zeka/yorumlama, bağlanan ajan veya chat LLM'i tarafından yapılır; ProjectMemory yalnızca araç ve veri erişimi sağlar.

## Özellikler

- MCP tabanlı proje hafızası
- SQLite kalıcı depolama
- FTS5 indeksli arama
- Memory Quality (SAME / CHANGED / NEW)
- OpenCode ve Antigravity cross-agent ortak hafıza
- Normal Chat MCP Client + AI Service

## Genel Bakış

Yapay zekâ ajanları ve chat uygulamaları genellikle oturumlar arasında önemli proje bağlamını kaybedebilir. ProjectMemory, MCP uyumlu yapay zekâ uygulamalarına bağlanabilen proje bazlı kalıcı bir hafıza katmanı sağlar.

Örneğin bir yapay zekâ ajanı veya chat uygulaması şu bilgileri kaydedebilir:

- Proje kararları
- Teknoloji seçimleri
- Mimari bilgiler
- Hata çözümleri
- Yapılacak işler
- Kullanıcı tercihleri
- Oturum özetleri

Kaydedilen bilgiler, daha sonraki oturumlarda ve hatta farklı agentlar veya chat uygulamaları tarafından tekrar çağrılabilir.

## Nasıl Çalışır?

```text
AI Agent / Chat LLM
       |
       | MCP
       v
ProjectMemory MCP Sunucusu
       |
       +-- remember / update_memory / forget
       |
       +-- recall / search_memories / list_memories
       |
       v
SQLite Veritabanı + FTS5
```

## Mimari

```text
OpenCode --------\
Antigravity ------> ProjectMemory MCP -> SQLite + FTS5
Normal Chat -----/
```

- **AI Agent / Chat LLM** doğal dili yorumlar; **ProjectMemory MCP** hafıza araçlarını sağlar.
- **SQLite** kalıcı hafızayı saklar; **FTS5** indeksli metin araması yapar.
- ProjectMemory içinde ayrı bir embedding modeli veya vektör veritabanı yoktur; arama FTS5 kelime indeksi üzerinden yapılır.
- Hafıza bir agente ait değildir; kayıtlar ProjectMemory'ye aittir. Farklı MCP istemcileri (ajanlar, chat uygulamaları) aynı hafızayı paylaşabilir.

### Normal Chat Mimari

Normal chat uygulaması SQLite'a DOĞRUDAN erişmez; tüm hafıza işlemleri ProjectMemory MCP araçları üzerinden yapılır.

```text
User
 │
 ├──> Chat LLM / AI Service
 │              │
 │              │ MCP tool call
 │              v
 │      ProjectMemoryClient (MCP stdio)
 │              │
 │              │ MCP stdio subprocess
 │              v
 │      ProjectMemory MCP
 │              │
 │              v
 │      SQLite + FTS5
```

### Mimari Prensip

Bu yaklaşım, Codebase-MCP benzeri bir agent/tool ayrımı kullanır; ancak ProjectMemory, Codebase MCP'nin birebir kopyası değildir. ProjectMemory, yapay zekâ ajanları için kalıcı, proje bazlı hafıza sağlamaya odaklanır.

## Memory Quality: SAME / CHANGED / NEW

ProjectMemory'ye yeni bir kalıcı bilgi kaydedilmeden önce agent, duplicate ve conflict kontrolü yapar. Yeni bilgi üç sınıftan birine ayrılır:

- **SAME** — aynı konu, aynı temel karar/değer: kelimeler değil, taşınan karar karşılaştırılır. Paraphrase, daha açıklayıcı ifade, eş anlamlı kelimeler veya farklı cümle yapısı CHANGED değildir; temel karar aynıysa SAME'dir ve hiçbir yazma işlemi yapılmaz. Yeni kayıt oluşturulmaz, mevcut hafıza olduğu gibi kalır.
- **CHANGED** — aynı konu fakat eski kararla çelişen/yeni karar: yeni kayıt oluşturulmaz, ilgili eski hafıza `update_memory` ile güncellenir.
- **NEW** — gerçekten farklı/yeni bir konu: `remember` ile yeni hafıza oluşturulur.

Bu davranışta katmanlar şöyle ayrılır:

- **Agent** = yorumlama. Yeni bilginin anlamını yorumlar, önce `search_memories` ile ilgili mevcut hafızaları bulur ve SAME / CHANGED / NEW kararını verir.
- **ProjectMemory MCP** = yalnızca `search_memories`, `remember` ve `update_memory` gibi araçları sağlar; anlam kararı vermez.
- **SQLite + FTS5** = saklama ve indeksli retrieval katmanı.

Herhangi bir embedding, model veya vektör veritabanı kullanılmaz; duplicate/conflict anlamı tamamen ajanın yorumuna dayanır. `remember` sunucu içindeki birebir eşleşme kontrolü yalnızca ikinci bir güvenlik katmanıdır.

Aynı protokol OpenCode skill'inde (`.opencode/skills/project-memory`) ve Antigravity rule'ında (`.agents/rules/project-memory.md`) tanımlıdır; iki ajan aynı davranışı sergiler.

## Normal Chat Entegrasyonu

Normal bir web chat uygulaması da aynı ProjectMemory MCP sunucusuna bağlanabilir. Chat katmanının dosyaları ve görevleri:

### chat/memory_client.py

- Mevcut `server.py` MCP sunucusunu gerçek MCP stdio alt süreci olarak başlatır.
- `ClientSession` kurar ve handshake (`initialize`) yapar.
- MCP araç listesini `list_tools()` ile çeker ve cache'ler.
- Generic `call_tool(name, arguments)` sağlar.
- Sunucuyu her mesajda yeniden başlatmayan, uzun ömürlü bir bağlantı kullanır.
- Hiçbir doğrudan SQLite erişimi içermez.

### chat/config.py

- Environment tabanlı LLM ayarları: `LLM_PROVIDER`, `LLM_API_KEY`,
  `LLM_MODEL`, `LLM_BASE_URL`, `LLM_MAX_TOOL_CALLS`, `LLM_TIMEOUT_SECONDS`.
- API anahtarı kaynak kodda hard-code edilmez; `.env` (Git'e işlenmez) desteklenir.

### chat/prompts.py

- Normal chat system prompt'unu tanımlar: kullanıcıyla sohbet, gerekince MCP araçları.
- Memory Quality (SAME / CHANGED / NEW) protokolü.
- Retrieval sırası: `search_memories` → yetersizse `recall` → geniş listeleme için `list_memories`.
- Bilinmeyen cevap, arama terimi olarak tahmin edilmez.
- `forget` yalnızca kullanıcının açık isteğinde kullanılır.

### chat/ai_service.py

- Sağlayıcıdan bağımsız LLM katmanı: `LLMProvider` Protocol + `OpenAICompatibleProvider`.
- httpx ile OpenAI-compatible tool calling.
- MCP tool schema → LLM function tool schema dönüşümü.
- Güvenli JSON tool argument parsing (bozuk arguments → açık hata).
- `ChatAgent` tool loop: LLM → tool call → ProjectMemoryClient → sonuç LLM'e → final text.
- Maksimum tool call limiti (sonsuz döngüyü engeller).

### Normal Chat Çalışma Akışı

Bir oturumda:

> Kullanıcı: "Backend için FastAPI kullanacağız, bunu hatırla."

```text
LLM
 ↓
search_memories
 ↓
kayıt yok → NEW
 ↓
remember
 ↓
ProjectMemory → SQLite
```

Başka bir oturumda:

> Kullanıcı: "Backend için hangi framework'ü seçmiştik?"

```text
LLM
 ↓
search_memories terms: ["backend", "framework", "api"]
 ↓
FastAPI kaydı bulunur
 ↓
LLM: "FastAPI'yi seçmiştik."
```

Not: Model, cevabı önceden bilmediği için "fastapi" kelimesini arama terimi olarak tahmin etmemelidir; arama terimleri yalnızca kullanıcının sorusundan çıkarılır.

## OpenCode kurulumu

Örnek yapılandırma `integrations/opencode.example.json` dosyasında bulunur. İçerisindeki `<PROJECT_ROOT>` değerini kendi proje yolunla değiştirip dosyayı `opencode.json` olarak proje köküne kopyala:

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

`opencode.json` bilgisayara özeldir ve `.gitignore` ile Git'ten hariç tutulur.

## Antigravity CLI kurulumu

Antigravity, workspace config olarak `.agents/mcp_config.json` dosyasını kullanır. Örnek yapılandırma `integrations/antigravity.example.json` dosyasında bulunur:

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

`<PROJECT_ROOT>` değerini kendi proje yolunla değiştir. Bu dosya da bilgisayara özeldir ve `.gitignore` ile Git'ten hariç tutulur.

Antigravity içinde bağlantıyı `/mcp` komutuyla kontrol edebilirsin. Beklenen araçlar: `remember`, `recall`, `search_memories`, `list_memories`, `update_memory`, `forget`.

## Cross-Agent Demo

Bu senaryo, ProjectMemory'nin tek bir agente bağlı olmadığını kanıtlayan gerçek bir testtir.

1. **Antigravity**:

   > Bu projede ikinci MCP agentı olarak Antigravity kullanılıyor.
   > Bunu proje hafızasına kaydet.

   → `project_memory/remember`
   → `SQLite memories.db`

2. **OpenCode** (daha sonraki bir oturumda):

   > Bu projede ikinci MCP agentı olarak hangisini kullanıyoruz?

   → ProjectMemory'den kayıt okunur
   → **Antigravity**

Bir agentın yazdığı kayıt, başka bir agent tarafından doğru şekilde okunabildi. Bu, hafızanın tek bir agente ait olmadığını, ProjectMemory katmanında paylaşıldığını gösterir.

## Testler

OpenCode ve Antigravity CLI, aynı ProjectMemory MCP sunucusuna ve aynı SQLite hafızasına bağlanarak gerçek olarak test edilmiştir. MCP uyumlu diğer istemciler de aynı sunucuya bağlanabilir; ancak henüz test edilmemiş istemciler "destekleniyor" olarak kesin şekilde ifade edilmez.

### tests/test_mcp_server.py

- MCP sunucusunun bellek içi istemci ile testi.
- Araç listesi, remember, recall, search_memories, list_memories,
  update_memory, forget ve FTS5 davranışları.

### tests/test_chat_memory_client.py

- Gerçek MCP subprocess üzerinden smoke testi.
- 6 aracın varlığını doğrular (remember, recall, search_memories,
  list_memories, update_memory, forget).
- remember → search → update → forget akışı.
- Geçici (temp) SQLite DB kullanır; production `data/memories.db` korunur.

### tests/test_chat_ai_service.py

- Gerçek ücretli LLM API çağrısı yapmaz; fake/mock provider kullanır.
- Normal text parse, tool call parse, JSON arguments.
- Bozuk arguments için açık hata.
- MCP schema → OpenAI tool schema dönüşümü.
- ChatAgent: search → remember → final akışı ve maksimum tool loop testi.

Testlerin tamamında production `data/memories.db` değiştirilmez.