.DEFAULT_GOAL := help

BLENDER ?= blender
INPUT ?=
OUTPUT ?=
REPORT ?= autotpose-report.json
BIND_METHOD ?= AUTO
PYTHON ?= .venv/bin/python
VENV_SITE_PACKAGES := $(shell . .venv/bin/activate 2>/dev/null && python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")

export PYTHONPATH := $(VENV_SITE_PACKAGES):$$PYTHONPATH

.PHONY: help sync compile test check pose pose-rest rig-pose rig-pose-rest legacy-bridge clean

help: ## Show available commands.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "%-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Create or update the project-local instance-rig environment.
	rm -f uv.lock
	uv venv --python 3.11 .venv
	uv lock --python 3.11
	uv sync --python .venv/bin/python

test: ## Run the Blender-neutral core contract tests.
	$(PYTHON) -m unittest discover -s tests -v

compile: ## Check that the Blender script has valid Python syntax.
	$(PYTHON) -m py_compile auto_t_pose.py

check: compile test ## Run all repository checks.

pose: ## Create a non-destructive T-pose. Requires INPUT (.blend/.glb/.gltf) and OUTPUT (.blend/.glb).
	@test -n "$(INPUT)" || (echo "Set INPUT to a source .blend, .glb, or .gltf path." >&2; exit 2)
	@test -n "$(OUTPUT)" || (echo "Set OUTPUT to a destination .blend or .glb path." >&2; exit 2)
	$(BLENDER) --background --python auto_t_pose.py -- --input "$(INPUT)" --output "$(OUTPUT)" --report "$(REPORT)"

pose-rest: ## Bake a rest pose. Requires INPUT (.blend/.glb/.gltf) and OUTPUT (.blend/.glb).
	@test -n "$(INPUT)" || (echo "Set INPUT to a source .blend, .glb, or .gltf path." >&2; exit 2)
	@test -n "$(OUTPUT)" || (echo "Set OUTPUT to a destination .blend or .glb path." >&2; exit 2)
	$(BLENDER) --background --python auto_t_pose.py -- --input "$(INPUT)" --output "$(OUTPUT)" --report "$(REPORT)" --apply-rest-pose

rig-pose: ## Auto-rig then T-pose. Requires INPUT (.blend/.glb/.gltf) and OUTPUT (.blend/.glb).
	@test -n "$(INPUT)" || (echo "Set INPUT to a source .blend, .glb, or .gltf path." >&2; exit 2)
	@test -n "$(OUTPUT)" || (echo "Set OUTPUT to a destination .blend or .glb path." >&2; exit 2)
	$(BLENDER) --background --python auto_t_pose.py -- --input "$(INPUT)" --output "$(OUTPUT)" --report "$(REPORT)" --auto-rig --bind-method "$(BIND_METHOD)"

rig-pose-rest: ## Auto-rig and bake a T-pose rest pose. Requires INPUT and OUTPUT paths.
	@test -n "$(INPUT)" || (echo "Set INPUT to a source .blend, .glb, or .gltf path." >&2; exit 2)
	@test -n "$(OUTPUT)" || (echo "Set OUTPUT to a destination .blend or .glb path." >&2; exit 2)
	$(BLENDER) --background --python auto_t_pose.py -- --input "$(INPUT)" --output "$(OUTPUT)" --report "$(REPORT)" --auto-rig --bind-method "$(BIND_METHOD)" --apply-rest-pose

legacy-bridge: ## Legacy prototype bridge for browser testing only; not the preferred AutoTPose workflow.
	@python mesh2motion-extension/mesh2motion_autotpose_bridge.py

clean: ## Remove generated local build and test artifacts.
	rm -rf build dist .pytest_cache .coverage htmlcov
