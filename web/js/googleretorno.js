// A volta do login com o Google (web/google.html, na janelinha aberta por agendagoogle.js): o servidor manda para cá
// com o resultado no fragmento (#ok=e-mail ou #erro=motivo). Avisa a agenda que abriu a janela, pelos dois caminhos
// (BroadcastChannel, que funciona mesmo quando a página do Google corta o window.opener, e postMessage), e fecha. Sem a
// janelinha (o navegador bloqueou e o login foi na própria aba), mostra o resultado e volta para a Gestão (a agenda
// relê a lista quando abre).
(function () {
  var p = new URLSearchParams(location.hash.slice(1));
  var r = p.has("erro") ? { erro: p.get("erro") } : { ok: p.get("ok") || "" };
  r.id = String(Date.now()) + Math.random().toString(16).slice(2);
  history.replaceState(null, "", location.pathname); // o resultado não fica no histórico
  var maiuscula = function (t) { return t.charAt(0).toUpperCase() + t.slice(1); };
  document.getElementById("g-titulo").textContent = r.erro ? "Não deu para conectar" : "Conta Google conectada";
  document.getElementById("g-msg").textContent = r.erro ? maiuscula(r.erro) + "."
    : (r.ok ? "A agenda de " + r.ok + " já aparece na sua agenda do BI." : "Pronto.");
  document.getElementById("g-ic").className = "g-retorno-ic " + (r.erro ? "ruim" : "ok");
  document.getElementById("g-ic").textContent = r.erro ? "!" : "✓";

  try { new BroadcastChannel("bi-google").postMessage({ biGoogle: r }); } catch (e) { /* navegador antigo */ }
  var abriu = null;
  try { abriu = window.opener && window.opener.location.origin === location.origin ? window.opener : null; } catch (e) { abriu = null; }
  if (abriu) abriu.postMessage({ biGoogle: r }, location.origin);

  // A janelinha fecha (o erro fica um pouco mais, para ser lido). Se continuar aberta, é uma aba comum (o navegador não
  // deixa o script fechar): o botão volta ao BI, sozinho quando deu certo.
  setTimeout(function () {
    window.close();
    setTimeout(function () {
      document.getElementById("g-voltar").hidden = false;
      if (!r.erro) setTimeout(function () { location.replace("/#/gestao"); }, 2000);
    }, 400);
  }, r.erro ? 4000 : 1200);
})();
