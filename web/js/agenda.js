// Página Agenda: as atividades de cada pessoa (só ela vê), na faixa de dias do mês (a mesma do "Ritmo do mês" da
// página Metas), com o dia de hoje num quadrado maior. Clicar num dia amplia o painel com as atividades dele:
// concluir (com o feedback, obrigatório quando a atividade pede), editar o feedback, desfazer e, nas que se repetem,
// o histórico de tudo o que foi feito. À direita, o formulário da atividade nova (única, diária, semanal, mensal ou a
// cada N dias), que também edita uma atividade. Em que dias cada atividade acontece é conta do servidor (bi/agenda.py).
import { MESES, api, esc, fmt, icone, ligarTooltips, linhaTT, toast } from "./util.js";

const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const DIAS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]]; // date.isoweekday()
const NOME_DIA = ["", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];
const REPETICOES = [["nenhuma", "Única"], ["diaria", "Diária"], ["semanal", "Semanal"], ["mensal", "Mensal"], ["intervalo", "A cada N dias"]];
const DESCARTAR_FB = "Descartar o feedback que você estava escrevendo?";

let raiz = null, dlg = null;
const estado = { mes: null, dados: null, aberto: null, editando: null, concluindo: null, form: null, formInicial: null, pedido: 0 };

// ---------- apoio ----------
const capitalizar = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);
const mesDe = (iso) => iso.slice(0, 7);
const hora = (iso) => (iso ? iso.slice(11, 16) : "");
const diaDaSemana = (iso) => new Date(`${iso}T12:00`).getDay() || 7; // 1 = segunda ... 7 = domingo
const atividade = (id) => estado.dados.atividades.find((a) => a.id === id);

function hojeLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function somarMes(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  const d = new Date(a, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function listaE(itens) {
  return itens.length < 2 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`;
}
// "26/10" no ano de hoje; "26/10/2025" em outro ano.
function dataCurta(iso) {
  return iso.slice(0, 4) === (estado.dados?.hoje || hojeLocal()).slice(0, 4) ? fmt.dataCurta(iso) : fmt.data(iso);
}
// Quando foi concluída: "às 14:03" no próprio dia, "em 28/10 às 09:10" depois.
function quando(iso, dia) {
  return iso.slice(0, 10) === dia ? `às ${hora(iso)}` : `em ${dataCurta(iso.slice(0, 10))} às ${hora(iso)}`;
}

// "Só neste dia", "Todo dia útil (ES)", "Toda segunda e quinta", "Todo dia 5", "A cada 15 dias" (e "até 30/11").
function textoRepeticao(a) {
  let t;
  if (a.repeticao === "nenhuma") t = "Só neste dia";
  else if (a.repeticao === "diaria") t = a.so_dias_uteis ? `Todo dia útil (${a.regiao})` : "Todo dia";
  else if (a.repeticao === "semanal") {
    const nomes = listaE(a.dias_semana.map((d) => NOME_DIA[d]));
    if (a.dias_semana.length === 7) t = "Todo dia da semana";
    else if (a.dias_semana.every((d) => d <= 5)) t = `Toda ${nomes}`;
    else if (a.dias_semana.every((d) => d >= 6)) t = `Todo ${nomes}`;
    else t = `Semanal: ${nomes}`;
  } else if (a.repeticao === "mensal") t = `Todo dia ${a.dia_mes}${a.dia_mes > 28 ? " (ou o último do mês)" : ""}`;
  else t = `A cada ${a.intervalo} dias`;
  return a.fim ? `${t}, até ${dataCurta(a.fim)}` : t;
}

// ---------- montagem ----------
export function agendaTemAlteracoes() {
  return !!raiz?.isConnected && (formMudou() || feedbackEscrito());
}

export function montarAgenda(el) {
  el.innerHTML = `<div class="ag-layout" id="ag-raiz">
    <section class="cartao ag-cal entra" style="--i:0">
      <div class="cartao-cab">
        <div><h2>${icone("calendario")}<span id="ag-titulo">Agenda</span></h2><p class="sub" id="ag-resumo">&nbsp;</p></div>
        <div class="ag-nav">
          <button class="btn icone" type="button" data-mes="-1" title="Mês anterior" aria-label="Mês anterior">${icone("voltar")}</button>
          <button class="btn" type="button" data-hoje>Hoje</button>
          <button class="btn icone" type="button" data-mes="1" title="Próximo mês" aria-label="Próximo mês">${icone("seta")}</button>
        </div>
      </div>
      <div id="ag-faixa"><div class="esqueleto" style="height:80px"></div></div>
      <div id="ag-dia"></div>
    </section>
    <aside class="cartao ag-nova entra" style="--i:1" id="ag-nova" aria-label="Atividade nova"></aside>
  </div>`;
  raiz = el.querySelector("#ag-raiz");
  raiz.addEventListener("click", aoClicar);
  raiz.addEventListener("change", aoMudar);
  raiz.addEventListener("keydown", aoTeclar);
  Object.assign(estado, { mes: null, dados: null, aberto: null, editando: null, concluindo: null });
  desenharForm();
  carregar();
}

async function carregar(mes = estado.mes, { aberto } = {}) {
  const pedido = ++estado.pedido;
  const cal = raiz.querySelector(".ag-cal");
  const mesmoMes = !!estado.dados && estado.dados.mes === (mes || estado.mes);
  if (estado.dados) cal.classList.add("recarregando");
  try {
    const d = await api(`/api/agenda${mes ? `?mes=${mes}` : ""}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    estado.mes = d.mes;
    if (aberto && mesDe(aberto) === d.mes) estado.aberto = aberto;
    else if (!estado.aberto || mesDe(estado.aberto) !== d.mes) estado.aberto = mesDe(d.hoje) === d.mes ? d.hoje : `${d.mes}-01`;
    if (estado.concluindo && !d.dias.some((x) => x.data === estado.concluindo.dia)) estado.concluindo = null;
    desenharFaixa(mesmoMes);
    desenharDia(!mesmoMes);
    if (!estado.editando && !formMudou()) definirDiaDoForm(estado.aberto);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (!estado.dados) raiz.querySelector("#ag-faixa").innerHTML = `<div class="vazio">${icone("alerta")}<p>${esc(e.message)}</p></div>`;
    toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) cal.classList.remove("recarregando");
  }
}

