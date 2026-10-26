// Minha agenda, no topo da página Gestão (gestao.js monta): as atividades de cada pessoa (só ela vê) e as tarefas de que
// ela participa, na faixa de dias do mês (a mesma do "Ritmo do mês" da página Metas), com o dia de hoje num quadrado
// maior. Cada quadrado mostra quantos itens o dia tem e, numa barrinha, os feitos (verde) e os que faltam (laranja;
// vermelho se o dia passou). Clicar num dia amplia o painel com o que há nele (os com horário primeiro).
// - Atividade: concluir (com o feedback, obrigatório quando a atividade pede), editar o feedback, desfazer e, nas que
//   se repetem, o histórico de tudo o que foi feito.
// - Tarefa: aparece no dia do prazo; cada subtarefa, no dia do prazo dela (quem criou vê todas; o participante, as
//   dele). A janela da tarefa mostra todas as subtarefas, de todos: cada um conclui as suas e, com autonomia, edita o
//   texto delas e cria subtarefas para si. No dia de hoje, um bloco lista as tarefas e subtarefas atrasadas.
// Ao lado, o formulário de atividade nova (única, diária, semanal, mensal ou a cada N dias, com horário opcional) ou de
// tarefa nova (prazo, participantes com ou sem autonomia e subtarefas), que também edita uma atividade ou uma tarefa.
// Recolhida, fica só a faixa de dias (a escolha fica guardada neste navegador). #/gestao?dia=AAAA-MM-DD abre a agenda
// nesse dia (o link das propostas do Assistente). Em que dias cada atividade acontece, o texto da repetição ("Toda
// segunda e quinta") e o que cada pessoa pode fazer numa tarefa vêm do servidor (bi/agenda.py e bi/tarefas.py).
import { MESES, api, esc, fmt, guardar, icone, ler, ligarTooltips, linhaTT, toast } from "./util.js";

const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const DIAS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]]; // date.isoweekday()
const MAX_SEGMENTOS = 6; // até aqui, a barrinha do dia tem um pedaço por item; acima, só as duas partes
const MAX_TOOLTIP = 6;   // itens listados no tooltip do dia
const REPETICOES = [["nenhuma", "Única"], ["diaria", "Diária"], ["semanal", "Semanal"], ["mensal", "Mensal"], ["intervalo", "A cada N dias"]];
const TIPOS = [["atividade", "Atividade"], ["tarefa", "Tarefa"]];
const DESCARTAR_FB = "Descartar o feedback que você estava escrevendo?";
const DESCARTAR_FORM = "Descartar o que foi preenchido no formulário?";
const DESCARTAR_SUB = "Descartar o que você mudou na subtarefa?";
const CHAVE_RECOLHIDA = "mv-agenda-recolhida";

let raiz = null, dlg = null;
// tipo: o do formulário (atividade ou tarefa); tf: os participantes e as subtarefas do formulário da tarefa;
// pessoas: quem pode participar ({eu, pessoas}, carregado na primeira tarefa); editando: {tipo, ...o item}.
const estado = { mes: null, dados: null, aberto: null, editando: null, concluindo: null, form: null, formInicial: null, pedido: 0,
                 tipo: "atividade", tf: null, pessoas: null };
// A janela da tarefa: a tarefa aberta, a subtarefa em edição (id, "nova" ou null), como o formulário dela começou e,
// na nova, para quem (o botão ao lado do nome da pessoa; null = quem criou).
const janela = { tarefa: null, editando: null, inicial: null, para: null };

// ---------- apoio ----------
const capitalizar = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);
const mesDe = (iso) => iso.slice(0, 7);
const hora = (iso) => (iso ? iso.slice(11, 16) : "");
const diaDaSemana = (iso) => new Date(`${iso}T12:00`).getDay() || 7; // 1 = segunda ... 7 = domingo
const atividade = (id) => estado.dados.atividades.find((a) => a.id === id);
const tarefa = (id) => estado.dados.tarefas.find((t) => t.id === id);
const subDe = (t, id) => t.subtarefas.find((s) => s.id === id);
const ehDia = (t) => /^\d{4}-\d{2}-\d{2}$/.test(t || "");
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;
// Tudo o que o dia tem (atividades e tarefas), para as contas: os dois carregam o feita.
const todos = (x) => [...x.itens, ...(x.tarefas || [])];

function hojeLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function somarMes(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  const d = new Date(a, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
// "26/10" no ano de hoje; "26/10/2025" em outro ano.
function dataCurta(iso) {
  return iso.slice(0, 4) === (estado.dados?.hoje || hojeLocal()).slice(0, 4) ? fmt.dataCurta(iso) : fmt.data(iso);
}
// Quando foi concluída: "às 14:03" no próprio dia, "em 28/10 às 09:10" depois.
function quando(iso, dia) {
  return iso.slice(0, 10) === dia ? `às ${hora(iso)}` : `em ${dataCurta(iso.slice(0, 10))} às ${hora(iso)}`;
}
// O prazo de uma tarefa ou subtarefa: "30/10" ou "30/10 às 14:00".
const prazoTxt = (x) => `${dataCurta(x.prazo)}${x.hora ? ` às ${x.hora}` : ""}`;
// A tarefa ou a subtarefa de uma referência da agenda ({tarefa, subtarefa}).
function daRef(r) {
  const t = tarefa(r.tarefa);
  return { t, s: r.subtarefa ? subDe(t, r.subtarefa) : null };
}
// O que o dia tem, na ordem do painel: com horário primeiro (no mesmo horário, as atividades antes).
function doDia(x) {
  const lista = [...x.itens.map((i) => ({ i, hora: atividade(i.atividade).hora })),
    ...(x.tarefas || []).map((r) => { const { t, s } = daRef(r); return { r, hora: (s || t).hora }; })];
  return lista.sort((a, b) => (a.hora == null) - (b.hora == null) || (a.hora || "").localeCompare(b.hora || ""));
}

// ---------- montagem ----------
export function agendaTemAlteracoes() {
  return (!!raiz?.isConnected && (formMudou() || feedbackEscrito())) || janelaMudou();
}

// dia: o dia a abrir (#/gestao?dia=…); sem ele, hoje.
export function montarAgenda(el, { dia } = {}) {
  el.innerHTML = `<section class="cartao ag-cal entra" style="--i:0" id="ag-raiz">
      <div class="cartao-cab">
        <div><h2>${icone("calendario")}Minha agenda<span class="ag-mes" id="ag-titulo"></span></h2>
          <p class="sub" id="ag-resumo">&nbsp;</p></div>
        <div class="ag-nav">
          <button class="btn icone" type="button" data-mes="-1" title="Mês anterior" aria-label="Mês anterior">${icone("voltar")}</button>
          <button class="btn" type="button" data-hoje>Hoje</button>
          <button class="btn icone" type="button" data-mes="1" title="Próximo mês" aria-label="Próximo mês">${icone("seta")}</button>
          <button class="btn icone" type="button" data-recolher aria-controls="ag-baixo"></button>
        </div>
      </div>
      <div id="ag-faixa"><div class="esqueleto" style="height:96px"></div></div>
      <div class="ag-baixo" id="ag-baixo">
        <div id="ag-dia"></div>
        <aside class="ag-nova" id="ag-nova" aria-label="Atividade nova"></aside>
      </div>
    </section>`;
  raiz = el.querySelector("#ag-raiz");
  raiz.addEventListener("click", aoClicar);
  raiz.addEventListener("change", aoMudar);
  raiz.addEventListener("keydown", aoTeclar);
  Object.assign(estado, { mes: null, dados: null, aberto: null, editando: null, concluindo: null, tipo: "atividade", tf: null, pessoas: null });
  recolher(ler(CHAVE_RECOLHIDA, false));
  desenharForm();
  const valido = ehDia(dia);
  carregar(valido ? mesDe(dia) : undefined, { aberto: valido ? dia : undefined });
}

// O link de uma proposta do Assistente (#/gestao?dia=…) com a Gestão já montada: abre a agenda nesse dia.
export function abrirNaAgenda(dia) {
  if (!raiz?.isConnected || !ehDia(dia)) return;
  if (raiz.classList.contains("recolhida")) recolher(false);
  estado.concluindo = null;
  carregar(mesDe(dia), { aberto: dia });
  raiz.scrollIntoView({ behavior: "smooth", block: "start" });
}

// A Gestão chama ao voltar para a página: o dia de hoje (e o que foi feito em outro aparelho) pode ter mudado.
export function recarregarAgenda() {
  if (raiz?.isConnected && estado.dados) carregar();
}

// Recolhida: só a faixa de dias; o dia aberto e o formulário somem até abrir de novo (ou clicar num dia).
function recolher(sim) {
  raiz.classList.toggle("recolhida", sim);
  const b = raiz.querySelector("[data-recolher]");
  const dica = sim ? "Mostrar o dia e o formulário" : "Recolher a agenda";
  b.innerHTML = icone(sim ? "mais" : "minimizar");
  b.title = dica;
  b.setAttribute("aria-label", dica);
  b.setAttribute("aria-expanded", String(!sim));
  guardar(CHAVE_RECOLHIDA, sim);
}

async function carregar(mes = estado.mes, { aberto } = {}) {
  const pedido = ++estado.pedido;
  const blocos = [raiz.querySelector("#ag-faixa"), raiz.querySelector("#ag-dia")];
  const mesmoMes = !!estado.dados && estado.dados.mes === (mes || estado.mes);
  if (estado.dados) blocos.forEach((b) => b.classList.add("recarregando"));
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
    if (pedido === estado.pedido) blocos.forEach((b) => b.classList.remove("recarregando"));
  }
}

// ---------- faixa de dias ----------
function desenharFaixa(quieta) {
  const d = estado.dados;
  const [ano, m] = d.mes.split("-").map(Number);
  raiz.querySelector("#ag-titulo").textContent = `${capitalizar(MESES[m - 1])} de ${ano}`;
  let atividades = 0, tarefas = 0, feitas = 0, atrasadas = 0;
  for (const x of d.dias) {
    atividades += x.itens.length;
    tarefas += x.tarefas.length;
    feitas += todos(x).filter((i) => i.feita).length;
    if (x.data < d.hoje) atrasadas += todos(x).filter((i) => !i.feita).length;
  }
  const partes = [atividades && plural(atividades, "atividade", "atividades"), tarefas && plural(tarefas, "tarefa", "tarefas")].filter(Boolean);
  raiz.querySelector("#ag-resumo").textContent = partes.length
    ? `${partes.join(" e ")} no mês · ${plural(feitas, "concluída", "concluídas")}${atrasadas ? ` · ${fmt.num(atrasadas)} sem concluir` : ""}`
    : "Nada marcado neste mês";
  raiz.querySelector("#ag-faixa").innerHTML = `<div class="faixa-dias ag-faixa ${quieta ? "quieta" : ""}" role="group" aria-label="Dias de ${MESES[m - 1]}">
    ${d.dias.map((x, n) => {
      const dia = Number(x.data.slice(8));
      const dow = new Date(x.data + "T12:00").getDay();
      const lista = doDia(x);
      const total = lista.length;
      const pendentes = todos(x).filter((i) => !i.feita).length, feitasDia = total - pendentes;
      const hoje = x.data === d.hoje;
      const classes = ["dia", total ? "tem" : "", total && !pendentes ? "feita" : "",
        pendentes && x.data < d.hoje ? "atrasada" : "", hoje ? "hoje" : "", x.data === estado.aberto ? "aberto" : "",
        dow === 0 || dow === 6 ? "ag-fds" : ""].filter(Boolean).join(" ");
      const col = n === 0 ? `;--col:${((dow + 6) % 7) + 1}` : "";
      const tt = `<div class='tt-t'>${fmt.dataCurta(x.data)} · ${fmt.semana(x.data)}${hoje ? " · hoje" : ""}</div>` +
        (total ? linhaTT("No dia", fmt.num(total)) + linhaTT("Feitas", fmt.num(feitasDia)) + linhaTT("Faltam", fmt.num(pendentes)) +
          lista.slice(0, MAX_TOOLTIP).map((e) => linhaDoDia(e)).join("") +
          (total > MAX_TOOLTIP ? `<div class='tt-l'><span>e mais ${total - MAX_TOOLTIP}</span></div>` : "")
          : linhaTT("No dia", "nada marcado"));
      const rotulo = `${dia} de ${MESES[m - 1]}${hoje ? ", hoje" : ""}: ${total ? `${plural(total, "item", "itens")}, ${plural(feitasDia, "feito", "feitos")}, faltam ${pendentes}` : "nada marcado"}`;
      return `<button type="button" class="${classes}" style="--i:${n}${col}" data-dia="${x.data}" data-tt="${esc(tt)}"
        aria-pressed="${x.data === estado.aberto}" aria-label="${esc(rotulo)}">${total ? `<i class="ag-n">${total}</i>` : ""}${dia}${barra(feitasDia, pendentes)}<span class="sem">${SEMANA[dow]}</span></button>`;
    }).join("")}
  </div>
  <div class="ag-legenda" aria-hidden="true"><span><b class="ag-n">3</b>atividades e tarefas no dia</span>
    <span><span class="ag-barra"><i class="f"></i><i></i><i></i></span>feitas e as que faltam</span>
    <span><i class="tem"></i>Com algo marcado</span><span><i class="feita"></i>Tudo feito</span>
    <span><i class="atrasada"></i>Ficou sem concluir</span></div>`;
  ligarTooltips(raiz.querySelector("#ag-faixa"));
}

// A barrinha do quadrado: um pedaço por item (os feitos primeiro); com muitos, só as duas partes.
function barra(feitas, faltam) {
  if (!feitas && !faltam) return "";
  const pedacos = feitas + faltam <= MAX_SEGMENTOS
    ? '<i class="f"></i>'.repeat(feitas) + "<i></i>".repeat(faltam)
    : `<i class="f" style="flex:${feitas}"></i><i style="flex:${faltam}"></i>`;
  return `<span class="ag-barra" aria-hidden="true">${pedacos}</span>`;
}

// Uma linha do tooltip do dia: a atividade, a tarefa ou a subtarefa (de quem, se não for minha).
function linhaDoDia(e) {
  let nome;
  if (e.i) nome = atividade(e.i.atividade).titulo;
  else {
    const { t, s } = daRef(e.r);
    nome = s ? `${s.titulo} (${s.minha ? "subtarefa" : `de ${s.responsavel.nome}`})` : `Tarefa: ${t.titulo}`;
  }
  return `<div class='tt-l'><span>${e.hora ? `${e.hora} ` : ""}${esc(nome)}</span><b>${(e.i || e.r).feita ? "feita" : "falta"}</b></div>`;
}

function abrirDia(dia) {
  if (raiz.classList.contains("recolhida")) recolher(false);
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
  const lista = doDia(x);
  const pendentes = todos(x).filter((i) => !i.feita).length;
  const situacao = !lista.length ? "" : !pendentes ? "tudo concluído"
    : futuro ? plural(pendentes, "item", "itens")
    : `${pendentes} ${pendentes === 1 ? "pendente" : "pendentes"} de ${lista.length}`;
  const atrasadas = x.data === d.hoje ? d.atrasadas : [];
  el.innerHTML = `<div class="ag-dia ${animar ? "abre" : ""}">
    <div class="ag-dia-cab">
      <div><h3>${capitalizar(fmt.semana(x.data))}, ${dataCurta(x.data)}${x.data === d.hoje ? ` <span class="chip laranja">hoje</span>` : ""}</h3>
        ${situacao ? `<small>${situacao}</small>` : ""}</div>
      <button class="btn" type="button" data-novo-no-dia>${icone("mais")}Novo neste dia</button>
    </div>
    ${atrasadas.length ? `<div class="ag-atrasadas">
      <h4>${icone("alerta")}Atrasadas <small>${plural(atrasadas.length, "item vencido", "itens vencidos")}, até concluir</small></h4>
      <ul class="ag-itens">${atrasadas.map((r, n) => refHtml(r, x.data, n, true)).join("")}</ul>
    </div>` : ""}
    ${lista.length ? `<ul class="ag-itens">${lista.map((e, n) => (e.i ? itemHtml(e.i, x.data, futuro, n) : refHtml(e.r, x.data, n))).join("")}</ul>`
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
      <b>${a.hora ? `<span class="ag-hora">${icone("relogio")}${a.hora}</span>` : ""}${esc(a.titulo)}</b>
      ${a.descricao ? `<p>${esc(a.descricao)}</p>` : ""}
      <div class="ag-chips"><span class="chip">${icone(repete ? "atualizar" : "calendario")}${esc(a.quando)}</span>
        ${a.exige_feedback ? `<span class="chip laranja">${icone("conversa")}Pede feedback</span>` : ""}</div>
      ${rodape}
    </div>
    <div class="ag-item-acoes">
      ${repete ? `<button type="button" data-historico title="Histórico de feedbacks" aria-label="Histórico de feedbacks de ${esc(a.titulo)}">${icone("caderneta")}</button>` : ""}
      <button type="button" data-editar title="Editar a atividade" aria-label="Editar ${esc(a.titulo)}">${icone("lapis")}</button>
      ${encerravel ? `<button type="button" data-encerrar title="Parar de repetir depois de hoje" aria-label="Encerrar ${esc(a.titulo)}">${icone("bandeira")}</button>` : ""}
      <button type="button" class="perigo" data-excluir title="Excluir a atividade" aria-label="Excluir ${esc(a.titulo)}">${icone("lixeira")}</button>
    </div>
  </li>`;
}

// Por que o check de uma tarefa ou subtarefa está ou não liberado.
function dicaCheck(t, s) {
  const x = s || t;
  if ((s ? s.pode : t.pode).concluir) return x.feita ? (s ? "Desfazer a conclusão" : "Reabrir a tarefa") : "Marcar como concluída";
  if (!s) return `Só ${t.criador.nome}, que criou a tarefa, conclui`;
  if (s.pela_tarefa) return "Concluída junto com a tarefa";
  if (t.feita) return "A tarefa foi concluída; quem criou reabre";
  return `Só ${s.responsavel.nome} (o responsável) ou ${t.criador.nome} (quem criou) conclui`;
}

// "Concluída por Beto às 14:03", "Concluída junto com a tarefa".
function textoConclusao(t, s, dia) {
  if (s?.pela_tarefa) return "Concluída junto com a tarefa";
  const x = s || t;
  const por = s?.concluida_por && !(s.minha && s.concluida_por.id === s.responsavel.id) ? ` por ${esc(s.concluida_por.nome)}` : "";
  return `Concluída${por} ${quando(x.concluida_em, dia)}`;
}

// Uma tarefa ou subtarefa no painel do dia (vencida: na lista de atrasadas de hoje, com o dia do prazo).
function refHtml(r, dia, n, vencida = false) {
  const { t, s } = daRef(r);
  const x = s || t;
  const pode = (s ? s.pode : t.pode).concluir;
  const dica = dicaCheck(t, s);
  const chips = [
    `<span class="chip ag-c-tarefa">${icone("tarefa")}${s ? `Subtarefa${s.minha ? "" : ` · ${esc(s.responsavel.nome)}`}` : "Tarefa"}</span>`,
    vencida ? `<span class="chip ag-c-atrasada">${icone("alerta")}Venceu em ${dataCurta(x.prazo)}</span>` : "",
    s ? `<span class="chip">Parte de: ${esc(t.titulo)}</span>` : "",
    !s && t.total ? `<span class="chip">${icone("visto")}${t.feitas} de ${plural(t.total, "subtarefa feita", "subtarefas feitas")}</span>` : "",
    !s && t.participantes.length ? `<span class="chip" title="${esc(t.participantes.map((p) => p.nome).join(", "))}">${icone("pessoas")}${plural(t.participantes.length + 1, "pessoa", "pessoas")}</span>` : "",
    !t.eu_criador ? `<span class="chip">${icone("usuario")}De ${esc(t.criador.nome)}</span>` : "",
  ].filter(Boolean).join("");
  return `<li class="ag-item ${s ? "ag-subtarefa" : "ag-tarefa"} ${x.feita ? "feita" : ""}" style="--i:${n}" data-tarefa="${t.id}" data-subtarefa="${s ? s.id : ""}" data-dia="${dia}">
    <button type="button" class="ag-check ${x.feita ? "feita" : ""}" data-check ${pode ? "" : "disabled"}
      aria-pressed="${x.feita}" title="${esc(dica)}" aria-label="${esc(dica)}: ${esc(x.titulo)}">${icone("visto")}</button>
    <div class="ag-item-t">
      <b>${x.hora ? `<span class="ag-hora">${icone("relogio")}${x.hora}</span>` : ""}${esc(x.titulo)}</b>
      ${x.descricao ? `<p>${esc(x.descricao)}</p>` : ""}
      <div class="ag-chips">${chips}</div>
      ${x.feita ? `<div class="ag-feito"><small><span>${textoConclusao(t, s, x.prazo)}</span></small></div>` : ""}
    </div>
    <div class="ag-item-acoes">
      <button type="button" data-abrir-tarefa title="Abrir a tarefa" aria-label="Abrir a tarefa ${esc(t.titulo)}">${icone("olho")}</button>
      ${t.eu_criador ? `<button type="button" data-editar title="Editar a tarefa" aria-label="Editar a tarefa ${esc(t.titulo)}">${icone("lapis")}</button>
        <button type="button" class="perigo" data-excluir title="Excluir a tarefa" aria-label="Excluir a tarefa ${esc(t.titulo)}">${icone("lixeira")}</button>` : ""}
    </div>
  </li>`;
}

const feedbackEscrito = () => !!raiz?.querySelector(".ag-fb textarea")?.value.trim();

// ---------- ações ----------
async function aoClicar(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if (b.dataset.dia && b.closest(".ag-faixa")) return abrirDia(b.dataset.dia);
  if ("recolher" in b.dataset) return recolher(!raiz.classList.contains("recolhida"));
  if (b.dataset.mes || "hoje" in b.dataset) {
    if (feedbackEscrito() && !confirm(DESCARTAR_FB)) return;
    estado.concluindo = null;
    const hoje = estado.dados?.hoje || hojeLocal();
    return "hoje" in b.dataset ? carregar(mesDe(hoje), { aberto: hoje }) : carregar(somarMes(estado.mes, Number(b.dataset.mes)));
  }
  if ("novoNoDia" in b.dataset) {
    if (estado.editando) {
      if (formMudou() && !confirm(`Descartar as mudanças nesta ${estado.editando.tipo}?`)) return;
      cancelarEdicao();
    }
    definirDiaDoForm(estado.aberto);
    raiz.querySelector("#ag-nova").scrollIntoView({ behavior: "smooth", block: "nearest" });
    return raiz.querySelector('#ag-form [name="titulo"]').focus();
  }
  if (b.dataset.tipo) return escolherTipo(b.dataset.tipo);
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
  if (b.dataset.autonomia) {
    lerSubs();
    const p = estado.tf.participantes.find((x) => x.id === Number(b.dataset.autonomia));
    p.autonomia = !p.autonomia;
    return desenharPessoas();
  }
  if (b.dataset.tirarPessoa) return tirarPessoa(Number(b.dataset.tirarPessoa));
  if ("maisSub" in b.dataset) return maisSub();
  if (b.dataset.subPara) return maisSub(Number(b.dataset.subPara));
  if (b.dataset.tirarSub) {
    lerSubs();
    estado.tf.subtarefas.splice(Number(b.dataset.tirarSub), 1);
    return desenharSubs();
  }
  if ("cancelarEdicao" in b.dataset) return cancelarEdicao();
  const li = b.closest(".ag-item");
  if (!li) return;
  if (li.dataset.tarefa) return aoClicarTarefa(b, li);
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

function aoClicarTarefa(b, li) {
  const t = tarefa(Number(li.dataset.tarefa));
  const s = li.dataset.subtarefa ? subDe(t, Number(li.dataset.subtarefa)) : null;
  if ("check" in b.dataset) return s ? alternarSub(s) : alternarTarefa(t);
  if ("abrirTarefa" in b.dataset) return abrirTarefa(t.id);
  if ("editar" in b.dataset) return editarTarefa(t);
  if ("excluir" in b.dataset) return excluirTarefa(t);
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
    if (editandoEste("atividade", a.id)) cancelarEdicao();
    toast("Atividade excluída");
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

// ---------- tarefas ----------
const editandoEste = (tipo, id) => estado.editando?.tipo === tipo && estado.editando.id === id;

// Grava uma mudança numa tarefa; a resposta traz a tarefa como ficou, que redesenha a janela (se for a aberta).
async function mexer(url, json, aviso) {
  try {
    const r = await api(url, { json });
    if (aviso) toast(aviso);
    if (r.tarefa && dlg?.open && janela.tarefa?.id === r.tarefa.id) {
      janela.editando = null;
      desenharTarefa(r.tarefa);
    }
    await carregar();
    return r;
  } catch (e) {
    toast(e.message, "erro");
    if (e.status === 404) { // a tarefa saiu (ou a pessoa saiu dela) em outro lugar
      if (dlg?.open && janela.tarefa) dlg.close();
      carregar();
    }
    return null;
  }
}

function alternarSub(s) {
  return mexer(`/api/agenda/subtarefa/${s.feita ? "desfazer" : "concluir"}`, { id: s.id });
}

function alternarTarefa(t) {
  const abertas = t.total - t.feitas;
  if (!t.feita && abertas && !confirm(`Concluir "${t.titulo}"? ${abertas === 1 ? "A subtarefa que falta passa" : `As ${abertas} subtarefas que faltam passam`} a contar como feita${abertas === 1 ? "" : "s"} (reabrindo a tarefa, elas voltam).`)) return;
  return mexer(`/api/agenda/tarefa/${t.feita ? "desfazer" : "concluir"}`, { id: t.id }, t.feita ? "Tarefa reaberta" : "Tarefa concluída");
}

async function excluirTarefa(t) {
  const subs = t.total ? ` ${t.total === 1 ? "A subtarefa sai" : `As ${t.total} subtarefas saem`} junto.` : "";
  const outros = t.participantes.length ? " Ela some da agenda de todos os participantes." : "";
  if (!confirm(`Excluir a tarefa "${t.titulo}"?${subs}${outros}`)) return;
  if (dlg?.open && janela.tarefa?.id === t.id) dlg.close();
  if (await mexer("/api/agenda/tarefa/excluir", { id: t.id }, "Tarefa excluída") && editandoEste("tarefa", t.id)) cancelarEdicao();
}

async function garantirPessoas() {
  if (estado.pessoas) return true;
  try {
    estado.pessoas = await api("/api/agenda/pessoas");
    return true;
  } catch (e) {
    toast(e.message, "erro");
    return false;
  }
}

async function editarTarefa(t) {
  if (!editandoEste("tarefa", t.id) && formMudou() && !confirm(DESCARTAR_FORM)) return;
  if (!(await garantirPessoas())) return;
  if (raiz.classList.contains("recolhida")) recolher(false);
  desenharForm({ ...t, tipo: "tarefa" });
  raiz.querySelector("#ag-nova").scrollIntoView({ behavior: "smooth", block: "nearest" });
  raiz.querySelector('#ag-form [name="titulo"]').focus();
}

// ---------- janela: histórico de uma atividade e a tarefa aberta ----------
function criarJanela() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  document.body.appendChild(dlg);
  // fica fora de #ag-raiz: os eventos dela são estes, não os da agenda
  dlg.addEventListener("click", aoClicarJanela);
  dlg.addEventListener("submit", aoEnviarSub);
  dlg.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && e.target.closest("[data-sub-form]")) {
      e.preventDefault();
      e.target.closest("form").requestSubmit();
    }
  });
  dlg.addEventListener("cancel", (e) => { if (janelaMudou() && !confirm(DESCARTAR_SUB)) e.preventDefault(); });
  dlg.addEventListener("close", () => Object.assign(janela, { tarefa: null, editando: null, inicial: null, para: null }));
}

