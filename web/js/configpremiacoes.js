// Configuração da página Premiações (só administradores): as faixas dos vendedores; cada supervisor (nome, variável,
// pesos, meta do mix, prêmio da inadimplência e as metas de todo mês de clientes novos e de reativação); as regras dos
// supervisores (as faixas, a trava, o bônus, o desconto pelo vencido, os dias sem comprar da reativação, os produtos
// fora do mix e os dias de atraso da inadimplência); as metas de um supervisor num mês; os motivos dos brindes que
// descontam da comissão; e, em "Acesso por usuário", as abas e os quadros de supervisor que cada visualizador vê (os
// vendedores dele, em todas as páginas, ficam em Usuários; aqui só aparecem, para avisar do quadro que ficaria de fora).
// Tudo vale depois de Salvar; as regras, para todos os meses.
import { api, esc, fmt, icone, toast } from "./util.js";
import { iniciais } from "./conta.js";

const INDICADORES = [
  ["faturamento", "Faturamento líquido"], ["mix", "Mix (exceto mussarela)"], ["positivacao", "Positivação"],
  ["novos", "Ativação de clientes novos"], ["reativacao", "Reativação de clientes"],
];
const SECOES = [["vendedores", "usuario", "Vendedores"], ["supervisores", "pessoas", "Supervisores"],
  ["regras", "ajustes", "Regras dos supervisores"], ["metas", "alvo", "Metas dos supervisores"], ["comissao", "moeda", "Comissão"],
  ["usuarios", "escudo", "Acesso por usuário"]];
// As abas da página Premiações, na ordem dela (bi/premiacoes.py ABAS).
const ABAS = [
  ["vendedores", "usuario", "Vendedores", "a premiação de cada vendedor pela meta de clientes"],
  ["supervisores", "pessoas", "Supervisores", "os quadros dos supervisores, que somam a carteira inteira do estado"],
  ["comissao", "moeda", "Comissão", "a comissão de cada vendedor das equipes BA e ES"],
];
const NOME_EQUIPE = { ES: "ES", BA: "BA", EDIR: "Edir" };

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/premiacoes/config
let orig = null, rasc = null;
let usuarios = [], nomesAcesso = {};     // os visualizadores e o nome dos vendedores das listas de "só alguns"
let origAcessos = null, acessos = null;  // login -> { ve, abas, supervisores }
let usuarioSel = null, buscaUsuario = "";
let secao = "vendedores";

const clone = (o) => JSON.parse(JSON.stringify(o));
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

export function configPremiacoesTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigPremiacoes(container, contexto) {
  ctx = contexto;
  raiz = container;
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    const mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : "";
    if (SECOES.some(([id]) => id === q.get("secao"))) secao = q.get("secao");
    if (q.get("u")) { secao = "usuarios"; usuarioSel = q.get("u"); }  // o link "Configurar" da tela Usuários
    carregarDados(await api(`/api/premiacoes/config${mes ? `?mes=${mes}` : ""}`));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  orig = clone(r.config);
  rasc = clone(r.config);
  usuarios = r.usuarios || [];
  nomesAcesso = r.nomes || {};
  origAcessos = Object.fromEntries(usuarios.map((u) => [u.login, {
    ve: (u.paginas || []).includes("premiacoes"),
    abas: [...(u.premiacoes?.abas || [])],
    supervisores: [...(u.premiacoes?.supervisores || [])],
  }]));
  acessos = clone(origAcessos);
  if (!usuarios.some((u) => u.login === usuarioSel)) usuarioSel = usuarios[0]?.login ?? null;
}

// ---------- apoio ----------
const pct = (v, casas = 2) => (v == null || isNaN(v) ? "" : String(Math.round(v * 100 * 10 ** casas) / 10 ** casas));
const numero = (inp) => (inp.value.trim() === "" ? NaN : Number(inp.value));

// Quantas folhas (valores) mudaram entre o rascunho e o salvo (um ajuste novo conta uma vez; uma lista de códigos, como
// os motivos, conta como uma folha só).
function folhas(o, prefixo = "", saida = {}) {
  if (Array.isArray(o) && o.every((x) => x === null || typeof x !== "object")) {
    saida[prefixo] = JSON.stringify(o);
  } else if (o && typeof o === "object") {
    for (const [k, v] of Object.entries(o)) folhas(v, `${prefixo}.${k}`, saida);
  } else saida[prefixo] = o;
  return saida;
}

function contarAlteracoesRegras() {
  const a = folhas(rasc), b = folhas(orig);
  let n = 0;
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) if (!Object.is(a[k], b[k])) n++;
  return n;
}

// Uma pessoa com o acesso mudado conta como uma alteração.
const usuarioMudou = (login) => !igual(acessos[login], origAcessos[login]);
const usuariosMudados = () => usuarios.filter((u) => usuarioMudou(u.login));
const contarAlteracoes = () => contarAlteracoesRegras() + usuariosMudados().length;

