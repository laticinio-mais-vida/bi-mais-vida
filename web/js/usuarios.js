// Página Usuários (só administradores): quem entra no painel e quais páginas cada um vê.
// Em Metas, o visualizador vê só as abas marcadas e, se a lista de vendedores estiver preenchida, só esses
// vendedores. Os vendedores de Projeções ficam na configuração da própria página (aqui só aparece o resumo).
// Quem barra é o servidor, a página só monta o cadastro.
import { api, esc, fmt, icone, toast } from "./util.js";
import { PAPEL, iniciais } from "./conta.js";

const ICONE_VISAO = { es: "mapa", ba: "mapa", edir: "usuario", outras_es: "leite", produtos_ba: "caixa" };
const ICONE_PAGINA = { metas: "alvo", projecoes: "tendencia" };
const DESCRICAO_PAGINA = { metas: "Metas do mês por vendedor e produto", projecoes: "Faturamento previsto para 6 meses" };

let ctx = null, raiz = null;
let dados = null;     // { usuarios, visoes, paginas, vendedores }
let sel = null;       // login em edição; "" = novo acesso; null = nenhum
let form = null, base = null;
let busca = "";
let ultimosAlguns = [];

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
  if (!u) return { login: "", nome: "", senha: "", papel: "visualizador", ativo: true, paginas: ["metas"], visoes: [], vendedores: null };
  return { login: u.login, nome: u.nome, senha: "", papel: u.papel, ativo: u.ativo,
           paginas: u.paginas ? [...u.paginas] : ["metas"],
           visoes: u.visoes ? [...u.visoes] : [], vendedores: u.vendedores ? [...u.vendedores] : null };
}

function abrir(login) {
  sel = login;
  const u = login ? dados.usuarios.find((x) => x.login === login) : null;
  form = login === null ? null : rascunho(u);
  base = form && clone(form);
  ultimosAlguns = form?.vendedores || [];
  busca = "";
}

function trocarPara(login) {
  if (sel === login) return;
  if (sujo() && !confirm("Há alterações não salvas neste acesso. Descartar?")) return;
  abrir(login);
  render();
}

const ehEu = (login) => login && login === ctx.eu.login;
const tituloVisao = (id) => dados.visoes.find((v) => v.id === id)?.titulo || id;
const tituloPagina = (id) => dados.paginas.find((p) => p.id === id)?.titulo || id;
const nomeVendedor = (id) => dados.vendedores.find((v) => v.id === id)?.nome || `Vendedor ${id}`;

function emLista(itens) {
  if (itens.length <= 1) return itens.join("");
  return itens.slice(0, -1).join(", ") + " e " + itens[itens.length - 1];
}

function resumoCurto(u) {
  if (u.papel === "admin") return "vê tudo";
  const partes = [emLista((u.paginas || []).map(tituloPagina))];
  if ((u.paginas || []).includes("metas")) {
    const n = u.vendedores?.length;
    partes.push(`${u.visoes.length} aba${u.visoes.length === 1 ? "" : "s"}`, n ? `${n} vendedor${n === 1 ? "" : "es"}` : "todos os vendedores");
  }
  return partes.join(" · ");
}

// Como a pessoa vê Projeções (definido na configuração da página Projeções).
function modoProjecoes(login) {
  const p = dados.usuarios.find((x) => x.login === login)?.projecoes || { modo: "metas" };
  if (p.modo === "todos") return "todos os vendedores da página";
  if (p.modo === "alguns") return `${p.vendedores.length} vendedor${p.vendedores.length === 1 ? "" : "es"} escolhido${p.vendedores.length === 1 ? "" : "s"}`;
  return "igual ao acesso de Metas";
}

