"""Generates docs/images/architecture-{dark,light}.svg (animated, GitHub light/dark aware).

Icons are official assets, embedded unmodified (only brand logos get a fill colour):
  * Google Cloud + Firebase + Next.js + FastAPI icons from the `diagrams` package (docs/diagrams/icons/*.png)
  * YouTube, OpenRouter, dev.to, LangChain logos from Simple Icons (CC0) (docs/diagrams/icons/*.svg)

Run:  python docs/diagrams/architecture.py      (stdlib only)
"""

import base64
import html
from pathlib import Path

HERE = Path(__file__).parent
ICONS = HERE / "icons"
OUT = HERE.parent / "images"

W, H = 1920, 1130
CW, CH = 224, 86  # card size

THEMES = {
    "dark": dict(bg1="#0a0e16", bg2="#0f1624", dot="#1a2232", card="#131a27", card_stroke="#253047",
                 text="#e8eef6", muted="#8d9aae", pill="#0b1019", frame="#4285F4", zone_alpha="0.07",
                 tile="#ffffff", shadow="0.55"),
    "light": dict(bg1="#f8fafd", bg2="#eef2f8", dot="#dde3ed", card="#ffffff", card_stroke="#dbe2ec",
                  text="#1d2430", muted="#5d6878", pill="#ffffff", frame="#4285F4", zone_alpha="0.05",
                  tile="#f3f5f9", shadow="0.12"),
}

C = dict(indigo="#7c7cf0", orange="#ff9a3c", purple="#a970ff", green="#2fbf71", red="#f0524a", pink="#ff4f9a",
         yellow="#fbbc04", blue="#4285F4", grey="#8d9aae")

BRAND_FILL = {"youtube": "#FF0033", "openrouter": "#111827", "devdotto": "#0A0A0A", "langchain": "#1C3C3C"}


