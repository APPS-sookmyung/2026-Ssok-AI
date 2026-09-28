# app/models/content_vector.py
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class ContentVector(Base):
    """
    북마크 본문 임베딩.

    실제 URL/제목/요약 텍스트는 스프링 메인 DB가 갖고 있고,
    여기에는 검색에 필요한 벡터와 식별자만 둡니다.
    """

    __tablename__ = "content_vectors"

    bookmark_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    space_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=False
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
