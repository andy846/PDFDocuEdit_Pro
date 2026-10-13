"""Named routing ports on the existing incremental, safely retired Qt scene."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsObject, QGraphicsView

from .canvas import NodeItem, WorkflowCanvas


class BranchItem(NodeItem):
    def ports(self):
        if self.node.kind=="route":
            routes=self.node.params.get("routes",[])
            return [(r["id"],r["name"]+(" · fallback" if r.get("fallback") else ""),108+24*i)
                    for i,r in enumerate(routes)]+[("exceptions","Exceptions",108+24*len(routes))]
        return [] if self.node.kind=="collect" else [("out","",38)]

    def boundingRect(self):
        height=122+24*len(self.node.params.get("routes",[])) if self.node.kind=="route" else 102
        return QRectF(-8,-2,190,height)

    def paint(self,painter,option,widget=None):
        super().paint(painter,option,widget)
        if self.node.kind=="route":
            palette=self.view.palette()
            painter.setPen(QPen(palette.highlight().color() if self.isSelected() else palette.mid().color(),1))
            painter.setBrush(palette.base())
            painter.drawRoundedRect(QRectF(0,97,174,self.boundingRect().height()-99),5,5)
            painter.setPen(palette.text().color())
            for _,name,y in self.ports():
                painter.drawText(QRectF(10,y-10,154,22),Qt.AlignmentFlag.AlignLeft,
                                 painter.fontMetrics().elidedText(name,Qt.TextElideMode.ElideRight,154))
            # Routing has distinct named outputs rather than the linear 'out' port.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.alternateBase())
            painter.drawEllipse(QPointF(174,38),6,6)
            painter.setBrush(palette.highlight())
            for _,_,y in self.ports():
                painter.drawEllipse(QPointF(174,y),5,5)

    def mousePressEvent(self,event):
        self.before=QPointF(self.pos())
        QGraphicsObject.mousePressEvent(self,event)


class BranchCanvas(WorkflowCanvas):
    def node_item_class(self,node):
        return BranchItem

    def mousePressEvent(self,event):
        if self.editable and event.button()==Qt.MouseButton.LeftButton:
            point=event.position().toPoint()
            for item in self.nodes.values():
                for _port,name,y in item.ports():
                    if (self.mapFromScene(item.pos()+QPointF(174,y))-point).manhattanLength()<=10:
                        item.setSelected(True)
                        self.message.emit((name or "Next step")+": use Settings to configure this path.")
                        event.accept()
                        return
        # Connections are made by Add route / Add step, with compatible paths.
        QGraphicsView.mousePressEvent(self,event)

    def redraw_edges(self):
        if not self.spec:
            return
        for item in self.edges:
            source=self.nodes[item.a]
            connection=next((e for e in self.spec.edges if e["source"]==item.a and e["target"]==item.b),None)
            y=next((y for port,_,y in source.ports() if connection and port==connection["port"]),38)
            a=source.pos()+QPointF(174,y)
            b=self.nodes[item.b].pos()+QPointF(0,38)
            path=QPainterPath(a)
            path.cubicTo(a+QPointF(65,0),b-QPointF(65,0),b)
            path.moveTo(b-QPointF(9,5))
            path.lineTo(b)
            path.lineTo(b-QPointF(9,-5))
            item.setPath(path)
            item.setPen(QPen(self.palette().highlight().color(),2))
            item.setToolTip((next((name for port,name,_ in source.ports() if connection and port==connection["port"]),"Next step"))+
                            " · configured path")
        self.viewport().update()

    def contextMenuEvent(self,event):
        item=self.itemAt(event.pos())
        if isinstance(item,NodeItem):
            self.scene().clearSelection()
            item.setSelected(True)
            self.message.emit("Configure the selected step in Settings. Use Add step or Add route to change the graph.")
        else:
            QGraphicsView.contextMenuEvent(self,event)
