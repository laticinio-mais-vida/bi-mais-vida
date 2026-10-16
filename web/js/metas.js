// Página Metas: uma página só, com as visões do Power BI (ES, BA, Edir, Outras Linhas ES, Produtos BA)
// como abas, mais os filtros de vendedores, meses e anos, todos de seleção múltipla (nada marcado = todos).
// Vários meses somam metas e realizados, como uma segmentação do Power BI; a conta fica em bi/metas.py.
import {
  api, esc, fmt, icone, chipStatus, STATUS, corStatus, MESES, animarContadores, animarEntradas,
  ligarTooltips, linhaTT, guardar, ler, toast,
} from "./util.js";
import { anel, corrida, ranking, barras } from "./graficos.js";
import { relatorioVendedores, relatorioProdutos, ligarCaptura } from "./relatorio.js";
import { ligarTelaCheia, sairTelaCheia } from "./telacheia.js";
import { multiSelecao } from "./multiselecao.js";

const ICONE_VISAO = { es: "mapa", ba: "mapa", edir: "usuario", outras_es: "leite", produtos_ba: "caixa" };
const COR = { fat: "var(--s-fat)", mus: "var(--s-mus)", out: "var(--s-out)", cli: "var(--k-cli)", vm: "var(--k-vm)" };
const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const nomeMes = (m) => MESES[m - 1][0].toUpperCase() + MESES[m - 1].slice(1);

let ctx = null;
let filtroV = null, filtroM = null, filtroA = null;
// anos e meses: os marcados nos filtros ([] = todos); null = página ainda não aberta.
const estado = { visao: "es", anos: null, meses: null, vendedores: [], dados: null, metricaCorrida: null, pedido: 0 };

export function montarMetas(container, contexto) {
  ctx = contexto;
  const op = ctx.opcoes;
  if (!op.visoes.length) {
    container.innerHTML = `<div class="cartao secao vazio">${icone("cadeado")}<p>Seu acesso ainda não tem nenhuma aba de Metas liberada. Fale com o administrador.</p></div>`;
    document.getElementById("subtitulo-pagina").innerHTML = "<span>Nenhuma aba liberada</span>";
    return;
  }
  const salvo = ler("mv-filtros", {});
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const nums = (t) => (t || "").split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0);
  const padrao = (k) => (op.padrao ? [op.padrao[k]] : []);
  const temFiltroNaUrl = q.has("visao");
  estado.visao = q.get("visao") || (estado.anos ? estado.visao : salvo.visao) || "es";
  if (!op.visoes.some((v) => v.id === estado.visao)) estado.visao = op.visoes[0].id; // só as visões do acesso
  if (temFiltroNaUrl) { // aceita também o endereço antigo (ano, mes e um vendedor só)
    estado.anos = q.has("anos") ? nums(q.get("anos")) : q.has("ano") ? nums(q.get("ano")) : padrao("ano");
    estado.meses = q.has("meses") ? nums(q.get("meses")) : q.has("mes") ? nums(q.get("mes")) : padrao("mes");
    estado.vendedores = nums(q.get("v"));
  } else if (!estado.anos) {
    estado.anos = padrao("ano");
    estado.meses = padrao("mes");
  }
  estado.dados = null;

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="visoes" role="tablist" aria-label="Visões">
        <span class="indicador"></span>
        ${op.visoes.map((v) => `<button class="visao" role="tab" data-visao="${v.id}">${icone(ICONE_VISAO[v.id] || "alvo")}${esc(v.titulo)}</button>`).join("")}
      </div>
      <div class="filtros">
        <div id="f-vendedores"></div>
        <div id="f-meses"></div>
        <div id="f-anos"></div>
        ${ctx.admin ? `<a class="btn btn-config" href="#/configuracoes" title="Configurações das metas: produtos, vendedores, devoluções, dias úteis e acesso por usuário">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="m-avisos"></div>
    <div id="m-conteudo"><div class="grade secao">
      <div class="esqueleto" style="height:150px"></div>
      <div class="kpis"><div class="esqueleto" style="height:220px"></div><div class="esqueleto" style="height:220px"></div><div class="esqueleto" style="height:220px"></div></div>
      <div class="esqueleto" style="height:360px"></div></div>
    </div>`;

  filtroV = multiSelecao(container.querySelector("#f-vendedores"), {
    rotulo: "Vendedores", icone: "usuario", todos: "Todos os vendedores", plural: "vendedores",
    busca: "Buscar vendedor ou código", itens: [], selecionados: estado.vendedores,
    aoAplicar: (lista) => { estado.vendedores = lista; carregar(); },
  });
  const aoMudarPeriodo = () => { ajustarPeriodo(); preencherPeriodo(); carregar(); };
  filtroM = multiSelecao(container.querySelector("#f-meses"), {
    rotulo: "Meses", icone: "calendario", todos: "Todos os meses", plural: "meses", semBusca: true, nomesAte: 3,
    classe: "curto", itens: [], selecionados: estado.meses,
    aoAplicar: (lista) => { estado.meses = lista; aoMudarPeriodo(); },
  });
  filtroA = multiSelecao(container.querySelector("#f-anos"), {
    rotulo: "Anos", icone: "funil", todos: "Todos os anos", plural: "anos", semBusca: true, nomesAte: 3,
    classe: "curto", itens: [], selecionados: estado.anos,
    aoAplicar: (lista) => { estado.anos = lista; aoMudarPeriodo(); },
  });

  container.querySelectorAll(".visao").forEach((b) => b.addEventListener("click", () => {
    if (estado.visao === b.dataset.visao) return;
    estado.visao = b.dataset.visao;
    estado.vendedores = [];
    filtroV.limpar();
    estado.metricaCorrida = null;
    ajustarPeriodo();
    preencherPeriodo();
    carregar();
  }));
  window.addEventListener("resize", posicionarIndicador);

  ajustarPeriodo();
  preencherPeriodo();
  carregar();
}

