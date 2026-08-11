"""Kısa süreli sohbet geçmişi için in-memory oturum mağazası.

SessionStore, tek bir sohbet oturumunun user/assistant mesaj çiftlerini
bellekte tutar. Sunucu yeniden başlarken (yeni process) tüm oturumlar
yok olur; bu bilinçli bir tasarımdır: kalıcı proje bilgileri
ProjectMemoryClient / MCP (SQLite) aracılığıyla yönetilir.

Bu sınıf asla doğrudan SQLite ya da başka bir kalıcı depolama
kullanmaz; yalnızca dict'de tutar. Böylece backend'in production
veri tabanına dokunması tamamen ortadan kalkar.
"""

from __future__ import annotations

import secrets
from typing import Any

SESSION_ID_BYTES = 16


class SessionStore:
    """In-memory oturum bazlı sohbet geçmişi."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _new_session_id() -> str:
        return secrets.token_hex(SESSION_ID_BYTES)

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def create_session(self) -> str:
        session_id = self._new_session_id()
        self._sessions[session_id] = []
        return session_id

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return [
            dict(message)
            for message in self._sessions.get(session_id, [])
        ]

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        self._sessions[session_id].append(
            {"role": role, "content": content}
        )

    def delete_session(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None
