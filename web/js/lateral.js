// Barra lateral com as páginas do painel. Recolhida mostra só os ícones (o nome aparece ao passar o mouse);
// expandida mostra os nomes. Lembra a escolha neste navegador. No celular vira uma gaveta que abre pelo
// botão de menu do topo e fecha ao escolher a página, tocar fora ou apertar Esc.
import { guardar, ler } from "./util.js";

const CHAVE = "mv-lateral";
const celular = () => window.matchMedia("(max-width: 860px)").matches;

export function ligarLateral() {
  const corpo = document.body;
  const alternar = document.getElementById("btn-lateral");
  const menu = document.getElementById("btn-menu");
  const fundo = document.getElementById("lateral-fundo");

  const expandir = (aberta) => {
    corpo.classList.toggle("lateral-aberta", aberta);
    alternar.setAttribute("aria-expanded", String(aberta));
    alternar.setAttribute("aria-label", aberta ? "Recolher o menu" : "Expandir o menu");
    alternar.title = aberta ? "Recolher o menu" : "Expandir o menu";
  };
  const abrirGaveta = () => {
    corpo.classList.add("lateral-gaveta");
    fundo.hidden = false;
    menu.setAttribute("aria-expanded", "true");
    document.querySelector(".lateral-item:not([hidden])")?.focus();
  };
  const fecharGaveta = () => {
    if (!corpo.classList.contains("lateral-gaveta")) return;
    corpo.classList.remove("lateral-gaveta");
    fundo.hidden = true;
    menu.setAttribute("aria-expanded", "false");
  };

  // primeira visita: aberta em telas largas, recolhida nas menores
  expandir(ler(CHAVE, window.innerWidth >= 1280));
  requestAnimationFrame(() => corpo.classList.add("lateral-pronta")); // sem animação ao carregar a página

  alternar.addEventListener("click", () => {
    if (celular()) return fecharGaveta();
    const aberta = !corpo.classList.contains("lateral-aberta");
    expandir(aberta);
    guardar(CHAVE, aberta);
  });
  menu.addEventListener("click", abrirGaveta);
  fundo.addEventListener("click", fecharGaveta);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && corpo.classList.contains("lateral-gaveta")) { fecharGaveta(); menu.focus(); }
  });
  document.querySelectorAll(".lateral-item").forEach((a) => a.addEventListener("click", fecharGaveta));
  window.matchMedia("(max-width: 860px)").addEventListener("change", fecharGaveta);
}

export function marcarPagina(rota) {
  document.querySelectorAll(".lateral-item").forEach((a) => {
    const ativa = a.dataset.rota === rota;
    a.classList.toggle("ativa", ativa);
    if (ativa) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

// Esconde as páginas que o usuário não pode abrir (o servidor também barra os dados delas).
export function mostrarPaginas(permitidas) {
  document.querySelectorAll(".lateral-item[data-pagina]").forEach((a) => { a.hidden = !permitidas.includes(a.dataset.pagina); });
}
