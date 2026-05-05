# Pull Request

## Descripción del cambio
<!-- ¿Qué hace este PR y por qué? Una o dos frases. Si arregla un bug, enlaza el issue. -->

## Tipo
- [ ] feat — nueva funcionalidad
- [ ] fix — corrección de bug
- [ ] refactor — cambio interno sin alterar comportamiento observable
- [ ] perf — mejora de rendimiento
- [ ] docs — documentación
- [ ] test — solo tests
- [ ] chore — tooling, deps, CI

## Módulos afectados
<!-- Marca los paquetes tocados. Si son más de tres, plantea si vale la pena partir el PR. -->
- [ ] `core/`
- [ ] `models/`
- [ ] `memory/`
- [ ] `perception/`
- [ ] `actions/`
- [ ] `mcp_servers/`
- [ ] `security/`
- [ ] `interface/`
- [ ] `config/`
- [ ] `tests/`
- [ ] `infra` (docker, Makefile, CI, .env.example)

## Tests añadidos
<!-- Lista de archivos de test nuevos o modificados. Si no hay tests, justifica por qué. -->
- `tests/...`

## Cobertura
- [ ] `make test` pasa en local
- [ ] Cobertura no baja en los módulos modificados
- [ ] Tests cubren los caminos de error, no solo el camino feliz

## Impacto en seguridad
<!-- Responde aunque sea con "ninguno". -->
- ¿Toca secrets, auth, sandbox, audit log o validación de input? **Sí / No**
- ¿Modifica `core/router.py` o las heurísticas de privacidad? **Sí / No**
- ¿Añade nuevas dependencias externas? **Sí / No** (si sí, lista cuáles y por qué)
- ¿Se ha ejecutado `@security-reviewer`? **Sí / No / N/A**

## Impacto en memoria/rendimiento
<!-- Recordatorio: el target es Mac M3 con 8GB RAM. -->
- ¿Carga modelos LLM en RAM al arrancar? **Sí / No**
- ¿Mantiene buffers/cachés sin límite? **Sí / No**
- ¿Hace I/O síncrono en paths del event loop? **Sí / No**
- ¿Añade un servicio docker nuevo? **Sí / No** (si sí, footprint en RAM)

## Checklist
- [ ] Type hints completos (`mypy --strict` pasa)
- [ ] Docstrings en español en funciones públicas
- [ ] No hay `print()` ni `eval()` ni `shell=True` sin sandbox
- [ ] No se commitea `.env`, claves o datos del vault
- [ ] `.env.example` actualizado si añadiste variables nuevas
- [ ] CHANGELOG actualizado si es un cambio user-facing

## Notas para el reviewer
<!-- Contexto que ayude a leer el diff: decisiones que considerarías raras, alternativas descartadas, work-in-progress, etc. -->
