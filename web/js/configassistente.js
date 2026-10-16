// Configuração da página Assistente (só administradores): quais vendedores cada visualizador consulta no assistente
// e quanto ele foi usado. Vendedor aqui é o vendedor da venda, como na página Metas: a IA só recebe as vendas e
// devoluções desses vendedores (o servidor monta os dados de cada acesso). Tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";
import { iniciais } from "./conta.js";

const MODOS = [
  { id: "metas", nome: "Igual a Metas", icone: "alvo" },
  { id: "todos", nome: "Todos", icone: "pessoas" },
  { id: "alguns", nome: "Só alguns", icone: "usuario" },
];

let raiz = null;
let dados = null;          // resposta de /api/assistente/config
let orig = null, rasc = null;
let secao = "usuarios";
let usuarioSel = null;
let buscaUsuario = "";

const clone = (o) => JSON.parse(JSON.stringify(o));
const dolar = (v) => "US$ " + new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);

export function configAssistenteTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigAssistente(container) {
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (q.get("u")) { secao = "usuarios"; usuarioSel = q.get("u"); }
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    carregarDados(await api("/api/assistente/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  orig = {
    usuarios: Object.fromEntries(dados.usuarios.map((u) => [u.login, {
      ve: (u.paginas || []).includes("assistente"),
      modo: u.assistente?.modo || "metas",
      vendedores: [...(u.assistente?.vendedores || [])].sort((a, b) => a - b),
    }])),
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

function contarAlteracoes() { return Object.keys(rasc.usuarios).filter(usuarioMudou).length; }

// Vendedores (com venda nos últimos 12 meses) que o usuário consulta, com o rascunho atual.
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
      ${[["usuarios", "escudo", "Acesso por usuário", nVe], ["uso", "grafico", "Uso e custo", dados.uso.hoje.perguntas]]
        .map(([id, ic, nome, n]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont">${n}</span></button>`).join("")}
      <div class="dica">${icone("info")} A IA só recebe as vendas, devoluções e metas dos vendedores do acesso de cada
        pessoa. Administradores consultam todos.</div>
    </aside>
    <div id="ca-secao"></div>
  </div>
  <div class="barra-salvar" id="ca-barra">
    <span id="ca-n">Alterações não salvas</span>
    <button class="btn" id="ca-descartar">Descartar</button>
    <button class="btn primario" id="ca-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => {
    secao = b.dataset.secao;
    raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x === b));
    renderSecao();
  }));
  raiz.querySelector("#ca-salvar").addEventListener("click", salvar);
  raiz.querySelector("#ca-descartar").addEventListener("click", () => { rasc = clone(orig); render(); });
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#ca-secao");
  if (secao === "uso") secaoUso(alvo);
  else secaoUsuarios(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#ca-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#ca-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  raiz.querySelector(".config-menu .cont").textContent = dados.usuarios.filter((u) => rasc.usuarios[u.login].ve).length;
}

// ======================================================================================
// Uso e custo
// ======================================================================================
function secaoUso(alvo) {
  const u = dados.uso;
  const pct = u.limite_custo_dia ? Math.min(1, u.hoje.custo / u.limite_custo_dia) : 0;
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("grafico")}Uso do assistente</h2>
      <p class="sub">Últimos ${u.dias} dias, pelo registro do servidor (logs/assistente-AAAA-MM.jsonl). O custo é a
        estimativa pelos tokens e pelos preços do config.ini; o valor cobrado está no Console da Anthropic.</p>
    </div></div>
    <div class="resumo-grupos">
      <div class="resumo-grupo" style="--c:var(--s-fat)"><div class="t">${icone("conversa")}Perguntas hoje</div>
        <div class="n">${u.hoje.perguntas}</div><div class="s">limite de ${u.limite_diario} por pessoa (administradores sem limite)</div></div>
      <div class="resumo-grupo" style="--c:var(--laranja)"><div class="t">${icone("moeda")}Gasto de hoje</div>
        <div class="n">${dolar(u.hoje.custo)}</div><div class="s">${fmt.pct(pct, 0)} do limite diário de ${dolar(u.limite_custo_dia)}</div></div>
      <div class="resumo-grupo" style="--c:var(--k-cli)"><div class="t">${icone("pessoas")}Pessoas que usaram</div>
        <div class="n">${u.por_usuario.length}</div><div class="s">nos últimos ${u.dias} dias</div></div>
    </div>
    ${u.por_usuario.length ? `
    <h3 class="usu-titulo">Por pessoa</h3>
    <div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>Pessoa</th><th>Perguntas</th><th>Custo estimado</th><th>Última pergunta</th></tr></thead>
      <tbody>${u.por_usuario.map((p) => `<tr><td>${esc(p.nome || p.login)} <span class="fraco">${esc(p.login)}</span></td>
        <td>${p.perguntas}</td><td>${dolar(p.custo)}</td><td>${p.ultima ? fmt.dataHora(p.ultima) : "—"}</td></tr>`).join("")}</tbody>
    </table></div>` : `<div class="vazio">${icone("conversa")}<p>Ninguém usou o assistente nos últimos ${u.dias} dias.</p></div>`}
    ${u.ultimas.length ? `
    <h3 class="usu-titulo">Últimas perguntas</h3>
    <div class="tabela-rolagem"><table class="dados ca-ultimas">
      <thead><tr><th>Pergunta</th><th>Quem</th><th>Quando</th><th>Consultas</th><th>Custo</th></tr></thead>
      <tbody>${u.ultimas.map((r) => `<tr><td>${esc(r.pergunta)}${r.erro ? `<br><span class="ca-erro">${icone("alerta")}${esc(r.erro)}</span>` : ""}</td>
        <td>${esc(r.nome || r.login)}</td><td>${fmt.dataHora(r.quando)}</td><td>${r.passos}</td><td>${dolar(r.custo)}</td></tr>`).join("")}</tbody>
    </table></div>` : ""}
  </section>`;
}

// ======================================================================================
// Acesso por usuário
// ======================================================================================
function secaoUsuarios(alvo) {
  if (!dados.usuarios.length) {
    alvo.innerHTML = `<section class="cartao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div><h3>Ainda não há visualizadores</h3>
      <p>Cadastre as pessoas em <b>Usuários</b>; depois, aqui você escolhe quais vendedores cada uma consulta no assistente.</p>
      <a class="btn primario" href="#/usuarios">${icone("escudo")}Abrir Usuários</a></section>`;
    return;
  }
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios">
    <aside class="cartao usu-lista entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("escudo")}Visualizadores</h2>
        <p class="sub">Quem usa o assistente e quais vendedores cada um consulta</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="ca-busca-u" type="search" placeholder="Buscar pessoa" value="${esc(buscaUsuario)}"></label>
      <div class="usu-itens" id="ca-itens"></div>
      <div class="dica">${icone("info")}<span>Nome, senha e páginas ficam em <a href="#/usuarios">Usuários</a>; as abas e os
        vendedores de Metas, em <a href="#/configuracoes?secao=usuarios">Metas › Configurar</a>.</span></div>
    </aside>
    <div id="ca-editor"></div>
  </div>`;
  alvo.querySelector("#ca-busca-u").addEventListener("input", (e) => { buscaUsuario = e.target.value; desenharItens(); });
  desenharItens();
  desenharEditor();
}

