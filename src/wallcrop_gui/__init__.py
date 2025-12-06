import sys
import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QGraphicsView, QGraphicsScene, 
                             QFileDialog, QToolBar, QLabel, QCheckBox, QWidget, 
                             QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox, QGraphicsItem, QGraphicsRectItem)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QBrush, QAction, QKeySequence
from PyQt6.QtCore import Qt, QRectF, QPointF

# Import core logic from wallcrop
try:
    from wallcrop import core
except ImportError:
    # Handle case where wallcrop is not installed in editable mode
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from wallcrop import core

class MonitorRect(QGraphicsItem):
    def __init__(self, rect, name, parent=None):
        super().__init__(parent)
        self.rect = rect
        self.name = name
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget):
        pen = QPen(QColor(255, 0, 0))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawRect(self.rect)
        
        # Draw semi-transparent fill
        painter.setBrush(QBrush(QColor(255, 0, 0, 50)))
        painter.drawRect(self.rect)
        
        # Draw Text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.rect, Qt.AlignmentFlag.AlignCenter, self.name)

class DraggableOverlay(QGraphicsRectItem):
    def __init__(self, rect, monitors_layout, update_callback, limits_rect, scale_factor):
        super().__init__(rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.monitors_layout = monitors_layout # List of (name, relative_rect)
        self.update_callback = update_callback
        self.limits = limits_rect
        self.scale_factor = scale_factor
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setPen(QPen(Qt.PenStyle.NoPen)) # Invisible container
        
        for name, rel_rect in self.monitors_layout:
             # Scale the individual monitor rects for display
            scaled_rect = QRectF(
                rel_rect.x() / scale_factor,
                rel_rect.y() / scale_factor,
                rel_rect.width() / scale_factor,
                rel_rect.height() / scale_factor
            )
            item = MonitorRect(scaled_rect, name, self)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            rect = self.boundingRect()
            # Visual rect is scaled down!
            w = rect.width() / self.scale_factor
            h = rect.height() / self.scale_factor
            
            x = new_pos.x()
            y = new_pos.y()
            
            lx = self.limits.x()
            ly = self.limits.y()
            lw = self.limits.width()
            lh = self.limits.height()
            
            # Clamp to stay fully inside limits
            if x < lx: x = lx
            if x + w > lx + lw: x = lx + lw - w
            if y < ly: y = ly
            if y + h > ly + lh: y = ly + lh - h
            
            # If overlay is somehow bigger than image (shouldn't happen with scale logic), force to top-left
            if w > lw: x = lx
            if h > lh: y = ly

            new_pos = QPointF(x, y)
            self.update_callback(new_pos)
            return new_pos

        return super().itemChange(change, value)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wallcrop GUI")
        self.resize(1000, 800)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Shortcuts
        self.open_action = QAction("Open Image", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open) # Ctrl+O
        self.open_action.triggered.connect(self.open_image)
        self.addAction(self.open_action)

        self.save_action = QAction("Crop & Save", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save) # Ctrl+S
        self.save_action.triggered.connect(self.save_crop)
        self.save_action.setEnabled(False)
        self.addAction(self.save_action)

        # Toolbar
        self.toolbar_layout = QHBoxLayout()
        self.btn_open = QPushButton("Open Image")
        self.btn_open.clicked.connect(self.open_image)
        self.toolbar_layout.addWidget(self.btn_open)

        self.btn_load_monitors = QPushButton("Load Monitors")
        self.btn_load_monitors.clicked.connect(self.load_monitors_dialog)
        self.toolbar_layout.addWidget(self.btn_load_monitors)
        
        self.cb_actual_size = QCheckBox("Actual Monitor Sizes (-a)")
        self.cb_actual_size.setEnabled(False)
        self.cb_actual_size.stateChanged.connect(self.refresh_overlay)
        self.toolbar_layout.addWidget(self.cb_actual_size)

        self.lbl_offset = QLabel("Offset: 0, 0")
        self.toolbar_layout.addWidget(self.lbl_offset)
        
        self.btn_save = QPushButton("Crop & Save")
        self.btn_save.clicked.connect(self.save_crop)
        self.btn_save.setEnabled(False)
        self.toolbar_layout.addWidget(self.btn_save)
        
        self.layout.addLayout(self.toolbar_layout)

        # Graphics View
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.layout.addWidget(self.view)

        # State
        self.image_path = None
        self.monitors = None
        self.overlay_item = None
        self.current_offset = (0, 0)
        self.image_item = None
        
        # Load persistent config
        self.config_dir = Path.home() / ".config" / "wallcrop"
        self.config_file = self.config_dir / "config.json"
        self.app_config = self.load_config()

    def load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.app_config, f)

    def load_monitors_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Monitors Config", str(Path.home()), "YAML (*.yml *.yaml)")
        if path:
            self.load_monitors_from_path(Path(path), persist=True)

    def load_monitors_from_path(self, path: Path, persist=False):
        try:
            self.monitors = core.load_monitors(path)
            self.cb_actual_size.setEnabled(True)
            
            # Check if actual size is feasible
            try:
                core.get_monitor_bounds(self.monitors, True)
                self.cb_actual_size.setChecked(True)
            except ValueError:
                self.cb_actual_size.setChecked(False)
                self.cb_actual_size.setEnabled(False)
                
            self.refresh_overlay()
            self.btn_save.setEnabled(True)
            self.save_action.setEnabled(True)
            
            if persist:
                self.app_config["default_monitors"] = str(path)
                self.save_config()
                
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Could not load monitors.yml: {e}")

    def resizeEvent(self, event):
        if self.image_item:
            self.view.fitInView(self.image_item, Qt.AspectRatioMode.KeepAspectRatio)
        super().resizeEvent(event)

    def open_image(self):
        pictures_dir = os.environ.get("XDG_PICTURES_DIR", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", pictures_dir, "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.load_image(Path(path))

    def load_image(self, path: Path):
        self.image_path = path
        self.scene.clear()
        self.overlay_item = None
        self.monitors = None
        self.btn_save.setEnabled(False)
        self.save_action.setEnabled(False)
        
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            QMessageBox.critical(self, "Error", "Could not load image.")
            return

        self.image_item = self.scene.addPixmap(pixmap)
        self.view.fitInView(self.image_item, Qt.AspectRatioMode.KeepAspectRatio)
        
        # Try loading monitors.yml from same dir, then fallback to config
        monitor_file = path.parent / "monitors.yml"
        if monitor_file.exists():
            self.load_monitors_from_path(monitor_file)
        elif "default_monitors" in self.app_config:
            fallback_path = Path(self.app_config["default_monitors"])
            if fallback_path.exists():
                self.load_monitors_from_path(fallback_path)
            else:
                QMessageBox.information(self, "Info", "No monitors.yml found in image directory, and default config not found.")
        else:
            QMessageBox.information(self, "Info", "No monitors.yml found. Please load one manually.")

    def refresh_overlay(self):
        if not self.monitors or not self.image_path:
            return

        # Safely remove old overlay
        if self.overlay_item:
            if self.overlay_item.scene() == self.scene:
                self.scene.removeItem(self.overlay_item)
            self.overlay_item = None

        use_actual_size = self.cb_actual_size.isChecked()
        
        try:
            min_x, min_y, max_x, max_y, px_per_cm_x, px_per_cm_y = core.get_monitor_bounds(self.monitors, use_actual_size)
        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        total_mon_w = max_x - min_x
        total_mon_h = max_y - min_y

        # Calculate Scale Factor (same logic as wallcrop.py)
        img_w = self.image_item.pixmap().width()
        img_h = self.image_item.pixmap().height()
        
        scale_x = total_mon_w / img_w
        scale_y = total_mon_h / img_h
        scale_factor = max(scale_x, scale_y, 1.0) # wallcrop logic: scales up if needed

        # Construct relative layout (unscaled coordinates)
        monitors_layout = []
        for m in self.monitors:
            if use_actual_size:
                x = int(m["x_cm"] * px_per_cm_x)
                y = int(m["y_cm"] * px_per_cm_y)
                w = int(m["width_cm"] * px_per_cm_x)
                h = int(m["height_cm"] * px_per_cm_y)
            else:
                x = m["x"]
                y = m["y"]
                w = m["width"]
                h = m["height"]
            
            monitors_layout.append((m["name"], QRectF(x - min_x, y - min_y, w, h)))

        # The bounding rect of the overlay needs to be the FULL size in logic units
        # But DraggableOverlay will scale it down for display.
        bounding_rect_logic = QRectF(0, 0, total_mon_w, total_mon_h)
        
        # Limits are the image bounds (0,0, img_w, img_h)
        limits_rect = QRectF(0, 0, img_w, img_h)

        self.overlay_item = DraggableOverlay(bounding_rect_logic, monitors_layout, self.update_offset_display, limits_rect, scale_factor)
        self.scene.addItem(self.overlay_item)

        # Center initially
        # Visual width/height
        vis_w = total_mon_w / scale_factor
        vis_h = total_mon_h / scale_factor
        
        center_x = (img_w - vis_w) / 2
        center_y = (img_h - vis_h) / 2
        
        self.overlay_item.setPos(center_x, center_y)
        self.update_offset_display(self.overlay_item.pos())

    def update_offset_display(self, pos):
        if not self.overlay_item: return
        
        # We need to convert the GUI position back to the "wallcrop logic" offset
        # Wallcrop logic: 
        #   If scale=1: offset_x = pos.x() - min_x (roughly)
        #   If scale>1: The image is effectively bigger in logic space.
        #   Wait, wallcrop SCALES THE IMAGE. 
        #   So if scale=2, the image becomes 2x bigger.
        #   The crop rect is then applied to that 2x image.
        #   
        #   GUI: We display 1x image. Overlay is 0.5x size.
        #   If overlay is at x=100 on 1x image.
        #   On 2x image, that corresponds to x=200.
        #   
        #   So: effective_x = pos.x() * scale_factor
        #   offset_x = effective_x - min_x
        
        sf = self.overlay_item.scale_factor
        
        use_actual_size = self.cb_actual_size.isChecked()
        try:
            min_x, min_y, _, _, _, _ = core.get_monitor_bounds(self.monitors, use_actual_size)
        except: return

        # Calculate effective position in "scaled image space"
        eff_x = int(pos.x() * sf)
        eff_y = int(pos.y() * sf)
        
        # Calculate the offset wallcrop needs
        # wallcrop: x_l = offset_x + m["x"]
        # In our scaled space, the monitor rect top-left is at (eff_x + m["x"] - min_x)
        # Wait... 
        # The monitor rect is at (monitor_x_logic, monitor_y_logic) relative to the overlay origin.
        # The overlay origin is at (eff_x, eff_y) in the scaled image.
        # So the monitor rect is at (eff_x + monitor_x_logic, eff_y + monitor_y_logic) in the scaled image.
        # 
        # We want this to match wallcrop's crop:
        # crop_x = offset_x + monitor_x_logic + min_x (because we subtracted min_x earlier?)
        # Let's look at core.py:
        # x_l = offset_x + m["x"] (or scaled cm equiv)
        # 
        # Our overlay holds relative rects: (m["x"] - min_x).
        # So logic coord in overlay = m["x"] - min_x.
        # Global coord = overlay_origin + logic_coord
        #              = eff_x + m["x"] - min_x
        # 
        # Wallcrop crop: offset_x + m["x"]
        # 
        # Equating them:
        # offset_x + m["x"] = eff_x + m["x"] - min_x
        # offset_x = eff_x - min_x
        
        off_x = eff_x - min_x
        off_y = eff_y - min_y
        
        self.current_offset = (off_x, off_y)
        self.lbl_offset.setText(f"Offset: {off_x}, {off_y} (Scale: {sf:.2f}x)")

    def save_crop(self):
        if not self.image_path: return
        
        offset_str = f"{self.current_offset[0]},{self.current_offset[1]}"
        output_dir = self.image_path.parent / "wallcrop"
        
        try:
            core.process_image(
                self.image_path,
                self.monitors,
                output_dir,
                "png",
                False, # no_scale
                self.cb_actual_size.isChecked(),
                offset_str
            )
            QMessageBox.information(self, "Success", f"Crops saved to {output_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to crop: {e}")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
