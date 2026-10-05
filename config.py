"""
Azure OpenAI configuration.

Your key (FfldSrq...) is an Azure OpenAI Service key, not a standard OpenAI
platform key - this project now talks to Azure's endpoint using Azure's
authentication scheme (api-key header + api-version query param), which is
different from platform.openai.com.

⚠️ SECURITY NOTE
This file contains your live API key in plain text. Do NOT commit it to git,
upload it anywhere, or share this folder as-is - anyone with this key can
make API calls billed to your company's Azure subscription.
"""

import os

def _get_secret(name, default=""):
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        return st.secrets[name]
    except Exception:
        return default

# From your Azure resource "Keys and Endpoint" page.
AZURE_OPENAI_API_KEY = _get_secret("AZURE_OPENAI_API_KEY")

# Base endpoint only - just the https://<resource-name>.openai.azure.com/
# part. Do NOT include /openai/responses or the ?api-version=... part here -
# those are added automatically by the code.
AZURE_OPENAI_ENDPOINT = "https://finance-openai.openai.azure.com/"

# The api-version from the URL you were given.
AZURE_OPENAI_API_VERSION = "2025-04-01-preview"

# This is your DEPLOYMENT NAME (not necessarily the underlying model's own
# name) - the identifier your Azure admin gave this deployment when they
# set it up. You confirmed this is "gpt-5.4-mini".
AZURE_OPENAI_DEPLOYMENT = "gpt-5.4-mini"

# --- Audio transcription (used by transcribe_videos.py only) ---
# Azure requires a SEPARATE deployment for Whisper/audio transcription -
# the deployment above is for TEXT generation only. If your company has
# provisioned a Whisper deployment, put its deployment name here. If you
# don't have one yet, leave this as-is; transcribe_videos.py will fail
# clearly telling you this deployment doesn't exist, rather than silently
# using the wrong one.
AZURE_OPENAI_WHISPER_DEPLOYMENT = "whisper-1"
