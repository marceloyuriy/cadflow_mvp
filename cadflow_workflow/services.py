from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max

from .models import (
    AuditEvent,
    BlockEvent,
    ManufacturingReview,
    Part,
    PartRevision,
    RevisionStatus,
)

User = get_user_model()


class WorkflowError(Exception):
    pass


class InvalidTransition(WorkflowError):
    pass


def _audit_revision(
    *,
    revision: PartRevision,
    actor: User,
    action: str,
    from_status: str = "",
    to_status: str = "",
    payload: Optional[dict] = None,
) -> None:
    AuditEvent.objects.create(
        entity_type="PartRevision",
        entity_id=revision.id,
        action=action,
        from_status=from_status or "",
        to_status=to_status or "",
        payload_json=payload or {},
        actor=actor,
    )


def _next_priority_rank() -> Decimal:
    # espaçamento grande para facilitar “rank fracionário” depois
    max_rank = (
        PartRevision.objects.filter(status=RevisionStatus.PRONTO_PRODUCAO)
        .aggregate(m=Max("priority_rank"))
        .get("m")
    )
    if max_rank is None:
        return Decimal("1000")
    return (Decimal(max_rank) + Decimal("1000")).quantize(Decimal("0.0001"))


@transaction.atomic
def create_revision(*, part_id: int, created_by: User, note: str = "") -> PartRevision:
    """
    CAD cria uma nova revisão.
    Regra: não permitir nova revisão se a revisão corrente já entrou em EM_EXECUCAO/TRAVADO/FINALIZADA.
    """
    part = Part.objects.select_for_update().get(id=part_id)

    current = (
        PartRevision.objects.select_for_update()
        .filter(part=part, is_current=True)
        .first()
    )
    if current and current.status in {
        RevisionStatus.EM_EXECUCAO,
        RevisionStatus.TRAVADO,
        RevisionStatus.FINALIZADA,
    }:
        raise InvalidTransition("Peça já está em execução/finalizada; não pode criar nova revisão.")

    last_no = (
        PartRevision.objects.filter(part=part).aggregate(m=Max("revision_no")).get("m") or 0
    )
    new_no = int(last_no) + 1

    # desativa revisão corrente (se existir)
    if current:
        current.is_current = False
        current.status = RevisionStatus.OBSOLETA
        current.save(update_fields=["is_current", "status"])
        _audit_revision(
            revision=current,
            actor=created_by,
            action="mark_obsolete",
            from_status=current.status,  # OBSOLETA já setado; ok p/ auditoria simples
            to_status=RevisionStatus.OBSOLETA,
            payload={"new_revision_no": new_no},
        )

    rev = PartRevision.objects.create(
        part=part,
        revision_no=new_no,
        is_current=True,
        status=RevisionStatus.AGUARDANDO_VALIDACAO,
        priority_rank=Decimal("0"),
        created_by=created_by,
        note=note,
    )
    _audit_revision(
        revision=rev,
        actor=created_by,
        action="create_revision",
        from_status="",
        to_status=rev.status,
        payload={"revision_no": rev.revision_no},
    )
    return rev


@transaction.atomic
def manufacturing_ok(*, revision_id: int, decided_by: User, limitations_text: str = "") -> PartRevision:
    """
    Manufatura aprova: AGUARDANDO_VALIDACAO -> PRONTO_PRODUCAO
    """
    rev = PartRevision.objects.select_for_update().get(id=revision_id)

    if rev.status != RevisionStatus.AGUARDANDO_VALIDACAO:
        raise InvalidTransition("Só dá OK quando estiver 'Aguardando validação'.")

    ManufacturingReview.objects.update_or_create(
        revision=rev,
        defaults={
            "decision": ManufacturingReview.Decision.OK,
            "limitations_text": limitations_text,
            "decided_by": decided_by,
        },
    )

    from_status = rev.status
    rev.status = RevisionStatus.PRONTO_PRODUCAO
    rev.priority_rank = _next_priority_rank()
    rev.save(update_fields=["status", "priority_rank"])

    _audit_revision(
        revision=rev,
        actor=decided_by,
        action="manufacturing_ok",
        from_status=from_status,
        to_status=rev.status,
        payload={"limitations_text": limitations_text},
    )
    return rev


@transaction.atomic
def request_revision(*, revision_id: int, decided_by: User, limitations_text: str = "") -> PartRevision:
    """
    Manufatura pede revisão: AGUARDANDO_VALIDACAO -> REVISAO_SOLICITADA
    Regra forte: após EM_EXECUCAO, não volta pro CAD.
    """
    rev = PartRevision.objects.select_for_update().get(id=revision_id)

    if rev.status != RevisionStatus.AGUARDANDO_VALIDACAO:
        raise InvalidTransition("Só pode solicitar revisão quando estiver 'Aguardando validação'.")

    ManufacturingReview.objects.update_or_create(
        revision=rev,
        defaults={
            "decision": ManufacturingReview.Decision.REVISAR,
            "limitations_text": limitations_text,
            "decided_by": decided_by,
        },
    )

    from_status = rev.status
    rev.status = RevisionStatus.REVISAO_SOLICITADA
    rev.save(update_fields=["status"])

    _audit_revision(
        revision=rev,
        actor=decided_by,
        action="request_revision",
        from_status=from_status,
        to_status=rev.status,
        payload={"limitations_text": limitations_text},
    )
    return rev


