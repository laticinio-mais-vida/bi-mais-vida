// Lista suspensa de seleção múltipla com busca e grupos (ex.: vendedores por equipe, produtos por categoria).
// Nada marcado = todos. As marcações só valem ao clicar em Aplicar ou fora da lista; Esc desfaz.
import { esc, icone } from "./util.js";

export function multiSelecao(el, op) {
  let itens = op.itens || [];
  let selecionados = new Set(op.selecionados || []);
  let rascunho = new Set();

  el.classList.add("multi");
  el.innerHTML = `
    <button class="multi-botao" type="button" aria-haspopup="dialog" aria-expanded="false">
      <span class="ic-campo">${icone(op.icone || "funil")}</span>
      <span class="multi-texto"></span>
    </button>
    <div class="multi-painel" role="dialog" aria-label="${esc(op.rotulo)}" hidden>
      <div class="multi-topo">
        <b>${esc(op.rotulo)}</b>
        <label class="campo sem-seta"><span class="ic-campo">${icone("busca")}</span>
          <input type="search" placeholder="${esc(op.busca || "Buscar")}" aria-label="${esc(op.busca || "Buscar")}"></label>
      </div>
      <div class="multi-lista"></div>
      <div class="multi-rodape">
        <span class="multi-resumo"></span>
        <button class="btn" type="button" data-acao="limpar">Limpar</button>
        <button class="btn primario" type="button" data-acao="aplicar">${icone("visto")}Aplicar</button>
      </div>
    </div>`;
  const botao = el.querySelector(".multi-botao");
  const painel = el.querySelector(".multi-painel");
  const lista = el.querySelector(".multi-lista");
  const busca = el.querySelector("input[type=search]");

  const nomeDe = (id) => itens.find((i) => i.id === id)?.nome || String(id);

  function textoBotao() {
    const n = selecionados.size;
    const t = n === 0 ? op.todos : n === 1 ? nomeDe([...selecionados][0]) : `${n} ${op.plural}`;
    el.querySelector(".multi-texto").textContent = t;
    botao.classList.toggle("com-filtro", n > 0);
    botao.title = n > 1 ? [...selecionados].map(nomeDe).join(", ") : t;
  }

  function desenharLista() {
    const grupos = (op.grupos || [{ id: null, nome: "" }]).filter((g) => itens.some((i) => (i.grupo ?? null) === g.id));
    lista.innerHTML = grupos.map((g) => {
      const doGrupo = itens.filter((i) => (i.grupo ?? null) === g.id);
      return `<div class="multi-grupo" data-grupo="${esc(g.id ?? "")}">
        ${g.nome ? `<label class="multi-op cab"><input type="checkbox" data-grupo="${esc(g.id ?? "")}"><span class="marca-caixa">${icone("visto")}</span>
          <b>${esc(g.nome)}</b><small>${doGrupo.length}</small></label>` : ""}
        ${doGrupo.map((i) => `<label class="multi-op" data-busca="${esc((i.nome + " " + (i.detalhe || "") + " " + i.id).toLowerCase())}">
          <input type="checkbox" value="${i.id}"><span class="marca-caixa">${icone("visto")}</span>
          <span class="n">${esc(i.nome)}${i.detalhe ? `<small>${esc(i.detalhe)}</small>` : ""}</span></label>`).join("")}
      </div>`;
    }).join("") || `<p class="multi-vazio">Nada para escolher com os dados atuais.</p>`;
    lista.querySelectorAll("input[value]").forEach((c) => c.addEventListener("change", () => {
      const id = Number(c.value);
      c.checked ? rascunho.add(id) : rascunho.delete(id);
      marcar();
    }));
    lista.querySelectorAll("input[data-grupo]").forEach((c) => c.addEventListener("change", () => {
      const caixas = [...lista.querySelectorAll(`.multi-grupo[data-grupo="${CSS.escape(c.dataset.grupo)}"] .multi-op:not([hidden]) input[value]`)];
      const todos = caixas.every((x) => rascunho.has(Number(x.value)));
      caixas.forEach((x) => (todos ? rascunho.delete(Number(x.value)) : rascunho.add(Number(x.value))));
      marcar();
    }));
  }

  function marcar() {
    lista.querySelectorAll("input[value]").forEach((c) => { c.checked = rascunho.has(Number(c.value)); });
    lista.querySelectorAll(".multi-grupo").forEach((g) => {
      const cab = g.querySelector("input[data-grupo]");
      if (!cab) return;
      const ids = [...g.querySelectorAll("input[value]")].map((x) => Number(x.value));
      const n = ids.filter((id) => rascunho.has(id)).length;
      cab.checked = n > 0 && n === ids.length;
      cab.indeterminate = n > 0 && n < ids.length;
    });
    const n = rascunho.size;
    el.querySelector(".multi-resumo").textContent = n ? `${n} marcado${n === 1 ? "" : "s"}` : op.todos;
  }

  function filtrar() {
    const termo = busca.value.trim().toLowerCase();
    lista.querySelectorAll(".multi-op[data-busca]").forEach((o) => { o.hidden = !!termo && !o.dataset.busca.includes(termo); });
    lista.querySelectorAll(".multi-grupo").forEach((g) => { g.hidden = !g.querySelector(".multi-op[data-busca]:not([hidden])"); });
  }

  function abrir() {
    rascunho = new Set(selecionados);
    busca.value = "";
    desenharLista();
    marcar();
    painel.hidden = false;
    painel.classList.remove("a-direita");
    if (painel.getBoundingClientRect().right > window.innerWidth - 8) painel.classList.add("a-direita");
    botao.setAttribute("aria-expanded", "true");
    busca.focus({ preventScroll: true });
    document.addEventListener("pointerdown", fora, true);
    document.addEventListener("keydown", tecla);
  }

  function fechar(aplicar) {
    if (painel.hidden) return;
    painel.hidden = true;
    botao.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", fora, true);
    document.removeEventListener("keydown", tecla);
    if (!aplicar) return;
    const mudou = rascunho.size !== selecionados.size || [...rascunho].some((id) => !selecionados.has(id));
    selecionados = new Set(rascunho);
    textoBotao();
    if (mudou && op.aoAplicar) op.aoAplicar([...selecionados]);
  }

  function fora(e) { if (!el.contains(e.target)) fechar(true); }
  function tecla(e) {
    if (e.key === "Escape") { fechar(false); botao.focus(); }
    if (e.key === "Enter" && e.target === busca) { e.preventDefault(); fechar(true); botao.focus(); }
  }

  botao.addEventListener("click", () => (painel.hidden ? abrir() : fechar(true)));
  busca.addEventListener("input", filtrar);
  el.querySelector("[data-acao=limpar]").addEventListener("click", () => { rascunho.clear(); marcar(); busca.focus(); });
  el.querySelector("[data-acao=aplicar]").addEventListener("click", () => { fechar(true); botao.focus(); });
  textoBotao();

  return {
    // Novas opções (vindas do servidor); marcações que não existem mais somem.
    definir(novos, marcados, grupos) {
      itens = novos;
      if (grupos) op.grupos = grupos;
      selecionados = new Set((marcados ?? [...selecionados]).filter((id) => itens.some((i) => i.id === id)));
      textoBotao();
    },
    valor: () => [...selecionados],
    limpar() { selecionados.clear(); textoBotao(); },
  };
}
