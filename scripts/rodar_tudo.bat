@echo off
chcp 65001 > nul
rem Roda todas as etapas em sequencia:
rem   1) agrega as saidas do SDDP (.hdr/.bin) por estado
rem   2) calcula os limites de exportacao/importacao de cada estado
rem   3) gera os graficos por estado (box plots, mapas de calor, ranking...)
rem   4) gera a analise de dias uteis x fins de semana
rem   5) identifica as barras com e sem margem de escoamento
rem   6) separa o vertimento por gargalo de transmissao x excesso no sistema (custo marginal)
rem   7) aponta as linhas e transformadores no limite (fluxos) e faz os graficos horarios por estado
rem   8) relacao: vertimento x injecao x CMO x fluxo e limite fisico das linhas
rem   9) balanco por estado nas horas de vertimento (renovavel + hidro + termica - carga)
rem Deixe este arquivo na mesma pasta dos scripts .py e das tabelas .csv e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com os .hdr/.bin das saidas e os hrload??.dat)
echo e tecle Enter:
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
set RES=%CASO%\resultados_uf

echo.
echo Estagios para os graficos por estado: digite so os DOIS numeros separados por espaco.
echo   Exemplo: 2 13   (estagios 2 a 13 = jan a dez de 2030).  Enter = todos os estagios.
set EST=
set E1=
set E2=
set /p EST=Estagios: 
if not "%EST%"=="" for /f "tokens=1,2 delims=-,; " %%a in ("%EST%") do (
    set E1=%%a
    set E2=%%b
)
set EST=
if defined E2 set EST=%E1% %E2%

echo.
echo Ano para os limites, dias uteis x fim de semana e margem das barras (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if not "%ANO%"=="" for /f "tokens=1 delims=-,; " %%a in ("%ANO%") do set ANO=%%a
if "%ANO%"=="" set ANO=2030

echo.
echo A etapa 1 (agregacao dos .bin) ja foi feita para este caso?
echo   Digite S para pular a etapa 1, ou so Enter para rodar tudo:
set PULAR=
set /p PULAR=Pular etapa 1 (S/Enter): 

echo.
echo Pasta do caso: %CASO%
if defined EST (echo Estagios: %EST%) else (echo Estagios: todos)
echo Ano: %ANO%

if /i not "%PULAR%"=="S" goto etapa1
rem so pula a etapa 1 se os resultados dela estiverem mesmo na pasta resultados_uf
if exist "%RES%\vergnd_uf_horario.csv" goto etapa2
echo.
echo AVISO: voce pediu para pular a etapa 1, mas nao achei os resultados dela em
echo   %RES%
echo   (vergnd_uf_horario.csv, gergnd_uf_horario.csv, businj_uf_horario.csv).
echo   A etapa 1 sera feita agora.
:etapa1
echo.
echo ===== [1/9] Agregando as saidas do SDDP por estado =====
python agrega_saidas_uf.py "%CASO%"
if errorlevel 1 goto erro

:etapa2
echo.
echo ===== [2/9] Limites de exportacao/importacao por estado =====
python limites_uf.py "%CASO%" "%~dp0." "%RES%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [3/9] Graficos por estado =====
if not defined EST goto sem_estagios
python graficos_uf.py "%RES%" --estagios %EST%
goto depois_graficos
:sem_estagios
python graficos_uf.py "%RES%"
:depois_graficos
if errorlevel 1 goto erro

echo.
echo ===== [4/9] Dias uteis x fins de semana =====
python analise_semana_carga.py "%RES%" --caso "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [5/9] Margem de escoamento das barras =====
python margem_barras.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [6/9] Vertimento por gargalo x excesso no sistema (custo marginal) =====
python gargalo_cmo.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [7/9] Linhas e transformadores no limite (fluxos) e graficos horarios por estado =====
python gargalo_linhas.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [8/9] Relacao: vertimento x injecao x CMO x fluxo e limite fisico das linhas =====
python relacao_gargalo.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [9/9] Balanco por estado nas horas de vertimento =====
python balanco_uf.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo Concluido. Resultados em: %RES%
echo   graficos\          graficos por estado, mapas de calor, ranking
echo   analise_semana\    dias uteis x fins de semana, correlacoes
echo   margem_barras\     barras com e sem margem de escoamento
echo   gargalo_cmo\       vertimento por gargalo de transmissao x excesso no sistema
echo   gargalo_linhas\    linhas no limite e graficos horarios por estado
echo   relacao_gargalo\   vertimento x injecao x CMO x linhas no limite, por situacao da hora
echo   balanco_uf\        balanco por estado nas horas de vertimento
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
