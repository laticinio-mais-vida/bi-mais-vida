// Configuração da página Projeções (só administradores): quais vendedores entram na página e quais vendedores
// cada visualizador vê nela. Vendedores novos das equipes ES, BA e Edir entram sozinhos; a lista guarda só quem
// foi desmarcado dessas equipes ou incluído de fora delas. Tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";
import { iniciais } from "./conta.js";

const MODOS = [
  { id: "metas", nome: "Igual a Metas", icone: "alvo" },
  { id: "todos", nome: "Todos da página", icone: "pessoas" },
  { id: "alguns", nome: "Só alguns", icone: "usuario" },
];

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/projecoes/config
let orig = null, rasc = null;
let secao = "vendedores";
let usuarioSel = null;
const filtro = { busca: "", situacao: "todos", equipe: "" };
let buscaUsuario = "";

const clone = (o) => JSON.parse(JSON.stringify(o));

export function configProjecoesTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigProjecoes(container, contexto) {
  ctx = contexto;
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (q.get("u")) { secao = "usuarios"; usuarioSel = q.get("u"); }
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    carregarDados(await api("/api/projecoes/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  orig = {
    pagina: dados.vendedores.filter((v) => v.na_pagina).map((v) => v.id).sort((a, b) => a - b),
    usuarios: Object.fromEntries(dados.usuarios.map((u) => [u.login, {
      ve: (u.paginas || []).includes("projecoes"),
      modo: u.projecoes?.modo || "metas",
      vendedores: [...(u.projecoes?.vendedores || [])].sort((a, b) => a - b),
    }])),
  };
  rasc = clone(orig);
  if (!dados.usuarios.some((u) => u.login === usuarioSel)) usuarioSel = dados.usuarios[0]?.login ?? null;
}

// ---------- apoio ----------
const naPagina = () => new Set(rasc.pagina);
const vendedor = (id) => dados.vendedores.find((v) => v.id === id);
const nomeVend = (id) => vendedor(id)?.nome || `Vendedor ${id}`;

function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

function usuarioMudou(login) {
  const a = rasc.usuarios[login], b = orig.usuarios[login];
  return a.ve !== b.ve || a.modo !== b.modo || (a.modo === "alguns" && JSON.stringify(a.vendedores) !== JSON.stringify(b.vendedores));
}

function contarAlteracoes() {
  const a = new Set(rasc.pagina), b = new Set(orig.pagina);
  let n = [...a].filter((id) => !b.has(id)).length + [...b].filter((id) => !a.has(id)).length;
  n += Object.keys(rasc.usuarios).filter(usuarioMudou).length;
  return n;
}

// Vendedores da página que o usuário vê, com o rascunho atual.
function vendedoresDoUsuario(u, r) {
  const pagina = dados.vendedores.filter((v) => naPagina().has(v.id));
  if (r.modo === "todos") return pagina;
  if (r.modo === "alguns") { const s = new Set(r.vendedores); return pagina.filter((v) => s.has(v.id)); }
  const grupos = new Set(dados.visoes.filter((v) => (u.visoes || []).includes(v.id)).flatMap((v) => v.grupos));
  const lista = u.vendedores ? new Set(u.vendedores) : null;
  return pagina.filter((v) => grupos.has(v.equipe) && (!lista || lista.has(v.id)));
}

function resumoCurto(u) {
  const r = rasc.usuarios[u.login];
  if (!r.ve) return "não vê a página";
  const n = vendedoresDoUsuario(u, r).length;
  const qtd = `${n} vendedor${n === 1 ? "" : "es"}`;
  return { metas: `igual a Metas · ${qtd}`, todos: `todos · ${qtd}`, alguns: qtd }[r.modo];
}

// ---------- estrutura ----------
function render() {
  const nPagina = rasc.pagina.length;
  const nVe = dados.usuarios.filter((u) => rasc.usuarios[u.login].ve).length;
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${[["vendedores", "pessoas", "Vendedores da página", nPagina], ["usuarios", "escudo", "Acesso por usuário", nVe]]
        .map(([id, ic, nome, n]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont">${n}</span></button>`).join("")}
      <div class="dica">${icone("info")} Vale só para a página Projeções, assim que você salvar. As metas e o ERP não mudam.
        Administradores veem todos os vendedores da página.</div>
    </aside>
    <div id="cp-secao"></div>
  </div>
  <div class="barra-salvar" id="cp-barra">
    <span id="cp-n">Alterações não salvas</span>
    <button class="btn" id="cp-descartar">Descartar</button>
    <button class="btn primario" id="cp-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => {
    secao = b.dataset.secao;
    raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x === b));
    renderSecao();
  }));
  raiz.querySelector("#cp-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cp-descartar").addEventListener("click", () => { rasc = clone(orig); render(); });
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cp-secao");
  if (secao === "usuarios") secaoUsuarios(alvo);
  else secaoVendedores(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cp-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cp-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  const conts = raiz.querySelectorAll(".config-menu .cont");
  conts[0].textContent = rasc.pagina.length;
  conts[1].textContent = dados.usuarios.filter((u) => rasc.usuarios[u.login].ve).length;
}

