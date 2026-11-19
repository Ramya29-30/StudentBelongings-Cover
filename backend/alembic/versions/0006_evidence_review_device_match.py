"""registration evidence, evidence review status, device matching and authenticity report fields

Revision ID: 0006
Revises: 0005

Backward compatible: only adds a table and columns that have defaults. On SQLite the columns are added with plain ALTER TABLE ... ADD COLUMN, NOT with
Alembic batch mode: batch mode rebuilds the table, and SQLite refuses to drop `assets` or `claims` while other rows reference them (foreign keys are ON), which fails on
any database that already holds data. ADD COLUMN keeps every existing row untouched. Nothing is dropped or rewritten except the backfill below.

Backfill rules (documented in docs/EVIDENCE_AND_FRAUD_CHECKS.md):
  * every self-service asset that already has an ACTIVE policy is marked "Approved" (grandfathered: it was insured under the earlier rules);
  * every other self-service asset is marked "Pending review", so staff must review it before a policy can be bought;
  * the single photograph and the invoice that were stored on the asset row are copied into asset_evidence as a front photograph and an invoice
    (the files themselves are not touched; their fingerprints are filled in lazily the first time they are needed).
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

_CT = {".png": "image/png", ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def upgrade() -> None:
    op.create_table('asset_evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('stored_name', sa.String(length=80), nullable=False),
    sa.Column('original_name', sa.String(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=40), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('phash', sa.String(length=16), nullable=False),
    sa.Column('phash_dct', sa.String(length=16), server_default='', nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('quality', sa.JSON(), nullable=False),
    sa.Column('exif', sa.JSON(), nullable=False),
    sa.Column('flags', sa.JSON(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.Column('review_status', sa.String(length=12), server_default='Pending', nullable=False),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_asset_evidence_asset_id'), 'asset_evidence', ['asset_id'], unique=False)
    op.create_index(op.f('ix_asset_evidence_phash'), 'asset_evidence', ['phash'], unique=False)
    op.create_index(op.f('ix_asset_evidence_sha256'), 'asset_evidence', ['sha256'], unique=False)

    sqlite = op.get_bind().dialect.name == "sqlite"

    def add(table: str, ddl: str, column: sa.Column) -> None:
        if sqlite:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        else:
            op.add_column(table, column)

    add('assets', "evidence_status VARCHAR(30) NOT NULL DEFAULT 'Pending review'", sa.Column('evidence_status', sa.String(length=30), server_default='Pending review', nullable=False))
    add('assets', "evidence_reviewed_by INTEGER REFERENCES users (id)", sa.Column('evidence_reviewed_by', sa.Integer(), nullable=True))
    add('assets', "evidence_reviewed_at DATETIME", sa.Column('evidence_reviewed_at', sa.DateTime(), nullable=True))
    add('assets', "evidence_review_note VARCHAR(500) NOT NULL DEFAULT ''", sa.Column('evidence_review_note', sa.String(length=500), server_default='', nullable=False))
    if not sqlite:
        op.create_foreign_key('fk_assets_evidence_reviewed_by', 'assets', 'users', ['evidence_reviewed_by'], ['id'])
    add('claim_images', "phash_dct VARCHAR(16) NOT NULL DEFAULT ''", sa.Column('phash_dct', sa.String(length=16), server_default='', nullable=False))
    add('claims', "ai_workflow_outcome VARCHAR(50) NOT NULL DEFAULT ''", sa.Column('ai_workflow_outcome', sa.String(length=50), server_default='', nullable=False))
    add('ai_verification_reports', "device_match JSON NOT NULL DEFAULT '{}'", sa.Column('device_match', sa.JSON(), server_default='{}', nullable=False))
    add('ai_verification_reports', "authenticity JSON NOT NULL DEFAULT '{}'", sa.Column('authenticity', sa.JSON(), server_default='{}', nullable=False))
    add('ai_verification_reports', "workflow_outcome VARCHAR(50) NOT NULL DEFAULT ''", sa.Column('workflow_outcome', sa.String(length=50), server_default='', nullable=False))

    # ---- backfill (see module docstring)
    bind = op.get_bind()
    note = "Grandfathered: the policy was activated before registration evidence review existed."
    bind.execute(sa.text(
        "UPDATE assets SET evidence_status = 'Approved', evidence_review_note = :note "
        "WHERE category_id IS NOT NULL AND id IN ("
        "  SELECT pa.asset_id FROM policy_assets pa JOIN policies p ON p.id = pa.policy_id WHERE p.status = 'Active' AND p.category_id IS NOT NULL)"), {"note": note})
    rows = bind.execute(sa.text(
        "SELECT id, owner_id, photo_file, photo_name, invoice_file, invoice_name, evidence_status, created_at FROM assets WHERE category_id IS NOT NULL")).fetchall()
    ins = sa.text("INSERT INTO asset_evidence (asset_id, kind, stored_name, original_name, content_type, size_bytes, sha256, phash, phash_dct, width, height, quality, exif, flags, "
                  "uploaded_by, uploaded_at, review_status) VALUES (:asset_id, :kind, :stored, :orig, :ct, 0, '', '', '', 0, 0, '{}', '{}', '[]', :owner, :at, :rs)")
    for r in rows:
        rs = "Accepted" if r.evidence_status == "Approved" else "Pending"
        for kind, stored, orig in (("front_photo", r.photo_file, r.photo_name), ("invoice", r.invoice_file, r.invoice_name)):
            if stored:
                ext = "." + stored.rsplit(".", 1)[-1].lower() if "." in stored else ""
                bind.execute(ins, {"asset_id": r.id, "kind": kind, "stored": stored, "orig": orig or stored, "ct": _CT.get(ext, "application/octet-stream"),
                                   "owner": r.owner_id, "at": r.created_at, "rs": rs})


def downgrade() -> None:
    # SQLite cannot drop these columns without rebuilding tables that other rows reference; on a populated SQLite database restore the pre-migration backup instead.
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_column('ai_workflow_outcome')
    with op.batch_alter_table('ai_verification_reports', schema=None) as batch_op:
        batch_op.drop_column('workflow_outcome')
        batch_op.drop_column('authenticity')
        batch_op.drop_column('device_match')
    with op.batch_alter_table('claim_images', schema=None) as batch_op:
        batch_op.drop_column('phash_dct')
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint('fk_assets_evidence_reviewed_by', 'assets', type_='foreignkey')  # on SQLite the foreign key is inline and disappears with its column
    with op.batch_alter_table('assets', schema=None) as batch_op:
        batch_op.drop_column('evidence_review_note')
        batch_op.drop_column('evidence_reviewed_at')
        batch_op.drop_column('evidence_reviewed_by')
        batch_op.drop_column('evidence_status')
    with op.batch_alter_table('asset_evidence', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_asset_evidence_sha256'))
        batch_op.drop_index(batch_op.f('ix_asset_evidence_phash'))
        batch_op.drop_index(batch_op.f('ix_asset_evidence_asset_id'))
    op.drop_table('asset_evidence')