// ---------- faixa de dias ----------
function desenharFaixa(quieta) {
  const d = estado.dados;
  const [ano, m] = d.mes.split("-").map(Number);
  raiz.querySelector("#ag-titulo").textContent = `${capitalizar(MESES[m - 1])} de ${ano}`;
  let total = 0, feitas = 0, atrasadas = 0;
  for (const x of d.dias) {
    total += x.itens.length;
    feitas += x.itens.filter((i) => i.feita).length;
    if (x.data < d.hoje) atrasadas += x.itens.filter((i) => !i.feita).length;
  }
  raiz.querySelector("#ag-resumo").textContent = total
    ? `${fmt.num(total)} ${total === 1 ? "atividade" : "atividades"} no mês · ${fmt.num(feitas)} ${feitas === 1 ? "concluída" : "concluídas"}${atrasadas ? ` · ${fmt.num(atrasadas)} sem concluir` : ""}`
    : "Nenhuma atividade neste mês";
  raiz.querySelector("#ag-faixa").innerHTML = `<div class="faixa-dias ag-faixa ${quieta ? "quieta" : ""}" role="group" aria-label="Dias de ${MESES[m - 1]}">
    ${d.dias.map((x, n) => {
      const dia = Number(x.data.slice(8));
      const dow = new Date(x.data + "T12:00").getDay();
      const pendentes = x.itens.filter((i) => !i.feita).length;
      const hoje = x.data === d.hoje;
      const classes = ["dia", x.itens.length ? "tem" : "", x.itens.length && !pendentes ? "feita" : "",
        pendentes && x.data < d.hoje ? "atrasada" : "", hoje ? "hoje" : "", x.data === estado.aberto ? "aberto" : "",
        dow === 0 || dow === 6 ? "ag-fds" : ""].filter(Boolean).join(" ");
      const col = n === 0 ? `;--col:${((dow + 6) % 7) + 1}` : "";
      const tt = `<div class='tt-t'>${fmt.dataCurta(x.data)} · ${fmt.semana(x.data)}${hoje ? " · hoje" : ""}</div>` +
        (x.itens.length ? linhaTT("Atividades", fmt.num(x.itens.length)) + linhaTT("Concluídas", fmt.num(x.itens.length - pendentes))
          : linhaTT("Atividades", "nenhuma"));
      const marca = pendentes ? `<i class="ag-n">${pendentes}</i>` : x.itens.length ? `<i class="ag-n ok">${icone("visto")}</i>` : "";
      const rotulo = `${dia} de ${MESES[m - 1]}${hoje ? ", hoje" : ""}: ${x.itens.length ? `${x.itens.length} atividades, ${pendentes} pendentes` : "nenhuma atividade"}`;
      return `<button type="button" class="${classes}" style="--i:${n}${col}" data-dia="${x.data}" data-tt="${esc(tt)}"
        aria-pressed="${x.data === estado.aberto}" aria-label="${esc(rotulo)}">${marca}${dia}<span class="sem">${SEMANA[dow]}</span></button>`;
    }).join("")}
  </div>
  <div class="ag-legenda" aria-hidden="true"><span><i></i>Livre</span><span><i class="tem"></i>Com atividade</span>
    <span><i class="feita"></i>Tudo concluído</span><span><i class="atrasada"></i>Ficou sem concluir</span></div>`;
  ligarTooltips(raiz.querySelector("#ag-faixa"));
}

function abrirDia(dia) {
  if (dia === estado.aberto) return;
  if (feedbackEscrito() && !confirm(DESCARTAR_FB)) return;
  estado.aberto = dia;
  estado.concluindo = null;
  raiz.querySelectorAll(".ag-faixa .dia").forEach((b) => {
    const sim = b.dataset.dia === dia;
    b.classList.toggle("aberto", sim);
    b.setAttribute("aria-pressed", String(sim));
  });
  desenharDia(true);
  if (!estado.editando && !formMudou()) definirDiaDoForm(dia);
}

// ---------- o dia aberto ----------
function desenharDia(animar) {
  const d = estado.dados;
  const x = d.dias.find((y) => y.data === estado.aberto);
  const el = raiz.querySelector("#ag-dia");
  if (!x) { el.innerHTML = ""; return; }
  const futuro = x.data > d.hoje;
  const pendentes = x.itens.filter((i) => !i.feita).length;
  const situacao = !x.itens.length ? "" : !pendentes ? "tudo concluído"
    : futuro ? `${pendentes} ${pendentes === 1 ? "atividade" : "atividades"}`
    : `${pendentes} ${pendentes === 1 ? "pendente" : "pendentes"} de ${x.itens.length}`;
  el.innerHTML = `<div class="ag-dia ${animar ? "abre" : ""}">
    <div class="ag-dia-cab">
      <div><h3>${capitalizar(fmt.semana(x.data))}, ${dataCurta(x.data)}${x.data === d.hoje ? ` <span class="chip laranja">hoje</span>` : ""}</h3>
        ${situacao ? `<small>${situacao}</small>` : ""}</div>
      <button class="btn" type="button" data-novo-no-dia>${icone("mais")}Atividade neste dia</button>
    </div>
    ${x.itens.length ? `<ul class="ag-itens">${x.itens.map((i, n) => itemHtml(i, x.data, futuro, n)).join("")}</ul>`
      : `<p class="ag-vazio">${icone("calendario")}Nada marcado para este dia.</p>`}
  </div>`;
  el.querySelector(".ag-fb textarea")?.focus();
}

