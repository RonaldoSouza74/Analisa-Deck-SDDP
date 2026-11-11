@echo off
chcp 65001 > nul
rem Capacidade de exportacao/importacao de cada estado (circuitos de divisa da rede do SDDP).
rem Deixe este arquivo na mesma pasta de limites_uf.py e barras_uf.csv e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com dcirc.dat, dtrans.dat, dcnvlcc.dat...) e tecle Enter:
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Cole o caminho da pasta resultados_uf (onde o limites_uf.csv sera gravado) e tecle Enter:
set /p PASTA=Pasta resultados_uf: 
set PASTA=%PASTA:"=%
echo.
echo Ano da rede a considerar (Enter = 2030):
set /p ANO=Ano: 
if "%ANO%"=="" set ANO=2030

python limites_uf.py "%CASO%" "%~dp0." "%PASTA%" --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
