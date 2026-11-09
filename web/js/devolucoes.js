// Página Devoluções: o que voltou na entrega (o pedido não ficou no cliente) e o vencido e danificado no cliente (o
// produto foi entregue e voltou da loja), cada um com o seu jeito de acompanhar, e o Parecer de Devoluções em PDF. A tela
// não mostra os códigos do ERP (motivo, produto, série da nota): cada causa aparece pelo nome e pela descrição. A conta fica no servidor (bi/devolucoes.py);
// aqui é a apresentação: os cartões com a média dos 6 meses anteriores, o gráfico de 13 meses, as causas com o
// responsável, as notas do mês, os produtos, segmentos e clientes, a tabela dos vendedores (ordenável, vira imagem para o
// WhatsApp) e o bloco de cada vendedor como no Parecer.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast, irParaLogin, MESES } from "./util.js";
import { colunasEmpilhadas } from "./graficos.js";
import { ligarCaptura } from "./relatorio.js";
import { ligarTelaCheia, sairTelaCheia } from "./telacheia.js";

const ABAS = {
  resumo: { titulo: "Resumo", icone: "grafico" },
  entrega: { titulo: "Na entrega", icone: "recibo" },
  cliente: { titulo: "No cliente", icone: "loja" },
  vendedores: { titulo: "Vendedores", icone: "usuario" },
};
const REGIOES = ["BA", "ES", "TERC"];
// As duas famílias (paleta categórica validada, as duas primeiras cores); "outros" no cinza.
const COR = { entrega: "var(--dv-entrega)", cliente: "var(--dv-cliente)", outros: "var(--dv-outros)" };
const CLIENTES_VISIVEIS = 50;
const nomeMes = (m) => MESES[m - 1][0].toUpperCase() + MESES[m - 1].slice(1);
const pct2 = (v) => fmt.pct(v, 2);
const qtd = (v) => fmt.num(v, 2);
const n1 = (v) => fmt.num(v, v != null && Math.abs(v - Math.round(v)) > 0.05 ? 1 : 0); // média por mês: 40,3
const numOuTraco = (v) => (v > 0.004 ? n1(v) : "—");
const valorOuTraco = (v) => (v > 0.004 ? fmt.moeda(v) : "—");
const plural = (n, um, varios) => `${n1(n)} ${Math.abs(n - 1) < 0.05 ? um : varios}`;

let ctx = null;
let ligadoUmaVez = false;
let CAUSA = {};
const estado = {
  aba: "resumo", mes: null, regiao: "", vendedor: "", dados: null, pedido: 0,
  escala: "pct", aberto: null, ordem: { campo: "pct", desc: true }, busca: "", todos: false,
};

export function montarDevolucoes(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const salvo = ler("mv-devolucoes", {});
  estado.aba = ABAS[q.get("aba")] ? q.get("aba") : ABAS[salvo.aba] ? salvo.aba : "resumo";
  estado.mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : null;
  estado.regiao = REGIOES.includes(q.get("r")) ? q.get("r") : "";
  estado.vendedor = /^\d+$/.test(q.get("v") || "") ? q.get("v") : "";
  estado.escala = salvo.escala === "valor" ? "valor" : "pct";
  estado.dados = null;
  estado.aberto = null;
  estado.busca = "";
  estado.todos = false;

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="visoes" role="tablist" aria-label="Devoluções" id="dv-abas">
        <span class="indicador"></span>
        ${Object.entries(ABAS).map(([id, a]) => `<button class="visao" role="tab" data-aba="${id}">${icone(a.icone)}${a.titulo}</button>`).join("")}
      </div>
      <div class="filtros">
        <label class="campo" title="Mês"><span class="ic-campo">${icone("calendario")}</span><select id="dv-mes" aria-label="Mês"></select></label>
        <label class="campo" title="Ano"><span class="ic-campo">${icone("funil")}</span><select id="dv-ano" aria-label="Ano"></select></label>
        <label class="campo" title="Região"><span class="ic-campo">${icone("mapa")}</span><select id="dv-regiao" aria-label="Região"><option value="">Todas as regiões</option></select></label>
        <label class="campo" title="Vendedor"><span class="ic-campo">${icone("usuario")}</span><select id="dv-vendedor" aria-label="Vendedor"><option value="">Todos os vendedores</option></select></label>
        <details class="dv-pdf" id="dv-pdf">
          <summary class="btn" title="O Parecer de Devoluções do mês em PDF, no formato de sempre">${icone("arquivo")}<span>Parecer em PDF</span></summary>
          <div class="dv-pdf-menu" id="dv-pdf-menu" role="menu"></div>
        </details>
      </div>
    </div>
    <div id="dv-avisos"></div>
    <div id="dv-conteudo"><div class="grade secao">
      <div class="kpis n3 dv-kpis">${'<div class="esqueleto" style="height:170px"></div>'.repeat(3)}</div>
      <div class="esqueleto" style="height:380px"></div></div>
    </div>`;

  container.querySelectorAll("[data-aba]").forEach((b) => b.addEventListener("click", () => {
    if (estado.aba === b.dataset.aba) return;
    estado.aba = b.dataset.aba;
    marcarAba();
    carregar();
  }));
  container.querySelector("#dv-ano").addEventListener("change", (e) => {
    const d = estado.dados;
    const doAno = d ? d.meses.filter((m) => m.valor.startsWith(e.target.value)) : [];
    const mesAtual = estado.mes ? estado.mes.slice(5) : "";
    estado.mes = (doAno.find((m) => m.valor.slice(5) === mesAtual) || doAno[0] || {}).valor || null;
    carregar();
  });
  container.querySelector("#dv-mes").addEventListener("change", (e) => { estado.mes = e.target.value; carregar(); });
  container.querySelector("#dv-regiao").addEventListener("change", (e) => { estado.regiao = e.target.value; estado.vendedor = ""; carregar(); });
  container.querySelector("#dv-vendedor").addEventListener("change", (e) => { estado.vendedor = e.target.value; carregar(); });
  container.querySelector("#dv-pdf").addEventListener("toggle", (e) => { // o menu abre para o lado que tem espaço
    const det = e.currentTarget;
    if (det.open) det.classList.toggle("a-direita", det.getBoundingClientRect().left + 340 > window.innerWidth - 12);
  });
  container.querySelector("#dv-pdf-menu").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pdf]");
    if (!b) return;
    container.querySelector("#dv-pdf").open = false;
    baixarPdf({ tipo: b.dataset.pdf, ...(b.dataset.regiao ? { regiao: b.dataset.regiao } : {}) }, b);
  });
  if (!ligadoUmaVez) { // uma vez só, mesmo quando a página é montada de novo
    ligadoUmaVez = true;
    document.addEventListener("click", (e) => { // fecha o menu do PDF ao clicar fora
      const menu = document.getElementById("dv-pdf");
      if (menu && menu.open && !menu.contains(e.target)) menu.open = false;
    });
    window.addEventListener("resize", posicionarIndicador);
  }
  const conteudo = container.querySelector("#dv-conteudo");
  conteudo.addEventListener("click", aoClicar);
  conteudo.addEventListener("change", (e) => {
    if (e.target.id === "dv-vend-bloco") abrirVendedor(Number(e.target.value), false);
  });
  conteudo.addEventListener("input", (e) => {
    if (e.target.id === "dv-busca") { estado.busca = e.target.value; filtrarClientes(); }
  });
  marcarAba();
  carregar();
}

export function recarregarDevolucoes() { if (ctx) carregar(true); }

function marcarAba() {
  document.querySelectorAll("#dv-abas [data-aba]").forEach((b) => {
    b.classList.toggle("ativa", b.dataset.aba === estado.aba);
    b.setAttribute("aria-selected", b.dataset.aba === estado.aba);
  });
  posicionarIndicador();
}

function posicionarIndicador() {
  const ativo = document.querySelector("#dv-abas .visao.ativa");
  const ind = document.querySelector("#dv-abas .indicador");
  if (!ativo || !ind) return;
  const primeira = !ind.style.width;
  if (primeira) ind.style.transition = "none";
  ind.style.transform = `translate(${ativo.offsetLeft}px, ${ativo.offsetTop}px)`;
  ind.style.width = ativo.offsetWidth + "px";
  ind.style.height = ativo.offsetHeight + "px";
  if (primeira) { void ind.offsetWidth; ind.style.transition = ""; }
}

function atualizarUrl() {
  guardar("mv-devolucoes", { aba: estado.aba, escala: estado.escala });
  if (!location.hash.startsWith("#/devolucoes")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams({ aba: estado.aba });
  if (estado.mes) p.set("m", estado.mes);
  if (estado.regiao) p.set("r", estado.regiao);
  if (estado.vendedor) p.set("v", estado.vendedor);
  history.replaceState(null, "", `#/devolucoes?${p}`);
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("dv-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  if (estado.dados) conteudo.classList.add("recarregando");
  sairTelaCheia();
  atualizarUrl();
  try {
    const p = new URLSearchParams({ aba: estado.aba });
    if (estado.mes) p.set("mes", estado.mes);
    if (estado.regiao) p.set("regiao", estado.regiao);
    if (estado.vendedor) p.set("vendedores", estado.vendedor);
    const d = await api(`/api/devolucoes?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    estado.mes = d.mes.valor;
    CAUSA = Object.fromEntries(d.causas.map((c) => [c.id, c]));
    atualizarUrl();
    preencherFiltros(d);
    ctx.subtitulo(d);
    document.getElementById("dv-avisos").innerHTML = (d.avisos || [])
      .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
    conteudo.innerHTML = { resumo: renderResumo, entrega: renderEntrega, cliente: renderCliente, vendedores: renderVendedores }[d.aba](d);
    if (d.aba === "resumo") desenharEvolucao();
    if (d.aba === "vendedores" && estado.aberto != null) abrirVendedor(estado.aberto, false);
    if (d.aba === "cliente") filtrarClientes();
    ligarCaptura(conteudo);
    ligarTelaCheia(conteudo);
    animarContadores(conteudo);
    animarEntradas(conteudo);
    ligarTooltips(conteudo);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 403 && estado.regiao) { // a região guardada não é do acesso
      estado.regiao = "";
      estado.vendedor = "";
      return carregar(silencioso);
    }
    if (e.status === 400 && (estado.mes || estado.vendedor)) { // mês ou vendedor que não vale mais
      estado.mes = null;
      estado.vendedor = "";
      if (!silencioso) toast(e.message, "erro");
      return carregar(silencioso);
    }
    const espera = e.status === 503; // os dados ainda não chegaram do computador da empresa (não é erro)
    const msg = espera ? e.message.charAt(0).toUpperCase() + e.message.slice(1) : e.message;
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone(e.status === 403 ? "cadeado" : espera ? "relogio" : "alerta")}<p>${e.status === 403 || espera ? "" : "Não foi possível carregar: "}${esc(msg)}</p></div>`;
    if (!silencioso && e.status !== 403 && !espera) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
  }
}

function preencherFiltros(d) {
  const anos = [...new Set(d.meses.map((m) => m.valor.slice(0, 4)))];
  const ano = d.mes.valor.slice(0, 4);
  document.getElementById("dv-ano").innerHTML = anos.map((a) => `<option value="${a}"${a === ano ? " selected" : ""}>${a}</option>`).join("");
  document.getElementById("dv-mes").innerHTML = d.meses.filter((m) => m.valor.startsWith(ano))
    .map((m) => `<option value="${m.valor}"${m.valor === d.mes.valor ? " selected" : ""}>${nomeMes(Number(m.valor.slice(5)))}</option>`).join("");
  const reg = document.getElementById("dv-regiao");
  reg.innerHTML = `<option value="">Todas as regiões</option>` + d.regioes
    .map((r) => `<option value="${r.id}"${r.id === d.regiao ? " selected" : ""}>${esc(r.nome)}</option>`).join("");
  reg.closest(".campo").hidden = d.regioes.length < 2;
  const nomesRegiao = Object.fromEntries(d.regioes.map((r) => [r.id, r.nome]));
  const vend = document.getElementById("dv-vendedor");
  const escolhido = d.vendedores[0] != null ? String(d.vendedores[0]) : "";
  vend.innerHTML = `<option value="">Todos os vendedores</option>` + d.vendedores_filtro
    .map((v) => `<option value="${v.id}"${String(v.id) === escolhido ? " selected" : ""}>${esc(v.nome)}${d.regiao ? "" : ` (${esc(nomesRegiao[v.regiao] || v.regiao)})`}</option>`).join("");
  const pdf = [];
  const tem = (r) => d.regioes.some((x) => x.id === r);
  if (tem("BA") || tem("ES")) pdf.push(`<button type="button" role="menuitem" data-pdf="geral">${icone("arquivo")}<span>Documento ${["BA", "ES"].filter(tem).join(" + ")}<small>as regiões e os rankings</small></span></button>`);
  d.regioes.forEach((r) => pdf.push(`<button type="button" role="menuitem" data-pdf="regiao" data-regiao="${r.id}">${icone("mapa")}<span>${r.id === "TERC" ? "Terceirizados" : `Região ${esc(r.nome)}`}<small>os vendedores da região e os rankings</small></span></button>`));
  pdf.push(`<button type="button" role="menuitem" data-pdf="todos">${icone("caixa")}<span>Todos os PDFs (zip)<small>as pastas BA, ES e TERCEIRIZADOS, um PDF por vendedor</small></span></button>`);
  document.getElementById("dv-pdf-menu").innerHTML = `<p class="dv-pdf-dica">Parecer de ${esc(d.mes.rotulo)} · com o seu acesso</p>${pdf.join("")}`;
}

// O PDF (ou o zip) montado agora no servidor, com o acesso de quem baixa.
async function baixarPdf(params, botao) {
  const p = new URLSearchParams({ ...params });
  if (estado.dados) p.set("mes", estado.dados.mes.valor);
  const original = botao ? botao.innerHTML : "";
  if (botao) { botao.disabled = true; botao.classList.add("girando"); }
  toast(params.tipo === "todos" ? "Montando os PDFs do Parecer…" : "Montando o PDF do Parecer…");
  try {
    const r = await fetch(`/api/devolucoes/parecer?${p}`);
    if (r.status === 401) return irParaLogin();
    if (!r.ok) {
      let msg = `erro ${r.status}`;
      try { msg = (await r.json()).erro || msg; } catch { /* sem corpo */ }
      throw new Error(msg);
    }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await r.blob());
    link.download = nomeDoArquivo(r.headers.get("Content-Disposition")) || "Parecer de Devoluções.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    toast("Arquivo salvo em Downloads.");
  } catch (err) {
    toast(err.message, "erro");
  } finally {
    if (botao) { botao.disabled = false; botao.classList.remove("girando"); botao.innerHTML = original; }
  }
}

function nomeDoArquivo(cabecalho) {
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cabecalho || "");
  if (utf8) { try { return decodeURIComponent(utf8[1]); } catch { /* usa o outro */ } }
  return /filename="([^"]+)"/i.exec(cabecalho || "")?.[1];
}

