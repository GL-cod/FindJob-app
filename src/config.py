from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


REQUIRED_CONFIG = {
    "api": {
        "search_url": str,
        "api_key": str,
    },
    "scraping": {
        "max_days": int,
        "batch_size": int,
    },
    "relevance": {
        "gemini_api_key": str,
        "user_description": str,
        "models": list
    },
    "telegram": {
        "bot_token": str,
        "chat_id": str,
    },
}


def required_sections():
    """Telegram is only needed when its alerts are on (TELEGRAM_ENABLED=true)."""
    from .telegram import enabled
    return {k: v for k, v in REQUIRED_CONFIG.items() if k != "telegram" or enabled()}


def validate_config(raw_config):
    missing = []
    wrong_type_or_input = []

    for section, fields in required_sections().items():
        if section not in raw_config:
            missing.append(section)
            continue

        if not isinstance(raw_config[section], dict):
            wrong_type_or_input.append(
                f"{section} (expected dict, got {type(raw_config[section]).__name__})"
            )
            continue

        for key, expected_type in fields.items():
            if key not in raw_config[section]:
                missing.append(f"{section}.{key}")
                continue

            value = raw_config[section][key]

            if not isinstance(value, expected_type):
                wrong_type_or_input.append(
                    f"{section}.{key} "
                    f"(expected {expected_type.__name__}, got {type(value).__name__})"
                )
            elif not value:
                wrong_type_or_input.append(
                    f"{section}.{key}"
                    f"(expected non-empty value, got {value!r})"
                )


    if missing or wrong_type_or_input:
        errors = []

        if missing:
            errors.append(
                "Missing configuration entries:\n"
                + "\n".join(f"  - {x}" for x in missing)
            )

        if wrong_type_or_input:
            errors.append(
                "Wrong configuration:\n"
                + "\n".join(f"  - {x}" for x in wrong_type_or_input)
            )

        raise ValueError("\n\n".join(errors))


def load_config(path=CONFIG_PATH):
    if not path.exists():
        raise ValueError(
            f"Configuration file not found at {path}. "
            "Copy 'config.example.yaml' to 'config.yaml' and fill it in."
        )

    with open(path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    validate_config(raw_config)

    config_dict = {
        "SEARCH_URL": raw_config["api"]["search_url"],
        "HEADERS": {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": "https://mon-vie-via.businessfrance.fr",
            "Referer": "https://mon-vie-via.businessfrance.fr/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",  
            "X-API-KEY": raw_config["api"]["api_key"],
        },
        "MAX_DAYS": raw_config["scraping"]["max_days"],
        "BATCH_SIZE": raw_config["scraping"]["batch_size"],
        "USER_PROFILE": raw_config["relevance"]["user_description"],
        "GEMINI_API_KEY": raw_config["relevance"]["gemini_api_key"],
        "GEMINI_MODELS": raw_config["relevance"]["models"],
        "TELEGRAM_BOT_TOKEN": str((raw_config.get("telegram") or {}).get("bot_token") or ""),
        "TELEGRAM_CHAT_ID": str((raw_config.get("telegram") or {}).get("chat_id") or ""),
    }

    return config_dict