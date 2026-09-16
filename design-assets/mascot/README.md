# Mascot lime sequence

Confirmed UI mascot. Lime / yellow-green character on a transparent
background. Fill color **#D7FF3F**.

**Blender deliveries are obsolete. Do not use them.**

This folder is the in-repo original. App compile and run must load
playback frames from the iOS bundle only. They must not read
`~/Downloads` or any other path outside this repository.

---

## Source (do not pack into the App)

Copied from the local Downloads originals. Those Downloads files were
not moved or deleted.

| File | Role |
|---|---|
| `source/mascot_lime_transparent_png_sequence.zip` | Confirmed transparent PNG sequence (241 frames: `frame_0000.png` … `frame_0240.png`, 512×512 RGBA) |
| `source/mascot_lime_transparent_prores4444.mov` | Confirmed ProRes 4444 master |

The iOS target does **not** reference these files. They stay in git as
design originals. This repository has no Git LFS pin; both files are
under GitHub’s 100 MB blob limit and follow the same ordinary-git
rule as other small binaries that are not listed in `.gitignore`.

---

## Runtime frames (packed with the App)

`ios/RockVision/Resources/MascotLime/`

| Clip | Packed files | Source frames (4-digit names in the ZIP) | FPS |
|---|---|---|---|
| Run loop | `run/run_00.png` … `run_07.png` (8) | `0029, 0030, 0032, 0033, 0034, 0035, 0037, 0038` looping toward `0039≈0029` | 12 |
| Jump | `jump/jump_00.png` … `jump_22.png` (23) | unique frames `0178` … `0232` (crouch, launch, air, land) | 12 |

The ZIP was authored around 24 fps with held duplicates. Holds were
dropped so footfall cadence stays even at 12 fps. Jump PNGs already
contain vertical body travel; the HUD must not add a second hop.

Loader: `ios/RockVision/Features/ScanLoading/MascotSequence.swift`
(`Bundle` subdirectory `MascotLime/run` and `MascotLime/jump`).

Preview cut points from review sessions are **not** the official clip
ranges above.
