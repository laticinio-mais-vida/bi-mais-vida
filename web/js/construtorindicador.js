// O "Indicador medido" das campanhas e dos objetivos da página Gestão: a predefinição (um tipo pronto ou uma
// combinação da Personalizada), como ela é calculada (com a janela de todos os indicadores), quem conta (base de
// clientes), a comparação do crescimento (só nos objetivos), os produtos com o preço-alvo (preço médio) e os filtros
// de produto e de cliente. Monta em qualquer contêiner; quem usa lê valor() na hora de gravar. A conferência de
// verdade é do servidor (bi/gestao.py validar).
import { esc, fmt, icone } from "./util.js";
import { multiSelecao } from "./multiselecao.js";
import { BASES, COMO_META, COMPARAR, FILTROS, FILTROS_PRODUTO, NOME_GRUPO, PRESETS, comoCalcula, presetDe } from "./indicadores.js";

const aceitaBase = (pr) => ["positivacao", "mix_medio", "frequencia"].includes(pr.metrica)
  || (pr.metrica === "personalizada" && ["total", "por_cliente"].includes(pr.forma));
const semFiltroProduto = (pr) => pr.metrica === "efetividade" || pr.metrica === "preco_medio";
const reais2 = (v) => "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
let janelaComo = null;

// A janela "Como cada indicador é calculado": todos os indicadores (o atual em destaque) e, nas campanhas, a base, a
// meta e o % da meta. Abre por cima de outra janela (a do objetivo).
export function abrirComoCalcula(atual, objetivo = false) {
  if (!janelaComo) {
    janelaComo = document.createElement("dialog");
    janelaComo.className = "dialogo ci-como-janela";
    janelaComo.setAttribute("aria-labelledby", "ci-como-titulo");
    document.body.appendChild(janelaComo);
    janelaComo.addEventListener("click", (e) => { if (e.target.closest("[data-fechar]")) janelaComo.close(); });
  }
  const item = ([nome, conta, detalhe], destaque) => `<div class="${destaque ? "atual" : ""}"><dt>${esc(nome)}</dt>
    <dd>${conta ? `<b>${esc(conta)}</b>` : ""}${detalhe ? ` ${esc(detalhe)}` : ""}</dd></div>`;
  const lista = PRESETS.filter((x) => objetivo || !x.objetivo)
    .map((x) => { const c = comoCalcula(x, objetivo); return item([x.nome, c.conta, c.detalhe], x.id === atual); }).join("");
  janelaComo.innerHTML = `<h2 id="ci-como-titulo">${icone("info")}Como cada indicador é calculado</h2>
    <p class="sub">${objetivo ? "No objetivo, a conta é da equipe toda, sem repetir clientes entre os vendedores."
      : "Na campanha, a conta é de cada vendedor (a efetividade e a carteira, pelos clientes da carteira dele)."} As vendas seguem as regras das metas.</p>
    <dl class="ci-como-lista">${lista}</dl>
    ${objetivo ? "" : `<h3>Base, meta e % da meta</h3><dl class="ci-como-lista">${COMO_META.map(([n, d]) => item([n, "", d])).join("")}</dl>`}
    <div class="dialogo-acoes"><button class="btn primario" type="button" data-fechar>Entendi</button></div>`;
  janelaComo.showModal();
  janelaComo.querySelector(".atual")?.scrollIntoView({ block: "center" });
}

// Valores de texto (linhas, UFs…) vão para a lista de seleção por posição: ela trabalha com números.
function opcoesFiltro(id, cat) {
  if (id === "produtos") {
    return cat.produtos.map((p) => ({ id: p.id, nome: p.nome, grupo: p.grupo === "mussarela" ? "mussarela" : `cat:${p.categoria || ""}`,
      detalhe: `código ${p.id}${p.unidade ? ` · ${p.unidade}` : ""}${p.linha ? ` · ${p.linha}` : ""}` }));
  }
  const valores = { linhas: cat.linhas, categorias: cat.categorias, grupos: cat.grupos, ufs: cat.ufs, segmentos: cat.segmentos,
                    areas: cat.areas || [] }[id];
  return valores.map((v, i) => ({ id: i, nome: id === "grupos" ? NOME_GRUPO[v] || v : v, valor: v }));
}