async function abrirHistorico(a) {
  let h;
  try {
    h = await api(`/api/agenda/historico?id=${a.id}`);
  } catch (e) { return toast(e.message, "erro"); }
  criarJanela();
  Object.assign(janela, { tarefa: null, editando: null, inicial: null, para: null });
  dlg.className = "dialogo camp-dialogo ag-historico";
  dlg.setAttribute("aria-labelledby", "ag-hist-titulo");
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
      <div><h2 id="ag-hist-titulo">${icone("caderneta")}${esc(at.titulo)}</h2>
        <p class="sub">${esc(at.quando)}${at.hora ? ` · ${at.hora}` : ""} · desde ${dataCurta(at.inicio)}</p></div>
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
  if (!dlg.open) dlg.showModal();
}

async function abrirTarefa(id) {
  let t;
  try {
    t = await api(`/api/agenda/tarefa?id=${id}`);
  } catch (e) {
    toast(e.message, "erro");
    if (e.status === 404) carregar();
    return;
  }
  criarJanela();
  dlg.className = "dialogo camp-dialogo ag-tarefa-dlg";
  dlg.setAttribute("aria-labelledby", "ag-tf-titulo");
  janela.editando = null;
  desenharTarefa(t);
  if (!dlg.open) dlg.showModal();
}

