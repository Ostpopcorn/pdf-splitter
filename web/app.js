// PDF Splitter web app: the settings, the files, the views of the original
// and the split pages, downloading and printing. The PDFs are split by
// pdfsplitter (Python) in worker.js, and their pages are shown with pdf.js.
// An image is put in a PDF by pdfsplitter, as the pixels that the browser
// decodes, or as it is if it is a JPEG image.

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

// Bumped when the defaults change, so that they apply to everybody once
const SETTINGS_KEY = "pdfsplitter.settings.v1";
const THEME_KEY = "pdfsplitter.theme";
const VIEW_KEY = "pdfsplitter.view";
// Like PAPERS in pdfsplitter/split.py, in mm
const PAPERS = {
  a4: { label: "A4", size: [210, 297] },
  letter: { label: "Letter", size: [215.9, 279.4] },
  a5: { label: "A5", size: [148, 210] },
  a3: { label: "A3", size: [297, 420] },
  legal: { label: "Legal", size: [215.9, 355.6] },
};
const MAX_MARGIN = 25; // mm
const MAX_SHRINK = 25; // percent
const DEFAULT_SETTINGS = { paper: "a4", overlap: 20, margin: 0, shrink: 10 };
// The original pages, both side by side, or the split pages, which are
// shown at first
const VIEWS = ["original", "both", "split"];
const DEFAULT_VIEW = "split";
// The width of the rendered pages in pixels, and their largest area
const RENDER_WIDTH = 1100;
const RENDER_AREA = 24e6;
// The largest image in pixels, and the pixels of each strip that is decoded,
// since a browser limits the size of a canvas
const MAX_IMAGE_AREA = 50e6;
const IMAGE_STRIP = 4e6;
// Safari prints a PDF in a frame as an empty page, so it opens the PDF in a
// new tab to print it from there
const PRINT_IN_TAB = /^((?!chrome|chromium|android|crios|fxios|edg).)*safari/i.test(navigator.userAgent);

const state = {
  settings: loadSettings(),
  view: VIEWS.includes(loadJson(VIEW_KEY, DEFAULT_VIEW)) ? loadJson(VIEW_KEY, DEFAULT_VIEW) : DEFAULT_VIEW,
  linkScroll: true,
  // The open files, whose pages follow one another, each {id, name, data,
  // pages, views, title, annotations, task, images, failed}. Data is the
  // PDF, null while an image is put in a PDF. Pages are the sizes of the
  // pages from pdfsplitter, views from pdf.js, which shows them before
  // Python has read the PDF. Task loads the PDF in pdf.js. Images are the
  // rendered pages. The id also names the jobs of the file in the worker.
  files: [],
  fileId: 0,
  plan: null,
  // {key, data} of the last split PDF, for the settings in key
  output: null,
  ready: false,
  error: null,
  planId: 0,
  splitId: 0,
  // {id, action, name, key, tab} of the split PDF that is being written,
  // to download or to print it
  pending: null,
};

/* Helpers */

function loadJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key));
    return value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

function saveJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
}

// Settings from storage: keep only known keys with the right type
function loadSettings() {
  const settings = { ...DEFAULT_SETTINGS };
  const saved = loadJson(SETTINGS_KEY, {});
  if (saved && typeof saved === "object") {
    for (const key of Object.keys(settings)) {
      if (typeof saved[key] === typeof settings[key]) settings[key] = saved[key];
    }
  }
  if (!(settings.paper in PAPERS)) settings.paper = DEFAULT_SETTINGS.paper;
  return clampSettings(settings);
}

// The largest overlap for the paper and the margin, like max_overlap in
// pdfsplitter/split.py
function maxOverlap({ paper, margin }) {
  return Math.max(0, Math.floor((PAPERS[paper].size[1] - 2 * margin) / 2));
}

function clampSettings(settings) {
  const clamp = (value, max) => Math.min(max, Math.max(0, Number.isFinite(value) ? value : 0));
  settings.margin = clamp(settings.margin, MAX_MARGIN);
  settings.shrink = clamp(settings.shrink, MAX_SHRINK);
  settings.overlap = clamp(settings.overlap, maxOverlap(settings));
  return settings;
}

function escapeHtml(text) {
  return text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function plural(count, word, words = word + "s") {
  return `${count} ${count === 1 ? word : words}`;
}

const percent = (value) => `${Math.round(value * 1e4) / 1e2}%`;

let toastTimer;
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

/* Python worker */

const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });

