// Página Gestão: campanhas de vendas num quadro (kanban), como no Bitrix. Cada card é uma campanha; arrastar muda a
// coluna (Planejada, Em andamento, Concluída) e, quando as datas dizem que ela já devia ter mudado, o card sugere.
// Clicar num card mostra embaixo o andamento de cada vendedor. A conta é toda no servidor (bi/gestao.py, os mesmos
// números que o Assistente dá). Criar e editar é numa janela; o rascunho que o Assistente monta chega por
// #/gestao?rascunho=<id> e abre a janela preenchida. Cada pessoa vê as campanhas que criou (o administrador, todas).
import { api, esc, fmt, icone, chipStatus, corStatus, STATUS, animarEntradas, ligarTooltips, linhaTT, toast } from "./util.js";
import { multiSelecao } from "./multiselecao.js";

export const COLUNAS = [
  { id: "planejada", nome: "Planejada", cor: "var(--s-ritmo)", vazio: "Campanhas que ainda vão começar" },
  { id: "andamento", nome: "Em andamento", cor: "var(--laranja)", vazio: "Arraste para cá as que já começaram" },
  { id: "concluida", nome: "Concluída", cor: "var(--ok-forte)", vazio: "As encerradas ficam aqui" },
];
export const METRICAS = {
  faturamento: { nome: "Faturamento", icone: "moeda", cor: "var(--s-fat)", descricao: "venda líquida em R$, descontando as devoluções, como nas metas" },
  volume: { nome: "Volume", icone: "caixa", cor: "var(--s-mus)", descricao: "quantidade vendida dos produtos da campanha (todos da mesma unidade)" },
  positivacao: { nome: "Positivação", icone: "pessoas", cor: "var(--k-cli)", descricao: "clientes distintos que compraram no período" },
  mix: { nome: "Mix", icone: "etiqueta", cor: "var(--s-out)", descricao: "produtos distintos vendidos no período" },
};
const FILTROS = [
  { id: "produtos", rotulo: "Produtos", icone: "caixa", todos: "Todos os produtos", plural: "produtos" },
  { id: "linhas", rotulo: "Linhas", icone: "etiqueta", todos: "Todas as linhas", plural: "linhas" },
  { id: "categorias", rotulo: "Categorias", icone: "funil", todos: "Todas as categorias", plural: "categorias" },
  { id: "grupos", rotulo: "Grupo", icone: "queijo", todos: "Mussarela e outras", plural: "grupos", semBusca: true },
  { id: "ufs", rotulo: "UF do cliente", icone: "mapa", todos: "Todas as UFs", plural: "UFs", semBusca: true },
  { id: "segmentos", rotulo: "Segmentos", icone: "pessoas", todos: "Todos os segmentos", plural: "segmentos" },
];
const NOME_GRUPO = { mussarela: "Mussarela", outras: "Outras linhas" };
const EQUIPE = { ES: "ES", BA: "BA", EDIR: "Edir", OCULTO: "Outros" };

let ctx = null, raiz = null, ligado = false;
const estado = { quadro: null, catalogo: null, erroCatalogo: null, sel: null, detalhe: null, todas: false,
                 arquivadas: false, busca: "", pedido: 0, pedidoSel: 0, naPagina: false };
let dlg = null, form = null, filtros = {};

// ---------- apoio ----------
// Valor na unidade da métrica (curto: para cards e barras).
export function valorMetrica(metrica, v, unidade = "", curto = false) {
  if (v == null || isNaN(v)) return "—";
  if (metrica === "faturamento") return curto ? fmt.moedaC(v) : fmt.moeda(v);
  if (metrica === "volume") return `${fmt.num(v, Math.abs(v) >= 100 ? 0 : 1)}${unidade ? " " + unidade.toLowerCase() : ""}`;
  const n = Math.round(v);
  const nome = metrica === "positivacao" ? (n === 1 ? "cliente" : "clientes") : (n === 1 ? "produto" : "produtos");
  return `${fmt.num(n)} ${nome}`;
}

export function periodoTexto(inicio, fim) {
  return inicio === fim ? fmt.data(inicio) : `${fmt.data(inicio)} a ${fmt.data(fim)}`;
}

const hoje = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const parametros = () => new URLSearchParams(location.hash.split("?")[1] || "");
const naGestao = () => /^#\/gestao(\?|$)/.test(location.hash);
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;

function nomeProduto(id, nomes) {
  return nomes?.[id] || estado.catalogo?.produtos.find((p) => p.id === id)?.nome || `produto ${id}`;
}

// Os filtros em texto curto (cards, painel e rascunho do Assistente).
export function textoFiltros(f, nomesProdutos) {
  const partes = [];
  const lista = (v, max = 3) => (v.length <= max ? v.join(", ") : `${v.slice(0, max).join(", ")} e mais ${v.length - max}`);
  if (f.produtos?.length) partes.push(lista(f.produtos.map((p) => nomeProduto(p, nomesProdutos))));
  if (f.linhas?.length) partes.push(`linha ${lista(f.linhas)}`);
  if (f.categorias?.length) partes.push(lista(f.categorias));
  if (f.grupos?.length) partes.push(f.grupos.map((g) => NOME_GRUPO[g] || g).join(" e "));
  if (f.ufs?.length) partes.push(`clientes de ${lista(f.ufs, 5)}`);
  if (f.segmentos?.length) partes.push(`segmento ${lista(f.segmentos)}`);
  return partes;
}

// ---------- montagem ----------
export function gestaoTemAlteracoes() { return !!(dlg?.open && formMudou()); }

export function recarregarGestao() {
  if (!ctx) return;
  estado.catalogo = null;
  carregar(true);
}

