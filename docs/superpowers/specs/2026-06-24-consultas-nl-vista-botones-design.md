# Consultas en lenguaje natural → vista determinista con botones — Design Spec

- Fecha: 2026-06-24
- Estado: aprobado por Pablo (brainstorming 2026-06-24)

## Problema

`/hoy`, `/manana`, `/semana`, `/pendientes`, `/objetivos` son comandos deterministas
(`views.py`) que devuelven texto **+ botones inline** (marcar hecho, ver completados,
editar, etc.). Pero si el usuario escribe lo mismo en lenguaje natural ("qué tengo
hoy"), el mensaje va a `brain.handle_message` (Claude), que **solo produce texto** —
sin botones. Resultado: ve la info pero no puede marcar tareas ni ver completados.

## Objetivos

- Detectar consultas de resumen en lenguaje natural y servir la **misma vista
  determinista** del comando equivalente (con su teclado de botones).
- Cubrir las 5 vistas: hoy, mañana, semana, pendientes, objetivos.
- No interceptar órdenes de crear/accionar ("apunta reunión hoy") — esas siguen a la IA.

## No-objetivos

- **No tocar la voz.** Una transcripción ("qué tengo hoy" por audio) sigue yendo a la
  IA. Es raro pedir un resumen por voz y evita complejidad.
- **No tocar `brain.py` ni los `CommandHandler` existentes.** Solo se añade lógica en
  `_on_message` y una función de detección.
- **No IA para clasificar.** Detección por reglas (determinista, gratis, sin latencia).

## Arquitectura

### `bot.match_summary_view(text: str) -> Optional[str]`

Función pura. Devuelve `"hoy"|"manana"|"semana"|"pendientes"|"objetivos"` o `None`.

Pasos:
1. **Normalizar**: minúsculas, quitar tildes, quitar signos `¿ ? ¡ ! . ,` de los
   extremos, colapsar espacios.
2. **Excluir acciones**: si el texto contiene (como palabra) un verbo de
   creación/acción → `None`. Lista: `apunta, apuntame, anota, anade, añade, agrega,
   pon, ponme, mete, meteme, crea, creame, recuerda, recuerdame, avisa, avisame,
   marca, completa, hice, termine, acabe, borra, elimina, quita, cambia, edita,
   mueve, sincroniza, conecta, tengo que`.
3. **Exigir señal de consulta**: o bien EMPIEZA por uno de
   `que, qué, muestra, muestrame, ensename, enseñame, dame, ver, lista, listame`,
   o bien el texto completo ES una de las frases-clave:
   `hoy, manana, esta semana, semana, pendientes, mis pendientes, mis tareas, tareas,
   objetivos, mis objetivos, mis metas, metas, mi dia, mi semana, mi agenda, agenda,
   agenda de hoy, agenda de manana, que tengo`.
   Si no hay señal de consulta → `None`.
4. **Mapear a vista** por marcador (orden de prioridad):
   - contiene `pendiente`/`pendientes`/`tarea`/`tareas` → `pendientes`
   - contiene `objetivo`/`objetivos`/`meta`/`metas` → `objetivos`
   - contiene `semana` → `semana`
   - contiene `manana` → `manana`
   - contiene `hoy`/`dia`/`agenda` → `hoy`
   - si llegó aquí por "que tengo"/"mi agenda" sin marcador → `hoy` (default)

### `bot._render_summary_view(view_key, conn, today) -> (text, keyboard)`

Helper que mapea la clave a la función de `views.py` (reutiliza las existentes):
- `hoy` → `views.render_today_view(today, conn)`
- `manana` → `views.render_tomorrow_view(today + 1día, conn)`
- `semana` → `views.render_week_view(today, conn)`
- `pendientes` → `views.render_pending_view(conn)`
- `objetivos` → `views.render_objectives_view(today, conn)`

### Integración en `_on_message`

Al principio (tras obtener `text` y el `user_id`):
1. Si `user_id != ALLOWED_USER_ID` → return (no autorizado). *(hoy lo gestiona
   process_incoming devolviendo None; lo hacemos explícito aquí para la rama nueva.)*
2. `view = match_summary_view(text)`. Si `view` no es None:
   - `today = date_utils.today_madrid()`; `with db.connect()` → `_render_summary_view`.
   - `reply_text(text, HTML, keyboard)` y **return** (no pasa por la IA).
3. Si es None → flujo actual intacto (`process_incoming` → IA + botón calendar + etc.).

## Manejo de errores

- Si el render fallara (excepción inesperada), capturar, loguear y caer al flujo normal
  (mandar a la IA) para no dejar al usuario sin respuesta.

## Tests

### tests/test_bot.py — detección (función pura, muchos casos)
- `test_match_summary_view_hoy`: "qué tengo hoy", "que tengo hoy", "qué hay hoy",
  "qué tengo para hoy", "mi día", "agenda de hoy", "hoy" → "hoy".
- `test_match_summary_view_manana`: "qué tengo mañana", "mañana", "qué hay mañana" → "manana".
- `test_match_summary_view_semana`: "qué tengo esta semana", "mi semana" → "semana".
- `test_match_summary_view_pendientes`: "qué tengo pendiente", "mis tareas",
  "pendientes", "qué tareas tengo" → "pendientes".
- `test_match_summary_view_objetivos`: "mis objetivos", "objetivos de la semana",
  "qué objetivos tengo", "mis metas" → "objetivos".
- `test_match_summary_view_ignores_create`: "apunta reunión hoy a las 5",
  "mañana tengo dentista", "recuérdame comprar pan hoy", "marca leer como hecho",
  "tengo que hacer los objetivos" → None.
- `test_match_summary_view_unrelated`: "hola", "gracias", "cuánto es 2+2",
  "ponme una alarma" → None.

### tests/test_bot.py — integración (async)
- `test_on_message_natural_hoy_renders_view_with_keyboard`: con una tarea creada,
  un mensaje "qué tengo hoy" produce reply con teclado (mismo que /hoy) y NO llama a
  brain.
- `test_on_message_normal_text_still_goes_to_brain`: "cuéntame un chiste" → llama a
  brain (regresión: el flujo normal intacto).

## Migración y compatibilidad

Ninguna. Sin schema. Reusa renders existentes. Comandos y voz intactos.

## Riesgos

1. **Falsos negativos** (forma rara no detectada) → va a la IA, texto sin botones.
   No empeora respecto a hoy.
2. **Falsos positivos** (orden de crear tomada por consulta) → mitigado por la lista
   de verbos de acción y la exigencia de señal de consulta. Cubierto por tests.

## Métrica de éxito

Post-deploy, manual: escribir "qué tengo hoy" → sale la vista con botones idéntica a
/hoy, se pueden marcar tareas y ver completados. Ídem mañana/semana/pendientes/objetivos.
"apunta X hoy" sigue creando. Suite verde.
