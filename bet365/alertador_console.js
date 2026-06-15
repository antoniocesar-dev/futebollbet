// alertador_console.js — destaque visual de jogos no fim (bet365 Ao-Vivo/Futebol)
// SOMENTE LEITURA: pinta na tela os jogos que batem seus criterios.
// NAO aposta nada. Voce clica manualmente. (Automacao de lance viola o ToS do bet365.)
//
// Uso no Console (F12) com a pagina #/IP/B1 aberta:
//   iniciarAlertas()                 -> usa CFG padrao abaixo
//   iniciarAlertas({minMinuto: 90})  -> sobrescreve parametros
//   pararAlertas()
//
// "30s antes do fim" nao existe de forma confiavel (acrescimos sao imprevisiveis).
// Use minMinuto (cronometro conta pra cima: 88:30, 90:00+).

const CFG = {
  minMinuto:   88,      // dispara quando o cronometro passa desse minuto
  difMinGols:  1,       // |placar_casa - placar_fora| >= isso (jogo "decidido"). 0 = ignora placar
  oddMax:      1.20,    // so destaca se a MENOR odd (favorito) <= isso. null = ignora
  oddMin:      1.001,   // piso da odd do favorito
  ligas:       [],      // [] = todas; ex.: ['Chile','Finlandia','Veikkaus']
  intervaloMs: 3000,    // re-checa a cada 3s
  beep:        false,   // bipe ao surgir alvo novo (alem do destaque visual)
};

let _alertTimer = null;
const _vistos = new Set();

function _min(timer) {                     // "88:30" -> 88
  if (!timer) return -1;
  const m = String(timer).match(/(\d+):(\d+)/);
  return m ? parseInt(m[1], 10) : -1;
}
function _num(o) { const n = parseFloat(String(o).replace(',', '.')); return isNaN(n) ? null : n; }

function _scan(cfg) {
  let alvos = 0, novos = 0;
  document.querySelectorAll('.ovm-Competition').forEach(comp => {
    const liga = ((comp.querySelector('.ovm-CompetitionHeader') || {}).innerText || '')
      .split('\n')[0].trim();
    if (cfg.ligas.length && !cfg.ligas.some(l => liga.toLowerCase().includes(l.toLowerCase()))) return;

    comp.querySelectorAll('.ovm-Fixture').forEach(fx => {
      const placar = [...fx.querySelectorAll('.ovm-ScorePill')].map(e => parseInt(e.innerText, 10));
      const minuto = _min((fx.querySelector('.ovm-InPlayTimer') || {}).innerText);
      const odds   = [...fx.querySelectorAll('.ovm-ParticipantOddsOnly')].map(e => _num(e.innerText)).filter(v => v != null);
      const favOdd = odds.length ? Math.min(...odds) : null;
      const dif    = (placar.length >= 2) ? Math.abs(placar[0] - placar[1]) : 0;

      const passaMinuto = minuto >= cfg.minMinuto;
      const passaPlacar = cfg.difMinGols === 0 || dif >= cfg.difMinGols;
      const passaOdd    = cfg.oddMax == null || (favOdd != null && favOdd >= cfg.oddMin && favOdd <= cfg.oddMax);

      const alvo = passaMinuto && passaPlacar && passaOdd;
      if (alvo) {
        alvos++;
        fx.style.outline = '3px solid #ffd400';
        fx.style.outlineOffset = '-3px';
        fx.style.boxShadow = '0 0 14px rgba(255,212,0,.7)';
        if (!fx.querySelector('.__alvoBadge')) {
          const b = document.createElement('div');
          b.className = '__alvoBadge';
          b.textContent = `⚡ ALVO ${minuto}'`;
          b.style.cssText = 'position:absolute;top:2px;left:2px;z-index:9;background:#ffd400;color:#000;font:bold 11px sans-serif;padding:1px 5px;border-radius:3px;pointer-events:none';
          fx.style.position = 'relative';
          fx.prepend(b);
        }
        const id = `${liga}|${[...fx.querySelectorAll('[class*="TeamName"]')].map(e=>e.innerText).join('|')}`;
        if (!_vistos.has(id)) { _vistos.add(id); novos++; }
      } else {
        fx.style.outline = ''; fx.style.boxShadow = '';
        const b = fx.querySelector('.__alvoBadge'); if (b) b.remove();
      }
    });
  });

  // banner de status
  let bar = document.getElementById('__alertaBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = '__alertaBar';
    bar.style.cssText = 'position:fixed;bottom:10px;right:10px;z-index:99999;background:#111;color:#ffd400;border:1px solid #ffd400;font:bold 13px sans-serif;padding:8px 12px;border-radius:6px;box-shadow:0 2px 12px rgba(0,0,0,.5)';
    document.body.appendChild(bar);
  }
  bar.textContent = `⚡ ${alvos} alvo(s) | min≥${cfg.minMinuto} dif≥${cfg.difMinGols} odd≤${cfg.oddMax ?? '-'}`;

  if (novos && cfg.beep) {
    try { const a = new (window.AudioContext||window.webkitAudioContext)(); const o = a.createOscillator(); o.connect(a.destination); o.frequency.value = 880; o.start(); setTimeout(() => o.stop(), 180); } catch (e) {}
  }
}

function iniciarAlertas(over = {}) {
  const cfg = { ...CFG, ...over };
  pararAlertas();
  _scan(cfg);
  _alertTimer = setInterval(() => _scan(cfg), cfg.intervaloMs);
  console.log('%cAlertas ON', 'color:#ffd400;font-weight:bold', cfg);
  return cfg;
}
function pararAlertas() {
  if (_alertTimer) clearInterval(_alertTimer);
  _alertTimer = null;
  document.querySelectorAll('.ovm-Fixture').forEach(fx => { fx.style.outline=''; fx.style.boxShadow=''; const b=fx.querySelector('.__alvoBadge'); if(b)b.remove(); });
  const bar = document.getElementById('__alertaBar'); if (bar) bar.remove();
  console.log('%cAlertas OFF', 'color:#888');
}
