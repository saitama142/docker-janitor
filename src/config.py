
import json
from pathlib import Path

CONFIG_DIR = Path("/etc/docker-janitor")
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "daemon_sleep_interval_seconds": 86400,  # 24 hours
    "image_age_threshold_days": 30,
}

def load_config() -> dict:
    """Loads the configuration from the JSON file."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            # Ensure all keys are present
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
    except (json.JSONDecodeError, IOError):
        # If file is corrupted or unreadable, save default and return it
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config: dict):
    """Saves the configuration to the JSON file."""
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except IOError:
        # This might happen due to permissions issues, though install script should handle it.
        # In a real app, we'd log this error.
        pass

def get_config_value(key: str):
    """Gets a specific value from the config."""
    return load_config().get(key)

def set_config_value(key: str, value):
    """Sets a specific value in the config."""
    config = load_config()
    config[key] = value
    save_config(config)
