// Página Gestão: campanhas de vendas num quadro (kanban), como no Bitrix. Cada card é uma campanha; arrastar muda a
// coluna (Planejada, Em andamento, Concluída) e, quando as datas dizem que ela já devia ter mudado, o card sugere.
// Clicar num card mostra embaixo o andamento de cada vendedor. A conta é toda no servidor (bi/indicadores.py, os
// mesmos números que o Assistente dá), que manda junto o descritor do indicador (nome, formato, como ler a meta):
// a página só formata. Criar e editar é numa janela; o rascunho que o Assistente monta chega por
// #/gestao?rascunho=<id> e abre a janela preenchida. Cada pessoa vê as campanhas que criou (o administrador, todas).
import { api, esc, fmt, icone, chipStatus, corStatus, STATUS, animarEntradas, ligarTooltips, linhaTT, toast } from "./util.js";
import { multiSelecao } from "./multiselecao.js";

export const COLUNAS = [
  { id: "planejada", nome: "Planejada", cor: "var(--s-ritmo)", vazio: "Campanhas que ainda vão começar" },
  { id: "andamento", nome: "Em andamento", cor: "var(--laranja)", vazio: "Arraste para cá as que já começaram" },
  { id: "concluida", nome: "Concluída", cor: "var(--ok-forte)", vazio: "As encerradas ficam aqui" },
];
// Os tipos de campanha (bi/indicadores.py TIPOS) e os blocos da Personalizada.
export const TIPOS = {
  positivacao: { nome: "Positivação", icone: "pessoas", cor: "var(--k-cli)", descricao: "clientes distintos com venda; dá para contar só os recuperados ou os novos" },
  mix_medio: { nome: "Mix médio", icone: "etiqueta", cor: "var(--s-out)", descricao: "produtos da campanha levados por cliente positivado (média)" },
  efetividade: { nome: "Efetividade", icone: "alvo", cor: "var(--s-ritmo)", descricao: "pedidos ÷ visitas esperadas, pelos dias de atendimento das áreas" },
  frequencia: { nome: "Frequência", icone: "calendario", cor: "var(--laranja)", descricao: "semanas com compra por cliente positivado (média)" },
  preco_medio: { nome: "Preço médio", icone: "moeda", cor: "var(--s-mus)", descricao: "preço de cada produto contra um preço-alvo" },
  personalizada: { nome: "Personalizada", icone: "ajustes", cor: "var(--s-fat)", descricao: "monte: faturamento, volume, clientes ou mix, no total, por cliente ou crescimento" },
};
const MEDIDAS = {
  faturamento: { nome: "Faturamento (R$)", icone: "moeda", cor: "var(--s-fat)", formas: ["total", "por_cliente", "crescimento"] },
  volume: { nome: "Volume (quantidade)", icone: "caixa", cor: "var(--s-mus)", formas: ["total", "por_cliente", "crescimento"] },
  clientes: { nome: "Clientes positivados", icone: "pessoas", cor: "var(--k-cli)", formas: ["total", "pct_carteira", "crescimento"] },
  produtos: { nome: "Mix (produtos distintos)", icone: "etiqueta", cor: "var(--s-out)", formas: ["total"] },
};
const FORMAS = { total: "Total no período", por_cliente: "Por cliente positivado", pct_carteira: "% da carteira que comprou", crescimento: "Crescimento sobre outro período" };
const COMPARAR = { periodo_anterior: "O período anterior", ano_anterior: "O mesmo período do ano anterior" };
const BASES = { todos: "Todos os clientes", novos: "Só clientes novos (sem compra antes do início)", recuperados: "Só clientes recuperados",
                nunca_compraram: "Quem nunca comprou os produtos da campanha", ja_compraram: "Quem já comprava os produtos da campanha" };
const LEGADOS = { faturamento: ["faturamento", "total"], volume: ["volume", "total"], mix: ["produtos", "total"] };
const ABERTURAS = { area: "Área comercial", segmento: "Segmento", produto: "Produto" };
const FILTROS_PRODUTO = ["produtos", "linhas", "categorias", "grupos"];
const FILTROS = [
  { id: "produtos", rotulo: "Produtos", icone: "caixa", todos: "Todos os produtos", plural: "produtos" },
  { id: "linhas", rotulo: "Linhas", icone: "etiqueta", todos: "Todas as linhas", plural: "linhas" },
  { id: "categorias", rotulo: "Categorias", icone: "funil", todos: "Todas as categorias", plural: "categorias" },
  { id: "grupos", rotulo: "Grupo", icone: "queijo", todos: "Mussarela e outras", plural: "grupos", semBusca: true },
  { id: "ufs", rotulo: "UF do cliente", icone: "mapa", todos: "Todas as UFs", plural: "UFs", semBusca: true },
  { id: "segmentos", rotulo: "Segmentos", icone: "pessoas", todos: "Todos os segmentos", plural: "segmentos" },
  { id: "areas", rotulo: "Áreas comerciais", icone: "mapa", todos: "Todas as áreas", plural: "áreas" },
];
const NOME_GRUPO = { mussarela: "Mussarela", outras: "Outras linhas" };
const EQUIPE = { ES: "ES", BA: "BA", EDIR: "Edir", OCULTO: "Outros" };

let ctx = null, raiz = null, ligado = false;
const estado = { quadro: null, catalogo: null, erroCatalogo: null, sel: null, detalhe: null, todas: false,
                 arquivadas: false, busca: "", pedido: 0, pedidoSel: 0, naPagina: false, abrir: null };
let dlg = null, form = null, filtros = {}, precos = null;

