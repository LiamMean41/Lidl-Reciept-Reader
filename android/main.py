#!/usr/bin/env python3
"""
Lidl Receipt Manager - Android / KivyMD edition
===============================================
Mobile port of the desktop PyQt5 app. Reads Lidl (Ireland) receipts, builds a
searchable product/price database, and lets you build tick-off shopping lists.

Import a receipt three ways:
  * photograph it           - on-device OCR (Google ML Kit on Android)
  * pick an image file       - same OCR path
  * paste the receipt text   - always works

Data lives in a local SQLite database in the app's private storage.

Run on desktop for testing:
    pip install "kivy[base]" kivymd==1.1.1 plyer
    pip install pytesseract pillow        # optional, only for image OCR on desktop
    python main.py

Build the Android APK: see README_ANDROID.md / buildozer.spec.
"""
import os
import threading

from kivy.clock import Clock, mainthread
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import NumericProperty, StringProperty

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import TwoLineListItem
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.snackbar import Snackbar
from kivymd.uix.textfield import MDTextField

from core.db import DB
from core import ocr

ON_ANDROID = ocr.ON_ANDROID

KV = """
ScreenManager:
    MDScreen:
        MDBoxLayout:
            orientation: "vertical"

            MDTopAppBar:
                title: "Lidl Receipt Manager"
                elevation: 2

            MDBottomNavigation:
                panel_color: app.theme_cls.primary_color
                selected_color_background: app.theme_cls.primary_dark
                text_color_active: 1, 1, 1, 1

                # ---------------------------------------------------- PRODUCTS
                MDBottomNavigationItem:
                    name: "products"
                    text: "Products"
                    icon: "basket"

                    MDBoxLayout:
                        orientation: "vertical"
                        padding: dp(8)
                        spacing: dp(6)

                        MDBoxLayout:
                            adaptive_height: True
                            spacing: dp(6)
                            MDRaisedButton:
                                text: "Photo"
                                icon: "camera"
                                on_release: app.import_camera()
                            MDRaisedButton:
                                text: "Image"
                                icon: "image"
                                on_release: app.import_image_file()
                            MDRaisedButton:
                                text: "Paste"
                                icon: "content-paste"
                                on_release: app.import_paste()

                        MDLabel:
                            id: products_count
                            text: ""
                            font_style: "Caption"
                            adaptive_height: True

                        MDTextField:
                            id: search
                            hint_text: "Search products"
                            mode: "rectangle"
                            on_text: app.refresh_products()

                        MDLabel:
                            text: "Tap a product to add it to the current list"
                            font_style: "Caption"
                            theme_text_color: "Hint"
                            adaptive_height: True

                        ScrollView:
                            MDList:
                                id: products_list

                # ------------------------------------------------------ LISTS
                MDBottomNavigationItem:
                    name: "lists"
                    text: "Lists"
                    icon: "format-list-checks"

                    MDBoxLayout:
                        orientation: "vertical"
                        padding: dp(8)
                        spacing: dp(6)

                        MDBoxLayout:
                            adaptive_height: True
                            spacing: dp(6)
                            MDRaisedButton:
                                id: list_picker
                                text: "No list"
                                on_release: app.open_list_menu()
                            MDIconButton:
                                icon: "plus"
                                on_release: app.new_list()
                            MDIconButton:
                                icon: "pencil"
                                on_release: app.rename_list()
                            MDIconButton:
                                icon: "delete"
                                on_release: app.delete_list()

                        ScrollView:
                            MDList:
                                id: items_list

                        MDBoxLayout:
                            adaptive_height: True
                            spacing: dp(6)
                            MDTextField:
                                id: item_name
                                hint_text: "Add an item"
                                mode: "rectangle"
                                size_hint_x: 0.6
                            MDTextField:
                                id: item_price
                                hint_text: "€"
                                mode: "rectangle"
                                input_filter: "float"
                                size_hint_x: 0.2
                            MDIconButton:
                                icon: "plus-circle"
                                on_release: app.add_manual_item()

                        MDBoxLayout:
                            adaptive_height: True
                            spacing: dp(6)
                            MDFlatButton:
                                text: "Clear ticked"
                                on_release: app.clear_ticked()
                            Widget:
                            MDLabel:
                                id: remaining
                                text: "Remaining: €0.00"
                                halign: "right"
                                bold: True
                                adaptive_height: True
"""


