from tests.composition.test_designer_controls import wait


def confirm_review(window):
    controller = window.production_review
    wait(lambda: bool(controller.contexts) and not controller.check_worker and len(controller.results) == len(controller.contexts))
    assert all(r["status"] == "checked" for r in controller.results), controller.results
    controller.pane.acknowledge.setChecked(True)
    controller.refresh_confirm()
    assert controller.pane.confirm.isEnabled(), controller.pane.status.text()
    controller.pane.confirm.click()
