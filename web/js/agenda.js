// Minha agenda, no topo da página Gestão (gestao.js monta): as atividades de cada pessoa (só ela vê) e as tarefas de que
// ela participa, na faixa de dias do mês (a mesma do "Ritmo do mês" da página Metas), com o dia de hoje num quadrado
// maior. Cada quadrado mostra quantos itens o dia tem e, numa barrinha, os feitos (verde) e os que faltam (laranja;
// vermelho se o dia passou). Clicar num dia amplia o painel com o que há nele (os com horário primeiro).
// - Atividade: concluir (com o feedback, obrigatório quando a atividade pede), editar o feedback, desfazer e, nas que
//   se repetem, o histórico de tudo o que foi feito.
// - Tarefa: aparece no dia do prazo; cada subtarefa, no dia do prazo dela (quem criou vê todas; o participante, as
//   dele). A janela da tarefa mostra a situação dela (A fazer, Fazendo, Concluída) e um card por pessoa com as
//   subtarefas dela, de todos: cada um muda a situação das suas e, com autonomia, edita o texto delas e cria
//   subtarefas para si. No dia de hoje, um bloco lista as tarefas e subtarefas atrasadas. Passado o prazo, quem
//   responde por ela (quem criou a tarefa; o responsável pela subtarefa) justifica o atraso, que todos veem.
// - Kanban (a outra vista, no lugar da faixa e do dia): as tarefas em A fazer, Fazendo e Concluída. Qualquer pessoa da
//   tarefa arrasta o card de coluna (e muda a situação dela na janela); clicar abre a janela da tarefa.
// O botão Nova (e o Novo neste dia) abre em tela cheia o formulário de atividade nova (única, diária, semanal, mensal
// ou a cada N dias, com horário opcional) ou de tarefa nova (prazo e um card por pessoa, com ou sem autonomia, com as
// subtarefas dela; a seta recolhe o card), que também edita uma atividade ou uma tarefa. Os dias se escolhem numa faixa
// de quadradinhos como a da agenda (escolherdia.js), que mostra quanto cada dia já tem.
// Recolhida, fica só a faixa de dias (a escolha, e a vista, ficam guardadas neste navegador). #/gestao?dia=AAAA-MM-DD
// abre a agenda nesse dia (o link das propostas do Assistente). Em que dias cada atividade acontece, o texto da
// repetição ("Toda segunda e quinta") e o que cada pessoa pode fazer numa tarefa vêm do servidor (bi/agenda.py e
// bi/tarefas.py).
import { campoDia, contarDias, focarDia, limitesDoDia, prepararDias, redesenharDias } from "./escolherdia.js";
import { MESES, api, esc, fmt, guardar, icone, ler, ligarTooltips, linhaTT, toast } from "./util.js";

const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const DIAS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]]; // date.isoweekday()
const MAX_SEGMENTOS = 6; // até aqui, a barrinha do dia tem um pedaço por item; acima, só as duas partes
const MAX_TOOLTIP = 6;   // itens listados no tooltip do dia
const REPETICOES = [["nenhuma", "Única"], ["diaria", "Diária"], ["semanal", "Semanal"], ["mensal", "Mensal"], ["intervalo", "A cada N dias"]];
const TIPOS = [["atividade", "Atividade"], ["tarefa", "Tarefa"]];
const VISTAS = [["agenda", "Agenda", "calendario"], ["quadro", "Kanban", "quadro"]];
// A situação de uma tarefa ou subtarefa (a coluna do kanban): o nome, o ícone e o aviso ao mover a tarefa.
const SITUACOES = [["a_fazer", "A fazer"], ["fazendo", "Fazendo"], ["concluida", "Concluída"]];
const NOME_SITUACAO = Object.fromEntries(SITUACOES);
const ICONE_SITUACAO = { a_fazer: "menos", fazendo: "relogio", concluida: "certo" };
const MOVIDA = { a_fazer: "Tarefa em A fazer", fazendo: "Tarefa em Fazendo", concluida: "Tarefa concluída" };
const COLUNA_VAZIA = { a_fazer: "Nenhuma tarefa a fazer", fazendo: "Nenhuma tarefa sendo feita", concluida: "Nenhuma concluída há pouco" };
const DESCARTAR_FB = "Descartar o feedback que você estava escrevendo?";
const DESCARTAR_FORM = "Descartar o que foi preenchido no formulário?";
const DESCARTAR_JANELA = "Descartar o que você estava escrevendo na tarefa?";
const CHAVE_RECOLHIDA = "mv-agenda-recolhida";
const CHAVE_VISTA = "mv-agenda-vista";

let raiz = null, dlg = null, tela = null; // tela: a janela em tela cheia do formulário (dentro de #ag-raiz)
// tipo: o do formulário (atividade ou tarefa); tf: os participantes e as subtarefas do formulário da tarefa;
// pessoas: quem pode participar ({eu, pessoas}, carregado na primeira tarefa); editando: {tipo, ...o item}; formDia: o
// dia em que o formulário abriu. vista: agenda ou quadro (o kanban, com as tarefas de estado.quadro); arrastando: a
// tarefa cujo card está sendo arrastado. meses: a contagem de cada dia dos meses já vistos, para escolher o dia.
const estado = { mes: null, dados: null, aberto: null, editando: null, concluindo: null, form: null, formInicial: null, pedido: 0,
                 tipo: "atividade", tf: null, pessoas: null, formDia: null, vista: "agenda", quadro: null, pedidoQuadro: 0,
                 arrastando: null, meses: new Map() };
// A janela da tarefa: a tarefa aberta, a subtarefa em edição (id, "nova" ou null), a justificativa de atraso sendo
// escrita ("tarefa", o id da subtarefa ou null; uma edição de cada vez), como o que está aberto começou, na subtarefa
// nova, para quem (o card em que ela foi aberta) e os cards de pessoa recolhidos.
const janela = { tarefa: null, editando: null, justificando: null, inicial: null, para: null, recolhidos: new Set() };
const JANELA_VAZIA = () => ({ tarefa: null, editando: null, justificando: null, inicial: null, para: null, recolhidos: new Set() });

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

// dia: o dia a abrir (#/gestao?dia=…, sempre na vista da agenda); sem ele, hoje.
export function montarAgenda(el, { dia } = {}) {
  el.innerHTML = `<section class="cartao ag-cal entra" style="--i:0" id="ag-raiz">
      <div class="cartao-cab">
        <div><h2>${icone("calendario")}Minha agenda<span class="ag-mes" id="ag-titulo"></span></h2>
          <p class="sub" id="ag-resumo">&nbsp;</p></div>
        <div class="ag-nav">
          <div class="seg-mini ag-vista" role="group" aria-label="Ver como">${VISTAS.map(([k, n, ic]) =>
            `<button type="button" data-vista="${k}">${icone(ic)}${n}</button>`).join("")}</div>
          <button class="btn primario" type="button" data-novo>${icone("mais")}Nova</button>
          <span class="ag-meses">
            <button class="btn icone" type="button" data-mes="-1" title="Mês anterior" aria-label="Mês anterior">${icone("voltar")}</button>
            <button class="btn" type="button" data-hoje>Hoje</button>
            <button class="btn icone" type="button" data-mes="1" title="Próximo mês" aria-label="Próximo mês">${icone("seta")}</button>
          </span>
          <button class="btn icone" type="button" data-recolher aria-controls="ag-baixo"></button>
        </div>
      </div>
      <div id="ag-faixa"><div class="esqueleto" style="height:96px"></div></div>
      <div class="ag-baixo" id="ag-baixo"><div id="ag-dia"></div></div>
      <div class="ag-quadro" id="ag-quadro"></div>
      <dialog class="ag-tela" id="ag-tela" aria-labelledby="ag-tela-titulo"></dialog>
    </section>`;
  raiz = el.querySelector("#ag-raiz");
  tela = raiz.querySelector("#ag-tela");
  raiz.addEventListener("click", aoClicar);
  raiz.addEventListener("change", aoMudar);
  raiz.addEventListener("keydown", aoTeclar);
  raiz.addEventListener("dragstart", aoArrastar);
  raiz.addEventListener("dragover", aoPassar);
  raiz.addEventListener("drop", aoSoltar);
  raiz.addEventListener("dragend", fimDoArraste);
  tela.addEventListener("cancel", (e) => { if (formMudou() && !confirm(DESCARTAR_FORM)) e.preventDefault(); });
  tela.addEventListener("close", () => {
    tela.innerHTML = "";
    Object.assign(estado, { editando: null, tf: null, formInicial: null });
  });
  const valido = ehDia(dia);
  Object.assign(estado, { mes: null, dados: null, aberto: null, editando: null, concluindo: null, tipo: "atividade", tf: null,
                          pessoas: null, quadro: null, meses: new Map(), vista: valido ? "agenda" : ler(CHAVE_VISTA, "agenda") });
  contarDias(contagem);
  recolher(ler(CHAVE_RECOLHIDA, false));
  escolherVista(estado.vista);
  carregar(valido ? mesDe(dia) : undefined, { aberto: valido ? dia : undefined });
}

