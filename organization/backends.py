from django.contrib.auth.backends import ModelBackend


class MicrosoftBackend(ModelBackend):
    """Load authenticated sessions and permissions without accepting passwords."""
    def authenticate(self, request, username=None, password=None, **kwargs):
        return None
