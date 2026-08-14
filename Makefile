.PHONY: validate install uninstall reinstall test

validate:
	claude plugin validate .

install:
	claude plugin install .

uninstall:
	claude plugin uninstall agent-handoff

reinstall: uninstall install

test:
	python3 -m pytest tests/ -v