worker.onmessage = ({ data }) => {
  if (data.type === "progress") {
    setEngine("loading", data.text);
    $("#overlay-text").textContent = data.text;
  } else if (data.type === "ready") {
    state.ready = true;
    state.versions = `pdfsplitter ${data.version} · pypdf ${data.pypdf} · Pyodide ${data.pyodide}`;
    renderVersions();
    setEngine("ready", "Ready");
    $("#overlay-text").textContent = readingText();
    plan();
  } else if (data.type === "read") {
    const file = fileById(data.id);
    if (!file) return;
    const response = data.error ? { error: data.error } : JSON.parse(data.response);
    if (response.error) {
      failFile(file, response.error);
      return;
    }
    Object.assign(file, response);
    renderOriginal();
    plan();
    render();
  } else if (data.type === "image" || data.type === "jpeg") {
    const file = fileById(data.id);
    if (!file) return;
    const { source } = file;
    delete file.source;
    // e.g., a JPEG image in CMYK, which the browser decodes instead
    if (data.error && data.type === "jpeg") decodeFile(file, source);
    else if (data.error) failFile(file, data.error);
    else readPdf(file, data.data);
  } else if (data.type === "plan") {
    if (data.id !== state.planId) return; // a newer plan is on its way
    setBusy(false);
    const response = data.error ? { error: data.error } : JSON.parse(data.response);
    state.error = response.error || null;
    state.plan = response.error ? null : response;
    render();
  } else if (data.type === "split") {
    finishSplit(data);
  } else if (data.type === "fatal") {
    setEngine("error", "Python could not start");
    showError(`Python could not start: ${data.message}`);
  }
};

worker.onerror = (event) => {
  setEngine("error", "Python could not start");
  showError(`Python could not start: ${event.message || "unknown error"}`);
};

function setEngine(kind, text) {
  $("#engine-dot").className = `dot ${kind === "ready" ? "ready" : kind === "error" ? "error" : ""}`;
  $("#engine-state").textContent = text;
}

function setBusy(busy) {
  if (state.ready) setEngine("ready", busy ? "Working…" : "Ready");
}

let planTimer;
function schedule(delay = 30) {
  clearTimeout(planTimer);
  planTimer = setTimeout(plan, delay);
}

// The sizes of the pages of the files, or null until Python has read them
function pageSizes() {
  const { files } = state;
  return files.length && files.every((file) => file.pages) ? files.flatMap((file) => file.pages) : null;
}

// The pages of the files, each {file, idx, size}, as far as they are known
const sizesOf = (file) => file.pages || file.views;
const allPages = () => state.files.flatMap((file) =>
  sizesOf(file).map((size, idx) => ({ file, idx, size })));

// The index of the first page of a file in all pages
function firstPage(file) {
  let first = 0;
  for (const other of state.files) {
    if (other === file) return first;
    first += sizesOf(other).length;
  }
  return -1;
}

function plan() {
  const pages = pageSizes();
  if (!pages) return;
  state.planId += 1;
  if (!state.ready) return;
  setBusy(true);
  worker.postMessage({
    type: "plan", id: state.planId,
    request: { pages, options: state.settings },
  });
}

function showError(message) {
  state.error = message;
  const overlay = $("#overlay");
  overlay.classList.add("show", "error");
  $("#overlay-text").textContent = message;
  renderStatus();
}

/* Settings */

function applySettingsToUI() {
  const { settings } = state;
  for (const input of $$("#paper input")) input.checked = input.value === settings.paper;
  const max = maxOverlap(settings);
  for (const input of $$("[data-setting]")) {
    if (input.dataset.setting === "overlap") input.max = max;
    // keep what is typed in the number field, e.g., an empty field
    if (input !== document.activeElement || input.type === "range") {
      input.value = settings[input.dataset.setting];
    }
  }
  $("#overlap").title = `0 to ${max} mm on ${PAPERS[settings.paper].label}`;
}

function renderPapers() {
  $("#paper").innerHTML = Object.entries(PAPERS).map(([key, { label, size }]) => `
    <label title="${size[0]} × ${size[1]} mm">
      <input type="radio" name="paper" value="${key}"><span>${label}</span>
    </label>`).join("");
}

function changeSetting(key, value) {
  state.settings[key] = value;
  clampSettings(state.settings);
  saveJson(SETTINGS_KEY, state.settings);
  applySettingsToUI();
  schedule();
}

$("#options").addEventListener("input", (event) => {
  const input = event.target;
  if (input.name === "paper") {
    changeSetting("paper", input.value);
  } else if (input.dataset.setting) {
    const value = parseFloat(input.value);
    if (Number.isFinite(value)) changeSetting(input.dataset.setting, value);
  }
});
// Show the value that is used after typing, e.g., the largest overlap
$("#options").addEventListener("change", (event) => {
  if (event.target.type === "number") {
    event.target.value = state.settings[event.target.dataset.setting];
  }
});

/* The files: PDFs and images, whose pages follow one another. New files
   follow the open ones. */

const isPdf = (bytes) => new TextDecoder("latin1").decode(bytes.subarray(0, 1024)).includes("%PDF-");
const isJpeg = (bytes) => bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
const fileById = (id) => state.files.find((file) => file.id === id);
const isOpen = (file) => state.files.includes(file);

// Open files after the open ones, each batch in the order of their names,
// e.g., page 2 before page 10
async function addFiles(list) {
  const sources = [...list].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  if (!sources.length) return;
  if (!state.files.length) resetScroll();
  const files = sources.map((source) => ({
    id: ++state.fileId, name: source.name, data: null, pages: null, views: [], images: [],
  }));
  state.files.push(...files);
  render();
  // one after another, so that only one image is decoded at a time
  for (const [idx, file] of files.entries()) await loadFile(file, sources[idx]);
}

