@echo off
chcp 65001 > nul
rem Exemplo com os dados reais: lista os momentos em que as usinas de um subsistema verteram numa
rem hora do dia e faz as contas que geram os pontos do grafico subsistema_<ID>.png.

cd /d "%~dp0"
echo.
echo Cole o caminho da pasta do caso SDDP (com cmgbus, vergnd e envetu .hdr/.bin) e tecle Enter:
set CASO=
set /p CASO=Pasta do caso: 
set CASO=%CASO:"=%
echo.
echo Subsistema (SE, SU, NE, NO, IT, AR, MA, BM, TP, PA, TA, IV, IM, XI; Enter = NE):
set SUB=
set /p SUB=Subsistema: 
if "%SUB%"=="" set SUB=NE
echo.
echo Hora do dia, de 1 a 24 (1 = 00h-01h; Enter = 22):
set HORA=
set /p HORA=Hora: 
if "%HORA%"=="" set HORA=22
echo.
echo Fonte: R = renovavel, H = hidreletrica (Enter = R):
set FONTE=
set /p FONTE=Fonte: 
set F=ren
if /i "%FONTE%"=="H" set F=hid
echo.
echo Ano (Enter = 2030):
set ANO=
set /p ANO=Ano: 
if "%ANO%"=="" set ANO=2030

python exemplo_cmo.py "%CASO%" --subsistema %SUB% --hora %HORA% --fonte %F% --ano %ANO%
if errorlevel 1 (
    echo.
    echo Algo deu errado. Copie as mensagens acima e envie para analise.
)
echo.
pause
