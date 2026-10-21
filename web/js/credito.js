// Página Reavaliação de Crédito: a página "Reavaliação Credito" do Power BI. Compras, pontualidade e inadimplência
// pelos títulos a receber de venda (mês e ano pela emissão, vendedor do título); limite, prazo e restante de um ou
// mais clientes (os limites somam), com as parcelas já pagas dos boletos divididos. A conta e a ordem da tabela
// ficam no servidor (bi/credito.py); aqui é a apresentação.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast, MESES } from "./util.js";
import { anel } from "./graficos.js";
import { ligarTelaCheia, sairTelaCheia } from "./telacheia.js";

const SITUACAO = {
  a_vencer: { rotulo: "A vencer", classe: "sem_meta", icone: "calendario" },
  vencido: { rotulo: "Vencido", classe: "atencao", icone: "calendario" },
  inadimplente: { rotulo: "Inadimplente", classe: "abaixo", icone: "alerta" },
  quitado: { rotulo: "Quitado", classe: "no_ritmo", icone: "certo" },
  quitado_atraso: { rotulo: "Quitado com atraso", classe: "atencao", icone: "alerta" },
};
// Colunas da tabela (chave = a coluna de ordenar no servidor) e o sentido do primeiro clique.
const COLUNAS = [
  { chave: "emissao", rotulo: "Emissão", sentido: "desc" },
  { chave: "titulo", rotulo: "Título", sentido: "desc" },
  { chave: "cliente", rotulo: "Cliente", sentido: "asc", esq: true, soVarios: true },
  { chave: "vendedor", rotulo: "Vendedor", sentido: "asc", esq: true },
  { chave: "vencimento", rotulo: "Vencimento", sentido: "desc" },
  { chave: "quitacao", rotulo: "Quitação", sentido: "desc" },
  { chave: "valor", rotulo: "Valor", sentido: "desc" },
  { chave: "pago", rotulo: "Valor já pago", sentido: "desc" },
  { chave: "dias", rotulo: "Atraso", dica: "dias de atraso", sentido: "desc" },
  { chave: "situacao", rotulo: "Situação", sentido: "desc", esq: true },
];
const ORDEM_PADRAO = { coluna: "emissao", sentido: "desc" };
const maiuscula = (t) => t.charAt(0).toUpperCase() + t.slice(1);

let ctx = null;
const estado = { clientes: [], mes: null, ano: null, vendedor: null, ordem: null, dados: null, pedido: 0, busca: 0 };

