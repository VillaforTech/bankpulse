# BankPulse Observability y negocio en vivo

Este stack es independiente del `compose.yaml` de la aplicacion y se conecta a la red externa `bankpulse-network`.

## Flujo verificado

`social-split-api` publica hechos confirmados en Redpanda. `business-analytics`
proyecta y conserva snapshots completos. `grafana-live-adapter` recupera las
revisiones posteriores a su cursor durable y publica InfluxDB line protocol en
`POST /api/live/push/bankpulse`. Grafana entrega el canal
`stream/bankpulse/business` al panel. No se envía JSON al endpoint Live.

Prometheus mantiene salud e historial técnico. No reemplaza el flujo Live y el
dashboard tiene el auto-refresh desactivado.

## 1. Levantar BankPulse con analítica

Desde la raíz del proyecto:

```bash
export ANALYTICS_COVERAGE_FROM=2026-09-16T00:00:00Z
docker compose -f compose.yaml -f compose.analytics.yaml up -d --build --wait
```

Use como `ANALYTICS_COVERAGE_FROM` el inicio UTC real de la población conocida.
No lo cambie sobre un volumen existente.

## 2. Levantar observabilidad

```bash
docker compose -f observability/compose.yaml up -d --build --wait
```

## 3. Abrir herramientas

- Grafana: http://localhost:3000
  - usuario: `admin`
  - clave demo: `bankpulse_demo`
- Prometheus: http://localhost:9090
- cAdvisor: http://localhost:8088
- Salud del adaptador dentro de la red: `http://grafana-live-adapter:8080/ready`

En Codespaces, use la pestana **Ports** para abrir los puertos 3000, 9090 y 8088.

## 4. Verificar targets

En Prometheus abra **Status > Targets**. Deben aparecer `payments-api`, `audit-api`, `cadvisor` y `prometheus` en estado UP.

## 5. Dashboard

Grafana aprovisiona automáticamente:

`Dashboards > BankPulse Lab > BankPulse Platform Overview`

`Dashboards > BankPulse Lab > BankPulse Deber 01 — Compromisos compartidos en vivo`

El segundo dashboard muestra:

- B-K1: `100 × cierres válidos / cierres` para la cohorte de 15 minutos; sin
  cierres muestra **SIN MUESTRA**, no cero.
- B-K2: suma de `abs(total − cuotas autorizadas)` por moneda.
- B-K3: cuotas autorizadas del backlog `OPEN` con edad mayor a 120 segundos.
- unidad, tamaño de muestra, revisión, evento/correlación, instante, calidad y
  estado de alerta de cada KPI.

Los estados de presentación son **ACTUAL**, **INCOMPLETO** y
**DESACTUALIZADO**. Dentro de ACTUAL, cada KPI distingue **SANO**,
**INCUMPLIDO** y **SIN MUESTRA**. El plugin vence localmente después de tres
segundos sin un snapshot/heartbeat; por ello una pantalla congelada no conserva
un verde válido.

## Bootstrap y reconexión

El cursor se guarda en el volumen `grafana-live-adapter-data` únicamente después
de que Grafana acepta el push. Al iniciar, el adaptador solicita
`/updates?after=N`; si está al día publica `/snapshot` como heartbeat completo.
Las revisiones viejas se ignoran. Si detecta un hueco, acepta el snapshot
completo más nuevo y contabiliza `recoveredGaps`; nunca combina campos de
revisiones distintas. Si el volumen de analítica fue reiniciado y la revisión
retrocede, el adaptador queda degradado para evitar presentar datos ambiguos.

Para probar reconexión sin borrar datos:

```bash
docker compose -f observability/compose.yaml stop grafana-live-adapter
docker compose -f observability/compose.yaml start grafana-live-adapter
docker compose -f observability/compose.yaml exec grafana-live-adapter \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/ready').read().decode())"
```

No use `down -v` si necesita conservar el cursor o la proyección.

## Validación del componente

```bash
python3 -m unittest discover -s services/grafana-live-adapter -p 'test_*.py' -v
docker compose -f observability/compose.yaml config --quiet
```

La aceptación final se coordina con #5: mínimo 100 operaciones correlacionadas,
valor realmente renderizado en los tres paneles, muestras crudas, p50/p95/máximo,
pérdidas, errores y capturas sano/rojo/recuperado. Una medición API-only no
acredita este dashboard.

Incluye disponibilidad de APIs, solicitudes HTTP, memoria JVM y CPU de contenedores.

## Incidente de demostracion

Desde la raiz:

```bash
docker compose stop mongo audit-api
```

Observe en Grafana que `Audit API UP` cambia a 0. Cree un pago para demostrar que payments-api continua trabajando y que el outbox retiene el evento.

Recupere:

```bash
docker compose up -d mongo audit-api
```

El target de audit-api vuelve a 1 y el mecanismo de outbox puede completar la entrega pendiente.

> cAdvisor depende del acceso al Docker daemon del host. En algunos entornos Codespaces/Docker remotos sus métricas pueden estar limitadas; las métricas Spring Boot/Prometheus siguen funcionando.

## Integrated verification

This branch includes the analytics component from PR #8 and targets `main`. Start the platform with `compose.yaml` and `compose.analytics.yaml`, setting `ANALYTICS_COVERAGE_FROM` to the actual start of a known population. Start Grafana and `grafana-live-adapter` from this directory’s Compose file. CI runs `scripts/analytics-integration.py` against the real producer, then `scripts/live-browser-test.cjs` in Chromium to verify rendering, stale state and recovery without reloading. Results and screenshots are saved under `artifacts/`. This check does not replace the separate 100-operation latency benchmark.
