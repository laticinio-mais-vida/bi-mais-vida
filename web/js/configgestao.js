// Configuração da página Gestão (só administradores):
// - Acesso por usuário: quem usa a página e quais vendedores cada visualizador acompanha (as ações, os objetivos e o
//   histórico deles). Só o administrador lança ações e objetivos e escreve observações. Vendedor aqui é o vendedor da
//   venda, como na página Metas.
// - Dias de atendimento: em que dias da semana cada área comercial é visitada. A efetividade das ações conta as
//   visitas esperadas por eles (começou com a planilha do Power BI). Área pendente ou não atendida fica fora da conta.
// Tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";
import { iniciais } from "./conta.js";

const MODOS = [
  { id: "metas", nome: "Igual a Metas", icone: "alvo" },
  { id: "todos", nome: "Todos", icone: "pessoas" },
  { id: "alguns", nome: "Só alguns", icone: "usuario" },
];
const DIAS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]];
const FILTROS_AREA = [
  { id: "pendentes", nome: "Pendentes" }, { id: "atendidas", nome: "Com dias" },
  { id: "nao", nome: "Não atendidas" }, { id: "todas", nome: "Todas" },
];

let raiz = null;
let dados = null;          // resposta de /api/gestao/config
let orig = null, rasc = null;
let usuarioSel = null;
let buscaUsuario = "";
let secao = "usuarios";
let buscaArea = "", filtroArea = "pendentes";

const clone = (o) => JSON.parse(JSON.stringify(o));

export function configGestaoTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigGestao(container) {
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (q.get("u")) usuarioSel = q.get("u");
  if (q.get("secao") === "areas") secao = "areas";
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    carregarDados(await api("/api/gestao/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  orig = {
    usuarios: Object.fromEntries(dados.usuarios.map((u) => [u.login, {
      ve: (u.paginas || []).includes("gestao"),
      modo: u.gestao?.modo || "metas",
      vendedores: [...(u.gestao?.vendedores || [])].sort((a, b) => a - b),
    }])),
    areas: Object.fromEntries((dados.areas || []).map((a) => [a.id, a.dias])),  // null = pendente; [] = não atendida
  };
  rasc = clone(orig);
  if (!dados.usuarios.some((u) => u.login === usuarioSel)) usuarioSel = dados.usuarios[0]?.login ?? null;
}

// ---------- apoio ----------
function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

function usuarioMudou(login) {
  const a = rasc.usuarios[login], b = orig.usuarios[login];
  return a.ve !== b.ve || a.modo !== b.modo || (a.modo === "alguns" && JSON.stringify(a.vendedores) !== JSON.stringify(b.vendedores));
}

const areaMudou = (id) => JSON.stringify(rasc.areas[id]) !== JSON.stringify(orig.areas[id]);
const areasMudadas = () => Object.keys(rasc.areas).filter(areaMudou);
const pendentes = () => (dados.areas || []).filter((a) => rasc.areas[a.id] == null && a.ativos > 0).length;

function contarAlteracoes() { return Object.keys(rasc.usuarios).filter(usuarioMudou).length + areasMudadas().length; }

// Vendedores (com venda nos últimos 12 meses) que o usuário acompanha na Gestão, com o rascunho atual.
function vendedoresDoUsuario(u, r) {
  if (r.modo === "todos") return dados.vendedores;
  if (r.modo === "alguns") { const s = new Set(r.vendedores); return dados.vendedores.filter((v) => s.has(v.id)); }
  const grupos = new Set(dados.visoes.filter((v) => (u.visoes || []).includes(v.id)).flatMap((v) => v.grupos));
  const lista = u.vendedores ? new Set(u.vendedores) : null;
  return dados.vendedores.filter((v) => grupos.has(v.equipe) && (!lista || lista.has(v.id)));
}

function resumoCurto(u) {
  const r = rasc.usuarios[u.login];
  if (!r.ve) return "não vê a página";
  const n = vendedoresDoUsuario(u, r).length;
  const qtd = `${n} vendedor${n === 1 ? "" : "es"}`;
  return { metas: `igual a Metas · ${qtd}`, todos: "todos os vendedores", alguns: qtd }[r.modo];
}

// ---------- estrutura ----------
function render() {
  const nVe = dados.usuarios.filter((u) => rasc.usuarios[u.login].ve).length;
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${[["usuarios", "escudo", "Acesso por usuário", nVe], ["areas", "calendario", "Dias de atendimento", pendentes()]]
        .map(([id, ic, nome, n]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont">${n}</span></button>`).join("")}
      <div class="dica">${icone("info")} Cada pessoa vê as ações, os objetivos e o histórico dos vendedores do acesso dela.
        Só os administradores lançam e mudam. Os dias de atendimento das áreas valem para a efetividade.</div>
    </aside>
    <div id="cg-secao"></div>
  </div>
  <div class="barra-salvar" id="cg-barra">
    <span id="cg-n">Alterações não salvas</span>
    <button class="btn" id="cg-descartar">Descartar</button>
    <button class="btn primario" id="cg-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => {
    secao = b.dataset.secao;
    raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x === b));
    renderSecao();
  }));
  raiz.querySelector("#cg-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cg-descartar").addEventListener("click", () => { rasc = clone(orig); render(); });
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cg-secao");
  if (secao === "areas") secaoAreas(alvo);
  else secaoUsuarios(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cg-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cg-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  const conts = raiz.querySelectorAll(".config-menu .cont");
  conts[0].textContent = dados.usuarios.filter((u) => rasc.usuarios[u.login].ve).length;
  conts[1].textContent = pendentes();
}

