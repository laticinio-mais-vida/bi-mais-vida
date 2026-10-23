// O que as campanhas e os objetivos da página Gestão medem (bi/indicadores.py), para a página e para o rascunho do
// Assistente: os tipos, as predefinições do "Indicador medido", os filtros, a janela da base e como formatar valores,
// metas e diferenças. A conta é toda no servidor, que manda o descritor do indicador (nome, formato, como ler a meta).
import { MESES, fmt } from "./util.js";

// Os tipos (bi/indicadores.py TIPOS) e os blocos da Personalizada.
export const TIPOS = {
  positivacao: { nome: "Positivação", icone: "pessoas", cor: "var(--k-cli)" },
  mix_medio: { nome: "Mix médio", icone: "etiqueta", cor: "var(--s-out)" },
  efetividade: { nome: "Efetividade", icone: "alvo", cor: "var(--s-ritmo)" },
  frequencia: { nome: "Frequência", icone: "calendario", cor: "var(--laranja)" },
  preco_medio: { nome: "Preço médio", icone: "moeda", cor: "var(--s-mus)" },
  personalizada: { nome: "Personalizada", icone: "ajustes", cor: "var(--s-fat)" },
};
export const MEDIDAS = {
  faturamento: { nome: "Faturamento (R$)", icone: "moeda", cor: "var(--s-fat)" },
  volume: { nome: "Volume (quantidade)", icone: "caixa", cor: "var(--s-mus)" },
  clientes: { nome: "Clientes positivados", icone: "pessoas", cor: "var(--k-cli)" },
  produtos: { nome: "Mix (produtos distintos)", icone: "etiqueta", cor: "var(--s-out)" },
};
export const COMPARAR = { periodo_anterior: "O período anterior", ano_anterior: "O mesmo período do ano anterior" };
export const BASES = { todos: "Todos os clientes", novos: "Só clientes novos (sem compra antes do início)", recuperados: "Só clientes recuperados",
                       nunca_compraram: "Quem nunca comprou os produtos escolhidos", ja_compraram: "Quem já comprava os produtos escolhidos" };
export const LEGADOS = { faturamento: ["faturamento", "total"], volume: ["volume", "total"], mix: ["produtos", "total"] };
export const ABERTURAS = { area: "Área comercial", segmento: "Segmento", produto: "Produto" };
export const FILTROS_PRODUTO = ["produtos", "linhas", "categorias", "grupos"];
export const FILTROS = [
  { id: "produtos", rotulo: "Produtos", icone: "caixa", todos: "Todos os produtos", plural: "produtos" },
  { id: "linhas", rotulo: "Linhas", icone: "etiqueta", todos: "Todas as linhas", plural: "linhas" },
  { id: "categorias", rotulo: "Categorias", icone: "funil", todos: "Todas as categorias", plural: "categorias" },
  { id: "grupos", rotulo: "Grupo", icone: "queijo", todos: "Mussarela e outras", plural: "grupos", semBusca: true },
  { id: "ufs", rotulo: "UF do cliente", icone: "mapa", todos: "Todas as UFs", plural: "UFs", semBusca: true },
  { id: "segmentos", rotulo: "Segmentos", icone: "pessoas", todos: "Todos os segmentos", plural: "segmentos" },
  { id: "areas", rotulo: "Áreas comerciais", icone: "mapa", todos: "Todas as áreas", plural: "áreas" },
];
export const NOME_GRUPO = { mussarela: "Mussarela", outras: "Outras linhas" };

