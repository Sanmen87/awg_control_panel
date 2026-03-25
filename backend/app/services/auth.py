from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User


class AuthService:
    def ensure_default_admin(self, db: Session, username: str, password: str) -> User:
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            return existing_user

        user = User(username=username, password_hash=hash_password(password), role="admin", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

