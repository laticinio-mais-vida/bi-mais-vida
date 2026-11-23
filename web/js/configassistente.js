// Configuração da página Assistente (só administradores), em duas partes. "Uso e custo": quanto o assistente foi usado
// (hoje, no mês e por pessoa nos últimos 30 dias) e as últimas perguntas. "Limites": o gasto total de todo mundo por
// dia e por mês e, de cada pessoa, perguntas por dia e gasto por dia e por mês, com um padrão para todos e, se
// quiser, um limite próprio para alguém. Vazio é sem limite; 0 barra. Os limites ficam em bi/uso.py
// (LimitesAssistente: tabela regras, nome "assistente", com versões) e valem na próxima pergunta, depois de Salvar.
// Os vendedores que cada pessoa consulta são os do acesso dela, escolhidos em Usuários.
import { api, esc, fmt, icone, toast } from "./util.js";

const SECOES = [["uso", "grafico", "Uso e custo"], ["limites", "cadeado", "Limites"]];
// os limites de cada pessoa: chave, título, explicação, tipo
const CAMPOS = [
  ["perguntas_dia", "Perguntas por dia", "Quantas perguntas a pessoa pode fazer por dia.", "perguntas"],
  ["custo_dia", "Gasto por dia", "Quanto as perguntas da pessoa podem custar num dia.", "dolar"],
  ["custo_mes", "Gasto por mês", "Quanto as perguntas da pessoa podem custar no mês.", "dolar"],
];
const TOTAIS = [
  ["total_dia", "Gasto total por dia", "Todas as pessoas somadas, administradores também. Ao chegar nele, ninguém pergunta até amanhã."],
  ["total_mes", "Gasto total por mês", "Todas as pessoas somadas, administradores também. Ao chegar nele, ninguém pergunta até o dia 1º."],
];
const MAX_PERGUNTAS = 10000;
const MAX_DOLARES = 100000;

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/assistente/config
let orig = null, rasc = null;
let secao = "uso";
let invalidos = {};        // "total_dia" | "padrao.custo_dia" | "u.12.custo_mes" -> o texto digitado que não vale

const clone = (o) => JSON.parse(JSON.stringify(o));
const igual = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const NUM_DOLAR = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 4, useGrouping: false });
const dolar = (v) => "US$ " + new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;

// O que a pessoa digitou: { ok, valor } (vazio = sem limite, null).
function ler(texto, tipo) {
  let t = String(texto ?? "").trim().replace(/^US\$\s*/i, "").replace(/\s+/g, "");
  if (!t) return { ok: true, valor: null };
  if (tipo === "perguntas") {
    if (!/^\d+$/.test(t) || Number(t) > MAX_PERGUNTAS) return { ok: false };
    return { ok: true, valor: Number(t) };
  }
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");  // 1.234,56 -> 1234.56
  if (!/^\d+(\.\d+)?$/.test(t)) return { ok: false };
  const v = Number(t);
  if (!Number.isFinite(v) || v > MAX_DOLARES) return { ok: false };
  return { ok: true, valor: Math.round(v * 10000) / 10000 };
}

const mostrar = (v, tipo) => (v == null ? "" : tipo === "perguntas" ? String(v) : NUM_DOLAR.format(v));
const textoLimite = (v, tipo) => (v == null ? "sem limite" : tipo === "perguntas" ? fmt.num(v) : dolar(v));

export function configAssistenteTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigAssistente(container, contexto = {}) {
  ctx = contexto;
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (SECOES.some(([id]) => id === q.get("secao"))) secao = q.get("secao");
  if (rasc && contarAlteracoes() > 0) { render(); return; }  // volta com o que estava sendo mudado
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
  orig = clone(r.limites.config);
  rasc = clone(orig);
  invalidos = {};
}

// ---------- o que mudou ----------
// Cada total, cada campo do padrão e cada pessoa contam um.
function contarAlteracoes() {
  let n = 0;
  for (const [k] of TOTAIS) n += !igual(rasc[k], orig[k]) || k in invalidos;
  for (const [k] of CAMPOS) n += !igual(rasc.padrao[k], orig.padrao[k]) || `padrao.${k}` in invalidos;
  const ids = new Set([...Object.keys(orig.usuarios), ...Object.keys(rasc.usuarios)]);
  for (const id of ids) n += !igual(rasc.usuarios[id], orig.usuarios[id]) || CAMPOS.some(([k]) => `u.${id}.${k}` in invalidos);
  return n;
}

// Os limites que valem para a pessoa no rascunho: os próprios, senão o padrão (administrador em Padrão: sem limite).
function vale(p) {
  const proprio = rasc.usuarios[p.id];
  if (proprio) return proprio;
  return p.papel === "admin" ? { perguntas_dia: null, custo_dia: null, custo_mes: null } : rasc.padrao;
}