// A PDF is read as it is. A JPEG image is put in a PDF by Python as it is,
// other images as the pixels that the browser decodes.
async function loadFile(file, source) {
  let data;
  try {
    data = new Uint8Array(await source.arrayBuffer());
  } catch {
    failFile(file, "Could not read the file.");
    return;
  }
  if (!isOpen(file)) return;
  if (isPdf(data)) {
    readPdf(file, data);
  } else if (isJpeg(data)) {
    file.source = source;
    worker.postMessage({ type: "jpeg", id: file.id, data });
  } else {
    await decodeFile(file, source);
  }
}

async function decodeFile(file, source) {
  let image;
  try {
    image = await decodeImage(source);
  } catch (err) {
    failFile(file, err instanceof RangeError ? err.message
      : "It is not a PDF or an image that your browser can open.");
    return;
  }
  if (isOpen(file)) worker.postMessage({ type: "image", id: file.id, ...image }, [image.pixels.buffer]);
}

// Read the PDF in Python, and show its pages with pdf.js
function readPdf(file, data) {
  file.data = data;
  worker.postMessage({ type: "read", id: file.id, data });
  renderPages(file);
  render();
}

function failFile(file, message) {
  toast(`${file.name}: ${message}`);
  removeFile(file);
}

function readingText() {
  const { files } = state;
  if (files.length > 1) return "Reading the files…";
  return files.length && !files[0].data ? "Reading the image…" : "Reading the PDF…";
}

// Decode an image into RGB pixels, on white like the paper
async function decodeImage(blob) {
  const bitmap = await createImageBitmap(blob);
  try {
    const { width, height } = bitmap;
    if (width * height > MAX_IMAGE_AREA) throw new RangeError("The image is too large.");
    const rows = Math.max(1, Math.min(height, Math.floor(IMAGE_STRIP / width)));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = rows;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new RangeError("The image is too large.");
    const pixels = new Uint8Array(width * height * 3);
    let out = 0;
    for (let top = 0; top < height; top += rows) {
      const count = Math.min(rows, height - top);
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, width, count);
      context.drawImage(bitmap, 0, top, width, count, 0, 0, width, count);
      const rgba = context.getImageData(0, 0, width, count).data;
      for (let idx = 0; idx < rgba.length; idx += 4) {
        pixels[out++] = rgba[idx];
        pixels[out++] = rgba[idx + 1];
        pixels[out++] = rgba[idx + 2];
      }
    }
    return { pixels, width, height };
  } finally {
    bitmap.close();
  }
}

// Free pdf.js and the rendered pages of a file
function freeFile(file) {
  if (file.task) file.task.destroy().catch(() => {});
  for (const url of file.images) if (url) URL.revokeObjectURL(url);
}

function removeFile(file) {
  if (!isOpen(file)) return;
  state.files = state.files.filter((other) => other !== file);
  freeFile(file);
  filesChanged();
}

function closeAll() {
  const { files } = state;
  state.files = [];
  for (const file of files) freeFile(file);
  filesChanged();
}

// The pages change with the files: the plan of the files before is dropped,
// and the split pages of it are shown until the new plan
function filesChanged() {
  state.planId += 1;
  state.plan = null;
  state.error = null;
  state.output = null;
  state.pending = null;
  removePrintFrame();
  if (!state.files.length) $("#result").innerHTML = "";
  renderOriginal();
  plan();
  render();
}

$("#pick").addEventListener("change", async (event) => {
  const files = [...event.target.files];
  event.target.value = "";
  await addFiles(files);
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-pick]")) $("#pick").click();
});
$("#close-all").addEventListener("click", closeAll);

$("#example").addEventListener("click", async () => {
  try {
    const response = await fetch("examples/example.pdf");
    if (!response.ok) throw new Error(response.status);
    await addFiles([new File([await response.blob()], "example.pdf", { type: "application/pdf" })]);
  } catch {
    toast("Could not load the example");
  }
});

document.addEventListener("paste", async (event) => {
  const files = event.clipboardData ? [...event.clipboardData.files] : [];
  if (files.length) {
    event.preventDefault();
    await addFiles(files);
  }
});

/* Drag and drop */

let dragDepth = 0;
window.addEventListener("dragenter", (event) => {
  if (![...event.dataTransfer.types].includes("Files")) return;
  dragDepth += 1;
  document.body.classList.add("dragging");
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) document.body.classList.remove("dragging");
});
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", async (event) => {
  event.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  await addFiles(event.dataTransfer.files);
});

