// Configuração da página Assistente (só administradores): quanto o assistente foi usado. Os vendedores que cada pessoa
// consulta são os do acesso dela, escolhidos em Usuários: a IA só recebe as vendas, devoluções e metas desses
// vendedores (o servidor monta os dados de cada acesso).
import { api, esc, fmt, icone } from "./util.js";

let raiz = null;
let dados = null;          // resposta de /api/assistente/config

const dolar = (v) => "US$ " + new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);

export function configAssistenteTemAlteracoes() { return false; }  // só leitura: nada para salvar

export async function montarConfigAssistente(container) {
  raiz = container;
  container.innerHTML = `<div class="config"><div class="esqueleto" style="height:300px"></div><div class="esqueleto" style="height:600px"></div></div>`;
  try {
    dados = await api("/api/assistente/config");
    render();
  } catch (e) {
    container.innerHTML = `<div class="cartao vazio">${icone("alerta")}<p>Não foi possível abrir a configuração: ${esc(e.message)}</p></div>`;
  }
}

// ---------- estrutura ----------
function render() {
  raiz.innerHTML = `
  <div class="config">
    <aside class="cartao config-menu entra" style="--i:0">
      <button data-secao="uso" class="ativa">${icone("grafico")}Uso e custo<span class="cont">${dados.uso.hoje.perguntas}</span></button>
      <div class="dica">${icone("info")} A IA só recebe as vendas, devoluções e metas dos vendedores do acesso de cada
        pessoa, escolhidos em <a href="#/usuarios">Usuários</a>. Administradores consultam todos.</div>
    </aside>
    <div id="ca-secao"></div>
  </div>`;
  secaoUso(raiz.querySelector("#ca-secao"));
}

// ======================================================================================
// Uso e custo
// ======================================================================================
function secaoUso(alvo) {
  const u = dados.uso;
  const pct = u.limite_custo_dia ? Math.min(1, u.hoje.custo / u.limite_custo_dia) : 0;
  alvo.innerHTML = `
  <section class="cartao entra" style="--i:1">
    <div class="cartao-cab"><div>
      <h2>${icone("grafico")}Uso do assistente</h2>
      <p class="sub">Últimos ${u.dias} dias, pelo registro do servidor (logs/assistente-AAAA-MM.jsonl). O custo é a
        estimativa pelos tokens e pelos preços do config.ini; o valor cobrado está no Console da Anthropic.</p>
    </div></div>
    <div class="resumo-grupos">
      <div class="resumo-grupo" style="--c:var(--s-fat)"><div class="t">${icone("conversa")}Perguntas hoje</div>
        <div class="n">${u.hoje.perguntas}</div><div class="s">limite de ${u.limite_diario} por pessoa (administradores sem limite)</div></div>
      <div class="resumo-grupo" style="--c:var(--laranja)"><div class="t">${icone("moeda")}Gasto de hoje</div>
        <div class="n">${dolar(u.hoje.custo)}</div><div class="s">${fmt.pct(pct, 0)} do limite diário de ${dolar(u.limite_custo_dia)}</div></div>
      <div class="resumo-grupo" style="--c:var(--k-cli)"><div class="t">${icone("pessoas")}Pessoas que usaram</div>
        <div class="n">${u.por_usuario.length}</div><div class="s">nos últimos ${u.dias} dias</div></div>
    </div>
    ${u.por_usuario.length ? `
    <h3 class="usu-titulo">Por pessoa</h3>
    <div class="tabela-rolagem"><table class="dados">
      <thead><tr><th>Pessoa</th><th>Perguntas</th><th>Custo estimado</th><th>Última pergunta</th></tr></thead>
      <tbody>${u.por_usuario.map((p) => `<tr><td>${esc(p.nome || p.login)} <span class="fraco">${esc(p.login)}</span></td>
        <td>${p.perguntas}</td><td>${dolar(p.custo)}</td><td>${p.ultima ? fmt.dataHora(p.ultima) : "—"}</td></tr>`).join("")}</tbody>
    </table></div>` : `<div class="vazio">${icone("conversa")}<p>Ninguém usou o assistente nos últimos ${u.dias} dias.</p></div>`}
    ${u.ultimas.length ? `
    <h3 class="usu-titulo">Últimas perguntas</h3>
    <div class="tabela-rolagem"><table class="dados ca-ultimas">
      <thead><tr><th>Pergunta</th><th>Quem</th><th>Quando</th><th>Consultas</th><th>Custo</th></tr></thead>
      <tbody>${u.ultimas.map((r) => `<tr><td>${esc(r.pergunta)}${r.erro ? `<br><span class="ca-erro">${icone("alerta")}${esc(r.erro)}</span>` : ""}</td>
        <td>${esc(r.nome || r.login)}</td><td>${fmt.dataHora(r.quando)}</td><td>${r.passos}</td><td>${dolar(r.custo)}</td></tr>`).join("")}</tbody>
    </table></div>` : ""}
  </section>`;
}
