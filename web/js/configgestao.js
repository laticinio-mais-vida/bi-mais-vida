// Configuração da página Gestão (só administradores): os dias de atendimento, em que dias da semana o vendedor pode
// atender cada área comercial (um ou mais). Na efetividade das campanhas, a semana conta num dia só, o último marcado,
// e o pedido em qualquer um dos dias vale a visita (começou com a planilha do Power BI). Área pendente
// ou não atendida fica fora da conta. Os vendedores que cada pessoa acompanha na Gestão (e na API pública) são os do
// acesso dela, escolhidos em Usuários. Tudo vale depois de Salvar.
import { api, esc, fmt, icone, toast } from "./util.js";

const DIAS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [7, "Dom"]];
const FILTROS_AREA = [
  { id: "pendentes", nome: "Pendentes" }, { id: "atendidas", nome: "Com dias" },
  { id: "nao", nome: "Não atendidas" }, { id: "todas", nome: "Todas" },
];

let raiz = null;
let dados = null;          // resposta de /api/gestao/config
let orig = null, rasc = null;
let buscaArea = "", filtroArea = "pendentes";
// As áreas mexidas desde a última troca de filtro ou busca: continuam na lista mesmo saindo do filtro (na lista
// Pendentes, a área sumia no primeiro clique e não dava para marcar o segundo dia).
let fixas = new Set();

const clone = (o) => JSON.parse(JSON.stringify(o));

export function configGestaoTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigGestao(container) {
  raiz = container;
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    carregarDados(await api("/api/gestao/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  orig = { areas: Object.fromEntries((dados.areas || []).map((a) => [a.id, a.dias])) };  // null = pendente; [] = não atendida
  rasc = clone(orig);
  fixas = new Set();
}

// ---------- apoio ----------
const areaMudou = (id) => JSON.stringify(rasc.areas[id]) !== JSON.stringify(orig.areas[id]);
const areasMudadas = () => Object.keys(rasc.areas).filter(areaMudou);
const pendentes = () => (dados.areas || []).filter((a) => rasc.areas[a.id] == null && a.ativos > 0).length;

function contarAlteracoes() { return areasMudadas().length; }

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      <button data-secao="areas" class="ativa">${icone("calendario")}Dias de atendimento<span class="cont">${pendentes()}</span></button>
      <div class="dica">${icone("info")} Cada pessoa vê as campanhas, os objetivos e o histórico dos vendedores do acesso dela,
        escolhidos em <a href="#/usuarios">Usuários</a>. Só os administradores lançam e mudam. Os dias de atendimento das
        áreas valem para a efetividade.</div>
    </aside>
    <div id="cg-secao"></div>
  </div>
  <div class="barra-salvar" id="cg-barra">
    <span id="cg-n">Alterações não salvas</span>
    <button class="btn" id="cg-descartar">Descartar</button>
    <button class="btn primario" id="cg-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelector("#cg-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cg-descartar").addEventListener("click", () => { rasc = clone(orig); fixas = new Set(); render(); });
  secaoAreas(raiz.querySelector("#cg-secao"));
  atualizarBarra();
}

const textoPendentes = (n) =>
  `${n} área${n === 1 ? "" : "s"} com clientes ativos ainda sem dia: os clientes delas ficam fora da efetividade.`;

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cg-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cg-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
  const p = pendentes();
  raiz.querySelector(".config-menu .cont").textContent = p;
  const aviso = raiz.querySelector("#ca-pendentes");
  if (aviso) { aviso.hidden = !p; aviso.querySelector("span").textContent = textoPendentes(p); }
}

// ======================================================================================
// Dias de atendimento das áreas comerciais
// ======================================================================================
function secaoAreas(alvo) {
  const n = pendentes();
  alvo.innerHTML = `
  <section class="cartao secao entra" style="--i:1">
    <div class="cartao-cab"><div><h2>${icone("calendario")}Dias de atendimento das áreas</h2>
      <p class="sub">Marque os dias em que o vendedor pode atender a área (um ou mais). Na efetividade, a semana da área
        conta como um dia só, o último marcado: cada cliente ativo tem uma visita, que vale com o pedido em qualquer um
        dos dias. Área pendente ou não atendida fica fora da conta (pedidos e visitas).</p></div></div>
    ${dados.aviso_areas ? `<div class="aviso">${icone("alerta")}<span>${esc(dados.aviso_areas)}</span></div>` : ""}
    <p class="usu-nota aviso-nota" id="ca-pendentes"${n ? "" : " hidden"}>${icone("alerta")}<span>${textoPendentes(n)}</span></p>
    <div class="barra-ferramentas usu-busca">
      <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span><input id="ca-busca" type="search" placeholder="Buscar área ou código" value="${esc(buscaArea)}"></label>
      <div class="seg-mini" role="group" aria-label="Quais áreas">${FILTROS_AREA.map((f) => `<button type="button" data-filtro="${f.id}" class="${filtroArea === f.id ? "ativo" : ""}">${f.nome}</button>`).join("")}</div>
      <button class="btn" type="button" id="ca-sugestoes" title="Nas áreas pendentes, marca o dia que o nome da área diz (ex.: “TEIXEIRA (SEXTA)”)">${icone("raio")}Usar o dia do nome nas pendentes</button>
    </div>
    <div class="areas-lista" id="ca-lista"></div>
  </section>`;
  alvo.querySelector("#ca-busca").addEventListener("input", (e) => { buscaArea = e.target.value; fixas = new Set(); desenharAreas(); });
  alvo.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => {
    filtroArea = b.dataset.filtro;
    fixas = new Set();
    alvo.querySelectorAll("[data-filtro]").forEach((x) => x.classList.toggle("ativo", x === b));
    desenharAreas();
  }));
  alvo.querySelector("#ca-sugestoes").addEventListener("click", () => {
    let n = 0;
    for (const a of dados.areas) {
      if (rasc.areas[a.id] == null && a.sugestao?.length) { rasc.areas[a.id] = [...a.sugestao]; fixas.add(a.id); n++; }
    }
    toast(n ? `${n} área${n === 1 ? "" : "s"} com o dia do nome (confira e salve)` : "Nenhuma pendente com o dia no nome", n ? "ok" : "erro");
    desenharAreas();
    atualizarBarra();
  });
  alvo.querySelector("#ca-lista").addEventListener("click", aoClicarArea);
  desenharAreas();
}