// ---------- apoio ----------
// Ícone e cor do card: o do tipo ou, na Personalizada, o da medida.
export function visual(ind) {
  return (ind?.tipo === "personalizada" ? MEDIDAS[ind.medida] : TIPOS[ind?.tipo]) || { icone: "quadro", cor: "var(--acento)" };
}

// O descritor de uma campanha ou rascunho de antes dos tipos novos (faturamento, volume, mix, positivação).
export function descritorLegado(r) {
  const [medida, forma] = LEGADOS[r.metrica] || [];
  if (medida) {
    return { tipo: "personalizada", medida, forma, comportamento: "soma", meta_em_pct: false, sufixo: "", casas: 0, unidade: r.unidade || "",
             nome: { faturamento: "Faturamento", volume: "Volume", produtos: "Mix de produtos" }[medida],
             formato: { faturamento: "moeda", volume: "quantidade", produtos: "produtos" }[medida] };
  }
  return { tipo: r.metrica, nome: TIPOS[r.metrica]?.nome || r.metrica, formato: r.metrica === "positivacao" ? "clientes" : "razao",
           comportamento: "soma", meta_em_pct: false, sufixo: "", casas: 0, unidade: "" };
}

// Valor no formato do indicador (curto: para cards e barras). Percentuais vêm em fração (0,8 = 80%).
export function valorIndicador(ind, v, unidade = "", curto = false) {
  if (v == null || isNaN(v)) return "—";
  const suf = !curto && ind.sufixo ? ` ${ind.sufixo}` : "";
  switch (ind.formato) {
    case "moeda": return (ind.casas && !curto ? `R$ ${fmt.num(v, 2)}` : curto ? fmt.moedaC(v) : fmt.moeda(v)) + suf;
    case "quantidade": {
      const u = (unidade || ind.unidade || "").toLowerCase();
      return `${fmt.num(v, Math.abs(v) >= 100 ? 0 : 1)}${u ? " " + u : ""}${suf}`;
    }
    case "pct": return fmt.pct(v);
    case "razao": return `${fmt.num(v, ind.casas || 2)}${suf}`;
    default: {
      const n = Math.round(v);
      const nome = ind.formato === "clientes" ? (n === 1 ? "cliente" : "clientes") : (n === 1 ? "produto" : "produtos");
      return `${fmt.num(n)} ${nome}`;
    }
  }
}

// A meta como a pessoa digitou (percentual em pontos: 80 = 80%; crescimento: +10%).
export function metaDigitada(ind, v, unidade = "") {
  if (!ind.meta_em_pct) return valorIndicador(ind, v, unidade);
  return ind.forma === "crescimento" ? `+${fmt.num(v, 1)}%` : `${fmt.num(v, 1)}%`;
}

// Contagens (pedidos, visitas, clientes) e, na venda por cliente e no preço médio, valores em R$.
function valorParte(ind, v) {
  if (v == null) return "—";
  return ind.medida === "faturamento" || ind.tipo === "preco_medio" ? fmt.moeda(v) : fmt.num(v, 1);
}

const reais2 = (v) => "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Em médias e percentuais não há ritmo: a situação é contra a meta.
const ROTULO_TAXA = { no_ritmo: "Na meta", abaixo: "Abaixo da meta" };
const rotuloStatus = (ind, st) => (ind?.comportamento === "taxa" && ROTULO_TAXA[st]) || (STATUS[st] || STATUS.sem_meta).rotulo;
const chipInd = (ind, st) => chipStatus(st, rotuloStatus(ind, st));

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
  if (f.areas?.length) partes.push(`área ${lista(f.areas, 2)}`);
  return partes;
}