// O valor de antes de um campo (o salvo), para marcar o que mudou. A pessoa que passou para Próprio agora: o que
// valia para ela (o padrão; o administrador, sem limite).
function antes(chave) {
  const partes = chave.split(".");
  if (partes.length === 1) return orig[chave];
  if (partes[0] === "padrao") return orig.padrao[partes[1]];
  const [, id, k] = partes;
  if (orig.usuarios[id]) return orig.usuarios[id][k];
  const p = dados.pessoas.find((x) => String(x.id) === id);
  return p && p.papel === "admin" ? null : orig.padrao[k];
}

const pessoaMudou = (id) => !igual(rasc.usuarios[id], orig.usuarios[id]) || CAMPOS.some(([k]) => `u.${id}.${k}` in invalidos);

// ---------- estrutura ----------
function render() {
  const u = dados.limites.ultima;
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${SECOES.map(([id, ic, nome]) => `<button type="button" data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont" data-cont="${id}" hidden></span></button>`).join("")}
      <div class="dica">${icone("info")} ${secao === "limites"
        ? `Os limites valem na próxima pergunta de cada pessoa, depois de salvar. Campo vazio é sem limite; 0 não deixa
          perguntar. ${u ? `Última alteração em ${esc(fmt.dataHora(u.em))}${u.por ? ` por ${esc(u.por)}` : ""}.` : "Ainda valem os limites do config.ini."}`
        : `A IA só recebe as vendas, devoluções e metas dos vendedores do acesso de cada pessoa, escolhidos em
          <a href="#/usuarios">Usuários</a>. Administradores consultam todos.`}</div>
    </aside>
    <div id="ca-secao"></div>
  </div>
  <div class="barra-salvar" id="ca-barra">
    <span id="ca-n">Alterações não salvas</span>
    <button class="btn" type="button" id="ca-descartar">Descartar</button>
    <button class="btn primario" type="button" id="ca-salvar">${icone("disco")}Salvar limites</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.secao)));
  raiz.querySelector("#ca-salvar").addEventListener("click", salvar);
  raiz.querySelector("#ca-descartar").addEventListener("click", () => {
    rasc = clone(orig);
    invalidos = {};
    render();
  });
  renderSecao();
}

function irPara(id) {
  secao = id;
  render();
  raiz.querySelector("#ca-secao").scrollIntoView({ block: "nearest" });
}

