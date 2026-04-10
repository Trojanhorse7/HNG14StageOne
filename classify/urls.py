from django.urls import path

from classify.views import ClassifyNameView

urlpatterns = [
    path("api/classify", ClassifyNameView.as_view()),
    path("api/classify/", ClassifyNameView.as_view()),
]
