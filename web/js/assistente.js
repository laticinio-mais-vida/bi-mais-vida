// Página Assistente: chat em que a pessoa pergunta sobre os dados e a IA (Claude) responde consultando o cache.
// A conta é toda no servidor (bi/assistente.py): ele monta os dados do acesso da pessoa, chama a IA e devolve a
// resposta com as consultas feitas. A conversa fica só neste navegador (sessionStorage) e volta ao servidor como
// texto a cada pergunta. A resposta da IA vira HTML só depois de escapada (nada do texto vira tag por conta própria).
import { api, esc, fmt, icone, toast } from "./util.js";

const CHAVE = "mv-assistente";
const ESPERA_MAX = 170000; // ms; o servidor desiste antes (tempo_total do config.ini)
const SUGESTOES = [
  "Quanto vendemos este mês, por equipe?",
  "Quais os 10 clientes que mais compraram no mês passado?",
  "Como estão as metas do mês?",
  "Quais clientes compraram no mês passado e ainda não compraram este mês?",
  "Quais produtos tiveram mais devolução nos últimos 3 meses, e por quê?",
];
const FERRAMENTA = {
  buscar_cliente: { nome: "Busca de cliente", icone: "busca" },
  buscar_produto: { nome: "Busca de produto", icone: "busca" },
  buscar_vendedor: { nome: "Busca de vendedor", icone: "busca" },
  resumo_vendas: { nome: "Resumo de vendas", icone: "moeda" },
  metas_e_realizado: { nome: "Metas e realizado", icone: "alvo" },
  consultar_sql: { nome: "Consulta aos dados", icone: "banco" },
};

let ctx = null, raiz = null, info = null;
let conversa = [];      // [{papel: "usuario"|"assistente", texto, consultas?, passos?, data_ref?, aviso?, uso?}]
let esperando = null;   // {inicio, relogio, controle} enquanto a pergunta está no servidor

function lerConversa() { try { return JSON.parse(sessionStorage.getItem(CHAVE)) || []; } catch { return []; } }
function guardarConversa() { try { sessionStorage.setItem(CHAVE, JSON.stringify(conversa)); } catch { /* sem armazenamento */ } }

