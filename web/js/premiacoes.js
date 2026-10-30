// Página Premiações: as páginas "Premiacao Vendedores" e "Premiacao Supervisores" do Power BI numa só, com uma aba para
// cada uma, como as abas da página de Metas, e a aba Comissão (a comissão dos vendedores das equipes BA e ES). A conta
// fica no servidor (bi/premiacoes.py); aqui é a apresentação: os cartões, as tabelas dos vendedores e da comissão (que
// viram imagem para o WhatsApp), os quadros dos supervisores, a comissão por produto e o passo a passo.
import { api, esc, fmt, icone, animarContadores, animarEntradas, ligarTooltips, guardar, ler, toast, MESES } from "./util.js";
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
  estado.aba = ABAS[q.get("aba")] ? q.get("aba") : ABAS[salvo.aba] ? salvo.aba : "vendedores";
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
        ${ctx.admin ? `<a class="btn btn-config" href="#/config-premiacoes" title="Faixas dos vendedores, pesos e metas dos supervisores">${icone("ajustes")}<span>Configurar</span></a>` : ""}
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
  guardar("mv-premiacoes", { aba: estado.aba });
  if (!location.hash.startsWith("#/premiacoes")) return; // trocou de página enquanto carregava
  const p = new URLSearchParams({ aba: estado.aba });
  if (estado.mes) p.set("m", estado.mes);
  history.replaceState(null, "", `#/premiacoes?${p}`);
}

