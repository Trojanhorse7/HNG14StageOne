"""Persisted profile aggregates from Genderize, Agify, and Nationalize."""

from django.db import models

from classify.uuid7 import new_uuid7

class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=new_uuid7, editable=False)
    name = models.CharField(max_length=255)
    name_normalized = models.CharField(max_length=255, unique=True, db_index=True)
    gender = models.CharField(max_length=32)
    gender_probability = models.FloatField()
    sample_size = models.PositiveIntegerField()
    age = models.PositiveSmallIntegerField()
    age_group = models.CharField(max_length=32)
    country_id = models.CharField(max_length=8)
    country_probability = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