// As subtarefas por pessoa: as minhas primeiro, depois as de quem criou e as dos outros, pelo nome.
function grupos(t) {
  const por = new Map();
  for (const s of t.subtarefas) {
    if (!por.has(s.responsavel.id)) por.set(s.responsavel.id, { pessoa: s.responsavel, minha: s.minha, subs: [] });
    por.get(s.responsavel.id).subs.push(s);
  }
  const ordem = (g) => [g.minha ? 0 : g.pessoa.id === t.criador.id ? 1 : 2, g.pessoa.nome.toLowerCase()];
  return [...por.values()].sort((a, b) => {
    const [x, y] = [ordem(a), ordem(b)];
    return x[0] - y[0] || x[1].localeCompare(y[1]);
  });
}

function desenharTarefa(t) {
  janela.tarefa = t;
  const pessoas = [{ ...t.criador, criador: true }, ...t.participantes];
  const lista = grupos(t).map((g) => {
    const feitas = g.subs.filter((s) => s.feita).length;
    return `<section class="ag-grupo">
      <h4>${icone("usuario")}${g.minha ? "As suas" : esc(g.pessoa.nome)} <small>${feitas} de ${g.subs.length}</small></h4>
      <ul class="ag-itens">${g.subs.map((s) => subHtml(t, s)).join("")}</ul>
    </section>`;
  }).join("");
  const nova = !t.pode.criar_subtarefa ? ""
    : janela.editando === "nova" ? `<div class="ag-grupo">${formSubHtml(t, null)}</div>`
    : `<button class="btn ag-mais-sub" type="button" data-sub-nova>${icone("mais")}${t.eu_criador ? "Subtarefa" : "Subtarefa para mim"}</button>`;
  dlg.innerHTML = `<div class="ag-tf">
    <div class="ag-hist-cab">
      <div><h2 id="ag-tf-titulo">${icone("tarefa")}${esc(t.titulo)}</h2>
        <p class="sub">Prazo: ${prazoTxt(t)}${t.atrasada ? ` <span class="chip ag-c-atrasada">${icone("alerta")}atrasada</span>` : ""}
          · criada por ${t.eu_criador ? "você" : esc(t.criador.nome)}</p></div>
      <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar">${icone("x")}</button>
    </div>
    ${t.descricao ? `<p class="ag-tf-desc">${esc(t.descricao)}</p>` : ""}
    <div class="ag-tf-pessoas">${pessoas.map((p) => pessoaHtml(t, p)).join("")}</div>
    <div class="ag-tf-prog">
      ${t.feita ? `<span class="chip ag-c-feita">${icone("visto")}Tarefa concluída ${quando(t.concluida_em, t.prazo)}</span>` : ""}
      <span>${t.total ? `${t.feitas} de ${plural(t.total, "subtarefa feita", "subtarefas feitas")}` : "Sem subtarefas"}</span>
      ${t.total ? barra(t.feitas, t.total - t.feitas) : ""}
    </div>
    ${t.eu_criador ? `<div class="ag-tf-acoes">
      <button class="btn" type="button" data-tf-concluir>${icone(t.feita ? "restaurar" : "visto")}${t.feita ? "Reabrir a tarefa" : "Concluir a tarefa"}</button>
      <button class="btn" type="button" data-tf-editar>${icone("lapis")}Editar</button>
      <button class="btn perigo" type="button" data-tf-excluir>${icone("lixeira")}Excluir</button>
    </div>` : ""}
    <span class="cf-rotulo ag-hist-rotulo">Subtarefas</span>
    ${lista || `<p class="ag-vazio">${icone("info")}Nenhuma subtarefa.</p>`}
    ${nova}
  </div>`;
  janela.inicial = janela.editando != null ? JSON.stringify(lerSubJanela()) : null;
}

