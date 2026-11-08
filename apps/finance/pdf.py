"""Compatibilité : les fonctions PDF sont dans apps.core.pdf (partagées par tous les modules)."""
from apps.core.pdf import table_report

__all__ = ["table_report"]
