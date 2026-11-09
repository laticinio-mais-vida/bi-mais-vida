// Configuração da página Projeções (só administradores): quais vendedores entram na página. Vendedor é o vendedor
// do cliente: cada um entra com a carteira inteira. Vendedores novos das equipes ES, BA e Edir entram sozinhos; a
// lista guarda só quem foi desmarcado dessas equipes ou incluído de fora delas. Cada visualizador vê, dos vendedores
// da página, só os do acesso dele (tela Usuários). Tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/projecoes/config
let orig = null, rasc = null;
const filtro = { busca: "", situacao: "todos", equipe: "" };

const clone = (o) => JSON.parse(JSON.stringify(o));

export function configProjecoesTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigProjecoes(container, contexto) {
  ctx = contexto;
  raiz = container;
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
  orig = { pagina: dados.vendedores.filter((v) => v.na_pagina).map((v) => v.id).sort((a, b) => a - b) };
  rasc = clone(orig);
}

// ---------- apoio ----------
const naPagina = () => new Set(rasc.pagina);

function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

function contarAlteracoes() { return contarAlteracoesPagina(); }

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      <button data-secao="vendedores" class="ativa">${icone("pessoas")}Vendedores da página<span class="cont">${rasc.pagina.length}</span></button>
      <div class="dica">${icone("info")} Vale só para a página Projeções, assim que você salvar. As metas e o ERP não mudam.
        Cada pessoa vê, dos vendedores da página, só os do acesso dela, escolhidos em <a href="#/usuarios">Usuários</a>.
        Administradores veem todos.</div>
    </aside>
    <div id="cp-secao"></div>
  </div>
  <div class="barra-salvar" id="cp-barra">
    <span id="cp-n">Alterações não salvas</span>
    <button class="btn" id="cp-descartar">Descartar</button>
    <button class="btn primario" id="cp-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelector("#cp-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cp-descartar").addEventListener("click", () => { rasc = clone(orig); render(); });
  renderSecao();
}

function renderSecao() {
  secaoVendedores(raiz.querySelector("#cp-secao"));
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cp-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cp-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  raiz.querySelector(".config-menu .cont").textContent = rasc.pagina.length;
}

// ======================================================================================
// Vendedores da página
// ======================================================================================
function secaoVendedores(alvo) {
  const equipes = dados.equipes.filter((e) => dados.vendedores.some((v) => v.equipe === e.id));
  const automaticas = emLista(dados.equipes.filter((e) => e.padrao).map((e) => e.nome));
  const sem = dados.sem_vendedor || { clientes: 0, venda_12m: 0 };
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("pessoas")}Vendedores que entram nas projeções</h2>
      <p class="sub">Cada vendedor entra com as vendas de todos os clientes da carteira dele (o vendedor do cliente no
        cadastro do ERP), inclusive as de antes de o cliente ser repassado a ele. Os marcados entram nos totais, nos
        gráficos e no filtro da página. Vendedores novos das equipes ${esc(automaticas)} entram sozinhos; desmarque
        contas internas ou quem não deve contar. As equipes vêm de Configurações das metas. Lista: vendedores com
        clientes que compraram desde 2024.</p>
    </div></div>
    <div class="resumo-grupos" id="cp-resumo"></div>
    ${sem.clientes ? `<p class="usu-nota aviso-nota" style="margin:0 0 14px">${icone("alerta")}<span>${sem.clientes}
      cliente${sem.clientes === 1 ? "" : "s"} sem vendedor no cadastro do ERP (${fmt.moedaC(sem.venda_12m)} em 12 meses)
      fica${sem.clientes === 1 ? "" : "m"} fora das projeções.</span></p>` : ""}
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
      <div class="prod-vendido">${v.venda_12m ? fmt.moedaC(v.venda_12m) : "—"}<small>${v.clientes} cliente${v.clientes === 1 ? "" : "s"} · ${v.ultima_venda ? `última venda ${fmt.data(v.ultima_venda)}` : "sem venda"}</small></div>
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

// ---------- gravação ----------
async function salvar() {
  const btn = raiz.querySelector("#cp-salvar");
  const pag = naPagina();
  const vendedores = {
    incluir: dados.vendedores.filter((v) => pag.has(v.id) && !v.padrao).map((v) => v.id),
    excluir: dados.vendedores.filter((v) => !pag.has(v.id) && v.padrao).map((v) => v.id),
  };
  btn.disabled = true;
  try {
    carregarDados(await api("/api/projecoes/config", { json: { vendedores } }));
    toast("Configuração das projeções salva");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}
