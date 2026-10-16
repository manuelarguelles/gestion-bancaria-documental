"""Cliente de Microsoft Foundry: autenticación Entra ID (sin API keys)."""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from urllib.parse import urlparse

from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from .config import settings


class _TokenFileCredential:
    """Credencial para desarrollo en contenedor: lee tokens de corta vida desde una carpeta montada.

    Archivos: `ai` (scope ai.azure.com, API del proyecto) y `cognitive` (scope cognitiveservices, embeddings).
    En producción se usa identidad administrada / OIDC (DefaultAzureCredential); nunca claves en la imagen.
    """

    def __init__(self, folder: str) -> None:
        self._folder = folder

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        name = "ai" if any("ai.azure.com" in s for s in scopes) else "cognitive"
        with open(os.path.join(self._folder, name), encoding="utf-8") as f:
            return AccessToken(f.read().strip(), int(time.time()) + 600)


def _credential():
    d = os.getenv("GBD_AAD_TOKEN_DIR")
    return _TokenFileCredential(d) if d and os.path.isdir(d) else DefaultAzureCredential()


@lru_cache
def project() -> AIProjectClient:
    return AIProjectClient(endpoint=settings().project_endpoint, credential=_credential(),
                           allow_preview=True)


@lru_cache
def openai_client():
    return project().get_openai_client()


def invoke_agent(name: str, text: str, conversation: str | None = None) -> str:
    """Invoca un agente (prompt o workflow) de Foundry por nombre y devuelve el texto final."""
    oc = openai_client()
    conv = conversation or oc.conversations.create().id
    r = oc.responses.create(conversation=conv, input=text,
                            extra_body={"agent_reference": {"name": name, "type": "agent_reference"}})
    return r.output_text


def invoke_json(name: str, text: str) -> dict:
    out = invoke_agent(name, text).strip()
    if out.startswith("```"):
        out = out.strip("`").removeprefix("json").strip()
    return json.loads(out)


@lru_cache
def _aoai() -> AzureOpenAI:
    """Embeddings vía el endpoint Azure OpenAI del mismo recurso que aloja el proyecto Foundry."""
    account = urlparse(settings().project_endpoint).hostname.split(".")[0]
    return AzureOpenAI(azure_endpoint=f"https://{account}.openai.azure.com", api_version="2024-10-21",
                       azure_ad_token_provider=get_bearer_token_provider(
                           _credential(), "https://cognitiveservices.azure.com/.default"))


def embed(texts: list[str]) -> list[list[float]]:
    r = _aoai().embeddings.create(model=settings().embedding_model, input=texts)
    return [d.embedding for d in r.data]


def run_workflow(name: str, text: str) -> list[str]:
    """Ejecuta un workflow de Foundry y devuelve los mensajes que emitió (uno por nodo con autoSend)."""
    oc = openai_client()
    r = oc.responses.create(conversation=oc.conversations.create().id, input=text,
                            extra_body={"agent_reference": {"name": name, "type": "agent_reference"}})
    if r.status != "completed":
        raise RuntimeError(f"workflow {name} terminó en {r.status}: {getattr(r, 'error', None)}")
    return [c.text for o in r.output if o.type == "message" for c in o.content if c.type == "output_text"]
