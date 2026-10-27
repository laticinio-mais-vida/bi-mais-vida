// Configuração da página Sugestão de Metas (só administradores): o crescimento desejado no ano por estado, os tetos da
// sazonalidade e do crescimento proposto, os faturamentos das áreas do BA (prazo entre o atendimento e o faturamento,
// número fixo para as quinzenais e ajustes à mão por área e mês) e a aprovação das metas, que passam a valer no painel
// de Metas. Quem vê a página e quais vendedores segue o acesso de Metas. Tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";

const DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
const NOMES_PAPEIS = { base: "mês base", meta: "mês da meta", base_ly: "base, ano passado", meta_ly: "meta, ano passado" };

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/sugestao/config
let orig = null, rasc = null;
let secao = "regras";
let busca = "";
// Aprovação de metas: a aba de um estado e mês (/api/sugestao/aprovacao) e o rascunho das linhas mexidas.
let aprov = null;
let aprovRasc = {};        // {id do vendedor: {aprovada, meta_fat, meta_mus, meta_cli}}
let aprovEstado = "BA", aprovMes = "";
let aberto = null;         // vendedor com os produtos abertos
let verOutros = false;

const clone = (o) => JSON.parse(JSON.stringify(o));

export function configSugestaoTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigSugestao(container, contexto) {
  ctx = contexto;
  raiz = container;
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    const mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : "";
    if (["regras", "faturamentos", "aprovacao"].includes(q.get("secao"))) secao = q.get("secao");
    if (["ES", "BA"].includes(q.get("e"))) aprovEstado = q.get("e");
    carregarDados(await api(`/api/sugestao/config${mes ? `?mes=${mes}` : ""}`));
    aprov = null;
    aprovMes = mes;
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
const pct = (v) => (v == null || isNaN(v) ? "" : String(Math.round(v * 1000) / 10).replace(".", ","));

const contarAlteracoes = () => contarRegras() + contarAprovacao();

function contarRegras() {
  let n = 0;
  for (const e of ["ES", "BA"]) if (rasc.crescimento[e] !== orig.crescimento[e]) n++;
  for (const k of ["teto_sazonalidade", "teto_crescimento"]) if (rasc[k] !== orig[k]) n++;
  for (const a of new Set([...Object.keys(rasc.fixos), ...Object.keys(orig.fixos)])) if (rasc.fixos[a] !== orig.fixos[a]) n++;
  for (const a of new Set([...Object.keys(rasc.prazos), ...Object.keys(orig.prazos)])) if (rasc.prazos[a] !== orig.prazos[a]) n++;
  const meses = new Set([...Object.keys(rasc.ajustes), ...Object.keys(orig.ajustes)]);
  for (const m of meses) {
    const a = rasc.ajustes[m] || {}, b = orig.ajustes[m] || {};
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) if (a[k] !== b[k]) n++;
  }
  return n;
}

