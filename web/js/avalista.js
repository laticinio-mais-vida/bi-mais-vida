// Contrato de avalista (página filha da Reavaliação de Crédito, botão "Avalista"): o contrato de quando o cliente compra
// num CNPJ que não está no nome dele e outra empresa ou uma pessoa garante o pagamento. A página preenche os dados da
// compradora e de quem garante, guarda o contrato e baixa o PDF igual ao modelo em Word.
// - Dois modelos, pelo tipo de quem garante: Pessoa jurídica (Contrato de Garantia Fidejussória) e Pessoa física
//   (Contrato de Compra e Venda de Produtos Lácteos, com a garantia dentro).
// - Pode ser salvo pela metade (basta a razão social da compradora). O que falta aparece no passo 5 e, no PDF, sai como
//   uma linha para preencher à mão.
// - As contas (o que falta, CNPJ e CPF que não conferem), a gravação e o PDF ficam no servidor (bi/avalista.py e
//   bi/avalista_pdf.py); aqui é a apresentação: enquanto a pessoa digita, a página pede a conferência
//   (/api/credito/avalista/conferir), que também devolve o CNPJ, o CPF e o CEP com a pontuação.
// - Os dados da Mais Vida são uma configuração só, que o administrador altera aqui mesmo.
// - Todos que têm a página de crédito veem os contratos e baixam o PDF; só quem fez ou um administrador edita ou exclui.
import { api, esc, fmt, icone, irParaLogin, toast } from "./util.js";

const TIPOS = [
  { chave: "pj", nome: "Pessoa jurídica", dica: "uma empresa garante o pagamento", icone: "loja" },
  { chave: "pf", nome: "Pessoa física", dica: "uma pessoa garante o pagamento, pelo CPF", icone: "usuario" },
];
const MODELO = {
  pj: "Contrato de Garantia Fidejussória e Outras Avenças",
  pf: "Contrato de Compra e Venda de Produtos Lácteos por Prazo Indeterminado e Outras Avenças",
};
const ESTADOS_CIVIS = ["Solteiro", "Solteira", "Casado", "Casada", "Divorciado", "Divorciada", "Viúvo", "Viúva", "União estável"];
const ROTULOS_MV = { razao_social: "Razão social", cnpj: "CNPJ", ie: "Inscrição estadual", endereco: "Endereço da sede",
  cep: "CEP", qualificacao: "Qualificação de quem representa", tratamento: "Tratamento", representante: "Nome de quem representa",
  nacionalidade: "Nacionalidade", estado_civil: "Estado civil", profissao: "Profissão", cpf: "CPF" };

let ctx = null, raiz = null;
// lista: o que /api/credito/avalistas trouxe (os contratos e o que o formulário usa); form: o que está na tela
// ({tipo, data, compradora, garantidores: {pj, pf}}: trocar o tipo não apaga o que foi digitado no outro);
// cliente: o cliente do ERP de onde veio a compradora; aberto: o contrato guardado que está no formulário;
// pendencias: a última conferência do servidor (erroConferir: por que ela falhou); sujo: há alteração não salva;
// fornecedor: o administrador está alterando os dados da Mais Vida; digitacoes: conta cada tecla, para a conferência
// que chega atrasada não pôr um valor velho num campo; os outros contadores: o pedido mais novo vale.
const estado = { lista: null, form: null, cliente: null, aberto: null, pendencias: null, erroConferir: null, sujo: false,
  salvando: false, fornecedor: false, digitacoes: 0, buscaLista: "", pedidoLista: 0, pedidoBusca: 0, pedidoConferir: 0 };

const pessoa = () => ({ tratamento: "", nome: "", nacionalidade: "", estado_civil: "", profissao: "", cpf: "", endereco: "", cep: "" });
const empresa = () => ({ razao_social: "", cnpj: "", ie: "", endereco: "", cep: "", qualificacao: "sócio administrador",
  poderes: "", representantes: [pessoa()] });
const formNovo = () => ({ tipo: null, data: estado.lista?.hoje || "", compradora: empresa(), garantidores: { pj: empresa(), pf: pessoa() } });

export function avalistaTemAlteracoes() { return estado.sujo; }

