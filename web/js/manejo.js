// Página Manejo da Base: os clientes que a campanha sugere passar para a central (pararam de comprar) ou inativar
// (inadimplentes há muito tempo, ou clientes da central que não compram). Quem está marcado para justificar responde
// cliente a cliente até o prazo do mês (pode seguir a sugestão, ou deve continuar como está, com o motivo); depois o
// administrador dá o veredito. Cada resposta e cada veredito ficam no histórico do cliente. As regras, a lista do mês e
// quem pode o quê ficam no servidor (bi/manejo.py); aqui é a apresentação: as duas listas, os filtros, a tabela
// ordenável, o histórico de cada cliente e as respostas, uma a uma ou de vários clientes de uma vez. A tela não mostra
// os códigos do ERP: só os nomes (a busca também acha pelo código do cliente).
import { api, esc, fmt, icone, toast, guardar, ler, clicarOrdem, ordenarPorNiveis, marcaOrdem, linhaOrdem } from "./util.js";
import { multiSelecao } from "./multiselecao.js";
import { ligarTelaCheia, sairTelaCheia, reajustarTelaCheia } from "./telacheia.js";

// decisao: "seguir" = seguir a sugestão; "manter" = fica como está. Os nomes mudam com a lista e com quem responde.
const LISTAS = {
  central: {
    titulo: "Passar para a central", icone: "enviar",
    justificar: { seguir: "Pode passar para a central", manter: "Deve continuar com o vendedor" },
    veredito: { seguir: "Passar para a central", manter: "Continua com o vendedor" },
    curto: { seguir: "Pode passar", manter: "Deve continuar" },
  },
  inativar: {
    titulo: "Inativar", icone: "sair",
    justificar: { seguir: "Pode inativar", manter: "Deve continuar ativo" },
    veredito: { seguir: "Inativar", manter: "Continua ativo" },
    curto: { seguir: "Pode inativar", manter: "Deve continuar" },
  },
};
const FREQUENCIA = { semanal: "Semanal", quinzenal: "Quinzenal", mensal: "Mensal", sem_frequencia: "Sem frequência" };
const ORDEM_FREQ = { semanal: 1, quinzenal: 2, mensal: 3, sem_frequencia: 4 };
const SITUACOES = {
  a_justificar: { rotulo: "A justificar", icone: "relogio", classe: "pendente" },
  justificada: { rotulo: "Justificado", icone: "visto", classe: "justificada" },
  sem_justificativa: { rotulo: "Sem justificativa", icone: "alerta", classe: "sem" },
  aguardando_erp: { rotulo: "Aguardando o ERP", icone: "relogio", classe: "erp" },
  feita: { rotulo: "Feito no ERP", icone: "certo", classe: "feita" },
  mantida: { rotulo: "Continua", icone: "menos", classe: "mantida" },
  saiu: { rotulo: "Saiu da lista", icone: "sair", classe: "saiu" },
};
const ORDEM_SIT = { a_justificar: 1, sem_justificativa: 2, justificada: 3, aguardando_erp: 4, feita: 5, mantida: 6, saiu: 7 };
const MOTIVO_SAIDA = {
  comprou: "voltou a comprar", pagou: "pagou", na_central: "já está na central", inativado: "foi inativado no ERP",
  fora_da_regra: "saiu da regra", outra_sugestao: "passou para a lista de inativação", mantido: "continua como está",
  aplicado: "feito no ERP",
};
// Os filtros da situação. "decidir" (o que espera o veredito) só aparece para o administrador.
const FILTROS = [
  { id: "decidir", rotulo: "Aguardando veredito", admin: true, cabe: (x) => x.situacao === "justificada" || x.situacao === "sem_justificativa" },
  { id: "a_justificar", rotulo: "A justificar", cabe: (x) => x.situacao === "a_justificar" },
  { id: "justificada", rotulo: "Justificados", cabe: (x) => x.situacao === "justificada" },
  { id: "sem_justificativa", rotulo: "Sem justificativa", cabe: (x) => x.situacao === "sem_justificativa" },
  { id: "veredito", rotulo: "Com veredito", cabe: (x) => ["aguardando_erp", "feita", "mantida"].includes(x.situacao) },
  { id: "saiu", rotulo: "Saíram", cabe: (x) => x.situacao === "saiu" },
  { id: "todas", rotulo: "Todos", cabe: () => true },
];
const FILTRO = Object.fromEntries(FILTROS.map((f) => [f.id, f]));
const NOME_EQUIPE = { ES: "Equipe ES", BA: "Equipe BA", EDIR: "Edir" };
const ORDEM_PADRAO = [{ campo: "dias", desc: true }]; // a ordem com que a lista abre (util.js: níveis)
const MIN_TEXTO = 10, MAX_TEXTO = 2000, MAX_LOTE = 500, MAX_RECUSADOS = 10;

const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;
// As datas vêm do servidor como AAAA-MM-DD (ou com a hora): o que não tiver esse formato vira um traço.
const DIA = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/;
const data = (iso) => { const m = DIA.exec(String(iso ?? "")); return m ? `${m[3]}/${m[2]}/${m[1]}` : "—"; };
const dataCurta = (iso) => { const m = DIA.exec(String(iso ?? "")); return m ? `${m[3]}/${m[2]}` : "—"; };
const dataHora = (iso) => { const m = DIA.exec(String(iso ?? "")); return m ? `${m[3]}/${m[2]}/${m[1]}${m[4] ? ` às ${m[4]}:${m[5]}` : ""}` : "—"; };
const semana = (iso) => { const m = DIA.exec(String(iso ?? "")); return m ? fmt.semana(`${m[1]}-${m[2]}-${m[3]}`) : ""; };
const maiuscula = (t) => (t ? String(t)[0].toUpperCase() + String(t).slice(1) : "");
const mesDe = (rotulo) => String(rotulo || "").split(" ")[0]; // "novembro de 2026" -> "novembro"
const semAcento = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

let ctx = null;
let filtroV = null;        // a lista suspensa dos vendedores
let ligadoUmaVez = false;
// rascunhos (id da sugestão -> { decisao, texto }) e lote (a resposta de vários de uma vez) sobrevivem a uma nova
// leitura dos dados e a montar a página de novo: o que a pessoa escreveu não se perde.
const estado = {
  dados: null, pedido: 0, mes: null, aba: "central", filtro: null, vendedores: [], busca: "",
  ordens: ORDEM_PADRAO, marcados: new Set(), aberto: null, rascunhos: {},
  lote: { decisao: null, texto: "" }, historico: {}, recusados: [], enviando: false,
  animar: true,  // os cartões e as linhas só entram animados na primeira vez de cada leitura pedida pela pessoa
};