function aoClicar(e) {
  const escala = e.target.closest("[data-escala]");
  if (escala) {
    estado.escala = escala.dataset.escala;
    guardar("mv-devolucoes", { aba: estado.aba, escala: estado.escala });
    document.querySelectorAll("[data-escala]").forEach((b) => b.classList.toggle("ativo", b.dataset.escala === estado.escala));
    desenharEvolucao();
    return;
  }
  const ordem = e.target.closest("[data-ordem]");
  if (ordem) {
    const campo = ordem.dataset.ordem;
    estado.ordem = { campo, desc: estado.ordem.campo === campo ? !estado.ordem.desc : campo !== "nome" };
    const sec = document.getElementById("dv-tabela-vend");
    if (sec && estado.dados?.aba === "vendedores") {
      sec.outerHTML = tabelaVendedores(estado.dados, 0, false);
      ligarCaptura(document.getElementById("dv-tabela-vend"));
      ligarTelaCheia(document.getElementById("dv-conteudo"));
    }
    return;
  }
  if (e.target.closest("[data-todos]")) {
    estado.todos = !estado.todos;
    filtrarClientes();
    return;
  }
  const pdfVend = e.target.closest("[data-pdf-vendedor]");
  if (pdfVend) {
    baixarPdf({ tipo: "vendedor", vendedor: pdfVend.dataset.pdfVendedor }, pdfVend);
    return;
  }
  const linha = e.target.closest("tr[data-vendedor]");
  if (linha) abrirVendedor(Number(linha.dataset.vendedor), true);
}

// ---------- apoio ----------
function kpi({ i, cor, ic, rotulo, valor, contar, formato = "moeda", meta, rodape = [], dica = "" }) {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}"${dica ? ` title="${esc(dica)}"` : ""}>
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${rotulo}</span></div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor"${contar != null ? ` data-contar="${contar}" data-fmt="${formato}"` : ""}>${valor}</div>
      <div class="kpi-meta">${meta}</div>
    </div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

// Devolução que sobe é ruim (vermelho), que cai é bom (verde); sempre com a seta e o texto. modo "pp": a diferença de
// um % em pontos percentuais; "rel": a variação relativa.
function chip(atual, antes, rotulo, modo = "rel") {
  if (atual == null || antes == null) return "";
  const dif = atual - antes;
  const titulo = `Comparado com ${rotulo}`;
  let igual, texto;
  if (modo === "pp") {
    igual = Math.abs(dif) < 5e-5;
    texto = `${fmt.num(Math.abs(dif) * 100, 2)} p.p.`;
  } else {
    igual = antes ? Math.abs(dif / antes) < 0.005 : Math.abs(dif) < 1e-9;
    texto = antes ? fmt.pct(Math.abs(dif / antes), 0) : "novo";
  }
  if (igual) return `<span class="dv-var igual" title="${esc(titulo)}">${icone("menos")}igual</span>`;
  const sobe = dif > 0;
  return `<span class="dv-var ${sobe ? "sobe" : "cai"}" title="${esc(titulo)}">${icone(sobe ? "acima" : "abaixo")}${sobe ? "+" : "−"}${texto}</span>`;
}

const rotuloMedia = (d) => (d.janela_cmp ? `a média de ${d.janela_cmp.rotulo}` : "");
const mediaCurta = (d) => (d.janela_cmp ? `Média ${d.janela_cmp.meses} ${d.janela_cmp.meses === 1 ? "mês" : "meses"}` : "");

