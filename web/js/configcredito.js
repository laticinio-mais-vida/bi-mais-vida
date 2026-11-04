// Configuração da página Reavaliação de Crédito (só administradores): o prazo mínimo entre reanálises do mesmo cliente
// (só um aumento de limite esbarra nele; o administrador pode registrar mesmo assim, e a reanálise fica marcada) e os dias
// até os dados do Serasa aparecerem como desatualizados. As regras ficam em bi/reanalise.py (ConfigCredito) e valem
// depois de Salvar.
import { api, esc, icone, toast } from "./util.js";

// chave, título, explicação, mínimo e máximo (em dias)
const CAMPOS = [
  ["intervalo_reanalise_dias", "Prazo mínimo entre reanálises",
    "Depois de uma reanálise do cliente, um aumento de limite só pode ser registrado passados estes dias, contados do dia dela. Redução, corte e manter o limite passam sempre. 0 desliga o bloqueio.", 0, 365],
  ["serasa_validade_dias", "Validade dos dados do Serasa",
    "Dias, contados da emissão do relatório do Serasa, até a página mostrar os dados como desatualizados.", 1, 365],
];

let ctx = null, raiz = null;
let dados = null;          // resposta de /api/credito/config
let orig = null, rasc = null;

export function configCreditoTemAlteracoes() { return !!(rasc && contarAlteracoes() > 0); }

export async function montarConfigCredito(container, contexto) {
  ctx = contexto;
  raiz = container;
  if (rasc && contarAlteracoes() > 0) { render(); return; }
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:200px"></div><div class="esqueleto" style="height:280px"></div></div>`;
  try {
    carregarDados(await api("/api/credito/config"));
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

function carregarDados(r) {
  dados = r;
  orig = { ...r.config };
  rasc = { ...r.config };
}

const contarAlteracoes = () => CAMPOS.filter(([k]) => String(rasc[k]) !== String(orig[k])).length;

function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      <button type="button" class="ativa">${icone("cadeado")}Regras do crédito</button>
      <div class="dica">${icone("info")} As regras valem assim que você salvar, para todos os clientes.
        ${dados.ativo ? "" : "Neste computador as reanálises e os dados do Serasa não ficam gravados: estas regras valem no site."}</div>
    </aside>
    <section class="cartao secao entra" style="--i:1">
      <div class="cartao-cab"><div><h2>${icone("cadeado")}Bloqueios e validade</h2>
        <p class="sub">O prazo mínimo vale para quem registra reanálises na página de crédito. Como administrador, você pode
          registrar um aumento dentro do prazo marcando “Registrar mesmo assim”, e a reanálise fica marcada como “passou
          do bloqueio”.</p></div></div>
      <div class="sug-regras">
        ${CAMPOS.map(([k, titulo, dica, min, max]) => `<label class="sug-campo"><span class="r"><b>${titulo}</b><small>${dica}</small></span>
          <span class="campo sem-seta"><input type="number" min="${min}" max="${max}" step="1" inputmode="numeric" data-k="${k}"
            value="${esc(String(rasc[k] ?? ""))}" aria-label="${esc(titulo)}, em dias"></span><em>dias</em></label>`).join("")}
      </div>
      <p class="form-erro" id="cc-erro" hidden></p>
    </section>
  </div>
  <div class="barra-salvar" id="cc-barra">
    <span id="cc-n">Alterações não salvas</span>
    <button class="btn" id="cc-descartar">Descartar</button>
    <button class="btn primario" id="cc-salvar">${icone("disco")}Salvar alterações</button>
  </div>`;
  raiz.querySelectorAll("[data-k]").forEach((inp) => inp.addEventListener("input", () => {
    rasc[inp.dataset.k] = inp.value.trim();
    atualizarBarra();
  }));
  raiz.querySelector("#cc-salvar").addEventListener("click", salvar);
  raiz.querySelector("#cc-descartar").addEventListener("click", () => { rasc = { ...orig }; render(); });
  atualizarBarra();
}

function atualizarBarra() {
  const n = contarAlteracoes();
  raiz.querySelector("#cc-barra").classList.toggle("visivel", n > 0);
  raiz.querySelector("#cc-n").textContent = n === 1 ? "1 alteração não salva" : `${n} alterações não salvas`;
}

function erro(msg) {
  const el = raiz.querySelector("#cc-erro");
  if (el) { el.textContent = msg; el.hidden = false; }
  toast(msg, "erro");
}

async function salvar() {
  const btn = raiz.querySelector("#cc-salvar");
  btn.disabled = true;
  try {
    carregarDados(await api("/api/credito/config", { json: { config: rasc } }));
    toast("Regras do crédito salvas");
    ctx.aoSalvar && ctx.aoSalvar();
    render();
  } catch (e) {
    erro(e.message);
  } finally {
    btn.disabled = false;
  }
}