function itemHtml(i, dia, futuro, n) {
  const a = atividade(i.atividade);
  const repete = a.repeticao !== "nenhuma";
  const escrevendo = estado.concluindo?.atividade === a.id && estado.concluindo?.dia === dia;
  const dica = futuro ? "Este dia ainda não chegou" : i.feita ? "Desfazer a conclusão" : "Marcar como concluída";
  const encerravel = repete && a.inicio <= estado.dados.hoje && (!a.fim || a.fim > estado.dados.hoje);
  let rodape = "";
  if (escrevendo) {
    rodape = `<div class="ag-fb">
      <textarea rows="2" maxlength="2000" aria-label="Feedback de ${esc(a.titulo)}"
        placeholder="${a.exige_feedback ? "Conte como foi (obrigatório para concluir)" : "Conte como foi (opcional)"}">${esc(i.feedback || "")}</textarea>
      <div class="ag-fb-acoes"><button class="btn" type="button" data-cancelar-fb>Cancelar</button>
        <button class="btn primario" type="button" data-confirmar>${icone("visto")}${i.feita ? "Salvar feedback" : "Concluir"}</button></div>
    </div>`;
  } else if (i.feita) {
    rodape = `<div class="ag-feito">
      ${i.feedback ? `<p>${icone("conversa")}<span>${esc(i.feedback)}</span></p>` : ""}
      <small><span>Concluída ${quando(i.concluida_em, dia)}</span>
        <button type="button" class="ge-link" data-editar-fb>${i.feedback ? "Editar feedback" : "Adicionar feedback"}</button>
        <button type="button" class="ge-link" data-desfazer>Desfazer</button></small>
    </div>`;
  }
  return `<li class="ag-item ${i.feita ? "feita" : ""}" style="--i:${n}" data-atividade="${a.id}" data-dia="${dia}">
    <button type="button" class="ag-check ${i.feita ? "feita" : ""}" data-check ${futuro ? "disabled" : ""}
      aria-pressed="${i.feita}" title="${dica}" aria-label="${dica}: ${esc(a.titulo)}">${icone("visto")}</button>
    <div class="ag-item-t">
      <b>${esc(a.titulo)}</b>
      ${a.descricao ? `<p>${esc(a.descricao)}</p>` : ""}
      <div class="ag-chips"><span class="chip">${icone(repete ? "atualizar" : "calendario")}${esc(textoRepeticao(a))}</span>
        ${a.exige_feedback ? `<span class="chip laranja">${icone("conversa")}Pede feedback</span>` : ""}</div>
      ${rodape}
    </div>
    <div class="ag-item-acoes">
      ${repete ? `<button type="button" data-historico title="Histórico" aria-label="Histórico de ${esc(a.titulo)}">${icone("restaurar")}</button>` : ""}
      <button type="button" data-editar title="Editar a atividade" aria-label="Editar ${esc(a.titulo)}">${icone("lapis")}</button>
      ${encerravel ? `<button type="button" data-encerrar title="Parar de repetir depois de hoje" aria-label="Encerrar ${esc(a.titulo)}">${icone("bandeira")}</button>` : ""}
      <button type="button" class="perigo" data-excluir title="Excluir a atividade" aria-label="Excluir ${esc(a.titulo)}">${icone("lixeira")}</button>
    </div>
  </li>`;
}

const feedbackEscrito = () => !!raiz?.querySelector(".ag-fb textarea")?.value.trim();

