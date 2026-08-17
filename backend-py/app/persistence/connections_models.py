"""SQLAlchemy model for the Connections Manager (additive).

Stores external integration credentials (Telegram / WhatsApp / MT5) with
tokens Fernet-encrypted at rest. Backed by PostgreSQL when enabled, otherwise
the JSON store fallback repository in ``connections_repository``.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


def _now():
    return datetime.now(timezone.utc)


class IntegrationSetting(Base):
    __tablename__ = "integration_settings"

    provider_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    port: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_addr: Mapped[str | None] = mapped_column(String(128), nullable=True)
    to_addr: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def to_dict(self):
        return {
            "provider_name": self.provider_name,
            "api_token": self.api_token,
            "phone_number_id": self.phone_number_id,
            "webhook_secret": self.webhook_secret,
            "admin_number": self.admin_number,
            "chat_id": self.chat_id,
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "is_active": bool(self.is_active),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
