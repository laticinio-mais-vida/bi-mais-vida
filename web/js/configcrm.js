// Configuração da página CRM (só administradores), em três partes. "Pontos e regras": as equipes, quando o cliente
// entra no CRM, as faixas da aderência e da pontualidade, os pontos do mix e os de cada quintil da rentabilidade (os
// quatro máximos somam 100). "Mix ideal": os itens de cada segmento; um item é um ou mais produtos que valem um pelo
// outro (a mesma cor na planilha MIX IDEAL) ou qualquer mussarela. "Custos": o custo industrial de cada produto por mês,
// digitado (dá para colar do Excel) ou importado de uma planilha, e os produtos que usam o custo de outro. As regras
// ficam em bi/crm.py (ConfigCrm: tabela regras, nome "crm", com versões) e tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";

const SECOES = [["regras", "ajustes", "Pontos e regras"], ["mix", "queijo", "Mix ideal"], ["custos", "moeda", "Custos"]];
const NOME_EQUIPE = { ES: "ES", BA: "BA", EDIR: "Edir" };
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const QUINTIS = ["os 20% de maior lucro", "de 20% a 40%", "de 40% a 60%", "de 60% a 80%", "os 20% de menor lucro (e quem não deu lucro)"];
const MAX_PLANILHA = 5 * 1024 * 1024;
const MAX_CUSTO = 100000;
const TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const NUM_CUSTO = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 6, useGrouping: false });

let ctx = null, raiz = null;
let dados = null;            // resposta de /api/crm/config
let orig = null, rasc = null;
let produtos = new Map();    // id -> { id, nome, linha, unidade, inativo, vendido, mussarela }
let secao = "regras";
let segSel = null;           // o segmento aberto no Mix ideal (a chave: sem acento e em maiúsculas)
let buscaSeg = "", buscaCusto = "";
let invalidos = {};          // "produto|mês" -> o texto digitado que não é um custo válido
let importada = null;        // a planilha de custos lida, esperando "Levar para a tabela"
let mexeu = false;           // a pessoa mudou alguma coisa nesta visita
let animar = true;           // as seções entram com animação só quando aparecem, não a cada mudança

const clone = (o) => JSON.parse(JSON.stringify(o));
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;
// Como o servidor compara o segmento (bi/crm.py, normalizar): maiúsculas, sem acento e sem espaço repetido.
const normalizar = (t) => String(t ?? "").normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toUpperCase().split(/\s+/).filter(Boolean).join(" ");
const MES = /^(\d{4})-(\d{2})$/;
const mesValido = (m) => { const x = MES.exec(String(m ?? "")); return !!x && Number(x[2]) >= 1 && Number(x[2]) <= 12; };
const mesRotulo = (m) => (mesValido(m) ? `${MESES[Number(m.slice(5)) - 1]}/${m.slice(2, 4)}` : "—");
const proximoMes = (m) => { const [a, n] = m.split("-").map(Number); return n === 12 ? `${a + 1}-01` : `${a}-${String(n + 1).padStart(2, "0")}`; };
const nomeProduto = (id) => produtos.get(Number(id))?.nome || `Produto ${id}`;
const pegar = (o, caminho) => caminho.split(".").reduce((x, k) => (x == null ? x : x[k]), o);
function por(o, caminho, valor) {
  const ks = caminho.split("."), ultimo = ks.pop();
  ks.reduce((x, k) => x[k], o)[ultimo] = valor;
}
// O que vai para o servidor: o número quando o campo tem um; senão o texto, e o servidor explica o erro.
const num = (v) => {
  const t = String(v ?? "").trim().replace(",", ".");
  const n = Number(t);
  return t !== "" && Number.isFinite(n) ? n : v;
};

export function configCrmTemAlteracoes() { return !!(rasc && alteracoes().total > 0); }

export async function montarConfigCrm(container, contexto) {
  ctx = contexto;
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (SECOES.some(([id]) => id === q.get("secao"))) secao = q.get("secao");
  if (q.get("seg")) { secao = "mix"; segSel = normalizar(q.get("seg")); }  // o link do cliente de segmento sem mix
  animar = true;
  if (rasc && mexeu && alteracoes().total > 0) { render(); return; }  // volta com o que estava sendo mudado
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:260px"></div><div class="esqueleto" style="height:520px"></div></div>`;
  try {
    carregarDados(await api("/api/crm/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  produtos = new Map((r.produtos || []).map((p) => [Number(p.id), { ...p, id: Number(p.id) }]));
  orig = clone(r.config);
  rasc = clone(orig);
  invalidos = {};
  importada = null;
  mexeu = false;
}

// ---------- o que mudou ----------
function paraSalvar(c) {
  const faixas = (lista) => lista.map((f) => ({ de: num(f.de), pontos: num(f.pontos) }));
  const r = c.rentabilidade;
  return {
    versao: c.versao ?? 1,
    equipes: (dados.equipes || Object.keys(NOME_EQUIPE)).filter((e) => c.equipes.includes(e)),
    meses_para_entrar: num(c.meses_para_entrar),
    aderencia: {
      semanas: num(c.aderencia.semanas), prazo_quinzenal: num(c.aderencia.prazo_quinzenal),
      prazo_mensal: num(c.aderencia.prazo_mensal), faixas: faixas(c.aderencia.faixas),
    },
    pontualidade: {
      desde: c.pontualidade.desde, tolerancia: num(c.pontualidade.tolerancia), sem_titulo: num(c.pontualidade.sem_titulo),
      faixas: faixas(c.pontualidade.faixas), descontos: faixas(c.pontualidade.descontos),
    },
    mix: { pontos: num(c.mix.pontos), segmentos: Object.fromEntries(Object.entries(c.mix.segmentos).filter(([, itens]) => itens.length)) },
    rentabilidade: {
      desde: r.desde, pontos: r.pontos.map(num),
      custos: Object.fromEntries(Object.entries(r.custos).filter(([, meses]) => Object.keys(meses).length)
        .map(([p, meses]) => [p, Object.fromEntries(Object.entries(meses).sort(([a], [b]) => a.localeCompare(b)))])),
      usa_custo_de: { ...r.usa_custo_de },
    },
  };
}

// Quantas coisas mudaram em cada parte: cada campo das regras, cada segmento do mix, cada produto dos custos.
function alteracoes() {
  const a = paraSalvar(orig), b = paraSalvar(rasc);
  const n = { regras: 0, mix: 0, custos: Object.keys(invalidos).length };
  for (const k of ["equipes", "meses_para_entrar"]) if (!igual(a[k], b[k])) n.regras++;
  for (const k of ["semanas", "prazo_quinzenal", "prazo_mensal", "faixas"]) if (!igual(a.aderencia[k], b.aderencia[k])) n.regras++;
  for (const k of ["desde", "tolerancia", "sem_titulo", "faixas", "descontos"]) if (!igual(a.pontualidade[k], b.pontualidade[k])) n.regras++;
  if (!igual(a.mix.pontos, b.mix.pontos)) n.regras++;
  for (const k of ["desde", "pontos"]) if (!igual(a.rentabilidade[k], b.rentabilidade[k])) n.regras++;
  for (const s of new Set([...Object.keys(a.mix.segmentos), ...Object.keys(b.mix.segmentos)])) {
    if (!igual(a.mix.segmentos[s] || [], b.mix.segmentos[s] || [])) n.mix++;
  }
  const ca = a.rentabilidade.custos, cb = b.rentabilidade.custos;
  for (const p of new Set([...Object.keys(ca), ...Object.keys(cb)])) if (!igual(ca[p] || {}, cb[p] || {})) n.custos++;
  const ua = a.rentabilidade.usa_custo_de, ub = b.rentabilidade.usa_custo_de;
  for (const p of new Set([...Object.keys(ua), ...Object.keys(ub)])) if (ua[p] !== ub[p]) n.custos++;
  n.total = n.regras + n.mix + n.custos;
  return n;
}

// Os pontos máximos de cada indicador (a faixa de cima): os quatro somam 100.
function maximos(c) {
  const topo = (lista) => Math.max(0, ...lista.map((x) => Number(num(x)) || 0));
  return {
    aderencia: topo(c.aderencia.faixas.map((f) => f.pontos)), pontualidade: topo(c.pontualidade.faixas.map((f) => f.pontos)),
    mix: Number(num(c.mix.pontos)) || 0, rentabilidade: topo(c.rentabilidade.pontos),
  };
}

// ---------- estrutura ----------
function render() {
  const u = dados.ultima;
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${SECOES.map(([id, ic, nome]) => `<button type="button" data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}<span class="cont" data-cont="${id}" hidden></span></button>`).join("")}
      <div class="dica">${icone("info")} Tudo vale assim que você salvar: as notas dos clientes são refeitas com as regras novas.
        ${u ? `Última alteração em ${esc(fmt.dataHora(u.em))}${u.por ? ` por ${esc(u.por)}` : ""}.` : "Ainda no padrão: o mix e os custos das planilhas, com os ajustes combinados."}</div>
    </aside>
    <div id="cc-secao"></div>
  </div>
  <div class="barra-salvar" id="cc-barra">
    <span id="cc-n">Alterações não salvas</span>
    <button class="btn" type="button" id="cc-descartar">Descartar</button>
    <button class="btn primario" type="button" id="cc-salvar">${icone("disco")}Salvar alterações</button>
  </div>
  <datalist id="cc-produtos">${[...produtos.values()].map((p) => `<option value="${p.id} · ${esc(p.nome)}">${esc([p.linha, p.unidade, p.inativo ? "inativo" : ""].filter(Boolean).join(" · "))}</option>`).join("")}</datalist>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.secao)));
  raiz.querySelector("#cc-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cc-descartar").addEventListener("click", () => {
    rasc = clone(orig);
    invalidos = {};
    importada = null;
    mexeu = false;
    animar = true;
    render();
  });
  renderSecao();
}