// ======================================================================================
// Dias de atendimento das áreas comerciais
// ======================================================================================
function secaoAreas(alvo) {
  const n = pendentes();
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("calendario")}Dias de atendimento das áreas</h2>
      <p class="sub">A efetividade das ações conta uma visita esperada por cliente ativo da área em cada dia marcado.
        Área pendente ou não atendida fica fora da conta (pedidos e visitas).</p></div></div>
    ${dados.aviso_areas ? `<div class="aviso">${icone("alerta")}<span>${esc(dados.aviso_areas)}</span></div>` : ""}
    ${n ? `<p class="usu-nota aviso-nota">${icone("alerta")}<span>${n} área${n === 1 ? "" : "s"} com clientes ativos ainda sem dia: os clientes delas ficam fora da efetividade.</span></p>` : ""}
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="ca-busca" type="search" placeholder="Buscar área ou código" value="${esc(buscaArea)}"></label>
      <div class="seg-mini" role="group" aria-label="Quais áreas">${FILTROS_AREA.map((f) => `<button type="button" data-filtro="${f.id}" class="${filtroArea === f.id ? "ativo" : ""}">${f.nome}</button>`).join("")}</div>
      <button class="btn" type="button" id="ca-sugestoes" title="Nas áreas pendentes, marca o dia que o nome da área diz (ex.: “TEIXEIRA (SEXTA)”)">${icone("raio")}Usar o dia do nome nas pendentes</button>
    </div>
    <div class="areas-lista" id="ca-lista"></div>
  </section>`;
  alvo.querySelector("#ca-busca").addEventListener("input", (e) => { buscaArea = e.target.value; desenharAreas(); });
  alvo.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => {
    filtroArea = b.dataset.filtro;
    alvo.querySelectorAll("[data-filtro]").forEach((x) => x.classList.toggle("ativo", x === b));
    desenharAreas();
  }));
  alvo.querySelector("#ca-sugestoes").addEventListener("click", () => {
    let n = 0;
    for (const a of dados.areas) if (rasc.areas[a.id] == null && a.sugestao?.length) { rasc.areas[a.id] = [...a.sugestao]; n++; }
    toast(n ? `${n} área${n === 1 ? "" : "s"} com o dia do nome (confira e salve)` : "Nenhuma pendente com o dia no nome", n ? "ok" : "erro");
    desenharAreas();
    atualizarBarra();
  });
  alvo.querySelector("#ca-lista").addEventListener("click", aoClicarArea);
  desenharAreas();
}

function estadoArea(a) {
  const d = rasc.areas[a.id];
  if (d == null) return "pendente";
  return d.length ? "atendida" : "nao";
}

function desenharAreas() {
  const termo = buscaArea.trim().toLowerCase();
  const lista = (dados.areas || []).filter((a) => {
    const st = estadoArea(a);
    if (filtroArea === "pendentes" && st !== "pendente") return false;
    if (filtroArea === "atendidas" && st !== "atendida") return false;
    if (filtroArea === "nao" && st !== "nao") return false;
    return !termo || `${a.nome} ${a.id}`.toLowerCase().includes(termo);
  }).sort((x, y) => (y.ativos - x.ativos) || x.nome.localeCompare(y.nome));
  const el = raiz.querySelector("#ca-lista");
  if (!lista.length) {
    el.innerHTML = `<p class="usu-nota">${icone("busca")}<span>${filtroArea === "pendentes" && !termo ? "Nenhuma área pendente." : "Nenhuma área com esse filtro."}</span></p>`;
    return;
  }
  el.innerHTML = lista.map((a) => {
    const dias = rasc.areas[a.id] || [];
    const st = estadoArea(a);
    const chip = { pendente: `<span class="chip-papel inativo">Pendente</span>`, nao: `<span class="chip-papel inativo">Não atendida</span>`,
                   atendida: `<span class="chip-papel">${dias.length} dia${dias.length === 1 ? "" : "s"}</span>` }[st];
    const sug = st === "pendente" && a.sugestao?.length
      ? `<button class="btn" type="button" data-sugestao="${a.id}">Usar ${a.sugestao.map((d) => DIAS[d - 1][1]).join(", ")}</button>` : "";
    return `<div class="area-linha ${areaMudou(a.id) ? "mudou" : ""}" data-id="${a.id}">
      <div class="n"><b>${esc(a.nome)}${areaMudou(a.id) ? " <em>(alterada)</em>" : ""}</b>
        <small>código ${a.id} · ${fmt.num(a.ativos)} cliente${a.ativos === 1 ? "" : "s"} ativo${a.ativos === 1 ? "" : "s"}${a.vendedores?.length ? ` · ${esc(a.vendedores.join(", "))}` : ""}${a.atualizada_por_nome && !areaMudou(a.id) ? ` · por ${esc(a.atualizada_por_nome)}` : ""}</small></div>
      <div class="dias-semana" role="group" aria-label="Dias de atendimento de ${esc(a.nome)}">${DIAS.map(([d, n]) =>
        `<button type="button" data-dia="${d}" aria-pressed="${dias.includes(d)}" class="${dias.includes(d) ? "ativo" : ""}">${n}</button>`).join("")}</div>
      <div class="area-acoes">${chip}${sug}
        <button class="btn icone" type="button" data-nao="${a.id}" title="Não atendida (fica fora da efetividade, sem aviso)" aria-label="Marcar ${esc(a.nome)} como não atendida">${icone("menos")}</button>
        <button class="btn icone" type="button" data-limpar="${a.id}" title="Voltar a pendente" aria-label="Voltar ${esc(a.nome)} a pendente">${icone("restaurar")}</button></div>
    </div>`;
  }).join("");
}

function aoClicarArea(e) {
  const b = e.target.closest("button");
  const linha = e.target.closest(".area-linha");
  if (!b || !linha) return;
  const id = Number(linha.dataset.id);
  const a = dados.areas.find((x) => x.id === id);
  if (b.dataset.dia) {
    const d = Number(b.dataset.dia);
    const atual = new Set(rasc.areas[id] || []);
    atual.has(d) ? atual.delete(d) : atual.add(d);
    rasc.areas[id] = [...atual].sort((x, y) => x - y);
  } else if (b.dataset.sugestao) rasc.areas[id] = [...a.sugestao];
  else if (b.dataset.nao) rasc.areas[id] = [];
  else if (b.dataset.limpar) rasc.areas[id] = null;
  else return;
  desenharAreas();
  atualizarBarra();
}

// ======================================================================================
// Acesso por usuário
// ======================================================================================
function secaoUsuarios(alvo) {
  if (!dados.usuarios.length) {
    alvo.innerHTML = `<section class="cartao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div><h3>Ainda não há visualizadores</h3>
      <p>Cadastre as pessoas em <b>Usuários</b>; depois, aqui você escolhe quais vendedores cada uma acompanha.</p>
      <a class="btn primario" href="#/usuarios">${icone("escudo")}Abrir Usuários</a></section>`;
    return;
  }
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios">
    <aside class="cartao usu-lista entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("escudo")}Visualizadores</h2>
        <p class="sub">Quem usa a Gestão e quais vendedores acompanha</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="cg-busca-u" type="search" placeholder="Buscar pessoa" value="${esc(buscaUsuario)}"></label>
      <div class="usu-itens" id="cg-itens"></div>
      <div class="dica">${icone("info")}<span>Nome, senha e páginas ficam em <a href="#/usuarios">Usuários</a>; as abas e os
        vendedores de Metas, em <a href="#/configuracoes?secao=usuarios">Metas › Configurar</a>.</span></div>
    </aside>
    <div id="cg-editor"></div>
  </div>`;
  alvo.querySelector("#cg-busca-u").addEventListener("input", (e) => { buscaUsuario = e.target.value; desenharItens(); });
  desenharItens();
  desenharEditor();
}

