"""Publicação do painel num VPS.

O computador da empresa continua lendo a cópia do banco (7 GB) e montando o cache (poucos MB). Sempre que o
cache ou uma planilha de metas muda, ele manda os três arquivos, num .zip, para o painel no VPS. O VPS não tem
Firebird: só recebe, confere e troca os arquivos em uso.

Os dois lados guardam a mesma chave em [publicacao] no config.ini. O pacote vai assinado com HMAC-SHA256 (data
do envio + hash do conteúdo): a chave nunca trafega, e pacote alterado no caminho ou de quem não tem a chave é
recusado.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .cache import Cache

log = logging.getLogger("bi.publicacao")

ROTA = "/api/publicacao/receber"
# Nome de cada arquivo dentro do pacote.
NOMES = {"cache": "cache.duckdb", "metas": "metas.xlsx", "metas_produtos": "metas_produtos.xlsx"}
LIMITE_PACOTE = 200 * 1024 * 1024  # o cache tinha 9 MB em out/2026, com as vendas desde 2024
TOLERANCIA_RELOGIO = 15 * 60  # segundos de diferença aceitos entre os relógios do PC e do VPS


class Recusado(Exception):
    """Pacote sem assinatura válida: quem enviou não tem a chave (ou o relógio está muito errado)."""


def gerar_chave() -> str:
    return secrets.token_urlsafe(32)


def assinar(chave: str, data: str, hash_corpo: str) -> str:
    return hmac.new(chave.encode(), f"{data}\n{hash_corpo}".encode(), hashlib.sha256).hexdigest()


class Envio:
    """No computador da empresa: manda o pacote ao VPS sempre que o cache ou uma planilha muda."""

    def __init__(self, ini, cache: Cache, planilhas: dict[str, Path]):
        self.destino = ini.get("publicacao", "enviar_para", fallback="").strip().rstrip("/")
        self.chave = ini.get("publicacao", "chave", fallback="").strip()
        self.cache = cache
        self.planilhas = planilhas
        self.estado = {"destino": self.destino or None, "enviando": False, "enviado_em": None, "erro": None}
        self._enviado = None  # versão que o VPS já tem (extração do cache + data das planilhas)
        self._falhas = 0
        self._proxima = 0.0
        self._trava = threading.Lock()

    @property
    def ativo(self) -> bool:
        return bool(self.destino)

    def _versao_local(self) -> tuple:
        versao = [self.cache.info.get("extraido_em")]
        for caminho in self.planilhas.values():
            try:
                st = caminho.stat()
                versao.append((st.st_mtime_ns, st.st_size))
            except OSError:
                versao.append(None)
        return tuple(versao)

    def verificar(self) -> None:
        """Chamado a cada meio minuto: envia se algo mudou desde o último envio aceito pelo VPS."""
        if (not self.ativo or not self.cache.pronto() or self.cache.estado["atualizando"]
                or time.time() < self._proxima or self._versao_local() == self._enviado):
            return
        try:
            self.enviar()
        except Exception:
            pass  # já foi para o log; tenta de novo mais tarde

    def enviar(self) -> dict:
        with self._trava:
            versao = self._versao_local()
            self.estado["enviando"] = True
            try:
                self._conferir_destino()
                corpo = self._pacote()
                resposta = self._post(corpo)
            except Exception as e:
                self._falhas += 1
                espera = min(60 * 2 ** self._falhas, 30 * 60)  # 2, 4, 8, 16 e depois a cada 30 min
                self._proxima = time.time() + espera
                self.estado["erro"] = str(e)
                log.warning("não foi possível enviar ao VPS: %s (nova tentativa em %d min)", e, espera // 60)
                raise
            finally:
                self.estado["enviando"] = False
            self._enviado, self._falhas, self._proxima = versao, 0, 0.0
            self.estado.update(enviado_em=dt.datetime.now().isoformat(timespec="seconds"), erro=None)
            log.info("dados enviados ao VPS (%.1f MB, dados até %s)", len(corpo) / 1e6, resposta.get("data_ref"))
            return resposta

    def _conferir_destino(self) -> None:
        if not self.chave:
            raise ValueError("falta a chave em [publicacao] no config.ini (gere com: python app.py --gerar-chave)")
        u = urlparse(self.destino)
        if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
            raise ValueError(f"o endereço do VPS precisa começar com https:// ({self.destino})")

    def _pacote(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(NOMES["cache"], self.cache.conteudo())
            for chave, caminho in self.planilhas.items():
                z.write(caminho, NOMES[chave])
        return buf.getvalue()

    def _post(self, corpo: bytes) -> dict:
        data = str(int(time.time()))
        req = urllib.request.Request(self.destino + ROTA, data=corpo, method="POST", headers={
            "Content-Type": "application/zip",
            "User-Agent": "BIMetasMaisVida-envio/1.0",
            "X-BI-Data": data,
            "X-BI-Assinatura": assinar(self.chave, data, hashlib.sha256(corpo).hexdigest()),
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                motivo = json.loads(e.read()).get("erro")
            except Exception:
                motivo = None
            raise RuntimeError(f"o VPS recusou o envio ({e.code}): {motivo or e.reason}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"sem conexão com {self.destino}: {e.reason}") from None


class Recebimento:
    """No VPS: confere a assinatura e cada arquivo do pacote; só depois troca os que estão em uso."""

    def __init__(self, ini, cache: Cache, planilhas: dict):
        self.chave = ini.get("publicacao", "chave", fallback="").strip()
        self.cache = cache
        self.planilhas = planilhas  # {"metas": PlanilhaMonitorada, "metas_produtos": PlanilhaMonitorada}
        self._trava = threading.Lock()

    def receber(self, leitor, tamanho: int, data: str | None, assinatura: str | None) -> dict:
        if not 0 < tamanho <= LIMITE_PACOTE:
            raise ValueError("pacote vazio ou grande demais")
        if not self.chave:
            raise Recusado("o VPS está sem a chave em [publicacao] no config.ini")
        with self._trava:
            pacote = self.cache.arquivo.parent / "recebido.zip.tmp"
            try:
                h = hashlib.sha256()
                with open(pacote, "wb") as f:
                    while tamanho:
                        bloco = leitor.read(min(tamanho, 1 << 20))
                        if not bloco:
                            raise ValueError("o pacote chegou incompleto")
                        h.update(bloco)
                        f.write(bloco)
                        tamanho -= len(bloco)
                # O corpo é lido inteiro antes de recusar, para a resposta chegar a quem enviou.
                try:
                    diferenca = abs(time.time() - int(data or ""))
                except ValueError:
                    raise Recusado("pedido sem data") from None
                if diferenca > TOLERANCIA_RELOGIO:
                    raise Recusado("o relógio do computador que envia está mais de 15 min diferente do VPS")
                if not hmac.compare_digest(assinar(self.chave, data, h.hexdigest()), assinatura or ""):
                    raise Recusado("assinatura inválida: a chave em [publicacao] não é a mesma nos dois config.ini "
                                   "(ou o pacote foi alterado no caminho)")
                return self._aplicar(pacote)
            finally:
                pacote.unlink(missing_ok=True)

    def _aplicar(self, pacote: Path) -> dict:
        temporarios: list[Path] = []
        trocas: list[tuple[Path, Path]] = []
        try:
            with zipfile.ZipFile(pacote) as z:
                nomes = set(z.namelist())
                if NOMES["cache"] not in nomes:
                    raise ValueError("o pacote não traz o cache")

                def extrair(nome: str, destino: Path) -> Path:
                    tmp = destino.with_name(destino.name + ".recebido.tmp")
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    temporarios.append(tmp)
                    with z.open(nome) as origem, open(tmp, "wb") as f:
                        shutil.copyfileobj(origem, f)
                    return tmp

                novo_cache = extrair(NOMES["cache"], self.cache.arquivo)
                try:
                    info = Cache.conferir(novo_cache)
                except Exception as e:
                    raise ValueError(f"o cache recebido não abriu: {e}") from None
                for chave, planilha in self.planilhas.items():
                    if NOMES[chave] not in nomes:
                        continue
                    tmp = extrair(NOMES[chave], planilha.arquivo)
                    try:
                        planilha.leitor(tmp)
                    except Exception as e:
                        raise ValueError(f"{planilha.arquivo.name} recebida não pôde ser lida: {e}") from None
                    trocas.append((tmp, planilha.arquivo))
            # Tudo conferido: troca as planilhas e depois o cache.
            for tmp, destino in trocas:
                os.replace(tmp, destino)
            self.cache.trocar(novo_cache)
        finally:
            for tmp in temporarios:
                tmp.unlink(missing_ok=True)
        planilhas = [destino.name for _, destino in trocas]
        log.info("dados recebidos: cópia do ERP de %s, dados até %s%s", info.get("banco_copia"), info["data_ref"],
                 f"; planilhas {', '.join(planilhas)}" if planilhas else "")
        return {"ok": True, "data_ref": info["data_ref"], "extraido_em": info["extraido_em"], "planilhas": planilhas}