export function montarGestao(container, contexto) {
  ctx = contexto;
  raiz = container;
  const q = parametros();
  if (q.get("c")) estado.sel = Number(q.get("c")) || null;
  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("quadro")}</span>
        <div><b>Campanhas</b><small>arraste os cards entre as colunas · clique para ver o andamento</small></div></div>
      <div class="filtros">
        <label class="campo sem-seta g-busca"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="g-busca" placeholder="Buscar campanha" aria-label="Buscar campanha" value="${esc(estado.busca)}"></label>
        ${ctx.admin ? `<div class="seg-mini" role="group" aria-label="Campanhas de quem">
          <button type="button" data-todas="0" class="${estado.todas ? "" : "ativo"}">Minhas</button>
          <button type="button" data-todas="1" class="${estado.todas ? "ativo" : ""}">De todos</button></div>` : ""}
        <button class="btn btn-limpar ${estado.arquivadas ? "ativo" : ""}" type="button" id="g-arquivadas" aria-pressed="${estado.arquivadas}">${icone("arquivo")}Arquivadas</button>
        <button class="btn primario" type="button" id="g-nova">${icone("mais")}Nova campanha</button>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-gestao" title="Configurações da gestão: os vendedores que cada pessoa pode pôr nas campanhas">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="g-avisos"></div>
    <div id="g-quadro"><div class="kanban">${COLUNAS.map(() => '<div class="esqueleto" style="height:320px"></div>').join("")}</div></div>
    <div id="g-detalhe"></div>`;
  let relogio = null;
  container.querySelector("#g-busca").addEventListener("input", (e) => {
    clearTimeout(relogio);
    relogio = setTimeout(() => { estado.busca = e.target.value.trim(); desenharQuadro(); }, 150);
  });
  container.querySelectorAll("[data-todas]").forEach((b) => b.addEventListener("click", () => {
    estado.todas = b.dataset.todas === "1";
    container.querySelectorAll("[data-todas]").forEach((x) => x.classList.toggle("ativo", x === b));
    carregar();
  }));
  container.querySelector("#g-arquivadas").addEventListener("click", (e) => {
    estado.arquivadas = !estado.arquivadas;
    e.currentTarget.classList.toggle("ativo", estado.arquivadas);
    e.currentTarget.setAttribute("aria-pressed", estado.arquivadas);
    carregar();
  });
  container.querySelector("#g-nova").addEventListener("click", () => abrirFormulario());
  ligarQuadro(container.querySelector("#g-quadro"));
  container.querySelector("#g-detalhe").addEventListener("click", aoClicarDetalhe);
  criarJanela();
  if (!ligado) {
    ligado = true;
    window.addEventListener("hashchange", aoMudarHash);
    document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".camp-pop, [data-menu]")) fecharMenus(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharMenus(); });
  }
  estado.naPagina = true;
  carregar();
  carregarCatalogo();
  if (q.get("rascunho")) abrirRascunho(q.get("rascunho"));
}

// Ao voltar para a página o quadro é lido de novo (uma campanha criada pelo Assistente aparece); ao sair, a janela
// de campanha fecha (se tinha alterações, o roteador já perguntou antes).
function aoMudarHash() {
  if (!naGestao()) {
    estado.naPagina = false;
    if (dlg?.open) dlg.close();
    fecharMenus();
    return;
  }
  const q = parametros();
  if (!estado.naPagina) { estado.naPagina = true; carregar(true); }
  if (q.get("rascunho")) abrirRascunho(q.get("rascunho"));
  else if (q.get("c") && Number(q.get("c")) !== estado.sel) selecionar(Number(q.get("c")), { rolar: true });
}

function atualizarUrl() {
  if (!naGestao()) return;
  history.replaceState(null, "", estado.sel ? `#/gestao?c=${estado.sel}` : "#/gestao");
}

// ---------- dados ----------
async function carregar(silencioso = false) {
  const alvo = raiz.querySelector("#g-quadro");
  const pedido = ++estado.pedido;
  if (estado.quadro) alvo.classList.add("recarregando");
  try {
    const p = new URLSearchParams();
    if (estado.todas) p.set("todas", "1");
    if (estado.arquivadas) p.set("arquivadas", "1");
    const d = await api(`/api/gestao?${p}`);
    if (pedido !== estado.pedido) return;
    estado.quadro = d;
    if (d.data_ref) ctx.subtitulo({ data_ref: d.data_ref });
    raiz.querySelector("#g-avisos").innerHTML = d.aviso ? `<div class="aviso">${icone("alerta")}<span>${esc(d.aviso)}</span></div>` : "";
    desenharQuadro();
    if (estado.sel && d.campanhas.some((c) => c.id === estado.sel)) selecionar(estado.sel, { silencioso: true });
    else if (estado.sel) { estado.sel = null; estado.detalhe = null; desenharDetalhe(); atualizarUrl(); }
  } catch (e) {
    if (pedido !== estado.pedido) return;
    alvo.innerHTML = `<div class="cartao secao vazio">${icone("alerta")}<p>Não foi possível carregar as campanhas: ${esc(e.message)}</p></div>`;
    if (!silencioso) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) alvo.classList.remove("recarregando");
  }
}

async function carregarCatalogo() {
  if (estado.catalogo) return estado.catalogo;
  try {
    estado.catalogo = await api("/api/gestao/catalogo");
    estado.erroCatalogo = null;
  } catch (e) {
    estado.erroCatalogo = e.message;
  }
  return estado.catalogo;
}

async function selecionar(id, { rolar = false, silencioso = false } = {}) {
  const mudou = estado.sel !== id;
  estado.sel = id;
  atualizarUrl();
  raiz.querySelectorAll(".camp-card").forEach((c) => c.classList.toggle("selecionada", Number(c.dataset.id) === id));
  const pedido = ++estado.pedidoSel;
  const alvo = raiz.querySelector("#g-detalhe");
  if (mudou || !estado.detalhe) {
    alvo.innerHTML = `<div class="secao"><div class="esqueleto" style="height:150px"></div><div class="esqueleto secao" style="height:340px"></div></div>`;
  } else {
    alvo.classList.add("recarregando");
  }
  if (rolar) alvo.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const d = await api(`/api/gestao/campanha?id=${id}`);
    if (pedido !== estado.pedidoSel) return;
    estado.detalhe = d;
    desenharDetalhe();
  } catch (e) {
    if (pedido !== estado.pedidoSel) return;
    if (e.status === 404) { estado.sel = null; estado.detalhe = null; atualizarUrl(); }
    alvo.innerHTML = `<div class="cartao secao vazio">${icone("alerta")}<p>${esc(e.message)}</p></div>`;
    if (!silencioso) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedidoSel) alvo.classList.remove("recarregando");
  }
}

function fecharDetalhe() {
  estado.sel = null;
  estado.detalhe = null;
  ++estado.pedidoSel;
  atualizarUrl();
  raiz.querySelectorAll(".camp-card.selecionada").forEach((c) => c.classList.remove("selecionada"));
  desenharDetalhe();
}

// ---------- quadro ----------
function visiveis() {
  const termo = estado.busca.toLowerCase();
  return (estado.quadro?.campanhas || []).filter((c) => !termo ||
    `${c.nome} ${c.descricao} ${c.criada_por_nome} ${c.id}`.toLowerCase().includes(termo));
}

