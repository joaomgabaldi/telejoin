"""Config do telejoin: o `.env` da raiz, no mesmo formato do telefuse.

Precedência: variável de ambiente real > `.env` > default no código.
"""
import os

RAIZ = os.path.dirname(os.path.abspath(__file__))
CAMINHO_ENV = os.environ.get("TELEJOIN_ENV") or os.path.join(RAIZ, ".env")


def _carregar(caminho):
    valores = {}
    try:
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                valores[chave.strip()] = valor.strip()
    except OSError:
        pass
    return valores


_ARQ = _carregar(CAMINHO_ENV)


def texto(chave, default=None):
    valor = os.environ.get(chave) or _ARQ.get(chave)
    return valor if valor else default


def inteiro(chave, default):
    valor = texto(chave)
    if valor is None:
        return default
    try:
        return int(valor)
    except ValueError:
        raise SystemExit(f"{CAMINHO_ENV}: {chave}={valor!r} não é um inteiro")


def caminho(chave, default):
    return os.path.join(RAIZ, texto(chave, default))


API_ID = inteiro("TELEGRAM_API_ID", 0)
API_HASH = texto("TELEGRAM_API_HASH", "")
SESSAO = caminho("TELEJOIN_SESSION", "telejoin.session")
ESTADO = caminho("TELEJOIN_ESTADO", "telejoin.estado.json")
INTERVALO_S = inteiro("TELEJOIN_INTERVALO_S", 30)
INTERVALO_MAX_S = inteiro("TELEJOIN_INTERVALO_MAX_S", 900)
