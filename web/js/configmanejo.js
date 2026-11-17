// Configuração da página Manejo da Base (só administradores): ligar a campanha (desligada, nenhuma lista é criada); em
// "Quem justifica", quem vê a página e quem pode responder pelos clientes (os vendedores de cada pessoa, em todas as
// páginas, ficam em Usuários; aqui só aparecem, para avisar do vendedor que ficou sem ninguém para justificar); e, em
// "Regras", os dias sem compra e de atraso de cada regra, o dia do prazo e quais vendedores são a central. As regras
// ficam em bi/manejo.py (ConfigManejo) e tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";
import { iniciais } from "./conta.js";

const SECOES = [["campanha", "loja", "Campanha"], ["usuarios", "escudo", "Quem justifica"], ["regras", "ajustes", "Regras"]];
// chave, título e explicação de cada regra, na ordem da tela
const DIAS = [
  ["semanal", "Cliente semanal", "Dias sem compra para sugerir a central. Vale também para o cliente sem frequência no cadastro (com o nome de uma rede no campo Rede, ou com o campo vazio)."],
  ["quinzenal", "Cliente quinzenal", "Dias sem compra para sugerir a central."],
  ["mensal", "Cliente mensal", "Dias sem compra para sugerir a central."],
  ["inadimplencia", "Inadimplência", "Dias de atraso do título em aberto mais antigo para sugerir a inativação."],
  ["central", "Cliente da central", "Dias sem compra para sugerir a inativação, contados do que for mais recente: a entrada na central ou a última compra."],
];
const MIN_DIAS = 1, MAX_DIAS = 365, MAX_PRAZO = 10;
const NOME_EQUIPE = { ES: "ES", BA: "BA", EDIR: "Edir" };

let ctx = null, raiz = null;
let dados = null;            // resposta de /api/manejo/config
let orig = null, rasc = null;
let usuarios = [], nomesAcesso = {};       // os visualizadores e o nome dos vendedores das listas de "só alguns"
let origAcessos = null, acessos = null;    // login -> { ve, justifica }
let usuarioSel = null, buscaUsuario = "";
let secao = "campanha";
let sugeriuCentral = false;  // a central veio marcada só como sugestão (ainda não foi salva)
let mexeu = false;           // a pessoa mudou alguma coisa nesta visita (a sugestão da central sozinha não conta)

