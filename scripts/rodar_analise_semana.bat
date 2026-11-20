@echo off
chcp 65001 > nul
rem Dias uteis x fins de semana (2 dias de menor carga de cada semana), so com dados do SDDP.
rem Deixe este arquivo na mesma pasta de analise_semana_carga.py e graficos_uf.py e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta resultados_uf (com vergnd, gergnd e businj _uf_horario.csv) e tecle Enter:
set /p PASTA=Pasta resultados_uf: 
set PASTA=%PASTA:"=%
echo.
echo Cole o caminho da pasta do caso SDDP (onde estao os hrload??.dat) e tecle Enter:
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%

python analise_semana_carga.py "%PASTA%" --caso "%CASO%"
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
