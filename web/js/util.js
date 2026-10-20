// Utilidades comuns: ícones, formatação pt-BR, animações de número, tooltip, avisos e chamadas à API.

const ICONES = {
  alvo: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
  engrenagem: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  atualizar: '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v5h-5"/>',
  sol: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  lua: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  moeda: '<circle cx="12" cy="12" r="9"/><path d="M14.8 9.3c-.5-.9-1.5-1.5-2.8-1.5-1.6 0-2.7.9-2.7 2.1 0 2.9 5.6 1.4 5.6 4.3 0 1.2-1.2 2.1-2.9 2.1-1.3 0-2.4-.6-2.9-1.6M12 6v1.8M12 16.3V18"/>',
  queijo: '<path d="M3 18V12.5L13 5l8 5.5V18z"/><path d="M3 12.5h18"/><circle cx="8" cy="15.3" r="1.1"/><circle cx="15.5" cy="15" r="1.4"/><circle cx="12.5" cy="9.5" r=".9"/>',
  leite: '<path d="M8.5 2.5h7v3l2.5 3.5V21H6V9l2.5-3.5z"/><path d="M6 13h12"/><path d="M8.5 5.5h7"/>',
  pessoas: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.2c2.6.3 4.5 2.4 4.5 5"/>',
  recibo: '<path d="M6 2.5h12v19l-3-2-3 2-3-2-3 2z"/><path d="M9 7.5h6M9 11.5h6M9 15.5h3"/>',
  calendario: '<rect x="3" y="4.5" width="18" height="16.5" rx="3"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>',
  caixa: '<path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5l9 4.5 9-4.5M12 12v9"/>',
  grafico: '<path d="M3 3v18h18"/><path d="M7 15l4-5 4 3 5-6"/>',
  ranking: '<path d="M4 6h11M4 12h16M4 18h7"/>',
  estrela: '<path d="m12 3 2.7 5.6 6.1.8-4.5 4.2 1.2 6L12 16.8 6.5 19.6l1.2-6-4.5-4.2 6.1-.8z"/>',
  certo: '<circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.7 2.7L16.2 9.5"/>',
  alerta: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.3v.2"/>',
  abaixo: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v9M8 12.5l4 4 4-4"/>',
  menos: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
  busca: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  usuario: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/>',
  devolucao: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  mais: '<path d="M12 5v14M5 12h14"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.2"/>',
  raio: '<path d="M13 2.5 4.5 13.5H11l-1 8 8.5-11H12z"/>',
  mapa: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  etiqueta: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8" r="1.3"/>',
  restaurar: '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/>',
  disco: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
  olho: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  expandir: '<path d="M14.5 3.5h6v6M9.5 20.5h-6v-6M20.5 3.5l-7 7M3.5 20.5l7-7"/>',
  recolher: '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
  cadeado: '<rect x="4.5" y="10.5" width="15" height="10.5" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/><path d="M12 14.5v2.5"/>',
  chave: '<circle cx="8" cy="15" r="4.5"/><path d="m11.2 11.8 8.8-8.8M16.5 6.5l2.5 2.5M14 9l2 2"/>',
  sair: '<path d="M14 4.5h4.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14"/><path d="M10 16.5 5.5 12 10 7.5M5.5 12H16"/>',
  escudo: '<path d="M12 2.8 4.5 5.8v5.7c0 4.6 3.2 8.3 7.5 9.7 4.3-1.4 7.5-5.1 7.5-9.7V5.8z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
  olhoFechado: '<path d="M3 3l18 18M10.6 5.1A10.5 10.5 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7c1.7 0 3.2-.5 4.5-1.2"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  visto: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  lapis: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  lixeira: '<path d="M4 7h16M10 11v6M14 11v6M5.5 7l1 13h11l1-13M9 7V4h6v3"/>',
  tendencia: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  menu: '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
  painel: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/><path d="m15.5 10-2 2 2 2"/>',
  funil: '<path d="M3.5 5h17l-6.5 7.5V19l-4 2v-8.5z"/>',
  voltar: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  ajustes: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  conversa: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z"/><path d="M8.5 8.5h7M8.5 11.5h4.5"/>',
  enviar: '<path d="M21 3 10.5 13.5"/><path d="M21 3l-6.5 18-4-7.5L3 9.5z"/>',
  copiar: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V6A2.5 2.5 0 0 0 13 3.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/>',
  banco: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13"/><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
  quadro: '<rect x="3" y="3.5" width="5" height="17" rx="1.6"/><rect x="9.5" y="3.5" width="5" height="11" rx="1.6"/><rect x="16" y="3.5" width="5" height="7" rx="1.6"/>',
  trofeu: '<path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4.5a2.5 2.5 0 0 0 2.6 3.4M17 6h2.5a2.5 2.5 0 0 1-2.6 3.4"/><path d="M12 14v3.5M8.5 20.5h7M9.5 17.5h5"/>',
  seta: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  arquivo: '<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v10.5h14V9M10 13h4"/>',
  pontos: '<circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
  bandeira: '<path d="M5 21V4"/><path d="M5 4.5c2.5-1.6 5-1.6 7 0s4.5 1.6 7 0v9c-2.5 1.6-5 1.6-7 0s-4.5-1.6-7 0"/>',
  foguete:'<path d="M12 15c-2-2-3-5-1-9 2-3 6-3.5 9-3.5 0 3-.5 7-3.5 9-4 2-7 1-9-1"/><path d="M9 13 5 14l2-4M11 15l-1 4 4-2"/><circle cx="15.5" cy="8.5" r="1.4"/>',
};

