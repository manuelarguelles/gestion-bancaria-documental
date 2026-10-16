.PHONY: install up down migrate policies deploy-agents samples run eval test api tokens docker-build docker-run
COMPOSE=docker compose -f docker/compose.yml --env-file .env

install:        ## entorno local
	python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
up:             ## Postgres + pgvector
	$(COMPOSE) up -d db
down:
	$(COMPOSE) down
migrate:
	.venv/bin/gbd migrate
policies:       ## embebe las políticas en pgvector
	.venv/bin/gbd indexar-politicas
deploy-agents:  ## publica agentes + workflow en Foundry (requiere az login)
	.venv/bin/gbd deploy-agentes
samples:
	.venv/bin/python dataplane/generar_muestras.py
run:            ## ejecuta el workflow sobre la bandeja de ejemplo
	.venv/bin/gbd run
eval:
	.venv/bin/python evals/run_eval.py
test:
	.venv/bin/python -m pytest -q
api:
	.venv/bin/gbd api
tokens:         ## tokens de corta vida para el contenedor (out/ está ignorado por git)
	mkdir -p out/tokens && az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv > out/tokens/ai \
	 && az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv > out/tokens/cognitive
docker-build:
	docker build -f docker/Dockerfile -t gbd:local .
docker-run: tokens  ## corre el workflow dentro del contenedor
	$(COMPOSE) --profile app run --rm app run --bandeja /app/dataplane/samples/bandeja --registro /app/dataplane/samples/registro_tesoreria.xlsx