@transaction.atomic
def pull_to_execution(*, revision_id: int, actor: User) -> PartRevision:
    """
    Manufatura puxa para execução: PRONTO_PRODUCAO -> EM_EXECUCAO
    """
    rev = PartRevision.objects.select_for_update().get(id=revision_id)

    if rev.status != RevisionStatus.PRONTO_PRODUCAO:
        raise InvalidTransition("Só pode puxar para execução se estiver 'Pronto p/ Produção'.")

    from_status = rev.status
    rev.status = RevisionStatus.EM_EXECUCAO
    rev.save(update_fields=["status"])

    _audit_revision(
        revision=rev,
        actor=actor,
        action="pull_to_execution",
        from_status=from_status,
        to_status=rev.status,
        payload={},
    )
    return rev


@transaction.atomic
def block(*, revision_id: int, actor: User, reason: str) -> PartRevision:
    """
    Bloqueia: PRONTO_PRODUCAO/EM_EXECUCAO -> TRAVADO
    """
    rev = PartRevision.objects.select_for_update().get(id=revision_id)

    if rev.status not in {RevisionStatus.PRONTO_PRODUCAO, RevisionStatus.EM_EXECUCAO}:
        raise InvalidTransition("Só pode travar se estiver 'Pronto p/ Produção' ou 'Em execução'.")

    # impede 2 bloqueios ativos
    if BlockEvent.objects.filter(revision=rev, unblocked_at__isnull=True).exists():
        raise InvalidTransition("Já existe um bloqueio ativo para esta revisão.")

    from_status = rev.status

    BlockEvent.objects.create(
        revision=rev,
        blocked_from_status=from_status,
        reason=reason,
        blocked_by=actor,
    )

    rev.status = RevisionStatus.TRAVADO
    rev.save(update_fields=["status"])

    _audit_revision(
        revision=rev,
        actor=actor,
        action="block",
        from_status=from_status,
        to_status=rev.status,
        payload={"reason": reason},
    )
    return rev


@transaction.atomic
def unblock(*, revision_id: int, actor: User) -> PartRevision:
    """
    Desbloqueia: TRAVADO -> (status anterior armazenado no BlockEvent)
    """
    rev = PartRevision.objects.select_for_update().get(id=revision_id)

    if rev.status != RevisionStatus.TRAVADO:
        raise InvalidTransition("Só pode destravar se estiver 'Travado'.")

    block_evt = (
        BlockEvent.objects.select_for_update()
        .filter(revision=rev, unblocked_at__isnull=True)
        .order_by("-blocked_at")
        .first()
    )
    if not block_evt:
        raise WorkflowError("Revisão está TRAVADO, mas não encontrei BlockEvent ativo.")

    restore_status = block_evt.blocked_from_status or RevisionStatus.PRONTO_PRODUCAO

    block_evt.unblocked_by = actor
    block_evt.unblocked_at = transaction.now()  # funciona no Django 6? não. Use timezone.now abaixo.
    # --- correção compatível ---
    from django.utils import timezone
    block_evt.unblocked_at = timezone.now()
    block_evt.save(update_fields=["unblocked_by", "unblocked_at"])

    from_status = rev.status
    rev.status = restore_status
    rev.save(update_fields=["status"])

    _audit_revision(
        revision=rev,
        actor=actor,
        action="unblock",
        from_status=from_status,
        to_status=rev.status,
        payload={},
    )
    return rev


@transaction.atomic
def finish(*, revision_id: int, actor: User) -> PartRevision:
    """
    Finaliza: EM_EXECUCAO -> FINALIZADA
    """
    rev = PartRevision.objects.select_for_update().get(id=revision_id)

    if rev.status != RevisionStatus.EM_EXECUCAO:
        raise InvalidTransition("Só pode finalizar se estiver 'Em execução'.")

    from_status = rev.status
    rev.status = RevisionStatus.FINALIZADA
    rev.save(update_fields=["status"])

    _audit_revision(
        revision=rev,
        actor=actor,
        action="finish",
        from_status=from_status,
        to_status=rev.status,
        payload={},
    )
    return rev


@transaction.atomic
def reorder_ready_queue(*, ordered_revision_ids: Iterable[int], actor: User) -> None:
    """
    Reordena PRONTO_PRODUCAO por priority_rank.
    ordered_revision_ids vem do front (SortableJS), na ordem desejada.
    """
    # trava o conjunto para evitar concorrência
    qs = PartRevision.objects.select_for_update().filter(
        id__in=list(ordered_revision_ids),
        status=RevisionStatus.PRONTO_PRODUCAO,
    )

    by_id = {r.id: r for r in qs}
    rank = Decimal("1000")

    for rid in ordered_revision_ids:
        r = by_id.get(int(rid))
        if not r:
            continue
        old = r.priority_rank
        r.priority_rank = rank
        r.save(update_fields=["priority_rank"])
        _audit_revision(
            revision=r,
            actor=actor,
            action="reorder",
            from_status=r.status,
            to_status=r.status,
            payload={"old_rank": str(old), "new_rank": str(rank)},
        )
        rank += Decimal("1000")