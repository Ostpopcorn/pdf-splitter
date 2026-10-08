"""Build the web app into a folder that can be served as a static site, e.g.,
with GitHub Pages. The web app runs pdfsplitter in the browser with Pyodide,
and shows the pages with pdf.js. Pyodide and pdf.js are downloaded from npm,
pypdf from PyPI, and served with the app.

    python web/build.py                 # build into web/dist
    python web/build.py --serve         # build and serve on http://localhost:8000
    python web/build.py --out _site     # build into another folder
"""
import argparse
import base64
import functools
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import tarfile
import urllib.request
import zipfile

PYODIDE_VERSION = "314.0.7"
PYODIDE_FILES = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm",
                 "python_stdlib.zip", "pyodide-lock.json"]
PDFJS_VERSION = "6.3.289"
# The files of pdf.js that render the pages: the legacy build, which also
# runs in browsers that are not the latest, e.g., Safari, the fonts that a
# PDF may use without embedding them, the character maps of CJK fonts, and
# the decoders of JPEG 2000 and JBIG2 images and of ICC colors
PDFJS_FILES = re.compile(r"(LICENSE|legacy/build/pdf(\.worker)?\.min\.mjs"
                         r"|standard_fonts/.*|cmaps/.*|iccs/.*"
                         r"|wasm/(openjpeg\.wasm|jbig2\.wasm|qcms_bg\.wasm"
                         r"|LICENSE.*))$")
PYPDF_VERSION = "6.19.0"
PYPDF_SHA256 = "7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14"
STATIC_FILES = ["index.html", "style.css", "app.js", "worker.js", "favicon.svg"]
EXAMPLES = ["example.pdf"]

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(WEB_DIR)
PACKAGE_DIR = os.path.join(ROOT_DIR, "pdfsplitter")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "pdfsplitter-web")


def _cached(name, download):
    path = os.path.join(CACHE_DIR, name)
    if os.path.isfile(path):
        with open(path, "rb") as _file:
            return _file.read()
    data = download()
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "wb") as _file:
        _file.write(data)
    return data


def download_npm(package, version):
    """Return the npm package (.tgz), which is cached."""
    def download():
        url = "https://registry.npmjs.org/{}/{}".format(package, version)
        with urllib.request.urlopen(url) as response:
            dist = json.load(response)["dist"]
        print("Downloading", dist["tarball"])
        with urllib.request.urlopen(dist["tarball"]) as response:
            data = response.read()
        algorithm, digest = dist["integrity"].split("-", 1)
        if base64.b64encode(hashlib.new(algorithm, data).digest()).decode() != digest:
            raise RuntimeError("The download of {} is corrupted".format(package))
        return data
    return _cached("{}-{}.tgz".format(package, version), download)


def download_pypdf():
    """Return the wheel of pypdf, which is pure Python, and cached."""
    name = "pypdf-{}-py3-none-any.whl".format(PYPDF_VERSION)

    def download():
        url = "https://pypi.org/pypi/pypdf/{}/json".format(PYPDF_VERSION)
        with urllib.request.urlopen(url) as response:
            (wheel,) = [_url for _url in json.load(response)["urls"]
                        if _url["filename"] == name]
        print("Downloading", wheel["url"])
        with urllib.request.urlopen(wheel["url"]) as response:
            return response.read()
    data = _cached(name, download)
    if hashlib.sha256(data).hexdigest() != PYPDF_SHA256:
        raise RuntimeError("The download of pypdf is corrupted")
    return data


