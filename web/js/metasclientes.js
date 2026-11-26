// As janelas dos cards das abas Metas ES, Metas BA e Metas Edir (bi/metas_clientes.py), sobre a página e com o fundo
// escuro: os clientes da carteira que o vendedor não atendeu ("Clientes atendidos") e os que compraram, mas deixaram de
// levar algum item do mix ideal do segmento ("Composição do faturamento"; o mix fica em CRM › Configurar › Mix ideal).
// Abrem com a aba, os meses e os vendedores da página. A tabela entra em lotes de 100 linhas, sem a animação das linhas
// (centenas de linhas animando travam o navegador), e ordena em até 3 níveis, como no CRM.
import { api, esc, fmt, icone, clicarOrdem, ordenarPorNiveis, marcaOrdem, linhaOrdem } from "./util.js";

const LOTE = 100, FOLGA = 25;
const semAcento = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;

let dlg = null, apertouFora = false;
const estado = { tipo: null, dados: null, busca: "", ordens: [], pedido: 0, admin: false };
let listaAtual = [], desenhadas = 0, vigia = null;

const LISTAS = {
  nao_atendidos: {
    titulo: "Clientes não atendidos", icone: "pessoas", busca: "Buscar cliente, cidade ou área",
    padrao: [{ campo: "media", desc: true }],
    texto: (c) => `${c.nome} ${c.cidade || ""} ${c.area || ""} ${c.segmento || ""} ${c.vendedor.nome} ${c.outros.join(" ")}`,
  },
  mix: {
    titulo: "Clientes que não compraram produtos indicados", icone: "queijo", busca: "Buscar cliente ou produto",
    padrao: [{ campo: "faltou", desc: true }, { campo: "comprado", desc: true }],
    texto: (c) => `${c.nome} ${c.cidade || ""} ${c.segmento || ""} ${c.vendedor.nome} ${c.faltou.join(" ")}`,
  },
};

const variosVendedores = (d) => d.vendedores.length > 1;
const variosMeses = (d) => d.periodo.meses.length > 1;

function cidade(c) { return c.cidade ? `${c.cidade}${c.uf ? `/${c.uf}` : ""}` : "—"; }

