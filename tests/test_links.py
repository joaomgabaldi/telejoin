import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from links import Alvo, LinkInvalido, interpretar, ler  # noqa: E402


@pytest.mark.parametrize("link,esperado", [
    ("https://t.me/+UGxezk8csjY4YzMx", Alvo("convite", "UGxezk8csjY4YzMx")),
    ("t.me/+_MRqmX3aA5oxNDEx", Alvo("convite", "_MRqmX3aA5oxNDEx")),
    ("https://t.me/joinchat/AAAAAEk-abc_1", Alvo("convite", "AAAAAEk-abc_1")),
    ("https://telegram.me/joinchat/XyZ", Alvo("convite", "XyZ")),
    ("tg://join?invite=abcDEF", Alvo("convite", "abcDEF")),
    ("https://t.me/durov", Alvo("username", "durov")),
    ("https://www.t.me/durov/", Alvo("username", "durov")),
    ("https://t.me/durov/123", Alvo("username", "durov")),
    ("https://t.me/durov?start=x", Alvo("username", "durov")),
    ("@telegram", Alvo("username", "telegram")),
    ("tg://resolve?domain=telegram&post=5", Alvo("username", "telegram")),
])
def test_interpretar_validos(link, esperado):
    assert interpretar(link) == esperado


@pytest.mark.parametrize("link", [
    "https://example.com/+abc",
    "https://t.me/",
    "https://t.me/c/123456/7",
    "https://t.me/joinchat/",
    "https://t.me/addstickers/pack",
    "https://t.me/ab",
    "@1abc",
    "tg://join?foo=bar",
])
def test_interpretar_invalidos(link):
    with pytest.raises(LinkInvalido):
        interpretar(link)


def test_ler_dedup_comentarios_e_invalidos():
    texto = """
    # lista
    https://t.me/+AAA
    https://t.me/Durov
    t.me/+AAA
    @durov
    https://t.me/+aaa
    lixo
    """
    alvos, invalidos = ler(texto)
    # username ignora caixa; hash de convite não
    assert [a.chave for a in alvos] == ["+AAA", "@durov", "+aaa"]
    assert invalidos == [("lixo", "não é um link do Telegram")]
