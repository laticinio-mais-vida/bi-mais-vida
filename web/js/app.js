// Inicialização: sessão, tema, rotas (#/metas, #/configuracoes e #/usuarios), estado dos dados e atualização
// da cópia do banco. Configurações e Usuários só aparecem para administradores (o servidor também barra).
import { api, esc, fmt, irParaLogin, ligarTema, preencherIcones, toast } from "./util.js";
import { montarMetas, recarregarMetas } from "./metas.js";
import { montarConfig, configTemAlteracoes } from "./config.js";
import { montarUsuarios, usuariosTemAlteracoes } from "./usuarios.js";
import { ligarMenuUsuario, mostrarUsuario } from "./conta.js";

const app = { opcoes: null, estado: null, rota: null, montadas: new Set(), usuario: null };
const ROTAS_ADMIN = ["configuracoes", "usuarios"];

function subtituloMetas(d) {
  app.dadosMetas = d;
  const sub = document.getElementById("subtitulo-pagina");
  sub.innerHTML = `<span>${esc(d.periodo.rotulo)} · ${esc(d.visao.titulo)}</span>
    <span class="ponto"><span class="pulso"></span>dados até ${fmt.semana(d.data_ref)}, ${fmt.dataCurta(d.data_ref)}</span>`;
}

function rodape() {
  const e = app.estado || {};
  // No VPS os dados chegam prontos do computador da empresa; no PC, o administrador vê se o envio ao VPS deu certo.
  const origem = e.modo === "vps"
    ? `<span>Recebidos no servidor em ${fmt.dataHora(e.recebido_em)}</span>`
    : `<span>Cache local gerado em ${fmt.dataHora(e.extraido_em)}</span>`;
  const envio = e.envio && app.usuario?.papel === "admin"
    ? `<span>${e.envio.erro ? `Envio ao servidor falhou: ${esc(e.envio.erro)}` : `Enviado ao servidor em ${fmt.dataHora(e.envio.enviado_em)}`}</span>`
    : "";
  document.getElementById("rodape").innerHTML = `
    <span>Fonte: cópia do ERP de ${fmt.dataHora(e.banco_copia)}</span>
    ${origem}${envio}
    <span>Metas: METAS.xlsx e METAS PRODUTOS.xlsx</span>
    <span>Laticínio Mais Vida</span>`;
}