function seloSituacao(d) {
  return d.situacao === "final"
    ? `<span class="pr-selo final" title="O mês já fechou">${icone("certo")}Mês fechado</span>`
    : `<span class="pr-selo prevista" title="O mês ainda está em andamento: os valores mudam até o fim dele">${icone("relogio")}Em andamento</span>`;
}

function seloLinha(d) {
  const partes = [d.mes.rotulo];
  if (d.regiao) partes.push(d.regioes.find((r) => r.id === d.regiao)?.nome || d.regiao);
  if (d.vendedores.length) partes.push(d.vendedores_filtro.find((v) => v.id === d.vendedores[0])?.nome || "vendedor escolhido");
  const cmp = d.janela_cmp ? ` · comparado com a média de ${d.janela_cmp.rotulo}` : "";
  return `<div class="dv-selo-linha entra" style="--i:0">${seloSituacao(d)}<span>${esc(partes.join(" · "))}${esc(cmp)}</span></div>`;
}

function ponto(familia) {
  return `<i class="dv-ponto" style="--c:${COR[familia] || COR.outros}" aria-hidden="true"></i>`;
}

function nomeCausa(id) { return CAUSA[id]?.nome || id; }

function tagCausa(id, extra = "") {
  const c = CAUSA[id] || { familia: "outros", nome: id };
  return `<span class="dv-causa-tag">${ponto(c.familia)}${esc(c.nome)}${extra}</span>`;
}

const famNome = (d, id) => d.familias.find((f) => f.id === id)?.nome || id;
const famDescricao = (d, id) => d.familias.find((f) => f.id === id)?.descricao || "";
const minuscula = (t) => (t ? t[0].toLowerCase() + t.slice(1) : t); // depois de dois-pontos, no meio da frase

function regiaoNome(d, id) { return d.regioes.find((r) => r.id === id)?.nome || (id === "TERC" ? "Terceirizados" : id); }

function vazio(ic, texto) { return `<div class="vazio">${icone(ic)}<p>${esc(texto)}</p></div>`; }

function secao(i, ic, titulo, sub, corpo, acoes = "", id = "") {
  return `
  <section class="cartao secao entra" style="--i:${i}"${id ? ` id="${id}"` : ""}>
    <div class="cartao-cab">
      <div><h3>${icone(ic)}${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}</div>${acoes}
    </div>
    ${corpo}
  </section>`;
}

function cliCelula(c) {
  const onde = [c.cidade, c.uf].filter(Boolean).join("/");
  return `${esc(c.nome)}${onde ? ` <small class="fraco">${esc(onde)}</small>` : ""}`;
}

// ---------- Resumo ----------
function renderResumo(d) {
  const a = d.cartoes.atual, m = d.cartoes.media, rot = rotuloMedia(d), curta = mediaCurta(d);
  const cmp = (atual, antes, modo = "pp") => (m ? chip(atual, antes, rot, modo) : "");
  const cartoes = [
    kpi({
      i: 1, cor: "var(--acento)", ic: "devolucao", rotulo: "Índice de devolução", valor: pct2(a.pct),
      meta: `<b>${fmt.moeda(a.total)}</b> voltaram de ${fmt.moedaC(a.venda)} vendidos no mês`,
      rodape: [
        ["Na entrega + vencido e danificado", `${pct2(a.entrega.pct)} + ${pct2(a.cliente.pct)}`],
        ...(m ? [[curta, `${pct2(m.pct)} ${cmp(a.pct, m.pct)}`]] : []),
      ],
    }),
    kpi({
      i: 2, cor: COR.entrega, ic: "recibo", rotulo: esc(famNome(d, "entrega")), valor: pct2(a.entrega.pct), dica: famDescricao(d, "entrega"),
      meta: `<b>${fmt.moeda(a.entrega.valor)}</b> em ${plural(a.entrega.notas, "nota", "notas")} · ${fmt.num(a.entrega.por_100, 2)} a cada 100 entregas`,
      rodape: m ? [[curta, `${pct2(m.entrega.pct)} ${cmp(a.entrega.pct, m.entrega.pct)}`],
        ["Notas por mês na média", `${n1(m.entrega.notas)} ${cmp(a.entrega.notas, m.entrega.notas, "rel")}`]] : [],
    }),
    kpi({
      i: 3, cor: COR.cliente, ic: "loja", rotulo: esc(famNome(d, "cliente")), valor: pct2(a.cliente.pct), dica: famDescricao(d, "cliente"),
      meta: `<b>${fmt.moeda(a.cliente.valor)}</b> em ${plural(a.cliente.clientes, "cliente", "clientes")}: produto que voltou da loja vencido ou danificado`,
      rodape: [
        ["Vencido · danificado", `${fmt.moeda(a.cliente.vencido)} · ${fmt.moeda(a.cliente.danificado)}`],
        ...(m ? [[curta, `${pct2(m.cliente.pct)} ${cmp(a.cliente.pct, m.cliente.pct)}`]] : []),
      ],
    }),
  ].join("");
  const usados = new Set(d.evolucao.flatMap((x) => ["entrega", "cliente", "outros"].filter((k) => x[k] > 0.004)));
  const legenda = `<div class="legenda dv-legenda">${["entrega", "cliente", "outros"].filter((k) => usados.has(k))
    .map((k) => `<span class="item"><span class="quadro" style="--c:${COR[k]}"></span>${esc(d.familias.find((f) => f.id === k)?.nome || k)}</span>`).join("")}</div>`;
  const evolucao = secao(4, "grafico", "Evolução em 13 meses",
    `<span id="dv-evo-sub">${estado.escala === "pct" ? "Em % da venda bruta de cada mês" : "Em R$"}</span>`,
    `${legenda}<div class="grafico dv-evolucao" id="dv-evolucao"></div>`,
    `<div class="seg-mini" role="group" aria-label="Escala do gráfico">
      <button type="button" data-escala="pct" class="${estado.escala === "pct" ? "ativo" : ""}">% da venda</button>
      <button type="button" data-escala="valor" class="${estado.escala === "valor" ? "ativo" : ""}">R$</button>
    </div>`);
  return `${seloLinha(d)}<section class="kpis n3 secao dv-kpis">${cartoes}</section>${evolucao}${porResponsavel(d, 5)}${tabelaRegioes(d, 6)}${metodo(d, 7)}`;
}

function desenharEvolucao() {
  const el = document.getElementById("dv-evolucao");
  const d = estado.dados;
  if (!el || !d || d.aba !== "resumo") return;
  const pct = estado.escala === "pct";
  const sub = document.getElementById("dv-evo-sub");
  if (sub) sub.textContent = pct ? "Em % da venda bruta de cada mês" : "Em R$";
  const ids = ["entrega", "cliente", ...(d.evolucao.some((x) => x.outros > 0.004) ? ["outros"] : [])];
  const series = ids.map((id) => ({ id, nome: d.familias.find((f) => f.id === id)?.nome || id, cor: COR[id] }));
  const valores = d.evolucao.map((x) => Object.fromEntries(ids.map((id) => [id, pct ? (x.venda ? x[id] / x.venda : 0) : x[id]])));
  colunasEmpilhadas(el, {
    meses: d.evolucao.map((x) => x.mes.curto),
    series, valores,
    formato: pct ? pct2 : fmt.moeda,
    eixo: pct ? (v) => fmt.pct(v, v === 0 ? 0 : 1) : fmt.eixo,
    destaque: d.evolucao.length - 1,
    rotulo: "Devoluções por mês: voltou na entrega e vencido e danificado no cliente",
    vazio: "Sem devoluções nestes meses.",
    extra: (i) => {
      const x = d.evolucao[i];
      return `<div class="tt-l"><span>Total</span><b>${pct ? pct2(x.pct) : fmt.moeda(x.total)}</b></div>`
        + `<div class="tt-l"><span>${pct ? "Em R$" : "% da venda"}</span><b>${pct ? fmt.moeda(x.total) : pct2(x.pct)}</b></div>`
        + `<div class="tt-l"><span>Venda bruta</span><b>${fmt.moedaC(x.venda)}</b></div>`
        + `<div class="tt-l"><span>Notas na entrega</span><b>${fmt.num(x.notas)} de ${fmt.num(x.entregas)} entregas</b></div>`
        + (x.brinde > 0.004 ? `<div class="tt-l"><span>Troca por brinde</span><b>${fmt.moeda(x.brinde)}</b></div>` : "");
    },
  });
}

function porResponsavel(d, i) {
  const grupos = d.responsaveis_mes;
  if (!grupos.length) return secao(i, "ranking", "Por que voltou e quem resolve", "", vazio("devolucao", `Nenhuma devolução em ${d.mes.rotulo}.`));
  const rot = rotuloMedia(d);
  const max = Math.max(1, ...grupos.flatMap((g) => g.causas.map((c) => c.valor)));
  const linhas = grupos.map((g) => `
    <div class="dv-resp">
      <div class="dv-resp-cab"><b>${esc(g.nome)}</b>
        <span>${fmt.moeda(g.valor)} · ${pct2(g.pct)} da venda ${d.janela_cmp ? chip(g.pct, g.media_pct, rot, "pp") : ""}</span></div>
      <div class="barras">${g.causas.map((c) => linhaCausa(d, c, max, rot)).join("")}</div>
    </div>`).join("");
  return secao(i, "ranking", "Por que voltou e quem resolve",
    "Cada causa no responsável pela etapa em que a devolução nasceu · a barra mostra o valor do mês, a seta compara o % da venda com a média",
    `<div class="dv-resps">${linhas}</div>`);
}