// el: onde vão a predefinição e quem conta; filtrosEm e precosEm: onde vão os filtros e os preços (padrão: el).
// inicial: {metrica, parametros, filtros, metas_produto}; objetivo: oferece o crescimento; aoMudar: avisa quem usa.
export function construtorIndicador(el, { catalogo: cat, inicial = {}, nomes = {}, objetivo = false, filtrosEm = null,
                                         precosEm = null, aoMudar = () => {} }) {
  let preset = presetDe(inicial.metrica || "positivacao", inicial.parametros || {});
  if (preset.objetivo && !objetivo) preset = PRESETS[0];
  const p = { clientes: "todos", ...(inicial.parametros || {}) };
  let metasProduto = new Map((inicial.metas_produto || []).map((x) => [x.id, x.meta]));
  const filtros = {};
  const grupos = [{ id: "mussarela", nome: "Mussarela" }, ...cat.categorias.map((c) => ({ id: `cat:${c}`, nome: c })), { id: "cat:", nome: "Demais produtos" }];
  const nomeProduto = (id) => nomes?.produtos?.[id] || cat.produtos.find((x) => x.id === id)?.nome || `produto ${id}`;

  el.innerHTML = `
    <label class="campo-form ci-preset"><span>Indicador medido</span>
      <span class="campo"><select data-ci-preset aria-label="Indicador medido" style="padding-left:14px">${PRESETS.filter((x) => objetivo || !x.objetivo)
        .map((x) => `<option value="${x.id}" ${x.id === preset.id ? "selected" : ""}>${esc(x.nome)}</option>`).join("")}</select></span></label>
    <p class="ci-como" data-ci-como aria-live="polite"></p>
    <div class="ci-sub" data-ci-sub></div>`;
  (precosEm || el).insertAdjacentHTML("beforeend", `<div class="ci-precos" data-ci-precos hidden>
      <span class="cf-rotulo">Produtos e preços-alvo <small>(R$ por unidade do produto)</small></span>
      <div class="filtros"><div data-ci-precos-ms></div></div><div class="cf-precos" data-ci-precos-lista></div></div>`);
  (filtrosEm || el).insertAdjacentHTML("beforeend", `<div class="ci-filtros">
      <span class="cf-rotulo"><span data-ci-rotulo-filtros>Produtos e clientes que contam</span> <small>(nada escolhido = tudo)</small></span>
      <div class="filtros cf-filtros">${FILTROS.map((f) => `<div data-ci-f="${f.id}"></div>`).join("")}</div>
      <p class="usu-nota" data-ci-dica hidden></p></div>`);
  const achar = (sel) => el.querySelector(sel) || (precosEm || el).querySelector(sel) || (filtrosEm || el).querySelector(sel);

  // filtros
  for (const def of FILTROS) {
    const itens = opcoesFiltro(def.id, cat);
    const atuais = inicial.filtros || {};
    const marcados = def.id === "produtos" ? (atuais.produtos || [])
      : (atuais[def.id] || []).map((v) => itens.findIndex((i) => i.valor === v)).filter((i) => i >= 0);
    // produto escolhido que não vendeu nos últimos 12 meses continua na lista, para poder tirar
    if (def.id === "produtos") {
      for (const pid of marcados) if (!itens.some((i) => i.id === pid)) itens.push({ id: pid, nome: nomeProduto(pid), grupo: "cat:", detalhe: `código ${pid}` });
    }
    filtros[def.id] = { itens, ms: multiSelecao(achar(`[data-ci-f="${def.id}"]`), {
      rotulo: def.rotulo, icone: def.icone, todos: def.todos, plural: def.plural, busca: `Buscar ${def.rotulo.toLowerCase()}`,
      semBusca: def.semBusca, classe: "curto", itens, selecionados: marcados, nomesAte: 2,
      grupos: def.id === "produtos" ? grupos : undefined, aoAplicar: () => { dicas(); aoMudar(); },
    }) };
  }

  // preço médio: os produtos e o preço-alvo de cada um, com o preço dos últimos 90 dias de dica
  const itensPreco = opcoesFiltro("produtos", cat);
  for (const pid of metasProduto.keys()) if (!itensPreco.some((i) => i.id === pid)) itensPreco.push({ id: pid, nome: nomeProduto(pid), grupo: "cat:", detalhe: `código ${pid}` });
  multiSelecao(achar("[data-ci-precos-ms]"), {
    rotulo: "Produtos", icone: "caixa", todos: "Escolha os produtos", plural: "produtos", busca: "Buscar produto",
    classe: "curto", itens: itensPreco, selecionados: [...metasProduto.keys()], nomesAte: 2, grupos,
    aoAplicar: (ids) => {
      const novo = new Map();
      for (const id of ids) novo.set(id, metasProduto.get(id) ?? null);
      metasProduto = novo;
      desenharPrecos();
      aoMudar();
    },
  });

  function desenharPrecos() {
    const alvo = achar("[data-ci-precos-lista]");
    const porId = new Map(cat.produtos.map((x) => [x.id, x]));
    if (!metasProduto.size) {
      alvo.innerHTML = `<p class="usu-nota">${icone("info")}<span>Escolha os produtos e dê o preço-alvo de cada um. ${objetivo
        ? "O índice da equipe compara o que ela vendeu com o que seria nos preços-alvo (100% = no alvo)."
        : "O % da meta de cada vendedor é o aumento de preço feito sobre a base dele ÷ o aumento até o preço-alvo."}</span></p>`;
      return;
    }
    alvo.innerHTML = [...metasProduto].map(([id, meta]) => {
      const x = porId.get(id);
      const un = (x?.unidade || "").toLowerCase();
      return `<div class="cf-preco" data-id="${id}">
        <span class="n">${esc(x?.nome || nomeProduto(id))}<small>código ${id}${un ? ` · ${esc(un)}` : ""}${x?.preco_90d ? ` · média dos últimos 90 dias: ${reais2(x.preco_90d)}` : ""}</small></span>
        <input class="cf-meta-v" type="number" min="0" step="0.01" inputmode="decimal" aria-label="Preço-alvo de ${esc(x?.nome || id)}"
          placeholder="${x?.preco_90d ? fmt.num(x.preco_90d, 2) : "R$"}" value="${meta ?? ""}"><span class="fraco">R$${un ? `/${esc(un)}` : ""}</span>
      </div>`;
    }).join("");
    alvo.querySelectorAll(".cf-preco input").forEach((i) => i.addEventListener("input", () => {
      const v = i.value.trim();
      metasProduto.set(Number(i.closest(".cf-preco").dataset.id), v === "" ? null : Number(v));
      aoMudar();
    }));
  }

  // quem conta, os dias sem compra e a comparação do crescimento; e o que aparece ou some com o tipo
  function desenharSub() {
    const sel = (k, rotulo, opcoes, valor) => `<label class="campo-form"><span>${esc(rotulo)}</span>
      <span class="campo"><select data-p="${k}" style="padding-left:14px">${Object.entries(opcoes).map(([id, n]) =>
        `<option value="${id}" ${id === valor ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></span></label>`;
    let html = "";
    if (preset.forma === "crescimento") html += sel("comparar", "Comparar com", COMPARAR, p.comparar || "periodo_anterior");
    if (aceitaBase(preset)) {
      html += sel("clientes", "Quem conta", BASES, p.clientes || "todos");
      if (p.clientes === "recuperados") {
        html += `<label class="campo-form"><span>Sem compra há pelo menos <small>(dias)</small></span>
          <input type="number" data-p="dias_sem_compra" min="1" max="730" step="1" value="${p.dias_sem_compra || 90}"></label>`;
      }
    }
    const sub = el.querySelector("[data-ci-sub]");
    sub.innerHTML = html;
    sub.hidden = !html;
    el.querySelector("[data-ci-como]").innerHTML = `${icone("info")}<span><b>Como é calculado:</b> ${esc(comoCalcula(preset, objetivo).conta)}
      <button type="button" class="ge-link" data-ci-todos>Ver detalhes</button></span>`;
    for (const id of FILTROS_PRODUTO) achar(`[data-ci-f="${id}"]`).hidden = semFiltroProduto(preset);
    achar("[data-ci-rotulo-filtros]").textContent = semFiltroProduto(preset) ? "Clientes que contam" : "Produtos e clientes que contam";
    achar("[data-ci-precos]").hidden = preset.metrica !== "preco_medio";
    dicas();
  }

  function unidadeVolume() {
    const escolhidos = filtros.produtos ? filtros.produtos.ms.valor() : [];
    return [...new Set(cat.produtos.filter((x) => escolhidos.includes(x.id)).map((x) => x.unidade))];
  }

  // Explica o que cada tipo pede (volume: uma unidade só; nunca/já compraram: os produtos).
  function dicas() {
    const dica = achar("[data-ci-dica]");
    const comProduto = FILTROS_PRODUTO.some((id) => filtros[id]?.ms.valor().length);
    const textos = [];
    if (preset.medida === "volume") {
      const u = unidadeVolume();
      textos.push(u.length > 1 ? `Os produtos escolhidos têm unidades diferentes (${u.join(", ")}): em volume use uma só.`
        : "Em volume, escolha produtos, linha, categoria ou grupo com uma unidade só (a quantidade não soma kg com unidade).");
    }
    if (preset.forma === "crescimento") textos.push("A meta é o crescimento sobre o período de comparação, para a equipe toda.");
    if (preset.metrica === "mix_medio") textos.push("Os produtos escolhidos são o mix medido; nada escolhido = todos os produtos.");
    if (["nunca_compraram", "ja_compraram"].includes(p.clientes) && aceitaBase(preset) && !comProduto) {
      textos.push("Para contar quem nunca ou já comprou, escolha os produtos.");
    }
    dica.innerHTML = textos.length ? `${icone("info")}<span>${esc(textos.join(" "))}</span>` : "";
    dica.hidden = !textos.length;
  }

  el.querySelector("[data-ci-preset]").addEventListener("change", (e) => {
    preset = PRESETS.find((x) => x.id === e.target.value);
    desenharSub();
    aoMudar({ preset: true });
  });
  el.querySelector("[data-ci-como]").addEventListener("click", (e) => {
    if (e.target.closest("[data-ci-todos]")) abrirComoCalcula(preset.id, objetivo);
  });
  el.querySelector("[data-ci-sub]").addEventListener("change", (e) => {
    const k = e.target.dataset.p;
    if (!k) return;
    p[k] = e.target.type === "number" ? Number(e.target.value) || null : e.target.value;
    desenharSub();
    aoMudar();
  });
  desenharPrecos();
  desenharSub();

  function parametros() {
    const s = {};
    if (preset.metrica === "personalizada") {
      Object.assign(s, { medida: preset.medida, forma: preset.forma });
      if (preset.forma === "crescimento") s.comparar = p.comparar || "periodo_anterior";
    }
    if (aceitaBase(preset)) {
      s.clientes = p.clientes || "todos";
      if (s.clientes === "recuperados") s.dias_sem_compra = p.dias_sem_compra || 90;
    }
    return s;
  }

  function valoresFiltros() {
    const saida = {};
    for (const [id, { itens, ms }] of Object.entries(filtros)) {
      if (semFiltroProduto(preset) && FILTROS_PRODUTO.includes(id)) continue; // escondidos neste tipo
      const v = ms.valor();
      if (!v.length) continue;
      saida[id] = id === "produtos" ? v : v.map((i) => itens.find((x) => x.id === i)?.valor).filter((x) => x != null);
    }
    return saida;
  }

  return {
    preset: () => preset,
    // o descritor que a página usa para os textos do alvo (o servidor manda o completo depois de gravar)
    descritor: () => ({ tipo: preset.metrica, medida: preset.medida, forma: preset.forma, formato: preset.formato,
                        meta_em_pct: !!preset.pct, unidade: preset.medida === "volume" ? (unidadeVolume()[0] || "") : "", sufixo: "" }),
    unidadeAlvo: () => (preset.medida === "volume" && preset.forma !== "crescimento"
      ? `${(unidadeVolume()[0] || "quantidade").toLowerCase()}${preset.forma === "por_cliente" ? " por cliente" : ""}` : preset.alvo),
    valor: () => ({ metrica: preset.metrica, parametros: parametros(), filtros: valoresFiltros(),
                    metas_produto: preset.metrica === "preco_medio" ? [...metasProduto].map(([id, meta]) => ({ id, meta })) : [] }),
    temFiltros: () => Object.keys(valoresFiltros()).length > 0,
  };
}
