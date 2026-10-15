// Página Configurações: tudo o que no Power BI ficava escrito dentro das fórmulas DAX.
import { api, esc, fmt, icone, MESES, toast, ligarTooltips, linhaTT } from "./util.js";

const LINHAS_MUSSARELA = [1, 54, 59, 61];
const GRUPOS = [
  { id: "mussarela", nome: "Mussarela", cor: "var(--s-mus)", icone: "queijo" },
  { id: "outras", nome: "Outras linhas", cor: "var(--s-out)", icone: "leite" },
  { id: "fora", nome: "Não conta", cor: "var(--linha-forte)", icone: "menos" },
];
const GRUPOS_VEND = [
  { id: "ES", nome: "ES" }, { id: "BA", nome: "BA" }, { id: "EDIR", nome: "Edir" }, { id: "OCULTO", nome: "Oculto" },
];
const PESOS = [{ v: 0, n: "Sem expediente" }, { v: 0.5, n: "Meio expediente" }, { v: 1, n: "Dia normal (trabalha)" }];

let ctx = null, raiz = null;
let orig = null, cfg = null, cat = null;
let secao = "produtos";
const filtro = { busca: "", grupo: "todos", linha: "" };
let anoCal = new Date().getFullYear();
let timerCal = null;

const clone = (o) => JSON.parse(JSON.stringify(o));
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export function configTemAlteracoes() { return !!(cfg && orig && contarAlteracoes() > 0); }

