@echo off
chcp 65001 > nul
rem Gargalos de transmissao em duas etapas:
rem   1) pelo custo marginal (gargalo_cmo.py): separa o vertimento em gargalo x excesso no sistema
rem   2) pelos fluxos (gargalo_linhas.py): aponta quais linhas e transformadores ficam no limite
rem Deixe este arquivo na mesma pasta dos scripts .py e das tabelas .csv e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP e tecle Enter.
echo   Precisa ter: cmgbus, vergnd, acline_flow, transformer_flow (.hdr/.bin) e, se houver,
echo   envetu, cmgsuc, cmglnk; e do deck: dcirc, mcirc, circstatus_b004m, dtrans, mtrans,
echo   transtatus_b004m, chidro??.dat, hydrounit??.dat
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Ano a analisar (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if not "%ANO%"=="" for /f "tokens=1 delims=-,; " %%a in ("%ANO%") do set ANO=%%a
if "%ANO%"=="" set ANO=2030

echo.
echo ===== [1/2] Vertimento por gargalo x excesso no sistema (custo marginal) =====
python gargalo_cmo.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo ===== [2/2] Linhas e transformadores no limite (fluxos) =====
python gargalo_linhas.py "%CASO%" --ano %ANO%
if errorlevel 1 goto erro

echo.
echo Concluido. Resultados em: %CASO%\resultados_uf\gargalo_cmo e %CASO%\resultados_uf\gargalo_linhas
echo.
pause
exit /b 0

:erro
echo.
echo Algo deu errado. Copie as mensagens acima e envie para analise.
echo.
pause
exit /b 1