function linhaCausa(d, c, max, rot) {
  const info = CAUSA[c.id] || { familia: "outros", nome: c.id };
  const conta = info.familia === "entrega" ? plural(c.notas, "nota", "notas") : plural(c.clientes, "cliente", "clientes");
  const tt = `<div class='tt-t'>${esc(info.nome)}</div>`
    + (info.descricao ? `<div class='tt-d'>${esc(info.descricao)}</div>` : "")
    + `<div class='tt-l'><span>No mês</span><b>${fmt.moeda2(c.valor)} · ${pct2(c.pct)} da venda</b></div>`
    + `<div class='tt-l'><span>${info.familia === "entrega" ? "Notas" : "Clientes"}</span><b>${n1(info.familia === "entrega" ? c.notas : c.clientes)}</b></div>`
    + (c.media_valor != null ? `<div class='tt-l'><span>Média por mês</span><b>${fmt.moeda(c.media_valor)} · ${pct2(c.media_pct)} da venda</b></div>` : "");
  return `
    <div class="barra-l dv-causa" data-tt="${esc(tt)}" tabindex="0">
      <span class="nome">${ponto(info.familia)}<span>${esc(info.nome)}</span></span>
      <span class="trilho"><span class="enche" style="--cor:${COR[info.familia]}" data-largura="${(c.valor / max) * 100}%"></span></span>
      <span class="val">${fmt.moeda(c.valor)}<small>${pct2(c.pct)} · ${conta}</small></span>
      <span class="dv-causa-var">${d.janela_cmp ? chip(c.pct, c.media_pct, rot, "rel") : ""}</span>
    </div>`;
}

function tabelaRegioes(d, i) {
  const rs = d.regioes_tabela;
  if (!rs || !rs.length) return "";
  const rot = rotuloMedia(d);
  const cel = (pct, valor) => `${pct2(pct)}<small class="dv-sub-cel">${valorOuTraco(valor)}</small>`;
  const linhas = rs.map((r, k) => {
    const a = r.atual, m = r.media;
    return `<tr style="--i:${k}"><td>${esc(r.id === "TERC" ? "Terceirizados" : `Região ${r.nome}`)}</td>
      <td>${fmt.moedaC(a.venda)}</td>
      <td class="dv-forte">${pct2(a.pct)} ${m ? chip(a.pct, m.pct, rot, "pp") : ""}</td>
      <td class="dv-fraco">${m ? pct2(m.pct) : "—"}</td>
      <td>${cel(a.entrega.pct, a.entrega.valor)}</td>
      <td>${fmt.num(a.entrega.notas)}<small class="dv-sub-cel">${fmt.num(a.entrega.por_100, 2)} / 100</small></td>
      <td>${cel(a.cliente.pct, a.cliente.valor)}</td>
      <td>${cel(a.cliente.pct_vencido, a.cliente.vencido)}</td>
      <td>${fmt.num(a.cliente.clientes_vencido)}<small class="dv-sub-cel">de ${fmt.num(a.compradores)}</small></td></tr>`;
  }).join("");
  return secao(i, "mapa", "Por região", "A mesma divisão do Parecer · o Edir conta na BA",
    `<div class="tabela-rolagem"><table class="dados dv-tabela-dados">
      <thead><tr><th>Região</th><th>Venda bruta</th><th>Índice</th><th>${esc(mediaCurta(d) || "Média")}</th>
        <th>${ponto("entrega")}Na entrega</th><th>${ponto("entrega")}Notas</th><th>${ponto("cliente")}Vencido e danificado</th>
        <th>${ponto("cliente")}Vencido</th><th>${ponto("cliente")}Clientes com vencido</th></tr></thead>
      <tbody>${linhas}</tbody></table></div>`);
}

// ---------- Na entrega ----------
function renderEntrega(d) {
  const a = d.cartoes.atual, m = d.cartoes.media, rot = rotuloMedia(d), curta = mediaCurta(d);
  const e = a.entrega, me = m ? m.entrega : null;
  const lancPct = e.valor ? a.lancamento.valor / e.valor : null;
  const cartoes = [
    kpi({
      i: 1, cor: COR.entrega, ic: "recibo", rotulo: "Notas devolvidas", valor: fmt.num(e.notas), contar: e.notas, formato: "num",
      meta: `<b>${fmt.num(e.por_100, 2)}</b> a cada 100 entregas (${fmt.num(a.entregas)} notas de venda no mês)`,
      rodape: me ? [[curta, `${n1(me.notas)} por mês ${chip(e.notas, me.notas, rot)}`], ["A cada 100 na média", fmt.num(me.por_100, 2)]] : [],
    }),
    kpi({
      i: 2, cor: COR.entrega, ic: "moeda", rotulo: "Valor que voltou", valor: fmt.moeda(0), contar: e.valor,
      meta: `<b>${pct2(e.pct)}</b> da venda bruta do mês`,
      rodape: me ? [[curta, `${pct2(me.pct)} ${chip(e.pct, me.pct, rot, "pp")}`], ["Valor por mês na média", fmt.moeda(me.valor)]] : [],
    }),
    kpi({
      i: 3, cor: "var(--ruim-forte)", ic: "alerta", rotulo: "Erros de lançamento", valor: fmt.num(a.lancamento.notas), contar: a.lancamento.notas, formato: "num",
      meta: `nota${a.lancamento.notas === 1 ? "" : "s"} · <b>${fmt.moeda(a.lancamento.valor)}</b>${lancPct != null ? ` (${fmt.pct(lancPct, 0)} do que voltou)` : ""}`,
      rodape: m ? [[curta, `${n1(m.lancamento.notas)} por mês ${chip(a.lancamento.notas, m.lancamento.notas, rot)}`]] : [],
    }),
    kpi({
      i: 4, cor: COR.entrega, ic: "caixa", rotulo: "Valor médio por nota", valor: fmt.moeda(e.valor_medio || 0),
      meta: `${plural(e.clientes, "cliente", "clientes")} com nota devolvida`,
      rodape: me ? [[curta, `${fmt.moeda(me.valor_medio)} ${chip(e.valor_medio, me.valor_medio, rot)}`]] : [],
    }),
  ].join("");
  return `${seloLinha(d)}<section class="kpis n4 secao dv-kpis">${cartoes}</section>
    ${causasEntrega(d, 5)}${notasDoMes(d, 6)}${vendedoresEntrega(d, 7)}${clientesQueRepetem(d, 8)}${metodo(d, 9)}`;
}

function causasEntrega(d, i) {
  const cs = d.causas_entrega;
  if (!cs.length) return "";
  const rot = rotuloMedia(d), curta = mediaCurta(d);
  const resp = Object.fromEntries(d.responsaveis.map((r) => [r.id, r.nome]));
  const linhas = cs.map((c, k) => `<tr style="--i:${k}">
      <td>${tagCausa(c.id)}</td><td class="esq dv-fraco">${esc(resp[CAUSA[c.id]?.responsavel] || "")}</td>
      <td class="dv-forte">${fmt.num(c.notas)}</td><td>${valorOuTraco(c.valor)}</td><td>${pct2(c.pct)}</td>
      <td>${c.notas ? fmt.moeda(c.valor_medio) : "—"}</td>
      ${d.janela_cmp ? `<td class="dv-fraco">${n1(c.media_notas)}</td><td class="dv-fraco">${fmt.moeda(c.media_valor)}</td><td>${chip(c.pct, c.media_pct, rot, "rel")}</td>` : ""}</tr>`).join("");
  return secao(i, "ranking", "Por causa", "Uma nota com duas causas conta nas duas · a seta compara o % da venda com a média",
    `<div class="tabela-rolagem"><table class="dados dv-tabela-dados">
      <thead><tr><th>Causa</th><th class="esq">Responsável</th><th>Notas</th><th>Valor</th><th>% da venda</th><th>Valor médio</th>
        ${d.janela_cmp ? `<th title="Média de ${esc(d.janela_cmp.rotulo)}">Notas por mês na média</th><th>Valor por mês na média</th><th>Variação</th>` : ""}</tr></thead>
      <tbody>${linhas}</tbody></table></div>`);
}

