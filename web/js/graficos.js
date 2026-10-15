// Gráficos em SVG desenhados à mão (sem bibliotecas): anel de progresso, corrida da meta, ranking e barras.
import { esc, fmt, icone, STATUS, corStatus, mostrarTooltip, esconderTooltip, linhaTT, reduzMovimento } from "./util.js";

const NS = "http://www.w3.org/2000/svg";

// ---------- anel de progresso ----------
// pct: realizado/meta; ritmo: fração esperada até hoje (marca no anel); cor: CSS var.
export function anel({ pct, ritmo = null, cor = "var(--s-fat)", rotulo = "da meta", tamanho = 104 }) {
  const r = 42, c = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(pct ?? 0, 1));
  const extra = Math.max(0, Math.min((pct ?? 0) - 1, 1));
  const marca = ritmo != null && ritmo > 0 && ritmo < 1
    ? (() => {
        const a = ritmo * 2 * Math.PI;
        const x1 = 50 + (r - 9) * Math.cos(a), y1 = 50 + (r - 9) * Math.sin(a);
        const x2 = 50 + (r + 9) * Math.cos(a), y2 = 50 + (r + 9) * Math.sin(a);
        return `<line class="marca-ritmo" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
      })()
    : "";
  return `
    <div class="anel" style="--cor:${cor};width:${tamanho}px;height:${tamanho}px">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle class="trilho" cx="50" cy="50" r="${r}" fill="none" stroke-width="10"/>
        <circle class="arco" cx="50" cy="50" r="${r}" fill="none" stroke-width="10"
          stroke-dasharray="${c}" stroke-dashoffset="${c}" data-offset="${c * (1 - p)}"/>
        ${extra > 0 ? `<circle class="arco-extra" cx="50" cy="50" r="${r - 13}" fill="none" stroke-width="5"
          stroke-dasharray="${2 * Math.PI * (r - 13)}" stroke-dashoffset="${2 * Math.PI * (r - 13)}"
          data-offset="${2 * Math.PI * (r - 13) * (1 - extra)}"/>` : ""}
        ${marca}
      </svg>
      <div class="anel-centro"><div>
        <div class="p"><span data-contar="${pct ?? 0}" data-fmt="pct0">0%</span></div>
        <div class="l">${esc(rotulo)}</div>
      </div></div>
    </div>`;
}

// ---------- escala "bonita" ----------
function ticks(max, n = 4) {
  if (max <= 0) return [0, 1];
  const bruto = max / n;
  const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= bruto) || 10 * mag;
  const saida = [];
  for (let v = 0; v <= max + passo * 0.001; v += passo) saida.push(v);
  if (saida[saida.length - 1] < max) saida.push(saida[saida.length - 1] + passo);
  return saida;
}

// ---------- corrida da meta (acumulado do mês x ritmo esperado) ----------
export function corrida(el, { diario, dias, meta, chave = "fat_acum", cor = "var(--s-fat)", projecao = null, situacao = "aberto", nome = "Faturamento" }) {
  let w = 0;
  const desenhar = () => {
    w = el.clientWidth;
    const tela = el.closest(".tela-cheia");
    const W = Math.max(320, el.clientWidth);
    const H = tela ? Math.max(340, Math.min(860, tela.clientHeight - 250)) : 340;
    const m = tela ? { e: 70, d: 128, t: 26, b: 34 } : { e: 58, d: 96, t: 22, b: 30 };
    const n = diario.length;
    const reais = diario.map((d) => d[chave]);
    const ultimo = reais.reduce((u, v, i) => (v != null ? i : u), -1);
    const maxReal = Math.max(0, ...reais.filter((v) => v != null));
    const yMaxBruto = Math.max(meta || 0, projecao || 0, maxReal) * 1.08 || 1;
    const tk = ticks(yMaxBruto, 4);
    const yMax = tk[tk.length - 1];
    const x = (i) => m.e + (i / Math.max(1, n - 1)) * (W - m.e - m.d);
    const y = (v) => H - m.b - (v / yMax) * (H - m.t - m.b);
    const esperado = diario.map((d) => (meta || 0) * d.ritmo);

    let s = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(nome)} acumulado no mês comparado ao ritmo esperado">`;
    // dias sem expediente (faixas suaves)
    const larg = (W - m.e - m.d) / Math.max(1, n - 1);
    (dias || []).forEach((d, i) => {
      if (d.peso === 0) s += `<rect x="${x(i) - larg / 2}" y="${m.t}" width="${larg}" height="${H - m.t - m.b}" fill="var(--surface-3)" opacity=".4"/>`;
    });
    tk.forEach((v) => {
      s += `<line class="grade-l" x1="${m.e}" x2="${W - m.d}" y1="${y(v)}" y2="${y(v)}"/>`;
      s += `<text class="eixo-t" x="${m.e - 10}" y="${y(v) + 4}" text-anchor="end">${fmt.eixo(v)}</text>`;
    });
    diario.forEach((d, i) => {
      const dia = Number(d.data.slice(8));
      if (dia === 1 || dia % 5 === 0 || i === n - 1) s += `<text class="eixo-t" x="${x(i)}" y="${H - 8}" text-anchor="middle">${dia}</text>`;
    });
    const temProj = projecao != null && situacao === "aberto" && ultimo >= 0 && ultimo < n - 1;
    // rótulos à direita: se meta e projeção ficarem perto, um vai para cima e o outro para baixo
    let yMeta = meta ? y(meta) + 4 : 0, yProj = temProj ? y(projecao) + 4 : 0;
    if (meta && temProj && Math.abs(y(meta) - y(projecao)) < 20) {
      if (projecao >= meta) { yProj = y(projecao) - 9; yMeta = y(meta) + 15; } else { yMeta = y(meta) - 9; yProj = y(projecao) + 15; }
    }
    if (meta) {
      s += `<line class="linha-meta" x1="${m.e}" x2="${W - m.d}" y1="${y(meta)}" y2="${y(meta)}"/>`;
      s += `<text class="rotulo-meta" x="${W - m.d + 8}" y="${yMeta}">Meta ${fmt.moedaC(meta)}</text>`;
      s += `<path class="linha-ritmo" d="M${esperado.map((v, i) => `${x(i)},${y(v)}`).join("L")}"/>`;
    }
    if (ultimo >= 0) {
      const pts = reais.slice(0, ultimo + 1).map((v, i) => `${x(i)},${y(v)}`);
      s += `<path class="area-real aparece" d="M${x(0)},${y(0)}L${pts.join("L")}L${x(ultimo)},${y(0)}Z" style="--cor:${cor}"/>`;
      s += `<path class="linha-real" id="linha-real" d="M${pts.join("L")}" style="--cor:${cor}"/>`;
      if (temProj) {
        s += `<path class="linha-proj aparece" d="M${x(ultimo)},${y(reais[ultimo])}L${x(n - 1)},${y(projecao)}" style="--cor:${cor}"/>`;
        s += `<circle class="aparece" cx="${x(n - 1)}" cy="${y(projecao)}" r="4" fill="var(--surface)" stroke="${cor}" stroke-width="2"/>`;
        s += `<text class="eixo-t aparece" x="${x(n - 1) + 8}" y="${yProj}">proj. ${fmt.moedaC(projecao)}</text>`;
      }
      s += `<circle class="ponto-fim aparece" cx="${x(ultimo)}" cy="${y(reais[ultimo])}" r="5" style="--cor:${cor}"/>`;
      const ly = y(reais[ultimo]);
      s += `<text class="rotulo-fim aparece" x="${x(ultimo)}" y="${ly - 12}" text-anchor="${ultimo > n * 0.75 ? "end" : "middle"}">${fmt.moedaC(reais[ultimo])}</text>`;
    }
    s += `<line class="mira" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}"/><circle class="mira-ponto" r="5" style="--cor:${cor}"/>`;
    s += `<rect class="captura" x="${m.e}" y="${m.t}" width="${W - m.e - m.d}" height="${H - m.t - m.b}" fill="transparent"/>`;
    s += "</svg>";
    el.innerHTML = s;
    el.style.setProperty("--cor", cor);

    const linha = el.querySelector("#linha-real");
    if (linha && !reduzMovimento() && !el.dataset.desenhado) {
      const L = linha.getTotalLength();
      linha.style.strokeDasharray = L;
      linha.style.strokeDashoffset = L;
      linha.classList.add("desenha");
    }
    el.dataset.desenhado = "1";

    const svg = el.querySelector("svg"), mira = el.querySelector(".mira"), ponto = el.querySelector(".mira-ponto");
    const mover = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.e) / (W - m.e - m.d)) * (n - 1))));
      const d = diario[i];
      el.classList.add("ativo");
      mira.setAttribute("x1", x(i)); mira.setAttribute("x2", x(i));
      const v = d[chave];
      if (v != null) { ponto.setAttribute("cx", x(i)); ponto.setAttribute("cy", y(v)); ponto.style.opacity = 1; } else ponto.style.opacity = 0;
      const dif = v != null && meta ? v - esperado[i] : null;
      const info = (dias || [])[i];
      mostrarTooltip(
        `<div class="tt-t">${fmt.dataCurta(d.data)} · ${fmt.semana(d.data)}${info && info.motivo && info.peso < 1 ? ` · ${esc(info.motivo)}` : ""}</div>` +
        (v != null ? linhaTT(`${nome} acumulado`, fmt.moeda(v), cor) : linhaTT("Ainda sem dados", "—")) +
        (meta ? linhaTT("Esperado pelo ritmo", fmt.moeda(esperado[i]), "var(--s-ritmo)") : "") +
        (dif != null ? linhaTT(dif >= 0 ? "Acima do ritmo" : "Abaixo do ritmo", fmt.moeda(Math.abs(dif))) : "") +
        (d.fat != null && chave === "fat_acum" ? linhaTT("Vendido no dia", fmt.moeda(d.fat)) : ""),
        ev.clientX, ev.clientY);
    };
    const sair = () => { el.classList.remove("ativo"); esconderTooltip(); };
    const cap = el.querySelector(".captura");
    cap.addEventListener("mousemove", mover);
    cap.addEventListener("mouseleave", sair);
  };
  desenhar();
  el._redesenhar = desenhar;
  if (el._ro) el._ro.disconnect();
  el._ro = new ResizeObserver(() => { if (Math.abs(el.clientWidth - w) > 4) desenhar(); });
  el._ro.observe(el);
}

