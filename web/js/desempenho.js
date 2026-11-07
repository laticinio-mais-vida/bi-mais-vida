// Painel de desempenho da equipe (página Gestão, abaixo da Equipe): o destaque do período, o quadro com uma coluna por
// vendedor (nota geral e 9 indicadores) e, ao clicar num vendedor, a ficha dele com os 9 cartões. A conta é toda no
// servidor (bi/desempenho.py); aqui só se desenha. O estado, o carregamento e os cliques ficam em gestao.js.
import { chipStatus, corStatus, esc, fmt, icone, linhaTT } from "./util.js";

const FAIXA = { batida: "Meta batida", atencao: "Atenção", abaixo: "Abaixo da meta", sem_meta: "Sem meta", sem_dados: "Sem dados" };
const ROTULO_TROCA = { batida: "Dentro do limite", atencao: "Perto do teto", abaixo: "Acima do teto" };
const DO_PERIODO = { ultimo_dia: "do dia", semana: "da semana", hoje: "de hoje" };

// O que cada indicador conta (o ⓘ da ficha e a dica do quadro).
const COMO = {
  outras: "Venda de outras linhas no período, menos as devoluções que descontam (a regra da página Metas), pelo vendedor da nota. A meta é a expectativa de cada dia × a parte de outras linhas na meta do mês. No BA, a meta de outras linhas e a de mussarela saem do volume da meta × o preço médio do vendedor no mês anterior, ajustadas para somar a meta de faturamento.",
  mussarela: "Venda de mussarela (todas, inclusive a fatiada) no período, menos as devoluções que descontam, pelo vendedor da nota. A meta é a expectativa de cada dia × a parte da mussarela na meta do mês. No BA, sai do volume da meta × o preço médio do vendedor no mês anterior.",
  faturamento: "Faturamento do período contra a expectativa de venda. O saldo do mês (meta − faturado até a véspera − pedidos em aberto feitos há menos de 8 dias) é distribuído pelo potencial dos clientes programados em cada dia que resta (a média do que cada um comprou nos 2 meses anteriores, dividida pelos dias de atendimento dele). Nunca fica abaixo do potencial normal do dia; com a meta do mês batida, vale o potencial normal.",
  atendimentos: "Clientes com pedido no dia da rota ÷ clientes esperados no dia: o semanal sempre, o quinzenal se não comprou nos 7 dias antes, o mensal se não comprou nos 21 dias antes (os dias de atendimento ficam em Gestão › Configurar). Pela carteira do vendedor.",
  efetividade: "A média da efetividade de cada dia do mês até o fim do período, como nas campanhas: pedidos na rota do dia ÷ visitas esperadas no dia. Meta de 100%.",
  frequencia: "Semanas com compra ÷ clientes que compraram no mês (a semana vai de domingo a sábado), pelo vendedor da nota. A meta é a média das compras esperadas desses clientes no mês inteiro, se atendidos dentro da periodicidade (semanal, quinzenal ou mensal), a partir da última compra antes do mês.",
  positivacao: "Clientes distintos com nota no mês, pelo vendedor que emitiu (como na página Metas), contra a META CLIENTE.",
  troca: "Devoluções e brindes de vencido e danificado ÷ faturamento bruto da carteira no mês, pelo dono do cliente. Verde até 1,0%; amarelo até 1,5%, o teto.",
  ticket: "Venda média do mês, como na página Metas: faturamento ÷ clientes com nota. Meta: meta de faturamento ÷ META CLIENTE.",
};

// As linhas do quadro, na ordem do Painel Comercial (bi/desempenho.py LINHAS): onde, indicador, rótulo, unidade.
const LINHAS = [
  ["mes", "positivacao", "Positivação", "cli"],
  ["dia", "atendimentos", "Atendimentos", "cli"],
  ["dia", "faturamento", "Faturamento", "R$"],
  ["dia", "mussarela", "Mussarela", "R$"],
  ["dia", "outras", "Outras linhas", "R$"],
  ["mes", "ticket", "Ticket médio", "R$"],
  ["mes", "frequencia", "Frequência", "sem."],
  ["mes", "efetividade", "Efetividade", "%"],
  ["mes", "troca", "% Troca", "%"],
];

