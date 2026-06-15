// raspador_console.js — bet365 Ao-Vivo / Futebol (somente leitura)
// Cole no Console do DevTools (F12) com a página #/IP/B1 aberta.
// Uso:
//   rasparBet365()            -> retorna array de jogos + imprime tabela
//   rasparBet365({copy:true}) -> tambem copia o JSON pra area de transferencia (copy())
//   baixarBet365()            -> baixa bet365_aovivo.json
//
// Estrutura confirmada em 2026-06-13. Se o bet365 mudar as classes ovm-*,
// ajuste os seletores (ver MAPEAMENTO-BET365.md).

function rasparBet365(opts = {}) {
  const T = el => (el ? el.innerText.trim() : null);
  const jogos = [];
  document.querySelectorAll('.ovm-Competition').forEach(comp => {
    const liga = (T(comp.querySelector('.ovm-CompetitionHeader')) || '')
      .split('\n')[0].trim();
    comp.querySelectorAll('.ovm-Fixture').forEach(fx => {
      const nomes  = [...fx.querySelectorAll('[class*="TeamName"]')].map(T).filter(Boolean);
      const placar = [...fx.querySelectorAll('.ovm-ScorePill')].map(T);
      const minuto = T(fx.querySelector('.ovm-InPlayTimer'));
      const odds   = [...fx.querySelectorAll('.ovm-ParticipantOddsOnly')].map(T);
      let casa = nomes[0], fora = nomes[1];
      if (!casa) {                                  // fallback por texto
        const p = fx.innerText.split('\n').map(s => s.trim()).filter(Boolean);
        casa = p[0]; fora = p[1];
      }
      jogos.push({
        liga, casa, fora,
        placar: (placar[0] ?? '?') + '-' + (placar[1] ?? '?'),
        minuto,
        odd_1: odds[0] ?? null,   // vitoria casa
        odd_x: odds[1] ?? null,   // empate
        odd_2: odds[2] ?? null,   // vitoria fora
      });
    });
  });
  console.log(`%c${jogos.length} jogos ao vivo / ${new Set(jogos.map(g => g.liga)).size} ligas`,
              'font-weight:bold;color:#0a0');
  console.table(jogos);
  if (opts.copy && typeof copy === 'function') { copy(JSON.stringify(jogos, null, 2)); console.log('JSON copiado.'); }
  window.__bet365 = jogos;
  return jogos;
}

function baixarBet365() {
  const jogos = rasparBet365();
  const blob = new Blob([JSON.stringify({ ts: new Date().toISOString(), total: jogos.length, jogos }, null, 2)],
                        { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bet365_aovivo.json';
  a.click();
  URL.revokeObjectURL(a.href);
  return jogos.length;
}