export async function montarConfig(container, contexto) {
  ctx = contexto;
  raiz = container;
  if (cfg && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    const r = await api("/api/config");
    orig = r.config; cfg = clone(r.config); cat = r.catalogo;
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir as configurações: ${esc(e.message)}</p></div>`;
  }
}

// ---------- apoio ----------
const grupoDe = (id) => cfg.produtos[id]?.grupo ?? "outras";
const categoriaDe = (id) => (grupoDe(id) === "outras" ? cfg.produtos[id]?.categoria ?? null : null);
const grupoVend = (v) => cfg.vendedores[v.id] ?? v.grupo;

function contarAlteracoes() {
  let n = 0;
  const ids = new Set([...Object.keys(cfg.produtos), ...Object.keys(orig.produtos)]);
  ids.forEach((id) => {
    const a = cfg.produtos[id] || { grupo: "outras", categoria: null };
    const b = orig.produtos[id] || { grupo: "outras", categoria: null };
    if (a.grupo !== b.grupo || (a.grupo === "outras" && (a.categoria || null) !== (b.categoria || null))) n++;
  });
  new Set([...Object.keys(cfg.vendedores), ...Object.keys(orig.vendedores)]).forEach((id) => { if (cfg.vendedores[id] !== orig.vendedores[id]) n++; });
  if (!igual(cfg.categorias, orig.categorias)) n++;
  if (!igual(cfg.devolucoes, orig.devolucoes)) n++;
  if (!igual(cfg.calendario, orig.calendario)) n++;
  return n;
}

function alertaProduto(p, mapaLinhaCat) {
  const g = grupoDe(p.id);
  if (LINHAS_MUSSARELA.includes(p.id_linha) && g !== "mussarela") return "Está na linha de mussarela do ERP";
  if (g === "mussarela" && !LINHAS_MUSSARELA.includes(p.id_linha)) return "Fora da linha de mussarela do ERP";
  if (g === "outras" && !categoriaDe(p.id) && mapaLinhaCat[p.id_linha]) return `Sem categoria; a mesma linha do ERP está em ${mapaLinhaCat[p.id_linha]}`;
  return null;
}

function mapaLinhaCategoria() {
  const cont = {};
  cat.produtos.forEach((p) => {
    const c = categoriaDe(p.id);
    if (!c) return;
    cont[p.id_linha] = cont[p.id_linha] || {};
    cont[p.id_linha][c] = (cont[p.id_linha][c] || 0) + 1;
  });
  const saida = {};
  Object.entries(cont).forEach(([l, cs]) => { saida[l] = Object.entries(cs).sort((a, b) => b[1] - a[1])[0][0]; });
  return saida;
}

function alterado(p) {
  const a = { grupo: grupoDe(p.id), categoria: categoriaDe(p.id) };
  const o = orig.produtos[p.id] || { grupo: "outras", categoria: null };
  return a.grupo !== o.grupo || (a.grupo === "outras" && (a.categoria || null) !== (o.grupo === "outras" ? o.categoria || null : null));
}

// ---------- estrutura ----------
function render() {
  const nAlertas = cat.produtos.filter((p) => alertaProduto(p, mapaLinhaCategoria())).length;
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${[["produtos", "caixa", "Produtos", cat.produtos.length], ["vendedores", "pessoas", "Vendedores", cat.vendedores.length],
         ["devolucoes", "devolucao", "Devoluções", cfg.devolucoes.motivos.length], ["calendario", "calendario", "Dias úteis e feriados", cfg.calendario.extras.length]]
        .map(([id, ic, nome, n]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont">${n}</span></button>`).join("")}
      <div class="dica">${icone("info")} As regras valem para todas as visões assim que você salvar. Nada é alterado no ERP nem nas planilhas.${nAlertas ? `<br><br><b style="color:var(--atencao)">${nAlertas} produto(s) com alerta</b> para revisar em Produtos.` : ""}</div>
      <button class="btn perigo" id="cfg-padrao" style="margin:6px 4px 4px">${icone("restaurar")}Restaurar padrão do Power BI</button>
    </aside>
    <div id="cfg-secao"></div>
  </div>
  <div class="barra-salvar" id="barra-salvar">
    <span id="cfg-n">Alterações não salvas</span>
    <button class="btn" id="cfg-descartar">Descartar</button>
    <button class="btn primario" id="cfg-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => {
    secao = b.dataset.secao;
    raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x === b));
    renderSecao();
  }));
  raiz.querySelector("#cfg-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cfg-descartar").addEventListener("click", () => { cfg = clone(orig); render(); });
  raiz.querySelector("#cfg-padrao").addEventListener("click", restaurarPadrao);
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cfg-secao");
  ({ produtos: secaoProdutos, vendedores: secaoVendedores, devolucoes: secaoDevolucoes, calendario: secaoCalendario })[secao](alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  const barra = raiz.querySelector("#barra-salvar");
  barra.classList.toggle("visivel", n > 0);
  raiz.querySelector("#cfg-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
}

async function salvar() {
  const btn = raiz.querySelector("#cfg-salvar");
  btn.disabled = true;
  try {
    const r = await api("/api/config", { json: cfg });
    orig = r.config; cfg = clone(r.config);
    const novo = await api("/api/config");
    cat = novo.catalogo;
    toast("Configurações salvas. As metas já usam as novas regras.");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

async function restaurarPadrao() {
  if (!confirm("Voltar todas as regras para o padrão do Power BI? As configurações atuais serão substituídas (uma cópia fica em config_metas.anterior.json).")) return;
  try {
    const r = await api("/api/config/padrao", { method: "POST" });
    orig = r.config; cfg = clone(r.config);
    cat = (await api("/api/config")).catalogo;
    toast("Regras do Power BI restauradas");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) { toast(e.message, "erro"); }
}

// ======================================================================================
// Produtos
// ======================================================================================
function secaoProdutos(alvo) {
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("caixa")}Produtos do faturamento</h2>
      <p class="sub">Escolha o que conta como <b>mussarela</b>, como <b>outras linhas</b> ou que <b>não entra</b> no faturamento (ex.: imobilizado).
      Produto que aparecer pela primeira vez entra como outras linhas, igual ao Power BI. Lista: produtos vendidos desde ${fmt.data(cat.desde)} e os já configurados.</p>
    </div></div>
    <div class="resumo-grupos" id="cfg-resumo"></div>
    <h4 style="font-size:14px;margin:6px 0 2px">Categorias de outras linhas</h4>
    <p class="sub" style="margin:0 0 8px;color:var(--tinta-3);font-size:13px">Aparecem na visão Outras Linhas ES e na composição de cada vendedor.</p>
    <div class="categorias-editor" id="cfg-cats"></div>
    <div class="barra-ferramentas">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cfg-busca" type="search" placeholder="Buscar produto ou código" value="${esc(filtro.busca)}"></label>
      <div class="filtro-chips" id="cfg-chips"></div>
      <label class="campo"><select id="cfg-linha" style="padding-left:14px"><option value="">Todas as linhas do ERP</option>
        ${[...new Map(cat.produtos.map((p) => [p.id_linha, p.linha])).entries()].sort((a, b) => String(a[1]).localeCompare(String(b[1])))
          .map(([id, n]) => `<option value="${id}" ${String(id) === filtro.linha ? "selected" : ""}>${esc(n || "Sem linha")}</option>`).join("")}
      </select></label>
    </div>
    <div class="barra-ferramentas" id="cfg-lote"></div>
    <div class="lista-produtos" id="cfg-lista"></div>
  </section>`;
  alvo.querySelector("#cfg-busca").addEventListener("input", (e) => { filtro.busca = e.target.value; desenharLista(); });
  alvo.querySelector("#cfg-linha").addEventListener("change", (e) => { filtro.linha = e.target.value; desenharLista(); });
  desenharResumo();
  desenharCategorias();
  desenharLista();
}

function desenharResumo() {
  const el = raiz.querySelector("#cfg-resumo");
  if (!el) return;
  el.innerHTML = GRUPOS.map((g) => {
    const ps = cat.produtos.filter((p) => grupoDe(p.id) === g.id);
    const total = ps.reduce((s, p) => s + p.vendido_12m, 0);
    return `<div class="resumo-grupo" style="--c:${g.cor}">
      <div class="t">${icone(g.icone)}${g.nome}</div>
      <div class="n">${ps.length} <span style="font-size:14px;color:var(--tinta-3);font-weight:600">produtos</span></div>
      <div class="s">${fmt.moedaC(total)} vendidos em 12 meses</div></div>`;
  }).join("");
}

function desenharCategorias() {
  const el = raiz.querySelector("#cfg-cats");
  if (!el) return;
  el.innerHTML = cfg.categorias.map((c, i) => {
    const n = cat.produtos.filter((p) => categoriaDe(p.id) === c).length;
    return `<span class="cat-chip">${esc(c)} <small style="color:var(--tinta-3)">${n}</small><button title="Remover categoria" data-i="${i}">${icone("x")}</button></span>`;
  }).join("") + `<span class="cat-nova"><input id="cfg-cat-nova" placeholder="Nova categoria" maxlength="40"><button id="cfg-cat-add">${icone("mais")}</button></span>`;
  el.querySelectorAll("button[data-i]").forEach((b) => b.addEventListener("click", () => {
    const nome = cfg.categorias[Number(b.dataset.i)];
    const usados = Object.values(cfg.produtos).filter((r) => r.categoria === nome).length;
    if (usados && !confirm(`${usados} produto(s) estão em "${nome}" e ficarão sem categoria. Remover?`)) return;
    cfg.categorias.splice(Number(b.dataset.i), 1);
    Object.values(cfg.produtos).forEach((r) => { if (r.categoria === nome) r.categoria = null; });
    desenharCategorias(); desenharLista(); atualizarBarra();
  }));
  const add = () => {
    const inp = el.querySelector("#cfg-cat-nova");
    const nome = inp.value.trim();
    if (!nome) return;
    if (cfg.categorias.some((c) => c.toLowerCase() === nome.toLowerCase())) { toast("Essa categoria já existe", "erro"); return; }
    cfg.categorias.push(nome);
    desenharCategorias(); desenharLista(); atualizarBarra();
  };
  el.querySelector("#cfg-cat-add").addEventListener("click", add);
  el.querySelector("#cfg-cat-nova").addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
}

function produtosFiltrados() {
  const mapa = mapaLinhaCategoria();
  const b = filtro.busca.trim().toLowerCase();
  return cat.produtos.filter((p) => {
    if (b && !p.nome.toLowerCase().includes(b) && !String(p.id).includes(b)) return false;
    if (filtro.linha && String(p.id_linha) !== filtro.linha) return false;
    const g = grupoDe(p.id);
    switch (filtro.grupo) {
      case "mussarela": case "outras": case "fora": return g === filtro.grupo;
      case "semcat": return g === "outras" && !categoriaDe(p.id);
      case "alertas": return !!alertaProduto(p, mapa);
      case "alterados": return alterado(p);
      default: return true;
    }
  });
}

function desenharLista() {
  const mapa = mapaLinhaCategoria();
  const chips = [["todos", "Todos"], ["mussarela", "Mussarela"], ["outras", "Outras linhas"], ["fora", "Não conta"], ["semcat", "Sem categoria"], ["alertas", "Com alerta"], ["alterados", "Alterados"]];
  const contagem = { alertas: cat.produtos.filter((p) => alertaProduto(p, mapa)).length, alterados: cat.produtos.filter(alterado).length };
  const elChips = raiz.querySelector("#cfg-chips");
  elChips.innerHTML = chips.map(([id, n]) => `<button class="filtro-chip ${filtro.grupo === id ? "ativo" : ""}" data-f="${id}">${n}${contagem[id] ? ` (${contagem[id]})` : ""}</button>`).join("");
  elChips.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { filtro.grupo = b.dataset.f; desenharLista(); }));

  const lista = produtosFiltrados();
  raiz.querySelector("#cfg-lote").innerHTML = lista.length > 1 ? `
    <span style="font-size:13px;color:var(--tinta-3);font-weight:600">${lista.length} produtos na lista. Marcar todos como:</span>
    ${GRUPOS.map((g) => `<button class="btn" data-lote="${g.id}" style="height:34px">${icone(g.icone)}${g.nome}</button>`).join("")}` : "";
  raiz.querySelectorAll("[data-lote]").forEach((b) => b.addEventListener("click", () => {
    if (!confirm(`Marcar os ${lista.length} produtos filtrados como "${GRUPOS.find((g) => g.id === b.dataset.lote).nome}"?`)) return;
    lista.forEach((p) => definirGrupo(p.id, b.dataset.lote));
    desenharLista(); desenharResumo(); atualizarBarra();
  }));

  const el = raiz.querySelector("#cfg-lista");
  if (!lista.length) { el.innerHTML = `<div class="vazio">${icone("busca")}<p>Nenhum produto com esses filtros.</p></div>`; return; }
  el.innerHTML = lista.map((p, i) => linhaProduto(p, i, mapa)).join("");
  el.querySelectorAll(".prod-linha").forEach(ligarLinhaProduto);
}

function linhaProduto(p, i, mapa) {
  const g = grupoDe(p.id), c = categoriaDe(p.id);
  const idx = GRUPOS.findIndex((x) => x.id === g);
  const alerta = alertaProduto(p, mapa);
  return `<div class="prod-linha ${alterado(p) ? "alterado" : ""}" data-id="${p.id}" style="--i:${i}">
    <div class="prod-nome">${esc(p.nome)}<small>Código ${p.id} · ${esc(p.linha || "sem linha")}${p.unidade ? " · " + esc(p.unidade) : ""}${p.inativo ? " · inativo no ERP" : ""}</small>
      ${alerta ? `<span class="alerta">${icone("alerta")}${esc(alerta)}</span>` : ""}</div>
    <div class="prod-vendido">${fmt.moedaC(p.vendido_12m)}<small>vendido em 12 meses</small></div>
    <div class="seletor" data-v="${idx}" role="radiogroup" aria-label="Grupo de ${esc(p.nome)}">
      <span class="marcador"></span>
      ${GRUPOS.map((x) => `<button type="button" role="radio" aria-checked="${x.id === g}" data-g="${x.id}" class="${x.id === g ? "ativo" : ""}"><span class="bolinha" style="--c:${x.cor}"></span>${x.nome}</button>`).join("")}
    </div>
    <label class="campo cat"><span class="sr">Categoria</span><select ${g !== "outras" ? "disabled" : ""}>
      <option value="">${g === "outras" ? "Sem categoria" : "—"}</option>
      ${cfg.categorias.map((x) => `<option ${x === c ? "selected" : ""}>${esc(x)}</option>`).join("")}
    </select></label>
  </div>`;
}

function definirGrupo(id, grupo) {
  const atual = cfg.produtos[id] || { grupo: "outras", categoria: null };
  cfg.produtos[id] = { grupo, categoria: grupo === "outras" ? atual.categoria || null : null };
}

function ligarLinhaProduto(linha) {
  const id = linha.dataset.id;
  const p = cat.produtos.find((x) => String(x.id) === id);
  const sel = linha.querySelector(".seletor");
  sel.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    definirGrupo(id, b.dataset.g);
    sel.dataset.v = GRUPOS.findIndex((x) => x.id === b.dataset.g);
    sel.querySelectorAll("button").forEach((x) => { x.classList.toggle("ativo", x === b); x.setAttribute("aria-checked", x === b); });
    atualizarDetalhesLinha(linha, p);
    desenharResumo(); desenharCategorias(); atualizarBarra();
  }));
  linha.querySelector("select").addEventListener("change", (e) => {
    cfg.produtos[id] = { grupo: "outras", categoria: e.target.value || null };
    atualizarDetalhesLinha(linha, p);
    desenharCategorias(); atualizarBarra();
  });
}

function atualizarDetalhesLinha(linha, p) {
  const g = grupoDe(p.id);
  const select = linha.querySelector("select");
  select.disabled = g !== "outras";
  select.options[0].textContent = g === "outras" ? "Sem categoria" : "—";
  select.value = categoriaDe(p.id) || "";
  linha.classList.toggle("alterado", alterado(p));
  const nome = linha.querySelector(".prod-nome");
  nome.querySelector(".alerta")?.remove();
  const al = alertaProduto(p, mapaLinhaCategoria());
  if (al) nome.insertAdjacentHTML("beforeend", `<span class="alerta">${icone("alerta")}${esc(al)}</span>`);
}

// ======================================================================================
// Vendedores
// ======================================================================================
function secaoVendedores(alvo) {
  const limite = new Date(); limite.setMonth(limite.getMonth() - 3);
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("pessoas")}Região de cada vendedor</h2>
      <p class="sub">Define em quais visões cada vendedor da planilha de metas aparece.
      <b>ES</b>: Metas ES e Outras Linhas ES · <b>BA</b>: Metas BA e Produtos BA · <b>Edir</b>: Metas Edir e Produtos BA · <b>Oculto</b>: não aparece.
      Vendedor novo que ainda não estiver aqui segue o supervisor do ERP.</p>
    </div></div>
    <div class="lista-produtos">
      ${cat.vendedores.map((v, i) => {
        const g = grupoVend(v);
        const idx = GRUPOS_VEND.findIndex((x) => x.id === g);
        const antigo = new Date(v.ultimo_mes + "T12:00") < limite;
        const alt = (cfg.vendedores[v.id] ?? v.grupo) !== (orig.vendedores[v.id] ?? v.grupo);
        const [a, m] = v.ultimo_mes.split("-");
        return `<div class="vend-linha ${antigo ? "antigo" : ""} ${alt ? "alterado" : ""}" data-id="${v.id}" style="--i:${i}">
          <div class="prod-nome">${esc(v.nome)}<small>ERP: ${esc(v.nome_erp || "—")} · código ${v.id}${v.inativo ? " · inativo" : ""}</small></div>
          <div style="font-size:13px;color:var(--tinta-2)">Supervisor: <b>${esc(v.supervisor || "—")}</b><br><span style="color:var(--tinta-3)">Última meta: ${MESES[Number(m) - 1]}/${a}</span></div>
          <div class="seletor v4" data-v="${idx}"><span class="marcador"></span>
            ${GRUPOS_VEND.map((x) => `<button type="button" data-g="${x.id}" class="${x.id === g ? "ativo" : ""}">${x.nome}</button>`).join("")}
          </div>
        </div>`;
      }).join("")}
    </div>
  </section>`;
  alvo.querySelectorAll(".vend-linha").forEach((linha) => {
    linha.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const id = linha.dataset.id;
      cfg.vendedores[id] = b.dataset.g;
      const sel = linha.querySelector(".seletor");
      sel.dataset.v = GRUPOS_VEND.findIndex((x) => x.id === b.dataset.g);
      sel.querySelectorAll("button").forEach((x) => x.classList.toggle("ativo", x === b));
      const v = cat.vendedores.find((x) => String(x.id) === id);
      linha.classList.toggle("alterado", (cfg.vendedores[id] ?? v.grupo) !== (orig.vendedores[id] ?? v.grupo));
      atualizarBarra();
    }));
  });
}

