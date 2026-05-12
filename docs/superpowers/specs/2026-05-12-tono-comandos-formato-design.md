# Tono, Comandos slash y Formato visual — Diseño

**Fecha:** 2026-05-12
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Sigue a:** mensajes de voz (2026-05-11-mensajes-de-voz-design.md)

## Objetivo

Tres mejoras pequeñas pero combinadas para que el bot sea más agradable y rápido de usar a diario:

1. **Tono motivador** (estilo coach personal).
2. **Comandos slash** para acciones frecuentes: `/hoy`, `/semana`, `/pendientes`, `/objetivos`.
3. **Formato visual** en respuestas (negritas + emojis para destacar) usando HTML de Telegram.

Filosofía: los tres cambios afectan a la "capa de presentación" y comportamiento conversacional. No tocan la lógica de dominio (eventos, tareas, objetivos) ni la base de datos. Bajo riesgo, mucho retorno en experiencia diaria.

## Decisiones clave

- **Personalidad:** coach personal motivador. Tutea siempre. Anima brevemente al cerrar tareas/objetivos. Sin ser cargante.
- **Comandos slash + lenguaje natural:** ambos disponibles. Los comandos slash se traducen internamente a una frase natural y pasan por el cerebro normal (no duplican lógica).
- **Formato:** HTML mode de Telegram (`parse_mode="HTML"`). Permite `<b>negrita</b>` y `<i>cursiva</i>` sin la complejidad de escape de Markdown V2.
- **Cuándo formatear:** el cerebro decide. Para resúmenes y listas largas: usa negritas para títulos de sección. Para confirmaciones cortas ("hecho, añadido"): texto plano.
- **Emojis con moderación:** 📅 eventos, 📝 tareas, 🎯 objetivos, 💪 ánimo, ✅ hecho. No uno por frase.

## Arquitectura

Tres archivos tocados:

- **`brain.py`:** se modifica el `_system_prompt()` para incluir el tono nuevo, las instrucciones de formato HTML y las plantillas mentales para los resúmenes. La función `handle_message` no cambia.
- **`bot.py`:**
  - Cambio en `_on_message` y `_on_voice`: añadir `parse_mode="HTML"` al `reply_text`.
  - 4 handlers nuevos para los comandos slash (`/hoy`, `/semana`, `/pendientes`, `/objetivos`).
  - Función `_register_bot_commands()` que llama a `bot.set_my_commands()` al arrancar para que el menú "/" en Telegram muestre las opciones.
- **Pequeña utilidad de escape** dentro de `bot.py` (o módulo compartido) para escapar `< > &` literales en datos del usuario antes de incluirlos en respuestas HTML. Solo aplica a entrada de usuario, no al texto generado por Claude.

No tocamos `tools.py`, `db.py`, `transcriber.py`, `date_utils.py`.

## Detalle de los comandos slash

Cada comando es un handler async que invoca `process_incoming(text=<frase_traducida>, from_user_id=update.effective_user.id)`. Pasa la respuesta por el cerebro como si el usuario hubiera escrito esa frase.

| Comando | Frase traducida que recibe el cerebro |
|---|---|
| `/hoy` | "Hazme el resumen de hoy: eventos del día + tareas pendientes." |
| `/semana` | "Hazme el resumen de la semana: eventos próximos + objetivos." |
| `/pendientes` | "Lista mis tareas pendientes." |
| `/objetivos` | "¿Cómo van mis objetivos de esta semana?" |

Y los comandos ya existentes (`/nueva`, `/reset`, `/clear`) siguen funcionando como ahora — limpiar la memoria conversacional.

## Detalle del system prompt actualizado

El prompt actual conserva las reglas críticas existentes (consultar BD antes de afirmar, pedir confirmación antes de borrar, etc.). Se añaden estas secciones:

