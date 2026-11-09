@echo off
chcp 65001 > nul
rem Gera os box plots por estado a partir da pasta resultados_uf.
rem Deixe este arquivo na mesma pasta de graficos_uf.py e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta resultados_uf (onde estao os *_uf_horario.csv)
echo e tecle Enter:
set /p PASTA=Pasta: 
set PASTA=%PASTA:"=%
echo.
echo Estagios a considerar (ex.: 2 13 para o ano de 2030). Enter = todos:
set /p EST=Estagios: 

if "%EST%"=="" (
    python graficos_uf.py "%PASTA%"
) else (
    python graficos_uf.py "%PASTA%" --estagios %EST%
)
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
    goto fim
)
echo.
echo Gerando graficos de dia util x fim de semana/feriado...
python graficos_semana.py "%PASTA%"
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
:fim
echo.
pause