function desenharItens() {
  const termo = buscaUsuario.trim().toLowerCase();
  const el = raiz.querySelector("#ca-itens");
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
  const alvo = raiz.querySelector("#ca-editor");
  const u = dados.usuarios.find((x) => x.login === usuarioSel);
  if (!u) { alvo.innerHTML = ""; return; }
  const r = rasc.usuarios[u.login];
  const idx = MODOS.findIndex((m) => m.id === r.modo);
  const outras = (u.paginas || []).filter((p) => p !== "assistente");
  alvo.innerHTML = `
  <section class="cartao usu-editor entra" style="--i:2">
    <div class="cartao-cab"><div>
      <h2>${icone("conversa")}Assistente de ${esc(u.nome)}</h2>
      <p class="sub">${esc(u.login)}${u.ativo ? "" : " · acesso desativado em Usuários"}</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${r.ve ? "ligada" : ""}" id="ca-ve" type="button" role="switch" aria-checked="${r.ve}" aria-label="Usa o assistente"></button>
      <div><b>Usa o assistente</b><p>${r.ve ? "A página aparece na barra lateral desta pessoa." : "Desligado, a página some da barra lateral e o servidor recusa as perguntas."}
        ${!outras.length && r.ve ? " É a única página dela: para tirar, libere outra antes em Usuários." : ""}</p></div>
    </div>
    <div ${r.ve ? "" : "hidden"}>
      <h3 class="usu-titulo">Vendedores que consulta</h3>
      <div class="seletor cp-modo" data-v="${idx}" role="radiogroup" aria-label="Vendedores que consulta"><span class="marcador"></span>
        ${MODOS.map((m) => `<button type="button" role="radio" data-modo="${m.id}" aria-checked="${m.id === r.modo}" class="${m.id === r.modo ? "ativo" : ""}">${icone(m.icone)}${m.nome}</button>`).join("")}
      </div>
      <div id="ca-modo-detalhe"></div>
    </div>
    <div class="usu-resumo" id="ca-resumo-u"></div>
    <p class="form-erro" id="ca-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#ca-ve").addEventListener("click", () => {
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
  const alvo = raiz.querySelector("#ca-modo-detalhe");
  if (r.modo === "metas") {
    const abas = dados.visoes.filter((v) => (u.visoes || []).includes(v.id));
    const link = `<a href="#/configuracoes?u=${encodeURIComponent(u.login)}">Metas › Configurar</a>`;
    if (!abas.length) {
      alvo.innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Esta pessoa não tem abas de Metas (${link}), então não consultaria nenhum vendedor. Escolha "Todos" ou "Só alguns".</span></p>`;
    } else {
      const equipes = [...new Set(abas.flatMap((v) => v.grupos))].map((g) => (g === "EDIR" ? "Edir" : g));
      const vend = u.vendedores ? `só os ${u.vendedores.length} vendedores marcados lá` : "todos os vendedores dessas equipes";
      alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Segue o acesso de Metas (${link}): equipes ${esc(emLista(equipes))}
        e ${vend}. Se o acesso de Metas mudar, este muda junto.</span></p>`;
    }
  } else if (r.modo === "todos") {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Consulta as vendas de todos os vendedores, inclusive os que entrarem depois.</span></p>`;
  } else {
    desenharEscolha(u);
  }
  atualizarResumoU(u);
}

