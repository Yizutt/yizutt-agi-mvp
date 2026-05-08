import os
from pathlib import Path


DEFAULT_LANGUAGE_CODE = "cnzh"
SUPPORTED_LANGUAGE_CODES = ("cnzh", "twzh", "en", "ja", "ko", "ar", "ru")

LANGUAGE_ALIASES = {
    "cnzh": "cnzh",
    "zh": "cnzh",
    "zh-cn": "cnzh",
    "zh_hans": "cnzh",
    "zh-hans": "cnzh",
    "zh-hans-cn": "cnzh",
    "cn": "cnzh",
    "hans": "cnzh",
    "simplified": "cnzh",
    "twzh": "twzh",
    "hkzh": "twzh",
    "zh-tw": "twzh",
    "zh-hk": "twzh",
    "zh_hant": "twzh",
    "zh-hant": "twzh",
    "hant": "twzh",
    "traditional": "twzh",
    "en": "en",
    "en-us": "en",
    "english": "en",
    "ja": "ja",
    "jp": "ja",
    "ja-jp": "ja",
    "japanese": "ja",
    "ko": "ko",
    "kr": "ko",
    "ko-kr": "ko",
    "korean": "ko",
    "ar": "ar",
    "arabic": "ar",
    "ru": "ru",
    "ru-ru": "ru",
    "russian": "ru",
}


def normalize_language_code(value: str | None) -> str:
    if not value:
        return DEFAULT_LANGUAGE_CODE
    key = value.strip().lower().replace("_", "-")
    return LANGUAGE_ALIASES.get(key, DEFAULT_LANGUAGE_CODE)


def language_from_entrypoint(argv0: str | None) -> str:
    if not argv0:
        return ""
    stem = Path(argv0).name
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    normalized = stem.lower().replace("-", "_")
    for part in reversed(normalized.split("_")):
        if part.replace("_", "-") in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[part.replace("_", "-")]
    return ""


def resolve_language(explicit: str | None = None, argv0: str | None = None, env_name: str = "YIZUTT_LANG") -> str:
    if explicit:
        return normalize_language_code(explicit)
    env_value = os.getenv(env_name)
    if env_value:
        return normalize_language_code(env_value)
    entry_value = language_from_entrypoint(argv0)
    if entry_value:
        return entry_value
    return DEFAULT_LANGUAGE_CODE
