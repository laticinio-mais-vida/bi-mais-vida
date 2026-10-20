// Página Gestão ("Gestão da equipe"), separada por região (ES e BA; o Edir é da BA). No topo, os objetivos do
// período da região; abaixo, as ações (com o tempo que falta e, nas encerradas, quantos ficaram no alvo) e um
// quadrado por vendedor do acesso, com o % da meta de faturamento do mês e uma etiqueta por ação. Clicar no
// vendedor abre o histórico interno dele (as ações com a base e o alvo dele, as observações, a parcial de cada
// semana e o resultado); clicar numa ação abre o andamento dela por vendedor.
// Só o administrador lança ações (marcando vendedores no quadro: a mesma ação para todos), cria objetivos, escreve
// observações, encerra e prorroga; quem tem a página acompanha os vendedores do acesso. A conta é toda no servidor
// (bi/gestao.py), que manda o descritor do indicador: a página só formata. O rascunho que o Assistente monta chega
// por #/gestao?rascunho=<id> e abre o formulário já preenchido.
import { MESES, STATUS, animarEntradas, api, chipStatus, corStatus, esc, fmt, guardar, icone, ler, ligarTooltips, toast } from "./util.js";
import { ABERTURAS, ALVOS, definirCatalogo, deltaTexto, duracaoTexto, iniciais, periodoTexto, textoAlvo, textoBase, textoFiltros,
         textoProgresso, valorIndicador, valorParte, visual } from "./indicadores.js";
import { construtorIndicador } from "./construtorindicador.js";

const PRAZOS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 26]; // semanas
const CORES_AVATAR = ["var(--s-fat)", "var(--s-out)", "var(--k-cli)", "var(--k-vm)", "var(--s-mus)"];
const CLASSE = { ok: "Alvo batido", mid: "Melhorou sobre a base", bad: "Abaixo da base", sem_alvo: "Sem alvo para comparar", sem_dados: "Sem dados" };
const SITUACAO = { planejada: "Planejada", em_vigor: "Em vigor", encerrada: "Encerrada" };
const ROTULO_TAXA = { no_ritmo: "Na meta", abaixo: "Abaixo da meta" };
const DESCARTAR = "Descartar o que foi preenchido nesta ação?";

let ctx = null, raiz = null, ligado = false;
const estado = {
  regiao: ler("mv-gestao-regiao", null), quadro: null, catalogo: null, erroCatalogo: null,
  vista: "grade", vendedor: null, historico: null, acao: null, detalhe: null, abrir: null, // o que o corpo mostra
  selecao: null, form: null, // lançando (ou editando) uma ação: os vendedores marcados e o formulário em linha
  recem: null, pedido: 0, pedidoVista: 0, naPagina: false,
};
let dlg = null, formObj = null;

// ---------- apoio ----------
const parametros = () => new URLSearchParams(location.hash.split("?")[1] || "");
const naGestao = () => /^#\/gestao(\?|$)/.test(location.hash);
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;
const corAvatar = (id) => CORES_AVATAR[Math.abs(Number(id) || 0) % CORES_AVATAR.length];
const primeiroNome = (nome) => String(nome || "").split(" ")[0];
const hora = (iso) => (iso ? iso.slice(11, 16) : "");
const capitalizar = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);
const rotuloStatus = (ind, st) => (ind?.comportamento === "taxa" && ROTULO_TAXA[st]) || (STATUS[st] || STATUS.sem_meta).rotulo;

function hojeLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function somar(iso, dias) {
  const d = new Date(`${iso}T12:00`);
  d.setDate(d.getDate() + dias);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function fimDoMes(iso) {
  const [a, m] = iso.split("-").map(Number);
  return `${a}-${String(m).padStart(2, "0")}-${String(new Date(a, m, 0).getDate()).padStart(2, "0")}`;
}
// O prazo em semanas (só os da lista); null = até uma data.
function semanasDe(inicio, fim) {
  const dias = Math.round((Date.parse(fim) - Date.parse(inicio)) / 864e5) + 1;
  return dias % 7 === 0 && PRAZOS.includes(dias / 7) ? dias / 7 : null;
}
// "novembro" (o mês inteiro) ou "13/10 a 30/11".
function periodoCurto(inicio, fim) {
  const [, m, d] = inicio.split("-").map(Number);
  if (d === 1 && fim === fimDoMes(inicio)) return MESES[m - 1];
  return `${fmt.dataCurta(inicio)} a ${fmt.dataCurta(fim)}`;
}
// "nas 3 semanas antes", "no dia antes": o tamanho da janela da base.
function janelaTexto(inicio, fim) {
  const t = duracaoTexto(inicio, fim);
  if (t === "1 semana") return "na semana antes";
  if (t === "1 dia") return "no dia antes";
  return `${t.endsWith("semanas") ? "nas" : "nos"} ${t} antes`;
}
function rotuloClasse(classe, caminho) {
  if (classe === "mid" && caminho != null) return `${fmt.num(Math.max(0, Math.min(1, caminho)) * 100)}% do caminho até o alvo`;
  return CLASSE[classe] || CLASSE.sem_dados;
}
const acaoDoQuadro = (id) => (estado.quadro?.acoes || []).find((a) => a.id === id);

// ---------- montagem ----------
export function gestaoTemAlteracoes() {
  return !!((estado.form && formMudou()) || (dlg?.open && objetivoMudou()) || raiz?.querySelector("#g-nota")?.value.trim());
}

export function recarregarGestao() {
  if (!ctx) return;
  estado.catalogo = null;
  carregar(true);
  if (estado.vista !== "grade") carregarVista({ silencioso: true });
}

export function montarGestao(container, contexto) {
  ctx = contexto;
  estado.selecao = estado.form = null;
  lerUrl();
  container.innerHTML = `<div class="ge" id="g-raiz">
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("pessoas")}</span>
        <div><b>Gestão da equipe</b><small id="g-hoje">&nbsp;</small></div></div>
      <div class="filtros">
        <div class="seg-mini ge-regioes" role="group" aria-label="Região" id="g-regioes"></div>
        ${ctx.admin ? `<button class="btn primario" type="button" data-nova>${icone("mais")}Nova ação</button>
          <a class="btn btn-config" href="#/config-gestao" title="Quem acompanha quais vendedores e os dias de atendimento das áreas">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="g-avisos"></div>
    <section class="ge-secao" id="g-objetivos"><div class="esqueleto" style="height:96px"></div></section>
    <section class="ge-secao" id="g-acoes"><div class="esqueleto" style="height:118px"></div></section>
    <section class="ge-secao" id="g-corpo"><div class="esqueleto" style="height:320px"></div></section>
  </div>`;
  raiz = container.querySelector("#g-raiz");
  raiz.addEventListener("click", aoClicar);
  raiz.addEventListener("change", aoMudarCampo);
  raiz.addEventListener("input", aoDigitar);
  raiz.addEventListener("keydown", aoTeclar);
  criarJanela();
  if (!ligado) {
    ligado = true;
    window.addEventListener("hashchange", aoMudarHash);
  }
  estado.naPagina = true;
  const rascunho = parametros().get("rascunho");
  carregar();
  if (estado.vista !== "grade") carregarVista();
  if (rascunho) abrirRascunho(rascunho);
}

function lerUrl() {
  const q = parametros();
  if (q.get("r")) estado.regiao = q.get("r").toUpperCase();
  const v = Number(q.get("v")) || null, a = Number(q.get("a") || q.get("c")) || null; // c: os links de antes
  estado.vista = v ? "vendedor" : a ? "acao" : "grade";
  estado.vendedor = v;
  estado.acao = a;
}

function atualizarUrl() {
  if (!naGestao()) return;
  const p = new URLSearchParams();
  if (estado.regiao) p.set("r", estado.regiao);
  if (estado.vista === "vendedor") p.set("v", estado.vendedor);
  if (estado.vista === "acao") p.set("a", estado.acao);
  history.replaceState(null, "", `#/gestao${p.toString() ? `?${p}` : ""}`);
}

// Ao voltar para a página o quadro é lido de novo (uma ação lançada pelo Assistente aparece); um link de dentro do
// painel (#/gestao?a=12, ?rascunho=…) abre o que pede. Ao sair, a janela do objetivo fecha (se tinha alterações, o
// roteador já perguntou).
function aoMudarHash() {
  if (!naGestao()) {
    estado.naPagina = false;
    if (dlg?.open) dlg.close();
    return;
  }
  const q = parametros();
  if (!estado.naPagina) { estado.naPagina = true; carregar(true); }
  if (q.get("rascunho")) return abrirRascunho(q.get("rascunho"));
  const antes = [estado.regiao, estado.vista, estado.vendedor, estado.acao].join();
  lerUrl();
  if ([estado.regiao, estado.vista, estado.vendedor, estado.acao].join() === antes) return;
  carregar(true);
  if (estado.vista !== "grade") carregarVista({ rolar: true });
}

// ---------- dados ----------
async function carregar(silencioso = false) {
  const pedido = ++estado.pedido;
  const blocos = ["#g-objetivos", "#g-acoes", "#g-grade"].map((s) => raiz.querySelector(s)).filter(Boolean);
  if (estado.quadro) blocos.forEach((b) => b.classList.add("recarregando"));
  try {
    const d = await api(`/api/gestao${estado.regiao ? `?regiao=${encodeURIComponent(estado.regiao)}` : ""}`);
    if (pedido !== estado.pedido) return;
    estado.quadro = d;
    if (d.regiao) { estado.regiao = d.regiao; guardar("mv-gestao-regiao", d.regiao); }
    if (d.data_ref) ctx.subtitulo({ data_ref: d.data_ref });
    atualizarUrl();
    desenharTudo();
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 403 && estado.regiao) { // a região guardada não está mais no acesso: a primeira que estiver
      estado.regiao = null;
      guardar("mv-gestao-regiao", null);
      return carregar(silencioso);
    }
    raiz.querySelector("#g-avisos").innerHTML = `<div class="cartao secao vazio">${icone("alerta")}<p>Não foi possível carregar a Gestão: ${esc(e.message)}</p></div>`;
    ["#g-objetivos", "#g-acoes"].forEach((s) => { raiz.querySelector(s).innerHTML = ""; });
    if (estado.vista === "grade") raiz.querySelector("#g-corpo").innerHTML = "";
    if (!silencioso) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) blocos.forEach((b) => b.classList.remove("recarregando"));
  }
}