// Quem conta e com o que compara, para os chips e o rascunho do Assistente.
export function textoBase(ind) {
  const partes = [];
  if (ind.base && ind.base !== "todos" && ind.base_texto) partes.push(ind.base_texto);
  if (ind.forma === "crescimento" && ind.comparar) partes.push(`contra ${COMPARAR[ind.comparar]?.toLowerCase() || ind.comparar}`);
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
  container.querySelector("#g-detalhe").addEventListener("change", (e) => {
    const s = e.target.closest("select[data-abrir]");
    if (!s || !estado.sel) return;
    estado.abrir = s.value; // "" = não abrir
    selecionar(estado.sel);
  });
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
  if (mudou) estado.abrir = null; // a abertura escolhida vale para a campanha aberta
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
    const d = await api(`/api/gestao/campanha?id=${id}${estado.abrir != null ? `&abrir=${encodeURIComponent(estado.abrir)}` : ""}`);
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
      <p>Uma campanha acompanha, num período, um indicador de cada vendedor: positivação (inclusive de clientes
        recuperados), mix médio, efetividade, frequência, preço médio por produto ou um indicador montado por você
        (faturamento, volume, clientes, crescimento…). Crie aqui ou peça ao Assistente, por exemplo:
        <i>“crie uma campanha para recuperar padarias sem compra há 60 dias, equipe BA, em novembro”</i>.</p>
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
  const ind = c.indicador || descritorLegado(c);
  const m = visual(ind);
  const r = c.resumo;
  let progresso = "";
  if (r && r.meta) {
    progresso = `<div class="camp-barra" style="--c:${corStatus(r.status)}"><i data-largura="${Math.min(100, (r.pct || 0) * 100)}%"></i></div>
      <div class="camp-num"><span><b>${fmt.pct(r.pct)}</b> da meta</span><span>${r.bateram} de ${r.com_meta} ${ind.comportamento === "taxa" ? "na meta" : "bateram"}</span></div>`;
  } else if (r) {
    progresso = `<div class="camp-num"><span>${esc(valorIndicador(ind, r.distintos ?? r.realizado, r.unidade, true))}</span><span>só ranking</span></div>`;
  } else if (c.aviso) {
    progresso = `<p class="camp-num fraco" title="${esc(c.aviso)}">${icone("info")}sem números ainda</p>`;
  }
  const sug = c.sugestao && !c.arquivada
    ? `<button type="button" class="camp-sugestao" data-mover="${c.sugestao.status}" title="Mover para ${esc(COLUNAS.find((x) => x.id === c.sugestao.status).nome)}">${icone("alerta")}${esc(c.sugestao.texto)} · mover</button>` : "";
  const autor = estado.todas && !c.minha ? `<small class="camp-autor">${icone("usuario")}${esc(c.criada_por_nome)}</small>` : "";
  return `<article class="camp-card ${c.id === estado.sel ? "selecionada" : ""} ${c.arquivada ? "arquivada" : ""}" draggable="true"
      data-id="${c.id}" tabindex="0" style="--c:${m.cor}" aria-label="Campanha ${esc(c.nome)}">
    <div class="camp-topo">
      <span class="chip camp-metrica">${icone(m.icone)}${esc(ind.nome)}</span>
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
  const c = d.campanha, a = d.andamento;
  const ind = a?.indicador || c.indicador || descritorLegado(c), m = visual(ind);
  const filtrosTxt = [...textoFiltros(c.filtros), ...textoBase(ind)];
  const pergunta = `Como está o andamento dos vendedores na campanha #${c.id} “${c.nome}”?`;
  const cab = `
  <section class="cartao secao camp-detalhe entra" style="--i:0;--c:${m.cor}">
    <div class="cartao-cab">
      <div>
        <h2>${icone(m.icone)}${esc(c.nome)}</h2>
        <p class="sub">${esc(periodoTexto(c.inicio, c.fim))} · ${esc(ind.nome)}: ${esc(ind.descricao || "")} · criada por ${esc(c.criada_por_nome)}</p>
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
  const avisos = (a.avisos || []).map((t) => `<div class="aviso">${icone("alerta")}<span>${esc(t)}</span></div>`).join("");
  const preco = ind.tipo === "preco_medio";
  alvo.innerHTML = cab + avisos + kpisAndamento(c, a) + rankingAndamento(c, a)
    + (preco ? gradePrecos(c, a) : tabelaAndamento(c, a)) + aberturaAndamento(a);
  animarEntradas(alvo);
  ligarTooltips(alvo);
}

// A mesma conta aberta por área, segmento ou produto (os vendedores do acesso, juntos, sem meta).
function aberturaAndamento(a) {
  const ind = a.indicador;
  if (!ind.aberturas?.length || a.situacao === "futuro") return "";
  const ab = a.abertura;
  const opcoes = [["", "Não abrir"], ...ind.aberturas.map((k) => [k, ABERTURAS[k]])]
    .map(([k, n]) => `<option value="${k}" ${k === (ab?.por || "") ? "selected" : ""}>${esc(n)}</option>`).join("");
  const comPartes = !!ind.numerador;
  const linhas = (ab?.linhas || []).map((x, i) => `<tr style="--i:${i}">
    <td class="nome-v">${esc(x.nome)}</td><td>${esc(valorIndicador(ind, x.valor, a.unidade))}</td>
    ${comPartes ? `<td>${valorParte(ind, x.numerador)}</td><td>${valorParte(ind, x.denominador)}</td>` : ""}</tr>`).join("");
  return `<section class="cartao secao entra" style="--i:7">
    <div class="cartao-cab"><div><h3>${icone("funil")}Aberto por ${esc(ab ? ABERTURAS[ab.por].toLowerCase() : "…")}</h3>
      <p class="sub">os vendedores da campanha juntos, sem meta${ab?.mais ? ` · mostrando ${ab.linhas.length} de ${ab.linhas.length + ab.mais}` : ""}</p></div>
      <label class="campo"><select data-abrir aria-label="Abrir por" style="padding-left:14px">${opcoes}</select></label></div>
    ${ab ? `<div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>${esc(ABERTURAS[ab.por])}</th><th>${esc(ind.nome)}</th>${comPartes ? `<th>${esc(ind.numerador)}</th><th>${esc(ind.denominador)}</th>` : ""}</tr></thead>
      <tbody>${linhas || `<tr><td colspan="4" class="fraco">Nada no período.</td></tr>`}</tbody></table></div>`
      : `<p class="usu-nota">${icone("info")}<span>Escolha como abrir o resultado: por ${ind.aberturas.map((k) => ABERTURAS[k].toLowerCase()).join(", ")}.</span></p>`}
  </section>`;
}

// Preço médio: o preço de cada vendedor em cada produto, contra o preço-alvo.
function gradePrecos(c, a) {
  if (!a.vendedores.length) return `<div class="cartao secao vazio">${icone("pessoas")}<p>Nenhum vendedor da campanha no seu acesso.</p></div>`;
  const prods = a.produtos || [];
  const cor = (pct) => (pct == null ? "" : pct >= 1 ? "var(--ok)" : pct >= 0.9 ? "var(--atencao)" : "var(--ruim)");
  const cel = (p) => (p?.preco == null ? '<td class="fraco">—</td>'
    : `<td><b style="color:${cor(p.pct)}">${reais2(p.preco)}</b><small>${fmt.pct(p.pct)} · ${fmt.num(p.quantidade, 1)} ${esc((p.unidade || "").toLowerCase())}</small></td>`);
  const linhas = a.vendedores.map((v, i) => {
    const por = Object.fromEntries((v.produtos || []).map((p) => [p.id, p]));
    return `<tr style="--i:${i}"><td class="nome-v">${esc(v.nome)}<small>código ${v.id} · ${esc(v.equipe || "")}</small></td>
      ${prods.map((p) => cel(por[p.id])).join("")}
      <td>${v.realizado != null ? `<b>${fmt.pct(v.realizado)}</b>` : "—"}</td><td>${a.situacao === "futuro" ? chipStatus("sem_meta", "Não começou") : chipInd(a.indicador, v.status)}</td></tr>`;
  }).join("");
  return `<section class="cartao secao entra" style="--i:6">
    <div class="cartao-cab"><div><h3>${icone("moeda")}Preço médio por produto</h3>
      <p class="sub">venda líquida ÷ quantidade de cada vendedor, contra o preço-alvo; o índice compara o que vendeu com o que seria nos preços-alvo</p></div></div>
    <div class="tabela-rolagem"><table class="dados camp-grade">
      <thead><tr><th>Vendedor</th>${prods.map((p) => `<th title="${esc(p.nome)}">${esc(p.nome)}<small>alvo ${reais2(p.meta)}${p.unidade ? `/${esc(p.unidade.toLowerCase())}` : ""}</small></th>`).join("")}<th>Índice</th><th>Situação</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td class="nome-v">Total</td>${prods.map(cel).join("")}<td><b>${fmt.pct(a.total.realizado)}</b></td><td>${chipInd(a.indicador, a.total.status)}</td></tr></tfoot>
    </table></div></section>`;
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
  const t = a.total, ind = a.indicador, m = visual(ind), u = a.unidade;
  const v = (x, curto) => esc(valorIndicador(ind, x, u, curto));
  const taxa = ind.comportamento === "taxa";
  const extras = [];
  if (t.distintos != null && t.distintos !== t.realizado) extras.push(`${esc(valorIndicador(ind, t.distintos, u))} sem repetir entre vendedores`);
  if (ind.numerador && t.numerador != null) extras.push(`${valorParte(ind, t.numerador)} ${esc(ind.numerador.toLowerCase())} ÷ ${valorParte(ind, t.denominador)} ${esc(ind.denominador.toLowerCase())}`);
  if (ind.forma === "crescimento" && a.periodo_base) extras.push(`contra ${v(t.base, true)} de ${esc(periodoTexto(a.periodo_base.inicio, a.periodo_base.fim))}`);
  const cards = [kpi(1, m.icone, "Realizado", v(t.realizado, true),
    [a.periodo.ate ? `até ${fmt.data(a.periodo.ate)}` : "a campanha ainda não começou", ...extras].join(" · "), m.cor)];
  const quem = taxa ? "na meta" : "bateram";
  if (a.situacao === "futuro") {
    cards.push(kpi(2, "alvo", "Meta da campanha", t.meta ? v(t.meta, true) : "Sem meta",
      t.meta ? (taxa ? "meta de cada vendedor (média)" : `soma das metas de ${plural(t.com_meta, "vendedor", "vendedores")}`) : "vale o ranking", "var(--s-ritmo)"));
    cards.push(kpi(3, "pessoas", "Vendedores", fmt.num(t.vendedores), "participando da campanha", "var(--ok-forte)"));
  } else if (t.meta) {
    const ritmo = !taxa && a.situacao === "aberto" && t.esperado != null ? ` · pelo ritmo, o esperado até agora é ${v(t.esperado, true)}` : "";
    cards.push(kpi(2, "alvo", "Atingido", fmt.pct(t.pct),
      `${chipInd(ind, t.status)} da meta${taxa ? "" : " de"} ${v(t.meta, true)}${ritmo}`, corStatus(t.status)));
    cards.push(kpi(3, "estrela", `Vendedores ${quem}`, `${t.bateram} <small class="fraco">de ${t.com_meta}</small>`,
      t.com_meta < t.vendedores ? `${plural(t.vendedores - t.com_meta, "vendedor", "vendedores")} sem meta (só ranking)` : "todos com meta", "var(--ok-forte)"));
  } else {
    const lider = a.vendedores[0];
    const tem = lider && lider.realizado != null && lider.realizado !== 0;
    cards.push(kpi(2, "ranking", "Liderando", tem ? esc(lider.nome) : "—", tem ? v(lider.realizado) : "ninguém vendeu ainda"));
    cards.push(kpi(3, "pessoas", "Vendedores", fmt.num(t.vendedores), "campanha sem meta: vale o ranking", "var(--ok-forte)"));
  }
  const cal = Object.entries(a.calendarios);
  const uteis = cal.map(([r, x]) => `${cal.length > 1 ? `${r}: ` : ""}${fmt.dias(x.dias_uteis)}`).join(" · ");
  if (a.situacao === "aberto") {
    const dias = cal.map(([r, x]) => `${cal.length > 1 ? `<small class="fraco">${r}</small> ` : ""}${fmt.dias(x.dias_restantes)}`).join(" ");
    cards.push(kpi(4, "calendario", "Dias úteis restantes", dias,
      `de ${uteis} no período${taxa ? "" : ` · ritmo esperado: ${cal.map(([, x]) => fmt.pct(x.ritmo, 0)).join(" / ")}`}`, "var(--s-fat)"));
  } else {
    const futuro = a.situacao === "futuro";
    cards.push(kpi(4, "calendario", futuro ? "Começa em" : "Encerrada em", fmt.dataCurta(futuro ? c.inicio : c.fim),
      `${esc(periodoTexto(c.inicio, c.fim))} · ${uteis} dias úteis`, "var(--s-fat)"));
  }
  const ocultos = a.ocultos ? `<p class="usu-nota">${icone("info")}<span>${plural(a.ocultos, "vendedor da campanha está", "vendedores da campanha estão")} fora do seu acesso e não ${a.ocultos === 1 ? "aparece" : "aparecem"} aqui.</span></p>` : "";
  return `<section class="kpis n4 secao">${cards.join("")}</section>${ocultos}`;
}

// Barras por vendedor: % da meta (com o ritmo esperado e os 100%) ou, sem meta, o realizado comparado ao maior.
// Em médias e percentuais (taxa) não há ritmo: vale a meta direto.
function rankingAndamento(c, a) {
  const itens = a.vendedores;
  if (!itens.length || a.situacao === "futuro") return "";
  const ind = a.indicador, cor = visual(ind).cor;
  const comMeta = itens.some((v) => v.meta);
  const u = a.unidade;
  const max = comMeta ? Math.min(Math.max(1.1, ...itens.map((v) => v.pct || 0)), 2) * 1.04
    : Math.max(...itens.map((v) => v.realizado || 0), ind.formato === "pct" ? 0.01 : 1) * 1.04;
  const pos = (x) => `${(Math.min(x, max) / max) * 100}%`;
  const comRitmo = ind.comportamento !== "taxa";
  const linhas = itens.map((v, i) => {
    const ritmo = comMeta && comRitmo && a.situacao === "aberto" ? a.calendarios[v.regiao]?.ritmo : null;
    const tt = `<div class='tt-t'>${esc(v.nome)}</div>` + linhaTT("Realizado", esc(valorIndicador(ind, v.realizado, u))) +
      (v.numerador != null ? linhaTT(ind.numerador, valorParte(ind, v.numerador)) + linhaTT(ind.denominador, valorParte(ind, v.denominador)) : "") +
      (v.meta ? linhaTT("Meta", esc(valorIndicador(ind, v.meta, u))) + linhaTT("Atingido", fmt.pct(v.pct)) + linhaTT("Situação", rotuloStatus(ind, v.status)) : "");
    const largura = comMeta ? pos(v.pct || 0) : pos(v.realizado || 0);
    return `<div class="rank-linha" data-tt="${esc(tt)}" tabindex="0">
      <span class="rank-pos ${i < 3 && v.realizado ? "top" : ""}">${i + 1}º</span>
      <span class="rank-nome" title="${esc(v.nome)}">${esc(v.nome)}</span>
      <span class="rank-trilho">
        ${ritmo ? `<span class="rank-marca" style="left:${pos(ritmo)}"></span>` : ""}
        ${comMeta ? `<span class="rank-marca cem" style="left:${pos(1)}"></span>` : ""}
        <span class="rank-barra ${v.status === "batida" ? "batida" : ""}" style="--cor-barra:${comMeta ? corStatus(v.status) : cor}" data-largura="${largura}"></span>
      </span>
      <span class="rank-val"><b>${v.meta ? fmt.pct(v.pct) : esc(valorIndicador(ind, v.realizado, u, true))}</b><span>${v.meta ? esc(valorIndicador(ind, v.realizado, u, true)) : "sem meta"}</span></span>
    </div>`;
  }).join("");
  const escala = comMeta ? `<div class="rank-escala"><span></span><span></span><div class="faixa-e"><span style="left:${pos(1)}">meta 100%</span></div><span></span></div>` : "";
  const sub = !comMeta ? "quem foi melhor na campanha"
    : comRitmo ? "% da meta de cada um; o traço tracejado é o ritmo esperado até a data dos dados" : "% da meta de cada um";
  return `<section class="cartao secao entra" style="--i:5">
    <div class="cartao-cab"><div><h3>${icone("ranking")}Ranking dos vendedores</h3><p class="sub">${sub}</p></div></div>
    ${escala}<div class="ranking">${linhas}</div></section>`;
}

function tabelaAndamento(c, a) {
  if (!a.vendedores.length) return `<div class="cartao secao vazio">${icone("pessoas")}<p>Nenhum vendedor da campanha no seu acesso.</p></div>`;
  const ind = a.indicador, u = a.unidade;
  const v = (x) => esc(valorIndicador(ind, x, u));
  const soma = ind.comportamento === "soma";
  const aberto = a.situacao === "aberto" && soma;
  const partes = !!ind.numerador, base = ind.forma === "crescimento";
  const linhas = a.vendedores.map((r, i) => `<tr style="--i:${i}">
    <td class="nome-v">${esc(r.nome)}<small>código ${r.id} · ${esc(r.equipe || "")}</small></td>
    <td>${v(r.realizado)}</td>
    ${partes ? `<td>${valorParte(ind, r.numerador)}</td><td>${valorParte(ind, r.denominador)}</td>` : ""}
    ${base ? `<td>${r.base ? v(r.base) : '<span class="fraco">sem base</span>'}</td>` : ""}
    <td>${r.meta ? v(r.meta) : '<span class="fraco">sem meta</span>'}${r.meta_individual ? ' <span class="fraco" title="meta ajustada para este vendedor">*</span>' : ""}</td>
    <td>${r.meta && r.pct != null ? `<span class="pct-cel"><span class="mini"><i style="width:${Math.min(100, (r.pct || 0) * 100)}%;--c:${corStatus(r.status)}"></i></span><b>${fmt.pct(r.pct)}</b></span>` : "—"}</td>
    ${soma ? `<td>${r.falta != null ? v(r.falta) : "—"}</td>` : ""}
    ${aberto ? `<td>${r.falta_por_dia != null ? v(r.falta_por_dia) : "—"}</td><td>${r.projecao != null ? v(r.projecao) : "—"}</td>` : ""}
    <td>${a.situacao === "futuro" ? chipStatus("sem_meta", "Não começou") : chipInd(ind, r.status)}</td></tr>`).join("");
  const individuais = a.vendedores.some((r) => r.meta_individual)
    ? `<p class="usu-nota">${icone("info")}<span>* meta ajustada para o vendedor; os demais seguem a meta padrão de ${esc(metaDigitada(ind, c.meta_padrao, u))}.</span></p>` : "";
  const nota = base ? `<p class="usu-nota">${icone("info")}<span>A meta de cada vendedor é a base (o que ele fez em ${esc(periodoTexto(a.periodo_base.inicio, a.periodo_base.fim))}) mais o crescimento pedido. Sem base, fica só no ranking.</span></p>` : "";
  return `<section class="cartao secao entra" style="--i:6">
    <div class="cartao-cab"><div><h3>${icone("pessoas")}Andamento por vendedor</h3>
      <p class="sub">${esc(ind.nome)} de ${esc(periodoTexto(c.inicio, c.fim))}${a.periodo.ate && a.periodo.ate !== c.fim ? `, com dados até ${fmt.data(a.periodo.ate)}` : ""}</p></div></div>
    <div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>Vendedor</th><th>Realizado</th>${partes ? `<th>${esc(ind.numerador)}</th><th>${esc(ind.denominador)}</th>` : ""}
        ${base ? "<th>Base</th>" : ""}<th>Meta</th><th>Atingido</th>${soma ? "<th>Falta</th>" : ""}
        ${aberto ? "<th>Falta por dia útil</th><th>Projeção</th>" : ""}<th>Situação</th></tr></thead>
      <tbody>${linhas}</tbody>
    </table></div>${individuais}${nota}</section>`;
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

// Campanha de antes dos tipos novos (ou rascunho antigo do Assistente): faturamento, volume e mix viram Personalizada.
function normalizarLegado(d) {
  const legado = LEGADOS[d.metrica];
  if (!legado) return { metrica: d.metrica, parametros: { ...(d.parametros || {}) } };
  return { metrica: "personalizada", parametros: { ...(d.parametros || {}), medida: legado[0], forma: legado[1] } };
}

const aceitaBase = (t, p) => ["positivacao", "mix_medio", "frequencia"].includes(t)
  || (t === "personalizada" && ["total", "por_cliente"].includes(p.forma));
const semFiltroProduto = (t) => t === "efetividade" || t === "preco_medio";

// dados: a campanha (editar), o rascunho do Assistente ou nada (nova). nomes: nomes que o rascunho já trouxe.
async function abrirFormulario({ id = null, dados = null, rascunho = null, nomes = null } = {}) {
  if (dlg.open && formMudou() && !confirm("Descartar o que foi preenchido nesta campanha?")) return;
  const inicio = hoje();
  filtros = {};
  precos = null;
  const d = dados || {
    nome: "", descricao: "", premiacao: "", inicio, fim: fimDoMes(inicio), metrica: "positivacao", parametros: {},
    filtros: {}, meta_padrao: 0, vendedores: [], metas_produto: [],
  };
  const { metrica, parametros } = normalizarLegado(d);
  form = {
    id, rascunho, nomes: nomes || {},
    metrica, parametros: { medida: "faturamento", forma: "total", clientes: "todos", ...parametros },
    metasProduto: new Map((d.metas_produto || []).map((p) => [p.id, p.meta])),
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
        <div class="cf-metricas" role="radiogroup" aria-label="Tipo de campanha">${Object.entries(TIPOS).map(([k, m]) => `
          <button type="button" class="visao-op ${k === metrica ? "ativo" : ""}" role="radio" aria-checked="${k === metrica}" data-metrica="${k}">
            ${icone(m.icone)}<span><b>${esc(m.nome)}</b><small>${esc(m.descricao)}</small></span></button>`).join("")}</div>
        <div class="cf-sub" id="cf-sub"></div></div>
      <div class="largo" id="cf-precos-bloco" hidden><span class="cf-rotulo">Produtos e preços-alvo <small>(R$ por unidade do produto)</small></span>
        <div class="filtros"><div id="cf-precos-ms"></div></div>
        <div class="cf-precos" id="cf-precos"></div></div>
      <div class="largo"><span class="cf-rotulo"><span id="cf-rotulo-filtros">Produtos e clientes que contam</span> <small>(nada escolhido = tudo)</small></span>
        <div class="filtros cf-filtros">${FILTROS.map((f) => `<div id="cf-f-${f.id}"></div>`).join("")}</div>
        <p class="usu-nota" id="cf-dica-filtro"></p></div>
      <label class="campo-form" id="cf-meta-bloco"><span>Meta padrão por vendedor <small id="cf-unidade"></small></span>
        <input type="number" name="meta_padrao" min="0" step="any" inputmode="decimal" value="${metrica === "preco_medio" ? "" : d.meta_padrao || ""}" placeholder="0 = sem meta, só ranking"></label>
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
    desenharSub();
  }));
  f.querySelector("#cf-sub").addEventListener("change", (e) => {
    const k = e.target.dataset.p;
    if (!k) return;
    form.parametros[k] = e.target.type === "number" ? Number(e.target.value) || null : e.target.value;
    if (k === "medida" && !MEDIDAS[form.parametros.medida].formas.includes(form.parametros.forma)) form.parametros.forma = "total";
    desenharSub();
  });
  f.querySelector('[name="inicio"]').addEventListener("change", (e) => {
    const fim = f.querySelector('[name="fim"]');
    if (!fim.value || fim.value < e.target.value) fim.value = fimDoMes(e.target.value);
  });
  if (!dlg.open) dlg.showModal();
  desenharSub();
  f.querySelector('[name="nome"]').focus();
  const cat = await carregarCatalogo();
  if (!form || dlg.querySelector("form") !== f) return; // fechou ou abriu outra enquanto o catálogo vinha
  if (!cat) {
    erroForm(`Não foi possível carregar vendedores e produtos: ${estado.erroCatalogo}`);
    f.querySelector("#cf-vendedores").innerHTML = "";
  } else {
    montarFiltros(f, d.filtros || {}, cat);
    montarPrecos(f, cat);
    montarVendedores(f, cat);
  }
  form.orig = JSON.stringify(coletar());
  desenharSub();
}

// Os blocos que dependem do tipo: medida, forma e comparação (Personalizada), quem conta (base de clientes) e,
// fora dele, a lista de preços-alvo, os filtros de produto e a meta padrão.
function desenharSub() {
  if (!form) return;
  const f = dlg.querySelector("form");
  const t = form.metrica, p = form.parametros;
  const sel = (k, rotulo, opcoes, valor) => `<label class="campo-form"><span>${esc(rotulo)}</span>
    <span class="campo"><select data-p="${k}" style="padding-left:14px">${Object.entries(opcoes).map(([id, n]) =>
      `<option value="${id}" ${id === valor ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></span></label>`;
  let html = "";
  if (t === "personalizada") {
    html += sel("medida", "O que medir", Object.fromEntries(Object.entries(MEDIDAS).map(([k, m]) => [k, m.nome])), p.medida);
    html += sel("forma", "Como", Object.fromEntries(MEDIDAS[p.medida].formas.map((k) => [k, FORMAS[k]])), p.forma);
    if (p.forma === "crescimento") html += sel("comparar", "Comparar com", COMPARAR, p.comparar || "periodo_anterior");
  }
  if (aceitaBase(t, p)) {
    html += sel("clientes", "Quem conta", BASES, p.clientes || "todos");
    if (p.clientes === "recuperados") {
      html += `<label class="campo-form"><span>Sem compra há pelo menos <small>(dias antes do início)</small></span>
        <input type="number" data-p="dias_sem_compra" min="1" max="730" step="1" value="${p.dias_sem_compra || 90}"></label>`;
    }
  }
  const sub = f.querySelector("#cf-sub");
  sub.innerHTML = html;
  sub.hidden = !html;
  for (const id of FILTROS_PRODUTO) {
    const el = f.querySelector(`#cf-f-${id}`);
    if (el) el.hidden = semFiltroProduto(t);
  }
  f.querySelector("#cf-rotulo-filtros").textContent = semFiltroProduto(t) ? "Clientes que contam" : "Produtos e clientes que contam";
  f.querySelector("#cf-precos-bloco").hidden = t !== "preco_medio";
  f.querySelector("#cf-meta-bloco").hidden = t === "preco_medio";
  f.querySelectorAll(".cf-vend .cf-meta-v").forEach((i) => {
    const linha = i.closest(".cf-vend");
    i.disabled = t === "preco_medio" || !linha.classList.contains("marcado");
    i.placeholder = t === "preco_medio" ? "—" : "padrão";
  });
  dicas();
}

// Preço médio: os produtos (a mesma lista do filtro) e o preço-alvo de cada um, com o preço dos últimos 90 dias de dica.
function montarPrecos(f, cat) {
  const itens = opcoesFiltro("produtos", cat);
  for (const p of form.metasProduto.keys()) if (!itens.some((i) => i.id === p)) itens.push({ id: p, nome: nomeProduto(p, form.nomes.produtos), grupo: "cat:", detalhe: `código ${p}` });
  const grupos = [{ id: "mussarela", nome: "Mussarela" }, ...cat.categorias.map((c) => ({ id: `cat:${c}`, nome: c })), { id: "cat:", nome: "Demais produtos" }];
  precos = multiSelecao(f.querySelector("#cf-precos-ms"), {
    rotulo: "Produtos da campanha", icone: "caixa", todos: "Escolha os produtos", plural: "produtos", busca: "Buscar produto",
    classe: "curto", itens, selecionados: [...form.metasProduto.keys()], nomesAte: 2, grupos,
    aoAplicar: (ids) => {
      const novo = new Map();
      for (const id of ids) novo.set(id, form.metasProduto.get(id) ?? null);
      form.metasProduto = novo;
      desenharPrecos(f);
    },
  });
  desenharPrecos(f);
}

function desenharPrecos(f) {
  const alvo = f.querySelector("#cf-precos");
  const porId = new Map((estado.catalogo?.produtos || []).map((p) => [p.id, p]));
  if (!form.metasProduto.size) {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Escolha os produtos e dê o preço-alvo de cada um. O índice do vendedor compara o que ele vendeu com o que seria nos preços-alvo (100% = no alvo).</span></p>`;
    return;
  }
  alvo.innerHTML = [...form.metasProduto].map(([id, meta]) => {
    const p = porId.get(id);
    const un = (p?.unidade || "").toLowerCase();
    return `<div class="cf-preco" data-id="${id}">
      <span class="n">${esc(p?.nome || nomeProduto(id, form.nomes.produtos))}<small>código ${id}${un ? ` · ${esc(un)}` : ""}${p?.preco_90d ? ` · média dos últimos 90 dias: ${reais2(p.preco_90d)}` : ""}</small></span>
      <input class="cf-meta-v" type="number" min="0" step="0.01" inputmode="decimal" aria-label="Preço-alvo de ${esc(p?.nome || id)}"
        placeholder="${p?.preco_90d ? fmt.num(p.preco_90d, 2) : "R$"}" value="${meta ?? ""}"><span class="fraco">R$${un ? `/${esc(un)}` : ""}</span>
    </div>`;
  }).join("");
  alvo.querySelectorAll(".cf-preco input").forEach((i) => i.addEventListener("input", () => {
    const v = i.value.trim();
    form.metasProduto.set(Number(i.closest(".cf-preco").dataset.id), v === "" ? null : Number(v));
  }));
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
  const valores = { linhas: cat.linhas, categorias: cat.categorias, grupos: cat.grupos, ufs: cat.ufs, segmentos: cat.segmentos,
                    areas: cat.areas || [] }[id];
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
    if (semFiltroProduto(form.metrica) && FILTROS_PRODUTO.includes(id)) continue; // escondidos neste tipo
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
    linha.querySelector(".cf-meta-v").disabled = !sim || form.metrica === "preco_medio";
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

// Explica a unidade da meta e o que cada tipo pede (volume: uma unidade só; nunca/já compraram: os produtos).
function dicas() {
  if (!form) return;
  const f = dlg.querySelector("form");
  const un = f.querySelector("#cf-unidade");
  const dica = f.querySelector("#cf-dica-filtro");
  const t = form.metrica, p = form.parametros;
  const escolhidos = filtros.produtos ? filtros.produtos.ms.valor() : [];
  const comProduto = FILTROS_PRODUTO.some((id) => filtros[id]?.ms.valor().length);
  let unidade = { positivacao: "(clientes)", mix_medio: "(produtos por cliente)", efetividade: "(%, ex.: 80)",
                  frequencia: "(semanas com compra por cliente)" }[t] || "";
  const textos = [];
  if (t === "personalizada") {
    unidade = p.forma === "crescimento" ? "(% de crescimento, ex.: 10)" : p.forma === "pct_carteira" ? "(% da carteira, ex.: 60)"
      : { faturamento: p.forma === "por_cliente" ? "(R$ por cliente)" : "(R$)", volume: p.forma === "por_cliente" ? "(por cliente)" : "",
          clientes: "(clientes)", produtos: "(produtos)" }[p.medida];
    if (p.medida === "volume") {
      const unidades = [...new Set((estado.catalogo?.produtos || []).filter((x) => escolhidos.includes(x.id)).map((x) => x.unidade))];
      if (unidades.length === 1 && p.forma !== "crescimento") unidade = `(${unidades[0].toLowerCase()}${p.forma === "por_cliente" ? " por cliente" : ""})`;
      textos.push(unidades.length > 1
        ? `Os produtos escolhidos têm unidades diferentes (${unidades.join(", ")}): em volume use uma só.`
        : "Em volume, escolha produtos, linha, categoria ou grupo com uma unidade só (a quantidade não soma kg com unidade).");
    }
    if (p.forma === "crescimento") textos.push("A meta de cada vendedor é o que ele fez no período de comparação mais o crescimento pedido.");
    if (p.forma === "pct_carteira") textos.push("Conta os clientes ativos da carteira de cada vendedor que compraram no período, de qualquer vendedor.");
  }
  if (t === "efetividade") textos.push("Conta os pedidos de venda e as visitas esperadas pelos dias de atendimento das áreas (Gestão › Configurar), pela carteira de cada vendedor. Clientes em áreas sem dia ficam fora.");
  if (t === "frequencia") textos.push("Semanas de domingo a sábado, cortadas na virada do mês, como no Power BI.");
  if (t === "mix_medio") textos.push("Os produtos escolhidos são o mix da campanha; nada escolhido = todos os produtos. Divide por todos os clientes que compraram.");
  if (["nunca_compraram", "ja_compraram"].includes(p.clientes) && aceitaBase(t, p) && !comProduto) {
    textos.push("Para contar quem nunca ou já comprou, escolha os produtos da campanha.");
  }
  un.textContent = unidade;
  dica.innerHTML = textos.length ? `${icone("info")}<span>${esc(textos.join(" "))}</span>` : "";
  dica.hidden = !textos.length;
}

function parametrosColetados() {
  const t = form.metrica, p = form.parametros, saida = {};
  if (t === "personalizada") {
    Object.assign(saida, { medida: p.medida, forma: p.forma });
    if (p.forma === "crescimento") saida.comparar = p.comparar || "periodo_anterior";
  }
  if (aceitaBase(t, p)) {
    saida.clientes = p.clientes || "todos";
    if (saida.clientes === "recuperados") saida.dias_sem_compra = p.dias_sem_compra || 90;
  }
  return saida;
}

function coletar() {
  const f = dlg.querySelector("form");
  const val = (n) => f.querySelector(`[name="${n}"]`).value;
  const preco = form.metrica === "preco_medio";
  const vendedores = [...f.querySelectorAll(".cf-vend.marcado")].map((l) => {
    const meta = l.querySelector(".cf-meta-v").value.trim();
    return { id: Number(l.dataset.id), meta: meta === "" || preco ? null : Number(meta) };
  });
  return {
    nome: val("nome").trim(), inicio: val("inicio"), fim: val("fim"), metrica: form.metrica, parametros: parametrosColetados(),
    filtros: Object.keys(filtros).length ? valoresFiltros() : {}, meta_padrao: preco ? 100 : Number(val("meta_padrao") || 0),
    premiacao: val("premiacao").trim(), descricao: val("descricao").trim(),
    vendedores: f.querySelector(".cf-vend") ? vendedores : [...form.vendedores].map(([id, meta]) => ({ id, meta })),
    metas_produto: preco ? [...form.metasProduto].map(([id, meta]) => ({ id, meta })) : [],
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
  if (dados.metrica === "preco_medio") {
    if (!dados.metas_produto.length) return erroForm("escolha os produtos do preço médio");
    if (dados.metas_produto.some((p) => !(p.meta > 0))) return erroForm("dê o preço-alvo de cada produto (R$ por unidade)");
  }
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
