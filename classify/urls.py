from django.urls import path

from classify.profile_views import ProfileDetailView, ProfileListCreateView
from classify.views import ClassifyNameView

urlpatterns = [
    path("api/classify", ClassifyNameView.as_view()),
    path("api/classify/", ClassifyNameView.as_view()),
    path("api/profiles", ProfileListCreateView.as_view()),
    path("api/profiles/", ProfileListCreateView.as_view()),
    path("api/profiles/<uuid:profile_id>", ProfileDetailView.as_view()),
    path("api/profiles/<uuid:profile_id>/", ProfileDetailView.as_view()),
]