const clone = (o) => JSON.parse(JSON.stringify(o));
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const emLista = (itens) => (itens.length <= 1 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`);
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;
const ordenados = (ids) => [...new Set((ids || []).map(Number))].sort((a, b) => a - b);
// A data do prazo vem do servidor como AAAA-MM-DD: o que não tiver esse formato não aparece.
const DIA = /^(\d{4})-(\d{2})-(\d{2})/;
const dataCurta = (iso) => { const m = DIA.exec(String(iso ?? "")); return m ? `${m[3]}/${m[2]}` : ""; };
const dataComSemana = (iso) => { const m = DIA.exec(String(iso ?? "")); return m ? `${fmt.semana(m[0])}, ${m[3]}/${m[2]}/${m[1]}` : ""; };

export function configManejoTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigManejo(container, contexto) {
  ctx = contexto;
  raiz = container;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (SECOES.some(([id]) => id === q.get("secao"))) secao = q.get("secao");
  if (q.get("u")) { secao = "usuarios"; usuarioSel = q.get("u"); }  // o link "Configurar" da tela Usuários
  if (rasc && mexeu && contarAlteracoes() > 0) { render(); return; }  // volta com o que estava sendo mudado
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:260px"></div><div class="esqueleto" style="height:520px"></div></div>`;
  try {
    carregarDados(await api("/api/manejo/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function normal(cfg) {
  const c = cfg || {}, dias = c.dias || {};
  return {
    versao: c.versao ?? 1, ligada: c.ligada === true,
    dias: Object.fromEntries(DIAS.map(([k]) => [k, dias[k] ?? ""])),
    prazo_dia_util: c.prazo_dia_util ?? 2, central: ordenados(c.central),
  };
}

function carregarDados(r) {
  dados = r;
  dados.vendedores = (r.vendedores || []).map((v) => ({ ...v, id: Number(v.id) }));
  orig = normal(r.config);
  rasc = clone(orig);
  mexeu = false;
  // Sem central salva, os vendedores com CENTRAL no nome já vêm marcados, como sugestão: só valem depois de Salvar.
  const sugestao = orig.central.length ? [] : dados.vendedores.filter((v) => v.nome_central).map((v) => v.id);
  sugeriuCentral = sugestao.length > 0;
  if (sugeriuCentral) rasc.central = ordenados(sugestao);
  usuarios = r.usuarios || [];
  nomesAcesso = r.nomes || {};
  origAcessos = Object.fromEntries(usuarios.map((u) => [u.login, {
    ve: (u.paginas || []).includes("manejo"),
    justifica: u.manejo?.justifica === true,
  }]));
  acessos = clone(origAcessos);
  if (!usuarios.some((u) => u.login === usuarioSel)) usuarioSel = usuarios[0]?.login ?? null;
}

// ---------- apoio ----------
function contarAlteracoesRegras() {
  let n = 0;
  if (rasc.ligada !== orig.ligada) n++;
  for (const [k] of DIAS) if (String(rasc.dias[k]) !== String(orig.dias[k])) n++;
  if (String(rasc.prazo_dia_util) !== String(orig.prazo_dia_util)) n++;
  if (!igual(ordenados(rasc.central), ordenados(orig.central))) n++;
  return n;
}

// Uma pessoa com o acesso mudado conta como uma alteração.
const usuarioMudou = (login) => !igual(acessos[login], origAcessos[login]);
const usuariosMudados = () => usuarios.filter((u) => usuarioMudou(u.login));
const contarAlteracoes = () => contarAlteracoesRegras() + usuariosMudados().length;

const nomeVendedor = (id) => nomesAcesso[id] || dados.vendedores.find((v) => v.id === Number(id))?.nome || "um vendedor";
const nomesCentral = () => ordenados(rasc.central).map(nomeVendedor);

function textoPrazo(n) {
  return { 1: "Último dia útil do mês", 2: "Penúltimo dia útil do mês", 3: "Antepenúltimo dia útil do mês" }[n]
    || `${n}º dia útil contando do fim do mês`;
}

// Os vendedores do acesso, como estão na tela Usuários (aqui só para ler).
function textoVendedores(u) {
  const e = u.escopo;
  if (!e) return "ainda nenhum vendedor escolhido";
  if (e.modo === "todos") return "todos os vendedores";
  if (e.modo === "equipes") return `os vendedores ${e.equipes.length === 1 ? "da equipe" : "das equipes"} ${emLista(e.equipes.map((q) => NOME_EQUIPE[q] || q))}`;
  const n = e.vendedores.length;
  return n <= 3 ? `só ${emLista(e.vendedores.map(nomeVendedor))}` : `só ${n} vendedores escolhidos`;
}

// Os vendedores da campanha (com cliente) que estão no acesso da pessoa: null no servidor = todos.
const comClientes = () => dados.vendedores.filter((v) => !(v.clientes === 0));
function alcance(u) {
  const ids = (dados.vendedores_do_acesso || {})[u.login];
  if (ids === null) return comClientes();
  const dele = new Set((Array.isArray(ids) ? ids : []).map(Number));
  return comClientes().filter((v) => dele.has(v.id));
}

// Os vendedores da campanha que ninguém marcado para justificar alcança: os clientes deles iriam sempre ao veredito
// como "sem justificativa".
function semJustificador() {
  const quem = usuarios.filter((u) => u.ativo !== false && acessos[u.login].ve && acessos[u.login].justifica);
  const cobertos = new Set(quem.flatMap((u) => alcance(u).map((v) => v.id)));
  return comClientes().filter((v) => !cobertos.has(v.id));
}

const quemJustifica = () => usuarios.filter((u) => acessos[u.login].ve && acessos[u.login].justifica);

function resumoCurtoAcesso(u) {
  const a = acessos[u.login];
  return !a.ve ? "não vê a página" : a.justifica ? "pode justificar" : "só consulta";
}

// O que falta para salvar o acesso (null = pode salvar). O servidor confere de novo.
function erroAcesso(u) {
  const a = acessos[u.login];
  if (!a.ve && !(u.paginas || []).some((p) => p !== "manejo")) return "é a única página desta pessoa; libere outra em Usuários antes de tirar esta";
  return null;
}

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      ${SECOES.map(([id, ic, nome]) => `<button type="button" data-secao="${id}" class="${secao === id ? "ativa" : ""}">${icone(ic)}${nome}</button>`).join("")}
      <div class="dica">${icone("info")} Tudo vale assim que você salvar. Os vendedores que cada pessoa vê, em todas as
        páginas, ficam em <a href="#/usuarios">Usuários</a>; aqui você escolhe quem pode justificar.
        ${dados.ativo === false ? "Neste computador a página só avisa: a campanha roda no site, e o que for salvo aqui vale só para este computador." : ""}</div>
    </aside>
    <div id="cm-secao"></div>
  </div>
  <div class="barra-salvar" id="cm-barra">
    <span id="cm-n">Alterações não salvas</span>
    <button class="btn" type="button" id="cm-descartar">Descartar</button>
    <button class="btn primario" type="button" id="cm-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-secao]").forEach((b) => b.addEventListener("click", () => irPara(b.dataset.secao)));
  raiz.querySelector("#cm-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cm-descartar").addEventListener("click", () => {
    rasc = clone(orig);
    acessos = clone(origAcessos);
    sugeriuCentral = false;
    mexeu = false;
    render();
  });
  renderSecao();
}

function irPara(id) {
  secao = id;
  raiz.querySelectorAll("[data-secao]").forEach((x) => x.classList.toggle("ativa", x.dataset.secao === id));
  renderSecao();
}

function renderSecao() {
  const alvo = raiz.querySelector("#cm-secao");
  if (secao === "usuarios") secaoUsuarios(alvo);
  else if (secao === "regras") secaoRegras(alvo);
  else secaoCampanha(alvo);
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cm-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cm-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
}

function mudou() {
  mexeu = true;
  atualizarBarra();
}

function erro(msg, id = "#cm-erro") {
  const el = raiz.querySelector(id) || raiz.querySelector("#cm-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

// ======================================================================================
// Campanha: ligada ou desligada, com o que confere antes de ligar
// ======================================================================================
function secaoCampanha(alvo) {
  const p = dados.prazo, prazoIgual = String(rasc.prazo_dia_util) === String(orig.prazo_dia_util);
  const quando = p && dataCurta(p.data) && prazoIgual ? ` (${dataCurta(p.data)} em ${esc(p.rotulo || "")})` : "";
  const justificam = quemJustifica(), central = nomesCentral(), fora = semJustificador();
  let explica;
  if (rasc.ligada) {
    explica = "A lista do mês recebe cada cliente assim que ele completa os dias e é atualizada a cada chegada de dados no site."
      + (orig.ligada ? "" : ` Ao salvar, a lista ${p && p.rotulo ? `de ${esc(p.rotulo)} ` : ""}nasce com quem já está na regra.`);
  } else {
    explica = "Desligada, nenhuma lista é criada nem atualizada. "
      + (orig.ligada ? "O que já está nas listas continua aberto para justificar e decidir." : "Antes de ligar, marque quem justifica e confira os vendedores da central.");
  }
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("loja")}Campanha</h2>
      <p class="sub">Sugere passar para a central o cliente que parou de comprar e inativar o inadimplente e o cliente da central que não compra</p></div></div>
    <div class="opcao-linha">
      <button class="chave ${rasc.ligada ? "ligada" : ""}" id="cm-ligada" type="button" role="switch" aria-checked="${rasc.ligada}" aria-label="Campanha ligada"></button>
      <div><b>Campanha ${rasc.ligada ? "ligada" : "desligada"}</b><p>${explica}</p></div>
    </div>
    <h3 class="usu-titulo">Para conferir</h3>
    <ul class="usu-dentro">
      <li class="${justificam.length ? "" : "aviso-nota"}">${icone(justificam.length ? "pessoas" : "alerta")}
        <span><b>Quem justifica:</b> ${justificam.length ? esc(emLista(justificam.map((u) => u.nome))) : "ninguém marcado ainda: todos os clientes iriam ao veredito sem justificativa"}</span>
        <a href="#/config-manejo?secao=usuarios" data-ir="usuarios">${icone("ajustes")}Escolher</a></li>
      <li class="${central.length ? "" : "aviso-nota"}">${icone(central.length ? "enviar" : "alerta")}
        <span><b>Central:</b> ${central.length ? esc(emLista(central)) : "nenhum vendedor marcado: marque antes de ligar a campanha"}${
          sugeriuCentral && igual(ordenados(rasc.central), ordenados(dados.vendedores.filter((v) => v.nome_central).map((v) => v.id))) ? " (sugestão pelo nome: confira e salve)" : ""}</span>
        <a href="#/config-manejo?secao=regras" data-ir="regras">${icone("ajustes")}Conferir</a></li>
      <li>${icone("calendario")}<span><b>Prazo para justificar:</b> ${esc(textoPrazo(Number(rasc.prazo_dia_util)).toLowerCase())}${quando}, até o fim do dia</span>
        <a href="#/config-manejo?secao=regras" data-ir="regras">${icone("ajustes")}Mudar</a></li>
      ${fora.length ? `<li class="aviso-nota">${icone("alerta")}<span><b>Sem ninguém para justificar:</b> ${esc(emLista(fora.map((v) => v.nome)))}.
        Os clientes ${fora.length === 1 ? "desse vendedor" : "desses vendedores"} iriam ao veredito sempre sem justificativa.</span>
        <a href="#/config-manejo?secao=usuarios" data-ir="usuarios">${icone("ajustes")}Resolver</a></li>` : ""}
    </ul>
    <p class="form-erro" id="cm-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#cm-ligada").addEventListener("click", () => {
    rasc.ligada = !rasc.ligada;
    mudou();
    secaoCampanha(alvo);
  });
  alvo.querySelectorAll("[data-ir]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    irPara(a.dataset.ir);
  }));
}

