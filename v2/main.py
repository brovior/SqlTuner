"""
Oracle SQL Tuner v2 — 어플리케이션 진입점

실행 방법:
  py -3.13-32 v2/main.py          (v2 디렉토리 기준)
  또는 프로젝트 루트에서:
  py -3.13-32 -m v2.main
"""
import sys
import os

# 프로젝트 루트를 Python 경로에 추가 (v2 패키지가 최상위에서 import 가능하도록)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PyQt5.QtWidgets import QApplication
from v2.ui.main_window import MainWindow
from v2.core.app_logger import get_logger

_logger = get_logger('main')


def main():
    os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')

    app = QApplication(sys.argv)
    app.setApplicationName('Oracle SQL Tuner v2')
    app.setOrganizationName('SQLTuner')
    app.setStyle('Fusion')

    _logger.info('===== Oracle SQL Tuner v2 시작 =====')

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    _logger.info('===== 앱 종료 (exit_code=%d) =====', exit_code)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
