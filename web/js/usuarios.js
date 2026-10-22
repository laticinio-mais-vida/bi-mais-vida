// Página Usuários (só administradores): quem entra no painel (nome, usuário, senha, papel) e quais páginas cada
// um vê. O que a pessoa vê dentro de cada página (abas, vendedores) fica no botão Configurar da própria página;
// aqui aparece só o resumo, com o link para lá. Quem barra é o servidor, a página só monta o cadastro.
import { api, esc, fmt, icone, toast } from "./util.js";
import { PAPEL, iniciais } from "./conta.js";

const ICONE_PAGINA = { metas: "alvo", projecoes: "tendencia", assistente: "conversa", gestao: "quadro", credito: "cartao" };
const DESCRICAO_PAGINA = {
  metas: "Metas do mês por vendedor e produto",
  projecoes: "Faturamento previsto para 6 meses",
  assistente: "Perguntas sobre os dados, respondidas por IA",
  gestao: "Objetivos, campanhas e o histórico de cada vendedor",
  credito: "Limite, compras, pontualidade e títulos de cada cliente",
};
const CONFIG_PAGINA = { metas: "configuracoes", projecoes: "config-projecoes", assistente: "config-assistente", gestao: "config-gestao" }; // rota do Configurar de cada página

let ctx = null, raiz = null;
let dados = null;     // { usuarios, paginas }
let sel = null;       // login em edição; "" = novo acesso; null = nenhum
let form = null, base = null;

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
  if (!u) return { login: "", nome: "", senha: "", papel: "visualizador", ativo: true, paginas: ["metas"] };
  return { login: u.login, nome: u.nome, senha: "", papel: u.papel, ativo: u.ativo, paginas: u.paginas ? [...u.paginas] : ["metas"] };
}

function abrir(login) {
  sel = login;
  const u = login ? dados.usuarios.find((x) => x.login === login) : null;
  form = login === null ? null : rascunho(u);
  base = form && clone(form);
}

function trocarPara(login) {
  if (sel === login) return;
  if (sujo() && !confirm("Há alterações não salvas neste acesso. Descartar?")) return;
  abrir(login);
  render();
}

const ehEu = (login) => login && login === ctx.eu.login;
const tituloPagina = (id) => dados.paginas.find((p) => p.id === id)?.titulo || id;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

function resumoCurto(u) {
  return u.papel === "admin" ? "vê tudo" : emLista((u.paginas || []).map(tituloPagina));
}

// O que a pessoa vê dentro de cada página, como está salvo na configuração da página (só leitura aqui).
function dentroDaPagina(u, pagina) {
  if (pagina === "credito") return { texto: "todos os clientes e vendedores (a página não tem configuração)" };
  if (pagina === "metas") {
    if (!u.visoes?.length) return { texto: "ainda sem abas: a página fica vazia até você escolher", aviso: true };
    const vend = u.vendedores ? plural(u.vendedores.length, "vendedor", "vendedores") : "todos os vendedores";
    return { texto: `${plural(u.visoes.length, "aba", "abas")} · ${vend}` };
  }
  const p = u[pagina] || { modo: "metas" }; // Projeções e Assistente: igual a Metas, todos ou só alguns
  if (p.modo === "todos") return { texto: "todos os vendedores da página" };
  if (p.modo === "alguns") return { texto: plural(p.vendedores.length, "vendedor escolhido", "vendedores escolhidos") };
  const semAbas = !u.visoes?.length;
  return { texto: semAbas ? "igual a Metas, que ainda não tem abas: nenhum vendedor" : "igual ao acesso de Metas", aviso: semAbas };
}

function resumoCompleto(f) {
  const quem = esc(f.nome.trim() || "Esta pessoa");
  if (f.papel === "admin") {
    return `<b>${quem}</b> vê todas as páginas, abas e vendedores, e pode mudar as configurações e os acessos.`;
  }
  if (!f.paginas.length) return "Marque ao menos uma página para este acesso.";
  const paginas = emLista(f.paginas.map((p) => `<b>${esc(tituloPagina(p))}</b>`));
  const txt = `<b>${quem}</b> vai ver a${f.paginas.length > 1 ? "s páginas" : " página"} ${paginas}.`;
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
        <small>${esc(u.login)} · ${esc(resumoCurto(u))}</small></span>
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
      <p>Aqui ficam o nome, o usuário, a senha e as <b>páginas</b> de cada pessoa. As abas e os vendedores que ela
        vê ficam no botão <b>Configurar</b> de cada página, em "Acesso por usuário".</p>
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
      ${[["visualizador", "olho", "Vê só as páginas que você liberar e, nelas, o que a configuração da página permitir."],
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
  const u = dados.usuarios.find((x) => x.login === sel);
  // Resumo do que está salvo na configuração de cada página marcada (para quem já tem cadastro).
  const dentro = u && u.papel !== "admin" ? form.paginas.map((p) => {
    const d = dentroDaPagina(u, p);
    return `<li class="${d.aviso ? "aviso-nota" : ""}">${icone(d.aviso ? "alerta" : ICONE_PAGINA[p] || "alvo")}
      <span><b>${esc(tituloPagina(p))}:</b> ${esc(d.texto)}</span>
      ${CONFIG_PAGINA[p] ? `<a href="#/${CONFIG_PAGINA[p]}?u=${encodeURIComponent(u.login)}">${icone("ajustes")}Configurar</a>` : ""}</li>`;
  }).join("") : "";
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
    <p class="usu-nota">${icone("info")}<span>As abas e os vendedores que a pessoa vê dentro de cada página ficam no botão
      <b>Configurar</b> da página, em "Acesso por usuário".${u ? "" : " Depois de criar o acesso, escolha lá as abas de Metas: até isso, a página fica vazia para ela."}</span></p>
    ${dentro ? `<ul class="usu-dentro">${dentro}</ul>` : ""}`;
  alvo.querySelectorAll(".visao-op[data-pagina]").forEach((b) => b.addEventListener("click", () => {
    const marcadas = new Set(form.paginas);
    marcadas.has(b.dataset.pagina) ? marcadas.delete(b.dataset.pagina) : marcadas.add(b.dataset.pagina);
    form.paginas = dados.paginas.map((p) => p.id).filter((id) => marcadas.has(id));
    desenharPermissoes();
  }));
  atualizarResumo();
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

async function salvar() {
  const btn = raiz.querySelector("#u-salvar");
  mostrarErro("");
  if (form.papel === "visualizador" && !form.paginas.length) return mostrarErro("marque ao menos uma página");
  btn.disabled = true;
  try {
    const original = sel || null;
    const r = await api("/api/usuarios", { json: { login_original: original, usuario: { ...form, senha: form.senha || null } } });
    dados.usuarios = r.usuarios;
    if (ehEu(original)) {
      ctx.eu = { ...ctx.eu, ...r.usuario };
      ctx.aoSalvarEu && ctx.aoSalvarEu(r.usuario);
    }
    const semAbas = r.usuario.papel !== "admin" && r.usuario.paginas.includes("metas") && !r.usuario.visoes.length;
    toast(original ? `Acesso de ${r.usuario.nome} salvo` :
      `Acesso de ${r.usuario.nome} criado${semAbas ? ". Agora escolha as abas dela em Metas › Configurar" : ""}`);
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
