// Página Reavaliação de Crédito: a página "Reavaliação Credito" do Power BI. Compras, pontualidade e inadimplência
// pelos títulos a receber de venda (mês e ano pela emissão, vendedor do título); limite, prazo e restante de um ou
// mais clientes (os limites somam), com as parcelas já pagas dos boletos divididos. Com um cliente, o parecer de um
// limite total novo (Indicado, com ressalvas ou Não indicado), o registro da reanálise (o limite e o prazo liberados e
// a justificativa) e as reanálises anteriores dele. A conta, a regra do parecer, a ordem da tabela e o retrato que a
// reanálise grava ficam no servidor (bi/credito.py e bi/reanalise.py); aqui é a apresentação.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast, MESES } from "./util.js";
import { anel } from "./graficos.js";
import { ligarTelaCheia, sairTelaCheia, reajustarTelaCheia } from "./telacheia.js";

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
// limite: o limite total pedido no parecer (some ao trocar de cliente); analise: o pedido do parecer em andamento.
// parecer: o último parecer mostrado (o registro grava o pedido dele); reanalises: o que /api/credito/reanalises
// trouxe do cliente (historico: o pedido em andamento); rascunho: o que foi digitado no registro, que fica quando a
// página é refeita por um filtro e some ao trocar de cliente ou depois de registrar.
const estado = { clientes: [], mes: null, ano: null, vendedor: null, ordem: null, limite: null, dados: null, pedido: 0,
  busca: 0, analise: 0, parecer: null, reanalises: null, historico: 0, rascunho: null };

export function montarCredito(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const num = (t) => (t && Number.isInteger(Number(t)) && Number(t) > 0 ? Number(t) : null);
  const valor = (t) => (t && Number.isFinite(Number(t)) && Number(t) > 0 ? Number(t) : null);
  const ordem = (t) => {
    const [coluna, sentido] = String(t || "").split("-");
    return COLUNAS.some((c) => c.chave === coluna) && ["asc", "desc"].includes(sentido) ? { coluna, sentido } : null;
  };
  if (["c", "m", "a", "v", "o", "l"].some((k) => q.has(k))) {
    Object.assign(estado, {
      clientes: (q.get("c") || "").split(",").map(num).filter(Boolean).map((id) => ({ id, nome: "" })),
      mes: num(q.get("m")), ano: num(q.get("a")), vendedor: num(q.get("v")), ordem: ordem(q.get("o")),
      limite: valor(q.get("l")),
    });
  } else if (!estado.dados) {
    const s = ler("mv-credito", {});
    Object.assign(estado, { clientes: Array.isArray(s.c) ? s.c.filter((c) => num(c?.id)) : [], mes: num(s.m),
      ano: num(s.a), vendedor: num(s.v), ordem: ordem(s.o), limite: valor(s.l) });
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
      <div class="kpis n4"><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div></div>
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
    Object.assign(estado, { clientes: [], mes: null, ano: null, vendedor: null, limite: null, rascunho: null });
    container.querySelector("#cr-cliente").value = "";
    desenharEscolhidos();
    carregar();
  });
  container.querySelector("#cr-escolhidos").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tirar]");
    if (b) tirarCliente(Number(b.dataset.tirar));
  });
  carregar();
}

// Ordenar a tabela: o servidor ordena o filtro inteiro (sem cliente, a tabela mostra só uma parte dos títulos).
// O clique fica no próprio cartão, que em tela cheia sai de #cr-conteudo.
function ligarOrdem(card) {
  card?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ordem]");
    if (!b) return;
    const atual = estado.ordem || ORDEM_PADRAO, col = COLUNAS.find((c) => c.chave === b.dataset.ordem);
    estado.ordem = atual.coluna === col.chave
      ? { coluna: col.chave, sentido: atual.sentido === "asc" ? "desc" : "asc" }
      : { coluna: col.chave, sentido: col.sentido };
    carregar(false, true);
  });
}

export function recarregarCredito() { if (ctx) carregar(true); }

