@echo off
set OUT=D:\cadflow\backup_logs
if not exist %OUT% mkdir %OUT%

for /f "tokens=1-3 delims=/- " %%a in ("%date%") do (
  set YYYY=%%c
  set MM=%%b
  set DD=%%a
)

docker compose exec -T db pg_dump -U cadflow_app -d cadflow > %OUT%\cadflow_%YYYY%-%MM%-%DD%.sql