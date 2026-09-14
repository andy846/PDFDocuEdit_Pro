import fitz
import pytest

from core.comparison import compare_snapshots, manual_pair, snapshot_file, unpair
from core.tasks import TaskCancelled


def pdf(pages):
    with fitz.open() as doc:
        for text in pages:
            page = doc.new_page()
            page.insert_text((50, 60), text)
        return doc.tobytes()


def test_same_and_inserted_pages():
    a = pdf(['First original page', 'Second unique page', 'Third page'])
    assert all(p.status == 'Same' for p in compare_snapshots(a, a))
    b = pdf(['First original page', 'An inserted page', 'Second unique page', 'Third page'])
    result = compare_snapshots(a, b)
    assert [(p.a, p.b) for p in result] == [(0, 0), (None, 1), (1, 2), (2, 3)]
    assert result[1].status == 'Added'
    assert compare_snapshots(b, a)[1].status == 'Deleted'


def test_text_changes_regions_and_sizes():
    result = compare_snapshots(pdf(['The amount is 100']), pdf(['The amount is 200']))[0]
    assert result.status == 'Modified'
    assert result.text[0].before == '100'
    assert result.text[0].after == '200'
    assert result.a_regions and result.b_regions
    with fitz.open(stream=pdf(['']), filetype='pdf') as a, fitz.open() as b:
        b.new_page(width=300, height=300)
        result = compare_snapshots(a.tobytes(), b.tobytes())[0]
        assert result.status == 'Modified'
        assert not result.has_text


def test_scans_rotation_and_cancellation():
    with fitz.open() as a, fitz.open() as b:
        a.new_page().draw_rect(fitz.Rect(20, 20, 70, 70), fill=(0, 0, 0))
        b.new_page().draw_rect(fitz.Rect(25, 20, 70, 70), fill=(0, 0, 0))
        result = compare_snapshots(a.tobytes(), b.tobytes())[0]
        assert not result.has_text
        assert result.status == 'Modified'
        b[0].set_rotation(90)
        assert compare_snapshots(a.tobytes(), b.tobytes())[0].status == 'Modified'
        with pytest.raises(TaskCancelled):
            compare_snapshots(a.tobytes(), b.tobytes(), cancelled=lambda: True)


def test_manual_pairing_preserves_pages():
    pairs = [(0, 0), (1, 1), (2, 2)]
    split = unpair(pairs, 1)
    assert split == [(0, 0), (1, None), (None, 1), (2, 2)]
    assert manual_pair(split, 1, 1) == pairs
    with pytest.raises(ValueError, match='cross'):
        manual_pair(pairs, 0, 2)


def test_encrypted_snapshot_is_independent(tmp_path):
    path = tmp_path / 'secret.pdf'
    with fitz.open(stream=pdf(['Private page']), filetype='pdf') as doc:
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='test', owner_pw='owner')
    with pytest.raises(ValueError):
        snapshot_file(path)
    snapshot = snapshot_file(path, 'test')
    path.write_bytes(pdf(['Changed source']))
    assert compare_snapshots(snapshot, snapshot)[0].status == 'Same'
    assert compare_snapshots(snapshot, snapshot_file(path))[0].status != 'Same'


def test_workspace_async_and_stale():
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication

    from dialogs.comparison_dialog import ComparisonDialog
    app = QApplication.instance() or QApplication([])
    a, b = pdf(['Amount 10']), pdf(['Amount 20'])
    revision = [1]
    dialog = ComparisonDialog(('A', lambda: a, lambda: revision[0]), [('B', lambda: b, lambda: 1)])
    try:
        dialog.start_comparison()
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if dialog._task is None else None)
        timer.start(20)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        timer.stop()
        assert dialog._task is None
        assert dialog.results[0].status == 'Modified'
        revision[0] += 1
        dialog.check_stale()
        assert 'out of date' in dialog.status.text()
        app.processEvents()
    finally:
        dialog.close()


def test_manual_pair_across_unpaired_pages():
    result = manual_pair([(0, None), (1, None), (None, 0), (None, 1)], 0, 1)
    assert result == [(None, 0), (0, 1), (1, None)]
