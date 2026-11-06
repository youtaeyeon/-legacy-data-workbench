import keyring
from keyring.errors import KeyringError


SERVICE_NAME = "hospital-marketing-mvp"


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore:
    def set(self, provider_id: str, api_key: str) -> None:
        if not api_key.strip():
            raise ValueError("API 키를 입력해 주세요.")
        try:
            keyring.set_password(SERVICE_NAME, provider_id, api_key)
        except (KeyringError, RuntimeError):
            raise CredentialStoreError("OS 자격 증명 저장소에 API 키를 저장하지 못했습니다.") from None

    def get(self, provider_id: str) -> str | None:
        try:
            return keyring.get_password(SERVICE_NAME, provider_id)
        except (KeyringError, RuntimeError):
            raise CredentialStoreError("OS 자격 증명 저장소에서 API 키를 읽지 못했습니다.") from None

    def delete(self, provider_id: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, provider_id)
        except keyring.errors.PasswordDeleteError:
            return
        except (KeyringError, RuntimeError):
            raise CredentialStoreError("OS 자격 증명 저장소에서 API 키를 지우지 못했습니다.") from None
