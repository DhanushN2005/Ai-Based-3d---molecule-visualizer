/* Shared 3Dmol.js wrapper used by the viewer, compare and quiz pages.
 * Colours come from the server (elements.py) so the scene, legend and .glb agree. */
(function () {
  const UNKNOWN = "#FF1493";
  const SUB = "₀₁₂₃₄₅₆₇₈₉";
  const subscript = s => s.replace(/\d/g, d => SUB[+d]);
  const BOND_SYMBOL = { 1: "–", 2: "=", 3: "≡" };
  const BOND_COLOR = { 1: "#e2e8f0", 2: "#fde047", 3: "#fb7185" };

  class MolView {
    constructor(el, opts) {
      opts = opts || {};
      this.colors = opts.colors || {};
      this.names = opts.names || {};
      this.title = opts.title || "";
      this.el = el;
      this.formula = opts.formula || "";
      this.smiles = opts.smiles || "";
      this.tip = opts.tip || null;          // element for hover tooltip (optional)
      this.tipBox = opts.tipBox || el;      // element the tooltip is positioned in
      this.fitScale = opts.fitScale || 0.85;   // number, or "auto" to scale by molecule size
      this.dark = opts.dark !== false;
      this.styleKind = "bs";
      this.atomLabels = "off";
      this.bondLabels = "off";
      this.showTitle = !!opts.showTitle;
      this.spinning = opts.spin !== false;
      this.molblock = null;
      this.v = $3Dmol.createViewer(el, { backgroundColor: this.dark ? "#0b1220" : "#ffffff" });
    }

    hexNum(el) { return parseInt((this.colors[el] || UNKNOWN).slice(1), 16); }

    styleSpec() {
      const cf = a => this.hexNum(a.elem);
      switch (this.styleKind) {
        case "stick":  return { stick: { radius: 0.2, colorfunc: cf } };
        case "sphere": return { sphere: { colorfunc: cf } };
        case "line":   return { line: { colorfunc: cf } };
        default:       return { stick: { radius: 0.15, colorfunc: cf }, sphere: { scale: 0.28, colorfunc: cf } };
      }
    }

    atoms() { return this.v.getModel(0).selectedAtoms({}); }

    redecorate() {
      const v = this.v;
      v.removeAllLabels();
      const atoms = this.atoms();

      if (this.atomLabels !== "off") {
        atoms.forEach(a => {
          if (this.atomLabels === "symnoh" && a.elem === "H") return;
          v.addLabel(this.atomLabels === "name" ? (this.names[a.elem] || a.elem) : a.elem, {
            position: { x: a.x, y: a.y, z: a.z },
            fontSize: 14, fontColor: this.colors[a.elem] || UNKNOWN, bold: true,
            backgroundColor: "#000000", backgroundOpacity: 0.55,
            showBackground: true, inFront: true, alignment: "center",
          });
        });
      }

      if (this.bondLabels !== "off") {
        atoms.forEach(a => {
          (a.bonds || []).forEach((j, k) => {
            if (j < a.index) return;                    // draw each bond once
            const b = atoms[j];
            if (!b) return;
            const order = Math.max(1, Math.min(3, Math.round((a.bondOrder || [])[k] || 1)));
            const sym = BOND_SYMBOL[order];
            v.addLabel(this.bondLabels === "pair" ? a.elem + sym + b.elem : sym, {
              position: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 },
              fontSize: this.bondLabels === "pair" ? 11 : 16, fontColor: BOND_COLOR[order], bold: true,
              backgroundColor: "#000000", backgroundOpacity: 0.6,
              showBackground: true, inFront: true, alignment: "center",
            });
          });
        });
      }

      if (this.showTitle && this.title && atoms.length) {
        // Floats in the 3D scene itself: name + formula above the molecule, SMILES below it.
        const xs = atoms.map(a => a.x), ys = atoms.map(a => a.y), zs = atoms.map(a => a.z);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
        const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
        v.addLabel(this.title + (this.formula ? "  ·  " + subscript(this.formula) : ""), {
          position: { x: cx, y: Math.max(...ys) + 1.4, z: cz }, alignment: "center",
          fontSize: 20, fontColor: "#f1f5f9", bold: true, inFront: true,
          backgroundColor: "#0f172a", backgroundOpacity: 0.7, showBackground: true,
          borderColor: "#5eead4", borderThickness: 1,
        });
        if (this.smiles) {
          v.addLabel("SMILES  " + this.smiles, {
            position: { x: cx, y: Math.min(...ys) - 1.4, z: cz }, alignment: "center",
            fontSize: 12, fontColor: "#cbd5e1", inFront: true,
            backgroundColor: "#0f172a", backgroundOpacity: 0.6, showBackground: true,
          });
        }
      }
      v.render();
    }

    setupHover() {
      const tip = this.tip;
      if (!tip) return;
      this.v.setHoverable({}, true,
        (atom, v, ev) => {
          if (!atom) return;
          const box = this.tipBox.getBoundingClientRect();
          tip.textContent = (this.names[atom.elem] || atom.elem) + " (" + atom.elem + ") · atom #" + (atom.serial ?? atom.index + 1);
          tip.style.left = Math.min(ev.clientX - box.left + 14, box.width - 200) + "px";
          tip.style.top = (ev.clientY - box.top + 14) + "px";
          tip.style.display = "block";
        },
        () => { tip.style.display = "none"; });
    }

    decorate() {
      this.v.setStyle({}, this.styleSpec());
      this.setupHover();
      this.redecorate();
      this.v.spin(this.spinning ? "y" : false, 0.6);
    }

    load(molblock) {
      this.molblock = molblock || this.molblock;
      this.v.stopAnimate();
      this.v.removeAllModels();
      this.v.addModel(this.molblock, "sdf");
      this.decorate();
      this.fit();
    }

    fit() {            // zoom to the molecule with margin for the toolbar and floating title
      this.v.zoomTo();
      let k = this.fitScale;
      if (k === "auto") {                      // tiny molecules fill the panel, big ones keep a margin
        const n = this.atoms().length;
        k = n <= 6 ? 1.6 : n <= 14 ? 1.35 : 1.12;
        if (this.el.clientWidth < 520) k *= 0.85;   // long molecules need more room on narrow panels
      }
      this.v.zoom(k);
      this.v.render();
    }

    loadFrames(sdf) {
      this.v.removeAllModels();
      this.v.addModelsAsFrames(sdf, "sdf");
      this.decorate();
      this.v.animate({ interval: 60, loop: "forward" });
    }

    setStyle(kind) { this.styleKind = kind; this.v.setStyle({}, this.styleSpec()); this.v.render(); }
    setAtomLabels(mode) { this.atomLabels = mode; this.redecorate(); }
    setBondLabels(mode) { this.bondLabels = mode; this.redecorate(); }
    setTitleVisible(on) { this.showTitle = on; this.redecorate(); }
    setDark(dark) { this.dark = dark; this.v.setBackgroundColor(dark ? "#0b1220" : "#ffffff"); this.redecorate(); }
    spin(on) { this.spinning = on; this.v.spin(on ? "y" : false, 0.6); }
    reset() { this.fit(); }
    resize() { this.v.resize(); this.v.render(); }
    png() { return this.v.pngURI(); }
  }

  window.MolView = MolView;
  window.molSubscript = subscript;
})();
