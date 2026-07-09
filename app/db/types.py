"""SQLAlchemy 自定义类型 - PostgreSQL 用 JSONB，SQLite 用 JSON"""
from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class JSONBCompat(TypeDecorator):
    """跨数据库 JSON 类型 - PostgreSQL 用 JSONB，SQLite 用 JSON

    生产用 PostgreSQL 是 JSONB，更高效；但本地 demo / 单测常用 SQLite。
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


__all__ = ["JSONBCompat"]
