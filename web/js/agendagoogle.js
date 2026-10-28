// As agendas do Google da pessoa (só leitura, bi/google_agenda.py): a janela do botão Google da agenda. Conecta pelo
// endereço secreto no formato iCal (colado aqui e nunca mostrado de volta: ele é uma senha), mostra como foi a última
// leitura de cada agenda, relê na hora e remove. O BI nunca escreve no Google; os eventos aparecem na agenda da pessoa.
// Onde a leitura não está ligada (no PC), a janela só avisa que ela fica no site.
import { api, esc, fmt, icone, toast } from "./util.js";

const PASSOS = [
  "No computador, abra <b>calendar.google.com</b> com a sua conta (o app do celular não mostra esta opção).",
  "Clique na engrenagem, no canto de cima, e em <b>Configurações</b>.",
  "À esquerda, em <b>Configurações das minhas agendas</b>, clique na sua agenda.",
  "Desça até <b>Integrar agenda</b>.",
  "Copie o último campo, <b>Endereço secreto no formato iCal</b>, e cole aqui.",
];

let dlg = null, dados = null, aoMudar = null;

// aoMudar: chamado depois de conectar, reler ou remover (a agenda recarrega o mês).
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
  dlg.addEventListener("submit", conectar);
}

// "hoje às 10:20", "ontem às 09:00" ou "em 25/10 às 09:00".
function quando(iso) {
  const dia = iso.slice(0, 10), hoje = new Date(), ontem = new Date(Date.now() - 864e5);
  const local = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const nome = dia === local(hoje) ? "hoje" : dia === local(ontem) ? "ontem" : `em ${fmt.dataCurta(dia)}`;
  return `${nome} às ${iso.slice(11, 16)}`;
}

// Como foi a última leitura. O erro do endereço que morreu já diz para colar de novo; o passageiro, que o BI tenta de
// novo sozinho.
function situacao(a) {
  if (!a.erro) return `<small>${icone("certo")}Lida ${quando(a.lida_em)}</small>`;
  const ultima = a.lida_em ? `última leitura boa ${quando(a.lida_em)}` : "ainda sem leitura";
  const motivo = a.erro.charAt(0).toUpperCase() + a.erro.slice(1);
  return `<small class="${a.atencao ? "ruim" : ""}">${icone("alerta")}${esc(motivo)} · ${ultima}</small>`;
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
  const lista = dados.agendas.length ? `<ul class="ag-g-lista">${dados.agendas.map((a) => `<li class="${a.atencao ? "atencao" : ""}">
      <div class="ag-g-info"><b>${esc(a.nome)}</b>
        <small>${esc(a.calendario)} · ${fmt.num(a.eventos)} ${a.eventos === 1 ? "evento" : "eventos"} guardados</small>
        ${situacao(a)}</div>
      <div class="ag-g-acoes">
        <button class="btn" type="button" data-atualizar="${a.id}" title="Ler a agenda agora">${icone("atualizar")}Atualizar agora</button>
        <button class="btn icone perigo" type="button" data-remover="${a.id}" title="Remover do BI" aria-label="Remover ${esc(a.nome)} do BI">${icone("lixeira")}</button>
      </div>
    </li>`).join("")}</ul>` : "";
  dlg.innerHTML = `${cab}${lista}
    <form class="ag-g-form" novalidate>
      <label class="campo-form"><span>${dados.agendas.length ? "Conectar outra agenda" : "Conectar uma agenda"}</span>
        <input name="endereco" inputmode="url" autocomplete="off" spellcheck="false" autocapitalize="off"
          placeholder="https://calendar.google.com/calendar/ical/…/private-…/basic.ics"></label>
      <p class="form-erro" role="alert" hidden></p>
      <div class="dialogo-acoes"><button class="btn primario" type="submit">${icone("elo")}Conectar</button></div>
    </form>
    <details class="ag-g-passos" ${dados.agendas.length ? "" : "open"}><summary>Onde achar o endereço secreto</summary>
      <ol>${PASSOS.map((p) => `<li>${p}</li>`).join("")}</ol></details>
    <ul class="ag-g-notas">
      <li>${icone("cadeado")}<span>O endereço funciona como uma senha: quem tem lê a agenda inteira. Não mande por mensagem; o BI guarda cifrado e não mostra de novo. Para cortar o acesso, use <b>Redefinir</b>, ao lado dele no Google (depois, cole o novo aqui).</span></li>
      <li>${icone("calendario")}<span>Só os eventos marcados como <b>Ocupado</b> no Google travam o seu horário para as tarefas dos outros; o de dia inteiro vem como Disponível, a não ser que você mude. Na sua própria agenda, eles só avisam.</span></li>
      <li>${icone("atualizar")}<span>O BI lê de novo a cada 10 minutos. Os eventos ficam só na sua agenda: ninguém mais vê.</span></li>
    </ul>`;
}

async function conectar(e) {
  e.preventDefault();
  const f = e.target, campo = f.elements.endereco, erro = f.querySelector(".form-erro");
  const botao = f.querySelector('[type="submit"]');
  if (!campo.value.trim()) {
    erro.textContent = "Cole o endereço secreto da agenda (veja onde achar logo abaixo).";
    erro.hidden = false;
    return campo.focus();
  }
  botao.disabled = true;
  erro.hidden = true;
  try {
    const r = await api("/api/agenda/google", { json: { endereco: campo.value.trim() } });
    campo.value = ""; // o endereço é uma senha: não fica no campo
    dados = r;
    desenhar();
    toast(r.nova ? `Agenda “${r.agenda.nome}” conectada` : `Endereço da agenda “${r.agenda.nome}” trocado`);
    aoMudar?.();
  } catch (err) {
    botao.disabled = false;
    erro.textContent = err.message;
    erro.hidden = false;
  }
}

async function aoClicar(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if ("fechar" in b.dataset) return dlg.close();
  const id = Number(b.dataset.atualizar || b.dataset.remover);
  if (!id) return;
  const a = dados.agendas.find((x) => x.id === id);
  if (b.dataset.remover && !confirm(`Remover “${a.nome}” do BI? Os eventos dela saem da sua agenda daqui; no Google, nada muda.`)) return;
  b.disabled = true;
  try {
    dados = await api(`/api/agenda/google/${b.dataset.remover ? "remover" : "atualizar"}`, { json: { id } });
    desenhar();
    const lida = dados.agendas.find((x) => x.id === id);
    if (b.dataset.remover) toast("Agenda do Google removida");
    else if (lida?.erro) toast(`Não deu para ler “${lida.nome}”: ${lida.erro}`, "erro");
    else toast(`Agenda “${a.nome}” lida agora`);
    aoMudar?.();
  } catch (err) {
    b.disabled = false;
    toast(err.message, "erro");
  }
}
