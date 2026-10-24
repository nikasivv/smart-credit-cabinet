.PHONY: up up-ai down reset test logs openapi smoke deploy reset-demo
up:        ## Запустить всё
	docker compose up --build -d && echo "Откройте http://localhost:8080"
up-ai:     ## Запустить вместе с локальной LLM
	docker compose --profile ai up --build -d
down:
	docker compose down
reset:     ## Удалить данные и запустить заново
	docker compose down -v && $(MAKE) up
test:      ## Unit + API-тесты в контейнере
	docker compose --profile test run --rm --build tests
logs:
	docker compose logs -f api worker
smoke:     ## Сквозной сценарий против запущенного стенда
	docker compose exec api python -m app.smoke
openapi:   ## Выгрузить спецификацию в docs/openapi.json
	curl -s http://localhost:8000/openapi.json -o docs/openapi.json && echo "docs/openapi.json обновлён"
deploy:    ## Развернуть демо-стенд на сервере (порт 80)
	bash scripts/deploy.sh
reset-demo: ## Сбросить данные демо-стенда
	bash scripts/reset-demo.sh