export function recarregarMetas() { if (ctx && filtroV) carregar(true); }

function mesesDaVisao() {
  return estado.visao === "produtos_ba" ? ctx.opcoes.meses_produtos : ctx.opcoes.meses;
}

// Meses com metas que entram no filtro: os anos marcados × os meses marcados (vazio = todos).
function periodos() {
  return mesesDaVisao().filter((m) => (!estado.anos.length || estado.anos.includes(m.ano)) &&
                                      (!estado.meses.length || estado.meses.includes(m.mes)));
}

// Tira do filtro o que não existe nesta aba. Se um filtro com marcação ficar vazio (que seria "todos"), volta
// para o mês padrão (o dos dados) ou o último com metas.
function ajustarPeriodo() {
  const disp = mesesDaVisao();
  if (!disp.length) return;
  const p = ctx.opcoes.padrao;
  const anosDisp = [...new Set(disp.map((m) => m.ano))];
  const tinhaAnos = estado.anos.length > 0, tinhaMeses = estado.meses.length > 0;
  estado.anos = estado.anos.filter((a) => anosDisp.includes(a));
  if (tinhaAnos && !estado.anos.length) estado.anos = [p && anosDisp.includes(p.ano) ? p.ano : anosDisp[anosDisp.length - 1]];
  const doAno = [...new Set(disp.filter((m) => !estado.anos.length || estado.anos.includes(m.ano)).map((m) => m.mes))];
  estado.meses = estado.meses.filter((m) => doAno.includes(m));
  if (tinhaMeses && !estado.meses.length) {
    const padraoServe = p && doAno.includes(p.mes) && (!estado.anos.length || estado.anos.includes(p.ano));
    estado.meses = [padraoServe ? p.mes : Math.max(...disp.filter((m) => !estado.anos.length || estado.anos.includes(m.ano)).map((m) => m.mes))];
  }
}

function preencherPeriodo() {
  const disp = mesesDaVisao();
  const anos = [...new Set(disp.map((m) => m.ano))].sort((a, b) => b - a);
  filtroA.definir(anos.map((a) => ({ id: a, nome: String(a) })), estado.anos);
  const meses = [...new Set(disp.filter((m) => !estado.anos.length || estado.anos.includes(m.ano)).map((m) => m.mes))].sort((a, b) => a - b);
  filtroM.definir(meses.map((m) => ({ id: m, nome: nomeMes(m), curto: MESES[m - 1].slice(0, 3) })), estado.meses);
  document.querySelectorAll(".visao").forEach((b) => b.classList.toggle("ativa", b.dataset.visao === estado.visao));
  posicionarIndicador();
}

function preencherVendedores(lista) {
  filtroV.definir(lista.map((v) => ({
    id: v.id, nome: v.nome,
    detalhe: `código ${v.id}${v.nome_erp && v.nome_erp.toLowerCase() !== v.nome.toLowerCase() ? ` · ERP: ${v.nome_erp}` : ""}`,
  })), estado.vendedores);
}

// Clique num vendedor (ranking, tabela, cartões): mostra só ele; de novo, volta para todos.
// Com Ctrl (ou Cmd no Mac), soma ou tira o vendedor dos que já estão marcados.
function escolherVendedor(id, ev) {
  const atual = new Set(estado.vendedores);
  if (ev && (ev.ctrlKey || ev.metaKey)) atual.has(id) ? atual.delete(id) : atual.add(id);
  else if (atual.size === 1 && atual.has(id)) atual.clear();
  else { atual.clear(); atual.add(id); }
  estado.vendedores = [...atual];
  carregar();
}

function posicionarIndicador() {
  const ativo = document.querySelector(".visao.ativa");
  const ind = document.querySelector(".visoes .indicador");
  if (!ativo || !ind) return;
  const primeira = !ind.style.width;
  if (primeira) ind.style.transition = "none";
  ind.style.transform = `translate(${ativo.offsetLeft}px, ${ativo.offsetTop}px)`;
  ind.style.width = ativo.offsetWidth + "px";
  ind.style.height = ativo.offsetHeight + "px";
  if (primeira) { void ind.offsetWidth; ind.style.transition = ""; }
}

