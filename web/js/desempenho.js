// Painel de desempenho da equipe (página Gestão, abaixo da Equipe): o destaque do período, o quadro com uma coluna por
// vendedor (nota geral e 9 indicadores) e, ao clicar num vendedor, a ficha dele com os 9 cartões. A conta é toda no
// servidor (bi/desempenho.py); aqui só se desenha. O estado, o carregamento e os cliques ficam em gestao.js.
import { chipStatus, corStatus, esc, fmt, icone } from "./util.js";

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

export function legendaDesempenho() {
  return `<div class="dsp-legenda">
    <span style="--c:var(--ok-forte)"><i></i>Verde: meta batida (100% ou mais)</span>
    <span style="--c:var(--atencao-forte)"><i></i>Amarelo: 90% a 99%</span>
    <span style="--c:var(--ruim-forte)"><i></i>Vermelho: abaixo de 90%</span>
    <span class="fraco">No % de troca, quanto menor melhor: verde até 1,0%, amarelo até 1,5%.</span>
  </div>`;
}
