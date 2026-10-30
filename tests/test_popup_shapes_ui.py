"""Actual popup shapes, interaction and reuse under the product stylesheet."""
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt6.QtGui import QRegion
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QMenu, QToolTip, QWidget

from styles.components import global_style
from styles.theme import apply_theme


@pytest.fixture(autouse=True)
def theme(qt_application):
    original = qt_application.styleSheet()
    apply_theme(qt_application, 'dark')
    qt_application.setStyleSheet(global_style())
    yield qt_application
    QToolTip.hideText()
    qt_application.setStyleSheet(original)


def assert_round(widget):
    assert widget.mask().isEmpty(), 'A binary mask clips the smooth fringe'
    assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    image = widget.grab().toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(image.width()//2, image.height()//2).alpha() == 255
    radius = round(14 * image.devicePixelRatio())
    assert any(0 < image.pixelColor(x, y).alpha() < 255
               for x in range(radius) for y in range(radius))


def test_popup_edge_has_per_pixel_alpha_instead_of_a_hard_clip(theme):
    menu = QMenu()
    menu.addAction('Smooth edge')
    try:
        menu.popup(QPoint(30, 30))
        theme.processEvents()
        assert menu.mask().isEmpty(), 'Binary regions cut off the antialiased fringe'
        assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        image = menu.grab().toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(image.width()//2, image.height()//2).alpha() == 255
        radius = round(14 * image.devicePixelRatio())
        assert any(0 < image.pixelColor(x, y).alpha() < 255
                   for x in range(radius) for y in range(radius))
    finally:
        menu.close()


def test_hidden_popups_are_not_mutated_during_stylesheet_polish(theme):
    menu = QMenu()
    menu.addAction('Hidden')
    flags = menu.windowFlags()
    theme.setStyleSheet(global_style())
    theme.processEvents()
    assert menu.mask().isEmpty()
    assert menu.windowFlags() == flags
    assert not menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    menu.close()


def test_menus_submenus_resize_and_keyboard_activation(theme):
    menu = QMenu()
    sub = menu.addMenu('Submenu')
    action = sub.addAction('Run')
    selected = []
    action.triggered.connect(lambda: selected.append(True))
    types = menu.windowType(), sub.windowType()
    try:
        menu.popup(QPoint(30, 30))
        theme.processEvents()
        assert_round(menu)
        sub.popup(QPoint(80, 50))
        theme.processEvents()
        assert_round(sub)
        flags = menu.windowFlags(), sub.windowFlags()
        sub.resize(320, 160)
        theme.processEvents()
        assert_round(sub)
        sub.setActiveAction(action)
        QTest.keyClick(sub, Qt.Key.Key_Return)
        assert selected == [True]
        assert flags == (menu.windowFlags(), sub.windowFlags())
        assert types == (menu.windowType(), sub.windowType())
    finally:
        sub.close()
        menu.close()


@pytest.mark.parametrize('editable', [False, True])
def test_combo_outer_frame_is_rounded_and_selection_works(theme, editable):
    combo = QComboBox()
    combo.setEditable(editable)
    combo.addItems([f'Item {i}' for i in range(100)])
    combo.show()
    try:
        combo.showPopup()
        theme.processEvents()
        popup = combo.view().window()
        # Windows may display a temporary roll-effect window first. Inspect
        # the actual dropdown only after its normal exposure completes.
        assert QTest.qWaitForWindowExposed(popup, 1000)
        assert_round(popup)
        assert popup.property('pdfdocueditPopupSurface') == 'combo'
        assert popup.grab().toImage().pixelColor(popup.width()//2, 0).name() == '#515157'
        for mode, border in (('light', '#c5c5ca'), ('dark', '#515157')):
            apply_theme(theme, mode)
            theme.setStyleSheet(global_style())
            theme.processEvents()
            assert popup.grab().toImage().pixelColor(popup.width()//2, 0).name() == border
            assert_round(popup)
        combo.view().setCurrentIndex(combo.model().index(50, 0))
        QTest.keyClick(combo.view(), Qt.Key.Key_Return)
        assert combo.currentIndex() == 50
    finally:
        combo.hidePopup()
        combo.close()


def test_real_tooltip_reuse_is_rounded_but_magnifier_is_untouched(theme):
    owner = QWidget()
    owner.show()
    magnifier = QLabel(owner, Qt.WindowType.ToolTip)
    magnifier.setObjectName('magnifierPopup')
    magnifier.resize(200, 200)
    try:
        for text in ('Short', 'Longer tooltip\nSecond line'):
            QToolTip.showText(QPoint(60, 60), text, owner)
            theme.processEvents()
            tip = next(w for w in QApplication.topLevelWidgets() if w.objectName() == 'qtooltip_label')
            assert_round(tip)
            assert tip.text() == text
        magnifier.show()
        theme.processEvents()
        assert magnifier.mask().isEmpty()
    finally:
        QToolTip.hideText()
        magnifier.close()
        owner.close()


def test_theme_reuse_removes_hard_masks_without_replacing_proxy(theme):
    menu = QMenu()
    menu.addAction('Item')
    try:
        menu.popup(QPoint(20, 20))
        theme.processEvents()
        proxy = theme._pdfdocuedit_round_style
        coordinator = theme._pdfdocuedit_popup_shapes
        for mode in ('light', 'dark') * 3:
            apply_theme(theme, mode)
            theme.setStyleSheet(global_style())
            menu.setMask(QRegion(menu.rect()))
            menu.repaint()
            theme.processEvents()
            assert_round(menu)
            assert theme._pdfdocuedit_round_style is proxy
            assert theme._pdfdocuedit_popup_shapes is coordinator
    finally:
        menu.close()


def test_paint_leaves_alpha_alone_and_removes_a_native_mask(theme, monkeypatch):
    menu = QMenu()
    menu.addAction('Cached shape')
    calls = []
    original_set_mask = menu.setMask
    original_clear_mask = menu.clearMask
    def clear_mask():
        calls.append(True)
        original_clear_mask()
    monkeypatch.setattr(menu, 'clearMask', clear_mask)
    try:
        menu.popup(QPoint(20, 20))
        theme.processEvents()
        calls.clear()
        for _ in range(5):
            menu.repaint()
            theme.processEvents()
        assert calls == []
        original_set_mask(QRegion(menu.rect()))
        menu.repaint()
        theme.processEvents()
        assert len(calls) == 1
        assert_round(menu)
    finally:
        menu.close()


def test_private_popup_state_survives_temporary_python_wrappers(theme):
    import gc
    combo = QComboBox()
    combo.addItems(['First', 'Second'])
    combo.show()
    try:
        combo.showPopup()
        theme.processEvents()
        popup = combo.view().window()
        assert popup.property('_popup_alpha')
        del popup
        gc.collect()
        for _ in range(4):
            theme.processEvents()
            popup = combo.view().window()
            assert popup.property('_popup_alpha')
            assert popup.property('_popup_shape_registered')
            assert_round(popup)
            del popup
            gc.collect()
    finally:
        combo.hidePopup()
        combo.close()


def test_dynamic_popups_across_windows_close_with_escape(theme):
    owners = [QWidget(), QWidget()]
    try:
        for owner in owners:
            owner.show()
        for index in range(12):
            menu = QMenu(owners[index % 2])
            menu.addAction('First')
            menu.addMenu('Nested').addAction('Child')
            menu.popup(QPoint(30, 30))
            theme.processEvents()
            assert_round(menu)
            QTest.keyClick(menu, Qt.Key.Key_Down)
            assert menu.activeAction().text() == 'First'
            QTest.keyClick(menu, Qt.Key.Key_Escape)
            assert not menu.isVisible()
            menu.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert all(owner.mask().isEmpty() for owner in owners)
    finally:
        for owner in owners:
            owner.close()


def test_first_popup_supports_alpha_when_native_handle_already_exists(theme):
    menu = QMenu()
    menu.addAction('First native popup')
    menu.ensurePolished()
    menu.winId()  # QMenu can create its native surface before aboutToShow.
    try:
        menu.popup(QPoint(30, 30))
        theme.processEvents()
        window = menu.windowHandle()
        assert window.requestedFormat().alphaBufferSize() >= 8
        # The offscreen plugin reports a default actual format (-1), even for
        # correctly painted alpha surfaces; Windows exposes the real format.
        if theme.platformName() == 'windows':
            assert window.format().alphaBufferSize() >= 8
        assert_round(menu)
    finally:
        menu.close()


@pytest.mark.parametrize('kind', ['menu', 'combo', 'dropdown'])
def test_popup_event_filter_lifetime_belongs_to_watched_widget(theme, kind):
    from PyQt6 import sip

    from styles.popups import _PopupSurfaceEvents

    owner = QComboBox() if kind != 'menu' else QMenu()
    widget = owner.view().window() if kind == 'dropdown' else owner
    widget.ensurePolished()
    coordinator = theme._pdfdocuedit_popup_shapes
    coordinator.register(widget)
    filters = widget.findChildren(_PopupSurfaceEvents, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert len(filters) == 1, 'Each surface must own its event filter until its own destruction'
    watched_filter = filters[0]
    for _ in range(4):
        coordinator.register(widget)
    assert widget.findChildren(_PopupSurfaceEvents, options=Qt.FindChildOption.FindDirectChildrenOnly) == filters
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(owner, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(widget) and sip.isdeleted(watched_filter)
    assert not sip.isdeleted(coordinator)
