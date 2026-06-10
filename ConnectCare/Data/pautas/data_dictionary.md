# Pautas de mantenimiento consolidadas — diccionario de datos

Consolidación y parametrización de los **7 cronogramas** de mantenimiento Mercedes-Benz
en un único dataset apto para que un modelo de ML lo consuma y aplique.

## Archivos

| Archivo | Contenido |
|---|---|
| `pautas_mantencion_consolidado.csv` | Tabla larga (*tidy*): **una fila = un evento de servicio** para una combinación modelo × perfil de operación × métrica. 1.132 filas. **Esta es la tabla principal para ML.** |
| `pautas_mantencion_consolidado.json` | Estructura anidada: metadatos, secuencias completas por modelo, tiempos de trabajo, tolerancias, reglas y notas. |
| `build_pautas.py` | Generador reproducible (vuelve a crear los dos anteriores). |

## Modelos incluidos

| Modelo | Chasis | Norma | Origen | Versión pauta | Eventos | Perfiles |
|---|---|---|---|---|---|---|
| Arocs 964 | 964 | Euro V-VI | Alemán | Julio 2024 | 26 | 7 |
| New Actros 963.4 / 964.4 | WDB/W1T 963.4 / 964.4 | Euro V-VI | Alemán | Febrero 2026 | 26 | 7 |
| New Actros Brasil 963.4 | 9BM963.4 / W1T963.4 | Euro V | Brasil | Mayo 2025 | 16 | 6 |
| Actros WDB 930/932/934 | WDB 930, 932, 934 | Euro IV-V | Alemán | v1.6 (Nov 2019) | 49 | 5 |
| Arocs 964 Brasil | 964 (Brasil) | Euro V | Brasil | Marzo 2025 | 26 | 7 |
| Axor WDF 942/944/950/952 | WDF 942/944/950/952 | Euro V | Alemán | v1.1 (Jun 2017) | 25 | 5 |
| Axor 9BM/WDB | WDB 940…954.5, 9BM 958.2/958.4 | Euro IV-V | Brasil | Diciembre 2025 | 24 | 5 |

## Columnas del CSV

| Columna | Tipo | Descripción |
|---|---|---|
| `marca` | str | Siempre `Mercedes-Benz`. |
| `familia` | str | `Arocs`, `New Actros`, `Actros` o `Axor`. |
| `modelo` | str | Identificador del modelo (clave de agrupación). |
| `chasis` | str | Código(s) de chasis. |
| `norma_euro` | str | Norma de emisiones. |
| `origen` | str | `Aleman (Europa)` o `Brasil`. |
| `version_pauta` | str | Versión/fecha del cronograma fuente. |
| `perfil_operacion` | str | `severo`, `mixto`, `carretero`, `forestal`, `mixer`, `mixto_mixer`. Condición de uso que define la frecuencia. |
| `metrica` | str | `km` u `horas`: variable que dispara el servicio. |
| `unidad` | str | `km` o `h`. |
| `evento_secuencia` | int | Posición ordinal del evento en la secuencia (1 = primero). |
| `servicio_codigo` | str | `SI`, `SL*`, `SM1`…`SM6`. |
| `servicio_nombre` | str | Nombre legible del servicio. |
| `valor_acumulado` | int | **Km u horas acumulados** a los que se ejecuta el servicio. Los km ya vienen multiplicados (el PDF los expresa "x 1.000"). |
| `intervalo_incremental` | int | Km u horas transcurridos desde el evento anterior del mismo perfil (el "cada cuánto" real). |
| `tiempo_trabajo_h` | float | Horas de trabajo mínimas de mano de obra para ese tipo de servicio. |
| `ciclo_mantenimiento` | str | Descripción del patrón cíclico de la secuencia. |
| `tolerancia_dias` | int | Margen máximo de tiempo en días (`90` en pautas tipo A; vacío en tipo B, que sólo usan los 12 meses). |
| `tolerancia_km` | int | Margen máximo absoluto de km (`1000` en pautas Brasil/Axor 9BM; vacío en el resto). |
| `tolerancia_pct` | int | `10`. Margen máximo porcentual sobre km/horas. |
| `intervalo_max_meses` | int | `12`. Tope por calendario. |
| `requiere_aceite_mineral` | bool | `True` solo en eventos `SL*` (aplican únicamente a motores con aceite mineral). |

> **Dos reglas de tolerancia.** *Tipo A* (Arocs/New Actros alemanes, Actros WDB, Axor WDF):
> 90 días o 10 % de km/horas. *Tipo B* (New Actros Brasil, Arocs Brasil, Axor 9BM/WDB):
> 12 meses o 1.000 km o 10 % de horas. En ambos: *lo primero que se cumpla*.

## Cómo lo aplica un modelo / motor de reglas

1. Filtrar por `modelo` y por el `perfil_operacion` del camión (según su uso real).
2. Elegir la `metrica` disponible del telemétrico: `km` (odómetro) u `horas` (horómetro).
3. Buscar el primer `valor_acumulado` ≥ lectura actual → ese es el **próximo** `servicio_codigo`.
4. **Regla de disparo:** se ejecuta el servicio por **km**, por **horas** o por **calendario**
   (máx. 12 meses) — *lo primero que se cumpla*. La tolerancia depende del modelo (ver tipo A/B arriba).
5. `tiempo_trabajo_h` permite estimar carga de taller; `intervalo_incremental` permite proyectar
   fechas a partir del uso diario promedio.

## Notas de interpretación

- **Perfil → frecuencia:** `severo` es el intervalo más corto (más frecuente) y `carretero` el más
  largo. Ej. Arocs km: severo 20.000 / mixto 40.000 / forestal 50.000 / carretero 60.000.
- **Actros WDB 930/932/934 y Axor WDF:** intercalan `SL*` (lubricación) entre servicios **solo si el
  motor usa aceite mineral**; tienen servicios anuales complementarios SA1/SA2/SA3 (no modelados como
  evento de km/horas, son por calendario). El Actros WDB equipa sistema *Telligent* que puede acortar
  intervalos según carga.
- **New Actros Brasil, Arocs Brasil, Axor 9BM/WDB:** sin Servicio Inicial (`SI`) ni `SL*` (motores con
  aceite sintético); la secuencia arranca en `SM1`. (Arocs Brasil sí tiene `SI`.)
- **Toma de fuerza (PTO):** en los Axor, vehículos con toma de fuerza al motor o caja deben usar
  solo el intervalo `severo` o `mixto` (nunca `carretero`).
- **Duplicado descartado:** la carpeta `Arocs Aleman Euro V - VI (1)` es idéntica al `Arocs 964`
  ya incluido (misma versión Julio 2024); no se agregó para evitar duplicación.
- Los valores son **referenciales** según los manuales del fabricante; no garantizan durabilidad y
  deben ser aplicados por personal calificado (texto de descargo de Comercial Kaufmann S.A.).
- La hoja de **lubricantes** (página 2 de cada PDF: aceites, refrigerantes, cantidades por
  componente) no se incluye en esta tabla de cronograma; puede parametrizarse aparte si se requiere.