// O link de uma proposta do Assistente (#/gestao?dia=…) com a Gestão já montada: abre a agenda nesse dia.
export function abrirNaAgenda(dia) {
  if (!raiz?.isConnected || !ehDia(dia)) return;
  if (raiz.classList.contains("recolhida")) recolher(false);
  if (estado.vista !== "agenda") escolherVista("agenda");
  estado.concluindo = null;
  carregar(mesDe(dia), { aberto: dia });
  raiz.scrollIntoView({ behavior: "smooth", block: "start" });
}

// A Gestão chama ao voltar para a página: o dia de hoje (e o que foi feito em outro aparelho) pode ter mudado.
export function recarregarAgenda() {
  if (raiz?.isConnected && estado.dados) recarregarTudo();
}

// Depois de uma mudança: a agenda e, se ele está à vista, o kanban.
function recarregarTudo() {
  return Promise.all([carregar(), estado.vista === "quadro" ? carregarQuadro() : null]);
}

// Recolhida: só a faixa de dias (no kanban, só o cabeçalho) até abrir de novo (ou clicar num dia).
function recolher(sim) {
  raiz.classList.toggle("recolhida", sim);
  const b = raiz.querySelector("[data-recolher]");
  const dica = sim ? "Mostrar a agenda" : "Recolher a agenda";
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
    // a contagem dos outros meses pode ter mudado junto: o que for preciso é pedido de novo
    estado.meses = new Map([[d.mes, contagemDoMes(d)]]);
    desenharFaixa(mesmoMes);
    desenharDia(!mesmoMes);
    if (tela.open) redesenharDias();
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (!estado.dados) raiz.querySelector("#ag-faixa").innerHTML = `<div class="vazio">${icone("alerta")}<p>${esc(e.message)}</p></div>`;
    toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) blocos.forEach((b) => b.classList.remove("recarregando"));
  }
}

// Os quadradinhos de escolher dia contam como a faixa: quantos itens o dia tem e se está tudo feito ou ficou atrasado.
function contagemDoMes(d) {
  const r = {};
  for (const x of d.dias) {
    const lista = todos(x);
    const faltam = lista.filter((i) => !i.feita).length;
    if (lista.length) r[x.data] = { n: lista.length, classe: !faltam ? "feita" : x.data < d.hoje ? "atrasada" : "tem" };
  }
  return r;
}

// A contagem de um dia (escolherdia.js pergunta); o mês ainda não visto é pedido uma vez só e redesenha ao chegar.
function contagem(dia) {
  const mes = mesDe(dia);
  if (!estado.meses.has(mes)) pedirMes(mes);
  return estado.meses.get(mes)?.[dia] || null;
}

async function pedirMes(mes) {
  const meses = estado.meses;
  meses.set(mes, null);
  try {
    const d = await api(`/api/agenda?mes=${mes}`);
    if (meses !== estado.meses) return; // a agenda recarregou nesse meio-tempo
    meses.set(mes, contagemDoMes(d));
    redesenharDias();
  } catch { /* sem a contagem, os dias desse mês aparecem sem o número */ }
}

// O título e o resumo do cabeçalho: os do mês (agenda) ou os do kanban.
function escreverCabecalho() {
  const titulo = raiz.querySelector("#ag-titulo"), resumo = raiz.querySelector("#ag-resumo");
  if (estado.vista === "quadro") {
    titulo.textContent = "Kanban das tarefas";
    if (!estado.quadro) return;
    const conta = (k) => estado.quadro.tarefas.filter((t) => t.situacao === k).length;
    const atrasadas = estado.quadro.tarefas.filter((t) => t.atrasada).length;
    resumo.textContent = estado.quadro.tarefas.length
      ? `${fmt.num(conta("a_fazer"))} a fazer · ${fmt.num(conta("fazendo"))} fazendo · ${plural(conta("concluida"), "concluída", "concluídas")} há pouco${atrasadas ? ` · ${plural(atrasadas, "atrasada", "atrasadas")}` : ""}`
      : "Nenhuma tarefa por aqui";
    return;
  }
  const d = estado.dados;
  if (!d) return;
  const [ano, m] = d.mes.split("-").map(Number);
  titulo.textContent = `${capitalizar(MESES[m - 1])} de ${ano}`;
  let atividades = 0, tarefas = 0, feitas = 0, atrasadas = 0;
  for (const x of d.dias) {
    atividades += x.itens.length;
    tarefas += x.tarefas.length;
    feitas += todos(x).filter((i) => i.feita).length;
    if (x.data < d.hoje) atrasadas += todos(x).filter((i) => !i.feita).length;
  }
  const partes = [atividades && plural(atividades, "atividade", "atividades"), tarefas && plural(tarefas, "tarefa", "tarefas")].filter(Boolean);
  resumo.textContent = partes.length
    ? `${partes.join(" e ")} no mês · ${plural(feitas, "concluída", "concluídas")}${atrasadas ? ` · ${fmt.num(atrasadas)} sem concluir` : ""}`
    : "Nada marcado neste mês";
}

