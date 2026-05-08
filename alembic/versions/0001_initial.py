"""initial schema (single-user)

Revision ID: 0001
Revises: 
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── analyses ──
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False, server_default="XAUUSD", index=True),
        sa.Column("timeframe", sa.String(10), nullable=False, index=True),
        sa.Column("is_mtf", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("chart_price", sa.Float(), nullable=True),
        sa.Column("market_price", sa.Float(), nullable=True),
        sa.Column("primary_bias", sa.String(20), nullable=True),
        sa.Column("trend_direction", sa.String(20), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="web"),
        sa.Column("user_context", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("image_hashes", sa.JSON(), nullable=True),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_analyses_created_status", "analyses", ["created_at", "status"])

    # ── audit_logs ──
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(40), nullable=False, server_default="owner"),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )
    op.create_index("ix_audit_action_created", "audit_logs", ["action", "created_at"])

    # ── share_links ──
    op.create_table(
        "share_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token", sa.String(32), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── analysis_outcomes ──
    op.create_table(
        "analysis_outcomes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("setup_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("setup_label", sa.String(64), nullable=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("stop_loss", sa.Float(), nullable=False),
        sa.Column("tp_levels", sa.JSON(), nullable=True),
        sa.Column("expected_rr", sa.String(32), nullable=True),
        sa.Column("chart_price_at_creation", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("entry_filled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("entry_filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_close_price", sa.Float(), nullable=True),
        sa.Column("realized_rr", sa.Float(), nullable=True),
        sa.Column("realized_pnl_pct", sa.Float(), nullable=True),
        sa.Column("tp1_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("tp2_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("tp3_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("tp4_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sl_hit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_favorable_excursion", sa.Float(), nullable=True),
        sa.Column("max_adverse_excursion", sa.Float(), nullable=True),
        sa.Column("last_checked_price", sa.Float(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_outcomes_status_active", "analysis_outcomes", ["status", "is_active"])

    # ── feedbacks ──
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("accuracy_rating", sa.Integer(), nullable=True),
        sa.Column("usefulness_rating", sa.Integer(), nullable=True),
        sa.Column("bias_correct", sa.Boolean(), nullable=True),
        sa.Column("levels_correct", sa.Boolean(), nullable=True),
        sa.Column("setup_followed", sa.Boolean(), nullable=True),
        sa.Column("setup_profitable", sa.Boolean(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("is_quality_example", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── backtest_runs ──
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False, server_default="XAUUSD"),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_setups_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_setups_filled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("avg_realized_rr", sa.Float(), nullable=True),
        sa.Column("total_pnl_R", sa.Float(), nullable=True),
        sa.Column("detailed_results", sa.JSON(), nullable=True),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── few_shot_examples ──
    op.create_table(
        "few_shot_examples",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_analysis_id", sa.String(36), sa.ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("symbol", sa.String(20), nullable=False, server_default="XAUUSD"),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("market_regime", sa.String(40), nullable=True),
        sa.Column("summary_text", sa.String(2000), nullable=False),
        sa.Column("full_result_json", sa.JSON(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_rr", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_id", sa.String(64), nullable=True),
        sa.Column("embedding_model", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fewshot_active_score", "few_shot_examples", ["is_active", "quality_score"])
    op.create_index("ix_fewshot_tf_regime", "few_shot_examples", ["timeframe", "market_regime"])


def downgrade() -> None:
    op.drop_table("few_shot_examples")
    op.drop_table("backtest_runs")
    op.drop_table("feedbacks")
    op.drop_table("analysis_outcomes")
    op.drop_table("share_links")
    op.drop_table("audit_logs")
    op.drop_table("analyses")
