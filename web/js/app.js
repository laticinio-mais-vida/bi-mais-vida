// Inicialização: tema, rotas (#/metas e #/configuracoes), estado dos dados e atualização da cópia do banco.
import { api, esc, fmt, preencherIcones, toast } from "./util.js";
import { montarMetas, recarregarMetas } from "./metas.js";
import { montarConfig, configTemAlteracoes } from "./config.js";

const app = { opcoes: null, estado: null, rota: null, montadas: new Set() };

function tema() {
  const btn = document.getElementById("btn-tema");
  btn.addEventListener("click", () => {
    const novo = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", novo);
    try { localStorage.setItem("mv-tema", novo); } catch { /* sem armazenamento */ }
    window.dispatchEvent(new Event("tema"));
  });
}

function subtituloMetas(d) {
  const sub = document.getElementById("subtitulo-pagina");
  sub.innerHTML = `<span>${esc(d.periodo.rotulo)} · ${esc(d.visao.titulo)}</span>
    <span class="ponto"><span class="pulso"></span>dados até ${fmt.semana(d.data_ref)}, ${fmt.dataCurta(d.data_ref)}</span>`;
}

function rodape() {
  const e = app.estado || {};
  document.getElementById("rodape").innerHTML = `
    <span>Fonte: cópia do ERP de ${e.banco_copia ? fmt.dataHora(e.banco_copia) : "—"}</span>
    <span>Cache local gerado em ${e.extraido_em ? fmt.dataHora(e.extraido_em) : "—"}</span>
    <span>Metas: METAS.xlsx e METAS PRODUTOS.xlsx</span>
    <span>Laticínio Mais Vida</span>`;
}

async function rotear() {
  const rota = (location.hash.replace(/^#\/?/, "").split("?")[0] || "metas");
  if (app.rota === "configuracoes" && rota !== "configuracoes" && configTemAlteracoes() &&
      !confirm("Há alterações não salvas nas configurações. Sair mesmo assim?")) {
    history.replaceState(null, "", "#/configuracoes");
    return;
  }
  app.rota = rota === "configuracoes" ? "configuracoes" : "metas";
  document.querySelectorAll(".nav-pilula").forEach((a) => a.classList.toggle("ativa", a.dataset.rota === app.rota));
  const pMetas = document.getElementById("pagina-metas"), pConfig = document.getElementById("pagina-configuracoes");
  pMetas.hidden = app.rota !== "metas";
  pConfig.hidden = app.rota !== "configuracoes";
  if (app.rota === "metas") {
    document.getElementById("titulo-pagina").textContent = "Acompanhamento de Metas";
    if (!app.montadas.has("metas") || app.precisaRecarregar) {
      app.montadas.add("metas");
      app.precisaRecarregar = false;
      montarMetas(pMetas, { opcoes: app.opcoes, subtitulo: subtituloMetas });
    }
  } else {
    document.getElementById("titulo-pagina").textContent = "Configurações das metas";
    document.getElementById("subtitulo-pagina").innerHTML = "<span>Produtos, vendedores, devoluções e dias úteis usados nos cálculos</span>";
    montarConfig(pConfig, { aoSalvar: () => { app.precisaRecarregar = true; } });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function aguardarDados() {
  const tela = document.getElementById("tela-preparo");
  for (;;) {
    try {
      app.estado = await api("/api/estado");
      if (app.estado.pronto) break;
      tela.hidden = false;
      document.getElementById("preparo-etapa").textContent =
        app.estado.atualizacao.erro ? `Erro: ${app.estado.atualizacao.erro}` : (app.estado.atualizacao.etapa || "Lendo a cópia do banco…");
    } catch {
      document.getElementById("preparo-etapa").textContent = "Aguardando o servidor…";
      tela.hidden = false;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  tela.hidden = true;
}

function botaoAtualizar() {
  const btn = document.getElementById("btn-atualizar");
  const rotulo = btn.querySelector(".rotulo");
  btn.addEventListener("click", async () => {
    if (btn.classList.contains("girando")) return;
    btn.classList.add("girando");
    rotulo.textContent = "Atualizando…";
    try {
      await api("/api/atualizar", { method: "POST" });
      await acompanharAtualizacao(rotulo);
    } catch (e) {
      toast(e.message, "erro");
    } finally {
      btn.classList.remove("girando");
      rotulo.textContent = "Atualizar dados";
    }
  });
}

async function acompanharAtualizacao(rotulo) {
  const antes = app.estado?.extraido_em;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1200));
    const e = await api("/api/estado");
    if (rotulo && e.atualizacao.etapa) rotulo.textContent = e.atualizacao.etapa + "…";
    if (!e.atualizacao.atualizando) {
      app.estado = e;
      if (e.atualizacao.erro) throw new Error("Falha ao ler o banco: " + e.atualizacao.erro);
      if (e.extraido_em !== antes) aoTrocarDados();
      else toast("Os dados já estavam atualizados");
      return;
    }
  }
}

async function aoTrocarDados() {
  app.opcoes = await api("/api/opcoes");
  rodape();
  toast(`Dados atualizados até ${fmt.dataCurta(app.estado.data_ref)}`);
  if (app.rota === "metas") recarregarMetas();
  else app.precisaRecarregar = true;
}

function vigiar() {
  setInterval(async () => {
    try {
      const antes = app.estado?.extraido_em;
      const e = await api("/api/estado");
      app.estado = e;
      if (!e.atualizacao.atualizando && e.extraido_em && e.extraido_em !== antes) aoTrocarDados();
    } catch { /* servidor fora do ar: tenta de novo no próximo ciclo */ }
  }, 60000);
}

async function iniciar() {
  preencherIcones(document);
  tema();
  botaoAtualizar();
  await aguardarDados();
  app.opcoes = await api("/api/opcoes");
  rodape();
  window.addEventListener("hashchange", rotear);
  await rotear();
  vigiar();
}

iniciar().catch((e) => toast(e.message, "erro"));
