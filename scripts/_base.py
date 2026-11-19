"""Pasta onde ficam as tabelas (.csv) e o mapa_uf.json.

Rodando normalmente (.py/.pyc): a pasta deste script.
Rodando como executável (PyInstaller, sys.frozen): a pasta do .exe.
"""
import os
import sys


def pasta_base():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
