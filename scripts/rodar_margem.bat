@echo off
chcp 65001 > nul
rem Margem de escoamento por barra: injecao do SDDP (businj) x capacidade dos circuitos monitorados.
rem Deixe este arquivo na mesma pasta de margem_barras.py, barras_uf.csv e dos demais scripts e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com businj.hdr/.bin e os arquivos de rede do deck) e tecle Enter:
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Ano a analisar (Enter = 2030):
set /p ANO=Ano: 
if "%ANO%"=="" set ANO=2030

python margem_barras.py "%CASO%" --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
