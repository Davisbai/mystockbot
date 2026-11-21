"""Shared production inputs for terminal, Streamlit, and scheduled scans."""
from app_support import source_digest
RUNTIME_SOURCE_SHA256 = source_digest(__file__)

TRAINING_START_DATE = '2023-01-01'
# Broader controls did not support replacing the existing exit policy.
EXTENSION_EXIT_MODE = 'legacy_exit'
# Entry quality floor: weak support or an edge near trading costs stays WATCH.
MIN_ENTRY_SUPPORT = 10
MIN_ENTRY_TD_PCT = 1.0
MODEL_VERSION = f'tdrl-20261121-entry-floor-v1-{EXTENSION_EXIT_MODE}'
