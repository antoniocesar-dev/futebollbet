// alertador_valor.js v2 — sinal de aposta AO VIVO bet365 (SOMENTE LEITURA).
// Tiers WATCH -> ARM -> GREEN. NAO aposta; voce decide e clica.
//
// Cole no Console (F12) com a pagina #/IP/B1 aberta:
//   iniciarValor()                                  // defaults
//   iniciarValor({armMin:88, probMin:0.80})         // mais exigente
//   iniciarValor({greenBuffer:0.5})                 // GREEN um pouco mais cedo
//   pararValor()
//
// O QUE MUDOU vs v1 (ver MAPEAMENTO-BET365.md / plano):
//  - Modelo de probabilidade calibrado no futebol.db: hazard por minuto (curva),
//    acrescimo como distribuicao, multiplicador de placar, banda de confianca.
//  - Relogio lido em MM:SS; guardas anti relogio-fantasma (congelado / >teto).
//  - Tiers + AND-gate: GREEN so fundo nos acrescimos, mercado aberto, relogio
//    fresco, criterios batidos e confirmado por N scans. (GREEN = "ultima boa
//    janela", NAO "faltam 40s" — o apito e imprevisivel.)
//  - Gancho SofaScore: se window.__ssCross[chave] existir (preenchido pelo
//    caminho Playwright), corrobora o minuto e mata verde se status=finished.
//
// CAL embutido vem de hazard_cal.json (gerado por calibrar_hazard.py). Pra
// re-calibrar: rode o .py e cole os novos valores no objeto CAL abaixo.