// ======================================================================================
// Quem justifica: quem vê a página e quem responde pelos clientes (os vendedores dele ficam em Usuários)
// ======================================================================================
function secaoUsuarios(alvo) {
  if (!usuarios.length) {
    alvo.innerHTML = `<section class="cartao usu-vazio entra" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div><h3>Ainda não há visualizadores</h3>
      <p>Cadastre as pessoas em <b>Usuários</b>; depois, aqui você escolhe quem vê a página e quem pode justificar.</p>
      <a class="btn primario" href="#/usuarios">${icone("escudo")}Abrir Usuários</a></section>`;
    return;
  }
  alvo.innerHTML = `
  <div class="usuarios cp-usuarios">
    <aside class="cartao usu-lista entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("escudo")}Visualizadores</h2>
        <p class="sub">Quem vê a página e quem pode justificar</p></div></div>
      <label class="campo sem-seta cp-busca-u"><span class="ic-campo">${icone("busca")}</span><input id="cm-busca-u" type="search" placeholder="Buscar pessoa" value="${esc(buscaUsuario)}"></label>
      <div class="usu-itens" id="cm-u-itens"></div>
      <div id="cm-cobertura"></div>
      <div class="dica">${icone("info")}<span>Nome, senha, páginas e os vendedores que cada pessoa vê (em todas as páginas)
        ficam em <a href="#/usuarios">Usuários</a>. Administradores veem todos os clientes e dão o veredito; eles não justificam.</span></div>
    </aside>
    <div id="cm-u-editor"></div>
  </div>`;
  alvo.querySelector("#cm-busca-u").addEventListener("input", (e) => { buscaUsuario = e.target.value; desenharItensUsuarios(); });
  desenharItensUsuarios();
  desenharEditorUsuario();
  desenharCobertura();
}

