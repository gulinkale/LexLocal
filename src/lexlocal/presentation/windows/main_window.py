from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    """Main desktop window for LexLocal."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("LexLocal")
        self.resize(960, 640)

        placeholder = QLabel("LexLocal")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setCentralWidget(placeholder)