;(function () {
  const VERSAO = 'v2.4';   // <- aparece na barra; se nao mostrar isso, e a versao ANTIGA
  // ---------------- calibracao (de hazard_cal.json) ----------------
  const CAL = {
    home_share: 0.5489,
    gols_por_jogo: 2.2682,
    h_reg_buckets: [0.010366,0.023221,0.016172,0.016586,0.023221,0.026123,
                    0.021562,0.026538,0.025709,0.02405,0.026953,0.026123,
                    0.022392,0.029855,0.022392,0.022806,0.031099,0.016586],
    h_stop_2h: 0.03133,
    stoppage_extra_pmf: [0.45,0.28,0.15,0.08,0.04],
    red: { down: 0.74, up: 1.30 },
    mult: { sigma: 0.35, d0: 1.5, clampLo: 0.45, clampHi: 2.2 },
    sigma_log: { base: 0.30, sem_stats: 0.10 },
    forca: { minJogos: 3, k: 5.0, wMax: 0.85 },   // shrinkage do blend forca-time
  };

  // ---------------- config / thresholds ----------------
  const DEF = {
    watchMin: 80,            // entra em WATCH
    armMin: 88,              // pode ARMar
    probMin: 0.70,           // prob minima do resultado dominante
    greenBuffer: 1.0,        // GREEN comeca esse tanto ANTES do fim anunciado
    unknownStoppageFloor: 2, // acrescimo desconhecido -> GREEN a partir de 92'
    greenOvershoot: 2,       // teto do GREEN acima do anunciado
    hardCeiling: 8,          // teto do GREEN quando acrescimo desconhecido
    stallScans: 2,           // relogio congelado por N scans -> STALE
    surgeScans: 3,           // sem mudanca de placar/flap nesses scans
    confirmScans: 2,         // GREEN precisa persistir N scans (anti-flicker)
    clockSkewTol: 2.0,       // tolerancia de minuto bet365 vs SofaScore
    intervaloMs: 3000,
    exigeOddAtiva: true,
    ssUrl: null,             // ex.: 'http://localhost:8765' (sofascore_live.py servir)
    ssRefreshMs: 10000,      // de quanto em quanto puxa o cross do SofaScore
    painel: true,            // momentum pelo painel do bet365 (jogo aberto) — sem API, mesma fonte
    stakeTotal: 10,          // R$ total p/ o calculo de Dutching (cobrir 2 resultados)
    dutch: true,             // mostra o plano de Dutching no badge dos ARM/GREEN
  };

  const COR = { WATCH:'#6aa0ff', ARM:'#ffb300', GREEN:'#2bd24f', STALE:'#e23b3b' };
  let timer = null;
  const ST = (window.__avState = window.__avState || {}); // estado por fixture

  // ---------------- cross-check SofaScore (opcional, via localhost) ----------
  const _RUIDO = new Set(['fc','cf','sc','ac','afc','cd','ca','club','clube',
    'calcio','ssd','ssc','us','as','if','sk','fk','bk','ik','il','de','do','da','the','fa']);
  function normalizarTime(n){            // espelha sofascore_live.normalizar
    if(!n) return '';
    let s=n.normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase();
    for(const ch of "._-/'") s=s.split(ch).join(' ');
    return s.split(/\s+/).filter(t=>t && !_RUIDO.has(t)).join(' ');
  }
  const ssCache = (window.__ssCache = window.__ssCache || {data:{}, ts:0, loading:false});
  function ssFetch(url, now){
    if(!url || ssCache.loading || (now - ssCache.ts) < (DEF.ssRefreshMs)) return;
    ssCache.loading = true;
    fetch(url, {cache:'no-store'}).then(r=>r.json()).then(d=>{
      ssCache.data = d || {}; ssCache.ts = Date.now(); ssCache.loading = false;
    }).catch(()=>{ ssCache.loading = false; });
  }
  function ssLookup(home, away){
    const k = normalizarTime(home)+'|'+normalizarTime(away);
    return ssCache.data[k] || (window.__ssCross && window.__ssCross[k]) || null;
  }
  function logarSinal(url, rec){              // POST best-effort pro servidor (Stage 3)
    if(!url) return;
    try{ fetch(url+'/log', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(rec)}).catch(()=>{}); }catch(e){}
  }
  // forca-time do FBref via servidor local (/forca), por nome; cache por jogo (muda devagar)
  const forcaCache = (window.__forcaCache = window.__forcaCache || {});
  function forcaLocal(url, casa, fora){
    if(!url) return null;
    const k = normalizarTime(casa)+'|'+normalizarTime(fora);
    if(k in forcaCache) return forcaCache[k];           // resolvido: obj {lam_casa,...} ou null
    forcaCache[k] = null;                                // em andamento -> nao re-busca
    fetch(url+'/forca?casa='+encodeURIComponent(casa)+'&fora='+encodeURIComponent(fora))
      .then(r=>r.json()).then(d=>{ forcaCache[k] = (d && d.lam_casa) ? d : null; }).catch(()=>{});
    return null;
  }

  // ---------------- momentum pelo PAINEL do bet365 (jogo aberto, sem API/SofaScore) ----------
  // Pesos das metricas do painel (sem xG; "Ataques Perigosos" = o sinal que a casa usa).
  // pesos das stats reais do painel bet365 (mesma fonte das odds). Somam 1.
  // SÓ as rodas (ordem casa/fora confiavel). A barra de chutes vem com ordem
  // ambigua (inverte o sinal) -> fora. "Ataques Perigosos" e o sinal principal.
  const PAINEL_W = { "Ataques Perigosos":0.65, "Ataques":0.20, "% de Posse":0.15 };
  const SEL_LISTA = '.ovm-FixtureList, .ovm-SortedFixtureList';  // agrupada OU ordenada
  function _painelFixture(){            // o jogo ABERTO = .ovm-Fixture FORA de qualquer lista
    return [...document.querySelectorAll('.ovm-Fixture')].find(f => !f.closest(SEL_LISTA));
  }
  function lerPainel(){                  // {casa,fora,stats} do jogo aberto, ou null
    const fx=_painelFixture(); if(!fx) return null;
    const nomes=[...fx.querySelectorAll('[class*="TeamName"]')].map(txt).filter(Boolean);
    if(nomes.length<2) return null;
    const s={};
    document.querySelectorAll('.ml1-WheelChartAdvanced').forEach(w=>{  // rodas: so existem no painel
      const lab=txt(w.querySelector('.ml1-WheelChartAdvanced_Text'));
      const ns=[...w.querySelectorAll('*')].map(txt).filter(x=>/^\d+$/.test(x)).map(Number);
      if(lab&&ns.length>=2) s[lab]=[ns[0],ns[1]];
    });
    const sb=document.querySelector('.ml1-StatsLowerAdvanced_ShotsDualBar');
    if(sb){ const n=(txt(sb).match(/\d+/g)||[]).map(Number);
      if(n.length>=4){ s["Finalizacoes"]=[n[0],n[1]]; s["ChutesAoGol"]=[n[2],n[3]]; } }
    return { casa:nomes[0], fora:nomes[1], stats:s };
  }
  function momentumPainel(stats){        // {casa,fora} a partir das stats do painel; 1/1 se vazio
    let sw=0, ss=0;
    for(const k in PAINEL_W){ const v=stats[k];
      if(!v||(v[0]+v[1])<=0) continue;
      const sh=Math.max(0.15,Math.min(0.85, v[0]/(v[0]+v[1])));
      ss+=PAINEL_W[k]*sh; sw+=PAINEL_W[k];
    }
    if(sw===0) return {casa:1, fora:1, ph:0.5};
    const ph=ss/sw;
    return { casa:Math.max(0.6,Math.min(1.7,Math.exp(0.5*2*(ph-0.5)))),
             fora:Math.max(0.6,Math.min(1.7,Math.exp(0.5*2*(0.5-ph)))), ph:+ph.toFixed(3) };
  }

  // ---------------- modelo (porta do prob_aovivo.py) ----------------
  const fatorial = n => { let f=1; for (let i=2;i<=n;i++) f*=i; return f; };
  const pois = (k,l) => l<=0 ? (k===0?1:0) : Math.exp(-l)*Math.pow(l,k)/fatorial(k);
  const clamp = (v,lo,hi) => Math.max(lo, Math.min(hi, v));

  function lamRegular(m) {
    if (m >= 90) return 0;
    let s = 0;
    for (let b=0;b<CAL.h_reg_buckets.length;b++) {
      const lo=5*b, hi=5*b+5, ov=Math.min(90,hi)-Math.max(m,lo);
      if (ov>0) s += CAL.h_reg_buckets[b]*ov;
    }
    return s;
  }
  function mults(gc,gf,m,restante,momC,momF,redC,redF) {
    const mu=CAL.mult, rd=CAL.red;
    const d=gc-gf, push=0.5+0.5*(Math.min(m,90)/90), t=Math.tanh(d/mu.d0);
    let msC=1+mu.sigma*(-t*push), msF=1+mu.sigma*(t*push);
    const net=(redC||0)-(redF||0), neff=Math.abs(net)*Math.min(1,Math.max(0,restante)/30);
    let mrC=1, mrF=1;
    if (net>0){ mrC=Math.pow(rd.down,neff); mrF=Math.pow(rd.up,neff); }
    else if (net<0){ mrC=Math.pow(rd.up,neff); mrF=Math.pow(rd.down,neff); }
    return [clamp((momC||1)*msC*mrC,mu.clampLo,mu.clampHi),
            clamp((momF||1)*msF*mrF,mu.clampLo,mu.clampHi)];
  }
  function convolui(gc,gf,lc,lf,kmax=8){
    let pc=0,pe=0,pf=0;
    for(let a=0;a<=kmax;a++){ const pa=pois(a,lc);
      for(let b=0;b<=kmax;b++){ const pb=pois(b,lf); const fc=gc+a,ff=gf+b;
        if(fc>ff)pc+=pa*pb; else if(fc<ff)pf+=pa*pb; else pe+=pa*pb; }}
    const s=pc+pe+pf||1; return [pc/s,pe/s,pf/s];
  }
  function blendForca(forca){ // -> [r_eff, sh_eff]; sem forca -> [1, home_share] (cai no global)
    const sh0=CAL.home_share; let r=1, sh=sh0;
    if(forca && forca.lam_casa && forca.lam_fora && forca.n>=CAL.forca.minJogos){
      const lcf=forca.lam_casa, laf=forca.lam_fora, tot=lcf+laf;
      if(tot>0){ const w=Math.min(CAL.forca.wMax, forca.n/(forca.n+CAL.forca.k));
        r = 1 + w*((tot/CAL.gols_por_jogo)-1);
        sh = sh0 + w*((lcf/tot)-sh0); }
    }
    return [r, Math.min(0.95,Math.max(0.05,sh))];
  }
  function probs(m,gc,gf,A,o){ // o = {momC,momF,redC,redF,escala,forca}
    const lreg=lamRegular(m), elapsed=Math.max(0,m-90);
    const [rEff,shEff]=blendForca(o.forca);
    const [Mc,Mf]=mults(gc,gf,m,Math.max(0,90-m)+A,o.momC,o.momF,o.redC,o.redF);
    const pmf=CAL.stoppage_extra_pmf; let pc=0,pe=0,pf=0,w=0;
    for(let x=0;x<pmf.length;x++){
      const S=A+x, remStop=Math.max(0,S-elapsed);
      const lt=(lreg+CAL.h_stop_2h*remStop)*(o.escala||1)*rEff;
      const [a,e,f]=convolui(gc,gf,lt*shEff*Mc,lt*(1-shEff)*Mf);
      pc+=pmf[x]*a; pe+=pmf[x]*e; pf+=pmf[x]*f; w+=pmf[x];
    }
    return w>0?[pc/w,pe/w,pf/w]:[pc,pe,pf];
  }
  function dominante(gc,gf,pc,pe,pf){ // -> {lab,prob,idx} (idx: 0=1,1=X,2=2)
    const c=[['CASA',pc,0],['EMPATE',pe,1],['FORA',pf,2]].sort((a,b)=>b[1]-a[1]);
    return {lab:c[0][0],prob:c[0][1],idx:c[0][2]};
  }
  function mantemProb(gc,gf,pc,pe,pf){ return gc>gf?pc : gc<gf?pf : pe; }
  // Dutching: cobre os 2 resultados de MENOR odd, dividindo `stake` pra retorno igual
  // se qualquer um dos 2 sair. Voce PERDE tudo se sair o 3o. Por isso o que importa
  // NAO e "lucro se cobrir", e o EV REAL = (1 - P_excluido)*retorno - stake (P do modelo).
  function dutch(odds, p3, stake){          // odds=[o1,oX,o2], p3=[pCasa,pEmpate,pFora]
    const LAB=['CASA','EMPATE','FORA'];
    if(odds.filter(o=>o!=null).length<3) return null;
    const ord=[0,1,2].sort((a,b)=>odds[a]-odds[b]);
    const a=ord[0], b=ord[1], ex=ord[2];
    const inv=1/odds[a]+1/odds[b], ret=stake/inv, pExcl=p3[ex];
    return { a:{lab:LAB[a], stake:stake*(1/odds[a])/inv}, b:{lab:LAB[b], stake:stake*(1/odds[b])/inv},
             excl:LAB[ex], pExcl, ret, seCobrePct:(ret/stake-1)*100,
             evPct:((1-pExcl)*ret/stake-1)*100 };   // EV real (negativo = nao vale)
  }

  // ---------------- parsing DOM ----------------
  const txt = e => (e&&typeof e.innerText==='string')?e.innerText.trim():'';
  const num = o => { const n=parseFloat(String(o).replace(',','.')); return isNaN(n)?null:n; };
  function parseRelogio(s){ const m=String(s||'').match(/(\d+):(\d+)/); // MM:SS
    return m ? {min:+m[1], seg:+m[2], tot:+m[1]+(+m[2])/60} : null; }
  function lerAcrescimo(fx){ // tenta "+N" no DOM da fixture (raro no overview)
    for(const e of fx.querySelectorAll('*')){ if(e.children.length) continue;
      const t=txt(e); const m=t.match(/^\+\s?(\d+)/); if(m) return +m[1]; }
    return null;
  }

  // ---------------- freshness ----------------
  function freshness(st, relogio, oddsCount, A, cfg, ss){
    const teto = (A!=null) ? 90+A+4 : 98;
    if (relogio && relogio.tot > teto) return {ok:false, strict:false, stale:'TETO'};
    // cross-check SofaScore (se disponivel)
    if (ss){
      if (ss.status==='finished') return {ok:false, strict:false, stale:'SS-FIM'};
      if (relogio && ss.min!=null && Math.abs(relogio.tot - ss.min) > cfg.clockSkewTol)
        return {ok:true, strict:false, stale:null, ssOk:false};
    }
    // congelado? compara segundos com o ultimo scan
    let advanced=true;
    if (st && st.lastTot!=null){
      if (relogio && relogio.tot === st.lastTot){
        st.stall = (st.stall||0)+1; advanced=false;
        if (st.stall >= cfg.stallScans) return {ok:false, strict:false, stale:'CONGELADO'};
      } else st.stall=0;
    }
    const mercadoOk = oddsCount>=3;
    return {ok:true, strict: advanced && mercadoOk && (!ss || ss.status!=='finished'),
            stale:null, ssOk: ss?true:undefined};
  }

  // ---------------- UX ----------------
  function ensureCSS(){
    if (document.getElementById('__avCSS')) return;
    const s=document.createElement('style'); s.id='__avCSS';
    s.textContent='@keyframes avPulse{0%{box-shadow:0 0 6px '+COR.GREEN+'aa}'
      +'50%{box-shadow:0 0 18px '+COR.GREEN+'}100%{box-shadow:0 0 6px '+COR.GREEN+'aa}}'
      +'.__avGreen{animation:avPulse 1s infinite}';
    document.head.appendChild(s);
  }
  function limpaCels(fx){ fx.querySelectorAll('.ovm-ParticipantOddsOnly').forEach(c=>{c.style.outline='';c.style.boxShadow='';}); }
  function limpa(fx){ fx.style.outline=''; fx.style.boxShadow=''; fx.classList.remove('__avGreen');
    limpaCels(fx); const b=fx.querySelector('.__avBadge'); if(b)b.remove(); }
  function pinta(fx, cor, pulse, texto, cellIdx){
    fx.style.outline='3px solid '+cor; fx.style.outlineOffset='-3px'; fx.style.position='relative';
    fx.classList.toggle('__avGreen', !!pulse);
    if(!pulse) fx.style.boxShadow='0 0 12px '+cor+'aa';
    limpaCels(fx);                                   // acende a CELULA exata p/ clicar (ARM/GREEN)
    const cells=fx.querySelectorAll('.ovm-ParticipantOddsOnly');
    if(cellIdx>=0 && cells[cellIdx]){ cells[cellIdx].style.outline='3px solid '+cor;
      cells[cellIdx].style.boxShadow='inset 0 0 16px '+cor; }
    let b=fx.querySelector('.__avBadge');
    if(!b){ b=document.createElement('div'); b.className='__avBadge';
      b.style.cssText='position:absolute;top:2px;left:2px;z-index:9;font:bold 10px sans-serif;'
        +'padding:1px 5px;border-radius:3px;color:#000;pointer-events:none;white-space:nowrap';
      fx.prepend(b); }
    b.style.background=cor; b.innerHTML=String(texto).replace(/\n/g,'<br>');  // suporta 2 linhas (Dutch)
  }

  // ---------------- scan ----------------
  function scan(cfg, now){
    let cont={IDLE:0,WATCH:0,ARM:0,GREEN:0,STALE:0};
    ssFetch(cfg.ssUrl, now);                 // atualiza o cross do SofaScore (async)
    const pn = cfg.painel ? lerPainel() : null;          // momentum do jogo ABERTO no painel
    const pnMom = pn ? momentumPainel(pn.stats) : null;
    const pnC = pn ? normalizarTime(pn.casa) : '', pnF = pn ? normalizarTime(pn.fora) : '';
    // TRAVA DE MERCADO: o modelo so vale p/ "Resultado Final" (1/X/2). Em "Proximo Gol"
    // ou "Partida - Gols" as 3 odds significam outra coisa -> nao sinaliza (evita erro).
    const tabAtiva=((document.querySelector('.ovm-ClassificationMarketSwitcherMenu_Item-active')||{}).textContent||'').trim();
    if(tabAtiva && !/Resultado Final/i.test(tabAtiva)){
      document.querySelectorAll('.ovm-Fixture').forEach(limpa);
      barra(cont, cfg, 'mercado "'+tabAtiva+'" — troque p/ "Resultado Final"');
      return;
    }
    document.querySelectorAll('.ovm-Fixture').forEach(fx=>{        // agrupada OU ordenada
        if(!fx.closest(SEL_LISTA)) return;                          // pula o jogo aberto (painel)
        const comp=fx.closest('.ovm-Competition');
        const liga=comp?(txt(comp.querySelector('.ovm-CompetitionHeader'))||'').split('\n')[0].trim():'';
        const nomes=[...fx.querySelectorAll('[class*="TeamName"]')].map(txt).filter(Boolean);
        const key=liga+'|'+nomes.join('|');
        // guard por-jogo: as vezes a fixture troca o 1X2 por "Marcar o Xo Gol" /
        // "Proximo Gol". Ai as 3 odds NAO sao 1/X/2 -> ignora (nao sinaliza errado).
        if(/Marcar o\s*\d|Pr[oó]ximo Gol/i.test(fx.textContent||'')){ limpa(fx); cont.IDLE++; return; }
        const relogio=parseRelogio((fx.querySelector('.ovm-InPlayTimer')||{}).innerText);
        const pl=[...fx.querySelectorAll('.ovm-ScorePill')].map(e=>parseInt(e.innerText,10));
        const odds=[...fx.querySelectorAll('.ovm-ParticipantOddsOnly')].map(e=>num(e.innerText));
        const oddsCount=odds.filter(v=>v!=null).length;

        if(!relogio || pl.length<2 || relogio.tot<cfg.watchMin){ limpa(fx); cont.IDLE++;
          if(ST[key]) ST[key].lastTot = relogio?relogio.tot:ST[key].lastTot; return; }

        const st = ST[key] = ST[key] || {};
        const ss = ssLookup(nomes[0], nomes[1]);
        const A = (ss && ss.injury!=null) ? ss.injury : lerAcrescimo(fx);
        const fr = freshness(st, relogio, oddsCount, A, cfg, ss);

        if(fr.stale){ limpa(fx); pinta(fx, COR.STALE, false, 'STALE '+fr.stale, -1);
          st.lastTot=relogio.tot; st.green=0; cont.STALE++; return; }

        // modelo
        // momentum: painel do bet365 (jogo aberto) tem prioridade; senao SofaScore; senao 1.0
        let momC=(ss&&ss.mom)?ss.mom.casa:1, momF=(ss&&ss.mom)?ss.mom.fora:1;
        if(pnMom && pnC===normalizarTime(nomes[0]) && pnF===normalizarTime(nomes[1])){
          momC=pnMom.casa; momF=pnMom.fora;
        }
        const forca = forcaLocal(cfg.ssUrl, nomes[0], nomes[1]) || (ss?ss.forca:null);  // FBref local > SofaScore
        const [pc,pe,pf]=probs(relogio.tot, pl[0], pl[1], A!=null?A:cfg.unknownStoppageFloor,
                               {momC, momF, redC:0, redF:0, forca});
        const dom=dominante(pl[0],pl[1],pc,pe,pf);
        const be=1/dom.prob, oddTela=odds[dom.idx];
        const valor=(oddTela!=null)&&(oddTela>be);
        const mercadoOk=oddsCount>=3 && (!cfg.exigeOddAtiva || oddTela!=null);

        // tiers
        const greenMin = (A!=null) ? 90+Math.max(0,A-cfg.greenBuffer) : 90+cfg.unknownStoppageFloor;
        const greenCeil = (A!=null) ? 90+A+cfg.greenOvershoot : 90+cfg.hardCeiling;
        const noSurge = (st.lastScore===undefined || st.lastScore===pl.join('-'))
                        && (st.lastOdds===undefined || !(st.lastOdds<3 && oddsCount>=3)); // sem flap
        const armOk = relogio.tot>=cfg.armMin && dom.prob>=cfg.probMin && valor && mercadoOk && fr.ok;
        const greenCond = armOk && relogio.tot>=greenMin && relogio.tot<=greenCeil
                          && fr.strict && noSurge && mercadoOk;
        st.green = greenCond ? (st.green||0)+1 : 0;
        const isGreen = st.green>=cfg.confirmScans;

        let tier = isGreen?'GREEN' : armOk?'ARM' : 'WATCH';
        const tela = oddTela!=null?oddTela.toFixed(2):'susp';
        const aTxt = A!=null?('+'+A):'+?';
        const motivo = !mercadoOk?' SUSPENSO' : (!noSurge?' GOL?' : '');
        let txtBadge = `${tier}${tier==='ARM'?motivo:''} ${dom.lab} ${(dom.prob*100).toFixed(0)}%`
                       + ` | just ${be.toFixed(2)} | tela ${tela} ${valor?'✓':'✗'} | ${aTxt}`;
        if(cfg.dutch && (tier==='ARM'||tier==='GREEN')){          // plano de Dutching (cobrir 2)
          const dt=dutch(odds, [pc,pe,pf], cfg.stakeTotal);
          if(dt){ const pA=Math.round(dt.a.stake/cfg.stakeTotal*100), pB=Math.round(dt.b.stake/cfg.stakeTotal*100);
            const lucroCob=dt.ret-cfg.stakeTotal;   // lucro/prejuizo se um dos 2 cobrir
            txtBadge += `\n💰 R$${dt.a.stake.toFixed(2)} ${dt.a.lab} (${pA}%) + R$${dt.b.stake.toFixed(2)} ${dt.b.lab} (${pB}%)`
            + ` → volta R$${dt.ret.toFixed(2)} de R$${cfg.stakeTotal} = ${lucroCob>=0?'LUCRO +':'PERDE '}R$${lucroCob.toFixed(2)} se cobrir`
            + ` · EV ${dt.evPct>=0?'+':''}${dt.evPct.toFixed(1)}%${dt.evPct>0?'✅':''} · perde tudo se ${dt.excl}`;
          }
        }
        pinta(fx, COR[tier], isGreen, txtBadge, tier==='WATCH'?-1:dom.idx);  // acende a celula 1/X/2
        if(isGreen && st.green===cfg.confirmScans){          // so na transicao p/ GREEN
          beep();
          logarSinal(cfg.ssUrl, {liga, casa:nomes[0], fora:nomes[1],
            event_id: ss?ss.event_id:null, minuto:+relogio.tot.toFixed(1),
            placar:pl.join('-'), resultado:dom.lab, prob:+dom.prob.toFixed(4),
            breakeven:+be.toFixed(3), odd_tela:oddTela, acrescimo:A});
        }
        cont[tier]++;

        st.lastTot=relogio.tot; st.lastScore=pl.join('-'); st.lastOdds=oddsCount;
    });
    barra(cont, cfg);
  }

  function beep(){ try{ const a=new (window.AudioContext||window.webkitAudioContext)();
    const o=a.createOscillator(); o.connect(a.destination); o.frequency.value=920;
    o.start(); setTimeout(()=>o.stop(),200);}catch(e){} }

  function barra(c,cfg,aviso){ let bar=document.getElementById('__avBar');
    if(!bar){ bar=document.createElement('div'); bar.id='__avBar';
      bar.style.cssText='position:fixed;bottom:10px;right:10px;z-index:99999;background:#111;'
        +'color:#fff;border:1px solid #444;font:bold 12px sans-serif;padding:8px 12px;border-radius:6px;line-height:1.4';
      document.body.appendChild(bar); }
    const linha2 = aviso
      ? `<span style="color:${COR.STALE}">⚠️ ${aviso}</span>`
      : `arm≥${cfg.armMin}' prob≥${cfg.probMin} · SofaScore: `
        + (cfg.ssUrl ? (Object.keys(ssCache.data).length+' jogos') : 'off');
    bar.innerHTML=`<span style="color:#33d17a;font-weight:bold">${VERSAO}</span>  `
      +`<span style="color:${COR.GREEN}">GREEN ${c.GREEN}</span> · `
      +`<span style="color:${COR.ARM}">ARM ${c.ARM}</span> · `
      +`<span style="color:${COR.WATCH}">WATCH ${c.WATCH}</span> · `
      +`<span style="color:${COR.STALE}">STALE ${c.STALE}</span><br>`+linha2;
  }

  // ---------------- API ----------------
  window.iniciarValor = function(over){
    const cfg=Object.assign({}, DEF, over||{});
    window.pararValor();
    ensureCSS();
    const tick=()=>scan(cfg, Date.now());
    tick(); timer=setInterval(tick, cfg.intervaloMs);
    console.log('%cAlertador v2 ON','color:#2bd24f;font-weight:bold', cfg);
    console.log('GREEN = fundo nos acrescimos + criterios + relogio fresco. NAO e "faltam 40s". Confira o jogo antes de clicar.');
    return cfg;
  };
  window.pararValor = function(){
    if(timer)clearInterval(timer); timer=null;
    document.querySelectorAll('.ovm-Fixture').forEach(limpa);
    const bar=document.getElementById('__avBar'); if(bar)bar.remove();
    for(const k in ST) delete ST[k];
    console.log('%cAlertador v2 OFF','color:#888');
  };
})();