function desenharItensUsuarios() {
  const termo = buscaUsuario.trim().toLowerCase();
  const el = raiz.querySelector("#cm-u-itens");
  el.innerHTML = usuarios.filter((u) => !termo || `${u.nome} ${u.login}`.toLowerCase().includes(termo)).map((u, i) => {
    const a = acessos[u.login];
    return `<button type="button" class="usu-item ${u.login === usuarioSel ? "selecionado" : ""} ${a.ve ? "" : "inativo"}" data-login="${esc(u.login)}" style="--i:${i}">
      <span class="avatar">${esc(iniciais(u.nome))}</span>
      <span class="t"><b>${esc(u.nome)}${usuarioMudou(u.login) ? " <em>(alterado)</em>" : ""}</b><small>${esc(u.login)} · ${esc(resumoCurtoAcesso(u))}</small></span>
      <span class="chip-papel ${a.ve ? (a.justifica ? "admin" : "") : "inativo"}">${a.ve ? (a.justifica ? "Justifica" : "Consulta") : "Não vê"}</span>
    </button>`;
  }).join("") || `<p class="usu-nota">${icone("busca")}Ninguém com esse nome.</p>`;
  el.querySelectorAll(".usu-item").forEach((b) => b.addEventListener("click", () => {
    if (usuarioSel === b.dataset.login) return;
    usuarioSel = b.dataset.login;
    desenharItensUsuarios();
    desenharEditorUsuario();
  }));
}