// O "Indicador medido": cada opção é um tipo pronto ou uma combinação da Personalizada. alvo: a unidade da meta;
// pct: a meta é em % (80 = 80%); objetivo: só nos objetivos (numa campanha a meta já sai da base).
export const PRESETS = [
  { id: "positivacao", metrica: "positivacao", nome: "Positivação (clientes com compra)", rotulo: "Positivação", alvo: "clientes", formato: "clientes" },
  { id: "mix_medio", metrica: "mix_medio", nome: "Mix médio (produtos por cliente)", rotulo: "Mix", alvo: "produtos por cliente", formato: "razao" },
  { id: "efetividade", metrica: "efetividade", nome: "Efetividade (pedidos ÷ visitas)", rotulo: "Efetividade", alvo: "%", pct: true, formato: "pct" },
  { id: "frequencia", metrica: "frequencia", nome: "Frequência (semanas com compra)", rotulo: "Frequência", alvo: "semanas por cliente", formato: "razao" },
  { id: "preco_medio", metrica: "preco_medio", nome: "Preço médio por produto", rotulo: "Preço", alvo: "", pct: true, formato: "pct" },
  { id: "faturamento:total", metrica: "personalizada", medida: "faturamento", forma: "total", nome: "Faturamento (R$)", rotulo: "Faturamento", alvo: "R$", formato: "moeda" },
  { id: "faturamento:por_cliente", metrica: "personalizada", medida: "faturamento", forma: "por_cliente", nome: "Venda média por cliente (R$)", rotulo: "Venda média", alvo: "R$ por cliente", formato: "moeda" },
  { id: "volume:total", metrica: "personalizada", medida: "volume", forma: "total", nome: "Volume (quantidade)", rotulo: "Volume", alvo: "", formato: "quantidade" },
  { id: "volume:por_cliente", metrica: "personalizada", medida: "volume", forma: "por_cliente", nome: "Volume por cliente", rotulo: "Volume/cliente", alvo: "por cliente", formato: "quantidade" },
  { id: "clientes:pct_carteira", metrica: "personalizada", medida: "clientes", forma: "pct_carteira", nome: "Cobertura da carteira (%)", rotulo: "Carteira", alvo: "% da carteira", pct: true, formato: "pct" },
  { id: "produtos:total", metrica: "personalizada", medida: "produtos", forma: "total", nome: "Produtos distintos vendidos", rotulo: "Produtos", alvo: "produtos", formato: "produtos" },
  { id: "faturamento:crescimento", metrica: "personalizada", medida: "faturamento", forma: "crescimento", nome: "Crescimento do faturamento (%)", rotulo: "Crescimento", alvo: "% de crescimento", pct: true, formato: "moeda", objetivo: true },
  { id: "volume:crescimento", metrica: "personalizada", medida: "volume", forma: "crescimento", nome: "Crescimento do volume (%)", rotulo: "Crescimento", alvo: "% de crescimento", pct: true, formato: "quantidade", objetivo: true },
  { id: "clientes:crescimento", metrica: "personalizada", medida: "clientes", forma: "crescimento", nome: "Crescimento da positivação (%)", rotulo: "Crescimento", alvo: "% de crescimento", pct: true, formato: "clientes", objetivo: true },
];

