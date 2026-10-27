// Página Gestão ("Gestão da equipe"), separada por região (ES e BA; o Edir é da BA). No topo, os objetivos do
// período da região; abaixo, as campanhas (com o tempo que falta e o andamento contra a meta) e um quadrado por
// vendedor do acesso, com uma etiqueta por campanha em vigor, colorida pelo % da meta. Clicar no vendedor abre o
// histórico interno dele (as campanhas com a base e a meta dele, as observações, a parcial de cada semana e o
// resultado); clicar numa campanha abre o andamento dela por vendedor.
// Só o administrador lança campanhas (marcando vendedores no quadro: a mesma campanha para todos), cria objetivos,
// escreve observações, encerra e prorroga; quem tem a página acompanha os vendedores do acesso. A campanha nova já
// vem com todos os vendedores ativos marcados, na meta padrão. Enquanto o formulário está aberto, os quadrados
// mostram a base de cada um (no período da base escolhido) e, nos marcados, a meta ("padrão" ou "própria"), com a
// opção de uma meta própria (no preço médio, o preço-alvo do vendedor em cada produto). A conta é toda no servidor
// (bi/gestao.py), que manda o descritor do indicador: a página só formata. O rascunho que o Assistente monta chega
// por #/gestao?rascunho=<id> e abre o formulário já preenchido. No topo fica a agenda de quem está vendo (agenda.js):
// as atividades dela e as tarefas de que participa, com os próprios eventos: os daqui ignoram o que acontece dentro
// dela (#g-agenda); #/gestao?dia=<AAAA-MM-DD> abre a agenda nesse dia.
import { abrirNaAgenda, abrirTarefaNaAgenda, agendaTemAlteracoes, montarAgenda, recarregarAgenda } from "./agenda.js";
import { MESES, STATUS, animarEntradas, api, chipStatus, corStatus, esc, fmt, guardar, icone, ler, ligarTooltips, toast } from "./util.js";
import { ABERTURAS, BASE_ANTIGA, METAS, META_ANTIGA, PERIODOS_BASE, alvoDe, comoCalcula, corMeta, daBase, definirCatalogo, deltaTexto,
         duracaoTexto, iniciais, intensidadeMeta, janelaFechada, periodoTexto, presetDe, textoAlvo, textoBase, textoFiltros,
         textoPeriodoBase, textoProgresso, valorIndicador, valorParte, visual } from "./indicadores.js";
import { abrirComoCalcula, construtorIndicador } from "./construtorindicador.js";

const PRAZOS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 26]; // semanas
const CORES_AVATAR = ["var(--s-fat)", "var(--s-out)", "var(--k-cli)", "var(--k-vm)", "var(--s-mus)"];
const CLASSE = { ok: "Meta batida", mid: "Melhorou sobre a base", bad: "Abaixo da base", sem_alvo: "Sem meta para comparar", sem_dados: "Sem dados" };
const SITUACAO = { planejada: "Planejada", em_vigor: "Em vigor", encerrada: "Encerrada" };
const ROTULO_TAXA = { no_ritmo: "Na meta", abaixo: "Abaixo da meta" };
const DESCARTAR = "Descartar o que foi preenchido nesta campanha?";