export function montarManejo(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const salvo = ler("mv-manejo", {});
  estado.aba = LISTAS[q.get("aba")] ? q.get("aba") : LISTAS[salvo.aba] ? salvo.aba : "central";
  estado.mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : null;
  Object.assign(estado, { dados: null, marcados: new Set(), aberto: null, historico: {}, recusados: [], busca: "", vendedores: [] });

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="visoes" role="tablist" aria-label="Listas do manejo da base" id="mj-abas">
        <span class="indicador"></span>
        ${Object.entries(LISTAS).map(([id, l]) => `<button class="visao" role="tab" data-aba="${id}">${icone(l.icone)}${l.titulo}<span class="mj-n" data-n="${id}"></span></button>`).join("")}
      </div>
      <div class="filtros">
        <label class="campo" title="Lista de qual mês" id="mj-campo-mes" hidden><span class="ic-campo">${icone("calendario")}</span><select id="mj-mes" aria-label="Mês da lista"></select></label>
        <div id="mj-vendedores" hidden></div>
        <label class="campo sem-seta mj-busca" id="mj-campo-busca" hidden><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="mj-busca" placeholder="Buscar cliente" autocomplete="off" spellcheck="false" aria-label="Buscar cliente pelo nome, pela cidade ou pelo código"></label>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-manejo" title="Quem justifica, os dias de cada regra, o prazo e os vendedores da central">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="mj-avisos"></div>
    <div id="mj-conteudo"><div class="grade secao">
      <div class="kpis n4">${'<div class="esqueleto" style="height:150px"></div>'.repeat(4)}</div>
      <div class="esqueleto" style="height:420px"></div></div>
    </div>
    <div class="barra-salvar mj-lote" id="mj-lote" data-acompanha-tela-cheia role="region" aria-label="Responder os clientes marcados"></div>`;

  container.querySelectorAll("[data-aba]").forEach((b) => b.addEventListener("click", () => {
    if (estado.aba === b.dataset.aba) return;
    estado.aba = b.dataset.aba;
    estado.marcados = new Set();
    estado.aberto = null;
    guardar("mv-manejo", { aba: estado.aba });
    marcarAba();
    atualizarUrl();
    desenharDados();
  }));
  container.querySelector("#mj-mes").addEventListener("change", (e) => {
    estado.mes = e.target.value;
    estado.marcados = new Set();
    estado.aberto = null;
    estado.recusados = [];
    carregar();
  });
  filtroV = multiSelecao(container.querySelector("#mj-vendedores"), {
    rotulo: "Vendedores", icone: "usuario", todos: "Todos os vendedores", plural: "vendedores", busca: "Buscar vendedor",
    itens: [], selecionados: [], nomesAte: 2,
    aoAplicar: (lista) => { estado.vendedores = lista; desenharDados(); },
  });
  container.querySelector("#mj-busca").addEventListener("input", (e) => { estado.busca = e.target.value; desenharLista(); });
  const lote = container.querySelector("#mj-lote");
  lote.addEventListener("click", aoClicarLote);
  lote.addEventListener("input", (e) => { if (e.target.id === "mj-lote-texto") estado.lote.texto = e.target.value; });
  lote.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.id === "mj-lote-texto") { e.preventDefault(); enviarLote(); } });
  container.querySelector("#mj-conteudo").addEventListener("click", (e) => {
    const ir = e.target.closest("[data-ir-mes]");
    if (!ir) return;
    estado.mes = ir.dataset.irMes;
    estado.marcados = new Set();
    estado.aberto = null;
    estado.recusados = [];
    carregar();
  });
  if (!ligadoUmaVez) { // uma vez só, mesmo quando a página é montada de novo
    ligadoUmaVez = true;
    window.addEventListener("resize", posicionarIndicador);
  }
  marcarAba();
  carregar();
}

// Os dados mudaram (cópia nova do banco): lê de novo sem perder o que a pessoa escreveu nem o que marcou.
export function recarregarManejo() { if (ctx && !estado.enviando) carregar(true); }

function marcarAba() {
  document.querySelectorAll("#mj-abas [data-aba]").forEach((b) => {
    b.classList.toggle("ativa", b.dataset.aba === estado.aba);
    b.setAttribute("aria-selected", b.dataset.aba === estado.aba);
  });
  posicionarIndicador();
}

function posicionarIndicador() {
  const ativo = document.querySelector("#mj-abas .visao.ativa");
  const ind = document.querySelector("#mj-abas .indicador");
  if (!ativo || !ind) return;
  const primeira = !ind.style.width;
  if (primeira) ind.style.transition = "none";
  ind.style.transform = `translate(${ativo.offsetLeft}px, ${ativo.offsetTop}px)`;
  ind.style.width = ativo.offsetWidth + "px";
  ind.style.height = ativo.offsetHeight + "px";
  if (primeira) { void ind.offsetWidth; ind.style.transition = ""; }
}

function atualizarUrl() {
  if (!location.hash.startsWith("#/manejo")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams({ aba: estado.aba });
  if (estado.mes) p.set("m", estado.mes);
  history.replaceState(null, "", `#/manejo?${p}`);
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("mj-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  if (!silencioso) {
    if (estado.dados) conteudo.classList.add("recarregando");
    sairTelaCheia();
  }
  atualizarUrl();
  try {
    const d = await api(`/api/manejo${estado.mes ? `?mes=${encodeURIComponent(estado.mes)}` : ""}`);
    if (pedido !== estado.pedido) return;
    estado.animar = !silencioso;
    aplicar(d);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 400 && estado.mes) { // o mês guardado no endereço não vale mais
      estado.mes = null;
      if (!silencioso) toast(e.message, "erro");
      return carregar(silencioso);
    }
    if (silencioso && estado.dados) return; // fica com o que estava na tela; a próxima leitura tenta de novo
    estado.dados = null;
    mostrarFiltros(false);
    atualizarLote();
    const espera = e.status === 503; // os dados ainda não chegaram do computador da empresa (não é erro)
    const msg = espera ? maiuscula(e.message) : e.message;
    document.getElementById("mj-avisos").innerHTML = "";
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone(e.status === 403 ? "cadeado" : espera ? "relogio" : "alerta")}<p>${e.status === 403 || espera ? "" : "Não foi possível carregar: "}${esc(msg)}</p></div>`;
    if (!silencioso && e.status !== 403 && !espera) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
  }
}

// Uma resposta do servidor (a leitura ou o que volta depois de gravar): guarda e desenha.
function aplicar(d) {
  // os códigos entram em atributos da página: sempre números
  (d.itens || []).forEach((x) => {
    x.id = Number(x.id);
    x.cliente = { ...(x.cliente || {}), id: Number(x.cliente?.id) };
    x.vendedor = { ...(x.vendedor || {}), id: Number(x.vendedor?.id) };
    x.fatos = x.fatos || {};
  });
  (d.vendedores || []).forEach((v) => { v.id = Number(v.id); });
  estado.dados = d;
  Object.values(estado.historico).forEach((h) => { h.velho = true; }); // o histórico aberto é lido de novo
  if (d.rodada && estado.mes) estado.mes = d.rodada.mes;
  atualizarUrl();
  if (d.data_ref) ctx.subtitulo(d);
  desenhar();
}

// ---------- apoio ----------
const item = (id) => (estado.dados?.itens || []).find((x) => x.id === id);
const tipoDe = (x) => (x.pode?.veredito ? "veredito" : x.pode?.justificar ? "justificar" : null);
const podeAgir = (x) => tipoDe(x) !== null;

function itensDaAba(d, aba = estado.aba) {
  const vend = estado.vendedores.length ? new Set(estado.vendedores) : null;
  return (d.itens || []).filter((x) => x.sugestao === aba && (!vend || vend.has(x.vendedor.id)));
}

// O filtro da situação: o que a pessoa escolheu ou, sem escolha, o que ela tem para fazer (se houver algum).
function filtroAtivo(d, base) {
  const vale = (id) => FILTRO[id] && (!FILTRO[id].admin || d.admin);
  if (estado.filtro && vale(estado.filtro)) return estado.filtro;
  const padrao = d.admin ? "decidir" : d.pode_justificar ? "a_justificar" : "todas";
  return base.some(FILTRO[padrao].cabe) ? padrao : "todas";
}

function cabeNaBusca(x, termo) {
  if (!termo) return true;
  return semAcento(`${x.cliente.nome} ${x.cliente.cidade || ""} ${x.cliente.id} ${x.vendedor.nome}`).includes(termo);
}

// Mantém o cursor onde estava (o campo com data-foco) quando um pedaço da página é desenhado de novo.
function comFoco(desenho) {
  const a = document.activeElement;
  const chave = a && a.dataset ? a.dataset.foco : null;
  const pos = chave && typeof a.selectionStart === "number" ? [a.selectionStart, a.selectionEnd] : null;
  desenho();
  if (!chave) return;
  const novo = document.querySelector(`[data-foco="${CSS.escape(chave)}"]`);
  if (!novo || novo === document.activeElement) return;
  novo.focus({ preventScroll: true });
  if (pos) { try { novo.setSelectionRange(pos[0], pos[1]); } catch { /* campo sem seleção */ } }
}

function mostrarFiltros(sim) {
  ["mj-campo-mes", "mj-vendedores", "mj-campo-busca"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = !sim;
  });
  if (!sim) document.querySelectorAll("#mj-abas [data-n]").forEach((el) => { el.textContent = ""; });
}

function textoPrazo(n) {
  return { 1: "o último dia útil do mês", 2: "o penúltimo dia útil do mês", 3: "o antepenúltimo dia útil do mês" }[n]
    || `o ${n}º dia útil contando do fim do mês`;
}

// ---------- a página ----------
function desenhar() {
  const d = estado.dados, conteudo = document.getElementById("mj-conteudo");
  if (!conteudo || !d) return;
  const aberto = document.querySelector(".cartao.em-tela-cheia");
  if (aberto && aberto.id !== "mj-lista") sairTelaCheia(); // os cartões de cima são refeitos
  document.getElementById("mj-avisos").innerHTML = (d.avisos || [])
    .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");

  if (d.ativo === false) { // o computador da empresa: a página só avisa
    sairTelaCheia();
    mostrarFiltros(false);
    atualizarLote();
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone("info")}<p>${esc(d.aviso || "Esta página funciona no site.")}</p></div>`;
    return;
  }
  if (!d.rodada) { // ainda sem nenhuma lista
    sairTelaCheia();
    mostrarFiltros(false);
    atualizarLote();
    conteudo.innerHTML = semLista(d);
    return;
  }
  preencherFiltros(d);
  if (!document.getElementById("mj-lista")) montarEsqueleto(conteudo);
  const alvoMetodo = document.getElementById("mj-metodo");
  const metodoAberto = !!alvoMetodo.querySelector("details")?.open; // quem abriu a explicação continua com ela aberta
  alvoMetodo.innerHTML = metodo(d);
  if (metodoAberto) alvoMetodo.querySelector("details").open = true;
  desenharDados();
  estado.animar = false;
}