async function carregarCatalogo() {
  if (estado.catalogo) return estado.catalogo;
  try {
    estado.catalogo = await api("/api/gestao/catalogo");
    definirCatalogo(estado.catalogo);
    estado.erroCatalogo = null;
  } catch (e) {
    estado.erroCatalogo = e.message;
  }
  return estado.catalogo;
}

// O histórico do vendedor ou o detalhe da ação (o corpo da página, no lugar dos quadrados).
async function carregarVista({ rolar = false, silencioso = false } = {}) {
  const el = raiz.querySelector("#g-corpo");
  const pedido = ++estado.pedidoVista;
  const mesma = estado.vista === "vendedor" ? estado.historico?.vendedor?.id === estado.vendedor : estado.detalhe?.item?.id === estado.acao;
  if (!mesma) el.innerHTML = `<div class="esqueleto" style="height:360px"></div>`;
  else el.classList.add("recarregando");
  if (rolar) el.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    if (estado.vista === "vendedor") {
      const d = await api(`/api/gestao/vendedor?id=${estado.vendedor}`);
      if (pedido !== estado.pedidoVista) return;
      estado.historico = d;
    } else if (estado.vista === "acao") {
      const d = await api(`/api/gestao/acao?id=${estado.acao}${estado.abrir != null ? `&abrir=${encodeURIComponent(estado.abrir)}` : ""}`);
      if (pedido !== estado.pedidoVista) return;
      estado.detalhe = d;
    } else {
      return;
    }
    desenharCorpo();
  } catch (e) {
    if (pedido !== estado.pedidoVista) return;
    el.innerHTML = `<div class="cartao secao vazio">${icone("alerta")}<p>${esc(e.message)}</p>
      <button class="btn" type="button" data-voltar>${icone("voltar")}Voltar ao quadro</button></div>`;
    if (!silencioso) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedidoVista) el.classList.remove("recarregando");
  }
}

async function recarregarTudo() {
  await Promise.all([carregar(true), estado.vista !== "grade" ? carregarVista({ silencioso: true }) : null]);
}

// ---------- quadro ----------
function desenharTudo() {
  const d = estado.quadro;
  raiz.querySelector("#g-hoje").textContent = `Hoje, ${fmt.dataCurta(d.hoje)}${d.data_ref ? ` · dados até ${fmt.dataCurta(d.data_ref)}` : ""}`;
  const regioes = raiz.querySelector("#g-regioes");
  regioes.innerHTML = (d.regioes || []).map((r) => `<button type="button" data-regiao="${r}" class="${r === d.regiao ? "ativo" : ""}" aria-pressed="${r === d.regiao}">${r}</button>`).join("");
  regioes.hidden = !(d.regioes || []).length;
  raiz.querySelector("#g-avisos").innerHTML = d.aviso ? `<div class="aviso">${icone("alerta")}<span>${esc(d.aviso)}</span></div>` : "";
  desenharObjetivos();
  desenharAcoes();
  desenharCorpo();
}

function desenharObjetivos() {
  const d = estado.quadro, el = raiz.querySelector("#g-objetivos");
  const lista = d.objetivos || [];
  if (!d.regiao || (!lista.length && !ctx.admin)) { el.innerHTML = ""; el.hidden = true; return; }
  el.hidden = false;
  const novo = ctx.admin ? `<button type="button" class="ge-obj ge-obj-novo entra" style="--i:${lista.length + 1}" data-objetivo="novo">${icone("mais")}<span>Objetivo do período</span></button>` : "";
  el.innerHTML = `<div class="ge-secao-cab"><h3>${icone("alvo")}Objetivos do período</h3>
      ${lista.length ? `<span>${plural(lista.length, "objetivo", "objetivos")} da equipe ${d.regiao}</span>` : ""}</div>
    <div class="ge-objetivos">${lista.map(cartaoObjetivo).join("")}${novo}</div>`;
  animarEntradas(el);
}

function cartaoObjetivo(o, i) {
  const a = o.andamento, ind = a?.indicador || o.indicador, u = a?.unidade || "";
  let corpo;
  if (!a) {
    corpo = `<span class="ge-obj-num fraco">${esc(o.aviso || "sem números ainda")}</span>`;
  } else if (a.realizado == null) {
    corpo = `<span class="ge-obj-num fraco">${o.situacao === "planejada" ? "ainda não começou" : "sem dados no período"}</span>`;
  } else {
    const semBarra = o.parcial && ind.comportamento === "soma"; // só parte da equipe: a barra contra o alvo de todos enganaria
    const pct = Math.max(0, Math.min(1, a.pct || 0));
    corpo = `${semBarra ? "" : `<span class="ge-obj-barra"><i style="--c:${corStatus(a.status)}" data-largura="${pct * 100}%"></i></span>`}
      <span class="ge-obj-num">${esc(textoProgresso(ind, a.realizado, a.meta, u))}${o.situacao === "planejada" ? " · ainda não começou" : ""}</span>`;
  }
  const parcial = o.parcial ? `<span class="ge-obj-nota">conta só os seus ${o.parcial.vendedores} de ${o.parcial.total} vendedores</span>` : "";
  const cab = `<span class="ge-obj-cab"><b>${icone("alvo")}${esc(o.nome)}</b><small>${esc(periodoCurto(o.inicio, o.fim))}</small></span>`;
  return ctx.admin
    ? `<button type="button" class="ge-obj entra" style="--i:${i + 1}" data-objetivo="${o.id}" title="Editar o objetivo">${cab}${corpo}${parcial}</button>`
    : `<div class="ge-obj entra" style="--i:${i + 1}">${cab}${corpo}${parcial}</div>`;
}

function desenharAcoes() {
  const d = estado.quadro, el = raiz.querySelector("#g-acoes");
  if (!d?.regiao) { el.innerHTML = ""; return; }
  const acoes = d.acoes || [];
  const vigor = acoes.filter((a) => a.situacao === "em_vigor").length;
  el.innerHTML = `<div class="ge-secao-cab"><h3>${icone("bandeira")}Ações da região ${d.regiao}</h3><span class="ge-contagem">${fmt.num(vigor)} em vigor</span></div>
    ${acoes.length ? `<div class="ge-acoes">${acoes.map(cartaoAcao).join("")}</div>`
      : `<p class="ge-vazio">${icone("info")}<span>Nenhuma ação lançada nesta região${ctx.admin ? ". Use Nova ação para marcar os vendedores e lançar." : "."}</span></p>`}`;
  animarEntradas(el);
}

