# -*- coding: utf-8 -*-
"""
validar_sinais.py — liquida os sinais GREEN logados (sinal_log) contra o
resultado real e mede acerto + P&L + calibracao do modelo.

O alertador (com ssUrl ligado) loga cada GREEN em sinal_log via o servidor
(sofascore_live.py). Aqui a gente:
  1. Para cada sinal ainda sem resultado_final, busca o placar final do jogo
     (pelo event_id na tabela evento; opcional: --fetch via API).
  2. Marca acertou (o resultado apostado se manteve?) e pnl (odd-1 se acertou,
     senao -1).
  3. Mostra: taxa de acerto, P&L total/ROI, e um diagrama de confiabilidade
     (prob prevista media vs frequencia real de acerto) — o teste honesto de
     "o modelo esta calibrado?".

Uso:
  py bet365/validar_sinais.py             # liquida pelo banco + relatorio
  py bet365/validar_sinais.py --fetch     # tenta puxar placares faltantes via API
  py bet365/validar_sinais.py --listar    # lista os sinais (settled e pendentes)
"""
import argparse
import os
import sqlite3
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(RAIZ, "futebol.db")


def conectar():
    con = sqlite3.connect(DB)
    with open(os.path.join(RAIZ, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())
    return con


def resultado_de(gc, gf):
    return "CASA" if gc > gf else "FORA" if gc < gf else "EMPATE"


def placar_final(con, event_id, usar_fetch):
    """(gols_casa, gols_fora) do jogo encerrado, do banco ou via API."""
    if event_id:
        row = con.execute("SELECT status, gols_casa, gols_fora FROM evento WHERE id=?",
                           (event_id,)).fetchone()
        if row and row[0] == "finished" and row[1] is not None:
            return row[1], row[2]
    if usar_fetch and event_id:
        try:
            sys.path.insert(0, os.path.join(RAIZ, "bet365"))
            import transporte
            st, data = transporte.buscar(f"/event/{event_id}", ok_404=True)
            if st == 200 and data:
                ev = data.get("event", {})
                if (ev.get("status", {}) or {}).get("type") == "finished":
                    return (ev.get("homeScore", {}).get("current"),
                            ev.get("awayScore", {}).get("current"))
        except Exception:
            pass
    return None, None


def liquidar(con, usar_fetch):
    pend = con.execute("SELECT id, event_id, resultado, odd_tela FROM sinal_log "
                       "WHERE resultado_final IS NULL").fetchall()
    n = 0
    for sid, eid, aposta, odd in pend:
        gc, gf = placar_final(con, eid, usar_fetch)
        if gc is None:
            continue
        final = resultado_de(gc, gf)
        acertou = 1 if final == aposta else 0
        pnl = ((odd or 0) - 1.0) if acertou else -1.0
        con.execute("UPDATE sinal_log SET resultado_final=?, acertou=?, pnl=? WHERE id=?",
                    (final, acertou, round(pnl, 3), sid))
        n += 1
    con.commit()
    return n, len(pend)


def relatorio(con):
    rows = con.execute("SELECT prob, odd_tela, acertou, pnl FROM sinal_log "
                       "WHERE resultado_final IS NOT NULL").fetchall()
    total_pend = con.execute("SELECT COUNT(*) FROM sinal_log WHERE resultado_final IS NULL").fetchone()[0]
    if not rows:
        print(f"Nenhum sinal liquidado ainda. Pendentes: {total_pend}.")
        return
    n = len(rows)
    acertos = sum(r[2] for r in rows)
    pnl = sum(r[3] for r in rows)
    odd_media = sum(r[1] or 0 for r in rows) / n
    prob_media = sum(r[0] or 0 for r in rows) / n
    print(f"=== {n} sinais liquidados ({total_pend} pendentes) ===")
    print(f"  Acerto:  {acertos}/{n} = {acertos/n*100:.1f}%   (modelo previa {prob_media*100:.1f}%)")
    print(f"  P&L:     {pnl:+.2f} u   |   ROI {pnl/n*100:+.1f}% por aposta   |   odd media {odd_media:.2f}")
    print(f"  Sanidade calibracao: previsto {prob_media*100:.1f}% vs real {acertos/n*100:.1f}% "
          f"(diferenca {abs(prob_media*100-acertos/n*100):.1f} pp)")
    # diagrama de confiabilidade por faixa de prob
    print("  --- confiabilidade (prob prevista -> acerto real) ---")
    faixas = [(0.70, 0.80), (0.80, 0.90), (0.90, 0.95), (0.95, 1.01)]
    for lo, hi in faixas:
        sub = [r for r in rows if lo <= (r[0] or 0) < hi]
        if sub:
            ac = sum(r[2] for r in sub) / len(sub)
            print(f"    {lo*100:.0f}-{hi*100:.0f}%: n={len(sub):3}  acerto real {ac*100:5.1f}%")
    if pnl < 0:
        print("  >> P&L negativo: confirma a expectativa -EV. O sinal melhora timing/disciplina,")
        print("     nao vira +EV. Mantenha limite de perda.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="puxa placares faltantes via API")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--marcar", nargs=2, metavar=("ID", "RESULTADO"),
                    help="marca o resultado real manualmente: --marcar 5 CASA")
    a = ap.parse_args()
    con = conectar()
    if a.marcar:
        sid, res = int(a.marcar[0]), a.marcar[1].upper()
        row = con.execute("SELECT casa, fora, resultado, odd_tela FROM sinal_log WHERE id=?",
                          (sid,)).fetchone()
        if not row:
            print(f"sinal id {sid} nao existe"); con.close(); return
        casa, fora, aposta, odd = row
        acertou = 1 if res == aposta else 0
        pnl = ((odd or 0) - 1.0) if acertou else -1.0
        con.execute("UPDATE sinal_log SET resultado_final=?, acertou=?, pnl=? WHERE id=?",
                    (res, acertou, round(pnl, 3), sid))
        con.commit()
        print(f"#{sid} {casa} x {fora}: apostou {aposta}, saiu {res} -> "
              f"{'ACERTOU' if acertou else 'ERROU'} | P&L {pnl:+.2f}u (odd {odd})")
        con.close(); return
    if a.listar:
        print(f"{'id':>3} {'ts':19} aposta@odd  -> resultado | acertou pnl   (jogo)")
        for r in con.execute("SELECT id,ts,casa,fora,resultado,odd_tela,resultado_final,acertou,pnl "
                             "FROM sinal_log ORDER BY id DESC LIMIT 40"):
            print(f"#{r[0]:>2} {r[1]} {r[4]}@{r[5]} -> {r[6] or 'PENDENTE'} | "
                  f"{'OK' if r[7]==1 else ('X' if r[7]==0 else '?')} {r[8] if r[8] is not None else ''}  ({r[2]} x {r[3]})")
        con.close(); return
    feitos, pend = liquidar(con, a.fetch)
    print(f"Liquidados agora: {feitos} (de {pend} pendentes)\n")
    relatorio(con)
    con.close()


if __name__ == "__main__":
    main()
