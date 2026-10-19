"""Tables in the separate `tube2dev_credentials` database. Only the API and worker service accounts
can connect to it. Values are KMS ciphertext; plaintext keys never touch any database."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CredsBase(DeclarativeBase):
    pass


class UserCredential(CredsBase):
    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)  # openrouter | devto
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kms_key_version: Mapped[str] = mapped_column(String(300), nullable=False)
    last4: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok | invalid | unknown
    username: Mapped[str | None] = mapped_column(String(200))  # dev.to handle
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