function desenharQuadro() {
  const alvo = raiz.querySelector("#g-quadro");
  if (!estado.quadro) return;
  const lista = visiveis();
  if (!estado.quadro.campanhas.length && !estado.busca) {
    alvo.innerHTML = `<section class="cartao secao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("quadro")}</div>
      <h3>${estado.arquivadas ? "Nenhuma campanha arquivada" : "Nenhuma campanha ainda"}</h3>
      <p>Uma campanha acompanha, num período, quanto cada vendedor vendeu de uma linha, de um produto ou de tudo:
        faturamento, volume, clientes positivados ou mix. Crie aqui ou peça ao Assistente, por exemplo:
        <i>“crie uma campanha de requeijão para a equipe BA em novembro, meta de 30 clientes por vendedor”</i>.</p>
      <button class="btn primario" type="button" data-nova>${icone("mais")}Nova campanha</button></section>`;
    alvo.querySelector("[data-nova]").addEventListener("click", () => abrirFormulario());
    return;
  }
  alvo.innerHTML = `<div class="kanban">${COLUNAS.map((col, i) => {
    const cards = lista.filter((c) => c.status === col.id);
    return `<section class="kanban-coluna entra" style="--i:${i + 1};--c:${col.cor}" data-status="${col.id}" aria-label="${esc(col.nome)}">
      <header class="kanban-cab"><span class="ponto"></span><b>${esc(col.nome)}</b><span class="cont">${cards.length}</span></header>
      <div class="kanban-cards" data-status="${col.id}">
        ${cards.map(cartao).join("") || `<p class="kanban-vazio">${esc(estado.busca ? "Nenhuma campanha com esse nome" : col.vazio)}</p>`}
      </div></section>`;
  }).join("")}</div>`;
  animarEntradas(alvo);
  ligarTooltips(alvo);
}

function cartao(c) {
  const m = METRICAS[c.metrica];
  const r = c.resumo;
  let progresso = "";
  if (r && r.meta) {
    progresso = `<div class="camp-barra" style="--c:${corStatus(r.status)}"><i data-largura="${Math.min(100, (r.pct || 0) * 100)}%"></i></div>
      <div class="camp-num"><span><b>${fmt.pct(r.pct)}</b> da meta</span><span>${r.bateram} de ${r.com_meta} bateram</span></div>`;
  } else if (r) {
    progresso = `<div class="camp-num"><span>${esc(valorMetrica(c.metrica, r.distintos ?? r.realizado, r.unidade, true))}</span><span>só ranking</span></div>`;
  }
  const sug = c.sugestao && !c.arquivada
    ? `<button type="button" class="camp-sugestao" data-mover="${c.sugestao.status}" title="Mover para ${esc(COLUNAS.find((x) => x.id === c.sugestao.status).nome)}">${icone("alerta")}${esc(c.sugestao.texto)} · mover</button>` : "";
  const autor = estado.todas && !c.minha ? `<small class="camp-autor">${icone("usuario")}${esc(c.criada_por_nome)}</small>` : "";
  return `<article class="camp-card ${c.id === estado.sel ? "selecionada" : ""} ${c.arquivada ? "arquivada" : ""}" draggable="true"
      data-id="${c.id}" tabindex="0" style="--c:${m.cor}" aria-label="Campanha ${esc(c.nome)}">
    <div class="camp-topo">
      <span class="chip camp-metrica">${icone(m.icone)}${esc(m.nome)}</span>
      ${c.arquivada ? `<span class="chip">${icone("arquivo")}arquivada</span>` : ""}
      <button type="button" class="camp-menu-btn" data-menu aria-haspopup="menu" aria-label="Mais ações da campanha ${esc(c.nome)}">${icone("pontos")}</button>
    </div>
    <h4>${esc(c.nome)}</h4>
    <p class="camp-info"><span>${icone("calendario")}${esc(periodoTexto(c.inicio, c.fim))}</span>
      <span>${icone("pessoas")}${plural(c.vendedores.length, "vendedor", "vendedores")}</span>
      ${c.premiacao ? `<span title="${esc(c.premiacao)}">${icone("trofeu")}prêmio</span>` : ""}</p>
    ${progresso}${sug}${autor}
  </article>`;
}

// Menu do card: mover para outra coluna (no celular não dá para arrastar), editar, arquivar e excluir.
function abrirMenu(card) {
  fecharMenus();
  const c = estado.quadro.campanhas.find((x) => x.id === Number(card.dataset.id));
  if (!c) return;
  card.insertAdjacentHTML("beforeend", `<div class="camp-pop" role="menu">
    ${COLUNAS.filter((col) => col.id !== c.status).map((col) => `<button type="button" role="menuitem" data-mover="${col.id}">${icone("seta")}Mover para ${esc(col.nome)}</button>`).join("")}
    <button type="button" role="menuitem" data-editar>${icone("lapis")}Editar</button>
    <button type="button" role="menuitem" data-arquivar="${c.arquivada ? "0" : "1"}">${icone("arquivo")}${c.arquivada ? "Tirar do arquivo" : "Arquivar"}</button>
    <button type="button" role="menuitem" data-excluir class="perigo">${icone("lixeira")}Excluir</button>
  </div>`);
  card.classList.add("com-menu");
  card.querySelector(".camp-pop button")?.focus();
}

function fecharMenus() {
  raiz?.querySelectorAll(".camp-pop").forEach((p) => { p.closest(".camp-card")?.classList.remove("com-menu"); p.remove(); });
}

function ligarQuadro(alvo) {
  alvo.addEventListener("click", (e) => {
    const card = e.target.closest(".camp-card");
    if (!card) return;
    const id = Number(card.dataset.id);
    const botao = e.target.closest("button");
    if (botao?.hasAttribute("data-menu")) { e.stopPropagation(); return card.querySelector(".camp-pop") ? fecharMenus() : abrirMenu(card); }
    if (botao?.dataset.mover) { fecharMenus(); return mover(id, botao.dataset.mover, null); }
    if (botao?.hasAttribute("data-editar")) { fecharMenus(); return editar(id); }
    if (botao?.dataset.arquivar) { fecharMenus(); return arquivar(id, botao.dataset.arquivar === "1"); }
    if (botao?.hasAttribute("data-excluir")) { fecharMenus(); return excluir(id); }
    if (e.target.closest(".camp-pop")) return;
    selecionar(id, { rolar: true });
  });
  alvo.addEventListener("keydown", (e) => {
    const card = e.target.closest(".camp-card");
    if (!card || e.target !== card) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selecionar(Number(card.dataset.id), { rolar: true }); }
  });
  // Arrastar (mouse): o lugar onde o card vai cair aparece tracejado; soltar grava a coluna e a posição.
  let arrastando = null;
  const lugar = document.createElement("div");
  lugar.className = "camp-lugar";
  alvo.addEventListener("dragstart", (e) => {
    const card = e.target.closest?.(".camp-card");
    if (!card) return;
    fecharMenus();
    arrastando = card;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.id);
    lugar.style.height = `${card.offsetHeight}px`;
    requestAnimationFrame(() => card.classList.add("arrastando"));
  });
  const listaDe = (e) => e.target.closest?.(".kanban-coluna")?.querySelector(".kanban-cards");
  alvo.addEventListener("dragover", (e) => {
    const lista = listaDe(e);
    if (!arrastando || !lista) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    alvo.querySelectorAll(".kanban-coluna").forEach((c) => c.classList.toggle("alvo", c.contains(lista)));
    const depois = [...lista.querySelectorAll(".camp-card:not(.arrastando)")]
      .find((c) => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
    lista.querySelector(".kanban-vazio")?.setAttribute("hidden", "");
    if (depois) lista.insertBefore(lugar, depois);
    else lista.appendChild(lugar);
  });
  alvo.addEventListener("drop", (e) => {
    const lista = listaDe(e);
    if (!arrastando || !lista) return;
    e.preventDefault();
    const proximo = lugar.nextElementSibling?.closest(".camp-card");
    const id = Number(arrastando.dataset.id);
    lista.insertBefore(arrastando, lugar);
    limparArraste();
    mover(id, lista.dataset.status, proximo ? Number(proximo.dataset.id) : null);
  });
  alvo.addEventListener("dragend", limparArraste);
  function limparArraste() {
    arrastando?.classList.remove("arrastando");
    arrastando = null;
    lugar.remove();
    alvo.querySelectorAll(".kanban-coluna.alvo").forEach((c) => c.classList.remove("alvo"));
    alvo.querySelectorAll(".kanban-vazio[hidden]").forEach((v) => v.removeAttribute("hidden"));
  }
}

