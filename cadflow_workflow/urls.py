from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),

     # CAD
    path("cad/", views.cad_dashboard, name="cad_dashboard"),
    path("cad/novo-envio/", views.cad_new_submission, name="cad_new_submission"),
    path("cad/revision/<int:revision_id>/upload/", views.cad_upload_files, name="cad_upload_files"),
    path("cad/arquivo/<int:file_id>/download/", views.cad_download_file, name="cad_download_file"),

    # Produção
    path("producao/", views.production_dashboard, name="production_dashboard"),
]
