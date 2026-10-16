// "Detalhamento por vendedor" no mesmo formato das matrizes do Power BI (indicadores nas linhas, vendedores
// nas colunas, Total no fim), pronto para virar imagem e ser enviado no WhatsApp. Em Outras Linhas ES, a
// tabela "Dentro da meta?" é um cartão à parte, com a própria imagem (vai separada no WhatsApp).
import { esc, fmt, icone, toast, STATUS } from "./util.js";

const NF2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const NF0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const FORMATOS = {
  moeda: (v) => "R$ " + NF2.format(v),
  pct: (v) => NF2.format(v * 100) + "%",
  int: (v) => NF0.format(Math.round(v)),
};
const vazio = (v) => v == null || isNaN(v) || Math.abs(v) < 0.005;

function cabecalho(d, titulo) {
  const c = d.calendario;
  const ritmo = c.situacao === "fechado" ? (c.meses.length > 1 ? "período fechado" : "mês fechado")
    : `${fmt.dias(c.dias_decorridos)} de ${fmt.dias(c.dias_uteis)} dias úteis · ritmo esperado ${fmt.pct(c.ritmo)}`;
  return `
    <div class="relatorio-cab">
      <img src="/img/logo-maisvida.png" alt="Mais Vida">
      <div>
        <div class="rt">${esc(titulo)} · ${esc(d.periodo.rotulo)}</div>
        <div class="rs">Dados até ${fmt.semana(d.data_ref)}, ${fmt.data(d.data_ref)} · ${ritmo}</div>
      </div>
      <div class="rl">${["no_ritmo", "atencao", "abaixo"].map((s) => `<span><span class="ponto-status ${s}"></span>${STATUS[s].rotulo}</span>`).join("")}</div>
    </div>`;
}

function cartao(d, i, titulo, sub, corpo, arquivo, ic = "ranking") {
  return `
  <section class="cartao secao entra" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone(ic)}${esc(titulo)}</h3><p class="sub">${sub}</p></div>
      <div class="acoes-relatorio">
        <button class="btn" data-captura="copiar" data-arquivo="${esc(arquivo)}" title="Copia a tabela como imagem para colar no WhatsApp">${icone("disco")}Copiar imagem</button>
        <button class="btn icone" data-captura="baixar" data-arquivo="${esc(arquivo)}" title="Baixar a tabela como imagem (PNG)">${icone("abaixo")}</button>
      </div>
    </div>
    <div class="tabela-rolagem relatorio-rolagem"><div class="relatorio">${corpo}</div></div>
  </section>`;
}

// ---------- visões por vendedor (Metas ES, BA, Edir, Outras Linhas ES) ----------
function linhasDoRelatorio(d) {
  const tipo = d.visao.tipo;
  const R = (rotulo, estilo, valor, formato, extra = {}) => ({ rotulo, estilo, valor, formato, ...extra });
  const pct = (k) => (c) => (vazio(c[k].realizado) ? null : c[k].pct);
  const st = (k) => (c) => c[k].status;
  const cats = d.categorias.lista.map((cat) => R(cat, "cat", (c) => c.categorias[cat], "moeda", { ocultaZero: true }));
  const fat = [
    R("Meta Faturamento", "meta", (c) => c.faturamento.meta, "moeda"),
    R("Faturamento Realizado", "real", (c) => c.faturamento.realizado, "moeda", { ocultaZero: true }),
    R("% Meta Faturamento Realizada", "pct", pct("faturamento"), "pct", { status: st("faturamento") }),
  ];
  const vm = [
    R("Meta Venda Média", "meta", (c) => c.venda_media.meta, "moeda"),
    R("Meta Venda Média Realizada", "real", (c) => c.venda_media.realizado, "moeda", { ocultaZero: true }),
  ];
  const cli = [
    R("Meta Clientes", "meta", (c) => c.clientes.meta, "int"),
    R("Meta Realizada Clientes", "real", (c) => c.clientes.realizado, "int", { ocultaZero: true }),
    R("% Meta Clientes Realizada", "pct", pct("clientes"), "pct", { status: st("clientes") }),
  ];
  const out = [
    R("Meta Outras Linhas", "meta", (c) => c.outras.meta, "moeda"),
    R("Meta Realizada Outras Linhas", "real", (c) => c.outras.realizado, "moeda", { ocultaZero: true }),
    R("% Meta Outras Linhas Realizada", "pct", pct("outras"), "pct", { status: st("outras") }),
  ];
  if (tipo === "completa") {
    return [
      ...fat,
      R("Meta Mussarela", "meta", (c) => c.mussarela.meta, "moeda"),
      R("Meta Realizada Mussarela", "real", (c) => c.mussarela.realizado, "moeda", { ocultaZero: true }),
      R("% Meta Mussarela Realizada", "pct", pct("mussarela"), "pct", { status: st("mussarela") }),
      ...out, ...cats, ...vm, ...cli,
    ];
  }
  if (tipo === "outras") {
    return [...out, R("Meta Restante Outras Linhas", "real", (c) => c.outras.meta - c.outras.realizado, "moeda"), ...cats];
  }
  return [...fat, ...vm, ...cli];
}

