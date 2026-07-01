import json
import os

from werkzeug.security import check_password_hash, generate_password_hash

CONFIG_FILE = "cache/config.json"

DEFAULTS = {
    "discord_webhook_url": "",
    "alert_city": "",
    "alert_radius_km": 50,
    "password_hash": "",
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return dict(DEFAULTS)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {**DEFAULTS, **data}


def save_config(config: dict) -> None:
    os.makedirs("cache", exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def is_configured() -> bool:
    return bool(load_config()["password_hash"])


def verify_password(password: str) -> bool:
    if not password:
        return False
    config = load_config()
    if not config["password_hash"]:
        return False
    return check_password_hash(config["password_hash"], password)


def set_up(discord_webhook_url: str, alert_city: str, alert_radius_km: float, password: str) -> None:
    """First-time setup only. Refuses to run again once a password is set, so
    a second visitor can't silently overwrite an already-configured instance."""
    if is_configured():
        raise ValueError("already configured")
    save_config({
        "discord_webhook_url": discord_webhook_url,
        "alert_city": alert_city,
        "alert_radius_km": alert_radius_km,
        "password_hash": generate_password_hash(password),
    })


def update(discord_webhook_url: str, alert_city: str, alert_radius_km: float, new_password: str | None = None) -> None:
    config = load_config()
    config["discord_webhook_url"] = discord_webhook_url
    config["alert_city"] = alert_city
    config["alert_radius_km"] = alert_radius_km
    if new_password:
        config["password_hash"] = generate_password_hash(new_password)
    save_config(config)
