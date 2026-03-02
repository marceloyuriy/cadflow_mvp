# CADFlow MVP (Django + Postgres 18 + Docker) — README / Runbook

CADFlow é um MVP para controlar o **workflow de peças** entre **CAD** e **Manufatura** (revisões, anexos, validação, priorização, execução, bloqueio/desbloqueio e auditoria), rodando em **Windows 11** com **Docker Desktop (WSL2)**.

---

## Stack

- Python 3.12 (container)
- Django 6
- Postgres 18
- Docker Compose (DEV)
- Volumes:
  - `db_data` (dados do Postgres)
  - `storage` (uploads/anexos)

> **Importante (Postgres 18+):** o volume do banco deve ser montado em **`/var/lib/postgresql`** (não em `/var/lib/postgresql/data`).

---

## Estrutura esperada do projeto

Na raiz (`C:\cadflow_mvp\`):

- `compose.yml`
- `Dockerfile`
- `requirements.txt`
- `.env` (seus segredos)
- `.env.example`
- `manage.py`
- `cadflow/`
  - `__init__.py`
  - `settings.py`
  - `urls.py`
  - `wsgi.py` ✅ (obrigatório se usar gunicorn)
  - `asgi.py` (recomendado)
- `workflow/` (app principal)

---

## Pré-requisitos (Windows 11)

1. Instalar:
   - VS Code
   - Git
   - Docker Desktop

2. Docker Desktop:
   - Settings → General → **Use the WSL 2 based engine**
   - Settings → Resources → WSL Integration → habilitar sua distro (ex.: Ubuntu)

3. Checagem:
```bash
docker --version
docker compose version