// Como cada indicador é calculado (o informativo do formulário e do detalhe da campanha), pelas contas de
// bi/indicadores.py. conta: a fórmula numa linha; detalhe: o resto; objetivo: o texto do objetivo, quando muda.
const MESMA_UNIDADE = "Escolha produtos da mesma unidade (a quantidade não soma kg com unidade).";
const CRESCIMENTO = {
  conta: "O indicador no período ÷ o mesmo indicador no período de comparação, menos 1.",
  detalhe: "Compara com o período anterior (do mesmo tamanho, logo antes; em meses cheios, os mesmos meses logo antes) ou com o mesmo período do ano anterior. Só nos objetivos.",
};
export const COMO_CALCULA = {
  positivacao: {
    conta: "Clientes distintos que compraram no período.",
    detalhe: "Cada cliente conta uma vez. Com produtos, linhas ou categorias escolhidos, só quem comprou esses produtos. Em “Quem conta” dá para contar só os clientes novos, os recuperados (sem compra há N dias antes do início) ou quem nunca ou já comprava os produtos escolhidos.",
  },
  mix_medio: {
    conta: "Produtos da campanha levados, somados cliente a cliente, ÷ clientes positivados.",
    detalhe: "Para cada cliente, conta quantos produtos diferentes da campanha ele levou e soma todos; divide pelos clientes que compraram qualquer produto, como no Power BI. Ex.: 4 clientes compraram, 2 levaram 3 produtos da campanha e 2 não levaram nenhum: 6 ÷ 4 = 1,5. Sem produto escolhido, contam todos os produtos.",
  },
  efetividade: {
    conta: "A média dos dias: pedidos na rota do dia ÷ visitas esperadas no dia.",
    detalhe: "Pela carteira do vendedor. As visitas esperadas de um dia são os clientes ativos das áreas atendidas nesse dia (Gestão › Configurar), pela frequência de compra do cadastro: os semanais sempre, os quinzenais sem compra nos 7 dias antes e os mensais sem compra nos 21 dias antes; quem não estava previsto e comprou no dia também entra nas visitas. Só contam os pedidos de clientes das áreas atendidas naquele dia (o pedido fora de rota fica de fora). A efetividade do período é a média dos dias com visita esperada: o fim de semana e os clientes em áreas sem dia ficam de fora.",
  },
  frequencia: {
    conta: "Semanas com compra, somadas cliente a cliente, ÷ clientes positivados.",
    detalhe: "Para cada cliente, conta em quantas semanas ele comprou (de domingo a sábado, cortadas na virada do mês, como no Power BI) e soma todos; divide pelos clientes que compraram. Ex.: um cliente comprou em 3 semanas e outro em 1: 4 ÷ 2 = 2,0.",
  },
  preco_medio: {
    conta: "Aumento de preço feito ÷ aumento pedido, do preço de cada vendedor na base até o preço-alvo.",
    detalhe: "O preço médio de um produto é a venda líquida ÷ a quantidade. O % da meta compara quanto o preço subiu desde a base do vendedor com quanto precisava subir até o preço-alvo: base R$ 10, alvo R$ 20 e agora R$ 15 = 50%. Com vários produtos, os aumentos são somados em R$, nas quantidades vendidas agora. Produto que já estava no alvo na base só desconta se cair abaixo dele. A meta própria troca o preço-alvo de um vendedor.",
    objetivo: {
      conta: "O que a equipe vendeu ÷ o que venderia, nas mesmas quantidades, nos preços-alvo.",
      detalhe: "O preço médio de um produto é a venda líquida ÷ a quantidade. 100% = a equipe vendeu no preço-alvo; acima disso, vendeu mais caro.",
    },
  },
  "faturamento:total": { conta: "Venda líquida em R$, descontando as devoluções, como nas metas." },
  "faturamento:por_cliente": { conta: "Venda líquida em R$ ÷ clientes positivados." },
  "volume:total": { conta: "Quantidade vendida, na unidade dos produtos, descontando as devoluções.", detalhe: MESMA_UNIDADE },
  "volume:por_cliente": { conta: "Quantidade vendida ÷ clientes positivados.", detalhe: MESMA_UNIDADE },
  "clientes:pct_carteira": {
    conta: "Clientes da carteira que compraram ÷ clientes ativos da carteira.",
    detalhe: "Pela carteira do vendedor: vale a compra feita com qualquer vendedor.",
  },
  "produtos:total": { conta: "Produtos diferentes vendidos no período." },
  "faturamento:crescimento": CRESCIMENTO, "volume:crescimento": CRESCIMENTO, "clientes:crescimento": CRESCIMENTO,
};
// A base, a meta e o % da meta das campanhas (o fim do informativo).
export const COMO_META = [
  ["Base", "O mesmo indicador, medido no período fechado escolhido (semana, quinzena, mês…): o último antes do início da campanha."],
  ["Meta", "Número: o valor que cada vendedor precisa atingir. Percentual: a base de cada um + X%. A meta própria troca a de um vendedor."],
  ["% da meta", "O resultado de cada vendedor ÷ a meta dele. Na barra da campanha: a soma dos resultados ÷ a soma das metas nos indicadores de total (positivação, faturamento, volume, produtos) e a média do % de cada um nos de média (mix, efetividade, frequência, por cliente, carteira); no preço médio, os aumentos de todos somados em R$."],
];
export function comoCalcula(preset, objetivo = false) {
  const c = COMO_CALCULA[preset?.id] || { conta: "" };
  return objetivo && c.objetivo ? c.objetivo : c;
}

// A predefinição de uma ação gravada (ou rascunho): o tipo e, na Personalizada, a medida e a forma.
export function presetDe(metrica, p = {}) {
  const legado = LEGADOS[metrica];
  if (legado) return PRESETS.find((x) => x.id === legado.join(":"));
  if (metrica !== "personalizada") return PRESETS.find((x) => x.id === metrica) || PRESETS[0];
  return PRESETS.find((x) => x.id === `${p.medida}:${p.forma || "total"}`) || PRESETS.find((x) => x.id === "faturamento:total");
}

// A meta da campanha: Número (o valor que cada um precisa atingir) ou Percentual (a base de cada um + X%). O "base + N"
// só aparece ao editar uma campanha de antes que o usa.
export const METAS = { fixo: "Número", pct: "Percentual" };
export const META_ANTIGA = { mais: "Quanto a mais sobre a base (antigo)" };

