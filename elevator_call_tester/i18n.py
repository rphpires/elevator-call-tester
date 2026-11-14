"""UI strings in English and Brazilian Portuguese. Logs stay in English."""

from __future__ import annotations

import locale
import os

LANGUAGES = {"en": "English", "pt_BR": "Português (Brasil)"}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app.title": "Elevator Call Tester",
        "language": "Language",
        "driver": "Elevator protocol",
        "conn.box": "Connection",
        "conn.type": "Connection type",
        "conn.serial": "Serial (Modbus RTU)",
        "conn.tcp": "IP converter (TCP)",
        "conn.port": "Serial port",
        "conn.refresh": "Refresh",
        "conn.serial_settings": "Line settings: {settings}",
        "conn.host": "Converter IP",
        "conn.tcp_port": "TCP port",
        "conn.framing": "Converter type",
        "framing.auto": "Detect automatically",
        "framing.mbap": "Modbus TCP gateway",
        "framing.rtu": "Transparent (raw RTU)",
        "conn.connect": "Connect",
        "conn.disconnect": "Disconnect",
        "conn.connected": "Connected",
        "conn.disconnected": "Not connected",
        "conn.busy": "Working...",
        "call.box": "Call",
        "call.origin": "Origin floor",
        "call.destination": "Destination floor",
        "call.send": "Place call",
        "call.accepted": "Call accepted",
        "call.failed": "Call failed",
        "log.box": "Log",
        "log.clear": "Clear",
        "log.open_folder": "Open log folder",
        "log.no_file": "File logging is disabled.",
        "help": "Help",
        "about": "About",
        "about.text": (
            "Elevator Call Tester {version}\n\n"
            "Bench and field tool to place elevator destination calls and inspect the frames on the wire.\n\n"
            "Not affiliated with, or endorsed by, any elevator manufacturer. "
            "Manufacturer names are trademarks of their owners and are used only to identify protocols."
        ),
        "footer.author": "Developed by Raphael Pires",
        "error": "Error",
        "tke.unit_id": "Gateway address",
        "tke.unit_id.help": (
            "Modbus slave address of the elevator interface (1-247).\n\n"
            "Serial: first byte of the RTU frame. Modbus TCP gateway: the unit id in the MBAP header, "
            "which the gateway uses to address the slave on its serial side."
        ),
        "tke.device": "Device",
        "tke.device.help": "Number of the device (terminal / reader) at the origin floor, as configured "
        "in the elevator system.",
        "tke.floor_offset": "Floor offset",
        "tke.floor_offset.help": (
            "Subtracted from origin and destination floors before sending, to match the access control "
            "floor numbering with the elevator's.\n\n"
            "Example: offset -2 turns floor 1 into 3 for the elevator."
        ),
        "tke.mco_map": "Destination MCOs",
        "tke.mco_map.help": (
            "Which MCO serves each destination floor.\n\n"
            "Format: 1:4,6,7-18;2:20-99\n"
            "MCO 1 serves floors 4, 6 and 7 to 18; MCO 2 serves 20 to 99.\n\n"
            "An entry without floors (e.g. 2) is the default for any floor not listed. "
            "Negative floors are allowed: 1:-2-5 means -2 to 5."
        ),
        "tke.message": "Display message",
        "tke.message.help": (
            "Text code shown on the elevator terminal display.\n\n"
            "Automatic: 'already on this floor' when origin equals destination, otherwise none."
        ),
        "tke.message.auto": "Automatic",
        "tke.message.none": "None (0)",
        "tke.message.already_on_floor": "Already on this floor (2)",
        "tke.message.access_denied": "Access denied (11)",
    },
    "pt_BR": {
        "app.title": "Elevator Call Tester",
        "language": "Idioma",
        "driver": "Protocolo do elevador",
        "conn.box": "Conexão",
        "conn.type": "Tipo de conexão",
        "conn.serial": "Serial (Modbus RTU)",
        "conn.tcp": "Conversor IP (TCP)",
        "conn.port": "Porta serial",
        "conn.refresh": "Atualizar",
        "conn.serial_settings": "Configuração da linha: {settings}",
        "conn.host": "IP do conversor",
        "conn.tcp_port": "Porta TCP",
        "conn.framing": "Tipo de conversor",
        "framing.auto": "Detectar automaticamente",
        "framing.mbap": "Gateway Modbus TCP",
        "framing.rtu": "Transparente (RTU cru)",
        "conn.connect": "Conectar",
        "conn.disconnect": "Desconectar",
        "conn.connected": "Conectado",
        "conn.disconnected": "Não conectado",
        "conn.busy": "Aguarde...",
        "call.box": "Chamada",
        "call.origin": "Andar de origem",
        "call.destination": "Andar de destino",
        "call.send": "Fazer chamada",
        "call.accepted": "Chamada aceita",
        "call.failed": "Chamada falhou",
        "log.box": "Log",
        "log.clear": "Limpar",
        "log.open_folder": "Abrir pasta de logs",
        "log.no_file": "Gravação de log em arquivo desativada.",
        "help": "Ajuda",
        "about": "Sobre",
        "about.text": (
            "Elevator Call Tester {version}\n\n"
            "Ferramenta de bancada e campo para disparar chamadas antecipadas de elevador e conferir "
            "os quadros no fio.\n\n"
            "Sem qualquer relação com os fabricantes de elevadores. Os nomes dos fabricantes são marcas "
            "de seus donos e aparecem só para identificar os protocolos."
        ),
        "footer.author": "Desenvolvido por Raphael Pires",
        "error": "Erro",
        "tke.unit_id": "Endereço do gateway",
        "tke.unit_id.help": (
            "Endereço de escravo Modbus da interface do elevador (1-247).\n\n"
            "Serial: primeiro byte do quadro RTU. Gateway Modbus TCP: o unit id do cabeçalho MBAP, que o "
            "gateway usa para endereçar o escravo do lado serial."
        ),
        "tke.device": "Dispositivo",
        "tke.device.help": "Número do dispositivo (terminal / leitora) no andar de origem, como configurado "
        "no sistema do elevador.",
        "tke.floor_offset": "Ajuste de pavimento",
        "tke.floor_offset.help": (
            "Subtraído dos andares de origem e destino antes do envio, para casar a numeração do controle "
            "de acesso com a do elevador.\n\n"
            "Ex.: ajuste -2 faz o andar 1 virar 3 para o elevador."
        ),
        "tke.mco_map": "MCOs de destino",
        "tke.mco_map.help": (
            "Qual MCO atende cada andar de destino.\n\n"
            "Formato: 1:4,6,7-18;2:20-99\n"
            "MCO 1 atende os andares 4, 6 e 7 a 18; MCO 2 atende 20 a 99.\n\n"
            "Uma entrada sem andares (ex.: 2) vale como padrão para qualquer andar não listado. "
            "Andares negativos são aceitos: 1:-2-5 vai de -2 a 5."
        ),
        "tke.message": "Mensagem no display",
        "tke.message.help": (
            "Código de texto mostrado no display do terminal do elevador.\n\n"
            "Automático: 'já está no andar' quando origem e destino são iguais; senão, nenhuma."
        ),
        "tke.message.auto": "Automático",
        "tke.message.none": "Nenhuma (0)",
        "tke.message.already_on_floor": "Já está no andar (2)",
        "tke.message.access_denied": "Acesso negado (11)",
    },
}


def detect_language() -> str:
    """pt_BR for a Portuguese system locale, English otherwise."""
    candidates = [os.environ.get(var, "") for var in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    if os.name == "nt":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            candidates.append("pt" if lang_id & 0x3FF == 0x16 else "")  # LANG_PORTUGUESE
        except (AttributeError, OSError):
            pass
    for value in candidates:
        if value.lower().startswith(("pt", "portuguese")):
            return "pt_BR"
    return "en"


class Translator:
    def __init__(self, language: str = "en"):
        self.language = language if language in STRINGS else "en"

    def __call__(self, key: str, **kwargs: object) -> str:
        text = STRINGS[self.language].get(key) or STRINGS["en"].get(key) or key
        return text.format(**kwargs) if kwargs else text
