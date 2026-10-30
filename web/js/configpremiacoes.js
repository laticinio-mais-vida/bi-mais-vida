// Configuração da página Premiações (só administradores): as faixas dos vendedores; o prêmio máximo, os nomes, os pesos,
// os mínimos e as metas dos supervisores, os produtos fora do mix e os motivos das devoluções impróprias; e a meta de
// faturamento e de clientes de um supervisor num mês, no lugar da soma das metas dos vendedores; e os motivos dos brindes
// que descontam da comissão. Quem vê a página e quais vendedores segue o acesso de Metas. Tudo vale depois de Salvar,
// para todos os meses.
import { api, esc, fmt, icone, toast } from "./util.js";

const INDICADORES = [
  ["receita", "Faturamento líquido", "Vendas − devoluções − brindes, sobre a meta (soma das metas dos vendedores)"],
  ["mix", "Mix", "Líquido sem os produtos fora do mix (a mussarela) ÷ líquido"],
  ["inadimplencia", "Inadimplência", "Em aberto e vencido ÷ faturamento líquido de 7 a 2 meses antes"],
  ["positivacao", "Positivação", "Clientes da carteira com venda no mês, sobre a meta (soma das metas dos vendedores)"],
  ["devolucoes", "Devoluções impróprias", "Devoluções e brindes de motivo impróprio ÷ faturamento bruto"],
];
const ESTADOS = ["BA", "ES"];

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/premiacoes/config
let orig = null, rasc = null;
let secao = "vendedores";

const clone = (o) => JSON.parse(JSON.stringify(o));

export function configPremiacoesTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigPremiacoes(container, contexto) {
  ctx = contexto;
  raiz = container;
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    const mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : "";
    if (["vendedores", "supervisores", "metas", "comissao"].includes(q.get("secao"))) secao = q.get("secao");
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
}

// ---------- apoio ----------
const pct = (v, casas = 2) => (v == null || isNaN(v) ? "" : String(Math.round(v * 100 * 10 ** casas) / 10 ** casas));

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

function contarAlteracoes() {
  const a = folhas(rasc), b = folhas(orig);
  let n = 0;
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) if (!Object.is(a[k], b[k])) n++;
  return n;
}

