// Página CRM: a nota de 0 a 100 de cada cliente, a soma de quatro indicadores (aderência à frequência, pontualidade de
// pagamento, mix ideal do segmento e rentabilidade). As contas, as regras e quem vê o quê ficam no servidor
// (bi/crm.py): aqui é a apresentação, com os filtros, os cartões, a tabela ordenável e, ao clicar num cliente, o porquê
// de cada nota (as compras do semestre, os itens do mix que faltam e o lucro bruto mês a mês e por produto).
import { api, esc, fmt, icone, toast, guardar, ler, clicarOrdem, lerNiveis, ordenarPorNiveis, marcaOrdem, linhaOrdem } from "./util.js";
import { multiSelecao } from "./multiselecao.js";
import { ligarTelaCheia, sairTelaCheia, reajustarTelaCheia } from "./telacheia.js";

const INDICADORES = [
  { id: "aderencia", rotulo: "Aderência", dica: "Aderência à frequência do cadastro (semanal, quinzenal ou mensal)" },
  { id: "pontualidade", rotulo: "Pontualidade", dica: "Títulos pagos em dia, com desconto pelo atraso médio" },
  { id: "mix", rotulo: "Mix", dica: "Itens do mix ideal do segmento que o cliente comprou no semestre" },
  { id: "rentabilidade", rotulo: "Rentabilidade", dica: "Lucro bruto do período, pelos quintis dos clientes do CRM" },
];
// Só para ler a distribuição na tela (a nota em si é a soma exata dos quatro indicadores).
const FAIXAS = [
  { id: "a", rotulo: "80 a 100", de: 80, cor: "var(--ok-forte)" },
  { id: "b", rotulo: "60 a 79", de: 60, cor: "color-mix(in srgb, var(--ok-forte) 55%, var(--atencao-forte))" },
  { id: "c", rotulo: "40 a 59", de: 40, cor: "var(--atencao-forte)" },
  { id: "d", rotulo: "20 a 39", de: 20, cor: "color-mix(in srgb, var(--atencao-forte) 45%, var(--ruim-forte))" },
  { id: "e", rotulo: "0 a 19", de: 0, cor: "var(--ruim-forte)" },
];
const FREQ = { semanal: "Semanal", quinzenal: "Quinzenal", mensal: "Mensal", "outra rede": "Outra rede (semanal)", "sem rede": "Sem rede (semanal)" };
const COLUNAS = [
  { id: "nome", rotulo: "Cliente", esq: true, valor: (c) => c.nome },
  { id: "vendedor", rotulo: "Vendedor", esq: true, valor: (c) => c.vendedor.nome },
  { id: "segmento", rotulo: "Segmento", esq: true, valor: (c) => c.segmento || "" },
  { id: "frequencia", rotulo: "Frequência", esq: true, valor: (c) => FREQ[c.frequencia] || c.frequencia },
  { id: "nota", rotulo: "Nota", valor: (c) => c.nota_exata },
  ...INDICADORES.map((i) => ({ id: i.id, rotulo: i.rotulo, valor: (c) => c[i.id]?.pontos ?? -1, dica: i.dica })),
  { id: "lucro", rotulo: "Lucro bruto", valor: (c) => c.rentabilidade?.lucro ?? -Infinity, dica: "Faturamento menos o custo industrial × volume, no período da rentabilidade" },
];
const TEXTO = ["nome", "vendedor", "segmento", "frequencia"];
const ORDEM_PADRAO = [{ campo: "nota", desc: true }];
const coluna = (id) => COLUNAS.find((c) => c.id === id);

const faixaDe = (nota) => FAIXAS.find((f) => nota >= f.de) || FAIXAS[FAIXAS.length - 1];
const semAcento = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const maiuscula = (t) => (t ? String(t)[0].toUpperCase() + String(t).slice(1) : "");
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;
const pts = (v) => (v == null ? "—" : fmt.num(v, 1));
const DIA = /^\d{4}-\d{2}-\d{2}/;
const data = (iso) => (DIA.test(String(iso ?? "")) ? fmt.data(String(iso).slice(0, 10)) : "—");
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const mesRotulo = (m) => (/^\d{4}-\d{2}$/.test(String(m ?? "")) ? `${MESES[Number(m.slice(5)) - 1]}/${m.slice(2, 4)}` : "—");
// A média só de quem tem o indicador (sem os títulos ou os pedidos no servidor, ele vem vazio).
const media = (lista, f) => { const vs = lista.map(f).filter((v) => v != null); return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null; };