let ctx = null, raiz = null, ligado = false;
const estado = {
  regiao: ler("mv-gestao-regiao", null), quadro: null, catalogo: null, erroCatalogo: null,
  vista: "grade", vendedor: null, historico: null, acao: null, detalhe: null, abrir: null, // o que o corpo mostra
  selecao: null, form: null, // lançando (ou editando) uma campanha: os vendedores marcados e o formulário em linha
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
// "em agosto/2026", "na semana de 12/10 a 18/10", "no trimestre jul a set/2026"; nas campanhas de antes (sem período),
// o tamanho da janela: "nas 3 semanas antes", "no dia antes".
function janelaTexto(periodo, inicio, fim) {
  if (periodo && periodo !== BASE_ANTIGA) {
    const t = textoPeriodoBase(periodo, inicio, fim);
    return { semana: `na semana de ${t}`, quinzena: `na quinzena de ${t}`, mes: `em ${t}`, ano: `em ${t}` }[periodo]
      || `no ${PERIODOS_BASE[periodo].toLowerCase()} ${t}`;
  }
  const t = duracaoTexto(inicio, fim);
  if (t === "1 semana") return "na semana antes";
  if (t === "1 dia") return "no dia antes";
  return `${t.endsWith("semanas") ? "nas" : "nos"} ${t} antes`;
}
// A janela das campanhas de antes: o mesmo número de dias, logo antes do início.
function janelaAntiga(inicio, fim) {
  const dias = Math.round((Date.parse(fim) - Date.parse(inicio)) / 864e5) + 1;
  return [somar(inicio, -dias), somar(inicio, -1)];
}
function rotuloClasse(classe, caminho) {
  if (classe === "mid" && caminho != null) return `${fmt.num(Math.max(0, Math.min(1, caminho)) * 100)}% do caminho até a meta`;
  return CLASSE[classe] || CLASSE.sem_dados;
}
const acaoDoQuadro = (id) => (estado.quadro?.acoes || []).find((a) => a.id === id);

// Preço médio: a meta é o preço-alvo de cada produto, e o % da meta é o aumento de preço feito ÷ o pedido, desde o
// preço de cada um na base (bi/indicadores.py progresso_preco). Os preços vêm por produto: {"<id>": {preco, quantidade}}.
const ePreco = (ind) => ind?.tipo === "preco_medio";
const precoDe = (precos, id) => precos?.[String(id)]?.preco ?? null;
// O preço-alvo de um vendedor num produto: o da meta própria dele ({"<id>": R$}) ou o da campanha.
const alvoDoVendedor = (alvos, p) => alvos?.[String(p.id)] ?? p.meta;
const reaisSinal = (v) => (v < 0 ? `−${fmt.moeda2(-v)}` : fmt.moeda2(v));
// O preço médio de vários vendedores juntos num produto (pela quantidade de cada um).
function precoJunto(listas, id) {
  let valor = 0, qtd = 0;
  for (const precos of listas) {
    const x = precos?.[String(id)];
    if (x?.preco != null && x.quantidade > 0) { valor += x.preco * x.quantidade; qtd += x.quantidade; }
  }
  return qtd ? valor / qtd : null;
}
// Um preço por produto: com um produto só, "R$ 19,14"; com vários, uma linha por produto (até 3).
function precosHtml(produtos, valorDe, vazio = "—") {
  const lista = produtos || [];
  const v = (p) => { const x = valorDe(p); return x == null ? `<span class="fraco">${vazio}</span>` : `<b>${fmt.moeda2(x)}</b>`; };
  if (lista.length === 1) return v(lista[0]);
  return `<span class="ge-vend-precos">${lista.slice(0, 3).map((p) => `<span><i title="${esc(p.nome)}">${esc(p.nome)}</i>${v(p)}</span>`).join("")}
    ${lista.length > 3 ? `<small>e mais ${lista.length - 3}</small>` : ""}</span>`;
}
// O mesmo em texto corrido: "R$ 19,14" ou "MANTEIGA 200G R$ 10,00 · QUEIJO MUSSARELA 4KG R$ 31,50".
function precosTexto(produtos, valorDe, vazio = "sem venda") {
  const lista = produtos || [];
  const v = (p) => { const x = valorDe(p); return x == null ? vazio : fmt.moeda2(x); };
  return lista.length === 1 ? v(lista[0]) : lista.map((p) => `${p.nome} ${v(p)}`).join(" · ");
}
// "R$ 30,00 (base R$ 10,00, alvo R$ 40,00)", produto a produto (alvos: a meta própria do vendedor).
function precosDica(produtos, base, agora, alvos) {
  const um = (p) => `${fmt.moeda2(precoDe(agora, p.id))} (base ${fmt.moeda2(precoDe(base, p.id))}, alvo ${fmt.moeda2(alvoDoVendedor(alvos, p))})`;
  return (produtos || []).length === 1 ? um(produtos[0]) : (produtos || []).map((p) => `${p.nome}: ${um(p)}`).join(" · ");
}

// ---------- montagem ----------
export function gestaoTemAlteracoes() {
  return !!((estado.form && formMudou()) || (dlg?.open && objetivoMudou()) || raiz?.querySelector("#g-nota")?.value.trim()
    || agendaTemAlteracoes());
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
        ${ctx.admin ? `<button class="btn primario" type="button" data-nova>${icone("mais")}Nova campanha</button>
          <a class="btn btn-config" href="#/config-gestao" title="Quem acompanha quais vendedores e os dias de atendimento das áreas">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="g-avisos"></div>
    <section class="ge-secao" id="g-agenda" aria-label="Minha agenda"></section>
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
  montarAgenda(raiz.querySelector("#g-agenda"), { dia: parametros().get("dia"), tarefa: parametros().get("tarefa") });
  if (parametros().get("tarefa")) atualizarUrl(); // a janela da tarefa já abriu: o link volta a ser o da página
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

// Ao voltar para a página o quadro é lido de novo (uma campanha lançada pelo Assistente aparece); um link de dentro do
// painel (#/gestao?a=12, ?rascunho=…) abre o que pede. Ao sair, a janela do objetivo fecha (se tinha alterações, o
// roteador já perguntou).
function aoMudarHash() {
  if (!naGestao()) {
    estado.naPagina = false;
    if (dlg?.open) dlg.close();
    return;
  }
  const q = parametros();
  if (!estado.naPagina) { estado.naPagina = true; carregar(true); recarregarAgenda(); }
  if (q.get("tarefa")) { // uma notificação do sino: abre a tarefa sem mudar o resto da página
    abrirTarefaNaAgenda(q.get("tarefa"));
    return atualizarUrl();
  }
  if (q.get("dia")) abrirNaAgenda(q.get("dia")); // o link de uma proposta do Assistente
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

// O histórico do vendedor ou o detalhe da campanha (o corpo da página, no lugar dos quadrados).
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
  el.innerHTML = `<div class="ge-secao-cab"><h3>${icone("bandeira")}Campanhas da região ${d.regiao}</h3><span class="ge-contagem">${fmt.num(vigor)} em vigor</span></div>
    ${acoes.length ? `<div class="ge-acoes">${acoes.map(cartaoAcao).join("")}</div>`
      : `<p class="ge-vazio">${icone("info")}<span>Nenhuma campanha lançada nesta região${ctx.admin ? ". Use Nova campanha para marcar os vendedores e lançar." : "."}</span></p>`}`;
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
  const noAlvo = enc && a.com_resultado ? `<span class="ge-no-alvo ${a.no_alvo ? "ok" : "zero"}">${a.no_alvo} de ${a.vendedores} na meta</span>` : "";
  const classe = enc ? "encerrada" : plan ? "planejada" : acaba ? "acaba" : "em-vigor";
  return `<button type="button" class="ge-acao ${classe} ${estado.vista === "acao" && estado.acao === a.id ? "atual" : ""} entra" style="--i:${i + 1}" data-acao="${a.id}">
    <span class="ge-acao-cab"><b>${esc(a.nome)}</b>${noAlvo}</span>
    <span class="ge-acao-info">${plural(a.vendedores, "vendedor", "vendedores")}, até ${fmt.dataCurta(a.fim)}</span>
    <span class="ge-tempo"><i data-largura="${largura}%"></i></span>
    <span class="ge-prazo">${esc(texto)}${extras ? `<small> · ${esc(extras)}</small>` : ""}</span>
    ${barraMeta(a)}
  </button>`;
}

// A segunda barra do cartão: o andamento da campanha contra a meta (a largura para em 100%; acima disso, o verde fica
// mais forte). Soma: a soma dos resultados ÷ a soma das metas; médias: a média do % de cada vendedor; preço médio: os
// aumentos feitos ÷ os pedidos, em R$.
function barraMeta(a) {
  if (a.situacao === "planejada") return `<span class="ge-meta"><i></i></span><span class="ge-meta-texto fraco">Meta: ainda não começou</span>`;
  const pct = a.meta_pct;
  if (pct == null) return `<span class="ge-meta"><i></i></span><span class="ge-meta-texto fraco">Meta: ${a.base_pendente ? "aguardando a base" : "sem números ainda"}</span>`;
  const conta = ePreco(a.indicador) ? "aumento de preço feito ÷ aumento pedido, somando os vendedores em R$"
    : a.indicador?.comportamento === "soma" ? "soma dos resultados ÷ soma das metas" : "média do % da meta de cada vendedor";
  const quem = a.com_meta < a.vendedores ? ` · ${a.com_meta} de ${a.vendedores} com meta` : "";
  return `<span class="ge-meta" style="--m:${corMeta(pct)};--i:${intensidadeMeta(pct)}" title="${esc(conta)}"><i data-largura="${Math.max(0, Math.min(1, pct)) * 100}%"></i></span>
    <span class="ge-meta-texto" style="--m:${corMeta(pct)}">${a.situacao === "encerrada" ? "Resultado: " : ""}${fmt.pct(pct, 0)} da meta<small>${esc(quem)}</small></span>`;
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
  const todos = estado.selecao && vend.length ? ` · <button type="button" class="ge-link" data-marcar-todos>${textoMarcarTodos()}</button>` : "";
  el.innerHTML = `<div class="ge-secao-cab"><h3>${icone("pessoas")}Equipe ${d.regiao}</h3><span>${plural(vend.length, "vendedor", "vendedores")}${estado.form ? " · a base de cada um no período escolhido" : ""}${todos}</span></div>
    ${vend.length ? `<div class="ge-grade ${estado.selecao ? "selecionando" : ""}">${vend.map(quadrado).join("")}</div>`
      : `<p class="ge-vazio">${icone("info")}<span>Nenhum vendedor da região no seu acesso.</span></p>`}`;
}

// O quadrado do vendedor. Com o formulário da campanha aberto: a base dele e, se marcado, a meta (com a meta própria);
// fora dele: as campanhas em vigor. O topo é o botão (marca/desmarca ou abre o histórico); o resto do quadrado também
// responde ao clique, menos os campos da meta própria (data-parar).
function quadrado(v) {
  const sel = estado.selecao, marcado = !!sel?.has(v.id);
  const corpo = estado.form ? baseDoQuadrado(v, marcado)
    : `<span class="ge-pills">${v.acoes.map(etiqueta).join("") || `<span class="ge-sem-acao">Sem campanha em vigor</span>`}</span>`;
  return `<div class="ge-vend ${marcado ? "marcado" : ""} ${estado.form ? "com-base" : ""}" data-vendedor="${v.id}">
    <button type="button" class="ge-vend-cab" data-vendedor="${v.id}" ${sel ? `role="checkbox" aria-checked="${marcado}"` : ""} aria-label="${esc(v.nome)}${sel ? "" : ": abrir o histórico"}">
      <span class="ge-avatar" style="--c:${corAvatar(v.id)}">${esc(iniciais(v.nome))}</span><b>${esc(v.nome)}</b>
      ${sel ? `<span class="ge-caixa">${marcado ? icone("visto") : ""}</span>` : ""}</button>
    ${v.inativo ? `<span class="ge-vend-fat">inativo no ERP</span>` : ""}
    ${corpo}</div>`;
}

function redesenharQuadrado(id) {
  const v = (estado.quadro?.vendedores || []).find((x) => x.id === id), card = raiz.querySelector(`.ge-vend[data-vendedor="${id}"]`);
  if (!v || !card) return;
  const foco = document.activeElement?.closest?.(".ge-vend") === card;
  card.outerHTML = quadrado(v);
  if (foco) raiz.querySelector(`.ge-vend[data-vendedor="${id}"] .ge-vend-cab`)?.focus();
}

// A base de um vendedor na prévia: o valor do indicador ou, no preço médio, o preço de cada produto.
function baseDaPrevia(p, id) {
  if (!p || p.pendente) return null;
  return (ePreco(p.indicador) ? p.precos?.[String(id)] : p.vendedores[String(id)]) ?? null;
}

// A base do vendedor no período escolhido (da prévia do servidor) e, nos marcados, a meta dele. No preço médio, o
// preço de cada produto na base.
function baseDoQuadrado(v, marcado) {
  const f = estado.form, p = f.previa, ind = p?.indicador;
  const base = baseDaPrevia(p, v.id);
  let linha;
  if (f.erroPrevia) linha = `<span class="fraco">Base: —</span>`;
  else if (!p) linha = `<span class="fraco">Base: calculando…</span>`;
  else if (p.pendente) linha = `<span class="fraco">Base: aguardando os dados</span>`;
  else if (ePreco(ind) && p.produtos) linha = `Base: ${precosHtml(p.produtos, (x) => precoDe(base, x.id), "sem venda")}`;
  else {
    linha = `Base: <b>${base == null ? "sem dados" : esc(valorIndicador(ind, base, p.unidade, true))}</b>`;
    // positivação em clientes: a % da base ao lado do número
    const da = ind?.cobertura && ind.meta_em !== "pct_base" ? daBase(p.coberturas?.[String(v.id)]) : null;
    if (da) linha += ` <small title="${esc(da.dica)}">(${esc(da.texto === "—" ? "sem a % da base" : `${da.texto} da base`)})</small>`;
  }
  return `<span class="ge-vend-base">${linha}</span>${marcado ? `<span class="ge-vend-meta" data-meta-de="${v.id}">${metaDoQuadrado(v, base)}</span>` : ""}`;
}

// Ao lado da meta do marcado: "padrão" (a da campanha) ou "própria".
const marcaMeta = (propria) => `<span class="ge-tag${propria ? " propria" : ""}">${propria ? "própria" : "padrão"}</span>`;

function nomeProduto(id) {
  return estado.catalogo?.produtos.find((x) => x.id === id)?.nome || estado.form?.nomes?.produtos?.[id] || `produto ${id}`;
}

// A meta própria de um vendedor no preço médio, só nos produtos da campanha: {"<id>": R$} ou null.
function alvosProprios(vid, produtos) {
  const p = estado.form?.alvos.get(vid) || {}, saida = {};
  for (const { id } of produtos) if (p[id] > 0) saida[id] = p[id];
  return Object.keys(saida).length ? saida : null;
}

// Preço médio no quadrado marcado: a meta é o preço-alvo de cada produto (o da campanha ou, na meta própria, o do
// vendedor); com um produto só, quanto o preço precisa subir desde a base. A meta própria abre um campo por produto.
function metaPreco(v, base) {
  const f = estado.form, alvos = f.construtor?.valor().metas_produto || [];
  const proprios = alvosProprios(v.id, alvos);
  let valor = "<b>o preço-alvo de cada produto</b>";
  if (alvos.length === 1) {
    const alvo = alvoDoVendedor(proprios, alvos[0]), b = precoDe(base, alvos[0].id);
    valor = !(alvo > 0) ? "<b>—</b>" : `<b>${fmt.moeda2(alvo)}</b>${b == null ? "" : b < alvo ? ` <small>(+${fmt.moeda2(alvo - b)})</small>` : " <small>(já no alvo)</small>"}`;
  }
  const linha = `<span class="ge-vend-alvo">Meta: ${valor}${alvos.length ? marcaMeta(!!proprios) : ""}</span>`;
  if (!alvos.length) return linha;
  if (!proprios && !f.abertas.has(v.id)) return `${linha}<button type="button" class="ge-link" data-meta-propria="${v.id}">Meta própria</button>`;
  const digitado = f.alvos.get(v.id) || {};
  const campo = (p) => `<input type="number" min="0" step="0.01" inputmode="decimal" data-preco-v="${v.id}" data-preco-p="${p.id}"
    value="${digitado[p.id] ?? ""}" placeholder="${p.meta > 0 ? esc(fmt.num(p.meta, 2)) : "R$"}"
    aria-label="Preço-alvo próprio de ${esc(v.nome)}${alvos.length > 1 ? ` em ${esc(nomeProduto(p.id))}` : ""}">`;
  const tirar = `<button type="button" class="ge-x" data-tirar-meta="${v.id}" title="Voltar à meta padrão" aria-label="Voltar à meta padrão">${icone("x")}</button>`;
  if (alvos.length === 1) return `${linha}<span class="ge-meta-propria" data-parar><small>R$</small>${campo(alvos[0])}${tirar}</span>`;
  return `${linha}<span class="ge-meta-precos" data-parar>${alvos.map((p) => `<label><i title="${esc(nomeProduto(p.id))}">${esc(nomeProduto(p.id))}</i>${campo(p)}</label>`).join("")}
    <span class="ge-meta-precos-rodape"><small>em branco = o da campanha</small>${tirar}</span></span>`;
}

function metaDoQuadrado(v, base) {
  const f = estado.form, p = f.previa, form = raiz.querySelector("#g-form");
  // o descritor do servidor (da prévia) enquanto ele for do indicador escolhido; trocado o tipo, o do construtor
  const d = f.construtor?.descritor(), q = p?.indicador;
  const ind = q && (!d || ["tipo", "medida", "forma", "meta_em"].every((k) => (q[k] ?? null) === (d[k] ?? null))) ? q : d;
  if (!ind) return "";
  if (ePreco(ind)) return metaPreco(v, base);
  const tipo = form?.querySelector('[name="alvo_tipo"]')?.value || f.dados.alvo_tipo;
  const padrao = form?.querySelector('[name="meta"]')?.value ?? "";
  const propria = f.metas.get(v.id);
  const meta = propria ?? (padrao === "" ? null : Number(padrao));
  const alvo = p && !p.pendente ? alvoDe(ind, tipo, base, meta) : tipo === "fixo" ? alvoDe(ind, tipo, null, meta) : null;
  const texto = alvo != null ? esc(valorIndicador(ind, alvo, p?.unidade || ind.unidade, true))
    : meta == null ? "—" : tipo === "pct" && p && !p.pendente ? "sem base" : "—";
  const sufixo = tipo === "pct" && meta != null ? ` <small>(+${esc(fmt.num(meta, 1))}%)</small>` : "";
  const aberta = propria != null || f.abertas.has(v.id);
  const unidade = tipo === "fixo" ? (ind.meta_em_pct ? "%" : "") : "%";
  const controle = aberta
    ? `<span class="ge-meta-propria" data-parar><input type="number" min="0" step="any" inputmode="decimal" data-meta-v="${v.id}" value="${propria ?? ""}"
        placeholder="${esc(padrao || "meta")}" aria-label="Meta própria de ${esc(v.nome)}">${unidade ? `<small>${unidade}</small>` : ""}
        <button type="button" class="ge-x" data-tirar-meta="${v.id}" title="Voltar à meta padrão" aria-label="Voltar à meta padrão">${icone("x")}</button></span>`
    : `<button type="button" class="ge-link" data-meta-propria="${v.id}">Meta própria</button>`;
  return `<span class="ge-vend-alvo">Meta: <b>${texto}</b>${sufixo}${marcaMeta(propria != null)}</span>${controle}`;
}

// Só o texto da meta dos marcados (a meta padrão ou o tipo mudou): os campos abertos ficam como estão.
function atualizarMetasQuadrados() {
  const f = estado.form;
  if (!f) return;
  raiz.querySelectorAll(".ge-vend-meta[data-meta-de]").forEach((el) => {
    const id = Number(el.dataset.metaDe), v = (estado.quadro?.vendedores || []).find((x) => x.id === id);
    const alvo = el.querySelector(".ge-vend-alvo");
    if (!v || !alvo) return;
    const tmp = document.createElement("span");
    tmp.innerHTML = metaDoQuadrado(v, baseDaPrevia(f.previa, id));
    alvo.replaceWith(tmp.querySelector(".ge-vend-alvo"));
  });
}

// Fora do formulário: uma etiqueta por campanha em vigor, com o % da meta até agora.
function etiqueta(e) {
  const pop = estado.recem === e.id ? " pop" : "";
  const a = acaoDoQuadro(e.id);
  if (e.pct == null || !a) {
    const porque = e.base_pendente ? "aguardando a base" : "sem meta ou sem números ainda";
    return `<span class="ge-pill${pop}" title="${esc(`${porque} · até ${fmt.dataCurta(e.fim)}`)}">${icone("bandeira")}${esc(e.rotulo)}</span>`;
  }
  const conta = ePreco(a.indicador) && a.produtos ? precosDica(a.produtos, e.base_precos, e.precos, e.alvos)
    : `${valorIndicador(a.indicador, e.resultado, a.unidade, true)} de ${valorIndicador(a.indicador, e.alvo, a.unidade, true)}`;
  const titulo = `${fmt.pct(e.pct, 0)} da meta (${conta}) · até ${fmt.dataCurta(e.fim)}`;
  return `<span class="ge-pill meta${pop}" style="--c:${corMeta(e.pct)};--i:${intensidadeMeta(e.pct)}" title="${esc(titulo)}">${esc(e.rotulo)} · ${fmt.pct(e.pct, 0)}</span>`;
}

// ---------- campanha em lote: marcar os vendedores e lançar ----------
function padraoAcao() {
  return { nome: "", rotulo: "", descricao: "", inicio: estado.quadro?.hoje || hojeLocal(), fim: null, semanas: 3,
           base_periodo: "mes", metrica: "mix_medio", parametros: {}, filtros: {}, alvo_tipo: "fixo", meta_padrao: "",
           metas_produto: [] };
}

function formMudou() {
  const f = estado.form;
  return !!(f && f.orig && JSON.stringify(coletarForm()) !== f.orig);
}

// Antes de trocar o que o corpo mostra: confirma se há uma campanha preenchida e sai do modo de seleção.
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
  const d = { ...padraoAcao(), ...(dados || {}) };
  const antiga = !!extra.id && d.base_periodo == null; // campanha de antes da 012: pode manter a base "logo antes"
  if (d.base_periodo == null) d.base_periodo = antiga ? BASE_ANTIGA : "mes";
  estado.form = { id: extra.id || null, rascunho: extra.rascunho || null, nomes: extra.nomes || {}, construtor: null, orig: null,
                  todos: !!extra.todos, // a campanha nova, com todos os vendedores ativos já marcados
                  dados: d, antiga, metas: new Map((dados?.vendedores || []).map((v) => [v.id, v.meta ?? null])),
                  // preço médio: a meta própria é o preço-alvo do vendedor em cada produto ({"<id>": R$})
                  alvos: new Map((dados?.vendedores || []).filter((v) => v.alvos_precos).map((v) => [v.id, { ...v.alvos_precos }])),
                  abertas: new Set(), previa: null, erroPrevia: null, carregandoPrevia: false, pedidoPrevia: 0,
                  chavePrevia: null, timerPrevia: null, chaveQuadros: null };
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
  clearTimeout(estado.form?.timerPrevia);
  estado.form = estado.selecao = null;
  const el = raiz.querySelector("#g-form");
  if (el) el.innerHTML = "";
  desenharGrade();
}

function alternar(id) {
  const s = estado.selecao;
  if (s.has(id)) s.delete(id); else s.add(id);
  redesenharQuadrado(id);
  contarSelecao();
  desenharMedia();
}

function contarSelecao() {
  const n = estado.selecao?.size || 0, f = estado.form;
  const t = raiz.querySelector("#gf-titulo"), b = raiz.querySelector("[data-lancar] span");
  if (t) t.textContent = f?.id ? `Editar campanha · ${plural(n, "vendedor", "vendedores")}` : `Nova campanha para ${plural(n, "vendedor", "vendedores")}`;
  if (b) b.textContent = f?.id ? "Salvar alterações" : `Lançar para ${n}`;
  const todos = raiz.querySelector("[data-marcar-todos]");
  if (todos) todos.textContent = textoMarcarTodos();
  if (n) erroForm("");
}

// Os vendedores que a campanha nova já traz marcados (e o "Marcar todos"): os do quadro, menos os inativos no ERP.
const ativosDoQuadro = () => (estado.quadro?.vendedores || []).filter((v) => !v.inativo).map((v) => v.id);
function textoMarcarTodos() {
  const s = estado.selecao, ativos = ativosDoQuadro();
  return s?.size && ativos.every((id) => s.has(id)) ? "Desmarcar todos" : "Marcar todos";
}

function marcarTodos() {
  const s = estado.selecao;
  if (!s) return;
  if (textoMarcarTodos() === "Desmarcar todos") s.clear();
  else ativosDoQuadro().forEach((id) => s.add(id));
  desenharGrade();
  contarSelecao();
  desenharMedia();
}

async function montarForm() {
  const alvo = raiz.querySelector("#g-form"), f = estado.form;
  if (!alvo || !f) return;
  const d = f.dados;
  f.semanas = d.fim ? semanasDe(d.inicio, d.fim) : d.semanas;
  alvo.innerHTML = `<section class="cartao ge-form entra" style="--i:0">
    <div class="ge-form-cab"><div><b id="gf-titulo"></b>
        <span class="fraco">${f.rascunho ? "Rascunho do Assistente: confira e lance. " : ""}${f.todos ? "Todos os vendedores ativos já vêm marcados, na meta padrão: desmarque no quadro abaixo quem fica de fora ou dê uma meta própria."
          : "Marque os vendedores no quadro abaixo."}</span></div>
      <span class="ge-pill">região ${esc(estado.quadro.regiao)}</span></div>
    <div class="ge-campos">
      <label class="campo-form"><span>Campanha</span><input name="nome" maxlength="120" value="${esc(d.nome)}" placeholder="Ex.: Aumentar mix médio" autocomplete="off"></label>
      <div class="ge-indicador" id="gf-indicador"><div class="esqueleto" style="height:66px"></div></div>
      <label class="campo-form"><span>Prazo</span><span class="campo"><select name="prazo" style="padding-left:14px"></select></span></label>
      <label class="campo-form"><span>Base <small>(período fechado antes do início)</small></span><span class="campo"><select name="base_periodo" style="padding-left:14px"></select></span></label>
      <div class="campo-form ge-alvo"><span>Meta <small id="gf-unidade"></small></span>
        <span class="ge-alvo-linha"><span class="campo"><select name="alvo_tipo" aria-label="Tipo de meta" style="padding-left:14px">${Object.entries({ ...METAS, ...(d.alvo_tipo === "mais" ? META_ANTIGA : {}) })
          .map(([k, n]) => `<option value="${k}" ${k === (d.alvo_tipo || "fixo") ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></span>
          <input name="meta" type="number" min="0" step="any" inputmode="decimal" value="${d.meta_padrao ?? ""}" placeholder="quanto" aria-label="Valor da meta"></span>
        <small class="ge-previa" id="gf-previa"></small></div>
    </div>
    <p class="ge-base-media" id="gf-base" aria-live="polite"></p>
    <div id="gf-precos"></div>
    <details class="ge-mais"><summary>${icone("ajustes")}Mais opções: início, etiqueta, descrição, produtos e clientes que contam</summary>
      <div class="ge-campos">
        <label class="campo-form"><span>Início</span><input type="date" name="inicio" value="${esc(d.inicio)}"></label>
        <label class="campo-form" id="gf-fim-bloco" ${f.semanas ? "hidden" : ""}><span>Fim</span><input type="date" name="fim" value="${esc(d.fim || somar(d.inicio, 20))}"></label>
        <label class="campo-form"><span>Etiqueta no quadro <small>(até 20 letras)</small></span><input name="rotulo" maxlength="20" value="${esc(d.rotulo || "")}" autocomplete="off"></label>
        <label class="campo-form ge-largo"><span>Descrição <small>(opcional)</small></span><textarea name="descricao" rows="2" maxlength="2000" placeholder="Objetivo e combinados da campanha">${esc(d.descricao || "")}</textarea></label>
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
  desenharBases(d.base_periodo);
  contarSelecao();
  desenharMedia();
  animarEntradas(alvo);
  const cat = await carregarCatalogo();
  if (estado.form !== f) return; // cancelou ou abriu outra enquanto o catálogo vinha
  if (!cat) {
    alvo.querySelector("#gf-indicador").innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Não foi possível carregar produtos e clientes: ${esc(estado.erroCatalogo)}</span></p>`;
    f.erroPrevia = "sem o catálogo de produtos e clientes";
    desenharMedia();
    desenharGrade();
    return;
  }
  desenharBases(); // agora com o começo do histórico (os períodos antes dele ficam bloqueados)
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

// Os períodos da base, com as datas de cada um a partir do início escolhido. Os que começam antes do histórico do
// cache ficam bloqueados; a campanha de antes da 012 ganha a opção de manter a regra dela.
function desenharBases(valor) {
  const f = estado.form, form = raiz.querySelector("#g-form"), el = form?.querySelector('[name="base_periodo"]');
  if (!f || !el) return;
  const atual = valor || el.value || f.dados.base_periodo;
  const inicio = form.querySelector('[name="inicio"]').value || estado.quadro.hoje;
  const desde = estado.catalogo?.inicio_dados;
  const opcoes = Object.entries(PERIODOS_BASE).map(([k, n]) => {
    const [de, ate] = janelaFechada(inicio, k);
    const antes = !!desde && de < desde;
    return `<option value="${k}" ${antes ? "disabled" : ""}>${n} · ${esc(textoPeriodoBase(k, de, ate))}${antes ? " (antes do histórico)" : ""}</option>`;
  });
  if (f.antiga) {
    const [de, ate] = janelaAntiga(inicio, fimDoForm());
    opcoes.push(`<option value="${BASE_ANTIGA}">Mesmo tamanho, logo antes (antigo) · ${fmt.dataCurta(de)} a ${fmt.dataCurta(ate)}</option>`);
  }
  el.innerHTML = opcoes.join("");
  el.value = atual;
  if (!el.value || el.selectedOptions[0]?.disabled) el.value = [...el.options].find((o) => !o.disabled)?.value || "";
}

function fimDoForm() {
  const form = raiz.querySelector("#g-form"), val = (n) => form.querySelector(`[name="${n}"]`).value;
  const inicio = val("inicio") || estado.quadro.hoje;
  return val("prazo") === "data" ? (val("fim") || inicio) : somar(inicio, 7 * Number(val("prazo")) - 1);
}

function atualizarAlvo() {
  const f = estado.form, form = raiz.querySelector("#g-form");
  if (!f?.construtor || !form) return;
  const pr = f.construtor.preset(), desc = f.construtor.descritor();
  const preco = pr.metrica === "preco_medio";
  const tipo = form.querySelector('[name="alvo_tipo"]').value;
  const unidade = f.construtor.unidadeAlvo() || "valor";
  form.querySelector(".ge-alvo-linha").hidden = preco;
  form.querySelector("#gf-unidade").textContent = preco ? "" : tipo === "pct" ? "(% sobre a base de cada um)"
    : tipo === "mais" ? `(${unidade} a mais sobre a base${pr.pct ? ", em pontos" : ""})` : `(${unidade} a atingir)`;
  const campo = form.querySelector('[name="meta"]');
  campo.step = tipo === "fixo" && ["clientes", "produtos"].includes(pr.formato) ? "1" : "any";
  const meta = campo.value;
  form.querySelector("#gf-previa").textContent = preco
    ? "O % da meta de cada um é o aumento de preço feito sobre a base ÷ o aumento até o preço-alvo (base R$ 10, alvo R$ 20 e agora R$ 15 = 50%)."
    : meta !== "" ? `${capitalizar(textoAlvo(desc, tipo, Number(meta), desc.unidade))}.` : "";
  form.querySelector('[name="rotulo"]').placeholder = pr.rotulo;
  // outro tipo ou outros produtos no preço médio: a meta dos quadrados muda de forma (os campos da meta própria)
  const chave = JSON.stringify([pr.id, preco ? f.construtor.valor().metas_produto.map((x) => x.id) : []]);
  if (f.chaveQuadros != null && chave !== f.chaveQuadros) {
    f.previa = f.erroPrevia = null; // a base de antes era de outro indicador: "calculando…" até a nova chegar
    if (JSON.parse(f.chaveQuadros)[0] !== pr.id) f.abertas.clear(); // outro tipo: fecha os campos vazios da meta própria
    desenharGrade();
  } else {
    atualizarMetasQuadrados();
  }
  f.chaveQuadros = chave;
  agendarPrevia();
}

// ---------- prévia da base (o servidor mede; nada é gravado) ----------
// No preço médio vão só os produtos: a base é o preço de cada um, que não depende do preço-alvo.
function corpoPrevia() {
  const f = estado.form, d = coletarForm();
  return { campanha: { id: f.id, regiao: d.regiao, inicio: d.inicio, semanas: d.semanas, fim: d.fim, base_periodo: d.base_periodo,
                       metrica: d.metrica, parametros: d.parametros, filtros: d.filtros,
                       metas_produto: d.metas_produto.map((p) => ({ id: p.id })) },
           ids: (estado.quadro?.vendedores || []).map((v) => v.id) };
}

// Pede a base de novo quando o que a muda mudou (o indicador, os filtros, os produtos, a base, o início ou o prazo).
function agendarPrevia() {
  const f = estado.form;
  if (!f?.construtor) return;
  const corpo = corpoPrevia(), chave = JSON.stringify(corpo);
  if (chave === f.chavePrevia) return;
  f.chavePrevia = chave;
  clearTimeout(f.timerPrevia);
  const { metrica, metas_produto: precos } = corpo.campanha;
  if (metrica === "preco_medio" && !precos.length) {
    f.previa = null;
    f.erroPrevia = "escolha os produtos para ver o preço de cada vendedor na base";
    desenharMedia();
    desenharGrade();
    return;
  }
  f.carregandoPrevia = true;
  desenharMedia();
  f.timerPrevia = setTimeout(() => buscarPrevia(f, corpo), 400);
}

async function buscarPrevia(f, corpo) {
  const n = ++f.pedidoPrevia;
  try {
    const p = await api("/api/gestao/base", { json: corpo });
    if (estado.form !== f || n !== f.pedidoPrevia) return;
    f.previa = p;
    f.erroPrevia = null;
  } catch (e) {
    if (estado.form !== f || n !== f.pedidoPrevia) return;
    f.previa = null;
    f.erroPrevia = e.message;
  }
  f.carregandoPrevia = false;
  desenharMedia();
  desenharGrade();
}

// "Média da equipe na base (agosto/2026): 4,1 produtos por cliente · dos 3 marcados: 4,4".
function desenharMedia() {
  const f = estado.form, el = raiz.querySelector("#gf-base");
  if (!f || !el) return;
  const p = f.previa;
  el.classList.toggle("carregando", !!f.carregandoPrevia);
  if (f.erroPrevia) { el.innerHTML = `${icone("info")}<span>Base: ${esc(f.erroPrevia)}</span>`; return; }
  if (!p) { el.innerHTML = `${icone("grafico")}<span>Calculando a base de cada vendedor…</span>`; return; }
  const periodo = textoPeriodoBase(p.base_periodo, p.base_inicio, p.base_fim);
  if (p.pendente) {
    el.innerHTML = `${icone("calendario")}<span>Base ${esc(periodo)}: os dados vão até ${fmt.dataCurta(p.data_ref)}; a base de cada um é medida quando o período fechar.</span>`;
    return;
  }
  if (p.aviso) { el.innerHTML = `${icone("alerta")}<span>${esc(capitalizar(p.aviso))}</span>`; return; }
  if (ePreco(p.indicador) && p.produtos) { // o preço de cada produto, pela quantidade de cada vendedor
    const todos = Object.values(p.precos || {});
    const marcados = [...(estado.selecao || [])].map((id) => p.precos?.[String(id)]).filter(Boolean);
    const juntos = (listas) => esc(precosTexto(p.produtos, (x) => precoJunto(listas, x.id)));
    const dos = marcados.length && marcados.length < todos.length
      ? ` · dos ${plural(marcados.length, "marcado", "marcados")}: <b>${juntos(marcados)}</b>` : "";
    el.innerHTML = `${icone("grafico")}<span>Preço médio da equipe na base (${esc(periodo)}): <b>${juntos(todos)}</b>${dos}</span>`;
    return;
  }
  const valor = (x) => esc(valorIndicador(p.indicador, x, p.unidade));
  const marcados = [...(estado.selecao || [])].map((id) => p.vendedores[String(id)]).filter((x) => x != null);
  const media = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
  const dos = marcados.length && marcados.length < Object.keys(p.vendedores).length
    ? ` · dos ${plural(marcados.length, "marcado", "marcados")}: <b>${valor(media(marcados))}</b>` : "";
  el.innerHTML = `${icone("grafico")}<span>Média da equipe na base (${esc(periodo)}): <b>${p.media == null ? "sem dados" : valor(p.media)}</b>${dos}</span>`;
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
    inicio: val("inicio"), ...(prazo === "data" ? { fim: val("fim") } : { semanas: Number(prazo) }),
    base_periodo: val("base_periodo") || f.dados.base_periodo, ...ind,
    alvo_tipo: preco ? "fixo" : val("alvo_tipo"), meta_padrao: preco ? 100 : (val("meta") === "" ? null : Number(val("meta"))),
    vendedores: [...(estado.selecao || [])].map((id) => (preco ? { id, meta: null, alvos_precos: alvosProprios(id, ind.metas_produto) }
      : { id, meta: f.metas.get(id) ?? null })),
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
  if (!dados.nome) return erroForm("dê um nome à campanha");
  if (dados.metrica === "preco_medio") {
    if (!dados.metas_produto.length) return erroForm("escolha os produtos do preço médio");
    if (dados.metas_produto.some((p) => !(p.meta > 0))) return erroForm("dê o preço-alvo de cada produto (R$ por unidade)");
  } else if (!(dados.meta_padrao > 0)) {
    return erroForm("dê a meta");
  }
  const btn = raiz.querySelector("[data-lancar]");
  btn.disabled = true;
  erroForm("");
  try {
    const r = f.id
      ? await api("/api/gestao/acao/editar", { json: { id: f.id, acao: dados } })
      : await api("/api/gestao/acoes", { json: { acao: dados, rascunho: f.rascunho } });
    const id = f.id || r.id;
    toast(f.id ? "Campanha salva" : r.ja_existia ? "Este rascunho já tinha virado campanha" : `Campanha lançada para ${plural(dados.vendedores.length, "vendedor", "vendedores")}`);
    clearTimeout(f.timerPrevia);
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
  if (!h.eventos.length) corpo = `<p class="ge-hist-vazio">${h.pode_editar ? "Nenhum registro ainda. Lance uma campanha ou escreva uma observação." : "Nenhum registro ainda."}</p>`;
  el.innerHTML = `<section class="cartao ge-hist entra" style="--i:0">
    <header class="ge-hist-cab">
      <button class="btn icone" type="button" data-voltar title="Voltar ao quadro" aria-label="Voltar ao quadro">${icone("voltar")}</button>
      <span class="ge-avatar grande" style="--c:${corAvatar(v.id)}">${esc(iniciais(v.nome))}</span>
      <div class="ge-hist-quem"><b>${esc(v.nome)}</b>
        <small>${esc(v.regiao || v.equipe || "")}, ${plural(h.em_vigor, "campanha em vigor", "campanhas em vigor")}${v.inativo ? " · inativo no ERP" : ""}</small></div>
      <span class="ge-cadeado" title="O vendedor não vê este histórico">${icone("cadeado")}Só controle interno</span>
    </header>
    <div class="ge-hist-corpo">${corpo}</div>
    ${h.pode_editar ? `<div class="ge-hist-rodape">
      <textarea id="g-nota" rows="1" maxlength="2000" placeholder="Escreva uma observação sobre ${esc(primeiroNome(v.nome))}" aria-label="Observação sobre ${esc(v.nome)}"></textarea>
      <button class="btn primario icone" type="button" data-enviar-nota title="Gravar a observação" aria-label="Gravar a observação">${icone("enviar")}</button>
      <button class="btn" type="button" data-acao-para="${v.id}" title="Lançar uma campanha só para ${esc(v.nome)}">${icone("bandeira")}Campanha</button>
    </div>` : ""}
  </section>`;
  animarEntradas(el);
}

function evento(e, h) {
  const a = h.acoes[String(e.acao)] || null;
  const ind = a?.indicador || { formato: "razao", casas: 2 };
  const u = a?.unidade || "";
  const d = e.dados || {};
  // no preço médio (eventos depois da 013, com os preços), a base e a meta em R$ por produto; o resto, como sempre
  const preco = ePreco(ind) && a?.produtos && d.base_precos !== undefined;
  const val = (x) => esc(valorIndicador(ind, x, u));
  const valBase = (x) => (preco ? esc(precosTexto(a.produtos, (p) => precoDe(d.base_precos, p.id))) : val(x));
  const valAlvo = (x) => (preco ? esc(precosTexto(a.produtos, (p) => d.alvos?.[String(p.id)] ?? p.meta)) : val(x));
  const nome = esc(d.nome || a?.nome || "");
  switch (e.tipo) {
    case "nota":
      return `<div class="ge-bolha dir"><p>${icone("lapis")}<span>${esc(e.texto)}</span></p>
        <small>${esc(e.autor)} · ${hora(e.criada_em)}${h.pode_editar ? `<button type="button" class="ge-x" data-excluir-nota="${e.id}" title="Apagar a observação" aria-label="Apagar a observação">${icone("x")}</button>` : ""}</small></div>`;
    case "lancada": {
      const janela = janelaTexto(d.base_periodo, d.base_inicio, d.base_fim);
      const base = d.base_pendente ? `Base: aguardando os dados de ${fmt.dataCurta(d.base_inicio)} a ${fmt.dataCurta(d.base_fim)}`
        : d.base == null ? `Base: sem dados ${janela}` : `Base: ${valBase(d.base)} ${janela}`;
      const alvo = d.alvo == null ? (d.base_pendente ? "Meta: sai da base, quando ela chegar" : "Meta: sem base para calcular")
        : `Meta: ${valAlvo(d.alvo)} até ${fmt.dataCurta(d.fim)}`;
      return `<div class="ge-bolha esq"><b>${icone("bandeira")}Campanha lançada: ${nome}</b>
        <p>${base}<br>${alvo}${d.vendedores > 1 ? `<br>Mesma campanha para ${d.vendedores} vendedores` : ""}</p>
        <small>${esc(e.autor)}${a ? ` · <button type="button" class="ge-link" data-acao="${e.acao}">ver a campanha</button>` : ""}</small></div>`;
    }
    case "parcial":
      return `<p class="ge-linha">${icone("grafico")}Parcial da semana ${d.semana}${a ? ` de ${esc(a.rotulo)}` : ""}: <b>${val(d.valor)}${ePreco(ind) ? " da meta" : ""}</b></p>`;
    case "resultado":
      return cartaoResultado(e, a, ind, u, h);
    case "prorrogada": {
      const resto = d.base_pendente ? "; a base aguarda os dados"
        : d.base_periodo ? `; a base continua a mesma, meta ${valAlvo(d.alvo)}`
        : `; base refeita ${janelaTexto(null, d.base_inicio, d.base_fim)}: ${valBase(d.base)}, meta ${valAlvo(d.alvo)}`;
      return `<p class="ge-linha sistema">${icone("calendario")}${nome} prorrogada até ${fmt.dataCurta(d.fim)}${resto} · ${esc(e.autor)}</p>`;
    }
    case "encerrada":
      return `<p class="ge-linha sistema">${icone("certo")}${nome} encerrada em ${fmt.dataCurta(d.fim)}${d.fim_antes && d.fim_antes !== d.fim ? ` (ia até ${fmt.dataCurta(d.fim_antes)})` : ""} · ${esc(e.autor)}</p>`;
    case "editada": {
      const mudou = (d.mudou || []).map((x) => (x === "alvo" ? "meta" : x)).join(", ");
      return `<p class="ge-linha sistema">${icone("lapis")}${nome} alterada (${esc(mudou)})${d.alvo != null ? `: meta ${valAlvo(d.alvo)}` : d.base_pendente ? ": a base nova aguarda os dados" : ""} · ${esc(e.autor)}</p>`;
    }
    case "removido":
      return `<p class="ge-linha sistema">${icone("x")}Saiu da campanha ${nome} · ${esc(e.autor)}</p>`;
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
  const corpo = ePreco(ind) && a?.produtos && d.precos !== undefined ? resultadoPreco(d, a)
    : `${barra("Base", d.base, "var(--s-ritmo)")}${barra("Meta", d.alvo, "var(--linha-forte)")}${barra("Resultado", d.resultado, cor)}
    ${delta ? `<p class="ge-delta">${delta}</p>` : ""}`;
  const botoes = e.atual && h.pode_editar && a ? `<div class="ge-resultado-acoes">
      ${e.provisorio ? `<button class="btn" type="button" data-encerrar="${a.id}">${icone("certo")}Encerrar campanha</button>` : ""}
      <button class="btn" type="button" data-prorrogar="${a.id}">${icone("calendario")}Prorrogar 2 semanas</button></div>` : "";
  return `<div class="ge-resultado ${cls}">
    <div class="ge-resultado-cab"><b>${icone("ranking")}Resultado: ${esc(d.nome || a?.nome || "")}</b><span class="ge-pill ${cls}">${esc(rotuloClasse(cls, d.caminho))}</span></div>
    ${corpo}
    ${e.provisorio ? `<p class="ge-delta fraco">Provisório: os dados vão até ${fmt.dataCurta(h.data_ref)}; o resultado fecha quando passarem do fim.</p>` : ""}
    ${botoes}</div>`;
}

// Preço médio: o preço de cada produto da base ao fim, contra o alvo, e o % da meta (o aumento feito ÷ o pedido).
function resultadoPreco(d, a) {
  const pct = d.resultado;
  const linhas = a.produtos.map((p) => {
    const id = String(p.id), alvo = d.alvos?.[id] ?? p.meta;
    return `<div class="ge-barra ge-preco"><span title="${esc(p.nome)}">${esc(p.nome)}</span>
      <span>${fmt.moeda2(precoDe(d.base_precos, id))} → <b>${fmt.moeda2(precoDe(d.precos, id))}</b></span><small>alvo ${fmt.moeda2(alvo)}</small></div>`;
  }).join("");
  const barra = `<div class="ge-barra"><span>% da meta</span><span class="ge-barra-trilho"><i style="--c:${corMeta(pct)}" data-largura="${Math.max(0, Math.min(1, pct || 0)) * 100}%"></i></span>
    <b>${pct == null ? "—" : fmt.pct(pct, 0)}</b></div>`;
  const aumento = d.delta == null ? "" : d.aumento_pedido
    ? `Aumento de preço: ${reaisSinal(d.delta)} de ${fmt.moeda2(d.aumento_pedido)} pedidos, nas quantidades vendidas`
    : "Já estava no preço-alvo na base: a meta era manter";
  return `${linhas}${barra}${aumento ? `<p class="ge-delta">${aumento}</p>` : ""}`;
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

// O botão "Campanha" do histórico: volta ao quadro com o vendedor já marcado.
async function acaoPara(id) {
  const v = estado.historico?.vendedor;
  if (raiz.querySelector("#g-nota")?.value.trim() && !confirm("Descartar a observação que você escreveu?")) return;
  if (v?.regiao && v.regiao !== estado.regiao) {
    estado.regiao = v.regiao;
    await carregar(true);
  }
  entrarSelecao([id]);
}

// ---------- detalhe da campanha ----------
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
  const resumo = enc ? `${d.total.no_alvo} de ${d.total.vendedores} na meta · ${plural(d.total.acima_da_base, "acima da base", "acima da base")}`
    : it.situacao === "planejada" ? `${plural(d.total.vendedores, "vendedor", "vendedores")} · começa em ${fmt.dataCurta(it.inicio)}`
    : `${plural(d.total.vendedores, "vendedor", "vendedores")} · dados até ${fmt.dataCurta(d.data_ref)}`;
  const pergunta = `Como está a campanha #${it.id} “${it.nome}”, vendedor por vendedor?`;
  const botoes = d.pode_editar ? `
    <button class="btn" type="button" data-editar-acao="${it.id}">${icone("lapis")}<span>Editar</span></button>
    ${!it.congelado && it.situacao !== "planejada" ? `<button class="btn" type="button" data-encerrar="${it.id}">${icone("certo")}<span>Encerrar</span></button>` : ""}
    <button class="btn" type="button" data-prorrogar="${it.id}">${icone("calendario")}<span>Prorrogar 2 semanas</span></button>
    <button class="btn icone" type="button" data-arquivar-acao="${it.id}" data-arquivada="${it.arquivada ? "0" : "1"}" title="${it.arquivada ? "Voltar ao quadro" : "Arquivar (sai do quadro; o histórico fica)"}" aria-label="${it.arquivada ? "Tirar do arquivo" : "Arquivar"}">${icone("arquivo")}</button>
    <button class="btn icone perigo" type="button" data-excluir-acao="${it.id}" title="Excluir a campanha" aria-label="Excluir a campanha">${icone("lixeira")}</button>` : "";
  const avisos = [d.aviso, ...(d.avisos || [])].filter(Boolean).map((t) => `<div class="aviso">${icone("alerta")}<span>${esc(t)}</span></div>`).join("");
  el.innerHTML = `<section class="cartao secao camp-detalhe entra" style="--i:0;--c:${m.cor}">
      <div class="cartao-cab">
        <div class="ge-det-tit"><button class="btn icone" type="button" data-voltar title="Voltar ao quadro" aria-label="Voltar ao quadro">${icone("voltar")}</button>
          <div><h2>${icone(m.icone)}${esc(it.nome)}</h2>
            <p class="sub">${esc(ind.nome)} · ${esc(periodoTexto(it.inicio, it.fim))} · meta ${esc(textoAlvo(ind, it.alvo_tipo, it.meta_padrao, u))} · lançada por ${esc(it.criada_por_nome)}</p></div></div>
        <div class="camp-acoes">${ctx.assistente ? `<a class="btn" href="#/assistente?q=${encodeURIComponent(pergunta)}" title="Abre o Assistente com a pergunta pronta">${icone("conversa")}<span>Perguntar ao Assistente</span></a>` : ""}${botoes}</div>
      </div>
      <div class="camp-chips">
        <span class="ge-pill ${enc ? "" : it.situacao === "planejada" ? "planejada" : "vigor"}">${esc(SITUACAO[it.situacao])}${it.provisorio ? " · provisório" : ""}</span>
        <span class="chip">${icone("calendario")}base: ${esc(it.base_periodo ? `${textoPeriodoBase(it.base_periodo, it.base_inicio, it.base_fim)} (${PERIODOS_BASE[it.base_periodo].toLowerCase()} fechad${it.base_periodo === "semana" || it.base_periodo === "quinzena" ? "a" : "o"})`
          : `${periodoTexto(it.base_inicio, it.base_fim)} (o mesmo tamanho, logo antes)`)}</span>
        ${(filtros.length ? filtros : ["todos os produtos e clientes"]).map((t) => `<span class="chip">${icone("funil")}${esc(t)}</span>`).join("")}
        ${it.arquivada ? `<span class="chip">${icone("arquivo")}arquivada</span>` : ""}
      </div>
      ${it.descricao ? `<p class="camp-descricao">${esc(it.descricao)}</p>` : ""}
      ${comoNoDetalhe(it)}
      <p class="ge-det-resumo">${esc(resumo)}${d.ocultos ? ` · ${plural(d.ocultos, "vendedor fora do seu acesso", "vendedores fora do seu acesso")}` : ""}</p>
    </section>
    ${avisos}${ind.tipo === "preco_medio" && d.produtos?.length ? gradePrecos(d) : tabelaAcao(d)}${aberturaAcao(d)}`;
  animarEntradas(el);
  ligarTooltips(el);
}

// "Como é calculado: …", com o botão que abre a janela de todos os indicadores.
function comoNoDetalhe(it) {
  const pr = presetDe(it.metrica, it.parametros), como = comoCalcula(pr);
  if (!como.conta) return "";
  return `<p class="ci-como camp-como">${icone("info")}<span><b>Como é calculado:</b> ${esc(como.conta)}
    <button type="button" class="ge-link" data-como="${esc(pr.id)}">Ver detalhes</button></span></p>`;
}

function tabelaAcao(d) {
  if (!d.linhas.length) return `<div class="cartao secao vazio">${icone("pessoas")}<p>Nenhum vendedor da campanha no seu acesso.</p></div>`;
  const it = d.item, ind = d.indicador, u = d.unidade;
  const v = (x) => esc(valorIndicador(ind, x, u));
  const enc = it.situacao === "encerrada";
  const partes = !!ind.numerador && !it.congelado;
  const comDaBase = ind.cobertura && ind.meta_em !== "pct_base"; // positivação em clientes: a % da base ao lado
  const pctDaBase = (da) => {
    const t = daBase(da);
    return t ? `<span title="${esc(t.dica)}">${esc(t.texto)}${t.partes ? `<small>${esc(t.partes)}</small>` : ""}</span>` : "—";
  };
  const linhas = d.linhas.map((x) => `<tr class="ge-clicavel" data-vendedor="${x.id}" tabindex="0" title="Abrir o histórico de ${esc(x.nome)}">
    <td class="nome-v">${esc(x.nome)}<small>código ${x.id}${x.equipe ? ` · ${esc(x.equipe)}` : ""}</small></td>
    <td>${x.base_pendente ? '<span class="fraco">aguardando os dados</span>' : x.base == null ? '<span class="fraco">sem dados</span>' : v(x.base)}${comDaBase && !x.base_pendente && x.base_da_base
      ? `<small title="${esc(daBase(x.base_da_base).dica)}">${esc(daBase(x.base_da_base).texto)} da base</small>` : ""}</td>
    <td>${x.alvo == null ? "—" : v(x.alvo)}</td>
    <td>${x.resultado == null ? "—" : `<b>${v(x.resultado)}</b>`}${partes && x.numerador != null
      ? `<small>${textoPartes(ind, x)}</small>` : ""}</td>
    ${comDaBase ? `<td>${pctDaBase(x.da_base)}</td>` : ""}
    <td>${x.pct == null ? "—" : `<span class="ge-pct" style="--c:${corMeta(x.pct)};--i:${intensidadeMeta(x.pct)}">${fmt.pct(x.pct, 0)}</span>`}</td>
    <td>${x.delta == null ? "—" : esc(deltaTexto(ind, x.delta, u))}</td>
    <td>${enc ? `<span class="ge-pill ${x.classe}">${esc(rotuloClasse(x.classe, x.caminho))}</span>`
      : it.situacao === "planejada" ? chipStatus("sem_meta", "Não começou") : x.status ? chipStatus(x.status, rotuloStatus(ind, x.status)) : "—"}</td></tr>`).join("");
  return `<section class="cartao secao entra" style="--i:2">
    <div class="cartao-cab"><div><h3>${icone("pessoas")}Por vendedor</h3>
      <p class="sub">${enc ? (it.congelado ? "resultado congelado no fim da campanha" : "resultado provisório: os dados ainda não passaram do fim")
        : "resultado até agora; a situação considera o ritmo dos dias úteis"} · clique no vendedor para ver o histórico</p></div></div>
    <div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>Vendedor</th><th>Base</th><th>Meta</th><th${partes ? ` title="${esc(ind.media_diaria ? ind.descricao : `${ind.numerador} ÷ ${ind.denominador}`)}"` : ""}>Resultado</th>${comDaBase
        ? `<th title="${esc(comoCalcula({ id: "positivacao:pct_base" }).conta)}">% da base</th>` : ""}<th>% da meta</th><th>Sobre a base</th><th>Situação</th></tr></thead>
      <tbody>${linhas}</tbody>${comDaBase && d.total.da_base ? `<tfoot><tr class="ge-total"><td class="nome-v">Equipe<small>os vendedores do seu acesso juntos</small></td><td></td><td></td>
        <td>${d.total.realizado == null ? "—" : `<b>${v(d.total.realizado)}</b>`}</td><td>${pctDaBase(d.total.da_base)}</td><td></td><td></td><td></td></tr></tfoot>` : ""}</table></div></section>`;
}

// "3 ÷ 8" embaixo do resultado; na efetividade (média dos dias), os pedidos, as visitas e os dias, que não se dividem.
function textoPartes(ind, x) {
  if (ind.media_mensal) { // a % da base: os atendidos e os ativos (somados nos meses, que não se dividem)
    return `${fmt.num(x.numerador)} de ${fmt.num(x.denominador)} da base${x.meses > 1 ? ` · média de ${x.meses} meses` : ""}`;
  }
  if (!ind.media_diaria) return `${valorParte(ind, x.numerador)} ÷ ${valorParte(ind, x.denominador)}`;
  return `${plural(x.numerador, "pedido na rota", "pedidos na rota")} · ${plural(x.denominador, "visita", "visitas")} · média de ${plural(x.dias || 0, "dia", "dias")}`;
}

// A mesma conta aberta por área, segmento ou produto (os vendedores do acesso, juntos), enquanto a campanha corre.
function aberturaAcao(d) {
  const ind = d.indicador;
  if (!ind.aberturas?.length || d.item.congelado || d.item.situacao === "planejada") return "";
  const ab = d.abertura;
  const opcoes = [["", "Não abrir"], ...ind.aberturas.map((k) => [k, ABERTURAS[k]])]
    .map(([k, n]) => `<option value="${k}" ${k === (ab?.por || "") ? "selected" : ""}>${esc(n)}</option>`).join("");
  const comPartes = !!ind.numerador;
  const linhas = (ab?.linhas || []).map((x) => `<tr>
    <td class="nome-v">${esc(x.nome)}</td><td>${esc(valorIndicador(ind, x.valor, d.unidade))}</td>
    ${comPartes ? `<td>${valorParte(ind, x.numerador)}</td><td>${valorParte(ind, x.denominador)}</td>` : ""}${ind.media_diaria ? `<td>${x.dias ?? "—"}</td>` : ""}</tr>`).join("");
  return `<section class="cartao secao entra" style="--i:3">
    <div class="cartao-cab"><div><h3>${icone("funil")}Aberto por ${esc(ab ? ABERTURAS[ab.por].toLowerCase() : "…")}</h3>
      <p class="sub">os vendedores da campanha juntos${ab?.mais ? ` · mostrando ${ab.linhas.length} de ${ab.linhas.length + ab.mais}` : ""}</p></div>
      <label class="campo"><select data-abrir aria-label="Abrir por" style="padding-left:14px">${opcoes}</select></label></div>
    ${ab ? `<div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>${esc(ABERTURAS[ab.por])}</th><th${ind.media_diaria ? ` title="${esc(ind.descricao)}"` : ""}>${esc(ind.nome)}</th>${comPartes ? `<th>${esc(ind.numerador)}</th><th>${esc(ind.denominador)}</th>` : ""}${ind.media_diaria ? "<th>Dias com visita</th>" : ""}</tr></thead>
      <tbody>${linhas || `<tr><td colspan="5" class="fraco">Nada no período.</td></tr>`}</tbody></table></div>`
      : `<p class="usu-nota">${icone("info")}<span>Escolha como abrir o resultado: por ${ind.aberturas.map((k) => ABERTURAS[k].toLowerCase()).join(", ")}.</span></p>`}
  </section>`;
}

// Preço médio: o preço de cada vendedor em cada produto, com o da base embaixo e a cor do caminho até o preço-alvo, e o
// % da meta de cada um (o aumento feito ÷ o pedido, em R$ nas quantidades vendidas).
function gradePrecos(d) {
  const prods = d.produtos, ind = d.indicador, it = d.item;
  const enc = it.situacao === "encerrada";
  const un = (p) => esc((p.unidade || "").toLowerCase());
  const alvoCampanha = Object.fromEntries(prods.map((p) => [p.id, p.meta]));
  const cel = (p, u) => {
    if (!p || (p.preco == null && p.base == null)) return '<td class="fraco">—</td>';
    const proprio = p.meta != null && p.meta !== alvoCampanha[p.id] ? ` · alvo próprio ${fmt.moeda2(p.meta)}` : "";
    const base = (p.base == null ? "sem base" : `base ${fmt.moeda2(p.base)}`) + proprio;
    const agora = p.preco == null ? '<span class="fraco">sem venda</span>'
      : `<b${p.pct != null ? ` style="color:color-mix(in srgb, ${corMeta(p.pct)} 70%, var(--tinta))"` : ""}>${fmt.moeda2(p.preco)}</b>`;
    return `<td title="${p.pct != null ? `${fmt.pct(p.pct, 0)} do caminho até o alvo` : ""}">${agora}<small>${base}${p.quantidade ? ` · ${fmt.num(p.quantidade, 1)} ${u}` : ""}</small></td>`;
  };
  const aumento = (x) => (x.delta == null ? "—" : x.aumento_pedido
    ? `${reaisSinal(x.delta)}<small>de ${fmt.moeda2(x.aumento_pedido)}</small>` : `${reaisSinal(x.delta)}<small>já estava no alvo</small>`);
  const linhas = d.linhas.map((x) => {
    const por = Object.fromEntries((x.produtos || []).map((p) => [p.id, p]));
    return `<tr class="ge-clicavel" data-vendedor="${x.id}" tabindex="0"><td class="nome-v">${esc(x.nome)}<small>código ${x.id}${x.equipe ? ` · ${esc(x.equipe)}` : ""}${x.meta_propria ? " · meta própria" : ""}</small></td>
      <td>${x.pct == null ? (x.base_pendente ? '<span class="fraco">aguardando a base</span>' : "—")
        : `<span class="ge-pct" style="--c:${corMeta(x.pct)};--i:${intensidadeMeta(x.pct)}">${fmt.pct(x.pct, 0)}</span>`}</td>
      <td>${aumento(x)}</td>
      <td>${enc ? `<span class="ge-pill ${x.classe}">${esc(rotuloClasse(x.classe, x.caminho))}</span>`
        : it.situacao === "planejada" ? chipStatus("sem_meta", "Não começou") : x.status ? chipStatus(x.status, rotuloStatus(ind, x.status)) : "—"}</td>
      ${prods.map((p) => cel(por[p.id], un(p))).join("")}</tr>`;
  }).join("");
  const equipe = (p) => (p.preco == null ? '<td class="fraco">—</td>' : `<td><b>${fmt.moeda2(p.preco)}</b><small>${fmt.num(p.quantidade, 1)} ${un(p)}</small></td>`);
  return `<section class="cartao secao entra" style="--i:2">
    <div class="cartao-cab"><div><h3>${icone("moeda")}Preço médio por produto</h3>
      <p class="sub">${enc ? (it.congelado ? "resultado congelado no fim da campanha" : "resultado provisório: os dados ainda não passaram do fim") : "preço até agora"} (venda líquida ÷ quantidade) e o da base embaixo · o % da meta é o aumento de preço feito sobre a base ÷ o aumento até o preço-alvo, somados em R$ nas quantidades vendidas (base R$ 10, alvo R$ 20 e agora R$ 15 = 50%) · clique no vendedor para ver o histórico</p></div></div>
    <div class="tabela-rolagem"><table class="dados camp-grade">
      <thead><tr><th>Vendedor</th><th>% da meta</th><th title="Aumento de preço feito, em R$ nas quantidades vendidas, e o que a meta pede">Aumento</th><th>Situação</th>${prods.map((p) => `<th title="${esc(p.nome)}">${esc(p.nome)}<small>alvo ${fmt.moeda2(p.meta)}${p.unidade ? `/${un(p)}` : ""}</small></th>`).join("")}</tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td class="nome-v">Equipe<small>aumento de todos ÷ o pedido</small></td><td><b>${d.total.realizado != null ? fmt.pct(d.total.realizado, 0) : "—"}</b></td><td></td><td></td>${prods.map(equipe).join("")}</tr></tfoot>
    </table></div></section>`;
}

// ---------- gravação (só o administrador) ----------
// nome, quantos vendedores e o fim: do detalhe aberto, do histórico ou do quadro.
function infoAcao(id) {
  const det = estado.detalhe?.item;
  if (det && det.id === id) return { nome: det.nome, n: det.vendedores?.length || estado.detalhe.total.vendedores, fim: det.fim, antiga: !det.base_periodo };
  const h = estado.historico?.acoes?.[String(id)];
  if (h) return { nome: h.nome, n: h.vendedores, fim: h.fim, antiga: !h.base_periodo };
  const q = acaoDoQuadro(id);
  return q ? { nome: q.nome, n: q.total_vendedores, fim: q.fim, antiga: !q.base_periodo } : { nome: `#${id}`, n: 0, fim: null, antiga: false };
}
const paraQuem = (n) => (n === 1 ? "o vendedor" : n ? `os ${n} vendedores` : "os vendedores");

async function encerrar(id) {
  const a = infoAcao(id), ate = estado.quadro?.data_ref;
  if (!confirm(`Encerrar “${a.nome}” para ${paraQuem(a.n)} dela? O resultado de cada um fica congelado${ate ? ` com os dados até ${fmt.dataCurta(ate)}` : ""}.`)) return;
  try {
    await api("/api/gestao/acao/encerrar", { json: { id } });
    toast("Campanha encerrada");
    await recarregarTudo();
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function prorrogar(id) {
  const a = infoAcao(id);
  const novo = a.fim ? ` (até ${fmt.dataCurta(somar(a.fim, 14))})` : "";
  const base = a.antiga ? "A base de cada um é medida de novo, no mesmo tamanho do novo prazo." : "A base de cada um continua a mesma.";
  if (!confirm(`Prorrogar “${a.nome}” por 2 semanas para ${paraQuem(a.n)} dela${novo}? ${base}`)) return;
  try {
    await api("/api/gestao/acao/prorrogar", { json: { id, dias: 14 } });
    toast("Campanha prorrogada por 2 semanas");
    await recarregarTudo();
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function arquivar(id, sim) {
  try {
    await api("/api/gestao/acao/arquivar", { json: { id, arquivada: sim } });
    toast(sim ? "Campanha arquivada: saiu do quadro (o histórico dos vendedores continua)" : "A campanha voltou ao quadro");
    await recarregarTudo();
  } catch (e) {
    toast(e.message, "erro");
  }
}

async function excluirAcao(id) {
  const a = infoAcao(id);
  if (!confirm(`Excluir “${a.nome}”? O histórico dos vendedores perde os registros desta campanha (as observações ficam).`)) return;
  try {
    await api("/api/gestao/acao/excluir", { json: { id } });
    toast("Campanha excluída");
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
  if (!ctx.admin) { toast("Só o administrador lança campanhas; peça a ele.", "erro"); return; }
  try {
    const r = await api(`/api/gestao/rascunho?id=${encodeURIComponent(uuid)}`);
    if (r.acao) {
      toast(`Este rascunho já virou a campanha “${r.acao.nome}”`);
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
    // rascunho de antes, com a meta "base + N" (que a campanha nova não tem): a meta fica para preencher
    const antigo = d.alvo_tipo === "mais";
    entrarSelecao((d.vendedores || []).map((v) => v.id),
                  { ...d, alvo_tipo: antigo ? "fixo" : d.alvo_tipo || "fixo", ...(antigo ? { meta_padrao: "", vendedores: (d.vendedores || []).map((v) => ({ id: v.id, meta: null })) } : {}) },
                  { rascunho: d.id, nomes: d.nomes });
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
    <p class="sub">Equipe ${esc(formObj.regiao)}: o indicador da equipe toda (sem repetir clientes entre os vendedores), contra uma meta da equipe.</p>
    <div class="cf-grade">
      <label class="campo-form largo"><span>Nome</span><input name="nome" maxlength="120" value="${esc(d.nome)}" placeholder="Ex.: Mix médio da equipe" autocomplete="off"></label>
      <label class="campo-form"><span>Início</span><input type="date" name="inicio" value="${esc(d.inicio)}"></label>
      <label class="campo-form"><span>Fim</span><input type="date" name="fim" value="${esc(d.fim)}"></label>
      <div class="largo ge-indicador" id="go-indicador"><div class="esqueleto" style="height:66px"></div></div>
      <label class="campo-form" id="go-meta-bloco"><span>Meta da equipe <small id="go-unidade"></small></span>
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
    if (dados.metrica !== "preco_medio" && !(dados.meta_padrao > 0)) return erro("dê a meta da equipe");
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

const daAgenda = (e) => !!e.target.closest("#g-agenda");

function aoClicar(e) {
  if (daAgenda(e)) return;
  if (e.target.closest(".multi")) return; // as listas de produtos e clientes têm o próprio data-acao (Aplicar, Limpar)
  const t = e.target.closest("[data-regiao],[data-nova],[data-objetivo],[data-acao-para],[data-acao],[data-vendedor],[data-voltar]," +
    "[data-encerrar],[data-prorrogar],[data-editar-acao],[data-arquivar-acao],[data-excluir-acao],[data-excluir-nota]," +
    "[data-enviar-nota],[data-cancelar-form],[data-lancar],[data-meta-propria],[data-tirar-meta],[data-parar]," +
    "[data-marcar-todos],[data-como]");
  if (!t) return;
  const ds = t.dataset;
  if ("marcarTodos" in ds) return marcarTodos();
  if (ds.como) return abrirComoCalcula(ds.como);
  if (ds.metaPropria) return abrirMetaPropria(Number(ds.metaPropria));
  if (ds.tirarMeta) return tirarMetaPropria(Number(ds.tirarMeta));
  if ("parar" in ds) return; // o campo da meta própria: não marca nem desmarca o vendedor
  if (ds.regiao) return trocarRegiao(ds.regiao);
  if ("nova" in ds) return entrarSelecao(ativosDoQuadro(), null, { todos: true });
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
  if (daAgenda(e)) return;
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
  if (t.name === "inicio") { desenharPrazos(); desenharBases(); }
  if ((t.name === "prazo" || t.name === "fim") && estado.form?.antiga) desenharBases(); // a janela de antes segue o prazo
  if (t.name === "alvo_tipo") atualizarAlvo();
  if (["inicio", "prazo", "fim", "base_periodo"].includes(t.name)) agendarPrevia();
}

function aoDigitar(e) {
  if (daAgenda(e)) return;
  if (e.target.name === "meta" && e.target.closest("#g-form")) atualizarAlvo();
  if (e.target.dataset.metaV && estado.form) {
    estado.form.metas.set(Number(e.target.dataset.metaV), e.target.value === "" ? null : Number(e.target.value));
    atualizarMetasQuadrados();
  }
  if (e.target.dataset.precoV && estado.form) { // preço médio: o preço-alvo próprio de um produto
    const vid = Number(e.target.dataset.precoV), proprios = { ...(estado.form.alvos.get(vid) || {}) };
    if (e.target.value === "") delete proprios[e.target.dataset.precoP];
    else proprios[e.target.dataset.precoP] = Number(e.target.value);
    estado.form.alvos.set(vid, proprios);
    atualizarMetasQuadrados();
  }
}

// A meta própria de um vendedor marcado: abre o campo no quadrado dele (o tipo é o da meta padrão; no preço médio,
// um preço-alvo por produto).
function abrirMetaPropria(id) {
  estado.form?.abertas.add(id);
  redesenharQuadrado(id);
  raiz.querySelector(`[data-meta-v="${id}"], [data-preco-v="${id}"]`)?.focus();
}

function tirarMetaPropria(id) {
  const f = estado.form;
  if (!f) return;
  f.metas.set(id, null);
  f.alvos.delete(id);
  f.abertas.delete(id);
  redesenharQuadrado(id);
  raiz.querySelector(`.ge-vend[data-vendedor="${id}"] [data-meta-propria]`)?.focus();
}

function aoTeclar(e) {
  if (daAgenda(e)) return;
  if (e.target.id === "g-nota" && e.key === "Enter" && !e.shiftKey) { // Enter grava; Shift+Enter pula linha
    e.preventDefault();
    enviarNota();
  } else if (e.key === "Enter" && e.target.matches("tr[data-vendedor]")) {
    abrirVendedor(Number(e.target.dataset.vendedor));
  }
}
