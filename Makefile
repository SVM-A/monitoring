.PHONY: \
  help setup install i run test lint format migrate makemigrations \
  docker-up docker-down docker-app-up docker-app-down add-docker-network docker-pstgr-up\
  docker-infrastructure-up docker-infrastructure-down docker-help docker-pstgr-down\
  clean clean-all lock sync check lang shell add doctor install-ssh env-pull \
  migrate-up migrate-down migrate-history migrate-help ssh-dev ssh-prod \
  dev prod user catalog

.DEFAULT_GOAL := help
SHELL := /bin/bash -O extglob -O nullglob

ifeq ($(wildcard .env),.env)
	include .env
endif

TYPE_SERVER ?= dev
TYPE_NETWORK ?= local
DOCKER_NETWORK ?= svm-a-network

ifeq ($(TYPE_SERVER),prod)
	TYPE_SERVER := prod
else ifeq ($(TYPE_SERVER),test)
	TYPE_SERVER := test
else
	TYPE_SERVER := dev
endif

ifeq ($(TYPE_NETWORK),server)
	TYPE_NETWORK := server
else
	TYPE_NETWORK := local
endif




TYPE_SERVICE=back
REPO_NAME=monitoring
APP_NAME=monitoring
REPO_AUTHOR=SVM-A
REPO_ENV_ACTION=/actions/workflows/export-env.yml
ZIP_FILE=env.zip
ENV_TMP_DIR=.env_downloaded
ENV_FILE=.env
SSH_SCRIPT_BASE := svm-a-auto-ssh
SSH_SCRIPT_SH := $(SSH_SCRIPT_BASE)-linux.sh
SSH_SCRIPT_CMD := $(SSH_SCRIPT_BASE)-run-windows.cmd
SERVER_IP_DEV=$(DEV_SERVER_IP)
SERVER_PORT_DEV=$(DEV_SERVER_PORT)
SERVER_IP_PROD=$(PROD_SERVER_IP)
SERVER_PORT_PROD=$(PROD_SERVER_PORT)
NAME_PATH_APP=svm-a-$(APP_NAME)
PYTHON_VERSION=3.12