export async function montarAssistente(container, contexto) {
  ctx = contexto;
  raiz = container;
  conversa = lerConversa();
  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("conversa")}</span>
        <div><b>Assistente de dados</b><small id="a-escopo">respostas com os dados do painel</small></div></div>
      <div class="filtros">
        <button class="btn btn-limpar" type="button" id="a-nova">${icone("mais")}Nova conversa</button>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-assistente" title="Configurações do assistente: o que cada pessoa consulta e o uso">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="a-avisos"></div>
    <section class="cartao chat entra" style="--i:1">
      <div class="chat-mensagens" id="a-msgs" aria-live="polite"></div>
      <form class="chat-entrada" id="a-form">
        <textarea id="a-texto" rows="1" maxlength="4000" placeholder="Faça uma pergunta sobre os dados…" aria-label="Sua pergunta"></textarea>
        <button class="btn primario" type="submit" id="a-enviar">${icone("enviar")}<span>Enviar</span></button>
      </form>
      <p class="chat-rodape" id="a-rodape">As respostas são geradas por IA com os dados do painel. Confira os números importantes em “Como cheguei nesse número”.</p>
    </section>`;
  const texto = container.querySelector("#a-texto");
  // Aba fechada ou recarregada no meio de uma pergunta: ela ficou sem resposta e volta para a caixa de texto.
  if (!esperando && conversa.at(-1)?.papel === "usuario") {
    texto.value = conversa.pop().texto;
    guardarConversa();
  }
  texto.addEventListener("input", () => ajustarAltura(texto));
  texto.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviar(); }
  });
  container.querySelector("#a-form").addEventListener("submit", (e) => { e.preventDefault(); enviar(); });
  container.querySelector("#a-nova").addEventListener("click", () => {
    if (esperando) return toast("Espere a resposta antes de começar outra conversa", "erro");
    conversa = [];
    guardarConversa();
    desenharMensagens();
    texto.focus();
  });
  desenharMensagens();
  await carregarInfo();
}

async function carregarInfo() {
  const avisos = raiz.querySelector("#a-avisos");
  try {
    info = await api("/api/assistente/info");
  } catch (e) {
    avisos.innerHTML = `<div class="aviso">${icone("alerta")}<span>${esc(e.message)}</span></div>`;
    travar(true);
    return;
  }
  if (info.data_ref) ctx.subtitulo({ data_ref: info.data_ref });
  if (info.escopo) raiz.querySelector("#a-escopo").textContent = `consulta ${info.escopo}`;
  const msgs = [];
  if (!info.configurado) {
    msgs.push(ctx.admin
      ? "O assistente ainda não foi configurado: coloque a chave da API da Anthropic em [ia] no config.ini do servidor e reinicie o painel (veja o README)."
      : "O assistente ainda não foi configurado. Fale com o administrador.");
  } else if (!info.pronto) {
    msgs.push("Os dados por cliente ainda não chegaram do computador da empresa. O assistente funciona depois da próxima atualização dos dados.");
  }
  avisos.innerHTML = msgs.map((m) => `<div class="aviso">${icone("alerta")}<span>${esc(m)}</span></div>`).join("");
  travar(!info.configurado || !info.pronto);
  mostrarRestantes(info.restantes);
}

function travar(sim) {
  raiz.querySelector("#a-texto").disabled = sim;
  raiz.querySelector("#a-enviar").disabled = sim;
  raiz.querySelectorAll(".chat-sugestao").forEach((b) => { b.disabled = sim; });
}

function mostrarRestantes(n) {
  const el = raiz.querySelector("#a-rodape");
  const base = "As respostas são geradas por IA com os dados do painel. Confira os números importantes em “Como cheguei nesse número”.";
  el.textContent = n == null ? base : `${base} ${n === 1 ? "Resta 1 pergunta" : `Restam ${n} perguntas`} hoje.`;
}

function ajustarAltura(t) {
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 200) + "px";
  t.style.overflowY = t.scrollHeight > 200 ? "auto" : "hidden"; // barra de rolagem só quando passa da altura máxima
}

// ---------- envio ----------
async function enviar(textoPronto) {
  if (esperando) return;
  const caixa = raiz.querySelector("#a-texto");
  const texto = (textoPronto ?? caixa.value).trim();
  if (!texto || caixa.disabled) return;
  caixa.value = "";
  ajustarAltura(caixa);
  conversa.push({ papel: "usuario", texto });
  guardarConversa();
  const controle = new AbortController();
  const limite = setTimeout(() => controle.abort(), ESPERA_MAX);
  esperando = { inicio: Date.now(), controle };
  desenharMensagens();
  esperando.relogio = setInterval(atualizarPensando, 1000);
  try {
    const mensagens = conversa.map(({ papel, texto: t, consultas }) => ({ papel, texto: t, consultas }));
    const r = await api("/api/assistente", { json: { mensagens }, signal: controle.signal });
    conversa.push({ papel: "assistente", texto: r.resposta, consultas: r.consultas, passos: r.passos,
      data_ref: r.data_ref, aviso: r.aviso, uso: r.uso });
    guardarConversa();
    if (r.restantes !== undefined) mostrarRestantes(r.restantes);
    pararEspera(limite);
    desenharMensagens();
  } catch (e) {
    // A pergunta não foi respondida: sai da conversa e volta para a caixa, para tentar de novo.
    conversa.pop();
    guardarConversa();
    pararEspera(limite);
    desenharMensagens();
    caixa.value = texto;
    ajustarAltura(caixa);
    const msg = e.name === "AbortError" ? "A resposta demorou demais. Tente uma pergunta mais simples ou mais específica." : e.message;
    desenharErro(msg);
  }
}

function pararEspera(limite) {
  clearTimeout(limite);
  if (esperando) clearInterval(esperando.relogio);
  esperando = null;
}

function atualizarPensando() {
  const el = raiz.querySelector("#a-pensando-s");
  if (el && esperando) el.textContent = `${Math.round((Date.now() - esperando.inicio) / 1000)} s`;
}

// ---------- desenho ----------
function desenharMensagens() {
  const el = raiz.querySelector("#a-msgs");
  if (!conversa.length && !esperando) {
    el.innerHTML = `
      <div class="chat-inicio">
        <span class="chat-avatar grande">${icone("conversa")}</span>
        <h2>Pergunte sobre os dados</h2>
        <p>Vendas, devoluções, clientes, produtos e metas, com os mesmos números das outras páginas.
          Cite clientes e produtos pelo nome: o assistente procura no cadastro.</p>
        <div class="chat-sugestoes">${SUGESTOES.map((s) => `<button type="button" class="chat-sugestao">${esc(s)}</button>`).join("")}</div>
      </div>`;
    el.querySelectorAll(".chat-sugestao").forEach((b) => b.addEventListener("click", () => enviar(b.textContent)));
    if (info) travar(!info.configurado || !info.pronto);
    return;
  }
  el.innerHTML = conversa.map((m, i) => (m.papel === "usuario" ? balaoUsuario(m) : balaoIA(m, i))).join("") +
    (esperando ? `<div class="chat-msg ia"><span class="chat-avatar">${icone("conversa")}</span>
      <div class="chat-corpo"><div class="chat-balao"><span class="chat-pensando">
        <span class="chat-pontos"><i></i><i></i><i></i></span>Consultando os dados… <span id="a-pensando-s">0 s</span>
      </span></div></div></div>` : "");
  el.querySelectorAll("[data-copiar]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(conversa[Number(b.dataset.copiar)].texto);
      toast("Resposta copiada");
    } catch { toast("Não foi possível copiar", "erro"); }
  }));
  const ultima = el.lastElementChild;
  if (ultima) requestAnimationFrame(() => ultima.scrollIntoView({ block: "nearest", behavior: "smooth" }));
}

function desenharErro(msg) {
  const el = raiz.querySelector("#a-msgs");
  el.insertAdjacentHTML("beforeend", `<div class="chat-msg ia"><span class="chat-avatar">${icone("alerta")}</span>
    <div class="chat-corpo"><div class="chat-balao erro">${esc(msg)}</div>
    <div class="chat-meta"><span>A pergunta voltou para a caixa de texto: ajuste se quiser e envie de novo.</span></div></div></div>`);
  el.lastElementChild.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function balaoUsuario(m) {
  return `<div class="chat-msg usuario"><div class="chat-balao">${esc(m.texto)}</div></div>`;
}

function balaoIA(m, i) {
  const passos = m.passos || [];
  const meta = [
    m.data_ref ? `dados até ${fmt.dataCurta(m.data_ref)}` : "",
    m.uso?.segundos != null ? `${fmt.num(m.uso.segundos, 0)} s` : "",
    m.uso?.custo != null ? `≈ US$ ${fmt.num(m.uso.custo, 3)} · ${fmt.num(m.uso.entrada + m.uso.cache_leitura + m.uso.cache_escrita)} tokens de entrada (${fmt.num(m.uso.cache_leitura)} do cache), ${fmt.num(m.uso.saida)} de saída` : "",
  ].filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("");
  return `<div class="chat-msg ia"><span class="chat-avatar">${icone("conversa")}</span>
    <div class="chat-corpo">
      <div class="chat-balao chat-texto">${markdown(m.texto)}</div>
      ${m.aviso ? `<p class="chat-aviso">${icone("alerta")}${esc(m.aviso)}</p>` : ""}
      <div class="chat-meta">${meta}<button type="button" class="chat-acao" data-copiar="${i}">${icone("copiar")}Copiar</button></div>
      ${passos.length ? desenharPassos(passos) : ""}
    </div></div>`;
}

function desenharPassos(passos) {
  return `<details class="chat-passos"><summary>${icone("banco")}Como cheguei nesse número
      <span class="fraco">${passos.length} consulta${passos.length === 1 ? "" : "s"}</span></summary>
    ${passos.map((p) => {
      const f = FERRAMENTA[p.ferramenta] || { nome: p.ferramenta, icone: "banco" };
      const linhas = p.erro ? `<b>erro:</b> ${esc(p.erro)}` : `${fmt.num(p.linhas)} linha${p.linhas === 1 ? "" : "s"} · ${fmt.num(p.ms)} ms`;
      return `<div class="chat-passo ${p.erro ? "erro" : ""}">
        <div class="t">${icone(f.icone)}<b>${esc(f.nome)}</b><span>${esc(descricao(p))}</span><small>${linhas}</small></div>
        ${p.sql ? `<pre>${esc(p.sql)}</pre>` : ""}
        ${p.colunas?.length && p.amostra?.length ? amostra(p) : ""}
      </div>`;
    }).join("")}
  </details>`;
}

function descricao(p) {
  const a = p.args || {};
  if (p.ferramenta.startsWith("buscar_")) return `“${a.texto || ""}”`;
  if (p.ferramenta === "resumo_vendas") {
    const partes = [`${a.de ? fmt.data(a.de) : "?"} a ${a.ate ? fmt.data(a.ate) : "?"}`];
    if (a.agrupar_por?.length) partes.push(`por ${a.agrupar_por.join(" e ")}`);
    return partes.join(", ");
  }
  if (p.ferramenta === "metas_e_realizado") return `${a.visao || ""} · ${(a.meses || []).join(", ")}`;
  return p.objetivo || a.objetivo || "";
}

function amostra(p) {
  const codigo = p.colunas.map((c) => /^id(_|$)/.test(c)); // códigos sem separador de milhar
  const celula = (v, j) => (typeof v === "number" ? (codigo[j] ? String(v) : fmt.num(v, 2)) : v === null ? "—"
    : typeof v === "boolean" ? (v ? "sim" : "não") : esc(v));
  const mais = p.linhas > p.amostra.length ? `<p class="fraco chat-mais">mostrando ${p.amostra.length} de ${fmt.num(p.linhas)} linhas</p>` : "";
  const num = p.colunas.map((_, j) => p.amostra.every((r) => r[j] === null || typeof r[j] === "number"));
  const classe = (j) => (num[j] ? ' class="num"' : "");
  return `<div class="tabela-rolagem"><table class="dados">
    <thead><tr>${p.colunas.map((c, j) => `<th${classe(j)}>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${p.amostra.map((r) => `<tr>${r.map((v, j) => `<td${classe(j)}>${celula(v, j)}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>${mais}`;
}

// ---------- markdown simples e seguro ----------
// O texto é escapado antes; depois só viram tag os marcadores conhecidos (negrito, itálico, código, títulos,
// listas e tabelas com |). Assim nada do que a IA escrever vira HTML de verdade.
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>");
}

const ehLinhaTabela = (l) => /^\s*\|.*\|\s*$/.test(l);
const ehSeparador = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const ehItem = (l) => /^\s*[-*•]\s+/.test(l);
const ehNumerado = (l) => /^\s*\d+[.)]\s+/.test(l);
const ehTitulo = (l) => /^\s*#{1,4}\s+/.test(l);

// Número, valor em reais ou percentual (alinha à direita nas tabelas).
const ehNumero = (c) => /^[−-]?\s*(R\$\s*)?[−-]?[\d.,]+\s*(%|mi|mil|kg|un)?$/i.test(c.replace(/\*\*/g, "").trim());

function markdown(texto) {
  const linhas = esc(texto || "").replace(/\r/g, "").split("\n");
  const partes = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  let html = "";
  let i = 0;
  while (i < linhas.length) {
    const l = linhas[i];
    if (ehLinhaTabela(l) && i + 1 < linhas.length && ehSeparador(linhas[i + 1])) {
      const cab = partes(l);
      // alinhamento: o do separador (---: ou :---:) e, sem ele, à direita nas colunas só de números
      const sep = partes(linhas[i + 1]);
      i += 2;
      const corpo = [];
      while (i < linhas.length && ehLinhaTabela(linhas[i])) corpo.push(partes(linhas[i++]));
      const alinhar = cab.map((_, j) => {
        const s = sep[j] || "";
        if (s.startsWith(":") && s.endsWith(":")) return "centro";
        if (s.endsWith(":")) return "num";
        if (s.startsWith(":")) return "";
        const valores = corpo.map((r) => r[j] || "").filter(Boolean);
        return valores.length && valores.every(ehNumero) ? "num" : "";
      });
      const td = (tag, c, j) => `<${tag}${alinhar[j] ? ` class="${alinhar[j]}"` : ""}>${inline(c || "")}</${tag}>`;
      html += `<div class="tabela-rolagem"><table class="dados"><thead><tr>${cab.map((c, j) => td("th", c, j)).join("")}</tr></thead>
        <tbody>${corpo.map((r) => `<tr>${cab.map((_, j) => td("td", r[j], j)).join("")}</tr>`).join("")}</tbody></table></div>`;
      continue;
    }
    if (ehItem(l) || ehNumerado(l)) {
      const numerada = ehNumerado(l);
      const itens = [];
      while (i < linhas.length && (numerada ? ehNumerado(linhas[i]) : ehItem(linhas[i]))) {
        itens.push(linhas[i++].replace(numerada ? /^\s*\d+[.)]\s+/ : /^\s*[-*•]\s+/, ""));
      }
      const tag = numerada ? "ol" : "ul";
      html += `<${tag}>${itens.map((x) => `<li>${inline(x)}</li>`).join("")}</${tag}>`;
      continue;
    }
    if (ehTitulo(l)) {
      html += `<h4>${inline(l.replace(/^\s*#{1,4}\s+/, ""))}</h4>`;
      i++;
      continue;
    }
    if (!l.trim()) { i++; continue; }
    const par = [];
    while (i < linhas.length && linhas[i].trim() && !ehItem(linhas[i]) && !ehNumerado(linhas[i]) && !ehTitulo(linhas[i])
           && !(ehLinhaTabela(linhas[i]) && i + 1 < linhas.length && ehSeparador(linhas[i + 1]))) {
      par.push(inline(linhas[i++]));
    }
    html += `<p>${par.join("<br>")}</p>`;
  }
  return html;
}