function atualizarUrl() {
  const o = estado.ordem;
  guardar("mv-credito", { c: estado.clientes, m: estado.mes, a: estado.ano, v: estado.vendedor, o: o ? `${o.coluna}-${o.sentido}` : null,
    l: estado.limite });
  if (!location.hash.startsWith("#/credito")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams();
  if (estado.clientes.length) p.set("c", estado.clientes.map((c) => c.id).join(","));
  if (estado.mes) p.set("m", estado.mes);
  if (estado.ano) p.set("a", estado.ano);
  if (estado.vendedor) p.set("v", estado.vendedor);
  if (o) p.set("o", `${o.coluna}-${o.sentido}`);
  if (estado.limite && estado.clientes.length === 1) p.set("l", estado.limite);
  history.replaceState(null, "", `#/credito${p.toString() ? "?" + p : ""}`);
  const limpar = document.getElementById("cr-limpar");
  if (limpar) limpar.hidden = !estado.clientes.length && !estado.mes && !estado.ano && !estado.vendedor;
}

// soTabela: só a ordem mudou; troca a tabela sem refazer (e reanimar) o resto da página, e sem sair da tela cheia.
async function carregar(silencioso = false, soTabela = false) {
  const conteudo = document.getElementById("cr-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  const alvo = (soTabela && document.getElementById("cr-tabela")) || conteudo;
  if (alvo === conteudo) sairTelaCheia();
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
      // o cartão fica (com o botão e, se for o caso, em tela cheia); só o que tem dentro dele é trocado
      const novo = document.createElement("template");
      novo.innerHTML = tabela(d, 0, false);
      const botao = alvo.querySelector(":scope > .btn-tela-cheia");
      alvo.replaceChildren(...novo.content.querySelector("#cr-tabela").childNodes, ...(botao ? [botao] : []));
      posRender(alvo);
      reajustarTelaCheia();
      return;
    }
    conteudo.innerHTML = render(d);
    posRender(conteudo);
    ligarOrdem(document.getElementById("cr-tabela"));
    ligarAnalise();
    ligarReanalises();
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 400 && (estado.clientes.length || estado.ano || estado.vendedor || estado.ordem)) {
      // filtro guardado neste navegador que não vale mais (cliente apagado, ano fora dos dados): volta a todos
      Object.assign(estado, { clientes: [], ano: null, vendedor: null, ordem: null, limite: null, rascunho: null });
      desenharEscolhidos();
      toast(e.message, "erro");
      return carregar(silencioso);
    }
    const ic = e.status === 403 ? "cadeado" : "alerta";
    const msg = e.status === 403 || e.status === 503 ? esc(e.message) : `Não foi possível carregar: ${esc(e.message)}`;
    sairTelaCheia(); // a tabela em tela cheia (ao ordenar) também some
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
  estado.limite = null; // o limite pedido e o registro começado eram de outro cliente
  estado.rascunho = null;
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

// Quantos caracteres o valor terá no fim da contagem: o CSS encolhe os longos (milhões) para caberem no cartão.
const largura = (valor, formato) => ` style="--n:${fmt[formato](valor).length}"`;

function kpiValor(i, cor, titulo, ic, valor, formato, meta, rodape = []) {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab(titulo, ic)}</div>
    <div class="kpi-corpo"><div>
      ${valor == null ? `<div class="kpi-valor kpi-na">—</div>`
        : `<div class="kpi-valor" data-contar="${valor}" data-fmt="${formato}"${largura(valor, formato)}>0</div>`}
      <div class="kpi-meta">${meta}</div>
    </div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function kpiSemCliente(i, cor, titulo, ic, meta = "O limite e o prazo são do cadastro de cada cliente.") {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab(titulo, ic)}</div>
    <div class="kpi-corpo"><div><div class="kpi-valor kpi-na">Escolha um cliente</div>
      <div class="kpi-meta">${meta}</div></div></div>
  </article>`;
}

// Prazo ou vendedor da carteira de vários clientes: o mesmo para todos, ou quantos diferentes.
const umOuVarios = (lista, varios) => (lista.length === 1 ? esc(lista[0]) : `${lista.length} ${varios}`);

// ---------- estrutura ----------
function render(d) {
  const k = d.cartoes, cr = d.credito, n = d.clientes.length;
  const periodo = descricaoFiltro(d);
  let h = n ? cabecalhoClientes(d) : "";
  if (n === 1) h += cartaoAnalise(d, 2) + cartaoReanalises(3);
  h += `<section class="kpis secao n4">
    ${kpiValor(1, "var(--s-fat)", "Valor total das compras", "moeda", k.valor, "moeda", periodo)}
    ${kpiValor(2, "var(--s-out)", "Quantidade de compras", "recibo", k.quantidade, "num", "títulos a receber de venda")}
    ${kpiValor(3, "var(--k-vm)", "Ticket médio", "etiqueta", k.ticket, "moeda", "valor ÷ quantidade de compras")}
    ${kpiInadimplencia(4, k, periodo)}
  </section>`;
  h += `<section class="kpis secao n4">
    ${kpiPontualidade(5, k)}
    ${cr ? kpiValor(6, "var(--k-cli)", "Limite de crédito", "cartao", cr.limite, "moeda",
      n > 1 ? `soma dos limites de ${n} clientes` : cr.limite > 0 ? "do cadastro do cliente" : "sem limite no cadastro",
      [["Prazo", umOuVarios(cr.prazos, "prazos diferentes")],
       ["Vendedor da carteira", umOuVarios(cr.carteiras, "vendedores")]])
      : kpiSemCliente(6, "var(--k-cli)", "Limite de crédito", "cartao")}
    ${cr ? kpiUtilizado(7, cr) : kpiSemCliente(7, "var(--s-out)", "Limite já utilizado", "tendencia",
      "Tudo o que o cliente ainda tem em aberto.")}
    ${cr ? kpiRestante(8, cr) : kpiSemCliente(8, "var(--s-mus)", "Limite restante", "escudo")}
  </section>`;
  h += tabela(d, 9);
  h += comoCalcula(d, 10);
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
    <p class="cr-analise-dica">${icone("escudo")}Para analisar um limite novo, deixe só um cliente escolhido.</p>
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
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab("Limite restante", "escudo")}</div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor${passou ? " cr-negativo" : ""}" data-contar="${cr.restante}" data-fmt="moeda"${largura(cr.restante, "moeda")}>0</div>
      <div class="kpi-meta">${meta}</div>
      <div class="medidor">
        <div class="medidor-trilho"><span class="enche" data-largura="${(Math.min(usado, escala) / escala) * 100}%"></span>${escala > 1 ? `<span class="alvo" style="left:${(1 / escala) * 100}%"></span>` : ""}</div>
        <div class="medidor-escala"><span>utilizado ${fmt.moeda(cr.em_aberto)}</span><span>limite ${fmt.moeda(cr.limite)}</span></div>
      </div>
    </div></div>
  </article>`;
}