// ======================================================================================
// Vendedores da página
// ======================================================================================
function secaoVendedores(alvo) {
  const equipes = dados.equipes.filter((e) => dados.vendedores.some((v) => v.equipe === e.id));
  const automaticas = emLista(dados.equipes.filter((e) => e.padrao).map((e) => e.nome));
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("pessoas")}Vendedores que entram nas projeções</h2>
      <p class="sub">Os marcados entram nos totais, nos gráficos e no filtro da página. Vendedores novos das equipes
        ${esc(automaticas)} entram sozinhos; desmarque contas internas ou quem não deve contar. As equipes vêm de
        Configurações das metas. Lista: todos os vendedores com venda desde 2024.</p>
    </div></div>
    <div class="resumo-grupos" id="cp-resumo"></div>
    <div class="barra-ferramentas">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cp-busca" type="search" placeholder="Buscar vendedor ou código" value="${esc(filtro.busca)}"></label>
      <div class="filtro-chips" id="cp-chips"></div>
      <label class="campo"><select id="cp-equipe" style="padding-left:14px"><option value="">Todas as equipes</option>
        ${equipes.map((e) => `<option value="${e.id}" ${filtro.equipe === e.id ? "selected" : ""}>${esc(e.nome)}</option>`).join("")}</select></label>
    </div>
    <div class="barra-ferramentas" id="cp-lote"></div>
    <div class="lista-produtos" id="cp-lista"></div>
  </section>`;
  alvo.querySelector("#cp-busca").addEventListener("input", (e) => { filtro.busca = e.target.value; desenharVendedores(); });
  alvo.querySelector("#cp-equipe").addEventListener("change", (e) => { filtro.equipe = e.target.value; desenharVendedores(); });
  desenharResumo();
  desenharVendedores();
}

function desenharResumo() {
  const el = raiz.querySelector("#cp-resumo");
  if (!el) return;
  const pag = naPagina();
  const dentro = dados.vendedores.filter((v) => pag.has(v.id)), fora = dados.vendedores.filter((v) => !pag.has(v.id));
  const soma = (l) => l.reduce((s, v) => s + v.venda_12m, 0);
  const total = soma(dados.vendedores) || 1;
  el.innerHTML = [
    ["var(--s-fat)", "certo", "Na página", dentro.length, `${fmt.moedaC(soma(dentro))} em 12 meses · ${fmt.pct(soma(dentro) / total, 0)} da venda bruta`],
    ["var(--linha-forte)", "menos", "Fora da página", fora.length, `${fmt.moedaC(soma(fora))} em 12 meses`],
    ["var(--laranja)", "raio", "Alterados", contarAlteracoesPagina(), "desde a última vez que salvou"],
  ].map(([c, ic, t, n, s]) => `<div class="resumo-grupo" style="--c:${c}"><div class="t">${icone(ic)}${t}</div>
    <div class="n">${n} <span style="font-size:14px;color:var(--tinta-3);font-weight:600">${t === "Alterados" ? "" : "vendedores"}</span></div>
    <div class="s">${s}</div></div>`).join("");
}

function contarAlteracoesPagina() {
  const a = new Set(rasc.pagina), b = new Set(orig.pagina);
  return [...a].filter((id) => !b.has(id)).length + [...b].filter((id) => !a.has(id)).length;
}

function vendedoresFiltrados() {
  const pag = naPagina(), ori = new Set(orig.pagina);
  const b = filtro.busca.trim().toLowerCase();
  return dados.vendedores.filter((v) => {
    if (b && !`${v.nome} ${v.nome_erp} ${v.id} ${v.supervisor}`.toLowerCase().includes(b)) return false;
    if (filtro.equipe && v.equipe !== filtro.equipe) return false;
    if (filtro.situacao === "dentro") return pag.has(v.id);
    if (filtro.situacao === "fora") return !pag.has(v.id);
    if (filtro.situacao === "alterados") return pag.has(v.id) !== ori.has(v.id);
    return true;
  });
}

function desenharVendedores() {
  const chips = [["todos", "Todos"], ["dentro", "Na página"], ["fora", "Fora da página"], ["alterados", "Alterados"]];
  const elChips = raiz.querySelector("#cp-chips");
  elChips.innerHTML = chips.map(([id, n]) => `<button class="filtro-chip ${filtro.situacao === id ? "ativo" : ""}" data-f="${id}">${n}</button>`).join("");
  elChips.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { filtro.situacao = b.dataset.f; desenharVendedores(); }));

  const lista = vendedoresFiltrados();
  const lote = raiz.querySelector("#cp-lote");
  lote.innerHTML = lista.length > 1 ? `<span style="font-size:13px;color:var(--tinta-3);font-weight:600">${lista.length} vendedores na lista:</span>
    <button class="btn" data-lote="1" style="height:34px">${icone("certo")}Marcar todos</button>
    <button class="btn" data-lote="0" style="height:34px">${icone("menos")}Desmarcar todos</button>` : "";
  lote.querySelectorAll("[data-lote]").forEach((b) => b.addEventListener("click", () => {
    const pag = naPagina();
    lista.forEach((v) => (b.dataset.lote === "1" ? pag.add(v.id) : pag.delete(v.id)));
    definirPagina(pag);
    desenharVendedores();
  }));

  const el = raiz.querySelector("#cp-lista");
  if (!lista.length) { el.innerHTML = `<div class="vazio">${icone("busca")}<p>Nenhum vendedor com esses filtros.</p></div>`; return; }
  const pag = naPagina(), ori = new Set(orig.pagina);
  const limite = new Date(dados.data_ref + "T12:00"); limite.setMonth(limite.getMonth() - 6);
  el.innerHTML = lista.map((v, i) => {
    const on = pag.has(v.id);
    const antigo = !v.ultima_venda || new Date(v.ultima_venda + "T12:00") < limite;
    const detalhe = [`código ${v.id}`, v.nome_erp && v.nome_erp.toLowerCase() !== v.nome.toLowerCase() ? `ERP: ${v.nome_erp}` : "",
      v.supervisor ? `sup. ${v.supervisor}` : "", v.inativo ? "inativo no ERP" : ""].filter(Boolean).join(" · ");
    const nota = !v.padrao ? "fora das equipes: só entra se marcar" : "";
    return `<div class="cp-vend ${on ? "" : "desligado"} ${antigo ? "antigo" : ""} ${on !== ori.has(v.id) ? "alterado" : ""}" style="--i:${i}">
      <button class="chave ${on ? "ligada" : ""}" type="button" role="switch" aria-checked="${on}" data-id="${v.id}" aria-label="${esc(v.nome)} entra na página"></button>
      <div class="prod-nome">${esc(v.nome)}<small>${esc(detalhe)}</small>${nota ? `<span class="alerta">${icone("info")}${nota}</span>` : ""}</div>
      <span class="chip-equipe e-${esc(v.equipe)}">${esc(v.rotulo_equipe)}</span>
      <div class="prod-vendido">${v.venda_12m ? fmt.moedaC(v.venda_12m) : "—"}<small>${v.ultima_venda ? `última venda ${fmt.data(v.ultima_venda)}` : "sem venda"}</small></div>
    </div>`;
  }).join("");
  el.querySelectorAll(".chave[data-id]").forEach((b) => b.addEventListener("click", () => {
    const id = Number(b.dataset.id);
    const pag2 = naPagina();
    pag2.has(id) ? pag2.delete(id) : pag2.add(id);
    definirPagina(pag2);
    const on = pag2.has(id);
    b.classList.toggle("ligada", on);
    b.setAttribute("aria-checked", on);
    const linha = b.closest(".cp-vend");
    linha.classList.toggle("desligado", !on);
    linha.classList.toggle("alterado", on !== new Set(orig.pagina).has(id));
  }));
}

function definirPagina(conjunto) {
  rasc.pagina = [...conjunto].sort((a, b) => a - b);
  desenharResumo();
  atualizarBarra();
}

// ======================================================================================
// Acesso por usuário
// ======================================================================================
function secaoUsuarios(alvo) {
  if (!dados.usuarios.length) {
    alvo.innerHTML = `<section class="cartao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div><h3>Ainda não há visualizadores</h3>
      <p>Cadastre as pessoas em <b>Usuários</b>; depois, aqui você escolhe quais vendedores cada uma vê nas Projeções.</p>
      <a class="btn primario" href="#/usuarios">${icone("escudo")}Abrir Usuários</a></section>`;
    return;
  }
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios">
    <aside class="cartao usu-lista entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("escudo")}Visualizadores</h2>
        <p class="sub">Quem vê a página e quais vendedores aparecem para cada um</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="cp-busca-u" type="search" placeholder="Buscar pessoa" value="${esc(buscaUsuario)}"></label>
      <div class="usu-itens" id="cp-itens"></div>
      <div class="dica">${icone("info")}<span>Nome, senha e páginas ficam em <a href="#/usuarios">Usuários</a>; as abas e os
        vendedores de Metas, em <a href="#/configuracoes?secao=usuarios">Metas › Configurar</a>.</span></div>
    </aside>
    <div id="cp-editor"></div>
  </div>`;
  alvo.querySelector("#cp-busca-u").addEventListener("input", (e) => { buscaUsuario = e.target.value; desenharItens(); });
  desenharItens();
  desenharEditor();
}

