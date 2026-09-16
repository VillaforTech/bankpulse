# Base de integración — BankPulse

Responsable #4: Roberto. La rama de aceptación integra #1/#2/#3/#5 sobre la base. La revisión humana y reproducción independiente siguen siendo necesarias.

## Arranque y pruebas

```bash
docker compose up --build -d --wait --wait-timeout 300
bash scripts/smoke-v2.sh
docker compose -f observability/compose.yaml up -d prometheus grafana
python3 -m unittest discover -s tests/infrastructure -v
```

Los repos comparten puertos publicados: usar Codespaces distintos o detener una plataforma antes de arrancar la otra. `docker compose down` conserva datos; no usar `down -v` sobre trabajo que se deba conservar.

## Contrato de infraestructura para el equipo

- Broker: `redpanda:9092`, topic `bankpulse.social-split.events.v1`, clave `aggregateId`, una partición y retención de 24 h para el entorno de desarrollo. El bootstrap es idempotente y no recrea topics existentes.
- Analítica #2: se acepta SQLite propio con WAL, volumen Linux y **una sola instancia** para este alcance. No necesita migrar a PostgreSQL para integrar. No lee tablas del productor. El gemelo usa otro almacenamiento; adaptar interfaces, no copiar su stack completo.
- Para iniciar analítica, usar `docker compose -f compose.yaml -f compose.analytics.yaml up --build -d --wait`. `ANALYTICS_COVERAGE_FROM` debe ser el inicio UTC real de una población conocida. No cambiarlo sobre una base existente ni inventar cobertura para datos previos.
- Analítica interna: `http://business-analytics:8000`, `/health`, `/ready`, `/snapshot`, `/updates?after=N`, `/stream?after=N`, `/metrics`. El volumen es exclusivo y persiste durante reinicios.
- #1 conserva su outbox y publica después del commit con eventId estable y aggregateVersion consecutiva. UTC debe conservar microsegundos. B-K3 cuenta cuotas autorizadas de sesiones OPEN con edad estrictamente mayor a 120 s; a los 120 s exactos todavía no vencen. B-K1/B-K2 usan cierres en [closedAt, closedAt + 900 s), por moneda cuando corresponde. Coordinar estas decisiones con la documentación del productor y los tests del consumidor.
- #3 conecta su adaptador al historial `/updates`; persiste la última revisión, recupera huecos y muestra calidad obsoleta tras 3 s sin actualización. Prometheus no sustituye Grafana Live.

## Gate y entrega de #5

El CI ejecuta unidades, compilación, despliegue, smoke, observabilidad y conserva artifacts antes de detener. `scripts/team-acceptance.sh` es obligatorio dentro del check de integración y por tanto de `Release gate`. **Archivo ausente, error, SKIPPED y medición parcial bloquean.** Ya no se permite el modo de base sin aceptación.

El benchmark de #5 conserva `--base-url` y `--out`; debe producir `measurementTarget=grafana-render`, requested/observed=100, lost=0, errors=[], p95Ms recalculable y 100 samples con correlationId único, rendered=true, correct=true, quality=FRESH, revision>0, latencyMs finito. El oráculo verifica los valores y la identidad de los tres paneles antes de escribir cada sample. El checker no convierte un booleano declarado en prueba visual: adjuntar captura y mediciones crudas del navegador. El runner actual usa Chromium, contrasta el evento con el outbox y verifica los tres paneles. El oráculo de B-K3 usa las sesiones OPEN y sus cuotas autorizadas; el consumidor de producción sigue siendo independiente de esa base.

El runner no acepta resiliencia SKIPPED: devuelve 0 solo cuando todos los escenarios pasan. Conserva fixtures y resultados; los oráculos no importan el calculador de producción. La reproducción completa está en [aceptación](deber-01.md).

## Orden para integrar

1. #10 ya contiene Social Split y la base de #9 en `main`.
2. #8 aporta analítica y #11 incorpora esa integración más Grafana Live.
3. #7 incorpora esas dependencias y el harness completo; revisar los PRs en ese orden para distinguir cada contribución.
4. El harness demuestra sano → mutación con salud UP → test rojo → corrección verde. La evidencia de un PR de regresión bloqueado en GitHub sigue siendo un paso separado.
5. Obtener revisión elegible y reproducir en Codespace limpio. La regla autorizada el 15 de septiembre exige una aprobación de otro colaborador con escritura; CODEOWNERS solo sugiere revisor. Se conservan todos los checks, la invalidación de aprobaciones y enforcement al administrador. Un PR propio no se autoaprueba.

Referencia: [gemelo](https://github.com/VillaforTech/bankpulse-reference). Código de referencia asistido por Codex; cada integrante conserva autoría y evidencia de su implementación.
