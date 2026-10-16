// Página Configurações das metas: tudo o que no Power BI ficava escrito dentro das fórmulas DAX e, em
// "Acesso por usuário", as abas e os vendedores de Metas que cada visualizador vê.
import { api, esc, fmt, icone, MESES, toast, ligarTooltips, linhaTT } from "./util.js";
import { iniciais } from "./conta.js";

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
const ICONE_VISAO = { es: "mapa", ba: "mapa", edir: "usuario", outras_es: "leite", produtos_ba: "caixa" };

let ctx = null, raiz = null;
let orig = null, cfg = null, cat = null;
let usuarios = [], visoes = [];          // visualizadores e abas de Metas (de /api/config)
let origAcessos = null, acessos = null;  // login -> { ve, visoes, vendedores (null = todos das abas) }
let secao = "produtos";
const filtro = { busca: "", grupo: "todos", linha: "" };
let anoCal = new Date().getFullYear();
let timerCal = null;
let usuarioSel = null, buscaUsuario = "", buscaVend = "";
const ultimosAlguns = {};                // login -> lista de "Só alguns" guardada ao trocar para "Todos"

const clone = (o) => JSON.parse(JSON.stringify(o));
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export function configTemAlteracoes() { return !!(cfg && orig && contarAlteracoes() > 0); }

