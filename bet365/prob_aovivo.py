# -*- coding: utf-8 -*-
"""
prob_aovivo.py — probabilidade de resultado AO VIVO (1X2) dado minuto + placar.

Modelo (calibrado em bet365/hazard_cal.json, gerado por calibrar_hazard.py):
  - Hazard de gols INOMOGENEO no tempo: lambda(t) varia por minuto (curva real
    do futebol.db; o fim de jogo e mais quente que a media). Integra o hazard
    sobre o tempo restante -> Lambda (gols esperados ate o fim).
  - Acrescimo do 2T tratado como DISTRIBUICAO (o anunciado e um piso; o arbitro
    sempre estende). Marginaliza os minutos extras.
  - Multiplicadores ao vivo (default 1.0 -> degrada pro modelo-tempo):
      * placar  : time perdendo pressiona, lider segura (rampa pelo tempo)
      * vermelho: time com um a menos marca menos / sofre mais
      * momentum: fator manual/externo (xG, pressao) por lado
  - Convolui dois Poisson (home/away) -> P(casa)/P(empate)/P(fora).
  - Banda de confianca: a incerteza das premissas vira um intervalo em P.

Uso:
  py bet365/prob_aovivo.py --min 89 --casa 1 --fora 1
  py bet365/prob_aovivo.py --min 90 --casa 1 --fora 1 --acrescimo 4
  py bet365/prob_aovivo.py --min 88 --casa 2 --fora 1 --vermelho-fora 1
  py bet365/prob_aovivo.py --min 87 --casa 1 --fora 1 --mom-casa 1.4   # casa pressionando

NAO e conselho de aposta. So a matematica do cenario.
"""
import argparse
import json
import math
import os
import sqlite3
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PASTA = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.path.join(PASTA, "hazard_cal.json")

# Fallback se hazard_cal.json nao existir (rode calibrar_hazard.py).
CAL_DEFAULT = {
    "gols_por_jogo": 2.2682, "home_share": 0.5489, "taxa_media_min": 0.0252,
    "h_reg_buckets": [0.0124, 0.0186, 0.0130, 0.0133, 0.0186, 0.0210, 0.0173,
                      0.0213, 0.0207, 0.0193, 0.0217, 0.0210, 0.0180, 0.0240,
                      0.0180, 0.0183, 0.0250, 0.0230],
    "h_stop_1h": 0.0297, "h_stop_2h": 0.0313,
    "stoppage_extra_pmf": [0.45, 0.28, 0.15, 0.08, 0.04],
    "red": {"down": 0.74, "up": 1.30},
    "mult": {"sigma": 0.35, "d0": 1.5, "clampLo": 0.45, "clampHi": 2.2},
    "sigma_log": {"base": 0.30, "sem_stats": 0.10, "por_mult": 0.15},
}


