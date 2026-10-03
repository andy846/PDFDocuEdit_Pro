"""Native Qt node canvas with typed ports, drag/drop, pan and zoom."""
from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QListWidget,
)

from .model import KINDS, LABELS


class NodeToolbox(QListWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.addItems([LABELS[k] for k in KINDS])
        self.setDragEnabled(True)
        self.setToolTip("Drag a step to the canvas. Each tool can appear once in a linear workflow.")

    def startDrag(self, supported):
        if not self.currentItem():
            return
        mime=QMimeData()
        mime.setData("application/x-pdflow-node",KINDS[self.currentRow()].encode())
        drag=QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class NodeItem(QGraphicsObject):
    def __init__(self,node,view,status):
        super().__init__()
        self.node,self.view,self.status=node,view,status
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable|QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPos(node.x,node.y)
        self.setToolTip("Click to configure. Drag to move. Click output port, then another input port to connect.")
        self.setZValue(2)

    def boundingRect(self):
        return QRectF(-8,-2,190,82)

    def paint(self,painter,option,widget=None):
        palette=self.view.palette()
        border=palette.highlight().color() if self.isSelected() else palette.mid().color()
        painter.setPen(QPen(border,2 if self.isSelected() else 1))
        painter.setBrush(palette.base())
        painter.drawRoundedRect(QRectF(0,0,174,76),8,8)
        painter.setPen(palette.text().color())
        painter.drawText(QRectF(12,9,152,22),Qt.AlignmentFlag.AlignLeft,LABELS[self.node.kind])
        painter.setPen(QColor("#c5572d") if self.status in ("Failed","Needs review") else palette.text().color())
        detail=self.status
        if not detail:
            if self.node.kind=="input":
                detail=f"{len(self.node.params.get('paths',[]))} PDF(s)"
            elif self.node.kind=="extract":
                detail=f"{len(self.node.params.get('regions',[]))} named region(s)"
            elif self.node.kind=="group":
                detail={"fixed":f"{self.node.params.get('pages',1)} page(s) / envelope","field":"Field changes","pattern":"Page-number pattern"}.get(self.node.params.get("method"),"Configure grouping")
            else:
                detail="Configure"
        painter.drawText(QRectF(12,37,152,26),Qt.AlignmentFlag.AlignLeft,detail)
        painter.setBrush(palette.highlight())
        for x in (0,174):
            painter.drawEllipse(QPointF(x,38),5,5)

    def mousePressEvent(self,event):
        self.before=QPointF(self.pos())
        if abs(event.pos().x()-174)<10 and abs(event.pos().y()-38)<12:
            self.view.pending=self.node.id
            self.view.message.emit("Choose the next step's input port")
            event.accept()
            return
        if abs(event.pos().x())<10 and abs(event.pos().y()-38)<12 and self.view.pending:
            pending=self.view.pending
            self.view.pending=None
            self.view.connectionRequested.emit(pending,self.node.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        super().mouseMoveEvent(event)
        self.view.redraw_edges()

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        if hasattr(self,"before") and self.before!=self.pos():
            self.view.positionChanged.emit(self.node.id,self.pos().x(),self.pos().y())


class EdgeItem(QGraphicsPathItem):
    def __init__(self,a,b,view):
        super().__init__()
        self.a,self.b,self.view=a,b,view
        self.setZValue(0)
        self.setToolTip("Double-click to remove this connection")

    def mouseDoubleClickEvent(self,event):
        self.view.disconnectRequested.emit(self.a,self.b)
        event.accept()


class WorkflowCanvas(QGraphicsView):
    nodeSelected=pyqtSignal(str)
    nodeDropped=pyqtSignal(str,float,float)
    positionChanged=pyqtSignal(str,float,float)
    connectionRequested=pyqtSignal(str,str)
    disconnectRequested=pyqtSignal(str,str)
    message=pyqtSignal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(200,180)
        self.nodes={}
        self.edges=[]
        self.pending=None
        self.scene().selectionChanged.connect(self.selection_changed)

    def selection_changed(self):
        selected=self.scene().selectedItems()
        if selected and isinstance(selected[0],NodeItem):
            self.nodeSelected.emit(selected[0].node.id)

    def mousePressEvent(self,event):
        # Hit-test ports in view space: small circles must remain usable at Fit
        # zoom and when a neighbouring node partially overlaps the port.
        if event.button()==Qt.MouseButton.LeftButton:
            point=event.position().toPoint()
            candidates=[]
            for item in self.nodes.values():
                if item.node.kind!="output":
                    position=self.mapFromScene(item.pos()+QPointF(174,38))
                    candidates.append(((position-point).manhattanLength(),"output",item.node.id))
                if self.pending and item.node.kind!="input":
                    position=self.mapFromScene(item.pos()+QPointF(0,38))
                    candidates.append(((position-point).manhattanLength(),"input",item.node.id))
            if candidates:
                distance,kind,identity=min(candidates)
                if distance<=10:
                    if kind=="output":
                        self.pending=identity
                        self.message.emit("Choose the next step's input port")
                    else:
                        previous=self.pending
                        self.pending=None
                        self.connectionRequested.emit(previous,identity)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape and self.pending:
            self.pending=None
            self.message.emit("Connection cancelled")
            event.accept()
            return
        super().keyPressEvent(event)

    def display(self,spec,statuses,selected=None):
        center=self.mapToScene(self.viewport().rect().center())
        if self.pending and not any(n.id==self.pending for n in spec.nodes):
            self.pending=None
        self.scene().blockSignals(True)
        self.scene().clear()
        self.nodes={n.id:NodeItem(n,self,statuses.get(n.id,"")) for n in spec.nodes}
        for item in self.nodes.values():
            self.scene().addItem(item)
            item.setSelected(item.node.id==selected)
        self.edges=[EdgeItem(a,b,self) for a,b in spec.edges]
        for edge in self.edges:
            self.scene().addItem(edge)
        self.redraw_edges()
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-150,-150,150,150))
        self.scene().blockSignals(False)
        self.centerOn(center)

    def redraw_edges(self):
        for edge in self.edges:
            a=self.nodes[edge.a].pos()+QPointF(174,38)
            b=self.nodes[edge.b].pos()+QPointF(0,38)
            path=QPainterPath(a)
            path.cubicTo(a+QPointF(65,0),b-QPointF(65,0),b)
            path.moveTo(b-QPointF(9,5))
            path.lineTo(b)
            path.lineTo(b-QPointF(9,-5))
            edge.setPath(path)
            edge.setPen(QPen(self.palette().highlight().color(),2))

    def fit(self):
        self.fitInView(self.scene().itemsBoundingRect().adjusted(-20,-20,20,20),Qt.AspectRatioMode.KeepAspectRatio)

    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat("application/x-pdflow-node"):
            event.acceptProposedAction()

    def dragMoveEvent(self,event):
        event.acceptProposedAction()

    def dropEvent(self,event):
        if event.mimeData().hasFormat("application/x-pdflow-node"):
            pos=self.mapToScene(event.position().toPoint())
            self.nodeDropped.emit(bytes(event.mimeData().data("application/x-pdflow-node")).decode(),pos.x(),pos.y())
            event.acceptProposedAction()

    def wheelEvent(self,event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor=1.15 if event.angleDelta().y()>0 else 1/1.15
            if .15<=self.transform().m11()*factor<=3:
                self.scale(factor,factor)
            event.accept()
        else:
            super().wheelEvent(event)
