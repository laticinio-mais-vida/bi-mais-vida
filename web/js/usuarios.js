// Página Usuários (só administradores): quem entra no painel (nome, usuário, senha, papel), quais páginas cada um vê
// e quais vendedores ele vê em todas elas (inclusive no Assistente, na API pública e no Crédito): todos, os das equipes
// marcadas (os que entrarem depois também) ou só alguns. O que é próprio de uma página (as abas de Metas, as abas e os
// supervisores de Premiações) fica no Configurar dela; aqui aparece só o resumo, com o link. Quem barra é o servidor, a
// página só monta o cadastro.
import { api, esc, fmt, icone, toast } from "./util.js";
import { PAPEL, iniciais } from "./conta.js";

const ICONE_PAGINA = { metas: "alvo", projecoes: "tendencia", sugestao: "foguete", premiacoes: "trofeu", devolucoes: "devolucao", assistente: "conversa", gestao: "quadro", credito: "cartao" };
const DESCRICAO_PAGINA = {
  metas: "Metas do mês por vendedor e produto",
  projecoes: "Faturamento previsto para 6 meses",
  sugestao: "Meta do mês seguinte sugerida por vendedor e produto",
  premiacoes: "Prêmio do mês de cada vendedor e de cada supervisor, e a comissão dos vendedores",
  devolucoes: "O que voltou na entrega e o vencido e danificado no cliente, por causa, produto, cliente e vendedor, e o Parecer em PDF",
  assistente: "Perguntas sobre os dados, respondidas por IA",
  gestao: "Objetivos, campanhas e o histórico de cada vendedor",
  credito: "Limite, compras, pontualidade e títulos de cada cliente",
};
const MODOS = [
  { id: "todos", nome: "Todos os vendedores", icone: "pessoas" },
  { id: "equipes", nome: "Só as equipes", icone: "mapa" },
  { id: "alguns", nome: "Só alguns vendedores", icone: "usuario" },
];

let ctx = null, raiz = null;
let dados = null;     // { usuarios, paginas, equipes, visoes, vendedores, aviso_vendedores }
let sel = null;       // login em edição; "" = novo acesso; null = nenhum
let form = null, base = null;
let guardado = { equipes: [], vendedores: [] };  // o que estava marcado em cada modo, para trocar e voltar sem perder
let buscaVend = "";

const clone = (o) => JSON.parse(JSON.stringify(o));
const sujo = () => !!form && JSON.stringify(form) !== JSON.stringify(base);

export function usuariosTemAlteracoes() { return sujo(); }