function cartaoAcao(a, i) {
  const enc = a.situacao === "encerrada", plan = a.situacao === "planejada", pz = a.prazo;
  const acaba = !enc && !plan && pz.faltam <= 5;
  const largura = enc ? 100 : plan ? 0 : pz.decorrido * 100;
  const texto = enc ? "Encerrada, resultado no histórico de cada um"
    : plan ? `Começa em ${pz.comeca_em === 1 ? "1 dia" : `${pz.comeca_em} dias`}`
    : pz.faltam === 0 ? "Termina hoje" : acaba ? `Termina em ${pz.faltam === 1 ? "1 dia" : `${pz.faltam} dias`}` : `Faltam ${pz.faltam} dias`;
  const extras = [a.provisorio ? "provisório" : "", a.base_pendente ? "base aguardando os dados" : ""].filter(Boolean).join(" · ");
  const noAlvo = enc && a.com_resultado ? `<span class="ge-no-alvo ${a.no_alvo ? "ok" : "zero"}">${a.no_alvo} de ${a.vendedores} no alvo</span>` : "";
  const classe = enc ? "encerrada" : plan ? "planejada" : acaba ? "acaba" : "em-vigor";
  return `<button type="button" class="ge-acao ${classe} ${estado.vista === "acao" && estado.acao === a.id ? "atual" : ""} entra" style="--i:${i + 1}" data-acao="${a.id}">
    <span class="ge-acao-cab"><b>${esc(a.nome)}</b>${noAlvo}</span>
    <span class="ge-acao-info">${plural(a.vendedores, "vendedor", "vendedores")}, até ${fmt.dataCurta(a.fim)}</span>
    <span class="ge-tempo"><i data-largura="${largura}%"></i></span>
    <span class="ge-prazo">${esc(texto)}${extras ? `<small> · ${esc(extras)}</small>` : ""}</span>
  </button>`;
}

function desenharCorpo() {
  const el = raiz.querySelector("#g-corpo");
  if (estado.vista === "vendedor") { desenharHistorico(); return; }
  if (estado.vista === "acao") { desenharDetalhe(); return; }
  if (!estado.quadro?.regiao) { el.innerHTML = ""; return; }
  if (!el.querySelector("#g-grade")) el.innerHTML = `<div id="g-form"></div><div id="g-grade"></div>`;
  desenharGrade();
}

function desenharGrade() {
  const el = raiz.querySelector("#g-grade");
  if (!el) return;
  const d = estado.quadro, vend = d.vendedores || [];
  const mes = d.mes_faturamento ? `% da meta de faturamento de ${MESES[d.mes_faturamento.mes - 1]}` : "";
  el.innerHTML = `<div class="ge-secao-cab"><h3>${icone("pessoas")}Equipe ${d.regiao}</h3><span>${plural(vend.length, "vendedor", "vendedores")}${mes ? ` · ${mes}` : ""}</span></div>
    ${vend.length ? `<div class="ge-grade ${estado.selecao ? "selecionando" : ""}">${vend.map(quadrado).join("")}</div>`
      : `<p class="ge-vazio">${icone("info")}<span>Nenhum vendedor da região no seu acesso.</span></p>`}`;
}

function quadrado(v) {
  const sel = estado.selecao, marcado = !!sel?.has(v.id);
  const fat = v.faturamento_pct == null ? "Sem meta de faturamento no mês" : `Faturamento ${fmt.pct(v.faturamento_pct, 0)} da meta`;
  const pills = v.acoes.map(etiqueta).join("") || `<span class="ge-sem-acao">Sem ação em vigor</span>`;
  return `<button type="button" class="ge-vend ${marcado ? "marcado" : ""}" data-vendedor="${v.id}" ${sel ? `role="checkbox" aria-checked="${marcado}"` : ""} aria-label="${esc(v.nome)}">
    <span class="ge-vend-cab"><span class="ge-avatar" style="--c:${corAvatar(v.id)}">${esc(iniciais(v.nome))}</span><b>${esc(v.nome)}</b>
      ${sel ? `<span class="ge-caixa">${marcado ? icone("visto") : ""}</span>` : ""}</span>
    <span class="ge-vend-fat">${esc(fat)}${v.inativo ? " · inativo" : ""}</span>
    <span class="ge-pills">${pills}</span></button>`;
}

function etiqueta(e) {
  const pop = estado.recem === e.id ? " pop" : "";
  if (e.situacao === "em_vigor") return `<span class="ge-pill vigor${pop}" title="Em vigor até ${fmt.dataCurta(e.fim)}">${icone("bandeira")}${esc(e.rotulo)}</span>`;
  if (e.situacao === "planejada") return `<span class="ge-pill planejada${pop}" title="Ainda não começou">${icone("calendario")}${esc(e.rotulo)}</span>`;
  const a = acaoDoQuadro(e.id);
  const delta = a && e.delta != null ? deltaTexto(a.indicador, e.delta, a.unidade) : "";
  const cls = ["ok", "mid", "bad"].includes(e.classe) ? e.classe : "";
  return `<span class="ge-pill ${cls}${pop}" title="${esc(rotuloClasse(e.classe))}${e.provisorio ? " (provisório)" : ""}">${esc(e.rotulo)}${delta ? ` ${esc(delta)}` : ""}</span>`;
}

// ---------- ação em lote: marcar os vendedores e lançar ----------
function padraoAcao() {
  return { nome: "", rotulo: "", descricao: "", inicio: estado.quadro?.hoje || hojeLocal(), fim: null, semanas: 3,
           metrica: "mix_medio", parametros: {}, filtros: {}, alvo_tipo: "mais", meta_padrao: "", metas_produto: [] };
}

function formMudou() {
  const f = estado.form;
  return !!(f && f.orig && JSON.stringify(coletarForm()) !== f.orig);
}

// Antes de trocar o que o corpo mostra: confirma se há uma ação preenchida e sai do modo de seleção.
function podeSairDoForm() {
  if (!estado.form) return true;
  if (formMudou() && !confirm(DESCARTAR)) return false;
  estado.form = estado.selecao = null;
  return true;
}

