// Aplicativos conectados (API pública, docs/api_publica.md): os outros aplicativos em que a pessoa entrou com o
// usuário e a senha do BI. Cada um vê a página Gestão em nome dela, só para ler. Desconectar apaga a chave dele, e o
// aplicativo pede o login de novo; trocar a senha desconecta todos. O nome do aplicativo vem de fora: sempre com esc().
import { api, esc, fmt, icone, toast } from "./util.js";

let dlg = null, lista = [];

export async function abrirAplicativos() {
  criar();
  dlg.innerHTML = `<div class="esqueleto" style="height:120px"></div>`;
  if (!dlg.open) dlg.showModal();
  try {
    lista = (await api("/api/aplicativos")).aplicativos;
  } catch (e) {
    dlg.close();
    return toast(e.message, "erro");
  }
  desenhar();
}

function criar() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo apps-janela";
  dlg.setAttribute("aria-labelledby", "apps-titulo");
  document.body.appendChild(dlg);
  dlg.addEventListener("click", aoClicar);
}

function itemHtml(a) {
  const uso = a.usada_em ? `último uso em ${fmt.dataHora(a.usada_em)}` : "ainda sem uso";
  return `<li class="apps-item">
    <div><b>${icone("elo")}${esc(a.aplicativo)}</b>
      <small>Conectado em ${fmt.dataHora(a.criada_em)} · ${uso} · vale até ${fmt.data(a.expira_em.slice(0, 10))}</small></div>
    <button class="btn icone perigo" type="button" data-desconectar="${a.id}" title="Desconectar" aria-label="Desconectar ${esc(a.aplicativo)}">${icone("lixeira")}</button>
  </li>`;
}

function desenhar() {
  dlg.innerHTML = `<div class="ag-hist-cab">
      <div><h2 id="apps-titulo">${icone("elo")}Aplicativos conectados</h2>
        <p class="sub">Aplicativos em que você entrou com o seu usuário do BI. Eles veem a página Gestão como você vê, só para ler.</p></div>
      <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar">${icone("x")}</button>
    </div>
    ${lista.length ? `<ul class="apps-lista">${lista.map(itemHtml).join("")}</ul>`
    : `<p class="apps-vazio">Nenhum aplicativo conectado.</p>`}
    <ul class="apps-notas">
      <li>${icone("cadeado")}<span>O BI não guarda a chave de cada aplicativo, só uma impressão digital dela. Desconectar apaga a chave, e o aplicativo pede o seu login de novo.</span></li>
      <li>${icone("chave")}<span>Trocar a sua senha desconecta todos os aplicativos. Cada conexão vale até a data indicada; depois, o aplicativo pede o seu login de novo.</span></li>
    </ul>`;
}

async function aoClicar(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if ("fechar" in b.dataset) return dlg.close();
  const id = Number(b.dataset.desconectar);
  if (!id) return;
  const a = lista.find((x) => x.id === id);
  if (!confirm(`Desconectar ${a ? a.aplicativo : "este aplicativo"}? Ele deixa de ver a Gestão e pede o seu login de novo.`)) return;
  b.disabled = true;
  try {
    lista = (await api("/api/aplicativos/desconectar", { json: { id } })).aplicativos;
    desenhar();
    toast("Aplicativo desconectado");
  } catch (err) {
    b.disabled = false;
    toast(err.message, "erro");
  }
}
