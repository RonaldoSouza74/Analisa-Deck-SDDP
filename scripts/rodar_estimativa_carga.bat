@echo off
chcp 65001 > nul
rem Estima a sensibilidade do vertimento a carga e o vertimento de fim de semana.
rem Deixe este arquivo na mesma pasta de estima_vertimento_carga.py e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta resultados_uf (onde esta o vergnd_uf_horario.csv) e tecle Enter:
set /p PASTA=Pasta resultados_uf: 
set PASTA=%PASTA:"=%
echo.
echo Cole o caminho da pasta do caso SDDP (onde estao os hrload??.dat) e tecle Enter:
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%

python estima_vertimento_carga.py "%PASTA%" --caso "%CASO%"
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