// ---------- faixa de dias ----------
function desenharFaixa(quieta) {
  const d = estado.dados;
  const m = Number(d.mes.slice(5));
  escreverCabecalho();
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

// Por que o check (ou a situação) de uma tarefa ou subtarefa está ou não liberado.
function dicaCheck(t, s, faz = "conclui") {
  const x = s || t;
  // a tarefa, qualquer pessoa dela conclui e reabre: o que não está liberado é sempre uma subtarefa
  if ((s ? s.pode : t.pode).concluir) return x.feita ? (s ? "Desfazer a conclusão" : "Reabrir a tarefa") : "Marcar como concluída";
  if (s.pela_tarefa) return "Concluída junto com a tarefa";
  if (t.feita) return "A tarefa foi concluída; reabra a tarefa para mudar";
  return `Só ${s.responsavel.nome} (o responsável) ou ${t.criador.nome} (quem criou) ${faz}`;
}

// A situação (A fazer, Fazendo, Concluída): os botões para quem pode mudar, senão só o chip.
function situacaoHtml(x, attr, rotulo, pode, dica) {
  if (!pode) return `<span class="chip ag-c-${x.situacao}" title="${esc(dica)}">${icone(ICONE_SITUACAO[x.situacao])}${NOME_SITUACAO[x.situacao]}</span>`;
  return `<div class="seg-mini ag-situacao" role="group" aria-label="${esc(rotulo)}">${SITUACOES.map(([k, n]) =>
    `<button type="button" ${attr}="${k}" class="st-${k} ${k === x.situacao ? "ativo" : ""}" aria-pressed="${k === x.situacao}">${icone(ICONE_SITUACAO[k])}${n}</button>`).join("")}</div>`;
}

// "Concluída por Beto às 14:03", "Concluída junto com a tarefa" (sem o "por" quando foi você, na tarefa, ou o
// responsável, na sua subtarefa).
function textoConclusao(t, s, dia) {
  if (s?.pela_tarefa) return "Concluída junto com a tarefa";
  const x = s || t, quem = x.concluida_por;
  const proprio = s ? s.minha && quem?.id === s.responsavel.id : quem?.id === t.eu;
  return `Concluída${quem && !proprio ? ` por ${esc(quem.nome)}` : ""} ${quando(x.concluida_em, dia)}`;
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
    x.situacao === "fazendo" ? `<span class="chip ag-c-fazendo">${icone("relogio")}Fazendo</span>` : "",
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
      ${x.justificativa ? justHtml(x, s ? s.justificada_por?.nome : t.criador.nome,
          x.pode.justificar ? `<button type="button" class="ge-link" data-justificar>Editar</button>` : "")
        : x.pode.justificar ? `<button type="button" class="ge-link ag-just-abrir" data-justificar>${icone("conversa")}Justificar o atraso</button>` : ""}
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
  const card = e.target.closest(".ag-card");
  if (card && !e.target.closest("button")) return abrirTarefa(Number(card.dataset.card));
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if (b.dataset.dia && b.closest(".ag-faixa")) return abrirDia(b.dataset.dia);
  if ("recolher" in b.dataset) return recolher(!raiz.classList.contains("recolhida"));
  if (b.dataset.vista) {
    if (raiz.classList.contains("recolhida")) recolher(false);
    return escolherVista(b.dataset.vista);
  }
  if (b.dataset.mes || "hoje" in b.dataset) {
    if (feedbackEscrito() && !confirm(DESCARTAR_FB)) return;
    estado.concluindo = null;
    const hoje = estado.dados?.hoje || hojeLocal();
    return "hoje" in b.dataset ? carregar(mesDe(hoje), { aberto: hoje }) : carregar(somarMes(estado.mes, Number(b.dataset.mes)));
  }
  // no kanban, Nova é tarefa; na agenda, o último tipo escolhido
  if ("novo" in b.dataset) return abrirForm(null, estado.vista === "quadro" ? "tarefa" : estado.tipo);
  if ("novoNoDia" in b.dataset) return abrirForm(null, estado.tipo);
  if ("fecharForm" in b.dataset) return fecharForm();
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
  if (b.dataset.subPara) return maisSub(Number(b.dataset.subPara));
  if (b.dataset.recolherPessoa) return alternarCard(b, estado.tf.recolhidos);
  if (b.dataset.abrirSub) {
    abrirSub(Number(b.dataset.abrirSub));
    return raiz.querySelector(`#ag-pessoas .ag-sub-linha[data-n="${b.dataset.abrirSub}"] [data-campo="titulo"]`).focus();
  }
  if ("fecharSub" in b.dataset) return abrirSub(null);
  if (b.dataset.tirarSub) {
    lerSubs();
    const n = Number(b.dataset.tirarSub), aberta = estado.tf.aberta;
    estado.tf.subtarefas.splice(n, 1);
    estado.tf.aberta = aberta == null || aberta === n ? null : aberta > n ? aberta - 1 : aberta;
    return desenharPessoas();
  }
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
  if ("justificar" in b.dataset) return abrirTarefa(t.id, { justificar: s ? s.id : "tarefa" }); // escreve na janela
  if ("editar" in b.dataset) return editarTarefa(t);
  if ("excluir" in b.dataset) return excluirTarefa(t);
}

function aoTeclar(e) {
  const t = e.target;
  if (t.matches(".ag-card") && (e.key === "Enter" || e.key === " ")) {
    e.preventDefault();
    return abrirTarefa(Number(t.dataset.card));
  }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && t.closest("#ag-form")) {
    e.preventDefault();
    return t.closest("form").requestSubmit();
  }
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
    toast("Atividade excluída");
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

// ---------- tarefas ----------
// Grava uma mudança numa tarefa; a resposta traz a tarefa como ficou, que redesenha a janela (se for a aberta).
async function mexer(url, json, aviso) {
  try {
    const r = await api(url, { json });
    if (aviso) toast(aviso);
    if (r.tarefa && dlg?.open && janela.tarefa?.id === r.tarefa.id) {
      Object.assign(janela, { editando: null, justificando: null });
      desenharTarefa(r.tarefa);
    }
    await recarregarTudo();
    return r;
  } catch (e) {
    toast(e.message, "erro");
    if (e.status === 404 && dlg?.open && janela.tarefa) dlg.close(); // a tarefa saiu (ou a pessoa saiu dela) em outro lugar
    recarregarTudo();
    return null;
  }
}

function alternarSub(s) {
  return mexer(`/api/agenda/subtarefa/${s.feita ? "desfazer" : "concluir"}`, { id: s.id });
}

// Concluir com subtarefas abertas: elas passam a contar como feitas (pergunta antes).
function podeConcluir(t) {
  const abertas = t.total - t.feitas;
  return !abertas || confirm(`Concluir "${t.titulo}"? ${abertas === 1 ? "A subtarefa que falta passa" : `As ${abertas} subtarefas que faltam passam`} a contar como feita${abertas === 1 ? "" : "s"} (reabrindo a tarefa, elas voltam).`);
}

function alternarTarefa(t) {
  if (!t.feita && !podeConcluir(t)) return;
  return mexer(`/api/agenda/tarefa/${t.feita ? "desfazer" : "concluir"}`, { id: t.id }, t.feita ? "Tarefa reaberta" : "Tarefa concluída");
}

// Leva a tarefa para outra coluna (arrastando o card ou na janela dela). No kanban, o card já muda de lugar; a
// resposta confirma (ou o recarregar devolve ele).
function moverTarefa(t, situacao) {
  if (situacao === t.situacao || (situacao === "concluida" && !podeConcluir(t))) return;
  const card = estado.quadro?.tarefas.find((x) => x.id === t.id);
  if (card) {
    card.situacao = situacao;
    if (estado.vista === "quadro") desenharQuadro(false);
  }
  return mexer("/api/agenda/tarefa/mover", { id: t.id, situacao }, MOVIDA[situacao]);
}

async function excluirTarefa(t) {
  const subs = t.total ? ` ${t.total === 1 ? "A subtarefa sai" : `As ${t.total} subtarefas saem`} junto.` : "";
  const outros = t.participantes.length ? " Ela some da agenda de todos os participantes." : "";
  if (!confirm(`Excluir a tarefa "${t.titulo}"?${subs}${outros}`)) return;
  if (dlg?.open && janela.tarefa?.id === t.id) dlg.close();
  await mexer("/api/agenda/tarefa/excluir", { id: t.id }, "Tarefa excluída");
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

function editarTarefa(t) {
  return abrirForm({ ...t, tipo: "tarefa" });
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
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && e.target.closest("[data-sub-form], [data-just-form]")) {
      e.preventDefault();
      e.target.closest("form").requestSubmit();
    }
  });
  dlg.addEventListener("cancel", (e) => { if (janelaMudou() && !confirm(DESCARTAR_JANELA)) e.preventDefault(); });
  dlg.addEventListener("close", () => Object.assign(janela, JANELA_VAZIA()));
}