// ======================================================================================
// Devoluções
// ======================================================================================
function secaoDevolucoes(alvo) {
  const d = cfg.devolucoes;
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("devolucao")}Devoluções que descontam do faturamento</h2>
      <p class="sub">Itens devolvidos com os motivos ligados abaixo são descontados do faturamento e do volume (as "devoluções próprias" do Power BI).
      A devolução conta pela data de entrada e pelo vendedor da devolução. Valores: últimos 12 meses.</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${d.ignorar_canceladas ? "ligada" : ""}" id="cfg-canc" role="switch" aria-checked="${d.ignorar_canceladas}"></button>
      <div><b>Ignorar devoluções canceladas</b><p>O Power BI descontava também as devoluções canceladas (cerca de R$ 11 mil em 2026). Ligado, elas não descontam.</p></div>
    </div>
    <div class="lista-produtos">
      ${cat.motivos.map((m, i) => {
        const on = d.motivos.includes(m.id);
        return `<div class="motivo-linha" style="--i:${i}">
          <button class="chave ${on ? "ligada" : ""}" data-m="${m.id}" role="switch" aria-checked="${on}" aria-label="${esc(m.nome)}"></button>
          <div><b>${m.id}</b> · ${esc(m.nome)}</div>
          <div class="prod-vendido">${m.valor_12m ? fmt.moedaC(m.valor_12m) : "—"}<small>devolvido em 12 meses</small></div>
        </div>`;
      }).join("")}
    </div>
  </section>`;
  alvo.querySelector("#cfg-canc").addEventListener("click", (e) => {
    d.ignorar_canceladas = !d.ignorar_canceladas;
    e.currentTarget.classList.toggle("ligada", d.ignorar_canceladas);
    e.currentTarget.setAttribute("aria-checked", d.ignorar_canceladas);
    atualizarBarra();
  });
  alvo.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => {
    const id = Number(b.dataset.m);
    d.motivos = d.motivos.includes(id) ? d.motivos.filter((x) => x !== id) : [...d.motivos, id].sort((a, c) => a - c);
    b.classList.toggle("ligada", d.motivos.includes(id));
    b.setAttribute("aria-checked", d.motivos.includes(id));
    atualizarBarra();
  }));
}

// ======================================================================================
// Dias úteis e feriados
// ======================================================================================
function secaoCalendario(alvo) {
  const c = cfg.calendario;
  const anos = [anoCal - 1, anoCal, anoCal + 1].filter((v, i, a) => a.indexOf(v) === i);
  const sabado = (r) => {
    const idx = [0, 0.5, 1].indexOf(Number(c.sabado[r]));
    return `<div class="seletor" data-v="${idx}" data-sab="${r}" style="min-width:330px"><span class="marcador"></span>
      ${["Não conta", "Meio dia", "Dia inteiro"].map((n, i) => `<button type="button" data-p="${[0, 0.5, 1][i]}" class="${i === idx ? "ativo" : ""}">${n}</button>`).join("")}</div>`;
  };
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("calendario")}Dias úteis e feriados</h2>
      <p class="sub">Os dias úteis de cada mês são calculados sozinhos: segunda a sexta, menos os feriados nacionais e estaduais.
      Use as exceções para feriados municipais, pontos facultativos ou dias em que a equipe trabalhou normalmente.</p>
    </div></div>
    <div class="opcao-linha"><div style="flex:1"><b>Sábado no Espírito Santo</b><p>Nas vendas de 2025 e 2026 a equipe do ES praticamente não vendeu aos sábados.</p></div>${sabado("ES")}</div>
    <div class="opcao-linha"><div style="flex:1"><b>Sábado na Bahia</b><p>A equipe da BA vendeu aos sábados cerca de 43% de um dia útil. O Power BI não contava o sábado.</p></div>${sabado("BA")}</div>
  </section>
  <section class="cartao secao entra" style="--i:2">
    <div class="cartao-cab"><div><h3>${icone("grafico")}Dias úteis por mês</h3><p class="sub">Já considerando as exceções e o sábado acima (antes de salvar)</p></div>
      <label class="campo"><select id="cfg-ano" style="padding-left:14px">${anos.map((a) => `<option ${a === anoCal ? "selected" : ""}>${a}</option>`).join("")}</select></label></div>
    <div class="meses-grade" id="cfg-meses"><div class="esqueleto" style="height:70px;grid-column:1/-1"></div></div>
  </section>
  <section class="duas-colunas secao">
    <article class="cartao entra" style="--i:3">
      <div class="cartao-cab"><div><h3>${icone("estrela")}Feriados automáticos de <span id="cfg-ano-t">${anoCal}</span></h3><p class="sub">Conferidos com as vendas de 2025 e 2026 em cada estado</p></div></div>
      <div id="cfg-feriados"></div>
    </article>
    <article class="cartao entra" style="--i:4">
      <div class="cartao-cab"><div><h3>${icone("mais")}Exceções</h3><p class="sub">Feriado local, meio expediente ou dia trabalhado em feriado</p></div>
        <button class="btn" id="cfg-extra-add">${icone("mais")}Adicionar data</button></div>
      <div id="cfg-extras"></div>
    </article>
  </section>`;
  alvo.querySelectorAll("[data-sab]").forEach((sel) => sel.querySelectorAll("button").forEach((b, i) => b.addEventListener("click", () => {
    c.sabado[sel.dataset.sab] = Number(b.dataset.p);
    sel.dataset.v = i;
    sel.querySelectorAll("button").forEach((x) => x.classList.toggle("ativo", x === b));
    atualizarBarra(); previaCalendario();
  })));
  alvo.querySelector("#cfg-ano").addEventListener("change", (e) => { anoCal = Number(e.target.value); alvo.querySelector("#cfg-ano-t").textContent = anoCal; previaCalendario(); });
  alvo.querySelector("#cfg-extra-add").addEventListener("click", () => {
    c.extras.push({ data: `${anoCal}-12-24`, regiao: "TODAS", peso: 0.5, descricao: "Véspera de Natal" });
    desenharExtras(); atualizarBarra(); previaCalendario();
  });
  desenharExtras();
  previaCalendario();
}