let ctx = null;
let filtroV = null;
let observador = null;   // acompanha a largura da tabela, para o detalhe do cliente caber na parte visível
let esperaBusca = 0;
// A tabela desenha só o começo da lista, e as próximas linhas entram quando a pessoa rola até perto do fim. Com 1.900
// clientes, refazer todas as linhas a cada filtro, ordem, busca ou clique num cliente travava a tela por segundos.
const LOTE = 100;       // quantas linhas entram por vez
const FOLGA = 25;       // quando uma das últimas FOLGA linhas desenhadas aparece na tela, entram as próximas
let listaAtual = [];    // os clientes da tabela (com os filtros, a busca e a ordem), desenhados até `desenhadas`
let desenhadas = 0;
let vigia = null;       // IntersectionObserver nas últimas FOLGA linhas (vigiar)
const estado = {
  dados: null, pedido: 0, vendedores: [], segmento: "", frequencia: "", faixa: "", sinalizados: false, busca: "",
  ordens: ORDEM_PADRAO, aberto: null, detalhes: {}, animar: true,  // ordens: os níveis da ordem da tabela (util.js)
};

export function montarCrm(container, contexto) {
  ctx = contexto;
  const salvo = ler("mv-crm", {}) || {};
  Object.assign(estado, {
    dados: null, aberto: null, detalhes: {}, busca: "", vendedores: [], segmento: "", frequencia: "", faixa: "", sinalizados: false,
    ordens: lerNiveis(salvo.ordem, coluna, ORDEM_PADRAO),
  });
  vigia?.disconnect();
  vigia = null;
  listaAtual = [];
  desenhadas = 0;
  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="filtros crm-filtros">
        <div id="crm-vendedores" hidden></div>
        <label class="campo" title="Segmento do cadastro"><span class="ic-campo">${icone("loja")}</span><select id="crm-segmento" aria-label="Segmento"><option value="">Todos os segmentos</option></select></label>
        <label class="campo" title="Frequência do cadastro (a rede)"><span class="ic-campo">${icone("calendario")}</span><select id="crm-frequencia" aria-label="Frequência">
          <option value="">Todas as frequências</option>${Object.entries(FREQ).map(([id, n]) => `<option value="${esc(id)}">${esc(n)}</option>`).join("")}</select></label>
        <label class="campo" title="Faixa da nota"><span class="ic-campo">${icone("estrela")}</span><select id="crm-faixa" aria-label="Faixa da nota">
          <option value="">Todas as notas</option>${FAIXAS.map((f) => `<option value="${f.id}">Nota de ${esc(f.rotulo)}</option>`).join("")}</select></label>
        <label class="crm-marca" title="Só os clientes com alguma sinalização: sem segmento, segmento sem mix ideal ou sem título a receber"><input type="checkbox" id="crm-sinalizados"><span>Só sinalizados</span></label>
        <label class="campo sem-seta crm-busca"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="crm-busca" placeholder="Buscar cliente" autocomplete="off" spellcheck="false" aria-label="Buscar cliente pelo nome, pela cidade ou pelo código"></label>
        <a class="btn" id="crm-excel" href="/api/crm/excel" title="Todos os clientes do CRM do seu acesso, em Excel">${icone("arquivo")}<span>Excel</span></a>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-crm" title="Os números de cada indicador, o mix ideal e os custos industriais">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="crm-avisos"></div>
    <div id="crm-conteudo"><div class="grade secao">
      <div class="kpis n4">${'<div class="esqueleto" style="height:150px"></div>'.repeat(4)}</div>
      <div class="esqueleto" style="height:420px"></div></div>
    </div>`;
  filtroV = multiSelecao(container.querySelector("#crm-vendedores"), {
    rotulo: "Vendedores", icone: "usuario", todos: "Todos os vendedores", plural: "vendedores", busca: "Buscar vendedor",
    itens: [], selecionados: [], nomesAte: 2,
    aoAplicar: (lista) => { estado.vendedores = lista; desenharDados(); },
  });
  const mudar = (id, campo, valor = (e) => e.target.value) => container.querySelector(id).addEventListener("change", (e) => {
    estado[campo] = valor(e);
    desenharDados();
  });
  mudar("#crm-segmento", "segmento");
  mudar("#crm-frequencia", "frequencia");
  mudar("#crm-faixa", "faixa");
  mudar("#crm-sinalizados", "sinalizados", (e) => e.target.checked);
  container.querySelector("#crm-busca").addEventListener("input", (e) => {
    estado.busca = e.target.value;
    clearTimeout(esperaBusca);
    esperaBusca = setTimeout(desenharTabela, 150);
  });
  carregar();
}

// Chegou uma cópia nova do banco: lê de novo sem perder os filtros nem o cliente aberto.
export function recarregarCrm() { if (ctx) carregar(true); }

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("crm-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  if (!silencioso) {
    if (estado.dados) conteudo.classList.add("recarregando");
    sairTelaCheia();
  }
  try {
    const d = await api("/api/crm");
    if (pedido !== estado.pedido) return;
    d.itens.forEach((c) => { c.id = Number(c.id); c.vendedor.id = Number(c.vendedor.id); });
    estado.dados = d;
    estado.detalhes = {};
    estado.animar = !silencioso;
    ctx.subtitulo(d);
    desenhar();
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (silencioso && estado.dados) return; // fica com o que estava na tela; a próxima leitura tenta de novo
    estado.dados = null;
    const espera = e.status === 503; // os dados ainda não chegaram do computador da empresa (não é erro)
    document.getElementById("crm-avisos").innerHTML = "";
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone(e.status === 403 ? "cadeado" : espera ? "relogio" : "alerta")}<p>${e.status === 403 || espera ? "" : "Não foi possível carregar: "}${esc(espera ? maiuscula(e.message) : e.message)}</p></div>`;
    if (!silencioso && e.status !== 403 && !espera) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
  }
}

