# NPN Asignacion Cod. Terreno

Complemento para [QGIS](https://qgis.org) que permite asignar de manera automatizada códigos consecutivos de terreno del NPN (Número Predial Nacional) en un campo de una capa de polígonos, mediante la aplicación de una estrategia espacial configurable.

## Funcionalidades

- Seleccion de capa de poligonos.
- Seleccion de `Campo codigo` destino.
- Opcion `solo elementos seleccionados`.
- Parametros `Start number` y `Stop number` (0000 a 9999).
- Seleccion de estrategia (1 a 5).
- Modo `repetir por grupo` con selector `Campo grupo`.
- Progreso de ejecucion con barra y opcion **Cancelar**.
- Carga temporal de la polilinea de recorrido (en modo sin grupo).

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
   - `Campo código terreno`
   - `solo elementos seleccionados` (opcional)
   - `Estrategia`
   - `Número inicial` / `Número final`
   - `repetir por grupo` (opcional)
   - `Campo grupo (vereda/manzana)` (obligatorio si activa `repetir por grupo`)
5. Ejecute con **OK** y monitoree el avance en la barra de progreso.

## Reglas de asignacion

- El rango valido de codigos es `0000` a `9999`.
- Si `Número inicial` / `Número final`, el plugin no ejecuta.
- En modo normal (sin grupo), si la cantidad de entidades excede el rango disponible, el plugin no ejecuta.
- En modo `repetir por grupo`, la validacion de rango es por grupo: cada grupo reinicia desde `Número inicial` hasta `Número final`.
- Si un grupo excede el rango, el proceso se detiene indicando el grupo con conflicto.
- El plugin escribe los codigos en el `Campo código terreno` seleccionado.

## Como funciona `repetir por grupo`

Cuando esta activo:

1. Primero agrupa entidades por el valor de `Campo grupo (vereda/manzana)`.
2. Luego ejecuta la estrategia seleccionada **dentro de cada grupo**.
3. Finalmente asigna codigos reiniciando en cada grupo:
   - primer elemento del grupo = `Número inicial`
   - siguiente = `Número inicial + 1`
   - ...
   - ultimo permitido = `Número final`

## Progreso y cancelacion

- Durante la ejecucion se muestra una barra de progreso.
- El proceso reporta etapas y avance por grupo.
- Se puede cancelar en cualquier momento con el boton **Cancelar**.

## Salidas

- Actualizacion del `Campo código terreno` en la capa origen.
- Capa temporal de linea con el recorrido de asignacion para visualizacion (modo sin grupo).

## Estrategias de asignacion

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
4. Mantiene continuidad local evitando trazos tipo "diente de sierra".

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
2. Ajusta cada centroide a su celda.
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

## Licencia

El proyecto incluye en la raíz el fichero [`LICENSE`](LICENSE) con el **texto completo de la GNU General Public License, versión 3** (29 de junio de 2007), tal como lo publica la [Free Software Foundation](https://www.fsf.org/) en [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html).