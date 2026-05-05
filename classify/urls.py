from django.urls import path

from classify.export_views import ProfileExportView
from classify.import_views import ProfileCsvImportView
from classify.profile_views import (
    ProfileDetailView,
    ProfileListCreateView,
    ProfileSearchView,
)
from classify.views import ClassifyNameView

urlpatterns = [
    path("api/classify", ClassifyNameView.as_view()),
    path("api/classify/", ClassifyNameView.as_view()),
    path("api/profiles/search", ProfileSearchView.as_view()),
    path("api/profiles/search/", ProfileSearchView.as_view()),
    path("api/profiles/export", ProfileExportView.as_view()),
    path("api/profiles/export/", ProfileExportView.as_view()),
    path("api/profiles/import", ProfileCsvImportView.as_view()),
    path("api/profiles/import/", ProfileCsvImportView.as_view()),
    path("api/profiles", ProfileListCreateView.as_view()),
    path("api/profiles/", ProfileListCreateView.as_view()),
    path("api/profiles/<uuid:profile_id>", ProfileDetailView.as_view()),
    path("api/profiles/<uuid:profile_id>/", ProfileDetailView.as_view()),
]
