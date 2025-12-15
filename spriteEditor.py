import sys
import io
from PIL import Image, ImageDraw, ImageFilter
import re
from copy import deepcopy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QCheckBox, QSlider, QFileDialog, QListWidget,
    QListWidgetItem, QFrame, QGridLayout, QMessageBox,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsObject,
    QGroupBox, QAbstractItemView, QApplication, QTabWidget, QComboBox, QLineEdit,
    QGraphicsRectItem, QColorDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QSize, QPoint, QPointF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QIcon, QBrush, QWheelEvent, QKeyEvent


try:
    import torch
    from realesrgan import RealESRGANer
    from realesrgan.archs.srvgg_arch import SRVGGNetCompact
    from basicsr.archs.rrdbnet_arch import RRDBNet
    REALESRGAN_AVAILABLE = True
except ImportError:
    REALESRGAN_AVAILABLE = False
    print("⚠️ Real-ESRGAN não está instalado.")

try:
    from rembg import remove
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False
    print("⚠️ rembg não está instalado.")


class GridOverlay(QGraphicsObject):

    positionChanged = pyqtSignal(int, int) 

    def __init__(self, cell_size=32, rows=1, cols=1, subdivisions=False):
        super().__init__()
        self.cell_size = cell_size
        self.rows = rows
        self.cols = cols
        self.subdivisions = subdivisions
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(10) 

    def boundingRect(self):
        width = self.cols * self.cell_size
        height = self.rows * self.cell_size
        return QRectF(0, 0, width, height)

    def paint(self, painter, option, widget):
        width = self.cols * self.cell_size
        height = self.rows * self.cell_size

 
        pen = QPen(QColor(255, 255, 255), 1, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True) 
        painter.setPen(pen)
        painter.drawRect(0, 0, width, height)

      
        if self.subdivisions or (self.rows > 1 or self.cols > 1):
           
            for c in range(1, self.cols):
                x = c * self.cell_size
                painter.drawLine(x, 0, x, height)
            
          
            for r in range(1, self.rows):
                y = r * self.cell_size
                painter.drawLine(0, y, width, y)

       
        painter.fillRect(0, 0, width, height, QColor(255, 255, 255, 30))

    def itemChange(self, change, value):
        if change == QGraphicsObject.GraphicsItemChange.ItemPositionChange:
           
            new_pos = value
            self.positionChanged.emit(int(new_pos.x()), int(new_pos.y()))
        return super().itemChange(change, value)

    def update_grid(self, rows, cols, subdivisions):
        self.rows = rows
        self.cols = cols
        self.subdivisions = subdivisions
        self.prepareGeometryChange()
        self.update()
        
        
class FineGridOverlay(QGraphicsObject):

    
    def __init__(self, image_rect, grid_spacing=4):
        super().__init__()
        self.image_rect = image_rect
        self.grid_spacing = grid_spacing
        self.setZValue(5)
        self.visible = False
    
    def boundingRect(self):
        return self.image_rect.adjusted(-1, -1, 1, 1)
    
    def paint(self, painter, option, widget):
        if not self.visible:
            return
            
        rect = self.image_rect
        
        # Grid fino
        pen = QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        
        # Linhas verticais
        x = 0
        while x <= rect.width():
            painter.drawLine(int(x), 0, int(x), int(rect.height()))
            x += self.grid_spacing
        
        # Linhas horizontais
        y = 0
        while y <= rect.height():
            painter.drawLine(0, int(y), int(rect.width()), int(y))
            y += self.grid_spacing
        
        # Borda da imagem em vermelho
        border_pen = QPen(QColor(255, 100, 100, 200), 3, Qt.PenStyle.SolidLine)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.drawRect(rect)
    
    def set_visible(self, visible):
        self.visible = visible
        self.update()
    
    def update_rect(self, new_rect):
        self.prepareGeometryChange()
        self.image_rect = new_rect
        self.update()
    
    def set_spacing(self, spacing):
        self.grid_spacing = spacing
        self.update()
        


class SelectionRectangle(QGraphicsRectItem):
    
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)  # Desabilitado por padrão
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(15)
        
        pen = QPen(QColor(0, 150, 255), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(0, 150, 255, 30)))
        
        self.setAcceptHoverEvents(True)
        
        # Armazena a imagem selecionada como um pixmap item
        self.selected_pixmap_item = None
        self.original_rect = None
        
    def set_rect(self, rect):
        """Define o retângulo de seleção"""
        self.setRect(rect)
        self.original_rect = rect
    
    def hoverEnterEvent(self, event):

        self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)
    
    def hoverLeaveEvent(self, event):
        """Restaura o cursor ao sair da seleção"""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)
    
    def mousePressEvent(self, event):

        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Restaura o cursor após arrastar"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().mouseReleaseEvent(event)



class ZoomableGraphicsView(QGraphicsView):

    
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.zoom_factor = 1.0
        
    def wheelEvent(self, event: QWheelEvent):

        modifiers = QApplication.keyboardModifiers()
        
        if modifiers == Qt.KeyboardModifier.ControlModifier:
     
            zoom_in_factor = 1.15
            zoom_out_factor = 1 / zoom_in_factor
           
            old_pos = self.mapToScene(event.position().toPoint())
            
         
            if event.angleDelta().y() > 0:
                factor = zoom_in_factor
                self.zoom_factor *= zoom_in_factor
            else:
                factor = zoom_out_factor
                self.zoom_factor *= zoom_out_factor
        
            if 0.1 <= self.zoom_factor <= 5.0:
                self.scale(factor, factor)
             
                new_pos = self.mapToScene(event.position().toPoint())
                delta = new_pos - old_pos
                self.translate(delta.x(), delta.y())
                
               
                if hasattr(self.parent(), 'update_zoom_label'):
                    self.parent().update_zoom_label(int(self.zoom_factor * 100))
            else:
             
                self.zoom_factor /= factor
            
            event.accept()
        else:
         
            super().wheelEvent(event)


