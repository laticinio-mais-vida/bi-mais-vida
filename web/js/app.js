// Inicialização: sessão, tema, barra lateral, rotas, estado dos dados e atualização da cópia do banco.
// Cada pessoa vê só as páginas liberadas no cadastro dela. Cada página tem a sua configuração (botão
// Configurar dentro dela, só para administradores); Usuários fica na barra lateral. O servidor também barra.
import { api, esc, fmt, icone, irParaLogin, ligarTema, preencherIcones, toast } from "./util.js";
import { montarMetas, recarregarMetas } from "./metas.js";
import { montarProjecoes, recarregarProjecoes } from "./projecoes.js";
import { montarConfig, configTemAlteracoes } from "./config.js";
import { montarConfigProjecoes, configProjecoesTemAlteracoes } from "./configprojecoes.js";
import { montarAssistente } from "./assistente.js";
import { montarConfigAssistente, configAssistenteTemAlteracoes } from "./configassistente.js";
import { montarGestao, recarregarGestao, gestaoTemAlteracoes } from "./gestao.js";
import { montarConfigGestao, configGestaoTemAlteracoes } from "./configgestao.js";
import { montarUsuarios, usuariosTemAlteracoes } from "./usuarios.js";
import { ligarMenuUsuario, mostrarUsuario } from "./conta.js";
import { ligarLateral, marcarPagina, mostrarPaginas } from "./lateral.js";

const app = { opcoes: null, estado: null, rota: null, montadas: new Set(), remontar: new Set(), usuario: null, dados: {} };
const PAGINAS_DE_DADOS = ["metas", "projecoes", "gestao"];

const ehAdmin = () => app.usuario?.papel === "admin";

// Para criar uma página: acrescente aqui, no index.html (seção e item da lateral) e, se ela for liberada
// por usuário, em PAGINAS de bi/acesso.py. A configuração de uma página é outra entrada, com `pai`: ela
// mantém a página de origem marcada na lateral e ganha o link de volta no topo.
const PAGINAS = {
  metas: {
    nome: "Metas",
    titulo: "Acompanhamento de Metas",
    montar: (el) => montarMetas(el, { opcoes: app.opcoes, admin: ehAdmin(), subtitulo: (d) => subtitulo("metas", d) }),
    recarregar: recarregarMetas,
  },
  projecoes: {
    nome: "Projeções",
    titulo: "Projeções de faturamento",
    montar: (el) => montarProjecoes(el, { admin: ehAdmin(), subtitulo: (d) => subtitulo("projecoes", d) }),
    recarregar: recarregarProjecoes,
  },
  configuracoes: {
    titulo: "Configurações das metas",
    fixo: "Produtos, vendedores, devoluções e dias úteis usados nos cálculos, e o que cada pessoa vê na página",
    pai: "metas",
    admin: true,
    sempreMonta: true,
    pendente: configTemAlteracoes,
    montar: (el) => montarConfig(el, { aoSalvar: () => PAGINAS_DE_DADOS.forEach((p) => app.remontar.add(p)) }),
  },
  "config-projecoes": {
    titulo: "Configurações das projeções",
    fixo: "Vendedores que entram na página e o que cada pessoa vê nela",
    pai: "projecoes",
    admin: true,
    sempreMonta: true,
    pendente: configProjecoesTemAlteracoes,
    montar: (el) => montarConfigProjecoes(el, { aoSalvar: () => app.remontar.add("projecoes") }),
  },
  assistente: {
    nome: "Assistente",
    titulo: "Assistente de dados",
    montar: (el) => montarAssistente(el, { admin: ehAdmin(), subtitulo: (d) => subtitulo("assistente", d) }),
  },
  "config-assistente": {
    titulo: "Configurações do assistente",
    fixo: "O que cada pessoa consulta no assistente e quanto ele foi usado",
    pai: "assistente",
    admin: true,
    sempreMonta: true,
    pendente: configAssistenteTemAlteracoes,
    montar: (el) => montarConfigAssistente(el),
  },
  gestao: {
    nome: "Gestão",
    titulo: "Gestão de campanhas",
    pendente: gestaoTemAlteracoes,
    montar: (el) => montarGestao(el, {
      admin: ehAdmin(), eu: app.usuario, assistente: paginasPermitidas().includes("assistente"),
      subtitulo: (d) => subtitulo("gestao", d),
    }),
    recarregar: recarregarGestao,
  },
  "config-gestao": {
    titulo: "Configurações da gestão",
    fixo: "Os vendedores que cada pessoa pode pôr nas campanhas e acompanhar",
    pai: "gestao",
    admin: true,
    sempreMonta: true,
    pendente: configGestaoTemAlteracoes,
    montar: (el) => montarConfigGestao(el),
  },
  usuarios: {
    titulo: "Usuários e acessos",
    fixo: "Quem entra no painel e quais páginas cada pessoa vê",
    admin: true,
    sempreMonta: true,
    pendente: usuariosTemAlteracoes,
    montar: (el) => montarUsuarios(el, {
      eu: app.usuario,
      aoSalvarEu: (u) => { app.usuario = { ...app.usuario, ...u }; mostrarUsuario(app.usuario); },
    }),
  },
};

