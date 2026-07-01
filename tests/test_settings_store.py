import pytest

import settings_store


@pytest.fixture(autouse=True)
def isolated_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "CONFIG_FILE", str(tmp_path / "config.json"))


def test_not_configured_by_default():
    assert settings_store.is_configured() is False


def test_set_up_persists_config_and_hashes_password():
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "secret123")

    assert settings_store.is_configured() is True
    config = settings_store.load_config()
    assert config["discord_webhook_url"] == "https://discord.example/webhook"
    assert config["alert_city"] == "Tours"
    assert config["alert_radius_km"] == 50
    assert config["password_hash"] != "secret123"  # never stored in clear


def test_set_up_refuses_to_overwrite_existing_config():
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "secret123")

    with pytest.raises(ValueError):
        settings_store.set_up("https://evil.example/webhook", "Paris", 10, "hijack")

    assert settings_store.load_config()["discord_webhook_url"] == "https://discord.example/webhook"


def test_verify_password_correct_and_incorrect():
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "secret123")

    assert settings_store.verify_password("secret123") is True
    assert settings_store.verify_password("wrong") is False


def test_verify_password_before_any_setup_is_always_false():
    assert settings_store.verify_password("anything") is False
    assert settings_store.verify_password("") is False


def test_update_changes_values_without_touching_password():
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "secret123")

    settings_store.update("https://discord.example/new-webhook", "Paris", 20)

    config = settings_store.load_config()
    assert config["discord_webhook_url"] == "https://discord.example/new-webhook"
    assert config["alert_city"] == "Paris"
    assert config["alert_radius_km"] == 20
    assert settings_store.verify_password("secret123") is True


def test_update_can_change_password():
    settings_store.set_up("https://discord.example/webhook", "Tours", 50, "secret123")

    settings_store.update("https://discord.example/webhook", "Tours", 50, new_password="newpass")

    assert settings_store.verify_password("secret123") is False
    assert settings_store.verify_password("newpass") is True
