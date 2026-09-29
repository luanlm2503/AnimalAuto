# Animal TV Generator

Local web app for arranging animal clips over a background, building deterministic movement timelines, and rendering long-form video with FFmpeg.

## Run

On Windows, install the Python requirements and FFmpeg, then run `run.bat`. The app opens at `http://localhost:8765`.

## Demo animals

`tools/update_demo_animals.py --assets-only` creates a contact sheet and transparent animated PNG sequences (packed as ZIPs) for a bird, lizard, and butterfly. They are temporary procedural illustrations, not real footage or photorealistic animals; replace them with real clips when available. `--apply` updates the existing `demo_th_th_bd83fd` project in place, retaining the mouse and replacing the hamster and ladybug entries after the new illustrations have been installed. Review the generated `tools/demo_assets/illustrations/contact_sheet.jpg` before applying them.

Bird and butterfly flight use the existing `run` clip slot for flapping/fluttering. Flight can be configured per animal in the Motion tab. Old projects retain ground-only movement by default.

## Tests

Run `python -m pytest` from the repository root.
