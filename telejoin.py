"""telejoin: entra nos grupos e canais de uma lista de links do Telegram.

    venv/bin/python telejoin.py [links.txt | -] [--dry-run] [--intervalo S] [--refazer] [--status]

Usa uma conta de usuário (MTProto), não bot: bot não entra por convite.
Cada resultado vai para o arquivo de estado; rodar de novo retoma de onde parou.

FLOOD_WAIT nunca encerra a execução: espera o tempo que o Telegram pedir, por
maior que seja, e segue. Só PEER_FLOOD (conta marcada como spam) e o limite de
chats param, porque insistir neles piora a situação da conta.
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime

from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Channel

import config
from links import ler

# Resultados definitivos: rodar de novo não tenta outra vez (a menos que --refazer).
# `erro` é tentado de novo na próxima execução.
FINAIS = {"entrou", "ja_membro", "pedido_enviado", "expirado", "invalido",
          "nao_existe", "nao_e_chat", "sem_acesso", "banido"}

# Chamadas que efetivamente entraram (ou pediram para entrar): são essas que
# contam para o limite de entradas, e só depois delas o ritmo pausa.
ENTRADAS = {"entrou", "pedido_enviado"}

# Sem conexão (rede caiu durante uma espera de horas): tenta reconectar a cada N s.
RECONEXAO_S = 60


class Parar(Exception):
    """Continuar faz mal à conta (PEER_FLOOD) ou não adianta (limite de chats)."""


def agora():
    return datetime.now().isoformat(timespec="seconds")


def hora(segundos_a_frente):
    return datetime.fromtimestamp(time.time() + segundos_a_frente).strftime("%d/%m %H:%M")


def duracao(segundos):
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------- estado

def carregar_estado():
    """{"links": {chave: resultado}, "floods": [registro, ...]}"""
    try:
        with open(config.ESTADO, encoding="utf-8") as f:
            estado = json.load(f)
    except FileNotFoundError:
        estado = {}
    estado.setdefault("links", {})
    estado.setdefault("floods", [])
    return estado


def salvar_estado(estado):
    # Escreve e renomeia: um Ctrl+C no meio não deixa JSON pela metade.
    tmp = config.ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.ESTADO)


# ---------------------------------------------------------------- ritmo

class Ritmo:
    """Intervalo entre entradas que se ajusta ao que o Telegram responde.

    Cada FLOOD_WAIT dobra o intervalo (até o teto); cada entrada sem flood o
    reduz em 10%, de volta ao valor base. Assim uma conta que tomou flood depois
    de 20 entradas não volta a entrar a cada 30 s e toma outro logo em seguida.
    """

    def __init__(self, base, teto):
        self.base = base
        self.teto = max(teto, base)
        self.atual = base
        self.entradas_desde_flood = 0
        self.ultimo_flood = None  # time.time() do último flood nesta execução

    def apos_entrada(self):
        self.entradas_desde_flood += 1
        self.atual = max(self.base, self.atual * 0.9)

    def apos_flood(self):
        self.entradas_desde_flood = 0
        self.ultimo_flood = time.time()
        self.atual = min(self.teto, self.atual * 2)

    def pausa(self):
        return self.atual * random.uniform(1, 1.5)


async def esperar(segundos, motivo):
    """Dorme `segundos`, dizendo no terminal até quando e quanto falta."""
    print(f"    {motivo}: esperando {duracao(segundos)} (até {hora(segundos)})", flush=True)
    fim = time.monotonic() + segundos
    while True:
        falta = fim - time.monotonic()
        if falta <= 0:
            return
        # Um aviso a cada 10 min: numa espera de horas, dá para ver que está vivo.
        await asyncio.sleep(min(falta, 600))
        falta = fim - time.monotonic()
        if falta > 0:
            print(f"    ...faltam {duracao(falta)}", flush=True)


# ---------------------------------------------------------------- entrar

def _titulo(updates):
    chats = getattr(updates, "chats", None) or []
    return chats[0].title if chats else None


async def entrar(client, alvo):
    """Uma tentativa -> (status, título ou detalhe). Flood e rede sobem para o chamador."""
    if alvo.tipo == "convite":
        try:
            return "entrou", _titulo(await client(ImportChatInviteRequest(alvo.valor)))
        except errors.UserAlreadyParticipantError:
            return "ja_membro", None
        except errors.InviteRequestSentError:
            # Chat com aprovação: o pedido fica pendente até um admin aceitar.
            return "pedido_enviado", None
        except errors.InviteHashExpiredError:
            return "expirado", None
        except (errors.InviteHashInvalidError, errors.InviteHashEmptyError):
            return "invalido", None

    try:
        entidade = await client.get_entity(alvo.valor)
    except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError, ValueError):
        return "nao_existe", None
    if not isinstance(entidade, Channel):
        return "nao_e_chat", "username é de usuário ou bot"
    if not entidade.left:
        return "ja_membro", entidade.title
    try:
        await client(JoinChannelRequest(entidade))
    except errors.InviteRequestSentError:
        return "pedido_enviado", entidade.title
    return "entrou", entidade.title


async def processar(client, alvo, ritmo, ao_flood=lambda registro: None):
    """Tenta até dar resultado. FLOOD_WAIT e queda de rede: espera e repete."""
    while True:
        try:
            if not client.is_connected():
                await client.connect()
            return await entrar(client, alvo)
        except errors.FloodError as e:
            # FloodWaitError e FloodPremiumWaitError: os dois trazem `seconds`.
            segundos = getattr(e, "seconds", None) or RECONEXAO_S
            n = ritmo.entradas_desde_flood
            ao_flood({
                "quando": agora(),
                "segundos": segundos,
                "link": alvo.chave,
                "entradas_antes": n,
                "min_desde_flood_anterior": (
                    round((time.time() - ritmo.ultimo_flood) / 60)
                    if ritmo.ultimo_flood else None),
                "intervalo_s": round(ritmo.atual),
            })
            ritmo.apos_flood()
            await esperar(segundos + 1,
                          f"FLOOD_WAIT de {duracao(segundos)} após {n} entrada(s); "
                          f"intervalo sobe para {duracao(ritmo.atual)}")
        except errors.PeerFloodError:
            raise Parar("PEER_FLOOD: o Telegram marcou a conta como possível spam. "
                        "Insistir agora pode restringir a conta; espere pelo menos "
                        "um dia antes de rodar de novo")
        except errors.ChannelsTooMuchError:
            raise Parar("a conta chegou no limite de canais/grupos "
                        "(500, ou 1000 com Premium); saia de alguns e rode de novo")
        except errors.ChannelPrivateError:
            return "sem_acesso", "privado ou a conta foi removida dele"
        except errors.UserBannedInChannelError:
            return "banido", None
        except errors.RPCError as e:
            return "erro", f"{type(e).__name__}: {e}"
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            await esperar(RECONEXAO_S, f"sem conexão ({type(e).__name__})")


async def rodar(alvos, args):
    estado = carregar_estado()
    links = estado["links"]
    pendentes = [a for a in alvos
                 if args.refazer or links.get(a.chave, {}).get("status") not in FINAIS]
    print(f"{len(alvos)} alvos, {len(alvos) - len(pendentes)} já resolvidos, "
          f"{len(pendentes)} a processar")
    if not pendentes:
        return 0

    if not config.API_ID or not config.API_HASH:
        raise SystemExit(f"preencha TELEGRAM_API_ID e TELEGRAM_API_HASH em {config.CAMINHO_ENV}")

    def ao_flood(registro):
        estado["floods"].append(registro)
        salvar_estado(estado)

    ritmo = Ritmo(args.intervalo, config.INTERVALO_MAX_S)
    # flood_sleep_threshold=0: todo FloodWait chega aqui, para ser registrado e
    # aparecer no terminal em vez de o Telethon dormir calado.
    client = TelegramClient(config.SESSAO, config.API_ID, config.API_HASH,
                            flood_sleep_threshold=0)
    await client.start()  # primeira vez: pede telefone, código e senha 2FA
    try:
        for i, alvo in enumerate(pendentes, 1):
            print(f"[{i}/{len(pendentes)}] {alvo.chave}", flush=True)
            try:
                status, info = await processar(client, alvo, ritmo, ao_flood)
            except Parar as e:
                print(f"PARANDO: {e}")
                return 2
            links[alvo.chave] = {"status": status, "info": info, "quando": agora()}
            salvar_estado(estado)
            print(f"    {status}" + (f" — {info}" if info else ""), flush=True)
            if status in ENTRADAS:
                ritmo.apos_entrada()
                if i < len(pendentes):
                    pausa = ritmo.pausa()
                    print(f"    pausa de {duracao(pausa)}", flush=True)
                    await asyncio.sleep(pausa)
    finally:
        await client.disconnect()
        resumo(alvos, estado)
    return 0


# ---------------------------------------------------------------- relatórios

def resumo(alvos, estado):
    contagem = {}
    for a in alvos:
        s = estado["links"].get(a.chave, {}).get("status", "pendente")
        contagem[s] = contagem.get(s, 0) + 1
    print("resumo: " + ", ".join(f"{s}={n}" for s, n in sorted(contagem.items())))


def mostrar_status():
    estado = carregar_estado()
    if not estado["links"] and not estado["floods"]:
        print("nenhuma execução ainda")
        return
    for chave, r in estado["links"].items():
        print(f"{r['status']:15} {chave}" + (f"  — {r['info']}" if r.get("info") else ""))
    contagem = {}
    for r in estado["links"].values():
        contagem[r["status"]] = contagem.get(r["status"], 0) + 1
    print("\nresumo: " + ", ".join(f"{s}={n}" for s, n in sorted(contagem.items())))

    if estado["floods"]:
        # A base para calibrar TELEJOIN_INTERVALO_S: quantas entradas a conta
        # aguentou antes de cada flood, e quanto o Telegram mandou esperar.
        print(f"\nFLOOD_WAITs ({len(estado['floods'])}):")
        print(f"  {'quando':19}  {'espera':>8}  {'entradas antes':>14}  {'intervalo':>9}")
        for f in estado["floods"]:
            print(f"  {f['quando']:19}  {duracao(f['segundos']):>8}  "
                  f"{f['entradas_antes']:>14}  {duracao(f['intervalo_s']):>9}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("arquivo", nargs="?", default=os.path.join(config.RAIZ, "links.txt"),
                   help="um link por linha; '-' lê da entrada padrão (padrão: links.txt)")
    p.add_argument("--dry-run", action="store_true",
                   help="só interpreta e lista os links, sem conectar")
    p.add_argument("--intervalo", type=int, default=config.INTERVALO_S,
                   help=f"intervalo base entre entradas em s (padrão: {config.INTERVALO_S})")
    p.add_argument("--refazer", action="store_true",
                   help="tenta de novo inclusive os links já resolvidos")
    p.add_argument("--status", action="store_true",
                   help="mostra o resultado de cada link e os FLOOD_WAITs, e sai")
    args = p.parse_args()

    if args.status:
        mostrar_status()
        return 0

    texto = sys.stdin.read() if args.arquivo == "-" else open(args.arquivo, encoding="utf-8").read()
    alvos, invalidos = ler(texto)
    for linha, motivo in invalidos:
        print(f"ignorado: {linha} ({motivo})", file=sys.stderr)

    if args.dry_run:
        for a in alvos:
            print(f"{a.tipo:8} {a.chave}")
        print(f"{len(alvos)} alvos únicos, {len(invalidos)} ignorados")
        return 0

    try:
        return asyncio.run(rodar(alvos, args))
    except KeyboardInterrupt:
        print("\ninterrompido; o progresso está salvo em", config.ESTADO)
        return 130


if __name__ == "__main__":
    sys.exit(main())
