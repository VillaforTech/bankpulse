# Evidencia del bloqueo de Social Split

Capturada el 16 de septiembre de 2026 antes de publicar la corrección.

- Repositorio: https://github.com/VillaforTech/bankpulse
- PR: https://github.com/VillaforTech/bankpulse/pull/13
- Commit defectuoso: `b78d9a6733c19967fd2e77a024b2b2d913091ac7`
- CI: https://github.com/VillaforTech/bankpulse/actions/runs/35150381217
- Commit correctivo: `16389a07775064078e1dfbe6eacf58242c19da24`
- CI correctivo: https://github.com/VillaforTech/bankpulse/actions/runs/35158251443

`mutation.diff` elimina una validación de negocio sin cambiar pruebas. `business-red.log` muestra readiness correcto y el cierre inconsistente aceptado. `containers-red.txt` conserva el estado de los contenedores antes del teardown. `blocked-pr.json` registra los checks rojos y el estado bloqueado; `branch-protection.json` demuestra que Release gate e integración son obligatorios con protección aplicada a administradores. El PR también carecía de aprobación: es un requisito adicional, no la causa del fallo de negocio.

La ejecución de GitHub conserva además logs completos y capturas del dashboard en `integration-evidence`. Para repetir localmente la falla y recuperación en un entorno desechable, seguir `docs/deber-01.md`: el harness crea una imagen mutada temporal, ejecuta las mismas pruebas, conserva los datos y restaura la imagen sana. No fusionar la revisión defectuosa para demostrar el bloqueo.