class ItemRow(MDBoxLayout):
    """A single shopping-list item: checkbox + name + price + delete."""
    item_id = NumericProperty(0)
    name = StringProperty("")
    price = NumericProperty(0.0)
    checked = NumericProperty(0)


Builder.load_string("""
<ItemRow>:
    orientation: "horizontal"
    adaptive_height: True
    padding: dp(4), 0
    spacing: dp(4)

    MDCheckbox:
        size_hint_x: None
        width: dp(40)
        active: bool(root.checked)
        on_active: app.toggle_item(root, self.active)

    MDLabel:
        text: root.name
        markup: True
        theme_text_color: "Custom"
        text_color: (0.6, 0.6, 0.6, 1) if root.checked else (0, 0, 0, 1)

    MDLabel:
        text: "€%.2f" % root.price
        size_hint_x: None
        width: dp(64)
        halign: "right"
        theme_text_color: "Custom"
        text_color: (0.6, 0.6, 0.6, 1) if root.checked else (0, 0, 0, 1)

    MDIconButton:
        icon: "close"
        on_release: app.remove_item(root.item_id)
""")


class ReceiptApp(MDApp):
    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.material_style = "M2"
        self.title = "Lidl Receipt Manager"
        self.db = DB(folder=self._data_dir())
        self.current_list_id = None
        self.list_menu = None
        self.root = Builder.load_string(KV)
        return self.root

    def on_start(self):
        # Pick the most recent list, if any, then populate both tabs.
        lists = self.db.lists()
        if lists:
            self.current_list_id = lists[0]['id']
        self.refresh_products()
        self.refresh_lists_ui()
        if ON_ANDROID:
            self._request_android_permissions()

    # ---------------------------------------------------------------- helpers
    def _data_dir(self):
        # On Android user_data_dir is the app's private, writable storage.
        try:
            return self.user_data_dir
        except Exception:
            return None  # DB() falls back to ~/.lidl_receipts on desktop

    def _request_android_permissions(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.CAMERA,
                                 Permission.READ_EXTERNAL_STORAGE,
                                 Permission.WRITE_EXTERNAL_STORAGE])
        except Exception:
            pass

    def toast(self, msg):
        Snackbar(text=msg).open()

    # ============================================================== PRODUCTS
    def refresh_products(self, *_):
        ids = self.root.ids
        search = ids.search.text.strip()
        rows = self.db.products(search)
        plist = ids.products_list
        plist.clear_widgets()
        for r in rows:
            sub = ("avg €%.2f  ·  min €%.2f  ·  max €%.2f  ·  x%d"
                   % (r['avg_price'], r['min_price'], r['max_price'], r['times']))
            item = TwoLineListItem(text=r['name'], secondary_text=sub)
            item.bind(on_release=lambda w, name=r['name']: self.add_product_to_list(name))
            plist.add_widget(item)
        ids.products_count.text = (
            "%d products  ·  %d receipts" % (len(rows), self.db.receipt_count()))

    def add_product_to_list(self, name):
        if self.current_list_id is None:
            self.toast("Create a list first (Lists tab)")
            return
        self.db.add_item(self.current_list_id, name, self.db.latest_price(name))
        self.refresh_items_ui()
        self.toast("Added '%s'" % name)

    # ---------------------------------------------------------------- IMPORT
    def _handle_parsed(self, parsed):
        status, n = self.db.save_receipt(parsed)
        if status == 'ok':
            self.refresh_products()
            self.toast("Added %d products (%s, %s)" % (
                n, parsed.get('store') or 'Lidl', parsed.get('date') or '?'))
        elif status == 'duplicate':
            self.toast("This receipt is already imported")
        else:
            self.toast("No products found in that text")

    def _ocr_then_parse(self, path):
        """Run OCR off the UI thread, then parse on the UI thread."""
        if not path:
            self.toast("No image selected")
            return
        self.toast("Reading receipt…")

        def worker():
            try:
                text = ocr.image_to_text(path)
            except Exception:
                import traceback
                self._error_main("OCR failed",
                                 "Path:\n%s\n\n%s" % (path, traceback.format_exc()))
                return
            from core.parser import parse_receipt
            self._parsed_main(parse_receipt(text))

        threading.Thread(target=worker, daemon=True).start()

    @mainthread
    def _toast_main(self, msg):
        self.toast(msg)

    @mainthread
    def _error_main(self, title, text):
        self._show_error(title, text)

    @mainthread
    def _parsed_main(self, parsed):
        self._handle_parsed(parsed)

    def _show_error(self, title, text):
        """Persistent, scrollable error dialog (toasts vanish too fast to read)."""
        from kivymd.uix.label import MDLabel
        from kivy.uix.scrollview import ScrollView
        lbl = MDLabel(text=text, adaptive_height=True, font_style="Caption")
        lbl.bind(width=lambda *_: setattr(lbl, "text_size", (lbl.width, None)))
        sv = ScrollView(size_hint_y=None, height=dp(320))
        sv.add_widget(lbl)
        dlg = MDDialog(title=title, type="custom", content_cls=sv,
                       buttons=[MDFlatButton(text="CLOSE",
                                             on_release=lambda *a: dlg.dismiss())])
        dlg.open()

    def import_camera(self):
        if not ON_ANDROID:
            self.toast("Camera capture is only available on the phone")
            return
        try:
            from plyer import camera
        except Exception:
            self.toast("plyer camera unavailable")
            return
        out = os.path.join(self.user_data_dir, "capture.jpg")
        try:
            camera.take_picture(filename=out,
                                on_complete=lambda p: self._ocr_then_parse(p or out))
        except Exception as e:
            self.toast("Camera error: %s" % e)

    def import_image_file(self):
        def on_selection(sel):
            if sel:
                self._ocr_then_parse(sel[0])
            else:
                self._toast_main("No image selected")
        try:
            from plyer import filechooser
            if ON_ANDROID:
                # Android's picker filters by MIME type, not glob patterns.
                filechooser.open_file(on_selection=on_selection,
                                      filters=["image/*"], mime_type="image/*")
            else:
                filechooser.open_file(
                    on_selection=on_selection,
                    filters=[["Images", "*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp"]])
        except Exception:
            import traceback
            self._show_error("File picker unavailable", traceback.format_exc())

    def import_paste(self):
        field = MDTextField(hint_text="Paste receipt text", multiline=True,
                            mode="rectangle", size_hint_y=None, height=dp(260))
        box = MDBoxLayout(orientation="vertical", adaptive_height=True,
                          padding=dp(8))
        box.add_widget(field)
        dlg = MDDialog(
            title="Paste receipt text", type="custom", content_cls=box,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dlg.dismiss()),
                MDFlatButton(text="IMPORT", on_release=lambda *a: (
                    self._paste_done(field.text), dlg.dismiss())),
            ])
        dlg.open()

    def _paste_done(self, text):
        if text.strip():
            from core.parser import parse_receipt
            self._handle_parsed(parse_receipt(text))

    # ================================================================= LISTS
    def _current_list_name(self):
        for l in self.db.lists():
            if l['id'] == self.current_list_id:
                return l['name']
        return None

    def refresh_lists_ui(self):
        name = self._current_list_name()
        self.root.ids.list_picker.text = name or "No list"
        self.refresh_items_ui()

    def open_list_menu(self):
        lists = self.db.lists()
        if not lists:
            self.new_list()
            return
        items = [{
            "viewclass": "OneLineListItem",
            "text": l['name'],
            "on_release": (lambda lid=l['id']: self._pick_list(lid)),
        } for l in lists]
        self.list_menu = MDDropdownMenu(
            caller=self.root.ids.list_picker, items=items, width_mult=4)
        self.list_menu.open()

    def _pick_list(self, lid):
        self.current_list_id = lid
        if self.list_menu:
            self.list_menu.dismiss()
        self.refresh_lists_ui()

    def refresh_items_ui(self):
        ids = self.root.ids
        ilist = ids.items_list
        ilist.clear_widgets()
        if self.current_list_id is None:
            ids.remaining.text = "Remaining: €0.00"
            return
        remaining = 0.0
        for r in self.db.list_items(self.current_list_id):
            name = ("[s]%s[/s]" % r['name']) if r['checked'] else r['name']
            ilist.add_widget(ItemRow(
                item_id=r['id'], name=name, price=r['price'], checked=r['checked']))
            if not r['checked']:
                remaining += r['price']
        ids.remaining.text = "Remaining: €%.2f" % remaining

    def toggle_item(self, row, active):
        # Avoid feedback loop: only act when state actually changed.
        if bool(row.checked) == bool(active):
            return
        self.db.set_checked(row.item_id, active)
        self.refresh_items_ui()

    def remove_item(self, item_id):
        self.db.remove_item(item_id)
        self.refresh_items_ui()

    def add_manual_item(self):
        if self.current_list_id is None:
            self.toast("Create or select a list first")
            return
        ids = self.root.ids
        name = ids.item_name.text.strip()
        if not name:
            return
        try:
            price = float(ids.item_price.text) if ids.item_price.text.strip() else 0.0
        except ValueError:
            price = 0.0
        self.db.add_item(self.current_list_id, name, price)
        ids.item_name.text = ""
        ids.item_price.text = ""
        self.refresh_items_ui()

    def clear_ticked(self):
        if self.current_list_id is None:
            return
        self.db.clear_checked(self.current_list_id)
        self.refresh_items_ui()

    # ----- list create / rename / delete via text dialog -----
    def _text_dialog(self, title, initial, on_ok):
        field = MDTextField(text=initial, mode="rectangle")
        box = MDBoxLayout(orientation="vertical", adaptive_height=True,
                          padding=dp(8))
        box.add_widget(field)
        dlg = MDDialog(
            title=title, type="custom", content_cls=box,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dlg.dismiss()),
                MDFlatButton(text="OK", on_release=lambda *a: (
                    on_ok(field.text.strip()), dlg.dismiss())),
            ])
        dlg.open()

    def new_list(self):
        def create(name):
            if name:
                self.current_list_id = self.db.create_list(name)
                self.refresh_lists_ui()
        self._text_dialog("New list", "", create)

    def rename_list(self):
        if self.current_list_id is None:
            return
        def rename(name):
            if name:
                self.db.rename_list(self.current_list_id, name)
                self.refresh_lists_ui()
        self._text_dialog("Rename list", self._current_list_name() or "", rename)

    def delete_list(self):
        if self.current_list_id is None:
            return
        name = self._current_list_name()
        dlg = MDDialog(
            title="Delete list",
            text="Delete '%s' and all its items?" % name,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *a: dlg.dismiss()),
                MDFlatButton(text="DELETE", on_release=lambda *a: (
                    self._do_delete_list(), dlg.dismiss())),
            ])
        dlg.open()

    def _do_delete_list(self):
        self.db.delete_list(self.current_list_id)
        remaining = self.db.lists()
        self.current_list_id = remaining[0]['id'] if remaining else None
        self.refresh_lists_ui()


if __name__ == "__main__":
    ReceiptApp().run()