function desenharItens() {
  const termo = buscaUsuario.trim().toLowerCase();
  const el = raiz.querySelector("#cp-itens");
  el.innerHTML = dados.usuarios.filter((u) => !termo || `${u.nome} ${u.login}`.toLowerCase().includes(termo)).map((u, i) => {
    const r = rasc.usuarios[u.login];
    return `<button type="button" class="usu-item ${u.login === usuarioSel ? "selecionado" : ""} ${r.ve ? "" : "inativo"}" data-login="${esc(u.login)}" style="--i:${i}">
      <span class="avatar">${esc(iniciais(u.nome))}</span>
      <span class="t"><b>${esc(u.nome)}${usuarioMudou(u.login) ? ' <em>(alterado)</em>' : ""}</b><small>${esc(u.login)} · ${esc(resumoCurto(u))}</small></span>
      <span class="chip-papel ${r.ve ? "" : "inativo"}">${r.ve ? "Vê" : "Não vê"}</span>
    </button>`;
  }).join("") || `<p class="usu-nota">${icone("busca")}Ninguém com esse nome.</p>`;
  el.querySelectorAll(".usu-item").forEach((b) => b.addEventListener("click", () => {
    usuarioSel = b.dataset.login;
    desenharItens();
    desenharEditor();
  }));
}