export function relatorioVendedores(d, i) {
  const colunas = [...d.linhas].sort((a, b) => a.nome_planilha.localeCompare(b.nome_planilha, "pt-BR"));
  const total = {
    faturamento: d.indicadores.faturamento, mussarela: d.indicadores.mussarela, outras: d.indicadores.outras,
    clientes: d.indicadores.clientes, venda_media: d.indicadores.venda_media, categorias: d.categorias.total,
  };
  const celula = (r, c) => {
    const v = r.valor(c);
    if (vazio(v) && (r.ocultaZero || r.estilo === "pct" || r.estilo === "cat")) return "";
    if (v == null) return "";
    const ponto = r.status ? `<span class="ponto-status ${r.status(c)}"></span>` : "";
    return ponto + FORMATOS[r.formato](v);
  };
  const linhas = linhasDoRelatorio(d);
  const tabela = `
    <table class="relatorio-tabela">
      <thead><tr><th></th>${colunas.map((c) => `<th data-vendedor="${c.id}" title="Filtrar por ${esc(c.nome)}">${esc(c.nome_planilha)}</th>`).join("")}<th class="total">Total</th></tr></thead>
      <tbody>${linhas.map((r) => `<tr class="${r.estilo}">
        <td class="rotulo">${esc(r.rotulo)}</td>${colunas.map((c) => `<td>${celula(r, c)}</td>`).join("")}<td class="total">${celula(r, total)}</td>
      </tr>`).join("")}</tbody>
    </table>`;
  const sub = "Mesmo formato da matriz do Power BI · clique no nome do vendedor para filtrar";
  let h = cartao(d, i, "Detalhamento por vendedor", sub, cabecalho(d, d.visao.titulo) + tabela, `metas-${d.visao.id}-${d.periodo.arquivo}`);
  if (d.visao.tipo === "outras") {
    h += cartao(d, i + 1, "Dentro da meta?", "Quanto falta de outras linhas para cada vendedor e quem está dentro da meta",
      cabecalho(d, `${d.visao.titulo} · Dentro da meta`) + tabelaDentroDaMeta(colunas),
      `metas-${d.visao.id}-dentro-da-meta-${d.periodo.arquivo}`, "estrela");
  }
  return h;
}

function tabelaDentroDaMeta(colunas) {
  return `
    <table class="relatorio-tabela dentro">
      <thead><tr><th>Vendedor</th><th>Falta Outras Linhas</th><th>Dentro da meta?</th></tr></thead>
      <tbody>${colunas.map((c) => {
        const falta = c.outras.meta - c.outras.realizado;
        const dentro = ["batida", "no_ritmo"].includes(c.outras.status);
        return `<tr><td class="rotulo">${esc(c.nome_planilha)}</td><td>${FORMATOS.moeda(falta)}</td>
          <td class="msg">${dentro ? `<span class="parabens">${icone("estrela")}Parabéns, dentro da meta!</span>` : ""}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
}