export async function montarUsuarios(container, contexto) {
  ctx = contexto;
  raiz = container;
  if (dados && sujo()) { render(); return; }
  container.innerHTML = `<div class="usuarios"><div class="esqueleto" style="height:420px"></div><div class="esqueleto" style="height:560px"></div></div>`;
  try {
    dados = await api("/api/usuarios");
    if (sel && !dados.usuarios.some((u) => u.login === sel)) sel = null;
    abrir(sel);
    render(true);
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir os usuários: ${esc(e.message)}</p></div>`;
  }
}

// ---------- apoio ----------
function rascunho(u) {
  if (!u) return { login: "", nome: "", senha: "", papel: "visualizador", ativo: true, paginas: ["metas"], escopo: null };
  return { login: u.login, nome: u.nome, senha: "", papel: u.papel, ativo: u.ativo,
           paginas: u.paginas ? [...u.paginas] : ["metas"], escopo: u.escopo ? clone(u.escopo) : null };
}

function abrir(login) {
  sel = login;
  const u = login ? dados.usuarios.find((x) => x.login === login) : null;
  form = login === null ? null : rascunho(u);
  base = form && clone(form);
  guardado = { equipes: [...(form?.escopo?.equipes || [])], vendedores: [...(form?.escopo?.vendedores || [])] };
  buscaVend = "";
}

function trocarPara(login) {
  if (sel === login) return;
  if (sujo() && !confirm("Há alterações não salvas neste acesso. Descartar?")) return;
  abrir(login);
  render();
}

const ehEu = (login) => login && login === ctx.eu.login;
const tituloPagina = (id) => dados.paginas.find((p) => p.id === id)?.titulo || id;
const nomeEquipe = (id) => dados.equipes.find((e) => e.id === id)?.nome || id;
const nomeVendedor = (id) => dados.vendedores.find((v) => v.id === id)?.nome || `Vendedor ${id}`;
const tituloAba = (id) => dados.visoes.find((v) => v.id === id)?.titulo || id;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

// Os vendedores do acesso numa frase curta, para a lista de pessoas.
function textoEscopo(e) {
  if (!e) return "sem vendedores escolhidos";
  if (e.modo === "todos") return "todos os vendedores";
  if (e.modo === "equipes") return `${e.equipes.length === 1 ? "equipe" : "equipes"} ${emLista(e.equipes.map(nomeEquipe))}`;
  return plural(e.vendedores.length, "vendedor", "vendedores");
}

function resumoCurto(u) {
  return u.papel === "admin" ? "vê tudo" : emLista((u.paginas || []).map(tituloPagina));
}

// As equipes dos vendedores do acesso, para saber quais abas de Metas teriam alguém: null = todas; com "só alguns",
// só os vendedores com meta na planilha (como o servidor faz).
function equipesDoAcesso(e) {
  if (!e) return new Set();
  if (e.modo === "todos") return null;
  if (e.modo === "equipes") return new Set(e.equipes);
  const ids = new Set(e.vendedores);
  return new Set(dados.vendedores.filter((v) => ids.has(v.id) && v.com_meta).map((v) => v.equipe));
}

// A nota de Metas: as abas escolhidas em Metas › Configurar e as que somem por não ter nenhum vendedor do acesso.
function notaMetas(u, f) {
  if (!u) return { pagina: "metas", aviso: true, texto: "depois de criar o acesso, escolha as abas em Metas › Configurar; até isso, a página fica vazia para ela" };
  const link = `#/configuracoes?u=${encodeURIComponent(u.login)}`;
  const abas = u.papel !== "admin" ? u.visoes || [] : [];
  if (!abas.length) return { pagina: "metas", aviso: true, link, texto: "ainda sem abas: a página fica vazia até você escolher" };
  const eq = equipesDoAcesso(f.escopo);
  const temAlguem = (id) => eq === null || (dados.visoes.find((v) => v.id === id)?.grupos || []).some((g) => eq.has(g));
  const vistas = abas.filter(temAlguem), somem = abas.filter((id) => !temAlguem(id));
  if (!vistas.length) {
    return { pagina: "metas", aviso: true, link, texto: `nenhuma das abas escolhidas (${emLista(abas.map(tituloAba))}) tem vendedor do acesso: a página fica vazia para ela` };
  }
  const fora = somem.length ? `; ${emLista(somem.map(tituloAba))} não aparece${somem.length > 1 ? "m" : ""} (nenhum vendedor do acesso)` : "";
  return { pagina: "metas", link, texto: `${vistas.length === 1 ? "aba" : "abas"} ${emLista(vistas.map(tituloAba))}${fora}` };
}

const TITULO_ABA_PREMIACOES = { vendedores: "Vendedores", supervisores: "Supervisores", comissao: "Comissão" };

// A nota de Premiações: as abas e os quadros de supervisor escolhidos em Premiações › Configurar e o que some por causa
// dos vendedores do acesso (o quadro de um supervisor soma a carteira inteira do estado dele).
function notaPremiacoes(u, f) {
  if (!u) return { pagina: "premiacoes", aviso: true, texto: "depois de criar o acesso, escolha as abas em Premiações › Configurar; até isso, a página fica vazia para ela" };
  const link = `#/config-premiacoes?u=${encodeURIComponent(u.login)}`;
  const p = u.papel !== "admin" ? u.premiacoes : null;
  const abas = p?.abas || [];
  if (!abas.length) return { pagina: "premiacoes", aviso: true, link, texto: "ainda sem abas: a página fica vazia até você escolher" };
  const e = f.escopo;
  const estados = !e || e.modo === "alguns" ? new Set() : e.modo === "todos" ? null : new Set(e.equipes);
  const quadros = (dados.supervisores_premiacoes || [])
    .filter((s) => (p.supervisores || []).includes(s.id) && (estados === null || estados.has(s.estado)));
  const vistas = abas.filter((a) => a !== "supervisores" || quadros.length);
  if (!vistas.length) return { pagina: "premiacoes", aviso: true, link, texto: "os quadros de supervisor escolhidos ficam fora dos vendedores do acesso: a página fica vazia para ela" };
  const sups = vistas.includes("supervisores") ? ` (${quadros.length === 1 ? "o quadro" : "os quadros"} de ${emLista(quadros.map((s) => s.nome))})` : "";
  const fora = abas.includes("supervisores") && !vistas.includes("supervisores") ? "; Supervisores não aparece (soma a carteira inteira do estado)" : "";
  return { pagina: "premiacoes", link, texto: `${vistas.length === 1 ? "aba" : "abas"} ${emLista(vistas.map((a) => TITULO_ABA_PREMIACOES[a]))}${sups}${fora}` };
}

// O que muda de uma página para outra (o resto é igual em todas: só os vendedores do acesso). u: o cadastro salvo
// (as abas de Metas e de Premiações vêm dele); f: o formulário.
function notasDasPaginas(u, f) {
  const e = f.escopo;
  const notas = [];
  if (f.paginas.includes("metas")) notas.push(notaMetas(u, f));
  if (f.paginas.includes("premiacoes")) notas.push(notaPremiacoes(u, f));
  if (f.paginas.includes("devolucoes") && e?.modo === "todos") notas.push({ pagina: "devolucoes", texto: "inclusive os terceirizados (vendedores sem equipe)" });
  if (f.paginas.includes("credito") && e && e.modo !== "todos") notas.push({ pagina: "credito", texto: "só os clientes da carteira desses vendedores ou com títulos deles" });
  return notas;
}

function resumoCompleto(f) {
  const quem = esc(f.nome.trim() || "Esta pessoa");
  if (f.papel === "admin") {
    return `<b>${quem}</b> vê todas as páginas, abas e vendedores, e pode mudar as configurações e os acessos.`;
  }
  if (!f.paginas.length) return "Marque ao menos uma página para este acesso.";
  const paginas = emLista(f.paginas.map((p) => `<b>${esc(tituloPagina(p))}</b>`));
  const e = f.escopo;
  let vend;
  if (!e) vend = ", mas <b>nenhum vendedor</b> até você escolher quais ela vê";
  else if (e.modo === "todos") vend = ", com <b>todos os vendedores</b>";
  else if (e.modo === "equipes") {
    vend = e.equipes.length ? `, só com os vendedores ${e.equipes.length === 1 ? "da equipe" : "das equipes"} ${emLista(e.equipes.map((q) => `<b>${esc(nomeEquipe(q))}</b>`))}`
      : ", mas falta marcar as equipes";
  } else if (!e.vendedores.length) vend = ", mas falta marcar os vendedores";
  else if (e.vendedores.length <= 3) vend = `, só com ${emLista(e.vendedores.map((v) => `<b>${esc(nomeVendedor(v))}</b>`))}`;
  else vend = `, só com <b>${e.vendedores.length} vendedores</b>`;
  const txt = `<b>${quem}</b> vai ver a${f.paginas.length > 1 ? "s páginas" : " página"} ${paginas}${vend}.`;
  return txt + (f.ativo ? "" : " <b>O acesso está desativado:</b> a pessoa não consegue entrar.");
}

function gerarSenha() {
  const letras = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from(crypto.getRandomValues(new Uint32Array(10)), (n) => letras[n % letras.length]).join("");
}

// ---------- estrutura ----------
function render(primeira = false) {
  raiz.innerHTML = `
  <div class="usuarios">
    <aside class="cartao usu-lista ${primeira ? "entra" : ""}" style="--i:0">
      <div class="cartao-cab"><div>
        <h2>${icone("escudo")}Acessos</h2>
        <p class="sub" id="u-contagem"></p>
      </div>
      <button class="btn primario" id="u-novo" type="button">${icone("mais")}Novo</button></div>
      <div class="usu-itens" id="u-itens"></div>
      <div class="dica">${icone("info")} Quem não é administrador recebe do servidor só os números liberados para ele, mesmo se mexer no endereço da página.</div>
    </aside>
    <div id="u-editor"></div>
  </div>`;
  raiz.querySelector("#u-novo").addEventListener("click", () => trocarPara(""));
  desenharLista();
  desenharEditor(primeira);
}

function desenharLista() {
  const us = dados.usuarios;
  const admins = us.filter((u) => u.papel === "admin").length;
  raiz.querySelector("#u-contagem").textContent =
    `${us.length} ${us.length === 1 ? "pessoa" : "pessoas"} · ${admins} administrador${admins === 1 ? "" : "es"}`;
  raiz.querySelector("#u-itens").innerHTML = us.map((u, i) => `
    <button type="button" class="usu-item ${u.login === sel ? "selecionado" : ""} ${u.ativo ? "" : "inativo"}" data-login="${esc(u.login)}" style="--i:${i}">
      <span class="avatar ${u.papel}">${esc(iniciais(u.nome))}</span>
      <span class="t"><b>${esc(u.nome)}${ehEu(u.login) ? ' <em>(você)</em>' : ""}</b>
        <small>${esc(u.login)} · ${u.papel === "admin" ? "" : `<span class="${u.escopo ? "" : "aviso-nota"}">${esc(textoEscopo(u.escopo))}</span> · `}${esc(resumoCurto(u))}</small></span>
      <span class="chip-papel ${u.ativo ? u.papel : "inativo"}">${u.ativo ? PAPEL[u.papel] : "Desativado"}</span>
    </button>`).join("");
  raiz.querySelectorAll(".usu-item").forEach((b) => b.addEventListener("click", () => trocarPara(b.dataset.login)));
}

function desenharEditor(primeira = false) {
  const alvo = raiz.querySelector("#u-editor");
  const classe = primeira ? "entra" : "";
  if (form === null) {
    alvo.innerHTML = `
    <section class="cartao usu-editor usu-vazio ${classe}" style="--i:1">
      <div class="usu-vazio-ic">${icone("escudo")}</div>
      <h3>Escolha um acesso ou crie um novo</h3>
      <p>Aqui ficam o nome, o usuário, a senha, as <b>páginas</b> de cada pessoa e os <b>vendedores</b> que ela vê, em
        todas as páginas. As abas de Metas ficam em <b>Metas › Configurar</b>, e as de Premiações, em
        <b>Premiações › Configurar</b>.</p>
      <button class="btn primario" id="u-novo2" type="button">${icone("mais")}Novo acesso</button>
    </section>`;
    alvo.querySelector("#u-novo2").addEventListener("click", () => trocarPara(""));
    return;
  }
  const novo = sel === "";
  const eu = ehEu(sel);
  const u = dados.usuarios.find((x) => x.login === sel);
  alvo.innerHTML = `
  <section class="cartao usu-editor ${classe}" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone(novo ? "mais" : "lapis")}${novo ? "Novo acesso" : `Acesso de ${esc(u.nome)}`}</h2>
      <p class="sub">${novo ? "Crie o usuário e a senha e passe para a pessoa. Ela pode trocar a senha depois, no menu com o nome dela."
        : `Criado em ${u.criado_em ? fmt.dataHora(u.criado_em) : "—"} · ${u.ultimo_acesso ? `último acesso em ${fmt.dataHora(u.ultimo_acesso)}` : "ainda não entrou"}`}</p>
    </div></div>

    <div class="usu-grade">
      <label class="campo-form"><span>Nome</span>
        <input id="u-nome" type="text" value="${esc(form.nome)}" placeholder="ex.: João da Silva" autocomplete="off"></label>
      <label class="campo-form"><span>Usuário (para entrar)</span>
        <input id="u-login" type="text" value="${esc(form.login)}" placeholder="ex.: joao.silva" autocomplete="off" autocapitalize="none" spellcheck="false"></label>
      <label class="campo-form largo"><span>${novo ? "Senha" : "Nova senha"}</span>
        <span class="com-botao">
          <input id="u-senha" type="password" value="${esc(form.senha)}" autocomplete="new-password"
            placeholder="${novo ? "Mínimo 6 caracteres" : "Deixe em branco para manter a senha atual"}">
          <button class="btn" type="button" id="u-gerar" title="Criar uma senha aleatória">${icone("raio")}Gerar</button>
        </span>
        ${novo ? "" : "<small>Trocar a senha desconecta a pessoa dos aparelhos em que ela estiver.</small>"}
      </label>
    </div>

    <h3 class="usu-titulo">Papel</h3>
    <div class="papeis">
      ${[["visualizador", "olho", "Vê só as páginas e os vendedores que você liberar."],
         ["admin", "escudo", "Vê tudo, muda as configurações das páginas e cadastra acessos."]].map(([p, ic, txt]) => `
        <button type="button" class="papel-op ${form.papel === p ? "ativo" : ""}" data-papel="${p}" aria-pressed="${form.papel === p}" ${eu ? "disabled" : ""}>
          <span class="papel-ic">${icone(ic)}</span><span><b>${PAPEL[p]}</b><small>${txt}</small></span>
        </button>`).join("")}
    </div>
    ${eu ? `<p class="usu-nota">${icone("info")}Você não pode tirar o seu próprio acesso de administrador.</p>` : ""}

    <div id="u-permissoes"></div>

    <div class="opcao-linha usu-ativo">
      <button class="chave ${form.ativo ? "ligada" : ""}" id="u-ativo" type="button" role="switch" aria-checked="${form.ativo}" aria-label="Acesso ativo" ${eu ? "disabled" : ""}></button>
      <div><b>Acesso ativo</b><p>Desativado, a pessoa não consegue entrar e as sessões abertas são encerradas. O cadastro fica guardado.</p></div>
    </div>

    <div class="usu-resumo" id="u-resumo"></div>
    <p class="form-erro" id="u-erro" role="alert" hidden></p>

    <div class="usu-acoes">
      ${!novo && !eu ? `<button class="btn perigo" type="button" id="u-excluir">${icone("lixeira")}Excluir</button>` : ""}
      <span class="espaco"></span>
      <button class="btn" type="button" id="u-cancelar">${novo ? "Cancelar" : "Desfazer"}</button>
      <button class="btn primario" type="button" id="u-salvar">${icone("disco")}${novo ? "Criar acesso" : "Salvar"}</button>
    </div>
  </section>`;

  const texto = (id, chave, transforma = (v) => v) => alvo.querySelector(id).addEventListener("input", (e) => {
    form[chave] = transforma(e.target.value);
    atualizarResumo();
  });
  texto("#u-nome", "nome");
  texto("#u-login", "login", (v) => v.trim().toLowerCase());
  texto("#u-senha", "senha");
  alvo.querySelector("#u-gerar").addEventListener("click", async () => {
    const input = alvo.querySelector("#u-senha");
    form.senha = gerarSenha();
    input.type = "text";
    input.value = form.senha;
    input.select();
    let copiou = false;
    try { await navigator.clipboard.writeText(form.senha); copiou = true; } catch { /* sem área de transferência */ }
    toast(copiou ? "Senha gerada e copiada. Passe para a pessoa antes de salvar." : "Senha gerada. Anote e passe para a pessoa antes de salvar.");
    atualizarResumo();
  });
  alvo.querySelectorAll(".papel-op").forEach((b) => b.addEventListener("click", () => {
    form.papel = b.dataset.papel;
    alvo.querySelectorAll(".papel-op").forEach((x) => { x.classList.toggle("ativo", x === b); x.setAttribute("aria-pressed", x === b); });
    desenharPermissoes();
  }));
  alvo.querySelector("#u-ativo").addEventListener("click", (e) => {
    form.ativo = !form.ativo;
    e.currentTarget.classList.toggle("ligada", form.ativo);
    e.currentTarget.setAttribute("aria-checked", form.ativo);
    atualizarResumo();
  });
  alvo.querySelector("#u-cancelar").addEventListener("click", () => {
    if (novo) { abrir(null); render(); return; }
    abrir(sel);
    desenharEditor();
  });
  alvo.querySelector("#u-salvar").addEventListener("click", salvar);
  alvo.querySelector("#u-excluir")?.addEventListener("click", excluir);
  desenharPermissoes();
  if (novo) alvo.querySelector("#u-nome").focus();
}

function desenharPermissoes() {
  const alvo = raiz.querySelector("#u-permissoes");
  if (form.papel === "admin") { alvo.innerHTML = ""; atualizarResumo(); return; }
  const idx = MODOS.findIndex((m) => m.id === form.escopo?.modo);
  alvo.innerHTML = `
    <h3 class="usu-titulo">Páginas que pode ver</h3>
    <div class="visoes-escolha paginas-escolha">
      ${dados.paginas.map((p) => {
        const on = form.paginas.includes(p.id);
        return `<button type="button" class="visao-op ${on ? "ativo" : ""}" data-pagina="${p.id}" aria-pressed="${on}">
          <span class="marca-caixa">${icone("visto")}</span>${icone(ICONE_PAGINA[p.id] || "alvo")}
          <span><b>${esc(p.titulo)}</b><small>${esc(DESCRICAO_PAGINA[p.id] || "")}</small></span>
        </button>`;
      }).join("")}
    </div>
    <h3 class="usu-titulo">Vendedores que vê <small>vale para todas as páginas, inclusive o Assistente e o Crédito</small></h3>
    <div class="seletor cp-modo" data-v="${idx}" role="radiogroup" aria-label="Vendedores que vê"><span class="marcador"></span>
      ${MODOS.map((m) => `<button type="button" role="radio" data-modo="${m.id}" aria-checked="${m.id === form.escopo?.modo}" class="${m.id === form.escopo?.modo ? "ativo" : ""}">${icone(m.icone)}${m.nome}</button>`).join("")}
    </div>
    <div id="u-escopo"></div>
    <ul class="usu-dentro" id="u-dentro"></ul>`;
  alvo.querySelectorAll(".visao-op[data-pagina]").forEach((b) => b.addEventListener("click", () => {
    const marcadas = new Set(form.paginas);
    marcadas.has(b.dataset.pagina) ? marcadas.delete(b.dataset.pagina) : marcadas.add(b.dataset.pagina);
    form.paginas = dados.paginas.map((p) => p.id).filter((id) => marcadas.has(id));
    b.classList.toggle("ativo", marcadas.has(b.dataset.pagina));
    b.setAttribute("aria-pressed", marcadas.has(b.dataset.pagina));
    desenharNotas();
    atualizarResumo();
  }));
  alvo.querySelectorAll(".cp-modo button").forEach((b) => b.addEventListener("click", () => {
    const modo = b.dataset.modo;
    if (form.escopo?.modo === modo) return;
    form.escopo = modo === "todos" ? { modo } : modo === "equipes" ? { modo, equipes: [...guardado.equipes] }
      : { modo, vendedores: [...guardado.vendedores] };
    const seletor = alvo.querySelector(".cp-modo");
    seletor.dataset.v = MODOS.findIndex((m) => m.id === modo);
    seletor.querySelectorAll("button").forEach((x) => { x.classList.toggle("ativo", x === b); x.setAttribute("aria-checked", x === b); });
    desenharEscopo();
    desenharNotas();
    atualizarResumo();
  }));
  desenharEscopo();
  desenharNotas();
  atualizarResumo();
}

// O detalhe do modo escolhido: as equipes, a lista de vendedores ou só a explicação.
function desenharEscopo() {
  const alvo = raiz.querySelector("#u-escopo");
  const e = form.escopo;
  if (!e) {
    alvo.innerHTML = `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Escolha quais vendedores a pessoa vê. Até isso, ela não vê
      nenhum vendedor em nenhuma página.</span></p>`;
    return;
  }
  if (e.modo === "todos") {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Vê qualquer vendedor, inclusive os sem equipe (terceirizados) e os que
      entrarem depois.</span></p>`;
    return;
  }
  if (e.modo === "equipes") return desenharEquipes();
  desenharEscolha();
}

function desenharEquipes() {
  const alvo = raiz.querySelector("#u-escopo");
  const e = form.escopo;
  const quantos = (id) => dados.vendedores.filter((v) => v.equipe === id).length;
  alvo.innerHTML = `
    <div class="visoes-escolha equipes-escolha">
      ${dados.equipes.map((q) => {
        const on = e.equipes.includes(q.id);
        const n = quantos(q.id);
        return `<button type="button" class="visao-op ${on ? "ativo" : ""}" data-equipe="${esc(q.id)}" aria-pressed="${on}">
          <span class="marca-caixa">${icone("visto")}</span>${icone(q.id === "EDIR" ? "usuario" : "mapa")}
          <span><b>${esc(q.nome)}</b><small>${dados.vendedores.length ? plural(n, "vendedor hoje", "vendedores hoje") : "equipe"}</small></span>
        </button>`;
      }).join("")}
    </div>
    <p class="usu-nota">${icone("info")}<span>Vendedor novo dessas equipes entra sozinho. A equipe de cada vendedor fica em
      <a href="#/configuracoes?secao=vendedores">Metas › Configurar › Vendedores</a>.</span></p>`;
  alvo.querySelectorAll(".visao-op[data-equipe]").forEach((b) => b.addEventListener("click", () => {
    const marcadas = new Set(e.equipes);
    marcadas.has(b.dataset.equipe) ? marcadas.delete(b.dataset.equipe) : marcadas.add(b.dataset.equipe);
    e.equipes = dados.equipes.map((q) => q.id).filter((id) => marcadas.has(id));
    guardado.equipes = [...e.equipes];
    b.classList.toggle("ativo", marcadas.has(b.dataset.equipe));
    b.setAttribute("aria-pressed", marcadas.has(b.dataset.equipe));
    desenharNotas();
    atualizarResumo();
  }));
}

function desenharEscolha() {
  const alvo = raiz.querySelector("#u-escopo");
  const e = form.escopo;
  const marcados = new Set(e.vendedores);
  const conhecidos = new Set(dados.vendedores.map((v) => v.id));
  // marcados que não estão mais na lista (sem venda em 12 meses) continuam aparecendo, para poder desmarcar
  const lista = [...dados.vendedores, ...e.vendedores.filter((id) => !conhecidos.has(id))
    .map((id) => ({ id, nome: `Vendedor ${id}`, nome_erp: "", rotulo_equipe: "sem venda em 12 meses" }))];
  alvo.innerHTML = `
    ${dados.aviso_vendedores ? `<p class="usu-nota aviso-nota">${icone("alerta")}<span>${esc(dados.aviso_vendedores)}</span></p>` : ""}
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="u-busca-v" type="search" placeholder="Buscar vendedor ou código" value="${esc(buscaVend)}"></label>
      <span class="usu-cont" id="u-cont"></span>
      <button class="btn" type="button" id="u-marcar">Marcar os da lista</button>
      <button class="btn" type="button" id="u-desmarcar">Desmarcar todos</button>
    </div>
    <div class="vend-escolha">${lista.map((v) => `
      <label class="vend-op ${v.inativo ? "antigo" : ""}" data-busca="${esc(`${v.nome} ${v.nome_erp} ${v.id} ${v.rotulo_equipe}`.toLowerCase())}">
        <input type="checkbox" data-id="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
        <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(v.rotulo_equipe)}${v.venda_12m ? ` · ${fmt.moedaC(v.venda_12m)} em 12 meses`
          : conhecidos.has(v.id) ? " · ainda sem venda" : ""}${v.inativo ? " · inativo no ERP" : ""}</small></span>
      </label>`).join("")}</div>`;
  const filtrar = () => {
    const termo = buscaVend.trim().toLowerCase();
    alvo.querySelectorAll(".vend-op").forEach((el) => { el.hidden = !!termo && !el.dataset.busca.includes(termo); });
  };
  const contar = () => {
    const n = e.vendedores.length;
    alvo.querySelector("#u-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
  };
  const definir = (ids) => {
    e.vendedores = [...ids].sort((a, b) => a - b);
    guardado.vendedores = [...e.vendedores];
    alvo.querySelectorAll(".vend-op input").forEach((c) => { c.checked = ids.has(Number(c.dataset.id)); });
    contar();
    desenharNotas();
    atualizarResumo();
  };
  alvo.querySelector("#u-busca-v").addEventListener("input", (ev) => { buscaVend = ev.target.value; filtrar(); });
  alvo.querySelectorAll(".vend-op input").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(e.vendedores);
    c.checked ? ids.add(Number(c.dataset.id)) : ids.delete(Number(c.dataset.id));
    definir(ids);
  }));
  alvo.querySelector("#u-marcar").addEventListener("click", () => {
    const ids = new Set(e.vendedores);
    alvo.querySelectorAll(".vend-op:not([hidden]) input").forEach((c) => ids.add(Number(c.dataset.id)));
    definir(ids);
  });
  alvo.querySelector("#u-desmarcar").addEventListener("click", () => definir(new Set()));
  filtrar();
  contar();
}

function desenharNotas() {
  const el = raiz.querySelector("#u-dentro");
  if (!el) return;
  const u = dados.usuarios.find((x) => x.login === sel);
  const notas = notasDasPaginas(u, form);
  el.hidden = !notas.length;
  el.innerHTML = notas.map((d) => `<li class="${d.aviso ? "aviso-nota" : ""}">${icone(d.aviso ? "alerta" : ICONE_PAGINA[d.pagina] || "alvo")}
      <span><b>${esc(tituloPagina(d.pagina))}:</b> ${esc(d.texto)}</span>
      ${d.link ? `<a href="${esc(d.link)}">${icone("ajustes")}Configurar</a>` : ""}</li>`).join("");
}

function atualizarResumo() {
  const el = raiz.querySelector("#u-resumo");
  if (el) el.innerHTML = `${icone("olho")}<span>${resumoCompleto(form)}</span>`;
}

// ---------- gravação ----------
function mostrarErro(msg) {
  const el = raiz.querySelector("#u-erro");
  el.textContent = msg ? msg.charAt(0).toUpperCase() + msg.slice(1) + "." : "";
  el.hidden = !msg;
}

// O que falta para salvar (null = pode salvar). O servidor confere de novo.
function faltando() {
  if (form.papel !== "visualizador") return null;
  if (!form.paginas.length) return "marque ao menos uma página";
  const e = form.escopo;
  if (!e) return "escolha quais vendedores a pessoa vê";
  if (e.modo === "equipes" && !e.equipes.length) return "marque ao menos uma equipe, ou escolha outra opção";
  if (e.modo === "alguns" && !e.vendedores.length) return "marque ao menos um vendedor, ou escolha outra opção";
  return null;
}

async function salvar() {
  const btn = raiz.querySelector("#u-salvar");
  mostrarErro("");
  const falta = faltando();
  if (falta) return mostrarErro(falta);
  btn.disabled = true;
  try {
    const original = sel || null;
    const r = await api("/api/usuarios", { json: { login_original: original, usuario: { ...form, senha: form.senha || null } } });
    dados.usuarios = r.usuarios;
    if (ehEu(original)) {
      ctx.eu = { ...ctx.eu, ...r.usuario };
      ctx.aoSalvarEu && ctx.aoSalvarEu(r.usuario);
    }
    const vis = r.usuario.papel !== "admin";
    const semAbas = [
      ...(vis && r.usuario.paginas.includes("metas") && !r.usuario.visoes.length ? ["Metas"] : []),
      ...(vis && r.usuario.paginas.includes("premiacoes") && !(r.usuario.premiacoes?.abas || []).length ? ["Premiações"] : []),
    ];
    toast(original ? `Acesso de ${r.usuario.nome} salvo` :
      `Acesso de ${r.usuario.nome} criado${semAbas.length ? `. Agora escolha as abas dela em ${semAbas.map((p) => `${p} › Configurar`).join(" e em ")}` : ""}`);
    abrir(r.usuario.login);
    render();
  } catch (e) {
    mostrarErro(e.message);
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}

async function excluir() {
  const u = dados.usuarios.find((x) => x.login === sel);
  if (!confirm(`Excluir o acesso de ${u.nome}? A pessoa não vai mais conseguir entrar (as campanhas que ela lançou na Gestão ficam). Se for só por um tempo, prefira desativar.`)) return;
  try {
    const r = await api("/api/usuarios/excluir", { json: { login: sel } });
    dados.usuarios = r.usuarios;
    toast(`Acesso de ${u.nome} excluído`);
    abrir(null);
    render();
  } catch (e) {
    toast(e.message, "erro");
  }
}