const somaPesos = (s) => INDICADORES.reduce((t, [k]) => t + (Number(s.pesos[k]) || 0), 0);
const padraoDe = (id) => dados.padrao.supervisores.lista.find((x) => x.id === id);

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${SECOES.map(([id, ic, nome]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}</button>`).join("")}
      <div class="dica">${icone("info")} As regras valem para todos os meses assim que você salvar: mudar uma faixa ou um
        peso recalcula também os meses que já passaram. As abas e os quadros de supervisor de cada pessoa ficam em Acesso
        por usuário; os vendedores dentro deles, em <a href="#/usuarios">Usuários</a> (o quadro de um supervisor, só para
        quem vê todos os vendedores do estado dele).</div>
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
  raiz.querySelector("#cp-descartar").addEventListener("click", () => { rasc = clone(orig); acessos = clone(origAcessos); render(); });
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cp-secao");
  if (secao === "supervisores") secaoSupervisores(alvo);
  else if (secao === "regras") secaoRegras(alvo);
  else if (secao === "metas") secaoMetas(alvo);
  else if (secao === "comissao") secaoComissao(alvo);
  else if (secao === "usuarios") secaoUsuarios(alvo);
  else secaoVendedores(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cp-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cp-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
}

function rodapePadrao(rotulo = "Restaurar o padrão") {
  return `<p class="form-erro" id="cp-erro" hidden></p>
    <div class="sug-regras-acoes"><button class="btn" type="button" id="cp-padrao">${icone("restaurar")}${rotulo}</button></div>`;
}

function ligarPadrao(alvo) {
  alvo.querySelector("#cp-padrao").addEventListener("click", () => {
    const metasMes = rasc.supervisores.metas_mes;
    rasc = clone(dados.padrao);
    rasc.supervisores.metas_mes = metasMes; // as metas trocadas em cada mês ficam
    toast("Padrão aplicado (faixas dos vendedores, supervisores, regras e brindes da comissão); as metas de cada mês ficam. Confira e salve");
    renderSecao();
  });
}

// ======================================================================================
// Vendedores: as faixas
// ======================================================================================
function secaoVendedores(alvo) {
  const faixas = rasc.vendedores.faixas;
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("usuario")}Faixas dos vendedores</h2>
      <p class="sub">O % é de clientes atendidos sobre a META CLIENTE do mês. Vale a maior faixa atingida (elas não se somam);
        abaixo da primeira, nada. Padrão do Power BI: 91% → R$ 200, 96% → R$ 250 e 100% → R$ 350.</p></div></div>
    <div class="pr-config-faixas">
      ${faixas.map((f, i) => `<div class="pr-config-faixa">
        <span>A partir de</span>
        <span class="campo sem-seta"><input type="number" min="0" max="500" step="0.5" inputmode="decimal" data-faixa="${i}" data-campo="min" value="${pct(f.min, 1)}" aria-label="% mínimo da faixa ${i + 1}"></span>
        <span>% da meta →&nbsp;R$</span>
        <span class="campo sem-seta"><input type="number" min="0" step="10" inputmode="decimal" data-faixa="${i}" data-campo="valor" value="${f.valor}" aria-label="Prêmio da faixa ${i + 1}"></span>
        <button class="btn icone" type="button" data-tirar="${i}" title="Tirar esta faixa" aria-label="Tirar esta faixa"${faixas.length === 1 ? " disabled" : ""}>${icone("lixeira")}</button>
      </div>`).join("")}
      <div><button class="btn" type="button" id="cp-mais-faixa">${icone("mais")}Acrescentar faixa</button></div>
    </div>
    ${rodapePadrao()}
  </section>`;
  alvo.querySelectorAll("[data-faixa]").forEach((inp) => inp.addEventListener("input", () => {
    const f = rasc.vendedores.faixas[Number(inp.dataset.faixa)];
    const v = inp.value.trim() === "" ? NaN : Number(inp.value);
    f[inp.dataset.campo] = inp.dataset.campo === "min" ? v / 100 : v;
    atualizarBarra();
  }));
  alvo.querySelectorAll("[data-tirar]").forEach((b) => b.addEventListener("click", () => {
    rasc.vendedores.faixas.splice(Number(b.dataset.tirar), 1);
    renderSecao();
  }));
  alvo.querySelector("#cp-mais-faixa").addEventListener("click", () => {
    const ultima = faixas[faixas.length - 1];
    faixas.push({ min: ultima ? Math.round((ultima.min + 0.05) * 1000) / 1000 : 1, valor: ultima ? ultima.valor : 0 });
    renderSecao();
  });
  ligarPadrao(alvo);
}

// ======================================================================================
// Supervisores: nome, variável, pesos, mix, inadimplência e as metas de todo mês
// ======================================================================================
function campo(chave, rotulo, valor, sufixo = "%", passo = "0.5", tipo = "number") {
  const entrada = tipo === "number"
    ? `<input type="number" min="0" step="${passo}" inputmode="decimal" data-campo="${chave}" value="${valor}">`
    : `<input type="text" maxlength="60" data-campo="${chave}" value="${esc(valor)}" style="text-align:left">`;
  return `<label${tipo === "number" ? "" : ' class="texto"'}><span>${rotulo}</span><span class="campo sem-seta">${entrada}</span><em>${sufixo}</em></label>`;
}

function blocoSupervisor(s, i) {
  const soma = somaPesos(s);
  const ruim = Math.abs(soma - 1) > 1e-6;
  const ad = s.inadimplencia;
  const mp = s.metas_padrao;
  return `<div class="pr-config-ind pr-config-sup" data-sup="${i}">
    <h4><span class="pr-estado">${esc(s.estado)}</span>${esc(s.nome || "Supervisor")}</h4>
    ${campo("nome", "Nome", s.nome, "", "", "text")}
    ${campo("variavel", "Variável", s.variavel, "R$", "100")}
    <div class="pr-config-sub">Pesos <small class="${ruim ? "form-erro" : "fraco"}">soma: ${fmt.num(soma * 100, 2)}%${ruim ? " (precisa dar 100%)" : ""} · 0 = não entra</small></div>
    ${INDICADORES.map(([k, t]) => campo(`peso.${k}`, t, pct(s.pesos[k]))).join("")}
    ${s.pesos.mix > 0 ? campo("meta_mix", "Meta do mix (sem mussarela ÷ líquido)", pct(s.meta_mix)) : ""}
    <div class="pr-config-sub">Metas de todo mês <small class="fraco">vazio = sem meta; para um mês só, use Metas dos supervisores</small></div>
    ${campo("metas.novos", "Clientes novos", mp.novos ?? "", "", "1")}
    ${campo("metas.reativacao", "Reativações", mp.reativacao ?? "", "", "1")}
    <label class="pr-config-check"><input type="checkbox" data-campo="inad"${ad ? " checked" : ""}>Prêmio da inadimplência (fora do variável)</label>
    ${ad ? campo("inad.valor", "Valor", ad.valor, "R$", "10") + campo("inad.limite", "Com inadimplência até", pct(ad.limite, 4), "%", "0.01") : ""}
  </div>`;
}

function secaoSupervisores(alvo) {
  const lista = rasc.supervisores.lista;
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("pessoas")}Supervisores</h2>
      <p class="sub">A parcela de cada indicador é o peso × o variável, e paga um % dela pela faixa atingida (as faixas, a
        trava, o bônus e o desconto ficam em Regras dos supervisores). O estado diz a carteira: os supervisores do mesmo
        estado usam os mesmos números.</p></div></div>
    <div class="pr-config-grade pr-config-sups">${lista.map(blocoSupervisor).join("")}</div>
    ${rodapePadrao()}
  </section>`;
  alvo.querySelectorAll("[data-sup]").forEach((bloco) => {
    const s = rasc.supervisores.lista[Number(bloco.dataset.sup)];
    bloco.querySelector('[data-campo="nome"]').addEventListener("input", (e) => { s.nome = e.target.value; atualizarBarra(); });
    bloco.addEventListener("change", (e) => {
      const c = e.target.dataset.campo;
      if (!c || c === "nome") { if (c === "nome") renderSecao(); return; }
      const v = numero(e.target);
      if (c === "variavel") s.variavel = v;
      else if (c.startsWith("peso.")) s.pesos[c.slice(5)] = v / 100;
      else if (c === "meta_mix") s.meta_mix = v / 100;
      else if (c.startsWith("metas.")) s.metas_padrao[c.slice(6)] = isNaN(v) ? null : v;
      else if (c === "inad") s.inadimplencia = e.target.checked ? clone((padraoDe(s.id) || {}).inadimplencia || { valor: 450, limite: 0.0045 }) : null;
      else if (c === "inad.valor") s.inadimplencia.valor = v;
      else if (c === "inad.limite") s.inadimplencia.limite = v / 100;
      renderSecao(); // a soma dos pesos e os campos que dependem deles
    });
  });
  ligarPadrao(alvo);
}

// ======================================================================================
// Regras dos supervisores: faixas, trava, bônus, desconto, motivos, produtos e dias
// ======================================================================================
function editorFaixas(chave, titulo, dica, meio) {
  const faixas = rasc.supervisores[chave];
  return `<h3 class="pr-config-tit">${titulo} <small class="fraco">${dica}</small></h3>
    <div class="pr-config-faixas" data-escala="${chave}">
      ${faixas.map((f, i) => `<div class="pr-config-faixa">
        <span>A partir de</span>
        <span class="campo sem-seta"><input type="number" min="0" max="500" step="0.5" inputmode="decimal" data-i="${i}" data-k="min" value="${pct(f.min)}" aria-label="% da meta da faixa ${i + 1}"></span>
        <span>${meio}</span>
        <span class="campo sem-seta"><input type="number" min="0" max="500" step="1" inputmode="decimal" data-i="${i}" data-k="pct" value="${pct(f.pct)}" aria-label="% pago na faixa ${i + 1}"></span>
        <button class="btn icone" type="button" data-tirar-faixa="${i}" title="Tirar esta faixa" aria-label="Tirar esta faixa"${faixas.length === 1 ? " disabled" : ""}>${icone("lixeira")}</button>
      </div>`).join("")}
      <div><button class="btn" type="button" data-mais-faixa>${icone("mais")}Acrescentar faixa</button></div>
    </div>`;
}

function editorDevolucao() {
  const d = rasc.supervisores.devolucao;
  return `<h3 class="pr-config-tit">Desconto pelo vencido <small class="fraco">o vencido ÷ as vendas do mês → o % do variável que fica; aplicado por último</small></h3>
    <div class="pr-config-faixas" data-devolucao>
      ${d.faixas.map((f, i) => `<div class="pr-config-faixa">
        <span>Até</span>
        <span class="campo sem-seta"><input type="number" min="0" max="100" step="0.1" inputmode="decimal" data-i="${i}" data-k="ate" value="${pct(f.ate, 3)}" aria-label="% de vencido da faixa ${i + 1}"></span>
        <span>% de vencido → mantém</span>
        <span class="campo sem-seta"><input type="number" min="0" max="100" step="1" inputmode="decimal" data-i="${i}" data-k="pct" value="${pct(f.pct)}" aria-label="% mantido na faixa ${i + 1}"></span>
        <button class="btn icone" type="button" data-tirar-faixa="${i}" title="Tirar esta faixa" aria-label="Tirar esta faixa">${icone("lixeira")}</button>
      </div>`).join("")}
      <div class="pr-config-faixa">
        <span>Acima disso</span><span></span><span>→ mantém</span>
        <span class="campo sem-seta"><input type="number" min="0" max="100" step="1" inputmode="decimal" data-k="acima" value="${pct(d.acima)}" aria-label="% mantido acima da última faixa"></span>
        <span></span>
      </div>
      <div><button class="btn" type="button" data-mais-faixa>${icone("mais")}Acrescentar faixa</button></div>
    </div>`;
}

function secaoRegras(alvo) {
  const s = rasc.supervisores;
  const nomesProd = Object.fromEntries(dados.produtos.map((p) => [p.id, p.nome]));
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("ajustes")}Regras dos supervisores</h2>
      <p class="sub">Valem para todos os supervisores. A conta: cada parcela paga o % da faixa atingida; sobre a soma
        delas, a trava pelo % da meta de faturamento, depois o bônus de superação e, por último, o desconto pelo vencido.
        Não há interpolação entre as faixas.</p></div></div>
    ${editorFaixas("escala_faturamento", "Faixas do faturamento e do mix", "o segundo número é o % da parcela pago", "% da meta → paga (%)")}
    ${editorFaixas("escala_clientes", "Faixas da positivação, dos novos e da reativação", "o segundo número é o % da parcela pago", "% da meta → paga (%)")}
    ${editorFaixas("trava", "Trava do faturamento", "sobre a soma das parcelas; abaixo da primeira faixa, nada", "% da meta → paga (%)")}
    ${editorFaixas("bonus", "Bônus de superação", "só com o faturamento acima de 100% da meta; sobre o valor depois da trava", "% da meta → + (%)")}
    ${editorDevolucao()}
    <h3 class="pr-config-tit">Motivos do vencido <small class="fraco">devoluções (não canceladas) e brindes com estes motivos entram no desconto</small></h3>
    <div class="pr-config-motivos">
      ${dados.motivos.map((m) => `<label><input type="checkbox" data-motivo="${m.id}"${s.motivos_vencido.includes(m.id) ? " checked" : ""}>${m.id} · ${esc(m.nome)}</label>`).join("")}
    </div>
    <h3 class="pr-config-tit">Produtos fora do mix <small class="fraco">a mussarela: o mix é o faturamento líquido sem eles</small></h3>
    <div class="pr-config-lista">
      ${s.produtos_fora_mix.map((p) => `<span class="chip">${p} · ${esc(nomesProd[p] || "produto")}<button type="button" data-tirar-prod="${p}" title="Tirar" aria-label="Tirar o produto ${p}">${icone("x")}</button></span>`).join("") || `<span class="fraco">Nenhum (o mix fica 100%).</span>`}
    </div>
    <div class="barra-ferramentas">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cp-prod" list="cp-prod-lista" placeholder="Código ou nome do produto"></label>
      <datalist id="cp-prod-lista">${dados.produtos.map((p) => `<option value="${p.id} · ${esc(p.nome)}"></option>`).join("")}</datalist>
      <button class="btn" type="button" id="cp-prod-mais">${icone("mais")}Acrescentar</button>
    </div>
    <h3 class="pr-config-tit">Dias</h3>
    <div class="sug-regras">
      <label class="sug-campo"><span class="r"><b>Reativação</b><small>Dias sem comprar, da compra anterior até a do mês, para contar como reativação</small></span>
        <span class="campo sem-seta"><input type="number" min="1" max="730" step="1" inputmode="numeric" data-dias="dias_sem_compra" value="${s.dias_sem_compra}"></span><em>dias</em></label>
      <label class="sug-campo"><span class="r"><b>Inadimplência</b><small>Vencido há pelo menos estes dias, na data dos dados</small></span>
        <span class="campo sem-seta"><input type="number" min="0" max="365" step="1" inputmode="numeric" data-dias="dias_inadimplencia" value="${s.dias_inadimplencia}"></span><em>dias</em></label>
    </div>
    ${rodapePadrao()}
  </section>`;
  alvo.querySelectorAll("[data-escala]").forEach((box) => {
    const lista = () => rasc.supervisores[box.dataset.escala];
    box.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.i == null) return;
      lista()[Number(t.dataset.i)][t.dataset.k] = numero(t) / 100;
      atualizarBarra();
    });
    box.addEventListener("click", (e) => {
      const tirar = e.target.closest("[data-tirar-faixa]");
      if (tirar) { lista().splice(Number(tirar.dataset.tirarFaixa), 1); renderSecao(); return; }
      if (!e.target.closest("[data-mais-faixa]")) return;
      const l = lista(), u = l[l.length - 1];
      l.push({ min: u ? Math.round((u.min + 0.1) * 1000) / 1000 : 1, pct: u ? u.pct : 1 });
      renderSecao();
    });
  });
  const dev = alvo.querySelector("[data-devolucao]");
  dev.addEventListener("input", (e) => {
    const t = e.target, d = rasc.supervisores.devolucao;
    if (t.dataset.k === "acima") d.acima = numero(t) / 100;
    else if (t.dataset.i != null) d.faixas[Number(t.dataset.i)][t.dataset.k] = numero(t) / 100;
    atualizarBarra();
  });
  dev.addEventListener("click", (e) => {
    const d = rasc.supervisores.devolucao;
    const tirar = e.target.closest("[data-tirar-faixa]");
    if (tirar) { d.faixas.splice(Number(tirar.dataset.tirarFaixa), 1); renderSecao(); return; }
    if (!e.target.closest("[data-mais-faixa]")) return;
    const u = d.faixas[d.faixas.length - 1];
    d.faixas.push({ ate: u ? Math.round((u.ate + 0.005) * 100000) / 100000 : 0.005, pct: u ? u.pct : 1 });
    renderSecao();
  });
  alvo.querySelectorAll("[data-motivo]").forEach((c) => c.addEventListener("change", () => {
    const id = Number(c.dataset.motivo);
    s.motivos_vencido = c.checked ? [...new Set([...s.motivos_vencido, id])].sort((a, b) => a - b)
      : s.motivos_vencido.filter((m) => m !== id);
    atualizarBarra();
  }));
  alvo.querySelectorAll("[data-tirar-prod]").forEach((b) => b.addEventListener("click", () => {
    s.produtos_fora_mix = s.produtos_fora_mix.filter((p) => p !== Number(b.dataset.tirarProd));
    renderSecao();
  }));
  const acrescentar = () => {
    const inp = alvo.querySelector("#cp-prod");
    const id = parseInt(inp.value, 10);
    if (!Number.isInteger(id) || id <= 0) { toast("Digite o código do produto (ou escolha na lista)", "erro"); return; }
    if (!s.produtos_fora_mix.includes(id)) s.produtos_fora_mix = [...s.produtos_fora_mix, id].sort((a, b) => a - b);
    renderSecao();
  };
  alvo.querySelector("#cp-prod-mais").addEventListener("click", acrescentar);
  alvo.querySelector("#cp-prod").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); acrescentar(); } });
  alvo.querySelectorAll("[data-dias]").forEach((inp) => inp.addEventListener("input", () => {
    s[inp.dataset.dias] = numero(inp);
    atualizarBarra();
  }));
  ligarPadrao(alvo);
}

