import os
from osgeo import gdal

from qgis.PyQt.QtWidgets import (QAction, QDialog, QVBoxLayout, QFormLayout, QGroupBox, QTabWidget,
                                    QWidget, QLabel, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar,
                                    QLineEdit, QHBoxLayout, QFileDialog)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (QgsProject, QgsRectangle, QgsMapSettings, QgsCoordinateReferenceSystem,
                        QgsCoordinateTransform, QgsGeometry, QgsMapRendererParallelJob,
                        QgsMapLayerProxyModel, QgsTask, QgsMessageLog, Qgis)
from qgis.gui import (QgsMapLayerComboBox, QgsFieldComboBox, QgsProjectionSelectionWidget)
from qgis.PyQt.QtCore import QSize, QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.utils import iface

gdal.UseExceptions()

class GISCropperDialog(QDialog):
    def __init__(self, parent=None):
        super(GISCropperDialog, self).__init__(parent)
        self.setWindowTitle("GISCropper - Crop and Export Tool")
        self.setMinimumWidth(500)

        # Main layout
        self.layout = QVBoxLayout(self)

        form_layout_points = QFormLayout()
        self.points_layer_combo = QgsMapLayerComboBox(self)
        self.points_layer_combo.setFilters(QgsMapLayerProxyModel.PointLayer)
        form_layout_points.addRow("Points Layer:", self.points_layer_combo)
        self.layout.addLayout(form_layout_points)
        
        self.tabs = QTabWidget()
        self.tab_crop = QWidget()
        self.tab_export = QWidget()
        self.tabs.addTab(self.tab_crop, "Crop Raster Layer")
        self.tabs.addTab(self.tab_export, "Crop WMS/Imagery")

        layout_crop = QFormLayout()
        self.raster_layer_combo = QgsMapLayerComboBox(self)
        self.raster_layer_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        layout_crop.addRow("Raster Layer:", self.raster_layer_combo)
        self.tab_crop.setLayout(layout_crop)

        layout_export = QFormLayout()
        self.wms_layer_combo = QgsMapLayerComboBox(self)
        self.wms_layer_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.width_px_spin = QSpinBox()
        self.width_px_spin.setRange(1, 9999); self.width_px_spin.setValue(127)
        self.height_px_spin = QSpinBox()
        self.height_px_spin.setRange(1, 9999); self.height_px_spin.setValue(127)
        layout_export.addRow("WMS/Imagery:", self.wms_layer_combo)
        layout_export.addRow("Output width (px):", self.width_px_spin)
        layout_export.addRow("Output height (px):", self.height_px_spin)
        self.tab_export.setLayout(layout_export)
        
        self.layout.addWidget(self.tabs)

        group_common = QGroupBox("Params")
        layout_common = QFormLayout()
        
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setReadOnly(True) 
        self.browse_button = QPushButton("Browse...", self)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_button)
        
        self.filename_field_combo = QgsFieldComboBox(self)
        self.points_src_widget = QgsProjectionSelectionWidget(self)
        self.output_src_widget = QgsProjectionSelectionWidget(self)
        self.width_m_spin = QDoubleSpinBox(self); self.width_m_spin.setRange(1, 99999); self.width_m_spin.setValue(2052)
        self.height_m_spin = QDoubleSpinBox(self); self.height_m_spin.setRange(1, 99999); self.height_m_spin.setValue(2052)

        layout_common.addRow("Output folder:", path_layout)
        layout_common.addRow("Filename field:", self.filename_field_combo)
        layout_common.addRow("Points SRC (Origin):", self.points_src_widget)
        layout_common.addRow("Output SRC (UTM):", self.output_src_widget)
        layout_common.addRow("Crop width (m):", self.width_m_spin)
        layout_common.addRow("Crop height (m):", self.height_m_spin)
        
        group_common.setLayout(layout_common)
        self.layout.addWidget(group_common)

        self.progress_bar = QProgressBar(self)
        self.btn_execute = QPushButton("Execute", self)
        self.btn_close = QPushButton("Close", self)
        
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(self.btn_execute)
        self.layout.addWidget(self.btn_close)

        self.points_layer_combo.layerChanged.connect(self.filename_field_combo.setLayer)
        self.btn_close.clicked.connect(self.close)
        self.btn_execute.clicked.connect(self.start_processing)
        self.browse_button.clicked.connect(self.select_output_folder)
    
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select the output folder", "")
        if folder:
            self.path_edit.setText(folder)

    def show_message(self, title, message, level=Qgis.Info, duration=5):
        iface.messageBar().pushMessage(title, message, level=level, duration=duration)

    def start_processing(self):
        self.btn_execute.setEnabled(False)
        self.progress_bar.setValue(0)
        
        try:
            points_layer = self.points_layer_combo.currentLayer()
            images_folder = self.path_edit.text()
            filename_field = self.filename_field_combo.currentField()
            points_src = self.points_src_widget.crs()
            output_src = self.output_src_widget.crs()
            width_m = self.width_m_spin.value()
            height_m = self.height_m_spin.value()

            if not all([points_layer, images_folder, points_src.isValid(), output_src.isValid()]):
                self.show_message("Error", "Fill in all required parameters!", level=Qgis.Critical)
                return
            
            os.makedirs(images_folder, exist_ok=True)
            transformation = QgsCoordinateTransform(points_src, output_src, QgsProject.instance().transformContext())
            
            if self.tabs.currentIndex() == 0:
                self.run_raster_clipping(points_layer, images_folder, filename_field, transformation, width_m, height_m, output_src)
            else:
                self.run_orthophoto_export(points_layer, images_folder, filename_field, transformation, width_m, height_m)
        
        except Exception as e:
            self.show_message("Unexpected Error", f"An error occurred: {e}", level=Qgis.Critical)
        finally:
            self.btn_execute.setEnabled(True)

    def run_raster_clipping(self, points_layer, folder, field, transform, width, height, output_src):
        raster_layer = self.raster_layer_combo.currentLayer()
        if not raster_layer:
            self.show_message("Error", "Select the raster layer to be cropped!", level=Qgis.Critical)
            return
        
        if not raster_layer.crs().isValid():
            self.show_message("CRS Error", "The input raster layer does not have a valid CRS defined!", level=Qgis.Critical)
            return

        self._process_features(points_layer, folder, field, transform, width, height, 'clip', raster_layer, output_src)

    def run_orthophoto_export(self, points_layer, folder, field, transform, width, height):
        wms_layer = self.wms_layer_combo.currentLayer()
        if not wms_layer:
            self.show_message("Error", "Select the base WMS/Image layer!", level=Qgis.Critical)
            return
            
        export_params = {
            'wms_layer': wms_layer,
            'width_px': self.width_px_spin.value(),
            'height_px': self.height_px_spin.value()
        }
        self._process_features(points_layer, folder, field, transform, width, height, 'export', export_params, None)

    def _process_features(self, points_layer, folder, field, transform, width, height, mode, extra_params, output_src=None):
        total = points_layer.featureCount()
        self.progress_bar.setMaximum(total)
        self.show_message("Starting", f"Processing {total} features...", duration=3)
        
        success_count = 0
        for i, feat in enumerate(points_layer.getFeatures()):
            QCoreApplication.processEvents()

            geom = QgsGeometry(feat.geometry())
            geom.transform(transform)
            center_point = geom.asPoint()
            
            extent = QgsRectangle.fromCenterAndSize(center_point, width, height)
            
            base_name = f'sample_{i+1}'
            if field and field in feat.fields().names():
                field_value = feat[field]
                if field_value: base_name = str(field_value)
            
            output_path = os.path.join(folder, f'{base_name}.tif')
            
            try:
                if mode == 'clip':
                    gdal.Translate(
                        destName=output_path,
                        srcDS=extra_params.source(), 
                        projWin=[extent.xMinimum(), extent.yMaximum(), extent.xMaximum(), extent.yMinimum()],
                        outputSRS=output_src.toWkt(),
                        format='GTiff',
                        creationOptions=['COMPRESS=LZW']
                    )

                elif mode == 'export':
                    settings = QgsMapSettings()
                    settings.setLayers([extra_params['wms_layer']])
                    settings.setDestinationCrs(transform.destinationCrs())
                    settings.setExtent(extent)
                    settings.setOutputSize(QSize(extra_params['width_px'], extra_params['height_px']))
                    
                    job = QgsMapRendererParallelJob(settings)
                    job.start()
                    job.waitForFinished()
                    
                    img = job.renderedImage()
                    img.save(output_path, "tif")
                
                success_count += 1
            except Exception as e:
                error_msg = f"Failed to process feature {base_name}: {e}"
                self.show_message("Processing Error", error_msg, level=Qgis.Critical, duration=10)
                QgsMessageLog.logMessage(error_msg, "GISCropper", Qgis.Critical)
                return

            self.progress_bar.setValue(i + 1)
        
        self.show_message("Success!", f"Process finished. {success_count} out of {total} features were processed.", duration=7)


class GISCropper:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = u'&GISCropper'
        self.dlg = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        self.action = QAction(QIcon(icon_path), u'Open GISCropper', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, self.action)

    def unload(self):
        self.iface.removePluginMenu(u'&GISCropper', self.action)

    def run(self):
        self.dlg = GISCropperDialog()
        self.dlg.show()