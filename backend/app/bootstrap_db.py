from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.auth import AuthService


def main() -> None:
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")

    db = SessionLocal()
    try:
        AuthService().ensure_default_admin(
            db,
            username=settings.default_admin_username,
            password=settings.default_admin_password,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