// Os cartões da ficha, na ordem do Painel Comercial.
const CARTOES = [
  ["dia", "outras", "Faturamento outras linhas"],
  ["dia", "mussarela", "Faturamento mussarela"],
  ["dia", "faturamento", "Meta de venda diária"],
  ["dia", "atendimentos", "Atendimentos"],
  ["mes", "efetividade", "Efetividade acumulada do mês"],
  ["mes", "frequencia", "Frequência de compras no mês"],
  ["mes", "positivacao", "Positivação"],
  ["mes", "troca", "% Troca — vencido + danificado"],
  ["mes", "ticket", "Ticket médio"],
];

const TIPO = { faturamento: "moeda", mussarela: "moeda", outras: "moeda", ticket: "moeda", atendimentos: "inteiro",
  positivacao: "inteiro", frequencia: "decimal", efetividade: "pct", troca: "pct2" };

function valor(k, v, curto = false) {
  if (v == null) return "—";
  const tipo = TIPO[k];
  if (tipo === "moeda") return curto ? fmt.moeda(v) : fmt.moeda2(v);
  if (tipo === "inteiro") return fmt.num(v);
  if (tipo === "decimal") return fmt.num(v, 2);
  if (tipo === "pct2") return fmt.pct(v, 2);
  return fmt.pct(v, 1);
}

// O valor sem a unidade, para o quadro ("R$" fica ao lado, como no Painel Comercial).
function cru(k, v) {
  if (v == null) return "—";
  const tipo = TIPO[k];
  if (tipo === "moeda") return fmt.num(v);
  return valor(k, v);
}

