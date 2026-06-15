# -*- coding: utf-8 -*-
"""
Treino e avaliação do modelo de ML (Estágio 3) — previsão 1X2.

- Split CRONOLÓGICO (treina no passado, testa no futuro) — sem vazamento temporal.
- Dois modelos: Regressão Logística (baseline robusto) e XGBoost.
- Imputação de features faltantes (mediana) dentro de um Pipeline.
- Avaliação por log-loss, Brier score multiclasse e acurácia, comparada a:
    * baseline ingênuo (taxas-base do treino: % casa/empate/fora)
    * baseline de mercado (odds implícitas), quando houver odds coletadas.
- Salva o melhor pipeline em `modelo.joblib`.

Uso:
  py treino.py                 # treina, avalia e salva
  py treino.py --teste 0.2     # fração final usada como teste (padrão 0.2)
"""
import argparse
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import joblib
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, accuracy_score
from xgboost import XGBClassifier

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import features as F

PASTA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(PASTA, "futebol.db")
MODELO_PATH = os.path.join(PASTA, "modelo.joblib")
CLASSES = ["H", "D", "A"]
MIN_TREINO = 50          # nº mínimo de jogos p/ treinar de forma minimamente séria


# ----------------------------------------------------------------- métricas
def brier_multiclasse(y_true_idx, probas):
    """Média, sobre as amostras, de sum_k (p_k - y_k)^2. Quanto menor, melhor.
    Varia de 0 (perfeito) a 2 (péssimo). Baseline aleatório ~0.66."""
    onehot = np.zeros_like(probas)
    onehot[np.arange(len(y_true_idx)), y_true_idx] = 1
    return np.mean(np.sum((probas - onehot) ** 2, axis=1))


def avaliar(nome, y_idx, probas):
    ll = log_loss(y_idx, probas, labels=[0, 1, 2])
    br = brier_multiclasse(y_idx, probas)
    ac = accuracy_score(y_idx, probas.argmax(axis=1))
    print(f"  {nome:<26} logloss={ll:.4f}  brier={br:.4f}  acuracia={ac:.1%}")
    return ll, br, ac


# ----------------------------------------------------------------- dados
def carregar_df():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        linhas = F.construir_dataset(con)
    finally:
        con.close()
    df = pd.DataFrame(linhas)
    df = df[df["alvo"].notna()].reset_index(drop=True)
    df = df.sort_values(["inicio_ts", "evento_id"]).reset_index(drop=True)
    return df


def descartar_features_vazias(df, cols):
    """Remove features 100% ausentes (ex.: xG/odds ainda não coletados),
    para não poluir o modelo. Retorna a lista de colunas mantidas."""
    mantidas = [c for c in cols if df[c].notna().any()]
    descartadas = [c for c in cols if c not in mantidas]
    if descartadas:
        print(f"Features ignoradas (sem dados ainda): {', '.join(descartadas)}")
    return mantidas


# ----------------------------------------------------------------- treino
def treinar(frac_teste=0.2):
    df = carregar_df()
    n = len(df)
    print(f"{n} jogos finalizados.  Alvo: "
          f"{(df['alvo']=='H').mean():.0%} casa / "
          f"{(df['alvo']=='D').mean():.0%} empate / "
          f"{(df['alvo']=='A').mean():.0%} fora")
    if n < MIN_TREINO:
        print(f"\n⚠️  Apenas {n} jogos — insuficiente para um modelo confiável "
              f"(ideal: 1000+ com detalhes). Treinando assim mesmo para validar "
              f"o pipeline; os números servem só de referência.")

    cols = descartar_features_vazias(df, F.COLUNAS)
    y = df["alvo"].map({c: i for i, c in enumerate(CLASSES)}).values
    X = df[cols].astype(float)

    corte = int(n * (1 - frac_teste))
    Xtr, Xte = X.iloc[:corte], X.iloc[corte:]
    ytr, yte = y[:corte], y[corte:]
    print(f"\nSplit cronológico: treino={len(Xtr)}  teste={len(Xte)}\n")

    # ---- baselines ----
    print("BASELINES (no conjunto de teste):")
    taxas = np.bincount(ytr, minlength=3) / len(ytr)
    base_proba = np.tile(taxas, (len(yte), 1))
    avaliar("ingênuo (taxas-base)", yte, base_proba)

    odds_cols = ["imp_casa", "imp_empate", "imp_fora"]
    if all(c in cols for c in odds_cols):
        mask = Xte[odds_cols].notna().all(axis=1).values
        if mask.sum() >= 10:
            avaliar(f"mercado/odds (n={mask.sum()})", yte[mask],
                    Xte.loc[mask, odds_cols].values)
        else:
            print("  mercado/odds            (odds insuficientes no teste)")
    else:
        print("  mercado/odds            (sem odds coletadas — colete com --detalhes)")

    # ---- modelos ----
    print("\nMODELOS (no conjunto de teste):")
    modelos = {
        "logística": Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("sc", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, C=0.5)),
        ]),
        "xgboost": Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("clf", XGBClassifier(
                n_estimators=180, max_depth=3, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
                reg_lambda=1.5, objective="multi:softprob", num_class=3,
                eval_metric="mlogloss", tree_method="hist", verbosity=0)),
        ]),
    }
    resultados = {}
    for nome, pipe in modelos.items():
        pipe.fit(Xtr, ytr)
        proba = pipe.predict_proba(Xte)
        # reordena colunas de proba para a ordem CLASSES (0,1,2) caso o clf reordene
        classes_ = pipe.named_steps["clf"].classes_
        idx = [list(classes_).index(i) for i in range(3)]
        resultados[nome] = (pipe, avaliar(nome, yte, proba[:, idx])[1])

    # ---- escolhe o melhor por Brier e re-treina em TODOS os dados ----
    melhor = min(resultados, key=lambda k: resultados[k][1])
    print(f"\n🏆 Melhor por Brier: {melhor}. Re-treinando em todos os {n} jogos…")
    final = modelos[melhor]
    final.fit(X, y)
    joblib.dump({"pipeline": final, "colunas": cols, "classes": CLASSES,
                 "n_treino": n, "modelo": melhor}, MODELO_PATH)
    print(f"Modelo salvo em {MODELO_PATH}")

    # importância de features (quando o modelo expõe)
    _importancias(final, cols)


def _importancias(pipe, cols):
    clf = pipe.named_steps["clf"]
    imp = None
    if hasattr(clf, "feature_importances_"):
        imp = clf.feature_importances_
    elif hasattr(clf, "coef_"):
        imp = np.abs(clf.coef_).mean(axis=0)
    if imp is None:
        return
    ordem = np.argsort(imp)[::-1]
    print("\nTop features:")
    for i in ordem[:10]:
        print(f"  {cols[i]:<16} {imp[i]:.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", type=float, default=0.2)
    a = ap.parse_args()
    treinar(a.teste)
