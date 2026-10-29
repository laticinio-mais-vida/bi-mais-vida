// As contas Google da pessoa (só leitura, bi/google_agenda.py): a janela do botão Google da agenda. "Entrar com o
// Google" abre o login do Google numa janelinha; na volta, web/google.html avisa esta página (BroadcastChannel e
// postMessage) e a lista é relida. Em cada conta, a pessoa liga as agendas que aparecem no BI (a principal já vem
// ligada), relê na hora e desconecta. O BI nunca escreve no Google; os eventos aparecem na agenda da pessoa. Onde a
// leitura não está ligada (no PC), a janela só avisa que ela fica no site.
import { api, esc, fmt, icone, toast } from "./util.js";

const ENTRAR = "/api/agenda/google/entrar";
const MAX_CONTAS = 3;
const PASSOS = [
  "Clique em <b>Entrar com o Google</b> e escolha a sua conta.",
  "Se aparecer <b>“O Google não verificou este app”</b>, clique em <b>Avançado</b> e depois em <b>Acessar bi.maisvida.cloud</b>. O aviso aparece porque o BI é um sistema interno da Mais Vida, sem a verificação que o Google faz em apps públicos.",
  "O Google pergunta se o BI pode <b>ver as suas agendas</b>: clique em <b>Continuar</b>.",
  "Pronto: a janelinha fecha e a sua agenda principal já aparece aqui. Ligue as outras que quiser.",
];

// esperando: mostra a dica enquanto a janelinha está aberta. abertoEm: quando esta aba abriu o login (o resultado só
// vale para ela, por até 15 minutos; um link para google.html aberto por fora não mexe aqui).
let dlg = null, dados = null, aoMudar = null, esperando = false, abertoEm = 0;

// aoMudar: chamado depois de conectar, ligar, reler ou desconectar (a agenda recarrega o mês).
export async function abrirGoogle(opcoes = {}) {
  aoMudar = opcoes.aoMudar || null;
  criar();
  dlg.innerHTML = `<div class="esqueleto" style="height:160px"></div>`;
  if (!dlg.open) dlg.showModal();
  try {
    dados = await api("/api/agenda/google");
  } catch (e) {
    dlg.close();
    return toast(e.message, "erro");
  }
  desenhar();
}

function criar() {
  if (dlg) return;
  dlg = document.createElement("dialog");
  dlg.className = "dialogo ag-g-janela";
  dlg.setAttribute("aria-labelledby", "ag-g-titulo");
  document.body.appendChild(dlg);
  dlg.addEventListener("click", aoClicar);
  dlg.addEventListener("change", aoLigar);
}

// "hoje às 10:20", "ontem às 09:00" ou "em 25/10 às 09:00".
function quando(iso) {
  const dia = iso.slice(0, 10), hoje = new Date(), ontem = new Date(Date.now() - 864e5);
  const local = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const nome = dia === local(hoje) ? "hoje" : dia === local(ontem) ? "ontem" : `em ${fmt.dataCurta(dia)}`;
  return `${nome} às ${iso.slice(11, 16)}`;
}

const maiuscula = (t) => t.charAt(0).toUpperCase() + t.slice(1);

// Como foi a última leitura de uma agenda ligada. O erro da agenda que não abre mais já diz o que fazer; o passageiro,
// que o BI tenta de novo sozinho.
function situacao(a) {
  if (!a.ligada) return "";
  if (!a.erro) {
    return a.lida_em ? `<small>${icone("certo")}Lida ${quando(a.lida_em)} · ${fmt.num(a.eventos)} ${a.eventos === 1 ? "evento" : "eventos"}</small>`
      : `<small>${icone("relogio")}Lendo pela primeira vez…</small>`;
  }
  const ultima = a.lida_em ? `última leitura boa ${quando(a.lida_em)}` : "ainda sem leitura";
  return `<small class="${a.atencao ? "ruim" : ""}">${icone("alerta")}${esc(maiuscula(a.erro))} · ${ultima}</small>`;
}

function contaHtml(c) {
  const caiu = c.trocar ? `<div class="aviso ag-g-caiu">${icone("alerta")}<span>${esc(maiuscula(c.erro || "a conexão com o Google caiu"))}.</span>
      <button class="btn" type="button" data-entrar>Entrar de novo</button></div>` : "";
  return `<li class="ag-g-conta ${c.atencao ? "atencao" : ""}">
    <div class="ag-g-conta-cab">
      <b>${icone("usuario")}${esc(c.email)}</b>
      <div class="ag-g-acoes">
        <button class="btn" type="button" data-atualizar="${c.id}" title="Ler as agendas desta conta agora" ${c.trocar ? "disabled" : ""}>${icone("atualizar")}Atualizar agora</button>
        <button class="btn icone perigo" type="button" data-desconectar="${c.id}" title="Desconectar esta conta" aria-label="Desconectar ${esc(c.email)}">${icone("lixeira")}</button>
      </div>
    </div>
    ${caiu}
    <ul class="ag-g-agendas">${c.agendas.map((a) => `<li class="${a.atencao ? "atencao" : ""}">
      <label><input type="checkbox" data-ligar="${a.id}" ${a.ligada ? "checked" : ""} ${c.trocar ? "disabled" : ""}>
        <span><b>${esc(a.nome)}</b>${a.principal ? ` <em>principal</em>` : ""}</span></label>
      ${situacao(a)}
    </li>`).join("")}</ul>
  </li>`;
}

