// Escolher um dia sem o calendário do navegador: uma faixa de quadradinhos como a da agenda (o dia da semana, o número,
// hoje em destaque e, quando a agenda conta, quantos itens o dia já tem), com setas para os dias de antes e os de
// depois. Cabem quantos dias a largura deixa; a faixa se refaz quando a largura muda.
// O valor fica num input escondido (name ou data-campo), que avisa "change" a cada escolha: o formulário lê como lia o
// <input type="date">. Com o foco num dia, as setas do teclado andam a escolha um dia.
// - campoDia({...}): o HTML do campo; prepararDias(raiz) desenha os campos novos depois que o HTML entra na página.
// - limitesDoDia(input, {min, max}): os dias de fora ficam bloqueados. focarDia(input): o foco vai para o dia escolhido.
// - contarDias(fn): fn(dia) → {n, classe} (os itens do dia; classe tem, feita ou atrasada) ou null; redesenharDias()
//   refaz todos os campos depois que a contagem muda.
import { MESES, esc, fmt, icone } from "./util.js";

const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const LARGURA = 38, VAO = 4;   // o menor quadradinho e o espaço entre dois
const MIN_DIAS = 5, MAX_DIAS = 31, SEM_LARGURA = 14;
let contador = () => null;

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const data = (dia) => new Date(`${dia}T12:00`);
const hoje = () => iso(new Date());
const entre = (de, ate) => Math.round((data(ate) - data(de)) / 864e5);
const capitalizar = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const mesCurto = (dia) => MESES[data(dia).getMonth()].slice(0, 3);
function somar(dia, n) {
  const d = data(dia);
  d.setDate(d.getDate() + n);
  return iso(d);
}

export function contarDias(fn) {
  contador = fn;
}

// nome (name="…") ou campo (data-campo="…"): onde o valor fica. rotulo: o nome do grupo de dias, para leitor de tela.
// vazio: o texto de quando não há dia, só nos campos opcionais (aparece também o botão que limpa). maxDica: por que os
// dias depois de max ficam bloqueados. contar: false nos campos de outra pessoa (a contagem é a da minha agenda).
// extra: HTML ao lado do dia escolhido (o horário, nas subtarefas).
export function campoDia({ nome, campo, valor = "", min = "", max = "", rotulo, vazio = "", maxDica = "", contar = true, extra = "" }) {
  return `<div class="ed" data-min="${min}" data-max="${max}" data-vazio="${esc(vazio)}" data-max-dica="${esc(maxDica)}" ${contar ? "" : 'data-sem-contagem'}>
    <input type="hidden" ${nome ? `name="${nome}"` : `data-campo="${campo}"`} value="${valor || ""}">
    <div class="ed-faixa">
      <button type="button" class="ed-seta" data-ed-mover="-1" title="Dias anteriores" aria-label="Dias anteriores">${icone("anterior")}</button>
      <div class="ed-dias" role="group" aria-label="${esc(rotulo)}"></div>
      <button type="button" class="ed-seta" data-ed-mover="1" title="Próximos dias" aria-label="Próximos dias">${icone("proximo")}</button>
    </div>
    <div class="ed-rodape">
      <button type="button" class="ed-escolhido" data-ed-ir title="Mostrar o dia escolhido"></button><span class="ed-mes"></span>
      ${vazio ? `<button type="button" class="ge-link ed-limpar" data-ed-limpar>Limpar</button>` : ""}
      ${extra ? `<span class="ed-extra">${extra}</span>` : ""}
    </div>
  </div>`;
}

// Quantos quadradinhos cabem na largura (escondido, ainda sem largura: um padrão, refeito quando aparecer).
function cabem(dias) {
  const w = dias.clientWidth;
  return w ? Math.max(MIN_DIAS, Math.min(MAX_DIAS, Math.floor((w + VAO) / (LARGURA + VAO)))) : SEM_LARGURA;
}

const observador = new ResizeObserver((entradas) => {
  for (const { target } of entradas) {
    const el = target.closest(".ed");
    if (!el?.isConnected) observador.unobserve(target);
    else if (cabem(target) !== Number(el.dataset.n)) desenhar(el);
  }
});

export function prepararDias(raiz) {
  raiz.querySelectorAll(".ed:not([data-n])").forEach((el) => {
    desenhar(el);
    observador.observe(el.querySelector(".ed-dias"));
  });
}

export function redesenharDias() {
  document.querySelectorAll(".ed[data-n]").forEach(desenhar);
}

export function limitesDoDia(input, { min, max } = {}) {
  const el = input.closest(".ed");
  if (min !== undefined) el.dataset.min = min || "";
  if (max !== undefined) el.dataset.max = max || "";
  if (el.dataset.n) desenhar(el);
}

export function focarDia(input) {
  const el = input.closest(".ed");
  el.dataset.ini = inicio(input.value, Number(el.dataset.n) || SEM_LARGURA);
  desenhar(el);
  (el.querySelector(".ed-dia.escolhido") || el.querySelector(".ed-dia:not(:disabled)"))?.focus();
}

