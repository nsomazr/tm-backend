"""Tests for reports module expansion."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.minerals.models import Mineral
from apps.reports.access import user_can_download_report, user_has_report_detail_access
from apps.reports.contextual import find_contextual_reports
from apps.reports.models import Report
from apps.reports.rag_service import _cosine_similarity, _split_text

User = get_user_model()


class ReportAccessTests(TestCase):
    def setUp(self):
        self.mineral = Mineral.objects.create(name="Gold", slug="gold", is_active=True)
        self.free_report = Report.objects.create(
            title="Free report",
            slug="free-report",
            mineral=self.mineral,
            access_type=Report.AccessType.FREE,
            report_format=Report.ReportFormat.PDF,
            is_active=True,
        )
        self.paid_report = Report.objects.create(
            title="Paid report",
            slug="paid-report",
            mineral=self.mineral,
            access_type=Report.AccessType.PAID,
            price=1000,
            is_active=True,
        )
        self.user = User.objects.create_user(username="tester", password="pass")

    def test_free_report_detail_access_anonymous(self):
        self.assertTrue(user_has_report_detail_access(None, self.free_report))

    def test_paid_report_blocks_anonymous(self):
        self.assertFalse(user_has_report_detail_access(None, self.paid_report))

    def test_free_report_download_authenticated(self):
        allowed, source = user_can_download_report(self.user, self.free_report)
        self.assertTrue(allowed)
        self.assertEqual(source, "free")


class ContextualReportsTests(TestCase):
    def setUp(self):
        self.mineral = Mineral.objects.create(name="Copper", slug="copper", is_active=True)
        self.report = Report.objects.create(
            title="Copper belt",
            slug="copper-belt",
            mineral=self.mineral,
            center_lat=-5.0,
            center_lng=32.0,
            bounding_box={"west": 31.5, "south": -5.5, "east": 32.5, "north": -4.5},
            is_active=True,
        )

    def test_finds_report_by_point_and_mineral(self):
        results = find_contextual_reports(lat=-5.1, lng=32.1, mineral_slug="copper", limit=5)
        self.assertTrue(results)
        self.assertEqual(results[0]["slug"], "copper-belt")


class RagServiceTests(TestCase):
    def test_split_text_chunks(self):
        text = "word " * 200
        chunks = _split_text(text)
        self.assertGreater(len(chunks), 1)

    def test_cosine_similarity_identical(self):
        vector = [0.1, 0.2, 0.3]
        self.assertAlmostEqual(_cosine_similarity(vector, vector), 1.0)
