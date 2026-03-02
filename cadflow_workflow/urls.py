from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),

     # CAD
    path("cad/", views.cad_dashboard, name="cad_dashboard"),
    path("cad/revision/<int:revision_id>/upload/", views.cad_upload_files, name="cad_upload_files"),

    # Produção
    path("producao/", views.production_dashboard, name="production_dashboard"),
]