function atualizarUrl() {
  const p = new URLSearchParams({ visao: estado.visao, anos: estado.anos.join(","), meses: estado.meses.join(",") });
  if (estado.vendedores.length) p.set("v", estado.vendedores.join(","));
  history.replaceState(null, "", `#/metas?${p}`);
  guardar("mv-filtros", { visao: estado.visao });
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("m-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  sairTelaCheia();
  if (estado.dados) conteudo.classList.add("recarregando");
  atualizarUrl();
  try {
    const lista = periodos();
    if (!lista.length) throw new Error("não há metas cadastradas para esta aba");
    const p = new URLSearchParams({ visao: estado.visao, meses: lista.map((m) => `${m.ano}-${m.mes}`).join(",") });
    if (estado.vendedores.length) p.set("vendedores", estado.vendedores.join(","));
    const d = await api(`/api/visao?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    const validos = estado.vendedores.filter((id) => d.vendedores.some((v) => v.id === id));
    if (validos.length !== estado.vendedores.length) { // vendedor sem meta nos meses escolhidos
      estado.vendedores = validos;
      return carregar(silencioso);
    }
    preencherVendedores(d.vendedores);
    ctx.subtitulo(d);
    renderAvisos(d);
    conteudo.innerHTML = d.visao.tipo === "produtos" ? renderProdutos(d) : renderVendedores(d);
    posRender(conteudo, d);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone("alerta")}<p>Não foi possível carregar: ${esc(e.message)}</p></div>`;
    if (!silencioso) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
  }
}

function renderAvisos(d) {
  document.getElementById("m-avisos").innerHTML = (d.avisos || [])
    .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
}

function posRender(raiz, d) {
  ligarCaptura(raiz);
  ligarTelaCheia(raiz);
  animarContadores(raiz);
  animarEntradas(raiz);
  ligarTooltips(raiz);
  if (d.visao.tipo !== "produtos") {
    desenharCorrida(d);
    const el = raiz.querySelector("#g-ranking");
    if (el) {
      const chave = d.visao.tipo === "outras" ? "outras" : "faturamento";
      ranking(el, d.linhas.map((l) => ({ id: l.id, nome: l.nome, ...l[chave] })), {
        ritmo: d.calendario.ritmo, situacao: d.calendario.situacao, aoClicar: escolherVendedor,
      });
      animarEntradas(el);
      ligarTooltips(el);
    }
    raiz.querySelectorAll(".seg-mini button").forEach((b) => b.addEventListener("click", () => {
      estado.metricaCorrida = b.dataset.m;
      raiz.querySelectorAll(".seg-mini button").forEach((x) => x.classList.toggle("ativo", x === b));
      const g = document.getElementById("g-corrida");
      delete g.dataset.desenhado;
      desenharCorrida(d);
    }));
  }
  raiz.querySelectorAll("[data-vendedor]").forEach((el) => el.addEventListener("click", (ev) => {
    escolherVendedor(Number(el.dataset.vendedor), ev);
  }));
}

const variosMeses = (d) => d.calendario.meses.length > 1;

// ======================================================================================
// Ritmo do mês (substitui o quadro "Dias úteis" do Power BI; calcula feriados sozinho)
// ======================================================================================
function faixaMeses(c) {
  const SITUACAO = { aberto: "em andamento", fechado: "encerrado", futuro: "ainda não começou" };
  return `<div class="faixa-meses" aria-label="Meses do período">
    ${c.meses.map((m, n) => {
      const pct = m.dias_uteis ? m.dias_decorridos / m.dias_uteis : 0;
      const tt = `<div class='tt-t'>${nomeMes(m.mes)} de ${m.ano} · ${SITUACAO[m.situacao]}</div>` +
        linhaTT("Dias úteis", fmt.dias(m.dias_uteis)) + linhaTT("Já passaram", fmt.dias(m.dias_decorridos));
      return `<div class="mes-r ${m.situacao} ${pct > 0.55 ? "cheio" : ""}" style="--i:${n}" data-tt="${esc(tt)}">
        <i style="height:${(pct * 100).toFixed(1)}%"></i><b>${MESES[m.mes - 1].slice(0, 3)}</b><small>${String(m.ano).slice(2)}</small></div>`;
    }).join("")}
  </div>`;
}

function renderRitmo(d, i = 0) {
  const c = d.calendario;
  const varios = variosMeses(d);
  const feriados = c.dias.filter((x) => x.tipo === "feriado" || x.tipo === "meio");
  const textos = {
    aberto: `Hoje cada meta${varios ? " do período" : ""} precisa estar em pelo menos <b>${fmt.pct(c.ritmo)}</b> para estar no ritmo.`,
    fechado: `${varios ? "Período encerrado" : "Mês encerrado"}: o ritmo esperado agora é 100% da meta.`,
    futuro: varios ? "Este período ainda não começou." : "Este mês ainda não começou.",
  };
  const MAX_FERIADOS = 4;
  const chipsFeriados = feriados.slice(0, MAX_FERIADOS).map((f) => `<span class="chip laranja">★ ${fmt.dataCurta(f.data)} · ${esc(f.motivo)}</span>`).join("") +
    (feriados.length > MAX_FERIADOS ? `<span class="chip laranja">+${feriados.length - MAX_FERIADOS} feriados</span>` : "");
  return `
  <section class="cartao ritmo secao entra" style="--i:${i}">
    <div>
      <div class="cartao-cab"><div>
        <h2>${icone("calendario")}Ritmo do ${varios ? "período" : "mês"}</h2>
        <p class="sub">${esc(d.periodo.rotulo)} · calendário ${c.regiao === "ES" ? "do Espírito Santo" : "da Bahia"}</p>
      </div></div>
      <div class="ritmo-numero"><span class="grande" data-contar="${c.dias_decorridos}" data-fmt="dias">0</span><span class="de">de ${fmt.dias(c.dias_uteis)} dias úteis</span></div>
      <div class="ritmo-legenda">${textos[c.situacao]}</div>
      <div class="ritmo-barra"><span data-largura="${c.ritmo * 100}%"></span></div>
    </div>
    ${varios ? faixaMeses(c) : `<div class="faixa-dias" aria-label="Dias do mês">
      ${c.dias.map((x, n) => {
        const dia = Number(x.data.slice(8));
        const dow = new Date(x.data + "T12:00").getDay();
        const sem = SEMANA[dow];
        const classes = [x.tipo, x.passou ? "passou" : "", x.data === d.data_ref ? "hoje" : ""].join(" ");
        const col = n === 0 ? `;--col:${((dow + 6) % 7) + 1}` : "";
        const tt = `<div class='tt-t'>${fmt.dataCurta(x.data)} · ${fmt.semana(x.data)}</div>` +
          linhaTT("Situação", x.motivo ? esc(x.motivo) : "Dia útil") +
          linhaTT("Conta como", x.peso === 1 ? "1 dia útil" : x.peso ? `${fmt.dias(x.peso)} dia útil` : "não conta");
        return `<div class="dia ${classes}" style="--i:${n}${col}" data-tt="${esc(tt)}">${dia}<span class="sem">${sem}</span></div>`;
      }).join("")}
    </div>`}
    <div>
      <div class="ritmo-stats">
        <div class="mini-stat"><div class="r">Ritmo esperado</div><div class="v">${fmt.pct(c.ritmo)}</div></div>
        <div class="mini-stat"><div class="r">Dias úteis restantes</div><div class="v">${fmt.dias(c.dias_restantes)}</div></div>
      </div>
      <div class="feriados-lista">
        ${feriados.length ? chipsFeriados : `<span class="chip">Sem feriados neste ${varios ? "período" : "mês"}</span>`}
        <span class="chip">Dados até ${fmt.dataCurta(d.data_ref)}</span>
      </div>
    </div>
  </section>`;
}

// ======================================================================================
// Visões por vendedor (Metas ES, BA, Edir e Outras Linhas ES)
// ======================================================================================
function kpi({ i, titulo, ic, cor, ind, tipo = "moeda", cal, extra = "" }) {
  const f = tipo === "moeda" ? "moedaC" : "num";
  const v = tipo === "moeda" ? fmt.moedaC : fmt.num;
  const linhas = [];
  if (ind.meta && cal.situacao === "aberto") linhas.push(["Esperado até hoje", v(ind.esperado)]);
  if (tipo === "moeda" && ind.projecao != null && cal.situacao === "aberto") linhas.push([cal.meses.length > 1 ? "Projeção do período" : "Projeção do mês", `${v(ind.projecao)} <span style="color:var(--tinta-3)">(${fmt.pct(ind.projecao_pct, 0)})</span>`]);
  if (ind.falta != null) {
    linhas.push([ind.falta > 0 ? "Falta para a meta" : "Meta", ind.falta > 0 ? v(ind.falta) : "alcançada"]);
    if (ind.falta_por_dia) linhas.push(["Necessário por dia útil", v(ind.falta_por_dia)]);
  }
  return `
  <article class="cartao kpi entra" style="--i:${i};--cor:${cor}">
    <div class="kpi-cab">
      <span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${esc(titulo)}</span>
      ${ind.meta ? chipStatus(ind.status) : chipStatus("sem_meta")}
    </div>
    <div class="kpi-corpo">
      ${anel({ pct: ind.pct, ritmo: cal.situacao === "aberto" ? cal.ritmo : null, cor })}
      <div>
        <div class="kpi-valor" data-contar="${ind.realizado}" data-fmt="${f}">0</div>
        <div class="kpi-meta">meta <b>${ind.meta ? v(ind.meta) : "não definida"}</b></div>
        ${extra}
      </div>
    </div>
    ${linhas.length ? `<div class="kpi-rodape">${linhas.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function kpiVendaMedia(i, vm) {
  const pct = vm.pct;
  const escala = Math.max(1.25, (pct || 0) * 1.05);
  const st = vm.meta ? (pct >= 1 ? "batida" : pct >= 0.9 ? "atencao" : "abaixo") : "sem_meta";
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:var(--k-vm)">
    <div class="kpi-cab">
      <span class="kpi-rotulo"><span class="kpi-icone">${icone("recibo")}</span>Venda média por cliente</span>
      ${chipStatus(st, st === "batida" ? "Acima da meta" : st === "atencao" ? "Perto da meta" : st === "abaixo" ? "Abaixo da meta" : "Sem meta")}
    </div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor" data-contar="${vm.realizado || 0}" data-fmt="moeda">0</div>
      <div class="kpi-meta">meta <b>${fmt.moeda(vm.meta)}</b> · ${fmt.pct(pct)} da meta</div>
      <div class="medidor">
        <div class="medidor-trilho"><span class="enche" data-largura="${(Math.min(pct || 0, escala) / escala) * 100}%"></span><span class="alvo" style="left:${(1 / escala) * 100}%"></span></div>
        <div class="medidor-escala"><span>R$ 0</span><span>meta</span></div>
      </div>
    </div></div>
    <div class="kpi-rodape"><div class="linha-r"><span>Como é calculada</span><b>faturamento ÷ clientes</b></div></div>
  </article>`;
}

function kpiComposicao(i, ind) {
  const mus = ind.mussarela.realizado, out = ind.outras.realizado, tot = mus + out || 1;
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:var(--s-mus)">
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone("queijo")}</span>Composição do faturamento</span></div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor" data-contar="${mus / tot}" data-fmt="pct0">0%</div>
      <div class="kpi-meta">do faturamento é <b>mussarela</b></div>
      <div class="composicao">
        <span style="--c:var(--s-mus)" data-largura="${(mus / tot) * 100}%"></span><span style="--c:var(--s-out)" data-largura="${(out / tot) * 100}%"></span>
      </div>
      <div class="legenda" style="margin-top:8px">
        <span class="item"><span class="quadro" style="--c:var(--s-mus)"></span>Mussarela ${fmt.moedaC(mus)}</span>
        <span class="item"><span class="quadro" style="--c:var(--s-out)"></span>Outras linhas ${fmt.moedaC(out)}</span>
      </div>
    </div></div>
  </article>`;
}

function kpiContagem(i, d) {
  const chave = d.visao.tipo === "outras" ? "outras" : "faturamento";
  const tot = d.linhas.length;
  const ok = d.linhas.filter((l) => ["batida", "no_ritmo"].includes(l[chave].status)).length;
  const at = d.linhas.filter((l) => l[chave].status === "atencao").length;
  const ru = tot - ok - at;
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:var(--verde)">
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone("pessoas")}</span>Vendedores dentro da meta</span></div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor"><span data-contar="${ok}" data-fmt="num">0</span> <span style="font-size:20px;color:var(--tinta-3)">de ${tot}</span></div>
      <div class="kpi-meta">no ritmo ou com a meta batida</div>
      <div class="segmentos" style="height:10px;margin-top:12px">
        ${ok ? `<i class="ok" style="--f:${ok}"></i>` : ""}${at ? `<i class="at" style="--f:${at}"></i>` : ""}${ru ? `<i class="ru" style="--f:${ru}"></i>` : ""}
      </div>
      <div class="legenda" style="margin-top:8px">
        <span class="item">${chipStatus("no_ritmo", `${ok} no ritmo`)}</span>
        <span class="item">${chipStatus("atencao", `${at} atenção`)}</span>
        <span class="item">${chipStatus("abaixo", `${ru} abaixo`)}</span>
      </div>
    </div></div>
  </article>`;
}

function renderVendedores(d) {
  const ind = d.indicadores, cal = d.calendario, tipo = d.visao.tipo;
  const unico = d.linhas.length === 1;
  let h = renderRitmo(d, 0);
  if (!d.linhas.length) {
    return h + `<div class="cartao secao vazio entra" style="--i:1">${icone("usuario")}<p>Nenhum vendedor desta visão tem meta em ${esc(d.periodo.rotulo)}.</p></div>`;
  }
  const cards = [];
  if (tipo === "completa") {
    cards.push(kpi({ i: 1, titulo: "Faturamento", ic: "moeda", cor: COR.fat, ind: ind.faturamento, cal }));
    cards.push(kpi({ i: 2, titulo: "Mussarela", ic: "queijo", cor: COR.mus, ind: ind.mussarela, cal }));
    cards.push(kpi({ i: 3, titulo: "Outras linhas", ic: "leite", cor: COR.out, ind: ind.outras, cal }));
    cards.push(kpi({ i: 4, titulo: "Clientes atendidos", ic: "pessoas", cor: COR.cli, ind: ind.clientes, tipo: "num", cal }));
    cards.push(kpiVendaMedia(5, ind.venda_media));
  } else if (tipo === "faturamento") {
    cards.push(kpi({ i: 1, titulo: "Faturamento", ic: "moeda", cor: COR.fat, ind: ind.faturamento, cal }));
    cards.push(kpi({ i: 2, titulo: "Clientes atendidos", ic: "pessoas", cor: COR.cli, ind: ind.clientes, tipo: "num", cal }));
    cards.push(kpiVendaMedia(3, ind.venda_media));
    cards.push(kpiComposicao(4, ind));
  } else {
    cards.push(kpi({ i: 1, titulo: "Outras linhas", ic: "leite", cor: COR.out, ind: ind.outras, cal }));
    if (!unico) cards.push(kpiContagem(2, d));
    const cats = d.categorias.lista.map((c) => [c, d.categorias.total[c]]).sort((a, b) => b[1] - a[1]);
    if (cats.length) {
      cards.push(`<article class="cartao kpi kpi-simples entra" style="--i:3;--cor:var(--s-out)">
        <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone("etiqueta")}</span>Categoria que mais vende</span></div>
        <div class="kpi-corpo"><div>
          <div class="kpi-valor" style="font-size:28px">${esc(cats[0][0])}</div>
          <div class="kpi-meta"><b>${fmt.moedaC(cats[0][1])}</b> · ${fmt.pct(cats[0][1] / (ind.outras.realizado || 1))} das outras linhas</div>
        </div></div>
        <div class="kpi-rodape">${cats.slice(1, 3).map(([c, v]) => `<div class="linha-r"><span>${esc(c)}</span><b>${fmt.moedaC(v)}</b></div>`).join("")}</div>
      </article>`);
    }
  }
  h += `<section class="kpis secao n${cards.length}">${cards.join("")}</section>`;

  // corrida + ranking/composição
  const metricas = tipo === "completa"
    ? [["fat", "Faturamento"], ["mus", "Mussarela"], ["out", "Outras linhas"]]
    : tipo === "outras" ? [["out", "Outras linhas"]] : [["fat", "Faturamento"]];
  if (!estado.metricaCorrida || !metricas.some((m) => m[0] === estado.metricaCorrida)) estado.metricaCorrida = metricas[0][0];
  h += `<section class="duas-colunas secao">
    <article class="cartao entra" style="--i:6">
      <div class="cartao-cab">
        <div><h3>${icone("grafico")}Corrida da meta</h3><p class="sub">Acumulado no ${variosMeses(d) ? "período (os meses um depois do outro)" : "mês"} comparado ao ritmo esperado de cada dia útil</p></div>
        ${metricas.length > 1 ? `<div class="seg-mini">${metricas.map(([k, n]) => `<button data-m="${k}" class="${k === estado.metricaCorrida ? "ativo" : ""}">${n}</button>`).join("")}</div>` : ""}
      </div>
      <div class="legenda" id="leg-corrida"></div>
      <div class="grafico" id="g-corrida" style="margin-top:8px"></div>
    </article>`;
  if (unico) {
    const l = d.linhas[0];
    const itens = [{ nome: "Mussarela", valor: l.mussarela.realizado, cor: COR.mus, icone: "queijo" }, { nome: "Outras linhas", valor: l.outras.realizado, cor: COR.out, icone: "leite" }];
    const cats = d.categorias.lista.map((c) => ({ nome: c, valor: l.categorias[c] })).concat([{ nome: "Demais produtos", valor: l.demais }]).filter((c) => c.valor);
    h += `<article class="cartao entra" style="--i:7">
      <div class="cartao-cab"><div><h3>${icone("queijo")}Composição de ${esc(l.nome)}</h3><p class="sub">Faturamento líquido no ${variosMeses(d) ? "período" : "mês"}</p></div></div>
      ${barras(itens, { total: l.faturamento.realizado })}
      <h4 style="margin:20px 0 10px;font-size:14px;color:var(--tinta-2)">Outras linhas por categoria</h4>
      ${barras(cats.sort((a, b) => b.valor - a.valor), { total: l.outras.realizado })}
    </article>`;
  } else {
    h += `<article class="cartao entra" style="--i:7">
      <div class="cartao-cab"><div><h3>${icone("ranking")}Ranking de vendedores</h3>
        <p class="sub">% da meta de ${tipo === "outras" ? "outras linhas" : "faturamento"} · clique para ver só o vendedor</p></div></div>
      <div id="g-ranking"></div>
    </article>`;
  }
  h += `</section>`;

  if ((tipo === "completa" || tipo === "outras") && !unico) h += renderCategorias(d, 8);
  h += relatorioVendedores(d, 9);
  return h;
}

function desenharCorrida(d) {
  const el = document.getElementById("g-corrida");
  if (!el) return;
  const m = estado.metricaCorrida || "fat";
  const ind = { fat: d.indicadores.faturamento, mus: d.indicadores.mussarela, out: d.indicadores.outras }[m];
  const nome = { fat: "Faturamento", mus: "Mussarela", out: "Outras linhas" }[m];
  const situacao = d.calendario.situacao;
  document.getElementById("leg-corrida").innerHTML = `
    <span class="item"><span class="traco" style="--c:${COR[m]}"></span>${nome} realizado</span>
    ${ind.meta ? `<span class="item"><span class="traco tracejado" style="--c:var(--s-ritmo)"></span>Ritmo esperado</span>
    <span class="item"><span class="traco" style="--c:var(--acento)"></span>Meta</span>` : ""}
    ${situacao === "aberto" ? `<span class="item"><span class="traco pontilhado" style="--c:${COR[m]}"></span>Projeção</span>` : ""}`;
  corrida(el, {
    diario: d.diario, dias: d.calendario.dias, meta: ind.meta, chave: `${m}_acum`, cor: COR[m],
    projecao: ind.projecao, situacao, nome,
  });
}

function renderCategorias(d, i) {
  const cats = d.categorias.lista;
  const total = d.indicadores.outras.realizado || 1;
  const itens = cats.map((c) => ({ nome: c, valor: d.categorias.total[c] })).concat([{ nome: "Demais produtos", valor: d.categorias.demais }])
    .sort((a, b) => b.valor - a.valor);
  const max = Math.max(1, ...d.linhas.flatMap((l) => cats.map((c) => l.categorias[c])));
  const celula = (v, nome, cat) => {
    const a = Math.max(0, v) / max;
    const fundo = `color-mix(in srgb, var(--s-out) ${Math.round(8 + a * 80)}%, var(--surface))`;
    const tinta = a > 0.55 ? "#fff" : "var(--tinta)";
    const tt = `<div class='tt-t'>${esc(nome)}</div>` + linhaTT(esc(cat), fmt.moeda(v));
    return `<td class="cel"><span style="background:${fundo};color:${tinta}" data-tt="${esc(tt)}">${v ? fmt.moedaC(v).replace("R$ ", "") : "—"}</span></td>`;
  };
  return `
  <section class="duas-colunas inverso secao">
    <article class="cartao entra" style="--i:${i}">
      <div class="cartao-cab"><div><h3>${icone("etiqueta")}Outras linhas por categoria</h3>
      <p class="sub">Categorias definidas em Configurações · total ${fmt.moedaC(d.indicadores.outras.realizado)}</p></div></div>
      ${barras(itens, { total })}
    </article>
    <article class="cartao entra" style="--i:${i + 1}">
      <div class="cartao-cab"><div><h3>${icone("pessoas")}Categorias por vendedor</h3><p class="sub">Quanto mais forte o azul, maior o valor (R$)</p></div></div>
      <div class="tabela-rolagem"><table class="dados calor">
        <thead><tr><th>Vendedor</th>${cats.map((c) => `<th style="text-align:center">${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${d.linhas.map((l, n) => `<tr style="--i:${n}"><td class="nome-v">${esc(l.nome)}</td>${cats.map((c) => celula(l.categorias[c], l.nome, c)).join("")}</tr>`).join("")}</tbody>
      </table></div>
    </article>
  </section>`;
}

// ======================================================================================
// Produtos BA (meta de volume por produto e vendedor)
// ======================================================================================
function renderProdutos(d) {
  const ind = d.indicadores, cal = d.calendario;
  let h = renderRitmo(d, 0);
  if (!d.produtos.length) {
    return h + `<div class="cartao secao vazio entra" style="--i:1">${icone("caixa")}<p>Não há metas de produtos para ${esc(d.periodo.rotulo)}.</p></div>`;
  }
  const simples = (i, titulo, ic, cor, valor, sub, st) => `
    <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
      <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${titulo}</span>${st ? chipStatus(st) : ""}</div>
      <div class="kpi-corpo"><div><div class="kpi-valor"><span data-contar="${valor}" data-fmt="num">0</span></div><div class="kpi-meta">${sub}</div></div></div>
    </article>`;
  h += `<section class="kpis secao n4">
    <article class="cartao kpi entra" style="--i:1;--cor:var(--s-out)">
      <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone("caixa")}</span>Atingimento médio</span></div>
      <div class="kpi-corpo">${anel({ pct: ind.atingimento, ritmo: cal.situacao === "aberto" ? cal.ritmo : null, cor: "var(--s-out)", rotulo: "média" })}
        <div><div class="kpi-valor"><span data-contar="${ind.produtos}" data-fmt="num">0</span></div><div class="kpi-meta">produtos com meta de volume</div></div></div>
      <div class="kpi-rodape"><div class="linha-r"><span>Ritmo esperado hoje</span><b>${fmt.pct(cal.situacao === "fechado" ? 1 : cal.ritmo)}</b></div></div>
    </article>
    ${simples(2, "No ritmo ou batidas", "certo", "var(--ok-forte)", ind.no_ritmo, `de ${ind.produtos} produtos · ${ind.batidas} já bateram`, "no_ritmo")}
    ${simples(3, "Atenção", "alerta", "var(--atencao-forte)", ind.atencao, "até 10% abaixo do ritmo", "atencao")}
    ${simples(4, "Abaixo do ritmo", "abaixo", "var(--ruim-forte)", ind.abaixo, "mais de 10% abaixo do ritmo", "abaixo")}
  </section>`;

  const filtrado = estado.vendedores.length > 0;
  if (d.resumo_vendedores.length > 1 || filtrado) {
    h += `<section class="cartao secao entra" style="--i:5">
      <div class="cartao-cab"><div><h3>${icone("pessoas")}Vendedores</h3><p class="sub">Média de atingimento das metas de produto · clique para detalhar, Ctrl+clique para somar outro</p></div></div>
      <div class="vend-cards">${(filtrado ? d.vendedores.map((v) => d.resumo_vendedores.find((r) => r.id === v.id) || { ...v, produtos: 0 }) : d.resumo_vendedores)
        .filter((v) => v.produtos !== undefined).map((v) => {
          const ok = v.no_ritmo || 0, at = v.atencao || 0, tot = v.produtos || 0, ru = tot - ok - at;
          return `<div class="vend-card ${estado.vendedores.includes(v.id) ? "selecionada" : ""}" data-vendedor="${v.id}" tabindex="0">
            <div class="n">${esc(v.nome)}</div>
            <div class="p">${v.atingimento != null ? fmt.pct(v.atingimento, 0) : "—"}</div>
            <div class="d">${tot ? `${ok} de ${tot} produtos no ritmo` : "clique para ver"}</div>
            ${tot ? `<div class="segmentos" data-tt="${esc(linhaTT("No ritmo", ok) + linhaTT("Atenção", at) + linhaTT("Abaixo", ru))}">${ok ? `<i class="ok" style="--f:${ok}"></i>` : ""}${at ? `<i class="at" style="--f:${at}"></i>` : ""}${ru ? `<i class="ru" style="--f:${ru}"></i>` : ""}</div>` : ""}
          </div>`;
        }).join("")}</div>
    </section>`;
  }

  h += relatorioProdutos(d, 6);
  if (d.colunas.length === 1) h += renderBullets(d, 7);
  return h;
}

function renderBullets(d, i) {
  const vid = String(d.colunas[0].id);
  const cal = d.calendario;
  const alvo = cal.situacao === "fechado" ? 1 : cal.ritmo;
  const linhas = d.produtos.map((p) => ({ p, c: p.por_vendedor[vid] })).filter((x) => x.c);
  return `<section class="cartao secao entra" style="--i:${i}">
    <div class="cartao-cab"><div><h3>${icone("caixa")}Produtos de ${esc(d.colunas[0].nome)}</h3>
    <p class="sub">Barra = volume vendido líquido · traço = meta do ${variosMeses(d) ? "período" : "mês"} · ritmo esperado ${fmt.pct(alvo)}</p></div></div>
    <div class="bullets">${linhas.map(({ p, c }) => {
      const escala = Math.max(1.15, (c.pct || 0) * 1.05);
      const larg = c.meta ? (Math.min(c.pct || 0, escala) / escala) * 100 : 100;
      const tt = `<div class='tt-t'>${esc(p.nome)}</div>` + linhaTT("Meta", `${fmt.num(c.meta, 1)} ${esc(p.unidade)}`) +
        linhaTT("Vendido", `${fmt.num(c.realizado, 1)} ${esc(p.unidade)}`) + linhaTT("Atingido", fmt.pct(c.pct)) + linhaTT("Esperado hoje", `${fmt.num(c.esperado, 1)} ${esc(p.unidade)}`);
      return `<div class="bullet" data-tt="${esc(tt)}">
        <div class="nome">${esc(p.nome)}<small>${c.meta ? `meta ${fmt.num(c.meta, 0)} ${esc(p.unidade)}` : "sem meta"}</small></div>
        <div class="trilho">
          <span class="enche" style="background:${c.meta ? corStatus(c.status) : "var(--linha-forte)"}" data-largura="${larg}%"></span>
          ${c.meta ? `<span class="alvo" style="left:${(1 / escala) * 100}%"></span><span class="alvo" style="left:${(alvo / escala) * 100}%;opacity:.4"></span>` : ""}
        </div>
        <div class="val">${chipStatus(c.status, c.meta ? fmt.pct(c.pct, 0) : "sem meta")} <span style="color:var(--tinta-3)">${fmt.num(c.realizado, 0)} ${esc(p.unidade)}</span></div>
      </div>`;
    }).join("")}</div>
  </section>`;
}
