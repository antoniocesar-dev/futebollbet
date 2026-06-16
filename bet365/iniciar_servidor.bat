@echo off
REM Sobe o servidor local de forca (FBref) em http://localhost:8765
REM Por padrao NAO toca no SofaScore (IP bloqueado) — serve so /forca do cache FBref.
REM Quando o IP do SofaScore liberar, adicione  --momentum  na linha abaixo.
cd /d "%~dp0.."
echo Servidor de forca rodando. Deixe esta janela aberta enquanto aposta.
echo No console do bet365:  iniciarValor({ssUrl:'http://localhost:8765'})
py bet365\sofascore_live.py servir
pause