export function montarCredito(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const num = (t) => (t && Number.isInteger(Number(t)) && Number(t) > 0 ? Number(t) : null);
  const ordem = (t) => {
    const [coluna, sentido] = String(t || "").split("-");
    return COLUNAS.some((c) => c.chave === coluna) && ["asc", "desc"].includes(sentido) ? { coluna, sentido } : null;
  };
  if (["c", "m", "a", "v", "o"].some((k) => q.has(k))) {
    Object.assign(estado, {
      clientes: (q.get("c") || "").split(",").map(num).filter(Boolean).map((id) => ({ id, nome: "" })),
      mes: num(q.get("m")), ano: num(q.get("a")), vendedor: num(q.get("v")), ordem: ordem(q.get("o")),
    });
  } else if (!estado.dados) {
    const s = ler("mv-credito", {});
    Object.assign(estado, { clientes: Array.isArray(s.c) ? s.c.filter((c) => num(c?.id)) : [], mes: num(s.m),
      ano: num(s.a), vendedor: num(s.v), ordem: ordem(s.o) });
  }
  estado.dados = null;

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("cartao")}</span>
        <div><b>Reavaliação de crédito</b><small>títulos a receber de venda, sem os cancelados</small></div></div>
      <div class="filtros">
        <div class="cr-busca" id="cr-busca">
          <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
            <input type="search" id="cr-cliente" placeholder="Cliente: nome ou código" autocomplete="off" spellcheck="false"
              role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="cr-sugestoes" aria-label="Adicionar cliente"></label>
          <div class="multi-painel cr-sugestoes" id="cr-sugestoes" role="listbox" aria-multiselectable="true" aria-label="Clientes encontrados" hidden></div>
        </div>
        <label class="campo"><span class="ic-campo">${icone("calendario")}</span><select id="cr-mes" aria-label="Mês de emissão">
          <option value="">Todos os meses</option>${MESES.map((m, i) => `<option value="${i + 1}">${maiuscula(m)}</option>`).join("")}</select></label>
        <label class="campo"><span class="ic-campo">${icone("calendario")}</span><select id="cr-ano" aria-label="Ano de emissão">
          <option value="">Todos os anos</option></select></label>
        <label class="campo"><span class="ic-campo">${icone("usuario")}</span><select id="cr-vendedor" aria-label="Vendedor do título">
          <option value="">Todos os vendedores</option></select></label>
        <button class="btn btn-limpar" type="button" id="cr-limpar" hidden>${icone("x")}Limpar filtros</button>
      </div>
      <div class="cr-escolhidos" id="cr-escolhidos" aria-label="Clientes escolhidos" hidden></div>
    </div>
    <div id="cr-avisos"></div>
    <div id="cr-conteudo"><div class="grade secao">
      <div class="kpis n3"><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div></div>
      <div class="kpis n4"><div class="esqueleto" style="height:190px"></div><div class="esqueleto" style="height:190px"></div><div class="esqueleto" style="height:190px"></div><div class="esqueleto" style="height:190px"></div></div>
      <div class="esqueleto" style="height:360px"></div></div>
    </div>`;

  ligarBusca(container);
  desenharEscolhidos();
  const sel = (id, chave) => container.querySelector(id).addEventListener("change", (e) => {
    estado[chave] = e.target.value ? Number(e.target.value) : null;
    carregar();
  });
  sel("#cr-mes", "mes");
  sel("#cr-ano", "ano");
  sel("#cr-vendedor", "vendedor");
  container.querySelector("#cr-limpar").addEventListener("click", () => {
    Object.assign(estado, { clientes: [], mes: null, ano: null, vendedor: null });
    container.querySelector("#cr-cliente").value = "";
    desenharEscolhidos();
    carregar();
  });
  container.querySelector("#cr-escolhidos").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tirar]");
    if (b) tirarCliente(Number(b.dataset.tirar));
  });
  // Ordenar a tabela: o servidor ordena o filtro inteiro (sem cliente, a tabela mostra só uma parte dos títulos).
  container.querySelector("#cr-conteudo").addEventListener("click", (e) => {
    const b = e.target.closest("[data-ordem]");
    if (!b) return;
    const atual = estado.ordem || ORDEM_PADRAO, col = COLUNAS.find((c) => c.chave === b.dataset.ordem);
    estado.ordem = atual.coluna === col.chave
      ? { coluna: col.chave, sentido: atual.sentido === "asc" ? "desc" : "asc" }
      : { coluna: col.chave, sentido: col.sentido };
    carregar(false, true);
  });
  carregar();
}

export function recarregarCredito() { if (ctx) carregar(true); }

function atualizarUrl() {
  const o = estado.ordem;
  guardar("mv-credito", { c: estado.clientes, m: estado.mes, a: estado.ano, v: estado.vendedor, o: o ? `${o.coluna}-${o.sentido}` : null });
  if (!location.hash.startsWith("#/credito")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams();
  if (estado.clientes.length) p.set("c", estado.clientes.map((c) => c.id).join(","));
  if (estado.mes) p.set("m", estado.mes);
  if (estado.ano) p.set("a", estado.ano);
  if (estado.vendedor) p.set("v", estado.vendedor);
  if (o) p.set("o", `${o.coluna}-${o.sentido}`);
  history.replaceState(null, "", `#/credito${p.toString() ? "?" + p : ""}`);
  const limpar = document.getElementById("cr-limpar");
  if (limpar) limpar.hidden = !estado.clientes.length && !estado.mes && !estado.ano && !estado.vendedor;
}

