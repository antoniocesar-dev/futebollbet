# -*- coding: utf-8 -*-
"""
gerar_bookmarklet.py — transforma alertador_valor.js num bookmarklet (favorito
de 1 clique). Gera bet365/bookmarklet.html: abra no Chrome e ARRASTE o link pra
barra de favoritos. Depois, em qualquer pagina do bet365 (Ao-Vivo > Futebol),
clique no favorito pra LIGAR/DESLIGAR o alerter — sem console, sem "permitir colar".

Uso:  py bet365/gerar_bookmarklet.py
      py bet365/gerar_bookmarklet.py --ssurl http://localhost:8765
"""
import argparse
import os
import urllib.parse

PASTA = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssurl", default=None, help="liga o servidor local de forca/log")
    ap.add_argument("--stake", type=float, default=None, help="valor total p/ Dutching (ex.: 50)")
    ap.add_argument("--mais-tempo", action="store_true", help="sinaliza mais cedo (ARM 84', GREEN antes)")
    a = ap.parse_args()

    import re
    with open(os.path.join(PASTA, "alertador_valor.js"), encoding="utf-8") as f:
        js = f.read()
    mv = re.search(r"VERSAO\s*=\s*'([^']+)'", js)
    versao = mv.group(1) if mv else "?"

    cfg = []
    if a.ssurl:
        cfg.append("ssUrl:'%s'" % a.ssurl)
    if a.stake:
        cfg.append("stakeTotal:%g" % a.stake)
    if a.mais_tempo:
        cfg.append("armMin:84")          # ARM mais cedo = mais tempo p/ colocar as 2 apostas
        cfg.append("greenBuffer:2.5")    # GREEN comeca mais cedo dentro do acrescimo
        cfg.append("unknownStoppageFloor:1")
    arg = "{" + ",".join(cfg) + "}" if cfg else ""
    toggle = (js + "\n;(function(){"
              "if(window.__avOn){window.pararValor();window.__avOn=false;}"
              "else{window.iniciarValor(%s);window.__avOn=true;}})();" % arg)

    href = "javascript:" + urllib.parse.quote(toggle, safe="")
    tam = len(href)

    html = """<!doctype html><html lang="pt-br"><meta charset="utf-8">
<title>Instalar bet365 Alerter</title>
<body style="font:16px sans-serif;max-width:640px;margin:40px auto;line-height:1.6;color:#111">
<h2>⚡ Instalar o bet365 Alerter &mdash; {versao}</h2>
<p style="background:#ffd400;padding:6px 10px;border-radius:6px;display:inline-block">
Versao desta pagina: <b>{versao}</b>. Ao rodar, a barra no canto deve mostrar <b>{versao}</b>.
Se mostrar outra (ou nenhuma), o favorito esta velho &mdash; apague e arraste de novo.</p>
<ol>
  <li>Mostre a barra de favoritos do Chrome: <b>Ctrl+Shift+B</b>.</li>
  <li><b>Arraste</b> o bot&atilde;o verde abaixo para a barra de favoritos.</li>
  <li>Abra o bet365 em <b>Ao-Vivo &gt; Futebol</b> (com a aba na frente).</li>
  <li>Clique no favorito para <b>ligar</b>. Clique de novo para <b>desligar</b>.</li>
</ol>
<p style="font-size:22px;margin:28px 0">
  <a href="{href}"
     style="background:#2bd24f;color:#000;padding:10px 18px;border-radius:8px;
            text-decoration:none;font-weight:bold">&#9889; bet365 Alerter</a>
</p>
<p style="color:#666;font-size:13px">Tamanho do bookmarklet: {tam} caracteres{ss}.
Somente leitura &mdash; n&atilde;o aposta. Mant&eacute;m a aba do bet365 vis&iacute;vel
pro rel&oacute;gio andar.</p>
</body></html>""".format(href=html_escape(href), tam=tam, versao=versao,
                          ss=(" · SofaScore: " + a.ssurl) if a.ssurl else "")

    saida = os.path.join(PASTA, "bookmarklet.html")
    with open(saida, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Bookmarklet gerado ({tam} chars). Abra no Chrome e arraste o link:")
    print(f"  {saida}")


def html_escape(s):
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
