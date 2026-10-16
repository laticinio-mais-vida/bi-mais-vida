"""Traz para o banco o que ficava em arquivos na pasta do painel. Cada máquina importa os seus (o PC e o site têm
cadastros separados): usuarios.json, config_metas.json (e a versão anterior), config_projecoes.json (idem) e
logs/assistente-*.jsonl.

Os arquivos ficam onde estão, como cópia, e o painel não os lê mais. Sem a pasta (testes) ou sem o arquivo, não
importa nada. O segredo das sessões não vem junto: o painel cria um novo e todos entram de novo uma vez (os cookies
antigos levavam o login, e os novos levam o id).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from bi.acesso import PAGINAS, PAGINAS_COM_ESCOPO, PAGINAS_PADRAO
from bi.configuracao import _valida as valida_metas
from bi.projecoes import ConfigProjecoes

log = logging.getLogger("bi.banco")


def aplicar(con, raiz: Path | None) -> None:
    if raiz is None:
        return
    _usuarios(con, raiz / "usuarios.json")
    _regras(con, "metas", raiz / "config_metas.json", valida_metas)
    _regras(con, "projecoes", raiz / "config_projecoes.json", ConfigProjecoes._valida)
    _perguntas(con, sorted((raiz / "logs").glob("assistente-*.jsonl")))


def _hora(texto) -> dt.datetime | None:
    """Os arquivos guardavam a hora deste computador sem o fuso."""
    return dt.datetime.fromisoformat(str(texto)).astimezone() if texto else None


def _jsonb(valor) -> str | None:
    return None if valor is None else json.dumps(valor, ensure_ascii=False, default=str)


def _usuarios(con, arquivo: Path) -> None:
    if not arquivo.exists():
        return
    usuarios = json.loads(arquivo.read_text(encoding="utf-8")).get("usuarios") or {}
    for login, u in usuarios.items():
        admin = u["papel"] == "admin"
        escopos = [None if admin or not u.get(p) else _jsonb(u[p]) for p in PAGINAS_COM_ESCOPO]
        con.execute(
            "INSERT INTO usuarios (login, nome, papel, ativo, senha, sessao, paginas, visoes, vendedores, "
            "escopo_projecoes, escopo_assistente, criado_em, ultimo_acesso) VALUES (%s, %s, %s, %s, %s, %s, "
            "%s::text[], %s::text[], %s::int[], %s::jsonb, %s::jsonb, COALESCE(%s, now()), %s)",
            [login, u.get("nome") or login, u["papel"], bool(u.get("ativo", True)), u["senha"], int(u.get("sessao") or 0),
             # Visualizador sem a lista de páginas foi cadastrado antes dela existir: vê Metas.
             None if admin else [p for p in PAGINAS if p in (u.get("paginas") or PAGINAS_PADRAO)],
             None if admin else list(u.get("visoes") or []),
             None if admin or u.get("vendedores") is None else [int(v) for v in u["vendedores"]],
             *escopos, _hora(u.get("criado_em")), _hora(u.get("ultimo_acesso"))])
    log.info("migração: %d usuários importados de %s", len(usuarios), arquivo.name)


def _regras(con, nome: str, arquivo: Path, valida) -> None:
    # A versão anterior (o .anterior.json que a página Configurações deixava) entra antes, para ficar no histórico.
    for caminho, obrigatorio in ((arquivo.with_name(arquivo.stem + ".anterior.json"), False), (arquivo, True)):
        if not caminho.exists():
            continue
        try:
            cfg = valida(json.loads(caminho.read_text(encoding="utf-8")))
        except ValueError:
            if obrigatorio:
                raise
            log.warning("migração: %s não foi importada (não passou na conferência das regras)", caminho.name)
            continue
        salva_em = dt.datetime.fromtimestamp(caminho.stat().st_mtime).astimezone()
        con.execute("INSERT INTO regras (nome, dados, salva_em, salva_por_nome) VALUES (%s, %s::jsonb, %s, %s)",
                    [nome, _jsonb(cfg), salva_em, f"importado de {caminho.name}"])
        log.info("migração: regras de %s importadas de %s", nome, caminho.name)


def _perguntas(con, arquivos: list[Path]) -> None:
    linhas = []
    for arquivo in arquivos:
        for texto in arquivo.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(texto)
                quando = _hora(r["quando"])
            except (ValueError, KeyError, TypeError):
                continue
            if not r.get("login") or not r.get("pergunta"):
                continue
            uso = r.get("uso") or {}
            linhas.append([
                quando, r["login"], r["login"], r.get("nome") or r["login"], r.get("escopo"), r["pergunta"],
                r.get("resposta"), r.get("aviso"), r.get("erro"), r.get("parada"), uso.get("modelo"),
                *(int(uso.get(k) or 0) for k in ("entrada", "saida", "cache_leitura", "cache_escrita", "chamadas")),
                float(uso.get("custo") or 0), uso.get("segundos"), _jsonb(r.get("passos") or []), r.get("data_ref"),
                [str(p) for p in r.get("pedidos_api") or [] if p],
            ])
    if not linhas:
        return
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO assistente_perguntas (quando, usuario, login, nome, escopo, pergunta, resposta, aviso, erro, "
            "parada, modelo, entrada, saida, cache_leitura, cache_escrita, chamadas, custo, segundos, passos, "
            "data_ref, pedidos_api) VALUES (%s, (SELECT id FROM usuarios WHERE login = %s), %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::date, %s::text[])", linhas)
    log.info("migração: %d perguntas ao Assistente importadas de %s", len(linhas),
                ", ".join(a.name for a in arquivos))
