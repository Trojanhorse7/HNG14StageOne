"""Insighta persisted profile snapshot (immutable once written except admin flows)."""

from django.db import models

from classify.uuid7 import new_uuid7


class Profile(models.Model):
    """Normalized demographic row keyed by UUIDv7 (`id`) with uniqueness on lowercase `name`."""

    id = models.UUIDField(primary_key=True, default=new_uuid7, editable=False)
    name = models.CharField(max_length=255, unique=True)
    gender = models.CharField(max_length=32, db_index=True)
    gender_probability = models.FloatField(db_index=True)
    age = models.PositiveSmallIntegerField(db_index=True)
    age_group = models.CharField(max_length=32, db_index=True)
    country_id = models.CharField(max_length=2, db_index=True)
    country_name = models.CharField(max_length=255, default="")
    country_probability = models.FloatField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["country_id", "age_group", "gender"]),
            models.Index(fields=["-created_at", "-id"]),
        ]
