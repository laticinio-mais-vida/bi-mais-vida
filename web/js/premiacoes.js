// Página Premiações: os vendedores (a página "Premiacao Vendedores" do Power BI), os supervisores (os regulamentos de
// nov/2026: um quadro por supervisor, com as parcelas, a trava, o bônus e o desconto) e a Comissão (a comissão dos
// vendedores das equipes BA e ES), uma aba para cada, como as abas da página de Metas. A conta fica no servidor
// (bi/premiacoes.py); aqui é a apresentação: os cartões, as tabelas dos vendedores e da comissão (que viram imagem para
// o WhatsApp), os quadros dos supervisores, a comissão por produto e o passo a passo. As abas e os quadros que cada
// pessoa vê vêm do servidor (Premiações › Configurar › Acesso por usuário); o PDF da tabela da aba é montado lá também.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast, irParaLogin, MESES } from "./util.js";
import { ligarCaptura } from "./relatorio.js";

const ABAS = {
  vendedores: { titulo: "Vendedores", icone: "usuario" },
  supervisores: { titulo: "Supervisores", icone: "pessoas" },
  comissao: { titulo: "Comissão", icone: "moeda" },
};
const nomeMes = (m) => MESES[m - 1][0].toUpperCase() + MESES[m - 1].slice(1);

let ctx = null;
const estado = { aba: "vendedores", mes: null, dados: null, pedido: 0, abertos: new Set(), vendedor: null };

export function montarPremiacoes(container, contexto) {
  ctx = contexto;
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const salvo = ler("mv-premiacoes", {});
  // Sem aba no endereço nem guardada, o servidor abre a primeira do acesso.
  estado.aba = ABAS[q.get("aba")] ? q.get("aba") : ABAS[salvo.aba] ? salvo.aba : null;
  estado.mes = /^\d{4}-\d{2}$/.test(q.get("m") || "") ? q.get("m") : null;
  estado.dados = null;

  container.innerHTML = `
    <div class="controles entra" style="--i:0">
      <div class="visoes" role="tablist" aria-label="Premiações" id="p-abas">
        <span class="indicador"></span>
        ${Object.entries(ABAS).map(([id, a]) => `<button class="visao" role="tab" data-aba="${id}">${icone(a.icone)}${a.titulo}</button>`).join("")}
      </div>
      <div class="filtros">
        <label class="campo" title="Mês"><span class="ic-campo">${icone("calendario")}</span><select id="p-mes" aria-label="Mês"></select></label>
        <label class="campo" title="Ano"><span class="ic-campo">${icone("funil")}</span><select id="p-ano" aria-label="Ano"></select></label>
        <button class="btn" type="button" id="p-pdf" title="Baixa a tabela desta aba em PDF, no mês escolhido" disabled>${icone("arquivo")}<span>Baixar PDF</span></button>
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-premiacoes" title="Faixas dos vendedores, regras e metas dos supervisores, brindes da comissão e o acesso de cada pessoa">${icone("ajustes")}<span>Configurar</span></a>` : ""}
      </div>
    </div>
    <div id="p-avisos"></div>
    <div id="p-conteudo"><div class="grade secao">
      <div class="kpis n4"><div class="esqueleto" style="height:170px"></div><div class="esqueleto" style="height:170px"></div><div class="esqueleto" style="height:170px"></div><div class="esqueleto" style="height:170px"></div></div>
      <div class="esqueleto" style="height:420px"></div></div>
    </div>`;

  container.querySelectorAll("[data-aba]").forEach((b) => b.addEventListener("click", () => {
    if (estado.aba === b.dataset.aba) return;
    estado.aba = b.dataset.aba;
    marcarAba();
    carregar();
  }));
  container.querySelector("#p-ano").addEventListener("change", (e) => {
    const d = estado.dados;
    const doAno = d ? d.meses.filter((m) => m.valor.startsWith(e.target.value)) : [];
    const mesAtual = estado.mes ? estado.mes.slice(5) : "";
    const mesmo = doAno.find((m) => m.valor.slice(5) === mesAtual);
    estado.mes = (mesmo || doAno[0] || {}).valor || null;
    carregar();
  });
  container.querySelector("#p-mes").addEventListener("change", (e) => { estado.mes = e.target.value; carregar(); });
  container.querySelector("#p-pdf").addEventListener("click", (e) => baixarPdf(e.currentTarget));
  container.querySelector("#p-conteudo").addEventListener("click", aoClicar);
  container.querySelector("#p-conteudo").addEventListener("change", (e) => {
    if (e.target.id === "p-com-vendedor") trocarVendedor(Number(e.target.value));
  });
  window.addEventListener("resize", posicionarIndicador);
  marcarAba();
  carregar();
}

export function recarregarPremiacoes() { if (ctx) carregar(true); }

function marcarAba(abas) {
  document.querySelectorAll("#p-abas [data-aba]").forEach((b) => {
    if (abas) b.hidden = !abas.includes(b.dataset.aba);
    b.classList.toggle("ativa", b.dataset.aba === estado.aba);
    b.setAttribute("aria-selected", b.dataset.aba === estado.aba);
  });
  posicionarIndicador();
}

function posicionarIndicador() {
  const ativo = document.querySelector("#p-abas .visao.ativa");
  const ind = document.querySelector("#p-abas .indicador");
  if (!ativo || !ind) return;
  const primeira = !ind.style.width;
  if (primeira) ind.style.transition = "none";
  ind.style.transform = `translate(${ativo.offsetLeft}px, ${ativo.offsetTop}px)`;
  ind.style.width = ativo.offsetWidth + "px";
  ind.style.height = ativo.offsetHeight + "px";
  if (primeira) { void ind.offsetWidth; ind.style.transition = ""; }
}

function atualizarUrl() {
  if (estado.aba) guardar("mv-premiacoes", { aba: estado.aba });
  if (!location.hash.startsWith("#/premiacoes")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams();
  if (estado.aba) p.set("aba", estado.aba);
  if (estado.mes) p.set("m", estado.mes);
  const s = p.toString();
  history.replaceState(null, "", `#/premiacoes${s ? `?${s}` : ""}`);
}