function semLista(d) {
  if (d.ligada === false) {
    return d.admin
      ? `<div class="cartao secao vazio">${icone("loja")}<p><b>A campanha ainda não foi ligada.</b><br>Em Configurar, marque quem pode justificar, confira os vendedores da central e ligue a campanha: a lista do mês nasce nesse momento.</p>
          <p><a class="btn primario" href="#/config-manejo">${icone("ajustes")}Abrir as configurações</a></p></div>`
      : `<div class="cartao secao vazio">${icone("loja")}<p>A campanha ainda não começou. Quando o administrador ligar, a lista do mês aparece aqui.</p></div>`;
  }
  return `<div class="cartao secao vazio">${icone("relogio")}<p>A lista deste mês ainda não foi montada: ela aparece na próxima atualização dos dados.</p></div>`;
}

// O cartão da lista fica no lugar e só o conteúdo dele é trocado: ele pode estar em tela cheia, e os cliques ficam nele.
function montarEsqueleto(conteudo) {
  conteudo.innerHTML = `
    <div id="mj-topo"></div>
    <section class="cartao secao mj-lista" id="mj-lista"><div id="mj-lista-corpo"></div></section>
    <div id="mj-metodo"></div>`;
  const card = conteudo.querySelector("#mj-lista");
  card.addEventListener("click", aoClicarLista);
  card.addEventListener("change", aoMarcar);
  card.addEventListener("input", aoDigitar);
  card.addEventListener("submit", aoEnviarForm);
}

function preencherFiltros(d) {
  mostrarFiltros(true);
  const mes = document.getElementById("mj-mes");
  mes.innerHTML = (d.rodadas || []).map((r) => `<option value="${esc(r.mes)}"${r.mes === d.rodada.mes ? " selected" : ""}>${esc(maiuscula(r.rotulo))}${r.aberta ? "" : " · encerrada"}</option>`).join("");
  document.getElementById("mj-campo-mes").hidden = (d.rodadas || []).length < 1;
  const equipes = [...new Set((d.vendedores || []).map((v) => v.equipe).filter(Boolean))].sort();
  const itens = (d.vendedores || []).map((v) => ({ id: v.id, nome: v.nome, grupo: equipes.length > 1 ? v.equipe : null }))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  filtroV.definir(itens, undefined, equipes.length > 1 ? equipes.map((e) => ({ id: e, nome: NOME_EQUIPE[e] || e })) : [{ id: null, nome: "" }]);
  estado.vendedores = filtroV.valor();
  document.getElementById("mj-vendedores").hidden = itens.length < 2;
}

// Os cartões de cima, os números das abas e a lista: tudo o que muda com a aba e com o filtro de vendedor.
function desenharDados() {
  const d = estado.dados, topo = document.getElementById("mj-topo");
  if (!d || !d.rodada || !topo) return;
  Object.keys(LISTAS).forEach((aba) => {
    const el = document.querySelector(`#mj-abas [data-n="${aba}"]`);
    if (el) el.textContent = fmt.num(itensDaAba(d, aba).length);
  });
  posicionarIndicador();
  topo.innerHTML = pendencias(d) + desligada(d) + cartoes(d);
  desenharLista();
  ligarTelaCheia(document.getElementById("mj-conteudo"));
}

function desligada(d) {
  return d.ligada === false
    ? `<div class="aviso">${icone("info")}<span>A campanha está desligada: a lista não recebe clientes novos nem é atualizada. O que já está nela continua aberto para justificar e decidir.</span></div>`
    : "";
}

// Meses diferentes do que está na tela que ainda têm cliente esperando o veredito ou a mudança no ERP.
function pendencias(d) {
  return (d.pendencias || []).map((p) => {
    const partes = [];
    if (p.sem_veredito) partes.push(`${plural(p.sem_veredito, "cliente", "clientes")} sem veredito`);
    if (p.aguardando_erp) partes.push(`${plural(p.aguardando_erp, "cliente", "clientes")} com veredito aguardando a mudança no ERP`);
    if (!partes.length) return "";
    return `<div class="aviso mj-pendencia">${icone("relogio")}<span>A lista de <b>${esc(p.rotulo || p.mes)}</b> ainda tem ${partes.join(" e ")}.</span>
      <button type="button" class="btn" data-ir-mes="${esc(p.mes)}">Ver a lista de ${esc(mesDe(p.rotulo) || p.mes)}</button></div>`;
  }).join("");
}

