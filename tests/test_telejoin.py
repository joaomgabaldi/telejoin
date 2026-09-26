import asyncio
import os
import sys

import pytest
from telethon import errors

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telejoin  # noqa: E402
from links import Alvo  # noqa: E402


class ClienteFalso:
    """Devolve (ou levanta) as respostas da fila, uma por chamada."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = 0
        self.conectado = True

    def is_connected(self):
        return self.conectado

    async def connect(self):
        self.conectado = True

    async def __call__(self, requisicao):
        self.chamadas += 1
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def esperas(monkeypatch):
    """Troca a espera real por uma lista dos segundos pedidos."""
    pedidas = []

    async def falsa(segundos, motivo):
        pedidas.append(segundos)
    monkeypatch.setattr(telejoin, "esperar", falsa)
    return pedidas


def rodar(cliente, ritmo=None, ao_flood=lambda r: None):
    ritmo = ritmo or telejoin.Ritmo(30, 900)
    return asyncio.run(telejoin.processar(cliente, Alvo("convite", "abc"), ritmo, ao_flood))


@pytest.mark.parametrize("erro,status", [
    (errors.UserAlreadyParticipantError(None), "ja_membro"),
    (errors.InviteRequestSentError(None), "pedido_enviado"),
    (errors.InviteHashExpiredError(None), "expirado"),
    (errors.InviteHashInvalidError(None), "invalido"),
    (errors.ChannelPrivateError(None), "sem_acesso"),
])
def test_erros_viram_status(erro, status):
    assert rodar(ClienteFalso(erro))[0] == status


def test_flood_de_horas_espera_e_continua(esperas):
    """Nenhum FLOOD_WAIT encerra a execução, por maior que seja."""
    dia = 86400
    cliente = ClienteFalso(errors.FloodWaitError(None, capture=dia), object())
    assert rodar(cliente)[0] == "entrou"
    assert esperas == [dia + 1]
    assert cliente.chamadas == 2


def test_flood_premium_tambem_espera(esperas):
    cliente = ClienteFalso(errors.FloodPremiumWaitError(None, capture=7), object())
    assert rodar(cliente)[0] == "entrou"
    assert esperas == [8]


def test_flood_registra_e_dobra_o_intervalo(esperas):
    ritmo = telejoin.Ritmo(30, 900)
    for _ in range(3):
        ritmo.apos_entrada()
    registros = []
    rodar(ClienteFalso(errors.FloodWaitError(None, capture=60), object()),
          ritmo, registros.append)
    assert ritmo.atual == 60
    assert ritmo.entradas_desde_flood == 0
    [r] = registros
    assert (r["segundos"], r["entradas_antes"], r["intervalo_s"], r["link"]) == (60, 3, 30, "+abc")


def test_queda_de_rede_reconecta_e_continua(esperas):
    cliente = ClienteFalso(ConnectionError("caiu"), object())
    assert rodar(cliente)[0] == "entrou"
    assert esperas == [telejoin.RECONEXAO_S]


def test_peer_flood_para():
    with pytest.raises(telejoin.Parar, match="PEER_FLOOD"):
        rodar(ClienteFalso(errors.PeerFloodError(None)))


def test_limite_de_canais_para():
    with pytest.raises(telejoin.Parar):
        rodar(ClienteFalso(errors.ChannelsTooMuchError(None)))


def test_ritmo_dobra_ate_o_teto_e_volta_devagar_a_base():
    r = telejoin.Ritmo(30, 100)
    r.apos_flood()
    assert r.atual == 60
    r.apos_flood()
    assert r.atual == 100  # teto
    for _ in range(50):
        r.apos_entrada()
    assert r.atual == 30  # nunca abaixo da base