function desenharEditor() {
  const alvo = raiz.querySelector("#cp-editor");
  const u = dados.usuarios.find((x) => x.login === usuarioSel);
  if (!u) { alvo.innerHTML = ""; return; }
  const r = rasc.usuarios[u.login];
  const idx = MODOS.findIndex((m) => m.id === r.modo);
  const outras = (u.paginas || []).filter((p) => p !== "projecoes");
  alvo.innerHTML = `
  <section class="cartao usu-editor entra" style="--i:2">
    <div class="cartao-cab"><div>
      <h2>${icone("tendencia")}Projeções de ${esc(u.nome)}</h2>
      <p class="sub">${esc(u.login)}${u.ativo ? "" : " · acesso desativado em Usuários"}</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${r.ve ? "ligada" : ""}" id="cp-ve" type="button" role="switch" aria-checked="${r.ve}" aria-label="Vê a página Projeções"></button>
      <div><b>Vê a página Projeções</b><p>${r.ve ? "A página aparece na barra lateral desta pessoa." : "Desligado, a página some da barra lateral e o servidor não manda os números."}
        ${!outras.length && r.ve ? " É a única página dela: para tirar, libere outra antes em Usuários." : ""}</p></div>
    </div>
    <div id="cp-vendedores-u" ${r.ve ? "" : "hidden"}>
      <h3 class="usu-titulo">Vendedores que vê</h3>
      <div class="seletor cp-modo" data-v="${idx}" role="radiogroup" aria-label="Vendedores que vê"><span class="marcador"></span>
        ${MODOS.map((m) => `<button type="button" role="radio" data-modo="${m.id}" aria-checked="${m.id === r.modo}" class="${m.id === r.modo ? "ativo" : ""}">${icone(m.icone)}${m.nome}</button>`).join("")}
      </div>
      <div id="cp-modo-detalhe"></div>
    </div>
    <div class="usu-resumo" id="cp-resumo-u"></div>
    <p class="form-erro" id="cp-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#cp-ve").addEventListener("click", (e) => {
    r.ve = !r.ve;
    e.currentTarget.classList.toggle("ligada", r.ve);
    e.currentTarget.setAttribute("aria-checked", r.ve);
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
  const alvo = raiz.querySelector("#cp-modo-detalhe");
  const vendo = vendedoresDoUsuario(u, r);
  if (r.modo === "metas") {
    const abas = dados.visoes.filter((v) => (u.visoes || []).includes(v.id));
    const link = `<a href="#/configuracoes?u=${encodeURIComponent(u.login)}">Metas › Configurar</a>`;
    if (!abas.length) {
      alvo.innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Esta pessoa não tem abas de Metas (${link}), então não veria nenhum vendedor. Escolha "Todos da página" ou "Só alguns".</span></p>`;
    } else {
      const equipes = [...new Set(abas.flatMap((v) => v.grupos))].map((g) => (g === "EDIR" ? "Edir" : g));
      const vend = u.vendedores ? `só os ${u.vendedores.length} vendedores marcados lá` : "todos os vendedores dessas equipes";
      alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Segue o acesso de Metas (${link}): abas ${esc(emLista(abas.map((a) => a.titulo)))}
        (equipes ${esc(emLista(equipes))}) e ${vend}. Se o acesso de Metas mudar, este muda junto.</span></p>`;
    }
  } else if (r.modo === "todos") {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Vê os ${vendo.length} vendedores da página, inclusive os que entrarem depois.</span></p>`;
  } else {
    desenharEscolha(u);
  }
  atualizarResumoU(u);
}