export function icone(nome, classe = "") {
  return `<svg class="ic ${classe}" viewBox="0 0 24 24" aria-hidden="true">${ICONES[nome] || ""}</svg>`;
}

// Botão sol/lua do topo: alterna o tema e lembra a escolha neste navegador.
export function ligarTema(btn) {
  btn.addEventListener("click", () => {
    const novo = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", novo);
    try { localStorage.setItem("mv-tema", novo); } catch { /* sem armazenamento */ }
    window.dispatchEvent(new Event("tema"));
  });
}

export function preencherIcones(raiz = document) {
  raiz.querySelectorAll("[data-icone]").forEach((el) => {
    if (!el.querySelector("svg")) el.insertAdjacentHTML("afterbegin", icone(el.dataset.icone));
  });
}

// ---------- formatação ----------
const nf = (min, max) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: min, maximumFractionDigits: max });
const NF0 = nf(0, 0), NF1 = nf(1, 1), NF2 = nf(2, 2), NF01 = nf(0, 1);

export const fmt = {
  moeda: (v) => (v == null || isNaN(v) ? "—" : "R$ " + NF0.format(Math.round(v))),
  moedaC(v) {
    if (v == null || isNaN(v)) return "—";
    const a = Math.abs(v), s = v < 0 ? "−" : "";
    if (a >= 1e6) return `${s}R$ ${NF2.format(a / 1e6)} mi`;
    if (a >= 1e4) return `${s}R$ ${NF1.format(a / 1e3)} mil`;
    return `${s}R$ ${NF0.format(a)}`;
  },
  eixo(v) {
    if (v >= 1e6) return NF01.format(v / 1e6) + " mi";
    if (v >= 1e3) return NF0.format(v / 1e3) + " mil";
    return NF0.format(v);
  },
  pct: (v, d = 1) => (v == null || isNaN(v) ? "—" : nf(d, d).format(v * 100) + "%"),
  num: (v, d = 0) => (v == null || isNaN(v) ? "—" : nf(0, d).format(v)),
  dias: (v) => (v == null ? "—" : NF01.format(v)),
  data: (iso) => { const [a, m, d] = iso.split("-"); return `${d}/${m}/${a}`; },
  dataCurta: (iso) => { const [, m, d] = iso.split("-"); return `${d}/${m}`; },
  semana: (iso) => ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"][new Date(iso + "T12:00").getDay()],
  dataHora: (iso) => { if (!iso) return "—"; const [d, h] = iso.split("T"); return `${fmt.data(d)} às ${h.slice(0, 5)}`; },
};

export const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- status ----------
export const STATUS = {
  batida: { rotulo: "Meta batida", icone: "estrela" },
  no_ritmo: { rotulo: "No ritmo", icone: "certo" },
  atencao: { rotulo: "Atenção", icone: "alerta" },
  abaixo: { rotulo: "Abaixo do ritmo", icone: "abaixo" },
  sem_meta: { rotulo: "Sem meta", icone: "menos" },
  sem_dados: { rotulo: "Sem dados", icone: "menos" }, // média sem divisor (ex.: nenhuma visita esperada)
};

export function chipStatus(st, rotulo) {
  const s = STATUS[st] || STATUS.sem_meta;
  return `<span class="status ${st}">${icone(s.icone)}${esc(rotulo || s.rotulo)}</span>`;
}