function desenharExtras() {
  const el = raiz.querySelector("#cfg-extras");
  const ex = cfg.calendario.extras;
  if (!ex.length) { el.innerHTML = `<div class="vazio" style="padding:20px">${icone("calendario")}<p>Nenhuma exceção cadastrada.</p></div>`; return; }
  el.innerHTML = ex.map((e, i) => `
    <div class="extra-linha" data-i="${i}">
      <input type="date" value="${esc(e.data)}" data-k="data" aria-label="Data">
      <select data-k="regiao" aria-label="Região">${["TODAS", "ES", "BA"].map((r) => `<option value="${r}" ${r === e.regiao ? "selected" : ""}>${r === "TODAS" ? "ES e BA" : r}</option>`).join("")}</select>
      <input type="text" value="${esc(e.descricao)}" data-k="descricao" placeholder="Descrição" aria-label="Descrição">
      <select data-k="peso" aria-label="Expediente">${PESOS.map((p) => `<option value="${p.v}" ${p.v === Number(e.peso) ? "selected" : ""}>${p.n}</option>`).join("")}</select>
      <button class="btn icone perigo" title="Remover" data-rem="${i}">${icone("x")}</button>
    </div>`).join("");
  el.querySelectorAll(".extra-linha").forEach((linha) => {
    const i = Number(linha.dataset.i);
    linha.querySelectorAll("[data-k]").forEach((inp) => inp.addEventListener("change", () => {
      const k = inp.dataset.k;
      ex[i][k] = k === "peso" ? Number(inp.value) : inp.value;
      atualizarBarra(); previaCalendario();
    }));
  });
  el.querySelectorAll("[data-rem]").forEach((b) => b.addEventListener("click", () => {
    ex.splice(Number(b.dataset.rem), 1);
    desenharExtras(); atualizarBarra(); previaCalendario();
  }));
}

