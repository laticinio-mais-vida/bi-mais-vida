// Tela de login. Sem nenhum usuário cadastrado, vira o "primeiro acesso" (só no computador do painel).
import { api, esc, icone, ligarTema, preencherIcones } from "./util.js";

const corpo = document.getElementById("login-corpo");
const cartao = document.getElementById("login-cartao");

// Depois de entrar, volta para a tela em que a sessão tinha caído (só caminhos internos #/...).
const volta = (() => {
  const v = new URLSearchParams(location.search).get("volta") || "";
  return v.startsWith("#/") ? v : "";
})();

function entrar() {
  cartao.classList.add("saindo");
  setTimeout(() => location.replace("/" + volta), 260);
}

function campo({ id, rotulo, ic, tipo = "text", auto, extra = "" }) {
  const senha = tipo === "password";
  return `<label class="login-campo" for="${id}"><span>${rotulo}</span>
    <span class="caixa">${icone(ic)}<input id="${id}" name="${id}" type="${tipo}" autocomplete="${auto}" required
      ${id === "login" ? 'autocapitalize="none" spellcheck="false"' : ""} ${extra}>
      ${senha ? `<button type="button" class="ver-senha" data-alvo="${id}" aria-label="Mostrar senha" title="Mostrar senha">${icone("olho")}</button>` : ""}
    </span></label>`;
}

function ligarVerSenha() {
  corpo.querySelectorAll(".ver-senha").forEach((b) => b.addEventListener("click", () => {
    const input = document.getElementById(b.dataset.alvo);
    const mostrar = input.type === "password";
    input.type = mostrar ? "text" : "password";
    b.innerHTML = icone(mostrar ? "olhoFechado" : "olho");
    b.setAttribute("aria-label", mostrar ? "Esconder senha" : "Mostrar senha");
    input.focus();
  }));
}

function erro(msg) {
  const el = corpo.querySelector(".login-erro");
  el.innerHTML = msg ? `${icone("alerta")}<span>${esc(msg)}</span>` : "";
  el.hidden = !msg;
  if (msg) {
    cartao.classList.remove("treme");
    void cartao.offsetWidth;
    cartao.classList.add("treme");
  }
}

function enviar(form, acao) {
  const botao = form.querySelector("button[type=submit]");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    erro("");
    botao.disabled = true;
    botao.classList.add("carregando");
    try {
      await acao(new FormData(form));
      entrar();
    } catch (err) {
      erro(err.message);
      botao.disabled = false;
      botao.classList.remove("carregando");
    }
  });
}

function formLogin() {
  corpo.innerHTML = `
    <h1>Acompanhamento de Metas</h1>
    <p class="login-sub">Entre com o usuário e a senha que o administrador do painel passou para você.</p>
    <form class="login-form" novalidate>
      ${campo({ id: "login", rotulo: "Usuário", ic: "usuario", auto: "username" })}
      ${campo({ id: "senha", rotulo: "Senha", ic: "cadeado", tipo: "password", auto: "current-password" })}
      <label class="login-lembrar"><input type="checkbox" name="lembrar"><span class="marca-caixa"></span>Manter conectado neste aparelho</label>
      <p class="login-erro" role="alert" hidden></p>
      <button class="btn primario login-entrar" type="submit"><span class="txt">Entrar</span>${icone("sair", "seta")}</button>
    </form>
    <p class="login-dica">${icone("info")}Esqueceu a senha? Peça ao administrador para criar uma nova.</p>`;
  const form = corpo.querySelector("form");
  ligarVerSenha();
  enviar(form, async (d) => {
    if (!d.get("login") || !d.get("senha")) throw new Error("preencha o usuário e a senha");
    await api("/api/login", { json: { login: d.get("login"), senha: d.get("senha"), lembrar: d.get("lembrar") === "on" }, semLogin: true });
  });
  document.getElementById("login").focus();
}

function formPrimeiroAcesso() {
  corpo.innerHTML = `
    <span class="login-selo">${icone("escudo")}Primeiro acesso</span>
    <h1>Crie o administrador</h1>
    <p class="login-sub">O painel ainda não tem usuários. O administrador vê tudo e cadastra os outros acessos
      (supervisores, vendedores) na página <b>Usuários</b>.</p>
    <form class="login-form" novalidate>
      ${campo({ id: "nome", rotulo: "Seu nome", ic: "usuario", auto: "name" })}
      ${campo({ id: "login", rotulo: "Usuário (para entrar)", ic: "etiqueta", auto: "username", extra: 'placeholder="ex.: joao.silva"' })}
      ${campo({ id: "senha", rotulo: "Senha (mínimo 6 caracteres)", ic: "cadeado", tipo: "password", auto: "new-password" })}
      ${campo({ id: "senha2", rotulo: "Repita a senha", ic: "cadeado", tipo: "password", auto: "new-password" })}
      <p class="login-erro" role="alert" hidden></p>
      <button class="btn primario login-entrar" type="submit"><span class="txt">Criar administrador e entrar</span>${icone("sair", "seta")}</button>
    </form>`;
  const form = corpo.querySelector("form");
  ligarVerSenha();
  enviar(form, async (d) => {
    if (!d.get("nome") || !d.get("login") || !d.get("senha")) throw new Error("preencha todos os campos");
    if (d.get("senha") !== d.get("senha2")) throw new Error("as duas senhas não são iguais");
    await api("/api/primeiro-acesso", { json: { nome: d.get("nome"), login: d.get("login"), senha: d.get("senha") }, semLogin: true });
  });
  document.getElementById("nome").focus();
}

function semUsuarios(modo) {
  const onde = modo === "vps"
    ? `no servidor. Pelo terminal do VPS, na pasta do painel, rode <b>python3 app.py --senha SEU_LOGIN</b>.`
    : `no computador onde o painel está instalado. Abra lá o endereço <b>http://127.0.0.1:${esc(location.port || "80")}</b>.`;
  corpo.innerHTML = `
    <span class="login-selo">${icone("escudo")}Primeiro acesso</span>
    <h1>Painel ainda sem usuários</h1>
    <p class="login-sub">Por segurança, o primeiro administrador só pode ser criado ${onde}</p>`;
}

async function iniciar() {
  preencherIcones(document);
  ligarTema(document.getElementById("btn-tema"));
  let s;
  try {
    s = await api("/api/sessao", { semLogin: true });
  } catch {
    corpo.innerHTML = `<h1>Painel fora do ar</h1><p class="login-sub">Não foi possível falar com o servidor do painel.
      Confira se ele está aberto no computador principal e tente de novo.</p>
      <button class="btn primario login-entrar" type="button" onclick="location.reload()">Tentar de novo</button>`;
    return;
  }
  if (s.usuario) return entrar();
  if (s.primeiro_acesso) return s.local ? formPrimeiroAcesso() : semUsuarios(s.modo);
  formLogin();
}

iniciar();