// A base (bi/indicadores.py PERIODOS_BASE e janela_fechada): o último período fechado que termina antes do início.
// "logo_antes": a regra das campanhas de antes (o mesmo tamanho da campanha, logo antes do início).
export const PERIODOS_BASE = { semana: "Semana", quinzena: "Quinzena", mes: "Mês", trimestre: "Trimestre", semestre: "Semestre", ano: "Ano" };
export const BASE_ANTIGA = "logo_antes";
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// [início, fim] da base, em AAAA-MM-DD. Semana de segunda a domingo; quinzena de 1 a 15 ou de 16 ao fim do mês.
export function janelaFechada(inicio, periodo) {
  const [a, m, d] = inicio.split("-").map(Number);
  if (periodo === "semana") {
    const ontem = new Date(a, m - 1, d - 1);
    const fim = new Date(a, m - 1, d - 1 - ontem.getDay()); // o último domingo antes do início (getDay: domingo = 0)
    return [iso(new Date(fim.getFullYear(), fim.getMonth(), fim.getDate() - 6)), iso(fim)];
  }
  if (periodo === "quinzena") {
    if (d > 15) return [iso(new Date(a, m - 1, 1)), iso(new Date(a, m - 1, 15))];
    return [iso(new Date(a, m - 2, 16)), iso(new Date(a, m - 1, 0))];
  }
  const meses = { mes: 1, trimestre: 3, semestre: 6, ano: 12 }[periodo];
  const primeiro = Math.floor((m - 1) / meses) * meses; // o mês (0 a 11) em que começa o período do início
  return [iso(new Date(a, primeiro - meses, 1)), iso(new Date(a, primeiro, 0))];
}

// "setembro/2026", "jul a set/2026", "12/10 a 18/10", "2025"; sem período, as datas e a regra de antes.
export function textoPeriodoBase(periodo, de, ate) {
  if (!de || !ate) return "";
  const [a, m] = de.split("-").map(Number), mf = Number(ate.split("-")[1]);
  if (!periodo || periodo === BASE_ANTIGA) return `${fmt.dataCurta(de)} a ${fmt.data(ate)} (o mesmo tamanho, logo antes)`;
  if (periodo === "mes") return `${MESES[m - 1]}/${a}`;
  if (periodo === "ano") return String(a);
  if (periodo === "trimestre" || periodo === "semestre") return `${MESES[m - 1].slice(0, 3)} a ${MESES[mf - 1].slice(0, 3)}/${ate.slice(0, 4)}`;
  return `${fmt.dataCurta(de)} a ${fmt.dataCurta(ate)}`;
}

// A meta de um vendedor na unidade do valor (percentuais em fração), como gestao.alvo_de: Número = a meta; Percentual
// = a base + X%; sem base (ou base 0 no Percentual), não há meta. Clientes e produtos arredondam para cima.
export function alvoDe(ind, tipo, base, meta) {
  if (ind.tipo === "preco_medio") return 1;
  const n = Number(meta), escala = ind.meta_em_pct ? 100 : 1;
  if (meta == null || meta === "" || isNaN(n) || !n) return null;
  if (tipo === "fixo") return n / escala;
  if (base == null || (tipo === "pct" && !base)) return null;
  const alvo = tipo === "mais" ? base + n / escala : base * (1 + n / 100);
  return ["clientes", "produtos"].includes(ind.formato) ? Math.ceil(alvo - 1e-9) : alvo;
}

// A cor do andamento contra a meta, num degradê sem degraus: vermelho até 50%, passando pelo laranja até o amarelo em
// 80% e pelo verde-amarelado até o verde em 100%; acima disso, um verde cada vez mais intenso até 150%. A mistura é em
// oklch (vermelho → amarelo passa pelo laranja, sem ficar barrento) e usa as cores do tema (claro ou escuro).
const DEGRADE_META = [[50, "var(--ruim-forte)"], [80, "var(--atencao-forte)"], [100, "var(--ok-forte)"], [150, "var(--ok-intenso)"]];
export function corMeta(pct) {
  if (pct == null || isNaN(pct)) return "var(--linha-forte)";
  const p = pct * 100;
  if (p <= DEGRADE_META[0][0]) return DEGRADE_META[0][1];
  for (let i = 1; i < DEGRADE_META.length; i++) {
    const [ate, cor] = DEGRADE_META[i], [de, antes] = DEGRADE_META[i - 1];
    if (p < ate) return `color-mix(in oklch, ${cor} ${Math.round(((p - de) / (ate - de)) * 100)}%, ${antes})`;
  }
  return DEGRADE_META[DEGRADE_META.length - 1][1];
}

