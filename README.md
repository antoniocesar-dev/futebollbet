# Futebol — coleta SofaScore + probabilidades ao vivo (bet365)

Projeto pessoal de análise esportiva. Duas partes:

1. **Coletor SofaScore** — alimenta um banco SQLite de partidas (resultados,
   estatísticas, escalações, xG, odds, incidentes) e calcula probabilidades 1X2
   (odds implícitas + Poisson de ataque/defesa + modelo ML).
2. **Alertador ao vivo bet365** (`bet365/`) — **somente leitura**: monitora jogos
   no fim, calcula a probabilidade do resultado atual se manter (modelo de hazard
   calibrado nos dados coletados) e **sinaliza** janelas de valor. Não aposta —
   o humano decide e clica.

## ⚠️ Aviso importante

- **Uso pessoal/educacional e de pesquisa.** Não é aconselhamento de aposta.
- **Somente leitura.** O alertador **não automatiza apostas** — apenas sinaliza.
  Automatizar cliques de aposta viola os Termos de Uso do bet365.
- **Respeite os ToS.** Os Termos do bet365 e do SofaScore proíbem scraping/uso
  comercial/redistribuição. Os **dados raspados não estão neste repositório**
  (veja `.gitignore`) — só o código.
- **Aposta é −EV.** A casa precifica e suspende mercados mais rápido que você
  clica. A ferramenta melhora *timing e disciplina*, não transforma em lucro.
  Defina limite de perda e aposte só o que pode perder. Jogo responsável.
- **Sem afiliação** com bet365 ou SofaScore. Sem garantia de qualquer tipo.

## Requisitos

```bash
pip install curl-cffi playwright scikit-learn xgboost joblib pandas numpy
playwright install chromium
```
(Windows: use `py -m pip install ...`. Nem tudo é necessário pra todo módulo.)

## Uso rápido

**Coleta + probabilidades (SofaScore):**
```bash
py coletor.py dia 2026-06-15        # coleta jogos do dia
py probabilidades.py proximos       # 1X2 dos jogos não iniciados
py raspador.py pendentes --limite 50
py manutencao.py                    # rotina diária (coleta + re-treino)
```

**Alertador ao vivo (bet365):**
```bash
py bet365/calibrar_hazard.py                 # gera bet365/hazard_cal.json
py bet365/prob_aovivo.py --min 89 --casa 1 --fora 1   # testa um cenário
py bet365/gerar_bookmarklet.py               # gera bet365/bookmarklet.html
```
No navegador, página Ao-Vivo→Futebol do bet365: cole `bet365/alertador_valor.js`
no console (ou instale o bookmarklet) e rode `iniciarValor()`.

Cross-check opcional (segunda fonte ao vivo):
```bash
py bet365/sofascore_live.py servir --forca   # serve http://localhost:8765
# console: iniciarValor({ssUrl:'http://localhost:8765'})
```

Validação dos sinais (P&L real):
```bash
py bet365/validar_sinais.py
```

## Estrutura

| Arquivo | O quê |
|---|---|
| `coletor.py` `raspador.py` `transporte.py` `gravar.py` | coleta SofaScore (REST + Playwright) |
| `schema.sql` | esquema do `futebol.db` |
| `probabilidades.py` `features.py` `treino.py` `prever.py` | modelos 1X2 / ML |
| `manutencao.py` | rotina agendada |
| `bet365/prob_aovivo.py` | modelo de probabilidade ao vivo (hazard λ(t) + força-time) |
| `bet365/alertador_valor.js` | alertador no navegador (tiers WATCH→ARM→GREEN) |
| `bet365/sofascore_live.py` | cross-check SofaScore (servidor local) |
| `bet365/calibrar_hazard.py` | calibração → `hazard_cal.json` |
| `bet365/validar_sinais.py` | backtest de P&L |
| `bet365/MAPEAMENTO-BET365.md` `MAPEAMENTO-SOFASCORE.md` | documentação |

## Licença

Sem licença formal — todos os direitos reservados ao autor. Uso por terceiros
sujeito aos avisos acima.
