# Generated manually for accounts app

import django.db.models.deletion
from django.db import migrations, models

import classify.uuid7


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=classify.uuid7.new_uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("github_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("username", models.CharField(max_length=255, unique=True)),
                ("email", models.CharField(blank=True, max_length=255)),
                ("avatar_url", models.URLField(blank=True, max_length=500)),
                (
                    "role",
                    models.CharField(
                        choices=[("admin", "admin"), ("analyst", "analyst")],
                        db_index=True,
                        default="analyst",
                        max_length=32,
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="GitHubOAuthState",
            fields=[
                ("state", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("code_verifier", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
        migrations.CreateModel(
            name="RefreshToken",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=classify.uuid7.new_uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("token_hash", models.CharField(db_index=True, max_length=64)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refresh_tokens",
                        to="accounts.user",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="githuboauthstate",
            index=models.Index(fields=["expires_at"], name="accounts_gi_expires_3f8a9d_idx"),
        ),
        migrations.AddIndex(
            model_name="refreshtoken",
            index=models.Index(
                fields=["token_hash", "revoked_at"],
                name="accounts_re_token_h_2c1e4b_idx",
            ),
        ),
    ]
