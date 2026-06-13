#!/usr/bin/env python3
"""
Linux Ramdisk Manager — GTK3 (PyGObject)
No pip installation required:
  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0
  Fedora:        sudo dnf install python3-gobject gtk3
  Arch:          sudo pacman -S python-gobject gtk3
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

import json
import locale
import os
import shutil
import subprocess
import threading
from pathlib import Path

CONFIG_DIR  = Path.home() / ".config" / "ramdisk-manager"
CONFIG_FILE = CONFIG_DIR / "config.json"
I18N_DIR    = Path(__file__).parent / "i18n"

DEFAULT_CONFIG = {"lang": "system"}


# ── Config & i18n ─────────────────────────────────────────────────────────────

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def detect_system_lang():
    try:
        loc = locale.getlocale()[0] or ""
    except Exception:
        loc = ""
    if not loc:
        loc = os.environ.get("LANG", "")
    return "de" if loc.lower().startswith("de") else "en"


def resolve_lang(setting):
    if setting == "system":
        return detect_system_lang()
    return setting


def load_i18n(lang):
    en = {}
    en_path = I18N_DIR / "en.json"
    if en_path.exists():
        with open(en_path) as f:
            en = json.load(f)
    if lang == "en":
        return en
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        return en
    with open(path) as f:
        strings = json.load(f)
    for k, v in en.items():
        strings.setdefault(k, v)
    return strings


def t(strings, key, **kwargs):
    s = strings.get(key, key)
    for k, v in kwargs.items():
        s = s.replace("{" + k + "}", str(v))
    return s


# ── MenuButton helper ─────────────────────────────────────────────────────────

def make_menu_button(items, on_select, min_width=150):
    btn = Gtk.MenuButton()
    btn.set_size_request(min_width, -1)
    lbl = Gtk.Label(label=items[0] if items else "")
    btn.add(lbl)
    menu = Gtk.Menu()

    def build_menu(items, current=None):
        for child in menu.get_children():
            menu.remove(child)
        group = []
        active = current if current in items else (items[0] if items else None)
        for text in items:
            item = Gtk.RadioMenuItem.new_with_label(group, text)
            group = item.get_group()
            if text == active:
                item.set_active(True)
            def _on_activate(i, tx=text):
                if i.get_active():
                    lbl.set_text(tx)
                    on_select(tx)
            item.connect("activate", _on_activate)
            menu.append(item)
        menu.show_all()
        if active:
            lbl.set_text(active)

    build_menu(items)
    btn.set_popup(menu)

    def update(new_items, current=None):
        build_menu(new_items, current)

    return btn, lbl, update


# ── Helper functions ──────────────────────────────────────────────────────────

def run_cmd(cmd, use_sudo=False, timeout_msg="Timeout"):
    if use_sudo:
        cmd = ["sudo"] + cmd
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, timeout_msg
    except FileNotFoundError as e:
        return False, str(e)


def get_ramdisks():
    disks = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "tmpfs":
                    mp = parts[1]
                    try:
                        total, used, free = shutil.disk_usage(mp)
                        pct = (used / total * 100) if total > 0 else 0
                        disks.append({
                            "mountpoint": mp,
                            "label":      Path(mp).name or mp,
                            "total_mb":   total / 1024 / 1024,
                            "used_mb":    used  / 1024 / 1024,
                            "free_mb":    free  / 1024 / 1024,
                            "percent":    pct,
                            "options":    parts[3],
                        })
                    except OSError:
                        disks.append({
                            "mountpoint": mp, "label": Path(mp).name or mp,
                            "total_mb": 0, "used_mb": 0, "free_mb": 0,
                            "percent": 0, "options": parts[3],
                        })
    except OSError:
        pass
    return disks


def fmt(mb):
    return f"{mb/1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def msg(strings, parent, kind, title_key, text):
    icons = {
        "error":    Gtk.MessageType.ERROR,
        "question": Gtk.MessageType.QUESTION,
        "info":     Gtk.MessageType.INFO,
    }
    btns = Gtk.ButtonsType.YES_NO if kind == "question" else Gtk.ButtonsType.OK
    d = Gtk.MessageDialog(
        transient_for=parent, modal=True,
        message_type=icons.get(kind, Gtk.MessageType.INFO),
        buttons=btns,
        text=t(strings, title_key),
    )
    d.format_secondary_text(text)
    resp = d.run()
    d.destroy()
    return resp == Gtk.ResponseType.YES


# ── Dialog: Create ramdisk ────────────────────────────────────────────────────

class CreateDialog(Gtk.Dialog):
    def __init__(self, parent, strings):
        super().__init__(title=t(strings, "dlg_create_title"),
                         transient_for=parent, modal=True)
        self.strings = strings
        self.set_default_size(400, -1)
        self.add_buttons(t(strings, "btn_cancel"), Gtk.ResponseType.CANCEL,
                         t(strings, "btn_create"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=10, row_spacing=10,
                        margin_top=16, margin_bottom=16,
                        margin_start=16, margin_end=16)
        self.get_content_area().add(grid)

        def lbl(k): return Gtk.Label(label=t(strings, k), xalign=1)

        # Mountpoint
        grid.attach(lbl("lbl_mountpoint"), 0, 0, 1, 1)
        mp_box = Gtk.Box(spacing=4)
        self.mp_entry = Gtk.Entry(text="/mnt/ramdisk", hexpand=True)
        browse_btn = Gtk.Button(label="…")
        browse_btn.connect("clicked", self._browse)
        mp_box.pack_start(self.mp_entry, True, True, 0)
        mp_box.pack_start(browse_btn, False, False, 0)
        grid.attach(mp_box, 1, 0, 1, 1)

        # Size
        grid.attach(lbl("lbl_size"), 0, 1, 1, 1)
        size_box = Gtk.Box(spacing=4)
        self.size_spin = Gtk.SpinButton.new_with_range(1, 65536, 1)
        self.size_spin.set_value(512)
        self._unit_current = "MB"
        self.unit_btn, _, _ = make_menu_button(
            ["MB", "GB"],
            lambda u: setattr(self, "_unit_current", u),
            min_width=70,
        )
        size_box.pack_start(self.size_spin, True, True, 0)
        size_box.pack_start(self.unit_btn, False, False, 0)
        grid.attach(size_box, 1, 1, 1, 1)

        # Permissions
        grid.attach(lbl("lbl_permissions"), 0, 2, 1, 1)
        self.perms_entry = Gtk.Entry(text="1777")
        grid.attach(self.perms_entry, 1, 2, 1, 1)

        # Note
        note = Gtk.Label(label=t(strings, "note_sudo"), xalign=0)
        note.get_style_context().add_class("dim-label")
        grid.attach(note, 0, 3, 2, 1)

        self.show_all()

    def _browse(self, _):
        d = Gtk.FileChooserDialog(
            title=t(self.strings, "dlg_pick_dir"),
            transient_for=self, modal=True,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(t(self.strings, "btn_cancel"), Gtk.ResponseType.CANCEL,
                      t(self.strings, "btn_choose"), Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.mp_entry.set_text(d.get_filename())
        d.destroy()

    def get_values(self):
        size = int(self.size_spin.get_value())
        return {
            "mountpoint": self.mp_entry.get_text().strip(),
            "size":       f"{size}{'m' if self._unit_current == 'MB' else 'g'}",
            "mode":       self.perms_entry.get_text().strip(),
        }


# ── Main window ───────────────────────────────────────────────────────────────

class RamdiskWindow(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_default_size(950, 480)
        self._disks = []

        self.cfg = load_config()
        self.strings = load_i18n(resolve_lang(self.cfg.get("lang", "system")))
        s = self.strings

        self.set_title(t(s, "app_title"))

        # HeaderBar
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = t(s, "app_title")
        self.set_titlebar(header)

        self._lang_options = [("de", "lang_de"), ("en", "lang_en"),
                               ("system", "lang_system")]
        self.lang_menu_btn = Gtk.MenuButton()
        self.lang_menu_btn.set_size_request(130, -1)
        self._lang_label = Gtk.Label()
        self.lang_menu_btn.add(self._lang_label)
        lang_menu = Gtk.Menu()
        group = []
        current_lang = self.cfg.get("lang", "system")
        for code, key in self._lang_options:
            item = Gtk.RadioMenuItem.new_with_label(group, t(s, key))
            group = item.get_group()
            if code == current_lang:
                item.set_active(True)
                self._lang_label.set_text(t(s, key))
            item.connect("activate", self._on_lang_menu_item, code)
            lang_menu.append(item)
        lang_menu.show_all()
        self.lang_menu_btn.set_popup(lang_menu)
        header.pack_end(self.lang_menu_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        self.add(vbox)

        # Toolbar
        self._toolbar = Gtk.Box(spacing=6)
        for key, cb in [
            ("btn_create_action", self._create),
            ("btn_umount",        self._umount),
            ("btn_delete",        self._delete),
            ("btn_clear",         self._clear),
            ("btn_resize",        self._resize),
            ("btn_refresh",       self._refresh),
            ("btn_copy_to",       self._copy_to),
            ("btn_copy_from",     self._copy_from),
        ]:
            btn = Gtk.Button(label=t(s, key))
            btn.connect("clicked", lambda _, f=cb: f())
            self._toolbar.pack_start(btn, False, False, 0)
        vbox.pack_start(self._toolbar, False, False, 0)

        # ListStore: mountpoint, label, total, used, free, pct(int), options, pct_str
        self.store = Gtk.ListStore(str, str, str, str, str, int, str, str)
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(True)
        self.tv.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        for key, idx, expand in [
            ("col_mountpoint", 0, True),
            ("col_label",      1, False),
            ("col_total",      2, False),
            ("col_used",       3, False),
            ("col_free",       4, False),
        ]:
            r = Gtk.CellRendererText()
            r.set_property("ellipsize", Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(t(s, key), r, text=idx)
            c.set_expand(expand)
            c.set_resizable(True)
            self.tv.append_column(c)

        # Usage progress bar column
        r_pct = Gtk.CellRendererProgress()
        c_pct = Gtk.TreeViewColumn(t(s, "col_usage"), r_pct, value=5, text=7)
        c_pct.set_min_width(130)
        self.tv.append_column(c_pct)

        # Options column
        r_opt = Gtk.CellRendererText()
        r_opt.set_property("ellipsize", Pango.EllipsizeMode.END)
        c_opt = Gtk.TreeViewColumn(t(s, "col_options"), r_opt, text=6)
        c_opt.set_expand(True)
        self.tv.append_column(c_opt)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.tv)
        vbox.pack_start(scroll, True, True, 0)

        self.statusbar = Gtk.Statusbar()
        self.ctx = self.statusbar.get_context_id("main")
        vbox.pack_start(self.statusbar, False, False, 0)

        self._refresh()
        GLib.timeout_add_seconds(5, self._auto_refresh)

    # ── Internal methods ──────────────────────────────────────────────────────

    def _set_status(self, text):
        self.statusbar.pop(self.ctx)
        self.statusbar.push(self.ctx, text)

    def _refresh(self):
        s = self.strings
        self._disks = get_ramdisks()
        self.store.clear()
        for d in self._disks:
            pct = int(d["percent"])
            self.store.append([
                d["mountpoint"], d["label"],
                fmt(d["total_mb"]), fmt(d["used_mb"]), fmt(d["free_mb"]),
                pct, d["options"][:60], f"{pct}%",
            ])
        self._set_status(t(s, "status_mounts", n=len(self._disks)))

    def _auto_refresh(self):
        self._refresh()
        return True

    def _selected(self):
        s = self.strings
        model, it = self.tv.get_selection().get_selected()
        if it is None:
            msg(s, self, "error", "no_selection", t(s, "err_no_selection"))
            return None
        idx = model.get_path(it).get_indices()[0]
        return self._disks[idx]

    def _create(self):
        s = self.strings
        dlg = CreateDialog(self, s)
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            v = dlg.get_values()
            mp = v["mountpoint"]
            dlg.destroy()
            if not os.path.exists(mp):
                ok, err = run_cmd(["mkdir", "-p", mp], use_sudo=True)
                if not ok:
                    msg(s, self, "error", "error",
                        t(s, "err_mkdir", err=err)); return
            ok, err = run_cmd(
                ["mount", "-t", "tmpfs", "-o",
                 f"size={v['size']},mode={v['mode']}", "tmpfs", mp],
                use_sudo=True)
            if ok:
                self._set_status(t(s, "status_created", mp=mp))
                self._refresh()
            else:
                msg(s, self, "error", "err_mount_failed", err)
        else:
            dlg.destroy()

    def _umount(self):
        s = self.strings
        d = self._selected()
        if not d: return
        if not msg(s, self, "question", "confirm",
                   t(s, "confirm_umount", mp=d["mountpoint"])): return
        ok, err = run_cmd(["umount", d["mountpoint"]], use_sudo=True)
        if ok:
            self._set_status(t(s, "status_umounted", mp=d["mountpoint"]))
            self._refresh()
        else:
            msg(s, self, "error", "err_umount_failed", err)

    def _delete(self):
        s = self.strings
        d = self._selected()
        if not d: return
        if not msg(s, self, "question", "confirm",
                   t(s, "confirm_delete", mp=d["mountpoint"])): return
        ok, err = run_cmd(["umount", d["mountpoint"]], use_sudo=True)
        if not ok:
            msg(s, self, "error", "err_umount_failed", err); return
        ok, err = run_cmd(["rmdir", d["mountpoint"]], use_sudo=True)
        if ok:
            self._set_status(t(s, "status_deleted"))
        else:
            self._set_status(t(s, "status_umounted_only", err=err))
        self._refresh()

    def _clear(self):
        s = self.strings
        d = self._selected()
        if not d: return
        mp = d["mountpoint"]
        if not msg(s, self, "question", "confirm",
                   t(s, "confirm_clear", mp=mp)): return
        ok, err = run_cmd(["find", mp, "-mindepth", "1", "-delete"])
        if ok:
            self._set_status(t(s, "status_cleared", mp=mp))
            self._refresh()
        else:
            msg(s, self, "error", "err_clear_failed", err)

    def _resize(self):
        s = self.strings
        d = self._selected()
        if not d: return

        dlg = Gtk.Dialog(title=t(s, "dlg_resize_title"),
                         transient_for=self, modal=True)
        dlg.set_default_size(320, -1)
        dlg.add_buttons(t(s, "btn_cancel"), Gtk.ResponseType.CANCEL,
                        t(s, "btn_apply"),  Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)

        box = Gtk.Box(spacing=8, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        dlg.get_content_area().add(box)
        box.pack_start(Gtk.Label(label=t(s, "lbl_new_size")), False, False, 0)
        spin = Gtk.SpinButton.new_with_range(1, 65536, 1)
        spin.set_value(max(1, int(d["total_mb"])))
        box.pack_start(spin, True, True, 0)

        _unit = ["MB"]
        unit_btn, _, _ = make_menu_button(
            ["MB", "GB"], lambda u: _unit.__setitem__(0, u), min_width=70)
        box.pack_start(unit_btn, False, False, 0)
        dlg.show_all()

        if dlg.run() == Gtk.ResponseType.OK:
            size   = int(spin.get_value())
            suffix = "m" if _unit[0] == "MB" else "g"
            dlg.destroy()
            ok, err = run_cmd(
                ["mount", "-o", f"remount,size={size}{suffix}",
                 d["mountpoint"]], use_sudo=True)
            if ok:
                self._set_status(
                    t(s, "status_resized", mp=d["mountpoint"],
                      size=size, unit=_unit[0]))
                self._refresh()
            else:
                msg(s, self, "error", "err_remount_failed", err)
        else:
            dlg.destroy()

    # ── rsync helpers ─────────────────────────────────────────────────────────

    def _run_rsync_threaded(self, src, dst, label):
        s = self.strings
        self._set_toolbar_sensitive(False)
        self._set_status(t(s, "status_transfer_started", label=label))

        self._rsync_dlg = self._make_progress_dialog(label)
        self._rsync_dlg.show_all()

        def worker():
            cmd = ["rsync", "-rav", "--partial", "--append", "--progress",
                   "--out-format=%n", src + "/", dst + "/"]
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                self._rsync_proc = proc
                lines = []
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        lines.append(line)
                        GLib.idle_add(self._rsync_update, line)
                proc.wait()
                ok  = proc.returncode == 0
                err = "" if ok else "\n".join(lines[-10:])
            except Exception as e:
                ok, err = False, str(e)
            GLib.idle_add(self._rsync_done, ok, err, label)

        threading.Thread(target=worker, daemon=True).start()

    def _make_progress_dialog(self, label):
        s = self.strings
        dlg = Gtk.Window(title=t(s, "dlg_transfer_title"))
        dlg.set_transient_for(self)
        dlg.set_default_size(600, 340)
        dlg.set_deletable(False)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       margin_top=10, margin_bottom=10,
                       margin_start=10, margin_end=10)
        dlg.add(vbox)
        vbox.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)

        self._rsync_buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self._rsync_buf)
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.set_wrap_mode(Gtk.WrapMode.CHAR)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tv)
        self._rsync_tv = tv
        vbox.pack_start(sw, True, True, 0)

        self._rsync_pbar = Gtk.ProgressBar()
        self._rsync_pbar.set_pulse_step(0.04)
        vbox.pack_start(self._rsync_pbar, False, False, 0)

        self._rsync_pulse_timer = GLib.timeout_add(100, self._pulse_pbar)
        return dlg

    def _pulse_pbar(self):
        self._rsync_pbar.pulse()
        return True

    def _rsync_update(self, line):
        end = self._rsync_buf.get_end_iter()
        self._rsync_buf.insert(end, line + "\n")
        adj = self._rsync_tv.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _rsync_done(self, ok, err, label):
        if hasattr(self, "_rsync_pulse_timer"):
            GLib.source_remove(self._rsync_pulse_timer)
        if hasattr(self, "_rsync_dlg") and self._rsync_dlg:
            self._rsync_dlg.destroy()
            self._rsync_dlg = None
        self._set_toolbar_sensitive(True)
        s = self.strings
        if ok:
            self._set_status(f"✓ {label}")
            self._refresh()
        else:
            self._set_status(t(s, "status_transfer_failed"))
            msg(s, self, "error", "err_rsync_failed", err)

    def _set_toolbar_sensitive(self, sensitive):
        for btn in self._toolbar.get_children():
            btn.set_sensitive(sensitive)

    def _copy_to(self):
        s = self.strings
        d = self._selected()
        if not d: return
        fc = Gtk.FileChooserDialog(
            title=t(s, "dlg_pick_src"), transient_for=self, modal=True,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        fc.add_buttons(t(s, "btn_cancel"), Gtk.ResponseType.CANCEL,
                       t(s, "btn_copy"),   Gtk.ResponseType.OK)
        if fc.run() == Gtk.ResponseType.OK:
            src = fc.get_filename()
            fc.destroy()
            self._run_rsync_threaded(
                src, d["mountpoint"], f"{src} → {d['mountpoint']}")
        else:
            fc.destroy()

    def _copy_from(self):
        s = self.strings
        d = self._selected()
        if not d: return
        fc = Gtk.FileChooserDialog(
            title=t(s, "dlg_pick_dst"), transient_for=self, modal=True,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        fc.add_buttons(t(s, "btn_cancel"), Gtk.ResponseType.CANCEL,
                       t(s, "btn_backup"), Gtk.ResponseType.OK)
        if fc.run() == Gtk.ResponseType.OK:
            dst = fc.get_filename()
            fc.destroy()
            self._run_rsync_threaded(
                d["mountpoint"], dst, f"{d['mountpoint']} → {dst}")
        else:
            fc.destroy()

    def _on_lang_menu_item(self, item, code):
        if not item.get_active():
            return
        if code == self.cfg.get("lang"):
            return
        self.cfg["lang"] = code
        save_config(self.cfg)
        for c, key in self._lang_options:
            if c == code:
                self._lang_label.set_text(t(self.strings, key))
                break
        new_strings = load_i18n(resolve_lang(code))
        dlg = Gtk.MessageDialog(
            transient_for=self, flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=t(new_strings, "restart_hint"),
        )
        dlg.run()
        dlg.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    win = RamdiskWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
