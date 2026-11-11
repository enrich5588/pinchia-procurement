"""Check the login view and database through the running WSGI server."""
import os
import urllib.request

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
import django

django.setup()
from django.conf import settings
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT 1")
request = urllib.request.Request(
    "http://127.0.0.1:8000/accounts/login/",
    headers={"Host": settings.ALLOWED_HOSTS[0], "X-Forwarded-Proto": "https"},
)
with urllib.request.urlopen(request, timeout=4) as response:
    if response.status != 200:
        raise SystemExit(f"Unexpected login status: {response.status}")
