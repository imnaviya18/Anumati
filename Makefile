.PHONY: up down build test lint backup restore bootstrap checks

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

test:
	./scripts/checks.sh test

lint:
	./scripts/checks.sh lint

backup:
	./scripts/backup.sh

restore:
	./scripts/restore.sh $(ARCHIVE)

bootstrap:
	./scripts/bootstrap.sh
