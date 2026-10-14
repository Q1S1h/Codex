"""Windows desktop entry point; --smoke-test is a finite offscreen startup check."""
import argparse
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description='XPS Analysis Studio V0.2')
    parser.add_argument('--smoke-test', action='store_true', help='Show window then exit after 800 ms')
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('XPS Analysis Studio')
    window = MainWindow()
    window.show()
    if args.smoke_test:
        QTimer.singleShot(800, app.quit)
    return app.exec()
