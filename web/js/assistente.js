// Página Assistente: chat em que a pessoa pergunta sobre os dados e a IA (Claude) responde consultando o cache.
// A conta é toda no servidor (bi/assistente.py): ele monta os dados do acesso da pessoa, chama a IA e devolve a
// resposta com as consultas feitas. As conversas ficam no servidor, como nos chats de IA: a lista ao lado mostra as
// da pessoa, cada uma tem o seu link (#/assistente?c=id) e abre em qualquer computador.
// A resposta da IA vira HTML só depois de escapada (nada do texto vira tag por conta própria).
// Campanhas: quando a IA monta um rascunho (propor_campanha), a resposta traz um card com "Criar campanha" (grava
// pela página Gestão) e "Revisar no painel"; nada é criado sem o clique. #/assistente?q=… abre uma conversa nova com
// a pergunta escrita (a página Gestão usa isso), sem enviar sozinho.
import { MESES, api, esc, fmt, icone, toast } from "./util.js";
import { descritorLegado, metaDigitada, periodoTexto, textoBase, textoFiltros, visual } from "./gestao.js";

const ESPERA_MAX = 170000; // ms; o servidor desiste antes (tempo_total do config.ini)
const CONFERIR_PENDENTE = 3000; // ms entre as conferências de uma pergunta feita em outra aba ou antes de recarregar
const SUGESTOES = [
  "Quanto vendemos este mês, por equipe?",
  "Quais os 10 clientes que mais compraram no mês passado?",
  "Como estão as metas do mês?",
  "Quais clientes compraram no mês passado e ainda não compraram este mês?",
  "Quais produtos tiveram mais devolução nos últimos 3 meses, e por quê?",
];
const FERRAMENTA = {
  buscar_cliente: { nome: "Busca de cliente", icone: "busca" },
  buscar_produto: { nome: "Busca de produto", icone: "busca" },
  buscar_vendedor: { nome: "Busca de vendedor", icone: "busca" },
  resumo_vendas: { nome: "Resumo de vendas", icone: "moeda" },
  metas_e_realizado: { nome: "Metas e realizado", icone: "alvo" },
  consultar_sql: { nome: "Consulta aos dados", icone: "banco" },
  listar_campanhas: { nome: "Campanhas", icone: "quadro" },
  andamento_campanha: { nome: "Andamento da campanha", icone: "quadro" },
  propor_campanha: { nome: "Rascunho de campanha", icone: "quadro" },
};

let ctx = null, raiz = null, info = null;
let atual = { ...nova(), carregando: true }; // conversa aberta; id null = nova, ainda não gravada
let conversas = [];     // lista ao lado: [{id, titulo, criada_em, atualizada_em}], mais recente antes
let esperando = null;   // {inicio, controle, conversa} enquanto a pergunta desta aba está no servidor
let pendente = null;    // {conversa, nova, pergunta, inicio}: pergunta que o servidor ainda responde, feita em outra
                        // aba ou antes de recarregar a página
let busca = "", pedidoLista = 0, abrindo = 0, acompanhando = false;

// mensagens: [{papel: "usuario"|"assistente", texto, consultas?, passos?, data_ref?, aviso?, uso?, rascunhos?}]
function nova() { return { id: null, titulo: "", mensagens: [] }; }
const linkDe = (id) => `#/assistente?c=${encodeURIComponent(id)}`;
const idDoHash = () => new URLSearchParams(location.hash.split("?")[1] || "").get("c");
const perguntaDoHash = () => new URLSearchParams(location.hash.split("?")[1] || "").get("q");

