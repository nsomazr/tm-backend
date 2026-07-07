"""Tests for Tanzania phone normalization."""

from django.test import TestCase

from apps.accounts.phone_utils import beem_dest_addr, normalize_tz_phone


class PhoneUtilsTests(TestCase):
    def test_normalize_local_format(self):
        self.assertEqual(normalize_tz_phone("0712345678"), "255712345678")

    def test_normalize_international(self):
        self.assertEqual(normalize_tz_phone("+255712345678"), "255712345678")
        self.assertEqual(normalize_tz_phone("255712345678"), "255712345678")

    def test_reject_invalid(self):
        self.assertIsNone(normalize_tz_phone("0812345678"))
        self.assertIsNone(normalize_tz_phone("12345"))

    def test_beem_dest_addr(self):
        self.assertEqual(beem_dest_addr("0712345678"), "255712345678")
