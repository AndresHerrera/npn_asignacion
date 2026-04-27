# NPN Asignación Cod. Terreno

Plugin para QGIS que asigna codigos consecutivos en un campo de una capa de poligonos, usando una estrategia espacial seleccionable.

## Funcionalidades

- Seleccion de capa de poligonos.
- Seleccion de `campo codigo` destino.
- Opcion `solo elementos seleccionados`.
- Parametros `Start number` y `Stop number` (0000 a 9999).
- Seleccion de estrategia (1 a 5).
- Carga temporal de la polilinea de recorrido resultante (`*_newcode_path`).

## Requisitos

- QGIS 3.x
- Dependencias Python disponibles en el entorno de QGIS:
  - `geopandas`
  - `numpy`
  - `shapely`

## Uso rapido

1. Abra QGIS y cargue una capa de poligonos.
2. Seleccione algunos elementos si desea usar el modo parcial.
3. Abra `npn asignacion`.
4. Configure:
   - `Capa`
   - `Campo codigo`
   - `solo elementos seleccionados` (opcional)
   - `Estrategia`
   - `Start number` / `Stop number`
5. Ejecute con **OK**.

## Reglas de asignacion

- El rango valido de codigos es `0000` a `9999`.
- Si `Start number > Stop number`, el plugin no ejecuta.
- Si la cantidad de entidades a procesar excede el rango disponible, el plugin no ejecuta.
- El plugin escribe los codigos en el `campo codigo` seleccionado.

## Salidas

- Actualizacion del campo codigo en la capa origen.
- Capa temporal de linea con el recorrido de asignacion para visualizacion.

## Estrategias

# Estrategias de asignación NPN Código Terreno


## Estrategia 1 - Grilla + Zig-zag + Morton

**Idea:** construir celdas sobre el ambito, recorrer de norte a sur en zig-zag y desempatar con clave Morton.

1. Obtiene un punto representativo por poligono.
2. Calcula fila/columna de grilla.
3. Recorre filas N -> S.
4. En filas alternas invierte sentido E -> O / O -> E.
5. En empates usa orden Morton para preservar vecindad 2D.

**Uso sugerido:** manzanas con formas irregulares donde se desea continuidad espacial.

## Estrategia 2 - Franjas + Microbandas

**Idea:** dividir en franjas horizontales y reducir saltos verticales usando microbandas.

1. Define franjas N -> S.
2. Dentro de cada franja crea microbandas.
3. Aplica boustrophedon en cada nivel.
4. Mantiene continuidad local evitando trazos "diente de sierra".

**Uso sugerido:** conjuntos con dispersion en Y dentro de la misma franja.

## Estrategia 3 - Hibrida N->S + Giro horario

**Idea:** priorizar norte-sur y luego ordenar por angulo horario desde referencia noroeste.

1. Clasifica por franjas N -> S.
2. Calcula centro de referencia.
3. Ordena por giro horario.
4. Desempata por distancia y area.
5. Rota la secuencia para iniciar en el elemento noroeste.

**Uso sugerido:** distribuciones complejas con necesidad de inicio controlado.

## Estrategia 4 - Snap a grilla por area minima

**Idea:** ajustar centroides al centro de celda mas cercano y ordenar sobre esa malla.

1. Estima paso de grilla usando raiz del area minima.
2. "Snapea" cada centroide a su celda.
3. Aplica barrido tipo boustrophedon.
4. Usa Morton para desempate y continuidad.

**Uso sugerido:** capas donde se requiere regularidad espacial de malla.

## Estrategia 5 - Lawnmower puro

**Idea:** recorrido de cortacesped por bandas horizontales.

1. Define bandas N -> S.
2. En una banda recorre O -> E.
3. En la siguiente recorre E -> O.
4. Repite alternancia hasta completar.

**Uso sugerido:** recorridos simples, legibles y predecibles para inspeccion visual.

## Rango de codigos

Todas las estrategias respetan:

- `NPN_START` y `NPN_STOP` (desde la UI)
- rango permitido: `0000` a `9999`
- validacion por cantidad de entidades a procesar