// ======================================================================================
// Comissão: os brindes que descontam
// ======================================================================================
function secaoComissao(alvo) {
  const c = rasc.comissao;
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("moeda")}Comissão dos vendedores</h2>
      <p class="sub">A comissão das vendas é a que o ERP gravou em cada venda (o % do vendedor para o produto no dia da
        venda). Dela saem todas as devoluções do mês e os brindes dos motivos marcados abaixo, × o % de hoje da tabela do
        ERP. Os % de cada vendedor e produto ficam no ERP: para mudar um %, mude lá. Entram só as equipes BA e ES.</p></div></div>
    <h3 class="pr-config-tit">Brindes que descontam da comissão <small class="fraco">padrão: danificado (10, 11 e 12) e vencido (16); as devoluções descontam todas</small></h3>
    <div class="pr-config-motivos">
      ${dados.motivos.map((m) => `<label><input type="checkbox" data-motivo-com="${m.id}"${c.motivos_brindes.includes(m.id) ? " checked" : ""}>${m.id} · ${esc(m.nome)}</label>`).join("")}
    </div>
    ${rodapePadrao()}
  </section>`;
  alvo.querySelectorAll("[data-motivo-com]").forEach((cx) => cx.addEventListener("change", () => {
    const id = Number(cx.dataset.motivoCom);
    c.motivos_brindes = cx.checked ? [...new Set([...c.motivos_brindes, id])].sort((a, b) => a - b)
      : c.motivos_brindes.filter((m) => m !== id);
    atualizarBarra();
  }));
  ligarPadrao(alvo);
}

// ======================================================================================
// Metas dos supervisores num mês
// ======================================================================================
const METAS = [["fat", "Faturamento", fmt.moeda, 1000], ["cli", "Clientes (positivação)", fmt.num, 1],
  ["novos", "Clientes novos", fmt.num, 1], ["reativacao", "Reativações", fmt.num, 1]];

function secaoMetas(alvo) {
  const mes = dados.mes.valor;
  const metasMes = rasc.supervisores.metas_mes;
  const aj = metasMes[mes] || {};
  const outros = Object.keys(metasMes).filter((m) => m !== mes).sort().reverse();
  const linha = (s, [k, rotulo, formato, passo]) => {
    const auto = k === "fat" || k === "cli" ? (dados.automatico[s.id] || {})[k] : s.metas_padrao[k];
    const v = (aj[s.id] || {})[k];
    return `<tr class="${v != null ? "mudou" : ""}"><td class="nome-v">${rotulo}</td>
      <td>${auto == null ? `<span class="fraco">sem meta</span>` : formato(auto)}</td>
      <td><span class="sug-num${v != null ? " ajustado" : ""}">
        <input type="number" min="0" step="${passo}" inputmode="decimal" data-aj="${s.id}" data-k="${k}" value="${v ?? ""}" placeholder="${auto ?? ""}" aria-label="${esc(`${rotulo} · ${s.nome}`)}">
        ${v != null ? `<button type="button" class="sug-limpar" data-limpar="${s.id}" data-k="${k}" title="Voltar à meta automática" aria-label="Voltar à meta automática">${icone("x")}</button>` : ""}
      </span></td></tr>`;
  };
  const usa = (s, k) => k === "fat" || k === "cli" || (s.pesos[k] || 0) > 0;
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("alvo")}Metas dos supervisores</h2>
      <p class="sub">Faturamento e clientes (positivação): a soma das metas dos vendedores do estado no mês (planilha de
        metas ou aprovada no painel; o Edir fica fora do BA). Clientes novos e reativações: as metas de todo mês, em
        Supervisores. Digite outro número para trocar a meta daquele mês (0 = sem meta) e apague para voltar.</p></div>
      <label class="campo" title="Mês"><span class="ic-campo">${icone("calendario")}</span>
        <select id="cp-mes">${dados.meses.map((m) => `<option value="${m.valor}"${m.valor === mes ? " selected" : ""}>${esc(m.rotulo)}</option>`).join("")}</select></label>
    </div>
    <div class="tabela-rolagem pr-metas-rolagem"><table class="dados sug-fat pr-metas">
      <thead><tr><th>Meta</th><th>Automática</th><th>Ajuste em ${esc(dados.mes.curto)}</th></tr></thead>
      <tbody>
        ${rasc.supervisores.lista.map((s) => `<tr class="pr-metas-sup"><td colspan="3"><span class="pr-estado">${esc(s.estado)}</span> ${esc(s.nome)}</td></tr>
          ${METAS.filter(([k]) => usa(s, k)).map((m) => linha(s, m)).join("")}`).join("")}
      </tbody>
    </table></div>
    ${outros.length ? `<p class="sub">Outros meses com meta trocada: ${outros.map((m) => `<b>${esc(m)}</b>`).join(", ")}.</p>` : ""}
    <p class="form-erro" id="cp-erro" hidden></p>
  </section>`;
  alvo.querySelector("#cp-mes").addEventListener("change", async (e) => {
    try {
      const r = await api(`/api/premiacoes/config?mes=${e.target.value}`);
      dados = { ...dados, mes: r.mes, automatico: r.automatico }; // o rascunho continua
      renderSecao();
    } catch (err) { toast(err.message, "erro"); }
  });
  const corpo = alvo.querySelector("tbody");
  corpo.addEventListener("change", (ev) => {
    const t = ev.target;
    if (!t.dataset.aj) return;
    const id = t.dataset.aj, k = t.dataset.k;
    if (t.value.trim() === "") {
      if (metasMes[mes] && metasMes[mes][id]) delete metasMes[mes][id][k];
    } else {
      metasMes[mes] = metasMes[mes] || {};
      metasMes[mes][id] = metasMes[mes][id] || {};
      metasMes[mes][id][k] = Number(t.value);
    }
    limparVazios(mes);
    renderSecao();
  });
  corpo.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-limpar]");
    if (!b) return;
    if (metasMes[mes] && metasMes[mes][b.dataset.limpar]) delete metasMes[mes][b.dataset.limpar][b.dataset.k];
    limparVazios(mes);
    renderSecao();
  });
}

