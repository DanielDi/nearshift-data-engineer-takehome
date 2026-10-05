# Guion de demostración (3 minutos)

1. Abrir [`showcase/index.html`](showcase/index.html). Aclarar que los datos son Olist 2016–2018 y que el tablero funciona sin servicios externos.
2. Mostrar los cuatro indicadores: R$ 13.221.498,11 de mercancía entregada, 96.478 pedidos, AOV R$ 137,04 y recompra 3,00 %. La métrica de valor excluye flete y reembolsos no observados.
3. En **Tendencias**, alternar entre valor mensual y AOV. Seleccionar noviembre de 2017 para mostrar el pico de R$ 987.765,37. Explicar que el gráfico omite los meses limítrofes con cobertura escasa, aunque estos permanecen en el mart y el CSV.
4. Mostrar el ranking de categorías y las señales de entrega: 6,77 % de pedidos entregados tarde entre los que tienen fechas comparables.
5. En **Consultas guiadas**, elegir una pregunta. La respuesta muestra valor, denominador cuando aplica y tabla curada.
6. Ir a **Solución**. Seguir el diagrama de cinco capas: CSV → raw → hechos/dimensiones → marts → web/API/GPT. Explicar dos decisiones: agregar artículos y pagos antes del join evita duplicar importes; usar `customer_unique_id` permite medir recompra real. La sección incluye otros cuatro riesgos y sus soluciones, más un guion oral de un minuto.
7. Abrir **Validación** y `reports/VALIDATION.md` para mostrar las 25 verificaciones y las diferencias de pagos conservadas como excepciones.
8. Si hay créditos API, iniciar `python showcase_server.py` y preguntar por un mes en lenguaje natural. GPT selecciona una de cinco métricas; el servidor ejecuta SQL fijo de solo lectura y construye la respuesta con datos del mart. Si no hay créditos, la demo guiada sigue disponible.

## Qué demuestra la solución

- Ingesta reproducible y modelo con granos explícitos para órdenes, artículos y pagos.
- Definiciones de métricas y diferencias frente a pagos contables documentadas.
- Validación automática antes de generar los reportes y el tablero.
- Entregable autónomo que se puede abrir desde el ZIP y una extensión GPT acotada a los datos solicitados.
