from __future__ import annotations

import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import ManufacturingReview, Part, PartRevision, RevisionFile, RevisionStatus


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CadDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.cad_group = Group.objects.create(name="CAD")
        self.user = User.objects.create_user(username="cad", password="123")
        self.user.groups.add(self.cad_group)
        self.client.login(username="cad", password="123")

    def test_new_submission_creates_part_revision_and_files(self):
        file1 = SimpleUploadedFile("desenho.pdf", b"pdf-content", content_type="application/pdf")
        file2 = SimpleUploadedFile("modelo.step", b"step-content", content_type="application/octet-stream")

        response = self.client.post(
            reverse("cad_new_submission"),
            {
                "code": "P-100",
                "description": "Peca de teste",
                "material": "Aco",
                "quantity": 2,
                "revision_note": "primeira revisao",
                "files": [file1, file2],
            },
        )

        self.assertEqual(response.status_code, 302)
        part = Part.objects.get(code="P-100")
        rev = PartRevision.objects.get(part=part, is_current=True)
        self.assertEqual(rev.revision_no, 1)
        self.assertEqual(rev.status, RevisionStatus.AGUARDANDO_VALIDACAO)
        self.assertEqual(RevisionFile.objects.filter(revision=rev).count(), 2)

    def test_dashboard_lists_requested_reviews(self):
        part = Part.objects.create(code="P-200")
        rev = PartRevision.objects.create(
            part=part,
            revision_no=1,
            is_current=True,
            status=RevisionStatus.REVISAO_SOLICITADA,
            created_by=self.user,
        )
        ManufacturingReview.objects.create(
            revision=rev,
            decision=ManufacturingReview.Decision.REVISAR,
            limitations_text="Falta cota crítica",
            decided_by=self.user,
        )

        response = self.client.get(reverse("cad_dashboard"))

        self.assertContains(response, "Falta cota crítica")
        self.assertContains(response, "P-200")

    def test_upload_page_shows_file_list_and_download(self):
        part = Part.objects.create(code="P-300")
        rev = PartRevision.objects.create(
            part=part,
            revision_no=1,
            is_current=True,
            status=RevisionStatus.AGUARDANDO_VALIDACAO,
            created_by=self.user,
        )
        revision_file = RevisionFile.objects.create(
            revision=rev,
            file=SimpleUploadedFile("arquivo.dxf", b"dxf-content"),
            original_name="arquivo.dxf",
            uploaded_by=self.user,
        )

        response = self.client.get(reverse("cad_upload_files", args=[rev.id]))
        self.assertContains(response, "arquivo.dxf")

        download = self.client.get(reverse("cad_download_file", args=[revision_file.id]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Disposition"].startswith("attachment;"), True)