function notasDoMes(d, i) {
  const ns = d.notas;
  const multi = !d.regiao && d.regioes.length > 1;
  if (!ns.length) return secao(i, "recibo", "As notas do mês", "", vazio("certo", `Nenhuma nota devolvida na entrega em ${d.mes.rotulo}.`));
  const linhas = ns.map((n, k) => {
    const emissao = n.emissao && n.emissao !== n.data ? `<small class="dv-sub-cel">nota de ${fmt.dataCurta(n.emissao)}</small>` : "";
    const numero = n.numero ? esc(n.numero) : "—";
    return `<tr style="--i:${Math.min(k, 30)}">
      <td class="esq">${fmt.dataCurta(String(n.data))}<small class="dv-sub-cel">${fmt.semana(String(n.data))}</small>${emissao}</td>
      <td>${numero}</td>
      <td class="esq dv-cli">${cliCelula(n.cliente)}</td>
      <td class="esq">${esc(n.vendedor)}${multi ? `<small class="dv-sub-cel">${esc(regiaoNome(d, n.regiao))}</small>` : ""}</td>
      <td class="esq">${n.causas.map((c) => tagCausa(c)).join(" ")}</td>
      <td>${fmt.num(n.itens)}</td>
      <td class="dv-forte">${fmt.moeda2(n.valor)}</td></tr>`;
  }).join("");
  const total = ns.reduce((s, n) => s + n.valor, 0);
  return secao(i, "recibo", `As notas do mês · ${fmt.num(ns.length)}`,
    `Cada nota devolvida na entrega em ${esc(d.mes.rotulo)}, da maior para a menor · pela data de entrada${d.notas_reais ? "" : " · sem o número das notas no cache, cada cliente num dia conta como uma nota"}`,
    `<div class="tabela-rolagem"><table class="dados dv-tabela-dados dv-notas">
      <thead><tr><th class="esq">Entrada</th><th>Nota</th><th class="esq">Cliente</th><th class="esq">Vendedor</th><th class="esq">Causa</th><th>Itens</th><th>Valor</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td class="esq">Total</td><td></td><td></td><td></td><td></td><td></td><td>${fmt.moeda2(total)}</td></tr></tfoot></table></div>`);
}

function vendedoresEntrega(d, i) {
  const vs = d.vendedores_entrega;
  if (!vs.length) return "";
  const multi = !d.regiao && d.regioes.length > 1;
  const linhas = vs.map((v, k) => `<tr style="--i:${k}">
      <td>${esc(v.nome)}${multi ? ` <small class="fraco">${esc(regiaoNome(d, v.regiao))}</small>` : ""}</td>
      <td class="dv-forte">${fmt.num(v.notas)}</td><td>${fmt.num(v.entregas)}</td><td class="dv-forte">${v.por_100 == null ? "—" : fmt.num(v.por_100, 2)}</td>
      <td>${fmt.moeda(v.valor)}</td><td>${pct2(v.pct)}</td>
      <td>${v.lancamento_notas ? `${fmt.num(v.lancamento_notas)}<small class="dv-sub-cel">${fmt.moeda(v.lancamento_valor)}</small>` : "—"}</td></tr>`).join("");
  return secao(i, "usuario", "Por vendedor",
    `Quem teve nota devolvida na entrega no mês, pelo valor${d.sem_nota ? ` · outros ${fmt.num(d.sem_nota)} vendedores venderam sem nenhuma` : ""}`,
    `<div class="tabela-rolagem"><table class="dados dv-tabela-dados">
      <thead><tr><th>Vendedor</th><th>Notas devolvidas</th><th>Entregas</th><th>A cada 100</th><th>Valor</th><th>% da venda</th><th>Erros de lançamento</th></tr></thead>
      <tbody>${linhas}</tbody></table></div>`);
}

function clientesQueRepetem(d, i) {
  const rs = d.repetem;
  const meses = d.meses6;
  const janela = meses.length ? `${meses[0].curto} a ${meses[meses.length - 1].curto}` : "";
  if (!rs.length) return secao(i, "relogio", "Clientes que repetem", "", vazio("certo", `Nenhum cliente com duas ou mais notas devolvidas na entrega de ${janela}.`));
  const linhas = rs.map((c, k) => `<tr style="--i:${Math.min(k, 30)}">
      <td class="esq dv-cli">${cliCelula(c)}</td><td class="esq">${esc(c.vendedor)}</td>
      <td class="dv-forte">${fmt.num(c.notas)}</td><td>${fmt.moeda(c.valor)}</td>
      <td class="esq">${c.causas.map((x) => tagCausa(x.id, x.notas > 1 ? ` <b>×${x.notas}</b>` : "")).join(" ")}</td>
      ${c.meses.map((x, j) => `<td class="centro"><span class="dv-marca${x ? " sim-entrega" : ""}" title="${esc(meses[j].rotulo)}: ${x ? "teve nota devolvida" : "sem nota"}">${x ? "●" : "○"}</span></td>`).join("")}
      <td>${fmt.dataCurta(String(c.ultima))}</td></tr>`).join("");
  return secao(i, "relogio", `Clientes que repetem · ${fmt.num(rs.length)}`,
    `Duas ou mais notas devolvidas na entrega de ${esc(janela)}: problema de relação com o cliente, não de um pedido só`,
    `<div class="tabela-rolagem"><table class="dados dv-tabela-dados">
      <thead><tr><th class="esq">Cliente</th><th class="esq">Vendedor</th><th>Notas</th><th>Valor</th><th class="esq">Causas</th>
        ${meses.map((x) => `<th class="centro">${esc(x.curto)}</th>`).join("")}<th>Última</th></tr></thead>
      <tbody>${linhas}</tbody></table></div>`);
}

// ---------- No cliente ----------
function renderCliente(d) {
  const a = d.cartoes.atual, m = d.cartoes.media, rot = rotuloMedia(d), curta = mediaCurta(d);
  const c = a.cliente, mc = m ? m.cliente : null, s6 = d.seis_meses;
  const janela = d.janela6.rotulo;
  const cartoes = [
    kpi({
      i: 1, cor: COR.cliente, ic: "loja", rotulo: "Vencido e danificado", valor: pct2(c.pct), dica: famDescricao(d, "cliente"),
      meta: `<b>${fmt.moeda(c.valor)}</b> no mês · vencido ${fmt.moeda(c.vencido)}, danificado ${fmt.moeda(c.danificado)}`,
      rodape: [...(mc ? [[curta, `${pct2(mc.pct)} ${chip(c.pct, mc.pct, rot, "pp")}`]] : []), ["Trocado por brinde", fmt.moeda(c.brinde)]],
    }),
    kpi({
      i: 2, cor: COR.cliente, ic: "relogio", rotulo: "Vencido", valor: pct2(c.pct_vencido),
      meta: `<b>${fmt.moeda(c.vencido)}</b> em ${plural(c.clientes_vencido, "cliente", "clientes")}`,
      rodape: mc ? [[curta, `${pct2(mc.pct_vencido)} ${chip(c.pct_vencido, mc.pct_vencido, rot, "pp")}`]] : [],
    }),
    kpi({
      i: 3, cor: COR.cliente, ic: "pessoas", rotulo: "Clientes", valor: fmt.num(c.clientes), contar: c.clientes, formato: "num",
      meta: `com vencido ou danificado no mês, de <b>${fmt.num(a.compradores)}</b> atendidos (${fmt.pct(c.pct_clientes, 0)})`,
      rodape: mc ? [[curta, `${n1(mc.clientes)} por mês ${chip(c.clientes, mc.clientes, rot)}`]] : [],
    }),
    kpi({
      i: 4, cor: "var(--ruim-forte)", ic: "alerta", rotulo: "Reincidentes", valor: fmt.num(s6.reincidentes), contar: s6.reincidentes, formato: "num",
      meta: `clientes com vencido em ${s6.minimo_reincidencia} ou mais dos meses de ${esc(janela)}`,
      rodape: s6.metade ? [["Metade do vencido e danificado", `${plural(s6.metade, "cliente", "clientes")}`]] : [],
    }),
  ].join("");
  return `${seloLinha(d)}<section class="kpis n4 secao dv-kpis">${cartoes}</section>
    ${tabelaProdutos(d, 5)}
    <div class="duas-colunas iguais secao">${cortes(d, 6, "segmentos")}${cortes(d, 7, "frequencias")}</div>
    ${danificadoPorOrigem(d, 8)}${tabelaClientes(d, 9)}${metodo(d, 10)}`;
}

function tabelaProdutos(d, i) {
  const ls = d.produtos;
  const janela = d.janela6.rotulo;
  if (!ls.length) return secao(i, "caixa", "Produtos", "", vazio("certo", `Nenhum vencido ou danificado de ${janela}.`));
  const ref = d.seis_meses.pct_vencido;
  const un = (u) => (u ? ` <small class="fraco">${esc(String(u).toLowerCase())}</small>` : "");
  const linhas = ls.map((l) => {
    const prods = l.produtos.map((p, k) => {
      const acima = ref != null && p.pct_venc_qtd6 != null && p.pct_venc_qtd6 > ref * 1.5;
      const origem = Object.entries(p.danificado6_origem || {}).sort((x, y) => y[1] - x[1])
        .map(([c, v]) => `<div class='tt-l'><span>${esc(nomeCausa(c))}</span><b>${fmt.moeda(v)}</b></div>`).join("");
      return `<tr style="--i:${Math.min(k, 30)}">
        <td class="dv-prod">${esc(p.nome)}</td>
        <td>${p.venda_qtd ? `${qtd(p.venda_qtd)}${un(p.unidade)}` : "—"}</td>
        <td>${p.venc_qtd ? `${fmt.pct(p.pct_venc_qtd, 2)}<small class="dv-sub-cel">${qtd(p.venc_qtd)} vencidos</small>` : "—"}</td>
        <td class="${acima ? "dv-acima" : ""}">${p.venc_qtd6 ? `${fmt.pct(p.pct_venc_qtd6, 2)}<small class="dv-sub-cel">${qtd(p.venc_qtd6)} de ${qtd(p.venda_qtd6)}</small>` : "—"}</td>
        <td${origem ? ` data-tt="${esc(`<div class='tt-t'>Danificado, por origem</div>${origem}`)}"` : ""}>${valorOuTraco(p.danificado6)}</td>
        <td class="dv-forte">${fmt.moeda(p.perda6)}</td>
        <td>${pct2(p.pct_perda6)}</td></tr>`;
    }).join("");
    return `<tr class="dv-linha-prod"><td>${esc(l.linha)}</td><td></td><td></td>
      <td title="Na linha, em R$">${pct2(l.pct_venc6)}</td><td></td><td>${fmt.moeda(l.perda6)}</td><td>${pct2(l.pct_perda6)}</td></tr>${prods}`;
  }).join("");
  return secao(i, "caixa", "Produtos",
    `O vencido em quantidade (unidades ou kg) sobre o que foi vendido do produto · ${esc(janela)} para comparar, porque o mês sozinho oscila · em vermelho, os que vencem 50% acima da média (${pct2(ref)} em R$)`,
    `<div class="tabela-rolagem"><table class="dados dv-tabela-dados dv-produtos">
      <thead><tr><th>Linha / produto</th><th>Vendido no mês</th><th>Vencido no mês</th>
        <th>Vencido em 6 meses</th><th>Danificado em 6 meses</th><th>Vencido + danificado em 6 meses</th><th>% da venda em 6 meses</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td>Total</td><td></td><td></td><td>${pct2(d.seis_meses.pct_vencido)}</td><td></td>
        <td>${fmt.moeda(d.seis_meses.perda)}</td><td>${pct2(d.seis_meses.pct_perda)}</td></tr></tfoot></table></div>`);
}

