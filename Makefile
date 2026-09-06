.PHONY: test backend-test backend-worker web-install web-build

test: backend-test

backend-test:
	cd backend && pytest -q

backend-worker:
	cd backend && python -m app.workers.main

web-install:
	cd apps/web && npm install

web-build:
	cd apps/web && npm run build