// De 0 (até 100%) a 1 (150% ou mais): o quanto a meta foi passada (o CSS usa em --i para reforçar o fundo e o brilho).
export function intensidadeMeta(pct) {
  if (pct == null || isNaN(pct)) return 0;
  return Math.max(0, Math.min(1, (Math.round(pct * 100) - 100) / 50));
}

// Ícone e cor: o do tipo ou, na Personalizada, o da medida.
export function visual(ind) {
  return (ind?.tipo === "personalizada" ? MEDIDAS[ind.medida] : TIPOS[ind?.tipo]) || { icone: "quadro", cor: "var(--acento)" };
}

// O descritor de um rascunho de antes dos tipos novos (faturamento, volume, mix, positivação).
export function descritorLegado(r) {
  const [medida, forma] = LEGADOS[r.metrica] || [];
  if (medida) {
    return { tipo: "personalizada", medida, forma, comportamento: "soma", meta_em_pct: false, sufixo: "", casas: 0, unidade: r.unidade || "",
             nome: { faturamento: "Faturamento", volume: "Volume", produtos: "Mix de produtos" }[medida],
             formato: { faturamento: "moeda", volume: "quantidade", produtos: "produtos" }[medida] };
  }
  return { tipo: r.metrica, nome: TIPOS[r.metrica]?.nome || r.metrica, formato: r.metrica === "positivacao" ? "clientes" : "razao",
           comportamento: "soma", meta_em_pct: false, sufixo: "", casas: 0, unidade: "" };
}

// Valor no formato do indicador (curto: para etiquetas e barras). Percentuais vêm em fração (0,8 = 80%).
export function valorIndicador(ind, v, unidade = "", curto = false) {
  if (v == null || isNaN(v)) return "—";
  const suf = !curto && ind.sufixo ? ` ${ind.sufixo}` : "";
  switch (ind.formato) {
    case "moeda": return (ind.casas && !curto ? `R$ ${fmt.num(v, 2)}` : curto ? fmt.moedaC(v) : fmt.moeda(v)) + suf;
    case "quantidade": {
      const u = (unidade || ind.unidade || "").toLowerCase();
      return `${fmt.num(v, Math.abs(v) >= 100 ? 0 : 1)}${u ? " " + u : ""}${suf}`;
    }
    case "pct": return fmt.pct(v);
    case "razao": return `${fmt.num(v, ind.casas || 2)}${suf}`;
    default: {
      const n = Math.round(v);
      const nome = ind.formato === "clientes" ? (n === 1 ? "cliente" : "clientes") : (n === 1 ? "produto" : "produtos");
      return `${fmt.num(n)} ${nome}`;
    }
  }
}

// A diferença sobre a base, com sinal ("+1,1", "−R$ 300", "+2,5 p.p.").
export function deltaTexto(ind, d, unidade = "") {
  if (d == null || isNaN(d)) return "";
  const s = d > 0 ? "+" : d < 0 ? "−" : "";
  const a = Math.abs(d);
  switch (ind.formato) {
    case "moeda": return `${s}${fmt.moedaC(a)}`;
    case "pct": return `${s}${fmt.num(a * 100, 1)} p.p.`;
    case "quantidade": { const u = (unidade || ind.unidade || "").toLowerCase(); return `${s}${fmt.num(a, a >= 100 ? 0 : 1)}${u ? " " + u : ""}`; }
    case "razao": return `${s}${fmt.num(a, a < 1 ? 2 : 1)}`;
    default: return `${s}${fmt.num(Math.round(a))}`;
  }
}

// A meta como a pessoa digitou (percentual em pontos: 80 = 80%; crescimento: +10%).
export function metaDigitada(ind, v, unidade = "") {
  if (!ind.meta_em_pct) return valorIndicador(ind, v, unidade);
  return ind.forma === "crescimento" ? `+${fmt.num(v, 1)}%` : `${fmt.num(v, 1)}%`;
}