def carregar_cal(path=CAL_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return CAL_DEFAULT


# ----------------------------------------------------------- hazard / lambda
def lam_regular_restante(m, h_reg):
    """Integra o hazard regular (buckets de 5 min) de `m` ate 90'."""
    if m >= 90:
        return 0.0
    total = 0.0
    for b in range(len(h_reg)):           # bucket b cobre [5b, 5b+5)
        lo, hi = 5.0 * b, 5.0 * b + 5.0
        ov = min(90.0, hi) - max(m, lo)
        if ov > 0:
            total += h_reg[b] * ov
    return total


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def multiplicadores(gc, gf, m, restante, cal, mom_casa, mom_fora, red_casa, red_fora):
    """Retorna (M_casa, M_fora): fatores na taxa de gols de cada lado."""
    mu = cal.get("mult", CAL_DEFAULT["mult"])
    red = cal.get("red", CAL_DEFAULT["red"])
    sigma, d0 = mu["sigma"], mu["d0"]
    lo, hi = mu["clampLo"], mu["clampHi"]

    # placar: lider segura, perdedor pressiona; rampa com o tempo
    d = gc - gf
    push = 0.5 + 0.5 * (min(m, 90.0) / 90.0)
    t = math.tanh(d / d0)
    m_score_c = 1.0 + sigma * (-t * push)
    m_score_f = 1.0 + sigma * (t * push)

    # vermelho: net>0 => casa com mais cartoes (desvantagem)
    net = (red_casa or 0) - (red_fora or 0)
    neff = abs(net) * min(1.0, max(0.0, restante) / 30.0)
    if net > 0:                            # casa em desvantagem
        m_red_c, m_red_f = red["down"] ** neff, red["up"] ** neff
    elif net < 0:                          # fora em desvantagem
        m_red_c, m_red_f = red["up"] ** neff, red["down"] ** neff
    else:
        m_red_c = m_red_f = 1.0

    M_c = clamp((mom_casa or 1.0) * m_score_c * m_red_c, lo, hi)
    M_f = clamp((mom_fora or 1.0) * m_score_f * m_red_f, lo, hi)
    return M_c, M_f


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def convolui(gc, gf, lam_casa, lam_fora, kmax=8):
    """P(casa)/P(empate)/P(fora) do placar FINAL dado gols adicionais ~ Poisson."""
    p_casa = p_emp = p_fora = 0.0
    for a in range(kmax + 1):
        pa = poisson_pmf(a, lam_casa)
        for b in range(kmax + 1):
            pb = poisson_pmf(b, lam_fora)
            fc, ff = gc + a, gf + b
            if fc > ff:   p_casa += pa * pb
            elif fc < ff: p_fora += pa * pb
            else:         p_emp += pa * pb
    s = p_casa + p_emp + p_fora or 1.0
    return p_casa / s, p_emp / s, p_fora / s


def lam_total_para_x(m, lam_reg, h_stop_2h, A, x):
    """Lambda combinado integrando o acrescimo jogado S = A + x."""
    S = A + x
    elapsed_stop = max(0.0, m - 90.0)
    rem_stop = max(0.0, S - elapsed_stop)
    return lam_reg + h_stop_2h * rem_stop


MIN_JOGOS_FORCA = 3     # min de jogos no mando p/ confiar na forca do time
K_SHRINK = 5.0          # shrinkage: w = n/(n+K) -> 5 jogos = meio caminho
W_MAX = 0.85            # nunca confia 100% no time (sempre sobra ruido)


def blend_forca(cal, share_ref, forca, h2h_share, peso_h2h):
    """Combina a forca-por-time (ataque x defesa) com o modelo global.
    Retorna (r_eff, sh_eff): fator de NIVEL e SHARE da casa ja shrinkados.
    Com forca ausente/insuficiente -> (1.0, share_ref): cai no modelo global EXATO."""
    r_eff, sh_eff = 1.0, share_ref
    if forca:
        lcf, laf, n = forca.get("lam_casa"), forca.get("lam_fora"), forca.get("n", 0)
        if lcf and laf and (lcf + laf) > 0 and n >= MIN_JOGOS_FORCA:
            total = lcf + laf
            r = total / cal["gols_por_jogo"]          # quao goleador e o confronto vs media
            sh_team = lcf / total                       # share da casa NESTE confronto
            w = min(W_MAX, n / (n + K_SHRINK))          # confianca pela amostra
            r_eff = 1.0 + w * (r - 1.0)
            sh_eff = share_ref + w * (sh_team - share_ref)
    if h2h_share is not None and peso_h2h > 0:           # nudge opcional de confronto direto
        sh_eff = sh_eff + peso_h2h * (h2h_share - sh_eff)
    return r_eff, min(0.95, max(0.05, sh_eff))


def probabilidades(m, gc, gf, cal, acrescimo=4.0, share=None,
                   mom_casa=1.0, mom_fora=1.0, red_casa=0, red_fora=0,
                   escala_lam=1.0, forca=None, h2h_share=None, peso_h2h=0.0):
    """Retorna (p_casa, p_empate, p_fora) marginalizando o acrescimo extra."""
    h_reg = cal["h_reg_buckets"]
    h_stop = cal["h_stop_2h"]
    pmf = cal.get("stoppage_extra_pmf", CAL_DEFAULT["stoppage_extra_pmf"])
    share_ref = cal["home_share"] if share is None else share
    r_eff, sh_eff = blend_forca(cal, share_ref, forca, h2h_share, peso_h2h)

    lam_reg = lam_regular_restante(m, h_reg)
    restante = max(0.0, 90.0 - m) + acrescimo
    M_c, M_f = multiplicadores(gc, gf, m, restante, cal,
                               mom_casa, mom_fora, red_casa, red_fora)

    p_c = p_e = p_f = 0.0
    wsum = 0.0
    for x, w in enumerate(pmf):
        lam_t = lam_total_para_x(m, lam_reg, h_stop, acrescimo, x) * escala_lam * r_eff
        lam_casa = lam_t * sh_eff * M_c
        lam_fora = lam_t * (1.0 - sh_eff) * M_f
        pc, pe, pf = convolui(gc, gf, lam_casa, lam_fora)
        p_c += w * pc; p_e += w * pe; p_f += w * pf
        wsum += w
    if wsum > 0:
        p_c, p_e, p_f = p_c / wsum, p_e / wsum, p_f / wsum
    return p_c, p_e, p_f


def mantem(gc, gf, p_casa, p_emp, p_fora):
    """Probabilidade do RESULTADO ATUAL se manter."""
    if gc > gf:   return p_casa, "CASA"
    if gc < gf:   return p_fora, "FORA"
    return p_emp, "EMPATE"


def banda_confianca(m, gc, gf, cal, **kw):
    """Intervalo em P(resultado atual) propagando incerteza no Lambda."""
    sl = cal.get("sigma_log", CAL_DEFAULT["sigma_log"])
    sigma_log = sl["base"]
    if kw.get("mom_casa", 1.0) == 1.0 and kw.get("mom_fora", 1.0) == 1.0:
        sigma_log += sl.get("sem_stats", 0.10)
    # mais gols (exp(+s)) -> resultado mais facil de mudar -> p_mantem menor
    p_hi = probabilidades(m, gc, gf, cal, escala_lam=math.exp(-sigma_log), **kw)
    p_lo = probabilidades(m, gc, gf, cal, escala_lam=math.exp(+sigma_log), **kw)
    return mantem(gc, gf, *p_lo)[0], mantem(gc, gf, *p_hi)[0]


def forca_time_db(evento_id):
    """Forca do confronto (lam_casa_full, lam_fora_full, n) do futebol.db,
    reusando a logica ataque x defesa do probabilidades.py. None se faltar dado."""
    raiz = os.path.dirname(PASTA)
    sys.path.insert(0, raiz)
    try:
        import probabilidades as P
    except Exception:
        return None
    con = sqlite3.connect(os.path.join(raiz, "futebol.db"))
    try:
        ev = con.execute("SELECT casa_id,fora_id,temporada_id FROM evento WHERE id=?",
                         (evento_id,)).fetchone()
        if not ev:
            return None
        casa_id, fora_id, temp = ev
        mlc, mlf = con.execute("SELECT AVG(gols_casa),AVG(gols_fora) FROM evento "
                               "WHERE status='finished' AND temporada_id=?", (temp,)).fetchone()
        atq_c, def_c = P.medias_time(con, casa_id, True, temp)
        atq_f, def_f = P.medias_time(con, fora_id, False, temp)
        nc = con.execute("SELECT COUNT(*) FROM evento WHERE casa_id=? AND status='finished' "
                         "AND temporada_id=? AND gols_casa IS NOT NULL", (casa_id, temp)).fetchone()[0]
        nf = con.execute("SELECT COUNT(*) FROM evento WHERE fora_id=? AND status='finished' "
                         "AND temporada_id=? AND gols_casa IS NOT NULL", (fora_id, temp)).fetchone()[0]
    finally:
        con.close()
    if None in (mlc, mlf, atq_c, def_c, atq_f, def_f) or not mlc or not mlf:
        return None
    # n limitado a 19 = janela que medias_time realmente usa (nao infla o shrinkage)
    return {"lam_casa": atq_c * def_f / mlc, "lam_fora": atq_f * def_c / mlf,
            "n": min(nc, nf, 19)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, required=True)
    ap.add_argument("--casa", type=int, required=True)
    ap.add_argument("--fora", type=int, required=True)
    ap.add_argument("--acrescimo", type=float, default=4.0, help="acrescimo anunciado (piso)")
    ap.add_argument("--share", type=float, default=None, help="override do share da casa")
    ap.add_argument("--mom-casa", type=float, default=1.0, help="multiplicador de momentum casa")
    ap.add_argument("--mom-fora", type=float, default=1.0)
    ap.add_argument("--vermelho-casa", type=int, default=0)
    ap.add_argument("--vermelho-fora", type=int, default=0)
    ap.add_argument("--evento", type=int, default=None, help="id SofaScore: puxa forca dos times do banco")
    ap.add_argument("--lam-casa-full", type=float, default=None, help="forca manual: gols/jogo esperados casa")
    ap.add_argument("--lam-fora-full", type=float, default=None)
    ap.add_argument("--n-jogos", type=int, default=10, help="amostra p/ shrinkage da forca manual")
    ap.add_argument("--h2h-share", type=float, default=None, help="share casa do confronto direto (0..1)")
    ap.add_argument("--peso-h2h", type=float, default=0.0, help="peso do H2H (default 0 = off)")
    a = ap.parse_args()

    cal = carregar_cal()
    # forca-por-time: --evento (banco) tem prioridade; senao --lam-casa/fora-full manuais
    forca = None
    if a.evento is not None:
        forca = forca_time_db(a.evento)
    elif a.lam_casa_full and a.lam_fora_full:
        forca = {"lam_casa": a.lam_casa_full, "lam_fora": a.lam_fora_full, "n": a.n_jogos}

    kw = dict(acrescimo=a.acrescimo, share=a.share, mom_casa=a.mom_casa,
              mom_fora=a.mom_fora, red_casa=a.vermelho_casa, red_fora=a.vermelho_fora,
              forca=forca, h2h_share=a.h2h_share, peso_h2h=a.peso_h2h)
    pc, pe, pf = probabilidades(a.min, a.casa, a.fora, cal, **kw)
    pm, lab = mantem(a.casa, a.fora, pc, pe, pf)
    blo, bhi = banda_confianca(a.min, a.casa, a.fora, cal, **kw)

    restante = max(0.0, 90.0 - a.min) + a.acrescimo
    odd = lambda p: f"{1/p:6.2f}" if p > 0 else "  inf"
    if forca:
        share_disp = a.share if a.share is not None else cal["home_share"]
        r_eff, sh_eff = blend_forca(cal, share_disp, forca, a.h2h_share, a.peso_h2h)
        print(f"\n[forca-time] λ_casa={forca['lam_casa']:.2f} λ_fora={forca['lam_fora']:.2f} "
              f"n={forca['n']} -> nivel x{r_eff:.2f}, share casa {sh_eff*100:.0f}% "
              f"(global {cal['home_share']*100:.0f}%)")
    else:
        print("\n[forca-time] sem dado de time -> modelo global (cai no comportamento padrao)")
    print(f"Placar {a.casa}-{a.fora} aos {a.min:.0f}'  |  ~{restante:.1f} min ate o fim "
          f"(acrescimo {a.acrescimo:.0f} = piso)  |  cal: {cal.get('_meta',{}).get('n_jogos','?')} jogos")
    print("-" * 60)
    print(f"  Vitoria casa : {pc*100:6.2f}%   odd justa {odd(pc)}")
    print(f"  EMPATE       : {pe*100:6.2f}%   odd justa {odd(pe)}")
    print(f"  Vitoria fora : {pf*100:6.2f}%   odd justa {odd(pf)}")
    print("-" * 60)
    print(f"  Resultado atual ({lab}) se mantem: {pm*100:5.1f}%  "
          f"[banda {blo*100:.0f}-{bhi*100:.0f}%]  breakeven {1/pm:.2f}")
    print("Obs: banda larga = entrada incerta. Odd real do bet365 vem com margem (menor).")


if __name__ == "__main__":
    main()
