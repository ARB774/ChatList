import sys

from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from db import Database


def bootstrap_database() -> Database:
    database = Database()
    database.initialize()
    return database


class MainWindow(QWidget):
    def __init__(self, database: Database):
        super().__init__()
        self.database = database
        self.setWindowTitle("ChatList")

        self.label = QLabel("")
        self.button = QPushButton("Нажми меня")
        self.button.clicked.connect(self.show_message)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def show_message(self):
        self.label.setText("Минимальная программа на Python")


def main() -> int:
    database = bootstrap_database()
    app = QApplication(sys.argv)
    window = MainWindow(database)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
