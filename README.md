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