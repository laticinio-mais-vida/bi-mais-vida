// As listas de clientes numa janela sobre a página, com o fundo escuro (bi/metas_clientes.py): o que dá para fazer para
// melhorar um número.
// - Página Metas (abas ES, BA e Edir), com a aba, os meses e os vendedores da página: os clientes da carteira que o
//   vendedor não atendeu (card "Clientes atendidos") e os que deixaram de levar algum item do mix ideal do segmento
//   (card "Composição do faturamento"; o mix fica em CRM › Configurar › Mix ideal).
// - Painel de desempenho da Gestão, com a região e o período do painel: Positivação, Atendimentos, Mussarela e Outras
//   linhas de um vendedor ou da equipe (o seletor da janela troca).
// A tabela entra em lotes de 100 linhas, sem a animação das linhas (centenas de linhas animando travam o navegador), e
// ordena em até 3 níveis, como no CRM.
import { api, esc, fmt, icone, clicarOrdem, ordenarPorNiveis, marcaOrdem, linhaOrdem } from "./util.js";

const LOTE = 100, FOLGA = 25;
const semAcento = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;

let dlg = null, apertouFora = false;
// op: { tipo, url, params (da rota), admin }; dados: a resposta.
const estado = { tipo: null, op: null, dados: null, busca: "", ordens: [], pedido: 0 };
let listaAtual = [], desenhadas = 0, vigia = null;

const textoCliente = (c) => `${c.nome} ${c.cidade || ""} ${c.area || ""} ${c.segmento || ""} ${c.vendedor.nome} ${(c.outros || []).join(" ")}`;
const POTENCIAL = [{ campo: "potencial", desc: true }];

const LISTAS = {
  // página Metas
  nao_atendidos: {
    titulo: "Clientes não atendidos", icone: "pessoas", busca: "Buscar cliente, cidade ou área",
    padrao: [{ campo: "media", desc: true }], texto: textoCliente,
  },
  mix: {
    titulo: "Clientes que não compraram produtos indicados", icone: "queijo", busca: "Buscar cliente ou produto",
    padrao: [{ campo: "faltou", desc: true }, { campo: "comprado", desc: true }],
    texto: (c) => `${textoCliente(c)} ${c.faltou.join(" ")}`,
  },
  // painel de desempenho da Gestão
  positivacao: {
    titulo: "Positivação · clientes que não compraram no mês", icone: "pessoas", busca: "Buscar cliente, cidade ou área",
    padrao: POTENCIAL, texto: textoCliente,
  },
  atendimentos: {
    titulo: "Atendimentos · clientes esperados que não foram atendidos", icone: "calendario", busca: "Buscar cliente, cidade ou área",
    padrao: POTENCIAL, texto: (c) => `${textoCliente(c)} ${c.frequencia || ""}`,
  },
  mussarela: {
    titulo: "Mussarela · clientes que não levaram mussarela", icone: "queijo", busca: "Buscar cliente, cidade ou segmento",
    padrao: POTENCIAL, texto: textoCliente,
  },
  outras: {
    titulo: "Outras linhas · clientes que não levaram produtos indicados", icone: "leite", busca: "Buscar cliente ou produto",
    padrao: POTENCIAL, texto: (c) => `${textoCliente(c)} ${c.faltou.join(" ")}`,
  },
};

const doPainel = () => ["positivacao", "atendimentos", "mussarela", "outras"].includes(estado.tipo);
const variosVendedores = (d) => d.vendedores.length > 1;
const variosMeses = (d) => !doPainel() && d.periodo.meses.length > 1;

function cidade(c) { return c.cidade ? `${c.cidade}${c.uf ? `/${c.uf}` : ""}` : "—"; }
const dataLonga = (iso) => `${fmt.semana(iso)}, ${fmt.dataCurta(iso)}`;

