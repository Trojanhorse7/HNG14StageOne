"""Regression tests for cache key generation and CSV ingest rules (LocMem cache override)."""

from __future__ import annotations

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from classify.filter_canonical import (
    canonical_filters,
    profile_list_search_cache_key,
)
from classify.models import Profile


def csv_file(content: bytes) -> SimpleUploadedFile:
    """Tiny helper so multipart posts include a named file object."""
    return SimpleUploadedFile("profiles.csv", content, content_type="text/csv")


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "profile_cache_tests",
            "TIMEOUT": 90,
        }
    },
)
class ProfileCsvImportTests(TestCase):
    """Role-gated CSV endpoint: duplicate handling inside one upload plus analyst denial."""

    headers = {"HTTP_X_API_VERSION": "1"}

    def setUp(self) -> None:
        cache.clear()
        self.admin = User.objects.create(
            github_id="gh_admin",
            username="administrator",
            role=UserRole.ADMIN,
            is_active=True,
        )
        self.analyst = User.objects.create(
            github_id="gh_analyst",
            username="alice",
            role=UserRole.ANALYST,
            is_active=True,
        )
        self.client = APIClient()
        Profile.objects.all().delete()

    def sample_row(self, name_suffix: str = "1") -> str:
        return (
            f"n_test_{name_suffix},male,0.9,29,adult,NG,Nigeria,0.95"
        )

    def test_duplicate_name_within_file_counts(self):
        hdr = ",".join(
            (
                "name",
                "gender",
                "gender_probability",
                "age",
                "age_group",
                "country_id",
                "country_name",
                "country_probability",
            )
        )
        body = "\n".join([hdr, self.sample_row("d1"), self.sample_row("d1")])
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            "/api/profiles/import",
            {"file": csv_file(body.encode("utf-8"))},
            format="multipart",
            **self.headers,
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload["total_rows"], 2)
        self.assertEqual(payload["inserted"], 1)
        self.assertEqual(payload["skipped"], 1)
        self.assertEqual(payload["reasons"]["duplicate_name"], 1)

    def test_analyst_import_forbidden(self):
        hdr = "name,gender,gender_probability,age,age_group,country_id,country_name,country_probability"
        self.client.force_authenticate(self.analyst)
        r = self.client.post(
            "/api/profiles/import",
            {"file": csv_file(f"{hdr}\n{self.sample_row()}".encode("utf-8"))},
            format="multipart",
            **self.headers,
        )
        self.assertEqual(r.status_code, 403)


class CanonicalFilterTests(TestCase):
    """Ensure canonical serialization + cache buckets stay stable between endpoints."""

    def test_list_equiv_canonical_same_key(self):
        a = canonical_filters({"country_id": "ng", "gender": "MALE"})
        b = canonical_filters({"country_id": "NG", "gender": "male"})
        self.assertEqual(a, b)

    def test_search_vs_list_different_bucket(self):
        fj = '{"country_id":"NG","gender":"male"}'
        k_list = profile_list_search_cache_key(
            kind="list",
            filters_json=fj,
            page=1,
            limit=10,
            sort_by="created_at",
            order="desc",
        )
        k_search = profile_list_search_cache_key(
            kind="search",
            filters_json=fj,
            page=1,
            limit=10,
            sort_by="created_at",
            order="desc",
        )
        self.assertNotEqual(k_list, k_search)