function desenharEscolha(u) {
  const r = rasc.usuarios[u.login];
  const alvo = raiz.querySelector("#cp-modo-detalhe");
  const pag = naPagina();
  const marcados = new Set(r.vendedores);
  const lista = dados.vendedores.filter((v) => pag.has(v.id) || marcados.has(v.id));
  alvo.innerHTML = `
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cp-busca-v" type="search" placeholder="Buscar vendedor ou código"></label>
      <span class="usu-cont" id="cp-cont"></span>
      <button class="btn" type="button" id="cp-todos">Marcar os da lista</button>
      <button class="btn" type="button" id="cp-nenhum">Desmarcar todos</button>
    </div>
    <div class="vend-escolha">${lista.map((v) => `
      <label class="vend-op" data-busca="${esc(`${v.nome} ${v.nome_erp} ${v.id}`.toLowerCase())}">
        <input type="checkbox" data-id="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(v.rotulo_equipe)}${pag.has(v.id) ? "" : " · fora da página"}</small></span>
      </label>`).join("")}</div>`;
  const contar = () => {
    const n = r.vendedores.length;
    alvo.querySelector("#cp-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
    atualizarResumoU(u);
    desenharItens();
    atualizarBarra();
  };
  const definir = (ids) => {
    r.vendedores = [...ids].sort((a, b) => a - b);
    alvo.querySelectorAll(".vend-op input").forEach((c) => { c.checked = ids.has(Number(c.dataset.id)); });
    contar();
  };
  alvo.querySelector("#cp-busca-v").addEventListener("input", (e) => {
    const termo = e.target.value.trim().toLowerCase();
    alvo.querySelectorAll(".vend-op").forEach((el) => { el.hidden = !!termo && !el.dataset.busca.includes(termo); });
  });
  alvo.querySelectorAll(".vend-op input").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(r.vendedores);
    c.checked ? ids.add(Number(c.dataset.id)) : ids.delete(Number(c.dataset.id));
    definir(ids);
  }));
  alvo.querySelector("#cp-todos").addEventListener("click", () => {
    const ids = new Set(r.vendedores);
    alvo.querySelectorAll(".vend-op:not([hidden]) input").forEach((c) => ids.add(Number(c.dataset.id)));
    definir(ids);
  });
  alvo.querySelector("#cp-nenhum").addEventListener("click", () => definir(new Set()));
  const n = r.vendedores.length;
  alvo.querySelector("#cp-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
}