function desenharItens() {
  const termo = buscaUsuario.trim().toLowerCase();
  const el = raiz.querySelector("#cg-itens");
  el.innerHTML = dados.usuarios.filter((u) => !termo || `${u.nome} ${u.login}`.toLowerCase().includes(termo)).map((u, i) => {
    const r = rasc.usuarios[u.login];
    return `<button type="button" class="usu-item ${u.login === usuarioSel ? "selecionado" : ""} ${r.ve ? "" : "inativo"}" data-login="${esc(u.login)}" style="--i:${i}">
      <span class="avatar">${esc(iniciais(u.nome))}</span>
      <span class="t"><b>${esc(u.nome)}${usuarioMudou(u.login) ? " <em>(alterado)</em>" : ""}</b><small>${esc(u.login)} · ${esc(resumoCurto(u))}</small></span>
      <span class="chip-papel ${r.ve ? "" : "inativo"}">${r.ve ? "Usa" : "Não usa"}</span>
    </button>`;
  }).join("") || `<p class="usu-nota">${icone("busca")}Ninguém com esse nome.</p>`;
  el.querySelectorAll(".usu-item").forEach((b) => b.addEventListener("click", () => {
    usuarioSel = b.dataset.login;
    desenharItens();
    desenharEditor();
  }));
}