function limparVazios(mes) {
  const metasMes = rasc.supervisores.metas_mes;
  if (!metasMes[mes]) return;
  for (const id of Object.keys(metasMes[mes])) if (!Object.keys(metasMes[mes][id]).length) delete metasMes[mes][id];
  if (!Object.keys(metasMes[mes]).length) delete metasMes[mes];
}

// ======================================================================================
// Acesso por usuário: as abas e os quadros de supervisor de cada visualizador (os vendedores dele ficam em Usuários)
// ======================================================================================
const tituloAba = (id) => ABAS.find(([a]) => a === id)?.[2] || id;
const nomeVendedor = (id) => nomesAcesso[id] || `Vendedor ${id}`;
const emLista = (itens) => (itens.length <= 1 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`);

// Os estados cuja carteira inteira a pessoa vê pelos vendedores do acesso (o quadro de um supervisor soma o estado
// inteiro, como o servidor confere): null = os dois; vazio = nenhum (só alguns vendedores, ou ainda sem escolha).
function estadosDoAcesso(u) {
  const e = u.escopo;
  if (!e || e.modo === "alguns") return new Set();
  if (e.modo === "todos") return null;
  return new Set(e.equipes);
}

const quadroFora = (u, s) => { const est = estadosDoAcesso(u); return est !== null && !est.has(s.estado); };
const quadrosVistos = (u) => rasc.supervisores.lista.filter((s) => acessos[u.login].supervisores.includes(s.id) && !quadroFora(u, s));
// As abas marcadas que aparecem para a pessoa: a dos supervisores, só com algum quadro que ela possa ver.
const abasVistas = (u) => acessos[u.login].abas.filter((id) => id !== "supervisores" || quadrosVistos(u).length);

// Os vendedores do acesso, como estão na tela Usuários (aqui só para ler).
function textoVendedores(u) {
  const e = u.escopo;
  if (!e) return "ainda nenhum vendedor escolhido";
  if (e.modo === "todos") return "todos os vendedores";
  if (e.modo === "equipes") return `os vendedores ${e.equipes.length === 1 ? "da equipe" : "das equipes"} ${emLista(e.equipes.map((q) => NOME_EQUIPE[q] || q))}`;
  const n = e.vendedores.length;
  return n <= 3 ? `só ${emLista(e.vendedores.map(nomeVendedor))}` : `só ${n} vendedores escolhidos`;
}

function resumoCurtoAcesso(u) {
  const a = acessos[u.login];
  if (!a.ve) return "não vê a página";
  if (!a.abas.length) return "sem abas";
  return `${a.abas.length} aba${a.abas.length === 1 ? "" : "s"}`;
}

// O que falta para salvar o acesso (null = pode salvar). O servidor confere de novo.
function erroAcesso(u) {
  const a = acessos[u.login];
  if (!a.ve) return (u.paginas || []).some((p) => p !== "premiacoes") ? null : "é a única página desta pessoa; libere outra em Usuários antes de tirar esta";
  if (!a.abas.length) return "marque ao menos uma aba, ou desligue a página";
  if (a.abas.includes("supervisores") && !a.supervisores.length) return "marque ao menos um supervisor, ou tire a aba Supervisores";
  return null;
}

function erroUsuario(u, msg) {
  secao = "usuarios";
  usuarioSel = u.login;
  render();
  const el = raiz.querySelector("#cp-u-erro");
  el.textContent = `${u.nome}: ${msg}.`;
  el.hidden = false;
  toast(`${u.nome}: ${msg}`, "erro");
}

function secaoUsuarios(alvo) {
  if (!usuarios.length) {
    alvo.innerHTML = `<section class="cartao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div><h3>Ainda não há visualizadores</h3>
      <p>Cadastre as pessoas em <b>Usuários</b>; depois, aqui você escolhe as abas das Premiações de cada uma.</p>
      <a class="btn primario" href="#/usuarios">${icone("escudo")}Abrir Usuários</a></section>`;
    return;
  }
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios">
    <aside class="cartao usu-lista entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("escudo")}Visualizadores</h2>
        <p class="sub">Quem vê a página, quais abas e quais quadros de supervisor</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="cp-busca-u" type="search" placeholder="Buscar pessoa" value="${esc(buscaUsuario)}"></label>
      <div class="usu-itens" id="cp-u-itens"></div>
      <div class="dica">${icone("info")}<span>Nome, senha, páginas e os vendedores que cada pessoa vê (em todas as páginas)
        ficam em <a href="#/usuarios">Usuários</a>. Administradores veem tudo.</span></div>
    </aside>
    <div id="cp-u-editor"></div>
  </div>`;
  alvo.querySelector("#cp-busca-u").addEventListener("input", (e) => { buscaUsuario = e.target.value; desenharItensUsuarios(); });
  desenharItensUsuarios();
  desenharEditorUsuario();
}

