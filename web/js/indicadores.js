// O que as ações e os objetivos da página Gestão medem (bi/indicadores.py), para a página e para o rascunho do
// Assistente: os tipos, as predefinições do "Indicador medido", os filtros e como formatar valores, alvos e
// diferenças. A conta é toda no servidor, que manda o descritor do indicador (nome, formato, como ler a meta).
import { fmt } from "./util.js";

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

// O "Indicador medido": cada opção é um tipo pronto ou uma combinação da Personalizada. alvo: a unidade do alvo;
// pct: o alvo é em % (80 = 80%); objetivo: só nos objetivos (numa ação o alvo já sai da base).
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

// A predefinição de uma ação gravada (ou rascunho): o tipo e, na Personalizada, a medida e a forma.
export function presetDe(metrica, p = {}) {
  const legado = LEGADOS[metrica];
  if (legado) return PRESETS.find((x) => x.id === legado.join(":"));
  if (metrica !== "personalizada") return PRESETS.find((x) => x.id === metrica) || PRESETS[0];
  return PRESETS.find((x) => x.id === `${p.medida}:${p.forma || "total"}`) || PRESETS.find((x) => x.id === "faturamento:total");
}

export const ALVOS = { mais: "+ sobre a base de cada um", pct: "+ % sobre a base de cada um", fixo: "Valor fixo para cada um" };

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

// Como o alvo da ação aparece ("+1 sobre a base de cada um", "+10% sobre a base", "80% para cada um").
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

// "3 semanas" ou "10 dias": o tamanho de um período (a ação e a janela da base têm o mesmo).
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