function renderSecao() {
  const alvo = raiz.querySelector("#ca-secao");
  if (secao === "limites") secaoLimites(alvo);
  else secaoUso(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#ca-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#ca-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  const cont = raiz.querySelector('[data-cont="limites"]');
  cont.hidden = !n;
  cont.textContent = n || "";
  const usoCont = raiz.querySelector('[data-cont="uso"]');
  usoCont.hidden = false;
  usoCont.textContent = dados.uso.hoje.perguntas;
}

// ======================================================================================
// Uso e custo
// ======================================================================================
function secaoUso(alvo) {
  const u = dados.uso, lim = orig;
  const pct = (gasto, limite) => (limite ? `${fmt.pct(Math.min(1, gasto / limite), 0)} do limite total de ${dolar(limite)}` : "sem limite total");
  const padrao = lim.padrao.perguntas_dia;
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("grafico")}Uso do assistente</h2>
      <p class="sub">Últimos ${u.dias} dias, pelo registro do servidor. O custo é a estimativa pelos tokens e pelos preços
        do config.ini; o valor cobrado está no Console da Anthropic.</p>
    </div></div>
    <div class="resumo-grupos">
      <div class="resumo-grupo" style="--c:var(--s-fat)"><div class="t">${icone("conversa")}Perguntas hoje</div>
        <div class="n">${u.hoje.perguntas}</div><div class="s">${padrao == null ? "sem limite de perguntas no padrão" : `padrão de ${plural(padrao, "pergunta", "perguntas")} por pessoa`}</div></div>
      <div class="resumo-grupo" style="--c:var(--laranja)"><div class="t">${icone("moeda")}Gasto de hoje</div>
        <div class="n">${dolar(u.hoje.custo)}</div><div class="s">${pct(u.hoje.custo, lim.total_dia)}</div></div>
      <div class="resumo-grupo" style="--c:var(--ok)"><div class="t">${icone("calendario")}Gasto do mês</div>
        <div class="n">${dolar(u.mes.custo)}</div><div class="s">${plural(u.mes.perguntas, "pergunta", "perguntas")} · ${pct(u.mes.custo, lim.total_mes)}</div></div>
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
// Limites
// ======================================================================================
// Um campo de limite: o valor do rascunho (ou o texto inválido que a pessoa digitou), marcado se mudou ou não vale.
function campo(chave, tipo, valor, rotulo) {
  const texto = chave in invalidos ? invalidos[chave] : mostrar(valor, tipo);
  const classe = chave in invalidos ? " erro" : !igual(valor, antes(chave)) ? " mudou" : "";
  return `<input class="ca-lim${classe}" type="text" inputmode="${tipo === "perguntas" ? "numeric" : "decimal"}" data-campo="${esc(chave)}"
    data-tipo="${tipo}" value="${esc(texto)}" placeholder="sem limite" aria-label="${esc(rotulo)}">`;
}

function secaoLimites(alvo) {
  const u = dados.uso;
  const gastoTotal = { total_dia: `Hoje: ${dolar(u.hoje.custo)}.`, total_mes: `Neste mês: ${dolar(u.mes.custo)}.` };
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("moeda")}Gasto total</h2>
      <p class="sub">O teto de todo mundo somado, para o gasto nunca passar do que a empresa quer. Em US$, pela estimativa
        de cada pergunta.</p></div></div>
    <div class="sug-regras">
      ${TOTAIS.map(([k, titulo, dica]) => `<label class="sug-campo"><span class="r"><b>${titulo}</b><small>${dica} ${gastoTotal[k]}</small></span>
        <span class="campo sem-seta">${campo(k, "dolar", rasc[k], titulo)}</span><em>US$</em></label>`).join("")}
    </div>
  </section>
  <section class="cartao entra" style="--i:2">
    <div class="cartao-cab"><div><h2>${icone("pessoas")}Padrão por pessoa</h2>
      <p class="sub">Vale para quem está em <b>Padrão</b> na tabela abaixo. Administradores em Padrão ficam sem limite por
        pessoa (só o gasto total).</p></div></div>
    <div class="sug-regras">
      ${CAMPOS.map(([k, titulo, dica, tipo]) => `<label class="sug-campo"><span class="r"><b>${titulo}</b><small>${dica}</small></span>
        <span class="campo sem-seta">${campo(`padrao.${k}`, tipo, rasc.padrao[k], `${titulo}, padrão`)}</span>
        <em>${tipo === "perguntas" ? "perguntas" : "US$"}</em></label>`).join("")}
    </div>
  </section>
  <section class="cartao entra" style="--i:3">
    <div class="cartao-cab"><div><h2>${icone("usuario")}Por pessoa</h2>
      <p class="sub">Quem tem o Assistente no acesso. Em <b>Próprio</b>, a pessoa fica com os limites da linha, no lugar do
        padrão. O uso de hoje e do mês ajuda a escolher.</p></div></div>
    ${dados.pessoas.length ? `<div class="tabela-rolagem"><table class="dados ca-pessoas">
      <thead><tr><th>Pessoa</th><th>Uso hoje</th><th>Uso no mês</th><th>Limite</th>
        ${CAMPOS.map(([, titulo, , tipo]) => `<th class="ca-num">${titulo}${tipo === "dolar" ? " <small>(US$)</small>" : ""}</th>`).join("")}</tr></thead>
      <tbody>${dados.pessoas.map(linhaPessoa).join("")}</tbody>
    </table></div>` : `<div class="vazio">${icone("usuario")}<p>Ninguém tem o Assistente no acesso. Libere a página em <a href="#/usuarios">Usuários</a>.</p></div>`}
    <p class="form-erro" id="ca-erro" hidden></p>
  </section>`;
  alvo.querySelectorAll("input[data-campo]").forEach((inp) => inp.addEventListener("input", () => digitar(inp)));
  alvo.querySelectorAll("[data-modo]").forEach((b) => b.addEventListener("click", () => trocarModo(Number(b.dataset.id), b.dataset.modo)));
}

function linhaPessoa(p) {
  const proprio = !!rasc.usuarios[p.id];
  const lim = vale(p);
  // chegou ao limite com o que vale agora no rascunho (o que a próxima pergunta vai encontrar)
  const no = (k, usado) => lim[k] != null && usado >= lim[k];
  const hoje = `${plural(p.uso.perguntas_dia, "pergunta", "perguntas")}<small>${dolar(p.uso.custo_dia)}</small>`;
  const mes = `${plural(p.uso.perguntas_mes, "pergunta", "perguntas")}<small>${dolar(p.uso.custo_mes)}</small>`;
  const aviso = no("perguntas_dia", p.uso.perguntas_dia) || no("custo_dia", p.uso.custo_dia) ? "hoje"
    : no("custo_mes", p.uso.custo_mes) ? "neste mês" : "";
  return `<tr class="${pessoaMudou(p.id) ? "mudou" : ""}">
    <td><b>${esc(p.nome)}</b>${p.papel === "admin" ? ` <span class="chip-papel admin">Administrador</span>` : ""}
      <small>${esc(p.login)}${aviso ? ` · <span class="ca-no-limite">chegou ao limite ${aviso}</span>` : ""}</small></td>
    <td>${hoje}</td><td>${mes}</td>
    <td><div class="seg-mini" role="group" aria-label="Limite de ${esc(p.nome)}">
      <button type="button" data-id="${p.id}" data-modo="padrao" class="${proprio ? "" : "ativo"}" aria-pressed="${!proprio}">Padrão</button>
      <button type="button" data-id="${p.id}" data-modo="proprio" class="${proprio ? "ativo" : ""}" aria-pressed="${proprio}">Próprio</button>
    </div></td>
    ${CAMPOS.map(([k, titulo, , tipo]) => `<td>${proprio
      ? campo(`u.${p.id}.${k}`, tipo, rasc.usuarios[p.id][k], `${titulo} de ${p.nome}`)
      : `<span class="ca-padrao" title="o padrão${p.papel === "admin" ? " do administrador" : ""}">${textoLimite(lim[k], tipo)}</span>`}</td>`).join("")}
  </tr>`;
}

// Digitar num campo: o rascunho muda na hora; o texto que não vale fica marcado e não vai para o servidor.
function digitar(inp) {
  const chave = inp.dataset.campo, tipo = inp.dataset.tipo;
  const r = ler(inp.value, tipo);
  if (r.ok) {
    delete invalidos[chave];
    const partes = chave.split(".");
    if (partes.length === 1) rasc[chave] = r.valor;
    else if (partes[0] === "padrao") rasc.padrao[partes[1]] = r.valor;
    else rasc.usuarios[partes[1]][partes[2]] = r.valor;
  } else {
    invalidos[chave] = inp.value;
  }
  inp.classList.toggle("erro", !r.ok);
  inp.classList.toggle("mudou", r.ok && !igual(r.valor, antes(chave)));
  // o padrão aparece nas linhas de quem está em Padrão: redesenha a tabela (o campo em que se digita fica fora dela)
  if (chave.startsWith("padrao.")) redesenharPessoas();
  else if (chave.startsWith("u.")) inp.closest("tr")?.classList.toggle("mudou", pessoaMudou(chave.split(".")[1]));
  atualizarBarra();
}

function redesenharPessoas() {
  const corpo = raiz.querySelector(".ca-pessoas tbody");
  if (!corpo) return;
  corpo.innerHTML = dados.pessoas.map(linhaPessoa).join("");
  corpo.querySelectorAll("input[data-campo]").forEach((inp) => inp.addEventListener("input", () => digitar(inp)));
  corpo.querySelectorAll("[data-modo]").forEach((b) => b.addEventListener("click", () => trocarModo(Number(b.dataset.id), b.dataset.modo)));
}

// Padrão -> Próprio: começa com o que valia para a pessoa (o padrão; o administrador, sem limite).
function trocarModo(id, modo) {
  const p = dados.pessoas.find((x) => x.id === id);
  if (!p) return;
  if (modo === "proprio" && !rasc.usuarios[id]) rasc.usuarios[id] = clone(orig.usuarios[id] || vale(p));
  if (modo === "padrao") {
    delete rasc.usuarios[id];
    CAMPOS.forEach(([k]) => delete invalidos[`u.${id}.${k}`]);
  }
  redesenharPessoas();
  atualizarBarra();
  if (modo === "proprio") raiz.querySelector(`input[data-campo="u.${id}.perguntas_dia"]`)?.focus();
}

function erro(msg) {
  const el = raiz.querySelector("#ca-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

function nomeDoCampo(chave) {
  const partes = chave.split(".");
  if (partes.length === 1) return TOTAIS.find(([k]) => k === chave)[1].toLowerCase();
  const titulo = CAMPOS.find(([k]) => k === partes[partes.length - 1])[1].toLowerCase();
  if (partes[0] === "padrao") return `${titulo} do padrão`;
  const p = dados.pessoas.find((x) => String(x.id) === partes[1]);
  return `${titulo} de ${p ? p.nome : "uma pessoa"}`;
}

async function salvar() {
  const errados = Object.keys(invalidos);
  if (errados.length) {
    if (secao !== "limites") irPara("limites");
    erro(`Corrija ${errados.length === 1 ? "o campo" : "os campos"} em vermelho (${errados.map(nomeDoCampo).join(", ")}): `
      + `perguntas em número inteiro, gasto em US$ (ex.: 1,50), ou vazio para não ter limite.`);
    return;
  }
  const btn = raiz.querySelector("#ca-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/assistente/config", { json: { config: rasc } }));
    toast("Limites do assistente salvos");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    erro(e.message);
  } finally {
    btn.disabled = false;
  }
}
