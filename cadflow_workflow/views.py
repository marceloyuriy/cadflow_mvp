from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import AuditEvent, BlockEvent, ManufacturingReview, Part, PartRevision, RevisionFile, RevisionStatus
from .services import InvalidTransition, create_revision


def _in_group(user, *group_names: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


@login_required
def home(request: HttpRequest) -> HttpResponse:
    if _in_group(request.user, "CAD", "ADMIN"):
        return redirect("cad_dashboard")
    if _in_group(request.user, "MANUFATURA", "ADMIN"):
        return redirect("production_dashboard")
    return redirect("/admin/")


@login_required
def cad_dashboard(request: HttpRequest) -> HttpResponse:
    if not _in_group(request.user, "CAD", "ADMIN"):
        messages.error(request, "Acesso restrito ao grupo CAD.")
        return redirect("login")

    pending_statuses = [
        RevisionStatus.AGUARDANDO_VALIDACAO,
        RevisionStatus.REVISAO_SOLICITADA,
        RevisionStatus.PRONTO_PRODUCAO,
    ]

    pending_files_count = RevisionFile.objects.filter(
        revision__is_current=True,
        revision__status__in=pending_statuses,
    ).count()

    pending_revisions_count = PartRevision.objects.filter(
        is_current=True,
        status__in=pending_statuses,
    ).count()

    by_status = PartRevision.objects.filter(is_current=True).values("status").annotate(c=Count("id"))
    status_map = {row["status"]: row["c"] for row in by_status}

    revisions = (
        PartRevision.objects.select_related("part")
        .prefetch_related("files")
        .filter(is_current=True)
        .exclude(status=RevisionStatus.OBSOLETA)
        .order_by("part__code", "-revision_no")
    )

    requested_reviews = (
        ManufacturingReview.objects.select_related("revision__part", "decided_by")
        .filter(revision__is_current=True, revision__status=RevisionStatus.REVISAO_SOLICITADA)
        .order_by("-decided_at")
    )

    in_production = (
        PartRevision.objects.select_related("part")
        .filter(is_current=True, status__in=[RevisionStatus.EM_EXECUCAO, RevisionStatus.TRAVADO, RevisionStatus.FINALIZADA])
        .order_by("part__code")
    )

    ready_for_production = (
        PartRevision.objects.select_related("part")
        .filter(is_current=True, status=RevisionStatus.PRONTO_PRODUCAO)
        .order_by("priority_rank", "part__code")
    )

    return render(
        request,
        "workflow/cad_dashboard.html",
        {
            "pending_files_count": pending_files_count,
            "pending_revisions_count": pending_revisions_count,
            "status_map": status_map,
            "revisions": revisions,
            "requested_reviews": requested_reviews,
            "in_production": in_production,
            "ready_for_production": ready_for_production,
        },
    )


@login_required
def cad_new_submission(request: HttpRequest) -> HttpResponse:
    if not _in_group(request.user, "CAD", "ADMIN"):
        messages.error(request, "Acesso restrito ao grupo CAD.")
        return redirect("login")

    if request.method != "POST":
        return redirect("cad_dashboard")

    code = (request.POST.get("code") or "").strip().upper()
    description = (request.POST.get("description") or "").strip()
    material = (request.POST.get("material") or "").strip()
    quantity = int(request.POST.get("quantity") or 1)
    need_by = request.POST.get("need_by") or None
    notes = (request.POST.get("notes") or "").strip()
    revision_note = (request.POST.get("revision_note") or "").strip()
    files = request.FILES.getlist("files")

    if not code:
        messages.error(request, "Informe o código da peça.")
        return redirect("cad_dashboard")

    if not files:
        messages.error(request, "Anexe pelo menos um arquivo da revisão.")
        return redirect("cad_dashboard")

    try:
        with transaction.atomic():
            part, created_part = Part.objects.select_for_update().get_or_create(
                code=code,
                defaults={
                    "description": description,
                    "material": material,
                    "quantity": quantity,
                    "need_by": need_by,
                    "notes": notes,
                },
            )

            if not created_part:
                part.description = description
                part.material = material
                part.quantity = quantity
                part.need_by = need_by
                part.notes = notes
                part.save(update_fields=["description", "material", "quantity", "need_by", "notes"])
                rev = create_revision(part_id=part.id, created_by=request.user, note=revision_note)
            else:
                rev = PartRevision.objects.create(
                    part=part,
                    revision_no=1,
                    is_current=True,
                    status=RevisionStatus.AGUARDANDO_VALIDACAO,
                    created_by=request.user,
                    note=revision_note,
                )
                AuditEvent.objects.create(
                    entity_type="PartRevision",
                    entity_id=rev.id,
                    action="create_revision",
                    from_status="",
                    to_status=rev.status,
                    payload_json={"revision_no": rev.revision_no},
                    actor=request.user,
                )

            for f in files:
                RevisionFile.objects.create(
                    revision=rev,
                    file=f,
                    original_name=f.name,
                    uploaded_by=request.user,
                )

    except (InvalidTransition, ValueError) as exc:
        messages.error(request, f"Não foi possível criar envio: {exc}")
        return redirect("cad_dashboard")

    messages.success(request, f"Envio registrado para {part.code} rev {rev.revision_no} com {len(files)} arquivo(s).")
    return redirect("cad_dashboard")


@login_required
def cad_upload_files(request: HttpRequest, revision_id: int) -> HttpResponse:
    if not _in_group(request.user, "CAD", "ADMIN"):
        messages.error(request, "Acesso restrito ao grupo CAD.")
        return redirect("login")

    rev = get_object_or_404(PartRevision.objects.select_related("part"), id=revision_id)

    if request.method == "POST":
        files = request.FILES.getlist("files")
        if not files:
            messages.warning(request, "Selecione pelo menos 1 arquivo.")
            return redirect("cad_upload_files", revision_id=rev.id)

        created = 0
        for f in files:
            RevisionFile.objects.create(
                revision=rev,
                file=f,
                original_name=f.name,
                uploaded_by=request.user,
            )
            created += 1

        messages.success(request, f"{created} arquivo(s) enviados para {rev.part.code} rev {rev.revision_no}.")
        return redirect("cad_upload_files", revision_id=rev.id)

    files = rev.files.all().order_by("-uploaded_at")
    return render(request, "workflow/cad_upload.html", {"rev": rev, "files": files})


@login_required
def cad_download_file(request: HttpRequest, file_id: int) -> HttpResponse:
    if not _in_group(request.user, "CAD", "ADMIN", "MANUFATURA"):
        raise Http404()

    revision_file = get_object_or_404(RevisionFile.objects.select_related("revision__part"), id=file_id)
    response = FileResponse(revision_file.file.open("rb"), as_attachment=True, filename=revision_file.original_name)
    return response


@login_required
def production_dashboard(request: HttpRequest) -> HttpResponse:
    if not _in_group(request.user, "MANUFATURA", "ADMIN"):
        messages.error(request, "Acesso restrito ao grupo Manufatura.")
        return redirect("login")

    ready = (
        PartRevision.objects.select_related("part")
        .filter(is_current=True, status=RevisionStatus.PRONTO_PRODUCAO)
        .order_by("priority_rank", "part__code")
    )
    in_exec = (
        PartRevision.objects.select_related("part")
        .filter(is_current=True, status=RevisionStatus.EM_EXECUCAO)
        .order_by("part__code")
    )
    blocked = (
        PartRevision.objects.select_related("part")
        .filter(is_current=True, status=RevisionStatus.TRAVADO)
        .order_by("part__code")
    )
    finished_last_30d = (
        PartRevision.objects.filter(
            is_current=True,
            status=RevisionStatus.FINALIZADA,
            created_at__gte=timezone.now() - timedelta(days=30),
        ).count()
    )

    total_ready = ready.count()
    total_in_exec = in_exec.count()
    total_blocked = blocked.count()

    active_block_reasons = list(BlockEvent.objects.filter(unblocked_at__isnull=True).values_list("reason", flat=True))
    top_reasons = Counter(active_block_reasons).most_common(5)

    return render(
        request,
        "workflow/production_dashboard.html",
        {
            "ready": ready,
            "in_exec": in_exec,
            "blocked": blocked,
            "total_ready": total_ready,
            "total_in_exec": total_in_exec,
            "total_blocked": total_blocked,
            "finished_last_30d": finished_last_30d,
            "top_reasons": top_reasons,
        },
    )
