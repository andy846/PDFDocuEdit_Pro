"""Isolated synthetic QA executable; never included in the shipped application."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def phase_run(phase, directory):
    os.environ['PDFDOCUEDIT_ENABLE_COMPOSITION']='0'
    os.environ['PDFDOCUEDIT_UPDATE_ROOT']=str(directory/'isolated-data')
    import fitz
    from PyQt6.QtCore import QSettings, QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from auth.application import PrivateApplication
    from auth.config import AuthConfig
    from auth.controller import AuthController
    from auth.model import Approval, timestamp
    from auth.store import ApprovalStore
    from core import viewer as viewer_module
    from core.diagnostics import configure_lifecycle_logging
    from core.settings import SettingsManager
    from dialogs.annotation_dialogs import WatermarkDialog
    from main import SingleInstanceRouter

    app=QApplication(['watermark-close-isolated-qa'])
    app.setOrganizationName('PDFDocuEdit-QA')
    app.setApplicationName('Watermark-Close-QA')
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(directory/'qsettings'))
    configure_lifecycle_logging(directory/'logs')
    viewer_module.SettingsManager=lambda: SettingsManager(directory/(phase+'-settings.json'))
    source=directory/'source.pdf'
    other=directory/'other.pdf'
    if phase=='edit':
        for path in (source,other):
            assert not path.exists(), 'QA output must be fresh'
            with fitz.open() as doc:
                page=doc.new_page()
                page.draw_rect(fitz.Rect(50,50,250,200),fill=(0,.5,1))
                if path==source:
                    png=page.get_pixmap().tobytes('png')
                    doc.delete_page(0)
                    page=doc.new_page()
                    page.insert_image(page.rect,stream=png)
                    page.set_rotation(90)
                else:
                    page.insert_text((72,240),'Fresh process: other PDF')
                doc.save(path)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    class Memory:
        value=None
        def get_password(self,*args): return self.value
        def set_password(self,*args): self.value=args[-1]
        def delete_password(self,*args): self.value=None
    config=AuthConfig('qatest','https://qatest.supabase.co','sb_publishable_qa')
    controller=AuthController(SimpleNamespace(),ApprovalStore('qatest',backend=Memory()))
    private=PrivateApplication(app,config,viewer_module.PDFViewer,controller=controller)
    now=timestamp()
    controller.commit_approval(Approval('qatest','f63613d9-81b8-4a36-b765-a37b6e9e0916',
                                        'qa@example.invalid','not-a-real-refresh-token',now,now))
    controller.timer.stop()
    viewer=private.viewer
    viewer.resize(1100,760)
    server='PDFDocuEdit-Watermark-QA-'+uuid4().hex
    router=SingleInstanceRouter(server,parent=app)
    assert router.listen()
    router.pathsReceived.connect(private.accept_paths)
    target=source if phase=='edit' else other
    state={'phase':phase,'pid':os.getpid(),'frozen':bool(getattr(sys,'frozen',False)),
           'real_account_login':False,'source_sha256':before,'rendered':False}
    def write():
        state.update(exiting=private.exiting,viewer_released=private.viewer is None,
                     source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==before)
        (directory/(phase+'-result.json')).write_text(json.dumps(state,indent=2),encoding='utf-8')
    def fail(error):
        state['error']=type(error).__name__
        state['trace']=traceback.format_exc()
        write()
        app.exit(2)
    def inspect_page():
        try:
            session=viewer._session
            if session is None or not session.engine.is_loaded() or not session.canvas._page_views:
                return
            pixmap=session.canvas._page_views.get(0).overlay._pixmap
            if pixmap is None:
                return
            poll.stop()
            image=pixmap.toImage()
            hits=sum(image.pixelColor(x,y).red()<240 or image.pixelColor(x,y).green()<240
                     for x in range(0,image.width(),max(1,image.width()//32))
                     for y in range(0,image.height(),max(1,image.height()//32)))
            assert hits>0
            state.update(rendered=True,non_white_samples=hits)
            if phase=='edit':
                class AutoApply(WatermarkDialog):
                    def exec(self):
                        QTimer.singleShot(220,self._validate)
                        return super().exec()
                viewer_module.WatermarkDialog=AutoApply
                viewer._show_watermark_dialog()
                assert session.engine.is_modified
                question=QMessageBox.question
                def discard(*args,**kwargs):
                    QTimer.singleShot(50,lambda: QApplication.activeModalWidget().button(
                        QMessageBox.StandardButton.Discard).click())
                    return question(*args,**kwargs)
                QMessageBox.question=discard
            viewer.close()
        except BaseException as error:
            fail(error)
    poll=QTimer(app)
    poll.timeout.connect(inspect_page)
    poll.start(20)
    app.aboutToQuit.connect(write)
    QTimer.singleShot(30000,lambda: fail(TimeoutError('QA deadline')))
    QTimer.singleShot(0,lambda: SingleInstanceRouter.forward_to_primary([target],server))
    code=app.exec()
    assert code==0 and state['rendered'] and private.exiting and private.viewer is None
    assert state['source_unchanged']
    return 0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=('edit','open','all'),default='all')
    parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    directory=args.directory.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    if args.phase!='all':
        return phase_run(args.phase,directory)
    command=[sys.executable] + ([] if getattr(sys,'frozen',False) else [str(Path(__file__).resolve())])
    env=dict(os.environ,PYTHONPATH=str(Path.cwd()),QT_QPA_PLATFORM='offscreen',
             HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='')
    for phase in ('edit','open'):
        with (directory/(phase+'.log')).open('w',encoding='utf-8') as log:
            subprocess.run(command+['--phase',phase,'--directory',str(directory)],check=True,
                           env=env,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    reports=[json.loads((directory/(phase+'-result.json')).read_text()) for phase in ('edit','open')]
    assert len({r['pid'] for r in reports})==2
    assert all(r['rendered'] and r['exiting'] and r['viewer_released'] and r['source_unchanged'] for r in reports)
    result={'passed':True,'separate_processes':True,'reports':reports}
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