// ---------- Produtos BA (Meta e Realizado por vendedor) ----------
export function relatorioProdutos(d, i) {
  const cols = d.colunas.map((c) => ({ ...c, rotulo: c.nome_erp || c.nome }));
  const comTotal = cols.length > 1;
  const produtos = [...d.produtos].sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  const par = (c, cls = "") => {
    if (!c) return `<td class="m ${cls}"></td><td class="${cls}"></td>`;
    const meta = c.meta || c.meta === 0 ? FORMATOS.int(c.meta) : "";
    const real = vazio(c.realizado) ? "" : `<span class="ponto-status ${c.meta ? c.status : "sem_meta"}"></span>${FORMATOS.int(c.realizado)}`;
    return `<td class="m ${cls}">${meta}</td><td class="${cls}">${real}</td>`;
  };
  const tabela = `
    <table class="relatorio-tabela produtos">
      <thead>
        <tr><th rowspan="2" class="prod-cab">Produto</th>${cols.map((c) => `<th colspan="2" class="grupo" data-vendedor="${c.id}" title="Filtrar por ${esc(c.nome)}">${esc(c.rotulo)}</th>`).join("")}${comTotal ? `<th colspan="2" class="grupo total">Total</th>` : ""}</tr>
        <tr>${cols.map(() => `<th class="sub">Meta</th><th class="sub">Realizado</th>`).join("")}${comTotal ? `<th class="sub total">Meta</th><th class="sub total">Realizado</th>` : ""}</tr>
      </thead>
      <tbody>${produtos.map((p) => `<tr>
        <td class="rotulo produto">${esc(p.nome)}</td>${cols.map((c) => par(p.por_vendedor[String(c.id)])).join("")}${comTotal ? par(p.tem_meta ? p.total : { ...p.total, meta: null }, "total") : ""}
      </tr>`).join("")}</tbody>
    </table>`;
  const corpo = cabecalho(d, "Metas Produtos BA") + tabela;
  const sub = "Mesmo formato da matriz do Power BI: meta de volume e volume vendido (líquido das devoluções que descontam)";
  return cartao(d, i, "Metas de volume por produto", sub, corpo, `metas-produtos-ba-${d.periodo.arquivo}`);
}

// ---------- imagem para o WhatsApp ----------
let carregando = null;
function carregarBiblioteca() {
  if (window.htmlToImage) return Promise.resolve(window.htmlToImage);
  if (!carregando) {
    carregando = new Promise((ok, falha) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js";
      s.onload = () => ok(window.htmlToImage);
      s.onerror = () => { carregando = null; falha(new Error("sem internet para gerar a imagem")); };
      document.head.appendChild(s);
    });
  }
  return carregando;
}

async function gerarPng(el) {
  const lib = await carregarBiblioteca();
  const fundo = getComputedStyle(document.body).getPropertyValue("--surface").trim() || "#ffffff";
  const opcoes = { pixelRatio: 2, backgroundColor: fundo, cacheBust: true, width: el.scrollWidth, height: el.scrollHeight };
  try {
    return await lib.toBlob(el, opcoes);
  } catch {
    return await lib.toBlob(el, { ...opcoes, skipFonts: true });
  }
}

export function ligarCaptura(raiz) {
  raiz.querySelectorAll("[data-captura]").forEach((btn) => btn.addEventListener("click", async () => {
    const alvo = btn.closest(".cartao").querySelector(".relatorio");
    const original = btn.innerHTML;
    btn.disabled = true;
    if (btn.dataset.captura === "copiar") btn.innerHTML = `${icone("atualizar")}Gerando…`;
    alvo.classList.add("capturando");
    try {
      const blob = await gerarPng(alvo);
      if (btn.dataset.captura === "copiar" && navigator.clipboard && window.ClipboardItem) {
        try {
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
          toast("Imagem copiada. É só colar no WhatsApp (Ctrl+V).");
          return;
        } catch { /* sem permissão de área de transferência: baixa o arquivo */ }
      }
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${btn.dataset.arquivo}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast("Imagem salva em Downloads.");
    } catch (e) {
      toast(`Não foi possível gerar a imagem (${e.message}). Use o Print Screen.`, "erro");
    } finally {
      alvo.classList.remove("capturando");
      btn.disabled = false;
      btn.innerHTML = original;
    }
  }));
}