function areaMudou(id) {
  const k = String(id);
  if (rasc.fixos[k] !== orig.fixos[k] || rasc.prazos[k] !== orig.prazos[k]) return true;
  return dados.meses.some(({ valor }) => (rasc.ajustes[valor] || {})[k] !== (orig.ajustes[valor] || {})[k]);
}

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${[["regras", "tendencia", "Regras da conta"], ["faturamentos", "calendario", "Faturamentos por área"],
        ["aprovacao", "certo", "Aprovação de metas"]]
        .map(([id, ic, nome]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}</button>`).join("")}
      <div class="dica">${icone("info")} As regras e os faturamentos valem só para a conta da sugestão, assim que você salvar.
        A meta aprovada vai para o painel de Metas no lugar da planilha. Quem vê a página e quais vendedores segue o acesso
        de Metas.</div>
    </aside>
    <div id="cs-secao"></div>
  </div>
  <div class="barra-salvar" id="cs-barra">
    <span id="cs-n">Alterações não salvas</span>
    <button class="btn" id="cs-descartar">Descartar</button>
    <button class="btn primario" id="cs-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => {
    secao = b.dataset.secao;
    raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x === b));
    renderSecao();
  }));
  raiz.querySelector("#cs-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cs-descartar").addEventListener("click", () => { rasc = clone(orig); aprovRasc = {}; render(); });
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cs-secao");
  if (secao === "faturamentos") secaoFaturamentos(alvo);
  else if (secao === "aprovacao") secaoAprovacao(alvo);
  else secaoRegras(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cs-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cs-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
}

// ======================================================================================
// Regras da conta
// ======================================================================================
function campoPct(chave, rotulo, valor, dica) {
  return `<label class="sug-campo">
    <span class="r"><b>${rotulo}</b><small>${dica}</small></span>
    <span class="campo sem-seta"><input type="number" min="0" max="100" step="0.5" inputmode="decimal" data-regra="${chave}" value="${pct(valor).replace(",", ".")}"></span>
    <em>%</em>
  </label>`;
}

function secaoRegras(alvo) {
  const p = dados.padrao;
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("tendencia")}Regras da conta</h2>
      <p class="sub">O padrão é o do Power BI: ${pct(p.crescimento.ES)}% de crescimento no ano e tetos de ${pct(p.teto_sazonalidade)}%.</p></div></div>
    <div class="sug-regras">
      ${campoPct("crescimento.ES", "Crescimento desejado no ano · ES", rasc.crescimento.ES, "O crescimento proposto completa o que falta para chegar nele")}
      ${campoPct("crescimento.BA", "Crescimento desejado no ano · BA", rasc.crescimento.BA, "O BA inclui o Edir")}
      ${campoPct("teto_sazonalidade", "Teto da sazonalidade", rasc.teto_sazonalidade, "Alta do ano passado acima disso fica no teto; queda reduz a meta")}
      ${campoPct("teto_crescimento", "Teto do crescimento proposto", rasc.teto_crescimento, "Quem caiu muito no ano recebe no máximo isso")}
    </div>
    <p class="form-erro" id="cs-erro" hidden></p>
    <div class="sug-regras-acoes"><button class="btn" type="button" id="cs-padrao">${icone("restaurar")}Restaurar padrão do Power BI</button></div>
  </section>`;
  alvo.querySelectorAll("[data-regra]").forEach((inp) => inp.addEventListener("input", () => {
    const v = inp.value.trim() === "" ? NaN : Number(inp.value) / 100;
    const [a, b] = inp.dataset.regra.split(".");
    if (b) rasc[a][b] = v; else rasc[a] = v;
    atualizarBarra();
  }));
  alvo.querySelector("#cs-padrao").addEventListener("click", () => {
    rasc.crescimento = clone(p.crescimento);
    rasc.teto_sazonalidade = p.teto_sazonalidade;
    rasc.teto_crescimento = p.teto_crescimento;
    rasc.fixos = clone(p.fixos);
    rasc.prazos = clone(p.prazos);
    toast("Padrão aplicado (também as áreas quinzenais e os prazos de faturamento); confira e salve");
    renderSecao();
  });
}

// ======================================================================================
// Faturamentos por área (BA)
// ======================================================================================
function secaoFaturamentos(alvo) {
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("calendario")}Faturamentos por área (BA)</h2>
      <p class="sub">Cada dia de atendimento da área é faturado no prazo dela, em dias úteis (1 = o dia útil seguinte: sexta e
        sábado → segunda; feriado empurra para o próximo). Confira o prazo com o dia em que a área fatura nas vendas. Em cinza,
        o número automático; digite outro para corrigir aquela área naquele mês, e apague para voltar ao automático. Área sem
        dia e sem número fixo fica fora da sugestão.</p></div>
      <label class="campo" title="Os quatro meses que a conta deste mês da meta usa"><span class="ic-campo">${icone("calendario")}</span>
        <select id="cs-mes">${dados.opcoes_meses.map((m) => `<option value="${m.valor}"${m.valor === dados.mes ? " selected" : ""}>Meta de ${esc(m.rotulo)}</option>`).join("")}</select></label>
    </div>
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="cs-busca" type="search" placeholder="Buscar área ou código" value="${esc(busca)}"></label>
      <a class="btn" href="#/config-gestao" title="Os dias de atendimento ficam na configuração da Gestão">${icone("ajustes")}Dias de atendimento (Gestão)</a>
    </div>
    <div class="tabela-rolagem"><table class="dados sug-fat">
      <thead><tr><th>Área</th><th>Atendimento</th><th title="Dias úteis entre o atendimento e o faturamento">Fatura depois de</th><th>Faturamentos</th>
        ${dados.meses.map((m, i) => `<th title="${esc(NOMES_PAPEIS[dados.papeis[i]])}">${esc(m.rotulo)}<small>${esc(NOMES_PAPEIS[dados.papeis[i]])}</small></th>`).join("")}</tr></thead>
      <tbody id="cs-areas"></tbody>
    </table></div>
  </section>`;
  alvo.querySelector("#cs-busca").addEventListener("input", (e) => { busca = e.target.value; desenharAreas(); });
  alvo.querySelector("#cs-mes").addEventListener("change", async (e) => {
    try {
      const r = await api(`/api/sugestao/config?mes=${e.target.value}`);
      dados = { ...r };  // o rascunho continua: muda só a contagem automática e os meses mostrados
      renderSecao();
    } catch (err) { toast(err.message, "erro"); }
  });
  const corpo = alvo.querySelector("#cs-areas");
  corpo.addEventListener("change", aoMudar);
  corpo.addEventListener("click", aoClicar);
  desenharAreas();
}

function descreverDias(dias) {
  if (dias == null) return `<span class="chip-papel inativo">Pendente</span>`;
  if (!dias.length) return `<span class="chip-papel inativo">Não atendida</span>`;
  return esc(dias.map((d) => DIAS[d - 1]).join(", "));
}

function desenharAreas() {
  const termo = busca.trim().toLowerCase();
  const lista = dados.areas.filter((a) => !termo || `${a.nome} ${a.id}`.toLowerCase().includes(termo));
  const corpo = raiz.querySelector("#cs-areas");
  if (!lista.length) {
    corpo.innerHTML = `<tr><td colspan="${4 + dados.meses.length}" class="fraco">Nenhuma área com esse filtro.</td></tr>`;
    return;
  }
  corpo.innerHTML = lista.map((a) => {
    const k = String(a.id);
    const fixo = rasc.fixos[k];
    const prazo = rasc.prazos[k] ?? 1;
    const semConta = fixo == null && !(a.dias && a.dias.length);
    const observado = (a.faturamento_observado || []).slice(0, 2).map((o) => `${o.dia} ${Math.round(o.pct * 100)}%`).join(" · ");
    const celulas = dados.meses.map(({ valor }) => {
      const ajuste = (rasc.ajustes[valor] || {})[k];
      const padrao = fixo != null ? fixo : a.automatico[String(prazo)][valor];
      return `<td><span class="sug-num${ajuste != null ? " ajustado" : ""}">
        <input type="number" min="0" max="31" step="1" inputmode="numeric" data-ajuste="${k}" data-mes="${valor}"
          value="${ajuste ?? ""}" placeholder="${padrao ?? "—"}" aria-label="Faturamentos de ${esc(a.nome)} em ${valor}">
        ${ajuste != null ? `<button type="button" class="sug-limpar" data-limpar="${k}" data-mes="${valor}" title="Voltar ao automático" aria-label="Voltar ao automático">${icone("x")}</button>` : ""}
      </span></td>`;
    }).join("");
    return `<tr class="${areaMudou(a.id) ? "mudou" : ""}">
      <td class="nome-v">${esc(a.nome)}${semConta ? ` <span class="chip-papel inativo">fica fora</span>` : ""}
        <small>código ${a.id} · ${a.clientes} cliente${a.clientes === 1 ? "" : "s"}${a.vendedores.length ? ` · ${esc(a.vendedores.join(", "))}` : ""}</small></td>
      <td>${descreverDias(a.dias)}</td>
      <td><select class="sug-prazo" data-prazo="${k}" aria-label="Prazo do faturamento de ${esc(a.nome)}"${fixo != null ? " disabled" : ""}>
          ${[1, 2, 3, 4, 5].map((n) => `<option value="${n}"${n === prazo ? " selected" : ""}>${n === 1 ? "1 dia útil" : `${n} dias úteis`}</option>`).join("")}
        </select>${observado ? `<small class="fraco">nas vendas: ${esc(observado)}</small>` : ""}</td>
      <td><span class="sug-modo">
        <select data-modo="${k}" aria-label="Como contar os faturamentos de ${esc(a.nome)}">
          <option value="auto"${fixo == null ? " selected" : ""}>Pelos dias</option>
          <option value="fixo"${fixo != null ? " selected" : ""}>Fixo</option>
        </select>
        ${fixo != null ? `<input type="number" min="1" max="31" step="1" data-fixo="${k}" value="${fixo}" aria-label="Faturamentos fixos por mês">` : ""}
      </span></td>
      ${celulas}
    </tr>`;
  }).join("");
}

function aoMudar(e) {
  const t = e.target;
  if (t.dataset.prazo) {
    if (t.value === "1") delete rasc.prazos[t.dataset.prazo]; else rasc.prazos[t.dataset.prazo] = Number(t.value);
  } else if (t.dataset.modo) {
    if (t.value === "fixo") rasc.fixos[t.dataset.modo] = orig.fixos[t.dataset.modo] ?? 2;
    else delete rasc.fixos[t.dataset.modo];
  } else if (t.dataset.fixo) {
    const n = Number(t.value);
    rasc.fixos[t.dataset.fixo] = t.value.trim() === "" ? NaN : n;
  } else if (t.dataset.ajuste) {
    const mes = t.dataset.mes, k = t.dataset.ajuste;
    if (t.value.trim() === "") {
      if (rasc.ajustes[mes]) delete rasc.ajustes[mes][k];
    } else {
      rasc.ajustes[mes] = rasc.ajustes[mes] || {};
      rasc.ajustes[mes][k] = Number(t.value);
    }
    if (rasc.ajustes[mes] && !Object.keys(rasc.ajustes[mes]).length) delete rasc.ajustes[mes];
  } else return;
  desenharAreas();
  atualizarBarra();
}

function aoClicar(e) {
  const b = e.target.closest("[data-limpar]");
  if (!b) return;
  const { mes, limpar } = b.dataset;
  if (rasc.ajustes[mes]) {
    delete rasc.ajustes[mes][limpar];
    if (!Object.keys(rasc.ajustes[mes]).length) delete rasc.ajustes[mes];
  }
  desenharAreas();
  atualizarBarra();
}

// ---------- gravação ----------
function erro(msg) {
  if (secao !== "regras" && /crescimento|teto/.test(msg)) { secao = "regras"; render(); }
  const el = raiz.querySelector("#cs-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

async function salvar() {
  const regras = contarRegras() > 0, metas = contarAprovacao() > 0;
  if (regras) {
    for (const [v, nome] of [[rasc.crescimento.ES, "o crescimento desejado do ES"], [rasc.crescimento.BA, "o crescimento desejado do BA"],
      [rasc.teto_sazonalidade, "o teto da sazonalidade"], [rasc.teto_crescimento, "o teto do crescimento proposto"]]) {
      if (!(v >= 0 && v <= 1)) return erro(`Use um valor entre 0% e 100% para ${nome}.`);
    }
  }
  const itens = metas ? itensAprovacao() : [];
  if (metas && !itens) return;
  const btn = raiz.querySelector("#cs-salvar");
  btn.disabled = true;
  try {
    if (regras) carregarDados(await api("/api/sugestao/config", { json: { config: rasc, mes: dados.mes } }));
    if (metas) {
      aprov = await api("/api/sugestao/aprovacao", { json: { estado: aprov.estado, mes: aprov.mes.meta, itens } });
      aprovRasc = {};
    }
    toast(metas ? "Metas gravadas: as aprovadas já valem no painel de Metas" : "Configuração da sugestão de metas salva");
    ctx.aoSalvar && ctx.aoSalvar(metas);
    render();
  } catch (e) {
    if (metas && secao !== "aprovacao" && !regras) { secao = "aprovacao"; render(); }
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

// ======================================================================================
// Aprovação de metas
// ======================================================================================
const linhasAprov = () => (aprov ? [...aprov.vendedores, ...aprov.outros, ...aprov.fora] : []);
const ehES = (v) => (v.aprovada ? v.aprovada.estado : aprov.estado) === "ES";

// Os valores gravados (aprovada) ou os sugeridos (pendente): o rascunho parte deles.
function padraoLinha(v) {
  const a = v.aprovada;
  if (a) return { aprovada: true, meta_fat: a.meta_fat, meta_mus: a.meta_mus, meta_cli: a.meta_cli };
  const s = v.sugerida || { fat: 0, mus: 0 };
  return { aprovada: false, meta_fat: Math.round(s.fat), meta_mus: Math.round(s.mus), meta_cli: v.clientes };
}
const atualLinha = (v) => aprovRasc[v.id] || padraoLinha(v);

function linhaMudou(v) {
  const o = padraoLinha(v), a = atualLinha(v);
  if (o.aprovada !== a.aprovada) return true;
  return a.aprovada && (o.meta_fat !== a.meta_fat || o.meta_cli !== a.meta_cli || (ehES(v) && o.meta_mus !== a.meta_mus));
}
const contarAprovacao = () => linhasAprov().filter(linhaMudou).length;

// A meta de volume de cada produto para o R$ da linha (a mesma conta do servidor, bi/aprovacao.py distribuir): no BA um
// fator só; no ES, o da mussarela e o das outras linhas. sobra = R$ sem produto para ir.
function distribuir(produtos, metaFat, metaMus, es) {
  const soma = (mus) => produtos.filter((p) => (p.grupo === "mussarela") === mus).reduce((a, p) => a + p.volume_sugerido * p.preco, 0);
  const sm = soma(true), so = soma(false);
  let fm, fo, sobra;
  if (es) {
    const am = metaMus, ao = metaFat - metaMus;
    fm = sm > 0 ? am / sm : 0; fo = so > 0 ? ao / so : 0;
    sobra = (sm > 0 ? 0 : am) + (so > 0 ? 0 : ao);
  } else {
    fm = fo = sm + so > 0 ? metaFat / (sm + so) : 0;
    sobra = sm + so > 0 ? 0 : metaFat;
  }
  return { lista: produtos.map((p) => ({ ...p, meta_volume: p.volume_sugerido * (p.grupo === "mussarela" ? fm : fo) })), sobra };
}

async function carregarAprovacao(estado, mes) {
  const r = await api(`/api/sugestao/aprovacao?estado=${estado}${mes ? `&mes=${mes}` : ""}`);
  aprov = r;
  aprovEstado = r.estado;
  aprovMes = r.mes.meta;
  aprovRasc = {};
  aberto = null;
}

async function secaoAprovacao(alvo) {
  if (!aprov) {
    alvo.innerHTML = `<section class="cartao secao"><div class="esqueleto" style="height:460px"></div></section>`;
    try {
      await carregarAprovacao(aprovEstado, aprovMes || dados.mes);
    } catch (e) {
      alvo.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a aprovação: ${esc(e.message)}</p></div>`;
      return;
    }
    if (secao !== "aprovacao") return;
  }
  const es = aprov.estado === "ES";
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("certo")}Aprovação de metas</h2>
      <p class="sub">A meta aprovada vale no painel de Metas no lugar das linhas da METAS.xlsx e da METAS PRODUTOS.xlsx do
        vendedor nesse mês. Edite o total em R$ e a meta de volume dos produtos muda no mesmo percentual${es
          ? "; no ES, a mussarela vem dos produtos da sugestão e outras linhas é o resto" : ""}. Os clientes vêm com a carteira do dia 1º.
        Editar uma linha pendente já marca para aprovar. A meta aprovada fica congelada, mesmo que a sugestão mude depois.</p></div>
      <div class="sug-aprov-filtros">
        <div class="seg-mini" role="group" aria-label="Estado" id="ca-estado">
          ${aprov.estados.map((e) => `<button type="button" data-estado="${e}" class="${e === aprov.estado ? "ativo" : ""}">${e}</button>`).join("")}</div>
        <label class="campo" title="O mês da meta (o mês base é o anterior)"><span class="ic-campo">${icone("calendario")}</span>
          <select id="ca-mes" aria-label="Mês da meta">${aprov.opcoes_meses.map((m) => `<option value="${m.valor}"${m.valor === aprov.mes.meta ? " selected" : ""}>Meta de ${esc(m.rotulo)}</option>`).join("")}</select></label>
      </div>
    </div>
    ${aprov.avisos.map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("")}
    <div class="sug-aprov-resumo" id="ca-resumo"></div>
    <div class="tabela-rolagem sug-aprov-rolagem"><table class="dados sug-aprov${es ? " es" : ""}">
      <thead><tr><th>Vendedor</th><th title="O que a fórmula da sugestão dá (na aprovada, o que dava quando foi aprovada)">Sugerida</th>
        <th>Meta (R$)</th>${es ? `<th title="Outras linhas = meta − mussarela">Mussarela (R$)</th>` : ""}
        <th title="${esc(textoClientes(aprov.clientes))}">Clientes</th><th>Na planilha</th><th>Situação</th></tr></thead>
      <tbody id="ca-linhas"></tbody>
    </table></div>
    ${aprov.outros.length ? `<button type="button" class="btn sug-aprov-outros" id="ca-outros" title="Do grupo do ${esc(aprov.estado)} nas Configurações das metas, com venda no mês base e sem meta nos últimos 3 meses">
      ${icone(verOutros ? "minimizar" : "mais")}${verOutros ? "Esconder" : "Mostrar"} ${aprov.outros.length} vendedor${aprov.outros.length === 1 ? "" : "es"} sem meta recente</button>` : ""}
  </section>`;
  alvo.querySelector("#ca-estado").addEventListener("click", (e) => {
    const b = e.target.closest("[data-estado]");
    if (b && b.dataset.estado !== aprov.estado) trocarAprovacao(b.dataset.estado, aprov.mes.meta, alvo);
  });
  alvo.querySelector("#ca-mes").addEventListener("change", (e) => trocarAprovacao(aprov.estado, e.target.value, alvo));
  const outros = alvo.querySelector("#ca-outros");
  if (outros) outros.addEventListener("click", () => { verOutros = !verOutros; secaoAprovacao(alvo); });
  const corpo = alvo.querySelector("#ca-linhas");
  corpo.addEventListener("change", aoEditarMeta);
  corpo.addEventListener("click", aoClicarMeta);
  alvo.querySelector("#ca-resumo").addEventListener("click", (e) => { if (e.target.closest("#ca-todas")) aprovarTodas(); });
  desenharMetas();
}

async function trocarAprovacao(estado, mes, alvo) {
  if (contarAprovacao() && !confirm("Descartar as alterações da aprovação que ainda não foram salvas?")) {
    secaoAprovacao(alvo);  // volta o seletor ao estado e mês da aba
    return;
  }
  try {
    await carregarAprovacao(estado, mes);
    secaoAprovacao(alvo);
    atualizarBarra();
  } catch (e) { toast(e.message, "erro"); }
}

function textoClientes(c) {
  if (c.fonte === "carteira") return `Clientes ativos da carteira em ${fmt.data(c.dia)} (sem os de pedido bloqueado)`;
  if (c.fonte === "carteira_hoje") return `O dia 1º ainda não chegou: clientes ativos da carteira em ${fmt.data(c.dia)}`;
  return "Sem o histórico da carteira nesse dia: vem a META CLIENTE da planilha";
}

const sinalPct = (v) => (v == null || !isFinite(v) ? "" : `${v >= 0 ? "+" : "−"}${fmt.pct(Math.abs(v))}`);
const quando = (iso) => (iso ? `${fmt.dataCurta(iso.slice(0, 10))} às ${iso.slice(11, 16)}` : "");

function desenharMetas() {
  const es = aprov.estado === "ES";
  const cols = es ? 7 : 6;
  const grupos = [[aprov.vendedores, ""], [verOutros ? aprov.outros : [], "Sem meta nos últimos 3 meses (confira o grupo nas Configurações das metas)"],
    [aprov.fora, "Aprovadas, mas fora da lista de vendedores hoje"]];
  raiz.querySelector("#ca-linhas").innerHTML = grupos.filter(([l]) => l.length).map(([lista, titulo]) =>
    (titulo ? `<tr class="sug-aprov-sep"><td colspan="${cols}">${esc(titulo)}</td></tr>` : "")
    + lista.map((v) => linhaMeta(v, cols)).join("")).join("")
    || `<tr><td colspan="${cols}" class="fraco">Nenhum vendedor do ${esc(aprov.estado)} com meta recente.</td></tr>`;
  // resumo: as da lista, com o rascunho
  const lista = aprov.vendedores;
  const aprovadas = lista.filter((v) => atualLinha(v).aprovada);
  const totalAprov = aprovadas.reduce((a, v) => a + (atualLinha(v).meta_fat || 0), 0);
  const totalSug = lista.reduce((a, v) => a + ((v.sugerida && v.sugerida.fat) || 0), 0);
  const pendentes = lista.filter((v) => !atualLinha(v).aprovada && v.sugerida && v.sugerida.fat > 0).length;
  raiz.querySelector("#ca-resumo").innerHTML = `
    <span><b>${aprovadas.length}</b> de ${lista.length} aprovada${lista.length === 1 ? "" : "s"}</span>
    <span>Aprovado <b>${fmt.moeda(totalAprov)}</b></span>
    <span>Sugerido ${fmt.moeda(totalSug)}</span>
    ${pendentes ? `<button type="button" class="btn" id="ca-todas">${icone("visto")}Aprovar ${pendentes === 1 ? "a pendente" : `as ${pendentes} pendentes`}</button>` : ""}`;
}

function situacao(v) {
  const o = padraoLinha(v), a = atualLinha(v);
  if (linhaMudou(v)) {
    const texto = !o.aprovada ? "A aprovar" : !a.aprovada ? "A retirar" : "Alteração não salva";
    return `<span class="chip-papel sug-aprov-rasc">${texto}</span><small>falta salvar</small>`;
  }
  if (v.aprovada) {
    const x = v.aprovada;
    return `<span class="chip-papel sug-aprov-ok">${icone("visto")}Aprovada</span>
      <small>${esc([x.aprovada_por, quando(x.aprovada_em)].filter(Boolean).join(" · "))}</small>
      ${x.alterada_em ? `<small>alterada${x.alterada_por ? ` por ${esc(x.alterada_por)}` : ""} · ${quando(x.alterada_em)}</small>` : ""}`;
  }
  return `<span class="chip-papel inativo">Pendente</span>
    ${v.retirada ? `<small>retirada${v.retirada.por ? ` por ${esc(v.retirada.por)}` : ""} · ${quando(v.retirada.em)}</small>` : ""}`;
}

function linhaMeta(v, cols) {
  const a = atualLinha(v), es = ehES(v), mudou = linhaMudou(v);
  const travada = !a.aprovada && !!v.aprovada;  // aprovada que vai ser retirada
  const sug = v.aprovada ? v.aprovada.sugerida_fat : v.sugerida && v.sugerida.fat;
  const hoje = v.aprovada && v.sugerida && Math.abs(v.sugerida.fat - v.aprovada.sugerida_fat) > Math.max(1, 0.005 * v.aprovada.sugerida_fat)
    ? v.sugerida.fat : null;
  const variacao = sug > 0 && a.meta_fat ? a.meta_fat / sug - 1 : null;
  const auto = v.aprovada ? v.aprovada.clientes_carteira : v.clientes;
  const diaAuto = v.aprovada ? v.aprovada.clientes_dia : aprov.clientes.fonte !== "planilha" ? aprov.clientes.dia : null;
  const semProdutos = !(v.aprovada ? v.aprovada.produtos : (v.sugerida || {}).produtos || []).length;
  const campo = (nome, valor, rotulo, passo = 1) => `<input type="number" min="0" step="${passo}" inputmode="numeric" data-campo="${nome}" data-id="${v.id}"
    value="${valor ?? ""}" aria-label="${esc(rotulo)} de ${esc(v.nome)}"${travada ? " disabled" : ""}>`;
  const p = v.planilha;
  let html = `<tr class="${mudou ? "mudou" : ""}${!a.aprovada ? " pendente" : ""}">
    <td class="ca-vend"><span class="ca-vend-in">
      <button class="chave ${a.aprovada ? "ligada" : ""}" type="button" role="switch" aria-checked="${a.aprovada}" data-aprovar="${v.id}"
        aria-label="Aprovar a meta de ${esc(v.nome)}"></button>
      <button type="button" class="ca-nome" data-abrir="${v.id}" aria-expanded="${aberto === v.id}" title="Ver a meta de volume dos produtos">
        ${esc(v.nome)}${icone("proximo", "ca-seta")}</button></span>
      ${v.equipe === "EDIR" ? `<small>Edir</small>` : ""}</td>
    <td>${sug != null ? fmt.moeda(sug) : "—"}${hoje != null ? `<small class="aviso-nota" title="A fórmula mudou desde a aprovação (devoluções, carteira, regras)">hoje: ${fmt.moeda(hoje)}</small>` : ""}</td>
    <td><span class="sug-num sug-aprov-num${mudou && a.meta_fat !== padraoLinha(v).meta_fat ? " ajustado" : ""}">${campo("meta_fat", a.meta_fat, "Meta em R$")}</span>
      <small>${variacao == null ? (semProdutos ? "sem produtos" : "")
        : Math.abs(variacao) < 0.0005 ? "= sugerida" : `${sinalPct(variacao)} na sugerida`}</small></td>`;
  if (es) {
    const out = (a.meta_fat || 0) - (a.meta_mus || 0);
    html += `<td><span class="sug-num sug-aprov-num${mudou && a.meta_mus !== padraoLinha(v).meta_mus ? " ajustado" : ""}">${campo("meta_mus", a.meta_mus, "Mussarela em R$")}</span>
      <small title="Outras linhas: ${fmt.moeda(out)}">${a.meta_fat > 0 ? `${fmt.pct((a.meta_mus || 0) / a.meta_fat, 0)} · outras ${fmt.moedaC(out)}` : ""}</small></td>`;
  }
  html += `<td><span class="sug-num${mudou && a.meta_cli !== padraoLinha(v).meta_cli ? " ajustado" : ""}">${campo("meta_cli", a.meta_cli, "Clientes")}</span>
      <small title="${diaAuto ? `Clientes ativos da carteira em ${fmt.data(diaAuto)}` : "Sem o histórico da carteira"}">${auto != null ? `carteira: ${auto}` : "preencha"}</small></td>
    <td>${p ? `${fmt.moeda(p.fat)}<small>${fmt.num(p.cli)} clientes${es && p.fat ? ` · mus. ${fmt.pct(p.mus / p.fat, 0)}` : ""}</small>` : `<span class="fraco">—</span>`}</td>
    <td class="ca-sit">${situacao(v)}</td>
  </tr>`;
  if (aberto === v.id) html += produtosMeta(v, cols);
  return html;
}

function produtosMeta(v, cols) {
  const a = atualLinha(v), es = ehES(v);
  const base = v.aprovada ? v.aprovada.produtos : (v.sugerida || {}).produtos || [];
  const { lista, sobra } = distribuir(base, a.meta_fat || 0, es ? a.meta_mus || 0 : 0, es);
  const total = lista.reduce((s, p) => s + p.meta_volume * p.preco, 0);
  return `<tr class="sug-aprov-prod"><td colspan="${cols}"><div class="sug-aprov-prod-in">
    ${lista.length ? `<table class="dados sug-aprov-mini">
      <thead><tr><th>Produto</th><th>Volume sugerido</th><th>Preço médio</th><th>Meta de volume</th><th>Meta (R$)</th></tr></thead>
      <tbody>${lista.map((p) => `<tr><td>${esc(p.produto)}${es && p.grupo === "mussarela" ? " <small>mussarela</small>" : ""}</td>
        <td>${fmt.num(p.volume_sugerido, 1)} ${esc(p.unidade)}</td><td>${fmt.moeda2(p.preco)}</td>
        <td><b>${fmt.num(p.meta_volume, 1)} ${esc(p.unidade)}</b></td><td>${fmt.moeda(p.meta_volume * p.preco)}</td></tr>`).join("")}</tbody>
      <tfoot><tr><td>Total (${lista.length} produto${lista.length === 1 ? "" : "s"})</td><td></td><td></td><td></td><td>${fmt.moeda(total)}</td></tr></tfoot>
    </table>` : `<p class="fraco">Sem produtos na sugestão para distribuir a meta de volume.</p>`}
    ${sobra > 0.5 && lista.length ? `<div class="aviso">${icone("alerta")}<span>${fmt.moeda(sobra)} da meta não têm produto ${es ? "desse grupo " : ""}na sugestão e ficam sem meta de volume.</span></div>` : ""}
    <p class="fraco">${v.aprovada ? `Volumes sobre o retrato da sugestão de quando foi aprovada${v.aprovada.clientes_dia ? ` (carteira de ${fmt.data(v.aprovada.clientes_dia)})` : ""}.` : "A meta de volume que vai para o painel ao aprovar com esse valor."}</p>
  </div></td></tr>`;
}

function aoClicarMeta(e) {
  const chave = e.target.closest("[data-aprovar]");
  const abrir = e.target.closest("[data-abrir]");
  if (chave) {
    const v = linhasAprov().find((x) => x.id === Number(chave.dataset.aprovar));
    const a = atualLinha(v), o = padraoLinha(v);
    if (a.aprovada) {  // desligar: retira a aprovada; numa pendente, volta aos valores sugeridos
      if (v.aprovada) aprovRasc[v.id] = { ...o, aprovada: false }; else delete aprovRasc[v.id];
    } else if (v.aprovada) {
      delete aprovRasc[v.id];  // religar uma aprovada: volta ao que está gravado
    } else {
      aprovRasc[v.id] = { ...a, aprovada: true };
    }
  } else if (abrir) {
    const id = Number(abrir.dataset.abrir);
    aberto = aberto === id ? null : id;
  } else return;
  desenharMetas();
  atualizarBarra();
}

function aoEditarMeta(e) {
  const t = e.target;
  if (!t.dataset.campo) return;
  const v = linhasAprov().find((x) => x.id === Number(t.dataset.id));
  const a = { ...atualLinha(v) };
  const n = t.value.trim() === "" ? null : Number(t.value);
  if (t.dataset.campo === "meta_fat" && ehES(v) && a.meta_fat > 0 && n != null) {
    a.meta_mus = Math.round((a.meta_mus || 0) * n / a.meta_fat);  // a mussarela acompanha o total, no mesmo %
  }
  a[t.dataset.campo] = n;
  a.aprovada = true;  // editar uma pendente já marca para aprovar
  aprovRasc[v.id] = a;
  if (!linhaMudou(v)) delete aprovRasc[v.id];
  desenharMetas();
  atualizarBarra();
}

function aprovarTodas() {
  let sem = 0;
  for (const v of aprov.vendedores) {
    const a = atualLinha(v);
    if (a.aprovada || !(v.sugerida && v.sugerida.fat > 0)) continue;
    if (a.meta_cli == null) { sem++; continue; }
    aprovRasc[v.id] = { ...a, aprovada: true };
  }
  if (sem) toast(`${sem} vendedor${sem === 1 ? "" : "es"} sem o número de clientes ficaram de fora: preencha e aprove`, "erro");
  desenharMetas();
  atualizarBarra();
}

// As linhas mudadas para gravar, já conferidas (null = algum erro, com o aviso).
function itensAprovacao() {
  const itens = [];
  for (const v of linhasAprov().filter(linhaMudou)) {
    const a = atualLinha(v), es = ehES(v);
    if (a.aprovada) {
      let msg = null;
      if (!(a.meta_fat > 0)) msg = `A meta de ${v.nome} precisa ser maior que zero.`;
      else if (es && !(a.meta_mus >= 0 && a.meta_mus <= a.meta_fat)) msg = `A mussarela de ${v.nome} precisa ficar entre zero e a meta total.`;
      else if (!(Number.isInteger(a.meta_cli) && a.meta_cli >= 0)) msg = `Preencha os clientes de ${v.nome} com um número inteiro.`;
      if (msg) {
        if (secao !== "aprovacao") { secao = "aprovacao"; render(); }
        toast(msg, "erro");
        return null;
      }
    }
    itens.push({ id_vendedor: v.id, aprovada: a.aprovada, meta_fat: a.meta_fat, meta_mus: es ? a.meta_mus : 0,
      meta_cli: a.meta_cli, versao: v.versao });
  }
  return itens;
}
