# Revisión de código — 2026-06-24

> **ACTUALIZACIÓN 2026-06-24:** Pablo pidió "soluciona todos". Los 7 hallazgos
> (🔴🟡⚪) están RESUELTOS y desplegados, cada uno con tests. Resumen al final.
> El detalle de cada uno queda abajo como referencia.


Dos revisiones autónomas (3 agentes) sobre todo el proyecto. Lo que **ya arreglé**
queda al final. Esto es lo **pendiente de tu decisión** — son bugs PRE-existentes
(no de hoy); no los toqué porque afectan a la lógica de XP/recordatorios que "tenéis
fina" y prefiero que des el OK antes de tocarla.

Prioridad: 🔴 alta · 🟡 media · ⚪ baja/dudoso.

---

## 🔴 1. El bonus de "día perfecto" (+20 XP) no se revierte al desmarcar
**Dónde:** `tools.py` — `_check_and_award_perfect_day` y los `uncomplete_*`/`unmark_*`.
**Qué pasa:** marcas la última cosa del día → +20 XP por día perfecto. Si luego
**desmarcas** ese ítem, se revierte su XP base pero **los +20 se quedan**. El día ya
no es perfecto, pero el XP/nivel conserva el bonus. Resultado: XP inflado de forma
permanente, y el resultado depende del orden en que marcas/desmarcas.
**Recomendación:** en los `uncomplete_*`/`unmark_*`, si el día deja de ser perfecto,
revertir también la fila `perfect_day` de hoy. Requiere recomputar "¿sigue siendo
día perfecto?" tras desmarcar. ~1-2h con tests.

## 🔴 2. Doble reversión de XP si se desmarca dos veces seguidas
**Dónde:** `tools.py` — `uncomplete_task`/`unmark_event_done`/`uncomplete_routine_today`/`unmark_objective_done`.
**Qué pasa:** la reversión coge "la última fila de XP no-reversal" y mete una fila
negativa. No comprueba si esa ganancia ya fue revertida. Si el botón de desmarcar se
pulsa dos veces (doble tap, reintento de Telegram), mete **dos** filas negativas → el
XP baja el doble.
**Recomendación:** hacer la reversión idempotente (marcar la ganancia como ya
revertida, o comprobar que no exista ya su reversión antes de insertar). ~1h con tests.

## 🟡 3. Un recordatorio personalizado puede duplicarse si falla el marcado
**Dónde:** `scheduler.py` `check_reminders` (envío) + marcado `sent=1`.
**Qué pasa:** primero se envía el mensaje y **después**, en otra conexión, se marca
`sent=1`. Si ese marcado falla (BD bloqueada un instante, crash), el aviso ya salió
pero `sent` sigue a 0 → en la pasada siguiente (5 min) se reenvía. Recordatorio
duplicado.
**Recomendación:** marcar `sent=1` **antes** de enviar (o en la misma transacción), o
tolerar el reenvío. Riesgo real bajo (la BD local rara vez falla), pero existe.

## 🟡 4. Un recordatorio "imposible" deja al evento SIN ningún aviso
**Dónde:** `tools.py` `add_event_reminder` + `scheduler.py` (defaults desactivados si
hay custom).
**Qué pasa:** si creas un evento para dentro de pocas horas y pides "avísame **1 semana
antes**", ese aviso ya es imposible (la fecha de aviso ya pasó) → se guarda como
"enviado" y nunca avisa. Y como hay un recordatorio custom, los avisos por defecto
(1h/1d antes) **se desactivan**. Resultado: ese evento no te avisa de nada.
**Recomendación:** si un custom es imposible al crearlo, no desactivar los defaults
(o avisar al usuario "ese aviso ya no llega a tiempo"). ~1h.

## 🟡 5. Las respuestas no están protegidas: si falla el envío, mutas pero no avisas
**Dónde:** `bot.py` `_on_message`/`_on_voice` — el `reply_text` final.
**Qué pasa:** el `try/except` cubre la lógica (crear tarea, etc.) pero NO el envío de
la respuesta. Si el `reply_text` falla (HTML mal formado de la IA, mensaje >4096
caracteres), la tarea **ya se creó** pero tú ves un fallo (o nada). Crees que no se
guardó y lo repites → duplicado.
**Recomendación:** envolver el envío final en try/except con un fallback (reintentar
sin HTML, o mensaje corto). ~30 min. Bajo riesgo, defensivo.

## ⚪ 6. `weeks_diff` permite marcar objetivos de una semana futura como "a tiempo"
**Dónde:** `tools.py` `mark_objective_done`.
**Qué pasa:** si un objetivo tiene `week_start` en el futuro, el cálculo da XP
`on_time`. Marcar hoy un objetivo de la semana que viene daría XP indebido. Muy poco
probable en uso real.
**Recomendación:** tratar semana futura como caso aparte (no dar XP o avisar). Menor.

## ⚪ 7. `datetime.now()` naive en el scheduler
**Dónde:** `scheduler.py check_reminders`.
**Qué pasa:** usa `datetime.now()` directo en vez de `date_utils.now_madrid_naive()`.
Funciona en producción porque el Dockerfile fija `TZ=Europe/Madrid`. Pero si algún
día se ejecuta sin esa variable, los recordatorios se desfasarían 1-2h. Frágil.
**Recomendación:** usar `date_utils.now_madrid_naive()` por coherencia. Trivial.

---

## ✅ Ya arreglado hoy (no requiere acción)
- Detección NL demasiado laxa: "qué tengo que hacer hoy" ahora funciona; "qué compro
  hoy" / "ver si puedo mañana" ya no dan vista por error. (commit del 2026-06-24)
- Guarda de `update.effective_user` None en `_on_message`.
- (De días previos) `/cancelar` en edición, edición por voz, cap del undo store,
  validación de `due_date`, etc.

## Estado general
El núcleo está sano. Ningún hallazgo es pérdida de datos crítica (el XP es "juego", no
datos esenciales). Los 🔴 1 y 2 corrompen el contador de XP con el tiempo; los 🟡 son
casos borde. Mi sugerencia de orden si quieres que los aborde: **2 → 1 → 3 → 5 → 4**,
y los ⚪ cuando apetezca.

---

## ✅ RESOLUCIÓN (2026-06-24) — los 7 resueltos

| # | Hallazgo | Cómo se resolvió |
|---|----------|------------------|
| 🔴 1 | Bonus día perfecto no se revertía | `_revert_perfect_day_if_broken` en uncomplete/unmark de tarea/evento/rutina; idempotencia del bonus por NETO |
| 🔴 2 | Doble reversión de XP | `_revert_last_gain` idempotente (solo revierte si la última fila es ganancia) |
| 🟡 3 | Recordatorio duplicado si falla el marcado | Marcar `sent`/`reminder_*_sent` ANTES de enviar |
| 🟡 4 | Recordatorio imposible anulaba los defaults | No se persiste el imposible; se entrega al momento y los defaults siguen activos |
| 🟡 5 | Respuesta sin proteger | `_safe_reply`: reintenta en texto plano si el HTML falla |
| ⚪ 6 | Objetivo de semana futura | Documentado como intencional (logro adelantado = on_time) + test |
| ⚪ 7 | `datetime.now()` naive en scheduler | `date_utils.now_madrid_naive()` |

Suite: **519/519**. Todo desplegado.
