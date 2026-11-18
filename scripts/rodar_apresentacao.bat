@echo off
chcp 65001 > nul
rem Monta a apresentacao (PowerPoint) com os graficos e numeros de resultados_uf.
rem Rode depois do rodar_tudo.bat. Deixe este arquivo na mesma pasta dos scripts .py e do mapa_uf.json.

cd /d "%~dp0"
python -c "import pptx" 2> nul
if errorlevel 1 (
    echo Instalando o pacote python-pptx ^(so na primeira vez^)...
    python -m pip install python-pptx
)
echo.
echo Cole o caminho da pasta do caso SDDP (a que tem a pasta resultados_uf dentro) e tecle Enter:
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Ano (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if not "%ANO%"=="" for /f "tokens=1 delims=-,; " %%a in ("%ANO%") do set ANO=%%a
if "%ANO%"=="" set ANO=2030

python apresentacao.py "%CASO%" --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
) else (
    echo.
    echo A apresentacao esta em  %CASO%\resultados_uf\apresentacao
)
echo.
pause