// Onde a faixa começa: hoje, se o dia escolhido cabe a partir dele; senão, uns dias antes do escolhido.
function inicio(valor, n) {
  const h = hoje();
  if (!valor || (valor >= h && entre(h, valor) < n - 1)) return h;
  return somar(valor, -Math.min(3, Math.floor(n / 4)));
}

// "outubro de 2026", "out – nov de 2026" ou "dez de 2026 – jan de 2027".
function meses(de, ate) {
  const [a1, m1] = de.split("-"), [a2, m2] = ate.split("-");
  if (a1 === a2 && m1 === m2) return `${MESES[m1 - 1]} de ${a1}`;
  return a1 === a2 ? `${mesCurto(de)} – ${mesCurto(ate)} de ${a1}` : `${mesCurto(de)} de ${a1} – ${mesCurto(ate)} de ${a2}`;
}

function desenhar(el) {
  const input = el.querySelector("input");
  const valor = input.value, n = cabem(el.querySelector(".ed-dias")), h = hoje();
  const { min, max } = el.dataset;
  const ini = el.dataset.ini || inicio(valor, n);
  Object.assign(el.dataset, { ini, n });
  const dias = Array.from({ length: n }, (_, k) => somar(ini, k));
  el.querySelector(".ed-dias").innerHTML = dias.map((d, k) => {
    const dt = data(d), dow = dt.getDay(), num = dt.getDate();
    const fora = (min && d < min) || (max && d > max);
    const c = "semContagem" in el.dataset ? null : contador(d);
    const classes = ["ed-dia", c?.classe || "", dow === 0 || dow === 6 ? "fds" : "", d === h ? "hoje" : "",
      d === valor ? "escolhido" : "", fora ? "fora" : ""].filter(Boolean).join(" ");
    const nome = `${capitalizar(fmt.semana(d))}, ${num} de ${MESES[dt.getMonth()]}${d === h ? " (hoje)" : ""}` +
      (c?.n ? `: ${c.n} ${c.n === 1 ? "item" : "itens"} na agenda` : "");
    const dica = !fora ? nome : min && d < min ? `Antes de ${fmt.dataCurta(min)}`
      : `${el.dataset.maxDica || "Depois do limite"} (${fmt.dataCurta(max)})`;
    return `<button type="button" class="${classes}" data-ed-dia="${d}" ${fora ? "disabled" : ""} aria-pressed="${d === valor}"
      aria-label="${esc(nome)}" title="${esc(dica)}">${k === 0 || num === 1 ? `<span class="ed-mes-tag">${mesCurto(d)}</span>` : ""}<span
      class="ed-sem">${SEMANA[dow]}</span><b>${num}</b>${c?.n ? `<i class="ed-n">${c.n}</i>` : ""}</button>`;
  }).join("");
  const escolhido = el.querySelector(".ed-escolhido");
  escolhido.textContent = valor
    ? `${capitalizar(fmt.semana(valor))}, ${valor.slice(0, 4) === h.slice(0, 4) ? fmt.dataCurta(valor) : fmt.data(valor)}`
    : el.dataset.vazio || "Escolha um dia";
  escolhido.classList.toggle("vazio", !valor);
  el.querySelector(".ed-mes").textContent = meses(dias[0], dias[n - 1]);
  const limpar = el.querySelector("[data-ed-limpar]");
  if (limpar) limpar.hidden = !valor;
}

function escolher(el, dia) {
  const input = el.querySelector("input");
  if (input.value === dia) return;
  input.value = dia;
  desenhar(el);
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

document.addEventListener("click", (e) => {
  const b = e.target.closest(".ed button");
  if (!b || b.disabled) return;
  const el = b.closest(".ed");
  if (b.dataset.edDia) return escolher(el, b.dataset.edDia);
  if (b.dataset.edMover) el.dataset.ini = somar(el.dataset.ini, Number(b.dataset.edMover) * Number(el.dataset.n));
  else if ("edIr" in b.dataset) el.dataset.ini = inicio(el.querySelector("input").value, Number(el.dataset.n));
  else if ("edLimpar" in b.dataset) return escolher(el, "");
  desenhar(el);
});

document.addEventListener("keydown", (e) => {
  const b = e.target.closest?.(".ed-dia");
  if (!b || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
  e.preventDefault();
  const el = b.closest(".ed");
  const dia = somar(b.dataset.edDia, e.key === "ArrowLeft" ? -1 : 1);
  const { min, max, ini } = el.dataset, n = Number(el.dataset.n);
  if ((min && dia < min) || (max && dia > max)) return;
  if (dia < ini) el.dataset.ini = somar(ini, -n);
  else if (entre(ini, dia) >= n) el.dataset.ini = somar(ini, n);
  escolher(el, dia);
  el.querySelector(`[data-ed-dia="${dia}"]`).focus();
});