function irPara(id) {
  secao = id;
  animar = true;
  raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x.dataset.secao === id));
  renderSecao();
  raiz.querySelector("#cc-secao").scrollIntoView({ block: "nearest" });
}

function renderSecao() {
  const alvo = raiz.querySelector("#cc-secao");
  if (secao === "mix") secaoMix(alvo);
  else if (secao === "custos") secaoCustos(alvo);
  else secaoRegras(alvo);
  animar = false;
  atualizarBarra();
}

function atualizarBarra() {
  const n = alteracoes();
  raiz.querySelector("#cc-barra").classList.toggle("visivel", n.total > 0);
  raiz.querySelector("#cc-n").textContent = n.total === 1 ? "1 alteração não salva" : `${n.total} alterações não salvas`;
  for (const [id] of SECOES) {
    const el = raiz.querySelector(`[data-cont="${id}"]`);
    if (el) { el.hidden = !n[id]; el.textContent = n[id] || ""; }
  }
}

function mudou() {
  mexeu = true;
  atualizarBarra();
}

function erro(msg) {
  const el = raiz.querySelector("#cc-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

const entra = (i) => (animar ? ` entra" style="--i:${i}` : "");

// Um produto digitado ou escolhido da lista: o código (o começo do texto) ou o nome exato. null = vazio;
// undefined = não achou.
function produtoDigitado(texto) {
  const t = String(texto || "").trim();
  if (!t) return null;
  const m = /^(\d+)/.exec(t);
  if (m && (produtos.has(Number(m[1])) || !produtos.size)) return Number(m[1]);
  const n = normalizar(t);
  for (const p of produtos.values()) if (normalizar(p.nome) === n) return p.id;
  return undefined;
}

// Liga um campo de produto (com a lista do ERP): age ao escolher da lista ou com Enter.
function ligarEscolha(inp, aoEscolher) {
  const tentar = () => {
    const id = produtoDigitado(inp.value);
    if (id === null) return;
    if (id === undefined) { toast("Produto não encontrado: escolha da lista ou digite o código", "erro"); return; }
    inp.value = "";
    aoEscolher(id);
  };
  inp.addEventListener("input", (e) => { if (!e.inputType || e.inputType === "insertReplacementText") tentar(); });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); tentar(); } });
}

// ======================================================================================
// Pontos e regras
// ======================================================================================
function campo(caminho, titulo, dica, unidade, { min = 0, max = 100, step = 1, tipo = "number" } = {}) {
  const v = pegar(rasc, caminho);
  const extra = tipo === "number" ? `min="${min}" max="${max}" step="${step}" inputmode="${step === 1 ? "numeric" : "decimal"}"` : "";
  return `<label class="sug-campo${tipo === "number" ? "" : " cc-largo"}"><span class="r"><b>${titulo}</b>${dica ? `<small>${dica}</small>` : ""}</span>
    <span class="campo sem-seta"><input type="${tipo}" ${extra} data-caminho="${caminho}" value="${esc(String(v ?? ""))}" aria-label="${esc(titulo)}"></span><em>${unidade}</em></label>`;
}

function faixas(caminho, [deAntes, deDepois], [ptsAntes, ptsDepois], abaixo) {
  const lista = pegar(rasc, caminho);
  return `<div class="cc-faixas">
    ${lista.map((f, i) => `<div class="cc-faixa">
      <span>${deAntes}</span>
      <span class="campo sem-seta"><input type="number" step="any" min="0" data-faixa="${caminho}" data-i="${i}" data-k="de" value="${esc(String(f.de ?? ""))}" aria-label="${esc(`${deAntes} (${deDepois})`)}"></span><em>${deDepois}</em>
      <span>${ptsAntes}</span>
      <span class="campo sem-seta"><input type="number" step="any" min="0" max="100" data-faixa="${caminho}" data-i="${i}" data-k="pontos" value="${esc(String(f.pontos ?? ""))}" aria-label="${esc(`${ptsAntes} (pontos)`)}"></span><em>${ptsDepois}</em>
      <button type="button" class="btn icone cc-tirar" data-tirar-faixa="${caminho}" data-i="${i}" title="Tirar esta faixa" aria-label="Tirar esta faixa" ${lista.length <= 1 ? "disabled" : ""}>${icone("x")}</button>
    </div>`).join("")}
    <div class="cc-faixa-pe"><span>${abaixo}</span><button type="button" class="btn" data-mais-faixa="${caminho}">${icone("mais")}Faixa</button></div>
  </div>`;
}

