@echo off
setlocal enabledelayedexpansion

if "%TYPE_SERVER%"=="" set "TYPE_SERVER=dev"
if "%LANG%"=="" set "LANG=ru"



REM === Локализация из .env.lang ===
if not exist "../.env.lang" (
    echo Missing .env.lang
    exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%A in ("../.env.lang") do (
    set "%%A=%%B"
)

REM === Функция msg ===
:msg
REM Проверка: если ключ не передан — ничего не выводим
if "%~1"=="" (
    echo [msg error] Empty key
    goto :eof
)

set "key=LANG_!LANG!_%~1"
call set "value=%%%key%%%"
if not defined value (
    echo [missing] !key!
) else (
    echo !value!
)
goto :eof

REM === Обязательная переменная NAME_PATH_APP ===
if "%NAME_PATH_APP%"=="" (
    call :msg NAME_PATH_APP_REQUIRED
    exit /b 1
)

call :msg INSTALL_OS

REM === Проверка curl ===
where curl >nul 2>nul
if errorlevel 1 (
    call :msg CURL_MISSING
    exit /b 1
)

REM === Если prod — работаем через uv ===
if /i "%TYPE_SERVER%"=="prod" (

    REM === Проверка uv ===
    where uv >nul 2>nul
    if errorlevel 1 (
        call :msg UV_INSTALL
        curl -Ls https://astral.sh/uv/install.sh | sh
    ) else (
        call :msg UV_INSTALLED
        uv --version
    )

    call :msg UV_UPDATE
    uv self update || call :msg UV_LATEST

    call :msg PATH_UPDATE
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

    call :msg UV_VENV
    if not "%PYTHON_VERSION%"=="" (
        call :msg PYTHON_VERSION_PROVIDED
        echo Python version: %PYTHON_VERSION%
        uv venv --python=%PYTHON_VERSION%
    ) else (
        call :msg PYTHON_VERSION_DEFAULT
        uv venv
    )

    call :msg UV_VENV_CREATE_PROD
    call :msg INSTALLING_PROJECT
    uv pip install .

) else (
    REM === dev-режим через python + pip ===

    call :msg UV_VENV_CREATE_DEV
    call :msg VENV_CREATING
    if not "%PYTHON_VERSION%"=="" (
        echo Creating virtualenv using: python%PYTHON_VERSION%
        python%PYTHON_VERSION% -m venv .venv
    ) else (
        python -m venv .venv
    )

    call :msg ACTIVATE_INSTALL
    call :msg INSTALLING_PROJECT

    .venv\Scripts\pip.exe install --upgrade pip
    .venv\Scripts\pip.exe install -e .[dev]

    call :msg REMOVE_EDITABLE_DEV

    REM Удаляем %NAME_PATH_APP% из site-packages вручную
    for /d %%D in (.venv\Lib\site-packages\%NAME_PATH_APP%*) do (
        rd /s /q "%%D"
    )
    if exist .venv\Lib\site-packages\%NAME_PATH_APP%.egg-link (
        del /q .venv\Lib\site-packages\%NAME_PATH_APP%.egg-link
    )
)

call :msg ACTIVATE_INSTALL
call :msg UV_VERSION
python --version



echo.
call :msg SETUP_DONE
echo.
call :msg IDE_HEADER
echo.
echo !LANG_%LANG%_PYCHARM!
echo.
echo !LANG_%LANG%_VSC
echo.
echo !LANG_%LANG%_TERMINAL!