async function mover(id, status, antesDe) {
  const c = estado.quadro.campanhas.find((x) => x.id === id);
  try {
    await api("/api/gestao/campanha/mover", { json: { id, status, antes_de: antesDe } });
    if (c && c.status !== status) toast(`${c.nome}: ${COLUNAS.find((x) => x.id === status).nome}`);
  } catch (e) {
    toast(e.message, "erro");
  }
  await carregar(true);
}

async function arquivar(id, arquivada) {
  try {
    await api("/api/gestao/campanha/arquivar", { json: { id, arquivada } });
    toast(arquivada ? "Campanha arquivada" : "Campanha de volta ao quadro");
    if (arquivada && estado.sel === id && !estado.arquivadas) fecharDetalhe();
  } catch (e) {
    toast(e.message, "erro");
  }
  await carregar(true);
}

async function excluir(id) {
  const c = estado.quadro?.campanhas.find((x) => x.id === id) || estado.detalhe?.campanha;
  if (!confirm(`Excluir a campanha “${c?.nome || id}”? Não dá para desfazer (para só tirar do quadro, use Arquivar).`)) return;
  try {
    await api("/api/gestao/campanha/excluir", { json: { id } });
    toast("Campanha excluída");
    if (estado.sel === id) fecharDetalhe();
  } catch (e) {
    toast(e.message, "erro");
  }
  await carregar(true);
}

// ---------- andamento ----------
function desenharDetalhe() {
  const alvo = raiz.querySelector("#g-detalhe");
  const d = estado.detalhe;
  if (!d) { alvo.innerHTML = ""; return; }
  const c = d.campanha, a = d.andamento, m = METRICAS[c.metrica];
  const filtrosTxt = textoFiltros(c.filtros);
  const pergunta = `Como está o andamento dos vendedores na campanha #${c.id} “${c.nome}”?`;
  const cab = `
  <section class="cartao secao camp-detalhe entra" style="--i:0;--c:${m.cor}">
    <div class="cartao-cab">
      <div>
        <h2>${icone(m.icone)}${esc(c.nome)}</h2>
        <p class="sub">${esc(periodoTexto(c.inicio, c.fim))} · ${esc(m.nome)}: ${esc(m.descricao)} · criada por ${esc(c.criada_por_nome)}</p>
      </div>
      <div class="camp-acoes">
        ${ctx.assistente ? `<a class="btn" href="#/assistente?q=${encodeURIComponent(pergunta)}" title="Abre o Assistente com a pergunta pronta">${icone("conversa")}<span>Perguntar ao Assistente</span></a>` : ""}
        <button class="btn" type="button" data-editar>${icone("lapis")}<span>Editar</span></button>
        <button class="btn icone" type="button" data-arquivar="${c.arquivada ? "0" : "1"}" title="${c.arquivada ? "Tirar do arquivo" : "Arquivar"}" aria-label="${c.arquivada ? "Tirar do arquivo" : "Arquivar"}">${icone("arquivo")}</button>
        <button class="btn icone perigo" type="button" data-excluir title="Excluir" aria-label="Excluir a campanha">${icone("lixeira")}</button>
        <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar o andamento">${icone("x")}</button>
      </div>
    </div>
    <div class="camp-chips">
      <span class="chip" style="--c:${COLUNAS.find((x) => x.id === c.status).cor}"><span class="ponto-coluna"></span>${esc(COLUNAS.find((x) => x.id === c.status).nome)}</span>
      ${filtrosTxt.length ? filtrosTxt.map((t) => `<span class="chip">${icone("funil")}${esc(t)}</span>`).join("") : `<span class="chip">${icone("funil")}todos os produtos e clientes</span>`}
      ${c.premiacao ? `<span class="chip laranja">${icone("trofeu")}${esc(c.premiacao)}</span>` : ""}
    </div>
    ${c.descricao ? `<p class="camp-descricao">${esc(c.descricao)}</p>` : ""}
    ${c.sugestao && !c.arquivada ? `<p class="usu-nota aviso-nota camp-sugestao-linha">${icone("alerta")}<span>${esc(c.sugestao.texto)}: a campanha está em
      <b>${esc(COLUNAS.find((x) => x.id === c.status).nome)}</b>.</span>
      <button class="btn" type="button" data-mover="${c.sugestao.status}">${icone("seta")}Mover para ${esc(COLUNAS.find((x) => x.id === c.sugestao.status).nome)}</button></p>` : ""}
  </section>`;
  if (!a) {
    alvo.innerHTML = cab + `<div class="aviso">${icone("alerta")}<span>${esc(d.aviso || "Sem dados de vendas para calcular o andamento.")}</span></div>`;
    return;
  }
  alvo.innerHTML = cab + kpisAndamento(c, a) + rankingAndamento(c, a) + tabelaAndamento(c, a);
  animarEntradas(alvo);
  ligarTooltips(alvo);
}

function aoClicarDetalhe(e) {
  const b = e.target.closest("button");
  const c = estado.detalhe?.campanha;
  if (!b || !c) return;
  if (b.hasAttribute("data-fechar")) return fecharDetalhe();
  if (b.hasAttribute("data-editar")) return editar(c.id);
  if (b.dataset.arquivar) return arquivar(c.id, b.dataset.arquivar === "1");
  if (b.hasAttribute("data-excluir")) return excluir(c.id);
  if (b.dataset.mover) return mover(c.id, b.dataset.mover, null);
}