function desenharEditor() {
  const alvo = raiz.querySelector("#cg-editor");
  const u = dados.usuarios.find((x) => x.login === usuarioSel);
  if (!u) { alvo.innerHTML = ""; return; }
  const r = rasc.usuarios[u.login];
  const idx = MODOS.findIndex((m) => m.id === r.modo);
  const outras = (u.paginas || []).filter((p) => p !== "gestao");
  alvo.innerHTML = `
  <section class="cartao usu-editor entra" style="--i:2">
    <div class="cartao-cab"><div>
      <h2>${icone("quadro")}Gestão de ${esc(u.nome)}</h2>
      <p class="sub">${esc(u.login)}${u.ativo ? "" : " · acesso desativado em Usuários"}</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${r.ve ? "ligada" : ""}" id="cg-ve" type="button" role="switch" aria-checked="${r.ve}" aria-label="Usa a Gestão"></button>
      <div><b>Usa a Gestão</b><p>${r.ve ? "A página aparece na barra lateral desta pessoa, que acompanha as ações, os objetivos e o histórico dos vendedores do acesso (também pelo Assistente)." : "Desligado, a página some da barra lateral e o servidor recusa os pedidos."}
        ${!outras.length && r.ve ? " É a única página dela: para tirar, libere outra antes em Usuários." : ""}</p></div>
    </div>
    <div ${r.ve ? "" : "hidden"}>
      <h3 class="usu-titulo">Vendedores que acompanha</h3>
      <div class="seletor cp-modo" data-v="${idx}" role="radiogroup" aria-label="Vendedores que acompanha"><span class="marcador"></span>
        ${MODOS.map((m) => `<button type="button" role="radio" data-modo="${m.id}" aria-checked="${m.id === r.modo}" class="${m.id === r.modo ? "ativo" : ""}">${icone(m.icone)}${m.nome}</button>`).join("")}
      </div>
      <div id="cg-modo-detalhe"></div>
    </div>
    <div class="usu-resumo" id="cg-resumo-u"></div>
    <p class="form-erro" id="cg-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#cg-ve").addEventListener("click", () => {
    r.ve = !r.ve;
    desenharEditor();
    desenharItens();
    atualizarBarra();
  });
  alvo.querySelectorAll(".cp-modo button").forEach((b) => b.addEventListener("click", () => {
    r.modo = b.dataset.modo;
    const sel = alvo.querySelector(".cp-modo");
    sel.dataset.v = MODOS.findIndex((m) => m.id === r.modo);
    sel.querySelectorAll("button").forEach((x) => { x.classList.toggle("ativo", x === b); x.setAttribute("aria-checked", x === b); });
    desenharModo(u);
    desenharItens();
    atualizarBarra();
  }));
  desenharModo(u);
}

function desenharModo(u) {
  const r = rasc.usuarios[u.login];
  const alvo = raiz.querySelector("#cg-modo-detalhe");
  if (r.modo === "metas") {
    const abas = dados.visoes.filter((v) => (u.visoes || []).includes(v.id));
    const link = `<a href="#/configuracoes?u=${encodeURIComponent(u.login)}">Metas › Configurar</a>`;
    if (!abas.length) {
      alvo.innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Esta pessoa não tem abas de Metas (${link}), então não teria nenhum vendedor. Escolha "Todos" ou "Só alguns".</span></p>`;
    } else {
      const equipes = [...new Set(abas.flatMap((v) => v.grupos))].map((g) => (g === "EDIR" ? "Edir" : g));
      const vend = u.vendedores ? `só os ${u.vendedores.length} vendedores marcados lá` : "todos os vendedores dessas equipes";
      alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Segue o acesso de Metas (${link}): equipes ${esc(emLista(equipes))}
        e ${vend}. Se o acesso de Metas mudar, este muda junto.</span></p>`;
    }
  } else if (r.modo === "todos") {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Acompanha qualquer vendedor, inclusive os que entrarem depois.</span></p>`;
  } else {
    desenharEscolha(u);
  }
  atualizarResumoU(u);
}