// Uma pessoa da tarefa, no topo da janela; para quem criou, com o botão que cria uma subtarefa para ela.
function pessoaHtml(t, p) {
  const papel = p.criador ? " · criou" : p.autonomia ? " · autonomia" : "";
  if (!(t.eu_criador && t.pode.criar_subtarefa)) return `<span class="chip">${icone("usuario")}${esc(p.nome)}${papel}</span>`;
  const quem = p.criador ? "você" : esc(p.nome);
  return `<span class="ag-pessoa">${icone("usuario")}<b>${esc(p.nome)}</b>${papel ? `<small>${papel}</small>` : ""}
    <button type="button" class="ag-pessoa-sub" data-sub-nova data-para="${p.id}" title="Criar uma subtarefa para ${quem}"
      aria-label="Criar uma subtarefa para ${quem}">${icone("mais")}Subtarefa</button></span>`;
}

function subHtml(t, s) {
  if (janela.editando === s.id) return `<li class="ag-item-form">${formSubHtml(t, s)}</li>`;
  const dica = dicaCheck(t, s);
  return `<li class="ag-item ${s.feita ? "feita" : ""}" data-sub="${s.id}">
    <button type="button" class="ag-check ${s.feita ? "feita" : ""}" data-sub-check ${s.pode.concluir ? "" : "disabled"}
      aria-pressed="${s.feita}" title="${esc(dica)}" aria-label="${esc(dica)}: ${esc(s.titulo)}">${icone("visto")}</button>
    <div class="ag-item-t">
      <b>${esc(s.titulo)}</b>
      ${s.descricao ? `<p>${esc(s.descricao)}</p>` : ""}
      <div class="ag-chips">
        <span class="chip ${s.atrasada ? "ag-c-atrasada" : ""}">${icone(s.atrasada ? "alerta" : "relogio")}${s.atrasada ? "Venceu em" : "Até"} ${prazoTxt(s)}</span>
        ${s.feita ? `<span class="chip ag-c-feita">${icone("visto")}${textoConclusao(t, s, s.prazo)}</span>` : ""}
      </div>
    </div>
    <div class="ag-item-acoes">
      ${s.pode.editar_texto ? `<button type="button" data-sub-editar title="Editar a subtarefa" aria-label="Editar ${esc(s.titulo)}">${icone("lapis")}</button>` : ""}
    </div>
  </li>`;
}