// soTabela: só a ordem mudou; troca a tabela sem refazer (e reanimar) o resto da página.
async function carregar(silencioso = false, soTabela = false) {
  const conteudo = document.getElementById("cr-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  sairTelaCheia();
  const alvo = (soTabela && document.getElementById("cr-tabela")) || conteudo;
  if (estado.dados) alvo.classList.add("recarregando");
  atualizarUrl();
  try {
    const p = new URLSearchParams();
    if (estado.clientes.length) p.set("clientes", estado.clientes.map((c) => c.id).join(","));
    if (estado.mes) p.set("mes", estado.mes);
    if (estado.ano) p.set("ano", estado.ano);
    if (estado.vendedor) p.set("vendedor", estado.vendedor);
    if (estado.ordem) { p.set("ordem", estado.ordem.coluna); p.set("sentido", estado.ordem.sentido); }
    const d = await api(`/api/credito?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    // só completa os nomes (do link ou do navegador): a lista pode ter mudado enquanto a resposta vinha
    const nomes = new Map(d.clientes.map((c) => [c.id, c.nome]));
    estado.clientes = estado.clientes.map((c) => ({ ...c, nome: nomes.get(c.id) || c.nome }));
    atualizarUrl();
    desenharEscolhidos();
    preencherFiltros(d);
    ctx.subtitulo(d);
    document.getElementById("cr-avisos").innerHTML = (d.avisos || [])
      .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
    if (alvo !== conteudo) {
      alvo.outerHTML = tabela(d, 0, false);
      posRender(document.getElementById("cr-tabela"));
      return;
    }
    conteudo.innerHTML = render(d);
    posRender(conteudo);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 400 && (estado.clientes.length || estado.ano || estado.vendedor || estado.ordem)) {
      // filtro guardado neste navegador que não vale mais (cliente apagado, ano fora dos dados): volta a todos
      Object.assign(estado, { clientes: [], ano: null, vendedor: null, ordem: null });
      desenharEscolhidos();
      toast(e.message, "erro");
      return carregar(silencioso);
    }
    const ic = e.status === 403 ? "cadeado" : "alerta";
    const msg = e.status === 403 || e.status === 503 ? esc(e.message) : `Não foi possível carregar: ${esc(e.message)}`;
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone(ic)}<p>${msg}</p></div>`;
    if (!silencioso && e.status !== 403 && e.status !== 503) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) alvo.classList?.remove("recarregando");
  }
}

function preencherFiltros(d) {
  const opcoes = (el, lista, todos, valor) => {
    el.innerHTML = `<option value="">${todos}</option>` + lista.map((o) => `<option value="${o.id}">${esc(o.nome)}</option>`).join("");
    el.value = valor ? String(valor) : "";
  };
  opcoes(document.getElementById("cr-ano"), d.opcoes.anos.map((a) => ({ id: a, nome: a })), "Todos os anos", d.filtros.ano);
  opcoes(document.getElementById("cr-vendedor"), d.opcoes.vendedores, "Todos os vendedores", d.filtros.vendedor);
  document.getElementById("cr-mes").value = d.filtros.mes ? String(d.filtros.mes) : "";
}

// ---------- clientes escolhidos ----------
function desenharEscolhidos() {
  const el = document.getElementById("cr-escolhidos");
  if (!el) return;
  el.hidden = !estado.clientes.length;
  el.innerHTML = estado.clientes.map((c) => `
    <span class="cr-chip"><span>${esc(c.nome || `Cliente ${c.id}`)}</span>
      <button type="button" data-tirar="${c.id}" aria-label="Tirar ${esc(c.nome || `o cliente ${c.id}`)}" title="Tirar da seleção">${icone("x")}</button></span>`).join("")
    + (estado.clientes.length > 1 ? `<span class="cr-chip-soma">${estado.clientes.length} clientes · os limites somam</span>` : "");
  const campo = document.getElementById("cr-cliente");
  campo.placeholder = estado.clientes.length ? "Adicionar outro cliente" : "Cliente: nome ou código";
}

let esperaCarregar = null;
function mudouClientes() {
  desenharEscolhidos();
  clearTimeout(esperaCarregar); // marcando vários seguidos na lista, carrega uma vez só
  esperaCarregar = setTimeout(() => carregar(), 350);
}

function tirarCliente(id) {
  estado.clientes = estado.clientes.filter((c) => c.id !== id);
  mudouClientes();
}

// ---------- busca de cliente (no servidor: são milhares) ----------
function ligarBusca(container) {
  const campo = container.querySelector("#cr-cliente");
  const lista = container.querySelector("#cr-sugestoes");
  let achados = [], ativo = -1, espera = null;
  const escolhido = (id) => estado.clientes.some((c) => c.id === id);

  const fechar = () => { lista.hidden = true; campo.setAttribute("aria-expanded", "false"); ativo = -1; };
  const desenhar = (texto) => {
    if (!achados.length) {
      lista.innerHTML = `<p class="multi-vazio">${texto ? "Nenhum cliente com esse nome ou código." : "Digite o nome ou o código do cliente."}</p>`;
    } else {
      lista.innerHTML = achados.map((c, i) => `
        <button type="button" class="multi-op cr-op${i === ativo ? " ativo" : ""}" role="option" aria-selected="${escolhido(c.id)}" data-i="${i}">
          <span class="cr-marca${escolhido(c.id) ? " sim" : ""}">${icone("visto")}</span>
          <span class="n">${esc(c.nome)}<small>código ${c.id}${c.carteira ? ` · carteira ${esc(c.carteira)}` : ""} · ${c.titulos ? `${fmt.num(c.titulos)} títulos` : "sem títulos"}</small></span>
        </button>`).join("");
    }
    lista.hidden = false;
    campo.setAttribute("aria-expanded", "true");
  };
  // Marca ou desmarca e deixa a lista aberta, para escolher outro da mesma busca (ex.: as lojas de uma rede).
  const alternar = (c) => {
    if (escolhido(c.id)) tirarCliente(c.id);
    else {
      estado.clientes = [...estado.clientes, { id: c.id, nome: c.nome }];
      mudouClientes();
    }
    desenhar(campo.value.trim());
  };
  const buscar = async () => {
    const texto = campo.value.trim();
    const pedido = ++estado.busca;
    if (!texto) { achados = []; desenhar(""); return; }
    try {
      const r = await api(`/api/credito/busca?texto=${encodeURIComponent(texto)}`);
      if (pedido !== estado.busca) return;
      achados = r.clientes;
      ativo = achados.length ? 0 : -1;
      desenhar(texto);
    } catch (e) {
      if (pedido === estado.busca) { fechar(); toast(e.message, "erro"); }
    }
  };

  campo.addEventListener("input", () => {
    clearTimeout(espera);
    espera = setTimeout(buscar, 220);
  });
  campo.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!achados.length) return;
      e.preventDefault();
      ativo = (ativo + (e.key === "ArrowDown" ? 1 : -1) + achados.length) % achados.length;
      desenhar(campo.value.trim());
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!lista.hidden && achados[ativo]) alternar(achados[ativo]);
    } else if (e.key === "Escape") {
      fechar();
      campo.value = "";
    } else if (e.key === "Backspace" && !campo.value && estado.clientes.length) {
      tirarCliente(estado.clientes[estado.clientes.length - 1].id); // apagar com o campo vazio tira o último
    }
  });
  lista.addEventListener("mousedown", (e) => e.preventDefault()); // não tira o foco do campo antes do clique
  lista.addEventListener("click", (e) => {
    const b = e.target.closest("[data-i]");
    if (b) { ativo = Number(b.dataset.i); alternar(achados[ativo]); }
  });
  campo.addEventListener("blur", () => { fechar(); campo.value = ""; achados = []; });
}