export async function montarAssistente(container, contexto) {
  ctx = contexto;
  raiz = container;
  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="proj-titulo"><span class="proj-icone">${icone("conversa")}</span>
        <div><b>Assistente de dados</b><small id="a-escopo">respostas com os dados do painel</small></div></div>
      <div class="filtros">
        <button class="btn btn-limpar btn-conversas" type="button" id="a-abrir-lista" aria-controls="a-lista" aria-expanded="false" hidden>${icone("menu")}Conversas</button>
        <button class="btn btn-limpar" type="button" id="a-nova">${icone("mais")}Nova conversa</button>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-assistente" title="Configurações do assistente: o que cada pessoa consulta e o uso">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="a-avisos"></div>
    <div class="assistente" id="a-grade">
      <aside class="cartao chat-lista entra" style="--i:1" id="a-lista" aria-label="Conversas" hidden>
        <div class="chat-lista-cab"><b>Conversas</b>
          <button type="button" class="chat-acao chat-lista-fechar" id="a-fechar-lista" aria-label="Fechar a lista de conversas">${icone("x")}</button></div>
        <label class="campo sem-seta chat-busca">${icone("busca", "ic-campo")}
          <input type="search" id="a-busca" placeholder="Buscar nas conversas" aria-label="Buscar nas conversas" autocomplete="off" maxlength="100"></label>
        <nav class="chat-itens" id="a-conversas"></nav>
      </aside>
      <section class="cartao chat entra" style="--i:1">
        <div class="chat-mensagens" id="a-msgs" aria-live="polite"></div>
        <form class="chat-entrada" id="a-form">
          <textarea id="a-texto" rows="1" maxlength="4000" placeholder="Faça uma pergunta sobre os dados…" aria-label="Sua pergunta"></textarea>
          <button class="btn primario" type="submit" id="a-enviar">${icone("enviar")}<span>Enviar</span></button>
        </form>
        <p class="chat-rodape" id="a-rodape">As respostas são geradas por IA com os dados do painel. Confira os números importantes em “Como cheguei nesse número”.</p>
      </section>
    </div>
    <div class="lateral-fundo chat-lista-fundo" id="a-fundo" hidden></div>`;
  const texto = container.querySelector("#a-texto");
  texto.addEventListener("input", () => ajustarAltura(texto));
  texto.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviar(); }
  });
  container.querySelector("#a-form").addEventListener("submit", (e) => { e.preventDefault(); enviar(); });
  container.querySelector("#a-nova").addEventListener("click", () => novaConversa());
  container.querySelector("#a-msgs").addEventListener("click", aoClicarRascunho);
  ligarLista();
  window.addEventListener("hashchange", aoMudarHash);
  setInterval(atualizarPensando, 1000);
  desenharMensagens();
  await carregarInfo();
}

async function carregarInfo() {
  const avisos = raiz.querySelector("#a-avisos");
  try {
    info = await api("/api/assistente/info");
  } catch (e) {
    atual = nova();
    desenharMensagens();
    avisos.innerHTML = `<div class="aviso">${icone("alerta")}<span>${esc(e.message)}</span></div>`;
    travar(true);
    return;
  }
  if (info.data_ref) ctx.subtitulo({ data_ref: info.data_ref });
  if (info.escopo) raiz.querySelector("#a-escopo").textContent = `consulta ${info.escopo}`;
  const msgs = [];
  if (!info.configurado) {
    msgs.push(ctx.admin
      ? "O assistente ainda não foi configurado: coloque a chave da API da Anthropic em [ia] no config.ini do servidor e reinicie o painel (veja o README)."
      : "O assistente ainda não foi configurado. Fale com o administrador.");
  } else if (!info.pronto) {
    msgs.push("Os dados por cliente ainda não chegaram do computador da empresa. O assistente funciona depois da próxima atualização dos dados.");
  }
  avisos.innerHTML = msgs.map((m) => `<div class="aviso">${icone("alerta")}<span>${esc(m)}</span></div>`).join("");
  mostrarRestantes(info.restantes);
  await iniciarHistorico();
  travar(!info.configurado || !info.pronto);
}

function travar(sim) {
  raiz.querySelector("#a-texto").disabled = sim;
  raiz.querySelector("#a-enviar").disabled = sim;
  raiz.querySelectorAll(".chat-sugestao").forEach((b) => { b.disabled = sim; });
}

function mostrarRestantes(n) {
  const el = raiz.querySelector("#a-rodape");
  const base = "As respostas são geradas por IA com os dados do painel. Confira os números importantes em “Como cheguei nesse número”.";
  el.textContent = n == null ? base : `${base} ${n === 1 ? "Resta 1 pergunta" : `Restam ${n} perguntas`} hoje.`;
}

function ajustarAltura(t) {
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 200) + "px";
  t.style.overflowY = t.scrollHeight > 200 ? "auto" : "hidden"; // barra de rolagem só quando passa da altura máxima
}

// ---------- histórico ----------
async function iniciarHistorico() {
  raiz.querySelector("#a-grade").classList.add("com-historico");
  raiz.querySelector("#a-lista").hidden = false;
  raiz.querySelector("#a-abrir-lista").hidden = false;
  raiz.querySelector("#a-conversas").innerHTML = '<div class="esqueleto chat-item-esqueleto"></div>'.repeat(4);
  await carregarLista();
  const q = perguntaDoHash();
  // Recarregou no meio da primeira pergunta de uma conversa: ela abre e mostra a resposta quando ficar pronta.
  await abrir(q ? null : idDoHash() || (pendente?.nova ? pendente.conversa : null));
  if (q) escreverPergunta(q);
}

// Pergunta pronta vinda de outra página (#/assistente?q=…): conversa nova, com o texto na caixa, sem enviar.
function escreverPergunta(q) {
  novaConversa({ substituir: true });
  const caixa = raiz.querySelector("#a-texto");
  caixa.value = q.slice(0, 4000);
  ajustarAltura(caixa);
  caixa.focus();
  caixa.setSelectionRange(caixa.value.length, caixa.value.length);
}

const urlLista = () => `/api/assistente/conversas${busca ? `?busca=${encodeURIComponent(busca)}` : ""}`;

async function carregarLista() {
  const vez = ++pedidoLista;
  try {
    const r = await api(urlLista());
    if (vez !== pedidoLista) return; // a busca mudou enquanto esta lista vinha
    conversas = r.conversas;
    if (r.pendente) marcarPendente(r.pendente);
    desenharLista();
  } catch (e) {
    if (vez === pedidoLista) {
      raiz.querySelector("#a-conversas").innerHTML = `<p class="chat-lista-vazio erro">${icone("alerta")}<span>${esc(e.message)}</span></p>`;
    }
  }
}

async function abrir(id) {
  const vez = ++abrindo;
  fecharLista();
  if (!id) {
    atual = nova();
  } else {
    atual = { ...nova(), id, titulo: conversas.find((c) => c.id === id)?.titulo || "", carregando: true };
    desenharMensagens();
    desenharLista();
    try {
      const r = await api(`/api/assistente/conversa?id=${encodeURIComponent(id)}`);
      if (vez !== abrindo) return; // abriu outra enquanto esta carregava
      atual = r.conversa || { ...nova(), id, titulo: tituloDe(r.pendente.pergunta) };
      if (r.pendente) marcarPendente(r.pendente);
      if (idDoHash() !== id) history.replaceState(null, "", linkDe(id));
    } catch (e) {
      if (vez !== abrindo) return;
      toast(e.message, "erro");
      atual = nova();
      history.replaceState(null, "", "#/assistente");
    }
  }
  desenharMensagens();
  desenharLista();
}

function aoMudarHash() {
  fecharLista();
  if (!/^#\/assistente(\?|$)/.test(location.hash)) return;
  const q = perguntaDoHash();
  if (q) return escreverPergunta(q);
  const id = idDoHash();
  if (id && id !== atual.id) abrir(id);
  else if (!id && atual.id) history.replaceState(null, "", linkDe(atual.id)); // voltou de outra página: segue na conversa
}

function novaConversa({ substituir = false } = {}) {
  if (atual.carregando && !info) return;
  ++abrindo;
  atual = nova();
  if (location.hash !== "#/assistente") history[substituir ? "replaceState" : "pushState"](null, "", "#/assistente");
  fecharLista();
  desenharMensagens();
  desenharLista();
  raiz.querySelector("#a-texto").focus();
}

// A conversa recebeu a primeira resposta (ganhou id) ou mais uma: sobe para o topo da lista.
function gravada(conversa, meta) {
  const eraNova = !conversa.id;
  conversa.id = meta.id;
  conversa.titulo = meta.titulo;
  conversas = [meta, ...conversas.filter((c) => c.id !== meta.id)];
  if (eraNova && conversa === atual) history.replaceState(null, "", linkDe(meta.id));
}

function marcarPendente(p) {
  if (esperando) return; // é a pergunta desta própria aba
  pendente = { ...p, inicio: Date.now() - (p.segundos || 0) * 1000 };
  acompanhar();
}

// Pergunta que o servidor ainda responde (feita em outra aba ou antes de recarregar): a lista e a conversa mostram
// "Consultando…" e a página confere de tempos em tempos até a resposta estar gravada.
async function acompanhar() {
  if (acompanhando) return;
  acompanhando = true;
  try {
    while (pendente) {
      await new Promise((r) => setTimeout(r, CONFERIR_PENDENTE));
      let r;
      try { r = await api(urlLista()); } catch { continue; }
      if (r.pendente?.conversa === pendente.conversa) continue;
      const feita = pendente;
      pendente = null;
      conversas = r.conversas;
      desenharLista();
      if (atual.id === feita.conversa) await recarregar(feita);
      if (r.pendente) marcarPendente(r.pendente); // outra pergunta já começou
    }
  } finally {
    acompanhando = false;
  }
}

async function recarregar(feita) {
  const antes = atual.mensagens.length;
  let conversa = null;
  try {
    conversa = (await api(`/api/assistente/conversa?id=${encodeURIComponent(feita.conversa)}`)).conversa;
  } catch { /* conversa nova que não chegou a ser gravada */ }
  if (atual.id !== feita.conversa) return;
  atual = conversa || nova();
  if (!conversa) history.replaceState(null, "", "#/assistente");
  desenharMensagens();
  desenharLista();
  if (!conversa || conversa.mensagens.length < antes + 2) {
    const caixa = raiz.querySelector("#a-texto");
    if (!caixa.value.trim()) { caixa.value = feita.pergunta; ajustarAltura(caixa); }
    desenharErro("A pergunta anterior não chegou a ser respondida.");
  }
}

async function excluir(id) {
  const c = conversas.find((x) => x.id === id);
  if (!c) return;
  if (esperando?.conversa.id === id || pendente?.conversa === id) {
    return toast("Espere a resposta antes de excluir esta conversa", "erro");
  }
  if (!confirm(`Excluir a conversa “${c.titulo}”? Não dá para desfazer.`)) return;
  try {
    await api("/api/assistente/conversa/excluir", { json: { id } });
  } catch (e) {
    return toast(e.message, "erro");
  }
  conversas = conversas.filter((x) => x.id !== id);
  toast("Conversa excluída");
  if (atual.id === id) novaConversa({ substituir: true });
  else desenharLista();
}

// Renomear no próprio item: Enter (ou sair do campo) salva, Esc desiste.
function editarTitulo(item) {
  const id = item.dataset.id;
  const c = conversas.find((x) => x.id === id);
  if (!c) return;
  item.classList.add("editando");
  item.innerHTML = `<input class="chat-item-campo" maxlength="80" value="${esc(c.titulo)}" aria-label="Nome da conversa">`;
  const campo = item.querySelector("input");
  campo.focus();
  campo.select();
  let feito = false;
  const terminar = async (salvar) => {
    if (feito) return;
    feito = true;
    const titulo = campo.value.trim();
    if (salvar && titulo && titulo !== c.titulo) {
      try {
        const r = await api("/api/assistente/conversa/renomear", { json: { id, titulo } });
        c.titulo = r.conversa.titulo;
        if (atual.id === id) atual.titulo = c.titulo;
      } catch (e) {
        toast(e.message, "erro");
      }
    }
    desenharLista();
  };
  campo.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); terminar(true); }
    if (e.key === "Escape") { e.stopPropagation(); terminar(false); }
  });
  campo.addEventListener("blur", () => terminar(true));
}

// Lista ao lado; no celular, uma gaveta que abre pelo botão Conversas e fecha ao escolher, tocar fora ou com Esc.
function ligarLista() {
  const lista = raiz.querySelector("#a-conversas");
  lista.addEventListener("click", (e) => {
    const item = e.target.closest(".chat-item[data-id]");
    if (!item || item.classList.contains("editando")) return;
    if (e.target.closest("[data-renomear]")) return editarTitulo(item);
    if (e.target.closest("[data-excluir]")) return excluir(item.dataset.id);
    if (e.target.closest(".chat-item-link")) fecharLista(); // o link troca o endereço e a conversa abre
  });
  let relogio = null;
  raiz.querySelector("#a-busca").addEventListener("input", (e) => {
    clearTimeout(relogio);
    relogio = setTimeout(() => { busca = e.target.value.trim(); carregarLista(); }, 250);
  });
  const botao = raiz.querySelector("#a-abrir-lista");
  botao.addEventListener("click", () => {
    raiz.querySelector("#a-lista").classList.add("aberta");
    raiz.querySelector("#a-fundo").hidden = false;
    botao.setAttribute("aria-expanded", "true");
    document.body.classList.add("chat-gaveta");
    (raiz.querySelector(".chat-item.selecionado .chat-item-link") || raiz.querySelector(".chat-item-link"))?.focus();
  });
  raiz.querySelector("#a-fechar-lista").addEventListener("click", () => { fecharLista(); botao.focus(); });
  raiz.querySelector("#a-fundo").addEventListener("click", fecharLista);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && raiz.querySelector("#a-lista").classList.contains("aberta")) { fecharLista(); botao.focus(); }
  });
  window.matchMedia("(max-width: 860px)").addEventListener("change", fecharLista);
}

function fecharLista() {
  const lista = raiz?.querySelector("#a-lista");
  if (!lista?.classList.contains("aberta")) return;
  lista.classList.remove("aberta");
  raiz.querySelector("#a-fundo").hidden = true;
  raiz.querySelector("#a-abrir-lista").setAttribute("aria-expanded", "false");
  document.body.classList.remove("chat-gaveta");
}

function desenharLista() {
  const el = raiz.querySelector("#a-conversas");
  const itens = [...conversas];
  // Conversa nova com a primeira pergunta ainda no servidor: aparece no topo antes de ser gravada.
  if (pendente?.nova && !conversas.some((c) => c.id === pendente.conversa)) {
    itens.unshift({ id: pendente.conversa, titulo: tituloDe(pendente.pergunta), provisoria: true });
  }
  if (esperando && !esperando.conversa.id) {
    itens.unshift({ id: null, titulo: tituloDe(esperando.conversa.mensagens[0]?.texto), provisoria: true,
      aberta: esperando.conversa === atual });
  }
  if (!itens.length) {
    el.innerHTML = `<p class="chat-lista-vazio">${busca ? "Nenhuma conversa encontrada." : "Suas conversas aparecem aqui depois da primeira pergunta."}</p>`;
    return;
  }
  let grupo = null;
  el.innerHTML = itens.map((c) => {
    const g = c.provisoria ? "Hoje" : grupoDe(c.atualizada_em);
    const titulo = g !== grupo ? `<h3 class="chat-grupo">${esc(g)}</h3>` : "";
    grupo = g;
    return titulo + itemConversa(c);
  }).join("");
}

function itemConversa(c) {
  const aberta = c.id ? c.id === atual.id : c.aberta;
  const respondendo = c.provisoria || pendente?.conversa === c.id || (esperando && esperando.conversa.id === c.id);
  const sinal = respondendo ? '<span class="chat-item-sinal" title="Respondendo…"></span>' : "";
  const classe = `chat-item${aberta ? " selecionado" : ""}`;
  if (!c.id) return `<div class="${classe}"><span class="chat-item-link">${sinal}<span class="t">${esc(c.titulo)}</span></span></div>`;
  const acoes = c.provisoria ? "" : `
    <button type="button" class="chat-item-acao" data-renomear title="Renomear" aria-label="Renomear a conversa “${esc(c.titulo)}”">${icone("lapis")}</button>
    <button type="button" class="chat-item-acao" data-excluir title="Excluir" aria-label="Excluir a conversa “${esc(c.titulo)}”">${icone("lixeira")}</button>`;
  return `<div class="${classe}" data-id="${esc(c.id)}">
    <a class="chat-item-link" href="${linkDe(c.id)}" title="${esc(c.titulo)}"${aberta ? ' aria-current="page"' : ""}>${sinal}<span class="t">${esc(c.titulo)}</span></a>${acoes}
  </div>`;
}

// Hoje, Ontem, Últimos 7 dias, Últimos 30 dias e, antes disso, o mês.
function grupoDe(iso) {
  const d = new Date(iso);
  const dia = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate());
  const dias = Math.round((dia(new Date()) - dia(d)) / 864e5);
  if (dias <= 0) return "Hoje";
  if (dias === 1) return "Ontem";
  if (dias < 7) return "Últimos 7 dias";
  if (dias < 30) return "Últimos 30 dias";
  const mes = MESES[d.getMonth()].replace(/^./, (l) => l.toUpperCase());
  return d.getFullYear() === new Date().getFullYear() ? mes : `${mes} de ${d.getFullYear()}`;
}

// Igual ao título que o servidor dá: a primeira linha da pergunta, cortada no fim de uma palavra.
function tituloDe(pergunta) {
  const linha = (String(pergunta || "").split("\n").find((l) => l.trim()) || "").trim().replace(/\s+/g, " ");
  if (linha.length <= 60) return linha || "Nova conversa";
  return linha.slice(0, 61).replace(/\s+\S*$/, "").replace(/[\s,.;:-]+$/, "") + "…";
}

// ---------- envio ----------
async function enviar(textoPronto) {
  const caixa = raiz.querySelector("#a-texto");
  const texto = (textoPronto ?? caixa.value).trim();
  if (!texto || caixa.disabled || atual.carregando) return;
  if (esperando || pendente) return toast("Espere a resposta da pergunta anterior", "erro");
  caixa.value = "";
  ajustarAltura(caixa);
  const conversa = atual; // a resposta vale para esta conversa, mesmo se a pessoa abrir outra enquanto espera
  conversa.mensagens.push({ papel: "usuario", texto });
  const controle = new AbortController();
  const limite = setTimeout(() => controle.abort(), ESPERA_MAX);
  esperando = { inicio: Date.now(), controle, conversa };
  desenharMensagens();
  desenharLista();
  try {
    // O servidor lê a conversa do banco: vai só a pergunta.
    const r = await api("/api/assistente", { json: { conversa: conversa.id, pergunta: texto }, signal: controle.signal });
    conversa.mensagens.push({ papel: "assistente", texto: r.resposta, consultas: r.consultas, passos: r.passos,
      data_ref: r.data_ref, aviso: r.aviso, uso: r.uso, rascunhos: r.rascunhos });
    if (r.conversa) gravada(conversa, r.conversa);
    if (r.restantes !== undefined) mostrarRestantes(r.restantes);
    pararEspera(limite);
    if (conversa === atual) desenharMensagens();
    desenharLista();
  } catch (e) {
    // A pergunta não foi respondida: sai da conversa e volta para a caixa, para tentar de novo.
    conversa.mensagens.pop();
    pararEspera(limite);
    const msg = e.name === "AbortError" ? "A resposta demorou demais. Tente uma pergunta mais simples ou mais específica." : e.message;
    if (conversa === atual) {
      desenharMensagens();
      caixa.value = texto;
      ajustarAltura(caixa);
      desenharErro(msg);
    } else {
      toast(msg, "erro");
    }
    desenharLista();
    carregarLista(); // se o tempo acabou só aqui, a pergunta pode seguir no servidor
  }
}

function pararEspera(limite) {
  clearTimeout(limite);
  esperando = null;
}

function inicioDaEspera() {
  if (esperando) return esperando.conversa === atual ? esperando.inicio : null;
  return pendente && pendente.conversa === atual.id ? pendente.inicio : null;
}

function atualizarPensando() {
  const el = raiz?.querySelector("#a-pensando-s");
  const inicio = inicioDaEspera();
  if (el && inicio) el.textContent = `${Math.round((Date.now() - inicio) / 1000)} s`;
}

// ---------- desenho ----------
function desenharMensagens() {
  const el = raiz.querySelector("#a-msgs");
  if (atual.carregando) {
    el.innerHTML = '<div class="chat-carregando"><div class="esqueleto"></div><div class="esqueleto"></div><div class="esqueleto"></div></div>';
    return;
  }
  const inicio = inicioDaEspera();
  // pergunta feita em outra aba (ou antes de recarregar): ainda não está nas mensagens da conversa
  const deFora = inicio && !esperando ? balaoUsuario({ texto: pendente.pergunta }) : "";
  if (!atual.mensagens.length && !inicio) {
    el.innerHTML = `
      <div class="chat-inicio">
        <span class="chat-avatar grande">${icone("conversa")}</span>
        <h2>Pergunte sobre os dados</h2>
        <p>Vendas, devoluções, clientes, produtos e metas, com os mesmos números das outras páginas.
          Cite clientes e produtos pelo nome: o assistente procura no cadastro.</p>
        <div class="chat-sugestoes">${SUGESTOES.map((s) => `<button type="button" class="chat-sugestao">${esc(s)}</button>`).join("")}</div>
      </div>`;
    el.querySelectorAll(".chat-sugestao").forEach((b) => b.addEventListener("click", () => enviar(b.textContent)));
    if (info) travar(!info.configurado || !info.pronto);
    return;
  }
  el.innerHTML = atual.mensagens.map((m, i) => (m.papel === "usuario" ? balaoUsuario(m) : balaoIA(m, i))).join("") + deFora +
    (inicio ? `<div class="chat-msg ia"><span class="chat-avatar">${icone("conversa")}</span>
      <div class="chat-corpo"><div class="chat-balao"><span class="chat-pensando">
        <span class="chat-pontos"><i></i><i></i><i></i></span>Consultando os dados… <span id="a-pensando-s">${Math.round((Date.now() - inicio) / 1000)} s</span>
      </span></div></div></div>` : "");
  el.querySelectorAll("[data-copiar]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(atual.mensagens[Number(b.dataset.copiar)].texto);
      toast("Resposta copiada");
    } catch { toast("Não foi possível copiar", "erro"); }
  }));
  const ultima = el.lastElementChild;
  if (ultima) requestAnimationFrame(() => ultima.scrollIntoView({ block: "nearest", behavior: "smooth" }));
}

function desenharErro(msg) {
  const el = raiz.querySelector("#a-msgs");
  el.insertAdjacentHTML("beforeend", `<div class="chat-msg ia"><span class="chat-avatar">${icone("alerta")}</span>
    <div class="chat-corpo"><div class="chat-balao erro">${esc(msg)}</div>
    <div class="chat-meta"><span>A pergunta voltou para a caixa de texto: ajuste se quiser e envie de novo.</span></div></div></div>`);
  el.lastElementChild.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function balaoUsuario(m) {
  return `<div class="chat-msg usuario"><div class="chat-balao">${esc(m.texto)}</div></div>`;
}

function balaoIA(m, i) {
  const passos = m.passos || [];
  const meta = [
    m.data_ref ? `dados até ${fmt.dataCurta(m.data_ref)}` : "",
    m.uso?.segundos != null ? `${fmt.num(m.uso.segundos, 0)} s` : "",
    m.uso?.custo != null ? `≈ US$ ${fmt.num(m.uso.custo, 3)} · ${fmt.num(m.uso.entrada + m.uso.cache_leitura + m.uso.cache_escrita)} tokens de entrada (${fmt.num(m.uso.cache_leitura)} do cache), ${fmt.num(m.uso.saida)} de saída` : "",
  ].filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("");
  return `<div class="chat-msg ia"><span class="chat-avatar">${icone("conversa")}</span>
    <div class="chat-corpo">
      <div class="chat-balao chat-texto">${markdown(m.texto)}</div>
      ${(m.rascunhos || []).map((r, j) => cartaoRascunho(r, i, j)).join("")}
      ${m.aviso ? `<p class="chat-aviso">${icone("alerta")}${esc(m.aviso)}</p>` : ""}
      <div class="chat-meta">${meta}<button type="button" class="chat-acao" data-copiar="${i}">${icone("copiar")}Copiar</button></div>
      ${passos.length ? desenharPassos(passos) : ""}
    </div></div>`;
}

// ---------- rascunho de campanha ----------
function cartaoRascunho(r, i, j) {
  const ind = r.indicador || descritorLegado(r); // rascunho de antes dos tipos novos
  const m = visual(ind);
  const nomes = r.nomes?.vendedores || {};
  const vend = (r.vendedores || []).map((v) => nomes[v.id] || `Vendedor ${v.id}`);
  const ajustes = (r.vendedores || []).filter((v) => v.meta != null).length;
  const precos = r.metas_produto || [];
  const meta = ind.tipo === "preco_medio"
    ? `preço-alvo de ${precos.length} produto${precos.length === 1 ? "" : "s"}: ${precos.slice(0, 3).map((p) => `${r.nomes?.produtos?.[p.id] || p.id} a R$ ${fmt.num(p.meta, 2)}`).join(", ")}${precos.length > 3 ? "…" : ""}`
    : r.meta_padrao ? `${metaDigitada(ind, r.meta_padrao, r.unidade)} por vendedor` : "sem meta (só ranking)";
  const filtros = [...textoFiltros(r.filtros || {}, r.nomes?.produtos), ...textoBase(ind)];
  const linhas = [
    ["calendario", "Período", periodoTexto(r.inicio, r.fim)],
    [m.icone, "Mede", ind.nome + (r.unidade && ind.medida === "volume" ? ` (${r.unidade.toLowerCase()})` : "")],
    ["alvo", "Meta", meta + (ajustes ? ` · ${ajustes} ajustada${ajustes === 1 ? "" : "s"}` : "")],
    ["pessoas", `${vend.length} vendedor${vend.length === 1 ? "" : "es"}`, vend.length <= 6 ? vend.join(", ") : `${vend.slice(0, 5).join(", ")} e mais ${vend.length - 5}`],
    ["funil", "Conta", filtros.length ? filtros.join(" · ") : "todos os produtos e clientes"],
    ...(r.premiacao ? [["trofeu", "Prêmio", r.premiacao]] : []),
  ];
  let acoes;
  if (r.campanha) {
    acoes = `<span class="chip camp-criada">${icone("certo")}Criada</span>
      <a class="btn" href="#/gestao?c=${r.campanha.id}">${icone("quadro")}Abrir no painel</a>`;
  } else if (info?.gestao) {
    acoes = `<button class="btn primario" type="button" data-criar="${i}:${j}">${icone("mais")}Criar campanha</button>
      <a class="btn" href="#/gestao?rascunho=${encodeURIComponent(r.id)}">${icone("lapis")}Revisar no painel</a>`;
  } else {
    acoes = `<span class="fraco">Para criar, peça ao administrador acesso à página Gestão.</span>`;
  }
  return `<div class="camp-rascunho" style="--c:${m.cor}">
    <div class="camp-rascunho-cab">${icone("quadro")}<span>${r.campanha ? "Campanha criada" : "Rascunho de campanha · ainda não criada"}</span></div>
    <h4>${esc(r.nome)}</h4>
    <dl>${linhas.map(([ic, rot, val]) => `<div>${icone(ic)}<dt>${esc(rot)}</dt><dd>${esc(val)}</dd></div>`).join("")}</dl>
    ${r.descricao ? `<p class="fraco">${esc(r.descricao)}</p>` : ""}
    <div class="camp-rascunho-acoes">${acoes}</div>
  </div>`;
}

async function aoClicarRascunho(e) {
  const b = e.target.closest("[data-criar]");
  if (!b) return;
  const [i, j] = b.dataset.criar.split(":").map(Number);
  const conversa = atual;
  const r = conversa.mensagens[i]?.rascunhos?.[j];
  if (!r || r.campanha) return;
  b.disabled = true;
  try {
    const campanha = { nome: r.nome, descricao: r.descricao, premiacao: r.premiacao, inicio: r.inicio, fim: r.fim,
      metrica: r.metrica, parametros: r.parametros || {}, filtros: r.filtros, meta_padrao: r.meta_padrao,
      vendedores: r.vendedores, metas_produto: r.metas_produto || [] };
    const res = await api("/api/gestao/campanhas", { json: { campanha, rascunho: r.id } });
    r.campanha = { id: res.campanha.id, nome: res.campanha.nome };
    toast(res.ja_existia ? "Esta campanha já tinha sido criada" : `Campanha “${res.campanha.nome}” criada`);
    if (conversa === atual) desenharMensagens();
  } catch (err) {
    b.disabled = false;
    toast(err.message, "erro");
  }
}

function desenharPassos(passos) {
  return `<details class="chat-passos"><summary>${icone("banco")}Como cheguei nesse número
      <span class="fraco">${passos.length} consulta${passos.length === 1 ? "" : "s"}</span></summary>
    ${passos.map((p) => {
      const f = FERRAMENTA[p.ferramenta] || { nome: p.ferramenta, icone: "banco" };
      const linhas = p.erro ? `<b>erro:</b> ${esc(p.erro)}` : `${fmt.num(p.linhas)} linha${p.linhas === 1 ? "" : "s"} · ${fmt.num(p.ms)} ms`;
      return `<div class="chat-passo ${p.erro ? "erro" : ""}">
        <div class="t">${icone(f.icone)}<b>${esc(f.nome)}</b><span>${esc(descricao(p))}</span><small>${linhas}</small></div>
        ${p.sql ? `<pre>${esc(p.sql)}</pre>` : ""}
        ${p.colunas?.length && p.amostra?.length ? amostra(p) : ""}
      </div>`;
    }).join("")}
  </details>`;
}

function descricao(p) {
  const a = p.args || {};
  if (p.ferramenta.startsWith("buscar_")) return `“${a.texto || ""}”`;
  if (p.ferramenta === "resumo_vendas") {
    const partes = [`${a.de ? fmt.data(a.de) : "?"} a ${a.ate ? fmt.data(a.ate) : "?"}`];
    if (a.agrupar_por?.length) partes.push(`por ${a.agrupar_por.join(" e ")}`);
    return partes.join(", ");
  }
  if (p.ferramenta === "metas_e_realizado") return `${a.visao || ""} · ${(a.meses || []).join(", ")}`;
  if (p.ferramenta === "listar_campanhas") return a.texto ? `“${a.texto}”` : "todas";
  if (p.ferramenta === "andamento_campanha") return p.resumo || `campanha ${a.campanha}`;
  if (p.ferramenta === "propor_campanha") return a.nome || "";
  return p.objetivo || a.objetivo || "";
}

function amostra(p) {
  const codigo = p.colunas.map((c) => /^id(_|$)/.test(c)); // códigos sem separador de milhar
  const celula = (v, j) => (typeof v === "number" ? (codigo[j] ? String(v) : fmt.num(v, 2)) : v === null ? "—"
    : typeof v === "boolean" ? (v ? "sim" : "não") : esc(v));
  const mais = p.linhas > p.amostra.length ? `<p class="fraco chat-mais">mostrando ${p.amostra.length} de ${fmt.num(p.linhas)} linhas</p>` : "";
  const num = p.colunas.map((_, j) => p.amostra.every((r) => r[j] === null || typeof r[j] === "number"));
  const classe = (j) => (num[j] ? ' class="num"' : "");
  return `<div class="tabela-rolagem"><table class="dados">
    <thead><tr>${p.colunas.map((c, j) => `<th${classe(j)}>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${p.amostra.map((r) => `<tr>${r.map((v, j) => `<td${classe(j)}>${celula(v, j)}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>${mais}`;
}

// ---------- markdown simples e seguro ----------
// O texto é escapado antes; depois só viram tag os marcadores conhecidos (negrito, itálico, código, títulos,
// listas e tabelas com |). Assim nada do que a IA escrever vira HTML de verdade.
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>");
}

const ehLinhaTabela = (l) => /^\s*\|.*\|\s*$/.test(l);
const ehSeparador = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
const ehItem = (l) => /^\s*[-*•]\s+/.test(l);
const ehNumerado = (l) => /^\s*\d+[.)]\s+/.test(l);
const ehTitulo = (l) => /^\s*#{1,4}\s+/.test(l);

// Número, valor em reais ou percentual (alinha à direita nas tabelas).
const ehNumero = (c) => /^[−-]?\s*(R\$\s*)?[−-]?[\d.,]+\s*(%|mi|mil|kg|un)?$/i.test(c.replace(/\*\*/g, "").trim());

function markdown(texto) {
  const linhas = esc(texto || "").replace(/\r/g, "").split("\n");
  const partes = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  let html = "";
  let i = 0;
  while (i < linhas.length) {
    const l = linhas[i];
    if (ehLinhaTabela(l) && i + 1 < linhas.length && ehSeparador(linhas[i + 1])) {
      const cab = partes(l);
      // alinhamento: o do separador (---: ou :---:) e, sem ele, à direita nas colunas só de números
      const sep = partes(linhas[i + 1]);
      i += 2;
      const corpo = [];
      while (i < linhas.length && ehLinhaTabela(linhas[i])) corpo.push(partes(linhas[i++]));
      const alinhar = cab.map((_, j) => {
        const s = sep[j] || "";
        if (s.startsWith(":") && s.endsWith(":")) return "centro";
        if (s.endsWith(":")) return "num";
        if (s.startsWith(":")) return "";
        const valores = corpo.map((r) => r[j] || "").filter(Boolean);
        return valores.length && valores.every(ehNumero) ? "num" : "";
      });
      const td = (tag, c, j) => `<${tag}${alinhar[j] ? ` class="${alinhar[j]}"` : ""}>${inline(c || "")}</${tag}>`;
      html += `<div class="tabela-rolagem"><table class="dados"><thead><tr>${cab.map((c, j) => td("th", c, j)).join("")}</tr></thead>
        <tbody>${corpo.map((r) => `<tr>${cab.map((_, j) => td("td", r[j], j)).join("")}</tr>`).join("")}</tbody></table></div>`;
      continue;
    }
    if (ehItem(l) || ehNumerado(l)) {
      const numerada = ehNumerado(l);
      const itens = [];
      while (i < linhas.length && (numerada ? ehNumerado(linhas[i]) : ehItem(linhas[i]))) {
        itens.push(linhas[i++].replace(numerada ? /^\s*\d+[.)]\s+/ : /^\s*[-*•]\s+/, ""));
      }
      const tag = numerada ? "ol" : "ul";
      html += `<${tag}>${itens.map((x) => `<li>${inline(x)}</li>`).join("")}</${tag}>`;
      continue;
    }
    if (ehTitulo(l)) {
      html += `<h4>${inline(l.replace(/^\s*#{1,4}\s+/, ""))}</h4>`;
      i++;
      continue;
    }
    if (!l.trim()) { i++; continue; }
    const par = [];
    while (i < linhas.length && linhas[i].trim() && !ehItem(linhas[i]) && !ehNumerado(linhas[i]) && !ehTitulo(linhas[i])
           && !(ehLinhaTabela(linhas[i]) && i + 1 < linhas.length && ehSeparador(linhas[i + 1]))) {
      par.push(inline(linhas[i++]));
    }
    html += `<p>${par.join("<br>")}</p>`;
  }
  return html;
}