function somaPesos() {
  return INDICADORES.reduce((s, [k]) => s + (Number(rasc.supervisores[k].peso) || 0), 0);
}

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${[["vendedores", "usuario", "Vendedores"], ["supervisores", "pessoas", "Supervisores"], ["metas", "alvo", "Metas dos supervisores"],
        ["comissao", "moeda", "Comissão"]]
        .map(([id, ic, nome]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}</button>`).join("")}
      <div class="dica">${icone("info")} As regras valem para todos os meses assim que você salvar: mudar uma faixa ou um
        peso recalcula também os meses que já passaram. Quem vê a página e quais vendedores segue o acesso de Metas.</div>
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
  if (secao === "supervisores") secaoSupervisores(alvo);
  else if (secao === "metas") secaoMetas(alvo);
  else if (secao === "comissao") secaoComissao(alvo);
  else secaoVendedores(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cp-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cp-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
}

function rodapePadrao(rotulo = "Restaurar padrão do Power BI") {
  return `<p class="form-erro" id="cp-erro" hidden></p>
    <div class="sug-regras-acoes"><button class="btn" type="button" id="cp-padrao">${icone("restaurar")}${rotulo}</button></div>`;
}

function ligarPadrao(alvo) {
  alvo.querySelector("#cp-padrao").addEventListener("click", () => {
    const ajustes = rasc.supervisores.ajustes;
    rasc = clone(dados.padrao);
    rasc.supervisores.ajustes = ajustes; // os ajustes das metas de cada mês ficam
    toast("Padrão aplicado (faixas, pesos, metas, produtos, motivos e brindes da comissão); confira e salve");
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
// Supervisores: prêmio, nomes, indicadores, produtos e motivos
// ======================================================================================
function campoInd(k, campo, rotulo, valor, sufixo = "%", passo = "0.5") {
  return `<label><span>${rotulo}</span>
    <span class="campo sem-seta"><input type="number" min="0" step="${passo}" inputmode="decimal" data-ind="${k}" data-campo="${campo}" value="${valor}"></span>
    <em>${sufixo}</em></label>`;
}

function secaoSupervisores(alvo) {
  const s = rasc.supervisores;
  const soma = somaPesos();
  const nomesProd = Object.fromEntries(dados.produtos.map((p) => [p.id, p.nome]));
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("pessoas")}Supervisores</h2>
      <p class="sub">Prêmio = soma dos pontos dos cinco indicadores × o prêmio máximo. Faturamento, mix e positivação dão o peso
        × o alcance a partir do mínimo (no máximo o peso); inadimplência e devoluções dão o peso inteiro dentro da meta.</p></div></div>
    <div class="sug-regras">
      <label class="sug-campo"><span class="r"><b>Prêmio máximo</b><small>O que o supervisor recebe com 100% dos pontos</small></span>
        <span class="campo sem-seta"><input type="number" min="0" step="100" inputmode="decimal" id="cp-maximo" value="${s.maximo}"></span><em>R$</em></label>
      ${ESTADOS.map((e) => `<label class="sug-campo"><span class="r"><b>Supervisor do ${e}</b><small>O nome que aparece no quadro</small></span>
        <span class="campo sem-seta"><input type="text" maxlength="60" data-nome="${e}" value="${esc(s.nomes[e])}" style="text-align:left"></span><em></em></label>`).join("")}
    </div>
    <h3 class="pr-config-tit">Indicadores <small class="${Math.abs(soma - 1) > 1e-6 ? "form-erro" : "fraco"}">soma dos pesos: ${fmt.num(soma * 100, 2)}%${Math.abs(soma - 1) > 1e-6 ? " (precisa dar 100%)" : ""}</small></h3>
    <div class="pr-config-grade">
      ${INDICADORES.map(([k, titulo, dica]) => {
        const ind = s[k];
        return `<div class="pr-config-ind"><h4>${esc(titulo)}</h4><small class="fraco">${esc(dica)}</small>
          ${campoInd(k, "peso", "Peso", pct(ind.peso))}
          ${"minimo" in ind ? campoInd(k, "minimo", "Mínimo de alcance", pct(ind.minimo)) : ""}
          ${"meta" in ind ? ESTADOS.map((e) => campoInd(k, `meta.${e}`, `Meta do ${e}`, pct(ind.meta[e], 4), "%", "0.01")).join("") : ""}
          ${"dias" in ind ? campoInd(k, "dias", "Vencido há pelo menos", ind.dias, "dias", "1") : ""}
        </div>`;
      }).join("")}
    </div>
    <h3 class="pr-config-tit">Produtos fora do mix <small class="fraco">o mix é o faturamento líquido sem eles</small></h3>
    <div class="pr-config-lista">
      ${s.produtos_fora_mix.map((p) => `<span class="chip">${p} · ${esc(nomesProd[p] || "produto")}<button type="button" data-tirar-prod="${p}" title="Tirar" aria-label="Tirar o produto ${p}">${icone("x")}</button></span>`).join("") || `<span class="fraco">Nenhum (o mix fica 100%).</span>`}
    </div>
    <div class="barra-ferramentas">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cp-prod" list="cp-prod-lista" placeholder="Código ou nome do produto"></label>
      <datalist id="cp-prod-lista">${dados.produtos.map((p) => `<option value="${p.id} · ${esc(p.nome)}"></option>`).join("")}</datalist>
      <button class="btn" type="button" id="cp-prod-mais">${icone("mais")}Acrescentar</button>
    </div>
    <h3 class="pr-config-tit">Motivos das devoluções impróprias <small class="fraco">devoluções e brindes com estes motivos contam no indicador</small></h3>
    <div class="pr-config-motivos">
      ${dados.motivos.map((m) => `<label><input type="checkbox" data-motivo="${m.id}"${s.motivos_improprios.includes(m.id) ? " checked" : ""}>${m.id} · ${esc(m.nome)}</label>`).join("")}
    </div>
    ${rodapePadrao()}
  </section>`;
  alvo.querySelector("#cp-maximo").addEventListener("input", (e) => {
    s.maximo = e.target.value.trim() === "" ? NaN : Number(e.target.value);
    atualizarBarra();
  });
  alvo.querySelectorAll("[data-nome]").forEach((inp) => inp.addEventListener("input", () => { s.nomes[inp.dataset.nome] = inp.value; atualizarBarra(); }));
  alvo.querySelectorAll("[data-ind]").forEach((inp) => inp.addEventListener("change", () => {
    const ind = s[inp.dataset.ind];
    const v = inp.value.trim() === "" ? NaN : Number(inp.value);
    const [campo, e] = inp.dataset.campo.split(".");
    if (campo === "dias") ind.dias = v;
    else if (e) ind.meta[e] = v / 100;
    else ind[campo] = v / 100;
    renderSecao(); // a soma dos pesos
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
  alvo.querySelectorAll("[data-motivo]").forEach((c) => c.addEventListener("change", () => {
    const id = Number(c.dataset.motivo);
    s.motivos_improprios = c.checked ? [...new Set([...s.motivos_improprios, id])].sort((a, b) => a - b)
      : s.motivos_improprios.filter((m) => m !== id);
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
    ${rodapePadrao("Restaurar padrão")}
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
function secaoMetas(alvo) {
  const mes = dados.mes.valor;
  const aj = rasc.supervisores.ajustes[mes] || {};
  const outros = Object.keys(rasc.supervisores.ajustes).filter((m) => m !== mes).sort().reverse();
  const linha = (e, k, rotulo, formato) => {
    const auto = dados.automatico[e][k];
    const v = (aj[e] || {})[k];
    return `<tr class="${v != null ? "mudou" : ""}"><td class="nome-v">${rotulo}</td>
      <td>${formato(auto)}</td>
      <td><span class="sug-num${v != null ? " ajustado" : ""}">
        <input type="number" min="0" step="${k === "cli" ? 1 : 1000}" inputmode="decimal" data-aj="${e}" data-k="${k}" value="${v ?? ""}" placeholder="${auto}" aria-label="${rotulo}">
        ${v != null ? `<button type="button" class="sug-limpar" data-limpar="${e}" data-k="${k}" title="Voltar à soma automática" aria-label="Voltar à soma automática">${icone("x")}</button>` : ""}
      </span></td></tr>`;
  };
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("alvo")}Metas dos supervisores</h2>
      <p class="sub">A meta de faturamento e a de positivação de cada supervisor são a soma das metas dos vendedores do estado
        no mês (planilha de metas ou aprovada no painel; o Edir fica fora do BA). Digite outro número para trocar a meta
        daquele mês, e apague para voltar à soma.</p></div>
      <label class="campo" title="Mês"><span class="ic-campo">${icone("calendario")}</span>
        <select id="cp-mes">${dados.meses.map((m) => `<option value="${m.valor}"${m.valor === mes ? " selected" : ""}>${esc(m.rotulo)}</option>`).join("")}</select></label>
    </div>
    <div class="tabela-rolagem"><table class="dados sug-fat pr-metas">
      <thead><tr><th>Meta</th><th>Soma dos vendedores</th><th>Ajuste em ${esc(dados.mes.curto)}</th></tr></thead>
      <tbody>
        ${ESTADOS.map((e) => linha(e, "fat", `Faturamento · ${e} (${esc(rasc.supervisores.nomes[e] || "")})`, fmt.moeda)
          + linha(e, "cli", `Clientes · ${e} (${esc(rasc.supervisores.nomes[e] || "")})`, fmt.num)).join("")}
      </tbody>
    </table></div>
    ${outros.length ? `<p class="sub">Outros meses com meta ajustada: ${outros.map((m) => `<b>${esc(m)}</b>`).join(", ")}.</p>` : ""}
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
    const e = t.dataset.aj, k = t.dataset.k;
    const ajustes = rasc.supervisores.ajustes;
    if (t.value.trim() === "") {
      if (ajustes[mes] && ajustes[mes][e]) delete ajustes[mes][e][k];
    } else {
      ajustes[mes] = ajustes[mes] || {};
      ajustes[mes][e] = ajustes[mes][e] || {};
      ajustes[mes][e][k] = Number(t.value);
    }
    limparVazios(mes);
    renderSecao();
  });
  corpo.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-limpar]");
    if (!b) return;
    const ajustes = rasc.supervisores.ajustes;
    if (ajustes[mes] && ajustes[mes][b.dataset.limpar]) delete ajustes[mes][b.dataset.limpar][b.dataset.k];
    limparVazios(mes);
    renderSecao();
  });
}

function limparVazios(mes) {
  const ajustes = rasc.supervisores.ajustes;
  if (!ajustes[mes]) return;
  for (const e of Object.keys(ajustes[mes])) if (!Object.keys(ajustes[mes][e]).length) delete ajustes[mes][e];
  if (!Object.keys(ajustes[mes]).length) delete ajustes[mes];
}

// ---------- gravação ----------
function erro(msg) {
  const el = raiz.querySelector("#cp-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

async function salvar() {
  if (Math.abs(somaPesos() - 1) > 1e-6) {
    if (secao !== "supervisores") { secao = "supervisores"; render(); }
    return erro(`Os pesos dos indicadores somam ${fmt.num(somaPesos() * 100, 2)}%: precisam dar 100%.`);
  }
  const btn = raiz.querySelector("#cp-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/premiacoes/config", { json: { config: rasc, mes: dados.mes.valor } }));
    toast("Regras das premiações salvas");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    erro(e.message);
  } finally {
    btn.disabled = false;
  }
}
