@echo off
chcp 65001 > nul
rem Agrega por UF as saidas do SDDP (gergnd, vergnd, businj, bus_losses).
rem Deixe este arquivo na mesma pasta de agrega_saidas_uf.py, barras_uf.csv
rem e usinas_renovaveis_uf.csv e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta onde estao os arquivos .hdr e .bin do SDDP
echo (ex.: C:\Estudo Curtailment SDDP\estudo_perdas_2025) e tecle Enter:
set /p CASO=Pasta:
set CASO=%CASO:"=%

python agrega_saidas_uf.py "%CASO%"
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
