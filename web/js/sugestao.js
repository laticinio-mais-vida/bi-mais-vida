// Página Sugestão de Metas: a meta do mês seguinte de cada vendedor, por produto (as páginas "Sugestão de Meta BA/ES"
// do Power BI). A conta fica no servidor (bi/sugestao.py); aqui é a apresentação: cartões, gráfico, tabela por produto
// (no BA também por área), o resumo dos vendedores e o passo a passo.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast } from "./util.js";
import { colunasLinha } from "./graficos.js";
import { ligarCaptura } from "./relatorio.js";
import { ligarTelaCheia, sairTelaCheia } from "./telacheia.js";

const MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const ORIGEM = { ajuste: "ajustado à mão", fixo: "número fixo", automatico: "pelos dias de atendimento" };

let ctx = null;
const estado = { estado: null, mes: null, vendedor: null, area: null, visao: "produtos", produto: null,
                 abertas: new Set(), dados: null, pedido: 0 };

export function montarSugestao(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const salvo = ler("mv-sugestao", {});
  const inteiro = (t) => (/^\d+$/.test(t || "") ? Number(t) : null);
  estado.estado = q.get("e") || salvo.e || null;
  estado.mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : null;
  estado.vendedor = inteiro(q.get("v"));
  estado.area = inteiro(q.get("a"));
  estado.visao = (q.get("t") || salvo.t) === "areas" ? "areas" : "produtos";
  estado.produto = null;
  estado.dados = null;

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("foguete")}</span>
        <div><b>Sugestão de metas</b><small id="s-sub">a meta do mês seguinte, por vendedor e produto</small></div></div>
      <div class="filtros">
        <div class="seg-mini" role="group" aria-label="Estado" id="s-estado"></div>
        <label class="campo" title="Vendedor"><span class="ic-campo">${icone("usuario")}</span><select id="s-vendedor" aria-label="Vendedor"></select></label>
        <label class="campo" title="Área comercial"><span class="ic-campo">${icone("mapa")}</span><select id="s-area" aria-label="Área comercial"></select></label>
        <label class="campo" title="Mês da meta (o mês base é o anterior)"><span class="ic-campo">${icone("calendario")}</span><select id="s-mes" aria-label="Mês da meta"></select></label>
        <button class="btn btn-limpar" type="button" id="s-limpar" hidden>${icone("x")}Limpar filtros</button>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-sugestao" title="Crescimento desejado, tetos e os faturamentos das áreas do BA">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="s-avisos"></div>
    <div id="s-conteudo"><div class="grade secao">
      <div class="kpis n4 sug-kpis"><div class="esqueleto" style="height:200px"></div><div class="esqueleto" style="height:200px"></div><div class="esqueleto" style="height:200px"></div><div class="esqueleto" style="height:200px"></div></div>
      <div class="esqueleto" style="height:380px"></div></div>
    </div>`;

  container.querySelector("#s-estado").addEventListener("click", (e) => {
    const b = e.target.closest("[data-estado]");
    if (!b || b.dataset.estado === estado.estado) return;
    estado.estado = b.dataset.estado;
    estado.vendedor = null;
    estado.area = null;
    carregar();
  });
  container.querySelector("#s-vendedor").addEventListener("change", (e) => {
    estado.vendedor = e.target.value ? Number(e.target.value) : null;
    estado.area = null;
    carregar();
  });
  container.querySelector("#s-area").addEventListener("change", (e) => { estado.area = e.target.value ? Number(e.target.value) : null; carregar(); });
  container.querySelector("#s-mes").addEventListener("change", (e) => { estado.mes = e.target.value; carregar(); });
  container.querySelector("#s-limpar").addEventListener("click", () => { estado.vendedor = null; estado.area = null; carregar(); });
  container.querySelector("#s-conteudo").addEventListener("click", aoClicar);
  carregar();
}

export function recarregarSugestao() { if (ctx) carregar(true); }

function atualizarUrl() {
  guardar("mv-sugestao", { e: estado.estado, t: estado.visao });
  if (!location.hash.startsWith("#/sugestao")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams();
  if (estado.estado) p.set("e", estado.estado);
  if (estado.mes) p.set("m", estado.mes);
  if (estado.vendedor) p.set("v", estado.vendedor);
  if (estado.area) p.set("a", estado.area);
  if (estado.visao === "areas") p.set("t", "areas");
  history.replaceState(null, "", `#/sugestao${p.toString() ? "?" + p : ""}`);
  document.getElementById("s-limpar").hidden = !estado.vendedor && !estado.area;
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("s-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  sairTelaCheia();
  if (estado.dados) conteudo.classList.add("recarregando");
  atualizarUrl();
  try {
    const p = new URLSearchParams();
    if (estado.estado) p.set("estado", estado.estado);
    if (estado.mes) p.set("mes", estado.mes);
    if (estado.vendedor) p.set("vendedor", estado.vendedor);
    if (estado.area) p.set("area", estado.area);
    const d = await api(`/api/sugestao?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    estado.estado = d.estado;
    estado.mes = d.mes.meta;
    estado.vendedor = d.filtros.vendedor;
    estado.area = d.filtros.area;
    if (estado.produto && !d.grafico.produtos[estado.produto]) estado.produto = null;
    atualizarUrl();
    preencherFiltros(d);
    ctx.subtitulo(d);
    document.getElementById("s-avisos").innerHTML = (d.avisos || [])
      .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
    conteudo.innerHTML = render(d);
    posRender(conteudo, d);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 400 && (estado.vendedor || estado.area || estado.mes)) {
      // filtro guardado de outro acesso ou de outro estado: volta para o padrão
      estado.vendedor = null;
      estado.area = null;
      estado.mes = null;
      toast(e.message, "erro");
      return carregar(silencioso);
    }
    if (e.status === 403) {
      conteudo.innerHTML = `<div class="cartao secao vazio">${icone("cadeado")}<p>${esc(e.message)}</p></div>`;
      return;
    }
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone("alerta")}<p>Não foi possível carregar: ${esc(e.message)}</p></div>`;
    if (!silencioso) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
  }
}

function preencherFiltros(d) {
  const op = d.opcoes;
  document.getElementById("s-estado").innerHTML = d.estados.map((e) =>
    `<button type="button" data-estado="${e}" class="${e === d.estado ? "ativo" : ""}" aria-pressed="${e === d.estado}">${e}</button>`).join("");
  document.getElementById("s-vendedor").innerHTML = `<option value="">Todos os vendedores do ${esc(d.estado)}</option>` +
    op.vendedores.map((v) => `<option value="${v.id}"${v.id === d.filtros.vendedor ? " selected" : ""}>${esc(v.nome)}${v.equipe === "EDIR" ? " (Edir)" : ""}</option>`).join("");
  document.getElementById("s-area").innerHTML = `<option value="">Todas as áreas</option>` +
    op.areas.map((a) => `<option value="${a.id}"${a.id === d.filtros.area ? " selected" : ""}>${esc(a.nome)}</option>`).join("");
  document.getElementById("s-mes").innerHTML = op.meses.map((m) =>
    `<option value="${m.valor}"${m.valor === d.mes.meta ? " selected" : ""}>Meta de ${esc(m.rotulo)}</option>`).join("");
  document.getElementById("s-sub").textContent = `meta de ${d.mes.rotulo_meta}, pela base de ${d.mes.rotulo_base}`;
}

// ---------- apoio ----------
const sinal = (v, d = 1) => (v == null || !isFinite(v) ? "—" : `${v > 0.00005 ? "+" : v < -0.00005 ? "−" : ""}${fmt.pct(Math.abs(v), d)}`);
const volume = (v, u) => (v == null ? "—" : `${fmt.num(v, 1)}${u ? ` <small class="fraco un">${esc(u)}</small>` : ""}`);

function variacao(v) {
  if (v == null || !isFinite(v)) return "";
  const sobe = v >= 0;
  return `<span class="chip-variacao ${sobe ? "sobe" : "desce"}">${icone(sobe ? "tendencia" : "abaixo")}${sobe ? "+" : "−"}${fmt.pct(Math.abs(v))}</span>`;
}

function nomeVendedor(d) {
  if (!d.filtros.vendedor) return `todos os vendedores do ${d.estado}`;
  return d.opcoes.vendedores.find((v) => v.id === d.filtros.vendedor)?.nome || `vendedor ${d.filtros.vendedor}`;
}

function descricaoFiltro(d) {
  const area = d.filtros.area ? d.opcoes.areas.find((a) => a.id === d.filtros.area)?.nome || `área ${d.filtros.area}` : null;
  return [nomeVendedor(d), area].filter(Boolean).join(" · ");
}

// ---------- estrutura ----------
function render(d) {
  let h = "";
  if (d.cartoes) {
    h += `<section class="kpis secao n4 sug-kpis">${kpis(d)}</section>`;
    h += cartaoGrafico(d, 5);
    h += tabela(d, 6);
  } else {
    h += `<section class="cartao secao vazio entra" style="--i:1">${icone("caixa")}<p>Sem vendas em ${esc(d.mes.rotulo_base)} (o mês base) para ${esc(descricaoFiltro(d))}: não há o que sugerir.</p></section>`;
  }
  h += resumo(d, 7);
  h += comoCalcula(d, 8);
  return h;
}

function posRender(raiz, d) {
  ligarCaptura(raiz);
  ligarTelaCheia(raiz);
  animarContadores(raiz);
  animarEntradas(raiz);
  ligarTooltips(raiz);
  desenharGrafico(d);
}

function aoClicar(e) {
  const d = estado.dados;
  if (!d) return;
  const v = e.target.closest("[data-vendedor]");
  if (v) {
    const id = Number(v.dataset.vendedor);
    estado.vendedor = estado.vendedor === id ? null : id;
    estado.area = null;
    carregar();
    return;
  }
  const visao = e.target.closest("[data-visao]");
  if (visao) {
    if (visao.dataset.visao === estado.visao) return;
    estado.visao = visao.dataset.visao;
    atualizarUrl();
    trocarTabela(d);
    return;
  }
  if (e.target.closest("[data-abrir-todas]")) {
    const todas = estado.abertas.size < d.areas.length;
    estado.abertas = new Set(todas ? d.areas.map((a) => a.id) : []);
    trocarTabela(d);
    return;
  }
  const area = e.target.closest("tr.area-cab");
  if (area) {
    const id = Number(area.dataset.area);
    if (estado.abertas.has(id)) estado.abertas.delete(id); else estado.abertas.add(id);
    const grupo = area.closest("tbody");
    grupo.classList.toggle("aberto", estado.abertas.has(id));
    area.querySelector(".sug-abrir")?.setAttribute("aria-expanded", estado.abertas.has(id));
    return;
  }
  if (e.target.closest("[data-limpar-produto]")) {
    escolherProduto(null);
    return;
  }
  const prod = e.target.closest("tr[data-produto]");
  if (prod) escolherProduto(prod.dataset.produto === estado.produto ? null : prod.dataset.produto);
}

function escolherProduto(id) {
  estado.produto = id;
  const raiz = document.getElementById("s-conteudo");
  raiz.querySelectorAll("tr[data-produto]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.produto === id));
  desenharGrafico(estado.dados);
}

// ---------- cartões ----------
function kpi({ i, cor, ic, rotulo, valor, contar, meta, rodape = [], extra = "" }) {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${rotulo}</span>${extra}</div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor"${contar != null ? ` data-contar="${contar}" data-fmt="moeda"` : ""}>${valor}</div>
      <div class="kpi-meta">${meta}</div>
    </div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function kpis(d) {
  const c = d.cartoes, p = d.parametros, m = d.mes;
  const lancada = d.filtros.vendedor && !d.filtros.area ? d.resumo.find((r) => r.id === d.filtros.vendedor)?.meta_lancada : null;
  const tt = `<div class='tt-t'>Meta sugerida sobre a base</div>${fmt.moeda(c.meta_rs)} contra ${fmt.moeda(c.base_rs)} em ${esc(m.curto_base)} (volume × o mesmo preço médio)`;
  const meta = kpi({
    i: 1, cor: "var(--s-fat)", ic: "alvo", rotulo: "Meta sugerida", valor: "R$ 0", contar: c.meta_rs,
    extra: `<span data-tt="${esc(tt)}">${variacao(c.crescimento_total)}</span>`,
    meta: `para <b>${esc(m.rotulo_meta)}</b> · ${esc(descricaoFiltro(d))}`,
    rodape: [
      [`Base de ${esc(m.curto_base)} (mesma conta)`, fmt.moeda(c.base_rs)],
      ...(lancada != null ? [["Meta lançada na planilha", fmt.moeda(lancada)]] : []),
      ["Produtos com meta", fmt.num(d.produtos.length)],
    ],
  });
  const saz = kpi({
    i: 2, cor: "var(--s-out)", ic: "calendario", rotulo: "Sazonalidade", valor: sinal(c.sazonalidade),
    meta: `ritmo de <b>${esc(p.meta_ly)}</b> sobre <b>${esc(p.base_ly)}</b>, por faturamento${c.exata ? "" : " · média ponderada"}`,
    rodape: [["Teto", `+${fmt.pct(p.teto_sazonalidade, 0)}`], ["Queda no ano passado", "reduz a meta"]],
  });
  const fat = d.dias
    ? kpi({ i: 3, cor: "var(--k-cli)", ic: "relogio", rotulo: "Dias úteis", valor: `${fmt.dias(d.dias.base)} → ${fmt.dias(d.dias.meta)}`,
            meta: `dias úteis do ES em <b>${esc(m.curto_base)}</b> e <b>${esc(m.curto_meta)}</b>`,
            rodape: [["Efeito na meta", sinal(c.efeito_faturamentos)]] })
    : kpi({ i: 3, cor: "var(--k-cli)", ic: "relogio", rotulo: "Faturamentos", valor: sinal(c.efeito_faturamentos),
            meta: `efeito do nº de faturamentos de cada área, <b>${esc(m.curto_base)}</b> → <b>${esc(m.curto_meta)}</b>`,
            rodape: [["Conta", "dias de atendimento + calendário"]] });
  const cre = kpi({
    i: 4, cor: "var(--s-mus)", ic: "tendencia", rotulo: "Crescimento proposto", valor: sinal(c.crescimento),
    meta: `${fmt.pct(p.crescimento, 0)} no ano menos o acumulado${c.exata ? "" : " · média ponderada"}`,
    rodape: [[`Acumulado ${esc(p.acumulado.de)}–${esc(p.acumulado.ate)}`, sinal(c.acumulado)], ["Faixa", `0% a +${fmt.pct(p.teto_crescimento, 0)}`]],
  });
  return meta + saz + fat + cre;
}

// ---------- gráfico ----------
function cartaoGrafico(d, i) {
  return `
  <section class="cartao secao entra" style="--i:${i}" id="s-cartao-grafico">
    <div class="cartao-cab"><div>
      <h3>${icone("grafico")}Evolução<span class="sug-g-produto" id="s-g-produto"></span></h3>
      <p class="sub" id="s-g-sub"></p>
    </div><div id="s-g-acao"></div></div>
    <div class="legenda">
      <span class="item"><span class="quadro" style="--c:var(--s-fat)"></span>${d.grafico.ano}</span>
      <span class="item"><span class="quadro" style="--c:var(--s-ritmo)"></span>${d.grafico.ano - 1}</span>
      <span class="item"><span class="traco" style="--c:var(--acento)"></span>Sazonalidade (eixo da direita)</span>
    </div>
    <div class="grafico" id="g-sugestao" style="margin-top:6px"></div>
  </section>`;
}

function desenharGrafico(d) {
  const el = document.getElementById("g-sugestao");
  if (!el || !d.cartoes) return;
  const id = estado.produto;
  const s = id ? d.grafico.produtos[id] : d.grafico.total;
  const prod = id ? d.produtos.find((p) => String(p.id) === id) : null;
  document.getElementById("s-g-produto").textContent = prod ? prod.nome : "";
  document.getElementById("s-g-sub").textContent = prod
    ? `Volume de ${prod.nome} em cada mês e a sazonalidade de cada mês para o seguinte no ano anterior (por dia útil, sem o teto)`
    : "Volume de todos os produtos somados (unidades diferentes, como no Power BI) · clique num produto da tabela para ver só ele";
  document.getElementById("s-g-acao").innerHTML = prod ? `<button class="btn" type="button" data-limpar-produto>${icone("x")}Todos os produtos</button>` : "";
  el.dataset.desenhado = "";
  colunasLinha(el, {
    meses: MESES_CURTOS, atual: s.atual, anterior: s.anterior, linha: s.sazonalidade,
    base: d.grafico.base, meta: d.grafico.meta, unidade: prod ? prod.unidade : "",
    nomes: { atual: String(d.grafico.ano), anterior: String(d.grafico.ano - 1), linha: "Sazonalidade para o mês seguinte" },
  });
}

// ---------- tabela ----------
const COLUNAS = [
  ["Volume base", "Volume líquido do mês base (vendas − devoluções que descontam)"],
  ["Faturamentos", "Faturamentos do mês base → do mês da meta (BA: da área; ES: dias úteis)"],
  ["Sazonalidade", "Ritmo do mês da meta sobre o do mês base, no ano passado, por faturamento (teto; queda reduz a meta)"],
  ["Acumulado", "Volume do ano até o mês base sobre o mesmo período do ano passado"],
  ["Cresc. proposto", "O que falta para o crescimento desejado no ano (de 0% até o teto)"],
  ["Meta (volume)", "Volume do mês base ÷ faturamentos × sazonalidade × faturamentos do mês da meta × crescimento proposto"],
  ["Preço médio", "Faturamento bruto do mês base ÷ volume vendido (sem descontar devoluções)"],
  ["Meta (R$)", "Meta (volume) × preço médio"],
];

function celulas(x, unidade, comVolume = true) {
  const fat = x.faturamentos
    ? `${fmt.dias(x.faturamentos.base)} → ${fmt.dias(x.faturamentos.meta)}`
    : `<span data-tt="${esc("<div class='tt-t'>Efeito dos faturamentos</div>as áreas têm números diferentes: média do efeito de cada uma, pelo volume")}">${sinal(x.efeito_faturamentos)}<small class="fraco">efeito</small></span>`;
  const travou = x.sazonalidade_calculada != null && Math.abs(x.sazonalidade_calculada - x.sazonalidade) > 0.00005;
  const saz = sinal(x.sazonalidade) + (travou ? `<small class="fraco sug-calc">calculada ${sinal(x.sazonalidade_calculada)}</small>` : "");
  return `
    <td>${comVolume ? volume(x.volume_base, unidade) : "—"}</td>
    <td>${fat}</td>
    <td>${saz}</td>
    <td>${sinal(x.acumulado)}</td>
    <td>${sinal(x.crescimento)}</td>
    <td>${comVolume ? volume(x.meta_volume, unidade) : "—"}</td>
    <td>${comVolume ? fmt.moeda2(x.preco) : "—"}</td>
    <td class="sug-meta">${fmt.moeda(x.meta_rs)}${comVolume ? "" : `<small class="fraco">base ${fmt.moeda(x.base_rs)}</small>`}</td>`;
}

function linhaProduto(p, k, filho = false) {
  return `<tr data-produto="${p.id}" class="${filho ? "filho " : ""}${String(p.id) === estado.produto ? "sel" : ""}" style="--i:${Math.min(k, 30)}">
    <td class="nome-v">${esc(p.nome)}<small>código ${p.id}${p.unidade ? ` · ${esc(p.unidade)}` : ""}</small></td>${celulas(p, p.unidade)}</tr>`;
}

function corpoTabela(d) {
  const porArea = d.estado === "BA" && estado.visao === "areas";
  if (!porArea) return `<tbody>${d.produtos.map((p, k) => linhaProduto(p, k)).join("")}</tbody>`;
  return d.areas.map((a, k) => {
    const aberta = estado.abertas.has(a.id);
    const origens = Object.values(a.origem || {}).filter((o) => o && o !== "automatico");
    const chip = origens.length ? `<span class="chip-papel">${esc(ORIGEM[origens[0]])}</span>` : "";
    return `<tbody class="grupo${aberta ? " aberto" : ""}">
      <tr class="area-cab" data-area="${a.id}" style="--i:${Math.min(k, 30)}">
        <td class="nome-v"><button type="button" class="sug-abrir" aria-expanded="${aberta}" aria-label="Abrir ou recolher os produtos">${icone("proximo")}</button>${esc(a.nome)}${chip}
          <small>${a.produtos.length} produto${a.produtos.length === 1 ? "" : "s"} · código ${a.id}</small></td>
        ${celulas(a, "", false)}
      </tr>
      ${a.produtos.map((p, j) => linhaProduto(p, j, true)).join("")}
    </tbody>`;
  }).join("");
}

function tabela(d, i) {
  const ba = d.estado === "BA";
  const c = d.cartoes;
  const fatTotal = d.dias ? `${fmt.dias(d.dias.base)} → ${fmt.dias(d.dias.meta)}` : sinal(c.efeito_faturamentos);
  return `
  <section class="cartao secao entra" style="--i:${i}" id="s-cartao-tabela">
    <div class="cartao-cab">
      <div><h3>${icone("caixa")}Meta por ${ba && estado.visao === "areas" ? "área e produto" : "produto"}</h3>
        <p class="sub">${ba && estado.visao === "areas" ? "Clique numa área para ver os produtos dela" : `Soma ${ba ? "das áreas e " : ""}dos vendedores escolhidos`} · clique num produto para ver o gráfico dele · ordem pela meta em R$</p></div>
      ${ba ? `<div class="sug-acoes">
        ${estado.visao === "areas" ? `<button class="btn" type="button" data-abrir-todas>${icone(estado.abertas.size < d.areas.length ? "expandir" : "recolher")}${estado.abertas.size < d.areas.length ? "Abrir todas" : "Recolher todas"}</button>` : ""}
        <div class="seg-mini" role="group" aria-label="Agrupar a tabela">
          <button type="button" data-visao="produtos" class="${estado.visao === "produtos" ? "ativo" : ""}">Por produto</button>
          <button type="button" data-visao="areas" class="${estado.visao === "areas" ? "ativo" : ""}">Por área</button>
        </div></div>` : ""}
    </div>
    <div class="tabela-rolagem"><table class="dados sug-tabela">
      <thead><tr><th>${ba && estado.visao === "areas" ? "Área / produto" : "Produto"}</th>${COLUNAS.map(([n, t]) => `<th title="${esc(t)}">${n}</th>`).join("")}</tr></thead>
      ${corpoTabela(d)}
      <tfoot><tr><td>Total</td><td>—</td><td>${fatTotal}</td><td>${sinal(c.sazonalidade)}</td><td>${sinal(c.acumulado)}</td>
        <td>${sinal(c.crescimento)}</td><td>—</td><td>—</td><td class="sug-meta">${fmt.moeda(c.meta_rs)}<small class="fraco">base ${fmt.moeda(c.base_rs)}</small></td></tr></tfoot>
    </table></div>
  </section>`;
}

function trocarTabela(d) {
  const velho = document.getElementById("s-cartao-tabela");
  if (!velho) return;
  velho.outerHTML = tabela(d, 0);
  const novo = document.getElementById("s-cartao-tabela");
  novo.classList.remove("entra");
  ligarTelaCheia(novo.parentElement);
  ligarTooltips(novo);
}

// ---------- resumo dos vendedores ----------
function resumo(d, i) {
  const m = d.mes;
  const linhas = d.resumo;
  const soma = (k) => linhas.reduce((a, r) => a + (r[k] || 0), 0);
  const base = soma("base_rs"), meta = soma("meta_rs");
  const lancadas = linhas.filter((r) => r.meta_lancada != null);
  const totalLancada = lancadas.reduce((a, r) => a + r.meta_lancada, 0);
  const dif = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${fmt.moeda(Math.abs(v))}`);
  const corpo = `
    <div class="relatorio-cab">
      <img src="/img/logo-maisvida.png" alt="Mais Vida">
      <div>
        <div class="rt">Sugestão de metas ${esc(d.estado)} · ${esc(m.rotulo_meta)}</div>
        <div class="rs">Base: ${esc(m.rotulo_base)} · dados até ${fmt.semana(d.data_ref)}, ${fmt.data(d.data_ref)}</div>
      </div>
    </div>
    <table class="relatorio-tabela sug-resumo">
      <thead><tr><th>Vendedor</th><th>Base (${esc(m.curto_base)})</th><th class="total">Meta sugerida</th><th>Crescimento</th>
        <th>Meta lançada</th><th>Lançada − sugerida</th></tr></thead>
      <tbody>${linhas.map((r) => `<tr data-vendedor="${r.id}" class="${r.id === d.filtros.vendedor ? "sel" : ""}" title="Clique para ver só ${esc(r.nome)}">
        <td class="rotulo">${esc(r.nome)}${r.equipe === "EDIR" ? " <small>(Edir)</small>" : ""}</td>
        <td>${fmt.moeda(r.base_rs)}</td><td class="total">${fmt.moeda(r.meta_rs)}</td><td>${sinal(r.crescimento)}</td>
        <td>${r.meta_lancada != null ? fmt.moeda(r.meta_lancada) : "—"}</td><td>${dif(r.diferenca)}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td class="rotulo">Total</td><td>${fmt.moeda(base)}</td><td class="total">${fmt.moeda(meta)}</td>
        <td>${base > 0 ? sinal(meta / base - 1) : "—"}</td><td>${lancadas.length ? fmt.moeda(totalLancada) : "—"}</td>
        <td>${lancadas.length ? dif(totalLancada - lancadas.reduce((a, r) => a + r.meta_rs, 0)) : "—"}</td></tr></tfoot>
    </table>`;
  const arquivo = `sugestao-metas-${d.estado}-${m.meta}`;
  return `
  <section class="cartao secao entra" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone("pessoas")}Resumo dos vendedores do ${esc(d.estado)}</h3>
        <p class="sub">Todos os vendedores do seu acesso, sem os filtros de vendedor e área · clique num vendedor para ver só ele · a meta lançada é a META FATURAMENTO da METAS.xlsx</p></div>
      <div class="acoes-relatorio">
        <button class="btn" data-captura="copiar" data-arquivo="${arquivo}" title="Copia a tabela como imagem para colar no WhatsApp">${icone("disco")}Copiar imagem</button>
        <button class="btn icone" data-captura="baixar" data-arquivo="${arquivo}" title="Baixar a tabela como imagem (PNG)">${icone("abaixo")}</button>
      </div>
    </div>
    <div class="tabela-rolagem relatorio-rolagem"><div class="relatorio">${corpo}</div></div>
  </section>`;
}

// ---------- como é calculado ----------
function comoCalcula(d, i) {
  const p = d.parametros, m = d.mes, ba = d.estado === "BA";
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como a sugestão é calculada</h3>
        <span class="sub">A conta das páginas de sugestão do Power BI, passo a passo, com os números em vigor</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Carteira de hoje:</b> entram as vendas e devoluções dos clientes que estão hoje na carteira de cada vendedor,
            com o histórico inteiro deles (cliente repassado leva o histórico para o vendedor novo). No BA a área é a área atual
            do cliente. A conta é por <b>${esc(p.grao)}</b>.</li>
          <li><b>Volume do mês base (${esc(m.rotulo_base)}):</b> vendas válidas menos as devoluções que descontam (motivos e
            canceladas como nas Configurações das metas), com as equivalências de produto. Produtos "não conta" ficam fora.</li>
          <li><b>Por faturamento:</b> o volume do mês base é dividido pelos faturamentos dele (${ba
            ? "os da área: cada dia de atendimento, de Gestão › Configurar, é faturado no prazo da área, em geral o dia útil seguinte (Eunápolis fatura dois dias úteis depois); áreas quinzenais têm número fixo e qualquer área pode ser ajustada num mês em Configurar"
            : "os dias úteis do ES, com os feriados e os extras das Configurações das metas"}).</li>
          <li><b>Sazonalidade:</b> o ritmo de ${esc(p.meta_ly)} sobre o de ${esc(p.base_ly)}, por faturamento. Sem venda no ano
            passado vale 1 (sem ajuste); o teto é <b>+${fmt.pct(p.teto_sazonalidade, 0)}</b>; uma queda no ano passado reduz a meta.</li>
          <li><b>Crescimento proposto:</b> ${fmt.pct(p.crescimento, 0)} no ano menos o acumulado de ${esc(p.acumulado.de)} a
            ${esc(p.acumulado.ate)} sobre ${esc(p.acumulado.de_ly)} a ${esc(p.acumulado.ate_ly)}, entre <b>0%</b> e
            <b>+${fmt.pct(p.teto_crescimento, 0)}</b>. Quem já cresceu mais que ${fmt.pct(p.crescimento, 0)} no ano fica com 0%.</li>
          <li><b>Meta (volume):</b> por faturamento × sazonalidade × faturamentos de ${esc(m.rotulo_meta)} × crescimento proposto.</li>
          <li><b>Meta (R$):</b> a meta em volume × o preço médio do mês base, que é o faturamento <b>bruto</b> ÷ o volume vendido
            (sem descontar devoluções). O total é a soma das linhas, e "todos os vendedores" é a soma da sugestão de cada um.</li>
        </ol>
        <h4>Diferenças em relação ao Power BI</h4>
        <ul class="metodo-passos">
          <li>Preço médio pelo faturamento bruto (o Power BI usava o líquido de todas as devoluções e dos brindes).</li>
          <li>Faturamentos calculados sozinhos, em vez da planilha "Quantidades Faturamentos.xlsx", com ajuste manual.</li>
          <li>Acumulado do ano até o mês base (em janeiro o Power BI dava +20% para todos).</li>
          <li>Devoluções canceladas não descontam, como no resto do painel; metas negativas contam como zero.</li>
        </ul>
      </div>
    </details>
  </section>`;
}