ESC := \033
BOLD := $(ESC)[1m
RESET := $(ESC)[0m
YELLOW := $(ESC)[0;33m


UNAME := $(shell uname)
ifeq ($(OS),Windows_NT)
  VENV_ACTIVATE := .venv\Scripts\activate
else ifeq ($(UNAME),Linux)
  VENV_ACTIVATE := . .venv/bin/activate
else ifeq ($(UNAME),Darwin)
  VENV_ACTIVATE := . .venv/bin/activate
else
  VENV_ACTIVATE := . .venv/bin/activate
endif

-include .env.lang

LANG ?= $(shell echo $$LANG | sed 's/\..*//' | cut -d_ -f1)
LANG := $(shell echo $(LANG) | sed 's/_.*//')


SUPPORTED_LANGS := ru en

ifeq ($(filter $(LANG),$(SUPPORTED_LANGS)),)
  $(error Unsupported language "$(LANG)". Supported: $(SUPPORTED_LANGS))
endif

define MSG
$(strip $(or $(LANG_$(shell echo $(LANG) | tr a-z A-Z)_$(1)),$(LANG_RU_$(1)),"[MSG:$1]"))
endef

# 🖍️ Цвета терминала (если доступны)
ifeq ($(NO_COLOR),true)
	RED :=
	GREEN :=
	GREY :=
	YELLOW :=
	BLUE :=
	CYAN :=
	BOLD :=
	RESET :=
else
	RED := $(shell tput setaf 1)
	GREEN := $(shell tput setaf 2)
	GREY := $(shell tput setaf 8)
	YELLOW := $(shell tput setaf 3)
	BLUE := $(shell tput setaf 4)
	CYAN := $(shell tput setaf 6)
	BOLD := $(shell tput bold)
	RESET := $(shell tput sgr0)
endif

lang-init:
	@echo "LANG=$(LANG)" > .env.lang

debug-env:
	@echo "BASE_WIDGET_URL = $(BASE_WIDGET_URL)"

install:
	@echo ""
	@if [ "$(TYPE_SERVER)" = "prod" ]; then \
		echo "$(BOLD)$(call MSG,INSTALLING_PROD)$(RESET)"; \
	else \
		echo "$(BOLD)$(call MSG,INSTALLING_DEV)$(RESET)"; \
	fi
	@echo "$(YELLOW)$(call MSG,INSTALL_OS)$(RESET)"
	@if [ "$$(uname)" = "Linux" ] || [ "$$(uname)" = "Darwin" ]; then \
		echo "$(call MSG,OS_LINUX)$(RESET)"; \
		chmod +x make-scripts/setup.sh && \
		TYPE_SERVER=$(TYPE_SERVER) NAME_PATH_APP=$(NAME_PATH_APP) PYTHON_VERSION=$(PYTHON_VERSION) LANG=$(LANG) make-scripts/setup.sh; \
	elif [ "$$OS" = "Windows_NT" ]; then \
		if [ -f make-scripts/setup.cmd ]; then \
			echo "$(call MSG,OS_WIN)"; \
			set TYPE_SERVER=$(TYPE_SERVER) && set NAME_PATH_APP=$(NAME_PATH_APP) && set PYTHON_VERSION=$(PYTHON_VERSION) && set LANG=$(LANG) && cmd /C make-scripts\\setup.cmd; \
		else \
			echo "$(call MSG,SCRIPT_NOT_FOUND)"; \
			exit 1; \
		fi; \
	else \
		echo "$(call MSG,OS_NOT_SUPPORTED)"; \
		exit 1; \
	fi

	@if [ "$(TYPE_SERVER)" = "dev" ]; then \
		echo "$(YELLOW)$(call MSG,SKIP_INSTALL_DEV)$(RESET)"; \
		$(MAKE) clean; \
		while true; do \
			echo -n "$(YELLOW)$(call MSG,ENV_PULL_OFFER) [y/N/q]: "; \
			read -r pull_answer; \
			pull_answer_l=$$(echo "$$pull_answer" | tr '[:upper:]' '[:lower:]'); \
			if [ "$$pull_answer_l" = "y" ]; then \
				$(MAKE) env-pull; \
				break; \
			elif [ "$$pull_answer_l" = "n" ] || [ -z "$$pull_answer_l" ]; then \
				echo "$(YELLOW)$(call MSG,ENV_PULL_SKIPPED)$(RESET)"; \
				break; \
			elif [ "$$pull_answer_l" = "q" ]; then \
				echo "$(YELLOW)$(call MSG,ENV_ABORTED)$(RESET)"; \
				break; \
			else \
				echo "$(RED)$(call MSG,ENV_INVALID_CHOICE)$(RESET)"; \
			fi; \
		done; \
	fi

i: install

env-pull:
	@MODE_ARG="$$(for g in $(MAKECMDGOALS); do \
		if [ "$$g" = "dev" ] || [ "$$g" = "prod" ]; then echo "$$g"; fi; \
	done)"; \
	if [ -z "$$MODE_ARG" ]; then MODE_ARG="dev"; fi; \
	if [ "$$MODE_ARG" != "dev" ] && [ "$$MODE_ARG" != "prod" ]; then \
		echo "$(RED)✖ $(call MSG,CONN_INVALID_MODE): '$$MODE_ARG'$(RESET)"; exit 1; \
	fi; \
	echo "$(CYAN)$(call MSG,ENV_PULL_START)$(RESET)"; \
	echo "$(YELLOW)$(call MSG,ENV_RUN_WORKFLOW_REMINDER)$(RESET)"; \
	@token=""; \
	make_token=""; \
	if [ -f $(ENV_FILE) ]; then \
		echo "$(CYAN)$(call MSG,ENV_HELP_TRY_MAKE_TOKEN)$(RESET)"; \
		echo "$(CYAN)$(call MSG,ENV_TRY_MAKE_TOKEN)$(RESET)"; \
		make_token=$$(grep -E '^MAKE_TOKEN=' $(ENV_FILE) | cut -d '=' -f2-); \
		if [ -n "$$make_token" ]; then \
			echo "$(YELLOW)$(call MSG,ENV_FOUND_MAKE_TOKEN)$(RESET)"; \
			status=$$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: token $$make_token" https://api.github.com/repos/$(REPO_AUTHOR)/$(REPO_NAME)/actions/artifacts); \
			if [ "$$status" = "200" ]; then \
				token="$$make_token"; \
				echo "$(GREEN)$(call MSG,ENV_MAKE_TOKEN_VALID)$(RESET)"; \
			else \
				echo "$(RED)$(call MSG,ENV_MAKE_TOKEN_INVALID)$(RESET)"; \
			fi; \
		else \
			echo "$(YELLOW)$(call MSG,ENV_MAKE_TOKEN_NOT_FOUND)$(RESET)"; \
			echo "$(YELLOW)$(call MSG,ENV_HELP_ADD_MAKE_TOKEN)$(RESET)"; \
			echo -n "$(call MSG,ENV_ENTER_TOKEN) "; \
		fi; \
	else \
		echo "$(RED)$(call MSG,ENV_HELP_NO_ENV)$(RESET)"; \
		echo "$(YELLOW)$(call MSG,ENV_TOKEN_HINT)$(RESET)"; \
		echo -n "$(call MSG,ENV_ENTER_TOKEN) "; \
	fi; \
	while [ -z "$$token" ]; do \
		if [ -n "$$GITHUB_TOKEN" ]; then \
			token="$$GITHUB_TOKEN"; \
		else \
			read -r input_token; \
			input_token_l=$$(echo "$$input_token" | tr '[:upper:]' '[:lower:]'); \
			if [ "$$input_token_l" = "q" ]; then \
				echo "$(YELLOW)$(call MSG,ENV_ABORTED)$(RESET)"; exit 0; \
			elif [ -n "$$input_token" ]; then \
				token="$$input_token"; \
				while true; do \
					echo -n "$(YELLOW)$(call MSG,ENV_SAVE_TOKEN_QUESTION) [y/N/q]: "; \
					read -r save_answer; \
					save_answer_l=$$(echo "$$save_answer" | tr '[:upper:]' '[:lower:]'); \
					if [ "$$save_answer_l" = "y" ]; then \
						echo "MAKE_TOKEN=$$token" >> $(ENV_FILE); \
						echo "$(GREEN)$(call MSG,ENV_TOKEN_SAVED)$(RESET)"; \
						break; \
					elif [ "$$save_answer_l" = "n" ] || [ -z "$$save_answer_l" ]; then \
						echo "$(YELLOW)$(call MSG,ENV_TOKEN_NOT_SAVED)$(RESET)"; \
						break; \
					elif [ "$$save_answer_l" = "q" ]; then \
						echo "$(YELLOW)$(call MSG,ENV_ABORTED)$(RESET)"; exit 0; \
					else \
						echo "$(RED)$(call MSG,ENV_INVALID_CHOICE)$(RESET)"; \
					fi; \
				done; \
			else \
				echo "$(RED)$(call MSG,ENV_INVALID_TOKEN)$(RESET)"; \
				echo -n "$(call MSG,ENV_ENTER_TOKEN) "; \
			fi; \
		fi; \
	done; \
	echo "$(call MSG,ENV_PULL_FETCHING)"; \
	response=$$(curl -s -H "Authorization: token $$token" https://api.github.com/repos/$(REPO_AUTHOR)/$(REPO_NAME)/actions/artifacts); \
	echo "$$response" | jq . > /dev/null 2>&1 || { \
	  echo "$(RED)$(call MSG,ENV_INVALID_RESPONSE)$(RESET)"; \
	  token=""; \
	  echo -n "$(call MSG,ENV_ENTER_TOKEN) "; \
	  continue; \
	}; \
	artifact_name="env-local-$(TYPE_SERVICE)-$(APP_NAME)-$$MODE_ARG"; \
	echo "$(CYAN)🔎 $(call MSG,ENV_LOOKING_FOR_ARTIFACT): $$artifact_name$(RESET)"; \
	artifact_url=$$(echo "$$response" \
	  | jq -r ".artifacts[] | select(.name==\"$$artifact_name\") | .archive_download_url" \
	  | head -n 1); \
	if [ -z "$$artifact_url" ]; then \
		echo "$(RED)$(call MSG,ENV_NO_ARTIFACT)$(RESET)"; \
		exit 1; \
	fi; \
	if [ -f $(ENV_FILE) ]; then \
		while true; do \
			echo "$(YELLOW)$(call MSG,ENV_EXISTS)$(RESET)"; \
			echo -n "$(call MSG,ENV_OVERWRITE_CONFIRM) [y/N/q]: "; \
			read -r answer; \
			answer_l=$$(echo "$$answer" | tr '[:upper:]' '[:lower:]'); \
			if [ "$$answer_l" = "y" ]; then \
				break; \
			elif [ "$$answer_l" = "q" ]; then \
				echo "$(YELLOW)$(call MSG,ENV_ABORTED)$(RESET)"; exit 0; \
			elif [ "$$answer_l" = "n" ] || [ -z "$$answer_l" ]; then \
				echo "$(YELLOW)$(call MSG,ENV_SKIPPED)$(RESET)"; exit 0; \
			else \
				echo "$(RED)$(call MSG,ENV_INVALID_CHOICE)$(RESET)"; \
			fi; \
		done; \
	fi; \
	echo "$(CYAN)$(call MSG,ENV_DOWNLOADING)$(RESET)"; \
	make_token_line=$$(grep -E '^MAKE_TOKEN=' $(ENV_FILE) || true); \
	dev_ssh_conf=$$(grep -E '^DEV_SSH_CONF=' $(ENV_FILE) || true); \
	prod_ssh_conf=$$(grep -E '^PROD_SSH_CONF=' $(ENV_FILE) || true); \
	curl -sL -H "Authorization: token $$token" "$$artifact_url" -o $(ZIP_FILE); \
	unzip -o $(ZIP_FILE) $(ENV_FILE) -d $(ENV_TMP_DIR) > /dev/null; \
	mv $(ENV_TMP_DIR)/$(ENV_FILE) $(ENV_FILE); rm -rf $(ENV_TMP_DIR) $(ZIP_FILE); \
	if [ -n "$$make_token_line" ]; then \
		echo "$$make_token_line" >> $(ENV_FILE); \
	fi; \
	if [ -n "$$dev_ssh_conf" ]; then \
		echo "$$dev_ssh_conf" >> $(ENV_FILE); \
	fi; \
	if [ -n "$$prod_ssh_conf" ]; then \
		echo "$$prod_ssh_conf" >> $(ENV_FILE); \
	fi; \
	echo "$(GREEN)$(call MSG,ENV_PULL_DONE)$(RESET)"

run:
	@echo ""
	@echo "$(BOLD)$(CYAN)🚀 $(call MSG,RUN_START)$(RESET)"
	@echo "$(YELLOW)🔧 $(call MSG,RUN_MODE): $(TYPE_SERVER)$(RESET)"
	@echo "$(GREEN)🌐 $(call MSG,RUN_URL): http://localhost:8001$(RESET)"

ifeq ($(TYPE_SERVER),prod)
	@which gunicorn > /dev/null || { echo "$(RED)✘ gunicorn $(call MSG,NOT_INSTALLED)$(RESET)"; exit 1; }
	$(VENV_ACTIVATE) && gunicorn run:app -c gunicorn.conf.py
else
	@which uvicorn > /dev/null || { echo "$(RED)✘ uvicorn $(call MSG,NOT_INSTALLED)$(RESET)"; exit 1; }

	@echo "$(CYAN)ℹ️  $(call MSG,RUN_AVAILABLE_ENDPOINTS):$(RESET)"
	@echo "   → http://localhost:55666/"
	@echo "   → http://localhost:55666/api/docs"

	@trap 'echo "\n$(RED)✖ $(call MSG,RUN_INTERRUPTED)$(RESET)"; exit 0' INT; \
	$(VENV_ACTIVATE) && uvicorn run:app --host 0.0.0.0 --port 55666
endif

add:
	@MODE_ARG="$$(for g in $(MAKECMDGOALS); do \
		if [ "$$g" = "dev" ] || [ "$$g" = "prod" ]; then echo "$$g"; fi; \
	done)"; \
	if [ -z "$$MODE_ARG" ]; then MODE_ARG="dev"; fi; \
	if [ "$$MODE_ARG" != "dev" ] && [ "$$MODE_ARG" != "prod" ]; then \
		echo "$(RED)✖ $(call MSG,CONN_INVALID_MODE): '$$MODE_ARG'$(RESET)"; exit 1; \
	fi; \
	echo "$(YELLOW)$(call MSG,ADD_PACKAGE): $$MODE_ARG$(RESET)"; \
	trap 'echo "\n$(RED)$(call MSG,INSTALL_CANCELLED)$(RESET)"; exit 0' INT; \
	while true; do \
		printf "%s " "$(call MSG,ENTER_PACKAGE_NAME)"; \
		read -r packages; \
		if [ -z "$$packages" ]; then \
			echo "$(RED)$(call MSG,EMPTY_PACKAGE)$(RESET)"; \
			continue; \
		fi; \
		for package in $$packages; do \
			echo "$(YELLOW)$(call MSG,TRY_INSTALL) $$package$(RESET)"; \
			if [ "$$MODE_ARG" = "prod" ]; then \
				if uv add "$$package" > /dev/null 2>&1; then \
					version=$$(uv pip freeze | grep "^$$package==" | cut -d= -f3); \
					echo "$(GREEN)✔ $(call MSG,PACKAGE_ADDED): $$package >= $$version$(RESET)"; \
				else \
					echo "$(RED)$(call MSG,PACKAGE_NOT_FOUND): $$package$(RESET)"; \
				fi; \
			else \
				if pip install "$$package" > /dev/null 2>&1; then \
					version=$$(pip show "$$package" | grep -i version | awk '{print $$2}'); \
					echo "$(GREEN)✔ $(call MSG,PACKAGE_ADDED): $$package >= $$version$(RESET)"; \
					# Проверяем наличие tomlkit, если нет — ставим и добавляем в pyproject.toml \
					if ! python -c "import tomlkit" 2>/dev/null; then \
						echo "$(YELLOW)$(call MSG,TRY_INSTALL) tomlkit$(RESET)"; \
						pip install tomlkit; \
						tkver=$$(pip show tomlkit | grep -i version | awk '{print $$2}'); \
						echo "$(GREEN)✔ $(call MSG,PACKAGE_ADDED): tomlkit >= $$tkver$(RESET)"; \
						python scripts/add_dep.py tomlkit "$$tkver"; \
					fi; \
					python scripts/add_dep.py "$$package" "$$version"; \
				else \
					echo "$(RED)$(call MSG,PACKAGE_NOT_FOUND): $$package$(RESET)"; \
				fi; \
			fi; \
		done; \
		break; \
	done


shell:
	@if [ ! -d ".venv" ]; then \
		echo "$(RED)⚠️  $(call MSG,VENV_NOT_FOUND)$(RESET)"; \
		echo "$(YELLOW)> $(call MSG,RUN_INSTALL_INSTRUCTION)$(RESET)"; \
		exit 1; \
	fi; \
	echo "$(call MSG,SHELL)"; \
	$(VENV_ACTIVATE) && exec bash

check:
	@echo "$(CYAN)🔍 $(call MSG,CHECK_START)$(RESET)"

	@# Проверка .venv
	@if [ -d .venv ]; then \
		echo "$(GREEN)✔ $(call MSG,CHECK_VENV_FOUND)$(RESET)"; \
	else \
		echo "$(RED)✖ $(call MSG,CHECK_VENV_MISSING)$(RESET)"; \
	fi

	@# Проверка uv.lock (только в prod)
	@if [ "$(TYPE_SERVER)" = "prod" ]; then \
		if [ -f uv.lock ]; then \
			echo "$(GREEN)✔ $(call MSG,CHECK_LOCK_FOUND)$(RESET)"; \
		else \
			echo "$(RED)✖ $(call MSG,CHECK_LOCK_MISSING)$(RESET)"; \
		fi; \
	else \
		echo "$(GREY)• $(call MSG,CHECK_LOCK_IGNORED)$(RESET)"; \
	fi

doctor:
	@echo "$(CYAN)$(call MSG,DOCTOR_HEADER)$(RESET)"
	@echo "$(YELLOW)$(call MSG,DOCTOR_HINT)$(RESET)"
	@echo ""
	@for cmd in curl jq unzip git docker python3; do \
		if command -v $$cmd >/dev/null 2>&1; then \
			echo "$(GREEN)$(call MSG,DOCTOR_FOUND)$$cmd$(RESET)"; \
		else \
			echo "$(RED)$(call MSG,DOCTOR_MISSING)$$cmd$(RESET)"; \
		fi; \
	done

test:
	@echo "$(CYAN)$(call MSG,TEST)$(RESET)"
	$(VENV_ACTIVATE) && pytest

lint:
	@echo "$(YELLOW)$(call MSG,LINT)$(RESET)"
	$(VENV_ACTIVATE) && black . --check && mypy .

format:
	@echo "$(YELLOW)$(call MSG,FORMAT)$(RESET)"
	$(VENV_ACTIVATE) && black . && isort .

migrate:
	@command -v alembic >/dev/null 2>&1 || { echo "$(RED)❌ alembic is not installed.$(RESET)"; exit 1; }
	@echo ""
	@echo "$(GREEN)$(call MSG,MIGRATE)$(RESET)"
	$(VENV_ACTIVATE) && alembic upgrade head
	@echo ""

migrate-up:
	@echo "$(GREEN)$(call MSG,MIGRATE_UP)$(RESET)"
	@name=$${NAME:-""}; \
	if [ -z "$$name" ]; then \
		echo -n "$(call MSG,ASK_MIGRATION_NAME)"; \
		read name_input; \
		name=$$name_input; \
	fi; \
	if [ -z "$$name" ]; then \
		name="auto_migration_$$(date +%Y%m%d_%H%M%S)"; \
		echo "📄 Auto-generated name: $$name"; \
	fi; \
	echo "$(call MSG,MIGRATION_NAME)$$name"; \
	$(VENV_ACTIVATE) && alembic revision --autogenerate -m "$$name"

migrate-down:
	@echo "$(RED)$(call MSG,MIGRATE_DOWN)$(RESET)"
	@target=$${NAME:-""}; \
	if [ -z "$$target" ]; then \
		echo "$(call MSG,MIGRATE_DOWN_CHOOSE)"; \
		alembic history | head -n 10 | awk '{printf "%d) %s %s %s %s\n", NR, $$1, $$2, $$3, $$4}'; \
		printf "$(call MSG,CHOOSE_REV_NUM)" > /dev/tty; \
		read rev_num < /dev/tty; \
		if [ "$$rev_num" = "0" ]; then \
			echo "$(call MSG,MIGRATE_DOWN_CANCELLED)"; \
			exit 0; \
		fi; \
		rev=$$(alembic history | head -n 10 | awk "NR==$$rev_num {print \$$1}"); \
	else \
		rev=$$target; \
	fi; \
	if [ -z "$$rev" ]; then \
		echo "$(call MSG,NO_REVISION_FOUND)"; \
		exit 1; \
	fi; \
	echo "$(call MSG,MIGRATING_TO_REV)$$rev"; \
	$(VENV_ACTIVATE) && alembic downgrade "$$rev"

migrate-prev:
	@rev=$$(alembic history | head -n 2 | tail -n 1 | awk '{print $$1}'); \
	echo "$(call MSG,MIGRATING_TO_REV)$$rev"; \
	bash -c '$(VENV_ACTIVATE) && alembic downgrade "$$0"' "$$rev"

migrate-history:
	@echo "$(BOLD)$(YELLOW)📜 Migration history:$(RESET)"
	@$(VENV_ACTIVATE) && alembic history | head -n 20

migrate-help:
	@echo "$(BOLD)$(CYAN)🔧 MIGRATION COMMANDS:$(RESET)"
	@echo "$(BOLD)$(YELLOW)make migrate                  $(RESET)-------> $(call MSG,HELP_MIGRATE)"
	@echo "$(BOLD)$(YELLOW)make migrate-up NAME=...      $(RESET)-------> $(call MSG,HELP_MIGRATE_UP)"
	@echo "$(BOLD)$(YELLOW)make migrate-down [NAME=rev]  $(RESET)-------> $(call MSG,HELP_MIGRATE_DOWN)"
	@echo "$(BOLD)$(YELLOW)make migrate-prev             $(RESET)-------> $(call MSG,HELP_MIGRATE_PREV)"
	@echo "$(BOLD)$(YELLOW)make migrate-history          $(RESET)-------> $(call MSG,HELP_MIGRATE_HISTORY)"
	@echo "$(BOLD)$(YELLOW)make migrate-help             $(RESET)-------> $(call MSG,HELP_MIGRATE_HELP)"
	@echo ""

add-docker-network:
	@echo "$(BLUE)$(call MSG,ADD_DOCKER_NETWORK)$(RESET)"
	@docker network inspect $(DOCKER_NETWORK) >/dev/null 2>&1 || \
	docker network create \
		--driver bridge \
		--subnet=172.113.0.0/16 \
		--gateway=172.113.0.1 \
		--attachable \
		$(DOCKER_NETWORK)

docker-up: add-docker-network
	@echo "$(BLUE)$(call MSG,DOCKER_UP)$(RESET)"
	docker compose --env-file .env -f deploy/compose.$(TYPE_SERVICE).$(APP_NAME).full.$(TYPE_SERVER).yml up -d

docker-down:
	@echo "$(BLUE)$(call MSG,DOCKER_DOWN)$(RESET)"
	docker compose -f deploy/compose.$(TYPE_SERVICE).$(APP_NAME).full.$(TYPE_SERVER).yml down

docker-pstgr-up: add-docker-network
	@echo "$(BLUE)$(call MSG,DOCKER_PSTGR_UP)$(RESET)"
	docker compose --env-file .env -f deploy/compose.$(TYPE_SERVICE).$(APP_NAME).pstgr.$(TYPE_SERVER).yml up -d

docker-pstgr-down:
	@echo "$(BLUE)$(call MSG,DOCKER_PSTGR_DOWN)$(RESET)"
	docker compose -f deploy/compose.$(TYPE_SERVICE).$(APP_NAME).pstgr.$(TYPE_SERVER).yml down

docker-app-up: add-docker-network
	@echo "$(BLUE)$(call MSG,DOCKER_APP_UP)$(RESET)"
	docker compose --env-file .env -f deploy/compose.$(TYPE_SERVICE).$(APP_NAME).app.$(TYPE_SERVER).yml up -d

docker-app-down:
	@echo "$(RED)$(call MSG,DOCKER_APP_DOWN)$(RESET)"
	docker compose -f deploy/compose.$(TYPE_SERVICE).$(APP_NAME).app.$(TYPE_SERVER).yml down

docker-infrastructure-up: add-docker-network
	@echo "$(BLUE)$(call MSG,DOCKER_INFRA_UP)$(RESET)"
	docker compose --env-file .env -f deploy/compose.infrastructure.$(TYPE_SERVER).yml up -d

docker-infrastructure-down:
	@echo "$(RED)$(call MSG,DOCKER_INFRA_DOWN)$(RESET)"
	docker compose -f deploy/compose.infrastructure.$(TYPE_SERVER).yml down

docker-help:
	@echo "$(BOLD)$(CYAN)🐳 DOCKER COMMANDS:$(RESET)"
	@echo "$(BOLD)$(YELLOW)make docker-up                 $(RESET)-------> $(call MSG,HELP_DOCKER_UP)"
	@echo "$(BOLD)$(YELLOW)make docker-down               $(RESET)-------> $(call MSG,HELP_DOCKER_DOWN)"
	@echo "$(BOLD)$(YELLOW)make docker-app-up             $(RESET)-------> $(call MSG,HELP_DOCKER_APP_UP)"
	@echo "$(BOLD)$(YELLOW)make docker-app-down           $(RESET)-------> $(call MSG,HELP_DOCKER_APP_DOWN)"
	@echo "$(BOLD)$(YELLOW)make docker-pstgr-up           $(RESET)-------> $(call MSG,HELP_DOCKER_PSTGR_UP)"
	@echo "$(BOLD)$(YELLOW)make docker-pstgr-down         $(RESET)-------> $(call MSG,HELP_DOCKER_PSTGR_DOWN)"
	@echo "$(BOLD)$(YELLOW)make docker-infrastructure-up  $(RESET)-------> $(call MSG,HELP_DOCKER_INFRA_UP)"
	@echo "$(BOLD)$(YELLOW)make docker-infrastructure-down$(RESET)-------> $(call MSG,HELP_DOCKER_INFRA_DOWN)"
	@echo "$(BOLD)$(YELLOW)make add-docker-network        $(RESET)-------> $(call MSG,HELP_ADD_DOCKER_NETWORK)"
	@echo ""

clean:
	@echo "$(RED)$(call MSG,CLEAN)$(RESET)"
	@find . -type d -name '__pycache__' -exec rm -r {} + || true
	@find . -type d -name '*.egg-info' -exec rm -r {} + || true
	@rm -rf \
		.mypy_cache \
		.pytest_cache \
		.coverage \
		htmlcov \
		build \
		*.egg-info \
		create_buckets.sh \
		.env.lang.bak \
		.env_downloaded

	@echo "Removing editable install links and leftover packages from site-packages..."
	@find .venv/lib -type f -name '$(NAME_PATH_APP).egg-link' -exec rm -f {} + || true
	@find .venv/lib -type d -path '*/site-packages/$(NAME_PATH_APP)*' -exec rm -rf {} + || true

clean-all:
	@echo "$(YELLOW)$(call MSG,CLEAN_ALL_PROMPT)$(RESET)" >&2; \
	read -r confirm; \
	confirm_l=$$(echo "$$confirm" | tr '[:upper:]' '[:lower:]'); \
	if [ "$$confirm_l" = "y" ]; then \
		echo "$(RED)$(call MSG,CLEAN_ALL_DONE)$(RESET)"; \
		$(MAKE) clean; \
		rm -rf \
			.venv \
			uv.lock \
			dist \
			node_modules \
			logs; \
	elif [ "$$confirm_l" = "q" ]; then \
		echo "$(YELLOW)$(call MSG,CLEAN_ABORTED)$(RESET)"; \
		exit 0; \
	else \
		echo "$(YELLOW)$(call MSG,CLEAN_ABORTED)$(RESET)"; \
	fi

lock:
	@if [ "$(TYPE_SERVER)" != "prod" ]; then \
		echo "$(RED)$(call MSG,LOCK_UNSUPPORTED)$(RESET)"; \
		exit 0; \
	fi
	@echo "$(YELLOW)$(call MSG,LOCKING)$(RESET)"
	$(VENV_ACTIVATE) && uv pip compile pyproject.toml

sync:
	@if [ "$(TYPE_SERVER)" != "prod" ]; then \
		echo "$(RED)$(call MSG,SYNC_UNSUPPORTED)$(RESET)"; \
		exit 0; \
	fi
	@echo "$(YELLOW)$(call MSG,SYNCING)$(RESET)"
	$(VENV_ACTIVATE) && uv pip install -- --sync

install-ssh:
	@echo "$(YELLOW)🔐 $$(call MSG,INSTALL_SSH_START)$(RESET)"
	@if [ "$(OS)" = "Windows_NT" ]; then \
		echo "$(YELLOW)⚠️  $$(call MSG,WINDOWS_DETECTED)$(RESET)"; \
		echo "$(BLUE)🔷 $$(call MSG,WINDOWS_HINT)$(RESET)"; \
		echo "    $(GREEN)$(SSH_SCRIPT_CMD)$(RESET)"; \
		echo "$(BLUE)🔷 $$(call MSG,RUNNING_WINDOWS_SCRIPT)$(RESET)"; \
		cmd /C make-scripts\\$(SSH_SCRIPT_CMD) $(LANG) $(TYPE_SERVER) $(SERVER_IP_$(shell echo $(TYPE_SERVER) | tr a-z A-Z)) $(SERVER_PORT_$(shell echo $(TYPE_SERVER) | tr a-z A-Z)); \
	else \
		UNAME=$$(uname); \
		if [ "$$UNAME" = "Linux" ] || [ "$$UNAME" = "Darwin" ]; then \
			echo "$(BLUE)🔷 $$(call MSG,UNIX_DETECTED) ($$UNAME). $(call MSG,RUNNING_LINUX_SCRIPT)$(RESET)"; \
			TYPE_SERVER=$(TYPE_SERVER) SERVER_IP=$(SERVER_IP_$(shell echo $(TYPE_SERVER) | tr a-z A-Z)) SERVER_PORT=$(SERVER_PORT_$(shell echo $(TYPE_SERVER) | tr a-z A-Z)) \
			bash make-scripts/$(SSH_SCRIPT_SH) $(LANG); \
		else \
			echo "$(RED)❌ $$(call MSG,UNKNOWN_OS): $$UNAME$(RESET)"; \
			exit 1; \
		fi \
	fi

ssh-dev:
	@$(MAKE) install-ssh TYPE_SERVER=dev LANG=$(LANG)

ssh-prod:
	@$(MAKE) install-ssh TYPE_SERVER=prod LANG=$(LANG)

lang:
	@echo "$(CYAN)$(call MSG,LANG_SELECT_PROMPT)$(RESET)"
	@echo "1. 🇷🇺 $(call MSG,LANG_RUSSIAN)"
	@echo "2. 🇬🇧 $(call MSG,LANG_ENGLISH)"
	@echo "Q. ❌ $(call MSG,LANG_CANCEL)"
	@while true; do \
		echo -n "$(call MSG,LANG_ENTER_CHOICE) "; read choice; \
		if [ "$$choice" = "1" ] || [ "$$choice" = "ru" ]; then \
			lang_val="ru"; break; \
		elif [ "$$choice" = "2" ] || [ "$$choice" = "en" ]; then \
			lang_val="en"; break; \
		elif [ "$$choice" = "q" ] || [ "$$choice" = "Q" ] || [ "$$choice" = "exit" ]; then \
			echo "$(YELLOW)$(call MSG,LANG_ABORTED)$(RESET)"; exit 0; \
		else \
			echo "$(RED)$(call MSG,LANG_INVALID_CHOICE)$(RESET)"; \
		fi; \
	done; \
	if grep -q '^LANG=' .env.lang 2>/dev/null; then \
		sed -i.bak "s/^LANG=.*/LANG=$$lang_val/" .env.lang && rm -f .env.lang.bak; \
	else \
		(echo "LANG=$$lang_val"; cat .env.lang 2>/dev/null) > .env.lang.tmp && mv .env.lang.tmp .env.lang; \
	fi; \
	echo "$(GREEN)$(call MSG,LANG_UPDATED): $$lang_val$(RESET)"


dev:
prod:
user:
catalog:


help:
	@echo "$(BOLD)$(CYAN)"
	@echo "╔════════════════════════════════════════════════════════════════════════════════╗"
	@echo "          $(call MSG,HELP_HEADER)"
	@echo "╚════════════════════════════════════════════════════════════════════════════════╝"
	@echo "$(RESET)"
	@echo " $(BOLD)💡 $(call MSG,HELP_WELCOME)$(RESET)"
	@echo ""
	@echo "$(BOLD)🔧 $(call MSG,HELP_GROUP_PROJECT)$(RESET)"
	@echo "  $(YELLOW)make run                 $(RESET) → $(call MSG,HELP_RUN)"
	@echo "  $(YELLOW)make install / i         $(RESET) → $(call MSG,HELP_INSTALL_$(shell echo $(TYPE_SERVER) | tr a-z A-Z))"
	@echo "  $(YELLOW)make env-pull [dev|prod] $(RESET) → $(call MSG,HELP_ENV_PULL)"
	@echo "  $(YELLOW)make lang                $(RESET) → $(call MSG,HELP_LANG)"
	@echo ""
	@echo "$(BOLD)📦 $(call MSG,HELP_GROUP_DEPS)$(RESET)"
	@echo "  $(YELLOW)make add [dev|prod]         $(RESET) → $(call MSG,HELP_ADD_$(shell echo $(TYPE_SERVER) | tr a-z A-Z))"
	@if [ "$(TYPE_SERVER)" = "prod" ]; then \
		echo "  $(YELLOW)make lock                	$(RESET) → $(call MSG,HELP_LOCK)"; \
		echo "  $(YELLOW)make sync                  $(RESET) → $(call MSG,HELP_SYNC)"; \
	else \
		echo "  $(GREY)make lock                    $(RESET) → $(call MSG,HELP_LOCK) $(call MSG,UNAVAILABLE_DEV)"; \
		echo "  $(GREY)make sync                    $(RESET) → $(call MSG,HELP_SYNC) $(call MSG,UNAVAILABLE_DEV)"; \
	fi
	@echo ""
	@echo "$(BOLD)🧪 $(call MSG,HELP_GROUP_CODE)$(RESET)"
	@echo "  $(YELLOW)make check       $(RESET) → $(call MSG,HELP_CHECK_$(shell echo $(TYPE_SERVER) | tr a-z A-Z))"
	@echo "  $(YELLOW)make test        $(RESET) → $(call MSG,HELP_TEST)"
	@echo "  $(YELLOW)make lint        $(RESET) → $(call MSG,HELP_LINT)"
	@echo "  $(YELLOW)make format      $(RESET) → $(call MSG,HELP_FORMAT)"
	@echo ""
	@echo "$(BOLD)🛠️ $(call MSG,HELP_GROUP_UTILS)$(RESET)"
	@echo "  $(YELLOW)make shell       $(RESET) → $(call MSG,HELP_SHELL)"
	@echo "  $(YELLOW)make doctor      $(RESET) → $(call MSG,HELP_DOCTOR)"
	@echo "  $(YELLOW)make clean       $(RESET) → $(call MSG,HELP_CLEAN)"
	@echo "  $(YELLOW)make clean-all   $(RESET) → $(call MSG,HELP_CLEAN_ALL)"
	@echo ""
	@echo "$(BOLD)🗃️ $(call MSG,HELP_GROUP_MIGRATE)$(RESET)"
	@echo "  $(YELLOW)make migrate           $(RESET) → $(call MSG,HELP_MIGRATE)"
	@echo "  $(YELLOW)make migrate-up        $(RESET) → $(call MSG,HELP_MIGRATE_UP)"
	@echo "  $(YELLOW)make migrate-down      $(RESET) → $(call MSG,HELP_MIGRATE_DOWN)"
	@echo "  $(YELLOW)make migrate-prev      $(RESET) → $(call MSG,HELP_MIGRATE_PREV)"
	@echo "  $(YELLOW)make migrate-history   $(RESET) → $(call MSG,HELP_MIGRATE_HISTORY)"
	@echo "  $(YELLOW)make migrate-help      $(RESET) → $(call MSG,HELP_MIGRATE_HELP)"
	@echo ""
	@echo "$(BOLD)🐳 $(call MSG,HELP_GROUP_DOCKER)$(RESET)"
	@echo "  $(YELLOW)make docker-up                 $(RESET) → $(call MSG,HELP_DOCKER_UP)"
	@echo "  $(YELLOW)make docker-down               $(RESET) → $(call MSG,HELP_DOCKER_DOWN)"
	@echo "  $(YELLOW)make docker-app-up             $(RESET) → $(call MSG,HELP_DOCKER_APP_UP)"
	@echo "  $(YELLOW)make docker-app-down           $(RESET) → $(call MSG,HELP_DOCKER_APP_DOWN)"
	@echo "  $(YELLOW)make docker-pstgr-up           $(RESET) → $(call MSG,HELP_DOCKER_PSTGR_UP)"
	@echo "  $(YELLOW)make docker-pstgr-down         $(RESET) → $(call MSG,HELP_DOCKER_PSTGR_DOWN)"
	@echo "  $(YELLOW)make docker-infrastructure-up  $(RESET) → $(call MSG,HELP_DOCKER_INFRA_UP)"
	@echo "  $(YELLOW)make docker-infrastructure-down$(RESET) → $(call MSG,HELP_DOCKER_INFRA_DOWN)"
	@echo "  $(YELLOW)make add-docker-network        $(RESET) → $(call MSG,HELP_ADD_DOCKER_NETWORK)"
	@echo "  $(YELLOW)make docker-help               $(RESET) → $(call MSG,HELP_DOCKER_HELP)"
	@echo ""
	@echo "$(BOLD)🔐 $(call MSG,HELP_GROUP_SSH)$(RESET)"
	@echo "  $(YELLOW)make ssh-dev        $(RESET) → $(call MSG,HELP_SSH_DEV)"
	@echo "  $(YELLOW)make ssh-prod       $(RESET) → $(call MSG,HELP_SSH_PROD)"
	@echo ""
	@echo " $(BOLD)ℹ️ $(call MSG,HELP_MORE_INFO)$(RESET)"
	@echo ""