function desenhar() {
  const cab = `<div class="ag-hist-cab">
      <div><h2 id="ag-g-titulo">${icone("elo")}Agendas do Google</h2>
        <p class="sub">Só leitura: os eventos aparecem na sua agenda daqui, e nada é escrito no Google.</p></div>
      <button class="btn icone" type="button" data-fechar title="Fechar" aria-label="Fechar">${icone("x")}</button>
    </div>`;
  if (!dados.ativo) {
    dlg.innerHTML = `${cab}<div class="aviso">${icone("info")}<span>${esc(dados.aviso)}</span></div>`;
    return;
  }
  const contas = dados.contas;
  const entrar = contas.length < MAX_CONTAS ? `<div class="ag-g-entrar">
      <button class="btn ${contas.length ? "" : "primario"}" type="button" data-entrar>${icone(contas.length ? "mais" : "elo")}${contas.length ? "Conectar outra conta Google" : "Entrar com o Google"}</button>
      ${esperando ? `<small>${icone("relogio")}Termine o login na janelinha do Google…</small>` : ""}
    </div>` : "";
  dlg.innerHTML = `${cab}
    ${contas.length ? `<ul class="ag-g-lista">${contas.map(contaHtml).join("")}</ul>` : ""}
    ${entrar}
    <details class="ag-g-passos" ${contas.length ? "" : "open"}><summary>Como conectar</summary>
      <ol>${PASSOS.map((p) => `<li>${p}</li>`).join("")}</ol></details>
    <ul class="ag-g-notas">
      <li>${icone("cadeado")}<span>O BI só pede para <b>ver</b> as suas agendas: não cria, não muda e não apaga nada no Google. Para tirar o acesso, clique na lixeira da conta (ou, no Google, em Conta › Segurança › Apps de terceiros com acesso). Veja a <a href="/privacidade.html" target="_blank" rel="noopener">política de privacidade</a>.</span></li>
      <li>${icone("calendario")}<span>Só os eventos marcados como <b>Ocupado</b> no Google travam o seu horário para as tarefas dos outros; o de dia inteiro vem como Disponível, a não ser que você mude. Na sua própria agenda, eles só avisam.</span></li>
      <li>${icone("atualizar")}<span>O BI lê de novo a cada 10 minutos. Os eventos ficam só na sua agenda: ninguém mais vê.</span></li>
    </ul>`;
}

// Abre o login do Google numa janelinha. Bloqueada pelo navegador: vai na própria aba (google.html volta para a Gestão).
// Fechada sem terminar, a janela relê a lista (não custa nada; o resultado de verdade chega por aoVoltar).
function entrar() {
  const janela = window.open(ENTRAR, "bi-google", "popup,width=520,height=700");
  if (!janela) {
    location.href = ENTRAR;
    return;
  }
  esperando = true;
  abertoEm = Date.now();
  desenhar();
  const vigia = setInterval(() => {
    if (!janela.closed) return;
    clearInterval(vigia);
    setTimeout(() => {
      if (!esperando) return;
      esperando = false;
      recarregar();
    }, 1500);
  }, 800);
}

async function recarregar() {
  try {
    dados = await api("/api/agenda/google");
    if (dlg?.open) desenhar();
  } catch (e) {
    toast(e.message, "erro");
  }
}

// O resultado do login ({id, ok: e-mail} ou {id, erro}), mandado por web/google.html pelos dois caminhos: vale uma vez.
const vistos = new Set();
async function aoVoltar(r) {
  if (!r?.id || vistos.has(r.id) || Date.now() - abertoEm > 15 * 60e3) return;
  vistos.add(r.id);
  esperando = false;
  abertoEm = 0;
  if (r.erro) toast(maiuscula(r.erro), "erro");
  else toast(`Conta Google ${r.ok} conectada`);
  await recarregar();
  aoMudar?.();
}
if ("BroadcastChannel" in window) {
  new BroadcastChannel("bi-google").addEventListener("message", (e) => aoVoltar(e.data?.biGoogle));
}
window.addEventListener("message", (e) => {
  if (e.origin === location.origin && e.data?.biGoogle) aoVoltar(e.data.biGoogle);
});

async function aoLigar(e) {
  const caixa = e.target.closest("[data-ligar]");
  if (!caixa) return;
  caixa.disabled = true;
  try {
    dados = await api("/api/agenda/google/ligar", { json: { id: Number(caixa.dataset.ligar), ligada: caixa.checked } });
    desenhar();
    aoMudar?.();
  } catch (err) {
    caixa.checked = !caixa.checked;
    caixa.disabled = false;
    toast(err.message, "erro");
  }
}

async function aoClicar(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if ("fechar" in b.dataset) return dlg.close();
  if ("entrar" in b.dataset) return entrar();
  const id = Number(b.dataset.atualizar || b.dataset.desconectar);
  if (!id) return;
  const c = dados.contas.find((x) => x.id === id);
  if (b.dataset.desconectar && !confirm(`Desconectar ${c.email}? As agendas dessa conta saem da sua agenda daqui, e o BI deixa de ter acesso a ela no Google.`)) return;
  b.disabled = true;
  try {
    dados = await api(`/api/agenda/google/${b.dataset.desconectar ? "desconectar" : "atualizar"}`, { json: { id } });
    desenhar();
    const agora = dados.contas.find((x) => x.id === id);
    const falhas = agora?.agendas.filter((a) => a.ligada && a.erro) || [];
    if (b.dataset.desconectar) toast("Conta Google desconectada");
    else if (agora?.trocar) toast(maiuscula(agora.erro), "erro");
    else if (falhas.length) toast(`Não deu para ler “${falhas[0].nome}”: ${falhas[0].erro}`, "erro");
    else toast("Agendas lidas agora");
    aoMudar?.();
  } catch (err) {
    b.disabled = false;
    toast(err.message, "erro");
  }
}