function cortes(d, i, chave) {
  const janela = d.janela6.rotulo;
  if (chave === "frequencias" && d.sem_rede) {
    return secao(i, "calendario", "Vencido por frequência de visita", "", vazio("relogio", "A rede dos clientes ainda não chegou do computador da empresa."));
  }
  const total = d[chave].reduce((s, x) => s + x.venda, 0);
  let lista = d[chave].filter((x) => x.vencido > 0.004 || x.venda >= total * 0.01);
  if (chave === "segmentos") lista = [...lista].sort((x, y) => (x.nome === "Sem segmento") - (y.nome === "Sem segmento") || (y.pct_vencido || 0) - (x.pct_vencido || 0));
  const max = Math.max(1e-9, ...lista.map((x) => x.pct_vencido || 0));
  const barras = lista.map((x) => `
    <div class="barra-l dv-corte" tabindex="0" data-tt="${esc(`<div class='tt-t'>${esc(x.nome)}</div>`
      + `<div class='tt-l'><span>Venda bruta</span><b>${fmt.moedaC(x.venda)}</b></div>`
      + `<div class='tt-l'><span>Vencido</span><b>${fmt.moeda(x.vencido)} · ${pct2(x.pct_vencido)}</b></div>`
      + `<div class='tt-l'><span>Vencido e danificado</span><b>${fmt.moeda(x.perda)} · ${pct2(x.pct_perda)}</b></div>`
      + `<div class='tt-l'><span>Clientes com vencido</span><b>${fmt.num(x.clientes_vencido)} de ${fmt.num(x.compradores)}</b></div>`)}">
      <span class="nome"><span>${esc(x.nome)}</span></span>
      <span class="trilho"><span class="enche" style="--cor:${COR.cliente}" data-largura="${((x.pct_vencido || 0) / max) * 100}%"></span></span>
      <span class="val">${pct2(x.pct_vencido)}<small>${fmt.moedaC(x.venda)} vendidos · ${fmt.num(x.clientes_vencido)} de ${fmt.num(x.compradores)}</small></span>
    </div>`).join("");
  const titulo = chave === "segmentos" ? "Vencido por segmento" : "Vencido por frequência de visita";
  const sub = chave === "segmentos"
    ? `Vencido sobre a venda de ${esc(janela)} · ao lado, os clientes com vencido de quem comprou`
    : `Pela rede do cliente no ERP (semanal, quinzenal, mensal) · ${esc(janela)}: com validade curta, quem compra de longe em longe leva estoque para mais tempo`;
  return secao(i, chave === "segmentos" ? "loja" : "calendario", titulo, sub,
    lista.length ? `<div class="barras dv-cortes">${barras}</div>` : vazio("certo", "Sem venda nestes meses."));
}

function danificadoPorOrigem(d, i) {
  const ds = d.danificados;
  const janela = d.janela6.rotulo;
  const total = ds.reduce((soma, x) => soma + x.valor6, 0);
  if (total <= 0.004) return secao(i, "alerta", "Danificado por origem", "", vazio("certo", `Nenhum produto danificado de ${janela}.`));
  const resp = Object.fromEntries(d.responsaveis.map((r) => [r.id, r.nome]));
  const max = Math.max(...ds.map((x) => x.valor6), 1);
  const dica = {
    danificado_producao: "sinal para a qualidade: veja o lote", danificado_logistica: "manuseio e temperatura no transporte",
    danificado_cliente: "manuseio e exposição na loja", danificado_sem_origem: "a devolução não diz onde aconteceu: vale registrar a origem",
  };
  const linhas = ds.map((x) => `
    <div class="dv-danificado">
      <div class="barra-l dv-causa" tabindex="0" data-tt="${esc(`<div class='tt-t'>${esc(nomeCausa(x.id))}</div><div class='tt-d'>${esc(CAUSA[x.id]?.descricao || "")}</div>`)}">
        <span class="nome">${ponto("cliente")}<span>${esc(nomeCausa(x.id))}<small class="dv-sub-cel">${esc(resp[CAUSA[x.id]?.responsavel] || "")} · ${esc(dica[x.id] || "")}</small></span></span>
        <span class="trilho"><span class="enche" style="--cor:${COR.cliente}" data-largura="${(x.valor6 / max) * 100}%"></span></span>
        <span class="val">${fmt.moeda(x.valor6)}<small>${fmt.moeda(x.valor)} no mês · ${plural(x.clientes6, "cliente", "clientes")}</small></span>
      </div>
      ${x.produtos.length ? `<p class="dv-danificado-prod">${x.produtos.map((pr) => `${esc(pr.nome)} <b>${fmt.moeda(pr.valor)}</b>`).join(" · ")}</p>` : ""}
    </div>`).join("");
  return secao(i, "alerta", "Danificado por origem", `Em ${esc(janela)} · cada origem tem um dono e um remédio diferente`, `<div class="dv-danificados">${linhas}</div>`);
}

function tabelaClientes(d, i) {
  const cs = d.clientes_perda, s6 = d.seis_meses, meses = d.meses6;
  const janela = d.janela6.rotulo;
  if (!cs.length) return secao(i, "pessoas", "Clientes", "", vazio("certo", `Nenhum cliente com vencido ou danificado de ${janela}.`));
  const linhas = cs.map((c, k) => `<tr style="--i:${Math.min(k, 30)}"${k >= CLIENTES_VISIVEIS ? " data-extra" : ""} data-busca="${esc(`${c.nome} ${c.id} ${c.cidade || ""} ${c.vendedor} ${c.segmento} ${c.produto}`.toLowerCase())}">
      <td class="dv-cli">${cliCelula(c)}</td><td class="esq">${esc(c.segmento)}</td><td class="esq">${esc(c.vendedor)}</td>
      <td>${c.compra6 == null ? "—" : fmt.moeda(c.compra6)}</td><td class="dv-forte">${fmt.moeda(c.perda6)}</td>
      <td class="dv-forte">${c.pct6 == null ? "—" : pct2(c.pct6)}</td>
      ${c.meses.map((x, j) => `<td class="centro"><span class="dv-marca${x ? " sim" : ""}" title="${esc(meses[j].rotulo)}: ${x ? "teve vencido" : "sem vencido"}">${x ? "●" : "○"}</span></td>`).join("")}
      <td class="esq">${esc(c.produto)}</td><td>${valorOuTraco(c.perda_mes)}</td></tr>`).join("");
  const resto = d.clientes_fora.n ? ` · outros ${fmt.num(d.clientes_fora.n)} clientes somam ${fmt.moeda(d.clientes_fora.perda6)}` : "";
  const concentracao = s6.metade
    ? `<p class="dv-destaque">${icone("ranking")}<span><b>${plural(s6.metade, "cliente fez", "clientes fizeram")}</b> metade do vencido e danificado de ${esc(janela)} (${fmt.moeda(s6.perda)})${s6.oitenta ? `, e <b>${fmt.num(s6.oitenta)}</b>, 80%` : ""}: é por eles que se começa.</span></p>` : "";
  return secao(i, "pessoas", `Clientes · ${fmt.num(s6.clientes)} com vencido ou danificado`,
    `Vencido e danificado de ${esc(janela)} sobre o que o cliente comprou no período · ● = mês com vencido${resto}`,
    `${concentracao}
    <div class="dv-busca-linha"><label class="campo dv-busca sem-seta" title="Procurar cliente"><span class="ic-campo">${icone("busca")}</span><input id="dv-busca" type="search" placeholder="Procurar cliente, cidade, vendedor ou produto" value="${esc(estado.busca)}"></label><span class="fraco" id="dv-busca-n"></span>
      ${cs.length > CLIENTES_VISIVEIS ? `<button class="btn" type="button" data-todos id="dv-todos"></button>` : ""}</div>
    <div class="tabela-rolagem"><table class="dados dv-tabela-dados dv-clientes" id="dv-ranking">
      <thead><tr><th>Cliente</th><th class="esq">Segmento</th><th class="esq">Vendedor</th><th>Compra em 6 meses</th><th>Vencido e danificado em 6 meses</th><th>% da compra</th>
        ${meses.map((x) => `<th class="centro">${esc(x.curto)}</th>`).join("")}<th class="esq">O que mais volta</th><th>No mês</th></tr></thead>
      <tbody>${linhas}</tbody></table></div>`);
}

