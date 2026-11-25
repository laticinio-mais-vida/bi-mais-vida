// Capa de análise de crédito (página filha da Reavaliação de Crédito): a "Capa de Análise de Crédito" de um cadastro novo
// (o cliente ainda não está no ERP) ou de uma reanálise (um cliente do ERP, escolhido aqui). O PDF do Serasa preenche a
// parte do Serasa; o histórico Mais Vida vem do ERP (na reanálise, do próprio cliente; no cadastro novo, só quando o CNPJ
// já é cliente); o analista responde o resto e escolhe o porte, e o painel indica o prazo e o limite pelo quadro da
// planilha "Classificação e Limites" (o sugerido é o mais baixo; o máximo, até onde pode chegar). Depois, registra o
// concedido e a justificativa. A reanálise pelo parecer, na página de crédito, continua igual.
// As contas, a leitura do PDF e a gravação ficam no servidor (bi/capa_credito.py); aqui é a apresentação: a cada escolha
// a página pede a capa de novo (/api/credito/capa/calcular). #/credito-capa?c=12 abre a reanálise do cliente 12.
// Uma capa registrada pode ser editada (quem registrou ou um administrador): o formulário abre com ela, e os itens
// automáticos (Serasa e histórico Mais Vida) ficam como foram registrados; #/credito-capa?e=7 abre a edição da capa 7.
// A lista das capas busca pelo cliente, pelo CNPJ ou pelo código (no servidor).
import { api, esc, fmt, icone, toast } from "./util.js";
import { consultaSerasa, corpoSerasa, itemCapa } from "./credito.js";

const MAX_PDF = 10 * 1024 * 1024;
const ORIGEM = { serasa: "do Serasa", erp: "do ERP", analista: "" };
const TIPOS = [
  { chave: "cadastro", nome: "Cadastro novo", dica: "o cliente ainda não está no ERP", icone: "loja" },
  { chave: "reanalise", nome: "Reanálise", dica: "um cliente que já está no ERP", icone: "usuario" },
];

let ctx = null, raiz = null;
// lista: o que /api/credito/capas trouxe (as capas e o que o formulário usa); tipo: "cadastro" ou "reanalise";
// cliente: o da reanálise ({id, nome, carteira}); serasaCliente: os envios do Serasa dele (/api/credito/serasa);
// serasaId: o envio da capa; analise: a capa (a última resposta do servidor); respostas: o que o analista escolheu;
// porte; rascunho: o que foi digitado; pedido e busca: o cálculo e a busca em andamento (o mais novo vale);
// edicao: a capa registrada que está sendo editada; buscaLista: o que está na busca da lista (pedidoLista: o pedido dela).
const estado = { lista: null, tipo: null, cliente: null, serasaCliente: null, serasaId: null, analise: null,
  respostas: {}, porte: null, rascunho: null, pedido: 0, busca: 0, lendoCliente: 0, enviando: false, registrando: false,
  edicao: null, buscaLista: "", pedidoLista: 0 };

export function capaTemAlteracoes() { return !!estado.analise; }

