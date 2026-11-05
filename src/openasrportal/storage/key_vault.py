"""Authenticated at-rest storage for explicitly admin-revealable client keys."""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class VaultError(RuntimeError):
    pass


class KeyVault:
    def __init__(self, directory):
        self.path = Path(directory) / "asr-key-vault.key"

    def cipher(self, *, create=False):
        if create and not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(Fernet.generate_key())
                    output.flush()
                    os.fsync(output.fileno())
        try:
            data = self.path.read_bytes()
            os.chmod(self.path, 0o600)
            return Fernet(data)
        except (OSError, ValueError) as error:
            raise VaultError(
                "ASR Key 密钥保管文件不可用，请从备份恢复 asr-key-vault.key"
            ) from error

    def encrypt(self, value):
        return self.cipher(create=True).encrypt(value.encode()).decode("ascii")

    def decrypt(self, value):
        try:
            return self.cipher().decrypt(value.encode("ascii")).decode()
        except (InvalidToken, UnicodeError) as error:
            raise VaultError("无法解密此 ASR Key，请检查密钥保管文件是否与数据库匹配") from error
