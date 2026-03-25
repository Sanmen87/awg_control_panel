from app.core.security import decrypt_value, encrypt_value
from app.models.server import Server


class ServerCredentialsService:
    def apply_secrets(
        self,
        server: Server,
        *,
        ssh_password: str | None = None,
        ssh_private_key: str | None = None,
        sudo_password: str | None = None,
    ) -> Server:
        if ssh_password:
            server.ssh_password_encrypted = encrypt_value(ssh_password)
        if ssh_private_key:
            server.ssh_private_key_encrypted = encrypt_value(ssh_private_key)
        if sudo_password:
            server.sudo_password_encrypted = encrypt_value(sudo_password)
        return server

    def get_ssh_password(self, server: Server) -> str | None:
        if not server.ssh_password_encrypted:
            return None
        return decrypt_value(server.ssh_password_encrypted)

    def get_private_key(self, server: Server) -> str | None:
        if not server.ssh_private_key_encrypted:
            return None
        return decrypt_value(server.ssh_private_key_encrypted)

    def get_sudo_password(self, server: Server) -> str | None:
        if not server.sudo_password_encrypted:
            return None
        return decrypt_value(server.sudo_password_encrypted)