async function abrirHistorico(a) {
  let h;
  try {
    h = await api(`/api/agenda/historico?id=${a.id}`);
  } catch (e) { return toast(e.message, "erro"); }
  criarJanela();
  Object.assign(janela, JANELA_VAZIA());
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

// justificar: abre já escrevendo a justificativa do atraso ("tarefa" ou o id da subtarefa), se a pessoa pode.
async function abrirTarefa(id, { justificar = null } = {}) {
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
  if (janela.tarefa?.id !== t.id) janela.recolhidos = new Set();
  const alvo = justificar === "tarefa" ? t : subDe(t, justificar);
  Object.assign(janela, { editando: null, justificando: alvo?.pode.justificar ? justificar : null });
  desenharTarefa(t);
  if (!dlg.open) dlg.showModal();
  dlg.querySelector("[data-just-form] textarea")?.focus();
}

// As pessoas da tarefa, cada uma num card com as subtarefas dela: você primeiro, depois quem criou e os outros, pelo nome.
function pessoasDaTarefa(t) {
  const ordem = (p) => (p.voce ? 0 : p.criador ? 1 : 2);
  return [{ ...t.criador, criador: true }, ...t.participantes].map((p) => ({ ...p, voce: p.id === t.eu }))
    .sort((a, b) => ordem(a) - ordem(b) || a.nome.localeCompare(b.nome));
}

function cartaoTarefa(t, p) {
  const subs = t.subtarefas.filter((s) => s.responsavel.id === p.id);
  const feitas = subs.filter((s) => s.feita).length;
  const recolhido = janela.recolhidos.has(p.id);
  const quem = p.voce ? "você" : esc(p.nome);
  const resumo = subs.length ? `${feitas} de ${subs.length} ${subs.length === 1 ? "feita" : "feitas"}` : "sem subtarefas";
  // quem criou acrescenta para qualquer pessoa; o participante com autonomia, só no próprio card
  const criar = !t.pode.criar_subtarefa || !(t.eu_criador || p.voce) ? ""
    : janela.editando === "nova" && janela.para === p.id ? formSubHtml(t, null)
    : `<button type="button" class="ag-pessoa-op ag-pessoa-sub" data-sub-nova data-para="${p.id}" title="Criar uma subtarefa para ${quem}"
        aria-label="Criar uma subtarefa para ${quem}">${icone("mais")}Subtarefa</button>`;
  return `<section class="ag-pessoa-card ${recolhido ? "recolhido" : ""}">
    <div class="ag-pessoa-cab">${nomeDoCard(p, resumo, recolhido, p.criador ? "· criou" : p.autonomia ? "· autonomia" : "")}</div>
    <div class="ag-pessoa-corpo">${subs.length ? `<ul class="ag-itens">${subs.map((s) => subHtml(t, s)).join("")}</ul>` : ""}${criar}</div>
  </section>`;
}

// A janela da tarefa: o que ela é, a situação (qualquer pessoa dela muda: A fazer, Fazendo ou Concluída), o andamento
// e um card por pessoa, com as subtarefas dela e a situação de cada uma.
function desenharTarefa(t) {
  janela.tarefa = t;
  const fazendo = t.subtarefas.filter((s) => s.situacao === "fazendo").length;
  dlg.innerHTML = `<div class="ag-tf">
    <div class="ag-hist-cab">
      <div><h2 id="ag-tf-titulo">${icone("tarefa")}${esc(t.titulo)}</h2>
        <p class="sub">Prazo: ${prazoTxt(t)}${t.atrasada ? ` <span class="chip ag-c-atrasada">${icone("alerta")}atrasada</span>` : ""}
          · criada por ${t.eu_criador ? "você" : esc(t.criador.nome)}</p></div>
      <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar">${icone("x")}</button>
    </div>
    ${t.descricao ? `<p class="ag-tf-desc">${esc(t.descricao)}</p>` : ""}
    <div class="ag-tf-prog">
      ${situacaoHtml(t, "data-tf-situacao", "Situação da tarefa", t.pode.concluir, dicaCheck(t, null, "muda a situação"))}
      ${t.feita ? `<span class="chip ag-c-feita">${icone("visto")}${textoConclusao(t, null, t.prazo)}</span>` : ""}
      <span>${t.total ? `${t.feitas} de ${plural(t.total, "subtarefa feita", "subtarefas feitas")}${fazendo ? ` · ${fazendo} fazendo` : ""}` : "Sem subtarefas"}</span>
      ${t.total ? barra(t.feitas, t.total - t.feitas) : ""}
    </div>
    ${blocoJust(t, "tarefa", t.criador.nome)}
    ${t.eu_criador ? `<div class="ag-tf-acoes">
      <button class="btn" type="button" data-tf-editar>${icone("lapis")}Editar</button>
      <button class="btn perigo" type="button" data-tf-excluir>${icone("lixeira")}Excluir</button>
    </div>` : ""}
    <span class="cf-rotulo ag-hist-rotulo">Pessoas e subtarefas</span>
    <div class="ag-pessoas">${pessoasDaTarefa(t).map((p) => cartaoTarefa(t, p)).join("")}</div>
  </div>`;
  prepararDias(dlg);
  janela.inicial = janela.editando != null || janela.justificando != null ? JSON.stringify(lerEdicaoJanela()) : null;
}

function subHtml(t, s) {
  if (janela.editando === s.id) return `<li class="ag-item-form">${formSubHtml(t, s)}</li>`;
  return `<li class="ag-item ag-sub-item st-${s.situacao}" data-sub="${s.id}">
    <div class="ag-item-t">
      <b>${esc(s.titulo)}</b>
      ${s.descricao ? `<p>${esc(s.descricao)}</p>` : ""}
      <div class="ag-chips">
        <span class="chip ${s.atrasada ? "ag-c-atrasada" : ""}">${icone(s.atrasada ? "alerta" : "relogio")}${s.atrasada ? "Venceu em" : "Até"} ${prazoTxt(s)}</span>
        ${s.feita ? `<span class="chip ag-c-feita">${icone("visto")}${textoConclusao(t, s, s.prazo)}</span>` : ""}
      </div>
      <div class="ag-sub-st">${situacaoHtml(s, "data-sub-situacao", `Situação de ${s.titulo}`, s.pode.concluir, dicaCheck(t, s, "mudam a situação"))}</div>
      ${blocoJust(s, s.id, s.justificada_por?.nome)}
    </div>
    <div class="ag-item-acoes">
      ${s.pode.editar_texto ? `<button type="button" data-sub-editar title="Editar a subtarefa" aria-label="Editar ${esc(s.titulo)}">${icone("lapis")}</button>` : ""}
    </div>
  </li>`;
}

// A justificativa do atraso de x (a tarefa ou uma subtarefa; todos da tarefa veem): o texto, de quem e quando, e o
// que vier junto (o Editar).
function justHtml(x, quem, extra = "") {
  if (!x.justificativa) return "";
  return `<div class="ag-just"><p>${icone("conversa")}<span>${esc(x.justificativa)}</span></p>
    <small><span>Justificativa do atraso${quem ? ` · ${esc(quem)}` : ""}${x.justificada_em ? `, ${quando(x.justificada_em, x.prazo)}` : ""}</span>${extra}</small></div>`;
}

// Na janela: o formulário (se está aberto), a justificativa com o Editar ou, se ainda não tem e a pessoa pode, o botão.
// alvo: "tarefa" ou o id da subtarefa.
function blocoJust(x, alvo, quem) {
  if (janela.justificando === alvo) return formJustHtml(x, alvo);
  if (x.justificativa) return justHtml(x, quem, x.pode.justificar ? `<button type="button" class="ge-link" data-just="${alvo}">Editar</button>` : "");
  return x.pode.justificar ? `<button type="button" class="ge-link ag-just-abrir" data-just="${alvo}">${icone("conversa")}Justificar o atraso</button>` : "";
}

function formJustHtml(x, alvo) {
  return `<form class="ag-fb ag-just-form" data-just-form="${alvo}" novalidate>
    <textarea data-campo="justificativa" rows="2" maxlength="2000" aria-label="Justificativa do atraso"
      placeholder="Por que atrasou? Todos da tarefa veem.">${esc(x.justificativa)}</textarea>
    <div class="ag-fb-acoes"><button class="btn" type="button" data-just-cancelar>Cancelar</button>
      <button class="btn primario" type="submit">${icone("disco")}Salvar justificativa</button></div>
  </form>`;
}

// A subtarefa nova (no card da pessoa) ou em edição, na janela: quem criou muda tudo (na edição, até passar para outra
// pessoa); o participante com autonomia, só o texto.
function formSubHtml(t, s) {
  const pessoas = [t.criador, ...t.participantes];
  const v = s || { titulo: "", descricao: "", responsavel: pessoas.find((p) => p.id === janela.para) || t.criador,
                   prazo: t.prazo, hora: t.hora };
  const responsavel = s ? `<label class="campo-form"><span>Responsável</span><span class="campo"><select data-campo="responsavel">${pessoas.map((p) =>
      `<option value="${p.id}" ${p.id === v.responsavel.id ? "selected" : ""}>${esc(p.nome)}${p.id === t.criador.id ? " (você)" : ""}</option>`).join("")}</select></span></label>`
    : `<input type="hidden" data-campo="responsavel" value="${v.responsavel.id}">`;
  const prazo = t.eu_criador ? `<div class="ag-sub-edit-campos ${s ? "" : "sem-responsavel"}">
      ${responsavel}
      <label class="campo-form"><span>Horário <small>(opcional)</small></span><input type="time" data-campo="hora" value="${v.hora || ""}"></label>
    </div>
    <div class="campo-form"><span>Prazo</span>${campoDia({ campo: "prazo", valor: v.prazo, max: t.prazo, maxDica: "Depois do prazo da tarefa",
      rotulo: "Prazo da subtarefa", contar: v.responsavel.id === t.eu })}</div>`
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

// O que está sendo escrito na janela: a subtarefa (nova ou em edição) ou a justificativa.
function lerEdicaoJanela() {
  const f = dlg?.querySelector("[data-sub-form], [data-just-form]");
  if (!f) return null;
  const v = {};
  f.querySelectorAll("[data-campo]").forEach((c) => { v[c.dataset.campo] = c.dataset.campo === "responsavel" ? Number(c.value) : c.value.trim(); });
  if ("hora" in v) v.hora = v.hora || null;
  return v;
}

const janelaMudou = () => !!dlg?.open && janela.inicial != null && JSON.stringify(lerEdicaoJanela()) !== janela.inicial;

// A subtarefa vence até o prazo da tarefa (no mesmo dia, o horário só conta quando os dois têm).
const depoisDoPrazo = (s, t) => !!s.prazo && (s.prazo > t.prazo || (s.prazo === t.prazo && !!s.hora && !!t.hora && s.hora > t.hora));

function aoClicarJanela(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if ("fechar" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_JANELA)) return;
    return dlg.close();
  }
  const t = janela.tarefa;
  if (!t) return;
  if (b.dataset.recolherPessoa) return alternarCard(b, janela.recolhidos);
  const s = b.closest("[data-sub]") ? subDe(t, Number(b.closest("[data-sub]").dataset.sub)) : null;
  if ("subNova" in b.dataset || "subEditar" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_JANELA)) return;
    Object.assign(janela, { editando: s ? s.id : "nova", justificando: null, para: b.dataset.para ? Number(b.dataset.para) : null });
    desenharTarefa(t);
    return dlg.querySelector('[data-sub-form] [data-campo="titulo"]').focus();
  }
  if (b.dataset.just) {
    if (janelaMudou() && !confirm(DESCARTAR_JANELA)) return;
    Object.assign(janela, { editando: null, justificando: b.dataset.just === "tarefa" ? "tarefa" : Number(b.dataset.just) });
    desenharTarefa(t);
    return dlg.querySelector("[data-just-form] textarea").focus();
  }
  if ("subCancelar" in b.dataset || "justCancelar" in b.dataset) {
    Object.assign(janela, { editando: null, justificando: null });
    return desenharTarefa(t);
  }
  if (b.dataset.subSituacao || b.dataset.tfSituacao) {
    if (janelaMudou() && !confirm(DESCARTAR_JANELA)) return;
    if (b.dataset.tfSituacao) return moverTarefa(t, b.dataset.tfSituacao);
    if (b.dataset.subSituacao !== s.situacao) return mexer("/api/agenda/subtarefa/mover", { id: s.id, situacao: b.dataset.subSituacao });
    return;
  }
  if ("tfEditar" in b.dataset) {
    if (janelaMudou() && !confirm(DESCARTAR_JANELA)) return;
    dlg.close();
    return editarTarefa(t);
  }
  if ("tfExcluir" in b.dataset) return excluirTarefa(t);
}

