# ProjectMemory MCP

ProjectMemory, AI agentlarının proje bazlı kalıcı hafızaya erişmesini sağlayan bir **MCP (Model Context Protocol) server** uygulamasıdır.

Amaç; farklı AI agentlarının aynı proje üzerinde çalışırken kararları, teknolojileri, görevleri ve önemli proje bilgilerini oturumlar arasında hatırlayabilmesini sağlamaktır.

ProjectMemory kendi başına bir LLM veya chat uygulaması değildir. Hafıza ve retrieval katmanı olarak çalışır.

## Mimari

```text
AI Agent / MCP Client
        │
        ▼
ProjectMemory MCP
        │
        ├── remember
        ├── recall
        ├── search_memories
        ├── list_memories
        ├── update_memory
        ├── forget
        └── get_project_context
        │
        ▼
SQLite + FTS5
```

* **MCP** → AI istemcileri ile hafıza sistemi arasındaki araç katmanı
* **SQLite** → kalıcı veri depolama
* **FTS5** → indeksli full-text search
* **BM25** → arama sonuçlarının sıralanması
* **LLM** → ProjectMemory çekirdeğinin parçası değildir

Embedding modeli veya vector database kullanılmaz.

## Özellikler

### Proje bazlı hafıza

Her proje kendi hafıza alanına sahiptir.

```text
Project A
└── kendi memory kayıtları

Project B
└── ayrı memory kayıtları
```

Projeler aynı SQLite veritabanı içerisinde `project_id` ile birbirinden izole edilir.

### Multi-agent kullanım

Aynı proje hafızası farklı MCP istemcileri tarafından kullanılabilir.

Örneğin:

```text
OpenCode ──────┐
Antigravity ───┼──► ProjectMemory MCP
Başka client ──┘
```

Bir agent tarafından kaydedilen proje bilgisi daha sonra başka bir agent tarafından geri çağrılabilir.

### Shared ve User Memory

ProjectMemory iki hafıza scope'u destekler.

#### Shared

Projenin ortak hafızasıdır.

Örneğin:

```text
Projede SQLite + FTS5 kullanılacak.
```

Aynı projedeki kullanıcıların ortak context'inde bulunabilir.

#### User

Belirli bir kullanıcının çalışma hafızasıdır.

Örneğin:

```text
Ebrar bugün MCP Inspector testini tamamladı.
```

Kullanıcının kendi varsayılan context'ine dahil edilir ancak başka kullanıcıların normal hafıza sonuçlarına otomatik olarak karışmaz.

Başka bir kullanıcının çalışma geçmişi gerektiğinde `owner_id` filtresiyle açıkça sorgulanabilir.

### Project Context

`get_project_context` aracı yeni bir agentın aktif projedeki önemli hafıza kayıtlarını tek çağrıyla almasını sağlar.

Kayıtlar öncelikle:

```text
importance DESC
updated_at DESC
id DESC
```

mantığıyla değerlendirilir.

Kategori çeşitliliği yalnızca aynı importance seviyesindeki kayıtlar arasında yardımcı kriter olarak kullanılır.

## MCP Araçları

| Tool                  | Açıklama                                          |
| --------------------- | ------------------------------------------------- |
| `remember`            | Yeni bir bilgiyi kalıcı proje hafızasına kaydeder |
| `recall`              | Geçmiş hafıza kayıtlarını geri çağırır            |
| `search_memories`     | FTS5 üzerinden hafızalarda arama yapar            |
| `list_memories`       | Aktif projedeki hafıza kayıtlarını listeler       |
| `update_memory`       | Mevcut hafıza kaydını günceller                   |
| `forget`              | Hafıza kaydını siler                              |
| `get_project_context` | Projenin önemli hafıza kayıtlarını getirir        |

## Memory Quality

Yeni bilgiler doğrudan kontrolsüz şekilde eklenmek yerine üç durumda değerlendirilir:

```text
SAME
→ Aynı bilgi zaten mevcut.
→ Yeni kayıt oluşturulmaz.

CHANGED
→ Aynı konu hakkında karar/değer değişmiştir.
→ Mevcut kayıt güncellenir.

NEW
→ Gerçekten yeni bir bilgidir.
→ Yeni memory oluşturulur.
```

Bu yapı gereksiz duplicate hafıza kayıtlarının oluşmasını azaltır.

## Kurulum

Repository'yi klonlayın:

```bash
git clone https://github.com/HafsaEbrar/project-memory-mcp.git
cd project-memory-mcp
```

Sanal ortam oluşturun.

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Bağımlılıkları yükleyin:

```bash
pip install -r requirements.txt
```

## MCP Server'ı Çalıştırma

```powershell
.\.venv\Scripts\python.exe server.py
```

MCP Inspector ile çalıştırmak için:

```powershell
npx @modelcontextprotocol/inspector .\.venv\Scripts\python.exe server.py
```

## Kullanıcı Bazlı Hafıza

User-scoped memory kullanmak için server tarafında kullanıcı kimliği tanımlanmalıdır.

PowerShell:

```powershell
$env:PROJECT_MEMORY_USER_ID="ebrar"
```

Ardından MCP server başlatılır.

```powershell
npx @modelcontextprotocol/inspector `
  -e PROJECT_MEMORY_USER_ID=ebrar `
  .\.venv\Scripts\python.exe server.py
```

Kullanıcı kimliği `remember` tool'u üzerinden değiştirilemez. `scope=user` kayıtlarının sahibi server configuration üzerinden belirlenir.

## Özel Database Yolu

Varsayılan database yerine farklı bir SQLite dosyası kullanmak için:

```powershell
$env:PROJECT_MEMORY_DB_PATH="C:\path\to\memories.db"
```

Inspector örneği:

```powershell
npx @modelcontextprotocol/inspector `
  -e PROJECT_MEMORY_USER_ID=ebrar `
  -e PROJECT_MEMORY_DB_PATH=C:\path\to\memories.db `
  .\.venv\Scripts\python.exe server.py
```

Bu özellik test veya farklı çalışma ortamlarını birbirinden ayırmak için kullanılabilir.

## Örnek Akış

Bir kullanıcı proje bilgisi kaydeder:

```text
remember

content:
"Projede SQLite + FTS5 kullanılacak."

category:
technology

importance:
8

scope:
shared
```

Daha sonra aynı projeye bağlanan başka bir agent bu bilgiyi:

```text
search_memories
```

veya:

```text
get_project_context
```

üzerinden kullanabilir.

User-scoped kayıt örneği:

```text
remember

content:
"Bugün API testlerini tamamladım."

category:
decision

importance:
8

scope:
user
```

Bu kayıt varsayılan olarak yalnızca mevcut kullanıcının çalışma context'ine dahil edilir.

## Testler

Tüm testleri çalıştırmak için:

```bash
python -m pytest
```

Clean installation üzerinde test paketi:

```text
25 passed
```

olarak doğrulanmıştır.

Testler production `data/memories.db` dosyasını değiştirmeyecek şekilde izole edilir.

## Teknolojiler

* Python
* MCP 2.0
* SQLite
* SQLite FTS5
* Pydantic
* Pytest
* FastAPI
* HTTPX

## Tasarım İlkeleri

ProjectMemory'nin temel yaklaşımı:

```text
Agent = yorumlama ve karar verme

MCP = araç ve iletişim katmanı

ProjectMemory = kalıcı proje hafızası

SQLite + FTS5 = storage ve retrieval
```

ProjectMemory içerisinde embedding modeli, vector database veya ek bir AI modeli bulunmaz.

Bu sayede hafıza sistemi kullanılan AI modelinden veya agent platformundan bağımsız kalır.