function kpi(i, ic, rotulo, valor, meta, cor = "var(--acento)") {
  return `<article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${esc(rotulo)}</span></div>
    <div class="kpi-corpo"><div><div class="kpi-valor">${valor}</div><div class="kpi-meta">${meta}</div></div></div></article>`;
}

function kpisAndamento(c, a) {
  const t = a.total, m = METRICAS[c.metrica], u = a.unidade;
  const v = (x, curto) => esc(valorMetrica(c.metrica, x, u, curto));
  const distintos = t.distintos != null && t.distintos !== t.realizado
    ? ` · ${esc(valorMetrica(c.metrica, t.distintos, u))} sem repetir entre vendedores` : "";
  const cards = [kpi(1, m.icone, "Realizado", v(t.realizado, true),
    `${a.periodo.ate ? `até ${fmt.data(a.periodo.ate)}` : "a campanha ainda não começou"}${distintos}`, m.cor)];
  if (a.situacao === "futuro") {
    cards.push(kpi(2, "alvo", "Meta da campanha", t.meta ? v(t.meta, true) : "Sem meta",
      t.meta ? `soma das metas de ${plural(t.com_meta, "vendedor", "vendedores")}` : "vale o ranking", "var(--s-ritmo)"));
    cards.push(kpi(3, "pessoas", "Vendedores", fmt.num(t.vendedores), "participando da campanha", "var(--ok-forte)"));
  } else if (t.meta) {
    cards.push(kpi(2, "alvo", "Atingido", fmt.pct(t.pct),
      `${chipStatus(t.status)} da meta de ${v(t.meta, true)}${a.situacao === "aberto" && t.esperado != null ? ` · pelo ritmo, o esperado até agora é ${v(t.esperado, true)}` : ""}`, corStatus(t.status)));
    cards.push(kpi(3, "estrela", "Vendedores na meta", `${t.bateram} <small class="fraco">de ${t.com_meta}</small>`,
      t.com_meta < t.vendedores ? `${plural(t.vendedores - t.com_meta, "vendedor", "vendedores")} sem meta (só ranking)` : "todos com meta", "var(--ok-forte)"));
  } else {
    const lider = a.vendedores[0];
    cards.push(kpi(2, "ranking", "Liderando", lider && lider.realizado ? esc(lider.nome) : "—",
      lider && lider.realizado ? v(lider.realizado) : "ninguém vendeu ainda"));
    cards.push(kpi(3, "pessoas", "Vendedores", fmt.num(t.vendedores), "campanha sem meta: vale o ranking", "var(--ok-forte)"));
  }
  const cal = Object.entries(a.calendarios);
  const uteis = cal.map(([r, x]) => `${cal.length > 1 ? `${r}: ` : ""}${fmt.dias(x.dias_uteis)}`).join(" · ");
  if (a.situacao === "aberto") {
    const dias = cal.map(([r, x]) => `${cal.length > 1 ? `<small class="fraco">${r}</small> ` : ""}${fmt.dias(x.dias_restantes)}`).join(" ");
    cards.push(kpi(4, "calendario", "Dias úteis restantes", dias,
      `de ${uteis} no período · ritmo esperado: ${cal.map(([, x]) => fmt.pct(x.ritmo, 0)).join(" / ")}`, "var(--s-fat)"));
  } else {
    const futuro = a.situacao === "futuro";
    cards.push(kpi(4, "calendario", futuro ? "Começa em" : "Encerrada em", fmt.dataCurta(futuro ? c.inicio : c.fim),
      `${esc(periodoTexto(c.inicio, c.fim))} · ${uteis} dias úteis`, "var(--s-fat)"));
  }
  const ocultos = a.ocultos ? `<p class="usu-nota">${icone("info")}<span>${plural(a.ocultos, "vendedor da campanha está", "vendedores da campanha estão")} fora do seu acesso e não ${a.ocultos === 1 ? "aparece" : "aparecem"} aqui.</span></p>` : "";
  return `<section class="kpis n4 secao">${cards.join("")}</section>${ocultos}`;
}

// Barras por vendedor: % da meta (com o ritmo esperado e os 100%) ou, sem meta, o realizado comparado ao maior.
function rankingAndamento(c, a) {
  const itens = a.vendedores;
  if (!itens.length || a.situacao === "futuro") return "";
  const comMeta = itens.some((v) => v.meta);
  const u = a.unidade;
  const max = comMeta ? Math.min(Math.max(1.1, ...itens.map((v) => v.pct || 0)), 2) * 1.04
    : Math.max(...itens.map((v) => v.realizado), 1) * 1.04;
  const pos = (x) => `${(Math.min(x, max) / max) * 100}%`;
  const linhas = itens.map((v, i) => {
    const st = STATUS[v.status] || STATUS.sem_meta;
    const ritmo = comMeta && a.situacao === "aberto" ? a.calendarios[v.regiao]?.ritmo : null;
    const tt = `<div class='tt-t'>${esc(v.nome)}</div>` + linhaTT("Realizado", esc(valorMetrica(c.metrica, v.realizado, u))) +
      (v.meta ? linhaTT("Meta", esc(valorMetrica(c.metrica, v.meta, u))) + linhaTT("Atingido", fmt.pct(v.pct)) + linhaTT("Situação", st.rotulo) : "");
    const largura = comMeta ? pos(v.pct || 0) : pos(v.realizado);
    return `<div class="rank-linha" data-tt="${esc(tt)}" tabindex="0">
      <span class="rank-pos ${i < 3 && v.realizado ? "top" : ""}">${i + 1}º</span>
      <span class="rank-nome" title="${esc(v.nome)}">${esc(v.nome)}</span>
      <span class="rank-trilho">
        ${ritmo ? `<span class="rank-marca" style="left:${pos(ritmo)}"></span>` : ""}
        ${comMeta ? `<span class="rank-marca cem" style="left:${pos(1)}"></span>` : ""}
        <span class="rank-barra ${v.status === "batida" ? "batida" : ""}" style="--cor-barra:${comMeta ? corStatus(v.status) : METRICAS[c.metrica].cor}" data-largura="${largura}"></span>
      </span>
      <span class="rank-val"><b>${v.meta ? fmt.pct(v.pct) : esc(valorMetrica(c.metrica, v.realizado, u, true))}</b><span>${v.meta ? esc(valorMetrica(c.metrica, v.realizado, u, true)) : "sem meta"}</span></span>
    </div>`;
  }).join("");
  const escala = comMeta ? `<div class="rank-escala"><span></span><span></span><div class="faixa-e"><span style="left:${pos(1)}">meta 100%</span></div><span></span></div>` : "";
  return `<section class="cartao secao entra" style="--i:5">
    <div class="cartao-cab"><div><h3>${icone("ranking")}Ranking dos vendedores</h3>
      <p class="sub">${comMeta ? "% da meta de cada um; o traço tracejado é o ritmo esperado até a data dos dados" : "quem mais vendeu na campanha"}</p></div></div>
    ${escala}<div class="ranking">${linhas}</div></section>`;
}