export async function montarAvalista(container, contexto) {
  ctx = contexto;
  raiz = container;
  container.innerHTML = `<div class="cc av"><div class="esqueleto" style="height:150px"></div><div class="esqueleto" style="height:320px"></div></div>`;
  try {
    estado.lista = await api(`/api/credito/avalistas${estado.buscaLista ? `?busca=${encodeURIComponent(estado.buscaLista)}` : ""}`);
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir os contratos de avalista: ${esc(e.message)}</p></div>`;
    return;
  }
  if (!estado.form) estado.form = formNovo();
  render();
  if (estado.form.tipo) conferir();
}

// ---------- o que está no formulário ----------
const somenteLeitura = () => !!estado.aberto && !estado.aberto.pode_editar;
const garantidor = () => estado.form.garantidores[estado.form.tipo];

// "compradora.representantes.0.nome" -> o objeto e a chave onde o valor fica
function lugar(caminho) {
  const partes = caminho.split(".");
  let alvo = partes[0] === "garantidor" ? garantidor() : partes[0] === "compradora" ? estado.form.compradora : estado.form;
  const resto = partes[0] === "data" ? partes : partes.slice(1);
  for (const p of resto.slice(0, -1)) alvo = alvo?.[p];
  return [alvo, resto[resto.length - 1]];
}
const valorDe = (caminho) => { const [alvo, chave] = lugar(caminho); return alvo?.[chave] ?? ""; };
function gravar(caminho, valor) { const [alvo, chave] = lugar(caminho); if (alvo) alvo[chave] = valor; }

function dadosDoForm() {
  const f = estado.form;
  return { tipo: f.tipo, data: f.data || null, compradora: f.compradora, garantidor: garantidor() };
}

// O contrato que veio do servidor (já conferido) no formulário, sem perder o que foi digitado no outro tipo.
function formDe(dados) {
  const f = formNovo();
  f.tipo = dados.tipo;
  f.data = dados.data || "";
  f.compradora = { ...empresa(), ...dados.compradora, representantes: dados.compradora.representantes.map((r) => ({ ...pessoa(), ...r })) };
  f.garantidores[dados.tipo] = dados.tipo === "pj"
    ? { ...empresa(), ...dados.garantidor, representantes: dados.garantidor.representantes.map((r) => ({ ...pessoa(), ...r })) }
    : { ...pessoa(), ...dados.garantidor };
  return f;
}

function limpar() {
  Object.assign(estado, { form: formNovo(), cliente: null, aberto: null, pendencias: null, erroConferir: null, sujo: false });
}

// ---------- a página ----------
function render() {
  const l = estado.lista;
  if (!l.ativo) {
    raiz.innerHTML = `<div class="cc av"><div class="aviso">${icone("info")}<span>${esc(l.aviso)}</span></div></div>`;
    return;
  }
  raiz.innerHTML = `
    <div class="cc av">
      <datalist id="av-estados-civis">${ESTADOS_CIVIS.map((x) => `<option value="${x}">`).join("")}</datalist>
      <section class="cartao secao entra cc-passo" id="av-tipo" style="--i:0"></section>
      <div id="av-form"></div>
      <section class="cartao secao entra cr-historico" id="av-lista" style="--i:2"></section>
    </div>`;
  ligar();
  desenharTipo();
  desenharForm();
  desenharLista();
}

// Os eventos ficam no .av, que é refeito a cada vez que a página monta (a seção da página fica).
function ligar() {
  const av = raiz.querySelector(".av");
  av.addEventListener("click", (e) => {
    const alvo = (seletor) => e.target.closest(seletor);
    let b;
    if ((b = alvo("[data-tipo]"))) mudarTipo(b.dataset.tipo);
    else if ((b = alvo("[data-mais-rep]"))) maisRepresentante(b.dataset.maisRep);
    else if ((b = alvo("[data-menos-rep]"))) menosRepresentante(b.dataset.menosRep, Number(b.dataset.n));
    else if ((b = alvo("[data-escolher]"))) escolherCliente(Number(b.dataset.escolher));
    else if (alvo("[data-soltar-cliente]")) { estado.cliente = null; estado.sujo = true; desenharForm(); }
    else if (alvo("[data-salvar]")) salvar();
    else if (alvo("[data-pdf]")) baixarDoForm();
    else if (alvo("[data-novo]")) novo();
    else if ((b = alvo("[data-ir]"))) irPara(b.dataset.ir);
    else if ((b = alvo("[data-abrir]"))) abrir(Number(b.dataset.abrir));
    else if ((b = alvo("[data-pdf-de]"))) baixar(Number(b.dataset.pdfDe), b);
    else if ((b = alvo("[data-excluir]"))) excluir(Number(b.dataset.excluir), b);
    else if (alvo("[data-mudar-mv]")) { estado.fornecedor = true; desenharMaisVida(); raiz.querySelector("#av-mv-form input")?.focus(); }
    else if (alvo("[data-cancelar-mv]")) { estado.fornecedor = false; desenharMaisVida(); }
    else if (alvo("[data-limpar-busca]")) { const c = raiz.querySelector("#av-busca-lista"); if (c) c.value = ""; buscarNaLista(""); }
  });
  av.addEventListener("input", (e) => {
    if (e.target.id === "av-busca-cliente") { buscarCliente(e.target.value); return; }
    if (e.target.id === "av-busca-lista") { esperarBuscaNaLista(e.target.value); return; }
    const caminho = e.target.dataset?.campo;
    if (!caminho) return;
    gravar(caminho, e.target.value);
    estado.sujo = true;
    estado.digitacoes += 1;
    esperarConferir();
  });
  av.addEventListener("submit", (e) => {
    if (e.target.id !== "av-mv-form") return;
    e.preventDefault();
    salvarMaisVida(e.target);
  });
}

const cabecalho = (n, titulo, sub, acoes = "") =>
  `<div class="cartao-cab"><div><h3><span class="cc-num">${n}</span>${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}</div>${acoes}</div>`;

// ---------- 1. quem garante ----------
function desenharTipo() {
  const card = raiz.querySelector("#av-tipo"), f = estado.form, a = estado.aberto;
  const botoes = TIPOS.map((t) => `<button type="button" class="cc-porte cc-tipo" role="radio" data-tipo="${t.chave}"
      aria-checked="${f.tipo === t.chave}"${somenteLeitura() ? " disabled" : ""}><b>${icone(t.icone)}${t.nome}</b><small>${t.dica}</small></button>`).join("");
  const aberto = a ? `
    <div class="cc-cliente cc-editando">
      <span class="cr-cliente-icone">${icone(a.pode_editar ? "lapis" : "olho")}</span>
      <div class="cr-cliente-nome"><b>Contrato nº ${a.id} · ${esc(a.compradora)}</b>
        <small>feito por ${esc(a.feito_por)} em ${fmt.dataHora(a.feito_em)}${a.editado_em ? ` · editado por ${esc(a.editado_por)} em ${fmt.dataHora(a.editado_em)}` : ""}${a.pode_editar ? "" : " · só quem fez ou um administrador altera"}</small></div>
      <button type="button" class="btn" data-novo>${icone("mais")}Novo contrato</button>
    </div>` : "";
  card.innerHTML = cabecalho(1, "Quem garante o pagamento",
    "O contrato muda conforme quem garante: uma empresa ou uma pessoa. A compradora é sempre a empresa do CNPJ das notas.") + `
    <div class="cc-portes cc-tipos" role="radiogroup" aria-label="Quem garante">${botoes}</div>
    ${f.tipo ? `<p class="av-modelo">${icone("arquivo")}<span>Modelo: <b>${MODELO[f.tipo]}</b></span></p>` : ""}${aberto}`;
}

function mudarTipo(tipo) {
  if (tipo === estado.form.tipo || somenteLeitura()) return;
  estado.form.tipo = tipo;
  estado.sujo = estado.sujo || !!estado.aberto;
  desenharTipo();
  desenharForm();
  conferir();
}

// ---------- 2 a 5. o formulário ----------
function campo(caminho, rotulo, { dica = "", opcional = false, classe = "", max = 200, lista = "", modo = "", tipo = "text", exemplo = "" } = {}) {
  return `<label class="campo-form ${classe}"><span>${rotulo}${opcional ? " <small>(opcional)</small>" : ""}</span>
    <input type="${tipo}" data-campo="${caminho}" value="${esc(valorDe(caminho))}" maxlength="${max}" autocomplete="off" spellcheck="false"
      ${lista ? `list="${lista}"` : ""} ${modo ? `inputmode="${modo}"` : ""} ${exemplo ? `placeholder="${esc(exemplo)}"` : ""} ${somenteLeitura() ? "disabled" : ""}>
    ${dica ? `<small>${dica}</small>` : ""}</label>`;
}

function tratamento(caminho) {
  const v = valorDe(caminho);
  return `<label class="campo-form av-curto"><span>Tratamento</span><span class="campo">
    <select data-campo="${caminho}" ${somenteLeitura() ? "disabled" : ""}><option value=""${v ? "" : " selected"}>Escolha</option>
      ${estado.lista.tratamentos.map((t) => `<option${t === v ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></span></label>`;
}

// Os dados de uma pessoa (representante ou garantidor). No modelo Pessoa física, o representante da compradora sai sem
// "Sr./Sra." e sem o endereço de casa. O documento é só o CPF (o RG dos modelos saiu do contrato).
function camposPessoa(caminho, { comTratamento, comEndereco }) {
  return `<div class="av-campos">
    ${comTratamento ? tratamento(`${caminho}.tratamento`) : ""}
    ${campo(`${caminho}.nome`, "Nome completo", { classe: "av-largo" })}
    ${campo(`${caminho}.nacionalidade`, "Nacionalidade", { max: 40, exemplo: "Brasileiro(a)" })}
    ${campo(`${caminho}.estado_civil`, "Estado civil", { max: 40, lista: "av-estados-civis" })}
    ${campo(`${caminho}.profissao`, "Profissão", { max: 80, exemplo: "Empresário(a)" })}
    ${campo(`${caminho}.cpf`, "CPF", { max: 20, modo: "numeric", exemplo: "000.000.000-00" })}
    ${comEndereco ? campo(`${caminho}.endereco`, "Endereço de onde mora", { classe: "av-largo", max: 300, dica: "Rua, número, complemento, bairro, cidade e estado." }) : ""}
    ${comEndereco ? campo(`${caminho}.cep`, "CEP", { max: 12, modo: "numeric", exemplo: "00000-000" }) : ""}
  </div>`;
}

function camposEmpresa(caminho, e) {
  const pj = estado.form.tipo === "pj", ler = somenteLeitura();
  const reps = e.representantes.map((_, n) => `
    <fieldset class="av-rep"><legend>${e.representantes.length > 1 ? `Representante ${n + 1}` : "Quem assina pela empresa"}
      ${e.representantes.length > 1 && !ler ? `<button type="button" class="link-botao" data-menos-rep="${caminho}" data-n="${n}">remover</button>` : ""}</legend>
      ${camposPessoa(`${caminho}.representantes.${n}`, { comTratamento: pj, comEndereco: pj })}</fieldset>`).join("");
  const mais = !ler && e.representantes.length < estado.lista.max_representantes
    ? `<button type="button" class="btn av-mais" data-mais-rep="${caminho}">${icone("mais")}Outra pessoa assina junto</button>` : "";
  return `<div class="av-campos">
      ${campo(`${caminho}.razao_social`, "Razão social", { classe: "av-largo" })}
      ${campo(`${caminho}.cnpj`, "CNPJ", { max: 24, exemplo: "00.000.000/0000-00" })}
      ${campo(`${caminho}.ie`, "Inscrição estadual", { max: 30, opcional: true })}
      ${campo(`${caminho}.endereco`, "Endereço da sede", { classe: "av-largo", max: 300, dica: "Rua, número, complemento, bairro, cidade e estado." })}
      ${campo(`${caminho}.cep`, "CEP", { max: 12, modo: "numeric", exemplo: "00000-000" })}
      ${campo(`${caminho}.qualificacao`, "Qualificação de quem representa", { max: 80, dica: "Como sai no contrato. Ex.: sócio administrador, sócios administradores, procurador." })}
    </div>${reps}${mais}`;
}

function clienteDoErp() {
  if (somenteLeitura()) return "";
  const c = estado.cliente;
  if (c) {
    return `<div class="cc-cliente av-erp"><span class="cr-cliente-icone">${icone("loja")}</span>
      <div class="cr-cliente-nome"><b>${esc(c.nome || `Cliente ${c.id}`)}</b><small>cliente do ERP · código ${c.id}${c.cidade ? ` · ${esc(c.cidade)}${c.uf ? `/${esc(c.uf)}` : ""}` : ""}</small></div>
      <button type="button" class="btn" data-soltar-cliente>${icone("x")}Desligar do cliente</button></div>`;
  }
  return `<div class="cc-busca av-erp">
    <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
      <input type="search" id="av-busca-cliente" placeholder="Já é cliente? Busque pelo nome ou código para puxar do ERP" autocomplete="off" spellcheck="false" aria-label="Cliente do ERP"></label>
    <div class="cc-resultados" id="av-resultados" aria-live="polite"></div></div>`;
}

function desenharForm() {
  const alvo = raiz.querySelector("#av-form"), f = estado.form;
  if (!f.tipo) { alvo.innerHTML = ""; return; }
  const pj = f.tipo === "pj";
  alvo.innerHTML = `
    <section class="cartao secao cc-passo" id="av-compradora">
      ${cabecalho(2, "Compradora", "A empresa que compra: o CNPJ em que as notas saem.")}
      ${clienteDoErp()}
      ${camposEmpresa("compradora", f.compradora)}
      ${pj ? `<div class="av-campos av-poderes">${campo("compradora.poderes", "Poderes conferidos por", { classe: "av-largo", max: 300, opcional: true,
        dica: "Só quando quem assina tem uma procuração. Ex.: Sra. FULANA DE TAL, portadora do CPF nº 000.000.000-00. Em branco, a frase não sai no contrato." })}</div>` : ""}
    </section>
    <section class="cartao secao cc-passo" id="av-garantidor">
      ${pj ? cabecalho(3, "Garantidora (avalista)", "A empresa que garante o pagamento se a compradora não pagar.")
        : cabecalho(3, "Garantidor (avalista)", "A pessoa que garante o pagamento se a compradora não pagar.")}
      ${pj ? camposEmpresa("garantidor", garantidor()) : camposPessoa("garantidor", { comTratamento: false, comEndereco: true })}
    </section>
    <section class="cartao secao cc-passo" id="av-data">
      ${cabecalho(4, "Data e dados da Mais Vida", "A data que sai no fim do contrato e os dados da Mais Vida, que são os mesmos em todos os contratos.")}
      <div class="av-campos">${campo("data", "Data do contrato", { tipo: "date", classe: "av-curto" })}</div>
      <div id="av-mv"></div>
    </section>
    <section class="cartao secao cc-passo" id="av-conferir"></section>`;
  desenharMaisVida();
  desenharConferir();
}

function maisRepresentante(caminho) {
  const e = caminho === "garantidor" ? garantidor() : estado.form.compradora;
  if (e.representantes.length >= estado.lista.max_representantes) return;
  e.representantes.push(pessoa());
  estado.sujo = true;
  desenharForm();
  raiz.querySelector(`[data-campo="${caminho}.representantes.${e.representantes.length - 1}.nome"]`)?.focus();
  conferir();
}

function menosRepresentante(caminho, n) {
  const e = caminho === "garantidor" ? garantidor() : estado.form.compradora;
  const r = e.representantes[n];
  if (!r || e.representantes.length < 2) return;
  if (Object.values(r).some((v) => v) && !confirm(`Remover ${r.nome || `o representante ${n + 1}`}?`)) return;
  e.representantes.splice(n, 1);
  estado.sujo = true;
  desenharForm();
  conferir();
}

// ---------- o cliente do ERP ----------
let esperaCliente = null;
function buscarCliente(texto) {
  clearTimeout(esperaCliente);
  const alvo = raiz.querySelector("#av-resultados");
  if (!texto.trim()) { alvo.innerHTML = ""; return; }
  esperaCliente = setTimeout(async () => {
    const pedido = ++estado.pedidoBusca;
    try {
      const r = await api(`/api/credito/busca?texto=${encodeURIComponent(texto.trim())}`);
      if (pedido !== estado.pedidoBusca || !raiz.querySelector("#av-resultados")) return;
      alvo.innerHTML = r.clientes.length ? r.clientes.slice(0, 8).map((c) => `
        <button type="button" class="cc-resultado" data-escolher="${c.id}"><b>${esc(c.nome)}</b>
          <small>código ${c.id}${c.carteira ? ` · carteira de ${esc(c.carteira)}` : ""}</small></button>`).join("")
        : `<p class="cr-hist-vazio">Nenhum cliente encontrado. Preencha a compradora à mão.</p>`;
    } catch (e) {
      if (pedido === estado.pedidoBusca) alvo.innerHTML = `<p class="cr-hist-vazio">${esc(e.message)}</p>`;
    }
  }, 250);
}

// Do ERP vêm a razão social e o CNPJ; o endereço, a inscrição estadual e os sócios não chegam ao painel.
async function escolherCliente(id) {
  try {
    const c = await api(`/api/credito/avalista/cliente?id=${id}`);
    estado.cliente = c;
    estado.form.compradora.razao_social = c.razao_social || "";
    if (c.cnpj) estado.form.compradora.cnpj = c.cnpj;
    estado.sujo = true;
    desenharForm();
    conferir();
    toast(c.cnpj ? "Razão social e CNPJ puxados do ERP. O endereço e os sócios não vêm do ERP: preencha aqui."
      : "Razão social puxada do ERP. O CNPJ deste cliente ainda não chegou: preencha aqui, com o endereço e os sócios.");
    raiz.querySelector('[data-campo="compradora.endereco"]')?.focus();
  } catch (e) {
    toast(e.message, "erro");
  }
}

// ---------- 4. os dados da Mais Vida ----------
function desenharMaisVida() {
  const alvo = raiz.querySelector("#av-mv"), l = estado.lista;
  if (!alvo) return;
  const f = l.fornecedor, falta = l.fornecedor_falta[estado.form.tipo] || [];
  if (estado.fornecedor && l.pode_fornecedor) {
    const c = (k, extra = "") => `<label class="campo-form ${extra}"><span>${ROTULOS_MV[k]}</span>
      <input type="text" name="${k}" value="${esc(f[k] || "")}" maxlength="300" autocomplete="off" spellcheck="false"></label>`;
    alvo.innerHTML = `
      <form class="av-mv-form" id="av-mv-form" novalidate>
        <p class="av-mv-nota">${icone("info")}<span>Valem para <b>todos</b> os contratos, inclusive os já guardados: o PDF sai sempre com os dados de agora.
          Os quatro últimos (da nacionalidade ao CPF) e a inscrição estadual só saem no modelo Pessoa física.</span></p>
        <div class="av-campos">
          ${c("razao_social", "av-largo")}${c("cnpj")}${c("ie")}${c("endereco", "av-largo")}${c("cep")}${c("qualificacao")}
          <label class="campo-form av-curto"><span>${ROTULOS_MV.tratamento}</span><span class="campo"><select name="tratamento">
            <option value=""></option>${l.tratamentos.map((t) => `<option${t === f.tratamento ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></span></label>
          ${c("representante", "av-largo")}${c("nacionalidade")}${c("estado_civil")}${c("profissao")}${c("cpf")}
        </div>
        <div class="cc-acoes-registro"><button class="btn primario" type="submit">${icone("certo")}Salvar os dados da Mais Vida</button>
          <button type="button" class="btn" data-cancelar-mv>${icone("x")}Cancelar</button></div>
      </form>`;
    return;
  }
  const quem = [f.tratamento, f.representante].filter(Boolean).join(" ");
  alvo.innerHTML = `
    <div class="av-mv">
      <div class="av-mv-texto"><b>${esc(f.razao_social)}</b>
        <small>CNPJ ${esc(f.cnpj)}${f.ie ? ` · IE ${esc(f.ie)}` : ""} · ${esc(f.endereco)}, CEP ${esc(f.cep)}</small>
        <small>Representada por ${esc(quem)}, ${esc(f.qualificacao)}</small></div>
      ${l.pode_fornecedor ? `<button type="button" class="btn" data-mudar-mv>${icone("lapis")}Alterar</button>` : ""}
    </div>
    ${falta.length ? `<div class="aviso">${icone("alerta")}<span>Para este modelo ainda faltam dados da Mais Vida: <b>${esc(falta.join(", "))}</b>.
      No PDF, saem como uma linha para preencher à mão. ${l.pode_fornecedor ? "Preencha em “Alterar”." : "Só o administrador preenche."}</span></div>` : ""}`;
}

async function salvarMaisVida(f) {
  const botao = f.querySelector('button[type="submit"]');
  botao.disabled = true;
  try {
    const fornecedor = Object.fromEntries(Object.keys(ROTULOS_MV).map((k) => [k, f.elements[k].value]));
    const r = await api("/api/credito/avalista/fornecedor", { json: { fornecedor } });
    estado.lista = { ...estado.lista, ...r };
    estado.fornecedor = false;
    desenharMaisVida();
    toast("Dados da Mais Vida salvos. Valem para todos os contratos.");
  } catch (e) {
    toast(e.message, "erro");
    botao.disabled = false;
  }
}

// ---------- 5. conferir, salvar e baixar ----------
let esperaConferir = null;
function esperarConferir() {
  clearTimeout(esperaConferir);
  esperaConferir = setTimeout(conferir, 500);
}

// O servidor diz o que falta e devolve o CNPJ, o CPF e o CEP com a pontuação: entram nos campos que não estão em uso.
async function conferir() {
  clearTimeout(esperaConferir);
  if (!estado.form.tipo) return;
  const pedido = ++estado.pedidoConferir, digitacoes = estado.digitacoes;
  try {
    const r = await api("/api/credito/avalista/conferir", { json: { dados: dadosDoForm() } });
    if (pedido !== estado.pedidoConferir) return;
    Object.assign(estado, { pendencias: r.pendencias, erroConferir: null });
    if (digitacoes === estado.digitacoes) arrumar(r.dados); // a pessoa digitou enquanto a resposta vinha: fica para a próxima
  } catch (e) {
    if (pedido !== estado.pedidoConferir) return;
    estado.pendencias = null;
    estado.erroConferir = e.message;
  }
  desenharConferir();
}

function arrumar(dados) {
  raiz.querySelectorAll("#av-form [data-campo]").forEach((el) => {
    if (el === document.activeElement || el.tagName === "SELECT" || el.type === "date") return;
    const partes = el.dataset.campo.split(".");
    let v = dados;
    for (const p of partes) v = v?.[p];
    if (typeof v === "string" && v !== el.value) { el.value = v; gravar(el.dataset.campo, v); }
  });
}

function desenharConferir() {
  const alvo = raiz.querySelector("#av-conferir");
  if (!alvo) return;
  const p = estado.pendencias, ler = somenteLeitura(), a = estado.aberto;
  let corpo;
  if (!p) corpo = `<p class="cr-hist-vazio">${estado.erroConferir ? esc(estado.erroConferir) : "Conferindo…"}</p>`;
  else if (!p.length) corpo = `<div class="av-ok">${icone("certo")}<span>Tudo preenchido. O contrato está pronto para baixar.</span></div>`;
  else {
    corpo = `<div class="av-faltam"><p>${icone("alerta")}<span><b>${p.length === 1 ? "Falta 1 item" : `Faltam ${p.length} itens`}.</b>
        Dá para salvar e baixar assim mesmo: no PDF, o que falta sai como uma linha para preencher à mão.</span></p>
      <ul>${p.map((x) => `<li><button type="button" class="link-botao" data-ir="${esc(x.campo)}">${esc(x.texto)}</button></li>`).join("")}</ul></div>`;
  }
  marcarCampos(p || []);
  const salvo = a && !estado.sujo;
  alvo.innerHTML = cabecalho(5, "Conferir, salvar e baixar",
    ler ? "Este contrato é de outra pessoa: dá para conferir e baixar o PDF." : "Salvar guarda o contrato na lista abaixo. O PDF sai igual ao modelo em Word.") + corpo + `
    <div class="cc-acoes-registro av-acoes">
      ${ler ? "" : `<button type="button" class="btn${salvo ? "" : " primario"}" data-salvar${estado.salvando ? " disabled" : ""}>${icone("disco")}${a ? "Salvar as alterações" : "Salvar o contrato"}</button>`}
      <button type="button" class="btn${salvo || ler ? " primario" : ""}" data-pdf${estado.salvando ? " disabled" : ""}>${icone("abaixo")}${ler || salvo ? "Baixar o PDF" : "Salvar e baixar o PDF"}</button>
      ${a || estado.sujo ? `<button type="button" class="btn" data-novo>${icone("mais")}Novo contrato</button>` : ""}
      <span class="av-situacao" aria-live="polite">${salvo ? `${icone("visto")}salvo` : estado.sujo ? "alterações não salvas" : ""}</span>
    </div>`;
}

// O campo com CNPJ, CPF ou CEP que não confere fica marcado; o que só está vazio aparece na lista.
function marcarCampos(pendencias) {
  const errados = new Set(pendencias.filter((x) => /não confere|8 números|o mesmo da/.test(x.texto)).map((x) => x.campo));
  raiz.querySelectorAll("#av-form [data-campo]").forEach((el) => el.classList.toggle("av-errado", errados.has(el.dataset.campo)));
}

function irPara(caminho) {
  const el = raiz.querySelector(`#av-form [data-campo="${CSS.escape(caminho)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.focus({ preventScroll: true });
}

function novo() {
  if (estado.sujo && !confirm("Começar um contrato novo? O que não foi salvo sai.")) return;
  limpar();
  desenharTipo();
  desenharForm();
  raiz.querySelector("#av-tipo")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Grava o que está na tela (um contrato novo, ou por cima do que está aberto). Devolve o contrato gravado, ou null.
async function salvar(silencioso = false) {
  const f = estado.form, a = estado.aberto;
  if (!f.tipo || estado.salvando || somenteLeitura()) return null;
  if (!f.compradora.razao_social.trim()) {
    toast("Escreva a razão social da compradora para salvar.", "erro");
    irPara("compradora.razao_social");
    return null;
  }
  estado.salvando = true;
  desenharConferir();
  try {
    const corpo = { dados: dadosDoForm(), id_cliente: estado.cliente?.id ?? null,
      ...(a ? { id: a.id, versao: a.versao } : { chave: estado.lista.chave }) };
    const r = await api("/api/credito/avalista", { json: corpo });
    const { contrato, ...lista } = r;
    estado.lista = { ...estado.lista, ...lista };
    const garantidores = estado.form.garantidores;
    Object.assign(estado, { aberto: contrato, form: formDe(contrato.dados), pendencias: contrato.pendencias, sujo: false });
    // o que foi digitado no outro tipo continua na tela, se a pessoa trocar de volta
    estado.form.garantidores[contrato.tipo === "pj" ? "pf" : "pj"] = garantidores[contrato.tipo === "pj" ? "pf" : "pj"];
    estado.salvando = false;
    if (estado.buscaLista) await buscarNaLista(estado.buscaLista, true);
    desenharTipo();
    desenharForm();
    desenharCorpoLista();
    if (!silencioso) toast(a ? "Alterações salvas." : `Contrato nº ${contrato.id} salvo.`);
    return contrato;
  } catch (e) {
    toast(e.message, "erro");
    return null;
  } finally {
    estado.salvando = false;
    desenharConferir();
  }
}

// O PDF é sempre o do contrato guardado: salva antes o que mudou.
async function baixarDoForm() {
  let a = estado.aberto;
  if (!somenteLeitura() && (!a || estado.sujo)) {
    a = await salvar(true);
    if (!a) return;
  }
  const n = (a.pendencias || []).length;
  if (n && !confirm(`${n === 1 ? "Falta 1 item" : `Faltam ${n} itens`} no contrato. Baixar assim mesmo?\n\nNo PDF, o que falta sai como uma linha para preencher à mão.`)) return;
  baixar(a.id, raiz.querySelector("[data-pdf]"));
}

async function baixar(id, botao) {
  if (botao) botao.disabled = true;
  toast("Montando o PDF…");
  try {
    const r = await fetch(`/api/credito/avalista/pdf?id=${id}`);
    if (r.status === 401) { irParaLogin(); return; }
    if (!r.ok) {
      let msg = `erro ${r.status}`;
      try { msg = (await r.json()).erro || msg; } catch { /* sem corpo */ }
      throw new Error(msg);
    }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await r.blob());
    link.download = nomeDoArquivo(r.headers.get("Content-Disposition")) || "Contrato de avalista.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    toast("PDF salvo em Downloads.");
  } catch (e) {
    toast(`Não foi possível baixar o PDF: ${e.message}`, "erro");
  } finally {
    if (botao?.isConnected) botao.disabled = false;
  }
}

function nomeDoArquivo(cabecalho) {
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cabecalho || "");
  if (utf8) { try { return decodeURIComponent(utf8[1]); } catch { /* usa o outro */ } }
  return /filename="([^"]+)"/i.exec(cabecalho || "")?.[1];
}

// ---------- os contratos guardados ----------
function desenharLista() {
  const card = raiz.querySelector("#av-lista");
  card.innerHTML = `
    <div class="cartao-cab cc-lista-cab"><div><h3>${icone("caderneta")}Contratos guardados</h3><p class="sub" id="av-lista-sub"></p></div>
      <div class="cc-busca-lista">
        <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" id="av-busca-lista" placeholder="Buscar pela compradora, por quem garante, CNPJ ou CPF" autocomplete="off" spellcheck="false"
            aria-label="Buscar nos contratos guardados" value="${esc(estado.buscaLista)}"></label>
      </div></div>
    <div id="av-lista-corpo" aria-live="polite"></div>`;
  desenharCorpoLista();
}

function itemContrato(x) {
  const aberto = estado.aberto?.id === x.id;
  const situacao = x.faltam ? `<span class="status atencao">${icone("alerta")}${x.faltam === 1 ? "falta 1 item" : `faltam ${x.faltam} itens`}</span>`
    : `<span class="status no_ritmo">${icone("certo")}completo</span>`;
  return `<li class="cr-hist-item av-item${aberto ? " av-aberto" : ""}">
    <div class="cr-hist-cab">
      <span class="cr-hist-tipo">Nº ${x.id} · ${esc(x.tipo_nome)}</span>${situacao}
      <span class="av-item-acoes">
        <button type="button" class="btn cr-hist-excluir" data-abrir="${x.id}"${aberto ? " disabled" : ""}>${icone(x.pode_editar ? "lapis" : "olho")}${aberto ? "Aberto" : x.pode_editar ? "Abrir" : "Ver"}</button>
        <button type="button" class="btn cr-hist-excluir" data-pdf-de="${x.id}">${icone("abaixo")}PDF</button>
        ${x.pode_excluir ? `<button type="button" class="btn perigo cr-hist-excluir" data-excluir="${x.id}" aria-label="Excluir o contrato de ${esc(x.compradora)}">${icone("lixeira")}Excluir</button>` : ""}
      </span>
    </div>
    <p class="av-item-nome"><b>${esc(x.compradora)}</b>${x.compradora_cnpj ? ` <small>CNPJ ${esc(x.compradora_cnpj)}</small>` : ""}</p>
    <p class="av-item-garante">Garante: ${x.garantidor ? `<b>${esc(x.garantidor)}</b>` : "<i>ainda sem nome</i>"}${x.garantidor_doc ? ` <small>${x.tipo === "pj" ? "CNPJ" : "CPF"} ${esc(x.garantidor_doc)}</small>` : ""}</p>
    <p class="av-item-quem">${x.data ? `Contrato de ${fmt.data(x.data)} · ` : ""}feito por ${esc(x.feito_por)} em ${fmt.dataHora(x.feito_em)}${x.editado_em ? ` · editado por ${esc(x.editado_por)} em ${fmt.dataHora(x.editado_em)}` : ""}</p>
  </li>`;
}

function desenharCorpoLista() {
  const corpo = raiz.querySelector("#av-lista-corpo"), sub = raiz.querySelector("#av-lista-sub");
  if (!corpo) return;
  const lista = estado.lista.contratos, busca = estado.buscaLista, n = lista.length;
  const limite = n >= 100 ? " (os 100 mais novos)" : "";
  sub.textContent = busca ? `${n} encontrado${n === 1 ? "" : "s"} para “${busca}”${limite}`
    : n ? `${n} guardado${n === 1 ? "" : "s"}${limite}, do mais novo para o mais antigo` : "os contratos salvos aparecem aqui, para abrir, corrigir e baixar de novo";
  corpo.innerHTML = n ? `<ol class="cr-hist">${lista.map(itemContrato).join("")}</ol>`
    : busca ? `<p class="cr-hist-vazio">Nenhum contrato encontrado para “${esc(busca)}”. <button type="button" class="link-botao" data-limpar-busca>Limpar a busca</button></p>`
      : `<p class="cr-hist-vazio">Nenhum contrato guardado ainda.</p>`;
}

let esperaLista = null;
function esperarBuscaNaLista(texto) {
  clearTimeout(esperaLista);
  esperaLista = setTimeout(() => buscarNaLista(texto), 300);
}

// A busca é no servidor; só a lista muda.
async function buscarNaLista(texto, semDesenhar = false) {
  const busca = String(texto || "").trim(), pedido = ++estado.pedidoLista;
  try {
    const r = await api(`/api/credito/avalistas${busca ? `?busca=${encodeURIComponent(busca)}` : ""}`);
    if (pedido !== estado.pedidoLista) return;
    estado.lista = { ...estado.lista, contratos: r.contratos };
    estado.buscaLista = busca;
  } catch (e) {
    if (pedido === estado.pedidoLista) toast(e.message, "erro");
    return;
  }
  if (!semDesenhar) desenharCorpoLista();
}

async function abrir(id) {
  if (estado.aberto?.id === id) return;
  if (estado.sujo && !confirm("Abrir este contrato? O que não foi salvo no formulário sai.")) return;
  try {
    const r = await api(`/api/credito/avalistas?id=${id}`);
    const c = r.contrato;
    Object.assign(estado, { aberto: c, form: formDe(c.dados), pendencias: c.pendencias, sujo: false,
      cliente: c.id_cliente ? { id: c.id_cliente, nome: "" } : null });
    desenharTipo();
    desenharForm();
    desenharCorpoLista();
    raiz.querySelector("#av-tipo")?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (c.id_cliente && c.pode_editar) nomeDoCliente(c.id_cliente);
  } catch (e) {
    toast(e.message, "erro");
    if (e.status === 404) buscarNaLista(estado.buscaLista);
  }
}

// O contrato guarda só o código do cliente do ERP: o nome e a cidade vêm de novo, para o cartão da compradora.
async function nomeDoCliente(id) {
  try {
    const c = await api(`/api/credito/avalista/cliente?id=${id}`);
    if (estado.cliente?.id !== id || estado.cliente.nome) return;
    estado.cliente = c;
    const cartao = raiz.querySelector("#av-compradora .av-erp .cr-cliente-nome");
    if (cartao) {
      cartao.innerHTML = `<b>${esc(c.nome || `Cliente ${c.id}`)}</b><small>cliente do ERP · código ${c.id}${c.cidade ? ` · ${esc(c.cidade)}${c.uf ? `/${esc(c.uf)}` : ""}` : ""}</small>`;
    }
  } catch { /* fica o código (o cliente pode ter saído do acesso de quem abriu) */ }
}

async function excluir(id, botao) {
  const x = estado.lista.contratos.find((c) => c.id === id);
  if (!confirm(`Excluir o contrato nº ${id}${x ? ` (${x.compradora})` : ""}? Ele sai desta página.`)) return;
  botao.disabled = true;
  try {
    estado.lista = { ...estado.lista, ...(await api("/api/credito/avalista/excluir", { json: { id } })) };
    if (estado.aberto?.id === id) { limpar(); desenharTipo(); desenharForm(); }
    if (estado.buscaLista) await buscarNaLista(estado.buscaLista, true);
    desenharCorpoLista();
    toast("Contrato excluído.");
  } catch (e) {
    toast(e.message, "erro");
    if (botao.isConnected) botao.disabled = false;
  }
}