def icon_uri(name: str) -> str:
    png = ICONS / f"{name}.png"
    if png.exists():
        return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    svg = svg.replace("<svg ", f'<svg fill="{BRAND_FILL.get(name, "#111")}" ', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


class Canvas:
    def __init__(self, t: dict):
        self.t = t
        self.layers: dict[str, list[str]] = {"zones": [], "edges": [], "cards": [], "labels": [], "top": []}

    # ---- primitives -------------------------------------------------------------------------
    def zone(self, x, y, w, h, title, color, dashed=False, sub=""):
        t = self.t
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        self.layers["zones"].append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{color}" fill-opacity="{t["zone_alpha"]}" '
            f'stroke="{color}" stroke-opacity="0.85" stroke-width="1.6"{dash}/>'
            f'<circle cx="{x + 20}" cy="{y + 22}" r="5" fill="{color}"/>'
            f'<text x="{x + 33}" y="{y + 27}" class="zt" fill="{color}">{html.escape(title)}</text>'
            + (f'<text x="{x + w - 16}" y="{y + 27}" class="zs" text-anchor="end">{html.escape(sub)}</text>' if sub else "")
        )

    def card(self, key, x, y, title, lines, icon, badge=None):
        t = self.t
        self.boxes[key] = (x, y, CW, CH)
        sub = "".join(f'<text x="{x + 84}" y="{y + 54 + i * 15}" class="cs">{html.escape(s)}</text>' for i, s in enumerate(lines))
        b = ""
        if badge:
            bw = 9 + 6.6 * len(badge)
            b = (f'<rect x="{x + CW - bw - 8}" y="{y - 11}" width="{bw}" height="22" rx="11" fill="{badge[1] if isinstance(badge, tuple) else C["yellow"]}"/>'
                 if False else "")
        self.layers["cards"].append(
            f'<g filter="url(#shadow)"><rect x="{x}" y="{y}" width="{CW}" height="{CH}" rx="14" fill="{t["card"]}" '
            f'stroke="{t["card_stroke"]}" stroke-width="1.2"/></g>'
            f'<rect x="{x + 14}" y="{y + 15}" width="56" height="56" rx="12" fill="{t["tile"]}"/>'
            f'<image href="{icon_uri(icon)}" x="{x + 20}" y="{y + 21}" width="44" height="44" preserveAspectRatio="xMidYMid meet"/>'
            f'<text x="{x + 84}" y="{y + 34}" class="ct">{html.escape(title)}</text>{sub}{b}'
        )

    def pill(self, x, y, text, color, step=None):
        t = self.t
        label = html.escape(text)
        w = 14 + 6.5 * len(text) + (22 if step else 0)
        cx = x - w / 2
        s = ""
        if step:
            s = (f'<circle cx="{cx + 12}" cy="{y}" r="9" fill="{color}"/>'
                 f'<text x="{cx + 12}" y="{y + 4}" class="sn" text-anchor="middle">{step}</text>')
        self.layers["labels"].append(
            f'<rect x="{cx}" y="{y - 11}" width="{w}" height="22" rx="11" fill="{t["pill"]}" stroke="{color}" '
            f'stroke-opacity="0.7"/>{s}<text x="{cx + (26 if step else 7)}" y="{y + 4}" class="el" fill="{color}">{label}</text>'
        )

    def path(self, d, color, label=None, at=None, step=None, dashed=False, flow=True, width=2.2):
        marker = f'url(#arr-{color.strip("#")})'
        if dashed:
            self.layers["edges"].append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="6 6" '
                f'stroke-linecap="round" marker-end="{marker}" opacity="0.95"/>')
        else:
            self.layers["edges"].append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-opacity="0.28" marker-end="{marker}"/>')
            if flow:
                self.layers["edges"].append(
                    f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" class="flow" stroke-linecap="round"/>')
        if label and at:
            self.pill(at[0], at[1], label, color, step)

    # ---- anchors & curves ------------------------------------------------------------------
    def a(self, key, side, dy=0, dx=0):
        x, y, w, h = self.boxes[key]
        return {"L": (x, y + h / 2 + dy), "R": (x + w, y + h / 2 + dy), "T": (x + w / 2 + dx, y), "B": (x + w / 2 + dx, y + h)}[side]

    def curve(self, p0, p3, color, label=None, step=None, vertical=False, dashed=False, t=0.5):
        (x0, y0), (x3, y3) = p0, p3
        if vertical:
            dy = (y3 - y0) / 2
            p1, p2 = (x0, y0 + dy), (x3, y3 - dy)
        else:
            dx = max(abs(x3 - x0) / 2, 40)
            p1, p2 = (x0 + dx, y0), (x3 - dx, y3)
        d = f"M{x0:.1f},{y0:.1f} C{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {x3 - (0 if vertical else 6):.1f},{y3 - (6 if vertical else 0):.1f}"
        mt = 1 - t
        mx = mt**3 * x0 + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * x3
        my = mt**3 * y0 + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * y3
        self.path(d, color, label, (mx, my), step, dashed)

    def render(self) -> str:
        t = self.t
        markers = "".join(
            f'<marker id="arr-{c.strip("#")}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for c in set(C.values()))
        style = f"""
            .tt {{ font: 700 30px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; fill: {t["text"]}; letter-spacing: -0.3px }}
            .ts {{ font: 400 15px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; fill: {t["muted"]} }}
            .zt {{ font: 700 14px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; letter-spacing: 0.2px }}
            .zs {{ font: 500 11.5px Consolas, 'SF Mono', Menlo, monospace; fill: {t["muted"]} }}
            .ct {{ font: 650 14.5px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; fill: {t["text"]} }}
            .cs {{ font: 400 11.5px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; fill: {t["muted"]} }}
            .el {{ font: 600 11.5px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif }}
            .sn {{ font: 700 11px 'Segoe UI', Arial, sans-serif; fill: #fff }}
            .lg {{ font: 500 12.5px 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; fill: {t["muted"]} }}
            .flow {{ stroke-dasharray: 7 11; animation: flow 1.1s linear infinite }}
            @keyframes flow {{ to {{ stroke-dashoffset: -36 }} }}
            .pulse {{ animation: pulse 2.4s ease-in-out infinite }}
            @keyframes pulse {{ 0%,100% {{ opacity: .35 }} 50% {{ opacity: .9 }} }}
            @media (prefers-reduced-motion: reduce) {{ .flow, .pulse {{ animation: none }} }}
        """
        defs = f"""<defs>
            <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{t["bg1"]}"/><stop offset="1" stop-color="{t["bg2"]}"/></linearGradient>
            <pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.3" fill="{t["dot"]}"/></pattern>
            <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" flood-opacity="{t["shadow"]}"/></filter>
            <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter>
            {markers}</defs>"""
        body = "".join("".join(self.layers[k]) for k in ("zones", "edges", "cards", "labels", "top"))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
                f'aria-label="Tube2Dev architecture on Google Cloud"><style>{style}</style>{defs}'
                f'<rect width="{W}" height="{H}" fill="url(#bg)"/><rect width="{W}" height="{H}" fill="url(#dots)"/>{body}</svg>')


def build(theme: str) -> str:
    cv = Canvas(THEMES[theme])
    cv.boxes = {}
    t = cv.t

    # title
    cv.layers["top"].append(
        f'<text x="40" y="62" class="tt">Tube2Dev <tspan fill="{C["blue"]}">·</tspan> architecture</text>'
        f'<text x="40" y="90" class="ts">YouTube → LangGraph → dev.to, with a human in the loop  ·  Google Cloud, us-east1  ·  everything authenticates with ADC, no key files</text>')

    # ---- zones ----
    cv.zone(300, 120, 1300, 830, "Google Cloud  ·  us-east1", C["blue"], sub="project · ADC · least-privilege service accounts")
    cv.zone(325, 250, 274, 400, "Cloud Run · services", C["blue"], dashed=True)
    cv.zone(625, 160, 274, 560, "Async", C["orange"], dashed=True)
    cv.zone(925, 250, 274, 400, "tube2dev-worker", C["purple"], dashed=True, sub="Cloud Run")
    cv.zone(1225, 160, 350, 450, "Data", C["green"], dashed=True)
    cv.zone(1240, 200, 320, 248, "Cloud SQL · PostgreSQL 16", C["green"], dashed=True)
    cv.zone(1225, 640, 350, 250, "Secrets & keys", C["red"], dashed=True)
    cv.zone(325, 760, 874, 160, "Build & observe", C["grey"], dashed=True)
    cv.zone(24, 560, 254, 160, "Firebase", C["yellow"], dashed=True)
    cv.zone(1640, 230, 264, 430, "External APIs", C["pink"])

    # glow behind the pipeline card (the heart of the system)
    cv.layers["zones"].append(f'<ellipse cx="1062" cy="543" rx="150" ry="70" fill="{C["purple"]}" opacity="0.35" filter="url(#glow)" class="pulse"/>')

    # ---- cards ----
    cv.card("you", 40, 330, "You", ["browser · any device"], "users")
    cv.card("auth", 40, 610, "Firebase Auth", ["Google · email link", "ID tokens"], "firebase-auth")
    cv.card("web", 350, 300, "tube2dev-web", ["Next.js 15 · React 19", "review editor · live UI"], "nextjs")
    cv.card("api", 350, 500, "tube2dev-api", ["FastAPI · REST + SSE", "LISTEN/NOTIFY → events"], "fastapi")
    cv.card("sched", 650, 200, "Cloud Scheduler", ["daily 04:15 UTC"], "cloud-scheduler")
    cv.card("jobs", 650, 330, "Cloud Run jobs", ["migrate · cleanup", "→ Cloud SQL / GCS"], "cloud-run")
    cv.card("tasks", 650, 520, "Cloud Tasks", ["queue: graph-runs", "deduped · retried"], "cloud-tasks")
    cv.card("worker", 950, 300, "FastAPI worker", ["/internal/run-job", "advisory lock per job"], "cloud-run")
    cv.card("graph", 950, 500, "LangGraph pipeline", ["11 nodes · checkpointed", "⏸ 2 human approvals"], "langchain")
    cv.card("appdb", 1260, 240, "tube2dev_app", ["jobs · events · usage", "checkpoints + store"], "cloud-sql")
    cv.card("creddb", 1260, 345, "tube2dev_credentials", ["user API keys", "KMS ciphertext only"], "cloud-sql")
    cv.card("gcs", 1260, 500, "Cloud Storage", ["transcripts · drafts", "content-addressed"], "gcs")
    cv.card("kms", 1260, 690, "Cloud KMS", ["user-api-keys", "AAD = user:provider"], "kms")
    cv.card("sm", 1260, 790, "Secret Manager", ["YouTube proxy creds"], "secret-manager")
    cv.card("build", 350, 805, "Cloud Build", ["build · test · migrate", "deploy (sa-build)"], "cloud-build")
    cv.card("logs", 650, 805, "Cloud Logging", ["JSON · trace ids", "+ browser logs"], "logging")
    cv.card("mon", 950, 805, "Monitoring", ["uptime · alerts"], "monitoring")
    cv.card("yt", 1660, 280, "YouTube", ["metadata · transcript", "via residential proxy"], "youtube")
    cv.card("llm", 1660, 400, "OpenRouter", ["your key · any model", "budget-capped"], "openrouter")
    cv.card("dev", 1660, 520, "dev.to", ["your key · draft/public", "idempotent publish"], "devdotto")

    # ---- edges: main flow (numbered) ----
    cv.curve(cv.a("you", "R"), cv.a("web", "L"), C["indigo"], "HTTPS", step=1)
    cv.curve(cv.a("you", "B"), cv.a("auth", "T"), C["yellow"], "sign in", step=2, vertical=True, dashed=True)
    cv.curve(cv.a("web", "B"), cv.a("api", "T"), C["indigo"], "REST + SSE", step=3, vertical=True)
    cv.curve(cv.a("api", "R"), cv.a("tasks", "L"), C["orange"], "enqueue", step=4)
    cv.curve(cv.a("tasks", "R"), cv.a("worker", "L"), C["orange"], "OIDC push", step=5, t=0.62)
    cv.curve(cv.a("worker", "B"), cv.a("graph", "T"), C["purple"], "astream()", step=6, vertical=True)
    cv.curve(cv.a("graph", "R", -18), cv.a("appdb", "L"), C["green"], "checkpoints", step=8, t=0.55)
    cv.curve(cv.a("graph", "R", 8), cv.a("gcs", "L"), C["green"], "gs:// refs", t=0.5)
    cv.curve(cv.a("worker", "R"), cv.a("creddb", "L"), C["green"], "decrypt keys", t=0.45)
    cv.curve(cv.a("sched", "B"), cv.a("jobs", "T"), C["orange"], "cron", vertical=True)
    cv.curve(cv.a("graph", "B", dx=40), cv.a("kms", "L"), C["red"], "decrypt", dashed=True, t=0.62)
    cv.curve(cv.a("graph", "B", dx=-40), cv.a("sm", "L"), C["red"], "proxy creds", dashed=True, t=0.7)

    # external "bus": the pipeline leaves GCP through the gap between Data and Secrets
    gx, gy = 1170, 543 + 24
    for i, (key, label, lx) in enumerate([("yt", "transcript", 1628), ("llm", "LLM calls", 1628), ("dev", "publish", 1628)]):
        off = i * 7
        tx, ty = cv.a(key, "L")
        bx = 1606 + off
        d = (f"M{gx},{gy + off} L{1205},{gy + off} Q1215,{gy + off} 1215,{gy + off + 10} L1215,{615 + off} "
             f"Q1215,{625 + off} 1225,{625 + off} L{bx - 10},{625 + off} Q{bx},{625 + off} {bx},{615 + off} "
             f"L{bx},{ty + 10} Q{bx},{ty} {bx + 10},{ty} L{tx - 6},{ty}")
        cv.path(d, C["pink"])
    cv.pill(1410, 625 + 7, "transcript · LLM calls · publish", C["pink"], step=7)

    # api -> KMS (encrypt on save), routed under the worker zone
    d = "M460,586 L460,694 Q460,704 470,704 L1205,704 Q1215,704 1215,714 L1215,723 Q1215,733 1225,733 L1254,733"
    cv.path(d, C["red"], "encrypt keys on save", (800, 704), dashed=True)
    # ops
    cv.curve(cv.a("build", "T"), (462, 652), C["grey"], "deploy", vertical=True, dashed=True)
    cv.curve(cv.a("logs", "R"), cv.a("mon", "L"), C["grey"], dashed=True)

    # ---- legend ----
    lx, ly = 40, 990
    items = [(C["indigo"], "user traffic", False), (C["orange"], "async execution", False), (C["purple"], "pipeline", False),
             (C["green"], "data", False), (C["red"], "secrets & keys", True), (C["pink"], "external APIs", False),
             (C["yellow"], "auth", True), (C["grey"], "build & ops", True)]
    leg = [f'<text x="{lx}" y="{ly}" class="zt" fill="{t["text"]}">Legend</text>']
    for i, (c, name, dashed) in enumerate(items):
        x = lx + 90 + i * 175
        dash = ' stroke-dasharray="6 6"' if dashed else ""
        leg.append(f'<line x1="{x}" y1="{ly - 5}" x2="{x + 38}" y2="{ly - 5}" stroke="{c}" stroke-width="3"{dash} stroke-linecap="round"/>'
                   f'<text x="{x + 48}" y="{ly}" class="lg">{html.escape(name)}</text>')
    leg.append(f'<text x="{lx}" y="{ly + 36}" class="lg">① sign-in &amp; app traffic  →  ④ API enqueues a graph segment  →  ⑤ Cloud Tasks pushes it to the worker  →  '
               f'⑥ LangGraph runs until the next human approval  →  ⑦ YouTube · LLMs · dev.to  →  ⑧ state checkpointed to Cloud SQL, text to GCS  →  events stream back over SSE</text>')
    leg.append(f'<text x="{lx}" y="{ly + 62}" class="lg">Icons: Google Cloud &amp; Firebase official icons (via mingrammer/diagrams), Next.js, FastAPI; brand logos from Simple Icons (CC0).</text>')
    cv.layers["top"].append("".join(leg))
    return cv.render()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        p = OUT / f"architecture-{theme}.svg"
        p.write_text(build(theme), encoding="utf-8")
        print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