```
Personalidad y tono:
- Eres el coach personal de organización de Pablo. Tuteas siempre.
- Cercano, motivador, con humor sano cuando encaja. NUNCA distante ni acartonado.
- Cuando Pablo termine una tarea u objetivo, anímalo brevemente.
- Cuando le quedan muchas cosas pendientes, no abrumes — ayúdale a verlas en perspectiva.

Formato de las respuestas:
- Telegram renderiza HTML. Usa <b>texto</b> para negritas e <i>texto</i> para cursivas.
- Confirmaciones cortas: texto plano sin formato.
- Resúmenes y listas: usa títulos de sección en negrita y bullets con "•".
- Emojis con moderación: 📅 eventos, 📝 tareas, 🎯 objetivos, 💪 ánimo, ✅ hecho.

Plantilla para resúmenes (ajústala si hace falta, no es obligatoria):

📅 <b>HOY</b>

• 09:00 — Reunión equipo
• 17:00 — Cita médico

📝 <b>PENDIENTES</b>

• Comprar pan
• Llamar fontanero

💪 [Cierre breve motivador opcional]

Cuando no haya nada en una sección, o la omites o pones "Nada por aquí".
```

## Manejo de caracteres especiales en HTML

Cuando Telegram recibe un mensaje con `parse_mode="HTML"`, los caracteres `<`, `>` y `&` se interpretan como HTML. Si Pablo añade un evento con texto literal `<algo>` (raro pero posible), al mostrarlo el render fallaría.

Solución: el cerebro recibe el system prompt con instrucción de **escapar entidades en texto generado por el usuario**. Pero como Claude no siempre lo hará de forma fiable, **redoblamos protección** con una función auxiliar en `bot.py` que escapa entidades sospechosas en la respuesta final si detecta `<` o `>` no formado como tag válido. En la práctica, esto rara vez se dispara.

Versión simple para el MVP: confiamos en que Claude siga la instrucción del prompt. Si en pruebas reales aparecen problemas, añadimos la función defensiva.

## Tests

1. `brain._system_prompt()` contiene las nuevas instrucciones de tono y formato.
2. `bot.process_slash_command("/hoy", user_id)` → llama al cerebro con la frase traducida. Idem para `/semana`, `/pendientes`, `/objetivos`.
3. `bot.process_slash_command("/comando_inexistente", user_id)` → devuelve None o pasa al flujo normal (probablemente devuelve None y el comando se ignora).
4. Handler async de slash (vía mock de `update.message`): se llama a `reply_text` con `parse_mode="HTML"`.
5. Test de regresión: los mensajes de texto normales y de voz **siguen funcionando** con el nuevo `parse_mode`.

## Compatibilidad con la conversación existente

Cualquier mensaje en el historial de Telegram que ya hayas tenido seguirá ahí como está. Solo los **mensajes nuevos** del bot tendrán el formato y tono nuevo.

La memoria conversacional (en RAM) tampoco se pierde: solo se renueva el prompt del sistema cuando el cerebro procesa un mensaje nuevo. Las respuestas anteriores que el cerebro tiene en memoria son del tono viejo, pero conforme avanzas las nuevas serán del tono nuevo.

## Fuera del alcance

- ❌ Formato Markdown V2 (más complejo de mantener; HTML basta).
- ❌ Botones inline / teclados (Telegram permite `reply_markup` con botones, pero no es necesario; los slash commands ya dan acceso rápido).
- ❌ Imágenes / gráficos de progreso.
- ❌ Personalización del tono por parte del usuario ("hazme menos motivador"). Si después molesta, se ajusta el prompt manualmente.

## Criterios de éxito

- Las respuestas del bot llegan con negritas reales y emojis renderizados en Telegram móvil.
- Cuando escribo `/hoy`, obtengo un resumen del día con secciones tipo `📅 HOY` y `📝 PENDIENTES`.
- Cuando completo una tarea u objetivo, el bot me anima brevemente.
- Los mensajes de texto y de voz normales siguen funcionando.
- Los tests pasan.