export function corStatus(st) {
  return { batida: "var(--ok-forte)", no_ritmo: "var(--ok-forte)", atencao: "var(--atencao-forte)", abaixo: "var(--ruim-forte)" }[st] || "var(--linha-forte)";
}

// ---------- movimento ----------
export const reduzMovimento = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function contar(el, para, formatar, duracao = 1100) {
  if (!el) return;
  const de = Number(el.dataset.valor || 0);
  el.dataset.valor = para ?? 0;
  if (para == null || isNaN(para)) { el.textContent = formatar(para); return; }
  if (reduzMovimento() || de === para) { el.textContent = formatar(para); return; }
  const t0 = performance.now();
  const passo = (t) => {
    const p = Math.min(1, (t - t0) / duracao);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = formatar(de + (para - de) * e);
    if (p < 1) requestAnimationFrame(passo);
  };
  requestAnimationFrame(passo);
}

export function animarContadores(raiz) {
  raiz.querySelectorAll("[data-contar]").forEach((el) => {
    const tipo = el.dataset.fmt || "moedaC";
    const f = tipo === "pct0" ? (v) => fmt.pct(v, 0) : fmt[tipo];
    contar(el, Number(el.dataset.contar), f);
  });
}

// Aplica larguras/offsets depois de inserir o HTML, para as transições CSS acontecerem.
export function animarEntradas(raiz) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    raiz.querySelectorAll("[data-largura]").forEach((el) => { el.style.width = el.dataset.largura; });
    raiz.querySelectorAll("[data-offset]").forEach((el) => { el.style.strokeDashoffset = el.dataset.offset; });
  }));
}

// ---------- tooltip ----------
const tt = () => document.getElementById("tooltip");
export function mostrarTooltip(html, x, y) {
  const el = tt();
  el.innerHTML = html;
  el.hidden = false;
  const r = el.getBoundingClientRect();
  let left = x + 16, top = y + 16;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - 16;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - 16;
  el.style.left = Math.max(8, left) + "px";
  el.style.top = Math.max(8, top) + "px";
}
export function esconderTooltip() { tt().hidden = true; }

export function ligarTooltips(raiz) {
  raiz.querySelectorAll("[data-tt]").forEach((el) => {
    el.addEventListener("mousemove", (e) => mostrarTooltip(el.dataset.tt, e.clientX, e.clientY));
    el.addEventListener("mouseleave", esconderTooltip);
    el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); mostrarTooltip(el.dataset.tt, r.right, r.top); });
    el.addEventListener("blur", esconderTooltip);
  });
}

export function linhaTT(rotulo, valor, cor) {
  const k = cor ? `<span class="k"><i style="--c:${cor}"></i>${esc(rotulo)}</span>` : `<span>${esc(rotulo)}</span>`;
  return `<div class="tt-l">${k}<b>${valor}</b></div>`;
}

// ---------- avisos ----------
export function toast(msg, tipo = "ok") {
  const el = document.createElement("div");
  el.className = "toast " + tipo;
  el.innerHTML = icone(tipo === "erro" ? "alerta" : "certo") + `<span>${esc(msg)}</span>`;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => { el.classList.add("sai"); setTimeout(() => el.remove(), 320); }, tipo === "erro" ? 6000 : 3200);
}

// ---------- API ----------
// Sessão vencida ou encerrada: volta para o login (e depois para a mesma tela). semLogin desliga isso.
export async function api(url, opcoes = {}) {
  const { semLogin, ...init } = opcoes;
  if (opcoes.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opcoes.json);
  }
  const r = await fetch(url, init);
  let dados = null;
  try { dados = await r.json(); } catch { /* corpo vazio */ }
  if (r.status === 401 && !semLogin) {
    irParaLogin();
    return new Promise(() => {}); // a página vai trocar; nada mais deve rodar
  }
  if (!r.ok) {
    const e = new Error((dados && dados.erro) || `erro ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return dados;
}

export function irParaLogin() {
  const volta = location.hash.startsWith("#/") ? "?volta=" + encodeURIComponent(location.hash) : "";
  location.replace("/login" + volta);
}

export function guardar(chave, valor) { try { localStorage.setItem(chave, JSON.stringify(valor)); } catch { /* sem armazenamento */ } }
export function ler(chave, padrao = null) { try { const v = localStorage.getItem(chave); return v == null ? padrao : JSON.parse(v); } catch { return padrao; } }