// Como a meta da campanha aparece ("+10% sobre a base de cada um", "80% para cada um", "+1 sobre a base", nas antigas).
export function textoAlvo(ind, alvoTipo, meta, unidade = "") {
  if (ind.tipo === "preco_medio") return "no preço-alvo de cada produto";
  if (meta == null || meta === "" || isNaN(meta)) return "";
  if (alvoTipo === "pct") return `+${fmt.num(meta, 1)}% sobre a base de cada um`;
  if (alvoTipo === "mais") {
    const n = ind.meta_em_pct ? `${fmt.num(meta, 1)} p.p.` : ind.formato === "moeda" ? fmt.moeda(meta)
      : ind.formato === "quantidade" ? valorIndicador(ind, meta, unidade) : fmt.num(meta, 2);
    return `+${n} sobre a base de cada um`;
  }
  return `${metaDigitada(ind, meta, unidade)} para cada um`;
}

// "4,4 de 5 produtos por cliente", "84% de 90%", "R$ 52 mil de R$ 60 mil".
export function textoProgresso(ind, real, alvo, unidade = "") {
  if (ind.formato === "pct") return `${fmt.pct(real)} de ${fmt.pct(alvo)}`;
  if (ind.formato === "razao") return `${fmt.num(real, 1)} de ${fmt.num(alvo, 1)}${ind.sufixo ? " " + ind.sufixo : ""}`;
  return `${valorIndicador(ind, real, unidade, true)} de ${valorIndicador(ind, alvo, unidade, true)}`;
}

// Contagens (pedidos, visitas, clientes) e, na venda por cliente e no preço médio, valores em R$.
export function valorParte(ind, v) {
  if (v == null) return "—";
  return ind.medida === "faturamento" || ind.tipo === "preco_medio" ? fmt.moeda(v) : fmt.num(v, 1);
}

export function periodoTexto(inicio, fim) {
  return inicio === fim ? fmt.data(inicio) : `${fmt.data(inicio)} a ${fmt.data(fim)}`;
}

// "3 semanas" ou "10 dias": o tamanho de um período (nas campanhas de antes, a janela da base tem o da campanha).
export function duracaoTexto(inicio, fim) {
  const dias = Math.round((Date.parse(fim) - Date.parse(inicio)) / 864e5) + 1;
  if (dias % 7 === 0) return dias === 7 ? "1 semana" : `${dias / 7} semanas`;
  return dias === 1 ? "1 dia" : `${dias} dias`;
}

let nomesCatalogo = {};
export function definirCatalogo(cat) {
  nomesCatalogo = Object.fromEntries((cat?.produtos || []).map((p) => [p.id, p.nome]));
}
const nomeProduto = (id, nomes) => nomes?.[id] || nomesCatalogo[id] || `produto ${id}`;

// Os filtros em texto curto (painel e rascunho do Assistente).
export function textoFiltros(f, nomesProdutos) {
  const partes = [];
  const lista = (v, max = 3) => (v.length <= max ? v.join(", ") : `${v.slice(0, max).join(", ")} e mais ${v.length - max}`);
  if (f.produtos?.length) partes.push(lista(f.produtos.map((p) => nomeProduto(p, nomesProdutos))));
  if (f.linhas?.length) partes.push(`linha ${lista(f.linhas)}`);
  if (f.categorias?.length) partes.push(lista(f.categorias));
  if (f.grupos?.length) partes.push(f.grupos.map((g) => NOME_GRUPO[g] || g).join(" e "));
  if (f.ufs?.length) partes.push(`clientes de ${lista(f.ufs, 5)}`);
  if (f.segmentos?.length) partes.push(`segmento ${lista(f.segmentos)}`);
  if (f.areas?.length) partes.push(`área ${lista(f.areas, 2)}`);
  return partes;
}

// Quem conta e com o que compara.
export function textoBase(ind) {
  const partes = [];
  if (ind.base && ind.base !== "todos" && ind.base_texto) partes.push(ind.base_texto);
  if (ind.forma === "crescimento" && ind.comparar) partes.push(`contra ${COMPARAR[ind.comparar]?.toLowerCase() || ind.comparar}`);
  return partes;
}

export function iniciais(nome) {
  const p = String(nome || "?").replace(/[^\p{L}\s]/gu, " ").split(/\s+/).filter(Boolean);
  return ((p[0]?.[0] || "?") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
}
