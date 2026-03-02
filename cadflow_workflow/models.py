from __future__ import annotations

import hashlib
import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q

User = get_user_model()


class RevisionStatus(models.TextChoices):
    AGUARDANDO_VALIDACAO = "AGUARDANDO_VALIDACAO", "Aguardando validação"
    REVISAO_SOLICITADA = "REVISAO_SOLICITADA", "Revisão solicitada"
    PRONTO_PRODUCAO = "PRONTO_PRODUCAO", "Pronto p/ Produção"
    EM_EXECUCAO = "EM_EXECUCAO", "Em execução"
    TRAVADO = "TRAVADO", "Travado"
    FINALIZADA = "FINALIZADA", "Finalizada"
    OBSOLETA = "OBSOLETA", "Obsoleta (substituída)"


class Part(models.Model):
    code = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, blank=True)
    material = models.CharField(max_length=120, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    need_by = models.DateField(null=True, blank=True)  # prazo/necessidade
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.code


class PartRevision(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name="revisions")
    revision_no = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)

    status = models.CharField(
        max_length=32, choices=RevisionStatus.choices, default=RevisionStatus.AGUARDANDO_VALIDACAO
    )

    # rank decimal p/ reorder no backlog (usado principalmente em PRONTO_PRODUCAO)
    priority_rank = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_revisions")
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["part", "revision_no"], name="uniq_part_revisionno"),
            models.UniqueConstraint(
                fields=["part"],
                condition=Q(is_current=True),
                name="uniq_current_revision_per_part",
            ),
        ]
        indexes = [
                    models.Index(fields=["status"]),
                    models.Index(fields=["is_current"]),
                    models.Index(fields=["part", "status"]),
                ]

    def __str__(self) -> str:
        return f"{self.part.code} rev {self.revision_no}"


def revision_upload_path(instance: "RevisionFile", filename: str) -> str:
    part_code = instance.revision.part.code
    rev = instance.revision.revision_no
    safe_name = os.path.basename(filename)
    return f"{part_code}/rev_{rev}/{instance.uid}__{safe_name}"


class RevisionFile(models.Model):
    revision = models.ForeignKey(PartRevision, on_delete=models.CASCADE, related_name="files")
    uid = models.UUIDField(default=uuid.uuid4, editable=False)

    file = models.FileField(upload_to=revision_upload_path)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="uploaded_files")

    def compute_hash_and_size(self) -> None:
        h = hashlib.sha256()
        self.file.open("rb")
        try:
            size = 0
            for chunk in self.file.chunks():
                size += len(chunk)
                h.update(chunk)
        finally:
            self.file.close()
        self.sha256 = h.hexdigest()
        self.size_bytes = size

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = os.path.basename(self.file.name)

        # calcula só se ainda não calculou (evita recomputar em updates de metadata)
        if self.file and (not self.sha256 or self.size_bytes == 0):
            self.compute_hash_and_size()

        super().save(*args, **kwargs)


class ManufacturingReview(models.Model):
    class Decision(models.TextChoices):
        OK = "OK", "OK p/ construir"
        REVISAR = "REVISAR", "Solicitar nova versão"

    revision = models.OneToOneField(PartRevision, on_delete=models.CASCADE, related_name="mfg_review")
    decision = models.CharField(max_length=16, choices=Decision.choices)
    limitations_text = models.TextField(blank=True)

    decided_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="mfg_reviews")
    decided_at = models.DateTimeField(auto_now_add=True)


class BlockEvent(models.Model):
    revision = models.ForeignKey(PartRevision, on_delete=models.CASCADE, related_name="blocks")

    blocked_from_status = models.CharField(max_length=32, blank=True)  # status antes de virar TRAVADO
    reason = models.TextField()

    blocked_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="blocks_created")
    blocked_at = models.DateTimeField(auto_now_add=True)

    unblocked_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="blocks_resolved"
    )
    unblocked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["revision"],
                condition=Q(unblocked_at__isnull=True),
                name="uniq_active_block_per_revision",
            )
        ]


class AuditEvent(models.Model):
    entity_type = models.CharField(max_length=50)
    entity_id = models.BigIntegerField()
    action = models.CharField(max_length=50)

    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32, blank=True)

    payload_json = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    happened_at = models.DateTimeField(auto_now_add=True)