export async function montarConfig(container, contexto) {
  ctx = contexto;
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (q.get("u") || q.get("secao") === "usuarios") secao = "usuarios";
  if (q.get("u")) usuarioSel = q.get("u");
  if (cfg && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    carregar(await api("/api/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir as configurações: ${esc(e.message)}</p></div>`;
  }
}

function carregar(r) {
  orig = r.config; cfg = clone(r.config); cat = r.catalogo;
  usuarios = r.usuarios; visoes = r.visoes;
  origAcessos = Object.fromEntries(usuarios.map((u) => [u.login, {
    ve: (u.paginas || []).includes("metas"),
    visoes: [...(u.visoes || [])],
    vendedores: u.vendedores ? [...u.vendedores].sort((a, b) => a - b) : null,
  }]));
  acessos = clone(origAcessos);
  if (!usuarios.some((u) => u.login === usuarioSel)) usuarioSel = usuarios[0]?.login ?? null;
}

// ---------- apoio ----------
const grupoDe = (id) => cfg.produtos[id]?.grupo ?? "outras";
const categoriaDe = (id) => (grupoDe(id) === "outras" ? cfg.produtos[id]?.categoria ?? null : null);
const grupoVend = (v) => cfg.vendedores[v.id] ?? v.grupo;

const usuarioMudou = (login) => !igual(acessos[login], origAcessos[login]);
const usuariosMudados = () => usuarios.filter((u) => usuarioMudou(u.login));

function contarAlteracoes() {
  return contarAlteracoesRegras() + usuariosMudados().length;
}

function contarAlteracoesRegras() {
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
         ["devolucoes", "devolucao", "Devoluções", cfg.devolucoes.motivos.length], ["calendario", "calendario", "Dias úteis e feriados", cfg.calendario.extras.length],
         ["usuarios", "escudo", "Acesso por usuário", contarVeem()]]
        .map(([id, ic, nome, n]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont" data-cont="${id}">${n}</span></button>`).join("")}
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
  raiz.querySelector("#cfg-descartar").addEventListener("click", () => { cfg = clone(orig); acessos = clone(origAcessos); render(); });
  raiz.querySelector("#cfg-padrao").addEventListener("click", restaurarPadrao);
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cfg-secao");
  ({ produtos: secaoProdutos, vendedores: secaoVendedores, devolucoes: secaoDevolucoes, calendario: secaoCalendario,
     usuarios: secaoUsuarios })[secao](alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  const barra = raiz.querySelector("#barra-salvar");
  barra.classList.toggle("visivel", n > 0);
  raiz.querySelector("#cfg-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  const cont = raiz.querySelector('[data-cont="usuarios"]');
  if (cont) cont.textContent = contarVeem();
}

async function salvar() {
  const btn = raiz.querySelector("#cfg-salvar");
  const mudados = usuariosMudados();
  for (const u of mudados) {
    const erro = erroAcesso(u);
    if (erro) return erroUsuario(u, erro);
  }
  const corpo = contarAlteracoesRegras() ? clone(cfg) : {};
  if (mudados.length) corpo.usuarios = Object.fromEntries(mudados.map((u) => [u.login, acessos[u.login]]));
  btn.disabled = true;
  try {
    await api("/api/config", { json: corpo });
    carregar(await api("/api/config"));
    toast(mudados.length && !corpo.produtos ? "Acessos de Metas salvos" : "Configurações salvas. As metas já usam as novas regras.");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

async function restaurarPadrao() {
  if (!confirm("Voltar todas as regras para o padrão do Power BI? As configurações atuais serão substituídas (uma cópia fica em config_metas.anterior.json). Os acessos por usuário não mudam.")) return;
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

// ======================================================================================
// Acesso por usuário: abas e vendedores de Metas de cada visualizador
// ======================================================================================
const contarVeem = () => usuarios.filter((u) => acessos[u.login].ve).length;
const tituloVisao = (id) => visoes.find((v) => v.id === id)?.titulo || id;
const nomeVendedor = (id) => cat.vendedores.find((v) => v.id === id)?.nome || `Vendedor ${id}`;
const rotuloGrupo = (g) => (g === "EDIR" ? "Edir" : g);

function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

function resumoCurtoAcesso(u) {
  const a = acessos[u.login];
  if (!a.ve) return "não vê a página";
  if (!a.visoes.length) return "sem abas";
  const n = a.vendedores?.length;
  return `${a.visoes.length} aba${a.visoes.length === 1 ? "" : "s"} · ${n ? `${n} vendedor${n === 1 ? "" : "es"}` : "todos os vendedores"}`;
}

// O que falta para salvar o acesso (null = pode salvar).
function erroAcesso(u) {
  const a = acessos[u.login];
  if (!a.ve) return (u.paginas || []).some((p) => p !== "metas") ? null : "é a única página desta pessoa; libere outra em Usuários antes de tirar esta";
  if (!a.visoes.length) return "marque ao menos uma aba, ou desligue a página";
  if (a.vendedores && !a.vendedores.length) return "marque ao menos um vendedor, ou escolha todos dessas abas";
  return null;
}

function erroUsuario(u, msg) {
  secao = "usuarios";
  usuarioSel = u.login;
  render();
  const el = raiz.querySelector("#cfg-u-erro");
  el.textContent = `${u.nome}: ${msg}.`;
  el.hidden = false;
  toast(`${u.nome}: ${msg}`, "erro");
}

function secaoUsuarios(alvo) {
  if (!usuarios.length) {
    alvo.innerHTML = `<section class="cartao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div><h3>Ainda não há visualizadores</h3>
      <p>Cadastre as pessoas em <b>Usuários</b>; depois, aqui você escolhe as abas e os vendedores de Metas de cada uma.</p>
      <a class="btn primario" href="#/usuarios">${icone("escudo")}Abrir Usuários</a></section>`;
    return;
  }
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios">
    <aside class="cartao usu-lista entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("escudo")}Visualizadores</h2>
        <p class="sub">Quem vê a página e quais abas e vendedores aparecem para cada um</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="cfg-busca-u" type="search" placeholder="Buscar pessoa" value="${esc(buscaUsuario)}"></label>
      <div class="usu-itens" id="cfg-u-itens"></div>
      <div class="dica">${icone("info")}<span>Nome, senha e páginas ficam em <a href="#/usuarios">Usuários</a>. Administradores veem tudo.
        Em Projeções, quem está em "Igual a Metas" segue estas abas e vendedores.</span></div>
    </aside>
    <div id="cfg-u-editor"></div>
  </div>`;
  alvo.querySelector("#cfg-busca-u").addEventListener("input", (e) => { buscaUsuario = e.target.value; desenharItensUsuarios(); });
  desenharItensUsuarios();
  desenharEditorUsuario();
}

function desenharItensUsuarios() {
  const termo = buscaUsuario.trim().toLowerCase();
  const el = raiz.querySelector("#cfg-u-itens");
  el.innerHTML = usuarios.filter((u) => !termo || `${u.nome} ${u.login}`.toLowerCase().includes(termo)).map((u, i) => {
    const a = acessos[u.login];
    return `<button type="button" class="usu-item ${u.login === usuarioSel ? "selecionado" : ""} ${a.ve ? "" : "inativo"}" data-login="${esc(u.login)}" style="--i:${i}">
      <span class="avatar">${esc(iniciais(u.nome))}</span>
      <span class="t"><b>${esc(u.nome)}${usuarioMudou(u.login) ? " <em>(alterado)</em>" : ""}</b><small>${esc(u.login)} · ${esc(resumoCurtoAcesso(u))}</small></span>
      <span class="chip-papel ${a.ve ? "" : "inativo"}">${a.ve ? "Vê" : "Não vê"}</span>
    </button>`;
  }).join("") || `<p class="usu-nota">${icone("busca")}Ninguém com esse nome.</p>`;
  el.querySelectorAll(".usu-item").forEach((b) => b.addEventListener("click", () => {
    if (usuarioSel === b.dataset.login) return;
    usuarioSel = b.dataset.login;
    buscaVend = "";
    desenharItensUsuarios();
    desenharEditorUsuario();
  }));
}

function desenharEditorUsuario() {
  const alvo = raiz.querySelector("#cfg-u-editor");
  const u = usuarios.find((x) => x.login === usuarioSel);
  if (!u) { alvo.innerHTML = ""; return; }
  const a = acessos[u.login];
  const outras = (u.paginas || []).filter((p) => p !== "metas");
  alvo.innerHTML = `
  <section class="cartao usu-editor entra" style="--i:2">
    <div class="cartao-cab"><div>
      <h2>${icone("alvo")}Metas de ${esc(u.nome)}</h2>
      <p class="sub">${esc(u.login)}${u.ativo ? "" : " · acesso desativado em Usuários"}</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${a.ve ? "ligada" : ""}" id="cfg-u-ve" type="button" role="switch" aria-checked="${a.ve}" aria-label="Vê a página Metas"></button>
      <div><b>Vê a página Metas</b><p>${a.ve ? "A página aparece na barra lateral desta pessoa." : "Desligado, a página some da barra lateral e o servidor não manda os números."}
        ${!outras.length && a.ve ? " É a única página dela: para tirar, libere outra antes em Usuários." : ""}</p></div>
    </div>
    <div id="cfg-u-permissoes" ${a.ve ? "" : "hidden"}></div>
    <div class="usu-resumo" id="cfg-u-resumo"></div>
    <p class="form-erro" id="cfg-u-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#cfg-u-ve").addEventListener("click", () => {
    a.ve = !a.ve;
    desenharEditorUsuario();
    aoMudarAcesso();
  });
  if (a.ve) desenharPermissoesUsuario(u);
  atualizarResumoUsuario(u);
}

function aoMudarAcesso() {
  desenharItensUsuarios();
  atualizarBarra();
}

function desenharPermissoesUsuario(u) {
  const a = acessos[u.login];
  const alvo = raiz.querySelector("#cfg-u-permissoes");
  const alguns = a.vendedores !== null;
  alvo.innerHTML = `
    <h3 class="usu-titulo">Abas que pode ver</h3>
    <div class="visoes-escolha">
      ${visoes.map((v) => {
        const on = a.visoes.includes(v.id);
        return `<button type="button" class="visao-op ${on ? "ativo" : ""}" data-visao="${v.id}" aria-pressed="${on}">
          <span class="marca-caixa">${icone("visto")}</span>${icone(ICONE_VISAO[v.id] || "alvo")}
          <span><b>${esc(v.titulo)}</b><small>vendedores ${esc(emLista(v.grupos.map(rotuloGrupo)))}</small></span>
        </button>`;
      }).join("")}
    </div>
    <h3 class="usu-titulo">Vendedores</h3>
    <div class="seletor v2 usu-modo" data-v="${alguns ? 1 : 0}"><span class="marcador"></span>
      <button type="button" data-modo="todos" class="${alguns ? "" : "ativo"}">${icone("pessoas")}Todos dessas abas</button>
      <button type="button" data-modo="alguns" class="${alguns ? "ativo" : ""}">${icone("usuario")}Só alguns vendedores</button>
    </div>
    <div id="cfg-u-vendedores"></div>`;
  alvo.querySelectorAll(".visao-op[data-visao]").forEach((b) => b.addEventListener("click", () => {
    const marcadas = new Set(a.visoes);
    marcadas.has(b.dataset.visao) ? marcadas.delete(b.dataset.visao) : marcadas.add(b.dataset.visao);
    a.visoes = visoes.map((v) => v.id).filter((id) => marcadas.has(id));
    b.classList.toggle("ativo", marcadas.has(b.dataset.visao));
    b.setAttribute("aria-pressed", marcadas.has(b.dataset.visao));
    desenharVendedoresUsuario(u);
    aoMudarAcesso();
  }));
  alvo.querySelectorAll(".usu-modo button").forEach((b) => b.addEventListener("click", () => {
    const querAlguns = b.dataset.modo === "alguns";
    if (querAlguns === (a.vendedores !== null)) return;
    if (querAlguns) a.vendedores = [...(ultimosAlguns[u.login] || origAcessos[u.login].vendedores || [])];
    else { ultimosAlguns[u.login] = a.vendedores; a.vendedores = null; }
    const seletor = alvo.querySelector(".usu-modo");
    seletor.dataset.v = querAlguns ? 1 : 0;
    seletor.querySelectorAll("button").forEach((x) => x.classList.toggle("ativo", x === b));
    desenharVendedoresUsuario(u);
    aoMudarAcesso();
  }));
  desenharVendedoresUsuario(u);
}

function desenharVendedoresUsuario(u) {
  const a = acessos[u.login];
  const alvo = raiz.querySelector("#cfg-u-vendedores");
  if (a.vendedores === null) {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}Vê todos os vendedores que aparecem nas abas marcadas, inclusive os que entrarem depois.</p>`;
    atualizarResumoUsuario(u);
    return;
  }
  const grupos = new Set(visoes.filter((v) => a.visoes.includes(v.id)).flatMap((v) => v.grupos));
  const marcados = new Set(a.vendedores);
  const limite = new Date(); limite.setMonth(limite.getMonth() - 3);
  const lista = cat.vendedores.filter((v) => grupos.has(grupoVend(v)) || marcados.has(v.id));
  alvo.innerHTML = `
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
        <input id="cfg-u-busca" type="search" placeholder="Buscar vendedor ou código" value="${esc(buscaVend)}"></label>
      <span class="usu-cont" id="cfg-u-cont"></span>
      <button class="btn" type="button" id="cfg-u-todos">Marcar os da lista</button>
      <button class="btn" type="button" id="cfg-u-nenhum">Desmarcar todos</button>
    </div>
    ${grupos.size ? "" : `<p class="usu-nota">${icone("info")}Marque as abas primeiro: a lista mostra os vendedores delas.</p>`}
    <div class="vend-escolha">
      ${lista.map((v) => {
        const antigo = new Date(v.ultimo_mes + "T12:00") < limite;
        const fora = !grupos.has(grupoVend(v));
        return `<label class="vend-op ${antigo ? "antigo" : ""}" data-busca="${esc((v.nome + " " + v.nome_erp + " " + v.id).toLowerCase())}">
          <input type="checkbox" data-id="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
          <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(rotuloGrupo(grupoVend(v)))}${v.supervisor ? ` · sup. ${esc(v.supervisor)}` : ""}${fora ? " · fora das abas marcadas" : ""}</small></span>
        </label>`;
      }).join("")}
    </div>`;
  const filtrar = () => {
    const termo = buscaVend.trim().toLowerCase();
    alvo.querySelectorAll(".vend-op").forEach((el) => { el.hidden = !!termo && !el.dataset.busca.includes(termo); });
  };
  const contar = () => {
    const n = a.vendedores.length;
    alvo.querySelector("#cfg-u-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
    atualizarResumoUsuario(u);
  };
  const definir = (ids) => {
    a.vendedores = [...ids].sort((x, y) => x - y);
    alvo.querySelectorAll(".vend-op input").forEach((c) => { c.checked = ids.has(Number(c.dataset.id)); });
    contar();
    aoMudarAcesso();
  };
  alvo.querySelector("#cfg-u-busca").addEventListener("input", (e) => { buscaVend = e.target.value; filtrar(); });
  alvo.querySelectorAll(".vend-op input").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(a.vendedores);
    c.checked ? ids.add(Number(c.dataset.id)) : ids.delete(Number(c.dataset.id));
    definir(ids);
  }));
  alvo.querySelector("#cfg-u-todos").addEventListener("click", () => {
    const ids = new Set(a.vendedores);
    alvo.querySelectorAll(".vend-op:not([hidden]) input").forEach((c) => ids.add(Number(c.dataset.id)));
    definir(ids);
  });
  alvo.querySelector("#cfg-u-nenhum").addEventListener("click", () => definir(new Set()));
  filtrar();
  contar();
}

function atualizarResumoUsuario(u) {
  const el = raiz.querySelector("#cfg-u-resumo");
  if (!el) return;
  const a = acessos[u.login];
  const quem = `<b>${esc(u.nome)}</b>`;
  let txt;
  if (!a.ve) txt = `${quem} não vê a página Metas.`;
  else if (!a.visoes.length) txt = "Marque ao menos uma aba para esta pessoa: sem abas, a página fica vazia para ela.";
  else {
    const abas = emLista(a.visoes.map((v) => `<b>${esc(tituloVisao(v))}</b>`));
    let vend;
    if (a.vendedores === null) vend = "com todos os vendedores dessas abas";
    else if (!a.vendedores.length) vend = "mas falta marcar os vendedores";
    else if (a.vendedores.length <= 3) vend = `só com ${emLista(a.vendedores.map((v) => `<b>${esc(nomeVendedor(v))}</b>`))}; os totais somam só ${a.vendedores.length === 1 ? "esse vendedor" : "esses vendedores"}`;
    else vend = `só com os <b>${a.vendedores.length} vendedores</b> marcados; os totais somam só esses vendedores`;
    txt = `${quem} vê as abas ${abas}, ${vend}.`;
  }
  el.innerHTML = `${icone("olho")}<span>${txt}</span>`;
}
