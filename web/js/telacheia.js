// Tela cheia por cartão (como o "modo de foco / tela cheia" do Power BI web).
// O cartão é levado para uma camada que cobre a tela e, quando o navegador permite, entra em tela cheia de
// verdade. Indicadores e tabelas são ampliados para caber; o gráfico de linha é redesenhado maior.
// Esc ou o mesmo botão voltam o cartão para o lugar dele.
import { icone, animarContadores, animarEntradas } from "./util.js";

let ativo = null;

export function ligarTelaCheia(raiz) {
  raiz.querySelectorAll(".cartao").forEach((card) => {
    if (card.querySelector(":scope > .btn-tela-cheia")) return;
    card.classList.add("com-tela-cheia");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn-tela-cheia";
    b.title = "Tela cheia";
    b.setAttribute("aria-label", "Mostrar em tela cheia");
    b.innerHTML = icone("expandir");
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      if (ativo && ativo.card === card) sairTelaCheia();
      else entrar(card);
    });
    card.appendChild(b);
  });
}

export function sairTelaCheia(sairDoNavegador = true) {
  if (!ativo) return;
  const { card, marcador, camada } = ativo;
  ativo = null;
  window.removeEventListener("resize", ajustar);
  document.removeEventListener("keydown", tecla);
  if (sairDoNavegador && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  card.classList.remove("em-tela-cheia");
  card.style.zoom = "";
  card.style.width = "";
  if (marcador.parentNode) marcador.replaceWith(card);
  ["tooltip", "toasts"].forEach((id) => document.body.appendChild(document.getElementById(id)));
  document.getElementById("tooltip").hidden = true;
  camada.remove();
  document.body.classList.remove("sem-rolagem");
  const btn = card.querySelector(":scope > .btn-tela-cheia");
  if (btn) {
    btn.innerHTML = icone("expandir");
    btn.title = "Tela cheia";
    btn.setAttribute("aria-label", "Mostrar em tela cheia");
    btn.focus({ preventScroll: true });
  }
  const g = card.querySelector(".grafico");
  if (g && g._redesenhar) requestAnimationFrame(() => g._redesenhar());
}

function entrar(card) {
  if (ativo) sairTelaCheia(false);
  const r = card.getBoundingClientRect();
  const camada = document.createElement("div");
  camada.className = "tela-cheia";
  // Pedir a tela cheia ainda dentro do clique (o navegador só permite assim); se não der, fica a camada.
  if (camada.requestFullscreen) {
    document.body.appendChild(camada);
    camada.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
  } else {
    document.body.appendChild(camada);
  }
  camada.innerHTML = `<div class="tc-dica">${icone("recolher")} Esc para sair da tela cheia</div><div class="tc-palco"></div>`;
  const marcador = document.createComment("lugar do cartão em tela cheia");
  card.before(marcador);
  camada.querySelector(".tc-palco").appendChild(card);
  ["tooltip", "toasts"].forEach((id) => camada.appendChild(document.getElementById(id)));
  card.classList.add("em-tela-cheia");
  const btn = card.querySelector(":scope > .btn-tela-cheia");
  btn.innerHTML = icone("recolher");
  btn.title = "Sair da tela cheia (Esc)";
  btn.setAttribute("aria-label", "Sair da tela cheia");
  document.body.classList.add("sem-rolagem");
  ativo = {
    card, marcador, camada, largura: r.width,
    modo: card.querySelector(".grafico") ? "grafico" : card.querySelector(".tabela-rolagem") ? "tabela" : "ajustar",
  };
  window.addEventListener("resize", ajustar);
  document.addEventListener("keydown", tecla);
  repetirAnimacoes(card);
  ajustar();
}

function tecla(e) {
  if (e.key === "Escape") sairTelaCheia();
}

document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement && ativo) sairTelaCheia(false);
});

function ajustar() {
  if (!ativo) return;
  const { card, camada, modo } = ativo;
  const W = camada.clientWidth - 96, H = camada.clientHeight - 120;
  card.style.zoom = "";
  if (modo === "grafico") {
    card.style.width = `${Math.min(W, 1800)}px`;
    const g = card.querySelector(".grafico");
    if (g && g._redesenhar) g._redesenhar();
    return;
  }
  if (modo === "tabela") {
    // tabelas: largura do conteúdo, ampliadas (ou reduzidas) para caber na largura da tela
    card.style.width = "max-content";
    const z = Math.max(0.5, Math.min(W / card.offsetWidth, 1.9));
    card.style.zoom = String(z);
    return;
  }
  card.style.width = `${ativo.largura}px`;
  const z = Math.min(W / card.offsetWidth, H / card.offsetHeight, 2.6);
  card.style.zoom = String(Math.max(1, z));
}

function repetirAnimacoes(card) {
  card.querySelectorAll("[data-contar]").forEach((el) => { el.dataset.valor = 0; });
  const animados = card.querySelectorAll("[data-largura], [data-offset]");
  animados.forEach((el) => {
    el.style.transition = "none";
    if (el.dataset.largura) el.style.width = "0";
    if (el.dataset.offset) el.style.strokeDashoffset = el.getAttribute("stroke-dasharray");
  });
  void card.offsetWidth;
  animados.forEach((el) => { el.style.transition = ""; });
  animarContadores(card);
  animarEntradas(card);
  const g = card.querySelector(".grafico");
  if (g) delete g.dataset.desenhado;
}