// ---------- ações ----------
async function aoClicar(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if (b.dataset.dia && b.closest(".ag-faixa")) return abrirDia(b.dataset.dia);
  if (b.dataset.mes || "hoje" in b.dataset) {
    if (feedbackEscrito() && !confirm(DESCARTAR_FB)) return;
    estado.concluindo = null;
    const hoje = estado.dados?.hoje || hojeLocal();
    return "hoje" in b.dataset ? carregar(mesDe(hoje), { aberto: hoje }) : carregar(somarMes(estado.mes, Number(b.dataset.mes)));
  }
  if ("novoNoDia" in b.dataset) {
    if (estado.editando) {
      if (formMudou() && !confirm("Descartar as mudanças nesta atividade?")) return;
      cancelarEdicao();
    }
    definirDiaDoForm(estado.aberto);
    raiz.querySelector("#ag-nova").scrollIntoView({ behavior: "smooth", block: "nearest" });
    return raiz.querySelector('#ag-form [name="titulo"]').focus();
  }
  if ("rep" in b.dataset) return escolherRepeticao(b.dataset.rep);
  if (b.dataset.diaSemana) {
    const d = Number(b.dataset.diaSemana);
    if (estado.form.dias.has(d)) estado.form.dias.delete(d); else estado.form.dias.add(d);
    b.classList.toggle("ativo", estado.form.dias.has(d));
    return b.setAttribute("aria-pressed", String(estado.form.dias.has(d)));
  }
  if (b.dataset.regiao) {
    estado.form.regiao = b.dataset.regiao;
    return b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("ativo", x === b));
  }
  if ("cancelarEdicao" in b.dataset) return cancelarEdicao();
  const li = b.closest(".ag-item");
  if (!li) return;
  const id = Number(li.dataset.atividade), dia = li.dataset.dia;
  const a = atividade(id);
  const item = estado.dados.dias.find((x) => x.data === dia).itens.find((i) => i.atividade === id);
  if ("check" in b.dataset) {
    if (item.feita) return desfazer(a, dia, item);
    if (a.exige_feedback) return escreverFeedback(id, dia);
    return concluir(a, dia, "");
  }
  if ("editarFb" in b.dataset) return escreverFeedback(id, dia);
  if ("cancelarFb" in b.dataset) { estado.concluindo = null; return desenharDia(false); }
  if ("confirmar" in b.dataset) return concluir(a, dia, li.querySelector(".ag-fb textarea").value, b);
  if ("desfazer" in b.dataset) return desfazer(a, dia, item);
  if ("historico" in b.dataset) return abrirHistorico(a);
  if ("editar" in b.dataset) return editar(a);
  if ("encerrar" in b.dataset) return encerrar(a);
  if ("excluir" in b.dataset) return excluir(a);
}

function aoTeclar(e) {
  const t = e.target;
  if (!t.matches(".ag-fb textarea")) return;
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); t.closest(".ag-item").querySelector("[data-confirmar]").click(); }
  if (e.key === "Escape") { estado.concluindo = null; desenharDia(false); }
}

function escreverFeedback(id, dia) {
  if (feedbackEscrito() && !confirm(DESCARTAR_FB)) return;
  estado.concluindo = { atividade: id, dia };
  desenharDia(false);
}

async function concluir(a, dia, feedback, botao) {
  if (a.exige_feedback && !feedback.trim()) {
    toast("Escreva o feedback para concluir esta atividade", "erro");
    return raiz.querySelector(".ag-fb textarea")?.focus();
  }
  if (botao) botao.disabled = true;
  try {
    await api("/api/agenda/concluir", { json: { id: a.id, dia, feedback } });
    estado.concluindo = null;
    await carregar();
  } catch (e) {
    if (botao) botao.disabled = false;
    toast(e.message, "erro");
  }
}

