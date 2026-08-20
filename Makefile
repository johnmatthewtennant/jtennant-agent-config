.PHONY: update

update:
	JTENNANT_AGENT_CONFIG_DIR="$(CURDIR)" ./install.sh --links-only