const TEXTO_SUBTITULO = {
  metas: (d) => `${d.periodo.rotulo} · ${d.visao.titulo}`,
  projecoes: (d) => `Faturamento bruto · ${d.periodo.de} a ${d.periodo.ate}`,
  assistente: () => "Pergunte sobre vendas, clientes, produtos e metas",
  gestao: () => "Campanhas de vendas e o andamento de cada vendedor",
};

// O subtítulo do topo mostra o filtro e a data dos dados da página aberta.
function subtitulo(rota, d) {
  app.dados[rota] = d;
  if (app.rota !== rota) return; // a resposta chegou depois de trocar de página
  document.getElementById("subtitulo-pagina").innerHTML = `<span>${esc(TEXTO_SUBTITULO[rota](d))}</span>
    <span class="ponto"><span class="pulso"></span>dados até ${fmt.semana(d.data_ref)}, ${fmt.dataCurta(d.data_ref)}</span>`;
}

function paginasPermitidas() {
  const admin = app.usuario.papel === "admin";
  return Object.keys(PAGINAS).filter((r) => (PAGINAS[r].admin ? admin : admin || app.usuario.paginas.includes(r)));
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
  const permitidas = paginasPermitidas();
  const pedida = location.hash.replace(/^#\/?/, "").split("?")[0];
  const rota = permitidas.includes(pedida) ? pedida : permitidas[0];
  const pendente = PAGINAS[app.rota]?.pendente;
  if (app.rota && app.rota !== rota && pendente && pendente() &&
      !confirm("Há alterações não salvas nesta página. Sair mesmo assim?")) {
    history.replaceState(null, "", "#/" + app.rota);
    return;
  }
  if (!rota) {
    document.getElementById("app").innerHTML = `<div class="cartao vazio">${icone("cadeado")}<p>Seu acesso ainda não tem nenhuma página liberada. Fale com o administrador.</p></div>`;
    return;
  }
  if (rota !== pedida) history.replaceState(null, "", "#/" + rota);
  app.rota = rota;
  marcarPagina(PAGINAS[rota].pai || rota);
  Object.keys(PAGINAS).forEach((r) => { document.getElementById(`pagina-${r}`).hidden = r !== rota; });
  const p = PAGINAS[rota];
  document.getElementById("titulo-pagina").textContent = p.titulo;
  document.title = `${p.titulo} · Mais Vida`;
  const sub = document.getElementById("subtitulo-pagina");
  if (p.fixo) {
    const volta = p.pai ? `<a class="link-voltar" href="#/${p.pai}">${icone("voltar")}${esc(PAGINAS[p.pai].nome)}</a>` : "";
    sub.innerHTML = `${volta}<span>${esc(p.fixo)}</span>`;
  }
  if (p.sempreMonta || !app.montadas.has(rota) || app.remontar.has(rota)) {
    app.montadas.add(rota);
    app.remontar.delete(rota);
    if (!p.fixo) sub.innerHTML = "<span>Carregando…</span>";
    p.montar(document.getElementById(`pagina-${rota}`));
  } else if (app.dados[rota]) {
    subtitulo(rota, app.dados[rota]); // volta o subtítulo da página depois de passar por outra
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
  PAGINAS_DE_DADOS.forEach((p) => {
    if (p === app.rota) PAGINAS[p].recarregar();
    else if (app.montadas.has(p)) app.remontar.add(p);
  });
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
  ligarLateral();
  const sessao = await api("/api/sessao");
  if (!sessao.usuario) return irParaLogin();
  app.usuario = sessao.usuario;
  mostrarUsuario(app.usuario);
  mostrarPaginas(paginasPermitidas());
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