async function desfazer(a, dia, item) {
  if (item.feedback && !confirm(`Desfazer a conclusão de "${a.titulo}" em ${dataCurta(dia)}? O feedback deste dia sai junto.`)) return;
  try {
    await api("/api/agenda/desfazer", { json: { id: a.id, dia } });
    estado.concluindo = null;
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

async function encerrar(a) {
  if (!confirm(`Encerrar "${a.titulo}"? Ela para de se repetir depois de hoje; o histórico fica guardado.`)) return;
  try {
    await api("/api/agenda/atividade/encerrar", { json: { id: a.id } });
    toast("Atividade encerrada");
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

async function excluir(a) {
  const aviso = a.repeticao === "nenhuma" ? "" : " Todo o histórico de feedbacks dela também é apagado; para só parar de repetir, use Encerrar.";
  if (!confirm(`Excluir "${a.titulo}"?${aviso}`)) return;
  try {
    await api("/api/agenda/atividade/excluir", { json: { id: a.id } });
    if (estado.editando?.id === a.id) cancelarEdicao();
    toast("Atividade excluída");
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

// ---------- histórico ----------
function criarJanela() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo camp-dialogo ag-historico";
  dlg.setAttribute("aria-labelledby", "ag-hist-titulo");
  document.body.appendChild(dlg);
  dlg.addEventListener("click", (e) => { if (e.target.closest("[data-fechar]")) dlg.close(); });
}

async function abrirHistorico(a) {
  let h;
  try {
    h = await api(`/api/agenda/historico?id=${a.id}`);
  } catch (e) { return toast(e.message, "erro"); }
  criarJanela();
  const at = h.atividade;
  const faltas = h.faltas.length ? `<div class="ag-hist-faltas">
      <span class="cf-rotulo">Dias que ficaram sem concluir${h.faltas_total > h.faltas.length ? ` <small>(os ${h.faltas.length} mais recentes)</small>` : ""}</span>
      <div class="feriados-lista">${h.faltas.map((d) => `<span class="chip">${dataCurta(d)} · ${fmt.semana(d).slice(0, 3)}</span>`).join("")}</div>
    </div>` : "";
  const registros = h.registros.length ? h.registros.map((r) => `<li>
      <div class="ag-hist-data"><b>${dataCurta(r.dia)}</b><small>${fmt.semana(r.dia)}</small></div>
      <div class="ag-hist-txt">${r.feedback ? `<p>${esc(r.feedback)}</p>` : `<p class="fraco">Concluída sem feedback</p>`}
        <small>Concluída ${quando(r.concluida_em, r.dia)}${r.editada_em ? ` · feedback editado ${quando(r.editada_em, r.dia)}` : ""}</small></div>
    </li>`).join("") : `<li class="ag-vazio">${icone("info")}Nada concluído ainda.</li>`;
  dlg.innerHTML = `<div class="ag-hist">
    <div class="ag-hist-cab">
      <div><h2 id="ag-hist-titulo">${icone("restaurar")}${esc(at.titulo)}</h2>
        <p class="sub">${esc(textoRepeticao(at))} · desde ${dataCurta(at.inicio)}</p></div>
      <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar">${icone("x")}</button>
    </div>
    <div class="ag-hist-resumo">
      <div class="mini-stat"><div class="r">Concluídas</div><div class="v">${fmt.num(h.feitas)} <small>de ${fmt.num(h.ocorrencias)}</small></div></div>
      <div class="mini-stat"><div class="r">Ficaram sem concluir</div><div class="v">${fmt.num(h.faltas_total)}</div></div>
    </div>
    ${faltas}
    <span class="cf-rotulo ag-hist-rotulo">O que foi feito</span>
    <ol class="ag-hist-lista">${registros}</ol>
  </div>`;
  dlg.showModal();
}

// ---------- formulário ----------
function desenharForm(a = null) {
  const inicio = a ? a.inicio : (estado.aberto || hojeLocal());
  const v = a || { titulo: "", descricao: "", inicio, repeticao: "nenhuma", dias_semana: null, dia_mes: null, intervalo: null,
                   so_dias_uteis: false, regiao: null, fim: null, exige_feedback: false };
  estado.form = { repeticao: v.repeticao, dias: new Set(v.dias_semana || []), regiao: v.regiao || "ES" };
  estado.editando = a;
  const el = raiz.querySelector("#ag-nova");
  el.setAttribute("aria-label", a ? "Editar atividade" : "Atividade nova");
  el.innerHTML = `<div class="cartao-cab"><div>
      <h2>${icone(a ? "lapis" : "mais")}${a ? "Editar atividade" : "Nova atividade"}</h2>
      <p class="sub">${a ? "O que já foi concluído continua no histórico." : "Só você vê as atividades da sua agenda."}</p>
    </div></div>
    <form id="ag-form" class="ag-form" novalidate>
      <label class="campo-form"><span>Título</span>
        <input name="titulo" maxlength="120" autocomplete="off" value="${esc(v.titulo)}" placeholder="Ex.: Visitar o Mercado do João"></label>
      <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
        <textarea name="descricao" rows="2" maxlength="2000">${esc(v.descricao)}</textarea></label>
      <div class="campo-form"><span>Repetição</span>
        <div class="seg-mini ag-rep" role="group" aria-label="Repetição">${REPETICOES.map(([k, n]) =>
          `<button type="button" data-rep="${k}" class="${k === v.repeticao ? "ativo" : ""}" aria-pressed="${k === v.repeticao}">${n}</button>`).join("")}</div></div>
      <div class="ag-datas">
        <label class="campo-form"><span data-rotulo-inicio>${v.repeticao === "nenhuma" ? "Dia" : "Começa em"}</span>
          <input type="date" name="inicio" value="${v.inicio}"></label>
        <label class="campo-form" data-para="diaria semanal mensal intervalo"><span>Termina em <small>(opcional)</small></span>
          <input type="date" name="fim" value="${v.fim || ""}"></label>
      </div>
      <div class="ag-sub" data-para="diaria">
        <label class="vend-op"><input type="checkbox" name="so_dias_uteis" ${v.so_dias_uteis ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
          <span class="n">Só dias úteis<small>Pula domingos, feriados e sábados sem expediente</small></span></label>
        <div class="ag-regiao" data-regioes ${v.so_dias_uteis ? "" : "hidden"}><span>Calendário</span>
          <div class="seg-mini" role="group" aria-label="Calendário dos dias úteis">${["ES", "BA"].map((r) =>
            `<button type="button" data-regiao="${r}" class="${estado.form.regiao === r ? "ativo" : ""}">${r}</button>`).join("")}</div></div>
      </div>
      <div class="ag-sub" data-para="semanal"><div class="campo-form"><span>Dias da semana</span>
        <div class="dias-semana" role="group" aria-label="Dias da semana">${DIAS.map(([d, n]) =>
          `<button type="button" data-dia-semana="${d}" aria-pressed="${estado.form.dias.has(d)}" class="${estado.form.dias.has(d) ? "ativo" : ""}">${n}</button>`).join("")}</div></div></div>
      <div class="ag-sub" data-para="mensal"><label class="campo-form"><span>Dia do mês</span>
        <input type="number" name="dia_mes" min="1" max="31" inputmode="numeric" value="${v.dia_mes ?? ""}">
        <small>Em meses que não têm esse dia, cai no último.</small></label></div>
      <div class="ag-sub" data-para="intervalo"><label class="campo-form"><span>A cada quantos dias</span>
        <input type="number" name="intervalo" min="2" max="365" inputmode="numeric" value="${v.intervalo ?? 15}">
        <small>Contando do primeiro dia. Quinzenal: 15.</small></label></div>
      <label class="vend-op"><input type="checkbox" name="exige_feedback" ${v.exige_feedback ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">Exige feedback ao concluir<small>Para marcar como feita, é preciso contar como foi</small></span></label>
      <div class="ag-form-acoes">
        ${a ? `<button class="btn" type="button" data-cancelar-edicao>Cancelar</button>` : ""}
        <button class="btn primario" type="submit">${icone(a ? "disco" : "mais")}${a ? "Salvar" : "Criar atividade"}</button>
      </div>
    </form>`;
  el.querySelector("form").addEventListener("submit", aoEnviar);
  mostrarCampos();
  estado.formInicial = JSON.stringify(coletar());
}

// Os campos da repetição escolhida (e o rótulo da data).
function mostrarCampos() {
  const f = raiz.querySelector("#ag-form");
  const rep = estado.form.repeticao;
  f.querySelectorAll("[data-para]").forEach((el) => { el.hidden = !el.dataset.para.split(" ").includes(rep); });
  f.querySelector("[data-rotulo-inicio]").textContent = rep === "nenhuma" ? "Dia" : "Começa em";
}

function escolherRepeticao(rep) {
  const f = raiz.querySelector("#ag-form");
  estado.form.repeticao = rep;
  f.querySelectorAll("[data-rep]").forEach((b) => {
    b.classList.toggle("ativo", b.dataset.rep === rep);
    b.setAttribute("aria-pressed", String(b.dataset.rep === rep));
  });
  const inicio = f.elements.inicio.value || hojeLocal();
  // Primeira vez na semanal ou na mensal: começa pelo dia da semana ou do mês da data escolhida.
  if (rep === "semanal" && !estado.form.dias.size) {
    const d = diaDaSemana(inicio);
    estado.form.dias.add(d);
    f.querySelector(`[data-dia-semana="${d}"]`).classList.add("ativo");
    f.querySelector(`[data-dia-semana="${d}"]`).setAttribute("aria-pressed", "true");
  }
  if (rep === "mensal" && !f.elements.dia_mes.value) f.elements.dia_mes.value = Number(inicio.slice(8));
  mostrarCampos();
}

function aoMudar(e) {
  if (e.target.name === "so_dias_uteis") raiz.querySelector("[data-regioes]").hidden = !e.target.checked;
}

// O dia do formulário acompanha o dia aberto; com o formulário intocado, isso não conta como alteração.
function definirDiaDoForm(dia) {
  const f = raiz.querySelector("#ag-form");
  if (!f || !dia) return;
  const intacto = !formMudou();
  f.elements.inicio.value = dia;
  if (intacto) estado.formInicial = JSON.stringify(coletar());
}

function coletar() {
  const f = raiz.querySelector("#ag-form");
  const rep = estado.form.repeticao;
  const uteis = rep === "diaria" && f.elements.so_dias_uteis.checked;
  const num = (n) => (f.elements[n].value === "" ? null : Number(f.elements[n].value));
  return {
    titulo: f.elements.titulo.value.trim(), descricao: f.elements.descricao.value.trim(), inicio: f.elements.inicio.value,
    repeticao: rep, dias_semana: rep === "semanal" ? [...estado.form.dias].sort() : null,
    dia_mes: rep === "mensal" ? num("dia_mes") : null, intervalo: rep === "intervalo" ? num("intervalo") : null,
    so_dias_uteis: uteis, regiao: uteis ? estado.form.regiao : null,
    fim: rep !== "nenhuma" && f.elements.fim.value ? f.elements.fim.value : null,
    exige_feedback: f.elements.exige_feedback.checked,
  };
}

function formMudou() {
  return !!raiz?.querySelector("#ag-form") && JSON.stringify(coletar()) !== estado.formInicial;
}

function editar(a) {
  if (estado.editando?.id !== a.id && formMudou() && !confirm("Descartar o que foi preenchido no formulário?")) return;
  desenharForm(a);
  raiz.querySelector("#ag-nova").scrollIntoView({ behavior: "smooth", block: "nearest" });
  raiz.querySelector('#ag-form [name="titulo"]').focus();
}

function cancelarEdicao() {
  desenharForm();
}

async function aoEnviar(e) {
  e.preventDefault();
  const f = e.target;
  const dados = coletar();
  if (!dados.titulo) { toast("Escreva o título da atividade", "erro"); return f.elements.titulo.focus(); }
  if (!dados.inicio) { toast("Escolha o dia da atividade", "erro"); return f.elements.inicio.focus(); }
  if (dados.repeticao === "semanal" && !dados.dias_semana.length) return toast("Escolha ao menos um dia da semana", "erro");
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const editando = estado.editando;
  try {
    if (editando) await api("/api/agenda/atividade/editar", { json: { id: editando.id, atividade: dados } });
    else await api("/api/agenda/atividades", { json: { atividade: dados } });
    toast(editando ? "Atividade salva" : "Atividade criada");
    desenharForm();
    await (editando ? carregar() : carregar(mesDe(dados.inicio), { aberto: dados.inicio }));
  } catch (err) {
    botao.disabled = false;
    toast(err.message, "erro");
  }
}
