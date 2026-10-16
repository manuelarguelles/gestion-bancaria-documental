"""Publica en Foundry los agentes (prompt) y el workflow declarativo definidos en agents/*.yaml.

Cada ejecución crea una NUEVA versión inmutable. Auth: Entra ID (az login / identidad administrada / OIDC).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from azure.ai.projects.models import (
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    TextResponseFormatJsonSchema,
    WorkflowAgentDefinition,
)

from ..foundry import project
from ..paths import root

AGENTS_DIR = root() / "agents"
ORDEN = ["clasificador", "extractor", "analista-excepciones"]  # el workflow va al final (depende de ellos)


def _subst(s: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ[m.group(1)], s)


def deploy_prompt_agent(path: Path) -> str:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    rf = spec["response_format"]
    definition = PromptAgentDefinition(
        model=_subst(spec["model"]),
        instructions=spec["instructions"],
        text=PromptAgentDefinitionTextOptions(
            format=TextResponseFormatJsonSchema(name=rf["name"], schema=rf["schema"], strict=rf.get("strict", True))
        ),
    )
    v = project().agents.create_version(agent_name=spec["name"], definition=definition,
                                        description=spec.get("description"))
    return f"{v.name} v{v.version}"


def deploy_workflow(path: Path) -> str:
    wf = path.read_text(encoding="utf-8")
    v = project().agents.create_version(agent_name="gbd-workflow-documental",
                                        definition=WorkflowAgentDefinition(workflow=wf),
                                        description="Workflow documental: clasificar -> extraer (cartas fianza)")
    return f"{v.name} v{v.version}"


def main() -> None:
    os.environ.setdefault("FOUNDRY_MODEL", "gpt-5-mini")
    for n in ORDEN:
        print("agente  ", deploy_prompt_agent(AGENTS_DIR / f"{n}.yaml"))
    print("workflow", deploy_workflow(AGENTS_DIR / "workflow-documental.yaml"))


if __name__ == "__main__":
    main()
