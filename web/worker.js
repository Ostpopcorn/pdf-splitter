// Runs pdfsplitter with Pyodide, so that the page stays responsive while
// Python works. Only the latest request to plan the pages is processed,
// after the PDFs to read or to split.
import { loadPyodide } from "./pyodide/pyodide.mjs";

let bridge = null;
let latest = null;
let scheduled = false;
const jobs = []; // PDFs to read ("read") or split ("split")

async function init() {
  postMessage({ type: "progress", text: "Starting Python…" });
  const pyodide = await loadPyodide({ indexURL: new URL("./pyodide/", import.meta.url).href });
  postMessage({ type: "progress", text: "Loading pdfsplitter…" });
  const response = await fetch(new URL("./packages.zip", import.meta.url));
  if (!response.ok) throw new Error(`Could not download pdfsplitter (${response.status})`);
  const sitePackages = pyodide.runPython("import site; site.getsitepackages()[0]");
  pyodide.unpackArchive(await response.arrayBuffer(), "zip", { extractDir: sitePackages });
  pyodide.runPython("import importlib; importlib.invalidate_caches()");
  bridge = pyodide.pyimport("pdfsplitter.web");
  const version = pyodide.runPython("import pdfsplitter; pdfsplitter.__version__");
  const pypdf = pyodide.runPython("import pypdf; pypdf.__version__");
  postMessage({ type: "ready", defaults: JSON.parse(bridge.defaults()), version, pypdf,
                pyodide: pyodide.version });
}

function process() {
  scheduled = false;
  if (!bridge) return;
  while (jobs.length) {
    const job = jobs.shift();
    try {
      if (job.type === "read") {
        postMessage({ type: "read", id: job.id, response: bridge.read(job.data) });
      } else {
        const proxy = bridge.split(job.data, JSON.stringify(job.request));
        const data = proxy.toJs();
        proxy.destroy();
        postMessage({ type: "split", id: job.id, data }, [data.buffer]);
      }
    } catch (err) {
      postMessage({ type: job.type, id: job.id, error: pythonError(err) });
    }
  }
  if (!latest) return;
  const { id, request } = latest;
  latest = null;
  try {
    postMessage({ type: "plan", id, response: bridge.plan(JSON.stringify(request)) });
  } catch (err) {
    postMessage({ type: "plan", id, error: pythonError(err) });
  }
}

function pythonError(err) {
  const text = String(err && err.message || err);
  // Show the last line of a Python traceback, e.g., "ValueError: ..."
  const lines = text.trim().split("\n");
  return lines[lines.length - 1];
}

function schedule() {
  if (!scheduled) {
    scheduled = true;
    setTimeout(process, 0);
  }
}

self.onmessage = (event) => {
  if (event.data.type === "plan") latest = event.data;
  else if (event.data.type === "read" || event.data.type === "split") jobs.push(event.data);
  else return;
  schedule();
};

init().then(schedule, (err) => {
  postMessage({ type: "fatal", message: String(err && err.message || err) });
});
