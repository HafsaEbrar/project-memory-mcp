"""Chat AI servisi için ortam tabanlı yapılandırma.

LLM sağlayıcı ayarları kaynak kodda hard-code edilmez; tamamı
ortam değişkenlerinden okunur. Proje kökünde bir ``.env`` dosyası
varsa değerleri yüklenir, ancak gerçek ortam değişkenleri her zaman
önceliklidir (dotenv davranışı). ``.env`` Git'e işlenmez.

Desteklenen ortam değişkenleri:

    LLM_PROVIDER            openai_compatible (MVP)
    LLM_API_KEY             API anahtarı (zorunlu, kaynak kodda yok)
    LLM_MODEL               model adı (varsayılan: gpt-4o-mini)
    LLM_BASE_URL            sağlayıcı temel adresi
                            (varsayılan: https://api.openai.com/v1)
    LLM_MAX_TOOL_CALLS      tek mesajdaki en fazla araç çağrısı
                            (varsayılan: 8)
    LLM_TIMEOUT_SECONDS     istek zaman aşımı (varsayılan: 60)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# Bu dosyanın bulunduğu klasör:
# project-memory-mcp/chat/
CHAT_DIR = Path(__file__).resolve().parent

# Projenin ana klasörü:
# project-memory-mcp/
PROJECT_ROOT = CHAT_DIR.parent

# .env dosyasının aranacağı yer:
# project-memory-mcp/.env
ENV_FILE_PATH = PROJECT_ROOT / ".env"

# Ortam değişkeni adları.
LLM_PROVIDER_ENV = "LLM_PROVIDER"
LLM_API_KEY_ENV = "LLM_API_KEY"
LLM_MODEL_ENV = "LLM_MODEL"
LLM_BASE_URL_ENV = "LLM_BASE_URL"
LLM_MAX_TOOL_CALLS_ENV = "LLM_MAX_TOOL_CALLS"
LLM_TIMEOUT_ENV = "LLM_TIMEOUT_SECONDS"

# Varsayılan değerler.
DEFAULT_PROVIDER = "openai_compatible"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_TIMEOUT_SECONDS = 60.0

# MVP'de desteklenen sağlayıcılar.
SUPPORTED_PROVIDERS = frozenset({DEFAULT_PROVIDER})


@dataclass(frozen=True)
class Settings:
    """
    LLM katmanının tüm yapılandırması.
    """

    provider: str
    api_key: str | None
    model: str
    base_url: str
    max_tool_calls: int
    timeout_seconds: float


def _read_dotenv(path: Path) -> dict[str, str]:
    """
    Basit bir .env dosyası okuyucu.

    Satır biçimi: KEY=value
    Boş satırlar ve # ile başlayan yorumlar atlanır.
    Değerdeki tırnaklar (tek/çift) temizlenir.

    Gerçek .env gramerinin tamamını uygulamaz; yaygın kullanım
    için yeterlidir. Değişkenler ortam değişkenlerinin yerini
    almaz, yalnızca doldurur.
    """

    values: dict[str, str] = {}

    if not path.is_file():
        return values

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if "=" not in stripped:
            continue

        key, _, raw_value = stripped.partition("=")
        key = key.strip()
        value = raw_value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1].strip()

        if key:
            values[key] = value

    return values


def load_settings(
    env: Mapping[str, str] | None = None,
) -> Settings:
    """
    Yapılandırmayı çevreden okur.

    env verilmezse önce proje kökündeki .env dosyası yüklenir,
    ardından gerçek ortam değişkenleri üzerine uygulanır
    (gerçek env önceliklidir). Testler, ``env`` parametresiyle
    gerçek ortama dokunmadan izole ortam geçirebilir.
    """

    if env is None:
        dotenv_values = _read_dotenv(ENV_FILE_PATH)
        environment = {**dotenv_values, **os.environ}
    else:
        environment = dict(env)

    provider = (
        environment.get(LLM_PROVIDER_ENV, DEFAULT_PROVIDER)
        .strip()
        .lower()
    )

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Desteklenmeyen LLM sağlayıcı: {provider!r}. "
            f"Desteklenen: {sorted(SUPPORTED_PROVIDERS)}"
        )

    api_key = environment.get(LLM_API_KEY_ENV)
    api_key = api_key.strip() if api_key else None

    model = environment.get(LLM_MODEL_ENV, DEFAULT_MODEL).strip()
    if not model:
        model = DEFAULT_MODEL

    base_url = environment.get(LLM_BASE_URL_ENV, DEFAULT_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_BASE_URL

    try:
        max_tool_calls = int(
            environment.get(LLM_MAX_TOOL_CALLS_ENV, DEFAULT_MAX_TOOL_CALLS)
        )
    except ValueError as exc:
        raise ValueError(
            f"{LLM_MAX_TOOL_CALLS_ENV} bir tam sayı olmalıdır."
        ) from exc

    if max_tool_calls < 1:
        raise ValueError(
            f"{LLM_MAX_TOOL_CALLS_ENV} en az 1 olmalıdır."
        )

    try:
        timeout_seconds = float(
            environment.get(LLM_TIMEOUT_ENV, DEFAULT_TIMEOUT_SECONDS)
        )
    except ValueError as exc:
        raise ValueError(
            f"{LLM_TIMEOUT_ENV} bir sayı olmalıdır."
        ) from exc

    if timeout_seconds <= 0:
        raise ValueError(
            f"{LLM_TIMEOUT_ENV} pozitif olmalıdır."
        )

    return Settings(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tool_calls=max_tool_calls,
        timeout_seconds=timeout_seconds,
    )
