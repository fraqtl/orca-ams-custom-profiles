"""Offline test of ams_custom_profiles: a fake `orca` module plus sample AMS data from a P2S.

Run with any Python 3.10+ (no printer or Orca needed):  python tests/test_offline.py
"""
import importlib.util
import json
import os
import sys
import threading
import time
import types

PLUGIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ams_custom_profiles", "ams_custom_profiles.py")
USER = "C:/Users/me/AppData/Roaming/OrcaSlicer/user/123/filament/%s.json"

# One AMS as a P2S reports it: two Bambu RFID spools, two untagged spools set by hand.
SAMPLE_AMS = [{"id": "0", "tray": [
    {"id": "0", "tray_type": "PLA", "tray_sub_brands": "PLA Matte", "tray_info_idx": "GFA01",
     "tray_id_name": "A01-K1", "tray_color": "000000FF"},
    {"id": "1", "tray_type": "PETG", "tray_sub_brands": "PETG HF", "tray_info_idx": "GFG02",
     "tray_id_name": "G02-D0", "tray_color": "ADB1B2FF"},
    {"id": "2", "tray_type": "PLA", "tray_sub_brands": "", "tray_info_idx": "P52d4b51",
     "tray_id_name": "", "tray_color": "808080FF"},
    {"id": "3", "tray_type": "PLA", "tray_sub_brands": "", "tray_info_idx": "P52d4b51",
     "tray_id_name": "", "tray_color": "808080FF"},
]}]

presets = {  # name -> (filament_id, is user preset)
    "Bambu PLA Matte @BBL P2S": ("GFA01", False),
    "Bambu PLA Matte 0.4 Charcoal": ("GFA01", True),
    "Bambu PLA Matte 0.4 Caramel": ("GFA01", True),
    "Bambu PETG-HF 0.4mm Light Grey": ("GFG02", True),
    "Bambu PETG-HF 0.4mm Black": ("GFG02", True),
    "Filaform PLA Basic 0.4 Pebble Grey": ("P52d4b51", True),
}


class P:
    def __init__(self, name):
        self.name, self.is_compatible = name, True
        self.file = USER % name if presets[name][1] else "C:/Program Files/OrcaSlicer/resources/profiles/BBL/x.json"

    def config_value(self, key):
        return [presets[self.name][0]] if key == "filament_id" else None


class Coll:
    def __init__(self):
        self.items = [P(n) for n in presets]

    def size(self):
        return len(self.items)

    def preset(self, i):
        return self.items[i]

    def find_preset(self, name):
        return next((p for p in self.items if p.name == name), None)


slots = ["Bambu PLA Matte @BBL P2S", "Bambu PETG HF @BBL P2S 0.4 nozzle", "Generic PLA", "Generic PLA"]
calls, dialogs, answers, messages = [], [], [], []
stored = {"cfg": "{}"}
printer_answer = {"printer_ip": " 10.0.0.9 ", "printer_serial": "SER123", "access_code": " testcode "}


class Bundle:
    filaments = Coll()

    def current_filament_preset_names(self):
        return list(slots)


class Tx:
    def __init__(self, slot, name):
        self.slot, self.name = slot, name

    def commit(self):
        calls.append((self.slot, self.name))
        slots[self.slot - 1] = self.name


class Win:
    def is_open(self):
        return False

    def close(self):
        pass


def create_window(html, title, on_submit, on_close, style=None, width=None, height=None):
    assert style == "MODAL" and width and height
    def reply():  # answer from another thread, like the UI thread would
        time.sleep(0.02)
        if "Printer connection" in html:
            dialogs.append("printer")
            on_submit(dict(printer_answer) if printer_answer else None)
        else:
            dialogs.append(html)
            on_submit({"preset": answers.pop(0)})
    threading.Thread(target=reply).start()
    return Win()


