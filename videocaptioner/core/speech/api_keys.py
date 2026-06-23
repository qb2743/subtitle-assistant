"""API key parsing helpers for speech providers.

Providers such as ElevenLabs accept multiple API keys in a single config
string so callers can rotate between accounts and avoid exhausting one
key's quota. ``parse_api_keys`` splits such a string on the common
separators (ASCII and full-width comma/semicolon plus whitespace).
"""

import re

_SPLIT_RE = re.compile(r"[\s,;，；]+")


def parse_api_keys(key_string: str | None) -> list[str]:
    """Parse a delimited API key string into a list of non-empty keys.

    Supports comma, semicolon, and whitespace separators (ASCII and
    full-width). ``None`` / empty input returns an empty list.
    """
    if not key_string:
        return []
    return [part.strip() for part in _SPLIT_RE.split(key_string) if part.strip()]