function desenharItensUsuarios() {
  const termo = buscaUsuario.trim().toLowerCase();
  const el = raiz.querySelector("#cp-u-itens");
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
    desenharItensUsuarios();
    desenharEditorUsuario();
  }));
}

function desenharEditorUsuario() {
  const alvo = raiz.querySelector("#cp-u-editor");
  const u = usuarios.find((x) => x.login === usuarioSel);
  if (!u) { alvo.innerHTML = ""; return; }
  const a = acessos[u.login];
  const outras = (u.paginas || []).filter((p) => p !== "premiacoes");
  alvo.innerHTML = `
  <section class="cartao usu-editor entra" style="--i:2">
    <div class="cartao-cab"><div>
      <h2>${icone("trofeu")}Premiações de ${esc(u.nome)}</h2>
      <p class="sub">${esc(u.login)}${u.ativo ? "" : " · acesso desativado em Usuários"}</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${a.ve ? "ligada" : ""}" id="cp-u-ve" type="button" role="switch" aria-checked="${a.ve}" aria-label="Vê a página Premiações"></button>
      <div><b>Vê a página Premiações</b><p>${a.ve ? "A página aparece na barra lateral desta pessoa." : "Desligado, a página some da barra lateral e o servidor não manda os números."}
        ${!outras.length && a.ve ? " É a única página dela: para tirar, libere outra antes em Usuários." : ""}</p></div>
    </div>
    <div id="cp-u-permissoes" ${a.ve ? "" : "hidden"}></div>
    <div class="usu-resumo" id="cp-u-resumo"></div>
    <p class="form-erro" id="cp-u-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#cp-u-ve").addEventListener("click", () => {
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
  const alvo = raiz.querySelector("#cp-u-permissoes");
  const lista = rasc.supervisores.lista;
  const nenhumEstado = lista.every((s) => quadroFora(u, s));
  const opcao = (dado, id, on, ic, titulo, sub, aviso) => `<button type="button" class="visao-op ${on ? "ativo" : ""}" data-${dado}="${id}" aria-pressed="${on}">
      <span class="marca-caixa">${icone("visto")}</span>${icone(ic)}
      <span><b>${esc(titulo)}</b><small>${esc(sub)}</small>${aviso ? `<small class="aviso-nota">${esc(aviso)}</small>` : ""}</span>
    </button>`;
  alvo.innerHTML = `
    <h3 class="usu-titulo">Abas que pode ver</h3>
    <div class="visoes-escolha">
      ${ABAS.map(([id, ic, titulo, sub]) => opcao("aba", id, a.abas.includes(id), ic, titulo, sub,
        id === "supervisores" && nenhumEstado ? "os vendedores do acesso desta pessoa não incluem um estado inteiro: a aba não aparece para ela" : "")).join("")}
    </div>
    ${a.abas.includes("supervisores") ? `
    <h3 class="usu-titulo">Quadros dos supervisores que pode ver</h3>
    <div class="visoes-escolha">
      ${lista.map((s) => opcao("sup", s.id, a.supervisores.includes(s.id), "pessoas", s.nome, `supervisor do ${s.estado}`,
        quadroFora(u, s) && !nenhumEstado ? `fora do acesso desta pessoa (precisa ver todos os vendedores do ${s.estado}): o quadro não aparece` : "")).join("")}
    </div>` : ""}
    <p class="usu-nota ${u.escopo ? "" : "aviso-nota"}">${icone(u.escopo ? "pessoas" : "alerta")}<span>Dentro das abas, ${esc(u.nome)} vê
      <b>${esc(textoVendedores(u))}</b>, como está em <a href="#/usuarios">Usuários</a> (vale para todas as páginas).</span></p>`;
  const alternar = (lista_, id, ordem) => {
    const marcados = new Set(lista_);
    marcados.has(id) ? marcados.delete(id) : marcados.add(id);
    return ordem.filter((x) => marcados.has(x));
  };
  alvo.querySelectorAll("[data-aba]").forEach((b) => b.addEventListener("click", () => {
    a.abas = alternar(a.abas, b.dataset.aba, ABAS.map(([id]) => id));
    // Ao ligar a aba dos supervisores pela primeira vez, já vêm marcados os quadros que a pessoa pode ver.
    if (b.dataset.aba === "supervisores" && a.abas.includes("supervisores") && !a.supervisores.length) {
      a.supervisores = lista.filter((s) => !quadroFora(u, s)).map((s) => s.id);
    }
    desenharPermissoesUsuario(u);
    atualizarResumoUsuario(u);
    aoMudarAcesso();
  }));
  alvo.querySelectorAll("[data-sup]").forEach((b) => b.addEventListener("click", () => {
    a.supervisores = alternar(a.supervisores, b.dataset.sup, lista.map((s) => s.id));
    b.classList.toggle("ativo", a.supervisores.includes(b.dataset.sup));
    b.setAttribute("aria-pressed", a.supervisores.includes(b.dataset.sup));
    atualizarResumoUsuario(u);
    aoMudarAcesso();
  }));
}

function atualizarResumoUsuario(u) {
  const el = raiz.querySelector("#cp-u-resumo");
  if (!el) return;
  const a = acessos[u.login];
  const quem = `<b>${esc(u.nome)}</b>`;
  let txt;
  if (!a.ve) txt = `${quem} não vê a página Premiações.`;
  else if (!a.abas.length) txt = "Marque ao menos uma aba para esta pessoa: sem abas, a página fica vazia para ela.";
  else if (a.abas.includes("supervisores") && !a.supervisores.length) txt = "Marque ao menos um supervisor, ou tire a aba Supervisores.";
  else {
    const vistas = abasVistas(u), quadros = quadrosVistos(u);
    const abas = emLista(vistas.map((id) => `<b>${esc(tituloAba(id))}</b>`));
    const sups = vistas.includes("supervisores") ? `, com ${quadros.length === 1 ? "o quadro" : "os quadros"} de ${emLista(quadros.map((s) => `<b>${esc(s.nome)}</b>`))}` : "";
    txt = vistas.length
      ? `${quem} vê ${vistas.length === 1 ? "a aba" : "as abas"} ${abas}${sups}; dentro delas, ${esc(textoVendedores(u))}.`
      : `${quem} não veria nenhuma aba: os quadros marcados ficam fora dos vendedores do acesso dela.`;
  }
  el.innerHTML = `${icone("olho")}<span>${txt}</span>`;
}

// ---------- gravação ----------
function erro(msg) {
  const el = raiz.querySelector("#cp-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

async function salvar() {
  const regras = contarAlteracoesRegras() > 0;
  const mudados = usuariosMudados();
  const errado = regras && rasc.supervisores.lista.find((s) => Math.abs(somaPesos(s) - 1) > 1e-6);
  if (errado) {
    if (secao !== "supervisores") { secao = "supervisores"; render(); }
    return erro(`Os pesos de ${errado.nome || "um supervisor"} somam ${fmt.num(somaPesos(errado) * 100, 2)}%: precisam dar 100%.`);
  }
  for (const u of mudados) {
    const msg = erroAcesso(u);
    if (msg) return erroUsuario(u, msg);
  }
  // Só vai o que mudou: sem regras novas, o servidor não grava outra versão delas.
  const corpo = { mes: dados.mes.valor };
  if (regras) corpo.config = rasc;
  if (mudados.length) corpo.usuarios = Object.fromEntries(mudados.map((u) => [u.login, acessos[u.login]]));
  const btn = raiz.querySelector("#cp-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/premiacoes/config", { json: corpo }));
    toast(regras && mudados.length ? "Regras e acessos das premiações salvos"
      : regras ? "Regras das premiações salvas" : "Acesso às premiações salvo");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    if (secao === "usuarios") {
      const el = raiz.querySelector("#cp-u-erro");
      if (el) { el.textContent = e.message; el.hidden = false; }
      toast(e.message, "erro");
    } else erro(e.message);
  } finally {
    btn.disabled = false;
  }
}
