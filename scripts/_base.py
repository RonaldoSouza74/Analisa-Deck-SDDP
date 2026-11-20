"""Pasta onde ficam as tabelas (.csv) e o mapa_uf.json.

Rodando normalmente (.py/.pyc): a pasta deste script.
Rodando como executável (PyInstaller ou Nuitka): a pasta do .exe.
"""
import os
import sys


def _empacotado():
    """True quando rodando como executável compilado (PyInstaller ou Nuitka)."""
    if getattr(sys, 'frozen', False):           # PyInstaller (e Nuitka recente)
        return True
    if '__compiled__' in globals():             # Nuitka
        return True
    exe = os.path.basename(sys.executable or '').lower()
    return 'python' not in exe                   # executável próprio (ex.: analisa.exe)


def pasta_base():
    if _empacotado():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