// ---------- ranking de vendedores ----------
export function ranking(el, itens, { ritmo, situacao, selecionado, aoClicar }) {
  if (!itens.length) { el.innerHTML = `<div class="vazio">${icone("usuario")}<p>Nenhum vendedor com meta neste mês.</p></div>`; return; }
  const ord = [...itens].sort((a, b) => (b.pct ?? -1) - (a.pct ?? -1));
  const maxPct = Math.max(1.1, ...ord.map((i) => i.pct || 0));
  const escala = Math.min(maxPct, 2) * 1.04;
  const pos = (v) => `${(Math.min(v, escala) / escala) * 100}%`;
  const alvo = situacao === "fechado" ? null : ritmo;
  let h = `<div class="rank-escala"><span></span><span></span><div class="faixa-e">`;
  if (alvo) h += `<span style="left:${pos(alvo)}">ritmo ${fmt.pct(alvo, 0)}</span>`;
  h += `<span style="left:${pos(1)}">meta 100%</span></div><span></span></div><div class="ranking">`;
  ord.forEach((it, i) => {
    const st = STATUS[it.status] || STATUS.sem_meta;
    h += `<div class="rank-linha ${selecionado === it.id ? "selecionada" : ""}" tabindex="0" role="button" data-id="${it.id}"
           data-tt="${esc(`<div class='tt-t'>${esc(it.nome)}</div>` + linhaTT("Realizado", fmt.moeda(it.realizado)) + linhaTT("Meta", fmt.moeda(it.meta)) + linhaTT("Atingido", fmt.pct(it.pct)) + linhaTT("Situação", st.rotulo))}">
        <span class="rank-pos ${i < 3 ? "top" : ""}">${i + 1}º</span>
        <span class="rank-nome" title="${esc(it.nome)}">${esc(it.nome)}</span>
        <span class="rank-trilho">
          ${alvo ? `<span class="rank-marca" style="left:${pos(alvo)}"></span>` : ""}
          <span class="rank-marca cem" style="left:${pos(1)}"></span>
          <span class="rank-barra ${it.status === "batida" ? "batida" : ""}" style="--cor-barra:${corStatus(it.status)}" data-largura="${pos(it.pct || 0)}"></span>
        </span>
        <span class="rank-val"><b>${icone(st.icone)} ${fmt.pct(it.pct)}</b><span>${fmt.moedaC(it.realizado)}</span></span>
      </div>`;
  });
  h += "</div>";
  el.innerHTML = h;
  el.querySelectorAll(".rank-val .ic").forEach((s, i) => { s.style.color = corStatus(ord[i].status); s.style.width = "14px"; s.style.height = "14px"; });
  el.querySelectorAll(".rank-linha").forEach((linha) => {
    const ir = () => aoClicar && aoClicar(Number(linha.dataset.id));
    linha.addEventListener("click", ir);
    linha.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ir(); } });
  });
}

// ---------- barras horizontais simples (uma série) ----------
export function barras(itens, { cor = "var(--s-out)", total = null, formato = fmt.moedaC } = {}) {
  const max = Math.max(1, ...itens.map((i) => Math.abs(i.valor)));
  return `<div class="barras">${itens.map((it) => `
    <div class="barra-l" data-tt="${esc(`<div class='tt-t'>${esc(it.nome)}</div>` + linhaTT("Valor", fmt.moeda(it.valor)) + (total ? linhaTT("Participação", fmt.pct(it.valor / total)) : ""))}">
      <span class="nome">${it.icone ? icone(it.icone) : ""}${esc(it.nome)}</span>
      <span class="trilho"><span class="enche" style="--cor:${it.cor || cor}" data-largura="${(Math.max(0, it.valor) / max) * 100}%"></span></span>
      <span class="val">${formato(it.valor)}${total ? `<small>${fmt.pct(it.valor / total)} do total</small>` : ""}</span>
    </div>`).join("")}</div>`;
}