// The order of the files changes by dragging their chips
let dragged = null;
$("#files").addEventListener("dragstart", (event) => {
  dragged = event.target.closest(".chip");
  if (!dragged) return;
  event.dataTransfer.effectAllowed = "move";
  // Firefox drags only with data
  event.dataTransfer.setData("text/plain", dragged.title);
  dragged.classList.add("dragging");
});
$("#files").addEventListener("dragover", (event) => {
  if (!dragged) return;
  event.preventDefault();
  const chip = event.target.closest(".chip");
  if (!chip || chip === dragged) return;
  const { left, width } = chip.getBoundingClientRect();
  if (event.clientX > left + width / 2) chip.after(dragged);
  else chip.before(dragged);
});
$("#files").addEventListener("dragend", () => {
  if (!dragged) return;
  dragged.classList.remove("dragging");
  dragged = null;
  const order = $$(".chip", $("#files")).map((chip) => Number(chip.dataset.id));
  if (order.join() === state.files.map((file) => file.id).join()) return;
  state.files.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
  filesChanged();
});
// The chips of many files scroll sideways, also with the wheel
$("#files").addEventListener("wheel", (event) => {
  const el = $("#files");
  if (el.scrollWidth <= el.clientWidth || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
  event.preventDefault();
  el.scrollLeft += event.deltaY;
}, { passive: false });
$("#files").addEventListener("click", (event) => {
  const button = event.target.closest("[data-close]");
  if (button) removeFile(fileById(Number(button.dataset.close)));
});

/* Showing the pages with pdf.js */

let pdfjs = null;
async function loadPdfjs() {
  if (!pdfjs) {
    pdfjs = import("./pdfjs/build/pdf.min.mjs").then((module) => {
      module.GlobalWorkerOptions.workerSrc = new URL("./pdfjs/build/pdf.worker.min.mjs", import.meta.url).href;
      state.pdfjsVersion = module.version;
      renderVersions();
      return module;
    });
  }
  return pdfjs;
}

// Render each page into an image, which both panes show
async function renderPages(file) {
  try {
    const module = await loadPdfjs();
    if (!isOpen(file)) return;
    const base = new URL("./pdfjs/", import.meta.url).href;
    file.task = module.getDocument({
      data: file.data.slice(), // pdf.js takes the buffer to its worker
      cMapUrl: `${base}cmaps/`,
      standardFontDataUrl: `${base}standard_fonts/`,
      wasmUrl: `${base}wasm/`,
      iccUrl: `${base}iccs/`,
      isEvalSupported: false,
    });
    const doc = await file.task.promise;
    const pages = [];
    const views = [];
    for (let idx = 0; idx < doc.numPages; idx++) {
      pages.push(await doc.getPage(idx + 1));
      const { width, height } = pages[idx].getViewport({ scale: 1 });
      views.push([width, height]);
    }
    if (!isOpen(file)) return;
    file.views = views;
    // show the pages before Python has read the PDF
    if (!file.pages) renderOriginal();
    for (const [idx, page] of pages.entries()) {
      const [width, height] = file.views[idx];
      const scale = Math.min(RENDER_WIDTH / width, Math.sqrt(RENDER_AREA / (width * height)));
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      // without annotations, which are not in the split PDF either
      await page.render({
        canvas, viewport, background: "#ffffff",
        annotationMode: module.AnnotationMode.DISABLE,
      }).promise;
      page.cleanup();
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!isOpen(file)) return;
      file.images[idx] = URL.createObjectURL(blob);
      showImage(file, idx);
    }
  } catch (err) {
    // closing the file stops pdf.js
    if (!isOpen(file)) return;
    file.failed = true;
    toast(`Could not show the pages of ${file.name}: ${err && err.message || err}`);
    renderOriginal();
  }
}

function showImage(file, idx) {
  const page = firstPage(file) + idx;
  const url = file.images[idx];
  for (const img of $$(`[data-page="${page}"] img`)) {
    img.src = url;
    img.hidden = false;
  }
  for (const el of $$(`.paper[data-page="${page}"]`)) el.classList.remove("loading");
}

/* Rendering */

// The original pages, without the slices, which follow the plan. Several
// files each start with their name.
function renderOriginal() {
  const several = state.files.length > 1;
  $("#original").innerHTML = allPages().map(({ file, idx, size: [width, height] }, page) => `
    ${several && idx === 0 ? `<div class="file-label" title="${escapeHtml(file.name)}">${FILE_ICON}<span>${escapeHtml(file.name)}</span></div>` : ""}
    <div class="orig" data-orig="${page}">
      <div class="page-label">Page ${page + 1}<span></span></div>
      <div class="orig-row">
        <div class="brackets"></div>
        <div class="paper ${file.images[idx] ? "" : file.failed ? "failed" : "loading"}" data-page="${page}" style="aspect-ratio: ${width} / ${height}">
          <img alt="Page ${page + 1}" ${file.images[idx] ? `src="${file.images[idx]}"` : "hidden"}>
          <div class="slice-hl"></div>
        </div>
      </div>
    </div>`).join("");
  unlink();
}

// The pages of paper of the plan, each with the page of the original that
// it shows and the slice of that page
function sheetsOf(plan) {
  const sheets = [];
  plan.pages.forEach((page, idx) => {
    page.slices.forEach(([top, bottom], part) => {
      sheets.push({ page: idx, part, count: page.slices.length, top, bottom, scale: page.scale, left: page.left });
    });
  });
  return sheets;
}

// The scale of a page as wide as the paper within the margins
const fullScale = (plan, width) => (plan.paper[0] - 2 * plan.margin) / width;