async function entrarSelecao(ids = [], dados = null, extra = {}) {
  if (!ctx.admin || !estado.quadro?.regiao) return;
  if (estado.form && formMudou() && !confirm(DESCARTAR)) return;
  estado.selecao = new Set(ids);
  estado.form = { id: extra.id || null, rascunho: extra.rascunho || null, nomes: extra.nomes || {}, construtor: null, orig: null,
                  dados: { ...padraoAcao(), ...(dados || {}) },
                  metas: new Map((dados?.vendedores || []).map((v) => [v.id, v.meta ?? null])) };
  if (estado.vista !== "grade") {
    estado.vista = "grade";
    estado.historico = estado.detalhe = null;
    atualizarUrl();
    raiz.querySelector("#g-corpo").innerHTML = "";
    desenharAcoes();
  }
  desenharCorpo();
  await montarForm();
  raiz.querySelector("#g-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function sairSelecao() {
  if (estado.form && formMudou() && !confirm(DESCARTAR)) return;
  estado.form = estado.selecao = null;
  const el = raiz.querySelector("#g-form");
  if (el) el.innerHTML = "";
  desenharGrade();
}

function alternar(id) {
  const s = estado.selecao;
  if (s.has(id)) s.delete(id); else s.add(id);
  const card = raiz.querySelector(`.ge-vend[data-vendedor="${id}"]`);
  if (card) {
    const m = s.has(id);
    card.classList.toggle("marcado", m);
    card.setAttribute("aria-checked", m);
    card.querySelector(".ge-caixa").innerHTML = m ? icone("visto") : "";
  }
  contarSelecao();
}

function contarSelecao() {
  const n = estado.selecao?.size || 0, f = estado.form;
  const t = raiz.querySelector("#gf-titulo"), b = raiz.querySelector("[data-lancar] span");
  if (t) t.textContent = f?.id ? `Editar ação · ${plural(n, "vendedor", "vendedores")}` : `Nova ação para ${plural(n, "vendedor", "vendedores")}`;
  if (b) b.textContent = f?.id ? "Salvar alterações" : `Lançar para ${n}`;
  if (n) erroForm("");
}

async function montarForm() {
  const alvo = raiz.querySelector("#g-form"), f = estado.form;
  if (!alvo || !f) return;
  const d = f.dados;
  f.semanas = d.fim ? semanasDe(d.inicio, d.fim) : d.semanas;
  alvo.innerHTML = `<section class="cartao ge-form entra" style="--i:0">
    <div class="ge-form-cab"><div><b id="gf-titulo"></b>
        <span class="fraco">${f.rascunho ? "Rascunho do Assistente: confira e lance. " : ""}Marque os vendedores no quadro abaixo.</span></div>
      <span class="ge-pill">região ${esc(estado.quadro.regiao)}</span></div>
    <div class="ge-campos">
      <label class="campo-form"><span>Ação</span><input name="nome" maxlength="120" value="${esc(d.nome)}" placeholder="Ex.: Aumentar mix médio" autocomplete="off"></label>
      <div class="ge-indicador" id="gf-indicador"><div class="esqueleto" style="height:66px"></div></div>
      <label class="campo-form"><span>Prazo</span><span class="campo"><select name="prazo" style="padding-left:14px"></select></span></label>
      <div class="campo-form ge-alvo"><span>Alvo <small id="gf-unidade"></small></span>
        <span class="ge-alvo-linha"><span class="campo"><select name="alvo_tipo" aria-label="Tipo de alvo" style="padding-left:14px">${Object.entries(ALVOS)
          .map(([k, n]) => `<option value="${k}" ${k === (d.alvo_tipo || "mais") ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></span>
          <input name="meta" type="number" min="0" step="any" inputmode="decimal" value="${d.meta_padrao ?? ""}" placeholder="quanto" aria-label="Número do alvo"></span>
        <small class="ge-previa" id="gf-previa"></small></div>
    </div>
    <div id="gf-precos"></div>
    <details class="ge-mais"><summary>${icone("ajustes")}Mais opções: início, etiqueta, descrição, produtos e clientes que contam</summary>
      <div class="ge-campos">
        <label class="campo-form"><span>Início</span><input type="date" name="inicio" value="${esc(d.inicio)}"></label>
        <label class="campo-form" id="gf-fim-bloco" ${f.semanas ? "hidden" : ""}><span>Fim</span><input type="date" name="fim" value="${esc(d.fim || somar(d.inicio, 20))}"></label>
        <label class="campo-form"><span>Etiqueta no quadro <small>(até 20 letras)</small></span><input name="rotulo" maxlength="20" value="${esc(d.rotulo || "")}" autocomplete="off"></label>
        <label class="campo-form ge-largo"><span>Descrição <small>(opcional)</small></span><textarea name="descricao" rows="2" maxlength="2000" placeholder="Objetivo e combinados da ação">${esc(d.descricao || "")}</textarea></label>
      </div>
      <div id="gf-filtros"></div>
    </details>
    <p class="form-erro" role="alert" hidden></p>
    <div class="ge-form-acoes">
      <button class="btn" type="button" data-cancelar-form>Cancelar</button>
      <button class="btn primario" type="button" data-lancar>${icone(f.id ? "disco" : "bandeira")}<span></span></button>
    </div>
  </section>`;
  desenharPrazos(f.semanas ? String(f.semanas) : "data");
  contarSelecao();
  animarEntradas(alvo);
  const cat = await carregarCatalogo();
  if (estado.form !== f) return; // cancelou ou abriu outra enquanto o catálogo vinha
  if (!cat) {
    alvo.querySelector("#gf-indicador").innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Não foi possível carregar produtos e clientes: ${esc(estado.erroCatalogo)}</span></p>`;
    return;
  }
  f.construtor = construtorIndicador(alvo.querySelector("#gf-indicador"), {
    catalogo: cat, inicial: d, nomes: f.nomes, filtrosEm: alvo.querySelector("#gf-filtros"), precosEm: alvo.querySelector("#gf-precos"),
    aoMudar: atualizarAlvo,
  });
  if (f.construtor.temFiltros() || d.descricao || d.rotulo || !f.semanas) alvo.querySelector(".ge-mais").open = true;
  atualizarAlvo();
  f.orig = JSON.stringify(coletarForm());
}

function desenharPrazos(valor) {
  const form = raiz.querySelector("#g-form"), el = form?.querySelector('[name="prazo"]');
  if (!el) return;
  const atual = valor || el.value;
  const inicio = form.querySelector('[name="inicio"]').value || estado.quadro.hoje;
  el.innerHTML = PRAZOS.map((n) => `<option value="${n}">${n} semana${n === 1 ? "" : "s"}, até ${fmt.dataCurta(somar(inicio, 7 * n - 1))}</option>`).join("")
    + `<option value="data">Até uma data (em Mais opções)</option>`;
  el.value = atual;
}

function atualizarAlvo() {
  const f = estado.form, form = raiz.querySelector("#g-form");
  if (!f?.construtor || !form) return;
  const pr = f.construtor.preset(), desc = f.construtor.descritor();
  const preco = pr.metrica === "preco_medio";
  const tipo = form.querySelector('[name="alvo_tipo"]').value;
  form.querySelector(".ge-alvo-linha").hidden = preco;
  form.querySelector("#gf-unidade").textContent = preco ? "" : tipo === "pct" ? "(% sobre a base)"
    : `(${f.construtor.unidadeAlvo() || "valor"}${tipo === "mais" && pr.pct ? ", em pontos" : ""})`;
  const meta = form.querySelector('[name="meta"]').value;
  form.querySelector("#gf-previa").textContent = preco ? "No preço-alvo de cada produto (100%)."
    : meta !== "" ? `${capitalizar(textoAlvo(desc, tipo, Number(meta), desc.unidade))}.` : "";
  form.querySelector('[name="rotulo"]').placeholder = pr.rotulo;
}

function coletarForm() {
  const f = estado.form, form = raiz.querySelector("#g-form");
  const val = (n) => form?.querySelector(`[name="${n}"]`)?.value ?? "";
  const prazo = val("prazo");
  const ind = f.construtor ? f.construtor.valor()
    : { metrica: f.dados.metrica, parametros: f.dados.parametros, filtros: f.dados.filtros, metas_produto: f.dados.metas_produto || [] };
  const preco = ind.metrica === "preco_medio";
  return {
    nome: val("nome").trim(), rotulo: val("rotulo").trim(), descricao: val("descricao").trim(), regiao: estado.quadro?.regiao,
    inicio: val("inicio"), ...(prazo === "data" ? { fim: val("fim") } : { semanas: Number(prazo) }), ...ind,
    alvo_tipo: preco ? "fixo" : val("alvo_tipo"), meta_padrao: preco ? 100 : (val("meta") === "" ? null : Number(val("meta"))),
    vendedores: [...(estado.selecao || [])].map((id) => ({ id, meta: f.metas.get(id) ?? null })),
  };
}

function erroForm(msg) {
  const el = raiz.querySelector("#g-form .form-erro");
  if (!el) return;
  el.textContent = msg ? capitalizar(msg) : "";
  el.hidden = !msg;
  if (msg) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function lancar() {
  const f = estado.form;
  if (!f) return;
  if (!f.construtor) return erroForm("espere carregar os produtos e os clientes");
  const dados = coletarForm();
  if (!dados.vendedores.length) return erroForm("marque ao menos um vendedor");
  if (!dados.nome) return erroForm("dê um nome à ação");
  if (dados.metrica === "preco_medio") {
    if (!dados.metas_produto.length) return erroForm("escolha os produtos do preço médio");
    if (dados.metas_produto.some((p) => !(p.meta > 0))) return erroForm("dê o preço-alvo de cada produto (R$ por unidade)");
  } else if (!(dados.meta_padrao > 0)) {
    return erroForm("dê o alvo");
  }
  const btn = raiz.querySelector("[data-lancar]");
  btn.disabled = true;
  erroForm("");
  try {
    const r = f.id
      ? await api("/api/gestao/acao/editar", { json: { id: f.id, acao: dados } })
      : await api("/api/gestao/acoes", { json: { acao: dados, rascunho: f.rascunho } });
    const id = f.id || r.id;
    toast(f.id ? "Ação salva" : r.ja_existia ? "Este rascunho já tinha virado ação" : `Ação lançada para ${plural(dados.vendedores.length, "vendedor", "vendedores")}`);
    estado.form = estado.selecao = null;
    raiz.querySelector("#g-form").innerHTML = "";
    estado.recem = id;
    setTimeout(() => { if (estado.recem === id) estado.recem = null; }, 1600);
    await carregar(true);
  } catch (e) {
    erroForm(e.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------- histórico interno do vendedor ----------
async function abrirVendedor(id) {
  if (estado.selecao && estado.vista === "grade") return alternar(id);
  if (!podeSairDoForm()) return;
  estado.vista = "vendedor";
  estado.vendedor = id;
  estado.historico = null;
  atualizarUrl();
  desenharAcoes();
  carregarVista({ rolar: true });
}

function voltarGrade() {
  if (raiz.querySelector("#g-nota")?.value.trim() && !confirm("Descartar a observação que você escreveu?")) return;
  estado.vista = "grade";
  estado.historico = estado.detalhe = null;
  atualizarUrl();
  raiz.querySelector("#g-corpo").innerHTML = "";
  desenharAcoes();
  desenharCorpo();
}

function desenharHistorico() {
  const h = estado.historico, el = raiz.querySelector("#g-corpo");
  if (!h) return;
  const v = h.vendedor;
  let corpo = "", dia = null;
  for (const e of h.eventos) {
    if (e.data !== dia) { corpo += `<div class="ge-dia"><span>${fmt.dataCurta(e.data)}</span></div>`; dia = e.data; }
    corpo += evento(e, h);
  }
  if (!h.eventos.length) corpo = `<p class="ge-hist-vazio">${h.pode_editar ? "Nenhum registro ainda. Lance uma ação ou escreva uma observação." : "Nenhum registro ainda."}</p>`;
  el.innerHTML = `<section class="cartao ge-hist entra" style="--i:0">
    <header class="ge-hist-cab">
      <button class="btn icone" type="button" data-voltar title="Voltar ao quadro" aria-label="Voltar ao quadro">${icone("voltar")}</button>
      <span class="ge-avatar grande" style="--c:${corAvatar(v.id)}">${esc(iniciais(v.nome))}</span>
      <div class="ge-hist-quem"><b>${esc(v.nome)}</b>
        <small>${esc(v.regiao || v.equipe || "")}, ${plural(h.em_vigor, "ação em vigor", "ações em vigor")}${v.inativo ? " · inativo no ERP" : ""}</small></div>
      <span class="ge-cadeado" title="O vendedor não vê este histórico">${icone("cadeado")}Só controle interno</span>
    </header>
    <div class="ge-hist-corpo">${corpo}</div>
    ${h.pode_editar ? `<div class="ge-hist-rodape">
      <textarea id="g-nota" rows="1" maxlength="2000" placeholder="Escreva uma observação sobre ${esc(primeiroNome(v.nome))}" aria-label="Observação sobre ${esc(v.nome)}"></textarea>
      <button class="btn primario icone" type="button" data-enviar-nota title="Gravar a observação" aria-label="Gravar a observação">${icone("enviar")}</button>
      <button class="btn" type="button" data-acao-para="${v.id}" title="Lançar uma ação só para ${esc(v.nome)}">${icone("bandeira")}Ação</button>
    </div>` : ""}
  </section>`;
  animarEntradas(el);
}

function evento(e, h) {
  const a = h.acoes[String(e.acao)] || null;
  const ind = a?.indicador || { formato: "razao", casas: 2 };
  const u = a?.unidade || "";
  const val = (x) => esc(valorIndicador(ind, x, u));
  const d = e.dados || {};
  const nome = esc(d.nome || a?.nome || "");
  switch (e.tipo) {
    case "nota":
      return `<div class="ge-bolha dir"><p>${icone("lapis")}<span>${esc(e.texto)}</span></p>
        <small>${esc(e.autor)} · ${hora(e.criada_em)}${h.pode_editar ? `<button type="button" class="ge-x" data-excluir-nota="${e.id}" title="Apagar a observação" aria-label="Apagar a observação">${icone("x")}</button>` : ""}</small></div>`;
    case "lancada": {
      const base = d.base_pendente ? `Base: aguardando os dados de ${fmt.dataCurta(d.base_inicio)} a ${fmt.dataCurta(d.base_fim)}`
        : d.base == null ? `Base: sem dados ${janelaTexto(d.base_inicio, d.base_fim)}` : `Base: ${val(d.base)} ${janelaTexto(d.base_inicio, d.base_fim)}`;
      const alvo = d.alvo == null ? (d.base_pendente ? "Alvo: sai da base, quando ela chegar" : "Alvo: sem base para calcular")
        : `Alvo: ${val(d.alvo)} até ${fmt.dataCurta(d.fim)}`;
      return `<div class="ge-bolha esq"><b>${icone("bandeira")}Ação lançada: ${nome}</b>
        <p>${base}<br>${alvo}${d.vendedores > 1 ? `<br>Mesma ação para ${d.vendedores} vendedores` : ""}</p>
        <small>${esc(e.autor)}${a ? ` · <button type="button" class="ge-link" data-acao="${e.acao}">ver a ação</button>` : ""}</small></div>`;
    }
    case "parcial":
      return `<p class="ge-linha">${icone("grafico")}Parcial da semana ${d.semana}${a ? ` de ${esc(a.rotulo)}` : ""}: <b>${val(d.valor)}</b></p>`;
    case "resultado":
      return cartaoResultado(e, a, ind, u, h);
    case "prorrogada":
      return `<p class="ge-linha sistema">${icone("calendario")}${nome} prorrogada até ${fmt.dataCurta(d.fim)}${d.base_pendente ? "; a base nova aguarda os dados"
        : `; base refeita ${janelaTexto(d.base_inicio, d.base_fim)}: ${val(d.base)}, alvo ${val(d.alvo)}`} · ${esc(e.autor)}</p>`;
    case "encerrada":
      return `<p class="ge-linha sistema">${icone("certo")}${nome} encerrada em ${fmt.dataCurta(d.fim)}${d.fim_antes && d.fim_antes !== d.fim ? ` (ia até ${fmt.dataCurta(d.fim_antes)})` : ""} · ${esc(e.autor)}</p>`;
    case "editada":
      return `<p class="ge-linha sistema">${icone("lapis")}${nome} alterada (${esc((d.mudou || []).join(", "))})${d.alvo != null ? `: alvo ${val(d.alvo)}` : d.base_pendente ? ": a base nova aguarda os dados" : ""} · ${esc(e.autor)}</p>`;
    case "removido":
      return `<p class="ge-linha sistema">${icone("x")}Saiu da ação ${nome} · ${esc(e.autor)}</p>`;
    default:
      return "";
  }
}

function cartaoResultado(e, a, ind, u, h) {
  const d = e.dados || {};
  const cls = d.classe || "sem_dados";
  const valores = [d.base, d.alvo, d.resultado].filter((x) => x != null);
  const mx = Math.max(...valores, 0) || 1;
  const cor = { ok: "var(--ok-forte)", mid: "var(--atencao-forte)", bad: "var(--ruim-forte)" }[cls] || "var(--linha-forte)";
  const barra = (rotulo, v, c) => `<div class="ge-barra"><span>${rotulo}</span><span class="ge-barra-trilho"><i style="--c:${c}" data-largura="${v == null ? 0 : (Math.max(0, v) / mx) * 100}%"></i></span>
    <b>${v == null ? "—" : esc(valorIndicador(ind, v, u, true))}</b></div>`;
  const delta = d.delta != null
    ? `${esc(deltaTexto(ind, d.delta, u))} sobre a base${d.delta_pct != null
      ? ` (${d.delta_pct >= 0 ? "+" : "−"}${fmt.num(Math.abs(d.delta_pct) * 100, Math.abs(d.delta_pct) < 0.1 ? 1 : 0)}%)` : ""}` : "";
  const botoes = e.atual && h.pode_editar && a ? `<div class="ge-resultado-acoes">
      ${e.provisorio ? `<button class="btn" type="button" data-encerrar="${a.id}">${icone("certo")}Encerrar ação</button>` : ""}
      <button class="btn" type="button" data-prorrogar="${a.id}">${icone("calendario")}Prorrogar 2 semanas</button></div>` : "";
  return `<div class="ge-resultado ${cls}">
    <div class="ge-resultado-cab"><b>${icone("ranking")}Resultado: ${esc(d.nome || a?.nome || "")}</b><span class="ge-pill ${cls}">${esc(rotuloClasse(cls, d.caminho))}</span></div>
    ${barra("Base", d.base, "var(--s-ritmo)")}${barra("Alvo", d.alvo, "var(--linha-forte)")}${barra("Resultado", d.resultado, cor)}
    ${delta ? `<p class="ge-delta">${delta}</p>` : ""}
    ${e.provisorio ? `<p class="ge-delta fraco">Provisório: os dados vão até ${fmt.dataCurta(h.data_ref)}; o resultado fecha quando passarem do fim.</p>` : ""}
    ${botoes}</div>`;
}

async function enviarNota() {
  const t = raiz.querySelector("#g-nota"), btn = raiz.querySelector("[data-enviar-nota]");
  const texto = t?.value.trim();
  if (!texto) return;
  btn.disabled = true;
  try {
    await api("/api/gestao/notas", { json: { id_vendedor: estado.vendedor, texto } });
    t.value = "";
    await carregarVista({ silencioso: true });
    raiz.querySelector("#g-nota")?.focus();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

async function excluirNota(id) {
  if (!confirm("Apagar esta observação?")) return;
  try {
    await api("/api/gestao/nota/excluir", { json: { id } });
    await carregarVista({ silencioso: true });
  } catch (e) {
    toast(e.message, "erro");
  }
}

// O botão "Ação" do histórico: volta ao quadro com o vendedor já marcado.
async function acaoPara(id) {
  const v = estado.historico?.vendedor;
  if (raiz.querySelector("#g-nota")?.value.trim() && !confirm("Descartar a observação que você escreveu?")) return;
  if (v?.regiao && v.regiao !== estado.regiao) {
    estado.regiao = v.regiao;
    await carregar(true);
  }
  entrarSelecao([id]);
}

// ---------- detalhe da ação ----------
function abrirAcao(id) {
  if (!podeSairDoForm()) return;
  estado.vista = "acao";
  estado.acao = id;
  estado.abrir = null;
  estado.detalhe = null;
  atualizarUrl();
  desenharAcoes();
  carregarVista({ rolar: true });
}

function desenharDetalhe() {
  const d = estado.detalhe, el = raiz.querySelector("#g-corpo");
  if (!d) return;
  const it = d.item;
  if (it.tipo === "objetivo") { // link para um objetivo: ele aparece no topo
    estado.vista = "grade";
    atualizarUrl();
    el.innerHTML = "";
    desenharCorpo();
    return;
  }
  const ind = d.indicador || it.indicador, u = d.unidade || "", m = visual(ind);
  const filtros = [...textoFiltros(it.filtros || {}), ...textoBase(ind)];
  const enc = it.situacao === "encerrada";
  const resumo = enc ? `${d.total.no_alvo} de ${d.total.vendedores} no alvo · ${plural(d.total.acima_da_base, "acima da base", "acima da base")}`
    : it.situacao === "planejada" ? `${plural(d.total.vendedores, "vendedor", "vendedores")} · começa em ${fmt.dataCurta(it.inicio)}`
    : `${plural(d.total.vendedores, "vendedor", "vendedores")} · dados até ${fmt.dataCurta(d.data_ref)}`;
  const pergunta = `Como está a ação #${it.id} “${it.nome}”, vendedor por vendedor?`;
  const botoes = d.pode_editar ? `
    <button class="btn" type="button" data-editar-acao="${it.id}">${icone("lapis")}<span>Editar</span></button>
    ${!it.congelado && it.situacao !== "planejada" ? `<button class="btn" type="button" data-encerrar="${it.id}">${icone("certo")}<span>Encerrar</span></button>` : ""}
    <button class="btn" type="button" data-prorrogar="${it.id}">${icone("calendario")}<span>Prorrogar 2 semanas</span></button>
    <button class="btn icone" type="button" data-arquivar-acao="${it.id}" data-arquivada="${it.arquivada ? "0" : "1"}" title="${it.arquivada ? "Voltar ao quadro" : "Arquivar (sai do quadro; o histórico fica)"}" aria-label="${it.arquivada ? "Tirar do arquivo" : "Arquivar"}">${icone("arquivo")}</button>
    <button class="btn icone perigo" type="button" data-excluir-acao="${it.id}" title="Excluir a ação" aria-label="Excluir a ação">${icone("lixeira")}</button>` : "";
  const avisos = [d.aviso, ...(d.avisos || [])].filter(Boolean).map((t) => `<div class="aviso">${icone("alerta")}<span>${esc(t)}</span></div>`).join("");
  el.innerHTML = `<section class="cartao secao camp-detalhe entra" style="--i:0;--c:${m.cor}">
      <div class="cartao-cab">
        <div class="ge-det-tit"><button class="btn icone" type="button" data-voltar title="Voltar ao quadro" aria-label="Voltar ao quadro">${icone("voltar")}</button>
          <div><h2>${icone(m.icone)}${esc(it.nome)}</h2>
            <p class="sub">${esc(ind.nome)} · ${esc(periodoTexto(it.inicio, it.fim))} · alvo ${esc(textoAlvo(ind, it.alvo_tipo, it.meta_padrao, u))} · lançada por ${esc(it.criada_por_nome)}</p></div></div>
        <div class="camp-acoes">${ctx.assistente ? `<a class="btn" href="#/assistente?q=${encodeURIComponent(pergunta)}" title="Abre o Assistente com a pergunta pronta">${icone("conversa")}<span>Perguntar ao Assistente</span></a>` : ""}${botoes}</div>
      </div>
      <div class="camp-chips">
        <span class="ge-pill ${enc ? "" : it.situacao === "planejada" ? "planejada" : "vigor"}">${esc(SITUACAO[it.situacao])}${it.provisorio ? " · provisório" : ""}</span>
        <span class="chip">${icone("calendario")}base: ${esc(periodoTexto(it.base_inicio, it.base_fim))} (o mesmo tamanho, logo antes)</span>
        ${(filtros.length ? filtros : ["todos os produtos e clientes"]).map((t) => `<span class="chip">${icone("funil")}${esc(t)}</span>`).join("")}
        ${it.arquivada ? `<span class="chip">${icone("arquivo")}arquivada</span>` : ""}
      </div>
      ${it.descricao ? `<p class="camp-descricao">${esc(it.descricao)}</p>` : ""}
      <p class="ge-det-resumo">${esc(resumo)}${d.ocultos ? ` · ${plural(d.ocultos, "vendedor fora do seu acesso", "vendedores fora do seu acesso")}` : ""}</p>
    </section>
    ${avisos}${ind.tipo === "preco_medio" && d.produtos?.length ? gradePrecos(d) : tabelaAcao(d)}${aberturaAcao(d)}`;
  animarEntradas(el);
  ligarTooltips(el);
}

function tabelaAcao(d) {
  if (!d.linhas.length) return `<div class="cartao secao vazio">${icone("pessoas")}<p>Nenhum vendedor da ação no seu acesso.</p></div>`;
  const it = d.item, ind = d.indicador, u = d.unidade;
  const v = (x) => esc(valorIndicador(ind, x, u));
  const enc = it.situacao === "encerrada";
  const partes = !!ind.numerador && !it.congelado;
  const linhas = d.linhas.map((x) => `<tr class="ge-clicavel" data-vendedor="${x.id}" tabindex="0" title="Abrir o histórico de ${esc(x.nome)}">
    <td class="nome-v">${esc(x.nome)}<small>código ${x.id}${x.equipe ? ` · ${esc(x.equipe)}` : ""}</small></td>
    <td>${x.base_pendente ? '<span class="fraco">aguardando os dados</span>' : x.base == null ? '<span class="fraco">sem dados</span>' : v(x.base)}</td>
    <td>${x.alvo == null ? "—" : v(x.alvo)}</td>
    <td>${x.resultado == null ? "—" : `<b>${v(x.resultado)}</b>`}${partes && x.numerador != null
      ? `<small>${valorParte(ind, x.numerador)} ÷ ${valorParte(ind, x.denominador)}</small>` : ""}</td>
    <td>${x.delta == null ? "—" : esc(deltaTexto(ind, x.delta, u))}</td>
    <td>${enc ? `<span class="ge-pill ${x.classe}">${esc(rotuloClasse(x.classe, x.caminho))}</span>`
      : it.situacao === "planejada" ? chipStatus("sem_meta", "Não começou") : x.status ? chipStatus(x.status, rotuloStatus(ind, x.status)) : "—"}</td></tr>`).join("");
  return `<section class="cartao secao entra" style="--i:2">
    <div class="cartao-cab"><div><h3>${icone("pessoas")}Por vendedor</h3>
      <p class="sub">${enc ? (it.congelado ? "resultado congelado no fim da ação" : "resultado provisório: os dados ainda não passaram do fim")
        : "resultado até agora; a situação considera o ritmo dos dias úteis"} · clique no vendedor para ver o histórico</p></div></div>
    <div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>Vendedor</th><th>Base</th><th>Alvo</th><th${partes ? ` title="${esc(ind.numerador)} ÷ ${esc(ind.denominador)}"` : ""}>Resultado</th><th>Sobre a base</th><th>Situação</th></tr></thead>
      <tbody>${linhas}</tbody></table></div></section>`;
}

// A mesma conta aberta por área, segmento ou produto (os vendedores do acesso, juntos), enquanto a ação corre.
function aberturaAcao(d) {
  const ind = d.indicador;
  if (!ind.aberturas?.length || d.item.congelado || d.item.situacao === "planejada") return "";
  const ab = d.abertura;
  const opcoes = [["", "Não abrir"], ...ind.aberturas.map((k) => [k, ABERTURAS[k]])]
    .map(([k, n]) => `<option value="${k}" ${k === (ab?.por || "") ? "selected" : ""}>${esc(n)}</option>`).join("");
  const comPartes = !!ind.numerador;
  const linhas = (ab?.linhas || []).map((x) => `<tr>
    <td class="nome-v">${esc(x.nome)}</td><td>${esc(valorIndicador(ind, x.valor, d.unidade))}</td>
    ${comPartes ? `<td>${valorParte(ind, x.numerador)}</td><td>${valorParte(ind, x.denominador)}</td>` : ""}</tr>`).join("");
  return `<section class="cartao secao entra" style="--i:3">
    <div class="cartao-cab"><div><h3>${icone("funil")}Aberto por ${esc(ab ? ABERTURAS[ab.por].toLowerCase() : "…")}</h3>
      <p class="sub">os vendedores da ação juntos${ab?.mais ? ` · mostrando ${ab.linhas.length} de ${ab.linhas.length + ab.mais}` : ""}</p></div>
      <label class="campo"><select data-abrir aria-label="Abrir por" style="padding-left:14px">${opcoes}</select></label></div>
    ${ab ? `<div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>${esc(ABERTURAS[ab.por])}</th><th>${esc(ind.nome)}</th>${comPartes ? `<th>${esc(ind.numerador)}</th><th>${esc(ind.denominador)}</th>` : ""}</tr></thead>
      <tbody>${linhas || `<tr><td colspan="4" class="fraco">Nada no período.</td></tr>`}</tbody></table></div>`
      : `<p class="usu-nota">${icone("info")}<span>Escolha como abrir o resultado: por ${ind.aberturas.map((k) => ABERTURAS[k].toLowerCase()).join(", ")}.</span></p>`}
  </section>`;
}

// Preço médio: o preço de cada vendedor em cada produto, contra o preço-alvo (enquanto a ação corre).
function gradePrecos(d) {
  const reais2 = (v) => "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const prods = d.produtos, ind = d.indicador;
  const cor = (pct) => (pct == null ? "" : pct >= 1 ? "var(--ok)" : pct >= 0.9 ? "var(--atencao)" : "var(--ruim)");
  const cel = (p) => (p?.preco == null ? '<td class="fraco">—</td>'
    : `<td><b style="color:${cor(p.pct)}">${reais2(p.preco)}</b><small>${fmt.pct(p.pct)} · ${fmt.num(p.quantidade, 1)} ${esc((p.unidade || "").toLowerCase())}</small></td>`);
  const linhas = d.linhas.map((x) => {
    const por = Object.fromEntries((x.produtos || []).map((p) => [p.id, p]));
    return `<tr class="ge-clicavel" data-vendedor="${x.id}" tabindex="0"><td class="nome-v">${esc(x.nome)}<small>código ${x.id}${x.equipe ? ` · ${esc(x.equipe)}` : ""}</small></td>
      ${prods.map((p) => cel(por[p.id])).join("")}
      <td>${x.resultado != null ? `<b>${fmt.pct(x.resultado)}</b>` : "—"}</td>
      <td>${x.base != null ? fmt.pct(x.base) : '<span class="fraco">sem base</span>'}</td>
      <td>${x.status ? chipStatus(x.status, rotuloStatus(ind, x.status)) : "—"}</td></tr>`;
  }).join("");
  return `<section class="cartao secao entra" style="--i:2">
    <div class="cartao-cab"><div><h3>${icone("moeda")}Preço médio por produto</h3>
      <p class="sub">venda líquida ÷ quantidade de cada vendedor, contra o preço-alvo; o índice compara o que vendeu com o que seria nos preços-alvo (100% = no alvo)</p></div></div>
    <div class="tabela-rolagem"><table class="dados camp-grade">
      <thead><tr><th>Vendedor</th>${prods.map((p) => `<th title="${esc(p.nome)}">${esc(p.nome)}<small>alvo ${reais2(p.meta)}${p.unidade ? `/${esc(p.unidade.toLowerCase())}` : ""}</small></th>`).join("")}<th>Índice</th><th>Base</th><th>Situação</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td class="nome-v">Total</td>${prods.map(cel).join("")}<td><b>${d.total.realizado != null ? fmt.pct(d.total.realizado) : "—"}</b></td><td></td><td></td></tr></tfoot>
    </table></div></section>`;
}

// ---------- gravação (só o administrador) ----------
// nome, quantos vendedores e o fim: do detalhe aberto, do histórico ou do quadro.
function infoAcao(id) {
  const det = estado.detalhe?.item;
  if (det && det.id === id) return { nome: det.nome, n: det.vendedores?.length || estado.detalhe.total.vendedores, fim: det.fim };
  const h = estado.historico?.acoes?.[String(id)];
  if (h) return { nome: h.nome, n: h.vendedores, fim: h.fim };
  const q = acaoDoQuadro(id);
  return q ? { nome: q.nome, n: q.total_vendedores, fim: q.fim } : { nome: `#${id}`, n: 0, fim: null };
}
const paraQuem = (n) => (n === 1 ? "o vendedor" : n ? `os ${n} vendedores` : "os vendedores");

async function encerrar(id) {
  const a = infoAcao(id), ate = estado.quadro?.data_ref;
  if (!confirm(`Encerrar “${a.nome}” para ${paraQuem(a.n)} dela? O resultado de cada um fica congelado${ate ? ` com os dados até ${fmt.dataCurta(ate)}` : ""}.`)) return;
  try {
    await api("/api/gestao/acao/encerrar", { json: { id } });
    toast("Ação encerrada");
    await recarregarTudo();
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function prorrogar(id) {
  const a = infoAcao(id);
  const novo = a.fim ? ` (até ${fmt.dataCurta(somar(a.fim, 14))})` : "";
  if (!confirm(`Prorrogar “${a.nome}” por 2 semanas para ${paraQuem(a.n)} dela${novo}? A base de cada um é medida de novo, no mesmo tamanho do novo prazo.`)) return;
  try {
    await api("/api/gestao/acao/prorrogar", { json: { id, dias: 14 } });
    toast("Ação prorrogada por 2 semanas");
    await recarregarTudo();
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function arquivar(id, sim) {
  try {
    await api("/api/gestao/acao/arquivar", { json: { id, arquivada: sim } });
    toast(sim ? "Ação arquivada: saiu do quadro (o histórico dos vendedores continua)" : "A ação voltou ao quadro");
    await recarregarTudo();
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function excluirAcao(id) {
  const a = infoAcao(id);
  if (!confirm(`Excluir “${a.nome}”? O histórico dos vendedores perde os registros desta ação (as observações ficam).`)) return;
  try {
    await api("/api/gestao/acao/excluir", { json: { id } });
    toast("Ação excluída");
    estado.vista = "grade";
    estado.detalhe = null;
    atualizarUrl();
    raiz.querySelector("#g-corpo").innerHTML = "";
    await carregar(true);
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function editarAcao(id) {
  let it = estado.detalhe?.item?.id === id ? estado.detalhe.item : null;
  try {
    if (!it) it = (await api(`/api/gestao/acao?id=${id}&abrir=`)).item;
  } catch (e) {
    return toast(e.message, "erro");
  }
  if (it.regiao !== estado.regiao) {
    estado.regiao = it.regiao;
    await carregar(true);
  }
  entrarSelecao(it.vendedores.map((v) => v.id), it, { id: it.id });
}

// ---------- rascunho do Assistente ----------
async function abrirRascunho(uuid) {
  atualizarUrl();
  if (!ctx.admin) { toast("Só o administrador lança ações; peça a ele.", "erro"); return; }
  try {
    const r = await api(`/api/gestao/rascunho?id=${encodeURIComponent(uuid)}`);
    if (r.acao) {
      toast(`Este rascunho já virou a ação “${r.acao.nome}”`);
      if (r.acao.regiao) estado.regiao = r.acao.regiao;
      estado.vista = "acao";
      estado.acao = r.acao.id;
      atualizarUrl();
      await carregar(true);
      return carregarVista({ rolar: true });
    }
    const d = r.rascunho;
    let regiao = d.regiao;
    if (!regiao) { // rascunho de antes das regiões: a dos vendedores
      const cat = await carregarCatalogo();
      const equipes = (d.vendedores || []).map((v) => cat?.vendedores.find((x) => x.id === v.id)?.equipe);
      regiao = equipes.filter((e) => e === "ES").length >= equipes.filter((e) => e === "BA" || e === "EDIR").length ? "ES" : "BA";
    }
    estado.regiao = regiao;
    await carregar(true);
    entrarSelecao((d.vendedores || []).map((v) => v.id), { ...d, alvo_tipo: d.alvo_tipo || "fixo" }, { rascunho: d.id, nomes: d.nomes });
  } catch (e) {
    toast(e.message, "erro");
  }
}

// ---------- objetivos (janela) ----------
function criarJanela() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo camp-dialogo";
  dlg.setAttribute("aria-labelledby", "go-titulo");
  document.body.appendChild(dlg);
  dlg.addEventListener("cancel", (e) => {
    if (dlg.querySelector(".multi-painel:not([hidden])")) { e.preventDefault(); return; } // o Esc era da lista
    if (objetivoMudou() && !confirm("Descartar o que foi preenchido neste objetivo?")) e.preventDefault();
  });
  dlg.addEventListener("close", () => { formObj = null; });
}

function coletarObjetivo() {
  const f = dlg.querySelector("form");
  const val = (n) => f.querySelector(`[name="${n}"]`).value;
  const ind = formObj.construtor ? formObj.construtor.valor() : {};
  const preco = ind.metrica === "preco_medio";
  return { nome: val("nome").trim(), regiao: formObj.regiao, inicio: val("inicio"), fim: val("fim"), ...ind,
           meta_padrao: preco ? 100 : (val("meta") === "" ? null : Number(val("meta"))), descricao: val("descricao").trim() };
}

function objetivoMudou() {
  return !!(formObj?.orig && dlg?.open && JSON.stringify(coletarObjetivo()) !== formObj.orig);
}

async function abrirObjetivo(id) {
  if (!ctx.admin || !estado.quadro?.regiao) return;
  const o = id === "novo" ? null : (estado.quadro.objetivos || []).find((x) => String(x.id) === String(id));
  const hoje = estado.quadro.hoje;
  const d = o || { nome: "", inicio: `${hoje.slice(0, 8)}01`, fim: fimDoMes(hoje), metrica: "positivacao", parametros: {}, filtros: {},
                   meta_padrao: "", metas_produto: [], descricao: "" };
  formObj = { id: o?.id || null, regiao: o?.regiao || estado.quadro.regiao, construtor: null, orig: null };
  dlg.innerHTML = `<form novalidate>
    <h2 id="go-titulo">${icone("alvo")}${o ? "Editar objetivo" : "Novo objetivo do período"}</h2>
    <p class="sub">Equipe ${esc(formObj.regiao)}: o indicador da equipe toda (sem repetir clientes entre os vendedores), contra um alvo da equipe.</p>
    <div class="cf-grade">
      <label class="campo-form largo"><span>Nome</span><input name="nome" maxlength="120" value="${esc(d.nome)}" placeholder="Ex.: Mix médio da equipe" autocomplete="off"></label>
      <label class="campo-form"><span>Início</span><input type="date" name="inicio" value="${esc(d.inicio)}"></label>
      <label class="campo-form"><span>Fim</span><input type="date" name="fim" value="${esc(d.fim)}"></label>
      <div class="largo ge-indicador" id="go-indicador"><div class="esqueleto" style="height:66px"></div></div>
      <label class="campo-form" id="go-meta-bloco"><span>Alvo da equipe <small id="go-unidade"></small></span>
        <input type="number" name="meta" min="0" step="any" inputmode="decimal" value="${d.meta_padrao ?? ""}"></label>
      <div class="largo" id="go-precos"></div>
      <div class="largo" id="go-filtros"></div>
      <label class="campo-form largo"><span>Descrição <small>(opcional)</small></span><textarea name="descricao" rows="2" maxlength="2000">${esc(d.descricao || "")}</textarea></label>
    </div>
    <p class="form-erro" role="alert" hidden></p>
    <div class="dialogo-acoes">
      ${o ? `<button class="btn perigo" type="button" data-excluir-obj style="margin-right:auto">${icone("lixeira")}Excluir</button>` : ""}
      <button class="btn" type="button" data-cancelar>Cancelar</button>
      <button class="btn primario" type="submit">${icone(o ? "disco" : "mais")}${o ? "Salvar" : "Criar objetivo"}</button>
    </div></form>`;
  const f = dlg.querySelector("form");
  const erro = (msg) => { const el = f.querySelector(".form-erro"); el.textContent = capitalizar(msg); el.hidden = !msg; };
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const dados = coletarObjetivo();
    if (!dados.nome) return erro("dê um nome ao objetivo");
    if (!dados.inicio || !dados.fim) return erro("escolha o início e o fim");
    if (dados.metrica !== "preco_medio" && !(dados.meta_padrao > 0)) return erro("dê o alvo da equipe");
    const btn = f.querySelector('button[type="submit"]');
    btn.disabled = true;
    erro("");
    try {
      if (formObj.id) await api("/api/gestao/objetivo/editar", { json: { id: formObj.id, objetivo: dados } });
      else await api("/api/gestao/objetivos", { json: { objetivo: dados } });
      toast(formObj.id ? "Objetivo salvo" : "Objetivo criado");
      formObj = null;
      dlg.close();
      await carregar(true);
    } catch (err) {
      erro(err.message);
    } finally {
      btn.disabled = false;
    }
  });
  f.querySelector("[data-cancelar]").addEventListener("click", () => {
    if (objetivoMudou() && !confirm("Descartar o que foi preenchido neste objetivo?")) return;
    dlg.close();
  });
  f.querySelector("[data-excluir-obj]")?.addEventListener("click", async () => {
    if (!confirm(`Excluir o objetivo “${o.nome}”?`)) return;
    try {
      await api("/api/gestao/objetivo/excluir", { json: { id: o.id } });
      toast("Objetivo excluído");
      formObj = null;
      dlg.close();
      await carregar(true);
    } catch (err) {
      erro(err.message);
    }
  });
  if (!dlg.open) dlg.showModal();
  f.querySelector('[name="nome"]').focus();
  const cat = await carregarCatalogo();
  if (!formObj || dlg.querySelector("form") !== f) return;
  if (!cat) return erro(`não foi possível carregar produtos e clientes: ${estado.erroCatalogo}`);
  const unidade = () => {
    const pr = formObj.construtor.preset();
    f.querySelector("#go-meta-bloco").hidden = pr.metrica === "preco_medio";
    f.querySelector("#go-unidade").textContent = `(${formObj.construtor.unidadeAlvo() || "valor"} para a equipe)`;
  };
  formObj.construtor = construtorIndicador(f.querySelector("#go-indicador"), {
    catalogo: cat, inicial: d, objetivo: true, filtrosEm: f.querySelector("#go-filtros"), precosEm: f.querySelector("#go-precos"),
    aoMudar: unidade,
  });
  unidade();
  formObj.orig = JSON.stringify(coletarObjetivo());
}

// ---------- eventos ----------
function trocarRegiao(r) {
  if (r === estado.regiao) return;
  if (!podeSairDoForm()) return;
  if (raiz.querySelector("#g-nota")?.value.trim() && !confirm("Descartar a observação que você escreveu?")) return;
  estado.regiao = r;
  estado.vista = "grade";
  estado.historico = estado.detalhe = null;
  raiz.querySelector("#g-corpo").innerHTML = `<div class="esqueleto" style="height:320px"></div>`;
  atualizarUrl();
  carregar();
}

function aoClicar(e) {
  const t = e.target.closest("[data-regiao],[data-nova],[data-objetivo],[data-acao-para],[data-acao],[data-vendedor],[data-voltar]," +
    "[data-encerrar],[data-prorrogar],[data-editar-acao],[data-arquivar-acao],[data-excluir-acao],[data-excluir-nota]," +
    "[data-enviar-nota],[data-cancelar-form],[data-lancar]");
  if (!t) return;
  const ds = t.dataset;
  if (ds.regiao) return trocarRegiao(ds.regiao);
  if ("nova" in ds) return entrarSelecao([]);
  if (ds.objetivo) return abrirObjetivo(ds.objetivo);
  if (ds.acaoPara) return acaoPara(Number(ds.acaoPara));
  if (ds.acao) return abrirAcao(Number(ds.acao));
  if (ds.vendedor) return abrirVendedor(Number(ds.vendedor));
  if ("voltar" in ds) return voltarGrade();
  if (ds.encerrar) return encerrar(Number(ds.encerrar));
  if (ds.prorrogar) return prorrogar(Number(ds.prorrogar));
  if (ds.editarAcao) return editarAcao(Number(ds.editarAcao));
  if (ds.arquivarAcao) return arquivar(Number(ds.arquivarAcao), ds.arquivada === "1");
  if (ds.excluirAcao) return excluirAcao(Number(ds.excluirAcao));
  if (ds.excluirNota) return excluirNota(Number(ds.excluirNota));
  if ("enviarNota" in ds) return enviarNota();
  if ("cancelarForm" in ds) return sairSelecao();
  if ("lancar" in ds) return lancar();
}

function aoMudarCampo(e) {
  const t = e.target;
  if (t.matches("select[data-abrir]")) {
    estado.abrir = t.value; // "" = não abrir
    return carregarVista();
  }
  if (!t.closest("#g-form")) return;
  const form = raiz.querySelector("#g-form");
  if (t.name === "prazo") {
    const data = t.value === "data";
    form.querySelector("#gf-fim-bloco").hidden = !data;
    if (data) {
      form.querySelector(".ge-mais").open = true;
      form.querySelector('[name="fim"]').focus();
    }
  }
  if (t.name === "inicio") desenharPrazos();
  if (t.name === "alvo_tipo") atualizarAlvo();
}

function aoDigitar(e) {
  if (e.target.name === "meta" && e.target.closest("#g-form")) atualizarAlvo();
}

function aoTeclar(e) {
  if (e.target.id === "g-nota" && e.key === "Enter" && !e.shiftKey) { // Enter grava; Shift+Enter pula linha
    e.preventDefault();
    enviarNota();
  } else if (e.key === "Enter" && e.target.matches("tr[data-vendedor]")) {
    abrirVendedor(Number(e.target.dataset.vendedor));
  }
}
