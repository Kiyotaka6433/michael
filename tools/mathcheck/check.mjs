// Reads a JSON array of LaTeX strings on stdin, prints a JSON array with null (renders) or an error message.
// Uses MathJax 3 with every TeX package, like Obsidian, but with errors turned into failures instead of red text.
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { mathjax } = require("mathjax-full/js/mathjax.js");
const { TeX } = require("mathjax-full/js/input/tex.js");
const { AllPackages } = require("mathjax-full/js/input/tex/AllPackages.js");
const { liteAdaptor } = require("mathjax-full/js/adaptors/liteAdaptor.js");
const { RegisterHTMLHandler } = require("mathjax-full/js/handlers/html.js");
const { STATE } = require("mathjax-full/js/core/MathItem.js");

RegisterHTMLHandler(liteAdaptor());
const tex = new TeX({
  packages: AllPackages.filter((p) => !["noerrors", "noundefined", "bussproofs"].includes(p)),
  formatError: (_jax, err) => { throw err; },
});
const doc = mathjax.document("", { InputJax: tex });

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (input += d));
process.stdin.on("end", () => {
  const out = JSON.parse(input).map((f) => {
    try {
      doc.convert(f, { display: true, end: STATE.CONVERT });   // parse to MathML only, no layout
      return null;
    } catch (e) {
      return String(e.message || e);
    }
  });
  process.stdout.write(JSON.stringify(out));
});