function renderSlices(plan, pages) {
  let out = 0;
  plan.pages.forEach((page, idx) => {
    const orig = $(`[data-orig="${idx}"]`);
    if (!orig) return;
    const [width, height] = pages[idx];
    const count = page.slices.length;
    const shrunk = Math.round((1 - page.scale / fullScale(plan, width)) * 100);
    $(".page-label span", orig).textContent = (count > 1 ? `· split onto ${count} pages` : "· fits on one page")
      + (shrunk > 0 ? `, ${shrunk}% smaller` : "");
    $(".brackets", orig).innerHTML = page.slices.map(([top, bottom], part) => `
      <div class="bracket ${part % 2 ? "odd" : "even"}" data-out="${out + part}"
           title="Page ${out + part + 1} of the split PDF"
           style="top: ${percent(top / height)}; height: ${percent((Math.min(bottom, height) - top) / height)}">
        <b>${out + part + 1}</b>
      </div>`).join("");
    const paper = $(".paper", orig);
    for (const el of $$(".band", paper)) el.remove();
    page.slices.slice(1).forEach(([top], part) => {
      const bottom = page.slices[part][1];
      if (bottom <= top) return;
      paper.insertAdjacentHTML("beforeend", `
        <div class="band" style="top: ${percent(top / height)}; height: ${percent((bottom - top) / height)}">
          <span class="band-label">on pages ${out + part + 1} and ${out + part + 2}</span>
        </div>`);
    });
    out += count;
  });
}

function renderSheets(plan, sheets) {
  const pages = allPages();
  const [paperWidth, paperHeight] = plan.paper;
  const { margin, overlap } = plan;
  const contentWidth = paperWidth - 2 * margin;
  const contentHeight = paperHeight - 2 * margin;
  const box = `left: ${percent(margin / paperWidth)}; top: ${percent(margin / paperHeight)};
    width: ${percent(contentWidth / paperWidth)}; height: ${percent(contentHeight / paperHeight)}`;
  const band = percent(Math.min(1, overlap / contentHeight));
  $("#result").innerHTML = sheets.map(({ page, part, count, top, scale, left }, out) => {
    const { file, idx, size: [width, height] } = pages[page];
    const url = file.images[idx];
    // a page that is shrunk is narrower than the paper, in its middle
    const place = `left: ${percent(left / contentWidth)}; width: ${percent(width * scale / contentWidth)};
      transform: translateY(-${percent(top / height)})`;
    const from = count > 1 ? `from page ${page + 1}, part ${part + 1} of ${count}` : `page ${page + 1}`;
    return `
      <div class="sheet-wrap" data-out="${out}">
        <div class="sheet-label">${out + 1}<span>· ${from}</span></div>
        <div class="sheet ${margin > 0 ? "has-margin" : ""}" data-page="${page}" style="aspect-ratio: ${paperWidth} / ${paperHeight}">
          <div class="sheet-content" style="${box}">
            <img alt="" style="${place}" ${url ? `src="${url}"` : "hidden"}>
            ${overlap > 0 && part > 0 ? `<div class="band top" style="top: 0; height: ${band}"></div>` : ""}
            ${overlap > 0 && part < count - 1 ? `<div class="band bottom" style="bottom: 0; height: ${band}"></div>` : ""}
          </div>
        </div>
      </div>`;
  }).join("");
  unlink();
}

function render() {
  const { plan } = state;
  const open = state.files.length > 0;
  document.body.classList.toggle("has-files", open);
  document.body.classList.toggle("several-files", state.files.length > 1);
  renderFiles();
  const overlay = $("#overlay");
  // the split pages of the files before stay until the new plan
  const waiting = open && !plan && !state.error && !$("#result").childElementCount;
  overlay.classList.toggle("show", Boolean(waiting || (open && state.error)));
  overlay.classList.toggle("error", Boolean(state.error));
  if (state.error) $("#overlay-text").textContent = state.error;
  else if (waiting && state.ready) $("#overlay-text").textContent = readingText();
  const ready = Boolean(open && plan && state.ready);
  $("#download").disabled = !ready;
  $("#print").disabled = !ready;
  const pages = pageSizes();
  if (plan && pages && plan.pages.length === pages.length) {
    renderSlices(plan, pages);
    renderSheets(plan, sheetsOf(plan));
    // keep the split pages at the part of the original that is shown
    if (linked()) align(panes.original, panes.result);
  }
  renderMeta();
  renderStatus();
}

const FILE_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>`;

// A chip for each file, which is dragged to change the order of several
function renderFiles() {
  if (dragged) return;
  const several = state.files.length > 1;
  $("#files").innerHTML = state.files.map(({ id, name, pages }) => `
    <span class="chip ${pages ? "" : "reading"}" data-id="${id}" draggable="${several}"
          title="${escapeHtml(name)}${several ? "\nDrag to change the order" : ""}">
      ${FILE_ICON}<span class="name">${escapeHtml(name)}</span><span class="count">${pages ? ` · ${plural(pages.length, "page")}` : " · reading…"}</span>
      <button class="chip-close" data-close="${id}" aria-label="Close ${escapeHtml(name)}" title="Close">×</button>
    </span>`).join("");
}

function renderMeta() {
  const { files, plan } = state;
  const pages = allPages().length;
  $("#original-meta").textContent = files.length > 1
    ? `${plural(files.length, "file")} · ${plural(pages, "page")}`
    : files.length ? files[0].name + (pages ? ` · ${plural(pages, "page")}` : "") : "";
  $("#result-meta").textContent = plan
    ? `${PAPERS[state.settings.paper].label} · ${plural(sheetsOf(plan).length, "page")}` : "";
}

const ICON_WARN = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 21h20z"/><path d="M12 10v5"/><path d="M12 18h.01"/></svg>`;
const ICON_INFO = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7h.01"/></svg>`;

