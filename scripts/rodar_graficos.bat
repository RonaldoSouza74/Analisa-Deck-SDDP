@echo off
chcp 65001 > nul
rem Gera os graficos por estado a partir da pasta resultados_uf.
rem Deixe este arquivo na mesma pasta de graficos_uf.py e de dois cliques nele.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta resultados_uf (onde estao os *_uf_horario.csv) e tecle Enter:
set PASTA=
set /p PASTA=Pasta: 
set PASTA=%PASTA:"=%
echo.
echo Estagios: digite so os DOIS numeros separados por espaco.
echo   Exemplo: 2 13   (estagios 2 a 13 = jan a dez de 2030).  Enter = todos os estagios.
set EST=
set E1=
set E2=
set /p EST=Estagios: 
if not "%EST%"=="" for /f "tokens=1,2 delims=-,; " %%a in ("%EST%") do (
    set E1=%%a
    set E2=%%b
)

if defined E2 goto com_estagios
python graficos_uf.py "%PASTA%"
goto fim
:com_estagios
python graficos_uf.py "%PASTA%" --estagios %E1% %E2%
:fim
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
