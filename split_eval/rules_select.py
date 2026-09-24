"""Seleziona il modulo delle regole di decisione: variabile d'ambiente
SPLIT_RULES_MODULE (default split_eval.decision_rules_split = v1)."""
import importlib
import os


def load():
    return importlib.import_module(os.environ.get('SPLIT_RULES_MODULE', 'split_eval.decision_rules_split'))
