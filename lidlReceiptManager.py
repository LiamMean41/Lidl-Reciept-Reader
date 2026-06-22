#!/usr/bin/env python3
"""
Lidl Receipt Manager
====================
A desktop app that reads Lidl (Ireland) receipts, builds a searchable
product/price database, and lets you build tick-off shopping lists.

Import a receipt three ways:
  * from an image (PNG/JPG screenshot) - needs Tesseract OCR + pytesseract
  * from a .txt file containing the receipt text
  * by pasting the receipt text directly

Data is stored in a local SQLite database at ~/.lidl_receipts/receipts.db

Run:
    pip install PyQt5
    pip install pytesseract pillow      # optional, only for image import
    python lidl_receipt_manager.py
"""
import os
import re
import sys
import sqlite3
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTableWidget, QTableWidgetItem, QListWidget,
    QListWidgetItem, QSplitter, QHeaderView, QMessageBox, QInputDialog, QFileDialog,
    QAbstractItemView, QComboBox, QDialog, QPlainTextEdit, QDialogButtonBox,
)

# ----- optional OCR support ------------------------------------------------
try:
    import pytesseract
    from PIL import Image
    # Point pytesseract at the Tesseract executable if it isn't already on PATH.
    if not pytesseract.pytesseract.tesseract_cmd or \
            os.path.basename(pytesseract.pytesseract.tesseract_cmd).lower() == 'tesseract':
        for _cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.join(os.environ.get('LOCALAPPDATA', ''),
                         r"Programs\Tesseract-OCR\tesseract.exe"),
        ):
            if os.path.isfile(_cand):
                pytesseract.pytesseract.tesseract_cmd = _cand
                break
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


# ===========================================================================
#  RECEIPT PARSER
# ===========================================================================
PRICE_LINE = re.compile(r'^(?P<name>.+?)\s{2,}(?P<price>\d+\.\d{2})\s+(?P<vat>[A-F])\s*$')
PRICE_LINE_LOOSE = re.compile(r'^(?P<name>.+?)\s+(?P<price>\d+\.\d{2})\s+(?P<vat>[A-F])\s*$')
QTY_LINE = re.compile(r'^\s*(?P<qty>\d+)\s*[xX]\s*(?P<unit>\d+\.\d{2})\s*$')
DISCOUNT = re.compile(r'-(?P<amt>\d+\.\d{2})\s*$')
TRN = re.compile(r'TRN-ID:\s*(\S+)')
DATE = re.compile(r'Date:\s*(\d{2}/\d{2}/\d{2})')
TOTAL = re.compile(r'^TOTAL\s+(\d+\.\d{2})\s*$')
STORE = re.compile(r'^([A-Za-z].+?)\s+-\s+IE\w+')
SKIP_NAME = re.compile(r'deposit', re.IGNORECASE)


def _is_noise(line):
    s = line.strip()
    if not s:
        return True
    if set(s) <= set('-= '):
        return True
    if s in ('EUR', 'Copy', 'More to Value.'):
        return True
    return False


def parse_receipt(text):
    """Parse raw receipt text into {store, date, trn_id, total, items[]}."""
    lines = text.splitlines()
    store = trn_id = rdate = total = None

    for ln in lines:
        if store is None:
            m = STORE.search(ln)
            if m:
                store = m.group(1).strip()
        m = TRN.search(ln)
        if m:
            trn_id = m.group(1).strip()
        m = DATE.search(ln)
        if m:
            try:
                rdate = datetime.strptime(m.group(1), '%d/%m/%y').date().isoformat()
            except ValueError:
                pass

    items = []
    current = None
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        m = TOTAL.match(stripped)
        if m:
            total = float(m.group(1))
            break
        if _is_noise(line):
            continue

        mq = QTY_LINE.match(stripped)
        if mq and current is not None:
            current['qty'] = int(mq.group('qty'))
            continue

        md = DISCOUNT.search(stripped)
        if md and current is not None:
            current['discount'] -= float(md.group('amt'))
            continue

        mp = PRICE_LINE.match(stripped) or PRICE_LINE_LOOSE.match(stripped)
        if mp:
            name = mp.group('name').strip()
            current = {
                'name': name,
                'gross': float(mp.group('price')),
                'vat': mp.group('vat'),
                'qty': 1,
                'discount': 0.0,
                'deposit': bool(SKIP_NAME.search(name)),
            }
            items.append(current)

    products = []
    for it in items:
        if it['deposit']:
            continue
        net = round(it['gross'] + it['discount'], 2)
        qty = it['qty'] or 1
        products.append({
            'name': it['name'],
            'qty': qty,
            'unit_price': round(net / qty, 2) if qty else net,
            'line_total': net,
            'vat': it['vat'],
        })

    return {'store': store, 'date': rdate, 'trn_id': trn_id,
            'total': total, 'items': products}


