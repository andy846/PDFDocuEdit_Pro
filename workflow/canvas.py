"""Native Qt node canvas with typed ports, drag/drop, pan and zoom."""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QMimeData, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDrag, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QListWidget,
    QListWidgetItem,
)

from .model import KINDS, LABELS

SYMBOLS={"input":"folder-open","merge":"layers","extract":"scan","group":"table","review":"search",
         "overlay":"file-text","output":"printer","data":"table","mapping":"settings","template":"file-text",
         "sequences":"table","mail_review":"search","compose":"printer","reports":"file-text"}


class NodeToolbox(QListWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.configure(KINDS)
        self.setDragEnabled(True)
        self.setToolTip("Drag a step to the canvas. Each tool can appear once in a linear workflow.")

    def configure(self,kinds):
        self.clear()
        for kind in kinds:
            item=QListWidgetItem(LABELS[kind])
            from ui.icons import icon
            item.setIcon(icon(SYMBOLS[kind]))
            item.setSizeHint(QSize(150,32))
            item.setData(Qt.ItemDataRole.UserRole,kind)
            item.setToolTip("Add "+LABELS[kind]+". Each step appears once in this workflow.")
            self.addItem(item)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange,QEvent.Type.StyleChange):
            from ui.icons import icon
            for i in range(self.count()):
                item=self.item(i)
                item.setIcon(icon(SYMBOLS[item.data(Qt.ItemDataRole.UserRole)]))

    def filter(self,text):
        for index in range(self.count()):
            item=self.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def startDrag(self, supported):
        if not self.currentItem():
            return
        mime=QMimeData()
        mime.setData("application/x-pdflow-node",self.currentItem().data(Qt.ItemDataRole.UserRole).encode())
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
        border=palette.highlight().color() if self.isSelected() else palette.text().color()
        if not self.isSelected():
            border.setAlpha(100)
        painter.setPen(QPen(border,2 if self.isSelected() else 1))
        painter.setBrush(palette.base())
        painter.drawRoundedRect(QRectF(0,0,174,76),8,8)
        painter.setPen(palette.text().color())
        font=painter.font()
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        from ui.icons import icon
        icon(SYMBOLS[self.node.kind],color=palette.text().color().name()).paint(painter,QRect(10,11,16,16))
        painter.drawText(QRectF(32,7,132,24),Qt.AlignmentFlag.AlignLeft,LABELS[self.node.kind])
        color=palette.highlight().color() if self.status else palette.mid().color()
        if not self.status:
            color.setAlpha(75)
        painter.setPen(QPen(color,3))
        painter.drawLine(QPointF(10,33),QPointF(164,33))
        painter.setPen(palette.text().color())
        font.setPointSizeF(8)
        font.setBold(False)
        painter.setFont(font)
        if self.node.kind=="input":
            detail=f"{len(self.node.params.get('paths',[]))} PDF(s)"
        elif self.node.kind=="extract":
            detail=f"{len(self.node.params.get('regions',[]))} named region(s)"
        elif self.node.kind=="group":
            detail={"fixed":f"{self.node.params.get('pages',1)} page(s) / envelope","field":"Field changes","pattern":"Page-number pattern"}.get(self.node.params.get("method"),"Configure grouping")
        else:
            detail=self.view.summaries.get(self.node.kind,"Configure step")
        marker={"Completed":"✓ ","Failed":"! ","Blocked":"! ","Needs review":"? ","Running":"▶ ","Ready":"✓ "}.get(self.status,"")
        if self.status:
            painter.drawText(QRectF(12,37,152,16),Qt.AlignmentFlag.AlignLeft,marker+self.status)
            painter.drawText(QRectF(12,53,152,19),Qt.AlignmentFlag.AlignLeft,detail)
        else:
            painter.drawText(QRectF(12,39,152,29),Qt.AlignmentFlag.AlignLeft|Qt.TextFlag.TextWordWrap,detail)
        for x in (0,174):
            if (x==0 and self.node.kind in ("input","data")) or (x==174 and self.node.kind in ("output","reports")):
                continue
            color=palette.highlight().color()
            if x==0 and self.view.pending and self.view.spec:
                source=self.view.nodes[self.view.pending].node.kind
                if self.node.kind not in self.view.spec.allowed_next(source):
                    color=palette.mid().color()
            painter.setBrush(color)
            painter.setPen(QPen(color,1))
            painter.drawEllipse(QPointF(x,38),5,5)

    def mousePressEvent(self,event):
        self.before=QPointF(self.pos())
        if abs(event.pos().x()-174)<10 and abs(event.pos().y()-38)<12:
            self.view.pending=self.node.id
            self.view.viewport().update()
            self.view.message.emit("Choose the next step's input port")
            event.accept()
            return
        if abs(event.pos().x())<10 and abs(event.pos().y()-38)<12 and self.view.pending:
            pending=self.view.pending
            self.view.pending=None
            self.view.viewport().update()
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
            self.setPos(round(self.pos().x()/10)*10,round(self.pos().y()/10)*10)
            self.view.positionChanged.emit(self.node.id,self.pos().x(),self.pos().y())


class EdgeItem(QGraphicsPathItem):
    def __init__(self,a,b,view):
        super().__init__()
        self.a,self.b,self.view=a,b,view
        self.setZValue(0)
        self.setToolTip("Double-click to remove this connection")

    def mouseDoubleClickEvent(self,event):
        event.accept()
        self.view.disconnectRequested.emit(self.a,self.b)