orca = types.ModuleType("orca")
orca.plugin = lambda c: c
orca.base = object
orca.register_capability = lambda c: None
orca.ExecutionResult = types.SimpleNamespace(success=lambda m: ("ok", m))
orca.script = types.SimpleNamespace(ScriptPluginCapabilityBase=object)
orca.host = types.SimpleNamespace(
    preset_bundle=lambda: Bundle(),
    preset=types.SimpleNamespace(filament=types.SimpleNamespace(begin_update=lambda slot, preset_name: Tx(slot, preset_name))),
    ui=types.SimpleNamespace(create_window=create_window, WINDOW_MODAL="MODAL",
                             message=lambda text, **k: messages.append(text) or "ok"))
sys.modules["orca"] = orca

spec = importlib.util.spec_from_file_location("plugin", PLUGIN)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

units = SAMPLE_AMS
seen = []
mod.read_ams = lambda ip, serial, code: seen.append((ip, serial, code)) or units


def run_on_worker(fn):  # Orca runs execute() on a Script worker thread, not the main thread
    out = {}
    t = threading.Thread(target=lambda: out.update(r=fn()))
    t.start(); t.join()
    return out["r"]


cap = mod.ApplyCustomProfiles()
cap.get_config = lambda: stored["cfg"]
cap.save_config = lambda s: stored.update(cfg=s) or True
_execute = cap.execute
cap.execute = lambda: run_on_worker(_execute)
cfg = lambda: json.loads(stored["cfg"])

# Run 1: fresh install -> printer setup window, then one question per new RFID colour.
answers[:] = ["Bambu PLA Matte 0.4 Charcoal", "Bambu PETG-HF 0.4mm Light Grey"]
print("RUN 1:", cap.execute()[1])
assert dialogs[0] == "printer" and len(dialogs) == 3, dialogs
assert seen[0] == ("10.0.0.9", "SER123", "testcode"), seen[0]
assert [c[0] for c in calls] == [1, 2] and slots[2:] == ["Generic PLA", "Generic PLA"], calls
print("  candidates for GFA01:", mod.candidate_presets("GFA01"))

# Run 2: new project with stock profiles -> no dialogs, tagged slots set from links.
slots[:] = ["Bambu PLA Matte @BBL P2S", "Bambu PETG HF @BBL P2S 0.4 nozzle", "Filaform PLA Basic 0.4 Pebble Grey", "Generic PLA"]
calls.clear(); dialogs.clear()
print("RUN 2:", cap.execute()[1])
assert not dialogs and len(calls) == 2 and slots[2:] == ["Filaform PLA Basic 0.4 Pebble Grey", "Generic PLA"]

# Run 3: already applied -> nothing changes.
calls.clear()
print("RUN 3:", cap.execute()[1])
assert not calls

# Run 4: project with only 2 filament slots.
slots[:] = ["Bambu PLA Matte @BBL P2S", "Generic PLA"]
calls.clear()
print("RUN 4:", cap.execute()[1])

# Run 5: two AMS units -> a note is shown.
two = [units[0], {"id": "1", "tray": units[0]["tray"]}]
mod.read_ams = lambda ip, serial, code: two
slots[:] = ["x"] * 8
print("RUN 5:", cap.execute()[1].splitlines()[0])
assert "2 AMS units" in messages[-1]

# Run 6: printer off -> details kept.
def off(ip, serial, code):
    raise TimeoutError("timed out")
mod.read_ams = off
print("RUN 6:", cap.execute()[1])
assert cfg()["access_code"] == "testcode"

# Run 7: login refused -> code cleared (links kept); the next run asks again with IP/serial pre-filled.
def refuse(ip, serial, code):
    raise mod.PrinterDetailsWrong("the printer refused the connection (code 5).")
mod.read_ams = refuse
print("RUN 7:", cap.execute()[1])
assert cfg()["access_code"] == "" and cfg()["printer_ip"] == "10.0.0.9" and cfg()["links"]

# Run 8: setup cancelled -> stops cleanly.
printer_answer = None
dialogs.clear()
print("RUN 8:", cap.execute()[1])
assert dialogs == ["printer"]
print("ALL OK")
