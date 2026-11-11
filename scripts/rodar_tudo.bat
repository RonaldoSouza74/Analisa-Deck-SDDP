@echo off
chcp 65001 > nul
rem Roda todas as etapas em sequencia:
rem   1) agrega as saidas do SDDP (.hdr/.bin) por estado
rem   2) calcula os limites de exportacao/importacao de cada estado
rem   3) gera os graficos por estado (box plots, mapas de calor, ranking...)
rem   4) gera a analise de dias uteis x fins de semana
rem   5) identifica as barras com e sem margem de escoamento
rem Deixe este arquivo na mesma pasta dos scripts .py e das tabelas .csv e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com os .hdr/.bin das saidas e os hrload??.dat)
echo e tecle Enter:
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Estagios para os graficos por estado (ex.: 2 13 para o ano de 2030). Enter = todos:
set /p EST=Estagios: 
echo.
echo Ano para os limites e para a analise de dias uteis x fim de semana (Enter = 2030):
set /p ANO=Ano: 
if "%ANO%"=="" set ANO=2030
set RES=%CASO%\resultados_uf

echo.
echo ===== [1/5] Agregando as saidas do SDDP por estado =====
python agrega_saidas_uf.py "%CASO%"
if errorlevel 1 goto erro

echo.
echo ===== [2/5] Limites de exportacao/importacao por estado =====
python limites_uf.py "%CASO%" "%~dp0." "%RES%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [3/5] Graficos por estado =====
if "%EST%"=="" goto sem_estagios
python graficos_uf.py "%RES%" --estagios %EST%
goto depois_graficos
:sem_estagios
python graficos_uf.py "%RES%"
:depois_graficos
if errorlevel 1 goto erro

echo.
echo ===== [4/5] Dias uteis x fins de semana =====
python analise_semana_carga.py "%RES%" --caso "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [5/5] Margem de escoamento das barras =====
python margem_barras.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo Concluido. Resultados em: %RES%
echo   graficos\          graficos por estado, mapas de calor, ranking
echo   analise_semana\    dias uteis x fins de semana, correlacoes
echo   margem_barras\     barras com e sem margem de escoamento
echo   limites_uf.csv     capacidade de exportacao/importacao por estado
echo.
pause
exit /b 0

:erro
echo.
echo Algo deu errado. Copie as mensagens acima e envie para analise.
echo.
pause
exit /b 1
