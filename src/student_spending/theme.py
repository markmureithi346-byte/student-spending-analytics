"""Shared visual language for the report and the interactive dashboard."""

from __future__ import annotations

BASE_CSS = """
:root {
  color-scheme: light;
  --ink: #241536;
  --muted: #6d6284;
  --line: #ece6f7;
  --accent: #6d28d9;
  --accent-2: #c026d3;
  --danger: #b42318;
  --danger-soft: #fff1f0;
  --success: #047857;
  --success-soft: #ecfdf5;
  --panel: rgba(255, 255, 255, 0.97);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; min-height: 100vh; padding: 30px 20px 72px;
  background: #140624; color: #f7f3ff;
  font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased;
}
.scene { position: fixed; inset: 0; z-index: -1; overflow: hidden;
         background: linear-gradient(155deg, #0f041d 0%, #250a47 48%, #150626 100%); }
.orb { position: absolute; border-radius: 50%; filter: blur(85px); opacity: .55;
       animation: drift 26s ease-in-out infinite alternate; }
.orb-a { width: 46vw; height: 46vw; top: -14vh; left: -10vw; background: #7c3aed; }
.orb-b { width: 38vw; height: 38vw; top: 6vh; right: -10vw; background: #d946ef;
         opacity: .38; animation-duration: 31s; animation-delay: -8s; }
.orb-c { width: 44vw; height: 44vw; bottom: -20vh; left: 26vw; background: #4f46e5;
         opacity: .45; animation-duration: 36s; animation-delay: -16s; }
@keyframes drift {
  0% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(3vw, 4vh, 0) scale(1.07); }
  100% { transform: translate3d(-4vw, -3vh, 0) scale(.95); }
}
.skip { position: absolute; left: -999px; top: 8px; background: #fff; color: var(--accent);
        padding: 8px 14px; border-radius: 8px; z-index: 100; }
.skip:focus { left: 16px; }
.shell { width: 100%; max-width: 1060px; margin: 0 auto; }
.hero { padding: 10px 6px 4px; }
.eyebrow { display: flex; align-items: center; gap: 8px; margin: 0 0 10px;
           font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
           color: #d8c4f7; font-weight: 600; }
.hero h1 { margin: 0 0 12px; font-size: clamp(34px, 5vw, 54px); line-height: 1.05;
           letter-spacing: -.035em; font-weight: 700; color: #fff; }
.hero h1 span { background: linear-gradient(100deg, #e9d5ff, #f0abfc 48%, #c4b5fd);
                -webkit-background-clip: text; background-clip: text; color: transparent; }
.lede { max-width: 720px; margin: 0 0 20px; font-size: 17px; color: #ded1f5; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 18px; padding: 0; list-style: none; }
.chips li { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px;
            border: 1px solid rgba(255,255,255,.18); border-radius: 999px;
            background: rgba(255,255,255,.08); color: #f3e8ff; font-size: 12.5px;
            backdrop-filter: blur(8px); }
.chip-key { color: #c4b0e6; text-transform: uppercase; letter-spacing: .08em;
            font-size: 10.5px; font-weight: 700; }
.chips code { background: rgba(255,255,255,.14); color: #fff;
              padding: 1px 6px; border-radius: 5px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: #34d399;
              display: inline-block; box-shadow: 0 0 0 3px rgba(52,211,153,.2); }
.status-dot.bad { background: #fb7185; box-shadow: 0 0 0 3px rgba(251,113,133,.2); }
.disclaimer { max-width: 820px; margin: 0 0 26px; padding: 12px 16px; border-radius: 12px;
              background: rgba(255, 251, 235, .94); border: 1px solid rgba(253, 230, 138, .85);
              color: #5b3a06; font-size: 13px; }
.disclaimer strong { color: #7c2d12; }
.toc { position: sticky; top: 12px; z-index: 30; display: flex; flex-wrap: wrap; gap: 4px;
       margin: 0 0 20px; padding: 7px; border-radius: 22px;
       background: rgba(19, 7, 36, .74); border: 1px solid rgba(255,255,255,.15);
       backdrop-filter: blur(18px); box-shadow: 0 18px 40px -22px rgba(0,0,0,.9); }
.toc a { flex: 0 0 auto; padding: 7px 13px; border-radius: 999px; color: #e7daf9;
         text-decoration: none; font-size: 13px; font-weight: 600;
         transition: background-color .15s ease, color .15s ease; }
.toc a:hover, .toc a:focus-visible { background: rgba(168, 85, 247, .3); color: #fff; outline: none; }
.panel { background: var(--panel); color: var(--ink); border-radius: 22px;
         padding: 26px 28px 28px; margin: 0 0 22px;
         border: 1px solid rgba(255,255,255,.75);
         box-shadow: 0 34px 70px -34px rgba(6, 1, 16, .85); scroll-margin-top: 86px; }
.panel .eyebrow { color: var(--accent); }
.panel .section-no { color: var(--accent-2); font-variant-numeric: tabular-nums; }
.panel h2 { margin: 0 0 6px; font-size: 24px; letter-spacing: -.02em; }
.panel h3 { margin: 26px 0 4px; font-size: 16px; letter-spacing: -.01em; }
.lead { margin: 0 0 18px; color: var(--muted); font-size: 14.5px; max-width: 78ch; }
.section-note { margin: 4px 0 12px; color: var(--muted); font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
         gap: 12px; margin: 18px 0 6px; }
.card { position: relative; padding: 15px 17px 16px; border-radius: 16px; overflow: hidden;
        background: linear-gradient(155deg, #fbf7ff, #f2e8ff 70%, #ece0ff);
        border: 1px solid #e6d6fb;
        transition: transform .18s ease, box-shadow .18s ease; }
.card::before { content: ""; position: absolute; inset: 0 0 auto; height: 3px;
                background: linear-gradient(90deg, #7c3aed, #d946ef); opacity: .85; }
.card:hover { transform: translateY(-2px);
              box-shadow: 0 12px 24px -14px rgba(109, 40, 217, .5); }
.card .label { font-size: 11px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .07em; color: #7c3aed; }
.card .value { margin-top: 5px; font-size: clamp(19px, 2vw, 23px); font-weight: 700;
               color: #2e1065; white-space: nowrap; font-variant-numeric: tabular-nums;
               letter-spacing: -.02em; }
.card .hint { margin-top: 2px; font-size: 12px; color: #6d6284; }
.headline { margin: 16px 0 4px; font-size: 15px; color: #3f2b5c; }
.headline strong { color: var(--accent); }
.banner { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;
          margin: 6px 0 16px; padding: 12px 15px; border-radius: 12px; font-size: 13.5px; }
.banner strong { font-weight: 700; }
.banner.good { background: var(--success-soft); border: 1px solid #a7f3d0; color: #065f46; }
.banner.bad { background: var(--danger-soft); border: 1px solid #fecaca; color: #912018; }
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px;
              background: #fff; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 520px; }
th, td { padding: 10px 13px; text-align: left; border-bottom: 1px solid var(--line);
         vertical-align: top; }
thead th { background: #f7f2ff; color: #5b4a7a; font-size: 11.5px; text-transform: uppercase;
           letter-spacing: .06em; font-weight: 700; white-space: nowrap; }
tbody tr:nth-child(even) { background: #fcfaff; }
tbody tr:hover { background: #f6edff; }
tbody tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.alert td { background: var(--danger-soft); color: #7a271a; }
tr.alert:hover td { background: #ffe4e0; }
tr.over td { background: #fff8f6; color: #5f2a22; }
tr.over:hover td { background: #ffefeb; }
tr.over td:last-child { color: var(--danger); font-weight: 700; }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px;
        font-size: 11.5px; font-weight: 700; letter-spacing: .03em; }
.pass { background: var(--success-soft); color: var(--success); }
.fail { background: var(--danger-soft); color: var(--danger); }
.panel code { background: #f3edfb; color: #5b21b6; padding: 2px 7px;
              border-radius: 5px; font-size: 12.5px; }
.panel table code { white-space: nowrap; }
.share { display: inline-flex; align-items: center; gap: 8px; justify-content: flex-end; }
.share-track { width: 64px; height: 6px; border-radius: 999px;
               background: #eee5fa; overflow: hidden; }
.share-fill { display: block; height: 100%; border-radius: inherit;
              background: linear-gradient(90deg, #7c3aed, #d946ef); }
.share-value { min-width: 42px; text-align: right; font-variant-numeric: tabular-nums; }
.chart-wrap { overflow-x: auto; margin-bottom: 14px; border-radius: 14px; }
.chart-hint { display: none; }
.chart { display: block; width: 100%; height: auto; background: #fff;
         border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; }
.chart text { font-family: inherit; font-size: 12px; fill: #4c3a66; }
.chart .bar-label { fill: #4c3a66; }
.chart .bar-value { fill: #7c6a9a; font-variant-numeric: tabular-nums; }
.chart .guide { stroke: #ece6f7; stroke-width: 1; }
footer.footer { margin: 4px 0 0; }
.footer p { margin: 0 0 8px; color: var(--muted); font-size: 13px; }
.footer strong { color: var(--ink); }
.footer .meta-line { font-size: 12px; }
.totop { display: inline-flex; margin-top: 6px; color: var(--accent);
         font-weight: 600; font-size: 13px; text-decoration: none; }
.totop:hover { text-decoration: underline; }
.panel:target { outline: 3px solid rgba(168, 85, 247, .45); outline-offset: 3px; }
@media (max-width: 900px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  body { padding: 18px 12px 48px; }
  .hero { padding: 6px 4px 0; }
  .lede { font-size: 15.5px; }
  .panel { padding: 20px 16px 22px; border-radius: 18px; scroll-margin-top: 118px; }
  .panel h2 { font-size: 21px; }
  .card .value { font-size: 19px; }
  .chart { min-width: 540px; }
  .chart-hint { display: block; margin: -4px 0 8px; color: var(--muted); font-size: 11.5px; }
  .toc { top: 8px; border-radius: 18px; gap: 2px; padding: 6px; }
  .toc a { padding: 6px 9px; font-size: 12px; }
  .table-wrap { border: 0; background: transparent; overflow: visible; }
  table { display: block; min-width: 0; font-size: 13.5px; }
  thead { display: none; }
  tbody { display: block; }
  tbody tr { display: block; margin: 0 0 10px; overflow: hidden;
             border: 1px solid var(--line); border-radius: 12px; background: #fff; }
  tbody tr:nth-child(even) { background: #fcfaff; }
  tbody tr:hover { background: inherit; }
  td { display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
       padding: 7px 12px; border-bottom: 1px solid #f3eefb; text-align: right;
       white-space: normal; }
  td:last-child { border-bottom: 0; }
  td::before { content: attr(data-label); flex: 0 0 40%; text-align: left;
               font-size: 10.5px; font-weight: 700; text-transform: uppercase;
               letter-spacing: .06em; color: var(--muted); }
  td.num { white-space: normal; }
  td:has(code) { display: block; text-align: left; }
  td:has(code)::before { display: block; margin-bottom: 3px; }
  .panel table code { white-space: nowrap; font-size: 11px; }
  tr.alert td, tr.over td { background: transparent; }
  tr.alert { background: var(--danger-soft); }
  tr.over { background: #fff8f6; }
  tr.over td:last-child { font-weight: 700; }
  tr.alert:hover td, tr.over:hover td { background: transparent; }
  .share { justify-content: flex-end; }
}
@media (max-width: 380px) {
  .cards { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .orb { animation: none; }
  .card { transition: none; }
}
@media print {
  body { background: #fff; color: #000; padding: 0; }
  .scene, .toc, .skip, .totop { display: none !important; }
  .hero h1, .hero h1 span { color: #2e1065; -webkit-text-fill-color: #2e1065;
                            background: none; }
  .lede, .eyebrow, .chips li { color: #333; }
  .chips li { background: #f5f5f5; border-color: #ddd; }
  .chips code { color: #000; }
  .disclaimer { background: #fff; border-color: #ccc; color: #000; }
  .panel { box-shadow: none; border: 1px solid #ddd; break-inside: avoid; }
  .panel, .card, .table-wrap, .chart { background: #fff; }
  .card .value, .card .label, .card .hint, .headline, .headline strong { color: #000; }
  .banner.good, .banner.bad { background: #fff; color: #000; border-color: #ccc; }
  tr.alert td { background: #fff; }
  a { color: #000; text-decoration: none; }
}
"""
