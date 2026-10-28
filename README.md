# AMS Tuned Profiles (OrcaSlicer plugin)

When you sync a Bambu AMS, Orca picks the stock profile for each spool ("Bambu PLA Matte"), even if you have a tuned profile for that exact colour. This plugin fixes that. It reads the spools from the printer and puts your own tuned profile in each RFID-tagged slot.

- **Learns each colour once.** Bambu RFID tags include a colour code (for example `A01-K1`). The first time it sees a colour, it asks which of your profiles to use, then remembers it for every spool of that colour.
- **Leaves untagged spools alone.** Third-party spools without a Bambu tag keep whatever profile you chose for that AMS slot.
- **Local only.** It talks to the printer on your network. No cloud, and no extra Python packages.

## Status: provided as-is

I shared this in the hope it helps. It works on my setup, and that is the only setup it has been tested on:

- **Printer:** Bambu Lab P2S with one AMS
- **Orca:** OrcaSlicer 2.5.0 nightly, built 2026-10-28. It needs the plugin API from [PR #16518](https://github.com/OrcaSlicer/OrcaSlicer/pull/16518), which is not in 2.5.0-alpha.

I'm not offering support. I may update it when a new nightly breaks it for me, but there are no promises. Issues and pull requests may go unanswered.

**Want to take it over?** Go for it. Fork it, rename it, publish it anywhere. Just keep the attribution (see Licence).

## AI disclosure

This plugin was written almost entirely by Claude (Anthropic's AI model, using Claude Code), working with me. I described the problem, made the design decisions, and tested it on my printer. Claude wrote the code and the tests, and worked out the plugin API from the help text inside the nightly build, because the wiki is out of date. Read the code before you trust it with your printer. It is one short file.

## Install

1. Copy the `ams_tuned_profiles` folder into Orca's plugin folder:
   - **Windows:** `%APPDATA%\OrcaSlicer\orca_plugins\`
   - **macOS:** `~/Library/Application Support/OrcaSlicer/orca_plugins/`
   - **Linux:** `~/.config/OrcaSlicer/orca_plugins/`
2. Restart Orca.
3. Open **Preferences > Plugins** and check that **AMS Tuned Profiles** is enabled.

## Use

1. Sync the AMS in the Prepare tab as usual.
2. Open **Preferences > Plugins**, click the arrow next to **AMS Tuned Profiles**, then run **Apply tuned AMS profiles**.
3. **First run only:** enter the printer's IP address, serial number and access code. All three are on the printer screen. Allow the network connection when Orca asks.
4. For each colour it hasn't seen before, choose your tuned profile.
5. A summary shows what it set in each slot.

Your colour-to-profile links are stored in the plugin's settings, under `links`. You can edit or delete them in the Plugins dialog.

## Limitations

- **Slot order:** it assumes Orca's filament slot N is AMS slot N. That's true right after a sync.
- **More than one AMS:** it matches slots in AMS order, but this is untested.
- **Not handled:** AMS HT, the external spool, and dual-nozzle printers (H2D).
- **Local connection:** some printers or firmware versions only allow it with LAN-only mode or Developer Mode turned on. If the printer refuses the login, the plugin says so.
- **Access code:** saved in plain text in the plugin's settings (`orca_plugins/config.json`), the same way Orca stores it. Orca doesn't let plugins read Orca's own copy.
- **Changing API:** the nightly plugin API is new and still changing, so a future nightly may break this.

## Tests

`python tests/test_offline.py` runs the plugin against a fake `orca` module and sample AMS data. You don't need a printer or Orca.

## Related

[OrcaSlicer issue #16961](https://github.com/OrcaSlicer/OrcaSlicer/issues/16961) proposes building this into Orca's own filament sync. That would be the better long-term fix.

## Licence

MIT. See [LICENSE](LICENSE). You can use, change and redistribute it freely, as long as you keep the copyright notice.