function resumoCompleto(f) {
  const quem = esc(f.nome.trim() || "Esta pessoa");
  if (f.papel === "admin") {
    return `<b>${quem}</b> vê todas as páginas, abas e vendedores, e pode mudar as Configurações e os acessos.`;
  }
  if (!f.paginas.length) return "Marque ao menos uma página para este acesso.";
  const metas = f.paginas.includes("metas");
  if (metas && !f.visoes.length) return "Marque ao menos uma aba de Metas para este acesso.";
  const paginas = emLista(f.paginas.map((p) => `<b>${esc(tituloPagina(p))}</b>`));
  let txt = `<b>${quem}</b> vai ver a${f.paginas.length > 1 ? "s páginas" : " página"} ${paginas}.`;
  if (metas) {
    const abas = emLista(f.visoes.map((v) => `<b>${esc(tituloVisao(v))}</b>`));
    let vend;
    if (f.vendedores === null) vend = "com todos os vendedores dessas abas";
    else if (!f.vendedores.length) vend = "mas falta marcar os vendedores";
    else if (f.vendedores.length <= 3) vend = `só com ${emLista(f.vendedores.map((v) => `<b>${esc(nomeVendedor(v))}</b>`))}; os totais somam só ${f.vendedores.length === 1 ? "esse vendedor" : "esses vendedores"}`;
    else vend = `só com os <b>${f.vendedores.length} vendedores</b> marcados; os totais somam só esses vendedores`;
    txt += ` Em Metas: abas ${abas}, ${vend}.`;
  }
  if (f.paginas.includes("projecoes")) txt += ` Em Projeções: ${esc(modoProjecoes(sel))}.`;
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
      <p>Exemplos: o <b>supervisor da BA</b> é um visualizador com as abas Metas BA e Produtos BA.
        Um <b>vendedor</b> é um visualizador com a aba dele e só ele marcado em Vendedores.</p>
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
      ${[["visualizador", "olho", "Vê só as páginas, abas e vendedores que você liberar."],
         ["admin", "escudo", "Vê tudo, muda as Configurações e cadastra acessos."]].map(([p, ic, txt]) => `
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
  const alguns = form.vendedores !== null;
  const metas = form.paginas.includes("metas"), projecoes = form.paginas.includes("projecoes");
  const semAbas = (dados.usuarios.find((x) => x.login === sel)?.projecoes?.modo || "metas") === "metas" && !form.visoes.length;
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
    ${metas ? `<h3 class="usu-titulo">Metas: abas que pode ver</h3>
    <div class="visoes-escolha">
      ${dados.visoes.map((v) => {
        const on = form.visoes.includes(v.id);
        return `<button type="button" class="visao-op ${on ? "ativo" : ""}" data-visao="${v.id}" aria-pressed="${on}">
          <span class="marca-caixa">${icone("visto")}</span>${icone(ICONE_VISAO[v.id] || "alvo")}
          <span><b>${esc(v.titulo)}</b><small>vendedores ${esc(emLista(v.grupos.map((g) => (g === "EDIR" ? "Edir" : g))))}</small></span>
        </button>`;
      }).join("")}
    </div>
    <h3 class="usu-titulo">Metas: vendedores</h3>
    <div class="seletor v2 usu-modo" data-v="${alguns ? 1 : 0}"><span class="marcador"></span>
      <button type="button" data-modo="todos" class="${alguns ? "" : "ativo"}">${icone("pessoas")}Todos dessas abas</button>
      <button type="button" data-modo="alguns" class="${alguns ? "ativo" : ""}">${icone("usuario")}Só alguns vendedores</button>
    </div>
    <div id="u-vendedores"></div>` : ""}
    ${projecoes ? `<h3 class="usu-titulo">Projeções: vendedores</h3>
    <p class="usu-nota">${icone("tendencia")}<span>Ficam na configuração da página Projeções. Hoje: <b>${esc(modoProjecoes(sel))}</b>.
      ${sel ? `<a href="#/config-projecoes?u=${encodeURIComponent(sel)}">Abrir a configuração das projeções</a>` : "Depois de criar o acesso, ajuste lá."}</span></p>
    ${semAbas ? `<p class="usu-nota aviso-nota">${icone("alerta")}<span>Sem abas de Metas, "igual ao acesso de Metas" não mostra nenhum vendedor: escolha os vendedores na configuração das projeções.</span></p>` : ""}` : ""}`;
  alvo.querySelectorAll(".visao-op[data-pagina]").forEach((b) => b.addEventListener("click", () => {
    const marcadas = new Set(form.paginas);
    marcadas.has(b.dataset.pagina) ? marcadas.delete(b.dataset.pagina) : marcadas.add(b.dataset.pagina);
    form.paginas = dados.paginas.map((p) => p.id).filter((id) => marcadas.has(id));
    desenharPermissoes(); // mostra ou esconde o que é de cada página
  }));
  alvo.querySelectorAll(".visao-op[data-visao]").forEach((b) => b.addEventListener("click", () => {
    const marcadas = new Set(form.visoes);
    marcadas.has(b.dataset.visao) ? marcadas.delete(b.dataset.visao) : marcadas.add(b.dataset.visao);
    form.visoes = dados.visoes.map((v) => v.id).filter((id) => marcadas.has(id));
    b.classList.toggle("ativo", marcadas.has(b.dataset.visao));
    b.setAttribute("aria-pressed", marcadas.has(b.dataset.visao));
    desenharVendedores();
  }));
  alvo.querySelectorAll(".usu-modo button").forEach((b) => b.addEventListener("click", () => {
    const querAlguns = b.dataset.modo === "alguns";
    if (querAlguns === (form.vendedores !== null)) return;
    if (querAlguns) form.vendedores = [...ultimosAlguns];
    else { ultimosAlguns = form.vendedores; form.vendedores = null; }
    const seletor = alvo.querySelector(".usu-modo");
    seletor.dataset.v = querAlguns ? 1 : 0;
    seletor.querySelectorAll("button").forEach((x) => x.classList.toggle("ativo", x === b));
    desenharVendedores();
  }));
  desenharVendedores();
}

function desenharVendedores() {
  const alvo = raiz.querySelector("#u-vendedores");
  if (!alvo) { atualizarResumo(); return; } // sem a página Metas
  if (form.vendedores === null) {
    alvo.innerHTML = `<p class="usu-nota">${icone("info")}Vê todos os vendedores que aparecem nas abas marcadas, inclusive os que entrarem depois.</p>`;
    atualizarResumo();
    return;
  }
  if (!dados.vendedores.length) {
    alvo.innerHTML = `<p class="usu-nota">${icone("alerta")}A lista de vendedores aparece quando os dados terminarem de carregar.</p>`;
    atualizarResumo();
    return;
  }
  const grupos = new Set(dados.visoes.filter((v) => form.visoes.includes(v.id)).flatMap((v) => v.grupos));
  const marcados = new Set(form.vendedores);
  const limite = new Date(); limite.setMonth(limite.getMonth() - 3);
  const lista = dados.vendedores.filter((v) => grupos.has(v.grupo) || marcados.has(v.id));
  alvo.innerHTML = `
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
        <input id="u-busca" type="search" placeholder="Buscar vendedor ou código" value="${esc(busca)}"></label>
      <span class="usu-cont" id="u-cont"></span>
      <button class="btn" type="button" id="u-todos">Marcar os da lista</button>
      <button class="btn" type="button" id="u-nenhum">Desmarcar todos</button>
    </div>
    ${grupos.size ? "" : `<p class="usu-nota">${icone("info")}Marque as abas primeiro: a lista mostra os vendedores delas.</p>`}
    <div class="vend-escolha" id="u-vend-lista">
      ${lista.map((v) => {
        const antigo = new Date(v.ultimo_mes + "T12:00") < limite;
        const fora = !grupos.has(v.grupo);
        return `<label class="vend-op ${antigo ? "antigo" : ""}" data-busca="${esc((v.nome + " " + v.nome_erp + " " + v.id).toLowerCase())}">
          <input type="checkbox" data-id="${v.id}" ${marcados.has(v.id) ? "checked" : ""}><span class="marca-caixa">${icone("visto")}</span>
          <span class="n">${esc(v.nome)}<small>código ${v.id} · ${esc(v.grupo === "EDIR" ? "Edir" : v.grupo)}${v.supervisor ? ` · sup. ${esc(v.supervisor)}` : ""}${fora ? " · fora das abas marcadas" : ""}</small></span>
        </label>`;
      }).join("")}
    </div>`;
  const filtrar = () => {
    const termo = busca.trim().toLowerCase();
    alvo.querySelectorAll(".vend-op").forEach((el) => { el.hidden = termo && !el.dataset.busca.includes(termo); });
  };
  const contar = () => {
    const n = form.vendedores.length;
    alvo.querySelector("#u-cont").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : "nenhum marcado";
    atualizarResumo();
  };
  const definir = (ids) => {
    form.vendedores = [...ids].sort((a, b) => a - b);
    alvo.querySelectorAll(".vend-op input").forEach((c) => { c.checked = ids.has(Number(c.dataset.id)); });
    contar();
  };
  alvo.querySelector("#u-busca").addEventListener("input", (e) => { busca = e.target.value; filtrar(); });
  alvo.querySelectorAll(".vend-op input").forEach((c) => c.addEventListener("change", () => {
    const ids = new Set(form.vendedores);
    c.checked ? ids.add(Number(c.dataset.id)) : ids.delete(Number(c.dataset.id));
    definir(ids);
  }));
  alvo.querySelector("#u-todos").addEventListener("click", () => {
    const ids = new Set(form.vendedores);
    alvo.querySelectorAll(".vend-op:not([hidden]) input").forEach((c) => ids.add(Number(c.dataset.id)));
    definir(ids);
  });
  alvo.querySelector("#u-nenhum").addEventListener("click", () => definir(new Set()));
  filtrar();
  contar();
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
  const temMetas = form.paginas.includes("metas");
  if (form.papel === "visualizador" && temMetas && !form.visoes.length) return mostrarErro("marque ao menos uma aba de Metas");
  if (form.papel === "visualizador" && temMetas && form.vendedores && !form.vendedores.length) return mostrarErro("marque ao menos um vendedor de Metas, ou escolha todos dessas abas");
  btn.disabled = true;
  try {
    const original = sel || null;
    const r = await api("/api/usuarios", { json: { login_original: original, usuario: { ...form, senha: form.senha || null } } });
    dados.usuarios = r.usuarios;
    if (ehEu(original)) {
      ctx.eu = { ...ctx.eu, ...r.usuario };
      ctx.aoSalvarEu && ctx.aoSalvarEu(r.usuario);
    }
    toast(original ? `Acesso de ${r.usuario.nome} salvo` : `Acesso de ${r.usuario.nome} criado`);
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
  if (!confirm(`Excluir o acesso de ${u.nome}? A pessoa não vai mais conseguir entrar. Se for só por um tempo, prefira desativar.`)) return;
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
