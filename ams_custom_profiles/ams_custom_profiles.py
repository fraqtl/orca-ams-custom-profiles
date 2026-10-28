# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.orcaslicer.plugin]
# name = "AMS Custom Profiles"
# description = "Reads the AMS spools from a Bambu printer over the local network and puts your own custom filament profile in each RFID-tagged slot. Asks once for any spool colour it has not seen, then remembers it. Provided as-is; written with AI assistance."
# author = "fraqtl (written with Claude, Anthropic's AI)"
# version = "0.3.0"
# ///
"""Match each AMS spool to a custom filament profile.

Bambu RFID spools report a colour code (tray_id_name, e.g. A01-K1), so one link covers every
spool of that colour. Untagged spools are left alone. Links and printer details live in this
capability's config, editable in the Plugins dialog.

Assumes Orca's filament slot N is AMS tray N (true after "Sync AMS").
"""
import html
import json
import os
import socket
import ssl
import struct
import threading
import time

import orca

MQTT_PORT = 8883
TIMEOUT_S = 15
TITLE = "AMS Custom Profiles"


class PrinterDetailsWrong(Exception):
    """The printer refused the login or sent nothing for this serial: ask for details again."""


# --- printer connection (minimal MQTT 3.1.1 over TLS, stdlib only) ---------------------------

def _str(s):
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _packet(first_byte, body):
    n, length = len(body), bytearray()
    while True:
        byte, n = n % 128, n // 128
        length.append(byte | (0x80 if n else 0))
        if not n:
            break
    return bytes([first_byte]) + bytes(length) + body


def _read_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("the printer closed the connection")
        buf += chunk
    return buf


def _read_packet(sock):
    first = _read_exact(sock, 1)[0]
    mult, length = 1, 0
    while True:
        b = _read_exact(sock, 1)[0]
        length += (b & 0x7F) * mult
        if not b & 0x80:
            break
        mult *= 128
    return first, _read_exact(sock, length)


def read_ams(ip, serial, access_code):
    """Return the printer's AMS units: a list of {"id": ..., "tray": [tray dicts in slot order]}."""
    # The printer's certificate is self-signed, so skip verification. A bare context also avoids
    # loading the system CA files, which Orca's plugin sandbox blocks.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with ctx.wrap_socket(socket.create_connection((ip, MQTT_PORT), timeout=TIMEOUT_S)) as sock:
        body = _str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
        body += _str("orca-ams-custom-%d" % os.getpid()) + _str("bblp") + _str(access_code)
        sock.sendall(_packet(0x10, body))
        first, ack = _read_packet(sock)
        if first != 0x20 or ack[1] != 0:
            raise PrinterDetailsWrong(
                "the printer refused the connection (code %d). Check the access code and serial "
                "number. Some printers or firmware only allow local connections with LAN-only mode "
                "or Developer Mode turned on." % ack[1])

        sock.sendall(_packet(0x82, struct.pack("!H", 1) + _str("device/%s/report" % serial) + b"\x00"))
        pushall = json.dumps({"pushing": {"sequence_id": "1", "command": "pushall"}}).encode()
        sock.sendall(_packet(0x30, _str("device/%s/request" % serial) + pushall))

        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            first, body = _read_packet(sock)
            if first >> 4 != 3:
                continue
            start = 2 + struct.unpack("!H", body[:2])[0] + (2 if (first >> 1) & 3 else 0)
            try:
                ams = json.loads(body[start:]).get("print", {}).get("ams")
            except ValueError:
                continue
            if ams and "ams" in ams:
                return ams["ams"]
    raise PrinterDetailsWrong("connected, but the printer sent no AMS data. Check the serial number.")


# --- dialogs -------------------------------------------------------------------------------

