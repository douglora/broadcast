"""Fixtures compartilhadas dos testes do livro (sem rede)."""

import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

FIXTURES = os.path.join(RAIZ, "tests", "fixtures")


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIXTURES


@pytest.fixture(scope="session")
def universo():
    from livro import universo as uni
    return uni.carregar()


@pytest.fixture(scope="session")
def limiares():
    from livro import universo as uni
    return uni.carregar_yaml("limiares.yaml")


def ler_serie_fixture(nome):
    import json
    from livro import indicadores as ind
    d = json.load(open(os.path.join(FIXTURES, "series", f"{nome}.json"), encoding="utf-8"))
    return ind.de_precos(d["dates"], d["prices"])
