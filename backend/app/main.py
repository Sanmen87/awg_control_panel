from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from app.api.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.auth import AuthService


def create_application() -> FastAPI:
    # Main API entrypoint: wires HTTP routes, CORS, schema init, and default admin bootstrap.
    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.on_event("startup")
    def startup() -> None:
        inspector = inspect(engine)
        alembic_config = Config("alembic.ini")
        known_tables = set(Base.metadata.tables.keys())
        existing_tables = set(inspector.get_table_names())
        has_schema = bool(existing_tables & known_tables)
        has_alembic_version = "alembic_version" in existing_tables

        # For fresh databases we run migrations normally. If the schema already exists from
        # earlier create_all-based local runs, we stamp the current head to avoid replaying
        # the initial enum/table creation migrations over an existing schema.
        alembic_config = Config("alembic.ini")
        if has_schema and not has_alembic_version:
            Base.metadata.create_all(bind=engine)
            command.stamp(alembic_config, "head")
        else:
            command.upgrade(alembic_config, "head")

        # Keep create_all as a safety net for fresh local databases and test runs.
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            AuthService().ensure_default_admin(
                db,
                username=settings.default_admin_username,
                password=settings.default_admin_password,
            )
        finally:
            db.close()

    return app


app = create_application()