function secaoRegras(alvo) {
  alvo.innerHTML = `
  <section class="cartao secao${entra(1)}">
    <div class="cartao-cab"><div><h2>${icone("pessoas")}Quem entra no CRM</h2>
      <p class="sub">Os clientes ativos dos vendedores das equipes marcadas (pelas regras de Metas), sem "PEDIDO BLOQUEADO" no nome. Quem nunca comprou, ou comprou pela primeira vez há pouco tempo, fica fora, sem nota</p></div></div>
    <div class="vend-escolha cc-equipes">${(dados.equipes || []).map((e) => `
      <label class="vend-op"><input type="checkbox" data-equipe="${esc(e)}" ${rasc.equipes.includes(e) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">Equipe ${esc(NOME_EQUIPE[e] || e)}<small>os vendedores da equipe, como em Metas</small></span></label>`).join("")}</div>
    <div class="sug-regras">
      ${campo("meses_para_entrar", "Meses desde a primeira compra", "O cliente entra quando a primeira compra (pedido de venda não cancelado) passou desse tempo. Com 0, entra a partir da primeira compra.", "meses", { max: 24 })}
    </div>
    <p class="usu-nota cc-total" id="cc-total"></p>
  </section>

  <section class="cartao secao${entra(2)}">
    <div class="cartao-cab"><div><h2>${icone("calendario")}Aderência à frequência</h2>
      <p class="sub">A frequência é a rede do cadastro: semanal, quinzenal ou mensal (outra rede ou nenhuma vale semanal). Conta uma compra por semana, de domingo a sábado, de qualquer vendedor</p></div></div>
    <div class="sug-regras">
      ${campo("aderencia.semanas", "Semanas do período", "As semanas fechadas até o último sábado (26 = um semestre). Quem comprou pela primeira vez depois do começo conta desde a primeira compra.", "semanas", { min: 4, max: 104 })}
      ${campo("aderencia.prazo_quinzenal", "Prazo do quinzenal", "Cada compra deixa o cliente quinzenal em dia por esses dias; cada dia além é atraso.", "dias", { min: 7, max: 60 })}
      ${campo("aderencia.prazo_mensal", "Prazo do mensal", "O mesmo, para o cliente mensal.", "dias", { min: 14, max: 120 })}
    </div>
    <h3 class="usu-titulo">Pontos <small>pela % das semanas com compra (semanal) ou dos dias em dia (quinzenal e mensal)</small></h3>
    ${faixas("aderencia.faixas", ["A partir de", "%"], ["vale", "pontos"], "Abaixo da última faixa, 0 pontos.")}
  </section>

  <section class="cartao secao${entra(3)}">
    <div class="cartao-cab"><div><h2>${icone("recibo")}Pontualidade de pagamento</h2>
      <p class="sub">Os títulos de venda que venceram no período; o título em aberto conta como atrasado, com os dias até hoje</p></div></div>
    <div class="sug-regras">
      ${campo("pontualidade.desde", "Títulos desde", "Os títulos que venceram a partir desta data contam (o histórico desde 2024).", "", { tipo: "date" })}
      ${campo("pontualidade.tolerancia", "Tolerância", "Pontual é o título pago até esses dias depois do vencimento. Os que venceram nesses últimos dias ainda não contam.", "dias", { max: 60 })}
      ${campo("pontualidade.sem_titulo", "Cliente sem título", "Os pontos de quem não tem título no período (ele fica sinalizado).", "pontos", { step: "any" })}
    </div>
    <h3 class="usu-titulo">Pontos <small>pela % dos títulos pagos em dia</small></h3>
    ${faixas("pontualidade.faixas", ["A partir de", "%"], ["vale", "pontos"], "Abaixo da última faixa, 0 pontos.")}
    <h3 class="usu-titulo">Desconto pelo atraso médio <small>a média de dias dos títulos atrasados; vale para quem atrasa em qualquer faixa, e a nota não fica negativa</small></h3>
    ${faixas("pontualidade.descontos", ["Atraso médio a partir de", "dias"], ["desconta", "pontos"], "Abaixo da última faixa, sem desconto.")}
  </section>

  <section class="cartao secao${entra(4)}">
    <div class="cartao-cab"><div><h2>${icone("queijo")}Mix ideal</h2>
      <p class="sub">O cliente ganha a parte dos pontos que corresponde aos itens do mix ideal do segmento que ele comprou no período</p></div></div>
    <div class="sug-regras">
      ${campo("mix.pontos", "Pontos do mix", "Com todos os itens do mix comprados no período, o cliente ganha esses pontos.", "pontos", { step: "any" })}
    </div>
    <p class="usu-nota">${icone("info")}<span>Os itens de cada segmento ficam em <a href="#/config-crm?secao=mix" data-ir="mix">Mix ideal</a>.</span></p>
  </section>

  <section class="cartao secao${entra(5)}">
    <div class="cartao-cab"><div><h2>${icone("grafico")}Rentabilidade</h2>
      <p class="sub">Lucro bruto = faturamento − custo industrial × volume, por produto e mês, das vendas a cliente. Os clientes do CRM são divididos em cinco partes iguais pelo lucro, recalculadas a cada mês novo de custo</p></div></div>
    <div class="sug-regras">
      ${campo("rentabilidade.desde", "Lucro bruto desde", "O lucro soma do começo deste mês até o último mês com custo em Custos.", "", { tipo: "month" })}
    </div>
    <h3 class="usu-titulo">Pontos de cada quintil</h3>
    <div class="cc-quintis">${rasc.rentabilidade.pontos.map((p, i) => `
      <label class="cc-quintil"><span>${i + 1}º quintil<small>${QUINTIS[i]}</small></span>
        <span class="campo sem-seta"><input type="number" step="any" min="0" max="100" data-quintil="${i}" value="${esc(String(p ?? ""))}" aria-label="Pontos do ${i + 1}º quintil"></span><em>pontos</em></label>`).join("")}</div>
    <p class="usu-nota">${icone("moeda")}<span>O custo de cada produto fica em <a href="#/config-crm?secao=custos" data-ir="custos">Custos</a>.</span></p>
    <p class="form-erro" id="cc-erro" role="alert" hidden></p>
    <div class="sug-regras-acoes"><button class="btn" type="button" id="cc-padrao">${icone("restaurar")}Voltar os pontos e as regras ao padrão</button></div>
  </section>`;
  alvo.querySelectorAll("[data-caminho]").forEach((inp) => inp.addEventListener("input", () => {
    por(rasc, inp.dataset.caminho, inp.value.trim());
    mudou();
    atualizarTotal();
  }));
  alvo.querySelectorAll("[data-equipe]").forEach((c) => c.addEventListener("change", () => {
    const marcadas = new Set(rasc.equipes);
    c.checked ? marcadas.add(c.dataset.equipe) : marcadas.delete(c.dataset.equipe);
    rasc.equipes = (dados.equipes || []).filter((e) => marcadas.has(e));
    mudou();
  }));
  alvo.querySelectorAll("[data-faixa]").forEach((inp) => inp.addEventListener("input", () => {
    pegar(rasc, inp.dataset.faixa)[Number(inp.dataset.i)][inp.dataset.k] = inp.value.trim();
    mudou();
    atualizarTotal();
  }));
  alvo.querySelectorAll("[data-tirar-faixa]").forEach((b) => b.addEventListener("click", () => {
    const lista = pegar(rasc, b.dataset.tirarFaixa);
    if (lista.length <= 1) return;
    lista.splice(Number(b.dataset.i), 1);
    mudou();
    secaoRegras(alvo);
  }));
  alvo.querySelectorAll("[data-mais-faixa]").forEach((b) => b.addEventListener("click", () => {
    const caminho = b.dataset.maisFaixa, lista = pegar(rasc, caminho);
    lista.push({ de: "", pontos: "" });
    mudou();
    secaoRegras(alvo);
    raiz.querySelector(`[data-faixa="${caminho}"][data-i="${lista.length - 1}"][data-k="de"]`)?.focus();
  }));
  alvo.querySelectorAll("[data-quintil]").forEach((inp) => inp.addEventListener("input", () => {
    rasc.rentabilidade.pontos[Number(inp.dataset.quintil)] = inp.value.trim();
    mudou();
    atualizarTotal();
  }));
  alvo.querySelectorAll("[data-ir]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); irPara(a.dataset.ir); }));
  alvo.querySelector("#cc-padrao").addEventListener("click", () => {
    const pad = clone(dados.padrao);
    Object.assign(rasc, { equipes: pad.equipes, meses_para_entrar: pad.meses_para_entrar, aderencia: pad.aderencia, pontualidade: pad.pontualidade });
    rasc.mix.pontos = pad.mix.pontos;
    rasc.rentabilidade.desde = pad.rentabilidade.desde;
    rasc.rentabilidade.pontos = pad.rentabilidade.pontos;
    mexeu = true;
    toast("Pontos e regras no padrão; o mix e os custos ficam como estão. Confira e salve");
    renderSecao();
  });
  atualizarTotal();
}

function atualizarTotal() {
  const el = raiz.querySelector("#cc-total");
  if (!el) return;
  const m = maximos(rasc), soma = m.aderencia + m.pontualidade + m.mix + m.rentabilidade, ok = Math.abs(soma - 100) < 1e-6;
  el.classList.toggle("aviso-nota", !ok);
  el.innerHTML = `${icone(ok ? "certo" : "alerta")}<span>A nota vai até <b>${fmt.num(soma, 2)}</b>: aderência ${fmt.num(m.aderencia, 2)}
    + pontualidade ${fmt.num(m.pontualidade, 2)} + mix ${fmt.num(m.mix, 2)} + rentabilidade ${fmt.num(m.rentabilidade, 2)}${ok ? "." : ". Os quatro máximos precisam somar 100."}</span>`;
}

// ======================================================================================
// Mix ideal: os itens de cada segmento
// ======================================================================================
// Os segmentos do mix e os do cadastro do ERP (os nomes que só mudam no acento ou na caixa são o mesmo segmento).
function segmentos() {
  const erp = new Map();
  for (const s of dados.segmentos || []) {
    const k = s.chave || normalizar(s.nome), x = erp.get(k);
    if (!x) erp.set(k, { nome: s.nome, clientes: s.clientes, maior: s.clientes });
    else {
      x.clientes += s.clientes;
      if (s.clientes > x.maior) { x.nome = s.nome; x.maior = s.clientes; }
    }
  }
  const chaves = new Set([...Object.keys(rasc.mix.segmentos), ...erp.keys()]);
  return [...chaves].map((k) => ({ chave: k, nome: erp.get(k)?.nome || k, clientes: erp.get(k)?.clientes ?? 0, noErp: erp.has(k),
    itens: (rasc.mix.segmentos[k] || []).length }))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
}

const segMudou = (k) => !igual(orig.mix.segmentos[k] || [], rasc.mix.segmentos[k] || []);

function secaoMix(alvo) {
  const lista = segmentos();
  if (!lista.some((s) => s.chave === segSel)) segSel = lista[0]?.chave ?? null;
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios cc-mix">
    <aside class="cartao usu-lista${entra(1)}">
      <div class="cartao-cab"><div><h2>${icone("loja")}Segmentos</h2>
        <p class="sub">O segmento do cliente vem do cadastro do ERP</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="cc-busca-seg" type="search" placeholder="Buscar segmento" value="${esc(buscaSeg)}"></label>
      <div class="usu-itens cc-segs" id="cc-segs"></div>
      <form class="cc-novo-seg" id="cc-novo-seg">
        <label class="campo sem-seta"><span class="ic-campo">${icone("mais")}</span><input id="cc-novo-seg-nome" placeholder="Outro segmento (o nome do ERP)" maxlength="80" autocomplete="off"></label>
        <button class="btn" type="submit">Adicionar</button>
      </form>
      <div class="dica">${icone("info")}<span>O cliente sem segmento, ou de um segmento sem mix, fica com 0 no mix e sinalizado na página.</span></div>
      <div class="sug-regras-acoes"><button class="btn" type="button" id="cc-padrao-mix">${icone("restaurar")}Voltar todo o mix ao da planilha</button></div>
    </aside>
    <div id="cc-seg-editor"></div>
  </div>`;
  alvo.querySelector("#cc-busca-seg").addEventListener("input", (e) => { buscaSeg = e.target.value; desenharSegmentos(true); });
  alvo.querySelector("#cc-novo-seg").addEventListener("submit", (e) => {
    e.preventDefault();
    const inp = alvo.querySelector("#cc-novo-seg-nome"), chave = normalizar(inp.value);
    if (!chave) return;
    if (!(chave in rasc.mix.segmentos)) rasc.mix.segmentos[chave] = [];
    segSel = chave;
    buscaSeg = "";
    inp.value = "";
    alvo.querySelector("#cc-busca-seg").value = "";
    desenharSegmentos(true);
    desenharEditorSeg();
    raiz.querySelector("#cc-novo-item")?.focus();
  });
  alvo.querySelector("#cc-padrao-mix").addEventListener("click", () => {
    rasc.mix.segmentos = clone(dados.padrao.mix.segmentos);
    mexeu = true;
    toast("O mix de todos os segmentos voltou ao da planilha, com os ajustes combinados. Confira e salve");
    renderSecao();
  });
  desenharSegmentos(animar);
  desenharEditorSeg();
}

function desenharSegmentos(animarLista = false) {
  const el = raiz.querySelector("#cc-segs");
  if (!el) return;
  const termo = normalizar(buscaSeg);
  el.classList.toggle("sem-animar", !animarLista);
  el.innerHTML = segmentos().filter((s) => !termo || normalizar(s.nome).includes(termo)).map((s, i) => `
    <button type="button" class="usu-item ${s.chave === segSel ? "selecionado" : ""} ${s.itens ? "" : "inativo"}" data-seg="${esc(s.chave)}" style="--i:${i}">
      <span class="avatar">${s.itens || "–"}</span>
      <span class="t"><b>${esc(s.nome)}${segMudou(s.chave) ? " <em>(alterado)</em>" : ""}</b>
        <small>${s.clientes ? plural(s.clientes, "cliente ativo", "clientes ativos") : s.noErp ? "nenhum cliente ativo" : "não está no cadastro do ERP"} · ${s.itens ? plural(s.itens, "item", "itens") : "sem mix"}</small></span>
    </button>`).join("") || `<p class="usu-nota">${icone("busca")}Nenhum segmento com esse nome.</p>`;
  el.querySelectorAll("[data-seg]").forEach((b) => b.addEventListener("click", () => {
    if (segSel === b.dataset.seg) return;
    segSel = b.dataset.seg;
    desenharSegmentos();
    animar = true;
    desenharEditorSeg();
    animar = false;
  }));
}

function itemHtml(it, i, n, nMus) {
  const acoes = `<div class="cc-item-acoes">
    <button type="button" class="btn icone" data-subir="${i}" title="Subir" aria-label="Subir o item" ${i === 0 ? "disabled" : ""}>${icone("acima")}</button>
    <button type="button" class="btn icone" data-descer="${i}" title="Descer" aria-label="Descer o item" ${i === n - 1 ? "disabled" : ""}>${icone("abaixo")}</button>
    <button type="button" class="btn icone" data-tirar-item="${i}" title="Tirar o item" aria-label="Tirar o item">${icone("lixeira")}</button></div>`;
  if (it.mussarela) {
    return `<li class="cc-item mussarela"><span class="cc-item-n">${i + 1}</span>
      <div class="cc-item-corpo"><div><b>Qualquer mussarela</b><small>${plural(nMus, "produto", "produtos")} da linha de mussarela no ERP: fatiada ou não, de qualquer marca</small></div></div>${acoes}</li>`;
  }
  return `<li class="cc-item"><span class="cc-item-n">${i + 1}</span>
    <div class="cc-item-corpo">
      <div class="cc-prods">${it.produtos.map((p) => `<span class="cc-prod${produtos.has(Number(p)) ? "" : " sem"}" title="${esc(nomeProduto(p))}">${esc(nomeProduto(p))}<small>${p}</small>
        <button type="button" data-tirar-prod="${i}" data-p="${p}" title="Tirar do item" aria-label="Tirar ${esc(nomeProduto(p))} do item">${icone("x")}</button></span>`).join("")}</div>
      <label class="campo sem-seta cc-mais-prod"><span class="ic-campo">${icone("mais")}</span><input list="cc-produtos" data-mais-prod="${i}" placeholder="Outro produto que vale pelo mesmo item" autocomplete="off" aria-label="Outro produto que vale pelo mesmo item"></label>
    </div>${acoes}</li>`;
}

function desenharEditorSeg() {
  const alvo = raiz.querySelector("#cc-seg-editor");
  if (!alvo) return;
  const s = segmentos().find((x) => x.chave === segSel);
  if (!s) {
    alvo.innerHTML = `<section class="cartao usu-vazio"><div class="usu-vazio-ic">${icone("loja")}</div><h3>Nenhum segmento ainda</h3>
      <p>Os segmentos aparecem depois da primeira cópia do banco do ERP; dá para adicionar um pelo nome, ao lado.</p></section>`;
    return;
  }
  const itens = rasc.mix.segmentos[s.chave] || [];
  const nMus = [...produtos.values()].filter((p) => p.mussarela).length;
  const pad = dados.padrao.mix.segmentos[s.chave];
  const pts = Number(num(rasc.mix.pontos)) || 0;
  alvo.innerHTML = `
  <section class="cartao usu-editor${entra(2)}">
    <div class="cartao-cab"><div><h2>${icone("queijo")}Mix ideal de ${esc(s.nome)}</h2>
      <p class="sub">${s.clientes ? plural(s.clientes, "cliente ativo", "clientes ativos") : "Nenhum cliente ativo com este segmento"}${
        itens.length ? ` · ${plural(itens.length, "item", "itens")}: cada item comprado no período vale ${fmt.num(pts / itens.length, 2)} pontos` : ""}</p></div></div>
    ${itens.length ? `<ol class="cc-itens">${itens.map((it, i) => itemHtml(it, i, itens.length, nMus)).join("")}</ol>`
      : `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Sem mix: os clientes deste segmento ficam com 0 no mix e sinalizados. Adicione os itens abaixo.</span></p>`}
    <div class="cc-novo-item">
      <label class="campo sem-seta"><span class="ic-campo">${icone("mais")}</span><input list="cc-produtos" id="cc-novo-item" placeholder="Item novo: o código ou o nome do produto" autocomplete="off" aria-label="Item novo"></label>
      <button class="btn" type="button" id="cc-mais-mus" ${itens.some((it) => it.mussarela) ? "disabled" : ""}>${icone("queijo")}Qualquer mussarela</button>
    </div>
    <p class="usu-nota">${icone("info")}<span>Os produtos de um mesmo item valem um pelo outro (a mesma cor na planilha): comprar qualquer um deles atende o item.
      O produto 3643 conta como 11469, como em Metas.</span></p>
    ${!produtos.size ? `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Os nomes dos produtos aparecem depois da primeira cópia do banco do ERP; até lá, digite o código.</span></p>` : ""}
    <p class="form-erro" id="cc-erro" role="alert" hidden></p>
    <div class="sug-regras-acoes cc-acoes">
      ${pad ? `<button class="btn" type="button" id="cc-seg-padrao" ${igual(pad, itens) ? "disabled" : ""}>${icone("restaurar")}Voltar ao da planilha</button>` : ""}
      ${itens.length ? `<button class="btn" type="button" id="cc-seg-tirar">${icone("lixeira")}Tirar o mix deste segmento</button>` : ""}
    </div>
  </section>`;
  const aoMudar = () => {
    mudou();
    desenharSegmentos();
    desenharEditorSeg();
  };
  const lista = () => (rasc.mix.segmentos[s.chave] ||= []);
  const ondeEsta = (id) => lista().findIndex((it) => (it.produtos || []).includes(id));
  ligarEscolha(alvo.querySelector("#cc-novo-item"), (id) => {
    const i = ondeEsta(id);
    if (i >= 0) return toast(`${nomeProduto(id)} já está no item ${i + 1}`, "erro");
    lista().push({ produtos: [id] });
    aoMudar();
    raiz.querySelector("#cc-novo-item")?.focus();
  });
  alvo.querySelectorAll("[data-mais-prod]").forEach((inp) => ligarEscolha(inp, (id) => {
    const n = Number(inp.dataset.maisProd), i = ondeEsta(id);
    if (i >= 0) return toast(`${nomeProduto(id)} já está no item ${i + 1}`, "erro");
    lista()[n].produtos.push(id);
    aoMudar();
    raiz.querySelector(`[data-mais-prod="${n}"]`)?.focus();
  }));
  alvo.querySelectorAll("[data-tirar-prod]").forEach((b) => b.addEventListener("click", () => {
    const it = lista()[Number(b.dataset.tirarProd)];
    it.produtos = it.produtos.filter((p) => p !== Number(b.dataset.p));
    if (!it.produtos.length) lista().splice(Number(b.dataset.tirarProd), 1);
    aoMudar();
  }));
  alvo.querySelector("#cc-mais-mus").addEventListener("click", () => {
    if (lista().some((it) => it.mussarela)) return;
    lista().push({ mussarela: true });
    aoMudar();
  });
  const trocar = (a, b) => { const l = lista(); [l[a], l[b]] = [l[b], l[a]]; aoMudar(); };
  alvo.querySelectorAll("[data-subir]").forEach((b) => b.addEventListener("click", () => trocar(Number(b.dataset.subir), Number(b.dataset.subir) - 1)));
  alvo.querySelectorAll("[data-descer]").forEach((b) => b.addEventListener("click", () => trocar(Number(b.dataset.descer), Number(b.dataset.descer) + 1)));
  alvo.querySelectorAll("[data-tirar-item]").forEach((b) => b.addEventListener("click", () => {
    lista().splice(Number(b.dataset.tirarItem), 1);
    aoMudar();
  }));
  alvo.querySelector("#cc-seg-padrao")?.addEventListener("click", () => {
    rasc.mix.segmentos[s.chave] = clone(pad);
    aoMudar();
  });
  alvo.querySelector("#cc-seg-tirar")?.addEventListener("click", () => {
    rasc.mix.segmentos[s.chave] = [];
    aoMudar();
  });
}

// ======================================================================================
// Custos: o custo industrial por mês e os produtos que usam o custo de outro
// ======================================================================================
// Um custo digitado: reais com vírgula ou ponto (27,57 ou 27.57). null = vazio; NaN = inválido.
function lerCusto(texto) {
  let t = String(texto ?? "").trim().replace(/^R\$\s*/i, "").replace(/\s/g, "");
  if (!t) return null;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  const v = Number(t);
  return Number.isFinite(v) && v > 0 && v <= MAX_CUSTO ? Math.round(v * 1e6) / 1e6 : NaN;
}

// As colunas da tabela: do mês de início do lucro bruto até o mês passado (ou o último mês com custo, se for depois).
function mesesDaTabela() {
  const r = rasc.rentabilidade;
  const ini = mesValido(r.desde) ? r.desde : mesValido(orig.rentabilidade.desde) ? orig.rentabilidade.desde : "2026-01";
  const hoje = new Date();
  let fim = hoje.getMonth() === 0 ? `${hoje.getFullYear() - 1}-12` : `${hoje.getFullYear()}-${String(hoje.getMonth()).padStart(2, "0")}`;
  for (const linha of Object.values(r.custos)) for (const m of Object.keys(linha)) if (m > fim) fim = m;
  const meses = [];
  for (let m = ini; m <= fim && meses.length < 36; m = proximoMes(m)) meses.push(m);
  return meses.length ? meses : [ini];
}

function secaoCustos(alvo) {
  const r = rasc.rentabilidade, meses = mesesDaTabela();
  const usaDe = r.usa_custo_de;
  const usadoPor = (p) => Object.entries(usaDe).filter(([, b]) => String(b) === String(p)).map(([a]) => a);
  const termo = normalizar(buscaCusto);
  const linhas = Object.keys(r.custos).map(Number)
    .filter((p) => !termo || normalizar(`${p} ${nomeProduto(p)}`).includes(termo))
    .sort((a, b) => nomeProduto(a).localeCompare(nomeProduto(b), "pt-BR"));
  const aliases = Object.entries(usaDe).sort(([a], [b]) => nomeProduto(a).localeCompare(nomeProduto(b), "pt-BR"));
  const temCusto = (p) => Object.keys(r.custos[String(p)] || {}).length > 0;
  const semCusto = [...produtos.values()].filter((p) => p.vendido && !temCusto(p.id) && !(String(p.id) in usaDe))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  const celula = (p, m) => {
    const k = `${p}|${m}`, v = r.custos[String(p)]?.[m], antes = orig.rentabilidade.custos[String(p)]?.[m];
    const classe = k in invalidos ? " erro" : (antes ?? null) !== (v ?? null) ? " mudou" : "";
    return `<td><input class="cc-custo${classe}" data-p="${p}" data-m="${m}" inputmode="decimal" placeholder="—" value="${esc(k in invalidos ? invalidos[k] : v != null ? NUM_CUSTO.format(v) : "")}" aria-label="${esc(`Custo de ${nomeProduto(p)} em ${mesRotulo(m)}`)}"></td>`;
  };
  alvo.innerHTML = `
  <section class="cartao secao${entra(1)}">
    <div class="cartao-cab"><div><h2>${icone("moeda")}Custo industrial por mês</h2>
      <p class="sub">Em reais por unidade vendida (o kg ou a peça, como no pedido), de ${mesRotulo(meses[0])} a ${mesRotulo(meses[meses.length - 1])}. A venda usa o custo do mês dela; sem custo no mês, fica fora do lucro bruto. Dá para colar do Excel</p></div>
      <div class="cc-cab-acoes"><button class="btn" type="button" id="cc-importar">${icone("arquivo")}Importar planilha</button>
        <input type="file" id="cc-arquivo" accept=".xlsx,${TIPO_XLSX}" hidden></div></div>
    <div id="cc-importada"></div>
    <div class="cc-barra-tabela">
      <label class="campo sem-seta cc-busca-custo"><span class="ic-campo">${icone("busca")}</span><input type="search" id="cc-busca-custo" placeholder="Buscar produto" value="${esc(buscaCusto)}" aria-label="Buscar produto na tabela"></label>
      <label class="campo sem-seta cc-mais-linha"><span class="ic-campo">${icone("mais")}</span><input list="cc-produtos" id="cc-mais-linha" placeholder="Produto novo na tabela: o código ou o nome" autocomplete="off" aria-label="Produto novo na tabela"></label>
    </div>
    ${linhas.length ? `<div class="tabela-rolagem cc-custos-rolagem"><table class="dados cc-custos">
      <thead><tr><th class="esq">Produto</th>${meses.map((m) => `<th>${mesRotulo(m)}</th>`).join("")}<th><span class="sr">Tirar</span></th></tr></thead>
      <tbody>${linhas.map((p) => {
        const prod = produtos.get(p), por_ = usadoPor(p);
        return `<tr data-linha="${p}"><td class="esq"><b>${esc(nomeProduto(p))}</b><small>${p}${prod?.unidade ? ` · ${esc(prod.unidade)}` : ""}${
          por_.length ? ` · vale também para ${esc(por_.map(nomeProduto).join(", "))}` : ""}</small></td>
          ${meses.map((m) => celula(p, m)).join("")}
          <td><button class="btn icone" type="button" data-tirar-linha="${p}" title="Tirar o produto da tabela" aria-label="Tirar ${esc(nomeProduto(p))} da tabela">${icone("lixeira")}</button></td></tr>`;
      }).join("")}</tbody></table></div>`
      : `<div class="vazio">${icone(termo ? "busca" : "moeda")}<p>${termo ? "Nenhum produto da tabela com esse nome." : "Nenhum custo ainda: importe a planilha ou adicione os produtos."}</p></div>`}
    <p class="form-erro" id="cc-erro" role="alert" hidden></p>
  </section>

  <section class="cartao secao${entra(2)}">
    <div class="cartao-cab"><div><h2>${icone("elo")}Produtos que usam o custo de outro</h2>
      <p class="sub">Para o produto sem linha própria na planilha de custos: mês a mês, ele usa o custo do outro</p></div></div>
    ${aliases.length ? `<div class="cc-usa">${aliases.map(([a, b]) => `<div class="cc-usa-linha">
        <span><b>${esc(nomeProduto(a))}</b><small>${a}</small></span>
        <span class="cc-usa-seta">usa o custo de ${icone("seta")}</span>
        <span><b>${esc(nomeProduto(b))}</b><small>${b}${temCusto(b) ? "" : " · sem custo na tabela"}</small></span>
        <button class="btn icone" type="button" data-tirar-usa="${a}" title="Tirar" aria-label="Tirar">${icone("lixeira")}</button></div>`).join("")}</div>`
      : `<p class="usu-nota">${icone("info")}<span>Nenhum produto usa o custo de outro.</span></p>`}
    <div class="cc-usa-novo">
      <label class="campo sem-seta"><input list="cc-produtos" id="cc-usa-a" placeholder="Produto" autocomplete="off" aria-label="Produto"></label>
      <span>usa o custo de</span>
      <label class="campo sem-seta"><input list="cc-produtos" id="cc-usa-b" placeholder="Outro produto" autocomplete="off" aria-label="Usa o custo de"></label>
      <button class="btn" type="button" id="cc-usa-mais">${icone("mais")}Adicionar</button>
    </div>
  </section>

  <section class="cartao secao${entra(3)}">
    <div class="cartao-cab"><div><h2>${icone("alerta")}Vendidos sem custo</h2>
      <p class="sub">Produtos vendidos desde ${mesRotulo(orig.rentabilidade.desde)} que não têm custo nem usam o de outro: o faturamento deles fica fora do lucro bruto. Clique para pôr na tabela</p></div></div>
    ${!produtos.size ? `<p class="usu-nota">${icone("info")}<span>A lista aparece depois da primeira cópia do banco do ERP.</span></p>`
      : semCusto.length ? `<div class="cc-sem">${semCusto.map((p) => `<button type="button" class="cc-sem-op" data-mais-sem="${p.id}" title="Pôr na tabela de custos">
          <span>${esc(p.nome)}<small>${p.id}${p.linha ? ` · ${esc(p.linha)}` : ""}${p.inativo ? " · inativo" : ""}</small></span>${icone("mais")}</button>`).join("")}</div>`
        : `<p class="usu-nota">${icone("certo")}<span>Todos os produtos vendidos no período têm custo.</span></p>`}
    <div class="sug-regras-acoes"><button class="btn" type="button" id="cc-padrao-custos">${icone("restaurar")}Voltar os custos ao padrão (a planilha de jan a set de 2026)</button></div>
  </section>`;

  const tbody = alvo.querySelector(".cc-custos tbody");
  const porCelula = (inp) => {
    const p = inp.dataset.p, m = inp.dataset.m, k = `${p}|${m}`, v = lerCusto(inp.value);
    const linha = (rasc.rentabilidade.custos[p] ||= {});
    delete invalidos[k];
    if (v === null) delete linha[m];
    else if (Number.isNaN(v)) invalidos[k] = inp.value;
    else linha[m] = v;
    const antes = orig.rentabilidade.custos[p]?.[m];
    inp.classList.toggle("erro", k in invalidos);
    inp.classList.toggle("mudou", !(k in invalidos) && (antes ?? null) !== (linha[m] ?? null));
  };
  alvo.querySelectorAll(".cc-custo").forEach((inp) => {
    inp.addEventListener("input", () => { porCelula(inp); mudou(); });
    // Colar do Excel: os valores separados por tabulação vão para os meses seguintes; as linhas, para os produtos de baixo.
    inp.addEventListener("paste", (e) => {
      const texto = (e.clipboardData?.getData("text") || "").replace(/\r/g, "").replace(/\n+$/, "");
      if (!/[\t\n]/.test(texto)) return;
      e.preventDefault();
      const trs = [...tbody.querySelectorAll("tr[data-linha]")];
      const li = trs.indexOf(inp.closest("tr")), ci = meses.indexOf(inp.dataset.m);
      texto.split("\n").forEach((linhaT, dl) => {
        const tr = trs[li + dl];
        if (!tr) return;
        linhaT.split("\t").forEach((t, dc) => {
          const m = meses[ci + dc], cel = m && tr.querySelector(`.cc-custo[data-m="${m}"]`);
          if (!cel) return;
          cel.value = t.trim();
          porCelula(cel);
        });
      });
      mudou();
    });
  });
  alvo.querySelector("#cc-busca-custo").addEventListener("input", (e) => {
    buscaCusto = e.target.value;
    const pos = e.target.selectionStart;
    secaoCustos(alvo);
    const novo = alvo.querySelector("#cc-busca-custo");
    novo.focus();
    novo.setSelectionRange(pos, pos);
  });
  const porNaTabela = (id) => {
    const k = String(id);
    if (k in usaDe) return toast(`${nomeProduto(id)} usa o custo de ${nomeProduto(usaDe[k])}: tire de "usa o custo de" antes`, "erro");
    if (!(k in rasc.rentabilidade.custos)) { rasc.rentabilidade.custos[k] = {}; mudou(); }
    buscaCusto = "";
    secaoCustos(alvo);
    const tr = alvo.querySelector(`tr[data-linha="${k}"]`);
    tr?.scrollIntoView({ block: "center" });
    tr?.querySelector(".cc-custo")?.focus();
  };
  ligarEscolha(alvo.querySelector("#cc-mais-linha"), porNaTabela);
  alvo.querySelectorAll("[data-mais-sem]").forEach((b) => b.addEventListener("click", () => porNaTabela(Number(b.dataset.maisSem))));
  alvo.querySelectorAll("[data-tirar-linha]").forEach((b) => b.addEventListener("click", () => {
    const p = b.dataset.tirarLinha;
    delete rasc.rentabilidade.custos[p];
    for (const k of Object.keys(invalidos)) if (k.startsWith(`${p}|`)) delete invalidos[k];
    mudou();
    secaoCustos(alvo);
  }));
  alvo.querySelectorAll("[data-tirar-usa]").forEach((b) => b.addEventListener("click", () => {
    delete rasc.rentabilidade.usa_custo_de[b.dataset.tirarUsa];
    mudou();
    secaoCustos(alvo);
  }));
  alvo.querySelector("#cc-usa-mais").addEventListener("click", () => {
    const a = produtoDigitado(alvo.querySelector("#cc-usa-a").value), b = produtoDigitado(alvo.querySelector("#cc-usa-b").value);
    if (a == null || b == null) return erro("Escolha os dois produtos da lista (ou digite os códigos).");
    const usa = rasc.rentabilidade.usa_custo_de;
    if (a === b) return erro("O produto não pode usar o próprio custo.");
    if (String(b) in usa) return erro(`${nomeProduto(b)} já usa o custo de ${nomeProduto(usa[String(b)])}: aponte direto para o original.`);
    if (Object.values(usa).some((x) => Number(x) === a)) return erro(`Outros produtos usam o custo de ${nomeProduto(a)}: ele não pode usar o de outro.`);
    if (temCusto(a)) return erro(`${nomeProduto(a)} tem custo na tabela: tire a linha dele antes, para usar o custo de ${nomeProduto(b)}.`);
    delete rasc.rentabilidade.custos[String(a)];
    usa[String(a)] = b;
    mudou();
    secaoCustos(alvo);
  });
  alvo.querySelector("#cc-padrao-custos").addEventListener("click", () => {
    rasc.rentabilidade.custos = clone(dados.padrao.rentabilidade.custos);
    rasc.rentabilidade.usa_custo_de = clone(dados.padrao.rentabilidade.usa_custo_de);
    invalidos = {};
    mexeu = true;
    toast("Custos no padrão: a planilha de jan a set de 2026, com os ajustes combinados. Confira e salve");
    renderSecao();
  });
  alvo.querySelector("#cc-importar").addEventListener("click", () => alvo.querySelector("#cc-arquivo").click());
  alvo.querySelector("#cc-arquivo").addEventListener("change", async (e) => {
    const arq = e.target.files?.[0];
    e.target.value = "";
    if (!arq) return;
    if (arq.size > MAX_PLANILHA) return erro("A planilha passou de 5 MB.");
    const btn = alvo.querySelector("#cc-importar");
    btn.disabled = true;
    try {
      const r = await api("/api/crm/custos/importar", { method: "POST", headers: { "Content-Type": TIPO_XLSX }, body: arq });
      importada = {
        nome: arq.name, meses: r.meses || [],
        linhas: (r.linhas || []).map((l) => {
          const id = l.id == null ? null : Number(l.id), custos = l.custos || {};
          return { produto: l.produto, custos, id, levar: id != null && Object.keys(custos).length > 0 && !(String(id) in rasc.rentabilidade.usa_custo_de) };
        }),
      };
      desenharImportada();
    } catch (err) {
      erro(err.message);
    } finally {
      btn.disabled = false;
    }
  });
  desenharImportada();
}

// A planilha importada: o que vai mudar na tabela, antes de levar.
function desenharImportada() {
  const el = raiz.querySelector("#cc-importada");
  if (!el) return;
  if (!importada) { el.innerHTML = ""; return; }
  const { linhas, meses } = importada;
  const levar = linhas.filter((l) => l.levar && l.id != null);
  const situacao = (l) => {
    const ms = Object.keys(l.custos);
    if (!ms.length) return "sem custo na planilha";
    if (l.id == null) return "escolha o produto do ERP";
    const usa = rasc.rentabilidade.usa_custo_de[String(l.id)];
    if (usa != null) return `usa o custo de ${nomeProduto(usa)}: marcado, passa a ter o custo da planilha`;
    const atual = rasc.rentabilidade.custos[String(l.id)] || {};
    if (!Object.keys(atual).length) return "produto novo na tabela";
    const n = ms.filter((m) => atual[m] !== l.custos[m]).length;
    return n ? `muda ${plural(n, "mês", "meses")}` : "igual à tabela";
  };
  el.innerHTML = `<div class="cc-import">
    <div class="cc-import-cab"><div><b>${icone("arquivo")}${esc(importada.nome)}</b>
      <small>${plural(linhas.length, "produto", "produtos")}, ${meses.length ? `de ${mesRotulo(meses[0])} a ${mesRotulo(meses[meses.length - 1])}` : "sem meses"}.
        Os meses com valor na planilha substituem os da tabela; o mês vazio ou com 0 fica como está. Nada é salvo antes de você salvar.</small></div>
      <div class="cc-import-acoes"><button class="btn" type="button" id="cc-imp-cancelar">Cancelar</button>
        <button class="btn primario" type="button" id="cc-imp-levar" ${levar.length ? "" : "disabled"}>${icone("visto")}Levar ${plural(levar.length, "produto", "produtos")} para a tabela</button></div></div>
    <div class="tabela-rolagem"><table class="dados cc-imp-tabela">
      <thead><tr><th class="esq">Na planilha</th><th class="esq">Produto do ERP</th><th class="esq">Meses com custo</th><th class="esq">O que muda</th></tr></thead>
      <tbody>${linhas.map((l, i) => {
        const ms = Object.keys(l.custos), faltam = meses.filter((m) => !(m in l.custos));
        return `<tr><td class="esq"><label class="cc-imp-marca"><input type="checkbox" data-imp-levar="${i}" ${l.levar && l.id != null ? "checked" : ""} ${!ms.length || l.id == null ? "disabled" : ""}>${esc(l.produto)}</label></td>
          <td class="esq">${l.id != null ? `${esc(nomeProduto(l.id))} <small>${l.id}</small> <button type="button" class="cc-link" data-imp-trocar="${i}">trocar</button>`
            : `<input list="cc-produtos" data-imp-produto="${i}" placeholder="Escolha o produto" autocomplete="off" aria-label="${esc(`Produto do ERP para ${l.produto}`)}">`}</td>
          <td class="esq">${fmt.num(ms.length)}${faltam.length && ms.length ? ` <small>sem ${esc(faltam.map(mesRotulo).join(", "))}</small>` : ""}</td>
          <td class="esq">${esc(situacao(l))}</td></tr>`;
      }).join("")}</tbody></table></div>
  </div>`;
  el.querySelector("#cc-imp-cancelar").addEventListener("click", () => { importada = null; desenharImportada(); });
  el.querySelectorAll("[data-imp-levar]").forEach((c) => c.addEventListener("change", () => {
    importada.linhas[Number(c.dataset.impLevar)].levar = c.checked;
    desenharImportada();
  }));
  el.querySelectorAll("[data-imp-trocar]").forEach((b) => b.addEventListener("click", () => {
    const l = importada.linhas[Number(b.dataset.impTrocar)];
    l.id = null;
    l.levar = false;
    desenharImportada();
    el.querySelector(`[data-imp-produto="${b.dataset.impTrocar}"]`)?.focus();
  }));
  el.querySelectorAll("[data-imp-produto]").forEach((inp) => ligarEscolha(inp, (id) => {
    const l = importada.linhas[Number(inp.dataset.impProduto)];
    l.id = id;
    l.levar = Object.keys(l.custos).length > 0 && !(String(id) in rasc.rentabilidade.usa_custo_de);
    desenharImportada();
  }));
  el.querySelector("#cc-imp-levar").addEventListener("click", () => {
    const marcadas = importada.linhas.filter((l) => l.levar && l.id != null && Object.keys(l.custos).length);
    const ids = marcadas.map((l) => l.id), repetido = ids.find((id, i) => ids.indexOf(id) !== i);
    if (repetido != null) return erro(`${nomeProduto(repetido)} está em duas linhas da planilha: desmarque uma.`);
    const usa = rasc.rentabilidade.usa_custo_de;
    for (const l of marcadas) {
      const k = String(l.id);
      delete usa[k];
      rasc.rentabilidade.custos[k] = { ...(rasc.rentabilidade.custos[k] || {}), ...l.custos };
      for (const m of Object.keys(l.custos)) delete invalidos[`${k}|${m}`];
    }
    importada = null;
    mudou();
    toast(`${plural(marcadas.length, "produto levado", "produtos levados")} para a tabela. Confira e salve`);
    secaoCustos(raiz.querySelector("#cc-secao"));
  });
}

// ---------- gravação ----------
// O que impede de salvar (null = pode). O servidor confere tudo de novo.
function erroLocal() {
  if (!rasc.equipes.length) return ["regras", "Escolha ao menos uma equipe."];
  const m = maximos(rasc), soma = m.aderencia + m.pontualidade + m.mix + m.rentabilidade;
  if (Math.abs(soma - 100) > 1e-6) return ["regras", `Os pontos máximos dos quatro indicadores somam ${fmt.num(soma, 2)}: precisam dar 100.`];
  if (!mesValido(rasc.rentabilidade.desde)) return ["regras", "Rentabilidade: escolha o mês de início do lucro bruto."];
  const inv = Object.keys(invalidos)[0];
  if (inv) {
    const [p, mes] = inv.split("|");
    return ["custos", `O custo de ${nomeProduto(p)} em ${mesRotulo(mes)} não é um valor válido: digite em reais, maior que zero (ex.: 27,57).`];
  }
  return null;
}

async function salvar() {
  const e = erroLocal();
  if (e) {
    if (secao !== e[0]) irPara(e[0]);
    return erro(e[1]);
  }
  const btn = raiz.querySelector("#cc-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/crm/config", { json: { config: paraSalvar(rasc) } }));
    toast("Regras do CRM salvas: as notas já usam as novas");
    ctx.aoSalvar && ctx.aoSalvar();
    animar = false;
    render();
  } catch (err) {
    erro(err.message);
  } finally {
    btn.disabled = false;
  }
}
