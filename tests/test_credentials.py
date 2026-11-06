import keyring

from hospital_marketing.credentials import CredentialStore


def test_credential_store_uses_os_keyring_without_echoing_secret(monkeypatch):
    saved = {}
    monkeypatch.setattr(keyring, "set_password", lambda service, username, secret: saved.update({(service, username): secret}))
    monkeypatch.setattr(keyring, "get_password", lambda service, username: saved.get((service, username)))
    monkeypatch.setattr(keyring, "delete_password", lambda service, username: saved.pop((service, username), None))
    store = CredentialStore()

    store.set("openai", "secret-test-key")
    assert store.get("openai") == "secret-test-key"
    store.delete("openai")
    assert store.get("openai") is None
    assert "secret-test-key" not in repr(store)