function tabelaAndamento(c, a) {
  if (!a.vendedores.length) return `<div class="cartao secao vazio">${icone("pessoas")}<p>Nenhum vendedor da campanha no seu acesso.</p></div>`;
  const u = a.unidade;
  const v = (x) => esc(valorMetrica(c.metrica, x, u));
  const aberto = a.situacao === "aberto";
  const linhas = a.vendedores.map((r, i) => `<tr style="--i:${i}">
    <td class="nome-v">${esc(r.nome)}<small>código ${r.id} · ${esc(r.equipe || "")}</small></td>
    <td>${v(r.realizado)}</td>
    <td>${r.meta ? v(r.meta) : '<span class="fraco">sem meta</span>'}${r.meta_individual ? ' <span class="fraco" title="meta ajustada para este vendedor">*</span>' : ""}</td>
    <td>${r.meta ? `<span class="pct-cel"><span class="mini"><i style="width:${Math.min(100, (r.pct || 0) * 100)}%;--c:${corStatus(r.status)}"></i></span><b>${fmt.pct(r.pct)}</b></span>` : "—"}</td>
    <td>${r.falta != null ? v(r.falta) : "—"}</td>
    ${aberto ? `<td>${r.falta_por_dia != null ? v(r.falta_por_dia) : "—"}</td><td>${r.projecao != null ? v(r.projecao) : "—"}</td>` : ""}
    <td>${a.situacao === "futuro" ? chipStatus("sem_meta", "Não começou") : chipStatus(r.status)}</td></tr>`).join("");
  const individuais = a.vendedores.some((r) => r.meta_individual)
    ? `<p class="usu-nota">${icone("info")}<span>* meta ajustada para o vendedor; os demais seguem a meta padrão de ${v(c.meta_padrao)}.</span></p>` : "";
  return `<section class="cartao secao entra" style="--i:6">
    <div class="cartao-cab"><div><h3>${icone("pessoas")}Andamento por vendedor</h3>
      <p class="sub">${esc(METRICAS[c.metrica].nome)} de ${esc(periodoTexto(c.inicio, c.fim))}${a.periodo.ate && a.periodo.ate !== c.fim ? `, com dados até ${fmt.data(a.periodo.ate)}` : ""}</p></div></div>
    <div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>Vendedor</th><th>Realizado</th><th>Meta</th><th>Atingido</th><th>Falta</th>
        ${aberto ? "<th>Falta por dia útil</th><th>Projeção</th>" : ""}<th>Situação</th></tr></thead>
      <tbody>${linhas}</tbody>
    </table></div>${individuais}</section>`;
}

// ---------- formulário (criar e editar) ----------
function criarJanela() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo camp-dialogo";
  dlg.setAttribute("aria-labelledby", "cf-titulo");
  document.body.appendChild(dlg);
  dlg.addEventListener("cancel", (e) => {
    if (dlg.querySelector(".multi-painel:not([hidden])")) { e.preventDefault(); return; } // o Esc era da lista
    if (formMudou() && !confirm("Descartar o que foi preenchido nesta campanha?")) e.preventDefault();
  });
  dlg.addEventListener("close", () => { form = null; });
}

async function editar(id) {
  const c = estado.quadro?.campanhas.find((x) => x.id === id) || (estado.detalhe?.campanha.id === id ? estado.detalhe.campanha : null);
  if (!c) return;
  abrirFormulario({ id: c.id, dados: c });
}

async function abrirRascunho(uuid) {
  if (naGestao()) history.replaceState(null, "", estado.sel ? `#/gestao?c=${estado.sel}` : "#/gestao");
  try {
    const r = await api(`/api/gestao/rascunho?id=${encodeURIComponent(uuid)}`);
    if (r.campanha) {
      toast(`Este rascunho já virou a campanha “${r.campanha.nome}”`);
      return selecionar(r.campanha.id, { rolar: true });
    }
    abrirFormulario({ dados: r.rascunho, rascunho: r.rascunho.id, nomes: r.rascunho.nomes });
  } catch (e) {
    toast(e.message, "erro");
  }
}