function kpi({ i, cor, ic, rotulo, valor, meta, rodape = [], dica = "" }) {
  return `
  <article class="cartao kpi kpi-simples${estado.animar ? " entra" : ""}" style="--i:${i};--cor:${cor}"${dica ? ` title="${esc(dica)}"` : ""}>
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${rotulo}</span></div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor">${valor}</div>
      <div class="kpi-meta">${meta}</div>
    </div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function cartoes(d) {
  const L = LISTAS[estado.aba], r = d.rodada, base = itensDaAba(d);
  const n = (f) => base.filter(f).length;
  const sit = (s) => n((x) => x.situacao === s);
  const justificadas = base.filter((x) => x.situacao === "justificada");
  const seguir = justificadas.filter((x) => x.justificativa?.decisao === "seguir").length;
  const comVeredito = n(FILTRO.veredito.cabe);
  let prazoValor, prazoMeta;
  if (!r.aberta) {
    prazoValor = "Encerrado";
    prazoMeta = `o prazo para justificar terminou ${semana(r.prazo)}, <b>${data(r.prazo)}</b>`;
  } else if (!r.dias_para_o_prazo) {
    prazoValor = "Hoje";
    prazoMeta = `é o <b>último dia para justificar</b>: vale até o fim do dia ${dataCurta(r.prazo)}`;
  } else {
    prazoValor = plural(r.dias_para_o_prazo, "dia", "dias");
    prazoMeta = `${r.dias_para_o_prazo === 1 ? "falta" : "faltam"} para o fim do prazo: ${semana(r.prazo)}, <b>${data(r.prazo)}</b>`;
  }
  return `<div class="grade secao"><div class="kpis n4 mj-kpis">
    ${kpi({
      i: 1, cor: "var(--s-fat)", ic: L.icone, rotulo: `Na lista de ${esc(mesDe(r.rotulo) || r.mes)}`, valor: fmt.num(base.length),
      meta: `${base.length === 1 ? "cliente sugerido" : "clientes sugeridos"} para <b>${estado.aba === "central" ? "a central" : "inativar"}</b>`,
      rodape: [["Com veredito", fmt.num(comVeredito)], ["Saíram da lista sozinhos", fmt.num(sit("saiu"))]],
      dica: "Todos os clientes que entraram nesta lista no mês, com os que já saíram dela",
    })}
    ${r.aberta ? kpi({
      i: 2, cor: "var(--atencao-forte)", ic: "relogio", rotulo: "A justificar", valor: fmt.num(sit("a_justificar")),
      meta: `esperando a resposta do supervisor até <b>${dataCurta(r.prazo)}</b>`,
      dica: "Clientes que ainda não têm a resposta do supervisor",
    }) : kpi({
      i: 2, cor: "var(--ruim-forte)", ic: "alerta", rotulo: "Sem justificativa", valor: fmt.num(sit("sem_justificativa")),
      meta: "o prazo passou sem resposta: vão ao veredito assim",
      dica: "Clientes que ficaram sem a resposta do supervisor até o prazo",
    })}
    ${kpi({
      i: 3, cor: "var(--k-cli)", ic: "visto", rotulo: "Justificados", valor: fmt.num(justificadas.length),
      meta: "com a resposta do supervisor, esperando o veredito",
      rodape: [[esc(L.curto.seguir), fmt.num(seguir)], [esc(L.curto.manter), fmt.num(justificadas.length - seguir)]],
    })}
    ${kpi({
      i: 4, cor: "var(--acento)", ic: "calendario", rotulo: "Prazo para justificar", valor: prazoValor, meta: prazoMeta,
      dica: "Depois do prazo o supervisor não responde mais; quem completar os dias depois dele entra na lista do mês seguinte",
    })}
  </div></div>`;
}

// ---------- a lista ----------
// texto: compara como texto (os nomes e as datas AAAA-MM-DD); asc: o primeiro clique ordena do menor para o maior.
function colunas() {
  const cols = [
    { id: "cliente", rotulo: "Cliente", esq: true, texto: true, asc: true, val: (x) => x.cliente.nome, cel: celCliente },
    { id: "vendedor", rotulo: "Vendedor", esq: true, texto: true, asc: true, val: (x) => x.vendedor.nome, cel: celVendedor },
  ];
  if (estado.aba === "inativar") {
    cols.push({ id: "motivo", rotulo: "Motivo", esq: true, val: (x) => x.fatos.inadimplencia?.dias ?? x.fatos.dias_sem_compra, cel: celMotivo });
  }
  cols.push(
    { id: "frequencia", rotulo: "Frequência", esq: true, asc: true, val: (x) => ORDEM_FREQ[x.fatos.frequencia] ?? 9, cel: celFrequencia },
    { id: "ultima", rotulo: "Última compra", texto: true, val: (x) => x.fatos.ultima_compra || "", cel: celUltima },
    { id: "dias", rotulo: "Dias sem compra", val: (x) => x.fatos.dias_sem_compra, cel: celDias },
    { id: "doze", rotulo: "Comprou em 12 meses", val: (x) => x.fatos.compras_12_meses?.valor ?? 0, cel: celDoze },
    { id: "situacao", rotulo: "Situação", esq: true, asc: true, val: (x) => ORDEM_SIT[x.situacao] ?? 9, cel: celSituacao },
    { id: "resposta", rotulo: "Resposta do supervisor", esq: true, texto: true, val: (x) => x.justificativa?.em || "", cel: celResposta },
    { id: "veredito", rotulo: "Veredito", esq: true, texto: true, val: (x) => x.veredito?.em || "", cel: celVeredito },
  );
  return cols;
}

// Pelos níveis da ordem (o último clique manda, os anteriores desempatam) e, no fim, pelo nome do cliente. Um nível de
// coluna que esta aba não tem (o Motivo fora da Inativar) é pulado, e volta a valer na aba que tem.
function ordenar(itens, cols) {
  return ordenarPorNiveis(itens, estado.ordens, (campo, a, b) => {
    const col = cols.find((c) => c.id === campo);
    if (!col) return 0;
    const x = col.val(a), y = col.val(b);
    return col.texto ? String(x ?? "").localeCompare(String(y ?? ""), "pt-BR") : (x ?? -Infinity) - (y ?? -Infinity);
  }, (a, b) => String(a.cliente.nome).localeCompare(String(b.cliente.nome), "pt-BR"));
}

// A coluna para a linha "Ordem: …" (o tipo diz como ler o sentido).
function colunaDaOrdem(cols, id) {
  const c = cols.find((x) => x.id === id);
  if (!c) return null;
  if (id === "frequencia") return { rotulo: c.rotulo, sentidos: ["semanal primeiro", "sem frequência primeiro"] };
  if (id === "situacao") return { rotulo: c.rotulo, sentidos: ["a justificar primeiro", "saíram primeiro"] };
  if (id === "ultima" || id === "resposta" || id === "veredito") return { rotulo: c.rotulo, tipo: "data" };
  return { rotulo: c.rotulo, tipo: c.texto ? "texto" : "numero" };
}

// O que aparece na tabela agora (aba, vendedores, situação e busca), já na ordem escolhida.
function visiveis(d) {
  const base = itensDaAba(d), filtro = filtroAtivo(d, base), termo = semAcento(estado.busca.trim());
  const cols = colunas();
  return { base, filtro, cols, itens: ordenar(base.filter(FILTRO[filtro].cabe).filter((x) => cabeNaBusca(x, termo)), cols) };
}

function desenharLista() {
  const d = estado.dados, corpo = document.getElementById("mj-lista-corpo");
  if (!d || !d.rodada || !corpo) return;
  const v = visiveis(d);
  const ids = new Set(v.itens.filter(podeAgir).map((x) => x.id));
  estado.marcados = new Set([...estado.marcados].filter((id) => ids.has(id))); // só fica marcado o que está à vista
  if (estado.aberto != null && !v.itens.some((x) => x.id === estado.aberto)) estado.aberto = null;
  const rolagem = corpo.querySelector(".tabela-rolagem");
  const pos = rolagem ? [rolagem.scrollTop, rolagem.scrollLeft] : null;
  comFoco(() => { corpo.innerHTML = lista(d, v); });
  const nova = corpo.querySelector(".tabela-rolagem");
  if (nova && pos) { nova.scrollTop = pos[0]; nova.scrollLeft = pos[1]; }
  atualizarMarcarTodos();
  atualizarLote();
  reajustarTelaCheia();
  if (estado.aberto != null) carregarHistorico(item(estado.aberto));
}

function lista(d, v) {
  const L = LISTAS[estado.aba], dias = (d.regras || {}).dias || {};
  const sub = estado.aba === "central"
    ? `Parou de comprar: ${fmt.num(dias.semanal)} dias ou mais para o cliente semanal${dias.quinzenal === dias.semanal ? ", o quinzenal" : ""} e o sem frequência no cadastro${dias.quinzenal === dias.semanal ? "" : `, ${fmt.num(dias.quinzenal)} para o quinzenal`}; ${fmt.num(dias.mensal)} para o mensal`
    : `Inadimplente há ${fmt.num(dias.inadimplencia)} dias ou mais, ou cliente da central há ${fmt.num(dias.central)} dias ou mais sem compra`;
  const chips = FILTROS.filter((f) => !f.admin || d.admin).map((f) => {
    const n = v.base.filter(f.cabe).length;
    return `<button type="button" class="mj-chip${f.id === v.filtro ? " ativo" : ""}${n ? "" : " zero"}" data-filtro="${f.id}" aria-pressed="${f.id === v.filtro}">${esc(f.rotulo)}<b>${fmt.num(n)}</b></button>`;
  }).join("");
  const podem = v.itens.filter(podeAgir).length;
  const niveis = estado.ordens.filter((n) => v.cols.some((c) => c.id === n.campo)); // o que vale nesta aba
  const th = (c) => {
    const m = marcaOrdem(niveis, c.id);
    return `<th class="${c.esq ? "esq" : ""}"${m.aria}><button type="button" class="mj-ordem${m.classe}" data-ordem="${c.id}"
      title="Ordenar por ${esc(c.rotulo.toLowerCase())}">${esc(c.rotulo)}<span class="mj-seta-o" aria-hidden="true">${m.seta}</span></button></th>`;
  };
  let corpo;
  if (!v.base.length) {
    corpo = `<div class="vazio">${icone(L.icone)}<p>Nenhum cliente nesta lista em ${esc(d.rodada.rotulo)}${estado.vendedores.length ? " com os vendedores escolhidos" : ""}.</p></div>`;
  } else if (!v.itens.length) {
    corpo = `<div class="vazio">${icone("busca")}<p>Nenhum cliente com este filtro.</p><p><button type="button" class="btn" data-ver-todos>Ver todos os ${fmt.num(v.base.length)}</button></p></div>`;
  } else {
    corpo = `
    ${linhaOrdem(niveis, ORDEM_PADRAO, (id) => colunaDaOrdem(v.cols, id))}
    <div class="tabela-rolagem mj-rolagem"><table class="dados mj-tabela${estado.animar ? " mj-entra" : ""}">
      <thead><tr>
        <th class="mj-sel">${podem ? `<label class="mj-marca" title="Marcar todos os que aparecem para responder de uma vez"><input type="checkbox" data-marcar-todos aria-label="Marcar todos os clientes que aparecem"><span class="marca-caixa">${icone("visto")}</span></label>` : ""}</th>
        ${v.cols.map(th).join("")}
      </tr></thead>
      <tbody>${v.itens.map((x, n) => linha(x, v.cols, n)).join("")}</tbody>
    </table></div>`;
  }
  const contagem = v.itens.length === v.base.length ? plural(v.base.length, "cliente", "clientes")
    : `${fmt.num(v.itens.length)} de ${plural(v.base.length, "cliente", "clientes")}`;
  return `
    <div class="cartao-cab mj-lista-cab">
      <div><h3>${icone(L.icone)}${esc(L.titulo)}</h3>
        <p class="sub">${esc(sub)} · ${contagem} · clique no cliente para ver o histórico${d.admin || d.pode_justificar ? " e responder" : ""}</p></div>
    </div>
    ${recusados()}
    <div class="mj-chips" role="group" aria-label="Filtrar pela situação">${chips}</div>
    ${corpo}`;
}

// O que o servidor não gravou no último envio (o cliente mudou de situação no meio-tempo), com o motivo de cada um.
function recusados() {
  const r = estado.recusados;
  if (!r.length) return "";
  const itens = r.slice(0, MAX_RECUSADOS).map((x) => `<li><b>${esc(x.cliente || "Cliente")}</b>: ${esc(x.motivo || "não foi gravado")}</li>`).join("");
  return `<div class="aviso mj-recusados">${icone("alerta")}<div><b>${r.length === 1 ? "1 cliente não foi gravado" : `${fmt.num(r.length)} clientes não foram gravados`}:</b>
    <ul>${itens}${r.length > MAX_RECUSADOS ? `<li>e mais ${fmt.num(r.length - MAX_RECUSADOS)}</li>` : ""}</ul></div>
    <button type="button" class="btn icone" data-fechar-recusados aria-label="Fechar este aviso" title="Fechar">${icone("x")}</button></div>`;
}

function linha(x, cols, n) {
  const aberta = estado.aberto === x.id, marcada = estado.marcados.has(x.id);
  const marca = podeAgir(x)
    ? `<label class="mj-marca" title="Marcar para responder vários de uma vez"><input type="checkbox" data-marcar="${x.id}"${marcada ? " checked" : ""} aria-label="Marcar ${esc(x.cliente.nome)}"><span class="marca-caixa">${icone("visto")}</span></label>`
    : "";
  return `<tr class="mj-linha${aberta ? " mj-aberta" : ""}${marcada ? " mj-marcada" : ""}" data-linha="${x.id}" style="--i:${Math.min(n, 20)}">
    <td class="mj-sel">${marca}</td>
    ${cols.map((c) => `<td class="${c.esq ? "esq " : ""}mj-c-${c.id}">${c.cel(x)}</td>`).join("")}
  </tr>${aberta ? detalhe(x, cols.length + 1) : ""}`;
}

function celCliente(x) {
  const c = x.cliente, f = x.fatos, aberta = estado.aberto === x.id;
  const onde = [c.cidade, c.uf].filter(Boolean).join("/");
  const tags = [];
  if (f.bloqueado_no_erp) tags.push(`<span class="mj-tag ruim" title="O cadastro do ERP está com este cliente bloqueado">${icone("cadeado")}bloqueado no ERP</span>`);
  if (x.anteriores) tags.push(`<span class="mj-tag" title="Este cliente já esteve em ${plural(x.anteriores, "outra lista", "outras listas")}: o histórico mostra o que foi respondido e decidido">${icone("caderneta")}${plural(x.anteriores, "lista anterior", "listas anteriores")}</span>`);
  return `<button type="button" class="mj-abrir" data-abrir="${x.id}" aria-expanded="${aberta}" title="${aberta ? "Fechar" : `Ver o histórico${podeAgir(x) ? " e responder" : ""}`}">
      <span class="mj-seta" aria-hidden="true">${icone("proximo")}</span><b>${esc(c.nome)}</b></button>
    <small>${esc(onde)}${onde ? " · " : ""}na lista desde ${dataCurta(x.entrou_em)}</small>${tags.length ? `<span class="mj-tags">${tags.join("")}</span>` : ""}`;
}

function celVendedor(x) {
  return `${esc(x.vendedor.nome)}${x.vendedor_entrada ? `<small title="O cliente trocou de vendedor depois de entrar na lista">entrou com ${esc(x.vendedor_entrada)}</small>` : ""}`;
}

const textoCentral = (f) => (f.na_central_desde ? `na central ${f.na_central_desde_antes ? "desde antes de" : "desde"} ${data(f.na_central_desde)}` : "na central");

function celMotivo(x) {
  const f = x.fatos, motivos = f.motivos || [], partes = [];
  if (motivos.includes("inadimplente") && f.inadimplencia) {
    const i = f.inadimplencia;
    partes.push(`<span class="mj-motivo"><b>Inadimplente há ${plural(i.dias, "dia", "dias")}</b><small>${fmt.moeda2(i.saldo)} em ${plural(i.titulos, "título", "títulos")} · o mais antigo venceu em ${data(i.vencimento_mais_antigo)}</small></span>`);
  }
  if (motivos.includes("central_sem_compra")) {
    partes.push(`<span class="mj-motivo"><b>Na central, ${plural(f.dias_sem_compra, "dia", "dias")} sem compra</b><small>${textoCentral(f)}</small></span>`);
  }
  if (motivos.includes("sem_compra")) {
    partes.push(`<span class="mj-motivo"><b>${plural(f.dias_sem_compra, "dia", "dias")} sem compra</b><small>também estaria na lista de passar para a central</small></span>`);
  }
  return partes.join("") || `<span class="fraco">—</span>`;
}

function celFrequencia(x) {
  const f = x.fatos;
  if (f.frequencia === "sem_frequencia") {
    return `<span title="Sem Semanal, Quinzenal ou Mensal no cadastro: conta como semanal">Sem frequência</span><small>${f.rede ? esc(f.rede) : "campo vazio no cadastro"} · conta como semanal</small>`;
  }
  return esc(FREQUENCIA[f.frequencia] || "—");
}

function celUltima(x) {
  const f = x.fatos;
  if (!f.ultima_compra) return `<span class="fraco">nunca comprou</span><small>conta do cadastro: ${data(f.conta_desde)}</small>`;
  if (f.origem_ultima_compra === "titulo") return `${data(f.ultima_compra)}<small>última compra antes de 2024</small>`;
  return data(f.ultima_compra);
}

function celDias(x) {
  const f = x.fatos;
  const origem = { reativacao: `desde a reativação, em ${dataCurta(f.conta_desde)}`, central: `desde que entrou na central`,
    cadastro: "desde o cadastro" }[f.origem_conta];
  return `<b class="mj-dias">${f.dias_sem_compra == null ? "—" : fmt.num(f.dias_sem_compra)}</b><small>${origem || (f.limite ? `limite: ${fmt.num(f.limite)}` : "")}</small>`;
}

function celDoze(x) {
  const c = x.fatos.compras_12_meses;
  if (!c || !(c.valor > 0)) return `<span class="fraco">sem compra</span>`;
  return `${fmt.moeda(c.valor)}<small>em ${plural(c.meses, "mês", "meses")}</small>`;
}

function celSituacao(x) {
  const s = SITUACOES[x.situacao] || SITUACOES.a_justificar, e = x.encerrada;
  let rotulo = s.rotulo, nota = "";
  if (x.situacao === "saiu" && e) { rotulo = `Saiu: ${MOTIVO_SAIDA[e.motivo] || "saiu da regra"}`; nota = `em ${dataCurta(e.em)}`; }
  if (x.situacao === "mantida") rotulo = LISTAS[x.sugestao].veredito.manter;
  if (x.situacao === "feita" && e) nota = `em ${dataCurta(e.em)}`;
  return `<span class="status mj-sit ${s.classe}">${icone(s.icone)}${esc(rotulo)}</span>${nota ? `<small>${nota}</small>` : ""}`;
}

function celResposta(x) {
  const j = x.justificativa;
  if (!j) {
    return `<span class="fraco">${x.situacao === "a_justificar" ? "aguardando" : x.situacao === "sem_justificativa" ? "não respondeu" : "—"}</span>`;
  }
  return `<span class="mj-resp ${j.decisao === "seguir" ? "seguir" : "manter"}">${icone(j.decisao === "seguir" ? "certo" : "bandeira")}${esc(LISTAS[x.sugestao].curto[j.decisao] || "")}</span>
    <small>${esc(j.por || "usuário excluído")} · ${dataCurta(j.em)}</small>${j.texto ? `<span class="mj-trecho" title="${esc(j.texto)}">${esc(j.texto)}</span>` : ""}`;
}

function celVeredito(x) {
  const v = x.veredito;
  if (!v) return `<span class="fraco">—</span>`;
  return `<span class="mj-resp ${v.decisao === "seguir" ? "seguir" : "manter"}">${icone(v.decisao === "seguir" ? "certo" : "menos")}${esc(LISTAS[x.sugestao].veredito[v.decisao] || "")}</span>
    <small>${esc(v.por || "usuário excluído")} · ${dataCurta(v.em)}</small>${v.texto ? `<span class="mj-trecho" title="${esc(v.texto)}">${esc(v.texto)}</span>` : ""}`;
}

// ---------- a linha aberta: o cliente hoje, o histórico e a resposta ----------
function detalhe(x, colspan) {
  return `<tr class="mj-detalhe" data-detalhe="${x.id}"><td colspan="${colspan}">
    <div class="mj-det">
      <section class="mj-bloco"><h4>${icone("loja")}O cliente hoje</h4>${fatos(x)}</section>
      <section class="mj-bloco"><h4>${icone("caderneta")}Histórico</h4><div id="mj-hist-${x.id}">${historico(x)}</div></section>
      <section class="mj-bloco mj-acao">${formulario(x)}</section>
    </div></td></tr>`;
}

function fatos(x) {
  const f = x.fatos, c = x.cliente, e = x.entrada || {}, l = [];
  const par = (a, b) => l.push(`<div><dt>${a}</dt><dd>${b}</dd></div>`);
  const entrou = [e.dias_sem_compra != null ? `com ${plural(e.dias_sem_compra, "dia", "dias")} sem compra` : "",
    e.dias_inadimplencia != null ? `com ${plural(e.dias_inadimplencia, "dia", "dias")} de atraso` : ""].filter(Boolean).join(" e ");
  par("Entrou na lista", `${data(x.entrou_em)}${entrou ? ` <small>${entrou}</small>` : ""}`);
  par("Vendedor", `${esc(x.vendedor.nome)}${x.vendedor_entrada ? ` <small>entrou na lista com ${esc(x.vendedor_entrada)}</small>` : ""}${
    f.com_vendedor_desde ? ` <small>com este vendedor ${f.com_vendedor_desde_antes ? "desde antes de" : "desde"} ${data(f.com_vendedor_desde)}</small>` : ""}`);
  if (f.na_central_desde) par("Na central", `${f.na_central_desde_antes ? "desde antes de" : "desde"} ${data(f.na_central_desde)}`);
  par("Frequência", f.frequencia === "sem_frequencia"
    ? `Sem frequência no cadastro <small>${f.rede ? `no campo Rede está “${esc(f.rede)}”` : "o campo Rede está vazio"}: conta como semanal</small>`
    : esc(FREQUENCIA[f.frequencia] || "—"));
  par("Última compra", !f.ultima_compra ? `nunca comprou <small>os dias contam do cadastro, em ${data(f.conta_desde)}</small>`
    : f.origem_ultima_compra === "titulo" ? `${data(f.ultima_compra)} <small>última compra antes de 2024, pelo título de venda</small>` : data(f.ultima_compra));
  const origem = { reativacao: `contados da reativação do cadastro, em ${data(f.conta_desde)}`, central: "contados da entrada na central",
    cadastro: "contados do cadastro", compra: "contados da última compra" }[f.origem_conta] || "";
  par("Dias sem compra", `<b>${f.dias_sem_compra == null ? "—" : fmt.num(f.dias_sem_compra)}</b> <small>${[origem, f.limite ? `o limite é ${fmt.num(f.limite)}` : ""].filter(Boolean).join(" · ")}</small>`);
  if (f.inadimplencia) {
    const i = f.inadimplencia;
    par("Inadimplência", `<b>${plural(i.dias, "dia", "dias")}</b> de atraso <small>${fmt.moeda2(i.saldo)} em aberto em ${plural(i.titulos, "título", "títulos")}${
      i.total > i.saldo + 0.005 ? ` (de ${fmt.moeda2(i.total)}, com uma parte já paga)` : ""} · o mais antigo venceu em ${data(i.vencimento_mais_antigo)}</small>`);
  }
  const doze = f.compras_12_meses;
  par("Comprou em 12 meses", doze && doze.valor > 0 ? `${fmt.moeda(doze.valor)} <small>em ${plural(doze.meses, "mês", "meses")}</small>` : "nada");
  const onde = [[c.cidade, c.uf].filter(Boolean).join("/"), c.area].filter(Boolean).join(" · ");
  if (onde) par("Onde fica", esc(onde));
  if (f.bloqueado_no_erp) par("Bloqueio", `<span class="mj-tag ruim">${icone("cadeado")}bloqueado no cadastro do ERP</span>`);
  return `<dl class="mj-fatos">${l.join("")}</dl>${f.dia ? `<p class="mj-nota">Números da cópia do banco de ${data(f.dia)}.</p>` : ""}`;
}

const textoEncerrada = (s) => {
  const e = s.encerrada;
  if (e.motivo === "aplicado") return `Feito no ERP: o cadastro mostrou a mudança em ${data(e.em)}.`;
  if (e.motivo === "mantido") return `Encerrada em ${data(e.em)}: ${LISTAS[s.sugestao]?.veredito.manter.toLowerCase() || "continua como está"}.`;
  return `Saiu da lista em ${data(e.em)}: ${MOTIVO_SAIDA[e.motivo] || "saiu da regra"}.`;
};

function evento(e, sugestao) {
  const veredito = e.tipo === "veredito", L = LISTAS[sugestao] || LISTAS.central;
  const numeros = [e.dias_sem_compra != null ? `${plural(e.dias_sem_compra, "dia", "dias")} sem compra no dia` : "",
    e.ultima_compra ? `última compra em ${data(e.ultima_compra)}` : ""].filter(Boolean).join(" · ");
  return `<li class="mj-ev ${veredito ? "veredito" : "justificativa"}">
    <span class="mj-ev-cab">${icone(veredito ? "bandeira" : "lapis")}<b>${veredito ? "Veredito" : "Resposta do supervisor"}: ${esc((veredito ? L.veredito : L.justificar)[e.decisao] || "")}</b></span>
    <small>${esc(e.por || "usuário excluído")} · ${dataHora(e.em)}${numeros ? ` · ${numeros}` : ""}</small>
    ${e.texto ? `<p>${esc(e.texto)}</p>` : ""}</li>`;
}

function historico(x) {
  const h = estado.historico[x.cliente.id];
  if (h?.dados) {
    const lista = h.dados.sugestoes || [];
    if (!lista.length) return `<p class="mj-nota">Nada registrado para este cliente.</p>`;
    return `<ol class="mj-hist">${lista.map((s) => {
      const e = s.entrada || {};
      const entrou = [e.dias_sem_compra != null ? `com ${plural(e.dias_sem_compra, "dia", "dias")} sem compra` : "",
        e.dias_inadimplencia != null ? `${plural(e.dias_inadimplencia, "dia", "dias")} de atraso` : ""].filter(Boolean).join(", ");
      return `<li class="mj-hist-mes${s.id === x.id ? " atual" : ""}">
        <div class="mj-hist-cab"><b>Lista de ${esc(s.rotulo || s.mes)}</b><span class="chip">${esc(LISTAS[s.sugestao]?.titulo || "")}</span>
          <small>entrou em ${data(s.entrou_em)}${entrou ? `, ${entrou}` : ""}${s.vendedor ? ` · ${esc(s.vendedor)}` : ""}</small></div>
        ${(s.eventos || []).length ? `<ul class="mj-evs">${s.eventos.map((ev) => evento(ev, s.sugestao)).join("")}</ul>`
          : `<p class="mj-nota">${s.encerrada ? "Sem resposta do supervisor nem veredito." : "Ainda sem resposta do supervisor nem veredito."}</p>`}
        ${s.encerrada ? `<p class="mj-hist-fim">${icone(s.encerrada.motivo === "aplicado" ? "certo" : "sair")}${esc(textoEncerrada(s))}</p>` : ""}
      </li>`;
    }).join("")}</ol>`;
  }
  // enquanto o histórico inteiro não chega, o que a linha já traz deste mês
  const agora = [x.justificativa ? evento({ ...x.justificativa, tipo: "justificativa" }, x.sugestao) : "",
    x.veredito ? evento({ ...x.veredito, tipo: "veredito" }, x.sugestao) : ""].join("");
  const estadoH = h?.erro ? `<p class="form-erro">${icone("alerta")}Não foi possível ler o histórico: ${esc(h.erro)}</p>`
    : `<p class="mj-nota">Lendo o histórico…</p>`;
  return `${agora ? `<ul class="mj-evs">${agora}</ul>` : ""}${estadoH}`;
}

async function carregarHistorico(x) {
  if (!x) return;
  const cid = x.cliente.id, h = estado.historico[cid];
  if (h && (h.carregando || (h.dados && !h.velho))) return;
  estado.historico[cid] = { ...(h || {}), carregando: true, erro: null };
  let novo;
  try {
    novo = { dados: await api(`/api/manejo/historico?cliente=${encodeURIComponent(cid)}`) };
  } catch (e) {
    novo = { dados: h?.dados || null, erro: h?.dados ? null : e.message };
  }
  estado.historico[cid] = novo;
  const aberto = estado.aberto != null ? item(estado.aberto) : null;
  const alvo = aberto && aberto.cliente.id === cid ? document.getElementById(`mj-hist-${aberto.id}`) : null;
  if (alvo) { alvo.innerHTML = historico(aberto); reajustarTelaCheia(); }
}

// O rascunho da resposta de uma linha: o que a pessoa já mexeu ou, sem nada, o que está gravado (para corrigir).
function rascunhoDe(x, tipo) {
  const r = estado.rascunhos[x.id];
  if (r) return r;
  const gravado = tipo === "veredito" ? x.veredito : x.justificativa;
  return { decisao: gravado?.decisao || null, texto: gravado?.texto || "" };
}

function dicaTexto(tipo, decisao) {
  if (tipo === "veredito") return "opcional";
  if (decisao === "manter") return `obrigatório: por que deve continuar (pelo menos ${MIN_TEXTO} letras)`;
  if (decisao === "seguir") return "opcional";
  return "escolha uma das respostas acima";
}

function porQueNao(x) {
  const d = estado.dados, prazo = d.rodada ? data(d.rodada.prazo) : "";
  if (x.situacao === "saiu") return "O cliente saiu da lista: não precisa mais de resposta nem de veredito.";
  if (x.situacao === "feita") return "O cadastro do ERP já mostra a mudança feita.";
  if (d.admin) {
    if (x.situacao === "a_justificar") return `O supervisor ainda pode justificar até ${prazo}. O veredito sai depois da resposta dele ou do prazo.`;
    return "Não há o que decidir nesta linha agora.";
  }
  if (!d.pode_justificar) return "O seu acesso é só de consulta nesta página.";
  if (x.veredito) return "Já tem veredito: a resposta do supervisor não muda mais.";
  if (d.rodada && !d.rodada.aberta) return `O prazo para justificar terminou em ${prazo}.`;
  return "Esta linha não pode ser respondida agora.";
}

function formulario(x) {
  const tipo = tipoDe(x), d = estado.dados;
  if (!tipo) return `<h4>${icone("info")}Resposta</h4><p class="mj-nota">${esc(porQueNao(x))}</p>`;
  const veredito = tipo === "veredito", L = LISTAS[x.sugestao][tipo], r = rascunhoDe(x, tipo);
  const gravado = veredito ? x.veredito : x.justificativa;
  const botao = veredito ? (gravado ? "Trocar o veredito" : "Dar o veredito") : (gravado ? "Corrigir a resposta" : "Gravar a resposta");
  const nota = veredito
    ? "O painel não muda o ERP: depois do veredito, faça a mudança no cadastro. A página marca como feito na cópia seguinte do banco."
    : `Dá para corrigir a resposta até o fim do dia ${dataCurta(d.rodada.prazo)}, enquanto não houver veredito.`;
  return `
    <form class="mj-form" data-form="${x.id}" novalidate>
      <h4>${icone(veredito ? "bandeira" : "lapis")}${veredito ? "Veredito" : "Sua resposta"}</h4>
      <div class="mj-escolha" role="radiogroup" aria-label="${veredito ? "Veredito" : "Resposta"} para ${esc(x.cliente.nome)}">
        ${["seguir", "manter"].map((dc) => `<button type="button" role="radio" class="mj-op${r.decisao === dc ? " ativo" : ""}" data-decisao="${dc}" aria-checked="${r.decisao === dc}">
          <span class="marca-caixa">${icone("visto")}</span><span>${esc(L[dc])}</span></button>`).join("")}
      </div>
      <label class="campo-form"><span>${veredito ? "Comentário" : "Motivo"} <small data-dica>${esc(dicaTexto(tipo, r.decisao))}</small></span>
        <textarea name="texto" rows="3" maxlength="${MAX_TEXTO}" data-foco="texto-${x.id}" placeholder="${veredito ? "Se quiser, escreva o porquê da decisão" : "Escreva o motivo"}">${esc(r.texto)}</textarea></label>
      <p class="form-erro" data-erro hidden></p>
      <div class="mj-form-acoes">
        <button class="btn primario" type="submit">${icone("certo")}${botao}</button>
        ${estado.rascunhos[x.id] ? `<button class="btn" type="button" data-descartar="${x.id}">Descartar</button>` : ""}
      </div>
      <small class="mj-nota">${esc(nota)}</small>
    </form>`;
}

function validar(tipo, decisao, texto) {
  if (decisao !== "seguir" && decisao !== "manter") return "Escolha uma das duas respostas.";
  const t = String(texto || "").trim();
  if (tipo === "justificar" && decisao === "manter" && t.length < MIN_TEXTO) return `Escreva o motivo para o cliente continuar (pelo menos ${MIN_TEXTO} letras).`;
  if (t.length > MAX_TEXTO) return `O texto passou de ${fmt.num(MAX_TEXTO)} letras.`;
  return null;
}

// ---------- cliques, marcações e digitação dentro do cartão da lista ----------
function aoClicarLista(e) {
  const t = e.target;
  const ordem = t.closest("[data-ordem]");
  if (ordem) {
    const campo = ordem.dataset.ordem, cols = colunas(), col = cols.find((c) => c.id === campo);
    estado.ordens = clicarOrdem(estado.ordens, campo, !col?.asc, (id) => cols.some((c) => c.id === id));
    desenharLista();
    return;
  }
  if (t.closest("[data-ordem-padrao]")) { estado.ordens = ORDEM_PADRAO; desenharLista(); return; }
  const chip = t.closest("[data-filtro]");
  if (chip) { estado.filtro = chip.dataset.filtro; desenharLista(); return; }
  if (t.closest("[data-ver-todos]")) {
    estado.filtro = "todas";
    estado.busca = "";
    const busca = document.getElementById("mj-busca");
    if (busca) busca.value = "";
    desenharLista();
    return;
  }
  if (t.closest("[data-fechar-recusados]")) { estado.recusados = []; desenharLista(); return; }
  const decisao = t.closest("[data-decisao]");
  if (decisao) { escolher(decisao); return; }
  const descartar = t.closest("[data-descartar]");
  if (descartar) { delete estado.rascunhos[Number(descartar.dataset.descartar)]; desenharLista(); return; }
  const abrir = t.closest("[data-abrir]");
  if (abrir) { alternar(Number(abrir.dataset.abrir)); return; }
  // o clique em qualquer outro ponto da linha também abre (menos nos campos e botões)
  const tr = t.closest("tr.mj-linha");
  if (tr && !t.closest("button, a, input, label, textarea, select")) alternar(Number(tr.dataset.linha));
}

function alternar(id) {
  estado.aberto = estado.aberto === id ? null : id;
  desenharLista();
  if (estado.aberto == null) return;
  const det = document.querySelector(`tr[data-detalhe="${id}"]`);
  if (det && det.getBoundingClientRect().bottom > window.innerHeight) det.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// A resposta escolhida numa linha aberta: guarda no rascunho e acerta os botões sem redesenhar (o texto não perde o cursor).
function escolher(botao) {
  const form = botao.closest("form[data-form]");
  if (!form) return;
  const x = item(Number(form.dataset.form));
  if (!x) return;
  const tipo = tipoDe(x), r = { ...rascunhoDe(x, tipo), decisao: botao.dataset.decisao };
  estado.rascunhos[x.id] = r;
  form.querySelectorAll("[data-decisao]").forEach((b) => {
    b.classList.toggle("ativo", b === botao);
    b.setAttribute("aria-checked", b === botao);
  });
  form.querySelector("[data-dica]").textContent = dicaTexto(tipo, r.decisao);
  form.querySelector("[data-erro]").hidden = true;
}

function aoDigitar(e) {
  const form = e.target.closest("form[data-form]");
  if (!form || e.target.name !== "texto") return;
  const x = item(Number(form.dataset.form));
  if (!x) return;
  estado.rascunhos[x.id] = { ...rascunhoDe(x, tipoDe(x)), texto: e.target.value };
  form.querySelector("[data-erro]").hidden = true;
}

function aoMarcar(e) {
  const t = e.target;
  if (t.matches("[data-marcar-todos]")) {
    const ids = visiveis(estado.dados).itens.filter(podeAgir).map((x) => x.id);
    estado.marcados = t.checked ? new Set(ids) : new Set();
    document.querySelectorAll("#mj-lista [data-marcar]").forEach((c) => {
      c.checked = estado.marcados.has(Number(c.dataset.marcar));
      c.closest("tr").classList.toggle("mj-marcada", c.checked);
    });
  } else if (t.matches("[data-marcar]")) {
    const id = Number(t.dataset.marcar);
    t.checked ? estado.marcados.add(id) : estado.marcados.delete(id);
    t.closest("tr").classList.toggle("mj-marcada", t.checked);
  } else return;
  atualizarMarcarTodos();
  atualizarLote();
}

function atualizarMarcarTodos() {
  const todos = document.querySelector("#mj-lista [data-marcar-todos]");
  if (!todos) return;
  const caixas = [...document.querySelectorAll("#mj-lista [data-marcar]")];
  const n = caixas.filter((c) => c.checked).length;
  todos.checked = n > 0 && n === caixas.length;
  todos.indeterminate = n > 0 && n < caixas.length;
}

function erroForm(form, msg) {
  const el = form?.querySelector("[data-erro]");
  if (el) { el.innerHTML = `${icone("alerta")}<span>${esc(msg)}</span>`; el.hidden = false; }
  else toast(msg, "erro");
}

function aoEnviarForm(e) {
  const form = e.target.closest("form[data-form]");
  if (!form) return;
  e.preventDefault();
  const x = item(Number(form.dataset.form));
  if (!x) return;
  const tipo = tipoDe(x);
  if (!tipo) return;
  const r = rascunhoDe(x, tipo), erro = validar(tipo, r.decisao, r.texto);
  if (erro) return erroForm(form, erro);
  enviar(tipo, [x], r.decisao, r.texto, form.querySelector("[type=submit]"), form);
}

// ---------- responder vários de uma vez (a barra de baixo) ----------
const marcadosDaAba = () => (estado.dados?.itens || []).filter((x) => x.sugestao === estado.aba && estado.marcados.has(x.id) && podeAgir(x));

function atualizarLote() {
  const barra = document.getElementById("mj-lote");
  if (!barra) return;
  const d = estado.dados, itens = d && d.rodada ? marcadosDaAba() : [];
  barra.classList.toggle("visivel", itens.length > 0);
  if (!itens.length) return;
  const tipo = d.admin ? "veredito" : "justificar", L = LISTAS[estado.aba][tipo], r = estado.lote;
  comFoco(() => {
    barra.innerHTML = `
      <span class="mj-lote-n"><b>${plural(itens.length, "cliente marcado", "clientes marcados")}</b>${itens.length > MAX_LOTE ? `<small>no máximo ${fmt.num(MAX_LOTE)} por vez</small>` : ""}</span>
      <div class="mj-lote-ops" role="radiogroup" aria-label="${tipo === "veredito" ? "Veredito" : "Resposta"} para os marcados">
        ${["seguir", "manter"].map((dc) => `<button type="button" role="radio" class="btn${r.decisao === dc ? " ativo" : ""}" data-lote-decisao="${dc}" aria-checked="${r.decisao === dc}">${esc(L[dc])}</button>`).join("")}
      </div>
      <input type="text" id="mj-lote-texto" data-foco="lote-texto" maxlength="${MAX_TEXTO}" value="${esc(r.texto)}"
        placeholder="${tipo === "veredito" ? "Comentário (opcional)" : r.decisao === "manter" ? "Motivo (obrigatório)" : "Motivo (obrigatório para continuar)"}"
        aria-label="${tipo === "veredito" ? "Comentário do veredito" : "Motivo da resposta"}">
      <button type="button" class="btn primario" id="mj-lote-enviar">${icone("certo")}${tipo === "veredito" ? "Dar o veredito" : "Responder"}</button>
      <button type="button" class="btn" id="mj-lote-limpar">Desmarcar</button>`;
  });
}

function aoClicarLote(e) {
  const dc = e.target.closest("[data-lote-decisao]");
  if (dc) {
    estado.lote.decisao = dc.dataset.loteDecisao;
    atualizarLote();
    return;
  }
  if (e.target.closest("#mj-lote-enviar")) { enviarLote(); return; }
  if (e.target.closest("#mj-lote-limpar")) {
    estado.marcados = new Set();
    document.querySelectorAll("#mj-lista [data-marcar]").forEach((c) => {
      c.checked = false;
      c.closest("tr").classList.remove("mj-marcada");
    });
    atualizarMarcarTodos();
    atualizarLote();
  }
}

function enviarLote() {
  const d = estado.dados, itens = marcadosDaAba();
  if (!d || !itens.length) return;
  const tipo = d.admin ? "veredito" : "justificar", r = estado.lote;
  if (itens.length > MAX_LOTE) return toast(`Marque no máximo ${fmt.num(MAX_LOTE)} clientes por vez.`, "erro");
  const erro = validar(tipo, r.decisao, r.texto);
  if (erro) {
    toast(erro, "erro");
    if (r.decisao) document.getElementById("mj-lote-texto")?.focus();
    return;
  }
  const L = LISTAS[estado.aba][tipo];
  if (itens.length > 1 && !confirm(`${tipo === "veredito" ? "Dar o veredito" : "Responder"} “${L[r.decisao]}” para os ${fmt.num(itens.length)} clientes marcados?`)) return;
  enviar(tipo, itens, r.decisao, r.texto, document.getElementById("mj-lote-enviar"), null, true);
}

// ---------- gravar ----------
async function enviar(tipo, itens, decisao, texto, botao, form, emLote = false) {
  const d = estado.dados;
  if (estado.enviando || !d?.rodada) return;
  estado.enviando = true;
  if (botao) botao.disabled = true;
  try {
    const r = await api(`/api/manejo/${tipo === "veredito" ? "veredito" : "justificar"}`, {
      json: { mes: d.rodada.mes, itens: itens.map((x) => ({ id: x.id, versao: x.versao })), decisao, texto: String(texto || "").trim() },
    });
    const fora = new Set((r.recusados || []).map((x) => x.id));
    itens.forEach((x) => {
      if (fora.has(x.id)) return;
      delete estado.rascunhos[x.id];
      estado.marcados.delete(x.id);
    });
    if (emLote) estado.lote = { decisao: null, texto: "" };
    estado.recusados = r.recusados || [];
    const n = r.gravados ?? itens.length - fora.size, m = estado.recusados.length;
    const gravou = tipo === "veredito" ? (n === 1 ? "1 veredito gravado" : `${fmt.num(n)} vereditos gravados`)
      : (n === 1 ? "1 resposta gravada" : `${fmt.num(n)} respostas gravadas`);
    if (m) toast(`${n ? `${gravou}. ` : ""}${m === 1 ? "1 cliente não foi gravado" : `${fmt.num(m)} clientes não foram gravados`}: o motivo está no topo da lista.`, "aviso");
    else toast(n === 1 ? (tipo === "veredito" ? "Veredito gravado" : "Resposta gravada") : gravou);
    if (Array.isArray(r.itens)) aplicar(r);  // a resposta já traz a lista do mês como ficou
    else await carregar(true);
  } catch (e) {
    if (form && form.isConnected) erroForm(form, maiuscula(e.message));
    toast(e.message, "erro");
    if (e.status === 403 || e.status === 404) carregar(true); // o acesso ou a lista mudou: mostra como está agora
  } finally {
    estado.enviando = false;
    if (botao && botao.isConnected) botao.disabled = false;
  }
}

// ---------- como é calculado ----------
function metodo(d) {
  const g = d.regras || {}, dias = g.dias || {}, central = g.central || [];
  const nomesCentral = central.length ? central.map((n) => esc(n)).join(", ") : "os vendedores marcados em Configurar";
  const prazo = g.prazo_dia_util ? textoPrazo(g.prazo_dia_util) : "o dia definido em Configurar";
  return `
  <section class="cartao secao metodo${estado.animar ? " entra" : ""}" style="--i:3">
    <details>
      <summary>
        <h3>${icone("info")}Como a lista é montada</h3>
        <span class="sub">Quem entra em cada lista, até quando dá para justificar e o que acontece depois do veredito</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Quem participa:</b> os clientes ativos dos vendedores das equipes do ES e da BA. Vendedores terceiros, a
            equipe do Edir, contas internas e os cadastros “PEDIDO BLOQUEADO” ficam de fora. Cada pessoa vê só os clientes
            dos vendedores do acesso dela.</li>
          <li><b>Passar para a central:</b> cliente semanal com ${fmt.num(dias.semanal)} dias ou mais sem compra, quinzenal com
            ${fmt.num(dias.quinzenal)} e mensal com ${fmt.num(dias.mensal)}. O cliente sem Semanal, Quinzenal ou Mensal no cadastro
            (com o nome de uma rede no campo Rede, ou com o campo vazio) conta como semanal. Quem já está com a central não entra aqui.</li>
          <li><b>Inativar:</b> cliente com título em aberto vencido há ${fmt.num(dias.inadimplencia)} dias ou mais; ou cliente
            da central (${nomesCentral}) há ${fmt.num(dias.central)} dias ou mais sem compra, contados do que for mais
            recente: o dia em que entrou na central ou a última compra.</li>
          <li><b>Dias sem compra:</b> da última venda faturada até o dia da cópia do banco${d.dia ? ` (${data(d.dia)})` : ""}.
            Quem não comprou desde janeiro de 2024 conta do último título de venda antigo; sem nenhum, do cadastro. O cliente
            reativado conta da reativação, e a troca de vendedor não recomeça a contagem.</li>
          <li><b>Uma lista por vez:</b> o cliente que está sem comprar e também é inadimplente aparece só na lista de
            inativação, com os dois motivos.</li>
          <li><b>A lista do mês:</b> o cliente entra assim que completa os dias, a cada chegada de dados. O prazo para
            justificar é ${esc(prazo)}, até o fim do dia. Depois dele a lista fecha, e quem completar os dias já entra na
            lista do mês seguinte.</li>
          <li><b>Resposta do supervisor:</b> quem está marcado para justificar diz se pode seguir a sugestão ou se o cliente
            deve continuar como está. O motivo é obrigatório quando é para continuar. Dá para corrigir até o prazo, enquanto
            não houver veredito; cada correção fica guardada. Passado o prazo, o cliente sem resposta vai ao veredito como
            “sem justificativa”.</li>
          <li><b>Veredito:</b> só o administrador dá, depois da resposta do supervisor ou do prazo. Pode ser trocado, e cada
            troca fica no histórico.</li>
          <li><b>Depois do veredito:</b> o painel não muda o ERP. Com “passar para a central” ou “inativar”, a linha fica
            “aguardando o ERP” até o cadastro mostrar a mudança, e então aparece como feita. Com “continua”, o cliente volta
            na lista do mês seguinte se ainda estiver na regra, com o histórico à vista.</li>
          <li><b>Saída sozinho:</b> antes do veredito, o cliente sai da lista quando volta a comprar, paga o que devia, já
            aparece com a central ou é inativado no ERP. A linha e as respostas ficam no histórico.</li>
          <li><b>Tabela:</b> clique no nome de uma coluna para ordenar (de novo, para inverter) e no cliente para abrir o
            histórico. As colunas clicadas antes continuam valendo para desempatar (até 3: o número ao lado da seta diz
            a vez de cada uma). As caixas marcam vários clientes para responder de uma vez.</li>
        </ol>
      </div>
    </details>
  </section>`;
}
