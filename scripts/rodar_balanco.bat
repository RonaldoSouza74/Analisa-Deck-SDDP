@echo off
chcp 65001 > nul
rem Balanco por estado nas horas de vertimento: renovavel + hidro + termica - carga = injecao.
rem Precisa das etapas 1 (agregacao) e 6 (gargalo_cmo) ja rodadas para o mesmo caso.
rem Deixe este arquivo na mesma pasta dos scripts .py e das tabelas .csv e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com gerhid, gerter e demxba .hdr/.bin e os arquivos
echo chidro??, ctermi??, hydrounit?? e thermunit??.dat do deck) e tecle Enter:
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Ano a analisar (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if not "%ANO%"=="" for /f "tokens=1 delims=-,; " %%a in ("%ANO%") do set ANO=%%a
if "%ANO%"=="" set ANO=2030

python balanco_uf.py "%CASO%" --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
