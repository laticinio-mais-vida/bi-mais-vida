// Avisos do painel, para quem tem a página Gestão (app.js liga): a cada minuto, e ao voltar para a aba, o painel
// pergunta /api/avisos.
// - Justificar o atraso: se há tarefa ou subtarefa vencida sem justificativa (bi/tarefas.py, pendencias), abre por cima
//   de qualquer página a janela que bloqueia o painel até tudo estar justificado; 24 horas depois de justificar, se
//   continuar atrasada, ela volta. A janela não fecha: o Esc não faz nada e, se o navegador fechar mesmo assim (o
//   Chromium fecha no segundo Esc), ela abre de novo. Cada item tem Enviar justificativa e Enviar e concluir (para quem
//   já terminou), e o aviso de pedir a prorrogação a quem criou a tarefa. O que estava sendo escrito na página de trás
//   fica como estava.
// - O sino (no topo, à esquerda do nome): o número de notificações não lidas (bi/notificacoes.py) e, clicando, o painel
//   com as mais recentes. Clicar numa abre a tarefa na Gestão (#/gestao?tarefa=…) e marca como lida.
import { abrirTarefaNaAgenda, atualizarTarefaAberta, recarregarAgenda } from "./agenda.js";
import { api, esc, fmt, icone, toast } from "./util.js";

const INTERVALO = 60000; // um minuto
// O ícone de cada tipo de notificação.
const ICONE_AVISO = { incluido: "pessoas", subtarefa_nova: "tarefa", prazo_mudou: "calendario", vence_em_breve: "relogio",
                      venceu: "alerta", concluida: "certo", justificativa: "conversa" };
// pendencias: o que falta justificar, como a última conferência trouxe; pedindo: uma conferência de cada vez; parado:
// sem a página Gestão (403), não confere mais.
const avisos = { pendencias: [], pedindo: false, parado: false };
let dlg = null, sino = null, painel = null;

const chave = (p) => `${p.tarefa}:${p.subtarefa || ""}`;
const dataCurta = (iso) => (iso.slice(0, 4) === String(new Date().getFullYear()) ? fmt.dataCurta(iso) : fmt.data(iso));

export function ligarAvisos() {
  ligarSino();
  conferir();
  setInterval(conferir, INTERVALO);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) conferir(); });
}

// Fora do ar (503) ou sem rede, fica quieto e tenta no próximo minuto; sem a Gestão (403), para.
async function conferir() {
  if (avisos.pedindo || avisos.parado) return;
  avisos.pedindo = true;
  try {
    const r = await api("/api/avisos");
    contarNaoLidas(r.nao_lidas);
    mostrarPendencias(r.pendencias);
  } catch (e) {
    if (e.status === 403) avisos.parado = true;
  } finally {
    avisos.pedindo = false;
  }
}

// ---------- o sino ----------
function ligarSino() {
  sino = document.getElementById("btn-sino");
  painel = document.getElementById("painel-avisos");
  sino.hidden = false;
  sino.addEventListener("click", () => (painel.hidden ? abrirPainel() : fecharPainel()));
  painel.addEventListener("click", aoClicarPainel);
  // fecha ao clicar fora (na captura: o botão do usuário para a propagação do clique), no Esc, ao rolar e ao redimensionar
  document.addEventListener("click", (e) => {
    if (!painel.hidden && !painel.contains(e.target) && !sino.contains(e.target)) fecharPainel();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !painel.hidden) { fecharPainel(); sino.focus(); } });
  window.addEventListener("resize", fecharPainel);
  window.addEventListener("scroll", fecharPainel, { passive: true });
}

function contarNaoLidas(n) {
  const el = document.getElementById("sino-n");
  el.hidden = !n;
  el.textContent = n > 9 ? "9+" : String(n);
  const rotulo = n ? `Notificações: ${n} não lida${n > 1 ? "s" : ""}` : "Notificações";
  sino.setAttribute("aria-label", rotulo);
  sino.title = rotulo;
}

// O painel abre embaixo do sino, como o menu do usuário, e pede a lista na hora.
async function abrirPainel() {
  const r = sino.getBoundingClientRect();
  painel.hidden = false;
  painel.style.top = `${r.bottom + 8}px`;
  painel.style.left = `${Math.max(8, Math.min(r.right - painel.offsetWidth, window.innerWidth - painel.offsetWidth - 8))}px`;
  sino.setAttribute("aria-expanded", "true");
  painel.innerHTML = `<div class="pa-cab"><b>Notificações</b></div><div class="esqueleto" style="height:120px;margin:10px"></div>`;
  try {
    desenharPainel(await api("/api/notificacoes"));
  } catch (e) {
    painel.innerHTML = `<div class="pa-cab"><b>Notificações</b></div><p class="pa-vazio">${icone("alerta")}${esc(e.message)}</p>`;
  }
}

function fecharPainel() {
  if (!painel || painel.hidden) return;
  painel.hidden = true;
  sino.setAttribute("aria-expanded", "false");
}