function desenhar() {
  const d = estado.dados, conteudo = document.getElementById("crm-conteudo");
  if (!d || !conteudo) return;
  document.getElementById("crm-avisos").innerHTML = (d.avisos || [])
    .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
  preencherFiltros(d);
  if (!document.getElementById("crm-lista")) {
    conteudo.innerHTML = `<div id="crm-topo"></div>
      <section class="cartao secao crm-lista" id="crm-lista"><div id="crm-lista-corpo"></div></section>
      <div id="crm-metodo"></div>`;
    const lista = conteudo.querySelector("#crm-lista");
    lista.addEventListener("click", aoClicarLista);
    lista.addEventListener("keydown", (e) => {
      const tr = e.target.closest("tr[data-cliente]");
      if (tr && e.target === tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); alternar(Number(tr.dataset.cliente)); }
    });
  }
  const metodoAberto = !!document.querySelector("#crm-metodo details")?.open;
  document.getElementById("crm-metodo").innerHTML = metodo(d);
  if (metodoAberto) document.querySelector("#crm-metodo details").open = true;
  desenharDados(true);  // na releitura dos dados, a tabela fica onde estava
  estado.animar = false;
}

function preencherFiltros(d) {
  const nomes = new Map(d.itens.map((c) => [c.vendedor.id, c.vendedor.nome]));
  const itens = [...nomes].map(([id, nome]) => ({ id, nome })).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  filtroV.definir(itens);
  estado.vendedores = filtroV.valor();
  document.getElementById("crm-vendedores").hidden = itens.length < 2;
  const seg = document.getElementById("crm-segmento");
  const segmentos = [...new Set(d.itens.map((c) => c.segmento || "(sem segmento)"))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  seg.innerHTML = `<option value="">Todos os segmentos</option>${segmentos.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("")}`;
  if (!segmentos.includes(estado.segmento)) estado.segmento = "";
  seg.value = estado.segmento;
}

function filtrados(d, comBusca = true) {
  const vend = estado.vendedores.length ? new Set(estado.vendedores) : null;
  const termo = comBusca ? semAcento(estado.busca.trim()) : "";
  return d.itens.filter((c) => (!vend || vend.has(c.vendedor.id))
    && (!estado.segmento || (c.segmento || "(sem segmento)") === estado.segmento)
    && (!estado.frequencia || c.frequencia === estado.frequencia)
    && (!estado.faixa || faixaDe(c.nota).id === estado.faixa)
    && (!estado.sinalizados || c.sinais.length)
    && (!termo || semAcento(`${c.nome} ${c.cidade || ""} ${c.id} ${c.vendedor.nome}`).includes(termo)));
}

function desenharDados(manter = false) {
  const d = estado.dados, topo = document.getElementById("crm-topo");
  if (!d || !topo) return;
  topo.innerHTML = cartoes(d, filtrados(d, false));
  desenharTabela(manter);
  ligarTelaCheia(document.getElementById("crm-conteudo"));
}

function kpi({ i, cor, ic, rotulo, valor, meta, rodape = [], dica = "" }) {
  return `
  <article class="cartao kpi kpi-simples${estado.animar ? " entra" : ""}" style="--i:${i};--cor:${cor}"${dica ? ` title="${esc(dica)}"` : ""}>
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${rotulo}</span></div>
    <div class="kpi-corpo"><div><div class="kpi-valor">${valor}</div><div class="kpi-meta">${meta}</div></div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function cartoes(d, lista) {
  const n = lista.length;
  // Quem ficou fora do CRM não tem segmento nem frequência na lista: aqui só o filtro de vendedores vale.
  const vend = estado.vendedores.length ? estado.vendedores.map(String) : null;
  const fora = { sem_compra: 0, recente: 0 };
  for (const [v, x] of Object.entries(d.fora_vendedores || {})) {
    if (vend && !vend.includes(v)) continue;
    fora.sem_compra += x.sem_compra;
    fora.recente += x.recente;
  }
  const porFaixa = FAIXAS.map((f) => [f, lista.filter((c) => faixaDe(c.nota).id === f.id).length]);
  const semMix = lista.filter((c) => c.mix?.sinal).length, semTitulo = lista.filter((c) => c.pontualidade?.sinal).length;
  const r = d.regras;
  const max = { aderencia: r.aderencia.faixas[0]?.pontos, pontualidade: r.pontualidade.faixas[0]?.pontos, mix: r.mix.pontos, rentabilidade: r.rentabilidade.pontos[0] };
  const notaMedia = media(lista, (c) => c.nota_exata);
  return `<div class="kpis n4">
    ${kpi({ i: 1, cor: "var(--s-fat)", ic: "pessoas", rotulo: "Clientes no CRM", valor: fmt.num(n),
      meta: `${plural(fora.sem_compra + fora.recente, "cliente ativo fora", "clientes ativos fora")} do CRM`,
      rodape: [["Nunca compraram", fmt.num(fora.sem_compra)], [`Primeira compra há menos de ${plural(r.meses_para_entrar, "mês", "meses")}`, fmt.num(fora.recente)]],
      dica: "Clientes ativos das equipes, com a primeira compra há mais tempo que o mínimo. Quem ficou fora não tem nota" })}
    ${kpi({ i: 2, cor: "var(--k-cli)", ic: "estrela", rotulo: "Nota média", valor: notaMedia == null ? "—" : fmt.num(notaMedia, 1),
      meta: "de 100 pontos",
      rodape: INDICADORES.map((ind) => [ind.rotulo, `${pts(media(lista, (c) => c[ind.id]?.pontos))} de ${fmt.num(max[ind.id])}`]) })}
    ${kpi({ i: 3, cor: "var(--s-mus)", ic: "ranking", rotulo: "Clientes por faixa da nota", valor: fmt.num(porFaixa[0][1]),
      meta: "com nota de 80 ou mais",
      rodape: porFaixa.map(([f, k]) => [`<span class="crm-bolinha" style="--c:${f.cor}"></span>Nota de ${esc(f.rotulo)}`, `${fmt.num(k)}${n ? ` · ${fmt.pct(k / n, 0)}` : ""}`]) })}
    ${kpi({ i: 4, cor: "var(--ruim-forte)", ic: "alerta", rotulo: "Sinalizados", valor: fmt.num(lista.filter((c) => c.sinais.length).length),
      meta: "o cadastro precisa de correção",
      rodape: [["Sem segmento ou segmento sem mix (0 no mix)", fmt.num(semMix)], ["Sem título a receber no período", fmt.num(semTitulo)]] })}
  </div>`;
}

// Pelos níveis da ordem (o último clique manda, os anteriores desempatam) e, no fim, pelo nome.
function ordenar(lista) {
  return ordenarPorNiveis(lista, estado.ordens, (campo, a, b) => {
    const col = coluna(campo);
    if (!col) return 0;
    const va = col.valor(a), vb = col.valor(b);
    return typeof va === "string" ? va.localeCompare(vb, "pt-BR") : va - vb;
  }, (a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

// manter: a releitura dos dados (cópia nova do banco), que deixa a tabela onde estava, com as linhas que já tinha.
// Sem ele (outro filtro, outra busca, outra ordem), a tabela volta para o começo.
function desenharTabela(manter = false) {
  const d = estado.dados, corpo = document.getElementById("crm-lista-corpo");
  if (!d || !corpo) return;
  const base = filtrados(d, false), lista = ordenar(filtrados(d));
  const iAberto = estado.aberto == null ? -1 : lista.findIndex((c) => c.id === estado.aberto);
  if (iAberto < 0) estado.aberto = null;
  const rolagem = corpo.querySelector(".tabela-rolagem");
  const pos = rolagem ? [manter === true ? rolagem.scrollTop : 0, rolagem.scrollLeft] : null;
  // Só o começo da lista (as próximas linhas entram ao rolar: maisLinhas). Com um cliente aberto, vai até a linha dele.
  listaAtual = lista;
  desenhadas = Math.min(lista.length, Math.max(LOTE, manter === true ? desenhadas : 0, Math.ceil((iAberto + 1) / LOTE) * LOTE));
  const th = (c) => {
    const m = marcaOrdem(estado.ordens, c.id);
    return `<th class="${c.esq ? "esq" : ""}"${m.aria}${c.dica ? ` title="${esc(c.dica)}"` : ""}>
      <button type="button" class="crm-ordem${m.classe}" data-ordem="${c.id}">${esc(c.rotulo)}<span class="crm-seta-o" aria-hidden="true">${m.seta}</span></button></th>`;
  };
  let tabela;
  if (!base.length) tabela = `<div class="vazio">${icone("pessoas")}<p>Nenhum cliente do CRM com estes filtros.</p></div>`;
  else if (!lista.length) tabela = `<div class="vazio">${icone("busca")}<p>Nenhum cliente com esta busca.</p></div>`;
  else {
    tabela = `${linhaOrdem(estado.ordens, ORDEM_PADRAO, (id) => { const c = coluna(id); return c && { rotulo: c.rotulo, tipo: TEXTO.includes(id) ? "texto" : "numero" }; })}
      <div class="tabela-rolagem crm-rolagem"><table class="dados crm-tabela${estado.animar ? " crm-entra" : ""}">
      <thead><tr>${COLUNAS.map(th).join("")}</tr></thead>
      <tbody>${lista.slice(0, desenhadas).map((c, i) => linha(c, i)).join("")}</tbody></table></div>
      <p class="crm-mais" hidden></p>`;
  }
  const contagem = lista.length === base.length ? plural(base.length, "cliente", "clientes") : `${fmt.num(lista.length)} de ${plural(base.length, "cliente", "clientes")}`;
  corpo.innerHTML = `<div class="cartao-cab"><div><h3>${icone("estrela")}Nota de cada cliente</h3>
    <p class="sub">${contagem} · clique no cliente para ver de onde sai cada nota</p></div></div>${tabela}`;
  const nova = corpo.querySelector(".tabela-rolagem");
  if (nova && pos) { nova.scrollTop = pos[0]; nova.scrollLeft = pos[1]; }
  observador?.disconnect();
  if (nova) {
    const medir = () => nova.style.setProperty("--crm-w", `${Math.max(280, nova.clientWidth - 26)}px`);
    medir();
    observador = new ResizeObserver(medir);
    observador.observe(nova);
  }
  avisoMais();
  vigiar();
  reajustarTelaCheia();
  if (estado.aberto != null) carregarDetalhe(estado.aberto);
}

const corpoDaTabela = () => document.querySelector("#crm-lista-corpo table.crm-tabela > tbody");

// Embaixo da tabela, enquanto faltam linhas: quantas já estão desenhadas.
function avisoMais() {
  const p = document.querySelector("#crm-lista-corpo .crm-mais");
  if (!p) return;
  p.hidden = desenhadas >= listaAtual.length;
  p.textContent = p.hidden ? "" : `Mostrando ${fmt.num(desenhadas)} de ${plural(listaAtual.length, "cliente", "clientes")} · role para ver os próximos`;
}

// As próximas linhas entram quando qualquer uma das últimas FOLGA aparece na tela: rolando a tabela aos poucos, pulando
// direto para o fim dela ou, em tela cheia, rolando a página. Se depois de entrarem as novas últimas já estiverem à
// vista (tela muito alta), entram mais.
function vigiar() {
  vigia?.disconnect();
  vigia = null;
  const tbody = corpoDaTabela();
  if (!tbody || desenhadas >= listaAtual.length) return;
  vigia = new IntersectionObserver((entradas) => { if (entradas.some((e) => e.isIntersecting)) maisLinhas(); });
  let tr = tbody.lastElementChild;
  for (let n = 0; tr && n < FOLGA; tr = tr.previousElementSibling) {
    if (tr.classList.contains("crm-linha")) { vigia.observe(tr); n += 1; }
  }
}

// Acrescenta o lote seguinte no fim da tabela, sem refazer as linhas que já estão.
function maisLinhas() {
  const tbody = corpoDaTabela();
  if (!tbody || desenhadas >= listaAtual.length) return;
  tbody.parentElement.classList.remove("crm-entra");  // a animação de entrada é só de quando a página abre
  const de = desenhadas;
  desenhadas = Math.min(listaAtual.length, de + LOTE);
  tbody.insertAdjacentHTML("beforeend", listaAtual.slice(de, desenhadas).map((c, i) => linha(c, de + i)).join(""));
  avisoMais();
  vigiar();
  reajustarTelaCheia();
}

const linhaDetalhe = (c) => `<tr class="crm-detalhe"><td colspan="${COLUNAS.length}"><div class="crm-det-caixa" id="crm-det-${c.id}">${detalhe(c)}</div></td></tr>`;

function linha(c, i) {
  const f = faixaDe(c.nota), aberto = c.id === estado.aberto;
  const local = [c.cidade, c.uf].filter(Boolean).join(" - ");
  const freq = c.frequencia === "outra rede" || c.frequencia === "sem rede"
    ? `Semanal<small>${c.frequencia === "outra rede" ? `rede ${esc(c.rede || "")}` : "sem rede no cadastro"}</small>` : esc(FREQ[c.frequencia] || c.frequencia);
  return `<tr class="crm-linha${aberto ? " crm-aberta" : ""}" data-cliente="${c.id}" tabindex="0" aria-expanded="${aberto}" style="--i:${Math.min(i, 20)}">
      <td class="esq"><b>${esc(c.nome)}</b><small>${c.id}${local ? ` · ${esc(local)}` : ""}${c.sinais.length ? ` · <span class="crm-sinal" title="${esc(c.sinais.join("; "))}">${icone("alerta")}${esc(c.sinais[0])}</span>` : ""}</small></td>
      <td class="esq">${esc(c.vendedor.nome)}</td>
      <td class="esq">${esc(c.segmento || "—")}</td>
      <td class="esq">${freq}</td>
      <td><span class="crm-nota" style="--c:${f.cor}" title="${esc(`Nota exata: ${fmt.num(c.nota_exata, 2)}`)}">${fmt.num(c.nota)}</span></td>
      ${INDICADORES.map((ind) => `<td class="crm-pts">${pts(c[ind.id]?.pontos)}</td>`).join("")}
      <td>${c.rentabilidade ? fmt.moeda(c.rentabilidade.lucro) : "—"}</td>
    </tr>${aberto ? linhaDetalhe(c) : ""}`;
}

function aoClicarLista(e) {
  const ordem = e.target.closest("[data-ordem]");
  if (ordem) {
    const campo = ordem.dataset.ordem;
    estado.ordens = clicarOrdem(estado.ordens, campo, !TEXTO.includes(campo));
    guardar("mv-crm", { ordem: estado.ordens });
    desenharTabela();
    return;
  }
  if (e.target.closest("[data-ordem-padrao]")) {
    estado.ordens = ORDEM_PADRAO;
    guardar("mv-crm", { ordem: estado.ordens });
    desenharTabela();
    return;
  }
  if (e.target.closest(".crm-detalhe")) return;
  const tr = e.target.closest("tr[data-cliente]");
  if (tr) alternar(Number(tr.dataset.cliente));
}

// Abre o quadro do cliente (ou fecha, se já era ele) mexendo só nas linhas dele: a tabela não é refeita.
function alternar(id) {
  const tbody = corpoDaTabela();
  if (!tbody) return;
  tbody.parentElement.classList.remove("crm-entra");  // o quadro não entra com a animação da abertura da página
  tbody.querySelectorAll(":scope > tr.crm-aberta").forEach((tr) => {
    tr.classList.remove("crm-aberta");
    tr.setAttribute("aria-expanded", "false");
  });
  tbody.querySelectorAll(":scope > tr.crm-detalhe").forEach((tr) => tr.remove());
  const tr = tbody.querySelector(`:scope > tr[data-cliente="${id}"]`);
  const c = estado.aberto === id ? null : listaAtual.find((x) => x.id === id);
  estado.aberto = c && tr ? id : null;
  if (estado.aberto != null) {
    tr.classList.add("crm-aberta");
    tr.setAttribute("aria-expanded", "true");
    tr.insertAdjacentHTML("afterend", linhaDetalhe(c));
    carregarDetalhe(id);
  }
  reajustarTelaCheia();
  tr?.focus({ preventScroll: true });
}

async function carregarDetalhe(id) {
  if (estado.detalhes[id]) return;
  estado.detalhes[id] = { carregando: true };
  try {
    estado.detalhes[id] = await api(`/api/crm/cliente?id=${encodeURIComponent(id)}`);
  } catch (e) {
    estado.detalhes[id] = { erro: e.message };
  }
  const alvo = document.getElementById(`crm-det-${id}`);
  const c = estado.dados?.itens.find((x) => x.id === id);
  if (alvo && c) { alvo.innerHTML = detalhe(c); reajustarTelaCheia(); }
}

function bloco(ic, titulo, pontos, max, corpo) {
  return `<div class="crm-bloco"><div class="crm-bloco-cab"><h4>${icone(ic)}${esc(titulo)}</h4>
    <span class="crm-bloco-pts">${pontos == null ? "sem nota" : `${pts(pontos)} <small>de ${fmt.num(max)}</small>`}</span></div>${corpo}</div>`;
}

function detalhe(c) {
  const det = estado.detalhes[c.id];
  if (!det || det.carregando) return `<div class="crm-det-carregando">${icone("relogio")}Carregando…</div>`;
  if (det.erro) return `<div class="aviso">${icone("alerta")}<span>${esc(det.erro)}</span></div>`;
  const r = estado.dados.regras;
  const a = c.aderencia, p = c.pontualidade, m = c.mix, rent = c.rentabilidade;
  const fq = FREQ[c.frequencia] || c.frequencia;
  const ader = a.regra === "semanas"
    ? `<p>${esc(fq)}${c.rede && c.frequencia === "outra rede" ? `, pela rede ${esc(c.rede)}` : ""}: comprou em <b>${plural(a.com_compra, "semana", "semanas")} de ${fmt.num(a.semanas)}</b> (${fmt.num(a.pct, 1)}%), contando desde ${data(a.inicio)}.</p>`
    : `<p>${esc(fq)}: cada compra deixa o cliente em dia por <b>${plural(a.prazo, "dia", "dias")}</b>. ${a.atraso ? `Ficou <b>${plural(a.atraso, "dia", "dias")} em atraso</b>` : "<b>Não ficou em atraso</b>"} em ${plural(a.dias, "dia", "dias")} desde ${data(a.inicio)} (${fmt.num(a.pct, 1)}% em dia)${a.maior_distancia != null ? `; a maior distância entre duas compras foi de ${plural(a.maior_distancia, "dia", "dias")}` : ""}.</p>`;
  const compras = (det.compras || []).length
    ? `<p class="crm-fraco">As compras contadas (a primeira de cada semana):</p><div class="crm-compras">${det.compras.map((x) => `<span>${esc(data(x).slice(0, 5))}</span>`).join("")}</div>`
    : `<p class="crm-fraco">Nenhuma compra no período.</p>`;
  const pont = !p ? `<p class="crm-fraco">Os títulos a receber ainda não chegaram do computador da empresa.</p>`
    : p.titulos === 0 ? `<p>Nenhum título a receber vencido desde ${data(r.pontualidade.desde)}: fica com ${plural(p.pontos, "ponto", "pontos")}, sinalizado.</p>`
      : `<p><b>${fmt.num(p.pct, 1)}%</b> de ${plural(p.titulos, "título", "títulos")} pagos em dia (até ${plural(r.pontualidade.tolerancia, "dia", "dias")} depois do vencimento) desde ${data(r.pontualidade.desde)}: ${plural(p.base, "ponto", "pontos")}.</p>
        <p>${p.atraso_medio == null ? "Nunca atrasou." : `Quando atrasa, paga em média <b>${fmt.num(p.atraso_medio, 1)} dias</b> depois do vencimento${p.desconto ? `: desconta ${plural(p.desconto, "ponto", "pontos")}` : ", sem desconto"}.`}${p.em_aberto ? ` ${p.em_aberto === 1 ? "1 título vencido está em aberto" : `${fmt.num(p.em_aberto)} títulos vencidos estão em aberto`}.` : ""}</p>`;
  const linkMix = ctx.admin && c.segmento ? ` <a href="#/config-crm?secao=mix&seg=${encodeURIComponent(c.segmento)}">Montar o mix de ${esc(c.segmento)}</a>.` : "";
  const mix = !m ? `<p class="crm-fraco">Os pedidos um a um ainda não chegaram do computador da empresa.</p>`
    : m.sinal ? `<p>${esc(maiuscula(m.sinal))}: fica com 0 no mix. ${c.segmento ? "Confira o segmento no cadastro do ERP." : "Preencha o segmento no cadastro do ERP."}${m.sinal.includes("sem mix") ? linkMix : ""}</p>`
      : `<p>Comprou <b>${fmt.num(m.atendidos)} de ${plural(m.itens, "item", "itens")}</b> do mix ideal de ${esc(c.segmento)} desde ${data(a.inicio)}.</p>
        <ul class="crm-mix">${(det.mix_itens || []).map((x) => `<li class="${x.atendido ? "ok" : "falta"}">${icone(x.atendido ? "certo" : "mais")}<span>${esc(x.nome)}</span></li>`).join("")}</ul>
        ${(det.mix_itens || []).some((x) => !x.atendido) ? `<p class="crm-fraco">Os itens com + o cliente não comprou no período: é o que dá para oferecer.</p>` : ""}`;
  const onde = !rent ? "" : rent.quintil === 1 ? "entre os 20% de maior lucro do CRM" : rent.quintil === 5 ? "entre os 20% de menor lucro do CRM (ou sem lucro)" : `no ${rent.quintil}º quintil do CRM, de 5`;
  const rentab = !rent ? `<p class="crm-fraco">Sem custo industrial em Configurar ou sem as vendas por cliente.</p>`
    : `<p>De ${mesRotulo(r.rentabilidade.desde)} a ${mesRotulo(r.rentabilidade.ate)}, faturou ${fmt.moeda(rent.faturamento)} e deixou <b>${fmt.moeda(rent.lucro)}</b> de lucro bruto${rent.margem != null ? ` (margem de ${fmt.num(rent.margem, 1)}%)` : ""}: ${onde}.${rent.sem_custo ? ` ${fmt.moeda(rent.sem_custo)} em produtos sem custo ficaram fora da conta.` : ""}</p>
      ${(det.rent_meses || []).length ? `<table class="dados crm-mini"><thead><tr><th class="esq">Mês</th><th>Faturamento</th><th>Lucro bruto</th><th>Margem</th></tr></thead><tbody>
        ${det.rent_meses.map((x) => { const base = x.faturamento - x.sem_custo; return `<tr><td class="esq">${mesRotulo(x.mes)}</td><td>${fmt.moeda(x.faturamento)}</td><td>${fmt.moeda(x.lucro)}</td><td>${base > 0 ? fmt.pct(x.lucro / base, 1) : "—"}</td></tr>`; }).join("")}</tbody></table>` : ""}
      ${(det.rent_produtos || []).length ? `<table class="dados crm-mini"><thead><tr><th class="esq">Produto</th><th>Volume</th><th>Faturamento</th><th>Lucro bruto</th></tr></thead><tbody>
        ${det.rent_produtos.slice(0, 10).map((x) => `<tr><td class="esq">${esc(x.nome)}${x.sem_custo ? ' <small class="crm-fraco">sem custo</small>' : ""}</td><td>${fmt.num(x.volume, 1)}</td><td>${fmt.moeda(x.faturamento)}</td><td>${x.sem_custo && !x.lucro ? "—" : fmt.moeda(x.lucro)}</td></tr>`).join("")}</tbody></table>
        ${det.rent_produtos.length > 10 ? `<p class="crm-fraco">Os 10 produtos de maior lucro, de ${fmt.num(det.rent_produtos.length)}.</p>` : ""}` : ""}`;
  return `<div class="crm-det">
    ${bloco("calendario", "Aderência à frequência", a.pontos, r.aderencia.faixas[0]?.pontos, ader + compras)}
    ${bloco("recibo", "Pontualidade de pagamento", p?.pontos, r.pontualidade.faixas[0]?.pontos, pont)}
    ${bloco("queijo", "Mix ideal do segmento", m?.pontos, r.mix.pontos, mix)}
    ${bloco("grafico", "Rentabilidade", rent?.pontos, r.rentabilidade.pontos[0], rentab)}
  </div>`;
}

function metodo(d) {
  const r = d.regras, per = r.periodo;
  const faixas = (lista, sufixo) => lista.map((f) => `${fmt.num(f.de)}${sufixo} = ${plural(f.pontos, "ponto", "pontos")}`).join("; ");
  const cortes = r.rentabilidade.cortes || [];
  return `<details class="crm-metodo"><summary>${icone("info")}Como a nota é calculada</summary>
    <ul>
      <li><b>Quem entra:</b> os clientes ativos dos vendedores das equipes ${esc(r.equipes.join(" e "))}, sem "PEDIDO BLOQUEADO" no nome, com a primeira compra há mais de ${plural(r.meses_para_entrar, "mês", "meses")}. Quem nunca comprou, ou é mais novo, fica fora, sem nota. A compra é o pedido de venda não cancelado, de qualquer vendedor.</li>
      <li><b>Aderência (${fmt.num(r.aderencia.faixas[0]?.pontos)} pontos):</b> as ${fmt.num(r.aderencia.semanas)} semanas fechadas de ${data(per.ini)} a ${data(per.fim)}, desde a primeira compra quando ela é mais recente, com uma compra por semana (a primeira). O semanal, e quem tem outra rede ou nenhuma, conta as semanas com compra; o quinzenal e o mensal, a parte do período em dia, com ${fmt.num(r.aderencia.prazo_quinzenal)} e ${fmt.num(r.aderencia.prazo_mensal)} dias entre as compras. A partir de ${faixas(r.aderencia.faixas, "%")}.</li>
      <li><b>Pontualidade (${fmt.num(r.pontualidade.faixas[0]?.pontos)} pontos):</b> os títulos que venceram desde ${data(r.pontualidade.desde)}. Pontual é o pago até ${plural(r.pontualidade.tolerancia, "dia", "dias")} depois do vencimento; o em aberto conta como atrasado. A partir de ${faixas(r.pontualidade.faixas, "%")}. O atraso médio dos atrasados desconta: ${r.pontualidade.descontos.map((f) => `a partir de ${plural(f.de, "dia", "dias")}, ${plural(f.pontos, "ponto", "pontos")}`).join("; ")}. Sem título no período: ${plural(r.pontualidade.sem_titulo, "ponto", "pontos")}, sinalizado.</li>
      <li><b>Mix (${fmt.num(r.mix.pontos)} pontos):</b> ${fmt.num(r.mix.pontos)} × os itens do mix ideal do segmento que o cliente comprou no mesmo período ÷ os itens do mix. Os produtos de um mesmo item valem um pelo outro; "qualquer mussarela" vale qualquer mussarela. Sem segmento, ou de segmento sem mix: 0, sinalizado.</li>
      <li><b>Rentabilidade (${fmt.num(r.rentabilidade.pontos[0])} pontos):</b> lucro bruto = faturamento − custo industrial × volume, por produto e mês, de ${mesRotulo(r.rentabilidade.desde)} até ${r.rentabilidade.ate ? mesRotulo(r.rentabilidade.ate) : "o último mês com custo"}. Os clientes do CRM são divididos em cinco partes iguais pelo lucro: ${r.rentabilidade.pontos.map((x) => fmt.num(x)).join(", ")} pontos${cortes.length === 4 ? ` (hoje, acima de ${fmt.moeda(cortes[3])}, de ${fmt.moeda(cortes[2])}, de ${fmt.moeda(cortes[1])}, de ${fmt.moeda(cortes[0])} e o resto)` : ""}.</li>
      <li><b>A nota</b> é a soma dos quatro, arredondada só no fim. As faixas da nota (80 a 100 e as outras) servem só para ler a distribuição.</li>
    </ul></details>`;
}