async function aoEnviarSub(e) {
  e.preventDefault();
  const f = e.target, t = janela.tarefa;
  const dados = lerEdicaoJanela();
  if (f.dataset.justForm) return enviarJust(f, t, dados.justificativa);
  if (!dados.titulo) {
    toast("Escreva o título da subtarefa", "erro");
    return f.querySelector('[data-campo="titulo"]').focus();
  }
  if (depoisDoPrazo(dados, t)) {
    toast(`A subtarefa vence depois da tarefa (${prazoTxt(t)}): o prazo dela vai até o da tarefa`, "erro");
    return focarDia(f.querySelector('[data-campo="prazo"]'));
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const nova = f.dataset.subForm === "nova";
  const r = nova ? await mexer("/api/agenda/subtarefas", { id: t.id, subtarefa: dados }, "Subtarefa criada")
    : await mexer("/api/agenda/subtarefa/editar", { id: Number(f.dataset.subForm), subtarefa: dados }, "Subtarefa salva");
  if (!r && f.isConnected) botao.disabled = false;
}

// Grava a justificativa do atraso da tarefa ou da subtarefa (vazia apaga a que havia).
async function enviarJust(f, t, texto) {
  const tarefa = f.dataset.justForm === "tarefa";
  const x = tarefa ? t : subDe(t, Number(f.dataset.justForm));
  if (!texto && !x.justificativa) {
    toast("Escreva por que atrasou", "erro");
    return f.querySelector("textarea").focus();
  }
  if (!texto && !confirm("Apagar a justificativa do atraso?")) return;
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const r = await mexer(`/api/agenda/${tarefa ? "tarefa" : "subtarefa"}/justificar`, { id: x.id, justificativa: texto },
    texto ? "Justificativa salva" : "Justificativa apagada");
  if (!r && f.isConnected) botao.disabled = false;
}

// ---------- formulário (em tela cheia) ----------
// Atividade ou tarefa nova (no dia `dia`) ou a edição de uma (item, com o tipo), numa janela que cobre a tela.
async function abrirForm(item = null, tipo = item ? item.tipo : estado.tipo, dia = estado.aberto || hojeLocal()) {
  if (tipo === "tarefa" && !(await garantirPessoas())) return;
  desenharForm(item, tipo, dia);
  if (!tela.open) tela.showModal();
  tela.querySelector('[name="titulo"]').focus();
}

// Fechar pergunta antes de descartar o que foi preenchido (depois de salvar, não).
function fecharForm(salvo = false) {
  if (!salvo && formMudou() && !confirm(DESCARTAR_FORM)) return;
  tela.close();
}

function desenharForm(item, tipo, dia) {
  Object.assign(estado, { tipo, editando: item, formDia: dia });
  const ehTarefa = tipo === "tarefa";
  const nome = ehTarefa ? "tarefa" : "atividade";
  const dica = ehTarefa
    ? (item ? "Quem participa vê as mudanças na agenda; só você muda os prazos." : "Com prazo, participantes e subtarefas para cada um.")
    : (item ? "O que já foi concluído continua no histórico." : "Só você vê as atividades da sua agenda.");
  tela.innerHTML = `<form id="ag-form" class="ag-form" novalidate>
    <header class="ag-tela-cab">
      <div class="ag-tela-tit"><h2 id="ag-tela-titulo">${icone(item ? "lapis" : ehTarefa ? "tarefa" : "calendario")}${item ? `Editar ${nome}` : `Nova ${nome}`}</h2>
        <small>${dica}</small></div>
      ${item ? "" : `<div class="seg-mini ag-tipo" role="group" aria-label="O que criar">${TIPOS.map(([k, n]) =>
        `<button type="button" data-tipo="${k}" class="${k === tipo ? "ativo" : ""}" aria-pressed="${k === tipo}">${n}</button>`).join("")}</div>`}
      <button class="btn icone" type="button" data-fechar-form title="Fechar (Esc)" aria-label="Fechar">${icone("x")}</button>
    </header>
    <div class="ag-tela-corpo"><div class="ag-tela-grade">${ehTarefa ? formTarefa(item, dia) : formAtividade(item, dia)}</div></div>
    <footer class="ag-tela-rodape">
      <small>Ctrl+Enter salva · Esc fecha</small>
      <button class="btn" type="button" data-fechar-form>Cancelar</button>
      <button class="btn primario" type="submit">${icone(item ? "disco" : "mais")}${item ? "Salvar" : `Criar ${nome}`}</button>
    </footer>
  </form>`;
  tela.querySelector("form").addEventListener("submit", aoEnviar);
  prepararDias(tela);
  if (ehTarefa) desenharPessoas(); else mostrarCampos();
  estado.formInicial = JSON.stringify(coletar());
}

// Duas partes, uma embaixo da outra: o que é (e se pede feedback) e quando (a repetição e os dias).
function formAtividade(a, dia) {
  const v = a || { titulo: "", descricao: "", inicio: dia, hora: null, repeticao: "nenhuma", dias_semana: null, dia_mes: null,
                   intervalo: null, so_dias_uteis: false, regiao: null, fim: null, exige_feedback: false };
  estado.form = { repeticao: v.repeticao, dias: new Set(v.dias_semana || []), regiao: v.regiao || "ES" };
  return `<div class="ag-tela-col">
      <label class="campo-form"><span>Título</span>
        <input name="titulo" maxlength="120" autocomplete="off" value="${esc(v.titulo)}" placeholder="Ex.: Visitar o Mercado do João"></label>
      <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
        <textarea name="descricao" rows="3" maxlength="2000">${esc(v.descricao)}</textarea></label>
      <label class="vend-op"><input type="checkbox" name="exige_feedback" ${v.exige_feedback ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">Exige feedback ao concluir<small>Para marcar como feita, é preciso contar como foi</small></span></label>
    </div>
    <div class="ag-tela-col">
      <div class="campo-form"><span>Repetição</span>
        <div class="seg-mini ag-rep" role="group" aria-label="Repetição">${REPETICOES.map(([k, n]) =>
          `<button type="button" data-rep="${k}" class="${k === v.repeticao ? "ativo" : ""}" aria-pressed="${k === v.repeticao}">${n}</button>`).join("")}</div></div>
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
      <div class="campo-form"><span data-rotulo-inicio>${v.repeticao === "nenhuma" ? "Dia" : "Começa em"}</span>
        ${campoDia({ nome: "inicio", valor: v.inicio, rotulo: "Dia da atividade" })}</div>
      <label class="campo-form ag-hora-campo"><span>Horário <small>(opcional)</small></span>
        <input type="time" name="hora" value="${v.hora || ""}"></label>
      <div class="campo-form" data-para="diaria semanal mensal intervalo"><span>Termina em <small>(opcional)</small></span>
        ${campoDia({ nome: "fim", valor: v.fim, min: v.inicio, vazio: "Sem data para terminar", rotulo: "Último dia da atividade" })}</div>
    </div>`;
}

// O formulário da tarefa: o que é e o prazo; embaixo, as pessoas e as subtarefas. Participantes e subtarefas ficam em
// estado.tf (desenharPessoas: um card por pessoa, com as subtarefas dela; recolhidos: os cards fechados; aberta: a
// subtarefa aberta para editar, a única com os campos, enquanto as outras mostram só o texto); os campos da subtarefa
// usam data-campo, não name: com nomes repetidos, f.elements.titulo deixaria de ser o da tarefa.
function formTarefa(t, dia) {
  estado.tf = {
    participantes: t ? t.participantes.map((p) => ({ id: p.id, nome: p.nome, autonomia: p.autonomia })) : [],
    subtarefas: t ? t.subtarefas.map((s) => ({ id: s.id, titulo: s.titulo, descricao: s.descricao, responsavel: s.responsavel.id,
                                               prazo: s.prazo, hora: s.hora || "" })) : [],
    recolhidos: new Set(),
    aberta: null,
  };
  return `<div class="ag-tela-col">
      <label class="campo-form"><span>Título</span>
        <input name="titulo" maxlength="120" autocomplete="off" value="${esc(t?.titulo || "")}" placeholder="Ex.: Preparar a feira de novembro"></label>
      <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
        <textarea name="descricao" rows="3" maxlength="2000">${esc(t?.descricao || "")}</textarea></label>
      <div class="campo-form"><span>Prazo</span>${campoDia({ nome: "prazo", valor: t ? t.prazo : dia, rotulo: "Prazo da tarefa" })}</div>
      <label class="campo-form ag-hora-campo"><span>Horário do prazo <small>(opcional)</small></span>
        <input type="time" name="hora" value="${t?.hora || ""}"></label>
    </div>
    <div class="ag-tela-col">
      <div class="campo-form"><span>Pessoas e subtarefas <small>(opcional)</small></span>
        <div class="ag-pessoas" id="ag-pessoas"></div>
        <span class="campo"><select data-add-pessoa aria-label="Adicionar participante"></select></span>
        <small>Com autonomia, a pessoa edita o texto das próprias subtarefas e cria subtarefas para si. Prazos, só você muda.</small>
      </div>
    </div>`;
}

// Um card por pessoa (você primeiro, depois os participantes), com as subtarefas dela dentro. Recolhido, fica só a
// pessoa; a linha aberta continua na página (escondida), para lerSubs ler o que foi digitado nela.
function desenharPessoas() {
  const f = raiz.querySelector("#ag-form");
  const { participantes, subtarefas, recolhidos } = estado.tf;
  const eu = estado.pessoas.eu, prazo = f.elements.prazo.value, hora = f.elements.hora.value || null;
  const lista = f.querySelector("#ag-pessoas");
  lista.innerHTML = [{ id: eu.id, nome: eu.nome, voce: true }, ...participantes].map((p) => {
    const linhas = subtarefas.map((s, n) => [s, n]).filter(([s]) => s.responsavel === p.id);
    const quem = p.voce ? "você" : esc(p.nome);
    const resumo = linhas.length ? plural(linhas.length, "subtarefa", "subtarefas") : "sem subtarefas";
    return `<div class="ag-pessoa-card ${recolhidos.has(p.id) ? "recolhido" : ""}">
      <div class="ag-pessoa-cab">
        ${nomeDoCard(p, resumo, recolhidos.has(p.id))}
        ${p.voce ? "" : `<button type="button" class="ag-pessoa-op ${p.autonomia ? "ativo" : ""}" data-autonomia="${p.id}" aria-pressed="${p.autonomia}"
          title="${p.autonomia ? "Com autonomia: edita o texto das próprias subtarefas e cria subtarefas para si. Clique para tirar." : "Sem autonomia: só conclui as próprias subtarefas. Clique para dar autonomia."}">${icone("chave")}Autonomia</button>
        <button type="button" class="ag-pessoa-op ag-pessoa-x" data-tirar-pessoa="${p.id}" title="Tirar ${esc(p.nome)} da tarefa" aria-label="Tirar ${esc(p.nome)} da tarefa">${icone("x")}</button>`}
      </div>
      <div class="ag-pessoa-corpo">
        ${linhas.map(([s, n]) => linhaSub(s, n, p, prazo, hora)).join("")}
        <button type="button" class="ag-pessoa-op ag-pessoa-sub" data-sub-para="${p.id}" title="Criar uma subtarefa para ${quem}"
          aria-label="Criar uma subtarefa para ${quem}">${icone("mais")}Subtarefa</button>
      </div>
    </div>`;
  }).join("");
  prepararDias(lista);
  const livres = estado.pessoas.pessoas.filter((p) => !participantes.some((q) => q.id === p.id));
  const sel = f.querySelector("[data-add-pessoa]");
  sel.innerHTML = `<option value="">${livres.length ? "Adicionar pessoa…" : "Ninguém mais com acesso à Gestão"}</option>` +
    livres.map((p) => `<option value="${p.id}">${esc(p.nome)}</option>`).join("");
  sel.disabled = !livres.length;
}

// O nome no topo do card (no formulário e na janela da tarefa): a seta e o nome recolhem o card (fica só a pessoa) e
// abrem de novo (com as subtarefas).
function nomeDoCard(p, resumo, recolhido, papel = "") {
  const nome = `${esc(p.nome)}${p.voce ? " (você)" : ""}`;
  return `<button type="button" class="ag-pessoa-nome" data-recolher-pessoa="${p.id}" aria-expanded="${!recolhido}"
    title="${recolhido ? "Mostrar" : "Esconder"} as subtarefas de ${nome}">${icone("setaBaixo", "ag-seta")}${icone("usuario")}<b>${nome}</b>${papel ? `<small>${papel}</small>` : ""}<small>· ${resumo}</small></button>`;
}

// Recolhe ou abre o card do botão (sem redesenhar: o que está sendo digitado continua); recolhidos guarda a escolha.
function alternarCard(b, recolhidos) {
  const card = b.closest(".ag-pessoa-card");
  const fechar = !card.classList.contains("recolhido");
  card.classList.toggle("recolhido", fechar);
  if (fechar) recolhidos.add(Number(b.dataset.recolherPessoa)); else recolhidos.delete(Number(b.dataset.recolherPessoa));
  b.setAttribute("aria-expanded", String(!fechar));
  b.title = b.title.replace(fechar ? "Esconder" : "Mostrar", fechar ? "Mostrar" : "Esconder");
}

// Uma subtarefa no card da pessoa p. Recolhida: só o texto e o prazo (em vermelho se passa do da tarefa), e clicar
// abre. Aberta (a de estado.tf.aberta): o título e, embaixo, o prazo (até o da tarefa) com o horário ao lado.
function linhaSub(s, n, p, prazoTarefa, horaTarefa) {
  const de = p.voce ? "você" : p.nome;
  const tirar = `<button type="button" class="ag-sub-tirar" data-tirar-sub="${n}" title="Tirar a subtarefa" aria-label="Tirar a subtarefa">${icone("x")}</button>`;
  if (estado.tf.aberta !== n) {
    const fora = depoisDoPrazo(s, { prazo: prazoTarefa, hora: horaTarefa });
    return `<div class="ag-sub-linha fechada" data-n="${n}">
      <button type="button" class="ag-sub-resumo" data-abrir-sub="${n}" aria-expanded="false" title="Abrir para editar">
        ${icone("setaBaixo", "ag-seta")}<span class="ag-sub-txt">${s.titulo.trim() ? esc(s.titulo) : "<i>Sem título</i>"}</span>
        ${s.prazo ? `<small class="${fora ? "fora" : ""}"${fora ? ' title="Vence depois da tarefa"' : ""}>até ${prazoTxt(s)}</small>` : ""}</button>
      ${tirar}
    </div>`;
  }
  const hora = `<input type="time" data-campo="hora" value="${s.hora || ""}" title="Horário (opcional)" aria-label="Horário da subtarefa (opcional)">`;
  return `<div class="ag-sub-linha" data-n="${n}">
      <div class="ag-sub-topo">
        <button type="button" class="ag-sub-recolher" data-fechar-sub title="Recolher a subtarefa" aria-expanded="true"
          aria-label="Recolher a subtarefa">${icone("setaBaixo")}</button>
        <input data-campo="titulo" maxlength="120" autocomplete="off" value="${esc(s.titulo)}" placeholder="O que fazer" aria-label="Subtarefa de ${esc(de)}">
        ${tirar}
      </div>
      ${campoDia({ campo: "prazo", valor: s.prazo, max: prazoTarefa, maxDica: "Depois do prazo da tarefa", rotulo: `Prazo da subtarefa de ${de}`,
                   contar: !!p.voce, extra: hora })}
    </div>`;
}

// Abre a subtarefa n para editar (a que estava aberta se recolhe) ou, com null, recolhe a aberta.
function abrirSub(n) {
  lerSubs();
  estado.tf.aberta = n;
  if (n != null) estado.tf.recolhidos.delete(estado.tf.subtarefas[n].responsavel);
  desenharPessoas();
}

// Copia o que foi digitado nas linhas de subtarefa para estado.tf (antes de redesenhar ou de enviar).
function lerSubs() {
  raiz.querySelectorAll("#ag-pessoas .ag-sub-linha").forEach((linha) => {
    const s = estado.tf.subtarefas[Number(linha.dataset.n)];
    linha.querySelectorAll("[data-campo]").forEach((c) => { s[c.dataset.campo] = c.value; });
  });
}

// Uma subtarefa nova no card da pessoa (aberto, se estava recolhido), com o prazo da tarefa: ela abre para escrever e
// as outras ficam recolhidas, só com o texto.
function maisSub(responsavel) {
  lerSubs();
  const f = raiz.querySelector("#ag-form");
  estado.tf.subtarefas.push({ id: null, titulo: "", descricao: "", responsavel, prazo: f.elements.prazo.value || hojeLocal(), hora: "" });
  focarSub(estado.tf.subtarefas.length - 1, "titulo");
}

// Põe o foco num campo da subtarefa n (no prazo, o dia escolhido), abrindo ela e o card dela.
function focarSub(n, campo) {
  if (estado.tf.aberta !== n || raiz.querySelector(`#ag-pessoas .recolhido .ag-sub-linha[data-n="${n}"]`)) abrirSub(n);
  const c = raiz.querySelector(`#ag-pessoas .ag-sub-linha[data-n="${n}"] [data-campo="${campo}"]`);
  if (c.type === "hidden") focarDia(c); else c.focus();
}

// Tira o participante da tarefa e, com ele, as subtarefas dele (perguntando antes, se houver).
function tirarPessoa(id) {
  lerSubs();
  const p = estado.tf.participantes.find((x) => x.id === id);
  const n = estado.tf.subtarefas.filter((s) => s.responsavel === id).length;
  if (n && !confirm(`Tirar ${p.nome} da tarefa? ${n === 1 ? "A subtarefa" : `As ${n} subtarefas`} de ${p.nome} ${n === 1 ? "sai" : "saem"} junto.`)) return;
  estado.tf.subtarefas = estado.tf.subtarefas.filter((s) => s.responsavel !== id);
  estado.tf.participantes = estado.tf.participantes.filter((x) => x.id !== id);
  estado.tf.recolhidos.delete(id);
  estado.tf.aberta = null; // as posições das subtarefas mudaram
  desenharPessoas();
}

async function escolherTipo(tipo) {
  if (tipo === estado.tipo) return;
  if (formMudou() && !confirm(DESCARTAR_FORM)) return;
  if (tipo === "tarefa" && !(await garantirPessoas())) return;
  desenharForm(null, tipo, estado.formDia);
  tela.querySelector('[name="titulo"]').focus();
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
  const t = e.target;
  if (t.name === "so_dias_uteis") raiz.querySelector("[data-regioes]").hidden = !t.checked;
  // o prazo da tarefa limita o das subtarefas (e as recolhidas avisam se passam dele); o começo da atividade, o fim
  if ((t.name === "prazo" || t.name === "hora") && estado.tf) {
    lerSubs();
    desenharPessoas();
  }
  if (t.name === "inicio") limitesDoDia(t.form.elements.fim, { min: t.value });
  if (t.matches("[data-add-pessoa]") && t.value) {
    lerSubs();
    const p = estado.pessoas.pessoas.find((x) => x.id === Number(t.value));
    estado.tf.participantes.push({ id: p.id, nome: p.nome, autonomia: false });
    estado.tf.participantes.sort((a, b) => a.nome.localeCompare(b.nome));
    desenharPessoas();
  }
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
  return !!tela?.open && !!tela.querySelector("#ag-form") && JSON.stringify(coletar()) !== estado.formInicial;
}

function editar(a) {
  return abrirForm({ ...a, tipo: "atividade" });
}

async function aoEnviar(e) {
  e.preventDefault();
  const f = e.target;
  if (estado.tipo === "tarefa") return enviarTarefa(f);
  const dados = coletar();
  if (!dados.titulo) { toast("Escreva o título da atividade", "erro"); return f.elements.titulo.focus(); }
  if (!dados.inicio) { toast("Escolha o dia da atividade", "erro"); return focarDia(f.elements.inicio); }
  if (dados.repeticao === "semanal" && !dados.dias_semana.length) return toast("Escolha ao menos um dia da semana", "erro");
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const editando = estado.editando;
  try {
    if (editando) await api("/api/agenda/atividade/editar", { json: { id: editando.id, atividade: dados } });
    else await api("/api/agenda/atividades", { json: { atividade: dados } });
    toast(editando ? "Atividade salva" : "Atividade criada");
    fecharForm(true);
    await (editando ? carregar() : carregar(mesDe(dados.inicio), { aberto: dados.inicio }));
  } catch (err) {
    botao.disabled = false;
    toast(err.message, "erro");
  }
}

async function enviarTarefa(f) {
  const dados = coletar();
  if (!dados.titulo) { toast("Escreva o título da tarefa", "erro"); return f.elements.titulo.focus(); }
  if (!dados.prazo) { toast("Escolha o prazo da tarefa", "erro"); return focarDia(f.elements.prazo); }
  for (const [n, s] of dados.subtarefas.entries()) {
    if (!s.titulo) { toast("Escreva o título da subtarefa", "erro"); return focarSub(n, "titulo"); }
    if (depoisDoPrazo(s, dados)) {
      toast(`A subtarefa "${s.titulo}" vence depois da tarefa: o prazo dela vai até o da tarefa`, "erro");
      return focarSub(n, "prazo");
    }
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const editando = estado.editando;
  try {
    if (editando) await api("/api/agenda/tarefa/editar", { json: { id: editando.id, versao: editando.versao, tarefa: dados } });
    else await api("/api/agenda/tarefas", { json: { tarefa: dados } });
    toast(editando ? "Tarefa salva" : "Tarefa criada");
    fecharForm(true);
    await Promise.all([editando ? carregar() : carregar(mesDe(dados.prazo), { aberto: dados.prazo }),
                       estado.vista === "quadro" ? carregarQuadro() : null]);
  } catch (err) {
    botao.disabled = false;
    toast(err.message, "erro");
  }
}

// ---------- kanban ----------
function escolherVista(vista) {
  estado.vista = vista;
  guardar(CHAVE_VISTA, vista);
  raiz.classList.toggle("vista-quadro", vista === "quadro");
  raiz.querySelectorAll("[data-vista]").forEach((b) => {
    b.classList.toggle("ativo", b.dataset.vista === vista);
    b.setAttribute("aria-pressed", String(b.dataset.vista === vista));
  });
  escreverCabecalho();
  if (vista === "quadro") carregarQuadro();
}

async function carregarQuadro() {
  const pedido = ++estado.pedidoQuadro;
  const el = raiz.querySelector("#ag-quadro");
  if (estado.quadro) el.classList.add("recarregando");
  else el.innerHTML = `<div class="esqueleto" style="height:280px"></div>`;
  try {
    const q = await api("/api/agenda/quadro");
    if (pedido !== estado.pedidoQuadro) return;
    const primeira = !estado.quadro;
    estado.quadro = q;
    desenharQuadro(primeira);
  } catch (e) {
    if (pedido !== estado.pedidoQuadro) return;
    if (!estado.quadro) el.innerHTML = `<div class="vazio">${icone("alerta")}<p>${esc(e.message)}</p></div>`;
    toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedidoQuadro) el.classList.remove("recarregando");
  }
}

// As três colunas: A fazer e Fazendo pelo prazo; Concluída, as concluídas por último primeiro.
function desenharQuadro(animar) {
  const q = estado.quadro;
  const colunas = Object.fromEntries(SITUACOES.map(([k]) => [k, []]));
  q.tarefas.forEach((t) => colunas[t.situacao].push(t));
  colunas.concluida.sort((a, b) => String(b.concluida_em || "~").localeCompare(String(a.concluida_em || "~")));
  escreverCabecalho();
  raiz.querySelector("#ag-quadro").innerHTML = `<div class="ag-colunas ${animar ? "abre" : ""}">${SITUACOES.map(([k, nome]) => `
      <section class="ag-coluna" data-coluna="${k}" aria-label="${nome}">
        <h3><i class="ag-st" aria-hidden="true"></i>${nome}<span class="ag-coluna-n">${colunas[k].length}</span></h3>
        <ul class="ag-cards">${colunas[k].map(cardHtml).join("") || `<li class="ag-coluna-vazia">${COLUNA_VAZIA[k]}</li>`}</ul>
      </section>`).join("")}</div>
    <p class="ag-quadro-dica">${icone("info")}Arraste o card para outra coluna, ou abra a tarefa e escolha a situação. As concluídas saem do kanban ${q.dias_concluidas} dias depois.</p>`;
}

function cardHtml(t, n) {
  const minhas = t.subtarefas.filter((s) => s.minha && !s.feita).length;
  const chips = [
    t.feita ? `<span class="chip ag-c-feita">${icone("visto")}Concluída em ${dataCurta(t.concluida_em.slice(0, 10))}</span>`
      : `<span class="chip ${t.atrasada ? "ag-c-atrasada" : ""}">${icone(t.atrasada ? "alerta" : "relogio")}${t.atrasada ? "Venceu em" : "Até"} ${prazoTxt(t)}</span>`,
    !t.eu_criador ? `<span class="chip">${icone("usuario")}De ${esc(t.criador.nome)}</span>` : "",
    t.participantes.length ? `<span class="chip" title="${esc(t.participantes.map((p) => p.nome).join(", "))}">${icone("pessoas")}${plural(t.participantes.length + 1, "pessoa", "pessoas")}</span>` : "",
    minhas ? `<span class="chip ag-c-tarefa" title="Subtarefas suas que faltam">${icone("tarefa")}${plural(minhas, "subtarefa sua", "subtarefas suas")}</span>` : "",
    t.justificativa ? `<span class="chip ag-c-justificada" title="${esc(t.justificativa)}">${icone("conversa")}Atraso justificado</span>` : "",
  ].filter(Boolean).join("");
  return `<li class="ag-card ${t.atrasada ? "atrasada" : ""}" style="--i:${n}" data-card="${t.id}" tabindex="0" role="button"
    ${t.pode.concluir ? 'draggable="true" title="Clique para abrir; arraste para mudar de coluna"' : 'title="Clique para abrir"'} aria-label="Abrir a tarefa ${esc(t.titulo)}">
    <b>${esc(t.titulo)}</b>
    ${t.descricao ? `<p>${esc(t.descricao)}</p>` : ""}
    <div class="ag-chips">${chips}</div>
    ${t.total ? `<div class="ag-card-prog">${barra(t.feitas, t.total - t.feitas)}<span>${t.feitas} de ${plural(t.total, "subtarefa feita", "subtarefas feitas")}</span></div>` : ""}
  </li>`;
}

// Arrastar o card (qualquer pessoa da tarefa): a coluna de baixo se destaca e, solto, ele muda de coluna.
function aoArrastar(e) {
  const card = e.target.closest?.(".ag-card[draggable]");
  if (!card) return;
  estado.arrastando = estado.quadro.tarefas.find((t) => t.id === Number(card.dataset.card));
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", card.dataset.card);
  requestAnimationFrame(() => card.classList.add("arrastando"));
}

function aoPassar(e) {
  if (!estado.arrastando) return;
  const col = e.target.closest?.(".ag-coluna");
  const outra = !!col && col.dataset.coluna !== estado.arrastando.situacao;
  raiz.querySelectorAll(".ag-coluna").forEach((c) => c.classList.toggle("alvo", outra && c === col));
  if (outra) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }
}

function aoSoltar(e) {
  const col = e.target.closest?.(".ag-coluna"), t = estado.arrastando;
  if (!col || !t) return;
  e.preventDefault();
  fimDoArraste();
  moverTarefa(t, col.dataset.coluna);
}

function fimDoArraste() {
  estado.arrastando = null;
  raiz.querySelectorAll(".ag-coluna.alvo, .ag-card.arrastando").forEach((x) => x.classList.remove("alvo", "arrastando"));
}
