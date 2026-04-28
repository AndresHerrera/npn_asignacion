import os

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTextEdit,
    QSpinBox,
    QVBoxLayout,
)
from qgis.PyQt.QtSvg import QSvgWidget


class NpnAsignacionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NPN Asignación (cod. terreno)")
        self.resize(460, 300)

        self.layer_combo = QComboBox()
        self.field_combo = QComboBox()
        self.strategy_combo = QComboBox()
        self.only_selected_checkbox = QCheckBox("solo elementos seleccionados")
        self.start_spin = QSpinBox()
        self.stop_spin = QSpinBox()
        self.repeat_by_group_checkbox = QCheckBox("repetir por grupo")
        self.group_field_combo = QComboBox()
        self.strategy_description = QTextEdit()
        self.strategy_image = QSvgWidget()
        self.status_label = QLabel(
            "Seleccione la capa, el campo destino y la estrategia."
        )
        self.status_label.setWordWrap(True)
        self.strategy_descriptions = {
            1: "Barrido en grilla N a S con zig-zag y desempate Morton para vecindad espacial.",
            2: "Boustrophedon por franjas con micro-bandas para suavizar variaciones en Y.",
            3: "Estrategia hibrida N a S con giro horario desde noroeste y desempate por area.",
            4: "Snap de centroides a grilla derivada del area minima y barrido tipo boustrophedon.",
            5: "Patron lawnmower por bandas horizontales N a S alternando oeste-este y este-oeste.",
        }
        self.strategy_images = {
            1: "estrategia1_ejemplo.svg",
            2: "estrategia2_ejemplo.svg",
            3: "estrategia3_ejemplo.svg",
            4: "estrategia4_ejemplo.svg",
            5: "estrategia5_ejemplo.svg",
        }
        self.start_spin.setRange(0, 9999)
        self.start_spin.setValue(0)
        self.start_spin.setDisplayIntegerBase(10)
        self.start_spin.setPrefix("")
        self.start_spin.setSingleStep(1)
        self.stop_spin.setRange(0, 9999)
        self.stop_spin.setValue(9999)
        self.stop_spin.setDisplayIntegerBase(10)
        self.stop_spin.setPrefix("")
        self.stop_spin.setSingleStep(1)
        self.group_field_combo.setEnabled(False)
        self.strategy_description.setReadOnly(True)
        self.strategy_description.setMinimumHeight(85)
        self.strategy_image.setMinimumHeight(170)

        self.strategy_combo.addItem("Estrategia 1", 1)
        self.strategy_combo.addItem("Estrategia 2", 2)
        self.strategy_combo.addItem("Estrategia 3", 3)
        self.strategy_combo.addItem("Estrategia 4", 4)
        self.strategy_combo.addItem("Estrategia 5", 5)

        form_layout = QFormLayout()
        form_layout.addRow("Capa:", self.layer_combo)
        form_layout.addRow("Campo código terreno:", self.field_combo)
        form_layout.addRow("", self.only_selected_checkbox)
        form_layout.addRow("Estrategia:", self.strategy_combo)
        form_layout.addRow("Número inicial:", self.start_spin)
        form_layout.addRow("Número final:", self.stop_spin)
        form_layout.addRow("", self.repeat_by_group_checkbox)
        form_layout.addRow("Campo grupo (vereda/manzana):", self.group_field_combo)
        form_layout.addRow("Descripcion estrategia:", self.strategy_description)
        form_layout.addRow("Imagen estrategia:", self.strategy_image)
        self.repeat_by_group_checkbox.toggled.connect(self.group_field_combo.setEnabled)
        self.strategy_combo.currentIndexChanged.connect(self._update_strategy_description)
        self._update_strategy_description()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.button_box)
        self.setLayout(main_layout)

    def _update_strategy_description(self):
        strategy_id = self.strategy_combo.currentData()
        text = self.strategy_descriptions.get(
            strategy_id, "Seleccione una estrategia para ver su descripcion."
        )
        self.strategy_description.setPlainText(text)
        image_name = self.strategy_images.get(strategy_id)
        if image_name:
            image_path = os.path.join(os.path.dirname(__file__), image_name)
            if os.path.exists(image_path):
                self.strategy_image.load(image_path)
