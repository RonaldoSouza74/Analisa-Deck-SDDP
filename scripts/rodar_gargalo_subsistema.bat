@echo off
chcp 65001 > nul
rem Vertimento por gargalo ENTRE SUBSISTEMAS x excesso no sistema, pelo CMO dos 14 subsistemas
rem (mediana das barras de cada subsistema x mediana do SIN) e intercambio nos circuitos de fronteira (interc).
rem Deixe este arquivo na mesma pasta de gargalo_subsistema.py, das tabelas .csv e dos demais scripts e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com cmgbus, vergnd, envetu, interc .hdr/.bin
echo e os arquivos sistem.dat, interc.dat, dcirc.dat, dtrans.dat, ddcline.dat... do deck) e tecle Enter:
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Ano a analisar (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if not "%ANO%"=="" for /f "tokens=1 delims=-,; " %%a in ("%ANO%") do set ANO=%%a
if "%ANO%"=="" set ANO=2030

python gargalo_subsistema.py "%CASO%" --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