function celCliente(c) {
  const outro = c.outros?.length ? `<span class="mc-outro">${icone("usuario")}comprou com ${esc(c.outros.join(", "))}</span>` : "";
  return `<td class="esq mc-cliente"><b>${esc(c.nome)}</b>${outro}</td>`;
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

// As colunas de cada lista. valor: para ordenar (texto ou número); cel: a célula.
function colunas(d) {
  const vend = variosVendedores(d);
  if (estado.tipo === "nao_atendidos") {
    return [
      { id: "cliente", rotulo: "Cliente", tipo: "texto", valor: (c) => c.nome, cel: celCliente },
      vend && { id: "vendedor", rotulo: "Vendedor", tipo: "texto", valor: (c) => c.vendedor.nome, cel: (c) => `<td class="esq">${esc(c.vendedor.nome)}</td>` },
      { id: "area", rotulo: "Área", tipo: "texto", valor: (c) => c.area || "", cel: (c) => `<td class="esq">${esc(c.area || "—")}</td>` },
      { id: "cidade", rotulo: "Cidade", tipo: "texto", valor: (c) => c.cidade || "", cel: (c) => `<td class="esq">${esc(cidade(c))}</td>` },
      { id: "segmento", rotulo: "Segmento", tipo: "texto", valor: (c) => c.segmento || "", cel: (c) => `<td class="esq">${esc(c.segmento || "—")}</td>` },
      { id: "ultima", rotulo: "Última compra", tipo: "data", valor: (c) => c.ultima || "", cel: celUltima,
        dica: "A última compra do cliente, com qualquer vendedor" },
      { id: "media", rotulo: "Compra média por mês", tipo: "numero", valor: (c) => c.media, cel: (c) => `<td>${fmt.moeda(c.media)}</td>`,
        dica: `As compras de ${d.media.de} a ${d.media.ate}, com qualquer vendedor, divididas por ${d.media.meses}` },
      variosMeses(d) && { id: "meses_sem", rotulo: "Meses sem compra", tipo: "numero", valor: (c) => c.meses_sem.length,
        cel: (c) => `<td class="esq">${esc(c.meses_sem.join(", "))}</td>`, dica: "Os meses do período em que o cliente não comprou com o vendedor" },
    ].filter(Boolean);
  }
  return [
    { id: "cliente", rotulo: "Cliente", tipo: "texto", valor: (c) => c.nome, cel: celCliente },
    vend && { id: "vendedor", rotulo: "Vendedor", tipo: "texto", valor: (c) => c.vendedor.nome, cel: (c) => `<td class="esq">${esc(c.vendedor.nome)}</td>` },
    { id: "segmento", rotulo: "Segmento", tipo: "texto", valor: (c) => c.segmento || "", cel: (c) => `<td class="esq mc-seg">${esc(c.segmento || "—")}</td>` },
    { id: "comprado", rotulo: "Comprado no período", tipo: "numero", valor: (c) => c.comprado, cel: (c) => `<td>${fmt.moeda(c.comprado)}</td>`,
      dica: "O que o cliente comprou no período, com qualquer vendedor" },
    { id: "mix", rotulo: "Mix levado", tipo: "numero", valor: (c) => (c.itens ? c.levados / c.itens : 0), cel: celMix,
      dica: "Quantos itens do mix ideal do segmento o cliente levou no período" },
    { id: "faltou", rotulo: "Faltou", tipo: "numero", valor: (c) => c.faltou.length, cel: celFaltou,
      sentidos: ["menos itens primeiro", "mais itens primeiro"], dica: "Os itens do mix ideal que o cliente não levou: é o que dá para oferecer" },
  ].filter(Boolean);
}

// ---------- abrir e fechar ----------
export async function abrirListaClientes({ tipo, visao, meses, vendedores, admin }) {
  criar();
  Object.assign(estado, { tipo, dados: null, busca: "", ordens: LISTAS[tipo].padrao.map((n) => ({ ...n })), admin });
  const pedido = ++estado.pedido;
  const L = LISTAS[tipo];
  dlg.setAttribute("aria-label", L.titulo);
  dlg.innerHTML = `<div class="mc-corpo">${cabecalho(L.titulo, "Carregando a lista…")}
    <div class="esqueleto" style="height:90px;margin-top:16px"></div><div class="esqueleto" style="height:260px;margin-top:12px"></div></div>`;
  if (!dlg.open) dlg.showModal();
  try {
    const p = new URLSearchParams({ lista: tipo, visao, meses: meses.join(",") });
    if (vendedores.length) p.set("vendedores", vendedores.join(","));
    const d = await api(`/api/metas/clientes?${p}`);
    if (pedido !== estado.pedido || !dlg.open) return;
    estado.dados = d;
    desenhar();
  } catch (e) {
    if (pedido !== estado.pedido || !dlg.open) return;
    dlg.innerHTML = `<div class="mc-corpo">${cabecalho(L.titulo, "")}
      <div class="vazio">${icone("alerta")}<p>Não foi possível carregar a lista: ${esc(e.message)}</p></div></div>`;
  }
}

export function fecharListaClientes() {
  if (dlg?.open) dlg.close();
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
  if (campo) {
    const col = colunas(estado.dados).find((c) => c.id === campo);
    const ids = new Set(colunas(estado.dados).map((c) => c.id));
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
  return plural(d.vendedores.length, "vendedor", "vendedores");
}

function resumo(d) {
  const r = d.resumo;
  if (estado.tipo === "nao_atendidos") {
    const varios = variosMeses(d);
    return `<div class="mc-resumo">
      ${stat("Carteira de hoje", r.carteira, "clientes ativos")}
      ${stat(varios ? "Compraram em todos os meses" : "Compraram com o vendedor", r.atendidos)}
      ${stat(varios ? "Ficaram algum mês sem comprar" : "Não compraram", r.nao_atendidos,
        r.com_outro ? `${plural(r.com_outro, "comprou", "compraram")} com outro vendedor` : "", true)}
    </div>`;
  }
  const fora = [];
  if (r.sem_mix) fora.push(`${plural(r.sem_mix, "cliente", "clientes")} de segmento sem mix ideal (${esc(r.segmentos_sem_mix.join(", "))})`);
  if (r.sem_segmento) fora.push(`${plural(r.sem_segmento, "cliente", "clientes")} sem segmento no cadastro`);
  return `<div class="mc-resumo">
      ${stat("Compraram com o vendedor", r.atendidos, "da carteira de hoje")}
      ${stat("Levaram todo o mix", r.completos)}
      ${stat("Deixaram de levar algum item", r.com_falta, "", true)}
    </div>
    ${fora.length ? `<p class="mc-nota">${icone("info")}<span>Ficam fora da lista: ${fora.join(" e ")}.</span></p>` : ""}`;
}

function como(d) {
  if (estado.tipo === "nao_atendidos") {
    return `<p>A lista parte da <b>carteira de hoje</b> de cada vendedor: os clientes ativos no ERP, sem “PEDIDO BLOQUEADO” no nome.
      Fica na lista quem não comprou com o próprio vendedor ${variosMeses(d) ? "em pelo menos um dos meses" : "no mês"} (venda faturada e não cancelada),
      a mesma regra do card, que conta o cliente para quem fez a venda. Quem comprou com outro vendedor aparece com o nome dele.</p>
      <p>O número do card pode ser um pouco diferente: ele conta todos os clientes para quem o vendedor vendeu, estejam ou não na carteira dele hoje.</p>
      <p><b>Compra média por mês:</b> o que o cliente comprou de ${esc(d.media.de)} a ${esc(d.media.ate)}, com qualquer vendedor, dividido por ${d.media.meses}.
      <b>Última compra:</b> com qualquer vendedor.</p>`;
  }
  const onde = estado.admin ? `<a href="#/config-crm?secao=mix">CRM › Configurar › Mix ideal</a>` : "CRM › Configurar › Mix ideal";
  return `<p>Entram os clientes da carteira de hoje que compraram com o próprio vendedor no período.
      O que eles levaram (com qualquer vendedor) é comparado com o <b>mix ideal do segmento</b>, em ${onde}.
      Um item com vários produtos vale com qualquer um deles, e “Qualquer mussarela” vale com qualquer produto da linha mussarela.</p>
      <p>Fica na lista quem deixou de levar pelo menos um item. Uma devolução não tira o item.
      ${d.resumo.nao_atendidos ? `Os ${plural(d.resumo.nao_atendidos, "cliente", "clientes")} da carteira que não compraram com o vendedor estão em “Clientes não atendidos”.` : ""}</p>`;
}

function desenhar() {
  const d = estado.dados, L = LISTAS[estado.tipo];
  const sub = `${esc(d.periodo.rotulo)} · ${quem(d)}${d.data_ref ? ` · vendas até ${fmt.data(d.data_ref)}` : ""}`;
  dlg.innerHTML = `<div class="mc-corpo">
    ${cabecalho(L.titulo, sub)}
    ${(d.avisos || []).map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("")}
    ${resumo(d)}
    <details class="mc-como"><summary>${icone("info")}Como é calculado</summary>${como(d)}</details>
    <div class="mc-ferramentas">
      <label class="campo sem-seta mc-busca"><span class="ic-campo">${icone("busca")}</span>
        <input type="search" id="mc-busca" placeholder="${esc(L.busca)}" autocomplete="off" spellcheck="false" aria-label="${esc(L.busca)}"></label>
      <span class="mc-contagem" id="mc-contagem"></span>
    </div>
    <div id="mc-tabela" class="mc-area"></div>
  </div>`;
  desenharTabela();
}

function filtrados() {
  const d = estado.dados, termo = semAcento(estado.busca.trim()), texto = LISTAS[estado.tipo].texto;
  return termo ? d.itens.filter((c) => semAcento(texto(c)).includes(termo)) : d.itens;
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
    const msg = estado.tipo === "nao_atendidos" ? "Todos os clientes da carteira compraram com o vendedor no período."
      : d.resumo.atendidos ? "Todos os clientes atendidos levaram o mix ideal do segmento (ou estão em segmento sem mix)."
        : "Nenhum cliente da carteira comprou com o vendedor no período.";
    area.innerHTML = `<div class="vazio">${icone("certo")}<p>${msg}</p></div>`;
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
