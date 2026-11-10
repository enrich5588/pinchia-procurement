from django.urls import path

from . import views


urlpatterns = [
    path("", views.task_list, name="collaboration_task_list"),
    path("<int:pk>/", views.task_detail, name="collaboration_task_detail"),
    path("<int:pk>/processing/", views.task_processing, name="collaboration_task_processing"),
    path("<int:pk>/complete/", views.task_complete, name="collaboration_task_complete"),
    path("<int:pk>/return/", views.task_return, name="collaboration_task_return"),
    path("<int:pk>/withdraw/", views.task_withdraw, name="collaboration_task_withdraw"),
    path(
        "forward/equipment/<int:pk>/",
        views.forward_equipment,
        name="collaboration_forward_equipment",
    ),
]