class SliceWindow(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sprite Editor - Made by Sherrat")
        self.resize(900, 600)
        
        self.setWindowIcon(QIcon("editor.ico"))  

        self.setStyleSheet("background-color: #494949; color: white;")
        self.original_image_pil = None       
        self.current_image_pil = None 
        self.sliced_images = []     
        self.cell_size = 32
        self.color_picker_mode = False
        self.paint_color_picker_mode = False  
        

        # Eraser tool
        self.eraser_mode = False
        self.eraser_size = 10
        self.eraser_feathering = 0  # NOVA VARIÁVEL
        self.last_eraser_point = None

      
        self.paint_mode = False
        self.paint_size = 5
        self.paint_color = QColor(0, 0, 0, 255)
        self.last_paint_point = None
        self.paint_feathering = 0  
        
        self.outline_color = QColor(0, 0, 0, 255)  # Preto por padrão       

        self.selection_mode = False
        self.selection_start = None
        self.selection_rect_item = None
        self.is_drawing_selection = False
        self.selected_image_data = None
        
        self.is_moving_selection = False
        self.move_start_pos = None
        self.selection_image_backup = None  # Backup da área original
        self.floating_selection_pixmap = None
        
        # Fine Grid
        self.fine_grid_item = None
        self.fine_grid_enabled = False
        self.fine_grid_spacing = 32
                
                
     
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_steps = 20

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("background-color: #333; border-bottom: 1px solid #222;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 5, 10, 5)

        btn_open = QPushButton("Open Image")
        btn_open.setStyleSheet("background-color: #555; padding: 5px;")
        btn_open.clicked.connect(self.open_image)
        tb_layout.addWidget(btn_open)
        
        tb_layout.addStretch()

        btn_rot_r = QPushButton("Rot 90°")
        btn_rot_r.clicked.connect(lambda: self.transform_image("rotate_90"))
        tb_layout.addWidget(btn_rot_r)

        btn_flip_h = QPushButton("Flip H")
        btn_flip_h.clicked.connect(lambda: self.transform_image("flip_h"))
        tb_layout.addWidget(btn_flip_h)

        main_layout.addWidget(toolbar)


        content_layout = QHBoxLayout()
        main_layout.addLayout(content_layout)

  
        left_panel = QFrame()
        left_panel.setFixedWidth(283)
        left_panel.setStyleSheet("QFrame { background-color: #444; border-right: 1px solid #222; } QLabel { color: #ddd; }")
        lp_layout = QVBoxLayout(left_panel)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #222; background: #444; }
            QTabBar::tab { background: #333; color: #ddd; padding: 4px; min-width: 58px; }
            QTabBar::tab:selected { background: #555; color: white; }
        """)


        tab_resize = QWidget()
        tab_resize_layout = QVBoxLayout(tab_resize)

        grp_resize = QGroupBox("Resize Image")
        resize_layout = QGridLayout()

        resize_layout.addWidget(QLabel("Width:"), 0, 0)
        self.spin_resize_width = QSpinBox()
        self.spin_resize_width.setRange(1, 9999)
        self.spin_resize_width.setValue(32)
        self.spin_resize_width.valueChanged.connect(self.on_resize_width_change)
        resize_layout.addWidget(self.spin_resize_width, 0, 1)

        resize_layout.addWidget(QLabel("Height:"), 1, 0)
        self.spin_resize_height = QSpinBox()
        self.spin_resize_height.setRange(1, 9999)
        self.spin_resize_height.setValue(32)
        self.spin_resize_height.valueChanged.connect(self.on_resize_height_change)
        resize_layout.addWidget(self.spin_resize_height, 1, 1)

        self.chk_keep_aspect = QCheckBox("Keep Aspect Ratio")
        self.chk_keep_aspect.setChecked(True)
        resize_layout.addWidget(self.chk_keep_aspect, 2, 0, 1, 2)

        resize_layout.addWidget(QLabel("Method:"), 3, 0)
        self.combo_resize_method = QComboBox()
        self.combo_resize_method.addItems(["Nearest (Pixel Art)", "Bilinear", "Bicubic", "Lanczos"])
        self.combo_resize_method.setCurrentIndex(0)
        resize_layout.addWidget(self.combo_resize_method, 3, 1)

        self.btn_apply_resize = QPushButton("Apply Resize")
        self.btn_apply_resize.setStyleSheet("background-color: #007acc; font-weight: bold;")
        self.btn_apply_resize.clicked.connect(self.apply_resize)
        self.btn_apply_resize.setEnabled(False)
        resize_layout.addWidget(self.btn_apply_resize, 4, 0, 1, 2)

        self.btn_reset_image = QPushButton("Reset Original")
        self.btn_reset_image.clicked.connect(self.reset_to_original)
        self.btn_reset_image.setEnabled(False)
        resize_layout.addWidget(self.btn_reset_image, 5, 0, 1, 2)

        # Na função init_ui, dentro da tab_resize, após grp_resize:

        grp_resize.setLayout(resize_layout)
        tab_resize_layout.addWidget(grp_resize)

        # NOVO GRUPO - Edge Detection & Outline
        grp_edges = QGroupBox("Edge Detection & Outline")
        edges_layout = QGridLayout()

        # Detector de Bordas
        edges_layout.addWidget(QLabel("Edge Detection:"), 0, 0, 1, 2)

        self.btn_detect_edges = QPushButton("Detect Edges")
        self.btn_detect_edges.setStyleSheet("background-color: #6c757d; font-weight: bold;")
        self.btn_detect_edges.clicked.connect(self.detect_edges)
        self.btn_detect_edges.setEnabled(False)
        edges_layout.addWidget(self.btn_detect_edges, 1, 0, 1, 2)

        # Outline Tool
        edges_layout.addWidget(QLabel("Outline:"), 2, 0, 1, 2)

        edges_layout.addWidget(QLabel("Color:"), 3, 0)
        self.btn_outline_color = QPushButton("Choose")
        self.btn_outline_color.setStyleSheet("background-color: #555;")
        self.btn_outline_color.clicked.connect(self.choose_outline_color)
        self.btn_outline_color.setEnabled(False)
        edges_layout.addWidget(self.btn_outline_color, 3, 1)

        self.lbl_outline_color_preview = QLabel()
        self.lbl_outline_color_preview.setFixedHeight(25)
        self.lbl_outline_color_preview.setStyleSheet("background-color: #000000; border: 1px solid #222;")
        edges_layout.addWidget(self.lbl_outline_color_preview, 4, 0, 1, 2)

        edges_layout.addWidget(QLabel("Thickness:"), 5, 0)
        self.spin_outline_thickness = QSpinBox()
        self.spin_outline_thickness.setRange(1, 20)
        self.spin_outline_thickness.setValue(2)
        self.spin_outline_thickness.setSuffix("px")
        edges_layout.addWidget(self.spin_outline_thickness, 5, 1)

        edges_layout.addWidget(QLabel("Feathering:"), 6, 0)
        self.spin_outline_feathering = QSpinBox()
        self.spin_outline_feathering.setRange(0, 100)
        self.spin_outline_feathering.setValue(0)
        self.spin_outline_feathering.setSuffix("%")
        self.spin_outline_feathering.setToolTip("0% = bordas duras, 100% = máxima suavização")
        edges_layout.addWidget(self.spin_outline_feathering, 6, 1)

        self.btn_apply_outline = QPushButton("Apply Outline")
        self.btn_apply_outline.setStyleSheet("background-color: #17a2b8; font-weight: bold;")
        self.btn_apply_outline.clicked.connect(self.apply_outline)
        self.btn_apply_outline.setEnabled(False)
        edges_layout.addWidget(self.btn_apply_outline, 7, 0, 1, 2)

        # Edge Eraser
        edges_layout.addWidget(QLabel("Edge Eraser:"), 8, 0, 1, 2)

        edges_layout.addWidget(QLabel("Distance:"), 9, 0)
        self.spin_edge_eraser_distance = QSpinBox()
        self.spin_edge_eraser_distance.setRange(1, 50)
        self.spin_edge_eraser_distance.setValue(5)
        self.spin_edge_eraser_distance.setSuffix("px")
        self.spin_edge_eraser_distance.setToolTip("Distância das bordas para apagar")
        edges_layout.addWidget(self.spin_edge_eraser_distance, 9, 1)

        edges_layout.addWidget(QLabel("Feathering:"), 10, 0)
        self.spin_edge_eraser_feathering = QSpinBox()
        self.spin_edge_eraser_feathering.setRange(0, 100)
        self.spin_edge_eraser_feathering.setValue(0)
        self.spin_edge_eraser_feathering.setSuffix("%")
        edges_layout.addWidget(self.spin_edge_eraser_feathering, 10, 1)

        self.btn_erase_edges = QPushButton("Erase Edges")
        self.btn_erase_edges.setStyleSheet("background-color: #dc3545; font-weight: bold;")
        self.btn_erase_edges.clicked.connect(self.erase_edges)
        self.btn_erase_edges.setEnabled(False)
        edges_layout.addWidget(self.btn_erase_edges, 11, 0, 1, 2)

        grp_edges.setLayout(edges_layout)
        tab_resize_layout.addWidget(grp_edges)

        tab_resize_layout.addStretch()
                
       

        tab_transparency = QWidget()
        tab_transparency_layout = QVBoxLayout(tab_transparency)

        # GRUPO 1: Remove Color (já existente)
        grp_transparency = QGroupBox("Remove Color")
        transparency_layout = QGridLayout()

        transparency_layout.addWidget(QLabel("Hex Color:"), 0, 0)
        self.line_hex_color = QLineEdit()
        self.line_hex_color.setPlaceholderText("#dcff73")
        self.line_hex_color.setMaxLength(7)
        self.line_hex_color.textChanged.connect(self.update_color_preview)
        transparency_layout.addWidget(self.line_hex_color, 0, 1)

        transparency_layout.addWidget(QLabel("Tolerance:"), 1, 0)
        self.spin_tolerance = QSpinBox()
        self.spin_tolerance.setRange(0, 255)
        self.spin_tolerance.setValue(0)
        self.spin_tolerance.setToolTip("0 = cor exata, valores maiores = cores similares")
        transparency_layout.addWidget(self.spin_tolerance, 1, 1)

        self.btn_pick_color = QPushButton("Pick Color from Image")
        self.btn_pick_color.setStyleSheet("background-color: #555;")
        self.btn_pick_color.clicked.connect(self.enable_color_picker)
        self.btn_pick_color.setEnabled(False)
        transparency_layout.addWidget(self.btn_pick_color, 2, 0, 1, 2)

        self.lbl_preview_color = QLabel()
        self.lbl_preview_color.setFixedHeight(30)
        self.lbl_preview_color.setStyleSheet("background-color: #dcff73; border: 1px solid #222;")
        transparency_layout.addWidget(self.lbl_preview_color, 3, 0, 1, 2)

        self.btn_remove_color = QPushButton("Remove Color")
        self.btn_remove_color.setStyleSheet("background-color: #dc3545; font-weight: bold; color: white;")
        self.btn_remove_color.clicked.connect(self.remove_color_to_transparent)
        self.btn_remove_color.setEnabled(False)
        transparency_layout.addWidget(self.btn_remove_color, 4, 0, 1, 2)

        grp_transparency.setLayout(transparency_layout)
        tab_transparency_layout.addWidget(grp_transparency)
        
        
       
        self.btn_remove_bg_ai = QPushButton("Remove Background (AI)")
        self.btn_remove_bg_ai.setStyleSheet("background-color: #9c27b0; font-weight: bold; color: white;")
        self.btn_remove_bg_ai.clicked.connect(self.remove_background_ai)
        self.btn_remove_bg_ai.setEnabled(False)

        if not REMBG_AVAILABLE:  # ← Use a variável global
            self.btn_remove_bg_ai.setToolTip("rembg não instalado")
        else:
            self.btn_remove_bg_ai.setToolTip("Remove background usando IA (U2Net)")

        transparency_layout.addWidget(self.btn_remove_bg_ai, 5, 0, 1, 2)

        

        # GRUPO 2: Color Adjustments (NOVO)
        grp_color_adjust = QGroupBox("Color Adjustments")
        color_adjust_layout = QGridLayout()

        # Brightness
        color_adjust_layout.addWidget(QLabel("Brightness:"), 0, 0)
        self.slider_brightness = QSlider(Qt.Orientation.Horizontal)
        self.slider_brightness.setRange(-100, 100)
        self.slider_brightness.setValue(0)
        self.slider_brightness.valueChanged.connect(self.on_brightness_change)
        color_adjust_layout.addWidget(self.slider_brightness, 0, 1)
        self.lbl_brightness = QLabel("0")
        self.lbl_brightness.setFixedWidth(40)
        self.lbl_brightness.setAlignment(Qt.AlignmentFlag.AlignRight)
        color_adjust_layout.addWidget(self.lbl_brightness, 0, 2)

        # Contrast
        color_adjust_layout.addWidget(QLabel("Contrast:"), 1, 0)
        self.slider_contrast = QSlider(Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(-100, 100)
        self.slider_contrast.setValue(0)
        self.slider_contrast.valueChanged.connect(self.on_contrast_change)
        color_adjust_layout.addWidget(self.slider_contrast, 1, 1)
        self.lbl_contrast = QLabel("0")
        self.lbl_contrast.setFixedWidth(40)
        self.lbl_contrast.setAlignment(Qt.AlignmentFlag.AlignRight)
        color_adjust_layout.addWidget(self.lbl_contrast, 1, 2)

        # Saturation
        color_adjust_layout.addWidget(QLabel("Saturation:"), 2, 0)
        self.slider_saturation = QSlider(Qt.Orientation.Horizontal)
        self.slider_saturation.setRange(-100, 100)
        self.slider_saturation.setValue(0)
        self.slider_saturation.valueChanged.connect(self.on_saturation_change)
        color_adjust_layout.addWidget(self.slider_saturation, 2, 1)
        self.lbl_saturation = QLabel("0")
        self.lbl_saturation.setFixedWidth(40)
        self.lbl_saturation.setAlignment(Qt.AlignmentFlag.AlignRight)
        color_adjust_layout.addWidget(self.lbl_saturation, 2, 2)

        # Separador visual
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #666;")
        color_adjust_layout.addWidget(separator, 3, 0, 1, 3)

        # Red
        color_adjust_layout.addWidget(QLabel("Red:"), 4, 0)
        self.slider_red = QSlider(Qt.Orientation.Horizontal)
        self.slider_red.setRange(-100, 100)
        self.slider_red.setValue(0)
        self.slider_red.valueChanged.connect(self.on_red_change)
        color_adjust_layout.addWidget(self.slider_red, 4, 1)
        self.lbl_red = QLabel("0")
        self.lbl_red.setFixedWidth(40)
        self.lbl_red.setAlignment(Qt.AlignmentFlag.AlignRight)
        color_adjust_layout.addWidget(self.lbl_red, 4, 2)

        # Green
        color_adjust_layout.addWidget(QLabel("Green:"), 5, 0)
        self.slider_green = QSlider(Qt.Orientation.Horizontal)
        self.slider_green.setRange(-100, 100)
        self.slider_green.setValue(0)
        self.slider_green.valueChanged.connect(self.on_green_change)
        color_adjust_layout.addWidget(self.slider_green, 5, 1)
        self.lbl_green = QLabel("0")
        self.lbl_green.setFixedWidth(40)
        self.lbl_green.setAlignment(Qt.AlignmentFlag.AlignRight)
        color_adjust_layout.addWidget(self.lbl_green, 5, 2)

        # Blue
        color_adjust_layout.addWidget(QLabel("Blue:"), 6, 0)
        self.slider_blue = QSlider(Qt.Orientation.Horizontal)
        self.slider_blue.setRange(-100, 100)
        self.slider_blue.setValue(0)
        self.slider_blue.valueChanged.connect(self.on_blue_change)
        color_adjust_layout.addWidget(self.slider_blue, 6, 1)
        self.lbl_blue = QLabel("0")
        self.lbl_blue.setFixedWidth(40)
        self.lbl_blue.setAlignment(Qt.AlignmentFlag.AlignRight)
        color_adjust_layout.addWidget(self.lbl_blue, 6, 2)

        # Botão Apply
        self.btn_apply_color = QPushButton("Apply")
        self.btn_apply_color.setStyleSheet("background-color: #28a745; font-weight: bold; color: white;")
        self.btn_apply_color.clicked.connect(self.apply_color_adjustments)
        self.btn_apply_color.setEnabled(False)
        color_adjust_layout.addWidget(self.btn_apply_color, 7, 0, 1, 3)

        # Botão Reset
        self.btn_reset_color = QPushButton("Reset")
        self.btn_reset_color.clicked.connect(self.reset_color_sliders)
        color_adjust_layout.addWidget(self.btn_reset_color, 8, 0, 1, 3)

        grp_color_adjust.setLayout(color_adjust_layout)
        tab_transparency_layout.addWidget(grp_color_adjust)

        tab_transparency_layout.addStretch()
        
        
             
        grp_paint = QGroupBox("Paint Brush")
        paint_layout = QGridLayout()
        
        paint_layout.addWidget(QLabel("Brush Size:"), 0, 0)
        self.spin_paint_size = QSpinBox()
        self.spin_paint_size.setRange(1, 100)
        self.spin_paint_size.setValue(5)
        self.spin_paint_size.valueChanged.connect(self.on_paint_size_change)
        paint_layout.addWidget(self.spin_paint_size, 0, 1)
        

        paint_layout.addWidget(QLabel("Feathering:"), 1, 0)
        self.spin_paint_feathering = QSpinBox()
        self.spin_paint_feathering.setRange(0, 100)
        self.spin_paint_feathering.setValue(0)
        self.spin_paint_feathering.setSuffix("%")
        self.spin_paint_feathering.setToolTip("0% = bordas duras, 100% = máxima suavização")
        self.spin_paint_feathering.valueChanged.connect(self.on_paint_feathering_change)
        paint_layout.addWidget(self.spin_paint_feathering, 1, 1)
        
        self.btn_choose_color = QPushButton("Choose Color")
        self.btn_choose_color.setStyleSheet("background-color: #555;")
        self.btn_choose_color.clicked.connect(self.choose_paint_color)
        self.btn_choose_color.setEnabled(False)
        paint_layout.addWidget(self.btn_choose_color, 2, 0, 1, 2)
        

        self.btn_pick_paint_color = QPushButton("Pick Color from Image")
        self.btn_pick_paint_color.setStyleSheet("background-color: #555;")
        self.btn_pick_paint_color.clicked.connect(self.enable_paint_color_picker)
        self.btn_pick_paint_color.setEnabled(False)
        paint_layout.addWidget(self.btn_pick_paint_color, 3, 0, 1, 2)
        
        self.lbl_paint_color_preview = QLabel()
        self.lbl_paint_color_preview.setFixedHeight(30)
        self.lbl_paint_color_preview.setStyleSheet("background-color: #000000; border: 1px solid #222;")
        paint_layout.addWidget(self.lbl_paint_color_preview, 4, 0, 1, 2)
        
        self.btn_toggle_paint = QPushButton("Enable Paint")
        self.btn_toggle_paint.setCheckable(True)
        self.btn_toggle_paint.setStyleSheet("background-color: #9b59b6; font-weight: bold;")
        self.btn_toggle_paint.clicked.connect(self.toggle_paint_mode)
        self.btn_toggle_paint.setEnabled(False)
        paint_layout.addWidget(self.btn_toggle_paint, 5, 0, 1, 2)
        
        grp_paint.setLayout(paint_layout)
        tab_transparency_layout.addWidget(grp_paint)        

        

        tab_slice = QWidget()
        tab_slice_layout = QVBoxLayout(tab_slice)

        grp_cells = QGroupBox("Cells")
        grp_cells_layout = QGridLayout()


        self.chk_empty = QCheckBox("Empty Sprites")
        self.chk_empty.setToolTip("Se marcado, salva sprites mesmo se forem transparentes")
        grp_cells_layout.addWidget(self.chk_empty, 1, 0, 1, 2)

        grp_cells_layout.addWidget(QLabel("X:"), 2, 0)
        self.spin_x = QSpinBox()
        self.spin_x.setRange(0, 9999)
        self.spin_x.valueChanged.connect(self.on_spinbox_change)
        grp_cells_layout.addWidget(self.spin_x, 2, 1)

        grp_cells_layout.addWidget(QLabel("Y:"), 3, 0)
        self.spin_y = QSpinBox()
        self.spin_y.setRange(0, 9999)
        self.spin_y.valueChanged.connect(self.on_spinbox_change)
        grp_cells_layout.addWidget(self.spin_y, 3, 1)

        grp_cells_layout.addWidget(QLabel("Cols:"), 4, 0)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 100)
        self.spin_cols.setValue(1)
        self.spin_cols.valueChanged.connect(self.update_grid_visuals)
        grp_cells_layout.addWidget(self.spin_cols, 4, 1)

        grp_cells_layout.addWidget(QLabel("Rows:"), 5, 0)
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 100)
        self.spin_rows.setValue(1)
        self.spin_rows.valueChanged.connect(self.update_grid_visuals)
        grp_cells_layout.addWidget(self.spin_rows, 5, 1)

        grp_cells.setLayout(grp_cells_layout)
        tab_slice_layout.addWidget(grp_cells)

        self.btn_cut = QPushButton("CUT IMAGE")
        self.btn_cut.setFixedHeight(40)
        self.btn_cut.setStyleSheet("background-color: #007acc; font-weight: bold; color: white;")
        self.btn_cut.clicked.connect(self.cut_image)
        tab_slice_layout.addWidget(self.btn_cut)
        
        grp_eraser = QGroupBox("Eraser Tool")
        eraser_layout = QGridLayout()

        eraser_layout.addWidget(QLabel("Brush Size:"), 0, 0)
        self.spin_eraser_size = QSpinBox()
        self.spin_eraser_size.setRange(1, 100)
        self.spin_eraser_size.setValue(10)
        self.spin_eraser_size.valueChanged.connect(self.on_eraser_size_change)
        eraser_layout.addWidget(self.spin_eraser_size, 0, 1)

        eraser_layout.addWidget(QLabel("Feathering:"), 1, 0)
        self.spin_eraser_feathering = QSpinBox()
        self.spin_eraser_feathering.setRange(0, 100)
        self.spin_eraser_feathering.setValue(0)
        self.spin_eraser_feathering.setSuffix("%")
        self.spin_eraser_feathering.setToolTip("0% = bordas duras, 100% = máxima suavização")
        self.spin_eraser_feathering.valueChanged.connect(self.on_eraser_feathering_change)
        eraser_layout.addWidget(self.spin_eraser_feathering, 1, 1)

        self.btn_toggle_eraser = QPushButton("Enable Eraser")
        self.btn_toggle_eraser.setCheckable(True)
        self.btn_toggle_eraser.setStyleSheet("background-color: #ff6b6b; font-weight: bold;")
        self.btn_toggle_eraser.clicked.connect(self.toggle_eraser_mode)
        self.btn_toggle_eraser.setEnabled(False)
        eraser_layout.addWidget(self.btn_toggle_eraser, 2, 0, 1, 2)  # Atualizar linha

        grp_eraser.setLayout(eraser_layout)
        tab_slice_layout.addWidget(grp_eraser)


        grp_selection = QGroupBox("Selection Tool")
        selection_layout = QGridLayout()
        
        self.btn_toggle_selection = QPushButton("Enable Selection")
        self.btn_toggle_selection.setCheckable(True)
        self.btn_toggle_selection.setStyleSheet("background-color: #ffa500; font-weight: bold;")
        self.btn_toggle_selection.clicked.connect(self.toggle_selection_mode)
        self.btn_toggle_selection.setEnabled(False)
        selection_layout.addWidget(self.btn_toggle_selection, 0, 0, 1, 2)
        
        self.btn_cut_selection = QPushButton("Cut Selection")
        self.btn_cut_selection.setStyleSheet("background-color: #e74c3c; font-weight: bold;")
        self.btn_cut_selection.clicked.connect(self.cut_selection)
        self.btn_cut_selection.setEnabled(False)
        selection_layout.addWidget(self.btn_cut_selection, 1, 0, 1, 2)
        
        self.btn_copy_selection = QPushButton("Copy Selection")
        self.btn_copy_selection.setStyleSheet("background-color: #3498db; font-weight: bold;")
        self.btn_copy_selection.clicked.connect(self.copy_selection)
        self.btn_copy_selection.setEnabled(False)
        self.btn_copy_selection.setVisible(False)
        selection_layout.addWidget(self.btn_copy_selection, 2, 0, 1, 2)
        
        self.btn_paste_selection = QPushButton("Paste")
        self.btn_paste_selection.setStyleSheet("background-color: #2ecc71; font-weight: bold;")
        self.btn_paste_selection.clicked.connect(self.paste_selection)
        self.btn_paste_selection.setEnabled(False)
        self.btn_paste_selection.setVisible(False)
        selection_layout.addWidget(self.btn_paste_selection, 3, 0, 1, 2)
        
        self.btn_clear_selection = QPushButton("Clear Selection")
        self.btn_clear_selection.clicked.connect(self.clear_selection)
        self.btn_clear_selection.setEnabled(False)
        selection_layout.addWidget(self.btn_clear_selection, 4, 0, 1, 2)
        
        grp_selection.setLayout(selection_layout)
        tab_slice_layout.addWidget(grp_selection)

        tab_slice_layout.addStretch()
        
        
        # GRUPO: Fine Grid
        grp_fine_grid = QGroupBox("Fine Grid")
        fine_grid_layout = QGridLayout()

        self.chk_enable_fine_grid = QCheckBox("Enable Fine Grid")
        self.chk_enable_fine_grid.setToolTip("Mostra grid fino sobre toda a imagem")
        self.chk_enable_fine_grid.toggled.connect(self.toggle_fine_grid)
        self.chk_enable_fine_grid.setEnabled(False)
        fine_grid_layout.addWidget(self.chk_enable_fine_grid, 0, 0, 1, 2)

        fine_grid_layout.addWidget(QLabel("Spacing:"), 1, 0)
        self.spin_fine_grid_spacing = QSpinBox()
        self.spin_fine_grid_spacing.setRange(1, 32)
        self.spin_fine_grid_spacing.setValue(4)
        self.spin_fine_grid_spacing.setSuffix("px")
        self.spin_fine_grid_spacing.valueChanged.connect(self.on_fine_grid_spacing_change)
        fine_grid_layout.addWidget(self.spin_fine_grid_spacing, 1, 1)

        grp_fine_grid.setLayout(fine_grid_layout)
        tab_slice_layout.addWidget(grp_fine_grid)
                
        
        

        tab_upscale = QWidget()
        tab_upscale_layout = QVBoxLayout(tab_upscale)

        # GRUPO 1: Denoise (que já discutimos)
        grp_denoise = QGroupBox("Denoise (Noise Reduction)")
        denoise_layout = QGridLayout()

        denoise_layout.addWidget(QLabel("Method:"), 0, 0)
        self.combo_denoise_method = QComboBox()
        self.combo_denoise_method.addItems([
            "Median Filter",
            "Gaussian Blur", 
            "Smooth Filter",
            "Smooth More"
        ])
        denoise_layout.addWidget(self.combo_denoise_method, 0, 1)

        denoise_layout.addWidget(QLabel("Strength:"), 1, 0)
        self.spin_denoise_strength = QSpinBox()
        self.spin_denoise_strength.setRange(1, 10)
        self.spin_denoise_strength.setValue(3)
        self.spin_denoise_strength.setToolTip("Kernel size para Median ou raio para Gaussian")
        denoise_layout.addWidget(self.spin_denoise_strength, 1, 1)

        self.btn_apply_denoise = QPushButton("Apply Denoise")
        self.btn_apply_denoise.setStyleSheet("background-color: #17a2b8; font-weight: bold;")
        self.btn_apply_denoise.clicked.connect(self.apply_denoise)
        self.btn_apply_denoise.setEnabled(False)
        denoise_layout.addWidget(self.btn_apply_denoise, 2, 0, 1, 2)

        grp_denoise.setLayout(denoise_layout)
        tab_upscale_layout.addWidget(grp_denoise)

        grp_upscale = QGroupBox("AI Upscale (Real-ESRGAN)")
        upscale_layout = QGridLayout()

        upscale_layout.addWidget(QLabel("Model:"), 0, 0)
        self.combo_upscale_model = QComboBox()
        self.combo_upscale_model.addItems([
            "RealESRGAN x4 (General)",
            "RealESRGAN x4 Anime",
            "RealESRGAN x2",
        ])
        self.combo_upscale_model.setCurrentIndex(1)
        upscale_layout.addWidget(self.combo_upscale_model, 0, 1)

        upscale_layout.addWidget(QLabel("Scale Factor:"), 1, 0)
        self.combo_upscale_factor = QComboBox()
        self.combo_upscale_factor.addItems(["2x", "3x", "4x"])
        self.combo_upscale_factor.setCurrentIndex(2)
        upscale_layout.addWidget(self.combo_upscale_factor, 1, 1)

        # NOVA OPÇÃO: Manter resolução original
        self.chk_keep_original_size = QCheckBox("Keep Original Resolution")
        self.chk_keep_original_size.setChecked(False)
        self.chk_keep_original_size.setToolTip(
            "Faz upscale para melhorar qualidade, depois redimensiona\n"
            "de volta para a resolução original (melhora detalhes)"
        )
        upscale_layout.addWidget(self.chk_keep_original_size, 2, 0, 1, 2)

        # Opção de usar GPU
        self.chk_use_gpu = QCheckBox("Use GPU (CUDA)")
        self.chk_use_gpu.setChecked(False)
        self.chk_use_gpu.setToolTip("Requer NVIDIA GPU com CUDA instalado")
        upscale_layout.addWidget(self.chk_use_gpu, 3, 0, 1, 2)

        # Botão Apply
        self.btn_apply_upscale = QPushButton("Apply AI Upscale")
        self.btn_apply_upscale.setStyleSheet("background-color: #28a745; font-weight: bold;")
        self.btn_apply_upscale.clicked.connect(self.apply_ai_upscale)

        if not REALESRGAN_AVAILABLE:
            self.btn_apply_upscale.setEnabled(False)
            self.btn_apply_upscale.setToolTip("Real-ESRGAN não instalado")
        else:
            self.btn_apply_upscale.setEnabled(False)

        upscale_layout.addWidget(self.btn_apply_upscale, 4, 0, 1, 2)

        # Label de status
        self.lbl_upscale_status = QLabel("")
        self.lbl_upscale_status.setStyleSheet("color: #aaa; font-size: 10px;")
        self.lbl_upscale_status.setWordWrap(True)

        if not REALESRGAN_AVAILABLE:
            self.lbl_upscale_status.setText("⚠️ Real-ESRGAN não disponível")

        upscale_layout.addWidget(self.lbl_upscale_status, 5, 0, 1, 2)

        grp_upscale.setLayout(upscale_layout)
        tab_upscale_layout.addWidget(grp_upscale)


        tab_upscale_layout.addStretch()


        self.tab_widget.addTab(tab_resize, "Adjust")
        self.tab_widget.addTab(tab_transparency, "Color")
        self.tab_widget.addTab(tab_slice, "Tools")
        self.tab_widget.addTab(tab_upscale, "Upscale")

        lp_layout.addWidget(self.tab_widget)


        grp_zoom = QGroupBox("Zoom")
        zoom_layout = QVBoxLayout()
        self.slider_zoom = QSlider(Qt.Orientation.Horizontal)
        self.slider_zoom.setRange(10, 500)
        self.slider_zoom.setValue(100)
        self.slider_zoom.valueChanged.connect(self.on_zoom_change)
        zoom_layout.addWidget(self.slider_zoom)
        self.lbl_zoom_val = QLabel("100% (Ctrl+Scroll)")
        self.lbl_zoom_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_layout.addWidget(self.lbl_zoom_val)
        grp_zoom.setLayout(zoom_layout)
        lp_layout.addWidget(grp_zoom)

        lp_layout.addStretch()
        content_layout.addWidget(left_panel)

        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(50, 50, 50))
        
        self.view = ZoomableGraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setStyleSheet("border: none;")
        
        self.view.mousePressEvent = self.view_mouse_press
        self.view.mouseMoveEvent = self.view_mouse_move
        self.view.mouseReleaseEvent = self.view_mouse_release
        
        content_layout.addWidget(self.view, 1)


        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)

        self.grid_item = GridOverlay()
        self.grid_item.positionChanged.connect(self.on_grid_moved_by_mouse)
        self.scene.addItem(self.grid_item)


        right_panel = QFrame()
        right_panel.setFixedWidth(300)
        right_panel.setStyleSheet("background-color: #444; border-left: 1px solid #222;")
        rp_layout = QVBoxLayout(right_panel)

        rp_layout.addWidget(QLabel("Sprites:"))
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(self.list_widget.size()) 
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setStyleSheet("QListWidget { background-color: #333; } QListWidget::item:selected { background-color: #007acc; }")
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setIconSize(QSize(32, 32))
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        rp_layout.addWidget(self.list_widget)

        self.btn_export = QPushButton("Export PNG")
        self.btn_export.setFixedHeight(30)
        self.btn_export.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        self.btn_export.clicked.connect(self.export_sprites)
        self.btn_export.setEnabled(False)
        rp_layout.addWidget(self.btn_export)


        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.clear_list)
        rp_layout.addWidget(btn_clear)

        content_layout.addWidget(right_panel)
        
        
        
            
    def toggle_fine_grid(self, checked):
        self.fine_grid_enabled = checked
        if self.fine_grid_item:
            self.fine_grid_item.set_visible(checked)

    def on_fine_grid_spacing_change(self, value):
        self.fine_grid_spacing = value
        if self.fine_grid_item:
            self.fine_grid_item.set_spacing(value)

    def create_fine_grid(self):
        if self.fine_grid_item:
            self.scene.removeItem(self.fine_grid_item)
        
        if self.current_image_pil:
            w = self.current_image_pil.width
            h = self.current_image_pil.height
            rect = QRectF(0, 0, w, h)
            self.fine_grid_item = FineGridOverlay(rect, self.fine_grid_spacing)
            self.scene.addItem(self.fine_grid_item)
            self.fine_grid_item.set_visible(self.fine_grid_enabled)
        
        
        
    def remove_background_ai(self):

        if not self.current_image_pil:
            return
        
        if not REMBG_AVAILABLE:  # ← Use a variável global aqui
            QMessageBox.critical(
                self,
                "Biblioteca Faltando",
                "rembg não está instalado!\nInstale com: pip install rembg"
            )
            return
        
        self.save_state()
        
        try:
            from rembg import remove  # Importa aqui de novo (já foi importado no topo)
            import io
            
            # Mostrar mensagem de progresso
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            
            # Converte PIL Image para bytes
            img_byte_arr = io.BytesIO()
            self.current_image_pil.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            # Remove background
            output_data = remove(img_byte_arr)
            
            # Converte de volta para PIL Image
            output_image = Image.open(io.BytesIO(output_data))
            
            # Garante que está em RGBA
            if output_image.mode != 'RGBA':
                output_image = output_image.convert('RGBA')
            
            self.current_image_pil = output_image
            self.update_canvas_image()
            
            QApplication.restoreOverrideCursor()
            
            QMessageBox.information(
                self,
                "Background Removed",
                "Background removido automaticamente com sucesso usando IA!"
            )
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error", f"Erro ao remover background: {str(e)}")
            
        
        
        
    def apply_denoise(self):

        if not self.current_image_pil:
            return
        
        self.save_state()
        
        try:
            method = self.combo_denoise_method.currentIndex()
            strength = self.spin_denoise_strength.value()
            
            img = self.current_image_pil.copy()
            
            if method == 0:  # Median Filter
                kernel_size = strength if strength % 2 == 1 else strength + 1
                img = img.filter(ImageFilter.MedianFilter(size=kernel_size))
                
            elif method == 1:  # Gaussian Blur
                img = img.filter(ImageFilter.GaussianBlur(radius=strength))
                
            elif method == 2:  # Smooth
                for _ in range(strength):
                    img = img.filter(ImageFilter.SMOOTH)
                    
            elif method == 3:  # Smooth More
                for _ in range(strength):
                    img = img.filter(ImageFilter.SMOOTH_MORE)
            
            self.current_image_pil = img
            self.update_canvas_image()
            
            QMessageBox.information(
                self,
                "Denoise Applied",
                f"Denoise aplicado com sucesso!\nMétodo: {self.combo_denoise_method.currentText()}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Erro ao aplicar denoise: {str(e)}")

    def apply_ai_upscale(self):

        if not self.current_image_pil:
            return
        
        if not REALESRGAN_AVAILABLE:
            QMessageBox.critical(
                self,
                "Dependência Faltando",
                "Real-ESRGAN não está instalado!"
            )
            return
        
        # Guardar resolução original
        original_width = self.current_image_pil.width
        original_height = self.current_image_pil.height
        keep_original_size = self.chk_keep_original_size.isChecked()
        
        self.btn_apply_upscale.setEnabled(False)
        self.lbl_upscale_status.setText("⏳ Carregando modelo...")
        QApplication.processEvents()
        
        try:
            import numpy as np
            import cv2
            
            # Configurar device
            use_gpu = self.chk_use_gpu.isChecked()
            device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'
            
            # Determinar modelo e escala
            model_idx = self.combo_upscale_model.currentIndex()
            scale_text = self.combo_upscale_factor.currentText()
            scale = int(scale_text.replace('x', ''))
            
            self.lbl_upscale_status.setText(f"⏳ Inicializando modelo...")
            QApplication.processEvents()
            
            # Configurar modelo baseado na seleção
            if model_idx == 0:  # General x4
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
                model_path = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth'
                netscale = 4
            elif model_idx == 1:  # Anime x4
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
                model_path = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth'
                netscale = 4
            else:  # x2
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)
                model_path = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth'
                netscale = 2
            
            # Criar upsampler
            upsampler = RealESRGANer(
                scale=netscale,
                model_path=model_path,
                model=model,
                tile=0,
                tile_pad=10,
                pre_pad=0,
                half=False,
                device=device
            )
            
            self.lbl_upscale_status.setText("⏳ Processando upscale...")
            QApplication.processEvents()
            
            # Converter PIL para numpy array (BGR para OpenCV)
            img_rgb = self.current_image_pil.convert('RGB')
            img_np = np.array(img_rgb)
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            
            # Aplicar upscaling
            output, _ = upsampler.enhance(img_bgr, outscale=scale)
            
            # Converter de volta para PIL (BGR -> RGB)
            output_rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
            upscaled_image = Image.fromarray(output_rgb)
            
            # Se tinha transparência, processar canal alpha
            if self.current_image_pil.mode == 'RGBA':
                alpha = self.current_image_pil.split()[-1]
                alpha_upscaled = alpha.resize(
                    (upscaled_image.width, upscaled_image.height),
                    Image.LANCZOS
                )
                upscaled_image = upscaled_image.convert('RGBA')
                upscaled_image.putalpha(alpha_upscaled)
            
            # NOVA LÓGICA: Manter resolução original se checkbox marcada
            if keep_original_size:
                self.lbl_upscale_status.setText("⏳ Redimensionando para resolução original...")
                QApplication.processEvents()
                
                # Usar LANCZOS para melhor qualidade no downscale
                upscaled_image = upscaled_image.resize(
                    (original_width, original_height),
                    Image.LANCZOS
                )
                
                result_msg = (
                    f"Imagem processada com sucesso!\n\n"
                    f"Upscale temporário: {scale}x\n"
                    f"Resolução final: {original_width}x{original_height} (original mantida)\n"
                    f"Device: {device}\n\n"
                    f"Qualidade melhorada através de upscale + downscale!"
                )
            else:
                result_msg = (
                    f"Imagem upscaled com sucesso!\n\n"
                    f"Escala: {scale}x\n"
                    f"Resolução original: {original_width}x{original_height}\n"
                    f"Nova resolução: {upscaled_image.width}x{upscaled_image.height}\n"
                    f"Device: {device}"
                )
            
            # Salvar estado
            self.save_state()
            
            # Atualizar imagem
            self.current_image_pil = upscaled_image
            self.update_canvas_image()
            
            # Atualizar spinboxes
            self.spin_resize_width.setValue(upscaled_image.width)
            self.spin_resize_height.setValue(upscaled_image.height)
            
            if keep_original_size:
                self.lbl_upscale_status.setText(
                    f"✅ Upscale completo!\n"
                    f"Resolução mantida: {original_width}x{original_height}"
                )
            else:
                self.lbl_upscale_status.setText(
                    f"✅ Upscale completo! {scale}x\n"
                    f"Nova resolução: {upscaled_image.width}x{upscaled_image.height}"
                )
            
            QMessageBox.information(
                self,
                "AI Upscale Complete",
                result_msg
            )
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.lbl_upscale_status.setText(f"❌ Erro: {str(e)}")
            QMessageBox.critical(
                self,
                "Error",
                f"Erro ao aplicar AI upscale:\n{str(e)}\n\n{error_details}"
            )
        
        finally:
            self.btn_apply_upscale.setEnabled(True)

                
    def apply_denoise(self):

        if not self.current_image_pil:
            return
        
        self.save_state()
        
        try:
            method = self.combo_denoise_method.currentIndex()
            strength = self.spin_denoise_strength.value()
            
            img = self.current_image_pil.copy()
            
            if method == 0:  # Median Filter
                # Valor ímpar para o kernel
                kernel_size = strength if strength % 2 == 1 else strength + 1
                img = img.filter(ImageFilter.MedianFilter(size=kernel_size))
                
            elif method == 1:  # Gaussian Blur
                radius = strength
                img = img.filter(ImageFilter.GaussianBlur(radius=radius))
                
            elif method == 2:  # Smooth
                for _ in range(strength):
                    img = img.filter(ImageFilter.SMOOTH)
                    
            elif method == 3:  # Smooth More
                for _ in range(strength):
                    img = img.filter(ImageFilter.SMOOTH_MORE)
            
            self.current_image_pil = img
            self.update_canvas_image()
            
            QMessageBox.information(
                self,
                "Denoise Applied",
                f"Denoise aplicado com sucesso!\nMétodo: {self.combo_denoise_method.currentText()}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Erro ao aplicar denoise: {str(e)}")
                     
 
    def on_brightness_change(self, value):
        self.lbl_brightness.setText(str(value))

    def on_contrast_change(self, value):
        self.lbl_contrast.setText(str(value))

    def on_saturation_change(self, value):
        self.lbl_saturation.setText(str(value))

    def on_red_change(self, value):
        self.lbl_red.setText(str(value))

    def on_green_change(self, value):
        self.lbl_green.setText(str(value))

    def on_blue_change(self, value):
        self.lbl_blue.setText(str(value))

    def reset_color_sliders(self):
        """Reseta todos os sliders de cor para 0"""
        self.slider_brightness.setValue(0)
        self.slider_contrast.setValue(0)
        self.slider_saturation.setValue(0)
        self.slider_red.setValue(0)
        self.slider_green.setValue(0)
        self.slider_blue.setValue(0)

    def apply_color_adjustments(self):

        if not self.current_image_pil:
            return
        
        self.save_state()
        
        try:
            from PIL import ImageEnhance
            import numpy as np
            
            img = self.current_image_pil.copy()
            
   
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            

            brightness_val = self.slider_brightness.value()
            if brightness_val != 0:
                factor = 1.0 + (brightness_val / 100.0)
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(factor)
            

            contrast_val = self.slider_contrast.value()
            if contrast_val != 0:
                factor = 1.0 + (contrast_val / 100.0)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(factor)
            

            saturation_val = self.slider_saturation.value()
            if saturation_val != 0:
                factor = 1.0 + (saturation_val / 100.0)
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(factor)

            red_val = self.slider_red.value()
            green_val = self.slider_green.value()
            blue_val = self.slider_blue.value()
            
            if red_val != 0 or green_val != 0 or blue_val != 0:
           
                img_array = np.array(img)
                
                
                r, g, b, a = img_array[:,:,0], img_array[:,:,1], img_array[:,:,2], img_array[:,:,3]
                
      
                r = np.clip(r.astype(np.int16) + red_val, 0, 255).astype(np.uint8)
                g = np.clip(g.astype(np.int16) + green_val, 0, 255).astype(np.uint8)
                b = np.clip(b.astype(np.int16) + blue_val, 0, 255).astype(np.uint8)
                
      
                img_array[:,:,0] = r
                img_array[:,:,1] = g
                img_array[:,:,2] = b
                
                img = Image.fromarray(img_array, 'RGBA')
            
            self.current_image_pil = img
            self.update_canvas_image()
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            QMessageBox.critical(self, "Error", f"Erro ao aplicar ajustes: {str(e)}\n\n{error_details}")


        
    def on_eraser_feathering_change(self, value):

        self.eraser_feathering = value
        

    def toggle_paint_mode(self, checked):

        self.paint_mode = checked
        
        if checked:
            if self.eraser_mode:
                self.btn_toggle_eraser.setChecked(False)
                self.toggle_eraser_mode(False)
            if self.selection_mode:
                self.btn_toggle_selection.setChecked(False)
                self.toggle_selection_mode(False)
            
            self.btn_toggle_paint.setText("Disable Paint")
            self.btn_toggle_paint.setStyleSheet("background-color: #8e44ad; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.grid_item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, False)
        else:
            self.btn_toggle_paint.setText("Enable Paint")
            self.btn_toggle_paint.setStyleSheet("background-color: #9b59b6; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.grid_item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
            self.last_paint_point = None
    
    def on_paint_size_change(self, value):
        self.paint_size = value
    
    def on_paint_feathering_change(self, value):

        self.paint_feathering = value
    
    def choose_paint_color(self):

        color = QColorDialog.getColor(self.paint_color, self, "Escolher Cor do Pincel")
        
        if color.isValid():
            self.paint_color = color
            self.lbl_paint_color_preview.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #222;"
            )
    
    def enable_paint_color_picker(self):
        self.paint_color_picker_mode = True
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.view.mousePressEvent = self.pick_paint_color_from_image
        
    
    def pick_paint_color_from_image(self, event):
        if not self.paint_color_picker_mode or not self.current_image_pil:
            return
        
        scene_pos = self.view.mapToScene(event.pos())
        x = int(scene_pos.x())
        y = int(scene_pos.y())
        
        w, h = self.current_image_pil.size
        if 0 <= x < w and 0 <= y < h:
            pixel = self.current_image_pil.getpixel((x, y))
            r, g, b, a = pixel  
            

            self.paint_color = QColor(r, g, b, a)
            
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            self.lbl_paint_color_preview.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #222;"
            )
            
            QMessageBox.information(
                self,
                "Color Selected",
                f"Cor do pincel: {hex_color}\nRGBA: ({r}, {g}, {b}, {a})"
            )
        
        self.paint_color_picker_mode = False
        self.view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.view.mousePressEvent = self.view_mouse_press
    
    def paint_at_point(self, point):
        if not self.current_image_pil:
            return
        
        x, y = point.x(), point.y()
        w, h = self.current_image_pil.size
        
        if x < 0 or y < 0 or x >= w or y >= h:
            return
        
        radius = self.paint_size // 2
        
        r, g, b, a = self.paint_color.red(), self.paint_color.green(), \
                     self.paint_color.blue(), self.paint_color.alpha()
        
        if self.paint_feathering == 0:

            draw = ImageDraw.Draw(self.current_image_pil, 'RGBA')
            bbox = [x - radius, y - radius, x + radius, y + radius]
            draw.ellipse(bbox, fill=(r, g, b, a))
        else:

            blur_radius = int((self.paint_feathering / 100.0) * radius)
            
            margin = blur_radius + 10
            temp_size = (radius * 2 + margin * 2, radius * 2 + margin * 2)
            
 
            color_layer = Image.new('RGB', temp_size, (r, g, b))
            

            mask = Image.new('L', temp_size, 0)
            mask_draw = ImageDraw.Draw(mask)
            
            center = radius + margin
            
            mask_draw.ellipse(
                [center - radius, center - radius, center + radius, center + radius],
                fill=a 
            )
            
      
            if blur_radius > 0:
                mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            

            color_layer = color_layer.convert('RGBA')
            color_layer.putalpha(mask)
            
 
            paste_x = x - center
            paste_y = y - center
            

            self.current_image_pil.alpha_composite(color_layer, (paste_x, paste_y))
        
        self.update_canvas_image()


    def paint_line(self, start, end):
        if not self.current_image_pil:
            return
        
        x1, y1 = start.x(), start.y()
        x2, y2 = end.x(), end.y()
        
        distance = max(abs(x2 - x1), abs(y2 - y1))
        
        if distance == 0:
            self.paint_at_point(start)
            return
        
        for i in range(distance + 1):
            t = i / distance
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            self.paint_at_point(QPoint(x, y))
            
    def save_state(self):
        if self.current_image_pil:
            state = self.current_image_pil.copy()
            self.undo_stack.append(state)
            
            if len(self.undo_stack) > self.max_undo_steps:
                self.undo_stack.pop(0)
            
            self.redo_stack.clear()
    
    def undo(self):
        if not self.undo_stack:
            QMessageBox.information(self, "Undo", "Nada para desfazer!")
            return
        
        if self.current_image_pil:
            self.redo_stack.append(self.current_image_pil.copy())
        
        self.current_image_pil = self.undo_stack.pop()
        self.update_canvas_image()
    
    def redo(self):
        if not self.redo_stack:
            QMessageBox.information(self, "Redo", "Nada para refazer!")
            return
        
        if self.current_image_pil:
            self.undo_stack.append(self.current_image_pil.copy())
        
        self.current_image_pil = self.redo_stack.pop()
        self.update_canvas_image()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
        
        super().keyPressEvent(event)
    
    def update_zoom_label(self, zoom_percentage):
        self.lbl_zoom_val.setText(f"{zoom_percentage}% (Ctrl+Scroll)")
        
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(zoom_percentage)
        self.slider_zoom.blockSignals(False)

    def toggle_selection_mode(self, checked):
        self.selection_mode = checked
        
        if checked:
            if self.eraser_mode:
                self.btn_toggle_eraser.setChecked(False)
                self.toggle_eraser_mode(False)
            if self.paint_mode:
                self.btn_toggle_paint.setChecked(False)
                self.toggle_paint_mode(False)
            
            self.btn_toggle_selection.setText("Disable Selection")
            self.btn_toggle_selection.setStyleSheet("background-color: #27ae60; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.grid_item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, False)
        else:
            self.btn_toggle_selection.setText("Enable Selection")
            self.btn_toggle_selection.setStyleSheet("background-color: #ffa500; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.grid_item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
    
    def clear_selection(self):
        if self.selection_rect_item:
            self.scene.removeItem(self.selection_rect_item)
            self.selection_rect_item = None
        
        self.btn_cut_selection.setEnabled(False)
        self.btn_copy_selection.setEnabled(False)
        self.btn_clear_selection.setEnabled(False)
    
    def cut_selection(self):
        if not self.selection_rect_item or not self.current_image_pil:
            return
        
        self.save_state()
        
        self.copy_selection()
        
        rect = self.selection_rect_item.rect()
        x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        
        transparent_box = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        self.current_image_pil.paste(transparent_box, (x, y))
        
        self.update_canvas_image()
        self.clear_selection()
        
        QMessageBox.information(self, "Cut", "Seleção recortada.")
    
    def copy_selection(self):
        if not self.selection_rect_item or not self.current_image_pil:
            return
        
        rect = self.selection_rect_item.rect()
        x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        
        img_w, img_h = self.current_image_pil.size
        if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
            QMessageBox.warning(self, "Invalid Selection", "Seleção fora dos limites da imagem!")
            return
        
        box = (x, y, x + w, y + h)
        self.selected_image_data = self.current_image_pil.crop(box)
        
        self.btn_paste_selection.setEnabled(True)
    
    def paste_selection(self):
        if not self.selected_image_data or not self.current_image_pil:
            return
        
        self.save_state()
        
        img_w, img_h = self.current_image_pil.size
        sel_w, sel_h = self.selected_image_data.size
        
        x = (img_w - sel_w) // 2
        y = (img_h - sel_h) // 2
        
        self.current_image_pil.paste(self.selected_image_data, (x, y))
        self.update_canvas_image()
        
        QMessageBox.information(self, "Paste", f"Colado em ({x}, {y})")
    
    def toggle_eraser_mode(self, checked):
        self.eraser_mode = checked
        
        if checked:
            if self.selection_mode:
                self.btn_toggle_selection.setChecked(False)
                self.toggle_selection_mode(False)
            if self.paint_mode:
                self.btn_toggle_paint.setChecked(False)
                self.toggle_paint_mode(False)
            
            self.btn_toggle_eraser.setText("Disable Eraser")
            self.btn_toggle_eraser.setStyleSheet("background-color: #51cf66; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.grid_item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, False)
        else:
            self.btn_toggle_eraser.setText("Enable Eraser")
            self.btn_toggle_eraser.setStyleSheet("background-color: #ff6b6b; font-weight: bold;")
            self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self.grid_item.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsMovable, True)
            self.last_eraser_point = None
    
    def on_eraser_size_change(self, value):
        self.eraser_size = value
    
    def view_mouse_press(self, event):
        modifiers = QApplication.keyboardModifiers()
        item_at_pos = self.view.itemAt(event.pos())
        
        if self.eraser_mode and event.button() == Qt.MouseButton.LeftButton:
            self.save_state()
            scene_pos = self.view.mapToScene(event.pos())
            self.last_eraser_point = QPoint(int(scene_pos.x()), int(scene_pos.y()))
            self.erase_at_point(self.last_eraser_point)
            
        elif self.paint_mode and event.button() == Qt.MouseButton.LeftButton:
            self.save_state()
            scene_pos = self.view.mapToScene(event.pos())
            self.last_paint_point = QPoint(int(scene_pos.x()), int(scene_pos.y()))
            self.paint_at_point(self.last_paint_point)
            
        elif self.selection_mode and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(event.pos())
            

            if modifiers == Qt.KeyboardModifier.ControlModifier and self.selection_rect_item:

                if self.selection_rect_item.contains(self.selection_rect_item.mapFromScene(scene_pos)):
                    self.start_moving_selection(scene_pos)
                    return
            

            self.selection_start = scene_pos
            self.is_drawing_selection = True
            
            if self.selection_rect_item:
                self.scene.removeItem(self.selection_rect_item)
                if self.floating_selection_pixmap:
                    self.scene.removeItem(self.floating_selection_pixmap)
                    self.floating_selection_pixmap = None
            
            self.selection_rect_item = SelectionRectangle()
            self.scene.addItem(self.selection_rect_item)
        else:
            QGraphicsView.mousePressEvent(self.view, event)


    
    def view_mouse_move(self, event):
        if self.eraser_mode and event.buttons() & Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(event.pos())
            current_point = QPoint(int(scene_pos.x()), int(scene_pos.y()))
            
            if self.last_eraser_point:
                self.erase_line(self.last_eraser_point, current_point)
            
            self.last_eraser_point = current_point
            
        elif self.paint_mode and event.buttons() & Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(event.pos())
            current_point = QPoint(int(scene_pos.x()), int(scene_pos.y()))
            
            if self.last_paint_point:
                self.paint_line(self.last_paint_point, current_point)
            
            self.last_paint_point = current_point
            
        elif self.selection_mode:
      
            if self.is_moving_selection and event.buttons() & Qt.MouseButton.LeftButton:
                scene_pos = self.view.mapToScene(event.pos())
                self.move_selection(scene_pos)

            elif self.is_drawing_selection:
                scene_pos = self.view.mapToScene(event.pos())
                rect = QRectF(self.selection_start, scene_pos).normalized()
                self.selection_rect_item.set_rect(rect)
        else:
            QGraphicsView.mouseMoveEvent(self.view, event)

    def view_mouse_release(self, event):
        if self.eraser_mode:
            self.last_eraser_point = None
            
        elif self.paint_mode:
            self.last_paint_point = None
            
        elif self.selection_mode:
            if self.is_moving_selection:
                self.finish_moving_selection()
            elif self.is_drawing_selection:
                self.is_drawing_selection = False
                
                if self.selection_rect_item and not self.selection_rect_item.rect().isEmpty():
                    self.btn_cut_selection.setEnabled(True)
                    self.btn_copy_selection.setEnabled(True)
                    self.btn_clear_selection.setEnabled(True)
        else:
            QGraphicsView.mouseReleaseEvent(self.view, event)
            
            
    def start_moving_selection(self, scene_pos):

        if not self.current_image_pil or not self.selection_rect_item:
            return
        
        self.save_state()
        self.is_moving_selection = True
        self.move_start_pos = scene_pos
        

        rect = self.selection_rect_item.rect()
        x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        

        box = (x, y, x + w, y + h)
        self.selected_image_data = self.current_image_pil.crop(box)
        

        transparent_box = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        self.current_image_pil.paste(transparent_box, (x, y))
        self.update_canvas_image()
        
      
        qim = self.pil_to_qimage(self.selected_image_data)
        pix = QPixmap.fromImage(qim)
        
        if self.floating_selection_pixmap:
            self.scene.removeItem(self.floating_selection_pixmap)
        
        self.floating_selection_pixmap = QGraphicsPixmapItem(pix)
        self.floating_selection_pixmap.setPos(x, y)
        self.floating_selection_pixmap.setZValue(20)  
        self.scene.addItem(self.floating_selection_pixmap)
        
        self.view.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def move_selection(self, scene_pos):

        if not self.is_moving_selection or not self.move_start_pos:
            return
        

        delta = scene_pos - self.move_start_pos

        rect = self.selection_rect_item.rect()
        new_rect = rect.translated(delta.x(), delta.y())
        self.selection_rect_item.set_rect(new_rect)
        

        if self.floating_selection_pixmap:
            current_pos = self.floating_selection_pixmap.pos()
            self.floating_selection_pixmap.setPos(current_pos.x() + delta.x(), current_pos.y() + delta.y())
        
        self.move_start_pos = scene_pos

    def finish_moving_selection(self):

        if not self.is_moving_selection:
            return
        

        if self.floating_selection_pixmap:
            final_pos = self.floating_selection_pixmap.pos()
            x, y = int(final_pos.x()), int(final_pos.y())
            

            if self.selected_image_data:
                self.current_image_pil.paste(self.selected_image_data, (x, y))
                self.update_canvas_image()
            

            self.scene.removeItem(self.floating_selection_pixmap)
            self.floating_selection_pixmap = None
        
        self.is_moving_selection = False
        self.move_start_pos = None
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
                

    
    def erase_at_point(self, point):

        if not self.current_image_pil:
            return
        
        x, y = point.x(), point.y()
        w, h = self.current_image_pil.size
        
        if x < 0 or y < 0 or x >= w or y >= h:
            return
        
        radius = self.eraser_size // 2
        
        if self.eraser_feathering == 0:

            draw = ImageDraw.Draw(self.current_image_pil, 'RGBA')
            bbox = [x - radius, y - radius, x + radius, y + radius]
            

            temp = Image.new('RGBA', self.current_image_pil.size, (0, 0, 0, 0))
            temp_draw = ImageDraw.Draw(temp)
            temp_draw.ellipse(bbox, fill=(0, 0, 0, 255))
            
            mask = temp.split()[3]
            

            pixels = self.current_image_pil.load()
            mask_pixels = mask.load()
            
            for py in range(max(0, y - radius), min(h, y + radius + 1)):
                for px in range(max(0, x - radius), min(w, x + radius + 1)):
                    if mask_pixels[px, py] > 0:
                        pixels[px, py] = (0, 0, 0, 0)
        else:

            blur_radius = int((self.eraser_feathering / 100.0) * radius)
            

            margin = blur_radius + 10
            temp_size = (radius * 2 + margin * 2, radius * 2 + margin * 2)
            
            mask = Image.new('L', temp_size, 0)
            mask_draw = ImageDraw.Draw(mask)
            
            center = radius + margin
            
            mask_draw.ellipse(
                [center - radius, center - radius, center + radius, center + radius],
                fill=255
            )
            
            if blur_radius > 0:
                mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            
            paste_x = x - center
            paste_y = y - center
            
            mask_pixels = mask.load()
            img_pixels = self.current_image_pil.load()
            
            for py in range(temp_size[1]):
                for px in range(temp_size[0]):
                    img_x = paste_x + px
                    img_y = paste_y + py
                    
  
                    if 0 <= img_x < w and 0 <= img_y < h:

                        mask_alpha = mask_pixels[px, py]
                        
                        if mask_alpha > 0:
     
                            current_pixel = img_pixels[img_x, img_y]
                            r, g, b, a = current_pixel
                            
  
                            erase_factor = mask_alpha / 255.0
                            new_alpha = int(a * (1.0 - erase_factor))
                            
                            img_pixels[img_x, img_y] = (r, g, b, new_alpha)
        
        self.update_canvas_image()

    
    def erase_line(self, start, end):
        if not self.current_image_pil:
            return
        
        x1, y1 = start.x(), start.y()
        x2, y2 = end.x(), end.y()
        
        distance = max(abs(x2 - x1), abs(y2 - y1))
        
        if distance == 0:
            self.erase_at_point(start)
            return
        
        for i in range(distance + 1):
            t = i / distance
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            self.erase_at_point(QPoint(x, y))

    def update_grid_visuals(self):
        rows = self.spin_rows.value()
        cols = self.spin_cols.value()
        subs = self.chk_subdivisions.isChecked()
        self.grid_item.update_grid(rows, cols, subs)

    def open_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.bmp *.jpg)")
        if file_path:
            try:
                self.current_image_pil = Image.open(file_path).convert("RGBA")
                self.original_image_pil = self.current_image_pil.copy()
                
                self.undo_stack.clear()
                self.redo_stack.clear()
                
                w, h = self.current_image_pil.size
                self.spin_resize_width.blockSignals(True)
                self.spin_resize_height.blockSignals(True)
                self.spin_resize_width.setValue(w)
                self.spin_resize_height.setValue(h)
                self.spin_resize_width.blockSignals(False)
                self.spin_resize_height.blockSignals(False)
                
                self.update_canvas_image()
                
                self.grid_item.setPos(0, 0)
                self.spin_x.setValue(0)
                self.spin_y.setValue(0)
                
                self.btn_apply_resize.setEnabled(True)
                self.btn_reset_image.setEnabled(True)
                self.btn_pick_color.setEnabled(True)
                self.btn_remove_color.setEnabled(True)
                self.btn_toggle_eraser.setEnabled(True)
                self.btn_toggle_paint.setEnabled(True)
                self.btn_choose_color.setEnabled(True)
                self.btn_pick_paint_color.setEnabled(True)  # NOVO
                self.btn_toggle_selection.setEnabled(True)
                self.btn_detect_edges.setEnabled(True)
                self.btn_outline_color.setEnabled(True)
                self.btn_apply_outline.setEnabled(True)
                self.btn_erase_edges.setEnabled(True)
                self.btn_apply_denoise.setEnabled(True)
                self.btn_apply_upscale.setEnabled(True)
                self.btn_apply_color.setEnabled(True)
                self.btn_reset_color.setEnabled(True)
                self.chk_enable_fine_grid.setEnabled(True)
                

                # Onde você habilita os outros botões:
                if REMBG_AVAILABLE:  # ← Use a variável global
                    self.btn_remove_bg_ai.setEnabled(True)

                
                
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
                
                
    def update_color_preview(self, text):
        if self.hex_to_rgb(text):
            self.lbl_preview_color.setStyleSheet(f"background-color: {text}; border: 1px solid #222;")
        else:
            self.lbl_preview_color.setStyleSheet("background-color: #333; border: 1px solid #222;")
                
                
    def hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return None
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except ValueError:
            return None

    def remove_color_to_transparent(self):
        if not self.current_image_pil:
            return
        
        self.save_state()
        
        hex_color = self.line_hex_color.text().strip()
        target_rgb = self.hex_to_rgb(hex_color)
        
        if not target_rgb:
            QMessageBox.warning(self, "Invalid Color", "Digite uma cor hex válida (ex: #dcff73)")
            return
        
        tolerance = self.spin_tolerance.value()
        
        try:
            img = self.current_image_pil.convert("RGBA")
            datas = img.getdata()
            
            newData = []
            pixels_changed = 0
            
            for item in datas:
                r, g, b, a = item
                
                if tolerance == 0:
                    if (r, g, b) == target_rgb:
                        newData.append((r, g, b, 0))
                        pixels_changed += 1
                    else:
                        newData.append(item)
                else:
                    r_diff = abs(r - target_rgb[0])
                    g_diff = abs(g - target_rgb[1])
                    b_diff = abs(b - target_rgb[2])
                    
                    if r_diff <= tolerance and g_diff <= tolerance and b_diff <= tolerance:
                        newData.append((r, g, b, 0))
                        pixels_changed += 1
                    else:
                        newData.append(item)
            
            img.putdata(newData)
            self.current_image_pil = img
            self.update_canvas_image()
            
            QMessageBox.information(
                self,
                "Color Removed",
                f"Cor {hex_color} removida!\n{pixels_changed} pixels tornados transparentes."
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            
            
            
    def choose_outline_color(self):

        color = QColorDialog.getColor(self.outline_color, self, "Escolher Cor do Outline")
        
        if color.isValid():
            self.outline_color = color
            self.lbl_outline_color_preview.setStyleSheet(
                f"background-color: {color.name()}; border: 1px solid #222;"
            )

    def detect_edges(self):

        if not self.current_image_pil:
            return
        
        self.save_state()
        
        try:
      
            gray = self.current_image_pil.convert('L')
            
  
            edges = gray.filter(ImageFilter.FIND_EDGES)
            

            edges_rgba = edges.convert('RGBA')
            
      
            from PIL import ImageOps
            edges_inverted = ImageOps.invert(edges.convert('RGB'))
            edges_rgba = edges_inverted.convert('RGBA')

            pixels = edges_rgba.load()
            original_pixels = self.current_image_pil.load()
            w, h = edges_rgba.size
            
            for y in range(h):
                for x in range(w):
                    r, g, b, a = pixels[x, y]
                    orig_a = original_pixels[x, y][3]
                    
         
                    if r < 128 and orig_a > 0:
                        pixels[x, y] = (0, 0, 0, 255)  
                    else:
                        pixels[x, y] = (0, 0, 0, 0)  
            
            self.current_image_pil = edges_rgba
            self.update_canvas_image()
            
            QMessageBox.information(self, "Edge Detection", "Bordas detectadas com sucesso!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Erro ao detectar bordas: {str(e)}")

    def apply_outline(self):

        if not self.current_image_pil:
            return
        
        self.save_state()
        
        try:
            thickness = self.spin_outline_thickness.value()
            feathering = self.spin_outline_feathering.value()
            
  
            r = self.outline_color.red()
            g = self.outline_color.green()
            b = self.outline_color.blue()
            a = self.outline_color.alpha()
            
            w, h = self.current_image_pil.size
            

            outline_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            

            if self.current_image_pil.mode == 'RGBA':
                alpha_mask = self.current_image_pil.split()[3]
            else:
                alpha_mask = Image.new('L', (w, h), 255)
            
      
            from PIL import ImageFilter
            
 
            expanded_mask = alpha_mask.copy()
            for _ in range(thickness):
                expanded_mask = expanded_mask.filter(ImageFilter.MaxFilter(3))
            
 
            if feathering > 0:
                blur_amount = (feathering / 100.0) * thickness
                expanded_mask = expanded_mask.filter(ImageFilter.GaussianBlur(radius=blur_amount))
            
   
            outline_color_layer = Image.new('RGBA', (w, h), (r, g, b, a))
            
     
            outline_layer.paste(outline_color_layer, (0, 0), expanded_mask)
            
            outline_pixels = outline_layer.load()
            alpha_pixels = alpha_mask.load()
            
            for y in range(h):
                for x in range(w):
                    if alpha_pixels[x, y] > 128:  
                        outline_pixels[x, y] = (0, 0, 0, 0)  
            

            result = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            result.paste(outline_layer, (0, 0), outline_layer)
            result.paste(self.current_image_pil, (0, 0), self.current_image_pil)
            
            self.current_image_pil = result
            self.update_canvas_image()
            
            QMessageBox.information(self, "Outline Applied", 
                                  f"Outline de {thickness}px aplicado com sucesso!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Erro ao aplicar outline: {str(e)}")

    def erase_edges(self):
        if not self.current_image_pil:
            return
        
        self.save_state()
        
        try:
            distance = self.spin_edge_eraser_distance.value()
            feathering = self.spin_edge_eraser_feathering.value()
            
            w, h = self.current_image_pil.size
            
            if self.current_image_pil.mode == 'RGBA':
                alpha = self.current_image_pil.split()[3]
            else:
                self.current_image_pil = self.current_image_pil.convert('RGBA')
                alpha = self.current_image_pil.split()[3]
            

            eroded_mask = alpha.copy()
            for _ in range(distance):
                eroded_mask = eroded_mask.filter(ImageFilter.MinFilter(3))
            
            if feathering > 0:
                blur_amount = (feathering / 100.0) * distance
                eroded_mask = eroded_mask.filter(ImageFilter.GaussianBlur(radius=blur_amount))
            
            self.current_image_pil.putalpha(eroded_mask)
            
            self.update_canvas_image()
            
            QMessageBox.information(self, "Edge Eraser", 
                                  f"Bordas apagadas em {distance}px!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Erro ao apagar bordas: {str(e)}")
            

    def enable_color_picker(self):
        self.color_picker_mode = True
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        
        self.original_mouse_press = self.view.mousePressEvent
        self.view.mousePressEvent = self.pick_color_from_image
        

    def pick_color_from_image(self, event):
        if not self.color_picker_mode or not self.current_image_pil:
            return
        
        scene_pos = self.view.mapToScene(event.pos())
        x = int(scene_pos.x())
        y = int(scene_pos.y())
        
        w, h = self.current_image_pil.size
        if 0 <= x < w and 0 <= y < h:
            pixel = self.current_image_pil.getpixel((x, y))
            r, g, b = pixel[:3]
            
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            self.line_hex_color.setText(hex_color)
            self.lbl_preview_color.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #222;")
            
            QMessageBox.information(
                self,
                "Color Selected",
                f"Cor selecionada: {hex_color}\nRGB: ({r}, {g}, {b})"
            )
        
        self.color_picker_mode = False
        self.view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.view.mousePressEvent = self.view_mouse_press
                    
                
                
    def on_resize_width_change(self, value):
        if self.chk_keep_aspect.isChecked() and self.original_image_pil:
            w, h = self.original_image_pil.size
            aspect_ratio = h / w
            new_height = int(value * aspect_ratio)
            self.spin_resize_height.blockSignals(True)
            self.spin_resize_height.setValue(new_height)
            self.spin_resize_height.blockSignals(False)

    def on_resize_height_change(self, value):
        if self.chk_keep_aspect.isChecked() and self.original_image_pil:
            w, h = self.original_image_pil.size
            aspect_ratio = w / h
            new_width = int(value * aspect_ratio)
            self.spin_resize_width.blockSignals(True)
            self.spin_resize_width.setValue(new_width)
            self.spin_resize_width.blockSignals(False)

    def apply_resize(self):
        """Aplica o resize na imagem atual"""
        if not self.original_image_pil:
            return
        
        self.save_state()
        
        new_width = self.spin_resize_width.value()
        new_height = self.spin_resize_height.value()
        
        method_map = {
            0: Image.NEAREST,
            1: Image.BILINEAR,
            2: Image.BICUBIC,
            3: Image.LANCZOS
        }
        
        resize_method = method_map[self.combo_resize_method.currentIndex()]
        
        try:
            self.current_image_pil = self.original_image_pil.resize(
                (new_width, new_height), 
                resize_method
            )
            self.update_canvas_image()
            
            QMessageBox.information(
                self,
                "Resize Applied",
                f"Image resized to {new_width}x{new_height}px"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Resize Error", str(e))

    def reset_to_original(self):
        if not self.original_image_pil:
            return
        
        self.save_state()
        
        self.current_image_pil = self.original_image_pil.copy()
        
        w, h = self.current_image_pil.size
        self.spin_resize_width.blockSignals(True)
        self.spin_resize_height.blockSignals(True)
        self.spin_resize_width.setValue(w)
        self.spin_resize_height.setValue(h)
        self.spin_resize_width.blockSignals(False)
        self.spin_resize_height.blockSignals(False)
         # Na função reset_to_original() e onde limpar a imagem:
        self.btn_remove_bg_ai.setEnabled(False)
       
        
        self.update_canvas_image()
                    
    def update_canvas_image(self):
        if self.current_image_pil:
            qim = self.pil_to_qimage(self.current_image_pil)
            pix = QPixmap.fromImage(qim)
            self.pixmap_item.setPixmap(pix)
            self.create_fine_grid()

            self.scene.setSceneRect(QRectF(pix.rect()))
            
            w, h = self.current_image_pil.size
            self.spin_x.setRange(0, w)
            self.spin_y.setRange(0, h)

    def transform_image(self, mode):
        if not self.current_image_pil: return
        
        self.save_state()
        
        if mode == "rotate_90":
            self.current_image_pil = self.current_image_pil.rotate(-90, expand=True)
        elif mode == "flip_h":
            self.current_image_pil = self.current_image_pil.transpose(Image.FLIP_LEFT_RIGHT)
        
        self.update_canvas_image()

    def on_grid_moved_by_mouse(self, x, y):
        self.spin_x.blockSignals(True)
        self.spin_y.blockSignals(True)
        self.spin_x.setValue(x)
        self.spin_y.setValue(y)
        self.spin_x.blockSignals(False)
        self.spin_y.blockSignals(False)

    def on_spinbox_change(self):
        x = self.spin_x.value()
        y = self.spin_y.value()
        self.grid_item.setPos(x, y)

    def on_zoom_change(self, value):
        scale = value / 100.0
        self.lbl_zoom_val.setText(f"{value}% (Ctrl+Scroll)")
        self.view.resetTransform()
        self.view.scale(scale, scale)
        
        self.view.zoom_factor = scale

    def cut_image(self):
        if not self.current_image_pil:
            return

        start_x = self.spin_x.value()
        start_y = self.spin_y.value()
        cols = self.spin_cols.value()
        rows = self.spin_rows.value()
        size = self.cell_size

        for c in range(cols):
            for r in range(rows):
                x = start_x + (c * size)
                y = start_y + (r * size)
                
                if x + size > self.current_image_pil.width or y + size > self.current_image_pil.height:
                    continue

                box = (x, y, x + size, y + size)
                sprite = self.current_image_pil.crop(box)
                
                if not self.chk_empty.isChecked():
                    if not sprite.getbbox(): 
                         continue

                self.add_sprite_to_list(sprite)

        if self.list_widget.count() > 0:
            self.btn_export.setEnabled(True)

    def add_sprite_to_list(self, pil_image):
        self.sliced_images.append(pil_image)
        
        qim = self.pil_to_qimage(pil_image)
        pix = QPixmap.fromImage(qim)
        
        icon = QIcon(pix)
        item = QListWidgetItem(icon, "")
        item.setSizeHint(QSize(40, 40)) 
        self.list_widget.addItem(item)
        self.list_widget.scrollToBottom()

    def clear_list(self):
        self.sliced_images.clear()
        self.list_widget.clear()
        self.btn_export.setEnabled(False)  


    def export_sprites(self):
        if not self.sliced_images:
            return
        
        output_dir = QFileDialog.getExistingDirectory(
            self, 
            "Select Output Directory",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not output_dir:
            return
        
        from PyQt6.QtWidgets import QInputDialog
        prefix, ok = QInputDialog.getText(
            self,
            "Export Prefix",
            "Enter filename prefix:",
            text="sprite"
        )
        
        if not ok or not prefix:
            prefix = "sprite"
        
        try:
            for idx, sprite in enumerate(self.sliced_images):
                filename = f"{prefix}_{idx:04d}.png"
                filepath = f"{output_dir}/{filename}"
                sprite.save(filepath, "PNG")
            
            QMessageBox.information(
                self,
                "Export Complete",
                f"{len(self.sliced_images)} sprites exported successfully!"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{str(e)}")


    @staticmethod
    def pil_to_qimage(pil_image):
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        data = pil_image.tobytes("raw", "RGBA")
        qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
        return qimage

if __name__ == '__main__':
    import sys
    try:
        app = QApplication(sys.argv)
        window = SliceWindow()
        window.show()
        window.showMaximized()
        sys.exit(app.exec())
    except Exception as e:
        print(f"❌ ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()
        input("Pressione ENTER para fechar...")
