#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -n "${PYTHON_BIN:-}" ]; then
    python_bin="$PYTHON_BIN"
elif [ -x /opt/venv/bin/python ]; then
    python_bin=/opt/venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    python_bin=python3
else
    python_bin=python
fi
# Production must supply a WSGI/ASGI server command.
if [ "$#" -eq 0 ] && [ "${DJANGO_SETTINGS_MODULE:-}" = "config.settings.production" ]; then
    echo "Supply a WSGI/ASGI server command using config.wsgi:application or config.asgi:application" >&2
    exit 1
fi
"$python_bin" manage.py migrate --noinput
"$python_bin" manage.py maintain_operation_logs
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
exec "$python_bin" manage.py runserver "0.0.0.0:${PORT:-8000}"
