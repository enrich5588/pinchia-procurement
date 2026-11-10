"""Small, literal .env loader. Existing process variables take precedence."""
import os
from django.core.exceptions import ImproperlyConfigured


def load_env(path):
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key.isidentifier():
            raise ImproperlyConfigured(f"Invalid .env entry at line {number}")
        if value.startswith(("'", '\"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ImproperlyConfigured(f"Unclosed .env quote at line {number}")
            value = value[1:-1]
        os.environ.setdefault(key, value)


def env_bool(name, default=False):
    value = os.environ.get(name, str(default)).lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ImproperlyConfigured(f"{name} must be true or false")
    return value in {"true", "1", "yes"}


def env_list(name, default=""):
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]