// ---------- apoio ----------
function descricaoPeriodo(f) {
  if (!f.mes && !f.ano) return "todo o histórico";
  if (f.mes && f.ano) return `${MESES[f.mes - 1]} de ${f.ano}`;
  return f.mes ? `${MESES[f.mes - 1]} de todos os anos` : `${f.ano}`;
}

function descricaoFiltro(d) {
  const v = d.filtros.vendedor && d.opcoes.vendedores.find((o) => o.id === d.filtros.vendedor);
  return `emissão em ${descricaoPeriodo(d.filtros)}${v ? ` · vendido por ${v.nome}` : ""}`;
}

function nomeClientes(d) {
  if (!d.clientes.length) return "Todos os clientes";
  return d.clientes.length === 1 ? d.clientes[0].nome : `${d.clientes.length} clientes`;
}

export function textoSubtitulo(d) {
  return `${nomeClientes(d)} · ${maiuscula(descricaoPeriodo(d.filtros))}`;
}

const cab = (titulo, ic) =>
  `<div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${esc(titulo)}</span>`;

function kpiValor(i, cor, titulo, ic, valor, formato, meta, rodape = []) {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab(titulo, ic)}</div>
    <div class="kpi-corpo"><div>
      ${valor == null ? `<div class="kpi-valor kpi-na">—</div>` : `<div class="kpi-valor" data-contar="${valor}" data-fmt="${formato}">0</div>`}
      <div class="kpi-meta">${meta}</div>
    </div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function kpiSemCliente(i, cor, titulo, ic) {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab(titulo, ic)}</div>
    <div class="kpi-corpo"><div><div class="kpi-valor kpi-na">Escolha um cliente</div>
      <div class="kpi-meta">O limite e o prazo são do cadastro de cada cliente.</div></div></div>
  </article>`;
}

// Prazo ou vendedor da carteira de vários clientes: o mesmo para todos, ou quantos diferentes.
const umOuVarios = (lista, varios) => (lista.length === 1 ? esc(lista[0]) : `${lista.length} ${varios}`);

// ---------- estrutura ----------
function render(d) {
  const k = d.cartoes, cr = d.credito, n = d.clientes.length;
  const periodo = descricaoFiltro(d);
  let h = n ? cabecalhoClientes(d) : "";
  h += `<section class="kpis secao n3">
    ${kpiValor(1, "var(--s-fat)", "Valor total das compras", "moeda", k.valor, "moeda", periodo)}
    ${kpiValor(2, "var(--s-out)", "Quantidade de compras", "recibo", k.quantidade, "num", "títulos a receber de venda")}
    ${kpiValor(3, "var(--k-vm)", "Ticket médio", "etiqueta", k.ticket, "moeda", "valor ÷ quantidade de compras")}
  </section>`;
  h += `<section class="kpis secao n4">
    ${kpiPontualidade(4, k)}
    ${cr ? kpiValor(5, "var(--k-cli)", "Limite de crédito", "cartao", cr.limite, "moeda",
      n > 1 ? `soma dos limites de ${n} clientes` : cr.limite > 0 ? "do cadastro do cliente" : "sem limite no cadastro",
      [["Prazo", umOuVarios(cr.prazos, "prazos diferentes")],
       ["Vendedor da carteira", umOuVarios(cr.carteiras, "vendedores")]])
      : kpiSemCliente(5, "var(--k-cli)", "Limite de crédito", "cartao")}
    ${kpiInadimplencia(6, k, periodo)}
    ${cr ? kpiRestante(7, cr) : kpiSemCliente(7, "var(--s-mus)", "Limite restante", "escudo")}
  </section>`;
  h += tabela(d, 8);
  h += comoCalcula(d, 9);
  return h;
}

function posRender(raiz) {
  ligarTelaCheia(raiz);
  animarContadores(raiz);
  animarEntradas(raiz);
  ligarTooltips(raiz);
}

function chipsSituacao(d) {
  const cr = d.credito, k = d.cartoes, chips = [];
  if (k.inadimplencia > 0) chips.push(`<span class="status abaixo">${icone("alerta")}Inadimplente</span>`);
  if (cr.limite > 0 && cr.restante < 0) chips.push(`<span class="status abaixo">${icone("alerta")}Passou do limite</span>`);
  if (!chips.length && cr.em_aberto === 0) chips.push(`<span class="status no_ritmo">${icone("certo")}Nada em aberto</span>`);
  return chips.join("");
}

function cabecalhoClientes(d) {
  if (d.clientes.length === 1) {
    const c = d.clientes[0];
    return `
    <section class="cartao secao entra cr-cliente" style="--i:1">
      <span class="cr-cliente-icone">${icone("loja")}</span>
      <div class="cr-cliente-nome"><b>${esc(c.nome)}</b>
        <small>código ${c.id}${c.carteira ? ` · carteira de ${esc(c.carteira)}` : ""} · prazo ${esc(c.prazo || "não informado")}</small></div>
      <div class="cr-cliente-chips">${chipsSituacao(d)}</div>
    </section>`;
  }
  const cr = d.credito;
  return `
  <section class="cartao secao entra" style="--i:1">
    <div class="cr-cliente cr-cliente-varios">
      <span class="cr-cliente-icone">${icone("loja")}</span>
      <div class="cr-cliente-nome"><b>${d.clientes.length} clientes</b><small>os limites e o que está em aberto somam</small></div>
      <div class="cr-cliente-chips">${chipsSituacao(d)}</div>
    </div>
    <div class="tabela-rolagem"><table class="dados cr-varios">
      <thead><tr><th>Cliente</th><th>Prazo</th><th>Limite</th><th>Em aberto</th><th>Restante</th></tr></thead>
      <tbody>${d.clientes.map((c) => `<tr>
        <td class="cr-nome">${esc(c.nome)}<small>código ${c.id}${c.carteira ? ` · carteira de ${esc(c.carteira)}` : ""}</small></td>
        <td>${esc(c.prazo || "—")}</td><td>${fmt.moeda2(c.limite)}</td><td>${fmt.moeda2(c.em_aberto)}</td>
        <td class="${c.restante < 0 ? "cr-negativo" : ""}">${fmt.moeda2(c.restante)}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td>Total</td><td></td><td>${fmt.moeda2(cr.limite)}</td><td>${fmt.moeda2(cr.em_aberto)}</td>
        <td class="${cr.restante < 0 ? "cr-negativo" : ""}">${fmt.moeda2(cr.restante)}</td></tr></tfoot>
    </table></div>
  </section>`;
}

function kpiPontualidade(i, k) {
  const cor = k.pontualidade == null ? "var(--linha-forte)" : k.pontualidade >= 0.9 ? "var(--ok-forte)"
    : k.pontualidade >= 0.7 ? "var(--atencao-forte)" : "var(--ruim-forte)";
  return `
  <article class="cartao kpi entra" style="--i:${i};--cor:${cor}">
    ${cab("Pontualidade", "certo")}</div>
    <div class="kpi-corpo">
      ${anel({ pct: k.pontualidade ?? 0, cor, rotulo: "pontual", tamanho: 96 })}
      <div>
        ${k.pontualidade == null ? `<div class="kpi-valor kpi-na">—</div><div class="kpi-meta">nenhum título quitado no filtro</div>`
          : `<div class="kpi-valor" data-contar="${k.pontualidade}" data-fmt="pct">0%</div>
             <div class="kpi-meta"><b>${fmt.num(k.quitados - k.quitados_atrasados)}</b> de ${fmt.num(k.quitados)} quitados até 7 dias depois do vencimento</div>`}
      </div>
    </div>
  </article>`;
}

function kpiInadimplencia(i, k, periodo) {
  const cor = k.inadimplencia > 0 ? "var(--ruim-forte)" : "var(--ok-forte)";
  return kpiValor(i, cor, "Inadimplência", "alerta", k.inadimplencia, "moeda",
    `em aberto, vencido há mais de 7 dias · ${periodo}`);
}

function kpiRestante(i, cr) {
  const passou = cr.restante < 0;
  const cor = passou ? "var(--ruim-forte)" : "var(--s-mus)";
  const usado = cr.usado ?? (cr.em_aberto > 0 ? 1 : 0);
  const escala = Math.max(1, usado);
  const meta = cr.limite > 0
    ? (passou ? `<b>passou ${fmt.moeda(-cr.restante)}</b> do limite` : `${fmt.pct(cr.usado, 0)} do limite em uso`)
    : "sem limite no cadastro";
  const pago = cr.pago_parcelas > 0
    ? `<div class="cr-pago-nota" data-tt="${esc(`Títulos em aberto: ${fmt.moeda2(cr.titulos_abertos)}<br>Parcelas já pagas: ${fmt.moeda2(cr.pago_parcelas)}<br>Ainda em aberto: ${fmt.moeda2(cr.em_aberto)}`)}">
        ${icone("certo")}${fmt.moeda(cr.pago_parcelas)} de parcelas já pagas voltaram para o limite</div>` : "";
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab("Limite restante", "escudo")}</div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor${passou ? " cr-negativo" : ""}" data-contar="${cr.restante}" data-fmt="moeda">0</div>
      <div class="kpi-meta">${meta}</div>
      <div class="medidor">
        <div class="medidor-trilho"><span class="enche" data-largura="${(Math.min(usado, escala) / escala) * 100}%"></span>${escala > 1 ? `<span class="alvo" style="left:${(1 / escala) * 100}%"></span>` : ""}</div>
        <div class="medidor-escala"><span>em aberto ${fmt.moeda(cr.em_aberto)}</span><span>limite ${fmt.moeda(cr.limite)}</span></div>
      </div>
      ${pago}
    </div></div>
  </article>`;
}

function celulaPago(l) {
  const parcelas = l.parcelas > 1 ? `${l.pagas} de ${l.parcelas} parcelas` : "";
  if (l.quitado) {
    return `<span class="fraco">${fmt.moeda2(l.pago)}</span>${parcelas ? `<small>${parcelas}</small>` : ""}`;
  }
  if (!l.pago) return parcelas ? `<span class="fraco">R$ 0,00</span><small>${parcelas}</small>` : `<span class="fraco">—</span>`;
  const tt = `Falta pagar ${fmt.moeda2(l.saldo)} de ${fmt.moeda2(l.valor)}`;
  return `<span class="cr-pago" data-tt="${esc(tt)}">${fmt.moeda2(l.pago)}</span><small>${parcelas || "pago em parte"}</small>`;
}

function tabela(d, i, animar = true) {
  const t = d.titulos, varios = d.clientes.length !== 1;
  const ordem = d.ordem || ORDEM_PADRAO;
  const padrao = ordem.coluna === ORDEM_PADRAO.coluna && ordem.sentido === ORDEM_PADRAO.sentido;
  const colunas = COLUNAS.filter((c) => varios || !c.soVarios);
  const col = COLUNAS.find((c) => c.chave === ordem.coluna);
  const nomeOrdem = col ? col.dica || col.rotulo.toLowerCase() : "";
  const sub = t.total > t.mostrando
    ? `${padrao ? `Os ${fmt.num(t.mostrando)} mais recentes` : `Os ${fmt.num(t.mostrando)} primeiros por ${esc(nomeOrdem)}`} de ${fmt.num(t.total)} títulos · ${esc(descricaoFiltro(d))}`
    : `${fmt.num(t.total)} título${t.total === 1 ? "" : "s"} · ${esc(descricaoFiltro(d))}`;
  const dias = (l) => {
    if (l.dias_atraso == null) return "—";
    const tt = l.dias_atraso < 0 ? `${-l.dias_atraso} dia${l.dias_atraso === -1 ? "" : "s"} antes do vencimento`
      : l.quitado ? "dias entre o vencimento e a quitação" : `dias desde o vencimento até ${fmt.data(d.hoje)}`;
    return `<span class="cr-dias${l.dias_atraso > 7 ? " atraso" : ""}" data-tt="${esc(tt)}">${fmt.num(l.dias_atraso)}</span>`;
  };
  const situacao = (s) => {
    const x = SITUACAO[s] || SITUACAO.a_vencer;
    return `<span class="status ${x.classe}">${icone(x.icone)}${x.rotulo}</span>`;
  };
  const th = (c) => {
    const ativa = c.chave === ordem.coluna;
    const aria = ativa ? ` aria-sort="${ordem.sentido === "asc" ? "ascending" : "descending"}"` : "";
    return `<th class="${c.esq ? "esq" : ""}"${aria}><button type="button" class="cr-ordem${ativa ? " ativa" : ""}" data-ordem="${c.chave}"
      title="Ordenar por ${esc(c.dica || c.rotulo.toLowerCase())}">${esc(c.rotulo)}<span class="cr-seta" aria-hidden="true">${ativa ? (ordem.sentido === "asc" ? "▲" : "▼") : "↕"}</span></button></th>`;
  };
  const corpo = t.linhas.length ? `
    <div class="tabela-rolagem"><table class="dados cr-titulos">
      <thead><tr>${colunas.map(th).join("")}</tr></thead>
      <tbody>${t.linhas.map((l, n) => `<tr style="--i:${Math.min(n, 20)}">
        <td>${fmt.data(l.emissao)}</td><td class="fraco">${l.id}</td>
        ${varios ? `<td class="cr-nome cr-quebra">${esc(l.cliente || `Cliente cód. ${l.id_cliente}`)}<small>código ${l.id_cliente}</small></td>` : ""}
        <td class="cr-nome">${esc(l.vendedor)}</td>
        <td>${l.vencimento ? fmt.data(l.vencimento) : "—"}</td><td>${l.quitacao ? fmt.data(l.quitacao) : "—"}</td>
        <td>${fmt.moeda2(l.valor)}</td><td class="cr-pago-cel">${celulaPago(l)}</td><td>${dias(l)}</td><td>${situacao(l.situacao)}</td>
      </tr>`).join("")}</tbody>
    </table></div>`
    : `<div class="vazio">${icone("recibo")}<p>Nenhum título neste filtro.</p></div>`;
  return `
  <section class="cartao secao${animar ? " entra" : ""}" id="cr-tabela" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone("recibo")}Títulos</h3><p class="sub">${sub}</p></div>
    </div>
    ${corpo}
  </section>`;
}

function comoCalcula(d, i) {
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como os números são calculados</h3>
        <span class="sub">As mesmas regras da página do Power BI, com as correções combinadas</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Base:</b> os títulos a receber do ERP de venda a cliente (origem VENDA, tipo CLIENTE) que não foram
            cancelados, desde o primeiro. Mês e ano filtram pela <b>data de emissão</b>; mês sem ano vale para aquele mês em
            todos os anos. O vendedor é o <b>vendedor do título</b>, não o da carteira do cliente.</li>
          <li><b>Compras:</b> valor total e quantidade de títulos; ticket médio = valor ÷ quantidade.</li>
          <li><b>Pontualidade:</b> títulos quitados até 7 dias depois do vencimento ÷ títulos quitados. No Power BI o
            cartão mostrava só 0 ou 1; aqui sai em %.</li>
          <li><b>Inadimplência:</b> soma dos títulos em aberto vencidos há mais de 7 dias, pelo valor do título.</li>
          <li><b>Valor já pago:</b> nos boletos divididos (7, 14, 21 dias…), o valor das parcelas já quitadas mais o que
            entrou numa parcela paga em parte. Juros e abatimento não contam. O vencimento do título é o da última parcela.</li>
          <li><b>Limite restante:</b> limite do cadastro − o que ainda está em aberto: <b>todos</b> os títulos em aberto do
            cliente, de qualquer emissão e vendedor, menos as parcelas já pagas (no Power BI, com mês e ano escolhidos, só os
            emitidos no período entravam, e as parcelas pagas não voltavam). Negativo = passou do limite. Com vários clientes
            escolhidos, os limites e o que está em aberto somam. Limite, prazo e restante só aparecem com cliente escolhido.</li>
          <li><b>Dias de atraso:</b> quitado = quitação − vencimento; em aberto = ${fmt.data(d.hoje)} (o dia da extração dos
            dados) − vencimento. Negativo = antes do vencimento.</li>
          <li><b>Tabela:</b> clique no nome de uma coluna para ordenar; de novo, para inverter. A ordem vale para todos os
            títulos do filtro, não só para os que aparecem.</li>
        </ol>
      </div>
    </details>
  </section>`;
}