// O aviso dos vendedores da campanha que ficaram sem ninguém para justificar (com o que está marcado agora).
function desenharCobertura() {
  const el = raiz.querySelector("#cm-cobertura");
  if (!el) return;
  const fora = semJustificador();
  el.innerHTML = fora.length
    ? `<p class="usu-nota aviso-nota cm-cobertura">${icone("alerta")}<span><b>Sem ninguém para justificar:</b> ${esc(emLista(fora.map((v) => v.nome)))}.
        Os clientes ${fora.length === 1 ? "desse vendedor" : "desses vendedores"} iriam ao veredito sempre sem justificativa.</span></p>`
    : `<p class="usu-nota cm-cobertura">${icone("certo")}<span>Todos os vendedores da campanha têm alguém para justificar.</span></p>`;
}

function desenharEditorUsuario() {
  const alvo = raiz.querySelector("#cm-u-editor");
  const u = usuarios.find((x) => x.login === usuarioSel);
  if (!u) { alvo.innerHTML = ""; return; }
  const a = acessos[u.login];
  const outras = (u.paginas || []).filter((p) => p !== "manejo");
  const alc = alcance(u), total = comClientes().length;
  const semAcesso = a.ve && a.justifica && !alc.length;
  alvo.innerHTML = `
  <section class="cartao usu-editor entra" style="--i:2">
    <div class="cartao-cab"><div>
      <h2>${icone("loja")}Manejo da Base de ${esc(u.nome)}</h2>
      <p class="sub">${esc(u.login)}${u.ativo === false ? " · acesso desativado em Usuários" : ""}</p>
    </div></div>
    <div class="opcao-linha">
      <button class="chave ${a.ve ? "ligada" : ""}" id="cm-u-ve" type="button" role="switch" aria-checked="${a.ve}" aria-label="Vê a página Manejo da Base"></button>
      <div><b>Vê a página Manejo da Base</b><p>${a.ve ? "A página aparece na barra lateral desta pessoa." : "Desligado, a página some da barra lateral e o servidor não manda as listas."}
        ${!outras.length && a.ve ? " É a única página dela: para tirar, libere outra antes em Usuários." : ""}</p></div>
    </div>
    <div class="opcao-linha">
      <button class="chave ${a.ve && a.justifica ? "ligada" : ""}" id="cm-u-justifica" type="button" role="switch" aria-checked="${a.ve && a.justifica}"
        aria-label="Pode justificar" ${a.ve ? "" : "disabled"}></button>
      <div><b>Pode justificar</b><p>${!a.ve ? "Só quem vê a página pode justificar."
        : a.justifica ? "Responde, até o prazo do mês, pelos clientes dos vendedores do acesso dela: se pode seguir a sugestão ou se o cliente deve continuar como está."
        : "Desligado, a pessoa só consulta as listas e o histórico."}</p></div>
    </div>
    <p class="usu-nota ${u.escopo && !semAcesso ? "" : "aviso-nota"}">${icone(u.escopo && !semAcesso ? "pessoas" : "alerta")}<span>Na página, ${esc(u.nome)} vê os clientes de
      <b>${esc(textoVendedores(u))}</b>, como está em <a href="#/usuarios">Usuários</a> (vale para todas as páginas): ${
        alc.length ? `${alc.length === total ? "todos os" : `${fmt.num(alc.length)} dos`} ${plural(total, "vendedor", "vendedores")} da campanha` : "nenhum vendedor da campanha"}.</span></p>
    <div class="usu-resumo" id="cm-u-resumo"></div>
    <p class="form-erro" id="cm-u-erro" role="alert" hidden></p>
  </section>`;
  alvo.querySelector("#cm-u-ve").addEventListener("click", () => {
    a.ve = !a.ve;
    if (!a.ve) a.justifica = false;
    aoMudarAcesso();
  });
  alvo.querySelector("#cm-u-justifica").addEventListener("click", () => {
    if (!a.ve) return;
    a.justifica = !a.justifica;
    aoMudarAcesso();
  });
  atualizarResumoUsuario(u);
}