// dados: a campanha (editar), o rascunho do Assistente ou nada (nova). nomes: nomes que o rascunho já trouxe.
async function abrirFormulario({ id = null, dados = null, rascunho = null, nomes = null } = {}) {
  if (dlg.open && formMudou() && !confirm("Descartar o que foi preenchido nesta campanha?")) return;
  const inicio = hoje();
  filtros = {};
  const d = dados || {
    nome: "", descricao: "", premiacao: "", inicio, fim: fimDoMes(inicio), metrica: "faturamento", filtros: {},
    meta_padrao: 0, vendedores: [],
  };
  form = {
    id, rascunho, nomes: nomes || {},
    metrica: d.metrica,
    vendedores: new Map((d.vendedores || []).map((v) => [v.id, v.meta])),
  };
  dlg.innerHTML = `<form id="cf-form" novalidate>
    <h2 id="cf-titulo">${icone("quadro")}${id ? "Editar campanha" : rascunho ? "Rascunho do Assistente" : "Nova campanha"}</h2>
    <p class="sub">${rascunho ? "Confira o que o Assistente montou e ajuste se quiser; a campanha só é criada quando você clicar em Criar." : "Os números saem das vendas do ERP, com as mesmas regras das metas."}</p>
    <div class="cf-grade">
      <label class="campo-form largo"><span>Nome da campanha</span><input name="nome" maxlength="120" required value="${esc(d.nome)}" placeholder="Ex.: Requeijão BA — novembro"></label>
      <label class="campo-form"><span>Início</span><input type="date" name="inicio" required value="${esc(d.inicio)}"></label>
      <label class="campo-form"><span>Fim</span><input type="date" name="fim" required value="${esc(d.fim)}"></label>
      <div class="largo"><span class="cf-rotulo">O que a campanha mede</span>
        <div class="cf-metricas" role="radiogroup" aria-label="Métrica">${Object.entries(METRICAS).map(([k, m]) => `
          <button type="button" class="visao-op ${k === d.metrica ? "ativo" : ""}" role="radio" aria-checked="${k === d.metrica}" data-metrica="${k}">
            ${icone(m.icone)}<span><b>${esc(m.nome)}</b><small>${esc(m.descricao)}</small></span></button>`).join("")}</div></div>
      <div class="largo"><span class="cf-rotulo">Produtos e clientes que contam <small>(nada escolhido = tudo)</small></span>
        <div class="filtros cf-filtros">${FILTROS.map((f) => `<div id="cf-f-${f.id}"></div>`).join("")}</div>
        <p class="usu-nota" id="cf-dica-filtro"></p></div>
      <label class="campo-form"><span>Meta padrão por vendedor <small id="cf-unidade"></small></span>
        <input type="number" name="meta_padrao" min="0" step="any" inputmode="decimal" value="${d.meta_padrao || ""}" placeholder="0 = sem meta, só ranking"></label>
      <label class="campo-form"><span>Premiação <small>(opcional)</small></span><input name="premiacao" maxlength="2000" value="${esc(d.premiacao)}" placeholder="Ex.: vale-compras de R$ 300"></label>
      <div class="largo"><span class="cf-rotulo">Vendedores <small id="cf-n-vend"></small></span>
        <div class="barra-ferramentas usu-busca">
          <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cf-busca-v" type="search" placeholder="Buscar vendedor ou código"></label>
          <span id="cf-equipes"></span>
          <button class="btn" type="button" id="cf-marcar">Marcar os da lista</button>
          <button class="btn" type="button" id="cf-desmarcar">Desmarcar todos</button>
        </div>
        <div class="cf-vendedores" id="cf-vendedores"><div class="esqueleto" style="height:120px"></div></div>
        <p class="usu-nota">${icone("info")}<span>Deixe a meta do vendedor em branco para usar a padrão; 0 deixa o vendedor sem meta (só no ranking).</span></p>
      </div>
      <label class="campo-form largo"><span>Descrição <small>(opcional)</small></span><textarea name="descricao" rows="2" maxlength="2000" placeholder="Objetivo e regras da campanha">${esc(d.descricao)}</textarea></label>
    </div>
    <p class="form-erro" role="alert" hidden></p>
    <div class="dialogo-acoes">
      <button class="btn" type="button" data-cancelar>Cancelar</button>
      <button class="btn primario" type="submit">${icone(id ? "disco" : "mais")}${id ? "Salvar alterações" : "Criar campanha"}</button>
    </div></form>`;
  const f = dlg.querySelector("form");
  f.addEventListener("submit", (e) => { e.preventDefault(); salvar(); });
  f.querySelector("[data-cancelar]").addEventListener("click", () => {
    if (formMudou() && !confirm("Descartar o que foi preenchido nesta campanha?")) return;
    dlg.close();
  });
  f.querySelectorAll("[data-metrica]").forEach((b) => b.addEventListener("click", () => {
    form.metrica = b.dataset.metrica;
    f.querySelectorAll("[data-metrica]").forEach((x) => { x.classList.toggle("ativo", x === b); x.setAttribute("aria-checked", x === b); });
    dicas();
  }));
  f.querySelector('[name="inicio"]').addEventListener("change", (e) => {
    const fim = f.querySelector('[name="fim"]');
    if (!fim.value || fim.value < e.target.value) fim.value = fimDoMes(e.target.value);
  });
  if (!dlg.open) dlg.showModal();
  f.querySelector('[name="nome"]').focus();
  const cat = await carregarCatalogo();
  if (!form || dlg.querySelector("form") !== f) return; // fechou ou abriu outra enquanto o catálogo vinha
  if (!cat) {
    erroForm(`Não foi possível carregar vendedores e produtos: ${estado.erroCatalogo}`);
    f.querySelector("#cf-vendedores").innerHTML = "";
  } else {
    montarFiltros(f, d.filtros || {}, cat);
    montarVendedores(f, cat);
  }
  form.orig = JSON.stringify(coletar());
  dicas();
}

function fimDoMes(iso) {
  const [a, m] = iso.split("-").map(Number);
  return new Date(Date.UTC(a, m, 0)).toISOString().slice(0, 10);
}

// Valores de texto (linhas, UFs…) vão para a lista de seleção por posição: ela trabalha com números.
function opcoesFiltro(id, cat) {
  if (id === "produtos") {
    return cat.produtos.map((p) => ({ id: p.id, nome: p.nome, grupo: p.grupo === "mussarela" ? "mussarela" : `cat:${p.categoria || ""}`,
      detalhe: `código ${p.id}${p.unidade ? ` · ${p.unidade}` : ""}${p.linha ? ` · ${p.linha}` : ""}` }));
  }
  const valores = { linhas: cat.linhas, categorias: cat.categorias, grupos: cat.grupos, ufs: cat.ufs, segmentos: cat.segmentos }[id];
  return valores.map((v, i) => ({ id: i, nome: id === "grupos" ? NOME_GRUPO[v] || v : v, valor: v }));
}

function montarFiltros(f, atuais, cat) {
  filtros = {};
  const grupos = [{ id: "mussarela", nome: "Mussarela" }, ...cat.categorias.map((c) => ({ id: `cat:${c}`, nome: c })), { id: "cat:", nome: "Demais produtos" }];
  for (const def of FILTROS) {
    const itens = opcoesFiltro(def.id, cat);
    const marcados = def.id === "produtos"
      ? (atuais.produtos || [])
      : (atuais[def.id] || []).map((v) => itens.findIndex((i) => i.valor === v)).filter((i) => i >= 0);
    // produto escolhido que não vendeu nos últimos 12 meses continua na lista, para poder tirar
    if (def.id === "produtos") {
      for (const p of marcados) if (!itens.some((i) => i.id === p)) itens.push({ id: p, nome: nomeProduto(p, form.nomes.produtos), grupo: "cat:", detalhe: `código ${p}` });
    }
    filtros[def.id] = { itens, ms: multiSelecao(f.querySelector(`#cf-f-${def.id}`), {
      rotulo: def.rotulo, icone: def.icone, todos: def.todos, plural: def.plural, busca: `Buscar ${def.rotulo.toLowerCase()}`,
      semBusca: def.semBusca, classe: "curto", itens, selecionados: marcados, nomesAte: 2,
      grupos: def.id === "produtos" ? grupos : undefined, aoAplicar: dicas,
    }) };
  }
}

function valoresFiltros() {
  const saida = {};
  for (const [id, { itens, ms }] of Object.entries(filtros)) {
    const v = ms.valor();
    if (!v.length) continue;
    saida[id] = id === "produtos" ? v : v.map((i) => itens.find((x) => x.id === i)?.valor).filter((x) => x != null);
  }
  return saida;
}

