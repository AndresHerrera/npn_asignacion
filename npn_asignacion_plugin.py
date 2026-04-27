import gc
import importlib.util
import os
import shutil
import site
import sys
import tempfile
import time

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    Qgis,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    edit,
)

from .npn_asignacion_dialog import NpnAsignacionDialog


class NpnAsignacionPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.menu_name = "NPN Asignación(cod. terreno)"
        self.plugin_dir = os.path.dirname(__file__)
        self.strategy_files = {
            1: "npn_estrategia1.py",
            2: "npn_estrategia2.py",
            3: "npn_estrategia3.py",
            4: "npn_estrategia4.py",
            5: "npn_estrategia5.py",
        }
        self.strategy_outputs = {
            1: "terrenos_test_estrategia1.shp",
            2: "terrenos_test_estrategia2.shp",
            3: "terrenos_test_estrategia3.shp",
            4: "terrenos_test_estrategia4.shp",
            5: "terrenos_test_estrategia5.shp",
        }

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icons", "icon_menu.svg")
        self.action = QAction(
            QIcon(icon_path), "NPN Asignación (cod. terreno)", self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu_name, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(self.menu_name, self.action)
            self.iface.removeToolBarIcon(self.action)

    def run(self):
        dialog = NpnAsignacionDialog(self.iface.mainWindow())
        self._populate_layers(dialog)
        dialog.layer_combo.currentIndexChanged.connect(
            lambda _idx: self._populate_fields(dialog)
        )
        self._populate_fields(dialog)

        if dialog.exec_() != dialog.Accepted:
            return

        layer = dialog.layer_combo.currentData()
        field_name = dialog.field_combo.currentText().strip()
        strategy_id = dialog.strategy_combo.currentData()
        only_selected = bool(dialog.only_selected_checkbox.isChecked())
        start_number = int(dialog.start_spin.value())
        stop_number = int(dialog.stop_spin.value())

        if layer is None:
            self._msg("Seleccione una capa valida.", level=Qgis.Warning)
            return
        if not field_name:
            self._msg("Seleccione un campo destino.", level=Qgis.Warning)
            return
        if not (1 <= int(strategy_id) <= 5):
            self._msg("Seleccione una estrategia valida.", level=Qgis.Warning)
            return
        if start_number > stop_number:
            self._msg("Start number debe ser menor o igual a Stop number.", level=Qgis.Warning)
            return

        try:
            asignados = self._assign_codes(
                layer,
                field_name,
                int(strategy_id),
                start_number,
                stop_number,
                only_selected,
            )
            self._msg("Asignacion completada correctamente.", level=Qgis.Success)
            QMessageBox.information(
                self.iface.mainWindow(),
                "NPN Asignación (cod. terreno)",
                f"Proceso finalizado correctamente.\n"
                f"Se asignaron códigos a {asignados} elemento(s).",
            )
        except Exception as exc:  # pragma: no cover - runtime integration
            QMessageBox.critical(
                self.iface.mainWindow(),
                "npn asignacion",
                f"No fue posible completar la asignacion:\n{exc}",
            )

    def _populate_layers(self, dialog):
        dialog.layer_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == 2:
                dialog.layer_combo.addItem(layer.name(), layer)

    def _populate_fields(self, dialog):
        dialog.field_combo.clear()
        layer = dialog.layer_combo.currentData()
        if layer is None:
            return
        for field in layer.fields():
            if field.type() in (QVariant.String, QVariant.Int, QVariant.LongLong):
                dialog.field_combo.addItem(field.name())

    def _assign_codes(
        self, layer, field_name, strategy_id, start_number, stop_number, only_selected
    ):
        if layer.fields().indexFromName(field_name) == -1:
            raise ValueError(f"El campo '{field_name}' no existe.")

        if layer.featureCount() == 0:
            raise ValueError("La capa seleccionada no tiene entidades.")

        selected_ids = layer.selectedFeatureIds() if only_selected else []
        if only_selected and not selected_ids:
            raise ValueError("No hay elementos seleccionados en la capa.")

        source_layer = layer
        source_request = QgsFeatureRequest()
        feature_count = int(layer.featureCount())
        if only_selected:
            source_request.setFilterFids(selected_ids)
            source_layer = layer.materialize(source_request)
            feature_count = int(source_layer.featureCount())
            if feature_count == 0:
                raise ValueError("No fue posible materializar los elementos seleccionados.")

        available_codes = (stop_number - start_number) + 1
        if feature_count > available_codes:
            raise ValueError(
                "La cantidad de entidades excede el rango Start/Stop seleccionado."
            )

        strategy_file = os.path.join(self.plugin_dir, self.strategy_files[strategy_id])
        if not os.path.exists(strategy_file):
            raise FileNotFoundError(f"No se encontro el script: {strategy_file}")

        tmp_dir = tempfile.mkdtemp(prefix="npn_asignacion_")
        try:
            input_path = os.path.join(tmp_dir, "terrenos_test.shp")
            output_path = os.path.join(tmp_dir, self.strategy_outputs[strategy_id])
            output_lines_path = output_path.replace(".shp", "_newcode_path.shp")

            error = QgsVectorFileWriter.writeAsVectorFormat(
                source_layer,
                input_path,
                "UTF-8",
                source_layer.crs(),
                "ESRI Shapefile",
            )
            if isinstance(error, tuple):
                err_code = error[0]
            else:
                err_code = error
            if err_code != QgsVectorFileWriter.NoError:
                raise RuntimeError("No fue posible exportar la capa a shapefile temporal.")

            current_dir = os.getcwd()
            original_sys_path = list(sys.path)
            original_start = os.environ.get("NPN_START")
            original_stop = os.environ.get("NPN_STOP")
            try:
                os.chdir(tmp_dir)
                self._sanitize_python_path_for_qgis()
                os.environ["NPN_START"] = str(start_number)
                os.environ["NPN_STOP"] = str(stop_number)
                spec = importlib.util.spec_from_file_location(
                    f"npn_estrategia_{strategy_id}_run", strategy_file
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                os.chdir(current_dir)
                sys.path = original_sys_path
                if original_start is None:
                    os.environ.pop("NPN_START", None)
                else:
                    os.environ["NPN_START"] = original_start
                if original_stop is None:
                    os.environ.pop("NPN_STOP", None)
                else:
                    os.environ["NPN_STOP"] = original_stop

            if not os.path.exists(output_path):
                output_path = self._find_strategy_output(tmp_dir, strategy_id)
                if output_path is None:
                    raise RuntimeError(
                        "La estrategia no genero la salida esperada. "
                        "Revise dependencias de geopandas/numpy/shapely."
                    )
            output_lines_path = output_path.replace(".shp", "_newcode_path.shp")
            self._load_temp_line_result(output_lines_path, layer.name(), strategy_id)

            result_layer = QgsVectorLayer(output_path, "npn_result", "ogr")
            if not result_layer.isValid():
                raise RuntimeError("No fue posible leer el resultado de la estrategia.")

            code_idx = result_layer.fields().indexFromName("NEW_CODE")
            if code_idx == -1:
                raise RuntimeError("La salida de estrategia no contiene el campo NEW_CODE.")

            layer_to_wgs84 = self._build_transform(layer.crs())
            result_to_wgs84 = self._build_transform(result_layer.crs())

            geometry_to_code = {}
            for feat in result_layer.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                key = self._feature_match_key(geom, result_to_wgs84)
                geometry_to_code.setdefault(key, []).append(str(feat["NEW_CODE"]))

            field_idx = layer.fields().indexFromName(field_name)
            updated = 0
            update_request = QgsFeatureRequest()
            if only_selected:
                update_request.setFilterFids(selected_ids)
            with edit(layer):
                for feat in layer.getFeatures(update_request):
                    geom = feat.geometry()
                    if geom is None or geom.isEmpty():
                        continue
                    key = self._feature_match_key(geom, layer_to_wgs84)
                    codes = geometry_to_code.get(key)
                    if not codes:
                        continue
                    code = codes.pop(0)
                    if layer.fields()[field_idx].type() in (QVariant.Int, QVariant.LongLong):
                        code_value = int(code)
                    else:
                        code_value = code
                    layer.changeAttributeValue(feat.id(), field_idx, code_value)
                    updated += 1

            layer.triggerRepaint()
            if updated == 0:
                raise RuntimeError(
                    "No se actualizaron entidades en el campo seleccionado. "
                    "Revise que la capa no haya cambiado durante el proceso."
                )
            result_layer = None
            gc.collect()
            return updated
        finally:
            self._safe_rmtree(tmp_dir)

    def _sanitize_python_path_for_qgis(self):
        """
        Evita mezclar ruedas de numpy/geopandas del usuario con las de QGIS.
        """
        user_site = site.getusersitepackages()
        normalized_user_site = os.path.normcase(os.path.abspath(user_site))
        sys.path = [
            p
            for p in sys.path
            if os.path.normcase(os.path.abspath(p)) != normalized_user_site
        ]

    def _safe_rmtree(self, folder):
        """
        En Windows, OGR puede mantener locks breves en .dbf/.shp.
        Reintenta limpieza para evitar WinError 32.
        """
        for _ in range(10):
            try:
                shutil.rmtree(folder, ignore_errors=False)
                return
            except PermissionError:
                time.sleep(0.15)
                gc.collect()
            except FileNotFoundError:
                return

    def _find_strategy_output(self, tmp_dir, strategy_id):
        expected_hint = f"estrategia{strategy_id}"
        candidates = []
        for name in os.listdir(tmp_dir):
            if not name.lower().endswith(".shp"):
                continue
            low = name.lower()
            if low.endswith("_newcode_path.shp"):
                continue
            if expected_hint in low or "terrenos_test_estrategia" in low:
                candidates.append(name)
        if not candidates:
            return None
        candidates.sort()
        return os.path.join(tmp_dir, candidates[0])

    def _load_temp_line_result(self, lines_path, source_layer_name, strategy_id):
        if not os.path.exists(lines_path):
            return
        line_layer = QgsVectorLayer(lines_path, "npn_linea_tmp", "ogr")
        if not line_layer.isValid():
            return
        temp_layer = line_layer.materialize(QgsFeatureRequest())
        temp_layer.setName(
            f"NPN Linea estrategia {strategy_id} - {source_layer_name}"
        )
        QgsProject.instance().addMapLayer(temp_layer)

    def _build_transform(self, source_crs):
        target = QgsCoordinateReferenceSystem("EPSG:4326")
        if source_crs == target:
            return None
        return QgsCoordinateTransform(source_crs, target, QgsProject.instance())

    def _feature_match_key(self, geom, transform):
        """
        Clave robusta por punto representativo en EPSG:4326 para asociar entidades.
        """
        work_geom = QgsGeometry(geom)
        if transform is not None:
            work_geom.transform(transform)
        p = work_geom.pointOnSurface().asPoint()
        return f"{round(float(p.x()), 7)}|{round(float(p.y()), 7)}"

    def _msg(self, text, level=Qgis.Info):
        self.iface.messageBar().pushMessage("npn asignacion", text, level=level, duration=5)
