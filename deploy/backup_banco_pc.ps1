# Cópia de segurança diária do banco PostgreSQL do painel no PC da empresa (usuários, regras, conversas e uso do
# Assistente). Fica em Documentos\backups-bi-banco, fora da pasta do projeto, e guarda os últimos 14 dias.
# A senha do usuário bi vem do pgpass.conf (%APPDATA%\postgresql\pgpass.conf, uma linha: localhost:5432:bi:bi:SENHA),
# nunca deste arquivo. Agendar (no PowerShell, uma vez):
#   $acao = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\Micro\Desktop\BI MAIS VIDA\bi-mais-vida\deploy\backup_banco_pc.ps1"'
#   Register-ScheduledTask -TaskName "BI Mais Vida - copia do banco" -Action $acao -Trigger (New-ScheduledTaskTrigger -Daily -At 12:30)
# Restaurar uma cópia (troca o conteúdo do banco pelo da cópia; feche o painel antes):
#   & "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U bi -h localhost -d bi --clean --if-exists "$env:USERPROFILE\Documents\backups-bi-banco\bi-AAAA-MM-DD.dump"
$ErrorActionPreference = "Stop"

$destino = Join-Path $env:USERPROFILE "Documents\backups-bi-banco"
$dias = 14
$pgDump = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" | Sort-Object FullName | Select-Object -Last 1
if (-not $pgDump) { throw "pg_dump.exe não encontrado em C:\Program Files\PostgreSQL" }

New-Item -ItemType Directory -Force $destino | Out-Null
$arquivo = Join-Path $destino ("bi-{0:yyyy-MM-dd}.dump" -f (Get-Date))
& $pgDump.FullName -U bi -h localhost -d bi -Fc -w -f "$arquivo.tmp"
if ($LASTEXITCODE -ne 0) { throw "pg_dump falhou (código $LASTEXITCODE)" }
Move-Item -Force "$arquivo.tmp" $arquivo
Get-ChildItem $destino -Filter "bi-*.dump" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$dias) } | Remove-Item
"{0:yyyy-MM-dd HH:mm:ss} cópia em {1} ({2:N0} KB)" -f (Get-Date), $arquivo, ((Get-Item $arquivo).Length / 1KB)