function desenharEscolha(u) {
  const r = rasc.usuarios[u.login];
  const alvo = raiz.querySelector("#ca-modo-detalhe");
  const marcados = new Set(r.vendedores);
  const conhecidos = new Set(dados.vendedores.map((v) => v.id));
  // marcados que não venderam nos últimos 12 meses continuam na lista, para poder desmarcar
  const lista = [...dados.vendedores, ...r.vendedores.filter((id) => !conhecidos.has(id))
    .map((id) => ({ id, nome: `Vendedor ${id}`, nome_erp: "", rotulo_equipe: "sem venda em 12 meses" }))];
  alvo.innerHTML = `
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="ca-busca-v" type="search" placeholder="Buscar vendedor ou código"></label>
      <span class="usu-cont" id="ca-cont"></span>
      <button class="btn" type="button" id="ca-todos">Marcar os da lista</button>
      <button class="btn" type="button" id="ca-nenhum">Desmarcar todos</button>
    </div>
    <div class="vend-escolha">${lista.map((v) => `
      <label class="vend-op" data-busca="${esc(`${v.nome} ${v.nome_erp} ${v.id}`.toLowerCase())}">
        <input type="checkbox" data-id="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(v.rotulo_equipe)}${v.venda_12m ? ` · ${fmt.moedaC(v.venda_12m)} em 12 meses` : ""}</small></span>
      </label>`).join("")}</div>`;
  const contar = () => {
    const n = r.vendedores.length;
    alvo.querySelector("#ca-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
  };
  const definir = (ids) => {
    r.vendedores = [...ids].sort((a, b) => a - b);
    alvo.querySelectorAll(".vend-op input").forEach((c) => { c.checked = ids.has(Number(c.dataset.id)); });
    contar();
    atualizarResumoU(u);
    desenharItens();
    atualizarBarra();
  };
  alvo.querySelector("#ca-busca-v").addEventListener("input", (e) => {
    const termo = e.target.value.trim().toLowerCase();
    alvo.querySelectorAll(".vend-op").forEach((el) => { el.hidden = !!termo && !el.dataset.busca.includes(termo); });
  });
  alvo.querySelectorAll(".vend-op input").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(r.vendedores);
    c.checked ? ids.add(Number(c.dataset.id)) : ids.delete(Number(c.dataset.id));
    definir(ids);
  }));
  alvo.querySelector("#ca-todos").addEventListener("click", () => {
    const ids = new Set(r.vendedores);
    alvo.querySelectorAll(".vend-op:not([hidden]) input").forEach((c) => ids.add(Number(c.dataset.id)));
    definir(ids);
  });
  alvo.querySelector("#ca-nenhum").addEventListener("click", () => definir(new Set()));
  contar();
}