// O que a aba mostra: sem linhas (nenhum vendedor do acesso no mês), o PDF fica desligado.
const temTabela = (d) => d && (d.aba === "supervisores" ? d.supervisores.length > 0 : d.vendedores.length > 0);

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("p-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  if (estado.dados) conteudo.classList.add("recarregando");
  const pdf = document.getElementById("p-pdf");
  if (pdf) pdf.disabled = true;
  atualizarUrl();
  try {
    const p = new URLSearchParams();
    if (estado.aba) p.set("aba", estado.aba);
    if (estado.mes) p.set("mes", estado.mes);
    const d = await api(`/api/premiacoes?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    estado.aba = d.aba;
    estado.mes = d.mes.valor;
    atualizarUrl();
    marcarAba(d.abas);
    if (pdf) pdf.disabled = !temTabela(d);
    preencherPeriodo(d);
    ctx.subtitulo(d);
    document.getElementById("p-avisos").innerHTML = (d.avisos || [])
      .map((a) => `<div class="aviso">${icone("alerta")}<span>${esc(a)}</span></div>`).join("");
    conteudo.innerHTML = d.aba === "supervisores" ? renderSupervisores(d) : d.aba === "comissao" ? renderComissao(d) : renderVendedores(d);
    ligarCaptura(conteudo);
    animarContadores(conteudo);
    animarEntradas(conteudo);
    ligarTooltips(conteudo);
  } catch (e) {
    if (pedido !== estado.pedido) return;
    if (e.status === 403 && estado.aba) { // a aba guardada não é do acesso: o servidor abre a primeira que for
      estado.aba = null;
      return carregar(silencioso);
    }
    if (e.status === 403) { // nenhuma aba do acesso (como em Metas): sem abas, mês, ano nem PDF
      marcarAba([]);
      document.querySelector("#p-abas")?.closest(".controles")?.setAttribute("hidden", "");
      document.getElementById("subtitulo-pagina").innerHTML = "<span>Nenhuma aba liberada</span>";
    }
    if (e.status === 400 && estado.mes) { // mês guardado sem meta: volta para o mês dos dados
      estado.mes = null;
      if (!silencioso) toast(e.message, "erro");
      return carregar(silencioso);
    }
    // 503: os dados da aba ainda não chegaram do computador da empresa (não é erro)
    const espera = e.status === 503;
    const msg = espera || e.status === 403 ? e.message.charAt(0).toUpperCase() + e.message.slice(1) : e.message;
    conteudo.innerHTML = `<div class="cartao secao vazio">${icone(e.status === 403 ? "cadeado" : espera ? "relogio" : "alerta")}<p>${e.status === 403 || espera ? "" : "Não foi possível carregar: "}${esc(msg)}</p></div>`;
    if (!silencioso && e.status !== 403 && !espera) toast(e.message, "erro");
  } finally {
    if (pedido === estado.pedido) conteudo.classList.remove("recarregando");
  }
}

function preencherPeriodo(d) {
  const anos = [...new Set(d.meses.map((m) => m.valor.slice(0, 4)))];
  const ano = d.mes.valor.slice(0, 4);
  document.getElementById("p-ano").innerHTML = anos.map((a) => `<option value="${a}"${a === ano ? " selected" : ""}>${a}</option>`).join("");
  document.getElementById("p-mes").innerHTML = d.meses.filter((m) => m.valor.startsWith(ano))
    .map((m) => `<option value="${m.valor}"${m.valor === d.mes.valor ? " selected" : ""}>${nomeMes(Number(m.valor.slice(5)))}</option>`).join("");
}

// O PDF da tabela da aba aberta, montado agora no servidor com o acesso de quem baixa.
async function baixarPdf(botao) {
  const d = estado.dados;
  if (!d) return;
  const p = new URLSearchParams({ aba: d.aba, mes: d.mes.valor });
  botao.disabled = true;
  botao.classList.add("girando");
  toast("Montando o PDF…");
  try {
    const r = await fetch(`/api/premiacoes/pdf?${p}`);
    if (r.status === 401) return irParaLogin();
    if (!r.ok) {
      let msg = `erro ${r.status}`;
      try { msg = (await r.json()).erro || msg; } catch { /* sem corpo */ }
      throw new Error(msg);
    }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(await r.blob());
    link.download = nomeDoArquivo(r.headers.get("Content-Disposition")) || "Premiações.pdf";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    toast("Arquivo salvo em Downloads.");
  } catch (err) {
    toast(err.message, "erro");
  } finally {
    botao.classList.remove("girando");
    botao.disabled = !temTabela(estado.dados);
  }
}

function nomeDoArquivo(cabecalho) {
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cabecalho || "");
  if (utf8) { try { return decodeURIComponent(utf8[1]); } catch { /* usa o outro */ } }
  return /filename="([^"]+)"/i.exec(cabecalho || "")?.[1];
}

function aoClicar(e) {
  const linha = e.target.closest("tr[data-vendedor]");
  if (linha) {
    trocarVendedor(Number(linha.dataset.vendedor));
    document.getElementById("p-com-det")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const b = e.target.closest("[data-abrir]");
  if (!b) return;
  const id = b.dataset.abrir;
  if (estado.abertos.has(id)) estado.abertos.delete(id); else estado.abertos.add(id);
  const alvo = document.getElementById(`p-det-${id}`);
  if (alvo) alvo.hidden = !estado.abertos.has(id);
  b.setAttribute("aria-expanded", estado.abertos.has(id));
  b.querySelector(".rot").textContent = estado.abertos.has(id) ? "Esconder" : b.dataset.rotulo;
}

// ---------- apoio ----------
function kpi({ i, cor, ic, rotulo, valor, contar, formato = "moeda2", meta, rodape = [], extra = "" }) {
  return `
  <article class="cartao kpi kpi-simples entra" style="--i:${i};--cor:${cor}">
    <div class="kpi-cab"><span class="kpi-rotulo"><span class="kpi-icone">${icone(ic)}</span>${rotulo}</span>${extra}</div>
    <div class="kpi-corpo"><div>
      <div class="kpi-valor"${contar != null ? ` data-contar="${contar}" data-fmt="${formato}"` : ""}>${valor}</div>
      <div class="kpi-meta">${meta}</div>
    </div></div>
    ${rodape.length ? `<div class="kpi-rodape">${rodape.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>` : ""}
  </article>`;
}

function seloSituacao(d) {
  return d.situacao === "final"
    ? `<span class="pr-selo final" title="O mês já fechou">${icone("certo")}Final</span>`
    : `<span class="pr-selo prevista" title="O mês ainda está em andamento: o valor muda até o fim dele">${icone("relogio")}Prevista</span>`;
}

const corPct = (pct, faixas) => {
  if (pct == null) return "var(--linha-forte)";
  const max = faixas.length ? faixas[faixas.length - 1].min : 1;
  if (pct + 1e-9 >= max) return "var(--ok-forte)";
  if (faixas.length && pct + 1e-9 >= faixas[0].min) return "var(--atencao-forte)";
  return "var(--ruim-forte)";
};

function barraPct(pct, cor) {
  const largura = Math.max(0, Math.min(1, pct || 0)) * 100;
  return `<span class="pct-cel"><span class="mini"><i style="--c:${cor};width:0" data-largura="${largura}%"></i></span><b>${fmt.pct(pct)}</b></span>`;
}

// 91% sem casa decimal; 92,5% com uma (91 × 100 dá 91,000…01 em ponto flutuante).
const pctFaixa = (v) => fmt.pct(v, Math.abs(v * 100 - Math.round(v * 100)) < 1e-6 ? 0 : 1);
const textoFaixa = (f) => `${pctFaixa(f.min)} → ${fmt.moeda2(f.valor)}`;

// ---------- vendedores ----------
function renderVendedores(d) {
  const t = d.total, f = d.faixas;
  const doAcesso = d.vendedores.length;
  if (!doAcesso) {
    return `<section class="cartao secao vazio entra" style="--i:1">${icone("usuario")}<p>Nenhum vendedor do seu acesso tem meta de clientes em ${esc(d.mes.rotulo)}.</p></section>`;
  }
  const totalPagar = kpi({
    i: 1, cor: "var(--ok-forte)", ic: "trofeu", rotulo: "Total da premiação", valor: fmt.moeda2(0), contar: t.premio,
    extra: seloSituacao(d),
    meta: `<b>${t.premiados}</b> de ${t.vendedores} vendedor${t.vendedores === 1 ? "" : "es"} com prêmio em ${esc(d.mes.rotulo)}`,
  });
  const clientes = kpi({
    i: 2, cor: "var(--k-cli)", ic: "pessoas", rotulo: "Clientes atendidos", valor: fmt.num(t.atendidos),
    meta: `de <b>${fmt.num(t.meta)}</b> na meta (${fmt.pct(t.pct)})`,
    rodape: [["Sem prêmio", fmt.num(t.vendedores - t.premiados)]],
  });
  const faixas = kpi({
    i: 3, cor: "var(--s-fat)", ic: "alvo", rotulo: "Faixas", valor: `${f.length} faixa${f.length === 1 ? "" : "s"}`,
    meta: "a maior faixa atingida vale (elas não se somam)",
    rodape: f.map((x) => [`a partir de ${pctFaixa(x.min)} da meta`, fmt.moeda2(x.valor)]),
  });
  const quase = d.vendedores.filter((v) => v.proxima && v.proxima.faltam <= 3)
    .sort((a, b) => a.proxima.faltam - b.proxima.faltam || a.nome.localeCompare(b.nome));
  const perto = kpi({
    i: 4, cor: "var(--atencao-forte)", ic: "tendencia", rotulo: "Perto da próxima faixa", valor: fmt.num(quase.length),
    meta: d.situacao === "final" ? "no fechamento do mês, a até 3 clientes da faixa seguinte" : "a até 3 clientes da faixa seguinte",
    rodape: [...quase.slice(0, 4).map((v) => [esc(v.nome), `faltam ${v.proxima.faltam} → ${fmt.moeda2(v.proxima.valor)}`]),
      ...(quase.length > 4 ? [[`e mais ${quase.length - 4}`, ""]] : [])],
  });
  return `<section class="kpis secao n4 pr-kpis">${totalPagar}${clientes}${faixas}${perto}</section>
    ${tabelaVendedores(d, 5)}
    ${comoVendedores(d, 6)}`;
}

function tabelaVendedores(d, i) {
  const f = d.faixas, t = d.total;
  const linhas = d.vendedores.map((v, k) => {
    const cor = corPct(v.pct, f);
    const prox = v.proxima
      ? `faltam <b>${fmt.num(v.proxima.faltam)}</b> cliente${v.proxima.faltam === 1 ? "" : "s"} → ${fmt.moeda2(v.proxima.valor)}`
      : `<span class="pr-ok">${icone("estrela")}faixa máxima</span>`;
    return `<tr style="--i:${k}">
      <td class="rotulo">${esc(v.nome)}${v.equipe === "EDIR" && !/edir/i.test(v.nome) ? " <small>(Edir)</small>" : ""}${v.aprovada ? ` <span class="sug-aprovada" title="Meta aprovada no painel">${icone("visto")}</span>` : ""}</td>
      <td class="centro">${esc(v.estado)}</td>
      <td>${fmt.num(v.meta)}</td>
      <td>${fmt.num(v.atendidos)}</td>
      <td style="color:${cor};font-weight:700">${fmt.pct(v.pct)}</td>
      <td class="centro">${v.faixa ? pctFaixa(v.faixa.min) : "—"}</td>
      <td class="total">${v.premio ? fmt.moeda2(v.premio) : "—"}</td>
      <td class="esq">${prox}</td></tr>`;
  }).join("");
  const corpo = `
    <div class="relatorio-cab">
      <img src="/img/logo-maisvida.png" alt="Mais Vida">
      <div>
        <div class="rt">Premiação dos vendedores · ${esc(d.mes.rotulo)}</div>
        <div class="rs">${d.situacao === "final" ? "Mês fechado" : "Prevista (mês em andamento)"} · dados até ${fmt.semana(d.data_ref)}, ${fmt.data(d.data_ref)}</div>
      </div>
      <div class="rl">${f.map((x) => `<span>${esc(textoFaixa(x))}</span>`).join("")}</div>
    </div>
    <table class="relatorio-tabela pr-tabela">
      <thead><tr><th>Vendedor</th><th>Estado</th><th>Meta clientes</th><th>Atendidos</th><th>% da meta</th><th>Faixa</th>
        <th class="total">Prêmio</th><th>Próxima faixa</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td class="rotulo">Total</td><td></td><td>${fmt.num(t.meta)}</td><td>${fmt.num(t.atendidos)}</td>
        <td>${fmt.pct(t.pct)}</td><td class="centro">${t.premiados} de ${t.vendedores}</td><td class="total">${fmt.moeda2(t.premio)}</td><td></td></tr></tfoot>
    </table>`;
  const arquivo = `premiacao-vendedores-${d.mes.valor}`;
  return `
  <section class="cartao secao entra" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone("trofeu")}Premiação dos vendedores</h3>
        <p class="sub">Clientes atendidos no mês sobre a META CLIENTE (planilha de metas ou aprovada no painel, com ✓) · o total de atendidos não repete cliente atendido por dois vendedores</p></div>
      <div class="acoes-relatorio">
        <button class="btn" data-captura="copiar" data-arquivo="${arquivo}" title="Copia a tabela como imagem para colar no WhatsApp">${icone("disco")}Copiar imagem</button>
        <button class="btn icone" data-captura="baixar" data-arquivo="${arquivo}" title="Baixar a tabela como imagem (PNG)">${icone("abaixo")}</button>
      </div>
    </div>
    <div class="tabela-rolagem relatorio-rolagem"><div class="relatorio">${corpo}</div></div>
  </section>`;
}

function comoVendedores(d, i) {
  const f = d.faixas;
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como a premiação dos vendedores é calculada</h3>
        <span class="sub">A conta da página "Premiacao Vendedores" do Power BI, com as faixas em vigor</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Quem entra:</b> os vendedores com META CLIENTE maior que zero no mês, na planilha METAS.xlsx ou na meta
            aprovada no painel (que substitui a planilha).</li>
          <li><b>Atendidos:</b> clientes distintos com venda não cancelada no mês, pelo vendedor da venda. É a mesma conta
            dos "clientes realizados" da página de Metas; devolução não tira o cliente.</li>
          <li><b>% da meta:</b> atendidos ÷ META CLIENTE.</li>
          <li><b>Prêmio:</b> o da maior faixa atingida: ${f.map((x) => `a partir de <b>${pctFaixa(x.min)}</b>, <b>${fmt.moeda2(x.valor)}</b>`).join("; ")}.
            Abaixo da primeira faixa, nada. As faixas ficam em Premiações › Configurar.</li>
          <li><b>Próxima faixa:</b> quantos clientes atendidos a mais o vendedor precisa para subir de faixa.</li>
        </ol>
        <h4>Diferenças em relação ao Power BI</h4>
        <ul class="metodo-passos">
          <li>O total da premiação é a soma dos prêmios. O Power BI aplicava a faixa ao % do total, o que não servia para pagar.</li>
          <li>Enquanto o mês está em andamento, o prêmio aparece como previsto.</li>
        </ul>
      </div>
    </details>
  </section>`;
}

// ---------- supervisores ----------
const FORMATO = {
  faturamento: (v) => fmt.moeda(v), mix: (v) => fmt.pct(v), positivacao: (v) => fmt.num(v),
  novos: (v) => fmt.num(v), reativacao: (v) => fmt.num(v),
};

// O alcance arredondado para baixo: 89,96% aparece como 89,9%, não como 90,0% ao lado de uma parcela zerada.
const pctBaixo = (v, casas = 1) => (v == null ? "—"
  : fmt.pct(Math.floor(v * 100 * 10 ** casas + 1e-6) / (100 * 10 ** casas), casas));

// "DEVOLUÇÃO IMPRÓPRIA - VENCIDO" -> "Devolução imprópria - vencido"; "QUEIJO MUSSARELA 4KG" -> "Queijo mussarela 4kg"
const nomeLegivel = (nome) => { const s = String(nome || "").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); };
// "DEVOLUÇÃO - ERRO DE LANÇAMENTO" -> "erro de lançamento"
const motivoDaMeta = (nome) => String(nome || "").replace(/^DEVOLU\S*\s*-\s*/i, "").toLowerCase();
const emLista = (itens) => (itens.length <= 1 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`);
const plural = (n, um, varios) => `${fmt.num(n)} ${n === 1 ? um : varios}`;

function renderSupervisores(d) {
  const cartoes = d.supervisores.map((s, k) => cartaoSupervisor(d, s, k + 1)).join("");
  return `<section class="pr-sups secao">${cartoes}</section>${comoSupervisores(d, d.supervisores.length + 2)}`;
}

function chipFaixa(x) {
  const cls = !x.pct ? "zero" : x.pct < 1 ? "parcial" : x.pct > 1 ? "acima" : "cheia";
  return `<span class="pr-faixa ${cls}">${x.pct ? pctFaixa(x.pct) : "0%"}</span>`;
}

function textoProxima(x) {
  const p = x.proxima;
  if (!p) return "";
  const falta = x.id === "faturamento" ? fmt.moeda(p.falta) : plural(p.falta, "cliente", "clientes");
  return `<small>faltam ${falta} para ${pctFaixa(p.min)}</small>`;
}

function linhaIndicador(x) {
  const f = FORMATO[x.id];
  const meta = x.sem_meta
    ? `<span class="fraco" data-tt="${esc("<div class='tt-t'>Sem meta</div>Sem meta no mês, a parcela fica em R$ 0. As metas ficam em Premiações › Configurar.")}">sem meta</span>`
    : x.ajustada
      ? `<span data-tt="${esc(`<div class='tt-t'>Meta trocada neste mês</div>Sem a troca, seria ${x.id === "faturamento" || x.id === "positivacao" ? "a soma das metas dos vendedores" : "a meta de todo mês"}: ${x.meta_auto == null ? "sem meta" : f(x.meta_auto)}`)}">${f(x.meta)} <small class="pr-aj">ajustada</small></span>`
      : f(x.meta);
  const cor = !x.pct ? "var(--ruim-forte)" : x.pct < 1 ? "var(--atencao-forte)" : "var(--ok-forte)";
  const largura = Math.max(0, Math.min(1, x.alcance || 0)) * 100;
  const alcance = x.alcance == null ? `<span class="fraco">—</span>`
    : `<span class="pct-cel"><span class="mini"><i style="--c:${cor};width:0" data-largura="${largura}%"></i></span><b>${pctBaixo(x.alcance)}</b></span>${textoProxima(x)}`;
  const sub = x.so_trava ? "não tem peso: só move a trava e o bônus" : `peso ${pctFaixa(x.peso)} · ${fmt.moeda2(x.referencia)}`;
  return `<tr>
    <td class="esq"><b>${esc(x.titulo)}</b><small>${sub}</small></td>
    <td>${f(x.realizado)}</td>
    <td>${meta}</td>
    <td class="pr-alc">${alcance}</td>
    <td class="centro">${x.so_trava ? "—" : chipFaixa(x)}</td>
    <td class="pr-pontos">${x.so_trava ? "—" : fmt.moeda2(x.parcela)}</td></tr>`;
}

function contaSupervisor(d, s) {
  const t = s.trava, b = s.bonus, dv = s.devolucao, ad = s.adicional;
  const passo = (rotulo, efeito, valor, cls = "") => `<div class="passo ${cls}"><span>${rotulo}</span><em>${efeito}</em><b>${valor}</b></div>`;
  const alc = t.alcance == null ? "sem meta de faturamento" : `faturamento a ${pctBaixo(t.alcance)} da meta`;
  const trava = t.pct >= 1 ? "mantém 100%" : t.pct > 0 ? `paga ${pctFaixa(t.pct)}` : "zera o prêmio";
  const bonus = b.pct ? `+${pctFaixa(b.pct)}` : t.pct <= 0 ? "—" : "só acima de 100%";
  const vencido = dv.indice == null ? "vencido sem vendas no mês" : `vencido em ${fmt.pct(dv.indice, 2)} das vendas`;
  const mantido = dv.pct >= 1 ? "sem desconto" : `mantém ${pctFaixa(dv.pct)}`;
  let adicional = "";
  if (ad) {
    const limite = fmt.pct(ad.limite, 2);
    const efeito = ad.pago ? `até ${limite}: paga` : { trava: "a trava zerou", sem_dados: "sem dados", acima: `acima de ${limite}` }[ad.motivo] || "não paga";
    const indice = ad.indice == null ? "sem dados" : `em ${fmt.pct(ad.indice, 2)}`;
    adicional = passo(`Prêmio da inadimplência · ${indice}`, efeito, `+ ${fmt.moeda2(ad.valor)}`, ad.pago ? "" : "zero");
  }
  return `<div class="pr-conta">
    <h4>A conta</h4>
    ${passo("Parcelas conquistadas", "", fmt.moeda2(s.conquistado))}
    ${passo(`Trava · ${alc}`, trava, fmt.moeda2(t.valor), t.pct <= 0 ? "zero" : "")}
    ${passo("Bônus de superação", bonus, fmt.moeda2(b.total))}
    ${passo(`Desconto · ${vencido}`, mantido, fmt.moeda2(dv.total))}
    ${adicional}
    ${passo("A receber", "", fmt.moeda2(s.premio), "total")}
  </div>`;
}

function listaClientes(d, s) {
  const novos = s.clientes.novos, reat = s.clientes.reativacoes;
  const linhasNovos = novos.map((c) => `<tr><td class="esq">${esc(c.nome)}${c.inativo ? ' <small class="pr-aj">inativo hoje</small>' : ""}</td>
      <td class="esq">${esc(c.cidade || "—")}</td><td class="esq">${esc(c.vendedor)}</td>
      <td>${fmt.data(c.cadastro)}</td><td>${fmt.data(c.compra)}</td></tr>`).join("");
  const linhasReat = reat.map((c) => `<tr><td class="esq">${esc(c.nome)}</td>
      <td class="esq">${esc(c.cidade || "—")}</td><td class="esq">${esc(c.vendedor)}</td>
      <td${c.antes_das_vendas ? ` data-tt="${esc("<div class='tt-t'>Pelo título de venda</div>Antes das vendas do painel, a última compra é a do último título de venda do ERP.")}"` : ""}>${fmt.data(c.anterior)}</td>
      <td>${fmt.data(c.data)}</td><td>${plural(c.dias, "dia", "dias")}</td></tr>`).join("");
  return `<div class="pr-clientes">
    <div>
      <h4 class="pr-det-tit">Clientes novos <small class="fraco">${plural(novos.length, "cadastrado e com compra no mês", "cadastrados e com compra no mês")}</small></h4>
      <div class="tabela-rolagem pr-vend-rolagem"><table class="dados">
        <thead><tr><th>Cliente</th><th>Cidade</th><th>Vendedor</th><th>Cadastro</th><th>1ª compra</th></tr></thead>
        <tbody>${linhasNovos || `<tr><td class="esq" colspan="5">Nenhum cliente cadastrado e com compra no mês.</td></tr>`}</tbody>
      </table></div>
    </div>
    <div>
      <h4 class="pr-det-tit">Reativações <small class="fraco">${plural(reat.length, "cliente", "clientes")} com compra depois de ${plural(d.dias_sem_compra, "dia", "dias")} ou mais sem comprar</small></h4>
      <div class="tabela-rolagem pr-vend-rolagem"><table class="dados">
        <thead><tr><th>Cliente</th><th>Cidade</th><th>Vendedor</th><th>Compra anterior</th><th>Voltou em</th><th>Sem comprar</th></tr></thead>
        <tbody>${linhasReat || `<tr><td class="esq" colspan="6">Nenhuma reativação no mês.</td></tr>`}</tbody>
      </table></div>
    </div>
  </div>`;
}

function cartaoSupervisor(d, s, i) {
  const c = s.contas;
  const id = `sup-${s.id}`;
  const aberto = estado.abertos.has(id);
  const contas = [
    ["Vendas do mês", fmt.moeda2(c.vendas)],
    ["− Devoluções que descontam na meta", fmt.moeda2(c.devolucoes)],
    ["= Faturamento líquido", fmt.moeda2(c.liquido)],
    ...(s.usa_mix ? [["Líquido sem mussarela (mix)", `${fmt.moeda2(c.liquido_mix)} · ${fmt.pct(c.pct_mix)}`]] : []),
    ["Vencido: devoluções", fmt.moeda2(c.dev_vencido)],
    ["Vencido: brindes", d.sem_brindes ? "ainda sem dados" : fmt.moeda2(c.brindes_vencido)],
    ["Vencido ÷ vendas", fmt.pct(c.indice_vencido, 2)],
    ...(s.usa_inadimplencia ? [
      [`Faturamento líquido de ${esc(d.janela.rotulo)}`, fmt.moeda2(c.liquido_6m)],
      [`Em aberto, vencido até ${fmt.data(d.corte_vencimento)}`, fmt.moeda2(c.inadimplente)],
      ["Inadimplência", d.sem_credito ? "ainda sem dados" : fmt.pct(c.indice_inadimplencia, 2)]] : []),
  ];
  const vendedores = s.vendedores.map((v) => `<tr>
      <td class="esq">${esc(v.nome)}</td><td>${fmt.moeda(v.liquido)}</td>${s.usa_mix ? `<td>${fmt.pct(v.pct_mix)}</td>` : ""}
      <td>${fmt.num(v.positivacao)}</td><td>${fmt.num(v.novos)}</td><td>${fmt.num(v.reativacoes)}</td>
      <td>${fmt.moeda(v.vencido)}</td>${s.usa_inadimplencia ? `<td>${fmt.moeda(v.inadimplente)}</td>` : ""}</tr>`).join("");
  const colunas = 6 + (s.usa_mix ? 1 : 0) + (s.usa_inadimplencia ? 1 : 0);
  const fracao = s.variavel ? s.premio / s.variavel : 0;
  return `
  <article class="cartao pr-sup entra" style="--i:${i}">
    <div class="pr-sup-cab">
      <div><span class="pr-estado">${esc(s.estado)}</span><h3>${esc(s.nome)}</h3>
        <small>Variável de ${fmt.moeda2(s.variavel)} · ${esc(d.mes.rotulo)}</small></div>
      <div class="pr-sup-valor">${seloSituacao(d)}<b data-contar="${s.premio}" data-fmt="moeda2">${fmt.moeda2(0)}</b>
        <small>${fmt.pct(fracao, 1)} do variável</small></div>
    </div>
    <div class="pr-sup-barra"><i style="width:0" data-largura="${Math.min(1, Math.max(0, fracao)) * 100}%"></i></div>
    <div class="pr-sup-corpo">
      <div class="tabela-rolagem pr-ind-rolagem">
        <table class="dados pr-ind">
          <thead><tr><th>Indicador</th><th>Realizado</th><th>Meta</th><th>Alcance</th><th>Faixa</th><th>Parcela</th></tr></thead>
          <tbody>${s.indicadores.map(linhaIndicador).join("")}</tbody>
          <tfoot><tr><td class="esq" colspan="5">Parcelas conquistadas</td><td class="pr-pontos">${fmt.moeda2(s.conquistado)}</td></tr></tfoot>
        </table>
      </div>
      ${contaSupervisor(d, s)}
    </div>
    <div class="pr-sup-acoes">
      <button class="btn" type="button" data-abrir="${id}" data-rotulo="Ver as contas" aria-expanded="${aberto}">${icone("recibo")}<span class="rot">${aberto ? "Esconder" : "Ver as contas"}</span></button>
    </div>
    <div class="pr-det" id="p-det-${id}"${aberto ? "" : " hidden"}>
      <div class="pr-det-topo">
        <div class="pr-contas">${contas.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>
        <div class="tabela-rolagem pr-vend-rolagem">
          <table class="dados">
            <thead><tr><th>Carteira de</th><th>Líquido</th>${s.usa_mix ? "<th>Mix</th>" : ""}<th>Positivação</th><th>Novos</th>
              <th>Reativações</th><th>Vencido</th>${s.usa_inadimplencia ? "<th>Inadimplente</th>" : ""}</tr></thead>
            <tbody>${vendedores || `<tr><td class="esq" colspan="${colunas}">Nenhum movimento na carteira.</td></tr>`}</tbody>
          </table>
        </div>
      </div>
      ${listaClientes(d, s)}
    </div>
  </article>`;
}

function textoEscala(faixas) {
  return faixas.map((f) => `a partir de ${pctFaixa(f.min)} da meta, ${pctFaixa(f.pct)}`).join("; ");
}

function comoSupervisores(d, i) {
  const e = d.escalas;
  const sups = d.supervisores;
  const titulos = [["faturamento", "Faturamento líquido"], ["mix", "Mix (exceto mussarela)"], ["positivacao", "Positivação"],
    ["novos", "Ativação de clientes novos"], ["reativacao", "Reativação de clientes"]];
  const usados = titulos.filter(([k]) => sups.some((s) => s.indicadores.some((x) => x.id === k && !x.so_trava)));
  const celula = (s, k) => {
    const x = s.indicadores.find((y) => y.id === k);
    return x && !x.so_trava ? `${pctFaixa(x.peso)} = ${fmt.moeda2(x.referencia)}` : "—";
  };
  const pesos = `<div class="tabela-rolagem"><table class="dados pr-pesos">
      <thead><tr><th>Indicador</th>${sups.map((s) => `<th>${esc(s.nome)} (${esc(s.estado)})</th>`).join("")}</tr></thead>
      <tbody>${usados.map(([k, t]) => `<tr><td class="esq">${t}</td>${sups.map((s) => `<td>${celula(s, k)}</td>`).join("")}</tr>`).join("")}</tbody>
      <tfoot><tr><td class="esq">Variável</td>${sups.map((s) => `<td>${fmt.moeda2(s.variavel)}</td>`).join("")}</tr></tfoot>
    </table></div>`;
  const motivosMeta = d.motivos_meta.map((m) => esc(motivoDaMeta(m.nome)));
  const vencido = d.motivos_vencido.map((m) => `"${esc(nomeLegivel(m.nome))}"`);
  const mussarela = d.produtos_fora_mix.map((p) => esc(nomeLegivel(p.nome)));
  const devolucao = [...e.devolucao.faixas.map((f) => `até ${fmt.pct(f.ate, 1)}, ${f.pct >= 1 ? "sem desconto" : `mantém ${pctFaixa(f.pct)}`}`),
    `acima disso, mantém ${pctFaixa(e.devolucao.acima)}`].join("; ");
  const comAdicional = sups.filter((s) => s.adicional);
  const adicional = comAdicional.map((s) => `<li><b>Prêmio da inadimplência (${esc(s.nome)}):</b> ${fmt.moeda2(s.adicional.valor_regra)}
      com a inadimplência em até ${fmt.pct(s.adicional.limite, 2)}: títulos de venda a cliente emitidos de ${esc(d.janela.rotulo)},
      vencidos há ${d.dias_atraso} dias ou mais (até ${fmt.data(d.corte_vencimento)}) e ainda em aberto na data dos dados, ÷ o
      faturamento líquido desses 6 meses. Entra depois de todos os passos, fora da trava, do bônus e do desconto, e não é
      pago quando a trava zera o prêmio. Conta o que está em aberto hoje: o mês fechado muda quando um cliente paga depois.</li>`).join("");
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como a premiação dos supervisores é calculada</h3>
        <span class="sub">Os regulamentos dos supervisores, com as regras em vigor em Premiações › Configurar</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Carteira de hoje:</b> entram os clientes cujo vendedor no cadastro é do estado (pelas Configurações das
            metas ou pelo supervisor no ERP). Terceiros, o Edir e contas internas ficam fora. Só vendas, devoluções e
            brindes de cliente (sem funcionário, fornecedor ou produtor), sem os produtos que ficam fora das metas. Os
            supervisores do mesmo estado usam os mesmos números.</li>
          <li><b>Parcelas:</b> cada indicador tem um peso; a parcela de referência é o peso × o variável:${pesos}</li>
          <li><b>Faturamento líquido:</b> vendas do mês − as devoluções que descontam na meta (${emLista(motivosMeta)}${d.canceladas_descontam ? ", com as canceladas" : ", sem as canceladas"}),
            como na página de Metas. Brindes não descontam, porque a meta também não desconta. Meta: a soma das METAS
            FATURAMENTO dos vendedores do estado no mês, ou o valor trocado em Configurar.</li>
          ${usados.some(([k]) => k === "mix") ? `<li><b>Mix (exceto mussarela):</b> o faturamento líquido sem ${emLista(mussarela)}
            ÷ o faturamento líquido, comparado com a meta do mix.</li>` : ""}
          <li><b>Positivação:</b> clientes da carteira com venda no mês, sobre a soma das METAS CLIENTE dos vendedores do
            estado (ou o valor trocado).</li>
          <li><b>Ativação de clientes novos:</b> clientes da carteira com cadastro no ERP dentro do mês e que já
            compraram no mesmo mês. Quem é cadastrado no fim do mês e só compra no seguinte não conta.</li>
          <li><b>Reativação de clientes:</b> clientes da carteira com uma compra no mês feita depois de
            ${plural(d.dias_sem_compra, "dia", "dias")} ou mais sem comprar, contados da compra anterior até essa. Só
            conta quem já tinha comprado: as vendas do painel começam em ${fmt.data(d.inicio_dados).slice(3)}; para quem não
            comprou desde então, a compra anterior é a do último título de venda do ERP. Quem nunca comprou não conta. Cada
            cliente conta uma vez no mês.</li>
          <li><b>Faixas</b> (sem interpolação): faturamento e mix: ${textoEscala(e.escala_faturamento)}; positivação,
            novos e reativação: ${textoEscala(e.escala_clientes)}. Abaixo da primeira faixa, a parcela fica em R$ 0. As
            metas de novos e de reativação ficam em Configurar.</li>
          <li><b>Trava</b> pelo % da meta de faturamento, sobre a soma das parcelas: ${e.trava.map((f) => `a partir de ${pctFaixa(f.min)}, paga ${pctFaixa(f.pct)}`).join("; ")};
            abaixo de ${pctFaixa(e.trava[0].min)}, nada.</li>
          <li><b>Bônus de superação</b>, só com o faturamento acima de 100% da meta, sobre o valor depois da trava:
            ${e.bonus.map((f) => `a partir de ${pctFaixa(f.min)}${f.min <= 1 ? " (acima de 100%)" : ""}, +${pctFaixa(f.pct)}`).join("; ")}.</li>
          <li><b>Desconto pelo vencido</b>, por último: devoluções não canceladas e brindes com motivo ${emLista(vencido)}
            ÷ as vendas do mês. ${devolucao.charAt(0).toUpperCase() + devolucao.slice(1)}.</li>
          ${adicional}
        </ol>
        <h4>Exemplo do regulamento</h4>
        <ul class="metodo-passos">
          <li>Parcelas de R$ 6.000 (100% de todas), faturamento a 105% da meta e vencido em 0,7%: a trava mantém R$ 6.000,
            o bônus de 2% leva a R$ 6.120 e o desconto (mantém 95%) deixa R$ 5.814.</li>
        </ul>
        <h4>Bom saber</h4>
        <ul class="metodo-passos">
          <li>Com as faixas de 150%, as parcelas conquistadas podem passar do variável.</li>
          <li>Enquanto o mês está em andamento, o prêmio aparece como previsto.</li>
          <li>As regras valem para todos os meses: mudar uma regra em Configurar recalcula também os meses que já passaram.</li>
        </ul>
      </div>
    </details>
  </section>`;
}

// ---------- comissão ----------
const desconto = (v) => (v ? `− ${fmt.moeda2(v)}` : "—");
const valorOuTraco = (v) => (v ? fmt.moeda2(v) : "—");
const pctComissao = (v) => (v == null ? "—" : fmt.pct(v, 2));

// "BRINDE - DANIFICADO NO CLIENTE" -> "Danificado no cliente"
function motivoCurto(nome) {
  const s = nome.replace(/^BRINDE\s*-\s*/i, "").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Para os cartões e a imagem: "danificados e vencidos" no padrão; com outros motivos, os códigos.
function rotuloBrindes(motivos) {
  if (!motivos.length) return "(nenhum motivo)";
  const tipo = (m) => (!/^BRINDE/i.test(m.nome) ? "outros" : /DANIFICADO/i.test(m.nome) ? "danificados"
    : /VENCIDO/i.test(m.nome) ? "vencidos" : "outros");
  const tipos = new Set(motivos.map(tipo));
  return tipos.has("outros") ? `dos motivos ${motivos.map((m) => m.id).join(", ")}` : [...tipos].join(" e ");
}

function renderComissao(d) {
  const t = d.total;
  if (!d.vendedores.length) {
    return `<section class="cartao secao vazio entra" style="--i:1">${icone("moeda")}<p>Nenhum vendedor das equipes BA e ES do seu acesso vendeu em ${esc(d.mes.rotulo)}.</p></section>
      ${comoComissao(d, 2)}`;
  }
  const brindes = rotuloBrindes(d.motivos_brindes);
  const aPagar = kpi({
    i: 1, cor: "var(--ok-forte)", ic: "moeda", rotulo: "Comissão a pagar", valor: fmt.moeda2(0), contar: t.a_pagar,
    extra: seloSituacao(d),
    meta: `<b>${t.vendedores}</b> vendedor${t.vendedores === 1 ? "" : "es"} das equipes BA e ES em ${esc(d.mes.rotulo)}`,
    rodape: d.por_estado.map((e) => [`${e.estado} · ${e.vendedores} vendedor${e.vendedores === 1 ? "" : "es"}`, fmt.moeda2(e.a_pagar)]),
  });
  const vendas = kpi({
    i: 2, cor: "var(--s-fat)", ic: "recibo", rotulo: "Comissão das vendas", valor: fmt.moeda2(0), contar: t.comissao_vendas,
    meta: `sobre <b>${fmt.moeda(t.vendido)}</b> vendidos a clientes (${pctComissao(t.pct)} em média)`,
    rodape: [["como o ERP gravou em cada venda", ""]],
  });
  const devolucoes = kpi({
    i: 3, cor: "var(--ruim-forte)", ic: "devolucao", rotulo: "Desconto das devoluções", valor: fmt.moeda2(0), contar: t.desc_devolucoes,
    meta: `de <b>${fmt.moeda(t.devolvido)}</b> devolvidos (todos os motivos)`,
    rodape: [["× o % de hoje da tabela", ""]],
  });
  const descBrindes = kpi({
    i: 4, cor: "var(--atencao-forte)", ic: "caixa", rotulo: "Desconto dos brindes", valor: fmt.moeda2(0), contar: t.desc_brindes,
    meta: d.sem_brindes ? "os brindes ainda não chegaram do computador da empresa" : `de <b>${fmt.moeda(t.brindes)}</b> em brindes ${esc(brindes)}`,
    rodape: d.motivos_brindes.slice(0, 4).map((m) => [`${m.id} · ${esc(motivoCurto(m.nome))}`, ""]),
  });
  return `<section class="kpis secao n4 pr-kpis">${aPagar}${vendas}${devolucoes}${descBrindes}</section>
    ${tabelaComissao(d, 5, brindes)}
    ${detalheComissao(d, 6)}
    ${comoComissao(d, 7)}`;
}

function tabelaComissao(d, i, brindes) {
  const t = d.total;
  const linhas = d.vendedores.map((v, k) => `<tr style="--i:${k}" data-vendedor="${v.id}" title="Ver a comissão por produto">
      <td class="rotulo">${esc(v.nome)}</td>
      <td class="centro">${esc(v.estado)}</td>
      <td>${fmt.moeda2(v.vendido)}</td>
      <td>${fmt.moeda2(v.comissao_vendas)}</td>
      <td>${pctComissao(v.pct)}</td>
      <td>${valorOuTraco(v.devolvido)}</td>
      <td class="pr-desc">${desconto(v.desc_devolucoes)}</td>
      <td>${d.sem_brindes ? "…" : valorOuTraco(v.brindes)}</td>
      <td class="pr-desc">${desconto(v.desc_brindes)}</td>
      <td class="total${v.a_pagar < 0 ? " pr-neg" : ""}">${fmt.moeda2(v.a_pagar)}</td></tr>`).join("");
  const corpo = `
    <div class="relatorio-cab">
      <img src="/img/logo-maisvida.png" alt="Mais Vida">
      <div>
        <div class="rt">Comissão dos vendedores · ${esc(d.mes.rotulo)}</div>
        <div class="rs">${d.situacao === "final" ? "Mês fechado" : "Prevista (mês em andamento)"} · dados até ${fmt.semana(d.data_ref)}, ${fmt.data(d.data_ref)}</div>
      </div>
      <div class="rl"><span>Vendas: comissão gravada no ERP</span><span>Descontos: devoluções e brindes ${esc(brindes)}</span></div>
    </div>
    <table class="relatorio-tabela pr-tabela pr-com">
      <thead><tr><th>Vendedor</th><th>Estado</th><th>Vendido</th><th>Comissão das vendas</th><th>% médio</th>
        <th>Devolvido</th><th>− Comissão</th><th>Brindes</th><th>− Comissão</th><th class="total">A pagar</th></tr></thead>
      <tbody>${linhas}</tbody>
      <tfoot><tr><td class="rotulo">Total</td><td class="centro">${t.vendedores}</td><td>${fmt.moeda2(t.vendido)}</td>
        <td>${fmt.moeda2(t.comissao_vendas)}</td><td>${pctComissao(t.pct)}</td><td>${valorOuTraco(t.devolvido)}</td>
        <td class="pr-desc">${desconto(t.desc_devolucoes)}</td><td>${d.sem_brindes ? "…" : valorOuTraco(t.brindes)}</td>
        <td class="pr-desc">${desconto(t.desc_brindes)}</td><td class="total${t.a_pagar < 0 ? " pr-neg" : ""}">${fmt.moeda2(t.a_pagar)}</td></tr></tfoot>
    </table>`;
  const arquivo = `comissao-vendedores-${d.mes.valor}`;
  return `
  <section class="cartao secao entra" style="--i:${i}">
    <div class="cartao-cab">
      <div><h3>${icone("moeda")}Comissão dos vendedores</h3>
        <p class="sub">Comissão das vendas a clientes − devoluções − brindes ${esc(brindes)} · clique num vendedor para ver por produto</p></div>
      <div class="acoes-relatorio">
        <button class="btn" data-captura="copiar" data-arquivo="${arquivo}" title="Copia a tabela como imagem para colar no WhatsApp">${icone("disco")}Copiar imagem</button>
        <button class="btn icone" data-captura="baixar" data-arquivo="${arquivo}" title="Baixar a tabela como imagem (PNG)">${icone("abaixo")}</button>
      </div>
    </div>
    <div class="tabela-rolagem relatorio-rolagem"><div class="relatorio">${corpo}</div></div>
  </section>`;
}

function trocarVendedor(id) {
  const d = estado.dados;
  if (!d || d.aba !== "comissao") return;
  estado.vendedor = id;
  const sec = document.getElementById("p-com-det");
  if (!sec) return;
  sec.outerHTML = detalheComissao(d, 0, false);
  ligarTooltips(document.getElementById("p-com-det"));
}

function detalheComissao(d, i, entrar = true) {
  const v = d.vendedores.find((x) => x.id === estado.vendedor) || d.vendedores[0];
  const opcoes = d.vendedores.map((x) => `<option value="${x.id}"${x.id === v.id ? " selected" : ""}>${esc(x.nome)} (${esc(x.estado)})</option>`).join("");
  const linhas = v.produtos.map((p) => {
    const tabela = p.sem_pct
      ? `<span class="pr-sem-pct" data-tt="${esc("<div class='tt-t'>Sem % na tabela</div>O vendedor não tem % de comissão para este produto na tabela do ERP: a devolução e o brinde não descontam.")}">sem % na tabela</span>`
      : pctComissao(p.pct_tabela);
    return `<tr>
      <td class="esq">${esc(p.nome)} <small class="fraco">${p.id}</small></td>
      <td>${valorOuTraco(p.vendido)}</td>
      <td>${p.vendido ? pctComissao(p.pct) : "—"}</td>
      <td>${valorOuTraco(p.comissao)}</td>
      <td>${valorOuTraco(p.devolvido)}</td>
      <td>${valorOuTraco(p.brindes)}</td>
      <td>${tabela}</td>
      <td class="pr-desc">${desconto(p.desc_devolucoes + p.desc_brindes)}</td>
      <td class="total${p.liquido < -0.005 ? " pr-neg" : ""}">${fmt.moeda2(p.liquido)}</td></tr>`;
  }).join("");
  return `
  <section class="cartao secao${entrar ? " entra" : ""}" style="--i:${i}" id="p-com-det">
    <div class="cartao-cab">
      <div><h3>${icone("caixa")}Comissão por produto</h3>
        <p class="sub">% médio = a comissão que o ERP gravou ÷ o vendido (0% quando a venda saiu sem comissão) · % da tabela = o de hoje, usado nos descontos</p></div>
      <label class="campo" title="Vendedor"><span class="ic-campo">${icone("usuario")}</span><select id="p-com-vendedor" aria-label="Vendedor">${opcoes}</select></label>
    </div>
    <div class="tabela-rolagem">
      <table class="dados pr-com-prod">
        <thead><tr><th>Produto</th><th>Vendido</th><th>% médio</th><th>Comissão</th><th>Devolvido</th><th>Brindes</th>
          <th>% da tabela</th><th>− Descontos</th><th>Líquido</th></tr></thead>
        <tbody>${linhas || `<tr><td class="esq" colspan="9">Nenhum movimento no mês.</td></tr>`}</tbody>
        <tfoot><tr><td class="esq">Total de ${esc(v.nome)}</td><td>${fmt.moeda2(v.vendido)}</td><td>${pctComissao(v.pct)}</td>
          <td>${fmt.moeda2(v.comissao_vendas)}</td><td>${valorOuTraco(v.devolvido)}</td><td>${valorOuTraco(v.brindes)}</td><td></td>
          <td class="pr-desc">${desconto(v.desc_devolucoes + v.desc_brindes)}</td><td class="total${v.a_pagar < 0 ? " pr-neg" : ""}">${fmt.moeda2(v.a_pagar)}</td></tr></tfoot>
      </table>
    </div>
  </section>`;
}

function comoComissao(d, i) {
  const motivos = d.motivos_brindes.length
    ? d.motivos_brindes.map((m) => `<b>${m.id}</b> (${esc(motivoCurto(m.nome))})`).join(", ")
    : "nenhum (os brindes não descontam)";
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como a comissão é calculada</h3>
        <span class="sub">O % de cada vendedor para cada produto vem do ERP; os descontos, das regras em Configurar</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Quem entra:</b> os vendedores das equipes BA e ES (pelas Configurações das metas ou pelo supervisor no
            ERP), que no ERP ganham comissão sobre a venda. O Edir e os terceiros ganham sobre o recebimento e ficam fora.</li>
          <li><b>O %:</b> é do vendedor para cada produto, na tabela de comissão do ERP (vendedor × produto). Para mudar um
            %, mude no ERP.</li>
          <li><b>Comissão das vendas:</b> a que o ERP gravou em cada item de venda a cliente não cancelada: o valor do item
            × o % do vendedor para o produto no dia da venda. Mudar a tabela depois não muda o que já foi vendido; venda feita
            antes de o produto ter % na tabela fica sem comissão.</li>
          <li><b>− Devoluções:</b> todas as devoluções não canceladas do mês (todos os motivos, pela data de entrada), do
            vendedor que está na devolução, × o % de hoje da tabela para o produto.</li>
          <li><b>− Brindes:</b> os brindes do mês com motivo ${motivos}, × o % de hoje da tabela. Os motivos ficam em
            Premiações › Configurar › Comissão.</li>
          <li><b>A pagar:</b> a comissão das vendas menos os dois descontos. Fica negativa quando as devoluções do mês passam
            da comissão.</li>
        </ol>
        <h4>Bom saber</h4>
        <ul class="metodo-passos">
          <li>Devolução ou brinde de um produto sem % na tabela do vendedor não desconta (aparece marcado em Comissão por
            produto).</li>
          <li>Só vendas, devoluções e brindes de cliente: venda a funcionário, fornecedor ou produtor não tem comissão no ERP.</li>
          <li>Enquanto o mês está em andamento, a comissão aparece como prevista.</li>
        </ul>
      </div>
    </details>
  </section>`;
}
