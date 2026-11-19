"""Relational schema (SQLAlchemy 2.0).  See docs/ER_DIAGRAM.md for the diagram."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SchemaVersion(Base):  # lightweight migration marker (see README "Schema management")
    __tablename__ = "schema_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))  # student | admin | assessor
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    student: Mapped["Student | None"] = relationship(back_populates="user", uselist=False)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    college: Mapped[str] = mapped_column(String(120), default="")
    roll_number: Mapped[str] = mapped_column(String(40), default="")
    user: Mapped[User] = relationship(back_populates="student")


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    make_model: Mapped[str] = mapped_column(String(120), default="")
    serial_number: Mapped[str] = mapped_column(String(80), default="")
    purchase_date: Mapped[date] = mapped_column(Date)
    declared_value: Mapped[float] = mapped_column(Numeric(12, 2))
    proof_of_purchase_ref: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # --- v3 (InsurTech) registration data. Legacy rows keep eligibility_status "Legacy" and cannot be bought through the self-service flow.
    brand: Mapped[str] = mapped_column(String(80), default="", server_default="")
    model_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("asset_categories.id"), nullable=True)
    invoice_file: Mapped[str] = mapped_column(String(80), default="", server_default="")
    invoice_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    photo_file: Mapped[str] = mapped_column(String(80), default="", server_default="")
    photo_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    invoice_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # never set by the student
    eligibility_status: Mapped[str] = mapped_column(String(20), default="Legacy", server_default="Legacy")  # Eligible | Legacy
    eligibility_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    # --- v4 registration evidence review (set only by staff; a student can never change these). Policy purchase requires "Approved".
    evidence_status: Mapped[str] = mapped_column(String(30), default="Pending review", server_default="Pending review")  # Pending review | More evidence requested | Approved | Rejected
    evidence_reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    evidence_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence_review_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    owner: Mapped[User] = relationship(foreign_keys=[owner_id])


class CoveragePlan(Base):
    """PolicyCenter 'product / coverage plan' analogue.  `terms` holds scalar configuration."""
    __tablename__ = "coverage_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    covered_perils: Mapped[list] = mapped_column(JSON, default=list)
    overall_limit: Mapped[float] = mapped_column(Numeric(12, 2))
    default_per_item_limit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    per_item_limits: Mapped[dict] = mapped_column(JSON, default=dict)  # category -> limit
    cap_at_declared_value: Mapped[bool] = mapped_column(Boolean, default=True)
    deductible_type: Mapped[str] = mapped_column(String(10), default="fixed")  # fixed | percent
    deductible_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    calc_order: Mapped[str] = mapped_column(String(40), default="LIMIT_THEN_DEDUCTIBLE")
    depreciation: Mapped[dict] = mapped_column(JSON, default=dict)
    waiting_period_days: Mapped[int] = mapped_column(Integer, default=0)
    required_documents: Mapped[dict] = mapped_column(JSON, default=dict)  # incident type -> [doc types]
    duplicate_window_days: Mapped[int] = mapped_column(Integer, default=0)
    repair_replace_threshold_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=70)
    disabled_rules: Mapped[list] = mapped_column(JSON, default=list)
    wording: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    exclusions: Mapped[list["Exclusion"]] = relationship(back_populates="plan", cascade="all, delete-orphan", order_by="Exclusion.code")


class Exclusion(Base):
    __tablename__ = "exclusions"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("coverage_plans.id"))
    code: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(120))
    clause: Mapped[str] = mapped_column(String(300), default="")
    incident_types: Mapped[list] = mapped_column(JSON, default=list)
    damage_types: Mapped[list] = mapped_column(JSON, default=list)
    severities: Mapped[list] = mapped_column(JSON, default=list)
    plan: Mapped[CoveragePlan] = relationship(back_populates="exclusions")


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(30), unique=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("coverage_plans.id"))
    status: Mapped[str] = mapped_column(String(20), default="Draft")  # Draft Active Expired Cancelled
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    activated_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancelled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # --- v3: terms frozen at purchase. Later changes to a category never alter an issued policy; the browser never supplies these values.
    category_id: Mapped[int | None] = mapped_column(ForeignKey("asset_categories.id"), nullable=True)
    purchase_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    monthly_premium: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    annual_premium: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_coverage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deductible: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    terms_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    student: Mapped[User] = relationship()
    plan: Mapped[CoveragePlan] = relationship()
    assets: Mapped[list["PolicyAsset"]] = relationship(cascade="all, delete-orphan")
    versions: Mapped[list["PolicyVersion"]] = relationship(cascade="all, delete-orphan", order_by="PolicyVersion.version")


class PolicyAsset(Base):
    __tablename__ = "policy_assets"
    __table_args__ = (UniqueConstraint("policy_id", "asset_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    added_on: Mapped[date] = mapped_column(Date, default=date.today)
    asset: Mapped[Asset] = relationship()


class PolicyVersion(Base):
    """Immutable snapshot of terms + insured assets (PolicyCenter 'policy period / job' analogue)."""
    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("policy_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"))
    version: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(300), default="")
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RepairCatalogueEntry(Base):
    __tablename__ = "repair_catalogue"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(40))
    component: Mapped[str] = mapped_column(String(80))
    damage_type: Mapped[str] = mapped_column(String(40), default="")  # "" = any
    action: Mapped[str] = mapped_column(String(20), default="Repair")  # Repair | Replace
    parts_cost: Mapped[float] = mapped_column(Numeric(12, 2))
    labour_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    notes: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_number: Mapped[str] = mapped_column(String(30), unique=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"))
    claimant_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    incident_date: Mapped[date] = mapped_column(Date)
    incident_type: Mapped[str] = mapped_column(String(40))
    incident_location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="Draft")
    policy_version_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(40), default="")  # engine output
    recommendation_reasons: Mapped[list] = mapped_column(JSON, default=list)
    estimated_payable: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    assessor_notes: Mapped[str] = mapped_column(Text, default="")
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    assessor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_run: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # --- v3 automated flow ("auto"): AI evidence verification, then a separate backend policy-rule engine. Legacy claims are "manual".
    flow: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual")
    damage_type: Mapped[str] = mapped_column(String(60), default="", server_default="")
    estimated_repair_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    assessed_loss: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    payable_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    ai_outcome: Mapped[str] = mapped_column(String(40), default="", server_default="")
    ai_workflow_outcome: Mapped[str] = mapped_column(String(50), default="", server_default="")  # v4 four-way outcome of the latest verification run
    decision_outcome: Mapped[str] = mapped_column(String(40), default="", server_default="")
    policy: Mapped[Policy] = relationship()
    claimant: Mapped[User] = relationship(foreign_keys=[claimant_id])
    asset: Mapped[Asset] = relationship()
    items: Mapped[list["ClaimItem"]] = relationship(cascade="all, delete-orphan", order_by="ClaimItem.id")
    evidence: Mapped[list["Evidence"]] = relationship(cascade="all, delete-orphan", order_by="Evidence.id")


class Evidence(Base):
    __tablename__ = "evidence_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    doc_type: Mapped[str] = mapped_column(String(40))
    original_name: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ClaimItem(Base):
    """Damaged item / ClaimCenter 'exposure' analogue, with the human-verified assessment."""
    __tablename__ = "claim_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    component: Mapped[str] = mapped_column(String(80))
    damage_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="Moderate")
    repair_action: Mapped[str] = mapped_column(String(20), default="Inspect Further")
    parts_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    labour_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_source: Mapped[str] = mapped_column(String(20), default="")  # catalogue | assessor | ""
    catalogue_entry_id: Mapped[int | None] = mapped_column(ForeignKey("repair_catalogue.id"), nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)  # evidence ids
    confidence: Mapped[str] = mapped_column(String(20), default="Unknown")  # Low|Medium|High|Unknown
    verification_status: Mapped[str] = mapped_column(String(20), default="Human Verified")
    notes: Mapped[str] = mapped_column(Text, default="")
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    ai_suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("ai_suggestions.id"), nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AISuggestion(Base):
    """AI (or clearly-labelled demo-fallback) output.  Never edited; kept separate from ClaimItem."""
    __tablename__ = "ai_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("policies.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # image_description | assessment | explanation | quotation
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    status_note: Mapped[str] = mapped_column(String(300), default="")
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_files.id"), nullable=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # processing metadata for real provider calls: attempts, latency_ms, token usage, request id, schema validation result, error text
    meta: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    validation_status: Mapped[str] = mapped_column(String(20), default="n/a", server_default="n/a")  # valid | invalid | n/a


class RuleEvaluationResult(Base):
    __tablename__ = "rule_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    run: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    rule_id: Mapped[str] = mapped_column(String(20))
    rule_name: Mapped[str] = mapped_column(String(120), default="")
    outcome: Mapped[str] = mapped_column(String(20))
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    clause: Mapped[str] = mapped_column(String(300), default="")
    follow_up: Mapped[str] = mapped_column(String(300), default="")
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CalculationLine(Base):
    __tablename__ = "calculation_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    run: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="step")
    label: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    running_total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    rule_ref: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ClaimStatusHistory(Base):
    __tablename__ = "claim_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    from_status: Mapped[str] = mapped_column(String(30), default="")
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int] = mapped_column(Integer)
    claim_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(50), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuthSession(Base):
    """Server-side login session. Only an HMAC of the random token is stored, never the token itself."""
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(200), default="")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), index=True)
    ip: Mapped[str] = mapped_column(String(64), default="", index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class ClaimReserve(Base):
    """One reserve record per claim: assessor RECOMMENDS, administrator APPROVES (four-eyes)."""
    __tablename__ = "claim_reserves"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), unique=True)
    recommended_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    approved_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ReserveHistory(Base):
    __tablename__ = "reserve_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # Recommend | Approve | Adjust | Release
    field: Mapped[str] = mapped_column(String(20))  # recommended | approved
    old_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    new_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Payment(Base):
    """SIMULATED payment record. No bank or gateway is ever contacted."""
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("claim_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default="Requested")  # Requested Approved Rejected Cancelled Paid Failed
    payee_name: Mapped[str] = mapped_column(String(120), default="")
    method: Mapped[str] = mapped_column(String(30), default="SIMULATED")
    idempotency_key: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    simulation_note: Mapped[str] = mapped_column(String(200), default="")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SystemSetting(Base):
    """Admin-editable runtime settings (key/value)."""
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(300), default="")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ====================================================================== v3: InsurTech models
class AssetCategory(Base):
    """Configurable insurance product per asset category. The ONLY source of eligibility, premium, coverage and deductible values."""
    __tablename__ = "asset_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    min_purchase_value: Mapped[float] = mapped_column(Numeric(12, 2))
    monthly_premium: Mapped[float] = mapped_column(Numeric(12, 2))
    max_coverage: Mapped[float] = mapped_column(Numeric(12, 2))
    deductible: Mapped[float] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    policy_months: Mapped[int] = mapped_column(Integer, default=12, server_default="12")
    waiting_period_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    depreciation_pct_per_year: Mapped[float] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    depreciation_max_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0, server_default="0")
    exclusions: Mapped[list] = mapped_column(JSON, default=list)  # human-readable exclusion clauses
    covered_incident_types: Mapped[list] = mapped_column(JSON, default=list)
    excluded_damage_types: Mapped[list] = mapped_column(JSON, default=list)
    damage_types: Mapped[list] = mapped_column(JSON, default=list)  # damage types the student can claim for this category
    reference_repair_costs: Mapped[dict] = mapped_column(JSON, default=dict)  # damage type -> reference cost used when no estimate is given
    eligibility_conditions: Mapped[str] = mapped_column(String(500), default="", server_default="")
    requires_serial: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("coverage_plans.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class PremiumTransaction(Base):
    """SIMULATED premium payment. No card or bank details exist anywhere in the system."""
    __tablename__ = "premium_transactions"
    __table_args__ = (UniqueConstraint("policy_id", "period_label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    period_label: Mapped[str] = mapped_column(String(7))  # YYYY-MM of the cover month paid for
    status: Mapped[str] = mapped_column(String(12), default="Paid")  # Paid | Failed
    method: Mapped[str] = mapped_column(String(20), default="SIMULATED")
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AssetEvidence(Base):
    """One stored file of registration evidence (photographs, invoice, other documents). Files live in UPLOAD_DIR under a random name."""
    __tablename__ = "asset_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # front_photo | back_photo | extra_photo | invoice | document
    stored_name: Mapped[str] = mapped_column(String(80))
    original_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    phash: Mapped[str] = mapped_column(String(16), default="", index=True)
    phash_dct: Mapped[str] = mapped_column(String(16), default="", server_default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    exif: Mapped[dict] = mapped_column(JSON, default=dict)
    flags: Mapped[list] = mapped_column(JSON, default=list)  # automatic observations shown to the reviewer (never a verdict)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    review_status: Mapped[str] = mapped_column(String(12), default="Pending", server_default="Pending")  # Pending | Accepted | Rejected
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ClaimImage(Base):
    __tablename__ = "claim_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stored_name: Mapped[str] = mapped_column(String(80))
    original_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str] = mapped_column(String(16), default="", index=True)
    phash_dct: Mapped[str] = mapped_column(String(16), default="", server_default="")  # second perceptual hash (DCT); "" for rows created before v4
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    exif: Mapped[dict] = mapped_column(JSON, default=dict)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AIVerificationReport(Base):
    __tablename__ = "ai_verification_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    run: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(30))  # onnx_model | vision_language_model | development_simulation | limited
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    model_info: Mapped[dict] = mapped_column(JSON, default=dict)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_identification: Mapped[dict] = mapped_column(JSON, default=dict)
    damage_detection: Mapped[dict] = mapped_column(JSON, default=dict)
    description_check: Mapped[dict] = mapped_column(JSON, default=dict)
    duplicate_check: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_completeness: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_indicators: Mapped[list] = mapped_column(JSON, default=list)
    device_match: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")  # v4: comparison with the registered photographs
    authenticity: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")  # v4: EXIF, manipulation indicators, duplicate summary
    workflow_outcome: Mapped[str] = mapped_column(String(50), default="", server_default="")  # v4 four-way outcome (see verification.WORKFLOW_*)
    outcome: Mapped[str] = mapped_column(String(40))
    route: Mapped[str] = mapped_column(String(20), default="auto")  # auto | more_evidence | exceptional_review
    explanation: Mapped[str] = mapped_column(Text, default="")
    next_step: Mapped[str] = mapped_column(Text, default="")
    processing_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ClaimDecision(Base):
    __tablename__ = "claim_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), index=True)
    run: Mapped[int] = mapped_column(Integer, default=1)
    outcome: Mapped[str] = mapped_column(String(40))
    decided_by: Mapped[str] = mapped_column(String(10), default="system")  # system | staff
    decided_by_user: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    calculation: Mapped[dict] = mapped_column(JSON, default=dict)
    payable_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Settlement(Base):
    """SIMULATED settlement. No bank or gateway is contacted."""
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), unique=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default="Processing")  # Processing | Settled
    method: Mapped[str] = mapped_column(String(20), default="SIMULATED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FinancialExpense(Base):
    __tablename__ = "financial_expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    category: Mapped[str] = mapped_column(String(20))  # operating | ai_technology
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    description: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RiskReserve(Base):
    __tablename__ = "risk_reserves"
    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    description: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ChatConversation(Base):
    """A CoverMate AI conversation. Always read through (public_id AND user_id) so one user can never open another's."""
    __tablename__ = "chat_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(80), default="")
    focus_policy_id: Mapped[int | None] = mapped_column(ForeignKey("policies.id"), nullable=True)
    focus_claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.id")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("chat_conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
