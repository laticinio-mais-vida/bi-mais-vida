// Página Projeções: faturamento bruto dos próximos 6 meses (faturamento, mussarela e mix), com filtros de
// vendedores e produtos de seleção múltipla. A conta fica no servidor (bi/projecoes.py); aqui é a apresentação.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast } from "./util.js";
import { projecao } from "./graficos.js";
import { ligarCaptura } from "./relatorio.js";
import { ligarTelaCheia, sairTelaCheia } from "./telacheia.js";
import { multiSelecao } from "./multiselecao.js";

const SERIES = {
  fat: { nome: "Faturamento", icone: "moeda", cor: "var(--s-fat)" },
  mus: { nome: "Mussarela", icone: "queijo", cor: "var(--s-mus)" },
  mix: { nome: "Mix", icone: "leite", cor: "var(--s-out)" },
};
const MESES_HISTORICO = 15;
const METODO = {
  modelo: "modelo completo na série",
  combinado: "média entre o modelo na série filtrada e a participação no total",
  participacao: "participação nos últimos 6 meses sobre a projeção do total (histórico curto)",
};

let ctx = null;
let filtroV = null, filtroP = null;
const estado = { vendedores: [], produtos: [], dados: null, pedido: 0 };

export function montarProjecoes(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const ids = (t) => (t || "").split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0);
  if (q.has("v") || q.has("p")) {
    estado.vendedores = ids(q.get("v"));
    estado.produtos = ids(q.get("p"));
  } else if (!estado.dados) {
    const salvo = ler("mv-projecoes", {});
    estado.vendedores = Array.isArray(salvo.v) ? salvo.v : [];
    estado.produtos = Array.isArray(salvo.p) ? salvo.p : [];
  }
  estado.dados = null;

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("tendencia")}</span>
        <div><b>Próximos 6 meses</b><small>faturamento bruto, sem descontar devoluções</small></div></div>
      <div class="filtros">
        <div id="f-p-vendedores"></div>
        <div id="f-p-produtos"></div>
        <button class="btn btn-limpar" type="button" id="f-p-limpar" hidden>${icone("x")}Limpar filtros</button>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-projecoes" title="Configurações das projeções: vendedores da página e o que cada pessoa vê">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="p-avisos"></div>
    <div id="p-conteudo"><div class="grade secao">
      <div class="kpis n3"><div class="esqueleto" style="height:250px"></div><div class="esqueleto" style="height:250px"></div><div class="esqueleto" style="height:250px"></div></div>
      <div class="esqueleto" style="height:400px"></div></div>
    </div>`;

  filtroV = multiSelecao(container.querySelector("#f-p-vendedores"), {
    rotulo: "Vendedores", icone: "usuario", todos: "Todos os vendedores", plural: "vendedores",
    busca: "Buscar vendedor ou código", itens: [], selecionados: estado.vendedores,
    aoAplicar: (lista) => { estado.vendedores = lista; carregar(); },
  });
  filtroP = multiSelecao(container.querySelector("#f-p-produtos"), {
    rotulo: "Produtos", icone: "caixa", todos: "Todos os produtos", plural: "produtos",
    busca: "Buscar produto ou código", itens: [], selecionados: estado.produtos,
    aoAplicar: (lista) => { estado.produtos = lista; carregar(); },
  });
  container.querySelector("#f-p-limpar").addEventListener("click", () => {
    estado.vendedores = [];
    estado.produtos = [];
    filtroV.limpar();
    filtroP.limpar();
    carregar();
  });
  carregar();
}

export function recarregarProjecoes() { if (ctx) carregar(true); }

function atualizarUrl() {
  guardar("mv-projecoes", { v: estado.vendedores, p: estado.produtos });
  if (!location.hash.startsWith("#/projecoes")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams();
  if (estado.vendedores.length) p.set("v", estado.vendedores.join(","));
  if (estado.produtos.length) p.set("p", estado.produtos.join(","));
  history.replaceState(null, "", `#/projecoes${p.toString() ? "?" + p : ""}`);
  document.getElementById("f-p-limpar").hidden = !estado.vendedores.length && !estado.produtos.length;
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("p-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  sairTelaCheia();
  if (estado.dados) conteudo.classList.add("recarregando");
  atualizarUrl();
  try {
    const p = new URLSearchParams();
    if (estado.vendedores.length) p.set("vendedores", estado.vendedores.join(","));
    if (estado.produtos.length) p.set("produtos", estado.produtos.join(","));
    const d = await api(`/api/projecoes?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    estado.vendedores = d.filtros.vendedores;
    estado.produtos = d.filtros.produtos;
    atualizarUrl();
    preencherFiltros(d);
    ctx.subtitulo(d);
    document.getElementById("p-avisos").innerHTML = (d.avisos || [])
      .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
    conteudo.innerHTML = render(d);
    posRender(conteudo, d);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 400 && estado.vendedores.length) {
      // filtro guardado de outro acesso neste navegador: volta para todos os vendedores
      estado.vendedores = [];
      filtroV.limpar();
      toast(e.message, "erro");
      return carregar(silencioso);
    }
    if (e.status === 403) { // acesso sem nenhum vendedor nas Projeções
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
  filtroV.definir(
    op.vendedores.map((v) => ({ id: v.id, nome: v.nome, grupo: v.equipe, detalhe: `código ${v.id}` })),
    estado.vendedores,
    op.equipes.map((e) => ({ id: e.id, nome: `Equipe ${e.nome}` })),
  );
  const grupoProduto = (p) => (p.grupo === "mussarela" ? "mussarela" : `cat:${p.categoria || ""}`);
  filtroP.definir(
    op.produtos.map((p) => ({ id: p.id, nome: p.nome, grupo: grupoProduto(p), detalhe: `código ${p.id}${p.unidade ? ` · ${p.unidade}` : ""}` })),
    estado.produtos,
    [{ id: "mussarela", nome: "Mussarela" }, ...op.categorias.map((c) => ({ id: `cat:${c}`, nome: c })), { id: "cat:", nome: "Demais produtos do mix" }],
  );
}

// ---------- apoio ----------
const temSerie = (d, s) => (s === "fat" ? d.tem.mus || d.tem.mix : d.tem[s]);

function variacao(v) {
  if (v == null || !isFinite(v)) return "";
  const sobe = v >= 0;
  return `<span class="chip-variacao ${sobe ? "sobe" : "desce"}">${icone(sobe ? "tendencia" : "abaixo")}${sobe ? "+" : "−"}${fmt.pct(Math.abs(v))}</span>`;
}

function descricaoFiltro(d) {
  const nomes = (lista, opcoes, todos, plural) => {
    if (!lista.length) return todos;
    const n = lista.map((id) => opcoes.find((o) => o.id === id)?.nome || `código ${id}`);
    return n.length <= 3 ? n.join(", ") : `${n.length} ${plural}`;
  };
  return `${nomes(d.filtros.vendedores, d.opcoes.vendedores, "todos os vendedores do seu acesso", "vendedores")} · ` +
    nomes(d.filtros.produtos, d.opcoes.produtos, "todos os produtos", "produtos");
}

// ---------- estrutura ----------
function render(d) {
  let h = `<section class="kpis secao n3">${["fat", "mus", "mix"].map((s, i) => kpi(d, s, i + 1)).join("")}</section>`;
  h += `<section class="secao">${cartaoGrafico(d, "fat", 4)}</section>`;
  h += `<section class="duas-colunas iguais secao">${cartaoGrafico(d, "mus", 5)}${cartaoGrafico(d, "mix", 6)}</section>`;
  h += tabela(d, 7);
  h += comoCalcula(d, 8);
  return h;
}

function posRender(raiz, d) {
  ligarCaptura(raiz);
  ligarTelaCheia(raiz);
  animarContadores(raiz);
  animarEntradas(raiz);
  ligarTooltips(raiz);
  for (const s of Object.keys(SERIES)) {
    const el = raiz.querySelector(`#g-proj-${s}`);
    if (el) projecao(el, { pontos: pontos(d, s), cor: SERIES[s].cor, nome: SERIES[s].nome });
  }
}

function kpi(d, s, i) {
  const S = SERIES[s];
  const cab = `<div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(S.icone)}</span>${S.nome}</span>`;
  if (!temSerie(d, s)) {
    return `<article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${S.cor}">${cab}</div>
      <div class="kpi-corpo"><div><div class="kpi-valor kpi-na">Não se aplica</div>
      <div class="kpi-meta">O filtro escolhido não tem produtos de ${S.nome.toLowerCase()}.</div></div></div></article>`;
  }
  const r = d.resumo[s], ma = d.mes_atual;
  const linhas = [
    ["Média por mês", fmt.moedaC(r.media)],
    ["Faixa provável", `${fmt.moedaC(r.min)} a ${fmt.moedaC(r.max)}`],
    ["Mesmos meses do ano anterior", fmt.moedaC(r.ano_anterior)],
  ];
  if (ma) linhas.push([`${ma.rotulo} (em andamento)`, `${fmt.moedaC(ma[s].valor)} <span class="fraco">pelo ritmo</span>`]);
  linhas.push(["Erro médio do método", `±${fmt.pct(r.erro, 0)}`]);
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${S.cor}">
    ${cab}${r.variacao != null ? `<span data-tt="${esc(`<div class='tt-t'>Comparado aos mesmos meses do ano anterior</div>${fmt.moeda(r.total)} contra ${fmt.moeda(r.ano_anterior)}`)}">${variacao(r.variacao)}</span>` : ""}</div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor" data-contar="${r.total}" data-fmt="moedaC">R$ 0</div>
      <div class="kpi-meta">projetado de <b>${esc(d.periodo.de)}</b> a <b>${esc(d.periodo.ate)}</b>${r.variacao != null ? ` · ${r.variacao >= 0 ? "acima" : "abaixo"} do ano anterior` : ""}</div>
      ${miniBarras(d, s)}
    </div></div>
    <div class="kpi-rodape">${linhas.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>
  </article>`;
}

// Os 6 meses projetados lado a lado, com o mesmo mês do ano anterior como traço.
function miniBarras(d, s) {
  const max = Math.max(...d.projecao.map((p) => Math.max(p[s].valor, p.ano_anterior[s] || 0))) || 1;
  return `<div class="mini-barras" style="--cor:${SERIES[s].cor}">${d.projecao.map((p) => {
    const tt = `<div class='tt-t'>${esc(p.rotulo)} · projeção</div><div class='tt-l'><span>Projeção</span><b>${fmt.moeda(p[s].valor)}</b></div>` +
      (p.ano_anterior[s] != null ? `<div class='tt-l'><span>Ano anterior</span><b>${fmt.moeda(p.ano_anterior[s])}</b></div>` : "");
    return `<span class="mb" data-tt="${esc(tt)}"><i style="height:${(p[s].valor / max) * 100}%"></i>${p.ano_anterior[s] != null ? `<em style="--a:${(p.ano_anterior[s] / max).toFixed(3)}"></em>` : ""}<small>${esc(p.rotulo.slice(0, 3))}</small></span>`;
  }).join("")}</div>`;
}

function pontos(d, s) {
  const saida = d.historico.slice(-MESES_HISTORICO).map((h) => ({
    rotulo: h.rotulo, tipo: "real", real: h[s], anterior: h.ano_anterior[s], dias: h.dias_uteis,
  }));
  const ma = d.mes_atual;
  if (ma) {
    saida.push({ rotulo: ma.rotulo, tipo: "atual", valor: ma[s].valor, min: ma[s].min, max: ma[s].max,
                 realizado: ma[s].realizado, anterior: ma.ano_anterior[s], dias: ma.dias_uteis });
  }
  d.projecao.forEach((p) => saida.push({ rotulo: p.rotulo, tipo: "proj", valor: p[s].valor, min: p[s].min, max: p[s].max,
                                          anterior: p.ano_anterior[s], dias: p.dias_uteis }));
  return saida;
}

function cartaoGrafico(d, s, i) {
  const S = SERIES[s];
  if (!temSerie(d, s)) {
    return `<article class="cartao entra vazio" style="--i:${i}">${icone(S.icone)}<p>${S.nome}: não se aplica ao filtro escolhido.</p></article>`;
  }
  return `
  <article class="cartao entra" style="--i:${i}">
    <div class="cartao-cab"><div>
      <h3>${icone(s === "fat" ? "grafico" : S.icone)}${S.nome}: realizado e projeção</h3>
      <p class="sub">Meses fechados${d.mes_atual ? ", o mês em andamento" : ""} e os próximos 6 · passe o mouse em cada mês</p>
    </div></div>
    <div class="legenda">
      <span class="item"><span class="traco" style="--c:${S.cor}"></span>Realizado</span>
      <span class="item"><span class="traco pontilhado" style="--c:${S.cor}"></span>Projeção</span>
      <span class="item"><span class="quadro faixa" style="--c:${S.cor}"></span>Faixa provável</span>
      <span class="item"><span class="traco" style="--c:var(--s-ritmo)"></span>Mesmo mês do ano anterior</span>
    </div>
    <div class="grafico" id="g-proj-${s}" style="margin-top:6px"></div>
  </article>`;
}

function tabela(d, i) {
  const series = ["mus", "mix"].filter((s) => d.tem[s]);
  const ma = d.mes_atual;
  const linhas = [];
  if (ma) linhas.push({ ...ma, rotulo: `${ma.rotulo} · em andamento`, dias: ma.dias_uteis, ant: ma.ano_anterior, atual: true });
  d.projecao.forEach((p) => linhas.push({ ...p, dias: p.dias_uteis, ant: p.ano_anterior }));
  const celula = (b) => (b ? fmt.moeda(b.valor) : "—");
  const faixa = (b) => (b ? `${fmt.moedaC(b.min)} a ${fmt.moedaC(b.max)}` : "—");
  const r = d.resumo;
  const corpo = `
    <div class="relatorio-cab">
      <img src="/img/logo-maisvida.png" alt="Mais Vida">
      <div>
        <div class="rt">Projeção do faturamento bruto · ${esc(d.periodo.de)} a ${esc(d.periodo.ate)}</div>
        <div class="rs">Dados até ${fmt.semana(d.data_ref)}, ${fmt.data(d.data_ref)} · ${esc(descricaoFiltro(d))}</div>
      </div>
    </div>
    <table class="relatorio-tabela proj-tabela">
      <thead><tr><th>Mês</th><th>Dias úteis</th>${series.map((s) => `<th>${SERIES[s].nome}</th>`).join("")}
        <th class="total">Faturamento</th><th>Faixa provável</th><th>Ano anterior</th><th>Variação</th></tr></thead>
      <tbody>${linhas.map((l) => `<tr class="${l.atual ? "atual" : ""}">
        <td class="rotulo">${esc(l.rotulo)}${l.atual ? `<small>vendido até agora ${fmt.moedaC(l.fat.realizado)} · fechamento pelo ritmo</small>` : ""}</td>
        <td>${fmt.dias(l.dias)}</td>
        ${series.map((s) => `<td>${celula(l[s])}</td>`).join("")}
        <td class="total">${celula(l.fat)}</td>
        <td class="fraco">${faixa(l.fat)}</td>
        <td>${l.ant.fat != null ? fmt.moeda(l.ant.fat) : "—"}</td>
        <td>${l.ant.fat ? variacao(l.fat.valor / l.ant.fat - 1) : "—"}</td>
      </tr>`).join("")}</tbody>
      <tfoot><tr>
        <td class="rotulo">Total dos 6 meses</td><td>${fmt.dias(d.projecao.reduce((a, p) => a + p.dias_uteis, 0))}</td>
        ${series.map((s) => `<td>${fmt.moeda(r[s].total)}</td>`).join("")}
        <td class="total">${fmt.moeda(r.fat.total)}</td>
        <td class="fraco">${fmt.moedaC(r.fat.min)} a ${fmt.moedaC(r.fat.max)}</td>
        <td>${r.fat.ano_anterior != null ? fmt.moeda(r.fat.ano_anterior) : "—"}</td>
        <td>${variacao(r.fat.variacao) || "—"}</td>
      </tr></tfoot>
    </table>`;
  const arquivo = `projecao-${d.projecao[0].ano}-${String(d.projecao[0].mes).padStart(2, "0")}`;
  return `
  <section class="cartao secao entra" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone("calendario")}Mês a mês</h3><p class="sub">Valores projetados com a faixa provável e o mesmo mês do ano anterior</p></div>
      <div class="acoes-relatorio">
        <button class="btn" data-captura="copiar" data-arquivo="${arquivo}" title="Copia a tabela como imagem para colar no WhatsApp">${icone("disco")}Copiar imagem</button>
        <button class="btn icone" data-captura="baixar" data-arquivo="${arquivo}" title="Baixar a tabela como imagem (PNG)">${icone("abaixo")}</button>
      </div>
    </div>
    <div class="tabela-rolagem relatorio-rolagem"><div class="relatorio">${corpo}</div></div>
  </section>`;
}

function comoCalcula(d, i) {
  const pr = d.parametros;
  const meses = [...(d.mes_atual ? [d.mes_atual.rotulo] : []), ...d.projecao.map((p) => p.rotulo)];
  const linhaErro = (s) => (temSerie(d, s)
    ? `<tr><td class="rotulo">${SERIES[s].nome}</td>${d.resumo[s].erro_por_distancia.map((e) => `<td>±${fmt.pct(e, 0)}</td>`).join("")}</tr>` : "");
  const metodos = ["mus", "mix"].filter((s) => d.tem[s]).map((s) => `<b>${SERIES[s].nome}</b>: ${METODO[d.metodo[s]]}`).join(" · ");
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como a projeção é calculada</h3>
        <span class="sub">O passo a passo e quanto o método errou quando foi testado nos meses passados</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Base:</b> faturamento bruto de cada mês desde ${esc(pr.inicio || "o início do cache")}, ou seja, todas as vendas
            válidas <b>sem descontar as devoluções</b> (por isso fica acima do realizado da página de Metas). Valem as
            equivalências de produto das Configurações, os produtos marcados como "não conta" ficam fora e entram as
            equipes ES, BA e Edir.</li>
          <li><b>Por dia útil:</b> cada mês é dividido pelos dias úteis do calendário (feriados de ES e BA e os extras das
            Configurações), para meses curtos ou com feriado não parecerem queda de venda.</li>
          <li><b>Dois métodos, e a média deles:</b> (a) o mesmo mês do ano anterior × o crescimento dos últimos 12 meses
            sobre os 12 anteriores; (b) a tendência dos últimos ${pr.janela_tendencia} meses, sem a sazonalidade e amortecida
            (a inclinação perde ${fmt.pct(1 - pr.amortecimento, 0)} a cada mês à frente), × o fator de sazonalidade do mês.
            O resultado volta para reais multiplicando pelos dias úteis de cada mês futuro.</li>
          <li><b>Com filtro de vendedor ou produto:</b> média entre o modelo aplicado só ao filtro e a projeção do total ×
            a participação do filtro nos últimos ${pr.janela_participacao} meses. Se o filtro não tiver ${pr.meses_modelo}
            meses seguidos de vendas (vendedor ou produto novo), vale só a participação.</li>
          <li><b>Faixa provável:</b> o método foi refeito para os últimos ${pr.origens_teste} meses usando só o que se sabia
            antes de cada um, e a faixa é o erro médio dessas tentativas para cada distância.</li>
          <li><b>Mês em andamento:</b> o realizado até agora mais o fechamento pelo ritmo (realizado ÷ dias úteis passados ×
            dias úteis do mês), igual à projeção da página de Metas, mas sobre o bruto.</li>
        </ol>
        <h4>Erro médio do método para este filtro, por mês projetado</h4>
        <div class="tabela-rolagem"><table class="dados erro-tabela">
          <thead><tr><th></th>${meses.map((m) => `<th>${esc(m)}</th>`).join("")}</tr></thead>
          <tbody>${linhaErro("fat")}${linhaErro("mus")}${linhaErro("mix")}</tbody>
        </table></div>
        ${metodos ? `<p class="usu-nota">${icone("info")}<span>Neste filtro: ${metodos}.</span></p>` : ""}
      </div>
    </details>
  </section>`;
}