async function rotear() {
  const pedida = (location.hash.replace(/^#\/?/, "").split("?")[0] || "metas");
  const rota = ROTAS_ADMIN.includes(pedida) && app.usuario.papel === "admin" ? pedida : "metas";
  const pendente = { configuracoes: configTemAlteracoes, usuarios: usuariosTemAlteracoes }[app.rota];
  if (app.rota !== rota && pendente && pendente() &&
      !confirm("Há alterações não salvas nesta página. Sair mesmo assim?")) {
    history.replaceState(null, "", "#/" + app.rota);
    return;
  }
  if (rota !== pedida) history.replaceState(null, "", "#/metas");
  app.rota = rota;
  document.querySelectorAll(".nav-pilula").forEach((a) => a.classList.toggle("ativa", a.dataset.rota === app.rota));
  const pMetas = document.getElementById("pagina-metas"), pConfig = document.getElementById("pagina-configuracoes");
  const pUsuarios = document.getElementById("pagina-usuarios");
  pMetas.hidden = app.rota !== "metas";
  pConfig.hidden = app.rota !== "configuracoes";
  pUsuarios.hidden = app.rota !== "usuarios";
  if (app.rota === "metas") {
    document.getElementById("titulo-pagina").textContent = "Acompanhamento de Metas";
    if (!app.montadas.has("metas") || app.precisaRecarregar) {
      app.montadas.add("metas");
      app.precisaRecarregar = false;
      montarMetas(pMetas, { opcoes: app.opcoes, subtitulo: subtituloMetas });
    } else if (app.dadosMetas) {
      subtituloMetas(app.dadosMetas); // volta o subtítulo de Metas depois de passar por outra página
    }
  } else if (app.rota === "configuracoes") {
    document.getElementById("titulo-pagina").textContent = "Configurações das metas";
    document.getElementById("subtitulo-pagina").innerHTML = "<span>Produtos, vendedores, devoluções e dias úteis usados nos cálculos</span>";
    montarConfig(pConfig, { aoSalvar: () => { app.precisaRecarregar = true; } });
  } else {
    document.getElementById("titulo-pagina").textContent = "Usuários e acessos";
    document.getElementById("subtitulo-pagina").innerHTML = "<span>Quem entra no painel e o que cada pessoa pode ver</span>";
    montarUsuarios(pUsuarios, { eu: app.usuario, aoSalvarEu: (u) => { app.usuario = { ...app.usuario, ...u }; mostrarUsuario(app.usuario); } });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function aguardarDados() {
  const tela = document.getElementById("tela-preparo");
  for (;;) {
    try {
      app.estado = await api("/api/estado");
      if (app.estado.pronto) break;
      tela.hidden = false;
      document.getElementById("preparo-etapa").textContent =
        app.estado.atualizacao.erro ? `Erro: ${app.estado.atualizacao.erro}` : (app.estado.atualizacao.etapa || "Lendo a cópia do banco…");
    } catch {
      document.getElementById("preparo-etapa").textContent = "Aguardando o servidor…";
      tela.hidden = false;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  tela.hidden = true;
}

function botaoAtualizar() {
  const btn = document.getElementById("btn-atualizar");
  const rotulo = btn.querySelector(".rotulo");
  btn.addEventListener("click", async () => {
    if (btn.classList.contains("girando")) return;
    btn.classList.add("girando");
    rotulo.textContent = "Atualizando…";
    try {
      await api("/api/atualizar", { method: "POST" });
      await acompanharAtualizacao(rotulo);
    } catch (e) {
      toast(e.message, "erro");
    } finally {
      btn.classList.remove("girando");
      rotulo.textContent = "Atualizar dados";
    }
  });
}

async function acompanharAtualizacao(rotulo) {
  const antes = app.estado?.extraido_em;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1200));
    const e = await api("/api/estado");
    if (rotulo && e.atualizacao.etapa) rotulo.textContent = e.atualizacao.etapa + "…";
    if (!e.atualizacao.atualizando) {
      app.estado = e;
      if (e.atualizacao.erro) throw new Error("Falha ao ler o banco: " + e.atualizacao.erro);
      if (e.extraido_em !== antes) aoTrocarDados();
      else toast("Os dados já estavam atualizados");
      return;
    }
  }
}

async function aoTrocarDados() {
  app.opcoes = await api("/api/opcoes");
  rodape();
  toast(`Dados atualizados até ${fmt.dataCurta(app.estado.data_ref)}`);
  if (app.rota === "metas") recarregarMetas();
  else app.precisaRecarregar = true;
}

function vigiar() {
  setInterval(async () => {
    try {
      const antes = app.estado?.extraido_em;
      const e = await api("/api/estado");
      app.estado = e;
      if (!e.atualizacao.atualizando && e.extraido_em && e.extraido_em !== antes) aoTrocarDados();
      else rodape(); // situação do envio ao VPS
    } catch { /* servidor fora do ar: tenta de novo no próximo ciclo */ }
  }, 60000);
}

async function iniciar() {
  preencherIcones(document);
  ligarTema(document.getElementById("btn-tema"));
  const sessao = await api("/api/sessao");
  if (!sessao.usuario) return irParaLogin();
  app.usuario = sessao.usuario;
  mostrarUsuario(app.usuario);
  ligarMenuUsuario();
  botaoAtualizar();
  await aguardarDados();
  document.body.dataset.modo = app.estado.modo; // no VPS some o que só existe no PC (Atualizar dados)
  app.opcoes = await api("/api/opcoes");
  rodape();
  window.addEventListener("hashchange", rotear);
  await rotear();
  vigiar();
}

iniciar().catch((e) => toast(e.message, "erro"));