// A subtarefa nova ou em edição, na janela: quem criou muda tudo; o participante com autonomia, só o texto.
function formSubHtml(t, s) {
  const pessoas = [t.criador, ...t.participantes];
  const v = s || { titulo: "", descricao: "", responsavel: pessoas.find((p) => p.id === janela.para) || t.criador,
                   prazo: t.prazo, hora: t.hora };
  const prazo = t.eu_criador ? `<div class="ag-sub-edit-campos">
      <label class="campo-form"><span>Responsável</span><span class="campo"><select data-campo="responsavel">${pessoas.map((p) =>
        `<option value="${p.id}" ${p.id === v.responsavel.id ? "selected" : ""}>${esc(p.nome)}${p.id === t.criador.id ? " (você)" : ""}</option>`).join("")}</select></span></label>
      <label class="campo-form"><span>Prazo</span><input type="date" data-campo="prazo" value="${v.prazo}" max="${t.prazo}"></label>
      <label class="campo-form"><span>Horário <small>(opcional)</small></span><input type="time" data-campo="hora" value="${v.hora || ""}"></label>
    </div>`
    : `<small class="ag-sub-prazo">${icone("cadeado")}Prazo: ${s ? prazoTxt(s) : `o da tarefa (${prazoTxt(t)})`}. Só ${esc(t.criador.nome)}, que criou a tarefa, muda.</small>`;
  return `<form class="ag-sub-edit" data-sub-form="${s ? s.id : "nova"}" novalidate>
    <label class="campo-form"><span>${s ? "Subtarefa" : "Nova subtarefa"}</span>
      <input data-campo="titulo" maxlength="120" autocomplete="off" value="${esc(v.titulo)}" placeholder="O que fazer"></label>
    <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
      <textarea data-campo="descricao" rows="2" maxlength="2000">${esc(v.descricao)}</textarea></label>
    ${prazo}
    <div class="ag-fb-acoes"><button class="btn" type="button" data-sub-cancelar>Cancelar</button>
      <button class="btn primario" type="submit">${icone(s ? "disco" : "mais")}${s ? "Salvar" : "Criar subtarefa"}</button></div>
  </form>`;
}

function lerSubJanela() {
  const f = dlg?.querySelector("[data-sub-form]");
  if (!f) return null;
  const v = {};
  f.querySelectorAll("[data-campo]").forEach((c) => { v[c.dataset.campo] = c.dataset.campo === "responsavel" ? Number(c.value) : c.value.trim(); });
  if ("hora" in v) v.hora = v.hora || null;
  return v;
}

const janelaMudou = () => !!dlg?.open && janela.inicial != null && JSON.stringify(lerSubJanela()) !== janela.inicial;

// A subtarefa vence até o prazo da tarefa (no mesmo dia, o horário só conta quando os dois têm).
const depoisDoPrazo = (s, t) => !!s.prazo && (s.prazo > t.prazo || (s.prazo === t.prazo && !!s.hora && !!t.hora && s.hora > t.hora));

function aoClicarJanela(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if ("fechar" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_SUB)) return;
    return dlg.close();
  }
  const t = janela.tarefa;
  if (!t) return;
  const s = b.closest("[data-sub]") ? subDe(t, Number(b.closest("[data-sub]").dataset.sub)) : null;
  if ("subNova" in b.dataset || "subEditar" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_SUB)) return;
    janela.editando = s ? s.id : "nova";
    janela.para = b.dataset.para ? Number(b.dataset.para) : null;
    desenharTarefa(t);
    return dlg.querySelector('[data-sub-form] [data-campo="titulo"]').focus();
  }
  if ("subCancelar" in b.dataset) {
    janela.editando = null;
    return desenharTarefa(t);
  }
  if ("subCheck" in b.dataset || "tfConcluir" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_SUB)) return;
    return s ? alternarSub(s) : alternarTarefa(t);
  }
  if ("tfEditar" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_SUB)) return;
    dlg.close();
    return editarTarefa(t);
  }
  if ("tfExcluir" in b.dataset) return excluirTarefa(t);
}