function aoMudarAcesso() {
  mexeu = true;
  desenharItensUsuarios();
  desenharEditorUsuario();
  desenharCobertura();
  atualizarBarra();
}

function atualizarResumoUsuario(u) {
  const el = raiz.querySelector("#cm-u-resumo");
  if (!el) return;
  const a = acessos[u.login], quem = `<b>${esc(u.nome)}</b>`, alc = alcance(u);
  let txt;
  if (!a.ve) txt = `${quem} não vê a página Manejo da Base.`;
  else if (!a.justifica) txt = `${quem} só consulta as listas e o histórico dos clientes de ${esc(textoVendedores(u))}.`;
  else if (!alc.length) txt = `${quem} está marcada para justificar, mas nenhum vendedor da campanha está no acesso dela: não terá clientes para responder. Acerte os vendedores em Usuários.`;
  else txt = `${quem} justifica os clientes de ${alc.length <= 4 ? esc(emLista(alc.map((v) => v.nome))) : `${fmt.num(alc.length)} vendedores da campanha`} até o prazo de cada mês.`;
  el.innerHTML = `${icone("olho")}<span>${txt}</span>`;
}

// ======================================================================================
// Regras: os dias, o dia do prazo e os vendedores da central
// ======================================================================================
function secaoRegras(alvo) {
  const p = dados.prazo;
  const notaPrazo = () => (p && dataComSemana(p.data) && String(rasc.prazo_dia_util) === String(orig.prazo_dia_util)
    ? `Na lista de ${esc(p.rotulo || "")}: <b>${dataComSemana(p.data)}</b>.` : "A data deste mês aparece depois de salvar.");
  const marcados = new Set(ordenados(rasc.central));
  // Quem está marcado e saiu das equipes do ES e da BA continua na lista, para dar para desmarcar.
  const conhecidos = new Set(dados.vendedores.map((v) => v.id));
  const fora = ordenados([...orig.central, ...rasc.central]).filter((id) => !conhecidos.has(id))
    .map((id) => ({ id, nome: nomesAcesso[id] || "Vendedor fora das equipes do ES e da BA", equipe: null, clientes: null, nome_central: true }));
  const lista = [...fora, ...dados.vendedores].sort((a, b) => (b.nome_central ? 1 : 0) - (a.nome_central ? 1 : 0)
    || String(a.equipe).localeCompare(String(b.equipe)) || String(a.nome).localeCompare(String(b.nome), "pt-BR"));
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("ajustes")}Dias de cada regra</h2>
      <p class="sub">Com quantos dias o cliente entra na lista. Os dias contam até o dia da cópia do banco; mudar um número vale na próxima atualização da lista</p></div></div>
    <div class="sug-regras">
      ${DIAS.map(([k, titulo, dica]) => `<label class="sug-campo"><span class="r"><b>${titulo}</b><small>${dica}</small></span>
        <span class="campo sem-seta"><input type="number" min="${MIN_DIAS}" max="${MAX_DIAS}" step="1" inputmode="numeric" data-dia="${k}"
          value="${esc(String(rasc.dias[k] ?? ""))}" aria-label="${esc(titulo)}, em dias"></span><em>dias</em></label>`).join("")}
    </div>

    <h3 class="usu-titulo">Prazo para justificar</h3>
    <label class="sug-campo cm-prazo"><span class="r"><b>Dia do prazo</b><small>O supervisor responde até o fim desse dia. Conta de segunda a sexta, sem os feriados
        do calendário do painel; se o ES e a BA derem dias diferentes, vale o mais cedo.</small></span>
      <span class="campo"><select id="cm-prazo" aria-label="Dia do prazo">
        ${Array.from({ length: MAX_PRAZO }, (_, i) => i + 1).map((n) => `<option value="${n}"${Number(rasc.prazo_dia_util) === n ? " selected" : ""}>${esc(textoPrazo(n))}</option>`).join("")}
      </select></span></label>
    <p class="usu-nota" id="cm-prazo-nota">${icone("calendario")}<span>${notaPrazo()}</span></p>

    <h3 class="usu-titulo">Vendedores da central <small>os clientes deles não entram em “passar para a central”; entram em “inativar” quando param de comprar</small></h3>
    ${sugeriuCentral ? `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Ainda não há central salva: os vendedores com CENTRAL no nome vieram marcados como sugestão. Confira e salve.</span></p>` : ""}
    <div class="vend-escolha cm-central">${lista.map((v) => `
      <label class="vend-op">
        <input type="checkbox" data-central="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">${esc(v.nome)}<small>${v.equipe ? `equipe ${esc(NOME_EQUIPE[v.equipe] || v.equipe)}` : "sem equipe"}${
          v.clientes != null ? ` · ${plural(v.clientes, "cliente ativo", "clientes ativos")}` : ""}</small></span>
      </label>`).join("") || `<p class="usu-nota">${icone("info")}A lista de vendedores aparece depois da primeira cópia do banco do ERP.</p>`}</div>
    <p class="usu-nota" id="cm-central-n"></p>

    <p class="form-erro" id="cm-erro" role="alert" hidden></p>
    <div class="sug-regras-acoes"><button class="btn" type="button" id="cm-padrao">${icone("restaurar")}Voltar os dias e o prazo ao padrão da campanha</button></div>
  </section>`;
  alvo.querySelectorAll("[data-dia]").forEach((inp) => inp.addEventListener("input", () => {
    rasc.dias[inp.dataset.dia] = inp.value.trim();
    mudou();
  }));
  alvo.querySelector("#cm-prazo").addEventListener("change", (e) => {
    rasc.prazo_dia_util = Number(e.target.value);
    mudou();
    alvo.querySelector("#cm-prazo-nota span").innerHTML = notaPrazo();
  });
  const contarCentral = () => {
    const n = rasc.central.length;
    alvo.querySelector("#cm-central-n").innerHTML = n ? `${icone("enviar")}<span>A central: <b>${esc(emLista(nomesCentral()))}</b>.</span>`
      : `${icone("alerta")}<span class="aviso-nota">Nenhum vendedor marcado: sem a central, a campanha não pode ser ligada.</span>`;
  };
  alvo.querySelectorAll("[data-central]").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(rasc.central);
    c.checked ? ids.add(Number(c.dataset.central)) : ids.delete(Number(c.dataset.central));
    rasc.central = ordenados([...ids]);
    contarCentral();
    mudou();
  }));
  alvo.querySelector("#cm-padrao").addEventListener("click", () => {
    const pad = normal(dados.padrao);
    rasc.dias = { ...pad.dias };
    rasc.prazo_dia_util = pad.prazo_dia_util;
    mexeu = true;
    toast("Dias e prazo no padrão da campanha; a central e quem justifica ficam como estão. Confira e salve");
    renderSecao();
  });
  contarCentral();
}

// ---------- gravação ----------
// O que impede de salvar as regras (null = pode). O servidor confere de novo.
function erroRegras() {
  for (const [k, titulo] of DIAS) {
    const v = Number(rasc.dias[k]);
    if (String(rasc.dias[k]).trim() === "" || !Number.isInteger(v) || v < MIN_DIAS || v > MAX_DIAS) {
      return ["regras", `${titulo}: digite um número inteiro de ${MIN_DIAS} a ${MAX_DIAS} dias.`];
    }
  }
  const prazo = Number(rasc.prazo_dia_util);
  if (!Number.isInteger(prazo) || prazo < 1 || prazo > MAX_PRAZO) return ["regras", "Escolha o dia do prazo."];
  if (rasc.ligada && !rasc.central.length) return ["regras", "Marque ao menos um vendedor da central antes de ligar a campanha."];
  return null;
}

async function salvar() {
  const regras = contarAlteracoesRegras() > 0, mudados = usuariosMudados();
  if (regras) {
    const e = erroRegras();
    if (e) {
      if (secao !== e[0]) irPara(e[0]);
      return erro(e[1]);
    }
  }
  for (const u of mudados) {
    const msg = erroAcesso(u);
    if (msg) {
      secao = "usuarios";
      usuarioSel = u.login;
      render();
      return erro(`${u.nome}: ${msg}.`, "#cm-u-erro");
    }
  }
  // Só vai o que mudou: sem regras novas, o servidor não grava outra versão delas.
  const corpo = {};
  if (regras) {
    corpo.config = {
      versao: rasc.versao, ligada: rasc.ligada,
      dias: Object.fromEntries(DIAS.map(([k]) => [k, Number(rasc.dias[k])])),
      prazo_dia_util: Number(rasc.prazo_dia_util), central: ordenados(rasc.central),
    };
  }
  if (mudados.length) {
    corpo.usuarios = Object.fromEntries(mudados.map((u) => [u.login, { ve: acessos[u.login].ve, justifica: acessos[u.login].ve && acessos[u.login].justifica }]));
  }
  const ligou = regras && rasc.ligada && !orig.ligada, desligou = regras && !rasc.ligada && orig.ligada;
  const btn = raiz.querySelector("#cm-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/manejo/config", { json: corpo }));
    toast(ligou ? "Campanha ligada: a lista do mês já está sendo montada" : desligou ? "Campanha desligada: as listas param de ser atualizadas"
      : regras && mudados.length ? "Regras e acessos do manejo salvos" : regras ? "Regras do manejo salvas" : "Quem justifica: salvo");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    erro(e.message, secao === "usuarios" ? "#cm-u-erro" : "#cm-erro");
  } finally {
    btn.disabled = false;
  }
}