function renderStatus() {
  const { plan } = state;
  const counts = $("#status-counts");
  const messages = [];
  if (plan) {
    const split = plan.pages.filter((page) => page.slices.length > 1).length;
    const out = sheetsOf(plan).length;
    counts.innerHTML = `<strong>${split}</strong> of ${plural(plan.pages.length, "page")} split · `
      + `<strong>${plan.pages.length} → ${out}</strong> ${out === 1 ? "page" : "pages"}`;
    const scales = plan.pages.map((page) => Math.round(page.scale * 100));
    const low = Math.min(...scales);
    const high = Math.max(...scales);
    messages.push(["info", `Scaled to ${low === high ? low : `${low}–${high}`}% to fit the width of ${PAPERS[state.settings.paper].label}`
      + (plan.margin > 0 ? ` within the margins` : "") + "."]);
  } else {
    counts.textContent = "";
  }
  const annotations = state.files.reduce((sum, file) => sum + (file.annotations || 0), 0);
  if (annotations) {
    messages.push(["warning", `${plural(annotations, "annotation")}, e.g., comments or links, ${annotations === 1 ? "is" : "are"} not in the split PDF.`]);
  }
  if (state.error) messages.unshift(["error", state.error]);
  $("#status-messages").innerHTML = messages.map(([kind, text]) =>
    `<span class="msg ${kind}" title="${escapeHtml(text)}">${kind === "info" ? ICON_INFO : ICON_WARN}${escapeHtml(text)}</span>`).join("");
}

function renderVersions() {
  $("#about-version").textContent = [state.versions, state.pdfjsVersion && `pdf.js ${state.pdfjsVersion}`]
    .filter(Boolean).join(" · ");
}

/* Views: the original pages, both side by side, or the split pages */

function renderView() {
  for (const view of VIEWS) document.body.classList.toggle(`view-${view}`, state.view === view);
  for (const input of $$("#views input")) input.checked = input.value === state.view;
  unlink();
}

// The page at the top of a pane, and how far the pane is scrolled into it
function topPage(pane) {
  if (!pane.el.clientHeight) return null; // hidden
  const top = pane.el.scrollTop;
  const page = $$(".orig, .sheet-wrap", pane.el).find((el) => topIn(pane, el) + el.offsetHeight > top);
  return page ? { page, into: (top - topIn(pane, page)) / page.offsetHeight } : null;
}

function scrollToPage(pane, anchor) {
  if (anchor && pane.el.clientHeight) {
    setScroll(pane, topIn(pane, anchor.page) + anchor.into * anchor.page.offsetHeight);
  }
}

$("#views").addEventListener("change", (event) => {
  const view = event.target.value;
  if (!VIEWS.includes(view)) return;
  // The pages are side by side in a view of one pane, so the pane that is
  // shown before and after keeps its page at the top, and the other pane
  // follows it
  const kept = state.view === "split" || view === "split" ? panes.result : panes.original;
  const anchor = topPage(kept);
  state.view = view;
  saveJson(VIEW_KEY, view);
  renderView();
  scrollToPage(kept, anchor);
  if (linked()) align(kept, other(kept));
});

/* Linking the panes: a slice of the original and its page of paper */

function highlight(out, on) {
  for (const el of $$(`[data-out="${out}"]`)) el.classList.toggle("hl", on);
  const { plan } = state;
  const pages = pageSizes();
  if (!plan || !pages) return;
  const sheet = sheetsOf(plan)[out];
  if (!sheet) return;
  const hl = $(`[data-orig="${sheet.page}"] .slice-hl`);
  if (!hl) return;
  const height = pages[sheet.page][1];
  hl.style.top = percent(sheet.top / height);
  hl.style.height = percent((Math.min(sheet.bottom, height) - sheet.top) / height);
  hl.classList.toggle("show", on);
}

for (const pane of ["#original", "#result"]) {
  $(pane).addEventListener("mouseover", (event) => {
    const el = event.target.closest(pane === "#original" ? ".bracket" : ".sheet-wrap");
    if (el && state.view === "both") highlight(Number(el.dataset.out), true);
  });
  $(pane).addEventListener("mouseout", (event) => {
    const el = event.target.closest(pane === "#original" ? ".bracket" : ".sheet-wrap");
    if (el && !el.contains(event.relatedTarget)) highlight(Number(el.dataset.out), false);
  });
}

function scrollWithin(scroller, el, offset = 0) {
  const top = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
  scroller.scrollTo({ top: Math.max(0, top + offset - 12), behavior: "smooth" });
}