function desenharEscolha(u) {
  const r = rasc.usuarios[u.login];
  const alvo = raiz.querySelector("#cg-modo-detalhe");
  const marcados = new Set(r.vendedores);
  const conhecidos = new Set(dados.vendedores.map((v) => v.id));
  // marcados que não venderam nos últimos 12 meses continuam na lista, para poder desmarcar
  const lista = [...dados.vendedores, ...r.vendedores.filter((id) => !conhecidos.has(id))
    .map((id) => ({ id, nome: `Vendedor ${id}`, nome_erp: "", rotulo_equipe: "sem venda em 12 meses" }))];
  alvo.innerHTML = `
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cg-busca-v" type="search" placeholder="Buscar vendedor ou código"></label>
      <span class="usu-cont" id="cg-cont"></span>
      <button class="btn" type="button" id="cg-todos">Marcar os da lista</button>
      <button class="btn" type="button" id="cg-nenhum">Desmarcar todos</button>
    </div>
    <div class="vend-escolha">${lista.map((v) => `
      <label class="vend-op" data-busca="${esc(`${v.nome} ${v.nome_erp} ${v.id}`.toLowerCase())}">
        <input type="checkbox" data-id="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(v.rotulo_equipe)}${v.venda_12m ? ` · ${fmt.moedaC(v.venda_12m)} em 12 meses` : ""}</small></span>
      </label>`).join("")}</div>`;
  const contar = () => {
    const n = r.vendedores.length;
    alvo.querySelector("#cg-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
  };
  const definir = (ids) => {
    r.vendedores = [...ids].sort((a, b) => a - b);
    alvo.querySelectorAll(".vend-op input").forEach((c) => { c.checked = ids.has(Number(c.dataset.id)); });
    contar();
    atualizarResumoU(u);
    desenharItens();
    atualizarBarra();
  };
  alvo.querySelector("#cg-busca-v").addEventListener("input", (e) => {
    const termo = e.target.value.trim().toLowerCase();
    alvo.querySelectorAll(".vend-op").forEach((el) => { el.hidden = !!termo && !el.dataset.busca.includes(termo); });
  });
  alvo.querySelectorAll(".vend-op input").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(r.vendedores);
    c.checked ? ids.add(Number(c.dataset.id)) : ids.delete(Number(c.dataset.id));
    definir(ids);
  }));
  alvo.querySelector("#cg-todos").addEventListener("click", () => {
    const ids = new Set(r.vendedores);
    alvo.querySelectorAll(".vend-op:not([hidden]) input").forEach((c) => ids.add(Number(c.dataset.id)));
    definir(ids);
  });
  alvo.querySelector("#cg-nenhum").addEventListener("click", () => definir(new Set()));
  contar();
}