async function carregar(silencioso = false) {
  const conteudo = document.getElementById("p-conteudo");
  if (!conteudo) return;
  const pedido = ++estado.pedido;
  if (estado.dados) conteudo.classList.add("recarregando");
  atualizarUrl();
  try {
    const p = new URLSearchParams({ aba: estado.aba });
    if (estado.mes) p.set("mes", estado.mes);
    const d = await api(`/api/premiacoes?${p}`);
    if (pedido !== estado.pedido) return;
    estado.dados = d;
    estado.mes = d.mes.valor;
    atualizarUrl();
    marcarAba(d.abas);
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
    if (e.status === 403 && estado.aba !== "vendedores") { // a aba dos supervisores não é do acesso
      estado.aba = "vendedores";
      marcarAba(["vendedores"]);
      return carregar(silencioso);
    }
    if (e.status === 400 && estado.mes) { // mês guardado sem meta: volta para o mês dos dados
      estado.mes = null;
      if (!silencioso) toast(e.message, "erro");
      return carregar(silencioso);
    }
    // 503: os dados da aba ainda não chegaram do computador da empresa (não é erro)
    const espera = e.status === 503;
    const msg = espera ? e.message.charAt(0).toUpperCase() + e.message.slice(1) : e.message;
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
  receita: (v) => fmt.moeda(v), mix: (v) => fmt.pct(v), inadimplencia: (v) => fmt.pct(v, 2),
  positivacao: (v) => fmt.num(v), devolucoes: (v) => fmt.pct(v, 2),
};

function renderSupervisores(d) {
  const cartoes = d.supervisores.map((s, k) => cartaoSupervisor(d, s, k + 1)).join("");
  return `<section class="pr-sups secao">${cartoes}</section>${comoSupervisores(d, d.supervisores.length + 2)}`;
}

function linhaIndicador(d, s, x) {
  const f = FORMATO[x.id];
  let alcance, regra;
  if ("dentro" in x) {
    alcance = x.realizado == null
      ? `<span class="fraco">${x.sem_dados ? "sem dados" : "sem base"}</span>`
      : `<span class="pr-teto ${x.dentro ? "sim" : "nao"}">${icone(x.dentro ? "certo" : "x")}${x.dentro ? "dentro" : "acima"}</span>`;
    regra = `até ${f(x.meta)}: ${fmt.pct(x.peso, 0)}`;
  } else {
    const cor = x.alcance == null || x.alcance + 1e-9 < x.minimo ? "var(--ruim-forte)" : x.alcance + 1e-9 >= 1 ? "var(--ok-forte)" : "var(--atencao-forte)";
    alcance = barraPct(x.alcance, cor);
    regra = `mín. ${fmt.pct(x.minimo, 0)} · até ${fmt.pct(x.peso, 0)}`;
  }
  const meta = x.ajustada
    ? `<span data-tt="${esc(`<div class='tt-t'>Meta ajustada à mão</div>A soma das metas dos vendedores seria ${f(x.meta_auto)}`)}">${f(x.meta)} <small class="pr-aj">ajustada</small></span>`
    : f(x.meta);
  return `<tr>
    <td class="esq"><b>${esc(x.titulo)}</b><small>${regra}</small></td>
    <td>${f(x.realizado)}</td>
    <td>${meta}</td>
    <td>${alcance}</td>
    <td class="pr-pontos">${fmt.pct(x.pontos, 1)}</td></tr>`;
}

function cartaoSupervisor(d, s, i) {
  const c = s.contas;
  const id = `sup-${s.estado}`;
  const aberto = estado.abertos.has(id);
  const contas = [
    ["Faturamento bruto do mês", fmt.moeda2(c.bruto)],
    ["− Devoluções (todos os motivos, sem as canceladas)", fmt.moeda2(c.devolucoes)],
    ["− Brindes", d.sem_brindes ? "ainda sem dados" : fmt.moeda2(c.brindes)],
    ["= Faturamento líquido", fmt.moeda2(c.liquido)],
    [`Líquido sem ${d.produtos_fora_mix.map((p) => p.id).join(", ")} (mix)`, fmt.moeda2(c.liquido_mix)],
    [`Faturamento líquido de ${esc(d.janela.rotulo)}`, fmt.moeda2(c.liquido_6m)],
    [`Em aberto, vencido até ${fmt.data(d.corte_vencimento)}`, fmt.moeda2(c.inadimplente)],
    ["Devoluções impróprias", fmt.moeda2(c.improprias_devolucoes)],
    ["Brindes impróprios", d.sem_brindes ? "ainda sem dados" : fmt.moeda2(c.improprias_brindes)],
  ];
  const vendedores = s.vendedores.map((v) => `<tr>
      <td class="esq">${esc(v.nome)}</td><td>${fmt.moeda(v.liquido)}</td><td>${fmt.pct(v.pct_mix)}</td>
      <td>${fmt.num(v.positivacao)}</td><td>${fmt.moeda(v.inadimplente)}</td><td>${fmt.moeda(v.improprias)}</td></tr>`).join("");
  return `
  <article class="cartao pr-sup entra" style="--i:${i}">
    <div class="pr-sup-cab">
      <div><span class="pr-estado">${esc(s.estado)}</span><h3>${esc(s.nome)}</h3>
        <small>${s.vendedores.length} vendedor${s.vendedores.length === 1 ? "" : "es"} com movimento na carteira · ${esc(d.mes.rotulo)}</small></div>
      <div class="pr-sup-valor">${seloSituacao(d)}<b data-contar="${s.premio}" data-fmt="moeda2">${fmt.moeda2(0)}</b>
        <small>${fmt.pct(s.pct, 1)} de ${fmt.moeda2(d.maximo)}</small></div>
    </div>
    <div class="pr-sup-barra"><i style="width:0" data-largura="${Math.min(1, s.pct) * 100}%"></i></div>
    <div class="tabela-rolagem pr-ind-rolagem">
      <table class="dados pr-ind">
        <thead><tr><th>Indicador</th><th>Realizado</th><th>Meta</th><th>Alcance</th><th>Pontos</th></tr></thead>
        <tbody>${s.indicadores.map((x) => linhaIndicador(d, s, x)).join("")}</tbody>
        <tfoot><tr><td>Total</td><td></td><td></td><td></td><td class="pr-pontos">${fmt.pct(s.pct, 1)}</td></tr></tfoot>
      </table>
    </div>
    <div class="pr-sup-acoes">
      <button class="btn" type="button" data-abrir="${id}" data-rotulo="Ver as contas" aria-expanded="${aberto}">${icone("recibo")}<span class="rot">${aberto ? "Esconder" : "Ver as contas"}</span></button>
    </div>
    <div class="pr-det" id="p-det-${id}"${aberto ? "" : " hidden"}>
      <div class="pr-contas">${contas.map(([a, b]) => `<div class="linha-r"><span>${a}</span><b>${b}</b></div>`).join("")}</div>
      <div class="tabela-rolagem pr-vend-rolagem">
        <table class="dados">
          <thead><tr><th>Carteira de</th><th>Líquido</th><th>Mix</th><th>Positivação</th><th>Inadimplente</th><th>Impróprias</th></tr></thead>
          <tbody>${vendedores || `<tr><td class="esq" colspan="6">Nenhum movimento na carteira.</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  </article>`;
}

function comoSupervisores(d, i) {
  const s = d.supervisores[0];
  const peso = (k) => fmt.pct(s.indicadores.find((x) => x.id === k).peso, 0);
  const minimo = (k) => fmt.pct(s.indicadores.find((x) => x.id === k).minimo, 0);
  const metas = (k, casas) => d.supervisores.map((x) => `${fmt.pct(x.indicadores.find((y) => y.id === k).meta, casas)} no ${x.estado}`).join(" e ");
  return `
  <section class="cartao secao entra metodo" style="--i:${i}">
    <details>
      <summary>
        <h3>${icone("info")}Como a premiação dos supervisores é calculada</h3>
        <span class="sub">A conta da página "Premiacao Supervisores" do Power BI, com as regras em vigor</span>
      </summary>
      <div class="metodo-corpo">
        <ol class="metodo-passos">
          <li><b>Carteira de hoje:</b> entram os clientes cujo vendedor no cadastro é do estado (pelas Configurações das
            metas ou pelo supervisor no ERP). Terceiros, o Edir e contas internas ficam fora. Só vendas, devoluções e
            brindes de cliente (sem funcionário, fornecedor ou produtor).</li>
          <li><b>Faturamento líquido (${peso("receita")}):</b> vendas do mês − devoluções não canceladas (todos os motivos,
            pela data de entrada) − brindes, sobre a meta. A meta é a soma das METAS FATURAMENTO dos vendedores do estado
            no mês, ou o valor ajustado à mão em Configurar. Abaixo de ${minimo("receita")} da meta, nada; acima,
            ${peso("receita")} × o alcance, no máximo ${peso("receita")}.</li>
          <li><b>Mix (${peso("mix")}):</b> o líquido sem ${d.produtos_fora_mix.map((p) => `${esc(p.nome)} (${p.id})`).join(", ")}
            ÷ o líquido, sobre a meta (${metas("mix", 0)}). Mínimo de ${minimo("mix")} de alcance.</li>
          <li><b>Inadimplência (${peso("inadimplencia")}):</b> títulos de venda a cliente emitidos de ${esc(d.janela.rotulo)},
            vencidos há ${d.dias_atraso} dias ou mais (até ${fmt.data(d.corte_vencimento)}) e ainda em aberto na data dos
            dados, ÷ o faturamento líquido desses 6 meses. Até a meta (${metas("inadimplencia", 2)}), ${peso("inadimplencia")};
            acima, nada. Como no Power BI, conta o que está em aberto hoje: o mês fechado muda quando um cliente paga depois.</li>
          <li><b>Positivação (${peso("positivacao")}):</b> clientes da carteira com venda no mês, sobre a soma das METAS
            CLIENTE dos vendedores do estado (ou o valor ajustado). Mínimo de ${minimo("positivacao")}.</li>
          <li><b>Devoluções impróprias (${peso("devolucoes")}):</b> devoluções e brindes com motivo
            ${d.motivos_improprios.map((m) => `<span title="${esc(m.nome)}">${m.id}</span>`).join(", ")} ÷ o faturamento
            bruto do mês. Até a meta (${metas("devolucoes", 1)}), ${peso("devolucoes")}; acima, nada.</li>
          <li><b>Prêmio:</b> a soma dos pontos × ${fmt.moeda2(d.maximo)}.</li>
        </ol>
        <h4>Diferenças em relação ao Power BI</h4>
        <ul class="metodo-passos">
          <li>As metas de faturamento e de positivação são a soma das metas dos vendedores do mês. No Power BI elas eram
            fixas (as de setembro/26: R$ 2.252.568 e 967 no BA, R$ 2.075.000 e 983 no ES).</li>
          <li>Só vendas a cliente: o Power BI ligava venda a funcionário ou fornecedor pelo código, que pode coincidir com o
            de um cliente.</li>
          <li>Os vendedores de cada estado vêm das Configurações das metas e do ERP, não de uma lista fixa de nomes.</li>
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
