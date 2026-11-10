from django.urls import path

from . import views

urlpatterns = [
    path("", views.supply_list, name="supplies"),
    path("new/", views.supply_create, name="supply_create"),
    path("bulk-return/", views.supply_bulk_return, name="supply_bulk_return"),
    path("bulk-processing/", views.supply_bulk_processing, name="supply_bulk_processing"),
    path("bulk-complete/", views.supply_bulk_complete, name="supply_bulk_complete"),
    path("<int:pk>/", views.supply_detail, name="supply_detail"),
    path("<int:pk>/edit/", views.supply_edit, name="supply_edit"),
    path("<int:pk>/return/", views.supply_return, name="supply_return"),
    path("<int:pk>/processing/", views.supply_processing, name="supply_processing"),
    path("<int:pk>/approve/", views.supply_approve, name="supply_approve"),
    path("<int:pk>/cancel/", views.supply_cancel, name="supply_cancel"),
    path("equipment/", views.equipment_list, name="equipment_procurement"),
    path("equipment/new/", views.equipment_create, name="equipment_create"),
    path("equipment/bulk-return/", views.equipment_bulk_return, name="equipment_bulk_return"),
    path("equipment/bulk-processing/", views.equipment_bulk_processing, name="equipment_bulk_processing"),
    path("equipment/bulk-complete/", views.equipment_bulk_complete, name="equipment_bulk_complete"),
    path("equipment/<int:pk>/", views.equipment_detail, name="equipment_detail"),
    path("equipment/<int:pk>/edit/", views.equipment_edit, name="equipment_edit"),
    path("equipment/<int:pk>/return/", views.equipment_return, name="equipment_return"),
    path("equipment/<int:pk>/processing/", views.equipment_processing, name="equipment_processing"),
    path("equipment/<int:pk>/complete/", views.equipment_complete, name="equipment_complete"),
    path("equipment/<int:pk>/cancel/", views.equipment_cancel, name="equipment_cancel"),
]
