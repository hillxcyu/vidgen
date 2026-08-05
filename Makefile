.PHONY: build test run clean

build:
	docker compose build

test:
	docker compose run --rm test

run:
	docker compose run --rm app --prompt "A red panda skiing in Hakuba" --mode "i2v_chaining"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
