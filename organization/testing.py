"""Explicit release-state fixture for business workflow and permission tests."""
from django.test import TestCase

from .models import FeaturePanel


class OpenPanelsTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Class-level TestCase transactions restore developing defaults afterwards.
        FeaturePanel.objects.update(status=FeaturePanel.Status.OPEN)
