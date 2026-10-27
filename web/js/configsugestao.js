// Configuração da página Sugestão de Metas (só administradores): o crescimento desejado no ano por estado, os tetos da
// sazonalidade e do crescimento proposto, e os faturamentos das áreas do BA (prazo entre o atendimento e o faturamento,
// número fixo para as quinzenais e ajustes à mão por área e mês). Quem vê a página e quais vendedores segue o acesso de
// Metas. Tudo vale depois de Salvar.
import { api, esc, icone, toast } from "./util.js";

const DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
const NOMES_PAPEIS = { base: "mês base", meta: "mês da meta", base_ly: "base, ano passado", meta_ly: "meta, ano passado" };

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/sugestao/config
let orig = null, rasc = null;
let secao = "regras";
let busca = "";

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
    carregarDados(await api(`/api/sugestao/config${mes ? `?mes=${mes}` : ""}`));
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

function contarAlteracoes() {
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
      ${[["regras", "tendencia", "Regras da conta"], ["faturamentos", "calendario", "Faturamentos por área"]]
        .map(([id, ic, nome]) => `<button data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}</button>`).join("")}
      <div class="dica">${icone("info")} Vale só para a página Sugestão de Metas, assim que você salvar. As metas lançadas e o
        ERP não mudam. Quem vê a página e quais vendedores segue o acesso de Metas.</div>
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
  raiz.querySelector("#cs-descartar").addEventListener("click", () => { rasc = clone(orig); render(); });
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cs-secao");
  if (secao === "faturamentos") secaoFaturamentos(alvo);
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
  for (const [v, nome] of [[rasc.crescimento.ES, "o crescimento desejado do ES"], [rasc.crescimento.BA, "o crescimento desejado do BA"],
    [rasc.teto_sazonalidade, "o teto da sazonalidade"], [rasc.teto_crescimento, "o teto do crescimento proposto"]]) {
    if (!(v >= 0 && v <= 1)) return erro(`Use um valor entre 0% e 100% para ${nome}.`);
  }
  const btn = raiz.querySelector("#cs-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/sugestao/config", { json: { config: rasc, mes: dados.mes } }));
    toast("Configuração da sugestão de metas salva");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}
