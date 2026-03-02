from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from workflow.models import Part, PartRevision, RevisionFile, ManufacturingReview, BlockEvent, AuditEvent


class Command(BaseCommand):
    help = "Cria grupos CAD/MANUFATURA/ADMIN e atribui permissões básicas."

    def handle(self, *args, **options):
        cad, _ = Group.objects.get_or_create(name="CAD")
        mfg, _ = Group.objects.get_or_create(name="MANUFATURA")
        adm, _ = Group.objects.get_or_create(name="ADMIN")

        # Permissions por modelo
        models = [Part, PartRevision, RevisionFile, ManufacturingReview, BlockEvent, AuditEvent]
        perms = []
        for mdl in models:
            ct = ContentType.objects.get_for_model(mdl)
            perms.extend(Permission.objects.filter(content_type=ct))

        # helper: filtrar codenames
        def p(*codenames):
            return Permission.objects.filter(codename__in=codenames)

        # CAD: cria peça, cria revisão, sobe arquivo, vê tudo
        cad_perms = (
            p(
                "add_part", "change_part", "view_part",
                "add_partrevision", "change_partrevision", "view_partrevision",
                "add_revisionfile", "change_revisionfile", "view_revisionfile",
                "view_manufacturingreview", "view_blockevent", "view_auditevent",
            )
        )
        cad.permissions.set(cad_perms)

        # MANUFATURA: vê tudo, cria review, pode alterar status (via UI/services)
        mfg_perms = (
            p(
                "view_part", "view_partrevision", "view_revisionfile",
                "add_manufacturingreview", "change_manufacturingreview", "view_manufacturingreview",
                "add_blockevent", "change_blockevent", "view_blockevent",
                "view_auditevent",
                "change_partrevision",  # necessário se usar admin; na UI você usa services
            )
        )
        mfg.permissions.set(mfg_perms)

        # ADMIN: tudo no app
        adm.permissions.set(perms)

        self.stdout.write(self.style.SUCCESS("Grupos e permissões criados/atualizados com sucesso."))