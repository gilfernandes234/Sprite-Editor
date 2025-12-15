import sys
import io
from PIL import Image, ImageDraw
import re
from copy import deepcopy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QCheckBox, QSlider, QFileDialog, QListWidget,
    QListWidgetItem, QFrame, QGridLayout, QMessageBox,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsObject,
    QGroupBox, QAbstractItemView, QApplication, QTabWidget, QComboBox, QLineEdit,
    QGraphicsRectItem
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QSize, QPoint, QPointF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QIcon, QBrush, QWheelEvent, QKeyEvent

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

# ============================================================================
# CLASSE PARA RETÂNGULO DE SELEÇÃO
# ============================================================================

class SelectionRectangle(QGraphicsRectItem):
    """Retângulo de seleção arrastável"""
    
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(15)  # Acima da grid
        
        # Estilo do retângulo
        pen = QPen(QColor(0, 150, 255), 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        
        # Preenchimento semi-transparente
        self.setBrush(QBrush(QColor(0, 150, 255, 30)))
        
    def set_rect(self, rect):
        """Define o retângulo de seleção"""
        self.setRect(rect)

# ============================================================================
# CUSTOM QGRAPHICSVIEW COM ZOOM POR CTRL+SCROLL
# ============================================================================

class ZoomableGraphicsView(QGraphicsView):
    """QGraphicsView com suporte a zoom via Ctrl+Scroll"""
    
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.zoom_factor = 1.0
        
    def wheelEvent(self, event: QWheelEvent):
        """Zoom com Ctrl+Scroll do mouse"""
        modifiers = QApplication.keyboardModifiers()
        
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # Zoom in/out
            zoom_in_factor = 1.15
            zoom_out_factor = 1 / zoom_in_factor
            
            # Salvar posição do mouse na cena antes do zoom
            old_pos = self.mapToScene(event.position().toPoint())
            
            # Aplicar zoom
            if event.angleDelta().y() > 0:
                factor = zoom_in_factor
                self.zoom_factor *= zoom_in_factor
            else:
                factor = zoom_out_factor
                self.zoom_factor *= zoom_out_factor
            
            # Limitar zoom (10% a 500%)
            if 0.1 <= self.zoom_factor <= 5.0:
                self.scale(factor, factor)
                
                # Ajustar viewport para manter mouse na mesma posição
                new_pos = self.mapToScene(event.position().toPoint())
                delta = new_pos - old_pos
                self.translate(delta.x(), delta.y())
                
                # Atualizar label de zoom no parent
                if hasattr(self.parent(), 'update_zoom_label'):
                    self.parent().update_zoom_label(int(self.zoom_factor * 100))
            else:
                # Reverter se ultrapassar limites
                self.zoom_factor /= factor
            
            event.accept()
        else:
            # Scroll normal
            super().wheelEvent(event)

# ============================================================================

class SliceWindow(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Slicer Obd")
        self.resize(900, 600)
        self.setStyleSheet("background-color: #494949; color: white;")
        self.original_image_pil = None       
        self.current_image_pil = None 
        self.sliced_images = []     
        self.cell_size = 32
        self.color_picker_mode = False
        
        # Variáveis para o eraser
        self.eraser_mode = False
        self.eraser_size = 10
        self.last_eraser_point = None
        
        # Variáveis para seleção
        self.selection_mode = False
        self.selection_start = None
        self.selection_rect_item = None
        self.is_drawing_selection = False
        self.selected_image_data = None
        
        # Sistema de Undo/Redo
        self.undo_stack = []  # Pilha de estados anteriores
        self.redo_stack = []  # Pilha de estados desfeitos
        self.max_undo_steps = 20  # Limitar memória

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Toolbar ---
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

        # Criar TabWidget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #222; background: #444; }
            QTabBar::tab { background: #333; color: #ddd; padding: 4px; min-width: 80px; }
            QTabBar::tab:selected { background: #555; color: white; }
        """)

        # Aba 1: Resize
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

        grp_resize.setLayout(resize_layout)
        tab_resize_layout.addWidget(grp_resize)
        tab_resize_layout.addStretch()
        
        
        # Aba 2: Transparency
        tab_transparency = QWidget()
        tab_transparency_layout = QVBoxLayout(tab_transparency)

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
        tab_transparency_layout.addStretch()


        
     
        # Aba 3: Slice/Cut
        tab_slice = QWidget()
        tab_slice_layout = QVBoxLayout(tab_slice)

        grp_cells = QGroupBox("Cells")
        grp_cells_layout = QGridLayout()

        self.chk_subdivisions = QCheckBox("Subdivisions")
        self.chk_subdivisions.toggled.connect(self.update_grid_visuals)
        grp_cells_layout.addWidget(self.chk_subdivisions, 0, 0, 1, 2)

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
        
        # ===== ERASER SECTION =====
        grp_eraser = QGroupBox("Eraser Tool")
        eraser_layout = QGridLayout()
        
        eraser_layout.addWidget(QLabel("Brush Size:"), 0, 0)
        self.spin_eraser_size = QSpinBox()
        self.spin_eraser_size.setRange(1, 100)
        self.spin_eraser_size.setValue(10)
        self.spin_eraser_size.valueChanged.connect(self.on_eraser_size_change)
        eraser_layout.addWidget(self.spin_eraser_size, 0, 1)
        
        self.btn_toggle_eraser = QPushButton("Enable Eraser")
        self.btn_toggle_eraser.setCheckable(True)
        self.btn_toggle_eraser.setStyleSheet("background-color: #ff6b6b; font-weight: bold;")
        self.btn_toggle_eraser.clicked.connect(self.toggle_eraser_mode)
        self.btn_toggle_eraser.setEnabled(False)
        eraser_layout.addWidget(self.btn_toggle_eraser, 1, 0, 1, 2)
        
        grp_eraser.setLayout(eraser_layout)
        tab_slice_layout.addWidget(grp_eraser)
        
        # ===== SELECTION SECTION =====
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
        selection_layout.addWidget(self.btn_copy_selection, 2, 0, 1, 2)
        
        self.btn_paste_selection = QPushButton("Paste")
        self.btn_paste_selection.setStyleSheet("background-color: #2ecc71; font-weight: bold;")
        self.btn_paste_selection.clicked.connect(self.paste_selection)
        self.btn_paste_selection.setEnabled(False)
        selection_layout.addWidget(self.btn_paste_selection, 3, 0, 1, 2)
        
        self.btn_clear_selection = QPushButton("Clear Selection")
        self.btn_clear_selection.clicked.connect(self.clear_selection)
        self.btn_clear_selection.setEnabled(False)
        selection_layout.addWidget(self.btn_clear_selection, 4, 0, 1, 2)
        
        grp_selection.setLayout(selection_layout)
        tab_slice_layout.addWidget(grp_selection)

        tab_slice_layout.addStretch()

        # Adicionar abas ao TabWidget
        self.tab_widget.addTab(tab_resize, "Resize")
        self.tab_widget.addTab(tab_transparency, "Transparency")
        self.tab_widget.addTab(tab_slice, "Slice")

        lp_layout.addWidget(self.tab_widget)

        # Zoom (fora das abas, sempre visível)
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
        
        # Usar o ZoomableGraphicsView customizado
        self.view = ZoomableGraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setStyleSheet("border: none;")
        
        # Sobrescrever eventos de mouse
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

    # ===== UNDO/REDO SYSTEM =====
    def save_state(self):
        """Salva o estado atual da imagem para undo"""
        if self.current_image_pil:
            # Copiar imagem atual
            state = self.current_image_pil.copy()
            self.undo_stack.append(state)
            
            # Limitar tamanho do stack
            if len(self.undo_stack) > self.max_undo_steps:
                self.undo_stack.pop(0)
            
            # Limpar redo stack quando nova ação é feita
            self.redo_stack.clear()
    
    def undo(self):
        """Desfaz a última ação (Ctrl+Z)"""
        if not self.undo_stack:
            QMessageBox.information(self, "Undo", "Nada para desfazer!")
            return
        
        # Salvar estado atual no redo stack
        if self.current_image_pil:
            self.redo_stack.append(self.current_image_pil.copy())
        
        # Restaurar último estado
        self.current_image_pil = self.undo_stack.pop()
        self.update_canvas_image()
    
    def redo(self):
        """Refaz a última ação desfeita (Ctrl+Y)"""
        if not self.redo_stack:
            QMessageBox.information(self, "Redo", "Nada para refazer!")
            return
        
        # Salvar estado atual no undo stack
        if self.current_image_pil:
            self.undo_stack.append(self.current_image_pil.copy())
        
        # Restaurar estado do redo
        self.current_image_pil = self.redo_stack.pop()
        self.update_canvas_image()
    
    def keyPressEvent(self, event: QKeyEvent):
        """Captura Ctrl+Z e Ctrl+Y"""
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
        """Atualiza label de zoom quando usa Ctrl+Scroll"""
        self.lbl_zoom_val.setText(f"{zoom_percentage}% (Ctrl+Scroll)")
        
        # Sincronizar slider (sem disparar evento)
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(zoom_percentage)
        self.slider_zoom.blockSignals(False)
    
    # ===== FIM UNDO/REDO =====

    # ===== FUNÇÕES DE SELEÇÃO =====
    def toggle_selection_mode(self, checked):
        """Ativa/desativa modo de seleção"""
        self.selection_mode = checked
        
        if checked:
            if self.eraser_mode:
                self.btn_toggle_eraser.setChecked(False)
                self.toggle_eraser_mode(False)
            
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
        """Remove o retângulo de seleção"""
        if self.selection_rect_item:
            self.scene.removeItem(self.selection_rect_item)
            self.selection_rect_item = None
        
        self.btn_cut_selection.setEnabled(False)
        self.btn_copy_selection.setEnabled(False)
        self.btn_clear_selection.setEnabled(False)
    
    def cut_selection(self):
        """Recorta a área selecionada (copia e apaga)"""
        if not self.selection_rect_item or not self.current_image_pil:
            return
        
        # Salvar estado antes de modificar
        self.save_state()
        
        self.copy_selection()
        
        rect = self.selection_rect_item.rect()
        x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        
        transparent_box = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        self.current_image_pil.paste(transparent_box, (x, y))
        
        self.update_canvas_image()
        self.clear_selection()
        
        QMessageBox.information(self, "Cut", "Seleção recortada! Use 'Paste' para colar.")
    
    def copy_selection(self):
        """Copia a área selecionada"""
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
        QMessageBox.information(self, "Copy", f"Área de {w}x{h}px copiada!")
    
    def paste_selection(self):
        """Cola a área copiada no centro"""
        if not self.selected_image_data or not self.current_image_pil:
            return
        
        # Salvar estado antes de modificar
        self.save_state()
        
        img_w, img_h = self.current_image_pil.size
        sel_w, sel_h = self.selected_image_data.size
        
        x = (img_w - sel_w) // 2
        y = (img_h - sel_h) // 2
        
        self.current_image_pil.paste(self.selected_image_data, (x, y))
        self.update_canvas_image()
        
        QMessageBox.information(self, "Paste", f"Colado em ({x}, {y})")
    
    # ===== FIM FUNÇÕES DE SELEÇÃO =====

    # ===== FUNÇÕES DO ERASER =====
    def toggle_eraser_mode(self, checked):
        """Ativa/desativa o modo borracha"""
        self.eraser_mode = checked
        
        if checked:
            if self.selection_mode:
                self.btn_toggle_selection.setChecked(False)
                self.toggle_selection_mode(False)
            
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
        """Atualiza o tamanho da borracha"""
        self.eraser_size = value
    
    def view_mouse_press(self, event):
        """Evento de mouse press"""
        if self.eraser_mode and event.button() == Qt.MouseButton.LeftButton:
            # Salvar estado antes de começar a apagar
            self.save_state()
            
            scene_pos = self.view.mapToScene(event.pos())
            self.last_eraser_point = QPoint(int(scene_pos.x()), int(scene_pos.y()))
            self.erase_at_point(self.last_eraser_point)
        elif self.selection_mode and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(event.pos())
            self.selection_start = scene_pos
            self.is_drawing_selection = True
            
            if self.selection_rect_item:
                self.scene.removeItem(self.selection_rect_item)
            
            self.selection_rect_item = SelectionRectangle()
            self.scene.addItem(self.selection_rect_item)
        else:
            QGraphicsView.mousePressEvent(self.view, event)
    
    def view_mouse_move(self, event):
        """Evento de mouse move"""
        if self.eraser_mode and event.buttons() & Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(event.pos())
            current_point = QPoint(int(scene_pos.x()), int(scene_pos.y()))
            
            if self.last_eraser_point:
                self.erase_line(self.last_eraser_point, current_point)
            
            self.last_eraser_point = current_point
        elif self.selection_mode and self.is_drawing_selection:
            scene_pos = self.view.mapToScene(event.pos())
            rect = QRectF(self.selection_start, scene_pos).normalized()
            self.selection_rect_item.set_rect(rect)
        else:
            QGraphicsView.mouseMoveEvent(self.view, event)
    
    def view_mouse_release(self, event):
        """Evento de mouse release"""
        if self.eraser_mode:
            self.last_eraser_point = None
        elif self.selection_mode and self.is_drawing_selection:
            self.is_drawing_selection = False
            
            if self.selection_rect_item and not self.selection_rect_item.rect().isEmpty():
                self.btn_cut_selection.setEnabled(True)
                self.btn_copy_selection.setEnabled(True)
                self.btn_clear_selection.setEnabled(True)
        else:
            QGraphicsView.mouseReleaseEvent(self.view, event)
    
    def erase_at_point(self, point):
        """Apaga pixels em um ponto específico"""
        if not self.current_image_pil:
            return
        
        x, y = point.x(), point.y()
        w, h = self.current_image_pil.size
        
        if x < 0 or y < 0 or x >= w or y >= h:
            return
        
        draw = ImageDraw.Draw(self.current_image_pil, 'RGBA')
        radius = self.eraser_size // 2
        
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
        
        self.update_canvas_image()
    
    def erase_line(self, start, end):
        """Apaga pixels ao longo de uma linha"""
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
    # ===== FIM FUNÇÕES DO ERASER =====

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
                
                # Limpar stacks ao abrir nova imagem
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
                self.btn_toggle_selection.setEnabled(True)
                
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
                
                
    def update_color_preview(self, text):
        """Atualiza o preview da cor conforme o usuário digita"""
        if self.hex_to_rgb(text):
            self.lbl_preview_color.setStyleSheet(f"background-color: {text}; border: 1px solid #222;")
        else:
            self.lbl_preview_color.setStyleSheet("background-color: #333; border: 1px solid #222;")
                
                
    def hex_to_rgb(self, hex_color):
        """Converte cor hex (#dcff73) para RGB (220, 255, 115)"""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return None
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except ValueError:
            return None

    def remove_color_to_transparent(self):
        """Remove uma cor específica e a torna transparente"""
        if not self.current_image_pil:
            return
        
        # Salvar estado antes de modificar
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

    def enable_color_picker(self):
        """Ativa o modo de seleção de cor diretamente da imagem"""
        self.color_picker_mode = True
        self.view.viewport().setCursor(Qt.CursorShape.CrossCursor)
        
        self.original_mouse_press = self.view.mousePressEvent
        self.view.mousePressEvent = self.pick_color_from_image
        
        QMessageBox.information(
            self,
            "Color Picker",
            "Clique na imagem para selecionar uma cor"
        )

    def pick_color_from_image(self, event):
        """Pega a cor do pixel clicado"""
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
        """Atualiza altura proporcionalmente se Keep Aspect Ratio está marcado"""
        if self.chk_keep_aspect.isChecked() and self.original_image_pil:
            w, h = self.original_image_pil.size
            aspect_ratio = h / w
            new_height = int(value * aspect_ratio)
            self.spin_resize_height.blockSignals(True)
            self.spin_resize_height.setValue(new_height)
            self.spin_resize_height.blockSignals(False)

    def on_resize_height_change(self, value):
        """Atualiza largura proporcionalmente se Keep Aspect Ratio está marcado"""
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
        
        # Salvar estado antes de modificar
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
        """Restaura a imagem original sem resize"""
        if not self.original_image_pil:
            return
        
        # Salvar estado antes de modificar
        self.save_state()
        
        self.current_image_pil = self.original_image_pil.copy()
        
        w, h = self.current_image_pil.size
        self.spin_resize_width.blockSignals(True)
        self.spin_resize_height.blockSignals(True)
        self.spin_resize_width.setValue(w)
        self.spin_resize_height.setValue(h)
        self.spin_resize_width.blockSignals(False)
        self.spin_resize_height.blockSignals(False)
        
        self.update_canvas_image()
                    


    def update_canvas_image(self):
        if self.current_image_pil:
            qim = self.pil_to_qimage(self.current_image_pil)
            pix = QPixmap.fromImage(qim)
            self.pixmap_item.setPixmap(pix)
            self.scene.setSceneRect(QRectF(pix.rect()))
            
            w, h = self.current_image_pil.size
            self.spin_x.setRange(0, w)
            self.spin_y.setRange(0, h)

    def transform_image(self, mode):
        if not self.current_image_pil: return
        
        # Salvar estado antes de transformar
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
        
        # Atualizar zoom_factor do view
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SliceWindow()
    window.show()
    sys.exit(app.exec())
