@echo off
chcp 65001 > nul
rem Vertimento por gargalo de transmissao x excesso no sistema, pelo custo marginal por barra (cmgbus).
rem Deixe este arquivo na mesma pasta de gargalo_cmo.py, das tabelas .csv e dos demais scripts e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com cmgbus, vergnd, envetu, cmgsuc, cmglnk .hdr/.bin
echo e os arquivos chidro??.dat e hydrounit??.dat do deck) e tecle Enter:
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Ano a analisar (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if not "%ANO%"=="" for /f "tokens=1 delims=-,; " %%a in ("%ANO%") do set ANO=%%a
if "%ANO%"=="" set ANO=2030

python gargalo_cmo.py "%CASO%" --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
