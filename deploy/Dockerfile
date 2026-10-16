# Só o Python e as bibliotecas: o código entra montado (docker-compose.yml), junto com o que o painel grava.
# O fdb (Firebird) não entra: no VPS o painel não lê o banco, recebe o cache pronto do PC da empresa.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
# psycopg: o banco PostgreSQL do painel (histórico do Assistente), só no VPS.
RUN pip install --no-cache-dir duckdb==1.5.5 pandas==3.0.5 numpy==2.4.4 anthropic==1.15.0 \
    "psycopg[binary]==3.3.6" psycopg-pool==3.3.3
WORKDIR /app
EXPOSE 8050
CMD ["python", "app.py", "--sem-navegador"]