function filtrarClientes() {
  const tabela = document.getElementById("dv-ranking");
  if (!tabela) return;
  const termo = estado.busca.trim().toLowerCase();
  let n = 0, total = 0;
  tabela.querySelectorAll("tbody tr").forEach((tr) => {
    total += 1;
    const casa = !termo || tr.dataset.busca.includes(termo);
    const mostra = casa && (termo || estado.todos || !tr.hasAttribute("data-extra"));
    tr.hidden = !mostra;
    if (mostra) n += 1;
  });
  const rot = document.getElementById("dv-busca-n");
  if (rot) rot.textContent = termo ? `${fmt.num(n)} de ${fmt.num(total)}` : "";
  const todos = document.getElementById("dv-todos");
  if (todos) {
    todos.hidden = !!termo;
    todos.textContent = estado.todos ? `Mostrar só os ${CLIENTES_VISIVEIS} primeiros` : `Mostrar os ${fmt.num(total)}`;
  }
}

// ---------- Vendedores ----------
function colunasVendedores() {
  return [
    { id: "nome", rotulo: "Vendedor", val: (v) => v.nome, texto: true },
    { id: "venda", rotulo: "Venda bruta", val: (v) => v.venda, f: fmt.moeda },
    { id: "pct", rotulo: "Índice", val: (v) => v.pct, f: pct2, forte: true },
    { id: "media_pct", rotulo: "Média 6 meses", val: (v) => v.media_pct, f: pct2, fraco: true },
    { id: "pct_entrega", rotulo: "% da venda", val: (v) => v.pct_entrega, f: pct2, familia: "entrega" },
    { id: "notas", rotulo: "Notas", val: (v) => v.notas, f: numOuTraco, familia: "entrega" },
    { id: "lancamento_notas", rotulo: "Erros de lançamento", val: (v) => v.lancamento_notas, f: numOuTraco, familia: "entrega" },
    { id: "pct_cliente", rotulo: "% da venda", val: (v) => v.pct_cliente, f: pct2, familia: "cliente" },
    { id: "pct_vencido", rotulo: "Vencido", val: (v) => v.pct_vencido, f: pct2, familia: "cliente" },
    { id: "clientes_vencido", rotulo: "Clientes com vencido", val: (v) => v.clientes_vencido, f: numOuTraco, familia: "cliente" },
    { id: "reincidentes", rotulo: "Reincidentes", val: (v) => v.reincidentes, f: numOuTraco, familia: "cliente" },
  ];
}

function renderVendedores(d) {
  if (!d.tabela.vendedores.length) {
    return `${seloLinha(d)}<section class="cartao secao vazio entra" style="--i:1">${icone("usuario")}<p>Nenhum vendedor do seu acesso vendeu ou teve devolução em ${esc(d.mes.rotulo)}.</p></section>${metodo(d, 2)}`;
  }
  return `${seloLinha(d)}${tabelaVendedores(d, 1)}<div id="dv-bloco"></div>${metodo(d, 3)}`;
}

function celulaVendedor(c, v) {
  const x = c.val(v);
  const classe = [c.texto ? "rotulo" : "", c.forte ? "dv-forte" : "", c.fraco ? "dv-fraco" : ""].filter(Boolean).join(" ");
  return `<td${classe ? ` class="${classe}"` : ""}>${c.texto ? esc(x) : c.f(x)}</td>`;
}

function tabelaVendedores(d, i, entrar = true) {
  const t = d.tabela, cols = colunasVendedores();
  const { campo, desc } = estado.ordem;
  const col = cols.find((c) => c.id === campo) || cols[2];
  const ordenar = (lista) => [...lista].sort((a, b) => {
    if ((a.id == null) !== (b.id == null)) return a.id == null ? 1 : -1; // "Outros sem devolução" fica no fim
    const x = col.val(a), y = col.val(b);
    if (col.texto) return desc ? String(y).localeCompare(String(x)) : String(x).localeCompare(String(y));
    const nx = x == null ? -Infinity : x, ny = y == null ? -Infinity : y;
    return desc ? ny - nx : nx - ny;
  });
  const grupos = `<tr class="dv-grupos"><th colspan="4"></th>
    <th colspan="3" style="--c:${COR.entrega}"><span class="dv-grupo">${esc(d.familias.find((f) => f.id === "entrega")?.nome || "")}</span></th>
    <th colspan="4" style="--c:${COR.cliente}"><span class="dv-grupo">${esc(d.familias.find((f) => f.id === "cliente")?.nome || "")}</span></th></tr>`;
  const cab = cols.map((c) => {
    const ativo = c.id === col.id;
    const sort = ativo ? (desc ? "descending" : "ascending") : "none";
    return `<th aria-sort="${sort}"><button type="button" class="dv-ordem${ativo ? " ativo" : ""}" data-ordem="${c.id}" title="Ordenar por ${esc(c.rotulo)}">${esc(c.rotulo)}${ativo ? `<span class="dv-seta">${desc ? "▼" : "▲"}</span>` : ""}</button></th>`;
  }).join("");
  const subtotal = (r, nome, classe = "dv-subtotal") => `<tr class="${classe}"><td class="rotulo">${esc(nome)}</td>${cols.slice(1).map((c) => `<td>${c.f(c.val(r))}</td>`).join("")}</tr>`;
  const corpo = t.regioes.map((r) => {
    const vs = ordenar(t.vendedores.filter((v) => v.regiao === r.id));
    const linhas = vs.map((v, k) => (v.id == null
      ? `<tr style="--i:${k}" class="dv-agrupado" title="${esc(v.agrupados.join(", "))}">${cols.map((c) => celulaVendedor(c, v)).join("")}</tr>`
      : `<tr style="--i:${k}" data-vendedor="${v.id}" title="Ver o bloco de ${esc(v.nome)} no Parecer">${cols.map((c) => celulaVendedor(c, v)).join("")}</tr>`)).join("");
    return `<tr class="dv-regiao"><td class="rotulo" colspan="${cols.length}">${esc(r.id === "TERC" ? "Terceirizados" : `Região ${r.nome}`)} · ${r.vendedores} vendedor${r.vendedores === 1 ? "" : "es"}</td></tr>${linhas}${t.regioes.length > 1 ? subtotal(r, `Total ${r.nome}`) : ""}`;
  }).join("");
  const conteudo = `
    <div class="relatorio-cab">
      <img src="/img/logo-maisvida.png" alt="Mais Vida">
      <div>
        <div class="rt">Devoluções por vendedor · ${esc(d.mes.rotulo)}</div>
        <div class="rs">${d.situacao === "final" ? "Mês fechado" : "Mês em andamento"} · dados até ${fmt.semana(d.data_ref)}, ${fmt.data(d.data_ref)} · % sobre a venda bruta${d.janela_cmp ? ` · média de ${esc(d.janela_cmp.rotulo)}` : ""}</div>
      </div>
    </div>
    <table class="relatorio-tabela dv-tabela">
      <thead>${grupos}<tr>${cab}</tr></thead>
      <tbody>${corpo}</tbody>
      <tfoot>${subtotal(t.total, "Total", "")}</tfoot>
    </table>`;
  const arquivo = `devolucoes-vendedores-${d.mes.valor}`;
  return `
  <section class="cartao secao${entrar ? " entra" : ""}" style="--i:${i}" id="dv-tabela-vend">
    <div class="cartao-cab">
      <div><h3>${icone("usuario")}Vendedores</h3>
        <p class="sub">Pelo vendedor da devolução ou do brinde · reincidentes = clientes com vencido em 3 ou mais dos 6 meses até ${esc(d.mes.curto)} · clique no cabeçalho para ordenar e num vendedor para ver o bloco dele no Parecer</p></div>
      <div class="acoes-relatorio">
        <button class="btn" data-captura="copiar" data-arquivo="${arquivo}" title="Copia a tabela como imagem para colar no WhatsApp">${icone("disco")}Copiar imagem</button>
        <button class="btn icone" data-captura="baixar" data-arquivo="${arquivo}" title="Baixar a tabela como imagem (PNG)">${icone("abaixo")}</button>
      </div>
    </div>
    <div class="tabela-rolagem relatorio-rolagem"><div class="relatorio">${conteudo}</div></div>
  </section>`;
}

