"""Spanish publishing titles for the HVAC topics written in English."""

SPANISH_TITLES = {
    "How a building automation system reads zone temperature and adjusts a VAV damper":
        "Cómo un sistema de automatización lee la temperatura de zona y ajusta una compuerta VAV",
    "What an energy management system does with occupancy schedules after hours":
        "Qué hace un sistema de gestión de energía con los horarios fuera de ocupación",
    "How a chilled-water valve responds when supply-air temperature leaves its setpoint":
        "Cómo responde una válvula de agua helada cuando el aire de suministro sale de su ajuste",
    "Why an HVAC economizer checks outdoor enthalpy before opening the outside-air damper":
        "Por qué un economizador revisa la entalpía exterior antes de abrir el aire exterior",
    "How a BAS keeps unoccupied floors from being cooled overnight":
        "Cómo un BAS evita enfriar pisos desocupados durante la noche",
    "What a supply-air temperature reset does for chiller energy in an EMS":
        "Qué hace el reinicio del aire de suministro por la energía del chiller en un EMS",
    "How a pressure-independent VAV box holds airflow when duct pressure changes":
        "Cómo una caja VAV mantiene el flujo cuando cambia la presión del ducto",
    "Why a hot-water reset curve lowers boiler temperature in mild weather":
        "Por qué una curva de reinicio baja la temperatura de la caldera en clima templado",
    "How a BAS proves a fan is running before it enables a heating coil":
        "Cómo un BAS comprueba que el ventilador gira antes de habilitar la calefacción",
    "What demand limiting means when an energy management system sheds HVAC load":
        "Qué es la limitación de demanda cuando el sistema reduce la carga de HVAC",
    "How a conference-room CO2 sensor increases outdoor air through the BAS":
        "Cómo un sensor de CO2 aumenta el aire exterior a través del BAS",
    "Why a freeze stat stops a coil and closes the outside-air damper":
        "Por qué un freeze stat detiene un serpentín y cierra la compuerta de aire exterior",
    "How an EMS trend log shows a heating valve that stayed open overnight":
        "Cómo un registro del EMS muestra una válvula de calefacción abierta toda la noche",
    "What static-pressure reset does for supply fans in a VAV system":
        "Qué hace el reinicio de presión estática por los ventiladores de un sistema VAV",
    "How a BAS morning warmup ends when the zone reaches the occupied setpoint":
        "Cómo termina el calentamiento matutino cuando la zona llega al ajuste ocupado",
    "Why condenser-water temperature reset saves chiller energy in cool weather":
        "Por qué el reinicio del agua del condensador ahorra energía del chiller en clima fresco",
    "How an occupancy sensor releases a VAV box to its unoccupied airflow":
        "Cómo un sensor de ocupación libera una caja VAV a su flujo desocupado",
    "What a building automation alarm does when a pump fails to prove flow":
        "Qué hace una alarma de automatización cuando una bomba no comprueba el flujo",
}

_SPANISH_WORDS = {
    "el", "la", "los", "las", "de", "del", "que", "en", "un", "una",
    "por", "como", "cómo", "qué", "para", "con", "al",
}


def _looks_spanish(text):
    words = {word.strip(".,;:!?¿¡").lower() for word in str(text or "").split()}
    return len(words & _SPANISH_WORDS) >= 2


def display_title(topic, language, narration=""):
    """English videos keep the stored topic. Spanish videos get a Spanish title."""
    topic = " ".join(str(topic or "").split())
    if str(language or "").lower() != "es":
        return topic
    return spanish_title(topic, narration)[:100]


def spanish_title(topic, narration=""):
    """Use a Spanish title when the video is spoken in Spanish."""
    topic = " ".join(str(topic or "").split())
    mapped = SPANISH_TITLES.get(topic)
    if mapped:
        return mapped
    narration = " ".join(str(narration or "").split())
    sentence = narration
    for mark in (".", "?", "!"):
        at = sentence.find(mark)
        if at > 20:
            sentence = sentence[:at]
            break
    sentence = sentence[:100].rstrip()
    if sentence and _looks_spanish(sentence) and not _looks_spanish(topic):
        return sentence
    return topic
