#!/bin/bash

export LANG="${LANG:-ru}"
export TYPE_SERVER="${TYPE_SERVER:-dev}"
NAME_PATH_APP="${NAME_PATH_APP}"
PYTHON_VERSION="${PYTHON_VERSION}"


# === Функция локализации ===
msg() {
  key=$1
  [ -z "$key" ] && return
  eval echo "\${LANG_${LANG^^}_$key}"
}

# === Загрузка локализации ===
ENV_LANG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env.lang"
if [ -f "$ENV_LANG_FILE" ]; then
  source "$ENV_LANG_FILE"
fi

# === Проверка обязательных переменных ===
if [ -z "$NAME_PATH_APP" ]; then
  echo "$(msg NAME_PATH_APP_REQUIRED)"
  exit 1
fi





# === Python version аргумент ===
if [ -n "$PYTHON_VERSION" ]; then
  echo "$(msg PYTHON_VERSION_PROVIDED): $PYTHON_VERSION"
  PY_BIN="python$PYTHON_VERSION"
else
  echo "$(msg PYTHON_VERSION_DEFAULT)"
  PY_BIN="python3"
fi

# === Проверка curl ===
if ! command -v curl &> /dev/null; then
  echo "$(msg CURL_INSTALL)"
  sudo apt update && sudo apt install -y curl
fi

# === Установка prod-режима через uv ===
if [[ "$TYPE_SERVER" == "prod" ]]; then
  export PATH="$HOME/.cargo/bin:$PATH"
  # Установка uv
  if command -v uv &> /dev/null; then
    echo "$(msg UV_INSTALLED) $(uv --version)"
  else
    echo "$(msg UV_INSTALL)"
    curl -Ls https://astral.sh/uv/install.sh | sh
  fi

  echo "$(msg PATH_UPDATE)"

  echo "$(msg UV_UPDATE)"
  uv self update || echo "$(msg UV_LATEST)"

  echo "$(msg UV_VENV)"
  if [ -n "$PYTHON_VERSION" ]; then
    uv venv --python="$PYTHON_VERSION"
  else
    uv venv
  fi

  echo "$(msg INSTALLING_PROJECT)"
  uv pip install .

  echo "$(msg UV_VENV_CREATE_PROD)"

# === Установка dev-режима через pip ===
else
  echo "$(msg UV_VENV_CREATE_DEV)"
  echo "$(msg VENV_CREATING)"
  $PY_BIN -m venv .venv

  echo "$(msg ACTIVATE_INSTALL)"
  source .venv/bin/activate

  echo "$(msg INSTALLING_PROJECT)"
  pip install --upgrade pip
  pip install -e '.[dev]'

  echo "$(msg REMOVE_EDITABLE_DEV)"
  find .venv/lib -type f -name "${NAME_PATH_APP}.egg-link" -exec rm -f {} + || true
  find .venv/lib -type d -path "*/site-packages/${NAME_PATH_APP}*" -exec rm -rf {} + || true
fi

# === Финал ===
echo "$(msg ACTIVATE_INSTALL)"
echo "$(msg UV_VERSION) $(python --version)"

echo ""
echo "$(msg SETUP_DONE)"
echo ""
echo "$(msg IDE_HEADER)"
echo ""
echo -e "$(msg PYCHARM)"
echo ""
echo -e "$(msg VSCODE)"
echo ""
echo -e "$(msg TERMINAL)"