const cor = (b) => corStatus(b.status === "batida" ? "batida" : b.status);
const largura = (b) => (b.pct == null ? 0 : Math.max(0, Math.min(100, b.pct * 100)));
const rotulo = (k, b) => (k === "troca" && ROTULO_TROCA[b.status]) || FAIXA[b.status] || FAIXA.sem_meta;
const iniciaisDe = (nome) => String(nome || "").split(/[\s-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();

export function textoPeriodo(d) {
  const p = d.periodo;
  if (!p) return "";
  if (p.chave === "semana") return `semana de ${fmt.dataCurta(p.inicio)} a ${fmt.dataCurta(p.fim)}`;
  if (p.chave === "hoje") return `hoje, ${fmt.dataCurta(p.fim)}${d.copia ? ` · dados da cópia das ${d.copia.slice(11, 16)}` : ""}`;
  return `${fmt.semana(p.fim)}, ${fmt.dataCurta(p.fim)}`;
}

export function filtroPeriodo(d, atual) {
  return `<div class="seg-mini dsp-periodos" role="group" aria-label="Período">${(d.periodos || []).map((p) =>
    `<button type="button" data-dsp-periodo="${p.chave}" class="${p.chave === atual ? "ativo" : ""}" aria-pressed="${p.chave === atual}">${esc(p.rotulo)}</button>`).join("")}</div>`;
}

export function avisosDesempenho(d) {
  const lista = [d.aviso, ...(d.avisos || [])].filter(Boolean);
  return lista.map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
}

// A: o destaque do período (a equipe toda do quadro).
export function heroDesempenho(d) {
  const t = d.totais, de = DO_PERIODO[d.periodo.chave] || "do período", du = d.dias_uteis || {};
  if (!t) return "";
  const per = t.periodo, mes = t.mes;
  return `<div class="dsp-hero" style="--c:${cor(per)}">
    <div class="dsp-hero-main">
      <small>Faturamento ${de}</small>
      <b>${fmt.moeda2(per.real)}</b>
      <span>${per.meta ? `${fmt.pct(per.pct)} da meta ${de}` : "sem meta para comparar"}</span>
    </div>
    <div class="dsp-hero-itens">
      <div><small>Meta ${de}</small><b>${per.meta ? fmt.moeda2(per.meta) : "—"}</b><span>${d.periodo.chave === "semana" ? "a soma da expectativa de cada dia" : "a expectativa de venda do dia"}</span></div>
      <div><small>Acumulado do mês</small><b>${fmt.moeda2(mes.real)}</b><span>${mes.meta ? `${fmt.pct(mes.pct)} de ${fmt.moeda(mes.meta)}` : "sem meta no mês"}</span></div>
      <div><small>Dias úteis restantes</small><b>${fmt.dias(du.restantes)}</b><span>de ${fmt.dias(du.total)} no mês</span></div>
      <div class="dsp-hero-status">${chipStatus(per.status, FAIXA[per.status])}</div>
    </div>
  </div>`;
}

function linha(v, [onde, k, nome, un]) {
  const b = v[onde][k];
  const pct = b.pct == null ? "—" : fmt.pct(b.pct, 0);
  const meta = b.meta == null ? "sem meta" : cru(k, b.meta);
  return `<div class="dsp-linha" style="--c:${cor(b)}" title="${esc(COMO[k])}">
    <div class="dsp-linha-top"><span>${nome}</span><b>${pct}</b></div>
    <div class="dsp-linha-val"><span>${cru(k, b.real)}</span><i>/</i><span class="dsp-meta">${meta}</span><small>${un}</small></div>
    <div class="dsp-barra"><i style="width:${largura(b)}%"></i></div>
  </div>`;
}

// B: o quadro, uma coluna por vendedor (arrasta para o lado quando não cabe).
export function quadroDesempenho(d) {
  const vend = d.vendedores || [];
  if (!vend.length) return `<p class="ge-vazio">${icone("info")}<span>Nenhum vendedor da região com meta no mês no seu acesso.</span></p>`;
  return `<div class="dsp-quadro${vend.length <= 4 ? " poucos" : ""}">${vend.map((v) => {
    const st = v.nota == null ? "sem_meta" : v.nota >= d.faixas.verde ? "batida" : v.nota >= d.faixas.amarelo ? "atencao" : "abaixo";
    return `<div class="dsp-col">
      <button type="button" class="dsp-col-cab" data-dsp-vendedor="${v.id}" style="--c:${corStatus(st)}" aria-label="${esc(v.nome)}: abrir a ficha">
        <span class="dsp-ini">${esc(iniciaisDe(v.nome))}</span><b title="${esc(v.nome)}">${esc(v.nome)}</b>
        <span class="dsp-nota" title="Nota geral: a média dos atingimentos">${v.nota == null ? "—" : fmt.pct(v.nota, 0)}</span>
      </button>
      <div class="dsp-linhas">${LINHAS.map((l) => linha(v, l)).join("")}</div>
    </div>`;
  }).join("")}</div>`;
}

const MODO = {
  meta_batida: "meta do mês batida: vale o potencial normal do dia",
  potencial: "o saldo pedia menos que o potencial normal do dia, que vale",
  sem_rota: "sem dia de atendimento pela frente: o saldo pelos dias úteis que restam",
  sem_meta: "sem meta no mês",
};

function notaFaturamento(v, d) {
  const exp = v.expectativa || [];
  const abertos = exp.reduce((s, e) => s + (e.abertos || 0), 0);
  if (exp.length !== 1) {
    const dias = exp.filter((e) => e.meta).length;
    return `soma da expectativa de ${dias} ${dias === 1 ? "dia" : "dias"} da semana`;
  }
  const e = exp[0];
  if (e.modo === "sem_meta") return MODO.sem_meta;
  if (!e.meta) return "não atende neste dia: nenhum cliente programado";
  const partes = [e.modo === "saldo" ? `saldo do mês ${fmt.moeda(e.saldo)} pelo potencial dos dias que restam` : MODO[e.modo]];
  partes.push(`potencial do dia ${fmt.moeda(e.potencial)}`);
  if (abertos) partes.push(`pedidos em aberto ${fmt.moeda(abertos)}`);
  return partes.join(" · ");
}

function notaCartao(v, onde, k, d) {
  const b = v[onde][k];
  if (k === "faturamento") return notaFaturamento(v, d);
  if (b.real == null && (k === "frequencia" || k === "ticket")) return "nenhum cliente com nota no mês ainda";
  if (b.real == null && k === "atendimentos") return "sem os pedidos de venda (veja o aviso acima)";
  if (b.real == null && k === "troca") return "sem faturamento da carteira no mês ainda";
  if (k === "mussarela" || k === "outras") {
    return v.regime === "volume" ? "meta do volume × preço médio do mês anterior" : v.regime === "valor" ? "meta da planilha" : "sem meta separada por linha";
  }
  if (k === "atendimentos") return b.meta == null && b.real != null ? "nenhum cliente esperado no dia" : `${fmt.num(b.real)} de ${fmt.num(b.meta)} clientes esperados`;
  if (k === "efetividade") return b.real == null ? "sem visita esperada no mês" : `${fmt.num(b.pedidos)} pedidos em ${fmt.num(b.visitas)} visitas esperadas · média de ${fmt.num(b.dias)} dias`;
  if (k === "frequencia") return `${fmt.num(b.semanas)} semanas com compra de ${fmt.num(b.clientes)} clientes · ${fmt.num(b.esperadas)} compras esperadas de ${fmt.num(b.clientes_meta)}`;
  if (k === "positivacao") return b.meta ? `${fmt.num(b.real)} de ${fmt.num(b.meta)} clientes${b.real < b.meta ? ` · faltam ${fmt.num(b.meta - b.real)}` : ""}` : `${fmt.num(b.real)} clientes`;
  if (k === "troca") return `${fmt.moeda2(b.valor)} sobre ${fmt.moeda(b.base)} de faturamento bruto`;
  if (k === "ticket") return `${fmt.moeda(v.mes.faturamento.real)} ÷ ${fmt.num(v.mes.positivacao.real)} clientes`;
  return "";
}

// C: a ficha do vendedor, com os 9 cartões (o ⓘ abre a explicação de cada um).
export function fichaDesempenho(d, v, abertos) {
  const st = v.nota == null ? "sem_meta" : v.nota >= d.faixas.verde ? "batida" : v.nota >= d.faixas.amarelo ? "atencao" : "abaixo";
  const cartoes = CARTOES.map(([onde, k, titulo]) => {
    const b = v[onde][k], chave = `${onde}-${k}`, aberto = abertos.has(chave);
    const metaTexto = b.meta == null ? "sem meta para comparar"
      : k === "troca" ? `teto ${valor(k, b.meta)} · usou ${fmt.pct(b.pct, 0)}` : `meta ${valor(k, b.meta)} · <b>${fmt.pct(b.pct, 1)}</b>`;
    return `<div class="dsp-cartao" style="--c:${cor(b)}">
      <div class="dsp-cartao-top"><span>${titulo}</span>
        <button type="button" class="btn icone dsp-info" data-dsp-info="${chave}" aria-expanded="${aberto}" title="Como é calculado" aria-label="Como é calculado: ${esc(titulo)}">${icone("info")}</button></div>
      <b class="dsp-cartao-val">${valor(k, b.real)}</b>
      <span class="dsp-cartao-meta">${metaTexto}</span>
      <div class="dsp-barra"><i style="width:${largura(b)}%"></i></div>
      <div class="dsp-cartao-pe">${chipStatus(b.status, rotulo(k, b))}</div>
      <small class="dsp-cartao-nota">${esc(notaCartao(v, onde, k, d))}</small>
      <p class="dsp-como"${aberto ? "" : " hidden"}>${esc(COMO[k])}</p>
    </div>`;
  }).join("");
  const sem = v.programacao?.sem_programacao;
  return `<div class="dsp-ficha">
    <div class="dsp-ficha-cab">
      <button class="btn" type="button" data-dsp-voltar>${icone("voltar")}Voltar ao quadro</button>
      <span class="dsp-ini grande" style="--c:${corStatus(st)}">${esc(iniciaisDe(v.nome))}</span>
      <div><b>${esc(v.nome)}</b><small>nota geral ${v.nota == null ? "—" : fmt.pct(v.nota, 0)} · ${fmt.num(v.programacao?.clientes)} clientes com dia de atendimento${sem ? ` · ${fmt.num(sem)} sem dia (Gestão › Configurar)` : ""}</small></div>
    </div>
    <div class="dsp-cartoes">${cartoes}</div>
  </div>`;
}

// A dica da meta do período (passar o mouse): de onde ela veio (o saldo, o potencial do dia, os pedidos em aberto).
function dicaMeta(v, de) {
  const b = v.dia.faturamento, exp = v.expectativa || [];
  const linhas = [linhaTT(`Venda ${de}`, fmt.moeda2(b.real)), linhaTT(`Meta ${de}`, b.meta == null ? "sem meta" : fmt.moeda2(b.meta))];
  if (b.pct != null) linhas.push(linhaTT("Atingido", fmt.pct(b.pct, 1)));
  if (exp.length === 1) {
    const e = exp[0];
    if (e.saldo != null) linhas.push(linhaTT("Saldo do mês", fmt.moeda2(e.saldo)));
    linhas.push(linhaTT("Potencial do dia", fmt.moeda2(e.potencial)));
    if (e.abertos) linhas.push(linhaTT("Pedidos em aberto", fmt.moeda2(e.abertos)));
    linhas.push(`<div class="tt-l"><span>${esc(e.modo === "saldo" && !e.meta ? "não atende neste dia" : (MODO[e.modo] || "a parte do dia no saldo do mês"))}</span></div>`);
  } else if (exp.length) {
    const dias = exp.filter((e) => e.meta).length, abertos = exp.reduce((s, e) => s + (e.abertos || 0), 0);
    linhas.push(linhaTT("Dias com meta", fmt.num(dias)));
    if (abertos) linhas.push(linhaTT("Pedidos em aberto (soma dos dias)", fmt.moeda2(abertos)));
  }
  return `<div class="tt-t">${esc(v.nome)}</div>${linhas.join("")}`;
}

const ponto = (st) => `<span class="dsp-ponto" style="--c:${corStatus(st)}"></span>`;

// E: a meta de venda diária por vendedor, em barras (0 a 150%, o traço é a meta) ou em tabela.
export function metaDiariaDesempenho(d, tabela) {
  const vend = d.vendedores || [];
  if (!vend.length) return "";
  const de = DO_PERIODO[d.periodo.chave] || "do período";
  const ESCALA = 1.5;
  const corpo = tabela ? `<div class="tabela-rolagem"><table class="dados dsp-tabela">
      <thead><tr><th>Vendedor</th><th>Venda ${de}</th><th>Meta ${de}</th><th>Atingido</th><th>Atend. / Clientes</th>
        <th>Ticket médio</th><th>% Troca</th><th>Situação</th></tr></thead>
      <tbody>${vend.map((v) => {
        const b = v.dia.faturamento, a = v.dia.atendimentos, t = v.dia.ticket, tr = v.mes.troca;
        return `<tr>
          <td>${esc(v.nome)}</td><td>${fmt.moeda2(b.real)}</td>
          <td><span class="dsp-dica" tabindex="0" data-tt="${esc(dicaMeta(v, de))}">${b.meta == null ? "sem meta" : fmt.moeda2(b.meta)}</span></td>
          <td>${b.pct == null ? "—" : fmt.pct(b.pct, 1)}</td>
          <td>${a.real == null ? "—" : `${fmt.num(a.real)} / ${a.meta == null ? 0 : fmt.num(a.meta)}`}</td>
          <td title="${t.meta ? `meta ${fmt.moeda2(t.meta)}: a meta ${de} ÷ ${fmt.num(t.esperados)} clientes esperados` : "sem meta"}">${t.real == null ? "—" : `${ponto(t.status)}${fmt.moeda2(t.real)}${t.pct != null ? ` <small>${fmt.pct(t.pct, 0)}</small>` : ""}`}</td>
          <td>${tr.real == null ? "—" : `${ponto(tr.status)}${fmt.pct(tr.real, 2)}`}</td>
          <td class="esq">${ponto(b.status)}${esc(FAIXA[b.status] || FAIXA.sem_meta)}</td>
        </tr>`;
      }).join("")}</tbody></table></div>`
    : `<div class="dsp-barras">${vend.map((v) => {
        const b = v.dia.faturamento, larg = b.pct == null ? 0 : Math.min(100, (b.pct / ESCALA) * 100);
        return `<div class="dsp-barra-linha" style="--c:${cor(b)}" tabindex="0" data-tt="${esc(dicaMeta(v, de))}">
          <span class="dsp-barra-nome">${esc(v.nome)}</span>
          <span class="dsp-barra-trilho"><i style="width:${larg}%"></i><b style="left:${100 / ESCALA}%" aria-hidden="true"></b></span>
          <span class="dsp-barra-pct">${b.pct == null ? "sem meta" : fmt.pct(b.pct, 0)}</span>
        </div>`;
      }).join("")}
      <div class="dsp-barra-linha dsp-escala" aria-hidden="true"><span></span><span class="dsp-barras-escala"><span style="left:0%">0%</span><span style="left:33.333%">50%</span><span style="left:66.667%">100%, a meta</span><span style="left:100%">150%</span></span><span></span></div></div>`;
  return `<div class="dsp-meta-dia">
    <div class="dsp-meta-dia-cab">
      <div><h4>Meta de venda diária por vendedor</h4>
        <p>A meta de cada dia é a expectativa: o saldo do mês (meta − faturado − pedidos em aberto) distribuído pelo potencial dos clientes programados nos dias que restam, nunca abaixo do potencial normal do dia. Passe o mouse para ver de onde ela veio.</p></div>
      <button class="btn" type="button" data-dsp-tabela aria-pressed="${tabela}">${icone(tabela ? "grafico" : "quadro")}${tabela ? "Ver gráfico" : "Ver tabela"}</button>
    </div>
    ${corpo}
  </div>`;
}

// ---------- a evolução mensal (bi/desempenho.py Painel.evolucao) ----------
export function abasDesempenho(vista) {
  const abas = [["dia", "Painel do dia"], ["mes", "Evolução mensal"]];
  return `<div class="seg-mini dsp-vistas" role="group" aria-label="Vista">${abas.map(([k, r]) =>
    `<button type="button" data-dsp-vista="${k}" class="${k === vista ? "ativo" : ""}" aria-pressed="${k === vista}">${r}</button>`).join("")}</div>`;
}

export function filtroVendedor(evo, selecionado) {
  const lista = evo?.vendedores || [];
  return `<label class="dsp-vendedor"><span>Vendedor</span>
    <select data-dsp-evo-vendedor aria-label="Vendedor da evolução mensal">
      <option value="">Equipe ${esc(evo?.regiao || "")}</option>
      ${lista.map((v) => `<option value="${v.id}" ${v.id === selecionado ? "selected" : ""}>${esc(v.nome)}</option>`).join("")}
    </select></label>`;
}

const SEG = {
  FOOD: { nome: "FOOD", cor: "var(--seg-food)" }, PADARIAS: { nome: "PADARIAS", cor: "var(--seg-padarias)" },
  REDES: { nome: "REDES", cor: "var(--seg-redes)" }, MERCADO: { nome: "MERCADO", cor: "var(--seg-mercado)" },
  OUTROS: { nome: "OUTROS", cor: "var(--seg-outros)" },
};
const MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const nomeMes = (iso) => `${MESES_LONGOS[Number(iso.slice(5, 7)) - 1]} de ${iso.slice(0, 4)}`;

function fatia(cx, cy, r, a0, a1) {
  const p = (a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const [x0, y0] = p(a0), [x1, y1] = p(a1);
  return `M${cx},${cy} L${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z`;
}

// G: a pizza do faturamento por segmento num mês, com a lista (nome, valor e %) ao lado.
function pizza(evo, mesSel) {
  const meses = (evo.meses || []).filter((m) => !m.futuro);
  if (!meses.length) return "";
  const m = meses.find((x) => x.mes === mesSel) || meses[meses.length - 1];
  const segs = (evo.segmentos || Object.keys(SEG)).map((k) => ({ k, v: Math.max(0, m.segmentos?.[k] || 0) }));
  const total = segs.reduce((s, x) => s + x.v, 0);
  let a = 0;
  const fatias = total > 0 ? segs.filter((x) => x.v > 0).map((x) => {
    const parte = x.v / total, a0 = a, a1 = a + parte * 2 * Math.PI;
    a = a1;
    const dica = `<div class="tt-t">${esc(SEG[x.k].nome)}</div>${linhaTT("Faturamento", fmt.moeda2(x.v), SEG[x.k].cor)}${linhaTT("Parte do mês", fmt.pct(parte, 1))}`;
    return parte >= 0.9999 ? `<circle cx="110" cy="110" r="100" fill="${SEG[x.k].cor}" stroke="var(--surface)" stroke-width="2" data-tt="${esc(dica)}"/>`
      : `<path d="${fatia(110, 110, 100, a0, a1)}" fill="${SEG[x.k].cor}" stroke="var(--surface)" stroke-width="2" stroke-linejoin="round" data-tt="${esc(dica)}"/>`;
  }).join("") : `<circle cx="110" cy="110" r="100" fill="var(--surface-3)"/>`;
  const opcoes = meses.slice().reverse().map((x) => `<option value="${x.mes}" ${x.mes === m.mes ? "selected" : ""}>${nomeMes(x.mes)}${x.parcial ? " (em andamento)" : ""}</option>`).join("");
  return `<div class="dsp-evo-cartao dsp-pizza">
    <div class="dsp-evo-cab"><div><h4>Faturamento por segmento</h4><p>O faturamento da página Metas, pelo segmento do cliente no cadastro.</p></div>
      <label class="dsp-mes"><span>Mês</span><select data-dsp-evo-mes aria-label="Mês da pizza de segmentos">${opcoes}</select></label></div>
    <div class="dsp-pizza-corpo">
      <svg viewBox="0 0 220 220" role="img" aria-label="Faturamento por segmento em ${esc(nomeMes(m.mes))}">${fatias}</svg>
      <table class="dsp-seg-lista"><tbody>${segs.map((x) => `<tr>
        <td><span class="dsp-seg-cor" style="--c:${SEG[x.k].cor}"></span>${SEG[x.k].nome}</td>
        <td>${fmt.moeda2(x.v)}</td><td>${total ? fmt.pct(x.v / total, 1) : "—"}</td></tr>`).join("")}
        <tr class="total"><td>Total</td><td>${fmt.moeda2(total)}</td><td>${total ? "100%" : "—"}</td></tr></tbody></table>
    </div>
    <details class="dsp-como-seg"><summary>Como cada cliente é classificado</summary>
      <p><b>REDES</b>: o segmento supermercado (por enquanto; um segmento "redes" no cadastro entra no lugar dele).
      <b>MERCADO</b>: mercearia, mercado, atacado e açougue. <b>PADARIAS</b>: padaria. <b>FOOD</b>: restaurante,
      lanchonete e cafeteria, pizzaria, pastelaria, hamburgueria, churrascaria, hotel e pousada, buffet, fábricas de doce
      e de salgado, hospitais e prefeituras. <b>OUTROS</b>: o segmento "outros", o cliente sem segmento e a venda a
      funcionário, produtor ou fornecedor. Vale o segmento de hoje no cadastro.</p>
    </details>
  </div>`;
}

// Uma linha de 12 meses (os vazios quebram a linha), com a linha da meta e a dica de cada mês.
function linhaMeses(meses, valor, { meta = null, rotuloMeta = "", formato, titulo }) {
  const W = 300, H = 128, PL = 44, PR = 10, PT = 12, PB = 22, iw = W - PL - PR, ih = H - PT - PB;
  const vals = meses.map(valor);
  const existentes = vals.filter((v) => v != null);
  if (!existentes.length) return `<p class="dsp-evo-vazio">Sem dados nos últimos meses.</p>`;
  let vMin = Math.min(...existentes, ...(meta != null ? [meta] : [])), vMax = Math.max(...existentes, ...(meta != null ? [meta] : []));
  const folga = (vMax - vMin) * 0.2 || Math.abs(vMax) * 0.1 || 1;
  vMin = Math.max(0, vMin - folga);
  vMax += folga;
  const x = (i) => PL + (meses.length < 2 ? iw / 2 : (i / (meses.length - 1)) * iw);
  const y = (v) => PT + ih - ((v - vMin) / (vMax - vMin)) * ih;
  let d = "", aberto = false;
  vals.forEach((v, i) => {
    if (v == null) { aberto = false; return; }
    d += `${aberto ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
    aberto = true;
  });
  const grade = [vMin, (vMin + vMax) / 2, vMax].map((v) => `<line x1="${PL}" y1="${y(v).toFixed(1)}" x2="${W - PR}" y2="${y(v).toFixed(1)}" class="dsp-grade"/>
    <text x="${PL - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" class="dsp-eixo">${esc(formato(v, true))}</text>`).join("");
  const linhaMeta = meta == null ? "" : `<line x1="${PL}" y1="${y(meta).toFixed(1)}" x2="${W - PR}" y2="${y(meta).toFixed(1)}" class="dsp-meta-linha"/>
    <text x="${W - PR}" y="${(y(meta) - 5).toFixed(1)}" text-anchor="end" class="dsp-eixo dsp-meta-rotulo">${esc(rotuloMeta)}</text>`;
  const ultimo = vals.length - 1 - [...vals].reverse().findIndex((v) => v != null);
  const parcial = meses[ultimo]?.parcial;
  const passo = meses.length < 2 ? iw : iw / (meses.length - 1);
  const alvos = meses.map((m, i) => {
    const dica = `<div class="tt-t">${esc(nomeMes(m.mes))}${m.parcial ? " (em andamento)" : ""}</div>${linhaTT(titulo, vals[i] == null ? "—" : esc(formato(vals[i])))}${meta != null ? linhaTT("Meta", esc(rotuloMeta)) : ""}`;
    return `<rect x="${(x(i) - passo / 2).toFixed(1)}" y="${PT}" width="${passo.toFixed(1)}" height="${ih}" fill="transparent" data-tt="${esc(dica)}"/>`;
  }).join("");
  return `<svg class="dsp-linha-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(titulo)} mês a mês">
    ${grade}${linhaMeta}
    <path d="${d.trim()}" fill="none" stroke="var(--s-fat)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(ultimo).toFixed(1)}" cy="${y(vals[ultimo]).toFixed(1)}" r="4.5" fill="${parcial ? "var(--surface)" : "var(--s-fat)"}" stroke="${parcial ? "var(--s-fat)" : "var(--surface)"}" stroke-width="2"/>
    <text x="${PL}" y="${H - 6}" class="dsp-eixo">${esc(meses[0].rotulo)}</text>
    <text x="${W - PR}" y="${H - 6}" text-anchor="end" class="dsp-eixo">${esc(meses[meses.length - 1].rotulo)}</text>
    ${alvos}</svg>`;
}

const pctEixo = (v, eixo) => fmt.pct(v, eixo ? 0 : 1);

// H: os cinco mini gráficos (atingimento, positivação, frequência, % de troca e ticket médio).
function minis(evo) {
  const meses = (evo.meses || []).filter((m) => !m.futuro);
  if (!meses.length) return "";
  const atual = meses[meses.length - 1], faixas = evo.faixas || { verde: 1, amarelo: 0.9 }, teto = evo.troca?.teto ?? 0.015;
  const st = (v, meta) => (v == null || !meta ? "sem_meta" : v / meta >= faixas.verde ? "batida" : v / meta >= faixas.amarelo ? "atencao" : "abaixo");
  const stTroca = (v) => (v == null ? "sem_dados" : v <= (evo.troca?.atencao ?? 0.01) ? "batida" : v <= teto ? "atencao" : "abaixo");
  const ating = (m) => (m.parcial ? m.atingimento_projetado : m.atingimento);
  const cartoes = [
    { titulo: "Atingimento da meta", sub: "Faturamento ÷ meta. O mês em andamento entra projetado pelo ritmo dos dias úteis.",
      valor: ating, formato: pctEixo, meta: 1, rotuloMeta: "meta 100%", status: (v) => st(v, 1) },
    { titulo: "Positivação", sub: "Clientes com nota ÷ META CLIENTE.", valor: (m) => m.positivacao, formato: pctEixo, meta: 1,
      rotuloMeta: "meta 100%", status: (v) => st(v, 1) },
    { titulo: "Frequência", sub: "Semanas com compra por cliente que comprou.", valor: (m) => m.frequencia,
      formato: (v) => fmt.num(v, 2), status: () => null },
    { titulo: "% de troca", sub: "Vencido + danificado ÷ bruto da carteira. Quanto menor, melhor.", valor: (m) => m.troca,
      formato: (v, eixo) => fmt.pct(v, eixo ? 1 : 2), meta: teto, rotuloMeta: `teto ${fmt.pct(teto, 1)}`, status: stTroca },
    { titulo: "Ticket médio", sub: "Faturamento ÷ clientes com nota.", valor: (m) => m.ticket,
      formato: (v, eixo) => (eixo ? fmt.moedaC(v) : fmt.moeda2(v)), status: () => null },
  ];
  return `<div class="dsp-minis">${cartoes.map((c) => {
    const v = c.valor(atual), s = c.status(v);
    return `<div class="dsp-evo-cartao dsp-mini">
      <div class="dsp-mini-cab"><span>${esc(c.titulo)}</span>
        ${s ? chipStatus(s, c.titulo === "% de troca" ? ROTULO_TROCA[s] || FAIXA[s] : FAIXA[s]) : ""}</div>
      <b class="dsp-mini-val">${v == null ? "—" : esc(c.formato(v))}</b>
      <small class="dsp-mini-data">${esc(nomeMes(atual.mes))}${atual.parcial ? (c.titulo === "Atingimento da meta" ? " (projeção)" : " (em andamento)") : ""}</small>
      ${linhaMeses(meses, c.valor, { meta: c.meta ?? null, rotuloMeta: c.rotuloMeta, formato: c.formato, titulo: c.titulo })}
      <p class="dsp-mini-sub">${esc(c.sub)}</p>
    </div>`;
  }).join("")}</div>`;
}

export function evolucaoDesempenho(evo, mesSel) {
  if (!evo) return `<div class="esqueleto" style="height:420px"></div>`;
  const alvo = evo.vendedor ? `de ${esc(evo.vendedor.nome)}` : `da equipe ${esc(evo.regiao || "")}`;
  return `<p class="dsp-evo-nota">Os últimos 12 meses ${alvo}${evo.vendedor ? "" : " (em cada mês, os vendedores com meta naquele mês)"}.</p>
    ${pizza(evo, mesSel)}${minis(evo)}`;
}

export function legendaDesempenho() {
  return `<div class="dsp-legenda">
    <span style="--c:var(--ok-forte)"><i></i>Verde: meta batida (100% ou mais)</span>
    <span style="--c:var(--atencao-forte)"><i></i>Amarelo: 90% a 99%</span>
    <span style="--c:var(--ruim-forte)"><i></i>Vermelho: abaixo de 90%</span>
    <span class="fraco">No % de troca, quanto menor melhor: verde até 1,0%, amarelo até 1,5%.</span>
  </div>`;
}
