"""Alembic environment. Uses the application's own engine/DATABASE_URL so migrations always target the configured database."""
from alembic import context

from app import models  # noqa: F401  (register tables)
from app.database import Base, engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
