// Minha agenda, no topo da página Gestão (gestao.js monta): as atividades de cada pessoa (só ela vê) e as tarefas de que
// ela participa, na faixa de dias do mês (a mesma do "Ritmo do mês" da página Metas), com o dia de hoje num quadrado
// maior. Cada quadrado mostra quantos itens o dia tem e, numa barrinha, os feitos (verde) e os que faltam (laranja;
// vermelho se o dia passou). Clicar num dia amplia o painel com o que há nele (os com horário primeiro).
// - Atividade: concluir (com o feedback, obrigatório quando a atividade pede), editar o feedback, desfazer e, nas que
//   se repetem, o histórico de tudo o que foi feito.
// - Tarefa: aparece no dia do prazo; cada subtarefa, no dia do prazo dela (quem criou vê todas; o participante, as
//   dele). A janela da tarefa mostra a situação dela (A fazer, Fazendo, Concluída) e um card por pessoa com as
//   subtarefas dela, de todos: cada um muda a situação das suas e, com autonomia, edita o texto delas e cria
//   subtarefas para si, escolhendo o dia. Quem tem autonomia recebe a subtarefa automática, que pede para programar
//   a execução: aparece em dois dias (é uma só: feita num, feita nos dois), não se edita e não entra no formulário de
//   quem criou, que não a vê nos dias da agenda. No dia de hoje, um bloco lista as tarefas e subtarefas atrasadas dos
//   dias anteriores (a que venceu hoje, no horário do prazo, fica no dia). Passado o prazo, quem responde por ela
//   (quem criou a tarefa; o responsável pela subtarefa) justifica o atraso: as justificativas formam um histórico, que
//   todos veem. Vencida e aberta, ela bloqueia o painel de quem responde até ele justificar (avisos.js).
// - Kanban (a outra vista, no lugar da faixa e do dia): as tarefas abertas pelo vencimento do prazo da tarefa (Vencido,
//   Vence hoje, Vence essa semana, de segunda a domingo, e Vence depois; a coluna vem do servidor) e as concluídas há
//   pouco. O card não se arrasta: clicar abre a janela da tarefa, onde se muda a situação.
// O botão Nova (e o Novo neste dia) abre em tela cheia o formulário de atividade nova (única, diária, semanal, mensal
// ou a cada N dias, com horário opcional) ou de tarefa nova (prazo e um card por pessoa, com ou sem autonomia, com as
// subtarefas dela; clicar no nome abre o card já com uma subtarefa nova: escolhe-se o dia, escreve-se o nome, e o dia
// escolhido depois já é o da próxima, que abre com a anterior guardada), que também edita uma atividade ou uma
// tarefa. Os dias se escolhem numa faixa de quadradinhos como a da agenda (escolherdia.js), que mostra quanto cada dia
// já tem. O título da subtarefa aceita um texto longo: a caixa dele cresce com o texto.
// Minimizada (o − do cabeçalho, ou o Minimizar tudo da Gestão), fica só o título (a escolha, e a vista, ficam
// guardadas neste navegador). #/gestao?dia=AAAA-MM-DD abre a agenda nesse dia (o link das propostas do Assistente).
// Em que dias cada atividade acontece, o texto da repetição ("Toda segunda e quinta") e o que cada pessoa pode fazer
// numa tarefa vêm do servidor (bi/agenda.py e bi/tarefas.py).
// Google Agenda (só leitura, bi/google_agenda.py; o botão Google abre agendagoogle.js): os eventos das agendas do
// Google que a pessoa ligou aparecem no dia (depois dos itens do BI, sem o check) e na dica do quadrado, mas não
// contam no número, na barrinha nem nas cores, que são do que há para fazer. "Trazer como atividade" abre o formulário
// de atividade nova preenchido com o evento. Gravar com um horário ocupado no Google da própria pessoa grava e avisa
// (o toast amarelo).
import { abrirGoogle } from "./agendagoogle.js";
import { campoDia, contarDias, focarDia, limitesDoDia, prepararDias, redesenharDias } from "./escolherdia.js";
import { MESES, api, esc, fmt, guardar, icone, ler, ligarTooltips, linhaTT, toast } from "./util.js";

const SEMANA = ["D", "S", "T", "Q", "Q", "S", "S"];
const DIAS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]]; // date.isoweekday()
const MAX_SEGMENTOS = 6; // até aqui, a barrinha do dia tem um pedaço por item; acima, só as duas partes
const MAX_TOOLTIP = 6;   // itens listados no tooltip do dia
const MAX_DICA = 80;     // caracteres do título de uma subtarefa (que pode ser longo) no tooltip do dia e nos avisos
const MAX_ALTURA_TITULO = 220; // px: a caixa do título da subtarefa cresce com o texto até aqui; depois, rola
const REPETICOES = [["nenhuma", "Única"], ["diaria", "Diária"], ["semanal", "Semanal"], ["mensal", "Mensal"], ["intervalo", "A cada N dias"]];
const TIPOS = [["atividade", "Atividade"], ["tarefa", "Tarefa"]];
const VISTAS = [["agenda", "Agenda", "calendario"], ["quadro", "Kanban", "quadro"]];
// A situação de uma tarefa ou subtarefa (na janela da tarefa): o nome, o ícone e o aviso ao mudar a da tarefa.
const SITUACOES = [["a_fazer", "A fazer"], ["fazendo", "Fazendo"], ["concluida", "Concluída"]];
const NOME_SITUACAO = Object.fromEntries(SITUACOES);
const ICONE_SITUACAO = { a_fazer: "menos", fazendo: "relogio", concluida: "certo" };
const MOVIDA = { a_fazer: "Tarefa em A fazer", fazendo: "Tarefa em Fazendo", concluida: "Tarefa concluída" };
// As colunas do kanban: as abertas pelo vencimento (o que o servidor dá) e as concluídas há pouco. A chave, o nome e o
// texto da coluna vazia.
const COLUNAS = [["vencido", "Vencido", "Nenhuma tarefa vencida"], ["hoje", "Vence hoje", "Nenhuma tarefa vence hoje"],
  ["semana", "Vence essa semana", "Nada mais vence nesta semana"], ["depois", "Vence depois", "Nenhuma tarefa para depois"],
  ["concluida", "Concluídas", "Nenhuma concluída há pouco"]];
const DESCARTAR_FB = "Descartar o feedback que você estava escrevendo?";
const DESCARTAR_FORM = "Descartar o que foi preenchido no formulário?";
const DESCARTAR_JANELA = "Descartar o que você estava escrevendo na tarefa?";
const CHAVE_RECOLHIDA = "mv-agenda-recolhida";
const CHAVE_VISTA = "mv-agenda-vista";

let raiz = null, dlg = null, tela = null; // tela: a janela em tela cheia do formulário (dentro de #ag-raiz)
// tipo: o do formulário (atividade ou tarefa); tf: os participantes e as subtarefas do formulário da tarefa;
// pessoas: quem pode participar ({eu, pessoas}, carregado na primeira tarefa); editando: {tipo, ...o item}; formDia: o
// dia em que o formulário abriu. vista: agenda ou quadro (o kanban, com as tarefas de estado.quadro). meses: a
// contagem de cada dia dos meses já vistos, para escolher o dia.
const estado = { mes: null, dados: null, aberto: null, editando: null, concluindo: null, form: null, formInicial: null, pedido: 0,
                 tipo: "atividade", tf: null, pessoas: null, formDia: null, vista: "agenda", quadro: null, pedidoQuadro: 0,
                 meses: new Map() };
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
const curto = (t, n) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t);
// Tudo o que o dia tem (atividades e tarefas), para as contas: os dois carregam o feita.
const todos = (x) => [...x.itens, ...(x.tarefas || [])];

function hojeLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function somarDias(dia, n) {
  const d = new Date(`${dia}T12:00`);
  d.setDate(d.getDate() + n);
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
// Antes do prazo da subtarefa: "Até" ou, na automática de dois dias, "Em 26/10 e" (o prazo vem depois).
const diasDaSub = (s) => (s.inicio && s.inicio !== s.prazo ? `Em ${dataCurta(s.inicio)} e` : "Até");
// A subtarefa automática (a que pede para programar a execução): um selo, com o porquê.
const chipAutomatica = (s) => (s.automatica ? `<span class="chip" title="Criada sozinha para quem tem autonomia: aparece em dois dias e, concluída num deles, fica feita nos dois. Sai se a autonomia for tirada.">${icone("info")}Automática</span>` : "");
// O horário de uma atividade: "14:00–15:00" ou, sem o fim, "14:00".
const horario = (a) => (a.hora_fim ? `${a.hora}–${a.hora_fim}` : a.hora);
// A atividade que se repete ou que dura vários dias (a única com o último dia): tem histórico e pode ser encerrada.
const variosDias = (a) => a.repeticao !== "nenhuma" || !!a.fim;
// A tarefa ou a subtarefa de uma referência da agenda ({tarefa, subtarefa}).
function daRef(r) {
  const t = tarefa(r.tarefa);
  return { t, s: r.subtarefa ? subDe(t, r.subtarefa) : null };
}
// O que o dia tem, na ordem do painel: com horário primeiro (no mesmo horário, as atividades antes). faixa: o horário
// como aparece (o da atividade, com o fim).
function doDia(x) {
  const lista = [...x.itens.map((i) => { const a = atividade(i.atividade); return { i, hora: a.hora, faixa: a.hora && horario(a) }; }),
    ...(x.tarefas || []).map((r) => { const { t, s } = daRef(r); return { r, hora: (s || t).hora, faixa: (s || t).hora }; })];
  return lista.sort((a, b) => (a.hora == null) - (b.hora == null) || (a.hora || "").localeCompare(b.hora || ""));
}

// ---------- montagem ----------
export function agendaTemAlteracoes() {
  return (!!raiz?.isConnected && (formMudou() || feedbackEscrito())) || janelaMudou();
}

// dia: o dia a abrir (#/gestao?dia=…, sempre na vista da agenda); sem ele, hoje. tarefa: a tarefa a abrir na janela
// dela (#/gestao?tarefa=…, o link de uma notificação do sino).
export function montarAgenda(el, { dia, tarefa } = {}) {
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
          <button class="btn ag-google-btn" type="button" data-google title="As suas agendas do Google (só leitura)">${icone("elo")}Google</button>
          <button class="btn icone" type="button" data-recolher aria-controls="ag-faixa ag-baixo ag-quadro"></button>
        </div>
      </div>
      <div id="ag-google-aviso"></div>
      <div id="ag-faixa"><div class="esqueleto" style="height:96px"></div></div>
      <div class="ag-baixo" id="ag-baixo"><div id="ag-dia"></div></div>
      <div class="ag-quadro" id="ag-quadro"></div>
      <dialog class="ag-tela" id="ag-tela" aria-labelledby="ag-tela-titulo"></dialog>
    </section>`;
  raiz = el.querySelector("#ag-raiz");
  tela = raiz.querySelector("#ag-tela");
  raiz.addEventListener("click", aoClicar);
  raiz.addEventListener("change", aoMudar);
  raiz.addEventListener("input", aoDigitar);
  raiz.addEventListener("keydown", aoTeclar);
  raiz.addEventListener("dia-escolhido", aoEscolherDia);
  tela.addEventListener("cancel", (e) => { if (formMudou() && !confirm(DESCARTAR_FORM)) e.preventDefault(); });
  tela.addEventListener("close", () => {
    tela.innerHTML = "";
    Object.assign(estado, { editando: null, tf: null, formInicial: null });
  });
  const valido = ehDia(dia);
  Object.assign(estado, { mes: null, dados: null, aberto: null, editando: null, concluindo: null, tipo: "atividade", tf: null,
                          pessoas: null, quadro: null, meses: new Map(), vista: valido ? "agenda" : ler(CHAVE_VISTA, "agenda") });
  contarDias(contagem);
  recolher(!valido && ler(CHAVE_RECOLHIDA, false)); // o link de um dia mostra a agenda, como abrirNaAgenda
  escolherVista(estado.vista);
  carregar(valido ? mesDe(dia) : undefined, { aberto: valido ? dia : undefined });
  if (Number(tarefa) > 0) abrirTarefa(Number(tarefa));
}

// O link de uma notificação do sino (#/gestao?tarefa=…) com a Gestão já montada: abre a janela da tarefa.
export function abrirTarefaNaAgenda(id) {
  if (!raiz?.isConnected || !(Number(id) > 0) || (janelaMudou() && !confirm(DESCARTAR_JANELA))) return;
  abrirTarefa(Number(id));
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

// O Minimizar tudo da Gestão: minimiza ou mostra a agenda, e pergunta se ela está minimizada.
export function minimizarAgenda(sim) {
  if (raiz?.isConnected && agendaMinimizada() !== sim) recolher(sim);
}
export const agendaMinimizada = () => !!raiz?.isConnected && raiz.classList.contains("recolhida");

// Depois de uma mudança feita fora da agenda (a janela do bloqueio, avisos.js): a janela da tarefa, se é ela que está
// aberta e nada está sendo escrito nela, mostra como ficou.
export async function atualizarTarefaAberta(id) {
  if (!dlg?.open || janela.tarefa?.id !== id || janelaMudou()) return;
  try {
    desenharTarefa(await api(`/api/agenda/tarefa?id=${id}`));
  } catch { /* a janela fica como estava */ }
}

// Depois de uma mudança: a agenda e, se ele está à vista, o kanban.
function recarregarTudo() {
  return Promise.all([carregar(), estado.vista === "quadro" ? carregarQuadro() : null]);
}

// Minimizada: só o título (sem os botões, a faixa de dias e o kanban) até abrir de novo (o +, ou o link de um dia). A
// Gestão fica sabendo (agenda-minimizada), para o botão Minimizar tudo.
function recolher(sim) {
  raiz.classList.toggle("recolhida", sim);
  const b = raiz.querySelector("[data-recolher]");
  const dica = sim ? "Mostrar a agenda" : "Minimizar a agenda";
  b.innerHTML = icone(sim ? "mais" : "minimizar");
  b.title = dica;
  b.setAttribute("aria-label", dica);
  b.setAttribute("aria-expanded", String(!sim));
  guardar(CHAVE_RECOLHIDA, sim);
  raiz.dispatchEvent(new Event("agenda-minimizada", { bubbles: true }));
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
    desenharAvisoGoogle();
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
    const conta = (k) => estado.quadro.tarefas.filter((t) => colunaDe(t) === k).length;
    const concluidas = conta("concluida"), vencidas = conta("vencido"), hoje = conta("hoje");
    resumo.textContent = estado.quadro.tarefas.length
      ? [plural(estado.quadro.tarefas.length - concluidas, "aberta", "abertas"),
         vencidas && plural(vencidas, "vencida", "vencidas"),
         hoje && `${fmt.num(hoje)} ${hoje === 1 ? "vence" : "vencem"} hoje`,
         concluidas && `${plural(concluidas, "concluída", "concluídas")} há pouco`].filter(Boolean).join(" · ")
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

// O botão Google com um ponto e, em cima da faixa, o aviso do que precisa de atenção: a conta cuja autorização caiu
// (entrar com o Google de novo), a agenda que não abre mais ou a que não é lida há mais de uma hora.
function desenharAvisoGoogle() {
  const avisos = [];
  for (const c of estado.dados.google?.contas || []) {
    if (c.trocar) {
      avisos.push(`A conexão com a conta Google ${esc(c.email)} caiu: entre com o Google de novo.`);
      continue;
    }
    for (const a of c.agendas.filter((x) => x.atencao)) {
      avisos.push(a.trocar ? `A agenda do Google “${esc(a.nome)}” não abre mais: ${esc(a.erro)}.`
        : `Não deu para ler a agenda do Google “${esc(a.nome)}”${a.lida_em ? ` desde ${dataCurta(a.lida_em.slice(0, 10))} às ${hora(a.lida_em)}` : ""}: ${esc(a.erro)}`);
    }
  }
  raiz.querySelector("[data-google]").classList.toggle("atencao", avisos.length > 0);
  raiz.querySelector("#ag-google-aviso").innerHTML = avisos.map((t) => `<div class="aviso ag-google-aviso">${icone("alerta")}
      <span>${t}</span>
      <button class="btn" type="button" data-google>Abrir</button>
    </div>`).join("");
}

// O horário de um evento do Google no dia: "14:00–15:00", "dia todo", "22:00 até a meia-noite" (continua no seguinte)
// ou "até 02:00" (começou no anterior).
function faixaGoogle(g) {
  if (g.dia_todo) return "dia todo";
  if (!g.hora) return `até ${g.hora_fim}`;
  if (!g.hora_fim) return `${g.hora} até a meia-noite`;
  return g.hora === g.hora_fim ? g.hora : `${g.hora}–${g.hora_fim}`;
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
      const g = x.google || []; // os eventos do Google: na dica e no pontinho, fora das contas
      const tt = `<div class='tt-t'>${fmt.dataCurta(x.data)} · ${fmt.semana(x.data)}${hoje ? " · hoje" : ""}</div>` +
        (total ? linhaTT("No dia", fmt.num(total)) + linhaTT("Feitas", fmt.num(feitasDia)) + linhaTT("Faltam", fmt.num(pendentes)) +
          lista.slice(0, MAX_TOOLTIP).map((e) => linhaDoDia(e)).join("") +
          (total > MAX_TOOLTIP ? `<div class='tt-l'><span>e mais ${total - MAX_TOOLTIP}</span></div>` : "")
          : g.length ? "" : linhaTT("No dia", "nada marcado")) + linhasGoogle(g);
      const rotulo = `${dia} de ${MESES[m - 1]}${hoje ? ", hoje" : ""}: ${total ? `${plural(total, "item", "itens")}, ${plural(feitasDia, "feito", "feitos")}, faltam ${pendentes}` : "nada marcado"}${g.length ? `; ${plural(g.length, "evento", "eventos")} do Google` : ""}`;
      return `<button type="button" class="${classes}" style="--i:${n}${col}" data-dia="${x.data}" data-tt="${esc(tt)}"
        aria-pressed="${x.data === estado.aberto}" aria-label="${esc(rotulo)}">${total ? `<i class="ag-n">${total}</i>` : ""}${g.length ? '<i class="ag-gdot" aria-hidden="true"></i>' : ""}${dia}${barra(feitasDia, pendentes)}<span class="sem">${SEMANA[dow]}</span></button>`;
    }).join("")}
  </div>
  <div class="ag-legenda" aria-hidden="true"><span><b class="ag-n">3</b>atividades e tarefas no dia</span>
    <span><span class="ag-barra"><i class="f"></i><i></i><i></i></span>feitas e as que faltam</span>
    <span><i class="tem"></i>Com algo marcado</span><span><i class="feita"></i>Tudo feito</span>
    <span><i class="atrasada"></i>Ficou sem concluir</span>
    ${d.google?.contas?.some((c) => c.agendas.some((a) => a.ligada)) ? `<span><i class="ag-gdot"></i>Evento do Google (só para ver)</span>` : ""}</div>`;
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

// As linhas do Google no tooltip do dia (depois das do BI): quantos e os primeiros, marcados "Google".
function linhasGoogle(g) {
  if (!g.length) return "";
  return linhaTT("Do Google", fmt.num(g.length)) + g.slice(0, MAX_TOOLTIP).map((e) =>
    `<div class='tt-l'><span>${esc(faixaGoogle(e))} ${esc(e.titulo)}</span><b>Google</b></div>`).join("") +
    (g.length > MAX_TOOLTIP ? `<div class='tt-l'><span>e mais ${g.length - MAX_TOOLTIP} do Google</span></div>` : "");
}

// Uma linha do tooltip do dia: a atividade, a tarefa ou a subtarefa (de quem, se não for minha).
function linhaDoDia(e) {
  let nome;
  if (e.i) nome = atividade(e.i.atividade).titulo;
  else {
    const { t, s } = daRef(e.r);
    nome = s ? `${curto(s.titulo, MAX_DICA)} (${s.minha ? "subtarefa" : `de ${s.responsavel.nome}`})` : `Tarefa: ${t.titulo}`;
  }
  return `<div class='tt-l'><span>${e.faixa ? `${e.faixa} ` : ""}${esc(nome)}</span><b>${(e.i || e.r).feita ? "feita" : "falta"}</b></div>`;
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
  const google = x.google || [];
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
      : google.length ? "" : `<p class="ag-vazio">${icone("calendario")}Nada marcado para este dia.</p>`}
    ${google.length ? `<div class="ag-google-dia">
      <h4>${icone("elo")}Do Google <small>só para ver; não conta nas contas do dia</small></h4>
      <ul class="ag-itens">${google.map((g, k) => googleHtml(g, x.data, lista.length + k, k)).join("")}</ul>
    </div>` : ""}
  </div>`;
  el.querySelector(".ag-fb textarea")?.focus();
}

function itemHtml(i, dia, futuro, n) {
  const a = atividade(i.atividade);
  const repete = a.repeticao !== "nenhuma", varios = variosDias(a);
  const escrevendo = estado.concluindo?.atividade === a.id && estado.concluindo?.dia === dia;
  const dica = futuro ? "Este dia ainda não chegou" : i.feita ? "Desfazer a conclusão" : "Marcar como concluída";
  const encerravel = varios && a.inicio <= estado.dados.hoje && (!a.fim || a.fim > estado.dados.hoje);
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
      <b>${a.hora ? `<span class="ag-hora">${icone("relogio")}${horario(a)}</span>` : ""}${esc(a.titulo)}</b>
      ${a.descricao ? `<p>${esc(a.descricao)}</p>` : ""}
      <div class="ag-chips"><span class="chip">${icone(repete ? "atualizar" : "calendario")}${esc(a.quando)}</span>
        ${a.ocupado ? `<span class="chip ag-c-ocupado" title="Ninguém marca outra coisa para você nesse horário">${icone("cadeado")}Horário ocupado</span>` : ""}
        ${a.exige_feedback ? `<span class="chip laranja">${icone("conversa")}Pede feedback</span>` : ""}</div>
      ${rodape}
    </div>
    <div class="ag-item-acoes">
      ${varios ? `<button type="button" data-historico title="Histórico de feedbacks" aria-label="Histórico de feedbacks de ${esc(a.titulo)}">${icone("caderneta")}</button>` : ""}
      <button type="button" data-editar title="Editar a atividade" aria-label="Editar ${esc(a.titulo)}">${icone("lapis")}</button>
      ${encerravel ? `<button type="button" data-encerrar title="${repete ? "Parar de repetir depois de hoje" : "Terminar hoje"}" aria-label="Encerrar ${esc(a.titulo)}">${icone("bandeira")}</button>` : ""}
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
    s ? chipAutomatica(s) : "",
    // a automática no primeiro dia: até quando ela vai
    s && !vencida && dia < s.prazo ? `<span class="chip">${icone("relogio")}Até ${dataCurta(s.prazo)}</span>` : "",
    vencida ? `<span class="chip ag-c-atrasada">${icone("alerta")}Venceu em ${dataCurta(x.prazo)}</span>` : "",
    // venceu hoje, no horário do prazo: fica no dia, sem ir para o bloco das atrasadas (que é dos dias de antes)
    !vencida && x.atrasada && x.prazo === estado.dados.hoje ? `<span class="chip ag-c-atrasada">${icone("alerta")}Venceu às ${x.hora}</span>` : "",
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
      ${justHtml(x, 1)}${botaoJust(x, "data-justificar")}
    </div>
    <div class="ag-item-acoes">
      <button type="button" data-abrir-tarefa title="Abrir a tarefa" aria-label="Abrir a tarefa ${esc(t.titulo)}">${icone("olho")}</button>
      ${t.eu_criador ? `<button type="button" data-editar title="Editar a tarefa" aria-label="Editar a tarefa ${esc(t.titulo)}">${icone("lapis")}</button>
        <button type="button" class="perigo" data-excluir title="Excluir a tarefa" aria-label="Excluir a tarefa ${esc(t.titulo)}">${icone("lixeira")}</button>` : ""}
    </div>
  </li>`;
}

// Um evento do Google no dia aberto: só para ver (sem o check), com a agenda de onde vem, se está ocupado e o botão de
// trazer como atividade. k: a posição dele no dia (data-google).
function googleHtml(g, dia, n, k) {
  const continua = [g.antes ? `desde ${dataCurta(g.de)}` : "", g.depois ? `até ${dataCurta(g.ate)}` : ""].filter(Boolean).join(", ");
  return `<li class="ag-item ag-google" style="--i:${n}" data-google="${k}" data-dia="${dia}">
    <span class="ag-g-marca" aria-hidden="true">${icone("elo")}</span>
    <div class="ag-item-t">
      <b><span class="ag-hora">${icone(g.dia_todo ? "calendario" : "relogio")}${faixaGoogle(g)}</span>${esc(g.titulo)}</b>
      <div class="ag-chips"><span class="chip ag-c-google">${icone("elo")}Google · ${esc(g.agenda)}</span>
        ${continua ? `<span class="chip">${icone("calendario")}${capitalizar(continua)}</span>` : ""}
        ${g.ocupado ? `<span class="chip ag-c-ocupado" title="Ninguém põe você numa tarefa nesse horário">${icone("cadeado")}Ocupado</span>` : ""}
        ${g.desatualizada ? `<span class="chip ag-c-atrasada" title="A agenda não é lida há mais de um dia">${icone("alerta")}Pode estar desatualizado</span>` : ""}</div>
    </div>
    <div class="ag-item-acoes">
      <button type="button" data-trazer title="Trazer como atividade" aria-label="Trazer ${esc(g.titulo)} como atividade">${icone("mais")}</button>
    </div>
  </li>`;
}

// Trazer como atividade: o formulário de atividade nova, preenchido com o evento (uma cópia só; depois, as duas ficam
// independentes). O de dia inteiro de vários dias vira a única de vários dias; o de horário, o pedaço deste dia (o que
// vem da meia-noite começa às 00:00; o que vai até ela fica sem o fim).
function trazerDoGoogle(li) {
  const dia = li.dataset.dia;
  const g = estado.dados.dias.find((x) => x.data === dia).google[Number(li.dataset.google)];
  const varios = g.dia_inteiro && g.ate > g.de;
  const modelo = { titulo: curto(g.titulo, 120), inicio: varios ? g.de : dia, fim: varios ? g.ate : null,
                   hora: g.dia_todo ? null : g.hora || "00:00", hora_fim: g.dia_todo ? null : g.hora_fim };
  return abrirForm(null, "atividade", modelo.inicio, modelo);
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
  if ("google" in b.dataset) return abrirGoogle({ aoMudar: () => carregar() }); // o botão do topo e o do aviso
  if (b.dataset.vista) return escolherVista(b.dataset.vista);
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
    if (p.autonomia && estado.tf.automaticas.has(p.id)
        && !confirm(`Tirar a autonomia de ${p.nome}? Ao salvar, a subtarefa automática que pede para programar a execução sai.`)) return;
    p.autonomia = !p.autonomia;
    return desenharPessoas();
  }
  if (b.dataset.tirarPessoa) return tirarPessoa(Number(b.dataset.tirarPessoa));
  if (b.dataset.recolherPessoa) return expandirPessoa(Number(b.dataset.recolherPessoa));
  if (b.dataset.abrirSub) return focarSub(Number(b.dataset.abrirSub), "titulo");
  // recolher a subtarefa aberta: no lugar dela, uma nova em branco no mesmo card
  if ("fecharSub" in b.dataset) return maisSub(estado.tf.subtarefas[estado.tf.aberta].responsavel);
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
  if ("google" in li.dataset) return "trazer" in b.dataset ? trazerDoGoogle(li) : undefined; // só para ver
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
  // Enter no título da subtarefa vai para os dias (Enter num deles guarda a subtarefa e abre a próxima nele), em vez
  // de salvar a tarefa inteira
  if (e.key === "Enter" && t.matches('#ag-pessoas .ag-sub-linha [data-campo="titulo"]')) {
    e.preventDefault();
    return focarDia(t.closest(".ag-sub-linha").querySelector('[data-campo="prazo"]'));
  }
  if (!t.matches(".ag-fb textarea")) return;
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); t.closest(".ag-item").querySelector("[data-confirmar]").click(); }
  if (e.key === "Escape") { estado.concluindo = null; desenharDia(false); }
}