function abrirVendedor(id, rolar) {
  const d = estado.dados;
  const alvo = document.getElementById("dv-bloco");
  if (!d || d.aba !== "vendedores" || !alvo) return;
  estado.aberto = id;
  const blocos = d.parecer.regioes.flatMap((r) => r.vendedores.map((b) => ({ ...b, regiao_nome: r.nome })));
  const b = blocos.find((x) => x.id === id);
  const v = d.tabela.vendedores.find((x) => x.id === id);
  const opcoes = blocos.map((x) => `<option value="${x.id}"${x.id === id ? " selected" : ""}>${esc(x.nome)}</option>`).join("");
  const corpo = b
    ? b.secoes.map(secaoParecer).join("")
    : vazio("devolucao", `${v ? v.nome : "Este vendedor"} não tem devolução nas seções do Parecer em ${d.mes.rotulo}${v && v.notas > 0 ? " (só erros de faturamento, expedição, logística ou falta de mercadoria, que não entram no Parecer)" : ""}.`);
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:0" id="dv-bloco-cartao">
    <div class="cartao-cab">
      <div><h3>${icone("recibo")}Parecer · ${esc(b ? b.nome : v ? v.nome : "")}</h3>
        <p class="sub">${b ? `${esc(b.regiao_nome === "Terceirizados" ? "Terceirizados" : `Região ${b.regiao_nome}`)} · ` : ""}o bloco do vendedor como sai no PDF: clientes abaixo do limite de volume do produto não aparecem nas tabelas por produto</p></div>
      <div class="dv-bloco-acoes">
        ${blocos.length ? `<label class="campo" title="Vendedor"><span class="ic-campo">${icone("usuario")}</span><select id="dv-vend-bloco" aria-label="Vendedor do Parecer">${b ? "" : `<option value="${id}" selected>${esc(v ? v.nome : "—")}</option>`}${opcoes}</select></label>` : ""}
        ${b ? `<button class="btn primario" type="button" data-pdf-vendedor="${b.id}" title="O Parecer deste vendedor em PDF (com os rankings)">${icone("arquivo")}<span>PDF do vendedor</span></button>` : ""}
      </div>
    </div>
    <div class="dv-parecer">${corpo}</div>
  </section>`;
  ligarTelaCheia(alvo);
  if (rolar) alvo.scrollIntoView({ behavior: "smooth", block: "start" });
}

function tabelaParecer(cab, linhas, alinhar) {
  return `<div class="tabela-rolagem dv-parecer-rolagem"><table class="dv-parecer-tabela">
    <thead><tr>${cab.map((c, k) => `<th class="${alinhar[k]}">${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${linhas.map(([cels, estilo]) => `<tr${estilo ? ` class="${estilo}"` : ""}>${cels.map((c, k) => `<td class="${alinhar[k]}">${c}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

function secaoParecer(s) {
  let h = `<h4 class="dv-p-secao">${esc(s.titulo)}</h4>`;
  if (s.tipo === "simples") {
    if (s.chave === "lancamento") h += `<p class="dv-p-erros">Erros de lançamento cometidos no mês: ${s.erros}</p>`;
    const linhas = s.linhas.map((r) => [[esc(r.cliente), qtd(r.qtd), fmt.moeda2(r.valor).replace("R$ ", "")], null]);
    linhas.push([["TOTAL", qtd(s.total.qtd), fmt.moeda2(s.total.valor).replace("R$ ", "")], "total"]);
    return h + tabelaParecer(["Cliente", "Qtd", "Valor (R$)"], linhas, ["esq", "dir", "dir"]);
  }
  const al = ["esq", "dir", "dir", "dir", "dir"];
  s.produtos.forEach((p) => {
    h += `<h5 class="dv-p-produto">${esc(p.nome)}${p.abaixo ? ` <small title="Clientes com volume abaixo do limite de ${fmt.num(p.limite)} do produto">+${p.abaixo} abaixo do limite</small>` : ""}</h5>`;
    const linhas = p.linhas.map((r) => [[esc(r.cliente), qtd(r.qtd), fmt.moeda2(r.valor).replace("R$ ", ""), r.fat == null ? "—" : fmt.moeda2(r.fat).replace("R$ ", ""), pct2(r.pct)], null]);
    linhas.push([["Total do produto", qtd(p.total.qtd), fmt.moeda2(p.total.valor).replace("R$ ", ""), "—", "—"], "total"]);
    h += tabelaParecer(["Cliente", "Qtd", "Valor (R$)", "Fat. Bruto (R$)", "% Devol."], linhas, al);
  });
  if (s.alerta && s.alerta.length) {
    h += `<h5 class="dv-p-produto">Clientes em Alerta (Vencimento)</h5>`;
    h += tabelaParecer(["Cliente", "Volume", "Valor (R$)", "Fat. Bruto (R$)", "% Devol."],
      s.alerta.map((r) => [[esc(r.cliente), qtd(r.volume), fmt.moeda2(r.valor).replace("R$ ", ""), r.fat == null ? "—" : fmt.moeda2(r.fat).replace("R$ ", ""), pct2(r.pct)], "alerta"]), al);
  }
  return h;
}

// ---------- como é calculado ----------
function metodo(d, i) {
  const resp = Object.fromEntries(d.responsaveis.map((r) => [r.id, r.nome]));
  const causas = d.causas.filter((c) => c.id !== "outros");
  const lista = (fam) => causas.filter((c) => c.familia === fam)
    .map((c) => `<li>${ponto(fam)}<span><b>${esc(c.nome)}</b> · ${esc(resp[c.responsavel] || "")}<small class="dv-sub-cel">${esc(c.descricao || "")}</small></span></li>`).join("");
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como é calculado</h3>
        <span class="sub">Os dois tipos de devolução, as causas e quem resolve cada uma, e as regras da página e do Parecer</span>
      </summary>
      <div class="metodo-corpo">
        <p>Devolução não é um número só. <b>${esc(famNome(d, "entrega"))}</b>: ${esc(minuscula(famDescricao(d, "entrega")))} São
          poucas notas, de valor alto, quase sempre a nota inteira, e se olha nota a nota. <b>${esc(famNome(d, "cliente"))}</b>:
          ${esc(minuscula(famDescricao(d, "cliente")))} São muitos casos pequenos, todo mês, e se olha pelo índice sobre a venda
          (produto, segmento, frequência de visita, cliente).</p>
        <div class="duas-colunas iguais">
          <div><h4>${ponto("entrega")}${esc(famNome(d, "entrega"))}</h4><ul class="dv-metodo-causas">${lista("entrega")}</ul></div>
          <div><h4>${ponto("cliente")}${esc(famNome(d, "cliente"))}</h4><ul class="dv-metodo-causas">${lista("cliente")}</ul></div>
        </div>
        <ol class="metodo-passos">
          <li><b>O que entra:</b> as devoluções não canceladas de cliente do cadastro, pela data de entrada e pelo vendedor da
            devolução, e as trocas por brinde de produto vencido ou danificado. Funcionário, fornecedor e produtor ficam fora,
            e brinde de outro tipo (degustação, doação, contrato, transferência) não é devolução. Um motivo novo no ERP
            aparece em "Outros motivos", com aviso.</li>
          <li><b>Notas:</b> cada nota de devolução conta uma vez, mesmo com vários produtos; uma nota com duas causas aparece
            nas duas. Entregas são as notas de venda do mês.${d.notas_reais ? "" : " Enquanto o número das notas não chega do computador da empresa, cada cliente num dia conta como uma nota."}</li>
          <li><b>% da venda:</b> sobre a venda bruta do mesmo recorte (vendas não canceladas a cliente, pelo vendedor da venda,
            sem descontar nada).</li>
          <li><b>Comparação:</b> a média dos 6 meses anteriores${d.janela_cmp ? ` (${esc(d.janela_cmp.rotulo)})` : ""}. O % é o
            total dos meses sobre a venda dos meses; notas, valores e clientes são a média por mês.</li>
          <li><b>6 meses até o mês:</b> produto, segmento, frequência de visita, clientes e reincidência usam ${d.janela6 ? esc(d.janela6.rotulo) : "os 6 meses até o escolhido"},
            porque o mês sozinho oscila. Reincidente é o cliente com vencido em 3 ou mais desses meses.</li>
          <li><b>Troca por brinde:</b> o ERP só registra o motivo no brinde desde abril de 2026; antes disso, o vencido e
            danificado no cliente aparece menor do que foi.</li>
          <li><b>Região:</b> pela equipe do vendedor (o Edir é da BA); quem não tem equipe é Terceirizado e só aparece para
            quem vê todos os vendedores.</li>
          <li>As causas e as regras são da própria página: o que se configura para Metas (motivos que descontam, canceladas,
            produtos equivalentes) não muda nenhum número daqui.</li>
        </ol>
        <h4>O Parecer em PDF</h4>
        <ul class="metodo-passos">
          <li>Só os vendedores com devolução, nas seções do Parecer: cliente ausente, erro de lançamento, recusa, vencido,
            danificado e os tipos adicionais. Faturamento, expedição, logística e falta de mercadoria aparecem na página, mas
            não no Parecer.</li>
          <li>Erros de lançamento no Parecer: cada combinação de data e cliente conta um, como no documento de sempre.</li>
          <li>Nas seções por produto, cada produto tem um limite de volume (15 para bebida láctea, manteiga e requeijão, 1
            para mussarela…): cliente abaixo do limite não aparece na tabela, mas conta nos totais e nos rankings. Os sabores
            de bebida láctea somam por tamanho.</li>
          <li>Clientes em alerta: vencido ≥ 20% das compras do mês e volume ≥ 30, ou volume ≥ 100.</li>
          <li>Todo PDF termina com os rankings por tipo, com o acesso de quem baixa.</li>
        </ul>
      </div>
    </details>
  </section>`;
}
