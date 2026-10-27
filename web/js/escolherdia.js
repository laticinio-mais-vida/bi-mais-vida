// Escolher um dia sem o calendário do navegador: o mês inteiro em quadradinhos como os da faixa da agenda (o dia da
// semana, o número, hoje em destaque e, quando a agenda conta, quantos itens o dia já tem), com setas para o mês de
// antes e o de depois. O mês fica numa linha só quando cabe; senão, em semanas de segunda a domingo, como a faixa da
// agenda no celular.
// O valor fica num input escondido (name ou data-campo), que avisa "change" a cada escolha: o formulário lê como lia o
// <input type="date">. Com o foco num dia, as setas do teclado andam a escolha (para cima e para baixo, uma semana).
// Clicar num dia (ou Enter nele) avisa também "dia-escolhido", mesmo que seja o dia que já estava: as setas só andam,
// o clique confirma.
// - campoDia({...}): o HTML do campo; prepararDias(raiz) desenha os campos novos depois que o HTML entra na página.
// - limitesDoDia(input, {min, max}): os dias de fora ficam bloqueados. focarDia(input): o foco vai para o dia escolhido.
// - contarDias(fn): fn(dia) → {n, classe} (os itens do dia; classe tem, feita ou atrasada) ou null; redesenharDias()
//   refaz todos os campos depois que a contagem muda.
import { MESES, esc, fmt, icone } from "./util.js";

const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const MIN_LINHA = 25; // a largura mínima de um quadradinho para o mês caber numa linha só
const PASSOS = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
let contador = () => null;

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const data = (dia) => new Date(`${dia}T12:00`);
const hoje = () => iso(new Date());
const capitalizar = (t) => t.charAt(0).toUpperCase() + t.slice(1);
function somar(dia, n) {
  const d = data(dia);
  d.setDate(d.getDate() + n);
  return iso(d);
}
function somarMes(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  return iso(new Date(a, m - 1 + n, 1)).slice(0, 7);
}

export function contarDias(fn) {
  contador = fn;
}

// nome (name="…") ou campo (data-campo="…"): onde o valor fica. rotulo: o nome do grupo de dias, para leitor de tela.
// vazio: o texto de quando não há dia, só nos campos opcionais (aparece também o botão que limpa). maxDica: por que os
// dias depois de max ficam bloqueados. contar: false nos campos de outra pessoa (a contagem é a da minha agenda).
export function campoDia({ nome, campo, valor = "", min = "", max = "", rotulo, vazio = "", maxDica = "", contar = true }) {
  return `<div class="ed" data-min="${min}" data-max="${max}" data-vazio="${esc(vazio)}" data-max-dica="${esc(maxDica)}" ${contar ? "" : "data-sem-contagem"}>
    <input type="hidden" ${nome ? `name="${nome}"` : `data-campo="${campo}"`} value="${valor || ""}">
    <div class="ed-cab">
      <button type="button" class="ed-seta" data-ed-mover="-1" title="Mês anterior" aria-label="Mês anterior">${icone("anterior")}</button>
      <b class="ed-mes" aria-live="polite"></b>
      <button type="button" class="ed-seta" data-ed-mover="1" title="Próximo mês" aria-label="Próximo mês">${icone("proximo")}</button>
      <span class="ed-lado">
        <button type="button" class="ed-escolhido" data-ed-ir title="Mostrar o mês do dia escolhido"></button>
        ${vazio ? `<button type="button" class="ge-link ed-limpar" data-ed-limpar>Limpar</button>` : ""}
      </span>
    </div>
    <div class="ed-dias" role="group" aria-label="${esc(rotulo)}"></div>
  </div>`;
}

// Numa linha só se os quadradinhos do mês cabem; senão, em semanas (escondido, ainda sem largura: fica como está).
function ajustarModo(el) {
  const dias = el.querySelector(".ed-dias"), w = dias.clientWidth;
  if (w) el.classList.toggle("grade", w < dias.children.length * MIN_LINHA);
}

const observador = new ResizeObserver((entradas) => {
  for (const { target } of entradas) {
    const el = target.closest(".ed");
    if (!el?.isConnected) observador.unobserve(target);
    else ajustarModo(el);
  }
});

export function prepararDias(raiz) {
  raiz.querySelectorAll(".ed:not([data-mes])").forEach((el) => {
    desenhar(el);
    observador.observe(el.querySelector(".ed-dias"));
  });
}

export function redesenharDias() {
  document.querySelectorAll(".ed[data-mes]").forEach(desenhar);
}

