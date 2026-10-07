# A drawing box for a card's picture mnemonic: the card's front shown
# faintly, and the user's ink drawn over it with a mouse, pen or finger.
# Built on Streamlit's own custom components (st.components.v2), so no
# extra package: the canvas runs in the page, and "Save" sends the ink back
# as a PNG (transparent, ink only -- the faint front is drawn again
# wherever it's shown). An empty canvas saved means "no drawing".
import base64

import streamlit as st

_CSS = """
.drawing { display: flex; flex-direction: column; gap: 0.5rem; align-items: flex-start; }
.drawing-sheet {
    position: relative; width: min(320px, 100%); aspect-ratio: 1;
    border: 1px solid var(--accent); touch-action: none; cursor: crosshair;
}
.drawing-sheet canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.drawing-tools { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.drawing-tools button {
    font: inherit; color: var(--accent); background: transparent; border: 1px solid var(--accent);
    border-radius: 0.5rem; padding: 0.2rem 0.7rem; cursor: pointer;
}
.drawing-tools button:hover { color: var(--text); border-color: var(--text); }
.drawing-tools button[aria-pressed="true"] { color: var(--text); border-color: var(--text); }
.drawing-tools button:disabled { opacity: 0.4; cursor: default; }
.drawing-status { opacity: 0.6; font-size: 0.85em; }
"""

_JS = """
export default function (component) {
    const { data, parentElement, setTriggerValue } = component;
    // Runs again whenever the page reruns; the sheet (and the ink on it)
    // is only built once per box.
    if (parentElement.querySelector(".drawing")) return;
    const root = document.createElement("div");
    root.className = "drawing";
    root.style.setProperty("--accent", data.accent);
    root.style.setProperty("--text", data.text);
    root.innerHTML = `
        <div class="drawing-sheet"><canvas class="guide"></canvas><canvas class="ink"></canvas></div>
        <div class="drawing-tools">
            <button data-tool="pen" aria-pressed="true">Pen</button>
            <button data-tool="accent" aria-pressed="false">Colour</button>
            <button data-tool="eraser" aria-pressed="false">Eraser</button>
            <button data-action="undo" disabled>Undo</button>
            <button data-action="clear">Clear</button>
            <button data-action="save">Save drawing</button>
        </div>
        <div class="drawing-status"></div>`;
    parentElement.appendChild(root);
    const sheet = root.querySelector(".drawing-sheet");
    const guide = root.querySelector(".guide");
    const ink = root.querySelector(".ink");
    const status = root.querySelector(".drawing-status");
    const size = 640;  // drawn at twice the shown size, for sharp lines
    for (const canvas of [guide, ink]) { canvas.width = size; canvas.height = size; }

    // The card's front, faint, to draw over.
    const g = guide.getContext("2d");
    g.fillStyle = data.text;
    g.globalAlpha = 0.18;
    g.textAlign = "center";
    g.textBaseline = "middle";
    const fontSize = Math.min(size * 0.8, (size * 0.9) / Math.max(1, data.front.length));
    g.font = `${fontSize}px "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif`;
    g.fillText(data.front, size / 2, size / 2);

    const c = ink.getContext("2d");
    c.lineCap = "round";
    c.lineJoin = "round";
    if (data.image) {
        const saved = new Image();
        saved.onload = () => c.drawImage(saved, 0, 0, size, size);
        saved.src = data.image;
    }

    let tool = "pen";
    const undo = [];
    const undoButton = root.querySelector('[data-action="undo"]');
    const remember = () => {
        undo.push(c.getImageData(0, 0, size, size));
        if (undo.length > 30) undo.shift();
        undoButton.disabled = false;
        status.textContent = "Not saved yet";
    };
    const point = event => {
        const box = ink.getBoundingClientRect();
        return [(event.clientX - box.left) * size / box.width, (event.clientY - box.top) * size / box.height];
    };
    let last = null;
    sheet.addEventListener("pointerdown", event => {
        event.preventDefault();
        sheet.setPointerCapture(event.pointerId);
        remember();
        last = point(event);
        stroke(event, last);
    });
    sheet.addEventListener("pointermove", event => {
        if (!last) return;
        const next = point(event);
        stroke(event, next);
        last = next;
    });
    const stop = () => { last = null; };
    sheet.addEventListener("pointerup", stop);
    sheet.addEventListener("pointercancel", stop);
    function stroke(event, to) {
        // A pen's pressure thickens the line; a mouse is a steady 0.5.
        const pressure = event.pressure > 0 ? event.pressure : 0.5;
        c.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
        c.strokeStyle = tool === "accent" ? data.accent : data.text;
        c.lineWidth = (tool === "eraser" ? 40 : 10) * (0.5 + pressure);
        c.beginPath();
        c.moveTo(last[0], last[1]);
        c.lineTo(to[0], to[1]);
        c.stroke();
    }

    root.querySelectorAll("[data-tool]").forEach(button => button.addEventListener("click", () => {
        tool = button.dataset.tool;
        root.querySelectorAll("[data-tool]").forEach(other => other.setAttribute("aria-pressed", other === button));
    }));
    undoButton.addEventListener("click", () => {
        if (undo.length) c.putImageData(undo.pop(), 0, 0);
        undoButton.disabled = !undo.length;
        status.textContent = "Not saved yet";
    });
    root.querySelector('[data-action="clear"]').addEventListener("click", () => {
        remember();
        c.clearRect(0, 0, size, size);
    });
    root.querySelector('[data-action="save"]').addEventListener("click", () => {
        // Nothing drawn: sent as "", which removes a saved drawing.
        const pixels = c.getImageData(0, 0, size, size).data;
        let blank = true;
        for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) { blank = false; break; }
        setTriggerValue("saved", blank ? "" : ink.toDataURL("image/png"));
        status.textContent = "Saved";
    });
}
"""

_drawing_box = st.components.v2.component("prescripts_drawing", css=_CSS, js=_JS)


def drawing_box(key: str, front: str, image: bytes | None, text_color: str, accent_color: str) -> bytes | None:
    # Shows the box, and returns the PNG just saved with "Save drawing" (b""
    # for an empty canvas), or None on every other run. `image` is the
    # drawing saved before, to carry on from.
    image_url = "data:image/png;base64," + base64.b64encode(image).decode() if image else ""
    result = _drawing_box(
        key=key,
        data={"front": front, "image": image_url, "text": text_color, "accent": accent_color},
        on_saved_change=lambda: None,
    )
    saved = getattr(result, "saved", None)
    if saved is None:
        return None
    return base64.b64decode(saved.split(",", 1)[1]) if saved else b""