function atualizarResumoU(u) {
  const el = raiz.querySelector("#cp-resumo-u");
  if (!el) return;
  const r = rasc.usuarios[u.login];
  const quem = `<b>${esc(u.nome)}</b>`;
  let txt;
  if (!r.ve) txt = `${quem} não vê a página Projeções.`;
  else {
    const vendo = vendedoresDoUsuario(u, r);
    if (!vendo.length) txt = `${quem} vê a página, mas <b>nenhum vendedor</b>: a página vai pedir para falar com o administrador.`;
    else if (vendo.length <= 4) txt = `${quem} vê as projeções de ${emLista(vendo.map((v) => `<b>${esc(v.nome)}</b>`))}; os totais somam só ${vendo.length === 1 ? "esse vendedor" : "esses vendedores"}.`;
    else txt = `${quem} vê as projeções de <b>${vendo.length} vendedores</b>${r.modo === "todos" ? " (todos os da página)" : ""}; os totais somam só esses vendedores.`;
  }
  el.innerHTML = `${icone("olho")}<span>${txt}</span>`;
}

// ---------- gravação ----------
async function salvar() {
  const btn = raiz.querySelector("#cp-salvar");
  for (const u of dados.usuarios) {
    const r = rasc.usuarios[u.login];
    if (!usuarioMudou(u.login)) continue;
    if (r.ve && r.modo === "alguns" && !r.vendedores.length) return erroUsuario(u, "marque ao menos um vendedor, ou escolha outra opção");
    if (!r.ve && !(u.paginas || []).some((p) => p !== "projecoes")) return erroUsuario(u, "é a única página desta pessoa; libere outra em Usuários antes de tirar esta");
  }
  const pag = naPagina();
  const vendedores = {
    incluir: dados.vendedores.filter((v) => pag.has(v.id) && !v.padrao).map((v) => v.id),
    excluir: dados.vendedores.filter((v) => !pag.has(v.id) && v.padrao).map((v) => v.id),
  };
  const usuarios = Object.fromEntries(dados.usuarios.filter((u) => usuarioMudou(u.login)).map((u) => {
    const r = rasc.usuarios[u.login];
    return [u.login, { ve: r.ve, modo: r.modo, vendedores: r.modo === "alguns" ? r.vendedores : null }];
  }));
  btn.disabled = true;
  try {
    carregarDados(await api("/api/projecoes/config", { json: { vendedores, usuarios } }));
    toast("Configuração das projeções salva");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

function erroUsuario(u, msg) {
  secao = "usuarios";
  usuarioSel = u.login;
  render();
  const el = raiz.querySelector("#cp-erro");
  el.textContent = `${u.nome}: ${msg}.`;
  el.hidden = false;
  toast(`${u.nome}: ${msg}`, "erro");
}