class WorkflowCanvas(QGraphicsView):
    nodeSelected=pyqtSignal(str)
    nodeDropped=pyqtSignal(str,float,float)
    positionChanged=pyqtSignal(str,float,float)
    connectionRequested=pyqtSignal(str,str)
    disconnectRequested=pyqtSignal(str,str)
    message=pyqtSignal(str)
    zoomChanged=pyqtSignal(float)

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
        self.spec=None
        self.summaries={}
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
                if item.node.kind not in ("output","reports"):
                    position=self.mapFromScene(item.pos()+QPointF(174,38))
                    candidates.append(((position-point).manhattanLength(),"output",item.node.id))
                if self.pending and item.node.kind not in ("input","data"):
                    position=self.mapFromScene(item.pos()+QPointF(0,38))
                    candidates.append(((position-point).manhattanLength(),"input",item.node.id))
            if candidates:
                distance,kind,identity=min(candidates)
                if distance<=10:
                    if kind=="output":
                        self.pending=identity
                        self.viewport().update()
                        self.message.emit("Choose the next step's input port")
                    else:
                        previous=self.pending
                        source=self.nodes[previous].node.kind
                        if self.spec and item_kind(self,identity) not in self.spec.allowed_next(source):
                            self.message.emit(f"{LABELS[source]} cannot connect to {LABELS[item_kind(self,identity)]}.")
                            event.accept()
                            return
                        self.pending=None
                        self.viewport().update()
                        self.connectionRequested.emit(previous,identity)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape and self.pending:
            self.pending=None
            self.viewport().update()
            self.message.emit("Connection cancelled")
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down):
            nodes=list(self.nodes.values())
            current=next((i for i,item in enumerate(nodes) if item.isSelected()),-1)
            delta=-1 if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Up) else 1
            if nodes:
                self.scene().clearSelection()
                nodes[(current+delta)%len(nodes)].setSelected(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def display(self,spec,statuses,selected=None):
        self.spec=spec
        center=self.mapToScene(self.viewport().rect().center())
        if self.pending and not any(n.id==self.pending for n in spec.nodes):
            self.pending=None
        scene=self.scene()
        blocked=scene.blockSignals(True)
        try:
            # Model commits can run inside selectionChanged/mouseReleaseEvent.
            # Keep the live Qt items: clearing the scene here deletes the mouse
            # grabber while QGraphicsScene is still dispatching its event.
            identities={n.id for n in spec.nodes}
            for identity in list(self.nodes):
                if identity not in identities:
                    self.retire_item(self.nodes.pop(identity))
            for node in spec.nodes:
                item=self.nodes.get(node.id)
                if item is None:
                    item=NodeItem(node,self,statuses.get(node.id,""))
                    self.nodes[node.id]=item
                    scene.addItem(item)
                else:
                    item.node=node
                    item.status=statuses.get(node.id,"")
                    item.setPos(node.x,node.y)
                    item.update()
                item.setSelected(node.id==selected)
            existing={(edge.a,edge.b):edge for edge in self.edges}
            connections={tuple(pair) for pair in spec.edges}
            for pair,edge in existing.items():
                if pair not in connections:
                    self.retire_item(edge)
            self.edges=[]
            for a,b in spec.edges:
                edge=existing.get((a,b))
                if edge is None:
                    edge=EdgeItem(a,b,self)
                    scene.addItem(edge)
                self.edges.append(edge)
            self.redraw_edges()
            scene.setSceneRect(scene.itemsBoundingRect().adjusted(-150,-150,150,150))
        finally:
            scene.blockSignals(blocked)
        self.centerOn(center)

    def retire_item(self,item):
        self.scene().removeItem(item)
        # Removed edges may still be inside mouseDoubleClickEvent. Keep them
        # alive until dispatch has returned, including when closing the view.
        def dispose():
            if not sip.isdeleted(item):
                sip.delete(item)
        QTimer.singleShot(0,dispose)

    def redraw_edges(self):
        for edge in self.edges:
            a=self.nodes[edge.a].pos()+QPointF(174,38)
            b=self.nodes[edge.b].pos()+QPointF(0,38)
            path=QPainterPath(a)
            if b.x()<a.x() and b.y()>a.y()+60:
                # Route wrapped rows through the gap, rather than across node cards.
                middle=(a.y()+b.y())/2
                right=a.x()+30
                left=b.x()-30
                path.cubicTo(a+QPointF(30,0),QPointF(right,a.y()),QPointF(right,middle))
                path.lineTo(QPointF(left,middle))
                path.cubicTo(QPointF(left,b.y()),b-QPointF(30,0),b)
            else:
                path.cubicTo(a+QPointF(65,0),b-QPointF(65,0),b)
            path.moveTo(b-QPointF(9,5))
            path.lineTo(b)
            path.lineTo(b-QPointF(9,-5))
            edge.setPath(path)
            edge.setPen(QPen(self.palette().highlight().color(),2))
        self.viewport().update()

    def drawBackground(self,painter,rect):
        painter.fillRect(rect,self.palette().alternateBase())
        if self.transform().m11()<.35:
            return
        color=self.palette().text().color()
        color.setAlpha(40)
        painter.setPen(QPen(color,1))
        left=int(rect.left()/20)*20
        top=int(rect.top()/20)*20
        for x in range(left,int(rect.right())+20,20):
            for y in range(top,int(rect.bottom())+20,20):
                painter.drawPoint(QPointF(x,y))

    def zoom(self,factor):
        if .15<=self.transform().m11()*factor<=3:
            self.scale(factor,factor)
            self.zoomChanged.emit(self.transform().m11())

    def reset_view(self):
        self.resetTransform()
        self.centerOn(self.scene().itemsBoundingRect().center())
        self.zoomChanged.emit(1)

    def fit(self):
        self.fitInView(self.scene().itemsBoundingRect().adjusted(-20,-20,20,20),Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit(self.transform().m11())

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
                self.zoom(factor)
            event.accept()
        else:
            super().wheelEvent(event)


def item_kind(view,identity):
    return view.nodes[identity].node.kind