// Limite já utilizado: tudo o que o cliente ainda tem em aberto (os títulos em aberto menos as parcelas já pagas).
function kpiUtilizado(i, cr) {
  const titulos = `${fmt.num(cr.qtd_abertos)} título${cr.qtd_abertos === 1 ? "" : "s"} em aberto`;
  const meta = cr.limite > 0 ? `${titulos} · ${fmt.pct(cr.usado, 0)} do limite` : titulos;
  const rodape = cr.pago_parcelas > 0
    ? [["Títulos em aberto", fmt.moeda(cr.titulos_abertos)],
       ["Parcelas já pagas", `− ${fmt.moeda(cr.pago_parcelas)}`]]
    : [];
  return kpiValor(i, cr.limite > 0 && cr.restante < 0 ? "var(--ruim-forte)" : "var(--s-out)", "Limite já utilizado",
    "tendencia", cr.em_aberto, "moeda", meta, rodape);
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

// ---------- parecer de um limite novo (a regra é do servidor: Credito.analisar) ----------
const PARECER = {
  indicado: { rotulo: "Indicado", classe: "no_ritmo", cor: "ok", icone: "certo" },
  ressalvas: { rotulo: "Indicado com ressalvas", classe: "atencao", cor: "mid", icone: "alerta" },
  nao_indicado: { rotulo: "Não indicado", classe: "abaixo", cor: "bad", icone: "x" },
};
const ICONE_CRITERIO = { ok: "certo", atencao: "alerta", bloqueio: "x" };
const vezes = (v) => `${fmt.num(v, 1)}×`;
const numero = (rotulo, valor, sub = "") => `<div><span>${rotulo}</span><b>${valor}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;

// "80.000", "80.000,50", "R$ 80000" ou "80000.5" -> número; null quando não é um valor positivo (zero: aceita 0).
function lerValor(texto, zero = false) {
  let s = String(texto || "").replace(/[^\d.,]/g, "");
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else if (!/^\d+\.\d{1,2}$/.test(s)) s = s.replace(/\./g, ""); // ponto de milhar, não de centavos
  const v = Number(s);
  return s && Number.isFinite(v) && (v > 0 || (zero && v === 0)) ? v : null;
}

function cartaoAnalise(d, i) {
  const c = d.clientes[0];
  const inicial = estado.limite ?? (c.limite > 0 ? c.limite : null);
  return `
  <section class="cartao secao entra cr-analise" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone("escudo")}Analisar novo limite</h3>
        <p class="sub">Digite o limite total que o cliente vai ter. A análise usa todo o histórico dele, de qualquer vendedor, sem os filtros de mês, ano e vendedor. Depois do parecer, registre o que foi liberado.</p></div>
    </div>
    <form class="cr-analise-form" id="cr-analise-form" novalidate>
      <label class="campo sem-seta"><span class="ic-campo">${icone("moeda")}</span>
        <input type="text" id="cr-limite" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="Limite pedido, em R$"
          aria-label="Limite total pedido, em reais" value="${inicial ? fmt.num(inicial, 2) : ""}"></label>
      <button class="btn primario" type="submit">${icone("escudo")}Analisar</button>
      <span class="cr-analise-atual">limite de hoje: <b>${c.limite > 0 ? fmt.moeda2(c.limite) : "sem limite no cadastro"}</b></span>
    </form>
    <div id="cr-analise-resultado" aria-live="polite"></div>
  </section>`;
}

function ligarAnalise() {
  const form = document.getElementById("cr-analise-form");
  if (!form) return;
  const campo = form.querySelector("#cr-limite");
  const pedir = (v) => {
    estado.limite = v;
    campo.value = fmt.num(v, 2);
    atualizarUrl();
    analisar();
  };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = lerValor(campo.value);
    if (!v) {
      toast("Digite o limite total pedido, em reais.", "erro");
      campo.focus();
      return;
    }
    pedir(v);
  });
  const resultado = document.getElementById("cr-analise-resultado");
  // "Analisar R$ X": o limite sugerido vira o pedido
  resultado.addEventListener("click", (e) => {
    const b = e.target.closest("[data-usar]");
    if (b) pedir(Number(b.dataset.usar));
  });
  // O registro da reanálise, que fica dentro do parecer (e é refeito com ele).
  resultado.addEventListener("input", (e) => {
    const f = e.target.closest("#cr-registro-form");
    if (!f) return;
    const digitou = e.target.name === "liberado" || estado.rascunho?.digitou;
    estado.rascunho = { cliente: estado.parecer?.cliente.id, liberado: f.liberado.value, prazo: f.prazo.value,
      justificativa: f.justificativa.value, digitou };
    resumoRegistro();
  });
  resultado.addEventListener("submit", (e) => {
    if (e.target.id !== "cr-registro-form") return;
    e.preventDefault();
    registrar(e.target);
  });
  if (estado.limite) analisar(); // veio do link ou deste navegador
}

async function analisar() {
  const alvo = document.getElementById("cr-analise-resultado");
  if (!alvo || estado.clientes.length !== 1 || !estado.limite) return;
  const pedido = ++estado.analise;
  if (alvo.childElementCount) alvo.classList.add("recarregando");
  else alvo.innerHTML = `<div class="esqueleto" style="height:240px"></div>`;
  try {
    const a = await api(`/api/credito/analise?cliente=${estado.clientes[0].id}&limite=${estado.limite}`);
    if (pedido !== estado.analise) return;
    estado.parecer = a;
    alvo.innerHTML = parecer(a);
    desenharRegistro();
  } catch (e) {
    if (pedido !== estado.analise) return;
    alvo.innerHTML = `<div class="aviso">${icone("alerta")}<span>Não foi possível analisar: ${esc(e.message)}</span></div>`;
  } finally {
    if (pedido === estado.analise) alvo.classList.remove("recarregando");
  }
}

function sugestao(a) {
  const n = a.numeros, r = a.regra;
  if (a.limite_sugerido == null) return "";
  const base = `${r.folga_ok}× o maior saldo em aberto dos últimos 12 meses (${fmt.moeda(n.maior_saldo)})`;
  if (a.limite_sugerido <= n.limite_atual) {
    return `<div class="cr-sugerido">${icone("info")}<p>O limite de hoje (${fmt.moeda(n.limite_atual)}) já cobre o que o
      histórico sustenta: ${fmt.moeda(a.limite_sugerido)}, ${base}.</p></div>`;
  }
  const outro = Math.abs(a.limite_sugerido - a.pedido) >= 0.01;
  return `<div class="cr-sugerido">${icone("info")}<p>O histórico sustenta um limite de até <b>${fmt.moeda(a.limite_sugerido)}</b>:
    ${base}, arredondado para cima.</p>
    ${outro ? `<button type="button" class="btn" data-usar="${a.limite_sugerido}">Analisar ${fmt.moeda(a.limite_sugerido)}</button>` : ""}</div>`;
}

function parecer(a) {
  const p = PARECER[a.parecer], n = a.numeros;
  const variacao = n.limite_atual > 0 ? a.pedido / n.limite_atual - 1 : null;
  const comparado = variacao == null ? "hoje sem limite no cadastro"
    : Math.abs(variacao) < 0.0005 ? "o mesmo de hoje"
    : `${variacao > 0 ? "+" : "−"}${fmt.pct(Math.abs(variacao), 0)} sobre o de hoje (${fmt.moeda(n.limite_atual)})`;
  return `
  <div class="cr-parecer ${p.cor} entra" style="--i:0">
    <div class="cr-parecer-cab">
      <span class="status ${p.classe}">${icone(p.icone)}${p.rotulo}</span>
      <span class="cr-parecer-pedido">limite pedido <b>${fmt.moeda2(a.pedido)}</b> · ${comparado}</span>
    </div>
    <ul class="cr-criterios">${a.criterios.map((c) => `
      <li class="${c.status}"><span class="cr-crit-ic">${icone(ICONE_CRITERIO[c.status])}</span>
        <div><b>${esc(c.titulo)}</b><span>${esc(c.detalhe)}</span></div></li>`).join("")}
    </ul>
    ${sugestao(a)}
    <div class="cr-parecer-numeros">
      ${numero("Maior saldo em aberto (12 meses)", fmt.moeda(n.maior_saldo),
        n.maior_saldo_em ? `em ${fmt.data(n.maior_saldo_em)}` : "")}
      ${numero("Limite pedido ÷ maior saldo", n.pedido_vezes_maior_saldo == null ? "—" : vezes(n.pedido_vezes_maior_saldo))}
      ${numero("Compras por mês (12 meses)", fmt.moeda(n.compras_mes))}
      ${numero("Prazo real", n.prazo_real == null ? "—" : `${fmt.num(n.prazo_real)} dias`,
        n.prazo_real == null ? "" : "mediana entre a emissão e o vencimento")}
      ${numero("Em aberto hoje", fmt.moeda(n.em_aberto),
        `${fmt.num(n.qtd_abertos)} título${n.qtd_abertos === 1 ? "" : "s"}, menos as parcelas pagas`)}
    </div>
    ${(a.avisos || []).map((x) => `<div class="aviso">${icone("alerta")}<span>${esc(x)}</span></div>`).join("")}
    <p class="cr-parecer-nota">Regra fixa da página, sem IA: os mesmos dados dão sempre a mesma resposta. Dados até
      ${fmt.data(a.hoje)}. A decisão final é de quem libera o crédito.</p>
    <div class="cr-registro" id="cr-registro"></div>
  </div>`;
}

// ---------- reanálise: registrar a decisão e as anteriores (bi/reanalise.py) ----------
const DECISAO = { primeiro_limite: "Primeiro limite", aumentou: "Aumento", manteve: "Manteve o limite", reduziu: "Redução",
  cortou: "Cortou o crédito" };

function cartaoReanalises(i) {
  return `
  <section class="cartao secao entra cr-historico" id="cr-reanalises" style="--i:${i}">
    <div class="cartao-cab"><div><h3>${icone("caderneta")}Reanálises deste cliente</h3>
      <p class="sub">o limite e o prazo liberados em cada reanálise, com a justificativa</p></div></div>
    <div class="esqueleto" style="height:72px"></div>
  </section>`;
}

function ligarReanalises() {
  const card = document.getElementById("cr-reanalises");
  if (!card) return;
  card.addEventListener("click", (e) => {
    const b = e.target.closest("[data-excluir]");
    if (b) excluirReanalise(Number(b.dataset.excluir), b);
  });
  desenharHistorico(); // a página refeita por um filtro já mostra as do mesmo cliente enquanto lê de novo
  carregarReanalises();
}

async function carregarReanalises() {
  if (!document.getElementById("cr-reanalises") || estado.clientes.length !== 1) return;
  const cliente = estado.clientes[0].id, pedido = ++estado.historico;
  try {
    const r = await api(`/api/credito/reanalises?cliente=${cliente}`);
    if (pedido !== estado.historico) return;
    estado.reanalises = { ...r, cliente };
  } catch (e) {
    if (pedido !== estado.historico) return;
    estado.reanalises = { erro: e.message, cliente };
  }
  desenharHistorico();
  desenharRegistro();
}

// A última reanálise contra o cadastro de hoje do ERP (o painel não muda o ERP: a pessoa muda lá).
function situacaoErp(x) {
  const e = x.erp;
  if (!e) return "";
  if (e.situacao === "aplicado") {
    return `<p class="cr-erp ok">${icone("certo")}<span>O cadastro do ERP já está com o limite e o prazo da última reanálise.</span></p>`;
  }
  if (e.situacao === "aguardando") {
    return `<p class="cr-erp">${icone("relogio")}<span>A última reanálise foi registrada com os dados de agora: o cadastro do ERP aparece na próxima atualização.</span></p>`;
  }
  return `<p class="cr-erp atencao">${icone("alerta")}<span>O cadastro do ERP está com <b>${fmt.moeda2(e.limite)} · ${esc(e.prazo || "sem prazo")}</b>,
    diferente da última reanálise (${fmt.moeda2(x.limite_liberado)} · ${esc(x.prazo_liberado)}).</span></p>`;
}

function itemReanalise(x) {
  const p = PARECER[x.parecer], n = x.numeros, v = x.decisao.variacao_limite;
  const tipo = DECISAO[x.decisao.limite] + (v != null && Math.abs(v) >= 0.0005 ? ` ${v > 0 ? "+" : "−"}${fmt.pct(Math.abs(v), 0)}` : "");
  const prazo = x.prazo_antes === x.prazo_liberado ? `prazo ${esc(x.prazo_liberado)}`
    : `prazo ${esc(x.prazo_antes || "não informado")} → <b>${esc(x.prazo_liberado)}</b>`;
  const liberado = x.parecer_liberado && x.parecer_liberado !== x.parecer
    ? ` · para o liberado: ${PARECER[x.parecer_liberado].rotulo.toLowerCase()}` : "";
  return `
  <li class="cr-hist-item">
    <div class="cr-hist-cab">
      <span class="cr-hist-quando"><b>${fmt.dataHora(x.feita_em)}</b> · ${esc(x.feita_por)}</span>
      <span class="cr-hist-tipo">${tipo}</span>
      <span class="status ${p.classe}" title="Parecer da regra para o limite pedido">${icone(p.icone)}${p.rotulo}</span>
      ${x.pode_excluir ? `<button type="button" class="btn perigo cr-hist-excluir" data-excluir="${x.id}"
        aria-label="Excluir a reanálise de ${fmt.dataHora(x.feita_em)}">${icone("lixeira")}Excluir</button>` : ""}
    </div>
    <p class="cr-hist-valores"><span>Limite ${fmt.moeda2(x.limite_antes)} → <b>${fmt.moeda2(x.limite_liberado)}</b></span>
      <span>${prazo}</span>
      <small>pedido ${fmt.moeda2(x.limite_pedido)}${x.limite_sugerido != null ? ` · a regra sugeria ${fmt.moeda2(x.limite_sugerido)}` : ""}${liberado}</small></p>
    <p class="cr-hist-just">${esc(x.justificativa)}</p>
    <details class="cr-hist-numeros"><summary>Ver os números do dia</summary>
      <div class="cr-parecer-numeros">
        ${numero("Compras (todo o histórico)", fmt.moeda(n.compras_valor),
          `${fmt.num(n.compras_qtd)} títulos${n.meses_cliente == null ? "" : ` · cliente há ${fmt.num(n.meses_cliente)} meses`}`)}
        ${numero("Pontualidade (12 meses)", fmt.pct(n.pontualidade_12m), `em todo o histórico: ${fmt.pct(n.pontualidade)}`)}
        ${numero("Compras por mês (12 meses)", fmt.moeda(n.compras_mes_12m))}
        ${numero("Maior saldo em aberto (12 meses)", fmt.moeda(n.maior_saldo_12m))}
        ${numero("Em aberto", fmt.moeda(n.em_aberto), n.uso_do_limite == null ? "" : `${fmt.pct(n.uso_do_limite, 0)} do limite de antes`)}
        ${numero("Inadimplência", fmt.moeda(n.inadimplencia))}
        ${numero("Prazo real (12 meses)", n.prazo_real_12m == null ? "—" : `${fmt.num(n.prazo_real_12m)} dias`)}
      </div>
      <p class="cr-parecer-nota">Dados até ${fmt.dataHora(x.dados_ate)}.</p>
    </details>
  </li>`;
}

function desenharHistorico() {
  const card = document.getElementById("cr-reanalises"), r = estado.reanalises;
  if (!card || !r || estado.clientes.length !== 1 || r.cliente !== estado.clientes[0].id) return;
  const lista = r.reanalises || [];
  let corpo;
  if (r.erro) corpo = `<div class="aviso">${icone("alerta")}<span>Não foi possível ler as reanálises: ${esc(r.erro)}</span></div>`;
  else if (!r.ativo) corpo = `<div class="aviso">${icone("info")}<span>${esc(r.aviso)}</span></div>`;
  else if (!lista.length) corpo = `<p class="cr-hist-vazio">Nenhuma reanálise registrada para este cliente. Analise um limite e registre a decisão logo abaixo do parecer.</p>`;
  else corpo = situacaoErp(lista[0]) + `<ol class="cr-hist">${lista.map(itemReanalise).join("")}</ol>`;
  const sub = lista.length ? `${lista.length} registrada${lista.length === 1 ? "" : "s"}, da mais nova para a mais antiga`
    : "o limite e o prazo liberados em cada reanálise, com a justificativa";
  card.innerHTML = `
    <div class="cartao-cab"><div><h3>${icone("caderneta")}Reanálises deste cliente</h3><p class="sub">${sub}</p></div></div>
    ${corpo}`;
}

function desenharRegistro() {
  const alvo = document.getElementById("cr-registro"), a = estado.parecer, r = estado.reanalises;
  if (!alvo || !a || !r || r.cliente !== a.cliente.id) return;
  if (r.erro) { alvo.innerHTML = ""; return; } // o cartão das reanálises já mostra o erro
  if (!r.ativo) { alvo.innerHTML = `<div class="aviso">${icone("info")}<span>${esc(r.aviso)}</span></div>`; return; }
  const s = estado.rascunho?.cliente === a.cliente.id ? estado.rascunho : null;
  const liberado = s?.digitou ? s.liberado : fmt.num(a.pedido, 2);
  const prazo = s ? s.prazo : (a.cliente.prazo || "");
  const opcoes = r.prazos.map((x) => `<option value="${esc(x)}"${x === prazo ? " selected" : ""}>${esc(x)}${x === a.cliente.prazo ? " (de hoje)" : ""}</option>`).join("");
  alvo.innerHTML = `
    <form class="cr-registro-form" id="cr-registro-form" novalidate>
      <div class="cr-registro-cab"><h4>${icone("caderneta")}Registrar reanálise</h4>
        <p>Grava a decisão com os números do cliente de agora (dados até ${fmt.dataHora(r.dados_ate)}). O painel não muda o ERP: depois de registrar, mude o limite e o prazo lá.</p></div>
      <div class="cr-registro-campos">
        <label class="campo-form"><span>Limite liberado (R$)</span>
          <input type="text" name="liberado" inputmode="decimal" autocomplete="off" spellcheck="false" value="${esc(liberado)}"></label>
        <label class="campo-form"><span>Prazo liberado</span><span class="campo"><span class="ic-campo">${icone("calendario")}</span>
          <select name="prazo">${prazo && r.prazos.includes(prazo) ? "" : `<option value="" selected>Escolha o prazo</option>`}${opcoes}</select></span></label>
      </div>
      <label class="campo-form"><span>Justificativa</span>
        <textarea name="justificativa" rows="3" maxlength="2000" placeholder="Por que liberou esse limite e esse prazo?">${esc(s?.justificativa || "")}</textarea>
        <small>Não escreva CPF, telefone ou endereço: o Assistente lê as justificativas.</small></label>
      <p class="cr-registro-resumo" id="cr-registro-resumo" aria-live="polite"></p>
      <div><button class="btn primario" type="submit">${icone("certo")}Registrar reanálise</button></div>
    </form>`;
  resumoRegistro();
}

// O que o registro vai gravar, enquanto a pessoa digita.
function resumoRegistro() {
  const f = document.getElementById("cr-registro-form"), a = estado.parecer;
  if (!f || !a) return;
  const v = lerValor(f.liberado.value, true), prazo = f.prazo.value;
  const antes = a.numeros.limite_atual, prazoAntes = a.cliente.prazo;
  let limite;
  if (v == null) limite = "Digite o limite liberado (0 corta o crédito)";
  else if (Math.abs(v - antes) < 0.005) limite = `Mantém o limite de ${fmt.moeda2(antes)}`;
  else {
    const varia = antes > 0 ? ` (${v > antes ? "+" : "−"}${fmt.pct(Math.abs(v / antes - 1), 0)})` : "";
    limite = `Limite ${fmt.moeda2(antes)} → <b>${fmt.moeda2(v)}</b>${varia}`;
  }
  const partes = [limite];
  if (prazo) partes.push(prazo === prazoAntes ? `mantém o prazo ${esc(prazo)}` : `prazo ${esc(prazoAntes || "não informado")} → <b>${esc(prazo)}</b>`);
  const outro = v != null && Math.abs(v - a.pedido) >= 0.005
    ? `<small>O parecer acima é do limite pedido (${fmt.moeda2(a.pedido)}); o registro guarda também o da regra para o valor liberado.</small>` : "";
  f.querySelector("#cr-registro-resumo").innerHTML = partes.join(" · ") + outro;
}

async function registrar(f) {
  const a = estado.parecer, r = estado.reanalises;
  if (!a || !r?.ativo) return;
  const liberado = lerValor(f.liberado.value, true), justificativa = f.justificativa.value.trim();
  const faltou = liberado == null ? [f.liberado, "Digite o limite liberado, em reais (0 corta o crédito)."]
    : !f.prazo.value ? [f.prazo, "Escolha o prazo liberado."]
    : justificativa.length < 10 ? [f.justificativa, "Escreva a justificativa (pelo menos 10 letras)."] : null;
  if (faltou) {
    toast(faltou[1], "erro");
    faltou[0].focus();
    return;
  }
  const botao = f.querySelector('button[type="submit"]');
  botao.disabled = true;
  try {
    const novo = await api("/api/credito/reanalise", { json: { chave: r.chave, cliente: a.cliente.id, pedido: a.pedido,
      liberado, prazo: f.prazo.value, justificativa, dados_ate: estado.dados?.extraido_em } });
    estado.rascunho = null;
    estado.reanalises = { ...novo, cliente: a.cliente.id };
    desenharHistorico();
    desenharRegistro();
    toast(novo.ja_existia ? "Esta reanálise já estava registrada." : "Reanálise registrada. Agora mude o limite e o prazo no ERP.");
  } catch (e) {
    toast(e.message, "erro");
    if (e.status === 400 && /atualizados/.test(e.message)) carregar(true); // extração nova: refaz a página e o parecer
  } finally {
    botao.disabled = false;
  }
}

async function excluirReanalise(id, botao) {
  if (!confirm("Excluir esta reanálise? Ela sai desta página e do Assistente.")) return;
  const cliente = estado.reanalises?.cliente;
  botao.disabled = true;
  try {
    const r = await api("/api/credito/reanalise/excluir", { json: { id } });
    estado.reanalises = { ...r, cliente };
    desenharHistorico();
    desenharRegistro();
    toast("Reanálise excluída.");
  } catch (e) {
    toast(e.message, "erro");
    botao.disabled = false;
  }
}

function comoParecer(r) {
  if (!r) return "";
  const pct = (v) => fmt.pct(v, 0);
  return `
          <li><b>Parecer de um limite novo</b> (com um cliente escolhido): o limite total que o cliente vai ter, contra
            o histórico inteiro dele (qualquer vendedor, sem os filtros de mês, ano e vendedor) nos últimos 12 meses até o
            dia da extração. É uma regra fixa, sem IA. <b>Não indicado</b>: título em aberto vencido há mais de
            ${r.tolerancia} dias, pontualidade abaixo de ${pct(r.pontual_min)} ou limite pedido acima de ${r.folga_max}× o
            maior saldo em aberto. <b>Indicado com ressalvas</b>: vencido há até ${r.tolerancia} dias; pontualidade abaixo
            de ${pct(r.pontual_ok)} ou menos de ${r.min_quitados} títulos quitados; cliente há menos de ${r.meses_cliente}
            meses; limite pedido acima do que o histórico sustenta (${r.folga_ok}× o maior saldo em aberto, arredondado
            para cima em ${fmt.moeda(r.arredondar)}); já deve mais que o limite pedido; ou
            nenhuma compra há mais de ${r.dias_sem_compra} dias. Senão, <b>Indicado</b>. Um limite igual ou menor que o de
            hoje não conta como aumento. <b>Maior saldo em aberto</b>: o máximo que o cliente deveu ao mesmo tempo nos 12
            meses, pelo valor dos títulos (sem descontar as parcelas: não temos a data de cada uma). <b>Limite
            sugerido</b>: o que o histórico sustenta (${r.folga_ok}× esse saldo, arredondado); não aparece
            com inadimplência nem com pontualidade abaixo de ${pct(r.pontual_min)}.</li>`;
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
          <li><b>Limite já utilizado:</b> tudo o que o cliente ainda tem em aberto: <b>todos</b> os títulos em aberto dele,
            de qualquer emissão e vendedor, menos as parcelas já pagas. Não depende do mês, do ano nem do vendedor.</li>
          <li><b>Limite restante:</b> limite do cadastro − limite já utilizado (no Power BI, com mês e ano escolhidos, só os
            emitidos no período entravam, e as parcelas pagas não voltavam). Negativo = passou do limite. Com vários clientes
            escolhidos, os limites e o que está em aberto somam. Limite, utilizado, prazo e restante só aparecem com cliente
            escolhido.</li>
          ${comoParecer(d.regra_parecer)}
          <li><b>Reanálise</b> (com um cliente escolhido, depois do parecer): quem tem a página registra o limite e o
            prazo liberados e a justificativa, e o painel guarda junto os números do cliente naquele momento (compras,
            pontualidade, o que está em aberto, os 12 meses da regra, o mês a mês e o parecer), para comparar decisões
            depois e para o Assistente. O registro não muda o ERP e fica só no site. Não dá para editar: quem registrou ou
            um administrador exclui e registra de novo.</li>
          <li><b>Dias de atraso:</b> quitado = quitação − vencimento; em aberto = ${fmt.data(d.hoje)} (o dia da extração dos
            dados) − vencimento. Negativo = antes do vencimento.</li>
          <li><b>Tabela:</b> clique no nome de uma coluna para ordenar; de novo, para inverter. A ordem vale para todos os
            títulos do filtro, não só para os que aparecem.</li>
        </ol>
      </div>
    </details>
  </section>`;
}
