.PHONY: test backend-test web-install web-build

test: backend-test

backend-test:
	cd backend && pytest -q

web-install:
	cd apps/web && npm install

web-build:
	cd apps/web && npm run build
