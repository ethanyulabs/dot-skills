# Looking at compare.jpg

Open `compare.jpg` and `focus.jpg` with the Read tool. `compare.jpg`: top row whole image before | after; second row the focus region scaled to fit (the label gives the zoom); third row (when exports were made) each export with the face box and the dating safe area in yellow. `focus.jpg`: the focus region at true 1:1, before | after. Fine detail (pores, hair, halos, inpaint marks) is judged on `focus.jpg`; composition, color and crops on `compare.jpg`. Write down one conclusion per line below; "fine" is a conclusion.

## Any action

- Overall brightness and contrast: did the after image go flat or harsh?
- Color cast: neutral areas (walls, concrete, white clothing) still neutral? Skin orange, gray or magenta?
- Clipping: white areas with no detail, black areas that became solid?
- Banding: visible steps in smooth gradients (sky, backgrounds, bokeh)?

## Portrait (`focus.jpg`, then the second row)

- Pores, fine hair, eyebrows, eyelashes still sharp? Smooth like wax or plastic = too strong.
- Edges of the face, nose, lips and hairline still crisp, no smearing into the background?
- Spots that were supposed to go are gone; moles that were supposed to stay are there; no patch marks or repeated texture where spots were inpainted?
- Eyes: slightly crisper, not crunchy or haloed?
- Background: any softening outside the skin (a sign the mask leaked)?
- Verdict → keep / `--skin-strength` −0.15 / +0.10 / `--blemish off` / ask the user.

## Landscape (`focus.jpg` = horizon band at 1:1)

- A bright rim along ridges or the skyline (halo)? → lower `--clahe` or `--far-clarity`.
- Sky: smooth gradient kept, not banded, not a gray lid? → lower `--sky-darken` or `--sky off`.
- Foreground texture visible without crunchy edges? Greens natural, not neon?
- Shadows: open enough to read, not blocked after the black point?
- Verdict → keep / named option change / ask.

## Exports (third row)

- Print: subject inside the frame, nothing important lost to the crop (`crop_box_in_source` says what was kept); orientation matches; `upscale` above 1.5 means a soft print, say so.
- Web: not visibly softer than the processed image.
- Dating: whole face box inside the yellow safe area, eyes around the upper third, no chin cut by the crop; hair the original already cut is not a crop fault but gets a sentence in the report; the look natural (no visible filter).
