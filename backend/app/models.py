"""SQLAlchemy ORM models.

Foreign-key cascades are declared in the DDL (``ondelete=``) and mirrored on the relationships
with ``passive_deletes=True`` so deletes are left to SQLite (``PRAGMA foreign_keys=ON``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db import UTCDateTime, new_id, utcnow


class Base(DeclarativeBase):
    """Declarative base for every table."""


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow, index=True
    )

    tags: Mapped[list[PromptTag]] = relationship(
        back_populates="prompt",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PromptTag.position",
        lazy="selectin",
    )
    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="prompt_ref",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PromptVersion.version",
        lazy="raise",
    )

    @property
    def tag_names(self) -> list[str]:
        return [tag.tag for tag in self.tags]


class PromptTag(Base):
    __tablename__ = "prompt_tags"

    prompt_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("prompts.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)
    #: Preserves the order in which tags were given.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    prompt: Mapped[Prompt] = relationship(back_populates="tags")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version", name="uq_prompt_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    prompt_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    prompt_ref: Mapped[Prompt] = relationship("Prompt", back_populates="versions")


class TestSuite(Base):
    __tablename__ = "test_suites"
    __test__ = False  # not a pytest test class

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow, index=True
    )

    cases: Mapped[list[TestCase]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestCase.position",
        lazy="raise",
    )


class TestCase(Base):
    __tablename__ = "test_cases"
    __table_args__ = (Index("ix_test_cases_suite_position", "suite_id", "position"),)
    __test__ = False

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    suite_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    variables: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    suite: Mapped[TestSuite] = relationship(back_populates="cases")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    suite_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("test_suites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    suite_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True
    )
    prompt_label: Mapped[str] = mapped_column(String(200), nullable=False)
    system: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    models: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    judge_model: Mapped[str] = mapped_column(String(128), nullable=False)
    cases_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    results: Mapped[list[EvalResultRow]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class EvalResultRow(Base):
    __tablename__ = "eval_results"
    __table_args__ = (Index("ix_eval_results_run_case", "eval_run_id", "case_index"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    eval_run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_index: Mapped[int] = mapped_column(Integer, nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    case_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    assertions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    run: Mapped[EvalRun] = relationship(back_populates="results")


class HistoryEntry(Base):
    __tablename__ = "history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    group_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    prompt_version_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    system_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    rendered_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