def modal(page, width, height):
    """Show an HTML page as a modal window; return what it passed to orca.submit(), or None."""
    ui, done, result = orca.host.ui, threading.Event(), {}

    def on_submit(data):
        result["data"] = data
        done.set()

    kwargs = dict(html=page, title=TITLE, on_submit=on_submit, on_close=lambda *a: done.set())
    if hasattr(ui, "WINDOW_MODAL"):
        kwargs["style"] = ui.WINDOW_MODAL
    try:
        win = ui.create_window(width=width, height=height, **kwargs)
    except TypeError:  # some builds may not take a size
        win = ui.create_window(**kwargs)
    # execute() runs on the Script worker, so waiting here does not freeze Orca. If it is ever
    # called on the UI thread, waiting would block the very callbacks we wait for, so don't.
    if threading.current_thread() is not threading.main_thread():
        done.wait(600)
    try:
        if win.is_open():
            win.close()
    except Exception:
        pass
    return result.get("data")


def ask_for_printer(cfg):
    """Ask for the printer's IP, serial and access code (Orca does not let plugins read its own
    settings file). Returns the updated fields, or None if cancelled."""
    def field(key, label, kind="text"):
        return ('<p>%s<br><input id="%s" type="%s" value="%s" style="width:100%%;padding:4px"></p>'
                % (label, key, kind, html.escape(cfg.get(key, ""), True)))
    page = """<!doctype html><html><body style="font-family:sans-serif;margin:16px">
<p><b>Printer connection</b></p>
<p>All three are on the printer screen: the IP and access code in the network (WLAN/LAN) settings,
the serial number in the device information. They are saved in this plugin's settings
(the access code in plain text, as Orca itself stores it).</p>
%s%s%s
<p style="margin-top:16px">
<button onclick="orca.submit({printer_ip: v('printer_ip'), printer_serial: v('printer_serial'), access_code: v('access_code')})">Save</button>
<button onclick="orca.submit(null)">Cancel</button></p>
<script>function v(id) { return document.getElementById(id).value.trim(); }</script>
</body></html>""" % (field("printer_ip", "IP address"), field("printer_serial", "Serial number"),
                     field("access_code", "Access code", "password"))
    result = modal(page, 460, 420)
    if not result or not all(result.get(k) for k in ("printer_ip", "printer_serial", "access_code")):
        return None
    return {k: result[k].strip() for k in ("printer_ip", "printer_serial", "access_code")}


def ask_for_preset(tray, slot, names):
    """Ask which profile a new spool colour should use. Returns a name, or None to skip."""
    swatch = "#" + tray.get("tray_color", "808080")[:6]
    options = "".join('<option value="%s">%s</option>' % (html.escape(n, True), html.escape(n)) for n in names)
    page = """<!doctype html><html><body style="font-family:sans-serif;margin:16px">
<p><b>New spool in slot %d</b></p>
<p><span style="display:inline-block;width:14px;height:14px;background:%s;border:1px solid #888;vertical-align:middle"></span>
 %s</p>
<p>Which custom profile should this colour use? Every spool with this colour will get it from now on.</p>
<select id="p" style="width:100%%;padding:4px">%s</select>
<p style="margin-top:16px">
<button onclick="orca.submit({preset: document.getElementById('p').value})">Use this profile</button>
<button onclick="orca.submit({preset: ''})">Skip for now</button></p>
</body></html>""" % (slot, swatch, html.escape(tray_label(tray)), options)
    result = modal(page, 460, 300)
    return (result or {}).get("preset") or None


# --- matching ------------------------------------------------------------------------------

def tray_key(tray):
    """Stable key for the spool's colour code, or None if the tray is empty or has no RFID tag.

    Untagged spools are left alone: their profile is whatever was chosen for that AMS slot.
    """
    name = tray.get("tray_id_name", "")
    return "rfid:" + name if tray.get("tray_type") and name else None


def tray_label(tray):
    brand = tray.get("tray_sub_brands") or tray.get("tray_type", "")
    return "%s, colour #%s" % (brand, tray.get("tray_color", "")[:6].upper())