// Clicking a slice shows its page of paper, and the other way round
$("#original").addEventListener("click", (event) => {
  const bracket = event.target.closest(".bracket");
  if (!bracket || state.view !== "both") return;
  const wrap = $(`#result .sheet-wrap[data-out="${bracket.dataset.out}"]`);
  if (!wrap) return;
  scrollWithin($("#result"), wrap);
  const sheet = $(".sheet", wrap);
  sheet.classList.remove("flash");
  void sheet.offsetWidth;
  sheet.classList.add("flash");
});

$("#result").addEventListener("click", (event) => {
  const wrap = event.target.closest(".sheet-wrap");
  if (!wrap || !state.plan || state.view !== "both") return;
  const sheet = sheetsOf(state.plan)[Number(wrap.dataset.out)];
  const paper = $(`[data-orig="${sheet.page}"] .paper`);
  if (!paper) return;
  const height = pageSizes()[sheet.page][1];
  scrollWithin($("#original"), paper, paper.offsetHeight * sheet.top / height);
});

/* Linked scrolling, like in TeX Tools */

const panes = {
  original: { el: $("#original"), expected: null, link: null },
  result: { el: $("#result"), expected: null, link: null },
};
const other = (pane) => (pane === panes.original ? panes.result : panes.original);
const linked = () => state.linkScroll && state.view === "both";

function resetScroll() {
  for (const pane of Object.values(panes)) setScroll(pane, 0);
}

// Scroll a pane from the code. Its scroll event is recognized by the
// position, so that it is not taken for the user's.
function setScroll(pane, top) {
  if (Math.abs(pane.el.scrollTop - top) >= 1) pane.el.scrollTop = top;
  pane.expected = pane.el.scrollTop;
}

// The positions of the elements change with the content and the width
function unlink() {
  for (const pane of Object.values(panes)) pane.link = null;
}

// The top of an element in the content of a pane
const topIn = (pane, el) => el.getBoundingClientRect().top - pane.el.getBoundingClientRect().top + pane.el.scrollTop;

// Map from the content of a pane to the content of the other pane, as points
// with straight lines between them. Each slice of the original is mapped to
// its page of paper. Where two slices overlap, the original goes through the
// overlap while the split pages go from the overlap at the end of a page to
// the overlap at the top of the next page, so that neither pane leaps.
function linkMap(from) {
  if (from.link) return from.link;
  const { plan } = state;
  const pages = pageSizes();
  const points = [[0, 0]];
  if (plan && pages && plan.pages.length === pages.length) {
    const contentWidth = plan.paper[0] - 2 * plan.margin;
    let out = 0;
    plan.pages.forEach((page, idx) => {
      const paper = $(`[data-orig="${idx}"] .paper`, panes.original.el);
      const contents = page.slices.map((_, part) =>
        $(`.sheet-wrap[data-out="${out + part}"] .sheet-content`, panes.result.el));
      out += page.slices.length;
      if (!paper || contents.some((el) => !el)) return;
      const height = pages[idx][1];
      const paperTop = topIn(panes.original, paper);
      const original = (y) => paperTop + paper.offsetHeight * Math.min(y, height) / height;
      const sheets = contents.map((el, part) => {
        const contentTop = topIn(panes.result, el);
        const perPoint = el.offsetWidth / contentWidth * page.scale;
        return (y) => contentTop + (Math.min(y, height) - page.slices[part][0]) * perPoint;
      });
      const pair = (y, part) => [original(y), sheets[part](y)];
      points.push(pair(0, 0));
      page.slices.slice(1).forEach(([top], part) => {
        points.push(pair(top, part), pair(page.slices[part][1], part + 1));
      });
      points.push(pair(height, page.slices.length - 1));
    });
  }
  points.push([panes.original.el.scrollHeight, panes.result.el.scrollHeight]);
  from.link = from === panes.original ? points : points.map(([a, b]) => [b, a]);
  return from.link;
}

function mapLink(points, position) {
  if (position <= points[0][0]) return points[0][1];
  // The last point at or before the position
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (points[mid][0] <= position) lo = mid;
    else hi = mid - 1;
  }
  const [x, y] = points[lo];
  const next = points[lo + 1];
  return next && next[0] > x ? y + (position - x) / (next[0] - x) * (next[1] - y) : y;
}

// The line at which the panes are linked, as a fraction of the height of a
// pane: the top at its start, the middle, and the bottom at its end, so that
// both panes start and end together
function linkLine(pane) {
  const max = pane.el.scrollHeight - pane.el.clientHeight;
  if (max <= 0) return 0;
  const zone = Math.min(pane.el.clientHeight, max) / 2;
  const position = Math.min(Math.max(pane.el.scrollTop, 0), max);
  return (Math.min(position, zone) + zone - Math.min(max - position, zone)) / (2 * zone);
}

// Scroll the other pane to what a pane shows
function align(from, to) {
  if (!state.plan) return;
  const line = linkLine(from);
  const at = mapLink(linkMap(from), from.el.scrollTop + line * from.el.clientHeight);
  const max = to.el.scrollHeight - to.el.clientHeight;
  setScroll(to, Math.min(Math.max(0, at - line * to.el.clientHeight), max));
}

