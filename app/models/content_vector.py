# app/models/content_vector.py
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class ContentVector(Base):
    """
    북마크 임베딩과 검색용 메타데이터.

    제목·요약은 스프링 데이터의 검색용 사본이며, saved_at은 북마크의 실제
    저장 시각입니다. 기존 벡터의 메타데이터는 확보되기 전까지 NULL로 둡니다.
    """

    __tablename__ = "content_vectors"
    __table_args__ = (
        Index("idx_content_vectors_saved_at", "saved_at"),
    )

    bookmark_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