function desenharPainel(d) {
  if (painel.hidden) return; // fechou enquanto a lista chegava
  contarNaoLidas(d.nao_lidas);
  painel.innerHTML = `<div class="pa-cab"><b>Notificações</b>
      ${d.nao_lidas ? `<button type="button" class="ge-link" data-ler-todas>Marcar todas como lidas</button>` : ""}</div>
    ${d.itens.length ? `<ul class="pa-lista">${d.itens.map(itemAviso).join("")}</ul>`
      : `<p class="pa-vazio">${icone("sino")}Nenhuma notificação por enquanto.</p>`}`;
}

function itemAviso(n) {
  return `<li><button type="button" class="pa-item ${n.lida ? "" : "nova"}" data-aviso="${n.id}" data-tarefa="${n.tarefa || ""}">
    <span class="pa-ic pa-${n.tipo}">${icone(ICONE_AVISO[n.tipo] || "info")}</span>
    <span class="pa-txt"><span>${esc(n.texto)}</span><small>${quandoFoi(n.criada_em)}</small></span>
  </button></li>`;
}

// "agora", "há 5 min", "há 3 h" (hoje), "ontem às 14:03" ou "26/10 às 14:03".
function quandoFoi(iso) {
  const d = new Date(iso), min = Math.floor((Date.now() - d.getTime()) / 60000);
  const ontem = new Date();
  ontem.setDate(ontem.getDate() - 1);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  if (d.toDateString() === new Date().toDateString()) return `há ${Math.floor(min / 60)} h`;
  if (d.toDateString() === ontem.toDateString()) return `ontem às ${iso.slice(11, 16)}`;
  return `${dataCurta(iso.slice(0, 10))} às ${iso.slice(11, 16)}`;
}

async function aoClicarPainel(e) {
  const b = e.target.closest("button");
  if (!b) return;
  if ("lerTodas" in b.dataset) {
    if (await marcarLidas({ todas: true })) desenharPainel(await api("/api/notificacoes").catch(() => ({ nao_lidas: 0, itens: [] })));
    return;
  }
  if (!b.dataset.aviso) return;
  fecharPainel();
  if (b.classList.contains("nova")) marcarLidas({ ids: [Number(b.dataset.aviso)] });
  if (b.dataset.tarefa) irParaTarefa(Number(b.dataset.tarefa));
}

async function marcarLidas(json) {
  try {
    const r = await api("/api/notificacoes/lidas", { json });
    contarNaoLidas(r.nao_lidas);
    return true;
  } catch (e) {
    toast(e.message, "erro");
    return false;
  }
}

// A tarefa abre na Gestão (o link muda e ela abre a janela da tarefa); se o link já é esse, abre direto.
function irParaTarefa(id) {
  const destino = `#/gestao?tarefa=${id}`;
  if (location.hash === destino) abrirTarefaNaAgenda(id);
  else location.hash = destino;
}

// ---------- justificar o atraso ----------
// Abre (ou mantém aberta) a janela com o que falta justificar; só redesenha se a lista mudou, para não atrapalhar quem
// está escrevendo (e, redesenhando, o que já estava escrito fica).
function mostrarPendencias(lista) {
  const antes = avisos.pendencias.map(chave).join(",");
  avisos.pendencias = lista;
  if (!lista.length) {
    if (dlg?.open) dlg.close();
    return;
  }
  criarJanela();
  if (lista.map(chave).join(",") !== antes || !dlg.querySelector(".av-item")) desenhar();
  if (!dlg.open) {
    dlg.showModal();
    dlg.querySelector(".av-item textarea")?.focus();
  }
}

function criarJanela() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo av-bloqueio";
  dlg.setAttribute("aria-labelledby", "av-bloqueio-titulo");
  document.body.appendChild(dlg);
  dlg.addEventListener("cancel", (e) => e.preventDefault());
  dlg.addEventListener("close", () => { if (avisos.pendencias.length) dlg.showModal(); });
  dlg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && !b.disabled && ("avEnviar" in b.dataset || "avConcluir" in b.dataset)) enviar(b.closest(".av-item"), "avConcluir" in b.dataset);
  });
  dlg.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && e.target.matches(".av-item textarea")) {
      e.preventDefault();
      enviar(e.target.closest(".av-item"), false);
    }
  });
}

function desenhar() {
  const escritos = Object.fromEntries([...dlg.querySelectorAll(".av-item")].map((li) => [li.dataset.chave, li.querySelector("textarea").value]));
  const n = avisos.pendencias.length;
  dlg.innerHTML = `<div class="av-bloqueio-corpo">
    <h2 id="av-bloqueio-titulo">${icone("alerta")}Justifique o atraso para continuar</h2>
    <p class="sub">${n === 1 ? "Este item venceu sem ser concluído" : `Estes ${n} itens venceram sem ser concluídos`}. Até a
      justificativa, o painel fica bloqueado; se continuar atrasado, ela é pedida de novo a cada 24 horas.</p>
    <ul class="av-lista">${avisos.pendencias.map((p) => itemHtml(p, escritos[chave(p)] || "")).join("")}</ul>
  </div>`;
}

