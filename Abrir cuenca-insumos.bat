@echo off
setlocal
title cuenca-insumos
cd /d "%~dp0"

rem Abre la interfaz de cuenca-insumos con doble clic. La primera vez en una
rem computadora comprueba Python y, si faltan las librerias, ofrece instalarlas.
rem El detalle de cada comprobacion esta en diagnostico.py.

if not exist "%~dp0diagnostico.py" (
    echo.
    echo  Falta el archivo diagnostico.py junto a este .bat.
    echo  Si abriste el .zip descargado de GitHub, primero descomprimelo:
    echo  clic derecho sobre el .zip, "Extraer todo", y abre el .bat de la carpeta extraida.
    echo.
    pause
    exit /b 1
)

rem 1. Buscar un Python que funcione. El "python" de la Microsoft Store que trae
rem    Windows cuando no hay Python instalado no sirve: solo abre la tienda.
set "PY="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    echo.
    echo  No se encontro Python en esta computadora.
    echo.
    echo   1. Descargalo de https://www.python.org/downloads/
    echo      el boton "Download Python 3.x" baja la version de 64 bits, que es la necesaria.
    echo   2. Al instalar, marca la casilla "Add python.exe to PATH".
    echo   3. Cierra esta ventana y vuelve a hacer doble clic en este archivo.
    echo.
    pause
    exit /b 1
)

rem 2. Comprobar Python, Tkinter, librerias y el paquete.
rem    diagnostico.py devuelve 0 = todo bien, 2 = falta instalar, 1 = otro problema.
set "DIAG=0"
%PY% "%~dp0diagnostico.py" --rapido >nul 2>nul
if errorlevel 1 set "DIAG=1"
if errorlevel 2 set "DIAG=2"

if "%DIAG%"=="1" (
    %PY% "%~dp0diagnostico.py" --rapido
    echo.
    echo  Corrige lo marcado como [FALLA] y vuelve a abrir este archivo.
    echo.
    pause
    exit /b 1
)

if "%DIAG%"=="2" (
    echo.
    echo  Primera vez en esta computadora: hay que instalar cuenca-insumos y sus librerias.
    echo  Necesita internet, descarga unos 60 MB y tarda uno o dos minutos.
    echo.
    choice /c SN /m "  Instalar ahora"
    if errorlevel 2 exit /b 1
    echo.
    %PY% -m pip install -e "%~dp0."
    echo.
    %PY% "%~dp0diagnostico.py" --rapido
    if errorlevel 1 (
        echo.
        echo  La instalacion no termino bien. Revisa los mensajes de arriba.
        echo  Si pides ayuda, copia este texto completo.
        echo.
        pause
        exit /b 1
    )
)

rem 3. Abrir la ventana sin dejar una consola abierta detras.
%PY% -m cuenca_insumos ventana --sin-consola
if errorlevel 1 (
    echo.
    echo  No se pudo abrir la ventana. Diagnostico completo:
    %PY% "%~dp0diagnostico.py"
    echo.
    pause
    exit /b 1
)
