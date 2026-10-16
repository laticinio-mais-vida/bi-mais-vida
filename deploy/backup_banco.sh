#!/usr/bin/env bash
# Cópia de segurança diária do banco PostgreSQL do painel (container bi_banco). Fica fora da pasta do projeto,
# porque o rollback do deploy apaga /opt/bi-mais-vida. Guarda os últimos 14 dias. No cron do servidor (crontab -e):
#   30 3 * * * bash /opt/bi-mais-vida/deploy/backup_banco.sh >> /var/log/bi-banco-backup.log 2>&1
# Restaurar uma cópia (troca o conteúdo do banco pelo da cópia):
#   docker exec -i bi_banco pg_restore -U bi -d bi --clean --if-exists < /opt/backups/bi-banco/bi-AAAA-MM-DD.dump
set -euo pipefail

DESTINO=/opt/backups/bi-banco
DIAS=14

mkdir -p "$DESTINO"
chmod 700 "$DESTINO"
arquivo="$DESTINO/bi-$(date +%F).dump"
docker exec bi_banco pg_dump -U bi -d bi -Fc > "$arquivo.tmp"
mv "$arquivo.tmp" "$arquivo"
find "$DESTINO" -name 'bi-*.dump' -mtime +"$DIAS" -delete
echo "$(date '+%F %T') cópia em $arquivo ($(du -h "$arquivo" | cut -f1))"