function montarVendedores(f, cat) {
  const conhecidos = new Map(cat.vendedores.map((v) => [v.id, v]));
  const lista = [...cat.vendedores];
  for (const id of form.vendedores.keys()) {
    if (!conhecidos.has(id)) {
      lista.push({ id, nome: form.nomes.vendedores?.[id] || estado.detalhe?.andamento?.vendedores.find((v) => v.id === id)?.nome || `Vendedor ${id}`,
                   rotulo_equipe: "sem venda em 12 meses", equipe: "" });
    }
  }
  const alvo = f.querySelector("#cf-vendedores");
  if (!lista.length) {
    alvo.innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Seu acesso na Gestão não tem vendedores. Fale com o administrador.</span></p>`;
    return;
  }
  alvo.innerHTML = lista.map((v) => {
    const marcado = form.vendedores.has(v.id);
    const meta = form.vendedores.get(v.id);
    return `<div class="cf-vend ${marcado ? "marcado" : ""}" data-id="${v.id}" data-equipe="${esc(v.equipe)}" data-busca="${esc(`${v.nome} ${v.nome_erp || ""} ${v.id}`.toLowerCase())}">
      <label class="vend-op"><input type="checkbox" ${marcado ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(v.rotulo_equipe || EQUIPE[v.equipe] || "")}${v.inativo ? " · inativo no ERP" : ""}</small></span></label>
      <input class="cf-meta-v" type="number" min="0" step="any" inputmode="decimal" placeholder="padrão" aria-label="Meta de ${esc(v.nome)}"
        value="${meta != null ? meta : ""}" ${marcado ? "" : "disabled"}>
    </div>`;
  }).join("");
  const equipes = [...new Set(cat.vendedores.map((v) => v.equipe))].filter(Boolean);
  f.querySelector("#cf-equipes").innerHTML = equipes.map((e) => `<button class="btn" type="button" data-equipe="${esc(e)}" title="Marcar todos os vendedores ativos da equipe">${icone("pessoas")}${esc(EQUIPE[e] || e)}</button>`).join("");
  const marcar = (linha, sim) => {
    linha.classList.toggle("marcado", sim);
    linha.querySelector('input[type="checkbox"]').checked = sim;
    linha.querySelector(".cf-meta-v").disabled = !sim;
  };
  alvo.addEventListener("change", (e) => {
    if (e.target.type === "checkbox") { marcar(e.target.closest(".cf-vend"), e.target.checked); contarVendedores(); }
  });
  f.querySelector("#cf-busca-v").addEventListener("input", (e) => {
    const termo = e.target.value.trim().toLowerCase();
    alvo.querySelectorAll(".cf-vend").forEach((l) => { l.hidden = !!termo && !l.dataset.busca.includes(termo); });
  });
  f.querySelector("#cf-marcar").addEventListener("click", () => {
    alvo.querySelectorAll(".cf-vend:not([hidden])").forEach((l) => marcar(l, true));
    contarVendedores();
  });
  f.querySelector("#cf-desmarcar").addEventListener("click", () => {
    alvo.querySelectorAll(".cf-vend").forEach((l) => marcar(l, false));
    contarVendedores();
  });
  f.querySelectorAll("#cf-equipes [data-equipe]").forEach((b) => b.addEventListener("click", () => {
    alvo.querySelectorAll(`.cf-vend[data-equipe="${CSS.escape(b.dataset.equipe)}"]`).forEach((l) => {
      if (!conhecidos.get(Number(l.dataset.id))?.inativo) marcar(l, true);
    });
    contarVendedores();
  }));
  contarVendedores();
}

function contarVendedores() {
  const n = dlg.querySelectorAll(".cf-vend.marcado").length;
  const el = dlg.querySelector("#cf-n-vend");
  if (el) el.textContent = n ? `· ${plural(n, "marcado", "marcados")}` : "· nenhum marcado";
}

// Explica a unidade da meta e o cuidado com volume (quantidades só somam na mesma unidade).
function dicas() {
  if (!form) return;
  const f = dlg.querySelector("form");
  const un = f.querySelector("#cf-unidade");
  const dica = f.querySelector("#cf-dica-filtro");
  const m = form.metrica;
  let unidade = { faturamento: "(R$)", positivacao: "(clientes)", mix: "(produtos)" }[m] || "";
  let texto = "";
  if (m === "volume") {
    const escolhidos = filtros.produtos ? filtros.produtos.ms.valor() : [];
    const unidades = [...new Set((estado.catalogo?.produtos || []).filter((p) => escolhidos.includes(p.id)).map((p) => p.unidade))];
    unidade = unidades.length === 1 ? `(${unidades[0].toLowerCase()})` : "";
    texto = unidades.length > 1
      ? `Os produtos escolhidos têm unidades diferentes (${unidades.join(", ")}): numa campanha de volume use uma só.`
      : "Em volume, escolha produtos, linha, categoria ou grupo com uma unidade só (a quantidade não soma kg com unidade).";
  }
  un.textContent = unidade;
  dica.innerHTML = texto ? `${icone("info")}<span>${esc(texto)}</span>` : "";
  dica.hidden = !texto;
}

function coletar() {
  const f = dlg.querySelector("form");
  const val = (n) => f.querySelector(`[name="${n}"]`).value;
  const vendedores = [...f.querySelectorAll(".cf-vend.marcado")].map((l) => {
    const meta = l.querySelector(".cf-meta-v").value.trim();
    return { id: Number(l.dataset.id), meta: meta === "" ? null : Number(meta) };
  });
  return {
    nome: val("nome").trim(), inicio: val("inicio"), fim: val("fim"), metrica: form.metrica,
    filtros: Object.keys(filtros).length ? valoresFiltros() : {}, meta_padrao: Number(val("meta_padrao") || 0),
    premiacao: val("premiacao").trim(), descricao: val("descricao").trim(),
    vendedores: f.querySelector(".cf-vend") ? vendedores : [...form.vendedores].map(([id, meta]) => ({ id, meta })),
  };
}

function formMudou() {
  return !!(form && dlg?.open && form.orig && JSON.stringify(coletar()) !== form.orig);
}

function erroForm(msg) {
  const el = dlg.querySelector(".form-erro");
  el.textContent = msg.charAt(0).toUpperCase() + msg.slice(1);
  el.hidden = !msg;
  if (msg) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function salvar() {
  const dados = coletar();
  if (!dados.nome) return erroForm("dê um nome à campanha");
  if (!dados.inicio || !dados.fim) return erroForm("escolha o início e o fim");
  if (dados.fim < dados.inicio) return erroForm("o fim é antes do início");
  if (!dados.vendedores.length) return erroForm("marque os vendedores da campanha");
  const btn = dlg.querySelector('button[type="submit"]');
  btn.disabled = true;
  erroForm("");
  try {
    const r = form.id
      ? await api("/api/gestao/campanha/editar", { json: { id: form.id, campanha: dados } })
      : await api("/api/gestao/campanhas", { json: { campanha: dados, rascunho: form.rascunho } });
    toast(form.id ? "Campanha salva" : r.ja_existia ? "Esta campanha já tinha sido criada" : "Campanha criada");
    form = null;
    dlg.close();
    estado.detalhe = { campanha: r.campanha, andamento: r.andamento, aviso: r.aviso };
    estado.sel = r.campanha.id;
    atualizarUrl();
    desenharDetalhe();
    await carregar(true);
    raiz.querySelector("#g-detalhe").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    erroForm(e.message);
  } finally {
    btn.disabled = false;
  }
}