function estadoArea(a) {
  const d = rasc.areas[a.id];
  if (d == null) return "pendente";
  return d.length ? "atendida" : "nao";
}

function desenharAreas() {
  const termo = buscaArea.trim().toLowerCase();
  const lista = (dados.areas || []).filter((a) => {
    if (fixas.has(a.id)) return true;
    const st = estadoArea(a);
    if (filtroArea === "pendentes" && st !== "pendente") return false;
    if (filtroArea === "atendidas" && st !== "atendida") return false;
    if (filtroArea === "nao" && st !== "nao") return false;
    return !termo || `${a.nome} ${a.id}`.toLowerCase().includes(termo);
  }).sort((x, y) => (y.ativos - x.ativos) || x.nome.localeCompare(y.nome));
  const el = raiz.querySelector("#ca-lista");
  if (!lista.length) {
    el.innerHTML = `<p class="usu-nota">${icone("busca")}<span>${filtroArea === "pendentes" && !termo ? "Nenhuma área pendente." : "Nenhuma área com esse filtro."}</span></p>`;
    return;
  }
  el.innerHTML = lista.map((a) => {
    const dias = rasc.areas[a.id] || [];
    const st = estadoArea(a);
    const chip = { pendente: `<span class="chip-papel inativo">Pendente</span>`, nao: `<span class="chip-papel inativo">Não atendida</span>`,
                   atendida: `<span class="chip-papel">${dias.length} dia${dias.length === 1 ? "" : "s"}</span>` }[st];
    const sug = st === "pendente" && a.sugestao?.length
      ? `<button class="btn" type="button" data-sugestao="${a.id}">Usar ${a.sugestao.map((d) => DIAS[d - 1][1]).join(", ")}</button>` : "";
    return `<div class="area-linha ${areaMudou(a.id) ? "mudou" : ""}" data-id="${a.id}">
      <div class="n"><b>${esc(a.nome)}${areaMudou(a.id) ? " <em>(alterada)</em>" : ""}</b>
        <small>código ${a.id} · ${fmt.num(a.ativos)} cliente${a.ativos === 1 ? "" : "s"} ativo${a.ativos === 1 ? "" : "s"}${a.vendedores?.length ? ` · ${esc(a.vendedores.join(", "))}` : ""}${a.atualizada_por_nome && !areaMudou(a.id) ? ` · por ${esc(a.atualizada_por_nome)}` : ""}</small></div>
      <div class="dias-semana" role="group" aria-label="Dias de atendimento de ${esc(a.nome)}">${DIAS.map(([d, n]) =>
        `<button type="button" data-dia="${d}" aria-pressed="${dias.includes(d)}" class="${dias.includes(d) ? "ativo" : ""}">${n}</button>`).join("")}</div>
      <div class="area-acoes">${chip}${sug}
        <button class="btn icone" type="button" data-nao="${a.id}" title="Não atendida (fica fora da efetividade, sem aviso)" aria-label="Marcar ${esc(a.nome)} como não atendida">${icone("menos")}</button>
        <button class="btn icone" type="button" data-limpar="${a.id}" title="Voltar a pendente" aria-label="Voltar ${esc(a.nome)} a pendente">${icone("restaurar")}</button></div>
    </div>`;
  }).join("");
}

function aoClicarArea(e) {
  const b = e.target.closest("button");
  const linha = e.target.closest(".area-linha");
  if (!b || !linha) return;
  const id = Number(linha.dataset.id);
  const a = dados.areas.find((x) => x.id === id);
  if (b.dataset.dia) {
    const d = Number(b.dataset.dia);
    const atual = new Set(rasc.areas[id] || []);
    atual.has(d) ? atual.delete(d) : atual.add(d);
    // Sem nenhum dia marcado, a área volta a como estava ao abrir, se lá também não tinha dias (pendente ou não
    // atendida); se tinha, fica pendente. "Não atendida" é o botão próprio.
    const antes = orig.areas[id];
    rasc.areas[id] = atual.size ? [...atual].sort((x, y) => x - y) : (antes && !antes.length ? [] : null);
  } else if (b.dataset.sugestao) rasc.areas[id] = [...a.sugestao];
  else if (b.dataset.nao) rasc.areas[id] = [];
  else if (b.dataset.limpar) rasc.areas[id] = null;
  else return;
  fixas.add(id);
  desenharAreas();
  atualizarBarra();
}

// ---------- gravação ----------
async function salvar() {
  const btn = raiz.querySelector("#cg-salvar");
  const areas = Object.fromEntries(areasMudadas().map((id) => [id, rasc.areas[id]]));
  btn.disabled = true;
  try {
    carregarDados(await api("/api/gestao/config", { json: { areas } }));
    toast("Configuração da Gestão salva");
    render();
  } catch (e) {
    toast(e.message, "erro");
  } finally {
    btn.disabled = false;
  }
}