export async function montarCapaCredito(container, contexto) {
  ctx = contexto;
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const c = Number(q.get("c")), e = Number(q.get("e"));
  // ?e=7 (o Editar da página do cliente): lido uma vez; o link sai do endereço para não reabrir a edição depois
  if (Number.isInteger(e) && e > 0) history.replaceState(null, "", "#/credito-capa");
  if (Number.isInteger(c) && c > 0 && !(estado.tipo === "reanalise" && estado.cliente?.id === c)) {
    limpar();
    Object.assign(estado, { tipo: "reanalise", cliente: { id: c, nome: "", carteira: null } });
  }
  container.innerHTML = `<div class="cc"><div class="esqueleto" style="height:160px"></div><div class="esqueleto" style="height:320px"></div></div>`;
  try {
    estado.lista = await api("/api/credito/capas");
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a capa de análise: ${esc(e.message)}</p></div>`;
    return;
  }
  if (estado.buscaLista) await buscarNaLista(estado.buscaLista, true); // a busca da lista continua de antes
  render();
  if (Number.isInteger(e) && e > 0 && estado.edicao?.id !== e) { editarCapa(e); return; }
  if (estado.edicao) return;
  if (estado.cliente && !estado.cliente.nome) completarCliente();
  if (estado.cliente && !estado.serasaCliente) carregarCliente();
}

function limpar() {
  Object.assign(estado, { tipo: null, cliente: null, serasaCliente: null, serasaId: null, analise: null, respostas: {},
    porte: null, rascunho: null, edicao: null });
}

function render() {
  const l = estado.lista;
  if (!l.ativo) {
    raiz.innerHTML = `<div class="cc"><div class="aviso">${icone("info")}<span>${esc(l.aviso)}</span></div></div>`;
    return;
  }
  raiz.innerHTML = `
    <div class="cc">
      <section class="cartao secao entra cc-passo" id="cc-tipo" style="--i:0"></section>
      <section class="cartao secao entra cc-passo" id="cc-serasa" style="--i:1"></section>
      <div id="cc-form"></div>
      <section class="cartao secao entra cr-historico" id="cc-lista" style="--i:2"></section>
    </div>`;
  ligar();
  desenharTipo();
  desenharSerasa();
  desenharForm();
  desenharLista();
}

// Os eventos ficam no .cc, que é refeito a cada vez que a página monta (a seção da página fica).
function ligar() {
  const cc = raiz.querySelector(".cc");
  cc.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tipo]");
    if (t) mudarTipo(t.dataset.tipo);
    const c = e.target.closest("[data-escolher]");
    if (c) escolherCliente({ id: Number(c.dataset.escolher), nome: c.dataset.nome, carteira: c.dataset.carteira || null });
    if (e.target.closest("[data-trocar-cliente]")) trocarCliente();
    const v = e.target.closest("[data-virar-reanalise]");
    if (v) {
      const x = estado.analise?.ja_cliente?.[0];
      if (x) { estado.tipo = "reanalise"; escolherCliente({ id: x.id, nome: x.nome, carteira: x.carteira }); }
    }
    if (e.target.closest("[data-enviar-pdf]")) raiz.querySelector("#cc-arquivo")?.click();
    if (e.target.closest("[data-descartar]") && confirm("Descartar esta capa? O PDF lido continua gravado.")) descartar();
    const x = e.target.closest("[data-excluir]");
    if (x) excluir(Number(x.dataset.excluir), x);
    const ed = e.target.closest("[data-editar]");
    if (ed) editarCapa(Number(ed.dataset.editar));
    if (e.target.closest("[data-cancelar-edicao]")) cancelarEdicao();
    if (e.target.closest("[data-limpar-busca]")) {
      const b = raiz.querySelector("#cc-busca-lista");
      if (b) b.value = "";
      buscarNaLista("");
    }
    const p = e.target.closest("[data-porte]");
    if (p) { estado.porte = p.dataset.porte; marcarPorte(); calcular(); }
    // o link para o cliente no Crédito: a página de crédito monta de novo para ler o cliente do link
    if (e.target.closest('a[href^="#/credito?"]')) ctx.remontarCredito?.();
  });
  cc.addEventListener("change", (e) => {
    if (e.target.id === "cc-arquivo") {
      const arquivo = e.target.files?.[0];
      e.target.value = "";
      if (arquivo) enviar(arquivo);
      return;
    }
    const item = e.target.dataset?.item;
    if (item) {
      estado.respostas[item] = e.target.value || null;
      calcular();
    }
    if (e.target.id === "cc-vendedor") guardarRascunho({ vendedor: e.target.value });
    if (e.target.name === "prazo") guardarRascunho({ prazo: e.target.value, escolheuPrazo: true });
    if (e.target.closest("#cc-registro-form")) resumo();
  });
  cc.addEventListener("input", (e) => {
    if (e.target.id === "cc-busca") { buscar(e.target.value); return; }
    if (e.target.id === "cc-busca-lista") { esperarBuscaNaLista(e.target.value); return; }
    if (e.target.id === "cc-nome") guardarRascunho({ nome: e.target.value });
    if (e.target.closest("#cc-registro-form")) {
      if (e.target.name === "limite") guardarRascunho({ digitou: true });
      resumo();
    }
  });
  cc.addEventListener("submit", (e) => {
    if (e.target.id !== "cc-registro-form") return;
    e.preventDefault();
    registrar(e.target);
  });
}

const cabecalho = (n, titulo, sub, acoes = "") =>
  `<div class="cartao-cab"><div><h3><span class="cc-num">${n}</span>${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}</div>${acoes}</div>`;

// ---------- 1. cadastro novo ou reanálise (e o cliente da reanálise) ----------
function desenharTipo() {
  const card = raiz.querySelector("#cc-tipo");
  if (estado.edicao) {
    const ed = estado.analise?.edicao || estado.edicao;
    card.innerHTML = cabecalho(1, "Editando uma capa registrada",
      "O Serasa, o histórico Mais Vida e o cliente ficam como foram registrados. Mude as respostas, o porte, o concedido e os textos; a versão de antes fica guardada.") + `
      <div class="cc-cliente cc-editando">
        <span class="cr-cliente-icone">${icone("lapis")}</span>
        <div class="cr-cliente-nome"><b>${esc(ed.cliente)}</b>
          <small>${esc(ed.tipo_nome || (estado.edicao.tipo === "reanalise" ? "Reanálise" : "Cadastro novo"))} · registrada em ${fmt.dataHora(ed.feita_em)} por ${esc(ed.feita_por)}</small></div>
        <button type="button" class="btn" data-cancelar-edicao>${icone("x")}Cancelar a edição</button>
      </div>`;
    return;
  }
  const botoes = TIPOS.map((t) => `<button type="button" class="cc-porte cc-tipo" role="radio" data-tipo="${t.chave}"
      aria-checked="${estado.tipo === t.chave}"><b>${icone(t.icone)}${t.nome}</b><small>${t.dica}</small></button>`).join("");
  let cliente = "";
  if (estado.tipo === "reanalise") {
    const c = estado.cliente;
    cliente = c ? `
      <div class="cc-cliente">
        <span class="cr-cliente-icone">${icone("loja")}</span>
        <div class="cr-cliente-nome"><b>${esc(c.nome || `Cliente ${c.id}`)}</b>
          <small>código ${c.id}${c.carteira ? ` · carteira de ${esc(c.carteira)}` : ""}${estado.analise?.cliente
            ? ` · limite de hoje ${fmt.moeda2(estado.analise.cliente.limite)} · prazo ${esc(estado.analise.cliente.prazo || "não informado")}` : ""}</small></div>
        <button type="button" class="btn" data-trocar-cliente>${icone("x")}Trocar cliente</button>
      </div>`
      : `
      <div class="cc-busca">
        <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="cc-busca" placeholder="Cliente: nome ou código" autocomplete="off" spellcheck="false" aria-label="Cliente da reanálise"></label>
        <div class="cc-resultados" id="cc-resultados" aria-live="polite"></div>
      </div>`;
  }
  card.innerHTML = cabecalho(1, "Cadastro novo ou reanálise",
    "A mesma capa vale para os dois. Na reanálise, escolha o cliente: o histórico Mais Vida e o Serasa são os dele.") + `
    <div class="cc-portes cc-tipos" role="radiogroup" aria-label="Tipo da capa">${botoes}</div>${cliente}`;
}

function mudarTipo(tipo) {
  if (tipo === estado.tipo) return;
  if (estado.analise && !confirm("Trocar o tipo da capa? O PDF e o cliente saem; as respostas do analista e o porte continuam.")) return;
  Object.assign(estado, { tipo, cliente: null, serasaCliente: null, serasaId: null, analise: null, rascunho: null });
  desenharTipo();
  desenharSerasa();
  desenharForm();
  if (tipo === "reanalise") raiz.querySelector("#cc-busca")?.focus();
}

let espera = null;
function buscar(texto) {
  clearTimeout(espera);
  const alvo = raiz.querySelector("#cc-resultados");
  if (!texto.trim()) { alvo.innerHTML = ""; return; }
  espera = setTimeout(async () => {
    const pedido = ++estado.busca;
    try {
      const r = await api(`/api/credito/busca?texto=${encodeURIComponent(texto.trim())}`);
      if (pedido !== estado.busca || !raiz.querySelector("#cc-resultados")) return;
      alvo.innerHTML = r.clientes.length ? r.clientes.slice(0, 12).map((c) => `
        <button type="button" class="cc-resultado" data-escolher="${c.id}" data-nome="${esc(c.nome)}" data-carteira="${esc(c.carteira || "")}">
          <b>${esc(c.nome)}</b><small>código ${c.id}${c.carteira ? ` · carteira de ${esc(c.carteira)}` : ""}${c.bloqueado ? " · bloqueado no ERP" : ""}</small></button>`).join("")
        : `<p class="cr-hist-vazio">Nenhum cliente encontrado.</p>`;
    } catch (e) {
      if (pedido === estado.busca) alvo.innerHTML = `<p class="cr-hist-vazio">${esc(e.message)}</p>`;
    }
  }, 250);
}

// O link #/credito-capa?c=12 traz só o código: o nome e a carteira vêm da busca.
async function completarCliente() {
  const id = estado.cliente.id;
  try {
    const r = await api(`/api/credito/busca?texto=${id}`);
    const c = r.clientes.find((x) => x.id === id);
    if (c && estado.cliente?.id === id) {
      Object.assign(estado.cliente, { nome: c.nome, carteira: c.carteira });
      desenharTipo();
    }
  } catch { /* a capa mostra o código */ }
}

function escolherCliente(c) {
  Object.assign(estado, { cliente: c, serasaCliente: null, serasaId: null, analise: null, rascunho: null });
  desenharTipo();
  desenharSerasa();
  desenharForm();
  carregarCliente();
}

function trocarCliente() {
  if (estado.analise && !confirm("Trocar o cliente? A capa dele sai; as respostas do analista e o porte continuam.")) return;
  Object.assign(estado, { cliente: null, serasaCliente: null, serasaId: null, analise: null, rascunho: null });
  desenharTipo();
  desenharSerasa();
  desenharForm();
  raiz.querySelector("#cc-busca")?.focus();
}

// Reanálise: os envios do Serasa do cliente; o mais recente vale para a capa.
async function carregarCliente() {
  const id = estado.cliente?.id, pedido = ++estado.lendoCliente;
  if (!id) return;
  try {
    const r = await api(`/api/credito/serasa?cliente=${id}`);
    if (pedido !== estado.lendoCliente || estado.cliente?.id !== id) return;
    estado.serasaCliente = r;
    estado.serasaId = r.atual?.id ?? null;
    if (estado.serasaId) await calcular(true);
  } catch (e) {
    if (pedido !== estado.lendoCliente) return;
    estado.serasaCliente = { erro: e.message };
  }
  desenharTipo();
  desenharSerasa();
  desenharForm();
}

// ---------- 2. o PDF do Serasa ----------
function desenharSerasa() {
  const card = raiz.querySelector("#cc-serasa"), a = estado.analise, l = estado.lista;
  const arquivo = `<input type="file" id="cc-arquivo" accept="application/pdf,.pdf" hidden>`;
  const botao = (rotulo, primario) => `<button type="button" class="btn${primario ? " primario" : ""}" data-enviar-pdf${estado.enviando ? " disabled" : ""}>
    ${icone("arquivo")}${estado.enviando ? "Lendo o PDF…" : rotulo}</button>`;
  const titulo = "PDF do Serasa";
  if (estado.edicao) {
    if (!a) { card.innerHTML = cabecalho(2, titulo, "") + `<div class="esqueleto" style="height:90px"></div>`; return; }
    const s = a.serasa;
    card.innerHTML = cabecalho(2, titulo, `O mesmo da capa · CNPJ ${esc(s.cnpj)}. Para usar outro PDF, faça uma capa nova.`)
      + consultaSerasa(s, { validade: l.validade_dias }) + corpoSerasa(s);
    return;
  }
  if (!estado.tipo || (estado.tipo === "reanalise" && !estado.cliente)) {
    card.innerHTML = cabecalho(2, titulo, "") + `<p class="cr-hist-vazio">${estado.tipo ? "Escolha o cliente da reanálise acima." : "Escolha acima se a capa é de um cadastro novo ou de uma reanálise."}</p>`;
    return;
  }
  const reanalise = estado.tipo === "reanalise";
  if (reanalise && !estado.serasaCliente) {
    card.innerHTML = cabecalho(2, titulo, "os dados do Serasa do cliente") + `<div class="esqueleto" style="height:90px"></div>`;
    return;
  }
  if (reanalise && estado.serasaCliente.erro) {
    card.innerHTML = cabecalho(2, titulo, "") + `<div class="aviso">${icone("alerta")}<span>Não foi possível ler os dados do Serasa do cliente: ${esc(estado.serasaCliente.erro)}</span></div>`;
    return;
  }
  if (!a) {
    const sub = reanalise ? "o Relato – Pessoa Jurídica do cliente: a parte do Serasa da capa sai dele"
      : "o Relato – Pessoa Jurídica do cliente novo: a parte do Serasa da capa sai dele";
    const texto = reanalise ? "Este cliente ainda não tem os dados do Serasa no painel. Envie o PDF do Relato para fazer a capa."
      : "Envie o PDF do Serasa para começar.";
    card.innerHTML = cabecalho(2, titulo, sub, `<div class="cr-serasa-acoes">${botao("Enviar PDF", true)}</div>`) + `
      <p class="cr-hist-vazio">${texto} O painel guarda só a fundação, o score, a recomendação, o risco, o histórico de
        pagamento e as anotações negativas; o PDF não fica guardado.</p>${arquivo}`;
    return;
  }
  const s = a.serasa;
  const acoes = `<div class="cr-serasa-acoes">${botao(reanalise ? "Enviar PDF novo" : "Trocar o PDF")}
    <button type="button" class="btn" data-descartar>${icone("x")}Descartar</button></div>`;
  const sub = `CNPJ ${esc(s.cnpj)}${reanalise ? ` · PDF enviado ao painel em ${fmt.dataHora(s.enviado_em)} por ${esc(s.enviado_por)}` : ""}`;
  const consulta = consultaSerasa(s, { validade: l.validade_dias, dica: reanalise ? "Se puder, envie um PDF novo do Serasa." : "" });
  card.innerHTML = cabecalho(2, titulo, sub, acoes) + consulta + (reanalise ? "" : avisoCliente(a)) + corpoSerasa(s) + arquivo;
}

// Cadastro novo com um CNPJ que já é cliente no ERP (de antes): o histórico Mais Vida sai do histórico dele, e a capa
// pode virar a reanálise dele.
function avisoCliente(a) {
  if (a.ja_cliente === null) {
    return `<div class="aviso">${icone("info")}<span>O ERP ainda não manda o CNPJ dos clientes: não deu para conferir se este CNPJ já é cliente. O histórico Mais Vida ficou como cliente novo.</span></div>`;
  }
  if (!a.ja_cliente.length) return "";
  const c = a.ja_cliente[0];
  const outros = a.ja_cliente.length > 1 ? ` (e mais ${a.ja_cliente.length - 1} código${a.ja_cliente.length > 2 ? "s" : ""} com o mesmo CNPJ)` : "";
  return `<div class="cr-bloqueio cc-ja-cliente">${icone("alerta")}<span><b>Este CNPJ já é cliente no ERP:</b> ${esc(c.nome)}, código ${c.id}${c.carteira ? `, da carteira de ${esc(c.carteira)}` : ""}${outros}.
    O histórico Mais Vida abaixo saiu desse código. Se for uma reanálise dele, faça a capa como reanálise.</span>
    <button type="button" class="btn" data-virar-reanalise>${icone("usuario")}Fazer como reanálise</button></div>`;
}

async function enviar(arquivo) {
  if (arquivo.size > MAX_PDF) { toast("O arquivo passou de 10 MB.", "erro"); return; }
  if (estado.analise && !confirm("Trocar o PDF? As respostas do analista continuam; a parte do Serasa muda.")) return;
  estado.enviando = true;
  desenharSerasa();
  try {
    if (estado.tipo === "reanalise") await enviarDoCliente(arquivo);
    else {
      const r = await api("/api/credito/capa/serasa", { method: "POST", headers: { "Content-Type": "application/pdf" }, body: arquivo });
      const novo = !estado.analise || estado.analise.serasa.cnpj_digitos !== r.serasa.cnpj_digitos;
      estado.serasaId = r.serasa.id;
      estado.analise = r;
      if (novo) estado.rascunho = { nome: r.serasa.nome_fantasia || r.serasa.razao_social || "" };
      toast(r.ja_existia ? "Este PDF já tinha sido lido: valem os dados gravados." : "PDF do Serasa lido.");
      if (Object.keys(estado.respostas).length || estado.porte) await calcular(true);
    }
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    estado.enviando = false;
    desenharTipo();
    desenharSerasa();
    desenharForm();
  }
}

// Reanálise: o PDF vai para os dados do Serasa do cliente (o mesmo envio da página de crédito, que confere o nome).
async function enviarDoCliente(arquivo, confirmar = false) {
  const id = estado.cliente.id;
  const r = await api(`/api/credito/serasa?cliente=${id}${confirmar ? "&confirmar=1" : ""}`,
    { method: "POST", headers: { "Content-Type": "application/pdf" }, body: arquivo });
  if (r.confirmar) { // o nome do relatório não bate com o do cliente
    if (confirm(r.confirmar)) return enviarDoCliente(arquivo, true);
    return;
  }
  if (estado.cliente?.id !== id) return;
  estado.serasaCliente = r;
  estado.serasaId = r.atual?.id ?? null;
  toast(r.ja_existia ? "Este PDF já estava gravado para o cliente." : "Dados do Serasa gravados para o cliente.");
  if (estado.serasaId) await calcular(true);
}

function descartar() {
  const tipo = estado.tipo, cliente = estado.cliente;
  limpar();
  // na reanálise, o cliente fica escolhido (e o Serasa dele volta a valer)
  if (tipo === "reanalise" && cliente) { Object.assign(estado, { tipo, cliente }); carregarCliente(); } else estado.tipo = tipo;
  desenharTipo();
  desenharSerasa();
  desenharForm();
}

// ---------- 3 a 5. o cliente e o porte, a capa e a indicação ----------
async function calcular(semDesenhar = false) {
  if (!estado.serasaId && !estado.edicao) return;
  const pedido = ++estado.pedido, primeira = !estado.analise;
  try {
    const corpo = estado.edicao ? { editar: estado.edicao.id, porte: estado.porte, respostas: estado.respostas }
      : { tipo: estado.tipo, cliente: estado.cliente?.id ?? null, serasa_id: estado.serasaId, porte: estado.porte,
        respostas: estado.respostas };
    const r = await api("/api/credito/capa/calcular", { json: corpo });
    if (pedido !== estado.pedido || (!estado.serasaId && !estado.edicao)) return;
    estado.analise = { ...r, ja_existia: estado.analise?.ja_existia };
  } catch (e) {
    if (pedido === estado.pedido) toast(e.message, "erro");
    return;
  }
  if (semDesenhar) return;
  if (primeira) { desenharTipo(); desenharSerasa(); desenharForm(); return; }
  atualizarPontos();
  desenharIndicacao();
  desenharRegistro();
}

function desenharForm() {
  const alvo = raiz.querySelector("#cc-form"), a = estado.analise, l = estado.lista;
  if (!a) { alvo.innerHTML = ""; return; }
  const r = estado.rascunho || {}, reanalise = a.tipo === "reanalise";
  // na reanálise, o vendedor começa no da carteira do cliente
  const vendedor = r.vendedor ?? (reanalise && a.cliente?.id_vendedor && l.vendedores.some((v) => v.id === a.cliente.id_vendedor)
    ? String(a.cliente.id_vendedor) : "");
  if (reanalise && vendedor && !r.vendedor) guardarRascunho({ vendedor });
  // na edição, o vendedor da capa vale mesmo que não esteja mais na lista (inativo ou fora do acesso)
  const ed = estado.edicao, lista = ed && !l.vendedores.some((v) => v.id === ed.id_vendedor)
    ? [...l.vendedores, { id: ed.id_vendedor, nome: ed.vendedor }] : l.vendedores;
  const vendedores = lista.map((v) => `<option value="${v.id}"${String(v.id) === String(vendedor) ? " selected" : ""}>${esc(v.nome)}</option>`).join("");
  const nome = reanalise
    ? `<div class="campo-form"><span>Cliente</span><p class="cc-nome-fixo"><b>${esc(a.cliente.nome)}</b>
        <small>código ${a.cliente.id} · limite ${estado.edicao ? "de antes da capa" : "de hoje"} ${fmt.moeda2(a.cliente.limite)} · prazo ${esc(a.cliente.prazo || "não informado")}</small></p></div>`
    : `<label class="campo-form"><span>Nome do cliente</span>
        <input type="text" id="cc-nome" maxlength="200" autocomplete="off" value="${esc(r.nome || "")}"></label>`;
  alvo.innerHTML = `
    <section class="cartao secao entra cc-passo" style="--i:1">
      ${cabecalho(3, "Cliente e porte", "O porte da empresa dá até onde o limite e o prazo podem chegar no quadro.")}
      <div class="cr-registro-campos">
        ${nome}
        <label class="campo-form"><span>${reanalise ? "Vendedor do cliente" : "Vendedor que trouxe o cliente"}</span><span class="campo"><span class="ic-campo">${icone("usuario")}</span>
          <select id="cc-vendedor">${vendedor ? "" : `<option value="" selected>Escolha o vendedor</option>`}${vendedores}</select></span></label>
      </div>
      <div class="cc-portes" role="radiogroup" aria-label="Porte da empresa">
        ${l.portes.map((p) => `<button type="button" class="cc-porte" role="radio" data-porte="${p.chave}" aria-checked="${estado.porte === p.chave}">
          <b>${esc(p.nome)}</b><small>até ${p.parcelas} parcelas${p.blocos === 5 ? " · negociação com a diretoria" : ""}</small></button>`).join("")}
      </div>
    </section>
    <section class="cartao secao entra cc-passo" style="--i:2">
      ${cabecalho(4, "Capa de análise", "Os itens do Serasa e do histórico Mais Vida vêm preenchidos; escolha os outros. Cada item vale até o peso dele, e a soma vai até 100.")}
      ${tabelaCapa(a)}
    </section>
    <section class="cartao secao entra cc-passo" id="cc-indicacao" style="--i:3"></section>
    <section class="cartao secao entra cc-passo" id="cc-registro" style="--i:4"></section>`;
  desenharIndicacao();
  desenharRegistro();
}

function tabelaCapa(a) {
  let grupo = null;
  const linhas = a.itens.map((x) => {
    const cab = x.grupo !== grupo ? `<tr class="cc-grupo"><td colspan="4">${esc(x.grupo)}</td></tr>` : "";
    grupo = x.grupo;
    let resposta;
    if (x.auto) {
      resposta = `<span class="cc-auto">${esc(x.rotulo)}</span>${x.fonte ? `<small>${icone(x.origem === "erp" ? "banco" : "arquivo")}${esc(ORIGEM[x.origem])}: ${esc(x.fonte)}</small>` : ""}`;
    } else {
      const escolhida = estado.respostas[x.chave];
      const opcoes = estado.lista.capa.find((c) => c.chave === x.chave)?.opcoes || [];
      resposta = `<span class="campo"><select data-item="${x.chave}" aria-label="${esc(x.eixo)}">
          <option value=""${escolhida ? "" : " selected"}>Escolha</option>
          ${opcoes.map((o) => `<option value="${o.chave}"${o.chave === escolhida ? " selected" : ""}>${esc(o.rotulo)} (${o.pontos})</option>`).join("")}
        </select></span>${x.fonte ? `<small class="cc-escolha">${icone("info")}${esc(x.fonte)}</small>` : ""}`;
    }
    return `${cab}<tr><td class="esq cc-eixo">${esc(x.eixo)}</td><td class="cc-peso">${x.peso}</td><td class="esq cc-resposta">${resposta}</td>
      <td class="cc-pontos"><span data-pontos="${x.chave}">${x.pontos == null ? "—" : x.pontos}</span><small class="cc-de-peso"> de ${x.peso}</small></td></tr>`;
  }).join("");
  return `<div class="tabela-rolagem cc-tabela"><table class="dados cc-capa">
      <thead><tr><th class="esq">Item</th><th>Peso</th><th class="esq">Resposta</th><th>Pontos</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td colspan="3" class="esq" id="cc-total-rotulo">${totalRotulo(a)}</td><td id="cc-total">${a.pontos}</td></tr></tfoot>
    </table></div>`;
}

function totalRotulo(a) {
  if (!a.completa) return `Pontuação até agora · falta${a.faltam.length === 1 ? "" : "m"} ${a.faltam.length} ite${a.faltam.length === 1 ? "m" : "ns"}`;
  const f = a.faixa;
  return `Pontuação, de 0 a 100 · <b>${esc(f.rotulo)}</b> (${f.faixa === 0 ? "menos de 40 pontos" : f.faixa === 4 ? "75 pontos ou mais" : `${f.de} a ${f.ate} pontos`})`;
}

function atualizarPontos() {
  const a = estado.analise;
  for (const x of a.itens) {
    const td = raiz.querySelector(`[data-pontos="${x.chave}"]`);
    if (td) td.textContent = x.pontos == null ? "—" : x.pontos;
  }
  const t = raiz.querySelector("#cc-total"), r = raiz.querySelector("#cc-total-rotulo");
  if (t) t.textContent = a.pontos;
  if (r) r.innerHTML = totalRotulo(a);
}

function marcarPorte() {
  raiz.querySelectorAll("[data-porte]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.porte === estado.porte)));
}

const dias = (lista) => (lista.length === 1 ? `${lista[0]} dias` : `${lista.slice(0, -1).join(", ")} e ${lista[lista.length - 1]} dias`);
const parcelas = (n) => `${n} parcela${n === 1 ? "" : "s"}`;

function desenharIndicacao() {
  const alvo = raiz.querySelector("#cc-indicacao"), a = estado.analise;
  if (!alvo || !a) return;
  const cab = cabecalho(5, "Indicação de prazo e limite", 'Pelo quadro da planilha "Classificação e Limites": a pontuação dá a faixa, e o porte, até onde chega.');
  const i = a.indicacao;
  if (!i) {
    const falta = [!a.completa && `responda ${a.faltam.length === 1 ? "o item que falta" : `os ${a.faltam.length} itens que faltam`} na capa`,
      !estado.porte && "escolha o porte da empresa"].filter(Boolean).join(" e ");
    alvo.innerHTML = cab + `<p class="cr-hist-vazio">Para ver a indicação, ${falta}.</p>`;
    return;
  }
  let corpo;
  if (i.sem_prazo) {
    corpo = `<div class="cr-parecer ruim"><div class="cr-parecer-cab"><span class="status ruim">${icone("x")}Sem prazo</span>
      <span class="cr-parecer-pedido">Menos de 40 pontos: <b>venda à vista</b> ou em 01 dia (venda antecipada), e aí qualquer limite vale.</span></div></div>`;
  } else {
    const porque = [`${esc(i.faixa_rotulo)}: até ${parcelas(i.parcelas_da_faixa)}`,
      `porte ${esc(i.porte_nome)}: até ${parcelas(i.parcelas_do_porte)}`].join("; ");
    corpo = `
      <div class="cc-indica">
        <div class="cc-indica-caixa sugerido"><span>Sugerido</span><b>${fmt.moeda(i.limite_sugerido)}</b>
          <small>em ${esc(i.prazo_sugerido)} · ${parcelas(i.parcelas)} (${dias(i.dias_sugeridos)})</small></div>
        <div class="cc-indica-caixa"><span>Pode chegar a</span><b>${fmt.moeda(i.limite_maximo)}</b>
          <small>em ${esc(i.prazo_maximo)} · ${parcelas(i.parcelas)} (${dias(i.dias_maximos)})</small></div>
      </div>
      <p class="cc-porque">${icone("info")}<span>${porque}.${i.diretoria ? ` <b>Acima de ${fmt.moeda(i.limite_maximo)}, só com negociação da diretoria.</b>` : ""}${i.faixa_vazia ? " Na planilha, esta casa do quadro está vazia: vale a da faixa anterior." : ""}
        À vista ou em 01 dia (venda antecipada), qualquer limite vale.</span></p>`;
  }
  alvo.innerHTML = cab + corpo + quadro(i);
}

// O quadro LIMITES em miniatura: as casas do cruzamento (a coluna da faixa no bloco do porte; na Grande, o 4º bloco e a
// diretoria) marcadas, com o sugerido e o máximo em destaque.
function quadro(i) {
  const l = estado.lista;
  const cab = l.faixas.map((f) => `<th${i.coluna === f.faixa || (i.sem_prazo && f.faixa === 0) ? ' class="cc-q-col"' : ""}>${f.faixa === 0 ? "menos de 40" : f.faixa === 4 ? "75 ou mais" : `${f.de} a ${f.ate}`}</th>`).join("");
  const prazos = l.faixas.map((f) => `<td>${f.parcelas ? parcelas(f.parcelas) : "sem prazo"}</td>`).join("");
  let marcouSugerido = false;
  const blocos = l.quadro.map((b, bi) => {
    // o bloco do porte (i.bloco, de 1 a 4) e, na Grande, a diretoria logo abaixo dele
    const noPorte = bi + 1 === i.bloco || (b.diretoria && i.diretoria);
    if (b.diretoria) {
      return `<tr class="cc-q-bloco${noPorte && !i.sem_prazo ? " no-porte" : ""}"><th class="esq">${bi + 1}º bloco<small>até ${parcelas(b.parcelas)}</small></th>
        <td>—</td><td colspan="4" class="cc-q-diretoria${noPorte && !i.sem_prazo ? " marcada" : ""}">negociação com a diretoria</td></tr>`;
    }
    return b.linhas.map((linha, li) => {
      const celulas = linha.map((v, ci) => {
        const marcada = noPorte && !i.sem_prazo && ci + 1 === i.coluna && v != null;
        let classe = marcada ? "marcada" : "";
        if (marcada && v === i.limite_sugerido && !marcouSugerido) { classe += " sugerido"; marcouSugerido = true; }
        return `<td class="${classe}" data-v="${v ?? ""}">${v == null ? "" : fmt.num(v)}</td>`;
      });
      return `<tr class="${li === 0 ? "cc-q-bloco" : ""}${noPorte ? " no-porte" : ""}">${li === 0 ? `<th class="esq" rowspan="${b.linhas.length}">${bi + 1}º bloco<small>até ${parcelas(b.parcelas)}</small></th>` : ""}<td></td>${celulas.join("")}</tr>`;
    }).join("");
  }).join("");
  const html = `
    <details class="cr-hist-numeros cc-quadro"><summary>Ver o quadro da planilha</summary>
      <div class="tabela-rolagem"><table class="dados cc-q">
        <thead><tr><th class="esq">Pontos</th>${cab}</tr><tr class="cc-q-prazo"><th class="esq">Prazo</th>${prazos}</tr></thead>
        <tbody>${blocos}</tbody></table></div>
      <p class="cr-parecer-nota">${i.sem_prazo ? "Menos de 40 pontos não entram no quadro." : `Em laranja, as casas do cruzamento: a coluna da faixa no ${i.bloco}º bloco (o do porte ${esc(i.porte_nome)})${i.diretoria ? " e, acima dele, a negociação com a diretoria" : ""}.`}
        Limites em R$. Cada parcela tem uma janela de dias: 5 a 7, 12 a 14, 19 a 21 e 26 a 29.</p>
    </details>`;
  // o máximo: a última casa marcada com o maior valor
  const tmp = document.createElement("template");
  tmp.innerHTML = html;
  if (!i.sem_prazo) {
    const marcadas = [...tmp.content.querySelectorAll("td.marcada[data-v]")].filter((td) => Number(td.dataset.v) === i.limite_maximo);
    if (marcadas.length) marcadas[marcadas.length - 1].classList.add("maximo");
  }
  return tmp.innerHTML;
}

// ---------- 6. o registro ----------
function guardarRascunho(mudar) {
  estado.rascunho = { ...(estado.rascunho || {}), ...mudar };
}

function lerValor(texto) {
  const t = String(texto || "").trim().replace(/[R$\s]/g, "");
  if (!t) return null;
  const n = Number(t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t.replace(/\.(?=\d{3}(\D|$))/g, ""));
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function desenharRegistro() {
  const alvo = raiz.querySelector("#cc-registro"), a = estado.analise, l = estado.lista;
  if (!alvo || !a) return;
  const cab = estado.edicao
    ? cabecalho(6, "Salvar a edição", "Grava uma versão nova da capa; a de antes fica guardada. O painel não muda o ERP: se o concedido mudou, mude o limite e o prazo lá.")
    : cabecalho(6, "Registrar a capa", "Grava a capa, a indicação e o que foi concedido. O painel não muda o ERP: depois de registrar, mude o limite e o prazo lá.");
  const i = a.indicacao;
  if (!i) { alvo.innerHTML = cab + `<p class="cr-hist-vazio">Termine a capa e escolha o porte para registrar.</p>`; return; }
  const r = estado.rascunho || {};
  // o limite começa no sugerido; o prazo, no sugerido se ele existe no ERP
  const limite = r.digitou ? r.limite : fmt.num(i.limite_sugerido, 2);
  // na edição, o prazo da capa vale mesmo que nenhum cliente o use mais no ERP
  const prazos = estado.edicao && !l.prazos.includes(estado.edicao.prazo_concedido)
    ? [...l.prazos, estado.edicao.prazo_concedido] : l.prazos;
  const prazo = r.escolheuPrazo && prazos.includes(r.prazo) ? r.prazo : prazos.includes(i.prazo_sugerido) ? i.prazo_sugerido : "";
  const dentro = new Set(a.prazos_dentro);
  const opcoes = prazos.map((x) => `<option value="${esc(x)}"${x === prazo ? " selected" : ""}>${esc(x)}${dentro.has(x) ? " · dentro do indicado" : ""}${a.cliente?.prazo === x ? " (de hoje)" : ""}</option>`).join("");
  alvo.innerHTML = cab + `
    <form class="cr-registro-form" id="cc-registro-form" novalidate>
      <div class="cr-registro-campos">
        <label class="campo-form"><span>Limite concedido (R$)</span>
          <input type="text" name="limite" inputmode="decimal" autocomplete="off" spellcheck="false" value="${esc(limite ?? "")}"></label>
        <label class="campo-form"><span>Prazo concedido</span><span class="campo"><span class="ic-campo">${icone("calendario")}</span>
          <select name="prazo">${prazo ? "" : `<option value="" selected>Escolha o prazo</option>`}${opcoes}</select></span></label>
      </div>
      <label class="campo-form"><span>Observações adicionais <small>(opcional)</small></span>
        <textarea name="observacoes" rows="2" maxlength="2000">${esc(r.observacoes || "")}</textarea></label>
      <label class="campo-form"><span>Justificativa</span>
        <textarea name="justificativa" rows="3" maxlength="2000" placeholder="Por que concedeu esse limite e esse prazo?">${esc(r.justificativa || "")}</textarea>
        <small>Não escreva CPF, telefone ou endereço.</small></label>
      <p class="cr-registro-resumo" id="cc-resumo" aria-live="polite"></p>
      <div id="cc-bloqueio" aria-live="polite"></div>
      <div class="cc-acoes-registro"><button class="btn primario" type="submit"${estado.registrando ? " disabled" : ""}>${icone("certo")}${estado.edicao ? "Salvar a edição" : "Registrar capa"}</button>
        ${estado.edicao ? `<button type="button" class="btn" data-cancelar-edicao>${icone("x")}Cancelar</button>` : ""}</div>
    </form>`;
  resumo();
}

const desdeBloqueio = (b) => (b.origem === "capa" ? "a capa de análise de crédito" : "a reanálise");

// À vista ou 01 dia: venda antecipada (o cliente paga antes de o pedido ser faturado), em que qualquer limite vale.
// Igual ao antecipada() de bi/capa_credito.py: "A VISTA" ou um prazo de um só dia, 0 ou 1.
function antecipada(prazo) {
  const dias = String(prazo || "").match(/\d+/g);
  return dias ? dias.length === 1 && Number(dias[0]) <= 1 : /VISTA/i.test(String(prazo || ""));
}

// O que o registro vai gravar e se passa do indicado, enquanto a pessoa digita. Na reanálise, o limite e o prazo de hoje
// e o prazo mínimo entre reanálises (só aumento esbarra; o administrador marca "Registrar mesmo assim").
function resumo() {
  const f = raiz.querySelector("#cc-registro-form"), a = estado.analise;
  if (!f || !a?.indicacao) return;
  guardarRascunho({ limite: f.limite.value, observacoes: f.observacoes.value, justificativa: f.justificativa.value });
  const i = a.indicacao, v = lerValor(f.limite.value), prazo = f.prazo.value, c = a.cliente;
  const partes = [];
  if (v == null) partes.push("Digite o limite concedido (0 = sem crédito, só à vista)");
  else {
    let nota = "";
    if (v > i.limite_maximo + 0.005 && antecipada(prazo)) nota = ` <span class="cr-v-bom">venda antecipada: qualquer limite vale</span>`;
    else if (v > i.limite_maximo + 0.005) nota = i.diretoria ? ` <span class="cr-v-ruim">acima do quadro: negociação com a diretoria</span>` : ` <span class="cr-v-ruim">acima do máximo indicado (${fmt.moeda(i.limite_maximo)})</span>`;
    else if (v + 0.005 >= i.limite_sugerido) nota = ` <span class="cr-v-bom">dentro do indicado</span>`;
    partes.push(c ? `Limite ${fmt.moeda2(c.limite)} → <b>${fmt.moeda2(v)}</b>${nota}` : `Limite <b>${fmt.moeda2(v)}</b>${nota}`);
  }
  if (prazo) {
    const dentro = a.prazos_dentro.includes(prazo);
    const antes = c && c.prazo !== prazo ? `${esc(c.prazo || "não informado")} → ` : "";
    partes.push(`prazo ${antes}<b>${esc(prazo)}</b> ${dentro ? `<span class="cr-v-bom">dentro do indicado</span>` : `<span class="cr-v-ruim">além do indicado (até ${esc(i.prazo_maximo)})</span>`}`);
  }
  f.querySelector("#cc-resumo").innerHTML = partes.join(" · ");
  // o prazo mínimo entre reanálises
  const b = a.bloqueio, alvo = f.querySelector("#cc-bloqueio");
  const bloqueado = !!(b && c && v != null && v > c.limite + 0.005);
  if (!bloqueado) alvo.innerHTML = "";
  else if (!alvo.firstChild) {
    alvo.innerHTML = `
      <div class="cr-bloqueio">${icone("cadeado")}<span>Este cliente está no prazo mínimo entre reanálises: <b>aumento só a partir de ${fmt.data(b.aumento_a_partir_de)}</b>
        (prazo mínimo de ${b.dias} dias desde ${desdeBloqueio(b)} de ${fmt.data(b.ultima_em)}).
        ${estado.edicao ? "Na edição, vale o prazo de quando a capa foi registrada. " : ""}${ctx.admin ? "Como administrador, você pode registrar mesmo assim, e a capa fica marcada como “passou do bloqueio”."
          : "Redução, corte ou manter o limite podem ser registrados."}</span></div>
      ${ctx.admin ? `<label class="cr-passar"><input type="checkbox" name="passar">Registrar mesmo assim</label>` : ""}`;
  }
  f.querySelector('button[type="submit"]').disabled = estado.registrando || (bloqueado && !(ctx.admin && f.passar?.checked));
}

async function registrar(f) {
  const a = estado.analise, l = estado.lista;
  if (!a?.indicacao || estado.registrando) return;
  const reanalise = a.tipo === "reanalise";
  const nome = raiz.querySelector("#cc-nome"), vendedor = raiz.querySelector("#cc-vendedor");
  const limite = lerValor(f.limite.value), justificativa = f.justificativa.value.trim();
  const faltou = !reanalise && !nome.value.trim() ? [nome, "Escreva o nome do cliente."]
    : !vendedor.value ? [vendedor, "Escolha o vendedor do cliente."]
    : limite == null ? [f.limite, "Digite o limite concedido, em reais (0 = sem crédito)."]
    : !f.prazo.value ? [f.prazo, "Escolha o prazo concedido."]
    : justificativa.length < 10 ? [f.justificativa, "Escreva a justificativa (pelo menos 10 letras)."] : null;
  if (faltou) {
    toast(faltou[1], "erro");
    faltou[0].focus();
    return;
  }
  estado.registrando = true;
  f.querySelector('button[type="submit"]').disabled = true;
  try {
    const comum = { chave: l.chave, nome: reanalise ? null : nome.value.trim(), id_vendedor: Number(vendedor.value),
      porte: estado.porte, respostas: estado.respostas, limite, prazo: f.prazo.value, observacoes: f.observacoes.value,
      justificativa, passar_bloqueio: !!f.passar?.checked };
    const editando = !!estado.edicao;
    const r = editando ? await api("/api/credito/capa/editar", { json: { ...comum, id: estado.edicao.id } })
      : await api("/api/credito/capa", { json: { ...comum, tipo: a.tipo, cliente: a.cliente?.id ?? null,
        serasa_id: estado.serasaId, dados_ate: a.dados_ate } });
    estado.lista = r;
    ctx.remontarCredito?.(); // a página de crédito do cliente mostra a capa
    limpar();
    desenharTipo();
    desenharSerasa();
    desenharForm();
    if (estado.buscaLista) await buscarNaLista(estado.buscaLista, true);
    desenharLista();
    toast(editando ? (r.ja_existia ? "Esta edição já estava salva." : "Capa editada. Se o concedido mudou, mude o limite e o prazo no ERP.")
      : r.ja_existia ? "Esta capa já estava registrada." : "Capa registrada. Agora mude o limite e o prazo no ERP.");
    raiz.querySelector("#cc-lista")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast(e.message, "erro");
    if (e.status === 400 && /atualizados|prazo mínimo/.test(e.message)) calcular(); // dados novos ou o bloqueio: de novo
    else if (e.status === 404 && estado.edicao) recarregarLista(); // editada ou excluída por outra pessoa
  } finally {
    estado.registrando = false;
    if (raiz.querySelector("#cc-registro-form")) resumo();
  }
}

// ---------- as capas registradas (o item é o mesmo da página do cliente: credito.js) ----------
// O cartão das capas registradas: o cabeçalho com a busca é desenhado uma vez (o campo não perde o foco); a lista,
// a cada busca.
function desenharLista() {
  const card = raiz.querySelector("#cc-lista");
  card.innerHTML = `
    <div class="cartao-cab cc-lista-cab"><div><h3>${icone("caderneta")}Capas registradas</h3><p class="sub" id="cc-lista-sub"></p></div>
      <div class="cc-busca-lista">
        <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="cc-busca-lista" placeholder="Buscar pelo cliente, CNPJ ou código" autocomplete="off" spellcheck="false"
            aria-label="Buscar nas capas registradas" value="${esc(estado.buscaLista)}"></label>
      </div></div>
    <div id="cc-lista-corpo" aria-live="polite"></div>`;
  desenharCorpoLista();
}

function desenharCorpoLista() {
  const corpo = raiz.querySelector("#cc-lista-corpo"), sub = raiz.querySelector("#cc-lista-sub");
  if (!corpo) return;
  const lista = estado.lista.capas, busca = estado.buscaLista, n = lista.length;
  const limite = n >= 100 ? " (as 100 mais novas)" : "";
  sub.textContent = busca ? `${n} encontrada${n === 1 ? "" : "s"} para “${busca}”${limite}`
    : n ? `${n} registrada${n === 1 ? "" : "s"}${limite}, da mais nova para a mais antiga` : "a capa, a indicação e o que foi concedido em cada uma";
  corpo.innerHTML = n ? `<ol class="cr-hist">${lista.map((x) => itemCapa(x)).join("")}</ol>`
    : busca ? `<p class="cr-hist-vazio">Nenhuma capa encontrada para “${esc(busca)}”. <button type="button" class="link-botao" data-limpar-busca>Limpar a busca</button></p>`
      : `<p class="cr-hist-vazio">Nenhuma capa registrada ainda.</p>`;
}

let esperaLista = null;
function esperarBuscaNaLista(texto) {
  clearTimeout(esperaLista);
  esperaLista = setTimeout(() => buscarNaLista(texto), 300);
}

// A busca é no servidor (o nome do cliente, a razão social, o CNPJ ou o código); só a lista muda.
async function buscarNaLista(texto, semDesenhar = false) {
  const busca = String(texto || "").trim(), pedido = ++estado.pedidoLista;
  try {
    const r = await api(`/api/credito/capas${busca ? `?busca=${encodeURIComponent(busca)}` : ""}`);
    if (pedido !== estado.pedidoLista) return;
    estado.lista = { ...estado.lista, capas: r.capas };
    estado.buscaLista = busca;
  } catch (e) {
    if (pedido === estado.pedidoLista) toast(e.message, "erro");
    return;
  }
  if (!semDesenhar) desenharCorpoLista();
}

async function recarregarLista() {
  await buscarNaLista(estado.buscaLista, true);
  desenharCorpoLista();
}

// ---------- editar uma capa registrada ----------
async function editarCapa(id) {
  if (estado.edicao?.id === id) return;
  if (estado.analise && !confirm("Editar esta capa? O que está no formulário agora sai.")) return;
  let x = estado.lista.capas.find((c) => c.id === id);
  try {
    if (!x) x = (await api(`/api/credito/capas?id=${id}`)).capas[0];
  } catch (e) {
    toast(e.message, "erro");
    return;
  }
  if (!x) { toast("Capa não encontrada: ela pode ter sido excluída ou editada; recarregue a página.", "erro"); return; }
  if (!x.pode_editar) { toast("Só quem registrou a capa ou um administrador pode editá-la.", "erro"); return; }
  limpar();
  Object.assign(estado, {
    edicao: x, tipo: x.tipo, porte: x.porte,
    cliente: x.tipo === "reanalise" ? { id: x.id_cliente, nome: x.cliente, carteira: null } : null,
    respostas: Object.fromEntries(x.respostas.filter((r) => !r.auto && r.opcao).map((r) => [r.chave, r.opcao])),
    rascunho: { nome: x.cliente, vendedor: String(x.id_vendedor), limite: fmt.num(x.limite_concedido, 2), digitou: true,
      prazo: x.prazo_concedido, escolheuPrazo: true, observacoes: x.observacoes || "", justificativa: x.justificativa },
  });
  desenharTipo();
  desenharSerasa();
  desenharForm();
  raiz.querySelector("#cc-tipo")?.scrollIntoView({ behavior: "smooth", block: "start" });
  await calcular(true);
  if (estado.edicao?.id !== id) return;
  desenharTipo();
  desenharSerasa();
  desenharForm();
}

function cancelarEdicao() {
  if (!confirm("Cancelar a edição? O que mudou no formulário sai; a capa fica como estava.")) return;
  limpar();
  desenharTipo();
  desenharSerasa();
  desenharForm();
}

async function excluir(id, botao) {
  if (!confirm("Excluir esta capa? Ela sai desta página e da página do cliente.")) return;
  botao.disabled = true;
  try {
    estado.lista = { ...estado.lista, ...(await api("/api/credito/capa/excluir", { json: { id } })) };
    ctx.remontarCredito?.();
    if (estado.edicao?.id === id) { limpar(); desenharTipo(); desenharSerasa(); desenharForm(); }
    if (estado.buscaLista) await buscarNaLista(estado.buscaLista, true);
    desenharCorpoLista();
    toast("Capa excluída.");
  } catch (e) {
    toast(e.message, "erro");
    botao.disabled = false;
  }
}
