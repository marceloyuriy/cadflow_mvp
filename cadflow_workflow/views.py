from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import BlockEvent, PartRevision, RevisionFile, RevisionStatus


def _in_group(user, *group_names: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


@login_required
def home(request: HttpRequest) -> HttpResponse:
    # Roteia o usuário conforme grupo
    if _in_group(request.user, "CAD", "ADMIN"):
        return redirect("cad_dashboard")
    if _in_group(request.user, "MANUFATURA", "ADMIN"):
        return redirect("production_dashboard")
    # fallback
    return redirect("/admin/")


@login_required
def cad_dashboard(request: HttpRequest) -> HttpResponse:
    if not _in_group(request.user, "CAD", "ADMIN"):
        messages.error(request, "Acesso restrito ao grupo CAD.")
        return redirect("login")

    # “Arquivos que ainda não foram puxados para produção”
    # Interpretação: tudo antes de EM_EXECUCAO (ou seja, aguardando/solicitada/pronto)
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

    by_status = (
        PartRevision.objects.filter(is_current=True)
        .values("status")
        .annotate(c=Count("id"))
    )
    status_map = {row["status"]: row["c"] for row in by_status}

    # Lista simples das revisões correntes (para CAD ver o “funil”)
    revisions = (
        PartRevision.objects.select_related("part")
        .filter(is_current=True)
        .exclude(status=RevisionStatus.OBSOLETA)
        .order_by("part__code", "-revision_no")
    )

    return render(
        request,
        "workflow/cad_dashboard.html",
        {
            "pending_files_count": pending_files_count,
            "pending_revisions_count": pending_revisions_count,
            "status_map": status_map,
            "revisions": revisions,
        },
    )


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
            return redirect("cad_dashboard")

        created = 0
        for f in files:
            rf = RevisionFile(
                revision=rev,
                file=f,
                original_name=f.name,  # seu model exige original_name (não é blank) :contentReference[oaicite:0]{index=0}
                uploaded_by=request.user,
            )
            # se você não implementou save() auto, garante hash/size aqui:
            try:
                rf.compute_hash_and_size()  # calcula sha256/size
            except Exception:
                # não bloqueia o MVP caso hash falhe por algum motivo
                pass
            rf.save()
            created += 1

        messages.success(request, f"{created} arquivo(s) enviados para {rev.part.code} rev {rev.revision_no}.")
        return redirect("cad_dashboard")

    return render(request, "workflow/cad_upload.html", {"rev": rev})


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

    # métricas
    total_ready = ready.count()
    total_in_exec = in_exec.count()
    total_blocked = blocked.count()

    # motivos de travamento (ativos)
    active_block_reasons = list(
        BlockEvent.objects.filter(unblocked_at__isnull=True)
        .values_list("reason", flat=True)
    )
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