// O título da subtarefa (no formulário e na janela da tarefa) é uma caixa de texto que cresce com ele.
function aoDigitar(e) {
  if (e.target.matches('textarea[data-campo="titulo"]')) ajustarTitulo(e.target);
}

// A altura da caixa do título da subtarefa: a do texto, até MAX_ALTURA_TITULO (depois, rola). O título não tem quebras
// de linha (Enter vai para os dias, ou cria a subtarefa na janela): as de um texto colado viram espaço. Escondida, a
// caixa fica como está. A conta vai duas vezes: a caixa mais alta pode dar à janela da tarefa a barra de rolagem, que
// estreita a caixa e pede mais uma linha.
function ajustarTitulo(t) {
  if (/[\r\n]/.test(t.value)) t.value = t.value.replace(/\s*[\r\n]+\s*/g, " ");
  if (!t.offsetHeight) return;
  const bordas = t.offsetHeight - t.clientHeight;
  t.style.height = "auto";
  for (let i = 0; i < 2; i++) t.style.height = `${Math.min(t.scrollHeight + bordas, MAX_ALTURA_TITULO)}px`;
  t.style.overflowY = t.scrollHeight > t.clientHeight ? "auto" : "hidden";
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
  const como = a.repeticao === "nenhuma" ? "Ela termina hoje" : "Ela para de se repetir depois de hoje";
  if (!confirm(`Encerrar "${a.titulo}"? ${como}; o histórico fica guardado.`)) return;
  try {
    await api("/api/agenda/atividade/encerrar", { json: { id: a.id } });
    toast("Atividade encerrada");
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

async function excluir(a) {
  const aviso = !variosDias(a) ? "" : " Todo o histórico de feedbacks dela também é apagado; para só parar antes, use Encerrar.";
  if (!confirm(`Excluir "${a.titulo}"?${aviso}`)) return;
  try {
    await api("/api/agenda/atividade/excluir", { json: { id: a.id } });
    toast("Atividade excluída");
    await carregar();
  } catch (e) { toast(e.message, "erro"); }
}

// ---------- tarefas ----------
// Grava uma mudança numa tarefa; a resposta traz a tarefa como ficou, que redesenha a janela (se for a aberta).
// O que gravou num horário ocupado do Google da própria pessoa: gravou assim mesmo, com o aviso (toast amarelo).
function avisar(r) {
  for (const a of r?.avisos || []) toast(capitalizar(a), "aviso");
}

async function mexer(url, json, aviso) {
  try {
    const r = await api(url, { json });
    if (aviso) toast(aviso);
    avisar(r);
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

// Muda a situação da tarefa (na janela dela). No kanban, o card já muda: concluída, vai para Concluídas; reaberta,
// volta para a coluna do prazo. A resposta confirma (ou o recarregar devolve ele).
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
  dlg.addEventListener("input", aoDigitar);
  dlg.addEventListener("keydown", (e) => {
    // Ctrl+Enter envia; no título da subtarefa, que não tem quebras de linha, o Enter também (como num campo de uma
    // linha)
    const titulo = e.target.matches('[data-sub-form] [data-campo="titulo"]');
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey || titulo) && e.target.closest("[data-sub-form], [data-just-form]")) {
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
        <p class="sub">${esc(at.quando)}${at.hora ? ` · ${horario(at)}` : ""} · desde ${dataCurta(at.inicio)}</p></div>
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
    ${blocoJust(t, "tarefa")}
    ${t.eu_criador ? `<div class="ag-tf-acoes">
      <button class="btn" type="button" data-tf-editar>${icone("lapis")}Editar</button>
      <button class="btn perigo" type="button" data-tf-excluir>${icone("lixeira")}Excluir</button>
    </div>` : ""}
    <span class="cf-rotulo ag-hist-rotulo">Pessoas e subtarefas</span>
    <div class="ag-pessoas">${pessoasDaTarefa(t).map((p) => cartaoTarefa(t, p)).join("")}</div>
  </div>`;
  prepararDias(dlg);
  dlg.querySelectorAll('textarea[data-campo="titulo"]').forEach(ajustarTitulo);
  janela.inicial = janela.editando != null || janela.justificando != null ? JSON.stringify(lerEdicaoJanela()) : null;
}

function subHtml(t, s) {
  if (janela.editando === s.id) return `<li class="ag-item-form">${formSubHtml(t, s)}</li>`;
  return `<li class="ag-item ag-sub-item st-${s.situacao}" data-sub="${s.id}">
    <div class="ag-item-t">
      <b>${esc(s.titulo)}</b>
      ${s.descricao ? `<p>${esc(s.descricao)}</p>` : ""}
      <div class="ag-chips">
        ${chipAutomatica(s)}
        <span class="chip ${s.atrasada ? "ag-c-atrasada" : ""}">${icone(s.atrasada ? "alerta" : "relogio")}${s.atrasada ? "Venceu em" : diasDaSub(s)} ${prazoTxt(s)}</span>
        ${s.feita ? `<span class="chip ag-c-feita">${icone("visto")}${textoConclusao(t, s, s.prazo)}</span>` : ""}
      </div>
      <div class="ag-sub-st">${situacaoHtml(s, "data-sub-situacao", `Situação de ${s.titulo}`, s.pode.concluir, dicaCheck(t, s, "mudam a situação"))}</div>
      ${blocoJust(s, s.id)}
    </div>
    <div class="ag-item-acoes">
      ${s.pode.editar_texto ? `<button type="button" data-sub-editar title="Editar a subtarefa" aria-label="Editar ${esc(s.titulo)}">${icone("lapis")}</button>` : ""}
    </div>
  </li>`;
}

// As justificativas do atraso de x (a tarefa ou uma subtarefa; todos da tarefa veem), da mais nova para a mais
// antiga, cada uma com quem escreveu, quando e, se foi de um prazo que depois mudou, qual. quantas: no dia, só a
// última (com quantas há antes); na janela da tarefa, todas.
function justHtml(x, quantas = Infinity) {
  const js = x.justificativas, mostrar = js.slice(0, quantas), antes = js.length - mostrar.length;
  return mostrar.map((j, n) => `<div class="ag-just"><p>${icone("conversa")}<span>${esc(j.texto)}</span></p>
    <small><span>Justificativa do atraso${j.por ? ` · ${esc(j.por.nome)}` : ""}, ${quando(j.criada_em, x.prazo)}${j.do_prazo ? "" : ` · do prazo de ${prazoTxt(j)}`}${n === mostrar.length - 1 && antes ? ` · e ${plural(antes, "outra antes", "outras antes")}` : ""}</span></small></div>`).join("");
}

// O botão de justificar (attr: data-justificar, no dia, ou data-just="alvo", na janela), para quem responde pelo
// atraso: cada justificativa se acrescenta às de antes.
function botaoJust(x, attr) {
  if (!x.pode.justificar) return "";
  return `<button type="button" class="ge-link ag-just-abrir" ${attr}>${icone("conversa")}${x.justificativas.length ? "Justificar de novo" : "Justificar o atraso"}</button>`;
}

// Na janela: as justificativas e, embaixo, o formulário (se está aberto) ou o botão. alvo: "tarefa" ou o id da
// subtarefa.
function blocoJust(x, alvo) {
  return justHtml(x) + (janela.justificando === alvo ? formJustHtml(alvo) : botaoJust(x, `data-just="${alvo}"`));
}

function formJustHtml(alvo) {
  return `<form class="ag-fb ag-just-form" data-just-form="${alvo}" novalidate>
    <textarea data-campo="justificativa" rows="2" maxlength="2000" aria-label="Justificativa do atraso"
      placeholder="Por que atrasou? Todos da tarefa veem."></textarea>
    <div class="ag-fb-acoes"><button class="btn" type="button" data-just-cancelar>Cancelar</button>
      <button class="btn primario" type="submit">${icone("enviar")}Enviar justificativa</button></div>
  </form>`;
}

// A subtarefa nova (no card da pessoa) ou em edição, na janela: quem criou muda tudo (na edição, até passar para outra
// pessoa); o participante com autonomia, o texto e o prazo das que ele mesmo cria (na nova, escolhe o dia).
function formSubHtml(t, s) {
  const pessoas = [t.criador, ...t.participantes];
  const v = s || { titulo: "", descricao: "", responsavel: pessoas.find((p) => p.id === janela.para) || t.criador,
                   prazo: t.prazo, hora: t.hora };
  const passar = s && t.eu_criador; // passar para outra pessoa, só quem criou
  const responsavel = passar ? `<label class="campo-form"><span>Responsável</span><span class="campo"><select data-campo="responsavel">${pessoas.map((p) =>
      `<option value="${p.id}" ${p.id === v.responsavel.id ? "selected" : ""}>${esc(p.nome)}${p.id === t.criador.id ? " (você)" : ""}</option>`).join("")}</select></span></label>`
    : s ? "" : `<input type="hidden" data-campo="responsavel" value="${v.responsavel.id}">`;
  const prazo = s ? s.pode.editar_prazo : true; // a nova: quem pode criar escolhe o dia
  const campos = prazo ? `<div class="ag-sub-edit-campos ${passar ? "" : "sem-responsavel"}">
      ${responsavel}
      <label class="campo-form"><span>Horário <small>(opcional)</small></span><input type="time" data-campo="hora" value="${v.hora || ""}"></label>
    </div>
    <div class="campo-form"><span>Prazo</span>${campoDia({ campo: "prazo", valor: v.prazo, max: t.prazo, maxDica: "Depois do prazo da tarefa",
      rotulo: "Prazo da subtarefa", contar: v.responsavel.id === t.eu })}</div>`
    : `<small class="ag-sub-prazo">${icone("cadeado")}Prazo: ${prazoTxt(s)}. Só ${esc(t.criador.nome)}, que criou a tarefa, muda.</small>`;
  return `<form class="ag-sub-edit" data-sub-form="${s ? s.id : "nova"}" novalidate>
    <label class="campo-form"><span>${s ? "Subtarefa" : "Nova subtarefa"}</span>
      <textarea data-campo="titulo" rows="1" maxlength="2000" autocomplete="off" placeholder="O que fazer">${esc(v.titulo)}</textarea></label>
    <label class="campo-form"><span>Descrição <small>(opcional)</small></span>
      <textarea data-campo="descricao" rows="2" maxlength="2000">${esc(v.descricao)}</textarea></label>
    ${campos}
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

// Acrescenta uma justificativa do atraso da tarefa ou da subtarefa (as de antes ficam: é um histórico).
async function enviarJust(f, t, texto) {
  const tarefa = f.dataset.justForm === "tarefa";
  const x = tarefa ? t : subDe(t, Number(f.dataset.justForm));
  if (!texto) {
    toast("Escreva por que atrasou", "erro");
    return f.querySelector("textarea").focus();
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const r = await mexer(`/api/agenda/${tarefa ? "tarefa" : "subtarefa"}/justificar`, { id: x.id, justificativa: texto },
    "Justificativa enviada");
  if (!r && f.isConnected) botao.disabled = false;
}

// ---------- formulário (em tela cheia) ----------
// Atividade ou tarefa nova (no dia `dia`) ou a edição de uma (item, com o tipo), numa janela que cobre a tela. modelo:
// os campos com que a atividade nova já abre (o evento do Google trazido como atividade).
async function abrirForm(item = null, tipo = item ? item.tipo : estado.tipo, dia = estado.aberto || hojeLocal(), modelo = null) {
  if (tipo === "tarefa" && !(await garantirPessoas())) return;
  desenharForm(item, tipo, dia, modelo);
  if (!tela.open) tela.showModal();
  tela.querySelector('[name="titulo"]').focus();
}

// Fechar pergunta antes de descartar o que foi preenchido (depois de salvar, não).
function fecharForm(salvo = false) {
  if (!salvo && formMudou() && !confirm(DESCARTAR_FORM)) return;
  tela.close();
}

function desenharForm(item, tipo, dia, modelo = null) {
  Object.assign(estado, { tipo, editando: item, formDia: dia, tf: null }); // formTarefa monta o tf da tarefa
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
    <div class="ag-tela-corpo"><div class="ag-tela-grade">${ehTarefa ? formTarefa(item, dia) : formAtividade(item, dia, modelo)}</div></div>
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

// Duas partes, uma embaixo da outra: o que é (e se pede feedback) e quando (a repetição, os dias e o horário, que
// pode ficar ocupado).
function formAtividade(a, dia, modelo = null) {
  const v = a || { titulo: "", descricao: "", inicio: dia, hora: null, hora_fim: null, ocupado: false, repeticao: "nenhuma",
                   dias_semana: null, dia_mes: null, intervalo: null, so_dias_uteis: false, regiao: null, fim: null,
                   exige_feedback: false, ...modelo };
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
      <div class="campo-form"><span data-rotulo-fim></span>
        ${campoDia({ nome: "fim", valor: v.fim, min: v.inicio, vazio: "Só neste dia", rotulo: "Último dia da atividade" })}</div>
      <div class="campo-form ag-horario"><span>Horário <small>(opcional)</small></span>
        <div class="ag-horario-campos">
          <label><small>Começa às</small><input type="time" name="hora" value="${v.hora || ""}"></label>
          <label><small>Termina às</small><input type="time" name="hora_fim" value="${v.hora_fim || ""}"></label>
        </div>
        <label class="vend-op" data-ocupado ${v.hora ? "" : "hidden"}><input type="checkbox" name="ocupado" ${v.ocupado ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
          <span class="n">Horário ocupado<small>Ninguém marca outra coisa para você nesse horário: nem você, nem quem cria tarefas. Precisa do fim do horário.</small></span></label>
      </div>
    </div>`;
}

// O formulário da tarefa: o que é e o prazo; embaixo, as pessoas e as subtarefas. Participantes e subtarefas ficam em
// estado.tf (desenharPessoas: um card por pessoa, com as subtarefas dela; expandida: a pessoa com o card aberto, uma
// de cada vez; aberta: a subtarefa aberta para editar, a única com os campos, enquanto as outras mostram só o texto; a
// nova que está sendo escrita leva compondo); os campos da subtarefa usam data-campo, não name: com nomes repetidos,
// f.elements.titulo deixaria de ser o da tarefa. As subtarefas automáticas (a que pede para programar a execução) não
// entram no formulário: o servidor cuida delas pela autonomia; automaticas guarda de quem elas são.
function formTarefa(t, dia) {
  const subs = t ? t.subtarefas.filter((s) => !s.automatica) : [];
  estado.tf = {
    participantes: t ? t.participantes.map((p) => ({ id: p.id, nome: p.nome, autonomia: p.autonomia })) : [],
    subtarefas: subs.map((s) => ({ id: s.id, titulo: s.titulo, descricao: s.descricao, responsavel: s.responsavel.id,
                                   prazo: s.prazo, hora: s.hora || "" })),
    automaticas: new Set(t ? t.subtarefas.filter((s) => s.automatica).map((s) => s.responsavel.id) : []),
    expandida: null,
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
        <small>Clique no nome de uma pessoa para criar as subtarefas dela: escolha o dia, escreva o que fazer e escolha o
          dia da próxima (a que você escreveu fica guardada). Quem entra já vem com autonomia: edita o texto das
          próprias subtarefas, cria subtarefas para si (escolhendo o dia) e recebe uma subtarefa automática pedindo
          para programar a execução, no dia em que entra e no seguinte (pulando sábado e domingo). Tirando a
          autonomia, ela sai. Os
          prazos das subtarefas que você cria, só você muda.</small>
      </div>
    </div>`;
}

// Um card por pessoa (você primeiro, depois os participantes), com as subtarefas dela dentro. Só o da pessoa
// expandida fica aberto, com uma subtarefa nova em branco no fim (expandirPessoa); os outros mostram só a pessoa.
function desenharPessoas() {
  const f = raiz.querySelector("#ag-form");
  const { participantes, subtarefas, expandida } = estado.tf;
  const eu = estado.pessoas.eu, prazo = f.elements.prazo.value, hora = f.elements.hora.value || null;
  const lista = f.querySelector("#ag-pessoas");
  lista.innerHTML = [{ id: eu.id, nome: eu.nome, voce: true }, ...participantes].map((p) => {
    const linhas = subtarefas.map((s, n) => [s, n]).filter(([s]) => s.responsavel === p.id);
    const escritas = linhas.filter(([s]) => !emBranco(s)).length; // a nova em branco ainda não conta
    const resumo = escritas ? plural(escritas, "subtarefa", "subtarefas") : "sem subtarefas";
    const fechado = p.id !== expandida;
    return `<div class="ag-pessoa-card ${fechado ? "recolhido" : ""}">
      <div class="ag-pessoa-cab">
        ${nomeDoCard(p, resumo, fechado)}
        ${p.voce ? "" : `<button type="button" class="ag-pessoa-op ${p.autonomia ? "ativo" : ""}" data-autonomia="${p.id}" aria-pressed="${p.autonomia}"
          title="${p.autonomia ? "Com autonomia: edita o texto das próprias subtarefas, cria subtarefas para si e recebe a subtarefa automática para programar a execução. Clique para tirar." : "Sem autonomia: só conclui as próprias subtarefas. Clique para dar autonomia."}">${icone("chave")}Autonomia</button>
        <button type="button" class="ag-pessoa-op ag-pessoa-x" data-tirar-pessoa="${p.id}" title="Tirar ${esc(p.nome)} da tarefa" aria-label="Tirar ${esc(p.nome)} da tarefa">${icone("x")}</button>`}
      </div>
      <div class="ag-pessoa-corpo">${linhas.map(([s, n]) => linhaSub(s, n, p, prazo, hora)).join("")}</div>
    </div>`;
  }).join("");
  prepararDias(lista);
  lista.querySelectorAll('textarea[data-campo="titulo"]').forEach(ajustarTitulo);
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

// Na janela da tarefa: recolhe ou abre o card do botão (sem redesenhar: o que está sendo digitado continua);
// recolhidos guarda a escolha.
function alternarCard(b, recolhidos) {
  const card = b.closest(".ag-pessoa-card");
  const fechar = !card.classList.contains("recolhido");
  card.classList.toggle("recolhido", fechar);
  if (fechar) recolhidos.add(Number(b.dataset.recolherPessoa)); else recolhidos.delete(Number(b.dataset.recolherPessoa));
  b.setAttribute("aria-expanded", String(!fechar));
  b.title = b.title.replace(fechar ? "Esconder" : "Mostrar", fechar ? "Mostrar" : "Esconder");
}

// Uma subtarefa no card da pessoa p. Recolhida: só o texto e o prazo (em vermelho se passa do da tarefa), e clicar
// abre. Aberta (a de estado.tf.aberta): em cima, os dias (até o prazo da tarefa); embaixo, o título com o horário ao
// lado. A que está sendo escrita (compondo) fica sem a seta e o x: escolher outro dia guarda ela e abre a próxima.
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
  const nova = !!s.compondo;
  return `<div class="ag-sub-linha ${nova ? "compondo" : ""}" data-n="${n}">
      ${campoDia({ campo: "prazo", valor: s.prazo, max: prazoTarefa, maxDica: "Depois do prazo da tarefa", rotulo: `Prazo da subtarefa de ${de}`,
                   contar: !!p.voce })}
      <div class="ag-sub-topo">
        ${nova ? "" : `<button type="button" class="ag-sub-recolher" data-fechar-sub title="Recolher a subtarefa" aria-expanded="true"
          aria-label="Recolher a subtarefa">${icone("setaBaixo")}</button>`}
        <textarea data-campo="titulo" rows="1" maxlength="2000" autocomplete="off"
          placeholder="${nova ? "Nova subtarefa: o que fazer" : "O que fazer"}" aria-label="Subtarefa de ${esc(de)}">${esc(s.titulo)}</textarea>
        ${hora}
        ${nova ? "" : tirar}
      </div>
    </div>`;
}

// Uma subtarefa nova em que nada foi escrito: não conta ao salvar e some quando outra abre.
const emBranco = (s) => !s.id && !s.titulo.trim();

// Abre a subtarefa n para editar (a que estava aberta se recolhe) ou, com null, recolhe a aberta; as novas deixadas
// em branco saem, e a que estava sendo escrita, com o nome, fica guardada. Devolve a posição de n depois disso.
function abrirSub(n) {
  lerSubs();
  const alvo = n == null ? null : estado.tf.subtarefas[n];
  estado.tf.subtarefas = estado.tf.subtarefas.filter((s) => s === alvo || !emBranco(s));
  estado.tf.subtarefas.forEach((s) => { if (s !== alvo) delete s.compondo; });
  estado.tf.aberta = alvo ? estado.tf.subtarefas.indexOf(alvo) : null;
  if (alvo) estado.tf.expandida = alvo.responsavel;
  desenharPessoas();
  return estado.tf.aberta;
}

// Clicar no nome da pessoa abre o card dela (o que estava aberto se recolhe) já com uma subtarefa nova no prazo da
// tarefa e o foco nos dias, para escolher o dia antes do nome; clicar de novo recolhe.
function expandirPessoa(id) {
  if (estado.tf.expandida !== id) return maisSub(id);
  estado.tf.expandida = null;
  abrirSub(null);
}

// O dia escolhido (clique ou Enter num quadradinho) na subtarefa aberta:
// - na que está sendo escrita, ainda sem nome, ele é o dia dela, e o cursor vai para o nome;
// - na que está sendo escrita, com o nome, ele é o da próxima: ela fica guardada com o dia que tinha e abre outra
//   nesse dia;
// - numa que estava sendo corrigida, ele é o novo dia dela, que se recolhe, e abre outra nesse dia.
function aoEscolherDia(e) {
  const linha = e.target.closest("#ag-pessoas .ag-sub-linha");
  if (!linha) return;
  const s = estado.tf.subtarefas[Number(linha.dataset.n)];
  const dia = e.target.value;
  lerSubs(); // com o nome escrito, a que está sendo escrita não lê o dia (lerSubs)
  if (s.compondo) {
    if (!s.titulo.trim()) return linha.querySelector('[data-campo="titulo"]').focus();
    delete s.compondo;
    linha.querySelector('[data-campo="prazo"]').value = s.prazo; // o próximo lerSubs lê o dia dela, não o clicado
  }
  maisSub(s.responsavel, dia, "titulo");
}

// Copia o que foi digitado nas linhas de subtarefa para estado.tf (antes de redesenhar ou de enviar). Na que está
// sendo escrita, com o nome já escrito, os dias são os da próxima: o dia dela fica o que era.
function lerSubs() {
  raiz.querySelectorAll("#ag-pessoas .ag-sub-linha").forEach((linha) => {
    const s = estado.tf.subtarefas[Number(linha.dataset.n)];
    const comNome = s.compondo && !!linha.querySelector('[data-campo="titulo"]')?.value.trim();
    linha.querySelectorAll("[data-campo]").forEach((c) => {
      if (!(comNome && c.dataset.campo === "prazo")) s[c.dataset.campo] = c.value;
    });
  });
}

// Uma subtarefa nova (a que está sendo escrita) no card da pessoa, que abre: no dia `dia` (sem ele, no prazo da
// tarefa), com o foco nos dias ou no nome (foco: "prazo" ou "titulo"). As outras ficam recolhidas, só com o texto.
function maisSub(responsavel, dia = null, foco = "prazo") {
  lerSubs();
  const f = raiz.querySelector("#ag-form");
  estado.tf.subtarefas.push({ id: null, titulo: "", descricao: "", responsavel, prazo: dia || f.elements.prazo.value || hojeLocal(),
                              hora: "", compondo: true });
  focarSub(estado.tf.subtarefas.length - 1, foco);
}

// Põe o foco num campo da subtarefa n (no prazo, o dia escolhido), abrindo ela e o card dela.
function focarSub(n, campo) {
  if (estado.tf.aberta !== n) n = abrirSub(n);
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
  if (estado.tf.expandida === id) estado.tf.expandida = null;
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

// Os campos da repetição escolhida e os rótulos dos dias: na única, o último dia faz dela uma atividade de vários dias;
// na que se repete, é quando ela para.
function mostrarCampos() {
  const f = raiz.querySelector("#ag-form");
  const rep = estado.form.repeticao, unica = rep === "nenhuma";
  f.querySelectorAll("[data-para]").forEach((el) => { el.hidden = !el.dataset.para.split(" ").includes(rep); });
  f.querySelector("[data-rotulo-inicio]").textContent = unica ? "Dia" : "Começa em";
  f.querySelector("[data-rotulo-fim]").innerHTML = unica ? "Até <small>(opcional, para vários dias)</small>" : "Termina em <small>(opcional)</small>";
  f.elements.fim.closest(".ed").dataset.vazio = unica ? "Só neste dia" : "Sem data para terminar";
  limitesDoDia(f.elements.fim); // redesenha com o texto de quando não há o último dia
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
  // o horário ocupado aparece quando a atividade tem o começo do horário
  if (t.name === "hora" && !estado.tf) t.form.querySelector("[data-ocupado]").hidden = !t.value;
  // o prazo da tarefa limita o das subtarefas (e as recolhidas avisam se passam dele); o começo da atividade, o fim
  if ((t.name === "prazo" || t.name === "hora") && estado.tf) {
    lerSubs();
    desenharPessoas();
  }
  if (t.name === "inicio") limitesDoDia(t.form.elements.fim, { min: t.value });
  // a subtarefa sendo escrita, ainda sem nome: o dia escolhido (também andando com as setas) é o dela
  if (t.dataset.campo === "prazo" && estado.tf) {
    const linha = t.closest("#ag-pessoas .ag-sub-linha");
    const s = linha && estado.tf.subtarefas[Number(linha.dataset.n)];
    if (s?.compondo && !linha.querySelector('[data-campo="titulo"]').value.trim()) s.prazo = t.value;
  }
  if (t.matches("[data-add-pessoa]") && t.value) {
    lerSubs();
    const p = estado.pessoas.pessoas.find((x) => x.id === Number(t.value));
    estado.tf.participantes.push({ id: p.id, nome: p.nome, autonomia: true }); // quem entra começa com autonomia
    estado.tf.participantes.sort((a, b) => a.nome.localeCompare(b.nome));
    maisSub(p.id); // o card de quem entrou já abre, pronto para a primeira subtarefa
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
  const hora = f.elements.hora.value || null;
  return {
    titulo: f.elements.titulo.value.trim(), descricao: f.elements.descricao.value.trim(), inicio: f.elements.inicio.value,
    hora, hora_fim: (hora && f.elements.hora_fim.value) || null, ocupado: !!hora && f.elements.ocupado.checked,
    repeticao: rep, dias_semana: rep === "semanal" ? [...estado.form.dias].sort() : null,
    dia_mes: rep === "mensal" ? num("dia_mes") : null, intervalo: rep === "intervalo" ? num("intervalo") : null,
    so_dias_uteis: uteis, regiao: uteis ? estado.form.regiao : null,
    fim: f.elements.fim.value || null, // na única, o último dia de uma atividade de vários dias
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
    subtarefas: estado.tf.subtarefas.filter((s) => !emBranco(s)).map((s) => ({
      id: s.id, titulo: s.titulo.trim(), descricao: s.descricao, responsavel: s.responsavel, prazo: s.prazo, hora: s.hora || null })),
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
  if (f.elements.hora_fim.value && !dados.hora) { toast("Diga a que horas a atividade começa", "erro"); return f.elements.hora.focus(); }
  if (dados.hora_fim && dados.hora_fim <= dados.hora) {
    toast("O fim do horário tem de ser depois do começo", "erro");
    return f.elements.hora_fim.focus();
  }
  if (dados.ocupado && !dados.hora_fim) {
    toast("Para marcar o horário como ocupado, diga a que horas ele termina", "erro");
    return f.elements.hora_fim.focus();
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const editando = estado.editando;
  try {
    const r = editando ? await api("/api/agenda/atividade/editar", { json: { id: editando.id, atividade: dados } })
      : await api("/api/agenda/atividades", { json: { atividade: dados } });
    toast(editando ? "Atividade salva" : "Atividade criada");
    avisar(r);
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
  // pelas posições em estado.tf (as em branco, que não vão, ficam de fora), para abrir a que tem problema
  for (const [n, s] of estado.tf.subtarefas.entries()) {
    if (emBranco(s)) continue;
    if (!s.titulo.trim()) { toast("Escreva o título da subtarefa", "erro"); return focarSub(n, "titulo"); }
    if (depoisDoPrazo(s, dados)) {
      toast(`A subtarefa "${curto(s.titulo, MAX_DICA)}" vence depois da tarefa: o prazo dela vai até o da tarefa`, "erro");
      return focarSub(n, "prazo");
    }
  }
  const botao = f.querySelector('[type="submit"]');
  botao.disabled = true;
  const editando = estado.editando;
  try {
    const r = editando ? await api("/api/agenda/tarefa/editar", { json: { id: editando.id, versao: editando.versao, tarefa: dados } })
      : await api("/api/agenda/tarefas", { json: { tarefa: dados } });
    toast(editando ? "Tarefa salva" : "Tarefa criada");
    avisar(r);
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

// A coluna da tarefa no kanban: a concluída em Concluídas; a aberta, a do vencimento do prazo (vem do servidor).
const colunaDe = (t) => (t.situacao === "concluida" ? "concluida" : t.vencimento);

// O período de cada coluna, embaixo do nome: "30/10", "31/10 a 01/11", "De 02/11 em diante".
function periodo(k, q) {
  const amanha = somarDias(q.hoje, 1);
  if (k === "semana") {
    if (q.semana_ate === q.hoje) return "A semana acaba hoje";
    return amanha === q.semana_ate ? dataCurta(amanha) : `${dataCurta(amanha)} a ${dataCurta(q.semana_ate)}`;
  }
  return { vencido: "O prazo já passou", hoje: dataCurta(q.hoje), depois: `De ${dataCurta(somarDias(q.semana_ate, 1))} em diante`,
           concluida: `Nos últimos ${q.dias_concluidas} dias` }[k];
}

// As colunas: as abertas pelo prazo (no mesmo dia, pelo horário, e as sem horário por último); Concluídas, as
// concluídas por último primeiro.
function desenharQuadro(animar) {
  const q = estado.quadro;
  const colunas = Object.fromEntries(COLUNAS.map(([k]) => [k, []]));
  q.tarefas.forEach((t) => colunas[colunaDe(t)].push(t));
  const peloPrazo = (a, b) => a.prazo.localeCompare(b.prazo) || (a.hora == null) - (b.hora == null) || (a.hora || "").localeCompare(b.hora || "");
  for (const [k] of COLUNAS) if (k !== "concluida") colunas[k].sort(peloPrazo);
  colunas.concluida.sort((a, b) => String(b.concluida_em || "~").localeCompare(String(a.concluida_em || "~")));
  escreverCabecalho();
  raiz.querySelector("#ag-quadro").innerHTML = `<div class="ag-colunas ${animar ? "abre" : ""}">${COLUNAS.map(([k, nome, vazia]) => `
      <section class="ag-coluna" data-coluna="${k}" aria-label="${nome}">
        <h3><i class="ag-st" aria-hidden="true"></i><span class="ag-coluna-t">${nome}<small>${periodo(k, q)}</small></span><span class="ag-coluna-n">${colunas[k].length}</span></h3>
        <ul class="ag-cards">${colunas[k].map(cardHtml).join("") || `<li class="ag-coluna-vazia">${vazia}</li>`}</ul>
      </section>`).join("")}</div>
    <p class="ag-quadro-dica">${icone("info")}Clique no card para abrir a tarefa e mudar a situação. As colunas seguem o prazo da tarefa (a semana vai de segunda a domingo); as concluídas saem do kanban ${q.dias_concluidas} dias depois.</p>`;
}

function cardHtml(t, n) {
  const minhas = t.subtarefas.filter((s) => s.minha && !s.feita);
  // as suas que vencem antes da tarefa: o card fica na coluna do prazo da tarefa, com o aviso
  const vencidas = minhas.filter((s) => s.atrasada).length;
  const hoje = minhas.filter((s) => !s.atrasada && s.prazo === estado.quadro.hoje).length;
  const chips = [
    t.feita ? `<span class="chip ag-c-feita">${icone("visto")}Concluída em ${dataCurta(t.concluida_em.slice(0, 10))}</span>`
      : `<span class="chip ${t.atrasada ? "ag-c-atrasada" : ""}">${icone(t.atrasada ? "alerta" : "relogio")}${t.atrasada ? "Venceu em" : "Até"} ${prazoTxt(t)}</span>`,
    t.situacao === "fazendo" ? `<span class="chip ag-c-fazendo">${icone("relogio")}Fazendo</span>` : "",
    !t.eu_criador ? `<span class="chip">${icone("usuario")}De ${esc(t.criador.nome)}</span>` : "",
    t.participantes.length ? `<span class="chip" title="${esc(t.participantes.map((p) => p.nome).join(", "))}">${icone("pessoas")}${plural(t.participantes.length + 1, "pessoa", "pessoas")}</span>` : "",
    minhas.length ? `<span class="chip ag-c-tarefa" title="Subtarefas suas que faltam">${icone("tarefa")}${plural(minhas.length, "subtarefa sua", "subtarefas suas")}</span>` : "",
    vencidas ? `<span class="chip ag-c-atrasada">${icone("alerta")}${vencidas === 1 ? "Sua subtarefa venceu" : `${fmt.num(vencidas)} subtarefas suas venceram`}</span>` : "",
    hoje ? `<span class="chip ag-c-hoje">${icone("relogio")}${hoje === 1 ? "Sua subtarefa vence hoje" : `${fmt.num(hoje)} subtarefas suas vencem hoje`}</span>` : "",
    t.justificativas.length ? `<span class="chip ag-c-justificada" title="${esc(t.justificativas[0].texto)}">${icone("conversa")}Atraso justificado</span>` : "",
  ].filter(Boolean).join("");
  return `<li class="ag-card ${t.atrasada ? "atrasada" : ""}" style="--i:${n}" data-card="${t.id}" tabindex="0" role="button"
    title="Clique para abrir" aria-label="Abrir a tarefa ${esc(t.titulo)}">
    <b>${esc(t.titulo)}</b>
    ${t.descricao ? `<p>${esc(t.descricao)}</p>` : ""}
    <div class="ag-chips">${chips}</div>
    ${t.total ? `<div class="ag-card-prog">${barra(t.feitas, t.total - t.feitas)}<span>${t.feitas} de ${plural(t.total, "subtarefa feita", "subtarefas feitas")}</span></div>` : ""}
  </li>`;
}
