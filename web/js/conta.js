// Menu do usuário no topo: quem está conectado, trocar a própria senha e sair.
import { api, esc, toast } from "./util.js";

export const PAPEL = { admin: "Administrador", visualizador: "Visualizador" };

export function iniciais(nome) {
  const partes = String(nome || "?").trim().split(/\s+/);
  return ((partes[0]?.[0] || "") + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
}

export function mostrarUsuario(u) {
  document.getElementById("nome-usuario").textContent = u.nome.split(/\s+/)[0];
  document.getElementById("avatar-usuario").textContent = iniciais(u.nome);
  document.getElementById("menu-avatar").textContent = iniciais(u.nome);
  document.getElementById("menu-nome").textContent = u.nome;
  document.getElementById("menu-papel").innerHTML = `${esc(PAPEL[u.papel])} · ${esc(u.login)}`;
  document.querySelectorAll("[data-admin]").forEach((el) => { el.hidden = u.papel !== "admin"; });
}

export function ligarMenuUsuario() {
  const btn = document.getElementById("btn-usuario");
  const menu = document.getElementById("menu-usuario");
  const fechar = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  const abrir = () => {
    const r = btn.getBoundingClientRect();
    menu.hidden = false;
    menu.style.top = `${r.bottom + 8}px`;
    menu.style.left = `${Math.max(8, Math.min(r.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8))}px`;
    btn.setAttribute("aria-expanded", "true");
    menu.querySelector("button").focus();
  };
  btn.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden ? abrir() : fechar(); });
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) fechar(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { fechar(); btn.focus(); } });
  window.addEventListener("resize", fechar);
  window.addEventListener("scroll", fechar, { passive: true });

  document.getElementById("btn-sair").addEventListener("click", async () => {
    fechar();
    try { await api("/api/sair", { method: "POST" }); } catch { /* sai mesmo assim */ }
    location.replace("/login");
  });
  document.getElementById("btn-trocar-senha").addEventListener("click", () => { fechar(); trocarSenha(); });
}

function trocarSenha() {
  const dlg = document.getElementById("dlg-senha");
  const form = document.getElementById("form-senha");
  const erro = form.querySelector(".form-erro");
  form.reset();
  erro.hidden = true;
  dlg.showModal();
  form.atual.focus();
  document.getElementById("dlg-senha-cancelar").onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const mostrar = (m) => { erro.textContent = m; erro.hidden = false; };
    if (!form.atual.value || !form.nova.value) return mostrar("Preencha a senha atual e a nova.");
    if (form.nova.value !== form.nova2.value) return mostrar("As duas senhas novas não são iguais.");
    const botao = form.querySelector("[type=submit]");
    botao.disabled = true;
    try {
      await api("/api/minha-senha", { json: { atual: form.atual.value, nova: form.nova.value } });
      dlg.close();
      toast("Senha trocada");
    } catch (err) {
      mostrar(err.message.charAt(0).toUpperCase() + err.message.slice(1) + ".");
    } finally {
      botao.disabled = false;
    }
  };
}