function previaCalendario() {
  clearTimeout(timerCal);
  timerCal = setTimeout(async () => {
    try {
      const validos = { ...cfg, calendario: { ...cfg.calendario, extras: cfg.calendario.extras.filter((e) => /^\d{4}-\d{2}-\d{2}$/.test(e.data)) } };
      const r = await api("/api/calendario", { json: { ano: anoCal, config: validos } });
      const meses = raiz.querySelector("#cfg-meses");
      if (!meses) return;
      meses.innerHTML = r.meses.map((m, i) => `<div class="mes-c entra" style="--i:${i}"><div class="m">${MESES[m.mes - 1]}</div>
        <div class="r"><span>ES</span><b>${fmt.dias(m.ES)}</b></div><div class="r"><span>BA</span><b>${fmt.dias(m.BA)}</b></div></div>`).join("");
      raiz.querySelector("#cfg-feriados").innerHTML = r.feriados.map((f) => `
        <div class="feriado-linha"><b>${fmt.dataCurta(f.data)} <small style="color:var(--tinta-3);font-weight:500">${fmt.semana(f.data).slice(0, 3)}</small></b>
        <span>${esc(f.nome)}</span><span style="text-align:right">${f.regioes.map((x) => `<span class="chip">${x}</span>`).join(" ")}</span></div>`).join("");
      ligarTooltips(meses);
    } catch (e) { toast(e.message, "erro"); }
  }, 250);
}
