// Página Reavaliação de Crédito: a página "Reavaliação Credito" do Power BI. Compras, pontualidade e inadimplência
// pelos títulos a receber de venda (mês e ano pela emissão, vendedor do título); limite, prazo e restante do
// cliente escolhido. A conta fica no servidor (bi/credito.py); aqui é a apresentação.
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
const maiuscula = (t) => t.charAt(0).toUpperCase() + t.slice(1);

let ctx = null;
const estado = { cliente: null, mes: null, ano: null, vendedor: null, dados: null, pedido: 0, busca: 0 };

export function montarCredito(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const num = (t) => (t && Number.isInteger(Number(t)) && Number(t) > 0 ? Number(t) : null);
  if (["c", "m", "a", "v"].some((k) => q.has(k))) {
    Object.assign(estado, { cliente: num(q.get("c")) && { id: num(q.get("c")), nome: "" }, mes: num(q.get("m")),
      ano: num(q.get("a")), vendedor: num(q.get("v")) });
  } else if (!estado.dados) {
    const s = ler("mv-credito", {});
    Object.assign(estado, { cliente: s.c?.id ? s.c : null, mes: num(s.m), ano: num(s.a), vendedor: num(s.v) });
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
              role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="cr-sugestoes" aria-label="Cliente"></label>
          <div class="multi-painel cr-sugestoes" id="cr-sugestoes" role="listbox" aria-label="Clientes encontrados" hidden></div>
        </div>
        <label class="campo"><span class="ic-campo">${icone("calendario")}</span><select id="cr-mes" aria-label="Mês de emissão">
          <option value="">Todos os meses</option>${MESES.map((m, i) => `<option value="${i + 1}">${maiuscula(m)}</option>`).join("")}</select></label>
        <label class="campo"><span class="ic-campo">${icone("calendario")}</span><select id="cr-ano" aria-label="Ano de emissão">
          <option value="">Todos os anos</option></select></label>
        <label class="campo"><span class="ic-campo">${icone("usuario")}</span><select id="cr-vendedor" aria-label="Vendedor do título">
          <option value="">Todos os vendedores</option></select></label>
        <button class="btn btn-limpar" type="button" id="cr-limpar" hidden>${icone("x")}Limpar filtros</button>
      </div>
    </div>
    <div id="cr-conteudo"><div class="grade secao">
      <div class="kpis n3"><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:150px"></div></div>
      <div class="kpis n4"><div class="esqueleto" style="height:190px"></div><div class="esqueleto" style="height:190px"></div><div class="esqueleto" style="height:190px"></div><div class="esqueleto" style="height:190px"></div></div>
      <div class="esqueleto" style="height:360px"></div></div>
    </div>`;

  ligarBusca(container);
  const sel = (id, chave) => container.querySelector(id).addEventListener("change", (e) => {
    estado[chave] = e.target.value ? Number(e.target.value) : null;
    carregar();
  });
  sel("#cr-mes", "mes");
  sel("#cr-ano", "ano");
  sel("#cr-vendedor", "vendedor");
  container.querySelector("#cr-limpar").addEventListener("click", () => {
    Object.assign(estado, { cliente: null, mes: null, ano: null, vendedor: null });
    container.querySelector("#cr-cliente").value = "";
    carregar();
  });
  carregar();
}

export function recarregarCredito() { if (ctx) carregar(true); }

function atualizarUrl() {
  guardar("mv-credito", { c: estado.cliente, m: estado.mes, a: estado.ano, v: estado.vendedor });
  if (!location.hash.startsWith("#/credito")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams();
  if (estado.cliente) p.set("c", estado.cliente.id);
  if (estado.mes) p.set("m", estado.mes);
  if (estado.ano) p.set("a", estado.ano);
  if (estado.vendedor) p.set("v", estado.vendedor);
  history.replaceState(null, "", `#/credito${p.toString() ? "?" + p : ""}`);
  const limpar = document.getElementById("cr-limpar");
  if (limpar) limpar.hidden = !estado.cliente && !estado.mes && !estado.ano && !estado.vendedor;
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("cr-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  sairTelaCheia();
  if (estado.dados) conteudo.classList.add("recarregando");
  atualizarUrl();
  try {
    const p = new URLSearchParams();
    if (estado.cliente) p.set("cliente", estado.cliente.id);
    if (estado.mes) p.set("mes", estado.mes);
    if (estado.ano) p.set("ano", estado.ano);
    if (estado.vendedor) p.set("vendedor", estado.vendedor);
    const d = await api(`/api/credito?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    if (d.cliente) estado.cliente = { id: d.cliente.id, nome: d.cliente.nome };
    atualizarUrl();
    preencherFiltros(d);
    ctx.subtitulo(d);
    conteudo.innerHTML = render(d);
    posRender(conteudo);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 400 && (estado.cliente || estado.ano || estado.vendedor)) {
      // filtro guardado neste navegador que não vale mais (cliente apagado, ano fora dos dados): volta a todos
      Object.assign(estado, { cliente: null, ano: null, vendedor: null });
      document.getElementById("cr-cliente").value = "";
      toast(e.message, "erro");
      return carregar(silencioso);
    }
    const ic = e.status === 403 ? "cadeado" : "alerta";
    const msg = e.status === 403 || e.status === 503 ? esc(e.message) : `Não foi possível carregar: ${esc(e.message)}`;
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone(ic)}<p>${msg}</p></div>`;
    if (!silencioso && e.status !== 403 && e.status !== 503) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
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
  const campo = document.getElementById("cr-cliente");
  if (document.activeElement !== campo) campo.value = d.cliente ? d.cliente.nome : "";
  campo.closest(".campo").classList.toggle("com-filtro", !!d.cliente);
}

// ---------- busca de cliente (no servidor: são milhares) ----------
function ligarBusca(container) {
  const campo = container.querySelector("#cr-cliente");
  const lista = container.querySelector("#cr-sugestoes");
  let achados = [], ativo = -1, espera = null;

  const fechar = () => { lista.hidden = true; campo.setAttribute("aria-expanded", "false"); ativo = -1; };
  const desenhar = (texto) => {
    if (!achados.length) {
      lista.innerHTML = `<p class="multi-vazio">${texto ? "Nenhum cliente com esse nome ou código." : "Digite o nome ou o código do cliente."}</p>`;
    } else {
      lista.innerHTML = achados.map((c, i) => `
        <button type="button" class="multi-op cr-op${i === ativo ? " ativo" : ""}" role="option" aria-selected="${i === ativo}" data-i="${i}">
          <span class="n">${esc(c.nome)}<small>código ${c.id}${c.carteira ? ` · carteira ${esc(c.carteira)}` : ""} · ${c.titulos ? `${fmt.num(c.titulos)} títulos` : "sem títulos"}</small></span>
        </button>`).join("");
    }
    lista.hidden = false;
    campo.setAttribute("aria-expanded", "true");
  };
  const escolher = (c) => {
    estado.cliente = { id: c.id, nome: c.nome };
    campo.value = c.nome;
    fechar();
    campo.blur();
    carregar();
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

  campo.addEventListener("focus", () => campo.select());
  campo.addEventListener("input", () => {
    clearTimeout(espera);
    espera = setTimeout(buscar, 220);
    if (!campo.value.trim() && estado.cliente) { // apagou o nome: volta para todos os clientes
      estado.cliente = null;
      fechar();
      carregar();
    }
  });
  campo.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!achados.length) return;
      e.preventDefault();
      ativo = (ativo + (e.key === "ArrowDown" ? 1 : -1) + achados.length) % achados.length;
      desenhar(campo.value.trim());
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!lista.hidden && achados[ativo]) escolher(achados[ativo]);
    } else if (e.key === "Escape") {
      fechar();
      campo.value = estado.cliente ? estado.cliente.nome : "";
    }
  });
  lista.addEventListener("mousedown", (e) => e.preventDefault()); // não tira o foco do campo antes do clique
  lista.addEventListener("click", (e) => {
    const b = e.target.closest("[data-i]");
    if (b) escolher(achados[Number(b.dataset.i)]);
  });
  campo.addEventListener("blur", () => {
    fechar();
    campo.value = estado.cliente ? estado.cliente.nome : campo.value.trim() ? "" : campo.value;
  });
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

export function textoSubtitulo(d) {
  return `${d.cliente ? d.cliente.nome : "Todos os clientes"} · ${maiuscula(descricaoPeriodo(d.filtros))}`;
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

// ---------- estrutura ----------
function render(d) {
  const k = d.cartoes, c = d.cliente;
  const periodo = descricaoFiltro(d);
  let h = c ? cabecalhoCliente(d) : "";
  h += `<section class="kpis secao n3">
    ${kpiValor(1, "var(--s-fat)", "Valor total das compras", "moeda", k.valor, "moeda", periodo)}
    ${kpiValor(2, "var(--s-out)", "Quantidade de compras", "recibo", k.quantidade, "num", "títulos a receber de venda")}
    ${kpiValor(3, "var(--k-vm)", "Ticket médio", "etiqueta", k.ticket, "moeda", "valor ÷ quantidade de compras")}
  </section>`;
  h += `<section class="kpis secao n4">
    ${kpiPontualidade(4, k)}
    ${c ? kpiValor(5, "var(--k-cli)", "Limite de crédito", "cartao", c.limite, "moeda",
      c.limite > 0 ? "do cadastro do cliente" : "sem limite no cadastro",
      [["Prazo", esc(c.prazo || "não informado")], ["Vendedor da carteira", esc(c.carteira || "sem vendedor")]])
      : kpiSemCliente(5, "var(--k-cli)", "Limite de crédito", "cartao")}
    ${kpiInadimplencia(6, k, periodo)}
    ${c ? kpiRestante(7, c) : kpiSemCliente(7, "var(--s-mus)", "Limite restante", "escudo")}
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

function cabecalhoCliente(d) {
  const c = d.cliente, k = d.cartoes;
  const chips = [];
  if (k.inadimplencia > 0) chips.push(`<span class="status abaixo">${icone("alerta")}Inadimplente</span>`);
  if (c.limite > 0 && c.restante < 0) chips.push(`<span class="status abaixo">${icone("alerta")}Passou do limite</span>`);
  if (!chips.length && c.em_aberto === 0) chips.push(`<span class="status no_ritmo">${icone("certo")}Nada em aberto</span>`);
  return `
  <section class="cartao secao entra cr-cliente" style="--i:1">
    <span class="cr-cliente-icone">${icone("loja")}</span>
    <div class="cr-cliente-nome"><b>${esc(c.nome)}</b>
      <small>código ${c.id}${c.carteira ? ` · carteira de ${esc(c.carteira)}` : ""} · prazo ${esc(c.prazo || "não informado")}</small></div>
    <div class="cr-cliente-chips">${chips.join("")}</div>
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

function kpiRestante(i, c) {
  const passou = c.restante < 0;
  const cor = passou ? "var(--ruim-forte)" : "var(--s-mus)";
  const usado = c.usado ?? (c.em_aberto > 0 ? 1 : 0);
  const escala = Math.max(1, usado);
  const meta = c.limite > 0
    ? (passou ? `<b>passou ${fmt.moeda(-c.restante)}</b> do limite` : `${fmt.pct(c.usado, 0)} do limite em uso`)
    : "sem limite no cadastro";
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    ${cab("Limite restante", "escudo")}</div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor${passou ? " cr-negativo" : ""}" data-contar="${c.restante}" data-fmt="moeda">0</div>
      <div class="kpi-meta">${meta}</div>
      <div class="medidor">
        <div class="medidor-trilho"><span class="enche" data-largura="${(Math.min(usado, escala) / escala) * 100}%"></span>${escala > 1 ? `<span class="alvo" style="left:${(1 / escala) * 100}%"></span>` : ""}</div>
        <div class="medidor-escala"><span>em aberto ${fmt.moeda(c.em_aberto)}</span><span>limite ${fmt.moeda(c.limite)}</span></div>
      </div>
    </div></div>
  </article>`;
}

function tabela(d, i) {
  const t = d.titulos, comCliente = !!d.cliente;
  const sub = t.total > t.mostrando
    ? `Os ${fmt.num(t.mostrando)} mais recentes de ${fmt.num(t.total)} títulos · ${esc(descricaoFiltro(d))}`
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
  const corpo = t.linhas.length ? `
    <div class="tabela-rolagem"><table class="dados cr-titulos">
      <thead><tr><th>Emissão</th><th>Título</th>${comCliente ? "" : `<th class="esq">Cliente</th>`}<th class="esq">Vendedor</th><th>Vencimento</th>
        <th>Quitação</th><th>Valor</th><th>Dias de atraso</th><th>Situação</th></tr></thead>
      <tbody>${t.linhas.map((l, n) => `<tr style="--i:${Math.min(n, 20)}">
        <td>${fmt.data(l.emissao)}</td><td class="fraco">${l.id}</td>
        ${comCliente ? "" : `<td class="cr-nome cr-quebra">${esc(l.cliente || `Cliente cód. ${l.id_cliente}`)}<small>código ${l.id_cliente}</small></td>`}
        <td class="cr-nome">${esc(l.vendedor)}</td>
        <td>${l.vencimento ? fmt.data(l.vencimento) : "—"}</td><td>${l.quitacao ? fmt.data(l.quitacao) : "—"}</td>
        <td>${fmt.moeda2(l.valor)}</td><td>${dias(l)}</td><td>${situacao(l.situacao)}</td>
      </tr>`).join("")}</tbody>
    </table></div>`
    : `<div class="vazio">${icone("recibo")}<p>Nenhum título neste filtro.</p></div>`;
  return `
  <section class="cartao secao entra" style="--i:${i}">
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
          <li><b>Inadimplência:</b> soma dos títulos em aberto vencidos há mais de 7 dias.</li>
          <li><b>Limite restante:</b> limite do cadastro − <b>todos</b> os títulos em aberto do cliente, de qualquer
            emissão e vendedor (no Power BI, com mês e ano escolhidos, só os emitidos no período entravam). Negativo =
            passou do limite. Limite, prazo e restante só aparecem com um cliente escolhido.</li>
          <li><b>Dias de atraso:</b> quitado = quitação − vencimento; em aberto = ${fmt.data(d.hoje)} (o dia da extração dos
            dados) − vencimento. Negativo = antes do vencimento.</li>
        </ol>
      </div>
    </details>
  </section>`;
}