async function aoEnviarSub(e) {
  e.preventDefault();
  const f = e.target, t = janela.tarefa;
  const dados = lerSubJanela();
  if (!dados.titulo) {
    toast("Escreva o título da subtarefa", "erro");
    return f.querySelector('[data-campo="titulo"]').focus();
  }
  if (depoisDoPrazo(dados, t)) {
    toast(`A subtarefa vence depois da tarefa (${prazoTxt(t)}): o prazo dela vai até o da tarefa`, "erro");
    return f.querySelector('[data-campo="prazo"]').focus();
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const nova = f.dataset.subForm === "nova";
  const r = nova ? await mexer("/api/agenda/subtarefas", { id: t.id, subtarefa: dados }, "Subtarefa criada")
    : await mexer("/api/agenda/subtarefa/editar", { id: Number(f.dataset.subForm), subtarefa: dados }, "Subtarefa salva");
  if (!r && f.isConnected) botao.disabled = false;
}

// ---------- formulário ----------
function desenharForm(item = null, tipo = item ? item.tipo : estado.tipo) {
  estado.tipo = tipo;
  estado.editando = item;
  const ehTarefa = tipo === "tarefa";
  const nome = ehTarefa ? "tarefa" : "atividade";
  const el = raiz.querySelector("#ag-nova");
  el.setAttribute("aria-label", item ? `Editar ${nome}` : `${capitalizar(nome)} nova`);
  const dica = ehTarefa
    ? (item ? "Quem participa vê as mudanças na agenda; só você muda os prazos." : "Com prazo, participantes e subtarefas para cada um.")
    : (item ? "O que já foi concluído continua no histórico." : "Só você vê as atividades da sua agenda.");
  el.innerHTML = `<div class="ag-nova-cab">
      <h3>${icone(item ? "lapis" : ehTarefa ? "tarefa" : "mais")}${item ? `Editar ${nome}` : `Nova ${nome}`}</h3>
      <small>${dica}</small>
    </div>
    ${item ? "" : `<div class="seg-mini ag-tipo" role="group" aria-label="O que criar">${TIPOS.map(([k, n]) =>
      `<button type="button" data-tipo="${k}" class="${k === tipo ? "ativo" : ""}" aria-pressed="${k === tipo}">${n}</button>`).join("")}</div>`}
    <form id="ag-form" class="ag-form" novalidate>${ehTarefa ? formTarefa(item) : formAtividade(item)}</form>`;
  el.querySelector("form").addEventListener("submit", aoEnviar);
  if (ehTarefa) desenharSubs(); else mostrarCampos();
  estado.formInicial = JSON.stringify(coletar());
}

function formAtividade(a) {
  const inicio = a ? a.inicio : (estado.aberto || hojeLocal());
  const v = a || { titulo: "", descricao: "", inicio, hora: null, repeticao: "nenhuma", dias_semana: null, dia_mes: null,
                   intervalo: null, so_dias_uteis: false, regiao: null, fim: null, exige_feedback: false };
  estado.form = { repeticao: v.repeticao, dias: new Set(v.dias_semana || []), regiao: v.regiao || "ES" };
  return `<label class="campo-form"><span>Título</span>
        <input name="titulo" maxlength="120" autocomplete="off" value="${esc(v.titulo)}" placeholder="Ex.: Visitar o Mercado do João"></label>
      <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
        <textarea name="descricao" rows="2" maxlength="2000">${esc(v.descricao)}</textarea></label>
      <div class="campo-form"><span>Repetição</span>
        <div class="seg-mini ag-rep" role="group" aria-label="Repetição">${REPETICOES.map(([k, n]) =>
          `<button type="button" data-rep="${k}" class="${k === v.repeticao ? "ativo" : ""}" aria-pressed="${k === v.repeticao}">${n}</button>`).join("")}</div></div>
      <div class="ag-datas">
        <label class="campo-form"><span data-rotulo-inicio>${v.repeticao === "nenhuma" ? "Dia" : "Começa em"}</span>
          <input type="date" name="inicio" value="${v.inicio}"></label>
        <label class="campo-form"><span>Horário <small>(opcional)</small></span>
          <input type="time" name="hora" value="${v.hora || ""}"></label>
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
      </div>`;
}

// O formulário da tarefa. Participantes e subtarefas ficam em estado.tf (desenharPessoas e desenharSubs); os campos das
// linhas de subtarefa usam data-campo, não name: com nomes repetidos, f.elements.titulo deixaria de ser o da tarefa.
function formTarefa(t) {
  const eu = estado.pessoas.eu;
  estado.tf = {
    participantes: t ? t.participantes.map((p) => ({ id: p.id, nome: p.nome, autonomia: p.autonomia })) : [],
    subtarefas: t ? t.subtarefas.map((s) => ({ id: s.id, titulo: s.titulo, descricao: s.descricao, responsavel: s.responsavel.id,
                                               nome: s.responsavel.nome, prazo: s.prazo, hora: s.hora || "" })) : [],
  };
  return `<label class="campo-form"><span>Título</span>
        <input name="titulo" maxlength="120" autocomplete="off" value="${esc(t?.titulo || "")}" placeholder="Ex.: Preparar a feira de novembro"></label>
      <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
        <textarea name="descricao" rows="2" maxlength="2000">${esc(t?.descricao || "")}</textarea></label>
      <div class="ag-datas">
        <label class="campo-form"><span>Prazo</span>
          <input type="date" name="prazo" value="${t ? t.prazo : (estado.aberto || hojeLocal())}"></label>
        <label class="campo-form"><span>Horário <small>(opcional)</small></span>
          <input type="time" name="hora" value="${t?.hora || ""}"></label>
      </div>
      <div class="campo-form"><span>Participantes <small>(opcional)</small></span>
        <div class="ag-pessoas" id="ag-pessoas"></div>
        <span class="campo"><select data-add-pessoa aria-label="Adicionar participante"></select></span>
        <small>Com autonomia, a pessoa edita o texto das subtarefas dela e cria subtarefas para si. Prazos, só você muda.</small>
      </div>
      <div class="campo-form"><span>Subtarefas <small>(opcional; responsável ${esc(eu.nome)} ou um participante)</small></span>
        <div class="ag-subs" id="ag-subs"></div>
        <button class="btn ag-mais-sub" type="button" data-mais-sub>${icone("mais")}Subtarefa</button>
      </div>
      <div class="ag-form-acoes">
        ${t ? `<button class="btn" type="button" data-cancelar-edicao>Cancelar</button>` : ""}
        <button class="btn primario" type="submit">${icone(t ? "disco" : "mais")}${t ? "Salvar" : "Criar tarefa"}</button>
      </div>`;
}

function desenharPessoas() {
  const f = raiz.querySelector("#ag-form");
  const { participantes } = estado.tf;
  f.querySelector("#ag-pessoas").innerHTML = participantes.map((p) => `<span class="ag-pessoa">
      ${icone("usuario")}<b>${esc(p.nome)}</b>
      <button type="button" class="ag-pessoa-sub" data-sub-para="${p.id}" title="Criar uma subtarefa para ${esc(p.nome)}"
        aria-label="Criar uma subtarefa para ${esc(p.nome)}">${icone("mais")}Subtarefa</button>
      <button type="button" data-autonomia="${p.id}" aria-pressed="${p.autonomia}" class="${p.autonomia ? "ativo" : ""}"
        title="${p.autonomia ? "Com autonomia: edita o texto das subtarefas dele e cria subtarefas para si. Clique para tirar." : "Sem autonomia: só conclui as subtarefas dele. Clique para dar autonomia."}">${icone("chave")}Autonomia</button>
      <button type="button" data-tirar-pessoa="${p.id}" title="Tirar ${esc(p.nome)} da tarefa" aria-label="Tirar ${esc(p.nome)} da tarefa">${icone("x")}</button>
    </span>`).join("") || `<span class="ag-sem-pessoas">Só você, por enquanto.</span>`;
  const livres = estado.pessoas.pessoas.filter((p) => !participantes.some((q) => q.id === p.id));
  const sel = f.querySelector("[data-add-pessoa]");
  sel.innerHTML = `<option value="">${livres.length ? "Adicionar pessoa…" : "Ninguém mais com acesso à Gestão"}</option>` +
    livres.map((p) => `<option value="${p.id}">${esc(p.nome)}</option>`).join("");
  sel.disabled = !livres.length;
}

function desenharSubs() {
  desenharPessoas();
  const eu = estado.pessoas.eu;
  const opcoes = [{ id: eu.id, nome: `${eu.nome} (você)` }, ...estado.tf.participantes];
  raiz.querySelector("#ag-subs").innerHTML = estado.tf.subtarefas.map((s, n) => {
    const resp = opcoes.some((o) => o.id === s.responsavel) ? opcoes : [...opcoes, { id: s.responsavel, nome: s.nome }];
    return `<div class="ag-sub-linha" data-n="${n}">
      <div class="ag-sub-topo">
        <input data-campo="titulo" maxlength="120" autocomplete="off" value="${esc(s.titulo)}" placeholder="O que fazer" aria-label="Subtarefa ${n + 1}">
        <button type="button" class="ag-sub-tirar" data-tirar-sub="${n}" title="Tirar a subtarefa" aria-label="Tirar a subtarefa ${n + 1}">${icone("x")}</button>
      </div>
      <div class="ag-sub-campos">
        <span class="campo"><select data-campo="responsavel" aria-label="Responsável pela subtarefa ${n + 1}">${resp.map((o) =>
          `<option value="${o.id}" ${o.id === s.responsavel ? "selected" : ""}>${esc(o.nome)}</option>`).join("")}</select></span>
        <input type="date" data-campo="prazo" value="${s.prazo}" aria-label="Prazo da subtarefa ${n + 1}">
        <input type="time" data-campo="hora" value="${s.hora || ""}" aria-label="Horário da subtarefa ${n + 1} (opcional)">
      </div>
    </div>`;
  }).join("");
}

// Copia o que foi digitado nas linhas de subtarefa para estado.tf (antes de redesenhar ou de enviar).
function lerSubs() {
  raiz.querySelectorAll("#ag-subs .ag-sub-linha").forEach((linha) => {
    const s = estado.tf.subtarefas[Number(linha.dataset.n)];
    linha.querySelectorAll("[data-campo]").forEach((c) => { s[c.dataset.campo] = c.dataset.campo === "responsavel" ? Number(c.value) : c.value; });
  });
}

// Uma linha de subtarefa nova, com o prazo da tarefa; responsavel: o participante do botão ao lado do nome (sem ele, eu).
function maisSub(responsavel = estado.pessoas.eu.id) {
  lerSubs();
  const f = raiz.querySelector("#ag-form");
  const eu = estado.pessoas.eu;
  const nome = responsavel === eu.id ? eu.nome : estado.tf.participantes.find((p) => p.id === responsavel).nome;
  estado.tf.subtarefas.push({ id: null, titulo: "", descricao: "", responsavel, nome,
                              prazo: f.elements.prazo.value || hojeLocal(), hora: "" });
  desenharSubs();
  raiz.querySelector('#ag-subs .ag-sub-linha:last-child [data-campo="titulo"]').focus();
}

function tirarPessoa(id) {
  lerSubs();
  const p = estado.tf.participantes.find((x) => x.id === id);
  const n = estado.tf.subtarefas.filter((s) => s.responsavel === id).length;
  if (n) return toast(`Passe ${n === 1 ? "a subtarefa" : `as ${n} subtarefas`} de ${p.nome} para outra pessoa ou tire ${n === 1 ? "a subtarefa" : "as subtarefas"} antes`, "erro");
  estado.tf.participantes = estado.tf.participantes.filter((x) => x.id !== id);
  desenharSubs();
}

async function escolherTipo(tipo) {
  if (tipo === estado.tipo) return;
  if (formMudou() && !confirm(DESCARTAR_FORM)) return;
  if (tipo === "tarefa" && !(await garantirPessoas())) return;
  desenharForm(null, tipo);
  raiz.querySelector('#ag-form [name="titulo"]').focus();
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
  if (e.target.matches("[data-add-pessoa]") && e.target.value) {
    lerSubs();
    const p = estado.pessoas.pessoas.find((x) => x.id === Number(e.target.value));
    estado.tf.participantes.push({ id: p.id, nome: p.nome, autonomia: false });
    estado.tf.participantes.sort((a, b) => a.nome.localeCompare(b.nome));
    desenharSubs();
  }
}

// O dia do formulário acompanha o dia aberto; com o formulário intocado, isso não conta como alteração.
function definirDiaDoForm(dia) {
  const f = raiz.querySelector("#ag-form");
  if (!f || !dia) return;
  const intacto = !formMudou();
  (f.elements.inicio || f.elements.prazo).value = dia;
  if (intacto) estado.formInicial = JSON.stringify(coletar());
}

function coletar() {
  return estado.tipo === "tarefa" ? coletarTarefa() : coletarAtividade();
}

function coletarAtividade() {
  const f = raiz.querySelector("#ag-form");
  const rep = estado.form.repeticao;
  const uteis = rep === "diaria" && f.elements.so_dias_uteis.checked;
  const num = (n) => (f.elements[n].value === "" ? null : Number(f.elements[n].value));
  return {
    titulo: f.elements.titulo.value.trim(), descricao: f.elements.descricao.value.trim(), inicio: f.elements.inicio.value,
    hora: f.elements.hora.value || null, repeticao: rep, dias_semana: rep === "semanal" ? [...estado.form.dias].sort() : null,
    dia_mes: rep === "mensal" ? num("dia_mes") : null, intervalo: rep === "intervalo" ? num("intervalo") : null,
    so_dias_uteis: uteis, regiao: uteis ? estado.form.regiao : null,
    fim: rep !== "nenhuma" && f.elements.fim.value ? f.elements.fim.value : null,
    exige_feedback: f.elements.exige_feedback.checked,
  };
}

function coletarTarefa() {
  const f = raiz.querySelector("#ag-form");
  lerSubs();
  return {
    titulo: f.elements.titulo.value.trim(), descricao: f.elements.descricao.value.trim(),
    prazo: f.elements.prazo.value, hora: f.elements.hora.value || null,
    participantes: estado.tf.participantes.map((p) => ({ id: p.id, autonomia: p.autonomia })),
    subtarefas: estado.tf.subtarefas.map((s) => ({ id: s.id, titulo: s.titulo.trim(), descricao: s.descricao, responsavel: s.responsavel,
                                                   prazo: s.prazo, hora: s.hora || null })),
  };
}

function formMudou() {
  return !!raiz?.querySelector("#ag-form") && JSON.stringify(coletar()) !== estado.formInicial;
}

function editar(a) {
  if (!editandoEste("atividade", a.id) && formMudou() && !confirm(DESCARTAR_FORM)) return;
  desenharForm({ ...a, tipo: "atividade" });
  raiz.querySelector("#ag-nova").scrollIntoView({ behavior: "smooth", block: "nearest" });
  raiz.querySelector('#ag-form [name="titulo"]').focus();
}

function cancelarEdicao() {
  desenharForm();
}

async function aoEnviar(e) {
  e.preventDefault();
  const f = e.target;
  if (estado.tipo === "tarefa") return enviarTarefa(f);
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

async function enviarTarefa(f) {
  const dados = coletar();
  if (!dados.titulo) { toast("Escreva o título da tarefa", "erro"); return f.elements.titulo.focus(); }
  if (!dados.prazo) { toast("Escolha o prazo da tarefa", "erro"); return f.elements.prazo.focus(); }
  const linhas = f.querySelectorAll(".ag-sub-linha");
  for (const [n, s] of dados.subtarefas.entries()) {
    if (!s.titulo) { toast("Escreva o título da subtarefa", "erro"); return linhas[n].querySelector('[data-campo="titulo"]').focus(); }
    if (depoisDoPrazo(s, dados)) {
      toast(`A subtarefa "${s.titulo}" vence depois da tarefa: o prazo dela vai até o da tarefa`, "erro");
      return linhas[n].querySelector('[data-campo="prazo"]').focus();
    }
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const editando = estado.editando;
  try {
    if (editando) await api("/api/agenda/tarefa/editar", { json: { id: editando.id, versao: editando.versao, tarefa: dados } });
    else await api("/api/agenda/tarefas", { json: { tarefa: dados } });
    toast(editando ? "Tarefa salva" : "Tarefa criada");
    desenharForm();
    await (editando ? carregar() : carregar(mesDe(dados.prazo), { aberto: dados.prazo }));
  } catch (err) {
    botao.disabled = false;
    toast(err.message, "erro");
  }
}
