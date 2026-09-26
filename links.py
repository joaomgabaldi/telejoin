"""Parser de links do Telegram: texto livre -> alvos para entrar.

Dois tipos de alvo, porque o MTProto tem duas chamadas diferentes:
  convite  — hash de convite (`t.me/+HASH`, `t.me/joinchat/HASH`,
             `tg://join?invite=HASH`) -> messages.importChatInvite
  username — canal/supergrupo público (`t.me/nome`, `@nome`,
             `tg://resolve?domain=nome`) -> channels.joinChannel

Sem rede aqui: tudo é testável offline.
"""
import re
from dataclasses import dataclass

# Caminhos de t.me que não são username de canal.
_RESERVADOS = {"joinchat", "addstickers", "addemoji", "share", "proxy", "socks",
               "addtheme", "setlanguage", "login", "confirmphone", "c", "s", "iv"}

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_HASH = re.compile(r"^[A-Za-z0-9_-]+$")

_TME = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?P<caminho>[^?#\s]*)",
    re.IGNORECASE,
)
_TG = re.compile(r"^tg://(?P<acao>join|resolve)\?(?P<query>\S+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Alvo:
    tipo: str   # "convite" ou "username"
    valor: str  # hash do convite ou username (sem @)

    @property
    def chave(self):
        """Identidade para dedup e para o arquivo de estado.

        Username é case-insensitive no Telegram; hash de convite não.
        """
        if self.tipo == "username":
            return f"@{self.valor.lower()}"
        return f"+{self.valor}"


class LinkInvalido(ValueError):
    pass


def interpretar(link):
    """Um link -> Alvo. Levanta LinkInvalido com o motivo."""
    link = link.strip()

    m = _TG.match(link)
    if m:
        params = dict(p.partition("=")[::2] for p in m["query"].split("&"))
        if m["acao"].lower() == "join" and _HASH.match(params.get("invite", "")):
            return Alvo("convite", params["invite"])
        if m["acao"].lower() == "resolve" and _USERNAME.match(params.get("domain", "")):
            return Alvo("username", params["domain"])
        raise LinkInvalido("link tg:// sem convite nem username")

    if link.startswith("@"):
        if _USERNAME.match(link[1:]):
            return Alvo("username", link[1:])
        raise LinkInvalido("username inválido")

    m = _TME.match(link)
    if not m:
        raise LinkInvalido("não é um link do Telegram")
    partes = [p for p in m["caminho"].split("/") if p]
    if not partes:
        raise LinkInvalido("link sem caminho")

    primeiro = partes[0]
    if primeiro.startswith("+"):
        if _HASH.match(primeiro[1:]):
            return Alvo("convite", primeiro[1:])
        raise LinkInvalido("hash de convite inválido")
    if primeiro.lower() == "joinchat":
        if len(partes) > 1 and _HASH.match(partes[1]):
            return Alvo("convite", partes[1])
        raise LinkInvalido("joinchat sem hash")
    if primeiro.lower() == "c":
        # t.me/c/<id>/<msg> só abre para quem já é membro: não carrega convite.
        raise LinkInvalido("link t.me/c/ é de chat privado e não serve para entrar")
    if primeiro.lower() in _RESERVADOS:
        raise LinkInvalido(f"t.me/{primeiro} não é canal nem grupo")
    # t.me/nome/123 (link de mensagem) também serve: o canal é o `nome`.
    if _USERNAME.match(primeiro):
        return Alvo("username", primeiro)
    raise LinkInvalido("username inválido")


def ler(texto):
    """Texto (um link por linha) -> (alvos únicos em ordem, [(linha, motivo)]).

    Linhas vazias e comentários (#) são ignorados; repetidos entram uma vez só.
    """
    alvos, vistos, invalidos = [], set(), []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        try:
            alvo = interpretar(linha)
        except LinkInvalido as e:
            invalidos.append((linha, str(e)))
            continue
        if alvo.chave not in vistos:
            vistos.add(alvo.chave)
            alvos.append(alvo)
    return alvos, invalidos