for (const pane of Object.values(panes)) {
  pane.el.addEventListener("scroll", () => {
    if (pane.expected !== null && Math.abs(pane.el.scrollTop - pane.expected) < 1) return;
    pane.expected = null;
    if (linked()) align(pane, other(pane));
  }, { passive: true });
}

const resizeObserver = new ResizeObserver(unlink);
for (const pane of Object.values(panes)) resizeObserver.observe(pane.el);

function renderLinkScroll() {
  const button = $("#link-scroll");
  button.setAttribute("aria-pressed", String(state.linkScroll));
  button.parentElement.classList.toggle("linked", state.linkScroll);
  button.title = state.linkScroll
    ? "Scrolling is linked: both sides show the same part of the page. Click to scroll them separately."
    : "Scrolling is not linked. Click to scroll both sides together.";
}

$("#link-scroll").addEventListener("click", () => {
  state.linkScroll = !state.linkScroll;
  renderLinkScroll();
  if (linked()) align(panes.original, panes.result);
});

/* About */

const aboutDialog = $("#about-dialog");
$("#about-open").addEventListener("click", () => aboutDialog.showModal());
aboutDialog.addEventListener("click", (event) => {
  if (event.target === aboutDialog || event.target.closest("[data-dialog-close]")) aboutDialog.close();
});

/* Downloading and printing the split PDF */

function saveBlob(blob, name) {
  const link = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob), download: name,
  });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

// notes.pdf, or notes.png, is saved as notes-a4.pdf, and with other files
// after it as notes-combined-a4.pdf
const splitName = (files, paper) =>
  `${files[0].name.replace(/\.[a-z0-9]{1,5}$/i, "")}${files.length > 1 ? "-combined" : ""}-${paper}.pdf`;
// The split PDF is written again only when the settings or the files change
const outputKey = () => JSON.stringify([state.settings, state.files.map((file) => file.id)]);

// Write the split PDF, or use the last one, and download or print it
function split(action) {
  const { files, plan } = state;
  if (!files.length || !plan || !state.ready) return;
  const name = splitName(files, state.settings.paper);
  if (state.output && state.output.key === outputKey()) {
    deliver(action, state.output.data, name);
    return;
  }
  state.splitId += 1;
  state.pending = {
    id: state.splitId, action, name, key: outputKey(),
    // a tab opens only right after a click, not when the PDF is written
    tab: action === "print" && PRINT_IN_TAB ? window.open("", "_blank") : null,
  };
  toast(action === "print" ? `Writing ${name} to print it…` : `Writing ${name}…`);
  worker.postMessage({
    type: "split", id: state.splitId, files: files.map((file) => file.data),
    request: { options: state.settings },
  });
}

function finishSplit(data) {
  const { pending } = state;
  if (!pending || data.id !== pending.id) return;
  state.pending = null;
  if (data.error) {
    if (pending.tab) pending.tab.close();
    toast(`Could not write ${pending.name}: ${data.error}`);
    return;
  }
  if (outputKey() === pending.key) state.output = { key: pending.key, data: data.data };
  deliver(pending.action, data.data, pending.name, pending.tab);
}

function deliver(action, data, name, tab = null) {
  const blob = new Blob([data], { type: "application/pdf" });
  if (action === "download") saveBlob(blob, name);
  else printBlob(blob, tab);
}

let printFrame = null;
function removePrintFrame() {
  if (!printFrame) return;
  URL.revokeObjectURL(printFrame.src);
  printFrame.remove();
  printFrame = null;
}

// Print the PDF in a hidden frame, which shows the print dialog of the
// browser, or else from a new tab
function printBlob(blob, tab) {
  const url = URL.createObjectURL(blob);
  const inTab = () => {
    const opened = tab || window.open(url, "_blank");
    if (!opened) {
      toast("Allow pop-ups to print the split PDF, or download it and print it");
      return;
    }
    if (tab) tab.location.href = url;
    toast("Print the split PDF from the new tab");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };
  if (PRINT_IN_TAB) {
    inTab();
    return;
  }
  removePrintFrame();
  const frame = Object.assign(document.createElement("iframe"), {
    className: "print-frame", src: url, title: "The split PDF to print",
  });
  frame.addEventListener("load", () => {
    setTimeout(() => {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch {
        inTab();
      }
    }, 100);
  }, { once: true });
  printFrame = frame;
  document.body.append(frame);
}

$("#download").addEventListener("click", () => split("download"));
$("#print").addEventListener("click", () => split("print"));
document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || !state.files.length) return;
  if (event.key === "s" || event.key === "p") {
    event.preventDefault();
    split(event.key === "s" ? "download" : "print");
  }
});

/* Theme */

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

$("#theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = dark ? "light" : "dark";
  applyTheme(theme);
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private mode */ }
});

/* Start */

try { applyTheme(localStorage.getItem(THEME_KEY)); } catch { /* private mode */ }
renderPapers();
applySettingsToUI();
renderView();
renderLinkScroll();
render();
// Load pdf.js while Python starts, so that the first PDF shows sooner
loadPdfjs().catch(() => {});