function emLista(itens) {
  return itens.length < 2 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`;
}

// O cliente e, embaixo, o que explica a linha: quem vendeu no lugar do vendedor, o pedido fora do dia da rota ou o
// cliente esperado que não comprou nada no período.
function celCliente(c) {
  const marcas = [];
  if (c.outros?.length) marcas.push(`<span class="mc-outro">${icone("usuario")}comprou com ${esc(c.outros.join(", "))}</span>`);
  else if (c.pedido_sem_nota) marcas.push(`<span class="mc-outro">${icone("recibo")}fez pedido no período, ainda sem nota</span>`);
  else if (c.comprou === false) marcas.push(`<span class="mc-outro mc-sem">${icone("menos")}não comprou no período</span>`);
  if (c.fora_do_dia?.length) {
    const datas = emLista(c.fora_do_dia.map(fmt.dataCurta));
    marcas.push(`<span class="mc-outro">${icone("calendario")}${c.fora_do_dia.length > 1 ? "pedidos" : "pedido"} em ${datas}, fora do dia da rota</span>`);
  }
  return `<td class="esq mc-cliente"><b>${esc(c.nome)}</b>${marcas.join("")}</td>`;
}

function celUltima(c) {
  if (!c.ultima) return `<td class="esq"><span class="mc-fraco">nunca comprou</span></td>`;
  const ha = c.dias === 0 ? "hoje" : c.dias === 1 ? "ontem" : `há ${fmt.num(c.dias)} dias`;
  return `<td class="esq">${fmt.data(c.ultima)}<small>${ha}</small></td>`;
}

function celMix(c) {
  const pct = c.itens ? c.levados / c.itens : 0;
  return `<td class="mc-mix"><b>${fmt.num(c.levados)} de ${fmt.num(c.itens)}</b>
    <span class="mc-barra" aria-hidden="true"><span style="width:${(pct * 100).toFixed(1)}%"></span></span></td>`;
}

// Os itens que faltaram: os primeiros VISIVEIS e um botão que mostra o resto na própria linha (um mix de 21 itens deixaria
// a linha alta demais). A busca acha por todos; com ela, os itens que batem com o termo vêm primeiro, para aparecerem.
const VISIVEIS = 6;
function celFaltou(c) {
  const resto = c.faltou.length - VISIVEIS;
  const termo = semAcento(estado.busca.trim());
  const itens = termo ? [...c.faltou].sort((a, b) => semAcento(b).includes(termo) - semAcento(a).includes(termo)) : c.faltou;
  const chips = itens.map((f) => `<span class="mc-item">${esc(f)}</span>`).join("");
  return `<td class="esq mc-faltou"><div class="mc-itens${resto > 0 ? " recolhido" : ""}">${chips}${resto > 0
    ? `<button type="button" class="mc-ver-itens" data-expandir aria-label="Mostrar os outros ${resto} itens">+ ${fmt.num(resto)} ${resto === 1 ? "item" : "itens"}</button>` : ""}</div></td>`;
}

const texto = (id, rotulo, valor, extra = {}) => ({ id, rotulo, tipo: "texto", valor: (c) => valor(c) || "", cel: (c) => `<td class="esq${extra.classe ? ` ${extra.classe}` : ""}">${esc(valor(c) || "—")}</td>`, ...extra });
const COL = {
  cliente: { id: "cliente", rotulo: "Cliente", tipo: "texto", valor: (c) => c.nome, cel: celCliente },
  vendedor: texto("vendedor", "Vendedor", (c) => c.vendedor.nome),
  area: texto("area", "Área", (c) => c.area),
  cidade: { id: "cidade", rotulo: "Cidade", tipo: "texto", valor: (c) => c.cidade || "", cel: (c) => `<td class="esq">${esc(cidade(c))}</td>` },
  segmento: texto("segmento", "Segmento", (c) => c.segmento, { classe: "mc-seg" }),
  ultima: { id: "ultima", rotulo: "Última compra", tipo: "data", valor: (c) => c.ultima || "", cel: celUltima,
    dica: "A última compra do cliente, com qualquer vendedor" },
  potencial: { id: "potencial", rotulo: "Potencial do mês", tipo: "numero", valor: (c) => c.potencial, cel: (c) => `<td>${fmt.moeda(c.potencial)}</td>`,
    dica: "A média do que o cliente comprou nos 2 meses fechados antes do mês, com qualquer vendedor (a conta da meta do dia)" },
  comprado: { id: "comprado", rotulo: "Comprado no período", tipo: "numero", valor: (c) => c.comprado, cel: (c) => `<td>${fmt.moeda(c.comprado)}</td>`,
    dica: "O que o cliente comprou no período, com qualquer vendedor" },
  mix: { id: "mix", rotulo: "Mix levado", tipo: "numero", valor: (c) => (c.itens ? c.levados / c.itens : 0), cel: celMix,
    dica: "Quantos itens do mix ideal do segmento o cliente levou no período" },
  faltou: { id: "faltou", rotulo: "Faltou", tipo: "numero", valor: (c) => c.faltou.length, cel: celFaltou,
    sentidos: ["menos itens primeiro", "mais itens primeiro"], dica: "Os itens do mix ideal que o cliente não levou: é o que dá para oferecer" },
  dia: { id: "dia", rotulo: "Dia esperado", tipo: "data", valor: (c) => c.dia, cel: (c) => `<td class="esq">${dataLonga(c.dia)}</td>`,
    dica: "O dia da rota em que o cliente era esperado (na área com mais de um dia, o último dia marcado da semana)" },
  frequencia: { id: "frequencia", rotulo: "Frequência", tipo: "texto", valor: (c) => c.frequencia || "semanal",
    cel: (c) => `<td class="esq">${c.frequencia ? esc(c.frequencia) : `semanal<small>sem frequência no cadastro</small>`}</td>`,
    dica: "A frequência de compra do cadastro (a rede): semanal, quinzenal ou mensal" },
  ultimo_pedido: { id: "ultimo_pedido", rotulo: "Último pedido", tipo: "data", valor: (c) => c.ultimo_pedido || "",
    cel: (c) => `<td class="esq">${c.ultimo_pedido ? fmt.data(c.ultimo_pedido) : `<span class="mc-fraco">nenhum</span>`}</td>`,
    dica: "O último pedido de venda do cliente, com qualquer vendedor" },
};

// As colunas de cada lista. valor: para ordenar (texto ou número); cel: a célula.
function colunas(d) {
  const vend = variosVendedores(d) && COL.vendedor;
  const lista = {
    nao_atendidos: [COL.cliente, vend, COL.area, COL.cidade, COL.segmento, COL.ultima,
      { id: "media", rotulo: "Compra média por mês", tipo: "numero", valor: (c) => c.media, cel: (c) => `<td>${fmt.moeda(c.media)}</td>`,
        dica: d.media ? `As compras de ${d.media.de} a ${d.media.ate}, com qualquer vendedor, divididas por ${d.media.meses}` : "" },
      variosMeses(d) && { id: "meses_sem", rotulo: "Meses sem compra", tipo: "numero", valor: (c) => c.meses_sem.length,
        cel: (c) => `<td class="esq">${esc(c.meses_sem.join(", "))}</td>`, dica: "Os meses do período em que o cliente não comprou com o vendedor" }],
    mix: [COL.cliente, vend, COL.segmento, COL.comprado, COL.mix, COL.faltou],
    positivacao: [COL.cliente, vend, COL.area, COL.cidade, COL.segmento, COL.ultima, COL.potencial],
    atendimentos: [COL.cliente, vend, COL.area, COL.dia, COL.frequencia, COL.ultimo_pedido, COL.potencial],
    mussarela: [COL.cliente, vend, COL.area, COL.segmento, COL.comprado, COL.potencial],
    outras: [COL.cliente, vend, COL.segmento, COL.comprado, COL.mix, COL.faltou, COL.potencial],
  }[estado.tipo];
  return lista.filter(Boolean);
}

// ---------- abrir, carregar e fechar ----------
// op: { tipo (uma das LISTAS), url (a rota), params (os da rota; vazio fica fora), admin }.
export function abrirListaClientes(op) {
  criar();
  Object.assign(estado, { tipo: op.tipo, op: { ...op, params: { ...op.params } }, busca: "",
    ordens: LISTAS[op.tipo].padrao.map((n) => ({ ...n })) });
  if (!dlg.open) dlg.showModal();
  carregar();
}

export function fecharListaClientes() {
  if (dlg?.open) dlg.close();
}

async function carregar() {
  const pedido = ++estado.pedido, L = LISTAS[estado.tipo];
  estado.dados = null;
  dlg.setAttribute("aria-label", L.titulo);
  dlg.innerHTML = `<div class="mc-corpo">${cabecalho(L.titulo, "Carregando a lista…")}
    <div class="esqueleto" style="height:90px;margin-top:16px"></div><div class="esqueleto" style="height:260px;margin-top:12px"></div></div>`;
  try {
    const p = new URLSearchParams();
    Object.entries(estado.op.params).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") p.set(k, v); });
    const d = await api(`${estado.op.url}?${p}`);
    if (pedido !== estado.pedido || !dlg.open) return;
    estado.dados = d;
    desenhar();
  } catch (e) {
    if (pedido !== estado.pedido || !dlg.open) return;
    dlg.innerHTML = `<div class="mc-corpo">${cabecalho(L.titulo, "")}
      <div class="vazio">${icone("alerta")}<p>Não foi possível carregar a lista: ${esc(e.message)}</p></div></div>`;
  }
}

function criar() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo mc-janela";
  document.body.appendChild(dlg);
  // Fecha no X, no Esc (o próprio <dialog>) e no clique no fundo escuro: o clique fora cai no próprio <dialog>, porque o
  // conteúdo (.mc-corpo) o preenche inteiro. Só quando o clique começou fora (selecionar um texto e soltar fora não fecha).
  dlg.addEventListener("pointerdown", (e) => { apertouFora = e.target === dlg; });
  dlg.addEventListener("click", aoClicar);
  dlg.addEventListener("input", (e) => {
    if (e.target.id !== "mc-busca") return;
    estado.busca = e.target.value;
    desenharTabela();
  });
  dlg.addEventListener("change", (e) => {  // o vendedor da lista do painel (vazio = a equipe toda)
    if (e.target.id !== "mc-vendedor") return;
    estado.op.params.vendedor = e.target.value;
    estado.busca = "";
    carregar();
  });
  dlg.addEventListener("close", () => {
    estado.pedido += 1;
    vigia?.disconnect();
    vigia = null;
    dlg.innerHTML = "";
  });
  window.addEventListener("hashchange", fecharListaClientes);
}

function aoClicar(e) {
  if (e.target === dlg) {
    if (apertouFora) dlg.close();
    return;
  }
  const b = e.target.closest("button");
  if (!b) return;
  if ("fechar" in b.dataset) return dlg.close();
  if ("expandir" in b.dataset) {
    b.parentElement.classList.remove("recolhido");
    return b.remove();
  }
  if ("ordemPadrao" in b.dataset) {
    estado.ordens = LISTAS[estado.tipo].padrao.map((n) => ({ ...n }));
    return desenharTabela();
  }
  const campo = b.dataset.ordem;
  if (campo && estado.dados) {
    const cols = colunas(estado.dados);
    const col = cols.find((c) => c.id === campo);
    const ids = new Set(cols.map((c) => c.id));
    estado.ordens = clicarOrdem(estado.ordens, campo, col && col.tipo !== "texto", (k) => ids.has(k));
    desenharTabela();
  }
}

// ---------- o desenho ----------
function cabecalho(titulo, sub) {
  return `<div class="ag-hist-cab mc-cab">
    <div><h2>${icone(LISTAS[estado.tipo].icone)}${esc(titulo)}</h2>${sub ? `<p class="sub">${sub}</p>` : ""}</div>
    <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar">${icone("x")}</button>
  </div>`;
}

function stat(rotulo, valor, extra = "", destaque = false) {
  return `<div class="mini-stat${destaque ? " mc-destaque" : ""}"><div class="r">${rotulo}</div><div class="v">${fmt.num(valor)}</div>${extra ? `<small>${extra}</small>` : ""}</div>`;
}

function quem(d) {
  if (!d.vendedores.length) return "nenhum vendedor";
  if (d.vendedores.length === 1) return esc(d.vendedores[0].nome);
  return doPainel() ? `equipe ${esc(d.regiao)} (${plural(d.vendedores.length, "vendedor", "vendedores")})`
    : plural(d.vendedores.length, "vendedor", "vendedores");
}

// O período da lista: na página Metas, o rótulo dos meses; no painel, o do painel (a positivação vai do dia 1º do mês).
function periodo(d) {
  if (!doPainel()) return esc(d.periodo.rotulo);
  const p = d.periodo;
  if (estado.tipo === "positivacao") return `mês até ${p.chave === "hoje" ? "hoje" : dataLonga(p.fim)}: de ${fmt.dataCurta(d.mes)} a ${fmt.dataCurta(p.fim)}`;
  if (p.inicio === p.fim) return p.chave === "hoje" ? `hoje, ${fmt.dataCurta(p.fim)}` : dataLonga(p.fim);
  return `semana de ${fmt.dataCurta(p.inicio)} a ${fmt.dataCurta(p.fim)}`;
}

function foraDaLista(r, parte) {
  const fora = [];
  if (parte === "mussarela" && r.sem_parte) fora.push(`${plural(r.sem_parte, "cliente", "clientes")} de segmento sem mussarela no mix ideal (${esc(r.segmentos_sem_parte.join(", "))})`);
  if (parte === "outras" && r.sem_parte) fora.push(`${plural(r.sem_parte, "cliente", "clientes")} de segmento cujo mix ideal só tem mussarela (${esc(r.segmentos_sem_parte.join(", "))})`);
  if (r.sem_mix) fora.push(`${plural(r.sem_mix, "cliente", "clientes")} de segmento sem mix ideal (${esc(r.segmentos_sem_mix.join(", "))})`);
  if (r.sem_segmento) fora.push(`${plural(r.sem_segmento, "cliente", "clientes")} sem segmento no cadastro`);
  return fora.length ? `<p class="mc-nota">${icone("info")}<span>Ficam fora da lista: ${emLista(fora)}.</span></p>` : "";
}

function resumo(d) {
  const r = d.resumo;
  if (!r) return "";
  const t = estado.tipo;
  if (t === "nao_atendidos" || t === "positivacao") {
    const varios = variosMeses(d);
    return `<div class="mc-resumo">
      ${stat("Carteira de hoje", r.carteira, "clientes ativos")}
      ${stat(varios ? "Compraram em todos os meses" : "Compraram com o vendedor", r.atendidos, t === "positivacao" ? `de ${fmt.dataCurta(r.de)} a ${fmt.dataCurta(r.ate)}` : "")}
      ${stat(varios ? "Ficaram algum mês sem comprar" : "Não compraram", r.nao_atendidos,
        r.com_outro ? `${plural(r.com_outro, "comprou", "compraram")} com outro vendedor` : "", true)}
    </div>`;
  }
  if (t === "atendimentos") {
    return `<div class="mc-resumo">
      ${stat("Clientes esperados", r.esperados, "na rota do período")}
      ${stat("Atendidos", r.atendidos, "com pedido no dia da rota")}
      ${stat("Não atendidos", r.nao_atendidos, r.fora_do_dia ? `${plural(r.fora_do_dia, "fez", "fizeram")} pedido fora do dia da rota` : "", true)}
    </div>`;
  }
  if (t === "mix") {
    return `<div class="mc-resumo">
      ${stat("Compraram com o vendedor", r.atendidos, "da carteira de hoje")}
      ${stat("Levaram todo o mix", r.completos)}
      ${stat("Deixaram de levar algum item", r.com_falta, "", true)}
    </div>${foraDaLista(r, "tudo")}`;
  }
  const base = `${plural(r.atendidos, "comprou", "compraram")} com o vendedor${r.esperados_sem_compra ? ` · ${fmt.num(r.esperados_sem_compra)} esperados na rota sem compra` : ""}`;
  const semNota = r.pedido_sem_nota ? `<p class="mc-nota">${icone("recibo")}<span>${plural(r.pedido_sem_nota, "cliente da lista fez", "clientes da lista fizeram")} pedido no período, mas a nota ainda não entrou nos dados (${r.pedido_sem_nota === 1 ? "aparece marcado" : "aparecem marcados"}): o que ${r.pedido_sem_nota === 1 ? "ele levou" : "eles levaram"} só conta depois da nota.</span></p>` : "";
  return `<div class="mc-resumo">
      ${stat("Clientes do período", r.base, base)}
      ${stat(t === "mussarela" ? "Levaram mussarela" : "Levaram todo o mix", r.completos, t === "outras" ? "sem contar a mussarela" : "")}
      ${stat(t === "mussarela" ? "Não levaram mussarela" : "Deixaram de levar algum item", r.com_falta, "", true)}
    </div>${foraDaLista(r, t)}${semNota}`;
}

function como(d) {
  const onde = estado.op.admin ? `<a href="#/config-crm?secao=mix">CRM › Configurar › Mix ideal</a>` : "CRM › Configurar › Mix ideal";
  const carteira = "A lista parte da <b>carteira de hoje</b> de cada vendedor: os clientes ativos no ERP, sem “PEDIDO BLOQUEADO” no nome.";
  const potencial = "<p><b>Potencial do mês:</b> a média do que o cliente comprou nos 2 meses fechados antes do mês (venda menos a devolução que desconta, com qualquer vendedor), a mesma conta da meta do dia. A lista começa pelo maior.</p>";
  switch (estado.tipo) {
    case "nao_atendidos":
      return `<p>${carteira}
        Fica na lista quem não comprou com o próprio vendedor ${variosMeses(d) ? "em pelo menos um dos meses" : "no mês"} (venda faturada e não cancelada),
        a mesma regra do card, que conta o cliente para quem fez a venda. Quem comprou com outro vendedor aparece com o nome dele.</p>
        <p>O número do card pode ser um pouco diferente: ele conta todos os clientes para quem o vendedor vendeu, estejam ou não na carteira dele hoje.</p>
        <p><b>Compra média por mês:</b> o que o cliente comprou de ${esc(d.media.de)} a ${esc(d.media.ate)}, com qualquer vendedor, dividido por ${d.media.meses}.
        <b>Última compra:</b> com qualquer vendedor.</p>`;
    case "mix":
      return `<p>Entram os clientes da carteira de hoje que compraram com o próprio vendedor no período.
        O que eles levaram (com qualquer vendedor) é comparado com o <b>mix ideal do segmento</b>, em ${onde}.
        Um item com vários produtos vale com qualquer um deles, e “Qualquer mussarela” vale com qualquer produto da linha mussarela.</p>
        <p>Fica na lista quem deixou de levar pelo menos um item. Uma devolução não tira o item.
        ${d.resumo.nao_atendidos ? `Os ${plural(d.resumo.nao_atendidos, "cliente", "clientes")} da carteira que não compraram com o vendedor estão em “Clientes não atendidos”.` : ""}</p>`;
    case "positivacao":
      return `<p>A positivação do painel conta os clientes com nota do vendedor no mês, do dia 1º até o fim do período. ${carteira}
        Fica na lista quem não comprou com o próprio vendedor nesses dias (venda faturada e não cancelada). Quem comprou com outro vendedor aparece com o nome dele.</p>
        <p>O número do painel pode ser um pouco diferente: ele conta todos os clientes para quem o vendedor vendeu, estejam ou não na carteira dele hoje.
        <b>Última compra:</b> com qualquer vendedor.</p>${potencial}`;
    case "atendimentos":
      return `<p>A mesma conta da linha Atendimentos: os clientes esperados na rota do período sem pedido de venda no dia da rota.
        O semanal é esperado toda semana; o quinzenal, se não comprou nos 7 dias antes; o mensal, se não comprou nos 21 dias antes.
        Na área com mais de um dia, o cliente é esperado uma vez por semana, no último dia marcado. Os dias de atendimento das áreas ficam em Gestão › Configurar.</p>
        <p>Quem fez pedido na mesma semana em outro dia aparece com a data: esse pedido não conta como atendimento, porque não foi no dia da rota.
        <b>Último pedido:</b> com qualquer vendedor.</p>${potencial}`;
    case "mussarela":
      return `<p>Entram os clientes da carteira de hoje que compraram com o próprio vendedor no período e os esperados na rota do período,
        mesmo sem compra (esses aparecem marcados). Fica na lista quem é de um segmento com “Qualquer mussarela” no <b>mix ideal</b> (${onde})
        e não levou mussarela no período, com qualquer vendedor.</p>
        <p>Mussarela é o grupo mussarela da página Metas, o mesmo da linha Mussarela do painel. O que o cliente levou sai das notas, como a
        linha do painel: quem fez pedido no período, mas ainda não tem nota, aparece marcado.</p>${potencial}`;
    default:  // outras
      return `<p>Os mesmos clientes da lista Mussarela: os da carteira de hoje que compraram com o próprio vendedor no período e os esperados na rota,
        mesmo sem compra (esses aparecem marcados). O que eles levaram (com qualquer vendedor) é comparado com o <b>mix ideal do segmento</b> sem o item
        da mussarela (${onde}). Um item com vários produtos vale com qualquer um deles.</p>
        <p>Fica na lista quem deixou de levar pelo menos um item. Uma devolução não tira o item. O que o cliente levou sai das notas,
        como a linha do painel: quem fez pedido no período, mas ainda não tem nota, aparece marcado.</p>${potencial}`;
  }
}

function seletorVendedor(d) {
  if (!doPainel() || !(d.equipe || []).length) return "";
  return `<label class="campo mc-vendedor"><span class="ic-campo">${icone("usuario")}</span>
    <select id="mc-vendedor" aria-label="Vendedor da lista">
      <option value=""${d.vendedor == null ? " selected" : ""}>Toda a equipe ${esc(d.regiao)}</option>
      ${d.equipe.map((v) => `<option value="${v.id}"${v.id === d.vendedor ? " selected" : ""}>${esc(v.nome)}</option>`).join("")}
    </select></label>`;
}

function desenhar() {
  const d = estado.dados, L = LISTAS[estado.tipo];
  const ref = doPainel() ? (d.copia ? `dados da cópia de ${fmt.dataCurta(d.copia.slice(0, 10))} às ${d.copia.slice(11, 16)}` : "")
    : d.data_ref ? `vendas até ${fmt.data(d.data_ref)}` : "";
  const sub = `${periodo(d)} · ${quem(d)}${ref ? ` · ${ref}` : ""}`;
  dlg.innerHTML = `<div class="mc-corpo">
    ${cabecalho(L.titulo, sub)}
    ${(d.avisos || []).map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("")}
    ${resumo(d)}
    <details class="mc-como"><summary>${icone("info")}Como é calculado</summary>${como(d)}</details>
    <div class="mc-ferramentas">
      <div class="mc-filtros">${seletorVendedor(d)}
        <label class="campo sem-seta mc-busca"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="mc-busca" placeholder="${esc(L.busca)}" autocomplete="off" spellcheck="false" aria-label="${esc(L.busca)}"></label></div>
      <span class="mc-contagem" id="mc-contagem"></span>
    </div>
    <div id="mc-tabela" class="mc-area"></div>
  </div>`;
  desenharTabela();
}

function filtrados() {
  const d = estado.dados, termo = semAcento(estado.busca.trim()), txt = LISTAS[estado.tipo].texto;
  return termo ? d.itens.filter((c) => semAcento(txt(c)).includes(termo)) : d.itens;
}

function ordenar(lista, cols) {
  return ordenarPorNiveis(lista, estado.ordens, (campo, a, b) => {
    const col = cols.find((c) => c.id === campo);
    if (!col) return 0;
    const va = col.valor(a), vb = col.valor(b);
    return typeof va === "string" ? va.localeCompare(vb, "pt-BR") : va - vb;
  }, (a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

function linha(c, cols) {
  return `<tr class="mc-linha">${cols.map((col) => col.cel(c)).join("")}</tr>`;
}

function vazio(d) {
  const r = d.resumo;
  if (!d.vendedores.length) return "Nenhum vendedor da equipe no seu acesso.";
  switch (estado.tipo) {
    case "nao_atendidos": return "Todos os clientes da carteira compraram com o vendedor no período.";
    case "positivacao": return "Todos os clientes da carteira compraram com o vendedor no mês.";
    case "atendimentos": return r.esperados ? "Todos os clientes esperados foram atendidos no dia da rota." : "Nenhum cliente esperado na rota do período.";
    case "mussarela": return r.base ? "Todos os clientes do período levaram mussarela (ou são de segmento sem mussarela no mix)." : "Nenhum cliente comprou com o vendedor nem era esperado na rota do período.";
    case "outras": return r.base ? "Todos os clientes do período levaram o mix ideal do segmento (ou estão em segmento sem mix)." : "Nenhum cliente comprou com o vendedor nem era esperado na rota do período.";
    default: return r.atendidos ? "Todos os clientes atendidos levaram o mix ideal do segmento (ou estão em segmento sem mix)."
      : "Nenhum cliente da carteira comprou com o vendedor no período.";
  }
}

function desenharTabela() {
  const d = estado.dados, area = document.getElementById("mc-tabela");
  if (!d || !area) return;
  const cols = colunas(d);
  const lista = ordenar(filtrados(), cols);
  listaAtual = lista;
  desenhadas = Math.min(lista.length, LOTE);
  const total = d.itens.length;
  document.getElementById("mc-contagem").textContent = lista.length === total
    ? plural(total, "cliente", "clientes") : `${fmt.num(lista.length)} de ${plural(total, "cliente", "clientes")}`;
  if (!total) {
    area.innerHTML = `<div class="vazio">${icone("certo")}<p>${vazio(d)}</p></div>`;
    return;
  }
  if (!lista.length) {
    area.innerHTML = `<div class="vazio">${icone("busca")}<p>Nenhum cliente com esta busca.</p></div>`;
    return;
  }
  const th = (c) => {
    const m = marcaOrdem(estado.ordens, c.id);
    return `<th class="${c.tipo === "numero" ? "" : "esq"}"${m.aria}${c.dica ? ` title="${esc(c.dica)}"` : ""}>
      <button type="button" class="crm-ordem${m.classe}" data-ordem="${c.id}">${esc(c.rotulo)}<span class="crm-seta-o" aria-hidden="true">${m.seta}</span></button></th>`;
  };
  area.innerHTML = `${linhaOrdem(estado.ordens, LISTAS[estado.tipo].padrao, (id) => cols.find((c) => c.id === id) || null)}
    <div class="tabela-rolagem mc-rolagem"><table class="dados mc-tabela">
      <thead><tr>${cols.map(th).join("")}</tr></thead>
      <tbody>${lista.slice(0, desenhadas).map((c) => linha(c, cols)).join("")}</tbody></table></div>
    <p class="mc-mais" hidden></p>`;
  avisoMais();
  vigiar(cols);
}

function avisoMais() {
  const p = dlg.querySelector(".mc-mais");
  if (!p) return;
  p.hidden = desenhadas >= listaAtual.length;
  p.textContent = p.hidden ? "" : `Mostrando ${fmt.num(desenhadas)} de ${plural(listaAtual.length, "cliente", "clientes")} · role para ver os próximos`;
}

// As próximas linhas entram quando qualquer uma das últimas FOLGA aparece (rolando aos poucos ou pulando para o fim).
function vigiar(cols) {
  vigia?.disconnect();
  vigia = null;
  const tbody = dlg.querySelector("table.mc-tabela > tbody");
  if (!tbody || desenhadas >= listaAtual.length) return;
  vigia = new IntersectionObserver((entradas) => { if (entradas.some((e) => e.isIntersecting)) maisLinhas(cols); });
  let tr = tbody.lastElementChild;
  for (let n = 0; tr && n < FOLGA; tr = tr.previousElementSibling, n += 1) vigia.observe(tr);
}

function maisLinhas(cols) {
  const tbody = dlg.querySelector("table.mc-tabela > tbody");
  if (!tbody || desenhadas >= listaAtual.length) return;
  const de = desenhadas;
  desenhadas = Math.min(listaAtual.length, de + LOTE);
  tbody.insertAdjacentHTML("beforeend", listaAtual.slice(de, desenhadas).map((c) => linha(c, cols)).join(""));
  avisoMais();
  vigiar(cols);
}