function atualizarResumoU(u) {
  const el = raiz.querySelector("#cg-resumo-u");
  if (!el) return;
  const r = rasc.usuarios[u.login];
  const quem = `<b>${esc(u.nome)}</b>`;
  let txt;
  if (!r.ve) txt = `${quem} não usa a Gestão.`;
  else if (r.modo === "todos") txt = `${quem} acompanha <b>qualquer vendedor</b>.`;
  else {
    const vendo = vendedoresDoUsuario(u, r);
    if (!vendo.length) txt = `${quem} vê a página, mas <b>nenhum vendedor</b>: não veria nenhuma ação.`;
    else if (vendo.length <= 4) txt = `${quem} acompanha só ${emLista(vendo.map((v) => `<b>${esc(v.nome)}</b>`))}.`;
    else txt = `${quem} acompanha <b>${vendo.length} vendedores</b>; os demais não aparecem para ela.`;
  }
  el.innerHTML = `${icone("olho")}<span>${txt}</span>`;
}

// ---------- gravação ----------
async function salvar() {
  const btn = raiz.querySelector("#cg-salvar");
  for (const u of dados.usuarios) {
    const r = rasc.usuarios[u.login];
    if (!usuarioMudou(u.login)) continue;
    if (r.ve && r.modo === "alguns" && !r.vendedores.length) return erroUsuario(u, "marque ao menos um vendedor, ou escolha outra opção");
    if (!r.ve && !(u.paginas || []).some((p) => p !== "gestao")) return erroUsuario(u, "é a única página desta pessoa; libere outra em Usuários antes de tirar esta");
  }
  const usuarios = Object.fromEntries(dados.usuarios.filter((u) => usuarioMudou(u.login)).map((u) => {
    const r = rasc.usuarios[u.login];
    return [u.login, { ve: r.ve, modo: r.modo, vendedores: r.modo === "alguns" ? r.vendedores : null }];
  }));
  const areas = Object.fromEntries(areasMudadas().map((id) => [id, rasc.areas[id]]));
  btn.disabled = true;
  try {
    carregarDados(await api("/api/gestao/config", { json: { usuarios, areas } }));
    toast("Configuração da Gestão salva");
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

function erroUsuario(u, msg) {
  usuarioSel = u.login;
  secao = "usuarios";
  render();
  const el = raiz.querySelector("#cg-erro");
  el.textContent = `${u.nome}: ${msg}.`;
  el.hidden = false;
  toast(`${u.nome}: ${msg}`, "erro");
}
