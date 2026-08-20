# Editing an existing cover

Read this reference only when the user wants to modify an existing finished image. The source image is the edit target, not merely a style reference.

## Preserve before changing

List the exact requested edit region and the invariants outside it. Change only that region. Preserve every other area: composition, text, punctuation, numbers, logos, colors, lines, objects, positions, texture, and fine detail.

Do not regenerate the entire image to make a local edit. Prefer deterministic canvas operations, direct compositing, or a tightly masked edit. If the available tool cannot honor a pixel-level preservation requirement, state that limitation instead of pretending it can.

## Adapt to 3:4 without destructive cropping

Inspect the source dimensions before editing.

- If the source is narrower and taller than 3:4, extend the canvas to the left and right.
- If the source is wider than 3:4, extend the canvas to the top and bottom.
- Continue the existing background, texture, lighting, perspective, grain, and illustration style into the new area.
- Do not crop, enlarge, move, or distort the subject merely to fill the canvas unless the user explicitly requests it.
- Do not cut off titles, people, products, logos, signatures, or bottom credits.

When the existing content already violates the safe area, preserve it unless the user authorizes repositioning. Explain that preservation and safe-area compliance conflict instead of moving content silently.

## Text, logos, and signatures

Existing Chinese, English, numbers, punctuation, logos, and interface text are locked pixels unless the user explicitly targets them. Never ask a generative model to recreate unchanged text.

When the user asks to remove a signature or other specific text, mask only that text and reconstruct the surrounding background seamlessly. Do not change adjacent copy or add replacement text, attribution, watermarks, logos, or “AI generated” labels.

## Verification

Before export:

- verify the output has an exact 3:4 ratio;
- check the requested edit and nothing else;
- compare all original readable text character by character;
- inspect the top, bottom, and side safe areas for accidental clipping;
- when deterministic image comparison is available, compare pixels outside the edit mask and require no difference;
- save to a new path and retain the source file.