def copy_npm(out_dir, package, version, folder, wanted):
    """Copy the wanted files of an npm package into the folder, without the
    legacy/ of their names."""
    target = os.path.join(out_dir, folder)
    with tarfile.open(fileobj=io.BytesIO(download_npm(package, version))) as archive:
        for _member in archive.getmembers():
            name = _member.name[len("package/"):]
            if not _member.isfile() or not wanted(name):
                continue
            name = name[len("legacy/"):] if name.startswith("legacy/") else name
            path = os.path.join(target, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as _file:
                shutil.copyfileobj(archive.extractfile(_member), _file)


def get_version():
    with open(os.path.join(PACKAGE_DIR, "__init__.py"), encoding="utf-8") as _file:
        return re.search(r'__version__ = "(.*?)"', _file.read()).group(1)


def zip_packages(out_dir):
    """Zip pdfsplitter and pypdf, which are pure Python, so that the worker
    unpacks them into the site-packages of Pyodide. Return a hash of the
    zipped files, which is the version of the zip file."""
    files = {}
    for name in sorted(os.listdir(PACKAGE_DIR)):
        if name.endswith(".py"):
            with open(os.path.join(PACKAGE_DIR, name), "rb") as _file:
                files["pdfsplitter/" + name] = _file.read()
    with zipfile.ZipFile(io.BytesIO(download_pypdf())) as wheel:
        for _name in wheel.namelist():
            if _name.startswith("pypdf/"):
                files[_name] = wheel.read(_name)
            elif _name.endswith((".dist-info/METADATA", ".dist-info/LICENSE",
                                 "licenses/LICENSE")):
                files[_name] = wheel.read(_name)
    digest = hashlib.sha256()
    with zipfile.ZipFile(os.path.join(out_dir, "packages.zip"), "w",
                         zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
            digest.update(name.encode() + data)
    return digest.hexdigest()


def _versioned(text, link, content):
    """Add a hash of the content to a link in the text, e.g., app.js?v=1a2b,
    so that browsers load the new file after an update instead of an old
    cached one, which may not fit the new index.html."""
    version = hashlib.sha256(content.encode("utf-8")).hexdigest()[:10]
    if text.count(link) != 1:
        raise RuntimeError("Expected {} once to add its version".format(link))
    # the link ends with a quote, e.g., src="app.js"
    return text.replace(link, "{}?v={}{}".format(link[:-1], version, link[-1]))


def copy_static(out_dir, packages):
    files = {}
    for name in STATIC_FILES:
        with open(os.path.join(WEB_DIR, name), encoding="utf-8") as _file:
            files[name] = _file.read()
    files["worker.js"] = _versioned(files["worker.js"], '"./packages.zip"',
                                    packages)
    files["app.js"] = _versioned(files["app.js"], '"./worker.js"',
                                 files["worker.js"])
    for _link in ('"./pdfjs/build/pdf.min.mjs"', '"./pdfjs/build/pdf.worker.min.mjs"'):
        files["app.js"] = _versioned(files["app.js"], _link, PDFJS_VERSION)
    files["index.html"] = _versioned(files["index.html"], 'href="style.css"',
                                     files["style.css"])
    files["index.html"] = _versioned(files["index.html"], 'src="app.js"',
                                     files["app.js"])
    for name, content in files.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8",
                  newline="\n") as _file:
            _file.write(content)


def build(out_dir):
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    packages = zip_packages(out_dir)
    copy_static(out_dir, packages)
    shutil.copytree(os.path.join(WEB_DIR, "fonts"), os.path.join(out_dir, "fonts"))
    os.makedirs(os.path.join(out_dir, "examples"))
    for name in EXAMPLES:
        shutil.copy(os.path.join(ROOT_DIR, "examples", name),
                    os.path.join(out_dir, "examples"))
    copy_npm(out_dir, "pyodide", PYODIDE_VERSION, "pyodide",
             lambda name: name in PYODIDE_FILES)
    copy_npm(out_dir, "pdfjs-dist", PDFJS_VERSION, "pdfjs",
             lambda name: bool(PDFJS_FILES.match(name)))
    print("Built the web app with pdfsplitter {}, pypdf {}, and pdf.js {} in {}"
          .format(get_version(), PYPDF_VERSION, PDFJS_VERSION, out_dir))


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".mjs": "text/javascript", ".js": "text/javascript",
                      ".wasm": "application/wasm", ".pdf": "application/pdf"}


def serve(out_dir, port):
    handler = functools.partial(Handler, directory=out_dir)
    with http.server.ThreadingHTTPServer(("localhost", port), handler) as server:
        print("Serving the web app on http://localhost:{}".format(port))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(WEB_DIR, "dist"),
                        help="Output folder (default: web/dist)")
    parser.add_argument("--serve", nargs="?", type=int, const=8000,
                        metavar="PORT", help="Serve the web app after building")
    args = parser.parse_args()
    build(args.out)
    if args.serve:
        serve(args.out, args.serve)


if __name__ == "__main__":
    main()