# ===========================================================================
#  DATABASE
# ===========================================================================
class DB:
    def __init__(self):
        folder = os.path.join(os.path.expanduser('~'), '.lidl_receipts')
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, 'receipts.db')
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY,
            store TEXT, rdate TEXT, trn_id TEXT UNIQUE,
            total REAL, imported_at TEXT
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY,
            receipt_id INTEGER, name TEXT, qty INTEGER,
            unit_price REAL, line_total REAL, vat TEXT,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY, name TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS list_items (
            id INTEGER PRIMARY KEY,
            list_id INTEGER, name TEXT, price REAL,
            qty INTEGER DEFAULT 1, checked INTEGER DEFAULT 0,
            FOREIGN KEY(list_id) REFERENCES lists(id) ON DELETE CASCADE
        );
        """)
        self.conn.commit()

    # ----- receipts -----
    def save_receipt(self, parsed):
        """Returns (status, count). status in {'ok','duplicate','empty'}."""
        if not parsed['items']:
            return ('empty', 0)
        trn = parsed['trn_id']
        if trn:
            existing = self.conn.execute(
                "SELECT id FROM receipts WHERE trn_id=?", (trn,)).fetchone()
            if existing:
                return ('duplicate', 0)
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO receipts (store,rdate,trn_id,total,imported_at) "
            "VALUES (?,?,?,?,?)",
            (parsed['store'], parsed['date'], trn, parsed['total'],
             datetime.now().isoformat(timespec='seconds')))
        rid = cur.lastrowid
        for it in parsed['items']:
            cur.execute(
                "INSERT INTO purchases (receipt_id,name,qty,unit_price,line_total,vat) "
                "VALUES (?,?,?,?,?,?)",
                (rid, it['name'], it['qty'], it['unit_price'],
                 it['line_total'], it['vat']))
        self.conn.commit()
        return ('ok', len(parsed['items']))

    def products(self, search=''):
        q = """
        SELECT name,
               ROUND(AVG(unit_price),2) AS avg_price,
               ROUND(MIN(unit_price),2) AS min_price,
               ROUND(MAX(unit_price),2) AS max_price,
               COUNT(*) AS times,
               MAX(rdate) AS last_seen
        FROM purchases p JOIN receipts r ON p.receipt_id = r.id
        """
        params = ()
        if search:
            q += " WHERE name LIKE ?"
            params = ('%' + search + '%',)
        q += " GROUP BY name ORDER BY name COLLATE NOCASE"
        return self.conn.execute(q, params).fetchall()

    def latest_price(self, name):
        row = self.conn.execute(
            "SELECT unit_price FROM purchases p JOIN receipts r ON p.receipt_id=r.id "
            "WHERE name=? ORDER BY r.rdate DESC, p.id DESC LIMIT 1", (name,)).fetchone()
        return row['unit_price'] if row else 0.0

    def receipt_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]

    # ----- lists -----
    def lists(self):
        return self.conn.execute(
            "SELECT * FROM lists ORDER BY created_at DESC, id DESC").fetchall()

    def create_list(self, name):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO lists (name,created_at) VALUES (?,?)",
                    (name, datetime.now().isoformat(timespec='seconds')))
        self.conn.commit()
        return cur.lastrowid

    def rename_list(self, list_id, name):
        self.conn.execute("UPDATE lists SET name=? WHERE id=?", (name, list_id))
        self.conn.commit()

    def delete_list(self, list_id):
        self.conn.execute("DELETE FROM list_items WHERE list_id=?", (list_id,))
        self.conn.execute("DELETE FROM lists WHERE id=?", (list_id,))
        self.conn.commit()

    def list_items(self, list_id):
        return self.conn.execute(
            "SELECT * FROM list_items WHERE list_id=? ORDER BY checked, id",
            (list_id,)).fetchall()

    def add_item(self, list_id, name, price, qty=1):
        self.conn.execute(
            "INSERT INTO list_items (list_id,name,price,qty,checked) VALUES (?,?,?,?,0)",
            (list_id, name, price, qty))
        self.conn.commit()

    def set_checked(self, item_id, checked):
        self.conn.execute("UPDATE list_items SET checked=? WHERE id=?",
                          (1 if checked else 0, item_id))
        self.conn.commit()

    def remove_item(self, item_id):
        self.conn.execute("DELETE FROM list_items WHERE id=?", (item_id,))
        self.conn.commit()

    def clear_checked(self, list_id):
        self.conn.execute("DELETE FROM list_items WHERE list_id=? AND checked=1",
                          (list_id,))
        self.conn.commit()


# ===========================================================================
#  PASTE DIALOG
# ===========================================================================
class PasteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste receipt text")
        self.resize(480, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Paste the full text of a Lidl receipt below:"))
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("monospace"))
        lay.addWidget(self.edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def text(self):
        return self.edit.toPlainText()


# ===========================================================================
#  MAIN WINDOW
# ===========================================================================
class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Lidl Receipt Manager")
        self.resize(940, 680)

        tabs = QTabWidget()
        tabs.addTab(self._build_products_tab(), "Products")
        tabs.addTab(self._build_lists_tab(), "Shopping Lists")
        self.setCentralWidget(tabs)

        self.refresh_products()
        self.refresh_lists()
        self._update_list_combo()

    # ---------------------------------------------------------------- PRODUCTS
    def _build_products_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # import toolbar
        bar = QHBoxLayout()
        b_img = QPushButton("Import from image…")
        b_img.clicked.connect(self.import_image)
        b_txt = QPushButton("Import from text file…")
        b_txt.clicked.connect(self.import_textfile)
        b_paste = QPushButton("Paste receipt text…")
        b_paste.clicked.connect(self.import_paste)
        bar.addWidget(b_img)
        bar.addWidget(b_txt)
        bar.addWidget(b_paste)
        bar.addStretch()
        self.lbl_count = QLabel()
        bar.addWidget(self.lbl_count)
        v.addLayout(bar)

        # search
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("type to filter products…")
        self.search.textChanged.connect(self.refresh_products)
        srow.addWidget(self.search)
        v.addLayout(srow)

        # table
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(
            ["Product", "Avg €", "Min €", "Max €", "Times", "Last bought"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 6):
            h.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        v.addWidget(self.tbl)

        # add-to-list controls
        addrow = QHBoxLayout()
        addrow.addWidget(QLabel("Add selected to:"))
        self.list_combo = QComboBox()
        self.list_combo.setMinimumWidth(200)
        addrow.addWidget(self.list_combo)
        b_add = QPushButton("Add →")
        b_add.clicked.connect(self.add_selected_to_list)
        addrow.addWidget(b_add)
        b_new = QPushButton("New list…")
        b_new.clicked.connect(self.new_list_from_products)
        addrow.addWidget(b_new)
        addrow.addStretch()
        v.addLayout(addrow)

        if not OCR_AVAILABLE:
            note = QLabel("Image import needs Tesseract OCR + "
                          "'pip install pytesseract pillow'. "
                          "Text/paste import always works.")
            note.setStyleSheet("color:#888; font-style:italic;")
            v.addWidget(note)
        return w

    def refresh_products(self):
        rows = self.db.products(self.search.text().strip())
        self.tbl.setRowCount(0)
        for r in rows:
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            vals = [r['name'],
                    f"{r['avg_price']:.2f}", f"{r['min_price']:.2f}",
                    f"{r['max_price']:.2f}", str(r['times']),
                    r['last_seen'] or ""]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col != 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.tbl.setItem(i, col, item)
        self.lbl_count.setText(
            f"{len(rows)} products  ·  {self.db.receipt_count()} receipts")

    # ---------------------------------------------------------------- IMPORT
    def _handle_parsed(self, parsed):
        status, n = self.db.save_receipt(parsed)
        if status == 'ok':
            QMessageBox.information(
                self, "Imported",
                f"Added {n} products from receipt "
                f"({parsed.get('store') or 'Lidl'}, {parsed.get('date') or '?'}).")
            self.refresh_products()
        elif status == 'duplicate':
            QMessageBox.information(self, "Already imported",
                                    "This receipt is already in the database.")
        else:
            QMessageBox.warning(
                self, "Nothing found",
                "Couldn't find any products in that text. If it came from an "
                "image, the OCR quality may be too low — try the paste option.")

    def import_image(self):
        if not OCR_AVAILABLE:
            QMessageBox.warning(
                self, "OCR not available",
                "Image import needs Tesseract OCR installed plus the Python "
                "packages:\n\n    pip install pytesseract pillow\n\n"
                "On Linux also: sudo apt install tesseract-ocr\n\n"
                "Meanwhile you can use 'Paste receipt text…'.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose receipt image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            text = pytesseract.image_to_string(Image.open(path))
        except Exception as e:
            QMessageBox.critical(self, "OCR failed", str(e))
            return
        self._handle_parsed(parse_receipt(text))

    def import_textfile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose receipt text file", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            self._handle_parsed(parse_receipt(f.read()))

    def import_paste(self):
        dlg = PasteDialog(self)
        if dlg.exec_() == QDialog.Accepted and dlg.text().strip():
            self._handle_parsed(parse_receipt(dlg.text()))

    # ------------------------------------------------ add products to a list
    def _update_list_combo(self):
        self.list_combo.clear()
        for l in self.db.lists():
            self.list_combo.addItem(l['name'], l['id'])

    def add_selected_to_list(self):
        rows = sorted({i.row() for i in self.tbl.selectedItems()})
        if not rows:
            QMessageBox.information(self, "Nothing selected",
                                    "Select one or more products first.")
            return
        if self.list_combo.count() == 0:
            self.new_list_from_products()
            if self.list_combo.count() == 0:
                return
        list_id = self.list_combo.currentData()
        for row in rows:
            name = self.tbl.item(row, 0).text()
            self.db.add_item(list_id, name, self.db.latest_price(name))
        self.refresh_lists()
        QMessageBox.information(
            self, "Added",
            f"Added {len(rows)} item(s) to '{self.list_combo.currentText()}'.")

    def new_list_from_products(self):
        name, ok = QInputDialog.getText(self, "New list", "List name:")
        if ok and name.strip():
            self.db.create_list(name.strip())
            self._update_list_combo()
            self.list_combo.setCurrentIndex(0)
            self.refresh_lists()

    # ------------------------------------------------------------- LISTS TAB
    def _build_lists_tab(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        split = QSplitter(Qt.Horizontal)

        # left: lists
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Shopping lists"))
        self.lists_widget = QListWidget()
        self.lists_widget.currentItemChanged.connect(self.refresh_items)
        lv.addWidget(self.lists_widget)
        lbtns = QHBoxLayout()
        for label, fn in [("New", self.new_list), ("Rename", self.rename_list),
                          ("Delete", self.delete_list)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            lbtns.addWidget(b)
        lv.addLayout(lbtns)
        split.addWidget(left)

        # right: items
        right = QWidget()
        rv = QVBoxLayout(right)
        self.items_title = QLabel("Items")
        f = self.items_title.font()
        f.setBold(True)
        self.items_title.setFont(f)
        rv.addWidget(self.items_title)

        self.items_tbl = QTableWidget(0, 3)
        self.items_tbl.setHorizontalHeaderLabels(["✓", "Item", "€"])
        self.items_tbl.verticalHeader().setVisible(False)
        self.items_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ih = self.items_tbl.horizontalHeader()
        ih.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ih.setSectionResizeMode(1, QHeaderView.Stretch)
        ih.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.items_tbl.itemChanged.connect(self._item_checked_changed)
        rv.addWidget(self.items_tbl)

        # add item manually
        arow = QHBoxLayout()
        self.item_name = QLineEdit()
        self.item_name.setPlaceholderText("add an item…")
        self.item_name.returnPressed.connect(self.add_manual_item)
        self.item_price = QLineEdit()
        self.item_price.setPlaceholderText("€")
        self.item_price.setFixedWidth(70)
        self.item_price.returnPressed.connect(self.add_manual_item)
        b_addi = QPushButton("Add")
        b_addi.clicked.connect(self.add_manual_item)
        arow.addWidget(self.item_name)
        arow.addWidget(self.item_price)
        arow.addWidget(b_addi)
        rv.addLayout(arow)

        # footer actions + remaining total
        frow = QHBoxLayout()
        b_rm = QPushButton("Remove selected")
        b_rm.clicked.connect(self.remove_selected_item)
        b_clear = QPushButton("Clear ticked")
        b_clear.clicked.connect(self.clear_ticked)
        frow.addWidget(b_rm)
        frow.addWidget(b_clear)
        frow.addStretch()
        self.total_lbl = QLabel("Remaining: €0.00")
        frow.addWidget(self.total_lbl)
        rv.addLayout(frow)

        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        outer.addWidget(split)
        return w

    def refresh_lists(self):
        current_id = None
        it = self.lists_widget.currentItem()
        if it:
            current_id = it.data(Qt.UserRole)
        self.lists_widget.blockSignals(True)
        self.lists_widget.clear()
        for l in self.db.lists():
            item = QListWidgetItem(l['name'])
            item.setData(Qt.UserRole, l['id'])
            self.lists_widget.addItem(item)
            if l['id'] == current_id:
                self.lists_widget.setCurrentItem(item)
        self.lists_widget.blockSignals(False)
        if self.lists_widget.currentItem() is None and self.lists_widget.count():
            self.lists_widget.setCurrentRow(0)
        self._update_list_combo()
        self.refresh_items()

    def _current_list_id(self):
        it = self.lists_widget.currentItem()
        return it.data(Qt.UserRole) if it else None

    def refresh_items(self, *_):
        self.items_tbl.blockSignals(True)
        self.items_tbl.setRowCount(0)
        lid = self._current_list_id()
        if lid is None:
            self.items_title.setText("Items")
            self.total_lbl.setText("Remaining: €0.00")
            self.items_tbl.blockSignals(False)
            return
        self.items_title.setText(self.lists_widget.currentItem().text())
        remaining = 0.0
        for r in self.db.list_items(lid):
            i = self.items_tbl.rowCount()
            self.items_tbl.insertRow(i)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if r['checked'] else Qt.Unchecked)
            chk.setData(Qt.UserRole, r['id'])
            name_item = QTableWidgetItem(r['name'])
            price_item = QTableWidgetItem(f"{r['price']:.2f}")
            price_item.setTextAlignment(Qt.AlignCenter)
            if r['checked']:
                for cell in (name_item, price_item):
                    fnt = cell.font()
                    fnt.setStrikeOut(True)
                    cell.setFont(fnt)
                    cell.setForeground(QColor("#aaaaaa"))
            else:
                remaining += r['price']
            self.items_tbl.setItem(i, 0, chk)
            self.items_tbl.setItem(i, 1, name_item)
            self.items_tbl.setItem(i, 2, price_item)
        self.total_lbl.setText(f"Remaining: €{remaining:.2f}")
        self.items_tbl.blockSignals(False)

    def _item_checked_changed(self, item):
        if item.column() != 0:
            return
        item_id = item.data(Qt.UserRole)
        self.db.set_checked(item_id, item.checkState() == Qt.Checked)
        self.refresh_items()

    def new_list(self):
        name, ok = QInputDialog.getText(self, "New list", "List name:")
        if ok and name.strip():
            self.db.create_list(name.strip())
            self.refresh_lists()
            self.lists_widget.setCurrentRow(0)

    def rename_list(self):
        lid = self._current_list_id()
        if lid is None:
            return
        cur = self.lists_widget.currentItem().text()
        name, ok = QInputDialog.getText(self, "Rename list", "New name:", text=cur)
        if ok and name.strip():
            self.db.rename_list(lid, name.strip())
            self.refresh_lists()

    def delete_list(self):
        lid = self._current_list_id()
        if lid is None:
            return
        name = self.lists_widget.currentItem().text()
        if QMessageBox.question(
                self, "Delete list", f"Delete '{name}' and all its items?"
        ) == QMessageBox.Yes:
            self.db.delete_list(lid)
            self.refresh_lists()

    def add_manual_item(self):
        lid = self._current_list_id()
        if lid is None:
            QMessageBox.information(self, "No list", "Create or select a list first.")
            return
        name = self.item_name.text().strip()
        if not name:
            return
        try:
            price = float(self.item_price.text()) if self.item_price.text().strip() else 0.0
        except ValueError:
            price = 0.0
        self.db.add_item(lid, name, price)
        self.item_name.clear()
        self.item_price.clear()
        self.refresh_items()

    def remove_selected_item(self):
        rows = sorted({i.row() for i in self.items_tbl.selectedItems()})
        for row in rows:
            item_id = self.items_tbl.item(row, 0).data(Qt.UserRole)
            self.db.remove_item(item_id)
        self.refresh_items()

    def clear_ticked(self):
        lid = self._current_list_id()
        if lid is None:
            return
        self.db.clear_checked(lid)
        self.refresh_items()


STYLE = """
QWidget { font-size: 14px; }
QPushButton {
    background:#0050aa; color:white; border:none; padding:7px 14px;
    border-radius:5px;
}
QPushButton:hover { background:#0066d6; }
QTableWidget { gridline-color:#e3e3e3; }
QHeaderView::section {
    background:#f4f6f8; padding:6px; border:none; border-bottom:1px solid #ddd;
    font-weight:bold;
}
QLineEdit, QComboBox, QPlainTextEdit {
    padding:6px; border:1px solid #cfd4da; border-radius:5px;
}
QTabBar::tab { padding:9px 18px; }
QTabBar::tab:selected { color:#0050aa; font-weight:bold; }
QListWidget { border:1px solid #cfd4da; border-radius:5px; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    db = DB()
    win = MainWindow(db)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