function atualizarResumoU(u) {
  const el = raiz.querySelector("#ca-resumo-u");
  if (!el) return;
  const r = rasc.usuarios[u.login];
  const quem = `<b>${esc(u.nome)}</b>`;
  let txt;
  if (!r.ve) txt = `${quem} não usa o assistente.`;
  else if (r.modo === "todos") txt = `${quem} pergunta sobre as vendas de <b>todos os vendedores</b>.`;
  else {
    const vendo = vendedoresDoUsuario(u, r);
    if (!vendo.length) txt = `${quem} vê a página, mas <b>nenhum vendedor</b>: o assistente vai pedir para falar com o administrador.`;
    else if (vendo.length <= 4) txt = `${quem} pergunta só sobre as vendas de ${emLista(vendo.map((v) => `<b>${esc(v.nome)}</b>`))}.`;
    else txt = `${quem} pergunta sobre as vendas de <b>${vendo.length} vendedores</b>; os demais ficam de fora das respostas.`;
  }
  el.innerHTML = `${icone("olho")}<span>${txt}</span>`;
}

// ---------- gravação ----------
async function salvar() {
  const btn = raiz.querySelector("#ca-salvar");
  for (const u of dados.usuarios) {
    const r = rasc.usuarios[u.login];
    if (!usuarioMudou(u.login)) continue;
    if (r.ve && r.modo === "alguns" && !r.vendedores.length) return erroUsuario(u, "marque ao menos um vendedor, ou escolha outra opção");
    if (!r.ve && !(u.paginas || []).some((p) => p !== "assistente")) return erroUsuario(u, "é a única página desta pessoa; libere outra em Usuários antes de tirar esta");
  }
  const usuarios = Object.fromEntries(dados.usuarios.filter((u) => usuarioMudou(u.login)).map((u) => {
    const r = rasc.usuarios[u.login];
    return [u.login, { ve: r.ve, modo: r.modo, vendedores: r.modo === "alguns" ? r.vendedores : null }];
  }));
  btn.disabled = true;
  try {
    carregarDados(await api("/api/assistente/config", { json: { usuarios } }));
    toast("Acessos do assistente salvos");
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
  const el = raiz.querySelector("#ca-erro");
  el.textContent = `${u.nome}: ${msg}.`;
  el.hidden = false;
  toast(`${u.nome}: ${msg}`, "erro");
}
