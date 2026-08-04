.PHONY: clean

help:
	@echo "  clean    remove unwanted stuff"
	@echo "  link     pip install -e ."
	@echo "  test     run the tests"
	@echo "  dev      run dev server"
	@echo "  docs     build documentation"

clean:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '.DS_Store' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -rf {} +
	find . -name '.coverage' -exec rm -rf {} +
	rm -rf build dist .eggs *.egg-info +

link:
	pip install -e .

dev:
	HOST=$$(python -c 'from passportd.basis.conf import config;print(config.get("HOST"))'); \
	PORT=$$(python -c 'from passportd.basis.conf import config;print(config.get("PORT"))'); \
	FLASK_APP=passportd.app:create_app FLASK_ENV=development FLASK_DEBUG=1 flask run --host $$HOST --port $$PORT

test:
	python -m unittest discover -p "test_*.py"

docs:
	cd docs && make html