// "há 5 minutos", "há 3 horas", "há 2 dias": desde quando o prazo venceu.
function haQuanto(iso) {
  const min = Math.max(1, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (min < 60) return `há ${min} minuto${min > 1 ? "s" : ""}`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} hora${h > 1 ? "s" : ""}`;
  const d = Math.floor(h / 24);
  return `há ${d} dia${d > 1 ? "s" : ""}`;
}

// Um item a justificar: o que é, quando venceu, a última justificativa (quando o painel pede de novo), a caixa de texto,
// o aviso da prorrogação (para quem criou, editar a tarefa) e os botões.
function itemHtml(p, texto) {
  const prazo = `${dataCurta(p.prazo)}${p.hora ? ` às ${p.hora}` : ""}`;
  const u = p.ultima;
  const ultima = u ? `<div class="ag-just"><p>${icone("conversa")}<span>${esc(u.texto)}</span></p>
      <small><span>${u.minha ? "Sua última justificativa" : `Última justificativa${u.por ? ` · ${esc(u.por)}` : ""}`}, ${fmt.dataHora(u.criada_em)}${u.do_prazo ? "" : " (de um prazo anterior)"}</span></small></div>` : "";
  const nota = p.eu_criador ? "Você criou esta tarefa: para mudar o prazo, edite a tarefa depois de justificar."
    : `Caso queira prorrogamento do prazo, solicite ao criador da tarefa (${esc(p.criador.nome)}).`;
  return `<li class="av-item" data-chave="${chave(p)}">
    <div class="av-item-cab"><span class="chip ag-c-tarefa">${icone("tarefa")}${p.subtarefa ? "Subtarefa" : "Tarefa"}</span><b>${esc(p.titulo)}</b></div>
    <div class="ag-chips">${p.subtarefa ? `<span class="chip">Parte de: ${esc(p.tarefa_titulo)}</span>` : ""}
      <span class="chip ag-c-atrasada">${icone("alerta")}Venceu em ${prazo} · ${haQuanto(p.vence_em)}</span></div>
    ${ultima}
    <textarea rows="3" maxlength="2000" aria-label="Por que ${esc(p.titulo)} atrasou" placeholder="Por que atrasou? Quem participa da tarefa vê.">${esc(texto)}</textarea>
    <p class="av-nota">${icone("info")}<span>${nota}</span></p>
    <p class="form-erro" role="alert" hidden></p>
    <div class="ag-fb-acoes">
      <button class="btn" type="button" data-av-concluir title="Para quem já terminou: justifica e marca como concluída">${icone("visto")}Enviar e concluir</button>
      <button class="btn primario" type="button" data-av-enviar>${icone("enviar")}Enviar justificativa</button>
    </div>
  </li>`;
}

// Envia a justificativa do item (e conclui, se pedido). O erro aparece no próprio item; depois de um erro, a lista é
// conferida de novo (o prazo pode ter sido prorrogado, ou a tarefa excluída, nesse meio-tempo).
async function enviar(li, concluir) {
  const p = avisos.pendencias.find((x) => chave(x) === li.dataset.chave);
  const caixa = li.querySelector("textarea"), erro = li.querySelector(".form-erro");
  const mostrarErro = (m) => { erro.textContent = m.charAt(0).toUpperCase() + m.slice(1) + (m.endsWith(".") ? "" : "."); erro.hidden = false; };
  const texto = caixa.value.trim();
  if (!texto) {
    mostrarErro("escreva por que atrasou");
    return caixa.focus();
  }
  const faltam = concluir && !p.subtarefa ? p.abertas : 0;
  if (faltam && !confirm(`Concluir "${p.titulo}"? ${faltam === 1 ? "A subtarefa que falta passa" : `As ${faltam} subtarefas que faltam passam`} a contar como feita${faltam === 1 ? "" : "s"}.`)) return;
  const botoes = li.querySelectorAll("button");
  botoes.forEach((b) => { b.disabled = true; });
  erro.hidden = true;
  try {
    await api(`/api/agenda/${p.subtarefa ? "subtarefa" : "tarefa"}/justificar`,
      { json: { id: p.subtarefa || p.tarefa, justificativa: texto, concluir } });
  } catch (e) {
    botoes.forEach((b) => { b.disabled = false; });
    mostrarErro(e.message);
    return conferir();
  }
  avisos.pendencias = avisos.pendencias.filter((x) => x !== p);
  recarregarAgenda();
  atualizarTarefaAberta(p.tarefa);
  if (avisos.pendencias.length) {
    desenhar();
    dlg.querySelector(".av-item textarea")?.focus();
  } else {
    dlg.close();
    toast(concluir ? "Justificado e concluído; o painel está liberado" : "Justificativa enviada; o painel está liberado");
  }
}