export function limitesDoDia(input, { min, max } = {}) {
  const el = input.closest(".ed");
  if (min !== undefined) el.dataset.min = min || "";
  if (max !== undefined) el.dataset.max = max || "";
  if (el.dataset.mes) desenhar(el);
}

export function focarDia(input) {
  const el = input.closest(".ed");
  el.dataset.mes = (input.value || hoje()).slice(0, 7);
  desenhar(el);
  (el.querySelector(".ed-dia.escolhido") || el.querySelector(".ed-dia:not(:disabled)"))?.focus();
}

function desenhar(el) {
  const input = el.querySelector("input");
  const valor = input.value, h = hoje();
  const { min, max } = el.dataset;
  const mes = el.dataset.mes || (valor || h).slice(0, 7);
  el.dataset.mes = mes;
  const [ano, m] = mes.split("-").map(Number);
  const dias = Array.from({ length: new Date(ano, m, 0).getDate() }, (_, k) => `${mes}-${String(k + 1).padStart(2, "0")}`);
  el.querySelector(".ed-dias").innerHTML = dias.map((d, k) => {
    const dow = data(d).getDay(), num = k + 1;
    const fora = (min && d < min) || (max && d > max);
    const c = "semContagem" in el.dataset ? null : contador(d);
    const classes = ["ed-dia", c?.classe || "", dow === 0 || dow === 6 ? "fds" : "", d === h ? "hoje" : "",
      d === valor ? "escolhido" : "", fora ? "fora" : ""].filter(Boolean).join(" ");
    const nome = `${capitalizar(fmt.semana(d))}, ${num} de ${MESES[m - 1]}${d === h ? " (hoje)" : ""}` +
      (c?.n ? `: ${c.n} ${c.n === 1 ? "item" : "itens"} na agenda` : "");
    const dica = !fora ? nome : min && d < min ? `Antes de ${fmt.dataCurta(min)}`
      : `${el.dataset.maxDica || "Depois do limite"} (${fmt.dataCurta(max)})`;
    // a coluna do dia 1 na vista em semanas (segunda = 1)
    const col = k === 0 ? ` style="--col:${((dow + 6) % 7) + 1}"` : "";
    return `<button type="button" class="${classes}"${col} data-ed-dia="${d}" ${fora ? "disabled" : ""} aria-pressed="${d === valor}"
      aria-label="${esc(nome)}" title="${esc(dica)}"><span class="ed-sem">${SEMANA[dow]}</span><b>${num}</b>${c?.n ? `<i class="ed-n">${c.n}</i>` : ""}</button>`;
  }).join("");
  el.querySelector(".ed-mes").textContent = `${capitalizar(MESES[m - 1])} de ${ano}`;
  const escolhido = el.querySelector(".ed-escolhido");
  escolhido.textContent = valor
    ? `${capitalizar(fmt.semana(valor))}, ${valor.slice(0, 4) === h.slice(0, 4) ? fmt.dataCurta(valor) : fmt.data(valor)}`
    : el.dataset.vazio || "Escolha um dia";
  escolhido.classList.toggle("vazio", !valor);
  const limpar = el.querySelector("[data-ed-limpar]");
  if (limpar) limpar.hidden = !valor;
  ajustarModo(el);
}

function escolher(el, dia) {
  const input = el.querySelector("input");
  if (input.value === dia) return;
  input.value = dia;
  if (dia) el.dataset.mes = dia.slice(0, 7);
  desenhar(el);
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

document.addEventListener("click", (e) => {
  const b = e.target.closest(".ed button");
  if (!b || b.disabled) return;
  const el = b.closest(".ed");
  if (b.dataset.edDia) {
    escolher(el, b.dataset.edDia);
    return el.querySelector("input").dispatchEvent(new Event("dia-escolhido", { bubbles: true }));
  }
  if ("edLimpar" in b.dataset) return escolher(el, "");
  if (b.dataset.edMover) el.dataset.mes = somarMes(el.dataset.mes, Number(b.dataset.edMover));
  else if ("edIr" in b.dataset) el.dataset.mes = (el.querySelector("input").value || hoje()).slice(0, 7);
  desenhar(el);
});

document.addEventListener("keydown", (e) => {
  const b = e.target.closest?.(".ed-dia");
  if (!b || !(e.key in PASSOS)) return;
  e.preventDefault();
  const el = b.closest(".ed");
  const dia = somar(b.dataset.edDia, PASSOS[e.key]);
  const { min, max } = el.dataset;
  if ((min && dia < min) || (max && dia > max)) return;
  escolher(el, dia);
  el.querySelector(`[data-ed-dia="${dia}"]`).focus();
});