def candidate_presets(material_id):
    """User filament presets compatible with the current printer; ones of this material first."""
    coll = orca.host.preset_bundle().filaments
    compatible = [p for p in (coll.preset(i) for i in range(coll.size())) if getattr(p, "is_compatible", True)]
    user = [p for p in compatible
            if "user" in (getattr(p, "file", "") or "").replace("\\", "/").lower().split("/")]
    same, other = [], []
    for p in user or compatible:  # fall back to every compatible preset if file paths are unavailable
        fid = p.config_value("filament_id")
        fid = fid[0] if isinstance(fid, (list, tuple)) and fid else fid
        (same if fid == material_id else other).append(p.name)
    return sorted(same) + sorted(other)


# --- plugin --------------------------------------------------------------------------------

class ApplyCustomProfiles(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Apply custom AMS profiles"

    def get_default_config(self):
        return {"printer_ip": "", "printer_serial": "", "access_code": "", "links": {}}

    def _config(self):
        cfg = self.get_default_config()
        try:
            cfg.update(json.loads(self.get_config() or "{}"))
        except ValueError:
            pass
        return cfg

    def execute(self):
        cfg = self._config()
        if not all(cfg.get(k) for k in ("printer_ip", "printer_serial", "access_code")):
            printer = ask_for_printer(cfg)
            if not printer:
                return orca.ExecutionResult.success("Cancelled: printer details not entered.")
            cfg.update(printer)
            self.save_config(json.dumps(cfg))
        try:
            units = read_ams(cfg["printer_ip"], cfg["printer_serial"], cfg["access_code"])
        except Exception as e:  # show any connection problem to the user
            msg = str(e).rstrip(".") + "."
            if isinstance(e, PrinterDetailsWrong):
                cfg["access_code"] = ""  # ask for the details again next run (links are kept)
                self.save_config(json.dumps(cfg))
                msg += " Run it again to re-enter the printer details."
            elif isinstance(e, OSError):  # off, asleep or wrong IP: keep the details
                msg += " Check the printer is on and the IP address (%s) is right." % cfg["printer_ip"]
            orca.host.ui.message("Could not read the AMS: %s" % msg, title=TITLE, buttons="ok", icon="error")
            return orca.ExecutionResult.success("AMS not read: %s" % msg)

        trays = [t for unit in units for t in unit.get("tray", [])]
        current = orca.host.preset_bundle().current_filament_preset_names()
        slot_count = len(current)
        links, changed, report = cfg["links"], False, []
        if len(units) > 1:
            report.append("Note: %d AMS units found. Only a single AMS has been tested; slots are "
                          "matched in AMS order." % len(units))

        for i, tray in enumerate(trays[:slot_count]):
            slot, key = i + 1, tray_key(tray)
            if key is None:
                if tray.get("tray_type"):
                    report.append("Slot %d: no RFID tag, left as %s" % (slot, current[i]))
                continue
            target = links.get(key)
            if not target or orca.host.preset_bundle().filaments.find_preset(target) is None:
                target = ask_for_preset(tray, slot, candidate_presets(tray.get("tray_info_idx", "")))
                if not target:
                    report.append("Slot %d: skipped" % slot)
                    continue
                links[key], changed = target, True
            if current[i] == target:
                report.append("Slot %d: %s (already set)" % (slot, target))
                continue
            try:
                orca.host.preset.filament.begin_update(slot, preset_name=target).commit()
                report.append("Slot %d: %s" % (slot, target))
            except (RuntimeError, ValueError) as e:
                report.append("Slot %d: could not set %s (%s)" % (slot, target, e))

        if changed:
            cfg["links"] = links
            self.save_config(json.dumps(cfg))
        if len(trays) > slot_count:
            report.append("(%d AMS slots have no matching filament slot in this project; sync the AMS first)"
                          % (len(trays) - slot_count))
        summary = "\n".join(report) or "Nothing to do: the AMS is empty."
        orca.host.ui.message(summary, title=TITLE, buttons="ok", icon="info")
        return orca.ExecutionResult.success(summary)


@orca.plugin
class AmsCustomProfiles(orca.base):
    def register_capabilities(self):
        # The printer's address is only known from the plugin's settings, which can't be read at
        # registration, so Orca asks for network permission on the first connection instead.
        orca.register_capability(ApplyCustomProfiles)
