"""Shared production inputs for terminal, Streamlit, and scheduled scans."""
from app_support import source_digest
RUNTIME_SOURCE_SHA256 = source_digest(__file__)

TRAINING_START_DATE = '2023-01-01'
# Broader controls did not support replacing the existing exit policy.
EXTENSION_EXIT_MODE = 'legacy_exit'
MODEL_VERSION = f'tdrl-20261014-chip-audit-v1-{EXTENSION_EXIT_MODE}'
